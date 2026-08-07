from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "traigent-first-run"
SKILL = SKILL_ROOT / "SKILL.md"
REQUIREMENTS = SKILL_ROOT / "assets" / "requirements-first-run.txt"


def pinned_sdk_version() -> str:
    """The `traigent` release `requirements-first-run.txt` actually installs.

    Read, never restated. Any document that names the pinned release - the
    license disclosure, its two license links, the telemetry contract link -
    derives it from here, so bumping the pin cannot leave a disclosure
    pointing at the terms of a release nobody installs.
    """
    for line in REQUIREMENTS.read_text().splitlines():
        name, separator, version = line.strip().partition("==")
        if name == "traigent" and separator and version:
            return version
    raise AssertionError(
        f"{REQUIREMENTS.relative_to(ROOT)} pins no `traigent==` release; "
        "every disclosure that names the installed version reads it from here"
    )


def assistant_facing_documents() -> list[Path]:
    """Every document the assistant reads while running the guide.

    Defined once because it was defined three times: two other corpora in this
    file each rebuilt the list and each omitted GUIDE.md, so a rule stated
    there was outside what any of them checked. That is the same defect the
    guidance checks below exist to catch, in the checks themselves - and the
    same rule CLAUDE.md now states for the guidance applies to this list: one
    decision, one home.
    """
    return [
        ROOT / "GUIDE.md",
        SKILL,
        *sorted((SKILL_ROOT / "references").glob("*.md")),
        *sorted((SKILL_ROOT / "assets").glob("*.md")),
    ]


GUIDANCE_BUDGET_LEDGER = Path(__file__).resolve().parent / "guidance_budget"
BUDGET_ENTRY_NAME = re.compile(r"^(\d{4})-[a-z0-9][a-z0-9-]*\.md$")
BUDGET_FIGURE = re.compile(
    r"^(resident|total)-(ceiling|measured): (\d[\d_]*)$", re.MULTILINE
)
BUDGET_FOLLOWS = re.compile(r"^follows: (\d{4})$", re.MULTILINE)
# A raise is a decision, so an entry that states a number and not a reason is
# the thing this ledger exists to refuse. The floor is not a guess: the
# shortest reason anyone has written across the nine raises in
# 0001-inherited-ledger.md is 259 characters, so 240 refuses a label without
# refusing a short argument.
BUDGET_REASON_FLOOR = 240
# A character count alone is satisfied by 240 characters of one repeated word,
# which is a label padded to length rather than an argument. Distinct words are
# the cheap second half: that same shortest inherited reason uses 30 of them, so
# 24 refuses padding with the same margin the character floor keeps. Neither
# number can tell a bad argument from a good one - both refuse only the entry
# that did not try.
BUDGET_REASON_DISTINCT_WORDS = 24
# Both floors above measure a reason against itself, and the cheapest way past
# any such floor is to copy one that already passed. That is not hypothetical
# padding: it is the single likeliest thing an author does when a length gate
# stands between them and a green suite, and this ledger ships nine ready-made
# reasons in `0001-inherited-ledger.md` for them to copy. So an entry is also
# measured against every other entry.
#
# Overlap is counted in five-word shingles rather than in words. Two honest
# entries about this package share a great deal of vocabulary - "measured",
# "ceiling", "run-safety.md", "merged package" - and a word-overlap score reads
# that as plagiarism. Five consecutive words in common is not vocabulary; it is
# the same sentence. Containment, not similarity: a reason is refused when most
# of ITS shingles appear in another entry, so pasting one paragraph out of the
# long inherited entry is caught even though it is a small part of that entry.
BUDGET_REASON_SHINGLE = 5
# 0.4 rather than a near-1 threshold, so that "copied and reworded" is refused
# along with "copied", and the boundary is probed from below rather than picked.
# Measured over the six independent reasons in `GuidanceBudgetLedgerRulesTests`
# and the committed root entry: verbatim copy 1.00, one paragraph lifted out of
# the long root entry 1.00, a copy with one verb swapped and the closing
# sentence rewritten 0.81 - against 0.14 for the highest an honestly written
# reason scores against the root, and 0.00 among the six themselves. 0.4 sits in
# the middle of a gap that wide, so neither floor nor ceiling of it is load
# bearing; re-measure rather than nudge if that ever stops being true.
BUDGET_REASON_BORROWED = 0.4


def _shingles(reason: str) -> set[tuple[str, ...]]:
    """Every run of `BUDGET_REASON_SHINGLE` consecutive words, lowercased."""
    words = re.findall(r"[a-z0-9_.#-]+", reason.casefold())
    return {
        tuple(words[i : i + BUDGET_REASON_SHINGLE])
        for i in range(len(words) - BUDGET_REASON_SHINGLE + 1)
    }


def guidance_budget_reason_overlap(reason: str, other: str) -> float:
    """How much of `reason` is already written in `other`, from 0 to 1."""
    mine = _shingles(reason)
    if not mine:
        return 0.0
    return len(mine & _shingles(other)) / len(mine)


def guidance_budget_entries(
    directory: Path = GUIDANCE_BUDGET_LEDGER,
) -> list[SimpleNamespace]:
    """Every raise of a guidance ceiling, one file each, read from `directory`.

    An entry states the ledger state it was measured on top of (`follows:`),
    the ceiling it puts in force, the figure it measured, and why. The
    directory is a parameter so the rules below can be exercised against
    invented ledgers rather than only against the one that is committed.

    `tests/guidance_budget/README.md` states the format for whoever adds the
    next one.
    """
    entries: list[SimpleNamespace] = []
    for path in sorted(directory.glob("*.md")):
        if path.name == "README.md":
            continue
        name = BUDGET_ENTRY_NAME.match(path.name)
        text = path.read_text(encoding="utf-8")
        figures: dict[str, dict[str, int]] = {"ceiling": {}, "measured": {}}
        # Counted as well as collected. A second `follows:` line is refused
        # below, and a second `total-ceiling:` line used to be the odd one out:
        # the loop simply overwrote, so the LAST spelling of the number silently
        # governed and the other one sat in the file looking authoritative.
        # Whichever way a duplicate arrives - a bad merge resolution, an author
        # editing the figure by adding a line instead of changing one - the
        # entry no longer says one thing, and that is the same defect in both
        # fields.
        stated: dict[tuple[str, str], int] = {}
        for which, kind, value in BUDGET_FIGURE.findall(text):
            stated[(kind, which)] = stated.get((kind, which), 0) + 1
            figures[kind][which] = int(value.replace("_", ""))
        follows = BUDGET_FOLLOWS.findall(text)
        reason = BUDGET_FOLLOWS.sub("", BUDGET_FIGURE.sub("", text))
        # The heading is the entry's name, not its argument.
        reason = re.sub(r"^#.*$", "", reason, flags=re.MULTILINE)
        entries.append(
            SimpleNamespace(
                path=path,
                index=int(name.group(1)) if name else None,
                ceilings=figures["ceiling"],
                measured=figures["measured"],
                follows=int(follows[0]) if len(follows) == 1 else None,
                follows_count=len(follows),
                restated=sorted(
                    f"{which}-{kind}" for (kind, which), n in stated.items() if n > 1
                ),
                reason=reason.strip(),
            )
        )
    return sorted(entries, key=lambda entry: (entry.index is None, entry.index))


def guidance_budget_reason_defect(reason: str) -> str | None:
    """Why this reason is not an argument, or None if it may be one."""
    if len(reason) < BUDGET_REASON_FLOOR:
        return f"{len(reason)} characters, under the {BUDGET_REASON_FLOOR} floor"
    distinct = len(set(re.findall(r"[a-z]{2,}", reason.casefold())))
    if distinct < BUDGET_REASON_DISTINCT_WORDS:
        return (
            f"{distinct} distinct words, under the "
            f"{BUDGET_REASON_DISTINCT_WORDS} floor - long enough only because "
            "it repeats itself"
        )
    return None


def guidance_budget_defects(entries: list[SimpleNamespace]) -> list[str]:
    """Every way this ledger fails to be a single chain of measured raises.

    Returned in stages, and the first stage with anything to say is the last
    one that runs: a ledger whose entries are not identifiable cannot be
    checked for what they point at.
    """
    if not entries:
        return ["the guidance budget ledger is empty"]

    naming = [
        f"{entry.path.name} is not named NNNN-slug.md, so it has no place in "
        "the order and cannot be told apart from the entry a concurrent branch "
        "added"
        for entry in entries
        if entry.index is None
    ]
    indexes = [entry.index for entry in entries if entry.index is not None]
    naming += [
        f"two budget ledger entries share the number {index:04d}; give each "
        "entry its own number and state which one the later follows"
        for index in sorted({i for i in indexes if indexes.count(i) > 1})
    ]
    if naming:
        return naming

    by_index = {entry.index: entry for entry in entries}
    content: list[str] = []
    for entry in entries:
        if not entry.ceilings:
            content.append(
                f"{entry.path.name} declares no ceiling; an entry that raises "
                "nothing is a note, and notes belong in the raise they explain"
            )
        for field in entry.restated:
            content.append(
                f"{entry.path.name} states {field}: more than once. The last "
                "one silently governs and the others sit in the file looking "
                "authoritative; an entry declares each figure exactly once."
            )
        defect = guidance_budget_reason_defect(entry.reason)
        if defect is not None:
            content.append(
                f"{entry.path.name} states a number without a reason ({defect}). "
                "What the ceiling buys, what it replaces, and the measured "
                "figure are the whole point of raising it deliberately."
            )
        else:
            # Only when the intrinsic floors pass, because "too short" and
            # "not yours" are different things to be told, and a short copy
            # should hear the simpler one first.
            for other in entries:
                if other is entry:
                    continue
                overlap = guidance_budget_reason_overlap(entry.reason, other.reason)
                if overlap >= BUDGET_REASON_BORROWED:
                    content.append(
                        f"{entry.path.name}'s reason is {overlap:.0%} "
                        f"{other.path.name}'s, in five-word runs. Copying a "
                        "reason that already passed is the cheapest way over a "
                        "length floor and says nothing about THIS raise: what "
                        "these bytes buy, what they replace, and what was "
                        "measured."
                    )
                    break
        for which, ceiling in sorted(entry.ceilings.items()):
            if which not in entry.measured:
                content.append(
                    f"{entry.path.name} declares {which}-ceiling but no "
                    f"{which}-measured; a ceiling nobody measured against is a "
                    "number, and the next merge has nothing to compare with"
                )
            elif entry.measured[which] >= ceiling:
                content.append(
                    f"{entry.path.name} measured {which} at "
                    f"{entry.measured[which]} against its own "
                    f"{which}-ceiling of {ceiling}; a ceiling at or below the "
                    "measurement is already breached"
                )
        for which in sorted(set(entry.measured) - set(entry.ceilings)):
            content.append(
                f"{entry.path.name} declares {which}-measured but no "
                f"{which}-ceiling; state the ceiling this measurement buys, or "
                "drop the measurement"
            )
        if entry.follows_count > 1:
            content.append(
                f"{entry.path.name} declares follows: more than once; an entry "
                "is measured on top of exactly one ledger state"
            )
        elif entry.follows is not None and entry.follows not in by_index:
            content.append(
                f"{entry.path.name} follows {entry.follows:04d}, which is not "
                "in this tree. An entry can only follow a state it actually "
                "has: measure on top of an entry that exists here, and say so."
            )
        elif entry.follows is not None and entry.follows >= entry.index:
            content.append(
                f"{entry.path.name} follows {entry.follows:04d}, which is not "
                "lower than its own number; the chain runs one way"
            )
    if content:
        return content

    roots = [entry for entry in entries if entry.follows is None]
    structure: list[str] = []
    if len(roots) != 1:
        structure.append(
            "the ledger has "
            + (
                "no entry that declares no follows:"
                if not roots
                else f"{len(roots)} entries that declare no follows: "
                + ", ".join(entry.path.name for entry in roots)
            )
            + ". Exactly one entry is the root; every other entry names the "
            "entry it was measured on top of."
        )
    followed: dict[int, list[SimpleNamespace]] = {}
    for entry in entries:
        if entry.follows is not None:
            followed.setdefault(entry.follows, []).append(entry)
    for target, claimants in sorted(followed.items()):
        if len(claimants) > 1:
            structure.append(
                ", ".join(entry.path.name for entry in claimants)
                + f" all follow {target:04d}, so they were each measured on the "
                "same ledger state and none of their figures describes the "
                "package that now holds every one of these changes. Measure the "
                "merged package, then either replace them with one entry "
                "measured against it, or re-point the later entry at the "
                "earlier one and re-state that entry's measured figure and "
                "ceiling against the merge."
            )
    if structure:
        return structure

    chain = _guidance_budget_walk(entries)
    monotone: list[str] = []
    for later in chain[1:]:
        for which, measurement in sorted(later.measured.items()):
            previous = _last_measured(chain, which, later)
            if previous is None:
                continue
            previous_entry, previous_measurement = previous
            previous_ceiling = _ceiling_in_force(chain, which, later)
            if (
                which in later.ceilings
                and previous_ceiling is not None
                and later.ceilings[which] < previous_ceiling
            ):
                # A prune lowers both the ceiling and the measurement; that is a
                # different decision and this check has nothing to say about it.
                continue
            if measurement < previous_measurement:
                monotone.append(
                    f"{later.path.name} measured {which} at {measurement}, "
                    f"below {previous_entry.path.name}'s {previous_measurement} "
                    "which it follows. A figure taken before its predecessor's "
                    "change cannot describe a package that contains it: "
                    "re-measure the merged package and re-state this entry's "
                    "figure and ceiling."
                )
    return monotone


def _guidance_budget_walk(entries: list[SimpleNamespace]) -> list[SimpleNamespace]:
    """Walk the ledger from its root, and insist the walk reaches all of it.

    One root and no two entries following the same one force a single path -
    n nodes, n-1 edges, in-degree and out-degree at most one, and numbers that
    only decrease, so there is nowhere for a fork or a cycle to be. That is why
    the ceiling in force is unambiguous, and why the walk below is the same
    order as the numbers.

    The guard is therefore unreachable while those two rules hold. It is not a
    check that catches an author mistake and is not tested as one; it is here
    so that changing either rule cannot quietly turn the ceiling in force into
    whichever branch of the ledger happened to be read.
    """
    successor = {entry.follows: entry for entry in entries if entry.follows is not None}
    chain = [next(entry for entry in entries if entry.follows is None)]
    while chain[-1].index in successor:
        chain.append(successor[chain[-1].index])
    if len(chain) != len(entries):
        raise RuntimeError(
            "the guidance budget ledger walks as "
            + ", ".join(entry.path.name for entry in chain)
            + " but holds "
            + ", ".join(entry.path.name for entry in entries)
            + "; the ceiling in force would depend on which branch was read"
        )
    return chain


def _last_measured(
    chain: list[SimpleNamespace], which: str, before: SimpleNamespace
) -> tuple[SimpleNamespace, int] | None:
    """The newest measurement of `which` strictly before `before` in the chain."""
    for entry in reversed(chain[: chain.index(before)]):
        if which in entry.measured:
            return entry, entry.measured[which]
    return None


def _ceiling_in_force(
    chain: list[SimpleNamespace], which: str, before: SimpleNamespace
) -> int | None:
    """The ceiling `which` was under strictly before `before` in the chain."""
    for entry in reversed(chain[: chain.index(before)]):
        if which in entry.ceilings:
            return entry.ceilings[which]
    return None


def guidance_budget_chain(
    entries: list[SimpleNamespace] | None = None,
) -> list[SimpleNamespace]:
    """The ledger read as the single chain of raises it has to be."""
    entries = guidance_budget_entries() if entries is None else entries
    defects = guidance_budget_defects(entries)
    if defects:
        raise ValueError(
            "the guidance budget ledger is not a single chain of measured "
            "raises, so no ceiling can be read off it:\n- " + "\n- ".join(defects)
        )
    return _guidance_budget_walk(entries)


def guidance_budget_ceilings(
    entries: list[SimpleNamespace] | None = None,
) -> dict[str, int]:
    """The ceiling in force: the last entry along the chain that declared it."""
    ceilings: dict[str, int] = {}
    for entry in guidance_budget_chain(entries):
        ceilings.update(entry.ceilings)
    return ceilings


def conversation_contract_documents() -> list[Path]:
    """Every tracked document that can shape or promise the user journey.

    The progressive-load corpus above owns the guidance byte budget. Public
    promises and repository-level instructions also participate in
    contradictions even though the installed skill does not load them all.
    """
    return [
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        ROOT / "CLAUDE.md",
        *assistant_facing_documents(),
    ]


CI_WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))


def ci_workflow_jobs(workflow: Path) -> dict[str, int | None]:
    """Every job in one workflow, mapped to its declared `timeout-minutes`.

    `None` means the job declares no job-level bound, or declares more than one
    and so states no single decision. Both are failures, and the caller says
    which failure it is checking for.

    Parsed by indentation rather than with PyYAML: the CI job that runs this
    test installs `ruff`, `black` and the three pinned first-run dependencies,
    none of which declares PyYAML, so importing it here would be relying on a
    transitive dependency to stay transitive.

    Written once because two tests ask different questions of the same parse.
    Parsing twice would let them disagree about what a job even is, which is the
    shape of defect they exist to catch.
    """
    in_jobs = False
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    for line in workflow.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_jobs = line.startswith("jobs:")
            current = None
            continue
        if in_jobs and indent == 2 and line.rstrip().endswith(":"):
            current = line.strip().rstrip(":")
            bodies[current] = []
        elif in_jobs and current is not None and indent >= 4:
            bodies[current].append(line)
    jobs: dict[str, int | None] = {}
    for job, body in bodies.items():
        declared = [
            line.strip()
            for line in body
            if len(line) - len(line.lstrip()) == 4
            and line.strip().startswith("timeout-minutes:")
        ]
        jobs[job] = int(declared[0].split(":", 1)[1]) if len(declared) == 1 else None
    return jobs


def behavioral_harness():
    """The offline harness module, imported the way the test runner reaches it.

    `python -m unittest discover -s tests` puts `tests/` on the path, so
    `tests/behavioral/test_contracts.py` can import this directly. This file is
    also run on its own, so the insert is repeated here rather than assumed -
    the same thing `tools/relock.py` does for the same reason.
    """
    if str(ROOT / "tests") not in sys.path:
        sys.path.insert(0, str(ROOT / "tests"))
    from behavioral import harness

    return harness
def cap_construction_blocks(source: str, default: object) -> dict[str, set[str]]:
    """Every `Cap(...)` in the scorer, mapped condition -> the `blocks` it names.

    Read from the AST rather than from `vars(READINESS)`, because a scan of the
    module's own attributes reaches only the caps built at module level. Two of
    the five conditions the partition check named -
    `dataset-below-measurable-size` and `dataset-coarse-resolution` - are
    constructed INSIDE `power_ceiling` and never entered that loop, so forcing
    `blocks=True` on the below-measurable-size branch left the guard green. The
    class is wider than these two: any cap, constant or rule built inside a
    function is invisible to a module-level scan.

    The value is the rendered expression and not a bool, because a site can
    decide at runtime: `blocks=effective_n == 0` is one condition with two
    branches, and a routing bullet that states one of them states a falsehood
    about the other. The default is passed in from the dataclass rather than
    written down here, so a change to `Cap.blocks`'s default cannot leave this
    reading every unannotated site as the wrong thing.
    """
    found: dict[str, set[str]] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "Cap" or not node.args:
            continue
        condition = node.args[0]
        if not isinstance(condition, ast.Constant) or not isinstance(
            condition.value, str
        ):
            continue
        rendered = repr(default)
        for keyword in node.keywords:
            if keyword.arg == "blocks":
                rendered = ast.unparse(keyword.value)
        found.setdefault(condition.value, set()).add(rendered)
    return found


RUN_SAFETY = SKILL_ROOT / "references" / "run-safety.md"
SDK_EXECUTION = SKILL_ROOT / "references" / "sdk-execution.md"

# The config-space document is a contract between prose the assistant follows and
# code that reads it, so these tests weld the documented shape to the real
# consumer rather than re-describing it.
_READINESS = SKILL_ROOT / "scripts" / "readiness.py"
_SPEC = importlib.util.spec_from_file_location(
    "first_run_readiness_for_prose", _READINESS
)
READINESS = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = READINESS
_SPEC.loader.exec_module(READINESS)


def preflight_constant(name: str) -> object:
    """Read one module-level constant out of `preflight.py` without running it.

    The two scripts are separate programs that meet over JSON, so nothing at
    runtime can compare their constants against each other - which is exactly
    why a number can be changed in one and left in the other. That comparison
    lives here. Parsed rather than executed, because a test about what
    preflight DECIDES should not depend on what importing it does.
    """
    source = ast.parse((SKILL_ROOT / "scripts" / "preflight.py").read_text())
    for node in source.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"preflight.py defines no module-level {name}")


def score_config_space(document: dict) -> tuple[object, list[str]]:
    """Run a config-space document through the real adapter and agent scorer."""
    pillar, caps, _knobs = READINESS.score_agent(
        READINESS.agent_facts_from_config_space(document)
    )
    return pillar, [cap.condition for cap in caps]


class SkillPackageTests(unittest.TestCase):
    def test_frontmatter_has_only_supported_fields(self) -> None:
        text = SKILL.read_text()
        frontmatter = text.split("---", 2)[1]
        keys = {
            line.split(":", 1)[0].strip()
            for line in frontmatter.splitlines()
            if ":" in line
        }
        self.assertEqual(keys, {"name", "description"})

    def test_every_relative_markdown_link_in_skill_exists(self) -> None:
        text = SKILL.read_text()
        targets = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
        relative_targets = [
            target.split("#", 1)[0]
            for target in targets
            if "://" not in target and not target.startswith("#")
        ]
        self.assertGreater(len(relative_targets), 0)
        for target in relative_targets:
            with self.subTest(target=target):
                self.assertTrue((SKILL_ROOT / target).exists())

    def test_root_entrypoint_links_exist(self) -> None:
        for document in (ROOT / "README.md", ROOT / "GUIDE.md"):
            targets = re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text())
            for target in targets:
                if "://" in target or target.startswith("#"):
                    continue
                relative = target.split("#", 1)[0]
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent / relative).exists())

    def test_installed_skill_is_self_contained(self) -> None:
        required = {
            "SKILL.md",
            "agents/openai.yaml",
            "references/component-creation.md",
            "references/evaluation-and-dataset.md",
            "references/run-safety.md",
            "references/sdk-execution.md",
            "scripts/preflight.py",
            "scripts/readiness.py",
            "scripts/calibrate_evaluator.py",
            "assets/run-plan.md",
            "assets/requirements-first-run.txt",
        }
        actual = {
            str(path.relative_to(SKILL_ROOT))
            for path in SKILL_ROOT.rglob("*")
            if path.is_file()
        }
        self.assertTrue(required <= actual)
        for path in SKILL_ROOT.rglob("*"):
            if path.is_file():
                self.assertNotIn("beginner", path.name.casefold())

    def test_generated_run_artifacts_are_not_tracked(self) -> None:
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--", "traigent-runs"],
            capture_output=True,
            text=True,
            check=False,
        )
        if listed.returncode != 0:
            raise RuntimeError(
                f"could not inspect tracked run artifacts: {listed.stderr.strip()}"
            )
        self.assertEqual(listed.stdout.strip(), "")

    def test_user_facing_skill_language_does_not_label_the_user(self) -> None:
        combined = "\n".join(
            path.read_text() for path in SKILL_ROOT.rglob("*.md") if path.is_file()
        ).casefold()
        self.assertNotIn("beginner", combined)
        self.assertNotIn("non-technical", combined)
        self.assertNotIn("not for experienced", combined)

    def test_active_run_guidance_contains_only_required_account_links(self) -> None:
        combined = "\n".join(path.read_text() for path in assistant_facing_documents())
        urls = re.findall(r"https?://[^`\s)]+", combined)
        allowed_hosts = {
            "portal.traigent.ai",
            # The public site is the ONLY destination for a user who holds no
            # access code yet - the portal's register page refuses them, so
            # without this the guide names the one address it must not give and
            # no address it may.
            "traigent.ai",
            "openrouter.ai",
            "platform.openai.com",
            "console.anthropic.com",
        }
        for url in urls:
            host = url.split("/", 3)[2]
            self.assertIn(host, allowed_hosts)
            # Host granularity is enough for the provider links, and not enough
            # for this one: `traigent.ai/register` is a page that does not exist
            # and is the exact shape run-safety forbids handing to a user with
            # no access code. The public site is only ever given bare.
            if host == "traigent.ai":
                self.assertEqual(
                    url.rstrip(").,"),
                    "https://traigent.ai",
                    "the public site is handed over bare, never with a path",
                )

    def test_quality_advisory_requires_evidence_choice_and_revalidation(self) -> None:
        skill_text = SKILL.read_text().casefold()
        quality_text = (
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
        )
        for phrase in (
            "quality advisory",
            "repair a working copy and re-run validation",
            "continue as a workflow demonstration",
            "pause for a user-authored fix",
            'do not infer "easy-only"',
        ):
            self.assertIn(phrase, f"{skill_text}\n{quality_text}")
        self.assertIn("stop before the search", skill_text)

    def test_guidance_is_progressively_routed(self) -> None:
        text = SKILL.read_text().casefold()
        self.assertNotIn("read these files before acting", text)
        for phrase in (
            "after inventory",
            "evaluation method is assessed",
            "before environment changes",
            "only before writing the wrapper",
        ):
            self.assertIn(phrase, text)

    def test_zero_anchor_task_intent_gate_requires_zero_writes(self) -> None:
        text = SKILL.read_text()
        gate_heading = "#### Zero-anchor intent gate"
        next_heading = "### 2. Show readiness once"
        self.assertIn(gate_heading, text)
        self.assertIn(next_heading, text)
        gate = text.split(gate_heading, 1)[1].split(next_heading, 1)[0]
        normalized_gate = " ".join(gate.casefold().split())
        top_level = " ".join(
            text.split("## Operating contract", 1)[0].casefold().split()
        )
        authorization_rows = (
            text.split("## Action authorization", 1)[1]
            .split("## Status language", 1)[0]
            .casefold()
            .splitlines()
        )

        self.assertEqual(gate.count("What should the walkthrough agent do?"), 1)
        self.assertEqual(gate.count("?"), 1)
        self.assertLess(
            normalized_gate.index("what should the walkthrough agent do?"),
            normalized_gate.index("stop and wait for the answer"),
        )
        for component in ("❗ **agent**", "❗ **dataset**", "❗ **evaluation**"):
            self.assertIn(component, normalized_gate)
            self.assertLess(
                normalized_gate.index(component),
                normalized_gate.index("what should the walkthrough agent do?"),
            )
        for phrase in (
            "stop and wait for the answer",
            "before that answer, make zero writes",
            "do not create `traigent-runs/`",
            "do not copy or fill the run plan",
            "do not change `.gitignore`",
            "do not create an environment",
            "do not install dependencies",
            "do not generate components",
            "once the user answers",
            "create the run record before generating the coherent trio",
        ):
            self.assertIn(phrase, normalized_gate)
        self.assertIn("only after task intent is anchored", top_level)
        for action in (
            "create `traigent-runs/` artifacts",
            "create an isolated environment",
            "install dependencies",
        ):
            action_row = next(
                (row for row in authorization_rows if action in row),
                "",
            )
            self.assertIn("| proceed only after", action_row)
            self.assertIn("task intent is anchored", action_row)

    def test_guide_has_one_workflow_entrypoint(self) -> None:
        guide = (ROOT / "GUIDE.md").read_text()
        start_section = guide.split("## Start here", 1)[1].split("## ", 1)[0]
        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", start_section)
        self.assertEqual(links, ["skills/traigent-first-run/SKILL.md"])
        normalized = " ".join(start_section.casefold().split())
        self.assertIn(
            "the skill routes its bundled references at the stage where each is needed",
            normalized,
        )
        self.assertIn("do not front-load them", normalized)

    def test_action_authorization_is_closed_and_cost_aware(self) -> None:
        skill_text = SKILL.read_text().casefold()
        safety_text = (
            (SKILL_ROOT / "references" / "run-safety.md").read_text().casefold()
        )
        contract_text = " ".join(f"{skill_text} {safety_text}".split())
        for phrase in (
            "an action not listed here is forbidden",
            "judgment-dependent change",
            "local-only",
            "separate explicit approval",
            "two short, contextual approvals",
            "single running total",
        ):
            self.assertIn(phrase, contract_text)
        self.assertIn(
            "does not yet share one cumulative budget",
            contract_text,
        )
        self.assertIn(
            "never replace it silently",
            safety_text,
        )

    def test_first_run_does_not_ask_for_implementation_settings(self) -> None:
        skill_text = " ".join(SKILL.read_text().casefold().split())
        safety_text = " ".join(RUN_SAFETY.read_text().casefold().split())
        combined = f"{skill_text} {safety_text}"
        for phrase in (
            "do not repeat a provider choice already resolved in stage 5",
            "stop once",
            "do not ask the user to choose cost, retries, or timeout settings",
            "one concise baseline preview and approval",
            "one total walkthrough ceiling, defaulting to `$5.00`",
            "do not layer another retry loop",
            "never call the walkthrough ceiling a hard provider-billing cap",
        ):
            self.assertIn(phrase, combined)
        for obsolete_prompt in (
            "explicit provider retry count",
            "remaining-budget ledger",
            "holdout phase timeout",
        ):
            self.assertNotIn(obsolete_prompt, combined)
        for paid_phase in (
            "smallest live provider/key check",
            "pre-baseline llm-judge calibration",
            "preserved baseline or generated six-row sweep",
            "added enhanced controls",
            "rule for recommending among tradeoffs",
        ):
            self.assertIn(paid_phase, combined)

    def test_staged_approvals_disclose_each_immediate_decision(
        self,
    ) -> None:
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        approval = safety.split("## approval and budgets", 1)[1].split(
            "## connected-run readiness", 1
        )[0]
        for phrase in (
            "before the provider-paid baseline",
            "show only its immediate scope",
            "after showing the baseline result",
            "connected stage a preview and approval",
            "tuning rows and limitations",
            "objective directions and weights",
            "managed search chooses trials",
            "rule for recommending among tradeoffs",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, approval)
        self.assertNotIn("winner holdout", approval)

    def test_dependency_install_authorization_is_narrow(self) -> None:
        skill_text = " ".join(SKILL.read_text().casefold().split())
        safety_text = " ".join(
            (SKILL_ROOT / "references" / "run-safety.md").read_text().casefold().split()
        )
        guide_text = " ".join((ROOT / "GUIDE.md").read_text().casefold().split())
        for text in (skill_text, safety_text, guide_text):
            for phrase in (
                "exact packages and versions",
                "user or environment",
                "private-data",
                "code execution",
            ):
                self.assertIn(phrase, text)
        self.assertIn("package-artifact", skill_text)
        self.assertIn(
            "external calls other than the narrow dependency fetch",
            skill_text,
        )

        requirements = REQUIREMENTS.read_text().splitlines()
        self.assertEqual(
            requirements,
            [
                "traigent==0.25.0",
                "litellm==1.93.0",
                "python-dotenv==1.2.2",
            ],
        )
        for text in (skill_text, safety_text, guide_text):
            self.assertIn("never", text)
            self.assertIn("unversioned `pip install traigent`", text)

    def test_readme_discloses_pinned_sdk_license_terms(self) -> None:
        # The version is DERIVED from the file that pins it, never restated
        # here. Asserting a literal this test carries makes the disclosure
        # stale through a fully green run: bump the requirements file, update
        # the one literal in `test_dependency_install_authorization_is_narrow`
        # above, relock, and the whole suite passes while README still names
        # the terms of a release nobody installs. The same class as that
        # test's prior art, applied to the document rather than the pin.
        version = pinned_sdk_version()
        readme_source = (ROOT / "README.md").read_text()
        readme = " ".join(readme_source.casefold().split())

        for phrase in (
            f"the pinned requirements install `traigent=={version}`",
            "`agpl-3.0-only`",
            "installing the package does not itself grant commercial terms",
            "separate written commercial agreement",
            "legal@traigent.ai",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)
        for target in ("LICENSE", "COMMERCIAL-LICENSE.md"):
            with self.subTest(target=target):
                self.assertIn(
                    f"https://github.com/Traigent/Traigent/blob/v{version}/{target}",
                    readme_source,
                )
        # Every release-shaped literal in the whole README, not only the three
        # in the licensing section: the telemetry link and the retention
        # paragraph under "Privacy" name the same pinned release, and a fourth
        # one added tomorrow is caught without this test being told about it.
        stated = set(re.findall(r"\d+\.\d+\.\d+", readme_source))
        self.assertEqual(
            stated,
            {version},
            "README states a release other than the pinned "
            f"`traigent=={version}`. Every version this document names is the "
            "one `assets/requirements-first-run.txt` installs; a link to some "
            "other tag describes terms the reader is not agreeing to.",
        )

    def test_readme_asserts_no_license_terms_for_this_repository(self) -> None:
        """This repository has no LICENSE, so it may not describe its own terms.

        `gh api repos/Traigent/traigent-first-run` returns `"license": null`
        with `"visibility": "public"`, and no LICENSE file is tracked - which
        is all-rights-reserved by default, while this same README tells the
        reader to `npx skills add Traigent/traigent-first-run`. A sentence
        saying the SDK notice "does not change the license terms for this
        guide repository" asserts terms that do not exist. Choosing a license
        is the owner's call; saying nothing is strictly better than saying
        something false, so the sentence is gone and stays gone.
        """
        readme = " ".join((ROOT / "README.md").read_text().casefold().split())
        for phrase in (
            "license terms for this guide repository",
            "the license of this repository",
            "this repository is licensed",
        ):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, readme)

    def test_incompatible_environment_recovery_uses_distinct_venv(self) -> None:
        skill_text = " ".join(SKILL.read_text().casefold().split())
        safety_text = " ".join(RUN_SAFETY.read_text().casefold().split())

        for text in (skill_text, safety_text):
            self.assertIn("conventional `.venv`", text)
            self.assertIn("implementation detail", text)
            self.assertIn("`.venv-traigent`", text)
        self.assertIn("preserve an incompatible `.venv`", skill_text)
        self.assertIn(
            "`.venv` already exists but uses an incompatible interpreter", safety_text
        )
        self.assertIn("python3.13 -m venv .venv-traigent", safety_text)
        self.assertNotIn("python3.13 -m venv .venv`", safety_text)

    def test_opening_gate_uses_one_compatible_project_environment(self) -> None:
        """Inventory is actionable when it finds one unambiguous interpreter."""
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        for phrase in (
            "exactly one compatible",
            "inside the user's project root",
            "use its resolved interpreter",
            "`python-version` as measured",
            "otherwise use the host `python3`",
            "provisional",
            "multiple compatible candidates",
            "fall back to the host",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)
        self.assertIn("skill's opening gate owns", safety)
        self.assertIn("stage 5 remains authoritative", safety)
        self.assertIn("environments outside the project", skill)
        self.assertIn("external-only environments", safety)
        self.assertIn(
            "a current-project environment managed outside the root is an external candidate, not an ignored one",
            safety,
        )
        joined = f"{skill} {safety}"
        self.assertNotIn(
            "host `python3` interpreter as a narrow bootstrap for every bundled script",
            joined,
        )

    def test_provider_inventory_is_separate_from_route_selection(self) -> None:
        skill_text = " ".join(SKILL.read_text().casefold().split())
        safety_text = " ".join(RUN_SAFETY.read_text().casefold().split())
        for text in (skill_text, safety_text):
            self.assertIn("credential", text)
            self.assertIn("do not", text)
            self.assertIn("route", text)
        self.assertIn("resolve the route from the selected agent", skill_text)
        self.assertIn("inventory presence—not values", skill_text)
        self.assertIn("never rewrite a route merely to match a key", skill_text)

    def test_provider_mismatch_names_sources_before_requesting_a_key(self) -> None:
        skill_text = " ".join(SKILL.read_text().casefold().split())
        safety_text = " ".join(RUN_SAFETY.read_text().casefold().split())
        env_example = " ".join((ROOT / ".env.example").read_text().casefold().split())

        for phrase in (
            "inventory presence—not values—in the process, handoff, and exact credentials",
            "project-declared env loader, launcher, or secret manager exposes without external calls",
            "never enumerate stores",
            "mark declared-only sources unverified",
            "reuse a matching credential in place when inheritable",
            "do not call the file unsaved",
            "agent route: <vendor/model>",
            "provider credentials: <vendors and sources>",
            "traigent key: <present/absent> (not a provider credential)",
            "preserve this route by adding <key>",
            "or change to <available vendor>?",
            "a route change requires recipient disclosure and approval",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill_text)
        self.assertNotIn("safe key-shape prefixes", safety_text)
        self.assertNotIn("convenient default", env_example)
        self.assertIn("another vendor's key does not change its route", env_example)
        self.assertIn("add its key or change provider", env_example)

    def test_selected_agent_identity_prevents_cross_project_result_confusion(
        self,
    ) -> None:
        """The guide source can be separate from the project being optimized."""
        guide_text = " ".join(
            (ROOT / "GUIDE.md").read_text().casefold().split()
        ).replace(" > ", " ")
        skill_text = " ".join(SKILL.read_text().casefold().split())
        plan_text = " ".join(
            (SKILL.parent / "assets" / "run-plan.md").read_text().casefold().split()
        )
        for phrase in (
            "not automatically the project being optimized",
            "at run time; never substitute",
            "target project: <absolute path>",
            "agent: <absolute path>:<function or command>",
            "historical — different agent",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, guide_text)
        for phrase in (
            "loaded guide source is not automatically the target project",
            "guide-source artifacts never count as its results",
            "a mismatched resumed artifact is historical, never current",
            "agent: none discovered",
            "until intent selects or creates one",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill_text)
        self.assertIn("agent: none discovered", guide_text)
        self.assertIn(
            "target project and selected agent (absolute path plus function or command)",
            plan_text,
        )
        safety_text = " ".join(
            (SKILL.parent / "references" / "run-safety.md")
            .read_text()
            .casefold()
            .split()
        )
        self.assertIn("credential-file-relative-path", safety_text)

    def test_free_readiness_research_is_not_presented_as_a_result(self) -> None:
        """Automatic checks validate readiness, not model performance."""
        guide_text = " ".join(
            (ROOT / "GUIDE.md").read_text().casefold().split()
        ).replace(" > ", " ")
        skill_text = " ".join(SKILL.read_text().casefold().split())
        self.assertIn("run free readiness research", guide_text)
        self.assertIn(
            "score and setup—not agent accuracy or an optimization result", guide_text
        )
        self.assertIn("i explain details", guide_text)
        self.assertIn("only if action is needed", guide_text)
        self.assertIn("the rendered readiness card is the summary", skill_text)
        self.assertIn(
            "do not separately explain passed calibration/mock wiring", skill_text
        )
        self.assertIn("neither is agent accuracy or an optimization result", skill_text)

    def test_stdlib_component_checks_precede_environment_and_secret_gates(
        self,
    ) -> None:
        text = SKILL.read_text()
        local_heading = "### 4. Validate components locally"
        environment_heading = "### 5. Prepare the environment and finish free checks"
        paid_heading = "### 6. Approve and run the baseline"
        for heading in (local_heading, environment_heading, paid_heading):
            self.assertIn(heading, text)

        local_section = text.split(local_heading, 1)[1].split(environment_heading, 1)[0]
        environment_section = text.split(environment_heading, 1)[1].split(
            paid_heading, 1
        )[0]
        normalized_local = " ".join(local_section.casefold().split())
        normalized_environment = " ".join(environment_section.casefold().split())

        preflight = normalized_local.index("run the bundled static preflight")
        calibration = normalized_local.index("run deterministic calibration")
        semantic_review = normalized_local.index(
            "record the assistant-performed semantic-coverage review"
        )
        ambiguity_gate = normalized_local.index(
            "if unresolved product-grading ambiguity"
        )
        self.assertLess(preflight, calibration)
        self.assertLess(semantic_review, calibration)
        self.assertLess(semantic_review, ambiguity_gate)
        self.assertLess(ambiguity_gate, preflight)
        for phrase in (
            "local structure and quality",
            "does not assert sdk compatibility",
            "before creating an isolated environment",
            "before installing dependencies",
            "before creating `.env`",
            "before asking for a provider key",
            "missing traigent sdk",
        ):
            self.assertIn(phrase, normalized_local)

        ordered_environment_phrases = (
            "resolve and prepare the environment",
            "install the exact declared dependencies",
            "verify capabilities and public signatures",
            "run a fresh-process traigent mock plumbing check",
            "create or minimally update `.env`",
            "stop once",
        )
        positions = [
            normalized_environment.index(phrase)
            for phrase in ordered_environment_phrases
        ]
        self.assertEqual(positions, sorted(positions))

    def test_run_safety_owns_depth_without_repeating_the_skill_flow(self) -> None:
        text = RUN_SAFETY.read_text()
        normalized_safety = " ".join(text.casefold().split())
        self.assertIn(
            "follow skill stages 4-7 for ordering; this reference does not define a second flow",
            normalized_safety,
        )
        self.assertNotIn("use this gate order", normalized_safety)
        for heading in (
            "## static and mock validation",
            "### execution-evaluator containment",
            "### deterministic calibration and mock plumbing",
            "### config-space document",
            "## approval and budgets",
            "## connected-run readiness",
            "## baseline and optimization",
            "## post-run verification",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, normalized_safety)

        for phrase in (
            "do not execute an llm judge",
            "uncertain or external evaluator",
            "two short, contextual approvals",
            "make model/provider calls",
        ):
            self.assertIn(phrase, normalized_safety)

    def test_local_baseline_checkpoint_precedes_every_traigent_key_request(
        self,
    ) -> None:
        """The account funnel starts only after visible provider-backed value."""
        text = SKILL.read_text().casefold()
        stage_five = " ".join(text.split("### 5.", 1)[1].split("### 6.", 1)[0].split())
        stage_seven = " ".join(text.split("### 7.", 1)[1].split("### 8.", 1)[0].split())

        for forbidden in (
            "keys they already hold",
            "both local secret pastes",
            "provide only the required account/key destination",
            "blank selected-provider and traigent key entries",
        ):
            self.assertNotIn(forbidden, stage_five)
        self.assertIn("stop once for only that secret locally", stage_five)

        ordered = (
            "the baseline needs only the user's provider credential",
            "show a **local baseline checkpoint**",
            "only after that checkpoint, ask for the traigent key",
            "once the key is present, run the zero-llm portal probe",
            "feature-detect a public exact sync id",
            "run the enhanced optimization connected",
        )
        positions = [stage_seven.index(phrase) for phrase in ordered]
        self.assertEqual(positions, sorted(positions))

    def test_public_promises_match_the_local_then_connected_sequence(self) -> None:
        documents = {
            path.name: " ".join(path.read_text().casefold().split())
            for path in (ROOT / "README.md", ROOT / "GUIDE.md", SKILL, RUN_SAFETY)
        }
        joined = " ".join(documents.values())
        self.assertNotIn("two connected optimization experiments", joined)
        for phrase in (
            "provider-paid local fixed baseline",
            "zero-llm portal probe",
            "connected managed optimization",
            "without rerunning",
            "otherwise it remains local",
        ):
            self.assertIn(phrase, joined)

    def test_readme_qualifies_public_cost_trial_and_approval_promises(self) -> None:
        """The short public summary must retain the conditions behind each promise."""
        readme = " ".join((ROOT / "README.md").read_text().casefold().split())
        for phrase in (
            "total execution stop target",
            "not a guaranteed provider-billing cap",
            "testing up to 12 configurations",
            "total combination count beside the ceiling",
            "number of configurations actually tested and any concrete shortfall reason",
            "cannot yet support a trustworthy paid comparison",
            # This used to pin "too little comparable evidence exists" as a
            # meaning of PAID RUN BLOCKED. The scorer no longer blocks on a
            # small comparison set or on generated data - both are runs the
            # guide sanctions, and both are now ceilings - so the phrase pinned
            # a promise the card had stopped keeping. What the README must
            # still carry is the boundary itself, from the other side.
            "they do not stop the run or ask you to fix anything",
            "judgment-dependent changes to real examples, expected answers, or grading policy",
            "destructive or production-affecting actions",
            "if no key is already present",
            "one model family available through the selected route",
            "additional upstream recipient is disclosed and approved",
            "portal key that can write experiments",
            "add a full-access key then",
            "ignored when the project uses git",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)

        self.assertNotIn("something is broken and paid work", readme)
        self.assertNotIn("then 10-13 connected managed trials", readme)

    def test_the_blocked_gloss_admits_every_state_that_actually_blocks(self) -> None:
        """`PAID RUN BLOCKED` may not be glossed as "create or repair something".

        One blocking condition is keyed on a row COUNT rather than on anything
        being absent or malformed. `power_ceiling` blocks below
        `WIRING_CHECK_EXAMPLES` scoreable rows, and its remedy is `get-data` -
        gather more evidence, which is neither creating a thing nor repairing
        one. Reproduced end to end through the real
        `preflight.py --json | readiness.py --preflight -` pipeline: six
        collected, labelled, well-formed rows per split with a healthy
        calibration and a healthy config space score 74/100 WORKABLE and print
        `PAID RUN BLOCKED`, carrying exactly one cap -
        `dataset-below-measurable-size`, ceiling 74, `blocks=True`,
        `action_kind='get-data'`. Nothing is missing and nothing is invalid, so
        a gloss offering only "create or repair" describes no available action
        for the card the reader is holding.

        Gated on the scorer rather than pinned as a phrase, which is the point:
        traigent-first-run#149 turns that condition into a ceiling except at
        zero scoreable rows. On the day it merges, thin evidence stops blocking,
        the branch below flips, and this test asks for the shorter gloss instead
        of silently continuing to accept a sentence the card no longer earns. It
        fails today if the evidence-gathering half is dropped, and it fails
        after #149 if the half is kept - the sentence and the behaviour cannot
        drift apart in either direction.
        """
        # n starts at 1: zero scoreable rows really is "something is missing",
        # which the other half of the gloss already covers. What has to be
        # covered here is a dataset that is present, valid and merely small.
        thin_evidence_blocks = False
        remedy = None
        for scoreable in range(1, READINESS.COARSE_RESOLUTION_EXAMPLES):
            cap = READINESS.power_ceiling(scoreable)
            if cap is not None and cap.blocks:
                thin_evidence_blocks = True
                remedy = cap.action_kind
                break

        readme = " ".join((ROOT / "README.md").read_text().casefold().split())
        gloss = readme.split("`paid run blocked` is the headline", 1)[1].split(
            "`limited to 89` means", 1
        )[0]
        if thin_evidence_blocks:
            # Not create, not repair: the closed remedy vocabulary says so.
            self.assertEqual(remedy, "get-data")
            self.assertIn("or too little comparable evidence exists", gloss)
            self.assertIn("repair or evidence-gathering action", gloss)
        else:
            self.assertNotIn("too little comparable evidence", gloss)

    def test_generated_artifacts_and_secrets_are_ignored_only_for_git_projects(
        self,
    ) -> None:
        """Protect artifacts and secrets without adding files outside Git."""
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        readme = " ".join((ROOT / "README.md").read_text().casefold().split())
        env_example = " ".join((ROOT / ".env.example").read_text().casefold().split())
        for phrase in (
            'git -c "<project-root>" rev-parse --is-inside-work-tree',
            "add `/traigent-runs/` to the project-root `.gitignore`",
            "otherwise do not create `.gitignore`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)
        self.assertIn("ignored when the project uses git", readme)
        self.assertIn("verify it is untracked and effectively ignored", env_example)

        # #124: run-safety.md is the one home for the .env tracked-file check's
        # exact commands and exit-code reasoning.
        for phrase in (
            "ls-files --error-unmatch -- .env",
            "exit 0 means tracked and must stop",
            "continue only on exit 1 with no match",
            "stop on any other status",
            "effective `/.env` rule",
            "`/.env`",
            "check-ignore -q -- .env",
            "effective-ignore check fails",
            "stop before secret entry",
            "outside git, do not create `.gitignore`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, safety)

        # SKILL.md's action-authorization row names the check and points at
        # run-safety.md instead of restating its commands or exit-code
        # reasoning - a second full statement of that logic is the defect
        # #124 found, not emphasis.
        env_row = skill.split("create or update a minimal `.env`", 1)[1].split(
            "| repair a working copy", 1
        )[0]
        self.assertIn("run-safety.md", env_row)
        self.assertIn("git-tracked-file safety check", env_row)
        self.assertIn("stop before secret entry", env_row)
        for restated in (
            "ls-files --error-unmatch -- .env",
            "exit 0 means tracked",
            "continue only on exit 1 with no match",
            "stop on any other status",
            "check-ignore -q -- .env",
            "effective `/.env` rule",
        ):
            with self.subTest(not_restated=restated):
                self.assertNotIn(restated, env_row)

        self.assertIn("verifies it is untracked and effectively ignored", readme)
        self.assertNotIn(
            "add that directory to the project `.gitignore`",
            skill,
        )

    def test_effective_git_ignore_check_detects_a_later_negation(self) -> None:
        """Pattern presence alone does not prove that a secret is ignored."""
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                ["git", "-C", directory, "init", "--quiet"],
                check=True,
                capture_output=True,
                text=True,
            )
            ignore = Path(directory) / ".gitignore"
            ignore.write_text("/.env\n!/.env\n")
            negated = subprocess.run(
                ["git", "-C", directory, "check-ignore", "-q", "--", ".env"],
                check=False,
            )
            ignore.write_text("/.env\n")
            effective = subprocess.run(
                ["git", "-C", directory, "check-ignore", "-q", "--", ".env"],
                check=False,
            )
            secret = Path(directory) / ".env"
            secret.write_text("EXAMPLE_API_KEY=\n")
            untracked = subprocess.run(
                [
                    "git",
                    "-C",
                    directory,
                    "ls-files",
                    "--error-unmatch",
                    "--",
                    ".env",
                ],
                check=False,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", directory, "add", "--force", "--", ".env"],
                check=True,
                capture_output=True,
            )
            tracked = subprocess.run(
                [
                    "git",
                    "-C",
                    directory,
                    "ls-files",
                    "--error-unmatch",
                    "--",
                    ".env",
                ],
                check=False,
                capture_output=True,
            )
        self.assertEqual(negated.returncode, 1)
        self.assertEqual(effective.returncode, 0)
        self.assertEqual(untracked.returncode, 1)
        self.assertEqual(tracked.returncode, 0)

    def test_installed_skill_tools_use_absolute_paths_from_the_project_cwd(
        self,
    ) -> None:
        """Installed skills do not live beneath the user's project."""
        guide = " ".join((ROOT / "GUIDE.md").read_text().casefold().split())
        evaluation_source = (
            SKILL_ROOT / "references" / "evaluation-and-dataset.md"
        ).read_text()
        evaluation = " ".join(evaluation_source.casefold().split())
        readme = " ".join((ROOT / "README.md").read_text().casefold().split())

        for text in (guide, evaluation):
            self.assertIn("absolute directory containing the loaded `skill.md`", text)
            self.assertIn("user's project root", text)
        self.assertIn("literal absolute skill directory", guide)
        self.assertIn(
            'TRAIGENT_FIRST_RUN_PYTHON="/absolute/path/to/the-selected-python"',
            evaluation_source,
        )
        self.assertIn(
            'TRAIGENT_FIRST_RUN_SKILL_DIR="/absolute/path/to/the-loaded-skill-directory"',
            evaluation_source,
        )
        self.assertIn(
            '"$TRAIGENT_FIRST_RUN_PYTHON" "$TRAIGENT_FIRST_RUN_SKILL_DIR/scripts/calibrate_evaluator.py"',
            evaluation_source,
        )
        self.assertNotIn(
            "python3 skills/traigent-first-run/scripts/",
            "\n".join(path.read_text() for path in assistant_facing_documents()),
        )
        self.assertNotIn("run the command from the repository root", evaluation)
        self.assertIn("installed skill's absolute directory", readme)
        self.assertIn("your project as the working directory", readme)

    def test_provenance_is_documented_as_a_per_row_average_with_ceilings(self) -> None:
        """Points and ceilings answer different questions; the guide says both.

        The per-row average is what stops one demo row condemning a collected
        dataset; the ceilings are what stop an average hiding how much of the
        result was invented. Documenting one without the other reads as either
        "generated data is fine" or "one bad row ruins it", and both are wrong.
        """
        dataset_text = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "was the question observed, and was the answer",
            "a mixture scores like a mixture",
            "99 collected rows and one generated one score 9.93, not 3",
            "provenance ceilings",
            "a ceiling is not a deduction and not a refusal",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, dataset_text)

        # An unknown word keeps its score but must never do so silently.
        self.assertIn("dataset-provenance-vocabulary", dataset_text)
        self.assertIn("is not silently demoted", dataset_text)

    def test_the_provenance_vocabulary_is_read_from_preflight_not_retyped(
        self,
    ) -> None:
        """A hand-typed roster drifted, and drifted in the silent direction.

        The prose listed 13 synthesised words against the module's 20, 10
        collected against 16, and framed the classification as binary - while
        `preflight.py` has a third class, `UNDECLARED_SOURCE_TOKENS`. A row
        declaring `provenance: "n/a"` therefore scored 6.0/10 with no vocabulary
        warning, which the documented two-list rule cannot account for. So the
        prose now names the three declarations and quotes no roster, and this
        checks the naming is real rather than decorative - the same weld
        `test_the_documented_schema_table_is_read_from_the_declaration` applies
        to the config-space table, which is the one prose table that never
        drifted.
        """
        spec = importlib.util.spec_from_file_location(
            "first_run_preflight_for_prose", SKILL_ROOT / "scripts" / "preflight.py"
        )
        preflight = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = preflight
        spec.loader.exec_module(preflight)
        source = (SKILL_ROOT / "references" / "evaluation-and-dataset.md").read_text()
        text = " ".join(source.casefold().split())

        for constant in (
            "SYNTHESISED_SOURCE_PREFIXES",
            "COLLECTED_SOURCE_PREFIXES",
            "UNDECLARED_SOURCE_TOKENS",
        ):
            with self.subTest(constant=constant):
                self.assertIn(constant, source, "the prose names no such constant")
                self.assertTrue(
                    hasattr(preflight, constant),
                    "the prose names a declaration preflight.py does not have",
                )
        # The third class is what the two-list framing hid, so the example
        # tokens must really belong to it.
        for token in ("n/a", "tbd"):
            self.assertIn(token, preflight.UNDECLARED_SOURCE_TOKENS)
        self.assertIn("raises no vocabulary warning", text)
        self.assertNotIn("a word on neither list", text)
        # The glossary is what the assistant phrases from, and it defined an
        # undeclared row as one that "does not record where it came from" -
        # false of the row that records `n/a`, which the card then prints as
        # `declared sources: n/a` beside that very word.
        glossary = " ".join(
            (SKILL_ROOT / "references" / "glossary.md").read_text().casefold().split()
        )
        entry = glossary.split("undeclared row -", 1)[1].split(" - ", 1)[0]
        self.assertIn("`n/a`", entry)
        self.assertNotIn("a row that does not record where it came from", glossary)
        # And the same sentence in the CARD, which is the artifact the customer
        # actually reads. The glossary was corrected for this and readiness.py
        # kept the false wording, so the fix reached the document a reader has
        # to go and look up and not the line printed in front of them: the card
        # said the row "does not record where it came from" and then printed
        # `declared sources: n/a` - what the row recorded - in the same
        # sentence. Pinned against readiness.py rather than a rendered card so
        # this cannot pass by the phrase merely moving.
        card_source = _READINESS.read_text()
        self.assertNotIn("the row does not record where it came from", card_source)
        self.assertIn("the row names no real source", card_source)
        # A retyped roster is what drifted; refuse its return. Counted over the
        # section, since one or two examples are explanation and a dozen is a
        # copy.
        section = source.split("### Declaring provenance", 1)[1].split("###", 1)[0]
        quoted = set(re.findall(r"`([a-z0-9/_-]+)`", section.casefold()))
        declared = set(preflight.SYNTHESISED_SOURCE_PREFIXES) | set(
            preflight.COLLECTED_SOURCE_PREFIXES
        )
        self.assertLessEqual(
            len(quoted & declared),
            3,
            "the vocabulary is being retyped here again; preflight.py declares it",
        )

    def test_the_modelled_status_lines_use_the_documented_row_count(self) -> None:
        """`component-creation.md`'s example is a line the customer sees.

        It showed "24 varied synthetic cases prepared" against the 18 every
        other document states, so an assistant copying the model announced a
        dataset size the run does not build. Read from the construction rule
        rather than pinned here, so the two cannot drift apart again.

        Swept over the whole corpus rather than over that one file, because
        fixing the instance left the class open: the count is restated three
        more times - SKILL.md's pricing scope, sdk-execution.md's walkthrough
        paragraph, and the rule itself - and a guard naming one restatement
        passed while another said something else. Probed: changing
        sdk-execution.md's copy to 24 and relocking left the suite green.

        The sweep is keyed on the PHRASINGS a row count is written in, not on a
        list of files, so a document that gains one of those sentences is
        covered without this test being edited.
        """
        dataset_text = (
            SKILL_ROOT / "references" / "evaluation-and-dataset.md"
        ).read_text()
        default = re.search(r"create (\d+) tuning examples by default", dataset_text)
        self.assertIsNotNone(default, "the generated dataset size is no longer stated")
        expected = int(default.group(1))

        counted = re.compile(
            r"(\d+)\s+(?:tuning rows|tuning examples|varied synthetic cases"
            r"|rows by default)"
        )
        statements: list[tuple[str, int]] = []
        for path in assistant_facing_documents():
            for match in counted.finditer(path.read_text()):
                statements.append((path.name, int(match.group(1))))
        # The rule plus its three restatements. Pinned so that DELETING a
        # restatement is a decision someone makes, not a way for this sweep to
        # quietly cover less than it did.
        self.assertEqual(
            len(statements),
            4,
            f"the walkthrough row count is now stated {len(statements)} times "
            f"({statements}); one home is better, but a new one must be welded "
            "here and a removed one accounted for",
        )
        for name, stated in statements:
            with self.subTest(document=name):
                self.assertEqual(
                    stated,
                    expected,
                    f"{name} states {stated} walkthrough rows against the "
                    f"construction rule's {expected}",
                )

        # And the difficulty breakdown, which is restated beside two of them and
        # has to add up to the same number. A breakdown summing to something
        # else is the same defect one level down, and it is the half a count
        # check cannot see.
        bands = re.compile(
            r"(\d+) easy,\s*(\d+) medium,\s*(\d+) hard,? and (\d+) very[ -]hard"
        )
        breakdowns = [
            (path.name, [int(value) for value in match.groups()])
            for path in assistant_facing_documents()
            for match in bands.finditer(" ".join(path.read_text().split()))
        ]
        self.assertTrue(breakdowns, "the difficulty breakdown is no longer stated")
        for name, counts in breakdowns:
            with self.subTest(document=name, breakdown=counts):
                self.assertEqual(
                    sum(counts),
                    expected,
                    f"{name}'s difficulty breakdown sums to {sum(counts)}, not "
                    f"the {expected} rows the rule builds",
                )

    def test_the_calibration_reject_list_states_what_actually_rejects(self) -> None:
        """Two of its items did not describe the helper that runs them.

        `binary` partial was written as "receiving a passing score", while the
        check is `partial <= --bad-maximum`: a binary partial at 0.50 is below
        the passing score and still exits 1, and the same file tells authors not
        to rely on unstated CLI defaults. And the exception item said "reject",
        twenty lines above the paragraph saying the advisory "never changes the
        authored probes' PASS" - which is what the helper does: a scorer with
        `except Exception: return 0.0` returns `"passed": true` and exit 0.
        """
        spec = importlib.util.spec_from_file_location(
            "first_run_calibrate_for_prose",
            SKILL_ROOT / "scripts" / "calibrate_evaluator.py",
        )
        calibrate = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = calibrate
        spec.loader.exec_module(calibrate)
        text = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        self.assertIn(
            f"partial output above `--bad-maximum` (`{calibrate.BAD_MAXIMUM}`)", text
        )
        self.assertNotIn("in `binary` mode, partial output receiving a passing", text)
        self.assertIn("nothing enforces this one", text)
        self.assertIn("the advisory never changes the authored probes' pass", text)

    # Every prose statement of the reasoning-headroom numbers, wherever it is
    # written. Fences are stripped first: `"max_tokens": 4096` inside a code
    # sample is the number being USED, not a claim about where it came from.
    _FENCED_BLOCK = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
    _HEADROOM_NUMBER = re.compile(r"\b(?:2048|4096)\b")
    # The vocabulary of a number that came from somewhere. This is the shape the
    # deleted citation had - not its wording - so a differently phrased retelling
    # ("the safety reference's measured minimum", "the derived high-effort
    # bound") fails on the same rule.
    _CLAIMS_A_DERIVATION = re.compile(
        r"\b(?:bound|bounds|derived|derivation|measured|benchmark\w*|computed|"
        r"calibrated|established|requirement|required)\b"
    )
    # The sentence has to be about the headroom floor itself, and it has to
    # name no source outside this package. Both narrowings exist because the
    # digits are not owned by this rule: `4096` appears in provider limits,
    # context windows and vendor documentation, and a sentence sourcing the
    # number to one of those is making a claim that HAS support. Refusing
    # those too would put a tripwire under nineteen contending branches for a
    # defect none of them is committing.
    _ABOUT_THE_HEADROOM_FLOOR = re.compile(r"max_tokens|headroom|reasoning effort")
    _NAMES_AN_OUTSIDE_SOURCE = re.compile(
        r"\b(?:provider|providers|vendor|vendors|api|apis|litellm|openai|"
        r"anthropic|upstream|documented|documentation|docs|context window|"
        r"model card|release note\w*)\b"
    )

    def _headroom_citation_offence(self, sentence: str) -> str | None:
        """Return the derivation word a sentence claims without support, if any."""
        if not self._HEADROOM_NUMBER.search(sentence):
            return None
        lowered = sentence.casefold()
        if not self._ABOUT_THE_HEADROOM_FLOOR.search(lowered):
            return None
        if self._NAMES_AN_OUTSIDE_SOURCE.search(lowered):
            return None
        claimed = self._CLAIMS_A_DERIVATION.search(lowered)
        return claimed.group(0) if claimed else None

    def test_the_reasoning_headroom_numbers_are_never_cited_as_derived(self) -> None:
        """The `max_tokens` numbers are a judgement, and one file cited them as a result.

        `run-safety.md` asserts `max_tokens` of at least 2048, and 4096 with
        high reasoning effort, and derives neither from anything - no
        measurement, no vendor limit, no trial. `sdk-execution.md` then cited
        that assertion as "the safety reference's high-effort bound", which is
        circular: the only support for the number was the sentence being cited,
        and "bound" tells a reader it has support it does not have. The fix was
        to stop claiming a derivation, not to invent one, so what has to hold
        afterwards is that NO document reintroduces the claim - in any wording.

        Pinned by shape rather than by the one phrase that was removed. A
        future "the measured 4096 floor" or "the derived headroom bound" fails
        here even though neither contains the deleted words. The positive half
        is asserted too: the owning statement must still say the numbers are
        unmeasured, so the rule cannot be satisfied by deleting the honesty
        along with the citation.

        Scoped, though, to the claim it is actually about. The first version of
        this guard checked every sentence anywhere in the corpus that merely
        contained `2048` or `4096`, which put a veto over two digits this rule
        does not own: "4096 is required by this provider" is a real derivation
        from a real source and would have failed. So a sentence offends only
        when it is about the headroom floor AND sources the number to nothing
        outside this package. Both examples are asserted below, because a
        widened pattern that starts refusing the legitimate one is the
        regression, and it would otherwise show up as somebody else's branch
        failing for a reason this test never explained.
        """
        # The sentence this rule was actually written against, verbatim from
        # the commit that removed it.
        self.assertEqual(
            self._headroom_citation_offence(
                "Set `max_tokens` at least 4096 (the safety reference's "
                "high-effort bound, applied flat here)."
            ),
            "bound",
        )
        # And a retelling that shares none of its words.
        self.assertEqual(
            self._headroom_citation_offence(
                "2048 is the measured answer headroom floor."
            ),
            "measured",
        )
        self.assertIsNone(
            self._headroom_citation_offence(
                "A `max_tokens` of 4096 is required by this provider."
            )
        )
        self.assertIsNone(
            self._headroom_citation_offence(
                "The retry budget is derived from 4096 recorded runs."
            )
        )

        offenders: list[str] = []
        for document in assistant_facing_documents():
            body = self._FENCED_BLOCK.sub("", document.read_text())
            for sentence in re.split(r"(?<=\.)\s+", " ".join(body.split())):
                claimed = self._headroom_citation_offence(sentence)
                if claimed:
                    offenders.append(
                        f"{document.relative_to(ROOT).as_posix()}: "
                        f"{claimed!r} in {sentence!r}"
                    )
        self.assertEqual(
            offenders,
            [],
            "a reasoning-headroom number is presented as derived from "
            "something; it is an unmeasured defensive floor, and the only "
            "support for it is the sentence asserting it",
        )
        owner = " ".join(RUN_SAFETY.read_text().casefold().split())
        self.assertIn("unmeasured defensive floor", owner)

    # The sentence that chooses grid over random, wherever it is written. A
    # threshold reintroduced as "40 configurations per trial" or "ten times the
    # trial cap" fails the same way the deleted "roughly twenty" did.
    _GRID_TO_RANDOM = re.compile(r"\bgrid\b.{0,400}?\brandom\b", re.IGNORECASE)
    _A_RATIO = re.compile(
        r"\b(?:\d+(?:[.,]\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"twelve|twenty|fifty|hundred)\b\s*(?:x|times|-fold|per|configurations?\s+per)"
        r"|\bper\s+(?:allowed\s+)?trial\b|\btimes\s+the\s+trial\s+cap\b",
        re.IGNORECASE,
    )

    def test_the_grid_to_random_switch_is_not_stated_as_a_threshold(self) -> None:
        """`sdk-execution.md` named a crossover nothing in this repository computes.

        It said a preserved baseline moves from `grid` to `random` above
        "roughly twenty configurations per allowed trial". No code chooses an
        algorithm anywhere in this package - the scripts are offline scorers,
        and the choice is prose the assistant follows - so the number had no
        derivation, no test, and no other document to agree with. It is the
        same defect as the `max_tokens` citation above, one step worse: that
        one at least cited a sentence.

        The digit is the trap. `readiness.py` damps the knob-count sub-score
        when `space_size > 20 * max_trials`, and that is a DIFFERENT
        subsystem - it lowers a readiness number, it does not decide how a
        search is run. Reading across from it would manufacture the derivation
        this fix removed, out of a coincidence. So the rule here is stated
        qualitatively, and this test refuses any threshold, including the one
        that would look like a match.

        Pinned by shape, like the headroom rule: any ratio in the sentence that
        chooses between the two algorithms fails, not just the phrase deleted.
        The positive half holds the qualitative rule in place so the check
        cannot be satisfied by deleting the guidance instead of the number.
        """
        offenders: list[str] = []
        for document in assistant_facing_documents():
            body = self._FENCED_BLOCK.sub("", document.read_text())
            for sentence in re.split(r"(?<=\.)\s+", " ".join(body.split())):
                if not self._GRID_TO_RANDOM.search(sentence):
                    continue
                ratio = self._A_RATIO.search(sentence)
                if ratio:
                    offenders.append(
                        f"{document.relative_to(ROOT).as_posix()}: "
                        f"{ratio.group(0)!r} in {sentence!r}"
                    )
        self.assertEqual(
            offenders,
            [],
            "the grid-to-random choice is stated as a numeric threshold. "
            "Nothing in this repository computes one - readiness.py's "
            "20 * max_trials damps a score in another subsystem and is not "
            "this rule - so the number would have no support but itself",
        )
        owner = " ".join(SDK_EXECUTION.read_text().casefold().split())
        self.assertIn("could not reach most of it", owner)

    # An authoring label: the artifact ordinal and template letter a drafter
    # uses to say which block this is, which is not a thing the reader knows
    # about. Matched by shape, because the one that leaked ("Artifact-2
    # template A:") is one of a family, and the next will carry a different
    # ordinal or letter.
    _AUTHORING_LABEL = re.compile(
        r"\bartifact[\s-]?\d+\b|\btemplate\s+[A-Z]\b\s*:", re.IGNORECASE
    )

    def test_no_document_carries_an_authoring_label_into_what_the_user_sees(
        self,
    ) -> None:
        """`Artifact-2 template A:` was a drafting marker, printed as guidance.

        It sat at the head of a paragraph telling the assistant what to show
        after portal registration, so the passage the user is quoted began with
        an internal ordinal naming a template nothing in this repository
        defines. There is no artifact numbering here to resolve it against; it
        was residue from how the passage was written, and it was removed rather
        than explained.

        Checked over the whole corpus and by shape, for the reason the deletion
        exists: the label is not wrong about anything, so nothing else fails
        when one reappears, and the next one will be `Artifact-3` or `template
        B`. Both spellings of the family are refused, in every document that can
        reach a user.
        """
        labelled: list[str] = []
        for document in conversation_contract_documents():
            for match in self._AUTHORING_LABEL.finditer(document.read_text()):
                labelled.append(
                    f"{document.relative_to(ROOT).as_posix()}: {match.group(0)!r}"
                )
        self.assertEqual(
            labelled,
            [],
            "a drafting label naming an artifact ordinal or template letter is "
            "in prose the assistant reads out; nothing here defines that "
            "numbering, so it names a thing the reader cannot look up",
        )

    def test_the_card_labels_the_readme_documents_are_the_ones_it_prints(
        self,
    ) -> None:
        """README named three labels; the code prints four.

        `PAID RUN BLOCKED` is the headline flag, and every blocking condition
        beneath it prints `FIX BEFORE PAID RUN` - the line that actually tells
        the reader what to do, and the only one the public explanation omitted.
        """
        readme = (ROOT / "README.md").read_text()
        card_source = _READINESS.read_text()
        for label in (
            "PAID RUN BLOCKED",
            "FIX BEFORE PAID RUN",
            "LIMITED TO",
            "WOULD LIMIT TO",
        ):
            with self.subTest(label=label):
                self.assertIn(label, card_source)
                self.assertIn(label, readme)

    def test_progress_promises_are_observable(self) -> None:
        """A synchronous run cannot promise a checkpoint it cannot expose."""
        normalized = " ".join(SKILL.read_text().casefold().split())
        sdk = " ".join(SDK_EXECUTION.read_text().casefold().split())
        for phrase in (
            "30-minute completion target",
            "not a hard wall-clock guarantee",
            "never promise a pause at minute 30",
            "only observable phase milestones",
            "never invent progress",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)
        self.assertIn("uncapped by default", sdk)
        self.assertNotIn("reaching that ceiling is a decision point", normalized)

    def test_user_journey_is_numbered_and_reports_measured_progress(self) -> None:
        guide = " ".join((ROOT / "GUIDE.md").read_text().casefold().split())
        skill = " ".join(SKILL.read_text().casefold().split())
        self.assertIn("welcome to traigent onboarding!", guide)
        for stage in ("inspect", "readiness", "baseline", "optimize", "results"):
            self.assertIn(f"**{stage}**", guide)
        self.assertIn("stage <n>/5", skill)
        self.assertIn("with measured numbers when available", guide)
        self.assertIn("readiness score, rows checked, calls/trials, cost", skill)
        self.assertIn("finished stages as compact checkmarks", skill)

    def test_the_opening_card_states_its_blank_lines_without_hedging(self) -> None:
        """Four hedges over a state the scorer produces unconditionally.

        SKILL.md mandates omitting *every* config-space file found before this
        run's enhanced search, on every guided run including a zero-anchor one.
        So no settings document ever reaches an opening score: `score_agent`
        takes the no-document branch every time, `nothing_to_search_pillar`
        marks two of its three sub-scores unmeasured behind one shared evidence
        string, and the opening card reads `1 of 3 checks measured` for a
        perfect project as readily as for a broken one. Measured against a
        60-row production-sourced dataset and a passing deterministic
        evaluator: `45/100 PARTIAL`, agent `1 of 3`, evaluation `2 of 4`.

        The glossary called that "usually", and counted two blank lines where
        the card prints three - the third being the whole Agent pillar, which
        never names its own three checks because they collapse into that one
        line. A reader who is told "usually" goes looking for what they did
        wrong; there is nothing to find.
        """
        glossary = " ".join(
            (SKILL_ROOT / "references" / "glossary.md").read_text().casefold().split()
        )
        for phrase in (
            # Unconditional, because the mandate is.
            "an opening score always reports that none was provided yet",
            "why three lines are blank at the start, every time",
            # The third blank named, and named as a pillar rather than a check.
            "the third is the whole agent pillar",
            "no settings document ever reaches an opening score",
            # Why its three named lines never print by name.
            "one absent input is one finding, not three",
            # And the point of the paragraph, which survives the correction.
            "none of them is something you were supposed to bring",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, glossary)
        for hedge in (
            "an opening score usually reports",
            "why two of them are usually blank",
        ):
            with self.subTest(hedge=hedge):
                self.assertNotIn(hedge, glossary)

        # The mandate this is read off, so the two cannot drift apart silently.
        skill = " ".join(SKILL.read_text().casefold().split())
        self.assertIn(
            "explicitly omit every config-space file found before this run's "
            "enhanced search",
            skill,
        )
        self.assertIn("every guided run does this", skill)

    def _opening_card(self, evaluation: int, dataset: int) -> tuple[int, str]:
        """Score one modelled opening card: no settings document, so 45 caps it.

        The opening card is defined by what it lacks - SKILL.md mandates that no
        config space is supplied on the first pass - so `agent-no-varying-knobs`
        is always among its caps and the agent pillar always scores 0. The other
        two pillars are what a real project varies, so they are the sweep.
        """
        pillars = [
            READINESS.Pillar(
                name="dataset", score=dataset, confidence=1.0, subscores=()
            ),
            READINESS.Pillar(
                name="evaluation", score=evaluation, confidence=1.0, subscores=()
            ),
            READINESS.Pillar(name="agent", score=0, confidence=1.0, subscores=()),
        ]
        scored = READINESS.aggregate(
            pillars,
            caps=[READINESS.NOTHING_WIRED_CAP],
            knobs=(),
            weights=dict(READINESS.DEFAULT_WEIGHTS),
        )
        return scored.overall, scored.band

    def test_the_band_sentence_matches_what_calibration_can_actually_move(
        self,
    ) -> None:
        """README told a first-time reader to calibrate and watch the band move.

        The band does not move past Partial there, and the code says why before
        any run: the opening card has no settings document by mandate, so
        `agent-no-varying-knobs` caps the whole score at 45, and 45 is Partial.

        Two later corrections, both measured on this sweep of 121 modelled
        opening shapes (dataset and evaluation pillars over 0..100 by 10):

        * 45 is an UPPER BOUND, not the score. No shape lands above it and 79
          of the 121 land below - 0, 4, 12, 35 and so on - held there by the
          weighted average rather than by the cap. "Holds the whole score at
          45" was true of 42 shapes and false of the other 79.
        * "It moves the band only once the score is clear of every ceiling" was
          false in the same sweep: calibrating moves the number in 76 of the 79
          below-ceiling shapes and the BAND in 39 of them, all NOT READY ->
          PARTIAL, while the 45 ceiling is still the binding limit. Measured
          end to end as well: 12 rows, undeclared provenance, `llm-judge-rubric`
          and no config space score 35/100 PARTIAL at the opening and 45/100
          PARTIAL after calibration - the number moved 10 points.

        What survives both is the ceiling: nothing calibration does can carry
        the card past 45, so Partial is the best the opening can report, and at
        the ceiling itself the card is genuinely unchanged (0 of the 42 shapes
        already at 45 move at all). That is the property asserted here, rather
        than the sentence's spelling - and the README requirement is derived
        from the sweep, so retuning the cap into an exact score, or widening it,
        fails this test instead of quietly outdating the paragraph.
        """
        self.assertEqual(READINESS.CONFIDENCE_BAND_CEILING, "WORKABLE")
        order = READINESS.BAND_ORDER
        self.assertLess(order.index("PARTIAL"), order.index("WORKABLE"))
        # 45 really is PARTIAL, so the sentence's arithmetic is the code's.
        self.assertEqual(READINESS.band_for(45, 1.0)[0], "PARTIAL")
        # And a band at or below the ceiling is never lifted by more
        # evidence, nor demoted for the lack of it: thin or full, 45 is
        # PARTIAL, which is why the ceiling is what bounds the opening card.
        self.assertEqual(READINESS.band_for(45, 0.35, 0.35), ("PARTIAL", False))

        shapes = [
            (evaluation, dataset)
            for evaluation in range(0, 101, 10)
            for dataset in range(0, 101, 10)
        ]
        landings = {self._opening_card(*shape)[0] for shape in shapes}
        # A ceiling, so nothing reaches past it, and the band it allows is the
        # best the opening card can print.
        self.assertEqual(max(landings), READINESS.NOTHING_WIRED_CAP.ceiling)
        self.assertEqual(READINESS.band_for(max(landings), 1.0)[0], "PARTIAL")

        at_ceiling = [s for s in shapes if self._opening_card(*s)[0] == max(landings)]
        below = [s for s in shapes if self._opening_card(*s)[0] < max(landings)]
        # Calibrating the evaluator is modelled as that pillar reaching 100.
        moved_at_ceiling = [
            s
            for s in at_ceiling
            if self._opening_card(100, s[1]) != self._opening_card(*s)
        ]
        moved_below = [
            s for s in below if self._opening_card(100, s[1]) != self._opening_card(*s)
        ]
        self.assertEqual(moved_at_ceiling, [])

        readme = " ".join((ROOT / "README.md").read_text().casefold().split())
        for phrase in (
            "the card names which pillar is thin",
            "`evaluation 100/100 (2 of 4 checks measured)`",
            "calibrating the evaluator is what fills that one in",
            "cannot carry the band past partial",
            "leaves `45/100 partial` exactly where it was",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)
        self.assertNotIn("calibrating the evaluator is usually what moves it", readme)

        # The two claims this test now derives rather than restates. Each
        # branch is reachable: a cap that pinned the score would make `below`
        # empty, and one that never bound anything would make `at_ceiling`
        # empty, and either would demand the other sentence here.
        if below:
            self.assertIn("holds the whole score to at most 45", readme)
            self.assertNotIn("holds the whole score at 45", readme)
        else:
            self.assertIn("holds the whole score at 45", readme)
        if moved_below:
            # Something below the ceiling does move, so the README may not
            # claim the opening card is frozen until every ceiling is cleared.
            self.assertNotIn("only once the score is clear of every ceiling", readme)
            self.assertIn("where 45 is already the number", readme)
        else:
            self.assertIn("only once the score is clear of every ceiling", readme)

    def test_local_example_retention_is_stated_the_same_way_in_both_homes(
        self,
    ) -> None:
        """A retention claim a customer reads must not be softer than the rule.

        `run-safety.md` states the fact correctly - the SDK writes example
        `query`, `response` and `expected` text to local logs **by default**,
        which is precise because `TRAIGENT_LOG_EXAMPLE_CONTENT` controls it.
        README said "normally", which reads as a tendency rather than a
        setting, in the one paragraph a reader consults to decide whether their
        prompts and answers stay on their machine. Same fact, same words.
        """
        readme = " ".join((ROOT / "README.md").read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        claim = (
            "`query`, `response`, and `expected` text to local optimization "
            "logs by default"
        )
        for text in (readme, safety):
            with self.subTest(document="readme" if text is readme else "run-safety"):
                self.assertIn(claim, text)
        self.assertNotIn("normally writes each example's", readme)
        # The env var is what makes "by default" the right word, so both homes
        # have to keep naming it.
        for text in (readme, safety):
            self.assertIn("traigent_log_example_content=false", text)

    def test_continue_cta_is_direct_and_evidence_based(self) -> None:
        readme = " ".join((ROOT / "README.md").read_text().casefold().split())
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        guidance = f"{skill} {safety}"

        for phrase in (
            "recommended next: continue with traigent optimization because <observed reason>",
            "continue with this bounded traigent run?",
            "do not manufacture urgency",
            "reply-ready line",
            "it approves nothing unless",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, guidance)
        self.assertIn("when the measured results show useful headroom", readme)
        self.assertIn("or address the strongest observed limitation first", readme)

    def test_readiness_is_explained_as_progress_without_invented_animation(
        self,
    ) -> None:
        skill = " ".join(SKILL.read_text().casefold().split())
        glossary = " ".join(
            (SKILL_ROOT / "references" / "glossary.md").read_text().casefold().split()
        )
        presentation = f"{skill} {glossary}"
        for phrase in (
            "stage 2/5 · readiness - <score>/100 (<band>)",
            "what the score measures",
            "the strongest evidence",
            "the one limitation that most affects the next action",
            "<opening> → <current>",
            "do not animate with invented progress",
        ):
            self.assertIn(phrase, presentation)

    def test_enhanced_detail_waits_for_the_baseline_checkpoint(self) -> None:
        skill = " ".join(SKILL.read_text().casefold().split())
        stage_six = skill.split("### 6. approve and run the baseline", 1)[1].split(
            "### 7. run the honest comparison", 1
        )[0]
        stage_seven = skill.split("### 7. run the honest comparison", 1)[1].split(
            "### 8. verify and report", 1
        )[0]
        self.assertIn("do not front-load its algorithm", stage_six)
        for premature_detail in (
            # #123's follow-up retired the "10-13-trial enhanced target"
            # phrasing for a ceiling. The detail this gate keeps out of the
            # baseline stage is the same one, so it is named the new way -
            # an assertNotIn on a string no longer written anywhere reads as
            # coverage while providing none.
            "up to 12 configurations",
            "12-configuration ceiling",
            "connected traigent runs synchronize",
            "portal history/direct links",
        ):
            self.assertNotIn(premature_detail, stage_six)
        self.assertLess(
            stage_seven.index("show a **local baseline checkpoint**"),
            stage_seven.index("stage 4/5 · optimize"),
        )
        self.assertIn("stage 4/5 · optimize", stage_seven)
        self.assertIn("portal history", stage_seven)
        self.assertIn("conditional capabilities", stage_seven)
        self.assertIn("obtain explicit approval for this connected stage", stage_seven)
        baseline_checkpoint = stage_seven.index("show a **local baseline checkpoint**")
        evidence_gate = stage_seven.index(
            "now check whether the dataset and evaluator distinguish configurations"
        )
        connected_preview = stage_seven.index(
            "only when this gate supports a measured opportunity"
        )
        connected_approval = stage_seven.index("stage 4/5 · optimize")
        self.assertLess(baseline_checkpoint, evidence_gate)
        self.assertLess(evidence_gate, connected_preview)
        self.assertLess(connected_preview, connected_approval)
        self.assertIn("stop before the search", stage_seven)
        for document in (SKILL, RUN_SAFETY, ROOT / ".env.example"):
            self.assertNotIn("combined approval", document.read_text().casefold())

    def test_run_plan_records_stage_specific_approvals(self) -> None:
        plan = " ".join(
            (SKILL_ROOT / "assets" / "run-plan.md").read_text().casefold().split()
        )
        self.assertIn("baseline plan and approval", plan)
        self.assertIn("baseline approval - status/scope/ceiling", plan)
        self.assertIn("connected-stage plan and approval", plan)
        self.assertIn(
            "connected-stage approval - status/scope, spend, remaining ceiling",
            plan,
        )
        self.assertLess(
            plan.index("baseline approval - status/scope/ceiling"),
            plan.index("local baseline checkpoint"),
        )
        self.assertLess(
            plan.index("local baseline checkpoint"),
            plan.index(
                "connected-stage approval - status/scope, spend, remaining ceiling"
            ),
        )

    def test_no_internal_tooling_is_named_in_this_public_package(self) -> None:
        """This repository is public; the tools that test it are not.

        Naming an internal repository or its test bank here leaks both its
        existence and, worse, what it does or does not cover - a reader learns
        where the gaps are. It has been scrubbed once already and came back
        through a test docstring crediting where a finding came from, which is a
        natural thing to write and exactly the thing that must not ship.

        Credit the mechanism ("a consumer that cross-checks the action against
        the caps") rather than the tool, and this stays true.

        Two things this got wrong, both found with the leak live and this test
        green. It matched file CONTENTS only, so an internal name in a FILENAME
        was invisible by construction - two published reports carried one in
        their names for their whole life. And its vocabulary covered only the
        internal test bank, so internal INFRASTRUCTURE walked straight past it:
        a private repository, two cluster names, an internal observability
        stack, and a non-production hostname that resolves publicly.
        Paths are checked now, and the vocabulary covers both families - as
        digests, because a public file listing them is the leak it guards.
        """
        # The names are NOT in this file, in any readable form. They used to be,
        # assembled from two adjacent fragments each, which defeats `grep` for
        # the exact string and defeats no reader at all: the fragments sat next
        # to each other in one tuple, under a comment saying what they were. A
        # public repository holding a plaintext inventory of private clusters,
        # hosts and datasets is the disclosure this test exists to prevent, and
        # the guard was the last place still doing it.
        #
        # So each name is stored as the sha256 of itself, and the check hashes
        # the TEXT instead of reading the names. That is a change to what this
        # file reveals, not to what the check catches: `token.casefold() in
        # text.casefold()` is exactly "some window of len(token) in the
        # casefolded text equals the token", so hashing every window of every
        # stored length and looking it up decides the same predicate, character
        # for character. The lengths are here because that equivalence needs
        # them - without them there is no window to hash.
        #
        # To add a name, without ever putting it in a file (mind shell history):
        #   python3 -c 'import hashlib,sys;b=sys.argv[1].casefold().encode();\
        #   print(len(b),hashlib.sha256(b).hexdigest())' 'the name'
        # then insert the length and the digest below, keeping both sorted.
        #
        # What this still discloses, exactly: how many names there are, and the
        # multiset of their lengths. The two are deliberately NOT paired - the
        # algorithm does not need the pairing, and the pairing is the part a
        # guesser would use to narrow a search. And a digest of a short,
        # guessable name is a confirmation oracle rather than a secret - anyone
        # who already suspects `<something>-dev` can hash it and test it against
        # this set, and no salt can fix that, because the salt would have to
        # ship here too. It stops a reader LEARNING the estate; it does not stop
        # someone CONFIRMING a name they had already guessed. That is the whole
        # of what it buys - and it is worth buying, because the reader who was
        # learning the estate from this file was not guessing.
        #
        # Two families are covered: the internal test bank and its harness, and
        # internal infrastructure - a private repository, two clusters, an
        # internal observability stack, a non-production host. Only what no
        # structural rule below can reach belongs here.
        forbidden_lengths = (7, 10, 12, 13, 15, 17, 18, 24)
        forbidden_digests = frozenset(
            bytes.fromhex(digest)
            for digest in (
                "001794b3d3cdd97012ef80c1e46ea9f688286ece5e89ed910c5ff003ec24110b",
                "0ca18865d86f87b138d88f539fd0727f4240a2836842436f86ea31f07c506b43",
                "2595809007003a29ceb06e6ff7b42e7f79a613dec7f27f8a95c307dd39d95c6e",
                "29598efb405e50a72098d65e2e8e8b06f66ac45ff3b5890976cbaa7ad0653da4",
                "422bc40ddc42faf8dfbe083b601daf85e828de904e3d38b2941265e4c0200186",
                "4f7f51f01a2ca6b25bea64840d28bb572441d9862cca573c4b1f2ee40dc12ac7",
                "50ffa53cfa10a5cfc2eacf9a270071d184abb026770822a42a4208f47c60d5e9",
                "5e4bce6b1241887627c40c217bbbc3449cf1671fee397a1b491e8216ae04e704",
                "634c62abdbffeefb6b7376779adfccfaca27551686418a9fba835c24f8d2e23e",
                "a11358728514ae1c6d7a65d99c3ac5dba1d159a302b09774af7415fe0493a5f2",
                "f356164dd71afbb8770f4a004585d0378da7c9996b9cc41804719d89b86d2e5d",
            )
        )
        # A denylist only ever knows what already leaked. Two structural rules
        # cover the classes instead, so the next name nobody has thought of is
        # caught the first time rather than after the incident.
        #
        # 1. Repository references are checked against an ALLOWLIST of the
        #    organisation's PUBLIC repositories. That inversion matters: the
        #    private set is 47 today and grows whenever someone creates a repo,
        #    so a denylist of it is stale by construction, while the public set
        #    is 6 and changes rarely. Anything not on it fails closed.
        # 2. A bare UUID is never customer guidance. Every one that shipped was
        #    a real session or experiment identifier from a production run.
        public_repos = {
            "traigent",
            "traigent-first-run",
            "traigent-web",
            "traigent-skills",
            "tvl",
            "traigentschema",
        }
        # Case-INSENSITIVE, because GitHub owner segments are: a URL written
        # `github.com/traigent/<repo>` resolves to exactly the same repository
        # as `Traigent/<repo>`, and the lowercase form is what people actually
        # type into a URL. (This comment cannot spell the leak out with a real
        # example, because the guard reads its own file and would flag it -
        # which is itself the demonstration.) An earlier revision matched
        # case-SENSITIVELY to spare the SDK's Python package path
        # `traigent/config_generator/presets/...`, which readiness.py cites
        # legitimately - but that bought one false red back at the cost of
        # opening the entire class: every private repository passed when the
        # organisation was written in lowercase.
        # The discriminator is structural instead of orthographic. A package
        # path continues into a further segment (`traigent/config_generator/`),
        # while a repository reference ends there - unless it is a github.com
        # URL, where a trailing slash leads to `/blob/...` rather than into a
        # package. So: a trailing slash means "package path" only when no host
        # precedes it.
        # That shape is a HOLE, and it is the one #160 asks be closed. A trailing
        # slash is exactly what a source-path citation has - the reference this
        # guard most needs to catch is a private repository followed by the file
        # inside it - so the exemption let every one of those through. The
        # CamelCase rule below caught the concatenated names by accident and the
        # rest passed clean: an owner segment, a private repository, then a file
        # path was silent whenever that repository was named in
        # lowercase-and-hyphens or in snake_case, which several of ours are.
        # So the exemption is inverted the same way the repository rule already
        # is: an ALLOWLIST of the package roots this package genuinely cites,
        # rather than a shape that lets an unbounded class through. It has one
        # member because exactly one is cited - readiness.py's vendored preset
        # path - and anything else fails closed. Adding to it is a decision
        # someone has to make, which is the property the shape rule never had.
        package_roots = {"config_generator"}
        # Kept separate from public_repos on purpose: these are not
        # repositories at all, they are slash-joined product phrases ("the
        # Traigent/LiteLLM import path"). Calling them public would be a
        # different claim from calling them not-a-repo, and the distinction is
        # what stops this exception quietly widening.
        not_repositories = {"litellm"}
        repo_reference = re.compile(
            r"(?P<host>github\.com/)?traigent/(?P<repo>[A-Za-z0-9._-]+)(?P<tail>/)?",
            re.IGNORECASE,
        )
        uuid_reference = re.compile(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
            re.IGNORECASE,
        )
        # A private repository named WITHOUT the `Traigent/` prefix - the bare
        # CamelCase form, in prose or in a filename - is invisible to the rule
        # above, which needs the organisation segment to anchor on. The
        # obvious repair is to add all 47 private names to `forbidden`, and it
        # is the wrong one: this file is published, so every name added to it
        # is itself disclosed, and a denylist of a set that grows weekly is
        # stale the moment someone creates a repo.
        # So match the SHAPE instead. Internal repositories are `Traigent` +
        # CamelCase; the public ones that share it are already in the allowlist
        # and are checked against it, so this needs to know nothing secret to
        # fail closed on a name nobody has seen yet.
        internal_repo_shape = re.compile(r"\bTraigent[A-Z][A-Za-z0-9]*")
        # ACCEPTED RESIDUAL, recorded here rather than left for the next reader
        # to rediscover: the three rules above are anchored on an organisation
        # segment (`<owner>/<repo>`) or on the `Traigent` + CamelCase shape, so a
        # private repository whose name carries NEITHER is invisible to all of
        # them. Bare lowercase-and-hyphens and bare snake_case names exist in
        # this organisation, and written on their own - no owner segment, no
        # capital - only the hashed denylist can reach them. That denylist
        # stores eight window lengths, which does not span every such name, so
        # some are not covered at all.
        # This is not a bug to be fixed here, and the fix that suggests itself
        # is worse than the gap: a complete denylist of private names would have
        # to be written into this published file, which discloses exactly what
        # it is protecting. The structural rules are deliberately the ones that
        # can be stated in public without leaking; the residual is the price.
        # What closes it is a private pre-publish scan, not a rule in this file.
        # Do not "repair" this by adding names.
        # The two canonical documentation placeholders (RFC 9562 nil and max).
        # A guide that documents experiment and session identifiers has to be
        # able to show the shape of one, and a guard that answers "you leaked a
        # production identifier" to the nil UUID is wrong in the way that
        # teaches an author to route around it. Only these two literals are
        # exempt - there is deliberately no `example-` prefix escape, because
        # that would let a real identifier through behind a marker.
        uuid_placeholders = {
            "00000000-0000-0000-0000-000000000000",
            "ffffffff-ffff-ffff-ffff-ffffffffffff",
        }
        # The file list comes from git, not a filesystem walk. `harness.py`
        # already learned this: a walk needs a hand-maintained list of what to
        # skip, and that list can only ever name the droppings someone already
        # hit. The first version of this check inverted it into an extension
        # ALLOWLIST, which is the same fragility - it silently ignored the
        # dataset `.jsonl` fixtures, `.env.example`, and every extensionless
        # file, any of which can carry prose. Git also answers the question this
        # test actually asks, which is what gets PUBLISHED, not what happens to
        # sit in the working tree.
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            capture_output=True,
            text=True,
            check=False,
        )
        if listed.returncode != 0:
            raise RuntimeError(
                f"could not list tracked files from git: {listed.stderr.strip()}"
            )

        def scan(text: str, where: str) -> list[str]:
            """Every rule, over one string - a filename as readily as a body.

            The rules used to be split by accident rather than by intent: the
            token denylist ran over both, while the repository and UUID rules
            ran over file CONTENTS only. That made a leak in a *filename*
            invisible to them by construction, which is the same shape of
            omission this test exists to close - and two of the three reports
            this pull request deletes leaked through their names as much as
            their bodies.
            """
            found: list[str] = []
            # Every window of every stored length, hashed and looked up. The
            # naming of the offender comes from the TEXT, not from the digest
            # set - which is the point: this message can only ever print a
            # string the scanned file already contains, so a failure reports
            # the leak that is in front of it without this file knowing the
            # names. It prints the casefolded form, because that is the string
            # that was matched; the author is looking at their own sentence, so
            # the case is not what they need told. Bytes rather than characters
            # is safe and not an approximation: UTF-8 is self-synchronising, so
            # a byte sequence occurs in the encoding exactly when the string
            # occurs in the text.
            blob = text.casefold().encode("utf-8", "surrogatepass")
            leaked: set[str] = set()
            for length in forbidden_lengths:
                for start in range(len(blob) - length + 1):
                    window = blob[start : start + length]
                    if hashlib.sha256(window).digest() in forbidden_digests:
                        leaked.add(window.decode("utf-8", "replace"))
            for name in sorted(leaked):
                found.append(f"{where}: {name!r}")
            for match in repo_reference.finditer(text):
                if (
                    match.group("tail")
                    and not match.group("host")
                    and match.group("repo").casefold() in package_roots
                ):
                    continue  # a cited package path, not a repository
                # `foo.git` and a sentence-final `foo.` are the same repository
                # as `foo`. Without this, the canonical clone URL of a PUBLIC
                # repo fails the check, and the failure message invites the
                # author to "fix" it by adding `traigent-first-run.git` to the
                # allowlist - which is how an allowlist fills up with junk.
                repo = match.group("repo").rstrip(".")
                if repo.casefold().endswith(".git"):
                    repo = repo[: -len(".git")]
                # `Traigent/LiteLLM` and similar prose are not repositories;
                # only flag a name that is not a known public repo AND looks
                # like one of ours.
                if repo.casefold() in not_repositories:
                    continue
                if repo.casefold() not in public_repos:
                    found.append(
                        f"{where}: names a non-public repository {repo!r} "
                        "(add it to public_repos only if it really is public)"
                    )
            for camel in internal_repo_shape.findall(text):
                if camel.casefold() in public_repos:
                    continue
                found.append(
                    f"{where}: names a non-public repository {camel!r} "
                    "(add it to public_repos only if it really is public)"
                )
            for match in uuid_reference.finditer(text):
                if match.group(0).casefold() in uuid_placeholders:
                    continue
                found.append(
                    f"{where}: contains a bare UUID - every one that has "
                    "shipped was a real session or experiment identifier"
                )
            return found

        offenders: list[str] = []
        for name in listed.stdout.split("\0"):
            if not name:
                continue
            path = ROOT / name
            # The PATH is checked before the contents, and unconditionally: a
            # file that cannot be decoded still has a name, and a name is
            # published in the tree listing whether or not anyone opens it.
            offenders.extend(scan(name, f"{name} (in the filename)"))
            try:
                raw = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary or deleted-but-tracked; no prose to leak
            offenders.extend(scan(raw, name))
        self.assertEqual(offenders, [], "internal tooling named in a public repository")

        # The tree being clean proves nothing about what the guard can SEE, and
        # the source-path exemption is where it saw nothing. Each string below
        # is a shape that shipped through the old rule: an owner segment, a
        # private repository, then the file inside it - the single most likely
        # way one of ours gets cited, and silent whenever the repository name
        # carried no capital letter for the CamelCase rule to catch.
        for shape in (
            "traigent/{}/docs/index.md",
            "Traigent/{}/README.md",
            "github.com/traigent/{}/blob/main/x.py",
        ):
            for invented in ("not-a-real-repo", "not_a_real_repo", "notarealrepo"):
                probe = shape.format(invented)
                with self.subTest(probe=probe):
                    self.assertNotEqual(scan(probe, "probe"), [])
        # And the one path the exemption exists for still passes, or the guard
        # has been tightened into a false red that teaches authors to route
        # around it - which is how the exemption was born.
        self.assertEqual(scan("traigent/config_generator/presets/x.py", "probe"), [])

    def test_the_glossary_distinguishes_a_ceiling_from_a_block(self) -> None:
        """The user-facing definition has to follow the code that changed.

        The glossary is where a reader learns what "cap" and "blocked" mean, and
        it said blocked was shown "whenever at least one cap fired". Once a cap
        could bound a claim without stopping the run, that sentence described
        behaviour the code no longer had - in the one document whose whole job
        is explaining the vocabulary.
        """
        glossary = " ".join(
            (SKILL_ROOT / "references" / "glossary.md").read_text().casefold().split()
        )
        self.assertNotIn("whenever at least one cap fired", glossary)
        self.assertNotIn("only a broken grading signal", glossary)
        self.assertNotIn("something is broken, and paid work", glossary)
        # Three phrases left this list because the code stopped doing what they
        # said. "fewer than ten comparable examples" was named here as a reason
        # a cap blocks; a wiring-check-sized dataset is now an advisory ceiling,
        # so the glossary was teaching the reader a rule the card had stopped
        # following - and a glossary is what the assistant answers the user's
        # question from. "too little comparable evidence" and "something is
        # missing or invalid" went with it, because both were the same claim
        # about what Blocked means. What replaces them is the boundary itself,
        # which is what this test was always guarding.
        for phrase in (
            "created or repaired before a paid comparison is worth making",
            "nothing scoreable in the split the search would tune on",
            "limits what the result may claim without saying anything is wrong",
            "it does not mean every component is broken",
            "a cap that only limits the claim does not set it",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, glossary)
        # The cross-reference this branch adds points at the settings-document
        # entry for why no document was provided, and that entry's answer is
        # unconditional, not usual: SKILL.md mandates omitting every
        # config-space file found before this run's enhanced search on every
        # guided run, so `score_agent` takes the no-document branch at every
        # opening score there is. Measured on a 60-row production-sourced
        # dataset with a passing deterministic evaluator, the opening card
        # still reads `1 of 3 checks measured`. "Usually" sends a reader who
        # cannot find their document looking for a mistake they did not make.
        self.assertIn("see that entry above for why one never is", glossary)
        self.assertNotIn("for why one usually is", glossary)

    def test_zero_anchor_gate_triggers_on_quality_not_file_presence(self) -> None:
        """#61: a stub agent satisfied the trigger and anchored nothing.

        The gate is the guide's only defence against inventing a whole
        agent/dataset/evaluator trio around a task the user never chose, and its
        binding force must not depend on the assistant having loaded
        `component-creation.md` first - SKILL.md loads that reference AFTER this
        gate is evaluated.
        """
        normalized = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "finds no agent *that performs an identifiable task*",
            "judge that by what the component does, not by whether the file exists",
            "returns a constant, echoes its input, or is a fixture or placeholder "
            "counts as **missing** for anchoring intent",
            "this gate is evaluated before that reference is loaded",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.casefold(), normalized)

    def test_large_dataset_is_bounded_after_the_score_not_before_it(self) -> None:
        """The score describes the dataset; the subset describes the run.

        A first run has to be bounded above ~100 rows, or every trial pays for
        every row. But choosing the bound BEFORE a score makes the user's data
        wear the run's limitation. On 500 labelled, difficulty-tagged production
        rows the score sees 249 comparable examples, while the same dataset
        scored as an 18-row subset sees 8 and calls it "a wiring check, not a
        score" - a sentence
        that is true of the run and false of the data. So the ordering is the
        contract, not an implementation detail.
        """
        skill_text = " ".join(SKILL.read_text().casefold().split())
        dataset_text = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )

        self.assertIn("first-run subset for a large dataset", dataset_text)
        for phrase in (
            "18 rows by default",
            "at least four from each of the four difficulty bands",
            "score the dataset, not the subset",
            "report the run's sample-size limitation separately",
            "sample within each split, never across it",
            "record what was chosen",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, dataset_text)

        # The inverted rule must not creep back in.
        self.assertNotIn("select before preflight, not after", dataset_text)
        # Both scores see the whole dataset, and the reason is stated.
        self.assertIn("run on the **whole** dataset", dataset_text)
        self.assertIn("a wiring check, not a score", dataset_text)
        # A bounded run may never read as a full evaluation.
        self.assertIn("beside the full row count", dataset_text)

        # The position is the whole point of this test, and it is bounded on BOTH
        # sides. After the stage-4 re-score, because a score taken on our sample
        # reports the run's limit as the dataset's. Before the spend estimate,
        # because an estimate priced on 4,812 rows and run on 18 asks the user to
        # approve a run that never happens - and a number that large may simply
        # get a no.
        self.assertIn("scope the run before pricing it", skill_text)
        self.assertIn(
            "estimate runtime and spend from that subset, not from the full row count",
            skill_text,
        )
        subset_at = skill_text.index("scope the run before pricing it")
        self.assertGreater(
            subset_at, skill_text.index("### 4. validate components locally")
        )
        self.assertLess(
            subset_at,
            skill_text.index("estimate runtime and spend from that subset"),
        )

    def test_closing_motivation_is_grounded_in_the_opening_gaps(self) -> None:
        """Motivation for a further run must come from measured evidence.

        The report already carries the readiness transition; what this pins is
        that the close names the gaps still open and what each costs, rather
        than offering encouragement or implying a further run fixes a gap the
        walkthrough cannot close.
        """
        skill_text = " ".join(SKILL.read_text().casefold().split())

        self.assertIn("saying what a further run would be worth", skill_text)
        self.assertIn(
            "name the ones still open and what each is now costing", skill_text
        )
        self.assertIn(
            "the user's own measured evidence rather than encouragement", skill_text
        )

        # And it must land on ONE action earned by the latest state, with the
        # reason attached. A menu of everything they could do is the same as no
        # recommendation, so the anti-pattern is pinned too.
        self.assertIn(
            "give the one next action the **latest validated state** earns", skill_text
        )
        self.assertIn(
            "a menu offered *instead of* a recommendation is the same as no recommendation",
            skill_text,
        )
        # The generic menu that follows must not restate the state-specific
        # moves: offering "connect the production agent" as an undifferentiated
        # option, one line under a block that names it as THIS project's earned
        # next action, is the contradiction this wording exists to remove.
        menu = skill_text.split("these are available whenever the user wants them", 1)[
            1
        ]
        for restated in (
            "connect the production agent.",
            "replace synthetic examples with reviewed real examples.",
            "align the evaluation method with the product's grading policy.",
        ):
            with self.subTest(restated=restated):
                self.assertNotIn(restated, menu)
        for state in (
            "generated or mostly generated data",
            "real inputs with model-written answers",
            "rows without expected outputs when the evaluator requires references",
            "a substitute component still standing in for a real one",
        ):
            with self.subTest(state=state):
                self.assertIn(state, skill_text)
        # It closes on the opening score, so it must follow the readiness
        # transition and precede the optional next steps.
        transition = skill_text.index("the readiness transition")
        motivation = skill_text.index("saying what a further run would be worth")
        next_steps = skill_text.index(
            "these are available whenever the user wants them"
        )
        self.assertLess(transition, motivation)
        self.assertLess(motivation, next_steps)

    def test_semantic_coverage_review_is_assistant_directed(self) -> None:
        skill_text = SKILL.read_text().casefold()
        quality_text = (
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
        )
        safety_text = " ".join(RUN_SAFETY.read_text().casefold().split())
        plan_text = (SKILL_ROOT / "assets" / "run-plan.md").read_text().casefold()
        calibrator_text = (
            (SKILL_ROOT / "scripts" / "calibrate_evaluator.py").read_text().casefold()
        )

        self.assertIn(
            "assistant-performed semantic-coverage review",
            skill_text,
        )
        self.assertIn(
            "the coding assistant performs and records a rigorous semantic-coverage review",
            quality_text,
        )
        self.assertIn(
            "for the stage-4 semantic-coverage review, use this outcome inventory",
            safety_text,
        )
        self.assertNotIn("human semantic-coverage", skill_text)
        self.assertNotIn("human semantic-coverage", quality_text)
        self.assertNotIn("human semantic-coverage", safety_text)
        self.assertNotIn("human semantic-coverage", plan_text)
        self.assertNotIn("human review", calibrator_text)
        self.assertNotIn("if that review is unavailable", skill_text)
        self.assertNotIn("if that review is unavailable", safety_text)
        self.assertIn(
            "coding assistant's recorded evidence-backed semantic-coverage review",
            calibrator_text,
        )

    def test_semantic_coverage_review_records_evidence_and_verdict(self) -> None:
        quality_text = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        plan_text = " ".join(
            (SKILL_ROOT / "assets" / "run-plan.md").read_text().casefold().split()
        )
        for phrase in (
            "product contracts",
            "tests, fixtures",
            "dataset labels",
            "rubrics",
            "materially distinct input shape",
            "outcome class",
            "rubric branch",
            "mode",
            "threshold",
            "evidence or coverage gap",
            "semantic-coverage verdict",
        ):
            self.assertIn(phrase, quality_text)
        for phrase in (
            "semantic-coverage evidence",
            "verdict (`sufficient`/`ambiguous`)",
            "known gaps",
            "calibration cases and results artifacts",
        ):
            self.assertIn(phrase, plan_text)

    def test_mandated_semantic_review_covers_code_execution_outcomes(self) -> None:
        """A supported code task must have explicit classes to review against."""
        text = RUN_SAFETY.read_text().casefold()
        outcome_table = text.split("for the stage-4 semantic-coverage review", 1)[
            1
        ].split("binding is first", 1)[0]
        for phrase in (
            "code or sql",
            "parse or compile failure",
            "correct but materially different implementation",
            "full test pass",
            "partial test pass",
            "wrong result after a clean exit",
            "runtime error",
            "timeout or resource-limit breach",
            "forbidden side effect",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, outcome_table)

    def test_execution_evaluator_permutation_pass_is_not_binding_evidence(
        self,
    ) -> None:
        """Reordered code failing to execute proves nothing about value binding."""
        skill = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "on an execution evaluator",
            "distinguished only because rearranged code is caught and scored as invalid",
            "carries no evidence about label/value binding",
            "a propagated parse or runtime exception is not a pass",
            "semantic-coverage review must cover that axis for code tasks",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_execution_evaluators_are_sandboxed_and_resource_bounded(self) -> None:
        """A subprocess timeout alone cannot contain model-written code."""
        skill_text = SKILL.read_text()
        authorization = " ".join(
            skill_text.split("## Action authorization", 1)[1]
            .split("## Status language", 1)[0]
            .casefold()
            .split()
        )
        for phrase in (
            "any path that executes or imports candidate output as code, shells out with it, or submits it to a code/sql engine",
            "execution-evaluator containment contract on every invocation",
            "otherwise do not run it",
        ):
            with self.subTest(authorization_phrase=phrase):
                self.assertIn(phrase, authorization)

        stage_four = " ".join(
            skill_text.split("### 4.", 1)[1].split("### 5.", 1)[0].casefold().split()
        )
        for phrase in (
            "an execution evaluator waits until the sandbox and declared local dependencies",
            "every calibration/scored invocation uses that containment",
            "otherwise do not run it",
        ):
            with self.subTest(stage_four_phrase=phrase):
                self.assertIn(phrase, stage_four)

        text = RUN_SAFETY.read_text()
        section = text.split("### Execution-evaluator containment", 1)[1].split(
            "### Deterministic calibration and mock plumbing", 1
        )[0]
        normalized = " ".join(section.casefold().split())

        for phrase in (
            "model-written code or sql as untrusted active content",
            "calibration and every scored callback",
            "disposable sandbox",
            "network disabled",
            "no provider, traigent, or project credentials",
            "read-only",
            "unprivileged",
            "wall-clock time",
            "cpu time",
            "memory",
            "process count",
            "open files",
            "file size",
            "captured output",
            "terminate the whole descendant process tree",
            "ordinary subprocess",
            "resource limits alone do not provide isolation",
            "do not run the execution evaluator",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

        calibration = " ".join(
            text.split("### Deterministic calibration and mock plumbing", 1)[1]
            .split("A Traigent mock run", 1)[0]
            .casefold()
            .split()
        )
        for phrase in (
            "before environment setup, run only a non-executing evaluator",
            "execution evaluator waits until its declared local dependencies and sandbox are available",
            "every candidate execution must satisfy the containment contract above",
        ):
            with self.subTest(calibration_phrase=phrase):
                self.assertIn(phrase, calibration)

        approval = " ".join(
            text.split("## Approval and budgets", 1)[1]
            .split("## Connected-run readiness", 1)[0]
            .casefold()
            .split()
        )
        for phrase in (
            "repeated model-written code or sql execution",
            "sandbox location",
            "tests and fixtures",
            "limits, residual risk",
            "external sandbox recipient",
        ):
            with self.subTest(approval_phrase=phrase):
                self.assertIn(phrase, approval)

        post_run = " ".join(
            text.split("## Post-run verification", 1)[1]
            .split("## Recovery", 1)[0]
            .casefold()
            .split()
        )
        for phrase in (
            "every execution-evaluator invocation used the declared sandbox and resource limits",
            "timeouts",
            "limit breaches",
            "forbidden side effects",
            "sandbox failures were counted and reported",
            "rather than retried outside containment",
        ):
            with self.subTest(post_run_phrase=phrase):
                self.assertIn(phrase, post_run)

        evaluation = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "process separation, not sandbox isolation",
            "follow the skill stage-4 gate",
            "`run-safety.md` owns execution-evaluator containment",
        ):
            self.assertIn(phrase, evaluation)
        for duplicated_mandate in (
            "delegate **every** probe's candidate content to that sandbox",
            "an execution evaluator waits for its declared dependencies",
        ):
            self.assertNotIn(duplicated_mandate, evaluation)

        calibrator_source = (
            SKILL_ROOT / "scripts" / "calibrate_evaluator.py"
        ).read_text()
        calibrator_doc = ast.get_docstring(ast.parse(calibrator_source)) or ""
        normalized_doc = " ".join(calibrator_doc.casefold().split())
        self.assertIn("process separation is not a sandbox", normalized_doc)
        self.assertIn("must delegate that content", normalized_doc)
        self.assertNotIn("isolated", normalized_doc)

    def test_product_grading_question_is_an_ambiguity_only_gate(self) -> None:
        quality_text = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        skill_text = " ".join(SKILL.read_text().casefold().split())
        for text in (quality_text, skill_text):
            for phrase in (
                "unresolved product-grading ambiguity",
                "materially change which output is correct",
                "candidate configurations rank",
                "ask exactly one product-grading question",
                "stop and wait",
            ):
                self.assertIn(phrase, text)
        self.assertIn(
            "proceed without asking or pausing. run static preflight immediately, then follow skill stage 4 for calibration sequencing",
            quality_text,
        )
        self.assertIn(
            "do not ask for generic approval of the probe matrix",
            quality_text,
        )
        self.assertIn(
            "show the exact judgment-dependent change and obtain explicit approval",
            quality_text,
        )
        combined_text = f"{skill_text} {quality_text}"
        for phrase in (
            "first resolve it against the semantic-coverage evidence already inspected",
            "explicitly establish whether order matters",
            "continue without asking",
            "only when the competing order semantics remain unresolved",
        ):
            self.assertIn(phrase, combined_text)

    def test_calibration_policy_cannot_be_chosen_to_make_the_scorer_pass(
        self,
    ) -> None:
        text = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "never select binary mode, thresholds, or tolerances because they make the current evaluator pass",
            "derive them from product semantics before any probe scores exist",
            "let calibration expose a mismatch",
        ):
            self.assertIn(phrase, text)

    def test_production_holdout_review_does_not_pause_the_walkthrough(
        self,
    ) -> None:
        text = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        self.assertIn(
            "later production-promotion safeguard, not a calibration gate or a reason to pause the first walkthrough",
            text,
        )

    def test_openrouter_approval_names_every_possible_recipient(self) -> None:
        skill_text = " ".join(SKILL.read_text().casefold().split())
        safety_text = " ".join(
            (SKILL_ROOT / "references" / "run-safety.md").read_text().casefold().split()
        )
        env_text = " ".join((ROOT / ".env.example").read_text().casefold().split())
        for text in (safety_text, env_text):
            for phrase in (
                "openrouter",
                "gateway",
                "upstream inference provider",
                "fallback",
            ):
                self.assertIn(phrase, text)
        self.assertIn("openrouter", skill_text)
        self.assertIn("every allowed upstream inference provider/route", skill_text)
        self.assertIn("exact recipient set", env_text)
        self.assertIn("disable fallbacks", env_text)
        self.assertIn("fallbacks can change recipients", env_text)
        self.assertIn("allowed routes/policy in stage approval", env_text)

    def test_secret_file_is_preserved_and_owner_only_before_entry(self) -> None:
        skill_text = " ".join(SKILL.read_text().casefold().split())
        safety_text = " ".join(
            (SKILL_ROOT / "references" / "run-safety.md").read_text().casefold().split()
        )
        readme_text = " ".join((ROOT / "README.md").read_text().casefold().split())
        for phrase in (
            "preserve existing values",
            "comments",
            "0600",
            "before opening",
        ):
            self.assertIn(phrase, skill_text)
            self.assertIn(phrase, safety_text)
        for text in (skill_text, safety_text):
            self.assertIn("missing selected-provider", text)
        self.assertIn(
            "add or request the traigent key only after the baseline checkpoint",
            skill_text,
        )
        self.assertIn(
            "traigent key only after the local baseline checkpoint", safety_text
        )
        self.assertIn("owner-only local `.env`", readme_text)

    def test_secret_file_gui_opener_is_detached_without_losing_headless_fallback(
        self,
    ) -> None:
        text = RUN_SAFETY.read_text()
        rules = text.split("### Rules", 1)[1].split(
            "Ask before any private content leaves the machine", 1
        )[0]
        normalized = " ".join(rules.casefold().split())

        for phrase in (
            "detached and non-blocking",
            "absolute `.env` path as one safely quoted argument",
            "redirect stdin, stdout, and stderr away from the assistant's pipes",
            "start it in the background",
            "start-process",
            "do not wait for the editor process",
            "print the absolute path immediately",
            "headless session",
            "print the absolute path as the fallback",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)
        self.assertIn("</dev/null >/dev/null 2>&1 &", rules)

    def test_evaluator_calibration_covers_multiple_cases(self) -> None:
        text = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "materially distinct inputs and outcome classes",
            "one input with four output variants is not enough",
            "normalized score in `[0, 1]`",
            "process separation, not sandbox isolation",
        ):
            self.assertIn(phrase, text)

    def test_exception_probe_advisory_routes_to_real_error_path_review(self) -> None:
        """The mechanical probe is evidence to inspect, never a diagnosis."""
        text = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "read `exception_probe_advisory` as an advisory, not a verdict",
            "malformed python and json text",
            "reaches `syntaxerror` or `jsondecodeerror` when the scorer uses those parsers",
            "it is not exhaustive",
            "consistent with a swallowed parser/evaluator exception",
            "can also be a deliberate unsupported-input rejection",
            "the probes cannot prove which",
            "task-valid malformed case",
            "genuine parser/runtime failures remain distinct before optimizing",
            "never changes the authored probes' pass by itself",
            "each deterministic supplemental attempt gets a fresh child",
            "isolating process-local scorer and dependency state",
            "one additional `--timeout` budget",
            "read `supplemental_probe_advisory` as unavailable evidence",
            "it never changes authored pass",
            "do not count an unavailable probe as distinguished",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_calibration_modes_follow_real_task_semantics(self) -> None:
        skill_text = SKILL.read_text().casefold()
        quality_text = (
            SKILL_ROOT / "references" / "evaluation-and-dataset.md"
        ).read_text()
        normalized_quality = " ".join(quality_text.casefold().split())
        for phrase in (
            "choose and record `score_mode` from the real task semantics",
            "binary mode is not an escape hatch",
            "require both `partial` and `bad` to fail",
            "good ~= equivalent_good > partial > bad",
            "--cases @traigent-runs/calibration-cases.json",
        ):
            self.assertIn(phrase, normalized_quality)
        self.assertNotIn(
            "the evaluator discriminates good, equivalent, partial, and bad outputs",
            skill_text,
        )

    def test_calibration_matrix_example_has_per_case_modes(self) -> None:
        text = (SKILL_ROOT / "references" / "evaluation-and-dataset.md").read_text()
        match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
        self.assertIsNotNone(match)
        cases = json.loads(match.group(1))
        self.assertEqual(
            {case["score_mode"] for case in cases},
            {"graded", "binary"},
        )
        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertTrue(
                    {"name", "score_mode", "expected", "input_data", "probes"}
                    <= case.keys()
                )
                self.assertEqual(
                    set(case["probes"]),
                    {"good", "equivalent_good", "partial", "bad"},
                )

    def test_existing_evaluator_adapter_preserves_provenance(self) -> None:
        text = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "preserve an existing evaluator unchanged",
            "does not replace the evaluator or change its provenance",
            "skill-owned keyword contract",
            "never reproduce or guess sdk callback aliases",
        ):
            self.assertIn(phrase, text)

    def test_sdk_contract_ownership_stays_in_the_installed_sdk(self) -> None:
        skill_text = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "public dataset loader/validator",
            "public no-execution contract validator",
            "never recreate sdk binding fallbacks",
        ):
            self.assertIn(phrase, skill_text)

        preflight_text = (SKILL_ROOT / "scripts" / "preflight.py").read_text()
        for sdk_internal in (
            "BaseEvaluator._should_expand_input_mapping",
            "_prepare_call_arguments",
            "Traigent 0.23",
            "InjectionMode",
            "DATASET_INPUT_FIELDS",
            "DATASET_EXPECTED_OUTPUT_FIELDS",
        ):
            self.assertNotIn(sdk_internal, preflight_text)
        self.assertIn("--input-field", preflight_text)
        self.assertIn("--expected-field", preflight_text)

    def test_run_record_is_compact_and_keeps_essential_state(self) -> None:
        text = (SKILL_ROOT / "assets" / "run-plan.md").read_text().casefold()
        for phrase in (
            "the user does not fill it in",
            "calibration cases and results artifacts",
            "total walkthrough ceiling (default `$5.00`)",
            "tracked spend, or conservative deduction",
            "remaining total ceiling",
            "partial/final result",
        ):
            self.assertIn(phrase, text)
        self.assertLessEqual(len(text.splitlines()), 60)
        for removed_detail in (
            "provider retry count",
            "provider-request timeout",
            "aggregate budget ledger",
        ):
            self.assertNotIn(removed_detail, text)

    def test_calibration_results_are_persisted_separately(self) -> None:
        text = (SKILL_ROOT / "references" / "evaluation-and-dataset.md").read_text()
        self.assertIn(
            "--json > traigent-runs/calibration-results.json",
            text,
        )
        self.assertIn(
            "traigent-runs/calibration-cases.json",
            text,
        )

    def test_sdk_template_defines_prompt_builder(self) -> None:
        text = (SKILL_ROOT / "references" / "sdk-execution.md").read_text()
        self.assertIn("def build_prompt(", text)
        self.assertIn('if style == "direct":', text)
        self.assertIn('elif style == "structured":', text)
        self.assertIn('elif style == "criteria_first":', text)
        self.assertIn("if self_check:", text)
        self.assertIn('"self_check": [False, True]', text)

    def test_sdk_comparison_uses_six_rows_then_added_knobs_and_twelve_trials(
        self,
    ) -> None:
        text = SDK_EXECUTION.read_text()
        normalized = " ".join(text.casefold().split())

        for phrase in (
            "BASELINE_TRIALS = positive_int(",
            '"TRAIGENT_FIRST_RUN_BASELINE_TRIALS",',
            "default=6,",
            "ENHANCED_MAX_TRIALS = positive_int(",
            '"TRAIGENT_FIRST_RUN_ENHANCED_MAX_TRIALS",',
            "default=12,",
            "assert configuration_count(BASELINE_SPACE) == 6",
            "assert 1 <= BASELINE_TRIALS <= configuration_count(BASELINE_SPACE)",
            "assert 1 <= ENHANCED_MAX_TRIALS < configuration_count(ENHANCED_SPACE)",
            "configuration_space=BASELINE_SPACE",
            "max_trials=BASELINE_TRIALS",
            "configuration_space=ENHANCED_SPACE",
            "max_trials=ENHANCED_MAX_TRIALS",
        ):
            self.assertIn(phrase, text)

        for phrase in (
            "six baseline rows and a 12-trial enhanced cap",
            "adds two real one-call controls",
            "`12` is therefore the ceiling and not a floor beneath a higher count",
            "max_trials` is a cap rather than an sdk-enforced minimum",
            # The 10 floor stays here and only here on the reference side: it
            # is the assistant's honesty check on a short run, so it must
            # survive the move of the user-facing copy to a bare ceiling.
            "fewer than 10 rows requires a concrete backend stop, timeout, "
            "cost-limit, or failure explanation",
            "not a count promised to the user",
        ):
            self.assertIn(phrase, normalized)

        baseline_block = text.split("BASELINE_SPACE = {", 1)[1].split(
            "ENHANCED_SPACE = {", 1
        )[0]
        enhanced_block = text.split("ENHANCED_SPACE = {", 1)[1].split(
            "def configuration_count", 1
        )[0]
        self.assertIn(
            '"prompt_style": [BASELINE_CONFIG["prompt_style"]]', baseline_block
        )
        self.assertIn('"self_check": [BASELINE_CONFIG["self_check"]]', baseline_block)
        self.assertIn('"structured"', enhanced_block)
        self.assertIn('"criteria_first"', enhanced_block)
        self.assertIn('"self_check": [False, True]', enhanced_block)

        code = re.findall(r"```python\n(.*?)\n```", text, re.DOTALL)[0]
        module = ast.parse(code)
        wanted_assignments = {
            "BASELINE_CONFIG",
            "BASELINE_SPACE",
            "ENHANCED_SPACE",
            "AGENT_TYPE",
            "WIRED_KNOBS",
            "PROBE_INPUTS",
            "PROBE_VERDICTS",
            "WIRED_OUTSIDE_THE_REQUEST",
            "UNPROVEN_WIRED_KNOBS",
        }
        selected_nodes = []
        for node in module.body:
            if isinstance(node, ast.FunctionDef) and node.name in {
                "configuration_count",
                "config_space_document",
                "build_prompt",
                "build_request",
                "probe_wiring",
            }:
                selected_nodes.append(node)
            elif isinstance(node, ast.Assert):
                selected_nodes.append(node)
            elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in wanted_assignments
                for target in node.targets
            ):
                selected_nodes.append(node)
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id in wanted_assignments
            ):
                # An annotated constant (`NAME: list[str] = []`) is an AnnAssign,
                # not an Assign; missing it leaves the asserts below referring to
                # a name this namespace never bound.
                selected_nodes.append(node)

        executable = ast.fix_missing_locations(
            ast.Module(body=selected_nodes, type_ignores=[])
        )
        namespace = {
            "math": __import__("math"),
            "SELECTED_CURRENT_MODEL": "provider/current",
            "SELECTED_ALTERNATIVE_MODEL": "provider/alternative",
            "SELECTED_STRONG_MODEL": "provider/strong",
            "STRONG_REASONING_EFFORT": None,
            "BASELINE_TRIALS": 4,
            "ENHANCED_MAX_TRIALS": 10,
            "MODEL_REQUEST_TIMEOUT_SECONDS": 120.0,
        }
        exec(compile(executable, "<sdk-spaces-and-knobs>", "exec"), namespace)

        count = namespace["configuration_count"]
        self.assertEqual(count(namespace["BASELINE_SPACE"]), 6)
        self.assertEqual(count(namespace["ENHANCED_SPACE"]), 54)
        for space_name in ("BASELINE_SPACE", "ENHANCED_SPACE"):
            self.assertEqual(
                namespace[space_name]["model"],
                [
                    "provider/current",
                    "provider/alternative",
                    "provider/strong",
                ],
                f"{space_name} must run the identical three-model ladder",
            )
        self.assertLessEqual(4, count(namespace["BASELINE_SPACE"]))
        self.assertLess(10, count(namespace["ENHANCED_SPACE"]))

        # The template's own producer must emit readiness evidence that clears
        # `agent-no-varying-knobs` through the real scorer - not a document the
        # test hand-writes to match. No pillar number is pinned here: the score
        # moves with unrelated template edits, the cap is the contract.
        document = namespace["config_space_document"](namespace["ENHANCED_SPACE"])
        self.assertEqual(document["knobs"], namespace["ENHANCED_SPACE"])
        self.assertEqual(document["wired"], namespace["WIRED_KNOBS"])
        self.assertEqual(document["agent_type"], namespace["AGENT_TYPE"])
        self.assertEqual(document["max_trials"], namespace["ENHANCED_MAX_TRIALS"])
        self.assertNotIn("configuration_space", document)
        # Undeclared keys are refused, so the one producer in this package has
        # to emit declared fields only. Asserting the set - not just the
        # absence of the alias - is what makes that a checked carve-out rather
        # than an assumption: a key added to the generator would fail here,
        # where the message names it, instead of at the scorer.
        self.assertEqual(
            set(document),
            set(document) & {spec.name for spec in READINESS.CONFIG_SPACE_FIELDS},
            "the producer emits a key CONFIG_SPACE_FIELDS does not declare, "
            "which the scorer now refuses",
        )
        _pillar, conditions = score_config_space(document)
        self.assertNotIn(
            "agent-no-varying-knobs",
            conditions,
            "the template's own config-space document must clear the cap it exists to clear",
        )

        build_prompt = namespace["build_prompt"]
        self.assertEqual(build_prompt("task", style="direct", self_check=False), "task")
        structured = build_prompt("task", style="structured", self_check=False)
        criteria = build_prompt("task", style="criteria_first", self_check=False)
        checked = build_prompt("task", style="direct", self_check=True)
        self.assertIn("Task:\ntask", structured)
        self.assertIn("decision criteria", criteria)
        self.assertIn("silently check", checked)
        self.assertNotEqual(structured, criteria)

        invalid_namespace = {
            "math": __import__("math"),
            "SELECTED_CURRENT_MODEL": "provider/current",
            "SELECTED_ALTERNATIVE_MODEL": "provider/alternative",
            "SELECTED_STRONG_MODEL": "provider/strong",
            "STRONG_REASONING_EFFORT": None,
            "BASELINE_TRIALS": 7,
            "ENHANCED_MAX_TRIALS": 10,
            "MODEL_REQUEST_TIMEOUT_SECONDS": 120.0,
        }
        with self.assertRaises(AssertionError):
            exec(
                compile(executable, "<sdk-invalid-reduced-plan>", "exec"),
                invalid_namespace,
            )

        reasoning_namespace = {
            "math": __import__("math"),
            "SELECTED_CURRENT_MODEL": "provider/current",
            "SELECTED_ALTERNATIVE_MODEL": "provider/alternative",
            "SELECTED_STRONG_MODEL": "provider/strong",
            "STRONG_REASONING_EFFORT": "high",
            "BASELINE_TRIALS": 4,
            "ENHANCED_MAX_TRIALS": 10,
        }
        with self.assertRaisesRegex(AssertionError, "pin temperature"):
            exec(
                compile(executable, "<sdk-reasoning-unpinned-temperature>", "exec"),
                reasoning_namespace,
            )

    def test_user_owned_baseline_is_not_padded_to_generated_row_target(self) -> None:
        guide = " ".join((ROOT / "GUIDE.md").read_text().casefold().split())
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        sdk = " ".join(SDK_EXECUTION.read_text().casefold().split())

        self.assertIn("preserving the user's configuration exactly", guide)
        self.assertIn("do not expand, shrink, or weaken a user-owned baseline", guide)
        self.assertIn(
            "one row is correct when that is what the user actually defined", guide
        )
        self.assertIn("preserve the user's existing baseline", skill)
        self.assertIn("including its original row count", skill)
        self.assertIn("preserve a user-owned baseline space unchanged", safety)
        self.assertIn("its row count exactly; do not expand it to six", sdk)
        self.assertIn("real one-row fixed configuration remains one row", sdk)
        self.assertIn("preserve its exact model set", sdk)
        self.assertIn("add non-model controls by default", sdk)
        self.assertIn(
            "matched an explicitly approved and disclosed reduced target", skill
        )

    def test_generated_model_ladder_never_expands_a_user_owned_baseline(self) -> None:
        """The affordable three-model ladder belongs only to generated evidence."""
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        sdk = " ".join(SDK_EXECUTION.read_text().casefold().split())

        for phrase in (
            "this section applies only when the assistant prepares a missing baseline",
            "one fast low-cost tier, one mid-tier workhorse, and one strong tier",
            "one step below the vendor's newest flagship",
            "do not select the flagship itself",
            "both generated spaces use the same three models",
            "never gets a model the baseline did not measure",
            "cannot be explained by quietly upgrading the model",
            "refine the swept values around its top rows",
            "sweep only knobs that are real for every model in the space",
            "when the user already owns a baseline, do not apply this ladder",
            "adding a cheaper or stronger model changes the experiment",
            "for the generated ladder, use one model family",
            "model slots are roles, not hardcoded ids",
        ):
            with self.subTest(document="sdk-execution", phrase=phrase):
                self.assertIn(phrase, sdk)
        for phrase in (
            "never the vendor's newest flagship",
            "the three-tier ladder applies only when this walkthrough supplies a missing baseline",
            "do not add cheaper tiers without the separate disclosure",
            "a user-owned baseline requires only its existing route and credential",
            "preserve its exact model set",
            "a deliberately small enhancement",
            "a small slice of what traigent can drive, not its full capability",
        ):
            with self.subTest(document="skill", phrase=phrase):
                self.assertIn(phrase, skill)
        for phrase in (
            "the fast, mid, and strong rungs of the walkthrough model ladder",
            "keeps the identical model list",
            "never to a model the baseline did not measure",
            "keeps the first run faster and cheaper",
            "do not add cheaper tiers or any other model",
            "a separate model comparison is disclosed and approved",
        ):
            with self.subTest(document="run-safety", phrase=phrase):
                self.assertIn(phrase, safety)

    def test_strong_reasoning_tier_swaps_sampling_for_effort_and_headroom(self) -> None:
        """A reasoning-tier model rejects sampled temperature and needs headroom.

        Executes the fence's call path shape: the strong tier at a declared
        reasoning effort must send reasoning kwargs instead of temperature,
        with at least the 4096-token answer headroom the safety reference
        requires, while ordinary tiers keep the swept temperature.
        """
        text = SDK_EXECUTION.read_text()
        self.assertIn('os.environ["TRAIGENT_FIRST_RUN_STRONG_MODEL"]', text)
        self.assertIn("TRAIGENT_FIRST_RUN_STRONG_REASONING_EFFORT", text)
        code = re.findall(r"```python\n(.*?)\n```", text, re.DOTALL)[0]
        call_path_nodes = [
            node
            for node in ast.parse(code).body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"build_request", "call_agent"}
        ]
        self.assertEqual(
            [node.name for node in call_path_nodes], ["build_request", "call_agent"]
        )
        calls = []

        def fake_completion(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(cost=0.01),
                choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))],
            )

        module = ast.fix_missing_locations(
            ast.Module(body=call_path_nodes, type_ignores=[])
        )
        namespace = {
            "litellm": SimpleNamespace(completion=fake_completion),
            "provider_reported_cost": lambda response: 0.01,
            "require_nonzero_token_usage": lambda response: None,
            "build_prompt": lambda message, *, style, self_check: message,
            "SELECTED_STRONG_MODEL": "provider/strong",
            "STRONG_REASONING_EFFORT": "high",
            "MODEL_REQUEST_TIMEOUT_SECONDS": 120.0,
        }
        exec(compile(module, "<sdk-call-agent>", "exec"), namespace)
        call_agent = namespace["call_agent"]

        call_agent(
            "task",
            {
                "model": "provider/strong",
                "temperature": 0.2,
                "prompt_style": "direct",
                "self_check": False,
            },
        )
        strong_call = calls[-1]
        self.assertEqual(strong_call["reasoning_effort"], "high")
        self.assertGreaterEqual(strong_call["max_tokens"], 4096)
        self.assertNotIn("temperature", strong_call)

        call_agent(
            "task",
            {
                "model": "provider/mid",
                "temperature": 0.2,
                "prompt_style": "direct",
                "self_check": False,
            },
        )
        ordinary_call = calls[-1]
        self.assertEqual(ordinary_call["temperature"], 0.2)
        self.assertNotIn("reasoning_effort", ordinary_call)

    def test_sdk_template_uses_internal_bounds_without_added_retries(self) -> None:
        text = SDK_EXECUTION.read_text()
        normalized = " ".join(text.casefold().split())
        for phrase in (
            "MODEL_REQUEST_TIMEOUT_SECONDS",
            "BASELINE_TIMEOUT_SECONDS",
            "OPTIMIZATION_TIMEOUT_SECONDS",
            "not math.isfinite(value) or value <= 0",
            "timeout=BASELINE_TIMEOUT_SECONDS",
            "timeout=OPTIMIZATION_TIMEOUT_SECONDS",
        ):
            self.assertIn(phrase, text)
        for phrase in (
            "the user does not fill them in",
            "do not set `traigent_vendor_max_retries`",
        ):
            self.assertIn(phrase, normalized)
        self.assertNotIn("num_retries=", text)
        self.assertNotIn("HOLDOUT_PHASE_TIMEOUT_SECONDS", text)
        self.assertNotIn("PROVIDER_RETRY_COUNT", text)

    def test_sdk_template_pins_paths_objectives_route_and_reported_cost(self) -> None:
        text = SDK_EXECUTION.read_text()
        for phrase in (
            "RUN_DIR = Path(__file__).resolve().parent",
            'SDK_RESULTS_DIR = RUN_DIR / "sdk-results"',
            'if not os.environ.get("TRAIGENT_RESULTS_FOLDER", "").strip()',
            'os.environ["TRAIGENT_RESULTS_FOLDER"] = str(SDK_RESULTS_DIR)',
            'TUNING_DATASET = str(RUN_DIR / "tuning.jsonl")',
            "save_to=BASELINE_RESULTS",
            "save_to=OPTIMIZED_RESULTS",
            "ObjectiveSchema.from_objectives(",
            'name="task_success", orientation="maximize"',
            'name="cost", orientation="minimize"',
            "def require_current_route_credential()",
            "def provider_reported_cost(response)",
            'usage.get("cost")',
            "llm_provider-x-litellm-response-cost",
        ):
            self.assertIn(phrase, text)
        self.assertNotIn('os.environ.setdefault("TRAIGENT_RESULTS_FOLDER"', text)
        self.assertNotIn("cost = litellm.completion_cost(", text)
        self.assertNotIn("HOLDOUT_DATASET", text)

    def test_preflight_and_readiness_share_the_resolved_evaluator_method(self) -> None:
        preflight = (SKILL_ROOT / "scripts" / "preflight.py").read_text()
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        self.assertIn('"--evaluator-method"', preflight)
        self.assertIn("REFERENCE_FREE_METHODS", preflight)
        self.assertEqual(
            preflight_constant("REFERENCE_FREE_METHODS"),
            set(READINESS.REFERENCE_FREE_METHODS),
        )
        for phrase in (
            "resolved evaluator method as run-scoped validation state",
            "same current `--evaluator-method` value to every paired preflight/readiness invocation",
            "omit the flag from both",
        ):
            self.assertIn(phrase, skill)
        stage_four = skill.split("### 4. validate components locally", 1)[1].split(
            "### 5. prepare the environment and finish free checks", 1
        )[0]
        for phrase in (
            "apply the run-scoped evaluator-method rule above",
            "resolve its method again",
            "this preflight and the paired readiness invocation in step 5",
        ):
            self.assertIn(phrase, stage_four)
        for document in (skill, safety):
            self.assertIn("preflight", document)
            self.assertIn("expected outputs", document)

    def test_the_similarity_line_the_card_prints_is_the_one_that_decides(
        self,
    ) -> None:
        """One decision, three homes: what decides, what prints, what is read.

        `preflight.NEAR_DUPLICATE_THRESHOLD` decides which rows count as
        repetition. `readiness.NEAR_DUPLICATE_PERCENT` is the number the card
        prints, and glossary.md is the number the user reads before agreeing to
        be judged by it. All three were independent literals, so lowering the
        deciding threshold to 0.8 left 472 tests passing while the card still
        promised "rows at least 90% similar" and the glossary still called 90%
        the chosen line - the customer told one number and scored on another.

        Asserted against the deciding constant, not beside it: a test that
        restates 90 is a fourth home for the same drift.
        """
        threshold = preflight_constant("NEAR_DUPLICATE_THRESHOLD")
        percent = READINESS.NEAR_DUPLICATE_PERCENT
        self.assertAlmostEqual(threshold * 100, percent, places=6)
        # Also the label preflight itself prints, so a threshold that is not a
        # whole percent cannot round into agreement with a card that is.
        self.assertEqual(f"{threshold:.0%}", f"{percent}%")
        near_duplicates = next(
            check
            for check in READINESS.DIVERSITY_CHECKS
            if check.certifier == "near_duplicate_status"
        )
        for label in (
            near_duplicates.found_label,
            near_duplicates.looking_for_label,
        ):
            self.assertIn(f"{percent}%", label)
        glossary = " ".join(
            (SKILL_ROOT / "references" / "glossary.md").read_text().split()
        )
        self.assertIn(f"repeat when {percent}% or more of their words match", glossary)
        self.assertIn(f"{percent}% is a chosen line", glossary)

    def test_no_document_states_the_similarity_line_as_its_own_number(
        self,
    ) -> None:
        """The fourth home the docstring above names, found in the same commit.

        The branch that welded three homes together created two more: an
        assistant-facing instruction in evaluation-and-dataset.md reading
        "near-duplicates at or above 90% shared words", inside no guard at all,
        and four `"90%"` literals across the test suite. A number welded in
        three places and written out in five is not welded.

        The rule is that only the two documents the guard above pins may state
        the number, and they state it BECAUSE they are pinned to the constant.
        Anywhere else names the check instead of the value.
        """
        percent = READINESS.NEAR_DUPLICATE_PERCENT
        pinned = {SKILL_ROOT / "references" / "glossary.md"}
        for document in assistant_facing_documents():
            if document in pinned:
                continue
            with self.subTest(document=document.name):
                text = " ".join(document.read_text().split())
                for phrase in (f"{percent}% shared words", f"{percent}% similar"):
                    # `assertNotIn` would print the whole document on failure,
                    # so the membership test is done here and the message says
                    # only what is wrong.
                    self.assertFalse(
                        phrase in text,
                        f"{document.name} states the similarity line as the "
                        f"literal {phrase!r}, in no guard - name the check "
                        "that prints it instead",
                    )

    def test_readiness_receives_only_a_grounded_task_kind(self) -> None:
        skill = " ".join(SKILL.read_text().casefold().split())
        quality = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "treat the output task kind as run-scoped validation state",
            "pass it as `--task-kind` to every readiness invocation from the opening gate onward",
            "never infer it only from a filename, language, or benchmark family",
            "omit `--task-kind` and report task fit as not yet measured",
        ):
            self.assertIn(phrase, quality)
        self.assertIn("apply the run-scoped task-kind rule to readiness only", skill)

    def test_sdk_template_cost_helper_prefers_public_cost_and_fails_closed(
        self,
    ) -> None:
        text = SDK_EXECUTION.read_text()
        functions = {}
        for source in re.findall(r"```python\n(.*?)\n```", text, re.DOTALL):
            for node in ast.parse(source).body:
                if isinstance(node, ast.FunctionDef):
                    functions[node.name] = node
        helper_module = ast.fix_missing_locations(
            ast.Module(body=[functions["provider_reported_cost"]], type_ignores=[])
        )
        namespace = {"math": __import__("math")}
        exec(compile(helper_module, "<provider-cost>", "exec"), namespace)
        helper = namespace["provider_reported_cost"]

        self.assertEqual(
            helper(SimpleNamespace(usage=SimpleNamespace(cost=0.25))), 0.25
        )
        self.assertEqual(helper(SimpleNamespace(usage=SimpleNamespace(cost=0.0))), 0.0)
        header_response = SimpleNamespace(
            usage=SimpleNamespace(cost=None),
            _hidden_params={
                "additional_headers": {"llm_provider-x-litellm-response-cost": "0.125"}
            },
        )
        self.assertEqual(helper(header_response), 0.125)
        self.assertIsNone(helper(SimpleNamespace(usage=SimpleNamespace(cost=None))))
        with self.assertRaisesRegex(RuntimeError, "malformed response-cost metadata"):
            helper(SimpleNamespace(usage=SimpleNamespace(cost="not-a-number")))
        with self.assertRaisesRegex(RuntimeError, "invalid per-response cost"):
            helper(SimpleNamespace(usage=SimpleNamespace(cost=float("nan"))))
        with self.assertRaisesRegex(RuntimeError, "invalid per-response cost"):
            helper(SimpleNamespace(usage=SimpleNamespace(cost=-0.01)))
        with self.assertRaisesRegex(RuntimeError, "malformed response-cost metadata"):
            helper(SimpleNamespace(usage=SimpleNamespace(cost=True)))

        usage_module = ast.fix_missing_locations(
            ast.Module(body=[functions["require_nonzero_token_usage"]], type_ignores=[])
        )
        usage_namespace = {"math": __import__("math")}
        exec(compile(usage_module, "<provider-usage>", "exec"), usage_namespace)
        require_usage = usage_namespace["require_nonzero_token_usage"]
        require_usage(SimpleNamespace(usage=SimpleNamespace(total_tokens=1)))
        require_usage(SimpleNamespace(usage={"total_tokens": 42}))
        require_usage(
            SimpleNamespace(usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3))
        )
        require_usage(
            SimpleNamespace(usage={"prompt_tokens": 1, "completion_tokens": 0})
        )
        for invalid in (None, 0, -1, True, float("nan"), float("inf")):
            with self.subTest(total_tokens=invalid):
                with self.assertRaisesRegex(RuntimeError, "nonzero token usage"):
                    require_usage(
                        SimpleNamespace(usage=SimpleNamespace(total_tokens=invalid))
                    )
        for invalid_components in (
            {"prompt_tokens": 0, "completion_tokens": 0},
            {"prompt_tokens": -1, "completion_tokens": 2},
            {"prompt_tokens": True, "completion_tokens": 2},
        ):
            with self.subTest(components=invalid_components):
                with self.assertRaisesRegex(RuntimeError, "nonzero token usage"):
                    require_usage(SimpleNamespace(usage=invalid_components))

        call_module = ast.fix_missing_locations(
            ast.Module(
                body=[
                    functions["provider_reported_cost"],
                    functions["require_nonzero_token_usage"],
                    functions["call_agent"],
                ],
                type_ignores=[],
            )
        )
        current_response = None

        def completion(**_kwargs):
            return current_response

        call_namespace = {
            "math": __import__("math"),
            "litellm": SimpleNamespace(completion=completion),
            "build_request": lambda message, config: {},
        }
        exec(compile(call_module, "<provider-call>", "exec"), call_namespace)
        call_agent = call_namespace["call_agent"]

        def response(*, usage):
            return SimpleNamespace(
                usage=usage,
                choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))],
            )

        current_response = response(usage=SimpleNamespace(total_tokens=3))
        self.assertEqual(call_agent("task", {}), ("answer", None))
        current_response = response(usage=SimpleNamespace(cost=0.2, total_tokens=3))
        self.assertEqual(call_agent("task", {}), ("answer", 0.2))
        current_response = response(usage=SimpleNamespace(cost=0.0, total_tokens=3))
        self.assertEqual(call_agent("task", {}), ("answer", 0.0))
        current_response = response(usage=SimpleNamespace())
        with self.assertRaisesRegex(RuntimeError, "nonzero token usage"):
            call_agent("task", {})
        current_response = response(usage=SimpleNamespace(cost=0.2))
        with self.assertRaisesRegex(RuntimeError, "nonzero token usage"):
            call_agent("task", {})

    def test_sdk_comparison_uses_one_public_metric_contract(self) -> None:
        text = SDK_EXECUTION.read_text()
        functions = {}
        for source in re.findall(r"```python\n(.*?)\n```", text, re.DOTALL):
            for node in ast.parse(source).body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions[node.name] = node

        task_score_node = functions["task_score"]
        self.assertEqual(
            [argument.arg for argument in task_score_node.args.args],
            ["prediction", "expected", "input_data"],
        )
        self.assertEqual(task_score_node.args.defaults, [])
        normalized = " ".join(text.casefold().split())
        for phrase in (
            "adapter around the preserved evaluator",
            "installed sdk's documented public `metric_functions` contract",
            "baseline and enhanced search must use the same selected public evaluation path",
            "same installed public `traigent.dataset.from_jsonl` loader",
        ):
            self.assertIn(phrase, normalized)
        self.assertIn("inspect.signature(traigent.Dataset.from_jsonl)", text)
        self.assertNotIn("HOLDOUT_DATASET", text)
        self.assertNotIn("def evaluate_holdout", text)

    def test_customer_portal_experiments_are_retained_and_linked(self) -> None:
        skill_text = " ".join(SKILL.read_text().casefold().split())
        guide_text = " ".join((ROOT / "GUIDE.md").read_text().casefold().split())
        sdk_text = " ".join(SDK_EXECUTION.read_text().casefold().split())

        self.assertIn("retain every experiment that was actually persisted", skill_text)
        self.assertIn("never delete one as automatic teardown", skill_text)
        self.assertIn("direct verified link for each persisted run", skill_text)
        self.assertIn(
            "do not delete portal experiments as walkthrough cleanup", guide_text
        )
        self.assertNotIn("assert baseline_results.cloud_url is not none", sdk_text)
        self.assertIn("assert optimized_results.cloud_url is not none", sdk_text)
        self.assertIn("comes from the successful sync json", sdk_text)
        self.assertIn("otherwise label it local-only", sdk_text)
        self.assertIn(
            "portal experiment deletion is never walkthrough teardown", sdk_text
        )

    def test_connection_failure_never_becomes_offline_customer_success(self) -> None:
        skill_text = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "provider, traigent backend, or portal connectivity is unavailable",
            "stop with the concrete failure and one recommended recovery",
            "never fall back automatically to mock or synthetic results",
            "never present offline checks as a completed optimization",
            "resume the connected path after the failure is resolved",
        ):
            self.assertIn(phrase, skill_text)

    def test_mock_process_disables_litellm_remote_cost_map_fetch(self) -> None:
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        for phrase in (
            "`traigent_offline_mode=true` and `litellm_local_model_cost_map=true`",
            "traigent offline mode does not by itself suppress litellm's import-time remote pricing-map fetch",
            "every generated mock wrapper and every documented free mock invocation",
        ):
            self.assertIn(phrase, safety)

    def test_mock_rejects_phantom_configuration_before_secret_handoff(self) -> None:
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        for phrase in (
            "trial settings are not consumed",
            "return to the stage-2 repair/continue/pause choice",
            "enter stage-3 adapter repair and revalidate only after the user chooses its scope",
            "do not open a credential file while optimization remains phantom",
        ):
            self.assertIn(phrase, safety)

    def test_ci_runs_package_and_format_validation(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text()
        for phrase in (
            'python-version: "3.12"',
            "python -m unittest discover -s tests -v",
            "ruff check .",
            "black --check .",
        ):
            self.assertIn(phrase, workflow)
        self.assertIn("ruff==0.15.12", workflow)
        self.assertIn("black==26.5.1", workflow)
        self.assertNotIn("pip install --upgrade ruff black", workflow)
        self.assertNotIn("/home/", workflow)

    def test_ci_runs_offline_contract_in_a_fail_closed_container(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text()
        offline_job = workflow.split("  offline-contract:", 1)[1].split(
            "  validate:", 1
        )[0]
        for phrase in (
            "--network none",
            "--read-only",
            "--cap-drop ALL",
            "--security-opt no-new-privileges",
            "--user 65534:65534",
            "$GITHUB_WORKSPACE:/repo:ro",
            "$RUNNER_TEMP/traigent-offline-evidence:/evidence",
            "python tests/behavioral/harness.py --all",
            "actions/upload-artifact@v4",
        ):
            self.assertIn(phrase, offline_job)
        self.assertNotIn("pip install", offline_job)
        self.assertNotIn("setup-python", offline_job)

    def test_every_ci_job_declares_its_own_timeout(self) -> None:
        """An undeclared job inherits GitHub's 360-minute default.

        Six hours of runner time for a job whose slowest observed run is under
        two minutes, and the pull request stays blocked for all six. The bound
        is asserted per job rather than per workflow because the default is
        applied per job: adding one without a `timeout-minutes` silently
        reintroduces the whole defect.

        This asks only whether a bound EXISTS and is not GitHub's own default
        written down. Whether the bound is large enough to be worth anything is
        a different question, and asking only this one is what let the two
        halves of this change disagree - see the sibling test below.
        """
        self.assertTrue(CI_WORKFLOWS, "no workflow files found")
        for workflow in CI_WORKFLOWS:
            jobs = ci_workflow_jobs(workflow)
            with self.subTest(workflow=workflow.name):
                self.assertTrue(jobs, f"{workflow.name} declares no jobs")
                for job, minutes in jobs.items():
                    with self.subTest(job=job):
                        self.assertIsNotNone(
                            minutes,
                            f"{workflow.name}:{job} must declare exactly one "
                            "job-level timeout-minutes",
                        )
                        self.assertGreater(minutes, 0)
                        # Anything at or above GitHub's own default is not a
                        # bound, it is the default written down.
                        self.assertLess(minutes, 360)

    def test_every_ci_job_outlives_the_harness_bound(self) -> None:
        """A job cap below the harness bound destroys the harness's diagnostic.

        The existence check above passed against both halves of this change
        while they contradicted each other. `harness.py --all` calls the
        calibrator with no `--timeout`, so it runs on the derived bound - 660s
        today - and the two jobs declared 600s and 300s. On that path GitHub
        cancelled the job first and reported a bare cancellation, so the partial
        stdout and stderr `run_command` collects from the killed child, which is
        the entire reason the derived bound exists, was never written.

        So the relation is asserted, not the number: the workflow may declare
        more than the floor, and a change to the calibrator's ceiling moves the
        floor without this test or the workflow comment being edited. Failing
        here means one of the two must move, and the message says which way.
        """
        harness = behavioral_harness()
        floor = harness.minimum_ci_job_timeout_minutes()
        self.assertGreater(
            floor * 60,
            harness.worst_case_command_timeout_seconds(),
            "the floor must strictly outlive the command bound, not tie it",
        )
        self.assertTrue(CI_WORKFLOWS, "no workflow files found")
        for workflow in CI_WORKFLOWS:
            for job, minutes in ci_workflow_jobs(workflow).items():
                with self.subTest(workflow=workflow.name, job=job):
                    self.assertIsNotNone(minutes)
                    self.assertGreaterEqual(
                        minutes,
                        floor,
                        f"{workflow.name}:{job} declares timeout-minutes: "
                        f"{minutes}, which is {minutes * 60}s. One allowlisted "
                        "command can hold this job for "
                        f"{harness.worst_case_command_timeout_seconds()}s "
                        "(the calibrator's "
                        f"{harness.calibration_budget_ceiling_seconds()}s "
                        "ceiling plus "
                        f"{harness.CALIBRATION_TIMEOUT_HEADROOM_SECONDS}s of "
                        "headroom), so GitHub would cancel the job before the "
                        "harness could write the partial output that explains "
                        f"the hang. Raise it to at least {floor}, or lower the "
                        "calibrator's ceiling.",
                    )

    def test_baseline_pins_grid_and_warns_about_the_auto_fallback(self) -> None:
        """Verified against installed traigent 0.25.0.

        Locally the SDK registers only `grid` and `random`; the managed
        algorithms are not registered. With no Traigent key, `algorithm="auto"`
        degrades to a local random sweep and logs `fallback_reason=no_api_key` -
        so a run that looks like managed search is really random sampling. The
        same six-point space returns the first grid cell every time under `grid`
        and a different winner under the fallback, which is why the baseline
        pins the algorithm rather than inheriting the default.
        """
        text = SDK_EXECUTION.read_text()
        normalized = " ".join(text.casefold().split())
        for phrase in (
            'pass `algorithm="grid"` explicitly',
            "falls back to a local `random` sweep",
            "fallback_reason=no_api_key",
            "grid also cannot enumerate a continuous parameter",
            "state which algorithm actually ran",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_close_recaps_readiness_and_offers_the_skills_package(self) -> None:
        normalized = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "close the loop on the readiness score the run opened with",
            "show opening beside closing",
            "which remaining gap to close first",
            "one action selected from the latest closing evidence",
            "re-rank the remaining closing caps",
            "npx skills add traigent/traigent-skills",
            "restart the session so the new skills load",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_the_close_states_the_run_scope_it_measured_at(self) -> None:
        """Small numbers read as the product's ceiling unless the close says otherwise.

        The walkthrough bounds itself deliberately - a row subset, a trial cap,
        and only the controls whose wiring it verified - and never told the user
        those were its own choices. So the close carries the three measured
        ratios, and each clause is dropped rather than estimated when this run
        does not hold its number.
        """
        skill_text = " ".join(SKILL.read_text().casefold().split())
        safety_text = " ".join(RUN_SAFETY.read_text().casefold().split())

        for phrase in (
            "rows scored beside the dataset's usable rows",
            "trials executed beside the enhanced space's combination count",
            "knobs varied beside the controls this run identified on the agent",
            "a getting-familiar run rather than the largest one available",
            "drop any clause this run did not measure instead of estimating it",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill_text)

        # Every clause has a stated degradation, so no path reaches the user
        # with an empty or invented number.
        for phrase in (
            "say the run scored every usable row",
            "drop this clause and say it stopped there instead",
            "there is no denominator to quote",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, safety_text)

        # A scope statement, not a pitch. The repository's own rule is that
        # motivation comes from measured evidence, so the close may not predict
        # a win it did not measure or manufacture a reason to act now.
        self.assertIn(
            "it does not predict that a larger run would have won, attach a deadline, "
            "or supply a reason to act now",
            safety_text,
        )

        # The scope statement is stated once and reused, so the no-lift path
        # cannot drift away from it.
        self.assertIn(
            "carry the run-scope statement above into this no-lift report", skill_text
        )
        self.assertLess(
            skill_text.index("the run's scope, in this run's own recorded numbers"),
            skill_text.index("carry the run-scope statement above"),
        )

    def test_the_handoff_names_real_skills_and_only_hypotheses(self) -> None:
        """The user leaves with tools, and with claims this run can support.

        At this run's row and trial counts a control that showed no effect was
        mostly not sampled enough to show one, so the handoff may recommend a
        test and may not report a finding. Every skill it may name has to exist
        in Traigent/traigent-skills, and every flag has to be one that repo
        documents.
        """
        skill_text = " ".join(SKILL.read_text().casefold().split())
        safety_text = " ".join(RUN_SAFETY.read_text().casefold().split())

        for phrase in (
            "so the user can continue alone, at their full dataset",
            "npx skills add traigent/traigent-skills --list",
            "npx skills add traigent/traigent-skills --skill <name>",
            "only which skills get named comes from this run's evidence",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill_text)

        # Claim strength is gated in the mandate itself, not left to the map.
        self.assertIn(
            "is a hypothesis to test at full scale, never a finding", skill_text
        )
        self.assertIn(
            "never that a control was shown not to matter",
            skill_text,
        )
        self.assertIn(
            "never as an established finding",
            safety_text,
        )

        # Only skills that exist in Traigent/traigent-skills, only flags that
        # repository documents. A handoff to a skill that was renamed away is a
        # dead end the user hits after the run is over, and it is discovered
        # after the walkthrough has already ended. Scoped to the map itself:
        # matching the whole file would also collect `traigent-runs` and any
        # future backticked path, and fail with a message about the wrong thing.
        handoff = safety_text.split("### continuation handoff", 1)[1].split("## ", 1)[0]
        named = set(re.findall(r"`(traigent-[a-z-]+)`", handoff))
        self.assertEqual(
            named,
            {
                "traigent-analyze-results",
                "traigent-analyze-variable-importance",
                "traigent-dataset-curate",
                "traigent-eval-audit",
                "traigent-optimize-config-space",
                "traigent-optimize-run",
            },
            "the handoff map names a skill this list has not confirmed exists in "
            "Traigent/traigent-skills - confirm it with `npx skills add "
            "Traigent/traigent-skills --list` and add it here, or drop the row",
        )
        joined = skill_text + " " + handoff
        skills_flags = set(re.findall(r"npx skills add [^`]*?(--[a-z-]+)", joined))
        self.assertEqual(
            skills_flags,
            {"--list", "--skill"},
            "the handoff names an `npx skills add` flag beyond the two that "
            "repository documents",
        )

    def test_cloud_insight_is_described_as_signals_not_numbers(self) -> None:
        """The backend withholds numeric dataset-quality scores from clients.

        Coarse buckets, counts and curation advice are client-visible; the
        underlying quality/coverage/diversity numbers are not. And the analysis
        is run-scoped, so promising to grade a dataset that has not been run
        would be a second false claim.
        """
        normalized = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "only when a verified run-scoped platform artifact actually returned them",
            "never fill the deeper-insights template from expectation",
            "promise a numeric dataset-quality score",
            "imply the platform graded an unrun dataset",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_post_run_insight_avoids_the_plugin_only_analyze_method(self) -> None:
        """Verified on installed traigent 0.25.0.

        `result.analyze()` raises ImportError without the traigent-tuned-variables
        plugin, which this run does not install - calling it would turn a
        finished, already-paid run into a crash at the reporting step. The audit
        and insights helpers, by contrast, are available and free.
        """
        normalized = " ".join(SDK_EXECUTION.read_text().casefold().split())
        for phrase in (
            "do not call the result's `analyze()` method",
            "raises `importerror` without it",
            "neither read is meaningful under mock mode",
            "suspect the expectation before the agent",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_traigent_key_must_have_write_access_not_read_only(self) -> None:
        """A read-only key spends on the run and records nothing.

        Verified in the portal service: a manually created key defaults to
        read-only, so the connected run is rejected at submit time and silently
        drops to local-only tracking. The warning has to land while the user is
        creating the key, because by the time the symptom appears the money is
        already spent.
        """
        normalized = " ".join(RUN_SAFETY.read_text().casefold().split())
        for phrase in (
            "must be able to write experiments, not only read them",
            "a manually created key defaults to read-only",
            "grant it full access",
            "do not add a backend or api url",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_first_time_access_path_is_single_and_ordered(self) -> None:
        """There is exactly one way a first-time user reaches the portal.

        The account is created by entering the single-use access code that
        arrives in the second Traigent email. Sending a user with no account
        straight to the portal's registration page strands them: registration
        requires that credential, so the page rejects them. The funnel stages
        also have to appear in the order the user meets them, or the guide
        reads as though the key can be collected before the account exists.
        Registering does not hand over a key: the user creates one in the
        portal afterwards, which is why the read-only default warning is the
        main path here and not an edge case.
        """
        text = RUN_SAFETY.read_text()
        pre_gate = text.split("Use this gate order:", 1)[0]
        normalized = " ".join(pre_gate.casefold().split())

        ordered_funnel_phrases = (
            "six-digit confirmation code",
            "single-use access code",
            "completes portal registration",
            "create a full-access key",
        )
        for phrase in (
            *ordered_funnel_phrases,
            "second email",
            "valid for 10 days",
            "already confirmed",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

        positions = [normalized.index(phrase) for phrase in ordered_funnel_phrases]
        self.assertEqual(positions, sorted(positions))

    def test_account_state_is_established_before_a_destination_is_named(self) -> None:
        """Receiving the access email and registering are separate acts.

        A user who read the second email and stopped has a valid access code
        and no account, and is the one person the registration page exists for
        - sending them to collect a key strands them just as surely as sending
        a user with no code to register. Registering is likewise not the same
        as holding a key: the key is shown once and cannot be read back, so a
        user who did not save it needs the key page, not the register page.
        The guide has to establish which state the user is in before it names
        a destination.
        """
        normalized = " ".join(RUN_SAFETY.read_text().casefold().split())
        for phrase in (
            "do not assume the user walked the whole path",
            # All four state labels, so a branch cannot be dropped or merged
            # back into an overlapping pair while the test still passes.
            "already registered, key in hand",
            "already registered, no key in hand",
            "not registered, holding an access code still inside its 10 days",
            "not registered, with no usable access code",
            # The destination itself, so the branch cannot silently go back to
            # naming a site it never gives an address for.
            "https://traigent.ai",
            # The four branches partition what the user *holds*. They cannot
            # also partition how long ago it happened - a customer who
            # registered five weeks ago and saved their key classifies as
            # "key in hand" and is still refused once the access period is
            # spent - so the list must not claim to cover every user.
            "those four are exclusive on what the user holds",
            "registering is not the same as holding a key",
            "the key is created in the portal, not issued by registering",
            "top-bar key control",
            "shown once and cannot be read back",
            "https://portal.traigent.ai/management/api-keys",
            "https://portal.traigent.ai/register",
            "it is the code, not the url, that gets a user in",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

        # A present-substring pin cannot see a residual. The unnamed form said
        # "start at the Traigent site" in three places; one substitution left
        # two of them behind and this file still passed, twice. The negative is
        # the half that fails on a leftover.
        self.assertNotIn("at the traigent site", normalized)
        # The other half of the same over-claim. The "key in hand" branch is
        # the one a long-registered customer reads, and the access-period
        # paragraph below says a valid key is still refused once the period is
        # spent - so this branch must not close the question either.
        self.assertNotIn("nothing else is required", normalized)

    def test_both_emailed_codes_are_handled_as_credentials(self) -> None:
        """The two emailed codes are bearer credentials; the link is not.

        The access code authorizes creating the account, so pasting it into chat
        hands that authority to the transcript. Neither it nor the six-digit
        confirmation code is a `uk_`-shaped secret, so the existing "never paste
        or print secrets" rule does not visibly cover them and an assistant can
        ask for them in good faith. The guide has to name them.

        The registration link is deliberately excluded: it carries no credential
        (`/register?lead=1`), because a credential in a URL is logged by nginx,
        kept in browser history and forwarded in the Referer header - the leak
        a backend change exists to remove. The guide must keep saying the
        link is plain, so nobody "helpfully" restores a one-click redeem URL and
        reintroduces it.
        """
        normalized = " ".join(RUN_SAFETY.read_text().casefold().split())
        for phrase in (
            "the confirmation code and the access code are credentials",
            "never ask the user to paste either one into chat",
            "never repeat one back",
            # The link must stay credential-free.
            "carries no credential",
            "the registration address itself is not a credential",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_api_key_authenticates_but_never_grants_portal_access(self) -> None:
        """An expired access period refuses a run that a valid key authenticates.

        The failure looks like the read-only-key failure - the run is refused
        after the money is spent - but the remedy is the opposite. Re-registering
        or minting a second key cannot restore access, and swapping to another
        address to collect a second access period is exactly what the one-period
        rule exists to prevent, so the guide has to name the distinction.
        """
        normalized = " ".join(RUN_SAFETY.read_text().casefold().split())
        for phrase in (
            "portal access period",
            "10 days from the moment the user registers",
            "the key authenticates the run",
            "does not by itself grant portal access",
            "stop and report it",
            "never re-register",
            "never create another key",
            "never switch to a different email address",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_retired_lead_funnel_vocabulary_is_absent(self) -> None:
        """`lead_token` and the two-path framing are gone, not renamed.

        A single-use access code carries the registration authorization, so
        there is no second bearer credential and no cold-start branch beside
        it. These phrases described the retired model; if one reappears the
        guide has drifted back to teaching a path that no longer exists.
        """
        combined = "\n".join(
            path.read_text()
            for path in [SKILL, *sorted((SKILL_ROOT / "references").glob("*.md"))]
        ).casefold()
        for phrase in (
            "self-register",
            "cold start",
            "cold-start",
            "no special expiry",
            "lead funnel",
            "lead-funnel",
            "lead_token",
            "lead path",
            # Auto-issuance, in every phrasing that survived a previous pass.
            # A presence-only contract let these coexist with the corrected
            # prose, so the guide claimed both at once and CI stayed green.
            "key has been issued for you",
            "issues at registration",
            "api key is issued",
            "key is issued on",
        ):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, combined)

    def test_baseline_sync_never_uses_all_and_never_reads_private_layout(self) -> None:
        """Verified against installed traigent 0.25.0.

        `--all` pushes every optimization ever logged on the machine - 1042
        sessions on the box used to check this, including unrelated projects.
        Separately, the SDK exposes no supported id for the run just completed
        (Traigent/Traigent#2020), and the fix for that belongs upstream: this
        repo must not work around it by reading the SDK's private storage
        layout.
        """
        normalized = " ".join(SDK_EXECUTION.read_text().casefold().split())
        for phrase in (
            "never use `--all`",
            "every optimization ever logged on the machine",
            "do not inspect private storage",
            "baseline_results.sync_session_id",
            "successful sync json",
            "traigent/traigent issue 2020",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_local_baseline_checkpoint_states_exactly_what_is_known(self) -> None:
        normalized = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "local fixed grid, not traigent choosing the trials",
            "primary tuning metric by its actual name",
            "executed and failed trial counts",
            "cost or latency as `not measured`",
            "no generalization or production-improvement claim exists yet",
            "this phase created no portal experiment",
            "this checkpoint is a valid place to stop",
            "baseline-only, not as a completed traigent optimization",
            "only after that checkpoint, ask for the traigent key",
            "full access rather than the read-only default",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)
        self.assertIn(
            "for the generated walkthrough, run the credible small space as one local fixed grid",
            " ".join(SDK_EXECUTION.read_text().casefold().split()),
        )

    def test_each_paid_run_has_an_exact_run_card(self) -> None:
        normalized = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "immediately before the paid baseline",
            "model ids",
            "each varying knob and its explicit values",
            "one plain-language note per knob",
            "total combination count",
            # #131 splits the one card in two, so the enhanced card's mandate
            # sits in stage 7 rather than beside the baseline's; #123's
            # follow-up adds the ceiling pairing to it. Both survive.
            "in the enhanced run card, repeat the baseline knobs, "
            "label every addition new",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_the_run_card_states_the_ceiling_against_the_space_it_searches(
        self,
    ) -> None:
        """The card already counts the space; the ceiling is read against it.

        A bare "up to 12" leaves the user with no sense of what 12 is 12 of,
        and the card had already computed the number that answers it. Pairing
        them is also what keeps the ceiling honest in the other direction:
        SKILL.md separately requires the enhanced space to be materially
        larger than the cap, and a card showing both makes a space that is not
        visible rather than merely asserted.
        """
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        self.assertIn(
            "pair that count with this run's trial cap as a ceiling, never a range",
            skill,
        )
        # run-safety.md owns the wording, so SKILL.md points rather than
        # restating it - the #124 rule applied to the copy this change adds.
        # It also must not name the cap, which is a value: `max_trials` is
        # env-overridable and an approved reduction lowers it, so a literal
        # 12 in the mandate is a ceiling the run may not actually be under.
        self.assertIn("`references/run-safety.md` owns that wording", skill)
        # #131 moved the enhanced card behind the baseline checkpoint, so the
        # mandate is bracketed where it now lives rather than at the combined
        # card this test was first written against.
        enhanced_card = skill.split("in the enhanced run card", 1)[1].split(
            "never promise a pause at minute 30", 1
        )[0]
        self.assertIsNone(
            re.search(r"\b12\b", enhanced_card),
            "the run-card mandate names the cap as a literal; it is a value "
            "that an env override or an approved reduction can lower, so the "
            "card would promise a ceiling this run is not under",
        )
        for phrase in (
            "`<total combination count>` possible configurations",
            "traigent will test up to `<enhanced trial cap>` of them",
            "name this count in `configurations` rather than `trials`",
            "give it as a ceiling, never as a range",
            "tested <executed trials> of <total combination count> configurations",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, safety)

    def test_the_card_numbers_come_from_the_approved_space_not_an_example(
        self,
    ) -> None:
        """The reference prints a worked space; the card must not quote it.

        sdk-execution.md's generated default works out to "54 possible
        configurations" - correctly so for the literal spaces it lists, but
        not for its own documented reasoning-tier branch, where pinning
        temperature makes the same default 18. That number now sits one lift
        away from a sentence the user reads and approves spending against, so
        the copy names where both numbers come from rather than leaving the
        nearest concrete figure to be borrowed.
        """
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        self.assertIn("both numbers come from the approved space itself", safety)
        self.assertIn("never from a worked example in a reference", safety)

    def test_the_configurations_noun_rule_does_not_capture_failed_trials(
        self,
    ) -> None:
        """A failed-trial count is a different quantity, not the same jargon.

        The rule exists because "trials" is optimizer vocabulary for the
        number a first-run user is asked to approve. Read as a blanket ban it
        would also condemn the baseline checkpoint's executed/failed trial
        counts, which name SDK records rather than the size of the run - so
        it is scoped to the count it was written for, and says so, rather
        than teaching the next reader to rename something already correct.
        """
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        self.assertIn(
            "`trials` remains the right word for a failed-trial count", safety
        )
        # The pre-existing checkpoint wording stays; a broad rule that
        # silently invalidated it would be the false-red half of this gate.
        self.assertIn(
            "executed and failed trial counts",
            " ".join(SKILL.read_text().casefold().split()),
        )

    def test_an_uncomputable_combination_count_degrades_to_the_ceiling_alone(
        self,
    ) -> None:
        """The paired number is computed, so it can be missing.

        Every other number on the card comes from the space the assistant just
        built, but a preserved user space need not be enumerable, and a
        template with a hole in it invites filling the hole with an estimate.
        The copy therefore names the degraded form explicitly, before and
        after the run, rather than leaving the assistant to improvise one.
        """
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        self.assertIn("cannot be computed", safety)
        self.assertIn(
            "state the ceiling on its own rather than estimating or rounding a total",
            safety,
        )
        self.assertIn(
            "or the executed count alone when that total was unavailable", safety
        )

    def test_the_ten_floor_is_an_internal_check_and_not_a_public_promise(self) -> None:
        """10 governs what the assistant may call the intended comparison.

        It was never a number the user was promised, and the documents they
        read now say only the ceiling - so the obligation has exactly two
        homes, both assistant-facing: sdk-execution.md states it with the
        reasoning, and SKILL.md's stage-8 verification applies it. If a future
        edit drops either, a run that produced three rows can be reported as
        the intended first-run comparison with nothing failing.
        """
        skill = " ".join(SKILL.read_text().casefold().split())
        sdk = " ".join(SDK_EXECUTION.read_text().casefold().split())
        self.assertIn("produced at least 10 of its 12 permitted trials", skill)
        self.assertIn("fewer than 10 rows requires a concrete backend stop", sdk)

        # The public surfaces state a ceiling. A count spoken as a range, or
        # as a raw trial count, is the framing this change removed.
        for name in ("README.md", "GUIDE.md"):
            document = " ".join((ROOT / name).read_text().casefold().split())
            with self.subTest(document=name):
                self.assertIn("up to 12 configurations", document)
                self.assertIsNone(
                    re.search(r"\d+\s*-\s*\d+ (?:trials|configurations)", document),
                    f"{name} gives the enhanced count as a range; at approval "
                    "time the user is asking for the worst case, which only a "
                    "ceiling answers",
                )
                self.assertIsNone(
                    re.search(r"\bup to \d+ trials\b", document),
                    f"{name} states the ceiling in trials; the user-facing "
                    "noun is `configurations`",
                )

    def test_final_report_layers_facts_limits_and_the_latest_next_action(
        self,
    ) -> None:
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        for phrase in (
            "**outcome** - baseline versus enhanced result",
            "**what the evidence establishes**",
            "**current state and limits**",
            "**next action** - one action selected from the latest closing evidence",
            "**details** - configurations, objectives, trials, failures, cost",
            "only fields actually returned",
            "verified run-scoped platform artifact actually returned them",
            "latest validated state",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)
        for phrase in (
            "verified facts, evidence-backed inferences, and untested hypotheses",
            "cause not established by this run",
        ):
            self.assertIn(phrase, safety)

    def test_optional_validation_is_not_part_of_the_default_run(self) -> None:
        documents = {
            "guide": " ".join((ROOT / "GUIDE.md").read_text().casefold().split()),
            "skill": " ".join(SKILL.read_text().casefold().split()),
            "sdk": " ".join(SDK_EXECUTION.read_text().casefold().split()),
            "dataset": " ".join(
                (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
                .read_text()
                .casefold()
                .split()
            ),
            "glossary": " ".join(
                (SKILL_ROOT / "references" / "glossary.md")
                .read_text()
                .casefold()
                .split()
            ),
        }
        for name, text in documents.items():
            with self.subTest(document=name):
                self.assertNotIn("18 tuning / 10 validation", text)
                self.assertNotIn("28 rows split", text)
                self.assertNotIn("create 28 examples by default", text)

        dataset = documents["dataset"]
        self.assertIn("create 18 tuning examples by default", dataset)
        self.assertIn("do not create a held-back validation set", dataset)
        self.assertIn("optional follow-up evidence", documents["glossary"])

        run_plan = " ".join(
            (SKILL_ROOT / "assets" / "run-plan.md").read_text().casefold().split()
        )
        for phrase in (
            "tuning rows, coverage, and known limitations",
            "local baseline checkpoint",
            "successful cli url, or `local-only` with reason",
            "baseline-versus-enhanced comparison - measured tuning behavior",
        ):
            self.assertIn(phrase, run_plan)

    def test_privacy_is_a_documented_contract_and_errors_are_sanitized(self) -> None:
        readme_source = (ROOT / "README.md").read_text()
        readme = " ".join(readme_source.casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        for phrase in (
            "pinned sdk 0.25.0 telemetry contract",
            "tuned configuration keys and values",
            "observability content the project explicitly opts into recording",
            "short content-free labels",
            "raw prompt text is not used as a configuration value",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)
        self.assertIn(
            "https://github.com/Traigent/Traigent/blob/v0.25.0/"
            "docs/api-reference/telemetry.md",
            readme_source,
        )
        self.assertIn("does not independently audit network packets", readme)
        self.assertIn(
            "stops if observed runtime behavior contradicts that contract", readme
        )
        for phrase in (
            "does not send user prompts or inputs",
            "to the traigent backend",
            "local optimization logs",
            "`query`, `response`, and `expected`",
            "`traigent_log_example_content=false`",
            "example ids and metrics",
            "content fields as `null`",
        ):
            with self.subTest(privacy_boundary=phrase):
                self.assertIn(phrase, readme)
        sdk = SDK_EXECUTION.read_text()
        wrapper = re.findall(r"```python\n(.*?)\n```", sdk, re.DOTALL)[0]
        content_opt_out = 'os.environ["TRAIGENT_LOG_EXAMPLE_CONTENT"] = "false"'
        self.assertIn(content_opt_out, wrapper)
        self.assertLess(
            wrapper.index(content_opt_out), wrapper.index("import traigent")
        )
        for phrase in (
            "backend transmission and local persistence as separate boundaries",
            "writes per-example `query`, `response`, and `expected` text",
            "retains example ids and metrics",
            "project-defined results folder",
        ):
            with self.subTest(local_log_boundary=phrase):
                self.assertIn(phrase, safety)
        self.assertIn(
            "privacy wording describes traigent's documented backend-payload contract",
            safety,
        )
        self.assertIn("never a raw traceback", safety)
        self.assertIn("sanitized provider message", safety)

    def test_the_grid_pin_is_scoped_to_the_baseline_only(self) -> None:
        """Pinning the connected search to a local algorithm would gut it.

        Verified on installed traigent 0.25.0: `auto` resolves to a cloud-brain
        execution intent, while naming `grid` or `random` resolves to a
        local-only intent. So pinning the enhanced run does not merely choose a
        weaker search - it bypasses a valid key entirely and the second run stops
        being a Traigent optimization, which is the whole comparison the first
        run exists to show.
        """
        normalized = " ".join(SDK_EXECUTION.read_text().casefold().split())
        for phrase in (
            "this applies to the local baseline only",
            'the connected search under "broader optimization" must stay on `auto`',
            'keep `algorithm="auto"` here, and never pin `grid` or `random`',
            "explicit `grid` or `random` selects configurations locally",
            "a valid key may still portal-track that local search",
            "the pinning rule is therefore per phase, not global",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_enhanced_run_code_block_still_uses_auto(self) -> None:
        """Guard the code itself, not only the prose around it."""
        text = SDK_EXECUTION.read_text()
        enhanced = text[text.index("## Broader optimization") :]
        enhanced = enhanced[: enhanced.index("## Result checks")]
        self.assertIn('algorithm="auto"', enhanced)
        self.assertNotIn('algorithm="grid"', enhanced)
        self.assertNotIn('algorithm="random"', enhanced)

    def test_absent_cost_is_never_reported_as_zero(self) -> None:
        """A stated $0.00 reads as "this was free", which is a false claim."""
        normalized = " ".join(SDK_EXECUTION.read_text().casefold().split())
        self.assertIn("an absent cost is `not measured`", normalized)
        self.assertIn("never turn absence into `$0.00`", normalized)
        self.assertIn("provider-reported zero with nonzero token usage", normalized)

    def test_local_baseline_is_free_of_traigent_not_free_of_spend(self) -> None:
        """The preview needs no Traigent key but still spends real provider money."""
        normalized = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "needs only the user's provider credential",
            "without a traigent key in that process",
            "it is local, not free",
            "spend from the same approved total",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_first_python_fence_is_the_decorator_contract(self) -> None:
        """Guard the positional dependency in the exec'd-fence tests.

        `test_sdk_comparison_uses_six_rows_then_added_knobs_and_twelve_trials`
        executes `re.findall(r"```python...")[0]` - the FIRST python fence in
        sdk-execution.md. Inserting any python fence above it silently changes
        which block is executed, and that test then fails with a confusing
        NameError or AssertionError that names neither ordering nor the new
        fence. This turns that into a failure that says what actually happened.
        """
        fences = re.findall(r"```python\n(.*?)\n```", SDK_EXECUTION.read_text(), re.S)
        self.assertTrue(fences, "sdk-execution.md must contain a python fence")
        self.assertIn(
            "BASELINE_SPACE = {",
            fences[0],
            "the first ```python fence in sdk-execution.md is no longer the "
            "decorator-contract block; a fence was inserted above it, which "
            "silently changes what the exec'd-fence tests run",
        )

    def test_run_phase_removes_portal_key_before_traigent_import(self) -> None:
        """The local-first guarantee must survive a stale key in ``.env``.

        Removing the key only in the later baseline call block is too late if
        an import-time SDK client has already captured it. The process phase is
        therefore read before dotenv, and the fail-safe baseline removes the
        portal key before the Traigent import.
        """
        text = SDK_EXECUTION.read_text()
        decorator = re.findall(r"```python\n(.*?)\n```", text, re.DOTALL)[0]
        phase = decorator.index("FIRST_RUN_PHASE = os.environ.get(")
        dotenv = decorator.index('load_dotenv(PROJECT_ROOT / ".env"')
        remove_key = decorator.index('os.environ.pop("TRAIGENT_API_KEY", None)')
        import_traigent = decorator.index("import traigent")
        self.assertLess(phase, dotenv)
        self.assertLess(dotenv, remove_key)
        self.assertLess(remove_key, import_traigent)
        self.assertIn('if FIRST_RUN_PHASE == "baseline":', decorator)

        baseline = text[text.index("## Small baseline sweep") :]
        baseline = baseline[: baseline.index("## Reading the result for insight")]
        connected = text[text.index("## Broader optimization") :]
        connected = connected[: connected.index("## Result checks")]
        self.assertIn('assert FIRST_RUN_PHASE == "baseline"', baseline)
        self.assertIn('assert FIRST_RUN_PHASE == "connected"', connected)
        self.assertIn(
            "supplied by the process and never by `.env`",
            " ".join(baseline.split()),
        )
        self.assertIn(
            "supplied by the process and never by `.env`",
            " ".join(connected.split()),
        )

    def test_first_json_fence_is_the_calibration_matrix(self) -> None:
        """Guard the same positional dependency for the calibration example.

        `test_calibration_matrix_example_has_per_case_modes` parses the FIRST
        ```json fence in evaluation-and-dataset.md.
        """
        text = (SKILL_ROOT / "references" / "evaluation-and-dataset.md").read_text()
        match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
        self.assertIsNotNone(
            match, "evaluation-and-dataset.md must contain a json fence"
        )
        cases = json.loads(match.group(1))
        self.assertIsInstance(
            cases,
            list,
            "the first ```json fence in evaluation-and-dataset.md is no longer "
            "the calibration-case matrix; a fence was inserted above it",
        )
        self.assertTrue(
            all(isinstance(case, dict) and "probes" in case for case in cases),
            "the first ```json fence must still be the calibration-case matrix",
        )

    def test_readiness_score_is_a_mandatory_gate(self) -> None:
        normalized = " ".join(SKILL.read_text().casefold().split())
        self.assertNotIn("when helpful", normalized)
        for phrase in (
            "as a mandatory gate",
            "#### opening readiness gate",
            "before any component creation or repair",
            "including a zero-anchor run",
            "the opening score is not skippable",
            "always reports all three pillars",
            "again as a required step of local validation",
            "the score grades measured evidence, not declared existence",
            # the opening score must reach the USER, not merely be computed
            "show it before anything is created or repaired",
            # a cap phrased for an absent component must not be read aloud at a
            # component that exists but is only unmeasured
            "describe an existing but unmeasured component as not yet measured",
            # the two sentences that reconcile a mandatory opening score with the
            # zero-anchor zero-writes ban - without these the doctrine reads as
            # licensing a pre-answer write
            "they authorize no project write",
            "recording it is a write and waits for the answer",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_historical_wiring_is_omitted_until_current_run_evidence_exists(
        self,
    ) -> None:
        """A stale author attestation cannot turn the opening card green."""
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        sdk = " ".join(SDK_EXECUTION.read_text().casefold().split())
        for phrase in (
            "historical context, not current-run readiness evidence",
            "omit every config-space file found before this run's enhanced search",
            "timestamp, hash, or non-empty `wired` list",
            "not yet measured",
            "do not infer `wired` from declared `knobs`",
            "zero-anchor opening may proceed",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)
        for phrase in (
            "including one left by an earlier guided run",
            "historical context only",
            "only that current-run file enters closing readiness",
            "request visibility, per model",
            "unverified claim for a reader to challenge",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, f"{safety} {sdk}")

    def test_every_agent_cap_condition_has_a_documented_branch(self) -> None:
        """The sibling below covers the dataset caps; nothing covered the agent one.

        SKILL.md's own sentence says "evaluator and agent caps route through the
        rules that already own them" and then routed no agent condition at all,
        while SKILL.md separately forbids showing a condition id to the user. So
        the assistant met the one cap that fires on every single run with no
        branch to take and no words to say, and a sentence claiming completeness
        is exactly what stops anyone checking.

        Scoped to the agent conditions, not to all of `ACTION_FOR_CONDITION`.
        The first draft here checked every condition the scorer can emit, which
        made this branch's guard depend on a sentence a different branch owns -
        `evaluator-timeout`'s route, which three open pull requests each wrote
        differently and which the owner settled into #151. A guard that can only
        pass after someone else's merge is not a guard on this change. Three
        sibling checks - dataset, evaluator, agent - each live with the branch
        that owns that rule, and together they still cover every condition.

        Enumerated from the module rather than listed here, for the same reason
        the dataset check pins its count: a second agent cap must be routed too.
        """
        source = (SKILL_ROOT / "scripts" / "readiness.py").read_text()
        conditions = {
            condition
            for condition in re.findall(r'Cap\(\s*"([a-z0-9-]+)"', source)
            if condition.startswith("agent-")
        }
        self.assertEqual(conditions, {"agent-no-varying-knobs"})
        normalized = " ".join(SKILL.read_text().casefold().split())
        # Split at the evaluator/agent sentence, not at the dataset one. This
        # branch also teaches the dataset intro the blocks-vs-advisory rule in
        # the same words ("an advisory ceiling, never a repair to route"), so a
        # search from the dataset anchor finds that sentence first and the
        # ordering assertion below reads a phrase 1_600 bytes before the
        # condition it is supposed to be routing.
        routing = normalized.split(
            "evaluator and agent caps route through the rules that already own them", 1
        )[1]
        for condition, branch in (
            ("agent-no-varying-knobs", "that run's own outcome to report"),
        ):
            with self.subTest(condition=condition):
                self.assertIn(
                    condition,
                    routing,
                    f"{condition} can stop or bound a run and the guidance "
                    "never names it, so the assistant has no branch to take "
                    "and no words to say - condition ids stay internal",
                )
                self.assertLess(routing.index(condition), routing.index(branch))

    def test_the_advisory_claim_matches_which_branches_actually_block(
        self,
    ) -> None:
        """SKILL.md routes by condition id, so a claim about one branch is a
        claim about every branch sharing that id.

        `agent-no-varying-knobs` was described as "an advisory ceiling, never a
        repair to route", justified by the branch where no settings document
        was provided - which is genuinely advisory (`blocks=False`). But the
        condition has five other construction sites and every one of them
        blocks, printing `FIX BEFORE PAID RUN` on the card while the routing
        bullet an assistant reads by id says the opposite.

        Read off the module rather than pinned: a sixth branch must be
        classified too.
        """
        both = {True: [], False: []}
        for name, value in vars(READINESS).items():
            if isinstance(value, READINESS.Cap) and (
                value.condition == "agent-no-varying-knobs"
            ):
                both[value.blocks].append(name)
        self.assertTrue(both[False], "no advisory branch left to justify the claim")
        self.assertTrue(both[True], "no blocking branch left; rewrite this check")
        normalized = " ".join(SKILL.read_text().casefold().split())
        routing = normalized.split("evaluator and agent caps route through", 1)[1]
        # The claim must be scoped, not stated of the condition as a whole.
        self.assertNotIn(
            "`agent-no-varying-knobs` is an advisory ceiling, never a repair to route",
            routing,
        )
        self.assertIn("is an advisory ceiling only where", routing)
        # And the blocking half must be stated, since that is what the card
        # prints for five of the six branches.
        self.assertIn("the same condition blocks", routing)
    def test_an_unrecognised_shape_is_read_before_it_is_called_broken(self) -> None:
        """The route has to say READ, not just "not creation".

        Removing "do not enter the creation dependency matrix" is caught by the
        branch table below. Replacing the rest of the sentence with the repair
        instruction it used to carry is not: the branch still routes away from
        creation, and the assistant is still told to fix a file nobody has
        opened. Both halves are the fix, so both are asserted.

        The obligation itself lives once, in the reference that owns the
        dataset stage - re-run the check with the paths the file uses, or
        convert a format the check does not read, and only then judge the data.
        SKILL.md names the order and points at it. Deleting either leaves the
        other stating half a route, which is why the two are pinned together.
        """
        skill = " ".join(SKILL.read_text().casefold().split())
        reference = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "re-map it per the dataset reference",
            "repair, then create, only if mapping fails",
        ):
            with self.subTest(document="SKILL.md", phrase=phrase):
                self.assertIn(phrase, skill)
        for phrase in (
            "correct the shape, not the data",
            "re-run preflight with the field paths the file actually uses",
            "convert a non-jsonl file into a jsonl working copy",
            "only when mapped rows still yield no input and expected answer",
        ):
            with self.subTest(document="evaluation-and-dataset.md", phrase=phrase):
                self.assertIn(phrase, reference)

    def test_every_dataset_cap_condition_has_a_documented_branch(self) -> None:
        source = (SKILL_ROOT / "scripts" / "readiness.py").read_text()
        # Scanned over the whole module, not one function body: the dataset caps
        # were split across `score_dataset` and `score_provenance`, and a scan
        # scoped to the first silently stopped seeing the provenance ones - the
        # guard went green while covering less.
        conditions = {
            condition
            for condition in re.findall(r'Cap\(\s*"([a-z0-9-]+)"', source)
            if condition.startswith("dataset-")
        }
        # A twelfth dataset cap must be routed too, so pin the count rather
        # than spot-checking the eleven that exist today. Ten when #149 wrote
        # this; #161 added the middle answer-key rung and #144 added
        # `dataset-shape-unrecognised`, and neither branch could see the other
        # two.
        self.assertEqual(len(conditions), 13)
        normalized = " ".join(SKILL.read_text().casefold().split())
        routing = normalized.split("route every active dataset cap", 1)[1]
        for condition, branch in (
            ("dataset-absent", "creation dependency matrix"),
            # An unrecognised shape routes to reading the file, and explicitly
            # NOT to creation: the id it used to share sent a customer holding
            # a perfectly good file into the dataset-creation branch. It does
            # not route to repair either - most files that reach it are not
            # broken, so the branch must not open by calling them invalid.
            (
                "dataset-shape-unrecognised",
                "do not enter the creation dependency matrix",
            ),
            ("dataset-no-expected-outputs", "repairing a labelled working copy"),
            ("dataset-integrity-fail", "repair and revalidate a working copy"),
            ("dataset-tune-holdout-overlap", "repair a disjoint split"),
            ("dataset-fully-synthetic", "walkthrough labeling rules"),
            ("dataset-mostly-synthetic", "name the split out loud"),
            (
                "dataset-undeclared-provenance",
                "say the assumption and both card scores",
            ),
            ("dataset-mostly-undeclared", "say the assumption and both card scores"),
            (
                "dataset-generated-answer-key",
                "a person reviews a sample of the answers",
            ),
            # The rung between "none of it" and "all of it", which the ladder
            # did not have: with one rung the cap turned on the last row.
            (
                "dataset-mostly-generated-answer-key",
                "the same review, on the model-written answers only",
            ),
            # Both map to `get-data`, and neither bullet said anything about
            # data: one said "call rankings exploratory" and the other said
            # report paired uncertainty. Read together with the action they
            # emit, the guidance told a customer to hedge the claim and never
            # what would lift the ceiling. The branch has to do what the action
            # name says, or the two halves route differently.
            # Distinct phrases, because the two conditions kept separate
            # bullets: #149 gave `below-measurable-size` a second, blocking
            # half that a merged bullet cannot carry, so `.index()` on one
            # shared phrase would find the earlier bullet for both.
            ("dataset-below-measurable-size", "more comparable examples is what lifts this"),
            ("dataset-coarse-resolution", "more comparable examples is what lifts this too"),
        ):
            with self.subTest(condition=condition):
                self.assertIn(condition, conditions)
                self.assertLess(routing.index(condition), routing.index(branch))
        # Every dataset condition the scorer can raise is routed here, not just
        # the ones this table spells out. The count above pins how many exist;
        # this pins that none of them reaches a reader with no branch at all.
        for condition in conditions:
            with self.subTest(condition=condition):
                self.assertIn(condition, routing)
        self.assertIn("present the reason rather than the condition id", normalized)
        # And the rule that decides which routes stop the run, checked against
        # the scorer rather than only quoted. Without it the routing list is
        # nine branches a reader classifies one at a time, which is how four of
        # them came to block while a fifth saying the same kind of thing did
        # not. Deliberately paired with the module: guidance that says
        # "advisory" over a scorer that blocks is the contradiction, not either
        # half alone.
        self.assertIn(
            "a route asking for a creation or repair blocks the run; one that "
            "only scopes what the result may claim is an advisory ceiling, "
            "never a repair to route",
            normalized,
        )
        blocking = {
            "dataset-absent",
            "dataset-no-expected-outputs",
            "dataset-integrity-fail",
            "dataset-tune-holdout-overlap",
            # #165's two rungs. Same ceilings as the declared pair, and a
            # different category: `declare-data-provenance` asks the user to
            # change the file, which #149's rule reads as a repair. #165's own
            # adapter tests assert the stop.
            "dataset-undeclared-provenance",
            "dataset-mostly-undeclared",
        }
        scoping = {
            "dataset-fully-synthetic",
            "dataset-mostly-synthetic",
            "dataset-generated-answer-key",
            # #161's second rung, added here because #149 wrote this partition
            # before that rung existed and #161 added the rung without seeing
            # the partition. It scopes: SKILL.md routes it to the same review
            # as the rung above, on the model-written answers only, and says
            # the run proceeds meanwhile.
            "dataset-mostly-generated-answer-key",
            "dataset-coarse-resolution",
        }
        # The third category, and the reason it has to exist: one condition
        # decides at runtime. `dataset-below-measurable-size` is advisory with
        # examples to compare on and blocks with none, so it belongs in neither
        # set above, and the routing bullet has to carry both halves - the same
        # shape `agent-no-varying-knobs` was given by the sibling test below.
        conditional = {"dataset-below-measurable-size"}
        # #144's condition: the remedy is one look at the file, so it is
        # neither a repair nor a scope. It stops the run - nothing was
        # measured - but the card may not call the file broken.
        diagnostic = {"dataset-shape-unrecognised"}
        self.assertEqual(blocking | scoping | conditional | diagnostic, conditions)
        sites = cap_construction_blocks(
            source, READINESS.Cap.__dataclass_fields__["blocks"].default
        )
        for condition in sorted(conditions):
            with self.subTest(cap=condition):
                declared = sites[condition]
                if condition in blocking:
                    self.assertEqual(
                        declared,
                        {"True"},
                        f"SKILL.md routes {condition} to a creation or a "
                        "repair, so every site must block",
                    )
                elif condition in diagnostic:
                    self.assertEqual(
                        declared,
                        {"True"},
                        f"SKILL.md routes {condition} to a look at material "
                        "that may be fine, but nothing was measured, so the "
                        "run still waits",
                    )
                elif condition in scoping:
                    self.assertEqual(
                        declared,
                        {"False"},
                        f"SKILL.md routes {condition} by scoping the claim, "
                        "so the scorer may bound the score and may not stop the "
                        "run or demand a repair",
                    )
                else:
                    # Neither literal. If a site ever settles on one, this
                    # condition belongs in `blocking` or `scoping` above and the
                    # bullet should stop carrying a half that cannot happen.
                    self.assertNotIn(
                        declared,
                        ({"True"}, {"False"}),
                        f"{condition} no longer decides at runtime; move it out "
                        "of `conditional` and simplify its routing bullet",
                    )
                    # And the bullet must state both halves, because SKILL.md
                    # routes by condition id: an assistant reading the advisory
                    # sentence by id is told the opposite of what the card
                    # prints for a 240-row dataset whose tuning side carries no
                    # labels - measured `FIX BEFORE PAID RUN no example can be
                    # scored`, status BLOCKED.
                    bullet = routing.split(f"`{condition}`", 1)[1].split("- `", 1)[0]
                    self.assertIn("only where", bullet)
                    self.assertIn("the same condition blocks", bullet)
                    self.assertIn("fix before paid run", bullet)
        # The other half of the same mandate, which had no home and no test:
        # a reason routed correctly and phrased in this module's vocabulary is
        # still a reason the reader cannot act on.
        self.assertIn("in the user's language", normalized)
        self.assertIn("machine vocabulary and condition ids stay internal", normalized)

    def test_run_record_keeps_the_readiness_transition(self) -> None:
        text = (SKILL_ROOT / "assets" / "run-plan.md").read_text().casefold()
        for phrase in (
            # both entries must keep the three fields the audited before/after
            # transition is made of, not just their headings
            "opening readiness score before any creation or repair - overall, "
            "band, binding caps:",
            "latest revalidated readiness score - overall, band, binding caps, "
            "and what changed:",
            "readiness transition",
            "`🛠️` substitute",
            # the record has to have somewhere to put what this run changed on
            # the customer's behalf, or the obligation to name it lands in
            # free text and stops being auditable
            "row ids repaired into the working copy, and row ids generated to "
            "fill a gap:",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        # a transition needs a fixed baseline: without this rule the opening
        # entry can be updated in place and the before/after becomes after/after
        self.assertIn(
            "never overwrite the recorded opening score",
            " ".join(SKILL.read_text().casefold().split()),
        )

    def test_final_report_shows_the_readiness_transition(self) -> None:
        normalized = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "the recorded opening score beside the closing one",
            "naming cleared and remaining caps",
            "treat every gain from a `🛠️` substitute as walkthrough setup",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_repair_paths_require_rescoring_and_active_branches(self) -> None:
        def norm(name: str) -> str:
            return " ".join(
                (SKILL_ROOT / "references" / name).read_text().casefold().split()
            )

        evaluation = norm("evaluation-and-dataset.md")
        glossary = norm("glossary.md")
        skill = " ".join(SKILL.read_text().casefold().split())
        self.assertIn("the applicable calibration, and the readiness score", evaluation)
        self.assertIn("because a file changed or because the score rose", evaluation)
        self.assertIn("route every active dataset cap", skill)
        self.assertIn("never real-world readiness", norm("component-creation.md"))
        self.assertNotIn("by default it never stops the run", glossary)
        self.assertIn("it decides what the run does next", glossary)

    def test_unusable_rows_are_diagnosed_from_the_file_not_from_the_summary(
        self,
    ) -> None:
        """The assistant has the file open; a relayed summary is a guess it did not have to make.

        The card's reason forwards preflight's own FAIL detail, which is honest
        but second-hand: it names a count, a percentage, and a line. The user
        can read that much themselves. What only the assistant can do is open
        the file and say which field the rows actually use against the one the
        run selected - which is also what turns "your data is unusable" into a
        one-line fix.

        Stated in the reference that owns the dataset stage and nowhere else,
        per CLAUDE.md: a second statement of a rule is a rule that can be
        changed in one place.
        """
        evaluation = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "where to look, not what to report",
            "open the file at those lines",
            "the field the rows use against the field the run selected",
            "relaying a summary they could have read themselves",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, evaluation)
        # One home. SKILL.md carries the flow and the routing, not the depth.
        self.assertNotIn(
            "open the file at those lines",
            " ".join(SKILL.read_text().casefold().split()),
        )

    def test_rows_changed_on_the_users_behalf_are_named_by_id(self) -> None:
        """ "Some rows were fixed" cannot be inspected, and neither can a count.

        Two things this guide does to a customer's data - repairing rows into a
        working copy, and generating rows to fill a gap - were reported without
        saying WHICH rows. The ids are already the identifier here: the bounded
        subset records the ones it chose, and an excluded degenerate gold
        records its own. This reuses them rather than adding a second scheme.
        """
        evaluation = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "name what changed by row id",
            "these ids were repaired, these ids are synthetic",
            "record both lists in `traigent-runs/run-plan.md` and say them to the user",
            # the reuse is the point - a second identifier scheme would be a
            # second place for two records of the same row to disagree
            "so reuse them rather than inventing a second way to point at a row",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, evaluation)

    def test_first_json_fence_in_run_safety_is_the_config_space_example(self) -> None:
        """Guard the positional dependency the next test relies on.

        `test_config_space_example_clears_the_cap_through_the_real_consumer`
        parses the FIRST ```json fence in run-safety.md. Inserting any json
        fence above it silently changes which document gets scored, and that
        test then fails in a way that names neither ordering nor the new fence.
        """
        match = re.search(r"```json\n(.*?)\n```", RUN_SAFETY.read_text(), re.DOTALL)
        self.assertIsNotNone(match, "run-safety.md must contain a json fence")
        document = json.loads(match.group(1))
        self.assertIsInstance(
            document,
            dict,
            "the first ```json fence in run-safety.md is no longer the "
            "config-space example; a fence was inserted above it",
        )
        for field in ("knobs", "wired"):
            self.assertIn(
                field,
                document,
                "the first ```json fence in run-safety.md must still be the "
                "config-space example; a fence was inserted above it",
            )

    def test_config_space_example_clears_the_cap_through_the_real_consumer(
        self,
    ) -> None:
        """The documented shape is scored, not merely described.

        This is what stops the worked example in run-safety.md drifting from
        `agent_facts_from_config_space`: the fence is fed to the real adapter and
        the real agent scorer, so a schema change on either side fails here
        instead of shipping prose that no longer parses.
        """
        match = re.search(r"```json\n(.*?)\n```", RUN_SAFETY.read_text(), re.DOTALL)
        assert match is not None
        pillar, conditions = score_config_space(json.loads(match.group(1)))
        self.assertEqual(conditions, [])
        # 90 = 35/35 knob-count + 30.4/40 variation + 25/25 coverage. It was 78
        # while the `general` catalog spelled the prompt dimension
        # `prompt_policy` (the template emits `prompt_style`) and still listed
        # `max_tokens`: the walkthrough lost 12.5 of 25 coverage points to a
        # naming mismatch and to a capacity guard run-safety.md forbids
        # sweeping. Both are catalog defects, so the document scores higher
        # without any change to the space it describes.
        self.assertEqual(pillar.score, 90)
        self.assertEqual(pillar.confidence, 1.0)

    def test_config_space_document_is_serialized_before_but_written_after(self) -> None:
        """The document must not be able to drift *or* outlive a failed search.

        Written before `optimize_sync`, the file survives a search that raised
        and a later score reads it as evidence for a run that never happened.
        Serialized after the call, it could describe a mutated space. So the
        template does both halves: freeze the bytes from the space this call
        receives, persist them only once the call has returned.
        """
        text = SDK_EXECUTION.read_text()
        enhanced = text[text.index("## Broader optimization") :]
        enhanced = enhanced[: enhanced.index("## Result checks")]
        serialize = enhanced.find("config_space_document(ENHANCED_SPACE)")
        search = enhanced.find("optimized_results = agent.optimize_sync(")
        write = enhanced.find("Path(CONFIG_SPACE_DOCUMENT).write_text(")
        self.assertNotEqual(
            serialize, -1, "the enhanced block must serialize the config space"
        )
        self.assertNotEqual(search, -1)
        self.assertNotEqual(write, -1, "the enhanced block must write the document")
        self.assertLess(
            serialize,
            search,
            "the config-space document must be serialized from the space this "
            "call receives, or it can record a space the run never got",
        )
        self.assertLess(
            search,
            write,
            "the config-space document must be written only after the search "
            "returns, or a failed run leaves evidence for a search that never ran",
        )
        # The write must persist the pre-call bytes, not re-serialize after it.
        self.assertNotIn(
            "write_text(\n    json.dumps(config_space_document",
            enhanced,
            "re-serializing at write time reintroduces the drift the early "
            "serialization exists to prevent",
        )

    def _template_producer_namespace(self) -> dict:
        """Execute the template's spaces and its config-space producer.

        The lifecycle tests below run the template's own enhanced-search block,
        so they need the same objects that block closes over.
        """
        code = re.findall(
            r"```python\n(.*?)\n```", SDK_EXECUTION.read_text(), re.DOTALL
        )[0]
        wanted_assignments = {
            "BASELINE_CONFIG",
            "BASELINE_SPACE",
            "ENHANCED_SPACE",
            "AGENT_TYPE",
            "WIRED_KNOBS",
        }
        selected = [
            node
            for node in ast.parse(code).body
            if (
                isinstance(node, ast.FunctionDef)
                and node.name in {"configuration_count", "config_space_document"}
            )
            or (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id in wanted_assignments
                    for target in node.targets
                )
            )
        ]
        namespace = {
            "math": __import__("math"),
            "SELECTED_CURRENT_MODEL": "provider/current",
            "SELECTED_ALTERNATIVE_MODEL": "provider/alternative",
            "SELECTED_STRONG_MODEL": "provider/strong",
            "STRONG_REASONING_EFFORT": None,
            "BASELINE_TRIALS": 4,
            "ENHANCED_MAX_TRIALS": 12,
        }
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])),
                "<sdk-config-space-producer>",
                "exec",
            ),
            namespace,
        )
        return namespace

    def test_config_space_document_never_outlives_the_search_it_describes(self) -> None:
        """Run the template's own search block and check what is left on disk.

        Ordering assertions only prove a *first* run leaves nothing behind.
        They cannot see the two cases that still produced false evidence: a
        retry over a changed space whose search raises keeps the previous run's
        document, and a return that executed no trial writes one. Nor can they
        see *what* is written - replacing the write body with
        `write_text("{}\\n")` satisfies every ordering check.

        So this executes the block against a stub search: the document must
        hold exactly the bytes serialized from the space the call received, and
        must be absent - not stale - whenever the search did not deliver trials.
        """
        producer = self._template_producer_namespace()
        text = SDK_EXECUTION.read_text()
        enhanced = text[text.index("## Broader optimization") :]
        enhanced = enhanced[: enhanced.index("## Result checks")]
        fence = re.search(r"```python\n(.*?)\n```", enhanced, re.DOTALL)
        self.assertIsNotNone(fence, "the enhanced search must still be a python fence")
        block = compile(fence.group(1), "<sdk-enhanced-search>", "exec")

        expected = (
            json.dumps(
                producer["config_space_document"](producer["ENHANCED_SPACE"]),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        searched: list[dict] = []

        def run(document: Path, outcome) -> None:
            def optimize_sync(**kwargs):
                searched.append(kwargs)
                return outcome()

            namespace = dict(producer)
            namespace.update(
                {
                    "json": json,
                    "Path": Path,
                    "os": SimpleNamespace(environ={"TRAIGENT_API_KEY": "test-key"}),
                    "FIRST_RUN_PHASE": "connected",
                    "agent": SimpleNamespace(optimize_sync=optimize_sync),
                    "OPTIMIZATION_TIMEOUT_SECONDS": 60.0,
                    "OPTIMIZED_RESULTS": str(
                        document.parent / "optimized-results.json"
                    ),
                    "CONFIG_SPACE_DOCUMENT": str(document),
                }
            )
            exec(block, namespace)

        def raises():
            raise RuntimeError("provider error")

        stale = '{"knobs": {"stale": [1, 2]}}\n'
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "config-space.json"

            run(document, lambda: SimpleNamespace(trials=[{"trial": 1}]))
            self.assertEqual(
                document.read_text(),
                expected,
                "the file must hold the document serialized from the space this "
                "call received, not whatever the write body happens to emit",
            )
            self.assertEqual(
                json.loads(document.read_text())["knobs"],
                searched[-1]["configuration_space"],
                "the persisted knobs must be the space optimize_sync was given",
            )

            # A retry: an earlier run's document is already on disk and this
            # search raises. Write-after-return alone leaves the stale file as
            # evidence for a search that is no longer the one being reported.
            document.write_text(stale)
            with self.assertRaises(RuntimeError):
                run(document, raises)
            self.assertFalse(
                document.exists(),
                "a search that raised must leave no config-space document, "
                "including one written by an earlier search",
            )

            # A search that returns having executed nothing searched no space
            # either, so it must not produce evidence that it did.
            document.write_text(stale)
            with self.assertRaises(AssertionError):
                run(document, lambda: SimpleNamespace(trials=[]))
            self.assertFalse(
                document.exists(),
                "a zero-trial return must leave no config-space document",
            )

    def test_skill_and_template_agree_on_when_the_document_is_written(self) -> None:
        """One behaviour, three documents - they must not contradict each other.

        SKILL.md is always loaded and the references are bundled, so an
        assistant adapting the wrapper for a real agent follows SKILL.md's
        timing. While SKILL.md said "serialize it to
        `traigent-runs/config-space.json` ... before the connected search
        runs", the write-after-return fix lived only in sdk-execution.md and
        was unreachable from the instruction that actually gets read.
        """
        documents = {
            "SKILL.md": " ".join(SKILL.read_text().casefold().split()),
            "sdk-execution.md": " ".join(SDK_EXECUTION.read_text().casefold().split()),
            "run-safety.md": " ".join(RUN_SAFETY.read_text().casefold().split()),
        }
        skill = documents["SKILL.md"]
        self.assertIn("freeze/remove/persist lifecycle", skill)
        self.assertIn("only after this search returns nonzero trials", skill)
        self.assertIn("only that current-run document", skill)
        for name in ("sdk-execution.md", "run-safety.md"):
            text = documents[name]
            with self.subTest(document=name):
                self.assertTrue(
                    "returned trials" in text or "returns nonzero trials" in text
                )
                self.assertTrue(
                    any(
                        phrase in text
                        for phrase in (
                            "remove any earlier document",
                            "deletes it before each search",
                            "unlink",
                        )
                    ),
                    f"{name} must remove stale evidence before a search",
                )
        self.assertNotIn(
            "serialize it to `traigent-runs/config-space.json`",
            skill,
            "SKILL.md must not instruct producing the file before the search",
        )

    def test_template_agent_type_names_a_catalog_the_scorer_recognizes(self) -> None:
        """An unrecognized `AGENT_TYPE` is not caught by anything else.

        The scorer accepts any string, and an unrecognized one leaves coverage
        unmeasured - which, because the pillar renormalizes over what it
        measured, *raises* the score by about 9 points while lowering its
        confidence. Mutating this constant to `"bogus_type"` passed every other
        semantic test in this file, because the producer test only compares the
        document's field to the constant that produced it.
        """
        namespace = self._template_producer_namespace()
        self.assertIn(
            namespace["AGENT_TYPE"],
            READINESS.HIGH_IMPACT_KNOBS,
            "AGENT_TYPE must name a catalog the scorer has, or the walkthrough's "
            "own document scores its coverage as unmeasured",
        )
        pillar, _ = score_config_space(
            namespace["config_space_document"](namespace["ENHANCED_SPACE"])
        )
        self.assertEqual(
            pillar.confidence,
            1.0,
            "every agent sub-score must be measured for the template's own document",
        )

    def test_every_wired_knob_actually_changes_the_agent_request(self) -> None:
        """`wired` is an author claim the scorer cannot verify - so verify it here.

        `agent_facts_from_config_space` reads the document, never the agent
        code, so listing a knob `call_agent` ignores inflates the agent pillar
        with a dimension the search cannot move. Making `prompt_style` a no-op
        (`style="direct"` instead of `style=config["prompt_style"]`) passes
        every other test in this file while the document still claims the knob
        is wired. This runs the template's own `call_agent` against a recording
        stub and fails when a wired knob leaves the request identical.

        It also pins `call_agent` to `build_request`: the fence's load-time
        assert probes `build_request`, so a `call_agent` that re-inlined its own
        request would leave that assert guarding dead code.
        """
        code = re.findall(
            r"```python\n(.*?)\n```", SDK_EXECUTION.read_text(), re.DOTALL
        )
        module = ast.parse(code[0])
        wanted_assignments = {"BASELINE_CONFIG", "BASELINE_SPACE", "ENHANCED_SPACE"}
        selected = [
            node
            for node in module.body
            if (
                isinstance(node, ast.FunctionDef)
                and node.name in {"build_prompt", "build_request", "call_agent"}
            )
            or (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id in wanted_assignments
                    for target in node.targets
                )
            )
        ]
        self.assertEqual(
            len(selected), 6, "the template no longer defines the knobs it wires"
        )

        requests: list[dict] = []

        class _Stub:
            @staticmethod
            def completion(**kwargs):
                requests.append(kwargs)
                message = SimpleNamespace(content="answer")
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        namespace = {
            "litellm": _Stub,
            "provider_reported_cost": lambda response: 0.0,
            "require_nonzero_token_usage": lambda response: None,
            "MODEL_REQUEST_TIMEOUT_SECONDS": 120.0,
            "SELECTED_CURRENT_MODEL": "provider/current",
            "SELECTED_ALTERNATIVE_MODEL": "provider/alternative",
            "SELECTED_STRONG_MODEL": "provider/strong",
            "STRONG_REASONING_EFFORT": None,
        }
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])),
                "<sdk-call-agent>",
                "exec",
            ),
            namespace,
        )

        space = namespace["ENHANCED_SPACE"]
        base = dict(namespace["BASELINE_CONFIG"])
        wired = json.loads(
            re.search(r"^WIRED_KNOBS = (\[[^\]]*\])", code[0], re.MULTILINE).group(1)
        )
        namespace["call_agent"]("task", base)
        baseline_request = requests[-1]
        for knob in wired:
            with self.subTest(knob=knob):
                self.assertIn(
                    knob,
                    space,
                    f"'{knob}' is wired but is not a dimension of the space",
                )
                alternatives = [value for value in space[knob] if value != base[knob]]
                self.assertTrue(alternatives, f"'{knob}' has no second value to test")
                namespace["call_agent"]("task", dict(base, **{knob: alternatives[0]}))
                self.assertNotEqual(
                    requests[-1],
                    baseline_request,
                    f"'{knob}' is listed under WIRED_KNOBS but changing it leaves "
                    "the agent request identical - the config-space document "
                    "would claim a search dimension the agent ignores",
                )

        # `call_agent` must route through `build_request`, not re-inline the
        # request: everything the fence asserts at load time is a claim about
        # `build_request`, and an inlined `call_agent` would drift past it.
        namespace["build_request"] = lambda message, config: {"probe": "sentinel"}
        namespace["call_agent"]("task", base)
        self.assertEqual(
            requests[-1],
            {"probe": "sentinel"},
            "call_agent must build its request with build_request, or the "
            "fence's wiring assert guards code the agent no longer calls",
        )

    def _wiring_probe_namespace(self, **overrides) -> dict:
        """Execute the fence's wiring probe with pieces of it swapped out."""
        code = re.findall(
            r"```python\n(.*?)\n```", SDK_EXECUTION.read_text(), re.DOTALL
        )[0]
        module = ast.parse(code)
        wanted_assignments = {
            "BASELINE_CONFIG",
            "BASELINE_SPACE",
            "ENHANCED_SPACE",
            "WIRED_KNOBS",
            "PROBE_INPUTS",
            "WIRED_OUTSIDE_THE_REQUEST",
        }
        selected = [
            node
            for node in module.body
            if (
                isinstance(node, ast.FunctionDef)
                and node.name in {"build_prompt", "build_request", "probe_wiring"}
            )
            or (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id in wanted_assignments
                    for target in node.targets
                )
            )
            or (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id in wanted_assignments
            )
        ]
        namespace = {
            "MODEL_REQUEST_TIMEOUT_SECONDS": 120.0,
            "SELECTED_CURRENT_MODEL": "provider/current",
            "SELECTED_ALTERNATIVE_MODEL": "provider/alternative",
            "SELECTED_STRONG_MODEL": "provider/strong",
            "STRONG_REASONING_EFFORT": None,
        }
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])),
                "<sdk-wiring-probe>",
                "exec",
            ),
            namespace,
        )
        namespace.update(overrides)
        return namespace

    def test_the_wiring_assert_catches_a_knob_the_prompt_builder_ignores(self) -> None:
        """Regression-test the guard itself, not merely its presence.

        `probe_wiring` is only worth its assert if it actually goes red. This
        re-executes the fence with `build_prompt` swapped for one that ignores
        `style` - exactly the `style="direct"` no-op the wiring test above was
        written against - and requires `prompt_style` to lose its `visible`
        verdict, leaving the fence's own assert with something to fail on. It
        also pins the escape mapping empty: seeding it with a name would
        silently re-admit the unverified claim the probe exists to expose.
        """
        honest = self._wiring_probe_namespace()
        self.assertEqual(
            honest["WIRED_OUTSIDE_THE_REQUEST"],
            {},
            "the shipped walkthrough wires every knob into the request, so its "
            "escape mapping must stay empty",
        )
        verdicts = honest["probe_wiring"](
            honest["ENHANCED_SPACE"], honest["BASELINE_CONFIG"]
        )
        self.assertEqual(
            sorted(verdicts),
            sorted(honest["WIRED_KNOBS"]),
            "the probe must return a verdict for every wired knob",
        )
        self.assertEqual(
            {knob for knob, verdict in verdicts.items() if verdict == "visible"},
            set(honest["WIRED_KNOBS"]),
            "every knob the shipped template calls wired must be provable "
            "from build_request alone",
        )

        no_op = self._wiring_probe_namespace(
            build_prompt=lambda message, *, style, self_check: message
            + ("\n\ncheck" if self_check else "")
        )
        with_no_op = no_op["probe_wiring"](
            no_op["ENHANCED_SPACE"], no_op["BASELINE_CONFIG"]
        )
        self.assertEqual(
            with_no_op["prompt_style"],
            "invisible",
            "a prompt builder that ignores `style` makes prompt_style a no-op; "
            "probe_wiring must stop vouching for it",
        )
        self.assertEqual(
            with_no_op["self_check"],
            "visible",
            "the probe must still credit the knobs that do reach the request",
        )

    def test_the_probe_reads_every_model_not_only_the_base_configs(self) -> None:
        """A knob one model consumes and another drops is dead for half the space.

        The probe used to build every request from `BASELINE_CONFIG`, so a knob
        the base model consumes came back proven while the *other* models in the
        ladder produced identical requests for every value of it. The search
        then spends trials on a dimension that cannot move two thirds of its
        own space, and the config-space document claims it as a real one.
        """
        namespace = self._wiring_probe_namespace()
        real_build_request = namespace["build_request"]

        def model_dependent(message: str, config: dict) -> dict:
            request = real_build_request(message, config)
            if config["model"] != namespace["BASELINE_CONFIG"]["model"]:
                # This model ignores self_check: same request for either value.
                request["messages"] = [{"role": "user", "content": message}]
            return request

        namespace["build_request"] = model_dependent
        verdicts = namespace["probe_wiring"](
            namespace["ENHANCED_SPACE"], namespace["BASELINE_CONFIG"]
        )
        self.assertEqual(
            verdicts["self_check"],
            "partial",
            "a knob only the base model consumes must not read as proven",
        )
        self.assertEqual(
            verdicts["temperature"],
            "visible",
            "a knob every model consumes must still be proven",
        )

    def test_the_probe_reads_more_than_one_input(self) -> None:
        """A knob that acts on real input only must not block a paying run.

        The probe tested the single literal `"probe"`, so a knob keyed on the
        shape of the input - a `sql_mode` applied when the message starts
        `SQL:` - produced identical requests, landed in UNPROVEN_WIRED_KNOBS,
        and failed the module import. That is a legitimate run blocked at
        generation time, so the probe reads several representative inputs and
        the template says to replace them with real ones.
        """
        namespace = self._wiring_probe_namespace()
        self.assertGreater(
            len(namespace["PROBE_INPUTS"]),
            1,
            "one probe string cannot exercise an input-dependent knob",
        )
        real_build_request = namespace["build_request"]
        trigger = namespace["PROBE_INPUTS"][-1]

        def input_dependent(message: str, config: dict) -> dict:
            request = real_build_request(message, config)
            if message == trigger and config["self_check"]:
                request["messages"] = [{"role": "user", "content": "rewritten"}]
            else:
                # Every other input ignores self_check entirely.
                request["messages"] = [{"role": "user", "content": message}]
            return request

        namespace["build_request"] = input_dependent
        verdicts = namespace["probe_wiring"](
            namespace["ENHANCED_SPACE"], namespace["BASELINE_CONFIG"]
        )
        self.assertEqual(
            verdicts["self_check"],
            "visible",
            "a knob that acts only on one of the probed inputs is wired, and "
            "refusing to load is a false refusal that blocks a paid run",
        )

    def _wiring_fence_block(self) -> ast.Module:
        """The load-time fence that judges the probe's verdicts.

        Compiled apart from the definitions it judges so the tests below can
        swap `build_request` or `build_prompt` first and then run the real
        fence over the verdicts that produces.
        """
        code = re.findall(
            r"```python\n(.*?)\n```", SDK_EXECUTION.read_text(), re.DOTALL
        )[0]
        body = ast.parse(code).body
        start = next(
            index
            for index, node in enumerate(body)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "PROBE_VERDICTS"
                for target in node.targets
            )
        )
        end = next(
            index
            for index, node in enumerate(body)
            if index > start
            and isinstance(node, ast.FunctionDef)
            and node.decorator_list
        )
        return ast.fix_missing_locations(
            ast.Module(body=body[start:end], type_ignores=[])
        )

    def test_a_conditional_knob_loads_and_says_which_models_honour_it(self) -> None:
        """`partial` blocked a legitimate run, and only `invisible` should.

        A knob can legitimately affect only the models that support it -
        `reasoning_effort` on a reasoning model is a conditional dimension, not
        an ignored knob - and the fence aborted the import on it, so a valid
        run never started. `WIRED_OUTSIDE_THE_REQUEST` is no honest escape for
        it either: the knob does act inside request construction, which is
        exactly what the probe just saw. It loads and is reported instead, with
        the models that honour it, so the asymmetry reaches the run record. The
        no-op the guard exists to catch - a knob no model and no probed input
        ever moves - still fails the load.
        """
        fence = self._wiring_fence_block()

        conditional = self._wiring_probe_namespace()
        honest_build_request = conditional["build_request"]
        base_model = conditional["BASELINE_CONFIG"]["model"]

        def only_the_base_model_reads_the_prompt(message: str, config: dict) -> dict:
            request = honest_build_request(message, config)
            if config["model"] != base_model:
                # This model takes no prompt-shaping knob at all, the way a
                # reasoning model takes no sampling temperature.
                request["messages"] = [{"role": "user", "content": message}]
            return request

        conditional["build_request"] = only_the_base_model_reads_the_prompt
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            exec(compile(fence, "<sdk-conditional-knob>", "exec"), conditional)

        self.assertEqual(
            {
                knob
                for knob, verdict in conditional["PROBE_VERDICTS"].items()
                if verdict == "partial"
            },
            {"prompt_style", "self_check"},
            "the probe must still see the asymmetry it saw before",
        )
        self.assertEqual(
            conditional["UNPROVEN_WIRED_KNOBS"],
            {},
            "a conditional dimension is information, not a failed load",
        )
        self.assertEqual(
            conditional["CONDITIONAL_WIRED_KNOBS"],
            {"prompt_style": [base_model], "self_check": [base_model]},
            "the load must name the models that honour a conditional knob",
        )
        report = printed.getvalue()
        for expected in ("conditional dimension", "prompt_style", base_model):
            self.assertIn(expected, report)

        dead = self._wiring_probe_namespace(
            build_prompt=lambda message, *, style, self_check: message
            + ("\n\ncheck" if self_check else "")
        )
        with self.assertRaises(AssertionError) as raised:
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(fence, "<sdk-no-op-knob>", "exec"), dead)
        self.assertIn("prompt_style", str(raised.exception))
        self.assertEqual(dead["UNPROVEN_WIRED_KNOBS"], {"prompt_style": "invisible"})

    def test_the_escape_list_cannot_be_a_blanket_waiver(self) -> None:
        """`WIRED_OUTSIDE_THE_REQUEST = list(WIRED_KNOBS)` silenced the guard.

        As a bare list of names, one assignment excused every knob at once
        while still passing every check. As a mapping of knob to where it acts,
        each entry is a reviewable claim: the list spelling no longer type-
        checks, and an entry naming a knob that is not wired, or carrying an
        empty description, fails the fence's own assert.
        """
        text = SDK_EXECUTION.read_text()
        self.assertIn("WIRED_OUTSIDE_THE_REQUEST: dict[str, str] = {}", text)
        namespace = self._wiring_probe_namespace()
        guard = next(
            node
            for node in ast.parse(
                re.findall(r"```python\n(.*?)\n```", text, re.DOTALL)[0]
            ).body
            if isinstance(node, ast.Assert)
            and "WIRED_OUTSIDE_THE_REQUEST" in ast.dump(node.test)
        )
        block = ast.fix_missing_locations(ast.Module(body=[guard], type_ignores=[]))

        for waiver, why in (
            (list(namespace["WIRED_KNOBS"]), "a bare list is a blanket waiver"),
            ({"model": ""}, "an empty description records no claim"),
            ({"not_a_knob": "somewhere"}, "an entry must name a wired knob"),
        ):
            with self.subTest(waiver=waiver):
                scope = dict(namespace, WIRED_OUTSIDE_THE_REQUEST=waiver)
                with self.assertRaises((AssertionError, AttributeError), msg=why):
                    exec(compile(block, "<sdk-wiring-escape>", "exec"), scope)

        scope = dict(
            namespace,
            WIRED_OUTSIDE_THE_REQUEST={"model": "chosen inside the retrieval step"},
        )
        exec(compile(block, "<sdk-wiring-escape>", "exec"), scope)

    def test_the_documented_schema_table_is_read_from_the_declaration(self) -> None:
        """The table and the validator must not be two hand-written artifacts.

        They were, and they drifted: every round of fixes closed a field in the
        code and left the prose describing the shape that had just stopped
        being accepted. The table is now welded to `CONFIG_SPACE_FIELDS` - same
        fields, same order, same declared type and requirement - so a field
        cannot be added, retyped, or removed on one side alone.
        """
        text = RUN_SAFETY.read_text()
        section = text[text.index("### Config-space document") :]
        table = re.search(
            r"^\| Field \| Type \| Required \|.*?\n\|[-| ]+\|\n((?:\|.*\n)+)",
            section,
            re.MULTILINE,
        )
        self.assertIsNotNone(table, "the config-space schema table is gone")
        rows = []
        for line in table.group(1).strip().splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            rows.append((cells[0].strip("`"), cells[1], cells[2]))
        self.assertEqual(
            rows,
            [
                (spec.name, spec.type_label, spec.requirement)
                for spec in READINESS.CONFIG_SPACE_FIELDS
            ],
            "the documented schema table no longer matches CONFIG_SPACE_FIELDS",
        )

    def test_the_documented_schema_refusals_hold_through_the_real_consumer(
        self,
    ) -> None:
        """Prose claims about refusal, checked against the adapter that refuses.

        Each shape below is one the section promises is refused rather than
        scored around. They are run through the real adapter so the promise
        cannot outlive the behaviour.
        """
        base = {"agent_type": "general", "knobs": {"widget": [1, 50]}}
        for description, document in (
            ("a bare scalar knob", {"knobs": {"widget": 5}}),
            ("an empty candidate list", {"knobs": {"widget": []}}),
            ("a container candidate", {"knobs": {"widget": [{"a": 1}]}}),
            ("a non-finite candidate", {"knobs": {"widget": [1, float("inf")]}}),
            (
                "a range with no width",
                dict(base, bounds={"widget": {"low": 3, "high": 3}}),
            ),
            ("an inverted range", dict(base, bounds={"widget": {"low": 5, "high": 1}})),
            ("a phantom wired name", dict(base, wired=["widgets"])),
            ("a fractional trial budget", dict(base, max_trials=1.5)),
            # The section promises every other key is refused by name. It used
            # to promise the opposite - "ignored whole" - and that promise is
            # what let `max_trial` silently delete the trial budget.
            ("a misspelled trial budget", dict(base, max_trial=3)),
            ("a misspelled bounds key", dict(base, bound={"widget": {}})),
            ("an undeclared key", dict(base, seed_policy="whatever")),
        ):
            with self.subTest(shape=description):
                with self.assertRaises(READINESS.ConfigSpaceInputError):
                    READINESS.agent_facts_from_config_space(document)

    def test_config_space_producer_and_consumer_are_both_instructed(self) -> None:
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())

        self.assertIn("traigent-runs/config-space.json", skill)
        self.assertIn("--config-space", skill)
        # the producer instruction has to land in the run stage, not only in the
        # closing recap - otherwise there is nothing for the closing score to read
        self.assertLess(
            skill.index("traigent-runs/config-space.json"),
            skill.index("close the loop on the readiness score the run opened with"),
        )
        self.assertIn("### config-space document", safety)
        self.assertIn("only the controls the agent call really consumes", safety)


class GuidanceDoesNotContradictItselfTests(unittest.TestCase):
    """Catch the failure this repo actually produces: two rules that disagree.

    Every other test here pins WORDING - that a phrase is present, that one
    passage precedes another. Those catch drift and reflows, and they caught
    none of the four contradictions found in this package's own history: the key
    was required both before and after the first result (#77), an absent `wired`
    meant both "nothing" and "all of them" (#78), the intent gate was triggered
    by presence in one file and by quality in another (#61), and a closing
    section condemned menus one line above a menu.

    A phrase lock cannot see any of those, because each phrase is individually
    correct. What they share is shape: one decision, described in two places,
    with the descriptions disagreeing. These tests encode that shape - each
    entry names a decision, the phrases that assert one answer, and the phrases
    that assert the opposite. Both sides appearing is the failure.

    Adding a rule here is cheap and adding a contradiction is not, so this is
    where a new load-bearing decision should be recorded.
    """

    def guidance(self) -> dict[str, str]:
        """Every assistant-facing document, whitespace-normalised.

        GUIDE.md and the run-plan template belong here and were missing. GUIDE.md
        is the entry point - the first thing a cloned run reads - so a
        contradiction between it and SKILL.md was invisible to every check built
        on this helper, and one of the four contradictions in this package's
        history (#16) was in GUIDE.md itself.

        The omission also understated the budget below by 8 KB, which is the
        difference between passing and failing it: the check reported 206 KB
        against a 210 KB ceiling while the assistant was actually loading 213.
        A gate that measures the wrong corpus reports the wrong verdict, and it
        reports it in the reassuring direction.
        """
        documents = {
            path.name: path.read_text() for path in assistant_facing_documents()
        }
        return {
            name: " ".join(text.casefold().split()) for name, text in documents.items()
        }

    def conversation(self) -> dict[str, str]:
        """Public promises plus every assistant-facing instruction."""
        documents = {
            path.name: path.read_text() for path in conversation_contract_documents()
        }
        return {
            name: " ".join(text.casefold().split()) for name, text in documents.items()
        }

    # (decision, phrases asserting one answer, phrases asserting the opposite)
    CONTRADICTIONS = (
        (
            "when the Traigent key is required",
            ("only after that checkpoint, ask for the traigent key",),
            (
                "ask the user to enter both keys locally",
                "before the first paid trial, run a zero-llm portal-tracking probe",
                "keys they already hold",
                "both local secret pastes",
                "provide only the required account/key destination",
                "blank selected-provider and traigent key entries",
                "two keys go into your local .env",
            ),
        ),
        (
            "whether both default measurements are connected",
            ("two measurements",),
            (
                "two connected optimization experiments",
                "exactly two connected optimization experiments",
            ),
        ),
        (
            "whether a user-owned baseline receives the generated model ladder",
            (
                "the three-tier ladder applies only when this walkthrough supplies a missing baseline",
            ),
            (
                "the ladder adds the tiers below it",
                "add the cheaper ladder tiers below it",
            ),
        ),
        (
            "whether a synchronous run promises a 30-minute pause",
            ("never promise a pause at minute 30",),
            ("reaching that ceiling is a decision point",),
        ),
        (
            "what an absent `wired` list attests",
            ('treats that as nothing-to-search rather than as "all of them"',),
            (
                "omitted or empty means every declared knob counts as wired",
                'an absent `wired` means "every declared knob is wired"',
            ),
        ),
        (
            "what anchors task intent",
            ("finds no agent *that performs an identifiable task*",),
            ("when the read-only inventory finds no agent, dataset,",),
        ),
        (
            "whether the readiness score is taken on the run's subset",
            ("score the dataset, not the subset",),
            ("select before preflight, not after",),
        ),
        (
            "who creates temporary walkthrough components",
            ("temporary walkthrough substitute created by the coding assistant",),
            (
                "temporary walkthrough substitute created by traigent",
                "traigent will create the coherent walkthrough substitutes",
                "state what traigent will create for the walkthrough",
                "if traigent generates temporary components",
                "traigent generated an agent for this walkthrough",
            ),
        ),
        (
            "whether historical config-space evidence enters readiness",
            ("historical context, not current-run readiness evidence",),
            (
                "plus any calibration or config-space evidence already present",
                "plus the calibration results and config-space document, whichever exist by this point",
                "plus the calibration results and config-space document, whichever exist",
                "supply whichever preflight, calibration, and config-space evidence exists",
            ),
        ),
        (
            "which interpreter runs the unambiguous opening gate",
            (
                "if there is exactly one compatible python 3.11-3.13 isolated-environment candidate overall and its resolved path is inside the user's project root",
            ),
            (
                "use the host `python3` interpreter as a narrow bootstrap for every bundled script",
                "uses the host `python3` interpreter as a narrow bootstrap for every bundled script",
            ),
        ),
        (
            "whether a non-git project receives a .gitignore",
            ("otherwise do not create `.gitignore`",),
            (
                "add that directory to the project `.gitignore`",
                "create `traigent-runs/` artifacts and add that path to `.gitignore`",
            ),
        ),
        (
            "the enhanced-run trial-count upper bound",
            ("up to 12 configurations",),
            (
                # #123: four documents stated "10-13" trials with "a cap of
                # 12" - twelve is less than thirteen, so as written either
                # the cap was not 12 or 13 never occurred. `max_trials` is
                # passed straight through to the SDK as the search's upper
                # bound (sdk-execution.md), so the cap really does bound
                # visible rows at 12.
                "10-13 trials",
                "10-13-trial",
                "10-13 visible trials",
                "10-13 visible enhanced rows",
                # The follow-up decision on #123: 10-12 was arithmetically
                # right and still the wrong shape to say out loud. At approval
                # time the user is asking what the worst case is, which a
                # ceiling answers and a range makes vague, and 10 was never a
                # promise to them - it is the assistant's own honesty check on
                # a short run, which sdk-execution.md keeps. So the range
                # itself is banned wherever it could be spoken, in either the
                # trial or the configuration noun.
                "10-12 trials",
                "10-12-trial",
                "10-12 visible trials",
                "10-12 visible enhanced rows",
                "10-12 configurations",
            ),
        ),
        (
            "whether a file no row could be read from is a defect in the data",
            # This one was a contradiction inside a single pull request, across
            # the two documents CLAUDE.md warns about by name. #144 added a
            # worked example to the dataset reference whose punchline is "the
            # rows are fine and the field selection is not", and in the same
            # commit added a SKILL.md branch calling the identical state
            # "broken data" and routing it to repair - each correct-looking on
            # its own, opposite when read together.
            #
            # Settled by execution: every situation that produces the state was
            # built and run through preflight and readiness. A `question` /
            # `answer` file, a nested schema, a CSV, a JSON array and YAML all
            # reach it with the rows intact, and re-reading the same bytes with
            # the fields the file uses scores them with no dataset cap at all.
            # So the score names its own reading, and whether the data is at
            # fault is established after the file is opened, not before.
            ("which is not a verdict on the data",),
            (
                "broken data, not missing data",
                "treat it as invalid; repair a working copy from the",
                "none of its rows could be read",
            ),
            # The reject list said the helper rejects a swallowed exception;
            # twenty lines below, the advisory paragraph says it never changes
            # PASS - and the helper agrees with the second: a scorer with
            # `except Exception: return 0.0` returns `"passed": true`, exit 0.
            "whether a swallowed evaluator exception fails calibration",
            ("nothing enforces this one",),
            ("an ordinary zero. for deterministic calibration",),
        ),
        (
            # Binary partial is held to `--bad-maximum`, not to "not passing":
            # a partial at 0.50 is below the passing score and still exits 1.
            "what a binary partial probe has to score",
            ("partial output above `--bad-maximum`",),
            ("in `binary` mode, partial output receiving a passing score",),
        ),
    )

    def test_no_decision_is_described_two_opposite_ways(self) -> None:
        joined = " ".join(self.conversation().values())
        for decision, agreed, contradicting in self.CONTRADICTIONS:
            with self.subTest(decision=decision):
                self.assertTrue(
                    any(phrase in joined for phrase in agreed),
                    f"the settled answer for '{decision}' is no longer stated - "
                    "if the decision changed, update this table with the new "
                    "answer rather than deleting the check",
                )
                for phrase in contradicting:
                    self.assertNotIn(
                        phrase,
                        joined,
                        f"'{decision}' is described two opposite ways; this "
                        "wording was settled and reintroducing it puts the "
                        "guidance back in conflict",
                    )

    # A value the guidance states in more than one document, and the pattern
    # that finds it. Anchored on the CONCEPT, never on the shape of the value:
    # a bare `\$(\d+\.\d{2})` also matches the "$0.00" in a sentence about
    # reporting cost as unmeasured, which is a different fact entirely and was
    # the first false positive this table produced.
    #
    # This is the half the CONTRADICTIONS registry above cannot do. That one
    # catches the reintroduction of a contradiction someone already found and
    # wrote down; it is silent on a value that drifts tomorrow in a document
    # nobody has read since. This one needs no foreknowledge: it fails whenever
    # two documents disagree about the same number, including one added later.
    SHARED_VALUES = (
        ("supported Python range", r"Python (3\.\d+\s*-\s*3\.\d+)"),
        ("the .env file mode", r"mode `(0[0-7]{3})`"),
        (
            "the total walkthrough ceiling",
            r"(?:ceiling|walkthrough)[^.]{0,40}?\$(\d+\.\d{2})",
        ),
        # The enhanced run's ceiling, matched as the ceiling phrase the user
        # reads rather than as a range: the range shape it used to have is now
        # banned outright in CONTRADICTIONS above, so a pattern anchored on
        # `\d+-\d+` would match nothing and quietly stop checking anything.
        ("the enhanced-run configuration ceiling", r"up to (\d+) configurations"),
        ("the generated baseline size", r"(\w+)-row baseline"),
    )

    def test_a_shared_value_is_not_stated_two_ways(self) -> None:
        """Two documents may repeat a number; they may not disagree about it.

        Every instance in this package's history was found by a human reading
        the whole guide. This finds the numeric subclass mechanically, which is
        the subclass that grows fastest: each new reference file is another
        place for the spend ceiling or the supported interpreter range to be
        restated slightly differently.
        """
        documents = self.guidance()
        for label, pattern in self.SHARED_VALUES:
            with self.subTest(value=label):
                stated = {
                    name: {
                        match.casefold()
                        for match in re.findall(pattern, text, re.IGNORECASE)
                    }
                    for name, text in documents.items()
                    if re.search(pattern, text, re.IGNORECASE)
                }
                # A single-sourced value cannot drift between documents, so an
                # entry that finds one is not checking anything - it reads as
                # coverage while providing none.
                self.assertGreater(
                    len(stated),
                    1,
                    f"'{label}' is now stated in {sorted(stated) or 'no document'} - "
                    "if it moved to a single home, delete this entry rather than "
                    "leaving a check that cannot fail",
                )
                values = set().union(*stated.values())
                self.assertEqual(
                    len(values),
                    1,
                    f"'{label}' is stated as {sorted(values)} across "
                    f"{sorted(stated)}. Two documents give the assistant "
                    "different numbers for one decision, and it will follow "
                    "whichever it read last.",
                )

    # A command the guidance states in more than one document, matched as the
    # literal invocation rather than a captured number. #124's class: the
    # .env tracked-file safety check was written out in full identically in
    # SKILL.md and run-safety.md, so nothing was drifted YET - but nothing
    # stopped an edit to one copy leaving the other stale, and the failure
    # mode of a stale copy here is a committed secret. SHARED_VALUES above
    # only ever anchors on a captured number; a command has no number to
    # anchor on, so it needs its own table, checked the same way: more than
    # one document must state it, and every document that does must state it
    # identically.
    SHARED_COMMANDS = (
        (
            "the forbidden unversioned Traigent install command",
            r"`(pip install[^`]*traigent[^`]*)`",
        ),
    )

    def test_a_shared_command_is_not_stated_two_ways(self) -> None:
        """Two documents may repeat a command; they may not diverge on it.

        #124 found the .env git-tracked-file check written out in full in
        both SKILL.md and run-safety.md - byte-identical at the time, so a
        phrase lock would have passed right up until someone fixed the
        exit-code handling in one copy and not the other, and the failure
        mode of that stale copy is a leaked secret. This is that class of
        defect, generalized: it fails whenever two documents give the
        assistant two different commands for what is supposed to be one
        check, including a divergence introduced after this test was
        written, the same way the numeric SHARED_VALUES check above needs no
        foreknowledge of which number will drift next.
        """
        documents = self.guidance()
        for label, pattern in self.SHARED_COMMANDS:
            with self.subTest(value=label):
                stated = {
                    name: {match.casefold() for match in re.findall(pattern, text)}
                    for name, text in documents.items()
                    if re.search(pattern, text)
                }
                # A single-sourced command cannot drift between documents, so
                # an entry that finds only one is not checking anything - it
                # reads as coverage while providing none.
                self.assertGreater(
                    len(stated),
                    1,
                    f"'{label}' is now stated in {sorted(stated) or 'no document'} - "
                    "if it moved to a single home, delete this entry rather than "
                    "leaving a check that cannot fail",
                )
                values = set().union(*stated.values())
                self.assertEqual(
                    len(values),
                    1,
                    f"'{label}' is written as {sorted(values)} across "
                    f"{sorted(stated)}. Two documents give the assistant "
                    "different commands for one check, and a stale copy "
                    "here is a silent security failure, not a cosmetic one.",
                )

    # Flags the guidance names that belong to something other than a bundled
    # script. `--all` is the SDK's own push flag, mentioned only to forbid it.
    # `--list` and `--skill` belong to `npx skills add`, which the close hands
    # the user so they can continue on their own; both are documented in
    # Traigent/traigent-skills, and the check that they exist there is
    # test_the_handoff_names_real_skills_and_only_hypotheses.
    EXTERNAL_FLAGS = frozenset({"--all", "--list", "--skill"})

    def test_the_guidance_names_no_flag_that_does_not_exist(self) -> None:
        """#62's class: an instruction that cannot be followed as written.

        The guide told the assistant twice to run preflight with "the combined
        dataset argument", which the tool has never had. A phrase lock cannot
        see that - the phrase was consistent, and consistently wrong. Reading
        the flags out of the scripts is what makes the check independent of
        whoever wrote the sentence.
        """
        defined: set[str] = set()
        for script in sorted((SKILL_ROOT / "scripts").glob("*.py")):
            tree = ast.parse(script.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "attr", "") == "add_argument"
                ):
                    for argument in node.args:
                        if isinstance(argument, ast.Constant) and str(
                            argument.value
                        ).startswith("--"):
                            defined.add(argument.value)
        self.assertTrue(defined, "found no flags to check against")

        mentioned: set[str] = set()
        for text in self.guidance().values():
            mentioned |= set(re.findall(r"`(--[a-z0-9][a-z0-9-]*)`", text))
        self.assertTrue(mentioned, "found no flag mentions to check")

        self.assertEqual(
            sorted(mentioned - defined - self.EXTERNAL_FLAGS),
            [],
            "the guidance names a flag no bundled script defines; an assistant "
            "following that instruction has to guess what was meant",
        )
        # The allowlist is the escape hatch, so it gets the same treatment as
        # the rule: an entry nothing mentions any more is removed, not left to
        # quietly widen what the check permits.
        self.assertEqual(
            sorted(self.EXTERNAL_FLAGS - mentioned),
            [],
            "an allowlisted external flag is no longer mentioned anywhere",
        )

    def test_a_budget_raise_carries_its_reason(self) -> None:
        """The committed ledger obeys the rules the mechanism enforces.

        Two things are checked, and they are different. CLAUDE.md has said
        since #104 that raising a ceiling "is a decision: change the number
        where it is defined, with the reason, in the same commit"; nothing
        enforced the second half, so a bare number passed. The number, the
        figure it was measured against, and the reason are now one file, and
        an entry missing any of the three fails.

        The second is what the ledger records five times: two branches each
        raise correctly for their own increment, and the merged package
        exceeds both. Every entry states the entry it was measured on top of,
        so two concurrent raises both honestly say `follows: 0001`, and the
        merge - which produces no textual conflict at all - fails because two
        entries may not follow the same one. A branch can only point at an
        entry it actually has, so renumbering around the collision does not
        help: an entry that claims to follow one its own tree lacks fails on
        that branch, before any merge.

        What this does not do: it detects that two raises were measured on the
        same state, not that any figure is correct. Nothing here re-measures
        the package on the author's behalf, and an author who re-points an
        entry and rewrites its figures to any larger pair of numbers is
        believed. The monotonicity check catches only the re-point whose
        stated figure is below the one it now follows - the un-remeasured
        case - and says nothing about a figure that is merely wrong. What
        keeps the whole thing honest is the ceiling check below, which
        measures the package for real.

        The rules themselves are exercised against invented ledgers in
        `GuidanceBudgetLedgerRulesTests`; this test is the committed ledger.
        """
        entries = guidance_budget_entries()
        self.assertTrue(entries, "the guidance budget ledger is empty")
        self.assertEqual(
            guidance_budget_defects(entries),
            [],
            "the committed guidance budget ledger breaks its own rules",
        )

        self.assertEqual(
            sorted(guidance_budget_ceilings()),
            ["resident", "total"],
            "the ledger no longer declares both ceilings, so one of the two "
            "budgets is unenforced",
        )

    def test_the_guidance_budget_is_not_silently_exceeded(self) -> None:
        """Size is a contradiction surface, so it gets a number and a ceiling.

        Nothing here is duplicated - measured at nine repeated sentences across
        every document - so this is genuine content, and the honest control is a
        budget rather than a de-duplication pass.

        Two numbers, because this package is progressively disclosed and one
        number described it wrongly. SKILL.md says "Load each reference when its
        stage begins", and sdk-execution.md is "only before writing the
        wrapper" - so the claim that once stood here, that the assistant loads
        all of it before reading a line of the user's project, was false about
        the design it was guarding. It is the shape of contradiction these tests
        exist to catch, inside the test that counts them.

        RESIDENT is what cannot leave: the entry documents and the flow. It is
        in context from the first turn to the last, so every rule in it competes
        with the user's project for attention the whole way, and it is the
        number that governs drift.

        TOTAL is the worst case - a run that reaches every stage, which a full
        guided run does. It bounds how much guidance can accumulate behind the
        mandates before the late, expensive stages, which is where an
        instruction quietly stops being followed.

        Neither number is here. Both live in `tests/guidance_budget/`, one file
        per raise, with the reason for that raise in the same file - because a
        ceiling that is edited by every branch is a ceiling every branch
        conflicts on, and the reasons were never what disagreed.
        """
        document_bytes = {
            path: len(path.read_bytes()) for path in assistant_facing_documents()
        }
        # Resident = read up front and never dropped. The references are loaded
        # per stage and can leave; these cannot.
        resident = sum(
            size
            for path, size in document_bytes.items()
            if path in {ROOT / "GUIDE.md", SKILL}
        )
        ceilings = guidance_budget_ceilings()
        self.assertLess(
            resident,
            ceilings["resident"],
            f"resident guidance is {resident} bytes against a "
            f"{ceilings['resident']} ceiling - the part in context for the "
            "whole run, competing with the user's project from the first turn. "
            "Stage detail belongs in the reference for that stage, which the "
            "run can load and leave. If it genuinely has to rise, add an entry "
            "to tests/guidance_budget/ with the measured number and the "
            "reason - and measure this merge, do not take a branch's figure.",
        )
        # Count the actual UTF-8 files, not Unicode code points or a
        # whitespace-normalized proxy. The ceiling in #104 is a byte ceiling.
        total = sum(document_bytes.values())
        budget = ceilings["total"]
        self.assertLess(
            total,
            budget,
            f"assistant-facing guidance is {total} bytes against a {budget} "
            "budget. Every rule added is also a surface for two rules to "
            "disagree on. Prune scope, or raise the ceiling deliberately: add "
            "an entry to tests/guidance_budget/ stating the measured total and "
            "why the addition earns it. If two branches just merged, this is "
            f"the arithmetic neither could do alone - {total} is the number "
            "that matters, not either side's.",
        )


class GuidanceBudgetLedgerRulesTests(unittest.TestCase):
    """The ledger rules, run against invented ledgers rather than the real one.

    Checking the rules against `tests/guidance_budget/` alone would only ever
    prove that the committed ledger is currently well-formed. Every rule here
    is exercised by writing the ledger that breaks it into a temporary
    directory, so each check is proven by the case it must refuse.
    """

    REASON = (
        "Branch A adds the degraded form of the enhanced-run card to "
        "run-safety.md: the sentence the assistant says when the combination "
        "count cannot be computed, so the card states the ceiling on its own "
        "instead of estimating a total it does not have. That is new contract "
        "surface with no prior statement, and it replaces nothing."
    )

    def ledger(self, **files: str) -> list[SimpleNamespace]:
        """Write an invented ledger to a temporary directory and read it back."""
        directory = Path(tempfile.mkdtemp(prefix="guidance-budget-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        for name, body in files.items():
            (directory / name).write_text(body, encoding="utf-8")
        return guidance_budget_entries(directory)

    # One genuinely different reason per invented entry, because the rules now
    # include "not substantially another entry's reason" and a fixture whose
    # entries all share one text would trip it. They are written about different
    # raises on purpose: they share this package's vocabulary heavily -
    # "measured", "ceiling", "run-safety.md", "merged package" - and
    # `test_a_reason_copied_from_another_entry_is_refused` is what proves the
    # threshold still lets that through.
    REASONS = (
        "Branch A adds the degraded form of the enhanced-run card to "
        "run-safety.md: the sentence the assistant says when the combination "
        "count cannot be computed, so the card states the ceiling on its own "
        "instead of estimating a total it does not have. That is new contract "
        "surface with no prior statement, and it replaces nothing.",
        "The evaluator-calibration probe grows a fourth case: a scorer that "
        "returns a tuple. Every earlier case covered a float, so the guidance "
        "described a shape the installed SDK does not always hand back, and an "
        "author following it wired an adapter that silently dropped the second "
        "element. The new text lives beside the three it joins.",
        "Readiness gains a plain-language line for the wired-knob shortfall, "
        "which until now printed a condition slug and nothing a first-time "
        "reader could act on. It goes in glossary.md, next to the other terms a "
        "user meets on the card, rather than in the ordered flow - so this buys "
        "vocabulary, not another mandate in the resident documents.",
        "The post-run close now states which of the user's own files were "
        "written and which were left untouched, in the reference that already "
        "owns the handoff. Two support conversations turned on somebody "
        "believing their dataset had been edited; naming the artefacts costs "
        "four sentences and removes the doubt entirely.",
        "Provenance for a generated held-out row is spelled out where the split "
        "is described instead of being implied by an example. A synthesised row "
        "cannot show that a winner generalises to real inputs, and the previous "
        "wording left a reader free to quote it as if it could. Longer, and it "
        "replaces a sentence that was wrong.",
        "Timeouts are bounded by a derivation rather than by a constant, so the "
        "text has to show the derivation. It lands in sdk-execution.md beside "
        "the call it bounds; the resident flow keeps only the decision. What "
        "grows is the reference, which a run loads once and leaves, not the "
        "part in context from the first turn.",
    )

    def entry(
        self,
        title: str,
        *,
        follows: int | None = None,
        reason: str | None = None,
        **figures: int,
    ) -> str:
        lines = [f"# {title}", ""]
        if follows is not None:
            lines.append(f"follows: {follows:04d}")
        lines += [
            f"{name.replace('_', '-')}: {value}" for name, value in figures.items()
        ]
        lines += ["", reason if reason is not None else self.reason_for(title), ""]
        return "\n".join(lines)

    def reason_for(self, title: str) -> str:
        """A distinct reason per title, stable within one test."""
        assigned = getattr(self, "_assigned_reasons", None)
        if assigned is None:
            assigned = self._assigned_reasons = {}
        if title not in assigned:
            self.assertLess(
                len(assigned),
                len(self.REASONS),
                "this fixture needs more distinct reasons than REASONS holds",
            )
            assigned[title] = self.REASONS[len(assigned)]
        return assigned[title]

    def root(self) -> str:
        return self.entry(
            "0001 - the ledger this mechanism inherited",
            resident_ceiling=61_500,
            resident_measured=61_129,
            total_ceiling=228_750,
            total_measured=228_407,
        )

    def assertDefect(self, entries: list[SimpleNamespace], fragment: str) -> None:
        defects = guidance_budget_defects(entries)
        self.assertTrue(defects, "the ledger was accepted; expected a defect")
        self.assertTrue(
            any(fragment in defect for defect in defects),
            f"no defect mentioned {fragment!r}; got {defects}",
        )

    def test_a_sequential_chain_of_raises_is_accepted(self) -> None:
        """The shape the mechanism is asking for has to actually pass.

        Reversal: this is the control for every refusal below. If it failed,
        the rules would be refusing the correct ledger too, and every other
        test in this class would prove nothing.
        """
        entries = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "0002-branch-a.md": self.entry(
                    "0002 - branch A",
                    follows=1,
                    total_ceiling=232_000,
                    total_measured=231_402,
                ),
                "0003-branch-b.md": self.entry(
                    "0003 - branch B",
                    follows=2,
                    total_ceiling=240_000,
                    total_measured=239_118,
                ),
            }
        )
        self.assertEqual(guidance_budget_defects(entries), [])
        self.assertEqual(
            [entry.path.name for entry in guidance_budget_chain(entries)],
            ["0001-inherited-ledger.md", "0002-branch-a.md", "0003-branch-b.md"],
        )
        self.assertEqual(
            guidance_budget_ceilings(entries),
            {"resident": 61_500, "total": 240_000},
        )

    def test_two_entries_measured_on_the_same_state_are_refused(self) -> None:
        """The mistake the ledger records five times, caught at the merge.

        Two branches each add an entry, each honestly measured on top of 0001.
        They take different numbers - the polite thing to do when you can see
        the other pull request - so nothing collides: no textual conflict, no
        duplicate number. Before `follows:` this merged green, and the higher
        number's ceiling silently governed a package neither branch measured.
        """
        entries = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "0002-branch-a.md": self.entry(
                    "0002 - branch A",
                    follows=1,
                    total_ceiling=232_000,
                    total_measured=231_402,
                ),
                "0003-branch-b.md": self.entry(
                    "0003 - branch B",
                    follows=1,
                    total_ceiling=240_000,
                    total_measured=239_118,
                ),
            }
        )
        # Neither of the two older checks sees this: the numbers differ, and
        # both entries carry a ceiling and a reason.
        self.assertEqual(
            sorted(entry.index for entry in entries), [1, 2, 3], "no duplicate number"
        )
        self.assertDefect(entries, "all follow 0001")
        # The message has to hand over the fix, not only the refusal.
        self.assertDefect(entries, "Measure the merged package")
        self.assertDefect(entries, "re-point the later entry at the earlier one")

    def test_an_entry_cannot_follow_one_that_is_not_in_the_tree(self) -> None:
        """Renumbering around the collision is what the pointer refuses.

        The second author renumbers 0002 to 0003 and writes `follows: 0002` to
        make the chain look sequential. On that author's own branch 0002 does
        not exist, so their own suite is red before the merge - which is the
        whole point of grounding the pointer in the tree rather than in the
        number.
        """
        entries = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "0003-branch-b.md": self.entry(
                    "0003 - branch B",
                    follows=2,
                    total_ceiling=240_000,
                    total_measured=239_118,
                ),
            }
        )
        self.assertDefect(entries, "follows 0002, which is not in this tree")

    def test_an_entry_is_measured_on_top_of_exactly_one_state(self) -> None:
        """Two follows: lines would let an entry claim both sides of a merge."""
        body = self.entry(
            "0003 - branch B",
            follows=1,
            total_ceiling=240_000,
            total_measured=239_118,
        ).replace("follows: 0001", "follows: 0001\nfollows: 0002")
        entries = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "0002-branch-a.md": self.entry(
                    "0002 - branch A",
                    follows=1,
                    total_ceiling=232_000,
                    total_measured=231_402,
                ),
                "0003-branch-b.md": body,
            }
        )
        self.assertDefect(entries, "declares follows: more than once")

    def test_an_entry_may_not_follow_a_higher_number(self) -> None:
        """The chain runs one way, so the ceiling in force is not a cycle."""
        entries = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "0002-branch-a.md": self.entry(
                    "0002 - branch A",
                    follows=3,
                    total_ceiling=232_000,
                    total_measured=231_402,
                ),
                "0003-branch-b.md": self.entry(
                    "0003 - branch B",
                    follows=1,
                    total_ceiling=240_000,
                    total_measured=239_118,
                ),
            }
        )
        self.assertDefect(entries, "which is not lower than its own number")

    def test_the_ledger_has_exactly_one_root(self) -> None:
        """Two entries that follow nothing are two ledgers in one directory."""
        two_roots = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "0002-branch-a.md": self.entry(
                    "0002 - branch A", total_ceiling=232_000, total_measured=231_402
                ),
            }
        )
        self.assertDefect(two_roots, "2 entries that declare no follows:")

        no_root = self.ledger(
            **{
                "0001-inherited-ledger.md": self.entry(
                    "0001 - root",
                    follows=1,
                    total_ceiling=228_750,
                    total_measured=228_407,
                ),
            }
        )
        self.assertDefect(no_root, "which is not lower than its own number")

    def test_a_re_point_that_never_re_measured_is_refused(self) -> None:
        """The offered fix is only a fix if the figure is taken again.

        Re-pointing 0003 at 0002 makes the chain well-formed. If the author
        does not re-measure, the figure they keep is the one they took on a
        package that did not contain 0002's change - and here it is smaller
        than 0002's own measurement, which cannot be true of a package that
        holds both. This catches exactly that case and not the general one:
        a re-point whose stale figure happens to be the larger of the two is
        believed.
        """
        entries = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "0002-branch-a.md": self.entry(
                    "0002 - branch A",
                    follows=1,
                    total_ceiling=232_000,
                    total_measured=231_402,
                ),
                "0003-branch-b.md": self.entry(
                    "0003 - branch B",
                    follows=2,
                    total_ceiling=232_500,
                    total_measured=229_800,
                ),
            }
        )
        self.assertDefect(entries, "below 0002-branch-a.md's 231402")
        self.assertDefect(entries, "re-measure the merged package")

    def test_a_prune_that_lowers_the_ceiling_may_lower_the_measurement(
        self,
    ) -> None:
        """Monotonicity is about raises; #104 lowered a ceiling after a prune.

        Reversal of the test above: the same falling measurement is accepted
        when the entry lowers the ceiling with it, because that is a prune
        rather than an unmeasured re-point. Without this the mechanism would
        make the one move CLAUDE.md actually prefers - prune instead of
        raise - impossible to record.
        """
        entries = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "0002-branch-a.md": self.entry(
                    "0002 - the #104 migration",
                    follows=1,
                    total_ceiling=220_000,
                    total_measured=209_400,
                ),
            }
        )
        self.assertEqual(guidance_budget_defects(entries), [])

    def test_a_ceiling_needs_the_figure_it_was_measured_against(self) -> None:
        """A ceiling with no measurement leaves the next merge nothing to
        compare against, and a ceiling under its own measurement is breached
        on arrival."""
        unmeasured = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "0002-branch-a.md": self.entry(
                    "0002 - branch A", follows=1, total_ceiling=232_000
                ),
            }
        )
        self.assertDefect(unmeasured, "declares total-ceiling but no total-measured")

        backwards = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "0002-branch-a.md": self.entry(
                    "0002 - branch A",
                    follows=1,
                    total_ceiling=232_000,
                    total_measured=232_400,
                ),
            }
        )
        self.assertDefect(backwards, "a ceiling at or below the measurement")

        # The other way round: a figure with no ceiling attached is a number
        # nobody has to live under, and the next entry would be held monotone
        # against it.
        stray = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "0002-branch-a.md": self.entry(
                    "0002 - branch A",
                    follows=1,
                    resident_ceiling=62_000,
                    resident_measured=61_400,
                    total_measured=231_402,
                ),
            }
        )
        self.assertDefect(stray, "declares total-measured but no total-ceiling")

    def test_an_entry_still_needs_a_number_a_name_and_a_reason(self) -> None:
        """The rules the previous revision had, kept and proven the same way."""
        unnamed = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "branch-a.md": self.entry(
                    "branch A",
                    follows=1,
                    total_ceiling=232_000,
                    total_measured=231_402,
                ),
            }
        )
        self.assertDefect(unnamed, "is not named NNNN-slug.md")

        # `follows:` is what catches two raises measured on one state; the
        # number is still what tells them apart in the order, so two entries
        # cannot share one.
        duplicated = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "0002-branch-a.md": self.entry(
                    "0002 - branch A",
                    follows=1,
                    total_ceiling=232_000,
                    total_measured=231_402,
                ),
                "0002-branch-b.md": self.entry(
                    "0002 - branch B",
                    follows=1,
                    total_ceiling=240_000,
                    total_measured=239_118,
                ),
            }
        )
        self.assertDefect(duplicated, "share the number 0002")

        no_ceiling = self.ledger(
            **{
                "0001-inherited-ledger.md": self.root(),
                "0002-branch-a.md": self.entry("0002 - branch A", follows=1),
            }
        )
        self.assertDefect(no_ceiling, "declares no ceiling")

    def test_the_reason_floor_refuses_padding_and_accepts_a_short_argument(
        self,
    ) -> None:
        """A character count alone is met by one word repeated to length.

        Both inputs are invented rather than taken from the committed ledger,
        because a check calibrated against the text it is checking proves only
        that the text has not changed. The padded string is over the character
        floor and is refused; the short argument is barely over it and is
        accepted, which is what stops the floor from refusing an author who
        made their case in four sentences.
        """
        padded = "padding " * 45
        self.assertGreater(len(padded.strip()), BUDGET_REASON_FLOOR)
        self.assertIsNotNone(guidance_budget_reason_defect(padded))

        short_but_real = (
            "The graduation handoff adds the closing run-scope statement to "
            "run-safety.md, which already owns the close. It replaces nothing "
            "and is new contract surface, so TOTAL rises. The merged package "
            "measures 229_204; the ceiling here is that figure rounded up, "
            "not either branch's own."
        )
        self.assertLess(len(short_but_real), 300)
        self.assertIsNone(guidance_budget_reason_defect(short_but_real))

        # The two floors do different work, so each gets an input the other
        # one lets through. This is under the character floor and well over
        # the distinct-word floor, and it is the entry the ledger exists to
        # refuse: a note about the arithmetic with no argument in it.
        arithmetic_only = (
            "Raised because the merged package grew past its previous ceiling "
            "once both branches landed together, so this number simply records "
            "that arithmetic and says nothing about which addition earns its "
            "bytes."
        )
        self.assertLess(len(arithmetic_only), BUDGET_REASON_FLOOR)
        self.assertGreaterEqual(
            len(set(re.findall(r"[a-z]{2,}", arithmetic_only.casefold()))),
            BUDGET_REASON_DISTINCT_WORDS,
        )
        self.assertIsNotNone(guidance_budget_reason_defect(arithmetic_only))

        self.assertIsNotNone(guidance_budget_reason_defect("Raised for #142."))

    def test_a_reason_copied_from_another_entry_is_refused(self) -> None:
        """The cheapest way over a length floor is to copy something that passed.

        Both floors above measure a reason against itself, so the entry that
        satisfies them at zero cost is the one whose reason is somebody else's.
        That is not a hypothetical: this ledger's root file ships nine written
        reasons, an author who wants a green suite has them open in the next
        tab, and every intrinsic floor - characters, distinct words, any future
        readability score - is passed by a copy by construction.

        The rule is containment in five-word runs, and both directions are
        exercised here. Vocabulary is not the signal: two honest entries about
        this package share "measured", "ceiling", "run-safety.md" and "merged
        package", and a word-overlap score would call that plagiarism.
        """
        # Control first, so the refusals below are the rule working rather than
        # the fixture being malformed: the same two entries, each with its own
        # reason, are accepted.
        root = self.root()
        clean = self.ledger(
            **{
                "0001-inherited-ledger.md": root,
                "0002-branch-a.md": self.entry(
                    "0002 - branch A",
                    follows=1,
                    total_ceiling=232_000,
                    total_measured=231_402,
                ),
            }
        )
        self.assertEqual(guidance_budget_defects(clean), [])

        borrowed = self.ledger(
            **{
                "0001-inherited-ledger.md": root,
                "0002-branch-a.md": self.entry(
                    "0002 - branch A",
                    follows=1,
                    total_ceiling=232_000,
                    total_measured=231_402,
                    # Word for word what 0001 says. Over both intrinsic floors,
                    # and it describes a raise that is not this one.
                    reason=self.reason_for("0001 - the ledger this mechanism inherited"),
                ),
            }
        )
        self.assertDefect(borrowed, "in five-word runs")

        original = self.REASONS[0]
        # Reworded, not rewritten: one verb swapped and the closing sentence
        # replaced. A near-1 threshold would let this through, which is why the
        # boundary is 0.4 and not 0.9.
        reworded = original.replace("adds", "introduces").replace(
            "That is new contract surface with no prior statement, and it "
            "replaces nothing.",
            "This is fresh contract surface.",
        )
        self.assertNotEqual(reworded, original)
        self.assertGreaterEqual(
            guidance_budget_reason_overlap(reworded, original),
            BUDGET_REASON_BORROWED,
        )

        # The boundary from below: genuinely different reasons about the same
        # subject, using the same technical vocabulary, have to be far under the
        # threshold or the rule is a tax on writing about this package at all.
        for other in self.REASONS[1:]:
            overlap = guidance_budget_reason_overlap(other, original)
            with self.subTest(other=other[:40]):
                self.assertLess(
                    overlap,
                    BUDGET_REASON_BORROWED,
                    f"two independently written reasons score {overlap:.0%} "
                    "against each other; the threshold refuses honest authors",
                )
        # And the real inherited entry, which is the one an author would
        # actually copy from, is no closer to any of them.
        inherited = guidance_budget_entries()[0].reason
        for other in self.REASONS:
            with self.subTest(other=other[:40]):
                self.assertLess(
                    guidance_budget_reason_overlap(other, inherited),
                    BUDGET_REASON_BORROWED,
                )
        # Containment, not similarity, is what makes the paste out of that long
        # entry catchable: one paragraph of it is a small fraction of 0001 and
        # all of the new entry.
        paragraph = "\n\n".join(inherited.split("\n\n")[3:6])
        self.assertIsNone(guidance_budget_reason_defect(paragraph))
        self.assertGreaterEqual(
            guidance_budget_reason_overlap(paragraph, inherited),
            BUDGET_REASON_BORROWED,
        )

    def test_a_figure_stated_twice_is_refused(self) -> None:
        """`follows:` was refused for being stated twice; a ceiling was not.

        The reader is the same and so is the damage. Two `total-ceiling:` lines
        parsed with the last one winning, so the number that governed was
        whichever came second in the file, while the other sat above it looking
        like the decision. That is the shape a bad merge resolution leaves, and
        the shape an author leaves who edits a figure by adding a line instead
        of changing one.
        """
        for field, value in (("total-ceiling", 240_000), ("total-measured", 239_118)):
            with self.subTest(field=field):
                stated = f"{field}: {value}"
                body = self.entry(
                    "0002 - branch A",
                    follows=1,
                    total_ceiling=240_000,
                    total_measured=239_118,
                )
                self.assertIn(stated, body)
                # The second spelling is the one that used to win silently.
                body = body.replace(stated, f"{stated}\n{field}: 999_999", 1)
                entries = self.ledger(
                    **{
                        "0001-inherited-ledger.md": self.root(),
                        "0002-branch-a.md": body,
                    }
                )
                self.assertDefect(entries, "more than once")


if __name__ == "__main__":
    unittest.main()

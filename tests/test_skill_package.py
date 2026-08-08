from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import posixpath
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


SKILL_PREFIX = "skills/traigent-first-run/"


def tracked_files() -> set[str]:
    """Every repository-relative path git publishes.

    From git rather than a filesystem walk, for the same reason the internal
    tooling check below uses git: the question is what gets PUBLISHED, not what
    happens to sit in the working tree.
    """
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0:
        raise RuntimeError(f"could not list tracked files: {listed.stderr.strip()}")
    return {name for name in listed.stdout.split("\0") if name.strip()}


def shipped_skill_files() -> set[str]:
    """Every file the Agent Skill installer copies, as skill-relative paths."""
    return {
        name[len(SKILL_PREFIX) :]
        for name in tracked_files()
        if name.startswith(SKILL_PREFIX)
    }


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


# A markdown block-level opener. Statements are cut at these as well as at
# sentence punctuation: a bullet ends at the newline and carries no full stop,
# so joining a block into one string makes two adjacent bullets a single
# "sentence" - and this guidance states the rungs as bullets.
_BLOCK_OPENER = re.compile(r"\s*(?:[-*+]\s|\d+[.)]\s|\||#{1,6}\s|>)")


def prose_statements(text: str) -> list[str]:
    """One document, cut into the statements a reader actually reads.

    Wrapped lines are rejoined first, because this guidance hard-wraps and a
    sentence routinely spans three source lines; splitting on newlines alone
    would tear a statement in half and report each half as saying nothing.
    """
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            blocks.append(" ".join(" ".join(current).split()))
            current.clear()

    for line in text.splitlines():
        if not line.strip():
            flush()
            continue
        if _BLOCK_OPENER.match(line):
            flush()
        current.append(line)
    flush()
    return [
        sentence
        for block in blocks
        for sentence in re.split(r"(?<=[.!?])\s+", block)
        if sentence.strip()
    ]


RUN_SAFETY = SKILL_ROOT / "references" / "run-safety.md"
SDK_EXECUTION = SKILL_ROOT / "references" / "sdk-execution.md"

# Two different 10-day periods exist and a customer meets both, so every mention
# of one has to say which. Spelled out as well as in digits: "the two ten-day
# windows" is the same sentence with the same defect, and a digits-only pattern
# reads it as clean.
TEN_DAY_MENTION = re.compile(r"\b(?:10|ten)[- ]days?\b", re.IGNORECASE)
TEN_DAY_COLLECTIVE = re.compile(r"\b(?:two|both)\s+(?:10|ten)[- ]day", re.IGNORECASE)
# A clock is named by the thing it is a property of. Registering is the event
# that ends one and starts the other, so "register"/"registration" appears in
# sentences about both and identifies neither - which is why it is not here.
_REGISTRATION_CLOCK = re.compile(r"access code", re.IGNORECASE)
_PORTAL_CLOCK = re.compile(r"portal access", re.IGNORECASE)


def ten_day_clocks_named(sentence: str) -> set[str]:
    """Which of the two 10-day clocks a sentence actually names.

    `"registration"` is the access code's clock: the code authorizes one portal
    registration for 10 days from issue, and afterwards it is dead. `"portal"`
    is the portal access period: 10 days of product use that *start* when that
    code is spent. Same number, different clock, different remedy.

    Returning a set rather than a boolean is the point. A sentence naming
    neither and a sentence naming the wrong one are different defects, and an
    "either will do" check cannot tell them apart - it accepts a sentence about
    the portal period because it happens to contain the word "registers".
    """
    named = set()
    if _REGISTRATION_CLOCK.search(sentence):
        named.add("registration")
    if _PORTAL_CLOCK.search(sentence):
        named.add("portal")
    return named


# A line that opens a markdown block-level unit: a list item, a table row, a
# heading, a block quote. The first version of the splitter joined a whole
# paragraph-separated block into one string and cut it on `.!?`, which is right
# for wrapped prose and wrong for every one of these - a bullet ends at the
# newline and carries no full stop, and a table row never does. So two bullets,
# one naming each clock, arrived as a single "sentence" naming both, and a table
# row arrived glued to its neighbours. `run-safety.md` already presents the
# account states as bullets and already carries tables, which is how a
# presentation this guard is meant to encourage became one it refused.
_MARKDOWN_BLOCK_START = re.compile(r"\s*(?:[-*+]\s|\d+[.)]\s|\||#{1,6}\s|>)")


def prose_units(text: str) -> list[str]:
    """One document, split the way a reader sees it.

    A unit is a markdown block - a paragraph, a list item, a table row - with
    its continuation lines rejoined, then cut into sentences. Rejoining matters
    because this guidance hard-wraps: a sentence routinely spans three source
    lines, and splitting on newlines alone would tear it apart and report each
    half as naming nothing. Both halves of that trade are load-bearing, which is
    why neither the line splitter nor the block splitter is used on its own.
    """
    units: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            units.append(" ".join(" ".join(current).split()))
            current.clear()

    for line in text.splitlines():
        if not line.strip():
            flush()
            continue
        if _MARKDOWN_BLOCK_START.match(line):
            flush()
        current.append(line)
    flush()
    return [
        sentence
        for unit in units
        for sentence in re.split(r"(?<=[.!?])\s+", unit)
        if sentence
    ]


def ten_day_sentences(text: str) -> list[str]:
    """Every sentence in a document that mentions a 10-day period."""
    return [
        sentence for sentence in prose_units(text) if TEN_DAY_MENTION.search(sentence)
    ]


def sdk_wrapper_state_nodes(text: str) -> list[ast.stmt]:
    """The generated wrapper's module-level state, as executable AST nodes.

    Every test that compiles `call_agent` out of the fenced source needs these
    in the module with it, because the function reads them. Collected from the
    document rather than restated as a literal in each fixture: a fixture that
    declares its own `REFUSED_TRIAL_COSTS = []` runs green against a wrapper
    that no longer has one.
    """
    nodes: list[ast.stmt] = []
    for source in re.findall(r"```python\n(.*?)\n```", text, re.DOTALL):
        for node in ast.parse(source).body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id.isupper():
                    nodes.append(node)
    return nodes


# Spelled forms of the counts a search space could plausibly have. The prose
# writes a size as a word ("twelve-row sweep") as often as a numeral ("12 and
# 48"), so both spellings of the SAME decision have to resolve to one number
# before anything can be compared. A size with no entry here raises rather than
# being skipped: an unrecognised spelling is a gap in this table, not a pass.
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "sixteen": 16,
    "eighteen": 18,
    "twenty": 20,
    "twenty-four": 24,
    "twenty-seven": 27,
    "thirty-two": 32,
    "thirty-six": 36,
    "forty-eight": 48,
    "fifty-four": 54,
    "ninety-six": 96,
}


def _quantity(spelling: str) -> int:
    """Resolve a numeral or a spelled number to an int, or say why it cannot."""
    if spelling.isdigit():
        return int(spelling)
    resolved = _NUMBER_WORDS.get(spelling.casefold())
    if resolved is None:
        raise AssertionError(
            f"the guidance states a space size as {spelling!r}, which this test "
            "cannot resolve to a number. Add it to _NUMBER_WORDS - a spelling "
            "nothing can read is a size nothing is checking."
        )
    return resolved


def generated_space_widths() -> dict[str, dict[str, int]]:
    """Each generated space's knobs, mapped to how many values it sweeps.

    Split out of `generated_space_sizes` below, which discarded these after
    multiplying them: the prose does not only state the products, it states the
    factors - "3 models x 2 prompt styles x 2 thinking shapes" - and a factor
    can go stale on its own while the product still agrees.
    """
    fence = re.findall(r"```python\n(.*?)\n```", SDK_EXECUTION.read_text(), re.DOTALL)[
        0
    ]
    spaces: dict[str, dict[str, int]] = {}
    for node in ast.parse(fence).body:
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not isinstance(node.value, ast.Dict):
            continue
        name = target.id.removesuffix("_SPACE")
        if f"{name}_SPACE" != target.id:
            continue
        widths: dict[str, int] = {}
        for key, value in zip(node.value.keys, node.value.values):
            assert isinstance(key, ast.Constant), f"{target.id} has a computed key"
            if isinstance(value, ast.List):
                widths[key.value] = len(value.elts)
            elif (
                isinstance(value, ast.Subscript)
                and isinstance(value.value, ast.Name)
                and isinstance(value.slice, ast.Constant)
            ):
                # `ENHANCED_SPACE["model"] = BASELINE_SPACE["model"]` - the
                # width lives in the space it is borrowed from.
                borrowed = value.value.id.removesuffix("_SPACE").casefold()
                widths[key.value] = spaces[borrowed][value.slice.value]
            else:
                raise AssertionError(
                    f"{target.id}[{key.value!r}] is neither a list of candidate "
                    "values nor a reference to another space's list, so its "
                    "width cannot be derived"
                )
        spaces[name.casefold()] = widths
    return spaces


def generated_space_sizes() -> dict[str, int]:
    """The two generated space sizes, derived from `sdk-execution.md` twice.

    The prose may not restate a size the code contradicts, so the size the
    check compares against has to come from the code and never from a number
    typed into this file. It is derived two independent ways and the two must
    agree:

    1. the `assert configuration_count(..._SPACE) == N` lines, which are what
       fails at load time inside a real run; and
    2. the product of the space literals themselves, walked from the fence's
       AST - `ENHANCED_SPACE` reuses several of the baseline's lists by
       reference, so those are resolved back through `BASELINE_SPACE`.

    Either derivation alone can be edited into agreement with a stale
    paragraph. Both moving together is a deliberate re-sizing, which is exactly
    when the documents are supposed to be re-read.
    """
    text = SDK_EXECUTION.read_text()
    asserted = {
        name: int(value)
        for name, value in re.findall(
            r"assert configuration_count\((BASELINE|ENHANCED)_SPACE\) == (\d+)", text
        )
    }
    assert sorted(asserted) == [
        "BASELINE",
        "ENHANCED",
    ], f"the fence must assert both space sizes; it asserts {sorted(asserted)}"

    constructed = {
        name: math.prod(widths.values())
        for name, widths in generated_space_widths().items()
    }
    folded = {name.casefold(): size for name, size in asserted.items()}
    assert constructed == folded, (
        f"the fence asserts {folded} but the spaces it defines are "
        f"{constructed}; the template contradicts its own asserts"
    )
    return folded


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


def quoted_prose(path: Path) -> str:
    """The whole document, whitespace-normalized, with leading `>` dropped.

    Not "the blockquotes" - every line, blockquote or not. The narrower helper
    is not worth building: what these checks need is the ability to match a
    sentence that a `>` block wrapped across lines, because to `str.split()`
    such a sentence has a `>` in the middle of it and a check written against
    the claim fails on the line wrapping instead. That would train the next
    author to pin half-sentences.

    What it therefore does NOT prove: that a matched phrase came from mandated
    user-facing copy rather than from ordinary body prose. Use it to find
    wording, and pin the placeholders (`<paired outcome counts>`) separately
    when the requirement is that the copy carries evidence.
    """
    lines = [
        line.lstrip().removeprefix(">").strip()
        for line in path.read_text().splitlines()
    ]
    return " ".join(" ".join(lines).casefold().split())


def python_block_containing(path: Path, needle: str) -> str:
    """The one fenced ```python block of `path` that contains `needle`.

    Raises unless exactly one block matches, so a check written against "the
    filter" cannot read a different block once the document grows another, nor
    pass against zero blocks once the code it binds is deleted outright.
    """
    blocks = [
        block
        for block in re.findall(
            r"^```python\n(.*?)^```", path.read_text(), re.DOTALL | re.MULTILINE
        )
        if needle in block
    ]
    if len(blocks) != 1:
        raise AssertionError(
            f"{needle!r} appears in {len(blocks)} fenced python blocks of "
            f"{path.name}; exactly one is required"
        )
    return blocks[0]


def load_guide_function(path: Path, definition: str):
    """Execute one fenced block of the guidance and return the function it defines.

    Loaded here for the same reason `readiness.py` is loaded above: the guide
    publishes real code, and a check that reads it as text can only prove the
    text is present.
    """
    namespace: dict = {}
    exec(python_block_containing(path, definition), namespace)  # noqa: S102
    return namespace[definition.removeprefix("def ").removesuffix("(")]


# The second run's frontier read. Its score floor is the only executable
# guarantee that no reported point scored below what the user already runs.
#
# Restored on the merge: these three definitions came in with #140 and were
# dropped resolving a conflict whose other side was the budget ledger. Without
# them ten of #140's tests raise NameError rather than testing anything.
FRONTIER_AT_OR_ABOVE = load_guide_function(SDK_EXECUTION, "def frontier_at_or_above(")


def prose_sentences(text: str) -> list[str]:
    """Split markdown prose into sentences without gluing list items together.

    Whitespace-normalising a whole document is what the phrase checks below do,
    and it is wrong for anything that has to reason about one statement: a
    wrapped sentence has its subject on one line and its predicate on the next,
    while two adjacent bullets are two statements that happen to share a
    paragraph. So blocks are unwrapped, list markers start a new statement, and
    only then is the text cut at sentence punctuation.
    """
    out: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        for item in re.sub(r"\n(?=\s*(?:[-*+]\s|\d+\.\s))", "\x1f", block).split(
            "\x1f"
        ):
            for sentence in re.split(r"(?<=[.!?])\s+", " ".join(item.split())):
                if sentence.strip():
                    out.append(sentence.strip())
    return out


# The rule that the walkthrough ceiling is never a provider-billing guarantee,
# recognised by what it SAYS rather than by how it is spelled. A statement of
# it has to name the ceiling and has to name what a provider charges; nothing
# else in this package's prose does both, so the pair is a usable signature.
_CEILING_TERMS = re.compile(
    r"\b(ceilings?|caps?|stop target|spend limit|cost limit)\b", re.IGNORECASE
)
_PROVIDER_MONEY = re.compile(
    r"\b(bills?|billed|billing|charges?|charged|invoiced?)\b", re.IGNORECASE
)
# What separates a MANDATE from a CONCLUSION is grammatical mood, not
# vocabulary, and the first version of this got that wrong in both directions.
# It was a hand-written list of eight negation words - never, do not, don't,
# must not, may not, shall not, cannot, avoid - which is the shape its own
# docstring warns about: "otherwise the guard is a word ban and the next
# duplicate simply gets reworded past it."
#
# It let real mandates through, because a mandate does not have to be negative:
#   "Always tell the user the walkthrough ceiling is only an execution stop
#    target, not something that caps what the provider bills"
#   "Present the ceiling as an execution stop target rather than a guarantee
#    about provider billing"
#   "Refrain from calling the walkthrough ceiling a hard provider-billing cap"
# and it refused a real conclusion, because a statement of fact can be negative:
#   "The walkthrough ceiling cannot guarantee what the provider bills;
#    `references/run-safety.md` owns the rule"
# which is the sentence shape README.md already uses - so the next person
# editing the public README tripped a guard about SKILL.md.
#
# The distinction that actually holds: a mandate is an instruction, so it is
# either in the imperative mood (no subject - "Never call it...", "Present
# it...", "Refrain from...") or it carries a deontic modal ("must never be
# described"). A conclusion predicates something OF the ceiling, so the ceiling
# is its subject: "The walkthrough ceiling is/cannot...".
#
# So the test is inverted, the way #167 inverted the private-repository denylist
# into a public allowlist. Rather than list the ways to say "don't" - an open
# set, which is why paraphrase walked past it - a candidate sentence is a
# mandate UNLESS it is recognisably a statement about the ceiling. That fails
# closed: the only way to be excused is to write a sentence whose subject is the
# ceiling and which legislates nothing, and that sentence is a conclusion.
#
# `_SUBJECT_DETERMINERS` is a closed grammatical class - English determiners and
# pronouns - which is what makes it different in kind from the word ban it
# replaces. Paraphrasing a mandate cannot grow this list; there is no new way to
# start an English noun phrase.
_SUBJECT_DETERMINERS = (
    r"the|this|that|these|those|a|an|it|its|they|their|we|our|you|your|"
    r"each|every|both|either|neither|any|some|no|one|there"
)
_CEILING_IS_THE_SUBJECT = re.compile(
    # An optional bullet or list marker, then a determiner, then up to three
    # words of the noun phrase, then the ceiling term itself.
    r"^\W*(?:[-*+]\s+|\d+[.)]\s+)?"
    rf"(?:{_SUBJECT_DETERMINERS})\b"
    r"(?:\s+[\w'$.`-]+){0,3}?"
    r"\s+(?:ceilings?|caps?|stop target|spend limit|cost limit|target)\b",
    re.IGNORECASE,
)
# A rule about behaviour, whatever the mood. "The stop target must never be
# described as..." opens with the ceiling as its subject and is still a mandate.
# `cannot` is deliberately NOT here: "the ceiling cannot guarantee what the
# provider bills" states what the ceiling is unable to do, which is the local
# conclusion CLAUDE.md explicitly permits.
_DEONTIC = re.compile(
    r"\b(?:must|shall|ought)\b|\bmay not\b|\bis not to be\b|\bare not to be\b"
    r"|\bis to be\b|\bare to be\b|\b(?:is|are) required to\b",
    re.IGNORECASE,
)


def is_billing_ceiling_mandate(sentence: str) -> bool:
    """Does this sentence legislate about the ceiling, rather than describe it?"""
    if _DEONTIC.search(sentence):
        return True
    return not _CEILING_IS_THE_SUBJECT.search(sentence)


def published_prose_documents() -> dict[str, str]:
    """Every markdown document this repository publishes, name -> raw text.

    From `git ls-files`, not a curated list. A one-home check whose corpus is
    hand-maintained can only ever be right about the documents somebody
    remembered: `conversation_contract_documents()` names six files, and the
    repository publishes seventeen markdown documents. README.md was in that
    list and `templates/`, `reports/` and `.github/` were not, so a mandate
    restated in any of them was outside every check by construction.

    `tests/` is excluded, and this is the only exclusion. The checks below
    plant mandate sentences deliberately, as the inputs that prove the rule can
    see one; scanning them would flag a guard's own fixtures. Nothing under
    `tests/` is prose a user or the assistant reads.

    Kept beside `instructional_documents()` below rather than merged with it,
    because the two answer different questions and #163 was right to want a
    second corpus: this one is EVERYTHING published, which is what the
    corpus-drift check needs, and that one additionally drops `reports/`,
    which quotes superseded guidance verbatim on purpose.
    """
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", "*.md"],
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0:
        raise RuntimeError(f"could not list tracked files: {listed.stderr.strip()}")
    return {
        name: (ROOT / name).read_text(encoding="utf-8")
        for name in sorted(listed.stdout.split("\0"))
        if name and not name.startswith("tests/")
    }


def instructional_documents() -> dict[str, str]:
    """Every markdown document this repository publishes AS INSTRUCTION.

    From `git ls-files`, not a curated list, because a curated list is only
    ever right about the documents somebody remembered.
    `conversation_contract_documents()` names six paths; the repository
    publishes seventeen markdown documents, and `README.md` - the most-read
    file here - was outside the one-home checks below until this corpus
    replaced them. A rule can be restated anywhere that gets published.

    Two directories are excluded, and each exclusion is a claim about what the
    document IS rather than about whether it happens to pass:

    * `tests/` plants restated mandates deliberately, as the inputs that prove
      a check can see one. Scanning them would flag a guard's own fixtures.
    * `reports/` records what past runs did, and quotes superseded guidance
      verbatim on purpose - `first-run-field-test.md` quotes a GUIDE.md step
      that no longer exists. A record of what was once written is not a second
      statement of the rule; treating it as one would make correcting the
      guidance require rewriting the history of having corrected it.
    """
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", "*.md"],
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0:
        raise RuntimeError(f"could not list tracked files: {listed.stderr.strip()}")
    return {
        name: (ROOT / name).read_text(encoding="utf-8")
        for name in sorted(listed.stdout.split("\0"))
        if name and not name.startswith(("tests/", "reports/"))
    }


def billing_ceiling_mandates(documents: dict[str, str]) -> dict[str, list[str]]:
    """Documents that state the billing-cap rule AS A MANDATE, by document.

    `documents` is name -> raw text, so this can be run over the repository or
    over invented text. Sentences that state the same conclusion without
    legislating are deliberately not returned: CLAUDE.md permits restating a
    conclusion locally and forbids restating the mandate, and that distinction
    is the whole content of the check.
    """
    found: dict[str, list[str]] = {}
    for name, text in documents.items():
        for sentence in prose_sentences(text):
            if not (
                _CEILING_TERMS.search(sentence) and _PROVIDER_MONEY.search(sentence)
            ):
                continue
            if is_billing_ceiling_mandate(sentence):
                found.setdefault(name, []).append(sentence)
    return found


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


# Three classifiers over ONE SENTENCE, used below to read a decision out of the
# guidance instead of confirming that a phrase is still spelled the same way.
#
# The distinction is the whole point. A check built from `assertIn("candidate
# to drop")` passes just as happily when the document has been changed to say
# the opposite thing somewhere else in the same sentence, and it passes when
# the sentence is reworded into nonsense as long as the fragment survives. So
# each of these takes a sentence and returns WHICH ANSWER it gives, and the
# tests below assert the answer. They are unit-tested against invented
# sentences - phrasings this guide does not contain, in both directions - so
# that a green result means the classifier can tell the directions apart,
# rather than meaning the document happened to be quoted correctly.

_SENTENCE_BREAK = re.compile(r"(?<=[.;:])\s+")

# "never X" and "not X" flip an assertion into its opposite, and this guidance
# writes both on purpose - it names the wording it forbids in order to forbid
# it. A classifier that ignored that would read every prohibition here as the
# claim it prohibits, and would call the document wrong for being right.
_IMMEDIATE_NEGATORS = ("never", "not", "than", "of", "no")


def _words(text: str) -> list[str]:
    """The alphabetic words of `text`, with punctuation and markup dropped."""
    return re.sub(r"[^a-z]+", " ", text.casefold()).split()


def _asserted(pattern: re.Pattern[str], sentence: str) -> int | None:
    """Offset of the first match of `pattern` the sentence is not negating.

    Negation here is the word immediately in front: `not preference` and
    `never the one to keep` are the shapes this guide uses to rule an answer
    out while still naming it.
    """
    for match in pattern.finditer(sentence):
        before = _words(sentence[: match.start()])
        if before and before[-1] in _IMMEDIATE_NEGATORS:
            continue
        return match.start()
    return None


_UNDER_MARGIN = re.compile(
    r"\b(?:under|below|less than|smaller than|within)\b[^,.;:]{0,40}?"
    r"\b(?:separation )?margin\b",
    re.IGNORECASE,
)
_DROP_VERDICT = re.compile(
    r"\b(?:candidate to drop|the one to drop|is droppable|drop(?:ped)? it)\b",
    re.IGNORECASE,
)
_KEEP_VERDICT = re.compile(
    r"\b(?:the one to keep|candidate to keep|must be kept|keep(?:s)? it|is kept)\b",
    re.IGNORECASE,
)


def tie_verdict(sentence: str) -> str | None:
    """For a knob whose values scored within the margin: drop it, or keep it?

    `None` means this sentence does not reach that verdict at all, which is
    itself a failing answer for the rule - a rule that stops before the verdict
    leaves the assistant to guess.
    """
    trigger = _UNDER_MARGIN.search(sentence)
    if trigger is None:
        return None
    tail = sentence[trigger.end() :]
    drop = _asserted(_DROP_VERDICT, tail)
    keep = _asserted(_KEEP_VERDICT, tail)
    if drop is None and keep is None:
        return None
    if keep is None or (drop is not None and drop < keep):
        return "drop"
    return "keep"


_BASELINE_AUTHORITY = re.compile(r"\bthe baseline'?s call\b", re.IGNORECASE)
_PREFERENCE_AUTHORITY = re.compile(r"\bpreference\b", re.IGNORECASE)


def selection_authority(sentence: str) -> str | None:
    """Who decides which of the customer's knobs to keep: evidence, or taste?"""
    baseline = _asserted(_BASELINE_AUTHORITY, sentence)
    preference = _asserted(_PREFERENCE_AUTHORITY, sentence)
    if (baseline is None) == (preference is None):
        return None
    return "baseline" if baseline is not None else "preference"


# A claim that a knob has NO EFFECT, in the ways one gets written. Not a
# blocklist of literals this document happens not to contain: it is the
# predicate, in its ordinary English forms, so a phrasing nobody has written
# yet is caught the first time rather than after someone reads it.
_NO_EFFECT_CLAIM = re.compile(
    r"\b(?:"
    r"do(?:es)? not matter|don't matter|doesn't matter|didn't matter|did not matter"
    # `inert` is deliberately absent. The guide uses it for a MECHANISM it can
    # name - a reasoning model's provider ignores `temperature`, which is true
    # of the API and not inferred from six trials - and this rule is about
    # inferring absence from a measurement that cannot carry it. Refusing the
    # provider fact would teach an author to route around the guard, which is
    # worse than the gap.
    # `unimportant` and `negligible` were the gap: "Report that the knob is
    # unimportant" is the same assertion as "the knob does not matter", in the
    # words an author reaches for when the blunt ones feel too strong - which
    # is exactly when it gets written. Enumerating the predicate is the design
    # here, so a form it cannot express is a hole in the design, not a missing
    # literal.
    r"|(?:is|are|was|were|be) +(?:irrelevant|useless|pointless|meaningless"
    r"|unimportant|negligible|not important)"
    r"|ha(?:s|ve|d) +no +(?:effect|impact|influence|bearing)"
    r"|no +(?:effect|impact|influence|difference) +(?:at all|whatsoever|on)"
    r"|does nothing|do nothing|did nothing"
    r"|makes? no difference"
    r"|(?:is|are|was|were) +(?:proven|shown|known) +(?:to be )?(?:irrelevant|useless)"
    r")\b",
    re.IGNORECASE,
)
# Prohibiting the claim is not making it, and this guide prohibits it in
# writing - so the marker has to be looked for across the whole clause in
# front, not only in the word immediately before. `never enough to prove one
# does nothing` negates from six words away.
#
# The markers are deliberately the strong ones. A bare `not` would have
# accepted `the knob did not move the baseline, so it does not matter`, which
# is precisely the sentence the rule exists to refuse.
#
# The name is deliberately narrow. This alternation is not a general-purpose
# "is this sentence a prohibition" matcher - it deliberately omits `do not`
# and `don't`, because those are too weak to hedge a no-effect claim. Naming
# it `_PROHIBITION` would invite a reader, or a merge, to reuse it as one.
_NO_EFFECT_HEDGE = re.compile(
    r"\b(?:never|cannot|can't|must not|may not|not enough|nothing here proves"
    r"|rather than|instead of|avoid|refuse|refuses|forbid(?:s|den)?|no claim"
    r"|does not prove|do not prove|cannot prove|is not proof|not proof)\b",
    re.IGNORECASE,
)


def claims_no_effect(sentence: str) -> bool:
    """Does this sentence assert that a knob has no effect?

    The guide may report `did not move the baseline` and may never report
    `does not matter`, because six trials cannot tell those apart. Naming the
    forbidden phrasing is how the rule is written, so a prohibition ("never say
    it does not matter") is not a violation, and an assertion ("it does not
    matter") is - regardless of which words the assertion happens to use.
    """
    for match in _NO_EFFECT_CLAIM.finditer(sentence):
        if not _NO_EFFECT_HEDGE.search(sentence[: match.start()]):
            return True
    return False


def sentences(text: str) -> list[str]:
    """Whitespace-normalised sentences, split on real sentence punctuation."""
    return [
        part.strip()
        for part in _SENTENCE_BREAK.split(" ".join(text.split()))
        if part.strip()
    ]


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

    def test_every_file_the_guidance_names_is_a_file_that_exists(self) -> None:
        """A named file the reader cannot open is an instruction they cannot follow.

        The link check above reads SKILL.md only, and only markdown-link syntax,
        so a path written in backticks - which is how most of this guidance names
        a file - was outside every check. `GUIDE.md` was named that way in
        SKILL.md's operating contract while living at the repository root, which
        the Agent Skill installer does not copy: the installed skill instructed
        the assistant to open a document it did not have, and nothing failed.

        Each document is resolved from where its reader actually stands. An
        installed run has the skill directory and nothing else, so a shipped
        document resolves against what git publishes under it. GUIDE.md is read
        from a clone, and its own "Start here" section sends the reader into the
        resolved skill directory for bundled files, so it resolves against the
        repository and that directory both - which is also why it must say which
        one it means when it names a bundled file.
        """
        shipped = shipped_skill_files()
        repository = tracked_files()
        # Source-repository paths that are deliberately not installed. Named
        # rather than pattern-excluded, because a silent exclusion is how the
        # defect above got in. Each is addressed to a maintainer editing this
        # package and is never opened during a run.
        unshipped = {
            "tests/test_skill_package.py": (
                "names the check that keeps run-safety.md's config-space table "
                "welded to readiness.py's declaration"
            ),
        }
        cited: set[str] = set()

        def unresolved(document: Path, text: str, roots: list[tuple[str, set[str]]]):
            """Report every reference in one document that resolves nowhere."""
            for raw in self._file_references(text):
                target = self._reference_path(raw)
                if not target or "://" in target:
                    continue
                # A path in the user's project that this run creates. It never
                # resolves in a guidance corpus and must not: no run artifact
                # is shipped, and none exists before the run makes it.
                #
                # Matched on the `traigent-runs/` SEGMENT rather than on the
                # start of the string, because guidance that tells the
                # assistant to name a written file "by absolute path" writes it
                # under a placeholder root - `<project root>/traigent-runs/
                # holdout.jsonl`. The reference extractor splits an inline-code
                # span on whitespace, so that arrives here as
                # `root>/traigent-runs/holdout.jsonl`, which is still the same
                # run artifact and still must not be looked for on disk. A
                # `startswith` check reported both written splits as dangling
                # files while the instruction naming them was correct.
                if target == "traigent-runs" or "traigent-runs/" in target:
                    continue
                if target in unshipped:
                    cited.add(target)
                    continue
                if any(
                    self._resolves(document, target, base, files)
                    for base, files in roots
                ):
                    continue
                yield f"{document} names {target!r}, which nothing here provides"

        dangling: list[str] = []
        for name in sorted(shipped):
            if name.endswith(".md"):
                dangling += unresolved(
                    Path(name), (SKILL_ROOT / name).read_text(), [("", shipped)]
                )
        dangling += unresolved(
            Path("GUIDE.md"),
            (ROOT / "GUIDE.md").read_text(),
            [("", repository), (SKILL_PREFIX, repository)],
        )
        self.assertEqual(
            dangling,
            [],
            "guidance names a file its reader cannot open",
        )
        # The escape hatch gets the same treatment as the rule: an entry nothing
        # cites any more is removed, not left to quietly widen what passes.
        self.assertEqual(sorted(set(unshipped) - cited), [])

        # A CLEAN TREE PROVES NOTHING ABOUT WHAT THE GUARD CAN SEE, and this
        # one is neuterable by a single token: drop `md` from `_NAMES_A_FILE`
        # and every backticked markdown reference stops being a reference at
        # all - including `GUIDE.md`, the exact defect this test was written
        # for, whose docstring says most of this guidance names a file in
        # backticks. So the guard is handed the defect it exists to catch, in
        # the form it actually took, and must report it.
        planted = "The operating contract lives in `GUIDE.md`; read it first."
        with self.subTest(direction="the defect is seen"):
            self.assertEqual(
                list(unresolved(Path("SKILL.md"), planted, [("", shipped)])),
                ["SKILL.md names 'GUIDE.md', which nothing here provides"],
                "an installed skill naming GUIDE.md - a file the installer does "
                "not copy - is invisible to this check",
            )
        # And the other direction, because a guard tightened until it flags
        # working references teaches authors to route around it: the same
        # sentence naming a file that IS shipped resolves silently.
        with self.subTest(direction="a working reference is not flagged"):
            self.assertEqual(
                list(
                    unresolved(
                        Path("SKILL.md"),
                        "The handoff lives in `references/run-safety.md`.",
                        [("", shipped)],
                    )
                ),
                [],
            )

    def test_the_reference_extractor_sees_every_kind_of_file_it_claims_to(
        self,
    ) -> None:
        """One token in `_NAMES_A_FILE` is the whole reach of the check above.

        Each extension there is a class of reference the guidance actually
        writes, and removing any one of them silently empties the check for that
        class rather than failing anything. `md` is the load-bearing one - the
        defect that started this was a backticked `GUIDE.md` - but `.py` names
        the three scripts, `.json`/`.jsonl` the config space and the dataset,
        `.txt` the pinned requirements and `.yml`/`.yaml` the agent definition.

        The near-misses matter as much: a version number, a decimal, and a
        sentence-ending abbreviation are not files, and a check that called them
        files would fail on prose nobody can rewrite.
        """
        for name in (
            "GUIDE.md",
            "SKILL.md",
            "references/run-safety.md",
            "scripts/readiness.py",
            "assets/requirements-first-run.txt",
            "traigent-runs/config-space.json",
            "traigent-runs/tuning.jsonl",
            "agents/openai.yaml",
            "agents/openai.yml",
        ):
            with self.subTest(reference=name):
                self.assertEqual(
                    self._file_references(f"Open `{name}` before you continue."),
                    [name],
                    "a backticked file reference is not recognised as one, so "
                    "every check built on this extractor is empty for it",
                )
        # Written the way prose writes them: with an anchor, in a link, and at
        # the end of a sentence.
        self.assertEqual(
            self._file_references("See `GUIDE.md#start-here` for the order."),
            ["GUIDE.md#start-here"],
        )
        self.assertEqual(
            self._reference_path("GUIDE.md#start-here"),
            "GUIDE.md",
        )
        self.assertEqual(
            self._file_references("[the handoff](references/run-safety.md)"),
            ["references/run-safety.md"],
        )
        # Not files, and each is something this guidance genuinely writes.
        for innocent in (
            "Pinned to `0.25.0` for the first run.",
            "Costs `$5.00` at most.",
            "Set `TRAIGENT_API_KEY=` in the file.",
            "Roughly `0.75` of the rows.",
        ):
            with self.subTest(innocent=innocent):
                self.assertEqual(self._file_references(innocent), [])
        # A fenced example is illustration, not an instruction to open a file.
        self.assertEqual(
            self._file_references("```\ncat some-file-that-does-not-exist.md\n```\n"),
            [],
        )

    # Fenced blocks are stripped: an illustrative path inside a code sample is
    # not an instruction to open a file, and treating it as one makes the check
    # fail on its own examples.
    _FENCE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
    _INLINE_CODE = re.compile(r"`([^`]+)`")
    _MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")
    _NAMES_A_FILE = re.compile(r"\.(?:md|py|txt|json|jsonl|ya?ml)$")

    @classmethod
    def _file_references(cls, text: str) -> list[str]:
        """Every token in one document that names a file, as written."""
        body = cls._FENCE.sub("", text)
        found = [
            token
            for span in cls._INLINE_CODE.findall(body)
            for token in span.split()
            if cls._NAMES_A_FILE.search(cls._reference_path(token))
        ]
        return found + cls._MARKDOWN_LINK.findall(body)

    @staticmethod
    def _reference_path(raw: str) -> str:
        """The path a reader would open, without the sentence around it.

        A reference is written into prose, so it arrives carrying an anchor, a
        comma, or the quotes of the shell line it sits in. Matching the raw
        token instead means `GUIDE.md#start-here` - the natural way to write the
        defect this test exists to catch, since GUIDE.md has a `## Start here` -
        is not recognised as a reference at all.
        """
        target = raw.split("#", 1)[0].split("?", 1)[0]
        # Trailing punctuation is stripped separately from leading, so that a
        # sentence-ending `SKILL.md.` loses its full stop while a dotfile keeps
        # its leading one.
        target = target.lstrip("\"'`(*").rstrip("\"'`),;:!?.")
        # `.../a/b` is this guidance's elision for "under some absolute prefix".
        return target[4:] if target.startswith(".../") else target

    @staticmethod
    def _resolves(document: Path, target: str, base: str, files: set[str]) -> bool:
        """Does `target`, read in `document`, name a file that exists?

        Candidates are paths, never basenames: a basename fallback passes
        `assets/glossary.md` for a file that lives in `references/`, which is
        not checking the reference the reader was given. The bundle root and its
        two directories are candidates because that is how these documents cite
        each other - `run-safety.md` from a sibling reference, `readiness.py`
        from SKILL.md - and each is a real directory, not a wildcard.
        """
        # A `..` climbs out of the bundle, and one of the candidate prefixes
        # would then let it climb back in - `scripts/../scripts/readiness.py`
        # normalizes onto a real file. Guidance never needs to write one.
        if ".." in target.split("/"):
            return False
        for prefix in ("", str(document.parent) + "/", "references/", "scripts/"):
            candidate = posixpath.normpath(
                posixpath.join(base, prefix.lstrip("./"), target)
            )
            if candidate.startswith(("..", "/")):
                continue
            if candidate in files:
                return True
        return False

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

    def _tracked_under(self, pathspec: str) -> str:
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--", pathspec],
            capture_output=True,
            text=True,
            check=False,
        )
        if listed.returncode != 0:
            raise RuntimeError(
                f"could not inspect tracked files under {pathspec}: "
                f"{listed.stderr.strip()}"
            )
        return listed.stdout.strip()

    def test_generated_run_artifacts_are_not_tracked(self) -> None:
        """A run writes `traigent-runs/`; committing it ships someone's run.

        The pathspec is the whole check, and `git ls-files` answers a pathspec
        that matches nothing exactly as it answers a clean tree: exit 0, empty
        output. So a typo in the thirteen characters below is byte-identical to
        the passing case, and this would stay green for the rest of the
        repository's life while tracking every artifact it exists to refuse.
        The positive control fixes that - the same call must find something
        where something is known to be tracked.
        """
        self.assertEqual(self._tracked_under("traigent-runs"), "")
        self.assertNotEqual(
            self._tracked_under("skills"),
            "",
            "`git ls-files` reports nothing under a directory this repository "
            "certainly tracks, so the empty result above is the tool failing "
            "to look rather than the tree being clean",
        )

    def test_user_facing_skill_language_does_not_label_the_user(self) -> None:
        combined = "\n".join(
            path.read_text() for path in SKILL_ROOT.rglob("*.md") if path.is_file()
        ).casefold()
        self.assertNotIn("beginner", combined)
        self.assertNotIn("non-technical", combined)
        self.assertNotIn("not for experienced", combined)

    ACCOUNT_LINK_HOSTS = frozenset(
        {
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
    )

    @classmethod
    def _account_link_offence(cls, url: str) -> str | None:
        """Why this address may not be handed to a user, or `None`.

        Trailing sentence punctuation is stripped BEFORE the host is read, not
        only before the path is compared. The bare-site rule below already did
        that; the host check did not, so an address written at the end of a
        sentence - `https://traigent.ai.` - was read as the host
        `traigent.ai.` and reported as a destination the guide may not name.
        A false red on the one address the guidance is required to hand over,
        waiting for the first author who ends a sentence with it.
        """
        url = url.rstrip(").,")
        host = url.split("/", 3)[2]
        if host not in cls.ACCOUNT_LINK_HOSTS:
            return f"{host} is not a destination this guide may name"
        # Host granularity is enough for the provider links, and not enough for
        # this one: `traigent.ai/register` is a page that does not exist and is
        # the exact shape run-safety forbids handing to a user with no access
        # code. The public site is only ever given bare.
        if host == "traigent.ai" and url != "https://traigent.ai":
            return "the public site is handed over bare, never with a path"
        return None

    def test_active_run_guidance_contains_only_required_account_links(self) -> None:
        """Every address the guidance hands a user, and nothing else.

        Both halves are probed. A clean corpus proves the documents are tidy
        today, not that this check can see an address that is not - and it
        never had, because no disallowed URL has ever been in the tree for it
        to reject. The bare-site rule in particular had no failing case at all,
        so it could have been deleted without anything going red.
        """
        combined = "\n".join(path.read_text() for path in assistant_facing_documents())
        urls = re.findall(r"https?://[^`\s)]+", combined)
        self.assertTrue(urls, "no address was extracted, so nothing was checked")
        for url in urls:
            with self.subTest(url=url):
                self.assertIsNone(self._account_link_offence(url))

        for planted in (
            # A destination this guide may not name at all.
            "https://evil.example.com/x",
            # The portal's register page, which refuses a user holding no code.
            "https://app.traigent.ai/register",
            # The page that does not exist - the shape the bare-site rule
            # exists for, and the one nothing in the tree ever exercised.
            "https://traigent.ai/register",
            "https://traigent.ai/pricing",
        ):
            with self.subTest(planted=planted):
                self.assertIsNotNone(
                    self._account_link_offence(planted),
                    "an address this guide may not hand over, and the check "
                    "cannot see it",
                )
        for legal in (
            "https://traigent.ai",
            "https://traigent.ai.",
            "https://portal.traigent.ai/settings",
            "https://console.anthropic.com/settings/keys",
        ):
            with self.subTest(legal=legal):
                self.assertIsNone(
                    self._account_link_offence(legal),
                    "the check refuses an address the guidance is required to "
                    "hand over",
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
            "preserved baseline or generated twelve-row sweep",
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

    # The one release this package names that is deliberately NOT the pinned
    # one, and the sentence that earns it. `run-safety.md` warns that on an
    # unsupported interpreter, resolution can select an unrelated obsolete
    # release - naming it is the whole point of the warning, so the check below
    # excuses this exact sentence rather than the bare number, and a second
    # passage naming `0.0.1` for some other reason still fails.
    NON_PINNED_RELEASE_ALLOWLIST = (
        "package resolution can select the unrelated obsolete `0.0.1` release",
    )

    def _unpinned_releases(self, text: str, pinned: set[str]) -> list[str]:
        """Release-shaped literals in `text` that no pinned requirement installs."""
        body = " ".join(text.split())
        for excused in self.NON_PINNED_RELEASE_ALLOWLIST:
            body = body.replace(excused, "")
        return sorted(set(re.findall(r"\d+\.\d+\.\d+", body)) - pinned)

    def test_no_assistant_facing_document_names_an_unpinned_release(self) -> None:
        """The README rule above, applied to the documents the assistant reads.

        `test_readme_discloses_pinned_sdk_license_terms` already refuses a
        release-shaped literal in README.md that is not the pinned one. The
        same claim is made in four more places the reader is sent to -
        `sdk-execution.md` names the pinned release three times (the local-log
        note, the relative-path defect, the sync limitation) and
        `run-safety.md` once - and none of them was covered by anything. So a
        pin bump could update README and leave the references describing the
        behaviour of a release nobody installs, with the suite green.

        Derived twice over: the permitted set is every version
        `assets/requirements-first-run.txt` actually pins, so naming the pinned
        `litellm` is legal without this test being edited, and bumping any pin
        fails here until the prose that describes it is re-read.
        """
        pinned = set()
        for line in REQUIREMENTS.read_text().splitlines():
            _, separator, version = line.strip().partition("==")
            if separator and version:
                pinned.add(version)
        self.assertIn(
            pinned_sdk_version(),
            pinned,
            "the permitted set must contain the pinned SDK release, or this "
            "check is reading the wrong file",
        )

        stale: dict[str, list[str]] = {}
        for document in assistant_facing_documents():
            named = self._unpinned_releases(document.read_text(), pinned)
            if named:
                stale[document.relative_to(ROOT).as_posix()] = named
        self.assertEqual(
            stale,
            {},
            "an assistant-facing document names a release the pinned "
            "requirements do not install. Every version statement in this "
            "guidance describes the behaviour of what the reader installs; a "
            "different one describes a release they will never run.",
        )

        # A clean tree proves the documents agree today, not that this check
        # can SEE a disagreement - and the corpus it walks narrows silently, so
        # the empty result above is also what a broken glob returns. Both
        # directions are probed against invented text instead.
        self.assertEqual(
            self._unpinned_releases("installed 9.9.9 behaves this way", pinned),
            ["9.9.9"],
        )
        self.assertEqual(
            self._unpinned_releases(
                f"installed {pinned_sdk_version()} behaves this way", pinned
            ),
            [],
        )
        self.assertEqual(
            self._unpinned_releases(self.NON_PINNED_RELEASE_ALLOWLIST[0], pinned),
            [],
            "the obsolete-release warning is the one excused sentence",
        )
        self.assertEqual(
            self._unpinned_releases("the obsolete `0.0.1` release", pinned),
            ["0.0.1"],
            "the exemption is the sentence, not the number: naming that "
            "release for any other reason is still a release nobody installs",
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

    def test_the_knob_selection_rule_matches_the_arithmetic_it_cites(self) -> None:
        """The guidance told the assistant to keep "a few" and stopped there.

        There was no rule for WHICH of a customer's own knobs to keep, no
        statement of what the space may cost, and no gate anywhere if the
        assistant kept all of them: a ten-knob space at 1024 configurations
        against a 12-trial cap raises no cap and prints no note - it just
        quietly loses points.

        The cost of that is measured below rather than asserted here, because
        the figures this docstring used to carry (49 and 60) could not be
        reproduced against `readiness.py` on any shape tried, and an
        unverifiable number in a docstring is exactly the drift the rest of
        this test exists to stop. What IS reproducible is stated with its
        inputs: ten wired knobs of a customer's own naming, two values each,
        `agent_type` "general" and `max_trials` 12, against that same
        customer's first four - the same knobs, the same agent, a gap made of
        nothing but the ratio of space to budget.

        The gap is what is asserted, and the absolute pair is not. Those
        numbers were 49/60, then 44/55, and are 64/75 as this merges: #174
        re-prices a categorical knob's two values as FULL breadth rather than
        half, which lifts every space here without touching the decision this
        test protects. A pillar's absolute value is a pricing choice branches
        are free to revise - #168 hit exactly this and rewrote its own
        assertion the same way after `85 != 77` failed a merge neither
        branch's CI could see. A relation survives a re-pricing; an absolute
        is a merge failure waiting for a date. The plateau and floor asserted
        above are the control: without them `kept_four > kept_all` would hold
        just as well for a scorer that had stopped responding to knob count.

        So the rule names the numbers, and this asserts the scorer agrees about
        the DIRECTION rather than about a pair. Guidance that cites arithmetic
        it does not share with the code is guidance that goes stale silently,
        which is the failure this file exists to catch.

        The first version of this test was a list of `assertIn` calls, and it
        was worth nothing: swapping the rule's `candidate to drop` for `the one
        to keep` - the exact reversal of the decision it was written to protect
        - left the whole suite green, and so did turning `the baseline's call,
        not preference` around. It pinned VOCABULARY. What follows pins the
        ANSWER, by reading it back out of the sentence with a classifier that
        is itself unit-tested against invented sentences in both directions.
        """
        text = RUN_SAFETY.read_text()
        start = text.index("A customer who brings ten wired knobs")
        rule = " ".join(text[start : text.index("Native boolean knobs", start)].split())
        parts = sentences(rule)

        # 1. Which way does the tie break? A knob whose values scored within
        #    the margin is a CANDIDATE TO DROP. Reverse the document and this
        #    reads "keep"; delete the verdict and this reads nothing at all.
        verdicts = {tie_verdict(part) for part in parts} - {None}
        self.assertEqual(
            verdicts,
            {"drop"},
            "a knob whose values scored within the separation margin is a "
            f"candidate to drop; the rule now reaches {verdicts or 'no verdict'}",
        )

        # 2. Who decides - the baseline's evidence, or the assistant's taste?
        authorities = {selection_authority(part) for part in parts} - {None}
        self.assertEqual(
            authorities,
            {"baseline"},
            "which of the customer's knobs to keep is decided by baseline "
            f"evidence, not preference; the rule now says {authorities or 'neither'}",
        )

        # 3. And the rule may not overclaim from six trials. This is the same
        #    predicate the whole-guidance check below applies; it runs here too
        #    because this paragraph is where the temptation lives.
        overclaims = [part for part in parts if claims_no_effect(part)]
        self.assertEqual(
            overclaims,
            [],
            "six baseline trials cannot show a knob has no effect, only that "
            "it did not move the baseline",
        )

        scripts = str(SKILL_ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        readiness = importlib.import_module("readiness")
        # #189 replaced `knob_count_points` - a ramp over how MANY knobs - with
        # `search_space_points`, a ladder over how much of the space the run
        # will actually compare. The rule's arithmetic is re-read against the
        # function that now decides it, rather than against one that is gone.
        points = readiness.search_space_points
        best = points(readiness.SEARCH_SPACE_FULL, readiness.SEARCH_SPACE_FULL)
        # Full credit starts at twelve reachable configurations, which is the
        # number the rule quotes; one below it is a lower rung.
        self.assertEqual(points(12, 12), best)
        self.assertLess(points(11, 12), best)
        # 240 is 20 x the default cap, and it is the threshold the rule quotes:
        # a space at it is unpunished and a space past it is damped.
        self.assertEqual(points(240, 12), best)
        self.assertLess(points(241, 12), best)
        # And an undeclared budget is damped where an oversized space is, which
        # is what stops deleting the field from buying the top rung.
        self.assertLess(points(1000, None), best)

        # The cost the rule exists to prevent, run through the real scorer so
        # the docstring's two numbers cannot go stale in silence. The knobs are
        # a customer's own naming rather than the scorer's canonical ones,
        # which is the case the rule is about: a customer arrives with their
        # agent's controls, not with `temperature` and `top_p`.
        declared = {f"knob_{index}": ["x", "y"] for index in range(10)}

        def agent_pillar(knobs: dict[str, list[str]]) -> int:
            pillar, caps = score_config_space(
                {
                    "knobs": knobs,
                    "max_trials": 12,
                    "wired": list(knobs),
                }
            )
            self.assertEqual(caps, [], "neither space is capped; only scored")
            return pillar.score

        kept_all = agent_pillar(declared)
        kept_four = agent_pillar(dict(list(declared.items())[:4]))
        self.assertGreater(
            kept_four,
            kept_all,
            "keeping four of a customer's ten knobs must score ABOVE keeping "
            "all ten, or the rule the guidance states is not the rule the "
            "scorer applies",
        )

        # 4. The upper bound is a MANDATE, so it lives in SKILL.md (CLAUDE.md:
        #    SKILL.md carries the mandates, a reference carries the depth), and
        #    the number it states is read back and compared against the ramp
        #    rather than quoted. Widen it to "four to nine" and this fails,
        #    because nine is past the plateau.
        stated = re.search(
            r"aim at (\w+) to (\w+) varying knobs",
            " ".join(SKILL.read_text().split()),
            re.IGNORECASE,
        )
        self.assertIsNotNone(
            stated,
            "SKILL.md no longer bounds the enhanced space's knob count - the "
            "unbounded 'materially larger than its trial cap' was the defect",
        )
        spelled = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
        }
        # The bound used to be compared against `knob_count_points`' plateau,
        # which was where it came from. #189 removed that ramp, so the bound is
        # no longer DERIVABLE from the scorer - and pretending otherwise would
        # be the drift this test exists to catch, pointed inward. What is
        # checked instead is that both ends of the stated bound still reach the
        # top rung against the default cap, and that a space below it does not.
        low, high = (spelled[word.casefold()] for word in stated.groups())
        self.assertLess(low, high, "the bound must name a range, low end first")
        for knobs_ in (low, high):
            with self.subTest(knobs=knobs_):
                self.assertEqual(
                    points(2**knobs_, readiness.SEARCH_SPACE_FULL),
                    best,
                    f"{knobs_} binary knobs must still reach full search-space "
                    "credit against the default cap, or SKILL.md's bound and "
                    "the scorer have drifted apart",
                )
        self.assertLess(points(2 ** (low - 1), readiness.SEARCH_SPACE_FULL), best)
        # ...and run-safety.md carries the arithmetic behind it without stating
        # the mandate a second time, which is the defect CLAUDE.md names.
        self.assertIn("twelve reachable", rule)
        self.assertNotIn("aim at", rule.casefold())

        # 5. The separation margin is calibration's, not a number invented for
        #    the prose - two homes for one threshold is how they drift apart -
        #    and the rule names where it lives so a reader can check it.
        calibration = importlib.import_module("calibrate_evaluator")
        self.assertIn(f"{calibration.SEPARATION_MARGIN} normalized", rule)
        self.assertIn("`--separation-margin` default in", rule)
        self.assertIn("calibrate_evaluator.py", rule)
        # Two unrelated 0.05s now sit in this file - the config-space scorer's
        # per-VALUE noise floor and this per-SCORE margin - so the rule has to
        # say which one it is not.
        self.assertIn("noise floor", rule)

        # 6. The obligation to name what was left out has ONE home: the
        #    approval preview's own checklist. It had two, each satisfiable
        #    without the other, which is a rule that can be changed in one
        #    place and still look enforced from the other.
        preview = text[text.index("give the connected stage a preview") :]
        self.assertIn("any knob of theirs left out and what the baseline", preview)
        # `excluded` came out of this alternation on the merge, and the reason
        # is a false positive rather than a narrowing. #149's routing bullet
        # for `agent-no-varying-knobs` says "only knobs excluded from scoring",
        # which is a statement about what the SCORER ignores - not about
        # disclosing a customer's knob this run declined to carry. #169 wrote
        # the alternation before that bullet existed, so the guard reported two
        # homes for a mandate that still has one, and deleting #149's phrase to
        # satisfy it would have removed load-bearing routing text to fix a
        # regex. The three remaining spellings all describe leaving something
        # OUT of the run, which is the mandate.
        omission_mandate = re.compile(
            r"\bknobs?\b[^.]{0,40}?\b(?:left out|omitted|not carried)\b",
            re.IGNORECASE,
        )
        homes = {
            path.name: len(omission_mandate.findall(path.read_text()))
            for path in assistant_facing_documents()
            if omission_mandate.search(path.read_text())
        }
        self.assertEqual(
            homes,
            {"run-safety.md": 1},
            "the omitted-knob disclosure is stated in more than one place; a "
            "rule with two homes can be changed in one and still look enforced "
            "from the other. Restate the conclusion and point at the home.",
        )

    def test_the_no_effect_classifier_can_tell_the_two_directions_apart(self) -> None:
        """The guard above is only worth its green if this is true.

        Every sentence here is INVENTED - none of them is in the package - so
        this measures the classifier rather than the document. A guard tested
        against the strings its own corpus contains proves only that the corpus
        was quoted correctly, which is how a test survives the mutation of the
        decision it was written to protect.
        """
        must_refuse = (
            "A spread under the margin proves the knob does not matter.",
            "Report that the knob is irrelevant, useless, and proves it has no effect.",
            "The baseline showed this control is useless, so drop it.",
            "Six trials showed the knob does nothing.",
            "Tell the customer the setting has no impact on their agent.",
            "Say the retrieval depth makes no difference and move on.",
            "That knob was shown to be irrelevant by the baseline.",
            "Report that the knob is unimportant.",
            "Say the value it chose is not important and move on.",
            "The spread was small, so that lever is negligible.",
        )
        for sentence in must_refuse:
            with self.subTest(refuse=sentence):
                self.assertTrue(
                    claims_no_effect(sentence),
                    "this asserts a knob has no effect and must be refused",
                )

        must_accept = (
            "Say `did not move the baseline`, never `does not matter`.",
            "Three observations a side is never enough to prove one does nothing.",
            "Six trials cannot prove a knob has no effect.",
            "Report that the knob did not move the baseline.",
            "A spread under the margin makes that knob a candidate to drop.",
            "Prefer the knob the baseline ranked, rather than one that does nothing.",
            "Silence is not a null result, so the knob gets no verdict.",
            "Never report that a knob is unimportant on twelve trials.",
            "Twelve trials cannot show a lever is negligible.",
        )
        for sentence in must_accept:
            with self.subTest(accept=sentence):
                self.assertFalse(
                    claims_no_effect(sentence),
                    "this reports the measurement honestly, or forbids the "
                    "overclaim, and must be allowed",
                )

    def test_the_direction_classifiers_can_tell_the_two_directions_apart(self) -> None:
        """Same argument, for the two answers the knob-selection rule gives.

        Invented sentences again, and deliberately including the reversals that
        the previous `assertIn` version of that test let through unchanged.
        """
        self.assertEqual(
            tie_verdict(
                "A spread under the separation margin did not move the "
                "baseline, and that knob is a candidate to drop."
            ),
            "drop",
        )
        self.assertEqual(
            tie_verdict(
                "A spread under the separation margin did not move the "
                "baseline, and that knob is the one to keep."
            ),
            "keep",
        )
        self.assertEqual(
            tie_verdict(
                "Where the values score within the margin, that knob is a "
                "candidate to drop, never the one to keep."
            ),
            "drop",
        )
        # No margin test, or no verdict after it, is not an answer.
        self.assertIsNone(tie_verdict("Keep a few of the most relevant knobs."))
        self.assertIsNone(
            tie_verdict("A spread under the separation margin is worth noting.")
        )

        self.assertEqual(
            selection_authority(
                "Which of theirs to keep is the baseline's call, not preference."
            ),
            "baseline",
        )
        self.assertEqual(
            selection_authority(
                "Which of theirs to keep is preference, not the baseline's call."
            ),
            "preference",
        )
        self.assertIsNone(selection_authority("Keep the knobs that look useful."))

    def test_no_guidance_document_claims_a_knob_has_no_effect(self) -> None:
        """The honesty rule, applied to the whole corpus rather than asserted.

        `Say "did not move the baseline", never "does not matter"` was stated
        and unenforced: inserting "report that the knob is irrelevant, useless,
        and proves it has no effect" into run-safety.md left every test green.
        A rule the package states about its own wording and does not check is a
        rule that survives exactly as long as nobody edits near it.

        This is deliberately corpus-wide and not scoped to the paragraph that
        states the rule. The overclaim is tempting wherever a result gets
        summarised, and the reporting sections are further from the rule than
        the paragraph that states it.
        """
        offenders = [
            f"{path.name}: {part}"
            for path in assistant_facing_documents()
            for part in sentences(path.read_text())
            if claims_no_effect(part)
        ]
        self.assertEqual(
            offenders,
            [],
            "a baseline can show that a knob did not move it; it cannot show "
            "that the knob has no effect, and this guidance may not say so",
        )

    def test_max_tokens_is_detected_not_predicted(self) -> None:
        """Three statements, one rule, each in the document that owns it.

        The rule this replaces was a 2048 floor that REFUSED a lower sweep. It
        was wrong for one reason that no amount of tuning the number fixes:
        reasoning headroom is not predictable - hidden thinking tokens are spent
        before the answer text and nothing declares how many - so every floor is
        a guess, and a guess that refuses breaks a configuration that would have
        been fine. 2048 tokens for an agent answering `a`, `b`, `c` or `d` is
        the reductio.

        What is true and worth keeping is WHY a low cap is dangerous, so that
        stays. Only the refusal goes, replaced by a detection: the provider
        reports `finish_reason == "length"` as a fact after the call, and the
        wrapper refuses that trial as a non-measurement rather than letting it
        be scored as a legitimate 0.

        The rule then went one step further than "do not predict a safe cap",
        to "do not set one". The hazard is a cross-run one and no single run
        could have shown it: a cap sized against the baseline's medium model is
        a cap the enhanced run's stronger or reasoning model can exceed, so the
        truncation is introduced BY this guide, between two runs, on a
        configuration the user never chose. So the wrapper sends no
        `max_tokens`, at any tier, and the user keeps every bit of their own
        ability to set one - the rule constrains us, not them.
        """
        text = RUN_SAFETY.read_text()
        start = text.index("`agent-no-varying-knobs` clears as soon as")
        section = " ".join(
            text[start : text.index("Three honesty rules", start)].split()
        )

        # 1. Composition point: no credit, no cap of ours, no floor either, and
        #    the danger still said.
        for phrase in (
            "`max_tokens` never counts either",
            "it is a resource limit, not a behaviour setting",
            "**Never introduce a cap the user did not already have",
            "carry it through verbatim",
            "the generated wrapper sends no `max_tokens` at any tier",
            "**No floor is imposed and no value is refused**",
            "a user may cap it however they like",
            "a cut-off answer scores 0 rather than low",
            "`require_untruncated_completion`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section)

        # 1b. The cross-run hazard is the reason OUR cap is worse than theirs,
        #     and the wall-clock preference is the remedy. Both stated, because
        #     a rule whose reason is unstated is a rule a later editor deletes.
        for phrase in (
            "it spans two runs",
            "the enhanced run's stronger or reasoning model can exceed",
            "**bound the clock or the trial count, never the tokens**",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section)

        # 1c. The wrapper carries no cap, and the prose beside it agrees. A
        #     rule stated in guidance and contradicted by the generated code is
        #     the contradiction class this repository keeps producing - and
        #     this is exactly where it was: the wrapper set `max_tokens` 4096
        #     while the guidance explained why caps are dangerous.
        sdk_text = SDK_EXECUTION.read_text()
        self.assertNotIn('"max_tokens"', sdk_text)
        self.assertIn("no `max_tokens` at all", sdk_text)

        # 2. The refusal is gone from the guidance, not merely unenforced -
        # a rule stated in prose and absent from the code is the contradiction
        # class this repository keeps producing.
        normalized = " ".join(text.casefold().split())
        for gone in (
            "sweep low `max_tokens` values",
            "sweeping it through anything below 2048 is refused",
            "pin it to one value at or above 2048",
        ):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, normalized)

        # 3. The scorer carries no floor to drift from.
        scripts = str(SKILL_ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        readiness = importlib.import_module("readiness")
        self.assertFalse(hasattr(readiness, "MAX_TOKENS_ANSWER_FLOOR"))
        self.assertIn("max_tokens", readiness.EXCLUDED_KNOB_REASONS)
        self.assertIn("seed", readiness.EXCLUDED_KNOB_REASONS)

    def test_the_wrapper_refuses_a_truncated_trial_rather_than_scoring_it(
        self,
    ) -> None:
        """The guard that actually prevents the original disaster.

        A strong model truncated, scored 0, and a weaker model was crowned the
        winner. Nothing enforced the "scan every trial for `finish_reason ==
        'length'`" instruction - it was a sentence in a reference, and the
        wrapper returned `response.choices[0].message.content or ""` whatever
        the provider said about why it stopped. A cut-off answer therefore
        entered the comparison as a legitimate 0.

        This asserts the guard exists, is CALLED (an uncalled checker is the
        same defect in a longer file), and raises rather than returning - the
        repository's own rule is that a failure is raised, never defaulted.
        """
        text = SDK_EXECUTION.read_text()
        functions = {}
        for source in re.findall(r"```python\n(.*?)\n```", text, re.DOTALL):
            for node in ast.parse(source).body:
                if isinstance(node, ast.FunctionDef):
                    functions[node.name] = node

        # Run it, do not read it. A guard asserted by substring passes while
        # comparing the wrong field.
        module = ast.fix_missing_locations(
            ast.Module(
                body=[
                    *sdk_wrapper_state_nodes(text),
                    functions["require_untruncated_completion"],
                    functions["call_agent"],
                ],
                type_ignores=[],
            )
        )
        current = None
        namespace = {
            "litellm": SimpleNamespace(completion=lambda **_: current),
            "build_request": lambda message, config: {},
            "require_nonzero_token_usage": lambda response: None,
            "provider_reported_cost": lambda response: 0.01,
        }
        exec(compile(module, "<truncation-guard>", "exec"), namespace)
        call_agent = namespace["call_agent"]
        guard = namespace["require_untruncated_completion"]

        def reply(finish_reason):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="a"),
                        finish_reason=finish_reason,
                    )
                ]
            )

        # The whole point: `call_agent` raises instead of handing back a
        # scoreable answer, so the trial cannot enter the comparison as a 0.
        current = reply("length")
        with self.assertRaisesRegex(RuntimeError, "truncated"):
            call_agent("task", {})
        message = ""
        try:
            guard(current)
        except RuntimeError as error:  # pragma: no cover - asserted below
            message = str(error)
        self.assertIn("not a measurement", message)
        # A bare failure is not actionable; the repair is named - and it names
        # BOTH repairs, because this wrapper sets no cap of its own. "Raise
        # this configuration's cap" was the whole message while the wrapper
        # sent `max_tokens` 4096; with no cap of ours the usual cause is the
        # model's own output limit, for which raising a cap is unperformable.
        self.assertIn("This wrapper sets no max_tokens", message)
        self.assertIn("if your own agent sets one, raise it", message)
        self.assertIn("the model's own output limit", message)
        self.assertIn("report it as excluded", message)

        # Only truncation. Every other stop reason is a real measurement, and a
        # guard that refused them would break the run it exists to protect.
        for reason in ("stop", "tool_calls", "content_filter", None):
            with self.subTest(finish_reason=reason):
                current = reply(reason)
                self.assertEqual(call_agent("task", {}), ("a", 0.01))

        # Providers that expose the choice as a mapping report the same fact.
        current = SimpleNamespace(
            choices=[
                {"message": SimpleNamespace(content="a"), "finish_reason": "length"}
            ]
        )
        with self.assertRaises(RuntimeError):
            guard(current)

        # And the post-run checklist says how a truncated trial now appears, so
        # the reader is not left checking for something that cannot arrive.
        safety = " ".join(RUN_SAFETY.read_text().split())
        self.assertIn(
            "`require_untruncated_completion` raises on `finish_reason == "
            '"length"`, so a truncated trial arrives as a failed trial rather '
            "than as a scored 0",
            safety,
        )

    def test_a_refused_trial_still_reports_the_money_it_spent(self) -> None:
        """Refusing a trial must not also lose the spend that bought it.

        Both guards raise, and `provider_reported_cost` was read AFTER them, so
        a truncated trial's cost was never read at all: the provider billed for
        every token it generated up to the cut, and the run reported $0 for it.
        The same ordering swallowed a zero-usage refusal.

        Executed rather than read, and both refusal paths are driven, because a
        reordering that fixes only the truncation branch looks identical in the
        diff to one that fixes both.
        """
        text = SDK_EXECUTION.read_text()
        functions = {}
        for source in re.findall(r"```python\n(.*?)\n```", text, re.DOTALL):
            for node in ast.parse(source).body:
                if isinstance(node, ast.FunctionDef):
                    functions[node.name] = node

        state = sdk_wrapper_state_nodes(text)
        self.assertEqual(
            [node.target.id for node in state if node.target.id.startswith("REFUSED")],
            ["REFUSED_TRIAL_COSTS"],
            "the wrapper must declare REFUSED_TRIAL_COSTS exactly once",
        )
        module = ast.fix_missing_locations(
            ast.Module(body=[*state, functions["call_agent"]], type_ignores=[])
        )
        current = None
        refuse: str | None = None

        def truncation_guard(response):
            if refuse == "truncated":
                raise RuntimeError("The provider truncated this completion")

        def usage_guard(response):
            if refuse == "usage":
                raise RuntimeError("did not report nonzero token usage")

        namespace = {
            "litellm": SimpleNamespace(completion=lambda **_: current),
            "build_request": lambda message, config: {},
            "require_nonzero_token_usage": usage_guard,
            "require_untruncated_completion": truncation_guard,
            "provider_reported_cost": lambda response: 0.02,
        }
        exec(compile(module, "<refused-trial-cost>", "exec"), namespace)
        call_agent = namespace["call_agent"]
        spent = namespace["REFUSED_TRIAL_COSTS"]
        current = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="a"))]
        )

        # A scored trial is not refused spend. It is already in the comparison,
        # and counting it here would double it.
        self.assertEqual(call_agent("task", {}), ("a", 0.02))
        self.assertEqual(spent, [])

        for reason in ("truncated", "usage"):
            with self.subTest(refused=reason):
                refuse = reason
                before = len(spent)
                with self.assertRaises(RuntimeError):
                    call_agent("task", {})
                self.assertEqual(
                    spent[before:],
                    [0.02],
                    f"a trial refused for {reason} was billed and its cost was "
                    "dropped, so the run reports $0 for money it spent",
                )
        refuse = None

        # An unknown cost is recorded as unknown, not as zero. Appending a
        # placeholder would let a run with no cost metadata report refused spend
        # of $0.00, which is a measurement it never made.
        namespace["provider_reported_cost"] = lambda response: None
        refuse = "truncated"
        before = len(spent)
        with self.assertRaises(RuntimeError):
            call_agent("task", {})
        self.assertEqual(spent[before:], [])

        # And the post-run checklist asks for the number, or nothing reads it.
        safety = " ".join(RUN_SAFETY.read_text().split())
        self.assertIn("report `REFUSED_TRIAL_COSTS` beside the total", safety)

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
        skill_text = " ".join(SKILL.read_text().casefold().split()).replace(" > ", " ")
        self.assertIn("run free readiness research", skill_text)
        self.assertIn(
            "score and setup—not agent accuracy or an optimization result", skill_text
        )
        self.assertIn("i explain details", skill_text)
        self.assertIn("only if action is needed", skill_text)
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
        # Re-anchored on #171's wording: the README no longer says "`paid run
        # blocked` is the headline", because #171 replaced that headline with a
        # `BLOCKER` line under the score. The gloss this reads is the same
        # paragraph, found by the label it now leads with.
        gloss = readme.split("`fix before paid run` means", 1)[1].split(
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
        # The construction rule now states TWO numbers - the generated total and
        # the tuning rows inside it - because the walkthrough reserves a
        # held-out set at creation time. Both are read from the rule, and the
        # rule is made to agree with itself, so neither can drift from the other
        # or from the restatements swept below.
        default = re.search(
            r"create (\d+) examples by default: (\d+) tuning rows", dataset_text
        )
        self.assertIsNotNone(default, "the generated dataset size is no longer stated")
        generated_total = int(default.group(1))
        expected = int(default.group(2))

        # The held-out split's size and composition, also read from the rule
        # rather than pinned here. Ten rows at 2/3/3/2 is settled; this reads it
        # so that the sweep below can tell a held-out breakdown apart from a
        # tuning one instead of demanding every breakdown sum to the same total.
        reserve = re.search(
            r"Reserve (\d+) held-out rows "
            r"\((\d+) easy, (\d+) medium, (\d+) hard, (\d+) very hard\)",
            dataset_text,
        )
        self.assertIsNotNone(
            reserve, "the held-out split's composition is no longer stated"
        )
        held_out = int(reserve.group(1))
        held_out_bands = [int(value) for value in reserve.groups()[1:]]
        self.assertEqual(
            sum(held_out_bands),
            held_out,
            "the held-out split's own breakdown does not sum to its stated size",
        )
        self.assertEqual(
            generated_total,
            expected + held_out,
            f"the rule builds {generated_total} rows but describes {expected} "
            f"tuning plus {held_out} held-out, which is {expected + held_out}",
        )

        counted = re.compile(
            r"(\d+)\s+(?:tuning rows|tuning examples|varied synthetic cases"
            r"|rows by default)"
        )
        statements: list[tuple[str, int]] = []
        for path in assistant_facing_documents():
            for match in counted.finditer(path.read_text()):
                statements.append((path.name, int(match.group(1))))
        # The rule plus its five restatements. Pinned so that DELETING a
        # restatement is a decision someone makes, not a way for this sweep to
        # quietly cover less than it did. Raised from four when the held-out
        # split arrived - the sampling rule that draws the tuning rows from the
        # tuning split states the count a fifth time - and from five when the
        # row-level sanity check arrived, whose section states how many rows it
        # reads. Each new statement is welded here rather than left uncovered.
        self.assertEqual(
            len(statements),
            6,
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
        #
        # Two breakdowns are legitimate now, not one: the tuning rows' and the
        # held-out set's. Requiring every breakdown to sum to the tuning count
        # would report the settled ten-row split as an error - the split is
        # correct and the guard would be wrong - so each breakdown is matched
        # against whichever set it describes. A held-out-sized one must also BE
        # the settled composition, which is stricter than the old sweep, not
        # looser: before, the ten-row split escaped this check entirely by
        # writing its bands without the word "and".
        bands = re.compile(
            r"(\d+) easy,\s*(\d+) medium,\s*(\d+) hard,?(?: and)? (\d+) very[ -]hard"
        )
        breakdowns = [
            (path.name, [int(value) for value in match.groups()])
            for path in assistant_facing_documents()
            for match in bands.finditer(" ".join(path.read_text().split()))
        ]
        self.assertTrue(breakdowns, "the difficulty breakdown is no longer stated")
        self.assertTrue(
            any(sum(counts) == expected for _, counts in breakdowns),
            "no document states the tuning rows' difficulty breakdown",
        )
        self.assertTrue(
            any(counts == held_out_bands for _, counts in breakdowns),
            "no document states the held-out split's difficulty breakdown",
        )
        for name, counts in breakdowns:
            with self.subTest(document=name, breakdown=counts):
                if sum(counts) == held_out:
                    self.assertEqual(
                        counts,
                        held_out_bands,
                        f"{name} states a {held_out}-row breakdown of {counts}, "
                        f"but the held-out split is {held_out_bands}",
                    )
                    continue
                self.assertEqual(
                    sum(counts),
                    expected,
                    f"{name}'s difficulty breakdown sums to {sum(counts)}, "
                    f"which is neither the {expected} tuning rows the rule "
                    f"builds nor the {held_out} it holds out",
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
        # The positive half: the rule may not be satisfied by going silent.
        # It used to read `assertIn("unmeasured defensive floor")`, because the
        # owning statement recommended 2048/4096 and had to admit the numbers
        # were a judgement. The branch that removed the floor removed the
        # numbers themselves, so there is no longer a judgement to be honest
        # about - and that assertion would have been satisfiable only by
        # reintroducing the floor this package now refuses to impose. What
        # replaces it is the same obligation against the current statement:
        # run-safety.md must still SAY that no floor is imposed and why, so
        # deleting the whole paragraph fails here exactly as deleting the
        # honesty did before.
        self.assertIn("no floor is imposed and no value is refused", owner)
        self.assertIn("reasoning headroom is not predictable", owner)

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
                ratio = self._threshold_in(sentence)
                if ratio is not None:
                    offenders.append(
                        f"{document.relative_to(ROOT).as_posix()}: "
                        f"{ratio!r} in {sentence!r}"
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

        # Measured before this probe existed: `_GRID_TO_RANDOM` reaches five
        # sentences in the corpus and `_A_RATIO` fires on none of them. So the
        # violation half of this guard had never once matched anything, and an
        # empty `offenders` was equally the answer for "the prose is honest"
        # and for "this regex can no longer see a threshold". The deleted
        # sentence is the first probe; the other two are the spellings the
        # docstring above says will come next, neither of which the original
        # phrase-ban would have caught.
        for planted in (
            "Above roughly twenty configurations per allowed trial, move a "
            "preserved baseline from `grid` to `random`.",
            "Switch from grid to random above 40 configurations per trial.",
            "Use grid, then random at ten times the trial cap.",
            "Prefer grid below 20 configurations per trial and random above it.",
        ):
            with self.subTest(planted=planted):
                self.assertIsNotNone(
                    self._threshold_in(planted),
                    "a numeric grid-to-random crossover this guard cannot see",
                )
        # And the qualitative rule the guidance is supposed to state, plus a
        # ratio in a sentence about something else entirely - neither is an
        # offence, or the guard is a false red that teaches authors to stop
        # writing the rule at all.
        for innocent in (
            "The baseline pins `grid`; never pin `random` on the connected search.",
            'Keep `algorithm="auto"` here, and never pin `grid` or `random`.',
            "The knob-count sub-score is damped above 20 configurations per trial.",
        ):
            with self.subTest(innocent=innocent):
                self.assertIsNone(
                    self._threshold_in(innocent),
                    "the guard reads an honest sentence as a threshold",
                )

    def _threshold_in(self, sentence: str) -> str | None:
        """The ratio stated in a grid-versus-random sentence, if it states one."""
        if not self._GRID_TO_RANDOM.search(sentence):
            return None
        ratio = self._A_RATIO.search(sentence)
        return None if ratio is None else ratio.group(0)

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

        # Measured before this probe existed: this pattern matches zero times
        # across the whole corpus, so `labelled == []` was being asserted about
        # text the regex has never once fired on. A guard that has never
        # matched anything is indistinguishable from a guard that cannot. The
        # first probe is the label that actually leaked; the rest are the
        # family the docstring says comes next.
        for planted in (
            "Artifact-2 template A: show this after registration.",
            "Artifact 3 - the closing summary.",
            "artifact-11 goes here",
            "Template B: paste this block.",
        ):
            with self.subTest(planted=planted):
                self.assertTrue(
                    self._AUTHORING_LABEL.search(planted),
                    "a drafting label this guard cannot see",
                )
        # The words themselves are ordinary and the guidance uses both, so the
        # shape has to be what fails. A false red here would be paid for in
        # prose nobody is allowed to write.
        for innocent in (
            "the run-plan template and the artifact it writes",
            "Use the template in `assets/run-plan.md`.",
            "Stage 2 produces one artifact the user keeps.",
        ):
            with self.subTest(innocent=innocent):
                self.assertIsNone(
                    self._AUTHORING_LABEL.search(innocent),
                    "the guard flags prose that carries no drafting label",
                )

    def test_the_card_labels_the_readme_documents_are_the_ones_it_prints(
        self,
    ) -> None:
        """README named three labels; the code prints four.

        `BLOCKER` is the headline flag, and every blocking condition beneath it
        prints `FIX BEFORE PAID RUN` - the line that actually tells the reader
        what to do, and the only one the public explanation omitted.

        The headline was `PAID RUN BLOCKED` until #171 moved the holding onto
        its own line under the score, on the grounds that a tag beside the band
        reads as the band being disbelieved. `BLOCKER` is what the card prints
        now, so it is what this checks; the pairing - README says what the code
        prints - is unchanged.
        """
        readme = (ROOT / "README.md").read_text()
        card_source = _READINESS.read_text()
        for label in (
            "BLOCKER",
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
        """The opening script lives where an installed run can actually read it.

        It was written in GUIDE.md and referenced from SKILL.md, and GUIDE.md is
        not part of what the Agent Skill installer copies - so the installed
        skill told the assistant to open with a document it did not have.
        """
        guide = " ".join((ROOT / "GUIDE.md").read_text().casefold().split())
        skill = " ".join(SKILL.read_text().casefold().split())
        self.assertIn("welcome to traigent onboarding!", skill)
        for stage in ("inspect", "readiness", "baseline", "optimize", "results"):
            self.assertIn(f"**{stage}**", skill)
        self.assertIn("stage <n>/5", skill)
        self.assertIn("with measured numbers when available", skill)
        self.assertIn("readiness score, rows checked, calls/trials, cost", skill)
        self.assertIn("finished stages as compact checkmarks", skill)
        # GUIDE.md keeps the cloned-repo reader pointed at it, and states it
        # only once: a second copy is a rule that can be changed in one place.
        self.assertIn('five-stage journey under "opening message"', guide)

        # "Only once" is asserted over the tracked tree, not over GUIDE.md.
        # Checking the one document the script just left proves it left; it says
        # nothing about README.md, `templates/` or `reports/`, and README.md is
        # the most-read file this repository publishes and already describes the
        # journey. A second copy there would be exactly the defect this branch
        # removed, in the file most likely to be edited by somebody who never
        # opens SKILL.md.
        homes = sorted(
            name
            for name in tracked_files()
            if not name.startswith("tests/")
            and "welcome to traigent onboarding!"
            in " ".join((ROOT / name).read_text(errors="ignore").casefold().split())
        )
        self.assertEqual(
            homes,
            ["skills/traigent-first-run/SKILL.md"],
            f"the opening script is written out in {homes}. It has one home - "
            "the installed skill, which is the only reader that has to perform "
            "it - and everything else points there.",
        )

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

    # Every guided-flow stage, listed so that adding one is a decision about
    # the opening promise rather than a silent change to the journey. A stage
    # the customer never notices still belongs here; what it may not do is
    # appear without anyone asking whether the promise should have said so.
    GUIDED_FLOW_STAGES = (
        "1. inspect quietly",
        "2. show readiness once",
        "3. complete the system",
        "4. validate components locally",
        "5. prepare the environment and finish free checks",
        "6. approve and run the baseline",
        "7. run the honest comparison",
        "8. verify and report",
    )

    # What the run asks of the customer, or hands them, in the order it happens
    # - paired with the numbered promise item that has to name it.
    #
    # Three of these were absent from the promise while the flow performed them
    # anyway: the SDK install, the account request, and the closing skills
    # handover. The account request is the costly one. It lands mid-run, after
    # a paid result, and a customer who was not told finds out at the moment
    # trust is either kept or lost - so the item number is pinned, not merely
    # the wording: promising the account in item 4 and not item 3 is the claim
    # that a real result arrives before anything has to be created.
    CUSTOMER_JOURNEY = (
        # (what the flow does, promise item, words that item must carry)
        ("perform safe, read-only discovery", 1, "inspect"),
        ("render the initial real-world readiness board", 2, "readiness"),
        ("install the exact declared dependencies", 3, "install the sdk"),
        ("### 6. approve and run the baseline", 3, "measure today's setup"),
        # The promise says ACCOUNT, so the flow phrase has to be the sentence
        # that establishes one. Pinning "ask for the traigent key" instead
        # left the promise's costliest item - create an account, mid-run,
        # after a paid result - evidenced by a sentence about a key.
        ("before being asked to create an account", 4, "traigent account"),
        ("### 8. verify and report", 5, "compare the runs"),
        ("hand over the traigent optimization skills", 5, "traigent skills"),
    )

    @staticmethod
    def _promise_items() -> dict[int, str]:
        """The numbered opening, as items, from SKILL.md's own blockquote.

        Bounded by the blockquote itself rather than by the sentence that
        happens to follow it: the trailing prose under this section is a
        mandate that can be reworded, and a marker string that stops matching
        silently widens this block to the rest of the file, where any other
        numbered list would be read as promise items.

        SKILL.md, not GUIDE.md. #154 deleted the blockquote from GUIDE.md and
        left a pointer, because the opening script has to be self-contained in
        the document the assistant actually loads; #164 edited three clauses
        INSIDE that same blockquote. Either merge order fails loudly, which is
        correct - a promise with two homes is one that can be changed in one of
        them. The resolution is one home: #164's three clauses moved into
        SKILL.md's "## Opening message", and this reads them there. Reading
        GUIDE.md would now find a pointer and no items at all.
        """
        quoted: list[str] = []
        for raw in (SKILL.read_text().split("## Opening message", 1)[1]).splitlines():
            if raw.startswith(">"):
                quoted.append(raw)
            elif quoted:
                break
        items: dict[int, list[str]] = {}
        current: int | None = None
        for raw in quoted:
            line = raw.lstrip(">").strip()
            numbered = re.match(r"(\d+)\.\s+(.*)", line)
            if numbered:
                current = int(numbered.group(1))
                items[current] = [numbered.group(2)]
            elif not line:
                # A blank quote line closes the list; without this the trailer
                # paragraph folds into the last item and every phrase below
                # would pass from the wrong place.
                current = None
            elif current is not None:
                items[current].append(line)
        return {
            number: " ".join(" ".join(parts).casefold().split())
            for number, parts in items.items()
        }

    def test_the_opening_promise_names_every_stage_the_customer_reaches(self) -> None:
        """The promise is welded to the flow, in both directions.

        A promise is the first thing a customer reads and the only description
        of the run they get before agreeing to it, so the failure mode is not a
        wrong sentence - it is a true one that stops being complete when a
        stage is added below it. Naming a step is not explaining it: these
        assertions demand the word, and deliberately not the mandate, which
        SKILL.md and run-safety.md own.
        """
        skill = " ".join(SKILL.read_text().casefold().split())
        items = self._promise_items()

        self.assertEqual(
            sorted(items), [1, 2, 3, 4, 5], f"unexpected promise items: {items}"
        )
        # The promise and the progress markers count the same journey. A sixth
        # promise item with `Stage <n>/5` still printed underneath it is a
        # customer told two different things about where they are.
        denominators = {
            match.group(1)
            for text in (
                skill,
                " ".join(
                    (SKILL_ROOT / "references" / "glossary.md")
                    .read_text()
                    .casefold()
                    .split()
                ),
            )
            for match in re.finditer(r"stage (?:<n>|\d)/(\d+)", text)
        }
        self.assertEqual(denominators, {str(len(items))})

        headings = tuple(
            " ".join(line[4:].casefold().split())
            for line in SKILL.read_text().splitlines()
            if line.startswith("### ")
        )
        self.assertEqual(
            headings,
            self.GUIDED_FLOW_STAGES,
            "the guided flow gained, lost, or reordered a stage. Classify it "
            "here, and if the customer does or receives anything in it, name "
            "it in GUIDE.md's opening promise as well.",
        )

        positions: list[int] = []
        for flow_phrase, item, promise_phrase in self.CUSTOMER_JOURNEY:
            with self.subTest(step=promise_phrase):
                # Counted, not merely found: the ordering check below reads
                # `index`, which is the FIRST occurrence. A phrase that also
                # appears in an earlier stage would order the journey by
                # wherever it happened to be mentioned first rather than by
                # where the step runs, and the check would still pass.
                self.assertEqual(
                    skill.count(flow_phrase),
                    1,
                    "the flow no longer does this exactly once, so the "
                    "promise is either promising something that does not "
                    "happen or being ordered by the wrong occurrence",
                )
                self.assertIn(
                    promise_phrase,
                    items[item],
                    f"promise item {item} does not name this step",
                )
                positions.append(skill.index(flow_phrase))
        # The promise has to tell the journey in the order it is lived, or the
        # ordering it asserts is decoration.
        self.assertEqual(
            positions,
            sorted(positions),
            "the promise lists these steps in an order the flow does not run "
            "them in",
        )
        self.assertEqual(
            [item for _flow, item, _phrase in self.CUSTOMER_JOURNEY],
            sorted(item for _flow, item, _phrase in self.CUSTOMER_JOURNEY),
        )

    def test_the_promise_keeps_the_two_mandates_that_bound_it(self) -> None:
        """The opening promise carries its own scope, and cannot lose it quietly.

        Rewriting the five numbered items is a change to what the run
        advertises; deleting the two sentences around them is a change to what
        the run is ALLOWED to do, and the second is invisible in a diff that
        looks like a copy edit. Both were dropped while this branch rewrote the
        items above them, which is how the class works: the sentences nobody is
        editing are the ones that leave.

        `Stop only for:` is a list of exceptions, so it needs the rule it
        excepts from on the same page - without it the list reads as the whole
        approval policy, which is the opposite of what it says. And the trailer
        is what makes the five items a sequence rather than a menu.

        Neither is a second home for a mandate. `SKILL.md` owns "perform safe,
        read-only discovery without asking for approval" and `run-safety.md`
        owns what the closing recommendation may claim; both are asserted here
        so that if either home moves, this pin fails rather than becoming the
        only surviving statement of a rule.
        """
        guide = " ".join((ROOT / "GUIDE.md").read_text().casefold().split())
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())

        for phrase in (
            "proceed with read-only inspection after stating the plan",
            "do not make the user approve safe discovery",
            "stop only for:",
        ):
            with self.subTest(guide=phrase):
                self.assertIn(phrase, guide)
        # The trailer moved with the blockquote it trails. #154 took the
        # promise out of GUIDE.md so the opening script is self-contained in
        # the document the assistant loads, and this sentence is the one that
        # makes the five items a sequence rather than a menu - so it is pinned
        # where the items now are, not where they used to be. Asserting it
        # against GUIDE.md would only be satisfiable by restoring the second
        # home this whole check exists to prevent.
        self.assertIn("baseline evidence decides the next step", skill)
        self.assertIn(
            "perform safe, read-only discovery without asking for approval",
            skill,
        )
        self.assertIn("never promise improvement", safety)

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
            "18 tuning rows by default",
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

    # The two rungs the credential handoff actually has, each matched by the
    # thing that makes it distinguishable rather than by a whole sentence: a
    # wording test would pass against a third rung inserted between them, which
    # is the failure this pair exists to prevent.
    _HANDOFF_RUNGS = (
        ("open it with the available graphical handler", "graphical session"),
        ("print the absolute path and stop", "print the absolute path as the fallback"),
    )
    # The removed middle rung: an editor or IDE resolved from the project. Two
    # spellings were matched at first - `fall back to the ide` and "associated
    # with the project directory" - which closed the shape that broke rather
    # than the class. Measured, "Otherwise open it in the project's own editor."
    # passed both. So the signature is the CLAIM: an editor or IDE within a
    # clause of the thing it is supposedly resolved from, in either order,
    # because nothing here resolves a project to an editor however it is worded.
    _MIDDLE_RUNG = re.compile(
        r"\b(?:ide|editor)\b[^.]{0,80}?\b(?:project|workspace|repository|repo"
        r"|directory|folder)\b"
        r"|\b(?:project|workspace|repository|repo|directory|folder)\b[^.]{0,80}?"
        r"\b(?:ide|editor)\b",
        re.IGNORECASE,
    )
    # What performs the open, and what to do when nothing can. Naming any of
    # these IS stating the mechanism, whatever verb surrounds it - which is the
    # class the two-spelling regex above could not reach. Re-adding a first rung
    # ("Open it using the first available GUI editor.") restores a mechanism to
    # a document that must not carry one, and measured, the earlier check passed
    # that too: it only ever looked for the rung that had been deleted.
    #
    # The opening VERB is deliberately absent. "Before opening it, require mode
    # `0600`" is a rule about the file, not about who opens it, and a check that
    # flagged it would push the mode rule out of the document that owns it.
    _OPENING_AGENT = re.compile(
        r"\bgui\b|\bgraphical\b|\bheadless\b|\bxdg-open\b|\bstart-process\b"
        r"|\bopener\b|\beditor\b|\bide\b|\bdesktop\b|\bwindow manager\b",
        re.IGNORECASE,
    )
    # ...but only where the credential file is the subject. `glossary.md` calls
    # the coding agent "the assistant running in your editor or terminal", which
    # names an editor and has nothing to do with this handoff.
    _CREDENTIAL_FILE = re.compile(
        r"`?\.env`?\b|credential (?:file|handoff|source)|handoff file"
        r"|traigent_api_key",
        re.IGNORECASE,
    )

    @classmethod
    def credential_opening_mechanism(cls, documents: dict[str, str]) -> dict[str, list]:
        """Every document that says HOW the credential file gets opened."""
        found: dict[str, list[str]] = {}
        for name, text in documents.items():
            for sentence in prose_statements(text):
                if not cls._CREDENTIAL_FILE.search(sentence):
                    continue
                if cls._OPENING_AGENT.search(sentence):
                    found.setdefault(name, []).append(sentence)
        return found

    def test_the_credential_handoff_has_two_rungs_and_exactly_one_home(self) -> None:
        """The middle rung named a mechanism nothing in this repository has.

        The chain read: graphical handler, else the IDE or editor associated
        with the project directory, else print the path. Nothing resolves a
        project directory to an IDE - not `run-safety.md`, which owns the
        handoff and states the two rungs it can actually perform, and not any
        script here. So the middle rung was an instruction the assistant could
        only guess at, in the one step where guessing means a secret is entered
        somewhere nobody named. It was removed rather than implemented: the
        owner's call, and the honest one, since the graphical handler already
        covers every case an IDE would have.

        The second half of the check is why it was three rungs in two places to
        begin with. `GUIDE.md` and `SKILL.md` each restated the chain that
        `run-safety.md` owns - the same rule in three documents for one
        audience - so removing the rung from two of them would have left the
        next editor free to put it back in either. CLAUDE.md's "one decision,
        one home" is the rule; this asserts it for this rule: the mechanism is
        stated where it is performed, `SKILL.md` points at that reference, and
        `GUIDE.md` says nothing about how the file gets opened.
        """
        raw = instructional_documents()
        documents = {
            name: " ".join(text.casefold().split()) for name, text in raw.items()
        }
        owner = RUN_SAFETY.relative_to(ROOT).as_posix()

        # 1. The middle rung is gone, everywhere - including from the owner.
        reintroduced = sorted(
            name for name, text in documents.items() if self._MIDDLE_RUNG.search(text)
        )
        self.assertEqual(
            reintroduced,
            [],
            "the credential handoff's middle rung is back: an IDE or editor "
            "resolved from the project directory, which nothing here can do",
        )

        # 2. Each surviving rung is stated once, in the document that owns it.
        for label, phrase in self._HANDOFF_RUNGS:
            with self.subTest(rung=label):
                homes = sorted(
                    name for name, text in documents.items() if phrase in text
                )
                self.assertEqual(
                    homes,
                    [owner],
                    f"the '{label}' rung is stated in {homes} - it belongs only "
                    "in the reference that performs the handoff",
                )

        # 3. And the owner really does carry both, in order, so "one home"
        # cannot be satisfied by the rule having no home at all.
        rules = documents[owner]
        positions = [rules.index(phrase) for _label, phrase in self._HANDOFF_RUNGS]
        self.assertEqual(positions, sorted(positions))

        # 4. No document but the owner says how the file is opened, in any
        # words. The previous revision checked GUIDE.md against five spellings,
        # which is the same defect one level up: it closed the two sentences
        # that had been there rather than the class, so "Otherwise open it in
        # the project's own editor" and a re-added "Open it using the first
        # available GUI editor" both passed - the second being a rung the branch
        # had just deleted. Naming an opening agent at all, in a sentence about
        # the credential file, is what fails now.
        stated = self.credential_opening_mechanism(raw)
        self.assertEqual(
            sorted(stated),
            [owner],
            "the credential file's opening mechanism is stated in "
            f"{sorted(stated)}. It has one home - the reference that performs "
            "the handoff - and every other document points there: "
            + " || ".join(
                f"{name}: {sentence}"
                for name, sentences in sorted(stated.items())
                if name != owner
                for sentence in sentences
            ),
        )
        # SKILL.md carries the pointer that replaced the mechanism, so "no
        # mechanism here" is not satisfied by dropping the subject entirely.
        self.assertIn(
            "follow that reference's single ordered handoff",
            documents[SKILL.relative_to(ROOT).as_posix()],
        )

    def test_the_handoff_mechanism_check_sees_a_rung_written_any_way(self) -> None:
        """Invented documents, because the tree only ever holds the fixed state.

        Running the check over the repository proves the fix, not the check.
        Each string below was measured against the previous revision of this
        guard: every one in the first group PASSED it, which is why that
        revision could be satisfied by a paraphrase of what it had just removed.
        """
        for label, planted in (
            # The reviewer's paraphrase of the deleted middle rung.
            (
                "paraphrased middle rung",
                "Otherwise open the `.env` in the " "project's own editor.",
            ),
            # The deleted middle rung, worded as the repository once had it.
            (
                "original middle rung",
                "If that is unavailable, open the `.env` "
                "with the IDE or editor associated with the chosen project "
                "directory.",
            ),
            # A FIRST rung put back into a document that must not carry one.
            # The old check looked only for the rung that had been deleted, so
            # restoring a different one was invisible.
            (
                "restored first rung",
                "Open the `.env` using the first available " "GUI editor.",
            ),
            (
                "restored fallback rung",
                "If headless, print the full `.env` path " "and stop.",
            ),
            (
                "windows spelling",
                "Hand off the credential file with " "`Start-Process`.",
            ),
            ("posix spelling", "Launch `xdg-open` on the credential file."),
            (
                "desktop spelling",
                "On a desktop session, pop the `.env` open for " "the user.",
            ),
        ):
            with self.subTest(planted=label):
                self.assertEqual(
                    sorted(self.credential_opening_mechanism({"GUIDE.md": planted})),
                    ["GUIDE.md"],
                    f"a {label} in GUIDE.md is invisible to this check, so the "
                    "mechanism this branch gave one home can be given a second "
                    "just by wording it differently",
                )

        # The other direction. Each of these is a legitimate statement ABOUT the
        # credential file that names no opening agent, and a check that flagged
        # one would push the rule it belongs to out of the document that owns
        # it - which is how the mechanism ended up restated in three documents
        # in the first place.
        for label, legal in (
            ("the mode rule", "Before opening it, require mode `0600` on POSIX."),
            (
                "the pointer",
                "`references/run-safety.md` selects the credential "
                "handoff file and owns every rule about it.",
            ),
            ("the when-to-open rule", "Stop once only when a key is truly " "missing."),
            (
                "the coding agent",
                "Your agent is the assistant running in your " "editor or terminal.",
            ),
            (
                "the tracked-file check",
                "Run the git-tracked-file safety check "
                "on the `.env` before secret entry.",
            ),
        ):
            with self.subTest(legal=label):
                self.assertEqual(
                    self.credential_opening_mechanism({"GUIDE.md": legal}),
                    {},
                    f"{label} is not a statement of the opening mechanism; "
                    "flagging it teaches authors to route around this check",
                )

        # `_MIDDLE_RUNG` runs over whole documents rather than over sentences
        # about the credential file, because the rung it names describes a
        # mechanism nothing here implements - so it must not exist anywhere, in
        # any context, whether or not the sentence around it mentions `.env`.
        for label, planted in (
            (
                "as first written",
                "fall back to the IDE or editor associated "
                "with the chosen project directory",
            ),
            ("paraphrased", "otherwise open it in the project's own editor"),
            ("reordered", "the editor the workspace is already open in"),
            ("renamed", "hand it to the repository's configured IDE"),
        ):
            with self.subTest(middle_rung=label):
                self.assertTrue(
                    self._MIDDLE_RUNG.search(planted),
                    f"the middle rung written {label} is invisible, so removing "
                    "it from three documents did not stop it coming back",
                )
        for legal in (
            "the assistant running in your editor or terminal",
            "keep every tool's working directory at the user's project root",
        ):
            with self.subTest(legal=legal):
                self.assertIsNone(self._MIDDLE_RUNG.search(legal))

    def test_the_one_home_corpus_is_what_this_repository_publishes(self) -> None:
        """A one-home check is only as good as the set of documents it opens.

        The earlier corpus was `assistant_facing_documents()`, which is the
        skill bundle plus GUIDE.md. `README.md` is not in it - the most-read
        file in a public repository - nor are `AGENTS.md`, `CLAUDE.md` or
        `templates/`. Measured, the deleted rung pasted verbatim into README.md
        passed the previous revision of the check above.
        """
        published = instructional_documents()
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--", "*.md"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        self.assertEqual(
            sorted(published),
            sorted(
                name for name in listed if not name.startswith(("tests/", "reports/"))
            ),
            "the corpus has drifted from what git publishes",
        )
        for expected in ("README.md", "AGENTS.md", "CLAUDE.md", "GUIDE.md"):
            with self.subTest(document=expected):
                self.assertIn(expected, published)
        # `templates/` was the directory this asserted, and #192 deleted it:
        # the two compatibility templates in it were a second home for the run
        # plan and the preflight script, which is the duplicate this corpus
        # exists to find. `skills/` is asserted instead - a directory that is
        # still published, so the check still fails if the corpus narrows.
        self.assertTrue(
            any(name.startswith("skills/") for name in published),
            "nothing under skills/ is in the corpus",
        )

    def test_the_assistant_facing_corpus_is_what_the_skill_bundle_publishes(
        self,
    ) -> None:
        """The third corpus, and the only one nothing anchored.

        The two `git ls-files` corpora above each assert what they contain, so
        a narrowing fails once and loudly. `assistant_facing_documents()` -
        which more checks in this file walk than either of them - asserted
        nothing. It is built from two `.glob("*.md")` calls, and a glob narrows
        SILENTLY: rename a reference, add a document under an extension nobody
        thought about, or break the path, and the list simply gets shorter.

        That is the shape this whole family of checks exists to refuse. An
        empty or narrowed corpus turns every `assertEqual(offenders, [])` built
        on it into a green tick over a document it never opened - measured, ten
        checks in this file go vacuous together, and none of them would say so.
        So the corpus is compared against what git actually publishes, in the
        four places the helper claims to read, and a document added beside them
        fails here until someone decides whether the assistant reads it.
        """
        corpus = [
            path.relative_to(ROOT).as_posix() for path in assistant_facing_documents()
        ]
        self.assertEqual(
            len(corpus),
            len(set(corpus)),
            "the corpus lists a document twice, so every check that joins it "
            "weighs that document twice",
        )
        listed = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "ls-files",
                "--",
                "GUIDE.md",
                f"{SKILL.relative_to(ROOT).as_posix()}",
                f"{(SKILL_ROOT / 'references').relative_to(ROOT).as_posix()}/*.md",
                f"{(SKILL_ROOT / 'assets').relative_to(ROOT).as_posix()}/*.md",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        self.assertEqual(
            sorted(corpus),
            sorted(listed),
            "the assistant-facing corpus has drifted from what the skill "
            "bundle publishes. Every check that sweeps it is silently scoped "
            "to whatever this glob still finds.",
        )
        # Named individually as well, because the equality above is satisfied
        # by both sides narrowing together - a reference deleted from the tree
        # and from the corpus in one commit. Each of these is a document some
        # check in this file has a rule about.
        for expected in (
            "GUIDE.md",
            "skills/traigent-first-run/SKILL.md",
            "skills/traigent-first-run/references/run-safety.md",
            "skills/traigent-first-run/references/sdk-execution.md",
            "skills/traigent-first-run/references/evaluation-and-dataset.md",
            "skills/traigent-first-run/references/glossary.md",
            "skills/traigent-first-run/references/component-creation.md",
            "skills/traigent-first-run/assets/run-plan.md",
        ):
            with self.subTest(document=expected):
                self.assertIn(expected, corpus)
        # `conversation_contract_documents()` wraps this list, so it inherits
        # both the hole and the fix; asserted rather than assumed.
        contract = [
            path.relative_to(ROOT).as_posix()
            for path in conversation_contract_documents()
        ]
        self.assertTrue(
            set(corpus) <= set(contract),
            "the conversation-contract corpus no longer covers every "
            "assistant-facing document",
        )

    # Where the user is sent, and how they get there. Both belong to the
    # reference that performs the handoff; GUIDE.md's paragraph points at it and
    # states neither. Addresses are matched as a shape rather than by hostname,
    # because the defect is naming *a* destination here, whichever one it is.
    _NAMES_A_DESTINATION = re.compile(
        r"https?://|\btraigent\.ai\b|\bregistration link\b|\bregister\b"
    )

    def test_the_guide_sends_the_reader_to_the_reference_and_names_no_address(
        self,
    ) -> None:
        """The same paragraph, and the same rule, from the other direction.

        This one has a history that is not the rung's. GUIDE.md used to promise
        `references/run-safety.md` held "the clickable registration link", and
        #148 established that there is no single link to promise: which address
        a user gets depends on which of four account states they are in, and a
        user with no access code who is handed the portal's register page is
        handed a page that refuses them. #148 changed this sentence to point at
        the reference for "which address each account state gets" instead.

        Nothing held that. #148's own checks are on `run-safety.md`, where the
        addresses live, so the GUIDE.md half was pinned by nothing - verified by
        restoring the old sentence on trunk, where the full suite stays green.

        The branch that made that concrete has since moved, and the record
        should say so rather than keep claiming a conflict that no longer
        happens. #154 was based on 6316067, before #148, so its copy of this
        file still carried the promise and genuinely collided with the sentence
        this branch rewrites. #154 has since been rebased onto this trunk; at
        the current heads `git merge-tree` auto-merges GUIDE.md and SKILL.md in
        both directions, and the only conflict is the generated behaviour lock,
        which `tools/relock.py` rewrites. So the hazard is not live today. That
        is the argument for a check rather than a narrative: a rebase retired it
        without anyone deciding to, and a rebase can bring it back the same way.

        So the shape is asserted rather than the sentence: GUIDE.md names no
        address, of any form, and keeps the pointer that replaced the promise.
        The rule is the same "one decision, one home" the rung check above
        applies to the mechanism - the destination is stated where the handoff
        is performed, and the entry point sends the reader there.
        """
        guide = " ".join((ROOT / "GUIDE.md").read_text().casefold().split())
        named = sorted(set(self._NAMES_A_DESTINATION.findall(guide)))
        self.assertEqual(
            named,
            [],
            "GUIDE.md names a registration destination; which address a user "
            "gets depends on their account state, so a single one stated here "
            "is wrong for three of the four (#148)",
        )
        self.assertIn("for which address each account state gets", guide)

    # When the credential file may be opened at all: once, and only for a key
    # that is genuinely missing. Matched as a shape - an opening or stopping
    # verb, scoped by "only"/"never"/"not", against a key described as missing,
    # already held, or a duplicate - rather than by any one sentence. This
    # repository has spelled the rule at least three ways, so a check on one
    # spelling would pass while a second document carried another.
    _WHEN_THE_FILE_IS_OPENED = re.compile(
        r"\b(?:open|reopen|stop)\w*\b[^.]{0,120}?\b(?:only|never|not)\b[^.]{0,80}?"
        r"\b(?:missing|already|duplicate)\b"
        r"|"
        r"\b(?:only|never|do not|not)\b[^.]{0,60}?\b(?:open|reopen|stop)\w*\b"
        r"[^.]{0,80}?\b(?:missing|already|duplicate)\b"
    )

    def test_when_the_credential_file_may_be_opened_is_stated_in_one_place(
        self,
    ) -> None:
        """The third rule in this paragraph, and it had no home of its own.

        The rung check above settled *how* the file is opened and the address
        check settled *where the user is then sent*. This is the remaining
        clause: *whether to open it at all*. GUIDE.md stated it - "open it only
        for the missing key, never to duplicate one that is already available" -
        in the one document CLAUDE.md says states no rule SKILL.md does not, and
        SKILL.md does not state it. `run-safety.md` does, as "stop once only
        when a key is truly missing", inside the ordered handoff it performs.

        So the clause was a mandate sitting away from its own mandate document
        while the reference that owns the step already carried it: a second
        statement of an existing rule, which CLAUDE.md calls a defect rather
        than emphasis. It is removed from GUIDE.md, which now names the selected
        source and points at the reference for the handoff itself.

        The assertion is the placement, not the wording, and it fails in both
        directions - which is the point. Delete the rule from `run-safety.md`
        and there are no homes, so the rule cannot quietly lose the one it has.
        Restate it in GUIDE.md or SKILL.md and there are two, so it cannot
        quietly gain a second. Neither failure needs anyone to remember that
        this paragraph was ever a problem.
        """
        documents = {
            path.relative_to(ROOT).as_posix(): " ".join(
                path.read_text().casefold().split()
            )
            for path in assistant_facing_documents()
        }
        owner = RUN_SAFETY.relative_to(ROOT).as_posix()

        homes = sorted(
            name
            for name, text in documents.items()
            if self._WHEN_THE_FILE_IS_OPENED.search(text)
        )
        self.assertEqual(
            homes,
            [owner],
            "when the credential file may be opened is stated in "
            f"{homes or 'no document at all'} - it belongs once, in the "
            "reference that performs the handoff",
        )

        # And the surviving statement is the rule, not some other sentence that
        # happens to fit the shape: opened once, and only for a missing key.
        stated = self._WHEN_THE_FILE_IS_OPENED.search(documents[owner]).group(0)
        for element in ("once", "key", "missing"):
            with self.subTest(element=element):
                self.assertIn(element, stated)

        # GUIDE.md keeps the pointer that replaced it, so "no rule here" is not
        # satisfied by the entry point simply dropping the subject.
        self.assertIn("`references/run-safety.md`", documents["GUIDE.md"])

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

    def test_a_slow_calibration_is_disclosed_asked_about_once_and_run_detached(
        self,
    ) -> None:
        """The three obligations a longer budget creates, none of them optional.

        A budget that lets a minute-per-call evaluator finish is a wait the user
        did not ask for, so it has to be disclosed before it starts; a timeout
        after it is a question with five answers, asked once rather than five
        times; and the wait now outlasts a foreground command, so calibration
        gets the detached invocation this package already ships for a long paid
        optimization. Guidance with no test is guidance one edit from gone.
        """
        reference = (
            SKILL_ROOT / "references" / "evaluation-and-dataset.md"
        ).read_text()
        normalized = " ".join(reference.casefold().split())

        for phrase in (
            # Disclosed before, not narrated after - and the estimate is derived
            # from the probe calls rather than being a shrug.
            "before the stage starts, say what it does and how long it may take",
            "four probe calls per input/expected pair",
            # One budget, so the quoted wait is the real one.
            "`--timeout` is the whole wait rather than half of it",
            # Asked once, with every option that applies.
            "ask once - one question carrying every option that applies, never "
            "one question per option",
            "**wait**, if the evaluator is normally this slow",
            "**take a named fix**, when the cause is certain",
            "a deterministic comparison - an exact or normalized match against "
            "the expected answer, no model call",
            "**retry**, since a provider call that has stalled looks the same "
            "from here",
            "**build a new evaluation method** together",
            # And named again at the close when it was avoidable and not fixed.
            "name that fix in the readiness summary, and again at the close if "
            "it was not taken",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

        # The detached invocation itself, not merely the word "detached": a
        # calibration killed by a foreground timeout writes no `timed_out`
        # record, so the one cap that tells slow from broken cannot fire.
        self.assertIn("nohup ", reference)
        self.assertIn("2> traigent-runs/calibration.log &", reference)
        self.assertIn(
            "a calibration killed from outside writes no result at all",
            normalized,
        )

        # SKILL.md owns the closing repetition, because the closing stage loads
        # run-safety.md and that reference does not own calibration.
        skill = " ".join(SKILL.read_text().casefold().split())
        self.assertIn(
            "name any avoidable cause of the slowness in the readiness summary "
            "and again at the close if it was not fixed",
            skill,
        )
        self.assertIn(
            "before calibration starts, say what it does and how long it may take",
            skill,
        )

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
            "shares the single `--timeout` budget",
            "read `supplemental_probe_advisory` as unavailable evidence",
            "it never changes authored pass",
            "do not count an unavailable probe as distinguished",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_the_guide_says_what_each_probe_set_is_for(self) -> None:
        """Two sets of probes ran and the guide never said why there were two.

        Everything downstream reads only the authored ones - `readiness.py`
        takes `cases`/`checks`/`scores`/`timed_out` and nothing else - so a
        reader could reasonably conclude the generated ones earn nothing and
        delete them. They earn the question the authored four cannot ask, and
        the answer is the reason they must not decide: a permutation scoring
        full marks is correct for an order-free task. The separation also
        carries the repair case, which is where it matters most and where the
        guidance said nothing at all - an author's own probes partly confirm the
        author's own fix, and generated probes cannot be revised to pass.
        """
        text = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "the authored probes are the verdict",
            "the only thing `passed`, the exit code, and the readiness score are "
            "built from",
            "they only ever raise a question, never a verdict",
            "only the author knows which this task is",
            "a probe an author can revise until it passes is weak evidence about a "
            "repair the author just wrote",
            "the half of the evidence not confirming its own fix",
            "read the first as the verdict and the second as the questions",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_the_short_calibration_command_routes_long_ones_to_the_detached_form(
        self,
    ) -> None:
        """Two invocations for one step, and only one of them survives the wait.

        The command block in the calibration section is a plain foreground run.
        `run-safety.md` records that harnesses often kill a foreground command at
        about five minutes, and a calibration budget now runs to fifteen - so a
        reader who follows the first block they meet loses the whole wait AND
        the timeout record that makes a slow evaluator legible. The pre-cap
        warning has the same problem from the other end: it goes to stderr,
        which only the detached form is capturing and polling.
        """
        text = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "that form is for a calibration that returns in seconds",
            'use the detached form in "when calibration runs long" instead',
            "can be killed from outside before it writes anything",
            "its warnings arrive on a stderr nobody is reading",
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
            # Each run's frontier is recorded: it is a result the user was
            # given, and after the fact this record is the only place it
            # survives.
            "accuracy-cost frontier for each run - its points, the recommended "
            "one, and the score claim with paired outcome counts",
        ):
            self.assertIn(phrase, text)
        # 61, raised from 60 when the held-out branch merged, and the raise is
        # the part that needs an argument rather than the line.
        #
        # The cap is shared, and twice a trunk branch measured itself against
        # the open held-out branch and gave a line back for it: 4ba2311 folded
        # the record's two frontier lines into one ("the cap is shared, and the
        # one that can spend less should"), and 351f312 rejoined the
        # connected-run field, "which wrapped for width rather than for
        # meaning". Both reserves were then spent by later trunk work - the
        # width wrap returned in 3f57acf, and the repaired/generated row-ids
        # field took the other - so trunk arrived at this merge holding 60 of
        # 60 with no reserve left, and the held-out score is a 61st line.
        #
        # It is not a line that can be given back the same way. Every bullet in
        # the template is now one physical line and one distinct field, so the
        # only remaining saving is folding two fields into one - which is a
        # decision about what the run record must keep separate, not a
        # reflow. The held-out score for the recommended configuration is the
        # result the holdout exists to produce, so the field stays and the
        # budget moves by exactly one.
        #
        # OWNER: if the record should stay at 60, the fold to make is a
        # judgement call about the two readiness-score lines under "Quality
        # evidence"; this raise is the reversible choice, not the settled one.
        self.assertLessEqual(len(text.splitlines()), 61)
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

    def test_the_knob_catalog_offers_twelve_and_the_space_pays_for_four(self) -> None:
        """The customer sees the breadth and pays for four - so both are here.

        `batch_size` is absent for the same reason `max_tokens` is: it moves
        throughput and cost without changing what the answer says. It was
        replaced by `self_consistency`, which does change the answer and does
        cost money to do it.
        """
        text = SDK_EXECUTION.read_text()
        catalog = text.split("### The knob catalog", 1)[1].split("###", 1)[0]
        for knob in (
            "model",
            "prompt_style",
            "thinking_shape",
            "pre_action_reflect",
            "reflect",
            "few_shot_count",
            "task_decomposition",
            "self_consistency",
            "retrieval_k",
            "context_format",
            "tool_policy",
            "temperature",
        ):
            with self.subTest(knob=knob):
                self.assertIn(f"`{knob}`", catalog)
        table = catalog.split("Two entries carry a precondition", 1)[0]
        for out in ("batch_size", "max_tokens", "self_check"):
            with self.subTest(out=out):
                self.assertNotIn(f"`{out}`", table)
        self.assertIn("`batch_size` and `max_tokens` are deliberately absent", catalog)
        # `self_consistency` needs sampling diversity and this walkthrough pins
        # temperature at 0, so it is offered only where it can do anything.
        self.assertIn("only when the customer's own temperature is above 0", catalog)
        # The waived detection: temperature's slot is decided by what the
        # customer already has, never by guessing the task's type.
        self.assertIn("do not build task-type detection", catalog)

    def test_the_knob_explanations_cite_nothing(self) -> None:
        """One plain sentence per knob, and nothing that reads as evidence.

        A customer watching their run start wants to know what is being tried,
        not to be handed reading. A percentage or a paper name in front of them
        also reads as a promise about THEIR task, which no published result
        about a technique ever is. So the published findings that justify the
        catalog live in the catalog's own reasoning and in this repo's history,
        never in the lines the customer sees.
        """
        text = SDK_EXECUTION.read_text()
        section = text.split("### Say what is being tried", 1)[1].split("\n##", 1)[0]
        # Rejoin wrapped bullets: two of them run past the file's line width,
        # and reading only their first line would let a second sentence hide
        # on the continuation.
        bullets: list[str] = []
        for line in section.splitlines():
            if line.strip().startswith("- **"):
                bullets.append(line.strip())
            elif bullets and line.startswith("  ") and line.strip():
                bullets[-1] += " " + line.strip()
            elif not line.strip():
                continue
        self.assertEqual(len(bullets), 12, "one line per catalog knob")
        for bullet in bullets:
            with self.subTest(bullet=bullet[:40]):
                explanation = bullet.split("** - ", 1)[1]
                self.assertNotRegex(explanation, r"\d")
                self.assertNotRegex(explanation, r"%")
                self.assertNotRegex(explanation, r"https?://")
                self.assertNotRegex(
                    explanation,
                    r"(?i)\b(research|study|studies|paper|published|reported|"
                    r"benchmark|shows that|et al)\b",
                )
                # One sentence. Not two dressed as one.
                self.assertEqual(explanation.rstrip().count("."), 1)
        self.assertIn('no references, no "research shows"', section)

    def test_sdk_template_defines_prompt_builder(self) -> None:
        text = (SKILL_ROOT / "references" / "sdk-execution.md").read_text()
        self.assertIn("def build_prompt(", text)
        self.assertIn('if style == "plain":', text)
        self.assertIn('elif style == "structured":', text)
        # Four behaviour knobs, and each intervenes at a different moment -
        # `pre_action_reflect` before any work, `thinking_shape` during the
        # answer, `reflect` on the finished answer. Two knobs that mean the
        # same thing are one dimension counted twice, which is why `self_check`
        # is gone: it and `reflect` were both "look at your answer again",
        # differing only in what the model was told to look at.
        self.assertIn("if pre_action_reflect:", text)
        self.assertIn('if thinking_shape == "chain_of_thought":', text)
        self.assertIn("if reflect:", text)
        self.assertNotIn("if self_check:", text)
        self.assertNotIn('"self_check"', text)
        for pair in (
            '"thinking_shape": BASELINE_SPACE["thinking_shape"]',
            '"pre_action_reflect": [False, True]',
            '"reflect": [False, True]',
        ):
            self.assertIn(pair, text)
        # `prompt_style`'s first value was renamed from "direct" when
        # `thinking_shape` arrived and took that word for what it describes.
        self.assertNotIn('"criteria_first"', text)

    def test_sdk_comparison_uses_twelve_rows_then_added_knobs_and_twelve_trials(
        self,
    ) -> None:
        text = SDK_EXECUTION.read_text()
        normalized = " ".join(text.casefold().split())

        for phrase in (
            "BASELINE_TRIALS = positive_int(",
            "ENHANCED_MAX_TRIALS = positive_int(",
            '"TRAIGENT_FIRST_RUN_ENHANCED_MAX_TRIALS",',
            "default=12,",
            "assert configuration_count(BASELINE_SPACE) == 12",
            "assert configuration_count(ENHANCED_SPACE) == 48",
            # The two asserts that keep those counts from drifting rather than
            # merely stating today's value. Deleting either left every count
            # test green: the spaces still had the right sizes, and nothing
            # stopped the next edit changing them.
            'len(BASELINE_SPACE["temperature"]) == 1 and '
            'len(ENHANCED_SPACE["temperature"]) == 1',
            "set(BASELINE_SPACE[knob]) <= set(ENHANCED_SPACE[knob]) "
            "for knob in BASELINE_SPACE",
            # EQUAL, not "at most": `grid` enumerates in order and stops at
            # the cap, so a cap below the size silently drops whichever rows
            # grid ordered last rather than running a smaller sweep.
            "assert BASELINE_TRIALS == configuration_count(BASELINE_SPACE)",
            "assert 1 <= ENHANCED_MAX_TRIALS < configuration_count(ENHANCED_SPACE)",
            "configuration_space=BASELINE_SPACE",
            "max_trials=BASELINE_TRIALS",
            "configuration_space=ENHANCED_SPACE",
            "max_trials=ENHANCED_MAX_TRIALS",
        ):
            self.assertIn(phrase, text)

        # Each default pinned inside ITS OWN positive_int block. Both counts are
        # 12 now, so an `assertIn("default=12,", text)` over the whole file says
        # nothing about either: flipping the baseline default back to 6 left the
        # enhanced one satisfying the assertion and the suite green.
        for name, default in (
            ("BASELINE_TRIALS", "default=12,"),
            ("ENHANCED_MAX_TRIALS", "default=12,"),
        ):
            with self.subTest(name=name):
                block = text.split(f"{name} = positive_int(", 1)[1].split(")", 1)[0]
                self.assertIn(f'"TRAIGENT_FIRST_RUN_{name}",', block)
                self.assertIn(default, block)

        for phrase in (
            "twelve baseline rows and a 12-trial enhanced cap",
            "adds two more real one-call controls: pre-action reflect and reflect",
            # The count is disclosed in the words the customer reads, and as a
            # COUNT rather than as a change from an earlier release of this
            # walkthrough - which is our changelog, on the card where they
            # approve spending money, about a run they have never made.
            "the baseline runs 12 paid trials, one for every configuration",
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
        # The baseline's two axes beyond `model` are `prompt_style` and
        # `thinking_shape`, and both must be knobs the enhanced space also
        # carries - otherwise the baseline ranks a lever the enhanced run will
        # never use, which is exactly what temperature became when it was
        # pinned. Two rather than one because the selection rule downstream
        # reads the baseline to choose the enhanced knobs.
        self.assertIn(
            '"prompt_style": [BASELINE_CONFIG["prompt_style"], "structured"]',
            baseline_block,
        )
        self.assertIn(
            '"thinking_shape": [BASELINE_CONFIG["thinking_shape"], "chain_of_thought"]',
            baseline_block,
        )
        self.assertIn('"temperature": [BASELINE_CONFIG["temperature"]]', baseline_block)
        for pinned in ("pre_action_reflect", "reflect"):
            with self.subTest(pinned=pinned):
                self.assertIn(
                    f'"{pinned}": [BASELINE_CONFIG["{pinned}"]]', baseline_block
                )
        self.assertIn('"prompt_style": BASELINE_SPACE["prompt_style"]', enhanced_block)
        self.assertIn('"temperature": BASELINE_SPACE["temperature"]', enhanced_block)
        self.assertIn('"pre_action_reflect": [False, True]', enhanced_block)
        self.assertIn('"reflect": [False, True]', enhanced_block)

        code = re.findall(r"```python\n(.*?)\n```", text, re.DOTALL)[0]
        module = ast.parse(code)
        wanted_assignments = {
            "BASELINE_CONFIG",
            "BASELINE_SPACE",
            "ENHANCED_SPACE",
            "WIRED_KNOBS",
            "BEHAVIOUR_KNOBS",
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
            "BASELINE_TRIALS": 12,
            "ENHANCED_MAX_TRIALS": 10,
            "MODEL_REQUEST_TIMEOUT_SECONDS": 120.0,
        }
        exec(compile(executable, "<sdk-spaces-and-knobs>", "exec"), namespace)

        # Exact, and asserted in the template itself so the number in the
        # prose cannot drift from the number the search receives. 3 models x 2
        # prompt styles x 2 thinking shapes, and 3 models x 4 binary knobs.
        count = namespace["configuration_count"]
        self.assertEqual(count(namespace["BASELINE_SPACE"]), 12)
        self.assertEqual(count(namespace["ENHANCED_SPACE"]), 48)
        self.assertEqual(len(namespace["BEHAVIOUR_KNOBS"]), 4)
        for knob in namespace["BEHAVIOUR_KNOBS"]:
            with self.subTest(knob=knob):
                self.assertEqual(len(namespace["ENHANCED_SPACE"][knob]), 2)
        # Temperature is pinned in BOTH, unconditionally. It used to be pinned
        # only when the strong tier reasoned, and that branch produced a second
        # pair of sizes (6 and 18) that no document ever stated.
        for space_name in ("BASELINE_SPACE", "ENHANCED_SPACE"):
            with self.subTest(space=space_name):
                self.assertEqual(namespace[space_name]["temperature"], [0.0])
        # The baseline is a strict subset, so it can rank only levers the
        # enhanced run actually carries.
        for knob, values in namespace["BASELINE_SPACE"].items():
            with self.subTest(knob=knob):
                self.assertLessEqual(
                    set(values), set(namespace["ENHANCED_SPACE"][knob])
                )
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
        self.assertNotIn("agent_type", document)
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
        off = {
            "style": "plain",
            "pre_action_reflect": False,
            "thinking_shape": "direct",
            "reflect": False,
        }
        # Every knob at its baseline value must leave the message untouched, or
        # the baseline is not the agent's current behaviour.
        self.assertEqual(build_prompt("task", **off), "task")
        # Each of the four intervenes at its own point, and each produces a
        # different prompt. Two knobs with one effect are one dimension counted
        # twice, which is what the space size would then be lying about.
        variants = {
            name: build_prompt("task", **{**off, name: value})
            for name, value in (
                ("style", "structured"),
                ("pre_action_reflect", True),
                ("thinking_shape", "chain_of_thought"),
                ("reflect", True),
            )
        }
        self.assertIn("Task:\ntask", variants["style"])
        self.assertIn("restate what is being asked", variants["pre_action_reflect"])
        self.assertIn("step by step", variants["thinking_shape"])
        self.assertIn("reconsider", variants["reflect"])
        self.assertEqual(len(set(variants.values())), 4)
        # `pre_action_reflect` plans BEFORE the work and `thinking_shape`
        # derives DURING it. For a single-call agent those collapse into each
        # other unless the wording holds them apart, and a collapsed pair is
        # the `pre_action_reflect` mistake again under new names.
        self.assertNotIn("step by step", variants["pre_action_reflect"])
        self.assertNotIn("restate what is being asked", variants["thinking_shape"])

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

        # The reasoning branch used to produce a SECOND pair of space sizes
        # that no document stated: temperature was dropped only when the strong
        # tier reasoned, so the enhanced space was 54 ordinarily and 18 there,
        # and the assert here fired on the space the template shipped. Pinning
        # temperature always removes the branch. The template now loads
        # unchanged under a reasoning strong tier, at the same 12 and 48 - which
        # is the whole reason to pin it, so it is asserted rather than assumed.
        reasoning_namespace = {
            "math": __import__("math"),
            "SELECTED_CURRENT_MODEL": "provider/current",
            "SELECTED_ALTERNATIVE_MODEL": "provider/alternative",
            "SELECTED_STRONG_MODEL": "provider/strong",
            "STRONG_REASONING_EFFORT": "high",
            "BASELINE_TRIALS": 12,
            "ENHANCED_MAX_TRIALS": 10,
            "MODEL_REQUEST_TIMEOUT_SECONDS": 120.0,
        }
        exec(
            compile(executable, "<sdk-reasoning-strong-tier>", "exec"),
            reasoning_namespace,
        )
        self.assertEqual(count(reasoning_namespace["BASELINE_SPACE"]), 12)
        self.assertEqual(count(reasoning_namespace["ENHANCED_SPACE"]), 48)
        self.assertEqual(
            reasoning_namespace["ENHANCED_SPACE"], namespace["ENHANCED_SPACE"]
        )

    def test_the_baseline_result_chooses_values_not_only_knobs(self) -> None:
        """The selection rule ran in one direction and now runs in two.

        Carrying a knob forward was decided from the baseline; carrying its
        VALUES forward was not, so the enhanced space re-tested values the
        baseline had already measured as poor. The rule reads the lowest-scoring
        combination and makes one of two moves, and which one depends on how far
        that score sits from the best.

        The conditional is the load-bearing part and is asserted in both
        directions. A small gap means the knob was evidently not what decided
        the run, so the slot is better spent on a different knob - replace it. A
        large gap means it clearly mattered - keep it and narrow its values
        toward the winner. Reversing those two would drop exactly the knobs the
        baseline proved to matter.

        The threshold is calibration's `SEPARATION_MARGIN`, read from that
        module rather than retyped, so "meaningfully different" cannot come to
        mean two numbers in two documents. Neither move resizes the space: 48 is
        which knobs and which values, not how many.
        """
        safety = " ".join(RUN_SAFETY.read_text().split())

        scripts = str(SKILL_ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        calibrate = importlib.import_module("calibrate_evaluator")
        self.assertIn(
            f"**{calibrate.SEPARATION_MARGIN} normalized separation margin** that "
            "calibration already uses",
            safety,
        )
        self.assertIn("shared deliberately, not by coincidence", safety)

        for phrase in (
            # The heading is what makes the rule findable from the enhanced
            # space's own section. Deleting it while leaving the body intact
            # passed every other assertion here.
            "**The baseline result chooses the enhanced space's values, not "
            "only its knobs.**",
            # Reading the loser is the new input; the knob rule already read
            # what varied.
            "by reading the combination that scored **lowest**",
            # Direction one: small gap, the knob did not decide it, replace it.
            "**Gap within the margin**",
            "evidently did not decide the run",
            "**Replace that knob**",
            # Direction two: large gap, the knob mattered, narrow its values.
            "**Gap beyond the margin**",
            "that knob clearly mattered",
            "**Keep it and narrow its values**",
            "moving them toward the winning configuration's",
            # Not a resize, and not a search.
            "Neither move changes the size",
            "this decides which knobs and which two values each, never how many",
            "the managed run does the searching",
            # The evidence is weak and must be described as weak.
            "at most six observations a side",
            "`the baseline's best combination used X` and never as `X is better`",
            "never as proof that a replaced knob does nothing",
            "the customer's own knob wins over one of this guide's suggestions",
            # Visible before the customer pays for it.
            "Every knob replaced and every value narrowed is named on the "
            "enhanced run's approval card",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, safety)

    def test_the_reduced_space_is_stated_exactly_and_framed_honestly(self) -> None:
        """Three owner decisions that only prose can carry.

        The counts are exact ON PURPOSE: "roughly 50" is a number nobody can
        check against a run, and every other size claim in this guide is
        checkable. So the mandate to state them exactly is asserted, not just
        the numbers themselves.

        The same target size applies to a customer who arrives with twenty
        knobs of their own. The reduction is for the demonstration's sake, and
        it is not a judgement about their knobs - the baseline-evidence rule
        decides which of THEIRS fill the slots, and what was left out is named
        in the approval preview.

        And it must not read as though the improvement were bought by shrinking
        the search. The honest framing is that the knobs are reduced to show the
        principle cheaply and that Traigent has tens more to recommend - a
        demonstration, not the ceiling. Deleting any of this left the suite
        green, because a number can be tested and a frame cannot unless it is
        pinned here.
        """
        sizes = generated_space_sizes()
        sdk = SDK_EXECUTION.read_text()
        for phrase in (
            'State them exactly,\nnever as "roughly" or "about"',
            "3 models × 2 prompt styles × 2 thinking shapes "
            f"= {sizes['baseline']} configurations",
            f"3 models × 4 binary behaviour knobs = {sizes['enhanced']} configurations",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, sdk)

        run_safety = " ".join(RUN_SAFETY.read_text().split())
        for phrase in (
            f"**The same {sizes['enhanced']} whatever the customer brings.**",
            f"gets a {sizes['enhanced']}-configuration enhanced space too, "
            "not a larger one",
            "the four slots are filled from what they brought",
            "baseline evidence decides which four",
            "Every knob replaced and every value narrowed is named on the "
            "enhanced run's approval card",
            "The knobs are reduced to demonstrate the principle cheaply",
            "Traigent knows tens of knobs it can recommend",
            "This is a demonstration, not the ceiling of what Traigent can do",
            "Never present the smaller space as though the improvement were "
            "bought by shrinking the search",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, run_safety)

    # "3 models x 2 prompt styles x 2 thinking shapes = 12 configurations", in
    # either document's multiplication sign and with markdown emphasis already
    # stripped. A knob counted as "N binary ..." contributes 2**N, which is how
    # the enhanced space is written: 3 models x 4 binary knobs is 3 x 2**4.
    _STATED_ARITHMETIC = re.compile(
        r"((?:\d+ [a-z][a-z ]*?[x×] )+\d+ [a-z][a-z ]*?)= (\d+)",
        re.IGNORECASE,
    )

    @classmethod
    def _stated_factors(cls, phrase: str) -> list[int]:
        """One multiplicand per knob a stated space arithmetic claims.

        "4 binary knobs" is four knobs of two values each, not one knob of
        four, so it expands to `[2, 2, 2, 2]`. The product is the same either
        way; the expansion is what lets the factors be compared against the
        fence's per-knob widths, which is where a knob quietly leaving the
        space shows up.
        """
        factors: list[int] = []
        for count, noun in re.findall(r"(\d+) ([a-z][a-z ]*)", phrase, re.IGNORECASE):
            if "binary" in noun.casefold():
                factors.extend([2] * int(count))
            else:
                factors.append(int(count))
        return factors

    def test_every_stated_space_arithmetic_multiplies_out_to_the_real_space(
        self,
    ) -> None:
        """The sizes are stated in more places than the check above looked.

        `test_the_reduced_space_is_stated_exactly_and_framed_honestly` pins two
        sentences in `sdk-execution.md` and two clauses in `run-safety.md`.
        Measured, the arithmetic itself is written FIVE times across the two
        documents - run-safety.md restates the whole baseline-and-enhanced
        sentence at its "exact sizes" paragraph, and states it a third time at
        "the space stays 3 models x 4 binary knobs = 48" - and three of those
        five were pinned by nothing. A re-sizing that updated the owner and the
        pinned clauses would leave the restatements contradicting them, with
        the suite green.

        So every statement of the form is found rather than listed, and each is
        checked three ways against the fence: the factors multiply out to the
        total it claims, the total is a size the fence actually builds, and the
        factors are that space's own non-trivial widths. A knob dropped from
        the space fails here even when the product is edited to agree.
        """
        sizes = generated_space_sizes()
        widths = generated_space_widths()
        swept = {
            name: sorted((width for width in space.values() if width > 1), reverse=True)
            for name, space in widths.items()
        }

        found: list[str] = []
        for document in conversation_contract_documents():
            body = " ".join(document.read_text().replace("*", " ").split())
            for phrase, total in self._STATED_ARITHMETIC.findall(body):
                where = f"{document.relative_to(ROOT).as_posix()}: {phrase}= {total}"
                found.append(where)
                factors = self._stated_factors(phrase)
                with self.subTest(statement=where):
                    self.assertEqual(
                        math.prod(factors),
                        int(total),
                        f"{factors} multiplies to {math.prod(factors)}, not the "
                        f"{total} this sentence states",
                    )
                    named = [name for name, size in sizes.items() if size == int(total)]
                    self.assertEqual(
                        len(named),
                        1,
                        f"no generated space has {total} configurations; the "
                        f"fence builds {sizes}",
                    )
                    self.assertEqual(
                        sorted(factors, reverse=True),
                        swept[named[0]],
                        f"the {named[0]} space sweeps {swept[named[0]]} values "
                        f"per knob; this sentence claims {factors}",
                    )
        # Five statements, and the count is asserted because a regex that stops
        # matching reports the same clean result as prose that stopped lying.
        self.assertEqual(
            len(found),
            5,
            "the number of stated space arithmetics has changed. Adding one is "
            "a sixth home for a decision `sdk-execution.md` owns; losing one "
            f"means this check no longer reads them. Found: {found}",
        )

        # Both directions, against invented sentences. The first is the shape a
        # re-sizing leaves behind: a product nobody recomputed.
        self.assertEqual(self._stated_factors("3 models x 2 prompt styles "), [3, 2])
        self.assertEqual(
            self._stated_factors("3 models x 4 binary knobs "), [3, 2, 2, 2, 2]
        )
        planted = "3 models x 2 prompt styles x 2 thinking shapes = 14 configurations"
        self.assertEqual(
            [
                math.prod(self._stated_factors(phrase)) == int(total)
                for phrase, total in self._STATED_ARITHMETIC.findall(planted)
            ],
            [False],
            "a stated arithmetic that does not multiply out is what this guard "
            "exists to catch, and it must be able to see one",
        )
        self.assertEqual(
            self._STATED_ARITHMETIC.findall(
                "The baseline runs 12 trials over 12 configurations."
            ),
            [],
            "a sentence that states a count without stating an arithmetic is "
            "not this check's business",
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
        self.assertIn("its row count exactly; do not expand it to twelve", sdk)
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
            # The enhanced space is fully determined before either run now:
            # binary knobs and a pinned temperature leave no swept range to
            # re-centre, so the between-runs refinement step is gone.
            "the enhanced space carries no pre-baseline placeholder to replace",
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

    def test_strong_reasoning_tier_swaps_sampling_for_effort_and_no_cap(self) -> None:
        """A reasoning-tier model rejects sampled temperature, and gets no cap.

        Executes the fence's call path shape: the strong tier at a declared
        reasoning effort must send reasoning kwargs instead of temperature,
        and no `max_tokens` at all, while ordinary tiers keep the swept
        temperature. Both tiers are bounded by the wall clock instead.

        The name said "and headroom" while the wrapper sent `max_tokens` 4096.
        Renamed with the change, because a test whose name states the opposite
        of what it asserts is read instead of run.
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
            "require_untruncated_completion": lambda response: None,
            "build_prompt": lambda message, **_knobs: message,
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
                "temperature": 0.0,
                "prompt_style": "plain",
                "thinking_shape": "direct",
                "reflect": False,
                "pre_action_reflect": False,
            },
        )
        strong_call = calls[-1]
        self.assertEqual(strong_call["reasoning_effort"], "high")
        self.assertNotIn("temperature", strong_call)
        # And no cap of ours, on the tier that used to carry one. This asserted
        # `max_tokens >= 4096` until the cross-run hazard was named: a number
        # that fits the baseline's medium model is a number this tier's
        # reasoning model can exceed, so the cap would truncate a configuration
        # the user never chose, between two runs, at our hand. The provider
        # default is the bound their agent already lives with.
        self.assertNotIn("max_tokens", strong_call)

        call_agent(
            "task",
            {
                "model": "provider/mid",
                "temperature": 0.0,
                "prompt_style": "plain",
                "thinking_shape": "direct",
                "reflect": False,
                "pre_action_reflect": False,
            },
        )
        ordinary_call = calls[-1]
        self.assertEqual(ordinary_call["temperature"], 0.0)
        self.assertNotIn("reasoning_effort", ordinary_call)
        self.assertNotIn("max_tokens", ordinary_call)
        # The bound this request DOES carry is the wall clock, which is the
        # distinction the rule turns on: a time limit stops the work, a token
        # limit corrupts the answer and then scores the corruption.
        self.assertEqual(ordinary_call["timeout"], 120.0)

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
            'HOLDOUT_DATASET = str(RUN_DIR / "holdout.jsonl")',
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
                    *sdk_wrapper_state_nodes(text),
                    functions["provider_reported_cost"],
                    functions["require_nonzero_token_usage"],
                    functions["require_untruncated_completion"],
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

        def response(*, usage, finish_reason="stop"):
            return SimpleNamespace(
                usage=usage,
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="answer"),
                        finish_reason=finish_reason,
                    )
                ],
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

    def test_sdk_holdout_uses_the_same_public_metric_contract(self) -> None:
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
            "baseline, search, and holdout must use the same selected public evaluation path",
            "same installed public `traigent.dataset.from_jsonl` loader",
        ):
            self.assertIn(phrase, normalized)
        self.assertIn("inspect.signature(traigent.Dataset.from_jsonl)", text)
        self.assertIn('HOLDOUT_DATASET = str(RUN_DIR / "holdout.jsonl")', text)
        self.assertIn("def holdout_agent_input(input_data)", text)
        # Scoring the winner on reserved rows is not a generalization claim,
        # and the closing result has to say so somewhere. Before this, no
        # document stated it of the closing result at all: the nearest sentence
        # read as a remedy ("score the enhanced winner against the reserved
        # held-out rows") rather than as the limit that still stands after it.
        self.assertIn(
            "this first-run comparison does not establish generalization or "
            "expected production improvement, and the held-out score does not "
            "convert it into one",
            normalized,
        )

        holdout_node = functions["evaluate_holdout"]
        holdout_module = ast.fix_missing_locations(
            ast.Module(
                body=[functions["holdout_agent_input"], holdout_node], type_ignores=[]
            )
        )
        examples = [
            SimpleNamespace(
                input_data="classify this",
                expected_output="urgent",
                metadata={
                    "id": "case-1",
                    "source": "reviewed",
                    "difficulty": "hard",
                    "coverage": "priority",
                    "split": "holdout",
                    "metadata": {"rubric_branch": "priority"},
                },
            ),
            SimpleNamespace(
                input_data={
                    "message": "classify that",
                },
                expected_output="normal",
                metadata={},
            ),
        ]
        loaded_paths = []
        agent_calls = []
        scorer_calls = []

        class Dataset:
            @staticmethod
            def from_jsonl(path):
                loaded_paths.append(path)
                return SimpleNamespace(examples=examples)

        def call_agent(message, config):
            agent_calls.append((message, config))
            return "urgent" if message == "classify this" else "normal", 0.25

        def task_score(output, expected, input_data):
            scorer_calls.append((output, expected, input_data))
            return 1.0

        namespace = {
            "HOLDOUT_DATASET": "/project/traigent-runs/holdout.jsonl",
            "call_agent": call_agent,
            "task_score": task_score,
            "traigent": SimpleNamespace(Dataset=Dataset),
        }
        exec(compile(holdout_module, "<sdk-holdout>", "exec"), namespace)

        config = {"model": "preserved-current-model"}
        score, cost = namespace["evaluate_holdout"](config)

        self.assertEqual(score, 1.0)
        self.assertEqual(cost, 0.5)
        self.assertEqual(loaded_paths, ["/project/traigent-runs/holdout.jsonl"])
        self.assertEqual(
            agent_calls,
            [("classify this", config), ("classify that", config)],
        )
        self.assertEqual(
            scorer_calls,
            [
                (
                    "urgent",
                    examples[0].expected_output,
                    "classify this",
                ),
                (
                    "normal",
                    examples[1].expected_output,
                    examples[1].input_data,
                ),
            ],
        )

        untracked_costs = iter((0.25, None))

        def call_agent_with_untracked_cost(message, config):
            output = "urgent" if message == "classify this" else "normal"
            return output, next(untracked_costs)

        namespace["call_agent"] = call_agent_with_untracked_cost
        score, cost = namespace["evaluate_holdout"](config)
        self.assertEqual(score, 1.0)
        self.assertIsNone(cost)

    def test_the_search_never_evaluates_the_reserved_rows(self) -> None:
        """The separate file is the mechanism; the claim alone is not.

        4531ae6 removed the held-out dataset *and* its plumbing, and the
        first reinstatement restored only the dataset - so the natural
        implementation was one 28-row `tuning.jsonl` with the reserved rows
        inside the search, while stage 8 still printed a clean held-out line.
        Nothing else catches that: preflight passes `dataset-split` on the
        combined scoring file, readiness never sees the optimizer's input,
        and no other check asserts what `eval_dataset` actually names.
        """
        text = SDK_EXECUTION.read_text()
        assignments: dict[str, ast.expr] = {}
        eval_datasets: list[ast.expr] = []
        for source in re.findall(r"```python\n(.*?)\n```", text, re.DOTALL):
            for node in ast.walk(ast.parse(source)):
                if (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                ):
                    assignments.setdefault(node.targets[0].id, node.value)
                if isinstance(node, ast.Call):
                    eval_datasets.extend(
                        keyword.value
                        for keyword in node.keywords
                        if keyword.arg == "eval_dataset"
                    )

        self.assertEqual(
            len(eval_datasets),
            1,
            "exactly one call may declare the dataset the search evaluates",
        )
        evaluated = eval_datasets[0]
        self.assertIsInstance(evaluated, ast.Name)
        self.assertEqual(
            evaluated.id,
            "TUNING_DATASET",
            "the search must evaluate the tuning file - naming the holdout "
            "file, or a combined file carrying both splits, puts the reserved "
            "rows back inside the selection they exist to sit outside of",
        )

        resolved = {}
        for name in ("TUNING_DATASET", "HOLDOUT_DATASET"):
            self.assertIn(name, assignments, f"the wrapper does not define {name}")
            resolved[name] = eval(  # noqa: S307 - the wrapper's own expression
                compile(
                    ast.fix_missing_locations(ast.Expression(assignments[name])),
                    "<sdk-dataset-paths>",
                    "eval",
                ),
                {"RUN_DIR": Path("/project/traigent-runs")},
            )
        self.assertEqual(
            resolved["TUNING_DATASET"], "/project/traigent-runs/tuning.jsonl"
        )
        self.assertEqual(
            resolved["HOLDOUT_DATASET"], "/project/traigent-runs/holdout.jsonl"
        )
        self.assertNotEqual(
            resolved["TUNING_DATASET"],
            resolved["HOLDOUT_DATASET"],
            "one file cannot both feed the search and be withheld from it",
        )

        dataset = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "write the reserved rows to their own file",
            "two files, not one file with a column",
            "`eval_dataset` names the tuning file only",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, dataset)

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
        same twelve-point space returns the first grid cell every time under `grid`
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

    def test_a_ten_day_sentence_is_classified_by_which_clock_it_names(self) -> None:
        """The classifier is checked against invented sentences, not the guide.

        This is the half the corpus scan below cannot check itself. Fed only
        sentences the documents already contain, a classifier that answers "yes,
        some clock is named" passes forever - including for a sentence about the
        portal period that qualifies on the word "registers", which is the event
        that *ends* the other clock. So the inputs here are written to separate
        those cases, and none of them is a quotation.

        The rule they pin: a clock is named by the thing it is a property of -
        the access code for the registration window, the portal access period
        for the portal one. "Register" belongs to both sentences and settles
        neither.
        """
        cases = {
            # The clock is named: this is the portal period, and it says so.
            "The portal access period lasts 10 days from the moment the user "
            "registers.": {"portal"},
            # The same sentence with the clock's name stripped. "Registers" is
            # still there, and it must not be enough - this is exactly the
            # mutation the or-either form of this check accepted.
            "The period lasts 10 days from the moment the user registers.": set(),
            "A single-use access code is valid for 10 days.": {"registration"},
            # Spelled out, and collective: both clocks, both named.
            "The two ten-day windows: the access code, then portal access.": {
                "portal",
                "registration",
            },
            # Counting them is not naming them, in either spelling.
            "Read the reference for the two 10-day windows.": set(),
            "There are two ten-day windows: registration, then registration "
            "expiry.": set(),
        }
        for sentence, expected in cases.items():
            with self.subTest(sentence=sentence):
                self.assertEqual(ten_day_clocks_named(sentence), expected)

        # The scan has to see the sentence before it can classify it, so the
        # spelling is pinned too: "ten-day" is the wording of this very branch's
        # own title, and a digits-only pattern skips it silently.
        for spelling in ("10 days", "10-day", "ten days", "ten-day", "TEN-DAY"):
            with self.subTest(spelling=spelling):
                self.assertTrue(TEN_DAY_MENTION.search(f"within {spelling} of that"))
        for spelling in ("two 10-day", "both ten-day", "two ten day"):
            with self.subTest(collective=spelling):
                self.assertTrue(TEN_DAY_COLLECTIVE.search(f"the {spelling} windows"))
        # Not every "ten" starts a period, and a false positive here would force
        # unrelated prose to name a clock it is not talking about.
        for innocent in ("often days go by", "the written days", "ten weeks"):
            with self.subTest(innocent=innocent):
                self.assertIsNone(TEN_DAY_MENTION.search(innocent))

    def test_the_two_ten_day_periods_are_never_conflated(self) -> None:
        """Two different 10-day periods exist, and a customer meets both.

        One bounds the access code: from the moment it is issued it authorizes
        one registration for 10 days, and after that it is dead and a fresh one
        has to be requested. The other starts when that code is spent: 10 days
        of portal access, at the end of which a perfectly valid API key is
        still refused and only a purchase restores it. Same number, different
        clock, different remedy - so a reader who merges them will wait out the
        wrong one.

        Pinned by shape rather than by a sentence, because the wording is free
        to change and the distinction is not. The defect is a 10-day period
        mentioned without saying which one it is, so that is what fails: a
        mention names at least one clock, and a mention that puts both periods
        in one sentence names both. "The two 10-day windows" fails on the
        second count - it counts them without distinguishing them.

        AT LEAST one, not exactly one, and that correction is the point of this
        revision. The first version demanded exactly one on the theory that
        naming both in one breath *was* the conflation. It is the opposite. The
        clearest sentence anyone can write here - "the access code's 10 days to
        register are not the same as the 10 days of portal access that
        registering starts" - names both clocks in order to separate them, and
        the rule refused it. A guard whose loudest false red lands on the best
        statement of the very distinction it enforces teaches authors to write
        the vaguer sentence, which is the defect. A sentence carrying two
        10-day mentions is held to naming both, so contrasting them is
        permitted and blurring them is not.

        Which clock is named is decided by `ten_day_clocks_named`, tested above
        against invented sentences. The scan here only applies that decision to
        the corpus; it cannot vouch for it, which is why that test is separate.
        """
        # The corpus is the contract documents, not the assistant-facing ones:
        # README.md is the single most-read file in a public repository and is
        # where a customer first meets the two windows, and it sat outside every
        # check that owns this distinction. It carries no 10-day sentence today;
        # including it is what makes that a fact the suite knows rather than one
        # this comment asserts. (Not the whole tracked tree, unlike the
        # disclosure guards: this file plants deliberately-vague 10-day
        # sentences as probe inputs, so scanning the tests would flag the guard's
        # own fixtures.)
        carrying = set()
        for path in conversation_contract_documents():
            for sentence in ten_day_sentences(path.read_text()):
                carrying.add(path.name)
                with self.subTest(document=path.name, sentence=sentence):
                    self.assertEqual(
                        self._ten_day_defect(sentence),
                        "",
                        f"{path.name}: {sentence}",
                    )

        # A pass has to mean the corpus was actually read, and the pointers that
        # carry the distinction are part of what is pinned: deleting them
        # outright would otherwise satisfy every assertion above by leaving
        # nothing to check. Superset, not equality - a sibling change that adds
        # a mention to another document is not a regression here.
        self.assertEqual(
            {"GUIDE.md", "SKILL.md", "glossary.md", "run-safety.md"} - carrying,
            set(),
            "a document that told the reader about a 10-day period has stopped "
            "mentioning one; the distinction was removed rather than corrected",
        )
        # The two entry documents are where a reader meets the pair, so each has
        # to keep a mention that names both clocks, not just any mention.
        for path in (ROOT / "GUIDE.md", SKILL):
            pair = [
                sentence
                for sentence in ten_day_sentences(path.read_text())
                if TEN_DAY_COLLECTIVE.search(sentence)
            ]
            with self.subTest(entry_document=path.name):
                self.assertTrue(
                    pair,
                    f"{path.name} no longer tells the reader there are two "
                    "10-day windows at all, so nothing points at the "
                    "difference between them",
                )

    @staticmethod
    def _ten_day_defect(sentence: str) -> str:
        """The reason one sentence conflates the clocks, or "" if it does not.

        Returned as a string rather than raised, so the corpus scan above and
        the invented-input probe below apply the identical rule to a real
        sentence and to a planted one. A guard checked only against the tree it
        already passes cannot tell "clean" from "neutered".
        """
        named = ten_day_clocks_named(sentence)
        # Two periods in one sentence - counted as a pair ("the two 10-day
        # windows") or written out twice - has to distinguish them.
        both = bool(TEN_DAY_COLLECTIVE.search(sentence)) or (
            len(TEN_DAY_MENTION.findall(sentence)) > 1
        )
        if both and named != {"registration", "portal"}:
            return (
                "refers to both 10-day periods at once but names "
                f"{sorted(named) or 'neither'} - the reader is told there are "
                "two and left to guess what distinguishes them"
            )
        if not named:
            return (
                "mentions a 10-day period without naming which - the access "
                "code's 10 days to register, or the 10 days of portal access "
                "that registering starts"
            )
        return ""

    def test_the_ten_day_guard_fails_on_a_planted_conflation(self) -> None:
        """The tree being clean says nothing about what the rule can see.

        Every input here is invented. The first group must be refused or the
        guard has been neutered into a rule that passes whatever it is given;
        the second must be accepted or it has been tightened into a rule that
        pushes authors away from the presentations that distinguish the clocks
        best - which is the failure this revision exists to correct, and the
        one a clean tree hid, because the tree simply had no bullet list or
        table row that mentioned a 10-day period.
        """
        for conflated in (
            "The key stops working 10 days later.",
            "Read `references/run-safety.md` for the two 10-day windows.",
            "Both ten-day clocks are covered in the reference.",
            "The access code gives you 10 days, and 10 days is also all you get "
            "afterwards.",
        ):
            with self.subTest(conflated=conflated):
                self.assertNotEqual(
                    self._ten_day_defect(conflated),
                    "",
                    f"the guard accepts {conflated!r}, which does not say "
                    "which 10-day period it means - it has been neutered",
                )

        for clear in (
            # The sentence the previous rule refused, and the reason it was
            # wrong: both clocks named, in order to contrast them.
            "The access code's 10 days to register are not the same as the 10 "
            "days of portal access that registering starts.",
            "A single-use access code is valid for 10 days.",
            "Portal access lasts 10 days from the moment you register.",
            "The two ten-day windows: the access code, then portal access.",
        ):
            with self.subTest(clear=clear):
                self.assertEqual(
                    self._ten_day_defect(clear),
                    "",
                    f"the guard refuses {clear!r}, which names its clock - a "
                    "false red here teaches authors to write the vaguer "
                    "sentence, which is the defect",
                )

        # And the splitter reaches the shapes it used to glue together. A
        # bullet list and a table row each carry one clock per unit; joined into
        # one string they read as a single sentence naming both, which the old
        # `.!?` splitter did and which made a correct list look like a
        # conflation - and, with the rule relaxed, would now make a genuine
        # conflation look correct. Both directions are checked.
        bullets = (
            "- The access code expires 10 days after it is issued\n"
            "- Portal access then runs for 10 days from registration\n"
        )
        self.assertEqual(
            [self._ten_day_defect(s) for s in ten_day_sentences(bullets)], ["", ""]
        )
        table = (
            "| Window | Length |\n"
            "| --- | --- |\n"
            "| Access code | 10 days |\n"
            "| Portal access | 10 days |\n"
        )
        self.assertEqual(
            [self._ten_day_defect(s) for s in ten_day_sentences(table)], ["", ""]
        )
        blurred = (
            "- The code expires 10 days after it is issued\n" "- You then get 10 days\n"
        )
        self.assertEqual(len(ten_day_sentences(blurred)), 2)
        self.assertTrue(
            all(self._ten_day_defect(s) for s in ten_day_sentences(blurred))
        )
        # Hard-wrapped prose still arrives whole: split on newlines alone, this
        # sentence becomes two halves that each name one clock and neither
        # mentions both, so a real conflation across a line break would pass.
        wrapped = (
            "The access code's 10 days to register are not the same as the\n"
            "10 days of portal access that registering starts.\n"
        )
        self.assertEqual(len(ten_day_sentences(wrapped)), 1)
        self.assertEqual(self._ten_day_defect(ten_day_sentences(wrapped)[0]), "")

    def test_retired_lead_funnel_vocabulary_is_absent(self) -> None:
        """`lead_token` and the two-path framing are gone, not renamed.

        A single-use access code carries the registration authorization, so
        there is no second bearer credential and no cold-start branch beside
        it. These phrases described the retired model; if one reappears the
        guide has drifted back to teaching a path that no longer exists.

        The corpus is `conversation_contract_documents()`. It was a fourth
        hand-rebuilt list - SKILL.md plus the references - which left out
        GUIDE.md, `assets/run-plan.md`, and README.md: the entry point, the
        record the user keeps, and the most-read file in a public repository.
        A retired phrase reappearing in any of them was invisible here by
        construction, which is the omission `assistant_facing_documents()`
        exists to stop being made a fourth time.
        """
        combined = "\n".join(
            path.read_text() for path in conversation_contract_documents()
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
        Separately, the SDK exposes no supported id
        for the run just completed, and the fix for that belongs upstream: this
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
            # Was "traigent/traigent issue 2020". The guidance may not carry an
            # internal issue number at all, so what is pinned is the decision -
            # the fix is upstream's and this repo must not route around it.
            "tracked upstream and the fix belongs there",
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

    def test_held_out_set_is_part_of_the_default_run_and_disclosed_seamlessly(
        self,
    ) -> None:
        """#127/#141: the holdout comes back, sized ten, disclosed once.

        Israel's call: keep the held-out set (removing it hides the winner's-
        curse evidence, not the problem), but never claim Traigent prevents
        overfitting (holdout support is not yet a real SDK feature) and never
        call a ten-row gap "overfitting" (it is inconclusive at that sample
        size). The split is reserved at dataset creation - same as the tuning
        rows - but its score stays undisclosed until stage 8's closing report,
        never at the stage-7 local baseline checkpoint, so a first run shows
        one comparison once rather than an empty promise twice.
        """
        documents = {
            "guide": " ".join((ROOT / "GUIDE.md").read_text().casefold().split()),
            "skill": " ".join(SKILL.read_text().casefold().split()),
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
                self.assertNotIn("create 18 tuning examples by default", text)
                self.assertNotIn("do not create a held-back validation set", text)
                self.assertNotIn("optional follow-up evidence", text)

        dataset = documents["dataset"]
        for phrase in (
            "create 28 examples by default: 18 tuning rows",
            "10 held-out rows (2 easy, 3 medium, 3 hard, 2 very hard)",
            "held-out set and claims",
            "selecting on the tuning rows inflates the tuning score",
            "ten rows cannot resolve a small gap",
            "do not say traigent prevents or corrects this",
            'do not call a gap in this range "overfitting,"',
            "never surface a repository, issue, or tracker reference to the user",
            "tuning set (<n> ex)",
            "held-out set (<m> ex)",
            "<m> examples cannot settle",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, dataset)

        self.assertIn("28 rows split 18 tuning / 10 held-out", documents["glossary"])
        # The glossary promised a check ten rows cannot perform, with no caveat
        # - while the entry two lines below it carried one. It also called an
        # 18/10 split "two halves" and offered the user three competing name
        # pairs for the same rows.
        glossary = documents["glossary"]
        for phrase in (
            "they cannot measure how much better one configuration is than another",
            "it can show a winner still works outside the rows it was chosen on "
            "and cannot measure by how much",
            "two parts of your examples, not equal halves",
            'say "tuning set" and "held-out set" to the user',
        ):
            with self.subTest(glossary_phrase=phrase):
                self.assertIn(phrase, glossary)
        self.assertNotIn("two halves of your examples", glossary)
        self.assertIn("disclosed once, beside the", documents["glossary"])

        skill = documents["skill"]
        checkpoint_index = skill.find(
            "do not disclose the held-out score before stage 8"
        )
        report_index = skill.find(
            "the recommended configuration's held-out score and small-sample note, "
            "shown here first"
        )
        self.assertGreaterEqual(checkpoint_index, 0)
        self.assertGreaterEqual(report_index, 0)
        self.assertLess(
            checkpoint_index,
            report_index,
            "the stage-7 checkpoint's refusal to disclose must precede stage "
            "8's actual disclosure, or the seamless ordering is not encoded",
        )
        self.assertIn("score only that one against the ten held-out rows", skill)
        self.assertIn(
            "verify the held-out score belongs to the one configuration this run "
            "recommends",
            skill,
        )

        self.assertIn(
            "discloses the enhanced winner's held-out score here", documents["guide"]
        )

        run_plan = " ".join(
            (SKILL_ROOT / "assets" / "run-plan.md").read_text().casefold().split()
        )
        for phrase in (
            "tuning rows and held-out rows (default 10, reserved at creation)",
            "local baseline checkpoint",
            "successful cli url, or `local-only` with reason",
            "baseline-versus-enhanced comparison - measured tuning behavior",
            "held-out score for the recommended configuration, the round it came "
            "from, its tuning score, the held-out set's real/generated counts, "
            "and the small-sample note",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, run_plan)

    def test_ten_held_out_rows_are_the_design_not_a_placeholder(self) -> None:
        """The owner's rule: ten rows, composed 2/3/3/2, topped up if needed.

        The first reinstatement told the assistant that growing the split past
        ten was tracked as a Traigent-owned follow-up, which made the size read
        as a placeholder someone would fix. It is not. Every further row is
        another paid call on the winner, and the honest answer to the noise
        that leaves is to say so. The composition therefore applies wherever
        the rows come from, real data is topped up rather than allowed to drop
        a band, and the display quotes counts because a percentage on ten rows
        claims ten times the resolution it has.

        THE PUBLISHED REASON USED TO BE THE SCORER'S FLOOR, and it was wrong
        twice over. The document said ten is "where the readiness score puts
        its own floor: at nine comparable rows it raises
        `dataset-below-measurable-size` and blocks the paid comparison". That
        was true of the scorer on this branch and false on #149, which makes
        the same cap advisory above zero scoreable rows - measured:
        `power_ceiling(9).blocks` is True here and False there, while
        `power_ceiling(0)` still blocks on both. So the customer-facing reason
        for the owner's number was a scorer detail an open branch was already
        changing, and the number is not changing.

        The reason is difficulty coverage, which is a property of the split
        itself and of nothing else: four bands, and the two that separate
        configurations most carry three rows each. That is what is asserted
        below - the arithmetic of the composition, executed, rather than the
        presence of a slug in a sentence.

        And that is the second half of the defect. This test used to prove the
        rationale by finding the string `dataset-below-measurable-size` in the
        prose. Greping a condition id out of a document asks whether somebody
        WROTE the claim, never whether the code DOES it - so the document and
        the scorer could disagree for as long as the sentence stayed put. The
        scorer is called here instead, and the two things it is called about
        are the two things the prose is now allowed to depend on.
        """
        dataset = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            # Ten is a decision, with the reason the guide previously promised
            # and never gave.
            "ten rows is the design, not a placeholder",
            "ten is what the composition costs",
            "the full picture comes from running the whole dataset over a wider knob space",
            # One composition, applied wherever the rows come from.
            "that composition holds wherever the rows come from",
            # Top up rather than drop a band - with what it costs.
            "top each set up to its composition with generated rows rather than "
            "dropping a band",
            "cannot show that the winner generalizes to real inputs",
            # A standard error is labelled as one, beside the interval.
            "one *standard error*",
            "a 95% interval is roughly twice that",
            # Counts, at the size where a percentage lies.
            "report counts, not percentages, while the split is this small",
            "can land lower, level, or higher",
            # The paired-count discipline belongs on the small case, not off it.
            "this is required on the ten-row default, not only above it",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, dataset)
        self.assertNotIn("growing the holdout past the default ten rows", dataset)
        # No minimum detectable effect, per the same decision: the guide still
        # refuses to invent a threshold before paired outcomes exist.
        self.assertIn(
            "never invent a percentage-point threshold before those outcomes exist",
            dataset,
        )
        # "Ten" and "at least ten" are different rules, and the file carried
        # both shapes: a fixed composition beside a sentence about adjusting
        # size. Say which of the two the number is.
        self.assertIn("ten is therefore exact in both directions", dataset)

        # 1. THE ARITHMETIC, EXECUTED. The composition is read out of the
        # document the assistant follows, not restated here, and then it is
        # made to do what the paragraph claims: it sums to ten, it covers all
        # four bands, and removing any single row drops some band to one. That
        # last is the whole argument for ten over nine, and it is a fact about
        # the split rather than about any scorer.
        composition = re.search(
            r"reserve (\d+) held-out rows \((\d+) easy, (\d+) medium, "
            r"(\d+) hard, (\d+) very hard\)",
            dataset,
        )
        self.assertIsNotNone(
            composition,
            "the held-out composition is no longer stated where a reader meets "
            "the split, so nothing here can check what ten buys",
        )
        total, *bands = (int(group) for group in composition.groups())
        self.assertEqual(sum(bands), total)
        self.assertEqual(total, 10)
        self.assertEqual(len(bands), 4)
        # No band has a spare row: the smallest is exactly two, which is the
        # smallest a band can be and still be measured rather than sampled. If
        # any band had three or more to give, ten would not be the cost of this
        # composition and the paragraph's reason would be wrong.
        self.assertEqual(
            min(bands),
            2,
            f"the smallest band holds {min(bands)} rows, so the split has a "
            "spare and ten is not what this composition costs",
        )
        outer, middle = (bands[0], bands[3]), (bands[1], bands[2])
        self.assertTrue(
            min(middle) > max(outer),
            f"the middle bands hold {middle} against the outer {outer}; the "
            "paragraph says the two that separate configurations most carry "
            "more, and they do not",
        )

        # 2. THE SCORER, ASKED RATHER THAN QUOTED. The published rationale used
        # to cite `dataset-below-measurable-size` blocking at nine. It must not
        # again, because that is the scorer's decision and #149 changes it -
        # the number here does not move when it does. What IS pinned is the
        # only claim the paragraph still leans on: the designed split is not
        # sitting on a blocking cap.
        self.assertNotIn("dataset-below-measurable-size", dataset)
        self.assertNotIn("blocks the paid comparison", dataset)
        designed = READINESS.power_ceiling(total)
        self.assertFalse(
            designed is not None and designed.blocks,
            f"the designed {total}-row split is itself blocked by "
            f"{designed.condition if designed else None}; the composition and "
            "the scorer disagree about the size this guide reserves",
        )
        self.assertIn("never a floor to grow from", dataset)
        # The one split that is not ten is a project's own, and the document no
        # longer tells the reader what the scorer will do to it. It used to -
        # "a split under ten comparable rows blocks the paid comparison
        # wherever it came from" - which is the same borrowed-threshold defect
        # a second time in the same paragraph, and false on #149 in the same
        # way. What is said instead is the only thing this guide decides about
        # somebody else's split: it is used as it stands.
        self.assertIn(
            "kept at the size it already has, whatever its composition", dataset
        )

    def test_real_rows_are_divided_between_both_sets_before_anything_is_generated(
        self,
    ) -> None:
        """The customer's rows go to both splits, in proportion, first.

        "Top up the shortfall" says how many generated rows to add and is
        silent on which set gets the real ones - so both degenerate fills were
        available and neither was refused. The reserved split is cut "at
        creation time, before any component design", which reads as reserve the
        real rows first; "user-provided examples expanded into additional
        tuning candidates" reads as the opposite. One of those leaves a
        held-out set of nothing but generated rows, which cannot say anything
        about real inputs - it only shows the winner survives rows the search
        never saw - and the other leaves the search optimizing a task the
        customer does not have.

        So the division is stated as a rule with an arithmetic the assistant
        cannot read two ways, and both failure directions are named beside it.
        The proportion is the sets' own: at the 18/10 default, roughly two real
        rows to tuning for every one held back.
        """
        dataset = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        self.assertIn(
            "**real rows reach both sets before either is topped up.**", dataset
        )
        for phrase in (
            # The rule, and the ordering that makes it a rule rather than a
            # preference: divide before generating, not after.
            "divide the real ones between them in the same proportion as the "
            "sets themselves, rounding in the tuning set's favour, before a "
            "single row is generated",
            # The owner's own worked example, and the two smaller ones that
            # pin the rounding direction.
            "ten real rows split seven and three",
            "four split three and one",
            "two split one and one",
            # Below two there is nothing to divide, and the tie-break is said
            # rather than left to the reader.
            "below two there is nothing to divide",
            # Both degenerate fills are refused, not just the one that is
            # easier to picture.
            "in both directions",
            "a held-out set of generated rows validates nothing about real inputs",
            "a tuning set of generated rows searches a task the customer does not have",
            # The composition survives the division.
            "placing each real row in the band its own difficulty puts it in",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, dataset)
        # And the closing report says the mixture out loud, because "held out"
        # is a claim about what the search saw, not about where a row came
        # from - a reader who is not told hears the second one.
        self.assertIn(
            "when the split was topped up, say so on the same line as its score",
            dataset,
        )
        # The counts themselves are stated once, in the details layer that owns
        # the whole mixture - see the row-provenance test below. The score line
        # points at them rather than repeating them.
        self.assertIn("the details layer below carries the counts", dataset)
        self.assertIn(
            "how many rows are the customer's and how many this run generated",
            dataset,
        )

    def test_the_close_says_where_the_two_written_files_are(self) -> None:
        """A user who wants the reserved rows gone has to be told where they are.

        The run writes two files the user did not ask for. Naming them only as
        `holdout.jsonl` tells a reader what the assistant called it, not where
        to look on their own disk, so the path is absolute the way every other
        path this guide asks a user to act on is absolute.

        The offer is only safe because their own dataset was never edited, so
        the conclusion is stated locally - not the preservation mandate, which
        has a home. And it is placed: the closing summary leads with the
        outcome and one recommendation, and file housekeeping competing with
        that is the "menu instead of a recommendation" the flow already
        refuses.
        """
        dataset = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "name both written files in the closing summary's details layer, "
            "by absolute path",
            "`<project root>/traigent-runs/tuning.jsonl`",
            "`<project root>/traigent-runs/holdout.jsonl`",
            "so a user who wants them gone knows which file to open",
            # Nothing is moved out and nothing is returned - the unease the
            # owner named, answered with what the run actually does. Verified
            # against the code: the bundled scripts write only the report path
            # they are given, and every repair path is a working copy.
            "both are derived: their dataset was read and rows were copied out of it",
            "nothing was moved and nothing has to be put back",
            "the original was never modified, lost no row, and stays the canonical copy",
            # Safe rather than alarming: the local conclusion, not the mandate.
            "so deleting either derived file loses nothing",
            # Placed below the outcome, not beside it.
            "it goes below the outcome and the recommendation, never beside them",
            # The one thing that IS stranded, told rather than done. Nothing
            # in the close said this before: the run repairs into a working
            # copy, reports the better score, and the user's own file keeps
            # the defect.
            "only the user can carry it",
            "their own dataset still has the defect this run worked around",
            "name what changed and in which rows, and leave applying it to them",
            "offer it; never write it",
            # Three kinds of row, kept apart. A repaired row is the customer's
            # with a field changed; a generated row is this run's. Collapsing
            # them into one "modified" bucket answers a question nobody asked
            # and loses the one they did.
            "those are three kinds of row",
            "a row the customer brought, a row of theirs this run repaired",
            "and a row this run generated",
            'merging them into one "modified" bucket destroys the only answer',
            "a repair changed a field, not an origin, so that row is still theirs; "
            "only a generated row is ours",
            # The mixture is stated as a mixture, with counts and ids - and as
            # counts rather than a path, because there is no third file.
            "give each set its own line saying it as a mixture",
            "how many rows are the customer's and how many this run generated, "
            "with the generated ids",
            "interleaved with the real ones; there is no third file to point at",
            # Reusing what exists, per the owner: no new vocabulary, no new file.
            "the provenance fields the rows already carry and the id lists this "
            "run already writes",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, dataset)

    def test_the_close_lists_every_file_this_run_wrote(self) -> None:
        """Two of the files were disclosed; the rest were not written by nobody.

        The disclosure above named the two dataset splits, which is the pair a
        reader is most likely to worry about - but the run also writes a run
        plan, a config-space document, two calibration files, sometimes a
        substitute agent or evaluator, sometimes a readiness report, and the
        SDK's own logs. A user who wants to know where everything went, to keep
        it or to delete it, should not have to ask a second time.

        The writes OUTSIDE `traigent-runs/` are the half that needs a guard
        rather than a phrase, because "delete the folder and nothing is lost"
        is true of the folder and false of every one of them, and an omission
        there reads exactly like completeness.

        The count is checked against SKILL.md's authorization table, not
        against a tuple written here. Comparing the prose to this test's own
        list is the producer agreeing with itself: it fails when an instruction
        disappears and passes silently when SKILL.md gains a new write outside
        the folder, which is exactly what happened twice. Installing the pinned
        set into an environment this run did NOT create mutates site-packages
        wherever that environment lives - SKILL.md authorises it behind one
        confirmation, and run-safety.md says a current-project environment
        managed outside the root is an external candidate - and the credential
        handoff to a user-named file is outside the project by definition.
        Neither was disclosed, and the sentence said "three".

        So every row of that table is classified here, on one side or the
        other, and a row that is neither fails. That is the shape
        `CAP_NO_IMPLICATION` already uses in the scorer, for the same reason: a
        list of positives cannot tell "checked, and it writes nothing outside"
        from "nobody looked".
        """
        # One entry per WRITE, not per table row, because the count in the prose
        # counts writes and one row authorises two of them. Each names the
        # SKILL.md action-class cell that authorises it, so a reworded row fails
        # here until it is re-classified rather than dropping out of the check.
        writes_outside_the_run_folder = (
            (
                "the /traigent-runs/ ignore line",
                "Create `traigent-runs/` artifacts; when the project root is "
                "inside a Git worktree, add `/traigent-runs/` to the "
                "project-root `.gitignore`",
                ("`.gitignore`",),
            ),
            (
                # When the file did not exist, the run wrote all of it, so the
                # disclosure owes the stronger true statement.
                "the provider key in .env",
                "Create or update a minimal `.env`",
                ("`.env`", "whole file"),
            ),
            (
                # Same row, different write: "use the user-named handoff or
                # target `.env`", and a file the user names is outside the
                # project by definition.
                "the credential handoff to a user-named file",
                "Create or update a minimal `.env`",
                ("the user named a file of their own",),
            ),
            (
                "the virtual environment this run created",
                "Create an isolated environment",
                ("`.venv`",),
            ),
            (
                # Not the environment - the packages. Deleting a run-created
                # `.venv` undoes this; installing into a reused one, which
                # SKILL.md authorises behind one confirmation and run-safety.md
                # says may sit outside the project root, leaves it behind.
                "the pinned packages in an environment this run did not create",
                "Install dependencies in the isolated environment",
                ("an environment this run did not create",),
            ),
        )
        # Rows that write nothing the close has to hand over: nothing at all,
        # only inside `traigent-runs/`, or only where the user already decided.
        writes_nothing_to_disclose_here = {
            "Read-only discovery and static validation",
            "Repair a working copy after the user chooses repair",
            "Change real labels, expected answers, examples, or rubric policy",
            "Execute an evaluator or mock check",
            "Make provider, private-data, connected Traigent, or external calls "
            "other than the narrow dependency fetch",
            "Perform destructive or production-affecting actions",
        }
        authorization = (
            SKILL.read_text()
            .split("## Action authorization", 1)[1]
            .split("\n## ", 1)[0]
        )
        rows = []
        for line in authorization.splitlines():
            line = line.strip()
            if not line.startswith("|") or set(line) <= set("|- "):
                continue
            action = " ".join(line.strip("|").split("|")[0].split())
            if action.casefold() == "action class":
                continue
            rows.append(action)
        self.assertTrue(rows, "the authorization table is no longer parseable")
        self.assertEqual(
            set(rows),
            {row for _, row, _ in writes_outside_the_run_folder}
            | writes_nothing_to_disclose_here,
            "an authorization row is on neither side: say whether it can leave "
            "something outside `traigent-runs/`, and disclose it in the close "
            "if it can",
        )
        counts = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}

        text = (
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
        )
        paragraphs = [" ".join(block.split()) for block in text.split("\n\n")]
        disclosures = [
            p for p in paragraphs if "not the only files this run wrote" in p
        ]
        self.assertEqual(len(disclosures), 1, "the file disclosure has one home")
        disclosure = disclosures[0]

        # Inside the folder: every path the guidance instructs the run to write.
        #
        # Written with the `traigent-runs/` prefix, which is how the rest of
        # this corpus names a run artifact and what the disclosure paragraph now
        # says. A bare basename was ambiguous in both directions: `run-plan.md`
        # is also the bundled template at `assets/run-plan.md`, and the guard
        # that every named file must resolve reported all six as files nothing
        # provides. What this test pins is unchanged - that the close names
        # every file the run writes - and the prefix is the spelling that makes
        # each one findable.
        for path in (
            "`traigent-runs/run-plan.md`",
            "`traigent-runs/config-space.json`",
            "`traigent-runs/calibration-cases.json`",
            "`traigent-runs/calibration-results.json`",
            "`traigent-runs/walkthrough_agent.py`",
            "`traigent-runs/evaluator.py`",
            "readiness report",
            "sdk run logs",
        ):
            with self.subTest(path=path):
                self.assertIn(path, disclosure)
        for phrase in (
            # Only what exists - the run does not write all of these every time.
            "name only what was actually written",
            "that whole folder is git-ignored and can be deleted without losing anything",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, disclosure)

        # Outside the folder: the artifacts deleting it does not remove.
        head, _, outside = disclosure.partition("writes sit outside the folder")
        self.assertTrue(
            outside, "the close must still say what survives deleting `traigent-runs/`"
        )
        for write, action, disclosed in writes_outside_the_run_folder:
            for token in disclosed:
                with self.subTest(write=write, token=token):
                    self.assertIn(
                        token.casefold(),
                        outside,
                        f"SKILL.md authorises {action!r}, which leaves {write} "
                        "outside `traigent-runs/`, and the close does not "
                        "disclose it",
                    )
        stated = head.split()[-1]
        self.assertIn(stated, counts, f"the count of outside writes reads {stated!r}")
        self.assertEqual(
            counts[stated],
            len(writes_outside_the_run_folder),
            "the stated count and SKILL.md's authorization table disagree about "
            "how many writes land outside `traigent-runs/`",
        )

    def test_an_installed_skill_is_disclosed_as_needing_a_fresh_session(self) -> None:
        """A skill installed mid-run is not usable in the run that installed it.

        Skills load when a session starts, so the handoff hands over something
        that does nothing until the user restarts - and "installed" reads as
        "ready" to everyone who has not been told otherwise. It sits with the
        file list because that is where the user is already asking what this
        run left behind and what to do with it - which is also why it has to
        say where the install landed and that removing it means deleting that
        directory: it is the one artifact that lands outside the project.

        Where it lands is the assistant's to read off the install, not this
        repository's to state: no document here records an install path, so a
        literal one in the guidance would be invented. That is asserted as an
        absence, because a fabricated path is indistinguishable from a real
        one to every reader who has not gone looking.
        """
        text = (
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
        )
        paragraphs = [" ".join(block.split()) for block in text.split("\n\n")]
        handoffs = [
            p for p in paragraphs if "inert in the session that installed it" in p
        ]
        self.assertEqual(
            len(handoffs), 1, "the installed-skill disclosure has one home"
        )
        handoff = handoffs[0]
        for phrase in (
            "skills load when a session starts",
            "start a new session, or refresh this one, and they are available",
            # Located, and removable - not just discussed.
            "name the absolute directory the install wrote to",
            "it is outside the project",
            "removing a skill means deleting that directory",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, handoff)
        invented = re.search(r"[~/][\w.\-/]*skills", handoff)
        self.assertIsNone(
            invented,
            f"the close names an install path this repository never documents: {invented}",
        )

    def test_generated_rows_are_not_re_judged_against_their_own_inputs(self) -> None:
        """The logical row check is for rows a human wrote, not rows we wrote.

        Re-judging a generated row asks the model to grade its own homework,
        and it buys no claim the corpus could make anyway: the synthetic
        ceiling already bounds what a generated dataset may be quoted for, so
        a second model judgement on top of it changes nothing and can only add
        a false sense of having verified something.

        Scoped in exactly one place, because a rule repeated as a caveat in
        several is the drift these tests exist to catch.
        """
        dataset = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "runs on rows the customer brought and skips rows this run generated",
            "the synthetic ceiling already bounds what a generated corpus may claim",
            "the model marking its own homework",
            # Named positively too, so the scope reads as a purpose rather than
            # as an exemption someone can argue back out of.
            "that check exists for the other case, where a human wrote the pairing",
            "stated once, here",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, dataset)

    def test_the_close_says_what_a_full_capability_run_would_do(self) -> None:
        """The ten rows are a teaching choice, said forwards rather than implied.

        The size decision is unchanged - ten, exact in both directions, for the
        reasons the sizing paragraphs above already give. What was missing is
        the positive half: the guide left "this is only a walkthrough" to be
        inferred from a caveat, which reads as a limitation being apologised
        for rather than as a step being demonstrated cheaply.

        Two brakes, because this sentence is the one most likely to become a
        pitch. It may not apologise for the ten rows, and it may not say what a
        larger run would return - only what it would do. The route to it is the
        skills handoff the close already carries, pointed at rather than
        restated.
        """
        dataset = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        for phrase in (
            "at full capability this same check runs over the customer's whole dataset",
            "that is where real-world validation actually happens",
            "showing the shape of that step cheaply rather than performing it",
            "which is a choice and not a shortfall",
            "without apologizing for the ten rows and without saying what a "
            "larger run would find",
            "the close's skills handoff is already the route to it",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, dataset)
        # It sits beside the small-sample caveat and does not replace it: the
        # backward-looking half stays exactly as it was.
        self.assertIn("ten rows cannot resolve a small gap", dataset)
        self.assertLess(
            dataset.index("keep the note only while one row still moves"),
            dataset.index("at full capability this same check runs"),
        )
        # And it does not reopen the size decision it explains.
        self.assertIn("ten is therefore exact in both directions", dataset)

    def test_one_configuration_is_selected_on_tuning_and_only_it_is_held_out_scored(
        self,
    ) -> None:
        """The held-out rows report on a choice; they never make one.

        The owner asked what happens when a later measurement comes back
        worse, and answered it with "run both at the very end of the test set".
        Running two configurations on the reserved rows and keeping the better
        one is selection, and a set used for selection is not held out - its
        number would carry exactly the optimism the tuning score carries, which
        is the one failure this split exists to prevent.

        The intent underneath is right and was unmet: the recommendation was
        the enhanced search's winner by position rather than by score, so a
        baseline that still beat it on the tuning rows lost anyway. Both paid
        measurements now compete, on the rows already spent on selection, and
        exactly one configuration reaches the reserved rows.

        The owner's Pareto instinct lands on the tuning side, where it is
        legitimate: at equal score, prefer the cheaper configuration.
        """
        dataset = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        skill = " ".join(SKILL.read_text().casefold().split())
        # One configuration, selected on the tuning scores across both paid
        # measurements - not on position.
        for phrase in (
            "score the held-out rows once, on one configuration: the one this run recommends",
            "select it on the **tuning** scores across both of them",
            "the enhanced search's winner is not the answer by position",
            "when the baseline's best configuration still scores higher on the "
            "tuning rows, that is the one this run recommends",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, dataset)
        # The correction, stated plainly enough that the mechanism cannot be
        # rebuilt by someone reading only this section.
        self.assertIn("**the held-out rows arbitrate nothing.**", dataset)
        self.assertIn(
            "scoring two configurations on them and keeping whichever came back "
            "higher is selection, and a set used for selection is not held out",
            dataset,
        )
        self.assertIn("it does not choose one", dataset)
        # The tie-break the owner asked for, kept on the side that may have it.
        self.assertIn(
            "when two configurations score the same on the tuning rows, prefer "
            "the cheaper one; at equal cost prefer the stronger model",
            dataset,
        )
        self.assertIn(
            "that is a decision taken on the rows selection is allowed to use", dataset
        )
        # SKILL.md carries the ordering mandate, and says which rows may not
        # decide it.
        self.assertIn(
            "select the configuration this run recommends on the **tuning** scores "
            "across both paid measurements - never on the held-out rows, which "
            "arbitrate nothing",
            skill,
        )
        self.assertIn(
            "verify the held-out score belongs to the one configuration this run "
            "recommends, chosen on the tuning scores, and that no other candidate "
            "was scored on those rows",
            skill,
        )

    def test_two_files_is_a_recorded_choice_not_an_sdk_limitation(self) -> None:
        """Why the reserved rows get a file, answered where the rule lives.

        `eval_dataset` accepts rows as well as a path on the pinned SDK, so
        "just choose which rows go where" is a real alternative rather than a
        misunderstanding. It is declined for a reason the guide has to carry or
        the next reader re-opens it: a filter is a predicate that has to keep
        being right, and this package already lost the reserved rows exactly
        once, when they sat inside the file the search was handed. Two files,
        beside an untouched original, is also the honest answer to "sounds like
        many files".
        """
        dataset = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        self.assertIn(
            "two files is a choice, not a limitation the sdk imposes", dataset
        )
        self.assertIn("`eval_dataset` also takes rows directly", dataset)
        self.assertIn(
            "a file the search was never given cannot leak a row however the "
            "predicate drifts",
            dataset,
        )
        self.assertIn("beside the user's untouched original", dataset)

    def test_the_difficulty_ladder_has_four_rungs_and_one_home(self) -> None:
        """Rank the rows before falling through to a random sample.

        The ladder used to go difficulty tags -> coverage/scenario tags ->
        seeded random, which discarded a judgement the assistant had already
        made: it is reading the rows in order to pick from them, so it can rank
        them, and it can ask whether the other tags differ in difficulty at all
        rather than assuming they do. Two rungs go in between.

        Both new rungs need a brake. "Clear" is a feeling unless something can
        refute it, so the school-levels test asks the estimate to separate the
        extremes rather than order the middle. And an estimate is the
        assistant's opinion: declared through the provenance machinery this file
        already has, and kept out of the scored `difficulty` field on rows the
        user brought, because filling that field would clear a spread complaint
        on the assistant's own judgement.

        One home, because the ladder had two: the bounded subset and the
        reserved split each stated it, which is the shape of every contradiction
        this package has produced.
        """
        dataset = " ".join(
            (SKILL_ROOT / "references" / "evaluation-and-dataset.md")
            .read_text()
            .casefold()
            .split()
        )
        self.assertIn("### choosing rows when difficulty is not labelled", dataset)
        for rung in (
            "**the rows carry difficulty tags.** stratify on them.",
            "**rank the rows yourself.**",
            "**the rows carry other tags**",
            "**neither holds.** take a seeded random sample",
        ):
            with self.subTest(rung=rung):
                self.assertIn(rung, dataset)
        # Rung 3 judges the tags before trusting them, and names what it got
        # when they turn out not to differ.
        self.assertIn(
            "judge by that same test whether those groups actually differ in difficulty",
            dataset,
        )
        self.assertIn("call that topical spread, not difficulty spread", dataset)
        # The falsifier, in the owner's own framing.
        for phrase in (
            "difficulty is clear when the bands differ the way school levels differ",
            "12-to-15-year-old",
            "short single-table sql query against a long multi-join one",
            '"clear" has to be falsifiable or it is a feeling',
            "separate the extremes, not to order the middle",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, dataset)
        # An estimate is declared, and cannot buy the difficulty sub-score.
        self.assertIn("`difficulty_provenance`", dataset)
        self.assertIn(
            "on rows the user brought, keep it out of the `difficulty` field itself",
            dataset,
        )
        self.assertIn(
            'filling it converts "declares no difficulty" into full band coverage',
            dataset,
        )
        # The exemption is deliberate and is stated with its reason, so it
        # cannot later read as an oversight and be closed: on a generated row
        # the band is not an estimate about someone else's data, it is part of
        # what was written, and the row already declares itself generated.
        self.assertIn("a generated row is the other case", dataset)
        self.assertIn("whoever wrote the question wrote its band too", dataset)
        self.assertIn("the row already declares itself generated", dataset)
        # One home: both call sites point at the ladder rather than restating
        # it, and the restatements they replaced must not come back.
        self.assertIn(
            'work down the ladder in "choosing rows when difficulty is not labelled"',
            dataset,
        )
        self.assertIn("work down the same ladder the bounded subset uses", dataset)
        for restatement in (
            "spread the pick across the coverage/scenario tags instead",
            "fall back exactly as the bounded subset above does",
        ):
            with self.subTest(restatement=restatement):
                self.assertNotIn(restatement, dataset)

    # There is no allowlist any more, and its absence is the point. It held
    # three exact citations - engineering rationale that "predates this rule" -
    # and every one of them named a repository or an issue number in a file the
    # installed skill ships. A citation that must not reach a customer is not
    # made safe by being old, and with nothing published there is no citation
    # this repository is stuck with, so the three sentences were rewritten to
    # say what they meant: the defect is upstream's and the fix belongs there.
    #
    # It was also the guard's own hole. `Tracked upstream as Traigent/Traigent
    # issue 1993.` sat on the allowlist while `Traigent/Traigent#1993` - the
    # same reference, in the commoner spelling - matched no pattern at all, so
    # the allowlist documented the exact form the guard could see and said
    # nothing about the form it could not.
    TRACKER_CITATION_ALLOWLIST: tuple[str, ...] = ()
    # Every shape a tracker citation is written in, not the two that happened to
    # be in the tree when this was written. Those two were `traigent-first-run#N`
    # and `traigent/traigent issue N`; measured against ten realistic spellings
    # they caught two. `Traigent/Traigent#1993` walked straight through - the
    # hash form of a string already on the allowlist above, spelled for the
    # other repository - as did a full issue URL, an owner-qualified private
    # repository, and a bare `issue #127`.
    #
    # What is deliberately NOT here is a bare `#\d+` on its own. That was the
    # first repair attempted, on the theory that "`#` glued to digits is an
    # issue reference and nothing else in customer-facing guidance". It is not:
    # measured, it fails the standard markdown cross-link
    # `[stage 3](../SKILL.md#3-complete-the-system)` - SKILL.md has eight
    # numbered stage headings, so that anchor is correct authoring - and the
    # ordinary sentence "If trial #3 fails, stop and report it", along with
    # `run #1`, `configuration #7` and `step #2`. In a walkthrough that counts
    # stages, trials, rows and configurations that is not an exotic input, and
    # the failure message would have said "carries a tracker reference" about a
    # sentence that carries none. A guard that misdiagnoses its own trigger
    # teaches the author to route around it.
    #
    # The discriminating signal is a REPOSITORY, or a tracking word in front of
    # the hash. Both are things a citation has and a count does not.
    TRACKER_REFERENCE = re.compile(
        # `traigent-first-run#78`, `Traigent/Traigent#2101`, and an owner
        # segment followed by any sibling repository - which this comment
        # cannot spell out, because the disclosure check further up this file
        # refuses exactly that shape. The owner segment is optional.
        r"(?:[\w.-]+/)?[\w.-]*traigent[\w.-]*#\d+"
        # The prose form: `<repo> issue 1993`, `<repo> pull 42`.
        r"|(?:[\w.-]+/)?traigent[\w.-]*\s+(?:issues?|prs?|pulls?|pull requests?)\s+#?\d+"
        # A tracker URL on any forge: GitHub issues/pulls/discussions, and
        # GitLab's `/-/issues/N`, whose extra path segment the first attempt's
        # `issues|pull` alternation could not reach.
        r"|[\w.-]+\.[a-z]{2,}/[\w.-]+/[\w./-]*?"
        r"(?:issues|pull|pulls|discussions|merge_requests)/\d+"
        # A bare hash introduced by a tracking word: `issue #127`, `see #2101`.
        r"|\b(?:issues?|tickets?|bugs?|prs?|pull requests?"
        r"|tracked(?:\s+(?:as|in|upstream(?:\s+as)?))?"
        r"|fixe[sd]|closes|resolves|see)\s+#\d+",
        re.IGNORECASE,
    )
    # Which repository a citation names, when it names one. A reference to THIS
    # repository is public by definition; a reference to any other one is a
    # disclosure, which is why the two are held to different corpora below.
    TRACKER_REPOSITORY = re.compile(
        r"([\w.-]*traigent[\w.-]*)\s*(?:#|\s(?:issue|pr|pull))", re.IGNORECASE
    )
    THIS_REPOSITORY = "traigent-first-run"
    TRACKER_LINE = re.compile(r"^\s*tracking:", re.IGNORECASE | re.MULTILINE)

    @classmethod
    def foreign_tracker_references(cls, text: str) -> list[str]:
        """Citations that name a repository other than this public one."""
        found = []
        for citation in cls.TRACKER_REFERENCE.findall(" ".join(text.split())):
            named = cls.TRACKER_REPOSITORY.search(citation)
            if named and named.group(1).casefold() != cls.THIS_REPOSITORY:
                found.append(citation)
        return found

    def test_no_assistant_facing_document_leaks_a_tracker_reference(self) -> None:
        """Customer-facing copy is pasted verbatim; a tracker link cannot ride along.

        The disclosure note is copied into the user's chat by instruction
        ("Report it as one line..."), so an issue reference anywhere in the
        copy the assistant reads is one autocomplete away from a customer's
        onboarding transcript. This is a public repository: internal repo,
        issue, and tracker names have no place in guidance the user sees.

        The corpus is every markdown document this repository publishes, from
        `git ls-files`, rather than `assistant_facing_documents()`. That list
        excluded README.md - the most-read file here, and the one a customer
        reads before anything else - along with AGENTS.md, CLAUDE.md,
        `templates/` and `reports/`.
        """
        for name, raw in published_prose_documents().items():
            # Whitespace-normalized, because an allowlisted citation wraps
            # across lines in the source and would otherwise never match.
            allowed = " ".join(raw.split())
            for citation in self.TRACKER_CITATION_ALLOWLIST:
                allowed = allowed.replace(citation, "")
            with self.subTest(document=name):
                self.assertEqual(
                    self.TRACKER_REFERENCE.findall(" ".join(raw.split())),
                    [],
                    f"{name} carries a tracker reference outside the "
                    "allowlisted engineering citations",
                )
                self.assertEqual(
                    self.TRACKER_LINE.findall(raw),
                    [],
                    f"{name} carries a 'Tracking:' line, which the "
                    "disclosure copy would paste to the user verbatim",
                )

    def test_no_published_file_names_another_repositorys_tracker(self) -> None:
        """The disclosure half, and it reads everything git publishes.

        Two different rules were being asked of one check. Copy hygiene - no
        issue numbers in text a user is handed - belongs to the prose corpus
        above. DISCLOSURE - no naming of a private repository's tracker -
        belongs to everything published, scripts included, because a comment in
        `readiness.py` ships inside the installed skill just as a sentence in
        `run-safety.md` does.

        Splitting them is what lets the corpus be whole without deleting
        legitimate engineering context. Measured, the three shipped scripts
        carry twelve `traigent-first-run#N` citations in code comments. Those
        name THIS repository, which is public, and no user ever sees a code
        comment - so the copy rule has no business there. A citation naming any
        other repository is a different fact and fails everywhere.
        """
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            capture_output=True,
            text=True,
            check=True,
        )
        offenders: dict[str, list[str]] = {}
        for name in sorted(listed.stdout.split("\0")):
            if not name or name.startswith("tests/"):
                # `tests/` writes citations deliberately, as the inputs that
                # prove this check can see one.
                continue
            try:
                raw = (ROOT / name).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            # Normalized before the allowlist is applied, because these
            # citations wrap across lines in the source and would otherwise
            # never match the entry that excuses them.
            raw = " ".join(raw.split())
            for citation in self.TRACKER_CITATION_ALLOWLIST:
                raw = raw.replace(citation, "")
            foreign = self.foreign_tracker_references(raw)
            if foreign:
                offenders[name] = foreign
        self.assertEqual(
            offenders,
            {},
            "a published file names another repository's tracker",
        )

    def test_the_tracker_guard_sees_a_citation_and_not_a_count(self) -> None:
        """Both directions, against invented text rather than the tree.

        A clean tree says nothing about what this pattern can SEE, and the
        pattern it replaced saw two of the ten spellings below. The second
        group matters as much: a walkthrough that counts stages, trials, rows
        and configurations writes `#` beside a number constantly, and the first
        repair of this guard failed every one of them.
        """
        for citation in (
            "traigent-first-run#78",
            "Traigent/Traigent#2101",
            "traigent/traigent#2101",
            "Traigent/traigent-first-run#78",
            # Assembled rather than written out: an owner segment followed by
            # `Traigent` + CamelCase is exactly the private-repository shape the
            # disclosure check in this same file refuses, so spelling one here
            # would make this file fail that check. The demonstration is that
            # the two guards agree.
            "Traigent/" + "Traigent" + "Backend#2450",
            "Traigent/Traigent#2100, #2101 and #2102",
            "`traigent-first-run#78`",
            "```\nsee Traigent/Traigent#2101\n```",
            "Traigent/Traigent#2101 (comment)",
            "Tracked upstream as Traigent/Traigent issue 1993.",
            "Traigent/Traigent issues 1993",
            "traigent-first-run pull 42",
            "https://github.com/Traigent/Traigent/issues/2101",
            "https://github.com/Traigent/traigent-first-run/issues/127",
            "https://github.com/Traigent/traigent-first-run/pull/142",
            "https://github.com/Traigent/Traigent/discussions/45",
            "https://gitlab.example.com/group/proj/-/issues/45",
            "see #2101 for why",
            "issue #127",
        ):
            with self.subTest(citation=citation):
                self.assertTrue(
                    self.TRACKER_REFERENCE.search(" ".join(citation.split())),
                    "an internal tracker citation the guard cannot see",
                )

        for legal in (
            "https://github.com/Traigent/traigent-first-run",
            "$traigent-first-run",
            "## A markdown heading",
            "traigent-first-run is the skill you install",
            "issue 2101 of the newsletter",
            # Standard markdown cross-links. SKILL.md has eight numbered stage
            # headings, so this anchor form is how a reader is sent to one.
            "[stage 3 of the flow](../SKILL.md#3-complete-the-system)",
            "[why](skills/traigent-first-run/SKILL.md#3-complete-the-system)",
            # Ordinary counting, in a walkthrough that counts constantly.
            "If trial #3 fails, stop and report it before spending more.",
            "run #1 finished before run #2",
            "configuration #7 of 12",
            "step #2 of the five-stage journey",
        ):
            with self.subTest(legal=legal):
                self.assertIsNone(
                    self.TRACKER_REFERENCE.search(" ".join(legal.split())),
                    "the guard flags copy that carries no tracker reference",
                )

        # And the disclosure half distinguishes this repository from any other.
        self.assertEqual(
            self.foreign_tracker_references("tracked in traigent-first-run#78"), []
        )
        self.assertEqual(
            self.foreign_tracker_references("tracked in Traigent/Traigent#2101"),
            ["Traigent/Traigent#2101"],
        )
        # ACCEPTED RESIDUAL: a bare project-key form (`ABC-127`) is not matched.
        # It cannot be, without a prefix denylist: the shape is identical to
        # `RFC-9562` and `ISO-8601`, both of which this package's comments have
        # reason to write, and a denylist of internal project keys published
        # here would be the disclosure it is meant to prevent. Nothing in this
        # repository uses that form today - verified by grep - and if one is
        # ever adopted the fix is to add its exact prefix, deliberately.

    def test_privacy_is_a_documented_contract_and_errors_are_sanitized(self) -> None:
        # The version is DERIVED, for the same reason
        # `test_readme_discloses_pinned_sdk_license_terms` derives it: this is
        # the telemetry half of the disclosure `pinned_sdk_version` names in
        # its own docstring, and it was the half still typing the number. Two
        # literals here meant a pin bump could leave the privacy contract
        # pointing at the terms of a release nobody installs - the exact
        # staleness the license half was fixed for, in the paragraph about what
        # leaves the user's machine.
        version = pinned_sdk_version()
        readme_source = (ROOT / "README.md").read_text()
        readme = " ".join(readme_source.casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        for phrase in (
            f"pinned sdk {version} telemetry contract",
            "tuned configuration keys and values",
            "observability content the project explicitly opts into recording",
            "short content-free labels",
            "raw prompt text is not used as a configuration value",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)
        self.assertIn(
            f"https://github.com/Traigent/Traigent/blob/v{version}/"
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

        `test_sdk_comparison_uses_twelve_rows_then_added_knobs_and_twelve_trials`
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

    def test_the_row_level_sanity_check_keeps_its_five_constraints(self) -> None:
        """The rules that stop an opinion behaving like a measurement.

        Each of these is load-bearing on its own, and the check is unsafe
        without any one of them - a judgement that can raise a score, or edit a
        gold, or grade rows the run itself wrote, is a worse defect than the
        one it was added to catch. They are pinned in prose because the scorer
        can only enforce three of the five; the other two are things the
        assistant does or does not do.
        """
        dataset = (SKILL_ROOT / "references" / "evaluation-and-dataset.md").read_text()
        normalized = " ".join(dataset.split())
        skill = " ".join(SKILL.read_text().split())

        # 1. Unbilled, which is the whole reason it may sit at the opening gate.
        self.assertIn("your own read, not a billed call", normalized)
        self.assertIn("needs no approval", normalized)
        self.assertIn("--row-review", skill)
        # 2. Scoped to the rows the user brought, stated as a purpose.
        self.assertIn(
            "reads the rows the user brought, and skips the rows this run " "generated",
            normalized,
        )
        self.assertIn("marking its own homework", normalized)
        # 3. The direction rule, no credit for a clean pass - and the bound,
        #    which is a ceiling and never a stop. A judgement that can cancel a
        #    paid run is the same defect as one that can raise a score, read
        #    from the other end: on collected data it can be wrong, and the run
        #    only reads the rows it draws.
        self.assertIn("bounds the run and never stops it", normalized)
        self.assertIn("may withhold a claim; it may not manufacture one", normalized)
        self.assertIn("may not cancel a paid run", normalized)
        self.assertIn(
            "a clean pass earns no points, no band, and no credit of any kind",
            normalized,
        )
        self.assertIn("sentence in the readiness evidence line", normalized)
        # 4. A finding is a question, never an edit - and the question has a
        #    shape: every flagged row's id, its quoted content, the reason, and
        #    whether the run will actually read it. Then the user's answer
        #    decides, in both directions.
        self.assertIn("never a silent edit, and it opens a conversation", normalized)
        self.assertIn(
            "I suspect this dataset has rows that need fixing before the run",
            normalized,
        )
        self.assertIn("do you agree or disagree?", normalized)
        self.assertIn("the id, the quoted content, and the reason", normalized)
        self.assertIn(
            "Say which of them are inside the rows this run will actually use",
            normalized,
        )
        self.assertIn("repair the rows in the working copy", normalized)
        self.assertIn("say in the run's own report what it was tuned on", normalized)
        # And the route says the same thing where routes live - as a ROUTE.
        # It stated all four of the mandates above at length, in a list where
        # every sibling is one line, which is the defect CLAUDE.md names: a
        # rule stated twice is a rule that can be changed in one place. What
        # SKILL.md owns is that this cap does not stop the run and where the
        # depth lives; the depth stays here.
        route = next(
            line
            for line in SKILL.read_text().splitlines()
            if line.startswith("- `dataset-unsound-expected-outputs`")
        )
        self.assertIn("bounded, not stopped", route)
        self.assertIn("evaluation-and-dataset.md", skill)
        for owned_here in (
            "the id, the quoted content, and the reason",
            "repair the rows in the working copy",
            "say in the run's own report what it was tuned on",
        ):
            with self.subTest(mandate=owned_here):
                self.assertNotIn(owned_here, skill)
        cap = READINESS.unsound_answer_cap(
            READINESS.RowReview(supplied=True, reviewed=10, unsound=5)
        )
        # Both flags, in both directions. Neither was asserted anywhere, and
        # the dataclass defaults gave this cap the opposite of both.
        self.assertFalse(cap.blocks)
        self.assertTrue(cap.asks)
        # 5. Declared as the assistant's judgement, never as the user's.
        self.assertIn("never as the user's ground truth", normalized)
        self.assertIn('"reviewer": "assistant"', dataset)
        # And the scorer actually implements the three it can.
        self.assertEqual(READINESS.ROW_REVIEW_REVIEWER, "assistant")
        self.assertNotIn("synthesised", READINESS.ROW_REVIEW_ORIGINS)
        self.assertLess(
            READINESS.UNSOUND_ANSWER_CEILING, READINESS.GENERATED_ANSWER_KEY_CEILING
        )

    def test_the_row_level_check_is_ordered_at_the_opening_gate(self) -> None:
        """Where it runs is a decision, so it is written down where flow lives.

        Not merely a placement: the opening gate is the one point at which the
        rule above - review what the user brought, skip what this run generated
        - covers every row in the file, because nothing has been generated yet.
        Later is also where a wrong expected answer has already been copied
        into whatever stage 3 derived from it.
        """
        skill = " ".join(SKILL.read_text().split())
        gate = skill.index("#### Opening readiness gate")
        creation = skill.index("### 3. Complete the system")
        instruction = skill.index("do the row-level sanity check")
        self.assertLess(gate, instruction)
        self.assertLess(instruction, creation)
        self.assertIn("no generated row competes with it yet", skill)

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
        # A fourteenth dataset cap must be routed too, so pin the count rather
        # than spot-checking the thirteen that exist today. Ten when #149 wrote
        # this; #161 added the middle answer-key rung and #144 added
        # `dataset-shape-unrecognised`, and neither branch could see the other
        # two.
        # #177 then added `dataset-unsound-expected-outputs`, the row-level
        # sanity check's one ceiling, which is the fourteenth.
        self.assertEqual(len(conditions), 14)
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
            (
                "dataset-below-measurable-size",
                "more comparable examples is what lifts this",
            ),
            (
                "dataset-coarse-resolution",
                "more comparable examples is what lifts this too",
            ),
            (
                "dataset-unsound-expected-outputs",
                "approval-gated question",
            ),
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
            # #177's row-level sanity check. It scopes for the plainest reason
            # on this list: the finding is the assistant's own reading of the
            # customer's answer key, and an opinion that can be wrong may bound
            # what the result claims and may not cancel a paid run the
            # customer's sound rows would have earned. #187 states that in the
            # module - `blocks=False`, `asks=True` - and SKILL.md routes it as
            # "bounded, not stopped".
            "dataset-unsound-expected-outputs",
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

    def test_the_billing_cap_mandate_has_exactly_one_home(self) -> None:
        """It had two homes, and the two were not spelled the same way.

        SKILL.md carried a bare lowercase sentence - "never call the
        walkthrough ceiling a hard provider-billing cap." - restating what
        run-safety.md's budget section already owned as "Never describe this as
        a hard provider-billing cap." Counting either exact phrase finds one
        occurrence in the defect and one in the fix, so a phrase count is green
        on both and documents nothing. A rule restated in different words is
        precisely the defect CLAUDE.md names, so this counts DOCUMENTS THAT
        LEGISLATE about the ceiling and provider billing, whatever words they
        use, and requires the single home to be reachable from SKILL.md.
        """
        owner = RUN_SAFETY.relative_to(ROOT).as_posix()
        mandates = billing_ceiling_mandates(published_prose_documents())
        self.assertEqual(
            sorted(mandates),
            [owner],
            f"the walkthrough-ceiling billing rule is stated as a mandate in "
            f"{sorted(mandates)}. A rule with two homes can be changed in one "
            "of them; restate the conclusion locally if a reader needs it, but "
            "leave the mandate where it is owned.",
        )
        # Two sentences in the owner, and the count is pinned so a third cannot
        # arrive unnoticed. They are not the same statement twice: `$5.00`
        # approval scope tells the assistant what to CALL the ceiling in the
        # card the user reads, and the budget section states the prohibition
        # that governs everywhere else. Both are inside the document that owns
        # the rule, which is what "one home" asks. The previous revision
        # asserted one because its word-ban could not see an affirmative
        # imperative, so the card sentence was invisible to it - the count
        # changed when the guard started working, not when the guidance did.
        self.assertEqual(
            len(mandates[owner]),
            2,
            f"run-safety.md now states the billing rule {len(mandates[owner])} "
            "times: " + " | ".join(mandates[owner]),
        )
        self.assertIn("references/run-safety.md", SKILL.read_text())

    def test_the_one_home_check_reads_meaning_and_not_vocabulary(self) -> None:
        """Exercised against invented text, because the corpus cannot show it.

        The repository only ever holds the fixed state, so running the check
        over it proves the fix and not the check. Every document here is
        fabricated: a paraphrase that shares no phrase with the real mandate
        must still be caught, and a local conclusion that points at the owner
        must still be allowed - otherwise the guard is a word ban and the next
        duplicate simply gets reworded past it.

        The first revision WAS that word ban - eight negation words - and it
        was wrong in both directions, so both directions are exercised here.
        The affirmative mandates below carry not one of those eight words and
        are the natural way to write the rule positively; the conclusions
        include the one README.md already uses, which that list refused.
        """
        owner = (
            "Keep the default `$5.00` ceiling across both approvals.\n"
            "Never call the walkthrough ceiling a hard provider-billing cap, "
            "tracked cost or not.\n"
        )
        paraphrases = {
            "reworded": "Do not present the walkthrough ceiling as a "
            "guaranteed limit on what the provider bills.\n",
            "restructured": "The stop target must never be described to the "
            "user as something that caps provider charges.\n",
            "verbatim": "never call the walkthrough ceiling a hard "
            "provider-billing cap.\n",
            # Affirmative mandates. A rule does not have to be spelled as a
            # prohibition to be one, and each of these walked past the word ban.
            "affirmative": "Always tell the user the walkthrough ceiling is "
            "only an execution stop target, not something that caps what the "
            "provider bills.\n",
            "positive-framing": "Present the ceiling as an execution stop "
            "target rather than a guarantee about provider billing.\n",
            "formal": "Refrain from calling the walkthrough ceiling a hard "
            "provider-billing cap.\n",
            "bulleted": "- Call the ceiling an execution stop target, never a "
            "promise about what the provider charges.\n",
        }
        for label, second in paraphrases.items():
            with self.subTest(duplicate=label):
                self.assertEqual(
                    sorted(
                        billing_ceiling_mandates(
                            {"run-safety.md": owner, "SKILL.md": second}
                        )
                    ),
                    ["SKILL.md", "run-safety.md"],
                    f"a {label} statement of the mandate is invisible to this "
                    "check, so the duplicate it exists to catch only has to be "
                    "written differently",
                )

        conclusions = {
            "pointer": "The walkthrough ceiling is an execution stop target, "
            "not a billing guarantee; `references/run-safety.md` owns the "
            "rule.\n",
            # The negative conclusion. This is the shape README.md already
            # uses, and the word ban failed it on `cannot` - a false red on the
            # single most-read file in a public repository, with a message
            # about a mandate the sentence does not state.
            "negative": "The walkthrough ceiling cannot guarantee what the "
            "provider bills; `references/run-safety.md` owns the rule.\n",
            "readme": "That target is a conservative control, not a "
            "guaranteed provider-billing cap.\n",
            "pronoun": "It is a stop target, not a promise about what the "
            "provider bills.\n",
        }
        for label, second in conclusions.items():
            with self.subTest(conclusion=label):
                self.assertEqual(
                    sorted(
                        billing_ceiling_mandates(
                            {"run-safety.md": owner, "README.md": second}
                        )
                    ),
                    ["run-safety.md"],
                    "a local conclusion with a pointer is what CLAUDE.md "
                    "permits; rejecting it would push writers into saying "
                    "nothing at all",
                )

    def test_the_one_home_corpus_is_every_document_this_repository_publishes(
        self,
    ) -> None:
        """The check is only as good as the set of documents it opens.

        The previous corpus was a hand-written list of six paths. The
        repository publishes seventeen markdown documents, so a mandate
        restated in `templates/`, `reports/` or `.github/` was outside the
        check by construction - which is the same defect, one level up, as the
        duplicate it looks for.
        """
        published = published_prose_documents()
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--", "*.md"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        self.assertEqual(
            sorted(published),
            sorted(name for name in listed if not name.startswith("tests/")),
            "the corpus has drifted from what git publishes",
        )
        # The named documents the earlier list held, and the directories it did
        # not - each asserted to be reachable, so a future narrowing fails here
        # rather than silently shrinking what the rule covers.
        for expected in ("README.md", "AGENTS.md", "CLAUDE.md", "GUIDE.md"):
            with self.subTest(document=expected):
                self.assertIn(expected, published)
        # `templates/` is NOT in this list, and its absence is the decision
        # rather than an oversight: #192 deleted the directory - the two
        # compatibility templates in it were a second home for the run plan and
        # the preflight script, which is the duplicate this very check exists
        # to refuse. A directory that no longer exists cannot be "reachable",
        # and asserting it here would only be satisfied by putting the
        # duplicates back.
        for directory in ("skills/", "reports/"):
            with self.subTest(directory=directory):
                self.assertTrue(
                    any(name.startswith(directory) for name in published),
                    f"nothing under {directory} is in the corpus",
                )

    def test_the_subjunctive_ceiling_is_explained_by_both_of_its_causes(
        self,
    ) -> None:
        """`binds` is `cap.ceiling == overall`, and `overall` has two inputs.

        The glossary is the file the assistant phrases from, and it said "would
        limit to" marks a ceiling that "only starts to matter once something
        lower is cleared" - true of a stricter cap, false of the other half.
        `overall` is `min(weighted_average, min(ceilings))`, so a sole ceiling
        above the average is equally not the operative limit. README.md already
        stated both causes; the two must not disagree.
        """
        glossary = " ".join(
            (SKILL_ROOT / "references" / "glossary.md").read_text().casefold().split()
        )
        readme = " ".join((ROOT / "README.md").read_text().casefold().split())
        sentence = glossary.split('"would limit to" is', 1)[1].split(".", 1)[0]
        self.assertIn("stricter", sentence)
        self.assertIn("average", sentence)
        self.assertNotIn(
            "only starts to matter once something lower is cleared", glossary
        )
        self.assertIn("your average simply has not climbed that high yet", readme)

    def test_every_evaluator_cap_condition_has_a_documented_branch(self) -> None:
        """The dataset caps were routed exhaustively; the evaluator ones were not.

        SKILL.md's paragraph opens "Evaluator and agent caps route through the
        rules that already own them" and then named three of the four the
        scorer can emit. `evaluator-timeout` ceilings the whole score at 45 and
        carries the remedy `bound-evaluator-cost` - a word that appeared in no
        guidance document, so an assistant holding that payload had nothing to
        route it to.

        Three open branches then wrote three incompatible routes into this one
        paragraph - ask the one question, raise the budget, route to the
        invalid-evaluator paragraph - which is the "five documents close the
        stop set five ways" defect reproduced inside a single file. The owner
        settled it by placing the question at "fill gaps", before any spend, so
        the route lives here with the stage that asks it and nowhere else. This
        check is what keeps it single: it fails if the condition loses its
        branch, and the sibling `test_the_timeout_route_has_exactly_one_home`
        fails if a second branch appears.

        Enumerated from the module rather than listed here, for the same reason
        the dataset check pins its count: a fifth evaluator cap must be routed
        too.
        """
        source = (SKILL_ROOT / "scripts" / "readiness.py").read_text()
        conditions = {
            condition
            for condition in re.findall(r'Cap\(\s*"([a-z0-9-]+)"', source)
            if condition.startswith("evaluator-")
        }
        self.assertEqual(len(conditions), 4)
        normalized = " ".join(SKILL.read_text().casefold().split())
        routing = normalized.split(
            "evaluator and agent caps route through the rules that already own them", 1
        )[1]
        for condition, branch in (
            ("evaluator-unresolved", "inspect, repair, or replace"),
            ("evaluator-invalid", "inspect, repair, or replace"),
            ("evaluator-timeout", "five-option question"),
            ("evaluator-absent", "create or select"),
        ):
            with self.subTest(condition=condition):
                self.assertIn(condition, conditions)
                self.assertLess(routing.index(condition), routing.index(branch))

    def test_the_timeout_route_has_exactly_one_home(self) -> None:
        """Three branches wrote three routes; only one of them may survive.

        The rule is CLAUDE.md's "one decision, one home", and this condition is
        the instance that proved it: a rule stated in two documents is a rule
        that can be changed in one, and three pull requests each rewrote this
        paragraph into a route the other two contradict. So `evaluator-timeout`
        is named in exactly one assistant-facing document - SKILL.md, which
        owns routing - and the depth behind it (what to say before the wait,
        the five options to offer after it) sits in the evaluation reference
        without restating the route.

        Counted over occurrences rather than files: the previous three drafts
        would each have passed a per-file check, because each put its whole
        route in one place. What they could not survive together is a count.
        """
        occurrences = {
            path.name: " ".join(path.read_text().casefold().split()).count(
                "evaluator-timeout"
            )
            for path in assistant_facing_documents()
        }
        self.assertEqual(
            {name: count for name, count in occurrences.items() if count},
            {"SKILL.md": 1},
            "the timeout route must be stated once, in the document that owns "
            "routing - a second statement is the defect this condition's own "
            "history is made of",
        )

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
        # The pillar's own score, re-measured rather than carried over.
        #
        # It reads 100 now, and the previous 93 is worth recording because of
        # what it was docking. The pillar used to average a per-knob quality
        # blend, and the shortfall in this space was the deliberately pinned
        # `temperature` - a knob this guide instructs authors to pin, because
        # sweeping it adds surface noise an exact-match evaluator punishes. The
        # sub-score therefore charged the walkthrough seven points for
        # following the walkthrough, and the note beside it warned readers not
        # to fix that by adding a third value to a two-value knob. A measure
        # that needs a warning against acting on it is not a measure.
        #
        # What earns the 100 is the shape rather than the taste: 48 distinct
        # configurations against a 12-trial budget, so the run compares twelve
        # of them, and 48 is four times the budget rather than twenty.
        self.assertEqual(pillar.score, 100)
        space = next(s for s in pillar.subscores if s.name == "search-space")
        self.assertEqual(
            space.evidence,
            "your space has 48 distinct configurations; this run will try up to "
            "12 of them",
        )
        self.assertEqual(pillar.confidence, 1.0)

    def test_the_qualitative_knob_rules_are_guidance_and_not_arithmetic(
        self,
    ) -> None:
        """Three rules the scorer used to approximate, now addressed to a reader.

        Each was in the arithmetic and each was wrong there in a way the code
        could not see: the noise floor only collapses knobs it has a range for,
        the alias table only knows the spellings it was told, and `wired` is a
        claim rather than a measurement. So they are stated where the one
        reader who can check them against the customer's actual agent will
        read them - beside the knob catalog that chooses the knobs - and the
        scorer keeps only what it can count.

        Pinned because "moved into guidance" is exactly the change that
        silently becomes "deleted" a branch later.
        """
        sdk = " ".join(SDK_EXECUTION.read_text().split())
        self.assertIn("Judging a space before you send it", sdk)
        self.assertIn("Values too close together are not two values", sdk)
        self.assertIn("Two knobs naming one dimension are one knob", sdk)
        self.assertIn("A knob the agent never reads is not a lever", sdk)
        # And each names why the scorer cannot settle it.
        self.assertIn("it has no range for an unfamiliar knob", sdk)
        self.assertIn("only knows the spellings it has been told about", sdk)
        self.assertIn("your claim rather than a measurement", sdk)
        # The pillar it describes is one number, and the document says which.
        self.assertIn(
            "how many distinct configurations the space holds, against how "
            "many the run has budget to try",
            sdk,
        )
        self.assertEqual(
            sorted(
                name
                for name in READINESS.CHECK_DISPLAY_NAMES
                if name in {"knob-count", "variation", "search-space"}
            ),
            ["search-space"],
        )

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
            "BASELINE_TRIALS": 12,
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

    def test_the_templates_own_document_measures_every_agent_subscore(self) -> None:
        """The walkthrough's own evidence must not score anything unmeasured.

        Run through the real scorer rather than a hand-written document, so a
        template edit that leaves a sub-score unmeasured fails here.
        """
        namespace = self._template_producer_namespace()
        pillar, _ = score_config_space(
            namespace["config_space_document"](namespace["ENHANCED_SPACE"])
        )
        self.assertEqual(
            pillar.confidence,
            1.0,
            "every agent sub-score must be measured for the template's own document",
        )

    def test_the_guidance_no_longer_documents_agent_type(self) -> None:
        """`agent_type` is removed, and the guidance must not re-grow it.

        The field selected the `HIGH_IMPACT_KNOBS` catalog for the `coverage`
        sub-score. Coverage was removed, which left the field read by nothing,
        so it is no longer declared, no longer produced by the template, and no
        longer documented. Documenting a field the scorer does not read is the
        specific failure this guards: a reader would put it in a document and
        reasonably expect it to do something.

        A document that still carries it is REFUSED, not ignored. #185 wrote
        "unknown keys are ignored whole - removal is not a break for anyone's
        existing document", which was true on the branch and is not true here:
        #190 landed first and refuses any key the declaration does not name.
        `test_declaring_agent_type_changes_nothing_the_run_emits` in
        tests/test_readiness_scoring.py pins the behaviour this tree has, and
        carries the owner decision that removing the field is therefore a
        breaking change for a document this guide's own producer once emitted.
        """
        self.assertNotIn(
            "agent_type",
            {spec.name for spec in READINESS.CONFIG_SPACE_FIELDS},
            "agent_type must not be a declared config-space field",
        )
        for name, path in (("run-safety.md", RUN_SAFETY),):
            with self.subTest(document=name):
                text = path.read_text()
                self.assertNotIn(
                    "| `agent_type` |",
                    text,
                    f"{name} still has a field-table row for a removed field",
                )
                self.assertNotIn(
                    '"agent_type"',
                    text,
                    f"{name} still emits agent_type in a worked example",
                )

        template = SDK_EXECUTION.read_text()
        self.assertNotIn(
            "AGENT_TYPE",
            template,
            "the walkthrough template must not produce a removed field",
        )
        # The SDK's own `recommend_configuration_space(agent_type)` is a
        # different surface - a real parameter of a real library function - and
        # is deliberately still documented. Removing our document field must
        # not quietly delete somebody else's API from the reference table.
        self.assertIn("recommend_configuration_space(agent_type)", template)

    def test_the_glossary_names_exactly_the_agent_lines_the_card_prints(self) -> None:
        """The card's Agent lines and the glossary's list are one decision.

        Read off `CHECK_DISPLAY_NAMES` rather than quoted, so removing a
        sub-score without removing its glossary entry fails here - which is the
        mutation that survived when `coverage` was dropped, leaving the
        customer a definition for a line the card no longer prints.
        """
        printed = {
            READINESS.CHECK_DISPLAY_NAMES[name]
            for name in ("knob-count", "variation", "search-space")
            if name in READINESS.CHECK_DISPLAY_NAMES
        }
        glossary = (SKILL_ROOT / "references" / "glossary.md").read_text()
        block = glossary.split("\n  Agent:\n", 1)[1].split("\n  Words the evidence", 1)[
            0
        ]
        listed = {
            line.strip().split(" - ", 1)[0].strip()
            for line in block.splitlines()
            if " - " in line and not line.startswith(" " * 20)
        }
        self.assertEqual(listed, printed)

    def test_every_pair_of_configuration_counts_agrees_with_the_fence(self) -> None:
        """The prose may not restate a size the code fence contradicts.

        `sdk-execution.md` asserts both sizes in executable code, and then
        speaks them again in prose two and three hundred lines earlier. The
        branch that changed the baseline from six configurations to twelve
        updated the asserts and one bullet and left two sentences saying "6 and
        48" - each correct-looking on its own, and neither visible in the diff
        that broke it, which is the defect class CLAUDE.md is about.

        Derived from the fence, never quoted: the asserted pair is read out of
        the document's own `assert configuration_count(...) == N` lines, and
        any prose pair ending in the enhanced count has to open with the
        baseline count. A future re-sizing changes both halves or fails here.
        """
        text = SDK_EXECUTION.read_text()
        asserted = dict(
            re.findall(
                r"assert configuration_count\((BASELINE|ENHANCED)_SPACE\) == (\d+)",
                text,
            )
        )
        self.assertEqual(
            sorted(asserted),
            ["BASELINE", "ENHANCED"],
            "the fence stopped asserting both sizes",
        )
        baseline, enhanced = int(asserted["BASELINE"]), int(asserted["ENHANCED"])
        self.assertNotEqual(
            baseline, enhanced, "the probe below needs the two to differ"
        )

        disagreeing = [
            match.group(0)
            for match in re.finditer(r"\b(\d+) and (\d+)\b", text)
            if int(match.group(2)) == enhanced and int(match.group(1)) != baseline
        ]
        self.assertEqual(
            disagreeing,
            [],
            f"prose states a baseline size the fence contradicts; it asserts "
            f"{baseline} and {enhanced}",
        )
        # And the pair really is spoken, so the check cannot pass by the prose
        # going silent about a number the reader is told twice.
        self.assertIn(f"{baseline} and {enhanced}", text)

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
            "require_untruncated_completion": lambda response: None,
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
        # `ast.literal_eval`, not `json.loads`: the literal is Python, and a
        # black-formatted multi-line list carries a trailing comma that JSON
        # refuses.
        wired = ast.literal_eval(
            re.search(
                r"^WIRED_KNOBS = (\[.*?\])", code[0], re.MULTILINE | re.DOTALL
            ).group(1)
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
                if not alternatives:
                    # A pinned knob is wired and consumed but searches nothing,
                    # which is the honest state for `temperature`. There is no
                    # second value to move the request with, so there is
                    # nothing here to prove; assert it really is pinned rather
                    # than silently skipping a knob that lost its values.
                    self.assertEqual(len(space[knob]), 1)
                    continue
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
        # `temperature` is wired and consumed, but pinned to one value, so the
        # probe reports `not-searched`: it claims no dimension, which is a
        # different statement from "the agent ignores it" and is not a defect.
        # Every knob the space actually searches must still be `visible`.
        self.assertEqual(verdicts["temperature"], "not-searched")
        self.assertEqual(
            {knob for knob, verdict in verdicts.items() if verdict == "visible"},
            set(honest["WIRED_KNOBS"]) - {"temperature"},
            "every knob the shipped template actually searches must be "
            "provable from build_request alone",
        )

        no_op = self._wiring_probe_namespace(
            build_prompt=lambda message, *, style, thinking_shape, reflect, pre_action_reflect: (
                message + ("\n\ncheck" if pre_action_reflect else "")
            )
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
            with_no_op["pre_action_reflect"],
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
            if config["model"] != namespace["BASELINE_CONFIG"]["model"]:
                # This model ignores pre_action_reflect and nothing else: same request
                # for either value of it, every other knob still honoured.
                config = {**config, "pre_action_reflect": False}
            return real_build_request(message, config)

        namespace["build_request"] = model_dependent
        verdicts = namespace["probe_wiring"](
            namespace["ENHANCED_SPACE"], namespace["BASELINE_CONFIG"]
        )
        self.assertEqual(
            verdicts["pre_action_reflect"],
            "partial",
            "a knob only the base model consumes must not read as proven",
        )
        self.assertEqual(
            verdicts["prompt_style"],
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
            if message == trigger and config["pre_action_reflect"]:
                request["messages"] = [{"role": "user", "content": "rewritten"}]
            else:
                # Every other input ignores pre_action_reflect entirely.
                request["messages"] = [{"role": "user", "content": message}]
            return request

        namespace["build_request"] = input_dependent
        verdicts = namespace["probe_wiring"](
            namespace["ENHANCED_SPACE"], namespace["BASELINE_CONFIG"]
        )
        self.assertEqual(
            verdicts["pre_action_reflect"],
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
            # All four behaviour knobs act through the prompt, so a model
            # that takes no prompt shaping at all is asymmetric in all four.
            # It was two while the space also swept temperature.
            {"prompt_style", "thinking_shape", "reflect", "pre_action_reflect"},
            "the probe must still see the asymmetry it saw before",
        )
        self.assertEqual(
            conditional["UNPROVEN_WIRED_KNOBS"],
            {},
            "a conditional dimension is information, not a failed load",
        )
        self.assertEqual(
            conditional["CONDITIONAL_WIRED_KNOBS"],
            {
                "prompt_style": [base_model],
                "thinking_shape": [base_model],
                "reflect": [base_model],
                "pre_action_reflect": [base_model],
            },
            "the load must name the models that honour a conditional knob",
        )
        report = printed.getvalue()
        for expected in ("conditional dimension", "prompt_style", base_model):
            self.assertIn(expected, report)

        # A builder that reads only `pre_action_reflect` makes the other three prompt
        # knobs no-ops at once, and every one of them must fail the load.
        dead = self._wiring_probe_namespace(
            build_prompt=lambda message, *, style, thinking_shape, reflect, pre_action_reflect: (
                message + ("\n\ncheck" if pre_action_reflect else "")
            )
        )
        with self.assertRaises(AssertionError) as raised:
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(fence, "<sdk-no-op-knob>", "exec"), dead)
        self.assertIn("prompt_style", str(raised.exception))
        self.assertEqual(
            dead["UNPROVEN_WIRED_KNOBS"],
            {
                "prompt_style": "invisible",
                "thinking_shape": "invisible",
                "reflect": "invisible",
            },
        )

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
        base = {"knobs": {"widget": [1, 50]}}
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

    def test_the_result_is_a_frontier_and_not_a_one_sided_saving(self) -> None:
        """The shape of the claim, and the shape it may not slide back into.

        A one-sided round can only report "cheaper at no lower score", which
        needs a noise bar to separate a saving from measurement variance - and
        this package had two unmeasured numbers holding one up. A frontier
        asserts no win, so it needs no bar. The guard is therefore twofold: the
        frontier vocabulary is required, and any threshold reappearing inside
        these sections is a signal the framing slipped back.
        """
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())

        self.assertIn("pareto frontier over accuracy and cost", skill)
        self.assertIn(
            "never show a frontier point that scored below the configuration "
            "the user is already running",
            skill,
        )
        # both wins, which is the whole reason the frontier replaced a
        # one-sided objective
        self.assertIn(
            "the same score for less money and a higher score for the same money",
            skill,
        )
        self.assertIn("a frontier asserts no win", safety)
        # the floor is a number the run reads, defined once, where the run that
        # reads it can find it
        self.assertIn("the floor is a number this run reads", safety)
        self.assertIn("def frontier_at_or_above(", SDK_EXECUTION.read_text())

        # It is not a stage and buys nothing: arithmetic over trials both runs
        # already paid for, which is also why there is no third run to gate,
        # approve, or offer.
        self.assertIn(
            "it costs nothing - it is arithmetic over trials already paid for", skill
        )
        self.assertIn(
            "it costs nothing and adds no stage - both runs priced every trial they completed",
            safety,
        )

        # No percentage threshold anywhere in the sections that decide this
        # run's outcome. `run-safety.md:686` asserted run-to-run token variance
        # "is single-digit percent" and `:699` predicted "the 5-25% savings
        # this round is most likely to find"; neither was measured, and both
        # existed only to defend a one-sided claim. A number reappearing here
        # is the framing sliding back, not a detail.
        for name, document, start, end in (
            (
                "SKILL.md",
                skill,
                "report each measurement as a **pareto frontier over accuracy and cost**",
                "### 8. verify and report",
            ),
            (
                "run-safety.md",
                safety,
                "### the accuracy-cost frontier",
                "## post-run verification",
            ),
        ):
            self.assertIn(start, document)
            section = document.split(start, 1)[1].split(end, 1)[0]
            with self.subTest(document=name):
                self.assertEqual(
                    re.findall(r"\d+(?:\.\d+)?\s?%", section),
                    [],
                    f"{name}'s frontier section states a percentage "
                    "threshold. A frontier asserts no win and needs no bar; a "
                    "number here means the one-sided framing came back, and "
                    "the two it replaced were both unmeasured",
                )

    def test_the_frontier_is_read_from_both_runs_and_costs_nothing(self) -> None:
        """Two paid runs, and each reports its own frontier for free.

        The round this replaced was a third paid stage with a gate, an
        approval, and an offer, to answer a question the trials already bought
        can answer: the baseline grid prices six configurations and the
        enhanced search prices up to twelve, so accuracy against cost is
        arithmetic either way. The cost-bearing controls therefore have to be
        varied inside run 2, which for a prepared baseline the shared model
        list above already does.

        The frontier informs the close; it does not become the close. A menu
        offered instead of a recommendation is the failure this stage already
        names, and a frontier is exactly the shape that would do it.
        """
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        sdk = " ".join(SDK_EXECUTION.read_text().casefold().split())

        # There is no third run to name, in any of the four documents a reader
        # could reach.
        for name, document in (
            ("SKILL.md", skill),
            ("run-safety.md", safety),
            ("sdk-execution.md", sdk),
            ("GUIDE.md", " ".join((ROOT / "GUIDE.md").read_text().casefold().split())),
        ):
            with self.subTest(document=name):
                self.assertNotIn("second enhanced run", document)
        self.assertIn("do not require a third optimization pass", skill)
        self.assertIn("this is the last run", skill)

        # The baseline reports one too, over the six trials it just paid for.
        self.assertIn(
            "show this grid's own accuracy-cost frontier beside the winner, read "
            "from the trials it just paid for",
            skill,
        )
        # ...and the enhanced run is where the cost-bearing controls live,
        # because there is nowhere later for them to go.
        self.assertIn(
            "the controls that carry cost are varied here or not at all", skill
        )
        # One function, both reads - not a second implementation.
        self.assertIn(
            "the same function reads the baseline grid's finished trials and the "
            "enhanced search's, so one function serves both",
            sdk,
        )

        # Placement: details layer, never in place of the recommendation.
        self.assertIn("each run's accuracy-cost frontier, in the details layer", skill)
        self.assertIn(
            "a frontier put where the recommendation belongs is the menu this "
            "stage already refuses",
            skill,
        )
        self.assertIn(
            "a menu offered *instead of* a recommendation is the same as no "
            "recommendation",
            SKILL.read_text().casefold(),
        )

        # A cheaper point is a hypothesis for the handoff, not a settled
        # finding - pointed at the rule that already says so rather than
        # restated beside it.
        self.assertIn(
            "what a frontier this size supports is a hypothesis worth testing at "
            "full scale",
            safety,
        )
        self.assertIn(
            "under the rule the continuation handoff below already states", safety
        )
        self.assertIn("it does not earn another paid round here", safety)

    def test_the_null_outcome_is_a_reported_finding(self) -> None:
        """The copy for "nothing beat what you already run" is the customer's.

        It is pinned because it is the outcome an assistant is likeliest to
        soften, skip, or turn into a pitch for one more round - and because
        three earlier revisions of it each asserted a universal negative over
        the space, which is false whenever the untested complement is
        non-empty. It reports counts and one frontier, and quantifies over
        nothing.
        """
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        quoted = quoted_prose(RUN_SAFETY)

        self.assertIn("both are results. neither is apologized for.", safety)
        self.assertIn(
            "report what this run counted, never a property of the space", safety
        )
        for phrase in (
            "this run tested `<executed trials>` of `<total combination count>` "
            "configurations",
            "the configuration you are already running is still the only point "
            "on the frontier",
            "so keeping it is the answer this run supports",
            "widening the search across your full dataset and your own controls "
            "is what the skills named at the close are for",
        ):
            with self.subTest(null_copy=phrase):
                self.assertIn(phrase, quoted)

        # the forward half points at an action, never at a result a further run
        # would return - that promise is the universal claim in another aim
        self.assertIn("it points at an action and never at a result", safety)
        self.assertIn("do not answer it with another paid run by default", safety)

        # the winning outcome carries evidence rather than a hardcoded verdict:
        # the score sentence is filled from the paired counts, not asserted
        self.assertIn("`<paired outcome counts>`", quoted)
        self.assertIn("`<the score statement the counts support>`", quoted)
        self.assertIn("default to directional", safety)
        self.assertIn(
            'say "the score did not get worse" only where a justified paired '
            "uncertainty analysis over the completed outputs supports it",
            safety,
        )
        self.assertIn(
            'never let "the optimizer picked it" stand in for evidence that the '
            "score held",
            safety,
        )


class FrontierAtOrAboveTests(unittest.TestCase):
    """Behaviour of the frontier read, which is real code, not prose.

    Every other check over this section pins a sentence, which stops silent
    deletion and nothing more. This one runs the block: the floor is the only
    executable guarantee that the report never hands back a configuration worse
    than the one the user already runs, and the check it replaced asserted the
    function's NAME - green against a body with the floor deleted, which is a
    pure cost minimiser.
    """

    @staticmethod
    def trial(score, cost, *, status="completed"):
        metrics = {}
        if score is not None:
            metrics["task_success"] = score
        if cost is not None:
            metrics["cost"] = cost
        return SimpleNamespace(status=status, metrics=metrics)

    def select(self, trials, *, floor=0.80):
        return FRONTIER_AT_OR_ABOVE(trials, "task_success", floor)

    def test_a_trial_reaches_the_frontier_only_at_or_above_the_floor(self) -> None:
        """Delete `score >= floor` and this fails: the cheap, bad trial is
        Pareto-optimal on cost, so nothing else keeps it off the report."""
        for label, score, qualifies in (
            ("equal to the floor", 0.80, True),
            ("above the floor", 0.91, True),
            ("below the floor", 0.30, False),
        ):
            with self.subTest(score=label):
                cheap = self.trial(score, 0.0060)
                self.assertEqual(self.select([cheap]), [cheap] if qualifies else [])

    def test_a_dominated_point_is_not_on_the_frontier(self) -> None:
        """Dearer and no better than another point is not a trade-off."""
        good = self.trial(0.95, 0.0040)
        dominated = self.trial(0.90, 0.0090)
        self.assertEqual(self.select([good, dominated]), [good])

    def test_a_genuine_trade_off_keeps_both_points(self) -> None:
        """Cheaper-and-lower against dearer-and-higher is what a frontier is
        for, and collapsing it to one point is the one-sided report this
        framing replaced."""
        cheap = self.trial(0.82, 0.0020)
        strong = self.trial(0.97, 0.0110)
        self.assertEqual(self.select([cheap, strong]), [cheap, strong])

    def test_the_incumbent_is_a_point_like_any_other(self) -> None:
        """Keeping what you already run is an answer the frontier shows."""
        incumbent = self.trial(0.80, 0.0120)
        self.assertEqual(self.select([incumbent]), [incumbent])

    def test_an_absent_cost_is_dropped_rather_than_read_as_zero(self) -> None:
        """Reading a missing cost as 0.0 puts every unpriced trial on the
        frontier, and dominates every priced one off it."""
        self.assertEqual(self.select([self.trial(0.95, None)]), [])
        self.assertEqual(self.select([self.trial(None, 0.0010)]), [])

    def test_only_completed_trials_are_considered(self) -> None:
        for status in ("failed", SimpleNamespace(value="failed")):
            with self.subTest(status=status):
                self.assertEqual(
                    self.select([self.trial(0.95, 0.0010, status=status)]), []
                )

    def test_the_frontier_comes_back_cheapest_first(self) -> None:
        """run-safety.md reports the frontier cheapest first, so the order is
        load-bearing rather than cosmetic."""
        cheapest = self.trial(0.85, 0.0020)
        middle = self.trial(0.90, 0.0050)
        dearest = self.trial(0.99, 0.0110)
        self.assertEqual(
            self.select([dearest, cheapest, middle]), [cheapest, middle, dearest]
        )


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
            # Affirmative report copy only, for the reason spelled out on the
            # knob entry below. "trade accuracy for cost" was here and had to
            # go: it also matches "never trade accuracy for cost", so the
            # registry would have failed the guide for stating the rule.
            #
            # The settled answer moved when the one-sided round became a
            # frontier. A one-sided objective refused the trade by never
            # searching for it; a frontier searches the whole trade-off and
            # refuses to *report* a point below what the user already gets,
            # which is the floor named here.
            "whether a second run may hand back a worse-scoring configuration",
            (
                "never show a frontier point that scored below the "
                "configuration the user is already running",
            ),
            (
                "we accepted a lower score for a lower cost",
                "the round bought a cheaper configuration at a small accuracy cost",
                "a slightly lower score is an acceptable price for the saving",
            ),
        ),
        (
            # Affirmative report copy only. A phrase that could also appear
            # inside a prohibition ("never that a control was shown not to
            # matter") does not belong here - it would fail the document for
            # stating the rule correctly.
            #
            # The agreed phrase is the rule's one home, in the continuation
            # handoff that carries observations out of the run. The second
            # run's own section used to restate it; that was a second home for
            # a rule this package already had, so it went rather than the rule.
            "whether a knob that moved nothing may be reported as not mattering",
            ("never as an established finding",),
            (
                "we removed the knobs that did not matter",
                "the search showed these knobs do not matter",
                "this round dropped the controls that had no effect",
            ),
        ),
        (
            # Three revisions of the null outcome each asserted a universal
            # negative over a set - "every configuration tested that cost less
            # also scored lower", then the same claim gated on "materially",
            # then "the only configurations this round found that cost less
            # were cheaper by less than run-to-run variance" - while the branch
            # routing to it constrained only the trials that cleared the score
            # bar. Each was false whenever the unexamined complement was
            # non-empty, and each patch opened the next gap. Settled answer:
            # report the run's own counts, which quantify over nothing.
            "what the null second-run outcome may claim",
            ("report what this run counted, never a property of the space",),
            (
                "already near the pareto frontier",
                "every configuration tested that cost less also scored lower",
                "every other configuration tested that cost materially less",
            ),
        ),
        (
            # This branch first answered "where does cost exploration go?" with
            # a third paid stage, then with an optional second enhanced run.
            # Both are the same shape: a run after the run. Two paid
            # measurements is the answer - the baseline grid and the enhanced
            # search - and a cheaper configuration is one more point in the
            # second one's space, not one more space. Everything the extra
            # round existed to gate, approve, and offer disappears with it.
            "how many paid runs the walkthrough performs",
            ("do not require a third optimization pass",),
            (
                "optional second enhanced run",
                "the second run's winner",
                "second enhanced run",
                "a third paid stage",
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
        ),
        (
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
        (
            # SKILL.md stage 5 asks, recommends preserving the agent's route,
            # and requires recipient disclosure before changing it. GUIDE.md
            # described the same situation as resolved silently in favour of
            # whichever vendor has a key - which sends the user's prompts to a
            # different company with no disclosure at all. The route sentence
            # landed in GUIDE.md (f2573a3) a day before 402023e settled the
            # rule in SKILL.md, run-safety.md and .env.example without
            # revisiting it.
            "who picks the provider route when the configured vendor has no key",
            ("never rewrite a route merely to match a key",),
            (
                "the assistant automatically uses the vendor the project already has configured",
                "the user only gets asked to choose if there is no usable vendor",
            ),
        ),
        (
            # The ceiling is not a billing guarantee in either case: the SDK
            # enforces its own per-optimization limit and "does not yet share
            # one cumulative budget with calibration and other calls". Two
            # documents attached "when cost is untracked" to that sentence,
            # which licenses telling a user with tracked cost that $5.00 is
            # guaranteed.
            "whether the walkthrough ceiling is ever a billing guarantee",
            ("never call the walkthrough ceiling a hard provider-billing cap",),
            (
                "for untracked cost, call it an execution stop target",
                "when any cost is untracked, that target is a conservative control",
            ),
        ),
        (
            # #169. The knob-selection rule shipped asserting that an
            # assistant-prepared baseline "sweeps only `model` and
            # `temperature`", and this same file already said the opposite
            # about thirty lines above: a reasoning-model strong rung drops
            # temperature for the whole walkthrough and uses two prompt styles
            # instead. Both failure directions are the ones the rule governs -
            # it told the assistant to compare scores across values that do not
            # exist, and to classify the one non-model knob the baseline DID
            # rank as never varied and therefore not a candidate.
            #
            # The settled answer is to read the axes off the space that ran
            # rather than to name them, which is also the only form that
            # survives the baseline's composition changing again.
            "which knobs an assistant-prepared baseline can rank",
            ("read which knobs it varied off the space that actually ran",),
            (
                "sweeps only `model` and `temperature`",
                "sweeps only model and temperature",
                "varies only `model` and `temperature`",
                "baseline's two axes are `model` and `temperature`",
            ),
        ),
        (
            # Settled at six when the baseline was three ladder models by one
            # further two-valued knob, and re-settled at twelve when a second
            # non-model axis was added so the selection rule downstream has
            # two levers to read rather than one. The previous settled answer
            # was deleted with the paragraph that carried it, which left the
            # registry with nothing to say about a decision that had just
            # changed - so it is restated here at its new value, and the
            # phrasings that assert the retired one are banned.
            #
            # This entry is the wording half. The arithmetic half is
            # `test_no_document_states_a_generated_space_size_the_fence_denies`,
            # which derives the number from the fence and needs no
            # foreknowledge of which sentence states it next.
            "how large the generated baseline sweep may be",
            ("3 models × 2 prompt styles × 2 thinking shapes = 12 configurations",),
            (
                "the three ladder models by one further swept knob taking two values",
                "at most three swept knobs, with no swept knob taking more than two values",
                "3 models × 2 temperatures = 6",
                "3 models × 2 prompt styles = 6",
                "six-row sweep",
                "six-row baseline",
                "six-row default",
                "six-configuration sweep",
                "six-configuration default",
                "six-point sweep",
                "six-point space",
                "six local fixed-grid configurations",
                "six baseline rows",
                "all six distinct",
                "all six intended",
            ),
        ),
        (
            # #127/#141: the held-out set came back, and with it the two
            # wrong things to say about the gap it exposes. Winner's-curse
            # selection bias plus ten rows' sampling noise means the gap is
            # inconclusive - not proof of overfitting, and not something
            # holdout support (not yet a real SDK feature) already prevents.
            "whether a tuning/held-out gap is called overfitting",
            ('do not call a gap in this range "overfitting,"',),
            ("small-data overfitting risk",),
        ),
        (
            "whether traigent already prevents the held-out gap",
            ("do not say traigent prevents or corrects this",),
            ("traigent prevents overfitting", "traigent already prevents this"),
        ),
        (
            # ML's conventional triple is train/validation/test, and this run
            # has neither three splits nor any training: the search optimizes
            # on one set, and the winner alone is scored on the other. The
            # package was spending four names on those two - "held-out",
            # "holdout", "validation", "test set" - so a reader met a third
            # word before finishing the first. One pair in customer copy; the
            # rest only to bridge to the reader's own vocabulary.
            "what the two splits are called in customer copy",
            ('say "tuning set" and "held-out set" to the user, and only that pair',),
            (
                "tuning split vs holdout (validation) split",
                "tuning set / held-back test set",
                "no tuning set and held-back test set",
                "followed by held-back validation",
                "shares examples with validation",
                "missing or overlapping validation split",
                # The stragglers the first sweep left behind. Each one is a
                # third noun in copy the assistant reads and repeats: the
                # exception clause for a project's own split, the instruction
                # naming what to call an assistant-authored one, the synthetic
                # evidence bullet, and the bounded-subset sampling rule.
                "own independent validation split",
                "held-back, non-blind validation",
                "non-blind validation evidence",
                "the held-out ten from the holdout split",
            ),
        ),
    )

    # Our own release history, in the words a customer reads. Every one of
    # these is a comparison to a run they have never made.
    OUR_CHANGELOG = (
        "previous version of this walkthrough",
        "earlier version of this walkthrough",
        "this walkthrough used to",
        "used to spend",
        "previous version of this guide",
        "in an earlier release",
    )

    def test_no_customer_facing_document_cites_our_release_history(self) -> None:
        """A first-run customer has no previous run to be compared against.

        The instance that produced this check was on the paid-spend approval
        card: `sdk-execution.md` told the assistant to say the baseline
        "doubles the baseline's paid trials against the previous version of
        this walkthrough", and `run-safety.md` repeated it as "double the 6
        this walkthrough used to spend, and the approval card says so in those
        words". A customer reading that is being asked to approve money against
        our changelog - a fact about our repository, presented as a fact about
        their run, on the one card where the number has to be about them.

        The rule is narrower than "never mention history": engineering
        rationale in a code comment is fine, and the ban is on the documents
        the assistant reads to the customer.
        """
        for name, text in self.conversation().items():
            for phrase in self.OUR_CHANGELOG:
                with self.subTest(document=name, phrase=phrase):
                    self.assertNotIn(
                        phrase,
                        text,
                        f"{name} compares this run to an earlier release of "
                        "this walkthrough. The customer has never run it, so "
                        "the comparison carries no information they can use "
                        "and reads as a discount on a price they never saw.",
                    )

    # The two splits have one customer-facing name each. These are the other
    # spellings, in the shape they appear when a script is talking ABOUT a
    # split rather than naming a field: a bare `holdout` is the identifier
    # vocabulary the guide deliberately kept (`holdout.jsonl`,
    # `HOLDOUT_DATASET`, `dataset-tune-holdout-overlap`, and the split labels a
    # user's own dataset may carry), so only the prose forms are banned.
    THIRD_NOUNS = (
        "validation set",
        "validation split",
        "test set",
        "held-back",
        "holdout row",
        "holdout set",
        "holdout split",
        "holdout input",
        "tuning and holdout",
        "tuning/holdout",
    )

    def test_no_bundled_script_prints_a_third_name_for_the_two_splits(self) -> None:
        """The registry above reads documents; the card and preflight print too.

        Both spellings this package settled against reached the user through a
        script rather than through prose - readiness printed "held-back test
        set" on the card's own evidence line, and preflight printed "no
        independent validation split was declared". A corpus of markdown files
        could not see either, so the sweep that found them was manual and the
        next one would have to be as well.

        String literals, not the whole file: `HOLDOUT_DATASET`, `holdout.jsonl`
        and the split labels a user's dataset may legitimately carry are the
        identifier vocabulary the decision explicitly kept. What is banned is
        prose - a script explaining a split to the reader in a third noun.
        """
        scripts = sorted((SKILL_ROOT / "scripts").glob("*.py"))
        self.assertEqual(
            [path.name for path in scripts],
            ["calibrate_evaluator.py", "preflight.py", "readiness.py"],
            "the bundled scripts have changed; this ban covers whatever this "
            "glob finds, so a script outside it is a script nobody checks",
        )
        for path in scripts:
            prose = self.script_prose(path.read_text())
            self.assertTrue(
                prose,
                f"no prose literal was extracted from {path.name}, so every "
                "ban below passed over an empty string",
            )
            for noun in self.THIRD_NOUNS:
                with self.subTest(script=path.name, noun=noun):
                    self.assertNotIn(
                        noun,
                        prose,
                        f"{path.name} says '{noun}' to the user. The pair is "
                        '"tuning set" and "held-out set"; a third noun sends '
                        "the reader looking for a third split.",
                    )

        # The extractor is the whole guard, and it fails OPEN: anything that
        # makes it return less - the `" " in` filter inverted, the glob
        # narrowed, a parse it stops reaching - leaves every ban above
        # asserting a noun is absent from a string that is empty. So it is run
        # against invented sources instead of only against the clean tree.
        # Both spellings below are the ones that actually shipped.
        self.assertIn(
            "validation split",
            self.script_prose(
                'MESSAGE = "no independent validation split was declared"'
            ),
        )
        self.assertIn(
            "held-back",
            self.script_prose('def f():\n    return "held-back test set"\n'),
        )
        # And the identifier vocabulary the decision deliberately KEPT is still
        # invisible to it, or the ban would be a false red against the names
        # the scripts are required to use.
        for kept in (
            'HOLDOUT_DATASET = "holdout.jsonl"',
            'CHECK = "dataset-tune-holdout-overlap"',
            'LABELS = ("tuning", "holdout")',
        ):
            with self.subTest(kept=kept):
                self.assertEqual(self.script_prose(kept), "")

    @staticmethod
    def script_prose(source: str) -> str:
        """Every multi-word string literal in `source`, casefolded and joined.

        Prose has spaces; an identifier, a split label, and a check id do not.
        """
        return " ".join(
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and " " in node.value
        ).casefold()

    def test_the_card_and_preflight_name_the_two_splits_the_settled_way(self) -> None:
        """The other half: the replacements are pinned, not merely the absence.

        A ban alone is satisfied by deleting the sentence. These are the four
        places a user actually reads a split's name outside the guidance - the
        power sub-score's two no-split branches, and preflight's split
        findings.
        """
        readiness = (SKILL_ROOT / "scripts" / "readiness.py").read_text()
        preflight = (SKILL_ROOT / "scripts" / "preflight.py").read_text()
        for phrase in (
            "tuning rows and no held-out set, so the ",
            "no tuning set and held-out set, so the result would be ",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readiness)
        for phrase in (
            "inputs overlap the tuning and held-out splits",
            "tuning and held-out inputs are disjoint",
            "tuning-only dataset; no held-out split was declared",
            "no explicit tuning/held-out split was found",
            "held-out rows; one example changes the score by ",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, preflight)

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
        # The cents are optional on purpose. `\$(\d+\.\d{2})` cannot match a
        # bare `$5`, so the one shape this value actually drifted into was the
        # one shape the check could not see: README.md said `$5` while every
        # guidance document said `$5.00`, and this entry was green throughout.
        # An unmatchable variant is not a passing check, it is an absent one.
        # `stop target` is here for the same reason - it is the phrase
        # run-safety.md requires the user be given, so it is the phrase the
        # ceiling is most likely to be restated under.
        # `estimate` joined the three anchors below after the coverage check
        # in `test_every_stated_cost_figure_is_read_by_the_ceiling_entry` was
        # written: SKILL.md states the ceiling as "if the estimate exceeds
        # `$5.00`", which names none of the other three words, so the pattern
        # read four of the five documents that carry the figure and SKILL.md
        # could have drifted to `$8.00` with this entry green. That is the same
        # miss as the `$5` one recorded above, found the same way - by asking
        # what the pattern does NOT reach rather than whether it passes.
        (
            "the total walkthrough ceiling",
            r"(?:ceiling|walkthrough|stop target|estimate)"
            r"[^.]{0,40}?\$(\d+(?:\.\d{2})?)",
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

        Run over the conversation corpus, not the progressive-load one. The
        guidance corpus excludes README.md, which is where the walkthrough
        ceiling is quoted to a reader who has installed nothing yet - so the
        one document most likely to be edited without opening SKILL.md was the
        one document this check could not read. Every entry in the table above
        already agrees across the wider corpus; widening it costs nothing and
        closes the hole it was measured through.
        """
        documents = self.conversation()
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

    # Cost figures that are deliberately NOT the walkthrough ceiling: a free
    # route genuinely costs nothing, and `$0.00` is the value sdk-execution.md
    # forbids printing for an absent cost. Both are decisions of their own, so
    # they are named here rather than being swept up by a check about a
    # different number.
    NON_CEILING_COST_FIGURES = frozenset({"0", "0.00"})

    def test_every_stated_cost_figure_is_read_by_the_ceiling_entry(self) -> None:
        """The shared-value table checks agreement; this checks it is looking.

        Its own comment records how this fails: the ceiling pattern could not
        match a bare `$5`, so the one shape the value actually drifted into was
        the one shape the check could not see, and the entry stayed green
        through it. That is a property of anchored patterns generally, not of
        that one spelling - the entry reads whichever sentences happen to use
        its words, and says nothing about the sentences that do not.

        Measured before `estimate` was added to it: five documents carry the
        ceiling figure and the pattern reached four. SKILL.md states it as "if
        the estimate exceeds `$5.00`", so SKILL.md - the document that carries
        the flow - could have drifted alone with the agreement check green.

        So every cost figure in the corpus is now accounted for: either the
        ceiling entry read it, or it is named above as a different decision. A
        sixth restatement in a new phrasing fails here rather than silently
        leaving the table's coverage one document smaller.

        One case it does not flag, stated rather than left to be discovered: an
        unreadable restatement of the SAME figure, in a document that already
        states it readably, passes - the value is accounted for in that
        document either way. It cannot drift while passing, which is the risk
        this exists for; measured, moving that restatement to `$8.00` fails
        here naming the document and the figure.
        """
        ceiling = dict(self.SHARED_VALUES)["the total walkthrough ceiling"]
        unread: dict[str, list[str]] = {}
        for name, text in self.conversation().items():
            read = set(re.findall(ceiling, text, re.IGNORECASE))
            missed = [
                amount
                for amount in re.findall(r"\$(\d+(?:\.\d{1,2})?)", text)
                if amount not in read and amount not in self.NON_CEILING_COST_FIGURES
            ]
            if missed:
                unread[name] = sorted(set(missed))
        self.assertEqual(
            unread,
            {},
            "a cost figure is stated in a phrasing the shared-value ceiling "
            "entry does not read, and is not declared to be a different "
            "number. It can drift alone, which is what that entry exists to "
            "prevent.",
        )
        # The entry is asserted to actually reach the document whose phrasing
        # it was widened for, so a later tightening cannot quietly undo it.
        self.assertTrue(
            re.search(ceiling, self.conversation()["SKILL.md"], re.IGNORECASE),
            "the ceiling entry no longer reads SKILL.md, which states the "
            "figure without using the word `ceiling`",
        )
        # Both directions against invented text: a new phrasing must be
        # unreadable by the pattern (so the coverage check above has something
        # to catch), and the declared exemptions must stay exempt.
        self.assertIsNone(
            re.search(ceiling, "A single trial may cost `$0.40` on this model."),
            "the coverage check is meaningless if the pattern reads every "
            "sentence that mentions money",
        )
        self.assertTrue(
            re.search(ceiling, "Use one total walkthrough ceiling, `$5.00`."),
        )

    # Every way a document states the size of one of the two generated spaces.
    # Each entry captures the QUANTITY and nothing else, so the check is
    # against the number the fence derives rather than against a spelling:
    # writing "6" into a sentence that today says "twelve" fails exactly as
    # writing "six" does, and a re-sizing to any other number fails both.
    #
    # Both spaces are listed on purpose. The guard that already exists for
    # this class only inspects `N and M` pairs whose M is the enhanced count,
    # so it sees a wrong baseline count only in the one sentence shape that
    # happens to name both - it was silent on the six other documents' worth
    # of "six-row sweep", and on "all six distinct points" two hundred lines
    # below it in its own file. A one-sided guard reads as coverage while the
    # unwatched side drifts, so neither side is unwatched here.
    BASELINE_SIZE_CLAIMS = (
        # "twelve-row sweep", "twelve-configuration fixed sweep",
        # "twelve-point space". `baseline` is deliberately not one of these
        # nouns: a PRESERVED baseline has whatever size the user defined, so a
        # row count beside that word is not a claim about the generated sweep.
        r"\b(\w+)-(?:row|point|configuration) (?:fixed )?(?:sweep|grid|default|space)\b",
        # The generated sweep is also called "the <N>-row baseline target".
        r"\b(\w+)-row baseline\b",
        # "all twelve distinct points executed", "all twelve intended rows".
        r"\ball (\w+) (?:distinct|intended)\b",
        r"\ball (\w+) configurations of a local\b",
        r"\b(\w+) baseline rows\b",
        r"baseline[^.]{0,90}?= (\d+) configurations",
        r"\brun as (\d+) trials\b",
        r"\bbaseline's (\d+) trials\b",
        r"\bexpand it to (\w+)\b",
        # The EXECUTABLE statements, which this guard was missing entirely.
        # Swept across all 34 open branches: of the 19 six-statements trunk
        # still carries, these patterns caught 15 - and the four they missed
        # included BOTH of the fence's own asserts and the environment default
        # feeding one of them. A guard that reads every sentence about the
        # size and not the two lines that decide it is checking the commentary
        # while the code drifts underneath. `sdk-execution.md` is prose around
        # a code block, so the block is matched as text like everything else.
        r"configuration_count\(baseline_space\) == (\d+)",
        r"first_run_baseline_trials\", default=(\d+)",
        # `a credible six-point standard sweep` walked past the noun-phrase
        # pattern above because one adjective sat between the quantity and the
        # noun. Anchored on the quantity and the noun with the adjectives left
        # open, so the next writer's adjective does not reopen the hole.
        r"\b(\w+)-point (?:\w+ )?sweep\b",
    )

    ENHANCED_SIZE_CLAIMS = (
        r"\b(\w+)-configuration enhanced\b",
        r"enhanced[^.]{0,90}?= (\d+) configurations",
        r"\bthe same (\w+) whatever\b",
        r"\bbinary knobs = (\d+)\b",
        r"\bexactly (\d+) configurations\b",
        r"configuration_count\(enhanced_space\) == (\d+)",
    )

    # The number beside these is a size the generated sweep is forbidden to
    # have, not a size it has: a preserved one-row baseline stays one row, and
    # an assistant-prepared walkthrough may not proceed with one. Matched on
    # the words immediately before the quantity so the exemption cannot spread
    # to a sentence that merely mentions a preserved baseline nearby - "the
    # preserved baseline or generated twelve-row sweep" is still checked.
    NOT_THE_GENERATED_SWEEP = ("preserved ", "proceed with a ", "user-owned ")

    # The other quantity in this package that is counted in ROWS and sized by
    # a default: the held-out split. `evaluation-and-dataset.md` writes "the
    # ten-row default" of it, which `(\w+)-row default` matches exactly as
    # readily as SKILL.md's "generated twelve-row default" - and the preceding
    # words there are "required on the", so the prefix exemption above cannot
    # see it. Merged with the branch that owns the split, this guard failed
    # with "these documents state {'evaluation-and-dataset.md': [10]}" on
    # prose that is right: the fix belongs to the pattern, not to a sentence
    # about the held-out set.
    #
    # Scoped to the SENTENCE rather than to a fixed window, because the words
    # that identify the subject sit wherever the author put them - in that
    # sentence, the only signal is "the split has", eleven words after the
    # quantity. Every true positive in the corpus is checked against this and
    # none of them names the split, which is the property that makes the
    # exemption safe rather than convenient.
    HELD_OUT_SPLIT = re.compile(r"held-?out|the split")
    # ...and the guard against the exemption widening: a sentence that names
    # BOTH the held-out split and the generated sweep is a sentence stating
    # the sweep's size, so it stays checked. Without this, adding "held-out"
    # anywhere in "the preserved baseline or generated twelve-row sweep" would
    # silently switch that statement off.
    STILL_THE_GENERATED_SWEEP = re.compile(r"generated|swept|grid")

    # `(\w+)` will happily capture the tail of a number that was written with a
    # separator: `a 10 000-configuration space` yields "000", which resolves to
    # 0 and is reported as a document claiming a zero-configuration baseline.
    # A thousands group is not a quantity, and the character before the capture
    # is what says so - a digit, or a digit and one space.
    NUMBER_FRAGMENT = re.compile(r"[\d,]\s?$")

    def _states_the_held_out_split(self, text: str, start: int, end: int) -> bool:
        opening = text.rfind(". ", 0, start) + 2
        closing = text.find(". ", end)
        sentence = text[opening : closing if closing != -1 else len(text)]
        return bool(self.HELD_OUT_SPLIT.search(sentence)) and not bool(
            self.STILL_THE_GENERATED_SWEEP.search(sentence)
        )

    def test_no_document_states_a_generated_space_size_the_fence_denies(self) -> None:
        """A size the assistant reads may not disagree with the size it runs.

        `sdk-execution.md` asserts both generated space sizes in executable
        code, and every assistant-facing document then speaks them again in
        prose - which is where they rot. The branch that took the baseline
        from six configurations to twelve updated the asserts and one bullet
        and left thirteen statements saying six, spread over five documents:
        each correct-looking on its own, none of them visible in the diff that
        broke it. An assistant reading SKILL.md built a six-configuration
        sweep against a fence asserting twelve, and stage 8 told it to verify
        that the six-row default had run on a run that emits twelve.

        So the size is derived from the code (see `generated_space_sizes`) and
        every stated size has to equal it. Nothing here pins the wording:
        re-sizing the baseline to eight breaks this test in every document
        that still says twelve, which is the moment those documents are meant
        to be re-read rather than the moment one of them is missed.

        Each pattern must also still match something. A pattern that matches
        nothing has stopped checking anything while continuing to pass, and
        that is how a guard for this class goes quiet without anyone noticing.
        """
        sizes = generated_space_sizes()
        # The public promises too, not only the loaded guide: README.md stated
        # the baseline's size to the user before they ever cloned anything.
        documents = self.conversation()
        for space, patterns in (
            ("baseline", self.BASELINE_SIZE_CLAIMS),
            ("enhanced", self.ENHANCED_SIZE_CLAIMS),
        ):
            expected = sizes[space]
            for pattern in patterns:
                with self.subTest(space=space, pattern=pattern):
                    stated: dict[str, set[int]] = {}
                    for name, text in documents.items():
                        for match in re.finditer(pattern, text):
                            preceding = text[max(0, match.start() - 24) : match.start()]
                            if preceding.endswith(self.NOT_THE_GENERATED_SWEEP):
                                continue
                            # Against the QUANTITY's own position, never the
                            # match's: `binary knobs = (\d+)` starts eleven
                            # characters after the `4` of "3 models x 4", and
                            # testing the match start there would silently
                            # exempt the enhanced space's only statement.
                            if self.NUMBER_FRAGMENT.search(text[: match.start(1)]):
                                continue
                            if self._states_the_held_out_split(
                                text, match.start(), match.end()
                            ):
                                continue
                            stated.setdefault(name, set()).add(
                                _quantity(match.group(1))
                            )
                    self.assertTrue(
                        stated,
                        f"no document states the {space} space's size this way "
                        "any more. If the wording moved, move this pattern with "
                        "it; leaving one that matches nothing is a check that "
                        "cannot fail.",
                    )
                    wrong = {
                        name: sorted(values)
                        for name, values in stated.items()
                        if values != {expected}
                    }
                    self.assertEqual(
                        wrong,
                        {},
                        f"the fence asserts a {space} space of {expected} "
                        f"configurations, and these documents state {wrong}. "
                        "An assistant follows the document it read last, so a "
                        "stale number here is a run built to the wrong size.",
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
                    reason=self.reason_for(
                        "0001 - the ledger this mechanism inherited"
                    ),
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

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "traigent-first-run"
SKILL = SKILL_ROOT / "SKILL.md"


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


RUN_SAFETY = SKILL_ROOT / "references" / "run-safety.md"
SDK_EXECUTION = SKILL_ROOT / "references" / "sdk-execution.md"

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

    fence = re.findall(r"```python\n(.*?)\n```", text, re.DOTALL)[0]
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
                widths[key.value] = spaces[value.value.id.removesuffix("_SPACE")][
                    value.slice.value
                ]
            else:
                raise AssertionError(
                    f"{target.id}[{key.value!r}] is neither a list of candidate "
                    "values nor a reference to another space's list, so its "
                    "width cannot be derived"
                )
        spaces[name] = widths

    constructed = {name: math.prod(widths.values()) for name, widths in spaces.items()}
    assert constructed == asserted, (
        f"the fence asserts {asserted} but the spaces it defines are "
        f"{constructed}; the template contradicts its own asserts"
    )
    return {name.casefold(): size for name, size in asserted.items()}


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

        requirements = (
            (SKILL_ROOT / "assets" / "requirements-first-run.txt")
            .read_text()
            .splitlines()
        )
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
            "too little comparable evidence exists",
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
                if match.group("tail") and not match.group("host"):
                    continue  # a package path continuing on, not a repository
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
        for phrase in (
            "something is missing or invalid",
            "too little comparable evidence for a trustworthy paid comparison",
            "fewer than ten comparable examples",
            "limits what the result may claim without saying anything is wrong",
            "it does not mean every component is broken",
            "a cap that only limits the claim does not set it",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, glossary)

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
            # The doubled baseline is disclosed in the words the customer reads,
            # not left for them to derive from two numbers.
            "this doubles the baseline's paid trials",
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
            "AGENT_TYPE",
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
        self.assertEqual(document["agent_type"], namespace["AGENT_TYPE"])
        self.assertEqual(document["max_trials"], namespace["ENHANCED_MAX_TRIALS"])
        self.assertNotIn("configuration_space", document)
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
        sdk = SDK_EXECUTION.read_text()
        for phrase in (
            'State them exactly,\nnever as "roughly" or "about"',
            "3 models × 2 prompt styles × 2 thinking shapes = 12 configurations",
            "3 models × 4 binary behaviour knobs = 48 configurations",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, sdk)

        run_safety = " ".join(RUN_SAFETY.read_text().split())
        for phrase in (
            "**The same 48 whatever the customer brings.**",
            "gets a 48-configuration enhanced space too, not a larger one",
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
        self.assertGreaterEqual(strong_call["max_tokens"], 4096)
        self.assertNotIn("temperature", strong_call)

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
        preflight_module = ast.parse(preflight)
        preflight_methods = next(
            ast.literal_eval(node.value)
            for node in preflight_module.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "REFERENCE_FREE_METHODS"
                for target in node.targets
            )
        )
        self.assertEqual(preflight_methods, set(READINESS.REFERENCE_FREE_METHODS))
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
        # A tenth dataset cap must be routed too, so pin the count rather
        # than spot-checking the nine that exist today.
        self.assertEqual(len(conditions), 9)
        normalized = " ".join(SKILL.read_text().casefold().split())
        routing = normalized.split("route every active dataset cap", 1)[1]
        for condition, branch in (
            ("dataset-absent", "creation dependency matrix"),
            ("dataset-no-expected-outputs", "repairing a labelled working copy"),
            ("dataset-integrity-fail", "repair and revalidate a working copy"),
            ("dataset-tune-holdout-overlap", "repair a disjoint split"),
            ("dataset-fully-synthetic", "walkthrough labeling rules"),
            ("dataset-mostly-synthetic", "name the split out loud"),
            (
                "dataset-generated-answer-key",
                "a person reviews a sample of the answers",
            ),
        ):
            with self.subTest(condition=condition):
                self.assertIn(condition, conditions)
                self.assertLess(routing.index(condition), routing.index(branch))
        self.assertIn("present the reason rather than the condition id", normalized)

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
        # The pillar's own score, re-measured rather than carried over, and the
        # drop from 90 is a real trade this space made on purpose, recorded so
        # nobody reads it as a regression.
        #
        # `knob_variation` scores a categorical knob at FULL breadth from two
        # distinct values, and the numeric-without-a-canonical-range path keeps
        # the old `(distinct - 1) / 2`. So the four binary behaviour knobs
        # score 1.0 each and `model` 1.0; the shortfall is the pinned
        # `temperature`, which earns the 0.1 pin credit and drags the mean to
        # 0.85, which is 38.25 of 45. The 90 came from three-valued
        # `prompt_style` and `temperature` sweeps, which scored the variation
        # sub-score better and bought the search nothing the owner wanted:
        # temperature adds surface noise an exact-match evaluator punishes.
        #
        # So this is a predictable-space decision paid for in one sub-score
        # that measures breadth of values rather than usefulness of knobs. It
        # is stated here rather than smoothed over, and it is not a reason to
        # add a third value to a knob that has two real settings.
        #
        # 93 rather than 94 since `coverage` was removed: it scored this space
        # 25/25, and the remaining two were re-weighted 55/45 - so the
        # variation shortfall is measured against 45 points instead of 40 and
        # costs one point more.
        self.assertEqual(pillar.score, 93)
        counted = next(s for s in pillar.subscores if s.name == "knob-count")
        self.assertEqual(
            counted.evidence, "5 of 6 wired knobs actually vary; 48 combinations"
        )
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

    def test_agent_type_moves_no_score_and_the_contract_says_so(self) -> None:
        """`agent_type` selected a catalog for a sub-score that no longer exists.

        Two halves, and only together are they worth anything. The behaviour:
        the same space scored under every accepted `agent_type` - and under an
        unrecognised one - must produce the identical pillar, sub-scores and
        confidence, because nothing in the scorer reads the field any more.
        The contract: `run-safety.md` has to say so, since a reader deciding
        what to put in the document is owed the fact that it costs nothing to
        get wrong.

        Written this way round on purpose. Asserting only the sentence would
        pass while the field silently regained an effect, and asserting only
        the behaviour would leave a field-table row that still promises one.
        """
        space = {
            "knobs": {
                "model": ["a", "b", "c"],
                "retrieval_k": [1, 5],
                "prompt_style": ["direct", "structured"],
            },
            "max_trials": 12,
            "wired": ["model", "retrieval_k", "prompt_style"],
        }

        def scored(agent_type):
            document = dict(space)
            if agent_type is not None:
                document["agent_type"] = agent_type
            pillar, _ = score_config_space(document)
            return (
                pillar.score,
                pillar.confidence,
                tuple(
                    (s.name, s.value, s.maximum, s.measured) for s in pillar.subscores
                ),
            )

        # `rag` names `retrieval_k` and `context_format`; `general` and
        # `code_gen` do not. Under the old sub-score those three answers
        # differed by design, which is what makes them the probe.
        baseline = scored("general")
        for agent_type in ("rag", "code_gen", None, "", "a-type-no-catalog-has"):
            with self.subTest(agent_type=agent_type):
                self.assertEqual(scored(agent_type), baseline)

        row = next(
            line
            for line in RUN_SAFETY.read_text().splitlines()
            if line.startswith("| `agent_type` |")
        )
        self.assertIn("changes no number", row.casefold())

    def test_the_glossary_names_exactly_the_agent_lines_the_card_prints(self) -> None:
        """The card's Agent lines and the glossary's list are one decision.

        Read off `CHECK_DISPLAY_NAMES` rather than quoted, so removing a
        sub-score without removing its glossary entry fails here - which is the
        mutation that survived when `coverage` was dropped, leaving the
        customer a definition for a line the card no longer prints.
        """
        printed = {
            READINESS.CHECK_DISPLAY_NAMES[name]
            for name in ("knob-count", "variation")
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
    )

    ENHANCED_SIZE_CLAIMS = (
        r"\b(\w+)-configuration enhanced\b",
        r"enhanced[^.]{0,90}?= (\d+) configurations",
        r"\bthe same (\w+) whatever\b",
        r"\bbinary knobs = (\d+)\b",
        r"\bexactly (\d+) configurations\b",
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
        # Raised from 60_000 to 60_500 by #123's follow-up, which reframes the
        # enhanced run's trial count for the reader who sees it at approval
        # time: the card now states a ceiling against the space's own
        # combination count instead of a range. The exact copy went to
        # run-safety.md, which owns the approval disclosure, so what landed
        # here is the mandate and the pointer - SKILL.md's own job. That is
        # new contract surface with no prior statement, not stage detail that
        # belongs in a reference. Half a kilobyte, because that is what the
        # mandate costs; a rounder number would bank headroom for the next
        # edit nobody weighed.
        #
        # The graduation handoff adds three mandates that only SKILL.md can
        # carry - the closing run-scope statement, its repetition on the
        # no-lift path, and the evidence-selected skills handoff - because each
        # is an ordering decision about the close, and the depth behind all
        # three moved into run-safety.md rather than into SKILL.md. That branch
        # raised this to 62_000 against a 60 KB base. #131 has since landed and
        # moved stage detail OUT of SKILL.md, which lowered the base - but not
        # by enough to absorb the three new mandates: the merged package
        # measures 61_129, over trunk's 60_500. So this genuinely rises, and
        # the figure below is the MEASURED merged resident rather than either
        # branch's - 62_000 would have banked 871 bytes nobody weighed.
        #
        # 61_500 and not the narrower 61_250: the 60_000 ceiling this file
        # carried before left 23 bytes of headroom, which is a ceiling that
        # trips on a one-word edit rather than on a decision. 371 bytes is the
        # smallest headroom that still makes the next raise a choice.
        self.assertLess(
            resident,
            61_500,
            f"resident guidance is {resident / 1024:.0f} KB - the part in "
            "context for the whole run, competing with the user's project from "
            "the first turn. Stage detail belongs in the reference for that "
            "stage, which the run can load and leave.",
        )
        # Count the actual UTF-8 files, not Unicode code points or a
        # whitespace-normalized proxy. The ceiling in #104 is a byte ceiling.
        total = sum(document_bytes.values())
        # The #104 migration lowered this from 220 KB after removing duplicated
        # environment, account, approval, config-lifecycle, and reporting detail
        # from resident SKILL.md. The new execution-evaluator safety contract is
        # real reference depth, not a reason to leave the old ceiling behind.
        # Resident fell from roughly 69 KB to 54 KB and TOTAL from roughly
        # 220 KB to 209 KB even with that new safety material, so both lowered
        # numbers record the shape change rather than merely making today's
        # text pass.
        #
        # The policy, so the next person does not have to invent one:
        #
        #   SKILL.md carries the ordered flow and the mandates. A reference
        #   carries the depth behind one stage. When this ceiling is reached,
        #   stage detail moves OUT of SKILL.md into the reference that owns
        #   that stage, and SKILL.md keeps the ordering and the decision. It
        #   does not move by growing a new document, because two of the four
        #   contradictions in this package's history were between SKILL.md and
        #   a reference, and every split is another seam for them.
        #
        # Raising this number is allowed and is a decision: change it here,
        # with the reason, in the same commit as the guidance that needs it.
        # PRs #125 and #126 add user-facing explanations for readiness evidence
        # and exact pre-run cards. Those are new contract surface, not duplicated
        # stage detail, so raise TOTAL by 5 KB while retaining a narrow ceiling.
        # #133 adds the present-but-unresolved-evaluator distinction (a new
        # evidence classification and its create/select vs. inspect/repair/
        # replace routing) to SKILL.md and evaluation-and-dataset.md - also new
        # contract surface, not duplicated stage detail - so raise TOTAL by
        # roughly 1 KB, keeping the ceiling as narrow as the addition allows.
        #
        # #123's follow-up raises it again, by 1.5 KB. The enhanced run's count
        # is now spoken to the user as a ceiling against the space it is drawn
        # from, and run-safety.md carries the copy for that plus the form it
        # degrades to when the combination count cannot be computed. Two of
        # those three sentences replace nothing, because the previous framing
        # said only a number. Against that, the duplicate statement of the
        # 10-row shortfall obligation left run-safety.md, since #123 had
        # already made sdk-execution.md its one home.
        #
        # #133 and #123's follow-up landed independently and each raised this
        # number from 220_000 for its own increment, both arriving at 221_500 -
        # so the merge produced no textual conflict on the line, only on the
        # reasons above it. Merged, the package carries BOTH additions and
        # measures 222_750, which neither branch's figure admits. The ceiling
        # is therefore set here against the measured combined total: this is
        # the arithmetic neither branch could do alone, and taking either
        # side's number would have failed the suite rather than the review.
        #
        # #131 merges that trunk in and adds the journey structure on top, and
        # the same arithmetic trap recurs one merge later: trunk said 223_000
        # and #131 said 222_250, and the merged package measures 223_442 - so
        # BOTH figures are too low again, for the same reason. The two changes
        # are additive because they change different things. #137 owns how the
        # enhanced count is *stated* - the ceiling copy and its degraded form,
        # which land in run-safety.md. #131 owns the journey *structure* - the
        # five-stage opening in GUIDE.md, the readiness presentation in
        # glossary.md, and splitting one combined approval into a baseline
        # approval and a separate connected-stage approval, which is the bulk
        # of run-safety.md's share. Against that, #131 moved stage detail out
        # of SKILL.md, so resident guidance falls to roughly 58 KB even while
        # TOTAL rises, and the RESIDENT ceiling above is left where it is
        # rather than raised; the ceiling copy sits in the reference for the
        # stage that owns it, which is the policy above working rather than
        # being spent. So the number below is the MEASURED merged total,
        # 223_442, rounded up to the next 250 - not either branch's figure,
        # and not an estimate. Measure it; do not take a side.
        #
        # The graduation handoff then adds the run-scope derivation and the
        # evidence-to-skill map to run-safety.md's post-run section - the
        # reference that already owns the close - so this is the policy above
        # working, not a bypass of it. That branch raised TOTAL by 6 KB to
        # 226_000 against a 220 KB base it branched from; trunk has since
        # reached 223_750 by the two merges recorded above. The number below is
        # the MEASURED merged total once more - 228_407 rounded up - and it is
        # the fourth consecutive merge in which neither side's figure was
        # correct, which is the whole reason this comment keeps growing instead
        # of the number being guessed. Every branch weighs its own increment
        # against the base it branched from; only the merge knows the sum.
        # Exact configuration counts then raise this to 231_500, a deliberate
        # 2_750-byte raise recorded with its reason because the previous
        # ceiling left 234 bytes.
        #
        # What was bought: the enhanced space is now 3 models x 4 binary
        # behaviour knobs = 48 configurations and the baseline 3 models x 2
        # prompt styles x 2 thinking shapes = 12, both stated as exact numbers
        # and both asserted in the template. (This sentence said "= 6" until
        # the size was re-settled at twelve four commits later, which put the
        # exact phrasing the CONTRADICTIONS registry BANS 480 lines below the
        # ban list carrying it. The registry cannot catch that and should not
        # try: `conversation()` reads the guidance, and adding this file to
        # that corpus would make every entry fail against its own banned
        # phrases. A ledger that restates a decision has to be corrected with
        # the decision, which is what this is.)
        # That is two new knobs (`thinking_shape`, `reflect`)
        # with their prompt branches, the derivation of why four behaviour
        # knobs replace a temperature sweep, and the subset/pin/size asserts -
        # none of which existed to be reworded.
        #
        # What it retires, which is the part that pays some of it back:
        # temperature used to be dropped only when the strong tier reasoned, so
        # the enhanced space was 54 ordinarily and 18 under a reasoning rung -
        # a second pair of sizes that appeared in no document, and a
        # conditional that the ladder section, the sweep-uniformly paragraph
        # and run-safety.md each restated. Those three collapse into one
        # unconditional pin, and the between-runs "replace the placeholder
        # temperature" step disappears with the swept range it existed to
        # re-centre.
        #
        # The same branch then extends the baseline-evidence selection rule
        # from one direction to two: which knobs the enhanced space carries was
        # already read off the baseline, which VALUES each carries was not, so
        # the enhanced run re-tested values the baseline had already measured
        # as poor. That rule is a conditional with two branches, an explicit
        # shared threshold, and a disclosure obligation - none of which had a
        # prior statement to be folded into.
        #
        # 233_750 and not 233_500: 519 bytes rather than 269, because the
        # previous ceiling's 234 is what made every branch in this batch
        # re-litigate the same arithmetic. Measured 233_231.
        #
        # Raised to 242_250 deliberately, and this is the reason.
        #
        # The knob catalog is the one addition here that is content rather than
        # rule. Twelve knobs, each with the condition that selects it, and
        # twelve one-sentence explanations printed to the customer once the
        # enhanced run is under way. It is bytes that no rewording folds away,
        # because a list of twelve things is twelve things - and it is the
        # point: the customer sees the breadth Traigent knows and pays for
        # four, which cannot be said without saying what the other eight are.
        # The explanations are held to one sentence each and forbidden from
        # citing anything (`test_the_knob_explanations_cite_nothing`), so the
        # section cannot grow into an essay under a later edit.
        #
        # What it pays back: `self_check` is gone. It and `reflect` were one
        # knob under two names, and every place that listed the four behaviour
        # knobs listed both, plus the paragraph in the prompt builder
        # explaining how they differed - a distinction that had to be restated
        # precisely because no reader could keep it.
        #
        # The baseline moving from 6 to 12 costs almost nothing in bytes: it is
        # the same sentences with different numerals, plus the disclosure that
        # the customer's paid trials doubled, which is one sentence and not
        # optional.
        #
        # 242_250 and not 242_000: 454 bytes of headroom rather than 204, on
        # the same reasoning the 519 above used. Measured 241_796.
        budget = 242_250
        self.assertLess(
            total,
            budget,
            f"assistant-facing guidance is {total / 1024:.0f} KB against a "
            f"{budget / 1024:.0f} KB budget. Every rule added is also a surface "
            "for two rules to disagree on. Prune scope, or raise this number "
            "deliberately with a reason.",
        )


if __name__ == "__main__":
    unittest.main()

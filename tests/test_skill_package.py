from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "traigent-first-run"
SKILL = SKILL_ROOT / "SKILL.md"
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

    def test_user_facing_skill_language_does_not_label_the_user(self) -> None:
        combined = "\n".join(
            path.read_text() for path in SKILL_ROOT.rglob("*.md") if path.is_file()
        ).casefold()
        self.assertNotIn("beginner", combined)
        self.assertNotIn("non-technical", combined)
        self.assertNotIn("not for experienced", combined)

    def test_active_run_guidance_contains_only_required_account_links(self) -> None:
        combined = "\n".join(
            path.read_text()
            for path in [
                SKILL,
                *sorted((SKILL_ROOT / "references").glob("*.md")),
            ]
        )
        urls = re.findall(r"https?://[^`\s)]+", combined)
        allowed_hosts = {
            "portal.traigent.ai",
            "openrouter.ai",
            "platform.openai.com",
            "console.anthropic.com",
        }
        for url in urls:
            host = url.split("/", 3)[2]
            self.assertIn(host, allowed_hosts)

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
            "one concise approval",
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
            "do not create a separate provider-choice question",
            "stop once",
            "do not ask the user to choose cost, retries, or timeout settings",
            "one concise combined approval",
            "`$5.00` total walkthrough ceiling by default",
            "do not add or ask the user to configure another retry policy",
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
            "llm-judge calibration",
            "preserved baseline or a generated six-row sweep",
            "one broader bounded optimization",
            "baseline winner versus enhanced winner holdout comparison",
        ):
            self.assertIn(paid_phase, skill_text)

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
        skill_text = SKILL.read_text()
        safety_text = RUN_SAFETY.read_text()

        for text in (skill_text, safety_text):
            self.assertIn("conventional `.venv`", text)
            self.assertIn("implementation detail", text)
        self.assertIn("`.venv` already exists but is\n   incompatible", skill_text)
        self.assertIn(
            "`.venv` already exists but uses an incompatible interpreter", safety_text
        )
        self.assertIn("python3.13 -m venv .venv-traigent", safety_text)
        self.assertNotIn("python3.13 -m venv .venv`", safety_text)

    def test_provider_inventory_is_separate_from_route_selection(self) -> None:
        skill_text = " ".join(SKILL.read_text().casefold().split())
        safety_text = " ".join(RUN_SAFETY.read_text().casefold().split())
        for text in (skill_text, safety_text):
            self.assertIn("credential", text)
            self.assertIn("do not", text)
            self.assertIn("route", text)
        self.assertIn("credential names only as an availability inventory", skill_text)
        self.assertIn("stop with one clear mismatch", skill_text)
        self.assertIn(
            "never rewrite the model identifier or provider prefix", skill_text
        )

    def test_stdlib_component_checks_precede_environment_and_secret_gates(
        self,
    ) -> None:
        text = SKILL.read_text()
        local_heading = "### 4. Validate components locally"
        environment_heading = "### 5. Prepare the environment and finish free checks"
        paid_heading = "### 6. Ask once before paid work"
        for heading in (local_heading, environment_heading, paid_heading):
            self.assertIn(heading, text)

        local_section = text.split(local_heading, 1)[1].split(environment_heading, 1)[0]
        environment_section = text.split(environment_heading, 1)[1].split(
            paid_heading, 1
        )[0]
        normalized_local = " ".join(local_section.casefold().split())
        normalized_environment = " ".join(environment_section.casefold().split())

        preflight = normalized_local.index("run the bundled static preflight")
        calibration = normalized_local.index("run deterministic evaluator calibration")
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
            "reuse an existing compatible isolated environment",
            "install the exact declared dependencies",
            "verify the installed sdk's capabilities",
            "run a fresh-process traigent mock plumbing check",
            "create the minimal `.env`",
            "stop once",
        )
        positions = [
            normalized_environment.index(phrase)
            for phrase in ordered_environment_phrases
        ]
        self.assertEqual(positions, sorted(positions))

    def test_run_safety_keeps_external_evaluators_and_provider_calls_gated(
        self,
    ) -> None:
        text = RUN_SAFETY.read_text()
        gate = text.split("Use this gate order:", 1)[1].split(
            "Do not split paid work", 1
        )[0]
        normalized_gate = " ".join(gate.casefold().split())
        ordered_gate_phrases = (
            "perform and record the evidence-backed semantic-coverage review",
            "if unresolved product-grading ambiguity",
            "run the bundled static preflight",
            "run deterministic evaluator calibration",
            "reuse an existing compatible isolated environment",
            "install the exact declared dependencies",
            "use the installed sdk's public dataset validator/loader",
            "run a fresh-process traigent mock plumbing check",
            "create the minimal `.env`",
            "stop once",
        )
        positions = [normalized_gate.index(phrase) for phrase in ordered_gate_phrases]
        self.assertEqual(positions, sorted(positions))

        normalized_safety = " ".join(text.casefold().split())
        for phrase in (
            "do not execute an llm judge",
            "uncertain or external evaluator",
            "explicit combined approval",
            "make model/provider calls",
        ):
            self.assertIn(phrase, normalized_safety)

    def test_portal_probe_gates_connected_work_not_the_baseline(self) -> None:
        """The key ask must never be able to overtake the baseline (#77).

        Three instructions bear on when the Traigent key is needed: stage 5
        collects keys, the portal-tracking probe runs before connected work,
        and stage 7 asks for the key only after the first result is on screen.
        A user arriving with no account has a valid order only while the probe
        is scoped to *connected* trials - if it gates the first paid trial of
        any kind, the provider-paid baseline drags the whole registration
        funnel in front of it, which is the ordering stage 7 exists to avoid.
        """
        skill_text = " ".join(SKILL.read_text().casefold().split())
        safety_text = " ".join(RUN_SAFETY.read_text().casefold().split())

        # The probe's trigger is reaching the portal, not spending money.
        self.assertIn("before the first connected paid trial", skill_text)
        self.assertNotIn("before the first paid trial,", skill_text)
        self.assertIn("the baseline is not gated on this probe", skill_text)
        self.assertIn("the probe gates connected work, not provider spend", safety_text)

        # Stage 5 may not send an account-less user through registration; that
        # ask belongs to stage 7, after the first result.
        self.assertIn(
            "do not send a user who has no traigent account through registration at this step",
            skill_text,
        )
        self.assertIn(
            "only after that first result is on screen, ask for the traigent key",
            skill_text,
        )

        # And the baseline still has to precede the key ask in the document.
        baseline_position = skill_text.index(
            "the baseline needs only the user's own provider"
        )
        key_ask_position = skill_text.index("only after that first result is on screen")
        self.assertLess(baseline_position, key_ask_position)

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
        wear the run's limitation. Measured on 500 labelled, difficulty-tagged
        production rows: the dataset pillar reads 98 with "249 examples -
        roughly +/-5pp", and the same dataset scored as an 18-row subset reads 80
        with "8 comparable examples - a wiring check, not a score" - a sentence
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
            "report the run's own resolution separately",
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
            subset_at, skill_text.index("approximate runtime and estimated spend")
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

        # And it must land on ONE action earned by their starting state, with the
        # reason attached. A menu of everything they could do is the same as no
        # recommendation, so the anti-pattern is pinned too.
        self.assertIn(
            "give the one next action their *starting* state earns", skill_text
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
            "rows without expected outputs, or placeholder answers",
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
            "coding assistant perform and record the evidence-backed semantic-coverage review",
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
            "proceed without asking or pausing: run static preflight and then local deterministic calibration",
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
        for text in (skill_text, safety_text, env_text):
            for phrase in (
                "openrouter",
                "gateway",
                "upstream inference provider",
                "fallback",
                "exact recipient set",
            ):
                self.assertIn(phrase, text)
        self.assertIn("every allowed upstream inference provider/route", skill_text)
        self.assertIn("disable fallbacks", safety_text)

    def test_secret_file_is_preserved_and_owner_only_before_entry(self) -> None:
        skill_text = " ".join(SKILL.read_text().casefold().split())
        safety_text = " ".join(
            (SKILL_ROOT / "references" / "run-safety.md").read_text().casefold().split()
        )
        readme_text = " ".join((ROOT / "README.md").read_text().casefold().split())
        for phrase in (
            "preserve existing values",
            "comments",
            "append only missing",
            "0600",
            "before opening",
        ):
            self.assertIn(phrase, skill_text)
            self.assertIn(phrase, safety_text)
        self.assertIn("owner-only local `.env`", readme_text)

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
            "not proof of isolation",
        ):
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
        safety_text = " ".join(
            (SKILL_ROOT / "references" / "run-safety.md").read_text().casefold().split()
        )
        for phrase in (
            "public dataset validator/loader",
            "public no-execution",
            "never recreate sdk binding or callback fallbacks",
        ):
            self.assertIn(phrase, skill_text)
        self.assertIn("never mirror sdk aliases or binding fallbacks", safety_text)

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
            "target is 10-13 visible enhanced rows",
            "max_trials` is a cap rather than an sdk-enforced minimum",
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

        self.assertIn(
            "user's existing baseline/configuration exactly as defined", guide
        )
        self.assertIn(
            "one row is correct when that is what the user actually defined", guide
        )
        self.assertIn("preserve the user's existing baseline", skill)
        self.assertIn("including its original row count", skill)
        self.assertIn("preserve a user-owned baseline space unchanged", safety)
        self.assertIn("its row count exactly; do not expand it to six", sdk)
        self.assertIn("real one-row fixed configuration remains one row", sdk)
        self.assertIn(
            "matched an explicitly approved and disclosed reduced target", skill
        )

    def test_walkthrough_model_ladder_skips_the_flagship(self) -> None:
        """The first run never auto-selects the vendor's newest flagship.

        Selected models ladder down from one step below the flagship, and both
        runs share the identical three-model list: the enhanced run never gets
        a model the baseline did not measure, so a win is attributable to the
        added knobs and the managed search rather than to a quiet model
        upgrade. A user's own flagship choice is preserved exactly, never
        swapped, and the user hears the one-line faster-and-cheaper reason
        before approving.
        """
        skill = " ".join(SKILL.read_text().casefold().split())
        safety = " ".join(RUN_SAFETY.read_text().casefold().split())
        sdk = " ".join(SDK_EXECUTION.read_text().casefold().split())

        for phrase in (
            "one fast low-cost tier, one mid-tier workhorse, and one strong tier",
            "one step below the vendor's newest flagship",
            "do not select the flagship itself",
            "both runs use the same three models",
            "never gets a model the baseline did not measure",
            "never to quietly upgrading the model",
            "refine the swept values around its top rows",
            "sweep only knobs that are real for every model in the space",
            "never remove or replace the user's model choice silently",
            "build the ladder inside one model family",
            "tiers are roles, not hardcoded ids",
        ):
            with self.subTest(document="sdk-execution", phrase=phrase):
                self.assertIn(phrase, sdk)
        for phrase in (
            "never the vendor's newest flagship",
            "faster and cheaper by searching down the ladder",
            "never auto-select the flagship itself",
            "never to a quietly upgraded model",
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
            "never remove or swap the user's model silently",
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
        header_response = SimpleNamespace(
            usage=SimpleNamespace(cost=None),
            _hidden_params={
                "additional_headers": {"llm_provider-x-litellm-response-cost": "0.125"}
            },
        )
        self.assertEqual(helper(header_response), 0.125)
        with self.assertRaisesRegex(RuntimeError, "stop before scaling"):
            helper(SimpleNamespace(usage=SimpleNamespace(cost=None)))
        with self.assertRaisesRegex(RuntimeError, "malformed response-cost metadata"):
            helper(SimpleNamespace(usage=SimpleNamespace(cost="not-a-number")))
        with self.assertRaisesRegex(RuntimeError, "invalid per-response cost"):
            helper(SimpleNamespace(usage=SimpleNamespace(cost=float("nan"))))

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

    def test_customer_portal_experiments_are_retained_and_linked(self) -> None:
        skill_text = " ".join(SKILL.read_text().casefold().split())
        guide_text = " ".join((ROOT / "GUIDE.md").read_text().casefold().split())
        sdk_text = " ".join(SDK_EXECUTION.read_text().casefold().split())

        self.assertIn(
            "retain the customer's baseline and optimization experiments", skill_text
        )
        self.assertIn(
            "never delete portal experiments as automatic teardown", skill_text
        )
        self.assertIn("direct link to every persisted first-run experiment", skill_text)
        self.assertIn("do not delete them as walkthrough cleanup", guide_text)
        self.assertIn("assert baseline_results.cloud_url is not none", sdk_text)
        self.assertIn("assert optimized_results.cloud_url is not none", sdk_text)
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
            "the opening score and the closing recap are the same conversation",
            "shows its full power only once the enhanced run has finished",
            "grows with the readiness score",
            "npx skills add traigent/traigent-skills",
            "restart the session so the new skills load",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_cloud_insight_is_described_as_signals_not_numbers(self) -> None:
        """The backend withholds numeric dataset-quality scores from clients.

        Coarse buckets, counts and curation advice are client-visible; the
        underlying quality/coverage/diversity numbers are not. And the analysis
        is run-scoped, so promising to grade a dataset that has not been run
        would be a second false claim.
        """
        normalized = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "describe those as signals and curation advice, not as numbers",
            "do not promise a numeric dataset-quality score",
            "never imply the platform can grade a dataset that has not been run",
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
            "neither is meaningful under mock mode",
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

        The account is created by redeeming the single-use access link that
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
            "single-use access link",
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
            "those four are exclusive and cover every user",
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

    def test_emailed_code_and_link_are_handled_as_credentials(self) -> None:
        """The code and the link are bearer credentials, not navigation.

        The link authorizes creating the account, so pasting it into chat hands
        that authority to the transcript. Neither it nor the six-digit code is a
        `uk_`-shaped secret, so the existing "never paste or print secrets" rule
        does not visibly cover them and an assistant can ask for them in good
        faith. The guide has to name them.
        """
        normalized = " ".join(RUN_SAFETY.read_text().casefold().split())
        for phrase in (
            "the confirmation code and the access link are credentials",
            "never ask the user to paste either one into chat",
            "never repeat one back",
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
            "do not go looking through the sdk's private storage layout",
            "traigent/traigent issue 2020",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_both_runs_are_reported_with_their_own_link(self) -> None:
        normalized = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "only after that first result is on screen, ask for the traigent key",
            "full access rather than the read-only default",
            "upload the baseline that already ran instead of paying to repeat it",
            "never present one link as though it covered both",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

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
            "it resolves to a local-only intent, so a valid key is bypassed",
            "the pinning rule is therefore per phase, not global",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_enhanced_run_code_block_still_uses_auto(self) -> None:
        """Guard the code itself, not only the prose around it."""
        text = SDK_EXECUTION.read_text()
        enhanced = text[text.index("## Broader optimization") :]
        enhanced = enhanced[: enhanced.index("## Holdout and result checks")]
        self.assertIn('algorithm="auto"', enhanced)
        self.assertNotIn('algorithm="grid"', enhanced)
        self.assertNotIn('algorithm="random"', enhanced)

    def test_absent_cost_is_never_reported_as_zero(self) -> None:
        """A stated $0.00 reads as "this was free", which is a false claim."""
        normalized = " ".join(SDK_EXECUTION.read_text().casefold().split())
        self.assertIn("report cost as not measured", normalized)
        self.assertIn("`total_cost` as absent rather than zero", normalized)

    def test_local_baseline_is_free_of_traigent_not_free_of_spend(self) -> None:
        """The preview needs no Traigent key but still spends real provider money."""
        normalized = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "needs only the user's own provider credential",
            "before any traigent account exists",
            "free of traigent, not free of spend",
            "the same combined approval and the same running total",
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
            "the zero-anchor walkthrough included",
            "this opening score is not skippable",
            "it always reports all three pillars",
            "a required step of local validation, not an optional aid",
            "the score grades measured evidence, not declared existence",
            # the opening score must reach the USER, not merely be computed
            "so the user knows the state they are starting from",
            # a cap phrased for an absent component must not be read aloud at a
            # component that exists but is only unmeasured
            "say so in your own words instead of repeating the card's reason",
            # the two sentences that reconcile a mandatory opening score with the
            # zero-anchor zero-writes ban - without these the doctrine reads as
            # licensing a pre-answer write
            "they authorize no project write",
            "recording it is a write and waits for the answer",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_absent_wiring_is_reported_as_unattested_not_untunable(self) -> None:
        """The `wired` list is an attestation, and the skill must say so.

        A cap that can only be cleared by naming the wired knobs is
        undiagnosable unless the skill says so, and the second phrase is the
        wording the cap reason emits - so the prose and the code drift together
        or not at all. The last phrase is the scoping clause: the same cap id
        fires for the zero-anchor opening, which the flow does proceed through,
        so the restriction cannot be keyed on the id.
        """
        normalized = " ".join(SKILL.read_text().casefold().split())
        for phrase in (
            "declaring a knob is not a statement that the agent consumes it",
            "does not state which of them the agent consumes",
            "an attestation the score takes at its word and never verifies",
            "while a document declares knobs without an attested `wired` list, "
            "do not begin paid optimization",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

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
        # An eighth dataset cap must be routed too, so pin the count rather
        # than spot-checking the seven that exist today.
        self.assertEqual(len(conditions), 7)
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
            "the caps that cleared and the caps that remain",
            "never presented as real-world readiness",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_references_require_the_score_on_the_repair_path(self) -> None:
        def norm(name: str) -> str:
            return " ".join(
                (SKILL_ROOT / "references" / name).read_text().casefold().split()
            )

        evaluation = norm("evaluation-and-dataset.md")
        glossary = norm("glossary.md")
        self.assertIn("the applicable calibration, and the readiness score", evaluation)
        self.assertIn("because a file changed or because the score rose", evaluation)
        self.assertIn(
            "branch on each active cap before continuing", norm("run-safety.md")
        )
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
        enhanced = enhanced[: enhanced.index("## Holdout and result checks")]
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
        enhanced = enhanced[: enhanced.index("## Holdout and result checks")]
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
                    "os": SimpleNamespace(environ={}),
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
        for name, text in documents.items():
            with self.subTest(document=name):
                self.assertIn(
                    "returned trials",
                    text,
                    f"{name} must state that the document is written only once "
                    "the search has returned trials",
                )
                self.assertTrue(
                    any(
                        phrase in text
                        for phrase in (
                            "delete any earlier copy",
                            "remove any earlier document",
                            "deletes it before each search",
                            "unlink",
                        )
                    ),
                    f"{name} must state that an earlier document is removed "
                    "before the search, or a failed retry keeps it",
                )
        self.assertNotIn(
            "serialize it to `traigent-runs/config-space.json`",
            documents["SKILL.md"],
            "SKILL.md must not instruct producing the file before the search",
        )
        skill = documents["SKILL.md"]
        self.assertLess(
            skill.index("serialize it"),
            skill.index("traigent-runs/config-space.json"),
            "SKILL.md must serialize the space first and name the file at the "
            "point it is saved",
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


if __name__ == "__main__":
    unittest.main()

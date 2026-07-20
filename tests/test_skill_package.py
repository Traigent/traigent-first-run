from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "traigent-first-run"
SKILL = SKILL_ROOT / "SKILL.md"


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
            "aggregate remaining-budget ledger",
        ):
            self.assertIn(phrase, contract_text)
        self.assertIn(
            "does not enforce the aggregate walkthrough cap",
            contract_text,
        )
        self.assertIn(
            "never replace it silently",
            safety_text,
        )

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
            "do not claim aliases",
            "inspect the installed binding behavior",
        ):
            self.assertIn(phrase, text)

    def test_run_plan_records_repeatable_calibration_and_ledger(self) -> None:
        text = (SKILL_ROOT / "assets" / "run-plan.md").read_text().casefold()
        for phrase in (
            "input/fixture",
            "expected outcome",
            "rubric/schema branch",
            "chosen thresholds and rationale",
            "human semantic-coverage reviewer",
            "human semantic-coverage verdict",
            "live provider/key check",
            "llm-judge calibration/evaluation",
            "retries/composites",
            "current-configuration holdout",
            "winner holdout",
            "phase worst case",
            "charged or conservative deduction",
            "remaining aggregate cap",
        ):
            self.assertIn(phrase, text)

    def test_sdk_template_defines_prompt_builder(self) -> None:
        text = (SKILL_ROOT / "references" / "sdk-execution.md").read_text()
        self.assertIn("def build_prompt(", text)
        self.assertIn('if style == "direct":', text)
        self.assertIn('if style == "structured":', text)

    def test_sdk_template_bounds_requests_phases_and_retries(self) -> None:
        text = (SKILL_ROOT / "references" / "sdk-execution.md").read_text()
        for phrase in (
            "PROVIDER_REQUEST_TIMEOUT_SECONDS",
            "BASELINE_TIMEOUT_SECONDS",
            "OPTIMIZATION_TIMEOUT_SECONDS",
            "HOLDOUT_PHASE_TIMEOUT_SECONDS",
            "PROVIDER_RETRY_COUNT",
            "not math.isfinite(value) or value <= 0",
            "num_retries=PROVIDER_RETRY_COUNT",
            "timeout=BASELINE_TIMEOUT_SECONDS",
            "timeout=OPTIMIZATION_TIMEOUT_SECONDS",
            "deadline = time.monotonic() + HOLDOUT_PHASE_TIMEOUT_SECONDS",
        ):
            self.assertIn(phrase, text)

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


if __name__ == "__main__":
    unittest.main()

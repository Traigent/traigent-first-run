from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()

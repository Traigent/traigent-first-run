"""Keep the public paste prompt comparable with copies hosted elsewhere."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OnboardingCopyTests(unittest.TestCase):
    def test_the_canonical_prompt_stays_short_and_stable(self) -> None:
        readme = (ROOT / "README.md").read_text()
        section = readme.split("## Start with one prompt\n", 1)[1]
        prompt = re.search(r"```text\n(.*?)\n```", section, re.S).group(1)
        self.assertEqual(
            prompt,
            "Help me run my first Traigent optimization.\n"
            "Clone https://github.com/Traigent/traigent-first-run and follow GUIDE.md.",
        )
        reassurance = section.split("```", 2)[2].split("The assistant performs", 1)[0]
        for phrase in (
            "small and reversible",
            "never hard-coded or printed",
            "explains why there is none",
        ):
            self.assertIn(phrase, reassurance)

    def test_readiness_names_its_free_value_and_the_existing_next_preview(self) -> None:
        skill = (ROOT / "skills" / "traigent-first-run" / "SKILL.md").read_text()
        opening = skill.split("#### Opening readiness gate", 1)[1].split(
            "**Read next.**", 1
        )[0]
        self.assertIn("free and needs no key", opening)
        self.assertIn("next paid step is the priced baseline preview", opening)
        # Stated in the assistant's own voice. It used to read "Per glossary:",
        # and the glossary carries only the "free" half - a citation a reader
        # following it does not find is worse than no citation.
        self.assertNotIn("Per glossary", opening)


if __name__ == "__main__":
    unittest.main()

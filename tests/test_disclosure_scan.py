"""The pre-publish scan's own behaviour, including the half that reports.

`test_skill_package.py` exercises the rules by walking the repository, which
proves they still catch a leak in a tracked file. It never touches the command
line, and the command line is where the rules meet text that is NOT yet
published - a pull-request body, an issue body, a comment.

That path has a failure mode the tracked-file path does not. Naming the matched
string is correct when the string is already in the tree: the message can only
repeat what is in front of the author. It is wrong before publication, because a
report that quotes the token turns a caught leak into a leak. That is not
hypothetical - a disclosure comment written to report three leaked names
reproduced all three while reporting them.

So redaction is the safety-critical half of this tool, and it shipped untested.
These are its tests.
"""

from __future__ import annotations

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import disclosure_scan  # noqa: E402  (needs the path line above)

# A name the structural rules refuse without any digest being involved, so this
# file plants no real one. `Traigent` + CamelCase is the shape the guard reads as
# an internal repository.
INVENTED = "Traigent" + "NotARealRepository"


class RedactionKeepsTheFindingAndDropsTheStringTests(unittest.TestCase):
    """A report about a leak must not be a second copy of it."""

    def setUp(self) -> None:
        findings = disclosure_scan.scan_text(f"See {INVENTED} for details.", "body.md")
        self.assertEqual(len(findings), 1, findings)
        self.finding = findings[0]

    def test_the_named_form_carries_the_string(self) -> None:
        """The tracked-file path is allowed to name it, and must keep doing so.

        Pinned as the counterpart to the test below: if naming ever stopped
        working, the redaction test would still pass and the guard's own failure
        messages would quietly become unactionable.
        """
        self.assertIn(INVENTED, self.finding)

    def test_the_redacted_form_does_not(self) -> None:
        redacted = disclosure_scan.redact(self.finding)
        self.assertNotIn(INVENTED, redacted)
        self.assertNotIn(INVENTED.casefold(), redacted.casefold())

    def test_redaction_keeps_the_location_and_the_reason(self) -> None:
        """Dropping the string must not drop what makes the finding actionable.

        A report that says only "something leaked" sends the author back to
        guess, and guessing means pasting candidates somewhere to test them.
        """
        redacted = disclosure_scan.redact(self.finding)
        self.assertIn("body.md", redacted)
        self.assertIn("non-public repository", redacted)
        self.assertIn("public_repos", redacted)

    def test_only_the_matched_string_is_replaced(self) -> None:
        """The trailing guidance names identifiers that are not secret.

        `public_repos` and `non_repository_hyphenated_terms` are the actionable
        part, so a blanket quote-stripper would take the wrong half.
        """
        redacted = disclosure_scan.redact(self.finding)
        self.assertEqual(redacted.count(disclosure_scan.REDACTED), 1)

    def test_a_finding_with_no_quoted_string_survives_intact(self) -> None:
        """The UUID finding names no token; redaction must leave it alone."""
        findings = disclosure_scan.scan_text(
            "Session 3f2504e0-4f89-11d3-9a0c-0305e82c3301 ran it.", "body.md"
        )
        self.assertEqual(len(findings), 1, findings)
        self.assertEqual(disclosure_scan.redact(findings[0]), findings[0])


class TheCommandLineDefaultsToRedactedTests(unittest.TestCase):
    """The default matters more than the flag: it is what gets typed."""

    def _run(self, text: str, *args: str) -> tuple[int, str]:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "disclosure_scan.py"),
                "--stdin",
                *args,
            ],
            input=text,
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.returncode, completed.stdout + completed.stderr

    def test_a_leak_is_reported_without_naming_it(self) -> None:
        code, output = self._run(f"See {INVENTED} for details.")
        self.assertEqual(code, 1)
        self.assertNotIn(INVENTED, output)
        self.assertIn("do not publish", output)

    def test_naming_is_opt_in_and_does_name(self) -> None:
        """Correct for text already public; never the default."""
        code, output = self._run(f"See {INVENTED} for details.", "--name-matches")
        self.assertEqual(code, 1)
        self.assertIn(INVENTED, output)

    def test_clean_text_passes(self) -> None:
        code, output = self._run("Nothing internal is named here.\n")
        self.assertEqual(code, 0)
        self.assertIn("PASS", output)

    def test_unreadable_input_is_not_a_pass(self) -> None:
        """Exit 2, never 0. A scan that read nothing has decided nothing.

        The trap this guards is a caller writing `scan || publish`: with a
        could-not-read collapsed into success, an unreadable path publishes.
        """
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "disclosure_scan.py"),
                str(ROOT / "does-not-exist.md"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertNotIn("PASS", completed.stdout)

    def test_it_refuses_two_input_sources_rather_than_choosing(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "disclosure_scan.py"),
                "--stdin",
                str(ROOT / "README.md"),
            ],
            input="",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)


class TheModuleDoesNotLeakThroughItsOwnRulesTests(unittest.TestCase):
    """It stores digests, not names, and it is a tracked file like any other."""

    def test_scanning_its_own_source_is_clean(self) -> None:
        source = (ROOT / "tools" / "disclosure_scan.py").read_text(encoding="utf-8")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            findings = disclosure_scan.scan_text(source, "disclosure_scan.py")
        self.assertEqual(findings, [])

    def test_the_digest_set_is_not_empty(self) -> None:
        """A scan that silently lost its denylist reports clean on everything.

        The lengths matter as much as the digests: without them there is no
        window to hash, so an empty tuple disables the whole token rule while
        every structural rule keeps passing.
        """
        self.assertTrue(disclosure_scan.forbidden_digests)
        self.assertTrue(disclosure_scan.forbidden_lengths)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

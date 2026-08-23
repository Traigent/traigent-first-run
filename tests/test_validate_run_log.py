"""What the run-log validator refuses, and what it must not refuse.

The log's rules were prose for one revision, and prose is what this repository
keeps rediscovering it cannot enforce: the closed vocabularies, the allowlist on
`detail`, and the append-only sequence are all executed by an assistant and
checked by nothing. So every rule that document states has a case here, and
every case is written as the line an assistant would plausibly produce rather
than as a synthetic counterexample.

The second half matters as much as the first. A checker that refuses valid
input teaches people to write around it, so the accepting cases below are the
sentences a careful run really does produce - a script name, an exit code, a
short quoted class, a bare stage number.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "traigent-first-run" / "scripts" / "validate_run_log.py"

sys.path.insert(0, str(SCRIPT.parent))

import validate_run_log  # noqa: E402


def line(**overrides: object) -> dict[str, object]:
    """A well-formed line, with the field under test replaced."""
    record: dict[str, object] = {
        "ts": "20260823T151204Z",
        "event": "blocked",
        "stage": 6,
        "class": "key",
        "state": "open",
        "detail": "waiting on a full-access portal key before the connected run",
    }
    record.update(overrides)
    return record


def findings(*records: dict[str, object]) -> list[str]:
    text = "\n".join(json.dumps(record) for record in records) + "\n"
    return [finding.problem for finding in validate_run_log.validate(text)]


class TheClosedVocabulariesAreEnforcedTests(unittest.TestCase):
    """A misspelled class used to land silently in a support artifact."""

    def test_a_class_outside_its_event_set_is_refused(self) -> None:
        problems = findings(line(**{"class": "credential"}))
        self.assertEqual(len(problems), 1)
        self.assertIn("outside its closed set", problems[0])

    def test_every_event_accepts_every_value_its_own_set_declares(self) -> None:
        for event, values in validate_run_log.CLASSES.items():
            for value in values:
                with self.subTest(event=event, value=value):
                    self.assertEqual(
                        findings(line(event=event, **{"class": value})), []
                    )

    def test_tool_fail_closes_over_exit_codes_rather_than_a_list(self) -> None:
        self.assertEqual(findings(line(event="tool_fail", **{"class": "3"})), [])
        problems = findings(line(event="tool_fail", **{"class": "readiness"}))
        self.assertEqual(len(problems), 1)
        self.assertIn("not an exit code", problems[0])

    def test_an_invented_event_is_refused_by_name(self) -> None:
        problems = findings(line(event="oops"))
        self.assertTrue(any("not one of the six" in problem for problem in problems))

    def test_the_field_set_is_closed_in_both_directions(self) -> None:
        record = line()
        record.pop("detail")
        self.assertTrue(any("missing field" in p for p in findings(record)))
        self.assertTrue(any("unknown field" in p for p in findings(line(extra=1))))


class TheAllowlistOnDetailIsCheckedTests(unittest.TestCase):
    """The privacy promise, which is the one that must not be prose.

    This runs on a customer's real project and the file is written to be handed
    to somebody else, so each carrier here is one a plausible sentence really
    does pick up: the guide's own habit is to print absolute paths and write
    session ids, which are right where they are and wrong in this file.
    """

    def test_each_carrier_is_named(self) -> None:
        cases = {
            "an absolute path": "the .env at /home/jsmith/proj/.env is tracked",
            "a credential": "the portal refused key uk_9fA2bQ7xLmZ0rTdEuv",
            "an email address": "the account anna.k@example.com has no plan",
            "a session or request id": (
                # Assembled rather than written out: this repository's guard
                # refuses a bare UUID in a tracked file, and it is right to -
                # every one that has ever shipped was a real identifier.
                "tracking dropped for "
                + "-".join(("7f3a91c2", "11de", "4d0b", "9a77", "2b6e4c5d8e01"))
            ),
            "a URL": "the probe failed against https://portal.example.com/api",
            "quoted content": (
                'the judge returned "the capital of France is Paris, and also"'
            ),
        }
        for carrier, detail in cases.items():
            with self.subTest(carrier=carrier):
                problems = findings(line(detail=detail))
                self.assertTrue(
                    any(carrier in problem for problem in problems),
                    f"{detail!r} was not refused for {carrier}",
                )

    def test_an_empty_detail_is_refused(self) -> None:
        self.assertTrue(any("empty" in p for p in findings(line(detail="   "))))

    def test_the_sentences_a_careful_run_writes_are_accepted(self) -> None:
        """The false-red side: a gate that refuses valid input teaches evasion."""
        for detail in (
            "waiting on a full-access portal key before the connected run",
            "readiness.py exited 3, so nothing was scored",
            "the credential file is tracked by git, so no key was requested",
            "the provider refused for quota, and no trial ran",
            "tracking degraded to local-only and paid work stopped",
            "a trial was refused as truncated and did not reach the comparison",
            "the evaluator could not be contained, so it was not executed",
            "the dataset cap 'below-measurable-size' is still standing",
        ):
            with self.subTest(detail=detail):
                self.assertEqual(findings(line(detail=detail)), [])


class TheAppendOnlySequenceIsCheckedTests(unittest.TestCase):
    """`open` then `cleared`, and nothing that changed nothing."""

    def test_cleared_without_an_open_before_it_is_refused(self) -> None:
        problems = findings(line(state="cleared"))
        self.assertTrue(any("without an open line" in p for p in problems))

    def test_a_repeat_of_a_standing_state_is_refused(self) -> None:
        problems = findings(line(), line(ts="20260823T151205Z"))
        self.assertTrue(any("already open" in p for p in problems))

    def test_open_then_cleared_holds(self) -> None:
        self.assertEqual(
            findings(line(), line(ts="20260823T151205Z", state="cleared")), []
        )

    def test_a_recurrence_after_clearing_holds(self) -> None:
        """Collapsing a retry storm must not also collapse a flap."""
        self.assertEqual(
            findings(
                line(),
                line(ts="20260823T151205Z", state="cleared"),
                line(ts="20260823T151206Z"),
            ),
            [],
        )

    def test_two_identities_do_not_share_a_sequence(self) -> None:
        self.assertEqual(findings(line(), line(ts="20260823T151205Z", stage=7)), [])


class TheScriptItselfBehavesTests(unittest.TestCase):
    """Exit codes are how the guide routes this, so they are part of the API."""

    def _run(self, text: str, *extra: str) -> subprocess.CompletedProcess[str]:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "run-log.jsonl"
            log.write_text(text, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(SCRIPT), "--log", str(log), *extra],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_a_clean_log_exits_zero(self) -> None:
        result = self._run(json.dumps(line()) + "\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("every line holds", result.stdout)

    def test_a_rejected_line_exits_one_and_is_locatable(self) -> None:
        result = self._run(json.dumps(line(**{"class": "nope"})) + "\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("line 1", result.stdout)

    def test_an_unreadable_log_exits_two_rather_than_reporting_findings(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--log", str(ROOT / "no-such-file.jsonl")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot be read", result.stderr)

    def test_a_line_that_is_not_json_is_one_finding_not_a_crash(self) -> None:
        """A malformed line is a finding about the log, never a stack trace."""
        result = self._run("{not json\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not JSON", result.stdout)

    def test_blank_lines_are_not_findings(self) -> None:
        self.assertEqual(self._run("\n\n").returncode, 0)

    def test_json_output_carries_the_same_verdict(self) -> None:
        result = self._run(json.dumps(line(**{"class": "nope"})) + "\n", "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(len(payload["findings"]), 1)

    def test_it_never_writes_to_the_log(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "run-log.jsonl"
            text = json.dumps(line(**{"class": "nope"})) + "\n"
            log.write_text(text, encoding="utf-8")
            subprocess.run(
                [sys.executable, str(SCRIPT), "--log", str(log)],
                capture_output=True,
                check=False,
            )
            self.assertEqual(log.read_text(encoding="utf-8"), text)


class TheGuidanceRoutesToItTests(unittest.TestCase):
    """A shipped checker nothing invokes is the defect it was written against."""

    def test_the_reference_names_the_script_and_its_exit_codes(self) -> None:
        text = " ".join(
            (ROOT / "skills" / "traigent-first-run" / "references" / "run-safety.md")
            .read_text()
            .casefold()
            .split()
        )
        self.assertIn("scripts/validate_run_log.py --log", text)
        self.assertIn("exit 1 names the lines", text)
        self.assertIn("exit 3 means the check itself could not run", text)

    def test_a_rejected_line_is_reported_rather_than_rewritten(self) -> None:
        """Append-only survives its own checker.

        A draft let this check rewrite the line it refused, which ends the
        unqualified append-only claim the whole design rests on - and it would
        have been the assistant editing history to tidy up after itself. The
        line is named to the user instead, and the directory is theirs.
        """
        text = " ".join(
            (ROOT / "skills" / "traigent-first-run" / "references" / "run-safety.md")
            .read_text()
            .casefold()
            .split()
        )
        self.assertIn("is not rewritten", text)
        self.assertNotIn("may rewrite a line", text)
        self.assertIn("theirs to delete", text)


if __name__ == "__main__":
    unittest.main()

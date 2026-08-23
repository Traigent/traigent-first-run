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
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "traigent-first-run" / "scripts" / "validate_run_log.py"
BASE_REFERENCE = ROOT / "skills" / "traigent-first-run" / "references" / "run-safety.md"

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

    def test_a_repeat_of_a_standing_state_is_accepted(self) -> None:
        """The one check that refused correct input, and why it went.

        Nothing on disk distinguishes a same-session retry - which the guide
        says writes no line - from a resumed session re-opening what it can no
        longer remember, which the guide explicitly licenses. Refusing both
        would have failed a correct run at the close, and collapsing on the
        identity answers the same either way. Deduplication stays guidance.
        """
        self.assertEqual(findings(line(), line(ts="20260823T151205Z")), [])

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


class TheFieldsWithNoNegativeCoverageTests(unittest.TestCase):
    """`ts`, `stage`, `state` and the record shape had none at all.

    A mutation sweep put a number on it: fifteen single edits that each broke a
    real rule stayed green, because every rule had exactly one representative
    example and no boundary. Deleting the timestamp check, widening the stage
    range, adding a third state, and accepting a non-object line were four of
    them. One example per rule proves the rule was written, not that it holds.
    """

    def test_a_timestamp_that_is_not_the_stamp_format_is_refused(self) -> None:
        for bad in ("nope", "2026-08-23T15:12:04Z", "20260823T151204", "", "20260823"):
            with self.subTest(ts=bad):
                self.assertTrue(
                    any("YYYYMMDDTHHMMSSZ" in p for p in findings(line(ts=bad)))
                )

    def test_the_stamp_the_guide_writes_is_accepted(self) -> None:
        self.assertEqual(findings(line(ts="20261231T235959Z")), [])

    def test_a_stage_outside_the_records_own_numbering_is_refused(self) -> None:
        for bad in (0, 9, 99, -1, "6", 6.5, True, None):
            with self.subTest(stage=bad):
                self.assertTrue(
                    any(
                        "not a run-record stage" in p for p in findings(line(stage=bad))
                    ),
                    f"stage {bad!r} was accepted",
                )

    def test_every_stage_the_record_has_is_accepted(self) -> None:
        for stage in range(1, 9):
            with self.subTest(stage=stage):
                self.assertEqual(findings(line(stage=stage)), [])

    def test_a_third_state_is_refused(self) -> None:
        for bad in ("closed", "OPEN", "", 1, None):
            with self.subTest(state=bad):
                self.assertTrue(
                    any(
                        "neither open nor cleared" in p
                        for p in findings(line(state=bad))
                    ),
                    f"state {bad!r} was accepted",
                )

    def test_a_line_that_is_not_an_object_is_a_finding(self) -> None:
        import json as _json

        text = _json.dumps([1, 2, 3]) + "\n"
        problems = [f.problem for f in validate_run_log.validate(text)]
        self.assertTrue(any("not a JSON object" in p for p in problems))

    def test_an_unhashable_value_is_a_finding_and_never_an_exception(self) -> None:
        """Exit 3 is reserved for the check breaking, not for a bad line.

        `value in frozenset` raises TypeError on a list or a dict, which the
        blanket handler turned into exit 3 - and the guide routes exit 3 as a
        tool failure, so the run would have logged a complaint about its own
        checker instead of showing the user the line.
        """
        for field in ("class", "event", "state"):
            for bad in ([1], {"a": 1}):
                with self.subTest(field=field, value=bad):
                    problems = findings(line(**{field: bad}))
                    self.assertTrue(problems, f"{field}={bad!r} produced no finding")

    def test_an_exit_code_outside_1_to_255_is_refused(self) -> None:
        for bad in ("0", "256", "999", "-1", 3):
            with self.subTest(code=bad):
                self.assertTrue(
                    any(
                        "not an exit code" in p
                        for p in findings(line(event="tool_fail", **{"class": bad}))
                    ),
                    f"exit code {bad!r} was accepted",
                )
        self.assertEqual(findings(line(event="tool_fail", **{"class": "255"})), [])


class ThePatternsThatRefusedGoodEnglishTests(unittest.TestCase):
    """The expensive direction, measured rather than assumed.

    Keying quoted content on an opening quote alone made every possessive
    apostrophe a finding, and this check runs at the close, so a correct log
    would have shown the customer a rejection. The accepting cases here are
    the sentences a run really writes.
    """

    def test_a_possessive_is_not_quoted_content(self) -> None:
        for detail in (
            "the provider's quota was exhausted and no trial ran",
            "the model's answer arrived truncated and the trial was refused",
            "the run couldn't reach the portal and stopped before paying",
            "the dataset cap 'below-measurable-size' is still standing",
        ):
            with self.subTest(detail=detail):
                self.assertEqual(findings(line(detail=detail)), [])

    def test_a_matched_quoted_span_is_still_refused(self) -> None:
        problems = findings(
            line(detail='the judge returned "the capital of France is Paris and also"')
        )
        self.assertTrue(any("quoted content" in p for p in problems))

    def test_a_decorator_is_not_an_email_address(self) -> None:
        self.assertEqual(
            findings(line(detail="the agent uses the @traigent.optimize decorator")), []
        )

    def test_a_long_token_does_not_hang_the_scanner(self) -> None:
        """An unbounded email pattern backtracked for 78 seconds on 256KB.

        The trigger is exactly what the rule targets - a pasted error body or a
        base64 blob - and it ran on the last step before the close.
        """
        import time

        start = time.monotonic()
        problems = findings(line(detail="x" * 250_000))
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertTrue(any("past the" in p for p in problems))

    def test_every_alternative_inside_a_pattern_has_its_own_example(self) -> None:
        """One example per rule leaves every other branch of it untested.

        A sweep confirmed it: narrowing the session-id threshold, deleting the
        `~/` branch and dropping `http://` each stayed green, because the one
        fixture per carrier happened to exercise a different alternative.
        """
        cases = {
            "a session or request id": (
                "the request " + "a3f91c2b11de4d0b" + " was rejected",
            ),
            "an absolute path": (
                "the credential file ~/proj/.env is tracked by git",
                "the file /home/user/proj/.env is tracked by git",
            ),
            "a URL": (
                "the probe failed against http://portal.example.com/api",
                "the probe failed against https://portal.example.com/api",
            ),
        }
        for carrier, details in cases.items():
            for detail in details:
                with self.subTest(carrier=carrier, detail=detail):
                    self.assertTrue(
                        any(carrier in p for p in findings(line(detail=detail))),
                        f"{detail!r} was not refused for {carrier}",
                    )

    def test_the_carriers_added_after_review_are_caught(self) -> None:
        for carrier, detail in {
            "an absolute path": "the file C:\\Users\\jsmith\\proj\\.env is tracked",
            "a host or address": "the probe could not reach 203.0.113.42 at all",
        }.items():
            with self.subTest(carrier=carrier):
                self.assertTrue(
                    any(carrier in p for p in findings(line(detail=detail))),
                    f"{detail!r} was not refused",
                )


class TheProseAndTheScriptDeclareOneVocabularyTests(unittest.TestCase):
    """They diverged once, and the divergence was customer-visible.

    `uncategorized` was argued for in `run-safety.md` and recorded as shipped
    in the budget entry while the script still refused it, so a completed run
    reporting no lift - a case SKILL.md stage 8 has a whole clause for - would
    have written a line its own checker rejected, and the close would have
    shown the customer `1 line(s) rejected`. Nothing compared the two, because
    one test read the prose and another read the code.
    """

    def _bullets(self) -> dict[str, str]:
        text = BASE_REFERENCE.read_text().split("### The run log", 1)[1]
        bullets: dict[str, str] = {}
        current = None
        for row in text.splitlines():
            opener = re.match(r"- `([a-z_]+)` - ", row)
            if opener:
                current = opener.group(1)
                bullets[current] = row
            elif current and row.startswith("  "):
                bullets[current] += " " + row.strip()
            elif current and not row.strip():
                current = None
        return bullets

    def test_every_event_the_script_closes_over_is_declared_in_the_prose(
        self,
    ) -> None:
        bullets = self._bullets()
        self.assertEqual(set(bullets), validate_run_log.EVENTS)

    def test_each_events_value_set_is_identical_in_both(self) -> None:
        bullets = self._bullets()
        for event, allowed in validate_run_log.CLASSES.items():
            declared = set(re.findall(r"`([a-z][a-z-]*)`", bullets[event]))
            # The bullet also names the event itself and, for `run_stop`, the
            # composed key it points at; the vocabulary is what remains.
            declared -= {event} | validate_run_log.EVENTS
            with self.subTest(event=event):
                self.assertEqual(
                    declared & allowed,
                    allowed,
                    f"{event}: the prose does not declare {sorted(allowed - declared)}",
                )
                self.assertEqual(
                    declared - allowed,
                    set(),
                    f"{event}: the prose declares {sorted(declared - allowed)}, "
                    "which the script refuses",
                )


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

    def test_the_internal_error_path_exits_three_and_says_whose_fault_it_is(
        self,
    ) -> None:
        """Exit 3 is in the contract and was never once executed by a test.

        The guide routes it as "the check could not run, which is never a
        finding about the log", so the number and the sentence are both part of
        the API - and a mutation lowering it to 1 stayed green.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / "boom.py"
            harness.write_text(
                "import sys\n"
                f"sys.path.insert(0, {str(SCRIPT.parent)!r})\n"
                "import validate_run_log\n"
                "validate_run_log.run = lambda *a, **k: (_ for _ in ()).throw("
                "RuntimeError('probe'))\n"
                "sys.exit(validate_run_log.main())\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(harness)], capture_output=True, text=True
            )
        self.assertEqual(result.returncode, 3)
        self.assertIn("validate_run_log.py", result.stderr)
        self.assertIn("defect in the check rather than in your project", result.stderr)
        # The stack stays behind the switch the sibling scripts already use.
        self.assertNotIn("Traceback", result.stderr)

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
        self.assertIn("append-only is what makes this file worth reading", text)


if __name__ == "__main__":
    unittest.main()

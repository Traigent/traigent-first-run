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


def remedies_for(text: str) -> list[tuple[str, str]]:
    """Every finding in raw log text, as (problem, remedy).

    Takes text rather than records because two of the branches under test are
    reached only by a line that is not a JSON object at all, which no dict can
    express.
    """
    return [(f.problem, f.remedy) for f in validate_run_log.validate(text)]


class TheClosedVocabulariesAreEnforcedTests(unittest.TestCase):
    """A misspelled class used to land silently in a support artifact."""

    def test_the_closed_sets_are_closed_against_literals_not_each_other(
        self,
    ) -> None:
        """Widening both homes together left every test green.

        The prose and the script are compared to one another, so a coordinated
        edit - an eighteenth `stopped` class added to both - passed. A set
        checked only against its own mirror is not closed; these literals are
        the mirror's mirror, and an intentional addition edits them on purpose.
        """
        self.assertEqual(
            validate_run_log.CLASSES["blocked"],
            frozenset({"approval", "key", "answer"}),
        )
        self.assertEqual(
            validate_run_log.CLASSES["stopped"],
            frozenset(
                {
                    "credential-file-tracked",
                    "ignore-check",
                    "containment",
                    "readiness-cap",
                    "invariants",
                    "tool",
                    "authentication",
                    "key-scope",
                    "account-access",
                    "quota",
                    "rate",
                    "validation",
                    "timeout",
                    "cost-ceiling",
                    "outage",
                    "persistence",
                    "uncategorized",
                }
            ),
        )
        self.assertEqual(
            validate_run_log.CLASSES["warning"],
            frozenset(
                {"refused-trial", "untracked-cost", "cap-standing", "uncategorized"}
            ),
        )
        self.assertEqual(validate_run_log.EVENTS, frozenset(validate_run_log.CLASSES))
        self.assertEqual(validate_run_log.STATES, frozenset({"open", "cleared"}))
        self.assertEqual(
            validate_run_log.FIELDS,
            frozenset({"ts", "event", "stage", "class", "state", "detail"}),
        )

    def test_the_allowlist_covers_the_whole_detail_at_any_length(self) -> None:
        """Two mutants skipped the scan, by length and by offset.

        A short `detail` and a carrier past the hundredth character were both
        accepted, because every fixture happened to be mid-length and put its
        carrier early.
        """
        self.assertTrue(findings(line(detail="stopped at ~/.env")))
        long_prose = "the run stopped after a long stretch of ordinary prose " * 2
        self.assertTrue(
            findings(line(detail=long_prose + "at https://portal.example.com/api"))
        )

    def test_a_class_outside_its_event_set_is_refused(self) -> None:
        problems = findings(line(**{"class": "credential"}))
        self.assertEqual(len(problems), 1)
        self.assertIn("outside its closed set", problems[0])

    def test_every_event_closes_its_set_not_only_the_first_one(self) -> None:
        """The fixture defaults to `blocked`, so the other two were untested.

        Opening `stopped` to any string left both suites green - and `stopped`
        is where seventeen of the twenty-four pairs live.
        """
        for event, invented in (
            ("stopped", "readiness"),
            ("warning", "tool"),
            ("blocked", "timeout"),
        ):
            with self.subTest(event=event):
                problems = findings(line(event=event, **{"class": invented}))
                self.assertTrue(problems, f"{event}:{invented} was accepted")
                self.assertIn("outside its closed set", problems[0])

    def test_no_event_carries_a_class_that_belongs_to_another(self) -> None:
        """A closed set that can grow is not closed."""
        for event, allowed in validate_run_log.CLASSES.items():
            others = set().union(
                *(v for k, v in validate_run_log.CLASSES.items() if k != event)
            )
            for stray in sorted(others - allowed):
                with self.subTest(event=event, stray=stray):
                    self.assertTrue(
                        findings(line(event=event, **{"class": stray})),
                        f"{event} accepted {stray}",
                    )

    def test_every_event_accepts_every_value_its_own_set_declares(self) -> None:
        for event, values in validate_run_log.CLASSES.items():
            for value in values:
                with self.subTest(event=event, value=value):
                    self.assertEqual(
                        findings(line(event=event, **{"class": value})), []
                    )

    def test_an_invented_event_is_refused_by_name(self) -> None:
        problems = findings(line(event="oops"))
        self.assertTrue(
            any("not one this log carries" in problem for problem in problems)
        )

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


class EveryAlternativeOfEveryPatternIsExercisedTests(unittest.TestCase):
    """One example per rule is one alternative per rule.

    A sweep put a number on it: deleting the bare-host branch, the alphanumeric
    session-id branch, three credential prefixes and both curly-quote forms each
    left the suite green, because the single fixture for that carrier happened
    to exercise a different alternative. These run against the compiled
    patterns rather than through `detail`, because the length bound short-
    circuits before the patterns do - which is also why the email bound needs
    its own case here.
    """

    def _pattern(self, label: str):
        for name, pattern in validate_run_log.LEAKS:
            if name == label:
                return pattern
        raise AssertionError(f"no pattern named {label}")

    def test_each_credential_prefix_is_refused(self) -> None:
        for prefix in (
            "sk-ant-",
            "sk-",
            "sk_",
            "uk_",
            "ghp_",
            "gho_",
            "ghu_",
            "ghs_",
            "github_pat_",
            "xoxb-",
            "AKIA",
            "eyJ",
        ):
            # The pattern wants 8+ of `[A-Za-z0-9_-]` after the prefix, and
            # nothing here should read as entropy to a person or a scanner.
            token = prefix + "EXAMPLE-NOT-A-KEY"
            with self.subTest(prefix=prefix):
                self.assertTrue(self._pattern("a credential").search(token), token)

    def test_both_branches_of_the_host_rule(self) -> None:
        pattern = self._pattern("a host or address")
        # RFC 5737 TEST-NET-3 and RFC 2606 example domains.
        self.assertTrue(pattern.search("could not reach 203.0.113.42 at all"))
        self.assertTrue(pattern.search("could not reach portal.example.com at all"))

    def test_a_host_whose_first_label_starts_with_a_digit(self) -> None:
        """Requiring the letter FIRST made real hosts unreachable.

        There is no word boundary inside `1password`, so a label that opens
        with a digit could never be the leftmost match. A label needs a letter
        somewhere, not at its head - and `1.0.dev` still has none.
        """
        pattern = self._pattern("a host or address")
        for host in ("1password.com", "3m.com", "0auth.dev", "9to5mac.com"):
            with self.subTest(host=host):
                self.assertTrue(pattern.search(f"could not reach {host} at all"), host)
        # PEP 440 pre-release-plus-dev pins, which a guide about pinning an SDK
        # writes about constantly: a label after digit-then-dot is a version.
        for version in ("1.0.dev", "1.0.0rc1.dev", "2.1.0b3.dev", "0.9.0a2.dev"):
            with self.subTest(version=version):
                self.assertEqual(
                    findings(
                        line(detail=f"the pinned httpx version {version} was refused")
                    ),
                    [],
                    version,
                )

    def test_the_identifier_shapes_that_are_settled_and_the_one_that_is_not(
        self,
    ) -> None:
        """Case separates an id from a class name; digit position never did.

        Two rounds moved the digit boundary and each traded one error for
        another - the second refused eight of thirteen realistic class names,
        `AzureOpenAIGpt4Error` among them, to catch tokens the single-case
        branch catches anyway. The mixed-case token is the residual, and the
        docstring states it rather than the checker pretending otherwise.
        """
        for identifier in (
            "1A2B3C4DEFGHIJKLMNOPQRST",
            "20260823abcdefghijklm",
            "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "a3f91c2b11de4d0b",
        ):
            with self.subTest(settled=identifier):
                self.assertTrue(
                    findings(line(detail=f"the request {identifier} was rejected")),
                    f"{identifier} was accepted",
                )
        for class_name in (
            "AzureOpenAIGpt4Error",
            "ChatGpt4TurboUnavailableError",
            "AnthropicClaude3OverloadedError",
            "BedrockClaude35SonnetError",
        ):
            with self.subTest(class_name=class_name):
                self.assertEqual(
                    findings(
                        line(detail=f"the provider raised {class_name} and stopped")
                    ),
                    [],
                    class_name,
                )
        # The residual, pinned so it is a decision rather than a surprise.
        self.assertEqual(
            findings(line(detail="the request a1b2c3d4EFGHIJKLMNOPQRSTUVWX failed")), []
        )
        self.assertIn(
            "a mixed-case token escapes",
            " ".join(SCRIPT.read_text().casefold().split()),
        )

    def test_both_branches_of_the_session_id_rule(self) -> None:
        pattern = self._pattern("a session or request id")
        self.assertTrue(pattern.search("request a3f91c2b11de4d0b failed"))
        self.assertTrue(pattern.search("request 01ARZ3NDEKTSV4RRFFQ69G5FAV failed"))
        # A class name is letters only, and naming one is how an uncategorised
        # provider refusal gets written.
        self.assertIsNone(pattern.search("returned a ServiceUnavailableError"))

    def test_both_straight_quote_forms(self) -> None:
        """The double form is refused through `detail`; the single had no case.

        A model answer arrives in whichever quote the assistant reached for, so
        deleting the single-quote alternative left both suites green.
        """
        pattern = self._pattern("quoted content")
        self.assertTrue(
            pattern.search('the judge returned "the capital of France is Paris"')
        )
        self.assertTrue(
            pattern.search("the judge returned 'the capital of France is Paris'")
        )

    def test_both_curly_quote_forms(self) -> None:
        pattern = self._pattern("quoted content")
        self.assertTrue(pattern.search("it said \u201c" + "a" * 30 + "\u201d"))
        self.assertTrue(pattern.search("it said \u2018" + "a" * 30 + "\u2019"))

    def test_both_url_schemes(self) -> None:
        pattern = self._pattern("a URL")
        self.assertTrue(pattern.search("against http://portal.example.com/api"))
        self.assertTrue(pattern.search("against https://portal.example.com/api"))

    def test_each_absolute_path_branch(self) -> None:
        pattern = self._pattern("an absolute path")
        for path in (
            "/home/user/proj/.env",
            "~/proj/.env",
            "~/.env",
            "C:\\Users\\proj",
        ):
            with self.subTest(path=path):
                self.assertTrue(pattern.search(f"the file {path} is tracked"), path)

    def test_the_email_pattern_is_bounded_on_its_own(self) -> None:
        """The length bound short-circuits before this ever runs through `detail`.

        Unbounded, this backtracked quadratically on a long token with no `@`
        in it, so the bound is what keeps the check fast on the input the rule
        exists to catch. Measured here against the pattern directly.
        """
        import time

        pattern = self._pattern("an email address")
        start = time.monotonic()
        self.assertIsNone(pattern.search("x" * 200_000))
        self.assertLess(time.monotonic() - start, 1.0)

    def test_the_detail_bound_admits_a_long_sentence(self) -> None:
        """The false-red side of the bound: it refuses a paste, not a sentence."""
        sentence = "the connected optimization stopped early " * 8
        self.assertLess(len(sentence), validate_run_log.DETAIL_LIMIT)
        self.assertEqual(findings(line(detail=sentence)), [])


class TheRegisterAProviderRefusalIsWrittenInTests(unittest.TestCase):
    """The sentences a run really writes about a refusal it cannot categorise.

    Naming the provider's error class is exactly what the contract asks for
    when the refusal is `uncategorized`, and three separate rules have refused
    that sentence across as many rounds: an opening apostrophe, a paired one,
    and a twenty-letter run. Vendor prefixes front-load their digits, which is
    what tells `OAuth2AuthenticationError` from an identifier.
    """

    def test_a_class_name_carrying_a_vendor_digit_is_not_an_identifier(self) -> None:
        for name in (
            "OAuth2AuthenticationError",
            "Sha256SignatureMismatch",
            "Base64DecodePayloadError",
            "Http2StreamClosedError",
            "Utf8DecodeFailureError",
            "Md5ChecksumMismatchError",
            "Iso8601TimestampError",
            "X509CertificateError",
            "Tls13HandshakeFailure",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    findings(
                        line(detail=f"the refusal was a {name} on the first trial")
                    ),
                    [],
                    f"{name} was refused",
                )

    def test_an_identifier_that_scatters_its_digits_is_still_refused(self) -> None:
        # Named `identifier` rather than `token`: these are request and session
        # id shapes, and the narrower word is both truer and what a secret
        # scanner reads as a credential assignment. Mixed-case shapes are the
        # documented residual and are covered by the settled/unsettled test.
        for identifier in (
            "a3f91c2b11de4d0b",
            "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        ):
            with self.subTest(identifier=identifier):
                self.assertTrue(
                    findings(line(detail=f"the request {identifier} was rejected")),
                    f"{identifier} was accepted",
                )

    def test_a_possessive_on_a_token_ending_in_a_digit(self) -> None:
        """A model id or a version ends in a digit, and the bound missed those."""
        for detail in (
            "gpt-4's refusal arrived before the rows' totals were counted",
            "python 3.12's resolver refused and the customers' rows were dropped",
            "the o1's answer was truncated before the evaluators' checks ran",
        ):
            with self.subTest(detail=detail):
                self.assertEqual(findings(line(detail=detail)), [])

    def test_two_short_quoted_terms_do_not_pair_across_the_gap(self) -> None:
        """The closing quote of one term paired with the opener of the next."""
        self.assertEqual(
            findings(
                line(detail='the "open" line arrived before the "cleared" line did')
            ),
            [],
        )

    def test_a_version_is_not_a_host(self) -> None:
        self.assertEqual(
            findings(line(detail="the pinned httpx version 1.0.dev was refused")), []
        )

    def test_a_carrier_after_punctuation_is_still_refused(self) -> None:
        """A boundary class misses every carrier that is not a space or a quote.

        The guide's own register prints paths in backticks and addresses in
        parentheses, so both were invisible to the check written for them.
        """
        for detail in (
            "the file `/home/user/clients/rows.csv` was missing",
            # A host whose TLD is outside the host rule's list, so only the
            # address rule can catch it - otherwise the lookbehind is untested
            # and reverting it stays green.
            "the account (anna.k@acme-health.co.uk) was refused",
            "the account <anna.k@acme-health.co.uk> was refused",
            "the account: anna.k@acme-health.co.uk was refused",
            "path=/home/user/proj/.env was tracked",
        ):
            with self.subTest(detail=detail):
                self.assertTrue(findings(line(detail=detail)), f"{detail!r} passed")


class TheSurvivorsOfTheSweepTests(unittest.TestCase):
    """One assertion per rule a 179-edit sweep could break in silence.

    Every case here failed on the mutant that found it and passed on the tree.
    They are grouped rather than scattered because what they have in common is
    the reason they were missing: each rule had a representative example and no
    boundary, so any narrowing that spared the example survived.
    """

    def _pattern(self, label: str):
        for name, pattern in validate_run_log.LEAKS:
            if name == label:
                return pattern
        raise AssertionError(f"no pattern named {label}")

    def test_the_path_rule_does_not_fire_on_a_relative_path(self) -> None:
        """Widening its left boundary would refuse the guide's own directory."""
        self.assertEqual(
            findings(line(detail="the cap under traigent-runs/readiness/ is standing")),
            [],
        )

    def test_every_slack_prefix_the_pattern_claims(self) -> None:
        for prefix in ("xoxb-", "xoxa-", "xoxp-", "xoxr-", "xoxs-"):
            with self.subTest(prefix=prefix):
                self.assertTrue(
                    self._pattern("a credential").search(prefix + "EXAMPLE-NOT-A-KEY")
                )

    def test_the_local_part_is_bounded(self) -> None:
        self.assertIsNone(
            self._pattern("an email address").search(
                "the account " + "a" * 70 + "@example.com"
            )
        )

    def test_every_tld_the_host_rule_lists(self) -> None:
        pattern = self._pattern("a host or address")
        for tld in ("com", "net", "org", "io", "ai", "dev"):
            with self.subTest(tld=tld):
                self.assertTrue(
                    pattern.search(f"could not reach portal.example.{tld} at all")
                )

    def test_the_detail_limit_and_its_boundary(self) -> None:
        """`>` not `>=`: a detail of exactly the limit is a sentence."""
        # Not "a": a long run of hex characters is a session id by another
        # rule, which is the fixture failing rather than the boundary.
        self.assertEqual(validate_run_log.DETAIL_LIMIT, 400)
        self.assertEqual(findings(line(detail="the run stopped " + "z" * 384)), [])
        self.assertTrue(
            any(
                "past the" in p
                for p in findings(line(detail="the run stopped " + "z" * 385))
            )
        )

    def test_the_identity_is_all_three_fields(self) -> None:
        """`open` on one identity must not clear another."""
        self.assertTrue(
            any(
                "without an open line" in p
                for p in findings(
                    line(), line(ts="20260823T151205Z", stage=7, state="cleared")
                )
            )
        )
        self.assertTrue(
            any(
                "without an open line" in p
                for p in findings(
                    line(),
                    line(ts="20260823T151205Z", state="cleared", **{"class": "answer"}),
                )
            )
        )

    def test_the_docstring_states_the_exit_codes_it_ships(self) -> None:
        doc = validate_run_log.__doc__ or ""
        for clause in (
            "Exits 0",
            "1 when any line is rejected",
            "2 when the file itself cannot be read",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, doc)

    def test_a_rejected_line_names_everything_it_carries(self) -> None:
        """One finding per carrier, so a reader fixes the line once."""
        problems = findings(
            line(
                detail="the file /home/user/proj/.env and https://example.com/api both failed"
            )
        )
        self.assertTrue(any("an absolute path" in p for p in problems))
        self.assertTrue(any("a URL" in p for p in problems))

    def test_the_file_is_untouched_byte_for_byte_and_stat_for_stat(self) -> None:
        """ "A checker, never a writer" - compared by inode, not by text."""
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "run-log.jsonl"
            log.write_text(
                json.dumps(line(**{"class": "nope"})) + "\n", encoding="utf-8"
            )
            before = log.stat()
            subprocess.run(
                [sys.executable, str(SCRIPT), "--log", str(log)],
                capture_output=True,
                check=False,
            )
            after = log.stat()
        self.assertEqual(
            (before.st_ino, before.st_size, before.st_mtime_ns),
            (after.st_ino, after.st_size, after.st_mtime_ns),
        )


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


class NoRemedyAsksForTheLineToBeRewrittenTests(unittest.TestCase):
    """The remedies told the reader to do the one thing the contract forbids.

    `references/run-safety.md` puts it in bold - the file is append-only, a
    line once written is never rewritten - and this script's own docstring
    already agreed that a rejected line is reported, not rewritten. Five
    remedies said otherwise anyway, and one of them (`a problem clears only
    after it was recorded as open`) could not be satisfied by any legal action
    at all, because an appended `open` lands after the `cleared` it would have
    to precede.

    The validator runs before every stop-and-wait once the record exists, so
    each of those was printed at every remaining gate for the rest of the run.
    """

    # One line per branch that rejects the shape of a line the log already
    # holds. Kept as raw text because two of them are not JSON objects.
    MALFORMED = (
        (
            "missing field",
            json.dumps({k: v for k, v in line().items() if k != "detail"}),
        ),
        ("is not YYYYMMDDTHHMMSSZ", json.dumps(line(ts="2026-08-23 15:12"))),
        ("line is not a JSON object", json.dumps(["not", "an", "object"])),
        ("line is not JSON", "{broken"),
        ("without an open line", json.dumps(line(state="cleared"))),
    )

    # Every verb that asks for the rejected line itself to change. `add it` is
    # listed whole: `add` alone is ordinary in a remedy about a later line.
    REWRITE = re.compile(
        r"\b(?:rewrite|restamp|amend|edit|correct|delete|replace)\b|^add it$",
        re.IGNORECASE,
    )

    def test_the_malformed_line_remedies_say_what_to_report(self) -> None:
        """The replacement, not only the absence.

        A ban alone is satisfied by emptying the remedy, so each of the five
        is pinned to the sentence that replaced it.

        The rule they answer to is pinned first, in both of its homes. Without
        that, deleting the append-only sentence from the reference would leave
        these five remedies correct about nothing, and this class would go on
        passing while the reason for it had gone.
        """
        reference = " ".join(BASE_REFERENCE.read_text().split())
        self.assertIn(
            "The file is append-only: a line, once written, is never rewritten",
            reference,
        )
        self.assertIn(
            "A rejected line is reported to the user, not rewritten",
            SCRIPT.read_text(),
        )
        for expected_problem, raw in self.MALFORMED:
            with self.subTest(problem=expected_problem):
                found = remedies_for(raw)
                problem, remedy = next(
                    pair for pair in found if expected_problem in pair[0]
                )
                self.assertTrue(
                    remedy.startswith("report the line as it stands"),
                    f"{problem!r} still answers with {remedy!r}",
                )

    def test_no_remedy_the_script_can_print_asks_for_a_rewrite(self) -> None:
        """The class, not the five instances.

        Asserted over every remedy the script produces on one log that reaches
        every branch, so a sixth remedy added later with the same reflex fails
        here rather than shipping.
        """
        text = "\n".join(raw for _problem, raw in self.MALFORMED)
        text += "\n" + "\n".join(
            json.dumps(record)
            for record in (
                line(event="exploded"),
                line(**{"class": "not-a-class"}),
                line(stage="5"),
                line(state="paused"),
                line(detail="the run stopped at /home/someone/project/agent.py"),
                {**line(), "extra": 1},
            )
        )
        produced = remedies_for(text)
        self.assertGreaterEqual(
            len(produced), 10, "the sweep stopped reaching branches"
        )
        for problem, remedy in produced:
            with self.subTest(problem=problem):
                self.assertIsNone(
                    self.REWRITE.search(remedy),
                    f"{problem!r} asks for the rejected line to be changed",
                )

    def test_the_orphan_cleared_remedy_states_what_an_append_can_do(self) -> None:
        """The unsatisfiable one, measured rather than argued.

        Appending the `open` the old remedy asked for leaves the finding
        exactly where it was, because the append lands after the `cleared`.
        The remedy now says that, so a reader stops trying.
        """
        orphan = json.dumps(line(state="cleared"))
        before = remedies_for(orphan + "\n")
        after = remedies_for(
            orphan + "\n" + json.dumps(line(ts="20260823T151205Z")) + "\n"
        )
        self.assertEqual(
            [p for p, _ in before],
            [p for p, _ in after],
            "appending an open line changed the finding, so the remedy was "
            "satisfiable after all and this fix is wrong",
        )
        remedy = next(r for p, r in after if "without an open line" in p)
        self.assertIn("would land after it, never before it", remedy)

    def test_a_quoted_stage_is_answered_about_the_quotes(self) -> None:
        """`use 1 to 8` told the writer of `"5"` to do what they had done.

        Five of the six fields take strings and the contract's own table types
        `class` on the row after `stage` without typing `stage`, so quoting it
        is the slip the remedy has to name.
        """
        _problem, remedy = next(
            pair
            for pair in remedies_for(json.dumps(line(stage="5")) + "\n")
            if "run-record stage" in pair[0]
        )
        self.assertEqual(remedy, "use an unquoted integer 1 to 8")

    def test_an_address_is_refused_with_the_reason_the_guidance_gives(self) -> None:
        """The refusal read as a contradiction of the reference beside it.

        `run-safety.md` tells the reader the registration address is not a
        credential and is safe to hand over; this script refused a `detail`
        naming a portal address with `never the instance`, which an address is
        not an instance of. Both hold - safe to say, still not part of what
        happened - and the remedy is where they are reconciled.

        The reference half is asserted too: if that sentence ever leaves the
        guidance, this remedy is answering a question nobody is being asked.
        """
        reference = " ".join(BASE_REFERENCE.read_text().split())
        self.assertIn("is not a credential and is safe to hand over", reference)
        for detail, label in (
            (
                "no portal key was entered; get one at portal.traigent.ai",
                "a host or address",
            ),
            ("the portal refused the account; see https://portal.traigent.ai", "a URL"),
        ):
            with self.subTest(detail=detail):
                # Looked up BY LABEL, not by position. A URL also trips the
                # absolute-path pattern - `//` satisfies it - so the first
                # finding on that line is a different carrier with a different
                # remedy, and taking it would have tested nothing.
                found = {
                    problem: remedy
                    for problem, remedy in remedies_for(
                        json.dumps(line(detail=detail)) + "\n"
                    )
                }
                remedy = found[f"detail carries {label}"]
                self.assertEqual(remedy, validate_run_log.ADDRESS_REMEDY)
                self.assertIn("safe to say to the user", remedy)

    def test_every_addressed_remedy_is_keyed_to_a_carrier_that_exists(self) -> None:
        """A typo in the map is silent: `.get` hands back the general sentence.

        So the key set is pinned against the labels `LEAKS` actually defines,
        and the two carriers that need the address sentence are named, rather
        than only counted.
        """
        labels = {label for label, _pattern in validate_run_log.LEAKS}
        self.assertEqual(
            set(validate_run_log.LEAK_REMEDIES) - labels,
            set(),
            "a remedy is keyed to a carrier no pattern reports",
        )
        self.assertEqual(
            set(validate_run_log.LEAK_REMEDIES), {"a URL", "a host or address"}
        )
        # And the carriers that keep the general sentence still get one.
        for label in labels - set(validate_run_log.LEAK_REMEDIES):
            with self.subTest(label=label):
                self.assertEqual(
                    validate_run_log.LEAK_REMEDIES.get(
                        label, validate_run_log.LEAK_REMEDY
                    ),
                    validate_run_log.LEAK_REMEDY,
                )


class TheFieldsWithNoNegativeCoverageTests(unittest.TestCase):
    """`ts`, `stage`, `state` and the record shape had none at all.

    A mutation sweep put a number on it: fifteen single edits that each broke a
    real rule stayed green, because every rule had exactly one representative
    example and no boundary. Deleting the timestamp check, widening the stage
    range, adding a third state, and accepting a non-object line were four of
    them. One example per rule proves the rule was written, not that it holds.
    """

    def test_a_timestamp_that_is_not_the_stamp_format_is_refused(self) -> None:
        for bad in (
            "nope",
            "2026-08-23T15:12:04Z",
            "20260823T151204",
            "",
            "20260823",
            "20260823t151204z",
        ):
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
        for field in ("class", "event", "state", "detail"):
            for bad in ([1], {"a": 1}):
                with self.subTest(field=field, value=bad):
                    problems = findings(line(**{field: bad}))
                    self.assertTrue(problems, f"{field}={bad!r} produced no finding")

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
            # RFC 5737 TEST-NET-3, reserved for documentation and never
            # routable - the same literal form this repository already uses
            # in its socket-contract fixtures.
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
        blank_run = 0
        for row in text.splitlines():
            opener = re.match(r"[-*+]\s+`([a-z_]+)`\s*[-\u2013\u2014]\s", row)
            if opener:
                current = opener.group(1)
                bullets[current] = row
            elif current and (row.startswith("  ") or blank_run == 0 and row.strip()):
                bullets[current] += " " + row.strip()
            elif current and not row.strip():
                blank_run += 1
                if blank_run > 1:
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
            # The bullet also names the event itself, and may name a FIELD -
            # `detail`, where a failing command's exit status goes. The
            # vocabulary is what remains once both are taken out.
            declared -= {event} | validate_run_log.EVENTS | validate_run_log.FIELDS
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

    def test_an_absent_log_is_nothing_to_report_rather_than_a_failure(self) -> None:
        """A run that met nothing worth logging wrote no file.

        Reporting that as unreadable had the guide route exit 2 as a tool
        failure - opening a log to complain that one is missing.
        """
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--log", str(ROOT / "no-such-file.jsonl")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no run log was written", result.stdout)

    def test_a_log_that_exists_and_cannot_be_read_exits_two(self) -> None:
        """Exit 2 is the file being unusable, which is not a finding about it."""
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            # A directory at the log's path exists and cannot be read as a file.
            log = Path(directory) / "run-log.jsonl"
            log.mkdir()
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--log", str(log)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot be read", result.stderr)

    def test_invalid_utf8_is_the_file_being_unusable_not_an_internal_error(
        self,
    ) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "run-log.jsonl"
            log.write_bytes(b'{"ts": "\xff\xfe"}\n')
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--log", str(log)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 2)

    def test_a_byte_order_mark_is_not_broken_json(self) -> None:
        import tempfile

        record = json.dumps(line())
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "run-log.jsonl"
            log.write_text(record + "\n", encoding="utf-8-sig")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--log", str(log)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_line_separator_inside_a_string_does_not_split_the_line(self) -> None:
        """`splitlines()` breaks on U+2028, which is legal inside a JSON string."""
        record = json.dumps(
            line(detail="the run stopped\u2028waiting"), ensure_ascii=False
        )
        problems = [f.problem for f in validate_run_log.validate(record + "\n")]
        self.assertEqual([p for p in problems if "not JSON" in p], [])

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

    def test_a_malformed_line_never_reports_the_check_as_broken(self) -> None:
        """`json.loads` raises RecursionError, which is not a ValueError.

        A deeply nested line is a finding about the log; reporting it as exit 3
        has the guide route its own checker as a tool failure.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "run-log.jsonl"
            log.write_text('{"a":' + "[" * 60_000 + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--log", str(log)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_a_stamp_in_other_digits_is_not_a_stamp(self) -> None:
        """Python's `\\d` is Unicode; the format this guide writes is not."""
        problems = findings(
            line(
                ts="\u0662\u0660\u0662\u0666\u0660\u0668\u0662\u0663T\u0662\u0660\u0661\u0668\u0665\u0661Z"
            )
        )
        self.assertTrue(any("YYYYMMDDTHHMMSSZ" in p for p in problems))

    def test_a_trailing_newline_does_not_satisfy_a_pattern(self) -> None:
        """`$` admits one; `fullmatch` is what the contract meant."""
        self.assertTrue(findings(line(ts="20260823T151204Z\n")))
        self.assertTrue(findings(line(**{"class": "key\n"})))

    def test_the_json_contract_holds_on_every_exit(self) -> None:
        """`--json` promised a parseable stdout and broke it on the commonest exit."""
        import tempfile

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--log",
                str(ROOT / "absent.jsonl"),
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "absent")

        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "run-log.jsonl"
            log.mkdir()
            unreadable = subprocess.run(
                [sys.executable, str(SCRIPT), "--log", str(log), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(unreadable.returncode, 2)
        self.assertEqual(json.loads(unreadable.stdout)["status"], "unreadable")

    def test_a_usage_error_is_the_check_failing_not_the_log(self) -> None:
        """argparse exits 2, which this tool spends on an unreadable log."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--not-a-real-flag"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 3)

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
        # One home each: the docstring for this script's own exits, and the
        # file's existing rule for exit 3, which every bundled script shares.
        self.assertIn("its docstring states what each exit means", text)
        self.assertIn("exit 3 routes as it does for every bundled script", text)
        self.assertIn("exit 3 from any bundled script", text)

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
        self.assertIn(
            "a rejected line is reported to the user with what it carries", text
        )
        self.assertNotIn("may rewrite a line", text)
        # The append-only claim itself stays where it is stated once.
        self.assertIn("a line, once written, is never rewritten", text)


if __name__ == "__main__":
    unittest.main()

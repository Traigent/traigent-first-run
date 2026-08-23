#!/usr/bin/env python3
"""Check `traigent-runs/run-log.jsonl` against the contract that defines it.

Every rule here is one `references/run-safety.md` states in prose and the
assistant carries out by hand: a closed class vocabulary per event, an exact
field set, `open` before `cleared`, and a `detail` naming the class of thing
that happened rather than the instance. A rule an assistant is asked to obey is
obeyed as often as it happens to remember it, and this is the one artifact whose
value is being trustworthy about a run that already went wrong.

What it cannot do is prove a sentence is free of the project's data. It refuses
the carriers that have a recognisable shape - paths, credentials, addresses,
identifiers, links, quoted spans - and five things the allowlist names have no
shape a checker can settle: a person's name, a machine's, an access or
confirmation code, a provider error body, and short or unquoted text from the
project. Those stay the assistant's to honour, and are named here so nobody
reads a clean exit as proof of more than it is.

One shape is settled only partly, and saying which is cheaper than implying
otherwise. An identifier is refused when it is hexadecimal, a UUID, or a run of
one case with a digit in it - the shapes ids actually take. A mixed-case token
escapes, because nothing separates one from a class name like
`AzureOpenAIGpt4Error`, and two attempts to separate them by where the digit
sits refused eight of thirteen real class names to catch ids a later attempt
caught anyway.

It is a checker, never a writer: it opens the log read-only and never edits it.
A rejected line is reported to the user, not rewritten. Nothing in the guided
run reads this output back as run state.

Exits 0 when every line holds, 1 when any line is rejected - a line that is not
JSON among them - 2 when the file itself cannot be read, and 3 when this script
fails, which is never a finding about the log.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

INTERNAL_ERROR_EXIT = 3
TRACEBACK_ENV = "TRAIGENT_FIRST_RUN_TRACEBACK"

# The identity is `event` + `stage` + `class`, so `class` is one of the three
# things deduplication matches on. Left open, one failure met twice spells itself two
# ways and the log grows a second entry for a problem that never changed.
#
# Three events, told apart by who has to act - the user, this run, or
# nobody. A fourth needs a boundary rule against the other three, and every
# boundary rule this file carried was a rule about the taxonomy rather than
# about a run.
CLASSES: dict[str, frozenset[str]] = {
    "blocked": frozenset({"approval", "key", "answer"}),
    "stopped": frozenset(
        {
            # a gate this guide defines
            "credential-file-tracked",
            "ignore-check",
            "containment",
            "readiness-cap",
            "invariants",
            # a bundled script that could not run
            "tool",
            # a provider, portal or Traigent refusal, by its category
            "authentication",
            "key-scope",
            "account-access",
            "quota",
            "rate",
            "validation",
            # the run or a phase ending early for its own reasons
            "timeout",
            "cost-ceiling",
            "outage",
            "persistence",
            "uncategorized",
        }
    ),
    "warning": frozenset(
        {"refused-trial", "untracked-cost", "cap-standing", "uncategorized"}
    ),
}
EVENTS = frozenset(CLASSES)
STATES = frozenset({"open", "cleared"})
FIELDS = frozenset({"ts", "event", "stage", "class", "state", "detail"})
TIMESTAMP = re.compile(r"[0-9]{8}T[0-9]{6}Z")

# What `detail` may not carry. The allowlist in run-safety.md is written as a
# sentence; these are the shapes that sentence decomposes into, and they are the
# ones a machine can settle. A checker cannot prove a sentence carries no
# customer data - it can refuse every carrier anyone has actually leaked
# through, which is what the clause is protecting against.
# One sentence, so a `detail` far past that is itself the finding, and a
# pattern scan over a huge single token is where a checker stops being fast.
# The bound is generous: it refuses a paste, not a long sentence.
DETAIL_LIMIT = 400

LEAKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Requires a boundary before the slash, so `3/5`, `and/or` and `input/output`
    # stay ordinary prose. The Windows branch takes one escaped backslash: two
    # matches a literal `C:\\`, which no JSON-decoded path contains.
    (
        "an absolute path",
        re.compile(r"(?<![A-Za-z0-9])(?:/[^\s\"']*/|~/|[A-Za-z]:\\)"),
    ),
    (
        "a credential",
        re.compile(
            r"\b(?:sk-ant-|sk-|sk_|uk_|ghp_|gho_|ghu_|ghs_|github_pat_|xox[baprs]-|AKIA|eyJ)"
            r"[A-Za-z0-9_\-]{8,}"
        ),
    ),
    # Bounded on both sides of the `@`: unbounded, this backtracks
    # quadratically on a long token containing no `@`, which is exactly the
    # pasted error body or base64 blob the rule exists to catch. A decorator
    # such as `@traigent.optimize` has nothing before the `@`, so it never
    # matched: the lookbehind is what lets an address follow a bracket.
    (
        "an email address",
        re.compile(
            r"(?<![A-Za-z0-9._%+\-@])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,255}\.[A-Za-z]{2,}"
        ),
    ),
    (
        "a session or request id",
        re.compile(
            r"\b(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{12}|[0-9a-fA-F]{16,}"
            r"|(?=[A-Za-z0-9]*[0-9])(?:[a-z0-9]{20,}|[A-Z0-9]{20,}))\b"
        ),
    ),
    ("a URL", re.compile(r"\bhttps?://\S+")),
    (
        "a host or address",
        re.compile(
            r"\b(?:\d{1,3}(?:\.\d{1,3}){3}\b|(?<!\d\.)[a-z0-9-]*[a-z][a-z0-9-]*\.(?:com|net|org|io|ai|dev)\b)"
        ),
    ),
    # A quoted span this long is a row, a prompt, or a model answer. The quotes
    # must PAIR: keying on an opener alone made every possessive apostrophe a
    # finding, so `the provider's quota was exhausted` was refused.
    (
        "quoted content",
        re.compile(
            # Both straight forms are bounded on each side by a character
            # a word can end with, because an apostrophe between two of
            # those is a possessive or a contraction: without it "the
            # user's approval before the provider's trial" reads as one
            # span, and so does a closing quote pairing with the opening
            # quote of the next quoted term. Digits count - a model id or a
            # version ends in one.
            '(?<![A-Za-z0-9])"[^"]{25,}"(?![A-Za-z0-9])'
            "|(?<![A-Za-z0-9])'[^']{25,}'(?![A-Za-z0-9])"
            "|\u201c[^\u201d]{25,}\u201d"
            "|\u2018[^\u2019]{25,}\u2019"
        ),
    ),
)


class Finding:
    """One rejected line, named by where it is and what is wrong with it."""

    def __init__(self, line_number: int, problem: str, remedy: str) -> None:
        self.line_number = line_number
        self.problem = problem
        self.remedy = remedy

    def as_dict(self) -> dict[str, Any]:
        return {
            "line": self.line_number,
            "problem": self.problem,
            "remedy": self.remedy,
        }

    def render(self) -> str:
        return f"  line {self.line_number}: {self.problem}\n    fix: {self.remedy}"


def _check_class(event: str, value: Any, number: int, out: list[Finding]) -> None:
    allowed = CLASSES.get(event)
    if allowed is None:
        return
    # `value in allowed` raises TypeError on a list or dict, and exit 3 is
    # reserved for the check breaking rather than for the log being wrong.
    if isinstance(value, str) and value in allowed:
        return
    out.append(
        Finding(
            number,
            f"{event} class {value!r} is outside its closed set",
            "use one of: " + ", ".join(sorted(allowed)),
        )
    )


def _check_detail(value: Any, number: int, out: list[Finding]) -> None:
    if not isinstance(value, str) or not value.strip():
        out.append(
            Finding(number, "detail is empty", "name what happened in one sentence")
        )
        return
    if len(value) > DETAIL_LIMIT:
        out.append(
            Finding(
                number,
                f"detail is {len(value)} characters, past the {DETAIL_LIMIT} a sentence needs",
                "one sentence naming the class of thing that happened",
            )
        )
        return
    for label, pattern in LEAKS:
        if pattern.search(value):
            out.append(
                Finding(
                    number,
                    f"detail carries {label}",
                    "name the class of thing that failed, never the instance",
                )
            )


def _check_line(record: Any, number: int, out: list[Finding]) -> tuple[str, str] | None:
    """Validate one record; return its identity when the line is well formed."""
    if not isinstance(record, dict):
        out.append(
            Finding(number, "line is not a JSON object", "write one object per line")
        )
        return None

    present = set(record)
    for missing in sorted(FIELDS - present):
        out.append(Finding(number, f"missing field {missing!r}", "add it"))
    for extra in sorted(present - FIELDS):
        out.append(
            Finding(
                number,
                f"unknown field {extra!r}",
                "the field set is closed: " + ", ".join(sorted(FIELDS)),
            )
        )
    if not FIELDS <= present:
        return None

    if not TIMESTAMP.fullmatch(str(record["ts"])):
        out.append(
            Finding(
                number, f"ts {record['ts']!r} is not YYYYMMDDTHHMMSSZ", "restamp it"
            )
        )
    event = record["event"]
    if not isinstance(event, str) or event not in EVENTS:
        out.append(
            Finding(
                number,
                f"event {event!r} is not one of the six",
                "use one of: " + ", ".join(sorted(EVENTS)),
            )
        )
        return None
    stage = record["stage"]
    if not isinstance(stage, int) or isinstance(stage, bool) or not 1 <= stage <= 8:
        out.append(
            Finding(number, f"stage {stage!r} is not a run-record stage", "use 1 to 8")
        )
    state_value = record["state"]
    if not isinstance(state_value, str) or state_value not in STATES:
        out.append(
            Finding(
                number,
                f"state {state_value!r} is neither open nor cleared",
                "use open when it happens, cleared when it stops applying",
            )
        )
    _check_class(event, record["class"], number, out)
    _check_detail(record["detail"], number, out)
    return (event, str(stage), str(record["class"]))


def validate(text: str) -> list[Finding]:
    """Every finding in one log, in the order a reader meets them."""
    findings: list[Finding] = []
    # An identity's state as the file has told it so far. `cleared` before
    # `open` is the one sequence that is wrong however it arose, and it is not
    # visible one line at a time. A repeated `open` is NOT checked: a resumed
    # session cannot remember what it left standing and the guide licenses it to
    # open again, so refusing that would refuse correct input - and collapsing on
    # the identity answers the same either way. Deduplication stays guidance.
    standing: dict[tuple[str, str], str] = {}
    # split("\n"), not splitlines(): the latter also breaks on U+2028,
    # U+2029 and the vertical tab, each of which is legal inside a JSON
    # string and would turn one valid line into two invalid ones.
    for number, raw in enumerate(text.split("\n"), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except (ValueError, RecursionError) as error:
            findings.append(
                Finding(number, f"line is not JSON ({error})", "write one JSON object")
            )
            continue
        identity = _check_line(record, number, findings)
        if identity is None:
            continue
        key = (identity[0], identity[1] + ":" + identity[2])
        state = record["state"]
        if state == "cleared" and standing.get(key) != "open":
            findings.append(
                Finding(
                    number,
                    "cleared without an open line before it",
                    "a problem clears only after it was recorded as open",
                )
            )
        standing[key] = state
    return findings


class _Parser(argparse.ArgumentParser):
    """Usage errors exit as the check breaking, not as an unreadable log.

    argparse's own exit code is 2, which this tool spends on "the file exists
    and could not be read" - so a misspelled flag reported a false fact about
    the customer's log.
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: {message}", file=sys.stderr)
        raise SystemExit(INTERNAL_ERROR_EXIT)


def run(argv: list[str] | None = None) -> int:
    parser = _Parser(
        description=(
            "Check a run log against the contract in references/run-safety.md. "
            "Read-only: it never writes to the log."
        )
    )
    parser.add_argument("--log", required=True, help="path to run-log.jsonl")
    parser.add_argument(
        "--json", action="store_true", help="emit findings as JSON on stdout"
    )
    args = parser.parse_args(argv)

    path = Path(args.log)

    def envelope(status: str, findings: list[Finding]) -> None:
        """The `--json` contract holds on every exit, not only the found one."""
        print(
            json.dumps(
                {
                    "log": str(path),
                    "status": status,
                    "findings": [finding.as_dict() for finding in findings],
                },
                indent=2,
            )
        )

    if not path.exists():
        # Reporting an absent log as unreadable would have the guide open a
        # file to complain that one is missing.
        if args.json:
            envelope("absent", [])
        else:
            print(f"{path}: no run log was written")
        return 0
    try:
        # utf-8-sig so a byte-order mark is not reported as broken JSON.
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        if args.json:
            envelope("unreadable", [])
        print(f"run log cannot be read: {error}", file=sys.stderr)
        return 2

    findings = validate(text)
    if args.json:
        envelope("ok" if not findings else "rejected", findings)
    elif findings:
        lines = len({finding.line_number for finding in findings})
        print(f"{len(findings)} finding(s) on {lines} line(s) in {path}:")
        for finding in findings:
            print(finding.render())
    else:
        print(f"{path}: every line holds")
    return 1 if findings else 0


def report_internal_error(tool: str, error: BaseException) -> int:
    """Say the check broke, not the project - copied out per script by design.

    Each bundled script owns this boundary, because each ships alone. The stack
    is available behind an environment variable rather than printed at a user
    who did not ask for it.
    """
    print(f"{tool}: {type(error).__name__}: {error}", file=sys.stderr)
    print(
        f"{tool} could not complete. This is a defect in the check rather than "
        "in your project; nothing about the run log was established.",
        file=sys.stderr,
    )
    if os.environ.get(TRACEBACK_ENV):
        traceback.print_exc()
    return INTERNAL_ERROR_EXIT


def main() -> int:
    try:
        return run()
    except Exception as error:  # noqa: BLE001 - reported, never swallowed
        return report_internal_error("validate_run_log.py", error)


if __name__ == "__main__":
    sys.exit(main())

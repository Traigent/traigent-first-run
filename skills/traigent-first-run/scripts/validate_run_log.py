#!/usr/bin/env python3
"""Check `traigent-runs/run-log.jsonl` against the contract that defines it.

Every rule this checks is one `references/run-safety.md` states in prose and the
assistant executes by hand: a closed class vocabulary per event, an exact field
set, `open` before `cleared`, and a `detail` that names the class of thing that
failed rather than the instance. Prose is what this repository's own history
says gets diverged from - four workers across two model families took one wrong
path in a single investigation - and this file is the one artifact whose value
is being trustworthy about a run that already went wrong.

It is a checker, never a writer: it opens the log read-only, and a run that
fails it fixes the line rather than the check. Nothing in the guided run reads
this output back as run state.

Exits 0 when every line holds, 1 when a line is rejected, 2 when the log itself
cannot be read as JSONL, and 3 when this script fails.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

INTERNAL_ERROR_EXIT = 3

# The identity is `event` + `stage` + `class`, so `class` is two thirds of what
# deduplication matches on. Left open, one failure met twice spells itself two
# ways and the log grows a second entry for a problem that never changed.
CLASSES: dict[str, frozenset[str]] = {
    "blocked": frozenset({"approval", "key", "answer"}),
    "gate_fail": frozenset(
        {
            "credential-file-tracked",
            "ignore-check",
            "containment",
            "readiness-cap",
            "invariants",
        }
    ),
    "external_refusal": frozenset(
        {
            "authentication",
            "key-scope",
            "account-access",
            "quota",
            "rate",
            "validation",
        }
    ),
    "run_stop": frozenset(
        {"timeout", "cost-ceiling", "outage", "persistence", "uncategorized"}
    ),
    "warning": frozenset({"refused-trial", "untracked-cost", "cap-standing"}),
}
# `tool_fail` closes over the exit codes a command can return rather than over a
# hand-written list, so it is checked by shape.
EXIT_CODE_CLASS = re.compile(r"^(?:0|[1-9][0-9]{0,2})$")
EVENTS = frozenset(CLASSES) | {"tool_fail"}
STATES = frozenset({"open", "cleared"})
FIELDS = frozenset({"ts", "event", "stage", "class", "state", "detail"})
TIMESTAMP = re.compile(r"^\d{8}T\d{6}Z$")

# What `detail` may not carry. The allowlist in run-safety.md is written as a
# sentence; these are the shapes that sentence decomposes into, and they are the
# ones a machine can settle. A checker cannot prove a sentence carries no
# customer data - it can refuse every carrier anyone has actually leaked
# through, which is what the clause is protecting against.
LEAKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("an absolute path", re.compile(r"(?:^|[\s\"'(])(?:/[^\s\"']*/|~/|[A-Za-z]:\\\\)")),
    (
        "a credential",
        re.compile(
            r"\b(?:sk-ant-|sk-|sk_|uk_|ghp_|gho_|ghu_|ghs_|github_pat_|xox[baprs]-|AKIA|eyJ)"
            r"[A-Za-z0-9_\-]{8,}"
        ),
    ),
    ("an email address", re.compile(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}")),
    (
        "a session or request id",
        re.compile(
            r"\b(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{12}|[0-9a-fA-F]{24,})\b"
        ),
    ),
    ("a URL", re.compile(r"\bhttps?://\S+")),
    # A quoted span this long is a row, a prompt, or a model answer - the three
    # things `TRAIGENT_LOG_EXAMPLE_CONTENT=false` exists to keep off the disk.
    ("quoted content", re.compile(r"[\"'“‘][^\"'”’]{25,}")),
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
    if event == "tool_fail":
        if not EXIT_CODE_CLASS.match(str(value)):
            out.append(
                Finding(
                    number,
                    f"tool_fail class {value!r} is not an exit code",
                    "use the exit status the command returned",
                )
            )
        return
    allowed = CLASSES.get(event)
    if allowed is None or value in allowed:
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

    if not TIMESTAMP.match(str(record["ts"])):
        out.append(
            Finding(
                number, f"ts {record['ts']!r} is not YYYYMMDDTHHMMSSZ", "restamp it"
            )
        )
    event = record["event"]
    if event not in EVENTS:
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
    if record["state"] not in STATES:
        out.append(
            Finding(
                number,
                f"state {record['state']!r} is neither open nor cleared",
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
    # `open` and a repeat of a state already standing are the two sequences the
    # append-only rule forbids, and neither is visible one line at a time.
    standing: dict[tuple[str, str], str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except ValueError as error:
            findings.append(
                Finding(number, f"line is not JSON ({error})", "write one JSON object")
            )
            continue
        identity = _check_line(record, number, findings)
        if identity is None:
            continue
        key = (identity[0], identity[1] + ":" + identity[2])
        state = record["state"]
        previous = standing.get(key)
        if state == "cleared" and previous != "open":
            findings.append(
                Finding(
                    number,
                    "cleared without an open line before it",
                    "a problem clears only after it was recorded as open",
                )
            )
        elif state == previous:
            findings.append(
                Finding(
                    number,
                    f"repeats {state!r} for an identity already {state}",
                    "a repeat that changed nothing adds no line",
                )
            )
        standing[key] = state
    return findings


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
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
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"run log cannot be read: {error}", file=sys.stderr)
        return 2

    findings = validate(text)
    if args.json:
        print(
            json.dumps(
                {
                    "log": str(path),
                    "status": "ok" if not findings else "rejected",
                    "findings": [finding.as_dict() for finding in findings],
                },
                indent=2,
            )
        )
    elif findings:
        print(f"{len(findings)} line(s) rejected in {path}:")
        for finding in findings:
            print(finding.render())
    else:
        print(f"{path}: every line holds")
    return 1 if findings else 0


def main() -> int:
    try:
        return run()
    except Exception as error:  # noqa: BLE001 - reported, never swallowed
        print(f"validate_run_log.py failed: {error!r}", file=sys.stderr)
        return INTERNAL_ERROR_EXIT


if __name__ == "__main__":
    sys.exit(main())

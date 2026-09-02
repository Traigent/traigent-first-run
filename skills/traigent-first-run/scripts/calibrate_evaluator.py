#!/usr/bin/env python3
"""Execute evaluator probes in an explicitly authorized child process.

Every scorer must return a finite, normalized, higher-is-better score in ``[0,1]``.
For deterministic calibration the child is credential-stripped, but process separation is not a
sandbox. This first-run guide does not calibrate a scorer that executes candidate code or SQL
through the ordinary path - not because the probes are the model's, they are authored here, but
because calling such a scorer opens an engine against a database this step cannot bound.
``--contained`` is the one bounded route that will, and ``references/run-safety.md`` states its
limits beside the manual containment review it does not replace. The read below decides which of
the two a scorer is eligible for, and refuses rather than guesses when it cannot follow the
scorer's path.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import builtins
import contextlib
import importlib.util
import inspect
import io
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from pathlib import Path
from typing import Any

# One budget rule, both kinds, and it is derived from the work rather than
# fixed. The point of calibration is to learn whether the user's evaluator can
# tell a right answer from a wrong one, and an evaluator that takes about a
# minute per call - a local model, a heavy normalisation, a network lookup - was
# being killed before it could report, so "we stopped it" was scored as "we
# could not verify it". Letting it finish is the whole job; a slow evaluator is
# a cost signal, not a broken one.
#
# A flat number cannot do that, which is why it is gone. The work scales with
# the case set: every case has four authored calls.  A deterministic run can add
# up to eight supplemental calls (five exception probes, up to two seam probes,
# and, where meaningful, a permutation probe).  A one-minute-per-call
# deterministic scorer therefore needs up to 1440 seconds for two cases; a judge
# needs 480. The onboarding
# ceiling can cut that work, but below it the budget must scale with every call
# it can make.
#
# Per-probe allowances. 75 seconds deterministic: the evaluator this exists for
# takes about a minute per call, and 75 gives that a quarter of headroom instead
# of landing exactly on it. 90 for a judge, which additionally pays network
# latency and may be a reasoning model thinking for a minute or more per probe.
# Four probes decide the calibration. Deterministic calibration then makes five
# exception probes, up to two seam probes, and, where the expected output
# admits a distinct ordering, one permutation probe per case. They are
# advisory, but they are real scorer calls and the default whole-calibration
# deadline reserves for the maximum - the seam probes included, on every
# deterministic case rather than only the ones whose flags arm them, because a
# budget that changes with a flag cannot be quoted before the flag is chosen.
PROBES_PER_CASE = 4
DETERMINISTIC_SUPPLEMENTAL_PROBES_PER_CASE = 1 + 2 + 5
DETERMINISTIC_SECONDS_PER_PROBE = 75
LLM_JUDGE_SECONDS_PER_PROBE = 90
# Fifteen minutes, and it is an owner decision rather than a derivation. This is
# onboarding, not a full-power run: a calibration that has not separated a good
# answer from a bad one in fifteen minutes most probably will not, and asking a
# first-run user to keep waiting past that buys a verdict they can already act
# on without. The previous 1800 was derived - the largest documented case set at
# its full per-probe allowance - and derivation is the wrong instrument for
# "how long is it fair to ask someone to wait", which is a judgement about the
# person and not about the work.
#
# So it CLAMPS, on purpose, and the clamp is the part that must be disclosed
# rather than hidden. A deterministic case reserves twelve possible calls, so at
# 75s each the ceiling already cuts the two-pair minimum (1800s derived); a
# judge at 90s stays whole through two pairs (720s) and is cut from three
# (1080s). A cut case set gets less per probe than `--help` quotes - 45 seconds
# per judge call at five pairs and 15 seconds per deterministic possible call -
# so an evaluator that really does take about a minute per call cannot finish a
# documented matrix inside this ceiling and will reach the timeout question.
# `references/evaluation-and-dataset.md` states that consequence to the user
# before the wait starts, and the guidance test welds it to this number.
#
# An explicit `--timeout` is deliberately not clamped: it is how the user's own
# "wait, my evaluator is normally this slow" answer to the timeout question is
# carried out, and a ceiling that overrode the person it was protecting would
# make that answer unanswerable.
#
# There is no floor. One lived here at 180 and could never bind - the smallest
# possible case set is a single case, which is four probes, which is already 300
# seconds - and an unreachable clamp reads as a protection that is not there.
CALIBRATION_TIMEOUT_CEILING_SECONDS = 900
SECONDS_PER_PROBE = {
    "deterministic": DETERMINISTIC_SECONDS_PER_PROBE,
    "llm-judge": LLM_JUDGE_SECONDS_PER_PROBE,
}
# How long before the budget expires the run says so, and why a fixed lead
# rather than a fraction of the budget: what the reader needs is time to decide,
# and two minutes is two minutes whatever the budget is, while a percentage of a
# short budget is seconds and decides nothing. At the 900-second ceiling it
# lands at minute 13 of 15.
#
# There is nothing to decide about STOPPING, which is why this is a warning and
# not a question - see `pre_cap_warning_message`.
PRE_CAP_WARNING_LEAD_SECONDS = 120


def calibration_timeout_seconds(case_count: int, kind: str) -> int:
    """Budget a calibration from the number of probe calls it is about to make."""
    probes_per_case = PROBES_PER_CASE
    if kind == "deterministic":
        probes_per_case += DETERMINISTIC_SUPPLEMENTAL_PROBES_PER_CASE
    probes = max(1, case_count) * probes_per_case
    return min(
        CALIBRATION_TIMEOUT_CEILING_SECONDS,
        probes * SECONDS_PER_PROBE[kind],
    )


def pre_cap_warning_delay(timeout_seconds: int) -> float | None:
    """Seconds to wait before warning, or None when a warning would say nothing.

    A budget no longer than the lead has no "before the cap" to warn in: the
    warning would fire at or before the first probe call, repeating what the
    assistant already said when it announced the wait.
    """
    if timeout_seconds <= PRE_CAP_WARNING_LEAD_SECONDS:
        return None
    return float(timeout_seconds - PRE_CAP_WARNING_LEAD_SECONDS)


def pre_cap_warning_message(timeout_seconds: int) -> str:
    """The pre-cap line, which is a warning and deliberately not a question.

    A "stop or continue?" here would be dishonest, because the two answers are
    not comparable: continuing costs the remaining minutes, and stopping costs
    every minute already spent. Calibration has no resume - the authored probes
    all run in one child that prints its result only once every case is done,
    and the parent writes nothing until that returns - so a stop discards the
    whole wait and a re-run starts at the first probe. Saying so is the only
    honest version of this line; the question with real alternatives is the one
    the timeout itself asks, after the budget has actually been spent.
    """
    return (
        "CALIBRATION STILL RUNNING: "
        f"{PRE_CAP_WARNING_LEAD_SECONDS} of the {timeout_seconds} seconds "
        "budgeted for this calibration remain. Nothing is recorded yet and "
        "there is no resume: calibration writes its result only when it "
        "finishes, so stopping now discards this wait entirely and a re-run "
        "starts from the first probe. Left alone it stops itself at the budget "
        "and writes the timeout record, which is a result that can be acted "
        "on. Relay this as a warning, not as a question."
    )


def start_pre_cap_warning(timeout_seconds: int) -> threading.Timer | None:
    """Arm the pre-cap warning on stderr, or return None when there is none.

    stderr because the documented calibration invocation is detached with
    stdout redirected into the results file - the log is where a warning issued
    while the run is still going can actually be read. Daemon, so the error
    paths that return before the cancel below cannot hold the interpreter open
    waiting for a warning about a calibration that already stopped.
    """
    delay = pre_cap_warning_delay(timeout_seconds)
    if delay is None:
        return None
    timer = threading.Timer(
        delay,
        lambda: print(pre_cap_warning_message(timeout_seconds), file=sys.stderr),
    )
    timer.daemon = True
    timer.start()
    return timer


GOOD_MINIMUM = 0.8
BAD_MAXIMUM = 0.2
EQUIVALENCE_TOLERANCE = 0.15
SEPARATION_MARGIN = 0.05
SECRET_MARKERS = (
    "API_KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "ACCESS_KEY",
    "AUTHORIZATION",
    "COOKIE",
    "SESSION",
)
MATRIX_COVERAGE_NOTE = (
    "Distinct names and payloads are structural checks only; calibration relies on "
    "the coding assistant's recorded evidence-backed semantic-coverage review of "
    "materially distinct inputs, outcome classes, and rubric/schema branches, "
    "including mode/threshold rationale, gaps, and verdict."
)
PROBE_NAMES = ("good", "equivalent_good", "partial", "bad")
SCORE_MODES = ("graded", "binary")


class AdversarialProbeAccess(RuntimeError):
    """Raised when a scorer tries to consume the adversarial output probe."""


EXCEPTION_PROBE_KINDS = (
    "value-error",
    "type-error",
    "syntax-error",
    "json-decode-error",
    "runtime-error",
)
MALFORMED_PYTHON_OUTPUT = "def :\n"
MALFORMED_JSON_OUTPUT = '{"unterminated":'


class AdversarialOutputProbe:
    """Reject common value operations so evaluator error handling becomes visible.

    This is deliberately not described as guaranteed to raise inside every
    scorer. A scorer may type-check the object and return zero without touching
    it. That makes a returned zero advisory evidence consistent with swallowed
    exceptions, not proof of one.
    """

    def __init__(self, error_kind: str):
        self._error_kind = error_kind

    def _raise(self, *_args, **_kwargs):
        message = f"the evaluator consumed the {self._error_kind} output probe"
        if self._error_kind == "value-error":
            raise ValueError(message)
        if self._error_kind == "type-error":
            raise TypeError(message)
        if self._error_kind == "runtime-error":
            raise AdversarialProbeAccess(message)
        raise RuntimeError(f"unknown adversarial probe kind: {self._error_kind}")

    __str__ = _raise
    __repr__ = _raise
    __bytes__ = _raise
    __format__ = _raise
    __bool__ = _raise
    __len__ = _raise
    __iter__ = _raise
    __contains__ = _raise
    __getitem__ = _raise
    __getattr__ = _raise
    __call__ = _raise
    __eq__ = _raise
    __ne__ = _raise
    __lt__ = _raise
    __le__ = _raise
    __gt__ = _raise
    __ge__ = _raise
    __hash__ = _raise
    __int__ = _raise
    __float__ = _raise
    __index__ = _raise
    __fspath__ = _raise
    __add__ = _raise
    __radd__ = _raise
    __mul__ = _raise
    __rmul__ = _raise


class MalformedTextOutputProbe(str):
    """Malformed parser input that rejects ordinary non-parser consumption.

    ``ast.parse``/``compile`` and ``json.loads`` accept ``str`` subclasses and
    inspect the underlying text directly, so these values reach the real parser
    errors. Common classifier/exact-match operations are overridden to raise
    the corresponding family instead of looking like an ordinary wrong answer
    that correctly scored zero.
    """

    def __new__(cls, value: str, error_kind: str):
        instance = super().__new__(cls, value)
        instance._error_kind = error_kind
        return instance

    def _raise(self, *_args, **_kwargs):
        message = f"the evaluator consumed the {self._error_kind} output probe"
        if self._error_kind == "syntax-error":
            raise SyntaxError(message)
        if self._error_kind == "json-decode-error":
            raise json.JSONDecodeError(message, MALFORMED_JSON_OUTPUT, 0)
        raise RuntimeError(f"unknown malformed-text probe kind: {self._error_kind}")

    __str__ = _raise
    __repr__ = _raise
    __bytes__ = _raise
    __format__ = _raise
    __bool__ = _raise
    __len__ = _raise
    __iter__ = _raise
    __contains__ = _raise
    __getitem__ = _raise
    __eq__ = _raise
    __ne__ = _raise
    __lt__ = _raise
    __le__ = _raise
    __gt__ = _raise
    __ge__ = _raise
    __hash__ = _raise
    __add__ = _raise
    __radd__ = _raise
    __mul__ = _raise
    __rmul__ = _raise
    casefold = _raise
    lower = _raise
    upper = _raise
    strip = _raise
    lstrip = _raise
    rstrip = _raise
    split = _raise
    rsplit = _raise
    splitlines = _raise
    replace = _raise
    translate = _raise
    join = _raise
    partition = _raise
    rpartition = _raise
    find = _raise
    index = _raise
    rindex = _raise


def probe_error_text(error: BaseException) -> str:
    """Serialize a supplemental-probe error without consuming its input again."""
    try:
        detail = str(error)
    except (KeyboardInterrupt, GeneratorExit):
        raise
    except BaseException as formatting_error:  # noqa: BLE001 - defensive boundary
        detail = (
            "<message unavailable; formatting raised "
            f"{type(formatting_error).__name__}>"
        )
    return f"{type(error).__name__}: {detail}"


def exception_probe_output(kind: str) -> Any:
    """Return a stimulus that can reach the named real parser/error path.

    A custom object's dunder cannot force ``ast.parse`` or ``json.loads`` past
    their input-type guards. The malformed strings are accepted by those
    parsers and make the parser itself raise ``SyntaxError`` or
    ``JSONDecodeError``. The object probes retain the broader value/type/runtime
    coverage used by non-parser evaluators.
    """
    if kind == "syntax-error":
        return MalformedTextOutputProbe(MALFORMED_PYTHON_OUTPUT, kind)
    if kind == "json-decode-error":
        return MalformedTextOutputProbe(MALFORMED_JSON_OUTPUT, kind)
    if kind in {"value-error", "type-error", "runtime-error"}:
        return AdversarialOutputProbe(kind)
    raise ValueError(f"unknown exception probe kind: {kind}")


# A wrong answer built from the expected one by moving its tokens, keeping every
# character between them. Same multiset, same punctuation, same line breaks -
# only the binding differs, which is the class the four author-written probes
# most often miss because the author already understands the task.
#
# Deterministic on purpose: calibration is re-run and compared, so a randomly
# drawn permutation would make two runs of an unchanged evaluator disagree.
#
# It answers a question the four probes cannot: "France 2 / Italy 1" against
# "France 1 / Italy 2" is a wrong answer with an identical token bag, and an
# evaluator comparing bags scores it 1.0 while every mechanical check stays
# green (traigent-first-run#99).
TOKEN_SPLIT = re.compile(r"(\s+)")


def permuted_answer(expected: Any) -> str | None:
    """Reorder the tokens of `expected`, or None when that is not meaningful.

    Returns None rather than something arbitrary for the cases where the probe
    would prove nothing: a non-string expectation has no token order, and a
    single token or an all-identical token run has no permutation that differs
    from the original - a probe equal to the expected answer SHOULD score 1.0,
    so asking about it would manufacture a false alarm on a correct evaluator.
    """
    if not isinstance(expected, str):
        return None
    parts = TOKEN_SPLIT.split(expected)
    positions = [i for i, part in enumerate(parts) if i % 2 == 0 and part]
    if len(positions) < 2:
        return None
    tokens = [parts[i] for i in positions]
    for candidate in (tokens[::-1], tokens[1:] + tokens[:1]):
        if candidate != tokens:
            for index, value in zip(positions, candidate):
                parts[index] = value
            return "".join(parts)
    # Every token identical: any permutation is the original.
    return None


# The seam: what the evaluator is actually handed.
#
# Both probe sets above stop short of the same place. The authored four measure
# the evaluator against strings their author wrote; the generated ones are built
# from the expected answer, which the author also wrote. Neither has ever been
# through the thing that stands between the model and the evaluator - the
# agent's own reply-to-answer step. Two paid runs were lost in that gap:
#
# - An extraction step took the LAST `SELECT` in a reply, correct for a model
#   that reasons before answering and wrong for every query containing a
#   subquery, whose inner `SELECT` is always later in the string. A right answer
#   arrived at the evaluator as an unbalanced fragment over the wrong table and
#   was honestly scored 0.24. One damaged row in eighteen moved every
#   configuration by about the width of the whole spread, so the ranking was
#   wrong rather than merely low - and the probe set already CONTAINED a
#   subquery. The shape was covered on one side of the wiring and not the other.
# - A reply arrived inside a markdown code fence, which is what a chat model
#   returns for code unless it is told otherwise and sometimes even when it is,
#   and the comparison read the fence as part of the answer. Twelve
#   configurations scored 0.000, which ranks nothing.
#
# So the probes that already exist are put through the step that already exists,
# and the property is the one thing both failures broke: an answer this
# evaluator calls right must not arrive as one it calls wrong. No new fixture,
# no shape table, no provider call.
# Both authored answers this evaluator already accepted, and both are sent in
# the fenced shape rather than as written.
#
# Sending a bare answer was the defect in the first version of this check. A
# reply-transform's documented domain is "the model's reply", and for a
# fence-bound agent - one whose prompt says to answer with a ```sql block, a
# common and correct design - a bare answer is a shape it never receives. Such
# a step legitimately returns "" or raises on one, and this check reported that
# as the agent damaging a right answer. It was asserting an assumption it had
# never stated and could not support: that every reply-transform is total on
# bare text.
#
# The fence is the one shape there IS evidence for on a code task, which is the
# whole reason this finding exists. So it is the only shape sent, and no other
# task kind runs a seam probe at all: where the guide has no evidenced reply
# shape, it has nothing honest to hand a reply step.
#
# `equivalent_good` takes the second slot rather than a bare `good` taking it.
# Surface variance is exactly what a text-processing step is sensitive to - an
# extractor keyed on an upper-case keyword is correct on one authored answer and
# destructive on the lower-case variant the same model emits, and only the pair
# can see that.
SEAM_TRANSFORMED_SOURCES = ("good", "equivalent_good")
SEAM_PROBES_PER_CASE = len(SEAM_TRANSFORMED_SOURCES)
# The one shape that is not a guess, and the two kinds where it is not one.
# Armed by the run-scoped task kind readiness.py already takes, never by
# inspecting the expected answer: "this looks like SQL" is the sort of
# inference this package refuses elsewhere. Two kinds and no table of shapes -
# nobody has asked what a routing answer looks like on the wire, and a table of
# imagined shapes is the same defect as a table of imagined probes.
FENCED_PROBE_TASK_KINDS = ("code", "code-sql")
FENCED_PROBE_LANGUAGE = {"code-sql": "sql", "code": ""}
TASK_KINDS = (
    "closed-label",
    "code",
    "code-sql",
    "extraction",
    "free-text",
    "numeric",
    "routing",
    "short-answer",
    "structured",
)


def seam_probes_are_off_domain(probes: list[dict[str, Any]]) -> bool:
    """True when every probe that ran was refused, which establishes nothing.

    A refusal cannot tell "this agent's code is broken" from "this check handed
    it a shape its own contract excludes", and reporting N refusals as N
    findings picks the first reading with no evidence for it. A structured-
    output step - `json.loads(reply)["sql"]` - raises on every fenced string
    there is, correctly, because its model returns JSON; the customer would
    have met that on the pre-spend approval as a defect to settle before
    paying.

    So all-refused is reported as this check being outside its domain rather
    than as a fault. A refusal sitting among preserved probes stays a finding:
    there the step demonstrably handles this shape and failed on this content.
    """
    ran = [probe for probe in probes if probe["outcome"] != "unavailable"]
    return bool(ran) and all(probe["outcome"] == "refused" for probe in ran)


def fenced_probe_output(good: Any, task_kind: str | None) -> str | None:
    """The case's own good answer, in the shape a model would have sent it.

    Generated rather than authored, which is what makes it evidence: the
    content is an answer the authored phase has already scored, so a failure
    here cannot be the answer being wrong. Only the wrapper changed.

    `None` where there is nothing honest to build - a good probe that is not
    text, or one already carrying a fence. Fencing a list is a shape no model
    sends, and fencing something already fenced tests a string nothing will
    produce.
    """
    if task_kind not in FENCED_PROBE_TASK_KINDS:
        return None
    if not isinstance(good, str) or not good.strip():
        return None
    if "```" in good or "~~~" in good:
        return None
    # The answer verbatim, never `.strip()`ed: for a whitespace-sensitive
    # evaluator a trimmed probe differs from the authored one in two ways, and
    # this check may only ever change the wrapper.
    return f"```{FENCED_PROBE_LANGUAGE[task_kind]}\n{good}\n```"


def seam_probe_outcome(
    *,
    reference_score: float,
    score: float | None,
    error: str | None,
    unavailable: dict[str, Any] | None,
    thresholds: dict[str, float],
) -> str:
    """What one seam probe establishes, in one word.

    `damaged` is the only outcome that says anything, and it is deliberately
    one-directional: the authored phase scored this same content at or above
    the good minimum, and the delivered form no longer clears it. An answer the
    evaluator calls right, arriving as one it does not.

    The line is `good_minimum` on both sides, and getting that wrong cost this
    check the very defect it was written for. It read `score <= bad_maximum`
    first - and the truncation that prompted all of this delivered an
    unbalanced fragment a partial-credit grader scored 0.24, which is above the
    0.2 default, so the fragment came back `preserved`. `bad_maximum` could not
    be raised to cover it either: its documented job is the ceiling the
    AUTHORED matrix holds a bad probe under, and loosening that to tighten this
    pulls the calibration gate the wrong way. `good_minimum` is the only
    threshold that already means "this evaluator calls the answer right", which
    is the whole claim being made.

    A transform that merely changes the string is not damage: trimming,
    unquoting and case folding all change it and none of them changes the
    verdict, so a check on the STRING would fire on every well-behaved agent
    there is. Nor is a graded scorer nudging 1.00 to 0.90 - that answer is
    still one this evaluator accepts.
    """
    if unavailable is not None:
        return "unavailable"
    if error is not None:
        return "refused"
    if (
        score is not None
        and reference_score >= thresholds["good_minimum"]
        and score < thresholds["good_minimum"]
    ):
        return "damaged"
    return "preserved"


def literal_or_file(value: str) -> Any:
    if value.startswith("@"):
        return json.loads(Path(value[1:]).read_text())
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


# The execution-scope read, and exactly what it is allowed to conclude.
#
# The docstring at the top of this file has always said this guide does not
# calibrate a scorer whose complete path executes candidate-generated code or
# SQL. Until now that sentence was the whole of the rule: the only refusal in
# the file was `--allow-execution`, which acknowledges that importing the
# scorer is intended and says nothing whatever about what the scorer then does
# with the probe it is handed. A rule nothing executes is advice, and on a
# text-to-SQL project the card scored obedience well below the same run that
# ignored the rule - a band lower, on evidence the obedient run was forbidden
# to collect - so it was advice with a price on following it.
#
# TWO MOMENTS, TWO REASONS, and conflating them is what made the old sentence
# false. Calibration runs the four probes this guide's own matrix authors, so
# there is no model-written statement at this step at all; what it does do is
# import the scorer and let it open its engine against whatever database it is
# configured for, and that database is the project's. THAT is why calibration
# is refused outside the envelope, and it is a containment question rather than
# a claim about where the SQL came from. A TRIAL is the other moment - there the
# model writes the query and the scorer runs it - and nothing here opens it.
# Each refusal below states the reason that is true of the step it refuses.
#
# Deciding whether an arbitrary program submits its own input to an engine is
# undecidable, so this read is deliberately asymmetric and each direction is
# stated rather than implied:
#
#   * SOUND WHERE IT REFUSES. A sink on the followed path is a real call into a
#     real engine and the file, line and callee are printed, so a refusal can
#     be checked against the source rather than taken on trust.
#   * BOUNDED WHERE IT CLEARS. `no-execution-found` means "no sink on the path
#     this read could follow", never "this scorer does not execute". The card
#     records every module the read declined to open, so the size of the bound
#     is visible to whoever reads the card.
#   * FAILS CLOSED WHERE IT CANNOT READ. A call this reader cannot resolve to
#     anything - a value fetched with `getattr`, a callable pulled out of a
#     dict, a project module whose source will not parse - makes the verdict
#     `unreadable`, and `unreadable` refuses exactly as `executes` does.
#
# That last one is the point of the whole design. The recurring defect in this
# package is a check that answers a semantic question from a surface signal and
# lets its "did not find it" branch count as a pass. Here the did-not-find-it
# branch is a refusal, and `test_a_scorer_this_reader_cannot_follow_is_refused`
# proves it by handing the reader a scorer whose sink is behind dynamic
# dispatch, asserting the refusal, and then asserting that the same scorer
# really does execute its input when it is run.
#
# Failing closed is only affordable because the refusal is not a terminus:
# `--contained` runs the same probes on the same scorer inside the envelope
# below and produces the same calibration evidence. A scorer this reader cannot
# clear is routed, not stopped.
SCOPE_CLEAR = "no-execution-found"
SCOPE_EXECUTES = "executes"
SCOPE_UNREADABLE = "unreadable"

# Every call into one of these modules is treated as an execution sink. The
# list is engines, not danger in general: each one takes a string and runs it,
# which is the exact shape SKILL.md's rule is about. A module here is refused
# on any call rather than on a named attribute, because the connect call and
# the execute call belong to the same decision - a scorer that opens a database
# to grade with is the class this gate exists for, wherever it puts the verb.
EXECUTION_SINK_MODULES = frozenset(
    {
        "aiosqlite",
        "asyncpg",
        "clickhouse_connect",
        "clickhouse_driver",
        "commands",
        "ctypes",
        "cx_Oracle",
        "databricks",
        "dill",
        "duckdb",
        "importlib",
        "marshal",
        "multiprocessing",
        "MySQLdb",
        "mysql",
        "oracledb",
        "pickle",
        "presto",
        "psycopg",
        "psycopg2",
        "pty",
        "pyhive",
        "pymysql",
        "pyodbc",
        "runpy",
        "snowflake",
        "sqlalchemy",
        "sqlite3",
        "subprocess",
        "trino",
    }
)

# `os` is not an engine and most of it is path arithmetic, so it is named at
# the attribute rather than at the module: these are the members that start a
# process or replace this one.
OS_EXECUTION_ATTRIBUTES = frozenset(
    {
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "fork",
        "forkpty",
        "popen",
        "posix_spawn",
        "posix_spawnp",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "startfile",
        "system",
    }
)

# Method names that hand their argument to an engine whatever the receiver is.
# Matched on the name alone and deliberately: a cursor, a connection, a session
# and an engine are four different objects with one verb between them, and no
# static read of a project resolves which one a local variable holds. Over-
# matching here costs a refusal that `--contained` answers; under-matching
# costs the gate.
EXECUTION_SINK_METHODS = frozenset(
    {
        "exec_driver_sql",
        "execute",
        "execute_batch",
        "execute_values",
        "executemany",
        "executescript",
        "read_sql",
        "read_sql_query",
        "read_sql_table",
    }
)

# Builtins that run what they are given.
#
# `compile` and `ast.parse` are deliberately absent, and their absence is the
# rule rather than an oversight: they PARSE, they do not run, and a parser gate
# is the first half of the very method `references/evaluation-and-dataset.md`
# recommends for a code answer. Refusing them would refuse the in-scope route.
# `eval(compile(...))` and `exec(compile(...))` are still caught, at the verb
# that actually runs the object.
EXECUTION_SINK_BUILTINS = frozenset({"__import__", "eval", "exec", "execfile"})

# Builtins whose result this reader cannot follow. They are not sinks - they
# are the end of the read, which is what `unreadable` means.
OPAQUE_BUILTINS = frozenset({"getattr", "globals", "locals", "vars"})

# Builtins a scorer may call without ending the read. Everything outside this
# set that is not resolved to a definition, an import or a sink is unreadable,
# so the set is enumerated rather than guessed at from `builtins`: a name this
# reader has not thought about must not clear by default.
SAFE_BUILTINS = frozenset(
    {
        "abs",
        "all",
        "any",
        "ascii",
        "bin",
        "bool",
        "bytearray",
        "bytes",
        "callable",
        "chr",
        "classmethod",
        # PARSES its argument and hands back a code object without running it,
        # and a parser gate over the answer is the first half of the method
        # this guide recommends for a code answer. The verbs that RUN a code
        # object are `eval` and `exec`, and both are sinks above.
        "compile",
        "complex",
        "delattr",
        "dict",
        "dir",
        "divmod",
        "enumerate",
        "filter",
        "float",
        "format",
        "frozenset",
        "hash",
        "hex",
        "id",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "map",
        "max",
        "hasattr",
        "memoryview",
        "min",
        "next",
        "object",
        "oct",
        "open",
        "ord",
        "pow",
        "property",
        "setattr",
        "staticmethod",
        "super",
        "print",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "slice",
        "sorted",
        "str",
        "sum",
        "tuple",
        "type",
        "zip",
    }
)

# Exception constructors a scorer raises. Calling one is not a call this reader
# needs to follow, and refusing them would end the read inside every `raise`.
SAFE_EXCEPTION_SUFFIX = ("Error", "Exception", "Warning")

# A read that has opened this many functions has stopped being a read of one
# scorer. Exhausting it is `unreadable`, never a pass: a budget whose overrun
# clears is the same defect as a not-found branch that clears.
SCOPE_READ_BUDGET = 400

# How many sites a refusal prints before it says how many more there are.
MAX_REPORTED_SCOPE_SITES = 5


def is_safe_exception_name(name: str) -> bool:
    """Whether calling this name raises rather than runs something.

    The builtin half is exact - `KeyboardInterrupt` and `SystemExit` carry no
    suffix, and a scorer that raises one is doing control flow. The suffix half
    is the bound, and it is narrow on purpose: a name this read could not
    resolve which is spelled like an exception is treated as one rather than
    ending the read inside every `raise` a project writes.
    """
    builtin = getattr(builtins, name, None)
    if isinstance(builtin, type) and issubclass(builtin, BaseException):
        return True
    return name[:1].isupper() and name.endswith(SAFE_EXCEPTION_SUFFIX)


class ModuleRead:
    """One parsed project file, and the names its top level binds."""

    def __init__(self, path: Path, tree: ast.Module) -> None:
        self.path = path
        self.tree = tree
        self.functions: dict[str, ast.AST] = {}
        self.classes: dict[str, ast.ClassDef] = {}
        # name -> dotted module it stands for, for `import x` / `import x as y`
        self.module_aliases: dict[str, str] = {}
        # name -> (dotted module, attribute) for `from m import n [as a]`
        self.imported_names: dict[str, tuple[str, str]] = {}
        self.star_imports: list[ast.ImportFrom] = []
        self.bound_values: set[str] = set()
        # name -> the module-level call that built it, so `STORE.rows(sql)` can
        # be followed into the class `STORE` was constructed from. Without this
        # the read cleared a scorer whose engine sat one attribute away: the
        # receiver was unresolvable, the method name was not one of the engine
        # verbs, and "could not follow it" quietly counted as "found nothing".
        self.instance_sources: dict[str, ast.Call] = {}
        self.top_level: list[ast.AST] = []
        for statement in tree.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[statement.name] = statement
                continue
            if isinstance(statement, ast.ClassDef):
                self.classes[statement.name] = statement
                continue
            self.top_level.append(statement)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.module_aliases[alias.asname or alias.name.split(".")[0]] = (
                        alias.name
                    )
            elif isinstance(node, ast.ImportFrom):
                if any(alias.name == "*" for alias in node.names):
                    self.star_imports.append(node)
                    continue
                module = "." * node.level + (node.module or "")
                for alias in node.names:
                    self.imported_names[alias.asname or alias.name] = (
                        module,
                        alias.name,
                    )
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    for name in ast.walk(target):
                        if isinstance(name, ast.Name):
                            self.bound_values.add(name.id)
                if isinstance(node.value, ast.Call) and len(node.targets) == 1:
                    target = node.targets[0]
                    if isinstance(target, ast.Name):
                        self.instance_sources[target.id] = node.value
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                if isinstance(node.target, ast.Name):
                    self.bound_values.add(node.target.id)


def attribute_root(node: ast.Attribute) -> str | None:
    """The leftmost `Name` of a dotted attribute chain, if it is one."""
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def local_bindings(node: ast.AST) -> tuple[dict[str, ast.AST], set[str]]:
    """Names a function body binds: nested definitions, and everything else."""
    definitions: dict[str, ast.AST] = {}
    values: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions[child.name] = child
        elif isinstance(child, ast.ClassDef):
            values.add(child.name)
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        values.add(name.id)
        elif isinstance(child, (ast.AnnAssign, ast.AugAssign)):
            if isinstance(child.target, ast.Name):
                values.add(child.target.id)
        elif isinstance(child, (ast.For, ast.AsyncFor, ast.comprehension)):
            for name in ast.walk(child.target):
                if isinstance(name, ast.Name):
                    values.add(name.id)
        elif isinstance(child, ast.arg):
            values.add(child.arg)
        elif isinstance(child, (ast.withitem,)):
            if child.optional_vars is not None:
                for name in ast.walk(child.optional_vars):
                    if isinstance(name, ast.Name):
                        values.add(name.id)
    return definitions, values


class ExecutionScopeReader:
    """Read a scorer's reachable project path for calls into an engine."""

    def __init__(self, import_root: Path, scorer_directory: Path) -> None:
        # The two directories the child puts on `sys.path`, in the same order,
        # so what this reader calls "the project" is exactly what the child
        # will be able to import.
        self.roots = [import_root.resolve(), scorer_directory.resolve()]
        self.sinks: list[dict[str, Any]] = []
        self.unreadable: list[dict[str, Any]] = []
        self.not_followed: set[str] = set()
        self.reads: dict[str, ModuleRead | None] = {}
        self.visited: set[tuple[str, str]] = set()
        self.opened = 0
        # The class whose method is currently being read, so `self.helper()`
        # resolves. `None` at module level and inside a plain function.
        self.owner: tuple[ModuleRead, ast.ClassDef] | None = None

    # -- recording ---------------------------------------------------------
    def record_sink(self, path: Path, node: ast.AST, detail: str) -> None:
        self.sinks.append(
            {
                "file": str(path),
                "line": getattr(node, "lineno", 0),
                "detail": detail,
            }
        )

    def record_unreadable(self, path: Path, node: ast.AST, detail: str) -> None:
        self.unreadable.append(
            {
                "file": str(path),
                "line": getattr(node, "lineno", 0),
                "detail": detail,
            }
        )

    # -- resolution --------------------------------------------------------
    def project_module_path(self, dotted: str, relative_to: Path) -> Path | None:
        """Where a dotted module lives inside the project, or None."""
        if not dotted:
            return None
        if dotted.startswith("."):
            stripped = dotted.lstrip(".")
            base = relative_to.parent
            for _ in range(len(dotted) - len(stripped) - 1):
                base = base.parent
            candidates = [base]
            parts = stripped.split(".") if stripped else []
        else:
            candidates = list(self.roots)
            parts = dotted.split(".")
        for base in candidates:
            if not parts:
                continue
            module_file = base.joinpath(*parts).with_suffix(".py")
            package_file = base.joinpath(*parts, "__init__.py")
            for candidate in (module_file, package_file):
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                if resolved.is_file():
                    return resolved
        return None

    def resolve_class(
        self, read: ModuleRead, call: ast.Call
    ) -> "tuple[ModuleRead, ast.ClassDef] | None":
        """The project class a module-level construction call names, if any.

        Deliberately returns None for anything outside the project rather than
        guessing. `WHITESPACE = re.compile(...)` is not a project object, and
        treating every unresolvable construction as unreadable would refuse the
        most ordinary scorer there is.
        """
        callee = call.func
        if isinstance(callee, ast.Name):
            name = callee.id
            if name in read.classes:
                return (read, read.classes[name])
            if name in read.imported_names:
                module, attribute = read.imported_names[name]
                return self.class_in_project_module(read, module, attribute)
            return None
        if isinstance(callee, ast.Attribute):
            root = attribute_root(callee)
            if root is not None and root in read.module_aliases:
                return self.class_in_project_module(
                    read, read.module_aliases[root], callee.attr
                )
        return None

    def class_in_project_module(
        self, read: ModuleRead, dotted: str, name: str
    ) -> "tuple[ModuleRead, ast.ClassDef] | None":
        path = self.project_module_path(dotted, read.path)
        if path is None:
            return None
        imported = self.read_module(path)
        if imported is None or name not in imported.classes:
            return None
        return (imported, imported.classes[name])

    def class_method(
        self, read: ModuleRead, node: ast.ClassDef, name: str
    ) -> ast.AST | None:
        """A method of this class, following bases this read can resolve."""
        for statement in node.body:
            if (
                isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                and statement.name == name
            ):
                return statement
        for base in node.bases:
            resolved: tuple[ModuleRead, ast.ClassDef] | None = None
            if isinstance(base, ast.Name) and base.id in read.classes:
                resolved = (read, read.classes[base.id])
            elif isinstance(base, ast.Name) and base.id in read.imported_names:
                module, attribute = read.imported_names[base.id]
                resolved = self.class_in_project_module(read, module, attribute)
            if resolved is None:
                continue
            base_read, base_class = resolved
            if base_class is node:
                continue
            found = self.class_method(base_read, base_class, name)
            if found is not None:
                return found
        return None

    def read_module(self, path: Path) -> ModuleRead | None:
        key = str(path)
        if key in self.reads:
            return self.reads[key]
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=key)
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as error:
            self.reads[key] = None
            self.unreadable.append(
                {
                    "file": key,
                    "line": 0,
                    "detail": (f"the source could not be read: {type(error).__name__}"),
                }
            )
            return None
        read = ModuleRead(path, tree)
        self.reads[key] = read
        for star in read.star_imports:
            self.record_unreadable(
                path,
                star,
                "`from ... import *` hides which names this file binds",
            )
        return read

    # -- walking -----------------------------------------------------------
    def walk_module_top_level(self, read: ModuleRead) -> None:
        """A module's top level runs on import, so it is on the path too."""
        key = (str(read.path), "<module>")
        if key in self.visited:
            return
        self.visited.add(key)
        for statement in read.top_level:
            self.walk_body(read, statement, {}, set())
        for dotted in list(read.module_aliases.values()) + [
            module for module, _ in read.imported_names.values()
        ]:
            path = self.project_module_path(dotted, read.path)
            if path is None:
                continue
            imported = self.read_module(path)
            if imported is not None:
                self.walk_module_top_level(imported)

    def walk_function(
        self,
        read: ModuleRead,
        node: ast.AST,
        name: str,
        owner: "tuple[ModuleRead, ast.ClassDef] | None" = None,
    ) -> None:
        key = (str(read.path), name)
        if key in self.visited:
            return
        self.visited.add(key)
        self.opened += 1
        if self.opened > SCOPE_READ_BUDGET:
            self.record_unreadable(
                read.path,
                node,
                f"the read passed {SCOPE_READ_BUDGET} functions and stopped",
            )
            return
        definitions, values = local_bindings(node)
        previous_owner = self.owner
        if owner is not None:
            self.owner = owner
        try:
            self.walk_body(read, node, definitions, values)
        finally:
            self.owner = previous_owner

    def walk_body(
        self,
        read: ModuleRead,
        node: ast.AST,
        definitions: dict[str, ast.AST],
        values: set[str],
    ) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                self.classify_call(read, child, definitions, values)

    def classify_call(
        self,
        read: ModuleRead,
        call: ast.Call,
        definitions: dict[str, ast.AST],
        values: set[str],
    ) -> None:
        callee = call.func
        if isinstance(callee, ast.Name):
            self.classify_name_call(read, call, callee, definitions, values)
            return
        if isinstance(callee, ast.Attribute):
            self.classify_attribute_call(read, call, callee)
            return
        # A call of a call, of a subscript, of a lambda. There is no name to
        # resolve, so the read ends here rather than passing.
        self.record_unreadable(
            read.path,
            call,
            f"a call through {type(callee).__name__} cannot be resolved to a "
            "definition",
        )

    def classify_name_call(
        self,
        read: ModuleRead,
        call: ast.Call,
        callee: ast.Name,
        definitions: dict[str, ast.AST],
        values: set[str],
    ) -> None:
        name = callee.id
        if name in EXECUTION_SINK_BUILTINS:
            self.record_sink(read.path, call, f"{name}() runs what it is given")
            return
        if name in OPAQUE_BUILTINS:
            self.record_unreadable(
                read.path, call, f"{name}() returns something this read cannot follow"
            )
            return
        if name in definitions:
            self.walk_function(read, definitions[name], f"{name}#{callee.lineno}")
            return
        if name in read.functions:
            self.walk_function(read, read.functions[name], name)
            return
        if name in read.classes:
            initializer = next(
                (
                    statement
                    for statement in read.classes[name].body
                    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and statement.name == "__init__"
                ),
                None,
            )
            if initializer is not None:
                self.walk_function(read, initializer, f"{name}.__init__")
            return
        if name in read.imported_names:
            module, attribute = read.imported_names[name]
            self.follow_import(read, call, module, attribute)
            return
        if name in read.module_aliases:
            self.classify_module_use(
                read, call, read.module_aliases[name], name, follow=True
            )
            return
        if name in SAFE_BUILTINS or is_safe_exception_name(name):
            return
        if name in values:
            self.record_unreadable(
                read.path,
                call,
                f"{name!r} is a value this read cannot resolve to a definition",
            )
            return
        self.record_unreadable(
            read.path, call, f"{name!r} is not bound by anything this read can see"
        )

    def classify_attribute_call(
        self, read: ModuleRead, call: ast.Call, callee: ast.Attribute
    ) -> None:
        attribute = callee.attr
        if attribute in EXECUTION_SINK_METHODS:
            self.record_sink(
                read.path,
                call,
                f".{attribute}() submits its argument to an engine",
            )
            return
        root = attribute_root(callee)
        if root is None:
            # A method on an expression. The receiver is unknown and the name
            # is not one of the engine verbs, so this is the bound rather than
            # the end of the read - recorded, and stated on the card.
            self.not_followed.add(f".{attribute}")
            return
        if root in read.module_aliases:
            self.classify_module_use(
                read, call, read.module_aliases[root], attribute, follow=True
            )
            return
        if root in read.imported_names:
            module, name = read.imported_names[root]
            self.classify_module_use(read, call, module, f"{name}.{attribute}")
            return
        # Only a one-level receiver is resolved. `self.spaces.sub(...)` has
        # `self` at the root of its chain but `sub` belongs to `self.spaces`,
        # and looking `sub` up on the enclosing class would refuse an entirely
        # ordinary scorer for not having a method it never claimed to have.
        direct = isinstance(callee.value, ast.Name)
        if root == "self" and direct:
            if self.owner is None:
                self.not_followed.add(f"self.{attribute}")
                return
            owner_read, owner_class = self.owner
            method = self.class_method(owner_read, owner_class, attribute)
            if method is None:
                self.record_unreadable(
                    read.path,
                    call,
                    f"self.{attribute}() is not a method of "
                    f"{owner_class.name}, so this read cannot say what it calls",
                )
                return
            self.walk_function(
                owner_read,
                method,
                f"{owner_class.name}.{attribute}",
                owner=(owner_read, owner_class),
            )
            return
        if direct and root in read.instance_sources:
            owner = self.resolve_class(read, read.instance_sources[root])
            if owner is not None:
                owner_read, owner_class = owner
                method = self.class_method(owner_read, owner_class, attribute)
                if method is None:
                    self.record_unreadable(
                        read.path,
                        call,
                        f"{root}.{attribute}() is not a method of "
                        f"{owner_class.name}, which {root} was built from",
                    )
                    return
                self.walk_function(
                    owner_read,
                    method,
                    f"{owner_class.name}.{attribute}",
                    owner=(owner_read, owner_class),
                )
                return
        self.not_followed.add(f"{root}.{attribute}")

    def classify_module_use(
        self,
        read: ModuleRead,
        call: ast.Call,
        dotted: str,
        attribute: str,
        *,
        follow: bool = False,
    ) -> None:
        head = dotted.lstrip(".").split(".")[0]
        if head in EXECUTION_SINK_MODULES:
            self.record_sink(
                read.path, call, f"{dotted}.{attribute}() calls into {head}"
            )
            return
        if head == "os" and attribute.split(".")[-1] in OS_EXECUTION_ATTRIBUTES:
            self.record_sink(read.path, call, f"os.{attribute}() starts a process")
            return
        path = self.project_module_path(dotted, read.path)
        if path is None:
            self.not_followed.add(dotted or "<relative>")
            return
        imported = self.read_module(path)
        if imported is None:
            return
        self.walk_module_top_level(imported)
        if not follow:
            return
        target = attribute.split(".")[0]
        if target in imported.functions:
            self.walk_function(imported, imported.functions[target], target)
        elif target in imported.classes:
            self.not_followed.add(f"{dotted}.{target}")

    def follow_import(
        self, read: ModuleRead, call: ast.Call, module: str, attribute: str
    ) -> None:
        self.classify_module_use(read, call, module, attribute, follow=True)

    # -- verdict -----------------------------------------------------------
    def verdict(self) -> str:
        if self.sinks:
            return SCOPE_EXECUTES
        if self.unreadable:
            return SCOPE_UNREADABLE
        return SCOPE_CLEAR


def execution_scope_scan(
    scorer_file: Path, scorer_name: str, import_root: Path
) -> dict[str, Any]:
    """Read the scorer's reachable project path without importing anything."""
    scorer_file = Path(scorer_file).resolve()
    reader = ExecutionScopeReader(Path(import_root), scorer_file.parent)
    read = reader.read_module(scorer_file)
    if read is not None:
        reader.walk_module_top_level(read)
        if scorer_name in read.functions:
            reader.walk_function(read, read.functions[scorer_name], scorer_name)
        elif scorer_name in read.classes:
            # `load_function` accepts any callable, and a class is one. Read the
            # two members calling it would run.
            owner = (read, read.classes[scorer_name])
            for member in ("__init__", "__call__"):
                method = reader.class_method(read, read.classes[scorer_name], member)
                if method is not None:
                    reader.walk_function(
                        read, method, f"{scorer_name}.{member}", owner=owner
                    )
        else:
            # The callable the run named is not a module-level definition in
            # the file it named. Whatever it is - an attribute of an object, a
            # name bound at import, a re-export - this read cannot open it, and
            # not opening it is not a pass.
            reader.unreadable.append(
                {
                    "file": str(scorer_file),
                    "line": 0,
                    "detail": (
                        f"{scorer_name!r} is not a function defined at the top "
                        "level of this file, so its body was never read"
                    ),
                }
            )
    return {
        "verdict": reader.verdict(),
        "sinks": reader.sinks,
        "unreadable": reader.unreadable,
        "not_followed": sorted(reader.not_followed),
        "functions_read": reader.opened,
        "files_read": sorted(key for key, value in reader.reads.items() if value),
    }


def scope_refusal_message(scan: dict[str, Any]) -> str:
    """What to print when the read will not clear the scorer for plain probes."""
    if scan["verdict"] == SCOPE_EXECUTES:
        head = (
            "Refusing to calibrate this scorer here: calling it opens an engine "
            "and runs statements against whatever that engine is pointed at. "
            "The probes are this guide's own authored pairs, so nothing the "
            "model wrote runs at this step - what is unbounded is the target, "
            "and a first run does not grade against a database it cannot "
            "bound."
        )
        sites = scan["sinks"]
    else:
        head = (
            "Refusing to calibrate this scorer here: this read could not follow "
            "its complete path to the end, so whether calling it reaches an "
            "engine is unsettled - and an unread path is not a cleared one."
        )
        sites = scan["unreadable"]
    lines = [head, ""]
    for site in sites[:MAX_REPORTED_SCOPE_SITES]:
        lines.append(f"  {site['file']}:{site['line']}: {site['detail']}")
    remaining = len(sites) - MAX_REPORTED_SCOPE_SITES
    if remaining > 0:
        lines.append(f"  ... and {remaining} more")
    lines.extend(
        [
            "",
            "Re-run with --contained to take the same authored probes through "
            "the containment envelope, which bounds the target: the network "
            "closed, subprocesses refused, sqlite opened read-only under a "
            "step budget, and cpu and file writes held down - with the card "
            "recording what was enforced. Point it at a disposable schema this "
            "run built, never at a database the project depends on. Or declare "
            "the refusal to readiness.py with --calibration-scope-refused and "
            "settle it through the containment review in "
            "references/run-safety.md.",
            "",
            "This refusal is about calibration only. A trial, where the model "
            "writes the query and this scorer runs it, is the other moment and "
            "no route here opens it.",
        ]
    )
    return "\n".join(lines)


# The containment envelope, and why a route had to exist before the gate could
# be enforced.
#
# `SKILL.md` forbids running a scorer that executes candidate-generated code or
# SQL, and `references/run-safety.md` used to end the guide there. That is the
# right instinct about the danger - executing model-written SQL against a
# customer's live database in their first ten minutes is genuinely dangerous -
# and the wrong terminus, because the calibration sub-score and the probe
# spread are the only checks in this package that separate a scorer which
# grades from one which does not, and a text-to-SQL project could not reach
# either of them, so a query-log project that obeyed the rule sat a band below
# the identical project that ignored it, and the whole of the difference was
# the one check the rule forbade. A safety rule that costs a band is a rule
# with a price on obedience, and the only thing between a user and that band
# was whether they read the sentence. The figures behind this are in the
# pull request that added the route; they came from a project fixture rather
# than from this tree, so they are not restated here as if they could be taken
# again from it.
#
# So this is the same probes, on the same scorer, inside an envelope this file
# builds and then ATTESTS. The attestation is the load-bearing part: it is
# produced by the tool from what it actually installed, never declared by the
# run, which is what makes a contained calibration evidence rather than a
# claim. A declaration verified against nothing must not pay, and this one is
# not a declaration.
#
# What the envelope closes, and what it does not:
#
#   * THE NETWORK, completely, at the socket layer. This is the half that
#     matters most, and it is why containment is worth the code: a production
#     database, a warehouse, an internal API and a metadata service are all
#     unreachable BY CONSTRUCTION from inside the envelope, whatever the
#     scorer's connection string says. The proxy environment variables the
#     deterministic path already set are not this - a direct `socket.connect`
#     walks straight past them.
#   * SUBPROCESSES, so a scorer cannot step outside the envelope by starting a
#     process that is not in it.
#   * SQLITE, opened read-only and given a step budget, because sqlite is the
#     engine a disposable schema is actually built in and it is the one whose
#     read-only mode this can express. `mode=ro` is enforced by the engine, not
#     by us: a candidate `DROP TABLE` fails inside sqlite.
#   * CPU AND FILE WRITES, through the process limits the platform offers.
#
#   * NOT memory, and not the filesystem beyond a write size. `RLIMIT_AS`
#     breaks ordinary scientific stacks at import, and this envelope has to be
#     usable by the projects it is for. Said here rather than implied by
#     silence, and said on the card too.
#   * NOT a sandbox in the isolation sense. Process separation was never one -
#     the module docstring has said so from the start - and adding four locks
#     to it does not make it one. What it is, is a bounded envelope whose
#     bounds are enumerated, enforced, and printed.
class ContainmentRefusal(RuntimeError):
    """Raised inside the envelope when the scorer reaches past its bounds."""


# Ten million sqlite virtual-machine instructions. A grading query over a
# disposable first-run schema is thousands; a cartesian product over the same
# schema passes this in well under a second of CPU. It bounds the runaway
# without bounding the work, which is the only thing a step budget can honestly
# claim to do.
SQLITE_STEP_BUDGET = 10_000_000
# How often sqlite asks the handler, in virtual-machine instructions. Small
# enough that a runaway is stopped promptly, large enough that the callback is
# not the cost.
SQLITE_PROGRESS_INTERVAL = 100_000
# Sixty-four mebibytes of writes. A disposable schema and its journals fit; a
# scorer filling the disk does not.
CONTAINED_FILE_BYTES = 64 * 1024 * 1024


def close_network(report: dict[str, Any]) -> None:
    """Refuse every outbound connection, at the socket layer."""
    import socket

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise ContainmentRefusal(
            "the containment envelope closed the network; this scorer tried to "
            "open a connection"
        )

    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.socket.sendto = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse
    if hasattr(socket, "create_server"):
        socket.create_server = refuse
    report["network"] = "closed at the socket layer"


def close_subprocesses(report: dict[str, Any]) -> None:
    """Refuse every way of starting a process that is not inside the envelope."""

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise ContainmentRefusal(
            "the containment envelope refuses subprocesses; this scorer tried "
            "to start a process outside it"
        )

    subprocess.Popen = refuse
    subprocess.run = refuse
    subprocess.call = refuse
    subprocess.check_call = refuse
    subprocess.check_output = refuse
    closed = []
    for attribute in sorted(OS_EXECUTION_ATTRIBUTES):
        if hasattr(os, attribute):
            setattr(os, attribute, refuse)
            closed.append(attribute)
    report["subprocess"] = "refused (subprocess, os." + ", os.".join(closed) + ")"


def contain_sqlite(report: dict[str, Any]) -> None:
    """Open every sqlite database read-only, under a step budget."""
    try:
        import sqlite3
    except ImportError:  # pragma: no cover - sqlite3 is in every CPython build
        report["sqlite"] = "not available in this interpreter"
        return

    class ContainedCursor(sqlite3.Cursor):
        def execute(self, *arguments: Any, **keywords: Any) -> Any:
            self.connection.reset_step_budget()
            return super().execute(*arguments, **keywords)

        def executemany(self, *arguments: Any, **keywords: Any) -> Any:
            self.connection.reset_step_budget()
            return super().executemany(*arguments, **keywords)

        def executescript(self, *arguments: Any, **keywords: Any) -> Any:
            self.connection.reset_step_budget()
            return super().executescript(*arguments, **keywords)

    # ATTACH is the escape a read-only main database does not close: the
    # connection is opened `mode=ro`, and the scorer attaches a second file it
    # creates and writes freely. Measured, not assumed - an attaching scorer
    # created and populated a side database from inside the first version of
    # this envelope, and the run exited 0. sqlite's own authorizer is the right
    # instrument, because it refuses inside the engine rather than by pattern-
    # matching the statement.
    attach_actions = tuple(
        value
        for value in (
            getattr(sqlite3, "SQLITE_ATTACH", 24),
            getattr(sqlite3, "SQLITE_DETACH", 25),
        )
    )

    def refuse_attach(action: int, *_details: Any) -> int:
        if action in attach_actions:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    class ContainedConnection(sqlite3.Connection):
        def __init__(self, *arguments: Any, **keywords: Any) -> None:
            super().__init__(*arguments, **keywords)
            self._steps_left = SQLITE_STEP_BUDGET
            sqlite3.Connection.set_progress_handler(
                self, self._step, SQLITE_PROGRESS_INTERVAL
            )
            sqlite3.Connection.set_authorizer(self, refuse_attach)

        # A bound the scorer can lift is not a bound. Both hooks are the
        # envelope's, and the connection refuses to hand them back.
        def set_authorizer(self, *_arguments: Any, **_keywords: Any) -> None:
            raise ContainmentRefusal(
                "the containment envelope owns this connection's authorizer; "
                "this scorer tried to replace it"
            )

        def set_progress_handler(self, *_arguments: Any, **_keywords: Any) -> None:
            raise ContainmentRefusal(
                "the containment envelope owns this connection's step budget; "
                "this scorer tried to replace it"
            )

        def _step(self) -> int:
            self._steps_left -= SQLITE_PROGRESS_INTERVAL
            # A non-zero return aborts the statement sqlite is running. The
            # scorer sees an OperationalError, which is the same shape a
            # malformed query already gives it.
            return 1 if self._steps_left <= 0 else 0

        def reset_step_budget(self) -> None:
            self._steps_left = SQLITE_STEP_BUDGET

        def cursor(self, factory: Any = None) -> Any:
            return super().cursor(factory or ContainedCursor)

        def execute(self, *arguments: Any, **keywords: Any) -> Any:
            self.reset_step_budget()
            return super().execute(*arguments, **keywords)

        def executemany(self, *arguments: Any, **keywords: Any) -> Any:
            self.reset_step_budget()
            return super().executemany(*arguments, **keywords)

        def executescript(self, *arguments: Any, **keywords: Any) -> Any:
            self.reset_step_budget()
            return super().executescript(*arguments, **keywords)

    real_connect = sqlite3.connect
    # `sqlite3/__init__.py` re-exports from `sqlite3.dbapi2`, so replacing one
    # name leaves the other pointing at the unpatched function. Also measured:
    # a scorer calling `sqlite3.dbapi2.connect` walked straight past the first
    # version of this envelope.
    dbapi = sys.modules.get("sqlite3.dbapi2")

    def contained_connect(database: Any, *arguments: Any, **keywords: Any) -> Any:
        keywords.setdefault("factory", ContainedConnection)
        own_factory = keywords["factory"] is ContainedConnection
        target = database
        if isinstance(database, (str, os.PathLike)):
            text = os.fspath(database)
            if text == ":memory:" or text == "":
                pass
            elif text.startswith("file:"):
                target = read_only_uri(text)
                keywords["uri"] = True
            else:
                target = read_only_uri(
                    "file:" + urllib.parse.quote(str(Path(text).resolve()))
                )
                keywords["uri"] = True
        connection = real_connect(target, *arguments, **keywords)
        if not own_factory and hasattr(connection, "set_progress_handler"):
            # The caller brought its own connection class, so the per-statement
            # reset above is not in play. The budget still bounds the
            # connection, and the card says which of the two applied rather
            # than reporting the stronger one.
            budget = {"left": SQLITE_STEP_BUDGET}

            def step() -> int:
                budget["left"] -= SQLITE_PROGRESS_INTERVAL
                return 1 if budget["left"] <= 0 else 0

            connection.set_progress_handler(step, SQLITE_PROGRESS_INTERVAL)
            connection.set_authorizer(refuse_attach)
            report["sqlite"] = (
                "read-only where the path is a file; attach refused; "
                f"{SQLITE_STEP_BUDGET} step budget per connection "
                "(the caller supplied its own connection factory, so the "
                "budget is not reset per statement and the hooks are "
                "replaceable)"
            )
        return connection

    sqlite3.connect = contained_connect
    if dbapi is not None:
        dbapi.connect = contained_connect
    report["sqlite"] = (
        "read-only where the path is a file; attach refused; "
        f"{SQLITE_STEP_BUDGET} step budget per statement"
    )


def read_only_uri(uri: str) -> str:
    """Force `mode=ro` into a sqlite file URI, replacing any mode it carries."""
    base, separator, query = uri.partition("?")
    parameters = [
        pair for pair in query.split("&") if pair and not pair.startswith("mode=")
    ]
    parameters.append("mode=ro")
    del separator
    return base + "?" + "&".join(parameters)


def bound_resources(report: dict[str, Any], cpu_seconds: int) -> None:
    """Apply the process limits this platform offers, and say which took."""
    try:
        import resource
    except ImportError:  # pragma: no cover - Windows has no resource module
        report["resources"] = "not available on this platform"
        return
    applied = []
    for name, limit in (
        ("RLIMIT_CPU", cpu_seconds),
        ("RLIMIT_FSIZE", CONTAINED_FILE_BYTES),
    ):
        constant = getattr(resource, name, None)
        if constant is None:
            continue
        try:
            soft, hard = resource.getrlimit(constant)
            ceiling = limit if hard in (resource.RLIM_INFINITY,) else min(limit, hard)
            resource.setrlimit(constant, (ceiling, hard))
        except (ValueError, OSError):
            continue
        applied.append(f"{name}={ceiling}")
        del soft
    report["resources"] = ", ".join(applied) if applied else "none could be applied"
    # Named because it is absent, not because it is present. A memory ceiling
    # breaks ordinary numeric stacks at import, and an envelope its own users
    # cannot load is not containment.
    report["not_bounded"] = (
        "address space, the filesystem beyond write size, and native code "
        "reached through ctypes"
    )


def apply_containment(cpu_seconds: int) -> dict[str, Any]:
    """Close the envelope, and return exactly what closed."""
    report: dict[str, Any] = {"mode": "contained"}
    close_network(report)
    close_subprocesses(report)
    contain_sqlite(report)
    bound_resources(report, cpu_seconds)
    return report


def subprocess_environment(allow_provider_access: bool) -> dict[str, str]:
    if allow_provider_access:
        environment = dict(os.environ)
    else:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not any(marker in key.upper() for marker in SECRET_MARKERS)
        }
        environment.update(
            {
                "HTTP_PROXY": "http://127.0.0.1:9",
                "HTTPS_PROXY": "http://127.0.0.1:9",
                "ALL_PROXY": "http://127.0.0.1:9",
                "NO_PROXY": "",
            }
        )
    environment.update(
        {
            "TRAIGENT_OFFLINE_MODE": "true",
            "LITELLM_LOCAL_MODEL_COST_MAP": "true",
        }
    )
    return environment


def load_function(spec: str):
    file_part, separator, name = spec.partition(":")
    if not separator or not name:
        raise ValueError("--scorer must use FILE.py:FUNCTION")
    path = Path(file_part).resolve()
    module_spec = importlib.util.spec_from_file_location(path.stem, path)
    if module_spec is None or module_spec.loader is None:
        raise ValueError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    function = getattr(module, name, None)
    if not callable(function):
        raise ValueError(f"{path} has no callable '{name}'")
    return function


async def await_metric_value(value: Any) -> Any:
    return await value


def bind_call(
    function,
    output: Any,
    expected: Any,
    input_data: Any,
    metadata: Any,
) -> float:
    """Call the skill-owned calibration-adapter contract and validate its score."""
    arguments = {
        "output": output,
        "expected": expected,
        "input_data": input_data,
        "metadata": metadata or {},
    }
    try:
        inspect.signature(function).bind(**arguments)
    except (TypeError, ValueError) as error:
        raise TypeError(
            "calibration adapter must accept keyword arguments "
            "output, expected, input_data, and metadata; create a thin adapter "
            "instead of relying on SDK callback aliases"
        ) from error
    raw_score = function(**arguments)
    if inspect.isawaitable(raw_score):
        raw_score = asyncio.run(await_metric_value(raw_score))
    try:
        score = float(raw_score)
    except (TypeError, ValueError) as error:
        raise TypeError(
            "score contract requires a numeric normalized higher-is-better value "
            f"in [0,1]; got {type(raw_score).__name__}"
        ) from error
    if not math.isfinite(score):
        raise ValueError(
            "score contract requires a finite normalized higher-is-better value "
            f"in [0,1]; got {score!r}"
        )
    if not 0.0 <= score <= 1.0:
        raise ValueError(
            "score contract requires a normalized higher-is-better value in [0,1]; "
            f"got {score!r}"
        )
    return score


def run_worker() -> int:
    # Named before the read, so the failure path can say which component failed
    # even when the read itself is what failed.
    operation = "authored"
    try:
        request = json.load(sys.stdin)
        operation = request.get("operation", "authored")
        # The acknowledgement, enforced HERE and not only in the parent.
        #
        # `run()` dispatches on `--_worker` before `parse_args()`, so this
        # process - the only one that ever imports the scorer - never evaluated
        # `--allow-execution` at all. The parent checked it once and every
        # child was trusted because only this file spawns them, which makes the
        # enforcement surface narrower than the flag's own help implies. The
        # request now carries the acknowledgement and the containment state,
        # and a request that carries neither is refused before anything is
        # imported. It does not make the child unforgeable by whoever writes
        # its stdin; what it does is stop the executing process from taking its
        # authorization on trust from its own command line.
        if not request.get("allow_execution"):
            raise ValueError(
                "this worker imports and executes the scorer, and the request "
                "does not carry the --allow-execution acknowledgement"
            )
        if request.get("contained"):
            containment_report = apply_containment(
                int(request.get("cpu_seconds", CALIBRATION_TIMEOUT_CEILING_SECONDS))
            )
        else:
            containment_report = None
        import_root = Path(request["import_root"])
        scorer_file = Path(request["scorer"].partition(":")[0]).resolve()
        import_paths = [str(import_root), str(scorer_file.parent)]
        sys.path[:] = import_paths + [
            path for path in sys.path if path not in import_paths
        ]
        captured_stdout = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout):
            # Read the operation FIRST, and load the scorer only for the
            # operations that score something. `load` checks the reply
            # transform and grades nothing, so loading the scorer there made a
            # broken scorer surface as "--reply-transform could not be loaded",
            # naming a correct flag and telling the assistant to fix it - while
            # the scorer's own failure has an exit code and a message of its
            # own that it must be allowed to reach.
            function = None if operation == "load" else load_function(request["scorer"])
            if operation == "authored":
                case_results = []
                for case in request["cases"]:
                    scores = {
                        label: bind_call(
                            function,
                            value,
                            case["expected"],
                            case.get("input_data"),
                            case.get("metadata"),
                        )
                        for label, value in case["probes"].items()
                    }
                    case_results.append({"name": case["name"], "scores": scores})
                response = {"cases": case_results}
            elif operation == "seam":
                # Every seam probe for every case, in ONE child. The
                # supplemental families above get a fresh interpreter each
                # because they are adversarial - malformed output, raised
                # exceptions, a probe object that refuses to be consumed - and
                # process-local state from one must not reach the next. A seam
                # probe is an ordinary string through ordinary code, and the
                # authored phase, which decides PASS, already scores every case
                # in one child for that reason.
                #
                # The cost of not doing this was measured rather than guessed:
                # the customer's agent module was imported once per probe, and
                # since the guidance this change adds says that module's top
                # level "for an agent file is commonly a provider client", a
                # client constructor ran on every one. Under a tight budget the
                # permutation probe and all five exception probes of the second
                # case came back `budget-exhausted` with the flag and did not
                # without it - the starvation the queue reorder had just
                # removed, coming back through the clock instead of the queue.
                transform = (
                    load_function(request["reply_transform"])
                    if request.get("reply_transform")
                    else None
                )
                seam_results = []
                for probe in request["probes"]:
                    output = probe["output"]
                    delivered = None
                    score = None
                    error_text = None
                    try:
                        if transform is not None:
                            # Inside this try with the scoring call, on purpose:
                            # a transform that raises on a probe IS the finding.
                            output = transform(output)
                            delivered = (
                                output if isinstance(output, str) else repr(output)
                            )
                        score = bind_call(
                            function,
                            output,
                            probe["expected"],
                            probe.get("input_data"),
                            probe.get("metadata"),
                        )
                    except (KeyboardInterrupt, GeneratorExit):
                        raise
                    except BaseException as error:  # a refusal is the evidence
                        error_text = probe_error_text(error)
                    seam_results.append(
                        {
                            "case_index": probe["case_index"],
                            "source": probe["source"],
                            "score": score,
                            "error": error_text,
                            "delivered": delivered,
                        }
                    )
                response = {"seam": seam_results}
            elif operation == "load":
                # Nothing is scored here. The scorer is already loaded above;
                # this resolves the reply transform and checks it accepts the
                # one positional argument its contract names, so a typo'd path,
                # a renamed function, a syntax error, an uninstalled dependency
                # and a two-argument signature all fail LOUDLY and once -
                # instead of arriving later as N identical refusals that cannot
                # be told from an agent whose contract excludes the shape.
                transform = load_function(request["reply_transform"])
                inspect.signature(transform).bind("probe")
                response = {"loaded": True}
            elif operation == "supplemental":
                case = request["case"]
                probe = request["probe"]
                if probe["type"] == "permutation":
                    output = probe["output"]
                elif probe["type"] == "exception":
                    output = exception_probe_output(probe["kind"])
                else:
                    raise ValueError(
                        f"unknown supplemental probe type: {probe['type']}"
                    )
                score = None
                error_text = None
                try:
                    score = bind_call(
                        function,
                        output,
                        case["expected"],
                        case.get("input_data"),
                        case.get("metadata"),
                    )
                except (KeyboardInterrupt, GeneratorExit):
                    # Cancellation remains control flow. The parent reports the
                    # crashed supplemental attempt as unavailable; it is never
                    # converted into evaluator evidence or an ordinary zero.
                    raise
                except BaseException as error:  # SystemExit is probe evidence
                    error_text = probe_error_text(error)
                response = {"score": score, "error": error_text}
            else:
                raise ValueError(f"unknown worker operation: {operation}")
        if containment_report is not None:
            response = {**response, "containment": containment_report}
        print(
            json.dumps(
                {
                    **response,
                    "captured_stdout": captured_stdout.getvalue(),
                }
            )
        )
        return 0
    except Exception as error:
        # `load` never loads the scorer, so nothing but the reply transform can
        # fail there. Saying "evaluator" would name the one component this
        # branch does not touch, under a headline about the other one.
        failed = (
            "Reply transform could not be loaded"
            if operation == "load"
            else "Evaluator execution failed"
        )
        print(f"{failed}: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def normalized_threshold(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("must be a finite number in [0,1]")
    return parsed


def existing_directory(value: str) -> Path:
    try:
        path = Path(value).expanduser().resolve()
    except (OSError, RuntimeError) as error:
        raise argparse.ArgumentTypeError("must be an existing directory") from error
    if not path.is_dir():
        raise argparse.ArgumentTypeError("must be an existing directory")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Calibrate a first-run grading adapter with one or more four-probe cases."
        )
    )
    parser.add_argument(
        "--scorer",
        required=True,
        help=(
            "FILE.py:FUNCTION accepting keyword arguments output, expected, "
            "input_data, and metadata"
        ),
    )
    parser.add_argument(
        "--import-root",
        type=existing_directory,
        default=str(Path.cwd()),
        help=(
            "project import root available to the scorer "
            "(default: caller's current working directory)"
        ),
    )
    parser.add_argument("--good")
    parser.add_argument("--equivalent-good")
    parser.add_argument("--partial")
    parser.add_argument("--bad")
    parser.add_argument("--expected")
    parser.add_argument("--input-data")
    parser.add_argument("--metadata")
    parser.add_argument(
        "--score-mode",
        choices=SCORE_MODES,
        help=(
            "probe contract for a single case: graded (default) requires ordered "
            "partial credit; binary requires partial and bad probes to fail"
        ),
    )
    parser.add_argument(
        "--cases",
        help=(
            "JSON array or @FILE containing at least two named, distinct cases; "
            "each case requires expected and good/equivalent_good/partial/bad "
            "probes and may select score_mode. Structural distinctness does not "
            "replace the coding assistant's recorded evidence-backed "
            "semantic-coverage review of material task branches"
        ),
    )
    parser.add_argument(
        "--kind", choices=("deterministic", "llm-judge"), default="deterministic"
    )
    parser.add_argument(
        "--reply-transform",
        help=(
            "FILE.py:FUNCTION taking one positional argument - the model's "
            "reply - and returning what the evaluator is handed. The agent's "
            "own extraction or clean-up step, so the authored probes can be "
            "scored the way an answer actually arrives instead of the way it "
            "was typed. Omit where the agent hands its reply over unchanged"
        ),
    )
    parser.add_argument(
        "--task-kind",
        choices=TASK_KINDS,
        help=(
            "the run-scoped output kind, in readiness.py's vocabulary. On code "
            "and code-sql it adds two seam probes per case, carrying that "
            "case's own good and equivalent-good answers inside a markdown "
            "code fence - the shape a chat model returns code in unless told "
            "otherwise. It arms nothing on any other kind, so pass it only "
            "where project evidence grounds one of those two"
        ),
    )
    parser.add_argument(
        "--allow-execution",
        action="store_true",
        help=(
            "confirm that importing and executing the scorer is intended - and "
            "the module behind --reply-transform, whose top level runs on the "
            "same import"
        ),
    )
    parser.add_argument(
        "--contained",
        action="store_true",
        help=(
            "run the probes inside the containment envelope: the network "
            "closed at the socket layer, subprocesses refused, sqlite opened "
            "read-only under a step budget, and cpu and file writes bounded. "
            "This is the route for a scorer whose path reaches an engine, and "
            "for one this tool's static read cannot follow - both are refused "
            "without it. Aim it at a disposable schema this run built. The card records what the envelope "
            "actually enforced, measured rather than declared. Refused beside "
            "--kind llm-judge, which needs the network the envelope closes"
        ),
    )
    parser.add_argument(
        "--paid-approved",
        action="store_true",
        help="confirm explicit approval for LLM-judge provider calls",
    )
    parser.add_argument(
        "--good-minimum",
        type=normalized_threshold,
        default=GOOD_MINIMUM,
        help=f"minimum accepted good/equivalent score (default: {GOOD_MINIMUM})",
    )
    parser.add_argument(
        "--bad-maximum",
        type=normalized_threshold,
        default=BAD_MAXIMUM,
        help=f"maximum accepted bad/binary-partial score (default: {BAD_MAXIMUM})",
    )
    parser.add_argument(
        "--equivalence-tolerance",
        type=normalized_threshold,
        default=EQUIVALENCE_TOLERANCE,
        help=(
            "maximum good/equivalent score difference "
            f"(default: {EQUIVALENCE_TOLERANCE})"
        ),
    )
    parser.add_argument(
        "--separation-margin",
        type=normalized_threshold,
        default=SEPARATION_MARGIN,
        help=(
            "minimum graded partial-to-good and bad-to-partial margin "
            f"(default: {SEPARATION_MARGIN})"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=positive_int,
        default=None,
        help=(
            "seconds the whole calibration may take: the authored phase and the "
            "deterministic supplemental probes share this one total budget, so "
            "this is the worst-case wall time and not half of it. The default is "
            f"derived from the work - {PROBES_PER_CASE} authored and up to "
            f"{DETERMINISTIC_SUPPLEMENTAL_PROBES_PER_CASE} supplemental probe "
            f"calls per deterministic case at {DETERMINISTIC_SECONDS_PER_PROBE}s "
            f"each, or {PROBES_PER_CASE} calls per --kind llm-judge case at "
            f"{LLM_JUDGE_SECONDS_PER_PROBE}s each for --kind llm-judge - and then "
            f"capped at {CALIBRATION_TIMEOUT_CEILING_SECONDS}s "
            f"({CALIBRATION_TIMEOUT_CEILING_SECONDS // 60} minutes), which is a "
            "ceiling on the wait rather than on the work and so gives a large "
            "case set less per probe than the rates above. Passing this "
            "explicitly is the user's own number and is not capped - and it is "
            "the whole budget, so size it for both phases: a value that covers "
            "only the authored probes leaves the supplemental ones nothing, "
            "they come back unavailable, and the ADVISORY line on stderr names "
            "how many. The default already allows for both; an explicit value "
            "of calls-times-cost does not. There is no "
            "resume: a calibration stopped before it finishes records nothing"
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def calibration_cases(args: argparse.Namespace) -> tuple[list[dict[str, Any]], bool]:
    single_case_options = {
        "--good": args.good,
        "--equivalent-good": args.equivalent_good,
        "--partial": args.partial,
        "--bad": args.bad,
        "--expected": args.expected,
        "--input-data": args.input_data,
        "--metadata": args.metadata,
        "--score-mode": args.score_mode,
    }
    if args.cases is not None:
        combined = [
            name for name, value in single_case_options.items() if value is not None
        ]
        if combined:
            raise ValueError(
                "--cases cannot be combined with single-case options: "
                + ", ".join(combined)
            )
        raw_cases = literal_or_file(args.cases)
        if not isinstance(raw_cases, list) or len(raw_cases) < 2:
            raise ValueError("--cases must contain a JSON array of at least two cases")
        cases = []
        normalized_names: set[str] = set()
        canonical_cases: set[str] = set()
        for index, raw_case in enumerate(raw_cases, 1):
            if not isinstance(raw_case, dict):
                raise ValueError(f"case {index} must be a JSON object")
            if "expected" not in raw_case:
                raise ValueError(f"case {index} is missing 'expected'")
            probes = raw_case.get("probes")
            if not isinstance(probes, dict):
                raise ValueError(f"case {index} must contain a 'probes' object")
            missing_probes = [name for name in PROBE_NAMES if name not in probes]
            if missing_probes:
                raise ValueError(
                    f"case {index} is missing probes: {', '.join(missing_probes)}"
                )
            name = raw_case.get("name", f"case-{index}")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"case {index} name must be a non-empty string")
            display_name = " ".join(name.split())
            normalized_name = display_name.casefold()
            if normalized_name in normalized_names:
                raise ValueError(
                    f"case {index} name duplicates another case after normalization: "
                    f"{display_name!r}"
                )
            normalized_names.add(normalized_name)
            score_mode = raw_case.get("score_mode", "graded")
            if not isinstance(score_mode, str) or score_mode not in SCORE_MODES:
                raise ValueError(
                    f"case {index} score_mode must be one of: "
                    f"{', '.join(SCORE_MODES)}"
                )
            # What outcome classes this case is claimed to cover. Optional, so
            # every existing matrix keeps working, and recorded verbatim when
            # given: the attestation used to state only a verdict, which cannot
            # be reviewed - a reader could see that someone looked, never what
            # they looked at, and so never that a class was missing
            # (traigent-first-run#99).
            outcome_classes = raw_case.get("outcome_classes", [])
            if not isinstance(outcome_classes, list) or not all(
                isinstance(item, str) and item.strip() for item in outcome_classes
            ):
                raise ValueError(
                    f"case {index} outcome_classes must be a list of non-empty "
                    "strings naming what this case covers"
                )
            case = {
                "name": display_name,
                "score_mode": score_mode,
                "expected": raw_case["expected"],
                "input_data": raw_case.get("input_data"),
                "metadata": raw_case.get("metadata", {}),
                "outcome_classes": [item.strip() for item in outcome_classes],
                "probes": {
                    probe_name: probes[probe_name] for probe_name in PROBE_NAMES
                },
            }
            canonical_case = json.dumps(
                {
                    key: value
                    for key, value in case.items()
                    # `outcome_classes` joins name and score_mode here: two cases
                    # with the same payload are the same case however they are
                    # labelled, and letting a declared class distinguish them
                    # would turn the duplicate guard off by writing a word.
                    if key not in {"name", "score_mode", "outcome_classes"}
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            if canonical_case in canonical_cases:
                raise ValueError(
                    f"case {index} duplicates another case payload; names and score "
                    "modes alone do not establish material branch coverage"
                )
            canonical_cases.add(canonical_case)
            cases.append(case)
        return cases, True

    required_options = {
        name: value
        for name, value in single_case_options.items()
        if name in {"--good", "--equivalent-good", "--partial", "--bad", "--expected"}
    }
    missing = [name for name, value in required_options.items() if value is None]
    if missing:
        raise ValueError("single-case calibration requires " + ", ".join(missing))
    return (
        [
            {
                "name": "case-1",
                "score_mode": args.score_mode or "graded",
                "expected": literal_or_file(args.expected),
                "input_data": (
                    literal_or_file(args.input_data)
                    if args.input_data is not None
                    else None
                ),
                "metadata": (
                    literal_or_file(args.metadata) if args.metadata is not None else {}
                ),
                "probes": {
                    "good": literal_or_file(args.good),
                    "equivalent_good": literal_or_file(args.equivalent_good),
                    "partial": literal_or_file(args.partial),
                    "bad": literal_or_file(args.bad),
                },
            }
        ],
        False,
    )


def calibration_thresholds(
    args: argparse.Namespace, cases: list[dict[str, Any]]
) -> dict[str, float]:
    thresholds = {
        "good_minimum": args.good_minimum,
        "bad_maximum": args.bad_maximum,
        "equivalence_tolerance": args.equivalence_tolerance,
        "separation_margin": args.separation_margin,
    }
    if thresholds["good_minimum"] <= thresholds["bad_maximum"]:
        raise ValueError("--good-minimum must be greater than --bad-maximum")
    if thresholds["separation_margin"] > 0.5:
        raise ValueError(
            "--separation-margin must be no greater than 0.5 so a normalized "
            "partial score can be separated from both good and bad"
        )
    if any(case["score_mode"] == "graded" for case in cases) and (
        thresholds["good_minimum"] - thresholds["bad_maximum"]
        < 2 * thresholds["separation_margin"]
    ):
        raise ValueError(
            "--good-minimum minus --bad-maximum must be at least twice "
            "--separation-margin for graded cases"
        )
    return thresholds


def calibration_checks(
    scores: dict[str, float],
    score_mode: str,
    thresholds: dict[str, float],
) -> dict[str, bool]:
    common = {
        "good_passes": scores["good"] >= thresholds["good_minimum"],
        "equivalent_is_accepted": scores["equivalent_good"]
        >= thresholds["good_minimum"],
        "equivalent_matches_good": abs(scores["good"] - scores["equivalent_good"])
        <= thresholds["equivalence_tolerance"],
        "bad_fails": scores["bad"] <= thresholds["bad_maximum"],
        "non_constant": len({round(score, 8) for score in scores.values()}) > 1,
    }
    if score_mode == "binary":
        return {
            **common,
            "partial_fails": scores["partial"] <= thresholds["bad_maximum"],
        }
    if score_mode != "graded":
        raise ValueError(f"score_mode must be one of: {', '.join(SCORE_MODES)}")
    return {
        **common,
        "partial_is_below_good": scores["partial"]
        <= min(scores["good"], scores["equivalent_good"])
        - thresholds["separation_margin"],
        "partial_is_above_bad": scores["partial"]
        >= scores["bad"] + thresholds["separation_margin"],
    }


def exception_probe_result(
    kind: str,
    score: float | None,
    error: str | None,
    unavailable: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify the advisory probe without claiming why a scorer returned zero."""
    if unavailable is not None:
        if score is not None or error is not None:
            raise ValueError(
                "an unavailable exception probe cannot also have a score or error"
            )
        return {
            "kind": kind,
            "score": None,
            "error": None,
            "outcome": "unavailable",
            "distinguished_from_zero": None,
            "available": False,
            "unavailable": unavailable,
        }
    if (score is None) == (error is None):
        raise ValueError(
            "exception probe must return exactly one of a score or propagated error"
        )
    if error is not None:
        outcome = "propagated-error"
    elif score == 0.0:
        outcome = "returned-zero"
    else:
        outcome = "returned-nonzero"
    return {
        "kind": kind,
        "score": score,
        "error": error,
        "outcome": outcome,
        "distinguished_from_zero": outcome != "returned-zero",
        "available": True,
        "unavailable": None,
    }


def unavailable_supplemental_attempt(reason: str, detail: str) -> dict[str, Any]:
    """Describe infrastructure/setup failure without manufacturing probe evidence."""
    return {
        "score": None,
        "error": None,
        "unavailable": {"reason": reason, "detail": detail},
    }


def run_supplemental_attempt(
    request: dict[str, Any],
    *,
    deadline: float,
    total_budget_seconds: int,
    environment: dict[str, str],
    cwd: Path,
) -> dict[str, Any]:
    """Run one advisory attempt in a disposable worker process.

    A supplemental timeout, import failure, crash, or malformed worker response
    is reported as unavailable. None can replace the authored calibration
    verdict because the authored worker has already completed independently.
    """
    remaining_seconds = deadline - time.monotonic()
    if remaining_seconds <= 0:
        return unavailable_supplemental_attempt(
            "budget-exhausted",
            f"the calibration's single {total_budget_seconds}-second total budget "
            "was spent before this supplemental probe could run",
        )
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--_worker"],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=remaining_seconds,
            env=environment,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return unavailable_supplemental_attempt(
            "timeout",
            "supplemental worker exceeded the remaining "
            f"{remaining_seconds:.3f} seconds of the calibration's "
            f"{total_budget_seconds}-second total budget",
        )
    except (OSError, subprocess.SubprocessError) as error:
        return unavailable_supplemental_attempt(
            "worker-setup-failed",
            f"supplemental worker could not be started or observed: {error}",
        )
    if process.returncode != 0:
        reason = "worker-signal" if process.returncode < 0 else "worker-failed"
        detail = process.stderr.strip() or (
            f"supplemental worker exited with status {process.returncode}"
        )
        return unavailable_supplemental_attempt(reason, detail)
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        return unavailable_supplemental_attempt(
            "invalid-worker-output",
            f"supplemental worker returned invalid JSON: {error.msg}",
        )
    if not isinstance(payload, dict):
        return unavailable_supplemental_attempt(
            "invalid-worker-output",
            "supplemental worker response was not a JSON object",
        )
    score = payload.get("score")
    error = payload.get("error")
    if (score is None) == (error is None):
        return unavailable_supplemental_attempt(
            "invalid-worker-output",
            "supplemental worker did not return exactly one score or propagated error",
        )
    if error is not None and not isinstance(error, str):
        return unavailable_supplemental_attempt(
            "invalid-worker-output",
            "supplemental worker error was not text",
        )
    return {"score": score, "error": error, "unavailable": None}


def run_seam_batch(
    request: dict[str, Any],
    *,
    deadline: float,
    total_budget_seconds: int,
    environment: dict[str, str],
    cwd: Path,
) -> list[dict[str, Any]]:
    """Score the whole seam family in one worker, and report per probe.

    One worker, so the customer's transform module is imported once for the
    family instead of once per probe. The cost is granularity on failure: a
    crash or a timeout takes every seam probe with it, and each is reported
    unavailable for the same reason. That is the trade the authored phase
    already makes for the four probes that decide PASS, and it is reported
    honestly - the parent has no partial output to attribute, so it attributes
    none.
    """
    probes = request["probes"]

    def all_unavailable(reason: str, detail: str) -> list[dict[str, Any]]:
        # Every entry carries the same reason AND says why they are the same:
        # this family shares one worker, so a reader told to inspect or re-run
        # an unavailable probe can tell "each was tried and each failed" from
        # "one worker carried all of them". The older families are attempted
        # individually and their entries look identical without this clause.
        together = (
            f" All {len(probes)} seam probes share one worker and fell together; "
            "none was attempted on its own."
        )
        return [
            unavailable_supplemental_attempt(reason, detail + together) for _ in probes
        ]

    remaining_seconds = deadline - time.monotonic()
    if remaining_seconds <= 0:
        return all_unavailable(
            "budget-exhausted",
            f"the calibration's single {total_budget_seconds}-second total budget "
            "was spent before the seam probes could run",
        )
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--_worker"],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=remaining_seconds,
            env=environment,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return all_unavailable(
            "timeout",
            f"the seam worker exceeded the remaining {remaining_seconds:.3f} "
            f"seconds of the calibration's {total_budget_seconds}-second total "
            "budget",
        )
    except (OSError, subprocess.SubprocessError) as error:
        return all_unavailable(
            "worker-setup-failed",
            f"the seam worker could not be started or observed: {error}",
        )
    if process.returncode != 0:
        reason = "worker-signal" if process.returncode < 0 else "worker-failed"
        return all_unavailable(
            reason,
            process.stderr.strip()
            or f"the seam worker exited with status {process.returncode}",
        )
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        return all_unavailable(
            "invalid-worker-output",
            f"the seam worker returned invalid JSON: {error.msg}",
        )
    scored = payload.get("seam") if isinstance(payload, dict) else None
    if not isinstance(scored, list) or len(scored) != len(probes):
        return all_unavailable(
            "invalid-worker-output",
            "the seam worker did not return one result per probe",
        )
    attempts = []
    for probe, result in zip(probes, scored, strict=True):
        score = result.get("score")
        error = result.get("error")
        if (score is None) == (error is None) or (
            error is not None and not isinstance(error, str)
        ):
            attempts.append(
                unavailable_supplemental_attempt(
                    "invalid-worker-output",
                    f"the seam worker returned neither a score nor a propagated "
                    f"error for {probe['source']!r}",
                )
            )
            continue
        attempts.append(
            {
                "score": score,
                "error": error,
                "unavailable": None,
                # What the evaluator was actually handed, which is the half of
                # the finding a reader cannot reconstruct. `None` where no
                # transform ran, because nothing was handed anywhere.
                "delivered": result.get("delivered"),
            }
        )
    return attempts


# The one place an unexpected failure is allowed to end.
#
# The three scripts in this bundle each own this boundary because each is a
# standalone file the skill copies out, and a shared helper module is a fourth
# file to keep in step. What it guards is identical in all three: an error
# nobody anticipated used to escape to the interpreter, which printed a
# traceback in place of the result and exited 1. The reader is running their
# first optimization; a defect in this check must not read as a defect in their
# project.
#
# Loud, not silent: the error class and message are printed, the exit code is
# non-zero and distinct, and nothing pretends a calibration ran. The
# environment variable prints the stack for whoever is fixing it.
INTERNAL_ERROR_EXIT = 3
TRACEBACK_ENV = "TRAIGENT_FIRST_RUN_TRACEBACK"


def report_internal_error(
    tool: str,
    error: BaseException,
    *,
    environ: dict[str, str] | None = None,
    stream: Any = None,
) -> int:
    """Print an unexpected failure as a diagnosis, never as a traceback."""
    out = sys.stderr if stream is None else stream
    env = os.environ if environ is None else environ
    print(f"{tool}: internal error - {type(error).__name__}: {error}", file=out)
    print(
        f"{tool} could not finish, and this is a defect in the check rather "
        "than in your project. No calibration result was produced, so treat "
        f"the evaluator as unchecked. Re-run with {TRACEBACK_ENV}=1 and report "
        "the output.",
        file=out,
    )
    if env.get(TRACEBACK_ENV):
        traceback.print_exception(type(error), error, error.__traceback__, file=out)
    return INTERNAL_ERROR_EXIT


def main() -> int:
    """The process boundary. See `report_internal_error`.

    Wraps the worker path too. A worker that dies unexpectedly already exits
    non-zero and the parent reads that (`worker-failed`); what changes is that
    its last words are a named error instead of a stack the parent discards.
    """
    try:
        return run()
    except Exception as error:  # noqa: BLE001 - the boundary is the point
        return report_internal_error("calibrate_evaluator.py", error)


def run() -> int:
    if "--_worker" in sys.argv:
        return run_worker()
    args = parse_args()
    if not args.allow_execution:
        print(
            "Refusing to import or execute the scorer, or the module behind "
            "--reply-transform, without --allow-execution.",
            file=sys.stderr,
        )
        return 2
    if args.kind == "llm-judge" and (
        args.reply_transform is not None or args.task_kind is not None
    ):
        print(
            "--reply-transform and --task-kind arm seam probes, which are "
            "scorer calls. Against an LLM judge those are provider calls "
            "nobody approved, so this combination is refused rather than "
            "silently ignored.",
            file=sys.stderr,
        )
        return 2
    absolute_transform = None
    if args.reply_transform is not None:
        transform_file, transform_separator, transform_name = (
            args.reply_transform.partition(":")
        )
        if not transform_separator or not transform_name:
            print("--reply-transform must use FILE.py:FUNCTION.", file=sys.stderr)
            return 2
        absolute_transform = f"{Path(transform_file).resolve()}:{transform_name}"
    if args.contained and args.kind == "llm-judge":
        print(
            "--contained closes the network, and an LLM judge reaches its "
            "provider over it, so the two cannot both hold. A judge whose "
            "path also executes candidate code or SQL has no route here: that "
            "is the manual containment review in references/run-safety.md.",
            file=sys.stderr,
        )
        return 2
    if args.kind == "llm-judge" and not args.paid_approved:
        print(
            "LLM-judge calibration can make provider calls; obtain approval and pass --paid-approved.",
            file=sys.stderr,
        )
        return 2

    try:
        cases, is_matrix = calibration_cases(args)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Invalid calibration cases: {error}", file=sys.stderr)
        return 2
    if args.timeout is None:
        # Set here, not at parse time: the budget depends on how many probe
        # calls the case set actually asks for, which is not known until the
        # cases are parsed.
        args.timeout = calibration_timeout_seconds(len(cases), args.kind)
    try:
        thresholds = calibration_thresholds(args, cases)
    except ValueError as error:
        print(f"Invalid calibration thresholds: {error}", file=sys.stderr)
        return 2

    scorer_file, separator, scorer_name = args.scorer.partition(":")
    if not separator or not scorer_name:
        print("--scorer must use FILE.py:FUNCTION.", file=sys.stderr)
        return 2
    absolute_scorer = f"{Path(scorer_file).resolve()}:{scorer_name}"
    # The gate, executed rather than described. Run BEFORE the first child, so
    # a scorer this read will not clear is never imported: the read itself
    # parses source and imports nothing, which is what lets it precede the
    # acknowledgement's consequences rather than follow them.
    scope = execution_scope_scan(scorer_file, scorer_name, args.import_root)
    if scope["verdict"] != SCOPE_CLEAR and not args.contained:
        print(scope_refusal_message(scope), file=sys.stderr)
        return 2
    # Attached once, here, rather than inside each of the two case-building
    # paths: one expected answer must not be able to acquire two permutations.
    #
    # Deterministic kinds only, and this is the load-bearing half of the gate.
    # An LLM judge bills for every probe, so generating one automatically would
    # spend the user's money on a check they never asked for - and the guide
    # requires paid work to be approved in advance, not added by a tool. A judge
    # therefore keeps exactly the four probes its author approved.
    if args.kind == "deterministic":
        for case in cases:
            case["permutation"] = permuted_answer(case["expected"])

    authored_request = {
        "operation": "authored",
        "scorer": absolute_scorer,
        "cases": cases,
        "import_root": str(args.import_root),
        "allow_execution": True,
        "contained": args.contained,
        "cpu_seconds": args.timeout,
    }
    worker_environment = subprocess_environment(
        allow_provider_access=args.kind == "llm-judge"
    )
    worker_cwd = Path(scorer_file).resolve().parent
    # One deadline for the whole calibration, opened before the FIRST child
    # this run starts and shared by every one after it, so `--timeout` is the
    # worst-case wall time its own help promises. The load probe below used to
    # sit outside it with a per-probe allowance of its own, so a slow import was
    # wall time nobody was quoted. Source, and the way to take the measurement
    # again: tests/test_calibrate_evaluator.py, which sleeps inside a
    # transform's module at import under a budget smaller than the sleep and
    # asserts the run finishes inside it. The guide has the assistant quote this
    # wait to the customer before the stage runs, so it is a number a person is
    # given rather than an internal bound.
    calibration_deadline = time.monotonic() + args.timeout
    # Armed over the whole calibration, every phase, because the wall clock the
    # user was quoted covers all of them. The cancel after the last probe is
    # cleanup and is honestly not what makes this safe - the daemon flag is,
    # since every early return below leaves the timer pending and the
    # interpreter must not wait on it.
    warning_timer = start_pre_cap_warning(args.timeout)
    if absolute_transform is not None:
        # Before the budget opens, and in the same credential-stripped child
        # every other piece of the customer's code runs in - never in this
        # process. A reply transform that cannot be loaded is a broken flag, not
        # a finding about an agent, and the old code could not say so: five
        # distinct mistakes - a missing file, a renamed function, a syntax
        # error, an uninstalled import, a two-argument signature - each arrived
        # as "every probe refused", which this script then reported as the check
        # being out of its domain. A typo silently disabled the whole check and
        # told the reader not to worry about it.
        try:
            loaded = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--_worker"],
                input=json.dumps(
                    {
                        "operation": "load",
                        "scorer": absolute_scorer,
                        "reply_transform": absolute_transform,
                        "import_root": str(args.import_root),
                        "allow_execution": True,
                        "contained": args.contained,
                        "cpu_seconds": args.timeout,
                    }
                ),
                text=True,
                capture_output=True,
                timeout=max(
                    0.0,
                    min(
                        float(DETERMINISTIC_SECONDS_PER_PROBE),
                        calibration_deadline - time.monotonic(),
                    ),
                ),
                env=worker_environment,
                cwd=worker_cwd,
            )
        except subprocess.TimeoutExpired:
            if warning_timer is not None:
                warning_timer.cancel()
            print(
                "--reply-transform could not be loaded inside this "
                f"calibration's {args.timeout}-second budget: importing its "
                "module did not finish. Nothing about this agent's delivery "
                "has been established. Re-run with a larger --timeout if that "
                "import is normally this slow.",
                file=sys.stderr,
            )
            return 2
        if loaded.returncode != 0:
            if warning_timer is not None:
                warning_timer.cancel()
            print(
                "--reply-transform could not be loaded, so no seam probe can "
                "run and nothing about this agent's delivery has been "
                "established. Two different things look like this, and the "
                "error below says which. A path, a function name or a "
                "signature that is wrong is a wrong flag: fix it. A module "
                "this environment cannot import yet is not - SKILL stage 4 has "
                "you defer both seam flags with the calibration to stage 5, "
                "where the dependencies are installed, rather than installing "
                "anything to satisfy this stage:\n"
                + (
                    loaded.stderr.strip()
                    or f"worker exited with status {loaded.returncode}"
                ),
                file=sys.stderr,
            )
            return 2
    # Advisory work still cannot consume the budget that decides calibration,
    # because the authored phase runs first and takes what it needs; what the
    # single deadline above removes is a second budget of the same size being
    # handed out after it - "one timeout at five minutes" was two at ten, and
    # `--help` disclosed that instead of fixing it.
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--_worker"],
            input=json.dumps(authored_request),
            text=True,
            capture_output=True,
            timeout=max(0.0, calibration_deadline - time.monotonic()),
            env=worker_environment,
            cwd=worker_cwd,
        )
    except subprocess.TimeoutExpired:
        # This line always reaches the assistant; the reference that owns the
        # question may not be loaded when it does. So it states the whole
        # question rather than two of its five answers - the previous wording
        # named only a larger --timeout and a faster model, which invited a
        # silent re-run at double the wait instead of one question to the person
        # paying for it.
        message = (
            f"Evaluator calibration exceeded its {args.timeout}-second budget. This does "
            "not by itself mean the evaluator is broken - slow and broken look "
            "identical from here. Do not silently re-run with a larger --timeout. "
            "Ask the user once, in one question, offering only what applies: "
            "wait, if the evaluator is normally this slow; take a named fix, if "
            "the cause is certain; score with a different judge model, or with a "
            "deterministic comparison - an exact or normalized match against the "
            "expected answer, no model call - where the task allows one; retry, "
            "since a provider call that has stalled looks the same from here; or "
            "build a new evaluation method together."
        )
        print(message, file=sys.stderr)
        # Emit a parseable result as well as the stderr line, so the readiness
        # scorer can actually see this. Its `evaluator-timeout (45)` cap reads a
        # `timed_out` key that nothing ever wrote: on timeout this exited 1 with
        # no JSON at all, so the one condition the scorer has a dedicated cap and
        # ceiling for could never fire, and a slow evaluator surfaced as a
        # generic calibration failure instead (traigent-first-run#71).
        #
        # The exit code stays 1 - the run still failed - and the payload is what
        # makes the failure legible.
        if args.json:
            # Whole authored calibration, not per-case (traigent-first-run#71,
            # point 2). Every case's authored probes run inside ONE subprocess,
            # so when the budget expires the parent has no partial output to
            # attribute: it cannot say which case was slow, or whether any
            # finished. Reporting a per-case breakdown would mean inventing one.
            #
            # `cases` is empty for that reason and not because zero cases were
            # requested, which is a distinction a reader of this payload has no
            # other way to make - so `timeout_scope` states it rather than
            # leaving it to be inferred from an empty list.
            print(
                json.dumps(
                    {
                        "timed_out": True,
                        "timeout_scope": "authored-calibration",
                        "passed": False,
                        "timeout_seconds": args.timeout,
                        "kind": args.kind,
                        "cases_requested": len(cases),
                        "cases": [],
                        "detail": message,
                    },
                    indent=2,
                )
            )
        return 1
    if process.returncode != 0:
        print(
            process.stderr.strip() or "Evaluator calibration failed.", file=sys.stderr
        )
        return 1

    payload = json.loads(process.stdout)
    containment_report = payload.get("containment") if args.contained else None

    # Every deterministic supplemental attempt gets a new interpreter. A
    # module reload in one interpreter does not isolate imported dependency
    # modules, global registries, environment mutation, or control flow. A
    # separate process does, for process-local state. Every attempt runs against
    # what is left of the one calibration deadline opened above and shares it
    # between them, so generated advisory work can neither consume the timeout
    # that decides calibration nor extend the wait the user was quoted.
    supplemental_results = [
        {"permutation": None, "exception_probes": [], "seam_probes": []}
        for _case in cases
    ]
    # Built across every case and run as one batch after the loop, so the
    # customer's transform module is imported once for the whole family rather
    # than once per probe.
    seam_queue: list[dict[str, Any]] = []
    if args.kind == "deterministic":
        for index, case in enumerate(cases):
            worker_case = {
                "name": case["name"],
                "expected": case["expected"],
                "input_data": case.get("input_data"),
                "metadata": case.get("metadata"),
            }
            request_base = {
                "operation": "supplemental",
                "scorer": absolute_scorer,
                "case": worker_case,
                "import_root": str(args.import_root),
                "allow_execution": True,
                "contained": args.contained,
                "cpu_seconds": args.timeout,
            }
            permutation = case.get("permutation")
            if permutation is not None:
                supplemental_results[index]["permutation"] = run_supplemental_attempt(
                    {
                        **request_base,
                        "probe": {
                            "type": "permutation",
                            "output": permutation,
                        },
                    },
                    deadline=calibration_deadline,
                    total_budget_seconds=args.timeout,
                    environment=worker_environment,
                    cwd=worker_cwd,
                )
            for kind in EXCEPTION_PROBE_KINDS:
                attempt = run_supplemental_attempt(
                    {
                        **request_base,
                        "probe": {"type": "exception", "kind": kind},
                    },
                    deadline=calibration_deadline,
                    total_budget_seconds=args.timeout,
                    environment=worker_environment,
                    cwd=worker_cwd,
                )
                supplemental_results[index]["exception_probes"].append(
                    {"kind": kind, **attempt}
                )
            # Last, deliberately. This family is the new arrival, and
            # enqueuing it ahead of the exception probes would make an
            # existing family starve first under budget pressure - a
            # silent change to what an unrelated check reports, decided by
            # an insertion point rather than by anyone.
            for source in SEAM_TRANSFORMED_SOURCES:
                sent = fenced_probe_output(case["probes"][source], args.task_kind)
                if sent is not None:
                    seam_queue.append(
                        {
                            "case_index": index,
                            "source": source,
                            "output": sent,
                            "expected": worker_case["expected"],
                            "input_data": worker_case["input_data"],
                            "metadata": worker_case["metadata"],
                        }
                    )
    if seam_queue:
        seam_attempts = run_seam_batch(
            {
                "operation": "seam",
                "scorer": absolute_scorer,
                "import_root": str(args.import_root),
                # The transform reaches the child through the request rather
                # than the parent: it is the customer's code, and it runs where
                # every other piece of their code runs - in the
                # credential-stripped worker, never here.
                "reply_transform": absolute_transform,
                "probes": seam_queue,
                "allow_execution": True,
                "contained": args.contained,
                "cpu_seconds": args.timeout,
            },
            deadline=calibration_deadline,
            total_budget_seconds=args.timeout,
            environment=worker_environment,
            cwd=worker_cwd,
        )
        for probe, attempt in zip(seam_queue, seam_attempts, strict=True):
            supplemental_results[probe["case_index"]]["seam_probes"].append(
                {"source": probe["source"], "sent": probe["output"], **attempt}
            )
    if warning_timer is not None:
        warning_timer.cancel()

    case_results = []
    for configured_case, case, supplemental in zip(
        cases, payload["cases"], supplemental_results, strict=True
    ):
        score_mode = configured_case["score_mode"]
        checks = calibration_checks(case["scores"], score_mode, thresholds)
        result = {
            "name": case["name"],
            "score_mode": score_mode,
            "scores": case["scores"],
            "checks": checks,
            "passed": all(checks.values()),
        }
        # Reported beside the checks and deliberately outside `passed`. A
        # permutation that scores well is not proof of a broken evaluator: for a
        # genuinely order-free task - a set of returned ids, an unordered label
        # list - accepting one is correct, and failing the run there would train
        # authors to work around the check rather than answer it. So it asks,
        # and the author answers something only they know.
        permutation = configured_case.get("permutation")
        if permutation is not None:
            attempt = supplemental["permutation"]
            if attempt is None:
                raise RuntimeError(
                    "a configured permutation has no supplemental result"
                )
            score = attempt["score"]
            error = attempt["error"]
            unavailable = attempt["unavailable"]
            result["permutation_probe"] = {
                "probe": permutation,
                "score": score,
                "error": error,
                "available": unavailable is None,
                "unavailable": unavailable,
                # Three states, not two. "Not distinguished" rather than
                # "failed": the evaluator did not separate a rearrangement of
                # the expected answer from the answer itself. `None` is the
                # third - the scorer refused the probe outright, which answers
                # neither question, and calling that a pass or a failure would
                # invent a result out of an exception.
                "distinguished": (
                    None
                    if unavailable is not None or error is not None or score is None
                    else score <= thresholds["bad_maximum"]
                ),
            }
        if args.kind == "deterministic":
            result["seam_probes"] = [
                {
                    "source": probe["source"],
                    "sent": probe["sent"],
                    "as_written": configured_case["probes"][probe["source"]],
                    # Null where no reply step ran. It used to echo `sent`
                    # back byte-for-byte, which is a delivery nothing performed
                    # written into the payload the guidance tells an assistant
                    # to read both halves of.
                    "delivered": (
                        probe.get("delivered")
                        if args.reply_transform is not None
                        else None
                    ),
                    "score": probe["score"],
                    "error": probe["error"],
                    # The authored score for this same content. One wrapper is
                    # the only difference, so a gap between the two is the
                    # wrapper, or what the reply step did to it - never the
                    # answer, which this evaluator has already accepted.
                    "reference_score": case["scores"][probe["source"]],
                    "outcome": seam_probe_outcome(
                        reference_score=case["scores"][probe["source"]],
                        score=probe["score"],
                        error=probe["error"],
                        unavailable=probe["unavailable"],
                        thresholds=thresholds,
                    ),
                    "available": probe["unavailable"] is None,
                    "unavailable": probe["unavailable"],
                }
                for probe in supplemental["seam_probes"]
            ]
            result["exception_probes"] = [
                exception_probe_result(
                    probe["kind"],
                    probe.get("score"),
                    probe.get("error"),
                    probe.get("unavailable"),
                )
                for probe in supplemental["exception_probes"]
            ]
        case_results.append(result)
    if is_matrix:
        declared = sorted(
            {
                item
                for configured_case in cases
                for item in configured_case.get("outcome_classes", [])
            }
        )
        result = {
            "cases": case_results,
            "coverage_note": MATRIX_COVERAGE_NOTE,
            # What the author says these cases cover, so a reviewer can see an
            # absent class. Empty is reported as empty rather than omitted: a
            # matrix that names nothing is the state worth noticing, and a
            # missing key reads as an older payload instead.
            "outcome_classes_covered": declared,
            "thresholds": thresholds,
            "passed": all(case["passed"] for case in case_results),
        }
    else:
        result = {
            "score_mode": case_results[0]["score_mode"],
            "scores": case_results[0]["scores"],
            "checks": case_results[0]["checks"],
            "thresholds": thresholds,
            "passed": case_results[0]["passed"],
        }
        # Single-case output is flat, so the probe has to be lifted out of the
        # case it came from or it would be the one shape that silently drops it.
        if "permutation_probe" in case_results[0]:
            result["permutation_probe"] = case_results[0]["permutation_probe"]
        if "exception_probes" in case_results[0]:
            result["exception_probes"] = case_results[0]["exception_probes"]
        if "seam_probes" in case_results[0]:
            result["seam_probes"] = case_results[0]["seam_probes"]

    # What was read, and what was enforced - on both shapes, because a card
    # that carries the calibration evidence has to carry the terms it was
    # obtained under. `execution_scope` is always present: a run that cleared
    # the read states the bound of that clearance, which is the list of modules
    # the read did not open, and a contained run states the sinks it was
    # contained BECAUSE of. `containment` appears only where the envelope
    # actually closed, and its contents come back from the child that closed
    # it rather than from the flag that asked for it - a declaration verified
    # against nothing must not pay, and this one is not a declaration.
    result["execution_scope"] = scope
    if containment_report is not None:
        result["containment"] = containment_report

    # One list, both shapes, so neither can answer this differently.
    #
    # `is False`, not `not`: `distinguished` is tri-state, and `not None` is
    # True - so a probe the scorer REFUSED would have raised the "does not
    # distinguish" question, which is a claim nothing established. Only a probe
    # that actually scored, and scored well, asks anything.
    unresolved = [
        case
        for case in case_results
        if "permutation_probe" in case
        and case["permutation_probe"]["distinguished"] is False
    ]
    if unresolved:
        result["permutation_question"] = (
            "This evaluator does not distinguish a rearrangement of the expected "
            "answer from the expected answer itself, in: "
            + ", ".join(case["name"] for case in unresolved)
            + ". That is correct for a task whose order genuinely does not "
            "matter, and the wrong check for one where it does - a swapped "
            "label/value binding is a wrong answer that scores full marks. "
            "Confirm which this task is before optimizing against it."
        )
    all_seam_probes = [
        probe for case in case_results for probe in case.get("seam_probes", [])
    ]
    delivered = args.reply_transform is not None
    if (
        args.kind == "deterministic"
        and not all_seam_probes
        # Only where a probe was EXPECTED. A calibration that named no reply
        # step and no code task kind did not ask for this check, and announcing
        # its absence on every closed-label run would be a line nobody can act
        # on printed beside the ones they can. What must never be silent is the
        # other case: flags that read as arming it while nothing runs.
        and (
            args.reply_transform is not None
            or args.task_kind in FENCED_PROBE_TASK_KINDS
        )
    ):
        # A check that quietly declines to run is the failure mode this whole
        # change exists to remove, so it says so rather than leaving an absent
        # key to be noticed. --task-kind is what arms it: without an evidenced
        # reply shape there is nothing honest to hand a reply step.
        result["seam_probe_skipped"] = (
            "No seam probe ran"
            + (
                ", because --task-kind was not one this check has an evidenced "
                "reply shape for (code, code-sql)"
                if args.task_kind not in FENCED_PROBE_TASK_KINDS
                else ", because no case had a good and equivalent-good probe "
                "this check could put a fence around"
            )
            + ". Nothing was established about how an answer reaches this "
            "evaluator; do not record this as a pass."
        )
        print(f"NOT RUN: {result['seam_probe_skipped']}", file=sys.stderr)
    if seam_probes_are_off_domain(all_seam_probes):
        # Not a finding, and deliberately not the advisory: nothing here
        # separates a broken step from one whose contract excludes this shape.
        result["seam_probe_off_domain"] = (
            "Every seam probe was refused by this run's reply step, so this "
            "check established nothing. A step that rejects every fenced string "
            "is what a structured-output agent looks like - one whose model "
            "returns JSON rather than a code block - and it is also what a "
            "broken step looks like; this cannot tell them apart and does not "
            "guess. Read it as a check that did not apply, not as a fault, and "
            "do not carry it to the approval as one. Where the agent's contract "
            "is not a code fence, omit --task-kind and record why."
        )
        print(f"OFF DOMAIN: {result['seam_probe_off_domain']}", file=sys.stderr)
    damaged_seams = [
        (case["name"], probe)
        for case in case_results
        for probe in case.get("seam_probes", [])
        if probe["outcome"] in ("damaged", "refused")
    ]
    if damaged_seams and "seam_probe_off_domain" not in result:
        listing = "; ".join(
            f"{name} ({probe['source']}: "
            + (
                f"raised {probe['error']} and returned nothing"
                if probe["outcome"] == "refused"
                else f"{probe['reference_score']:.4f} as written, "
                f"{probe['score']:.4f} " + ("as delivered" if delivered else "fenced")
            )
            + ")"
            for name, probe in damaged_seams
        )
        if delivered:
            result["seam_probe_advisory"] = (
                "The answer this evaluator is handed is not the answer it was "
                "calibrated on. In: "
                + listing
                + ". Each is an answer the authored probes already scored as "
                "right, put through this run's own reply step in the shape a "
                "chat model returns code - and coming out as one this evaluator "
                "scores as wrong, or not coming out at all. The fenced shape is "
                "one this check constructed, not one observed from this route: "
                "what is established is how the step behaves on it, not that "
                "the model sends it. That is a fact about the two strings "
                "recorded beside it, not a verdict on any model. It does not "
                "change calibration PASS. Show both strings "
                "and settle it before the paid run: every trial passes through "
                "this same step, and configurations that all score the damaged "
                "form cannot be told apart."
            )
        else:
            # No reply step exists in this run, so nothing was "delivered" and
            # nothing "arrived". The fenced string is one this check BUILT, and
            # saying otherwise would put two identical strings in front of a
            # customer under a sentence claiming they differ.
            result["seam_probe_advisory"] = (
                "This evaluator scores an answer it has already accepted as "
                "wrong when that answer carries a markdown code fence. In: "
                + listing
                + ". This run has no reply step between the model and the "
                "evaluator, so the fenced string recorded beside each is one "
                "this check constructed and not one anything produced: nothing "
                "here establishes that the model sends a fence, only that this "
                "pair could not read it if it did. A chat model usually does "
                "fence code, and has been observed doing so against a prompt "
                "forbidding it, which is why this is worth showing. It does not "
                "change calibration PASS. Put both strings on the approval and "
                "let the customer say which their agent returns."
            )
    zero_exception_probes = [
        (
            case["name"],
            [
                probe["kind"]
                for probe in case.get("exception_probes", [])
                if probe["outcome"] == "returned-zero"
            ],
        )
        for case in case_results
        if any(
            probe["outcome"] == "returned-zero"
            for probe in case.get("exception_probes", [])
        )
    ]
    if zero_exception_probes:
        result["exception_probe_advisory"] = (
            "This evaluator returned an ordinary 0.0 for one or more exception "
            "or malformed-output probes in: "
            + "; ".join(
                f"{name} ({', '.join(kinds)})" for name, kinds in zero_exception_probes
            )
            + ". That is consistent with a swallowed parser or evaluator "
            "exception, but it can also be a deliberate rejection of an "
            "unsupported or malformed output with zero. This advisory does not "
            "prove the cause or change calibration PASS. Inspect the exception "
            "path and ensure genuine parser/runtime failures propagate distinctly "
            "before optimizing."
        )
    unavailable_supplemental_probes = []
    for case in case_results:
        permutation_probe = case.get("permutation_probe")
        if permutation_probe and permutation_probe["unavailable"] is not None:
            unavailable_supplemental_probes.append(
                {
                    "case": case["name"],
                    "probe": "permutation",
                    **permutation_probe["unavailable"],
                }
            )
        unavailable_supplemental_probes.extend(
            {
                "case": case["name"],
                "probe": probe["kind"],
                **probe["unavailable"],
            }
            for probe in case.get("exception_probes", [])
            if probe["unavailable"] is not None
        )
        # The family this list was extended for. It collected from two of three
        # probe families, and a seam probe lost to the budget went unmentioned
        # in the very payload whose purpose is that a finding reaches a person -
        # which is the defect the comment below already records, one family on.
        unavailable_supplemental_probes.extend(
            {
                "case": case["name"],
                "probe": f"seam:{probe['source']}",
                **probe["unavailable"],
            }
            for probe in case.get("seam_probes", [])
            if probe["unavailable"] is not None
        )
    if unavailable_supplemental_probes:
        result["supplemental_probe_unavailable"] = unavailable_supplemental_probes
        result["supplemental_probe_advisory"] = (
            "One or more deterministic supplemental probes were unavailable: "
            + "; ".join(
                f"{item['case']} ({item['probe']}: {item['reason']})"
                for item in unavailable_supplemental_probes
            )
            + ". Their details are recorded in supplemental_probe_unavailable. "
            "Supplemental setup, timeout, or crash evidence never changes the "
            "authored calibration PASS; inspect or rerun unavailable probes before "
            "relying on them."
        )
    if "seam_probe_advisory" in result:
        print(f"ADVISORY: {result['seam_probe_advisory']}", file=sys.stderr)
        for name, probe in damaged_seams:
            print(f"[{name}] {probe['source']}", file=sys.stderr)
            if delivered:
                print(f"  SENT     : {probe['sent']!r}", file=sys.stderr)
                print(
                    "  DELIVERED: "
                    + (
                        f"nothing - raised {probe['error']}"
                        if probe["outcome"] == "refused"
                        else repr(probe["delivered"])
                    ),
                    file=sys.stderr,
                )
            else:
                # One string, because there is only one. The bare form is the
                # authored probe, already listed by the authored phase.
                print(
                    f"  AS WRITTEN : {probe['as_written']!r}  "
                    f"{probe['reference_score']:.4f}",
                    file=sys.stderr,
                )
                print(
                    f"  CONSTRUCTED: {probe['sent']!r}  "
                    + (
                        f"raised {probe['error']}"
                        if probe["outcome"] == "refused"
                        else f"{probe['score']:.4f}"
                    )
                    + "  (built by this check - not observed)",
                    file=sys.stderr,
                )
    if "supplemental_probe_advisory" in result:
        # The summary line goes to stderr in every mode, including --json. The
        # documented invocation redirects stdout into a results file, so an
        # advisory that lives only in the payload is an advisory nobody reads: a
        # measured run lost three of twelve supplemental attempts to the budget
        # and said nothing at all. Degraded advisory evidence has to announce
        # itself, or the next reader takes a partial probe set for a complete
        # one. Only the summary - it already names every case, probe, and reason.
        # The per-probe details can be a child traceback, and those stay in the
        # payload and the human-readable listing below.
        print(f"ADVISORY: {result['supplemental_probe_advisory']}", file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif is_matrix:
        for case in case_results:
            print(f"[{case['name']}] mode={case['score_mode']}")
            for label, score in case["scores"].items():
                print(f"{label:<16} {score:.4f}")
            failed = [name for name, passed in case["checks"].items() if not passed]
            print("PASS" if not failed else f"FAIL: {', '.join(failed)}")
        print("OVERALL PASS" if result["passed"] else "OVERALL FAIL")
    else:
        print(f"mode             {result['score_mode']}")
        for label, score in result["scores"].items():
            print(f"{label:<16} {score:.4f}")
        failed = [name for name, passed in result["checks"].items() if not passed]
        print("PASS" if not failed else f"FAIL: {', '.join(failed)}")
    # Printed for the human paths too. A question only a person can answer is
    # worth nothing in a payload nobody reads, and this is exactly the run where
    # the six checks come back green.
    if not args.json and "permutation_question" in result:
        print()
        print(f"QUESTION: {result['permutation_question']}")
    if not args.json and "exception_probe_advisory" in result:
        print()
        print(f"ADVISORY: {result['exception_probe_advisory']}")
    if not args.json and "supplemental_probe_advisory" in result:
        print()
        for item in result["supplemental_probe_unavailable"]:
            print(
                f"UNAVAILABLE: [{item['case']}] {item['probe']} "
                f"({item['reason']}): {item['detail']}"
            )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

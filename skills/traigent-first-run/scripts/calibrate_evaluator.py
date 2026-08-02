#!/usr/bin/env python3
"""Execute evaluator probes in an explicitly authorized child process.

Every scorer must return a finite, normalized, higher-is-better score in ``[0,1]``.
For deterministic calibration the child is credential-stripped, but process separation is not a
sandbox. A scorer that executes candidate code or SQL must delegate that content to the
execution-evaluator containment required by ``references/run-safety.md``.
"""

from __future__ import annotations

import argparse
import asyncio
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
import time
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 30
# An LLM judge does not leave the process once - it makes four probe calls per
# case, and a reasoning model can think for a minute or more on each. A
# deterministic scorer's 30 seconds reported a *working* judge as timed out,
# which is a false failure on the check whose whole job is telling a broken
# evaluator from a slow one.
#
# So the judge budget is derived from the work rather than fixed: a generous
# per-probe allowance times the probes actually being run. The floor keeps a
# tiny case set from getting an unreasonably short budget; the ceiling is where
# "slow" stops being a credible explanation and a hang is the likelier one, and
# it also stops calibration from quietly eating the run's own time budget.
LLM_JUDGE_SECONDS_PER_PROBE = 90
LLM_JUDGE_TIMEOUT_FLOOR_SECONDS = 180
LLM_JUDGE_TIMEOUT_CEILING_SECONDS = 600
PROBES_PER_CASE = 4


def llm_judge_timeout_seconds(case_count: int) -> int:
    """Budget an LLM-judge calibration from the number of probe calls it makes."""
    probes = max(1, case_count) * PROBES_PER_CASE
    return max(
        LLM_JUDGE_TIMEOUT_FLOOR_SECONDS,
        min(LLM_JUDGE_TIMEOUT_CEILING_SECONDS, probes * LLM_JUDGE_SECONDS_PER_PROBE),
    )


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


def literal_or_file(value: str) -> Any:
    if value.startswith("@"):
        return json.loads(Path(value[1:]).read_text())
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


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
    try:
        request = json.load(sys.stdin)
        import_root = Path(request["import_root"])
        scorer_file = Path(request["scorer"].partition(":")[0]).resolve()
        import_paths = [str(import_root), str(scorer_file.parent)]
        sys.path[:] = import_paths + [
            path for path in sys.path if path not in import_paths
        ]
        captured_stdout = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout):
            function = load_function(request["scorer"])
            operation = request.get("operation", "authored")
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
        print(
            f"Evaluator execution failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
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
        "--allow-execution",
        action="store_true",
        help="confirm that importing and executing the scorer is intended",
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
            "seconds the authored calibration phase may take; deterministic "
            "supplemental probes receive one separate total budget of the same "
            "size, so worst-case wall time is roughly twice this value (default: "
            f"{DEFAULT_TIMEOUT_SECONDS}); for --kind llm-judge, "
            f"{LLM_JUDGE_SECONDS_PER_PROBE}s per probe call, "
            f"{LLM_JUDGE_TIMEOUT_FLOOR_SECONDS}-"
            f"{LLM_JUDGE_TIMEOUT_CEILING_SECONDS}s)"
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


def calibration_thresholds(args: argparse.Namespace) -> dict[str, float]:
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
    phase_budget_seconds: int,
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
            f"supplemental phase exhausted its {phase_budget_seconds}-second total budget",
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
            f"{remaining_seconds:.3f} seconds of its phase budget",
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


def main() -> int:
    if "--_worker" in sys.argv:
        return run_worker()
    args = parse_args()
    if not args.allow_execution:
        print(
            "Refusing to import or execute the scorer without --allow-execution.",
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
        # Set here, not at parse time: the judge budget depends on how many
        # probe calls the case set actually asks for.
        args.timeout = (
            llm_judge_timeout_seconds(len(cases))
            if args.kind == "llm-judge"
            else DEFAULT_TIMEOUT_SECONDS
        )
    try:
        thresholds = calibration_thresholds(args)
    except ValueError as error:
        print(f"Invalid calibration thresholds: {error}", file=sys.stderr)
        return 2

    scorer_file, separator, scorer_name = args.scorer.partition(":")
    if not separator or not scorer_name:
        print("--scorer must use FILE.py:FUNCTION.", file=sys.stderr)
        return 2
    absolute_scorer = f"{Path(scorer_file).resolve()}:{scorer_name}"
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
    }
    worker_environment = subprocess_environment(
        allow_provider_access=args.kind == "llm-judge"
    )
    worker_cwd = Path(scorer_file).resolve().parent
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--_worker"],
            input=json.dumps(authored_request),
            text=True,
            capture_output=True,
            timeout=args.timeout,
            env=worker_environment,
            cwd=worker_cwd,
        )
    except subprocess.TimeoutExpired:
        message = (
            f"Authored evaluator calibration exceeded {args.timeout} seconds. This does "
            "not by itself mean the evaluator is broken - a reasoning judge can "
            "legitimately take longer. Re-run with a larger --timeout, or "
            "calibrate against a faster model, before concluding anything about "
            "the evaluator itself."
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

    # Every deterministic supplemental attempt gets a new interpreter. A
    # module reload in one interpreter does not isolate imported dependency
    # modules, global registries, environment mutation, or control flow. A
    # separate process does, for process-local state. Its budget is separate
    # from the full authored budget and shared across the attempts, so generated
    # advisory work can never consume the timeout that decides calibration.
    supplemental_results = [
        {"permutation": None, "exception_probes": []} for _case in cases
    ]
    if args.kind == "deterministic":
        supplemental_deadline = time.monotonic() + args.timeout
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
                    deadline=supplemental_deadline,
                    phase_budget_seconds=args.timeout,
                    environment=worker_environment,
                    cwd=worker_cwd,
                )
            for kind in EXCEPTION_PROBE_KINDS:
                attempt = run_supplemental_attempt(
                    {
                        **request_base,
                        "probe": {"type": "exception", "kind": kind},
                    },
                    deadline=supplemental_deadline,
                    phase_budget_seconds=args.timeout,
                    environment=worker_environment,
                    cwd=worker_cwd,
                )
                supplemental_results[index]["exception_probes"].append(
                    {"kind": kind, **attempt}
                )

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
            "matter, and a broken ruler for one where it does - a swapped "
            "label/value binding is a wrong answer that scores full marks. "
            "Confirm which this task is before optimizing against it."
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
        print(f"ADVISORY: {result['supplemental_probe_advisory']}")
        for item in result["supplemental_probe_unavailable"]:
            print(
                f"UNAVAILABLE: [{item['case']}] {item['probe']} "
                f"({item['reason']}): {item['detail']}"
            )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

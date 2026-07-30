#!/usr/bin/env python3
"""Execute evaluator probes in an isolated, explicitly approved subprocess.

Every scorer must return a finite, normalized, higher-is-better score in ``[0,1]``.
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
import subprocess
import sys
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
        print(
            json.dumps(
                {
                    "cases": case_results,
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
            "seconds the calibration subprocess may take (default: "
            f"{DEFAULT_TIMEOUT_SECONDS}; for --kind llm-judge, "
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
            case = {
                "name": display_name,
                "score_mode": score_mode,
                "expected": raw_case["expected"],
                "input_data": raw_case.get("input_data"),
                "metadata": raw_case.get("metadata", {}),
                "probes": {
                    probe_name: probes[probe_name] for probe_name in PROBE_NAMES
                },
            }
            canonical_case = json.dumps(
                {
                    key: value
                    for key, value in case.items()
                    if key not in {"name", "score_mode"}
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
    request = {
        "scorer": absolute_scorer,
        "cases": cases,
        "import_root": str(args.import_root),
    }
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--_worker"],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=args.timeout,
            env=subprocess_environment(allow_provider_access=args.kind == "llm-judge"),
            cwd=Path(scorer_file).resolve().parent,
        )
    except subprocess.TimeoutExpired:
        message = (
            f"Evaluator calibration exceeded {args.timeout} seconds. This does "
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
            # Whole-calibration, not per-case (traigent-first-run#71, point 2).
            # Every case's probes run inside ONE subprocess, so when the budget
            # expires the parent has no partial output to attribute: it cannot
            # say which case was slow, or whether any finished. Reporting a
            # per-case breakdown would mean inventing one.
            #
            # `cases` is empty for that reason and not because zero cases were
            # requested, which is a distinction a reader of this payload has no
            # other way to make - so `timeout_scope` states it rather than
            # leaving it to be inferred from an empty list.
            print(
                json.dumps(
                    {
                        "timed_out": True,
                        "timeout_scope": "calibration",
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
    case_results = []
    for configured_case, case in zip(cases, payload["cases"], strict=True):
        score_mode = configured_case["score_mode"]
        checks = calibration_checks(case["scores"], score_mode, thresholds)
        case_results.append(
            {
                "name": case["name"],
                "score_mode": score_mode,
                "scores": case["scores"],
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
    if is_matrix:
        result = {
            "cases": case_results,
            "coverage_note": MATRIX_COVERAGE_NOTE,
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
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

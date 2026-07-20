#!/usr/bin/env python3
"""Execute evaluator probes in an isolated, explicitly approved subprocess.

Every scorer must return a finite, normalized, higher-is-better score in ``[0,1]``.
"""

from __future__ import annotations

import argparse
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
SDK_METRIC_VALUES = {
    "output",
    "expected",
    "llm_metrics",
    "example",
    "input_data",
    "metadata",
    "config",
    "example_index",
}
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
    if inspect.iscoroutinefunction(function):
        raise ValueError("async metric functions are not supported")
    return function


def bind_call(
    function,
    output: Any,
    expected: Any,
    input_data: Any,
    metadata: Any,
    example_index: int,
) -> float:
    """Bind one SDK-shaped call and enforce the normalized score contract."""
    signature = inspect.signature(function)
    values = {
        "output": output,
        "expected": expected,
        "llm_metrics": {},
        "example": None,
        "input_data": input_data,
        "metadata": metadata or {},
        "config": {},
        "example_index": example_index,
    }
    parameters = list(signature.parameters.values())
    kwargs = {
        parameter.name: values[parameter.name]
        for parameter in parameters
        if parameter.name in SDK_METRIC_VALUES
        and parameter.kind
        not in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }
    }
    positional_only = [
        parameter.name
        for parameter in parameters
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
    ]
    if positional_only:
        raise TypeError(
            "SDK metric functions must use keyword-bindable parameters; "
            f"positional-only parameters found: {positional_only}"
        )
    if "output" not in signature.parameters:
        raise TypeError(
            "SDK metric functions must declare an explicit 'output' parameter; "
            "add an adapter instead of using aliases"
        )
    unsupported_required = [
        parameter.name
        for parameter in parameters
        if parameter.default is inspect.Parameter.empty
        and parameter.kind
        not in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }
        and parameter.name not in SDK_METRIC_VALUES
    ]
    if unsupported_required:
        raise TypeError(
            "required parameters are not supported by the SDK metric binder: "
            f"{unsupported_required}"
        )
    signature.bind(**kwargs)
    try:
        score = float(function(**kwargs))
    except (TypeError, ValueError) as error:
        raise TypeError(
            "score contract requires a numeric normalized higher-is-better value "
            "in [0,1]"
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
        captured_stdout = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout):
            function = load_function(request["scorer"])
            case_results = []
            for index, case in enumerate(request["cases"]):
                scores = {
                    label: bind_call(
                        function,
                        value,
                        case["expected"],
                        case.get("input_data"),
                        case.get("metadata"),
                        index,
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
        print(f"Evaluator execution failed: {error}", file=sys.stderr)
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Calibrate a Traigent evaluator with one or more four-probe cases."
        )
    )
    parser.add_argument("--scorer", required=True, help="FILE.py:FUNCTION")
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
            "JSON array or @FILE of named cases; each case requires expected and "
            "good/equivalent_good/partial/bad probes and may select score_mode"
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
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
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
        if not isinstance(raw_cases, list) or not raw_cases:
            raise ValueError("--cases must contain a non-empty JSON array")
        cases = []
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
            score_mode = raw_case.get("score_mode", "graded")
            if not isinstance(score_mode, str) or score_mode not in SCORE_MODES:
                raise ValueError(
                    f"case {index} score_mode must be one of: "
                    f"{', '.join(SCORE_MODES)}"
                )
            cases.append(
                {
                    "name": name,
                    "score_mode": score_mode,
                    "expected": raw_case["expected"],
                    "input_data": raw_case.get("input_data"),
                    "metadata": raw_case.get("metadata", {}),
                    "probes": {name: probes[name] for name in PROBE_NAMES},
                }
            )
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


def calibration_checks(scores: dict[str, float], score_mode: str) -> dict[str, bool]:
    common = {
        "good_passes": scores["good"] >= GOOD_MINIMUM,
        "equivalent_is_accepted": scores["equivalent_good"] >= GOOD_MINIMUM,
        "bad_fails": scores["bad"] <= BAD_MAXIMUM,
        "non_constant": len({round(score, 8) for score in scores.values()}) > 1,
    }
    if score_mode == "binary":
        return {
            **common,
            "partial_fails": scores["partial"] <= BAD_MAXIMUM,
        }
    if score_mode != "graded":
        raise ValueError(f"score_mode must be one of: {', '.join(SCORE_MODES)}")
    return {
        **common,
        "equivalent_matches_good": abs(scores["good"] - scores["equivalent_good"])
        <= EQUIVALENCE_TOLERANCE,
        "partial_is_below_good": scores["partial"]
        <= min(scores["good"], scores["equivalent_good"]) - SEPARATION_MARGIN,
        "partial_is_above_bad": scores["partial"] >= scores["bad"] + SEPARATION_MARGIN,
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

    scorer_file, separator, scorer_name = args.scorer.partition(":")
    if not separator or not scorer_name:
        print("--scorer must use FILE.py:FUNCTION.", file=sys.stderr)
        return 2
    absolute_scorer = f"{Path(scorer_file).resolve()}:{scorer_name}"
    request = {
        "scorer": absolute_scorer,
        "cases": cases,
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
        print(
            f"Evaluator calibration exceeded {args.timeout} seconds.", file=sys.stderr
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
        checks = calibration_checks(case["scores"], score_mode)
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
            "passed": all(case["passed"] for case in case_results),
        }
    else:
        result = {
            "score_mode": case_results[0]["score_mode"],
            "scores": case_results[0]["scores"],
            "checks": case_results[0]["checks"],
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

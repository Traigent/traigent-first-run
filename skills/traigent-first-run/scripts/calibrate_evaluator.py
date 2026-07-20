#!/usr/bin/env python3
"""Execute four evaluator probes in an isolated, explicitly approved subprocess."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import inspect
import io
import json
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
RECOGNIZED_VALUES = {
    "actual",
    "actual_output",
    "output",
    "prediction",
    "predicted",
    "result",
    "expected",
    "expected_output",
    "ground_truth",
    "reference",
    "target",
    "llm_metrics",
    "metrics",
    "example",
    "input_data",
    "metadata",
    "config",
    "example_index",
}


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
    function, output: Any, expected: Any, input_data: Any, metadata: Any
) -> float:
    signature = inspect.signature(function)
    values = {
        "actual": output,
        "actual_output": output,
        "output": output,
        "prediction": output,
        "predicted": output,
        "result": output,
        "expected": expected,
        "expected_output": expected,
        "ground_truth": expected,
        "reference": expected,
        "target": expected,
        "llm_metrics": {},
        "metrics": {},
        "example": None,
        "input_data": input_data,
        "metadata": metadata or {},
        "config": {},
        "example_index": 0,
    }
    parameters = list(signature.parameters.values())
    kwargs = {
        parameter.name: values[parameter.name]
        for parameter in parameters
        if parameter.name in RECOGNIZED_VALUES
        and parameter.kind
        not in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }
    }
    candidates = [
        ((), kwargs),
        ((output, expected, {}), {}),
        ((output, expected), {}),
        ((output,), {}),
    ]
    for args, keyword_args in candidates:
        try:
            signature.bind(*args, **keyword_args)
        except TypeError:
            continue
        return float(function(*args, **keyword_args))
    raise TypeError("no production-compatible scorer call form fits the signature")


def run_worker() -> int:
    request = json.load(sys.stdin)
    captured_stdout = io.StringIO()
    with contextlib.redirect_stdout(captured_stdout):
        function = load_function(request["scorer"])
        scores = {
            label: bind_call(
                function,
                value,
                request["expected"],
                request.get("input_data"),
                request.get("metadata"),
            )
            for label, value in request["probes"].items()
        }
    print(json.dumps({"scores": scores, "captured_stdout": captured_stdout.getvalue()}))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calibrate a Traigent evaluator with four ordered probes."
    )
    parser.add_argument("--scorer", required=True, help="FILE.py:FUNCTION")
    parser.add_argument("--good", required=True)
    parser.add_argument("--equivalent-good", required=True)
    parser.add_argument("--partial", required=True)
    parser.add_argument("--bad", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--input-data")
    parser.add_argument("--metadata")
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

    scorer_file, separator, scorer_name = args.scorer.partition(":")
    if not separator or not scorer_name:
        print("--scorer must use FILE.py:FUNCTION.", file=sys.stderr)
        return 2
    absolute_scorer = f"{Path(scorer_file).resolve()}:{scorer_name}"
    request = {
        "scorer": absolute_scorer,
        "expected": literal_or_file(args.expected),
        "input_data": literal_or_file(args.input_data) if args.input_data else None,
        "metadata": literal_or_file(args.metadata) if args.metadata else {},
        "probes": {
            "good": literal_or_file(args.good),
            "equivalent_good": literal_or_file(args.equivalent_good),
            "partial": literal_or_file(args.partial),
            "bad": literal_or_file(args.bad),
        },
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
    scores = payload["scores"]
    checks = {
        "good_passes": scores["good"] >= GOOD_MINIMUM,
        "equivalent_is_accepted": scores["equivalent_good"] >= GOOD_MINIMUM,
        "equivalent_matches_good": abs(scores["good"] - scores["equivalent_good"])
        <= EQUIVALENCE_TOLERANCE,
        "partial_is_below_good": scores["partial"]
        <= min(scores["good"], scores["equivalent_good"]) - SEPARATION_MARGIN,
        "partial_is_above_bad": scores["partial"] >= scores["bad"] + SEPARATION_MARGIN,
        "bad_fails": scores["bad"] <= BAD_MAXIMUM,
        "non_constant": len({round(score, 8) for score in scores.values()}) > 1,
    }
    result = {"scores": scores, "checks": checks, "passed": all(checks.values())}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for label, score in scores.items():
            print(f"{label:<16} {score:.4f}")
        failed = [name for name, passed in checks.items() if not passed]
        print("PASS" if not failed else f"FAIL: {', '.join(failed)}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

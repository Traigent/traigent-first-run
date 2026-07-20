#!/usr/bin/env python3
"""Static, zero-call preflight for a Traigent first run.

This command reads local files and installed-package metadata only. It never imports
user modules, executes an agent or evaluator, contacts an LLM provider, contacts
Traigent, or consumes optimization quota.

Use ``calibrate_evaluator.py`` separately to execute evaluator probes.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
SUPPORTED_PYTHON_MIN = (3, 11)
SUPPORTED_PYTHON_MAX = (3, 14)
MIN_TRAIGENT_VERSION = (0, 21)
MAX_NEAR_DUPLICATE_ROWS = 500
NEAR_DUPLICATE_THRESHOLD = 0.9
DOMINANT_OUTPUT_RATIO = 0.9
MAX_REPORTED_DATASET_ERRORS = 5
EXPECTED_DIFFICULTIES = {"easy", "medium", "hard", "very-hard"}

VENDOR_KEYS = {
    "OpenRouter": ("OPENROUTER_API_KEY",),
    "OpenAI": ("OPENAI_API_KEY",),
    "Anthropic": ("ANTHROPIC_API_KEY",),
    "Google (Gemini)": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "Mistral": ("MISTRAL_API_KEY",),
    "Cohere": ("COHERE_API_KEY",),
    "HuggingFace": ("HF_TOKEN",),
}
BEDROCK_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION")
SCORER_NAMES = {
    "output",
    "expected",
    "llm_metrics",
    "example",
    "input_data",
    "metadata",
    "config",
    "example_index",
}


@dataclass(frozen=True)
class Result:
    check: str
    status: str
    detail: str


@dataclass(frozen=True)
class StaticSignature:
    name: str
    positional_only: list[str]
    positional: list[str]
    keyword_only: list[str]
    required: list[str]
    defaults: dict[str, str]
    has_varargs: bool
    has_kwargs: bool
    is_async: bool


RESULTS: list[Result] = []


def emit(check: str, status: str, detail: str) -> None:
    RESULTS.append(Result(check, status, detail))


def key_present(value: str | None) -> bool:
    if value is None:
        return False
    stripped = value.strip()
    return bool(stripped) and not stripped.startswith("#")


def parse_env_file(path: Path) -> dict[str, str | None]:
    """Parse the small KEY=VALUE subset used by the first-run environment."""
    values: dict[str, str | None] = {}
    if not path.exists():
        return values
    for line_number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            emit(
                "env-file",
                WARN,
                f"{path}:{line_number} is not KEY=VALUE and was ignored.",
            )
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            emit(
                "env-file",
                WARN,
                f"{path}:{line_number} has an invalid environment variable name.",
            )
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def read_env(path: Path) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """Mirror python-dotenv's default precedence: process environment wins."""
    file_values = parse_env_file(path)
    effective = dict(file_values)
    effective.update(os.environ)
    source = (
        f"{path} + process environment" if path.exists() else "process environment only"
    )
    emit("env-source", PASS, f"{source}; process values take precedence")
    if not path.exists():
        emit(
            "env-file",
            WARN,
            f"{path} not found; create a minimal file before paid work",
        )
    return effective, file_values


def check_python() -> None:
    current = (sys.version_info.major, sys.version_info.minor)
    if SUPPORTED_PYTHON_MIN <= current < SUPPORTED_PYTHON_MAX:
        emit("python-version", PASS, sys.version.split()[0])
    else:
        emit(
            "python-version",
            FAIL,
            f"Python {current[0]}.{current[1]} is outside the supported 3.11-3.13 range",
        )


def numeric_version(raw: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", raw)[:3]) or (0,)


def check_sdk() -> None:
    try:
        installed = version("traigent")
    except PackageNotFoundError:
        emit("sdk-version", FAIL, "traigent is not installed in the active interpreter")
        return
    parsed = numeric_version(installed)
    if installed == "0.0.1" or parsed < MIN_TRAIGENT_VERSION:
        emit(
            "sdk-version",
            FAIL,
            f"traigent {installed} is unsupported; install a release >=0.21",
        )
    else:
        emit("sdk-version", PASS, f"traigent {installed}")
    if importlib.util.find_spec("tenacity") is None:
        emit(
            "sdk-retry-dep",
            WARN,
            "tenacity is absent; install it if the agent uses LiteLLM num_retries",
        )


def check_keys(env: dict[str, str | None]) -> None:
    configured = [
        vendor
        for vendor, names in VENDOR_KEYS.items()
        if any(key_present(env.get(name)) for name in names)
    ]
    bedrock_present = [name for name in BEDROCK_KEYS if key_present(env.get(name))]
    if len(bedrock_present) == len(BEDROCK_KEYS):
        configured.append("Bedrock")
    elif bedrock_present:
        emit(
            "provider-key",
            WARN,
            "Bedrock credentials are incomplete; access key, secret, and region are required",
        )

    if not configured:
        emit(
            "provider-key",
            WARN,
            "no LLM provider key is configured; static checks can continue, paid work cannot",
        )
    elif len(configured) == 1:
        emit("provider-key", PASS, f"configured provider: {configured[0]}")
    else:
        emit(
            "provider-key",
            WARN,
            f"multiple providers are configured ({', '.join(configured)}); select one for this run",
        )

    traigent_key = env.get("TRAIGENT_API_KEY")
    if not key_present(traigent_key):
        emit(
            "traigent-key",
            PASS,
            "not configured yet; required only for connected execution",
        )
    elif not traigent_key.strip().startswith("uk_"):
        emit(
            "traigent-key",
            WARN,
            "portal keys normally begin with uk_; verify the local paste",
        )
    else:
        emit("traigent-key", PASS, "portal key shape looks plausible")

    openrouter_key = env.get("OPENROUTER_API_KEY")
    if key_present(openrouter_key) and not openrouter_key.strip().startswith("sk-or-"):
        emit("openrouter-key", WARN, "OpenRouter keys normally begin with sk-or-")


def check_cost_settings(
    env: dict[str, str | None], file_values: dict[str, str | None]
) -> None:
    raw_cap = env.get("TRAIGENT_RUN_COST_LIMIT")
    if not key_present(raw_cap):
        emit("cost-cap", WARN, "TRAIGENT_RUN_COST_LIMIT is not configured")
    else:
        try:
            cap = float(raw_cap)
        except (TypeError, ValueError):
            emit("cost-cap", FAIL, "TRAIGENT_RUN_COST_LIMIT must be a positive number")
        else:
            if cap <= 0:
                emit("cost-cap", FAIL, "TRAIGENT_RUN_COST_LIMIT must be positive")
            else:
                emit("cost-cap", PASS, f"per-process cap: ${cap:.2f}")

    approved_in_file = file_values.get("TRAIGENT_COST_APPROVED")
    if key_present(approved_in_file) and approved_in_file.strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        emit(
            "cost-approved",
            FAIL,
            "TRAIGENT_COST_APPROVED is persisted in .env; remove it and set it only per approved process",
        )
    elif key_present(env.get("TRAIGENT_COST_APPROVED")):
        emit(
            "cost-approved",
            WARN,
            "TRAIGENT_COST_APPROVED is active in the process; confirm this is the approved paid process",
        )

    if key_present(env.get("TRAIGENT_BACKEND_URL")):
        emit(
            "backend-url",
            WARN,
            "TRAIGENT_BACKEND_URL is overridden; verify that a non-default backend is intentional",
        )


def check_models(models: list[str]) -> None:
    if not models:
        return
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
    try:
        import litellm
    except ImportError:
        emit(
            "model-pricing",
            WARN,
            "litellm is not importable; local pricing checks skipped",
        )
        return

    for model in models:
        if not re.fullmatch(r"[A-Za-z0-9._:/-]+", model):
            emit(
                f"model-format:{model}",
                FAIL,
                "model id contains unsupported characters",
            )
            continue
        emit(
            f"model-format:{model}",
            PASS,
            "format accepted; liveness requires a separately approved provider check",
        )
        try:
            prompt_cost, completion_cost = litellm.cost_per_token(
                model=model,
                prompt_tokens=1000,
                completion_tokens=1000,
            )
        except Exception:
            emit(
                f"model-pricing:{model}",
                WARN,
                "no local price entry; do not claim a reliable estimate until pricing is resolved",
            )
        else:
            emit(
                f"model-pricing:{model}",
                PASS,
                f"local price map returned prompt={prompt_cost}, completion={completion_cost}",
            )


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def normalized_text(value: Any) -> str:
    text = stable_json(value) if not isinstance(value, str) else value
    return " ".join(re.findall(r"\w+", text.casefold()))


def token_set(value: Any) -> set[str]:
    return set(normalized_text(value).split())


def is_synthetic(row: dict[str, Any]) -> bool:
    source = row.get("source")
    if source is None and isinstance(row.get("metadata"), dict):
        source = row["metadata"].get("source")
    return str(source).casefold() == "synthetic"


def row_metadata_value(row: dict[str, Any], key: str) -> Any:
    if key in row:
        return row[key]
    metadata = row.get("metadata")
    return metadata.get(key) if isinstance(metadata, dict) else None


def check_dataset(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        emit("dataset-shape", FAIL, f"{path} does not exist")
        return None

    rows: list[dict[str, Any]] = []
    invalid_rows: list[tuple[int, str]] = []
    candidate_count = 0
    for line_number, raw_line in enumerate(path.read_text().splitlines(), 1):
        if not raw_line.strip():
            continue
        candidate_count += 1
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as error:
            invalid_rows.append((line_number, f"invalid JSON ({error.msg})"))
            continue
        if not isinstance(row, dict):
            invalid_rows.append((line_number, "row is not an object"))
            continue
        missing = [field for field in ("input", "output") if field not in row]
        if missing:
            invalid_rows.append(
                (line_number, f"missing required fields: {', '.join(missing)}")
            )
            continue
        rows.append(row)

    if invalid_rows:
        invalid_percentage = len(invalid_rows) / candidate_count * 100
        examples = "; ".join(
            f"line {line_number}: {detail}"
            for line_number, detail in invalid_rows[:MAX_REPORTED_DATASET_ERRORS]
        )
        emit(
            "dataset-integrity",
            FAIL,
            f"{len(invalid_rows)}/{candidate_count} rows ({invalid_percentage:.1f}%) "
            f"are unusable; {examples}",
        )
    if not rows:
        emit("dataset-shape", FAIL, "dataset has no usable rows")
        return None
    if not invalid_rows:
        emit("dataset-shape", PASS, f"{len(rows)} valid JSONL rows")
    if len(rows) < 10:
        emit(
            "dataset-size",
            WARN,
            f"{len(rows)} rows is a wiring check, not a credible score",
        )

    input_types = {type(row["input"]).__name__ for row in rows}
    if len(input_types) > 1:
        emit(
            "dataset-input-shape",
            FAIL,
            f"mixed input types cannot share one agent contract: {sorted(input_types)}",
        )
    else:
        emit(
            "dataset-input-shape",
            PASS,
            f"all inputs use the same {next(iter(input_types))} shape",
        )

    synthetic = any(is_synthetic(row) for row in rows)
    raw_ids = [row_metadata_value(row, "id") for row in rows]
    missing_ids = [
        index + 1 for index, value in enumerate(raw_ids) if value in (None, "")
    ]
    ids = [
        stable_json(value) if isinstance(value, (dict, list)) else str(value)
        for value in raw_ids
        if value not in (None, "")
    ]
    if missing_ids:
        status = FAIL if synthetic else WARN
        emit("dataset-ids", status, f"{len(missing_ids)} rows have no stable id")
    id_counts = Counter(ids)
    duplicate_ids = sorted(
        str(value) for value, count in id_counts.items() if count > 1
    )
    if duplicate_ids:
        emit("dataset-ids", FAIL, f"duplicate ids: {duplicate_ids[:10]}")
    elif not missing_ids:
        emit("dataset-ids", PASS, "stable ids are unique")

    normalized_inputs: dict[str, list[int]] = {}
    for index, row in enumerate(rows, 1):
        normalized_inputs.setdefault(normalized_text(row["input"]), []).append(index)
    exact_duplicates = [
        positions for positions in normalized_inputs.values() if len(positions) > 1
    ]
    if exact_duplicates:
        emit(
            "dataset-duplicates",
            FAIL if synthetic else WARN,
            f"exact/normalized duplicate inputs at rows {exact_duplicates[:10]}",
        )
    else:
        emit("dataset-duplicates", PASS, "no exact or normalized duplicate inputs")

    if len(rows) <= MAX_NEAR_DUPLICATE_ROWS:
        near_pairs: list[tuple[int, int]] = []
        sets = [token_set(row["input"]) for row in rows]
        for left in range(len(sets)):
            for right in range(left + 1, len(sets)):
                union = sets[left] | sets[right]
                similarity = (
                    len(sets[left] & sets[right]) / len(union) if union else 1.0
                )
                if similarity >= NEAR_DUPLICATE_THRESHOLD:
                    near_pairs.append((left + 1, right + 1))
        if near_pairs:
            emit(
                "dataset-near-duplicates",
                FAIL if synthetic else WARN,
                f"near-duplicate input pairs: {near_pairs[:10]}",
            )
        else:
            emit("dataset-near-duplicates", PASS, "no high-similarity input pairs")
    else:
        emit(
            "dataset-near-duplicates",
            SKIP,
            f"{len(rows)} rows exceeds the local pairwise-check limit of {MAX_NEAR_DUPLICATE_ROWS}",
        )

    outputs = [normalized_text(row["output"]) for row in rows]
    output_counts = Counter(outputs)
    if any(not output for output in outputs):
        emit("dataset-outputs", FAIL, "one or more expected outputs are empty")
    elif len(set(outputs)) == 1:
        emit(
            "dataset-outputs",
            FAIL if synthetic else WARN,
            "every expected output is identical; evaluator discrimination is likely degenerate",
        )
    else:
        emit("dataset-outputs", PASS, f"{len(set(outputs))} distinct expected outputs")
        dominant_count = max(output_counts.values())
        dominant_ratio = dominant_count / len(outputs)
        if dominant_ratio >= DOMINANT_OUTPUT_RATIO:
            emit(
                "dataset-ceiling-risk",
                WARN,
                f"{dominant_count}/{len(outputs)} expected outputs "
                f"({dominant_ratio:.1%}) are identical; a majority-only strategy "
                "could hide meaningful failures",
            )

    splits: dict[str, set[str]] = {}
    for row in rows:
        split = row_metadata_value(row, "split")
        if split:
            splits.setdefault(str(split).casefold(), set()).add(
                normalized_text(row["input"])
            )
    tune_names = {"tune", "tuning", "train", "search"}
    holdout_names = {"holdout", "test", "validation", "validate"}
    tune_inputs = set().union(
        *(values for name, values in splits.items() if name in tune_names)
    )
    holdout_inputs = set().union(
        *(values for name, values in splits.items() if name in holdout_names)
    )
    overlap = tune_inputs & holdout_inputs
    if overlap:
        emit("dataset-split", FAIL, f"{len(overlap)} inputs overlap tuning and holdout")
    elif tune_inputs and holdout_inputs:
        emit("dataset-split", PASS, "tuning and holdout inputs are disjoint")
    else:
        emit("dataset-split", WARN, "no explicit tuning/holdout split was found")

    difficulty_values = [
        str(row_metadata_value(row, "difficulty")).casefold().replace("_", "-")
        for row in rows
        if row_metadata_value(row, "difficulty")
    ]
    difficulties = set(difficulty_values)
    if difficulty_values and difficulties == {"easy"}:
        emit(
            "dataset-difficulty",
            FAIL if synthetic else WARN,
            f"all {len(difficulty_values)} difficulty-tagged rows are easy; "
            "a ceiling effect may leave configurations indistinguishable",
        )
    elif (
        not synthetic and difficulty_values and not difficulties & {"hard", "very-hard"}
    ):
        emit(
            "dataset-difficulty",
            WARN,
            f"none of {len(difficulty_values)} difficulty-tagged rows are hard or "
            "very-hard; boundary and failure-mode coverage may be missing",
        )
    elif not synthetic and EXPECTED_DIFFICULTIES <= difficulties:
        emit("dataset-difficulty", PASS, "all four difficulty bands are represented")

    if synthetic:
        missing_difficulties = EXPECTED_DIFFICULTIES - difficulties
        if missing_difficulties:
            emit(
                "dataset-difficulty",
                FAIL,
                f"synthetic data is missing difficulty bands: {sorted(missing_difficulties)}",
            )
        else:
            emit(
                "dataset-difficulty", PASS, "all four difficulty bands are represented"
            )
        scenario_count = len(
            {
                str(row_metadata_value(row, "coverage"))
                for row in rows
                if row_metadata_value(row, "coverage")
            }
        )
        if scenario_count < 4:
            emit(
                "dataset-coverage",
                WARN,
                f"only {scenario_count} distinct coverage/scenario tags were found",
            )
        else:
            emit("dataset-coverage", PASS, f"{scenario_count} distinct scenario tags")

    return rows


def parse_function_spec(spec: str, check: str) -> StaticSignature | None:
    file_part, separator, function_name = spec.partition(":")
    if not separator or not function_name:
        emit(check, FAIL, f"'{spec}' must use FILE.py:FUNCTION")
        return None
    path = Path(file_part)
    if not path.exists():
        emit(check, FAIL, f"{path} does not exist")
        return None
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError as error:
        emit(check, FAIL, f"{path}:{error.lineno} has invalid Python syntax")
        return None
    node = next(
        (
            item
            for item in tree.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == function_name
        ),
        None,
    )
    if node is None:
        emit(check, FAIL, f"{path} has no function named '{function_name}'")
        return None

    positional_only = [argument.arg for argument in node.args.posonlyargs]
    positional_nodes = [*node.args.posonlyargs, *node.args.args]
    positional = [argument.arg for argument in positional_nodes]
    keyword_only = [argument.arg for argument in node.args.kwonlyargs]
    defaults: dict[str, str] = {}
    positional_default_offset = len(positional_nodes) - len(node.args.defaults)
    for index, default in enumerate(node.args.defaults, positional_default_offset):
        defaults[positional[index]] = ast.unparse(default)
    for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        if default is not None:
            defaults[argument.arg] = ast.unparse(default)
    required = [name for name in [*positional, *keyword_only] if name not in defaults]
    return StaticSignature(
        name=function_name,
        positional_only=positional_only,
        positional=positional,
        keyword_only=keyword_only,
        required=required,
        defaults=defaults,
        has_varargs=node.args.vararg is not None,
        has_kwargs=node.args.kwarg is not None,
        is_async=isinstance(node, ast.AsyncFunctionDef),
    )


def check_binding(rows: list[dict[str, Any]], agent_spec: str) -> None:
    signature = parse_function_spec(agent_spec, "dataset-binding")
    if signature is None:
        return
    named = set(signature.positional) | set(signature.keyword_only)
    dict_rows = [row for row in rows if isinstance(row["input"], dict)]
    if not dict_rows:
        required_positional = [
            name
            for name in signature.positional
            if name in signature.required and name not in {"self", "cls"}
        ]
        if not signature.positional and not signature.has_varargs:
            emit(
                "dataset-binding",
                FAIL,
                "scalar input has no positional parameter to bind",
            )
        elif len(required_positional) > 1 and not signature.has_varargs:
            emit(
                "dataset-binding",
                FAIL,
                "scalar input cannot satisfy multiple required parameters: "
                f"{required_positional}",
            )
        else:
            emit(
                "dataset-binding", PASS, "scalar input can bind to the first parameter"
            )
        return

    input_keys = set().union(*(row["input"].keys() for row in dict_rows))
    top_level_keys = set().union(
        *({key for key in row if key not in {"input", "output"}} for row in dict_rows)
    )
    failed = False
    for key in sorted(input_keys):
        if key not in named and not signature.has_kwargs:
            failed = True
            emit(
                "dataset-binding", FAIL, f"input key '{key}' matches no agent parameter"
            )
    for name in signature.required:
        if name in {"self", "cls"}:
            continue
        missing_rows = [
            index for index, row in enumerate(dict_rows, 1) if name not in row["input"]
        ]
        if missing_rows:
            failed = True
            emit(
                "dataset-binding",
                FAIL,
                f"required agent parameter '{name}' is missing from rows {missing_rows[:10]}",
            )
    for name, default in signature.defaults.items():
        if name not in input_keys and name in top_level_keys:
            failed = True
            emit(
                "dataset-binding",
                FAIL,
                f"'{name}' is top-level only and would stay at default {default}; copy it into input",
            )
    if not failed:
        emit(
            "dataset-binding", PASS, f"all {len(input_keys)} input keys bind statically"
        )


def check_scorer_signature(scorer_spec: str) -> None:
    signature = parse_function_spec(scorer_spec, "scorer-signature")
    if signature is None:
        return
    if signature.is_async:
        emit("scorer-signature", FAIL, "async metric functions are not awaited")
        return
    if signature.positional_only:
        emit(
            "scorer-signature",
            FAIL,
            "SDK metric parameters must be keyword-bindable; positional-only "
            f"parameters found: {signature.positional_only}",
        )
        return
    named = set(signature.positional) | set(signature.keyword_only)
    if "output" not in named:
        emit(
            "scorer-signature",
            FAIL,
            "declare an explicit 'output' parameter; add an adapter instead of aliases",
        )
        return
    unsupported_required = [
        name for name in signature.required if name not in SCORER_NAMES
    ]
    if unsupported_required:
        emit(
            "scorer-signature",
            FAIL,
            "required parameters are not supported by the SDK metric binder: "
            f"{unsupported_required}",
        )
        return
    emit(
        "scorer-signature",
        PASS,
        "signature is statically compatible; evaluator code was not imported or executed",
    )
    emit(
        "scorer-calibration",
        SKIP,
        "run calibrate_evaluator.py separately with good, equivalent-good, partial, and bad probes",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Traigent first-run static preflight (zero provider/backend calls)."
    )
    parser.add_argument("--env", default=".env", help="path to the local .env")
    parser.add_argument(
        "--models", default="", help="comma-separated LiteLLM model ids"
    )
    parser.add_argument("--dataset", help="JSONL dataset to validate")
    parser.add_argument("--agent", help="FILE.py:FUNC for static dataset binding")
    parser.add_argument("--scorer", help="FILE.py:FUNC for static signature validation")
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable results"
    )
    parser.add_argument("--strict", action="store_true", help="exit 1 on warnings")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env, file_values = read_env(Path(args.env))
    check_python()
    check_sdk()
    check_keys(env)
    check_cost_settings(env, file_values)

    models = [model.strip() for model in args.models.split(",") if model.strip()]
    check_models(models)

    rows = check_dataset(Path(args.dataset)) if args.dataset else None
    if args.agent and rows is not None:
        check_binding(rows, args.agent)
    elif args.agent:
        emit("dataset-binding", SKIP, "--agent requires a valid --dataset")
    if args.scorer:
        check_scorer_signature(args.scorer)

    if args.json:
        print(json.dumps([asdict(result) for result in RESULTS], indent=2))
    else:
        width = max(len(result.check) for result in RESULTS)
        for result in RESULTS:
            print(f"{result.check:<{width}}  {result.status:<4}  {result.detail}")
        counts = {
            status: sum(result.status == status for result in RESULTS)
            for status in (PASS, WARN, FAIL, SKIP)
        }
        print(
            f"\n{counts[PASS]} pass, {counts[WARN]} warn, "
            f"{counts[FAIL]} fail, {counts[SKIP]} skipped"
        )

    if any(result.status == FAIL for result in RESULTS):
        return 1
    if args.strict and any(result.status == WARN for result in RESULTS):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Static, zero-call preflight for a Traigent first run.

This command reads local files and installed-package metadata only. It never imports
user modules, executes an agent or evaluator, contacts an LLM provider, contacts
Traigent, or consumes optimization quota.

Use ``calibrate_evaluator.py`` separately to execute evaluator probes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
SUPPORTED_PYTHON_MIN = (3, 11)
SUPPORTED_PYTHON_MAX = (3, 14)
SUPPORTED_TRAIGENT_VERSION = "0.25.0"
MAX_NEAR_DUPLICATE_ROWS = 500
NEAR_DUPLICATE_THRESHOLD = 0.9
DOMINANT_OUTCOME_RATIO = 0.9
MAX_REPORTED_DATASET_ERRORS = 5
EXPECTED_DIFFICULTIES = {"easy", "medium", "hard", "very-hard"}
COMMON_OUTCOME_FIELDS = (
    "label",
    "category",
    "class",
    "intent",
    "decision",
    "status",
    "type",
    "grade",
)
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


@dataclass(frozen=True)
class Result:
    check: str
    status: str
    detail: str
    metrics: dict[str, Any] | None = None


RESULTS: list[Result] = []


def emit(
    check: str, status: str, detail: str, metrics: dict[str, Any] | None = None
) -> None:
    """Record one check.

    `detail` is prose for a human. `metrics` carries the same facts as data so a
    downstream reader (the readiness scorer) can consume them without parsing
    the sentence - a wording change should never alter a score.
    """
    RESULTS.append(Result(check, status, detail, metrics))


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


def check_env_permissions(path: Path) -> None:
    """Require owner-only access before a local file receives secrets."""
    if not path.exists():
        return
    if os.name == "nt":
        emit(
            "env-permissions",
            SKIP,
            "POSIX mode checks are unavailable; protect this file with the platform ACL",
        )
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        emit(
            "env-permissions",
            FAIL,
            f"{path} mode is {mode:04o}; set owner-only mode 0600 before entering secrets",
        )
    else:
        emit("env-permissions", PASS, f"{path} mode is 0600")


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


def check_sdk(*, defer_missing: bool = False) -> None:
    try:
        installed = version("traigent")
    except PackageNotFoundError:
        if defer_missing:
            emit(
                "sdk-version",
                SKIP,
                "traigent is not installed yet; verify it in the isolated environment after installation",
            )
        else:
            emit(
                "sdk-version",
                FAIL,
                "traigent is not installed in the active interpreter",
            )
        return
    if installed != SUPPORTED_TRAIGENT_VERSION:
        emit(
            "sdk-version",
            FAIL,
            f"traigent {installed} is unsupported for this tested first run; "
            f"install traigent=={SUPPORTED_TRAIGENT_VERSION}",
        )
    else:
        emit("sdk-version", PASS, f"traigent {installed}")


def check_keys(env: dict[str, str | None]) -> None:
    available = [
        vendor
        for vendor, names in VENDOR_KEYS.items()
        if any(key_present(env.get(name)) for name in names)
    ]
    bedrock_present = [name for name in BEDROCK_KEYS if key_present(env.get(name))]
    if len(bedrock_present) == len(BEDROCK_KEYS):
        available.append("Bedrock")
    elif bedrock_present:
        emit(
            "provider-credentials",
            WARN,
            "Bedrock credentials are incomplete; access key, secret, and region are required",
        )

    if not available:
        emit(
            "provider-credentials",
            WARN,
            "no LLM provider credentials are available; inspect the agent route separately, "
            "and do not begin paid work until that route's credential is present",
        )
    else:
        emit(
            "provider-credentials",
            PASS,
            f"credential names are available for {', '.join(available)}; "
            "this inventory does not select or change the agent's provider route",
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
        emit(
            "cost-cap",
            PASS,
            "no custom per-optimization cap; the installed SDK default applies",
        )
    else:
        try:
            cap = float(raw_cap)
        except (TypeError, ValueError):
            emit("cost-cap", FAIL, "TRAIGENT_RUN_COST_LIMIT must be a positive number")
        else:
            if cap <= 0:
                emit("cost-cap", FAIL, "TRAIGENT_RUN_COST_LIMIT must be positive")
            else:
                emit("cost-cap", PASS, f"custom per-optimization cap: ${cap:.2f}")

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


def dataset_field_value(row: dict[str, Any], field_path: str) -> tuple[bool, Any]:
    value: Any = row
    for part in field_path.split("."):
        if not part or not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value


def normalize_dataset_row(
    row: dict[str, Any],
    input_field: str = "input",
    expected_field: str = "output",
) -> tuple[dict[str, Any] | None, str | None]:
    """Project explicitly selected fields into the local quality-check shape.

    This deliberately does not assert SDK compatibility. Exact dataset normalization
    belongs to the installed SDK's public validation and loading paths.
    """

    if input_field == expected_field:
        return (
            None,
            "input and expected-output field paths must be different",
        )

    input_found, input_value = dataset_field_value(row, input_field)
    if not input_found:
        return (
            None,
            f"missing selected input field '{input_field}'",
        )

    expected_found, expected_value = dataset_field_value(row, expected_field)
    if not expected_found:
        return (
            None,
            f"missing selected expected-output field '{expected_field}'",
        )

    normalized = dict(row)
    normalized["input"] = input_value
    normalized["output"] = expected_value
    return normalized, None


def normalized_text(value: Any) -> str:
    text = stable_json(value) if not isinstance(value, str) else value
    return " ".join(re.findall(r"\w+", text.casefold()))


def token_set(value: Any) -> set[str]:
    return set(normalized_text(value).split())


SYNTHETIC_SOURCE_PREFIXES = ("synthetic", "generated", "walkthrough", "mock")


def is_synthetic(row: dict[str, Any]) -> bool:
    """Report whether a row's declared provenance is generated, not collected.

    Prefix matching, not equality: the walkthrough dataset this skill generates
    declares `"source": "synthetic-walkthrough"`, so an exact `== "synthetic"`
    test returned False for our own generated rows and silently disabled every
    escalation below that depends on it.
    """
    source = row.get("source")
    if source is None and isinstance(row.get("metadata"), dict):
        source = row["metadata"].get("source")
    if source is None:
        return False
    normalized = str(source).casefold().strip()
    return normalized.startswith(SYNTHETIC_SOURCE_PREFIXES)


def row_metadata_value(row: dict[str, Any], key: str) -> Any:
    if key in row:
        return row[key]
    metadata = row.get("metadata")
    return metadata.get(key) if isinstance(metadata, dict) else None


def nested_output_value(output: Any, field_path: str) -> tuple[bool, Any]:
    value = output
    for part in field_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value


def structured_outcomes(
    rows: list[dict[str, Any]], outcome_field: str | None
) -> tuple[str, list[Any]] | None:
    fields = (outcome_field,) if outcome_field else COMMON_OUTCOME_FIELDS
    for field in fields:
        values: list[Any] = []
        for row in rows:
            found, value = nested_output_value(row["output"], field)
            if not found or isinstance(value, (dict, list)) or value is None:
                values = []
                break
            values.append(value)
        if values:
            return field, values

    if outcome_field:
        emit(
            "dataset-outcome-field",
            FAIL,
            f"output field '{outcome_field}' is missing or non-scalar in one or more rows",
        )
    return None


def check_dataset(
    path: Path,
    outcome_field: str | None = None,
    input_field: str = "input",
    expected_field: str = "output",
) -> list[dict[str, Any]] | None:
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
        normalized_row, normalization_error = normalize_dataset_row(
            row,
            input_field=input_field,
            expected_field=expected_field,
        )
        if normalization_error is not None:
            invalid_rows.append((line_number, normalization_error))
            continue
        if normalized_row is None:
            raise RuntimeError("dataset normalization returned no row without an error")
        rows.append(normalized_row)

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
    labelled = sum(
        1 for row in rows if str(row.get("output", "")).strip() not in ("", "None")
    )
    declared_sources = {
        str(
            row.get("source") or (row.get("metadata") or {}).get("source") or "unknown"
        ).casefold()
        for row in rows
    }
    emit(
        "dataset-provenance",
        WARN if synthetic else PASS,
        (
            "every row declares generated provenance"
            if synthetic
            else f"declared sources: {sorted(declared_sources)}"
        ),
        {
            "rows": len(rows),
            "labelled_rows": labelled,
            "synthetic": synthetic,
            "sources": sorted(declared_sources),
        },
    )
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
        if dominant_ratio >= DOMINANT_OUTCOME_RATIO:
            emit(
                "dataset-ceiling-risk",
                WARN,
                f"{dominant_count}/{len(outputs)} expected outputs "
                f"({dominant_ratio:.1%}) are identical; a majority-only strategy "
                "could hide meaningful failures",
            )

    structured = structured_outcomes(rows, outcome_field)
    if structured:
        field, values = structured
        normalized_values = [normalized_text(value) for value in values]
        value_counts = Counter(normalized_values)
        dominant_count = max(value_counts.values())
        dominant_ratio = dominant_count / len(normalized_values)
        if dominant_ratio >= DOMINANT_OUTCOME_RATIO:
            emit(
                "dataset-ceiling-risk",
                WARN,
                f"{dominant_count}/{len(values)} values ({dominant_ratio:.1%}) in "
                f"output field '{field}' are identical; a majority-only strategy "
                "could hide meaningful failures",
            )
        else:
            emit(
                "dataset-outcome-field",
                PASS,
                f"output field '{field}' has {len(value_counts)} distinct values",
            )

    splits: dict[str, set[str]] = {}
    split_counts: Counter[str] = Counter()
    for row in rows:
        split = row_metadata_value(row, "split")
        if split:
            split_name = str(split).casefold()
            split_counts[split_name] += 1
            splits.setdefault(split_name, set()).add(normalized_text(row["input"]))
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
        tuning_count = sum(
            count for name, count in split_counts.items() if name in tune_names
        )
        holdout_count = sum(
            count for name, count in split_counts.items() if name in holdout_names
        )
        if tuning_count < 10:
            emit(
                "dataset-tuning-size",
                WARN,
                f"{tuning_count} tuning rows is a wiring check, not a credible optimization score",
                {"tuning_rows": tuning_count},
            )
        else:
            emit(
                "dataset-tuning-size",
                PASS,
                f"{tuning_count} tuning rows",
                {"tuning_rows": tuning_count},
            )
        emit(
            "dataset-holdout-resolution",
            WARN if holdout_count < 10 else PASS,
            f"{holdout_count} holdout rows; one example changes the score by "
            f"{(100 / holdout_count):.1f} percentage points",
            {"holdout_rows": holdout_count},
        )
    else:
        emit("dataset-split", WARN, "no explicit tuning/holdout split was found")

    difficulty_values = [
        str(row_metadata_value(row, "difficulty")).casefold().replace("_", "-")
        for row in rows
        if row_metadata_value(row, "difficulty")
    ]
    difficulties = set(difficulty_values)
    emit(
        "dataset-difficulty-coverage",
        PASS if EXPECTED_DIFFICULTIES <= difficulties else WARN,
        (
            f"{len(difficulty_values)} of {len(rows)} rows carry a difficulty tag; "
            f"bands present: {sorted(difficulties) or 'none'}"
        ),
        {
            "tagged_rows": len(difficulty_values),
            "total_rows": len(rows),
            "bands": sorted(difficulties),
            "missing_bands": sorted(EXPECTED_DIFFICULTIES - difficulties),
        },
    )
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Traigent first-run static preflight (zero provider/backend calls)."
    )
    parser.add_argument("--env", default=".env", help="path to the local .env")
    parser.add_argument(
        "--models", default="", help="comma-separated LiteLLM model ids"
    )
    parser.add_argument("--dataset", help="JSONL dataset to validate")
    parser.add_argument(
        "--input-field",
        default="input",
        help=(
            "dot path used only by local quality checks (default: input); "
            "this does not configure or validate SDK loading"
        ),
    )
    parser.add_argument(
        "--expected-field",
        default="output",
        help=(
            "dot path used only by local quality checks (default: output); "
            "this does not configure or validate SDK loading"
        ),
    )
    parser.add_argument(
        "--outcome-field",
        help="dot path for a structured discrete outcome, such as category or result.label",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable results"
    )
    parser.add_argument(
        "--defer-missing-sdk",
        action="store_true",
        help="report an absent SDK as deferred during the mandatory pre-install component pass",
    )
    parser.add_argument("--strict", action="store_true", help="exit 1 on warnings")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env_path = Path(args.env)
    env, file_values = read_env(env_path)
    check_env_permissions(env_path)
    check_python()
    check_sdk(defer_missing=args.defer_missing_sdk)
    check_keys(env)
    check_cost_settings(env, file_values)

    models = [model.strip() for model in args.models.split(",") if model.strip()]
    check_models(models)

    if args.dataset:
        check_dataset(
            Path(args.dataset),
            outcome_field=args.outcome_field,
            input_field=args.input_field,
            expected_field=args.expected_field,
        )

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

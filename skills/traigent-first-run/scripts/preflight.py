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
import json
import os
import re
import stat
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Sequence

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
SUPPORTED_PYTHON_MIN = (3, 11)
SUPPORTED_PYTHON_MAX = (3, 14)
SUPPORTED_TRAIGENT_VERSION = "0.25.0"
# Jaccard similarity over normalized word sets. This is the only number the
# repetition deduction now rests on (traigent-first-run#158), and nothing
# derives it: it is order-blind, so a reordered sentence scores 1.0, and it is
# length-sensitive, so one changed word clears 0.9 at 19 tokens and never does
# below that. What it should be is an open owner question
# (traigent-first-run#170); until it is answered the user-facing text calls it
# a chosen line rather than a discovered one.
NEAR_DUPLICATE_THRESHOLD = 0.9
# How many near-duplicate pairs the scan will collect before it stops. A display
# bound, not a limit on what is checked: the emit prints ten, and a dataset with
# a thousand near-duplicate pairs has already answered the only question this
# check asks. Bounded so one very repetitive dataset cannot materialize millions
# of tuples.
MAX_NEAR_DUPLICATE_PAIRS = 1000
# A ceiling on the WORK the near-duplicate join may do - never on the number of
# rows it will look at. The join below is exact, so this bounds the datasets it
# cannot finish, not the ordinary path. Reaching it cannot produce a clean
# result: the caller emits SKIP, and readiness reads a SKIP as unchecked.
#
# This replaced a 500-row ceiling above which the check emitted SKIP and stopped
# running. Nothing downstream distinguished that SKIP from a pass, so every
# dataset over 500 rows silently lost near-duplicate detection - precisely the
# size at which duplicates become likely (traigent-first-run#151).
#
# COUNTED IN TOKEN OPERATIONS, and that is the correction. It used to count
# distinct candidate PAIRS, which is not what the loop spends: a pair costs one
# posting-list step to find and then a set union and intersection over both
# rows' tokens, so a row of 300 tokens costs 600 units where a row of 12 costs
# 24. Bounding the pair count therefore bounded nothing on exactly the datasets
# that are slow. Measured on 2,000 RAG-shaped rows of 300 tokens: 1.7M candidate
# pairs - 34% of a 5,000,000 pair budget, so it never fired - and 1.03 BILLION
# token operations, which ran for 45 s with no output and no timeout and then
# answered PASS. Trunk took 0.24 s on the same file.
#
# The number is derived from wall clock and nothing else. This loop sustains
# 15-22M token operations per second across the shapes measured (2,000x300 RAG
# chunks, 5,000 rows over a 60-word vocabulary, 5,000 short rows), so 60M is
# about three to four seconds - long enough that no ordinary dataset reaches it
# and short enough that a user is not left watching a script that will not
# answer. Re-derive it if the loop's inner work changes; do not move it because
# a dataset wanted more.
MAX_NEAR_DUPLICATE_WORK = 60_000_000
DOMINANT_OUTCOME_RATIO = 0.9
MAX_REPORTED_DATASET_ERRORS = 5
MAX_REPORTED_DATASET_IDS = 10
WIRING_CHECK_EXAMPLES = 10
EXPECTED_DIFFICULTIES = {"easy", "medium", "hard", "very-hard"}
REFERENCE_FREE_METHODS = {
    "llm-judge-pointwise",
    "llm-judge-pairwise",
    "llm-judge-rubric",
}
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
    require_expected: bool = True,
) -> tuple[dict[str, Any] | None, str | None]:
    """Project explicitly selected fields into the local quality-check shape.

    This deliberately does not assert SDK compatibility. Exact dataset normalization
    belongs to the installed SDK's public validation and loading paths. A declared
    reference-free evaluator may project a missing expectation to ``None``.
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
    if not expected_found and require_expected:
        return (
            None,
            f"missing selected expected-output field '{expected_field}'",
        )
    if not expected_found:
        expected_value = None

    normalized = dict(row)
    normalized["input"] = input_value
    normalized["output"] = expected_value
    return normalized, None


def dataset_row_is_labelled(
    row: dict[str, Any], expected_field: str = "output"
) -> bool:
    """Report whether a normalized row carries a usable expected output.

    A row is unlabelled when the expected output is absent, JSON `null`, or a
    blank string; anything else is a label the evaluator can score against.

    The `is None` test reads the *raw* value on purpose. Stringifying first -
    `str(row.get("output", "")).strip() not in ("", "None")` - cannot tell a
    missing label from the legitimate one-word label "None", because Python
    renders the null as the same four characters. A two-class dataset whose
    negative class is literally "None" (a no-intent / none-of-the-above class,
    or a pandas round-trip) then had exactly the rows carrying that label - half
    the dataset - reported as unscoreable while the other class stayed labelled,
    which clamped the power subscore and printed a false "N scoreable" marker.
    Do not collapse this back into a single stringified comparison.

    One definition, used by both the aggregate `labelled_rows` count and the
    per-split counts, so the two can never disagree about the same row.

    `expected_field` exists so the one definition also works on a RAW row, where
    the answer still sits under the user's own field name. The default keeps
    every normalized-row caller unchanged; the split loop passes the real field,
    because reading `row["output"]` off a raw row under `--expected-field answer`
    silently counts every answered row as unlabelled.
    """

    found, value = dataset_field_value(row, expected_field)
    if not found or value is None:
        return False
    return str(value).strip() != ""


def normalized_text(value: Any) -> str:
    text = stable_json(value) if not isinstance(value, str) else value
    return " ".join(re.findall(r"\w+", text.casefold()))


def normalized_identity(value: Any) -> str:
    """Normalize equality without collapsing distinct symbol-only values."""
    words = normalized_text(value)
    if words:
        return words
    text = value if isinstance(value, str) else stable_json(value)
    return text.strip().casefold()


def token_set(value: Any) -> set[str]:
    return set(normalized_text(value).split())


def near_duplicate_prefix(
    tokens: set[str], rank: dict[str, int], threshold: float
) -> list[str]:
    """The tokens of one row that must be indexed for an exact threshold join.

    Prefix filtering (Chaudhuri et al.): order every token by a global ranking,
    and two sets whose Jaccard similarity is at least `threshold` must share a
    token inside their prefixes. Suppose they do not, and let `w` be the
    lowest-ranked token they have in common. `w` sits outside at least one of
    the two prefixes, so every shared token sits in that set's suffix and the
    intersection is at most `size - prefix`, which is below `threshold * size` -
    contradicting the similarity. So a candidate pair can never be missed by
    looking only at prefixes, and the join stays exact rather than sampled.

    The length uses floor where the derivation uses ceil. Floor is never
    shorter, and a longer prefix only admits extra candidates that the exact
    Jaccard check then rejects - whereas a prefix one token too short drops real
    pairs silently. Binary floating point puts `0.9 * 10` at 9.000000000000002,
    so the rounding direction has to be the one that cannot lose a pair.

    Ranking rarest-first is what makes this cheap: the indexed tokens are the
    ones that share a bucket with almost nothing.
    """
    size = len(tokens)
    length = max(1, min(size, size - int(threshold * size) + 1))
    return sorted(tokens, key=lambda token: rank[token])[:length]


def near_duplicate_pairs(
    token_sets: Sequence[set[str]],
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
    *,
    limit: int | None = None,
    max_work: int | None = None,
) -> tuple[list[tuple[int, int]], bool]:
    """Find every pair of rows at or above `threshold` Jaccard similarity.

    Returns `(pairs, complete)` as 1-based row numbers. `complete` says whether
    the scan examined every candidate it needed to; it is the honest half of the
    answer, because an empty `pairs` means "no near-duplicates" only when the
    scan finished. The caller must not report an incomplete empty scan as a pass.

    Replaces a full pairwise scan that ran only below 500 rows. This one runs at
    any size and returns the same pairs - `tests/test_preflight.py` checks that
    against the pairwise scan on random datasets, because an index that silently
    misses pairs would be the same defect one layer down.

    The two bounds resolve from the module constants at call time rather than in
    the signature's defaults, which bind once at import and cannot then be moved.
    """
    limit = MAX_NEAR_DUPLICATE_PAIRS if limit is None else limit
    max_work = MAX_NEAR_DUPLICATE_WORK if max_work is None else max_work
    pairs: list[tuple[int, int]] = []

    # Rows whose input has no word characters at all ("?", "-", "..."). Their
    # union is empty, which the pairwise scan scored as similarity 1.0, so they
    # were all near-duplicates of each other. Kept, and computed directly rather
    # than through the index, because they share no token to be indexed under.
    empty = [index + 1 for index, tokens in enumerate(token_sets) if not tokens]
    for left in range(len(empty)):
        for right in range(left + 1, len(empty)):
            if len(pairs) >= limit:
                return pairs, False
            pairs.append((empty[left], empty[right]))

    frequency: Counter[str] = Counter()
    for tokens in token_sets:
        frequency.update(tokens)
    rank = {
        token: position
        for position, (token, _count) in enumerate(
            sorted(frequency.items(), key=lambda item: (item[1], item[0]))
        )
    }

    index_by_token: dict[str, list[int]] = {}
    work = 0
    for position, tokens in enumerate(token_sets):
        if not tokens:
            continue
        prefix = near_duplicate_prefix(tokens, rank, threshold)
        seen: set[int] = set()
        for token in prefix:
            postings = index_by_token.get(token, ())
            # Two charges, because there are two costs, and the old accounting
            # counted neither of them.
            #
            # Walking a posting list costs one step per entry whether or not
            # the entry is a candidate this row has already seen - charged here
            # in one O(1) step, before the walk, so the accounting itself is
            # not what makes this slow.
            work += len(postings)
            if work > max_work:
                return sorted(pairs), False
            for other in postings:
                if other in seen:
                    continue
                seen.add(other)
                # And the exact check costs a union and an intersection over
                # both rows' whole token sets. This is where the time actually
                # goes: 1.7M candidate pairs of 300-token rows is 1.03 billion
                # token operations, and counting the pairs alone said 1.7M.
                work += len(tokens) + len(token_sets[other])
                if work > max_work:
                    return sorted(pairs), False
                union = tokens | token_sets[other]
                if len(tokens & token_sets[other]) / len(union) >= threshold:
                    if len(pairs) >= limit:
                        return sorted(pairs), False
                    pairs.append((other + 1, position + 1))
        for token in prefix:
            index_by_token.setdefault(token, []).append(position)
    return sorted(pairs), True


# One question, two answers: was this written, or was it collected? Every token
# below is a spelling of one of those - "synthetic", "generated", "walkthrough"
# (the dataset this skill writes for its own demo) and "mock" are not different
# kinds of data, they are different words for data nobody observed.
#
# Prefix matching, not equality, because real tokens carry qualifiers:
# `synthetic-walkthrough`, `production-2026-q1`. An exact `== "synthetic"` test
# once returned False for this skill's own generated rows, which scored them as
# collected production data and disabled every escalation below.
SYNTHESISED_SOURCE_PREFIXES = (
    "synthetic",
    "synthesis",
    "synthesised",
    "synthesized",
    "generated",
    "generative",
    "llm",
    "gpt",
    "claude",
    "model-written",
    "model-generated",
    "machine-generated",
    "ai-",
    "ai_",
    "walkthrough",
    "mock",
    "fake",
    "placeholder",
    "simulated",
    "template",
)
COLLECTED_SOURCE_PREFIXES = (
    "production",
    "prod",
    "real",
    "collected",
    "observed",
    "logged",
    "log",
    "customer",
    "user",
    "field",
    "human",
    "curated",
    "reviewed",
    "annotated",
    "benchmark",
    "gold",
)
UNDECLARED_SOURCE_TOKENS = {"unknown", "n/a", "na", "none", "null", "tbd", "?"}

# Kept as the historical name so an existing caller/reader keeps working.
SYNTHETIC_SOURCE_PREFIXES = SYNTHESISED_SOURCE_PREFIXES

PROVENANCE_SYNTHESISED = "synthesised"
PROVENANCE_COLLECTED = "collected"
PROVENANCE_UNDECLARED = "undeclared"


def row_provenance(row: dict[str, Any]) -> Any:
    """Return a row's declared provenance token, or None if it declares none.

    Rows declare where their data came from under either `provenance` or the
    older `source` name, at the top level or nested in `metadata`. Reading only
    `source` (the historical name) meant a row that declared
    `metadata.provenance` read as `unknown` - it never earned the production
    band, and a row whose synthetic origin was declared only under `provenance`
    was scored as if it were collected. Both names are read here so the two
    scripts agree on one field.
    """
    metadata = row.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    for candidate in (
        row.get("provenance"),
        metadata.get("provenance"),
        row.get("source"),
        metadata.get("source"),
    ):
        if candidate not in (None, ""):
            return candidate
    return None


def row_output_provenance(row: dict[str, Any]) -> Any:
    """Return where a row's *expected output* came from, or None if undeclared.

    Separate from {@link row_provenance} because a row carries one token for
    itself, and that cannot express the common real shape: genuine collected
    inputs whose expected answers were written by a model rather than observed.
    Declaring it in the row's own token does not work - anything starting with
    a synthetic prefix marks the whole row generated - so it is read from its
    own field, under either name, at the top level or nested in `metadata`, to
    match how `row_provenance` reads its pair.
    """
    metadata = row.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    for candidate in (
        row.get("output_provenance"),
        metadata.get("output_provenance"),
        row.get("output_source"),
        metadata.get("output_source"),
    ):
        if candidate not in (None, ""):
            return candidate
    return None


def has_generated_output(row: dict[str, Any]) -> bool:
    """Report whether a row declares its expected output as generated."""
    source = row_output_provenance(row)
    if source is None:
        return False
    return str(source).casefold().strip().startswith(SYNTHETIC_SOURCE_PREFIXES)


def is_synthetic(row: dict[str, Any]) -> bool:
    """Report whether one row's declared provenance is written, not collected.

    A single row's answer to the one question in {@link classify_provenance}.
    Whether the *dataset* is synthetic is a question about shares, not about any
    one row, and is answered in `emit_dataset_provenance`.
    """
    return classify_provenance(row_provenance(row))[0] == PROVENANCE_SYNTHESISED


def classify_provenance(token: Any) -> tuple[str, bool]:
    """Classify one provenance token, and report whether it was recognised.

    Returns `(class, recognised)`. An unrecognised non-empty token is classified
    `collected` so that a project using its own vocabulary (`crm-export`) keeps
    the score it has today rather than being silently demoted by a word list -
    but `recognised=False` is reported so the caller can say out loud which
    tokens it had to take on trust. Silently reading an unknown word as
    collected production data is the failure this pair exists to make visible.
    """
    if token in (None, ""):
        return PROVENANCE_UNDECLARED, True
    normalized = str(token).casefold().strip()
    if not normalized or normalized in UNDECLARED_SOURCE_TOKENS:
        return PROVENANCE_UNDECLARED, True
    if normalized.startswith(SYNTHESISED_SOURCE_PREFIXES):
        return PROVENANCE_SYNTHESISED, True
    if normalized.startswith(COLLECTED_SOURCE_PREFIXES):
        return PROVENANCE_COLLECTED, True
    return PROVENANCE_COLLECTED, False


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


def emit_dataset_provenance(
    present_rows: list[dict[str, Any]],
    *,
    labelled: int,
    scored_rows: Sequence[dict[str, Any]] = (),
) -> bool:
    """Emit the provenance metric and report whether the data is synthetic.

    `present_rows` are every row that carries an input, whether or not it also
    carries an expected output, so the reported row count reflects the data that
    exists rather than only the fully-labelled subset. `labelled` is the count
    that additionally carries a non-empty expected output. Emitting this even
    when no row is labelled is what lets the readiness scorer tell an unlabelled
    dataset (a partial score) apart from an absent one.
    """
    counts = {
        PROVENANCE_COLLECTED: 0,
        PROVENANCE_SYNTHESISED: 0,
        PROVENANCE_UNDECLARED: 0,
    }
    unrecognised: set[str] = set()
    declared_sources: set[str] = set()
    for row in present_rows:
        token = row_provenance(row)
        declared_sources.add(str(token or "unknown").casefold())
        provenance_class, recognised = classify_provenance(token)
        counts[provenance_class] += 1
        if not recognised:
            unrecognised.add(str(token).casefold().strip())

    total = len(present_rows)
    # Counted, not `any()`. One generated row in a thousand collected ones used
    # to mark the whole dataset generated - scoring 3 of 10 and capping the run
    # at 65 - while the detail line said "every row declares generated
    # provenance", which was false for every mixture. The scorer needs the
    # shares to answer "how much of this is invented", so they are reported here
    # and `synthetic` keeps its name meaning what it says: all of it.
    synthetic = total > 0 and counts[PROVENANCE_SYNTHESISED] == total

    # A row whose own token is synthesised is already counted there; this is the
    # other shape - collected inputs whose expected answers were written by a
    # model. Scanned over rows that actually carry an expected output, through
    # the same `dataset_row_is_labelled` predicate the aggregate and per-split
    # counts use: a row with no answer cannot have a generated one, and
    # answering "does this row have an output" with a private test here is how
    # the checks in this file came to disagree about the same row (#68, #70).
    answerable = [row for row in scored_rows if dataset_row_is_labelled(row)]
    generated_answer_rows = sum(
        1
        for row in answerable
        if has_generated_output(row)
        and classify_provenance(row_provenance(row))[0] != PROVENANCE_SYNTHESISED
    )
    generated_outputs = generated_answer_rows > 0

    def _share(count: int, of: int) -> float:
        return round(count / of, 4) if of else 0.0

    synthesised_share = _share(counts[PROVENANCE_SYNTHESISED], total)
    if synthetic:
        detail = f"all {total} rows declare generated provenance"
    elif counts[PROVENANCE_SYNTHESISED]:
        detail = (
            f"{counts[PROVENANCE_SYNTHESISED]} of {total} rows declare generated "
            f"provenance ({synthesised_share:.0%}); declared sources: "
            f"{sorted(declared_sources)}"
        )
    elif generated_outputs:
        detail = (
            f"declared sources: {sorted(declared_sources)}; "
            f"{generated_answer_rows} of {len(answerable)} expected outputs "
            "declare generated provenance"
        )
    else:
        detail = f"declared sources: {sorted(declared_sources)}"
    emit(
        "dataset-provenance",
        WARN if counts[PROVENANCE_SYNTHESISED] else PASS,
        detail,
        {
            "rows": total,
            "labelled_rows": labelled,
            "synthetic": synthetic,
            "generated_outputs": generated_outputs,
            "collected_rows": counts[PROVENANCE_COLLECTED],
            "synthesised_rows": counts[PROVENANCE_SYNTHESISED],
            "undeclared_rows": counts[PROVENANCE_UNDECLARED],
            "generated_answer_rows": generated_answer_rows,
            "answerable_rows": len(answerable),
            "sources": sorted(declared_sources),
            "unrecognised_sources": sorted(unrecognised),
        },
    )
    if unrecognised:
        # Scored as collected for backward compatibility, so say so rather than
        # let an unknown word quietly earn the production band.
        emit(
            "dataset-provenance-vocabulary",
            WARN,
            f"{sorted(unrecognised)} is not a recognised provenance word and was "
            "treated as collected by the compatibility rule, not verified as real; "
            "declare generated data with a "
            "'synthetic'/'generated' token if that is wrong",
        )
    return synthetic


def stable_id_is_missing(value: Any) -> bool:
    """Treat absent, empty, and whitespace-only IDs as unusable identifiers."""
    return value is None or (isinstance(value, str) and not value.strip())


def emit_dataset_id_findings(
    row_records: list[tuple[int, dict[str, Any]]],
) -> None:
    """Validate IDs across every input-bearing row, including unlabelled rows."""
    missing_records: list[tuple[int, dict[str, Any]]] = []
    ids: list[str] = []
    for line_number, row in row_records:
        value = row_metadata_value(row, "id")
        if stable_id_is_missing(value):
            missing_records.append((line_number, row))
        else:
            ids.append(
                stable_json(value) if isinstance(value, (dict, list)) else str(value)
            )
    if missing_records:
        missing_lines = [line_number for line_number, _row in missing_records]
        generated_missing = sum(
            1
            for _line_number, row in missing_records
            if classify_provenance(row_provenance(row))[0] == PROVENANCE_SYNTHESISED
        )
        shown_lines = missing_lines[:MAX_REPORTED_DATASET_IDS]
        location = (
            f"source line {shown_lines[0]}"
            if len(missing_lines) == 1
            else f"source lines {shown_lines}"
        )
        suffix = (
            ""
            if len(missing_lines) <= len(shown_lines)
            else f" (first {MAX_REPORTED_DATASET_IDS} shown)"
        )
        noun = "row" if len(missing_lines) == 1 else "rows"
        verb = "has" if len(missing_lines) == 1 else "have"
        generated_noun = "row" if generated_missing == 1 else "rows"
        generated_verb = "requires" if generated_missing == 1 else "require"
        generated_detail = (
            f"; {generated_missing} generated {generated_noun} "
            f"{generated_verb} an id"
            if generated_missing
            else ""
        )
        emit(
            "dataset-ids",
            FAIL if generated_missing else WARN,
            f"{len(missing_lines)} {noun} at {location}{suffix} {verb} "
            "no stable id; add stable ids in a working copy before excluding rows "
            f"or selecting a bounded subset, then re-run validation{generated_detail}",
        )
    id_counts = Counter(ids)
    duplicate_ids = sorted(value for value, count in id_counts.items() if count > 1)
    if duplicate_ids:
        emit(
            "dataset-ids",
            FAIL,
            f"duplicate ids: {duplicate_ids[:MAX_REPORTED_DATASET_IDS]}",
        )
    elif not missing_records:
        emit("dataset-ids", PASS, "stable ids are unique")


def check_evaluator(path: Path) -> None:
    """Static, non-executing structural check for the evaluator source file.

    Parses the file with `ast.parse` only. That builds a syntax tree without
    running a single line of the file - no import, no call, no module-level
    side effect - so it never touches provider credentials and never invokes
    whatever the evaluator's own logic does. That is also the honest limit of
    what this check can claim: a file that parses is merely readable as
    Python, not correct. Whether it behaves like a real evaluator - for
    example, whether its score ever depends on the input - is a runtime
    question, and this check does not attempt to answer it. That question
    belongs to `calibrate_evaluator.py`, which answers it deliberately, in a
    credential-stripped subprocess, only after explicit approval
    (traigent-first-run#133).
    """
    if not path.exists():
        emit("evaluator-shape", FAIL, f"{path} does not exist", {"exists": False})
        return
    try:
        source = path.read_text()
    except (OSError, UnicodeDecodeError) as error:
        emit(
            "evaluator-shape",
            FAIL,
            f"{path} could not be read as text: {error}",
            {"exists": True, "parses": False},
        )
        return
    try:
        ast.parse(source, filename=str(path))
    except SyntaxError as error:
        emit(
            "evaluator-shape",
            FAIL,
            f"{path} is not valid Python: {error}",
            {"exists": True, "parses": False},
        )
        return
    except (MemoryError, RecursionError, ValueError) as error:
        # `ast.parse` refuses some inputs without calling them a SyntaxError,
        # and an uncaught one takes the whole process down mid-run - emitting
        # no JSON at all, which silently breaks the `--json` contract
        # `readiness.py --preflight -` reads. A ~50 KB file of chained unary
        # operators is enough: CPython raises `MemoryError: Parser stack
        # overflowed`, not a SyntaxError. `RecursionError` and `ValueError`
        # (older CPythons raise it for embedded null bytes) are the same
        # class of refusal.
        #
        # Reported as `parses: False`, which is the fail-closed reading and
        # the honest one: this check could not establish that the file
        # parses. It deliberately does not claim the file is invalid Python -
        # what happened is that parsing did not complete, and the detail says
        # so, because the remedy either way is to inspect the file.
        emit(
            "evaluator-shape",
            FAIL,
            f"{path} could not be parsed: {type(error).__name__}: {error}",
            {"exists": True, "parses": False},
        )
        return
    emit(
        "evaluator-shape",
        PASS,
        f"{path} parses as valid Python; this proves nothing about its "
        "scoring behavior, which is not executed here",
        {"exists": True, "parses": True},
    )


def check_dataset(
    path: Path,
    outcome_field: str | None = None,
    input_field: str = "input",
    expected_field: str = "output",
    evaluator_method: str | None = None,
) -> list[dict[str, Any]] | None:
    if not path.exists():
        emit("dataset-shape", FAIL, f"{path} does not exist")
        return None

    reference_free = evaluator_method in REFERENCE_FREE_METHODS
    rows: list[dict[str, Any]] = []
    present_rows: list[dict[str, Any]] = []
    present_row_records: list[tuple[int, dict[str, Any]]] = []
    invalid_rows: list[tuple[int, str]] = []
    unlabelled_present = 0
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
            require_expected=not reference_free,
        )
        if normalization_error is not None:
            invalid_rows.append((line_number, normalization_error))
            # A row that carries an input but only lacks its expected output is a
            # present-but-unlabelled data point, not malformed data. It is still
            # unusable for scoring, but tracking it lets the readiness adapter
            # tell "rows exist, none labelled" apart from "no dataset at all".
            input_found, _ = dataset_field_value(row, input_field)
            expected_found, _ = dataset_field_value(row, expected_field)
            if input_found and not expected_found and input_field != expected_field:
                present_rows.append(row)
                present_row_records.append((line_number, row))
                unlabelled_present += 1
            continue
        if normalized_row is None:
            raise RuntimeError("dataset normalization returned no row without an error")
        rows.append(normalized_row)
        present_rows.append(row)
        present_row_records.append((line_number, row))

    malformed_rows = len(invalid_rows) - unlabelled_present
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
            {
                "invalid_rows": len(invalid_rows),
                "malformed_rows": malformed_rows,
                "unlabelled_rows": unlabelled_present,
                "candidate_rows": candidate_count,
            },
        )
    if not rows:
        if present_rows:
            # Rows carry inputs but none carry an expected output: a
            # present-but-unlabelled dataset, not an absent one. Emit provenance
            # so the readiness adapter reaches the "no expected outputs" branch
            # (a partial score) instead of "no dataset at all", then stop - there
            # are no labelled rows to run the remaining quality checks against.
            emit_dataset_provenance(present_rows, labelled=0)
            emit_dataset_id_findings(present_row_records)
            emit(
                "dataset-shape",
                FAIL,
                f"{len(present_rows)} rows carry inputs but none carry an "
                "expected output",
            )
            return None
        emit("dataset-shape", FAIL, "dataset has no usable rows")
        return None
    if not invalid_rows:
        emit("dataset-shape", PASS, f"{len(rows)} valid JSONL rows")
    if len(rows) < WIRING_CHECK_EXAMPLES:
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

    labelled = sum(1 for row in rows if dataset_row_is_labelled(row))
    synthetic = emit_dataset_provenance(
        present_rows, labelled=labelled, scored_rows=rows
    )
    emit_dataset_id_findings(present_row_records)

    normalized_inputs: dict[str, list[int]] = {}
    for index, row in enumerate(rows, 1):
        normalized_inputs.setdefault(normalized_identity(row["input"]), []).append(
            index
        )
    exact_duplicates = [
        positions for positions in normalized_inputs.values() if len(positions) > 1
    ]
    # Both records describe repetition, and the readiness score deducts for it
    # once - `dataset-near-duplicates` is what it deducts on, because identical
    # rows are 100% similar and so are already inside "at least 90% similar".
    # This one is kept because it is a hash bucket: O(n), always complete, and
    # therefore still able to report repetition on a dataset where the bounded
    # near-duplicate join gave up. It detects; it does not score twice.
    if exact_duplicates:
        emit(
            "dataset-duplicates",
            FAIL if synthetic else WARN,
            f"exact/normalized duplicate inputs at rows {exact_duplicates[:10]}",
        )
    else:
        emit("dataset-duplicates", PASS, "no exact or normalized duplicate inputs")

    threshold_percent = f"{NEAR_DUPLICATE_THRESHOLD:.0%}"
    near_pairs, near_complete = near_duplicate_pairs(
        [token_set(row["input"]) for row in rows]
    )
    if near_pairs:
        # A truncated scan still answered the question - there ARE
        # near-duplicates - so it stays a finding rather than becoming a SKIP.
        # What it cannot claim is that these are all of them.
        more = "" if near_complete else "; the scan stopped early, so there may be more"
        emit(
            "dataset-near-duplicates",
            FAIL if synthetic else WARN,
            f"input pairs at least {threshold_percent} similar (shared words "
            f"over total words), identical rows included: {near_pairs[:10]}{more}",
        )
    elif near_complete:
        emit(
            "dataset-near-duplicates",
            PASS,
            f"no input pair reaches {threshold_percent} similarity",
        )
    else:
        # Found nothing AND did not finish, which is not the same statement as
        # "found nothing". The only way here is a dataset so repetitive that the
        # filter admits everything; say that this is unchecked, never clean.
        #
        # And say why it took so long, in terms of the dataset the user is
        # holding. Getting here is the one slow path in this script, so they
        # have just waited and are then told the check did not run; without the
        # second sentence that reads as the script having hung on their data.
        #
        # The sentence that used to be here named only one of the two ways in -
        # "a vocabulary small enough to make nearly every pair a candidate" -
        # and a 2,000-row set of 300-word RAG chunks, which has an ordinary
        # vocabulary, is the other and the slower one. A user reading the old
        # text about their own file would have concluded it did not apply.
        emit(
            "dataset-near-duplicates",
            SKIP,
            "the near-duplicate scan reached its work budget before comparing "
            "every candidate pair, so this dataset is UNCHECKED for "
            "near-duplicates - not clean. The exact check compares whole word "
            "sets, so cost grows with both the number of rows and the length of "
            "each one: long rows (documents, transcripts, retrieved chunks) "
            "reach it soonest, and so do many short rows drawn from a small "
            "vocabulary. Split long inputs, or scan a sample, if you need this "
            "answered",
        )

    unlabelled = [row for row in rows if not dataset_row_is_labelled(row)]
    scoreable_rows = [row for row in rows if dataset_row_is_labelled(row)]
    if reference_free:
        emit(
            "dataset-outputs",
            SKIP,
            f"{evaluator_method} is reference-free; expected outputs are not required",
        )
    else:
        placeholder_outputs = [
            row for row in scoreable_rows if not normalized_text(row["output"])
        ]
        if placeholder_outputs:
            emit(
                "dataset-output-placeholders",
                WARN,
                f"{len(placeholder_outputs)}/{len(rows)} expected outputs carry no "
                'word characters (for example "-", "?" or "...") - confirm '
                "whether these are intentional symbolic labels or placeholders; "
                "they remain in the labelled counts",
                {"placeholder_rows": len(placeholder_outputs), "rows": len(rows)},
            )
        scoreable_outputs = [
            normalized_identity(row["output"]) for row in scoreable_rows
        ]
        output_counts = Counter(scoreable_outputs)
        if unlabelled:
            emit(
                "dataset-outputs",
                FAIL,
                f"{len(unlabelled)}/{len(rows)} expected outputs are empty",
            )
        elif len(scoreable_outputs) < 2:
            # Dominance needs at least two answers to be a statement about
            # anything. One row's single answer holds 100% of the rows by
            # arithmetic, and reporting that charged a 1-row dataset 6 of its
            # 20 diversity points for a finding no dataset of that size can
            # avoid - and told its owner to diversify answers they have one of.
            # The size problem is real and `dataset-size` already says it.
            emit(
                "dataset-outputs",
                PASS,
                f"{len(scoreable_outputs)} expected output, which is too few "
                "for answer spread to mean anything; the row count is the "
                "finding here",
            )
        elif len(output_counts) == 1:
            emit(
                "dataset-outputs",
                FAIL if synthetic else WARN,
                "every expected output is identical; evaluator discrimination is likely degenerate",
            )
            # And say it in the dominance vocabulary too, because this IS the
            # dominance finding at its maximum - one answer holding 100% of the
            # rows. Without this, the branch below is the only place
            # `dataset-ceiling-risk` is raised, and it is unreachable here: it
            # lives under the PASS arm. `_answer_dominance_status` in
            # readiness.py reads a PASS on `dataset-outputs` as its witness that
            # the spread was examined, so the WARN above left it with no record
            # at all and it reported answer dominance as NEVER CHECKED.
            #
            # The consequence was a scoring inversion, which is what makes this
            # worth an extra record rather than a comment: an unmeasured
            # sub-score drops out of the pillar average, so a dataset where
            # every answer is identical scored HIGHER than one where 90% are.
            # A skipped check is not a passed check - and a check that ran and
            # found the worst possible answer must not read as one that never
            # ran.
            emit(
                "dataset-ceiling-risk",
                WARN,
                f"{len(scoreable_outputs)}/{len(scoreable_outputs)} expected "
                "outputs (100.0%) are identical; a majority-only strategy "
                "could hide meaningful failures",
            )
        else:
            emit(
                "dataset-outputs",
                PASS,
                f"{len(output_counts)} distinct expected outputs",
            )
            dominant_count = max(output_counts.values())
            dominant_ratio = dominant_count / len(scoreable_outputs)
            if dominant_ratio >= DOMINANT_OUTCOME_RATIO:
                emit(
                    "dataset-ceiling-risk",
                    WARN,
                    f"{dominant_count}/{len(scoreable_outputs)} expected outputs "
                    f"({dominant_ratio:.1%}) are identical; a majority-only strategy "
                    "could hide meaningful failures",
                )

        structured = structured_outcomes(scoreable_rows, outcome_field)
        if structured:
            field, values = structured
            value_counts = Counter(normalized_identity(value) for value in values)
            dominant_count = max(value_counts.values())
            dominant_ratio = dominant_count / len(values)
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
    labelled_split_counts: Counter[str] = Counter()
    # Iterates `present_rows`, not only normalized scoreable rows (#66). Under a
    # reference-requiring method, a row with no output never reaches `rows`, so a
    # holdout declared that way used to be invisible:
    # preflight reported "no explicit tuning/holdout split was found" about a
    # dataset where every row declared one, and readiness scored it through the
    # no-split branch.
    #
    # The input is resolved through `dataset_field_value` rather than read as
    # `row["input"]`. That subscript is only correct on a normalized row, where
    # "input" is the projected value; on a raw row it is a KeyError under any
    # non-default `--input-field`.
    for row in present_rows:
        split = row_metadata_value(row, "split")
        if split:
            split_name = str(split).casefold()
            split_counts[split_name] += 1
            if dataset_row_is_labelled(row, expected_field):
                labelled_split_counts[split_name] += 1
            _, input_value = dataset_field_value(row, input_field)
            splits.setdefault(split_name, set()).add(normalized_identity(input_value))
    tune_names = {"tune", "tuning", "train", "search"}
    holdout_names = {"holdout", "test", "validation", "validate"}
    tune_inputs = set().union(
        *(values for name, values in splits.items() if name in tune_names)
    )
    holdout_inputs = set().union(
        *(values for name, values in splits.items() if name in holdout_names)
    )
    overlap = tune_inputs & holdout_inputs

    def emit_tuning_size(tuning_count: int, tuning_labelled: int) -> None:
        tuning_scoreable = tuning_count if reference_free else tuning_labelled
        tuning_suffix = (
            ""
            if tuning_scoreable == tuning_count
            else f", {tuning_scoreable} scoreable"
        )
        tuning_metrics = {
            "tuning_rows": tuning_count,
            "tuning_labelled_rows": tuning_labelled,
        }
        if tuning_scoreable < WIRING_CHECK_EXAMPLES:
            emit(
                "dataset-tuning-size",
                WARN,
                f"{tuning_count} tuning rows{tuning_suffix} is a wiring check, "
                "not a credible optimization score",
                tuning_metrics,
            )
        else:
            emit(
                "dataset-tuning-size",
                PASS,
                f"{tuning_count} tuning rows{tuning_suffix}; clears the "
                f"{WIRING_CHECK_EXAMPLES}-row static wiring boundary; "
                "readiness rates comparison size separately",
                tuning_metrics,
            )

    if overlap:
        emit("dataset-split", FAIL, f"{len(overlap)} inputs overlap tuning and holdout")
    elif tune_inputs and holdout_inputs:
        emit(
            "dataset-split",
            PASS,
            "tuning and holdout inputs are disjoint",
            {"kind": "tuning-and-holdout"},
        )
        tuning_count = sum(
            count for name, count in split_counts.items() if name in tune_names
        )
        holdout_count = sum(
            count for name, count in split_counts.items() if name in holdout_names
        )
        tuning_labelled = sum(
            count for name, count in labelled_split_counts.items() if name in tune_names
        )
        holdout_labelled = sum(
            count
            for name, count in labelled_split_counts.items()
            if name in holdout_names
        )
        emit_tuning_size(tuning_count, tuning_labelled)
        holdout_scoreable = holdout_count if reference_free else holdout_labelled
        holdout_metrics = {
            "holdout_rows": holdout_count,
            "holdout_labelled_rows": holdout_labelled,
        }
        if holdout_scoreable == 0:
            # Dividing 100 by the *total* holdout size claimed a per-example
            # resolution the evaluator cannot deliver; with no scoreable holdout
            # row there is no resolution to quote at all, and the old divisor
            # would now be zero.
            holdout_detail = (
                f"{holdout_count} holdout rows, none scoreable; no holdout row "
                "carries an expected output, so this split resolves nothing"
            )
        elif holdout_scoreable == holdout_count:
            holdout_detail = (
                f"{holdout_count} holdout rows; one example changes the score by "
                f"{(100 / holdout_count):.1f} percentage points"
            )
        else:
            holdout_detail = (
                f"{holdout_count} holdout rows, {holdout_scoreable} scoreable; one "
                f"scoreable example changes the score by "
                f"{(100 / holdout_scoreable):.1f} percentage points"
            )
        emit(
            "dataset-holdout-resolution",
            WARN if holdout_scoreable < WIRING_CHECK_EXAMPLES else PASS,
            holdout_detail,
            holdout_metrics,
        )
    elif tune_inputs:
        tuning_count = sum(
            count for name, count in split_counts.items() if name in tune_names
        )
        tuning_labelled = sum(
            count for name, count in labelled_split_counts.items() if name in tune_names
        )
        emit(
            "dataset-split",
            PASS,
            "tuning-only dataset; no independent validation split was declared",
            {"kind": "tuning-only"},
        )
        emit_tuning_size(tuning_count, tuning_labelled)
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
        "--evaluator-method",
        help=(
            "declared method; pointwise, pairwise, and rubric LLM judges allow "
            "input-only rows, while absent or other values require expected outputs"
        ),
    )
    parser.add_argument(
        "--evaluator",
        help=(
            "path to the evaluator source file for a static, non-executing "
            "syntax check (ast.parse only - never imported or run); pass this "
            "whenever an evaluator file was found, even if --evaluator-method "
            "is omitted because no method could be honestly declared for it"
        ),
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
            evaluator_method=args.evaluator_method,
        )

    if args.evaluator:
        check_evaluator(Path(args.evaluator))

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

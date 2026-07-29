#!/usr/bin/env python3
"""Plan and score a Traigent first run from Agent/Dataset/Evaluation evidence.

Two related jobs live here.

`build_plan` answers "what must be created, in what order" from three declared
provenance states. It is a planner: the caller asserts the states.

The scoring half answers "how ready is this project to be optimized at all", by
*measuring* the artifacts instead of accepting a declaration. It consumes the
JSON already emitted by the two sibling scripts - `preflight.py --json` for the
dataset and `calibrate_evaluator.py --json` for the evaluator - plus a config
space describing the agent's knobs, and returns one 0-100 score per pillar and
an aggregate.

The score is deliberately modest about itself. It runs before any optimization,
from local evidence only, so it estimates rather than measures: a sub-score that
cannot be computed is marked unmeasured and excluded rather than scored zero,
and the reported confidence says how much of the pillar was actually observed.
The config space's 'wired' list is the one input that is weaker than that: it is
an attestation, taken at its word and never verified, because nothing here reads
the agent's code. Declaring a knob is not a statement that the agent consumes
it, so a document that never names its wired knobs has attested no wiring and
that pillar reports nothing to search.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

ComponentState = Literal["real", "limited", "demo", "missing", "invalid"]
COMPONENTS = ("agent", "dataset", "evaluation")


@dataclass(frozen=True)
class ReadinessPlan:
    states: dict[str, ComponentState]
    real_ready_count: int
    walkthrough_ready_count: int
    missing_real: list[str]
    create: list[str]
    action: str


def build_plan(
    agent: ComponentState,
    dataset: ComponentState,
    evaluation: ComponentState,
) -> ReadinessPlan:
    """Return the dependency-aware completion plan for one starting state."""
    states: dict[str, ComponentState] = {
        "agent": agent,
        "dataset": dataset,
        "evaluation": evaluation,
    }
    real = {name for name, state in states.items() if state == "real"}
    usable = {
        name for name, state in states.items() if state in {"real", "limited", "demo"}
    }
    missing = [name for name in COMPONENTS if name not in usable]
    limited = [name for name, state in states.items() if state == "limited"]
    invalid = [name for name, state in states.items() if state == "invalid"]

    if limited or invalid:
        create = missing
        action = (
            "Explain each concrete quality issue, recommend repairing a working copy, "
            "and revalidate it. Continue with limited material only as an explicitly "
            "labeled demonstration."
        )
    elif real == set(COMPONENTS):
        create: list[str] = []
        action = "Validate and use all three real components without replacement."
    elif "demo" in states.values():
        create = missing
        action = (
            "Preserve existing walkthrough substitutes, create only missing pieces, "
            "and validate the complete system."
        )
    elif real == {"agent", "dataset"}:
        create = ["evaluation"]
        action = "Build evaluation from the real agent output and dataset expectations."
    elif real == {"agent", "evaluation"}:
        create = ["dataset"]
        action = (
            "Build a dataset that exercises the real agent and matches the evaluation."
        )
    elif real == {"dataset", "evaluation"}:
        create = ["agent"]
        action = (
            "Build an agent whose input and output contracts match both real anchors."
        )
    elif real == {"agent"}:
        create = ["dataset", "evaluation"]
        action = "Build the dataset from the agent contract, then evaluation from both."
    elif real == {"dataset"}:
        create = ["agent", "evaluation"]
        action = "Build an agent from the dataset contract, then evaluation from both."
    elif real == {"evaluation"}:
        create = ["dataset", "agent"]
        action = "Build scoreable data for the evaluation, then an agent matching both."
    elif not real and not usable:
        create = ["agent", "dataset", "evaluation"]
        action = "Ask once for task intent, then build one coherent walkthrough system."
    else:
        create = missing
        action = "Repair invalid components around the real anchors, then validate the system."

    return ReadinessPlan(
        states=states,
        real_ready_count=len(real),
        walkthrough_ready_count=len(usable),
        missing_real=[name for name in COMPONENTS if name not in real],
        create=create,
        action=action,
    )


def render_text(plan: ReadinessPlan) -> str:
    """Render real readiness separately from generated walkthrough substitutes."""
    lines = [f"Real-world readiness: {plan.real_ready_count}/3"]
    for name in COMPONENTS:
        state = plan.states[name]
        if state == "real":
            lines.append(f"✅ {name.title()}: real")
        elif state == "limited":
            lines.append(
                f"❗ {name.title()}: real material exists but evidence is limited"
            )
        elif state == "invalid":
            lines.append(f"❗ {name.title()}: validation failed")
        else:
            lines.append(f"❗ {name.title()}: no real component is connected")

    demo_components = [name for name in COMPONENTS if plan.states[name] == "demo"]
    if demo_components:
        lines.extend(("", "Walkthrough setup:"))
        for name in demo_components:
            lines.append(f"🛠️ {name.title()}: generated walkthrough substitute")

    lines.append(f"Action: {plan.action}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scoring model
#
# Weights are a judgment call, not a measurement: nothing here establishes that
# dataset quality is 1.6x agent knobs. They are exposed through --weights and
# printed in the report so the number stays auditable. Measurement (dataset plus
# evaluation) dominates because a wrong measurement produces confidently wrong
# results, which is worse than a small search space; knobs weigh least because
# they are the cheapest gap to close.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
DEFAULT_WEIGHTS = {"dataset": 40.0, "evaluation": 35.0, "agent": 25.0}
BAND_THRESHOLDS = (
    (30, "NOT READY"),
    (55, "PARTIAL"),
    (75, "WORKABLE"),
    (90, "STRONG"),
    (101, "EXCELLENT"),
)
BAND_ORDER = ["NOT READY", "PARTIAL", "WORKABLE", "STRONG", "EXCELLENT"]
CONFIDENCE_BAND_CEILING = "WORKABLE"
MIN_CONFIDENCE_FOR_TOP_BANDS = 0.75

# Vendored from the installed SDK's canonical presets
# (traigent/config_generator/presets/range_presets.py, read at 0.23.0). The
# scorer runs before any install, so it cannot import them; --verify-against-sdk
# re-reads them when the SDK *is* importable and reports drift without ever
# changing a score. The installed SDK is always authoritative.
CANONICAL_RANGES: dict[str, dict[str, float]] = {
    "temperature": {"low": 0.0, "high": 1.0},
    "top_p": {"low": 0.1, "high": 1.0},
    "frequency_penalty": {"low": 0.0, "high": 2.0},
    "presence_penalty": {"low": 0.0, "high": 2.0},
    "similarity_threshold": {"low": 0.0, "high": 1.0},
    "mmr_lambda": {"low": 0.0, "high": 1.0},
    "chunk_overlap_ratio": {"low": 0.0, "high": 0.5},
    "max_tokens": {"low": 256, "high": 4096},
    "k": {"low": 1, "high": 10},
    "retrieval_k": {"low": 1, "high": 5},
    "chunk_size": {"low": 100, "high": 1000},
    "chunk_overlap": {"low": 0, "high": 200},
    "few_shot_count": {"low": 0, "high": 10},
    "fewshot_k": {"low": 0, "high": 10},
    "batch_size": {"low": 1, "high": 64},
    "n": {"low": 1, "high": 5},
    "top_k": {"low": 1, "high": 100},
    "candidate_count": {"low": 1, "high": 3},
}

# Sweeping a seed measures run-to-run variance, not configuration quality, so it
# neither earns variation credit nor counts as a missing knob.
EXCLUDED_KNOBS = {"seed"}

# `model` has a canonical list, but it is OpenAI-only; a user routing through
# OpenRouter or Bedrock overlaps it at zero. Score breadth, never coverage.
OPEN_CATEGORICAL_KNOBS = {"model", "embedding_model", "reranker_model"}

# Below these deltas two values are the same configuration in practice.
NOISE_FLOORS: dict[str, float] = {"temperature": 0.05, "top_p": 0.05}
DEFAULT_NOISE_FRACTION = 0.02
FULL_SPAN_FRACTION = 0.6
ENDPOINT_TOLERANCE_FRACTION = 0.05

HIGH_IMPACT_KNOBS: dict[str, tuple[str, ...]] = {
    "rag": ("model", "retrieval_k", "temperature", "context_format", "prompt_policy"),
    "code_gen": ("model", "temperature", "fewshot_k", "schema_context", "max_tokens"),
    "general": ("model", "temperature", "prompt_policy", "max_tokens"),
}

# Evaluation-method profiles. `fidelity` is which task kinds the method actually
# measures well; a method can be perfectly reproducible and still be the wrong
# ruler, which is why task fit is scored separately from reproducibility.
METHOD_PROFILES: dict[str, dict[str, Any]] = {
    "exact": {
        "reproducibility": 1.0,
        "cost": 1.0,
        "fits": ("closed-label", "short-answer", "routing", "structured"),
    },
    "normalized-exact": {
        "reproducibility": 1.0,
        "cost": 1.0,
        "fits": ("closed-label", "short-answer", "routing"),
    },
    "numeric-tolerance": {
        "reproducibility": 1.0,
        "cost": 1.0,
        "fits": ("numeric",),
    },
    "set-f1": {
        "reproducibility": 1.0,
        "cost": 1.0,
        "fits": ("extraction", "structured"),
    },
    "schema": {
        "reproducibility": 1.0,
        "cost": 1.0,
        "fits": ("structured",),
    },
    "execution": {
        "reproducibility": 0.9,
        "cost": 1.0,
        "fits": ("code-sql", "code"),
    },
    "routing": {
        "reproducibility": 1.0,
        "cost": 1.0,
        "fits": ("routing", "closed-label"),
    },
    "fuzzy": {
        "reproducibility": 1.0,
        "cost": 1.0,
        "fits": ("short-answer", "free-text"),
    },
    "embedding": {
        "reproducibility": 0.6,
        "cost": 0.7,
        "fits": ("free-text", "short-answer"),
    },
    "llm-judge-pointwise": {
        "reproducibility": 0.2,
        "cost": 0.2,
        "fits": ("free-text",),
    },
    "llm-judge-pairwise": {
        "reproducibility": 0.3,
        "cost": 0.1,
        "fits": ("free-text",),
    },
    "llm-judge-rubric": {
        "reproducibility": 0.45,
        "cost": 0.15,
        "fits": ("free-text", "structured"),
    },
    "composite": {
        "reproducibility": 0.5,
        "cost": 0.5,
        "fits": ("free-text", "structured", "code-sql", "routing"),
    },
}
DETERMINISTIC_METHODS = {
    "exact",
    "normalized-exact",
    "numeric-tolerance",
    "set-f1",
    "schema",
    "execution",
    "routing",
    "fuzzy",
}


@dataclass(frozen=True)
class SubScore:
    name: str
    value: float
    maximum: float
    measured: bool
    evidence: str


@dataclass(frozen=True)
class Cap:
    condition: str
    ceiling: int
    reason: str


@dataclass(frozen=True)
class Pillar:
    name: str
    score: int
    confidence: float
    subscores: tuple[SubScore, ...]


@dataclass(frozen=True)
class KnobScore:
    name: str
    kind: str
    distinct_values: int
    effective_values: int
    span: float
    resolution: float
    coverage: float
    quality: float
    span_ratio: float | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReadinessScore:
    schema_version: int
    overall: int
    weighted_average: int
    band: str
    status: str
    confidence: float
    band_limited_by_confidence: bool
    weights: dict[str, float]
    pillars: tuple[Pillar, ...]
    caps: tuple[Cap, ...]
    knobs: tuple[KnobScore, ...]
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class DatasetFacts:
    exists: bool = False
    rows: int | None = None
    labelled_rows: int | None = None
    tuning_rows: int | None = None
    holdout_rows: int | None = None
    difficulty_bands: tuple[str, ...] = ()
    difficulty_tagged_rows: int | None = None
    duplicate_status: str | None = None
    near_duplicate_status: str | None = None
    ceiling_risk: bool = False
    split_overlap: bool = False
    integrity_failed: bool = False
    synthetic: bool = False
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationFacts:
    present: bool = False
    method: str | None = None
    task_kind: str | None = None
    calibration_present: bool = False
    checks: tuple[dict[str, bool], ...] = ()
    probe_scores: tuple[tuple[float, ...], ...] = ()
    timed_out: bool = False


@dataclass(frozen=True)
class AgentFacts:
    agent_type: str | None = None
    max_trials: int | None = None
    knobs: dict[str, list[Any]] = field(default_factory=dict)
    # None means the document never named the knobs the agent consumes, so
    # nothing is attested as wired and the pillar fails closed. An empty tuple
    # is the different, explicit statement "nothing is wired". Declaring a knob
    # is not a statement that the agent consumes it - and neither state is
    # verified here, only read.
    wired: tuple[str, ...] | None = None
    bounds: dict[str, dict[str, float]] = field(default_factory=dict)


def round_half_up(value: float) -> int:
    """Round .5 away from zero.

    `round()` uses banker's rounding, which surprises a reader at a band
    boundary: round(74.5) is 74, not 75.
    """
    return int(math.floor(value + 0.5))


def band_for(score: int, confidence: float) -> tuple[str, bool]:
    """Return the band, demoted when too little of the score was measured.

    Renormalizing unmeasured sub-scores can *raise* a score when less is known,
    so a thin-evidence run is not allowed to present as STRONG or EXCELLENT.
    """
    band = BAND_ORDER[-1]
    for threshold, name in BAND_THRESHOLDS:
        if score < threshold:
            band = name
            break
    if confidence >= MIN_CONFIDENCE_FOR_TOP_BANDS:
        return band, False
    ceiling_index = BAND_ORDER.index(CONFIDENCE_BAND_CEILING)
    if BAND_ORDER.index(band) <= ceiling_index:
        return band, False
    return CONFIDENCE_BAND_CEILING, True


def combine(name: str, subscores: Sequence[SubScore]) -> Pillar:
    """Renormalize over measured sub-scores and report the observed fraction."""
    measured = [item for item in subscores if item.measured]
    total_weight = sum(item.maximum for item in subscores)
    measured_weight = sum(item.maximum for item in measured)
    if not measured or measured_weight <= 0:
        return Pillar(
            name=name,
            score=0,
            confidence=0.0,
            subscores=tuple(sorted(subscores, key=lambda item: item.name)),
        )
    earned = sum(item.value for item in measured)
    score = round_half_up(100.0 * earned / measured_weight)
    confidence = measured_weight / total_weight if total_weight else 0.0
    return Pillar(
        name=name,
        score=max(0, min(100, score)),
        confidence=round(confidence, 2),
        subscores=tuple(sorted(subscores, key=lambda item: item.name)),
    )


def noise_floor(name: str, low: float, high: float) -> float:
    if name in NOISE_FLOORS:
        return NOISE_FLOORS[name]
    return abs(high - low) * DEFAULT_NOISE_FRACTION


def effective_numeric_values(values: Sequence[float], floor: float) -> list[float]:
    """Collapse neighbours closer together than the system can distinguish."""
    kept: list[float] = []
    for value in sorted(values):
        if not kept or abs(value - kept[-1]) > floor:
            kept.append(value)
    return kept


def knob_variation(
    name: str,
    values: Sequence[Any],
    bounds: dict[str, float] | None = None,
) -> KnobScore:
    """Score one knob's variation as span, resolution, and coverage.

    They are reported separately rather than only as a blend, because the blend
    alone hides the diagnosis: a two-point sweep over a tenth of the useful
    range is a real sweep with a narrow span, and saying "span 17%" is more
    actionable than a single low number.
    """
    unique = list(dict.fromkeys(values))
    distinct = len(unique)
    notes: list[str] = []

    if name in EXCLUDED_KNOBS:
        return KnobScore(
            name=name,
            kind="excluded",
            distinct_values=distinct,
            effective_values=distinct,
            span=0.0,
            resolution=0.0,
            coverage=0.0,
            quality=0.0,
            span_ratio=None,
            notes=("sweeping this measures run-to-run variance, not quality",),
        )

    numeric = all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in unique
    )
    spec = bounds or CANONICAL_RANGES.get(name)

    if numeric and spec:
        low = float(spec["low"])
        high = float(spec["high"])
        floor = noise_floor(name, low, high)
        numbers = [float(value) for value in unique]
        effective = effective_numeric_values(numbers, floor)
        if len(effective) < 2:
            notes.append(
                "only one value - nothing to search"
                if distinct < 2
                else (
                    f"all {distinct} values fall within {floor:g} of each other - "
                    "the same configuration in practice"
                )
            )
            return KnobScore(
                name=name,
                kind="numeric",
                distinct_values=distinct,
                effective_values=len(effective),
                span=0.0,
                resolution=0.0,
                coverage=0.0,
                quality=0.0,
                span_ratio=(
                    (max(numbers) - min(numbers)) / (high - low) if high > low else 0.0
                ),
                notes=tuple(notes),
            )
        width = high - low
        span_ratio = (max(numbers) - min(numbers)) / width if width > 0 else 0.0
        span = min(1.0, span_ratio / FULL_SPAN_FRACTION) if width > 0 else 0.0
        resolution = len(effective) / distinct if distinct else 0.0
        tolerance = width * ENDPOINT_TOLERANCE_FRACTION
        touches_low = min(numbers) <= low + tolerance
        touches_high = max(numbers) >= high - tolerance
        interior = any(low + tolerance < value < high - tolerance for value in numbers)
        coverage = 0.4 * touches_low + 0.4 * touches_high + 0.2 * interior
        quality = 0.60 * span + 0.25 * resolution + 0.15 * coverage
        if span_ratio < 0.25:
            notes.append(f"spans {span_ratio:.0%} of the useful {low:g}-{high:g} range")
        if not touches_low and not touches_high:
            notes.append("never reaches either end of the useful range")
        return KnobScore(
            name=name,
            kind="numeric",
            distinct_values=distinct,
            effective_values=len(effective),
            span=round(span, 3),
            resolution=round(resolution, 3),
            coverage=round(coverage, 3),
            quality=round(quality, 3),
            span_ratio=round(span_ratio, 4),
            notes=tuple(notes),
        )

    if distinct < 2:
        notes.append("only one value - nothing to search")
        return KnobScore(
            name=name,
            kind="categorical" if not numeric else "numeric",
            distinct_values=distinct,
            effective_values=distinct,
            span=0.0,
            resolution=0.0,
            coverage=0.0,
            quality=0.0,
            span_ratio=None,
            notes=tuple(notes),
        )

    # Categorical, boolean, or numeric without a canonical range: breadth is the
    # only honest signal. Two distinct values is a real comparison; more is
    # better up to a small plateau.
    quality = min(1.0, (distinct - 1) / 2.0)
    if name in OPEN_CATEGORICAL_KNOBS:
        notes.append("scored on breadth; canonical value list is provider-specific")
    elif numeric:
        notes.append("no canonical range for this knob; scored on breadth only")
    return KnobScore(
        name=name,
        kind="categorical",
        distinct_values=distinct,
        effective_values=distinct,
        span=0.0,
        resolution=1.0,
        coverage=round(quality, 3),
        quality=round(quality, 3),
        span_ratio=None,
        notes=tuple(notes),
    )


def size_points(effective_n: int | None) -> tuple[float, str]:
    """Band statistical power on the smaller split, not the row count.

    The question a first run answers is "can this separate config A from B",
    whose resolution comes from the smaller split. The standard error of a
    proportion is at most 0.5/sqrt(n): n=30 gives about +/-9pp, n=100 about
    +/-5pp, n=384 about +/-2.5pp - so a large set never claims more precision
    than it has.
    """
    if effective_n is None:
        return 0.0, "no usable split size"
    if effective_n < 10:
        return 5.0, f"{effective_n} comparable examples - a wiring check, not a score"
    if effective_n < 30:
        return 12.0, f"{effective_n} examples - roughly +/-16pp of noise per result"
    if effective_n < 50:
        return 18.0, f"{effective_n} examples - roughly +/-9pp of noise per result"
    if effective_n < 100:
        return 22.0, f"{effective_n} examples - roughly +/-7pp of noise per result"
    if effective_n < 300:
        return 23.0, f"{effective_n} examples - roughly +/-5pp of noise per result"
    return 25.0, f"{effective_n} examples - roughly +/-2.5pp of noise per result"


def score_dataset(facts: DatasetFacts) -> tuple[Pillar, list[Cap]]:
    caps: list[Cap] = []
    subs: list[SubScore] = []

    if not facts.exists or not facts.rows:
        caps.append(
            Cap(
                "dataset-absent",
                20,
                "No dataset is connected, so nothing can be measured.",
            )
        )
        subs.append(SubScore("labels", 0.0, 30.0, True, "no dataset"))
        subs.append(SubScore("power", 0.0, 25.0, True, "no dataset"))
        subs.append(SubScore("difficulty", 0.0, 15.0, False, "no dataset"))
        subs.append(SubScore("diversity", 0.0, 20.0, False, "no dataset"))
        subs.append(SubScore("provenance", 0.0, 10.0, True, "no dataset"))
        return combine("dataset", subs), caps

    rows = facts.rows
    labelled = facts.labelled_rows if facts.labelled_rows is not None else 0
    if labelled == 0:
        caps.append(
            Cap(
                "dataset-no-expected-outputs",
                30,
                "Rows have inputs but no expected outputs, so there is nothing to "
                "score a configuration against.",
            )
        )
        subs.append(
            SubScore(
                "labels", 0.0, 30.0, True, f"{rows} rows, none with an expectation"
            )
        )
    else:
        ratio = labelled / rows
        subs.append(
            SubScore(
                "labels",
                round(30.0 * ratio, 2),
                30.0,
                True,
                f"{labelled}/{rows} rows carry an expected output",
            )
        )

    if facts.tuning_rows is not None and facts.holdout_rows is not None:
        effective = min(facts.tuning_rows, facts.holdout_rows)
        points, evidence = size_points(effective)
        evidence = (
            f"{facts.tuning_rows} tuning / {facts.holdout_rows} holdout; {evidence}"
        )
    else:
        effective = rows
        points, evidence = size_points(effective)
        points *= 0.8
        evidence = f"no declared tuning/holdout split; {evidence}"
    subs.append(SubScore("power", round(points, 2), 25.0, True, evidence))

    if facts.difficulty_tagged_rows:
        bands = set(facts.difficulty_bands)
        fraction = len(bands & {"easy", "medium", "hard", "very-hard"}) / 4.0
        subs.append(
            SubScore(
                "difficulty",
                round(15.0 * fraction, 2),
                15.0,
                True,
                f"bands present: {', '.join(sorted(bands)) or 'none'}",
            )
        )
    else:
        subs.append(
            SubScore(
                "difficulty",
                0.0,
                15.0,
                False,
                "no rows carry a difficulty tag - spread is unverified, not absent",
            )
        )

    diversity_inputs = [facts.duplicate_status, facts.near_duplicate_status]
    if any(status is not None for status in diversity_inputs):
        earned = 20.0
        problems: list[str] = []
        for label, status in (
            ("duplicate inputs", facts.duplicate_status),
            ("near-duplicate inputs", facts.near_duplicate_status),
        ):
            if status in ("FAIL", "WARN"):
                earned -= 7.0
                problems.append(label)
        if facts.ceiling_risk:
            earned -= 6.0
            problems.append("one expected output dominates")
        subs.append(
            SubScore(
                "diversity",
                round(max(0.0, earned), 2),
                20.0,
                True,
                "; ".join(problems) if problems else "no duplicate or dominance signal",
            )
        )
    else:
        subs.append(
            SubScore("diversity", 0.0, 20.0, False, "duplication was not checked")
        )

    if facts.synthetic:
        provenance = 3.0
        evidence = "fully generated - cannot represent production traffic"
        caps.append(
            Cap(
                "dataset-fully-synthetic",
                65,
                "The dataset is generated, so a high score here measures the "
                "walkthrough, not real-world readiness.",
            )
        )
    elif "unknown" in facts.sources or not facts.sources:
        provenance = 6.0
        evidence = "provenance undeclared - not credited as production data"
    else:
        provenance = 10.0
        evidence = f"declared sources: {', '.join(facts.sources)}"
    subs.append(SubScore("provenance", provenance, 10.0, True, evidence))

    if facts.split_overlap:
        caps.append(
            Cap(
                "dataset-tune-holdout-overlap",
                50,
                "Tuning and holdout share examples, so the holdout score is "
                "inflated - a believable wrong number.",
            )
        )
    if facts.integrity_failed:
        caps.append(
            Cap(
                "dataset-integrity-fail",
                35,
                "The dataset failed a structural check.",
            )
        )
    return combine("dataset", subs), caps


def score_evaluation(facts: EvaluationFacts) -> tuple[Pillar, list[Cap]]:
    caps: list[Cap] = []
    subs: list[SubScore] = []

    if not facts.present:
        caps.append(
            Cap(
                "evaluator-absent",
                40,
                "No evaluation method is connected, so no result can be trusted.",
            )
        )
        subs.append(SubScore("calibration", 0.0, 40.0, True, "no evaluator"))
        subs.append(SubScore("task-fit", 0.0, 25.0, False, "no evaluator"))
        subs.append(SubScore("reproducibility", 0.0, 20.0, False, "no evaluator"))
        subs.append(SubScore("probe-spread", 0.0, 15.0, False, "no evaluator"))
        return combine("evaluation", subs), caps

    if facts.calibration_present and facts.checks:
        gating_failed = [
            index
            for index, checks in enumerate(facts.checks)
            if not checks.get("non_constant", True) or not checks.get("bad_fails", True)
        ]
        per_case: list[float] = []
        for checks in facts.checks:
            values = [bool(value) for value in checks.values()]
            per_case.append(sum(values) / len(values) if values else 0.0)
        blended = 0.5 * (sum(per_case) / len(per_case)) + 0.5 * min(per_case)
        subs.append(
            SubScore(
                "calibration",
                round(40.0 * blended, 2),
                40.0,
                True,
                f"{len(facts.checks)} calibration case(s); weakest case "
                f"{min(per_case):.0%} of checks passed",
            )
        )
        if gating_failed:
            caps.append(
                Cap(
                    "evaluator-invalid",
                    25,
                    "The evaluator scores a wrong answer as well as a right one, "
                    "or returns a constant. Every number below it is unreliable.",
                )
            )
    else:
        subs.append(
            SubScore(
                "calibration", 0.0, 40.0, False, "the evaluator was not calibrated"
            )
        )

    profile = METHOD_PROFILES.get(facts.method or "")
    if profile and facts.task_kind:
        fits = facts.task_kind in profile["fits"]
        subs.append(
            SubScore(
                "task-fit",
                25.0 if fits else 8.0,
                25.0,
                True,
                (
                    f"{facts.method} suits {facts.task_kind} output"
                    if fits
                    else f"{facts.method} is a poor ruler for {facts.task_kind} output"
                ),
            )
        )
    else:
        subs.append(
            SubScore(
                "task-fit",
                0.0,
                25.0,
                False,
                "task kind not declared - fit is unverified",
            )
        )

    if profile:
        reproducibility = profile["reproducibility"]
        cost = profile["cost"]
        blended = 0.7 * reproducibility + 0.3 * cost
        deterministic = facts.method in DETERMINISTIC_METHODS
        subs.append(
            SubScore(
                "reproducibility",
                round(20.0 * blended, 2),
                20.0,
                True,
                (
                    "deterministic and free to run"
                    if deterministic
                    else f"{facts.method} varies between runs and costs money"
                ),
            )
        )
    else:
        subs.append(
            SubScore(
                "reproducibility", 0.0, 20.0, False, "evaluation method not declared"
            )
        )

    if facts.probe_scores:
        spreads = [max(case) - min(case) for case in facts.probe_scores if case]
        widest = max(spreads) if spreads else 0.0
        subs.append(
            SubScore(
                "probe-spread",
                round(15.0 * min(1.0, widest), 2),
                15.0,
                True,
                f"widest good-to-bad separation across probes: {widest:.2f}",
            )
        )
    else:
        subs.append(
            SubScore("probe-spread", 0.0, 15.0, False, "no probe scores available")
        )

    if facts.timed_out:
        caps.append(
            Cap(
                "evaluator-timeout",
                45,
                "The evaluator did not finish within its timeout.",
            )
        )
    return combine("evaluation", subs), caps


def knob_count_points(varying: int, space_size: int, max_trials: int | None) -> float:
    """Plateau, not a ramp.

    More knobs is not monotonically better: a space far larger than the trial
    budget cannot be explored, so a twelve-knob space against a twelve-trial cap
    is worse than four. A ramp would tell users to keep adding knobs forever.
    """
    if varying == 0:
        return 0.0
    if varying == 1:
        base = 12.0
    elif varying <= 3:
        base = 26.0
    elif varying <= 6:
        base = 35.0
    else:
        base = max(24.0, 35.0 - 2.0 * (varying - 6))
    if max_trials and space_size and space_size / max_trials > 20:
        base = min(base, 24.0)
    return base


NOTHING_WIRED_CAP = Cap(
    "agent-no-varying-knobs",
    45,
    "No tunable knob is attested as wired, so there is nothing to search.",
)

UNATTESTED_WIRING_CAP = Cap(
    "agent-no-varying-knobs",
    45,
    "Search controls are declared, but the document does not state which of "
    "them the agent consumes, so nothing is attested as wired to search.",
)


def nothing_to_search_pillar(evidence: str) -> Pillar:
    """The agent pillar every "no knob is attested as wired" state reports.

    Three inputs land here: no knobs declared at all, knobs declared with no
    `wired` list, and knobs declared with an explicit empty one. The rule is
    that all three report the same shape - score 0, `knob-count` measured at
    zero, the two behavior-dependent sub-scores unmeasured - because how many
    knobs the document attests as wired is readable off the document in every
    one of them (it is zero), while how those absent knobs vary and what they
    cover is not readable from anything.

    Holding them equal is what keeps confidence monotonic: handing the scorer a
    config space can never *lower* the agent pillar's confidence below what the
    same run reports with no document at all. An earlier draft marked all three
    sub-scores unmeasured for the missing-`wired` case alone, which dropped that
    pillar to confidence 0.00 while a run with no document kept 0.35 - so
    supplying more input reported knowing less.
    """
    return combine(
        "agent",
        [
            SubScore("knob-count", 0.0, 35.0, True, evidence),
            SubScore("variation", 0.0, 40.0, False, evidence),
            SubScore("coverage", 0.0, 25.0, False, evidence),
        ],
    )


def score_agent(facts: AgentFacts) -> tuple[Pillar, list[Cap], list[KnobScore]]:
    caps: list[Cap] = []
    subs: list[SubScore] = []

    # Order is deliberate: an empty `knobs` map is answered here, ahead of the
    # `wired` branch, so `{"knobs": {}}` keeps saying "no knobs declared"
    # whether or not it carries a `wired` key. Swapping the two branches would
    # silently reword the emptiest document in the file.
    if not facts.knobs:
        return nothing_to_search_pillar("no knobs declared"), [NOTHING_WIRED_CAP], []

    if facts.wired is None:
        # Declared knobs, unattested wiring. The document lists controls but
        # never states which of them the agent consumes, and this script cannot
        # tell: it reads JSON, not the agent's call path. So the knobs it can
        # credit are the ones attested as wired - here, none - and the cap
        # stays binding until the document names them. What this contract buys
        # is "explicitly attested", not "measured": actually proving that a
        # knob reaches a provider call is the job of issue #59's
        # `demonstrably_wired()` probe, and until that lands the `wired` list
        # is an unenforced claim.
        return (
            nothing_to_search_pillar(
                f"{len(facts.knobs)} declared knob(s), none attested as wired - "
                "name the knobs the agent consumes in the document's 'wired' list"
            ),
            [UNATTESTED_WIRING_CAP],
            [],
        )

    wired = set(facts.wired)
    considered = {name: values for name, values in facts.knobs.items() if name in wired}
    knobs = [
        knob_variation(name, values, facts.bounds.get(name))
        for name, values in sorted(considered.items())
    ]
    scoreable = [knob for knob in knobs if knob.kind != "excluded"]
    varying = [knob for knob in scoreable if knob.effective_values >= 2]

    space_size = 1
    for name, values in considered.items():
        space_size *= max(1, len(set(map(repr, values))))

    if not knobs:
        # Reachable now only for an explicit "wired": [] (or wired names
        # matching no declared knob). "no knobs declared" was false here:
        # knobs ARE declared, zero of them are attested as wired.
        return (
            nothing_to_search_pillar(
                f"0 of {len(facts.knobs)} declared knobs are attested as wired"
            ),
            [NOTHING_WIRED_CAP],
            knobs,
        )

    if not varying:
        caps.append(
            Cap(
                "agent-no-varying-knobs",
                45,
                "Every declared knob has a single effective value, so no "
                "configuration differs from any other.",
            )
        )

    subs.append(
        SubScore(
            "knob-count",
            knob_count_points(len(varying), space_size, facts.max_trials),
            35.0,
            True,
            f"{len(varying)} of {len(scoreable)} wired knobs actually vary; "
            f"{space_size} combinations",
        )
    )

    if scoreable:
        mean_quality = sum(knob.quality for knob in scoreable) / len(scoreable)
        weakest = min(scoreable, key=lambda knob: knob.quality)
        subs.append(
            SubScore(
                "variation",
                round(40.0 * mean_quality, 2),
                40.0,
                True,
                f"weakest knob '{weakest.name}' at {weakest.quality:.0%}",
            )
        )
    else:
        subs.append(SubScore("variation", 0.0, 40.0, False, "no scoreable knobs"))

    catalog = HIGH_IMPACT_KNOBS.get(facts.agent_type or "general")
    if catalog:
        present = {knob.name for knob in scoreable}
        missing = [name for name in catalog if name not in present]
        fraction = 1.0 - (len(missing) / len(catalog))
        subs.append(
            SubScore(
                "coverage",
                round(25.0 * fraction, 2),
                25.0,
                True,
                (
                    f"not tuning: {', '.join(missing)}"
                    if missing
                    else "every high-impact knob for this agent type is tuned"
                ),
            )
        )
    else:
        subs.append(SubScore("coverage", 0.0, 25.0, False, "agent type not recognized"))
    return combine("agent", subs), caps, knobs


def collect_gaps(
    pillars: Sequence[Pillar], knobs: Sequence[KnobScore], caps: Sequence[Cap]
) -> tuple[str, ...]:
    """Order remediation by how many points it is actually costing."""
    gaps: list[tuple[float, str]] = []
    for cap in caps:
        gaps.append((1000.0, f"{cap.condition}: {cap.reason}"))
    for pillar in pillars:
        for sub in pillar.subscores:
            if not sub.measured:
                gaps.append(
                    (
                        sub.maximum * 0.5,
                        f"{pillar.name}/{sub.name} could not be measured - "
                        f"{sub.evidence}",
                    )
                )
            elif sub.value < sub.maximum:
                gaps.append(
                    (
                        sub.maximum - sub.value,
                        f"{pillar.name}/{sub.name}: {sub.evidence}",
                    )
                )
    for knob in knobs:
        for note in knob.notes:
            gaps.append((5.0, f"knob '{knob.name}': {note}"))
    gaps.sort(key=lambda item: (-item[0], item[1]))
    return tuple(text for _, text in gaps)


def aggregate(
    pillars: Sequence[Pillar],
    caps: Sequence[Cap],
    knobs: Sequence[KnobScore],
    weights: dict[str, float],
) -> ReadinessScore:
    total_weight = sum(weights.values())
    weighted = sum(
        weights.get(pillar.name, 0.0) * pillar.score for pillar in pillars
    ) / (total_weight or 1.0)
    weighted_average = round_half_up(weighted)

    ordered_caps = tuple(sorted(caps, key=lambda cap: (cap.ceiling, cap.condition)))
    ceiling = min((cap.ceiling for cap in ordered_caps), default=100)
    overall = min(weighted_average, ceiling)

    confidence_total = sum(weights.get(p.name, 0.0) for p in pillars) or 1.0
    confidence = (
        sum(weights.get(p.name, 0.0) * p.confidence for p in pillars) / confidence_total
    )
    band, limited = band_for(overall, confidence)
    return ReadinessScore(
        schema_version=SCHEMA_VERSION,
        overall=overall,
        weighted_average=weighted_average,
        band=band,
        status="BLOCKED" if ordered_caps else "OK",
        confidence=round(confidence, 2),
        band_limited_by_confidence=limited,
        weights=dict(sorted(weights.items())),
        pillars=tuple(sorted(pillars, key=lambda pillar: pillar.name)),
        caps=ordered_caps,
        knobs=tuple(sorted(knobs, key=lambda knob: knob.name)),
        gaps=collect_gaps(pillars, knobs, ordered_caps),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

IDE_COLOR_MARKERS = ("PYCHARM_HOSTED", "JPY_PARENT_PID", "SPY_INTERACTIVE")
WINDOWS_VT_MARKERS = ("WT_SESSION", "ANSICON", "ConEmuANSI", "TERM")


def resolve_color(
    stream: Any, override: str = "auto", environ: dict[str, str] | None = None
) -> bool:
    """Decide whether ANSI is safe for this host.

    A bare isatty() check is wrong in both directions: PyCharm, VS Code, Spyder
    and Jupyter render ANSI while reporting isatty() False, and a legacy Windows
    console is a tty that mangles escapes without virtual-terminal processing.

    The order matters for CI. The offline harness runs these scripts with a
    fixed eleven-key environment that contains none of the markers below, and
    pipes stdout - so every branch falls through to False and no escape byte can
    reach `clean_capture`, which rejects them.
    """
    env = os.environ if environ is None else environ
    if override == "always":
        return True
    if override == "never":
        return False
    if env.get("NO_COLOR"):
        return False
    if env.get("FORCE_COLOR"):
        return True
    if env.get("TERM") == "dumb":
        return False
    is_tty = bool(getattr(stream, "isatty", lambda: False)())
    if is_tty:
        if sys.platform.startswith("win"):
            return any(env.get(marker) for marker in WINDOWS_VT_MARKERS)
        return True
    if env.get("TERM_PROGRAM") == "vscode":
        return True
    return any(env.get(marker) for marker in IDE_COLOR_MARKERS)


def supports_unicode(stream: Any) -> bool:
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        "█".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


@dataclass(frozen=True)
class Palette:
    reset: str = ""
    strong: str = ""
    warn: str = ""
    bad: str = ""
    dim: str = ""


PLAIN = Palette()
ANSI = Palette(
    reset="\x1b[0m",
    strong="\x1b[32m",
    warn="\x1b[33m",
    bad="\x1b[31m",
    dim="\x1b[2m",
)


def band_color(palette: Palette, score: int) -> str:
    if score >= 75:
        return palette.strong
    if score >= 55:
        return palette.warn
    return palette.bad


def bar(score: int, *, width: int = 20, unicode_ok: bool = True) -> str:
    filled = round_half_up(score / 100 * width)
    full, empty = ("█", "░") if unicode_ok else ("#", "-")
    return full * filled + empty * (width - filled)


def marker_unmeasured(unicode_ok: bool) -> str:
    """The glyph for a check that did not run.

    Defined once because the card's summary line points the reader back at these
    rows by name; a second literal would drift the two apart on an ASCII
    terminal, where the summary would cite a glyph the rows never printed.
    """
    return "•" if unicode_ok else "?"


def marker(sub: SubScore, unicode_ok: bool) -> str:
    if not sub.measured:
        return marker_unmeasured(unicode_ok)
    if sub.value >= sub.maximum * 0.8:
        return "OK" if not unicode_ok else "✅"
    return "!!" if not unicode_ok else "❗"


def render_card(
    score: ReadinessScore, *, palette: Palette = PLAIN, unicode_ok: bool = True
) -> str:
    """Render the terminal card.

    Meaning never depends on colour: the markers and the numbers carry it, so a
    monochrome terminal loses nothing. Deliberately contains no timestamp - the
    offline harness runs every scenario twice and compares the evidence.
    """
    lines: list[str] = []
    headline = f"{score.overall}/100  {score.band}"
    if score.status == "BLOCKED":
        headline += "  (BLOCKED)"
    lines.append(f"TRAIGENT OPTIMIZATION READINESS{' ' * 8}{headline}")
    lines.append("")
    for pillar in score.pillars:
        colour = band_color(palette, pillar.score)
        headline_suffix = f"  {pillar.score}/100"
        if pillar.confidence < MIN_CONFIDENCE_FOR_TOP_BANDS:
            # A renormalized score over half the checks is not the same claim as
            # a full one. Saying so on the same line stops "100/100" from reading
            # as "verified perfect" when most of it was never observed. The share
            # itself is an internal weight ratio and means nothing to the reader,
            # so the plain fact is shown here and the marked rows below say which.
            headline_suffix += f"  {palette.dim}(partly checked){palette.reset}"
        lines.append(
            f"  {pillar.name.upper():<11} {colour}{bar(pillar.score, unicode_ok=unicode_ok)}"
            f"{palette.reset}{headline_suffix}"
        )
        for sub in pillar.subscores:
            lines.append(f"    {marker(sub, unicode_ok)} {sub.name:<16} {sub.evidence}")
        lines.append("")
    if score.caps:
        for cap in score.caps:
            lines.append(f"  {palette.bad}BLOCKED{palette.reset} {cap.reason}")
        lines.append("")
    if score.band_limited_by_confidence:
        # Grounded in the rows above rather than in a percentage: the reader can
        # see which checks did not run and why. Direction matters - skipping a
        # check *raises* the renormalized score, so the honest plain sentence is
        # "a partial check can read better", never "your real score is higher".
        unchecked = marker_unmeasured(unicode_ok)
        lines.append(
            f"  {palette.dim}Some checks could not run (marked {unchecked} above). "
            f"A partial check can read better than a full one, so this stays "
            f"at {score.band}.{palette.reset}"
        )
    lines.append(
        f"  {palette.dim}Approximate, from what runs on this machine. Traigent "
        f"measures this properly after a real run.{palette.reset}"
    )
    return "\n".join(lines)


def render_markdown(score: ReadinessScore, timestamp: str | None = None) -> str:
    """Render the durable report.

    The timestamp is caller-supplied and never read from the clock, so this
    module stays reproducible across the harness's two passes.
    """
    lines = ["# Traigent optimization readiness", ""]
    if timestamp:
        lines.extend([f"Generated: {timestamp}", ""])
    lines.extend(
        [
            f"**{score.overall}/100 - {score.band}**"
            + ("  ·  status: BLOCKED" if score.status == "BLOCKED" else ""),
            "",
            f"Weighted average before caps: {score.weighted_average}/100. "
            f"Measured confidence: {score.confidence:.0%}.",
            "",
            "This is a first-pass estimate computed from local evidence only, "
            "before any optimization has run. It is an ordinal planning aid, not "
            "a calibrated probability. Weights are a judgment call and are listed "
            "below so the number stays auditable.",
            "",
            "| Pillar | Score | Weight | Confidence |",
            "| --- | --- | --- | --- |",
        ]
    )
    for pillar in score.pillars:
        lines.append(
            f"| {pillar.name} | {pillar.score}/100 | "
            f"{score.weights.get(pillar.name, 0):.0f}% | {pillar.confidence:.0%} |"
        )
    lines.append("")
    for pillar in score.pillars:
        lines.extend(
            [
                f"## {pillar.name.title()}",
                "",
                "| Check | Points | Evidence |",
                "| --- | --- | --- |",
            ]
        )
        for sub in pillar.subscores:
            points = (
                "unmeasured" if not sub.measured else f"{sub.value:g} / {sub.maximum:g}"
            )
            lines.append(f"| {sub.name} | {points} | {sub.evidence} |")
        lines.append("")
    if score.knobs:
        lines.extend(
            [
                "## Knobs",
                "",
                "| Knob | Values | Span | Resolution | Coverage | Quality |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for knob in score.knobs:
            span = "n/a" if knob.span_ratio is None else f"{knob.span_ratio:.0%}"
            lines.append(
                f"| {knob.name} | {knob.distinct_values} | {span} | "
                f"{knob.resolution:.0%} | {knob.coverage:.0%} | {knob.quality:.0%} |"
            )
        lines.append("")
    if score.caps:
        lines.extend(["## What is blocking a trustworthy result", ""])
        for cap in score.caps:
            lines.append(
                f"- **{cap.condition}** (caps the score at {cap.ceiling}): {cap.reason}"
            )
        lines.append("")
    if score.gaps:
        lines.extend(["## Ranked gaps", ""])
        for gap in score.gaps:
            lines.append(f"- {gap}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Adapters - the only code that knows another script's JSON shape
# ---------------------------------------------------------------------------


def _metrics_by_check(records: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        record["check"]: record.get("metrics") or {}
        for record in records
        if isinstance(record, dict) and "check" in record
    }


def _status_by_check(records: Sequence[dict[str, Any]]) -> dict[str, str]:
    return {
        record["check"]: record.get("status", "")
        for record in records
        if isinstance(record, dict) and "check" in record
    }


class PreflightInputError(ValueError):
    """Supplied preflight JSON cannot be scored honestly.

    A distinct type so the CLI can refuse bad scoring input (exit 2 with the
    message) while a genuine bug inside the fact adapters still surfaces as a
    traceback instead of being misreported as unreadable input.
    """


def dataset_facts_from_preflight(records: Sequence[dict[str, Any]]) -> DatasetFacts:
    metrics = _metrics_by_check(records)
    statuses = _status_by_check(records)
    provenance = metrics.get("dataset-provenance", {})
    difficulty = metrics.get("dataset-difficulty-coverage", {})
    integrity = metrics.get("dataset-integrity", {})
    # No provenance metric at all means preflight found no rows to describe - a
    # genuinely absent or empty dataset. An unlabelled-but-present dataset now
    # carries provenance (rows > 0, labelled_rows == 0), so it lands below in the
    # exists=True branch and reaches the cap-30 "no expected outputs" case.
    if not provenance:
        return DatasetFacts(exists=False)
    # Structural integrity is about malformed rows (bad JSON, non-objects,
    # missing inputs). Rows that merely lack an expected output are unlabelled,
    # not malformed, so they must not trip the integrity cap - they are scored
    # through the "no expected outputs" branch instead. Read dataset-integrity
    # directly (dataset-shape now also fails for a merely-unlabelled dataset).
    integrity_status = statuses.get("dataset-integrity")
    if integrity_status == "FAIL" and "malformed_rows" not in integrity:
        raise PreflightInputError(
            "dataset-integrity FAILed but carries no malformed_rows count - "
            "this preflight JSON predates the current preflight.py; re-run "
            "preflight.py --json from the same version as this script"
        )
    structurally_failed = integrity_status == "FAIL" and integrity["malformed_rows"] > 0
    return DatasetFacts(
        exists=True,
        rows=provenance.get("rows"),
        labelled_rows=provenance.get("labelled_rows"),
        tuning_rows=metrics.get("dataset-tuning-size", {}).get("tuning_rows"),
        holdout_rows=metrics.get("dataset-holdout-resolution", {}).get("holdout_rows"),
        difficulty_bands=tuple(difficulty.get("bands", ())),
        difficulty_tagged_rows=difficulty.get("tagged_rows"),
        duplicate_status=statuses.get("dataset-duplicates"),
        near_duplicate_status=statuses.get("dataset-near-duplicates"),
        ceiling_risk="dataset-ceiling-risk" in statuses,
        split_overlap=statuses.get("dataset-split") == "FAIL",
        integrity_failed=structurally_failed or statuses.get("dataset-ids") == "FAIL",
        synthetic=bool(provenance.get("synthetic")),
        sources=tuple(provenance.get("sources", ())),
    )


def evaluation_facts_from_calibration(
    payload: dict[str, Any] | None,
    *,
    method: str | None = None,
    task_kind: str | None = None,
) -> EvaluationFacts:
    """Normalize both shapes `calibrate_evaluator` emits into one fact set."""
    if payload is None:
        return EvaluationFacts(
            present=method is not None, method=method, task_kind=task_kind
        )
    cases = payload.get("cases")
    if not isinstance(cases, list):
        cases = [payload]
    checks: list[dict[str, bool]] = []
    probes: list[tuple[float, ...]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_checks = case.get("checks")
        if isinstance(case_checks, dict):
            checks.append({key: bool(value) for key, value in case_checks.items()})
        scores = case.get("scores")
        if isinstance(scores, dict):
            numeric = [
                float(value)
                for value in scores.values()
                if isinstance(value, (int, float))
            ]
            if numeric:
                probes.append(tuple(numeric))
    return EvaluationFacts(
        present=True,
        method=method,
        task_kind=task_kind,
        calibration_present=bool(checks),
        checks=tuple(checks),
        probe_scores=tuple(probes),
        timed_out=bool(payload.get("timed_out")),
    )


def agent_facts_from_config_space(document: dict[str, Any]) -> AgentFacts:
    knobs = document.get("knobs") or document.get("configuration_space") or {}
    return AgentFacts(
        agent_type=document.get("agent_type"),
        max_trials=document.get("max_trials"),
        knobs={
            name: list(values)
            for name, values in knobs.items()
            if isinstance(values, (list, tuple))
        },
        wired=tuple(document["wired"]) if "wired" in document else None,
        bounds={
            name: {"low": float(spec["low"]), "high": float(spec["high"])}
            for name, spec in (document.get("bounds") or {}).items()
            if isinstance(spec, dict) and "low" in spec and "high" in spec
        },
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_json(reference: str) -> Any:
    if reference == "-":
        return json.loads(sys.stdin.read())
    return json.loads(Path(reference).read_text())


def parse_weights(raw: str) -> dict[str, float]:
    parts = [piece.strip() for piece in raw.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("--weights needs three values: D,E,A")
    try:
        values = [float(part) for part in parts]
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"--weights must be numeric: {error}"
        ) from error
    if any(value < 0 for value in values) or sum(values) <= 0:
        raise argparse.ArgumentTypeError("--weights must be non-negative and non-zero")
    return {"dataset": values[0], "evaluation": values[1], "agent": values[2]}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plan a first run from declared provenance, or score optimization "
            "readiness from measured evidence."
        )
    )
    choices = ("real", "limited", "demo", "missing", "invalid")
    parser.add_argument("--agent", choices=choices)
    parser.add_argument("--dataset", choices=choices)
    parser.add_argument("--evaluation", choices=choices)
    parser.add_argument("--preflight", help="preflight.py --json output (path or -)")
    parser.add_argument(
        "--calibration", help="calibrate_evaluator.py --json output (path or -)"
    )
    parser.add_argument(
        "--config-space",
        help=(
            "agent knob document (path or -); knobs earn credit only when its "
            "'wired' list names them - the list is an unverified attestation, "
            "and an absent one credits nothing"
        ),
    )
    parser.add_argument(
        "--evaluator-method",
        choices=tuple(sorted(METHOD_PROFILES)),
        help="declared evaluation method (recorded as declared, not measured)",
    )
    parser.add_argument(
        "--task-kind",
        help="output kind the agent produces (closed-label, free-text, code-sql, ...)",
    )
    parser.add_argument(
        "--weights",
        type=parse_weights,
        default=dict(DEFAULT_WEIGHTS),
        help="pillar weights as dataset,evaluation,agent (default 40,35,25)",
    )
    parser.add_argument("--report", help="write the markdown report to this path")
    parser.add_argument(
        "--report-timestamp",
        help="timestamp for the report; never read from the clock",
    )
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--ascii", action="store_true", help="force ASCII glyphs")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when the score is BLOCKED (never the default)",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable output"
    )
    return parser.parse_args(argv)


def scoring_requested(args: argparse.Namespace) -> bool:
    return any((args.preflight, args.calibration, args.config_space))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if not scoring_requested(args):
        if not all((args.agent, args.dataset, args.evaluation)):
            print(
                "provide --agent/--dataset/--evaluation to plan, or --preflight/"
                "--calibration/--config-space to score",
                file=sys.stderr,
            )
            return 2
        plan = build_plan(args.agent, args.dataset, args.evaluation)
        if args.json:
            print(json.dumps(asdict(plan), indent=2, sort_keys=True))
            return 0
        print(render_text(plan))
        return 0

    try:
        dataset_facts = (
            dataset_facts_from_preflight(load_json(args.preflight))
            if args.preflight
            else DatasetFacts(exists=False)
        )
        evaluation_facts = evaluation_facts_from_calibration(
            load_json(args.calibration) if args.calibration else None,
            method=args.evaluator_method,
            task_kind=args.task_kind,
        )
        agent_facts = (
            agent_facts_from_config_space(load_json(args.config_space))
            if args.config_space
            else AgentFacts()
        )
    except (OSError, json.JSONDecodeError, PreflightInputError) as error:
        print(f"cannot read scoring input: {error}", file=sys.stderr)
        return 2

    dataset_pillar, dataset_caps = score_dataset(dataset_facts)
    evaluation_pillar, evaluation_caps = score_evaluation(evaluation_facts)
    agent_pillar, agent_caps, knobs = score_agent(agent_facts)
    score = aggregate(
        [dataset_pillar, evaluation_pillar, agent_pillar],
        [*dataset_caps, *evaluation_caps, *agent_caps],
        knobs,
        args.weights,
    )

    if args.report:
        Path(args.report).write_text(render_markdown(score, args.report_timestamp))

    if args.json:
        print(json.dumps(asdict(score), indent=2, sort_keys=True))
    else:
        use_color = resolve_color(sys.stdout, args.color)
        unicode_ok = not args.ascii and supports_unicode(sys.stdout)
        print(
            render_card(
                score,
                palette=ANSI if use_color else PLAIN,
                unicode_ok=unicode_ok,
            )
        )

    if args.strict and score.status == "BLOCKED":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
and the user-facing evidence coverage says how much of the pillar was actually observed.
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
from typing import Any, Iterable, Literal, Sequence

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

# 2: caps carry `action_kind` and the payload carries `recommended_action`.
#
# Additive - nothing was removed or renamed, so a reader of v1 keeps working.
# Bumped anyway, because the version is what lets a consumer tell "this scorer
# does not emit a remedy" from "this run has no remedy to emit", and those need
# different handling: the first is a stale script, the second is a healthy
# project. Left at 1, a consumer seeing no `recommended_action` could not tell
# which it was looking at.
SCHEMA_VERSION = 2
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

# `max_tokens` is deliberately absent from every catalog. It exists so the model
# is not cut off mid-answer: references/run-safety.md requires at least 2048
# (4096 at high reasoning effort) and says not to "sweep low `max_tokens` values
# in any space that contains a reasoning model", because a tight cap truncates
# the answer to `finish_reason == "length"`, scores it 0, and silently crowns a
# weaker model the winner. That makes it a capacity guard, not a quality lever -
# so a space that obeys the safety rule must not be docked for not sweeping it.
HIGH_IMPACT_KNOBS: dict[str, tuple[str, ...]] = {
    "rag": ("model", "retrieval_k", "temperature", "context_format", "prompt_style"),
    "code_gen": ("model", "temperature", "fewshot_k", "schema_context"),
    "general": ("model", "temperature", "prompt_style"),
}

# Accepted alternate spellings of a catalog knob, mapped onto the one canonical
# name the catalog uses. Both spellings name one search dimension, so the rename
# happens once - `canonical_alias_names`, applied to the facts before any
# sub-score reads them - rather than inside whichever sub-score noticed the
# problem. Normalizing only inside coverage let knob-count, variation and the
# combination count treat the two spellings as two independent dimensions.
KNOB_ALIASES: dict[str, str] = {"prompt_policy": "prompt_style"}

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
    # Reference-free: these score a row from the input and a rubric, so a row
    # carrying no expected output is still scoreable by them. Named once here
    # because the dataset pillar has to ask the question and a scattered
    # startswith("llm-judge") test drifts the moment a method is added.
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


# What the user should DO about each cap, as a closed vocabulary.
#
# Closed, because an open string reintroduces the problem one layer down: a
# consumer cannot tell a near-miss ("fix the evaluator") from a real
# disagreement with `repair-evaluator`, so a typo grades as a defect.
#
# Keyed by condition rather than passed at each `Cap(...)`, because the remedy
# is a property OF the condition, and several conditions are raised from more
# than one place - `dataset-fully-synthetic` from two, `agent-no-varying-knobs`
# from three. Sixteen call sites carrying their own copy is sixteen chances for
# two of them to disagree about the same condition, which is the drift this
# field exists to remove rather than relocate.
#
# The spellings are not invented here. A downstream grader already keeps this
# table, because the payload said what was wrong and never what to do - so every
# consumer re-derived the mapping and drifted from it (traigent-first-run#98).
# Emitting it is what makes that copy deletable instead of a second source of
# truth.
PROCEED = "proceed"
ACTION_FOR_CONDITION: dict[str, str] = {
    "dataset-absent": "get-data",
    "dataset-below-measurable-size": "get-data",
    "dataset-coarse-resolution": "get-data",
    "dataset-no-expected-outputs": "label-data",
    "dataset-integrity-fail": "repair-dataset",
    "dataset-tune-holdout-overlap": "resplit-dataset",
    "dataset-fully-synthetic": "connect-real-data",
    "dataset-mostly-synthetic": "connect-real-data",
    "dataset-generated-answer-key": "review-answer-key",
    # Same remedy as the line above, deliberately: both say the answer key
    # cannot be trusted until a person looks at it, and a consumer that already
    # routes `review-answer-key` needs no new slug to route this. A second
    # spelling for one remedy is the drift this table exists to remove.
    "dataset-unsound-expected-outputs": "review-answer-key",
    "evaluator-absent": "connect-evaluator",
    "evaluator-unresolved": "repair-evaluator",
    "evaluator-invalid": "repair-evaluator",
    "evaluator-timeout": "bound-evaluator-cost",
    "agent-no-varying-knobs": "vary-knobs",
}
ACTION_KINDS = frozenset({PROCEED, *ACTION_FOR_CONDITION.values()})


# Every ceiling, in one ordered place, with the basis for each number beside it.
#
# TWO THINGS ARE RECORDED HERE, and they are different claims.
#
# The ORDER is a rule: a worse condition gets a lower ceiling. That was always
# the evident intent and it was nowhere written and nothing checked it, so it
# had already gone wrong once - before #144 two overlapping unreadable-dataset
# conditions were ranked by whichever author wrote each one, with nothing
# comparing them. The order is therefore asserted, in
# `tests/test_readiness_scoring.py`, so a new cap cannot be inserted out of
# sequence and an existing ceiling cannot be moved past its neighbours.
#
# The NUMBERS are not a rule and this comment does not pretend otherwise. Each
# is a position on a 0-100 scale, chosen so that a run carrying the condition
# cannot present as better than it is. Where a number has a derivation it is
# given below; where the honest basis is "it sits between these two neighbours
# on a scale", that is what is written, because inventing a derivation for it
# would be worse than admitting the ranking is a judgment. Changing a value is
# the owner's call; changing the ORDER breaks the test.
#
# The groups are the part that IS derived from something real - what the
# condition destroys - and the ceilings of one group may not reach into
# another's:
#
#   NO RESULT TO BOUND   A component the score is computed FROM is missing, or
#                        is present and actively wrong. There is no number to
#                        put a ceiling on; the ceiling exists to say so.
#   ANSWERS THE WRONG    Every component is present and valid, and the run still
#   QUESTION             does not answer what was asked - every configuration is
#                        identical, the evaluator never finished, or the set held
#                        back to check the winner was already tuned on.
#   BOUNDED CLAIM        Nothing is broken. The run produces a real comparison,
#                        and only what it may CLAIM is limited - by whose data it
#                        ran on, or by how much of it there was.
#
# #149 draws the stop/ceiling line through the same material from the other
# side: a route asking for creation or repair is a stop, a route that only
# scopes the claim is a ceiling. That is the `blocks` flag and it is not
# restated here - one decision, one home. This file owns how far the number may
# rise; #149 owns whether the run may proceed at all.
#
# Note for whoever revisits the values: `ACTION_FOR_CONDITION` does NOT give
# this grouping for free, and it was checked. `get-data` is the remedy for
# `dataset-absent` (20), `dataset-below-measurable-size` (74) and
# `dataset-coarse-resolution` (89), which span the whole range - the remedy
# vocabulary answers "what should the user do", not "how much of the result
# survives", and those are different questions about the same condition.
DATASET_ABSENT_CEILING = 20
# Nothing was measured at all, so this is the floor of the scale: the lowest
# ceiling any condition carries, and NOT READY however good the rest looks.
EVALUATOR_INVALID_CEILING = 25
# Just above an absent dataset and below every other condition. A ruler that
# scores a wrong answer as well as a right one is worse than a missing one,
# because it produces believable numbers; it sits above 20 only because the
# dataset it would measure is still there.
DATASET_NO_EXPECTED_OUTPUTS_CEILING = 30
# The bottom of PARTIAL. Rows exist and are readable - real material, and the
# gap is one addition away - but nothing can be scored until it is made.
DATASET_INTEGRITY_CEILING = 35
# Above 30 because only SOME rows are unusable: what is left is scoreable, and
# the remedy is a repair rather than a collection effort.
EVALUATOR_ABSENT_CEILING = 40
# Above the dataset conditions below it because the dataset - the expensive
# half - is intact; choosing an evaluation method is the cheapest of these gaps
# to close.
EVALUATOR_UNRESOLVED_CEILING = 40
# Deliberately equal to `evaluator-absent`. The user has the same problem
# either way - no evaluation this run can trust - and only the remedy differs
# (inspect and repair the file, rather than select a method). Equal ceilings are
# allowed; the order asserts non-decreasing, not strictly increasing.
EVALUATOR_TIMEOUT_CEILING = 45
# First of the "answers the wrong question" band, so above every ceiling in the
# band below it. Everything is connected and valid; this run simply did not
# finish, and re-running within a bound is all that is asked.
AGENT_NO_VARYING_KNOBS_CEILING = 45
# Equal to the timeout for the same reason: nothing is broken, and the run
# compares nothing. An optimization with one configuration is a single
# measurement wearing a search's clothes.
SPLIT_OVERLAP_CEILING = 50
# Top of that band. Worse than the two above it because the result is not
# merely absent or uninformative - it is flattered, and a believable wrong
# number is the most expensive failure on this list.
FULLY_SYNTHETIC_CEILING = 65
# First of the "bounded claim" band. Nothing here was observed, so the run
# measures the walkthrough; it clears 50 because the comparison it performs is
# a real one, and it stays in WORKABLE because what it compares is invented.
MOSTLY_SYNTHETIC_CEILING = 70
# Above `fully-synthetic` because some of the data IS real - strictly less
# invented, so strictly less capped. This pair is the clearest case of the
# ordering rule: the condition below implies this one, so its ceiling may never
# be the higher of the two.
UNSOUND_ANSWER_CEILING = 70
# Equal to `mostly-synthetic`, and ranked AFTER it - the tie is broken, not
# left to whichever author wrote each line, which is the failure this whole
# block exists to stop.
#
# The number first. It sits below `generated-answer-key` (75) because it is the
# stronger finding about the same thing: that condition says nobody observed
# these answers, this one says somebody read them and they disagree with their
# own questions. It sits above the structural dataset conditions (overlap 50,
# unreadable rows 35) because those are measured and this is an opinion, and an
# opinion may not be the harshest number on the card. What 70 buys is one
# thing: the run cannot present as STRONG while a material share of what it
# grades against is believed wrong.
#
# Now the tie. `mostly-synthetic` is a COUNT - preflight read the provenance
# field on every row and divided. This is the assistant's reading of a
# customer's domain, and on collected data it can simply be wrong. Where two
# conditions bound the claim by the same amount, the measured one is ranked as
# the worse of the two, because a severity you counted outranks a severity you
# inferred. That is the same reason `evaluator-absent` precedes
# `evaluator-unresolved` at their shared 40.
#
# Both belong to "bounded claim" and neither implies the other, so there is no
# `CAP_IMPLICATIONS` entry: a dataset can be mostly generated with a sound
# answer key, or fully collected with a wrong one.
WIRING_CHECK_CEILING = 74
# One below the STRONG boundary at 75, which is the only derived number in this
# block: the claim is about what the result may PRESENT as, and under ten
# comparable examples it may not present as STRONG. See
# `WIRING_CHECK_EXAMPLES`.
GENERATED_ANSWER_KEY_CEILING = 75
# The questions are real and there are enough of them; only the answer key was
# written by a model, so the score reports agreement with that model. Above
# both synthetic ceilings because strictly more of the data was observed.
COARSE_RESOLUTION_CEILING = 89
# One below the EXCELLENT boundary at 90, derived the same way as 74: under
# thirty comparable examples a small difference may be chance, so the result
# may not present as EXCELLENT. The highest ceiling here, because nothing is
# wrong with this run at all. See `COARSE_RESOLUTION_EXAMPLES`.

CAP_SEVERITY_ORDER: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] = (
    (
        "no result to bound",
        (
            ("dataset-absent", DATASET_ABSENT_CEILING),
            ("evaluator-invalid", EVALUATOR_INVALID_CEILING),
            ("dataset-no-expected-outputs", DATASET_NO_EXPECTED_OUTPUTS_CEILING),
            ("dataset-integrity-fail", DATASET_INTEGRITY_CEILING),
            ("evaluator-absent", EVALUATOR_ABSENT_CEILING),
            ("evaluator-unresolved", EVALUATOR_UNRESOLVED_CEILING),
        ),
    ),
    (
        "answers the wrong question",
        (
            ("evaluator-timeout", EVALUATOR_TIMEOUT_CEILING),
            ("agent-no-varying-knobs", AGENT_NO_VARYING_KNOBS_CEILING),
            ("dataset-tune-holdout-overlap", SPLIT_OVERLAP_CEILING),
        ),
    ),
    (
        "bounded claim",
        (
            ("dataset-fully-synthetic", FULLY_SYNTHETIC_CEILING),
            ("dataset-mostly-synthetic", MOSTLY_SYNTHETIC_CEILING),
            ("dataset-unsound-expected-outputs", UNSOUND_ANSWER_CEILING),
            ("dataset-below-measurable-size", WIRING_CHECK_CEILING),
            ("dataset-generated-answer-key", GENERATED_ANSWER_KEY_CEILING),
            ("dataset-coarse-resolution", COARSE_RESOLUTION_CEILING),
        ),
    ),
)

# The one ceiling per condition, read off the order above so the two cannot
# disagree. Every `Cap(...)` in this module passes the named constant, and a
# test reads the source to prove it - a literal at a call site is how one
# condition acquires two ceilings, which is the defect `action_kind` already
# removed for remedies.
CAP_CEILING: dict[str, int] = {
    condition: ceiling
    for _group, entries in CAP_SEVERITY_ORDER
    for condition, ceiling in entries
}

# Where one condition's evidence STRICTLY IMPLIES another's, the stricter one
# must not carry the higher ceiling. This is the ordering rule with a
# derivation rather than a judgment behind it: a dataset where every row is
# generated is also a dataset where most rows are, so it cannot be the less
# capped of the two. It is also the exact shape that failed before #144, where
# two overlapping unreadable-dataset conditions were ranked independently.
#
# `(stricter, looser)`. Asserted, not documented: adding a cap that narrows an
# existing one and giving it a higher ceiling fails the suite.
CAP_IMPLICATIONS: tuple[tuple[str, str], ...] = (
    # No dataset is also no expected outputs, and no comparable examples.
    ("dataset-absent", "dataset-no-expected-outputs"),
    ("dataset-absent", "dataset-below-measurable-size"),
    ("dataset-absent", "dataset-coarse-resolution"),
    # No labels is no comparable example either, under a reference-based method.
    ("dataset-no-expected-outputs", "dataset-below-measurable-size"),
    # All of it generated is also most of it generated.
    ("dataset-fully-synthetic", "dataset-mostly-synthetic"),
    # Under ten comparable examples is also under thirty.
    ("dataset-below-measurable-size", "dataset-coarse-resolution"),
)


@dataclass(frozen=True)
class Cap:
    condition: str
    ceiling: int
    reason: str
    # Whether this condition stops the run, or only limits what it may claim.
    #
    # Every cap used to imply BLOCKED, which was right while every cap meant
    # "something here is broken". A ceiling that only says "this cannot present
    # as EXCELLENT" is a different statement: the run is fine, the claim is
    # bounded. Conflating them marked a healthy 30-row dataset BLOCKED and told
    # the assistant not to proceed with a run that was worth doing - against the
    # guide's own rule that a low score never stops the walkthrough.
    blocks: bool = True
    # Whether the run proceeds AND the user is still asked something first.
    #
    # `blocks` alone could not express this branch's own finding. Setting it
    # False was necessary - a reading of the answer key is not a defect the
    # assistant may cancel a paid run over - and on its own it deleted the
    # routing with the block: `recommended_action` returns `proceed` unless a
    # cap blocks, so the payload said "nothing to do" about a condition whose
    # entire content is a question for the user. The two states the payload
    # could express were "stop and fix this" and "carry on"; the one this
    # condition is in is neither.
    #
    # So it is a third: the ceiling stands, `status` stays OK, the run is worth
    # making - and `recommended_action` still carries the remedy, because there
    # IS something to do first and doing it changes the answer key the run is
    # graded against.
    #
    # Deliberately not set on every advisory ceiling. `dataset-coarse-
    # resolution` bounds a claim and asks nothing: telling a customer with 25
    # rows to `get-data` before their first run is the conflation `blocks` was
    # added to end. This flag says the cap is a QUESTION, which is a property
    # of `review-answer-key` and not of a size.
    asks: bool = False
    # Derived, never passed: `init=False` means no call site can supply one, so
    # the table above is the only place a remedy is decided and a condition
    # cannot acquire two.
    action_kind: str = field(init=False)

    def __post_init__(self) -> None:
        # Fails closed on an unmapped condition. A new cap therefore cannot ship
        # without a remedy - it raises the moment it is constructed, in the
        # author's own test run, rather than emitting a payload whose consumers
        # silently see no recommendation for that one condition.
        try:
            kind = ACTION_FOR_CONDITION[self.condition]
        except KeyError:
            raise ValueError(
                f"cap {self.condition!r} has no entry in ACTION_FOR_CONDITION; "
                "every cap names a remedy, so add one there rather than "
                "emitting a diagnosis a consumer cannot act on"
            ) from None
        object.__setattr__(self, "action_kind", kind)
        # The same guard for the ordering. A cap with no place in
        # `CAP_SEVERITY_ORDER` has an unranked ceiling, which is the state this
        # module was in for every cap until now: the number was whatever its
        # author picked, against neighbours nobody had compared it to. The
        # VALUE is deliberately not checked here - `Cap(condition, 50, ...)` is
        # a legitimate way to build a probe - so the value is pinned instead by
        # the source-reading test, which is where a wrong constant at a call
        # site actually shows up.
        if self.condition not in CAP_CEILING:
            raise ValueError(
                f"cap {self.condition!r} has no place in CAP_SEVERITY_ORDER; "
                "every cap is ranked against the others, so add it to the "
                "group its condition belongs to rather than choosing a "
                "ceiling that nothing compares"
            )
        if self.asks and self.blocks:
            raise ValueError(
                f"cap {self.condition!r} both blocks and asks; a blocking cap "
                "already routes its remedy, and the two together describe a "
                "run that is stopped and proceeding at once"
            )


# What each check is called on the card.
#
# The keys are this module's own vocabulary and stay that way in `--json`,
# where the reader is a machine and a stable identifier is the point. The
# values are for the card, where the reader is someone running their first
# optimization and "probe-spread" is not a phrase they have met.
#
# This is the guide's own rule applied to its most-read artifact: "Keep
# internal check IDs, SDK internals, and optimization jargon out of user-facing
# progress" (SKILL.md). Cap condition ids were already kept out; these twelve
# were printed verbatim, and nine of them appeared in no glossary entry, so a
# reader who wanted to know what "power" meant had nowhere to look.
#
# Each is phrased as the question the check answers, so the line reads as a
# finding rather than a category.
CHECK_DISPLAY_NAMES: dict[str, str] = {
    # dataset
    "labels": "answers to score against",
    "power": "examples to compare on",
    "difficulty": "range of difficulty",
    "diversity": "repeated or dominant answers",
    "provenance": "where the rows came from",
    # evaluation
    "calibration": "checked on known-good and known-bad",
    "task-fit": "right kind of check for this output",
    "reproducibility": "same answer every time",
    "probe-spread": "separates good answers from bad",
    # agent
    "knob-count": "settings that vary",
    "variation": "how widely each setting varies",
    "coverage": "the settings that matter most",
}


def display_name(check: str) -> str:
    """The card's name for a check, falling back to the internal one.

    Falls back rather than raising: a missing entry costs a reader one obscure
    word, while a scorer that refuses to render its own card costs them the
    result. A test keeps the table complete, which is the right place for that
    to fail - in the author's run, not the user's.
    """
    return CHECK_DISPLAY_NAMES.get(check, check)


def binds(cap: Cap, overall: int) -> bool:
    """Whether this cap's ceiling is the one actually holding the score down.

    `aggregate` takes the *lowest* ceiling and the weighted average, so a cap
    can be entirely real and still not be the operative limit - either a
    stricter cap sits below it or the pillars never reached it. Its ceiling is
    then a number that describes nothing on the report it is printed on.

    Both renderers ask this rather than each deciding for itself, because the
    card and the durable report drifting apart is how this class of defect got
    reported twice: the card's cap line was fixed while the markdown one, whose
    heading keys off `status` and so looked fine, kept the same unconditioned
    number.

    `overall` is `min(weighted_average, min(ceilings))`, so it is never above a
    ceiling - equality is the whole test.
    """
    return cap.ceiling == overall


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
    # The one thing to do next, from ACTION_KINDS. Per-cap remedies say what
    # each condition asks for; this says which of them to do FIRST, which is the
    # question a reader actually has when several fired.
    #
    # Named `recommended_action` and not `action`, because `--json` emits two
    # different payloads and the other one already has an `action`:
    # `ReadinessPlan.action` is a PROSE sentence for a human, this is a slug from
    # a closed set for a machine. Same flag, same word, different type - so they
    # are deliberately not the same key, and must not be unified into one later.
    # A plan payload carries no `schema_version`, which is how a consumer tells
    # the two apart.
    recommended_action: str
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
    tuning_labelled_rows: int | None = None
    holdout_labelled_rows: int | None = None
    difficulty_bands: tuple[str, ...] = ()
    difficulty_tagged_rows: int | None = None
    duplicate_status: str | None = None
    near_duplicate_status: str | None = None
    ceiling_risk: bool = False
    split_overlap: bool = False
    integrity_failed: bool = False
    # True only when EVERY row is generated. Mixtures are read from the counts
    # below; asking "is this dataset synthetic" of a mixture has no true answer.
    synthetic: bool = False
    generated_outputs: bool = False
    # Row counts by provenance class. All zero means the preflight JSON predates
    # them, and `score_provenance` falls back to the pre-count behaviour rather
    # than reading the absence as an empty dataset.
    collected_rows: int = 0
    synthesised_rows: int = 0
    undeclared_rows: int = 0
    # Rows carrying an expected answer, and how many of those answers a model
    # wrote rather than a person observing them.
    answerable_rows: int = 0
    generated_answer_rows: int = 0
    # Rows whose expected output carries no word characters ("-", "?", "..."):
    # kept as labels while their intentional-label/placeholder meaning is unverified.
    placeholder_rows: int = 0
    sources: tuple[str, ...] = ()
    # Custom source tokens that preflight credited as collected for backward
    # compatibility but could not verify from its vocabulary.
    unrecognised_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class RowReview:
    """The assistant's own read of whether each expected output answers its input.

    Deliberately NOT a field on `DatasetFacts`. Everything in that class was
    measured by preflight from the user's files; this was judged by the
    assistant reading the rows, and the two must not become one bag of "facts"
    a later reader treats alike. Every other check in this scorer looks at one
    column - empty golds, constant golds, dominant answers, duplicates - so a
    row whose expected answer plainly contradicts its own input passes all of
    them, and the optimizer then rewards whichever configuration gets it wrong.

    It carries no points. A judgement can withhold a claim and may not
    manufacture one, so a clean review leaves the score exactly where not
    running it at all would have left it, and says so in the evidence line
    instead - where it costs nothing and names who did the checking.
    """

    supplied: bool = False
    # Rows read, and the verdicts. `unsound` is "this expected output is not a
    # sensible answer to this input"; `unsure` is the assistant declining to
    # answer, which is reported and never scored - deciding it belongs to the
    # user, through the same approval gate a gold change already needs.
    reviewed: int = 0
    unsound: int = 0
    unsure: int = 0
    # Reviewed rows by the provenance class preflight assigned them. Kept so
    # the coverage claim can be checked against the counted rows rather than
    # believed: a review cannot say it read more collected rows than exist.
    reviewed_collected: int = 0
    reviewed_undeclared: int = 0
    # How many of the `unsound` rows are among the rows this run will actually
    # tune and check on. The run reads 28 rows - 18 tuning and 10 held out - so
    # a wrong answer outside them changes nothing that happens, and a wrong
    # answer inside them is what the search is about to be graded against.
    # Those are two different sentences to a customer, and the card can only
    # tell them apart if the review says which rows it is talking about.
    #
    # Optional, and absent is not zero. At the opening gate on a large dataset
    # the subset has not been drawn yet, so nothing can honestly claim
    # membership; `None` is that state and the card then says only that the
    # file has bad rows. On a dataset at or under the subset size, every
    # provided row is a row the run uses, which is the case where this is worth
    # saying and the case where it is knowable.
    unsound_in_run: int | None = None


@dataclass(frozen=True)
class EvaluationFacts:
    # An evaluator is connected, on EITHER witness: a method was declared for
    # it, or preflight's static shape check found a file on disk. It used to
    # mean only the first, which is why a project whose evaluator existed but
    # could not be honestly named scored identically to one with no evaluator
    # at all - "absent", and routed to create/select rather than to
    # inspect/repair (traigent-first-run#133). `method` still says whether
    # this run can name what it does; `present` says only that something is
    # there to name.
    present: bool = False
    method: str | None = None
    task_kind: str | None = None
    calibration_present: bool = False
    # Whether a calibration payload reached the scorer at all, which is a
    # different fact from whether it carried checks. Without it the scorer can
    # only see "no checks" and cannot tell a calibration that never ran from
    # one that ran and produced none - and it was reporting the first of those
    # as though it had established it.
    calibration_supplied: bool = False
    checks: tuple[dict[str, bool], ...] = ()
    probe_scores: tuple[tuple[float, ...], ...] = ()
    timed_out: bool = False
    # Whether the evaluator source parses as Python, from preflight's static
    # `ast.parse`-only check (never import, never execution). None means that
    # check never ran - not that it passed. `present=True` with `method=None`
    # and this still None or True is "a file is connected but no method could
    # be honestly declared for it" (an ambiguous or ordinary-looking shape);
    # False narrows that same present-but-unresolved state to "the file is
    # not even valid Python" (traigent-first-run#133).
    parses: bool | None = None


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
    # Whether a config-space document reached the scorer at all. Distinct from
    # whether it declared knobs, and the distinction is the whole point: the
    # guide deliberately withholds a document found before this run's search
    # (traigent-first-run#105), so the common opening state is "nothing was
    # supplied" - and the card was reporting that as "no knobs declared", which
    # is a claim about the user's project rather than about this score's input.
    config_space_supplied: bool = False


def round_half_up(value: float) -> int:
    """Round .5 away from zero.

    `round()` uses banker's rounding, which surprises a reader at a band
    boundary: round(74.5) is 74, not 75.
    """
    return int(math.floor(value + 0.5))


def band_for(
    score: int, confidence: float, weakest_pillar_confidence: float | None = None
) -> tuple[str, bool]:
    """Return the band, demoted when too little of the score was measured.

    Renormalizing unmeasured sub-scores can *raise* a score when less is known,
    so a thin-evidence run is not allowed to present as STRONG or EXCELLENT.

    Both confidences are checked, because the aggregate alone did not deliver
    that promise. It is a weighted mean, so two fully-measured pillars carry a
    nearly-unmeasured third over the line: agent 1.00, dataset 1.00 and an
    uncalibrated evaluation pillar at 0.45 average to 0.81, clear of the 0.75
    gate, and the run reported 89 STRONG with a 100/100 evaluation pillar that
    had observed two of its four checks. An uncalibrated evaluator is the exact
    thin evidence this guard exists to refuse - and it is the ordinary state of
    the opening card, which runs before any calibration exists.
    """
    band = BAND_ORDER[-1]
    for threshold, name in BAND_THRESHOLDS:
        if score < threshold:
            band = name
            break
    thinnest = confidence
    if weakest_pillar_confidence is not None:
        thinnest = min(confidence, weakest_pillar_confidence)
    if thinnest >= MIN_CONFIDENCE_FOR_TOP_BANDS:
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

    if not unique:
        # A knob with no candidates is not a narrower search space: every
        # numeric path below reaches `max(numbers)` on an empty list. The
        # config-space adapter refuses this shape outright, so this is the
        # answer for a caller that builds `AgentFacts` directly.
        return KnobScore(
            name=name,
            kind="empty",
            distinct_values=0,
            effective_values=0,
            span=0.0,
            resolution=0.0,
            coverage=0.0,
            quality=0.0,
            span_ratio=None,
            notes=("no candidate values - nothing to search",),
        )

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


# A deduction cannot express "this cannot be trusted". Power is 25 of the
# dataset pillar's 100 and the pillar is 40% of the total, so the entire range
# from perfect to worst moves the overall score by 8 - a one-row holdout could
# still reach 92 and read as "proceed" (traigent-first-run#88).
#
# Same shape, and the same number, as the provenance case the rubric already
# fixed: "a ten-point deduction still allowed a synthetic dataset perfect on
# every other dimension to score 93", so provenance was capped instead. Power
# was left with the identical structure and no cap.
#
# The thresholds reuse the planning bands `size_points` already draws. They
# bound the strength of a claim from sample size alone; they do not pretend to
# calculate paired uncertainty or a minimum detectable effect before outcomes
# exist. The ceilings sit one point below a band edge because the claim is about
# what the result may *present as*, not about the arithmetic.
#
# The two ceilings themselves live with every other ceiling in
# `CAP_SEVERITY_ORDER`, because their ORDER against the rest is a rule and a
# number defined beside its own threshold is a number nothing ranks. The
# thresholds stay here, where they are read.
WIRING_CHECK_EXAMPLES = 10
COARSE_RESOLUTION_EXAMPLES = 30


def power_ceiling(effective_n: int | None) -> Cap | None:
    """Bound claim strength using a pre-run sample-size planning band.

    Returns None outside the two small-set planning bands; that is not a claim
    that uncertainty has been calculated. The count passed in is the *scoreable*
    one, which is why #88 was blocked on #67: capping a number that under-states
    power for a reference-free judge would convert a soft under-claim into a
    hard, band-changing false verdict.
    """
    if effective_n is None:
        return None
    if effective_n < WIRING_CHECK_EXAMPLES:
        return Cap(
            "dataset-below-measurable-size",
            WIRING_CHECK_CEILING,
            # The arithmetic IS the context. "Wiring check" told a reader
            # nothing; "one example is worth 17 points" tells them why a winner
            # here may just have caught a lucky row. Guarded because a dataset
            # can have rows and nothing scoreable, and 100/0 would take the
            # scorer down on the one card that most needs to render.
            (
                f"only {effective_n} comparable example(s) - one example moves "
                f"the score by about {100 / effective_n:.0f} points, so a "
                "configuration can look better by winning a single row. Treat "
                "any difference as a hint, not a result."
                if effective_n
                else "no example can be scored, so nothing can be compared."
            ),
        )
    if effective_n < COARSE_RESOLUTION_EXAMPLES:
        return Cap(
            "dataset-coarse-resolution",
            COARSE_RESOLUTION_CEILING,
            # Says what it costs the reader, not how a statistician would
            # measure it. "Paired uncertainty from completed paired outcomes"
            # is the method, and the method belongs in the reference the
            # assistant reads - a card is glanced at, not studied.
            f"{effective_n} comparable examples is a small comparison set, so "
            "a small difference between configurations may be chance rather "
            "than a real improvement.",
            # The run is worth making - it just cannot claim a small win.
            blocks=False,
        )
    return None


def size_points(effective_n: int | None) -> tuple[float, str]:
    """Place the smaller scoreable split in a pre-run sample-size planning band.

    Sample size alone cannot supply paired uncertainty or a detectable effect:
    both depend on completed paired outcomes. These ordinal bands reward more
    evidence without attaching an unsupported percentage-point claim.
    """
    if effective_n is None:
        return 0.0, "no usable split size"
    if effective_n < 10:
        return 5.0, f"{effective_n} comparable examples - a wiring check, not a score"
    if effective_n < 30:
        return 12.0, f"{effective_n} examples - small comparison set"
    if effective_n < 50:
        return 18.0, f"{effective_n} examples - limited comparison set"
    if effective_n < 100:
        return 22.0, f"{effective_n} examples - moderate comparison set"
    if effective_n < 300:
        return 23.0, f"{effective_n} examples - substantial comparison set"
    return 25.0, f"{effective_n} examples - large comparison set"


# Per-row provenance credit, out of the sub-score's 10 points. The ladder is the
# same question asked twice: was the question observed, and was the answer?
COLLECTED_ROW_POINTS = 10.0  # observed question, observed answer
GENERATED_ANSWER_ROW_POINTS = 6.0  # observed question, answer written by a model
UNDECLARED_ROW_POINTS = 6.0  # says nothing - not credited as production data
SYNTHESISED_ROW_POINTS = 3.0  # neither was observed

# A cap is a ceiling on the whole run, not a deduction. It exists because a
# points deduction cannot stop an average from hiding a fatal flaw: 10 -> 3 on a
# 10-point sub-score inside a 40%-weighted pillar moves the overall score by
# 2.8, so a fully generated dataset that was perfect everywhere else still
# reported 93 and read as production-ready.
#
# The three ceilings these shares raise are defined with every other ceiling in
# `CAP_SEVERITY_ORDER`; only the shares that trigger them live here.
MOSTLY_SYNTHETIC_SHARE = 0.5
GENERATED_ANSWER_KEY_SHARE = 1.0

# The row-level sanity check's ceiling lives with every other ceiling in
# `CAP_SEVERITY_ORDER`, because its ORDER against the rest is a rule and a
# number defined beside its own threshold is a number nothing ranks. Only the
# share that triggers it lives here.
#
# One row in ten. Grounded in what the run does with these rows rather than
# picked for roundness: the recommended configuration is reported on ten
# held-out rows, so one wrong answer there moves the reported number by ten
# points - larger than the gaps this run uses to rank configurations. At that
# share the wrong answers can outweigh the differences the score is being read
# for, which is the point at which the claim has to be bounded rather than
# footnoted.
UNSOUND_ANSWER_SHARE = 0.1
# The three answers the check may give, and the only author it may declare.
ROW_REVIEW_VERDICTS = ("yes", "no", "unsure")
ROW_REVIEW_REVIEWER = "assistant"
# Provenance classes a reviewed row may carry. `synthesised` is absent on
# purpose and refused below: this run's own generated rows are out of scope.
ROW_REVIEW_ORIGINS = ("collected", "undeclared")


def _row_count(value: Any, name: str) -> int:
    """Read one provenance row count, refusing a present-but-impossible one.

    An absent key means the preflight JSON predates the field, and falls back to
    0 so an older payload keeps scoring as it did. A key that IS present and
    carries a negative or non-integer count is a different thing: it reaches the
    arithmetic, shifts the denominator every share is computed over, and can
    push the sub-score past its own 10-point maximum (`-1` synthesised rows
    against 50 collected scores 10.14). Refused for the same reason, and with
    the same message, as the declared-split counts a few lines below - a guard
    that checks four counts and waves three through is the odd-one-out this
    file already has an issue open about (traigent-first-run#69).
    """
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PreflightInputError(
            f"dataset-provenance carries no usable {name} count - row counts "
            "are whole and non-negative, so this preflight JSON was edited or "
            "predates the current preflight.py; re-run preflight.py --json "
            "from the same version as this script"
        )
    return value


def score_provenance(
    facts: DatasetFacts, *, uses_expected_outputs: bool = True
) -> tuple[float, str, list[Cap]]:
    """Credit provenance by share, and cap on how much of the data was invented.

    Scored per row and averaged rather than by an all-or-nothing test. The old
    `any(is_synthetic(...))` marked a 1000-row collected dataset fully generated
    on the strength of one demo row: 3 of 10 points, the run capped at 65, and a
    detail line claiming every row was generated. Mixtures are the normal case
    once a user tops up real data with examples, so they get a real answer.

    Falls back to the pre-count behaviour when the counts are absent, which is
    what a preflight JSON written before this field looks like - an older
    payload keeps scoring exactly as it did rather than silently reading 0 rows.
    """
    caps: list[Cap] = []
    counted = facts.collected_rows + facts.synthesised_rows + facts.undeclared_rows
    if not counted:
        if facts.synthetic:
            return (
                SYNTHESISED_ROW_POINTS,
                "fully generated - cannot represent production traffic",
                [
                    Cap(
                        "dataset-fully-synthetic",
                        FULLY_SYNTHETIC_CEILING,
                        "The dataset is generated, so a high score here measures "
                        "the walkthrough, not real-world readiness.",
                    )
                ],
            )
        if "unknown" in facts.sources or not facts.sources:
            return (
                UNDECLARED_ROW_POINTS,
                "no row says whether it was collected or generated, so none "
                "counts as evidence about real traffic",
                [],
            )
        return (
            COLLECTED_ROW_POINTS,
            f"declared sources: {', '.join(facts.sources)}",
            [],
        )

    # An answer written by a model downgrades a row that was otherwise
    # collected; it cannot downgrade one already counted as synthesised, and
    # cannot rescue one either.
    generated_answers = (
        min(facts.generated_answer_rows, facts.collected_rows)
        if uses_expected_outputs
        else 0
    )
    clean_collected = facts.collected_rows - generated_answers
    points = (
        clean_collected * COLLECTED_ROW_POINTS
        + generated_answers * GENERATED_ANSWER_ROW_POINTS
        + facts.undeclared_rows * UNDECLARED_ROW_POINTS
        + facts.synthesised_rows * SYNTHESISED_ROW_POINTS
    ) / counted

    synthesised_share = facts.synthesised_rows / counted
    if facts.synthesised_rows == counted:
        caps.append(
            Cap(
                "dataset-fully-synthetic",
                FULLY_SYNTHETIC_CEILING,
                "The dataset is generated, so a high score here measures the "
                "walkthrough, not real-world readiness.",
            )
        )
    elif synthesised_share > MOSTLY_SYNTHETIC_SHARE:
        # Without this the any()->all() correction would hand every mixture a
        # free pass: a 90%-generated dataset would lose its ceiling entirely.
        caps.append(
            Cap(
                "dataset-mostly-synthetic",
                MOSTLY_SYNTHETIC_CEILING,
                "Most of the dataset is generated, so the result mostly "
                "measures invented examples rather than real traffic.",
            )
        )

    # The expected answers are the ruler every score is measured against. When
    # all of them were written by a model, an accuracy number reports agreement
    # with that model's opinion, not correctness - believable, and unfalsifiable
    # from inside the run. The questions are still real, so this ceiling sits
    # above both synthetic ones.
    if (
        facts.answerable_rows
        and uses_expected_outputs
        and facts.generated_answer_rows
        >= facts.answerable_rows * GENERATED_ANSWER_KEY_SHARE
        and facts.synthesised_rows != counted
    ):
        caps.append(
            Cap(
                "dataset-generated-answer-key",
                GENERATED_ANSWER_KEY_CEILING,
                "Every expected answer was written by a model, so a score "
                "measures agreement with that model rather than correctness.",
                # Advisory, for the reason this branch already gives for its
                # own sibling: `review-answer-key` is a question put to the
                # customer, not a creation and not a repair, and under the rule
                # on `Cap.blocks` a question bounds a claim rather than
                # cancelling a run.
                #
                # It was left at the dataclass default here, which made this
                # branch ship the one state its own guarding test forbids: two
                # conditions under ONE remedy slug with opposite verdicts, and
                # the STRICTER ceiling (75) proceeding while the looser one
                # (70) blocked. On this branch's own base both were True; the
                # `False` was expected to arrive with #149, which reaches the
                # same conclusion independently and sets exactly this line. If
                # that lands first the two edits agree, so the conflict
                # resolves to the value both sides already chose.
                blocks=False,
            )
        )

    return (
        round(points, 2),
        provenance_evidence(
            facts, counted, uses_expected_outputs=uses_expected_outputs
        ),
        caps,
    )


def provenance_evidence(
    facts: DatasetFacts, counted: int, *, uses_expected_outputs: bool = True
) -> str:
    """Name the mixture, so a share is never rounded away into one word.

    "mostly real" and "mostly generated" are the same word to a reader who
    wanted the number, and the number is what decides whether the result can be
    quoted, so the counts go in the line.
    """
    if facts.synthesised_rows == counted:
        return "fully generated - cannot represent production traffic"
    unverified = ""
    if facts.unrecognised_sources:
        unverified = (
            "; unrecognized provenance tokens treated as collected on an "
            f"unverified declaration: {', '.join(facts.unrecognised_sources)}"
        )
    parts: list[str] = []
    if facts.collected_rows:
        parts.append(f"{facts.collected_rows} collected")
    if facts.synthesised_rows:
        parts.append(f"{facts.synthesised_rows} generated")
    if facts.undeclared_rows:
        parts.append(f"{facts.undeclared_rows} undeclared")
    mixture = f"{', '.join(parts)} of {counted} rows"
    if facts.undeclared_rows:
        # "Undeclared" is a category name; on its own it tells a reader nothing
        # they can act on. The line is about trust - a row that does not say
        # where it came from cannot be credited as real traffic - so the
        # consequence is spelled once here rather than folded into the count,
        # which produced "30 not saying whether they were collected or
        # generated of 30 rows".
        # Deliberately avoids naming either origin. An existing guard refuses
        # the word "collected" on a line about undeclared inputs, because a
        # reader skimming it takes the word for a claim that the rows are real -
        # which is the misreading this whole sub-score exists to prevent.
        mixture += (
            " (undeclared means the row does not record where it came from, so "
            "it cannot count as evidence about real traffic)"
        )
    if facts.generated_answer_rows:
        if not uses_expected_outputs:
            return (
                f"{mixture}; {facts.generated_answer_rows} model-written expected "
                f"answers are present but unused by this evaluator{unverified}"
            )
        return (
            f"{mixture}; {facts.generated_answer_rows} of {facts.answerable_rows} "
            f"expected answers written by a model, not observed{unverified}"
        )
    if not facts.synthesised_rows:
        return (
            f"{mixture}; declared sources: {', '.join(facts.sources)}" f"{unverified}"
        )
    return f"{mixture}{unverified}"


def labels_evidence(labelled: int, rows: int, placeholders: int) -> str:
    """Name symbol-only outputs without guessing whether they are placeholders.

    A punctuation-only output can be an intentional class label. The scorer
    therefore keeps it in the declared label/sample counts while making the
    unresolved interpretation visible.
    """
    base = f"{labelled}/{rows} rows carry an expected output"
    if not placeholders:
        return base
    return (
        f"{base}; {placeholders} are symbol-only and need confirmation as "
        "intentional labels or placeholders (retained in these counts)"
    )


REFERENCE_FREE_METHODS = frozenset(
    {"llm-judge-pointwise", "llm-judge-pairwise", "llm-judge-rubric"}
)


def row_review_evidence(review: RowReview, facts: DatasetFacts) -> str:
    """Say what the read covered and what it found, in the line that costs nothing.

    A clean pass has to be able to say something, or the check is invisible
    whenever it works. It says it here rather than in points, because points
    would be the assistant crediting its own opinion - and every count in the
    sentence is a coverage claim, so the sentence names the rows read against
    the rows there are. The score reads the whole dataset, not a subset, and a
    review of 28 rows out of 4,812 says exactly that instead of implying the
    dataset was cleared.
    """
    if not review.supplied:
        return ""
    counted = facts.collected_rows + facts.synthesised_rows + facts.undeclared_rows
    provided = (
        facts.collected_rows + facts.undeclared_rows if counted else (facts.rows or 0)
    )
    line = f"the coding assistant read {review.reviewed} of {provided} provided rows"
    if review.unsound == 1:
        line += "; 1 expected answer contradicts its input"
    elif review.unsound:
        line += f"; {review.unsound} expected answers contradict their input"
    else:
        line += "; none contradicts its own input"
    if review.unsure:
        line += f", {review.unsure} undecided"
    if facts.synthesised_rows:
        line += f"; {facts.synthesised_rows} generated rows not reviewed"
    return line


def run_rows(facts: DatasetFacts) -> int | None:
    """How many rows this run will actually tune and check on, when it is known.

    Read from the declared split rather than from the guide's default 28,
    because the two are not the same claim: 28 is what this walkthrough creates
    when it has to create a dataset, and a customer who brought their own split
    has whatever they brought. `None` when no split has been declared yet -
    which is the ordinary opening state on one undivided file, and the state in
    which the card may not put a number on it.
    """
    if facts.tuning_rows is None or facts.holdout_rows is None:
        return None
    return facts.tuning_rows + facts.holdout_rows


def unsound_answer_cap(review: RowReview, run_rows: int | None = None) -> Cap | None:
    """The one ceiling this judgement may set, and never a point of credit.

    Fires on the share of what was actually read, which is the only population
    it has evidence about. A single wrong answer below that share is still
    surfaced - it becomes the approval-gated question the action table already
    requires, and it is counted in the evidence line above - it just does not
    bound the whole run on its own.

    An `unsure` never reaches here. Withholding a claim on evidence the
    assistant gathered is one thing; withholding it because the assistant could
    not decide would let uncertainty grade the user's data.
    """
    if not review.supplied or not review.reviewed or not review.unsound:
        return None
    if review.unsound < review.reviewed * UNSOUND_ANSWER_SHARE:
        return None
    subject = (
        "1 answer does not answer its own question"
        if review.unsound == 1
        else f"{review.unsound} answers do not answer their own question"
    )
    # Two different findings, and the reader has to be told which one this is.
    # The run reads a bounded subset - the tuning rows plus the held-out ten -
    # so a wrong answer outside it costs nothing: the file has a bad row and
    # the run never opens it. A wrong answer inside it is the run being graded
    # against something believed wrong, which is the whole reason to say any of
    # this before the paid search rather than after.
    if review.unsound_in_run is None:
        consequence = (
            "somewhere in the file this run draws from. Whether the search "
            "reads them depends on which rows are drawn"
        )
    elif review.unsound_in_run == 0:
        consequence = (
            "outside the rows this run tunes and checks on, so the search does "
            "not read them"
        )
    else:
        scope = f"the {run_rows} rows" if run_rows else "the rows"
        consequence = (
            f"{review.unsound_in_run} of them among {scope} this run tunes and "
            "checks on, so the search is about to be graded against them"
        )
    return Cap(
        "dataset-unsound-expected-outputs",
        UNSOUND_ANSWER_CEILING,
        f"Reading each row's input beside its expected answer, {subject} "
        f"(of {review.reviewed} read) - {consequence}. This is the coding "
        "assistant's reading, not a measurement, so it is put to you as a "
        "question with the row and the reason, and nothing is edited until you "
        "answer. The run is not stopped; what it may claim is bounded until "
        "the answer key is agreed.",
        # Bounds, never blocks - and the reason is not a preference about
        # severity. Three things decide it, and they point the same way.
        #
        # The run only ever reads 28 rows (18 tuning, 10 held out). A customer
        # with 28 sound rows has a run worth making whatever else is in the
        # file; a broken row the search never opens stops nothing, and the
        # `unsound_in_run` clause above is what lets the card say which case
        # this is instead of asserting the worse one.
        #
        # On collected data this judgement can simply be wrong. A row that
        # reads as contradictory to a model can be correct in the customer's
        # domain - a refund approved outside the policy window because their
        # goodwill rule says so - and an opinion that can be wrong may bound a
        # claim and may not cancel the customer's run. (On model-generated rows
        # the judgement is far more likely right, and those rows are refused by
        # this input and bounded by the synthetic ceiling anyway.)
        #
        # And the remedy decides it, under the rule on `Cap.blocks`: a route
        # that asks for a creation or a repair blocks, a route that scopes what
        # the result may claim is advisory. `review-answer-key` is a question
        # put to the customer - not a creation, not a repair.
        # `dataset-generated-answer-key` carries that identical slug and is
        # advisory for the same reason, and one remedy may not mean "stop" on
        # one card and "proceed" on the next. Whether each provenance cap
        # blocks is decided once, beside those caps; this one is decided here,
        # and the two decisions have to agree.
        blocks=False,
        # And ASKS, which is the half `blocks=False` alone deleted. The entire
        # content of this condition is a question for the user, and with the
        # block removed `recommended_action` returned `proceed` - a payload
        # saying there is nothing to do about a finding whose only purpose is
        # to be acted on before the run. Measured: 89 STRONG / OK / proceed
        # under the default `blocks=True` became 70 WORKABLE / BLOCKED /
        # review-answer-key, and `blocks=False` on its own returned it to
        # proceed with the remedy gone. The run proceeds, the ceiling stands,
        # and the remedy is still named.
        asks=True,
    )


def scores_without_a_reference(method: str | None) -> bool:
    """True when the evaluator can score a row that carries no expected output.

    A rubric or pointwise judge reads the input and the output; the gold answer
    is not an input to it. So "how many rows are scoreable" has a different
    answer for those methods, and the dataset pillar cannot answer it alone
    (traigent-first-run#67).
    """
    return method in REFERENCE_FREE_METHODS


def score_dataset(
    facts: DatasetFacts,
    evaluator_method: str | None = None,
    review: RowReview | None = None,
) -> tuple[Pillar, list[Cap]]:
    caps: list[Cap] = []
    subs: list[SubScore] = []
    review = review or RowReview()

    if not facts.exists or not facts.rows:
        caps.append(
            Cap(
                "dataset-absent",
                DATASET_ABSENT_CEILING,
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
    reference_free = scores_without_a_reference(evaluator_method)
    labelled = facts.labelled_rows if facts.labelled_rows is not None else 0
    # Appended to whichever labels line is written, and only ever appended: it
    # is the sub-score named "answers to score against", which is the one the
    # question "is this a sensible answer to this input" belongs to. It changes
    # no value and no maximum, so a review that finds nothing leaves this
    # pillar byte-for-byte where an unreviewed run leaves it apart from this
    # clause.
    review_clause = row_review_evidence(review, facts)

    def with_review(evidence: str) -> str:
        return f"{evidence}; {review_clause}" if review_clause else evidence

    if reference_free:
        subs.append(
            SubScore(
                "labels",
                0.0,
                30.0,
                False,
                with_review(
                    "this reference-free evaluator does not use expected outputs"
                    + (f" ({labelled} present but unused)" if labelled else "")
                ),
            )
        )
    elif labelled == 0:
        caps.append(
            Cap(
                "dataset-no-expected-outputs",
                DATASET_NO_EXPECTED_OUTPUTS_CEILING,
                "Rows have inputs but no expected outputs, so there is nothing to "
                "score a configuration against.",
            )
        )
        subs.append(
            SubScore(
                "labels",
                0.0,
                30.0,
                True,
                with_review(f"{rows} rows, none with an expectation"),
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
                with_review(labels_evidence(labelled, rows, facts.placeholder_rows)),
            )
        )

    # How many rows this run can actually compare configurations on. For a
    # reference-based scorer that is the labelled count: a row with no expected
    # answer cannot be scored against one. For a reference-free judge - rubric,
    # pointwise, pairwise - the gold answer is not an input at all, so every row
    # with an input is scoreable and clamping to the labelled count *understates*
    # power rather than protecting anyone (traigent-first-run#67).
    #
    # The pillar therefore takes the resolved method. Before, `score_dataset`
    # received only DatasetFacts and structurally could not ask: a 100-row set
    # with 10 reference answers was put in the smallest planning band even when
    # a rubric judge could score all 100. That under-claim is the same class of
    # error as an over-claim, and a ceiling would turn it into a hard,
    # band-changing false verdict.
    def scoreable(rows_available: int, labelled_available: int) -> int:
        return (
            rows_available
            if reference_free
            else min(rows_available, labelled_available)
        )

    if facts.tuning_rows is not None and facts.holdout_rows is not None:
        split_floor = min(facts.tuning_rows, facts.holdout_rows)
        if reference_free:
            # A judge that needs no reference scores every row in the smaller
            # split, so the labelled counts do not bound this comparison at all.
            # Reached for a DECLARED split, which is the common shape - applying
            # the method only to the no-split branch left the fix dead exactly
            # where most datasets land.
            effective = split_floor
            marker = f"{split_floor} scoreable"
        elif (
            facts.tuning_labelled_rows is not None
            and facts.holdout_labelled_rows is not None
        ):
            effective = min(
                split_floor, facts.tuning_labelled_rows, facts.holdout_labelled_rows
            )
            marker = (
                f"{facts.tuning_labelled_rows}/{facts.holdout_labelled_rows} scoreable"
            )
        else:
            effective = scoreable(split_floor, labelled)
            marker = f"{labelled} scoreable"
        points, evidence = size_points(effective)
        prefix = f"{facts.tuning_rows} to tune on / {facts.holdout_rows} held back"
        if effective < split_floor:
            prefix = f"{prefix}, {marker}"
        evidence = f"{prefix}; {evidence}"
    elif facts.tuning_rows is not None:
        tuning_labelled = (
            facts.tuning_labelled_rows
            if facts.tuning_labelled_rows is not None
            else labelled
        )
        effective = scoreable(facts.tuning_rows, tuning_labelled)
        points, evidence = size_points(effective)
        points *= 0.8
        if effective < facts.tuning_rows:
            evidence = (
                f"{facts.tuning_rows} tuning rows, {tuning_labelled} scoreable; "
                f"{evidence}"
            )
        evidence = (
            f"{facts.tuning_rows} tuning rows and no held-out set, so the "
            f"result would be measured on the same rows the search used; {evidence}"
        )
    else:
        effective = scoreable(rows, labelled)
        points, evidence = size_points(effective)
        points *= 0.8
        if effective < rows:
            evidence = f"{rows} rows, {labelled} scoreable; {evidence}"
        evidence = (
            "no tuning set and held-out set, so the result would be "
            f"measured on the same rows the search used; {evidence}"
        )
    subs.append(SubScore("power", round(points, 2), 25.0, True, evidence))
    # Deducting alone let the card say "a wiring check, not a score" and return
    # STRONG in the same breath (#88). The ceiling is what stops a result
    # presenting as trustworthy when nothing measurable was measured.
    ceiling = power_ceiling(effective)
    if ceiling is not None:
        caps.append(ceiling)

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
                (
                    "; ".join(problems)
                    if problems
                    else "no repeated questions, and no single answer used by most rows"
                ),
            )
        )
    else:
        subs.append(
            SubScore("diversity", 0.0, 20.0, False, "duplication was not checked")
        )

    provenance, evidence, provenance_caps = score_provenance(
        facts, uses_expected_outputs=not reference_free
    )
    caps.extend(provenance_caps)
    subs.append(SubScore("provenance", provenance, 10.0, True, evidence))

    # Guarded by the same question the generated-answer-key cap asks: when the
    # evaluator never reads an expected output, a wrong one cannot mis-rank
    # anything, so there is nothing to withhold. A dataset with no expected
    # outputs at all needs no guard - it already carries a ceiling of 30, well
    # below this one, so this cap could never be the binding number there.
    if not reference_free:
        unsound = unsound_answer_cap(review, run_rows(facts))
        if unsound is not None:
            caps.append(unsound)

    if facts.split_overlap:
        caps.append(
            Cap(
                "dataset-tune-holdout-overlap",
                SPLIT_OVERLAP_CEILING,
                "The same examples appear in both the set the search tunes on "
                "and the set held back to check it, so the final score is "
                "flattered - a believable wrong number.",
            )
        )
    if facts.integrity_failed:
        caps.append(
            Cap(
                "dataset-integrity-fail",
                DATASET_INTEGRITY_CEILING,
                "Some rows could not be read as data - malformed lines, or missing "
                "the input or expected-answer field.",
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
                EVALUATOR_ABSENT_CEILING,
                "No evaluation method is connected, so no result can be trusted.",
            )
        )
        subs.append(SubScore("calibration", 0.0, 40.0, True, "no evaluator"))
        subs.append(SubScore("task-fit", 0.0, 25.0, False, "no evaluator"))
        subs.append(SubScore("reproducibility", 0.0, 20.0, False, "no evaluator"))
        subs.append(SubScore("probe-spread", 0.0, 15.0, False, "no evaluator"))
        return combine("evaluation", subs), caps

    # `present` is true and no calibration result has spoken yet, but no
    # method was declared for it either - a file is connected and this run
    # cannot honestly say what it does. That is a different customer problem
    # from "evaluator-absent": nothing needs to be created or selected, an
    # existing file needs to be inspected, repaired, or replaced
    # (traigent-first-run#133).
    #
    # Every witness that calibration was ever engaged - real checks, a
    # supplied payload, or a payload that timed out before producing checks -
    # excludes this branch, so a run that tried and has something to say
    # (including "it timed out") keeps saying it through the paths below
    # rather than being relabelled "never resolved".
    calibration_engaged = (
        facts.calibration_present
        or facts.calibration_supplied
        or facts.timed_out
        or bool(facts.checks)
    )
    if facts.method is None and not calibration_engaged:
        if facts.parses is False:
            reason = (
                "An evaluator file is connected, but it does not parse as "
                "valid Python, so no method can be declared for it - inspect "
                "and repair or replace it."
            )
            evidence = "evaluator present but does not parse as Python"
        else:
            reason = (
                "An evaluator file is connected, but no method could be "
                "honestly declared for it without executing it, so no result "
                "can be trusted - inspect it and repair or replace it."
            )
            evidence = "evaluator present, method not resolved"
        caps.append(Cap("evaluator-unresolved", EVALUATOR_UNRESOLVED_CEILING, reason))
        subs.append(SubScore("calibration", 0.0, 40.0, True, evidence))
        subs.append(SubScore("task-fit", 0.0, 25.0, False, evidence))
        subs.append(SubScore("reproducibility", 0.0, 20.0, False, evidence))
        subs.append(SubScore("probe-spread", 0.0, 15.0, False, evidence))
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
                    EVALUATOR_INVALID_CEILING,
                    "The evaluator scores a wrong answer as well as a right one, "
                    "or returns a constant. Every number below it is unreliable.",
                )
            )
    else:
        # Say what this score can see, not what it infers about the world.
        #
        # "The evaluator was not calibrated" is a claim about the user's
        # project, and the only thing establishing it was that no calibration
        # payload reached this scorer. An evaluator calibrated last week, or in
        # a run whose JSON nobody passed to `--calibration`, produced it too.
        #
        # It could also be flatly self-contradicting: a calibration that RAN and
        # timed out emits a payload with no cases, so the same card reported
        # "the evaluator was not calibrated" beside an `evaluator-timeout` cap,
        # which can only fire when calibration ran.
        #
        # This module already draws the distinction correctly a hundred lines
        # away - "spread is unverified, not absent". This was the one place it
        # did not.
        if facts.timed_out:
            evidence = "calibration ran but did not finish"
        elif facts.calibration_supplied:
            evidence = "calibration ran but reported no checks"
        else:
            evidence = "no calibration result was provided to this score"
        subs.append(SubScore("calibration", 0.0, 40.0, False, evidence))

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
                f"scores a right answer {widest:.2f} above a wrong one, out of 1.00",
            )
        )
    else:
        subs.append(
            SubScore(
                "probe-spread",
                0.0,
                15.0,
                False,
                "not yet measured how far apart it scores a right and a wrong answer",
            )
        )

    if facts.timed_out:
        caps.append(
            Cap(
                "evaluator-timeout",
                EVALUATOR_TIMEOUT_CEILING,
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
    # Compared as integers rather than through `space_size / max_trials`: both
    # sides are unbounded Python integers, and true division of two large ones
    # raises OverflowError instead of answering the question.
    if max_trials and space_size and space_size > 20 * max_trials:
        base = min(base, 24.0)
    return base


NOTHING_WIRED_CAP = Cap(
    "agent-no-varying-knobs",
    AGENT_NO_VARYING_KNOBS_CEILING,
    "Nothing is marked as a setting the agent actually uses, so there is "
    "nothing to search.",
)

UNATTESTED_WIRING_CAP = Cap(
    "agent-no-varying-knobs",
    AGENT_NO_VARYING_KNOBS_CEILING,
    "Settings are listed, but none is marked as one the agent uses - marking "
    "them is what makes them searchable.",
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

    # Once, before anything counts a dimension - see `canonical_alias_names`.
    facts = canonical_alias_names(facts)

    # Order is deliberate: an empty `knobs` map is answered here, ahead of the
    # `wired` branch, so `{"knobs": {}}` keeps saying "no knobs declared"
    # whether or not it carries a `wired` key. Swapping the two branches would
    # silently reword the emptiest document in the file.
    if not facts.knobs:
        # Say which of the two this is. "No knobs declared" is a claim about the
        # user's project, and the guide deliberately withholds a config-space
        # document found before this run's search (#105) - so the ordinary
        # opening state is that nothing was supplied, and the card was reporting
        # it as though the project declared nothing. A user looking at an agent
        # with five knobs on screen reads that as the score being wrong.
        #
        # Same class as the calibration line (#121); this is its sibling, and
        # the phrase-list test written there was too narrow to catch it.
        evidence = (
            "the settings document lists no settings"
            if facts.config_space_supplied
            else "no settings document was provided to this score yet"
        )
        return nothing_to_search_pillar(evidence), [NOTHING_WIRED_CAP], []

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
                f"{len(facts.knobs)} setting(s) listed, none marked as one the "
                "agent uses - list those in the document's 'wired' field"
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

    # Two different questions, and one number cannot answer both.
    #
    # `space_size` is how many CONFIGURATIONS the search can distinguish, and it
    # is printed beside the knob counts - so it must be derived from the same
    # knobs those counts are, or the sentence does not add up. Multiplying over
    # every knob included `seed`, which this module deliberately excludes from
    # scoring, and printed "2 of 2 wired knobs actually vary; 24 combinations"
    # for two two-valued knobs. Four is the only number two of those can make.
    #
    # `run_count` is how many TRIALS the budget must cover, and there `seed`
    # does count: the SDK runs every combination once per seed, so the spend is
    # real even though the dimension measures variance rather than quality.
    # That is why the budget check below reads this one.
    space_size = 1
    for knob in scoreable:
        space_size *= knob.distinct_values
    run_count = 1
    for knob in knobs:
        run_count *= knob.distinct_values

    if not knobs:
        # Reachable now only for an explicit "wired": [] (or wired names
        # matching no declared knob). "no knobs declared" was false here:
        # knobs ARE declared, zero of them are attested as wired.
        return (
            nothing_to_search_pillar(
                f"0 of {len(facts.knobs)} listed settings are marked as ones "
                "the agent uses"
            ),
            [NOTHING_WIRED_CAP],
            knobs,
        )

    if not varying:
        caps.append(
            Cap(
                "agent-no-varying-knobs",
                AGENT_NO_VARYING_KNOBS_CEILING,
                "Every setting has only one value to try, so every configuration "
                "would be identical.",
            )
        )

    # Named when the two differ, because a reader who can add cannot otherwise
    # reconcile a budget penalty with the knobs on the same line - the knob that
    # caused it is, by construction, not among them.
    repeats = run_count // space_size if space_size else 1
    combinations = (
        f"{space_size} combinations"
        if repeats <= 1
        else f"{space_size} combinations x {repeats} repeats = {run_count} runs"
    )
    subs.append(
        SubScore(
            "knob-count",
            knob_count_points(len(varying), run_count, facts.max_trials),
            35.0,
            True,
            f"{len(varying)} of {len(scoreable)} wired knobs actually vary; "
            + combinations,
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
        # Already canonical: `canonical_alias_names` renamed the facts above.
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


# Caps outrank every sub-score gap - a broken ruler is not a few points - but
# they do not all outrank each other. Ranked flat at one weight, ties broke
# alphabetically, so the first thing the list told a user to fix was whichever
# cap sorted first by name, and not the one setting their score.
#
# Two things decide a cap's cost, so both order it. Whether it BLOCKS: paid work
# measured against a broken ruler measures the wrong thing, which outranks any
# ceiling. And whether it BINDS: among caps of the same kind, the one holding
# the score down is the one worth fixing first - the others cost nothing until
# it is gone. Ranking on `blocks` alone left the identical symptom between two
# blocking caps, which is the half of this defect the first fix missed.
BLOCKING_AND_BINDING_WEIGHT = 1000.0
BLOCKING_CAP_WEIGHT = 975.0
BINDING_CEILING_WEIGHT = 950.0
INACTIVE_CEILING_WEIGHT = 900.0


def cap_weight(cap: Cap, overall: int) -> float:
    """How much this cap is costing, as the ranked list orders it."""
    if cap.blocks:
        return (
            BLOCKING_AND_BINDING_WEIGHT if binds(cap, overall) else BLOCKING_CAP_WEIGHT
        )
    return BINDING_CEILING_WEIGHT if binds(cap, overall) else INACTIVE_CEILING_WEIGHT


def collect_gaps(
    pillars: Sequence[Pillar],
    knobs: Sequence[KnobScore],
    caps: Sequence[Cap],
    overall: int,
) -> tuple[str, ...]:
    """Order remediation by how many points it is actually costing.

    `overall` is required rather than defaulted: every cap's rank depends on
    whether its ceiling is the operative one, and a default would answer "no"
    for all of them - silently restoring the flat ordering this argument exists
    to replace, in whichever caller forgot to pass it.
    """
    gaps: list[tuple[float, str]] = []
    for cap in caps:
        gaps.append((cap_weight(cap, overall), f"{cap.condition}: {cap.reason}"))
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


def recommended_action(ordered_caps: Sequence[Cap]) -> str:
    """The one remedy to do first, from caps already sorted by ceiling.

    A blocking cap displaces `proceed` first: the run is waiting on it, so
    nothing else is the next thing to do. Among blocking caps the lowest
    ceiling wins, which is the one setting the score. `ordered_caps` is already
    sorted by ceiling, so the first blocking entry is that one; this reads the
    order rather than re-deriving it, so the two cannot disagree about which
    cap is most severe.

    An ASKING cap displaces it second, and that is the state the payload could
    not express. A ceiling that stops nothing and still has a question behind
    it - "these rows look wrong to me; do you agree?" - used to come out as
    `proceed`, so a consumer reading the payload saw no remedy for the one
    condition whose entire content is a remedy. It is not the same as blocking:
    `status` stays OK, the run is worth making, and the question is what to do
    before it rather than instead of it.

    An advisory ceiling that asks nothing still recommends nothing. Bounding a
    claim is not a defect, and telling a customer with 25 rows to go and get
    more before their first run is the conflation `blocks` was added to end.
    """
    for cap in ordered_caps:
        if cap.blocks:
            return cap.action_kind
    for cap in ordered_caps:
        if cap.asks:
            return cap.action_kind
    return PROCEED


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
    band, limited = band_for(
        overall,
        confidence,
        min((pillar.confidence for pillar in pillars), default=None),
    )
    return ReadinessScore(
        schema_version=SCHEMA_VERSION,
        overall=overall,
        weighted_average=weighted_average,
        band=band,
        status="BLOCKED" if any(cap.blocks for cap in ordered_caps) else "OK",
        recommended_action=recommended_action(ordered_caps),
        confidence=round(confidence, 2),
        band_limited_by_confidence=limited,
        weights=dict(sorted(weights.items())),
        pillars=tuple(sorted(pillars, key=lambda pillar: pillar.name)),
        caps=ordered_caps,
        knobs=tuple(sorted(knobs, key=lambda knob: knob.name)),
        gaps=collect_gaps(pillars, knobs, ordered_caps, overall),
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
        headline += "  (PAID RUN BLOCKED)"
    lines.append(f"TRAIGENT OPTIMIZATION READINESS{' ' * 8}{headline}")
    lines.append("")
    for pillar in score.pillars:
        colour = band_color(palette, pillar.score)
        headline_suffix = f"  {pillar.score}/100"
        if pillar.confidence < MIN_CONFIDENCE_FOR_TOP_BANDS:
            # A renormalized score over half the checks is not the same claim as
            # a full one, and "(partly checked)" proved too quiet to carry that
            # next to a full bar and a round number: an uncalibrated evaluator
            # read as 100/100 with two of four checks observed. The count is
            # named instead, because "2 of 4 checks" is a fact the reader can
            # act on where an internal weight ratio is not.
            measured = sum(1 for sub in pillar.subscores if sub.measured)
            headline_suffix += (
                f"  {palette.dim}({measured} of {len(pillar.subscores)} checks"
                f" measured){palette.reset}"
            )
        lines.append(
            f"  {pillar.name.upper():<11} {colour}{bar(pillar.score, unicode_ok=unicode_ok)}"
            f"{palette.reset}{headline_suffix}"
        )
        # Several checks in a pillar can rest on one fact, and printing it once
        # per check reads as several findings. An agent with no config-space
        # document produced three rows all saying "no knobs declared" - one
        # fact, three chances for a reader to think two of them are something
        # else they must also fix.
        distinct = {sub.evidence for sub in pillar.subscores}
        if not pillar.subscores:
            # A pillar can carry no checks at all - `aggregate` accepts one and
            # several callers build them. The old loop was a no-op there; the
            # column-width calculation below is not, and `max()` of nothing
            # raises. Rendering a card must not be able to fail on a shape the
            # scorer itself produces.
            pass
        elif len(pillar.subscores) > 1 and len(distinct) == 1:
            # One fact, so one line. Naming the checks here would join three
            # labels into a sentence longer than the finding, which is how the
            # first attempt at this made an unreadable pillar out of a readable
            # one - the evidence IS the finding when nothing distinguishes them.
            worst = min(pillar.subscores, key=lambda sub: (sub.measured, sub.value))
            lines.append(f"    {marker(worst, unicode_ok)} {distinct.pop()}")
        else:
            # Width from the labels actually present, not a constant: these are
            # phrases now, and a fixed column either wraps the long ones or
            # pads every short one to the width of the longest name in the file.
            width = max(len(display_name(sub.name)) for sub in pillar.subscores)
            for sub in pillar.subscores:
                label = display_name(sub.name)
                lines.append(
                    f"    {marker(sub, unicode_ok)} {label:<{width}}  {sub.evidence}"
                )
        lines.append("")
    if score.caps:
        for cap in score.caps:
            # The label has to carry the difference the status already makes,
            # or the card contradicts its own JSON: an advisory ceiling reported
            # `status: OK` while this line printed BLOCKED next to it.
            #
            # "Cap" is the word the code and the schema use; it is not a word a
            # first-time reader knows. What they need is the consequence, so the
            # line says it: something to fix before paying, or a limit on the
            # number - with the limit shown, since "why is this 89" is the
            # question it answers.
            #
            # The number has to be conditioned too, not only the kind of label.
            # A ceiling that is not the operative one is not what limits this
            # score, and printing it flat states a number the card cannot
            # reconcile: the reader is shown 89 beside a 25, with nothing on the
            # card saying the lowest ceiling wins. The subjunctive is the whole
            # fix - it says the ceiling is real without claiming it applies now.
            if cap.blocks:
                label = f"{palette.bad}FIX BEFORE PAID RUN{palette.reset}"
            elif binds(cap, score.overall):
                label = f"{palette.warn}LIMITED TO {cap.ceiling}{palette.reset}"
            else:
                label = f"{palette.warn}WOULD LIMIT TO {cap.ceiling}{palette.reset}"
            lines.append(f"  {label} {cap.reason}")
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
        f"  {palette.dim}Local pre-run planning estimate, not a probability or "
        f"measured optimization result.{palette.reset}"
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
            + ("  ·  status: PAID RUN BLOCKED" if score.status == "BLOCKED" else ""),
            "",
            f"Weighted average before caps: {score.weighted_average}/100. "
            f"Evidence coverage: {score.confidence:.0%}.",
            "",
            "This is a first-pass estimate computed from local evidence only, "
            "before any optimization has run. It is an ordinal planning aid, not "
            "a calibrated probability. Weights are a judgment call and are listed "
            "below so the number stays auditable.",
            "",
            "| Pillar | Score | Weight | Evidence coverage |",
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
    # Split by what the cap does, not merely listed together: an advisory
    # ceiling under "What is blocking a trustworthy result" is false about the
    # only thing the heading asserts, and this report is the durable artifact -
    # it outlives the terminal the card was printed to.
    blocking = [cap for cap in score.caps if cap.blocks]
    limiting = [cap for cap in score.caps if not cap.blocks]

    def cap_line(cap: Cap) -> str:
        # Conditioned for the same reason the card's label is: a ceiling that is
        # not the operative one caps nothing, and stating it flat invites the
        # reader to take it as the score's limit.
        effect = (
            f"caps the score at {cap.ceiling}"
            if binds(cap, score.overall)
            else f"would cap the score at {cap.ceiling}"
        )
        # The remedy goes in the durable report, not on the card: this file
        # already names each cap by its internal condition id, and the card
        # deliberately does not - the guide keeps that vocabulary out of
        # user-facing lines. Both are machine-readable artifacts here.
        return (
            f"- **{cap.condition}** ({effect}, fix: `{cap.action_kind}`): {cap.reason}"
        )

    if blocking:
        lines.extend(["## What is blocking a trustworthy result", ""])
        lines.extend(cap_line(cap) for cap in blocking)
        lines.append("")
    if limiting:
        lines.extend(["## What limits how high this can score", ""])
        lines.extend(cap_line(cap) for cap in limiting)
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


def evaluator_shape_from_preflight(
    records: Sequence[dict[str, Any]],
) -> tuple[bool, bool | None]:
    """Read preflight's static `evaluator-shape` check, if one ran.

    Returns `(present, parses)`. `present` is a measured fact - preflight
    found a file at the path it was given - not a declaration; `parses` is
    `None` when no such check ran (not "it failed"), `True` when the file
    parsed as valid Python, `False` when it did not. preflight never imports
    or executes the file to produce this (`check_evaluator`, `ast.parse`
    only), so this stays inside the credential-free opening gate.
    """
    shape = _metrics_by_check(records).get("evaluator-shape")
    if not shape:
        return False, None
    return bool(shape.get("exists")), shape.get("parses")


class PreflightInputError(ValueError):
    """Supplied preflight JSON cannot be scored honestly.

    A distinct type so the CLI can refuse bad scoring input (exit 2 with the
    message) while a genuine bug inside the fact adapters still surfaces as a
    traceback instead of being misreported as unreadable input.
    """


class ConfigSpaceInputError(ValueError):
    """A config-space document the scorer cannot read.

    The sibling of `PreflightInputError` for `--config-space`. Preflight and
    calibration JSON are machine-written, but this document is hand-authorable -
    a real agent's wrapper is adapted, not copied verbatim - so a typo in it is
    a reachable path, not a bug. It gets the same treatment: refuse with a
    message naming the field, never score a document we cannot read.
    """


class RowReviewInputError(ValueError):
    """A row review the scorer cannot read, or may not accept as one.

    The sibling of `ConfigSpaceInputError` for `--row-review`, and hand-authored
    in the same way. It refuses rather than degrades for a reason particular to
    this input: every other scoring input is a measurement, and this one is an
    opinion that is allowed to lower a score. An opinion that arrives malformed,
    over-claiming its coverage, or attributed to anyone but the assistant is
    exactly the input that must not be quietly repaired into a usable one.
    """


def row_review_from_document(document: Any, facts: DatasetFacts) -> RowReview:
    """Read the assistant's row-by-row read, refusing one it cannot stand behind.

    Checked against `facts` rather than taken at its word, because two of this
    review's rules are only worth stating if they can be verified:

    * It reviews rows the user brought and skips the ones this run generated.
      A generated row is capped by the synthetic ceiling regardless, most of it
      will be fine, and a model re-judging output it just wrote is marking its
      own homework. So `synthesised` is not an accepted origin at all, and the
      count of rows left unreviewed for that reason is read from preflight -
      derived, not declared, so the review cannot claim a skip it did not make.
    * It is the assistant's judgement and never the user's ground truth. The
      author is a required field with one accepted value, so a file asserting
      the user said something is refused here instead of being scored as if
      they had. Their answer arrives through the approval gate, not this file.

    * It may say which rows the run actually reads, and is checked when it
      does. `in_run` is optional because at the opening gate on a large dataset
      the subset has not been drawn; it is all-or-nothing across the entries
      because a half-answered file would let the unanswered rows read as
      "outside the run", which understates the finding in the direction that
      favours proceeding.

    A per-row sentence is required for the same reason: it is what makes a
    verdict inspectable, and what stops a blanket "all fine" being emitted by
    something that never read a row.
    """
    if not isinstance(document, dict):
        raise RowReviewInputError(
            "row review must be a JSON object with 'reviewer' and 'rows'"
        )
    reviewer = document.get("reviewer")
    if reviewer != ROW_REVIEW_REVIEWER:
        raise RowReviewInputError(
            f"row review declares reviewer {reviewer!r}; this input records the "
            f"coding assistant's own read, so it must say {ROW_REVIEW_REVIEWER!r}. "
            "A user's verdict is not this file's type - it arrives as an answer "
            "to the approval-gated question, and is never written here on their "
            "behalf"
        )
    rows = document.get("rows")
    if not isinstance(rows, list) or not rows:
        raise RowReviewInputError(
            "row review carries no 'rows' list; omit --row-review rather than "
            "supplying an empty review, which would read as 'nothing was wrong'"
        )

    seen: set[str] = set()
    counts = {verdict: 0 for verdict in ROW_REVIEW_VERDICTS}
    origins = {origin: 0 for origin in ROW_REVIEW_ORIGINS}
    # Three states, not two. Every entry says whether the run reads that row,
    # or none of them does; a review where some entries answer and some do not
    # is refused rather than read as "the silent ones are outside", because
    # that reading is the one that would understate the finding.
    in_run_declared: set[bool] = set()
    unsound_in_run = 0
    for index, entry in enumerate(rows):
        where = f"row review entry {index}"
        if not isinstance(entry, dict):
            raise RowReviewInputError(f"{where} is not an object")
        row_id = entry.get("id")
        if not isinstance(row_id, str) or not row_id.strip():
            raise RowReviewInputError(
                f"{where} has no 'id'; a verdict nobody can trace to a row "
                "cannot be put to the user as a question about that row"
            )
        if row_id in seen:
            raise RowReviewInputError(
                f"{where} repeats id {row_id!r}; one row carries one verdict, "
                "and a repeat inflates the share the ceiling is decided on"
            )
        seen.add(row_id)
        verdict = entry.get("verdict")
        if verdict not in ROW_REVIEW_VERDICTS:
            raise RowReviewInputError(
                f"{where} has verdict {verdict!r}; expected one of "
                f"{', '.join(ROW_REVIEW_VERDICTS)}"
            )
        origin = entry.get("origin")
        if origin == "synthesised":
            raise RowReviewInputError(
                f"{where} reviews a generated row ({row_id!r}). This check reads "
                "the rows the user brought; rows this run generated are already "
                "bounded by the synthetic ceiling, and a model re-judging its "
                "own output is not evidence"
            )
        if origin not in ROW_REVIEW_ORIGINS:
            raise RowReviewInputError(
                f"{where} has origin {origin!r}; expected one of "
                f"{', '.join(ROW_REVIEW_ORIGINS)} - the provenance class "
                "preflight assigned that row"
            )
        note = entry.get("note")
        if not isinstance(note, str) or not note.strip():
            raise RowReviewInputError(
                f"{where} carries no 'note'; each verdict states in one sentence "
                "why, which is what makes it a read rather than a tally"
            )
        in_run = entry.get("in_run")
        if in_run is not None and not isinstance(in_run, bool):
            raise RowReviewInputError(
                f"{where} has in_run {in_run!r}; it says whether this run reads "
                "that row, so it is true or false or absent - and absent means "
                "the rows have not been drawn yet, never 'no'"
            )
        in_run_declared.add(in_run is not None)
        counts[verdict] += 1
        origins[origin] += 1
        if verdict == "no" and in_run:
            unsound_in_run += 1

    if len(in_run_declared) > 1:
        raise RowReviewInputError(
            "row review answers 'in_run' for some rows and not others; the "
            "card reports how many flagged rows the run actually reads, and a "
            "partial answer would count the unanswered ones as outside it"
        )

    for origin, available in (
        ("collected", facts.collected_rows),
        ("undeclared", facts.undeclared_rows),
    ):
        if origins[origin] > available:
            raise RowReviewInputError(
                f"row review reports {origins[origin]} {origin} rows read, but "
                f"preflight counted {available}; the review and the dataset it "
                "claims to describe are not the same dataset"
            )

    # Checked against the split for the same reason the origin counts are
    # checked against preflight: this is the one input that lowers a score on
    # nothing but its own word, so a coverage claim it makes about the run's
    # own rows is verified where a fact exists to verify it against.
    declared = run_rows(facts)
    marked_in_run = sum(1 for entry in rows if entry.get("in_run"))
    if declared is not None and marked_in_run > declared:
        raise RowReviewInputError(
            f"row review marks {marked_in_run} rows as ones this run reads, "
            f"but the declared split holds {declared}; a review cannot place "
            "more rows in the run than the run has"
        )

    return RowReview(
        supplied=True,
        reviewed=len(rows),
        unsound=counts["no"],
        unsure=counts["unsure"],
        reviewed_collected=origins["collected"],
        reviewed_undeclared=origins["undeclared"],
        unsound_in_run=unsound_in_run if in_run_declared == {True} else None,
    )


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
    tuning_metrics = metrics.get("dataset-tuning-size", {})
    holdout_metrics = metrics.get("dataset-holdout-resolution", {})
    split_metrics = metrics.get("dataset-split", {})
    split_kind = split_metrics.get("kind")
    # A declared split whose per-split labelled counts are missing can only be
    # scored with the aggregate clamp, which demonstrably fails to lower the
    # score for a split whose labels sit entirely on one side. Refuse rather
    # than under-clamp - the same call the malformed_rows guard above makes.
    #
    # "A split was declared" is read from two independent witnesses because
    # either one alone has a blind spot. The metric records are what the scorer
    # consumes, but a record that is absent altogether announces nothing - so a
    # JSON carrying only `dataset-tuning-size` would slip past a record-only
    # test into the no-split branch with the holdout's labelled count silently
    # unknown. `dataset-split == PASS` covers that: every preflight version that
    # found a disjoint tuning/holdout split emits it, including versions that
    # emitted the two size records with no metrics at all. FAIL is deliberately
    # *not* a witness - an overlapping split emits no split metric records by
    # construction, so treating FAIL as a declared split would make every
    # overlapping dataset start refusing instead of scoring through the no-split
    # branch under its overlap cap. WARN means no split was found at all.
    declares_tuning_only = split_kind == "tuning-only"
    declares_tuning_and_holdout = "dataset-holdout-resolution" in metrics or (
        statuses.get("dataset-split") == "PASS" and not declares_tuning_only
    )
    if declares_tuning_only:

        def _usable_count(value: Any) -> bool:
            return isinstance(value, int) and not isinstance(value, bool) and value >= 0

        unusable = [
            name
            for name, source in (
                ("tuning_rows", tuning_metrics),
                ("tuning_labelled_rows", tuning_metrics),
            )
            if not _usable_count(source.get(name))
        ]
        if unusable or "dataset-holdout-resolution" in metrics:
            problem = "/".join(unusable) or "holdout_rows"
            raise PreflightInputError(
                "tuning-only split metrics carry an unusable "
                f"{problem} count - re-run preflight.py --json from the same "
                "version as this script"
            )
        aggregate_labelled = provenance.get("labelled_rows")
        tuning_labelled = tuning_metrics["tuning_labelled_rows"]
        if (
            aggregate_labelled is not None
            and _usable_count(aggregate_labelled)
            and tuning_labelled > aggregate_labelled
        ):
            raise PreflightInputError(
                f"tuning-only split metrics report {tuning_labelled} labelled rows, "
                f"more than the {aggregate_labelled} the dataset declares in total - "
                "re-run preflight.py --json from the same version as this script"
            )
    elif declares_tuning_and_holdout:
        # Presence is not enough: score_dataset branches on value, so a key
        # carrying JSON null reaches the aggregate fallback exactly as an absent
        # key would. Demand a whole non-negative number for all four counts
        # (bool is an int in Python and is not a row count; a negative count is
        # not one either - it arithmetically reaches the scorer and prints a
        # nonsense band like "-5 comparable examples").
        def _usable_count(value: Any) -> bool:
            return isinstance(value, int) and not isinstance(value, bool) and value >= 0

        unusable = [
            name
            for name, source in (
                ("tuning_rows", tuning_metrics),
                ("tuning_labelled_rows", tuning_metrics),
                ("holdout_rows", holdout_metrics),
                ("holdout_labelled_rows", holdout_metrics),
            )
            if not _usable_count(source.get(name))
        ]
        if unusable:
            raise PreflightInputError(
                "declared split metrics carry no usable "
                f"{'/'.join(unusable)} count - a declared tuning/held-out split "
                "can only be scored from all four per-split row counts, so this "
                "preflight JSON predates the current preflight.py or was "
                "edited; re-run preflight.py --json from the same version as "
                "this script"
            )
        # #69: the same guard, applied to the aggregates and to the coherence
        # between the two. Checking type and sign on four counts while waving the
        # aggregates through invites a reader to trust numbers nothing validated,
        # and its own rationale - a negative count "arithmetically reaches the
        # scorer and prints a nonsense band" - applies verbatim to them.
        for name, value in (
            ("rows", provenance.get("rows")),
            ("labelled_rows", provenance.get("labelled_rows")),
        ):
            if value is not None and not _usable_count(value):
                raise PreflightInputError(
                    f"dataset-provenance carries no usable {name} count - row "
                    "counts are whole and non-negative, so this preflight JSON "
                    "was edited or predates the current preflight.py; re-run "
                    "preflight.py --json from the same version as this script"
                )
        # No row is counted twice: `tune_names` and `holdout_names` are disjoint
        # and a row carries one split tag, so the two split-labelled counts
        # cannot legitimately exceed the aggregate. A shape that says otherwise
        # (100 split labels against 1 aggregate label) was accepted and scored
        # 22.0 power beside "1/100 rows carry an expected output".
        aggregate_labelled = provenance.get("labelled_rows")
        split_labelled = (
            tuning_metrics.get("tuning_labelled_rows"),
            holdout_metrics.get("holdout_labelled_rows"),
        )
        if aggregate_labelled is not None and all(
            _usable_count(count) for count in split_labelled
        ):
            if sum(split_labelled) > aggregate_labelled:
                raise PreflightInputError(
                    f"declared split metrics report {sum(split_labelled)} labelled "
                    f"rows across tuning and held-out, more than the "
                    f"{aggregate_labelled} the dataset declares in total - the "
                    "splits are disjoint, so this cannot describe one dataset; "
                    "re-run preflight.py --json from the same version as this "
                    "script"
                )
    return DatasetFacts(
        exists=True,
        rows=provenance.get("rows"),
        labelled_rows=provenance.get("labelled_rows"),
        tuning_rows=tuning_metrics.get("tuning_rows"),
        holdout_rows=holdout_metrics.get("holdout_rows"),
        tuning_labelled_rows=tuning_metrics.get("tuning_labelled_rows"),
        holdout_labelled_rows=holdout_metrics.get("holdout_labelled_rows"),
        difficulty_bands=tuple(difficulty.get("bands", ())),
        difficulty_tagged_rows=difficulty.get("tagged_rows"),
        duplicate_status=statuses.get("dataset-duplicates"),
        near_duplicate_status=statuses.get("dataset-near-duplicates"),
        ceiling_risk="dataset-ceiling-risk" in statuses,
        split_overlap=statuses.get("dataset-split") == "FAIL",
        integrity_failed=structurally_failed or statuses.get("dataset-ids") == "FAIL",
        synthetic=bool(provenance.get("synthetic")),
        generated_outputs=bool(provenance.get("generated_outputs")),
        placeholder_rows=_row_count(
            metrics.get("dataset-output-placeholders", {}).get("placeholder_rows"),
            "placeholder_rows",
        ),
        collected_rows=_row_count(provenance.get("collected_rows"), "collected_rows"),
        synthesised_rows=_row_count(
            provenance.get("synthesised_rows"), "synthesised_rows"
        ),
        undeclared_rows=_row_count(
            provenance.get("undeclared_rows"), "undeclared_rows"
        ),
        answerable_rows=_row_count(
            provenance.get("answerable_rows"), "answerable_rows"
        ),
        generated_answer_rows=_row_count(
            provenance.get("generated_answer_rows"), "generated_answer_rows"
        ),
        sources=tuple(provenance.get("sources", ())),
        unrecognised_sources=tuple(provenance.get("unrecognised_sources", ())),
    )


def evaluation_facts_from_calibration(
    payload: dict[str, Any] | None,
    *,
    method: str | None = None,
    task_kind: str | None = None,
    evaluator_present: bool = False,
    evaluator_parses: bool | None = None,
) -> EvaluationFacts:
    """Normalize both shapes `calibrate_evaluator` emits into one fact set.

    `evaluator_present`/`evaluator_parses` come from preflight's static
    `evaluator-shape` check (`evaluator_shape_from_preflight`, below), not
    from a declaration - a file preflight found on disk, whether or not this
    run could honestly declare a method for it. Without either signal,
    presence still falls back to "a method was declared", the only fact this
    function used to have (traigent-first-run#133).
    """
    if payload is None:
        return EvaluationFacts(
            present=method is not None or evaluator_present,
            method=method,
            task_kind=task_kind,
            parses=evaluator_parses,
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
        # A payload arrived, whatever it turned out to contain. Reaching this
        # line is the proof - `payload is None` returned above.
        calibration_supplied=True,
        checks=tuple(checks),
        probe_scores=tuple(probes),
        timed_out=bool(payload.get("timed_out")),
        parses=evaluator_parses,
    )


# ---------------------------------------------------------------------------
# The config-space document schema
#
# One declaration, `CONFIG_SPACE_FIELDS`, is the single source of truth for what
# this document may contain: the field's name, the type it accepts, and - through
# its reader - the domain of every value inside it. `agent_facts_from_config_space`
# reads nothing else, and `tests/test_skill_package.py` regenerates the schema
# table in references/run-safety.md from this tuple and fails when the two
# disagree.
#
# This shape exists because the previous one failed repeatedly in the same two
# ways, over three review cycles and nineteen findings. Validation was a sequence
# of independent per-field checks and the documented table was a separate
# hand-written artifact, so each round closed the field that had just been
# reported and the next round arrived through the field nobody had written a
# check for - a knob whose value was a bare scalar, then a falsey one, then a
# `wired` name matching no knob, then a candidate list with nothing in it, then a
# candidate that was a dict. Every one of them was silently narrowed and then
# scored, under an evidence line that was false.
#
# The question "is field X validated?" is therefore no longer answerable one
# field at a time. A field is declared here and validated, or it is not a field:
# an undeclared key is ignored whole, never half-read. Two rules hold across
# every reader, in both directions:
#
# * **Never coerce a value the field's documented type does not admit.**
#   `document.get(field) or {}` reads `[]`, `null`, `0` and `""` as "absent", so
#   presence is tested with `in` and the type is checked on what was written.
# * **Never refuse a value the documented type does admit.** JSON has one number
#   type and several ways to spell one value, so a reader judges the *value*:
#   `12.0` is the trial budget `12`, and `"5"` is the bound `5`. Turning a
#   document that scores into a hard exit-2 failure is a worse outcome than the
#   silence being replaced.
# ---------------------------------------------------------------------------


def _scalar_candidate(where: str, value: Any) -> Any:
    """One candidate value of one knob, or a refusal naming where it sits.

    Every candidate is deduplicated, compared and counted, so the domain is the
    hashable JSON scalars. The two shapes outside it both used to survive the
    per-field checks, because those checked the *list* and never its contents:

    * A dict or a list reached `dict.fromkeys(values)` as an unhashable key and
      raised a bare `TypeError` traceback - not the named exit-2 refusal this
      document promises for anything it cannot read.
    * A non-finite float is worse than unreadable, because it scores.
      `temperature: [0.0, Infinity]` read as a 72 that cleared every cap and
      `[NaN, NaN]` as a 59, and neither describes any set of runs: the span
      against which the sweep is measured is infinite in one case and undefined
      in the other.
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        # Deliberately not routed through float(): a large integer candidate is
        # a legal JSON number and float() raises OverflowError on it.
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, float):
        raise ConfigSpaceInputError(
            f"config-space {where} is {value!r}, which is not a candidate "
            "value: a knob is scored against the span its values cover, and "
            "an infinite or undefined span is not a sweep"
        )
    raise ConfigSpaceInputError(
        f"config-space {where} is {type(value).__name__}; a candidate value "
        "must be a string, number, boolean, or null, because the scorer "
        "compares and counts candidates"
    )


def _read_knob_space(field: str, value: Any) -> dict[str, list[Any]]:
    """`knobs` / `configuration_space`: knob name to its candidate values."""
    if not isinstance(value, dict):
        raise ConfigSpaceInputError(
            f"config-space '{field}' must be an object mapping each knob "
            f"name to its list of candidate values, not {type(value).__name__}"
        )
    space: dict[str, list[Any]] = {}
    for knob, candidates in value.items():
        # A knob written as a bare scalar instead of a list of candidates used
        # to be dropped, which is the worst outcome available: the knob leaves
        # the space, the score frequently goes *up* because the dropped knob
        # was the one not varying, and the cap reason printed afterwards
        # describes a space the author never wrote.
        if not isinstance(candidates, (list, tuple)):
            raise ConfigSpaceInputError(
                f"config-space '{field}' entries must each be a list of "
                f"candidate values: '{knob}' is {type(candidates).__name__}"
            )
        # An empty list is that same silent narrowing in its purest form: it
        # declares a dimension with nothing to try. Scored, it printed "0 of 1
        # wired knobs actually vary; 1 combinations" - a knob count the
        # document contradicts beside a combination count of a space that has
        # no configurations at all.
        if not candidates:
            raise ConfigSpaceInputError(
                f"config-space {field}['{knob}'] lists no candidate values; a "
                "knob with nothing to try is not a search dimension - remove "
                "it, or give it the values the search should try"
            )
        space[knob] = [
            _scalar_candidate(f"{field}['{knob}'][{index}]", candidate)
            for index, candidate in enumerate(candidates)
        ]
    return space


def _read_name_list(field: str, value: Any) -> tuple[str, ...]:
    """`wired`: the knob names the agent call actually consumes.

    This reader only parses the field; what an ABSENT `wired` means is
    `score_agent`'s call, not this function's, and the two must not restate
    each other (traigent-first-run#78). Producers should always emit the list -
    stating what the agent consumes is the document's purpose. A present one
    that is not a list of names is a claim about the search space that cannot
    be read: a non-string entry matches no knob and would silently shrink the
    considered set instead.
    """
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(name, str) for name in value
    ):
        raise ConfigSpaceInputError(
            f"config-space '{field}' must be a list of knob names, not {value!r}"
        )
    return tuple(value)


def _read_edge(knob: str, edge: str, value: Any) -> float:
    """One end of one `bounds` pair.

    A bound sets the noise floor and the span every numeric knob is scored
    against, so a non-number here silently decides whether that knob counts as
    varying at all. bool is an int in Python and is not a bound.

    A numeric *string* is accepted deliberately: this adapter has always read
    bounds through `float()`, so `{"low": "1", "high": "5"}` scored before this
    guard existed, and refusing it now would turn a working document into a
    hard exit-2 failure.

    `float()` also parses "inf" and "nan", which are not ranges: an infinite
    span makes the 2% noise floor infinite and a NaN span makes every
    comparison false, so either one collapses a knob that genuinely sweeps
    1 -> 50 into "nothing to search".
    """
    if not isinstance(value, bool) and isinstance(value, (int, float, str)):
        try:
            number = float(value)
        except (ValueError, OverflowError):
            number = math.nan
        if math.isfinite(number):
            return number
    raise ConfigSpaceInputError(
        f"config-space bounds['{knob}']['{edge}'] must be a finite number, "
        f"not {value!r}"
    )


def _read_bounds(field: str, value: Any) -> dict[str, dict[str, float]]:
    """`bounds`: a per-knob replacement for the scorer's canonical range."""
    if not isinstance(value, dict):
        raise ConfigSpaceInputError(
            f"config-space '{field}' must be an object mapping a knob name to "
            f"a low/high pair, not {type(value).__name__}"
        )
    read: dict[str, dict[str, float]] = {}
    for knob, spec in sorted(value.items()):
        if not isinstance(spec, dict):
            raise ConfigSpaceInputError(
                f"config-space bounds['{knob}'] must be an object with 'low' "
                f"and 'high', not {type(spec).__name__}"
            )
        # A half-written bound was dropped silently, so the knob was scored
        # against the canonical range - or against no range at all - rather
        # than the one the author declared. That flips whether the knob counts
        # as varying, so it is refused for the same reason a scalar knob is.
        missing = [edge for edge in ("low", "high") if edge not in spec]
        if missing:
            raise ConfigSpaceInputError(
                f"config-space bounds['{knob}'] must carry both 'low' and "
                f"'high'; {' and '.join(repr(edge) for edge in missing)} missing"
            )
        low = _read_edge(knob, "low", spec["low"])
        high = _read_edge(knob, "high", spec["high"])
        # The edges were checked one at a time and never as the pair they are.
        # Both failures scored: an inverted pair makes every span negative, and
        # a zero-width pair divides the span by zero *and* zeroes the noise
        # floor, so two values a hair apart read as a genuine sweep and the
        # `agent-no-varying-knobs` cap cleared on a range that admits one value.
        if not low < high:
            raise ConfigSpaceInputError(
                f"config-space bounds['{knob}'] must have 'low' below 'high', "
                f"not low={low:g} and high={high:g}: a knob is scored against "
                "the width of this range, and this one has none"
            )
        # Ordered finite edges are still not a usable range: both harms the
        # checks above close are reachable one step outside them, through the
        # width the edges were never checked as.
        #
        # * Overflow. `{"low": -1e308, "high": 1e308}` is two finite numbers
        #   whose difference is `inf`, so the noise floor is infinite and a knob
        #   genuinely sweeping 1 -> 50 collapses to "nothing to search" - the
        #   verbatim harm `_read_edge` refuses the *spelling* "inf" to prevent.
        # * Underflow. `{"low": 0.0, "high": 5e-324}` has `low < high` and a
        #   width so small that `width * DEFAULT_NOISE_FRACTION` underflows to
        #   0.0, so two practically identical values read as a genuine sweep and
        #   clear `agent-no-varying-knobs` - the verbatim harm the `low == high`
        #   refusal above cites. For a knob whose floor is a fixed constant the
        #   same width instead makes the span ratio it divides infinite, which
        #   is no more measurable, so the default fraction is what decides.
        width = high - low
        # Under the canonical name, because that is the name `score_agent` will
        # look the floor up under: a check that reads a spelling the scorer has
        # already renamed is answering about a knob that will not exist.
        floor = noise_floor(KNOB_ALIASES.get(knob, knob), low, high)
        if (
            not math.isfinite(width)
            or width * DEFAULT_NOISE_FRACTION <= 0.0
            or floor <= 0.0
        ):
            raise ConfigSpaceInputError(
                f"config-space bounds['{knob}'] spans {low:g} to {high:g}, "
                f"whose width is {width:g} and whose noise floor is {floor:g}: "
                "a knob is scored against that width and two values within that"
                " floor are one configuration, so a width this scorer cannot "
                "measure is not a range it can search"
            )
        read[knob] = {"low": low, "high": high}
    return read


def _read_trial_budget(field: str, value: Any) -> int:
    """`max_trials`: how many configurations the search may actually try.

    JSON has a single number type, so an integral budget arrives as `12` from
    one writer and `12.0` from another; both name the same integer and both
    scored before this guard existed, so the check is on the value. A Python
    `int` is judged as an int and never converted - `float(10**309)` raises
    OverflowError, which is how a legal positive JSON integer turned into a
    traceback on a document the parent scored.
    """
    if not isinstance(value, bool):
        if isinstance(value, int):
            if value >= 1:
                return value
        elif isinstance(value, float):
            if math.isfinite(value) and value.is_integer() and value >= 1:
                return int(value)
    raise ConfigSpaceInputError(
        f"config-space '{field}' must be a positive integer, not {value!r}"
    )


def _read_agent_type(field: str, value: Any) -> str:
    """`agent_type`: which high-impact catalog coverage is scored against.

    An unrecognized *string* stays legal: it names an agent this scorer has no
    catalog for, which is a real situation and not a typo the scorer can
    detect. Coverage then goes unmeasured, and because `combine` renormalizes
    over the measured sub-scores that *raises* the pillar's score while
    dropping its confidence - the "agent type not recognized" gap line is what
    carries the news, not the number. A non-string cannot even be looked up.
    """
    if not isinstance(value, str):
        raise ConfigSpaceInputError(
            f"config-space '{field}' must be a string naming the agent type "
            f"('general', 'rag', or 'code_gen'), not {value!r}"
        )
    return value


@dataclass(frozen=True)
class ConfigSpaceField:
    """One field of the config-space document, and how it is read.

    `type_label` and `requirement` are the documented schema: the table in
    references/run-safety.md is checked against them, so a field cannot be
    added, retyped or removed in one place only.
    """

    name: str
    type_label: str
    requirement: str
    read: Any


CONFIG_SPACE_FIELDS: tuple[ConfigSpaceField, ...] = (
    ConfigSpaceField(
        "knobs",
        "object: knob name to a non-empty list of scalar candidate values",
        "one of the two",
        _read_knob_space,
    ),
    ConfigSpaceField(
        "configuration_space",
        "same shape",
        "accepted alias",
        _read_knob_space,
    ),
    ConfigSpaceField(
        "agent_type",
        '`"general"`, `"rag"`, or `"code_gen"`',
        "no",
        _read_agent_type,
    ),
    ConfigSpaceField(
        "max_trials",
        "positive integer",
        "no",
        _read_trial_budget,
    ),
    ConfigSpaceField(
        "wired",
        "list of knob names",
        "**yes - always emit it**",
        _read_name_list,
    ),
    ConfigSpaceField(
        "bounds",
        'object: knob name to `{"low": number, "high": number}`, low below high',
        "no",
        _read_bounds,
    ),
)

# The spellings of the search space itself, in preference order - derived from
# the declaration rather than repeated, so adding a spelling is one edit and the
# preferred one is whichever the table lists first.
CONFIG_SPACE_SPACE_KEYS = tuple(
    spec.name for spec in CONFIG_SPACE_FIELDS if spec.read is _read_knob_space
)


def candidate_domain(values: Iterable[Any]) -> list[tuple[bool, Any]]:
    """A candidate list as a key that tells `True` from `1`.

    `True == 1` and `False == 0` in Python, so comparing two candidate lists
    directly read `[true, false]` and `[1, 0]` as one domain: two spellings of
    one dimension declared over *different* values were merged silently, which
    is the narrowing the refusal below exists to stop. `dict.fromkeys` collapsed
    the pair the same way, before any comparison ran.

    The key pairs each value with whether it is a bool rather than using its
    `repr`, because `1` and `1.0` genuinely are one candidate everywhere else
    here - `knob_variation` dedupes by value, and the combination count was
    moved off `repr` for exactly that reason. Keying on `repr` would refuse
    `[1]` against `[1.0]`, a document that scores today.
    """
    return list(dict.fromkeys((isinstance(value, bool), value) for value in values))


def canonical_alias_names(facts: AgentFacts) -> AgentFacts:
    """Collapse alias spellings onto one dimension before anything counts them.

    Doing this inside the coverage sub-score alone was too late. Knob-count,
    variation and the combination count had already run, and each of them had
    counted `prompt_policy` and `prompt_style` as two independent dimensions:
    declaring both over the same values scored the agent pillar 95 with "5 of 5
    wired knobs" and 108 combinations, against 93, "4 of 4" and 36 for the
    single spelling. One conceptual dimension earned two dimensions' credit and
    tripled the reported size of the space.

    Two spellings of one dimension with *different* candidate lists is not a
    space this can silently pick a winner from, so it is refused.
    """
    names = (*facts.knobs, *(facts.wired or ()), *facts.bounds)
    if not any(name in KNOB_ALIASES for name in names):
        return facts

    def _canonical(name: str) -> str:
        return KNOB_ALIASES.get(name, name)

    knobs: dict[str, list[Any]] = {}
    for name, values in facts.knobs.items():
        canonical = _canonical(name)
        held = knobs.get(canonical)
        if held is not None and candidate_domain(held) != candidate_domain(values):
            raise ConfigSpaceInputError(
                f"config-space declares both '{name}' and '{canonical}' over "
                "different candidate values, but they are two spellings of one "
                "search dimension: declare it once, under either name"
            )
        if held is None:
            knobs[canonical] = list(values)

    bounds: dict[str, dict[str, float]] = {}
    for name, spec in facts.bounds.items():
        canonical = _canonical(name)
        held = bounds.get(canonical)
        if held is not None and held != spec:
            raise ConfigSpaceInputError(
                f"config-space bounds declares both '{name}' and '{canonical}' "
                "with different ranges, but they are two spellings of one "
                "search dimension: declare it once, under either name"
            )
        if held is None:
            bounds[canonical] = dict(spec)

    return AgentFacts(
        agent_type=facts.agent_type,
        max_trials=facts.max_trials,
        knobs=knobs,
        wired=(
            None
            if facts.wired is None
            else tuple(dict.fromkeys(_canonical(name) for name in facts.wired))
        ),
        bounds=bounds,
        # Carried, not defaulted. This function rebuilds the dataclass, so a
        # field it forgets is silently reset - and `score_agent` calls it before
        # reading anything, so the reset would be invisible and total.
        config_space_supplied=facts.config_space_supplied,
    )


def _reject_phantom_names(
    field: str, names: Iterable[str], knobs: dict[str, Any], knobs_key: str
) -> None:
    """Refuse a `wired`/`bounds` name that is no knob of the declared space.

    Both fields address knobs by name, and both are read by intersecting with
    the space, so an unmatched name silently disappears instead of failing.

    It judges the *canonical* name and reports the written one, and it runs
    after `canonical_alias_names`. Running before it made this refuse
    `wired: ["prompt_policy"]` against a space declaring `prompt_style` - a
    spelling this module itself defines as legal - and say the name "is not
    declared", which is false under the module's own semantics: it does match a
    declared knob, through `KNOB_ALIASES`. A validation step that reads names
    the normalization step has not yet collapsed cannot answer the question it
    is asking.
    """
    phantom = sorted(
        {name for name in names if KNOB_ALIASES.get(name, name) not in knobs}
    )
    if phantom:
        detail = ", ".join(f"'{name}'" for name in phantom)
        raise ConfigSpaceInputError(
            f"config-space '{field}' names {detail}, which "
            f"{'is' if len(phantom) == 1 else 'are'} not declared in "
            f"'{knobs_key}': a name that matches no knob would silently shrink "
            "the scored space instead"
        )


def agent_facts_from_config_space(document: dict[str, Any]) -> AgentFacts:
    """Read a config-space document, or refuse it naming the field at fault.

    Every field is read by its own entry in `CONFIG_SPACE_FIELDS` and by
    nothing else, so this function holds only what is genuinely *cross*-field.
    There are three such rules, and they run in this order because a rule that
    reads a name must read the name the scorer will use:

    1. **Which space spelling is read.** `knobs` wins over its
       `configuration_space` alias only when it is non-empty, and `knobs_key`
       names whichever was actually read, so no message points at a key the
       author never wrote.
    2. **Alias spellings are collapsed onto one dimension**
       (`canonical_alias_names`), across `knobs`, `wired` and `bounds` at once.
       Two spellings of one dimension declared over different candidate values,
       or with different ranges, are refused here rather than merged.
    3. **A `wired` or `bounds` name must be a knob of the declared space**
       (`_reject_phantom_names`, applied to each field). Such a name is not a
       narrower space, it is a typo, and it is refused rather than dropped.

    Rule 3 runs on the output of rule 2 and never the other way round: an alias
    spelling is a legal name for a declared knob, so checking names before they
    are collapsed refuses documents this module itself defines as valid.
    """
    if not isinstance(document, dict):
        raise ConfigSpaceInputError(
            "config-space document must be a JSON object with a 'knobs' key, "
            f"not {type(document).__name__}"
        )
    # Presence with `in`, never truthiness: `[]`, `null`, `0` and `""` are
    # malformed values of a field that was written, not absent fields. Every
    # declared field present in the document is read, so a malformed alias
    # cannot hide behind a well-formed preferred key either.
    read = {
        spec.name: spec.read(spec.name, document[spec.name])
        for spec in CONFIG_SPACE_FIELDS
        if spec.name in document
    }
    declared = {key: read[key] for key in CONFIG_SPACE_SPACE_KEYS if key in read}
    if not declared:
        raise ConfigSpaceInputError(
            "config-space document must declare 'knobs' (or its "
            "'configuration_space' alias) as an object mapping each knob name "
            "to its list of candidate values"
        )
    # `knobs` wins only when it is non-empty, so an empty one falls through to
    # the alias. Name whichever key was actually read, or the message points at
    # a key the author did not write. An explicitly empty space is a statement
    # the scorer can read ("no knobs declared"), unlike an absent one.
    knobs_key = next(
        (key for key in CONFIG_SPACE_SPACE_KEYS if declared.get(key)),
        next(iter(declared)),
    )
    knobs = declared[knobs_key]
    # Absent and explicit-empty are DIFFERENT claims: absent says nothing
    # about wiring, `[]` says "none of them". Collapsing them here would
    # erase the distinction before the scorer ever sees it (#78).
    wired = read["wired"] if "wired" in read else None
    bounds = read.get("bounds", {})
    # A misspelled name is a *string*, so the field's own type check lets it
    # through, and `score_agent` then intersects `wired` with the space and
    # drops it - a silent narrowing that raises the score and makes the card
    # assert "1 of 1 wired knobs actually vary" about a document that declared
    # two. A `bounds` name addresses knobs the same way and fails the same way:
    # the declared range never reaches the knob it was meant for, so the knob
    # is scored against the canonical range or on breadth alone, which can flip
    # it from "collapsed" to "varying" and clear the cap on a range the author
    # never declared for it. The template's own fence asserts this before it
    # searches; enforce it here too, because the document is read long after.
    facts = canonical_alias_names(
        AgentFacts(
            agent_type=read.get("agent_type"),
            max_trials=read.get("max_trials"),
            knobs=knobs,
            wired=wired,
            bounds=bounds,
            # Reaching this line is the proof: a document was read.
            config_space_supplied=True,
        )
    )
    # Against the collapsed space, and reporting the spelling the author wrote.
    # An unattested document names nothing, so there is no phantom to reject.
    if wired is not None:
        _reject_phantom_names("wired", wired, facts.knobs, knobs_key)
    _reject_phantom_names("bounds", bounds, facts.knobs, knobs_key)
    return facts


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
        "--row-review",
        help=(
            "the coding assistant's own read of each provided row (path or -): "
            "does this expected output answer this input? Lowers the ceiling "
            "when a material share do not, and never raises the score"
        ),
    )
    parser.add_argument(
        "--evaluator-method",
        choices=tuple(sorted(METHOD_PROFILES)),
        help="declared evaluation method (recorded as declared, not measured)",
    )
    parser.add_argument(
        "--task-kind",
        choices=TASK_KINDS,
        help=(
            "output kind the agent produces; use code for executable source and "
            "code-sql for SQL query output"
        ),
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

    # Refused rather than ignored, and refused before anything else runs: a
    # review supplied without the preflight it describes has no dataset to
    # check its coverage against, so it would be accepted on its own word - and
    # this is the one input allowed to move the score on nothing but its own
    # word. The planner half takes no evidence at all, so a review reaching it
    # is the same mistake spelled differently.
    if args.row_review and not args.preflight:
        print(
            "cannot read scoring input: --row-review needs --preflight - its "
            "coverage is checked against the counted rows, and cannot be taken "
            "on trust",
            file=sys.stderr,
        )
        return 2

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
        # Loaded once and reused for both the dataset and evaluator-shape
        # reads: `--preflight` accepts `-` for stdin, which a second
        # `load_json` call cannot re-read.
        preflight_records = load_json(args.preflight) if args.preflight else []
        dataset_facts = (
            dataset_facts_from_preflight(preflight_records)
            if args.preflight
            else DatasetFacts(exists=False)
        )
        evaluator_present, evaluator_parses = evaluator_shape_from_preflight(
            preflight_records
        )
        evaluation_facts = evaluation_facts_from_calibration(
            load_json(args.calibration) if args.calibration else None,
            method=args.evaluator_method,
            task_kind=args.task_kind,
            evaluator_present=evaluator_present,
            evaluator_parses=evaluator_parses,
        )
        agent_facts = (
            agent_facts_from_config_space(load_json(args.config_space))
            if args.config_space
            else AgentFacts()
        )
        row_review = (
            row_review_from_document(load_json(args.row_review), dataset_facts)
            if args.row_review
            else RowReview()
        )
    except (
        OSError,
        json.JSONDecodeError,
        PreflightInputError,
        ConfigSpaceInputError,
        RowReviewInputError,
    ) as error:
        print(f"cannot read scoring input: {error}", file=sys.stderr)
        return 2

    dataset_pillar, dataset_caps = score_dataset(
        dataset_facts, evaluation_facts.method, row_review
    )
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

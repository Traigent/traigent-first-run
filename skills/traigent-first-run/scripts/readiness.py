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
import difflib
import json
import math
import os
import sys
import traceback
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
# Read each entry as "score BELOW this number is that band" - these are
# exclusive upper bounds, not the score a band requires. The last entry is an
# upper sentinel one past the top of a 0-100 scale, so EXCELLENT is 90-100 and
# nothing needs 101. Written out because the bare tuple invites exactly the
# opposite reading - "you need 101 to be excellent" - and a band table a reader
# has to reverse-engineer is a band table that gets misquoted. The inclusive
# range is on each line so the table can be read without running it, and
# `test_the_documented_bands_match_the_thresholds` holds the glossary's
# customer-facing copy of these ranges to the same numbers.
BAND_THRESHOLDS = (
    (30, "NOT READY"),  # 0-29
    (55, "PARTIAL"),  # 30-54
    (75, "WORKABLE"),  # 55-74
    (90, "STRONG"),  # 75-89
    (101, "EXCELLENT"),  # 90-100; 101 is the sentinel, not a requirement
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

# Names that mean a knob this file already knows, kept ONLY so a document
# using one can be refused by name. Never read to rename anything: this
# replaces `KNOB_ALIASES`, whose renaming had to run before every count, could
# silently reset a field of the dataclass it rebuilt, and forced an ordering
# between itself and the phantom-name check. `_reject_synonym_spellings` owns
# what that table was actually for.
#
# Whoever merges the branch that removes `max_tokens` from every catalog:
# its `test_max_tokens_is_absent_from_every_catalog` reads `MODULE.KNOB_ALIASES`,
# which this branch deletes. It sits outside any conflict region, so the merge
# is clean and the suite errors. Point that row at `KNOB_SYNONYMS`.
KNOB_SYNONYMS: dict[str, str] = {"prompt_policy": "prompt_style"}

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
    # Whether the evidence for this check was THIS RUN'S to supply and was not
    # supplied.
    #
    # `combine` renormalizes over measured sub-scores, which is right when the
    # tool could not look - no catalog exists for this agent type - and wrong
    # when the run simply did not say. Renormalizing there deletes the check
    # from the denominator, so silence pays: omitting `--task-kind` scored the
    # evaluation pillar 100 where declaring a poorly-fitting kind scored it 83,
    # and omitting the probe scores scored 100 where declaring a narrow spread
    # scored 87. Withholding evidence outscored supplying it, on the same
    # project, by up to 5 points overall.
    #
    # A withheld check keeps its full weight in the denominator and earns
    # nothing, so absence can never beat a declaration. It stays `measured=
    # False`, so confidence still reports it as unchecked and the card still
    # marks it - what changes is only that it stops being free.
    withheld: bool = False


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
    # A file was named and no row in it matched the shape preflight read it
    # with. It is not `get-data`: the customer has data, so sending them to
    # collect more is the wrong instruction - and it was the instruction, from
    # the id this state borrowed. It is not `repair-dataset` either, which is
    # the correction this entry carries. `repair-dataset` asserts the file is
    # defective, and on the inputs that actually reach here it usually is not:
    # a fully labelled file whose rows say `question`/`answer` produces this
    # exact state, and re-running preflight with `--input-field question
    # --expected-field answer` scores it 31/PARTIAL with no dataset cap at all.
    # So does a nested schema, a CSV, a JSON array, and YAML. What is true of
    # every one of them is that no row confirmed the shape the run assumed -
    # which is a reason to go and look, not a verdict on the data.
    #
    # `dataset-integrity-fail` keeps `repair-dataset` and that stays right,
    # because it fires only when at least one row DID match: the shape
    # assumption is confirmed by that row, so the rest are genuinely broken.
    # Zero matched rows is the absence of that evidence, and the two conditions
    # already sit exactly on that line.
    "dataset-shape-unrecognised": "read-dataset",
    "dataset-below-measurable-size": "get-data",
    "dataset-coarse-resolution": "get-data",
    "dataset-no-expected-outputs": "label-data",
    "dataset-integrity-fail": "repair-dataset",
    "dataset-tune-holdout-overlap": "resplit-dataset",
    "dataset-fully-synthetic": "connect-real-data",
    "dataset-mostly-synthetic": "connect-real-data",
    "dataset-generated-answer-key": "review-answer-key",
    # The same remedy as the rung above, deliberately: both say a person has to
    # look at the answer key before the number means anything, and a consumer
    # already routing `review-answer-key` needs no second slug for "most of it"
    # against "all of it". A second spelling for one remedy is the drift this
    # table exists to remove.
    "dataset-mostly-generated-answer-key": "review-answer-key",
    "evaluator-absent": "connect-evaluator",
    "evaluator-unresolved": "repair-evaluator",
    "evaluator-invalid": "repair-evaluator",
    "evaluator-timeout": "bound-evaluator-cost",
    "agent-no-varying-knobs": "vary-knobs",
}
ACTION_KINDS = frozenset({PROCEED, *ACTION_FOR_CONDITION.values()})

# What each route ASKS THE USER FOR - a different question from how far the
# ceiling lets the score rise, and the question that decides whether the run
# waits.
#
# #149 partitions the routes in two: a route asking for a creation or a repair
# stops the run, and a route that only scopes what the result may claim does
# not. `dataset-shape-unrecognised` is neither, and that is why it is here.
# Nothing needs creating - the customer handed over a file. Nothing is known to
# need repairing - a fully labelled file whose rows say `question`/`answer`
# produces this exact state and is not defective in any way. And the claim is
# not merely scoped: a score read from zero matched rows is not a bounded
# result, it is no result.
#
# So the partition is three, and the third one is real:
#
#   CREATION_OR_REPAIR  something must be made or mended before this can be
#                       measured                              -> the run waits
#   DIAGNOSTIC          nothing was measured, and the material may be perfectly
#                       fine; what is owed is a look at it, not a change to it
#                                                             -> the run waits
#   CLAIM_SCOPING       a real comparison whose claim is bounded
#                                                             -> the run proceeds
#
# The first two both stop the run and are still not the same statement, which
# is why this is a third category rather than a widened first one. They route
# to different work, and they read differently on the card a customer is shown
# before they are asked to pay: telling someone whose file is perfectly good to
# repair it is precisely the defect this branch exists to remove, and a two-way
# partition can only say "repair".
CREATION_OR_REPAIR = "creation-or-repair"
DIAGNOSTIC = "diagnostic"
CLAIM_SCOPING = "claim-scoping"
ROUTE_CATEGORIES = frozenset({CREATION_OR_REPAIR, DIAGNOSTIC, CLAIM_SCOPING})

ROUTE_CATEGORY: dict[str, str] = {
    "dataset-absent": CREATION_OR_REPAIR,
    # The condition this category was added for. `read-dataset` is the only
    # remedy in the vocabulary that asks for an inspection rather than a
    # change.
    "dataset-shape-unrecognised": DIAGNOSTIC,
    # Both route to `get-data` and they disagree about whether the run waits -
    # `below-measurable-size` blocks and `coarse-resolution` does not. Both are
    # classified by what the result IS (a real comparison, narrowly bounded)
    # rather than by that disagreement, which is tracked separately: forcing
    # the two into agreement breaks one side either way, and it is not this
    # branch's call.
    "dataset-below-measurable-size": CLAIM_SCOPING,
    "dataset-coarse-resolution": CLAIM_SCOPING,
    "dataset-no-expected-outputs": CREATION_OR_REPAIR,
    "dataset-integrity-fail": CREATION_OR_REPAIR,
    "dataset-tune-holdout-overlap": CREATION_OR_REPAIR,
    "dataset-fully-synthetic": CLAIM_SCOPING,
    "dataset-mostly-synthetic": CLAIM_SCOPING,
    "dataset-generated-answer-key": CLAIM_SCOPING,
    # #161's second rung. It scopes for the same reason the rung above
    # does - the questions are real and only part of the ruler is a
    # model's - and it is registered here because `Cap.__post_init__`
    # fails closed on an unclassified condition: #161 added the cap and
    # #144 added the registry, and neither branch could see the other.
    "dataset-mostly-generated-answer-key": CLAIM_SCOPING,
    "evaluator-absent": CREATION_OR_REPAIR,
    # The sweep found a second one. A file is connected and no method could be
    # honestly declared for it without executing it - which on the ordinary
    # shape means nothing is wrong, only unnamed. It shares `repair-evaluator`
    # with `evaluator-invalid` because a consumer needs no new slug, but the
    # two are not the same statement: `evaluator-invalid` was PROVEN wrong by
    # probes that ran, and this one was never read.
    "evaluator-unresolved": DIAGNOSTIC,
    "evaluator-invalid": CREATION_OR_REPAIR,
    "evaluator-timeout": CREATION_OR_REPAIR,
    # Conditional, and classified the same way `dataset-below-measurable-size`
    # above already is: by what the result IS, not by whether the run waits.
    # Three caps carry this condition. Two of them - nothing wired, and knobs
    # listed with none attested - are repairs and declare `blocks=True`. The
    # third (`NOT_YET_MEASURED_CAP`, from #144) fires when no config-space
    # document reached this score at all: nothing in the user's project is
    # broken, the enhanced run is simply what writes that document, and it
    # declares `blocks=False`. #149 wrote CREATION_OR_REPAIR here before that
    # third branch existed, and its own agent-routing test already asserts this
    # condition must have BOTH a blocking and an advisory branch - so
    # CREATION_OR_REPAIR contradicted #149's own expectation the moment #144
    # landed, and the two compose only under the category that admits both.
    "agent-no-varying-knobs": CLAIM_SCOPING,
}


# What a ceiling is FOR, and the one sentence the ordering was missing.
#
# A ceiling answers "how good is this data now", not "what could this become".
# That is the owner's decision and it settles the objection the ranking keeps
# attracting: a broken real dataset is capped harder (35) than a fully
# generated one (65), which looks inverted if you read the numbers as a claim
# about real-world basis. It is not one. A broken dataset cannot be run at all;
# a generated one can be run today and corrected by a person afterwards. Grade
# the current state, and the order comes out the way it is.
#
# Do not reorder these on the strength of the potential reading - it was put to
# the owner and rejected.
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
DATASET_SHAPE_UNRECOGNISED_CEILING = 25
# Equal to `evaluator-invalid`, and for a related reason: neither state has
# produced a number anyone may read. A file was provided and no row in it
# matched the shape this score read it with, so nothing was measured. It cannot
# be 20 - that is "no data at all" and this customer has a file. It stays below
# `dataset-no-expected-outputs` (30) and `dataset-integrity-fail` (35) because
# each of those has at least one row that confirmed the shape, which is
# positive evidence this state does not have.
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
WIRING_CHECK_CEILING = 74
# One below the STRONG boundary at 75, which is the only derived number in this
# block: the claim is about what the result may PRESENT as, and under ten
# comparable examples it may not present as STRONG. See
# `WIRING_CHECK_EXAMPLES`.
GENERATED_ANSWER_KEY_CEILING = 74
# The questions are real and there are enough of them; only the answer key was
# written by a model, so the score reports agreement with that model. Above
# both synthetic ceilings because strictly more of the data was observed - and
# 74 rather than 75, because 75 IS the STRONG threshold: at 75 a dataset whose
# entire ruler was written by a model could present as STRONG, which is the one
# claim this ceiling exists to refuse. Synthesised material may be workable; it
# may not be good.
#
# Two of the three ceilings on this ladder are not derived and are not meant to
# be. 65 and 70 are relative positions - ordered against each other because
# strictly more invented data may not be the less capped, and placed inside
# WORKABLE because that is the band the ladder intends. Only this rung states a
# claim about a BAND, so only this rung takes the band edge's number, the same
# way `WIRING_CHECK_CEILING` and `COARSE_RESOLUTION_CEILING` do. Do not
# "correct" 65 and 70 onto a band edge: they answer a different question.
#
# It lands equal to `WIRING_CHECK_CEILING`, which is a coincidence of the same
# band edge rather than a shared cause, exactly as `evaluator-absent` and
# `evaluator-unresolved` already do at 40.
MOSTLY_GENERATED_ANSWER_KEY_CEILING = 74
# The rung the ladder was missing, and the reason it needed one: with the rung
# above as the only one, the cap turned on the LAST row. 200 of 200 model-
# written answers scored 74/WORKABLE/BLOCKED and 199 of 200 scored 94/EXCELLENT
# with no cap at all, on the same dataset - a ceiling one row removes is not a
# ceiling. The sibling ladder never had that shape: `MOSTLY_SYNTHETIC_SHARE` is
# 0.5, so generated ROWS have always been graded in two steps.
#
# EQUAL to the rung above, and that is the whole available room. The owner's
# rule is that data a model supplied may be workable and may not be good, so
# every ceiling on this ladder sits below the STRONG edge at 75; the rung above
# already takes 74, the highest number that satisfies it. A ladder cannot
# graduate a value it has no room to graduate, so this rung graduates the OTHER
# thing a cap decides: the run does not wait. All of the key being a model's
# stops the run until a person has looked; most of it bounds what the result
# may claim and lets the run proceed, because the questions are all real and a
# person did write part of the key.
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
            ("dataset-shape-unrecognised", DATASET_SHAPE_UNRECOGNISED_CEILING),
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
            ("dataset-below-measurable-size", WIRING_CHECK_CEILING),
            ("dataset-generated-answer-key", GENERATED_ANSWER_KEY_CEILING),
            (
                "dataset-mostly-generated-answer-key",
                MOSTLY_GENERATED_ANSWER_KEY_CEILING,
            ),
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

# The declared order, as a number the runtime actually reads.
#
# `CAP_CEILING` above folds the order away - a dict answers "what ceiling",
# never "which is worse" - and both consumers used to sort by
# `(ceiling, condition)`, which at equal ceilings is alphabetical. So the order
# written down above decided nothing: swapping two entries left `CAP_CEILING`
# byte-identical and every payload unchanged, and where it could be observed it
# was contradicted. At the 45 tie the declaration ranks `evaluator-timeout`
# first and the card recommended `vary-knobs`, purely because "a" sorts before
# "e".
#
# The ceiling still decides severity, because the ceiling is what holds the
# score down. This rank decides the tie - the one place the ceiling has nothing
# left to say, and the exact place the declaration was silent before.
CAP_RANK: dict[str, int] = {
    condition: index
    for index, condition in enumerate(
        condition
        for _group, entries in CAP_SEVERITY_ORDER
        for condition, _ceiling in entries
    )
}


def cap_order(cap: "Cap") -> tuple[int, int]:
    """The one sort key for caps, so no consumer invents a second one.

    `aggregate` and `collect_gaps` both order caps, and ordering them two ways
    is how the card's recommended action and the gap list come to disagree
    about which cap is worst. They call this.
    """
    return (cap.ceiling, CAP_RANK[cap.condition])


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
    # A file no row of which matched the shape it was read with yielded no
    # expected answer and no comparable example either - the same three
    # consequences as an absent dataset, from a file that does exist.
    ("dataset-shape-unrecognised", "dataset-no-expected-outputs"),
    ("dataset-shape-unrecognised", "dataset-below-measurable-size"),
    ("dataset-shape-unrecognised", "dataset-coarse-resolution"),
    # All of it generated is also most of it generated.
    ("dataset-fully-synthetic", "dataset-mostly-synthetic"),
    # And the same on the answer-key ladder, which now has the same two rungs.
    ("dataset-generated-answer-key", "dataset-mostly-generated-answer-key"),
    # Under ten comparable examples is also under thirty.
    ("dataset-below-measurable-size", "dataset-coarse-resolution"),
)

# The other half of that declaration, and the half that was doing nothing.
#
# `CAP_SEVERITY_ORDER` is enforced twice - the constructor refuses an unranked
# condition and a test refuses a ranked one nothing raises. `CAP_IMPLICATIONS`
# was enforced nowhere: it constrains only the pairs someone remembered to
# write down, so a new cap that narrows an existing one and carries the higher
# ceiling ships green, which is the #144 defect exactly. Silence and "I checked
# and it overlaps nothing" are the same text in a file that only lists pairs.
#
# So overlap is declared for every condition, not for the ones that have one.
# A condition is either named in a pair above or listed here with the reason it
# is not, and the constructor refuses one that is in neither - the author of a
# new cap is asked the question rather than trusted to have asked it.
CAP_NO_IMPLICATION: dict[str, str] = {
    "evaluator-invalid": (
        "a ruler that scores wrong answers well is orthogonal to every dataset "
        "condition and mutually exclusive with the other evaluator ones"
    ),
    "evaluator-absent": "nothing is connected; no other condition can be read off that",
    "evaluator-unresolved": (
        "present-but-unnamed excludes absent, and no dataset condition follows "
        "from it"
    ),
    "evaluator-timeout": "a run that did not finish says nothing about the material",
    "agent-no-varying-knobs": "about the search space, which no dataset fact implies",
    "dataset-integrity-fail": (
        "fires only when at least one row DID parse, so it is the complement of "
        "dataset-absent rather than a narrowing of it"
    ),
    "dataset-tune-holdout-overlap": (
        "a split defect; it can accompany any size or provenance and narrows none"
    ),
}

# Every condition, reviewed for overlap one way or the other.
CAP_OVERLAP_REVIEWED: frozenset[str] = frozenset(
    {condition for pair in CAP_IMPLICATIONS for condition in pair}
    | set(CAP_NO_IMPLICATION)
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
    #
    # Which one a condition is, is not decided here case by case. SKILL.md
    # routes every cap by id, and the route already answers the question:
    #
    #   route asks for a creation or a repair   -> blocks (the run waits)
    #   route scopes what the RESULT may claim  -> advisory (the run proceeds)
    #
    # Read off that table, `dataset-absent` ("enter the creation dependency
    # matrix"), `dataset-no-expected-outputs`, `dataset-integrity-fail` and
    # `dataset-tune-holdout-overlap` ("repair a disjoint split") block, and the
    # three evaluator conditions block through the invalid-evaluator paragraph -
    # "do not run paid optimization against it". The synthetic-provenance,
    # generated-answer-key and small-sample conditions do not: their routes are
    # "apply the walkthrough labeling rules", "scope the claim", "before a
    # correctness claim", and "call rankings exploratory". Those are sentences
    # about the claim, and a ceiling is how this module says them.
    blocks: bool = True
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
        # And the third registry, which was declared and enforced nowhere. A
        # cap whose overlap with the others nobody stated is the #144 defect
        # waiting to recur - it fails here rather than shipping green.
        # And the route category, on the same fail-closed footing. A cap whose
        # route nobody classified is a cap whose `blocks` was chosen rather
        # than derived, which is how a customer holding a perfectly good file
        # was told to repair it.
        if self.condition not in ROUTE_CATEGORY:
            raise ValueError(
                f"cap {self.condition!r} has no entry in ROUTE_CATEGORY; say "
                "whether its remedy asks for a creation or repair, asks only "
                "for a look at material that may be fine, or only scopes what "
                "the result may claim"
            )
        if ROUTE_CATEGORY[self.condition] != CLAIM_SCOPING and not self.blocks:
            raise ValueError(
                f"cap {self.condition!r} is routed as "
                f"{ROUTE_CATEGORY[self.condition]} and does not block; a "
                "condition under which nothing was measured cannot let the "
                "run present a result, so either it scopes a claim or it waits"
            )
        if self.condition not in CAP_OVERLAP_REVIEWED:
            raise ValueError(
                f"cap {self.condition!r} states no overlap with the other "
                "conditions; name it in CAP_IMPLICATIONS if its evidence "
                "implies another condition's, or in CAP_NO_IMPLICATION with "
                "the reason it implies none"
            )
        # The two fields the guards above never looked at.
        #
        # `condition` failed closed and these did not, so `Cap(cond, None, ...)`,
        # `Cap(cond, "twenty", ...)`, `Cap(cond, 999, ...)`, `Cap(cond, -5, ...)`
        # and `blocks="yes"` all constructed. Each reaches arithmetic that
        # cannot say so: `min(weighted_average, ceiling)` raises deep inside
        # `aggregate` on a string and silently returns `None` for the overall
        # score's comparison partner, 999 makes a ceiling that can never bind,
        # -5 makes one that always does, and a truthy `blocks` string turns
        # every ceiling into a block. The type hints stated all of this and
        # nothing read them.
        #
        # The VALUE is still not pinned to `CAP_CEILING[condition]` - a probe
        # building `Cap(condition, 50, ...)` to exercise a ceiling it does not
        # otherwise reach is legitimate, and the source-reading test is where a
        # wrong constant at a call site actually shows up. What is refused is a
        # ceiling that is not a score on the 0-100 scale the band table reads.
        if isinstance(self.ceiling, bool) or not isinstance(self.ceiling, int):
            raise ValueError(
                f"cap {self.condition!r} carries a non-integer ceiling "
                f"{self.ceiling!r}; a ceiling is a score on the same 0-100 "
                "scale as the overall, because that is what it is compared to"
            )
        if not 0 <= self.ceiling <= 100:
            raise ValueError(
                f"cap {self.condition!r} carries a ceiling of {self.ceiling}, "
                "which is off the 0-100 scale; a ceiling above 100 can never "
                "bind and one below 0 always does, and neither describes a "
                "band this module can name"
            )
        if not isinstance(self.blocks, bool):
            raise ValueError(
                f"cap {self.condition!r} carries a non-boolean blocks flag "
                f"{self.blocks!r}; `blocks` decides BLOCKED against OK and a "
                "truthy string decides it silently in one direction"
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
    # Whether a dataset reached this score at all, and if it did, how much of it
    # could be read. `exists` alone conflated two states the customer
    # experiences very differently: "you have no data" and "I could not read the
    # data you gave me". The second has several causes - the rows are fine but
    # the selected field names are not the ones in the file, the lines are not
    # JSON, one field path was selected for both the input and the expected
    # answer - and reporting any of them as the first tells a customer holding a
    # good dataset to go and get one.
    # This mirrors AgentFacts.config_space_supplied, which already draws the
    # same line for the same reason.
    dataset_supplied: bool = False
    unreadable_rows: int | None = None
    # Preflight's own sentence about why nothing could be read, forwarded
    # verbatim rather than re-derived here.
    #
    # This adapter cannot see the cause: `unreadable_rows` is the same number
    # for a file of broken JSON, a file whose selected field names are not the
    # ones in it, and a run that selected one field path for both the input and
    # the expected answer. Guessing a cause from the count produced a sentence
    # that was simply false for the third - it named "malformed lines, or
    # missing the input or expected-answer field" and told the reader to "check
    # both", when neither was true and preflight had already reported
    # `input and expected-output field paths must be different`.
    #
    # `None` when preflight said nothing about it; then the reason names no
    # cause at all rather than inventing one.
    unreadable_detail: str | None = None
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
    # Withheld checks stay in the denominator and earn nothing. Renormalizing
    # over the measured ones is right when this tool could not look, and wrong
    # when the run was asked for the evidence and did not give it - there,
    # dropping the check from the denominator made silence score better than an
    # honest answer. See `SubScore.withheld`. Confidence below is unchanged and
    # still reports them as unchecked, because they are.
    scored_weight = measured_weight + sum(
        item.maximum for item in subscores if item.withheld and not item.measured
    )
    score = round_half_up(100.0 * earned / scored_weight)
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
            # The two reasons above are two different findings, and only one of
            # them stops anything. With examples to compare on, this is the
            # wiring check the guide itself sanctions - preflight WARNs rather
            # than FAILs at this size, `size_points` calls it "a wiring check,
            # not a score", and SKILL.md routes it to "call rankings
            # exploratory, not stable comparisons". Blocking contradicted the
            # cap's own last sentence on the same card: "treat any difference
            # as a hint, not a result" is advice for a run that happens.
            # Its 89-ceiling twin below already had this right.
            #
            # Zero scoreable examples is the other finding, and it keeps
            # blocking: nothing can be compared at all, so there is no result
            # to bound. That state is reachable with the aggregate label count
            # non-zero - every label on one side of a declared split - where no
            # other cap fires to stop it.
            blocks=effective_n == 0,
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
# The four ceilings these shares raise are defined with every other ceiling in
# `CAP_SEVERITY_ORDER`; only the shares that trigger them live here.
#
# Both ladders now graduate in two steps, and the answer-key one did not. Its
# single rung fired at 1.0 exactly, so the cap turned on the last row: 200 of
# 200 model-written answers scored 74/WORKABLE/BLOCKED and 199 of 200 scored
# 94/EXCELLENT with no cap at all. `MOSTLY_GENERATED_ANSWER_KEY_SHARE` is the
# missing rung, and it is 0.5 for the same reason its sibling is: "most of it"
# is the one share boundary that means something to a reader.
MOSTLY_SYNTHETIC_SHARE = 0.5
MOSTLY_GENERATED_ANSWER_KEY_SHARE = 0.5
GENERATED_ANSWER_KEY_SHARE = 1.0

# All three are advisory, by the rule on `Cap.blocks`: SKILL.md routes them to
# "apply the walkthrough labeling rules", "scope the claim" and "before a
# correctness claim" - sentences about what the result may say, not repairs the
# run waits on. Blocking made the guide contradict itself at its own finish
# line. Generated data is what the guide CREATES for a user who has none, so
# `tests/behavioral/scenarios/partial-missing-dataset` - real agent, real
# evaluator, an 18-row walkthrough dataset this guide wrote, and
# `closing_beats_opening: true` - closed on "65/100 WORKABLE (PAID RUN
# BLOCKED)" and "fix: connect-real-data", demanding real data from the one
# user who by construction has none. The glossary says the opposite in so many
# words: "synthetic data is fine for a first run but cannot prove real-world".
#
# The ceilings are untouched and still bind - 65, 70 and 75 are exactly how
# "cannot prove real-world" is said in a number. `aggregate` takes the minimum
# over all caps whatever their `blocks`.
FULLY_SYNTHETIC_CAP = Cap(
    "dataset-fully-synthetic",
    FULLY_SYNTHETIC_CEILING,
    "The dataset is generated, so a high score here measures the walkthrough, "
    "not real-world readiness.",
    blocks=False,
)
MOSTLY_SYNTHETIC_CAP = Cap(
    "dataset-mostly-synthetic",
    MOSTLY_SYNTHETIC_CEILING,
    "Most of the dataset is generated, so the result mostly measures invented "
    "examples rather than real traffic.",
    blocks=False,
)
GENERATED_ANSWER_KEY_CAP = Cap(
    "dataset-generated-answer-key",
    GENERATED_ANSWER_KEY_CEILING,
    "Every expected answer was written by a model, so a score measures "
    "agreement with that model rather than correctness.",
    blocks=False,
)


def _row_count(value: Any, name: str, *, required: bool = True) -> int:
    """Read one provenance row count, refusing an absent or impossible one.

    An absent key used to fall back to 0, on the rationale that "the preflight
    JSON predates the field, so an older payload keeps scoring as it did". That
    is a backward-compatibility decision, and this repository has published
    nothing for anyone to be compatible with - there is no older payload. What
    the fallback bought instead was a gate that fails open: `answerable_rows`
    guards the whole generated-answer-key ladder, and a 0 short-circuits it, so
    a preflight JSON with the key deleted scored the same 200-row dataset
    EXCELLENT with no cap where the real payload capped it at 74. Silence was
    the highest-scoring input.

    So absence is refused, with the same message the impossible values below
    already carry. `required=False` is for a count whose CHECK is conditional -
    `dataset-output-placeholders` is emitted only when placeholders exist, so
    its absence is a measured "none", not a missing field.

    A key that IS present and
    carries a negative or non-integer count is a different thing: it reaches the
    arithmetic, shifts the denominator every share is computed over, and can
    push the sub-score past its own 10-point maximum (`-1` synthesised rows
    against 50 collected scores 10.14). Refused for the same reason, and with
    the same message, as the declared-split counts a few lines below - a guard
    that checks four counts and waves three through is the odd-one-out this
    file already has an issue open about (traigent-first-run#69).
    """
    if value is None:
        if not required:
            return 0
        raise PreflightInputError(
            f"dataset-provenance carries no {name} count - every count this "
            "score reads is emitted together by preflight.py, so this JSON was "
            "edited or predates the current preflight.py; re-run preflight.py "
            "--json from the same version as this script"
        )
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
                [FULLY_SYNTHETIC_CAP],
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
        caps.append(FULLY_SYNTHETIC_CAP)
    elif synthesised_share > MOSTLY_SYNTHETIC_SHARE:
        # Without this the any()->all() correction would hand every mixture a
        # free pass: a 90%-generated dataset would lose its ceiling entirely.
        caps.append(MOSTLY_SYNTHETIC_CAP)

    # The expected answers are the ruler every score is measured against. When
    # all of them were written by a model, an accuracy number reports agreement
    # with that model's opinion, not correctness - believable, and unfalsifiable
    # from inside the run. The questions are still real, so this ceiling sits
    # above both synthetic ones.
    #
    # Two rungs, the same shape as the synthetic ladder above, because one rung
    # made this a cliff rather than a ceiling: it fired at 1.0 exactly, so 199
    # of 200 model-written answers cleared it entirely and scored EXCELLENT on
    # a ruler 99.5% of which was a model's. Deleting one row is not a remedy.
    #
    # `answerable_rows` is read through `_row_count`, which refuses an absent
    # count rather than reading it as zero - a zero here short-circuits the
    # whole ladder, and silence used to buy that for free.
    #
    # Both rungs are advisory. #161 wrote the upper one with `Cap`'s default,
    # which is `blocks=True`; #149 had already decided the opposite for this
    # exact condition, because SKILL.md routes it to "a person reviews a sample
    # before a correctness claim" - a scope on what may be said, not a repair
    # the run waits on. Taking #161's construction verbatim would have re-armed
    # the stop that #149 exists to remove, on the walkthrough dataset this
    # guide writes for a user who has no data. So the module-level
    # `GENERATED_ANSWER_KEY_CAP` is kept for the full rung and the new rung is
    # built here, because its reason quotes counts and cannot be a constant.
    if uses_expected_outputs and facts.synthesised_rows != counted:
        generated_key_share = (
            facts.generated_answer_rows / facts.answerable_rows
            if facts.answerable_rows
            else 0.0
        )
        if generated_key_share >= GENERATED_ANSWER_KEY_SHARE:
            caps.append(GENERATED_ANSWER_KEY_CAP)
        elif generated_key_share > MOSTLY_GENERATED_ANSWER_KEY_SHARE:
            caps.append(
                Cap(
                    "dataset-mostly-generated-answer-key",
                    MOSTLY_GENERATED_ANSWER_KEY_CEILING,
                    f"{facts.generated_answer_rows} of "
                    f"{facts.answerable_rows} expected answers were written by "
                    "a model, so most of what this score is measured against "
                    "is a model's opinion rather than an observed answer.",
                    # A real comparison on real questions, most of whose ruler
                    # a person did not write. That bounds the claim; it does
                    # not stop the run, exactly as the small-sample ceiling at
                    # the same number does not.
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


def scores_without_a_reference(method: str | None) -> bool:
    """True when the evaluator can score a row that carries no expected output.

    A rubric or pointwise judge reads the input and the output; the gold answer
    is not an input to it. So "how many rows are scoreable" has a different
    answer for those methods, and the dataset pillar cannot answer it alone
    (traigent-first-run#67).
    """
    return method in REFERENCE_FREE_METHODS


def score_dataset(
    facts: DatasetFacts, evaluator_method: str | None = None
) -> tuple[Pillar, list[Cap]]:
    caps: list[Cap] = []
    subs: list[SubScore] = []

    if not facts.exists or not facts.rows:
        # Three different situations used to produce one sentence, and one
        # remedy. Say which, and route each to its own.
        unreadable = facts.unreadable_rows or 0
        detail = facts.unreadable_detail
        if facts.dataset_supplied and unreadable:
            # Rows were counted and none matched the shape the run read them
            # with. The earlier wording called that broken data. It is not, on
            # most of the files that produce it - see `ACTION_FOR_CONDITION`
            # for the reproductions - so this says what is true instead: what
            # failed is the reading, and whether the data is at fault is not
            # yet established.
            #
            # Ceiling 25, kept, and re-argued for the sentence it now carries.
            # It is a bound on what has been DEMONSTRATED, and nothing has:
            # the score may not present a file nobody has read as better than
            # one that is measurable. 20 is "no data at all"; this customer has
            # a file, so it cannot be that. It stays below
            # `dataset-no-expected-outputs` (30) and `dataset-integrity-fail`
            # (35) because each of those has at least one row that confirmed
            # the shape, which is positive evidence this state does not have.
            #
            # Blocking, because nothing here is measurable yet - but the route
            # is `read-dataset`, so what it blocks on is one look at the file
            # rather than a repair. The reason says so, because this cap is
            # computed at the opening gate, before the assistant has had any
            # chance to adapt, and a customer reading that card is owed the
            # fact that it can clear on the very next step.
            #
            # The cause is preflight's to state, not this adapter's to guess:
            # every wording invented here was false for at least one of the
            # inputs that reach this branch.
            reason = (
                "A dataset was provided and no row in it matched the shape "
                "this score read it with, so nothing could be measured yet"
            )
            reason += f": {detail}." if detail else "."
            reason += (
                " That describes the reading, not a defect in the data - open "
                "the file, select the fields it actually uses, and re-score; "
                "this can clear on the next step."
            )
            evidence = "provided, no row matched the shape it was read with"
            caps.append(
                Cap(
                    "dataset-shape-unrecognised",
                    DATASET_SHAPE_UNRECOGNISED_CEILING,
                    reason,
                )
            )
        else:
            if facts.dataset_supplied:
                # A dataset was named and preflight counted no rows to salvage
                # - the path does not exist, or the file holds nothing. Those
                # are different problems and preflight's `dataset-shape` FAIL
                # says which; without it, this printed one sentence for both.
                #
                # "nothing could be read from it" was one word away from the
                # `dataset-shape-unrecognised` sentence directly above, and the
                # two route to opposite remedies: go and get data, or go and
                # read the file you have. A reader cannot pick a branch off two
                # sentences that differ by "and none of its rows" versus "but
                # nothing". So this one says the thing that makes `get-data`
                # the right instruction - there are no rows here at all, so
                # there is nothing to go and look at - which is exactly what
                # separates it from the state above, where rows exist and none
                # of them matched the shape they were read with.
                reason = (
                    "A dataset was provided to this score and it holds no rows "
                    "at all, so there is nothing to measure and nothing to "
                    "repair"
                )
                reason += f": {detail}" if detail else "."
                evidence = "provided, no rows read"
            else:
                reason = (
                    "No dataset was provided to this score, so nothing can be measured."
                )
                evidence = "no dataset provided to this score"
            caps.append(Cap("dataset-absent", DATASET_ABSENT_CEILING, reason))
        subs.append(SubScore("labels", 0.0, 30.0, True, evidence))
        subs.append(SubScore("power", 0.0, 25.0, True, evidence))
        subs.append(SubScore("difficulty", 0.0, 15.0, False, evidence))
        subs.append(SubScore("diversity", 0.0, 20.0, False, evidence))
        subs.append(SubScore("provenance", 0.0, 10.0, True, evidence))
        return combine("dataset", subs), caps

    rows = facts.rows
    reference_free = scores_without_a_reference(evaluator_method)
    labelled = facts.labelled_rows if facts.labelled_rows is not None else 0
    # Whether the reason nothing is scoreable is already named, and already
    # routed, by the labels cap below. Read by the power ceiling further down.
    unlabelled_capped = False
    if reference_free:
        subs.append(
            SubScore(
                "labels",
                0.0,
                30.0,
                False,
                "this reference-free evaluator does not use expected outputs"
                + (f" ({labelled} present but unused)" if labelled else ""),
            )
        )
    elif labelled == 0:
        unlabelled_capped = True
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
                labels_evidence(labelled, rows, facts.placeholder_rows),
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
        # Resolution is a property of the TUNING split, and the holdout is
        # exempt from it.
        #
        # This used to take `min(tuning, holdout, ...)`, so the held-back set
        # bounded a number it does not participate in producing. The search
        # compares configurations against each other on the tuning rows; that
        # comparison's resolution is how many rows it has. The holdout is not a
        # second comparison - it checks the one winner the search already
        # picked, once, and it is deliberately small.
        #
        # The cost of the old reading was structural rather than marginal. The
        # walkthrough reserves ten held-out rows, so `min` was ten for every
        # project that used it, `power_ceiling(10)` fired every time, and
        # EXCELLENT became unreachable: a perfect 1,000-row project scored 89
        # with a permanent `dataset-coarse-resolution` cap it could not clear
        # by any action - other than deleting the holdout, which is the one
        # thing the guide asks for. It also inverted the incentive the sweep
        # above is about: declaring a split scored WORSE than declaring none.
        #
        # The holdout keeps every other job it has. Its own size is stated to
        # the user where the result is read, the overlap cap still fires on a
        # leaky split, and nothing here claims ten rows can settle a question -
        # only that they do not set the tuning comparison's resolution.
        if reference_free:
            # A judge that needs no reference scores every tuning row, so the
            # labelled counts do not bound this comparison at all.
            effective = facts.tuning_rows
            marker = f"{facts.tuning_rows} scoreable"
        elif facts.tuning_labelled_rows is not None:
            effective = min(facts.tuning_rows, facts.tuning_labelled_rows)
            marker = f"{facts.tuning_labelled_rows} scoreable"
        else:
            effective = scoreable(facts.tuning_rows, labelled)
            marker = f"{labelled} scoreable"
        points, evidence = size_points(effective)
        prefix = f"{facts.tuning_rows} to tune on / {facts.holdout_rows} held back"
        if effective < facts.tuning_rows:
            prefix = f"{prefix}, {marker}"
        # Exempt from setting the resolution is not exempt from being reported.
        # A held-back set with nothing scoreable in it cannot check the winner
        # it exists to check, and taking it out of `effective` above is what
        # stopped that from showing up in the number - so it is said here
        # instead, on the card, where a user can act on it.
        if not reference_free and facts.holdout_labelled_rows == 0:
            prefix = f"{prefix}; none of the held-back rows can be scored"
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
            f"{facts.tuning_rows} tuning rows and no independent validation set, so the "
            f"result would be measured on the same rows the search used; {evidence}"
        )
    else:
        effective = scoreable(rows, labelled)
        points, evidence = size_points(effective)
        points *= 0.8
        if effective < rows:
            evidence = f"{rows} rows, {labelled} scoreable; {evidence}"
        evidence = (
            "no tuning set and held-back test set, so the result would be "
            f"measured on the same rows the search used; {evidence}"
        )
    subs.append(SubScore("power", round(points, 2), 25.0, True, evidence))
    # Deducting alone let the card say "a wiring check, not a score" and return
    # STRONG in the same breath (#88). The ceiling is what stops a result
    # presenting as trustworthy when nothing measurable was measured.
    ceiling = power_ceiling(effective)
    # A zero that the labels cap already owns is not a second finding.
    #
    # When rows exist and none carries an expected output, `effective` is zero
    # BECAUSE of that, and `dataset-no-expected-outputs` has already said so
    # and routed it to `label-data` - repair the rows the customer is holding.
    # Appending the power ceiling here restated the same zero as
    # `dataset-below-measurable-size`, whose remedy is `get-data`: the card
    # carried two FIX lines for one fact, and the second told a customer with
    # 50 perfectly good inputs to go and collect examples. That is the defect
    # this file already fixed for `dataset-shape-unrecognised`, one condition
    # over.
    #
    # Suppressing it moves no number: 30 is below the 74 ceiling, so the labels
    # cap is the operative one either way and the run stays blocked. When the
    # zero has any other source - an empty side of a declared split - nothing
    # else has named it, so the ceiling still fires.
    if ceiling is not None and not (effective == 0 and unlabelled_capped):
        caps.append(ceiling)

    # `is not None`, not truthiness. A declared zero means preflight looked at
    # every row and found no difficulty tag, which is a measurement with a
    # value of nothing; truthiness read it as "the check never ran" and dropped
    # it from the denominator, so a dataset that tags nothing scored the
    # pillar 92 where one that honestly tags a single band scored 82. The
    # weaker dataset won by ten points for saying less.
    if facts.difficulty_tagged_rows is not None:
        bands = set(facts.difficulty_bands)
        fraction = len(bands & {"easy", "medium", "hard", "very-hard"}) / 4.0
        subs.append(
            SubScore(
                "difficulty",
                round(15.0 * fraction, 2),
                15.0,
                True,
                (
                    f"bands present: {', '.join(sorted(bands))}"
                    if bands
                    else f"no row of {facts.rows} carries a difficulty tag, so "
                    "no spread is evidenced"
                ),
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
                withheld=True,
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
        # Deliberately left as-is. The dataset pillar above earns its new
        # phrasing with a new fact (`dataset_supplied`); this pillar has no
        # equivalent, and `present=False` covers both "no evaluator reached this
        # score" and "a path was supplied that does not exist". Rewording it to
        # "was provided to this score" without that fact would be false in the
        # second case - one WAS provided. Giving this pillar the same fact is a
        # follow-up, not a free rename.
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
                # Withheld, not unavailable: the run is asked for
                # `--task-kind` and chose not to answer. Renormalized away, not
                # answering scored the pillar 100 against 83 for declaring a
                # kind the method is a poor ruler for.
                withheld=True,
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
                # Same shape as task-fit: calibration is this run's to perform,
                # and reporting no probe scores used to score the pillar 100
                # against 87 for reporting a narrow spread honestly.
                withheld=True,
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

# Deliberately tense-neutral, and it took two drafts to get there. The first
# said "has reached this score YET" and "the enhanced search WRITES that
# document" - a claim that the search has not happened. This scorer cannot know
# that: it reads a preflight file, a calibration file and a config-space file,
# and those look identical at the opening gate and at the close. The guide
# passes `--config-space` at the close only when the search emitted one, so a
# stopped, failed, or zero-trial search lands here too - and there the future
# tense is simply false. What IS true in both places is the mechanism: no
# document was provided, and the enhanced run is what produces one. The reader
# who has just watched their search fail is told that by the run's own outcome
# report, not by this line.
#
# "provided", to match the pillar evidence beside it - two spellings of one
# fact, fourteen lines apart, read as two findings.
NOT_YET_MEASURED_CAP = Cap(
    "agent-no-varying-knobs",
    AGENT_NO_VARYING_KNOBS_CEILING,
    "No settings document was provided to this score, so the settings a search "
    "would vary cannot be counted. The enhanced run writes that document when "
    "it completes; nothing in your project needs repairing for this.",
    blocks=False,
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
            # No "yet": the same tense bug the cap reason beside it was fixed
            # for. This branch is also reached at the CLOSE by a stopped,
            # failed, or zero-trial search, and there "yet" claims the search
            # has not happened - which this module cannot know and which is
            # false exactly when the reader has just watched one fail. Two
            # spellings of one fact, fourteen lines apart, and only one of them
            # was made true at both gates.
            else "no settings document was provided to this score"
        )
        # `blocks` answers "does this stop the run", not "is this true" - the
        # comment on the field says so, and says every cap used to imply BLOCKED
        # back when every cap meant something was broken. Both states here are
        # true; only one of them stops anything.
        #
        # A supplied document that lists nothing IS a defect: the user handed
        # over their wiring and there is nothing in it. No document at all is
        # not - the guide withholds one found before this run's search, so the
        # ordinary opening state is that none reached the score, and the very
        # next step is the baseline, which runs regardless. Reporting that as
        # BLOCKED told every project, including a perfect one, that its paid run
        # was stopped, and set `recommended_action` to `vary-knobs` - a repair
        # for a defect the user does not have - on the last card shown before
        # they are asked to pay.
        #
        # The ceiling is unchanged and still applies: `aggregate` takes the
        # minimum over all caps whatever their `blocks`, so the score stays
        # capped at 45 until wiring evidence exists. Only the claim that the run
        # is stopped goes away.
        #
        # The condition is "no document was supplied", which is WIDER than the
        # argument above - that argument is about the opening gate, and this
        # branch is also reached at the close by a stopped, failed, or zero-trial
        # search, which emits no document either (`references/run-safety.md`,
        # config-space document). Narrowing it would need a fact naming the
        # phase, and this module has none: preflight, calibration and
        # config-space are the whole input and all three look the same at both
        # gates. Rather than infer one, the two artifacts that CAN tell the
        # difference carry it - the cap's reason says nothing that is false
        # after a failed search, and run-safety.md tells the assistant that at
        # the close this cap's silence is not a verdict on the search, whose
        # outcome is reported from the run itself.
        cap = NOTHING_WIRED_CAP if facts.config_space_supplied else NOT_YET_MEASURED_CAP
        return nothing_to_search_pillar(evidence), [cap], []

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
    # Second column: the declared severity rank, so two caps that weigh the
    # same break their tie the way `CAP_SEVERITY_ORDER` ranks them instead of
    # by whichever condition id sorts first alphabetically. Non-cap gaps take a
    # rank past every cap's, which is where their weight already puts them and
    # keeps their existing alphabetical tie-break intact.
    unranked = len(CAP_RANK)
    gaps: list[tuple[float, int, str]] = []
    for cap in caps:
        gaps.append(
            (
                cap_weight(cap, overall),
                CAP_RANK[cap.condition],
                f"{cap.condition}: {cap.reason}",
            )
        )
    for pillar in pillars:
        for sub in pillar.subscores:
            if not sub.measured:
                gaps.append(
                    (
                        sub.maximum * 0.5,
                        unranked,
                        f"{pillar.name}/{sub.name} could not be measured - "
                        f"{sub.evidence}",
                    )
                )
            elif sub.value < sub.maximum:
                gaps.append(
                    (
                        sub.maximum - sub.value,
                        unranked,
                        f"{pillar.name}/{sub.name}: {sub.evidence}",
                    )
                )
    for knob in knobs:
        for note in knob.notes:
            gaps.append((5.0, unranked, f"knob '{knob.name}': {note}"))
    gaps.sort(key=lambda item: (-item[0], item[1], item[2]))
    return tuple(text for _weight, _rank, text in gaps)


def recommended_action(ordered_caps: Sequence[Cap]) -> str:
    """The one remedy to do first, from caps already sorted by ceiling.

    Only a *blocking* cap can displace `proceed`. An advisory ceiling bounds
    what the result may claim and stops nothing, so a run carrying only those is
    still worth making - recommending a fix there would contradict the guide's
    own rule that a low score never stops the walkthrough, and it is the same
    conflation `blocks` was added to end.

    Among blocking caps the lowest ceiling wins, which is the one setting the
    score. `ordered_caps` is already sorted by ceiling, so the first blocking
    entry is that one; this reads the order rather than re-deriving it, so the
    two cannot disagree about which cap is most severe.
    """
    for cap in ordered_caps:
        if cap.blocks:
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

    ordered_caps = tuple(sorted(caps, key=cap_order))
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
        # see which checks did not run and why.
        #
        # The sentence used to say a partial check can read BETTER than a full
        # one, which was true of every unmeasured check and is now true only of
        # the ones this run could not obtain - a check whose evidence the run
        # was asked for and did not supply keeps its full weight and earns
        # nothing (`SubScore.withheld`). So the line no longer makes a claim
        # about the direction, which now differs between two kinds of gap, and
        # says the thing that is true of both: the evidence is thin, and a thin
        # score is held at this band.
        unchecked = marker_unmeasured(unicode_ok)
        lines.append(
            f"  {palette.dim}Some checks could not run (marked {unchecked} above), "
            f"so this score rests on less evidence than a full one and stays "
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
        #
        # Only for a cap that blocks, though. `action_kind` is keyed by
        # CONDITION, so all three `agent-no-varying-knobs` sites share
        # `vary-knobs` - and printing "fix: `vary-knobs`" under "What limits how
        # high this can score" hands a perfect project a repair for a defect it
        # does not have, in the durable artifact, which is the exact line this
        # change set out to stop showing. `dataset-coarse-resolution` had the
        # same shape ("fix: `get-data`" for a healthy 15-row set), so both are
        # fixed here rather than one: it is one rule, not two instances.
        # `--json` still carries `action_kind` on every cap for consumers that
        # want it; what goes away is the word "fix" over a state that is not
        # broken.
        remedy = f", fix: `{cap.action_kind}`" if cap.blocks else ""
        return f"- **{cap.condition}** ({effect}{remedy}): {cap.reason}"

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


def _dataset_absence_detail(records: Sequence[dict[str, Any]]) -> str | None:
    """Preflight's own sentence about why no row reached the score.

    Preferred from `dataset-integrity`, which names the per-row cause exactly
    ("invalid JSON (...)", "missing selected input field 'input'", "input and
    expected-output field paths must be different"); otherwise from
    `dataset-shape`, which is the only witness that separates a path that does
    not exist from a file that exists and holds nothing - two states that
    printed byte-identical scores before this read them.

    `None` when neither check FAILed with a detail, so the caller says nothing
    about the cause rather than choosing one.
    """
    details = {
        record["check"]: record.get("detail")
        for record in records
        if isinstance(record, dict)
        and "check" in record
        and record.get("status") == "FAIL"
    }
    for check in ("dataset-integrity", "dataset-shape"):
        detail = details.get(check)
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return None


def dataset_facts_from_preflight(records: Sequence[dict[str, Any]]) -> DatasetFacts:
    metrics = _metrics_by_check(records)
    statuses = _status_by_check(records)
    provenance = metrics.get("dataset-provenance", {})
    difficulty = metrics.get("dataset-difficulty-coverage", {})
    integrity = metrics.get("dataset-integrity", {})
    # Structural integrity is about malformed rows (bad JSON, non-objects,
    # missing inputs). Rows that merely lack an expected output are unlabelled,
    # not malformed, so they must not trip the integrity cap - they are scored
    # through the "no expected outputs" branch instead. Read dataset-integrity
    # directly (dataset-shape now also fails for a merely-unlabelled dataset).
    #
    # Checked before the no-provenance return below, not after it: that return
    # reads the same count to decide between "broken data" and "no data", so a
    # payload too old to carry it must refuse there too rather than quietly
    # score as the second.
    integrity_status = statuses.get("dataset-integrity")
    if integrity_status == "FAIL" and "malformed_rows" not in integrity:
        raise PreflightInputError(
            "dataset-integrity FAILed but carries no malformed_rows count - "
            "this preflight JSON predates the current preflight.py; re-run "
            "preflight.py --json from the same version as this script"
        )
    # No provenance metric at all means preflight found no rows to describe - a
    # genuinely absent or empty dataset. An unlabelled-but-present dataset now
    # carries provenance (rows > 0, labelled_rows == 0), so it lands below in the
    # exists=True branch and reaches the cap-30 "no expected outputs" case.
    if not provenance:
        # Preflight ran no dataset check at all -> nothing was supplied. It ran
        # one and salvaged nothing -> a dataset was supplied and could not be
        # read. Both used to arrive here as a bare exists=False.
        supplied = any(
            str(record.get("check", "")).startswith("dataset-") for record in records
        )
        return DatasetFacts(
            exists=False,
            dataset_supplied=supplied,
            # `malformed_rows`, not `invalid_rows`: the latter is
            # `malformed_rows + unlabelled_rows` (preflight.py), and an
            # unlabelled row is a row that WAS read. The two agree on every
            # payload that reaches this return today, because a dataset with
            # unlabelled rows carries provenance and leaves through the branch
            # below - so reading the sum was correct only by way of a fact
            # asserted elsewhere. Read the count that means what this says.
            unreadable_rows=integrity.get("malformed_rows"),
            unreadable_detail=_dataset_absence_detail(records),
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
                f"{'/'.join(unusable)} count - a declared tuning/holdout split "
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
                    f"rows across tuning and holdout, more than the "
                    f"{aggregate_labelled} the dataset declares in total - the "
                    "splits are disjoint, so this cannot describe one dataset; "
                    "re-run preflight.py --json from the same version as this "
                    "script"
                )
    return DatasetFacts(
        exists=True,
        # Preflight described a dataset, so one was supplied - stated here
        # rather than left to default. `exists=True` with no usable row count
        # (a provenance record carrying no `rows`) falls into the same
        # no-rows branch of `score_dataset` as the returns above, where the
        # default `False` made it say "No dataset was provided to this score"
        # about a dataset preflight had just described.
        dataset_supplied=True,
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
            # Emitted only when at least one placeholder exists, so an absent
            # count here is preflight saying "none", not preflight saying
            # nothing.
            required=False,
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
# an undeclared key is *refused*, never half-read and never quietly dropped.
# Ignoring it was the earlier rule, and it reproduced the very defect above
# through the schema's own front door - `max_trial` for `max_trials` is one
# character, and the document that carried it scored 89 STRONG as 92 EXCELLENT
# under a byte-identical evidence line, exit 0. A key this declaration does not
# name cannot be told apart from a misspelling of one it does, so it is refused
# by name (`_reject_undeclared_fields`). Two rules hold across every reader, in
# both directions:
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
        floor = noise_floor(knob, low, high)
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


def _reject_synonym_spellings(knobs: dict[str, Any], knobs_key: str) -> None:
    """Refuse a knob written under a name that means a knob this file knows.

    What `KNOB_ALIASES` bought was not the renaming - that was the part with
    the ordering hazard, the rebuilt dataclass and the field it could silently
    reset. What it bought was a REFUSAL: two spellings of one search dimension
    are two dimensions to everything downstream, so declaring both doubled the
    reported size of the space and paid a second dimension's credit for it.
    Deleting the table deleted the refusal with it, and measured end to end on
    one document declaring `prompt_policy` and `prompt_style` over different
    values, the scorer went from exit 2 to exit 0 with the agent pillar at 77
    against 61 for the same space written once, 24 combinations against 12, and
    a card reading `4 of 4 wired knobs actually vary`. A deletion that raises a
    score is the shape this repository has been wrong about before.

    So the refusal stays and the substitution does not. `KNOB_SYNONYMS` is
    never read to rename anything: no name the author wrote is replaced, no
    facts object is rebuilt, and nothing downstream has to know the table
    exists. It produces one message, and the message teaches the spelling the
    rest of this file uses - which is the same help `_reject_phantom_names`
    gives for a near miss, applied to the one case a near miss cannot reach
    because the written name is not a misspelling of anything.

    That case is the quieter half of the same defect. A document written
    consistently in `prompt_policy` matches itself, so nothing was phantom and
    nothing was refused - it simply scored lower, silently, than the identical
    document written in `prompt_style`: coverage 8.33/25 against 16.67/25 on
    one measured pair, with the missing knob named in the evidence line as
    though the author had not tuned it. Refusing is what makes that visible.

    Nothing is lost by refusing either shape: this repository has published no
    config space, and the one producer of the document writes `prompt_style`.
    """
    written = [name for name in knobs if name in KNOB_SYNONYMS]
    if not written:
        return
    detail = ", ".join(
        f"'{name}', which is another name for '{KNOB_SYNONYMS[name]}'"
        for name in sorted(written)
    )
    raise ConfigSpaceInputError(
        f"config-space '{knobs_key}' declares {detail}: declare each search "
        "dimension once, under the name this scorer knows. Two spellings of "
        "one dimension are counted as two dimensions, which doubles the "
        "reported size of the space and pays twice for one knob"
    )


def _reject_phantom_names(
    field: str, names: Iterable[str], knobs: dict[str, Any], knobs_key: str
) -> None:
    """Refuse a `wired`/`bounds` name that is no knob of the declared space.

    Both fields address knobs by name, and both are read by intersecting with
    the space, so an unmatched name silently disappears instead of failing.

    A name is compared to the declared space exactly as written. It used to be
    compared through an alias table first, which forced this check to run after
    a normalization step and made the ordering between the two a defect
    surface of its own; the table is gone, so a name either names a declared
    knob or it does not.

    What the table actually bought was one knob's worth of tolerance for one
    synonym. That is replaced here by the general form of the same help: the
    message names the declared knob the written name is closest to, for every
    knob rather than for `prompt_policy` alone, and it teaches the canonical
    spelling instead of silently substituting it.
    """
    phantom = sorted({name for name in names if name not in knobs})
    if phantom:
        detail = ", ".join(
            (
                f"'{name}' (did you mean '{near[0]}'?)"
                if (near := difflib.get_close_matches(name, sorted(knobs), n=1))
                else f"'{name}'"
            )
            for name in phantom
        )
        raise ConfigSpaceInputError(
            f"config-space '{field}' names {detail}, which "
            f"{'is' if len(phantom) == 1 else 'are'} not declared in "
            f"'{knobs_key}': a name that matches no knob would silently shrink "
            "the scored space instead"
        )


def _reject_undeclared_fields(document: dict[str, Any]) -> None:
    """Refuse a document key that `CONFIG_SPACE_FIELDS` does not name.

    Ignoring the key was the documented behaviour, and it produced exactly the
    defect the declaration exists to stop. `max_trial` for `max_trials` is one
    character, and it does not fail: the budget that dampens the knob-count
    points simply is not there, so a 512-configuration space against a 3-trial
    cap scored as though it had no cap at all - measured on the trunk this
    replaces, 89 STRONG became 92 EXCELLENT under a byte-identical evidence
    line ("6 of 6 wired knobs actually vary; 512 combinations"), exit 0, no
    warning. `bound` for `bounds` drops the author's declared range the same
    way, and the knob is then scored against the canonical one.

    That is the same failure as a misspelled `wired` name, which this module
    already refuses for the same reason: the misspelling is not a narrower
    document, it is a typo, and reading the document around it scores a claim
    the author did not make. "Ignored whole" was only ever safe for a key that
    means nothing to the scorer, and no such key can be told apart from a
    misspelling of one that means a great deal.

    Nothing is lost by refusing: this repository has never published a config
    space, and the one producer that emits the document
    (`config_space_document` in references/sdk-execution.md) writes declared
    fields only.
    """
    declared = {spec.name for spec in CONFIG_SPACE_FIELDS}
    undeclared = sorted((key for key in document if key not in declared), key=repr)
    if not undeclared:
        return
    described = []
    for key in undeclared:
        near = (
            difflib.get_close_matches(key, sorted(declared), n=1, cutoff=0.6)
            if isinstance(key, str)
            else []
        )
        described.append(f"{key!r} (did you mean {near[0]!r}?)" if near else repr(key))
    raise ConfigSpaceInputError(
        f"config-space document has no field {', '.join(described)}; the "
        f"fields it may declare are {', '.join(repr(n) for n in sorted(declared))}. "
        "A key this schema does not name is a misspelling of one it does, and "
        "reading the document without it scores a claim the document never made"
    )


def agent_facts_from_config_space(document: dict[str, Any]) -> AgentFacts:
    """Read a config-space document, or refuse it naming the field at fault.

    Every field is read by its own entry in `CONFIG_SPACE_FIELDS` and by
    nothing else, so this function holds only what is genuinely *cross*-field.
    There are three such rules, and they run in this order because a rule that
    reads a name must read the name the scorer will use:

    0. **Every key of the document must be a declared field**
       (`_reject_undeclared_fields`). A key the declaration does not name is a
       misspelling of one that it does, and reading the document around it
       scores a claim the author never made.
    1. **Which space spelling is read.** `knobs` wins over its
       `configuration_space` alias only when it is non-empty, and `knobs_key`
       names whichever was actually read, so no message points at a key the
       author never wrote.
    2. **A `wired` or `bounds` name must be a knob of the declared space**
       (`_reject_phantom_names`, applied to each field). Such a name is not a
       narrower space, it is a typo, and it is refused rather than dropped.
    """
    if not isinstance(document, dict):
        raise ConfigSpaceInputError(
            "config-space document must be a JSON object with a 'knobs' key, "
            f"not {type(document).__name__}"
        )
    _reject_undeclared_fields(document)
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
    facts = AgentFacts(
        agent_type=read.get("agent_type"),
        max_trials=read.get("max_trials"),
        knobs=knobs,
        wired=wired,
        bounds=bounds,
        # Reaching this line is the proof: a document was read.
        config_space_supplied=True,
    )
    _reject_synonym_spellings(facts.knobs, knobs_key)
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


# The one place an unexpected failure is allowed to end.
#
# `run` below catches the four input errors it can name and returns 2. Every
# other failure - a `ValueError` from a cap the registries do not know, a
# `KeyError` from a payload shape nobody anticipated, a `TypeError` from a
# field that arrived as a string - escaped to the interpreter, which printed a
# traceback and exited 1. The card never printed at all.
#
# That is the worst possible output for this tool. The person reading it is
# running their first optimization, the traceback names this file rather than
# anything they wrote, and it replaces the one artifact the whole run exists to
# produce. A defect in the checker must not read as a defect in their project.
#
# So the boundary catches broadly and the failure stays loud: named error class,
# its message, a non-zero exit, and nothing pretending a score was computed.
# What it does NOT do is swallow it - the environment variable prints the whole
# stack for whoever is fixing it, which is the audience a traceback was ever
# for. An environment variable rather than a flag because the three scripts
# share this boundary and none of them should grow an option for it.
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
        "than in your project. Nothing was scored, so treat no result as "
        f"reported. Re-run with {TRACEBACK_ENV}=1 and report the output.",
        file=out,
    )
    if env.get(TRACEBACK_ENV):
        traceback.print_exception(type(error), error, error.__traceback__, file=out)
    return INTERNAL_ERROR_EXIT


def main(argv: Sequence[str] | None = None) -> int:
    """The process boundary. See `report_internal_error`."""
    try:
        return run(argv)
    except Exception as error:  # noqa: BLE001 - the boundary is the point
        return report_internal_error("readiness.py", error)


def run(argv: Sequence[str] | None = None) -> int:
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
    except (
        OSError,
        json.JSONDecodeError,
        PreflightInputError,
        ConfigSpaceInputError,
    ) as error:
        print(f"cannot read scoring input: {error}", file=sys.stderr)
        return 2

    dataset_pillar, dataset_caps = score_dataset(dataset_facts, evaluation_facts.method)
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

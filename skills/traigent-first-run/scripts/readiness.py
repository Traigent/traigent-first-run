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
import textwrap
import traceback
from dataclasses import asdict, dataclass, field, replace
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
#
# 3: `weighted_average` is no longer always an average over all three pillars.
#
# Bumped where `provenance_assumption` was not, and the difference is the point.
# That field was purely additive: a consumer ignoring it read every other key
# exactly as before. This one changes what an existing key MEANS. A pillar
# nothing could be measured for is now left out of the average rather than
# averaged in as a zero (`unmeasured_pillars` names which, and is empty in the
# ordinary case) - so a consumer that divides `weighted_average` back out over
# the three declared weights gets a different answer than the one this script
# computed, silently, and only on the runs where the difference matters most.
# Reading the version is how it finds out; reading the new field is how it
# recovers the denominator.
SCHEMA_VERSION = 3
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
#
# One preset is deliberately NOT vendored. `max_tokens` has a canonical range
# upstream and no entry here, because an entry here is what makes a knob
# sweepable: `knob_variation` measures a numeric knob against its range and pays
# for the span. Sweeping `max_tokens` is not a thing this guide will ever ask
# for, so the range it would be measured against is not a number this file
# should hold. See `EXCLUDED_KNOB_REASONS` below for why, and the block above
# `HIGH_IMPACT_KNOBS` for the rule that keeps it out of the generated wrapper.
CANONICAL_RANGES: dict[str, dict[str, float]] = {
    "temperature": {"low": 0.0, "high": 1.0},
    "top_p": {"low": 0.1, "high": 1.0},
    "frequency_penalty": {"low": 0.0, "high": 2.0},
    "presence_penalty": {"low": 0.0, "high": 2.0},
    "similarity_threshold": {"low": 0.0, "high": 1.0},
    "mmr_lambda": {"low": 0.0, "high": 1.0},
    "chunk_overlap_ratio": {"low": 0.0, "high": 0.5},
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

# Knobs that earn no knob-variety credit, each with the reason it earns none.
# A mapping rather than a set because the reasons are not the same reason, and
# the note is printed beside the knob: telling an author their `max_tokens`
# sweep "measures run-to-run variance" would be false, and a false explanation
# is worse than none.
#
# `seed` measures run-to-run variance, not configuration quality.
#
# `max_tokens` earns nothing for a different reason, and saying `seed`'s reason
# beside it would be false: sweeping `max_tokens` does not measure variance, it
# measures whether the answer FIT. Every value of it asks the same question of
# the same agent and differs only in whether the reply survived to be read. That
# is not a behaviour lever - it decides whether an answer exists, not whether it
# is good - and it is worse than uninformative, because driving it down does not
# merely fail to inform the comparison, it corrupts it. A cap that cuts the
# answer off returns `finish_reason == "length"`, which scores 0 rather than
# low, so the model that truncated loses a comparison it may have won. See
# `references/run-safety.md`, which owns why a
# low cap is dangerous and requires the generated wrapper to refuse a truncated
# trial as a non-measurement rather than let it be scored.
#
# Measured before and after, on the space that made the case: `model:
# [o3-mini, gpt-4o-mini]`, `temperature: [0.0, 0.7]`, `prompt_style: [direct,
# structured]` scored the agent pillar 77, and the same space with `max_tokens:
# [256, 512]` added scored 83. Sweeping the one knob that can silently zero the
# best model was worth six points. With the exclusion below both spaces score
# 77, which is the number that was never wrong.
EXCLUDED_KNOB_REASONS: dict[str, str] = {
    "seed": "sweeping this measures run-to-run variance, not quality",
    "max_tokens": (
        "a resource limit, not a behaviour setting - sweeping it measures "
        "whether the answer fit, not whether it was good, and a cap that "
        "truncates scores 0 rather than low"
    ),
}
EXCLUDED_KNOBS = frozenset(EXCLUDED_KNOB_REASONS)

# `model` has a canonical list, but it is OpenAI-only; a user routing through
# OpenRouter or Bedrock overlaps it at zero. Score breadth, never coverage.
#
# These are also the knobs that keep a LADDER instead of the flat categorical
# credit below (`MODEL_BREADTH_LADDER`): every one of them names a model, and a
# model is the one categorical dimension where more choices really is better.
# Two models can only say "this one won"; three - cheap, mid, strong - are what
# it takes to see the cost-for-quality trade the middle rung makes, and that
# trade is the whole finding this guide reports.
OPEN_CATEGORICAL_KNOBS = {"model", "embedding_model", "reranker_model"}

# What a knob with exactly ONE declared value earns, whatever its type.
#
# It adds nothing to the search - every configuration in the space gets that
# same value - so it cannot earn much. But it is not worth nothing either,
# because pinning can be the deliberate, correct decision: `temperature: [0]`
# on a task that has to be reproducible is expertise, not an omission, and the
# author who wrote it down was thinking about the knob. Ten points says "you
# decided this" without ever pretending a decision is a search.
#
# One declared value only. Several values that collapse into one - the numeric
# path's `temperature: [0.1, 0.115]`, both sides of a noise floor - earn zero
# instead, and the difference is the whole point: that author did not pin the
# knob, they tried to sweep it and the sweep does not exist. Crediting the two
# alike would pay for the mistake the noise floor was built to name.
PINNED_KNOB_CREDIT = 0.10

# Breadth credit for a model knob, by how many models it actually compares.
# Three is the intended shape, so it is where full marks sit. Two rates below
# it but well above a pin: comparing two models is real work, just not the
# whole comparison - it can say which of the two won, and cannot say what the
# middle rung costs. The bottom rung is the ordinary pin credit above, because
# a model pinned to one id is pinned in exactly the sense every other knob is.
MODEL_BREADTH_LADDER = {1: PINNED_KNOB_CREDIT, 2: 0.60}
MODEL_BREADTH_FULL = 3

# The agent pillar's ONE sub-score, and why arithmetic over several of them is
# gone.
#
# This is an onboarding guide. The reader is someone running a first
# optimization with their own coding assistant beside them, and the pillar's
# job is to tell them whether there is a search here worth paying for - not to
# grade the taste of their knob choices to two decimal places. Three sub-scores
# became two became one, and the last step is the one that admits what the
# scorer can actually know before a single trial has run.
#
# The size of the space is the measure, because it is the only thing here that
# is both decidable and load-bearing. Ten knobs with one value each is a space
# of one: every trial identical, whatever the catalog says about those ten
# names. Whether four knobs with wide values beat ten knobs with narrow ones is
# not decidable from a JSON document - it is what the run is FOR - so this
# scorer stops pretending to rank it and reports what it can count.
#
# The two sub-scores this replaces:
#
# `knob-count` counted varying knobs on a plateau and then damped the result
# against the trial budget. The damping was the part that carried information,
# and it was about the space, not the count; the count itself answered a
# question nobody has, because four knobs of two values and two knobs of four
# are the same search and scored differently.
#
# `variation` averaged a per-knob quality blend, and one piece of it was
# load-bearing: the numeric noise floor that refuses `temperature:
# [0.1, 0.115]` as a sweep. That piece SURVIVES, and survives in a stronger
# place - it is now inside the count itself, through `effective_values`, so a
# fake sweep does not produce a bigger space rather than producing a bigger
# space and then losing points for it. The rest of the blend - span,
# resolution, endpoint coverage, categorical breadth - is still computed and
# still reported per knob, where a reader can act on "spans 17% of the useful
# 0-2 range". It just no longer pretends to be a fraction of a hundred.
#
# What goes with it is the 55/45 weighting, and the argument for it. Two
# numbers only need weighing against each other while there are two of them.
#
# The qualitative rules the arithmetic used to carry now live in
# `references/sdk-execution.md`, beside the knob catalog, as guidance
# addressed to the assistant - the reader that can check them: values too close
# together are not a sweep, two knobs naming one dimension are one knob, and a
# knob the agent never reads is not a lever. None of the three is decidable
# from the value lists alone, which is why each was either approximated or got
# wrong when it was arithmetic.
SEARCH_SPACE_WEIGHT = 100.0

# A third sub-score, `coverage`, scored `1.0 - missing/len(HIGH_IMPACT_KNOBS[
# agent_type])` out of 25 and is gone. Two things were wrong with it and only
# the first was noticed at the time. The `agent_type` document field went with
# it: selecting that catalog was the only thing it ever did, so once coverage
# was removed the field was read by nothing and is no longer declared.
#
# It restated `knob-count`. The line beside it already reads "4 of 4 wired
# knobs actually vary", so a pillar carrying both charged twice for one fact.
# The rewrite considered - "any knob with 2+ values counts" - would have made
# the restatement exact rather than approximate, which is why it was dropped.
#
# The second is worse, and it is measured. `present` was built from `scoreable`,
# which includes PINNED knobs, so coverage graded whether the catalog names
# appeared in the document, not whether anything was tuned. A space declaring
# `model: [a], temperature: [0], prompt_style: [direct]` - every configuration
# identical, `agent-no-varying-knobs` firing on the same card - scored coverage
# 25/25, full marks, from the sub-score displayed to the customer as "the
# settings that matter most". It was not a redundant measure of the right
# thing; it was a confident measure of the wrong thing.
#
# And it punished better knobs. Measured on the scorer this branch replaces,
# with the shapes stated so both sides can be re-derived - the previous figures
# here were 90 and 78, and named no shape, which is how they survived being
# unreachable:
#
#   {model: 3 values, temperature: [0.0, 1.0], prompt_style: 2 values}
#     - the general catalog, exactly - coverage 25/25, pillar 91
#   {model: 3 values, thinking_shape / reflect / self_consistency: 2 each}
#     - coverage 8.33/25, pillar 83, evidence `not tuning: temperature,
#       prompt_style`
#
# Eight points for bringing four levers instead of three, and an evidence line
# telling the customer to sweep the knob this guide now pins at 0 and calls
# surface noise. The gap is smaller than 78 claimed and the direction is the
# whole argument; 78 was not merely imprecise, it is unreachable - swept
# exhaustively over one to four values on each of those four knobs, that shape
# scores one of {12, 29, 33, 52, 56, 61, 65, 79, 83} and never 78. Narrow the
# temperature sweep to the `[0.0, 0.2]` of this guide's own worked example and
# the catalog shape scores 85, so the gap is two - the penalty for better knobs
# is real at every width, and its size depends on a value the catalog shape
# happens to carry, which is itself the argument against scoring names.
#
# The other two went the same way and for a related reason - see
# `SEARCH_SPACE_WEIGHT` above. What is worth recording here is that a
# re-weighting was drafted first, 35:40 became 55:45, and it was the wrong
# repair. The argument for 55:45 was that `variation` had stopped
# discriminating once categorical breadth earned full credit at two values, so
# `knob-count` had to carry more - which is a description of one sub-score
# measuring nothing, answered by paying the other one more. The weighting
# question only exists while there are two numbers to weigh.

# Below these deltas two values are the same configuration in practice.
NOISE_FLOORS: dict[str, float] = {"temperature": 0.05, "top_p": 0.05}
DEFAULT_NOISE_FRACTION = 0.02
FULL_SPAN_FRACTION = 0.6
ENDPOINT_TOLERANCE_FRACTION = 0.05

# Which knobs are worth searching, by kind of agent. Nothing in this scorer
# selects among these keys any more: `coverage` was the only sub-score that
# read one, and the `agent_type` field that chose it went with it. The catalog
# stays because it is not a scoring input - it is the list the enhanced run
# picks the customer's knobs from, and a human or an assistant reading this
# file chooses the row. That is also why the keys are kept as three separate
# rows rather than flattened into one list: a RAG agent and a code-generation
# agent genuinely want different levers, and the distinction is still true
# even though no code branches on it. Anything reintroducing a *scoring* use
# of these keys needs a document field to select one, which no longer exists.
#
# `max_tokens` is deliberately absent from every catalog in this file: the
# high-impact catalogs below, and `CANONICAL_RANGES`, `OPEN_CATEGORICAL_KNOBS`,
# `NOISE_FLOORS` and `KNOB_SYNONYMS` above. Those catalogs are the
# recommendation path - an assistant composing a space reads them to decide what
# is worth tuning - so a knob named in any of them is a knob this guide
# proposes. `EXCLUDED_KNOB_REASONS` then refuses it credit if an author declares
# it anyway. Absent from the catalogs, never refused in a document: the rule
# constrains what this guide PROPOSES, never what the customer is allowed to
# write.
#
# No floor is enforced here, and none can be. How much room an answer needs is
# not predictable from a config-space document - hidden reasoning tokens are
# spent before the answer text and nothing declares how many - so any floor is a
# guess, and a guess that REFUSES a configuration breaks a run that would have
# been fine. `2048` would be absurd for an agent whose expected answer is `a`,
# `b`, `c` or `d`. The honest instrument is detection, not prediction: the
# generated wrapper refuses a trial the provider reports as truncated, which is
# a fact rather than a forecast.
#
# Nor does any cap get introduced. `references/run-safety.md` owns that rule and
# the generated wrapper it describes sends no `max_tokens` at all; the danger it
# closes is a cross-run one, which is why no single run could show it. A cap sized to
# the baseline's medium model is a cap the enhanced run's stronger or reasoning
# model can exceed, so the truncation would be introduced BY this guide, between
# two runs, on a configuration the customer never chose.
#
# The `max_tokens` exclusion above is a rule with an enforcer, not merely a note
# about a table nothing reads: #168 landed here first, so the `CANONICAL_RANGES`
# entry that still earned the knob credit through `knob_variation` is gone and
# the knob is refused outright. #182 removed the `coverage` sub-score that used
# to read the catalog above, and #185 removed the `agent_type` field that chose
# a row in it - both are in this tree, so nothing selects among these rows now.
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
    # Not `connect-real-data`. The dataset is *assumed* generated because no row
    # said otherwise, and the customer may already have collected the rows and
    # simply never labelled them - in which case the remedy is a field, not a
    # data-collection project.
    "dataset-undeclared-provenance": "declare-data-provenance",
    "dataset-mostly-undeclared": "declare-data-provenance",
    "dataset-generated-answer-key": "review-answer-key",
    # The same remedy as the rung above, deliberately: both say a person has to
    # look at the answer key before the number means anything, and a consumer
    # already routing `review-answer-key` needs no second slug for "most of it"
    # against "all of it". A second spelling for one remedy is the drift this
    # table exists to remove.
    "dataset-mostly-generated-answer-key": "review-answer-key",
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
    # #165's two rungs, reached by silence rather than by a declaration. Same
    # ceilings as the declared pair above and a DIFFERENT category, which is
    # #165's own point: the remedy is `declare-data-provenance`, and declaring
    # is a change the user makes to their file. #149's rule reads that as a
    # repair, so these stop the run where the declared pair does not - and
    # #165's adapter tests assert exactly that (BLOCKED, `connect-real-data`
    # once declaring can no longer lift the ceiling). Registered here because
    # `Cap.__post_init__` fails closed and #144 wrote this table without them.
    "dataset-undeclared-provenance": CREATION_OR_REPAIR,
    "dataset-mostly-undeclared": CREATION_OR_REPAIR,
    "dataset-generated-answer-key": CLAIM_SCOPING,
    # #161's second rung. It scopes for the same reason the rung above
    # does - the questions are real and only part of the ruler is a
    # model's - and it is registered here because `Cap.__post_init__`
    # fails closed on an unclassified condition: #161 added the cap and
    # #144 added the registry, and neither branch could see the other.
    "dataset-mostly-generated-answer-key": CLAIM_SCOPING,
    # #177's row-level sanity check, registered here for exactly the reason the
    # two rungs above are: `Cap.__post_init__` fails closed on an unclassified
    # condition, #144 wrote this table, and #177 wrote the cap against a base
    # that had neither this registry nor `CAP_SEVERITY_ORDER`. Neither branch
    # could see the other, and the merge is the first tree where both exist.
    #
    # `CLAIM_SCOPING`, with the same argument its `review-answer-key` siblings
    # carry: the remedy is a question put to the customer about material that
    # may be perfectly good, not a change they must make first. #187 makes that
    # explicit by giving the cap `blocks=False` and `asks=True`, and the guard
    # below refuses any non-scoping route that does not block - so this is the
    # only category the merged behaviour admits.
    "dataset-unsound-expected-outputs": CLAIM_SCOPING,
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
    # Back to CREATION_OR_REPAIR, where #149 first put it, and #201 is what
    # makes that right again rather than a revert.
    #
    # This condition carried three caps and now carries two. #144 added a third
    # that fired when no config-space document reached the score at all - a
    # ceiling for a state where nothing in the customer's project was broken -
    # and CLAIM_SCOPING was the only category that could hold a blocking pair
    # and an advisory single together. #201 deleted that third branch: an
    # unmeasured pillar is now left out of the average instead of ceilinged, so
    # there is no longer an advisory reading of this condition to accommodate.
    #
    # What is left is two caps that both block and both name a repair: a
    # settings document listing nothing, and one listing settings while marking
    # none of them as ones the agent uses. Both are `vary-knobs`, both wait.
    # Leaving CLAIM_SCOPING here would say this condition can bound a claim
    # while the run proceeds, which is now true of none of its branches.
    "agent-no-varying-knobs": CREATION_OR_REPAIR,
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
            # Identical ceilings to the pair above, deliberately: the
            # assumption IS "generated", so the claim the run may make is the
            # same one. What differs is the remedy - a customer who has real
            # data and never labelled it is asked to declare, not to go and
            # collect - and the remedy is not what this table ranks.
            ("dataset-undeclared-provenance", FULLY_SYNTHETIC_CEILING),
            ("dataset-mostly-synthetic", MOSTLY_SYNTHETIC_CEILING),
            ("dataset-mostly-undeclared", MOSTLY_SYNTHETIC_CEILING),
            ("dataset-unsound-expected-outputs", UNSOUND_ANSWER_CEILING),
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
    # And the same on the undeclared rungs, which grade the same mass reached
    # by silence rather than by a declaration.
    ("dataset-undeclared-provenance", "dataset-mostly-undeclared"),
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
    # #177's cap, answered in #188's own words: it and the provenance
    # conditions "both belong to 'bounded claim' and neither implies the
    # other". Declared here rather than left silent because this registry
    # refuses silence - #177 and #188 were both written against a base without
    # it, so the answer existed in their prose and nowhere a guard could read.
    "dataset-unsound-expected-outputs": (
        "a dataset can be mostly generated with a sound answer key, or fully "
        "collected with a wrong one, so it narrows no provenance condition and "
        "none narrows it"
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
    "search-space": "how many settings-combinations there are to try",
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
class ProvenanceAssumption:
    """What this score assumed about silent rows, and what it cost.

    An assumption a customer only discovers after paying is not an assumption,
    it is a trap - so the one this scorer makes is carried in the payload beside
    the number it produced, and rendered on the card rather than left to a
    reference. `if_declared_collected` is the same evidence scored again with
    these rows counted as collected; it is computed, never estimated, because a
    number a customer is invited to act on has to be the one they would get.
    """

    undeclared_rows: int
    scored_rows: int
    # The two grades: what this run scored under the assumption, and what the
    # identical evidence scores once the silent rows declare a collected source.
    scored_as_generated: int
    if_declared_collected: int


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
    # The pillars left OUT of `weighted_average`, because nothing in them was
    # observed and nothing in them was withheld (see `nothing_was_looked_at`).
    # Empty on the ordinary run, and empty is the honest default: a consumer
    # that never reads this key still divides the average over the right weights
    # on every score where the two agree.
    #
    # It is a key rather than a derivation for the same reason
    # `provenance_assumption` is. A consumer CAN re-derive it from `pillars`,
    # and re-deriving is how two implementations of one rule drift - especially
    # this rule, whose whole content is a distinction between two kinds of
    # unmeasured that a `confidence` of 0.00 does not express.
    unmeasured_pillars: tuple[str, ...]
    gaps: tuple[str, ...]
    # `None` when no row was silent, which is the ordinary case: there is no
    # assumption to disclose, so nothing is printed. Additive, so a consumer
    # reading schema 2 keeps working; it gains a key it can ignore.
    provenance_assumption: ProvenanceAssumption | None = None


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
    # Whether one expected answer dominates the dataset - as a preflight status,
    # not a boolean. It replaced `ceiling_risk: bool`, where False meant both
    # "checked, no dominant answer" and "never checked": under a reference-free
    # evaluator preflight skips the whole expected-output branch, so the check
    # never runs, and the card still printed "no single answer used by most
    # rows". A status can say "did not run", and `diversity_state` below reads
    # anything outside PASS/WARN/FAIL as exactly that.
    answer_dominance_status: str | None = None
    split_overlap: bool = False
    integrity_failed: bool = False
    # True only when EVERY row is generated. Mixtures are read from the counts
    # below; asking "is this dataset synthetic" of a mixture has no true answer.
    synthetic: bool = False
    generated_outputs: bool = False
    # Row counts by provenance class. All zero means the preflight JSON predates
    # them, and `score_provenance` reads `sources` instead rather than taking
    # the absence for an empty dataset. That fallback reaches the same verdict
    # the counted path reaches, NOT the one the older payload used to get: a
    # payload declaring `unknown` scored 6.0 under no ceiling and now scores 3.0
    # under a blocking 65, because the rule is about what silence means and not
    # about which payload shape carried it.
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
class DiscoveredKnob:
    """One parameter the agent's own code exposes, and whether it can be searched.

    Read out of the agent by the assistant, not out of a Traigent document -
    which is why every field that decides credit is a fact about the code, and
    why `evidence` is required rather than nice to have. The rule this class
    exists to enforce is the owner's: score the space that is genuinely
    reachable, never one we invented. A parameter with no citation is not a
    parameter this score has seen.

    `reachable_values` is deliberately a FLOOR, not an estimate, and the two
    kinds get it for different reasons.

    A categorical parameter is counted at the number of values actually
    available - the model ids configured, the prompt strategies the code
    branches on - because those are countable things that exist. Two is the
    minimum that means anything: one option is not a choice, which is exactly
    the rule `categorical_breadth` already applies to a declared knob.

    A numeric parameter is counted at 2 and never more, however wide its range,
    because how many points a search would take inside that range is a decision
    nobody has made yet. Two is what the range itself establishes: a span wider
    than this scorer's own noise floor contains at least two values a run could
    tell apart. Counting a continuous range as "many" would be the invention the
    owner's rule refuses, and it is also how a space grows by declaring values
    nothing can distinguish - the defect `noise_floor` exists to refuse.
    """

    name: str
    kind: str
    reachable_values: int
    evidence: str
    # Empty when the parameter earns credit. Otherwise the reason it does not,
    # said to the reader rather than dropped: an author who wrote down a
    # parameter and saw it silently ignored learns nothing about why.
    uncredited_reason: str = ""

    @property
    def credited(self) -> bool:
        return not self.uncredited_reason


@dataclass(frozen=True)
class AgentFacts:
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
    # What the assistant read out of the agent's own source: the parameters it
    # can already vary, each with the line that shows it can.
    #
    # A SECOND input, never a substitute for the first, and the separation is
    # the safety property. A config-space document carries a `wired` list, which
    # is an attestation that the agent consumes those knobs; the guide refuses a
    # historical one as current wiring (SKILL.md, run-safety.md) and that refusal
    # is untouched here. This input attests nothing about wiring and is never
    # read as though it did: `wired` stays `None`, `knobs` stays empty, and a
    # supplied config-space document wins outright. What it answers is the
    # different question the opening card had no answer to at all - how much
    # there is to search - and it answers it from the code rather than from a
    # document nobody has written yet.
    discovered: tuple[DiscoveredKnob, ...] = ()
    # Whether that read happened, as distinct from what it found. Same line
    # `config_space_supplied` draws one field up: "nothing was looked at" and
    # "the look found nothing" are different findings and get different
    # sentences.
    discovery_supplied: bool = False


def round_half_up(value: float) -> int:
    """Round .5 away from zero.

    `round()` uses banker's rounding, which surprises a reader at a band
    boundary: round(74.5) is 74, not 75.
    """
    return int(math.floor(value + 0.5))


def band_for(
    score: int,
    confidence: float,
    weakest_pillar_confidence: float | None = None,
    *,
    pillar_excluded: bool = False,
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
    # A pillar left out of the average is thin evidence by the same argument,
    # and it is the one shape the two confidences above cannot see: `aggregate`
    # excludes the pillar from both, so a run scored on two fully-observed
    # pillars reports 1.00 coverage and 1.00 for its weakest - a perfect
    # evidence record for a score computed without a third of the picture.
    #
    # This guard exists to refuse exactly that trade. Renormalizing is the right
    # arithmetic, because averaging in a zero nobody measured states something
    # false about the project; presenting the result as EXCELLENT is a different
    # claim, and the missing pillar is the reason it may not be made. So the
    # number renormalizes and the band does not follow it up (#201).
    if thinnest >= MIN_CONFIDENCE_FOR_TOP_BANDS and not pillar_excluded:
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


def categorical_breadth(name: str, distinct: int) -> float:
    """Breadth credit for a knob scored on its value list alone.

    A closed categorical knob earns FULL credit at two or more values. The old
    `(distinct - 1) / 2` scored two values at 50%, and that 50% was an
    assertion this scorer is in no position to make: it says a third value
    exists and would have been better. For a categorical knob there is usually
    no way to know how many values exist. `thinking_shape` might be direct and
    chain-of-thought, or those plus tree-of-thought, or those plus
    graph-of-thought and whatever is published next - so any denominator picked
    here is a guess about a list nobody wrote down, and a guess that
    systematically underprices an honest two-value comparison. Two distinct
    values means the dimension is genuinely being explored, which is the only
    thing this sub-score set out to measure.

    Model knobs are the exception, and `OPEN_CATEGORICAL_KNOBS` explains why
    they alone keep a ladder.

    One value is `PINNED_KNOB_CREDIT` for every name, model or not - the same
    rung the numeric path grafts on for the same reason.

    Numeric knobs never reach this function's flat rule at two or more values:
    a numeric knob with no canonical range and no caller bounds keeps the old
    `(distinct - 1) / 2`, because for a number the "how many more are there"
    question the paragraph above calls unanswerable has an answer - infinitely
    many, between any two of them - and breadth is standing in for a span this
    scorer cannot compute. Scoring an unbounded `retrieval_depth: [1, 2]` at
    100% would hand out exactly the narrow-sweep credit the numeric path exists
    to withhold.
    """
    if distinct < 2:
        return PINNED_KNOB_CREDIT
    if name in OPEN_CATEGORICAL_KNOBS:
        if distinct >= MODEL_BREADTH_FULL:
            return 1.0
        return MODEL_BREADTH_LADDER[distinct]
    return 1.0


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

    if name in EXCLUDED_KNOB_REASONS:
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
            # The knob's own reason, not one shared reason: `seed` and
            # `max_tokens` earn nothing for different causes, and printing the
            # wrong cause beside a knob is a false explanation.
            notes=(EXCLUDED_KNOB_REASONS[name],),
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
            # The pin rung, grafted on rather than replacing anything: span,
            # resolution and coverage are all still honestly zero, and this
            # knob still does not count as varying. Only for a knob the author
            # declared with ONE value - `temperature: [0]` is a decision, and
            # `temperature: [0.1, 0.115]` is a sweep that does not exist.
            pinned_quality = PINNED_KNOB_CREDIT if distinct < 2 else 0.0
            return KnobScore(
                name=name,
                kind="numeric",
                distinct_values=distinct,
                effective_values=len(effective),
                span=0.0,
                resolution=0.0,
                coverage=0.0,
                quality=pinned_quality,
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
            quality=categorical_breadth(name, distinct),
            span_ratio=None,
            notes=tuple(notes),
        )

    # Categorical, boolean, or numeric without a canonical range: breadth is the
    # only honest signal.
    #
    # A CATEGORICAL knob with two or more values is being genuinely explored and
    # scores full breadth - see `categorical_breadth` for why the old
    # `(distinct - 1) / 2` was pricing a denominator it could not know. A NUMERIC
    # knob with no canonical range keeps that old formula, because there the
    # denominator is not unknowable, it is unbounded, and full marks for two
    # values would be the narrow-sweep credit the numeric path withholds.
    quality = (
        min(1.0, (distinct - 1) / 2.0)
        if numeric
        else categorical_breadth(name, distinct)
    )
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
SYNTHESISED_ROW_POINTS = 3.0  # neither was observed
# A row that says nothing is scored as a row that says generated. Defined AS
# the synthesised credit rather than repeating 3.0, because the two are one
# decision: silence is an assumption, and the assumption is the pessimistic one.
#
# It used to score 6.0 and carry no ceiling, which paid for silence. Measured on
# 200 identical rows differing only in whether `provenance` was present: declared
# synthetic scored 65 and BLOCKED the paid run, the same rows with the field
# removed scored 91 and OK. Twenty-six points and a block, for telling the truth.
#
# The assumption is never silent in return - `main` re-scores the same evidence
# with these rows counted as collected and prints both numbers, so a customer
# reads what they scored under the assumption and what declaring would earn.
UNDECLARED_ROW_POINTS = SYNTHESISED_ROW_POINTS

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
# The reasons for the same two rungs of that ladder, reached by silence instead
# of by a declaration. The ceilings are identical because the assumption IS
# "generated"; what differs is the remedy, and it has to. `connect-real-data` is
# the wrong instruction for a customer who already has real data and never
# labelled it, and reading silence as a declaration is what made staying quiet
# the cheaper move.
#
# The reasons are named here and the conditions are written out at each `Cap(`
# below, rather than splatting one tuple: two separate guards read the condition
# strings straight out of this file's source, and a cap built from a variable is
# a cap they stop seeing.
#
# Both reasons describe a corpus that HAS declared-generated rows in it as well,
# so neither claims the dataset declared nothing at all, and neither asks for a
# declaration on rows that may not exist. "Declare the rows that were collected"
# was both: it read as "nothing here is declared" beside a corpus that was
# largely declared generated, and it instructed a reader with no collected rows
# to declare rows they do not have. The instruction is conditional instead,
# because whether any silent row was collected is the one thing this scorer
# cannot see and the reader can.
# "records nothing this run could read" and not "records nothing": a row
# carrying a word the vocabulary does not know is in the same position as a
# silent one - this script cannot tell what it came from - and it is now scored
# there, so the sentence has to describe both or it is false on the card of
# every customer using their own vocabulary.
UNDECLARED_ALL_REASON = (
    "No row of this dataset was observed - every row is either declared "
    "generated, or records no source this run can read, and a row whose source "
    "it cannot read is scored as generated. Declare or re-label the source on "
    "any such row that was collected; if none was, this dataset is generated."
)
UNDECLARED_MOST_REASON = (
    "More than half of these rows were never observed: they are declared "
    "generated, or record no source this run can read and are scored as "
    "generated. Declare or re-label the source on any such row that was "
    "collected."
)
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

    Reads `sources` instead when the counts are absent, which is what a preflight
    JSON written before this field looks like - the absence is a payload shape,
    not an empty dataset. That path reaches the same verdict as the counted one
    and NOT the verdict it used to reach: `unknown` scored 6.0 under no ceiling
    and now scores 3.0 under a blocking 65, because the rule is about what
    silence means rather than about which payload carried it.
    """
    caps: list[Cap] = []
    counted = facts.collected_rows + facts.synthesised_rows + facts.undeclared_rows
    undeclared_rows = facts.undeclared_rows
    synthesised_rows = facts.synthesised_rows
    if not counted:
        # A fact set with rows in it and no per-row provenance count says
        # nothing about where any row came from - which is precisely what an
        # undeclared row says - so it is scored there, in two lines.
        #
        # What used to be here was forty: a second implementation of this whole
        # ladder that re-derived it from `sources`, with its own helper
        # (`declares_no_provenance`), its own counterfactual token
        # (`COUNTERFACTUAL_SOURCE`) and its own branch in
        # `provenance_assumption`. Its stated purpose was a preflight JSON
        # written before the counts existed. `emit_dataset_provenance` emits
        # all three counts together for every dataset with a row in it, and
        # this repository has published nothing that could have been written
        # before that - so the machinery guarded a payload that has never
        # existed, and any real one that reaches this line is truncated. The
        # adapter refuses that one at the boundary; here the fail-closed
        # reading is enough, and it is the same reading a silent row gets.
        # `synthetic` is preflight's own all-or-nothing statement about the
        # same rows and is kept, so a count-free fixture that says every row is
        # generated is still scored generated rather than merely unread.
        counted = facts.rows
        if facts.synthetic:
            synthesised_rows = facts.rows
        else:
            undeclared_rows = facts.rows

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
        + undeclared_rows * UNDECLARED_ROW_POINTS
        + synthesised_rows * SYNTHESISED_ROW_POINTS
    ) / counted

    # The ladder runs on how much of the corpus was never observed, and an
    # undeclared row counts there: it is scored as generated, so it is capped as
    # generated. Half declared-collected and half silent is 50%, under the
    # threshold, so it is not capped at all: it loses points per row like any
    # mixture. Half declared-generated and half silent is 100% unobserved and IS
    # capped, at 65, even though neither half reaches 100% on its own - which is
    # the case the two shares could not see separately.
    unobserved = synthesised_rows + undeclared_rows

    # WHICH of the two remedies that ceiling carries is a share too, not the
    # existence of a silent row. `undeclared_rows > 0` handed "declare the rows
    # that were collected" to any corpus with one silent row in it, including a
    # corpus that is overwhelmingly DECLARED generated - which is the wrong
    # remedy this pair of conditions exists to prevent, in mirror image.
    # Measured on 50 collected / 260 declared-generated / 90 silent: the reader
    # was told to declare, declared all 90, scored the same 70, stayed BLOCKED,
    # and was only then handed `connect-real-data` - the instruction they needed
    # first.
    #
    # The threshold is the ceiling's own, and it is chosen because it is exactly
    # the condition under which declaring changes the answer. Moving every
    # silent row into the collected count leaves `synthesised_rows` as the whole
    # unobserved mass, so declaring clears both rungs if and only if the
    # DECLARED generated rows are at most `MOSTLY_SYNTHETIC_SHARE` of the
    # corpus. Past that they hold the ceiling down on their own, no declaration
    # can lift it, and the honest first instruction is to connect real data -
    # while the silent rows stay named in the evidence line and in the
    # disclosure sentence, so nothing about them is hidden by routing the
    # remedy at the mass that actually binds.
    silent = (
        undeclared_rows > 0 and synthesised_rows <= counted * MOSTLY_SYNTHETIC_SHARE
    )
    if unobserved == counted:
        caps.append(
            Cap(
                "dataset-undeclared-provenance",
                FULLY_SYNTHETIC_CEILING,
                UNDECLARED_ALL_REASON,
            )
            if silent
            else Cap(
                "dataset-fully-synthetic",
                FULLY_SYNTHETIC_CEILING,
                "The dataset is generated, so a high score here measures the "
                "walkthrough, not real-world readiness.",
                blocks=False,
            )
        )
    elif unobserved / counted > MOSTLY_SYNTHETIC_SHARE:
        # Without this the any()->all() correction would hand every mixture a
        # free pass: a 90%-generated dataset would lose its ceiling entirely.
        caps.append(
            Cap(
                "dataset-mostly-undeclared",
                MOSTLY_SYNTHETIC_CEILING,
                UNDECLARED_MOST_REASON,
            )
            if silent
            else Cap(
                "dataset-mostly-synthetic",
                MOSTLY_SYNTHETIC_CEILING,
                "Most of the dataset is generated, so the result mostly "
                "measures invented examples rather than real traffic.",
                blocks=False,
            )
        )

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
    # `unobserved != counted`, not `synthesised_rows != counted`: #165 widened
    # this premise and #161 rewrote the body under it, so the merge takes both.
    # "The questions are still real" is the whole basis of this ceiling, and it
    # is false for a corpus where no row was observed - whether the rows say
    # "generated" or say nothing at all. The 65 governs there and says strictly
    # more.
    if uses_expected_outputs and unobserved != counted:
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
            replace(
                facts,
                synthesised_rows=synthesised_rows,
                undeclared_rows=undeclared_rows,
            ),
            counted,
            uses_expected_outputs=uses_expected_outputs,
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
            "; provenance tokens this run could not verify, scored as "
            "undeclared rather than as collected: "
            f"{', '.join(facts.unrecognised_sources)}"
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
        # "does not record where it came from" was false of exactly the row
        # this line most often describes. A row carrying `provenance: "n/a"`
        # DID record something - `n/a` is in `UNDECLARED_SOURCE_TOKENS` - and
        # the same line then prints `declared sources: n/a`, so the card told
        # the reader the row recorded nothing directly beside what it recorded.
        # The glossary's entry was corrected for this; the card, which is what
        # the customer actually reads, kept the sentence. Say what is true of
        # both rows that reach here: no field at all, and a non-answer in one.
        mixture += (
            " (undeclared means the row names no real source this run can "
            "read - no provenance field at all, a non-answer such as n/a, or "
            "a word its vocabulary does not know - so this run scores it as "
            "generated)"
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
        # Only when there is a source to name. Preflight used to substitute the
        # literal `unknown` for a row carrying no provenance field, so this line
        # printed `declared sources: unknown` about a declaration nobody made,
        # directly after the clause saying the rows declare nothing. With the
        # substitution gone the list is genuinely empty in that case, and the
        # mixture clause above already says so.
        if facts.sources:
            return (
                f"{mixture}; declared sources: {', '.join(facts.sources)}"
                f"{unverified}"
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


NEAR_DUPLICATE_PERCENT = 90


@dataclass(frozen=True)
class DiversityCheck:
    """One question the diversity sub-score asks, and what answering it costs.

    `detectors` are every preflight record that can raise this question's
    finding. `certifier` is the single record allowed to CLEAR it. The two
    differ because a detector can be cheaper than the question it serves: it
    can say "there is a problem" without being able to say "there is none".
    """

    detectors: tuple[str, ...]
    certifier: str
    # Two labels, because the same question needs a different noun in the two
    # sentences: what it FOUND ("one expected output dominates") is not what it
    # was LOOKING FOR ("whether one expected output dominates"), and reusing the
    # first in the unchecked line reads as a finding the check never made.
    found_label: str
    looking_for_label: str
    # What it says when it ran and found nothing. A third label rather than a
    # negation of the first, because "no rows at least 90% similar to another
    # row" is not English a first-time reader gets on one pass.
    clean_label: str
    points: float
    # Whether this question has a subject at all when the evaluator needs no
    # reference answer. A question with no subject is not an unrun check.
    needs_expected_outputs: bool = False


# The questions the diversity sub-score speaks for, each with the points it is
# worth and the words the card uses.
#
# They are listed rather than inlined because the rule below has to hold for all
# of them identically, and the defect this table exists to prevent was one of
# them being handled by a test the others did not get.
#
# ONE deduction for repetition, not two. `dataset-duplicates` (byte-identical
# after normalization) and `dataset-near-duplicates` (Jaccard >= 0.9) both fire
# on the same duplicated row, because two identical token sets have similarity
# exactly 1.0 - so a single copied row used to cost 7 + 7 of the 20 diversity
# points for one defect described twice. The owner's decision is that the
# near-duplicate check subsumes the exact one for scoring: >= 90% similar is
# already the finding, and 100% needs no second one (traigent-first-run#158).
#
# The exact check is kept as a DETECTOR rather than deleted, because it can
# answer where the near scan cannot. It is a hash bucket - O(n), always
# complete - while the near scan is a bounded join that emits SKIP when it
# passes its comparison budget. On that dataset the exact check is the only
# thing still able to raise repetition at all, so it feeds the same single
# deduction. What it may never do is CLEAR the question: "no byte-identical
# rows" is not "no rows 90% alike", so `certifier` is the near check alone.
DIVERSITY_CHECKS: tuple[DiversityCheck, ...] = (
    DiversityCheck(
        detectors=("near_duplicate_status", "duplicate_status"),
        certifier="near_duplicate_status",
        found_label=(f"rows at least {NEAR_DUPLICATE_PERCENT}% similar to another row"),
        looking_for_label=(
            f"whether rows repeat each other at {NEAR_DUPLICATE_PERCENT}% "
            "similarity or more"
        ),
        clean_label=(
            f"no repeated questions at {NEAR_DUPLICATE_PERCENT}% similarity or more"
        ),
        points=7.0,
    ),
    DiversityCheck(
        detectors=("answer_dominance_status",),
        certifier="answer_dominance_status",
        found_label="one expected output dominates",
        looking_for_label="whether one expected output dominates",
        clean_label="no single answer used by most rows",
        points=6.0,
        # Under a reference-free judge there are no expected outputs, so this
        # question has no subject - it is not a check that did not run, it is a
        # check that does not apply. Scoring it as "did not run" discarded the
        # near-duplicate PASS beside it and put the whole sub-score into the
        # unmeasured branch: a 40-row input-only dataset measured DATASET
        # 81/100 (3 of 5 checks) before this branch and 70/100 (2 of 5) after,
        # a false red on a configuration the guide fully supports.
        needs_expected_outputs=True,
    ),
)
# A preflight status only counts as evidence when it is one of these. Everything
# else - SKIP, an absent record, a status this scorer does not know - means the
# check did not establish anything.
MEASURED_STATUSES = frozenset({"PASS", "WARN", "FAIL"})


def diversity_subscore(
    facts: DatasetFacts, *, uses_expected_outputs: bool = True
) -> SubScore:
    """Score duplication and answer dominance, claiming only what actually ran.

    `uses_expected_outputs` is the same context `score_provenance` takes on the
    adjacent line, and it was the one this function did not get. Without it,
    "cannot apply" and "did not run" were the same answer here, which is the
    defect this function exists to remove pointed the other way.

    One rule, and it is the whole point of this function: a check that did not
    run must never read as a check that passed.

    `SKIP` used to fall through the `in ("FAIL", "WARN")` test that decides
    whether to deduct, so a skipped check kept its full points AND the sentence
    "no repeated questions, and no single answer used by most rows" - a clean
    bill of health for something nobody looked at. Two checks reached the card
    that way: near-duplicates above 500 rows, and answer dominance under a
    reference-free evaluator (traigent-first-run#151).

    A question is answered by its `certifier` and only by it. Its other
    detectors can raise a finding but cannot pronounce it clean, which is what
    lets the exact-duplicate check keep earning its place after the
    near-duplicate check took over the scoring: on a dataset where the near
    scan ran out of budget, an exact duplicate is still a found problem, while
    an exact PASS leaves the 90%-similarity question genuinely unasked.

    So there are three outcomes, not two:

    * A problem was found. Deduct for it, stay measured, and name the checks
      that did not run beside it. Staying measured matters - marking the
      sub-score unmeasured would delete a real finding, and `combine`
      renormalizes over what is measured, so deleting it would RAISE the pillar.
    * Everything that ran was clean, and everything ran. Full points.
    * Everything that ran was clean, and something did not run. There is no
      clean claim to make, so the sub-score is unmeasured: excluded from the
      score, marked on the card, and counted against evidence coverage.

    The third case cannot inflate the pillar either. An unmeasured sub-score
    leaves the pillar equal to its other checks, and a full-marks sub-score is
    the one whose removal can only hold the average down or leave it unchanged.
    """
    problems: list[str] = []
    unchecked: list[str] = []
    earned = 20.0
    # A check whose subject this run does not have is not part of the question.
    # It keeps its points - there is nothing here for it to find - and it is
    # never named as unrun, because "we did not look at your expected outputs"
    # is not a gap on a run that has none.
    applicable = [
        check
        for check in DIVERSITY_CHECKS
        if uses_expected_outputs or not check.needs_expected_outputs
    ]
    for check in applicable:
        statuses = [getattr(facts, name) for name in check.detectors]
        if any(status in ("FAIL", "WARN") for status in statuses):
            # Deduct once, however many detectors saw it. Naming each of them
            # would print one defect as a list of findings, which is the
            # arithmetic this table exists to stop.
            earned -= check.points
            problems.append(check.found_label)
        elif getattr(facts, check.certifier) in MEASURED_STATUSES:
            continue
        else:
            unchecked.append(check.looking_for_label)

    not_checked = f"not checked: {', '.join(unchecked)}"
    if len(unchecked) == len(applicable):
        return SubScore("diversity", 0.0, 20.0, False, "duplication was not checked")
    if problems:
        evidence = "; ".join(problems)
        if unchecked:
            evidence = f"{evidence}; {not_checked}"
        return SubScore("diversity", round(max(0.0, earned), 2), 20.0, True, evidence)
    if unchecked:
        return SubScore(
            "diversity",
            0.0,
            20.0,
            False,
            f"{not_checked} - the checks that did run found nothing, which is "
            "not the same as clean",
        )
    # Built from the questions that applied, never from a fixed sentence. A
    # run with no expected outputs must not be told that no single answer
    # dominates them - that was the original defect, and a hard-coded clean
    # line reintroduces it the moment a question stops applying.
    return SubScore(
        "diversity",
        20.0,
        20.0,
        True,
        ", and ".join(check.clean_label for check in applicable),
    )


def score_dataset(
    facts: DatasetFacts,
    evaluator_method: str | None = None,
    review: RowReview | None = None,
) -> tuple[Pillar, list[Cap]]:
    caps: list[Cap] = []
    subs: list[SubScore] = []
    review = review or RowReview()

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
        # Resolution is a property of the TUNING split, and the holdout is
        # exempt from it.
        #
        # This used to take `min(tuning, holdout, ...)`, so the held-out set
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
        # A held-out set with nothing scoreable in it cannot check the winner
        # it exists to check, and taking it out of `effective` above is what
        # stopped that from showing up in the number - so it is said here
        # instead, on the card, where a user can act on it.
        if not reference_free and facts.holdout_labelled_rows == 0:
            prefix = f"{prefix}; none of the held-out rows can be scored"
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

    subs.append(diversity_subscore(facts, uses_expected_outputs=not reference_free))

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


# The search-space ladder, as SHARES of whatever the sub-score is worth, so the
# curve and the pillar weight stay separable. The ladder this replaces was
# written as points out of 35 and read back as points out of 55 when the pillar
# was re-weighted, which silently reshaped it instead of rescaling it.
#
# Every threshold below is a number this guide already uses somewhere else. It
# is a taste guide, and inventing a fresh scale for it would be the same
# mistake as the sub-score it replaces.
#
# The smallest space in which two knobs can interact at all: two binary
# dimensions. Below it the run compares points along one line, which is a
# comparison and not a search.
SEARCH_SPACE_INTERACTION = 4
# `BASELINE_TRIALS` in references/sdk-execution.md. Twelve is what this guide's
# own baseline sweep enumerates exhaustively, and that file says why: it is the
# run whose "job is to rank knobs across all of them". A space this run can
# compare twelve distinct configurations from is a space that does what this
# guide asks of one.
SEARCH_SPACE_FULL = 12
SEARCH_SPACE_ONE_DIMENSION = 0.35
SEARCH_SPACE_PARTIAL = 0.70
# Kept from the ladder this replaces, where it was the one clause carrying
# information about the space rather than about the knob count. Past twenty
# times the budget the search reads under five percent of what it declares, and
# what comes back describes the sample rather than the space.
OVERSIZED_SPACE_FACTOR = 20


def configuration_budget(max_trials: int | None, repeats: int) -> int | None:
    """How many distinct configurations the trial budget actually pays for.

    Not `max_trials`. A run that sweeps three seeds spends three trials on each
    configuration, so twelve trials buy four configurations and not twelve -
    the seed dimension is excluded from what the search can TELL APART and is
    emphatically not excluded from what it COSTS. Dividing here is what keeps
    both true in one number, and it is the relationship the retired ladder
    expressed by damping against the raw trial count.

    `None` when no budget was declared, which is a different statement from a
    budget of zero: nothing bounds the space rather than nothing being tried.
    That distinction is the whole contract of this return type, and `if not
    max_trials` collapsed it - a declared `0` left here as `None` and was
    scored, and described in the evidence line, as "no trial budget was
    declared". `_read_trial_budget` refuses a zero from a config-space
    document, so nothing reached this through the supported path; the test
    below pins it anyway, because `AgentFacts` is constructed directly by
    `build_plan` and by callers that never pass through that reader.
    """
    if max_trials is None:
        return None
    return max_trials // max(repeats, 1)


def search_space_points(configurations: int, budget: int | None) -> float:
    """Score the space by how much of it this run will actually compare.

    Size RELATIVE TO THE TRIAL BUDGET, not size alone, and the two shapes that
    decide it point opposite ways. A thousand configurations against twelve
    trials is worse than forty-eight: the twelve trials are the same twelve
    either way, and the thousand-configuration report describes a sample nobody
    chose. But forty-eight configurations against forty-eight trials is not
    better than forty-eight against twelve by anything this scorer can see
    before a trial has run - which is the whole reason the pillar stopped
    grading knob choices.

    So the credit is read off `min(configurations, budget)` - what the run will
    actually compare - and then damped when the declared space dwarfs it.

    An UNDECLARED budget is damped too, and that is the part an earlier draft
    got backwards. "With no budget there is nothing to be too large for" reads
    as reasoning about the space; it is actually reasoning about the document.
    Nothing in a document that omits `max_trials` establishes that the run will
    compare the whole space - the top rung is a claim that it will - and
    scoring the silence as though it were `max_trials = infinity` made deleting
    a line worth more than writing one.

    Measured on this scorer, one identical 10 000-configuration space:
    `max_trials: 12` scored this pillar 70 and omitting the field scored it
    100, which carried the whole card from 88 STRONG to 96 EXCELLENT. The
    guide's own producer always emits `max_trials` (`BASELINE_TRIALS` and
    `ENHANCED_MAX_TRIALS` in references/sdk-execution.md), so the only document
    the old rule rewarded was one that had dropped the field - and both of this
    guide's own spaces still score 100, because both declare it.

    So an absent budget is capped where an oversized one is: one step below
    complete. Declaring a budget can still score lower than omitting one - a
    declared `max_trials: 1` scores 0 - and that is not the same defect. "This
    run compares one configuration" is a real and bad measurement; silence is
    not a measurement of anything, and is scored as neither.
    """
    # One branch, not two. A space of one configuration and a budget of one
    # trial are the same finding - the run compares nothing - so an early
    # return for the first would be a second spelling of the rung below.
    reachable = min(configurations, budget) if budget is not None else configurations
    if reachable < 2:
        share = 0.0
    elif reachable < SEARCH_SPACE_INTERACTION:
        share = SEARCH_SPACE_ONE_DIMENSION
    elif reachable < SEARCH_SPACE_FULL:
        share = SEARCH_SPACE_PARTIAL
    else:
        share = 1.0
    # Two reasons to refuse the top rung, and neither of them is "the space is
    # small". Written as one `if/elif` on the same `share` so a future edit
    # cannot restore the top rung down one path and not the other.
    if budget is None:
        share = min(share, SEARCH_SPACE_PARTIAL)
    # Compared as integers rather than through `configurations / budget`: both
    # sides are unbounded Python integers, and true division of two large ones
    # raises OverflowError instead of answering the question.
    elif configurations > OVERSIZED_SPACE_FACTOR * budget:
        share = min(share, SEARCH_SPACE_PARTIAL)
    return round(SEARCH_SPACE_WEIGHT * share, 2)


def search_space_shortfall(configurations: int, budget: int | None) -> str:
    """Name the step this run sits under, because the ladder is a step function.

    `search_space_points` takes four values and no others - measured across
    seventeen space sizes against a declared budget, only 0, 35, 70 and 100
    were ever produced. That shape is deliberate and stays: every threshold in
    it is a number this guide already uses (2 to compare anything at all, 4 for
    the smallest space two settings can interact in, `SEARCH_SPACE_FULL` for
    the baseline sweep), and replacing them with a smooth curve would invent a
    scale, which is the exact mistake the retired `variation` sub-score made.

    What does NOT stay is the cliff being silent. A step function means one
    extra value in one knob can be worth a band - measured: 11 compared
    configurations score this pillar 70 and the card 88 STRONG, 12 score it 100
    and the card 96 EXCELLENT - while the sentence beside the number moves by
    one digit and never mentions that a boundary was crossed. So the rung is
    named here, with the distance to the next one, which is the only form of
    this fact a reader can act on.

    Returns a clause to append, or an empty string at the top rung, where there
    is no next step to name.
    """
    reachable = min(configurations, budget) if budget is not None else configurations
    if reachable < 2:
        # `configurations <= 1` is already spelled out by the caller; this is
        # the other way to reach it - a budget too small to compare anything.
        return "" if configurations <= 1 else "; a budget this small compares nothing"
    if reachable < SEARCH_SPACE_INTERACTION:
        needed = SEARCH_SPACE_INTERACTION - reachable
        return (
            f"; {needed} more would reach the {SEARCH_SPACE_INTERACTION} this "
            "guide scores as room for two settings to interact"
        )
    if reachable < SEARCH_SPACE_FULL:
        needed = SEARCH_SPACE_FULL - reachable
        return (
            f"; {needed} more would reach the {SEARCH_SPACE_FULL} this guide "
            "scores as a complete search"
        )
    # At or past the top rung by size, so anything below full credit now comes
    # from the budget rather than from the space - say which, because the two
    # have different repairs and the score alone distinguishes neither.
    if budget is None:
        return (
            "; declaring `max_trials` is what lets this reach full credit - "
            "undeclared, it is held one step below"
        )
    if configurations > OVERSIZED_SPACE_FACTOR * budget:
        return (
            f"; the space is over {OVERSIZED_SPACE_FACTOR}x what that budget "
            "reaches, which holds this one step below full credit"
        )
    return ""


def search_space_evidence(
    configurations: int,
    declared: int,
    repeats: int,
    budget: int | None,
    uncredited: Sequence[str] = (),
) -> str:
    """One sentence a person can act on, which a bare number is not.

    Names the space, then what this run will do with it, then which step of the
    ladder that lands on - because the first is a rewrite, the second is an
    argument, and the third is the one the score actually moves on. The
    collapse is named whenever it happened, or the sentence contradicts a
    document the reader can count for themselves.
    """
    unit = "configuration" if configurations == 1 else "configurations"
    line = f"your space has {configurations} distinct {unit}"
    if declared > configurations:
        line += f" ({declared} declared - values too close to tell apart count once)"
    if configurations <= 1:
        line += "; every trial would be identical"
    elif budget is not None:
        line += f"; this run will try up to {min(configurations, budget)} of them"
    else:
        # Not "the run may try all of them". Nothing here establishes that, and
        # it was the sentence that made the old top-rung score sound earned.
        line += (
            "; no trial budget was declared, so nothing here says how much of "
            "it this run compares"
        )
    if repeats > 1:
        # The knob is NAMED rather than assumed to be `seed`. #189 wrote
        # "each repeated N times over 'seed'" while `seed` was the only
        # excluded knob; #168 added `max_tokens`, and neither branch's CI
        # could see the other. Two `max_tokens` values are also not a repeat
        # of anything - they are two different requests that differ only in
        # whether the reply survived - so the word changes with the knob.
        named = ", ".join(f"'{name}'" for name in uncredited) or "'seed'"
        multiplied = all(name == "seed" for name in uncredited) and bool(uncredited)
        verb = "repeated" if multiplied else "multiplied"
        line += f", each {verb} {repeats} times over {named}"
    return line + search_space_shortfall(configurations, budget)


NOTHING_WIRED_CAP = Cap(
    "agent-no-varying-knobs",
    AGENT_NO_VARYING_KNOBS_CEILING,
    "Nothing is marked as a setting the agent actually uses, so there is "
    "nothing to search.",
)

# There is no third cap here, and its absence is a decision (#201).
#
# `NOT_YET_MEASURED_CAP` used to sit between these two: an advisory ceiling of
# 45 whose own reason said "nothing in your project needs repairing for this".
# It fired on every guided run by construction, because the guide withholds
# every config-space file found before this run's search - so no opening card
# could exceed 45/PARTIAL for any customer, however good their project.
# Measured on the strongest realistic opening project (200 production rows,
# difficulty-tagged, 180/20 split, evaluator calibrated and passing all seven
# probes): dataset 94, evaluation 100, agent 0 at confidence 0.00, weighted
# average 73, overall 45 PARTIAL, with that cap the only one firing.
#
# A ceiling is a statement about the customer's project, and that one was a
# statement about this walkthrough's own sequencing. It is deleted rather than
# reworded, and what replaces it is two things that are each more honest than a
# number: the agent is READ, so the space is usually measured rather than
# missing (`score_discovered_agent`), and where it genuinely cannot be, the
# pillar is left out of the average instead of averaged in as a zero
# (`aggregate`) - which is what README.md has always promised for a check that
# cannot be computed.
#
# The other two caps here are untouched, and the difference is not a matter of
# degree. Both are findings about a document that exists: one lists no settings,
# the other lists settings and marks none of them as ones the agent uses. Those
# are defects in material the customer handed over, and they still block.

UNATTESTED_WIRING_CAP = Cap(
    "agent-no-varying-knobs",
    AGENT_NO_VARYING_KNOBS_CEILING,
    "Settings are listed, but none is marked as one the agent uses - marking "
    "them is what makes them searchable.",
)


def nothing_to_search_pillar(
    evidence: str, *, supplied: bool, withheld: bool = False
) -> Pillar:
    """The agent pillar every "no knob is attested as wired" state reports.

    Three inputs land here: no knobs declared at all, knobs declared with no
    `wired` list, and knobs declared with an explicit empty one. All three
    report score 0, because a space nothing varies in has one configuration
    however the document spells it.

    What separates them is whether a document arrived, and with one sub-score
    that is exactly what `measured` now says. A document that lists nothing, or
    wires nothing, IS a measurement of the search space - it is one
    configuration, read off the file. No document at all is not a measurement
    of anything, and the previous shape claimed it was: `knob-count` was marked
    measured at the opening gate, where this guide deliberately withholds any
    config-space document, so the pillar reported 55% evidence coverage for a
    space nobody had looked at.

    Confidence stays monotonic, which was the constraint an earlier draft
    broke: handing the scorer a config space can never *lower* this pillar's
    confidence. Supplying nothing gives 0.00; supplying a document that lists
    nothing gives 1.00; supplying a real one gives 1.00.

    `withheld` splits the `supplied=False` half in two, and #201 is what made
    the split load-bearing. Both halves score 0 at confidence 0.00; what differs
    is whether that zero counts.

    * Nothing about the agent reached this score - no settings document and no
      read of the agent's source. This run was asked for that evidence, so the
      check is WITHHELD: it keeps its full weight and earns nothing, exactly as
      `--task-kind` and the probe scores do. Measured on the same 200-row
      project, the alternative is not academic - excluding it scored 99 for a
      run that looked at nothing against 92 for a run that read the agent and
      found four parameters. Not looking would have been worth 7 points.
    * The agent WAS read and no varying parameter could be established. Nothing
      further was withheld; the tool looked with the evidence it had and could
      not compute the check. That is the state README.md promises is "marked
      unmeasured and excluded rather than scored zero", and `aggregate` excludes
      it.
    """
    return combine(
        "agent",
        [
            SubScore(
                "search-space",
                0.0,
                SEARCH_SPACE_WEIGHT,
                supplied,
                evidence,
                withheld=withheld,
            )
        ],
    )


def discovered_space_evidence(
    credited: Sequence[DiscoveredKnob], reachable: int
) -> str:
    """What the read of the agent found, as a floor the reader can check.

    Says "at least", every time, and means it. `reachable` multiplies a floor
    per parameter (see `DiscoveredKnob`), so the true space is this number or
    larger and never smaller - and a sentence that dropped the qualifier would
    be asserting a count nobody has chosen the values for.

    Names the parameters rather than counting them. "3 settings" is a number the
    reader cannot check against their own file; `model, temperature, top_p` is a
    list they can, and disagreeing with it is the point - this is a read of
    their code, and a read they can see is a read they can correct.
    """
    named = ", ".join(knob.name for knob in credited)
    unit = "configuration" if reachable == 1 else "configurations"
    return (
        f"read from your agent: {named} can vary, reaching at least {reachable} "
        f"distinct {unit}; no trial budget is declared yet, so this counts what "
        "the agent makes reachable rather than what a run would compare"
    )


def score_discovered_agent(
    facts: AgentFacts,
) -> tuple[Pillar, list[Cap], list[KnobScore]]:
    """Score the search space from the agent's own code (#201).

    The opening gate's answer to "what is there to search", when no config-space
    document exists yet and by the guide's own design never will at this point.

    Two properties hold here that do not hold for a config-space document, and
    both are why this is a separate path rather than a looser reading of that
    one. It attests nothing about wiring, so it clears no wiring cap and cannot
    be mistaken for the `wired` list the guide refuses to inherit. And it has no
    trial budget - the run that would spend one has not been planned - so
    `search_space_points` is asked with `budget=None`, which its own rule
    already damps one rung below complete. A space measured before anyone has
    said how much of it will be compared may not present as fully searched.

    Returns no `KnobScore` rows. Those grade a DECLARED knob against its range
    and its value list, and neither exists here; emitting rows built from a
    floor would put invented per-knob detail on the card beside real detail.
    """
    credited = [knob for knob in facts.discovered if knob.credited]
    if not credited:
        # The look happened and credited nothing. That is still not a
        # measurement OF the space: a parameter this read did not establish may
        # exist anyway - reading source is how you find what is there, not proof
        # of what is not - so the honest report is that the space was not
        # established, and `aggregate` leaves the pillar out rather than
        # averaging in a zero for it.
        refused = [knob for knob in facts.discovered if not knob.credited]
        detail = (
            "; ".join(f"{knob.name}: {knob.uncredited_reason}" for knob in refused)
            if refused
            else "the read found no parameter the agent can vary"
        )
        return (
            nothing_to_search_pillar(
                f"the agent was read and no varying setting was established - "
                f"{detail}",
                supplied=False,
            ),
            [],
            [],
        )
    reachable = 1
    for knob in credited:
        reachable *= knob.reachable_values
    return (
        combine(
            "agent",
            [
                SubScore(
                    "search-space",
                    search_space_points(reachable, None),
                    SEARCH_SPACE_WEIGHT,
                    True,
                    discovered_space_evidence(credited, reachable),
                )
            ],
        ),
        # No cap. Every credited parameter reaches two or more values it can be
        # told apart on, so `agent-no-varying-knobs` would be false here in all
        # three of its readings - there IS something to search, and this is the
        # evidence for it.
        [],
        [],
    )


def score_agent(facts: AgentFacts) -> tuple[Pillar, list[Cap], list[KnobScore]]:
    caps: list[Cap] = []
    subs: list[SubScore] = []

    # A config-space document wins outright, and this order is the safety
    # property rather than a preference. A customer who BRINGS a settings
    # document is already handled correctly - it is read, its `wired` list is
    # what earns credit, and `NOTHING_WIRED_CAP`/`UNATTESTED_WIRING_CAP` are
    # real findings about it. A read of the agent must not be able to talk over
    # any of that, or it becomes a way to score around a document that says
    # nothing is wired.
    if facts.discovery_supplied and not facts.config_space_supplied:
        return score_discovered_agent(facts)

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
        # A cap in one of these two states and not the other, and #201 is why.
        #
        # `blocks` answers "does this stop the run", not "is this true" - the
        # comment on the field says so, and says every cap used to imply BLOCKED
        # back when every cap meant something was broken.
        #
        # A supplied document that lists nothing IS a defect: the user handed
        # over their wiring and there is nothing in it. That still caps, and
        # still blocks. No document at all is not a defect and now carries no
        # ceiling either. The advisory cap that used to sit here bounded every
        # opening card in the product at 45 while its own reason said "nothing
        # in your project needs repairing for this" - a ceiling that describes
        # this walkthrough's sequencing rather than the customer's project. What
        # is true of that state is that nothing was measured, and the honest way
        # to say so is to leave the pillar out of the average, which `aggregate`
        # now does. A number is not a way of saying "I did not look".
        #
        # This branch is also reached at the CLOSE by a stopped, failed, or
        # zero-trial search, which emits no document either
        # (`references/run-safety.md`, config-space document). That reading is
        # unchanged and is the reason the evidence sentence carries no tense:
        # this module cannot tell the two gates apart, so it says the one thing
        # true at both - no settings document reached this score.
        return (
            nothing_to_search_pillar(
                evidence,
                supplied=facts.config_space_supplied,
                # Nothing about the agent reached this score - not a document,
                # not a read of its source. The guide asks for one of the two at
                # every gate, so this is silence, and silence keeps its weight.
                withheld=not facts.config_space_supplied,
            ),
            [NOTHING_WIRED_CAP] if facts.config_space_supplied else [],
            [],
        )

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
                "agent uses - list those in the document's 'wired' field",
                supplied=True,
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

    # Three counts, and they answer three different questions. Collapsing any
    # two of them is how this block was wrong before.
    #
    # `configurations` is how many settings-combinations the search can TELL
    # APART, and it is the number the pillar is scored on. Two things make it
    # smaller than a naive product over the value lists, and both are the
    # point rather than a rounding. `seed` is excluded, because sweeping it
    # measures run-to-run variance and every seed sees the same configuration -
    # multiplying it in printed "2 of 2 wired knobs actually vary; 24
    # combinations" for two two-valued knobs, and four is the only number two
    # of those can make. And `effective_values` collapses numeric values closer
    # together than the noise floor, so `temperature: [0.1, 0.115]` is one
    # value and not two. That collapse is the piece of the retired `variation`
    # sub-score that had to survive: counting a fake sweep as two would let a
    # space grow by declaring values nothing can tell apart, which is the exact
    # shape the noise floor exists to refuse.
    #
    # `declared_configurations` is the same product WITHOUT the collapse. It is
    # never scored; it exists so the evidence line can say a number the reader
    # can reconcile with their own file, and name why the two differ.
    #
    # `run_count` is how many TRIALS the run will actually spend, and there
    # both `seed` and the un-collapsed values count: the SDK enumerates what
    # the document says, so the money is real even where the distinction is
    # not.
    configurations = 1
    declared_configurations = 1
    for knob in scoreable:
        configurations *= max(knob.effective_values, 1)
        declared_configurations *= max(knob.distinct_values, 1)
    run_count = 1
    for knob in knobs:
        run_count *= max(knob.distinct_values, 1)

    if not knobs:
        # Reachable now only for an explicit "wired": [] (or wired names
        # matching no declared knob). "no knobs declared" was false here:
        # knobs ARE declared, zero of them are attested as wired.
        return (
            nothing_to_search_pillar(
                f"0 of {len(facts.knobs)} listed settings are marked as ones "
                "the agent uses",
                supplied=True,
            ),
            [NOTHING_WIRED_CAP],
            knobs,
        )

    if not varying:
        # Two ways to have nothing to search, and one sentence was false about
        # the second. `{"seed": [1, 2, 3, 4, 5]}` wired reaches here with five
        # values on the only setting the document names - "every setting has
        # only one value to try" is a count the same card contradicts two lines
        # up, where it prints "1 combinations x 5 repeats = 5 runs". `seed` is
        # excluded from scoring on purpose (EXCLUDED_KNOBS): sweeping it
        # measures run-to-run variance rather than configuration quality. So
        # the honest reason names the exclusion instead of miscounting the
        # values, and what counts is unchanged.
        excluded = [knob.name for knob in knobs if knob.kind == "excluded"]
        caps.append(
            Cap(
                "agent-no-varying-knobs",
                # #156's two reasons, on #149's named constant. #156 wrote the
                # literal 45 here; the ceiling is ranked in CAP_SEVERITY_ORDER
                # and a literal at a call site is what lets one condition
                # acquire two ceilings, which the source-reading guard refuses.
                AGENT_NO_VARYING_KNOBS_CEILING,
                (
                    "Every setting has only one value to try, so every "
                    "configuration would be identical."
                    if scoreable
                    else (
                        "The only wired setting(s) - "
                        + ", ".join(sorted(excluded))
                        + " - measure run-to-run variance rather than "
                        "configuration quality, so there is nothing for the "
                        "search to choose between."
                    )
                ),
            )
        )

    # How many times the SDK re-runs each configuration, which is what `seed`
    # buys. Named in the evidence line when it is more than one, because a
    # reader who can multiply cannot otherwise reconcile the trial spend with
    # the configuration count - the dimension that caused it is, by
    # construction, not one of the ones being counted.
    repeats = run_count // declared_configurations if declared_configurations else 1
    budget = configuration_budget(facts.max_trials, repeats)
    subs.append(
        SubScore(
            "search-space",
            search_space_points(configurations, budget),
            SEARCH_SPACE_WEIGHT,
            True,
            search_space_evidence(
                configurations,
                declared_configurations,
                repeats,
                budget,
                sorted(knob.name for knob in knobs if knob.kind == "excluded"),
            ),
        )
    )

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


def nothing_was_looked_at(pillar: Pillar) -> bool:
    """Whether this pillar's zero is a measurement or the absence of one.

    The distinction `SubScore.withheld` already draws, read one level up.

    A check that is `measured` was looked at. A check that is `withheld` was
    this run's to supply and was not supplied, which is not the same as
    unavailable - dropping those from the denominator made silence pay, and
    that is exactly the defect the field was added to close. So a pillar counts
    as looked-at when ANY of its checks is either, and only a pillar where
    nothing was measured and nothing was withheld is genuinely unobserved.

    That rule is what keeps this from re-opening the hole `withheld` closed. An
    evaluation pillar on an uncalibrated evaluator has three withheld checks and
    confidence 0.00; it is NOT excluded, because the run was asked for that
    evidence. An agent pillar with no settings document has one check that
    nobody could look at, and it is.

    A pillar carrying NO sub-scores at all is never excluded, and the empty
    `any()` is why that needs saying: `not any([])` is True, so the rule read
    backwards on the one shape that has no evidence record to read. `aggregate`
    accepts such a pillar and several callers build them directly with a score
    and a confidence of their own - excluding those would drop a caller's stated
    number out of the average on the strength of a field they never filled in.
    No sub-scores is not "nothing was looked at"; it is "this pillar does not
    report at that granularity".
    """
    return bool(pillar.subscores) and not any(
        sub.measured or sub.withheld for sub in pillar.subscores
    )


def aggregate(
    pillars: Sequence[Pillar],
    caps: Sequence[Cap],
    knobs: Sequence[KnobScore],
    weights: dict[str, float],
) -> ReadinessScore:
    # README.md's promise - "a check that cannot be computed is marked
    # unmeasured and excluded rather than scored zero" - applied to a whole
    # pillar, which is where it was being broken (#201). The agent pillar at the
    # opening gate was scored 0 at confidence 0.00, and the engine averaged that
    # zero in anyway: 94 dataset and 100 evaluation came out as 73, and the same
    # evidence renormalized over the two pillars that were actually observed
    # comes out as 97. A 24-point gap between what the document promised and
    # what the arithmetic did.
    #
    # Never all of them. A score with no observed pillar at all has nothing to
    # renormalize over, and the old denominator is the only defined answer there
    # - so the exclusion switches itself off rather than dividing by zero or
    # inventing a number out of no evidence whatsoever.
    unobserved = {pillar.name for pillar in pillars if nothing_was_looked_at(pillar)}
    if len(unobserved) >= len(pillars):
        unobserved = set()
    observed = [pillar for pillar in pillars if pillar.name not in unobserved]

    # Summed over the weights DICT, not over the pillars, exactly as before:
    # several callers score fewer pillars than they declare weights for, and
    # changing that denominator would silently re-scale them. Only the excluded
    # pillars' weights come out.
    total_weight = sum(
        weight for name, weight in weights.items() if name not in unobserved
    )
    weighted = sum(
        weights.get(pillar.name, 0.0) * pillar.score for pillar in observed
    ) / (total_weight or 1.0)
    weighted_average = round_half_up(weighted)

    ordered_caps = tuple(sorted(caps, key=cap_order))
    ceiling = min((cap.ceiling for cap in ordered_caps), default=100)
    overall = min(weighted_average, ceiling)

    # Confidence and the band follow the same exclusion, and they have to. A
    # pillar that is not in the average must not be in the evidence coverage
    # either - reporting 67% coverage for a number computed entirely from
    # fully-observed evidence describes a different score than the one printed -
    # and `band_for`'s weakest-pillar guard would otherwise hold every such run
    # at WORKABLE on the confidence of a pillar it just declined to score.
    confidence_total = sum(weights.get(p.name, 0.0) for p in observed) or 1.0
    confidence = (
        sum(weights.get(p.name, 0.0) * p.confidence for p in observed)
        / confidence_total
    )
    band, limited = band_for(
        overall,
        confidence,
        min((pillar.confidence for pillar in observed), default=None),
        pillar_excluded=bool(unobserved),
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
        unmeasured_pillars=tuple(sorted(unobserved)),
        gaps=collect_gaps(pillars, knobs, ordered_caps, overall),
    )


def score_run(
    dataset_facts: DatasetFacts,
    evaluation_facts: EvaluationFacts,
    agent_facts: AgentFacts,
    weights: dict[str, float],
    review: RowReview | None = None,
) -> ReadinessScore:
    """Score one set of facts end to end.

    Extracted so the counterfactual below is the SAME computation over changed
    facts, rather than a second arithmetic path that could drift from the one
    the customer was actually graded by. A quoted alternative score has to be
    the score they would really get; re-deriving it another way is how it stops
    being that.

    The row review travels with the facts for exactly that reason. It is an
    input to the dataset pillar, so a counterfactual scored without it would be
    a different computation and could quote an alternative grade the customer
    could never actually get. It defaults to absent so that every caller which
    has no review still scores what an unreviewed run scores.
    """
    dataset_pillar, dataset_caps = score_dataset(
        dataset_facts, evaluation_facts.method, review
    )
    evaluation_pillar, evaluation_caps = score_evaluation(evaluation_facts)
    agent_pillar, agent_caps, knobs = score_agent(agent_facts)
    return aggregate(
        [dataset_pillar, evaluation_pillar, agent_pillar],
        [*dataset_caps, *evaluation_caps, *agent_caps],
        knobs,
        weights,
    )


def provenance_assumption(
    score: ReadinessScore,
    dataset_facts: DatasetFacts,
    evaluation_facts: EvaluationFacts,
    agent_facts: AgentFacts,
    weights: dict[str, float],
    review: RowReview | None = None,
) -> ProvenanceAssumption | None:
    """Both grades for a corpus that did not say where it came from.

    Returns `None` when every row declared a source - there is then no
    assumption, and a disclosure line about one would be noise.

    The counterfactual scores the same evidence again with the silent rows read
    as collected. It deliberately does not touch `synthetic` or the answer-key
    counts: this answers exactly one question - "what if these rows are
    collected data nobody labelled" - and a second edit would make it answer a
    different one.

    "Silent" now includes a row that declared a source in a vocabulary this
    run does not know, because `classify_provenance` scores that row as
    undeclared - so the customer whose rows all say `crm-export` is shown, in
    this sentence, the grade their own declaration earns once it is mapped.
    That is the half of the unverifiable-declaration rule that keeps it from
    being a punishment: the number is disclosed before they do anything.
    """
    if not dataset_facts.exists or not dataset_facts.rows:
        # `score_dataset` scores no provenance for these at all - it reports
        # "no dataset" and caps at 20 - so there is no assumption behind the
        # number to disclose. Restated here because `main` calls this beside
        # that guard rather than from inside it.
        return None
    counted = (
        dataset_facts.collected_rows
        + dataset_facts.synthesised_rows
        + dataset_facts.undeclared_rows
    )
    # The same normalization `score_provenance` makes, and it has to be the
    # same one: this function has to disclose an assumption on exactly the runs
    # that were scored under it.
    undeclared = dataset_facts.undeclared_rows
    if not counted:
        counted = dataset_facts.rows
        undeclared = 0 if dataset_facts.synthetic else dataset_facts.rows
    if not undeclared:
        return None
    # One shape, because there is only one. The second branch that used to be
    # here declared `COUNTERFACTUAL_SOURCE` into `sources` for a count-free
    # payload, through a `declares_no_provenance` helper that read the silence
    # out of a word list. Neither exists now.
    declared = replace(
        dataset_facts,
        collected_rows=dataset_facts.collected_rows + undeclared,
        undeclared_rows=0,
    )
    if_declared = score_run(
        declared, evaluation_facts, agent_facts, weights, review
    ).overall
    if if_declared == score.overall:
        # Two identical grades are a repetition, not a disclosure: "scores
        # 77/100 ... the same evidence scores 77/100" spends the reader's
        # attention, at the moment they are deciding whether to pay, to tell
        # them nothing changes. It happens when something else binds the run at
        # or below where provenance does - and the silent rows are still counted
        # in the provenance evidence line, which says what they scored as, so
        # suppressing the sentence hides no fact.
        return None
    return ProvenanceAssumption(
        undeclared_rows=undeclared,
        scored_rows=counted,
        scored_as_generated=score.overall,
        if_declared_collected=if_declared,
    )


def assumption_sentence(assumption: ProvenanceAssumption) -> str:
    """The disclosure, in one sentence, with both numbers in it.

    One sentence and not a paragraph because it competes with the score for the
    reader's attention at the one moment they are deciding whether to pay, and
    the whole content is: this number rests on an assumption, here is the other
    number if the assumption is wrong.
    """
    # "no source this run can read" rather than "do not record where they came
    # from": since an unrecognised token is scored here too, the older wording
    # was false on the card of a customer who HAD declared one, in their own
    # words, on every row.
    rows = (
        f"{assumption.undeclared_rows} of {assumption.scored_rows} rows record "
        "no source this run can read"
        if assumption.undeclared_rows < assumption.scored_rows
        else f"No row of the {assumption.scored_rows} records a source this run "
        "can read"
    )
    return (
        f"{rows}, so this run scores them as generated: "
        f"{assumption.scored_as_generated}/100. Declared as collected data, the "
        f"same evidence scores {assumption.if_declared_collected}/100."
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


BLOCKER_KEYWORD = "BLOCKER"
# The BODY column, not the whole line: the keyword and its gutter are added
# on top, so a rendered line is this plus eleven characters.
BLOCKER_BODY_WIDTH = 76


def blocker_lines(score: ReadinessScore, palette: Palette) -> list[str]:
    """The sentence that joins the band to the block, when one is in force.

    The two say different things about different questions. The band grades the
    EVIDENCE - how good what you brought is. The block answers whether the paid
    run may START. Both can be true at once, and routinely are: the walkthrough
    that generates its own dataset scores 65/100 WORKABLE and is blocked by
    `dataset-fully-synthetic`, which is the ordinary case rather than an edge.

    Printed adjacent with no connective - `65/100  WORKABLE  (PAID RUN
    BLOCKED)` - they read as one self-contradicting verdict, and a reader who
    resolves it in either direction gets it wrong: either the score is fake, or
    the block is pedantry. Neither is true, and neither is fixable by changing
    which caps block or where the bands sit. What was missing was the sentence
    between the two claims, so that is what this adds.

    The keyword is the point. `BLOCKER` is one word a reader can hold, and it
    is followed by the only three facts they need: the score stands, one named
    thing is in the way, and here is what happens after it is cleared. The
    thing itself is not repeated here - it is on the FIX BEFORE PAID RUN line
    below, and printing a reason twice reads as two problems, which is the
    defect this whole card keeps having to fix.
    """
    blocking = [cap for cap in score.caps if cap.blocks]
    if not blocking:
        return []
    if len(blocking) == 1:
        count, pronoun, marked = "one thing has", "it", "marked"
    else:
        count = f"{len(blocking)} things have"
        pronoun, marked = "them", "each marked"
    body = (
        f"{score.overall}/100 {score.band} is what your evidence supports, and "
        f"that stands. Whether the paid run may start is a separate question: "
        f"{count} to be cleared first, {marked} FIX BEFORE PAID RUN below. Fix "
        f"{pronoun}, run this score again, and the paid comparison can start."
    )
    wrapped = textwrap.wrap(body, width=BLOCKER_BODY_WIDTH)
    indent = " " * (2 + len(BLOCKER_KEYWORD) + 2)
    lines = [f"  {palette.bad}{BLOCKER_KEYWORD}{palette.reset}  {wrapped[0]}"]
    lines.extend(f"{indent}{line}" for line in wrapped[1:])
    lines.append("")
    return lines


def unmeasured_pillar_sentence(score: ReadinessScore) -> str:
    """Say which pillars the average was NOT computed over, and what that means.

    Printed wherever the average is, because a number that silently changed its
    denominator is the defect this field was added to prevent, not to record.
    The sentence deliberately does not say the pillar is fine or bad: it says
    nothing was seen, which is the only claim the evidence supports.
    """
    names = ", ".join(score.unmeasured_pillars)
    plural = len(score.unmeasured_pillars) > 1
    return (
        f"Nothing could be measured for the {names} pillar{'s' if plural else ''}, "
        f"so {'they were' if plural else 'it was'} left out of that average "
        f"rather than counted as zero. This score is over the "
        f"{'others' if plural else 'other pillars'}; it is not a verdict on "
        f"{'those' if plural else 'that one'}."
    )


def render_card(
    score: ReadinessScore, *, palette: Palette = PLAIN, unicode_ok: bool = True
) -> str:
    """Render the terminal card.

    Meaning never depends on colour: the markers and the numbers carry it, so a
    monochrome terminal loses nothing. Deliberately contains no timestamp - the
    offline harness runs every scenario twice and compares the evidence.
    """
    lines: list[str] = []
    # The headline carries the band and nothing else. It used to append
    # "(PAID RUN BLOCKED)" here, which put a grade and a gate in one breath -
    # `blocker_lines` above owns why that reads as a contradiction and what
    # replaces it.
    headline = f"{score.overall}/100  {score.band}"
    lines.append(f"TRAIGENT OPTIMIZATION READINESS{' ' * 8}{headline}")
    lines.append("")
    lines.extend(blocker_lines(score, palette))
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
    if score.provenance_assumption is not None:
        # On the card, not only in the durable report or a reference. This is
        # the one line that says the headline number rests on an assumption
        # about the reader's own data, and a customer who learns that after
        # paying learns it too late - so it sits with the score, and it carries
        # the number they would get instead rather than only the bad news.
        lines.append(
            f"  {palette.warn}ASSUMED GENERATED{palette.reset} "
            f"{assumption_sentence(score.provenance_assumption)}"
        )
        lines.append("")
    if score.unmeasured_pillars:
        # On the card and not only in the durable report. The pillar prints
        # 0/100 in the rows above - it has no other number to print - and a
        # reader who can add would otherwise reconcile those three rows against
        # the headline and get a different answer. This is the line that says
        # the zero was not counted.
        lines.append(
            f"  {palette.dim}{unmeasured_pillar_sentence(score)}{palette.reset}"
        )
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
            f"**{score.overall}/100 - {score.band}**",
            "",
            # Same separation the card makes, in the durable artifact: the band
            # grades the evidence, the status answers whether the paid run may
            # start, and putting them in one line made a grade look like a
            # refusal.
            #
            # `BLOCKER`, which is the card's word and the one README.md and the
            # glossary define. This line used to read "Status: PAID RUN
            # BLOCKED", a fourth token beside `BLOCKER`, `FIX BEFORE PAID RUN`
            # and `LIMITED TO n` that no document explains - so a reader who met
            # the durable report first met a term the guide does not carry, and
            # a reader who met both had to work out they were the same thing.
            # The machine-readable answer to this question is `status` in the
            # `--json` payload and has always been there; this file is prose.
            *(
                [
                    "**BLOCKER.** The band above describes how good this "
                    "evidence is; this describes whether the paid run may "
                    "start. Both can be true at once. See "
                    '"What is blocking a trustworthy result" below for what has '
                    "to clear first, then re-run this score.",
                    "",
                ]
                if score.status == "BLOCKED"
                else []
            ),
            f"Weighted average before caps: {score.weighted_average}/100. "
            f"Evidence coverage: {score.confidence:.0%}.",
            "",
            *(
                [unmeasured_pillar_sentence(score), ""]
                if score.unmeasured_pillars
                else []
            ),
            *(
                [assumption_sentence(score.provenance_assumption), ""]
                if score.provenance_assumption is not None
                else []
            ),
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


def _answer_dominance_status(statuses: dict[str, str]) -> str | None:
    """Say whether preflight actually examined the spread of expected answers.

    Preflight has no `dataset-answer-dominance` record: it emits
    `dataset-ceiling-risk` only when one answer dominates, and stays silent
    otherwise. So absence had to be read as "checked, nothing found" - which is
    wrong whenever the check never ran at all, and it does not run under a
    reference-free evaluator, where the whole expected-output branch is skipped
    and `dataset-outputs` is SKIP.

    The witness for "it ran" is therefore the PASS on the check that computes
    the distribution: `dataset-outputs` counts distinct expected answers and
    `dataset-outcome-field` does the same for a structured outcome field, and
    dominance is derived inside those branches. Either PASS means the spread was
    looked at. Anything else - SKIP, WARN, FAIL, or no record - means it was not,
    and `None` is returned so the sub-score refuses to call it clean.

    Reading this from two records rather than one is deliberate: a dataset
    scored on a structured outcome field can carry a dominant `output` and a
    healthy `result.label`, and preflight raises `dataset-ceiling-risk` from
    both branches.

    When that record is present its own status is returned unchanged rather
    than re-labelled. This is a translation, not a judgement: preflight decides
    how severe a dominant answer is - today WARN, FAIL if it ever ranks one
    that way - and a literal here would silently downgrade whatever it decided.
    """
    if "dataset-ceiling-risk" in statuses:
        return statuses["dataset-ceiling-risk"]
    if "PASS" in (
        statuses.get("dataset-outputs"),
        statuses.get("dataset-outcome-field"),
    ):
        return "PASS"
    return None


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


def _failed(statuses: dict[str, str], check: str) -> bool:
    """Whether `check` FAILed, refusing to answer for a check that ran and could not.

    The un-ported half of this module's own rule. `diversity_subscore` was
    taught that a check which did not run must never read as a check that
    passed; two lines in this adapter kept doing exactly that, with
    `statuses.get(name) == "FAIL"` - every status that is not the word FAIL,
    including a SKIP and including a status this version has never heard of,
    came out as the clean answer and fed a cap that then did not fire.

    An ABSENT record is a different statement and is deliberately still read as
    clean. `check_dataset` emits `dataset-split` only where a split can be
    looked for and `dataset-ids` only where ids exist to compare - an unlabelled
    150-row dataset legitimately carries neither - so absence here means the
    question did not arise, not that it was ducked. What is refused is a record
    that IS present and says the check could not answer, because that is the
    reading this module has already paid for once.
    """
    status = statuses.get(check)
    if status is None:
        return False
    if status not in MEASURED_STATUSES:
        raise PreflightInputError(
            f"{check} reports {status!r}, which is not a result this score can "
            "read - a check that could not answer must not be scored as one "
            "that passed. Re-run preflight.py --json from the same version as "
            "this script, and if the check genuinely cannot run on this "
            "dataset, say so rather than emitting a status nothing consumes"
        )
    return status == "FAIL"


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
        answer_dominance_status=_answer_dominance_status(statuses),
        split_overlap=_failed(statuses, "dataset-split"),
        integrity_failed=structurally_failed or _failed(statuses, "dataset-ids"),
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

    No rule here judges a knob's *values* against a safety floor. One was tried
    for `max_tokens` and removed: how much room an answer needs is not knowable
    from this document, so the floor was a guess, and a guess that refuses a
    configuration breaks runs that would have been fine - `2048` for an agent
    answering `a`, `b`, `c` or `d`. What replaced it predicts nothing:
    `EXCLUDED_KNOB_REASONS` stops paying for the sweep, and the generated
    wrapper refuses a trial the provider *reports* as truncated.
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


class AgentDiscoveryInputError(ValueError):
    """An agent-knobs document the scorer cannot read.

    The sibling of `ConfigSpaceInputError` and `RowReviewInputError`, and
    hand-authored like both: the assistant writes it from what it read in the
    user's agent, so a typo in it is a reachable path rather than a bug.

    It refuses rather than degrades for the reason `RowReviewInputError` gives
    and one more of its own. This input is allowed to RAISE a score - it is the
    only one that can turn an unmeasured pillar into a measured one - so a
    document that arrives malformed is exactly the document that must not be
    quietly repaired into a usable one. A structurally unreadable file is
    refused here; a parameter that simply does not qualify is not an error at
    all, it is a finding, and it is reported as one with its reason.
    """


# The keys an agent-knobs document may carry, per parameter. Closed, and
# checked, for the reason the config-space fields are: a misspelled `values` is
# a parameter that silently earns nothing, and silence is how an author
# concludes the tool ignored them rather than that they typed it wrong.
DISCOVERED_KNOB_FIELDS = frozenset({"values", "low", "high", "evidence"})


def discovered_knob_from_entry(name: str, spec: Any) -> DiscoveredKnob:
    """Read one discovered parameter, saying plainly why it earns nothing.

    Every refusal below is the owner's rule, which is a rule about EVIDENCE
    rather than about plausibility: "according to what his agent can see - if
    numeric, and if not, have more than 1 option". So a numeric parameter needs
    a range this scorer can measure, a categorical needs at least two options
    that actually exist, and both need the line of the agent that shows it.

    Nothing here is inferred from the name. `temperature` is in
    `CANONICAL_RANGES`, and it would have been easy to let that table supply a
    range the author did not write - which is precisely the invention the
    owner's rule refuses, and would credit a project for a parameter its agent
    may hard-code. The canonical table answers "how wide is this knob's span
    relative to the usual one" for a knob somebody DECLARED; it does not answer
    "does this agent expose it".
    """
    if not isinstance(spec, dict):
        raise AgentDiscoveryInputError(
            f"knob {name!r} must be an object with the evidence for it, not "
            f"{type(spec).__name__}; say where in the agent you saw it"
        )
    unknown = sorted(set(spec) - DISCOVERED_KNOB_FIELDS)
    if unknown:
        raise AgentDiscoveryInputError(
            f"knob {name!r} carries unknown field(s) {', '.join(unknown)}; the "
            f"fields read here are {', '.join(sorted(DISCOVERED_KNOB_FIELDS))}"
        )
    evidence = spec.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        raise AgentDiscoveryInputError(
            f"knob {name!r} carries no evidence; this score credits a search "
            "space it can see in the agent, so name the file and line where "
            "the parameter is passed rather than asserting that it exists"
        )
    evidence = evidence.strip()

    if name in EXCLUDED_KNOBS:
        # Refused for exactly the reason a declared one is, and with the same
        # sentence, so an author who wired `seed` reads one explanation rather
        # than two that have to be reconciled.
        return DiscoveredKnob(
            name, "excluded", 0, evidence, EXCLUDED_KNOB_REASONS[name]
        )

    values = spec.get("values")
    if values is not None:
        if not isinstance(values, list):
            raise AgentDiscoveryInputError(
                f"knob {name!r} declares 'values' as {type(values).__name__}; "
                "it is the list of options the agent can actually take"
            )
        distinct = len({repr(value) for value in values})
        if distinct < 2:
            return DiscoveredKnob(
                name,
                "categorical",
                distinct,
                evidence,
                f"{distinct} option(s) available - one option is not a choice, "
                "so there is nothing here for a search to compare",
            )
        return DiscoveredKnob(name, "categorical", distinct, evidence)

    low, high = spec.get("low"), spec.get("high")
    if low is None or high is None:
        return DiscoveredKnob(
            name,
            "unknown",
            0,
            evidence,
            "neither a list of options nor a low/high range was established, "
            "so how much this parameter could vary is not something this score "
            "has seen",
        )
    if not all(
        isinstance(bound, (int, float)) and not isinstance(bound, bool)
        for bound in (low, high)
    ):
        raise AgentDiscoveryInputError(
            f"knob {name!r} declares a non-numeric range ({low!r}, {high!r}); "
            "a range is two numbers the parameter can take"
        )
    if high <= low:
        raise AgentDiscoveryInputError(
            f"knob {name!r} declares low {low!r} and high {high!r}; the high "
            "bound has to be above the low one for the range to hold anything"
        )
    # The same floor a declared numeric knob is measured against, so a range
    # too narrow for this scorer to tell two values apart is refused here
    # rather than counted as a dimension and collapsed later.
    if float(high) - float(low) <= noise_floor(name, float(low), float(high)):
        return DiscoveredKnob(
            name,
            "numeric",
            0,
            evidence,
            f"the range {low} to {high} is inside this score's noise floor for "
            f"{name}, so two values drawn from it would not be told apart",
        )
    return DiscoveredKnob(name, "numeric", 2, evidence)


def agent_facts_from_discovery(document: Any) -> AgentFacts:
    """Read the assistant's read of the agent, and nothing about wiring.

    Returns `AgentFacts` with `knobs` and `wired` untouched on purpose. This
    document is not a config space and must never be promoted into one: the
    `wired` attestation is what the guide refuses to take from a historical
    file, and building one here out of parameters read from source would
    re-create exactly that, one input over.
    """
    if not isinstance(document, dict):
        raise AgentDiscoveryInputError(
            f"the agent-knobs document must be an object, not "
            f"{type(document).__name__}"
        )
    unknown = sorted(set(document) - {"knobs", "source"})
    if unknown:
        raise AgentDiscoveryInputError(
            f"the agent-knobs document carries unknown field(s) "
            f"{', '.join(unknown)}; it reads 'knobs' and 'source'"
        )
    knobs = document.get("knobs")
    if knobs is None:
        raise AgentDiscoveryInputError(
            "the agent-knobs document declares no 'knobs'; an empty object is "
            "the way to say the agent exposes nothing, and it is a different "
            "statement from omitting the field"
        )
    if not isinstance(knobs, dict):
        raise AgentDiscoveryInputError(
            f"'knobs' must be an object keyed by parameter name, not "
            f"{type(knobs).__name__}"
        )
    return AgentFacts(
        discovered=tuple(
            discovered_knob_from_entry(name, spec)
            for name, spec in sorted(knobs.items())
        ),
        # Reaching this line is the proof: the agent was read.
        discovery_supplied=True,
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
        "--agent-knobs",
        help=(
            "the coding assistant's own read of the agent's source (path or -): "
            "which parameters it can already vary, each with the line that "
            "shows it. Measures the search space at the opening gate, where no "
            "config-space document exists; attests nothing about wiring, and is "
            "ignored when --config-space is given"
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
    # `--agent-knobs` counts. It is evidence about the project, so a run that
    # supplies only it is asking for a score and not for a plan - and leaving it
    # out would send that run down the planner branch, which then refuses it for
    # missing `--agent/--dataset/--evaluation` and never mentions the flag the
    # caller actually passed.
    return any((args.preflight, args.calibration, args.config_space, args.agent_knobs))


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
        # `--config-space` first, and the `elif` is the safety property, not a
        # style choice: a brought document decides the agent pillar outright,
        # and a read of the agent may not talk over one that says nothing is
        # wired. See `score_agent`.
        if args.config_space:
            agent_facts = agent_facts_from_config_space(load_json(args.config_space))
        elif args.agent_knobs:
            agent_facts = agent_facts_from_discovery(load_json(args.agent_knobs))
        else:
            agent_facts = AgentFacts()
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
        AgentDiscoveryInputError,
        RowReviewInputError,
    ) as error:
        print(f"cannot read scoring input: {error}", file=sys.stderr)
        return 2

    # The row review travels with the facts through `score_run`, rather than
    # this function re-deriving the pillars to thread it in. `score_run` exists
    # so the provenance counterfactual below is the SAME computation over
    # changed facts; scoring the real run one way and the counterfactual
    # another is exactly the drift it was extracted to prevent. The review is
    # passed to both for the same reason - it is a read of the answer key, and
    # declaring provenance does not change what the answers say.
    score = score_run(
        dataset_facts, evaluation_facts, agent_facts, args.weights, row_review
    )
    assumption = provenance_assumption(
        score, dataset_facts, evaluation_facts, agent_facts, args.weights, row_review
    )
    if assumption is not None:
        score = replace(score, provenance_assumption=assumption)

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

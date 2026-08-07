# SDK Execution

Use this reference after component creation and before writing the run wrapper.

## Contents

1. Capability discovery
2. Automatic run bounds
3. Walkthrough model ladder
4. Decorator contract
5. Small baseline sweep
6. Broader optimization
7. Result checks

## Capability discovery

Inspect the installed SDK instead of assuming a release-specific signature:

```bash
python - <<'PY'
import inspect
import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.core.objectives import ObjectiveDefinition, ObjectiveSchema

print(getattr(traigent, "__version__", "unknown"))
print(inspect.signature(traigent.optimize))
print(inspect.signature(EvaluationOptions))
print(inspect.signature(traigent.Dataset.from_jsonl))
print(inspect.signature(ObjectiveDefinition))
print(inspect.signature(ObjectiveSchema.from_objectives))
PY
```

After decorating the function, inspect `agent.optimize_sync` the same way. If the installed
signatures or public dataset loader do not support the usage below, adapt from the installed
public API. Do not invent arguments or reproduce SDK internals.

Start that inspection at these public locations instead of searching the whole package. Treat the
map as navigation, not fixed signatures: confirm each on the installed version, never hardcode a
signature you have not inspected, and treat an absent name as unavailable rather than assumed.

| Need | Import from |
| --- | --- |
| `optimize` decorator, `EvaluationOptions`, `InjectionOptions` | `traigent.api.decorators` |
| `get_config()` - read the trial's chosen values inside the agent body | `traigent` (`traigent.get_config`) |
| `ObjectiveDefinition`, `ObjectiveSchema` | `traigent.core.objectives` |
| Dataset loader and example fields (`.input_data` / `.expected_output` / `.metadata`) | `traigent.Dataset` (`Dataset.from_jsonl`) |
| `optimize_sync(...)` and its result object | the decorated function (`agent.optimize_sync`) |
| Knob recommendations - `recommend_configuration_space(agent_type)`, agent_type `rag` or `code_gen` | `traigent.config_generator.recommendations` |

Read outcomes from attributes on the result object rather than parsing the printed table; inspect
it once and reuse the names: `cloud_url` (direct portal link), `best_config`, `best_score`,
`total_cost`, `trials`, `failed_trials`, `stop_reason`, `run_label`. Confirm the exact names on the
installed version and treat any that are absent as not available. For the scorer argument contract,
use the installed public `metric_functions` shape shown under "Decorator contract" below rather than
inferring aliases or positional fallbacks from SDK internals.

The installed SDK owns:

- The default per-optimization cost limit and its in-run enforcement.
- Graceful partial results when an optimization timeout occurs.
- Retries for transient Traigent-backend requests.
- Provider-error classification and stop reasons.

The first-run wrapper must not duplicate those behaviors. Leave the SDK/provider retry defaults
unchanged, preserve any retry behavior already present in the user's agent, and do not set
`TRAIGENT_VENDOR_MAX_RETRIES` or LiteLLM `num_retries` for generated walkthrough code. If the
preserved agent already has bounded provider retries, include their possible extra calls in the
automatic runtime/spend estimate without asking the user to choose the count.

## Automatic run bounds

Do not ask the user for retry counts or timeout values. Before the paid live probe, estimate
runtime conservatively from dataset size, planned trials, and calls per example. After the
approved probe, replace that estimate with observed latency:

```text
expected seconds =
    rows * trials * calls per example * observed upper latency / effective concurrency

SDK phase timeout = expected seconds * a reasonable completion margin
```

Use a positive floor so setup overhead does not make a small run fail immediately. The coding
assistant selects the exact internal values and places them in the current process; the user does
not fill them in. If the observed estimate becomes materially longer than the approved estimate,
offer a smaller representative run or state the additional approximate time and cost.

Do not bound the enhanced optimization with a mid-run wall-clock cap. Pass
`timeout=OPTIMIZATION_TIMEOUT_SECONDS` where that value is `None` by default, so a legitimately
progressing search is never cut off partway and forced to report a partial result - and so a large
run is not truncated wholesale by a fixed clock. Its real bounds are the trial cap, the total cost
ceiling, and the per-model-request timeout below: a stuck provider call is caught by the request
timeout and total spend by the ceiling. Keep a first run from taking too long by sizing it up
front, not by cutting it: if the runtime estimate is too high, reduce the run before starting - a
smaller representative tuning slice, fewer trials, or a smaller model set - and disclose the
revised estimate; a large *preserved* baseline (never shrink a user-owned one) then runs to
completion under the cost ceiling rather than being truncated. The estimate above still drives the
up-front time/cost disclosure and the baseline phase timeout (`timeout=BASELINE_TIMEOUT_SECONDS`, a
small fixed grid). Set `TRAIGENT_FIRST_RUN_OPTIMIZATION_TIMEOUT_SECONDS` only for the rare case that
genuinely needs a hard wall-clock stop.

Keep an individual model-request timeout so one stuck provider call cannot hang the walkthrough.
Reuse the real agent's existing value when present. Generated LiteLLM walkthrough code may use a
reasonable internal fallback such as 120 seconds, adjusted automatically after the live probe.
This is not a new retry policy.

Use one total walkthrough ceiling, `$5.00` by default. Leave the SDK per-optimization cost limit
at its installed default unless it exceeds the remaining total ceiling; then lower it through the
installed public API or a process-only setting. Keep one running total across paid phases, not a
phase ledger.

## Walkthrough model ladder

This section applies only when the assistant prepares a missing baseline. Select its models from
the provider route the user already has in hand: one fast low-cost tier, one mid-tier workhorse,
and one strong tier one step below the vendor's newest flagship. Do not select the flagship
itself. Omitting it bounds generated-walkthrough cost and latency; do not imply it has no value.
State that in the plan and price any flagship comparison separately. Every selected model runs in
the baseline grid and must fit the approved time and cost envelope.

Both generated spaces use the same three models and both have an exact size. State them exactly,
never as "roughly" or "about"; the asserts beside the spaces below enforce both:

- baseline: **3 models × 2 prompt styles × 2 thinking shapes = 12 configurations**, run as 12
  trials so `grid` enumerates every one of them and nothing is left to trial order.
- enhanced: **3 models × 4 binary behaviour knobs = 48 configurations**, a quarter of it reachable
  within the 12-trial cap and inside the 4-6 varying knobs the readiness scorer pays full marks for.

Say on the approval card, plainly: **this doubles the baseline's paid trials** against the previous
version of this walkthrough. What the second axis buys is that the enhanced knobs are chosen from
evidence about two levers rather than one. The user approves the doubled number before it is spent.

Temperature is pinned at 0 in both, never swept. It mostly adds surface noise when the evaluator
wants an exact match, and a reasoning strong tier ignores it entirely - which used to make the
walkthrough conditional, dropping temperature in that branch alone and silently giving the enhanced
space a second size nothing wrote down. Pinning it always makes both branches identical, 12 and 48
whether the strong tier reasons or not.

The four behaviour knobs are **prompt style**, **pre-action reflect**, **thinking shape** (direct or
chain-of-thought), and **reflect**, two values each. They shape behaviour rather than sampling, and
each intervenes at a different moment - how the task is framed, before the work starts, during the
answer, after it - so none is another spelling of its neighbour. Four knobs, four moments, is the
test any replacement from the catalog below has to pass.

**`self_check` is gone, and `reflect` is the one that stayed.** They were one knob under two names:
both appended "look at your answer again and fix it", differing only in what the model was told to
look at, and no customer-facing sentence tells those apart without becoming two sentences that mean
the same thing. `reflect` is the usual name for the technique, and it pairs with the
`pre_action_reflect` now opposite it - plan before, revise after, a real axis.

The synthesized walkthrough dataset contains 18 tuning rows: 3 easy, 5 medium, 5 hard, and 5 very
hard. The baseline's two non-model axes are `prompt_style` and `thinking_shape` because the enhanced
space carries both: a baseline that ranks a lever the enhanced run will not use has measured nothing
usable, which is what temperature became once it was pinned. Every baseline value is kept, so the
baseline is a strict subset and the enhanced run never gets a model the baseline did not measure, so
a measured difference cannot be explained by quietly upgrading the model. The assistant adds the disclosed
controls; Traigent performs managed, cost-aware selection among them. Keep those actors separate
in the report.

### The knob catalog - twelve to choose from, four to pay for

The four slots above are the default fill for a generated single-call classification or extraction
walkthrough - a selection, not the list. Pick the four that fit the customer's agent from this
catalog, keeping the four-different-moments test, and name the ones left out on the approval card:
the customer sees the breadth, and pays for four.

| Knob | Values | Choose it when |
|---|---|---|
| `model` | 3 ladder rungs | always - it is the ladder, not a slot |
| `prompt_style` | `plain`, `structured` | default slot; the task's framing is unexamined |
| `thinking_shape` | `direct`, `chain_of_thought` | default slot; answers need derivation, not recall |
| `pre_action_reflect` | off, on | default slot; the agent starts work before reading the whole request |
| `reflect` | off, on | default slot; answers are nearly right and need one revision |
| `few_shot_count` | two counts within 0-10 | the task has a house format worked examples would teach |
| `task_decomposition` | off, on | one request bundles several sub-tasks |
| `self_consistency` | off, on | **only when the customer's own temperature is above 0** - see below |
| `retrieval_k` | two counts within 1-5 | RAG agents only; there is a retriever to widen |
| `context_format` | two layouts | retrieved or structured context is pasted in raw |
| `tool_policy` | two policies | the agent calls tools and over- or under-uses them |
| `temperature` | the customer's own values | **only when the customer already sweeps it** - see below |

Two entries carry a precondition, and both are load-bearing.

`self_consistency` samples an answer several times and keeps the majority one. It earns its catalog
place by being a quality lever that is visibly also a cost lever - it buys accuracy by spending more
per question, which puts it on the accuracy-for-cost frontier this guide reports rather than only
claiming to sit there. But it needs sampling diversity, and **this walkthrough pins temperature at
0**, where every sample repeats and the majority vote costs three calls to reproduce one. Selectable
only for a customer already running above 0; offering it beside a pinned temperature sells a
multiplier on the bill for nothing on the answer.

`temperature` is pinned at 0 by default and its slot goes to another catalog knob. When the customer
already sweeps it, use **their** values rather than a range invented here, and do not pin underneath
them. Read which case applies off their existing configuration; do not build task-type detection.

`batch_size` and `max_tokens` are deliberately absent: both move throughput and cost without changing
what the answer says, and a knob that cannot change the answer is not a quality lever.

### Judging a space before you send it

Readiness scores the agent pillar on one number: how many distinct configurations the space holds,
against how many the run has budget to try. That number is the honest part - whether four wide
knobs beat ten narrow ones is what the run is *for*, and nothing can rank it from a JSON file.

Three things it cannot count, and you can. Check each before emitting the document; none of them
lowers the score by itself, and each makes the score describe a search that is not there.

- **Values too close together are not two values.** `temperature: [0.1, 0.115]` is one setting
  written twice, and a run that spends two trials on it learns nothing from the second. The scorer
  collapses the numeric ones it has a range for - the card then says "2 distinct configurations
  (4 declared)" - but it has no range for an unfamiliar knob, so `chunk_size: [500, 505]` counts as
  two and the space it reports is bigger than the space that exists.
- **Two knobs naming one dimension are one knob.** `prompt_style` and `prompt_policy` are the same
  lever spelled twice, and the scorer only knows the spellings it has been told about. Two aliases
  it does not know multiply the space by the size of a dimension the agent has only one of.
- **A knob the agent never reads is not a lever.** Only names in `wired` are counted, and that list
  is your claim rather than a measurement. A name in it the call path ignores adds configurations
  that differ in nothing.

So say what you left out and why on the approval card, in the customer's terms, and let their own
judgement of their agent settle it. That is the check this guide actually has - the customer knows
whether two of their knobs are the same knob, and the scorer never will.

### Say what is being tried, once the enhanced run is under way

The moment the enhanced optimization starts, the customer is waiting on it. Use that wait: print one
line per knob in the space, in their terms, saying what it changes about how their agent answers.
One sentence each, verbatim:

- **model** - Tries the same task on a cheaper, a mid-range, and a stronger model.
- **prompt_style** - Changes how the request is worded, from bare task to spelled-out instructions.
- **thinking_shape** - Lets the model work through the problem before answering instead of
  answering straight away.
- **pre_action_reflect** - Has the model restate what is being asked and plan an approach before it
  starts.
- **reflect** - Has the model look back at its own answer and fix it before returning it.
- **few_shot_count** - Shows the model worked examples of the task first.
- **task_decomposition** - Splits a request that contains several jobs into separate steps.
- **self_consistency** - Answers the same question several times and keeps the answer that comes up
  most.
- **retrieval_k** - Changes how much retrieved material the model is given to work from.
- **context_format** - Changes how the supplied material is laid out for the model to read.
- **tool_policy** - Changes how readily the agent reaches for its tools.
- **temperature** - Changes how much the model varies its wording between runs.

Say nothing else here. No percentages, no reported gains, no references, no "research shows". A
customer waiting on a run wants to know what is being tried, not to be handed reading - and a number
quoted here reads as a promise about their task, which none of it is.

Sweep only knobs that are real for every model in the space. When one model ignores a knob the
others honor, the winner comparison is confounded - a configuration can win on a prompt or setting
the other models were never given on equal terms, and no report footnote untangles that; when every
model faces exactly the same variations, the winner is clear and the enhanced run's insight is
accurate. So when the strong tier is a reasoning model, pin its calling convention identically in
both runs - a chosen reasoning effort, no `max_tokens` at all, and no sampling parameters such a
model rejects. Nothing else changes: temperature is already pinned for every space, and the four
behaviour knobs are real for a reasoning model and a sampling model alike, so both branches run the
same 12 and 48.

When the user already owns a baseline, do not apply this ladder. Preserve its exact model set and
row count in the enhanced space and add non-model controls by default. Adding a cheaper or stronger
model changes the experiment and attribution, so do it only as a separately disclosed and approved
model comparison. Preserve an existing flagship and its calling convention exactly; never replace
or augment it silently.

For the generated ladder, use one model family when the selected route can supply all three model
choices. One family keeps the result readable - "the mid tier held the strong tier's accuracy at a
fraction of the cost" is a sentence the user can act on - keeps a single company receiving the
user's prompts, and keeps one bill. If the chosen vendor does not expose at least three usable
model choices, ask the user to add a second vendor only for the missing model(s), and name that
extra provider in the approval. When using OpenRouter, one key reaches every family; still prefer
one family by default, and borrow a missing model from a second family only when the chosen family
lacks it, naming that extra provider in the approval.

These three model slots are roles, not hardcoded ids: pick concrete model ids from what the
selected route lists at run time, then verify each id is live and cost-tracked before scaling, as
`run-safety.md` already requires.

## Decorator contract

Use one production-compatible function for baseline and optimization:

```python
import json
import math
import os
from pathlib import Path

from dotenv import load_dotenv

RUN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = RUN_DIR.parent
# Read before dotenv: a stale .env cannot opt into connected work. Baseline is
# the fail-safe default.
FIRST_RUN_PHASE = os.environ.get(
    "TRAIGENT_FIRST_RUN_PHASE", "baseline"
).strip().casefold()
load_dotenv(PROJECT_ROOT / ".env", override=False)
os.environ.pop("TRAIGENT_FIRST_RUN_PHASE", None)
if FIRST_RUN_PHASE not in {"baseline", "connected"}:
    raise ValueError("TRAIGENT_FIRST_RUN_PHASE must be 'baseline' or 'connected'")
if FIRST_RUN_PHASE == "baseline":
    # Remove before import so no client can capture a portal key locally.
    os.environ.pop("TRAIGENT_API_KEY", None)
SDK_RESULTS_DIR = RUN_DIR / "sdk-results"
if not os.environ.get("TRAIGENT_RESULTS_FOLDER", "").strip():
    os.environ["TRAIGENT_RESULTS_FOLDER"] = str(SDK_RESULTS_DIR)
# SDK 0.25.0 otherwise stores query/response/expected text in local per-example
# logs. The first-run record needs ids and metrics, not another copy of content.
os.environ["TRAIGENT_LOG_EXAMPLE_CONTENT"] = "false"

import litellm
import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.core.objectives import ObjectiveDefinition, ObjectiveSchema

TUNING_DATASET = str(RUN_DIR / "tuning.jsonl")
BASELINE_RESULTS = str(RUN_DIR / "baseline-results.json")
OPTIMIZED_RESULTS = str(RUN_DIR / "optimized-results.json")
CONFIG_SPACE_DOCUMENT = str(RUN_DIR / "config-space.json")
SELECTED_CURRENT_MODEL = os.environ["TRAIGENT_FIRST_RUN_CURRENT_MODEL"]
SELECTED_ALTERNATIVE_MODEL = os.environ["TRAIGENT_FIRST_RUN_ALTERNATIVE_MODEL"]
SELECTED_STRONG_MODEL = os.environ["TRAIGENT_FIRST_RUN_STRONG_MODEL"]
# Set only when the strong tier is a reasoning model; blank means no reasoning kwargs.
STRONG_REASONING_EFFORT = (
    os.environ.get("TRAIGENT_FIRST_RUN_STRONG_REASONING_EFFORT", "").strip() or None
)
SELECTED_CURRENT_PROVIDER = os.environ["TRAIGENT_FIRST_RUN_CURRENT_PROVIDER"].casefold()
PROVIDER_KEY_NAMES = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
}


def positive_number(name: str, *, default: float | None = None) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        if default is None:
            raise ValueError(f"{name} is required")
        value = default
    else:
        value = float(raw_value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def positive_int(name: str, *, default: int | None = None) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        if default is None:
            raise ValueError(f"{name} is required")
        value = default
    else:
        value = int(raw_value)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def optional_positive_number(name: str) -> float | None:
    """Return a positive float from the environment, or None when unset - used
    for bounds that are intentionally uncapped by default."""
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return None
    value = float(raw_value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


MODEL_REQUEST_TIMEOUT_SECONDS = positive_number(
    "TRAIGENT_FIRST_RUN_MODEL_REQUEST_TIMEOUT_SECONDS",
    default=120.0,
)
BASELINE_TIMEOUT_SECONDS = positive_number(
    "TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS"
)
# No wall-clock cap on the enhanced optimization by default (None): the search
# runs to its trial cap, bounded by the total cost ceiling and the per-model-
# request timeout above. Set the env var only to add an optional wall-clock limit.
OPTIMIZATION_TIMEOUT_SECONDS = optional_positive_number(
    "TRAIGENT_FIRST_RUN_OPTIMIZATION_TIMEOUT_SECONDS"
)
BASELINE_TRIALS = positive_int(
    "TRAIGENT_FIRST_RUN_BASELINE_TRIALS",
    default=12,
)
ENHANCED_MAX_TRIALS = positive_int(
    "TRAIGENT_FIRST_RUN_ENHANCED_MAX_TRIALS",
    default=12,
)


def require_current_route_credential() -> None:
    key_name = PROVIDER_KEY_NAMES.get(SELECTED_CURRENT_PROVIDER)
    if key_name is None:
        raise RuntimeError(
            f"No first-run credential mapping is declared for the inspected "
            f"provider route {SELECTED_CURRENT_PROVIDER!r}"
        )
    if not os.environ.get(key_name, "").strip():
        raise RuntimeError(
            f"The current model route {SELECTED_CURRENT_MODEL!r} uses "
            f"{SELECTED_CURRENT_PROVIDER}, but {key_name} is not set. Add that "
            "credential or explicitly approve a provider-route change; the "
            "first run will not switch routes automatically."
        )

BASELINE_CONFIG = {
    "model": SELECTED_CURRENT_MODEL,
    # Pinned, never swept, in both phases: it adds surface noise an exact
    # match punishes, and pinning it always retires the branch that used to
    # give the enhanced space a second, undocumented size.
    "temperature": 0.0,
    # `prompt_style`'s first value was "direct" until `thinking_shape` arrived
    # and took that word for the thing it actually describes.
    "prompt_style": "plain",
    "pre_action_reflect": False,
    "thinking_shape": "direct",
    "reflect": False,
}
BASELINE_SPACE = {
    # The same three ladder models run in both phases, so the enhanced run
    # never gets a model the baseline did not measure.
    "model": [
        BASELINE_CONFIG["model"],
        SELECTED_ALTERNATIVE_MODEL,
        SELECTED_STRONG_MODEL,
    ],
    "temperature": [BASELINE_CONFIG["temperature"]],
    # Two non-model axes, and both must be knobs the enhanced space carries -
    # otherwise the baseline ranks a lever that run will not use. Two rather
    # than one because the selection rule downstream reads the baseline to
    # choose the enhanced knobs, and one ranked lever is almost nothing to
    # read. It costs 12 paid trials instead of 6; the approval card says so.
    "prompt_style": [BASELINE_CONFIG["prompt_style"], "structured"],
    "thinking_shape": [BASELINE_CONFIG["thinking_shape"], "chain_of_thought"],
    "pre_action_reflect": [BASELINE_CONFIG["pre_action_reflect"]],
    "reflect": [BASELINE_CONFIG["reflect"]],
}
ENHANCED_SPACE = {
    "model": BASELINE_SPACE["model"],
    "temperature": BASELINE_SPACE["temperature"],
    # Four behaviour knobs, two values each, keeping every baseline value: the
    # baseline space is a strict subset of this one.
    "prompt_style": BASELINE_SPACE["prompt_style"],
    "pre_action_reflect": [False, True],
    "thinking_shape": BASELINE_SPACE["thinking_shape"],
    "reflect": [False, True],
}
# Readiness evidence for `scripts/readiness.py --config-space`. AGENT_TYPE names
# the high-impact catalog this walkthrough drew its knobs from; it is recorded
# on the score and changes no number, because the sub-score that once graded a
# space against that catalog was removed. WIRED_KNOBS names only the dimensions
# call_agent below actually consumes - a knob listed here that the agent ignores
# is a false claim about the search space. The scorer cannot check that claim,
# so the assert under `demonstrably_wired` below checks it here at load time.
AGENT_TYPE = "general"
WIRED_KNOBS = [
    "model",
    "temperature",
    "prompt_style",
    "pre_action_reflect",
    "thinking_shape",
    "reflect",
]
# Inputs the wiring probe below re-builds requests over. A knob that acts only
# on some inputs - a `sql_mode` applied when the message starts "SQL:", say -
# produces identical requests under a single literal, so probing one string
# reports a genuinely wired knob as unproven and blocks the run before it
# starts. Replace these with two or three real inputs from tuning.jsonl,
# covering the shapes the task actually contains.
PROBE_INPUTS = [
    "probe",
    "Probe: a longer request that states an explicit output constraint.",
]


def configuration_count(space: dict[str, list]) -> int:
    return math.prod(len(values) for values in space.values())


def config_space_document(space: dict[str, list]) -> dict:
    """Serialize the finalized search space as readiness config-space evidence."""
    return {
        "agent_type": AGENT_TYPE,
        "max_trials": ENHANCED_MAX_TRIALS,
        "knobs": {name: list(values) for name, values in space.items()},
        "wired": list(WIRED_KNOBS),
    }


# Every count this walkthrough claims is pinned here, so "48 configurations"
# is a fact the file refuses to contradict rather than a number in a paragraph.
BEHAVIOUR_KNOBS = ["prompt_style", "pre_action_reflect", "thinking_shape", "reflect"]
assert len(set(BASELINE_SPACE["model"])) == 3
assert ENHANCED_SPACE["model"] == BASELINE_SPACE["model"]
assert all(
    set(BASELINE_SPACE[knob]) <= set(ENHANCED_SPACE[knob]) for knob in BASELINE_SPACE
), "the baseline must be a subset, or it ranks levers the enhanced run will not use"
# Unconditional, where it used to fire only under a reasoning strong tier: the
# rule got simpler, not stricter, and the branch that gave the enhanced space a
# second size is gone with it.
assert (
    len(BASELINE_SPACE["temperature"]) == 1 and len(ENHANCED_SPACE["temperature"]) == 1
), "temperature is pinned, never swept - behaviour knobs carry the search"
assert all(len(ENHANCED_SPACE[knob]) == 2 for knob in BEHAVIOUR_KNOBS)
# 3 models x 2 prompt styles x 2 thinking shapes, and 3 models x 4 binary
# behaviour knobs - both holding whether or not the strong tier reasons.
assert configuration_count(BASELINE_SPACE) == 12
assert configuration_count(ENHANCED_SPACE) == 48
# EQUAL, not "at most". The baseline runs `algorithm="grid"`, which enumerates
# the space in order and stops at the trial cap - so a cap below the size is
# not a smaller sweep, it is a sweep that silently drops whichever
# configurations grid happened to order last, and the baseline's job is to rank
# knobs across all of them. Any override of TRAIGENT_FIRST_RUN_BASELINE_TRIALS
# that is not the space size fails here, at load, rather than quietly measuring
# a truncated space.
assert BASELINE_TRIALS == configuration_count(BASELINE_SPACE)
assert 1 <= ENHANCED_MAX_TRIALS < configuration_count(ENHANCED_SPACE)
assert set(WIRED_KNOBS) <= set(ENHANCED_SPACE), (
    "every wired knob must name a dimension of the space actually searched"
)

OBJECTIVES = ObjectiveSchema.from_objectives(
    [
        ObjectiveDefinition(
            name="task_success", orientation="maximize", weight=1.0
        ),
        ObjectiveDefinition(name="cost", orientation="minimize", weight=1.0),
    ]
)


def build_prompt(
    message: str,
    *,
    style: str,
    pre_action_reflect: bool,
    thinking_shape: str,
    reflect: bool,
) -> str:
    """Four knobs, four different moments - two knobs with one effect are one
    dimension counted twice, which is why `self_check` is not here: it and
    `reflect` were both "look at your answer again", differing only in what the
    model was told to look at, and that is one dimension under two names.

    `style` frames the task. `pre_action_reflect` acts BEFORE any work starts -
    restate the request and plan an approach. `thinking_shape` acts DURING the
    answer - derive it step by step instead of emitting it. `reflect` acts
    AFTER - reconsider the finished answer and revise it.

    Keep `pre_action_reflect` and `thinking_shape` textually distinct or they
    collapse into each other for a single-call agent: planning what to produce
    is not the same instruction as deriving it, and the wording below is what
    holds them apart. A replacement knob from the catalog has to survive the
    same test."""
    if style == "plain":
        prompt = message
    elif style == "structured":
        prompt = (
            "Complete the task below. Follow every requested output constraint and return only "
            f"the requested result.\n\nTask:\n{message}"
        )
    else:
        raise ValueError(f"unsupported prompt style: {style}")
    if pre_action_reflect:
        prompt += (
            "\n\nBefore you begin, restate what is being asked and what a correct answer must "
            "contain, decide your approach, then carry it out."
        )
    if thinking_shape == "chain_of_thought":
        prompt += (
            "\n\nReason through the task step by step before you answer, then return only the "
            "requested result."
        )
    elif thinking_shape != "direct":
        raise ValueError(f"unsupported thinking shape: {thinking_shape}")
    if reflect:
        prompt += (
            "\n\nAfter reaching an answer, reconsider whether it is actually correct, and "
            "revise it if it is not. Return only the final answer."
        )
    return prompt


def task_score(prediction, expected, input_data) -> float:
    # Generate this adapter from the installed SDK's documented public
    # metric_functions contract. Keep the preserved evaluator unchanged.
    ...


def provider_reported_cost(response) -> float | None:
    usage = getattr(response, "usage", None)
    reported = getattr(usage, "cost", None)
    if reported is None and isinstance(usage, dict):
        reported = usage.get("cost")
    if reported is None:
        hidden = getattr(response, "_hidden_params", {}) or {}
        headers = hidden.get("additional_headers", {}) or {}
        reported = headers.get("llm_provider-x-litellm-response-cost")
    if reported is None:
        return None
    if isinstance(reported, bool):
        raise RuntimeError("The provider returned malformed response-cost metadata")
    try:
        cost = float(reported)
    except (TypeError, ValueError) as error:
        raise RuntimeError("The provider returned malformed response-cost metadata") from error
    if not math.isfinite(cost) or cost < 0:
        raise RuntimeError("The provider returned an invalid per-response cost")
    return cost


def require_nonzero_token_usage(response) -> None:
    """Distinguish a real free-route response from a canned or missing call."""
    usage = getattr(response, "usage", None)

    def usage_field(name: str):
        if isinstance(usage, dict):
            return usage.get(name)
        return getattr(usage, name, None)

    total_tokens = usage_field("total_tokens")
    if total_tokens is None:
        # Some provider adapters expose only the two component counts. They
        # still prove a real call when every reported component is valid and
        # their sum is nonzero.
        components = [
            value
            for value in (
                usage_field("prompt_tokens"),
                usage_field("completion_tokens"),
            )
            if value is not None
        ]
        if components and all(
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value >= 0
            for value in components
        ):
            total_tokens = sum(components)
    if (
        isinstance(total_tokens, bool)
        or not isinstance(total_tokens, (int, float))
        or not math.isfinite(total_tokens)
        or total_tokens <= 0
    ):
        raise RuntimeError(
            "The provider response did not report nonzero token usage; "
            "stop before treating this as a real call"
        )


def build_request(message: str, config: dict) -> dict:
    """Build the provider request from one configuration. Pure: makes no call.

    Kept separate from `call_agent` so a wired-knob claim can be probed without
    a network or a key: two configurations that differ in a real search
    dimension must produce two different request dicts.
    """
    sampling_kwargs: dict = {"temperature": config["temperature"]}
    if config["model"] == SELECTED_STRONG_MODEL and STRONG_REASONING_EFFORT:
        # Reasoning models reject sampled temperature and need answer headroom
        # beyond their hidden reasoning tokens, so this model swaps sampling
        # controls for effort plus headroom rather than sending both.
        sampling_kwargs = {
            "reasoning_effort": STRONG_REASONING_EFFORT,
            "max_tokens": 4096,
        }
    return {
        "model": config["model"],
        "timeout": MODEL_REQUEST_TIMEOUT_SECONDS,
        **sampling_kwargs,
        "messages": [
            {
                "role": "user",
                "content": build_prompt(
                    message,
                    style=config["prompt_style"],
                    pre_action_reflect=config["pre_action_reflect"],
                    thinking_shape=config["thinking_shape"],
                    reflect=config["reflect"],
                ),
            }
        ],
    }


def call_agent(message: str, config: dict) -> tuple[str, float | None]:
    response = litellm.completion(**build_request(message, config))
    require_nonzero_token_usage(response)
    cost = provider_reported_cost(response)
    return response.choices[0].message.content or "", cost


def probe_wiring(space: dict[str, list], base: dict) -> dict[str, str]:
    """Classify each wired knob by what a pure request diff can actually prove.

    What this proves and nothing more: **request visibility, per model** - that
    changing the knob changes the dict `build_request` returns, under each model
    in the space. It never proves provider *effect*: a provider that silently
    ignores a parameter it accepts produces two different requests and one
    behaviour. Only the run itself can show effect; this only rules out the
    dimension that could not possibly have one.

    It probes every model in the space, not just the base's, because request
    construction branches on the model. It probes several inputs, because a knob
    that acts only on some inputs is invisible under one literal string.

    Verdicts:

    - `visible`     - under every model in the space, some alternative value
                      changes the request for some probed input.
    - `partial`     - it changes the request under some models and never under
                      others. That is a *conditional* dimension, not a dead one:
                      `reasoning_effort` exists only on a reasoning model, so a
                      knob that moves that model's request and no other is
                      exactly right. This is information about the shape of the
                      space, reported below with the models that honour it - not
                      a failure, and not something to launder through
                      WIRED_OUTSIDE_THE_REQUEST, since the knob demonstrably
                      does act inside request construction.
    - `invisible`   - no model and no probed input ever changes the request.
                      This alone is fatal: it is the no-op that inflates the
                      config-space document with a dimension nothing can move.
                      The probe cannot tell "acts outside request construction"
                      from "the agent ignores it"; it says so and refuses to
                      guess, which is what WIRED_OUTSIDE_THE_REQUEST records.
    - `not-searched`- fewer than two distinct values, so it claims no dimension.
    """
    models = list(dict.fromkeys(space.get("model", [base["model"]])))
    verdicts: dict[str, str] = {}
    for knob in WIRED_KNOBS:
        values = space.get(knob, [])
        if len(set(map(repr, values))) < 2:
            verdicts[knob] = "not-searched"
            continue
        moved = set()
        for model in models:
            model_base = {**base, "model": model}
            for message in PROBE_INPUTS:
                baseline = build_request(message, model_base)
                if any(
                    build_request(message, {**model_base, knob: value}) != baseline
                    for value in values
                ):
                    moved.add(model)
                    break
        if len(moved) == len(models):
            verdicts[knob] = "visible"
        elif moved:
            verdicts[knob] = "partial"
        else:
            verdicts[knob] = "invisible"
    return verdicts


# Knobs that genuinely act outside request construction - a RAG retrieval depth,
# a tool policy, a repair loop - are invisible to the probe above, so they are
# recorded here instead. This is a MAPPING, knob -> where it acts, because a
# bare list of names was a blanket waiver: `WIRED_OUTSIDE_THE_REQUEST =
# list(WIRED_KNOBS)` silenced the guard entirely while still passing. An entry
# is an explicit, reviewable claim, NOT evidence: nothing verifies it, and the
# load prints it so a reader can challenge it. Add a knob only when you can say
# where in the agent it acts; if you cannot, it is not a real search dimension -
# drop it from WIRED_KNOBS rather than parking it here. Empty for this
# walkthrough: all four of its knobs are visible in the request.
WIRED_OUTSIDE_THE_REQUEST: dict[str, str] = {}

assert all(
    knob in WIRED_KNOBS and isinstance(where, str) and where.strip()
    for knob, where in WIRED_OUTSIDE_THE_REQUEST.items()
), (
    "every WIRED_OUTSIDE_THE_REQUEST entry must map a wired knob to a "
    "non-empty description of where in the agent it acts"
)

PROBE_VERDICTS = probe_wiring(ENHANCED_SPACE, BASELINE_CONFIG)
# A `partial` knob is a conditional dimension and it loads: `reasoning_effort`
# on a reasoning model moves that model's request and no other, and failing the
# load on it blocked a valid run before it started. Re-probing the space one
# model at a time names the models that do honour it, so the asymmetry reaches
# the run record instead of being either hidden or fatal.
CONDITIONAL_WIRED_KNOBS = {
    knob: [
        model
        for model in dict.fromkeys(
            ENHANCED_SPACE.get("model", [BASELINE_CONFIG["model"]])
        )
        if probe_wiring(
            {**ENHANCED_SPACE, "model": [model]},
            {**BASELINE_CONFIG, "model": model},
        )[knob]
        == "visible"
    ]
    for knob, verdict in PROBE_VERDICTS.items()
    if verdict == "partial"
}
# Only `invisible` is fatal, because only `invisible` is the no-op this guard
# exists to catch: a knob no model and no probed input ever moves is a claimed
# search dimension the agent cannot act on, and claiming it is what inflated an
# earlier walkthrough's agent pillar by 12 points.
UNPROVEN_WIRED_KNOBS = {
    knob: verdict
    for knob, verdict in PROBE_VERDICTS.items()
    if verdict == "invisible" and knob not in WIRED_OUTSIDE_THE_REQUEST
}
assert not UNPROVEN_WIRED_KNOBS, (
    f"{UNPROVEN_WIRED_KNOBS} are listed under WIRED_KNOBS but changing them "
    "never changed the request under any model or any probed input, so the "
    "config-space document would claim a search dimension the agent cannot "
    "move. The probe cannot tell 'acts outside request construction' from "
    "'the agent ignores it' and will not guess: wire them, add probe inputs "
    "that exercise them, record where they act in WIRED_OUTSIDE_THE_REQUEST, "
    "or remove them from WIRED_KNOBS"
)
for _knob, _models in sorted(CONDITIONAL_WIRED_KNOBS.items()):
    # Neither a failure nor a free pass: the search moves this knob for part of
    # the space, and the run record should say which part.
    print(
        f"conditional dimension: '{_knob}' changes the request under "
        f"{', '.join(_models)} and under no other model in the space; the "
        "search still moves it, for those models only"
    )
for _knob, _where in sorted(WIRED_OUTSIDE_THE_REQUEST.items()):
    # Say it rather than wave it through: an escaped knob is an unproven claim
    # and the run record should show it as one.
    print(
        f"unverified wiring claim: '{_knob}' is declared to act at {_where}; "
        "the request probe cannot confirm it"
    )


@traigent.optimize(
    objectives=OBJECTIVES,
    configuration_space=ENHANCED_SPACE,
    evaluation=EvaluationOptions(
        eval_dataset=TUNING_DATASET,
        metric_functions={"task_success": task_score},
    ),
)
def agent(message: str) -> str:
    config = traigent.get_config()
    output, _cost = call_agent(message, config)
    return output
```

The process-only values above are selected by the coding assistant from the inspected project and
live-probe observation; they are not questions for the user. The generated walkthrough defaults
to twelve baseline rows and a 12-trial enhanced cap. Preserve those counts when they fit the approved
time, cost, and plan quota; prefer a smaller representative tuning slice over collapsing the
comparison back to one-versus-two rows. The assistant derives the current provider route from the
existing vendor setup, the current agent call, and the route inventory, then populates the process
variables used below; the user does not type route metadata into the run. Call
`require_current_route_credential()` immediately before the approved live probe. If the discovered
route cannot be populated from the existing vendor and there is no usable fallback ladder, stop and
ask the user to add a vendor or choose a different one. Keep the real current model and parameter
values in `BASELINE_CONFIG`, `BASELINE_SPACE`, and every corresponding enhanced dimension. Select
the alternative and strong models from the same approved provider route when generating the
walkthrough, following the walkthrough model ladder above; set
`TRAIGENT_FIRST_RUN_STRONG_REASONING_EFFORT` only when the selected strong tier actually supports
a reasoning-effort control, and pin the same value for both runs. A new route or recipient
requires revised data-egress approval. In the generated default, every search
variable must affect the actual agent call for every model in the space. A preserved conditional
dimension may affect only the models that support it, but the request probe must report that
partial coverage and the run record must name those models. When the strong tier runs as a
reasoning model, temperature is inert for it - which costs the comparison nothing, because
temperature is pinned in both spaces and every swept knob is uniform across the ladder.

The concrete spaces above are the generated classification/extraction walkthrough default, not a
template to force onto every real agent. Its baseline is a credible twelve-point sweep: the three
ladder models by two prompt styles by two thinking shapes, with the remaining controls pinned to
the current behavior. The enhanced space keeps every one of those values, the same three models,
and adds two more real one-call controls: pre-action reflect and reflect. That is exactly 48
configurations, so a 12-trial managed run has meaningful choices to make and reaches a quarter of
the space.

When the user already has a baseline or fixed current configuration, preserve that baseline space
and its row count exactly; do not expand it to twelve. Add task-relevant controls only to the enhanced
space, based on the existing agent and observed failure modes. Useful additions include context
format, retrieval depth, few-shot count, tool policy, or repair behavior. Do not add no-op fields,
string-encoded booleans, or multi-call composite behavior merely to increase the portal row count.

Require nonzero token usage for every provider call; cost metadata alone does not prove the model
ran. Use public response cost when present. Reported `0` is valid with nonzero usage. The
fallback above reads OpenRouter's provider-reported response-cost header as surfaced by LiteLLM.
When cost is absent but nonzero usage proves a real call, return `None`, report `not measured`, and
deduct the approved estimate. Do not call
`litellm.completion_cost()` here: a real OpenRouter response can be billable and valid even when a
local model-price lookup fails. If neither public usage nor a provider-reported cost is available,
stop before baseline/search instead of scaling an untracked path.

Do not include `expected` in the agent signature. Dataset inputs call the agent; expected output
belongs only to evaluation.

Keep the dataset path absolute, as `TUNING_DATASET` above already is (`str(RUN_DIR / "...")`).
On the installed SDK (through 0.25.0) a *relative* dataset path that
contains a directory component (for example `"traigent-runs/tuning.jsonl"`) is silently re-joined
onto its own resolved parent by dataset validation and doubles into
`.../traigent-runs/traigent-runs/tuning.jsonl`, failing with `FileNotFoundError` at decoration
time. Never shorten these to a relative path. Tracked upstream as Traigent/Traigent issue 1993.

Generate `task_score` as an adapter around the preserved evaluator using the installed SDK's
documented public `metric_functions` contract; the example reflects the inspected three-argument
contract. Do not infer aliases or positional fallbacks from SDK internals. When grading requires
example metadata or full control of agent execution, use the installed SDK's public custom
evaluator instead. The baseline, search, and any later comparison run must use the same selected
public evaluation path.

## Small baseline sweep

For the generated walkthrough, run the credible small space as one local fixed grid containing its
initial configuration. Start a fresh process with `TRAIGENT_FIRST_RUN_PHASE=baseline` (the
fail-safe default), supplied by the process and never by `.env`. The contract removes
`TRAIGENT_API_KEY` before importing Traigent while preserving its file value for later:

```python
assert FIRST_RUN_PHASE == "baseline", "baseline must run in the local phase"
os.environ["TRAIGENT_EXPERIMENT_NAME"] = "first-run standard sweep"
require_current_route_credential()
baseline_results = agent.optimize_sync(
    algorithm="grid",
    configuration_space=BASELINE_SPACE,
    max_trials=BASELINE_TRIALS,
    timeout=BASELINE_TIMEOUT_SECONDS,
    save_to=BASELINE_RESULTS,
)
```

Pass `algorithm="grid"` explicitly for this baseline sweep. **This applies to the local baseline
only; the connected search under "Broader optimization" must stay on `auto`.** The two runs are
deliberately different, and that difference is the comparison the first run exists to show.

The reason to pin the baseline is that `auto` means different things depending on whether a key is
present. With no Traigent key it does not fail and does not run managed search: it falls back to a
local `random` sweep and reports `fallback_reason=no_api_key`, so a run that looks like Traigent's
managed search is really random sampling. Locally the SDK registers exactly two searches, `grid` and
`random`; the managed family is cloud side and is not registered locally. At baseline size the
difference is visible - the same twelve-point space returns the first grid cell every time under
`grid`, and a different winner between runs under the fallback. A first result the user can
reproduce in front of someone else is worth more than one they cannot, so state which algorithm
actually ran rather than implying the managed one did.

Grid also cannot enumerate a continuous parameter, so every baseline knob stays an explicit list of
values. If a preserved user space is far larger than its trial cap - more than roughly twenty
configurations per allowed trial - grid would only ever reach a corner of it; use `random` there
instead and say why.

Do not supply a separate `default_config`; on local proposal paths it can consume a trial slot and
truncate the grid. Normally verify all twelve distinct points executed and that `BASELINE_CONFIG`
appears in the returned trials. If the baseline approval explicitly reduced that default, verify
the returned count matches the disclosed plan and still contains `BASELINE_CONFIG`. For an
existing user-owned baseline, replace the generated example's
`BASELINE_SPACE`, trial count, and algorithm with the preserved values and behavior exactly. A
real one-row fixed configuration remains one row; never manufacture variants around it.

After the baseline, add its tracked cost to the single running total. If cost is unavailable,
deduct the conservative estimate. Do not start the search if it cannot fit the remaining total
ceiling.

Read cost as a number only when the SDK reports one. An absent cost is `not measured`, while an
explicit provider-reported zero with nonzero token usage is a genuine free-route result. Never turn
absence into `$0.00`.

## Reading the result for insight

Two post-run reads cost nothing, need no key, and turn a flat "it improved by N points" into
something the user can act on. Confirm both on the installed version before relying on them, and
treat an absent name as unavailable rather than assumed.

- A per-example audit on the result object flags examples that no configuration ever scored
  correctly, and can carry a suggested answer where several unrelated models agreed on the same
  non-gold output. Those flags are the fastest route to a mislabelled reference: when every
  configuration fails one example, suspect the expectation before the agent.
- An optimization-insights helper summarizes which controls actually moved the score and which did
  not. A knob that never changed the outcome is worth reporting - it tells the user where not to
  spend effort next time.

Comparison reads need two completed configurations. The generated grid qualifies; a preserved
baseline with one row must wait for the enhanced result or report insight unavailable.
Neither read is meaningful under mock mode: identical canned responses describe the mock, not the
dataset.

Do not call the result's `analyze()` method. It requires a separate plugin that this run does not
install and raises `ImportError` without it, so calling it turns a finished run into a crash at the
reporting step.

## Carrying the local baseline into the portal

A baseline that ran without a Traigent key is logged locally. Upload it without another provider
call only when the installed public result exposes an exact sync id:

```bash
traigent sync "$SESSION_ID" --dry-run --json
traigent sync "$SESSION_ID" --json
```

Never use `--all`: it pushes every optimization ever logged on the machine, not this walkthrough's
baseline. Always inspect the dry-run before anything leaves the machine. Parse the real command's
JSON and use its `cloud_url` as the baseline portal link; syncing does not mutate the earlier
`baseline_results.cloud_url`.

Use `baseline_results.sync_session_id` only after feature-detecting that public attribute and a
non-empty value. If unavailable, leave the baseline local and report it from the saved local
results - do not inspect private storage or substitute `--all`. The pinned 0.25.0 release does not
expose this id; support is capability-gated for a later release. Tracked upstream as
Traigent/Traigent issue 2020.

## Broader optimization

The enhanced space carries no pre-baseline placeholder to replace. Every value in it is fixed
before either run, because the four behaviour knobs are binary and temperature is pinned - there is
no swept range to re-centre on the baseline's winner, and so no between-runs edit for anything to
get wrong. What the baseline result decides is which knobs a customer's own space keeps, not which
values this one sweeps.

The config-space document is serialized from the space this call receives, so it records what the
search actually got - but nothing is on disk while the search runs.
Three steps in order give the file one meaning and no other, *this is the space the search that just
completed received*:

- **Serialize before the call.** The bytes are frozen from the same `ENHANCED_SPACE` object the call
  is about to receive, so no later edit to the space can drift into them.
- **Unlink before the call.** Ordering alone only protects a first run. A retry - the space is
  narrowed, or the previous search failed and is resumed - starts with the earlier run's document
  already on disk, and if this search raises, that stale file survives as evidence for a search that
  is no longer the one being reported. Removing it makes the file's existence conditional on *this*
  search, not on any search ever having run.
- **Write after trials are confirmed.** A search that returns having executed nothing did not search
  the space either, so the document is persisted after `optimized_results.trials` is checked rather
  than merely after the call returns.

A run that legitimately stops earlier, raises, or completes no trial therefore emits no document at
all, and the closing score honestly reports the agent pillar as not yet measured. Re-write the
document whenever the space changes. Its shape is documented in `references/run-safety.md`, and the
finished file is passed to the closing readiness score with `--config-space`.

After the account/key handoff, start a fresh process with
`TRAIGENT_FIRST_RUN_PHASE=connected`, supplied by the process and never by `.env`. It loads the
updated `.env`; the earlier process cannot see that edit. Run the zero-LLM portal probe, then one
connected search with the same function, tuning dataset, and evaluator:

```python
assert FIRST_RUN_PHASE == "connected", "optimization must run in the connected phase"
assert os.environ.get("TRAIGENT_API_KEY", "").strip(), "Traigent key is not active"
os.environ["TRAIGENT_EXPERIMENT_NAME"] = "first-run Traigent optimization"
# Frozen from the space this call receives; persisted only once this search has
# returned trials of its own.
config_space_evidence = (
    json.dumps(config_space_document(ENHANCED_SPACE), indent=2, sort_keys=True) + "\n"
)
# An earlier run's document describes an earlier search. It must not survive
# this one, whatever this one does.
Path(CONFIG_SPACE_DOCUMENT).unlink(missing_ok=True)
optimized_results = agent.optimize_sync(
    algorithm="auto",
    configuration_space=ENHANCED_SPACE,
    max_trials=ENHANCED_MAX_TRIALS,
    timeout=OPTIMIZATION_TIMEOUT_SECONDS,
    save_to=OPTIMIZED_RESULTS,
)
assert optimized_results.trials, "optimization did not execute"
Path(CONFIG_SPACE_DOCUMENT).write_text(config_space_evidence)
```

Keep `algorithm="auto"` here, and never pin `grid` or `random` for the connected search. `auto` is
the managed path: it resolves to a cloud-brain execution intent and lets Traigent pick the method,
which is the entire point of the second run. Explicit `grid` or `random` selects configurations
locally; a valid key may still portal-track that local search, but it does not turn it into managed
configuration selection. The managed methods are reachable through `auto` on a connected run.

The pinning rule is therefore per phase, not global: pin the baseline so it is reproducible, leave
the enhanced run on `auto` so it is actually optimized. If a connected search reports a local
fallback reason, treat that as a failure to investigate rather than a result to present - the run
did not do what the report will claim it did.

Do not enable mock mode in this process. The optimization space must include the current
configuration and every baseline value, plus meaningful added knobs that the function consumes.
`max_trials` is a cap rather than an SDK-enforced minimum, passed straight through as
`max_trials=ENHANCED_MAX_TRIALS`, so returned trials never exceed it - unlike the baseline's
twelve-point space, where "all twelve" already names the whole result. `12` is therefore the ceiling and
not a floor beneath a higher count, which is why everything the user reads states it as a ceiling -
"up to 12 configurations" - rather than as a range. Report the actual count and stop reason. Fewer
than 10 rows requires a concrete backend stop, timeout, cost-limit, or failure explanation rather
than being presented as the intended first-run comparison; that floor is this assistant's own
honesty check on a short run, not a count promised to the user, so it stays out of the user-facing
copy while continuing to govern what may be called the intended comparison.

If an optional optimization timeout was set and `stop_reason == "timeout"` with trials completed,
retain and report the best partial result (the enhanced run is uncapped by default, so this is
defensive handling rather than the normal path).
Offer another bounded pass only when the search was still improving or left a specific worthwhile
hypothesis, and state its additional approximate time and cost. If zero trials completed,
diagnose provider latency, a hung call, or setup failure rather than asking for more time. Do not
describe another invocation as "resume" unless the installed SDK exposes a public resume API.

## Result checks

Report the selected baseline configuration and the selected enhanced configuration on the tuning
evidence actually produced in this run. Show the best config, score, cost, latency, stop reason,
and direct portal links for every persisted run. Put the two results side by side, explain the
knob differences, and state what changed in the measured tuning behavior. The baseline and
enhanced search must use the same selected public evaluation path and the same installed public
`traigent.Dataset.from_jsonl` loader. This first-run comparison does not establish generalization
or expected production improvement: a small tuning dataset can overfit. Consider independent
validation later only when it would change a real decision.

Before reporting:

```python
assert baseline_results.trials, "baseline did not execute"
assert optimized_results.trials, "optimization did not execute"
assert baseline_results.best_config is not None, "no baseline winner selected"
assert optimized_results.best_config is not None, "no best configuration selected"
assert optimized_results.cloud_url is not None, "optimization is not available in the portal"
```

Also verify that a user-owned baseline was preserved exactly, or that the generated baseline
returned all twelve intended distinct rows including its initial configuration. For an explicitly
approved reduced plan, verify the disclosed lower count and initial configuration instead. Inspect
failed trials, cost tracking, truncation, declared measures, stop reason, and persistence status
as defined in `run-safety.md`. The baseline portal URL, when exact sync was supported, comes from
the successful sync JSON; otherwise label it local-only. Keep and link every experiment actually
persisted. Portal experiment deletion is never walkthrough teardown and requires a later explicit
user request. Do not apply the best configuration automatically. Export it as a candidate and ask
before any production change.

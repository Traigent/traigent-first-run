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
- enhanced: **3 models × 3 binary behaviour knobs = 24 configurations**, half of it reachable
  within the 12-trial cap and, with `model`, at the four varying knobs the readiness scorer pays
  full marks for.

Say on the approval card, plainly: **the baseline runs 12 paid trials, one for every configuration
in its space**. For the generated walkthrough, all enhanced controls are already fixed; for a
customer-owned space, the two baseline axes provide evidence about which of its existing controls
to carry. State the baseline as a count, never as a change from whatever this guide did before: a
first-run customer has no run of ours to compare against, and our release history is not a fact
about their spend. The user approves the count itself before it is spent.

Temperature has one task-selected value in both spaces and is never swept. Use `0` only when the
task and evaluator demand one reproducible output - exact mathematics, executable checks, strict
schemas, or case-sensitive matching. Otherwise choose one supported nonzero value that permits
normal wording or creative variation without violating the evaluator. Do that before either paid
run, then record the value and reason on the baseline approval card. This is an assistant decision,
not another question or a fourth paid knob.
Keeping the selected value fixed across both phases preserves the 12- and 24-configuration sizes
and keeps their comparison attributable. A user-owned baseline instead keeps its temperature
behavior exactly, including an unset provider default.

The three behaviour knobs are **prompt style**, **thinking shape** (direct or chain-of-thought),
and **reflect**, two values each. They shape behaviour rather than sampling, and each intervenes at
a different moment - how the task is framed, during the answer, and after it - so none is another
spelling of its neighbour. Three knobs are enough to make the managed run choose among more
configurations than it can execute without turning a first taste into the full-power workflow.

**`self_check` is gone, and `reflect` is the one that stayed.** They were one knob under two names:
both appended "look at your answer again and fix it", differing only in what the model was told to
look at, and no customer-facing sentence tells those apart without becoming two sentences that mean
the same thing. `reflect` is the usual name for the technique.

The synthesized walkthrough dataset contains 18 tuning rows: 3 easy, 5 medium, 5 hard, and 5 very
hard, plus the ten held-out rows reserved at creation time in their own file, which no search
ever evaluates. The baseline's two non-model axes are `prompt_style` and `thinking_shape` because the enhanced
space carries both: a baseline that ranks a lever the enhanced run will not use has measured nothing
usable, which is what temperature became once it was pinned. Every baseline value is kept, so the
baseline is a strict subset and the enhanced run never gets a model the baseline did not measure, so
a measured difference cannot be explained by quietly upgrading the model. The coding assistant
fixes every generated value before either run; the user is never asked to pick values or edit the
wrapper. The assistant adds the disclosed
controls; Traigent performs managed, cost-aware selection among them. Keep those actors separate
in the report.

### The knob catalog - eleven to choose from, three to pay for

The three slots above are the default fill for a generated single-call classification or extraction
walkthrough - a selection, not the list. Pick the three that fit the customer's agent from this
catalog, keeping the different-moments test, and name the ones left out on the approval card. The
catalog is assistant-side choice, not a menu the first-run customer has to design; the approval
card shows the selected three and why they fit.

| Knob | Values | Choose it when |
|---|---|---|
| `model` | 3 ladder rungs | always - it is the ladder, not a slot |
| `prompt_style` | `plain`, `structured` | default slot; the task's framing is unexamined |
| `thinking_shape` | `direct`, `chain_of_thought` | default slot; answers need derivation, not recall |
| `reflect` | off, on | default slot; answers are nearly right and need one revision |
| `few_shot_count` | two counts within 0-10 | the task has a house format worked examples would teach |
| `task_decomposition` | off, on | one request bundles several sub-tasks |
| `self_consistency` | off, on | only when every sampled configuration uses temperature above 0 - see below |
| `retrieval_k` | two counts within 1-5 | RAG agents only; there is a retriever to widen |
| `context_format` | two layouts | retrieved or structured context is pasted in raw |
| `tool_policy` | two policies | the agent calls tools and over- or under-uses them |
| `temperature` | the customer's own values | only when preserving a customer-owned sweep - see below |

Two entries carry a precondition, and both are load-bearing.

`self_consistency` samples an answer several times and keeps the majority one. It earns its catalog
place by being a quality lever that is visibly also a cost lever - it buys accuracy by spending more
per question, which puts it on the accuracy-for-cost frontier this guide reports rather than only
claiming to sit there. But it needs sampling diversity. Select it only when every sampled
configuration uses a temperature above `0` and the agent and evaluator can benefit from diverse
answers; at `0`, the majority vote can cost three calls to reproduce one. Its extra calls must fit
the connected-stage approval and one of the existing three slots.

For an assistant-prepared walkthrough, temperature is one task-selected fixed value, not a search
slot. When the customer already sweeps it, preserve **their** values rather than inventing a new
range or pinning underneath them. Do not add a temperature sweep to generated material merely to
manufacture breadth.

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
model rejects. Nothing else changes: temperature is fixed to the selected value in every space,
and the three paid behaviour knobs are real for a reasoning model and a sampling model alike, so
both branches run the same 12 and 24.

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
    raise SystemExit("TRAIGENT_FIRST_RUN_PHASE must be 'baseline' or 'connected'")
def inherited(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


# Both phases are paid, and a canned response costs nothing and proves nothing.
# The SDK honours an inherited mock flag outside production, so neither phase
# may start under one.
if inherited("TRAIGENT_MOCK_LLM"):
    raise SystemExit(
        "TRAIGENT_MOCK_LLM is set. Both measurements would run on canned "
        "responses, so every score would describe the mock and not the agent. "
        "Unset it before a paid phase; this run will not unset it for you."
    )
if FIRST_RUN_PHASE == "baseline":
    if inherited("TRAIGENT_REQUIRE_CLOUD"):
        raise SystemExit(
            "TRAIGENT_REQUIRE_CLOUD requires a backend session, but the baseline "
            "is deliberately local. Stop before paid work, disclose this conflict "
            "on the baseline approval card, and only after approval launch a new "
            "baseline process with TRAIGENT_REQUIRE_CLOUD=0 in its environment. "
            "Do not merely unset it: .env could restore the true value."
        )
    # Backend-offline is process-local: a stored CLI credential can survive
    # removing the environment key, so this is what keeps the baseline local.
    os.environ["TRAIGENT_OFFLINE_MODE"] = "true"
    os.environ.pop("TRAIGENT_API_KEY", None)
else:
    # Both spellings: the SDK reads either as offline, and either resolves this
    # run to local-only BEFORE a session is attempted - so the flag below is
    # never consulted and the run completes locally with the guard apparently on.
    for offline_name in ("TRAIGENT_OFFLINE", "TRAIGENT_OFFLINE_MODE"):
        if inherited(offline_name):
            raise SystemExit(
                f"{offline_name} is set, which resolves this run to local-only "
                "before a backend session is attempted and so silently defeats "
                "TRAIGENT_REQUIRE_CLOUD: this phase would spend on a local "
                "search and report it as the managed one. Unset it deliberately "
                "to run connected, or stop at the local baseline. This run will "
                "not unset it for you - where data may go is a choice to make."
            )
    # Managed search or nothing. Without this the SDK degrades a connected run
    # whose backend session cannot be created - absent, wrong, or unscoped key,
    # backend unreachable - to a local sweep, and returns a result that reads
    # like the managed one the user approved paying for.
    os.environ["TRAIGENT_REQUIRE_CLOUD"] = "1"
SDK_RESULTS_DIR = RUN_DIR / "sdk-results"
if not os.environ.get("TRAIGENT_RESULTS_FOLDER", "").strip():
    os.environ["TRAIGENT_RESULTS_FOLDER"] = str(SDK_RESULTS_DIR)
# SDK 0.26.0 otherwise stores query/response/expected text in local per-example
# logs. The first-run record needs ids and metrics, not another copy of content.
os.environ["TRAIGENT_LOG_EXAMPLE_CONTENT"] = "false"

import litellm
import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.core.objectives import ObjectiveDefinition, ObjectiveSchema

TUNING_DATASET = str(RUN_DIR / "tuning.jsonl")
# A separate file, not a column in the tuning one: only `eval_dataset=TUNING_DATASET`
# below reaches the search, so a reserved row cannot be scored during selection.
HOLDOUT_DATASET = str(RUN_DIR / "holdout.jsonl")
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

# Select this literal from the inspected task and evaluator before either paid
# run. Zero belongs only to deterministic/exact work; otherwise use one
# supported nonzero value that permits the expected variation. Keep it fixed across both phases so
# it does not become a fourth paid knob or confound their comparison.
WALKTHROUGH_TEMPERATURE = 0.0


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
    # One task-selected value in both phases. This worked exact-output example
    # uses zero; replace WALKTHROUGH_TEMPERATURE before a non-deterministic run.
    "temperature": WALKTHROUGH_TEMPERATURE,
    # `prompt_style`'s first value was "direct" until `thinking_shape` arrived
    # and took that word for the thing it actually describes.
    "prompt_style": "plain",
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
    "reflect": [BASELINE_CONFIG["reflect"]],
}
ENHANCED_SPACE = {
    "model": BASELINE_SPACE["model"],
    "temperature": BASELINE_SPACE["temperature"],
    # Three behaviour knobs, two values each, keeping every baseline value: the
    # baseline space is a strict subset of this one.
    "prompt_style": BASELINE_SPACE["prompt_style"],
    "thinking_shape": BASELINE_SPACE["thinking_shape"],
    "reflect": [False, True],
}
# Readiness evidence for `scripts/readiness.py --config-space`. WIRED_KNOBS
# names only the dimensions call_agent below actually consumes - a knob listed
# here that the agent ignores is a false claim about the search space. The
# scorer cannot check that claim, so the assert under `demonstrably_wired`
# below checks it here at load time.
WIRED_KNOBS = [
    "model",
    "temperature",
    "prompt_style",
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
        "max_trials": ENHANCED_MAX_TRIALS,
        "knobs": {name: list(values) for name, values in space.items()},
        "wired": list(WIRED_KNOBS),
    }


# Every count this walkthrough claims is pinned here, so "24 configurations"
# is a fact the file refuses to contradict rather than a number in a paragraph.
BEHAVIOUR_KNOBS = ["prompt_style", "thinking_shape", "reflect"]
assert set(BASELINE_CONFIG) == set(BASELINE_SPACE), (
    "every baseline config key must be a grid dimension, or exact trial lookup fails"
)
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
), "temperature is fixed once, never swept - behaviour knobs carry the search"
assert all(len(ENHANCED_SPACE[knob]) == 2 for knob in BEHAVIOUR_KNOBS)
# 3 models × 2 prompt styles × 2 thinking shapes, and 3 models × 3 binary
# behaviour knobs - both holding whether or not the strong tier reasons.
assert configuration_count(BASELINE_SPACE) == 12
assert configuration_count(ENHANCED_SPACE) == 24
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
    thinking_shape: str,
    reflect: bool,
) -> str:
    """The three supported prompt controls act at different moments.

    Two knobs with one effect are one
    dimension counted twice, which is why `self_check` is not here: it and
    `reflect` were both "look at your answer again", differing only in what the
    model was told to look at, and that is one dimension under two names.

    `style` frames the task. `thinking_shape` acts DURING the answer - derive
    it step by step instead of emitting it. `reflect` acts AFTER - reconsider
    the finished answer and revise it. A replacement knob from the catalog has
    to survive the same distinct-effect test."""
    if style == "plain":
        prompt = message
    elif style == "structured":
        prompt = (
            "Complete the task below. Follow every requested output constraint and return only "
            f"the requested result.\n\nTask:\n{message}"
        )
    else:
        raise ValueError(f"unsupported prompt style: {style}")
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


def require_untruncated_completion(response) -> None:
    """A trial the provider cut off is not a measurement, so refuse it.

    The evaluator cannot tell a cut-off answer from a wrong one, so it scores 0
    rather than low and the model it happened to loses to one that had room.
    Raising sends it to the failed-trial count instead. `run-safety.md` owns
    why nothing here sets or predicts a cap.
    """
    choice = response.choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    if finish_reason is None and isinstance(choice, dict):
        finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        raise RuntimeError(
            "The provider truncated this completion (finish_reason='length'). "
            "It is not a measurement and must not be scored: a cut-off answer "
            "scores 0 rather than low and can crown a weaker model. This "
            "wrapper sets no max_tokens, so if your own agent sets one, raise "
            "it and re-run this configuration; otherwise the answer ran into "
            "the model's own output limit, so drop this configuration and "
            "report it as excluded"
        )


def build_request(message: str, config: dict) -> dict:
    """Build the provider request from one configuration. Pure: makes no call.

    Kept separate from `call_agent` so a wired-knob claim can be probed without
    a network or a key: two configurations that differ in a real search
    dimension must produce two different request dicts.
    """
    sampling_kwargs: dict = {"temperature": config["temperature"]}
    if config["model"] == SELECTED_STRONG_MODEL and STRONG_REASONING_EFFORT:
        # Reasoning models reject sampled temperature, so this model swaps the
        # sampling control for an effort setting rather than sending both. No
        # `max_tokens` here or on any other tier - `run-safety.md` owns why,
        # and it is not an oversight to correct.
        sampling_kwargs = {"reasoning_effort": STRONG_REASONING_EFFORT}
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
                    thinking_shape=config["thinking_shape"],
                    reflect=config["reflect"],
                ),
            }
        ],
    }


# Spend on trials this wrapper refused. Both guards below raise, so reading the
# cost after them dropped that money out of every total the run reports: a
# truncated trial was billed for every token generated up to the cut, and
# surfaced as $0. It is spend that bought no measurement - report it, never add
# it to the comparison.
REFUSED_TRIAL_COSTS: list[float] = []


def call_agent(message: str, config: dict) -> tuple[str, float | None]:
    response = litellm.completion(**build_request(message, config))
    cost = provider_reported_cost(response)  # before either refusal, not after
    try:
        require_nonzero_token_usage(response)
        require_untruncated_completion(response)
    except RuntimeError:
        if cost is not None:
            REFUSED_TRIAL_COSTS.append(cost)
        raise
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
# walkthrough: all three of its paid knobs are visible in the request.
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
temperature is fixed in both spaces and every swept knob is uniform across the ladder.

The concrete spaces above are the generated classification/extraction walkthrough default, not a
template to force onto every real agent. Its baseline is a credible twelve-point sweep: the three
ladder models by two prompt styles by two thinking shapes, with the remaining controls pinned to
the current behavior. The enhanced space keeps every one of those values, the same three models,
and adds one more real one-call control: reflect. That is exactly 24 configurations, so a 12-trial
managed run has meaningful choices to make while keeping the first taste deliberately small.

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

Keep every dataset path absolute, as `TUNING_DATASET` and `HOLDOUT_DATASET` above already are
(`str(RUN_DIR / "...")`). Never shorten these to a relative path: the SDK resolves a relative one
against the working directory of whichever process opens it, and this run's dataset lives under
`RUN_DIR` while the assistant works from the project root. An absolute path is the same file from
any directory, which is the property that matters when the run, a re-run, and `traigent sync` are
three different processes. Nothing announces a breach of this rule: a relative path that resolves
against the wrong directory reads one file or misses one, and neither is a crash.

Generate `task_score` as an adapter around the preserved evaluator using the installed SDK's
documented public `metric_functions` contract; the example reflects the inspected three-argument
contract. Do not infer aliases or positional fallbacks from SDK internals. When grading requires
example metadata or full control of agent execution, use the installed SDK's public custom
evaluator instead.

## Small baseline sweep

For the generated walkthrough, run the credible small space as one local fixed grid containing its
initial configuration. Start a fresh process with `TRAIGENT_FIRST_RUN_PHASE=baseline` (the
fail-safe default), supplied by the process and never by `.env`. The contract forces backend-offline
before import: removing `TRAIGENT_API_KEY` does not suppress a stored CLI login. Provider calls stay
real. The setting dies with the baseline process; never export it, because the connected
process requires it absent and refuses it if inherited.

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
values. If a preserved user space is large enough that its trial cap could not reach most of it,
grid would only ever cover the corner it starts from; use `random` there instead, and say which
one ran and why.

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
SESSION_ID="<copy baseline_results.sync_session_id>"
TRAIGENT_FIRST_RUN_RESULTS_DIR="/absolute/path/to/project/traigent-runs/sdk-results"
TRAIGENT_RESULTS_FOLDER="$TRAIGENT_FIRST_RUN_RESULTS_DIR" traigent sync "$SESSION_ID" --dry-run --json
TRAIGENT_RESULTS_FOLDER="$TRAIGENT_FIRST_RUN_RESULTS_DIR" traigent sync "$SESSION_ID" --json
```

`TRAIGENT_RESULTS_FOLDER` is not optional here. The id is relative to the store that holds the
record, `traigent sync` is a separate process that resolves its store from its own environment, and
the run above set that variable inside the Python process only. Without it the CLI looks in its
default root and rejects an id that is on disk. Replace the placeholder with the resolved absolute
path to this project's `traigent-runs/sdk-results`; do not reuse the Python-only `RUN_DIR` name in
the shell.

Never use `--all`: it pushes every optimization ever logged on the machine, not this walkthrough's
baseline. Always inspect the dry-run before anything leaves the machine. Parse the real command's
JSON and use its `cloud_url` as the baseline portal link; syncing does not mutate the earlier
`baseline_results.cloud_url`.

Use `baseline_results.sync_session_id` only after feature-detecting that public attribute and a
non-empty value. If unavailable, leave the baseline local and report it from the saved local
results - do not inspect private storage or substitute `--all`, whatever the reason: any gap here is
tracked upstream and the fix belongs there.

An empty value is a normal answer, not a failure. The field carries a live id when the local store
holds the authoritative copy of the run - this walkthrough's baseline, run with no Traigent key -
and is empty when the backend tracked the run end to end, because then there is nothing to upload
and `cloud_url` already names it. Read the field itself, never a `metadata` mirror of it, and do not
carry it across a reload: it names a record in one machine's store, and a result loaded from disk
may have come from another.

## Broader optimization

The enhanced space carries no pre-baseline placeholder to replace. Every value in it is fixed
before either run, because the three behaviour knobs are binary and temperature was selected once - there is
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
error_path = RUN_DIR / "optimization-error.json"
try:
    # A retry that succeeds must not retain the previous attempt's failure.
    error_path.unlink(missing_ok=True)
except OSError:
    raise SystemExit(
        "Managed optimization did not start: the stale sanitized error artifact could not be removed."
    ) from None
try:
    optimized_results = agent.optimize_sync(
        algorithm="auto",
        configuration_space=ENHANCED_SPACE,
        max_trials=ENHANCED_MAX_TRIALS,
        timeout=OPTIMIZATION_TIMEOUT_SECONDS,
        save_to=OPTIMIZED_RESULTS,
    )
except BaseException as exc:
    # pyo3 panic exceptions inherit directly from BaseException. Preserve
    # deliberate process cancellation, but turn SDK/provider failures into a
    # bounded artifact and a non-traceback exit. Never persist str(exc): an SDK
    # error can contain prompts, outputs, endpoints, personal data, or secrets.
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        raise
    try:
        error_path.write_text(
            json.dumps(
                {
                    "status": "managed-optimization-stopped",
                    "error_type": type(exc).__name__,
                    "detail": "Raw exception omitted; inspect it locally and redact before reporting.",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        # Suppress both the artifact failure and the original exception. Python
        # otherwise prints the original as chained context, undoing the redaction.
        raise SystemExit(
            "Managed optimization stopped; the sanitized error artifact could not be written."
        ) from None
    raise SystemExit(
        f"Managed optimization stopped ({type(exc).__name__}); see {error_path}"
    ) from None
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

`TRAIGENT_REQUIRE_CLOUD=1`, set for this phase in the wrapper above, is why that check is a
backstop rather than the only defence. Without it `auto` does not fail when the managed brain is
unreachable: it falls back to a local sweep, returns a result, and leaves the fallback reason for
someone to notice afterwards - after twelve paid trials the user approved as a managed search. With
it, session-creation failure raises before any trial. The flag is set only here: it fails any run
that creates no backend session, which is what the baseline phase is. An inherited true value
therefore stops the baseline before spending instead of being silently removed. Disclose the
conflict on the approval card; only after approval may a fresh baseline process be launched with
`TRAIGENT_REQUIRE_CLOUD=0` in its process environment. Do not merely unset it: because dotenv loads
with `override=False`, a true value in `.env` would be restored and stop the baseline again.

Setting it is necessary and not sufficient, and it has to be both spellings. `TRAIGENT_OFFLINE` and
`TRAIGENT_OFFLINE_MODE` each resolve the run to local-only before a session is ever attempted, so
the enforcement site never runs, and either one produces exactly the run this guards against while
the guard reads as on - worse than not setting it. The wrapper refuses to start the connected phase
under either instead of clearing it: no-egress is a deliberate choice about where the user's data
may go, and unsetting it to satisfy this run would send data out on their behalf.

Because the phase now fails instead of degrading, own the failure. The canonical call above catches
ordinary SDK/provider exceptions and pyo3 panic exceptions, while preserving deliberate
`KeyboardInterrupt`/`SystemExit`. It persists only the exception type and a fixed explanation, then
exits nonzero without a traceback. Never save or display raw `str(exc)`: exception text can contain
prompts, outputs, endpoints, personal data, or credentials. Inspect it locally, sanitize the useful
category, and route that sanitized account through the ordinary honest-report path. If even the
sanitized artifact cannot be written, the nested fallback exits with a fixed message and suppresses
both exception contexts, so the original text still cannot leak through chaining. Before a retry,
the wrapper removes that artifact or stops before spending; a later success can therefore never
leave an earlier `managed-optimization-stopped` record beside it.

Two shapes reach that handler and they cost differently. A session that cannot be created fails
before any provider trial, so nothing was spent and the honest report is "the managed run did not
start", with the sanitized reason and the baseline still standing as the result. A managed run that
loses the brain mid-flight raises after some trials are already paid for: recover what the SDK
persisted, report the trials that completed and the spend they carried, and say plainly that the
search stopped early rather than presenting a partial frontier as the answer. Neither shape is a
reason to re-run the phase without the flag - that would buy back the exact result this prevents.

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

**Read the frontier by hand, on the metric the run actually declared.** The same function reads the
baseline grid's finished trials and the enhanced search's, so one function serves both. It is
arithmetic over artifacts already in hand and makes no provider call:

```python
def frontier_at_or_above(trials, metric_name, floor):
    """Non-dominated completed trials scoring at or above `floor`, cheapest first.

    `metric_name` is this run's own objective name - the key wired through
    `metric_functions`, which is `"task_success"` in this reference's worked
    example - and never `"accuracy"`, which can sit in the same metrics map
    while being built-in exact match rather than the scorer this run wired.

    `floor` is the incumbent trial's value under this same `metric_name`, so
    both sides of the comparison are the same measurement. Never pass the
    result's `best_score` - under the two-objective schema above it is the
    weighted scalarization of score and cost, not the metric being compared.

    The floor is what keeps the frontier honest. Without it the cheapest
    trial is always on the frontier however badly it scored, and the report
    hands the user a configuration worse than the one they already run.

    Higher-is-better is assumed, which is what this reference's
    `orientation="maximize"` objective declares. For a run whose primary
    metric is one where lower is better - an error rate, declared `minimize` -
    reverse both score comparisons rather than passing the metric through
    unchanged, or the frontier is built out of the worst-scoring trials.
    """
    priced = []
    for trial in trials:
        if getattr(trial.status, "value", trial.status) != "completed":
            continue
        score = trial.metrics.get(metric_name)
        cost = trial.metrics.get("cost")
        # An absent cost is not a zero. A trial the run could not price cannot
        # take part in a cost comparison, and reading it as 0.0 puts every
        # unpriced trial on the frontier.
        if score is None or cost is None:
            continue
        if score >= floor:
            priced.append((cost, score, trial))
    frontier = [
        (cost, score, trial)
        for cost, score, trial in priced
        # Dominated: some other point is no dearer and no lower-scoring, and
        # strictly better on one of the two. Nobody would take this one.
        if not any(
            other_cost <= cost
            and other_score >= score
            and (other_cost < cost or other_score > score)
            for other_cost, other_score, _other in priced
        )
    ]
    return [trial for _cost, _score, trial in sorted(frontier, key=lambda row: row[0])]
```

The incumbent is a point like any other and is reported as one: keeping what you already run is a
choice the frontier is meant to show, not one it hides. The incumbent trial that supplies `floor`
must itself carry a reported, positive cost: a `0.0` produced by unknown model pricing is
indistinguishable in the metrics map from a genuine free route, and `references/run-safety.md`
makes measured cost a precondition for the read.

Do not pass `strategy=` or `strategy_params` to obtain this: the frontier is the function above and
nothing else. The presets are unused here because a strategy can replace the objectives the
decorator declared without raising or warning, and because the cost-floor preset floors on built-in
exact-match accuracy rather than the wired scorer - so the floor silently becomes `0.0` and it
returns the cheapest configuration rather than the cheapest acceptable one. Both move the winner
without moving anything the report shows.

Score the reserved rows with the run's recommended configuration, when SKILL stage 7 says to,
against `HOLDOUT_DATASET` through the same loader and the same `task_score` the search used.
`references/evaluation-and-dataset.md` owns which configuration that is - one call of
`evaluate_holdout`, never one per candidate, whatever the rounds returned. The returned
cost joins the single running total exactly as a baseline phase does; `references/run-safety.md`
owns what the approval discloses about those calls.

```python
def holdout_agent_input(input_data):
    if isinstance(input_data, str):
        return input_data
    if isinstance(input_data, dict) and isinstance(input_data.get("message"), str):
        return input_data["message"]
    raise TypeError(
        "Holdout input does not match the inspected agent(message: str) contract"
    )


def evaluate_holdout(config: dict) -> tuple[float, float | None]:
    scores = []
    tracked_cost: float | None = 0.0
    holdout = traigent.Dataset.from_jsonl(HOLDOUT_DATASET)
    for example in holdout.examples:
        input_data = example.input_data
        expected = example.expected_output
        output, call_cost = call_agent(holdout_agent_input(input_data), config)
        scores.append(task_score(output, expected, input_data))
        if call_cost is None:
            tracked_cost = None
        elif tracked_cost is not None:
            tracked_cost += call_cost
    return sum(scores) / len(scores), tracked_cost
```

Report the selected baseline configuration and the selected enhanced configuration on the tuning
evidence actually produced in this run. Show the best config, score, cost, latency, stop reason,
and direct portal links for every persisted run. Put the two results side by side, explain the
knob differences, and state what changed in the measured tuning behavior. The baseline, search,
and holdout must use the same selected public evaluation path, using the same installed public
`traigent.Dataset.from_jsonl` loader. This first-run comparison does not establish generalization
or expected production improvement, and the held-out score does not convert it into one: that
split is assistant-visible, non-blind, and too small to settle a difference.
`references/evaluation-and-dataset.md` owns the reservation, the disclosure format, and the
small-sample caveat.

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

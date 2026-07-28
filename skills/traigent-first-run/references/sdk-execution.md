# SDK Execution

Use this reference after component creation and before writing the run wrapper.

## Contents

1. Capability discovery
2. Automatic run bounds
3. Walkthrough model ladder
4. Decorator contract
5. Small baseline sweep
6. Broader optimization
7. Holdout and result checks

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

Select the models Traigent chooses as a ladder within the selected provider route, from model ids
the route currently lists: one fast low-cost tier, one mid-tier workhorse, and one strong tier one
step below the vendor's newest flagship. Do not select the flagship itself - the newest, most
expensive model the vendor currently markets as its best. A first run exists to show the workflow
and the cost-accuracy tradeoff quickly, and the flagship makes every trial slower and more
expensive without teaching more about either; say that in one line when presenting the plan.
Capping the ladder one step down is also what keeps the comparison honest and affordable: every
selected model must run in the baseline grid, so every selected model has to be quick and cheap
enough to grid.

Both runs use the same three models. The baseline grids them against two evaluator-safe
temperatures - six rows, the sweep a user would credibly run by hand, with the mid tier as the
generated initial configuration - and it keeps the pre-account first result quick and cheap. The
enhanced space keeps the identical model list and grows along the other axes: once the baseline
result is in, refine the swept values around its top rows - a winner at temperature 0.2 earns
close neighbors such as 0.1 and 0.3, not only a farther point - while keeping every baseline
value so the comparison stays contained, and add the prompt-policy and self-check controls.
Because the enhanced run never gets a model the baseline did not measure, a win is attributable to
Traigent's added knobs and managed, cost-aware search - never to quietly upgrading the model.

Sweep only knobs that are real for every model in the space. When one model ignores a knob the
others honor, the winner comparison is confounded - a configuration can win on a prompt or
setting the other models were never given on equal terms, and no report footnote untangles that;
when every model faces exactly the same variations, the winner is clear and the enhanced run's
insight is accurate. So when the strong tier is a reasoning model, pin its calling convention
identically in both runs - a chosen reasoning effort with the answer-headroom rule (`max_tokens`
at least 4096), and no sampling parameters such a model rejects - and, since temperature is then
inert for it, drop temperature as a swept knob for the whole walkthrough: pin one temperature for
the sampling models and sweep uniform knobs instead, two prompt styles in the baseline and the
prompt-policy plus self-check controls in the enhanced space.

When the inspected agent already calls the vendor's flagship, keep it exactly where it is: it is
the current configuration, so it anchors the baseline being measured and stays in the enhanced
space. Add the cheaper ladder tiers below it instead of more flagship-tier models, and tell the
user why before the approval - the first run stays fast and cheap by searching down the ladder,
and the interesting first question becomes whether a cheaper tier holds the flagship's accuracy, a
legitimate cost-side win. Never remove or replace the user's model choice silently.

Build the ladder inside one model family. One family keeps the result readable - "the mid tier
held the strong tier's accuracy at a fraction of the cost" is a sentence the user can act on -
keeps a single company receiving the user's prompts, and keeps one bill. When several direct
provider credentials exist, pick one family, name it and the reason in the plan, and let the
combined approval - which already lists every data recipient - be the user's moment to switch. On
the OpenRouter route one key reaches every family; still ladder within one family by default, and
borrow a missing rung from a second family only when the chosen family lacks it, naming that
extra upstream recipient in the approval.

Tiers are roles, not hardcoded ids: pick concrete model ids from what the selected route lists at
run time, then verify each id is live and cost-tracked before scaling, as `run-safety.md` already
requires.

## Decorator contract

Use one production-compatible function for baseline and optimization:

```python
import math
import os
from pathlib import Path

from dotenv import load_dotenv

RUN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = RUN_DIR.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)
SDK_RESULTS_DIR = RUN_DIR / "sdk-results"
if not os.environ.get("TRAIGENT_RESULTS_FOLDER", "").strip():
    os.environ["TRAIGENT_RESULTS_FOLDER"] = str(SDK_RESULTS_DIR)

import litellm
import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.core.objectives import ObjectiveDefinition, ObjectiveSchema

TUNING_DATASET = str(RUN_DIR / "tuning.jsonl")
HOLDOUT_DATASET = str(RUN_DIR / "holdout.jsonl")
BASELINE_RESULTS = str(RUN_DIR / "baseline-results.json")
OPTIMIZED_RESULTS = str(RUN_DIR / "optimized-results.json")
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
    default=6,
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
    "temperature": 0.0,
    "prompt_style": "direct",
    "self_check": False,
}
BASELINE_SPACE = {
    # The same three ladder models run in both phases, so the enhanced run
    # never gets a model the baseline did not measure.
    "model": [
        BASELINE_CONFIG["model"],
        SELECTED_ALTERNATIVE_MODEL,
        SELECTED_STRONG_MODEL,
    ],
    # Nonzero values are safe only when the evaluator tolerates valid surface variation.
    # Otherwise pin 0.0 and substitute other real controls to retain the planned row count.
    "temperature": [BASELINE_CONFIG["temperature"], 0.2],
    "prompt_style": [BASELINE_CONFIG["prompt_style"]],
    "self_check": [BASELINE_CONFIG["self_check"]],
}
ENHANCED_SPACE = {
    "model": BASELINE_SPACE["model"],
    # After the baseline, bracket its top rows with close neighbors (a winner
    # at 0.2 earns 0.1 and 0.3) while keeping every baseline value; 0.4 below
    # is only the pre-baseline placeholder.
    "temperature": [*BASELINE_SPACE["temperature"], 0.4],
    "prompt_style": [
        BASELINE_CONFIG["prompt_style"],
        "structured",
        "criteria_first",
    ],
    "self_check": [False, True],
}


def configuration_count(space: dict[str, list]) -> int:
    return math.prod(len(values) for values in space.values())


assert len(set(BASELINE_SPACE["model"])) == 3
assert configuration_count(BASELINE_SPACE) == 6
assert 1 <= BASELINE_TRIALS <= configuration_count(BASELINE_SPACE)
assert 1 <= ENHANCED_MAX_TRIALS < configuration_count(ENHANCED_SPACE)

OBJECTIVES = ObjectiveSchema.from_objectives(
    [
        ObjectiveDefinition(
            name="task_success", orientation="maximize", weight=1.0
        ),
        ObjectiveDefinition(name="cost", orientation="minimize", weight=1.0),
    ]
)


def build_prompt(message: str, *, style: str, self_check: bool) -> str:
    if style == "direct":
        prompt = message
    elif style == "structured":
        prompt = (
            "Complete the task below. Follow every requested output constraint and return only "
            f"the requested result.\n\nTask:\n{message}"
        )
    elif style == "criteria_first":
        prompt = (
            "Identify the task's decision criteria, apply each criterion carefully, and return "
            f"only the requested result.\n\nTask:\n{message}"
        )
    else:
        raise ValueError(f"unsupported prompt style: {style}")
    if self_check:
        prompt += (
            "\n\nBefore returning the result, silently check it against the task constraints "
            "and correct any mismatch. Do not include the check in the response."
        )
    return prompt


def task_score(prediction, expected, input_data) -> float:
    # Generate this adapter from the installed SDK's documented public
    # metric_functions contract. Keep the preserved evaluator unchanged.
    ...


def provider_reported_cost(response) -> float:
    usage = getattr(response, "usage", None)
    reported = getattr(usage, "cost", None)
    if reported is None and isinstance(usage, dict):
        reported = usage.get("cost")
    if reported is None:
        hidden = getattr(response, "_hidden_params", {}) or {}
        headers = hidden.get("additional_headers", {}) or {}
        reported = headers.get("llm_provider-x-litellm-response-cost")
    if reported is None:
        raise RuntimeError(
            "The provider response did not include a usable per-response cost; "
            "stop before scaling this paid run rather than guessing from a model map"
        )
    try:
        cost = float(reported)
    except (TypeError, ValueError) as error:
        raise RuntimeError("The provider returned malformed response-cost metadata") from error
    if not math.isfinite(cost) or cost <= 0:
        raise RuntimeError("The provider returned an invalid per-response cost")
    return cost


def call_agent(message: str, config: dict) -> tuple[str, float]:
    sampling_kwargs: dict = {"temperature": config["temperature"]}
    if config["model"] == SELECTED_STRONG_MODEL and STRONG_REASONING_EFFORT:
        # Reasoning models reject sampled temperature and need answer headroom
        # beyond their hidden reasoning tokens, so this model swaps sampling
        # controls for effort plus headroom rather than sending both.
        sampling_kwargs = {
            "reasoning_effort": STRONG_REASONING_EFFORT,
            "max_tokens": 4096,
        }
    response = litellm.completion(
        model=config["model"],
        timeout=MODEL_REQUEST_TIMEOUT_SECONDS,
        **sampling_kwargs,
        messages=[
            {
                "role": "user",
                "content": build_prompt(
                    message,
                    style=config["prompt_style"],
                    self_check=config["self_check"],
                ),
            }
        ],
    )
    cost = provider_reported_cost(response)
    return response.choices[0].message.content or "", cost


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
to six baseline rows and a 12-trial enhanced cap. Preserve those counts when they fit the approved
time, cost, and plan quota; prefer a smaller representative tuning slice over collapsing the
comparison back to one-versus-two rows. Derive
`TRAIGENT_FIRST_RUN_CURRENT_PROVIDER` from the current agent call, not from which credential names
happen to exist. Call `require_current_route_credential()` immediately before the approved live
probe. If another provider's credential is present instead, stop with the mismatch; never rewrite
the current model identifier or provider prefix silently. Keep the real current model and parameter
values in `BASELINE_CONFIG`, `BASELINE_SPACE`, and every corresponding enhanced dimension. Select
the alternative and strong models from the same approved provider route when generating the
walkthrough, following the walkthrough model ladder above; set
`TRAIGENT_FIRST_RUN_STRONG_REASONING_EFFORT` only when the selected strong tier actually supports
a reasoning-effort control, and pin the same value for both runs. A new route
or recipient requires revised data-egress approval. Every search variable must affect the actual
agent call for every model in the space; when the strong tier runs as a reasoning model,
temperature is inert for it - follow the ladder section above and sweep uniform knobs instead of
a knob only some models honor.

The concrete spaces above are the generated classification/extraction walkthrough default, not a
template to force onto every real agent. Its baseline performs a credible six-point standard
sweep: the three ladder models by two evaluator-safe temperatures, with the added prompt controls
pinned to the current behavior. The enhanced space keeps all of those values - the same three
models - extends the temperature range around the baseline's winner,
and adds two real one-call controls: three prompt policies and a native
boolean self-check branch. That creates 54 possible
configurations, so a 12-trial managed run has meaningful choices to make.

When the user already has a baseline or fixed current configuration, preserve that baseline space
and its row count exactly; do not expand it to six. Add task-relevant controls only to the enhanced
space, based on the existing agent and observed failure modes. Useful additions include context
format, retrieval depth, few-shot count, tool policy, or repair behavior. Do not add no-op fields,
string-encoded booleans, or multi-call composite behavior merely to increase the portal row count.

Use the provider's public response cost when it is present. The fallback above reads OpenRouter's
provider-reported response-cost header as surfaced by LiteLLM. Do not call
`litellm.completion_cost()` here: a real OpenRouter response can be billable and valid even when a
local model-price lookup fails. If neither public usage nor a provider-reported cost is available,
stop before baseline/search instead of scaling an untracked path.

Do not include `expected` in the agent signature. Dataset inputs call the agent; expected output
belongs only to evaluation.

Keep every dataset path absolute, as `TUNING_DATASET` and `HOLDOUT_DATASET` above already are
(`str(RUN_DIR / "...")`). On the installed SDK (through 0.25.0) a *relative* dataset path that
contains a directory component (for example `"traigent-runs/tuning.jsonl"`) is silently re-joined
onto its own resolved parent by dataset validation and doubles into
`.../traigent-runs/traigent-runs/tuning.jsonl`, failing with `FileNotFoundError` at decoration
time. Never shorten these to a relative path. Tracked upstream as Traigent/Traigent issue 1993.

Generate `task_score` as an adapter around the preserved evaluator using the installed SDK's
documented public `metric_functions` contract; the example reflects the inspected three-argument
contract. Do not infer aliases or positional fallbacks from SDK internals. When grading requires
example metadata or full control of agent execution, use the installed SDK's public custom
evaluator instead. The baseline, search, and holdout must use the same selected public evaluation
path.

## Small baseline sweep

For the generated walkthrough, run the credible small space as one connected grid. The generated
initial configuration must be one of its points:

```python
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
difference is visible - the same six-point space returns the first grid cell every time under
`grid`, and a different winner between runs under the fallback. A first result the user can
reproduce in front of someone else is worth more than one they cannot, so state which algorithm
actually ran rather than implying the managed one did.

Grid also cannot enumerate a continuous parameter, so every baseline knob stays an explicit list of
values. If a preserved user space is far larger than its trial cap - more than roughly twenty
configurations per allowed trial - grid would only ever reach a corner of it; use `random` there
instead and say why.

Do not supply a separate `default_config`; on local proposal paths it can consume a trial slot and
truncate the grid. Normally verify all six distinct points executed and that `BASELINE_CONFIG`
appears in the returned trials. If the combined approval explicitly reduced that default, verify
the returned count matches the disclosed plan and still contains `BASELINE_CONFIG`. For an
existing user-owned baseline, replace the generated example's
`BASELINE_SPACE`, trial count, and algorithm with the preserved values and behavior exactly. A
real one-row fixed configuration remains one row; never manufacture variants around it.

After the baseline, add its tracked cost to the single running total. If cost is unavailable,
deduct the conservative estimate. Do not start the search if it cannot fit the remaining total
ceiling.

Read cost as a number only when the SDK reports one. A run with no captured provider spend returns
`total_cost` as absent rather than zero, so report cost as not measured instead of printing `$0.00`
- a stated zero reads as "this was free", which is a different and false claim.

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

Both need at least two completed configurations to say anything, which the baseline already
provides. Neither is meaningful under mock mode: canned responses make every configuration score
identically, so a flag there describes the mock, not the dataset.

Do not call the result's `analyze()` method. It requires a separate plugin that this run does not
install and raises `ImportError` without it, so calling it turns a finished run into a crash at the
reporting step.

## Carrying the local baseline into the portal

A baseline that ran before the Traigent key existed is logged locally, so it can be uploaded
afterwards instead of being paid for a second time:

```bash
traigent sync "$SESSION_ID" --dry-run   # names the run and its trial count; no upload, no key
traigent sync "$SESSION_ID"             # upload that one run
```

Never use `--all`: it pushes every optimization ever logged on the machine, not this walkthrough's
baseline. Always dry-run first so the wrong session is caught before anything leaves the machine.

Take `SESSION_ID` from whatever the installed SDK exposes for it. If the installed version offers no
supported way to obtain the id for the run just completed, leave the baseline local and report it
from the local results - do not go looking through the SDK's private storage layout, and do not
substitute `--all`. Tracked upstream as Traigent/Traigent issue 2020.

## Broader optimization

Run one connected search using the same decorated function, tuning dataset, and evaluator:

```python
os.environ["TRAIGENT_EXPERIMENT_NAME"] = "first-run Traigent optimization"
optimized_results = agent.optimize_sync(
    algorithm="auto",
    configuration_space=ENHANCED_SPACE,
    max_trials=ENHANCED_MAX_TRIALS,
    timeout=OPTIMIZATION_TIMEOUT_SECONDS,
    save_to=OPTIMIZED_RESULTS,
)
```

Keep `algorithm="auto"` here, and never pin `grid` or `random` for the connected search. `auto` is
the managed path: it resolves to a cloud-brain execution intent and lets Traigent pick the method,
which is the entire point of the second run. Naming a local algorithm explicitly does the opposite
of an optimization - it resolves to a local-only intent, so a valid key is bypassed, the search
drops back to the same exhaustive or random sweep the baseline already ran, and the enhanced run
stops being a Traigent optimization at all. The managed methods are not registered in the local
SDK, so they are only reachable through `auto` on a connected run.

The pinning rule is therefore per phase, not global: pin the baseline so it is reproducible, leave
the enhanced run on `auto` so it is actually optimized. If a connected search reports a local
fallback reason, treat that as a failure to investigate rather than a result to present - the run
did not do what the report will claim it did.

Do not enable mock mode in this process. The optimization space must include the current
configuration and every baseline value, plus meaningful added knobs that the function consumes.
`max_trials` is a cap rather than an SDK-enforced minimum. The default target is 10-13 visible
enhanced rows with a cap of 12; report the actual count and stop reason. Fewer than 10 rows requires
a concrete backend stop, timeout, cost-limit, or failure explanation rather than being presented as
the intended first-run comparison.

If an optional optimization timeout was set and `stop_reason == "timeout"` with trials completed,
retain and report the best partial result (the enhanced run is uncapped by default, so this is
defensive handling rather than the normal path).
Offer another bounded pass only when the search was still improving or left a specific worthwhile
hypothesis, and state its additional approximate time and cost. If zero trials completed,
diagnose provider latency, a hung call, or setup failure rather than asking for more time. Do not
describe another invocation as "resume" unless the installed SDK exposes a public resume API.

## Holdout and result checks

Evaluate the selected small-sweep configuration and selected enhanced configuration on the
untouched holdout with the same agent path and evaluator. A holdout check is not another
optimization search. Generate `holdout_agent_input` from the installed public loader's observed
`input_data` shape and the inspected agent signature. The canonical `input`/`output` JSONL shape
loads a scalar; the mapping branch below is only for the example agent's explicit `message` input
contract, not an SDK alias:

```python
def holdout_agent_input(input_data) -> str:
    if isinstance(input_data, str):
        return input_data
    if isinstance(input_data, dict) and isinstance(input_data.get("message"), str):
        return input_data["message"]
    raise TypeError(
        "Holdout input does not match the inspected agent(message: str) contract"
    )


def evaluate_holdout(config: dict) -> tuple[float, float]:
    scores = []
    tracked_cost = 0.0
    holdout = traigent.Dataset.from_jsonl(HOLDOUT_DATASET)
    for example in holdout.examples:
        input_data = example.input_data
        expected = example.expected_output
        output, call_cost = call_agent(holdout_agent_input(input_data), config)
        scores.append(task_score(output, expected, input_data))
        tracked_cost += call_cost
    return sum(scores) / len(scores), tracked_cost


baseline_holdout_score, baseline_holdout_cost = evaluate_holdout(
    baseline_results.best_config
)
winner_holdout_score, winner_holdout_cost = evaluate_holdout(
    optimized_results.best_config
)
```

Before each holdout batch, ensure its conservative estimate fits the one remaining total. Add
tracked holdout costs to the reported walkthrough total. Loading holdout through the same
installed public `traigent.Dataset.from_jsonl` loader used for tuning preserves the SDK's
normalization semantics.

Before reporting:

```python
assert baseline_results.trials, "baseline did not execute"
assert optimized_results.trials, "optimization did not execute"
assert baseline_results.best_config is not None, "no baseline winner selected"
assert optimized_results.best_config is not None, "no best configuration selected"
assert baseline_results.cloud_url is not None, "baseline is not available in the portal"
assert optimized_results.cloud_url is not None, "optimization is not available in the portal"
```

Also verify that a user-owned baseline was preserved exactly, or that the generated baseline
returned all six intended distinct rows including its initial configuration. For an explicitly
approved reduced plan, verify the disclosed lower count and initial configuration instead. Verify
that the enhanced run returned 10-13 rows, the disclosed reduced target, or a concrete shortfall
reason. Inspect failed trials, cost tracking, truncation, declared measures, stop reason, and
persistence status as defined in `run-safety.md`. Keep both experiments in the portal and report
their direct `cloud_url` values; portal experiment deletion is never walkthrough teardown and
requires a later explicit user request. Do not apply the best configuration automatically. Export
it as a candidate and ask before any production change.

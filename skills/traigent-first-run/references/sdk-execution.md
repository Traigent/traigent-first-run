# SDK Execution

Use this reference after component creation and before writing the run wrapper.

## Contents

1. Capability discovery
2. Automatic run bounds
3. Decorator contract
4. Current baseline
5. Bounded optimization
6. Holdout and result checks

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

Keep an individual model-request timeout so one stuck provider call cannot hang the walkthrough.
Reuse the real agent's existing value when present. Generated LiteLLM walkthrough code may use a
reasonable internal fallback such as 120 seconds, adjusted automatically after the live probe.
This is not a new retry policy.

Use one total walkthrough ceiling, `$5.00` by default. Leave the SDK per-optimization cost limit
at its installed default unless it exceeds the remaining total ceiling; then lower it through the
installed public API or a process-only setting. Keep one running total across paid phases, not a
phase ledger.

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


def positive_int(name: str) -> int:
    value = int(os.environ[name])
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


MODEL_REQUEST_TIMEOUT_SECONDS = positive_number(
    "TRAIGENT_FIRST_RUN_MODEL_REQUEST_TIMEOUT_SECONDS",
    default=120.0,
)
BASELINE_TIMEOUT_SECONDS = positive_number(
    "TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS"
)
OPTIMIZATION_TIMEOUT_SECONDS = positive_number(
    "TRAIGENT_FIRST_RUN_OPTIMIZATION_TIMEOUT_SECONDS"
)
MAX_TRIALS = positive_int("TRAIGENT_FIRST_RUN_MAX_TRIALS")


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
}
SEARCH_SPACE = {
    "model": [
        BASELINE_CONFIG["model"],
        SELECTED_ALTERNATIVE_MODEL,
    ],
    "temperature": [BASELINE_CONFIG["temperature"], 0.2],
    "prompt_style": [BASELINE_CONFIG["prompt_style"], "structured"],
}

OBJECTIVES = ObjectiveSchema.from_objectives(
    [
        ObjectiveDefinition(
            name="task_success", orientation="maximize", weight=1.0
        ),
        ObjectiveDefinition(name="cost", orientation="minimize", weight=1.0),
    ]
)


def build_prompt(message: str, *, style: str) -> str:
    if style == "direct":
        return message
    if style == "structured":
        return (
            "Complete the task below. Follow every requested output constraint and return only "
            f"the requested result.\n\nTask:\n{message}"
        )
    raise ValueError(f"unsupported prompt style: {style}")


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
    response = litellm.completion(
        model=config["model"],
        temperature=config["temperature"],
        timeout=MODEL_REQUEST_TIMEOUT_SECONDS,
        messages=[
            {
                "role": "user",
                "content": build_prompt(message, style=config["prompt_style"]),
            }
        ],
    )
    cost = provider_reported_cost(response)
    return response.choices[0].message.content or "", cost


@traigent.optimize(
    objectives=OBJECTIVES,
    configuration_space=SEARCH_SPACE,
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
live-probe observation; they are not questions for the user. Derive
`TRAIGENT_FIRST_RUN_CURRENT_PROVIDER` from the current agent call, not from which credential names
happen to exist. Call `require_current_route_credential()` immediately before the approved live
probe. If another provider's credential is present instead, stop with the mismatch; never rewrite
the current model identifier or provider prefix silently. Keep the real current model and parameter
values in `BASELINE_CONFIG` and every corresponding search dimension. Every search variable must
affect the actual agent call.

Use the provider's public response cost when it is present. The fallback above reads OpenRouter's
provider-reported response-cost header as surfaced by LiteLLM. Do not call
`litellm.completion_cost()` here: a real OpenRouter response can be billable and valid even when a
local model-price lookup fails. If neither public usage nor a provider-reported cost is available,
stop before baseline/search instead of scaling an untracked path.

Do not include `expected` in the agent signature. Dataset inputs call the agent; expected output
belongs only to evaluation.

Generate `task_score` as an adapter around the preserved evaluator using the installed SDK's
documented public `metric_functions` contract; the example reflects the inspected three-argument
contract. Do not infer aliases or positional fallbacks from SDK internals. When grading requires
example metadata or full control of agent execution, use the installed SDK's public custom
evaluator instead. The baseline, search, and holdout must use the same selected public evaluation
path.

## Current baseline

Run the actual current configuration as one connected grid point:

```python
os.environ["TRAIGENT_EXPERIMENT_NAME"] = "first-run current configuration"
require_current_route_credential()
baseline_space = {name: [value] for name, value in BASELINE_CONFIG.items()}
baseline_results = agent.optimize_sync(
    algorithm="grid",
    configuration_space=baseline_space,
    max_trials=1,
    timeout=BASELINE_TIMEOUT_SECONDS,
    save_to=BASELINE_RESULTS,
)
```

If the installed SDK counts an implicit/default trial separately, size `max_trials` from observed
behavior so the current configuration actually executes. Verify it appears in returned trials.
For an existing agent without explicit configuration values, create a thin wrapper whose baseline
branch calls the original behavior unchanged.

After the baseline, add its tracked cost to the single running total. If cost is unavailable,
deduct the conservative estimate. Do not start the search if it cannot fit the remaining total
ceiling.

## Bounded optimization

Run one connected search using the same decorated function, tuning dataset, and evaluator:

```python
os.environ["TRAIGENT_EXPERIMENT_NAME"] = "first-run Traigent optimization"
optimized_results = agent.optimize_sync(
    algorithm="auto",
    configuration_space=SEARCH_SPACE,
    max_trials=MAX_TRIALS,
    timeout=OPTIMIZATION_TIMEOUT_SECONDS,
    save_to=OPTIMIZED_RESULTS,
)
```

Do not enable mock mode in this process. The optimization space must include the current
configuration.

When `stop_reason == "timeout"` and trials completed, retain and report the best partial result.
Offer another bounded pass only when the search was still improving or left a specific worthwhile
hypothesis, and state its additional approximate time and cost. If zero trials completed,
diagnose provider latency, a hung call, or setup failure rather than asking for more time. Do not
describe another invocation as "resume" unless the installed SDK exposes a public resume API.

## Holdout and result checks

Evaluate the unchanged current configuration and selected best configuration on the untouched
holdout with the same agent path and evaluator. A holdout check is not another optimization
search. Generate `holdout_agent_input` from the installed public loader's observed `input_data`
shape and the inspected agent signature. The canonical `input`/`output` JSONL shape loads a scalar;
the mapping branch below is only for the example agent's explicit `message` input contract, not an
SDK alias:

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


baseline_holdout_score, baseline_holdout_cost = evaluate_holdout(BASELINE_CONFIG)
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
assert optimized_results.best_config is not None, "no best configuration selected"
assert baseline_results.cloud_url is not None, "baseline is not available in the portal"
assert optimized_results.cloud_url is not None, "optimization is not available in the portal"
```

Also inspect failed trials, cost tracking, truncation, declared measures, stop reason, and
persistence status as defined in `run-safety.md`. Keep both experiments in the portal and report
their direct `cloud_url` values; portal experiment deletion is never walkthrough teardown and
requires a later explicit user request. Do not apply the best configuration automatically. Export
it as a candidate and ask before any production change.

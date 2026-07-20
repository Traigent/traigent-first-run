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

print(getattr(traigent, "__version__", "unknown"))
print(inspect.signature(traigent.optimize))
print(inspect.signature(EvaluationOptions))
print(inspect.signature(traigent.Dataset.from_jsonl))
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
`TRAIGENT_VENDOR_MAX_RETRIES` or LiteLLM `num_retries` for generated walkthrough code.

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

from dotenv import load_dotenv

load_dotenv(override=False)

import litellm
import traigent
from traigent.api.decorators import EvaluationOptions

TUNING_DATASET = "traigent-runs/tuning.jsonl"
HOLDOUT_DATASET = "traigent-runs/holdout.jsonl"
SELECTED_CURRENT_MODEL = os.environ["TRAIGENT_FIRST_RUN_CURRENT_MODEL"]
SELECTED_ALTERNATIVE_MODEL = os.environ["TRAIGENT_FIRST_RUN_ALTERNATIVE_MODEL"]


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
    cost = float(litellm.completion_cost(completion_response=response))
    return response.choices[0].message.content or "", cost


@traigent.optimize(
    objectives=["task_success", "cost"],
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
live-probe observation; they are not questions for the user. Keep the real current model and
parameter values in `BASELINE_CONFIG` and every corresponding search dimension. Every search
variable must affect the actual agent call.

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
baseline_space = {name: [value] for name, value in BASELINE_CONFIG.items()}
baseline_results = agent.optimize_sync(
    algorithm="grid",
    configuration_space=baseline_space,
    max_trials=1,
    timeout=BASELINE_TIMEOUT_SECONDS,
    save_to="traigent-runs/baseline-results.json",
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
    save_to="traigent-runs/optimized-results.json",
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
search:

```python
def evaluate_holdout(config: dict) -> tuple[float, float]:
    scores = []
    tracked_cost = 0.0
    holdout = traigent.Dataset.from_jsonl(HOLDOUT_DATASET)
    for example in holdout.examples:
        input_data = example.input_data
        expected = example.expected_output
        output, call_cost = call_agent(input_data["message"], config)
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
assert optimized_results.cloud_url is not None, "optimization is not available in the portal"
```

Also inspect failed trials, cost tracking, truncation, declared measures, stop reason, and
persistence status as defined in `run-safety.md`. Do not apply the best configuration
automatically. Export it as a candidate and ask before any production change.

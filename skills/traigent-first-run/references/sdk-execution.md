# SDK Execution

Use this reference after component creation and before writing the run wrapper.

## Contents

1. Capability discovery
2. Decorator contract
3. Current baseline
4. Bounded optimization
5. Holdout and result checks

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
signatures or the public `traigent.Dataset.from_jsonl` loader do not support the usage below,
stop and adapt from the installed public API. Do not invent arguments.

## Approved runtime bounds

Before writing the wrapper, copy the combined approval's named positive provider-request,
baseline, optimization, and holdout phase timeouts plus its explicit provider retry count into
the current process environment. Do not invent defaults or persist approval in `.env`. Derive
each phase timeout from the approved call floor, `(1 + provider retry count)`, request timeout,
judge/composite calls, and an explicit orchestration allowance. Record that calculation and the
chosen values in `run-plan.md`.

The example below passes the request timeout and retry count to LiteLLM, and the baseline/search
timeouts to `optimize_sync`. The installed SDK must expose `timeout` on `optimize_sync`; the
capability-discovery step above is the authority.

Treat the SDK timeout as an optimization-phase stop bound, not as a replacement for the provider
request timeout. The holdout deadline is checked around each synchronous call and divides the
remaining time among permitted attempts; an in-flight request still returns or errors through its
shorter provider timeout. Include retry backoff and cleanup in the orchestration allowance.

## Decorator contract

Use one production-compatible function for baseline and optimization:

```python
import math
import os
import time

from dotenv import load_dotenv

load_dotenv(override=False)

import litellm
import traigent
from traigent.api.decorators import EvaluationOptions

TUNING_DATASET = "traigent-runs/tuning.jsonl"
HOLDOUT_DATASET = "traigent-runs/holdout.jsonl"
SELECTED_CURRENT_MODEL = os.environ["TRAIGENT_FIRST_RUN_CURRENT_MODEL"]
SELECTED_ALTERNATIVE_MODEL = os.environ["TRAIGENT_FIRST_RUN_ALTERNATIVE_MODEL"]


def positive_seconds(name: str) -> float:
    value = float(os.environ[name])
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def nonnegative_int(name: str) -> int:
    value = int(os.environ[name])
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def positive_int(name: str) -> int:
    value = int(os.environ[name])
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


# Export these process-only values from the unchanged combined approval.
PROVIDER_REQUEST_TIMEOUT_SECONDS = positive_seconds(
    "TRAIGENT_FIRST_RUN_PROVIDER_REQUEST_TIMEOUT_SECONDS"
)
BASELINE_TIMEOUT_SECONDS = positive_seconds(
    "TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS"
)
OPTIMIZATION_TIMEOUT_SECONDS = positive_seconds(
    "TRAIGENT_FIRST_RUN_OPTIMIZATION_TIMEOUT_SECONDS"
)
HOLDOUT_PHASE_TIMEOUT_SECONDS = positive_seconds(
    "TRAIGENT_FIRST_RUN_HOLDOUT_PHASE_TIMEOUT_SECONDS"
)
PROVIDER_RETRY_COUNT = nonnegative_int("TRAIGENT_FIRST_RUN_PROVIDER_RETRY_COUNT")
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
    # Generate a runtime adapter from this installed SDK's documented public
    # metric_functions contract. Keep the preserved evaluator unchanged.
    ...


def call_agent(
    message: str,
    config: dict,
    *,
    request_timeout_seconds: float | None = None,
) -> tuple[str, float]:
    effective_timeout = (
        PROVIDER_REQUEST_TIMEOUT_SECONDS
        if request_timeout_seconds is None
        else request_timeout_seconds
    )
    if effective_timeout <= 0:
        raise ValueError("request_timeout_seconds must be positive")
    response = litellm.completion(
        model=config["model"],
        temperature=config["temperature"],
        timeout=effective_timeout,
        num_retries=PROVIDER_RETRY_COUNT,
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

Set the two non-secret model-id environment values from the real agent or the locally validated
walkthrough choices before launch. Keep the real current model and parameter values in
`BASELINE_CONFIG` and in every corresponding search dimension. Every search variable must affect
the actual agent call.

Do not include `expected` in the agent signature. Dataset input fields call the agent; expected
output belongs only to evaluation.

Generate `task_score` as an adapter around the preserved evaluator using the installed SDK's
documented public `metric_functions` contract; the example above reflects the inspected
three-argument contract. Do not infer aliases or positional fallbacks from SDK internals. When
grading requires example metadata or full control of agent execution, use the installed SDK's
public custom-evaluator model instead of extending this callback from memory. Do not change the
evaluator's grading policy. The baseline, search, and holdout must use the same selected public
evaluation path.

## Current baseline

Check the baseline's combined worst-case cost against its allocation in the aggregate
remaining-budget ledger. Then run the current configuration as one connected grid point:

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

For an existing agent that does not expose explicit configuration values, create a thin wrapper
whose baseline branch calls the original behavior unchanged. Do not substitute an assistant-chosen
"normal" configuration for the real current behavior.

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

Set `MAX_TRIALS`, the per-optimization-call SDK cost limit, provider key, Traigent key, and
process-only cost approval from the recorded combined approval. Separately check the search's
combined worst-case cost against the aggregate remaining-budget ledger before calling
`optimize_sync`. Do not enable mock mode in this process.

The optimization space must include the current configuration. If it does not, the comparison
cannot prove the search beat what the user had.

## Holdout and result checks

Evaluate the unchanged current configuration and selected best configuration on the untouched
holdout with the same agent path and evaluator. Count these provider/evaluator calls in the
combined approval. A holdout check is not another optimization search. Use the undecorated
`call_agent` helper so each configuration is explicit:

```python
def evaluate_holdout(config: dict, *, phase_name: str) -> tuple[float, float]:
    deadline = time.monotonic() + HOLDOUT_PHASE_TIMEOUT_SECONDS
    scores = []
    tracked_cost = 0.0
    holdout = traigent.Dataset.from_jsonl(HOLDOUT_DATASET)
    for example in holdout.examples:
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise TimeoutError(
                f"{phase_name} exceeded its approved holdout phase deadline"
            )
        input_data = example.input_data
        expected = example.expected_output
        # Reserve request time for every permitted attempt inside the phase deadline.
        per_attempt_timeout = min(
            PROVIDER_REQUEST_TIMEOUT_SECONDS,
            remaining_seconds / (1 + PROVIDER_RETRY_COUNT),
        )
        output, call_cost = call_agent(
            input_data["message"],
            config,
            request_timeout_seconds=per_attempt_timeout,
        )
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"{phase_name} exceeded its approved holdout phase deadline"
            )
        scores.append(task_score(output, expected, input_data))
        tracked_cost += call_cost
    return sum(scores) / len(scores), tracked_cost


baseline_holdout_score, baseline_holdout_cost = evaluate_holdout(
    BASELINE_CONFIG,
    phase_name="current-configuration holdout",
)
winner_holdout_score, winner_holdout_cost = evaluate_holdout(
    optimized_results.best_config,
    phase_name="winner holdout",
)
```

Adapt the input expansion to the real agent signature. For an LLM judge, instrument and add judge
cost separately. Before each current-configuration and winner holdout call batch, confirm its
combined worst-case cost fits the aggregate remaining-budget ledger. Add both holdout costs to the
reported first-run total; they are not included in the optimization result object's aggregate.
Loading holdout through the same installed public `traigent.Dataset.from_jsonl` loader used for
tuning preserves the SDK's input, expected-output, and metadata normalization, including
top-level side fields and a nested literal `metadata` field.
The monotonic deadline is created separately for each holdout batch. Include both holdout phase
timeouts and every permitted retry attempt in the approved runtime estimate.

Before reporting:

```python
assert baseline_results.trials, "baseline did not execute"
assert optimized_results.trials, "optimization did not execute"
assert optimized_results.best_config is not None, "no best configuration selected"
assert optimized_results.cloud_url is not None, "optimization is not available in the portal"
```

Also inspect failed trials, cost tracking, truncation, declared measures, and persistence status as
defined in `run-safety.md`. Do not apply the best configuration automatically. Export it as a
candidate and ask before any production change.

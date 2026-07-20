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
PY
```

After decorating the function, inspect `agent.optimize_sync` the same way. If the installed
signatures do not support the arguments below, stop and adapt from the installed public API. Do
not invent arguments.

## Decorator contract

Use one production-compatible function for baseline and optimization:

```python
import os

import litellm
import traigent
from dotenv import load_dotenv
from traigent.api.decorators import EvaluationOptions

load_dotenv(override=False)

TUNING_DATASET = "traigent-runs/tuning.jsonl"
SELECTED_CURRENT_MODEL = os.environ["TRAIGENT_FIRST_RUN_CURRENT_MODEL"]
SELECTED_ALTERNATIVE_MODEL = os.environ["TRAIGENT_FIRST_RUN_ALTERNATIVE_MODEL"]
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


def task_score(output, expected, input_data=None) -> float:
    # Replace with the calibrated task-specific evaluator.
    ...


def call_agent(message: str, config: dict) -> tuple[str, float]:
    response = litellm.completion(
        model=config["model"],
        temperature=config["temperature"],
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

## Current baseline

Run the current configuration as one connected grid point:

```python
os.environ["TRAIGENT_EXPERIMENT_NAME"] = "first-run current configuration"
baseline_space = {name: [value] for name, value in BASELINE_CONFIG.items()}
baseline_results = agent.optimize_sync(
    algorithm="grid",
    configuration_space=baseline_space,
    max_trials=1,
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
    save_to="traigent-runs/optimized-results.json",
)
```

Set `MAX_TRIALS`, cost cap, provider key, Traigent key, and process-only cost approval from the
recorded combined approval. Do not enable mock mode in this process.

The optimization space must include the current configuration. If it does not, the comparison
cannot prove the search beat what the user had.

## Holdout and result checks

Evaluate the unchanged current configuration and selected best configuration on the untouched
holdout with the same agent path and evaluator. Count these provider/evaluator calls in the
combined approval. A holdout check is not another optimization search. Use the undecorated
`call_agent` helper so each configuration is explicit:

```python
import json


def evaluate_holdout(config: dict) -> tuple[float, float]:
    scores = []
    tracked_cost = 0.0
    with open("traigent-runs/holdout.jsonl") as holdout_file:
        for line in holdout_file:
            row = json.loads(line)
            output, call_cost = call_agent(row["input"]["message"], config)
            scores.append(task_score(output, row["output"], row["input"]))
            tracked_cost += call_cost
    return sum(scores) / len(scores), tracked_cost


baseline_holdout_score, baseline_holdout_cost = evaluate_holdout(BASELINE_CONFIG)
winner_holdout_score, winner_holdout_cost = evaluate_holdout(
    optimized_results.best_config
)
```

Adapt the input expansion to the real agent signature. For an LLM judge, instrument and add judge
cost separately. Add both holdout costs to the reported first-run total; they are not included in
the optimization result object's aggregate.

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

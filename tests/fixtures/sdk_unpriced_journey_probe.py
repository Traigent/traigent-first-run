"""Run the guide's unpriced call path through the real, offline SDK optimizer.

The parent supplies the current guide on stdin so a retained mutation can use
the same probe without editing source. Only the customer-specific request,
scorer and terminal provider transport are fixtures; the guide's call checks,
ledger installation, objective schema and agent decorator execute unchanged.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.metadata
import io
import json
import re
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

from offline_socket_probe import ATTEMPTS, install_guard


def guide_nodes(text: str) -> tuple[dict[str, ast.FunctionDef], ast.Assign, ast.Assign]:
    nodes = [
        node
        for fence in re.findall(r"```python\n(.*?)\n```", text, re.DOTALL)
        for node in ast.parse(fence).body
    ]
    functions = {node.name: node for node in nodes if isinstance(node, ast.FunctionDef)}
    assignments = {
        target.id: node
        for node in nodes
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    objectives = assignments["OBJECTIVES"]
    condition_names = {
        node.test.id
        for node in ast.walk(objectives)
        if isinstance(node, ast.IfExp) and isinstance(node.test, ast.Name)
    }
    if len(condition_names) != 1:
        raise AssertionError("the guide must declare one cost-availability condition")
    return functions, assignments[condition_names.pop()], objectives


def compile_journey(
    text: str, *, reported_cost: float | None = None
) -> tuple[dict, list]:
    import test_skill_package as guide_fixture
    import traigent
    from traigent.api.decorators import EvaluationOptions
    from traigent.core.objectives import ObjectiveDefinition, ObjectiveSchema

    functions, cost_available, objectives = guide_nodes(text)
    placed: list[dict] = []

    def provider(**request):
        placed.append(request)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=request["messages"][0]["content"]),
                    finish_reason="stop",
                )
            ],
            usage=None,
            _hidden_params={"response_cost": reported_cost},
        )

    def build_request(message, config):
        return {
            "model": "synthetic/provider",
            "messages": [{"role": "user", "content": config.get("answer", message)}],
        }

    def task_score(prediction, expected, input_data):
        # The guide deliberately preserves the customer's text-only contract.
        if not isinstance(prediction, str):
            raise TypeError("the preserved evaluator requires a text prediction")
        return float(prediction == expected)

    namespace = {
        "__name__": "sdk_unpriced_guide_fixture",
        "traigent": traigent,
        "EvaluationOptions": EvaluationOptions,
        "ObjectiveDefinition": ObjectiveDefinition,
        "ObjectiveSchema": ObjectiveSchema,
        "litellm": guide_fixture.litellm_module(provider),
        "build_request": build_request,
        "task_score": task_score,
        **guide_fixture.spend_gate_bindings(
            ceiling=0.21, remaining=0.21, per_call=0.05
        ),
    }
    body = [
        *guide_fixture.sdk_wrapper_state_nodes(text),
        functions["provider_reported_cost"],
        functions["require_untruncated_completion"],
        *guide_fixture.sdk_wrapper_spend_gate(text),
        functions["call_agent"],
        cost_available,
        objectives,
    ]
    # A mutation restoring the old helper must execute it, not fail at lookup.
    if "require_nonzero_token_usage" in functions:
        body.insert(0, functions["require_nonzero_token_usage"])
    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    exec(compile(module, "<guide-call-path>", "exec"), namespace)  # noqa: S102
    return namespace, placed


def schema_values(schema) -> list[dict]:
    return [
        {"name": item.name, "orientation": item.orientation, "weight": item.weight}
        for item in schema.objectives
    ]


def run(text: str, record: dict) -> None:
    import traigent
    from test_skill_package import pinned_sdk_version

    record["sdk_version"] = importlib.metadata.version("traigent")
    record["pinned_sdk_version"] = pinned_sdk_version()
    record["sdk_module"] = traigent.__file__
    record["phase"] = "compile-guide"
    namespace, placed = compile_journey(text)
    functions, cost_available, objective_node = guide_nodes(text)
    record["primary_schema"] = schema_values(namespace["OBJECTIVES"])

    known_namespace = {
        cost_available.targets[0].id: True,
        "ObjectiveDefinition": namespace["ObjectiveDefinition"],
        "ObjectiveSchema": namespace["ObjectiveSchema"],
    }
    exec(  # noqa: S102
        compile(
            ast.Module(body=[objective_node], type_ignores=[]), "<known-cost>", "exec"
        ),
        known_namespace,
    )
    record["known_cost_schema"] = schema_values(known_namespace["OBJECTIVES"])

    dataset = Path("rows.jsonl").resolve()
    dataset.write_text(
        "".join(
            json.dumps(
                {
                    "example_id": str(row),
                    "input": {"message": f"synthetic row {row}"},
                    "expected_output": "correct",
                }
            )
            + "\n"
            for row in (1, 2)
        ),
        encoding="utf-8",
    )
    namespace.update(
        ENHANCED_SPACE={"answer": ["incorrect", "correct"]},
        TUNING_DATASET=str(dataset),
    )
    exec(  # noqa: S102
        compile(
            ast.Module(body=[functions["agent"]], type_ignores=[]),
            "<guide-agent>",
            "exec",
        ),
        namespace,
    )
    agent = namespace["agent"]
    namespace["TRACKED_RUN"] = agent
    record["phase"] = "optimization"
    result = agent.optimize_sync(algorithm="grid", max_trials=2, progress_bar=False)
    record["journey"] = {
        "objectives": result.objectives,
        "best_config": (
            dict(result.best_config) if result.best_config is not None else None
        ),
        "trials": [
            {
                "config": dict(trial.config),
                "metrics": dict(trial.metrics),
                "successful": trial.is_successful,
            }
            for trial in result.trials
        ],
        "provider_fixture_calls": len(placed),
        "reported_costs": list(namespace["RUN_CALL_COSTS"]),
        "budget_debits": list(namespace["RUN_SPEND_USD"]),
        "remaining": namespace["run_remaining_usd"](),
    }
    record["phase"] = "budget-refusal"
    try:
        namespace["call_agent"]("an extra row", {"answer": "correct"})
    except RuntimeError as error:
        record["budget_refusal"] = str(error)
    else:
        record["budget_refusal"] = None
    record["calls_after_refusal"] = len(placed)
    spend_report = io.StringIO()
    with contextlib.redirect_stdout(spend_report):
        namespace["report_run_spend"]()
    record["spend_report"] = spend_report.getvalue()

    record["phase"] = "known-cost-without-usage"
    known, known_placed = compile_journey(text, reported_cost=0.125)
    output, cost = known["call_agent"]("known cost without usage", {})
    record["known_cost_call"] = {
        "output": output,
        "cost": cost,
        "reported_costs": known["RUN_CALL_COSTS"],
        "budget_debits": known["RUN_SPEND_USD"],
        "provider_fixture_calls": len(known_placed),
    }
    record["phase"] = "complete"


def main() -> int:
    install_guard()
    text = sys.stdin.read()
    record = {
        "guide_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "phase": "imports",
    }
    sdk_output = io.StringIO()
    try:
        with contextlib.redirect_stdout(sdk_output):
            run(text, record)
    except Exception as error:
        record["error"] = {"type": type(error).__name__, "message": str(error)}
        traceback.print_exc()
    record["network_attempts"] = ATTEMPTS
    record["sdk_stdout"] = sdk_output.getvalue()
    print(json.dumps(record, default=str))
    return int("error" in record)


if __name__ == "__main__":
    raise SystemExit(main())

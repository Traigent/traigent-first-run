#!/usr/bin/env python3
"""Exercise actual SDK mock interception under the existing socket guard."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path

from offline_socket_probe import ATTEMPTS, install_guard


def main() -> None:
    install_guard()
    root = Path(os.environ["TRAIGENT_RESULTS_FOLDER"])
    root.mkdir(parents=True, exist_ok=True)
    dataset = root / "dataset.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "example_id": "one",
                "input": {"message": "Which queue handles this billing question?"},
                "expected_output": "billing",
            }
        )
        + "\n"
    )
    mode = os.environ["PROBE_MOCK_MODE"]
    captured = io.StringIO()
    calls = []
    responses = []
    trials = []
    error = None
    error_detail = None
    active = False
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            import traigent
            from traigent.api.decorators import EvaluationOptions
            from traigent.core import objectives
            from traigent.utils.env_config import is_mock_llm

            if mode in {"api", "raw"}:
                prelude = Path(os.environ["PROBE_MOCK_PRELUDE_PATH"]).read_text()
                exec(compile(prelude, "documented-mock-prelude", "exec"), {})
            active = is_mock_llm()

            import litellm

            def score(prediction: str, expected: str, input_data: dict) -> float:
                del input_data
                return float(prediction == expected)

            @traigent.optimize(
                objectives=objectives.ObjectiveSchema.from_objectives(
                    [
                        objectives.ObjectiveDefinition(
                            name="score", orientation="maximize", weight=1.0
                        )
                    ]
                ),
                configuration_space={"style": ["plain", "careful"]},
                evaluation=EvaluationOptions(
                    eval_dataset=str(dataset), metric_functions={"score": score}
                ),
            )
            def agent(message: str) -> str:
                style = traigent.get_config()["style"]
                messages = [
                    {"role": "system", "content": f"Route this request: {style}."},
                    {"role": "user", "content": message},
                ]
                calls.append({"style": style, "messages": messages})
                if mode == "raw":
                    from openai import OpenAI

                    client = OpenAI(
                        api_key="offline-test-not-a-real-key",  # placeholder fixture
                        max_retries=0,
                    )
                    response = client.chat.completions.create(
                        model="gpt-4.1-mini", messages=messages, timeout=1
                    )
                else:
                    response = litellm.completion(
                        model="gpt-4.1-mini",
                        messages=messages,
                        num_retries=0,
                        timeout=1,
                        **(
                            {"api_key": "offline-test-not-a-real-key"}
                            if mode == "old-flags"
                            else {}
                        ),
                    )
                responses.append(
                    {"id": response.id, "content": response.choices[0].message.content}
                )
                return response.choices[0].message.content

            result = agent.optimize_sync(
                algorithm="grid",
                configuration_space={"style": ["plain", "careful"]},
                max_trials=2,
                save_to=str(root / "result.json"),
            )
            trials = [
                {
                    "config": dict(trial.config),
                    "metrics": dict(trial.metrics),
                    "successful": trial.is_successful,
                }
                for trial in result.trials
            ]
    except BaseException as caught:
        error = type(caught).__name__
        error_detail = str(caught)
    print(
        json.dumps(
            {
                "mode": mode,
                "active": active,
                "calls": calls,
                "responses": responses,
                "trials": trials,
                "error": error,
                "error_detail": error_detail,
                "attempts": ATTEMPTS,
                "diagnostic": captured.getvalue(),
            }
        )
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Exercise the pinned SDK baseline with a stored CLI credential and socket guard."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path

from offline_socket_probe import ATTEMPTS, install_guard

home = Path(os.environ["HOME"])
credential_dir = home / ".traigent"
credential_dir.mkdir(parents=True, exist_ok=True)
credential_path = credential_dir / "credentials.json"
credential_path.write_text(json.dumps({"api_key": "PRIVATE_SENTINEL"}))
credential_path.chmod(0o600)

dataset = Path(os.environ["TRAIGENT_DATASET_ROOT"]) / "baseline.jsonl"
dataset.parent.mkdir(parents=True, exist_ok=True)
dataset.write_text(
    json.dumps(
        {
            "example_id": "one",
            "input": {"message": "hello"},
            "expected_output": "ok",
        }
    )
    + "\n"
)

install_guard()

error: BaseException | None = None
trials = 0
cloud_url = None
stored_key_resolved = False
captured = io.StringIO()
try:
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        import traigent
        from traigent.api.decorators import EvaluationOptions
        from traigent.config.backend_config import BackendConfig
        from traigent.core.objectives import ObjectiveDefinition, ObjectiveSchema

        stored_key_resolved = BackendConfig.get_api_key() == "PRIVATE_SENTINEL"
        objectives = ObjectiveSchema.from_objectives(
            [ObjectiveDefinition(name="score", orientation="maximize", weight=1.0)]
        )

        def score(prediction: str, expected: str, input_data: dict) -> float:
            del input_data
            return float(prediction == expected)

        @traigent.optimize(
            objectives=objectives,
            configuration_space={"style": ["a", "b"]},
            evaluation=EvaluationOptions(
                eval_dataset=str(dataset),
                metric_functions={"score": score},
            ),
        )
        def agent(_message: str) -> str:
            traigent.get_config()
            return "ok"

        result = agent.optimize_sync(
            algorithm="grid",
            configuration_space={"style": ["a", "b"]},
            max_trials=2,
            save_to=str(Path(os.environ["TRAIGENT_RESULTS_FOLDER"]) / "result.json"),
        )
        trials = len(result.trials)
        cloud_url = result.cloud_url
except BaseException as caught:  # the parent asserts the exact safe boundary
    error = caught

print(
    json.dumps(
        {
            "attempts": ATTEMPTS,
            "cloud_url": cloud_url,
            "error": type(error).__name__ if error is not None else None,
            "offline": os.environ.get("TRAIGENT_OFFLINE_MODE"),
            "stored_key_resolved": stored_key_resolved,
            "trials": trials,
        }
    )
)

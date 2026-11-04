"""Retain paid observations while the real baseline safety boundary stops calls."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RUNTIME = (
    Path(__file__).resolve().parents[1]
    / "skills/traigent-first-run/assets/first_run_runtime.py"
)


class BaselineSafetyStopTests(unittest.TestCase):
    def run_fixture(self, costs, *, stop_before=False, scorer_calls=0, fail_row=False):
        spec = importlib.util.spec_from_file_location("baseline_stop_runtime", RUNTIME)
        runtime = importlib.util.module_from_spec(spec)
        with (
            mock.patch.dict(sys.modules, {spec.name: runtime}),
            mock.patch.object(sys, "dont_write_bytecode", True),
        ):
            spec.loader.exec_module(runtime)
        runtime.RUN_COST_CEILING_USD = runtime.RUN_COST_REMAINING_USD = (
            2.0 if scorer_calls else 1.0
        )
        runtime.UNTRACKED_CALL_COST_USD = 0.1
        attempts, placed = [], []
        charges = iter(costs)

        @runtime.halting
        def agent(text, model):
            attempts.append((model, text))
            if stop_before:
                raise runtime.SafetyRefusal("PRIVATE_PROVIDER_DETAIL")
            slot = runtime.reserve_call_spend((), {"model": model, "max_retries": 0})
            placed.append((model, text))
            runtime.settle_call_spend(slot, next(charges))
            if fail_row and text == "second":
                raise ValueError("PRIVATE_ROW_DETAIL")
            return text

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runs = project / "traigent-runs"
            runs.mkdir()
            (project / "rows.json").write_text(
                json.dumps(
                    [
                        {"id": 0, "input": "first", "expected": "first"},
                        {"id": 1, "input": "second", "expected": "second"},
                    ]
                )
            )
            bridge = runtime.Bridge(
                {
                    "dataset": {
                        "path": "rows.json",
                        "input": "input",
                        "expected": "expected",
                        "id": "id",
                    },
                    "agent": {
                        "args": {"text": "$input", "model": "$config.model"},
                        "calls_per_row": 1,
                    },
                    "evaluator": {
                        "args": {"output": "$output", "expected": "$expected"},
                        "calls_per_row": scorer_calls,
                    },
                    "baseline": {
                        "config": {"model": "a"},
                        "space": {"model": ["a", "b", "c"]},
                    },
                },
                runs,
            )
            bridge._functions = {
                "agent": agent,
                "evaluator": lambda output, expected: float(output == expected),
            }

            def start():
                bridge.started = bridge.ledgered = True

            output = io.StringIO()
            with (
                mock.patch.object(bridge, "start", start),
                mock.patch.dict(
                    os.environ, {"TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS": "60"}
                ),
                contextlib.redirect_stdout(output),
            ):
                status = bridge.run_baseline()
            document = json.loads((runs / "baseline-results.json").read_text())
        return (
            status,
            document,
            attempts,
            placed,
            runtime.RUN_SPEND_USD,
            output.getvalue(),
        )

    def test_budget_stop_retains_complete_and_partial_configurations(self):
        status, document, attempts, placed, ledger, output = self.run_fixture(
            [0.2, 0.2, 0.55]
        )
        self.assertEqual(status, 3)
        self.assertFalse(document["complete"])
        self.assertEqual(document["stop_reason"], "safety_refusal")
        self.assertEqual([r["n_scored"] for r in document["results"]], [2, 1])
        self.assertEqual([r["n_unfinished"] for r in document["results"]], [0, 1])
        self.assertEqual([r["n_failed"] for r in document["results"]], [0, 0])
        self.assertEqual([r["mean_score"] for r in document["results"]], [1.0, 1.0])
        self.assertEqual(document["results"][1]["rows"], [{"id": 0, "score": 1.0}])
        self.assertEqual(
            attempts, [("a", "first"), ("a", "second"), ("b", "first"), ("b", "second")]
        )
        self.assertEqual(placed, attempts[:-1])
        self.assertEqual(ledger, [0.2, 0.2, 0.55])
        self.assertEqual(document["provider_calls"], 3)
        self.assertEqual(document["budget_debit_usd"], 0.95)
        self.assertIn("stopped before any further spend", output)

    def test_zero_completion_stop_is_saved_without_raw_exception_text(self):
        status, document, attempts, placed, ledger, output = self.run_fixture(
            [], stop_before=True
        )
        self.assertEqual(status, 3)
        self.assertFalse(document["complete"])
        self.assertEqual(document["stop_reason"], "safety_refusal")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(placed, [])
        self.assertEqual(ledger, [])
        self.assertEqual(document["provider_calls"], 0)
        self.assertEqual(document["budget_debit_usd"], 0)
        self.assertEqual(len(document["results"]), 1)
        self.assertEqual(document["results"][0]["n_unfinished"], 2)
        self.assertIsNone(document["results"][0]["mean_score"])
        self.assertNotIn("PRIVATE_PROVIDER_DETAIL", json.dumps(document) + output)

    def test_stop_retains_ordinary_failures_and_unknown_cost_reservations(self):
        status, document, attempts, placed, ledger, _ = self.run_fixture(
            [None, 0.3, 0.55], fail_row=True
        )
        self.assertEqual(status, 3)
        self.assertFalse(document["complete"])
        self.assertEqual(document["stop_reason"], "safety_refusal")
        self.assertEqual([r["n_scored"] for r in document["results"]], [1, 1])
        self.assertEqual([r["n_failed"] for r in document["results"]], [1, 0])
        self.assertEqual([r["n_unfinished"] for r in document["results"]], [0, 1])
        self.assertEqual(document["results"][0]["failure_types"], {"ValueError": 1})
        self.assertEqual(ledger, [0.1, 0.3, 0.55])
        self.assertEqual(document["budget_debit_usd"], 0.95)
        self.assertEqual(document["known_cost_usd"], 0.85)
        self.assertEqual(len(attempts), 4)
        self.assertEqual(placed, attempts[:-1])

    def test_accounting_stop_retains_paid_debit_without_calling_next_row(self):
        # A declared scorer call was never made. Bridge.score itself refuses;
        # the completed agent call remains paid but has no valid observation.
        status, document, attempts, placed, ledger, _ = self.run_fixture(
            [0.05], scorer_calls=1
        )
        self.assertEqual(status, 3)
        self.assertFalse(document["complete"])
        self.assertEqual(document["stop_reason"], "safety_refusal")
        self.assertEqual(attempts, [("a", "first")])
        self.assertEqual(placed, attempts)
        self.assertEqual(ledger, [0.05])
        self.assertEqual(document["budget_debit_usd"], 0.05)
        self.assertEqual(document["results"][0]["n_scored"], 0)
        self.assertEqual(document["results"][0]["n_failed"], 0)

    def test_completed_control_keeps_all_calls_and_success(self):
        status, document, attempts, placed, ledger, _ = self.run_fixture([0.05] * 6)
        self.assertEqual(status, 0)
        self.assertTrue(document["complete"])
        self.assertIsNone(document["stop_reason"])
        self.assertEqual(len(attempts), 6)
        self.assertEqual(placed, attempts)
        self.assertEqual(ledger, [0.05] * 6)
        self.assertEqual([r["n_scored"] for r in document["results"]], [2, 2, 2])
        self.assertEqual([r["n_unfinished"] for r in document["results"]], [0, 0, 0])

    def test_ordinary_row_failures_still_allow_later_configurations(self):
        status, document, attempts, placed, _, output = self.run_fixture(
            [0.05] * 6, fail_row=True
        )
        self.assertEqual(status, 3)
        self.assertFalse(document["complete"])
        self.assertIsNone(document["stop_reason"])
        self.assertEqual(len(attempts), 6)
        self.assertEqual(placed, attempts)
        self.assertEqual([r["n_scored"] for r in document["results"]], [1, 1, 1])
        self.assertEqual([r["n_failed"] for r in document["results"]], [1, 1, 1])
        self.assertEqual([r["n_unfinished"] for r in document["results"]], [0, 0, 0])
        self.assertEqual(document["results"][0]["failure_types"], {"ValueError": 1})
        self.assertNotIn("PRIVATE_ROW_DETAIL", json.dumps(document) + output)


if __name__ == "__main__":
    unittest.main()

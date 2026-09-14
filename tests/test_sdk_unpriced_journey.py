"""A usable unpriced guide journey must reach the pinned SDK and stay bounded."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_offline_socket_contract import _credential_stripped_environment

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests" / "fixtures" / "sdk_unpriced_journey_probe.py"
GUIDE = ROOT / "skills" / "traigent-first-run" / "references" / "sdk-execution.md"


def run_probe(guide_source: str | None = None) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        environment = {
            key: value
            for key, value in _credential_stripped_environment({}).items()
            if not key.startswith("TRAIGENT_")
        }
        environment.update(
            {
                "LITELLM_LOCAL_MODEL_COST_MAP": "true",
                "TRAIGENT_OFFLINE_MODE": "true",
                "TRAIGENT_COST_APPROVED": "true",
                "TRAIGENT_RUN_COST_LIMIT": "1.0",
                "TRAIGENT_RESULTS_FOLDER": directory,
                "TRAIGENT_LOG_EXAMPLE_CONTENT": "false",
                "TRAIGENT_AUTO_SYNC": "false",
                "PYTHONPATH": os.pathsep.join(
                    [str(ROOT / "tests"), str(ROOT / "tests" / "fixtures")]
                    + [str(Path(entry).resolve()) for entry in sys.path if entry]
                ),
            }
        )
        return subprocess.run(
            [sys.executable, str(PROBE)],
            input=(
                GUIDE.read_text(encoding="utf-8")
                if guide_source is None
                else guide_source
            ),
            cwd=directory,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )


class SDKUnpricedJourneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if importlib.util.find_spec("traigent") is None:
            message = "Install assets/requirements-first-run.txt to run the native SDK journey"
            if os.environ.get("CI"):
                raise AssertionError(message)
            raise unittest.SkipTest(message)
        cls.process = run_probe()

    def result(self) -> dict:
        self.assertEqual(
            self.process.returncode,
            0,
            f"Guide/SDK journey failed: stdout={self.process.stdout} stderr={self.process.stderr}",
        )
        result = json.loads(self.process.stdout)
        self.assertEqual(result["phase"], "complete")
        self.assertEqual(result["network_attempts"], [])
        self.assertEqual(result["sdk_version"], result["pinned_sdk_version"])
        return result

    def test_primary_only_guide_reaches_a_real_sdk_winner_without_vendor_metadata(
        self,
    ) -> None:
        result = self.result()
        self.assertEqual(
            result["primary_schema"],
            [{"name": "accuracy", "orientation": "maximize", "weight": 1.0}],
        )
        journey = result["journey"]
        self.assertEqual(journey["objectives"], ["accuracy"])
        self.assertEqual(journey["best_config"], {"answer": "correct"})
        self.assertEqual(len(journey["trials"]), 2)
        self.assertTrue(all(trial["successful"] for trial in journey["trials"]))
        self.assertEqual(
            {
                trial["config"]["answer"]: trial["metrics"]["accuracy"]
                for trial in journey["trials"]
            },
            {"incorrect": 0.0, "correct": 1.0},
        )
        self.assertEqual(journey["provider_fixture_calls"], 4)

    def test_unknown_vendor_cost_is_retained_and_the_guide_refuses_a_fifth_call(
        self,
    ) -> None:
        result = self.result()
        journey = result["journey"]
        self.assertEqual(journey["reported_costs"], [None] * 4)
        self.assertEqual(journey["budget_debits"], [0.05] * 4)
        self.assertAlmostEqual(journey["remaining"], 0.01)
        self.assertIsNotNone(result["budget_refusal"])
        self.assertIn("was not placed", result["budget_refusal"])
        self.assertEqual(result["calls_after_refusal"], 4)
        known_cost_line = next(
            line
            for line in result["spend_report"].splitlines()
            if line.startswith("Known call cost")
        )
        self.assertIn("not reported", known_cost_line)
        self.assertNotIn("$0.0000", known_cost_line)

    def test_known_cost_without_usage_and_the_priced_objective_schema_remain_available(
        self,
    ) -> None:
        result = self.result()
        self.assertEqual(
            result["known_cost_schema"],
            [
                {"name": "accuracy", "orientation": "maximize", "weight": 1.0},
                {"name": "cost", "orientation": "minimize", "weight": 1.0},
            ],
        )
        self.assertEqual(
            result["known_cost_call"],
            {
                "output": "known cost without usage",
                "cost": 0.125,
                "reported_costs": [0.125],
                "budget_debits": [0.125],
                "provider_fixture_calls": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()

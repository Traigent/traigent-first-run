from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "traigent-first-run" / "scripts" / "preflight.py"
SPEC = importlib.util.spec_from_file_location("first_run_preflight", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def synthetic_rows() -> list[dict]:
    difficulties = ("easy", "medium", "hard", "very-hard")
    rows = []
    for index in range(24):
        rows.append(
            {
                "id": f"walkthrough-{index:02d}",
                "input": f"scenario_{index} unique_token_{index} format_{index % 5}",
                "output": {
                    "label": f"class-{index % 4}",
                    "reason": f"rule-{index % 3}",
                },
                "source": "synthetic",
                "difficulty": difficulties[index // 6],
                "coverage": f"scenario-{index % 8}",
                "split": "tune" if index < 18 else "holdout",
            }
        )
    return rows


class StaticPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        MODULE.RESULTS.clear()

    def test_process_environment_overrides_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("TRAIGENT_RUN_COST_LIMIT=2.00\n")
            with mock.patch.dict(
                os.environ, {"TRAIGENT_RUN_COST_LIMIT": "7.00"}, clear=False
            ):
                effective, file_values = MODULE.read_env(env_path)
            self.assertEqual(effective["TRAIGENT_RUN_COST_LIMIT"], "7.00")
            self.assertEqual(file_values["TRAIGENT_RUN_COST_LIMIT"], "2.00")

    def test_synthetic_dataset_quality_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text(
                "\n".join(json.dumps(row) for row in synthetic_rows()) + "\n"
            )
            rows = MODULE.check_dataset(dataset)
        self.assertIsNotNone(rows)
        failures = [result for result in MODULE.RESULTS if result.status == MODULE.FAIL]
        self.assertEqual(failures, [])

    def test_duplicate_synthetic_input_fails(self) -> None:
        rows = synthetic_rows()
        rows[1]["input"] = rows[0]["input"]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        failures = [
            result.check for result in MODULE.RESULTS if result.status == MODULE.FAIL
        ]
        self.assertIn("dataset-duplicates", failures)

    def test_ast_binding_does_not_execute_module_top_level(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed.txt"
            agent = root / "agent.py"
            agent.write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('executed')\n"
                "def answer(question: str, tone: str = 'plain') -> str:\n"
                "    return question\n"
            )
            rows = [{"input": {"question": "hello"}, "output": "hello"}]
            MODULE.check_binding(rows, f"{agent}:answer")
            self.assertFalse(marker.exists())
            self.assertTrue(
                any(
                    result.check == "dataset-binding" and result.status == MODULE.PASS
                    for result in MODULE.RESULTS
                )
            )

    def test_required_agent_parameter_must_exist_in_every_dict_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text(
                "def answer(question: str, tone: str) -> str:\n" "    return question\n"
            )
            rows = [
                {"input": {"question": "hello", "tone": "plain"}, "output": "a"},
                {"input": {"question": "goodbye"}, "output": "b"},
            ]
            MODULE.check_binding(rows, f"{agent}:answer")
        self.assertTrue(
            any(
                result.check == "dataset-binding"
                and result.status == MODULE.FAIL
                and "rows [2]" in result.detail
                for result in MODULE.RESULTS
            )
        )

    def test_scalar_input_cannot_bind_multiple_required_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text(
                "def answer(question: str, tone: str) -> str:\n" "    return question\n"
            )
            rows = [{"input": "hello", "output": "a"}]
            MODULE.check_binding(rows, f"{agent}:answer")
        self.assertTrue(
            any(
                result.check == "dataset-binding" and result.status == MODULE.FAIL
                for result in MODULE.RESULTS
            )
        )

    def test_scorer_check_is_static_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed.txt"
            scorer = root / "scorer.py"
            scorer.write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('executed')\n"
                "def score(output, expected):\n"
                "    return 1.0 if output == expected else 0.0\n"
            )
            MODULE.check_scorer_signature(f"{scorer}:score")
            self.assertFalse(marker.exists())
            self.assertTrue(
                any(
                    result.check == "scorer-calibration"
                    and result.status == MODULE.SKIP
                    for result in MODULE.RESULTS
                )
            )

    def test_local_model_check_does_not_open_a_socket(self) -> None:
        with mock.patch(
            "socket.socket.connect",
            side_effect=AssertionError("network access attempted"),
        ):
            MODULE.check_models(["openai/gpt-4o-mini"])
        self.assertFalse(any(result.status == MODULE.FAIL for result in MODULE.RESULTS))


if __name__ == "__main__":
    unittest.main()

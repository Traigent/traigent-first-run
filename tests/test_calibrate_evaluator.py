from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "traigent-first-run" / "scripts" / "calibrate_evaluator.py"


class EvaluatorCalibrationTests(unittest.TestCase):
    def make_scorer(self, directory: str) -> Path:
        scorer = Path(directory) / "scorer.py"
        scorer.write_text(
            "def score(output, expected):\n"
            "    required = set(expected)\n"
            "    actual = set(output)\n"
            "    return len(required & actual) / len(required)\n"
        )
        return scorer

    def make_alias_scorer(self, directory: str) -> Path:
        scorer = Path(directory) / "alias_scorer.py"
        scorer.write_text(
            "def score(prediction, reference):\n"
            "    required = set(reference)\n"
            "    actual = set(prediction)\n"
            "    return len(required & actual) / len(required)\n"
        )
        return scorer

    def make_case_dependent_scorer(self, directory: str) -> Path:
        scorer = Path(directory) / "case_dependent_scorer.py"
        scorer.write_text(
            "def score(output, expected, input_data, metadata):\n"
            "    if metadata['family'] == 'extraction' and "
            "input_data['format'] == 'fields':\n"
            "        required = set(expected)\n"
            "        actual = set(output)\n"
            "        return len(required & actual) / len(required)\n"
            "    return 1.0\n"
        )
        return scorer

    def make_constant_scorer(self, directory: str, expression: str) -> Path:
        scorer = Path(directory) / "constant_scorer.py"
        scorer.write_text("def score(output, expected):\n" f"    return {expression}\n")
        return scorer

    def command(self, scorer: Path) -> list[str]:
        return [
            sys.executable,
            str(SCRIPT),
            "--scorer",
            f"{scorer}:score",
            "--good",
            '["name", "email", "phone", "city"]',
            "--equivalent-good",
            '["city", "phone", "email", "name"]',
            "--partial",
            '["name", "email"]',
            "--bad",
            '["unrelated"]',
            "--expected",
            '["name", "email", "phone", "city"]',
            "--json",
        ]

    def test_refuses_execution_without_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(
                self.command(self.make_scorer(directory)),
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 2)
        self.assertIn("--allow-execution", process.stderr)

    def test_four_probe_ordering_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(
                [*self.command(self.make_scorer(directory)), "--allow-execution"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertTrue(payload["passed"])
        self.assertGreater(payload["scores"]["partial"], payload["scores"]["bad"])

    def test_rejects_aliases_that_real_sdk_cannot_bind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(
                [
                    *self.command(self.make_alias_scorer(directory)),
                    "--allow-execution",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 1)
        self.assertIn("explicit 'output'", process.stderr)

    def test_matrix_fails_when_a_case_dependent_scorer_only_passes_first_case(
        self,
    ) -> None:
        cases = [
            {
                "name": "field extraction",
                "expected": ["name", "email", "phone", "city"],
                "input_data": {"format": "fields"},
                "metadata": {"family": "extraction"},
                "probes": {
                    "good": ["name", "email", "phone", "city"],
                    "equivalent_good": ["city", "phone", "email", "name"],
                    "partial": ["name", "email"],
                    "bad": ["unrelated"],
                },
            },
            {
                "name": "sentiment classification",
                "expected": "positive",
                "input_data": {"format": "label"},
                "metadata": {"family": "classification"},
                "probes": {
                    "good": "positive",
                    "equivalent_good": "POSITIVE",
                    "partial": "mixed",
                    "bad": "negative",
                },
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            cases_path = Path(directory) / "cases.json"
            cases_path.write_text(json.dumps(cases))
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{self.make_case_dependent_scorer(directory)}:score",
                    "--cases",
                    f"@{cases_path}",
                    "--allow-execution",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 1, process.stderr)
        payload = json.loads(process.stdout)
        self.assertFalse(payload["passed"])
        self.assertTrue(payload["cases"][0]["passed"])
        self.assertFalse(payload["cases"][1]["passed"])
        self.assertEqual(
            [case["name"] for case in payload["cases"]],
            ["field extraction", "sentiment classification"],
        )

    def test_rejects_scores_outside_normalized_finite_contract(self) -> None:
        invalid_scores = {
            "non-finite": "float('nan')",
            "above-one": "1.01",
            "below-zero": "-0.01",
        }
        for label, expression in invalid_scores.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                process = subprocess.run(
                    [
                        *self.command(self.make_constant_scorer(directory, expression)),
                        "--allow-execution",
                    ],
                    capture_output=True,
                    text=True,
                )
            self.assertEqual(process.returncode, 1)
            self.assertIn("score contract requires", process.stderr)
            self.assertIn("[0,1]", process.stderr)

    def test_llm_judge_requires_paid_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(
                [
                    *self.command(self.make_scorer(directory)),
                    "--allow-execution",
                    "--kind",
                    "llm-judge",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 2)
        self.assertIn("--paid-approved", process.stderr)

    def test_paid_approved_judge_path_can_execute(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(
                [
                    *self.command(self.make_scorer(directory)),
                    "--allow-execution",
                    "--kind",
                    "llm-judge",
                    "--paid-approved",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)


if __name__ == "__main__":
    unittest.main()

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
            "def score(output, expected, input_data=None, metadata=None):\n"
            "    required = set(expected)\n"
            "    actual = set(output)\n"
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
        scorer.write_text(
            "def score(output, expected, input_data=None, metadata=None):\n"
            f"    return {expression}\n"
        )
        return scorer

    def make_exact_label_scorer(self, directory: str) -> Path:
        scorer = Path(directory) / "exact_label_scorer.py"
        scorer.write_text(
            "def score(output, expected, input_data=None, metadata=None):\n"
            "    return float(output.casefold() == expected.casefold())\n"
        )
        return scorer

    def make_surface_penalty_scorer(self, directory: str) -> Path:
        scorer = Path(directory) / "surface_penalty_scorer.py"
        scorer.write_text(
            "def score(output, expected, input_data=None, metadata=None):\n"
            "    if output == expected:\n"
            "        return 1.0\n"
            "    if output.casefold() == expected.casefold():\n"
            "        return 0.8\n"
            "    return 0.0\n"
        )
        return scorer

    def make_mixed_mode_scorer(self, directory: str) -> Path:
        scorer = Path(directory) / "mixed_mode_scorer.py"
        scorer.write_text(
            "def score(output, expected, input_data=None, metadata=None):\n"
            "    if isinstance(expected, list):\n"
            "        required = set(expected)\n"
            "        actual = set(output)\n"
            "        return len(required & actual) / len(required)\n"
            "    return float(output.casefold() == expected.casefold())\n"
        )
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
        self.assertEqual(payload["score_mode"], "graded")
        self.assertGreater(payload["scores"]["partial"], payload["scores"]["bad"])
        self.assertIn("partial_is_above_bad", payload["checks"])

    def test_default_import_root_supports_project_and_scorer_sibling_imports(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            scorer_directory = project_root / "traigent-runs"
            scorer_directory.mkdir()
            (project_root / "project_eval.py").write_text(
                "def field_coverage(output, expected):\n"
                "    required = set(expected)\n"
                "    return len(required & set(output)) / len(required)\n"
            )
            (scorer_directory / "scorer_context.py").write_text(
                "from pathlib import Path\n\n"
                "def cwd_matches_scorer():\n"
                "    return Path.cwd() == Path(__file__).resolve().parent\n"
            )
            scorer = scorer_directory / "evaluator.py"
            scorer.write_text(
                "from project_eval import field_coverage\n"
                "from scorer_context import cwd_matches_scorer\n\n"
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    assert cwd_matches_scorer()\n"
                "    return field_coverage(output, expected)\n"
            )
            process = subprocess.run(
                [
                    *self.command(Path("traigent-runs/evaluator.py")),
                    "--allow-execution",
                ],
                capture_output=True,
                text=True,
                cwd=project_root,
            )
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_explicit_import_root_supports_project_module_from_another_cwd(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outer_directory = Path(directory)
            project_root = outer_directory / "project"
            scorer_directory = project_root / "traigent-runs"
            scorer_directory.mkdir(parents=True)
            (project_root / "project_eval.py").write_text(
                "def field_coverage(output, expected):\n"
                "    required = set(expected)\n"
                "    return len(required & set(output)) / len(required)\n"
            )
            scorer = scorer_directory / "evaluator.py"
            scorer.write_text(
                "from project_eval import field_coverage\n\n"
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    return field_coverage(output, expected)\n"
            )
            process = subprocess.run(
                [
                    *self.command(scorer),
                    "--import-root",
                    str(project_root),
                    "--allow-execution",
                ],
                capture_output=True,
                text=True,
                cwd=outer_directory,
            )
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_import_root_must_be_an_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            not_a_directory = root / "not-a-directory"
            not_a_directory.write_text("content")
            for invalid_root in (root / "missing", not_a_directory):
                with self.subTest(import_root=invalid_root):
                    process = subprocess.run(
                        [
                            *self.command(self.make_scorer(directory)),
                            "--import-root",
                            str(invalid_root),
                            "--allow-execution",
                        ],
                        capture_output=True,
                        text=True,
                    )
                self.assertEqual(process.returncode, 2)
                self.assertIn("--import-root", process.stderr)
                self.assertIn("existing directory", process.stderr)

    def test_awaits_async_function_and_sync_returned_awaitable(self) -> None:
        scorers = {
            "async-function": (
                "async def score(output, expected, input_data=None, metadata=None):\n"
                "    return len(set(output) & set(expected)) / len(set(expected))\n"
            ),
            "returned-awaitable": (
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    async def calculate():\n"
                "        return len(set(output) & set(expected)) / len(set(expected))\n"
                "    return calculate()\n"
            ),
        }
        for label, source in scorers.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                scorer = Path(directory) / "async_scorer.py"
                scorer.write_text(source)
                process = subprocess.run(
                    [*self.command(scorer), "--allow-execution"],
                    capture_output=True,
                    text=True,
                )
            self.assertEqual(process.returncode, 0, process.stderr)

    def test_requires_explicit_calibration_adapter_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "unbound_scorer.py"
            scorer.write_text(
                "def score(*, unsupported_required):\n"
                "    return float(bool(unsupported_required))\n"
            )
            process = subprocess.run(
                [*self.command(scorer), "--allow-execution"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 1)
        self.assertIn("TypeError:", process.stderr)
        self.assertIn(
            "calibration adapter must accept keyword arguments", process.stderr
        )
        self.assertIn("instead of relying on SDK callback aliases", process.stderr)

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
        self.assertEqual(
            [case["score_mode"] for case in payload["cases"]],
            ["graded", "graded"],
        )
        self.assertEqual(
            payload["coverage_note"],
            "Distinct names and payloads are structural checks only; calibration "
            "relies on the coding assistant's recorded evidence-backed "
            "semantic-coverage review of materially distinct inputs, outcome "
            "classes, and rubric/schema branches, including mode/threshold "
            "rationale, gaps, and verdict.",
        )
        self.assertNotIn("human review", payload["coverage_note"])

    def test_matrix_help_uses_assistant_semantic_coverage_review(self) -> None:
        process = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        normalized_help = " ".join(process.stdout.split())
        self.assertIn(
            "Structural distinctness does not replace the coding assistant's "
            "recorded evidence-backed semantic-coverage review of material task "
            "branches",
            normalized_help,
        )
        self.assertNotIn("human review", normalized_help.casefold())

    def test_binary_exact_label_calibration_accepts_no_partial_credit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{self.make_exact_label_scorer(directory)}:score",
                    "--good",
                    '"positive"',
                    "--equivalent-good",
                    '"POSITIVE"',
                    "--partial",
                    '"mixed"',
                    "--bad",
                    '"negative"',
                    "--expected",
                    '"positive"',
                    "--score-mode",
                    "binary",
                    "--allow-execution",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["score_mode"], "binary")
        self.assertTrue(payload["checks"]["partial_fails"])
        self.assertNotIn("partial_is_above_bad", payload["checks"])

    def test_binary_mode_rejects_a_bad_probe_that_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{self.make_exact_label_scorer(directory)}:score",
                    "--good",
                    '"positive"',
                    "--equivalent-good",
                    '"POSITIVE"',
                    "--partial",
                    '"mixed"',
                    "--bad",
                    '"positive"',
                    "--expected",
                    '"positive"',
                    "--score-mode",
                    "binary",
                    "--allow-execution",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 1, process.stderr)
        payload = json.loads(process.stdout)
        self.assertFalse(payload["passed"])
        self.assertFalse(payload["checks"]["bad_fails"])

    def test_binary_mode_rejects_excess_surface_form_penalty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{self.make_surface_penalty_scorer(directory)}:score",
                    "--good",
                    '"positive"',
                    "--equivalent-good",
                    '"POSITIVE"',
                    "--partial",
                    '"mixed"',
                    "--bad",
                    '"negative"',
                    "--expected",
                    '"positive"',
                    "--score-mode",
                    "binary",
                    "--allow-execution",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 1, process.stderr)
        payload = json.loads(process.stdout)
        self.assertEqual(payload["scores"]["good"], 1.0)
        self.assertEqual(payload["scores"]["equivalent_good"], 0.8)
        self.assertTrue(payload["checks"]["equivalent_is_accepted"])
        self.assertFalse(payload["checks"]["equivalent_matches_good"])
        self.assertFalse(payload["passed"])

    def test_graded_default_keeps_strict_partial_separation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{self.make_exact_label_scorer(directory)}:score",
                    "--good",
                    '"positive"',
                    "--equivalent-good",
                    '"POSITIVE"',
                    "--partial",
                    '"mixed"',
                    "--bad",
                    '"negative"',
                    "--expected",
                    '"positive"',
                    "--allow-execution",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 1, process.stderr)
        payload = json.loads(process.stdout)
        self.assertEqual(payload["score_mode"], "graded")
        self.assertFalse(payload["checks"]["partial_is_above_bad"])

    def test_matrix_can_mix_graded_and_binary_score_modes(self) -> None:
        cases = [
            {
                "name": "graded extraction",
                "score_mode": "graded",
                "expected": ["name", "email", "phone", "city"],
                "probes": {
                    "good": ["name", "email", "phone", "city"],
                    "equivalent_good": ["city", "phone", "email", "name"],
                    "partial": ["name", "email"],
                    "bad": ["unrelated"],
                },
            },
            {
                "name": "binary sentiment",
                "score_mode": "binary",
                "expected": "positive",
                "probes": {
                    "good": "positive",
                    "equivalent_good": "POSITIVE",
                    "partial": "mixed",
                    "bad": "negative",
                },
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{self.make_mixed_mode_scorer(directory)}:score",
                    "--cases",
                    json.dumps(cases),
                    "--allow-execution",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertTrue(payload["passed"])
        self.assertEqual(
            [case["score_mode"] for case in payload["cases"]],
            ["graded", "binary"],
        )
        self.assertTrue(all(case["passed"] for case in payload["cases"]))

    def test_rejects_unknown_or_malformed_score_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scorer = self.make_exact_label_scorer(directory)
            single_process = subprocess.run(
                [
                    *self.command(scorer),
                    "--score-mode",
                    "unknown",
                    "--allow-execution",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(single_process.returncode, 2)
            self.assertIn("invalid choice", single_process.stderr)

            for invalid_mode in ("unknown", {"kind": "binary"}):
                with self.subTest(invalid_mode=invalid_mode):
                    cases = [
                        {
                            "name": "invalid mode",
                            "score_mode": invalid_mode,
                            "expected": "positive",
                            "probes": {
                                "good": "positive",
                                "equivalent_good": "POSITIVE",
                                "partial": "mixed",
                                "bad": "negative",
                            },
                        },
                        {
                            "name": "second case",
                            "expected": "negative",
                            "probes": {
                                "good": "negative",
                                "equivalent_good": "NEGATIVE",
                                "partial": "mixed",
                                "bad": "positive",
                            },
                        },
                    ]
                    matrix_process = subprocess.run(
                        [
                            sys.executable,
                            str(SCRIPT),
                            "--scorer",
                            f"{scorer}:score",
                            "--cases",
                            json.dumps(cases),
                            "--allow-execution",
                        ],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(matrix_process.returncode, 2)
                    self.assertIn("score_mode must be one of", matrix_process.stderr)

    def test_matrix_requires_two_distinct_named_case_payloads(self) -> None:
        base_case = {
            "name": "Branch One",
            "expected": ["a", "b"],
            "probes": {
                "good": ["a", "b"],
                "equivalent_good": ["b", "a"],
                "partial": ["a"],
                "bad": ["z"],
            },
        }
        invalid_case_sets = {
            "one case": [base_case],
            "normalized duplicate names": [
                base_case,
                {
                    **base_case,
                    "name": "  branch   one ",
                    "expected": ["c", "d"],
                    "probes": {
                        "good": ["c", "d"],
                        "equivalent_good": ["d", "c"],
                        "partial": ["c"],
                        "bad": ["z"],
                    },
                },
            ],
            "duplicate payloads": [base_case, {**base_case, "name": "Branch Two"}],
        }
        for label, cases in invalid_case_sets.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                scorer = self.make_scorer(directory)
                process = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--scorer",
                        f"{scorer}:score",
                        "--cases",
                        json.dumps(cases),
                        "--allow-execution",
                    ],
                    capture_output=True,
                    text=True,
                )
            self.assertEqual(process.returncode, 2)
            self.assertIn("Invalid calibration cases", process.stderr)

    def test_matrix_rejects_same_payload_with_different_score_modes(self) -> None:
        base_case = {
            "name": "Graded branch",
            "score_mode": "graded",
            "expected": ["a", "b"],
            "input_data": {"branch": "same"},
            "metadata": {"rubric": "same"},
            "probes": {
                "good": ["a", "b"],
                "equivalent_good": ["b", "a"],
                "partial": ["a"],
                "bad": ["z"],
            },
        }
        cases = [
            base_case,
            {
                **base_case,
                "name": "Binary branch",
                "score_mode": "binary",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{self.make_scorer(directory)}:score",
                    "--cases",
                    json.dumps(cases),
                    "--allow-execution",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 2)
        self.assertIn("Invalid calibration cases", process.stderr)
        self.assertIn("names and score modes alone", process.stderr)

    def test_custom_thresholds_are_validated_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "threshold_scorer.py"
            scorer.write_text(
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    return {'good': 0.70, 'equivalent': 0.65, "
                "'partial': 0.40, 'bad': 0.30}[output]\n"
            )
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{scorer}:score",
                    "--good",
                    "good",
                    "--equivalent-good",
                    "equivalent",
                    "--partial",
                    "partial",
                    "--bad",
                    "bad",
                    "--expected",
                    "expected",
                    "--good-minimum",
                    "0.60",
                    "--bad-maximum",
                    "0.35",
                    "--equivalence-tolerance",
                    "0.10",
                    "--separation-margin",
                    "0.05",
                    "--allow-execution",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertEqual(
            payload["thresholds"],
            {
                "bad_maximum": 0.35,
                "equivalence_tolerance": 0.1,
                "good_minimum": 0.6,
                "separation_margin": 0.05,
            },
        )

    def test_rejects_invalid_or_incoherent_thresholds(self) -> None:
        invalid_arguments = (
            ("--good-minimum", "nan"),
            ("--bad-maximum", "-0.1"),
            ("--good-minimum", "0.2", "--bad-maximum", "0.2"),
            (
                "--good-minimum",
                "0.8",
                "--bad-maximum",
                "0.2",
                "--separation-margin",
                "0.51",
            ),
        )
        for arguments in invalid_arguments:
            with self.subTest(
                arguments=arguments
            ), tempfile.TemporaryDirectory() as directory:
                process = subprocess.run(
                    [
                        *self.command(self.make_scorer(directory)),
                        *arguments,
                        "--allow-execution",
                    ],
                    capture_output=True,
                    text=True,
                )
            self.assertEqual(process.returncode, 2)

    def test_timeout_must_be_strictly_positive(self) -> None:
        for value in ("0", "-1"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                process = subprocess.run(
                    [
                        *self.command(self.make_scorer(directory)),
                        "--timeout",
                        value,
                        "--allow-execution",
                    ],
                    capture_output=True,
                    text=True,
                )
            self.assertEqual(process.returncode, 2)
            self.assertIn("greater than zero", process.stderr)

    def test_evaluator_exception_keeps_type_and_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "raising_scorer.py"
            scorer.write_text(
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    raise ValueError('rubric label missing')\n"
            )
            process = subprocess.run(
                [*self.command(scorer), "--allow-execution"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 1)
        self.assertIn("ValueError: rubric label missing", process.stderr)
        self.assertNotIn("score contract", process.stderr)

    def test_nonnumeric_return_uses_score_contract_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "nonnumeric_scorer.py"
            scorer.write_text(
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    return {'grade': 'pass'}\n"
            )
            process = subprocess.run(
                [*self.command(scorer), "--allow-execution"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 1)
        self.assertIn("TypeError: score contract requires", process.stderr)
        self.assertIn("got dict", process.stderr)

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


class TimeoutIsReportableTests(unittest.TestCase):
    """A slow evaluator must be legible to the scorer, not just to stderr.

    `readiness.py` carries an `evaluator-timeout (45)` cap gated on a `timed_out`
    key that nothing ever wrote: on timeout this script exited non-zero with no
    JSON at all. The one condition it has a dedicated cap and ceiling for could
    never fire, and a slow evaluator - an LLM judge, a subprocess-heavy scorer -
    surfaced as a generic calibration failure (traigent-first-run#71).
    """

    CASES = [
        {
            "name": "field extraction",
            "expected": ["name", "email"],
            "input_data": {"format": "fields"},
            "probes": {
                "good": ["name", "email"],
                "equivalent_good": ["email", "name"],
                "partial": ["name"],
                "bad": ["unrelated"],
            },
        },
        {
            "name": "sentiment",
            "expected": "positive",
            "input_data": {"format": "label"},
            "probes": {
                "good": "positive",
                "equivalent_good": "POSITIVE",
                "partial": "mixed",
                "bad": "negative",
            },
        },
    ]

    def _run_slow_calibration(self, directory: Path) -> subprocess.CompletedProcess:
        scorer = directory / "slow_scorer.py"
        scorer.write_text(
            "import time\n\n\n"
            "def score(*, output, expected, input_data=None, metadata=None):\n"
            "    time.sleep(30)\n"
            "    return 1.0\n"
        )
        cases = directory / "cases.json"
        cases.write_text(json.dumps(self.CASES))
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--scorer",
                f"{scorer}:score",
                "--cases",
                f"@{cases}",
                "--timeout",
                "2",
                "--allow-execution",
                "--json",
            ],
            capture_output=True,
            text=True,
        )

    def test_a_timeout_emits_a_parseable_result_and_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            process = self._run_slow_calibration(Path(raw))

        # The exit code stays the failure signal.
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertIn("exceeded 2 seconds", process.stderr)
        # And the payload is what makes the failure legible.
        payload = json.loads(process.stdout)
        self.assertTrue(payload["timed_out"])
        self.assertFalse(payload["passed"])
        self.assertEqual(payload["timeout_seconds"], 2)

    def test_a_timeout_is_scoped_to_the_whole_calibration_not_a_case(self) -> None:
        """#71 point 2: decide what a timeout means when cases are mixed.

        It is whole-calibration. Every case's probes share one subprocess, so
        when the budget expires the parent has no partial output to attribute -
        it cannot say which case was slow or whether any finished, and a
        per-case breakdown would have to be invented.

        `cases` is therefore empty because nothing could be attributed, not
        because none were requested. A reader has no way to tell those apart
        from an empty list, so the payload states both.
        """
        with tempfile.TemporaryDirectory() as raw:
            process = self._run_slow_calibration(Path(raw))
        payload = json.loads(process.stdout)

        self.assertEqual(payload["timeout_scope"], "calibration")
        self.assertEqual(payload["cases"], [])
        self.assertEqual(payload["cases_requested"], len(self.CASES))

    def test_readiness_raises_the_timeout_cap_from_that_payload(self) -> None:
        """The two halves of the contract, tested together.

        Asserting the payload alone would have passed while the cap stayed
        unreachable, which is exactly how this went unnoticed.
        """
        readiness = SCRIPT.parent / "readiness.py"
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            process = self._run_slow_calibration(directory)
            calibration = directory / "calibration.json"
            calibration.write_text(process.stdout)
            preflight = directory / "preflight.json"
            preflight.write_text(
                json.dumps(
                    [
                        {
                            "check": "dataset-provenance",
                            "status": "PASS",
                            "metrics": {
                                "rows": 40,
                                "labelled_rows": 40,
                                "collected_rows": 40,
                            },
                        }
                    ]
                )
            )
            scored = subprocess.run(
                [
                    sys.executable,
                    str(readiness),
                    "--preflight",
                    str(preflight),
                    "--calibration",
                    str(calibration),
                    "--json",
                ],
                capture_output=True,
                text=True,
            )

        self.assertEqual(scored.returncode, 0, scored.stderr)
        caps = {
            cap["condition"]: cap["ceiling"]
            for cap in json.loads(scored.stdout)["caps"]
        }
        self.assertEqual(caps.get("evaluator-timeout"), 45)

    def test_an_llm_judge_budget_scales_with_the_probe_calls_it_makes(self) -> None:
        """A reasoning judge can think for a minute on each of four probes a case.

        One flat number cannot serve both a deterministic scorer that never
        leaves the process and a judge making 4 network round trips per case, so
        the budget is derived from the work - with a floor so a tiny case set is
        not starved, and a ceiling where "slow" stops being credible and a hang
        is likelier. The ceiling also stops calibration quietly consuming the
        run's own time budget.
        """
        module = _load_constants()
        budget = module["llm_judge_timeout_seconds"]

        self.assertGreater(budget(1), module["DEFAULT_TIMEOUT_SECONDS"])
        self.assertGreaterEqual(budget(1), module["LLM_JUDGE_TIMEOUT_FLOOR_SECONDS"])
        self.assertLessEqual(budget(50), module["LLM_JUDGE_TIMEOUT_CEILING_SECONDS"])
        # More cases never buys less time.
        self.assertLessEqual(budget(1), budget(2))
        self.assertLessEqual(budget(2), budget(4))
        # And a zero/negative count cannot produce a nonsense budget.
        self.assertGreaterEqual(budget(0), module["LLM_JUDGE_TIMEOUT_FLOOR_SECONDS"])

    def test_a_timeout_says_slow_is_not_the_same_as_broken(self) -> None:
        """The cap means "not verified", never "this evaluator is bad"."""
        with tempfile.TemporaryDirectory() as raw:
            process = self._run_slow_calibration(Path(raw))
        self.assertIn("does not by itself mean the evaluator is broken", process.stderr)
        self.assertIn("larger --timeout", process.stderr)


def _load_constants() -> dict:
    """Load the module's timeout constants and helper without importing it.

    Importing the script executes its argument parser at module scope in some
    entry paths; the constants and the one pure function are all this needs.
    """
    import ast

    source = SCRIPT.read_text()
    tree = ast.parse(source)
    namespace: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.startswith(("LLM_JUDGE_", "DEFAULT_TIMEOUT", "PROBES_PER_CASE")):
                namespace[name] = ast.literal_eval(node.value)
        elif (
            isinstance(node, ast.FunctionDef)
            and node.name == "llm_judge_timeout_seconds"
        ):
            exec(compile(ast.Module([node], []), "<calibrator>", "exec"), namespace)
    return namespace


if __name__ == "__main__":
    unittest.main()


class PermutationProbeTests(unittest.TestCase):
    """traigent-first-run#99 - the six checks pass on a binding-blind ruler.

    The worked example: a SQL-result evaluator comparing token bags scores the
    inverted answer ("France 1 / Italy 2" against "France 2 / Italy 1") a
    perfect 1.0, while every mechanical check stays green, because the token
    multiset is identical and only the binding differs.
    """

    TOKEN_BAG = (
        "def score(*, output, expected, input_data, metadata):\n"
        "    a, b = set(str(output).split()), set(str(expected).split())\n"
        "    return len(a & b) / len(a | b) if (a | b) else 1.0\n"
    )
    ROW_AWARE = (
        "def score(*, output, expected, input_data, metadata):\n"
        "    a = [tuple(l.split()) for l in str(output).strip().splitlines()]\n"
        "    b = [tuple(l.split()) for l in str(expected).strip().splitlines()]\n"
        "    if not b:\n"
        "        return 1.0 if not a else 0.0\n"
        "    return sum(1 for r in b if r in a) / len(b)\n"
    )
    CASES = [
        {
            "name": "counts",
            "expected": "France 2\nItaly 1",
            "probes": {
                "good": "France 2\nItaly 1",
                "equivalent_good": "France 2\nItaly 1",
                "partial": "France 2",
                "bad": "Spain 9",
            },
        },
        {
            "name": "names",
            "expected": "Alice Bob",
            "probes": {
                "good": "Alice Bob",
                "equivalent_good": "Alice Bob",
                "partial": "Alice",
                "bad": "Zoe",
            },
        },
    ]

    def calibrate(self, directory: str, source: str, *extra: str, cases=None):
        scorer = Path(directory) / "scorer.py"
        scorer.write_text(source, encoding="utf-8")
        case_file = Path(directory) / "cases.json"
        case_file.write_text(json.dumps(cases or self.CASES), encoding="utf-8")
        process = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--scorer",
                f"{scorer}:score",
                "--cases",
                f"@{case_file}",
                "--allow-execution",
                "--json",
                *extra,
            ],
            capture_output=True,
            text=True,
        )
        return process, json.loads(process.stdout)

    def test_a_binding_blind_evaluator_is_questioned_not_failed(self) -> None:
        """The six checks are right; the question is what they cannot ask."""
        with tempfile.TemporaryDirectory() as directory:
            process, payload = self.calibrate(directory, self.TOKEN_BAG)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(payload["passed"], "the six checks correctly still pass")
        for case in payload["cases"]:
            with self.subTest(case=case["name"]):
                probe = case["permutation_probe"]
                self.assertEqual(probe["score"], 1.0)
                self.assertFalse(probe["distinguished"])
        self.assertIn("permutation_question", payload)
        self.assertIn("rearrangement", payload["permutation_question"])

    def binary_cases(self):
        """The same cases, each in the mode the row-aware scorer implements.

        `counts` has two rows, so a partially-right answer scores 0.5 - graded
        partial credit, and graded is its contract. `names` has one row, so the
        same partial answer scores 0.0, which no graded rule can accept because
        partial must sit a margin ABOVE bad. Per-case `score_mode` exists for
        exactly this, and using one mode for both would make the test fail on a
        mode mismatch it never meant to exercise rather than on the probe.
        """
        cases = json.loads(json.dumps(self.CASES))
        modes = {"counts": "graded", "names": "binary"}
        for case in cases:
            case["score_mode"] = modes[case["name"]]
        return cases

    def test_a_correct_evaluator_is_not_questioned(self) -> None:
        """The false-red side. A check that cries wolf teaches evasion.

        Without this, the honest outcome of the probe would be indistinguishable
        from it firing on everything.
        """
        with tempfile.TemporaryDirectory() as directory:
            process, payload = self.calibrate(
                directory, self.ROW_AWARE, cases=self.binary_cases()
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        for case in payload["cases"]:
            self.assertTrue(case["permutation_probe"]["distinguished"])
        self.assertNotIn("permutation_question", payload)

    def test_a_paid_judge_gets_no_extra_probe(self) -> None:
        """Counted, not read off the branch: an added probe is billed.

        The guide requires paid work to be approved in advance, so a tool may
        not add a provider call of its own - proven by counting the scorer
        invocations rather than by inspecting the condition that guards them.
        """
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "calls.log"
            counting = (
                "from pathlib import Path\n"
                f"LOG = Path({str(log)!r})\n"
                "def score(*, output, expected, input_data, metadata):\n"
                "    LOG.open('a').write('x\\n')\n"
                "    return 1.0 if str(output) == str(expected) else 0.0\n"
            )
            self.calibrate(
                directory, counting, "--kind", "llm-judge", "--paid-approved"
            )
            paid_calls = len(log.read_text().splitlines())
            log.unlink()
            self.calibrate(directory, counting, "--kind", "deterministic")
            free_calls = len(log.read_text().splitlines())
        self.assertEqual(paid_calls, 8, "4 probes x 2 cases, and nothing added")
        self.assertEqual(free_calls, 10, "the deterministic path adds one per case")

    def test_a_permutation_is_never_the_expected_answer(self) -> None:
        """A probe equal to the expectation SHOULD score 1.0.

        Emitting one would manufacture a false alarm on a correct evaluator, so
        these return None instead of something arbitrary.
        """
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            from calibrate_evaluator import permuted_answer
        finally:
            sys.path.pop(0)
        for value in ("France 2\nItaly 1", "a a b", "x=1; y=2"):
            with self.subTest(value=value):
                permuted = permuted_answer(value)
                self.assertIsNotNone(permuted)
                self.assertNotEqual(permuted, value)
                self.assertEqual(sorted(permuted.split()), sorted(value.split()))
        for value in ("solo", "a a a", "", {"k": 1}, 42, None):
            with self.subTest(value=value):
                self.assertIsNone(permuted_answer(value))

    def test_the_probe_is_deterministic(self) -> None:
        """Two runs of an unchanged evaluator must not disagree."""
        with tempfile.TemporaryDirectory() as directory:
            _, first = self.calibrate(directory, self.TOKEN_BAG)
            _, second = self.calibrate(directory, self.TOKEN_BAG)
        self.assertEqual(
            [c["permutation_probe"] for c in first["cases"]],
            [c["permutation_probe"] for c in second["cases"]],
        )

    def test_declared_outcome_classes_are_recorded(self) -> None:
        """The attestation says what it covered, not only its verdict."""
        cases = self.binary_cases()
        cases[0]["outcome_classes"] = ["label/value binding", "empty result"]
        cases[1]["outcome_classes"] = ["ordering"]
        with tempfile.TemporaryDirectory() as directory:
            _, payload = self.calibrate(directory, self.ROW_AWARE, cases=cases)
        self.assertEqual(
            payload["outcome_classes_covered"],
            ["empty result", "label/value binding", "ordering"],
        )

    def test_naming_a_class_cannot_defeat_the_duplicate_guard(self) -> None:
        """Otherwise the dedup check is switched off by writing a word."""
        cases = [
            {
                "name": "a",
                "expected": "x y",
                "outcome_classes": ["ordering"],
                "probes": {
                    "good": "x y",
                    "equivalent_good": "x y",
                    "partial": "x",
                    "bad": "z",
                },
            },
            {
                "name": "b",
                "expected": "x y",
                "outcome_classes": ["binding"],
                "probes": {
                    "good": "x y",
                    "equivalent_good": "x y",
                    "partial": "x",
                    "bad": "z",
                },
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "scorer.py"
            scorer.write_text(self.ROW_AWARE, encoding="utf-8")
            case_file = Path(directory) / "cases.json"
            case_file.write_text(json.dumps(cases), encoding="utf-8")
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{scorer}:score",
                    "--cases",
                    f"@{case_file}",
                    "--allow-execution",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 2)
        self.assertIn("duplicates another case payload", process.stderr)

    STRICT = (
        "def score(*, output, expected, input_data, metadata):\n"
        "    def parse(s):\n"
        "        rows = []\n"
        "        for line in str(s).strip().splitlines():\n"
        "            name, count = line.split()\n"
        "            rows.append((name, int(count)))\n"
        "        return rows\n"
        "    return 1.0 if parse(output) == parse(expected) else 0.0\n"
    )

    def test_a_scorer_that_refuses_the_probe_does_not_fail_the_run(self) -> None:
        """The probe is the only scorer input the author did not write.

        Plenty of correct scorers parse what they are given and raise on
        anything else. Unguarded, a generated probe failed the whole calibration
        with "invalid literal for int()" - a run that passed before this
        existed, reported against the user's evaluator with no hint the input
        was ours.
        """
        cases = [
            {
                "name": "counts",
                "expected": "France 2\nItaly 1",
                "score_mode": "binary",
                "probes": {
                    "good": "France 2\nItaly 1",
                    "equivalent_good": "France 2\nItaly 1",
                    "partial": "France 3",
                    "bad": "Spain 9",
                },
            },
            {
                "name": "more",
                "expected": "Spain 4\nPeru 5",
                "score_mode": "binary",
                "probes": {
                    "good": "Spain 4\nPeru 5",
                    "equivalent_good": "Spain 4\nPeru 5",
                    "partial": "Spain 9",
                    "bad": "Chile 1",
                },
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            process, payload = self.calibrate(directory, self.STRICT, cases=cases)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(payload["passed"], "the author's own probes still decide")
        for case in payload["cases"]:
            with self.subTest(case=case["name"]):
                probe = case["permutation_probe"]
                self.assertIsNone(probe["score"])
                self.assertIsNotNone(probe["error"])
                # Tri-state: the scorer refused, which answers neither question.
                self.assertIsNone(probe["distinguished"])
        # `not None` is True, so a two-state filter would have asked the
        # "does not distinguish" question about a probe that never scored.
        self.assertNotIn("permutation_question", payload)

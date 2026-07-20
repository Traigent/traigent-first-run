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


if __name__ == "__main__":
    unittest.main()

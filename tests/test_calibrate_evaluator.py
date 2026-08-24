from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "traigent-first-run" / "scripts" / "calibrate_evaluator.py"
# The opening gate, run beside this script by the one test that pins the two
# digests to each other. A comparison whose two sides are computed
# differently is a comparison that reports differences that are not there.
PREFLIGHT = ROOT / "skills" / "traigent-first-run" / "scripts" / "preflight.py"
# The reference that owns this stage. Several tests below weld a number in the
# script to the sentence that discloses it, because a bound the user is never
# told about is the defect, not the bound.
EVALUATION_REFERENCE = (
    ROOT / "skills" / "traigent-first-run" / "references" / "evaluation-and-dataset.md"
)


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

    def test_timeout_help_discloses_one_shared_budget_derived_from_the_work(
        self,
    ) -> None:
        """`--timeout` is the whole wait, and the default is derived, not flat.

        Both halves are contract the user reads before deciding whether to wait.
        The help used to disclose that the deterministic path quietly took a
        second budget of the same size - "worst-case wall time is roughly twice
        this value" - which documented the defect instead of removing it.

        Merging the two budgets is the right call at the DERIVED default, where
        the derivation already allows for both phases. It has a cost at an
        explicit `--timeout`, and that is the one invocation this option exists
        for: "wait, my evaluator is normally this slow" is answered with calls
        times cost, which sizes the authored phase exactly and leaves the
        supplemental probes nothing. Measured on a three-case matrix with a
        0.55s-per-call evaluator and `--timeout 8`: 13 of 15 supplemental probes
        lost here against 3 of 15 before the merge. The `ADVISORY` line makes
        that visible after the fact; the help is where it is visible before, so
        the cost is disclosed inside the option that triggers it.
        """
        process = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        normalized = " ".join(process.stdout.split())
        self.assertIn("share this one total budget", normalized)
        self.assertIn("worst-case wall time and not half of it", normalized)
        self.assertIn("derived from the work", normalized)
        self.assertNotIn("roughly twice", normalized)
        # The cost of the merge, at the invocation that pays it. Naming the
        # sharing without naming the consequence is what the reader already had:
        # true, and not enough to size a number by.
        for disclosure in (
            "size it for both phases",
            "leaves the supplemental ones nothing",
            "they come back unavailable",
            "ADVISORY line on stderr names how many",
        ):
            with self.subTest(disclosure=disclosure):
                self.assertIn(disclosure, normalized)

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

    def test_silent_exception_to_zero_is_reported_without_rewriting_verdict(
        self,
    ) -> None:
        """A green four-probe matrix must still surface hidden evaluator errors."""
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "silent_exception_scorer.py"
            scorer.write_text(
                "import json\n\n"
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    try:\n"
                "        if isinstance(output, str):\n"
                "            json.loads(output)\n"
                "        required = set(expected)\n"
                "        actual = set(output)\n"
                "        return len(required & actual) / len(required)\n"
                "    except Exception:\n"
                "        return 0.0\n"
            )
            process = subprocess.run(
                [*self.command(scorer), "--allow-execution"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertTrue(payload["passed"], "authored probes still own the verdict")
        probes = payload["exception_probes"]
        self.assertEqual(
            {probe["kind"] for probe in probes},
            {
                "value-error",
                "type-error",
                "syntax-error",
                "json-decode-error",
                "runtime-error",
            },
        )
        self.assertTrue(all(probe["score"] == 0.0 for probe in probes))
        self.assertTrue(all(probe["error"] is None for probe in probes))
        self.assertTrue(all(probe["outcome"] == "returned-zero" for probe in probes))
        self.assertTrue(all(not probe["distinguished_from_zero"] for probe in probes))
        self.assertIn("exception_probe_advisory", payload)
        advisory = payload["exception_probe_advisory"]
        self.assertIn("ordinary 0.0", advisory)
        self.assertIn("consistent with a swallowed", advisory)
        self.assertIn("can also be a deliberate rejection", advisory)
        self.assertIn("does not prove the cause or change calibration PASS", advisory)

    def test_each_supplemental_probe_isolates_imported_dependency_state(self) -> None:
        """A scorer reload is insufficient when its imported helper is cached."""
        cases = [
            {
                "name": "first fields",
                "expected": "a 1 b 2",
                "metadata": {
                    "poison": True,
                    "scores": {
                        "a 1 b 2": 1.0,
                        "A 1 B 2": 0.9,
                        "a 1": 0.5,
                        "wrong-a": 0.0,
                    },
                },
                "probes": {
                    "good": "a 1 b 2",
                    "equivalent_good": "A 1 B 2",
                    "partial": "a 1",
                    "bad": "wrong-a",
                },
            },
            {
                "name": "second fields",
                "expected": "w 3 x 4",
                "metadata": {
                    "poison": False,
                    "scores": {
                        "w 3 x 4": 1.0,
                        "W 3 X 4": 0.9,
                        "w 3": 0.5,
                        "wrong-b": 0.0,
                    },
                },
                "probes": {
                    "good": "w 3 x 4",
                    "equivalent_good": "W 3 X 4",
                    "partial": "w 3",
                    "bad": "wrong-b",
                },
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "evaluator_state.py"
            helper.write_text("poisoned = False\n")
            scorer = Path(directory) / "stateful_scorer.py"
            scorer.write_text(
                "import evaluator_state\n\n"
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    if type(output) is str and output in metadata['scores']:\n"
                "        return metadata['scores'][output]\n"
                "    if metadata['poison']:\n"
                "        evaluator_state.poisoned = True\n"
                "        return 0.0\n"
                "    if evaluator_state.poisoned:\n"
                "        return 0.0\n"
                "    raise ValueError('fresh dependency state')\n"
            )
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{scorer}:score",
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
        self.assertTrue(all(case["passed"] for case in payload["cases"]))
        first, second = payload["cases"]
        self.assertEqual(first["permutation_probe"]["score"], 0.0)
        self.assertIsNone(first["permutation_probe"]["error"])
        self.assertIsNone(second["permutation_probe"]["score"])
        self.assertIn("fresh dependency state", second["permutation_probe"]["error"])
        self.assertTrue(
            all(
                probe["outcome"] == "returned-zero"
                for probe in first["exception_probes"]
            )
        )
        self.assertTrue(
            all(
                probe["outcome"] == "propagated-error"
                for probe in second["exception_probes"]
            )
        )

    def test_propagated_exception_is_distinct_from_an_ordinary_zero(self) -> None:
        """A scorer that fails loudly must not receive the silent-error warning."""
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "loud_scorer.py"
            scorer.write_text(
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    if isinstance(output, str):\n"
                "        raise ValueError('malformed text remains an error')\n"
                "    required = set(expected)\n"
                "    actual = set(output)\n"
                "    return len(required & actual) / len(required)\n"
            )
            process = subprocess.run(
                [
                    *self.command(scorer),
                    "--allow-execution",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        probes = payload["exception_probes"]
        self.assertTrue(all(probe["score"] is None for probe in probes))
        self.assertTrue(all(probe["error"] is not None for probe in probes))
        self.assertTrue(all(probe["outcome"] == "propagated-error" for probe in probes))
        self.assertTrue(all(probe["distinguished_from_zero"] for probe in probes))
        self.assertNotIn("exception_probe_advisory", payload)

    def test_exception_family_probe_finds_a_value_error_specific_swallow(self) -> None:
        """One custom RuntimeError cannot exercise an except ValueError path."""
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "value_error_scorer.py"
            scorer.write_text(
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    if isinstance(output, str):\n"
                "        raise RuntimeError('malformed text is not the target')\n"
                "    try:\n"
                "        if type(output).__name__ == 'AdversarialOutputProbe':\n"
                "            str(output)\n"
                "        required = set(expected)\n"
                "        actual = set(output)\n"
                "        return len(required & actual) / len(required)\n"
                "    except ValueError:\n"
                "        return 0.0\n"
            )
            process = subprocess.run(
                [*self.command(scorer), "--allow-execution"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertTrue(payload["passed"])
        probes = {probe["kind"]: probe for probe in payload["exception_probes"]}
        self.assertEqual(probes["value-error"]["outcome"], "returned-zero")
        for kind in (
            "type-error",
            "syntax-error",
            "json-decode-error",
            "runtime-error",
        ):
            self.assertEqual(probes[kind]["outcome"], "propagated-error")
        self.assertIn("exception_probe_advisory", payload)

    def test_malformed_python_probe_reaches_ast_and_compile_syntax_errors(
        self,
    ) -> None:
        """A str subclass passes parser type guards that rejected the old object."""
        parser_calls = (
            "ast.parse(output)",
            "compile(output, '<calibration-probe>', 'exec')",
        )
        for parser_call in parser_calls:
            with self.subTest(
                parser_call=parser_call
            ), tempfile.TemporaryDirectory() as directory:
                scorer = Path(directory) / "python_parser_scorer.py"
                scorer.write_text(
                    "import ast\n\n"
                    "def score(output, expected, input_data=None, metadata=None):\n"
                    "    if isinstance(output, str):\n"
                    "        try:\n"
                    f"            {parser_call}\n"
                    "        except SyntaxError:\n"
                    "            return 0.0\n"
                    "        raise RuntimeError('unexpected valid generated source')\n"
                    "    required = set(expected)\n"
                    "    actual = set(output)\n"
                    "    return len(required & actual) / len(required)\n"
                )
                process = subprocess.run(
                    [*self.command(scorer), "--allow-execution"],
                    capture_output=True,
                    text=True,
                )
            self.assertEqual(process.returncode, 0, process.stderr)
            payload = json.loads(process.stdout)
            probes = {probe["kind"]: probe for probe in payload["exception_probes"]}
            self.assertEqual(probes["syntax-error"]["outcome"], "returned-zero")
            self.assertIn("exception_probe_advisory", payload)

    def test_malformed_text_subclasses_preserve_native_parser_errors(self) -> None:
        """Overridden classifier operations must not replace parser diagnostics."""
        import ast

        sys.path.insert(0, str(SCRIPT.parent))
        try:
            from calibrate_evaluator import exception_probe_output
        finally:
            sys.path.pop(0)

        python_probe = exception_probe_output("syntax-error")
        with self.assertRaises(SyntaxError) as ast_error:
            ast.parse(python_probe)
        self.assertEqual(ast_error.exception.msg, "invalid syntax")
        with self.assertRaises(SyntaxError) as compile_error:
            compile(python_probe, "<calibration-probe>", "exec")
        self.assertEqual(compile_error.exception.msg, "invalid syntax")

        json_probe = exception_probe_output("json-decode-error")
        with self.assertRaises(json.JSONDecodeError) as json_error:
            json.loads(json_probe)
        self.assertEqual(json_error.exception.msg, "Expecting value")

    def test_malformed_json_probe_reaches_json_decode_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "json_parser_scorer.py"
            scorer.write_text(
                "import json\n\n"
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    if isinstance(output, str):\n"
                "        try:\n"
                "            json.loads(output)\n"
                "        except json.JSONDecodeError:\n"
                "            return 0.0\n"
                "        raise RuntimeError('unexpected valid generated JSON')\n"
                "    required = set(expected)\n"
                "    actual = set(output)\n"
                "    return len(required & actual) / len(required)\n"
            )
            process = subprocess.run(
                [*self.command(scorer), "--allow-execution"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        probes = {probe["kind"]: probe for probe in payload["exception_probes"]}
        self.assertEqual(probes["json-decode-error"]["outcome"], "returned-zero")
        self.assertIn("exception_probe_advisory", payload)

    def test_malformed_text_probes_do_not_look_like_normal_wrong_labels(self) -> None:
        """Healthy exact-label paths must propagate the probe, not return zero."""
        scorer_bodies = (
            "return float(output.casefold() == expected.casefold())",
            "return float(output == expected)",
        )
        for body in scorer_bodies:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                scorer = Path(directory) / "exact_label_scorer.py"
                scorer.write_text(
                    "def score(output, expected, input_data=None, metadata=None):\n"
                    f"    {body}\n"
                )
                process = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--scorer",
                        f"{scorer}:score",
                        "--good",
                        '"positive"',
                        "--equivalent-good",
                        '"positive"',
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
            probes = {probe["kind"]: probe for probe in payload["exception_probes"]}
            for kind in ("syntax-error", "json-decode-error"):
                self.assertEqual(probes[kind]["outcome"], "propagated-error")
            self.assertNotIn("exception_probe_advisory", payload)

    def test_probe_error_with_unprintable_input_remains_advisory(self) -> None:
        """Formatting a probe-triggered exception must not fail calibration."""
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "unprintable_error_scorer.py"
            scorer.write_text(
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    if isinstance(output, str):\n"
                "        raise ValueError('malformed text')\n"
                "    if type(output).__name__ == 'AdversarialOutputProbe':\n"
                "        raise ValueError(output)\n"
                "    required = set(expected)\n"
                "    actual = set(output)\n"
                "    return len(required & actual) / len(required)\n"
            )
            process = subprocess.run(
                [*self.command(scorer), "--allow-execution"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertTrue(payload["passed"])
        probes = payload["exception_probes"]
        self.assertTrue(all(probe["outcome"] == "propagated-error" for probe in probes))
        self.assertEqual(
            {probe["kind"] for probe in probes},
            {
                "value-error",
                "type-error",
                "syntax-error",
                "json-decode-error",
                "runtime-error",
            },
        )
        object_probes = [
            probe
            for probe in probes
            if probe["kind"] in {"value-error", "type-error", "runtime-error"}
        ]
        self.assertTrue(
            all(
                "ValueError: <message unavailable" in probe["error"]
                for probe in object_probes
            )
        )
        self.assertTrue(
            any("AdversarialProbeAccess" in probe["error"] for probe in object_probes)
        )

    def test_keyboard_interrupt_from_supplemental_probe_is_not_swallowed(self) -> None:
        """Cancellation is control flow, not evaluator evidence."""
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "interrupting_scorer.py"
            scorer.write_text(
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    if type(output).__name__ == 'AdversarialOutputProbe':\n"
                "        raise KeyboardInterrupt()\n"
                "    required = set(expected)\n"
                "    actual = set(output)\n"
                "    return len(required & actual) / len(required)\n"
            )
            process = subprocess.run(
                [*self.command(scorer), "--allow-execution"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertTrue(payload["passed"])
        object_probes = [
            probe
            for probe in payload["exception_probes"]
            if probe["kind"] in {"value-error", "type-error", "runtime-error"}
        ]
        self.assertTrue(
            all(probe["outcome"] == "unavailable" for probe in object_probes)
        )
        self.assertTrue(
            all(
                "KeyboardInterrupt" in probe["unavailable"]["detail"]
                for probe in object_probes
            )
        )
        self.assertIn("supplemental_probe_advisory", payload)
        # The advisory summary announces itself on stderr in every mode. What
        # must not reach stderr is the child's own cancellation trace - that is
        # the swallowing this test is about, and it stays in the payload.
        self.assertEqual(
            [line for line in process.stderr.splitlines() if line.strip()],
            [f"ADVISORY: {payload['supplemental_probe_advisory']}"],
        )

    def test_supplemental_import_failure_is_unavailable_and_preserves_pass(
        self,
    ) -> None:
        """A non-idempotent import belongs to the advisory, not the verdict."""
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "first-import.complete"
            scorer = Path(directory) / "single_import_scorer.py"
            scorer.write_text(
                "from pathlib import Path\n\n"
                f"MARKER = Path({str(marker)!r})\n"
                "if MARKER.exists():\n"
                "    raise RuntimeError('repeat import rejected')\n"
                "MARKER.write_text('loaded')\n\n"
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    required = set(expected)\n"
                "    actual = set(output)\n"
                "    return len(required & actual) / len(required)\n"
            )
            process = subprocess.run(
                [*self.command(scorer), "--allow-execution"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertTrue(payload["passed"])
        probes = payload["exception_probes"]
        self.assertTrue(all(probe["outcome"] == "unavailable" for probe in probes))
        self.assertTrue(
            all(
                probe["unavailable"]["reason"] == "worker-failed"
                and "repeat import rejected" in probe["unavailable"]["detail"]
                for probe in probes
            )
        )
        self.assertIn("supplemental_probe_advisory", payload)

    def test_supplemental_phase_has_one_cumulative_budget_and_preserves_pass(
        self,
    ) -> None:
        """Five hanging attempts may consume one extra timeout, not five."""
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "hanging_supplemental_scorer.py"
            scorer.write_text(
                "import time\n\n"
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    if type(output).__name__ in {\n"
                "        'AdversarialOutputProbe', 'MalformedTextOutputProbe'\n"
                "    }:\n"
                "        time.sleep(10)\n"
                "    required = set(expected)\n"
                "    actual = set(output)\n"
                "    return len(required & actual) / len(required)\n"
            )
            started = time.monotonic()
            process = subprocess.run(
                [
                    *self.command(scorer),
                    "--timeout",
                    "1",
                    "--allow-execution",
                ],
                capture_output=True,
                text=True,
            )
            elapsed = time.monotonic() - started
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertLess(
            elapsed, 4.0, "supplemental attempts exceeded one shared budget"
        )
        payload = json.loads(process.stdout)
        self.assertTrue(payload["passed"])
        probes = payload["exception_probes"]
        self.assertTrue(all(probe["outcome"] == "unavailable" for probe in probes))
        reasons = [probe["unavailable"]["reason"] for probe in probes]
        self.assertEqual(reasons.count("timeout"), 1)
        self.assertEqual(reasons.count("budget-exhausted"), len(probes) - 1)
        self.assertIn("supplemental_probe_advisory", payload)

    def test_nonzero_probe_score_is_reported_as_the_third_advisory_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "nonzero_exception_scorer.py"
            scorer.write_text(
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    try:\n"
                "        if not isinstance(output, list):\n"
                "            raise TypeError('unsupported probe')\n"
                "        required = set(expected)\n"
                "        actual = set(output)\n"
                "        return len(required & actual) / len(required)\n"
                "    except Exception:\n"
                "        return 0.1\n"
            )
            process = subprocess.run(
                [*self.command(scorer), "--allow-execution"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        probes = payload["exception_probes"]
        self.assertTrue(all(probe["score"] == 0.1 for probe in probes))
        self.assertTrue(all(probe["error"] is None for probe in probes))
        self.assertTrue(all(probe["outcome"] == "returned-nonzero" for probe in probes))
        self.assertTrue(all(probe["distinguished_from_zero"] for probe in probes))
        self.assertNotIn("exception_probe_advisory", payload)

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

    # The same two cases, with the label task declared binary so a scorer that
    # gives it no partial credit is judged against the contract it actually
    # meets. The pre-cap tests below need a calibration that genuinely PASSES:
    # a warning asserted on top of a failing run proves nothing about the run
    # that will actually be waiting at minute 13.
    PASSING_CASES = [
        CASES[0],
        {**CASES[1], "score_mode": "binary"},
    ]

    def _passing_fixture(self, directory: Path) -> tuple[Path, Path]:
        """A briefly-slow local scorer that passes both cases. No provider call."""
        scorer = directory / "brief_scorer.py"
        scorer.write_text(
            "import time\n\n\n"
            "def score(output, expected, input_data=None, metadata=None):\n"
            "    time.sleep(0.3)\n"
            "    if isinstance(expected, list):\n"
            "        required = set(expected)\n"
            "        return len(required & set(output)) / len(required)\n"
            "    return float(output.casefold() == expected.casefold())\n"
        )
        cases = directory / "passing-cases.json"
        cases.write_text(json.dumps(self.PASSING_CASES))
        return scorer, cases

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
        self.assertIn("exceeded its 2-second budget", process.stderr)
        # And the payload is what makes the failure legible.
        payload = json.loads(process.stdout)
        self.assertTrue(payload["timed_out"])
        self.assertFalse(payload["passed"])
        self.assertEqual(payload["timeout_seconds"], 2)

    def test_a_timeout_is_scoped_to_the_authored_calibration_not_a_case(self) -> None:
        """#71 point 2: decide what a timeout means when cases are mixed.

        It is whole-authored-calibration. Every case's authored probes share one
        subprocess, so when the budget expires the parent has no partial output
        to attribute - it cannot say which case was slow or whether any
        finished, and a per-case breakdown would have to be invented.

        `cases` is therefore empty because nothing could be attributed, not
        because none were requested. A reader has no way to tell those apart
        from an empty list, so the payload states both.
        """
        with tempfile.TemporaryDirectory() as raw:
            process = self._run_slow_calibration(Path(raw))
        payload = json.loads(process.stdout)

        self.assertEqual(payload["timeout_scope"], "authored-calibration")
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
                                # Every count preflight emits together: the
                                # scorer refuses a payload missing any of them
                                # rather than reading absence as zero.
                                "collected_rows": 40,
                                "synthesised_rows": 0,
                                "undeclared_rows": 0,
                                "answerable_rows": 40,
                                "generated_answer_rows": 0,
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

    # The evaluator this whole change exists for: about a minute per call. It is
    # the unit the budget has to be measured against, because "300" and "30" are
    # both defensible-looking numbers that kill it.
    SLOW_EVALUATOR_SECONDS_PER_CALL = 60
    # What the guide asks a calibration matrix to cover, and `--cases` will not
    # accept fewer than two, so this is the whole documented range.
    DOCUMENTED_CASE_COUNTS = (2, 3, 4, 5)

    def test_the_budget_covers_a_minute_per_call_evaluator_until_the_cap_binds(
        self,
    ) -> None:
        """Pin the number to the work it must cover, not to itself.

        A flat budget passes every relative-shape assertion while failing the
        one customer it was written for: 4 probe calls per case times a
        one-minute call is 480 seconds at the two-case minimum and 1200 at five,
        so 30 and 300 are the same defect an order of magnitude apart. Reverting
        the derivation has to fail on meaning here, not on a file hash.

        What changed is where the check stops. The fifteen-minute cap is a
        decision about how long it is fair to make a first-run user wait, so
        above it the derivation is deliberately cut and this can no longer
        assert the slow evaluator is covered - that would be asserting the cap
        away. So it asserts the derivation is intact everywhere the cap does not
        bind, and the sibling test below owns what happens where it does.
        """
        module = _load_constants()
        budget = module["calibration_timeout_seconds"]
        probes_per_case = module["PROBES_PER_CASE"]
        ceiling = module["CALIBRATION_TIMEOUT_CEILING_SECONDS"]

        uncapped = 0
        for case_count in self.DOCUMENTED_CASE_COUNTS:
            needed = case_count * probes_per_case * self.SLOW_EVALUATOR_SECONDS_PER_CALL
            for kind in ("deterministic", "llm-judge"):
                if needed > ceiling:
                    continue
                uncapped += 1
                with self.subTest(cases=case_count, kind=kind):
                    self.assertGreaterEqual(
                        budget(case_count, kind),
                        needed,
                        f"{case_count} cases is {case_count * probes_per_case} probe "
                        f"calls; a {self.SLOW_EVALUATOR_SECONDS_PER_CALL}s-per-call "
                        f"evaluator needs {needed}s, the cap does not bind there, "
                        "and this budget kills it anyway",
                    )
        # A cap low enough to skip every documented size would turn the loop
        # above into a green tick over nothing.
        self.assertGreater(uncapped, 0)

    def test_where_the_cap_binds_it_is_the_budget_and_the_guide_says_what_that_costs(
        self,
    ) -> None:
        """A clamped run gets less per probe than `--help` quotes. Disclose it.

        This test replaces one that asserted the ceiling never clamps a
        documented run. That was true of the derived 1800 and is deliberately
        false of the owner's 900: fifteen minutes bounds the wait, not the work,
        so at four and five pairs the per-probe rate silently drops. Silently is
        the part that is not allowed - so the assertion moved from "it never
        happens" to "when it happens the user is told", which is the only form
        of this check that survives the decision.
        """
        module = _load_constants()
        budget = module["calibration_timeout_seconds"]
        probes_per_case = module["PROBES_PER_CASE"]
        ceiling = module["CALIBRATION_TIMEOUT_CEILING_SECONDS"]
        per_probe = {
            "deterministic": module["DETERMINISTIC_SECONDS_PER_PROBE"],
            "llm-judge": module["LLM_JUDGE_SECONDS_PER_PROBE"],
        }

        clamped = 0
        for case_count in self.DOCUMENTED_CASE_COUNTS:
            for kind, seconds in per_probe.items():
                derived = case_count * probes_per_case * seconds
                with self.subTest(cases=case_count, kind=kind):
                    self.assertEqual(budget(case_count, kind), min(derived, ceiling))
                if derived > ceiling:
                    clamped += 1
        # The disclosure below is only honest if there is something to disclose.
        self.assertGreater(
            clamped,
            0,
            "no documented case count is clamped, so the guidance sentence this "
            "test pins is describing something that cannot happen",
        )

        # The owner set fifteen minutes; the guide has to say so, say why, and
        # say what it costs the evaluator that is genuinely that slow.
        self.assertEqual(ceiling, 900)
        # The arithmetic behind the sentence, so a constant can never move and
        # leave the words describing the previous number.
        last_whole = {
            kind: max(
                count
                for count in range(1, 100)
                if count * probes_per_case * seconds <= ceiling
            )
            for kind, seconds in per_probe.items()
        }
        self.assertEqual(last_whole, {"deterministic": 3, "llm-judge": 2})
        five_pair_rate = ceiling / (5 * probes_per_case)
        self.assertEqual(five_pair_rate, 45)
        # Both cuts, because the sentence quotes both. One number for both rates
        # was true of the deterministic budget and understated the judge's: 45 is
        # a 40% cut against 75 and exactly half of 90, and it was the judge - the
        # slower of the two, and the one paying per model call - whose loss was
        # the one not stated.
        self.assertEqual(
            round(100 * (1 - five_pair_rate / per_probe["deterministic"])), 40
        )
        self.assertEqual(five_pair_rate * 2, per_probe["llm-judge"])
        normalized = " ".join(EVALUATION_REFERENCE.read_text().casefold().split())
        for phrase in (
            "fifteen minutes is the ceiling on that budget, and say so before the wait "
            "starts",
            "this is onboarding rather than a full-power run",
            "the ceiling bounds the wait, not the work",
            # Both rates, because a judge is cut a pair earlier than a
            # deterministic scorer and one number for both would misinform the
            # reader who is paying per probe.
            "whole to three pairs deterministic and two for a judge",
            # Built from the constants, not typed twice. A probe that moved
            # DETERMINISTIC_SECONDS_PER_PROBE to 60 survived the literal version
            # of this line: both counts above happened to stay put, and the only
            # thing that had become false was the "75" in the sentence.
            #
            # Both rates, for the same reason the pair counts above are both
            # named. "45 seconds instead of 75" said "either way" and then
            # quoted one rate, so the judge - cut to exactly half rather than by
            # 40% - read as losing less than it does.
            f"{ceiling // (5 * probes_per_case)} seconds - which is a "
            f"{round(100 * (1 - five_pair_rate / per_probe['deterministic']))}% "
            f"cut against the {per_probe['deterministic']} the deterministic "
            f"budget is derived at, and exactly half the "
            f"{per_probe['llm-judge']} a judge is",
            "their own larger `--timeout` is not capped",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_the_pre_cap_warning_lands_before_the_cap_and_only_when_it_can(
        self,
    ) -> None:
        """Two minutes of notice, and none where two minutes is the whole wait.

        The owner asked for the warning at about minute 13 of 15. A fixed lead
        gives that, and gives the same two minutes to decide at any budget,
        which a percentage does not: 13% of a 300-second budget is 39 seconds.
        The None case is the other half - a budget no longer than the lead has
        no "before the cap" to warn in, and a warning fired at the first probe
        call only repeats what the assistant said when it announced the wait.
        """
        module = _load_constants()
        delay = module["pre_cap_warning_delay"]
        lead = module["PRE_CAP_WARNING_LEAD_SECONDS"]
        ceiling = module["CALIBRATION_TIMEOUT_CEILING_SECONDS"]

        # The owner's own example, at the owner's own ceiling.
        self.assertEqual(delay(ceiling), 780.0)
        self.assertEqual((ceiling - delay(ceiling)) / 60, 2.0)
        # Whatever the budget, the notice is the same size.
        for budget_seconds in (300, 600, 900):
            with self.subTest(budget=budget_seconds):
                self.assertEqual(delay(budget_seconds), budget_seconds - lead)
        # And a budget that cannot carry the lead gets no warning rather than
        # one at t=0.
        self.assertIsNone(delay(lead))
        self.assertIsNone(delay(lead - 1))
        self.assertIsNotNone(delay(lead + 1))

    def test_the_pre_cap_line_is_a_warning_and_says_there_is_no_resume(self) -> None:
        """The owner's condition: a stop/continue question here is dishonest.

        Stopping is not the cheap half of a choice - it discards every minute
        already spent, because the authored probes run in one child that reports
        only when every case is done and the parent writes nothing until it
        returns. So the line has to say the run cannot be resumed, and must not
        be phrased as a choice between two things of different size.
        """
        module = _load_constants()
        message = module["pre_cap_warning_message"](900)
        normalized = " ".join(message.casefold().split())

        self.assertIn("there is no resume", normalized)
        self.assertIn("stopping now discards this wait entirely", normalized)
        self.assertIn("re-run starts from the first probe", normalized)
        # It still says what happens if nothing is done, or it is only bad news.
        self.assertIn("writes the timeout record", normalized)
        self.assertIn("warning, not as a question", normalized)
        # The numbers in it are the real ones.
        self.assertIn("120 of the 900 seconds", normalized)
        # And it does not offer the choice the docstring rejects.
        self.assertNotIn("stop or continue", normalized)
        self.assertNotIn("?", message)

    def test_the_pre_cap_warning_actually_reaches_stderr_during_the_run(self) -> None:
        """Measured, because a timer that never fires is a promise in a comment.

        A budget one second above the lead puts the warning one second into the
        run, which is what makes this affordable to assert end to end rather
        than at minute 13. The scorer is local and sleeps; no provider is called.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            scorer, cases = self._passing_fixture(directory)
            module = _load_constants()
            budget_seconds = module["PRE_CAP_WARNING_LEAD_SECONDS"] + 1
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{scorer}:score",
                    "--cases",
                    f"@{cases}",
                    "--timeout",
                    str(budget_seconds),
                    "--allow-execution",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )

        warnings = [
            line
            for line in process.stderr.splitlines()
            if "CALIBRATION STILL RUNNING" in line
        ]
        self.assertEqual(
            len(warnings),
            1,
            f"expected exactly one pre-cap warning on stderr, got {process.stderr!r}",
        )
        self.assertIn("there is no resume", warnings[0])
        # It is a warning about a run still going, so it cannot be the last word:
        # the calibration still finished and still reported.
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(json.loads(process.stdout)["passed"])

    def test_a_short_calibration_is_not_warned_about_a_cap_it_cannot_reach(
        self,
    ) -> None:
        """The quiet case, asserted so the timer cannot become unconditional."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            scorer, cases = self._passing_fixture(directory)
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{scorer}:score",
                    "--cases",
                    f"@{cases}",
                    "--timeout",
                    "20",
                    "--allow-execution",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )

        self.assertNotIn("CALIBRATION STILL RUNNING", process.stderr)

    def test_the_guide_says_there_is_no_resume_and_forbids_the_stop_question(
        self,
    ) -> None:
        """The disclosure has to match what the code does, or it is worse than none.

        The code has no resume path, so the guidance may not offer a choice that
        implies one. This is pinned in the reference rather than left to the
        script's own stderr line because the assistant decides what to say to
        the user, and it decides that from here.
        """
        normalized = " ".join(EVALUATION_REFERENCE.read_text().casefold().split())

        self.assertIn("**there is no resume.**", normalized)
        self.assertIn(
            "a calibration stopped part-way records nothing and a re-run starts at the "
            "first probe",
            normalized,
        )
        self.assertIn(
            'do not turn it into a "stop or continue" question',
            normalized,
        )
        self.assertIn(
            "continuing costs the minutes that are left, stopping costs every minute "
            "already spent",
            normalized,
        )

    def test_the_budget_is_bounded_and_monotonic(self) -> None:
        module = _load_constants()
        budget = module["calibration_timeout_seconds"]
        ceiling = module["CALIBRATION_TIMEOUT_CEILING_SECONDS"]

        for kind in ("deterministic", "llm-judge"):
            with self.subTest(kind=kind):
                # A hang is still stopped.
                self.assertLessEqual(budget(500, kind), ceiling)
                # More cases never buys less time.
                self.assertLessEqual(budget(1, kind), budget(2, kind))
                self.assertLessEqual(budget(2, kind), budget(4, kind))
                # And a zero/negative count cannot produce a nonsense budget.
                self.assertGreater(budget(0, kind), 0)
                self.assertEqual(budget(0, kind), budget(1, kind))
        # A judge pays network latency on top of the same work - below the cap.
        # At and above it the two paths meet at the same number, because the cap
        # is a bound on the wait and the wait does not care which kind produced
        # it. Asserting the strict inequality everywhere would be asserting the
        # cap away; asserting both halves is what the function actually does.
        self.assertGreater(budget(2, "llm-judge"), budget(2, "deterministic"))
        self.assertEqual(budget(500, "llm-judge"), budget(500, "deterministic"))
        self.assertEqual(budget(500, "llm-judge"), ceiling)

    # Every case-set size the budget can be asked about. `--cases` requires at
    # least two and one is the smallest the function itself accepts, so this
    # range covers every input a clamp could bind on, with a wide margin above.
    LEGAL_CASE_COUNTS = range(0, 501)
    KINDS = ("deterministic", "llm-judge")
    _NAMES_A_CLAMP = re.compile(r"_(?:FLOOR|CEILING|MINIMUM|MAXIMUM)_SECONDS$")

    def _budget_source(self) -> ast.FunctionDef:
        """`calibration_timeout_seconds`, as source rather than as a callable."""
        for node in ast.parse(SCRIPT.read_text()).body:
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "calibration_timeout_seconds"
            ):
                return node
        self.fail("the module no longer defines calibration_timeout_seconds")

    def test_every_clamp_this_module_declares_can_actually_bind(self) -> None:
        """A clamp that cannot bind is a protection that is not there.

        `LLM_JUDGE_TIMEOUT_FLOOR_SECONDS = 180` lived here and could never fire:
        the smallest case set is one case, which is `PROBES_PER_CASE` probes,
        which is already 300 seconds - so `max(180, ...)` returned its other
        argument for every input the function can receive. It was removed rather
        than raised, because a floor nobody reaches still reads to the next
        person as "small case sets are protected", and they are not.

        Nothing catches that by behaviour, and that is exactly why it needs a
        test: putting the floor back changes no output, so every value-based
        assertion in this file passes with it there. A deletion whose undo is
        invisible is the one a merge undoes and nobody notices.

        So the check is structural, and it is a rule rather than a list of the
        names that have appeared so far. Two places are read: any module-level
        constant whose name says it is a clamp, and any bound written inside the
        budget function itself - because the floor's second, worse form is a
        bare `max(180, ...)` with no constant to notice. Each must be a value
        the budget actually returns for some legal case count. A ceiling
        qualifies because the budget reaches it; a floor qualifies because the
        budget rests on it; an unreachable number of either kind does not.
        """
        module = _load_constants()
        budget = module["calibration_timeout_seconds"]
        reachable = {
            budget(count, kind)
            for count in self.LEGAL_CASE_COUNTS
            for kind in self.KINDS
        }

        declared = {
            name: value
            for name, value in module.items()
            if isinstance(value, int)
            and not isinstance(value, bool)
            and self._NAMES_A_CLAMP.search(name)
        }
        self.assertTrue(declared, "this module declares no timeout clamp at all")

        # Every argument of a `min`/`max` bounding the budget's RETURNED value
        # that is a number this test can resolve - a literal, or a module
        # constant by name. Scoped to the return because that is where a bound
        # on the wait can be: `max(1, case_count)` further up guards a count,
        # not a number of seconds, and is not a clamp on anything. An expression
        # argument is left alone; it is the work, not a bound on it.
        written: dict[str, int] = {}
        returns = [
            node.value
            for node in ast.walk(self._budget_source())
            if isinstance(node, ast.Return) and node.value is not None
        ]
        self.assertTrue(returns, "the budget function returns nothing")
        for node in [child for tree in returns for child in ast.walk(tree)]:
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"min", "max"}
            ):
                continue
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, int
                ):
                    written[f"{node.func.id}({argument.value})"] = argument.value
                elif isinstance(argument, ast.Name) and isinstance(
                    module.get(argument.id), int
                ):
                    written[argument.id] = module[argument.id]

        unreachable = sorted(
            f"{where}={value}"
            for where, value in {**declared, **written}.items()
            if value not in reachable
        )
        self.assertEqual(
            unreachable,
            [],
            "a clamp is declared or written that the budget never returns for "
            "any legal case count, so it cannot bind - it reads as a protection "
            "this module does not have",
        )

    def test_the_budget_is_the_work_and_never_a_flat_default(self) -> None:
        """`DEFAULT_TIMEOUT_SECONDS = 30` was one number for every case set.

        It killed a working evaluator that takes about a minute per call and
        reported it as unverifiable - and a flat 300 would have done the same
        thing one order of magnitude later, so the defect is the flatness and
        not the value. What has to keep holding is that below the ceiling the
        budget is exactly the work: probes times the per-probe allowance, with
        nothing added, nothing floored and nothing substituted.

        Asserting the identity rather than a table of numbers is what makes this
        survive a re-tuning. Change `DETERMINISTIC_SECONDS_PER_PROBE` and it
        still passes; add a rounding, a margin or a substituted constant and it
        does not.
        """
        module = _load_constants()
        budget = module["calibration_timeout_seconds"]
        probes_per_case = module["PROBES_PER_CASE"]
        ceiling = module["CALIBRATION_TIMEOUT_CEILING_SECONDS"]
        per_probe = module["SECONDS_PER_PROBE"]

        below_ceiling = 0
        for kind in self.KINDS:
            for count in self.LEGAL_CASE_COUNTS:
                derived = max(1, count) * probes_per_case * per_probe[kind]
                with self.subTest(kind=kind, cases=count):
                    self.assertEqual(budget(count, kind), min(ceiling, derived))
                if derived < ceiling:
                    below_ceiling += 1
        self.assertGreater(
            below_ceiling,
            0,
            "the ceiling binds at every legal size, so this proves nothing "
            "about the derivation it is meant to be checking",
        )

    def test_the_default_wait_is_derived_where_the_case_count_is_known(self) -> None:
        """The derivation has to be the thing that is actually called.

        The two tests above prove `calibration_timeout_seconds` is honest; they
        say nothing about whether anyone uses it. A merge that restored the old
        flat default would leave both of them passing and still hand every
        calibration 30 seconds, because the constant and the caller are separate
        lines - and the caller is the only one the user feels.

        Read structurally, from the one branch that decides an unset `--timeout`:
        whatever it assigns must be a call to the derivation. A literal there, a
        module constant there, or no such branch at all, all fail. The case
        count has to be in hand for the derivation to mean anything, which is
        why this is checked at the call site and not at parse time.
        """
        assignments: list[str] = []
        for node in ast.walk(ast.parse(SCRIPT.read_text())):
            if not isinstance(node, ast.If):
                continue
            test = ast.unparse(node.test).replace(" ", "")
            if test not in {"args.timeoutisNone", "args.timeoutis None"}:
                continue
            for statement in ast.walk(node):
                if isinstance(statement, ast.Assign) and any(
                    ast.unparse(target) == "args.timeout"
                    for target in statement.targets
                ):
                    assignments.append(ast.unparse(statement.value))
        self.assertEqual(
            len(assignments),
            1,
            "the branch that fills in an unset --timeout is gone, or there is "
            f"more than one of it: {assignments}",
        )
        self.assertRegex(
            assignments[0],
            r"^calibration_timeout_seconds\(",
            "an unset --timeout is filled in with something other than the "
            "derived budget, so the work-scaled number this branch computes is "
            "not the number anyone waits",
        )

    def test_one_timeout_is_the_whole_calibration_not_one_per_phase(self) -> None:
        """`--timeout N` must be the wait, not half of it.

        The supplemental phase opened a second budget of the same size after the
        authored phase returned, so a user told "about five minutes" could wait
        ten. Measured rather than read off the source, because the two phases are
        two `subprocess.run` calls and only the clock knows whether they share a
        deadline.
        """
        budget_seconds = 4
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            scorer = directory / "slow_everywhere_scorer.py"
            scorer.write_text(
                "import time\n\n\n"
                "def score(*, output, expected, input_data=None, metadata=None):\n"
                "    if type(output).__name__ in {\n"
                "        'AdversarialOutputProbe', 'MalformedTextOutputProbe'\n"
                "    }:\n"
                "        time.sleep(30)\n"
                "    time.sleep(0.3)\n"
                "    return 1.0 if output == expected else 0.0\n"
            )
            cases = directory / "cases.json"
            cases.write_text(json.dumps(self.CASES))
            started = time.monotonic()
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{scorer}:score",
                    "--cases",
                    f"@{cases}",
                    "--timeout",
                    str(budget_seconds),
                    "--allow-execution",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
            elapsed = time.monotonic() - started

        # The authored phase spends most of the budget; the supplemental probes
        # get what is left of the same one, and hang until it runs out.
        self.assertLess(
            elapsed,
            budget_seconds + 1.5,
            f"--timeout {budget_seconds} took {elapsed:.2f}s of wall clock; the "
            "supplemental phase is taking a second budget",
        )
        payload = json.loads(process.stdout)
        self.assertIn("supplemental_probe_advisory", payload)

    def test_degraded_supplemental_evidence_is_announced_not_only_recorded(
        self,
    ) -> None:
        """--json writes the payload to a file; stderr is what gets read.

        The documented invocation redirects stdout into
        `calibration-results.json`, so an advisory that exists only in the
        payload is advisory evidence lost quietly.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            scorer = directory / "hanging_supplemental_scorer.py"
            scorer.write_text(
                "import time\n\n"
                "def score(output, expected, input_data=None, metadata=None):\n"
                "    if type(output).__name__ in {\n"
                "        'AdversarialOutputProbe', 'MalformedTextOutputProbe'\n"
                "    }:\n"
                "        time.sleep(10)\n"
                "    required = set(expected)\n"
                "    actual = set(output)\n"
                "    return len(required & actual) / len(required)\n"
            )
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{scorer}:score",
                    "--expected",
                    "['name', 'email']",
                    "--good",
                    "['name', 'email']",
                    "--equivalent-good",
                    "['email', 'name']",
                    "--partial",
                    "['name']",
                    "--bad",
                    "['unrelated']",
                    "--timeout",
                    "1",
                    "--allow-execution",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
        payload = json.loads(process.stdout)
        self.assertIn("supplemental_probe_advisory", payload)
        self.assertIn(
            f"ADVISORY: {payload['supplemental_probe_advisory']}", process.stderr
        )

    def test_a_timeout_says_slow_is_not_the_same_as_broken(self) -> None:
        """The cap means "not verified", never "this evaluator is bad"."""
        with tempfile.TemporaryDirectory() as raw:
            process = self._run_slow_calibration(Path(raw))
        self.assertIn("does not by itself mean the evaluator is broken", process.stderr)

    def test_the_timeout_line_carries_the_whole_question_not_two_of_its_answers(
        self,
    ) -> None:
        """This line always reaches the assistant; the reference may not be loaded.

        It used to offer a larger `--timeout` or a faster model - two of five
        options, and an invitation to double the user's wait without asking.
        """
        with tempfile.TemporaryDirectory() as raw:
            process = self._run_slow_calibration(Path(raw))
        normalized = " ".join(process.stderr.split())
        self.assertIn("Do not silently re-run with a larger --timeout", normalized)
        self.assertIn("Ask the user once, in one question", normalized)
        for option in (
            "wait, if the evaluator is normally this slow",
            "take a named fix",
            "score with a different judge model",
            "deterministic comparison",
            "retry",
            "build a new evaluation method together",
        ):
            with self.subTest(option=option):
                self.assertIn(option, normalized)


# The pure, import-free helpers this file evaluates out of the script. They sit
# together, immediately after the constants they read, so the walk below stops
# before the first assignment that needs an import (`TOKEN_SPLIT`, a compiled
# regex) - which is why this collects a named set and returns at the last of
# them rather than reading the whole module.
_PURE_HELPERS = (
    "calibration_timeout_seconds",
    "pre_cap_warning_delay",
    "pre_cap_warning_message",
)


def _load_constants() -> dict:
    """Load the module's timeout constants and pure helpers without importing it.

    Importing the script executes its argument parser at module scope in some
    entry paths; the module-level constants and these pure functions are all
    this needs.

    Every top-level assignment up to and including the last required helper is
    evaluated, in source order, and nothing is suppressed. The previous version
    filtered by name prefix, so renaming a constant made it silently absent here
    instead of failing; a swallowed exec would do the same thing one layer down.
    """
    import ast

    source = SCRIPT.read_text()
    tree = ast.parse(source)
    namespace: dict = {}
    remaining = set(_PURE_HELPERS)
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            exec(compile(ast.Module([node], []), "<calibrator>", "exec"), namespace)
        elif isinstance(node, ast.FunctionDef) and node.name in remaining:
            exec(compile(ast.Module([node], []), "<calibrator>", "exec"), namespace)
            remaining.discard(node.name)
            if not remaining:
                return namespace
    raise AssertionError(
        "calibrate_evaluator.py no longer defines: " + ", ".join(sorted(remaining))
    )


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
        self.assertEqual(
            free_calls,
            20,
            "the deterministic path adds one binding and five exception probes per case",
        )

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


class TheResultNamesTheEvaluatorItCalibratedTests(unittest.TestCase):
    """traigent-first-run#260: a result that says what it measured.

    The `--json` result recorded nothing identifying the evaluator it ran
    against - no digest, no path, no timestamp of the file it read. The guide
    writes that result to one conventional path with `>`, so an interrupted or
    repeated first run leaves exactly one where the next run reaches for it,
    and a calibration produced for evaluator A read as current evidence about
    evaluator B. `evaluator_sha256` is the fact that makes the two
    distinguishable; `readiness.py` is what compares them.

    `evaluator_path` is the other half, and without it the comparison accuses
    the wrong people. The guide has this tool run a thin adapter under
    `traigent-runs/` while the opening gate reads the customer's own evaluator
    where it lives, so two digests that differ is the ordinary state of the
    documented "brought their own" path. Only two digests that differ at ONE
    path is a stale result.
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
            "name": "second extraction",
            "expected": ["city", "country"],
            "input_data": {"format": "fields"},
            "probes": {
                "good": ["city", "country"],
                "equivalent_good": ["country", "city"],
                "partial": ["city"],
                "bad": ["unrelated"],
            },
        },
    ]

    SCORER_SOURCE = (
        "def score(output, expected, input_data=None, metadata=None):\n"
        "    required = set(expected)\n"
        "    return len(required & set(output)) / len(required)\n"
    )

    @staticmethod
    def _digest_of(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    @staticmethod
    def _script_module():
        spec = importlib.util.spec_from_file_location(
            "first_run_calibrate_identity", SCRIPT
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def _calibrate(
        self, directory: Path, source: str, cases: list[dict], *extra: str
    ) -> tuple[subprocess.CompletedProcess, dict]:
        scorer = directory / "scorer.py"
        scorer.write_text(source)
        case_file = directory / "cases.json"
        case_file.write_text(json.dumps(cases))
        process = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--scorer",
                f"{scorer}:score",
                "--cases",
                f"@{case_file}",
                "--allow-execution",
                "--timeout",
                "20",
                "--json",
                *extra,
            ],
            capture_output=True,
            text=True,
        )
        self.assertIn(process.returncode, (0, 1), process.stderr[-2000:])
        return process, json.loads(process.stdout)

    def test_a_matrix_result_names_the_evaluator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, payload = self._calibrate(
                Path(directory), self.SCORER_SOURCE, self.CASES
            )
            # The matrix shape, pinned so the assertion cannot be satisfied by
            # the flat one drifting into this test.
            self.assertIn("cases", payload)
            self.assertTrue(payload["passed"])
            self.assertEqual(
                payload["evaluator_sha256"], self._digest_of(self.SCORER_SOURCE)
            )

    def test_a_failing_calibration_still_names_the_evaluator(self) -> None:
        """A result nobody is proud of is still a result about one file.

        Worth its own case because the refusal downstream is about identity,
        not about the verdict: a FAILING calibration of some other evaluator
        is exactly the payload that must not be allowed to raise
        `evaluator-invalid` against the evaluator actually being scored.
        """
        constant = "def score(output, expected, input_data=None, metadata=None):\n    return 1.0\n"
        with tempfile.TemporaryDirectory() as directory:
            _, payload = self._calibrate(Path(directory), constant, self.CASES)
            self.assertFalse(payload["passed"])
            self.assertEqual(payload["evaluator_sha256"], self._digest_of(constant))

    def test_a_single_case_result_names_the_evaluator(self) -> None:
        """The flat shape has its own result dict and would drop it separately."""
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "scorer.py"
            scorer.write_text(self.SCORER_SOURCE)
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{scorer}:score",
                    "--expected",
                    json.dumps(["name", "email"]),
                    "--good",
                    json.dumps(["name", "email"]),
                    "--equivalent-good",
                    json.dumps(["email", "name"]),
                    "--partial",
                    json.dumps(["name"]),
                    "--bad",
                    json.dumps(["unrelated"]),
                    "--allow-execution",
                    "--timeout",
                    "20",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
            self.assertIn(process.returncode, (0, 1), process.stderr[-2000:])
            payload = json.loads(process.stdout)
            # The flat shape, pinned the same way and for the same reason.
            self.assertNotIn("cases", payload)
            self.assertEqual(
                payload["evaluator_sha256"], self._digest_of(self.SCORER_SOURCE)
            )

    def test_a_timed_out_result_names_the_evaluator(self) -> None:
        """A timeout is a claim about one evaluator too.

        Its `evaluator-timeout` cap must not be raised against whatever
        evaluator a later run happens to be scoring, and the timeout payload
        is built in its own branch that would keep its old silence.
        """
        slow = (
            "import time\n\n\n"
            "def score(output, expected, input_data=None, metadata=None):\n"
            "    time.sleep(30)\n"
            "    return 1.0\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "slow_scorer.py"
            scorer.write_text(slow)
            case_file = Path(directory) / "cases.json"
            case_file.write_text(json.dumps(self.CASES))
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{scorer}:score",
                    "--cases",
                    f"@{case_file}",
                    "--allow-execution",
                    "--timeout",
                    "2",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(process.returncode, 1, process.stderr[-2000:])
            payload = json.loads(process.stdout)
            self.assertTrue(payload["timed_out"])
            self.assertEqual(payload["evaluator_sha256"], self._digest_of(slow))
            self.assertEqual(payload["evaluator_path"], str(scorer.resolve()))

    def test_an_evaluator_whose_bytes_cannot_be_decoded_is_not_named(self) -> None:
        """No text was read, so the helper says so instead of inventing a name.

        Unit-level because the CLI path cannot reach a result here - the child
        that imports such a file fails first - and because an absent stamp has
        to keep meaning "could not say", never "read it and it was empty".
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scorer.py"
            path.write_bytes(b"\xff\xfe\x00def score():\n")
            module = self._script_module()
            self.assertIsNone(module.evaluator_source_digest(path))
            self.assertIsNone(
                module.evaluator_source_digest(Path(directory) / "absent.py")
            )

    def test_the_result_names_the_file_it_ran_and_not_only_its_bytes(
        self,
    ) -> None:
        """The half that keeps the comparison from firing on the wrong runs.

        A digest alone cannot tell "this file changed under us" from "these
        are two different files", and the guide makes the second one the
        documented path: the customer's evaluator is preserved where it is and
        a thin adapter over it is what gets calibrated here.
        """
        with tempfile.TemporaryDirectory() as directory:
            process, payload = self._calibrate(
                Path(directory), self.SCORER_SOURCE, self.CASES
            )
            self.assertEqual(process.returncode, 0, process.stderr[-2000:])
            self.assertEqual(
                payload["evaluator_path"],
                str((Path(directory) / "scorer.py").resolve()),
            )

    def test_a_relative_scorer_is_stamped_where_it_actually_is(self) -> None:
        """Resolved, because two processes need not share a directory.

        `traigent-runs/evaluator.py` read from two different working
        directories is two different files, and a stamp that recorded the
        typed string would call them one - which is the direction that
        produces a false accusation rather than a missed one.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "traigent-runs").mkdir()
            scorer = root / "traigent-runs" / "evaluator.py"
            scorer.write_text(self.SCORER_SOURCE)
            case_file = root / "cases.json"
            case_file.write_text(json.dumps(self.CASES))
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    "traigent-runs/evaluator.py:score",
                    "--cases",
                    "@cases.json",
                    "--allow-execution",
                    "--timeout",
                    "20",
                    "--json",
                ],
                capture_output=True,
                text=True,
                cwd=root,
            )
            self.assertEqual(process.returncode, 0, process.stderr[-2000:])
            payload = json.loads(process.stdout)
            self.assertNotEqual(payload["evaluator_path"], "traigent-runs/evaluator.py")
            self.assertEqual(payload["evaluator_path"], str(scorer.resolve()))

    def test_the_stamp_agrees_with_what_the_opening_gate_reports(self) -> None:
        """The contract that makes the comparison mean anything at all.

        Two scripts computing a digest their own way would disagree on any
        file whose text and bytes differ - a CRLF checkout is enough - and
        `readiness.py` would then report every legitimate calibration as
        produced for a different evaluator. Both digests are computed here by
        running the two real scripts, so a change to either side's computation
        fails this rather than surfacing as a refusal on somebody's card.
        """
        crlf_source = self.SCORER_SOURCE.replace("\n", "\r\n")
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "scorer.py"
            scorer.write_bytes(crlf_source.encode())
            case_file = Path(directory) / "cases.json"
            case_file.write_text(json.dumps(self.CASES))
            calibration = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{scorer}:score",
                    "--cases",
                    f"@{case_file}",
                    "--allow-execution",
                    "--timeout",
                    "20",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
            self.assertIn(calibration.returncode, (0, 1), calibration.stderr[-2000:])
            preflight = subprocess.run(
                [
                    sys.executable,
                    str(PREFLIGHT),
                    "--evaluator",
                    str(scorer),
                    "--defer-missing-sdk",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
            self.assertIn(preflight.returncode, (0, 1), preflight.stderr[-2000:])
        stamped = json.loads(calibration.stdout)["evaluator_sha256"]
        shape = next(
            record
            for record in json.loads(preflight.stdout)
            if record["check"] == "evaluator-shape"
        )
        self.assertEqual(stamped, shape["metrics"]["sha256"])
        # And it is the digest of the DECODED text, not of the bytes on disk -
        # which is what makes one evaluator checked out twice, with two line
        # ending conventions, still one evaluator.
        self.assertEqual(stamped, self._digest_of(self.SCORER_SOURCE))

    NON_ASCII_SCORER = (
        "def score(output, expected, input_data=None, metadata=None):\n"
        '    """Naïve set overlap - the accent is the point of this file."""\n'
        "    required = set(expected)\n"
        "    return len(required & set(output)) / len(required)\n"
    )

    @staticmethod
    def _preferred_encoding(environment: dict) -> str:
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import locale; print(locale.getpreferredencoding(False))",
            ],
            capture_output=True,
            text=True,
            env=environment,
        )
        return probe.stdout.strip()

    def test_the_two_scripts_agree_across_two_host_text_defaults(self) -> None:
        """One evaluator, two interpreters, one name.

        The guide runs the opening gate under the host `python3` and this tool
        under whichever interpreter the run has, so `read_text()`'s
        locale-preferred default was not one decision but two. Two hosts that
        disagree about it - UTF-8 mode on against off - would give one
        non-ASCII evaluator two different answers, and `readiness.py` would
        report a calibration that is genuinely current as produced for a
        different evaluator.

        Run as the defect arrives: the two sides in OPPOSITE regimes. Both
        environments are checked to be genuinely different first, so a host
        that cannot produce two defaults fails here rather than passing this
        while measuring one regime twice.
        """
        ascii_environment = {
            **os.environ,
            "LC_ALL": "C",
            "PYTHONCOERCECLOCALE": "0",
            "PYTHONUTF8": "0",
        }
        utf8_environment = {**os.environ, "PYTHONUTF8": "1"}
        ascii_preferred = self._preferred_encoding(ascii_environment)
        utf8_preferred = self._preferred_encoding(utf8_environment)
        self.assertNotEqual(
            ascii_preferred.casefold(),
            utf8_preferred.casefold(),
            "this host reports one text default under both regimes, so this "
            "test cannot tell a named encoding from an inherited one",
        )
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "scorer.py"
            scorer.write_text(self.NON_ASCII_SCORER, encoding="utf-8")
            case_file = Path(directory) / "cases.json"
            case_file.write_text(json.dumps(self.CASES))
            calibration = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{scorer}:score",
                    "--cases",
                    f"@{case_file}",
                    "--allow-execution",
                    "--timeout",
                    "20",
                    "--json",
                ],
                capture_output=True,
                text=True,
                env=ascii_environment,
            )
            self.assertIn(calibration.returncode, (0, 1), calibration.stderr[-2000:])
            preflight = subprocess.run(
                [
                    sys.executable,
                    str(PREFLIGHT),
                    "--evaluator",
                    str(scorer),
                    "--defer-missing-sdk",
                    "--json",
                ],
                capture_output=True,
                text=True,
                env=utf8_environment,
            )
            self.assertIn(preflight.returncode, (0, 1), preflight.stderr[-2000:])
        shape = next(
            record
            for record in json.loads(preflight.stdout)
            if record["check"] == "evaluator-shape"
        )
        stamped = json.loads(calibration.stdout)["evaluator_sha256"]
        # Each side named the file at all - under the locale-preferred default
        # the ASCII-regime side could not read it, so the comparison it was
        # supposed to make silently did not happen.
        self.assertEqual(shape["metrics"]["sha256"], stamped)
        self.assertEqual(stamped, self._digest_of(self.NON_ASCII_SCORER))
        # And the CRLF property is not paid for by naming an encoding: text
        # mode still translates line endings, so one evaluator checked out
        # twice is still one evaluator.
        with tempfile.TemporaryDirectory() as directory:
            crlf = Path(directory) / "scorer.py"
            crlf.write_bytes(self.NON_ASCII_SCORER.replace("\n", "\r\n").encode())
            crlf_preflight = subprocess.run(
                [
                    sys.executable,
                    str(PREFLIGHT),
                    "--evaluator",
                    str(crlf),
                    "--defer-missing-sdk",
                    "--json",
                ],
                capture_output=True,
                text=True,
                env=ascii_environment,
            )
            self.assertIn(crlf_preflight.returncode, (0, 1), crlf_preflight.stderr)
        crlf_shape = next(
            record
            for record in json.loads(crlf_preflight.stdout)
            if record["check"] == "evaluator-shape"
        )
        self.assertEqual(crlf_shape["metrics"]["sha256"], stamped)


class NoInternalFailureReachesTheUserAsATracebackTests(unittest.TestCase):
    """An unexpected error printed a traceback where the calibration goes.

    `main` handled the failures it could name and let every other one escape
    to the interpreter. A defect in this script must not read to the customer
    as a defect in the evaluator it was asked to check.
    """

    @staticmethod
    def _module():
        spec = importlib.util.spec_from_file_location("first_run_calibrate", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_an_unexpected_error_is_diagnosed_rather_than_dumped(self) -> None:
        module = self._module()
        for error in (KeyError("cases"), TypeError("not subscriptable")):
            with self.subTest(error=type(error).__name__):

                def boom() -> None:
                    raise error

                module.parse_args = boom
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = module.main()
                self.assertEqual(code, module.INTERNAL_ERROR_EXIT)
                self.assertEqual(out.getvalue(), "")
                self.assertIn(type(error).__name__, err.getvalue())
                self.assertNotIn("Traceback (most recent call last)", err.getvalue())
                self.assertIn("treat the evaluator as unchecked", err.getvalue())

    def test_the_stack_is_still_available_to_whoever_is_fixing_it(self) -> None:
        module = self._module()
        stream = io.StringIO()
        code = module.report_internal_error(
            "calibrate_evaluator.py",
            ValueError("boom"),
            environ={module.TRACEBACK_ENV: "1"},
            stream=stream,
        )
        self.assertEqual(code, module.INTERNAL_ERROR_EXIT)
        self.assertIn("ValueError: boom", stream.getvalue())

    def test_a_refusal_still_exits_two_rather_than_three(self) -> None:
        """The false-red direction: a named refusal is not an internal error."""
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "scorer.py"
            scorer.write_text(
                "def score(output, expected, **kwargs):\n    return 1.0\n"
            )
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scorer",
                    f"{scorer}:score",
                    "--kind",
                    "deterministic",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertIn("--allow-execution", process.stderr)
        self.assertNotIn("internal error", process.stderr)


if __name__ == "__main__":
    unittest.main()

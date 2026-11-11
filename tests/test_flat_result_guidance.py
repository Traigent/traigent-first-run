"""Flat measurements and a constant evaluator are different evidence (#610)."""

import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "traigent-first-run"


class FlatResultGuidanceTests(unittest.TestCase):
    def test_completion_and_recovery_share_the_evidence_based_interpretation(self):
        safety = (SKILL_ROOT / "references" / "run-safety.md").read_text()
        verification = " ".join(
            safety.split("### Verification checks", 1)[1]
            .split("### Run-scope statement", 1)[0]
            .split()
        )
        for statement in (
            "Primary objective measures appear and satisfy the metric's contract",
            "Flat measured scores alone do not invalidate a calibrated comparison",
            "all-one maximized accuracy and all-zero minimized error can be correct",
            "flat poor performance is a measured outcome, not an established evaluator defect",
            "The gate in `evaluation-and-dataset.md`'s Mandatory calibration remains in force",
            "Check calibration, references, truncation and provider failures before prescribing repair",
        ):
            with self.subTest(statement=statement):
                self.assertIn(statement, verification)
        recovery = " ".join(
            safety.split("## Recovery", 1)[1]
            .split("### Run record and resuming", 1)[0]
            .split()
        )
        self.assertIn(
            "Flat measures alone: follow Post-run verification's no-lift interpretation",
            recovery,
        )
        self.assertIn("under a newly scoped approval", recovery)

    def test_flat_observations_do_not_require_a_constant_evaluator(self):
        """Run the real calibration CLI, with no network or provider dependency.

        The same calibrated scorer measures all-correct and all-wrong samples;
        complementing accuracy gives the equivalent minimized error observation.
        A scorer returning one for every probe must still fail calibration.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for expression, expected_exit in (
                (
                    "float(output.strip().casefold() == expected.strip().casefold())",
                    0,
                ),
                ("1.0", 1),
            ):
                with self.subTest(expression=expression):
                    scorer = root / "scorer.py"
                    scorer.write_text(
                        "def score(output, expected, input_data=None, metadata=None):\n"
                        f"    return {expression}\n",
                        encoding="utf-8",
                    )
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-I",
                            "-S",
                            "-B",
                            str(SKILL_ROOT / "scripts" / "calibrate_evaluator.py"),
                            "--scorer",
                            f"{scorer}:score",
                            "--good",
                            '"positive"',
                            "--equivalent-good",
                            '" POSITIVE "',
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
                        cwd=root,
                        env={"PATH": os.defpath},
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    self.assertEqual(result.returncode, expected_exit, result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertEqual(payload["passed"], expected_exit == 0)
                    self.assertEqual(
                        payload["checks"]["non_constant"], expected_exit == 0
                    )
                    if expected_exit:
                        continue
                    score = runpy.run_path(str(scorer))["score"]
                    accuracy = [
                        score(output, "positive")
                        for output in ("positive", " POSITIVE ")
                    ]
                    self.assertEqual(accuracy, [1.0, 1.0])
                    self.assertEqual([1.0 - value for value in accuracy], [0.0, 0.0])
                    self.assertEqual(
                        [score(output, "positive") for output in ("negative", "mixed")],
                        [0.0, 0.0],
                    )

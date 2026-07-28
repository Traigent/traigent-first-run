"""Replay tests for the preflight -> readiness adapter.

These drive the real `preflight.py --json | readiness.py --preflight -` pipeline
over tiny JSONL fixtures rather than hand-constructing `DatasetFacts`, so they
pin the adapter against the two commonest real dataset shapes the scorer must
report honestly:

* an unlabelled-but-present dataset must reach the "no expected outputs" cap
  (30 / PARTIAL), not be mistaken for an absent dataset (20 / NOT READY);
* a dataset with malformed rows must fire the structural-integrity cap (35);
* declared real provenance must score the full 10-point production band, while
  declared-synthetic provenance scores 3 and is capped.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "traigent-first-run" / "scripts"
PREFLIGHT = SCRIPTS / "preflight.py"
READINESS = SCRIPTS / "readiness.py"


def _write_jsonl(directory: Path, name: str, rows: list[dict]) -> Path:
    path = directory / name
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def _preflight_records(dataset: Path) -> list[dict]:
    """Run the real preflight and return its `--json` records."""
    process = subprocess.run(
        [
            sys.executable,
            str(PREFLIGHT),
            "--dataset",
            str(dataset),
            "--defer-missing-sdk",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    # preflight exits 1 whenever any check FAILs (an unlabelled or malformed
    # dataset does), so 0 and 1 are both expected; the JSON is emitted regardless.
    assert process.returncode in (0, 1), process.stderr
    return json.loads(process.stdout)


def _score(dataset: Path, extra: tuple[str, ...] = ()) -> dict:
    """Replay preflight JSON into readiness and return the parsed score."""
    preflight_json = json.dumps(_preflight_records(dataset))
    process = subprocess.run(
        [sys.executable, str(READINESS), "--preflight", "-", "--json", *extra],
        input=preflight_json,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def _provenance_metric(records: list[dict]) -> dict:
    return next(
        record["metrics"]
        for record in records
        if record["check"] == "dataset-provenance"
    )


def _dataset_subscore(score: dict, name: str) -> dict:
    pillar = next(p for p in score["pillars"] if p["name"] == "dataset")
    return next(sub for sub in pillar["subscores"] if sub["name"] == name)


# A healthy evaluator and search space so the overall score is bound by the
# dataset cap under test rather than by an absent evaluator or agent.
HEALTHY_CALIBRATION = {
    "cases": [
        {
            "checks": {"good_passes": True, "bad_fails": True, "non_constant": True},
            "scores": {"good": 1.0, "bad": 0.0},
        }
    ]
}
HEALTHY_SPACE = {
    "knobs": {
        "temperature": [0.0, 0.5, 1.0],
        "prompt_policy": ["direct", "structured", "criteria_first"],
    },
    "wired": ["temperature", "prompt_policy"],
    "max_trials": 12,
}


class ReadinessAdapterReplayTests(unittest.TestCase):
    def _healthy_context(self, directory: Path) -> tuple[str, ...]:
        calibration = directory / "calibration.json"
        space = directory / "space.json"
        calibration.write_text(json.dumps(HEALTHY_CALIBRATION))
        space.write_text(json.dumps(HEALTHY_SPACE))
        return (
            "--calibration",
            str(calibration),
            "--config-space",
            str(space),
            "--evaluator-method",
            "exact",
            "--task-kind",
            "closed-label",
        )

    def test_unlabelled_but_present_reaches_cap_30_not_cap_20(self) -> None:
        """C1: 150 real rows with inputs but no expected outputs.

        Must reach the cap-30 "no expected outputs" branch (30 / PARTIAL), not
        the cap-20 "no dataset at all" branch, and must not be mistaken for a
        structural-integrity failure.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"email-{index}",
                    "input": f"customer email {index} about topic {index % 7}",
                    "metadata": {"provenance": "production"},
                }
                for index in range(150)
            ]
            dataset = _write_jsonl(directory, "unlabelled.jsonl", rows)

            # The mechanism: a labelled-count metric survives the usable-row
            # filter even though zero rows are usable.
            provenance = _provenance_metric(_preflight_records(dataset))
            self.assertEqual(provenance["rows"], 150)
            self.assertEqual(provenance["labelled_rows"], 0)

            score = _score(dataset, self._healthy_context(directory))
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertIn("dataset-no-expected-outputs", conditions)
            self.assertNotIn("dataset-absent", conditions)
            self.assertNotIn("dataset-integrity-fail", conditions)
            self.assertEqual(score["overall"], 30)
            self.assertEqual(score["band"], "PARTIAL")

    def test_unlabelled_dataset_only_still_escapes_the_absent_cap(self) -> None:
        """C1, minimal drive: even with no evaluator or space, the cap is 30.

        The dataset-only score stays NOT READY (nothing else is connected), but
        the binding dataset cap must be "no expected outputs", never "absent".
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [{"input": f"unlabelled case {index}"} for index in range(40)]
            dataset = _write_jsonl(directory, "unlabelled-only.jsonl", rows)
            score = _score(dataset)
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertIn("dataset-no-expected-outputs", conditions)
            self.assertNotIn("dataset-absent", conditions)

    def test_malformed_rows_fire_the_integrity_cap_35(self) -> None:
        """C2: labelled rows mixed with malformed rows fire the 35 cap."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataset = directory / "malformed.jsonl"
            good = "\n".join(
                json.dumps(
                    {
                        "id": f"row-{index}",
                        "input": f"question {index}",
                        "output": f"answer {index % 3}",
                    }
                )
                for index in range(20)
            )
            dataset.write_text(
                good
                + "\n"
                + "{broken json here\n"
                + "{also broken\n"
                + '["not", "an", "object"]\n'
            )

            score = _score(dataset, self._healthy_context(directory))
            caps = {cap["condition"]: cap["ceiling"] for cap in score["caps"]}
            self.assertIn("dataset-integrity-fail", caps)
            self.assertEqual(caps["dataset-integrity-fail"], 35)
            # Labelled rows exist, so this is not a "no expected outputs" case.
            self.assertNotIn("dataset-no-expected-outputs", caps)

    def test_declared_real_provenance_scores_the_full_band(self) -> None:
        """C3: rows carrying metadata.provenance='production' score 10/10."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"distinct question {index} token{index}",
                    "output": f"answer {index % 4}",
                    "metadata": {"provenance": "production"},
                }
                for index in range(30)
            ]
            dataset = _write_jsonl(directory, "real.jsonl", rows)

            provenance = _provenance_metric(_preflight_records(dataset))
            self.assertEqual(provenance["sources"], ["production"])
            self.assertFalse(provenance["synthetic"])

            score = _score(dataset)
            subscore = _dataset_subscore(score, "provenance")
            self.assertEqual(subscore["value"], 10.0)

    def test_old_preflight_json_without_malformed_count_fails_loudly(self) -> None:
        """Version-skew guard: integrity FAIL without `malformed_rows` must not
        be silently scored (the count decides whether the 35 cap fires) - the
        scorer refuses the stale JSON and tells the user to re-run preflight.
        """
        stale_records = [
            {
                "check": "dataset-integrity",
                "status": "FAIL",
                "detail": "3/23 rows (13.0%) are unusable",
                "metrics": {},
            },
            {
                "check": "dataset-provenance",
                "status": "PASS",
                "detail": "declared sources: ['unknown']",
                "metrics": {
                    "rows": 20,
                    "labelled_rows": 20,
                    "synthetic": False,
                    "sources": ["unknown"],
                },
            },
        ]
        process = subprocess.run(
            [sys.executable, str(READINESS), "--preflight", "-", "--json"],
            input=json.dumps(stale_records),
            capture_output=True,
            text=True,
        )
        self.assertEqual(process.returncode, 2, process.stdout)
        self.assertIn("malformed_rows", process.stderr)
        self.assertIn("re-run", process.stderr)

    def test_declared_synthetic_provenance_scores_three_and_is_capped(self) -> None:
        """C3: rows declaring synthetic provenance score 3/10 and are capped."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"distinct question {index} token{index}",
                    "output": f"answer {index % 4}",
                    "metadata": {"provenance": "synthetic-walkthrough"},
                }
                for index in range(30)
            ]
            dataset = _write_jsonl(directory, "synthetic.jsonl", rows)

            provenance = _provenance_metric(_preflight_records(dataset))
            self.assertTrue(provenance["synthetic"])

            score = _score(dataset)
            subscore = _dataset_subscore(score, "provenance")
            self.assertEqual(subscore["value"], 3.0)
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertIn("dataset-fully-synthetic", conditions)


if __name__ == "__main__":
    unittest.main()

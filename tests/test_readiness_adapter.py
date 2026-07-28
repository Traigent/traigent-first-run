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


def _run_readiness(records: list[dict]) -> subprocess.CompletedProcess:
    """Feed hand-built preflight records to the scorer without asserting exit."""
    return subprocess.run(
        [sys.executable, str(READINESS), "--preflight", "-", "--json"],
        input=json.dumps(records),
        capture_output=True,
        text=True,
    )


def _declared_split_records(
    tuning_metrics: dict | None,
    holdout_metrics: dict | None,
    *,
    split_status: str | None = "PASS",
) -> list[dict]:
    """Minimal preflight JSON for a dataset that declares a real split.

    `None` for either metrics dict drops that size record entirely, which is
    what a truncated, filtered, or older-version JSON looks like - the record
    itself is gone, so nothing inside it can be inspected. `split_status=None`
    drops the `dataset-split` record too, leaving the size records as the only
    surviving evidence that a split was declared.
    """
    records = [
        {
            "check": "dataset-provenance",
            "status": "PASS",
            "detail": "declared sources: ['production']",
            "metrics": {
                "rows": 100,
                "labelled_rows": 50,
                "synthetic": False,
                "sources": ["production"],
            },
        },
    ]
    if split_status is not None:
        records.append(
            {
                "check": "dataset-split",
                "status": split_status,
                "detail": "tuning and holdout inputs are disjoint",
                "metrics": {},
            }
        )
    if tuning_metrics is not None:
        records.append(
            {
                "check": "dataset-tuning-size",
                "status": "PASS",
                "detail": "50 tuning rows",
                "metrics": tuning_metrics,
            }
        )
    if holdout_metrics is not None:
        records.append(
            {
                "check": "dataset-holdout-resolution",
                "status": "PASS",
                "detail": "50 holdout rows; one example changes the score by 2.0 "
                "percentage points",
                "metrics": holdout_metrics,
            }
        )
    return records


def _split_rows(holdout_input: str) -> list[dict]:
    """50 labelled tuning rows against 50 labelled holdout rows.

    Passing the tuning half's own input template makes the two splits overlap,
    which is how preflight is driven into its `dataset-split` FAIL branch.
    """
    return [
        {
            "id": f"tune-{index}",
            "input": f"tuning question {index} token{index}",
            "output": f"answer {index % 4}",
            "split": "tune",
            "metadata": {"provenance": "production"},
        }
        for index in range(50)
    ] + [
        {
            "id": f"holdout-{index}",
            "input": holdout_input.format(index=index),
            "output": f"answer {index % 4}",
            "split": "holdout",
            "metadata": {"provenance": "production"},
        }
        for index in range(50)
    ]


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

    def test_mixed_labelled_dataset_scores_power_on_labelled_rows_only(self) -> None:
        """C4: 10 labelled rows among 100 buy the precision of 10, not of 100.

        The 90 rows that omit the expected-output field are present-but-
        unlabelled, so `malformed_rows` stays 0 and the structural-integrity
        cap must not fire - the honest report is a low power sub-score.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"labelled-{index}",
                    "input": f"labelled question {index} token{index}",
                    "output": f"answer {index % 4}",
                    "metadata": {"provenance": "production"},
                }
                for index in range(10)
            ] + [
                {
                    "id": f"unlabelled-{index}",
                    "input": f"unlabelled question {index} othertoken{index}",
                    "metadata": {"provenance": "production"},
                }
                for index in range(90)
            ]
            dataset = _write_jsonl(directory, "mixed.jsonl", rows)

            provenance = _provenance_metric(_preflight_records(dataset))
            self.assertEqual(provenance["rows"], 100)
            self.assertEqual(provenance["labelled_rows"], 10)

            score = _score(dataset, self._healthy_context(directory))
            power = _dataset_subscore(score, "power")
            self.assertEqual(power["value"], 9.6)
            self.assertIn("10 scoreable", power["evidence"])
            self.assertNotIn("100 examples", power["evidence"])
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertNotIn("dataset-integrity-fail", conditions)

    def test_labels_on_one_side_of_a_declared_split_collapse_power(self) -> None:
        """C5: a holdout nothing can score is not a holdout.

        50 labelled tuning rows against 50 unscoreable holdout rows compare
        exactly zero examples, however large the split looks.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"tune-{index}",
                    "input": f"tuning question {index} token{index}",
                    "output": f"answer {index % 4}",
                    "split": "tune",
                    "metadata": {"provenance": "production"},
                }
                for index in range(50)
            ] + [
                {
                    "id": f"holdout-{index}",
                    "input": f"holdout question {index} othertoken{index}",
                    "output": "",
                    "split": "holdout",
                    "metadata": {"provenance": "production"},
                }
                for index in range(50)
            ]
            dataset = _write_jsonl(directory, "one-sided-split.jsonl", rows)

            score = _score(dataset, self._healthy_context(directory))
            power = _dataset_subscore(score, "power")
            self.assertEqual(power["value"], 5.0)
            self.assertIn("50/0 scoreable", power["evidence"])

    def test_a_none_valued_class_label_does_not_clamp_power(self) -> None:
        """C6: a fully labelled dataset must not be reported as half unscoreable.

        The negative class of this two-class dataset is the literal string
        "None" - a no-intent label, or a null that survived a pandas round-trip
        as text. Every row carries an expected output, so the 50/50 split is
        worth the full 50-example precision; calling half of it unscoreable is
        the same class of false claim the clamp exists to remove, pointed the
        other way.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"intent-{index}",
                    "input": f"utterance {index} token{index}",
                    "output": "None" if index % 2 else "book_flight",
                    "split": "tune" if index < 50 else "holdout",
                    "metadata": {"provenance": "production"},
                }
                for index in range(100)
            ]
            dataset = _write_jsonl(directory, "none-class.jsonl", rows)

            provenance = _provenance_metric(_preflight_records(dataset))
            self.assertEqual(provenance["labelled_rows"], 100)

            score = _score(dataset, self._healthy_context(directory))
            power = _dataset_subscore(score, "power")
            self.assertEqual(power["value"], 22.0)
            self.assertIn("50 examples", power["evidence"])
            self.assertNotIn("scoreable", power["evidence"])

    def test_json_null_expected_outputs_still_clamp_power(self) -> None:
        """C7: the same shape with genuine nulls stays clamped.

        Only half of these rows can be scored, so the clamp C6 forbids must
        fire here - the predicate distinguishes the two shapes rather than
        widening what counts as a label.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"intent-{index}",
                    "input": f"utterance {index} token{index}",
                    "output": None if index % 2 else "book_flight",
                    "split": "tune" if index < 50 else "holdout",
                    "metadata": {"provenance": "production"},
                }
                for index in range(100)
            ]
            dataset = _write_jsonl(directory, "null-class.jsonl", rows)

            provenance = _provenance_metric(_preflight_records(dataset))
            self.assertEqual(provenance["labelled_rows"], 50)

            score = _score(dataset, self._healthy_context(directory))
            power = _dataset_subscore(score, "power")
            self.assertEqual(power["value"], 12.0)
            self.assertIn("25/25 scoreable", power["evidence"])

    def test_old_preflight_json_without_labelled_split_counts_fails_loudly(
        self,
    ) -> None:
        """Version-skew guard: a declared split without its per-split labelled
        counts can only be scored with the aggregate clamp, which demonstrably
        fails to lower a split whose labels all sit on one side - so refuse it
        rather than report a score that is too high.
        """
        stale_records = [
            {
                "check": "dataset-provenance",
                "status": "PASS",
                "detail": "declared sources: ['production']",
                "metrics": {
                    "rows": 100,
                    "labelled_rows": 50,
                    "synthetic": False,
                    "sources": ["production"],
                },
            },
            {
                "check": "dataset-tuning-size",
                "status": "PASS",
                "detail": "50 tuning rows",
                "metrics": {"tuning_rows": 50},
            },
            {
                "check": "dataset-holdout-resolution",
                "status": "PASS",
                "detail": "50 holdout rows; one example changes the score by 2.0 "
                "percentage points",
                "metrics": {"holdout_rows": 50},
            },
        ]
        process = subprocess.run(
            [sys.executable, str(READINESS), "--preflight", "-", "--json"],
            input=json.dumps(stale_records),
            capture_output=True,
            text=True,
        )
        self.assertEqual(process.returncode, 2, process.stdout)
        self.assertIn("tuning_labelled_rows", process.stderr)
        self.assertIn("re-run", process.stderr)

    def test_null_valued_labelled_split_counts_are_refused(self) -> None:
        """A key carrying JSON null is not a count.

        The scorer branches on *value*, so a null-valued `tuning_labelled_rows`
        reaches the same aggregate fallback an absent key would - and the
        aggregate cannot see labels sitting entirely on one side of the split.
        Presence of the key must not be mistaken for a usable number.
        """
        process = _run_readiness(
            _declared_split_records(
                {"tuning_rows": 50, "tuning_labelled_rows": None},
                {"holdout_rows": 50, "holdout_labelled_rows": None},
            )
        )
        self.assertEqual(process.returncode, 2, process.stdout)
        self.assertIn("tuning_labelled_rows", process.stderr)
        self.assertIn("re-run", process.stderr)

    def test_negative_split_counts_are_refused(self) -> None:
        """A row count cannot be negative.

        Nothing preflight emits is below zero, so a negative count means the
        JSON was hand-edited or corrupted. It is arithmetically a number, so it
        flows straight through the scorer and prints a nonsense band ("-5
        comparable examples") instead of admitting the input is unusable.
        """
        process = _run_readiness(
            _declared_split_records(
                {"tuning_rows": -5, "tuning_labelled_rows": -5},
                {"holdout_rows": -5, "holdout_labelled_rows": -5},
            )
        )
        self.assertEqual(process.returncode, 2, process.stdout)
        self.assertIn("tuning_rows", process.stderr)
        self.assertIn("holdout_labelled_rows", process.stderr)
        self.assertIn("re-run", process.stderr)

    def test_a_missing_split_size_record_is_refused(self) -> None:
        """A record that is absent altogether announces nothing.

        A JSON carrying only `dataset-tuning-size` says a split exists but
        leaves the holdout's labelled count unknowable - and an unknown holdout
        could be zero, which is the whole failure this guard exists to refuse.
        """
        process = _run_readiness(
            _declared_split_records(
                {"tuning_rows": 50, "tuning_labelled_rows": 50}, None
            )
        )
        self.assertEqual(process.returncode, 2, process.stdout)
        self.assertIn("holdout_labelled_rows", process.stderr)
        self.assertIn("re-run", process.stderr)

    def test_a_declared_split_with_no_size_records_at_all_is_refused(self) -> None:
        """`dataset-split: PASS` alone still declares a split.

        Preflight versions predating the size metrics emit the PASS status with
        no per-split counts anywhere; the status is the witness that a split
        exists when neither record survives.
        """
        process = _run_readiness(_declared_split_records(None, None))
        self.assertEqual(process.returncode, 2, process.stdout)
        self.assertIn("tuning_rows", process.stderr)
        self.assertIn("re-run", process.stderr)

    def test_size_records_declare_a_split_without_the_status_record(self) -> None:
        """The size records are a witness in their own right.

        A JSON whose `dataset-split` record never arrived still describes a
        split the moment it carries per-split sizes, so the counts inside them
        must be usable.
        """
        process = _run_readiness(
            _declared_split_records(
                {"tuning_rows": 50, "tuning_labelled_rows": None},
                {"holdout_rows": 50, "holdout_labelled_rows": None},
                split_status=None,
            )
        )
        self.assertEqual(process.returncode, 2, process.stdout)
        self.assertIn("tuning_labelled_rows", process.stderr)
        self.assertIn("re-run", process.stderr)

    def test_the_refusal_names_the_counts_that_are_actually_missing(self) -> None:
        """The message must not blame the half that is present.

        With only the labelled counts supplied, it is the totals that are
        missing; naming `tuning_labelled_rows` there sends the reader looking
        for the one key they can already see.
        """
        process = _run_readiness(
            _declared_split_records(
                {"tuning_labelled_rows": 50}, {"holdout_labelled_rows": 50}
            )
        )
        self.assertEqual(process.returncode, 2, process.stdout)
        self.assertIn("tuning_rows", process.stderr)
        self.assertIn("holdout_rows", process.stderr)
        self.assertNotIn("labelled", process.stderr)
        self.assertIn("re-run", process.stderr)

    def test_a_complete_declared_split_still_scores(self) -> None:
        """The guard must refuse only what it cannot score, never a real split."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataset = _write_jsonl(
                directory,
                "split.jsonl",
                _split_rows("holdout question {index} other{index}"),
            )

            score = _score(dataset, self._healthy_context(directory))
            power = _dataset_subscore(score, "power")
            self.assertEqual(power["value"], 22.0)
            self.assertIn("50 tuning / 50 holdout", power["evidence"])

    def test_an_overlapping_split_still_scores_through_the_no_split_branch(
        self,
    ) -> None:
        """An overlapping split emits no size records, and must not start refusing.

        `dataset-split` FAIL suppresses both metric records by construction, so
        treating FAIL as a declared split would turn every overlapping dataset
        into an exit-2 refusal. Its overlap cap already says the number is not
        trustworthy.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataset = _write_jsonl(
                directory,
                "overlap.jsonl",
                _split_rows("tuning question {index} token{index}"),
            )

            records = {record["check"] for record in _preflight_records(dataset)}
            self.assertNotIn("dataset-tuning-size", records)

            score = _score(dataset, self._healthy_context(directory))
            power = _dataset_subscore(score, "power")
            self.assertIn("no declared tuning/holdout split", power["evidence"])
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertIn("dataset-tune-holdout-overlap", conditions)

    def test_a_dataset_with_no_split_still_scores(self) -> None:
        """No split declared anywhere is not staleness - it is a plain dataset."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index}",
                    "output": f"answer {index % 4}",
                    "metadata": {"provenance": "production"},
                }
                for index in range(60)
            ]
            dataset = _write_jsonl(directory, "flat.jsonl", rows)

            score = _score(dataset, self._healthy_context(directory))
            power = _dataset_subscore(score, "power")
            self.assertEqual(power["value"], 17.6)
            self.assertIn("no declared tuning/holdout split", power["evidence"])

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

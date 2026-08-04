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
* input-only rows remain fully inspectable for a declared reference-free judge,
  including split-overlap detection.
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


def _preflight_records(dataset: Path, *extra: str) -> list[dict]:
    """Run the real preflight and return its `--json` records."""
    process = subprocess.run(
        [
            sys.executable,
            str(PREFLIGHT),
            "--dataset",
            str(dataset),
            "--defer-missing-sdk",
            "--json",
            *extra,
        ],
        capture_output=True,
        text=True,
    )
    # preflight exits 1 whenever any check FAILs (an unlabelled or malformed
    # dataset does), so 0 and 1 are both expected; the JSON is emitted regardless.
    assert process.returncode in (0, 1), process.stderr
    return json.loads(process.stdout)


def _score(
    dataset: Path,
    extra: tuple[str, ...] = (),
    preflight_extra: tuple[str, ...] = (),
) -> dict:
    """Replay preflight JSON into readiness and return the parsed score."""
    preflight_json = json.dumps(_preflight_records(dataset, *preflight_extra))
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


def _tuning_only_records() -> list[dict]:
    return [
        {
            "check": "dataset-provenance",
            "status": "PASS",
            "detail": "declared sources: ['synthetic-walkthrough']",
            "metrics": {
                "rows": 18,
                "labelled_rows": 18,
                "synthetic": True,
                "sources": ["synthetic-walkthrough"],
            },
        },
        {
            "check": "dataset-split",
            "status": "PASS",
            "detail": "tuning-only dataset; no independent validation split was declared",
            "metrics": {"kind": "tuning-only"},
        },
        {
            "check": "dataset-tuning-size",
            "status": "PASS",
            "detail": "18 tuning rows",
            "metrics": {"tuning_rows": 18, "tuning_labelled_rows": 18},
        },
    ]


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
    def test_task_kind_cli_is_closed_and_distinguishes_code_from_sql(self) -> None:
        help_result = subprocess.run(
            [sys.executable, str(READINESS), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        help_text = " ".join(help_result.stdout.split())
        self.assertIn("use code for executable source", help_text)
        self.assertIn("code-sql for SQL query output", help_text)

        invalid = subprocess.run(
            [
                sys.executable,
                str(READINESS),
                "--preflight",
                "-",
                "--task-kind",
                "sql",
                "--json",
            ],
            input="[]",
            capture_output=True,
            text=True,
        )
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("invalid choice: 'sql'", invalid.stderr)

        accepted = subprocess.run(
            [
                sys.executable,
                str(READINESS),
                "--preflight",
                "-",
                "--evaluator-method",
                "execution",
                "--task-kind",
                "code",
                "--json",
            ],
            input="[]",
            capture_output=True,
            text=True,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        score = json.loads(accepted.stdout)
        evaluation = next(
            pillar for pillar in score["pillars"] if pillar["name"] == "evaluation"
        )
        task_fit = next(
            subscore
            for subscore in evaluation["subscores"]
            if subscore["name"] == "task-fit"
        )
        self.assertEqual(task_fit["value"], 25.0)
        self.assertEqual(task_fit["evidence"], "execution suits code output")

    def _healthy_context(
        self, directory: Path, method: str = "exact"
    ) -> tuple[str, ...]:
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
            method,
            "--task-kind",
            "closed-label",
        )

    def test_tuning_only_preflight_records_are_scored_as_tuning_only(self) -> None:
        process = _run_readiness(_tuning_only_records())
        self.assertEqual(process.returncode, 0, process.stderr)
        score = json.loads(process.stdout)
        dataset = next(
            pillar for pillar in score["pillars"] if pillar["name"] == "dataset"
        )
        power = next(
            subscore for subscore in dataset["subscores"] if subscore["name"] == "power"
        )
        self.assertIn(
            "18 tuning rows and no independent validation set", power["evidence"]
        )
        self.assertNotIn("no tuning set", power["evidence"])

    def test_real_tuning_only_preflight_replays_into_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataset = _write_jsonl(
                directory,
                "tuning-only.jsonl",
                [
                    {
                        "id": f"tune-{index}",
                        "input": f"tuning question {index} token{index}",
                        "output": f"answer {index % 3}",
                        "split": "tune",
                        "metadata": {"provenance": "synthetic-walkthrough"},
                    }
                    for index in range(18)
                ],
            )
            records = _preflight_records(dataset)
            split = next(
                record for record in records if record["check"] == "dataset-split"
            )
            self.assertEqual(split["metrics"], {"kind": "tuning-only"})
            score = _score(dataset)

        power = _dataset_subscore(score, "power")
        self.assertIn(
            "18 tuning rows and no independent validation set", power["evidence"]
        )
        self.assertNotIn("no tuning set", power["evidence"])

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

    def test_reference_free_input_only_rows_keep_quality_and_split_evidence(
        self,
    ) -> None:
        """A rubric judge scores inputs without inventing answer keys."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"review request {index} token{index}",
                    "split": "tune" if index < 50 else "validation",
                    "metadata": {
                        "provenance": "production",
                        "difficulty": ("easy", "medium", "hard")[index % 3],
                    },
                }
                for index in range(100)
            ]
            dataset = _write_jsonl(directory, "reference-free.jsonl", rows)
            method_args = ("--evaluator-method", "llm-judge-rubric")
            records = _preflight_records(dataset, *method_args)
            statuses = {record["check"]: record["status"] for record in records}

            self.assertEqual(statuses["dataset-shape"], "PASS")
            self.assertEqual(statuses["dataset-outputs"], "SKIP")
            self.assertEqual(statuses["dataset-split"], "PASS")
            self.assertEqual(statuses["dataset-ids"], "PASS")
            self.assertFalse(
                any(record["check"] == "dataset-integrity" for record in records)
            )
            tuning = next(
                record for record in records if record["check"] == "dataset-tuning-size"
            )
            validation = next(
                record
                for record in records
                if record["check"] == "dataset-holdout-resolution"
            )
            self.assertEqual(tuning["metrics"]["tuning_rows"], 50)
            self.assertEqual(tuning["metrics"]["tuning_labelled_rows"], 0)
            self.assertEqual(validation["metrics"]["holdout_rows"], 50)
            self.assertEqual(validation["metrics"]["holdout_labelled_rows"], 0)

            score = _score(
                dataset,
                self._healthy_context(directory, method="llm-judge-rubric"),
                preflight_extra=method_args,
            )
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertNotIn("dataset-no-expected-outputs", conditions)
            self.assertNotIn("dataset-integrity-fail", conditions)
            power = _dataset_subscore(score, "power")
            self.assertIn("50 to tune on / 50 held back", power["evidence"])
            self.assertIn("50 examples", power["evidence"])

    def test_reference_free_input_only_split_still_detects_leakage(self) -> None:
        """Optional references must not disable input-overlap detection."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": (
                        "shared request"
                        if index in (0, 50)
                        else f"distinct request {index} token{index}"
                    ),
                    "split": "tune" if index < 50 else "validation",
                    "metadata": {"provenance": "production"},
                }
                for index in range(100)
            ]
            dataset = _write_jsonl(directory, "reference-free-overlap.jsonl", rows)
            method_args = ("--evaluator-method", "llm-judge-rubric")
            records = _preflight_records(dataset, *method_args)
            split = next(
                record for record in records if record["check"] == "dataset-split"
            )
            self.assertEqual(split["status"], "FAIL")
            self.assertIn("1 inputs overlap", split["detail"])

            score = _score(
                dataset,
                self._healthy_context(directory, method="llm-judge-rubric"),
                preflight_extra=method_args,
            )
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertIn("dataset-tune-holdout-overlap", conditions)
            self.assertNotIn("dataset-no-expected-outputs", conditions)

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
            self.assertIn("50 to tune on / 50 held back", power["evidence"])

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
            self.assertIn("no tuning set and held-back test set", power["evidence"])
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
            self.assertIn("no tuning set and held-back test set", power["evidence"])

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

    def test_real_inputs_with_generated_outputs_score_the_middle_band(self) -> None:
        """C5: collected inputs whose expected answers were written by a model.

        Scores 6 of 10 - below collected production data, above a fully
        generated set - because the ruler those rows are graded against is the
        model's opinion, not a fact anyone recorded. It must NOT reach the
        fully-synthetic branch, whose 3 points also cap the whole score at 65.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"ticket-{index}",
                    "input": f"real customer ticket {index} token{index}",
                    "output": f"answer {index % 4}",
                    "metadata": {
                        "provenance": "production",
                        "output_provenance": "generated",
                    },
                }
                for index in range(30)
            ]
            dataset = _write_jsonl(directory, "generated-outputs.jsonl", rows)

            provenance = _provenance_metric(_preflight_records(dataset))
            self.assertFalse(provenance["synthetic"])
            self.assertTrue(provenance["generated_outputs"])

            score = _score(dataset)
            subscore = _dataset_subscore(score, "provenance")
            self.assertEqual(subscore["value"], 6.0)
            self.assertIn("expected answers written by a model", subscore["evidence"])
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertNotIn("dataset-fully-synthetic", conditions)

    def test_generated_outputs_do_not_claim_real_inputs_when_inputs_are_undeclared(
        self,
    ) -> None:
        """The band asserts the INPUTS are real, so undeclared inputs lose it.

        Same 6 points either way, but the reason differs, and reporting "real
        inputs" about rows that never said where they came from would be the
        card asserting something it cannot know.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index}",
                    "output": f"answer {index % 4}",
                    "metadata": {"output_provenance": "generated"},
                }
                for index in range(30)
            ]
            dataset = _write_jsonl(directory, "undeclared-inputs.jsonl", rows)

            score = _score(dataset)
            subscore = _dataset_subscore(score, "provenance")
            self.assertEqual(subscore["value"], 6.0)
            self.assertIn("30 undeclared", subscore["evidence"])
            self.assertNotIn("collected", subscore["evidence"])

    def test_a_synthetic_row_stays_fully_synthetic_whatever_its_output_says(
        self,
    ) -> None:
        """A generated row is generated. The new field cannot upgrade it to 6."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index}",
                    "output": f"answer {index % 4}",
                    "metadata": {
                        "provenance": "synthetic-walkthrough",
                        "output_provenance": "generated",
                    },
                }
                for index in range(30)
            ]
            dataset = _write_jsonl(directory, "synthetic-both.jsonl", rows)

            score = _score(dataset)
            self.assertEqual(_dataset_subscore(score, "provenance")["value"], 3.0)
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertIn("dataset-fully-synthetic", conditions)

    def test_a_dataset_that_declares_nothing_new_scores_exactly_as_before(self) -> None:
        """Regression guard: the new field is additive, not a rescore.

        Every dataset in circulation predates `output_provenance`, so absent
        means "unchanged" - production data must still score the full 10.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index}",
                    "output": f"answer {index % 4}",
                    "metadata": {"provenance": "production"},
                }
                for index in range(30)
            ]
            dataset = _write_jsonl(directory, "production.jsonl", rows)

            provenance = _provenance_metric(_preflight_records(dataset))
            self.assertFalse(provenance["generated_outputs"])
            self.assertEqual(
                _dataset_subscore(_score(dataset), "provenance")["value"], 10.0
            )

    def test_a_row_with_no_answer_cannot_have_a_generated_answer(self) -> None:
        """The scan is scoped to rows that actually carry an expected output.

        Scoped through `dataset_row_is_labelled`, the same predicate the
        aggregate and per-split counts use, rather than a private test here -
        the checks in preflight.py disagreeing about whether a given row has an
        output is the class already filed as #68 and #70.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index}",
                    "output": f"answer {index % 4}" if index % 2 else "",
                    # Declared on every row, including the ones with no answer.
                    "metadata": {
                        "provenance": "production",
                        "output_provenance": (
                            "generated" if index % 2 == 0 else "human-reviewed"
                        ),
                    },
                }
                for index in range(30)
            ]
            dataset = _write_jsonl(directory, "half-unlabelled.jsonl", rows)

            # Only the blank-output rows claim a generated answer, and a blank
            # output is not an answer - so the band must not fire.
            provenance = _provenance_metric(_preflight_records(dataset))
            self.assertFalse(provenance["generated_outputs"])
            subscore = _dataset_subscore(_score(dataset), "provenance")
            self.assertEqual(subscore["value"], 10.0)

    def test_one_generated_row_does_not_condemn_a_collected_dataset(self) -> None:
        """The mixture bug: `any()` made 1 demo row in 1000 a generated dataset.

        999 collected rows and one generated one scored 3 of 10 and capped the
        whole run at 65, while the card claimed every row was generated. Credit
        is now per row, so the score barely moves and no cap fires.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index}",
                    "output": f"answer {index % 4}",
                    "metadata": {
                        "provenance": "synthetic" if index == 0 else "production"
                    },
                }
                for index in range(100)
            ]
            dataset = _write_jsonl(directory, "one-synthetic.jsonl", rows)

            provenance = _provenance_metric(_preflight_records(dataset))
            self.assertFalse(provenance["synthetic"])
            self.assertEqual(provenance["synthesised_rows"], 1)
            self.assertEqual(provenance["collected_rows"], 99)

            score = _score(dataset)
            subscore = _dataset_subscore(score, "provenance")
            # 99*10 + 1*3 over 100 rows.
            self.assertEqual(subscore["value"], 9.93)
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertNotIn("dataset-fully-synthetic", conditions)
            self.assertNotIn("dataset-mostly-synthetic", conditions)

    def test_a_mostly_generated_mixture_keeps_a_ceiling(self) -> None:
        """Fixing any()->all() must not hand every mixture a free pass."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index}",
                    "output": f"answer {index % 4}",
                    "metadata": {
                        "provenance": "synthetic" if index < 80 else "production"
                    },
                }
                for index in range(100)
            ]
            dataset = _write_jsonl(directory, "mostly-synthetic.jsonl", rows)

            score = _score(dataset)
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertIn("dataset-mostly-synthetic", conditions)
            self.assertNotIn("dataset-fully-synthetic", conditions)
            self.assertLessEqual(score["overall"], 70)

    def test_an_entirely_model_written_answer_key_keeps_a_ceiling(self) -> None:
        """Real questions, but every answer is a model's opinion.

        An accuracy number then reports agreement with that model rather than
        correctness, and nothing inside the run can falsify it.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"real question {index} token{index}",
                    "output": f"answer {index % 4}",
                    "metadata": {
                        "provenance": "production",
                        "output_provenance": "llm-written",
                    },
                }
                for index in range(30)
            ]
            dataset = _write_jsonl(directory, "generated-key.jsonl", rows)

            score = _score(dataset)
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertIn("dataset-generated-answer-key", conditions)
            self.assertLessEqual(score["overall"], 75)
            # "llm-written" must read as generated, not as an unknown word.
            self.assertEqual(_dataset_subscore(score, "provenance")["value"], 6.0)

    def test_reference_free_judge_ignores_a_model_written_optional_key(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"real question {index} token{index}",
                    "output": f"optional answer {index % 4}",
                    "metadata": {
                        "provenance": "production",
                        "output_provenance": "llm-written",
                    },
                }
                for index in range(30)
            ]
            dataset = _write_jsonl(directory, "unused-generated-key.jsonl", rows)
            method_args = ("--evaluator-method", "llm-judge-rubric")
            score = _score(
                dataset,
                self._healthy_context(directory, method="llm-judge-rubric"),
                preflight_extra=method_args,
            )
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertNotIn("dataset-generated-answer-key", conditions)
            labels = _dataset_subscore(score, "labels")
            provenance = _dataset_subscore(score, "provenance")
            self.assertFalse(labels["measured"])
            self.assertEqual(provenance["value"], 10.0)
            self.assertIn(
                "present but unused by this evaluator", provenance["evidence"]
            )

    def test_an_unrecognised_provenance_word_is_flagged_not_silently_credited(
        self,
    ) -> None:
        """A project's own vocabulary keeps its score, but is said out loud."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index}",
                    "output": f"answer {index % 4}",
                    "metadata": {"provenance": "crm-export"},
                }
                for index in range(30)
            ]
            dataset = _write_jsonl(directory, "own-vocabulary.jsonl", rows)

            records = _preflight_records(dataset)
            vocabulary = [
                record
                for record in records
                if record["check"] == "dataset-provenance-vocabulary"
            ]
            self.assertEqual(len(vocabulary), 1)
            self.assertEqual(vocabulary[0]["status"], "WARN")
            self.assertIn("crm-export", vocabulary[0]["detail"])
            provenance = _provenance_metric(records)
            self.assertEqual(provenance["unrecognised_sources"], ["crm-export"])

            # Unchanged score: the word list must not silently demote a project.
            # The uncertainty must survive the adapter and appear beside that
            # score, rather than disappearing between preflight and readiness.
            scored = _dataset_subscore(_score(dataset), "provenance")
            self.assertEqual(scored["value"], 10.0)
            self.assertIn("unverified declaration", scored["evidence"])
            self.assertIn("crm-export", scored["evidence"])

    def test_an_impossible_provenance_count_is_refused_not_absorbed(self) -> None:
        """A negative count must not quietly change the denominator.

        Zeroing it kept the score plausible while every share was computed over
        the wrong total, and -1 synthesised rows against 50 collected scored
        10.14 on a sub-score whose maximum is 10. Driven through the real CLI so
        the refusal is what a user actually sees. An absent key still falls back
        to 0 - that is a payload predating the field, not a broken one.
        """
        metrics = {
            "rows": 50,
            "labelled_rows": 50,
            "collected_rows": 50,
            "synthesised_rows": -1,
        }
        record = [{"check": "dataset-provenance", "status": "PASS", "metrics": metrics}]
        process = subprocess.run(
            [sys.executable, str(READINESS), "--preflight", "-", "--json"],
            input=json.dumps(record),
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("synthesised_rows", process.stderr)
        self.assertIn("re-run preflight.py --json", process.stderr)

        # Absent counts are the version-skew case and must still be accepted.
        metrics.pop("synthesised_rows")
        metrics.pop("collected_rows")
        accepted = subprocess.run(
            [sys.executable, str(READINESS), "--preflight", "-", "--json"],
            input=json.dumps(record),
            capture_output=True,
            text=True,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_a_holdout_that_omits_the_output_field_is_still_a_declared_split(
        self,
    ) -> None:
        """#66: a row missing the expected-output field never reached the split loop.

        `normalize_dataset_row` rejects it, so it landed only in `present_rows`
        and preflight reported "no explicit tuning/holdout split was found" about
        a dataset where all 100 rows declare one.
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
                    "input": f"holdout question {index} token{index}",
                    "split": "holdout",
                    "metadata": {"provenance": "production"},
                }
                for index in range(50)
            ]
            dataset = _write_jsonl(directory, "missing-holdout-output.jsonl", rows)

            records = _preflight_records(dataset)
            split = next(r for r in records if r["check"] == "dataset-split")
            self.assertNotEqual(
                split["status"], "WARN", "the split must no longer read as absent"
            )
            sizes = next(
                (r for r in records if r["check"] == "dataset-tuning-size"), None
            )
            self.assertIsNotNone(sizes, "per-split size records must be emitted")
            self.assertEqual(sizes["metrics"]["tuning_rows"], 50)
            # The holdout rows exist but none of them can be scored.
            self.assertEqual(sizes["metrics"]["tuning_labelled_rows"], 50)

    def test_a_custom_expected_field_still_counts_split_labels(self) -> None:
        """The one labelled-row oracle has to work on a raw row too.

        The split loop reads `present_rows`, which are raw, so a predicate
        hard-coded to `row["output"]` would count every answered row as
        unlabelled under `--expected-field`.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "question": f"question {index} token{index}",
                    "answer": f"answer {index % 4}",
                    "split": "tune" if index < 30 else "holdout",
                    "metadata": {"provenance": "production"},
                }
                for index in range(60)
            ]
            dataset = _write_jsonl(directory, "custom-fields.jsonl", rows)
            records = _preflight_records(
                dataset, "--input-field", "question", "--expected-field", "answer"
            )
            sizes = next(r for r in records if r["check"] == "dataset-tuning-size")
            self.assertEqual(sizes["metrics"]["tuning_rows"], 30)
            self.assertEqual(sizes["metrics"]["tuning_labelled_rows"], 30)

    def test_a_punctuation_placeholder_is_not_both_labelled_and_empty(self) -> None:
        """#70: one dataset reported both claims about the same rows."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index}",
                    "output": f"answer {index % 4}" if index % 2 else "-",
                    "metadata": {"provenance": "production"},
                }
                for index in range(100)
            ]
            dataset = _write_jsonl(directory, "placeholders.jsonl", rows)
            records = _preflight_records(dataset)
            statuses = {r["check"]: r["status"] for r in records}

            # A "-" IS a label by the one oracle, so emptiness must not be claimed.
            self.assertNotEqual(statuses.get("dataset-outputs"), "FAIL")
            # But the placeholder signal is kept, as its own separate question.
            placeholders = next(
                r for r in records if r["check"] == "dataset-output-placeholders"
            )
            self.assertEqual(placeholders["metrics"]["placeholder_rows"], 50)

            # #70's second criterion: the card may not print a confident band
            # over rows whose "answer" is punctuation. The count reaches the
            # scorer and qualifies the sentence that claims they are labelled -
            # without reclassifying them, which would move the score for every
            # dataset using a symbol as a legitimate label.
            labels = _dataset_subscore(_score(dataset), "labels")
            self.assertIn("50 are symbol-only", labels["evidence"])
            self.assertIn("retained in these counts", labels["evidence"])
            self.assertEqual(labels["value"], 30.0)

    def test_distinct_symbolic_labels_are_not_collapsed_to_one_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index}",
                    "output": "+" if index % 2 else "-",
                    "metadata": {"provenance": "production"},
                }
                for index in range(20)
            ]
            dataset = _write_jsonl(directory, "symbol-classes.jsonl", rows)
            records = _preflight_records(dataset)
            outputs = next(
                record for record in records if record["check"] == "dataset-outputs"
            )
            placeholders = next(
                record
                for record in records
                if record["check"] == "dataset-output-placeholders"
            )
            self.assertEqual(outputs["status"], "PASS")
            self.assertEqual(outputs["detail"], "2 distinct expected outputs")
            self.assertEqual(placeholders["metrics"]["placeholder_rows"], 20)

            repeated = _write_jsonl(
                directory,
                "one-symbol.jsonl",
                [{**row, "output": "-"} for row in rows],
            )
            repeated_outputs = next(
                record
                for record in _preflight_records(repeated)
                if record["check"] == "dataset-outputs"
            )
            self.assertIn(
                "every expected output is identical", repeated_outputs["detail"]
            )

    def test_unlabelled_rows_do_not_trip_the_ceiling_risk(self) -> None:
        """#68: `normalized_text(None)` -> "null" became a dominant value.

        The card docked the same 90 rows twice - once on power, once as a false
        "one expected output dominates" - and called them both unlabelled and
        identically-answered.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index}",
                    "output": f"answer {index % 5}" if index < 10 else None,
                    "metadata": {"provenance": "production"},
                }
                for index in range(100)
            ]
            dataset = _write_jsonl(directory, "mostly-unlabelled.jsonl", rows)
            statuses = {r["check"]: r["status"] for r in _preflight_records(dataset)}
            self.assertNotIn("dataset-ceiling-risk", statuses)

    def test_split_labels_exceeding_the_aggregate_are_refused(self) -> None:
        """#69: the guard checked four split counts and no aggregate.

        100 split labels against 1 aggregate label was accepted and scored 22.0
        power beside "1/100 rows carry an expected output". The splits are
        disjoint, so no dataset can be both.
        """
        payload = [
            {
                "check": "dataset-provenance",
                "status": "PASS",
                "metrics": {"rows": 100, "labelled_rows": 1},
            },
            {"check": "dataset-split", "status": "PASS", "metrics": {}},
            {
                "check": "dataset-tuning-size",
                "status": "PASS",
                "metrics": {"tuning_rows": 50, "tuning_labelled_rows": 50},
            },
            {
                "check": "dataset-holdout-resolution",
                "status": "PASS",
                "metrics": {"holdout_rows": 50, "holdout_labelled_rows": 50},
            },
        ]
        process = subprocess.run(
            [sys.executable, str(READINESS), "--preflight", "-", "--json"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("more than the 1", process.stderr)

    def test_a_negative_aggregate_count_is_refused(self) -> None:
        """#69: the same rationale the split guard gives, applied to aggregates."""
        payload = [
            {
                "check": "dataset-provenance",
                "status": "PASS",
                "metrics": {"rows": 100, "labelled_rows": -5},
            },
            {"check": "dataset-split", "status": "PASS", "metrics": {}},
            {
                "check": "dataset-tuning-size",
                "status": "PASS",
                "metrics": {"tuning_rows": 50, "tuning_labelled_rows": 25},
            },
            {
                "check": "dataset-holdout-resolution",
                "status": "PASS",
                "metrics": {"holdout_rows": 50, "holdout_labelled_rows": 25},
            },
        ]
        process = subprocess.run(
            [sys.executable, str(READINESS), "--preflight", "-", "--json"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("labelled_rows", process.stderr)


def _preflight_evaluator_records(evaluator: Path | None, *extra: str) -> list[dict]:
    """Run the real preflight over one evaluator file and return its records.

    `evaluator=None` omits `--evaluator` entirely - the shape a project with
    no evaluator file at all presents to preflight - rather than pointing at
    a path that does not exist, which is a different, narrower claim.
    """
    evaluator_args = ["--evaluator", str(evaluator)] if evaluator is not None else []
    process = subprocess.run(
        [
            sys.executable,
            str(PREFLIGHT),
            *evaluator_args,
            "--defer-missing-sdk",
            "--json",
            *extra,
        ],
        capture_output=True,
        text=True,
    )
    assert process.returncode in (0, 1), process.stderr
    return json.loads(process.stdout)


def _score_evaluator(
    evaluator: Path | None, readiness_extra: tuple[str, ...] = ()
) -> dict:
    """Replay real preflight's evaluator-shape JSON into readiness."""
    preflight_json = json.dumps(_preflight_evaluator_records(evaluator))
    process = subprocess.run(
        [
            sys.executable,
            str(READINESS),
            "--preflight",
            "-",
            "--json",
            *readiness_extra,
        ],
        input=preflight_json,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def _evaluation_caps(score: dict) -> list[str]:
    return [cap["condition"] for cap in score["caps"]]


class EvaluatorPresenceAdapterTests(unittest.TestCase):
    """traigent-first-run#133, driven through the real preflight/readiness CLIs.

    Four states an evaluator file can be in when a first run opens, replayed
    through the real `preflight.py --evaluator ... --json | readiness.py
    --preflight -` pipeline rather than hand-built facts, so the plumbing
    between the two scripts is what is actually under test.
    """

    def test_absent_evaluator_is_reported_absent_not_unresolved(self) -> None:
        score = _score_evaluator(None)
        self.assertIn("evaluator-absent", _evaluation_caps(score))
        self.assertNotIn("evaluator-unresolved", _evaluation_caps(score))

    def test_import_invalid_evaluator_is_present_but_unresolved(self) -> None:
        """A syntax error is caught by preflight's `ast.parse`, never by import."""
        with tempfile.TemporaryDirectory() as directory:
            evaluator = Path(directory) / "evaluator.py"
            evaluator.write_text("def score(output, expected:\n    return 1.0\n")
            score = _score_evaluator(evaluator)
        caps = _evaluation_caps(score)
        self.assertIn("evaluator-unresolved", caps)
        self.assertNotIn("evaluator-absent", caps)
        cap = next(c for c in score["caps"] if c["condition"] == "evaluator-unresolved")
        self.assertEqual(cap["action_kind"], "repair-evaluator")

    def test_constant_pass_evaluator_is_present_but_unresolved_before_calibration(
        self,
    ) -> None:
        """Case 08: a constant-pass file parses fine but earns no method.

        The opening gate correctly refuses to declare a method for a scorer
        whose result plainly does not depend on its input - that refusal is
        an assistant judgment call, not something this static check performs
        - so this run passes no `--evaluator-method`. The file is still
        `present`, from preflight's parse, and must not read as absent.
        """
        with tempfile.TemporaryDirectory() as directory:
            evaluator = Path(directory) / "evaluator.py"
            evaluator.write_text("def score(output, expected):\n    return 1.0\n")
            score = _score_evaluator(evaluator)
        caps = _evaluation_caps(score)
        self.assertIn("evaluator-unresolved", caps)
        self.assertNotIn("evaluator-absent", caps)
        self.assertNotIn("evaluator-invalid", caps)

    def test_constant_pass_caught_by_calibration_is_evaluator_invalid(self) -> None:
        """The same file, once a method is declared and calibration runs it.

        This is the complementary path: calibration - not the static check -
        is what is able to observe that the score never changes, and it
        reports that as `evaluator-invalid`, still distinct from
        `evaluator-unresolved`.
        """
        with tempfile.TemporaryDirectory() as directory:
            evaluator = Path(directory) / "evaluator.py"
            evaluator.write_text("def score(output, expected):\n    return 1.0\n")
            calibration = json.dumps(
                {
                    "cases": [
                        {
                            "checks": {
                                "good_passes": True,
                                "bad_fails": True,
                                "non_constant": False,
                            }
                        }
                    ]
                }
            )
            preflight_json = json.dumps(_preflight_evaluator_records(evaluator))
            calibration_path = Path(directory) / "calibration.json"
            calibration_path.write_text(calibration)
            process = subprocess.run(
                [
                    sys.executable,
                    str(READINESS),
                    "--preflight",
                    "-",
                    "--calibration",
                    str(calibration_path),
                    "--evaluator-method",
                    "exact",
                    "--json",
                ],
                input=preflight_json,
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        score = json.loads(process.stdout)
        caps = _evaluation_caps(score)
        self.assertIn("evaluator-invalid", caps)
        self.assertNotIn("evaluator-unresolved", caps)
        self.assertNotIn("evaluator-absent", caps)

    def test_healthy_evaluator_reaches_full_calibrated_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evaluator = Path(directory) / "evaluator.py"
            evaluator.write_text(
                "def score(output, expected):\n"
                "    return 1.0 if output == expected else 0.0\n"
            )
            calibration = json.dumps(
                {
                    "cases": [
                        {
                            "checks": {
                                "good_passes": True,
                                "bad_fails": True,
                                "non_constant": True,
                            }
                        },
                        {
                            "checks": {
                                "good_passes": True,
                                "bad_fails": True,
                                "non_constant": True,
                            }
                        },
                    ]
                }
            )
            preflight_json = json.dumps(_preflight_evaluator_records(evaluator))
            calibration_path = Path(directory) / "calibration.json"
            calibration_path.write_text(calibration)
            process = subprocess.run(
                [
                    sys.executable,
                    str(READINESS),
                    "--preflight",
                    "-",
                    "--calibration",
                    str(calibration_path),
                    "--evaluator-method",
                    "exact",
                    "--json",
                ],
                input=preflight_json,
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        score = json.loads(process.stdout)
        caps = _evaluation_caps(score)
        self.assertFalse(
            {"evaluator-absent", "evaluator-unresolved", "evaluator-invalid"}
            & set(caps)
        )


if __name__ == "__main__":
    unittest.main()

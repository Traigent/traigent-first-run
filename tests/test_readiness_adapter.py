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

import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "traigent-first-run" / "scripts"
PREFLIGHT = SCRIPTS / "preflight.py"
READINESS = SCRIPTS / "readiness.py"
# Imported so a points assertion can name the constant it is about rather than
# restating its value beside it.
_SPEC = importlib.util.spec_from_file_location("first_run_readiness_adapter", READINESS)
MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = MODULE
_SPEC.loader.exec_module(MODULE)


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


def _cap(score: dict, condition: str) -> dict:
    return next(cap for cap in score["caps"] if cap["condition"] == condition)


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


def _readiness_records(
    records: list[dict], extra: tuple[str, ...], *rendering: str
) -> str:
    """Score hand-built preflight records, asserting the run succeeded.

    Separate from `_score`, which starts at a JSONL file and lets the real
    preflight write the records: a payload shape preflight no longer emits -
    one written before a field existed - can only be built by hand, and that is
    exactly the shape worth replaying.
    """
    process = subprocess.run(
        [sys.executable, str(READINESS), "--preflight", "-", *rendering, *extra],
        input=json.dumps(records),
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    return process.stdout


def _score_records(records: list[dict], extra: tuple[str, ...] = ()) -> dict:
    return json.loads(_readiness_records(records, extra, "--json"))


def _card_records(records: list[dict], extra: tuple[str, ...] = ()) -> str:
    return _readiness_records(records, extra, "--color", "never", "--ascii")


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
                # Every count preflight emits together, because the scorer now
                # refuses a payload missing any of them: the fallback that read
                # an absent count as 0 was a backward-compatibility decision
                # against a version that never shipped, and it opened the
                # generated-answer-key gate for free.
                "collected_rows": 100,
                "synthesised_rows": 0,
                "undeclared_rows": 0,
                "answerable_rows": 50,
                "generated_answer_rows": 0,
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
                "collected_rows": 0,
                "synthesised_rows": 18,
                "undeclared_rows": 0,
                "answerable_rows": 18,
                "generated_answer_rows": 0,
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
        "prompt_style": ["direct", "structured", "criteria_first"],
    },
    "wired": ["temperature", "prompt_style"],
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

    def test_a_dataset_with_other_field_names_is_not_reported_as_absent(self) -> None:
        """The bug this pair exists for, end to end through the real pipeline.

        Three well-formed, fully labelled rows whose file says `question` /
        `answer` were scored as "No dataset is connected" with the machine
        recommendation `get-data` - the customer was told to go and collect
        data they already had. Preflight had already reported the real cause.

        This lives in the ADAPTER tests on purpose. The scoring tests build
        DatasetFacts by hand, so they cannot see `dataset_facts_from_preflight`
        losing the distinction, and mutating the adapter to drop it left the
        whole suite green.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {"id": "1", "question": "refund my order", "answer": "refund"},
                {"id": "2", "question": "where is my package", "answer": "tracking"},
                {"id": "3", "question": "cancel subscription", "answer": "cancel"},
            ]
            dataset = _write_jsonl(directory, "customer.jsonl", rows)
            score = _score(dataset)

        caps = {cap["condition"]: cap for cap in score["caps"]}
        self.assertNotIn("dataset-absent", caps)
        self.assertIn("dataset-shape-unrecognised", caps)
        cap = caps["dataset-shape-unrecognised"]
        # The routing is the fix. A reworded `dataset-absent` still recommended
        # `get-data` and still routed the guide into dataset creation, because
        # the remedy is keyed by condition id.
        self.assertEqual(cap["action_kind"], "read-dataset")
        self.assertEqual(score["recommended_action"], "read-dataset")
        reason = cap["reason"]
        # It must say a dataset WAS provided ...
        self.assertIn("A dataset was provided", reason)
        # ... and must not claim the project has none.
        self.assertNotIn("No dataset is connected", reason)
        self.assertNotIn("No dataset was provided", reason)
        # The cause is preflight's, forwarded verbatim rather than guessed.
        self.assertIn("missing selected input field 'input'", reason)

    def test_a_dataset_with_other_field_names_scores_clean_once_it_is_mapped(
        self,
    ) -> None:
        """The other half of the same file, and the reason the cap is not a verdict.

        The rows above are well-formed, fully labelled and entirely usable; the
        only thing wrong is that the run read them with `input`/`output`. Read
        with the fields the file actually uses, the identical bytes score with
        no dataset cap of any kind - so what the opening card capped was the
        reading, and calling it broken data was false about this file.

        This is the assertion that makes the pair a pair. Without it the suite
        could only say "the unreadable branch fires", which is exactly the
        claim that was true and misleading at the same time. It also pins the
        second half of the owner's rule: a successful re-map leaves no residue,
        so nothing may persist a cap across it.
        """
        rows = [
            {"id": str(index), "question": f"q{index}", "answer": f"a{index % 4}"}
            for index in range(40)
        ]
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "customer.jsonl", rows)
            unmapped = _score(dataset)
            mapped = _score(
                dataset,
                preflight_extra=(
                    "--input-field",
                    "question",
                    "--expected-field",
                    "answer",
                ),
            )

        self.assertIn(
            "dataset-shape-unrecognised",
            {cap["condition"] for cap in unmapped["caps"]},
        )
        # Same file, same bytes, read correctly: no dataset finding survives.
        self.assertEqual(
            [cap for cap in mapped["caps"] if cap["condition"].startswith("dataset-")],
            [],
        )
        self.assertGreater(mapped["overall"], unmapped["overall"])
        self.assertNotEqual(mapped["recommended_action"], "read-dataset")

    def test_the_more_broken_file_is_never_sent_to_collect_new_data(self) -> None:
        """The discontinuity, on one file, in one assertion.

        Ninety of a hundred rows unreadable fired `dataset-integrity-fail` and
        recommended `repair-dataset`. Making the file WORSE - all hundred
        unreadable - fired `dataset-absent` and recommended `get-data`, so the
        more broken file was the one told to go and collect data. Neither may
        route to collection: the customer has the file in both cases.

        The two remedies are deliberately not the same, and the line between
        them is evidence rather than severity. At 90 of 100, ten rows DID match
        the shape the run assumed - that confirms the assumption, so the other
        ninety are genuinely malformed and `repair-dataset` is a claim the run
        can support. At 100 of 100 nothing confirmed it, so the only supportable
        instruction is to go and read the file. Asserting both here keeps a
        later edit from collapsing them back into one remedy in either
        direction.
        """
        broken = "{not json at all"
        good = {"id": "1", "input": "q", "output": "a", "source": "collected"}
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            partial = directory / "partial.jsonl"
            partial.write_text(
                "\n".join([json.dumps(good)] * 10 + [broken] * 90) + "\n"
            )
            everything = directory / "everything.jsonl"
            everything.write_text("\n".join([broken] * 100) + "\n")
            partial_score = _score(partial)
            everything_score = _score(everything)

        self.assertEqual(partial_score["recommended_action"], "repair-dataset")
        self.assertEqual(everything_score["recommended_action"], "read-dataset")
        for score in (partial_score, everything_score):
            with self.subTest(score=score["recommended_action"]):
                self.assertNotEqual(score["recommended_action"], "get-data")
        conditions = {cap["condition"] for cap in everything_score["caps"]}
        self.assertIn("dataset-shape-unrecognised", conditions)
        self.assertNotIn("dataset-absent", conditions)

    def test_a_third_cause_is_reported_as_itself_not_as_the_other_two(self) -> None:
        """A healthy dataset can be unreadable for a reason nobody listed.

        One field path selected for both the input and the expected answer makes
        every row of a perfectly good file unusable. `normalize_dataset_row`
        reports exactly that. The sentence that named malformed lines and a
        missing field, then closed with "check both before concluding the data
        is missing", was false about this file three ways.
        """
        rows = [
            {"id": str(index), "input": f"q{index}", "output": f"a{index % 3}"}
            for index in range(120)
        ]
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "healthy.jsonl", rows)
            score = _score(
                dataset,
                preflight_extra=(
                    "--input-field",
                    "input",
                    "--expected-field",
                    "input",
                ),
            )

        caps = {cap["condition"]: cap for cap in score["caps"]}
        self.assertIn("dataset-shape-unrecognised", caps)
        reason = caps["dataset-shape-unrecognised"]["reason"]
        self.assertIn("input and expected-output field paths must be different", reason)
        # None of the guessed causes, and no claim that the list was complete.
        for invented in ("malformed lines", "expected-answer field", "Check both"):
            with self.subTest(invented=invented):
                self.assertNotIn(invented, reason)

    def test_a_missing_path_and_an_empty_file_do_not_read_the_same(self) -> None:
        """Two different problems, two different repairs, one sentence before.

        A path that does not exist is a typo or a wrong working directory. A
        file that exists and holds nothing is a dataset yet to be written. They
        produced byte-identical scores; preflight's `dataset-shape` FAIL knew
        the difference all along.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            empty = directory / "empty.jsonl"
            empty.write_text("")
            missing = directory / "not-written-yet.jsonl"
            empty_score = _score(empty)
            missing_score = _score(missing)

        empty_reason = _cap(empty_score, "dataset-absent")["reason"]
        missing_reason = _cap(missing_score, "dataset-absent")["reason"]
        self.assertNotEqual(empty_reason, missing_reason)
        self.assertIn("does not exist", missing_reason)
        self.assertIn(missing.name, missing_reason)
        self.assertNotIn("does not exist", empty_reason)

    def test_a_described_dataset_with_no_row_count_is_not_called_absent(self) -> None:
        """Reachable from the public `--preflight -` surface, so pinned there.

        A provenance record with no `rows` count leaves `exists=True` and no
        usable rows: the same no-rows branch, entered from the other return.
        That return omitted the supplied fact, so a dataset preflight had just
        described was reported as one that never reached the score.
        """
        records = [
            {
                "check": "dataset-provenance",
                "status": "PASS",
                "detail": "described",
                # The provenance counts are emitted together by
                # preflight.py (one `emit` call), and #161 made an
                # absent one a refusal rather than a silent zero - so a
                # fixture that omits them is not a payload this script
                # can receive. Stated as real zeros, which is what the
                # described-but-empty dataset this test is about emits.
                "metrics": {
                    "labelled_rows": 0,
                    "synthetic": False,
                    "collected_rows": 0,
                    "synthesised_rows": 0,
                    "undeclared_rows": 0,
                    "generated_answer_rows": 0,
                    "answerable_rows": 0,
                },
            }
        ]
        process = subprocess.run(
            [sys.executable, str(READINESS), "--preflight", "-", "--json"],
            input=json.dumps(records),
            capture_output=True,
            text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        reason = _cap(json.loads(process.stdout), "dataset-absent")["reason"]
        self.assertIn("A dataset was provided to this score", reason)
        self.assertNotIn("No dataset was provided", reason)

    def test_unlabelled_rows_are_not_counted_as_unreadable(self) -> None:
        """`invalid_rows` is `malformed_rows + unlabelled_rows`, not either one.

        An unlabelled row was read. Counting it as unreadable would route a
        payload whose rows are all present-but-unlabelled to `repair-dataset`
        for rows that need labels, not repair. Preflight emits provenance for
        that shape today, so the divergence is unreachable through the pipeline
        - which is exactly why it is pinned here, on the payload the adapter
        actually reads, rather than left correct by a fact asserted elsewhere.
        """
        records = [
            {
                "check": "dataset-integrity",
                "status": "FAIL",
                "detail": "5/5 rows (100.0%) are unusable",
                "metrics": {
                    "invalid_rows": 5,
                    "malformed_rows": 0,
                    "unlabelled_rows": 5,
                    "candidate_rows": 5,
                },
            }
        ]
        process = _run_readiness(records)
        self.assertEqual(process.returncode, 0, process.stderr)
        conditions = {cap["condition"] for cap in json.loads(process.stdout)["caps"]}
        self.assertIn("dataset-absent", conditions)
        self.assertNotIn("dataset-shape-unrecognised", conditions)

    def test_a_payload_too_old_to_carry_malformed_rows_is_refused(self) -> None:
        """The refusal now covers the return that reads the same count.

        The guard sat below the no-provenance return, so a payload predating
        `malformed_rows` was refused when it described rows and silently scored
        as "no data at all" when it did not - the one place the missing count
        decides between broken data and no data.
        """
        records = [
            {
                "check": "dataset-integrity",
                "status": "FAIL",
                "detail": "3/3 rows (100.0%) are unusable",
                "metrics": {"invalid_rows": 3, "candidate_rows": 3},
            }
        ]
        process = _run_readiness(records)
        self.assertEqual(process.returncode, 2, process.stdout)
        self.assertIn("malformed_rows", process.stderr)

    def test_a_dataset_that_never_reached_the_score_is_reported_as_absent(self) -> None:
        """The other half, also end to end: preflight run with no --dataset.

        `_preflight_records` always passes `--dataset`, so this one drives
        preflight directly - the state under test is precisely its absence.
        """
        preflight = subprocess.run(
            [sys.executable, str(PREFLIGHT), "--defer-missing-sdk", "--json"],
            capture_output=True,
            text=True,
        )
        self.assertIn(preflight.returncode, (0, 1), preflight.stderr)
        records = json.loads(preflight.stdout)
        self.assertEqual(
            [r for r in records if str(r.get("check", "")).startswith("dataset-")],
            [],
            "preflight emitted a dataset check without a dataset",
        )
        process = subprocess.run(
            [sys.executable, str(READINESS), "--preflight", "-", "--json"],
            input=json.dumps(records),
            capture_output=True,
            text=True,
        )
        score = json.loads(process.stdout)

        caps = {cap["condition"]: cap for cap in score["caps"]}
        self.assertIn("dataset-absent", caps)
        reason = caps["dataset-absent"]["reason"]
        self.assertIn("provided to this score", reason)
        # Must not borrow the supplied-but-unreadable sentence.
        self.assertNotIn("A dataset was provided", reason)

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

    def test_a_holdout_nothing_can_score_is_said_rather_than_scored(self) -> None:
        """C5, re-decided: it is a real problem about a different question.

        50 labelled tuning rows against 50 unscoreable holdout rows used to
        collapse power to zero, on the reading that the two splits compare
        zero examples between them. They do not compare anything between them:
        the search compares configurations on the tuning rows, and the holdout
        checks the winner those rows picked. 50 tuning rows are 50 tuning rows.

        What is true is that nothing can check the winner, and that is stated
        on the card instead of expressed as a resolution number about a
        comparison it does not describe.
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
            self.assertEqual(power["value"], 22.0)
            self.assertIn("none of the held-back rows can be scored", power["evidence"])

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
            self.assertIn("25 scoreable", power["evidence"])

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

        Reporting "real inputs" about rows that never said where they came from
        would be the card asserting something it cannot know. They score as
        generated rows - 3, not the 6 a model-written answer over a collected
        question earns - because the question's origin is unknown too.
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
            self.assertEqual(subscore["value"], 3.0)
            self.assertIn("30 undeclared", subscore["evidence"])
            self.assertNotIn("collected", subscore["evidence"])
            self.assertIn(
                "dataset-undeclared-provenance",
                {cap["condition"] for cap in score["caps"]},
            )

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

    def test_an_unverifiable_declaration_does_not_outscore_a_verifiable_one(
        self,
    ) -> None:
        """A project's own vocabulary is said out loud AND is not credited.

        This used to assert the opposite half - that `crm-export` kept the full
        collected credit, so a word list could not demote a project using its
        own vocabulary. What that bought was that a lie outscored the truth.
        Measured on 200 identical rows with only the token varying: no token
        scored 65 and BLOCKED, the truthful `synthetic` scored 65 and BLOCKED,
        and `crm-export` AND `zzz` both scored 95 EXCELLENT. Three junk
        characters in a field nothing checks were worth thirty points.

        The rule is not "refuse unknown tokens" - that would demote the honest
        project the old reading was protecting. It is that an UNVERIFIABLE
        declaration must not outscore a VERIFIABLE one, so an unreadable token
        scores what a silent row scores: never above a row that declares itself
        generated. Nothing is refused, the tokens are named, the remedy is one
        relabel, and the disclosure prints the grade that relabel earns.
        """
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

            # Scored as undeclared, which is what an unreadable token is, and
            # never above a row that honestly declares itself generated.
            scored = _dataset_subscore(_score(dataset), "provenance")
            self.assertEqual(scored["value"], MODULE.UNDECLARED_ROW_POINTS)
            self.assertLessEqual(
                scored["value"],
                MODULE.SYNTHESISED_ROW_POINTS,
                "an unverifiable declaration outscored an honest one",
            )
            self.assertIn("could not verify", scored["evidence"])
            self.assertIn("crm-export", scored["evidence"])

            # And it is disclosed, not punished: the card names the tokens, the
            # remedy is a relabel, and the second grade is printed.
            payload = _score(dataset)
            self.assertIn(
                "dataset-undeclared-provenance",
                [cap["condition"] for cap in payload["caps"]],
            )
            assumption = payload["provenance_assumption"]
            self.assertIsNotNone(assumption)
            self.assertGreater(
                assumption["if_declared_collected"],
                assumption["scored_as_generated"],
                "the honest project is shown no way back to the score it lost",
            )

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

        # An ABSENT count is refused for the same reason, and this is the
        # direction that used to pass. There is no version skew to be
        # compatible with - nothing has been published - and reading a missing
        # count as 0 short-circuited the generated-answer-key ladder, so a
        # payload with `answerable_rows` deleted scored better than the real
        # one it was derived from.
        metrics.pop("synthesised_rows")
        refused_absent = subprocess.run(
            [sys.executable, str(READINESS), "--preflight", "-", "--json"],
            input=json.dumps(record),
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(refused_absent.returncode, 0)
        self.assertIn("synthesised_rows", refused_absent.stderr)

        # The false-red direction: a complete payload still scores.
        metrics.update(
            {
                "synthesised_rows": 0,
                "undeclared_rows": 0,
                "answerable_rows": 50,
                "generated_answer_rows": 0,
            }
        )
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


def _rows(count: int, provenance: str | None, *, offset: int = 0) -> list[dict]:
    """`count` otherwise identical rows, differing only in what they declare.

    `offset` keeps ids and inputs distinct when two blocks are concatenated
    into one mixed corpus; without it the halves collide and the run is capped
    for duplicate rows instead of for the thing under test.
    """
    rows = []
    for index in range(offset, offset + count):
        row = {
            "id": f"row-{index}",
            "input": f"customer message {index} token{index}",
            "output": f"answer {index % 5}",
        }
        if provenance is not None:
            row["metadata"] = {"provenance": provenance}
        rows.append(row)
    return rows


class UndeclaredProvenanceIsScoredAsGeneratedTests(unittest.TestCase):
    """Silence is an assumption, and the card makes it and states it.

    Measured before this changed, on 200 rows differing only in whether
    `provenance` was present: declared synthetic scored 65 and BLOCKED the paid
    run; the same rows with the field removed scored 91 and OK. Telling the
    truth cost twenty-six points and a block, which is a scoring rule that pays
    for silence. It is fixed by reading silence as the pessimistic case - and
    then by never letting the assumption be the part a customer finds out about
    after paying.
    """

    def _context(self, directory: Path) -> tuple[str, ...]:
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
            "normalized-exact",
            "--task-kind",
            "closed-label",
        )

    def _card(self, dataset: Path, extra: tuple[str, ...]) -> str:
        preflight_json = json.dumps(_preflight_records(dataset))
        process = subprocess.run(
            [
                sys.executable,
                str(READINESS),
                "--preflight",
                "-",
                "--color",
                "never",
                "--ascii",
                *extra,
            ],
            input=preflight_json,
            capture_output=True,
            text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        return process.stdout

    def test_declaring_synthetic_provenance_no_longer_costs_anything(self) -> None:
        """The defect itself: same rows, one declares, one does not."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            extra = self._context(directory)
            declared = _write_jsonl(
                directory, "declared.jsonl", _rows(200, "synthetic-walkthrough")
            )
            silent = _write_jsonl(directory, "silent.jsonl", _rows(200, None))

            declared_score = _score(declared, extra)
            silent_score = _score(silent, extra)

            self.assertEqual(declared_score["overall"], silent_score["overall"])
            self.assertEqual(declared_score["status"], silent_score["status"])
            self.assertEqual(silent_score["status"], "BLOCKED")
            # Same verdict, different instruction. Telling a customer to connect
            # real data is wrong when the data may already be real and merely
            # unlabelled, so the remedies deliberately do not match.
            self.assertEqual(declared_score["recommended_action"], "connect-real-data")
            self.assertEqual(
                silent_score["recommended_action"], "declare-data-provenance"
            )

    def test_the_card_states_the_assumption_and_both_grades(self) -> None:
        """The disclosure is on the card, and its second number is computed."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            extra = self._context(directory)
            silent = _write_jsonl(directory, "silent.jsonl", _rows(200, None))
            collected = _write_jsonl(
                directory, "collected.jsonl", _rows(200, "production")
            )

            score = _score(silent, extra)
            assumption = score["provenance_assumption"]
            self.assertEqual(assumption["undeclared_rows"], 200)
            self.assertEqual(assumption["scored_rows"], 200)
            self.assertEqual(assumption["scored_as_generated"], score["overall"])
            # Not a hand-written figure: the same rows, declared as collected,
            # really do score this. A quoted alternative a customer is invited
            # to act on has to be the one they would actually get.
            self.assertEqual(
                assumption["if_declared_collected"],
                _score(collected, extra)["overall"],
            )
            self.assertGreater(
                assumption["if_declared_collected"], assumption["scored_as_generated"]
            )

            card = self._card(silent, extra)
            self.assertIn("ASSUMED GENERATED", card)
            self.assertIn(f"{assumption['scored_as_generated']}/100", card)
            self.assertIn(f"{assumption['if_declared_collected']}/100", card)

    def test_a_declared_corpus_carries_no_assumption_to_disclose(self) -> None:
        """No silent row, no assumption - and therefore no line about one."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            extra = self._context(directory)
            collected = _write_jsonl(
                directory, "collected.jsonl", _rows(200, "production")
            )
            self.assertIsNone(_score(collected, extra)["provenance_assumption"])
            self.assertNotIn("ASSUMED GENERATED", self._card(collected, extra))

    def test_a_half_undeclared_corpus_is_answered_rather_than_ignored(self) -> None:
        """The partial cases, both of them, with the rule stated once.

        The ladder runs on how much was never observed, so which half the
        silent rows are mixed with decides the answer:

        * half collected, half silent is 50% - under the threshold, so it is
          capped by neither rung and simply loses points per row;
        * half generated, half silent is 100% unobserved and IS capped, at 65,
          even though neither half reaches 100% on its own.

        Both still disclose the assumption, because both made one.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            extra = self._context(directory)
            with_real = _write_jsonl(
                directory,
                "half-real.jsonl",
                _rows(100, "production") + _rows(100, None, offset=100),
            )
            with_generated = _write_jsonl(
                directory,
                "half-generated.jsonl",
                _rows(100, "synthetic-walkthrough") + _rows(100, None, offset=100),
            )

            mixed_real = _score(with_real, extra)
            self.assertEqual(
                [cap["condition"] for cap in mixed_real["caps"]],
                [],
                "half a corpus saying nothing is not a majority",
            )
            self.assertEqual(mixed_real["status"], "OK")
            self.assertEqual(_dataset_subscore(mixed_real, "provenance")["value"], 6.5)
            self.assertEqual(
                mixed_real["provenance_assumption"]["undeclared_rows"], 100
            )

            mixed_generated = _score(with_generated, extra)
            capped = next(
                cap
                for cap in mixed_generated["caps"]
                if cap["condition"] == "dataset-undeclared-provenance"
            )
            self.assertEqual(capped["ceiling"], 65)
            self.assertEqual(capped["action_kind"], "declare-data-provenance")
            # The silent half is what the customer can act on today, so the
            # sentence names its share rather than claiming the whole corpus.
            self.assertIn(
                "100 of 200 rows record no source this run can read",
                self._card(with_generated, extra),
            )

    def test_a_mostly_undeclared_corpus_reaches_the_lower_rung(self) -> None:
        """Above half, under all: the 70 ceiling, with the same remedy."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            extra = self._context(directory)
            dataset = _write_jsonl(
                directory,
                "mostly-silent.jsonl",
                _rows(120, None) + _rows(80, "production", offset=120),
            )
            score = _score(dataset, extra)
            cap = next(
                cap
                for cap in score["caps"]
                if cap["condition"] == "dataset-mostly-undeclared"
            )
            self.assertEqual(cap["ceiling"], 70)
            self.assertEqual(cap["action_kind"], "declare-data-provenance")

    def test_preflight_no_longer_passes_a_dataset_that_declared_nothing(self) -> None:
        """`unknown` used to PASS, which read as "checked, and fine"."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            silent = _write_jsonl(directory, "silent.jsonl", _rows(200, None))
            record = next(
                record
                for record in _preflight_records(silent)
                if record["check"] == "dataset-provenance"
            )
            self.assertEqual(record["status"], "WARN")
            self.assertIn("scored as generated", record["detail"])

            collected = _write_jsonl(
                directory, "collected.jsonl", _rows(200, "production")
            )
            passing = next(
                record
                for record in _preflight_records(collected)
                if record["check"] == "dataset-provenance"
            )
            self.assertEqual(passing["status"], "PASS")

    def test_a_silent_minority_does_not_take_the_remedy_from_a_generated_majority(
        self,
    ) -> None:
        """50 collected / 260 declared generated / 90 silent - who owns the ceiling.

        The shape the other cases here do not have: 100/100 and 120/80 both put
        silence at or above half the unobserved mass, so the minority case was
        untested and a bare `undeclared_rows > 0` passed every one of them.

        Measured end to end on this corpus before the share test: the reader was
        told to declare the rows that were collected, declared all 90, scored
        the identical 70, stayed BLOCKED, and only then received
        `connect-real-data` - the instruction they needed first. That is the
        wrong-remedy harm the undeclared conditions exist to prevent, handed out
        by the fix for it. So the decision under test is which remedy this
        corpus gets, and the declared-generated majority is what decides it.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            extra = self._context(directory)
            silent_minority = _rows(50, "production") + _rows(
                260, "synthetic-walkthrough", offset=50
            )
            before = _write_jsonl(
                directory,
                "silent-minority.jsonl",
                silent_minority + _rows(90, None, offset=310),
            )
            complied = _write_jsonl(
                directory,
                "declared.jsonl",
                silent_minority + _rows(90, "production", offset=310),
            )

            score = _score(before, extra)
            self.assertEqual(score["recommended_action"], "connect-real-data")
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertIn("dataset-mostly-synthetic", conditions)
            self.assertNotIn("dataset-mostly-undeclared", conditions)
            self.assertNotIn("dataset-undeclared-provenance", conditions)

            # Why that is the right remedy and the other one was not: doing what
            # `declare-data-provenance` asks moves nothing here, because the 260
            # declared generated rows hold the ceiling down by themselves.
            self.assertEqual(_score(complied, extra)["overall"], score["overall"])
            self.assertEqual(_score(complied, extra)["status"], score["status"])

            # Nothing about the 90 is hidden by routing the remedy elsewhere.
            self.assertIn(
                "90 undeclared", _dataset_subscore(score, "provenance")["evidence"]
            )

    def test_two_equal_grades_are_not_offered_as_a_choice(self) -> None:
        """A disclosure that repeats the score is noise where it costs most.

        The sentence exists to say the headline rests on an assumption and to
        carry the number the reader would get instead. When the two numbers are
        equal there is no number instead - "scores 70/100 ... the same evidence
        scores 70/100" spends the reader's attention, at the moment they are
        deciding whether to pay, to tell them nothing changes.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            extra = self._context(directory)
            dataset = _write_jsonl(
                directory,
                "silent-minority.jsonl",
                _rows(50, "production")
                + _rows(260, "synthetic-walkthrough", offset=50)
                + _rows(90, None, offset=310),
            )
            score = _score(dataset, extra)
            self.assertIsNone(score["provenance_assumption"])
            self.assertNotIn("ASSUMED GENERATED", self._card(dataset, extra))
            # Still stated where it is a fact rather than a choice.
            self.assertIn(
                "scores it as generated",
                _dataset_subscore(score, "provenance")["evidence"],
            )

    def test_a_payload_carrying_no_row_counts_is_read_as_saying_nothing(
        self,
    ) -> None:
        """The count-free payload, with forty lines of machinery removed.

        `emit_dataset_provenance` emits the collected, generated and undeclared
        counts together for every dataset with a row in it, so a payload
        carrying none of them is truncated rather than old - nothing has been
        published for it to be older than. It used to be handled by a second
        implementation of the whole provenance ladder that re-derived it from
        `sources`, with its own helper, its own counterfactual token and its
        own branch in the disclosure.

        All of that is one fail-closed reading now: no per-row count is no
        statement about any row, which is what a silent row is. `sources` no
        longer decides anything here, which is the point - the token list is
        what an unverifiable declaration used to be scored from.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            extra = self._context(directory)
            records = [
                {
                    "check": "dataset-provenance",
                    "status": "WARN",
                    "detail": "no row records a provenance",
                    "metrics": {
                        "rows": 200,
                        "labelled_rows": 200,
                        "synthetic": False,
                        "sources": ["unknown"],
                    },
                },
                {
                    "check": "dataset-split",
                    "status": "PASS",
                    "detail": "tuning and holdout inputs are disjoint",
                    "metrics": {},
                },
                {
                    "check": "dataset-tuning-size",
                    "status": "PASS",
                    "detail": "100 tuning rows",
                    "metrics": {"tuning_rows": 100, "tuning_labelled_rows": 100},
                },
                {
                    "check": "dataset-holdout-resolution",
                    "status": "PASS",
                    "detail": "100 holdout rows",
                    "metrics": {"holdout_rows": 100, "holdout_labelled_rows": 100},
                },
            ]
            score = _score_records(records, extra)
            self.assertEqual(score["recommended_action"], "declare-data-provenance")
            self.assertEqual(score["status"], "BLOCKED")

            assumption = score["provenance_assumption"]
            self.assertIsNotNone(assumption)
            self.assertEqual(assumption["undeclared_rows"], 200)
            self.assertEqual(assumption["scored_rows"], 200)
            self.assertEqual(assumption["scored_as_generated"], score["overall"])
            self.assertGreater(
                assumption["if_declared_collected"], assumption["scored_as_generated"]
            )
            # Computed from the same payload with the rows actually counted as
            # collected, not by writing a word into `sources` - which no longer
            # moves anything, and is exactly the machinery that came out.
            declared = [dict(record) for record in records]
            declared[0]["metrics"] = dict(
                declared[0]["metrics"],
                collected_rows=200,
                synthesised_rows=0,
                undeclared_rows=0,
                answerable_rows=200,
                generated_answer_rows=0,
            )
            self.assertEqual(
                assumption["if_declared_collected"],
                _score_records(declared, extra)["overall"],
            )
            # And the token list on its own buys nothing: declaring
            # `sources: ["collected"]` with no counts behind it is an
            # unverifiable declaration and scores where silence scores.
            worded = [dict(record) for record in records]
            worded[0]["metrics"] = dict(
                worded[0]["metrics"], sources=["collected"]
            )
            self.assertEqual(
                _score_records(worded, extra)["overall"],
                score["overall"],
            )

            card = _card_records(records, extra)
            self.assertIn("ASSUMED GENERATED", card)
            self.assertIn(f"{assumption['scored_as_generated']}/100", card)
            self.assertIn(f"{assumption['if_declared_collected']}/100", card)


if __name__ == "__main__":
    unittest.main()

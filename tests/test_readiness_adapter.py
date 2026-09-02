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

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "traigent-first-run" / "scripts"
PREFLIGHT = SCRIPTS / "preflight.py"
READINESS = SCRIPTS / "readiness.py"
# Imported so a points assertion can name the constant it is about rather than
# restating its value beside it.
# Imported so an assertion about the similarity line can name the constant that
# decides it rather than restating the number beside it - a literal here is the
# fourth home the shared-value guard exists to prevent.
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
                "detail": "tuning and held-out inputs are disjoint",
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
                "detail": "50 held-out rows; one example changes the score by 2.0 "
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
            "detail": "tuning-only dataset; no held-out split was declared",
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
    ],
    "passed": True,
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
        self.assertIn("18 tuning rows and no held-out set", power["evidence"])
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
        self.assertIn("18 tuning rows and no held-out set", power["evidence"])
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
            # `source` is stated because #165 scores a row that declares none
            # as generated, and this test's claim is that a correct re-map
            # leaves NO dataset finding. Without it the file would carry a
            # provenance cap that has nothing to do with the shape - a true
            # finding about a different fact, which would make the assertion
            # below untestable rather than wrong.
            {
                "id": str(index),
                "question": f"q{index}",
                "answer": f"a{index % 4}",
                "source": "production",
            }
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
            # Both runs name the agent, so the remedy this test reads is the
            # DATASET's. An undeclared agent blocks at a lower ceiling and its
            # own remedy would win `recommended_action` on both sides, which
            # would hide the very discontinuity being asserted.
            named_agent = ("--agent-origin", "brought")
            partial_score = _score(partial, extra=named_agent)
            everything_score = _score(everything, extra=named_agent)

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
            # "held-out", not "held-back": `THIRD_NOUNS` in test_skill_package
            # bans the prose form "held-back" from every bundled script, and
            # names this very evidence line as the defect that produced the
            # ban. The guarantee here is unchanged - an unscoreable holdout is
            # SAID on the card - only the settled name for the split is.
            self.assertIn("none of the held-out rows can be scored", power["evidence"])

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
                "detail": "50 held-out rows; one example changes the score by 2.0 "
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
            self.assertIn("no tuning set and held-out set", power["evidence"])
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
            self.assertIn("no tuning set and held-out set", power["evidence"])

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
            #
            # The agent is named for the counterfactual's sake: the second grade
            # is only printable while relabelling would MOVE the card, and an
            # undeclared agent holds both readings at one ceiling, so the
            # disclosure would correctly report nothing to show.
            payload = _score(dataset, extra=("--agent-origin", "brought"))
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
        record = [
            {"check": "dataset-provenance", "status": "PASS", "metrics": metrics},
            {"check": "dataset-split", "status": "WARN", "metrics": {}},
            {"check": "dataset-ids", "status": "PASS", "metrics": {}},
        ]
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

    def test_a_reference_free_run_never_claims_an_answer_spread_it_has_no_use_for(
        self,
    ) -> None:
        """End to end: the card must not speak about expected outputs at all.

        A reference-free judge does not use expected outputs, so preflight
        skips the whole expected-output branch - and answer dominance is
        computed inside it. `dataset-ceiling-risk` was therefore absent for the
        same reason it is absent from a healthy dataset, and readiness read
        that absence as "checked, nothing found": the card printed "no single
        answer used by most rows" about a dataset where 95% of the answers were
        identical and nothing had looked.

        Reading it as "did not run" fixed the false claim and bought a false
        red: the near-duplicate check DID run and pass, and its result was
        discarded with it, so a 40-row input-only dataset dropped from DATASET
        81/100 (3 of 5 checks) to 70/100 (2 of 5) on a configuration the guide
        fully supports. The answer is neither: a question with no subject does
        not apply, so it is not scored, not named as unrun, and not spoken
        about - and the check beside it keeps the answer it earned.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index} distinct{index}",
                    "output": "yes" if index < 57 else f"no-{index}",
                    "metadata": {"provenance": "production"},
                }
                for index in range(60)
            ]
            dataset = _write_jsonl(directory, "dominant.jsonl", rows)

            reference_free = _score(
                dataset,
                extra=("--evaluator-method", "llm-judge-pointwise"),
                preflight_extra=("--evaluator-method", "llm-judge-pointwise"),
            )
            statuses = {
                record["check"]: record["status"]
                for record in _preflight_records(
                    dataset, "--evaluator-method", "llm-judge-pointwise"
                )
            }
            self.assertEqual(statuses["dataset-outputs"], "SKIP")
            self.assertNotIn("dataset-ceiling-risk", statuses)

            diversity = next(
                sub
                for pillar in reference_free["pillars"]
                if pillar["name"] == "dataset"
                for sub in pillar["subscores"]
                if sub["name"] == "diversity"
            )
            # Measured, because the question that applies was asked and
            # answered - and silent about the one that does not.
            self.assertTrue(diversity["measured"], diversity["evidence"])
            self.assertNotIn("no single answer", diversity["evidence"])
            self.assertNotIn("expected output", diversity["evidence"])
            self.assertNotIn("not checked", diversity["evidence"])
            self.assertEqual(diversity["value"], diversity["maximum"])

            # The same dataset under a reference-requiring evaluator DOES run
            # the check, and must still report the dominance it finds.
            measured = _score(dataset)
            diversity = next(
                sub
                for pillar in measured["pillars"]
                if pillar["name"] == "dataset"
                for sub in pillar["subscores"]
                if sub["name"] == "diversity"
            )
            self.assertTrue(diversity["measured"])
            self.assertIn("one expected output dominates", diversity["evidence"])

    def test_free_text_answers_reach_the_card_as_unasked_not_as_clean(self) -> None:
        """#216, end to end: preflight declines, and the card says it declined.

        Dominance is measured against a chance baseline of `1 / k`, which is a
        baseline only when the `k` answers seen ARE the answer space. On a
        free-text task they are a sample of an open-ended one - `k` grows with
        the row count - so the check does not run.

        That is a legitimate answer and a dangerous one: the whole point of
        #158 is that a check which did not run must never read as a check that
        passed. So preflight emits `dataset-ceiling-risk` as SKIP rather than
        staying silent, because silence here is indistinguishable from a clean
        dataset - `dataset-outputs` is a PASS either way, and readiness reads
        that PASS as its witness that the spread was examined.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index} distinct{index}",
                    "output": (
                        "a shared sentence answer"
                        if index < 2
                        else f"a distinct sentence answer number {index}"
                    ),
                    "metadata": {"provenance": "production"},
                }
                for index in range(66)
            ]
            dataset = _write_jsonl(directory, "free-text.jsonl", rows)
            statuses = {r["check"]: r["status"] for r in _preflight_records(dataset)}
            # PASS on the record readiness would otherwise take as its witness,
            # which is exactly why the SKIP has to be emitted rather than left
            # implicit in an absent record.
            self.assertEqual(statuses["dataset-outputs"], "PASS")
            self.assertEqual(statuses["dataset-ceiling-risk"], "SKIP")

            diversity = next(
                sub
                for pillar in _score(dataset)["pillars"]
                if pillar["name"] == "dataset"
                for sub in pillar["subscores"]
                if sub["name"] == "diversity"
            )
            self.assertFalse(diversity["measured"], diversity["evidence"])
            self.assertIn("not checked", diversity["evidence"])
            self.assertIn("dominates", diversity["evidence"])

    def test_a_large_dataset_is_still_checked_for_near_duplicates(self) -> None:
        """The readiness half of the 500-row skip: no silent clean bill.

        Above 500 rows preflight emitted SKIP, and the diversity sub-score's
        `in ("FAIL", "WARN")` test let it through with full points - so the
        card said "no repeated questions" about rows nothing had compared.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = [
                {
                    "id": f"row-{index}",
                    "input": f"question {index} token{index} distinct{index} alpha",
                    "output": f"answer {index % 6}",
                    "metadata": {"provenance": "production"},
                }
                for index in range(700)
            ]
            rows[0]["input"] = "one two three four five six seven eight nine ten"
            rows[1]["input"] = "one two three four five six seven eight nine"
            dataset = _write_jsonl(directory, "big.jsonl", rows)
            statuses = {
                record["check"]: record["status"]
                for record in _preflight_records(dataset)
            }
            self.assertEqual(statuses["dataset-near-duplicates"], "WARN")

            diversity = next(
                sub
                for pillar in _score(dataset)["pillars"]
                if pillar["name"] == "dataset"
                for sub in pillar["subscores"]
                if sub["name"] == "diversity"
            )
            self.assertTrue(diversity["measured"])
            self.assertIn(
                f"{MODULE.NEAR_DUPLICATE_PERCENT}% similar", diversity["evidence"]
            )

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
                    ],
                    "passed": False,
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

    def test_incomplete_calibration_earns_no_behavioral_credit(self) -> None:
        """A verdict with no measurement behind it earns no behavioral credit.

        The third payload this used to sweep --
        `{"cases": [{"checks": {"good_passes": true}}], "passed": false}` -- was
        moved to `test_a_reported_failure_over_a_partial_table_convicts`. It is
        the one case here where the calibrator DID measure something and then
        reported failure, and pinning it to `evaluator-unvalidated` was pinning
        a run that spends money on an evaluator its own calibrator failed.
        These two remain: no cases at all, and a case whose check table is
        empty. Both are a verdict with nothing behind it.
        """
        with tempfile.TemporaryDirectory() as directory:
            evaluator = Path(directory) / "evaluator.py"
            evaluator.write_text(
                "def score(output, expected):\n"
                "    return 1.0 if output == expected else 0.0\n"
            )
            for payload in (
                {"cases": [], "passed": False},
                {"cases": [{"checks": {}}], "passed": False},
            ):
                with self.subTest(payload=payload):
                    calibration = Path(directory) / "calibration.json"
                    calibration.write_text(json.dumps(payload))
                    score = _score_evaluator(
                        evaluator,
                        (
                            "--evaluator-method",
                            "exact",
                            "--calibration",
                            str(calibration),
                        ),
                    )
                    caps = _evaluation_caps(score)
                    self.assertIn("evaluator-unvalidated", caps)
                    self.assertNotIn("evaluator-invalid", caps)
                    unvalidated = _cap(score, "evaluator-unvalidated")
                    self.assertEqual(
                        unvalidated["ceiling"],
                        MODULE.EVALUATOR_UNVALIDATED_CEILING,
                    )
                    self.assertFalse(unvalidated["blocks"])
                    self.assertEqual(unvalidated["action_kind"], "proceed")
                    evaluation = next(
                        pillar
                        for pillar in score["pillars"]
                        if pillar["name"] == "evaluation"
                    )
                    calibration_score = next(
                        subscore
                        for subscore in evaluation["subscores"]
                        if subscore["name"] == "calibration"
                    )
                    self.assertFalse(calibration_score["measured"])
                    self.assertTrue(calibration_score["withheld"])
                    self.assertEqual(calibration_score["value"], 0.0)

    def test_a_reported_failure_over_a_partial_table_convicts(self) -> None:
        """The calibrator ran this evaluator and said it failed.

        A truncated check table is a reason to trust that verdict more, not a
        reason to spend money. This payload routed to `evaluator-unvalidated`
        (45, proceed) until the completeness rule read the verdict as evidence
        in its own right, while the same payload with a complete table
        convicted at 25 -- and the comment governing that code had promised
        both routes convict since before either was written.
        """
        with tempfile.TemporaryDirectory() as directory:
            evaluator = Path(directory) / "evaluator.py"
            evaluator.write_text(
                "def score(output, expected):\n"
                "    return 1.0 if output == expected else 0.0\n"
            )
            for payload in (
                {"cases": [{"checks": {"good_passes": True}}], "passed": False},
                {
                    "cases": [{"checks": {"good_passes": True, "bad_fails": True}}],
                    "passed": False,
                },
            ):
                with self.subTest(payload=payload):
                    calibration = Path(directory) / "calibration.json"
                    calibration.write_text(json.dumps(payload))
                    score = _score_evaluator(
                        evaluator,
                        (
                            "--evaluator-method",
                            "exact",
                            "--calibration",
                            str(calibration),
                        ),
                    )
                    caps = _evaluation_caps(score)
                    self.assertIn("evaluator-invalid", caps)
                    self.assertNotIn("evaluator-unvalidated", caps)
                    invalid = _cap(score, "evaluator-invalid")
                    self.assertEqual(
                        invalid["ceiling"],
                        MODULE.EVALUATOR_INVALID_CEILING,
                    )
                    self.assertTrue(invalid["blocks"])
                    self.assertEqual(invalid["action_kind"], "repair-evaluator")
                    evaluation = next(
                        pillar
                        for pillar in score["pillars"]
                        if pillar["name"] == "evaluation"
                    )
                    calibration_score = next(
                        subscore
                        for subscore in evaluation["subscores"]
                        if subscore["name"] == "calibration"
                    )
                    self.assertTrue(calibration_score["measured"])
                    self.assertFalse(calibration_score["withheld"])
                    self.assertEqual(calibration_score["value"], 0.0)

    def test_calibration_that_rejects_a_known_good_answer_is_invalid(self) -> None:
        """A complete failed check is a broken evaluator, not missing evidence."""
        with tempfile.TemporaryDirectory() as directory:
            evaluator = Path(directory) / "evaluator.py"
            evaluator.write_text(
                "def score(output, expected):\n"
                "    return 1.0 if output == expected else 0.0\n"
            )
            calibration = Path(directory) / "calibration.json"
            calibration.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "checks": {
                                    "good_passes": False,
                                    "bad_fails": True,
                                    "non_constant": True,
                                }
                            }
                        ],
                        "passed": False,
                    }
                )
            )
            score = _score_evaluator(
                evaluator,
                (
                    "--evaluator-method",
                    "exact",
                    "--calibration",
                    str(calibration),
                ),
            )
        caps = _evaluation_caps(score)
        self.assertIn("evaluator-invalid", caps)
        self.assertNotIn("evaluator-unvalidated", caps)

    def test_any_complete_authored_calibration_failure_is_invalid(self) -> None:
        """Partial and equivalent probes are verdict checks, not decoration."""
        for failed_check in ("partial_fails", "equivalent_is_accepted"):
            with self.subTest(
                failed_check=failed_check
            ), tempfile.TemporaryDirectory() as directory:
                evaluator = Path(directory) / "evaluator.py"
                evaluator.write_text(
                    "def score(output, expected):\n"
                    "    return 1.0 if output == expected else 0.0\n"
                )
                checks = {
                    "good_passes": True,
                    "bad_fails": True,
                    "non_constant": True,
                    "partial_fails": True,
                    "equivalent_is_accepted": True,
                }
                checks[failed_check] = False
                calibration = Path(directory) / "calibration.json"
                calibration.write_text(
                    json.dumps(
                        {
                            "cases": [{"checks": checks}],
                            "passed": False,
                        }
                    )
                )
                score = _score_evaluator(
                    evaluator,
                    (
                        "--evaluator-method",
                        "exact",
                        "--calibration",
                        str(calibration),
                    ),
                )

            caps = _evaluation_caps(score)
            self.assertIn("evaluator-invalid", caps)
            self.assertNotIn("evaluator-unvalidated", caps)
            self.assertLessEqual(score["overall"], MODULE.EVALUATOR_INVALID_CEILING)

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
                    ],
                    "passed": True,
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

            # OWNER DECISION RECORDED HERE, and revised twice. #165 wrote it as
            # three assertions: equal overall, equal status, and both BLOCKED.
            # #149 then decided that a generated dataset may not stop the run at
            # all - the guide WRITES the walkthrough dataset for a user who has
            # none, and blocking it made the guide demand real data from the one
            # user who by construction has none. That left silence BLOCKED and
            # declared-generated OK.
            #
            # #211 measured what that cost and the owner settled it: the two
            # agree on the run/wait axis as well. Silence is not a defect - the
            # rows parse, the answers are there, and the only thing absent is a
            # word saying who wrote them - so it bounds the claim exactly as its
            # declared twin does. Blocking it punished a project whose real rows
            # carry a vocabulary this script does not know more harshly than a
            # project that declared its whole corpus generated.
            #
            # #165's purpose survives intact, and this is where it is asserted:
            # silence may never be cheaper than declaring. The SCORE is
            # identical, which is the number the defect was about, and silence
            # still costs strictly more - it carries a question its declared
            # twin has already answered, so `recommended_action` names a remedy
            # where declaring names none.
            self.assertEqual(declared_score["overall"], silent_score["overall"])
            self.assertEqual(declared_score["status"], "OK")
            self.assertEqual(silent_score["status"], "OK")
            # Same ceiling, different instruction. Telling a customer to connect
            # real data is wrong when the data may already be real and merely
            # unlabelled, so the remedies deliberately do not match.
            self.assertEqual(declared_score["recommended_action"], "proceed")
            self.assertEqual(
                silent_score["recommended_action"], "declare-data-provenance"
            )
            # And that remedy reaches the reader through the asking tier rather
            # than through a stop, which is the whole of what #211 changed.
            silent_cap = next(
                cap
                for cap in silent_score["caps"]
                if cap["condition"] == "dataset-undeclared-provenance"
            )
            declared_cap = next(
                cap
                for cap in declared_score["caps"]
                if cap["condition"] == "dataset-fully-synthetic"
            )
            self.assertEqual(silent_cap["ceiling"], declared_cap["ceiling"])
            self.assertFalse(silent_cap["blocks"])
            self.assertTrue(silent_cap["asks"])
            self.assertFalse(declared_cap["asks"])

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
            # The decision under test is WHICH condition owns this corpus, and
            # the three assertions below are it. `recommended_action` was #165's
            # proxy for that and #149 took it away: an advisory cap does not set
            # the recommendation at all, so a corpus whose only cap scopes the
            # claim recommends `proceed` whatever the condition is called. The
            # remedy is still carried per cap in `action_kind`, which is where
            # this now reads it.
            self.assertEqual(score["recommended_action"], "proceed")
            conditions = {cap["condition"] for cap in score["caps"]}
            self.assertEqual(
                {cap["action_kind"] for cap in score["caps"]},
                {"connect-real-data"},
            )
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
                    # The counts are stated rather than omitted. #161 made an
                    # absent count a refusal (exit 2) instead of a silent zero,
                    # because an absent `answerable_rows` short-circuited the
                    # whole answer-key ladder and made silence the
                    # highest-scoring input. preflight.py emits all of these in
                    # one `emit` call, so a payload without them is not one this
                    # script can receive - and what this test is about, a corpus
                    # where no row declares a source, is exactly
                    # `undeclared_rows: 200`.
                    "metrics": {
                        "rows": 200,
                        "labelled_rows": 200,
                        "synthetic": False,
                        "sources": ["unknown"],
                        "collected_rows": 0,
                        "synthesised_rows": 0,
                        "undeclared_rows": 200,
                        "generated_answer_rows": 0,
                        "answerable_rows": 200,
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
            # OK, not BLOCKED, since #211: the remedy reaches the reader through
            # the asking tier. The assertion this test is actually about is the
            # line above - a payload that states no source still routes to
            # `declare-data-provenance` rather than to silence - and that is the
            # half `asks` preserves where `blocks` used to carry it.
            self.assertEqual(score["status"], "OK")

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
            worded[0]["metrics"] = dict(worded[0]["metrics"], sources=["collected"])
            self.assertEqual(
                _score_records(worded, extra)["overall"],
                score["overall"],
            )

            card = _card_records(records, extra)
            self.assertIn("ASSUMED GENERATED", card)
            self.assertIn(f"{assumption['scored_as_generated']}/100", card)
            self.assertIn(f"{assumption['if_declared_collected']}/100", card)


class RowReviewPipelineTests(unittest.TestCase):
    """The row-level sanity check driven through the real two-script pipeline.

    Hand-built facts cannot show the point of this check, which is that every
    other dataset check passes on the broken row. These drive the real
    `preflight.py --json | readiness.py --preflight -` path over a dataset whose
    only defect is that three expected answers contradict their own inputs.
    """

    # Twenty distinct support tickets rather than one sentence with a number
    # swapped, because a template makes every row a near-duplicate of every
    # other and the duplicate checks would then be the thing that fired.
    CASES = (
        (
            "Bought a standing desk on 2 March, asked for a refund on 9 March; "
            "the plan allows 30 days.",
            "approve",
        ),
        (
            "Ordered noise-cancelling headphones, opened them, and requested a "
            "return 41 days later against a 30-day window.",
            "deny",
        ),
        (
            "A subscriber cancelled mid-term after 3 days and wants the annual "
            "fee back; annual plans refund within 14 days.",
            "approve",
        ),
        (
            "Espresso machine arrived damaged; the buyer reported it the same "
            "afternoon and the damage policy has no time limit.",
            "approve",
        ),
        (
            "Mechanical keyboard bought in January, refund asked for in June, "
            "policy window 30 days.",
            "deny",
        ),
        (
            "Running watch returned on day 30 of a 30-day window, unworn and boxed.",
            "approve",
        ),
        (
            "Office chair assembled and used for four months; the buyer now "
            "dislikes the colour. Window is 30 days.",
            "deny",
        ),
        (
            "Monitor arm shipped to the wrong address by us; buyer asks for a "
            "refund on day 52.",
            "approve",
        ),
        (
            "Label printer bought under a 60-day trial, returned on day 58 with "
            "all accessories.",
            "approve",
        ),
        (
            "Projector lamp failed after 14 months; warranty covers 12 and the "
            "refund window closed long ago.",
            "deny",
        ),
        (
            "Docking station never delivered; the carrier confirmed the loss and "
            "the buyer wants their money back.",
            "approve",
        ),
        (
            "Gift card purchased two years ago; the buyer asks for cash back. "
            "Gift cards are non-refundable.",
            "deny",
        ),
        (
            "Laptop sleeve ordered twice by mistake; the duplicate is unopened "
            "and was flagged on day 2.",
            "approve",
        ),
        (
            "Software licence activated and used for a full quarter, refund "
            "requested at renewal. Activated licences are final.",
            "deny",
        ),
        (
            "Webcam returned on day 12 of a 14-day window, in original packaging.",
            "approve",
        ),
        (
            "Conference ticket for an event that already took place; the buyer "
            "did not attend and asks for a refund.",
            "deny",
        ),
        (
            "Ergonomic mouse developed a stuck button in week 3; the plan "
            "refunds faults inside 90 days.",
            "approve",
        ),
        (
            "Custom-engraved pen returned after 5 days; personalised goods are "
            "excluded from the refund policy.",
            "deny",
        ),
        (
            "Tablet stand refunded request filed on day 9 against a 30-day "
            "window, item unused.",
            "approve",
        ),
        (
            "Annual membership used for eleven months, refund asked for in the "
            "final week. Used memberships are not refundable.",
            "deny",
        ),
    )

    # The one wrong shape, applied to whichever rows the test names: the
    # request is plainly outside the stated window and the expected answer
    # approves it anyway. Well-formed, unique, tagged, perfectly scoreable.
    WRONG_INPUT = (
        "Refund requested {days} days after purchase for the {item}; the "
        "policy window is 30 days."
    )

    @classmethod
    def _rows(cls, wrong: tuple[str, ...] = ()) -> list[dict]:
        rows = []
        for index, (text, answer) in enumerate(cls.CASES):
            identifier = f"row-{index}"
            if identifier in wrong:
                text = cls.WRONG_INPUT.format(
                    days=45 + index, item=f"order {1000 + index}"
                )
                answer = "approve"
            rows.append(
                {
                    "id": identifier,
                    "input": text,
                    "output": answer,
                    "split": "tuning" if index < 12 else "holdout",
                    "difficulty": ("easy", "medium", "hard", "very-hard")[index % 4],
                    "provenance": "customer-support-export",
                }
            )
        return rows

    @staticmethod
    def _review(rows: list[dict], wrong: tuple[str, ...] = ()) -> dict:
        return {
            "reviewer": "assistant",
            "rows": [
                {
                    "id": row["id"],
                    "origin": "collected",
                    "verdict": "no" if row["id"] in wrong else "yes",
                    "note": (
                        "45 days against a 30-day window cannot be 'approve'"
                        if row["id"] in wrong
                        else "the day count sits inside the stated window"
                    ),
                }
                for row in rows
            ],
        }

    def _score(self, directory: Path, rows: list[dict], review: dict | None) -> dict:
        dataset = _write_jsonl(directory, "dataset.jsonl", rows)
        extra: tuple[str, ...] = ()
        if review is not None:
            review_path = directory / "row-review.json"
            review_path.write_text(json.dumps(review))
            extra = ("--row-review", str(review_path))
        return _score(
            dataset,
            extra=("--evaluator-method", "normalized-exact", *extra),
            preflight_extra=("--evaluator-method", "normalized-exact"),
        )

    def test_every_column_wise_check_passes_on_the_broken_dataset(self) -> None:
        """The gap this closes: nothing else looks at the two fields together."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            sound = _preflight_records(
                _write_jsonl(directory, "sound.jsonl", self._rows())
            )
            broken = _preflight_records(
                _write_jsonl(
                    directory, "broken.jsonl", self._rows(("row-1", "row-5", "row-13"))
                )
            )
        statuses = {
            record["check"]: record["status"]
            for record in sound
            if record["check"].startswith("dataset-")
        }
        self.assertEqual(
            statuses,
            {
                record["check"]: record["status"]
                for record in broken
                if record["check"].startswith("dataset-")
            },
        )
        self.assertNotIn("FAIL", statuses.values())
        # Neither of the two non-PASS checks is a finding about these rows.
        # One is about how many were held back, which both files share; the
        # other could not run - every one of these twenty scenarios opens with
        # its own words, so no input form recurs for `dataset-split-family` to
        # read the split against, and it SKIPs rather than reporting a clean
        # split it never established. Nothing here reads a row's answer against
        # its own question, which is why the broken file is invisible to all
        # of it.
        self.assertEqual(
            {check for check, status in statuses.items() if status != "PASS"},
            {"dataset-holdout-resolution", "dataset-split-family"},
        )
        self.assertEqual(statuses["dataset-split-family"], "SKIP")

    def test_a_clean_pipeline_run_scores_identically_with_and_without_a_review(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = self._rows()
            unreviewed = self._score(directory, rows, None)
            reviewed = self._score(directory, rows, self._review(rows))
        for field in ("overall", "weighted_average", "band", "status", "caps"):
            with self.subTest(field=field):
                self.assertEqual(reviewed[field], unreviewed[field])
        self.assertEqual(
            reviewed["recommended_action"], unreviewed["recommended_action"]
        )

    def test_the_reading_lowers_the_ceiling_and_routes_to_the_answer_key(
        self,
    ) -> None:
        wrong = ("row-1", "row-5", "row-13")
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            rows = self._rows(wrong)
            before = self._score(directory, rows, None)
            after = self._score(directory, rows, self._review(rows, wrong))
        self.assertNotIn(
            "dataset-unsound-expected-outputs",
            [cap["condition"] for cap in before["caps"]],
        )
        cap = next(
            entry
            for entry in after["caps"]
            if entry["condition"] == "dataset-unsound-expected-outputs"
        )

        # The lowest ceiling the DATASET may claim under falls. This fixture
        # supplies no evaluator and no config space, so a stricter cap from
        # elsewhere is already holding `overall` below 70 - which is the honest
        # shape of a cap: it is a limit, and a limit only moves a number that
        # had reached it.
        def dataset_ceiling(score: dict) -> int:
            return min(
                entry["ceiling"]
                for entry in score["caps"]
                if entry["condition"].startswith("dataset-")
            )

        self.assertLess(dataset_ceiling(after), dataset_ceiling(before))
        self.assertEqual(cap["ceiling"], 70)
        # The remedy travels on the cap itself. Which remedy is recommended
        # FIRST is a separate question, and on this fixture a stricter blocking
        # cap (no evaluator is connected at all) rightly answers it.
        self.assertEqual(cap["action_kind"], "review-answer-key")
        self.assertLessEqual(after["overall"], before["overall"])

    def test_a_review_without_the_preflight_it_describes_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            review_path = Path(raw) / "row-review.json"
            review_path.write_text(json.dumps(self._review(self._rows())))
            process = subprocess.run(
                [
                    sys.executable,
                    str(READINESS),
                    "--row-review",
                    str(review_path),
                    "--agent",
                    "real",
                    "--dataset",
                    "real",
                    "--evaluation",
                    "real",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 2)
        self.assertIn("--row-review needs --preflight", process.stderr)


class TheFamilyPartitionedSplitReachesTheCardTests(unittest.TestCase):
    """#242 end to end: the two scripts have to agree about the same file.

    The unit halves are pinned either side of this - preflight's own reading in
    `tests/test_preflight.py`, the cap's routing in
    `tests/test_readiness_scoring.py` - and neither can see the seam. The
    finding travels as a metric on a check readiness has to know to look for,
    and a check whose record readiness never reads is a check that runs and
    changes nothing.
    """

    @staticmethod
    def _rows(partitioned: bool) -> list[dict]:
        """The issue's own shape: `add`/`max_of` tuned, `is_even`/`fib` held back."""
        stems = ("def add", "def max_of", "def is_even", "def fib")
        rows = []
        for index, stem in enumerate(stems):
            for case in range(8):
                rows.append(
                    {
                        "id": f"{stem}-{case}".replace(" ", "-"),
                        "input": f"{stem}(value) case number {case}",
                        "output": stem.split()[-1],
                        "provenance": "collected",
                        "difficulty": ("easy", "medium", "hard", "very-hard")[case % 4],
                        "split": (
                            ("tuning" if index < 2 else "holdout")
                            if partitioned
                            else ("tuning" if case < 6 else "holdout")
                        ),
                    }
                )
        return rows

    def _score(self, partitioned: bool) -> dict:
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "dataset.jsonl", self._rows(partitioned))
            return _score(
                dataset,
                # The agent is declared so the card is about the SPLIT. Leaving
                # it out would put a blocking absent-agent cap on both sides of
                # the comparison, and this test's whole content is that the
                # family-partitioned side stops nothing.
                extra=(
                    "--evaluator-method",
                    "normalized-exact",
                    "--agent-origin",
                    "brought",
                ),
                preflight_extra=("--evaluator-method", "normalized-exact"),
            )

    def test_the_split_still_passes_and_the_family_check_does_not(self) -> None:
        """Disjointness was never the wrong answer - it was the wrong question."""
        with tempfile.TemporaryDirectory() as raw:
            records = _preflight_records(
                _write_jsonl(Path(raw), "dataset.jsonl", self._rows(True))
            )
        statuses = {record["check"]: record["status"] for record in records}
        self.assertEqual(statuses["dataset-split"], "PASS")
        self.assertEqual(statuses["dataset-split-family"], "WARN")

    def test_the_cap_reaches_the_card_and_the_run_is_not_stopped(self) -> None:
        score = self._score(True)
        cap = _cap(score, "dataset-split-by-task-family")
        self.assertFalse(cap["blocks"])
        self.assertTrue(cap["asks"])
        self.assertEqual(cap["action_kind"], "review-split")
        self.assertEqual(score["status"], "OK")
        self.assertEqual(score["recommended_action"], "review-split")
        self.assertLessEqual(score["overall"], cap["ceiling"])

    def test_the_same_rows_split_across_the_families_reach_no_cap(self) -> None:
        """The counterfactual, so the cap is pinned to the LINE and not the rows.

        Compared on the CONDITIONS rather than on `overall`: neither run
        supplies a calibration or a reading of an agent, so both are already
        held at 45 by the advisory no-knobs and unvalidated-evaluator
        conditions, and an equal score there would say nothing about the cap
        this test is for. Both also carry the small-comparison ceiling, which
        is a fact about how many rows there are and is identical on either side
        of the redraw - it is in the expected list precisely so that the one
        condition that does move is the only difference between them.
        """

        def conditions(score: dict) -> list[str]:
            return sorted(cap["condition"] for cap in score["caps"])

        self.assertEqual(
            conditions(self._score(False)),
            [
                "agent-no-varying-knobs",
                "dataset-coarse-resolution",
                "evaluator-unvalidated",
            ],
        )
        self.assertEqual(
            conditions(self._score(True)),
            [
                "agent-no-varying-knobs",
                "dataset-coarse-resolution",
                "dataset-split-by-task-family",
                "evaluator-unvalidated",
            ],
        )


class TheDeclaredOriginTravelsFromArgvToTheCardTests(unittest.TestCase):
    """#238's flags, asserted where they are actually consumed.

    Found by mutation-probing this branch rather than by reading it. The unit
    tests beside `score_run` pass an origin into the fact set and the CLI test
    beside them reads it back off `parse_args` - which is the producer agreeing
    with itself, and neither touches the two lines in `run` that carry one to
    the other. Deleting BOTH of those lines left the whole suite green.

    That is the worst place for this branch to be blind. #238's decision that a
    missing flag raises nothing rests entirely on the guided run always passing
    one; a CLI that parses the flag and drops it scores every generated
    component as the customer's own and says nothing, which is the exact defect
    the change was written to remove.
    """

    def _rows(self) -> list[dict]:
        return [
            {
                "id": f"row-{index}",
                "input": f"Ticket {index}: the invoice total does not match the quote.",
                "output": ("billing", "refund", "account", "technical")[index % 4],
                "provenance": "collected",
                "difficulty": ("easy", "medium", "hard", "very-hard")[index % 4],
            }
            for index in range(40)
        ]

    def _conditions(self, *origin_flags: str) -> list[str]:
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "dataset.jsonl", self._rows())
            score = _score(
                dataset,
                extra=("--evaluator-method", "normalized-exact", *origin_flags),
                preflight_extra=("--evaluator-method", "normalized-exact"),
            )
        return sorted(cap["condition"] for cap in score["caps"])

    def test_declaring_nothing_is_the_baseline_these_are_measured_against(self) -> None:
        """The baseline, and since #375 the agent half of it is not free.

        Declaring nothing about the agent is now a finding rather than a
        neutral starting point: SKILL.md leaves the flag off only where no
        agent exists, so the payload reads that silence the way it already
        reads silence about the dataset and the evaluator. The two calls below
        differ in the declaration alone, which is what makes the flag visible
        here rather than assumed.
        """
        self.assertEqual(
            self._conditions(),
            ["agent-absent", "evaluator-unvalidated"],
        )
        self.assertEqual(
            self._conditions(
                "--evaluator-origin", "brought", "--agent-origin", "brought"
            ),
            ["agent-no-varying-knobs", "evaluator-unvalidated"],
        )

    def test_each_flag_reaches_the_payload_on_its_own(self) -> None:
        """One at a time, so neither line can be carried by the other."""
        self.assertEqual(
            self._conditions("--evaluator-origin", "generated"),
            [
                # No `--agent-origin` in this call, so the agent half reports
                # its own silence rather than an unestablished search space.
                "agent-absent",
                "evaluator-generated",
                "evaluator-unvalidated",
            ],
        )
        self.assertEqual(
            self._conditions("--agent-origin", "generated"),
            [
                "agent-generated",
                "agent-no-varying-knobs",
                "evaluator-unvalidated",
            ],
        )

    def test_an_unknown_origin_is_refused_rather_than_ignored(self) -> None:
        """A value outside the vocabulary must not read as "not declared".

        Silently ignoring it would be the same silence the flag exists to end,
        arriving through the flag itself.
        """
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "dataset.jsonl", self._rows())
            preflight_json = json.dumps(_preflight_records(dataset))
            process = subprocess.run(
                [
                    sys.executable,
                    str(READINESS),
                    "--preflight",
                    "-",
                    "--json",
                    "--agent-origin",
                    "demo",
                ],
                input=preflight_json,
                capture_output=True,
                text=True,
            )
        self.assertEqual(process.returncode, 2)
        self.assertIn("invalid choice: 'demo'", process.stderr)


class DuplicatedRowsBuyNoResolutionTests(unittest.TestCase):
    """Copying rows must not clear the cap that asks for more comparisons.

    `dataset-coarse-resolution` is the cap about RESOLUTION - whether the rows
    can tell two configurations apart - and the remedy it carries asks for more
    comparable examples. The cheapest way to satisfy a count of rows is to copy
    the rows already there, and that adds no comparison whatever: both copies
    hold the same input, so every configuration scores them identically and the
    pair separates nothing. The fake repair was therefore the exact opposite of
    the cap's own subject, and it used to clear it.

    Nothing had to be measured to refuse it. Preflight scans the inputs for
    repetition on its way past and reports what it found in the same JSON this
    scorer is handed, so the evidence was already inside the document being
    scored. These tests drive the real chain and pin that the scorer reads it.
    """

    @staticmethod
    def _rows(copies: int) -> list[dict]:
        """A dataset whose tuning side is `copies` copies of the same questions.

        Half of `MODULE.COARSE_RESOLUTION_EXAMPLES` distinct tuning questions, so one
        copy sits below the resolution line and two copies reach it by row count
        alone. The held-out side is left alone and stays distinct - the cap is a
        property of the tuning split, and a duplicate there would be a second
        finding rather than this one.
        """
        distinct = MODULE.COARSE_RESOLUTION_EXAMPLES // 2
        tuning = [
            {
                "input": f"summarise ticket {index} about a billing charge",
                "output": f"billing-{index}",
                "source": "collected",
                "split": "tuning",
            }
            for index in range(distinct)
        ]
        holdout = [
            {
                "input": f"summarise account note {index} about a refund",
                "output": f"refund-{index}",
                "source": "collected",
                "split": "holdout",
            }
            for index in range(MODULE.WALKTHROUGH_HOLDOUT_ROWS)
        ]
        return tuning * copies + holdout

    def _score_copies(self, copies: int) -> dict:
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "dataset.jsonl", self._rows(copies))
            return _score(dataset)

    def test_the_honest_dataset_is_capped_on_its_resolution(self) -> None:
        """The starting state: half the resolution line, so the cap fires.

        Pinned first because the duplicated case below is only meaningful
        against it - a cap that never fired cannot be shown to survive.
        """
        score = self._score_copies(1)
        self.assertIn(
            "dataset-coarse-resolution",
            [cap["condition"] for cap in score["caps"]],
        )
        power = _dataset_subscore(score, "power")
        self.assertEqual(power["value"], 12.0)
        self.assertIn(
            f"{MODULE.COARSE_RESOLUTION_EXAMPLES // 2} examples", power["evidence"]
        )

    def test_duplicating_every_tuning_row_does_not_clear_the_cap(self) -> None:
        """The fake repair, performed exactly as a reader would perform it.

        Fifteen tuning rows copied once is thirty rows and fifteen questions.
        By row count that clears the line; by comparisons it has not moved.
        """
        duplicated = self._score_copies(2)
        # Asserted by name before it is read, so the regression this test exists
        # for reports as the cap going missing rather than as a `StopIteration`
        # inside a helper.
        self.assertIn(
            "dataset-coarse-resolution",
            [cap["condition"] for cap in duplicated["caps"]],
        )
        cap = _cap(duplicated, "dataset-coarse-resolution")
        self.assertEqual(cap["ceiling"], MODULE.COARSE_RESOLUTION_CEILING)
        # The same number the honest dataset scored. Copying rows may not move
        # the power sub-score either, or the cap would merely be a label over a
        # score that had already been bought.
        self.assertEqual(_dataset_subscore(duplicated, "power")["value"], 12.0)

    def test_the_card_says_which_rows_repeat_rather_than_only_refusing(
        self,
    ) -> None:
        """A refusal a customer cannot act on is half an answer.

        The evidence has to carry both counts: what their file holds and what a
        comparison can resolve. Naming only the second reads as the scorer
        losing their rows.
        """
        evidence = _dataset_subscore(self._score_copies(2), "power")["evidence"]
        distinct = MODULE.COARSE_RESOLUTION_EXAMPLES // 2
        self.assertIn(f"{MODULE.COARSE_RESOLUTION_EXAMPLES} to tune on", evidence)
        self.assertIn(f"{distinct} of them repeat an input already counted", evidence)
        self.assertIn(f"{distinct} examples", evidence)

    def test_a_duplicate_finding_without_its_count_is_refused(self) -> None:
        """An older payload must not read as a clean one.

        The state this refuses is precisely the one where the row count
        overstates the comparison, so scoring it on the rows would restore the
        defect for exactly the datasets that have it.
        """
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "dataset.jsonl", self._rows(2))
            records = _preflight_records(dataset)
        for record in records:
            if record["check"] == "dataset-duplicates":
                self.assertEqual(record["status"], "WARN")
                record["metrics"].pop("distinct_rows")
        process = _run_readiness(records)
        self.assertEqual(process.returncode, 2)
        self.assertIn("carries no distinct_rows count", process.stderr)


class WhichRowsMayBeSubtractedFromTheComparisonCountTests(unittest.TestCase):
    """What "the same row" is allowed to mean when it lowers a customer's score.

    `resolved_by_distinct` bounds the comparison count by preflight's count of
    DIFFERENT rows, and that count is exact-after-normalization. On the fixture
    below it does its job: 40 whole-row copies planted among 132 questions are
    found and reported as 100. That is a statement about this fixture rather
    than about the mechanism, which had a second gap of its own - the distinct
    count was taken over ALL tuning rows while the number it bounds counts only
    the LABELLED ones, so a split mixing the two carried byte-identical repeats
    through a comparison that subtracted nothing. That was
    traigent-first-run#356 and it is fixed: both counts are now taken over the
    rows being compared, and `ARepeatSurvivesAMixedSplitNoLongerTests` below
    holds them there. Every fixture in THIS class is fully labelled, so none of
    them could ever have shown it, which is why the two classes are separate.

    What the count cannot see at all is a row REWORDED - six questions written
    out fifty times each as `... (variant N)` are 300 byte-distinct rows, and
    the card called them a `substantial comparison set` while the line two rows
    above it said `rows at least 70% similar to another row`.

    The obvious fix is to bound the count on the near-duplicate reading instead.
    It was built and measured, and it is refused. Every figure below is measured
    on the fixtures in this class, at 70% Jaccard over three-word runs with an
    identical expected answer required:

        reworded 300 rows          honest 6     bound says   6   correct
        120 distinct tickets, raw  honest 120   bound says 120   correct
        the same 120 under a
        64-word instruction        honest 120   bound says   4   FALSE RED
        the same 120 with that
        text as a SUFFIX           honest 120   bound says   4   FALSE RED

    Four, over 120 genuinely different support tickets: the card would call that
    dataset `a wiring check, not a score` and raise a ceiling over the run. A
    false red on ordinary data is worse than a generous number on repetitive
    data, because the generous number is advisory and the ceiling stops a run.

    What is NOT claimed here is that the separation is impossible. Two repairs
    clear every fixture above - discounting three-word runs that appear in more
    than half the corpus, and stripping the shared opening `family_offset`
    already computes for `dataset-split-family`, whose own docstring calls an
    instruction prefix "the ordinary case rather than a corner". The first holds
    at every cut from 0.9 to 0.3 and collapses at 0.1, where the reworded rows
    go back to reporting all 300 as different; the second clears a prefix and
    still reports 4 on the same boilerplate moved to the end of the row. Both
    are one threshold picked against five corpora somebody wrote for this test,
    and the failure is silent and in the punishing direction, so neither is
    validated enough to lower a customer's score on. That is the reason this
    ships no bound - not that no signal exists.

    What ships instead is a CLAUSE. The complaint was a card that contradicted
    itself, and `facts.near_duplicate_status` was already carried into the
    scorer and already deducting seven diversity points. Saying what the repeat
    check found, and what this count did about it, moves no value, raises no
    ceiling, and cannot false-red whatever the check later becomes.

    THE CLAUSE ONLY REACHES WHAT THE CHECK CATCHES, AND THAT IS LESS THAN THIS
    CLASS MIGHT SUGGEST. It hangs off `dataset-near-duplicates`, which decides
    at 70% similarity, so a reworded repeat that lands under the line is
    invisible to it - and this repository shipped one. Measured on
    `tests/behavioral/outcomes/clean-proceed/project/evaluation-dataset.jsonl`,
    the canonical CLEAN outcome: 36 tuning rows resolving to 24 questions, with
    `[case 025]`...`[case 036]` repeating `[case 001]`...`[case 012]` word for
    word apart from the number. `dataset-duplicates` PASS, `dataset-near-
    duplicates` PASS at a maximum pairwise similarity of 0.6923 - 0.0077 under
    the line - so the card printed `36 examples - limited comparison set` with
    no clause at all, beside a diversity line affirming `no repeated questions
    at 70% similarity or more`. `asking-answer-key` held the same rows.

    BOTH HALVES OF THAT ARE NOW CLOSED, and neither by moving the threshold.
    The sentence went first: a scan comparing inputs and counting shared word
    runs may not report on whether two rows ask the same QUESTION, so the clean
    line says what the two scans established and the similarity scan may no
    longer clear the question by itself. Then the fixture, because the number
    beside it was still 36 for 24 questions and no wording fixes that - those
    two files now hold 48 different questions with a held-out split that shares
    none of them, and `ACleanOutcomeFixtureIsMadeOfDifferentQuestionsTests` in
    the behavioral suite keeps them that way. What is NOT claimed is that the
    threshold has been made right. It cannot be: the reworded fixtures above put
    120 different tickets at 4 under a shared instruction, and the repaired file
    put 24 real repeats at 0.6923, so the false-red band and the false-green
    band overlap and no line between them exists. That is why the bound below
    is still exact-identity only.
    """

    # 34 subjects x 4 measures is 136 phrasings, of which the fixture uses 132.
    # Written out rather than generated from anything the scorer imports: a
    # fixture built from the constant an assertion reads is a test that passes
    # for every value of it.
    SUBJECTS = (
        "singers",
        "albums",
        "concerts",
        "stadiums",
        "countries",
        "cities",
        "tracks",
        "playlists",
        "labels",
        "producers",
        "venues",
        "tours",
        "awards",
        "genres",
        "instruments",
        "studios",
        "engineers",
        "festivals",
        "sponsors",
        "tickets",
        "refunds",
        "invoices",
        "shipments",
        "returns",
        "warehouses",
        "couriers",
        "suppliers",
        "contracts",
        "employees",
        "shifts",
        "departments",
        "budgets",
        "regions",
        "currencies",
    )
    MEASURES = ("count", "average rating", "total revenue", "earliest date")
    COLUMNS = {
        "count": "COUNT(*)",
        "average rating": "AVG(rating)",
        "total revenue": "SUM(revenue)",
        "earliest date": "MIN(created_at)",
    }

    # Six questions, each written out fifty times with a `(variant N)` suffix
    # and the identical expected answer - the shape that was reported, and the
    # one no exact count can see.
    REWORDED = (
        (
            "How many orders were placed by customers in the state of "
            "California during the last full calendar quarter",
            "SELECT COUNT(*) FROM orders WHERE state = 'CA'",
        ),
        (
            "What is the total revenue collected from every subscription "
            "invoice that was paid in the previous financial year",
            "SELECT SUM(amount) FROM invoices WHERE status = 'paid'",
        ),
        (
            "Which five products generated the largest gross margin across "
            "all warehouse regions last month",
            "SELECT product_id FROM sales ORDER BY margin DESC LIMIT 5",
        ),
        (
            "List every employee who has not submitted a timesheet for any "
            "week since the start of the current year",
            "SELECT id FROM employees WHERE timesheet_id IS NULL",
        ),
        (
            "What is the average number of days between an order being placed "
            "and the same order being delivered",
            "SELECT AVG(delivered_at - placed_at) FROM orders",
        ),
        (
            "Show the monthly count of new support tickets opened by "
            "enterprise accounts over the past two years",
            "SELECT date_trunc('month', opened_at) FROM tickets",
        ),
    )

    # 120 support tickets, thirty per category, each a different problem a
    # person would recognise as its own. Not five passes over twenty-four texts
    # with a week number appended, which is what this fixture was: two rows
    # differing only in a numeral are answered identically by any classifier,
    # so the earlier version was itself an instance of the defect and its tests
    # forbade the scorer from noticing.
    BILLING = (
        "my card was charged twice for the same monthly plan",
        "the invoice pdf will not open in my browser at all",
        "I was billed after cancelling my subscription last week",
        "the price on my receipt does not match the checkout page",
        "please explain the pro rata line on this month statement",
        "a currency conversion fee appeared that I never agreed to",
        "our purchase order number is missing from every invoice",
        "the tax rate applied looks wrong for our registered address",
        "we need invoices sent to accounts payable and not to me",
        "the annual plan renewed at a higher rate without warning",
        "your system charged a card we removed months ago",
        "the discount code from your sales team was never applied",
        "billing emails go to a colleague who left the company",
        "we are on net thirty terms but got a dunning notice",
        "the seat overage line has no breakdown I can audit",
        "an unfamiliar charge from a region we do not operate in",
        "the receipt shows a plan name we have never subscribed to",
        "payment failed silently and nobody told us for a fortnight",
        "we want to switch from monthly to annual mid cycle",
        "the vat number on our invoices is missing a digit",
        "a credit note was promised in march and never issued",
        "your billing portal rejects our corporate amex outright",
        "the usage graph and the invoice disagree by four thousand calls",
        "we were charged for a workspace that was archived in january",
        "the first invoice arrived three weeks after the trial ended",
        "estimated charges in the console never match the final bill",
        "we cannot download invoices older than twelve months",
        "the plan comparison page quotes a price the checkout ignores",
        "our card expires next month and there is no way to update it",
        "a failed payment locked the account before anyone was emailed",
    )
    TECHNICAL = (
        "the app crashes whenever I open the reporting dashboard",
        "exports keep timing out on datasets larger than ten megabytes",
        "single sign on redirects me back to the login screen",
        "notifications stopped arriving on my phone after the update",
        "the search box returns nothing even for exact titles",
        "uploading a csv fails with an unhelpful server error",
        "webhooks stopped firing at about three in the morning",
        "the api returns five hundred on any request with a filter",
        "charts render blank in firefox but fine in chrome",
        "our nightly sync has been stuck at ninety percent for days",
        "the mobile app logs out every time it goes to background",
        "date pickers show the wrong month in australian timezones",
        "bulk edit silently drops changes past the hundredth row",
        "the websocket connection drops every ninety seconds",
        "pdf reports come out with overlapping text in the header",
        "rate limits trigger far below the documented threshold",
        "the sandbox environment returns production data occasionally",
        "keyboard navigation skips the entire left hand menu",
        "attachments over five megabytes vanish without an error",
        "the integration with our warehouse stopped authenticating",
        "scheduled jobs run twice whenever daylight saving shifts",
        "the audit log is missing every event from last tuesday",
        "our custom domain shows a certificate warning in safari",
        "pagination returns the same page for every cursor value",
        "the editor loses unsaved work when a session token expires",
        "sorting by date puts december before january every time",
        "the diff view shows changes that were never made",
        "importing from the legacy format truncates unicode names",
        "background workers pile up until the queue has to be flushed",
        "the health endpoint reports green while the app is down",
    )
    ACCOUNT = (
        "I cannot change the email address on my profile",
        "two factor codes are rejected even though the clock is right",
        "please merge the duplicate workspace someone created",
        "I need to transfer ownership of a project to a colleague",
        "my teammate cannot see the folder I shared with her",
        "the seat count on our plan is wrong after an offboarding",
        "our admin left and nobody else has administrator rights",
        "invitations expire before new joiners can accept them",
        "the role picker offers permissions our tier does not include",
        "deleting a member removed their comments from every thread",
        "we need to rename the organisation after an acquisition",
        "sso group mapping puts contractors in the finance group",
        "the password reset link keeps saying it has already been used",
        "a departed employee still receives our weekly digest",
        "we cannot enforce two factor for the whole organisation",
        "guest accounts can see internal projects they should not",
        "the activity feed attributes my actions to another user",
        "moving a project between teams lost all its permissions",
        "our domain capture claims users we did not invite",
        "the api key list shows keys nobody in the team recognises",
        "a suspended account still counts towards our seat limit",
        "profile photos revert to the default after every login",
        "we need an export of who accessed what for our auditors",
        "the invite email lands in spam for everyone on outlook",
        "changing a workspace slug broke every bookmarked link",
        "there is no way to see which seats are actually being used",
        "our security team needs session length shortened to an hour",
        "the account recovery flow asks for a phone we never gave",
        "team members added by sso cannot be removed manually",
        "the ownership transfer completed but the old owner kept access",
    )
    REFUND = (
        "I would like a refund for the annual plan bought yesterday",
        "we were double charged when renewing two workspaces at once",
        "the trial converted early and I want the difference back",
        "a chargeback was raised in error and I want to reverse it",
        "please refund the overage from last month unexpected spike",
        "I cancelled within the window and still want my money back",
        "we paid for twenty seats and only ever activated three",
        "the outage last quarter should come with a service credit",
        "a duplicate subscription ran alongside ours for six months",
        "our finance team paid an invoice that had already been settled",
        "the upgrade was a mistake made by an intern the same hour",
        "we want the unused portion back after downgrading early",
        "a refund was approved in july and has never arrived",
        "the amount refunded is short by the payment processing fee",
        "we were billed in dollars after switching to euro pricing",
        "a promotional month was charged despite the offer letter",
        "the renewal happened while our cancellation ticket was open",
        "please refund the sandbox workspace we were told was free",
        "we paid twice because the first attempt showed as failed",
        "the enterprise quote was signed lower than what we were charged",
        "our nonprofit discount was applied a full year too late",
        "a data migration we never received was billed as a service",
        "the partial month after termination should not have been billed",
        "we want the deposit back now that the pilot has ended",
        "the wrong entity was invoiced and paid it before we noticed",
        "an add on we disabled kept billing for another two cycles",
        "the credit from the previous refund was never usable",
        "we cancelled the trial and were still charged the setup fee",
        "the annual commitment was cancelled under the thirty day clause",
        "refund issued to a closed card and nobody can tell us where it went",
    )

    TICKETS = BILLING + TECHNICAL + ACCOUNT + REFUND
    CATEGORIES = ("billing", "technical", "account", "refund")
    # The wrapper a real prompted classification dataset carries on every row.
    # Sixty-four words of it, which is ordinary, and it is what makes 120 different
    # tickets look alike to a measure that reads runs of words.
    INSTRUCTION = (
        "You are an experienced customer support triage assistant working for "
        "a software company that sells a subscription analytics product to "
        "business teams. Read the following customer support ticket carefully "
        "and decide which single category it belongs to, choosing only from "
        "billing, technical, account and refund, and reply with the category "
        "name on its own with no other words or punctuation. The ticket "
        "text follows: "
    )
    # The sentence the card gains when the repeat check fired. Stated once here
    # and asserted both ways, because a clause that appears everywhere says as
    # little as one that appears nowhere.
    CAVEAT = (
        "the repeated-rows check fired, and this count subtracts exact repeats only"
    )

    @classmethod
    def _questions(cls) -> list[tuple[str, str]]:
        asked = [
            (
                f"How many {subject} do we have and what is the "
                f"{measure} across them",
                f"SELECT {cls.COLUMNS[measure]} FROM {subject}",
            )
            for subject in cls.SUBJECTS
            for measure in cls.MEASURES
        ]
        return asked[:132]

    @classmethod
    def _copied_rows(cls) -> list[dict]:
        """132 different questions, 40 of them copied whole into the tuning side.

        140 rows to tune on - 100 originals and 40 exact copies of the first
        forty - and 32 held back. A comparison on that tuning side can resolve
        100 different examples, and no arithmetic in the scorer is needed to
        know it: the fixture says which forty were copied.
        """
        questions = cls._questions()
        rows = [
            {
                "id": f"tune-{index}",
                "input": question,
                "output": answer,
                "source": "collected",
                "split": "tuning",
            }
            for index, (question, answer) in enumerate(questions[:100])
        ]
        rows += [
            {
                "id": f"tune-copy-{index}",
                "input": question,
                "output": answer,
                "source": "collected",
                "split": "tuning",
            }
            for index, (question, answer) in enumerate(questions[:40])
        ]
        rows += [
            {
                "id": f"hold-{index}",
                "input": question,
                "output": answer,
                "source": "collected",
                "split": "holdout",
            }
            for index, (question, answer) in enumerate(questions[100:])
        ]
        return rows

    @classmethod
    def _ticket_rows(cls, instruction: str = "") -> list[dict]:
        """120 different tickets over four categories, 60 each side of the split.

        Thirty tickets per category, every one of them its own problem, so the
        honest comparison count is 120 and the honest tuning count is 60. That
        is the property the tests below rest on, and it is a property of the
        text rather than of any measure applied to it: no two of these rows can
        be answered by one another.
        """
        return [
            {
                "id": f"ticket-{index}",
                "input": f"{instruction}{ticket}",
                "output": cls.CATEGORIES[index // 30],
                "source": "collected",
                "split": "tuning" if index % 2 == 0 else "holdout",
            }
            for index, ticket in enumerate(cls.TICKETS)
        ]

    @classmethod
    def _reworded_rows(cls) -> list[dict]:
        """300 rows spelling six questions, split 150 to tune on / 150 held back."""
        rows = []
        for question_index, (question, answer) in enumerate(cls.REWORDED):
            for copy in range(50):
                suffix = "" if copy == 0 else f" (variant {copy})"
                rows.append(
                    {
                        "id": f"q{question_index}-v{copy}",
                        "input": f"{question}{suffix}",
                        "output": answer,
                        "source": "collected",
                        "split": "tuning" if copy < 25 else "holdout",
                    }
                )
        return rows

    def _evidence(self, rows: list[dict]) -> str:
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "dataset.jsonl", rows)
            score = _score(dataset)
        return _dataset_subscore(score, "power")["evidence"]

    def _caps(self, rows: list[dict]) -> list[str]:
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "dataset.jsonl", rows)
            score = _score(dataset)
        return [cap["condition"] for cap in score["caps"]]

    def _near_duplicate_status(self, rows: list[dict]) -> str:
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "dataset.jsonl", rows)
            records = _preflight_records(dataset)
        return next(
            record["status"]
            for record in records
            if record["check"] == "dataset-near-duplicates"
        )

    def test_whole_row_copies_are_subtracted_from_the_comparison_count(self) -> None:
        """The mechanism that works, pinned to the sentence a customer reads.

        Forty of the 140 tuning rows are copies, so the tuning side holds 100
        different examples. Both numbers are asserted, and the band with them,
        because a bound that quietly stopped subtracting would still print a
        plausible sentence about a hundred and forty rows.
        """
        evidence = self._evidence(self._copied_rows())
        self.assertIn("140 to tune on / 32 held back", evidence)
        self.assertIn("40 of them repeat an input already counted", evidence)
        self.assertIn(
            "100 different example(s) are what a comparison can resolve", evidence
        )
        self.assertIn("100 examples - substantial comparison set", evidence)

    def test_different_questions_sharing_one_answer_key_are_not_repeats(self) -> None:
        """Reused labels are what a closed-label task IS, not repetition.

        A hundred and twenty tickets over four categories: thirty rows carry
        each answer, and every one is a different problem a model can get right
        or wrong on its own. Nothing may be subtracted, and the repeat check
        does not fire at all on this text - which is what separates this case
        from the prefixed one below rather than repeating it. So the caveat must
        be absent here, or it would be a sentence the card prints unconditionally.
        """
        rows = self._ticket_rows()
        self.assertEqual(self._near_duplicate_status(rows), "PASS")
        evidence = self._evidence(rows)
        self.assertIn("60 to tune on / 60 held back", evidence)
        self.assertIn("60 examples - moderate comparison set", evidence)
        self.assertNotIn("repeat an input already counted", evidence)
        self.assertNotIn(self.CAVEAT, evidence)

    def test_an_instruction_shared_by_every_row_is_not_repetition(self) -> None:
        """The same 120 tickets, wrapped the way a prompted dataset wraps them.

        This is the dataset that refused the bound. The similarity check fires
        on it - correctly, by its own definition, because the rows DO share more
        than 70% of their word runs - and the tickets underneath are still 120
        different problems. So the warning is asserted as present and the
        comparison count as untouched, in one test: the pair of them is the
        finding, and either alone reads as the other check being broken.
        """
        rows = self._ticket_rows(self.INSTRUCTION)
        self.assertIn(self._near_duplicate_status(rows), ("WARN", "FAIL"))
        evidence = self._evidence(rows)
        self.assertIn("60 to tune on / 60 held back", evidence)
        self.assertIn("60 examples - moderate comparison set", evidence)
        self.assertNotIn("repeat an input already counted", evidence)
        # And the card says what was found, on the dataset where saying it costs
        # a good corpus nothing.
        self.assertIn(self.CAVEAT, evidence)
        # The ceiling, asserted rather than inferred. A count of four raises
        # `dataset-below-measurable-size` and drops the overall score from 30 to
        # 23, and THAT is the harm the whole class argues about - a number is
        # advisory, a ceiling stops a run. The band assertion above happens to
        # catch the same mutant today, which is why these were once dropped as
        # redundant; redundancy against one mutant is not the same as saying
        # nothing about the consequence, and this class had said nothing.
        self.assertNotIn("dataset-below-measurable-size", self._caps(rows))
        self.assertNotIn("dataset-coarse-resolution", self._caps(rows))

    def test_a_reworded_dataset_is_still_scored_on_its_rows(self) -> None:
        """PINS A VALUE THAT IS KNOWN TO BE WRONG, so that fixing it goes red.

        Six questions in three hundred rows resolve six comparisons, and the
        tuning side of this fixture resolves six. The card says 150. That is the
        defect, it is unfixed, and nothing in the repository reproduced it -
        so a correct bound could have been written and merged with every test
        green and no sign that this line had moved.

        The band assertion below is therefore NOT a statement that 150 is
        right. It is a tripwire: change the comparison count for the better and
        this test fails, which is the notice to come and delete it. What the
        card must say truthfully today is the second half - the repeat check
        fired, and this count only subtracts exact repeats - and that half is
        asserted as a requirement rather than as a tripwire.
        """
        rows = self._reworded_rows()
        self.assertIn(self._near_duplicate_status(rows), ("WARN", "FAIL"))
        evidence = self._evidence(rows)
        self.assertIn(self.CAVEAT, evidence)
        self.assertIn(
            "150 examples - substantial comparison set",
            evidence,
            "the comparison count on a reworded dataset has changed. If it now "
            "reports the six questions these 300 rows spell, that is the fix "
            "this class documents as open: delete this tripwire, and check the "
            "false-red fixtures above still pass.",
        )

    def test_the_caveat_is_carried_by_the_repeat_check_and_nothing_else(self) -> None:
        """One switch, both positions, on datasets that differ only in that switch.

        The two ticket fixtures hold the same 120 problems and the same 4
        answers; the prefixed one is the same text with a wrapper. Preflight's
        repeat check is what differs, so a clause that follows it must appear on
        exactly one of them - and a clause bolted to anything else in the
        payload would appear on both or neither.
        """
        plain = self._ticket_rows()
        wrapped = self._ticket_rows(self.INSTRUCTION)
        self.assertEqual(self._near_duplicate_status(plain), "PASS")
        self.assertIn(self._near_duplicate_status(wrapped), ("WARN", "FAIL"))
        self.assertNotIn(self.CAVEAT, self._evidence(plain))
        self.assertIn(self.CAVEAT, self._evidence(wrapped))
        # And it does not depend on anything having been subtracted: the copied
        # fixture subtracts forty rows and still carries it, because the exact
        # pass cannot tell the scorer whether the near check found more.
        self.assertIn(self.CAVEAT, self._evidence(self._copied_rows()))

    def test_the_clause_refers_to_the_repeat_check_rather_than_restating_it(
        self,
    ) -> None:
        """The threshold has three homes already; this may not be a fourth.

        `DIVERSITY_CHECKS` owns the sentence describing the similarity line and
        prints it on its own row of the same card. A copy here would put the
        phrase twice on one card with nothing holding the two equal, and a copy
        that went stale would state a threshold the check did not decide on.
        So the clause carries no number, and the card carries the phrase once.
        """
        self.assertNotIn("%", self.CAVEAT)
        self.assertNotIn(str(MODULE.NEAR_DUPLICATE_PERCENT), self.CAVEAT)
        rows = self._ticket_rows(self.INSTRUCTION)
        self.assertIn(self.CAVEAT, self._evidence(rows))
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "dataset.jsonl", rows)
            card = _score(dataset)
        printed = " ".join(
            sub["evidence"] for pillar in card["pillars"] for sub in pillar["subscores"]
        )
        self.assertEqual(
            printed.count(f"{MODULE.NEAR_DUPLICATE_PERCENT}% similar"),
            1,
            "the similarity line is printed more than once on one card, so two "
            "copies of one threshold can drift apart between adjacent rows",
        )


class ARepeatSurvivesAMixedSplitNoLongerTests(unittest.TestCase):
    """The comparison count, end to end, on a dataset half annotated (#356).

    Everything here runs the shipped `preflight.py` and the shipped
    `readiness.py` as separate processes, so what is asserted is the sentence a
    customer reads rather than a call into the scorer's internals. The rows are
    written out from question texts and row counts; no assertion reads a
    constant the fixture was built from.
    """

    LABELLED = 20
    QUESTIONS = 10
    SILENT = 40
    HELD = 10

    @classmethod
    def _rows(cls, *, silent: int | None = None, labelled_answers: bool = True):
        """Tuning rows asking ten questions twice over, beside unlabelled rows.

        `silent` exists so one test can delete exactly the rows that are not
        scoreable and compare the two runs. That is the whole finding: rows the
        comparison never touches were deciding whether the bound applied.
        """
        silent = cls.SILENT if silent is None else silent
        rows = [
            {
                "id": f"labelled-{index}",
                "input": f"question number {index % cls.QUESTIONS} about billing",
                "output": f"answer-{index % cls.QUESTIONS}",
                "source": "collected",
                "split": "tuning",
            }
            for index in range(cls.LABELLED)
        ]
        if not labelled_answers:
            for row in rows:
                row.pop("output")
        rows += [
            {
                "id": f"silent-{index}",
                "input": f"an unlabelled question numbered {index} about shipping",
                "source": "collected",
                "split": "tuning",
            }
            for index in range(silent)
        ]
        rows += [
            {
                "id": f"held-{index}",
                "input": f"a held out question numbered {index} about accounts",
                "output": f"answer-h{index}",
                "source": "collected",
                "split": "holdout",
            }
            for index in range(cls.HELD)
        ]
        return rows

    def _score_rows(self, rows: list[dict], method: str | None = None) -> dict:
        # The method reaches BOTH scripts or neither. Preflight decides which
        # rows it can score, readiness decides which count describes them, and
        # telling only one of them is a third population - the very mistake this
        # class is about, made by the test instead of by the code.
        extra = () if method is None else ("--evaluator-method", method)
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "dataset.jsonl", rows)
            return _score(dataset, extra=extra, preflight_extra=extra)

    def _evidence(self, rows: list[dict], method: str | None = None) -> str:
        return _dataset_subscore(self._score_rows(rows, method), "power")["evidence"]

    def test_a_mixed_split_no_longer_carries_its_repeats_through_the_count(
        self,
    ) -> None:
        """The reproduction on the issue, asserted from both ends.

        Ten of the twenty scoreable tuning rows repeat a question the other ten
        already ask, so ten is what the comparison resolves. Twenty was the
        number this card printed, and it is asserted absent as well as ten
        asserted present: a bound that stopped applying would still print a
        fluent sentence about twenty examples.
        """
        evidence = self._evidence(self._rows())
        self.assertIn("10 of them repeat an input already counted", evidence)
        self.assertIn(
            "10 different example(s) are what a comparison can resolve", evidence
        )
        self.assertIn("10 examples - small comparison set", evidence)
        self.assertNotIn(
            "20 examples",
            evidence,
            "the comparison count is back to counting rows the split's "
            "unlabelled half made look distinct",
        )

    def test_rows_the_run_cannot_score_do_not_decide_whether_the_bound_applies(
        self,
    ) -> None:
        """The same twenty scoreable rows, with and without the silent forty.

        One variable moves between these two runs and it is rows that carry no
        answer. The reported comparison count may not move with it - that
        dependence IS the defect, and it is the one thing a single fixture
        cannot show.
        """
        with_silent = self._evidence(self._rows())
        without_silent = self._evidence(self._rows(silent=0))
        for evidence in (with_silent, without_silent):
            self.assertIn(
                "10 different example(s) are what a comparison can resolve",
                evidence,
            )

    def test_more_unlabelled_rows_never_loosen_the_bound_further(self) -> None:
        """Scaling the population that used to satisfy the guard changes nothing."""
        for silent in (0, 40, 200):
            with self.subTest(silent=silent):
                self.assertIn(
                    "10 different example(s) are what a comparison can resolve",
                    self._evidence(self._rows(silent=silent)),
                )

    def test_a_tuning_side_with_no_holdout_is_bounded_the_same_way(self) -> None:
        """The second call site, which the fixtures above never reach.

        `score_dataset` bounds the comparison count in three branches, and the
        one for a file declaring a tuning split with nothing held back is its
        own code path with its own copy of the decision. Reverting just that
        branch to the count over all tuning rows re-plants #356 there, and
        every other test in this file stays green - so the branch is exercised
        here rather than assumed to follow from its neighbour.
        """
        rows = [row for row in self._rows() if not row["id"].startswith("held-")]
        evidence = self._evidence(rows)
        self.assertIn("no held-out set", evidence)
        self.assertIn("10 of them repeat an input already counted", evidence)
        self.assertIn(
            "10 different example(s) are what a comparison can resolve", evidence
        )
        self.assertNotIn("20 examples", evidence)

    def test_a_payload_without_the_scoreable_count_leaves_the_number_alone(
        self,
    ) -> None:
        """An older preflight JSON must not be read as a dataset with no repeats.

        The count is absent there, and absent is not zero and not "the same as
        the rows". It returns the comparison count untouched, which restores the
        behaviour from before this bound existed rather than inventing one.
        """
        records = _declared_split_records(
            {
                "tuning_rows": 60,
                "tuning_labelled_rows": 20,
                "tuning_distinct_rows": 50,
            },
            {"holdout_rows": 10, "holdout_labelled_rows": 10},
        )
        evidence = _dataset_subscore(_score_records(records), "power")["evidence"]
        self.assertNotIn("repeat an input already counted", evidence)

    def test_a_reference_free_run_still_bounds_on_an_older_payload(self) -> None:
        """The reason the reference-free arm reads the count that always existed.

        A judge needing no gold answer scores every present row, so the two
        counts describe the same rows and either answers. Reading the older key
        there is what keeps a preflight JSON written before the newer one was
        added from silently losing its bound: the new key is absent, and absent
        means the comparison count is returned untouched. Choosing the newer key
        for both arms would pass every fixture in this class and drop the bound
        on exactly the payloads nobody regenerated.
        """
        records = _declared_split_records(
            {
                "tuning_rows": 60,
                "tuning_labelled_rows": 0,
                "tuning_distinct_rows": 50,
            },
            {"holdout_rows": 10, "holdout_labelled_rows": 0},
        )
        evidence = _dataset_subscore(
            _score_records(records, ("--evaluator-method", "llm-judge-rubric")),
            "power",
        )["evidence"]
        self.assertIn("10 of them repeat an input already counted", evidence)
        self.assertIn(
            "50 different example(s) are what a comparison can resolve", evidence
        )

    def test_a_reference_free_method_bounds_on_every_tuning_row(self) -> None:
        """Where every present row is scoreable, every present row is counted.

        The rows are the same file with no expected answers at all, so under a
        judge that needs none the scoreable side is all sixty and the questions
        are fifty. A bound that kept counting only labelled rows would report
        nothing here, and a bound that kept counting all rows would report
        nothing on the fixture above; only a count taken over the rows being
        compared gets both right.
        """
        rows = self._rows(labelled_answers=False)
        evidence = self._evidence(rows, method="llm-judge-rubric")
        self.assertIn("10 of them repeat an input already counted", evidence)
        self.assertIn(
            "50 different example(s) are what a comparison can resolve", evidence
        )


class TheRoutesOfferedWhenRowsRepeatTests(unittest.TestCase):
    """What the card puts to a customer once repeated rows are found.

    Asserted as rendered by the shipped script, because the whole contract is
    about what a person reads: which routes exist, that exactly one is marked,
    that the marked one continues the run, that the mark never disagrees with
    the payload's own recommendation, and where the block sits relative to the
    result it follows.

    NUMBERS, MARKS AND POSITIONS - never sentences. An earlier version of this
    class pinned three phrases, and rewording the prose while keeping every
    number, the mark and the disclosure correct failed it. A guard that reds
    correct writing is a defect in the guard.
    """

    def _rows(self, repeats: int = 6, distinct: int = 12) -> list[dict]:
        rows = [
            {
                "id": f"row-{index}",
                "input": f"a question numbered {index} about the billing system",
                "output": f"answer-{index}",
                "source": "collected",
                "split": "tuning",
            }
            for index in range(distinct)
        ]
        rows += [
            {
                "id": f"copy-{index}",
                "input": f"a question numbered {index} about the billing system",
                "output": f"answer-{index}",
                "source": "collected",
                "split": "tuning",
            }
            for index in range(repeats)
        ]
        rows += [
            {
                "id": f"held-{index}",
                "input": f"a held out question numbered {index} about accounts",
                "output": f"answer-h{index}",
                "source": "collected",
                "split": "holdout",
            }
            for index in range(6)
        ]
        return rows

    def _flat_rows(self, repeats: int = 5, distinct: int = 15) -> list[dict]:
        """The same repetition in a file that declares no split at all."""
        rows = [
            {
                "id": f"row-{index}",
                "input": f"a question numbered {index} about the billing system",
                "output": f"answer-{index}",
                "source": "collected",
            }
            for index in range(distinct)
        ]
        rows += [
            {
                "id": f"copy-{index}",
                "input": f"a question numbered {index} about the billing system",
                "output": f"answer-{index}",
                "source": "collected",
            }
            for index in range(repeats)
        ]
        return rows

    def _card(self, rows: list[dict]) -> str:
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "dataset.jsonl", rows)
            records = _preflight_records(dataset)
        return _card_records(records)

    def _clean_rows(self) -> list[dict]:
        return self._rows(repeats=0)

    @staticmethod
    def _route_lines(card: str) -> list[str]:
        return [
            line.strip() for line in card.splitlines() if re.match(r"\s+[A-Z]\. ", line)
        ]

    @staticmethod
    def _quotes(line: str, number: int) -> bool:
        return re.search(rf"\b{number}\b", line) is not None

    def _marked(self, routes: list[str]) -> str:
        marked = [line for line in routes if MODULE.RECOMMENDED_MARK in line]
        self.assertEqual(len(marked), 1, f"not exactly one marked route: {routes}")
        return marked[0]

    # ---- the shape of the block

    def test_the_routes_are_lettered_from_a_without_a_gap(self) -> None:
        """Contiguous letters, whichever routes this state actually offers.

        The first route is conditional, so the letters are positions and not
        names: dropping it must renumber the rest rather than leaving the list
        starting at B.
        """
        for rows in (self._rows(), self._flat_rows()):
            routes = self._route_lines(self._card(rows))
            with self.subTest(routes=routes):
                self.assertTrue(routes)
                self.assertEqual(
                    [line[0] for line in routes],
                    [chr(ord("A") + index) for index in range(len(routes))],
                )

    def test_exactly_one_route_carries_the_recommendation(self) -> None:
        """Two marks and none are the same defect from opposite sides."""
        for rows in (self._rows(), self._flat_rows()):
            with self.subTest(rows=len(rows)):
                self._marked(self._route_lines(self._card(rows)))

    def test_the_recommended_route_never_hands_the_work_back(self) -> None:
        """The mark may not land on the route that ends this run's part.

        Asserted against the LAST route, which is the one that asks the
        customer to go and edit their own file. Whatever the other routes say
        and however many of them there are, the mark may not be on that one -
        continuing is this guide's default and a finding may not turn into a
        stop.
        """
        for rows in (self._rows(), self._flat_rows()):
            routes = self._route_lines(self._card(rows))
            with self.subTest(routes=routes):
                self.assertNotIn(MODULE.RECOMMENDED_MARK, routes[-1])

    # ---- the mark and the payload may not disagree

    def _card_for(self, action_caps: list, finding) -> tuple[str, str]:
        """A rendered card over hand-built caps, so both arms are reachable.

        The dataset fixtures in this class always carry a blocking
        `evaluator-absent`, so `recommended_action` is never the size remedy
        and the arm that offers to write rows is unreachable through them. It
        is the arm the whole block was rebuilt around, so it is driven here
        from `aggregate` directly rather than left unexercised.
        """
        score = MODULE.aggregate(
            [MODULE.Pillar("dataset", 70.0, 1.0, ())],
            action_caps,
            (),
            MODULE.DEFAULT_WEIGHTS,
            repeated=finding,
        )
        return score.recommended_action, MODULE.render_card(score, unicode_ok=False)

    @staticmethod
    def _size_cap(asks: bool):
        return MODULE.Cap(
            "dataset-coarse-resolution",
            89,
            "a small comparison set",
            blocks=False,
            asks=asks,
        )

    @staticmethod
    def _blocking_cap():
        return MODULE.Cap("evaluator-absent", 40, "no evaluator", blocks=True)

    def test_the_offer_to_write_rows_tracks_the_runs_own_recommendation(
        self,
    ) -> None:
        """The defect this block was rebuilt to remove.

        Writing rows is the bounded top-up's offer, and it exists only while a
        size cap is asking with nothing blocking ahead of it. The routes may
        point at that offer and may not make a second one, so the extra route
        appears exactly when the payload's own recommendation is that remedy.

        Identified by POSITION and COUNT, never by a word in the sentence. An
        earlier version of this test looked for "writes" in the route text, so
        renaming the verb made the assertion vacuous and a planted second offer
        went undetected.
        """
        finding = MODULE.RepeatedInputs(
            scoreable=18, distinct=12, side="on the tuning side"
        )
        cases = [
            ("a size cap asks and nothing blocks", [self._size_cap(True)], True),
            ("a size cap that may not offer", [self._size_cap(False)], False),
            (
                "something blocks ahead of it",
                [self._blocking_cap(), self._size_cap(True)],
                False,
            ),
            ("no cap at all", [], False),
        ]
        for name, caps, offers in cases:
            with self.subTest(case=name):
                action, card = self._card_for(caps, finding)
                self.assertEqual(action == MODULE.ADD_EXAMPLES, offers, action)
                routes = self._route_lines(card)
                self.assertEqual(
                    len(routes),
                    3 if offers else 2,
                    f"{name}: wrong number of routes: {routes}",
                )
                marked = self._marked(routes)
                self.assertTrue(marked.startswith("A."), marked)
                self.assertNotIn(MODULE.RECOMMENDED_MARK, routes[-1])

    def test_the_writing_route_names_no_count_of_its_own(self) -> None:
        """The block may point at the bounded offer and may not restate it.

        A count of rows to write here would be a second offer beside the one
        the size cap already made, with its own arithmetic and no bound, which
        is how the earlier version came to offer 30 rows against a 28-row stop.
        The route is the first one on the offering arm, by position.
        """
        for scoreable, distinct in ((18, 12), (40, 20), (9, 3)):
            with self.subTest(scoreable=scoreable, distinct=distinct):
                finding = MODULE.RepeatedInputs(
                    scoreable=scoreable, distinct=distinct, side="on the tuning side"
                )
                action, card = self._card_for([self._size_cap(True)], finding)
                self.assertEqual(action, MODULE.ADD_EXAMPLES)
                offer = self._route_lines(card)[0]
                self.assertEqual(
                    re.findall(r"\b\d+\b", offer),
                    [],
                    f"the writing route states a count of its own: {offer!r}",
                )

    def test_dropping_the_first_route_renumbers_the_rest(self) -> None:
        """The letters are positions, so removing A must not start the list at B."""
        finding = MODULE.RepeatedInputs(
            scoreable=18, distinct=12, side="on the tuning side"
        )
        for caps in ([self._size_cap(True)], [self._size_cap(False)]):
            _action, card = self._card_for(caps, finding)
            routes = self._route_lines(card)
            with self.subTest(routes=routes):
                self.assertEqual(
                    [line[0] for line in routes],
                    [chr(ord("A") + index) for index in range(len(routes))],
                )

    # ---- the numbers
    # ---- the numbers

    def test_the_routes_quote_the_count_the_card_reported(self) -> None:
        """One arithmetic, two places on one card, and they may not disagree.

        The block is assembled separately from the comparison count above it,
        which is exactly how two numbers about one dataset come to contradict
        each other on the same screen. Several shapes, because a single fixture
        would agree by coincidence.
        """
        for repeats, distinct in ((6, 12), (3, 20), (11, 14)):
            scoreable = distinct + repeats
            with self.subTest(repeats=repeats, distinct=distinct):
                card = self._card(self._rows(repeats=repeats, distinct=distinct))
                finding = next(
                    line
                    for line in card.splitlines()
                    if MODULE.REPEATED_ROWS_LABEL in line
                )
                for number in (repeats, scoreable, distinct):
                    self.assertTrue(
                        self._quotes(finding, number),
                        f"{number} is missing from {finding!r}",
                    )
                carry_on = [
                    line
                    for line in self._route_lines(card)
                    if self._quotes(line, distinct)
                ]
                self.assertTrue(
                    carry_on,
                    "no route offers to continue on the questions the rows "
                    f"resolve: {self._route_lines(card)}",
                )
                for line in self._route_lines(card):
                    self.assertFalse(
                        self._quotes(line, scoreable),
                        "a route is offered on the row count, which is the "
                        f"count this finding says overstates it: {line!r}",
                    )

    def test_the_finding_counts_the_rows_it_says_it_counts(self) -> None:
        """The population named in the sentence is the population counted.

        `scoreable` is the rows this run can score, which on a half-annotated
        tuning side is fewer than the rows on it. Saying "rows to tune on"
        beside that number named the wrong set, in a change about naming the
        right one.
        """
        rows = self._rows(repeats=4, distinct=10)
        for index in range(6):
            rows.append(
                {
                    "id": f"silent-{index}",
                    "input": f"an unlabelled question numbered {index}",
                    "source": "collected",
                    "split": "tuning",
                }
            )
        card = self._card(rows)
        finding = next(
            line for line in card.splitlines() if MODULE.REPEATED_ROWS_LABEL in line
        )
        self.assertTrue(self._quotes(finding, 14), finding)
        self.assertFalse(
            self._quotes(finding, 20),
            f"the finding counts 14 rows and names 20 of them: {finding!r}",
        )

    # ---- when the block appears at all

    def test_a_dataset_with_nothing_repeated_is_asked_nothing(self) -> None:
        """The block is a finding, so its absence is the ordinary card."""
        card = self._card(self._clean_rows())
        self.assertNotIn(MODULE.REPEATED_ROWS_LABEL, card)
        self.assertEqual(self._route_lines(card), [])

    def test_a_file_with_no_declared_split_is_asked_too(self) -> None:
        """Repetition is not a property of having declared a split.

        A customer who brought one flat file has the same defect and the same
        three answers to it, and the branch that scores them is a different one
        - so it is asserted separately rather than assumed to follow.
        """
        card = self._card(self._flat_rows())
        self.assertIn(MODULE.REPEATED_ROWS_LABEL, card)
        self.assertTrue(self._route_lines(card))

    def test_the_question_sits_below_every_result_it_follows(self) -> None:
        """Below the pillars AND below every ceiling, not merely below the top.

        A question printed before its own evidence asks a customer to answer
        before they have read anything. The ceilings are part of that evidence:
        a card that asks which examples to compare on above `FIX BEFORE PAID
        RUN` and three limits is asking them to choose while the reasons are
        still below the fold.

        EACH CAP IS FOUND BY ITS REASON, not by a rendered marker. The first
        version of this test looked for `LIMITED TO {ceiling}`, which the
        renderer prints only on the binding branch - every other cap renders
        `WOULD LIMIT TO n` or `FIX BEFORE PAID RUN`, and `LIMITED TO 89` is not
        a substring of `WOULD LIMIT TO 89`. So the guarded assertion ran zero
        times out of four while `assertTrue(score["caps"])` above it made the
        test look guarded, and the position mutation still passed. The reason
        is a field of the cap rather than a spelling of the card, so it is
        present however the line is labelled.
        """
        rows = self._rows()
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "dataset.jsonl", rows)
            records = _preflight_records(dataset)
        card = _card_records(records)
        score = _score_records(records)
        label_at = card.index(MODULE.REPEATED_ROWS_LABEL)
        for pillar in score["pillars"]:
            self.assertLess(card.index(pillar["name"].upper()), label_at)
        self.assertTrue(score["caps"], "this fixture is meant to carry ceilings")
        checked = 0
        for cap in score["caps"]:
            self.assertIn(
                cap["reason"],
                card,
                f"the cap {cap['condition']!r} is not on the card at all, so "
                "nothing here can say where the question sits relative to it",
            )
            self.assertLess(
                card.index(cap["reason"]),
                label_at,
                f"the question is printed above the ceiling {cap['condition']!r}",
            )
            checked += 1
        self.assertEqual(
            checked,
            len(score["caps"]),
            "not every cap was positioned against the question",
        )
        self.assertEqual(card.count(MODULE.REPEATED_ROWS_LABEL), 1)
        self.assertEqual(
            card.count(MODULE.RECOMMENDED_MARK),
            1,
            "the recommendation is marked more than once on one card",
        )

    def test_the_offer_route_a_points_at_is_printed_above_it(self) -> None:
        """Route A says "above", so the thing it names has to be above it.

        This is the position rule with teeth on it. Route A is deictic: it does
        not restate the bounded offer, it points at one, and a block rendered
        higher up the card would leave that sentence pointing upward at an
        offer printed below it. Nothing else in this suite ties the two
        together, so moving the block satisfied every other assertion.

        The cap is built by `power_ceiling`, the function that builds it in a
        real run, so the sentence asserted here is the shipped remedy's own and
        not one invented by this test. A hand-written reason could carry any
        words at all and would prove nothing about what a customer reads.
        """
        finding = MODULE.RepeatedInputs(
            scoreable=16, distinct=12, side="on the tuning side"
        )
        cap = MODULE.power_ceiling(12, 16, available_rows=16)
        self.assertIsNotNone(cap)
        self.assertTrue(cap.asks, "this fixture is meant to reach the asking arm")
        action, card = self._card_for([cap], finding)
        self.assertEqual(action, MODULE.ADD_EXAMPLES)
        offer = MODULE.top_up_offer(12, 16).strip()
        self.assertTrue(offer, "this fixture is meant to carry the bounded offer")
        sentence = offer.split(".")[0]
        self.assertIn(
            sentence,
            card,
            "the bounded offer is not on this card, so this test is not "
            "exercising the arm route A points at",
        )
        self.assertLess(
            card.index(sentence),
            card.index(MODULE.REPEATED_ROWS_LABEL),
            "route A points upward at an offer printed below it",
        )
        # And the route that points at it is the one that is actually there.
        self.assertTrue(self._route_lines(card)[0].startswith("A."))


class RepeatedRowsAreCappedOnTheirOwnAccountTests(unittest.TestCase):
    """#378: the same rows were stopped or cleared by their ids.

    Ninety rows, thirty of them exact repeats of another row. Preflight's only
    dataset FAIL was `dataset-ids`, the repetition itself only WARNed, and
    `dataset-shape` PASSed ninety valid rows - so the blocking readiness cap was
    `dataset-integrity-fail`, printing "some rows could not be read as data -
    malformed lines, or missing the input or expected-answer field" over a file
    where nothing was malformed and no field was missing. The same card said
    "90/90 rows carry an expected output" two lines above it.

    Renumbering the thirty ids and changing nothing else cleared the file
    completely. A duplicated export normally does renumber, so the commonest
    shape of the defect was the one that walked through.

    Driven end to end through both real scripts, because the finding is
    assembled from a preflight metric this branch adds and a readiness reason
    built out of it; hand-built facts on either side of that seam would test one
    half against a fixture of its own.
    """

    CATEGORIES = ("billing", "cancellation", "technical-support", "account")

    def _distinct(self) -> list[dict]:
        return [
            {
                "id": f"support-{index:03d}",
                "input": (
                    f"Ticket {index}: the customer writes about "
                    f"{self.CATEGORIES[index % len(self.CATEGORIES)]} "
                    "and asks what to do next."
                ),
                "output": self.CATEGORIES[index % len(self.CATEGORIES)],
                "source": "production-support-log",
                "difficulty": ("easy", "medium", "hard")[index % 3],
            }
            for index in range(1, 61)
        ]

    def _scored(self, *, renumber: bool) -> dict:
        """One file, thirty repeated rows, ids colliding or not.

        The two files differ in the `id` field of thirty rows and in nothing
        else. That is the whole experiment: the inputs, the answers, the
        provenance and the difficulty tags are byte-identical, so any difference
        in the payload is attributable to the ids alone.
        """
        distinct = self._distinct()
        repeats = [dict(row) for row in distinct[:30]]
        if renumber:
            for offset, row in enumerate(repeats, start=1):
                row["id"] = f"support-{60 + offset:03d}"
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "duplicated.jsonl", distinct + repeats)
            return _score(
                dataset,
                # The agent and the evaluation method are declared so the card
                # is about the DATASET. Their own absences cap lower and would
                # decide `recommended_action` on both sides.
                extra=(
                    "--evaluator-method",
                    "normalized-exact",
                    "--agent-origin",
                    "brought",
                    "--evaluator-origin",
                    "brought",
                ),
                preflight_extra=("--evaluator-method", "normalized-exact"),
            )

    def test_the_repetition_caps_whether_or_not_the_ids_collide(self) -> None:
        """The load-bearing test from the report, in both directions.

        The renumbered file is the one that used to be cleared, so it is the
        one that has to carry the finding now. The colliding file keeps it too:
        a cap that appeared only when the ids happened to agree would be the
        same accident with a new name.
        """
        for renumber in (False, True):
            with self.subTest(renumbered=renumber):
                score = self._scored(renumber=renumber)
                cap = _cap(score, "dataset-repeated-rows")
                self.assertFalse(cap["blocks"])
                self.assertTrue(cap["asks"])
                self.assertEqual(cap["action_kind"], "review-repeats")
                # The counts come out of the finding the card already prints,
                # so the cap and the routes below it cannot quote two numbers.
                self.assertEqual(
                    score["repeated_inputs"],
                    {"scoreable": 90, "distinct": 60, "side": "in your dataset"},
                )
                self.assertIn("30 of the 90 rows", cap["reason"])
                self.assertIn("resolves 60 different examples", cap["reason"])

    def test_the_renumbered_export_no_longer_walks_straight_through(self) -> None:
        """What the customer sees change, on the file that used to pass.

        Nothing about it blocks - the rows are real and a comparison over sixty
        different questions is worth making - so the change is in what the
        payload ASKS. `proceed` said there was nothing to answer while the card
        printed two routes to answer it.
        """
        score = self._scored(renumber=True)
        self.assertEqual(score["status"], "OK")
        self.assertEqual(score["recommended_action"], "review-repeats")
        self.assertNotIn(
            "dataset-integrity-fail",
            [cap["condition"] for cap in score["caps"]],
            "renumbering the ids repaired nothing about the rows",
        )

    def test_the_integrity_reason_names_the_ids_and_not_malformed_rows(
        self,
    ) -> None:
        """The customer-facing sentence that was false.

        Both halves are asserted. The new sentence has to name the collision and
        its count; the old one may not survive anywhere in it, because a reason
        that still mentions malformed lines sends a reader looking for lines
        that parse perfectly.
        """
        score = self._scored(renumber=False)
        cap = _cap(score, "dataset-integrity-fail")
        self.assertTrue(cap["blocks"])
        self.assertIn("30 ids are used by more than one row", cap["reason"])
        for absent in ("malformed", "missing the input", "could not be read as data"):
            with self.subTest(phrase=absent):
                self.assertNotIn(absent, cap["reason"])
        # And the card is no longer contradicting itself two lines apart.
        labels = _dataset_subscore(score, "labels")
        self.assertIn("90/90", labels["evidence"])

    def test_a_genuinely_malformed_row_still_reads_as_malformed(self) -> None:
        """The honest direction, so the reason is not simply reworded.

        A file with unreadable lines and unique ids must still be told that its
        lines are unreadable. Without this the fix would be a rename that moved
        the false sentence rather than removing it.
        """
        rows = self._distinct()
        with tempfile.TemporaryDirectory() as raw:
            dataset = Path(raw) / "broken.jsonl"
            dataset.write_text(
                "\n".join([json.dumps(row) for row in rows] + ["{not json at all"] * 10)
                + "\n"
            )
            score = _score(
                dataset,
                extra=("--agent-origin", "brought"),
            )
        cap = _cap(score, "dataset-integrity-fail")
        self.assertIn("could not be read as data", cap["reason"])
        self.assertIn("malformed lines", cap["reason"])
        self.assertNotIn("used by more than one row", cap["reason"])

    def test_a_file_with_no_repeats_carries_no_repetition_cap(self) -> None:
        """The false-red direction the cap would otherwise have.

        Sixty different questions, no repeats, everything else identical to the
        fixtures above. A cap that fires here would be reading something other
        than repetition, and the finding it is built from would be absent too.
        """
        with tempfile.TemporaryDirectory() as raw:
            dataset = _write_jsonl(Path(raw), "clean.jsonl", self._distinct())
            score = _score(
                dataset,
                extra=(
                    "--evaluator-method",
                    "normalized-exact",
                    "--agent-origin",
                    "brought",
                    "--evaluator-origin",
                    "brought",
                ),
                preflight_extra=("--evaluator-method", "normalized-exact"),
            )
        self.assertIsNone(score["repeated_inputs"])
        self.assertNotIn(
            "dataset-repeated-rows", [cap["condition"] for cap in score["caps"]]
        )


if __name__ == "__main__":
    unittest.main()

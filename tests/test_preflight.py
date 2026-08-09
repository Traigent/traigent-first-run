from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "traigent-first-run" / "scripts" / "preflight.py"
SPEC = importlib.util.spec_from_file_location("first_run_preflight", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def synthetic_rows() -> list[dict]:
    difficulties = ("easy", "medium", "hard", "very-hard")
    rows = []
    for index in range(24):
        rows.append(
            {
                "id": f"walkthrough-{index:02d}",
                "input": f"scenario_{index} unique_token_{index} format_{index % 5}",
                "output": {
                    "label": f"class-{index % 4}",
                    "reason": f"rule-{index % 3}",
                },
                "source": "synthetic",
                "difficulty": difficulties[index // 6],
                "coverage": f"scenario-{index % 8}",
                "split": "tune" if index < 18 else "holdout",
            }
        )
    return rows


class StaticPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        MODULE.RESULTS.clear()

    def test_process_environment_overrides_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("TRAIGENT_RUN_COST_LIMIT=2.00\n")
            with mock.patch.dict(
                os.environ, {"TRAIGENT_RUN_COST_LIMIT": "7.00"}, clear=False
            ):
                effective, file_values = MODULE.read_env(env_path)
            self.assertEqual(effective["TRAIGENT_RUN_COST_LIMIT"], "7.00")
            self.assertEqual(file_values["TRAIGENT_RUN_COST_LIMIT"], "2.00")

    def test_missing_custom_cost_limit_uses_sdk_default_without_warning(self) -> None:
        MODULE.check_cost_settings({}, {})
        cost_cap = next(
            result for result in MODULE.RESULTS if result.check == "cost-cap"
        )
        self.assertEqual(cost_cap.status, MODULE.PASS)
        self.assertIn("installed SDK default applies", cost_cap.detail)

    def test_sdk_check_accepts_only_the_tested_version(self) -> None:
        with mock.patch.object(
            MODULE, "version", return_value=MODULE.SUPPORTED_TRAIGENT_VERSION
        ):
            MODULE.check_sdk()
        result = next(item for item in MODULE.RESULTS if item.check == "sdk-version")
        self.assertEqual(result.status, MODULE.PASS)

    def test_sdk_check_can_defer_an_expected_preinstall_absence(self) -> None:
        with mock.patch.object(
            MODULE, "version", side_effect=MODULE.PackageNotFoundError
        ):
            MODULE.check_sdk(defer_missing=True)
        result = next(item for item in MODULE.RESULTS if item.check == "sdk-version")
        self.assertEqual(result.status, MODULE.SKIP)
        self.assertIn("after installation", result.detail)

    def test_sdk_check_still_fails_on_missing_sdk_without_defer(self) -> None:
        with mock.patch.object(
            MODULE, "version", side_effect=MODULE.PackageNotFoundError
        ):
            MODULE.check_sdk()
        result = next(item for item in MODULE.RESULTS if item.check == "sdk-version")
        self.assertEqual(result.status, MODULE.FAIL)

    def test_deferred_preinstall_pass_exits_zero_when_sdk_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                sys,
                "argv",
                [
                    str(SCRIPT),
                    "--env",
                    str(Path(directory) / ".env"),
                    "--defer-missing-sdk",
                    "--json",
                ],
            ), mock.patch.object(
                MODULE, "version", side_effect=MODULE.PackageNotFoundError
            ):
                with redirect_stdout(io.StringIO()):
                    exit_code = MODULE.main()
        self.assertEqual(exit_code, 0)

    @unittest.skipIf(os.name == "nt", "POSIX permissions are not available")
    def test_env_permissions_reject_group_or_world_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("OPENAI_API_KEY=\n")
            env_path.chmod(0o664)
            MODULE.check_env_permissions(env_path)
        result = next(
            item for item in MODULE.RESULTS if item.check == "env-permissions"
        )
        self.assertEqual(result.status, MODULE.FAIL)
        self.assertIn("0600", result.detail)

    @unittest.skipIf(os.name == "nt", "POSIX permissions are not available")
    def test_env_permissions_accept_owner_only_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("OPENAI_API_KEY=\n")
            env_path.chmod(0o600)
            MODULE.check_env_permissions(env_path)
        result = next(
            item for item in MODULE.RESULTS if item.check == "env-permissions"
        )
        self.assertEqual(result.status, MODULE.PASS)

    @unittest.skipIf(os.name == "nt", "POSIX permissions are not available")
    def test_env_permissions_reject_owner_execute_bits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("OPENAI_API_KEY=\n")
            env_path.chmod(0o700)
            MODULE.check_env_permissions(env_path)
        result = next(
            item for item in MODULE.RESULTS if item.check == "env-permissions"
        )
        self.assertEqual(result.status, MODULE.FAIL)
        self.assertIn("0700", result.detail)

    def test_sdk_check_rejects_obsolete_and_unvalidated_versions(self) -> None:
        for installed in ("0.0.1", "0.24.0", "0.25.1"):
            with self.subTest(installed=installed):
                MODULE.RESULTS.clear()
                with mock.patch.object(MODULE, "version", return_value=installed):
                    MODULE.check_sdk()
                result = next(
                    item for item in MODULE.RESULTS if item.check == "sdk-version"
                )
                self.assertEqual(result.status, MODULE.FAIL)
                self.assertIn("install traigent==0.26.0", result.detail)

    def test_provider_credentials_are_inventory_not_route_selection(self) -> None:
        MODULE.check_keys(
            {
                "OPENAI_API_KEY": "placeholder-openai",
                "ANTHROPIC_API_KEY": "placeholder-anthropic",
            }
        )
        result = next(
            item for item in MODULE.RESULTS if item.check == "provider-credentials"
        )
        self.assertEqual(result.status, MODULE.PASS)
        self.assertIn("OpenAI, Anthropic", result.detail)
        self.assertIn("does not select or change", result.detail)
        self.assertNotIn("select one", result.detail)

    def test_both_backend_origin_overrides_are_reported(self) -> None:
        """The SDK resolves its backend from either name, so one is not enough.

        `TRAIGENT_BACKEND_URL` was the only one named here, while the SDK falls
        back to `TRAIGENT_API_URL` and prefers either over the stored or default
        route. An unreported override sends a paid, portal-tracked run to a
        backend nobody approved - and it still looks connected, so the
        require-cloud guard in the wrapper does not catch it either.
        """
        for present, expected in (
            ({"TRAIGENT_BACKEND_URL": "https://example.invalid"}, ["TRAIGENT_BACKEND_URL"]),
            ({"TRAIGENT_API_URL": "https://example.invalid/api"}, ["TRAIGENT_API_URL"]),
            (
                {
                    "TRAIGENT_BACKEND_URL": "https://example.invalid",
                    "TRAIGENT_API_URL": "https://example.invalid/api",
                },
                ["TRAIGENT_BACKEND_URL", "TRAIGENT_API_URL"],
            ),
        ):
            with self.subTest(present=sorted(present)):
                MODULE.RESULTS.clear()
                MODULE.check_cost_settings(dict(present), {})
                result = next(
                    item for item in MODULE.RESULTS if item.check == "backend-url"
                )
                self.assertEqual(result.status, MODULE.WARN)
                for name in expected:
                    self.assertIn(name, result.detail)

        MODULE.RESULTS.clear()
        MODULE.check_cost_settings({}, {})
        self.assertEqual(
            [item for item in MODULE.RESULTS if item.check == "backend-url"],
            [],
            "a clean environment must not warn, or the warning means nothing",
        )

    def test_synthetic_dataset_quality_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text(
                "\n".join(json.dumps(row) for row in synthetic_rows()) + "\n"
            )
            rows = MODULE.check_dataset(dataset)
        self.assertIsNotNone(rows)
        failures = [result for result in MODULE.RESULTS if result.status == MODULE.FAIL]
        self.assertEqual(failures, [])
        tuning = next(
            result for result in MODULE.RESULTS if result.check == "dataset-tuning-size"
        )
        holdout = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-holdout-resolution"
        )
        self.assertEqual(tuning.status, MODULE.PASS)
        self.assertIn("18 tuning rows", tuning.detail)
        self.assertEqual(holdout.status, MODULE.WARN)
        self.assertIn("16.7 percentage points", holdout.detail)
        self.assertEqual(
            tuning.metrics, {"tuning_rows": 18, "tuning_labelled_rows": 18}
        )
        self.assertEqual(
            holdout.metrics, {"holdout_rows": 6, "holdout_labelled_rows": 6}
        )

    def test_tuning_only_dataset_is_not_reported_as_an_undeclared_split(self) -> None:
        rows = synthetic_rows()[:18]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)

        split = next(
            result for result in MODULE.RESULTS if result.check == "dataset-split"
        )
        tuning = next(
            result for result in MODULE.RESULTS if result.check == "dataset-tuning-size"
        )
        self.assertEqual(split.status, MODULE.PASS)
        self.assertEqual(
            split.detail,
            "tuning-only dataset; no held-out split was declared",
        )
        self.assertEqual(
            tuning.metrics, {"tuning_rows": 18, "tuning_labelled_rows": 18}
        )
        self.assertFalse(
            any(
                result.check == "dataset-holdout-resolution"
                for result in MODULE.RESULTS
            )
        )

    def test_split_metrics_count_labelled_rows_separately(self) -> None:
        """A holdout whose rows carry no expected output resolves nothing.

        The per-split labelled counts are what the readiness scorer clamps
        power on, so they must be reported next to the raw split sizes rather
        than inferred from the aggregate labelled count.
        """
        rows = [
            {
                "id": f"tune-{index}",
                "input": f"tuning case {index} token{index}",
                "output": f"answer {index % 3}",
                "split": "tune",
            }
            for index in range(8)
        ] + [
            {
                "id": f"holdout-{index}",
                "input": f"holdout case {index} othertoken{index}",
                "output": "",
                "split": "holdout",
            }
            for index in range(4)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        tuning = next(
            result for result in MODULE.RESULTS if result.check == "dataset-tuning-size"
        )
        holdout = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-holdout-resolution"
        )
        self.assertEqual(tuning.metrics, {"tuning_rows": 8, "tuning_labelled_rows": 8})
        self.assertEqual(
            holdout.metrics, {"holdout_rows": 4, "holdout_labelled_rows": 0}
        )
        self.assertEqual(tuning.status, MODULE.WARN)
        self.assertIn("8 tuning rows", tuning.detail)
        self.assertEqual(holdout.status, MODULE.WARN)
        self.assertIn("none scoreable", holdout.detail)
        self.assertNotIn("percentage points", holdout.detail)

    def test_holdout_resolution_quotes_only_scoreable_rows(self) -> None:
        """Per-example resolution is 100/scoreable, not 100/total.

        Quoting the total claims a precision the evaluator cannot deliver on
        the half of the holdout it cannot score at all.
        """
        rows = [
            {
                "id": f"tune-{index}",
                "input": f"tuning case {index} token{index}",
                "output": f"answer {index % 3}",
                "split": "tune",
            }
            for index in range(20)
        ] + [
            {
                "id": f"holdout-{index}",
                "input": f"holdout case {index} othertoken{index}",
                "output": f"answer {index % 3}" if index < 10 else "",
                "split": "holdout",
            }
            for index in range(20)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        holdout = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-holdout-resolution"
        )
        self.assertEqual(holdout.metrics["holdout_labelled_rows"], 10)
        self.assertEqual(holdout.metrics["holdout_rows"], 20)
        self.assertEqual(holdout.status, MODULE.PASS)
        self.assertIn("10.0 percentage points", holdout.detail)
        self.assertNotIn("5.0 percentage points", holdout.detail)

    def test_a_label_that_reads_none_is_still_a_label(self) -> None:
        """A label reading "None" is a class name, not a missing output.

        Stringifying the raw value before the emptiness test rendered the JSON
        null and the one-word label "None" as the same four characters, so a
        two-class dataset whose negative class is literally "None" - a
        no-intent class, or a pandas round-trip - read as entirely unlabelled
        and had its splits reported as half unscoreable.
        """
        self.assertTrue(MODULE.dataset_row_is_labelled({"output": "None"}))
        self.assertFalse(MODULE.dataset_row_is_labelled({"output": None}))
        self.assertFalse(MODULE.dataset_row_is_labelled({}))
        self.assertFalse(MODULE.dataset_row_is_labelled({"output": "   "}))

        rows = [
            {
                "id": f"intent-{index}",
                "input": f"utterance {index} token{index}",
                "output": "None" if index % 2 else "book_flight",
                "split": "tune" if index < 10 else "holdout",
            }
            for index in range(20)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        tuning = next(
            result for result in MODULE.RESULTS if result.check == "dataset-tuning-size"
        )
        holdout = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-holdout-resolution"
        )
        self.assertEqual(
            tuning.metrics, {"tuning_rows": 10, "tuning_labelled_rows": 10}
        )
        self.assertEqual(
            holdout.metrics, {"holdout_rows": 10, "holdout_labelled_rows": 10}
        )
        self.assertNotIn("scoreable", tuning.detail)
        self.assertNotIn("scoreable", holdout.detail)

    def test_a_json_null_expected_output_is_still_unlabelled(self) -> None:
        """The behaviour the "None" sentinel was protecting must survive.

        A row whose expected output is JSON `null` carries nothing to score
        against, so it must stay out of the labelled counts even though the
        predicate no longer looks at the stringified value.
        """
        rows = [
            {
                "id": f"tune-{index}",
                "input": f"tuning case {index} token{index}",
                "output": f"answer {index % 3}",
                "split": "tune",
            }
            for index in range(10)
        ] + [
            {
                "id": f"holdout-{index}",
                "input": f"holdout case {index} othertoken{index}",
                "output": None,
                "split": "holdout",
            }
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        holdout = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-holdout-resolution"
        )
        self.assertEqual(
            holdout.metrics, {"holdout_rows": 10, "holdout_labelled_rows": 0}
        )
        self.assertIn("none scoreable", holdout.detail)

    def test_combined_dataset_reports_a_small_tuning_split(self) -> None:
        rows = synthetic_rows()[:12]
        for index, row in enumerate(rows):
            row["split"] = "tune" if index < 8 else "holdout"
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        tuning = next(
            result for result in MODULE.RESULTS if result.check == "dataset-tuning-size"
        )
        self.assertEqual(tuning.status, MODULE.WARN)
        self.assertIn("8 tuning rows", tuning.detail)

    def test_ten_scoreable_rows_pass_only_the_static_wiring_boundary(self) -> None:
        """A preflight PASS must not read as a readiness-resolution verdict."""
        rows = [
            {
                "id": f"row-{index}",
                "input": f"case {index} token{index}",
                "output": f"answer {index % 3}",
                "split": "tune" if index < 10 else "holdout",
            }
            for index in range(20)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        tuning = next(
            result for result in MODULE.RESULTS if result.check == "dataset-tuning-size"
        )
        self.assertEqual(tuning.status, MODULE.PASS)
        self.assertIn("10-row static wiring boundary", tuning.detail)
        self.assertIn("readiness rates comparison size separately", tuning.detail)

    def test_missing_stable_ids_route_to_the_reversible_working_copy_repair(
        self,
    ) -> None:
        rows = [
            {
                "input": f"case {index} token{index}",
                "output": f"answer {index}",
                "source": "production",
            }
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        ids = next(result for result in MODULE.RESULTS if result.check == "dataset-ids")
        self.assertEqual(ids.status, MODULE.WARN)
        self.assertIn("add stable ids in a working copy", ids.detail)
        self.assertIn("before excluding rows or selecting a bounded subset", ids.detail)
        self.assertIn("re-run validation", ids.detail)

    def test_id_repair_includes_unlabelled_rows_and_whitespace_ids(self) -> None:
        rows = [
            {
                "id": f"row-{index}",
                "input": f"labelled case {index}",
                "output": f"answer {index}",
                "source": "production",
            }
            for index in range(10)
        ] + [
            {"id": "   ", "input": "unlabelled whitespace id", "source": "production"},
            {"input": "unlabelled missing id", "source": "production"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        ids = [result for result in MODULE.RESULTS if result.check == "dataset-ids"]
        self.assertEqual(len(ids), 1)
        self.assertEqual(ids[0].status, MODULE.WARN)
        self.assertIn("2 rows at source lines [11, 12]", ids[0].detail)
        self.assertIn("add stable ids in a working copy", ids[0].detail)

    def test_generated_row_without_id_fails_inside_a_mixed_dataset(self) -> None:
        rows = [
            {
                "id": f"real-{index}",
                "input": f"collected case {index}",
                "output": f"answer {index}",
                "source": "production",
            }
            for index in range(9)
        ]
        rows.append(
            {
                "input": "generated case without an id",
                "output": "generated answer",
                "source": "synthetic",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        ids = next(result for result in MODULE.RESULTS if result.check == "dataset-ids")
        self.assertEqual(ids.status, MODULE.FAIL)
        self.assertIn("1 row at source line 10 has no stable id", ids.detail)
        self.assertIn("1 generated row requires an id", ids.detail)

    def test_duplicate_ids_include_unlabelled_rows(self) -> None:
        rows = [
            {
                "id": f"row-{index}",
                "input": f"labelled case {index}",
                "output": f"answer {index}",
                "source": "production",
            }
            for index in range(10)
        ]
        rows.append(
            {
                "id": "row-0",
                "input": "unlabelled duplicate",
                "source": "production",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        ids = [result for result in MODULE.RESULTS if result.check == "dataset-ids"]
        self.assertTrue(
            any(
                result.status == MODULE.FAIL and "row-0" in result.detail
                for result in ids
            ),
            ids,
        )

    def test_all_unlabelled_dataset_still_routes_missing_ids_to_repair(self) -> None:
        rows = [
            {"input": "first unlabelled case", "source": "production"},
            {"id": "kept", "input": "second unlabelled case", "source": "production"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        ids = next(result for result in MODULE.RESULTS if result.check == "dataset-ids")
        self.assertEqual(ids.status, MODULE.WARN)
        self.assertIn("source line 1", ids.detail)
        self.assertIn("before excluding rows or selecting a bounded subset", ids.detail)

    def test_explicit_local_quality_fields_do_not_rewrite_dataset(self) -> None:
        rows = [
            {
                "request.payload": "preserved side field",
                "request": {"payload": f"case {index}"},
                "reference": {"answer": f"answer {index}"},
                "id": f"case-{index}",
                "source": "reviewed",
                "metadata": {"rubric_branch": f"branch-{index % 3}"},
                "split": "tune" if index < 8 else "holdout",
            }
            for index in range(12)
        ]

        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            original_text = "\n".join(json.dumps(row) for row in rows) + "\n"
            dataset.write_text(original_text)
            normalized_rows = MODULE.check_dataset(
                dataset,
                input_field="request.payload",
                expected_field="reference.answer",
            )
            self.assertEqual(dataset.read_text(), original_text)

        self.assertEqual(len(normalized_rows or []), len(rows))
        self.assertFalse(
            any(result.status == MODULE.FAIL for result in MODULE.RESULTS),
            MODULE.RESULTS,
        )
        for index, row in enumerate(normalized_rows or []):
            with self.subTest(index=index):
                self.assertEqual(row["input"], f"case {index}")
                self.assertEqual(row["output"], f"answer {index}")
                self.assertEqual(row["id"], f"case-{index}")
                self.assertEqual(row["request.payload"], "preserved side field")
                self.assertEqual(
                    row["metadata"],
                    {"rubric_branch": f"branch-{index % 3}"},
                )

    def test_selected_local_quality_fields_must_exist(self) -> None:
        rows = [
            {
                "request": {},
                "reference": {"answer": "answer"},
            },
            {
                "request": {"payload": "case"},
                "reference": {},
            },
            {
                "request": {"payload": "valid"},
                "reference": {"answer": "valid"},
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            normalized_rows = MODULE.check_dataset(
                dataset,
                input_field="request.payload",
                expected_field="reference.answer",
            )

        self.assertEqual(len(normalized_rows or []), 1)
        integrity = next(
            result for result in MODULE.RESULTS if result.check == "dataset-integrity"
        )
        self.assertEqual(integrity.status, MODULE.FAIL)
        self.assertIn(
            "line 1: missing selected input field 'request.payload'", integrity.detail
        )
        self.assertIn(
            "line 2: missing selected expected-output field 'reference.answer'",
            integrity.detail,
        )

    def test_one_cause_is_reported_once_however_many_rows_share_it(self) -> None:
        """The detail grew with the file instead of with what is wrong with it.

        Readiness forwards this string verbatim onto the card, so six rows
        missing the same selected field printed that sentence six times - 347
        characters, one fact. Nothing there was wrong, only repeated; the
        remedy is to say each distinct cause once, keep the first line it was
        seen on so the file can be opened at it, and count the rest.
        """
        rows = [{"question": f"q{index}", "answer": f"a{index}"} for index in range(6)]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)

        integrity = next(
            result for result in MODULE.RESULTS if result.check == "dataset-integrity"
        )
        self.assertEqual(integrity.status, MODULE.FAIL)
        cause = "missing selected input field 'input'"
        self.assertEqual(integrity.detail.count(cause), 1)
        # The line to open, and how many others share the cause.
        self.assertIn(f"line 1 (+5 more): {cause}", integrity.detail)
        # Every row is still counted; only the repetition is gone.
        self.assertIn("6/6 rows (100.0%) are unusable", integrity.detail)
        self.assertLess(len(integrity.detail), 200)

    def test_distinct_causes_each_get_a_slot_rather_than_the_first_one_repeating(
        self,
    ) -> None:
        """The report cap now bounds causes, which is what a reader needs.

        Capping ROWS spent all five slots on whichever cause happened to come
        first, so a file with several different problems reported one of them.
        """
        rows = [
            '{"question": "q", "answer": "a"}',
            "not json at all",
            '["not", "an", "object"]',
            '{"input": "q"}',
            '{"question": "q2", "answer": "a2"}',
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(rows) + "\n")
            MODULE.check_dataset(dataset)

        detail = next(
            result for result in MODULE.RESULTS if result.check == "dataset-integrity"
        ).detail
        for cause in (
            "line 1 (+1 more): missing selected input field 'input'",
            "row is not an object",
            "invalid JSON",
        ):
            with self.subTest(cause=cause):
                self.assertIn(cause, detail)

    def test_dataset_normalization_contract_violation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text('{"input": "case", "output": "answer"}\n')
            with mock.patch.object(
                MODULE, "normalize_dataset_row", return_value=(None, None)
            ), self.assertRaisesRegex(
                RuntimeError, "dataset normalization returned no row without an error"
            ):
                MODULE.check_dataset(dataset)

    def test_default_local_fields_do_not_infer_sdk_aliases(self) -> None:
        row = {
            "input_data": {"message": "same"},
            "expected_output": "answer",
        }
        normalized, error = MODULE.normalize_dataset_row(row)
        self.assertIsNone(normalized)
        self.assertEqual(error, "missing selected input field 'input'")

        normalized, error = MODULE.normalize_dataset_row(
            row,
            input_field="input_data",
            expected_field="expected_output",
        )
        self.assertIsNone(error)
        self.assertEqual(normalized["input"], {"message": "same"})
        self.assertEqual(normalized["output"], "answer")

    def test_duplicate_synthetic_input_fails(self) -> None:
        rows = synthetic_rows()
        rows[1]["input"] = rows[0]["input"]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        failures = [
            result.check for result in MODULE.RESULTS if result.status == MODULE.FAIL
        ]
        self.assertIn("dataset-duplicates", failures)

    @staticmethod
    def _pairwise_near_duplicates(
        token_sets: list[set[str]], threshold: float = 0.9
    ) -> list[tuple[int, int]]:
        """The full O(n^2) scan, kept here as the oracle for the indexed join.

        This is the code the indexed join replaced. It stays in the tests
        because a similarity index that quietly misses pairs would be the same
        defect the index was written to remove - a check that reports clean
        without having looked - one layer further down.
        """
        pairs = []
        for left in range(len(token_sets)):
            for right in range(left + 1, len(token_sets)):
                union = token_sets[left] | token_sets[right]
                similarity = (
                    len(token_sets[left] & token_sets[right]) / len(union)
                    if union
                    else 1.0
                )
                if similarity >= threshold:
                    pairs.append((left + 1, right + 1))
        return pairs

    def test_indexed_near_duplicate_join_matches_the_pairwise_scan(self) -> None:
        """Exactness, on the shapes that break naive similarity indexes."""
        import random

        random.seed(20260806)
        vocabulary = [f"word{index}" for index in range(40)]
        for _ in range(200):
            token_sets = [
                set(random.sample(vocabulary, size))
                for size in (random.randint(0, 8) for _ in range(random.randint(0, 40)))
            ]
            pairs, complete = MODULE.near_duplicate_pairs(token_sets)
            self.assertTrue(complete)
            self.assertEqual(
                pairs,
                sorted(self._pairwise_near_duplicates(token_sets)),
                f"indexed join disagrees with the pairwise scan on {token_sets}",
            )

    def test_near_duplicates_are_still_checked_above_five_hundred_rows(self) -> None:
        """The check must not stop running as the dataset gets big.

        A 500-row ceiling used to turn this into SKIP, and nothing downstream
        told a SKIP from a pass - so a 5,000-row dataset silently lost
        duplicate detection at exactly the size where duplicates become likely.
        """
        rows = [
            {
                "id": f"real-{index}",
                "input": f"question {index} about topic {index} number {index}",
                "output": f"answer {index % 7}",
                "source": "production",
            }
            for index in range(900)
        ]
        # Row 2 repeats nine of row 1's ten tokens: Jaccard 9/10, at threshold.
        rows[0]["input"] = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        rows[1]["input"] = "alpha beta gamma delta epsilon zeta eta theta iota"
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        near = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-near-duplicates"
        )
        self.assertEqual(near.status, MODULE.WARN, near.detail)
        self.assertIn("(1, 2)", near.detail)

    def test_an_incomplete_near_duplicate_scan_is_skip_and_never_pass(self) -> None:
        """Out of budget with nothing found is unchecked, not clean."""
        token_sets = [{"a", "b", "c"} for _ in range(50)]
        pairs, complete = MODULE.near_duplicate_pairs(token_sets, max_work=0, limit=10)
        self.assertEqual(pairs, [])
        self.assertFalse(complete)

    def test_a_truncated_near_duplicate_scan_still_reports_its_findings(self) -> None:
        """Pairs found before the budget ran out are a finding, not a SKIP.

        The budget is in token operations, so it has to buy at least one whole
        comparison: a posting step plus both rows' token counts.
        """
        token_sets = [{"a", "b", "c"} for _ in range(50)]
        pairs, complete = MODULE.near_duplicate_pairs(token_sets, max_work=10, limit=10)
        self.assertTrue(pairs)
        self.assertFalse(complete)

    def test_the_budget_is_spent_on_the_work_and_not_on_the_pair_count(
        self,
    ) -> None:
        """The bound has to bound what the loop actually spends.

        It used to count distinct candidate PAIRS, which is not the cost: each
        pair is found with one posting-list step and then settled with a union
        and an intersection over both rows' whole token sets. So a few very
        long rows cost a great deal and counted as almost nothing. Measured on
        2,000 RAG-shaped rows of 300 tokens: 1.7M candidate pairs - 34% of a
        5,000,000 pair budget, so the bound never fired - and 1.03 billion
        token operations, which ran 45 s with no output and no timeout and then
        answered PASS. Trunk answered in 0.24 s.

        Asserted on the accounting rather than on a clock, which would be
        flaky. Three rows are three candidate pairs however long they are, so
        a budget of 100 stops this scan only if the row length is being
        charged for.
        """
        long_rows = [{f"token{index}" for index in range(1000)} for _ in range(3)]
        pairs, complete = MODULE.near_duplicate_pairs(long_rows, max_work=100)
        self.assertFalse(
            complete,
            "three 1,000-token rows are three candidate pairs and about six "
            "thousand token operations; a budget of 100 that still completes "
            "is counting pairs",
        )
        # The false-red direction: the same three pairs with short rows are
        # cheap, and must still finish inside the same budget.
        short_rows = [{"a", "b", "c"} for _ in range(3)]
        _pairs, short_complete = MODULE.near_duplicate_pairs(short_rows, max_work=100)
        self.assertTrue(short_complete)

    def test_one_row_is_not_charged_for_an_answer_spread_it_cannot_have(
        self,
    ) -> None:
        """Dominance needs two answers to be a statement about anything.

        One row's single answer holds 100% of the rows by arithmetic, and
        reporting that charged a 1-row dataset 6 of its 20 diversity points -
        14.0 against 20.0, dataset 64 against 71 - for a finding no dataset of
        that size can avoid, and told its owner to diversify answers they have
        one of. The row count IS the problem and `dataset-size` already says
        so, loudly.
        """
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "one.jsonl"
            dataset.write_text(
                json.dumps({"id": "r1", "input": "only question", "output": "only"})
                + "\n"
            )
            MODULE.check_dataset(dataset)
        checks = {result.check: result for result in MODULE.RESULTS}
        self.assertNotIn("dataset-ceiling-risk", checks)
        self.assertEqual(checks["dataset-outputs"].status, MODULE.PASS)
        self.assertIn("too few", checks["dataset-outputs"].detail)
        # And the size itself is still reported as the problem it is.
        self.assertEqual(checks["dataset-size"].status, MODULE.WARN)

    def test_two_identical_answers_are_still_a_finding(self) -> None:
        """The false-red direction: the guard is about one row, not about two."""
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "two.jsonl"
            dataset.write_text(
                "\n".join(
                    json.dumps(
                        {"id": f"r{index}", "input": f"question {index}", "output": "x"}
                    )
                    for index in range(2)
                )
                + "\n"
            )
            MODULE.check_dataset(dataset)
        checks = {result.check: result for result in MODULE.RESULTS}
        self.assertIn("dataset-ceiling-risk", checks)

    def test_an_exhausted_budget_emits_skip_rather_than_a_clean_result(self) -> None:
        """The one remaining way this check can fail to run must say so.

        Driven through `check_dataset` and not just the join, because the
        defect being guarded lived in the emit: the old ceiling produced a SKIP
        that nothing downstream distinguished from a pass. The budget is
        patched down rather than a pathological dataset built, so the test
        states the contract instead of the size at which it triggers.
        """
        rows = [
            {
                "id": f"real-{index}",
                # A shared vocabulary, so the filter admits candidate pairs and
                # the budget is actually consulted. The rows are not similar
                # enough to BE near-duplicates: the scan finds nothing, runs
                # out of budget, and must not call that clean.
                "input": f"alpha beta gamma delta token{index}",
                "output": f"answer {index % 4}",
                "source": "production",
            }
            for index in range(40)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            with mock.patch.object(MODULE, "MAX_NEAR_DUPLICATE_WORK", 0):
                MODULE.check_dataset(dataset)
        near = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-near-duplicates"
        )
        self.assertEqual(near.status, MODULE.SKIP, near.detail)
        self.assertIn("UNCHECKED", near.detail)
        self.assertNotIn("no high-similarity", near.detail)
        # And it must account for the wait, in terms of the dataset the reader
        # is holding. This is the one slow path in the script, so they have just
        # waited and are then told the check did not run; the detail has to name
        # what causes it or the pause reads as a hang. It must name BOTH causes:
        # the text used to name only a small vocabulary, and the slower way in
        # is long rows with an entirely ordinary one.
        self.assertIn("length of each one", near.detail)
        self.assertIn("vocabulary", near.detail)

    def test_corrupted_row_count_and_percentage_are_reported(self) -> None:
        valid_rows = [
            {"input": f"case {index}", "output": f"answer {index}"}
            for index in range(6)
        ]
        invalid_lines = [
            "{broken",
            json.dumps({"input": "missing output"}),
            json.dumps(["not", "an", "object"]),
            "{also broken",
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text(
                "\n".join([*(json.dumps(row) for row in valid_rows), *invalid_lines])
                + "\n"
            )
            rows = MODULE.check_dataset(dataset)
        self.assertEqual(len(rows or []), 6)
        integrity = next(
            result for result in MODULE.RESULTS if result.check == "dataset-integrity"
        )
        self.assertEqual(integrity.status, MODULE.FAIL)
        self.assertIn("4/10 rows (40.0%)", integrity.detail)

    def test_easy_only_real_dataset_warns_about_ceiling(self) -> None:
        rows = [
            {
                "id": f"real-{index}",
                "input": f"simple case {index}",
                "output": f"answer {index}",
                "difficulty": "easy",
            }
            for index in range(12)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        self.assertTrue(
            any(
                result.check == "dataset-difficulty"
                and result.status == MODULE.WARN
                and "ceiling effect" in result.detail
                for result in MODULE.RESULTS
            )
        )

    def test_dominant_expected_output_warns_about_hidden_failures(self) -> None:
        rows = [
            {
                "id": f"real-{index}",
                "input": f"case {index}",
                "output": "majority" if index < 9 else "minority",
            }
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        self.assertTrue(
            any(
                result.check == "dataset-ceiling-risk"
                and result.status == MODULE.WARN
                and "9/10" in result.detail
                for result in MODULE.RESULTS
            )
        )

    def test_total_answer_dominance_is_a_finding_not_an_unchecked_gap(self) -> None:
        """100% is the dominance check's worst case, not its absent case.

        `dataset-ceiling-risk` was raised only inside the `else` arm that runs
        when there is more than one distinct expected output. A dataset where
        EVERY answer is identical took the `len(output_counts) == 1` arm, which
        emitted `dataset-outputs` WARN and nothing else - so the one check that
        measures answer spread produced no record at the exact input it exists
        to catch.

        readiness.py reads a PASS on `dataset-outputs` as its witness that the
        spread was examined, so a WARN there left answer dominance reported as
        NEVER CHECKED, and an unmeasured sub-score drops out of the pillar
        average instead of deducting from it. The dataset with the worst
        possible answer spread therefore scored HIGHER than one with 90%
        dominance. Both records are asserted here, because either alone is
        satisfied by the shape that produced the inversion.
        """
        rows = [
            {"id": f"real-{index}", "input": f"case {index}", "output": "same"}
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        self.assertTrue(
            any(
                result.check == "dataset-outputs"
                and "every expected output is identical" in result.detail
                for result in MODULE.RESULTS
            ),
            "the degenerate-outputs finding is gone",
        )
        self.assertTrue(
            any(
                result.check == "dataset-ceiling-risk"
                and result.status == MODULE.WARN
                and "10/10" in result.detail
                and "100.0%" in result.detail
                for result in MODULE.RESULTS
            ),
            "total answer dominance raised no dominance record, so the score "
            "will report it as a check that never ran",
        )

    def test_dominant_structured_label_is_not_hidden_by_unique_reasons(self) -> None:
        rows = [
            {
                "id": f"real-{index}",
                "input": f"case {index}",
                "output": {
                    "label": "majority" if index < 9 else "minority",
                    "reason": f"unique reason {index}",
                },
            }
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        self.assertTrue(
            any(
                result.check == "dataset-ceiling-risk"
                and result.status == MODULE.WARN
                and "output field 'label'" in result.detail
                and "9/10" in result.detail
                for result in MODULE.RESULTS
            )
        )

    def test_explicit_nested_outcome_field_detects_nonstandard_schema(self) -> None:
        rows = [
            {
                "id": f"real-{index}",
                "input": f"case {index}",
                "output": {
                    "result": {
                        "priority": "normal" if index < 9 else "urgent",
                    },
                    "reason": f"unique reason {index}",
                },
            }
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset, "result.priority")
        self.assertTrue(
            any(
                result.check == "dataset-ceiling-risk"
                and "output field 'result.priority'" in result.detail
                for result in MODULE.RESULTS
            )
        )

    def test_preflight_does_not_mirror_sdk_call_binding(self) -> None:
        text = SCRIPT.read_text()
        for sdk_owned_detail in (
            "BaseEvaluator._should_expand_input_mapping",
            "InjectionMode",
            "dataset-binding",
            "scorer-signature",
            "Traigent 0.23",
            "--agent",
            "--scorer",
        ):
            self.assertNotIn(sdk_owned_detail, text)

    def test_local_model_check_does_not_open_a_socket(self) -> None:
        with mock.patch(
            "socket.socket.connect",
            side_effect=AssertionError("network access attempted"),
        ):
            MODULE.check_models(["openai/gpt-4o-mini"])
        self.assertFalse(any(result.status == MODULE.FAIL for result in MODULE.RESULTS))


class EvaluatorShapeCheckTests(unittest.TestCase):
    """traigent-first-run#133: a static, non-executing check on evaluator.py.

    `check_evaluator` only ever calls `ast.parse` on the file's text - it
    never imports, calls, or otherwise runs a line of it - so it can tell
    "present and parses" apart from "present but broken" and "absent"
    without touching whatever the file's own logic does. Whether a parseable
    file behaves like a real evaluator (for example, whether a constant-pass
    scorer's return ever depends on its input) is a behavioral question this
    check does not and cannot answer; that is `calibrate_evaluator.py`'s job,
    run separately and only after explicit approval.
    """

    def setUp(self) -> None:
        MODULE.RESULTS.clear()

    def _shape(self) -> dict:
        result = next(r for r in MODULE.RESULTS if r.check == "evaluator-shape")
        return {"status": result.status, **(result.metrics or {})}

    def test_absent_evaluator_file_is_reported_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            MODULE.check_evaluator(Path(directory) / "evaluator.py")
        shape = self._shape()
        self.assertEqual(shape["status"], MODULE.FAIL)
        self.assertFalse(shape["exists"])
        self.assertNotIn("parses", shape)

    def test_import_invalid_evaluator_fails_to_parse(self) -> None:
        """A syntax error is caught by `ast.parse` alone - nothing is run."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text("def score(output, expected:\n    return 1.0\n")
            MODULE.check_evaluator(path)
        shape = self._shape()
        self.assertEqual(shape["status"], MODULE.FAIL)
        self.assertTrue(shape["exists"])
        self.assertFalse(shape["parses"])

    def test_constant_pass_evaluator_parses_like_any_other_valid_python(self) -> None:
        """The static check cannot and does not claim to catch this.

        A constant-pass scorer is syntactically ordinary Python - it imports
        fine and has a plausible shape - so this check reports exactly what a
        real evaluator would report too: `parses: True`. Distinguishing the
        two requires observing behavior, which only calibration does.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text("def score(output, expected):\n    return 1.0\n")
            MODULE.check_evaluator(path)
        shape = self._shape()
        self.assertEqual(shape["status"], MODULE.PASS)
        self.assertTrue(shape["exists"])
        self.assertTrue(shape["parses"])

    def test_healthy_evaluator_parses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text(
                "def score(output, expected):\n"
                "    return 1.0 if output == expected else 0.0\n"
            )
            MODULE.check_evaluator(path)
        shape = self._shape()
        self.assertEqual(shape["status"], MODULE.PASS)
        self.assertTrue(shape["exists"])
        self.assertTrue(shape["parses"])

    def test_check_never_imports_the_file(self) -> None:
        """The check must not be trickable into executing the module.

        A module-level statement that raises on *import* (not on call) would
        surface as an exception here if this check ever imported the file
        instead of only parsing its syntax tree.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text(
                "raise RuntimeError('this must never execute during preflight')\n"
            )
            MODULE.check_evaluator(path)
        shape = self._shape()
        self.assertEqual(shape["status"], MODULE.PASS)
        self.assertTrue(shape["parses"])

    def test_a_file_the_parser_refuses_does_not_crash_the_run(self) -> None:
        """`ast.parse` refuses some input without raising `SyntaxError`.

        A ~50 KB file of chained unary operators makes CPython raise
        `MemoryError: Parser stack overflowed`. Uncaught, that ends the whole
        preflight process before it prints anything, so `--json` emits no
        JSON at all and the readiness scorer reading that stream gets
        nothing - a corrupted or oddly-formed file, not an exotic attack.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text("-" * 50_000 + "1\n")
            MODULE.check_evaluator(path)
        shape = self._shape()
        self.assertEqual(shape["status"], MODULE.FAIL)
        self.assertTrue(shape["exists"])
        self.assertFalse(shape["parses"])

    def test_the_whole_json_run_survives_a_file_the_parser_refuses(self) -> None:
        """The contract the crash actually broke: `--json` still emits JSON.

        Driven through the real CLI, because the defect was that the process
        died before reaching the `--json` print - which a direct call to
        `check_evaluator` alone would not have caught.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text("-" * 50_000 + "1\n")
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--evaluator",
                    str(path),
                    "--defer-missing-sdk",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
        self.assertIn(process.returncode, (0, 1), f"crashed: {process.stderr[-2000:]}")
        records = json.loads(process.stdout)
        shape = next(r for r in records if r["check"] == "evaluator-shape")
        self.assertEqual(shape["status"], MODULE.FAIL)
        self.assertFalse(shape["metrics"]["parses"])


class NoInternalFailureReachesTheUserAsATracebackTests(unittest.TestCase):
    """An unexpected error printed a traceback where the check results go.

    `main` handled the failures it could name and let every other one escape
    to the interpreter: exit 1, a stack naming this file, and no check output
    at all. The reader is running their first optimization; a defect in this
    script must not read as a defect in what they brought.
    """

    def _explode(self, error: BaseException) -> None:
        original = MODULE.check_python

        def boom() -> None:
            raise error

        MODULE.check_python = boom
        self.addCleanup(setattr, MODULE, "check_python", original)

    def test_an_unexpected_error_is_diagnosed_rather_than_dumped(self) -> None:
        for error in (KeyError("metrics"), TypeError("not subscriptable")):
            with self.subTest(error=type(error).__name__):
                self._explode(error)
                out, err = io.StringIO(), io.StringIO()
                with mock.patch.object(sys, "argv", ["preflight.py"]):
                    with redirect_stdout(out), redirect_stderr(err):
                        code = MODULE.main()
                self.assertEqual(code, MODULE.INTERNAL_ERROR_EXIT)
                self.assertEqual(out.getvalue(), "")
                self.assertIn(type(error).__name__, err.getvalue())
                self.assertNotIn("Traceback (most recent call last)", err.getvalue())

    def test_the_stack_is_still_available_to_whoever_is_fixing_it(self) -> None:
        stream = io.StringIO()
        code = MODULE.report_internal_error(
            "preflight.py",
            ValueError("boom"),
            environ={MODULE.TRACEBACK_ENV: "1"},
            stream=stream,
        )
        self.assertEqual(code, MODULE.INTERNAL_ERROR_EXIT)
        self.assertIn("ValueError: boom", stream.getvalue())

    def test_a_normal_run_is_untouched_by_the_boundary(self) -> None:
        """The false-red direction: nothing normal may be caught."""
        del MODULE.RESULTS[:]
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["preflight.py"]):
            with redirect_stdout(out), redirect_stderr(err):
                code = MODULE.main()
        self.assertIn(code, (0, 1))
        self.assertNotIn("internal error", err.getvalue())
        self.assertTrue(out.getvalue().strip())


if __name__ == "__main__":
    unittest.main()

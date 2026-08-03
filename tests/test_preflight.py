from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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
                self.assertIn("install traigent==0.25.0", result.detail)

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

        split = next(result for result in MODULE.RESULTS if result.check == "dataset-split")
        tuning = next(
            result for result in MODULE.RESULTS if result.check == "dataset-tuning-size"
        )
        self.assertEqual(split.status, MODULE.PASS)
        self.assertEqual(
            split.detail,
            "tuning-only dataset; no independent validation split was declared",
        )
        self.assertEqual(tuning.metrics, {"tuning_rows": 18, "tuning_labelled_rows": 18})
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


if __name__ == "__main__":
    unittest.main()

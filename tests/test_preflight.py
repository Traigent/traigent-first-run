from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
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

    def test_sdk_jsonl_input_and_expected_aliases_normalize_without_rewriting(
        self,
    ) -> None:
        rows = []
        expected_aliases = (
            "output",
            "expected",
            "expected_output",
            "answer",
            "target",
            "label",
        )
        for index, (input_alias, expected_alias) in enumerate(
            (
                (input_alias, expected_alias)
                for input_alias in ("input", "input_data")
                for expected_alias in expected_aliases
            )
        ):
            rows.append(
                {
                    input_alias: {"message": f"case {index}"},
                    expected_alias: f"answer {index}",
                    "id": f"alias-{index}",
                    "source": "reviewed",
                    "metadata": {"rubric_branch": f"branch-{index % 3}"},
                    "split": "tune" if index < 8 else "holdout",
                }
            )

        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            original_text = "\n".join(json.dumps(row) for row in rows) + "\n"
            dataset.write_text(original_text)
            normalized_rows = MODULE.check_dataset(dataset)
            self.assertEqual(dataset.read_text(), original_text)

        self.assertEqual(len(normalized_rows or []), len(rows))
        self.assertFalse(
            any(result.status == MODULE.FAIL for result in MODULE.RESULTS),
            MODULE.RESULTS,
        )
        for index, row in enumerate(normalized_rows or []):
            with self.subTest(index=index):
                self.assertEqual(row["input"], {"message": f"case {index}"})
                self.assertEqual(row["output"], f"answer {index}")
                self.assertEqual(row["id"], f"alias-{index}")
                self.assertEqual(
                    row["metadata"],
                    {"rubric_branch": f"branch-{index % 3}"},
                )

    def test_conflicting_sdk_jsonl_aliases_fail_closed(self) -> None:
        rows = [
            {
                "input": {"message": "canonical"},
                "input_data": {"message": "conflict"},
                "output": "answer",
            },
            {
                "input": {"message": "case"},
                "output": "canonical",
                "expected_output": "conflict",
            },
            {
                "input": {"message": "valid"},
                "output": "valid",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            normalized_rows = MODULE.check_dataset(dataset)

        self.assertEqual(len(normalized_rows or []), 1)
        integrity = next(
            result for result in MODULE.RESULTS if result.check == "dataset-integrity"
        )
        self.assertEqual(integrity.status, MODULE.FAIL)
        self.assertIn(
            "line 1: conflicting input fields: input, input_data", integrity.detail
        )
        self.assertIn(
            "line 2: conflicting expected-output fields: output, expected_output",
            integrity.detail,
        )

    def test_identical_sdk_jsonl_aliases_preserve_nonselected_side_fields(
        self,
    ) -> None:
        row = {
            "input": {"message": "same"},
            "input_data": {"message": "same"},
            "output": "answer",
            "expected_output": "answer",
            "metadata": {"rubric": "exact"},
        }
        normalized, error = MODULE.normalize_dataset_row(row)
        self.assertIsNone(error)
        self.assertEqual(
            normalized,
            {
                "input_data": {"message": "same"},
                "expected_output": "answer",
                "metadata": {"rubric": "exact"},
                "input": {"message": "same"},
                "output": "answer",
            },
        )

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

    def test_ast_binding_does_not_execute_module_top_level(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed.txt"
            agent = root / "agent.py"
            agent.write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('executed')\n"
                "def answer(question: str, tone: str = 'plain') -> str:\n"
                "    return question\n"
            )
            rows = [{"input": {"question": "hello"}, "output": "hello"}]
            MODULE.check_binding(rows, f"{agent}:answer")
            self.assertFalse(marker.exists())
            self.assertTrue(
                any(
                    result.check == "dataset-binding" and result.status == MODULE.PASS
                    for result in MODULE.RESULTS
                )
            )

    def test_required_agent_parameter_must_exist_in_every_dict_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text(
                "def answer(question: str, tone: str) -> str:\n" "    return question\n"
            )
            rows = [
                {"input": {"question": "hello", "tone": "plain"}, "output": "a"},
                {"input": {"question": "goodbye"}, "output": "b"},
            ]
            MODULE.check_binding(rows, f"{agent}:answer")
        self.assertTrue(
            any(
                result.check == "dataset-binding"
                and result.status == MODULE.FAIL
                and "rows [2]" in result.detail
                for result in MODULE.RESULTS
            )
        )

    def test_scalar_input_cannot_bind_multiple_required_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text(
                "def answer(question: str, tone: str) -> str:\n" "    return question\n"
            )
            rows = [{"input": "hello", "output": "a"}]
            MODULE.check_binding(rows, f"{agent}:answer")
        self.assertTrue(
            any(
                result.check == "dataset-binding" and result.status == MODULE.FAIL
                for result in MODULE.RESULTS
            )
        )

    def test_scalar_input_cannot_bind_required_keyword_only_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text(
                "def answer(message: str, *, locale: str) -> str:\n"
                "    return message\n"
            )
            rows = [{"input": "hello", "output": "a"}]
            MODULE.check_binding(rows, f"{agent}:answer")
        self.assertTrue(
            any(
                result.check == "dataset-binding"
                and result.status == MODULE.FAIL
                and "required keyword-only parameters: ['locale']" in result.detail
                for result in MODULE.RESULTS
            )
        )

    def test_scalar_input_allows_defaulted_keyword_only_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text(
                "def answer(message: str, *, locale: str = 'en') -> str:\n"
                "    return message\n"
            )
            rows = [{"input": "hello", "output": "a"}]
            MODULE.check_binding(rows, f"{agent}:answer")
        self.assertTrue(
            any(
                result.check == "dataset-binding" and result.status == MODULE.PASS
                for result in MODULE.RESULTS
            )
        )

    def test_top_level_self_or_cls_cannot_bind_scalar_input(self) -> None:
        for receiver in ("self", "cls"):
            with self.subTest(
                receiver=receiver
            ), tempfile.TemporaryDirectory() as directory:
                agent = Path(directory) / "agent.py"
                agent.write_text(
                    f"def answer({receiver}, query):\n" "    return query\n"
                )
                MODULE.check_binding(
                    [{"input": "hello", "output": "a"}], f"{agent}:answer"
                )
            self.assertTrue(
                any(
                    result.check == "dataset-binding"
                    and result.status == MODULE.FAIL
                    and "multiple required parameters" in result.detail
                    for result in MODULE.RESULTS
                )
            )
            MODULE.RESULTS.clear()

    def test_top_level_self_or_cls_is_required_for_mapping_input(self) -> None:
        for receiver in ("self", "cls"):
            with self.subTest(
                receiver=receiver
            ), tempfile.TemporaryDirectory() as directory:
                agent = Path(directory) / "agent.py"
                agent.write_text(
                    f"def answer({receiver}, query):\n" "    return query\n"
                )
                MODULE.check_binding(
                    [{"input": {"query": "hello"}, "output": "a"}],
                    f"{agent}:answer",
                )
            self.assertTrue(
                any(
                    result.check == "dataset-binding"
                    and result.status == MODULE.FAIL
                    and f"'{receiver}' is missing" in result.detail
                    for result in MODULE.RESULTS
                )
            )
            MODULE.RESULTS.clear()

    def test_single_parameter_receives_whole_mapping_when_name_is_absent(
        self,
    ) -> None:
        sources = {
            "regular": "def answer(payload):\n    return payload['message']\n",
            "positional-only": (
                "def answer(payload, /):\n    return payload['message']\n"
            ),
        }
        for label, source in sources.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                agent = Path(directory) / "agent.py"
                agent.write_text(source)
                MODULE.check_binding(
                    [{"input": {"message": "hello"}, "output": "hello"}],
                    f"{agent}:answer",
                )
            self.assertTrue(
                any(
                    result.check == "dataset-binding" and result.status == MODULE.PASS
                    for result in MODULE.RESULTS
                ),
                MODULE.RESULTS,
            )
            self.assertFalse(
                any(result.status == MODULE.FAIL for result in MODULE.RESULTS),
                MODULE.RESULTS,
            )
            MODULE.RESULTS.clear()

    def test_single_parameter_mixed_positional_and_keyword_mapping_rows_pass(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text("def answer(payload):\n    return payload\n")
            MODULE.check_binding(
                [
                    {"input": {"message": "whole mapping"}, "output": "a"},
                    {"input": {"payload": "keyword value"}, "output": "b"},
                ],
                f"{agent}:answer",
            )

        self.assertTrue(
            any(
                result.check == "dataset-binding" and result.status == MODULE.PASS
                for result in MODULE.RESULTS
            ),
            MODULE.RESULTS,
        )
        self.assertFalse(
            any(result.status == MODULE.FAIL for result in MODULE.RESULTS),
            MODULE.RESULTS,
        )

    def test_single_positional_only_parameter_receives_same_named_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text("def answer(payload, /):\n    return payload\n")
            signature = MODULE.parse_function_spec(f"{agent}:answer", "dataset-binding")
            self.assertIsNotNone(signature)
            self.assertFalse(
                MODULE.mapping_input_expands(signature, {"payload": "field value"})
            )
            MODULE.RESULTS.clear()
            MODULE.check_binding(
                [{"input": {"payload": "field value"}, "output": "field value"}],
                f"{agent}:answer",
            )

        self.assertFalse(
            any(result.status == MODULE.FAIL for result in MODULE.RESULTS),
            MODULE.RESULTS,
        )

    def test_parameter_injection_forces_grouped_and_flat_mapping_expansion(
        self,
    ) -> None:
        decorators = {
            "grouped": (
                "@traigent.optimize(\n"
                "    injection={'injection_mode': 'parameter', "
                "'config_param': 'config'}\n"
                ")\n"
            ),
            "flat": (
                "@traigent.optimize(\n"
                "    injection_mode='parameter', config_param='config'\n"
                ")\n"
            ),
            "enum": (
                "@traigent.optimize(\n"
                "    injection_mode=InjectionMode.PARAMETER, config_param='config'\n"
                ")\n"
            ),
            "options": (
                "@traigent.optimize(\n"
                "    injection=InjectionOptions(\n"
                "        injection_mode='parameter', config_param='config'\n"
                "    )\n"
                ")\n"
            ),
        }
        for label, decorator in decorators.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                agent = Path(directory) / "agent.py"
                agent.write_text(
                    "import traigent\n"
                    f"{decorator}def answer(payload, config=None):\n"
                    "    return payload['message']\n"
                )
                MODULE.check_binding(
                    [{"input": {"message": "hello"}, "output": "hello"}],
                    f"{agent}:answer",
                )
            failures = [
                result.detail
                for result in MODULE.RESULTS
                if result.check == "dataset-binding" and result.status == MODULE.FAIL
            ]
            self.assertTrue(
                any(
                    "input key 'message' matches no agent parameter" in detail
                    for detail in failures
                ),
                MODULE.RESULTS,
            )
            self.assertTrue(
                any(
                    "required agent parameter 'payload' is missing" in detail
                    for detail in failures
                ),
                MODULE.RESULTS,
            )
            MODULE.RESULTS.clear()

    def test_context_default_and_seamless_injection_keep_adaptive_mapping(
        self,
    ) -> None:
        decorators = {
            "default": "@traigent.optimize()\n",
            "flat-context": "@traigent.optimize(injection_mode='context')\n",
            "grouped-context": (
                "@traigent.optimize(injection={'injection_mode': 'context'})\n"
            ),
            "seamless": "@traigent.optimize(injection_mode='seamless')\n",
        }
        for label, decorator in decorators.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                agent = Path(directory) / "agent.py"
                agent.write_text(
                    "import traigent\n"
                    f"{decorator}def answer(payload):\n    return payload['message']\n"
                )
                MODULE.check_binding(
                    [{"input": {"message": "hello"}, "output": "hello"}],
                    f"{agent}:answer",
                )
            self.assertFalse(
                any(result.status == MODULE.FAIL for result in MODULE.RESULTS),
                MODULE.RESULTS,
            )
            MODULE.RESULTS.clear()

    def test_unresolved_optimize_injection_mode_fails_closed(self) -> None:
        decorators = {
            "flat": "@traigent.optimize(injection_mode=MODE)\n",
            "grouped": "@traigent.optimize(injection=INJECTION_OPTIONS)\n",
            "grouped-value": (
                "@traigent.optimize(injection={'injection_mode': MODE})\n"
            ),
        }
        for label, decorator in decorators.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                agent = Path(directory) / "agent.py"
                agent.write_text(
                    "import traigent\n"
                    f"{decorator}def answer(payload):\n    return payload['message']\n"
                )
                MODULE.check_binding(
                    [{"input": {"message": "hello"}, "output": "hello"}],
                    f"{agent}:answer",
                )
            self.assertTrue(
                any(
                    result.check == "dataset-binding"
                    and result.status == MODULE.FAIL
                    and "cannot be resolved statically" in result.detail
                    for result in MODULE.RESULTS
                ),
                MODULE.RESULTS,
            )
            MODULE.RESULTS.clear()

    def test_parameter_injection_same_key_regular_passes_positional_only_fails(
        self,
    ) -> None:
        sources = {
            "regular": (
                "import traigent\n"
                "@traigent.optimize(injection_mode='parameter')\n"
                "def answer(payload, config=None):\n"
                "    return payload\n"
            ),
            "positional-only": (
                "import traigent\n"
                "@traigent.optimize(injection_mode='parameter')\n"
                "def answer(payload, /, config=None):\n"
                "    return payload\n"
            ),
        }
        for label, source in sources.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                agent = Path(directory) / "agent.py"
                agent.write_text(source)
                MODULE.check_binding(
                    [{"input": {"payload": "field value"}, "output": "field value"}],
                    f"{agent}:answer",
                )
            failures = [
                result
                for result in MODULE.RESULTS
                if result.check == "dataset-binding" and result.status == MODULE.FAIL
            ]
            if label == "regular":
                self.assertEqual(failures, [], MODULE.RESULTS)
            else:
                self.assertTrue(
                    any("positional-only" in result.detail for result in failures),
                    MODULE.RESULTS,
                )
            MODULE.RESULTS.clear()

    def test_parameter_injection_multi_parameter_mapping_still_uses_keywords(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text(
                "import traigent\n"
                "@traigent.optimize(injection_mode='parameter')\n"
                "def answer(payload, tone='plain', config=None):\n"
                "    return f'{tone}: {payload}'\n"
            )
            MODULE.check_binding(
                [
                    {
                        "input": {"payload": "hello", "tone": "formal"},
                        "output": "formal: hello",
                    }
                ],
                f"{agent}:answer",
            )

        self.assertFalse(
            any(result.status == MODULE.FAIL for result in MODULE.RESULTS),
            MODULE.RESULTS,
        )

    def test_traigent_optimize_import_aliases_are_recognized(self) -> None:
        sources = {
            "module-alias": (
                "import traigent as tg\n"
                "@tg.optimize(injection_mode='parameter')\n"
                "def answer(payload, config=None):\n"
                "    return payload\n"
            ),
            "function-alias": (
                "from traigent.api.decorators import optimize as tune\n"
                "@tune(injection_mode='parameter')\n"
                "def answer(payload, config=None):\n"
                "    return payload\n"
            ),
        }
        for label, source in sources.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                agent = Path(directory) / "agent.py"
                agent.write_text(source)
                MODULE.check_binding(
                    [{"input": {"message": "hello"}, "output": "hello"}],
                    f"{agent}:answer",
                )
            self.assertTrue(
                any(result.status == MODULE.FAIL for result in MODULE.RESULTS),
                MODULE.RESULTS,
            )
            MODULE.RESULTS.clear()

    def test_unrelated_optimize_decorator_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text(
                "import unrelated_optimizer\n"
                "@unrelated_optimizer.optimize(injection_mode=DYNAMIC_MODE)\n"
                "def answer(payload):\n"
                "    return payload['message']\n"
            )
            MODULE.check_binding(
                [{"input": {"message": "hello"}, "output": "hello"}],
                f"{agent}:answer",
            )
        self.assertFalse(
            any(result.status == MODULE.FAIL for result in MODULE.RESULTS),
            MODULE.RESULTS,
        )

    def test_parameter_injection_validates_config_parameter(self) -> None:
        sources = {
            "missing": (
                "import traigent\n"
                "@traigent.optimize(injection_mode='parameter')\n"
                "def answer(question):\n"
                "    return question\n"
            ),
            "positional-only": (
                "import traigent\n"
                "@traigent.optimize(injection_mode='parameter')\n"
                "def answer(question, config, /):\n"
                "    return question\n"
            ),
            "dynamic": (
                "import traigent\n"
                "@traigent.optimize(\n"
                "    injection_mode='parameter', config_param=CONFIG_NAME\n"
                ")\n"
                "def answer(question, config=None):\n"
                "    return question\n"
            ),
            "mode-conflict": (
                "import traigent\n"
                "@traigent.optimize(\n"
                "    injection_mode='context',\n"
                "    injection={'injection_mode': 'parameter'}\n"
                ")\n"
                "def answer(question, config=None):\n"
                "    return question\n"
            ),
            "config-conflict": (
                "import traigent\n"
                "@traigent.optimize(\n"
                "    injection_mode='parameter', config_param='config',\n"
                "    injection={'injection_mode': 'parameter', "
                "'config_param': 'settings'}\n"
                ")\n"
                "def answer(question, config=None, settings=None):\n"
                "    return question\n"
            ),
        }
        for label, source in sources.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                agent = Path(directory) / "agent.py"
                agent.write_text(source)
                MODULE.check_binding(
                    [{"input": {"question": "hello"}, "output": "hello"}],
                    f"{agent}:answer",
                )
            self.assertTrue(
                any(result.status == MODULE.FAIL for result in MODULE.RESULTS),
                MODULE.RESULTS,
            )
            MODULE.RESULTS.clear()

    def test_injected_config_is_exempt_but_dataset_collision_fails(self) -> None:
        source = (
            "import traigent\n"
            "@traigent.optimize(injection_mode='parameter')\n"
            "def answer(question, config=None):\n"
            "    return question\n"
        )
        for label, input_data, should_fail in (
            ("valid", {"question": "hello"}, False),
            ("collision", {"question": "hello", "config": "user value"}, True),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                agent = Path(directory) / "agent.py"
                agent.write_text(source)
                MODULE.check_binding(
                    [{"input": input_data, "output": "hello"}],
                    f"{agent}:answer",
                )
            self.assertEqual(
                any(result.status == MODULE.FAIL for result in MODULE.RESULTS),
                should_fail,
                MODULE.RESULTS,
            )
            MODULE.RESULTS.clear()

    def test_parameter_injection_does_not_exempt_real_dataset_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text(
                "import traigent\n"
                "@traigent.optimize(injection_mode='parameter')\n"
                "def answer(question, tone, config=None):\n"
                "    return f'{tone}: {question}'\n"
            )
            MODULE.check_binding(
                [{"input": {"question": "hello"}, "output": "hello"}],
                f"{agent}:answer",
            )
        self.assertTrue(
            any(
                result.status == MODULE.FAIL and "'tone' is missing" in result.detail
                for result in MODULE.RESULTS
            ),
            MODULE.RESULTS,
        )

    def test_single_keyword_only_parameter_cannot_receive_mapping_positionally(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text("def answer(*, payload):\n    return payload\n")
            MODULE.check_binding(
                [{"input": {"message": "hello"}, "output": "hello"}],
                f"{agent}:answer",
            )

        self.assertTrue(
            any(
                result.check == "dataset-binding"
                and result.status == MODULE.FAIL
                and "agent has no positional parameter" in result.detail
                for result in MODULE.RESULTS
            ),
            MODULE.RESULTS,
        )

    def test_multi_parameter_mapping_still_expands_and_fails_missing_fields(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text(
                "def answer(payload, tone='plain'):\n"
                "    return f'{tone}: {payload}'\n"
            )
            MODULE.check_binding(
                [{"input": {"message": "hello"}, "output": "plain: hello"}],
                f"{agent}:answer",
            )

        failures = [
            result.detail
            for result in MODULE.RESULTS
            if result.check == "dataset-binding" and result.status == MODULE.FAIL
        ]
        self.assertTrue(
            any(
                "input key 'message' matches no agent parameter" in detail
                for detail in failures
            )
        )
        self.assertTrue(
            any(
                "required agent parameter 'payload' is missing from rows [1]" in detail
                for detail in failures
            )
        )

    def test_mapping_input_cannot_bind_required_positional_only_parameter(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text(
                "def answer(message, /, tone):\n" "    return f'{tone}: {message}'\n"
            )
            MODULE.check_binding(
                [
                    {
                        "input": {"message": "hello", "tone": "plain"},
                        "output": "plain: hello",
                    }
                ],
                f"{agent}:answer",
            )

        failures = [
            result.detail
            for result in MODULE.RESULTS
            if result.check == "dataset-binding" and result.status == MODULE.FAIL
        ]
        self.assertTrue(
            any(
                "required positional-only agent parameters: ['message']" in detail
                for detail in failures
            )
        )
        self.assertTrue(
            any(
                "input key 'message' targets a positional-only agent parameter"
                in detail
                for detail in failures
            )
        )
        self.assertFalse(
            any(
                result.check == "dataset-binding" and result.status == MODULE.PASS
                for result in MODULE.RESULTS
            )
        )

    def test_mapping_input_allows_omitted_defaulted_positional_only_parameter(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text(
                "def answer(prefix='default', /, *, message):\n"
                "    return f'{prefix}: {message}'\n"
            )
            MODULE.check_binding(
                [
                    {
                        "input": {"message": "hello"},
                        "output": "default: hello",
                    }
                ],
                f"{agent}:answer",
            )

        self.assertTrue(
            any(
                result.check == "dataset-binding" and result.status == MODULE.PASS
                for result in MODULE.RESULTS
            ),
            MODULE.RESULTS,
        )
        self.assertFalse(
            any(result.status == MODULE.FAIL for result in MODULE.RESULTS),
            MODULE.RESULTS,
        )

    def test_mapping_input_cannot_supply_defaulted_positional_only_parameter(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Path(directory) / "agent.py"
            agent.write_text(
                "def answer(prefix='default', /, *, message):\n"
                "    return f'{prefix}: {message}'\n"
            )
            MODULE.check_binding(
                [
                    {
                        "input": {"prefix": "custom", "message": "hello"},
                        "output": "custom: hello",
                    }
                ],
                f"{agent}:answer",
            )

        self.assertTrue(
            any(
                result.check == "dataset-binding"
                and result.status == MODULE.FAIL
                and "input key 'prefix' targets a positional-only agent parameter"
                in result.detail
                for result in MODULE.RESULTS
            ),
            MODULE.RESULTS,
        )
        self.assertFalse(
            any(
                result.check == "dataset-binding" and result.status == MODULE.PASS
                for result in MODULE.RESULTS
            )
        )

    def test_scorer_check_is_static_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed.txt"
            scorer = root / "scorer.py"
            scorer.write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('executed')\n"
                "def score(output, expected):\n"
                "    return 1.0 if output == expected else 0.0\n"
            )
            MODULE.check_scorer_signature(f"{scorer}:score")
            self.assertFalse(marker.exists())
            self.assertTrue(
                any(
                    result.check == "scorer-calibration"
                    and result.status == MODULE.SKIP
                    for result in MODULE.RESULTS
                )
            )

    def test_scorer_aliases_are_statically_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "scorer.py"
            scorer.write_text(
                "def score(prediction, reference):\n"
                "    return 1.0 if prediction == reference else 0.0\n"
            )
            MODULE.check_scorer_signature(f"{scorer}:score")
        self.assertTrue(
            any(
                result.check == "scorer-signature"
                and result.status == MODULE.PASS
                and "keyword aliases/context" in result.detail
                for result in MODULE.RESULTS
            )
        )

    def test_scorer_positional_fallbacks_are_statically_compatible(self) -> None:
        sources = {
            "positional-only": (
                "def score(prediction, reference, /):\n"
                "    return float(prediction == reference)\n"
            ),
            "arbitrary-names": (
                "def score(left, right):\n" "    return float(left == right)\n"
            ),
            "variadic": "def score(*values):\n    return 1.0\n",
            "zero-argument": "def score():\n    return 1.0\n",
        }
        for label, source in sources.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                scorer = Path(directory) / "scorer.py"
                scorer.write_text(source)
                MODULE.check_scorer_signature(f"{scorer}:score")
            self.assertTrue(
                any(
                    result.check == "scorer-signature"
                    and result.status == MODULE.PASS
                    and "positional fallback" in result.detail
                    for result in MODULE.RESULTS
                )
            )
            MODULE.RESULTS.clear()

    def test_async_scorer_is_statically_compatible_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "scorer.py"
            scorer.write_text(
                "async def score(actual_output, ground_truth, *, metadata):\n"
                "    return float(actual_output == ground_truth)\n"
            )
            MODULE.check_scorer_signature(f"{scorer}:score")
        self.assertTrue(
            any(
                result.check == "scorer-signature"
                and result.status == MODULE.PASS
                and "async result will be awaited" in result.detail
                for result in MODULE.RESULTS
            )
        )

    def test_scorer_that_sdk_cannot_bind_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scorer = Path(directory) / "scorer.py"
            scorer.write_text(
                "def score(*, unsupported_required):\n"
                "    return float(bool(unsupported_required))\n"
            )
            MODULE.check_scorer_signature(f"{scorer}:score")
        self.assertTrue(
            any(
                result.check == "scorer-signature"
                and result.status == MODULE.FAIL
                and "cannot bind" in result.detail
                for result in MODULE.RESULTS
            )
        )

    def test_local_model_check_does_not_open_a_socket(self) -> None:
        with mock.patch(
            "socket.socket.connect",
            side_effect=AssertionError("network access attempted"),
        ):
            MODULE.check_models(["openai/gpt-4o-mini"])
        self.assertFalse(any(result.status == MODULE.FAIL for result in MODULE.RESULTS))


if __name__ == "__main__":
    unittest.main()

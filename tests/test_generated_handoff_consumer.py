"""Measured generated baselines reach the real connected comparison boundary."""

from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import test_generate_adapter as adapter_tests

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "skills/traigent-first-run/assets/run_wrapper.py"
REFERENCE = ROOT / "skills/traigent-first-run/references/sdk-execution.md"


def consumer_namespace():
    tree = ast.parse(WRAPPER.read_text(encoding="utf-8"))
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_canonical_json", "load_baseline_transfer"}
    ]
    namespace = {"json": json, "math": math, "hashlib": hashlib, "Path": Path}
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), str(WRAPPER), "exec"),
        namespace,
    )
    return namespace


class GeneratedHandoffConsumerTests(unittest.TestCase):
    runtime_bridge = adapter_tests.CanonicalRuntimeOutcomeTests.runtime_bridge
    baseline_result = adapter_tests.CanonicalRuntimeOutcomeTests.baseline_result

    def test_preflight_uses_sdk_ids_without_changing_existing_alias_precedence(self):
        preflight = adapter_tests.MODULE.load_sibling("preflight")
        rows = [
            (index, {"input": str(index), "metadata": {"example_id": identity}})
            for index, identity in enumerate(("stable-a", "stable-b"), 1)
        ]
        with mock.patch.object(preflight, "RESULTS", []), contextlib.redirect_stdout(
            io.StringIO()
        ):
            preflight.emit_dataset_id_findings(rows)
            findings = [
                result for result in preflight.RESULTS if result.check == "dataset-ids"
            ]
        self.assertTrue(findings)
        self.assertTrue(all(result.status == "PASS" for result in findings))
        for row, expected in (
            ({"id": "old", "metadata": {"example_id": "sdk"}}, "old"),
            ({"metadata": {"id": "old", "example_id": "sdk"}}, "old"),
            ({"id": "", "metadata": {"example_id": "sdk"}}, ""),
            ({"metadata": {"id": None, "example_id": "sdk"}}, None),
        ):
            self.assertEqual(preflight.row_metadata_value(row, "id"), expected)

    def test_generated_cli_baseline_hands_off_without_any_provider_call(self):
        project = adapter_tests.Project(
            self,
            agent='def answer(text, model, temperature):\n    return {"result": {"label": text.split()[0]}}\n',
        )
        project.config["agent"]["calls_per_row"] = 0
        generated = project.generate()
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
        program = """
import runpy, socket, sys
from unittest.mock import patch
def forbidden(*args, **kwargs):
    raise AssertionError('This authored deterministic baseline must place no network call')
path = sys.argv[1]
sys.argv = [path, 'baseline']
with patch.object(socket.socket, 'connect', forbidden), patch.object(socket, 'getaddrinfo', forbidden):
    runpy.run_path(path, run_name='__main__')
"""
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(project.root),
            "TRAIGENT_SKIP_DOTENV": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "TRAIGENT_FIRST_RUN_COST_CEILING_USD": "1",
            "TRAIGENT_FIRST_RUN_COST_SPENT_USD": "0",
            "TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD": "0.001",
            "TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS": "120",
        }
        baseline = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                program,
                str(project.runs / "adapter_bridge.py"),
            ],
            cwd=project.root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
        document = json.loads((project.runs / "baseline-results.json").read_text())
        self.assertEqual(document["provider_calls"], 0)
        spec, _, _ = adapter_tests.MODULE.validate(project.config, project.root)
        runtime = adapter_tests.load_runtime("cli_handoff_reader")
        bridge = runtime.Bridge(spec, project.runs)
        _, examples = self.sdk_examples(bridge)
        trials, incumbent = self.restore(bridge, examples)
        self.assertEqual(len(trials), 2)
        self.assertEqual(incumbent.metrics, {"task_quality": 1.0})

    def restore(self, bridge, examples=None):
        if examples is None:
            examples = [
                SimpleNamespace(
                    input_data=row["input"],
                    expected_output=row["expected"],
                    metadata=row["metadata"],
                )
                for row in bridge.tuning_rows()
            ]
        name = bridge.spec["primary_metric"]["name"]
        return consumer_namespace()["load_baseline_transfer"](
            str(bridge.run_dir / "baseline-transfer.json"),
            bridge.spec["baseline"]["config"],
            {"knobs": bridge.spec["baseline"]["space"], "wired": [], "max_trials": 12},
            len(examples),
            "SDK byte hash is deliberately different",
            name,
            [{"name": name, "orientation": "maximize", "weight": 1.0}],
            baseline_results_path=str(bridge.run_dir / "baseline-results.json"),
            tuning_examples=examples,
        )

    def sdk_examples(self, bridge):
        path = bridge.run_dir / "tuning.jsonl"
        path.write_text(
            "".join(
                json.dumps(
                    {
                        "input": row["input"],
                        "expected_output": row["expected"],
                        "metadata": row["metadata"],
                    }
                )
                + "\n"
                for row in bridge.tuning_rows()
            ),
            encoding="utf-8",
        )
        program = """
import json, socket, sys
from unittest.mock import patch
def forbidden(*args, **kwargs):
    raise AssertionError('No provider or network is part of this handoff test')
with patch.object(socket.socket, 'connect', forbidden), patch.object(socket, 'getaddrinfo', forbidden):
    import traigent
    examples = traigent.Dataset.from_jsonl(sys.argv[1]).examples
    print('LOADED_ROWS=' + json.dumps([
        {'input_data': row.input_data, 'expected_output': row.expected_output,
         'metadata': row.metadata} for row in examples]))
"""
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(bridge.project_root),
            "TRAIGENT_DATASET_ROOT": str(bridge.project_root),
            "TRAIGENT_OFFLINE_MODE": "true",
            "TRAIGENT_SKIP_DOTENV": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        }
        result = subprocess.run(
            [sys.executable, "-B", "-c", program, str(path)],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        line = next(
            line
            for line in result.stdout.splitlines()
            if line.startswith("LOADED_ROWS=")
        )
        return path, [
            SimpleNamespace(**row) for row in json.loads(line.split("=", 1)[1])
        ]

    def test_real_generated_writer_to_sdk_loaded_rows_and_connected_fence(self):
        for shape in ("flat", "nested-combined"):
            with self.subTest(shape=shape), self.runtime_bridge() as (
                _,
                bridge,
                placed,
            ):
                bridge.spec["primary_metric"] = {
                    "name": "task_quality",
                    "orientation": "maximize",
                }
                original = bridge.tuning_rows()
                if shape == "flat":
                    source_rows = [
                        {
                            "input": row["input"],
                            "expected": row["expected"],
                            "metadata": row["metadata"],
                        }
                        for row in original
                    ]
                    bridge.spec["dataset"] = {
                        "path": "rows.jsonl",
                        "input": "input",
                        "expected": "expected",
                        "metadata": "metadata",
                        "id": "metadata.example_id",
                    }
                else:
                    source_rows = [
                        dict(row, split="tuning") for row in adapter_tests.ROWS
                    ]
                    source_rows.append(
                        {
                            "id": "heldout",
                            "payload": {"q": "do not grade"},
                            "gold": {"label": "never"},
                            "split": "holdout",
                        }
                    )
                    bridge.spec["dataset"]["split"] = "split"
                (bridge.project_root / "rows.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in source_rows),
                    encoding="utf-8",
                )
                status, document, _ = self.baseline_result(bridge)
                self.assertEqual(status, 0)
                self.assertEqual(len(placed), 4)
                tuning_path, examples = self.sdk_examples(bridge)
                restored, incumbent = self.restore(bridge, examples)
                self.assertEqual(len(restored), 2)
                self.assertEqual(incumbent.metrics, {"task_quality": 1.0})
                self.assertEqual(
                    len(placed), 4, "handoff must not call the agent again"
                )
                self.assertFalse((bridge.run_dir / "baseline-transfer.json").exists())
                self.assertNotIn("do not grade", json.dumps(document))
                text = REFERENCE.read_text(encoding="utf-8")
                fence = next(
                    source
                    for source in re.findall(r"```python\n(.*?)\n```", text, re.S)
                    if "baseline_trials, baseline_incumbent = load_baseline_transfer("
                    in source
                )
                prefix = []
                for node in ast.parse(fence).body:
                    prefix.append(node)
                    if (
                        isinstance(node, ast.Assign)
                        and isinstance(node.value, ast.Call)
                        and getattr(node.value.func, "id", None)
                        == "load_baseline_transfer"
                    ):
                        break
                namespace = consumer_namespace()
                digest = hashlib.sha256(tuning_path.read_bytes()).hexdigest()
                namespace.update(
                    {
                        "FIRST_RUN_PHASE": "connected",
                        "TUNING_DATASET": str(tuning_path),
                        "tuning_dataset_fingerprint": lambda path: hashlib.sha256(
                            Path(path).read_bytes()
                        ).hexdigest(),
                        "TUNING_DATASET_INITIAL_FINGERPRINT": digest,
                        "BASELINE_TRANSFER_FILE": str(
                            bridge.run_dir / "baseline-transfer.json"
                        ),
                        "BASELINE_RESULTS": str(
                            bridge.run_dir / "baseline-results.json"
                        ),
                        "BASELINE_CONFIG": bridge.spec["baseline"]["config"],
                        "BASELINE_SPACE": bridge.spec["baseline"]["space"],
                        "config_space_document": lambda space: {"knobs": space},
                        "PROBE_INPUTS": tuple(row.input_data for row in examples),
                        "TUNING_EXAMPLES": examples,
                        "PRIMARY_OBJECTIVE": SimpleNamespace(name="task_quality"),
                        "OBJECTIVE_SIGNATURE": [
                            {
                                "name": "task_quality",
                                "orientation": "maximize",
                                "weight": 1.0,
                            }
                        ],
                        "COST_REMOVAL_RECORD": None,
                    }
                )
                exec(
                    compile(
                        ast.Module(body=prefix, type_ignores=[]),
                        "<real-connected-fence>",
                        "exec",
                    ),
                    namespace,
                )
                self.assertEqual(
                    namespace["baseline_incumbent"].metrics, {"task_quality": 1.0}
                )

    def test_malformed_generated_envelopes_never_use_a_stale_sdk_transfer(self):
        with self.runtime_bridge() as (_, bridge, _):
            _, original, _ = self.baseline_result(bridge)
            path = bridge.run_dir / "baseline-results.json"
            stale = copy.deepcopy(original["comparison_transfer"])
            stale["format_version"] = 2
            stale["baseline_space"] = {
                "knobs": bridge.spec["baseline"]["space"],
                "wired": [],
                "max_trials": 12,
            }
            stale["tuning_fingerprint"] = "SDK byte hash is deliberately different"
            (bridge.run_dir / "baseline-transfer.json").write_text(json.dumps(stale))
            changes = [
                lambda doc: doc.update(complete=False),
                lambda doc: doc.pop("comparison_transfer"),
                lambda doc: doc.update(comparison_transfer=[]),
                lambda doc: doc.update(kind="unknown"),
                lambda doc: doc["comparison_transfer"].update(format_version=3.0),
                lambda doc: doc["comparison_transfer"].update(tuning_rows=True),
                lambda doc: doc["comparison_transfer"].update(
                    tuning_fingerprint="wrong"
                ),
                lambda doc: doc["comparison_transfer"].update(metric_name="accuracy"),
                lambda doc: doc["comparison_transfer"]["objective_signature"][0].update(
                    orientation="minimize"
                ),
                lambda doc: doc["comparison_transfer"]["trials"].pop(),
                lambda doc: doc["comparison_transfer"]["trials"].append(
                    copy.deepcopy(doc["comparison_transfer"]["trials"][0])
                ),
                lambda doc: doc["comparison_transfer"]["trials"][0][
                    "example_results"
                ].pop(),
            ]
            for bad in (float("nan"), float("inf"), True):
                changes.append(
                    lambda doc, value=bad: doc["comparison_transfer"]["trials"][0][
                        "example_results"
                    ][0]["metrics"].update(task_quality=value)
                )
            for index, change in enumerate(changes):
                with self.subTest(case=index):
                    document = copy.deepcopy(original)
                    change(document)
                    path.write_text(json.dumps(document))
                    with self.assertRaises(SystemExit):
                        self.restore(bridge)
            for raw in ("null", "[]", "{broken"):
                path.write_text(raw)
                with self.assertRaises(SystemExit):
                    self.restore(bridge)
            path.unlink()
            with self.assertRaises(SystemExit):
                self.restore(bridge)

    def test_current_sdk_result_uses_sdk_transfer_instead_of_old_bridge_evidence(self):
        with self.runtime_bridge() as (_, bridge, _):
            _, original, _ = self.baseline_result(bridge)
            payload = copy.deepcopy(original["comparison_transfer"])
            payload["format_version"] = 2
            payload["baseline_space"] = {
                "knobs": bridge.spec["baseline"]["space"],
                "wired": [],
                "max_trials": 12,
            }
            payload["tuning_fingerprint"] = "SDK byte hash is deliberately different"
            (bridge.run_dir / "baseline-transfer.json").write_text(json.dumps(payload))
            current_sdk = {
                "_schema_version": 2,
                "best_config": payload["incumbent_config"],
                "trials": payload["trials"],
            }
            path = bridge.run_dir / "baseline-results.json"
            path.write_text(json.dumps(current_sdk))
            trials, _ = self.restore(bridge)
            self.assertEqual(len(trials), 2)
            self.assertNotIn("baseline_producer", trials[0].metadata)
            current_sdk["best_config"] = {"model": "different"}
            path.write_text(json.dumps(current_sdk))
            with self.assertRaises(SystemExit):
                self.restore(bridge)


if __name__ == "__main__":
    unittest.main()

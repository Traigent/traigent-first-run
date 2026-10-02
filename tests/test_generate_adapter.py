"""The adapter generator: config in, a thin bridge out, the customer's code untouched.

What is pinned: generation is deterministic and preserves the customer's sources; nested field
paths and argument mappings reach the callables; every refusal happens before a file is written;
the shared runtime keeps the guarantees of the hand-adapted wrapper (its ledger is a syntax-tree
copy of the wrapper's, offline is enforced, the holdout file is never opened, an unsupported
transport is stopped on the first row); and the bridge's `score` meets the calibration contract.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "traigent-first-run"
SCRIPTS = SKILL / "scripts"
GENERATOR = SCRIPTS / "generate_adapter.py"
RUNTIME = SKILL / "assets" / "first_run_runtime.py"
SDK_EXECUTION = SKILL / "references" / "sdk-execution.md"
CALIBRATE = SCRIPTS / "calibrate_evaluator.py"

SPEC = importlib.util.spec_from_file_location("first_run_generate_adapter", GENERATOR)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

AGENT = """
import litellm


def answer(text, model="openai/m", temperature=0.0, *, suffix=""):
    reply = litellm.completion(
        model=model,
        temperature=temperature,
        messages=[{"role": "user", "content": text + suffix}],
        mock_response=text.split()[0],
    )
    return {"result": {"label": reply.choices[0].message.content}}
"""
EVALUATOR = """
def exact(output, expected):
    return 1.0 if output == expected else 0.0
"""
ROWS = [
    {"id": "a", "payload": {"q": "billing please"}, "gold": {"label": "billing"}},
    {"id": "b", "payload": {"q": "technical issue"}, "gold": {"label": "technical"}},
]


def base_config() -> dict:
    return {
        "schema_version": 1,
        "dataset": {
            "path": "rows.jsonl",
            "input": "payload.q",
            "expected": "gold.label",
            "id": "id",
        },
        "agent": {
            "callable": "agent:answer",
            "args": {
                "text": "$input",
                "model": "$config.model",
                "temperature": "$config.temperature",
            },
            "output_path": "result.label",
        },
        "evaluator": {
            "callable": "evaluator:exact",
            "args": {"output": "$output", "expected": "$expected"},
        },
        "baseline": {
            "config": {"model": "openai/m-small", "temperature": 0.0},
            "space": {
                "model": ["openai/m-small", "openai/m-large"],
                "temperature": [0.0],
            },
        },
    }


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Project:
    def __init__(
        self, test: unittest.TestCase, rows=ROWS, agent=AGENT, evaluator=EVALUATOR
    ):
        self.directory = tempfile.TemporaryDirectory()
        test.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name, "project").resolve()
        self.root.mkdir()
        (self.root / "agent.py").write_text(agent, encoding="utf-8")
        (self.root / "evaluator.py").write_text(evaluator, encoding="utf-8")
        (self.root / "rows.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        self.config = base_config()
        self.runs = self.root / "traigent-runs"

    def generate(self, run_dir: Path | None = None) -> subprocess.CompletedProcess:
        config = self.root.parent / "adapter.json"
        config.write_text(json.dumps(self.config), encoding="utf-8")
        if run_dir is not None:
            self.runs = run_dir
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(GENERATOR),
                "generate",
                "--config",
                str(config),
                "--project-root",
                str(self.root),
                *(["--run-dir", str(run_dir)] if run_dir else []),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def bridge(
        self, *arguments: str, env: dict | None = None
    ) -> subprocess.CompletedProcess:
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(self.root),
            "TRAIGENT_FIRST_RUN_COST_CEILING_USD": "1.00",
            "TRAIGENT_FIRST_RUN_COST_SPENT_USD": "0",
            "TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD": "0.001",
            "TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS": "120",
            **(env or {}),
        }
        return subprocess.run(
            [sys.executable, "-B", str(self.runs / "adapter_bridge.py"), *arguments],
            capture_output=True,
            text=True,
            env=environment,
            cwd=self.root,
            check=False,
        )


class GenerationTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        first = Project(self)
        self.assertEqual(first.generate().returncode, 0)
        second = Project(self)
        self.assertEqual(second.generate().returncode, 0)
        for name in ("adapter_bridge.py", "first_run_runtime.py", "config-space.json"):
            self.assertEqual(
                (first.runs / name).read_bytes(),
                (second.runs / name).read_bytes(),
                name,
            )

    def test_the_customers_sources_are_untouched_and_not_copied(self) -> None:
        project = Project(self)
        before = {
            n: sha(project.root / n) for n in ("agent.py", "evaluator.py", "rows.jsonl")
        }
        self.assertEqual(project.generate().returncode, 0)
        self.assertEqual(before, {n: sha(project.root / n) for n in before})
        bridge = (project.runs / "adapter_bridge.py").read_text(encoding="utf-8")
        self.assertNotIn("litellm", bridge)
        self.assertNotIn("def exact", bridge)
        self.assertIn("agent.py", bridge)
        self.assertEqual(sha(project.runs / "first_run_runtime.py"), sha(RUNTIME))

    def test_the_bridge_and_the_config_space_pass_the_existing_scans(self) -> None:
        project = Project(self)
        self.assertEqual(project.generate().returncode, 0)
        preflight = MODULE.load_sibling("preflight")
        tree = ast.parse(
            (project.runs / "adapter_bridge.py").read_text(encoding="utf-8")
        )
        self.assertEqual(preflight.candidate_execution_witnesses(tree), ())
        self.assertEqual(preflight.process_execution_witnesses(tree), ())
        document = json.loads(
            (project.runs / "config-space.json").read_text(encoding="utf-8")
        )
        self.assertEqual(document["wired"], ["model", "temperature"])

    def test_the_baseline_runs_nested_fields_through_the_bridge(self) -> None:
        project = Project(self)
        self.assertEqual(project.generate().returncode, 0)
        done = project.bridge("baseline")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        results = json.loads(
            (project.runs / "baseline-results.json").read_text(encoding="utf-8")
        )
        self.assertTrue(results["complete"])
        self.assertEqual([r["mean_score"] for r in results["results"]], [1.0, 1.0])
        self.assertEqual(
            [item["id"] for item in results["results"][0]["rows"]], ["a", "b"]
        )
        self.assertNotIn("billing please", json.dumps(results))
        self.assertIn("this process placed 4 provider call(s)", done.stdout)

    def test_the_probe_proves_a_wired_knob_without_a_key_or_network(self) -> None:
        project = Project(self)
        self.assertEqual(project.generate().returncode, 0)
        done = project.bridge("probe", env={})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        verdicts = json.loads(done.stdout)["wiring"]
        self.assertEqual(verdicts, {"model": "visible", "temperature": "not-searched"})

    def test_a_knob_the_agent_ignores_is_reported_not_credited(self) -> None:
        agent = AGENT.replace("model=model", 'model="fixed"')
        project = Project(self, agent=agent)
        self.assertEqual(project.generate().returncode, 0)
        done = project.bridge("probe")
        self.assertEqual(done.returncode, 3)
        self.assertEqual(json.loads(done.stdout)["wiring"]["model"], "ignored")


class RefusalTests(unittest.TestCase):
    def refused(self, project: Project) -> list[str]:
        done = project.generate()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertFalse(project.runs.exists(), "a refusal must write nothing")
        return json.loads(done.stdout)["refused"]

    def test_an_unknown_config_field_is_refused_by_name(self) -> None:
        project = Project(self)
        project.config["agent"]["colour"] = "red"
        self.assertTrue(any("agent.colour" in r for r in self.refused(project)))

    def test_a_mapping_that_does_not_fit_the_signature_is_refused(self) -> None:
        project = Project(self)
        project.config["agent"]["args"]["nope"] = "$input"
        self.assertTrue(any("no parameter nope" in r for r in self.refused(project)))
        project = Project(self)
        del project.config["agent"]["args"]["text"]
        self.assertTrue(any("requires text" in r for r in self.refused(project)))

    def test_an_evaluator_cannot_read_a_knob(self) -> None:
        project = Project(self)
        project.config["evaluator"]["args"]["expected"] = "$config.model"
        self.assertTrue(any("not available" in r for r in self.refused(project)))

    def test_a_positional_only_callable_is_refused(self) -> None:
        project = Project(
            self, evaluator="def exact(output, expected, /):\n    return 1.0\n"
        )
        self.assertTrue(any("positional-only" in r for r in self.refused(project)))

    def test_an_unsupported_transport_is_refused(self) -> None:
        project = Project(self, agent="import requests\n" + AGENT)
        reasons = self.refused(project)
        self.assertTrue(any("requests" in r and "ledger" in r for r in reasons))

    def test_a_transport_hidden_behind_a_project_module_is_refused(self) -> None:
        project = Project(self, agent="import helper\n" + AGENT)
        (project.root / "helper.py").write_text("import httpx\n", encoding="utf-8")
        self.assertTrue(any("httpx" in r for r in self.refused(project)))

    def test_an_evaluator_that_reaches_a_process_is_refused_even_through_a_helper(
        self,
    ) -> None:
        project = Project(self, evaluator="from helper import grade as exact\n")
        (project.root / "helper.py").write_text(
            "import subprocess\n\n\ndef grade(output, expected):\n"
            "    return float(subprocess.run(['true']).returncode == 0)\n",
            encoding="utf-8",
        )
        self.assertTrue(
            any("helper.py" in r and "containment" in r for r in self.refused(project))
        )

    def test_paths_outside_the_project_are_refused(self) -> None:
        project = Project(self)
        project.config["dataset"]["path"] = "../rows.jsonl"
        (project.root.parent / "rows.jsonl").write_text("{}\n", encoding="utf-8")
        self.assertTrue(any("outside the project" in r for r in self.refused(project)))
        project = Project(self)
        project.config["agent"]["callable"] = "../elsewhere.py:answer"
        self.assertTrue(any("outside the project" in r for r in self.refused(project)))

    def test_a_space_readiness_would_reject_is_refused(self) -> None:
        project = Project(self)
        project.config["baseline"]["wired"] = ["model", "tempratur"]
        self.assertTrue(
            any("readiness would refuse" in r for r in self.refused(project))
        )

    def test_repeated_values_and_a_config_off_the_space_are_refused(self) -> None:
        project = Project(self)
        project.config["baseline"]["space"]["model"] = [
            "openai/m-small",
            "openai/m-small",
        ]
        self.assertTrue(any("repeats a value" in r for r in self.refused(project)))
        project = Project(self)
        project.config["baseline"]["config"]["model"] = "m-other"
        self.assertTrue(any("not in its space" in r for r in self.refused(project)))

    def test_a_knob_no_argument_consumes_is_refused(self) -> None:
        project = Project(self)
        project.config["baseline"]["space"]["top_p"] = [0.1, 0.9]
        project.config["baseline"]["config"]["top_p"] = 0.1
        self.assertTrue(
            any("top_p" in r and "consume" in r for r in self.refused(project))
        )

    def test_a_singleton_knob_is_allowed_and_not_searched(self) -> None:
        project = Project(self)
        self.assertEqual(project.generate().returncode, 0)
        document = json.loads(
            (project.runs / "config-space.json").read_text(encoding="utf-8")
        )
        self.assertEqual(document["knobs"]["temperature"], [0.0])


class SuggestTests(unittest.TestCase):
    def test_suggestions_are_printed_and_nothing_is_written(self) -> None:
        project = Project(self)
        before = sorted(p.name for p in project.root.iterdir())
        done = subprocess.run(
            [
                sys.executable,
                "-B",
                str(GENERATOR),
                "suggest",
                "--project-root",
                str(project.root),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        found = json.loads(done.stdout)
        self.assertIn("payload.q", found["dataset"]["fields"])
        self.assertIn("id", found["dataset"]["id_candidates"])
        self.assertIn("gold.label", found["dataset"]["expected_candidates"])
        self.assertIn("suggestions only", found["note"])
        self.assertEqual(before, sorted(p.name for p in project.root.iterdir()))


class SharedRuntimeTests(unittest.TestCase):
    """The runtime keeps the wrapper's guarantees; these are the ones a bridge could lose."""

    @staticmethod
    def strip_docstrings(node: ast.AST) -> ast.AST:
        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body = child.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(getattr(body[0], "value", None), ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    child.body = body[1:] or [ast.Pass()]
        return node

    @staticmethod
    def bindings(tree: ast.Module) -> dict[str, ast.AST]:
        found: dict[str, ast.AST] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[node.name] = node
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                found[node.target.id] = node
            elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                found[node.targets[0].id] = node
        return found

    def test_the_ledger_is_a_syntax_tree_copy_of_the_wrappers(self) -> None:
        fence = re.findall(
            r"```python\n(.*?)\n```", SDK_EXECUTION.read_text(encoding="utf-8"), re.S
        )
        template = self.bindings(ast.parse(max(fence, key=len)))
        runtime = self.bindings(ast.parse(RUNTIME.read_text(encoding="utf-8")))
        shared = [
            "approved_usd",
            "provider_reported_cost",
            "require_untruncated_completion",
            "run_remaining_usd",
            "report_run_spend",
            "record_call_spend",
            "PRICED_REQUEST_KNOBS",
            "UNPRICED_KNOB_MARKERS",
            "worst_case_requests",
            "tracking_stopped",
            "reserve_call_spend",
            "settle_call_spend",
            "REJECTED_BEFORE_BILLING",
            "release_call_spend",
            "ledgered",
            "ledgered_async",
            "refuse_unless_it_fits",
        ]
        for name in shared:
            with self.subTest(name):
                self.assertIn(name, template)
                self.assertIn(name, runtime)
                self.assertEqual(
                    ast.dump(self.strip_docstrings(template[name])),
                    ast.dump(self.strip_docstrings(runtime[name])),
                    f"{name} drifted from references/sdk-execution.md; copy it, do not edit it here",
                )

    def test_the_split_names_match_preflights(self) -> None:
        preflight = MODULE.load_sibling("preflight")
        runtime = importlib.util.spec_from_file_location("rt", RUNTIME)
        module = importlib.util.module_from_spec(runtime)
        runtime.loader.exec_module(module)
        self.assertEqual(module.TUNING_SPLIT_NAMES, preflight.TUNING_SPLIT_NAMES)
        self.assertEqual(module.HOLDOUT_SPLIT_NAMES, preflight.HOLDOUT_SPLIT_NAMES)

    def test_offline_is_enforced_inside_the_agent_process(self) -> None:
        agent = (
            "import os\n\n\ndef answer(text, k=1):\n"
            "    return '|'.join([os.environ['TRAIGENT_OFFLINE_MODE'],"
            " str(len(os.environ.get('TRAIGENT_API_KEY', ''))),"
            " os.environ.get('TRAIGENT_BACKEND_URL', '')])\n"
        )
        rows = [{"payload": {"q": "x"}, "gold": {"label": "true|0|"}}]
        project = Project(self, agent=agent, rows=rows)
        project.config["dataset"].pop("id")
        project.config["agent"] = {
            "callable": "agent:answer",
            "args": {"text": "$input", "k": "$config.k"},
            "calls_per_row": 0,
        }
        project.config["baseline"] = {"config": {"k": 1}, "space": {"k": [1]}}
        self.assertEqual(project.generate().returncode, 0)
        done = project.bridge(
            "baseline",
            env={
                "TRAIGENT_API_KEY": "tk_synthetic_not_real",
                "TRAIGENT_BACKEND_URL": "https://example.invalid",
            },
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        results = json.loads(
            (project.runs / "baseline-results.json").read_text(encoding="utf-8")
        )
        self.assertEqual(results["results"][0]["mean_score"], 1.0)

    def test_the_holdout_file_is_never_opened_and_holdout_rows_are_dropped(
        self,
    ) -> None:
        rows = [
            {
                "id": "t",
                "split": "train",
                "payload": {"q": "billing a"},
                "gold": {"label": "billing"},
            },
            {
                "id": "h",
                "split": "holdout",
                "payload": {"q": "billing b"},
                "gold": {"label": "billing"},
            },
        ]
        project = Project(self, rows=rows)
        project.config["dataset"]["split"] = "split"
        project.config["dataset"]["holdout_path"] = "never-created.jsonl"
        self.assertEqual(project.generate().returncode, 0)
        done = project.bridge("baseline")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        results = json.loads(
            (project.runs / "baseline-results.json").read_text(encoding="utf-8")
        )
        self.assertEqual(results["tuning_rows"], 1)
        self.assertEqual([i["id"] for i in results["results"][0]["rows"]], ["t"])

    def test_an_agent_the_ledger_cannot_see_is_stopped_on_the_first_row(self) -> None:
        agent = "def answer(text, model='m', temperature=0.0):\n    return 'billing'\n"
        project = Project(self, agent=agent)
        self.assertEqual(project.generate().returncode, 0)
        done = project.bridge("baseline")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("transport is not supported", done.stdout + done.stderr)
        self.assertFalse((project.runs / "baseline-results.json").exists())

    def test_a_ceiling_the_sweep_cannot_fit_refuses_before_any_call(self) -> None:
        project = Project(self)
        self.assertEqual(project.generate().returncode, 0)
        done = project.bridge(
            "baseline", env={"TRAIGENT_FIRST_RUN_COST_CEILING_USD": "0.002"}
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("needs 4 provider calls", done.stdout + done.stderr)
        self.assertFalse((project.runs / "baseline-results.json").exists())

    def test_no_approval_means_no_run_and_mock_mode_is_refused(self) -> None:
        project = Project(self)
        self.assertEqual(project.generate().returncode, 0)
        done = project.bridge(
            "baseline", env={"TRAIGENT_FIRST_RUN_COST_CEILING_USD": ""}
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("is not set", done.stdout + done.stderr)
        done = project.bridge("baseline", env={"TRAIGENT_MOCK_LLM": "1"})
        self.assertIn("TRAIGENT_MOCK_LLM", done.stdout + done.stderr)

    def test_a_connected_phase_is_not_run_by_a_bridge(self) -> None:
        project = Project(self)
        self.assertEqual(project.generate().returncode, 0)
        done = project.bridge("baseline", env={"TRAIGENT_FIRST_RUN_PHASE": "connected"})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("local baseline", done.stdout + done.stderr)


def load_runtime(name: str = "rt"):
    spec = importlib.util.spec_from_file_location(name, RUNTIME)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ASYNC_AGENT = AGENT.replace("def answer", "async def answer").replace(
    "litellm.completion(", "await litellm.acompletion("
)


class FirstRunAuditTests(unittest.TestCase):
    """Regressions for the third external review: each fails on the code it was written against."""

    def refused(self, project: Project) -> list[str]:
        done = project.generate()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertFalse(project.runs.exists(), "a refusal must write nothing")
        return json.loads(done.stdout)["refused"]

    # P1a - async transports are intercepted
    def test_an_async_agent_is_recorded_by_the_probe_and_ledgered_by_the_baseline(
        self,
    ) -> None:
        project = Project(self, agent=ASYNC_AGENT)
        self.assertEqual(project.generate().returncode, 0)
        probe = project.bridge("probe")
        self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
        self.assertEqual(json.loads(probe.stdout)["wiring"]["model"], "visible")
        done = project.bridge("baseline")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("this process placed 4 provider call(s)", done.stdout)

    def test_the_probe_places_no_call_on_any_sync_or_async_transport(self) -> None:
        from unittest import mock
        import asyncio

        module = load_runtime("rt_probe")
        placed: list[str] = []

        def sync_call(*a, **k):
            placed.append("sync")

        async def async_call(*a, **k):
            placed.append("async")

        fake = type("L", (), {"completion": sync_call, "acompletion": async_call})
        from openai.resources.chat.completions import AsyncCompletions, Completions

        with mock.patch.object(Completions, "create", sync_call), mock.patch.object(
            AsyncCompletions, "create", async_call
        ):
            module.litellm = fake
            module.install_recorders()
            calls = [
                lambda: fake.completion(model="m"),
                lambda: asyncio.run(fake.acompletion(model="m")),
                lambda: Completions.create(object(), model="m"),
                lambda: asyncio.run(AsyncCompletions.create(object(), model="m")),
            ]
            for call in calls:
                with self.assertRaises(module._ProbeStop):
                    call()
        self.assertEqual(placed, [])
        self.assertEqual(len(module.PROBED_REQUESTS), 4)

    # P1b - the gold answer never reaches the agent
    def test_a_mapping_that_hands_the_agent_the_gold_answer_is_refused(self) -> None:
        for token in ("$expected", "$row", "$output"):
            with self.subTest(token):
                project = Project(self)
                project.config["agent"]["args"]["suffix"] = token
                self.assertTrue(
                    any(
                        "agent.args.suffix" in r and "refused" in r
                        for r in self.refused(project)
                    )
                )
        project = Project(self)
        project.config["dataset"][
            "input"
        ] = "gold"  # the input field contains the answer
        self.assertTrue(any("overlap" in r for r in self.refused(project)))

    def test_the_runtime_gives_the_agent_no_expected_answer_even_from_a_hand_made_spec(
        self,
    ) -> None:
        module = load_runtime("rt_gold")
        project = Project(self)
        self.assertEqual(project.generate().returncode, 0)
        spec = {
            "dataset": {},
            "agent": {
                "file": "agent.py",
                "function": "answer",
                "calls_per_row": 0,
                "args": {"text": "$expected"},
            },
            "evaluator": {},
        }
        bridge = module.Bridge(spec, project.runs)
        row = {"input": "i", "expected": "GOLD", "id": 0, "metadata": {}}
        with self.assertRaises(KeyError):
            bridge.agent_output(row, {})

    # P1c - a safety refusal halts the run
    def test_an_accounting_refusal_on_the_first_row_places_no_further_call(
        self,
    ) -> None:
        project = Project(self)
        project.config["evaluator"][
            "calls_per_row"
        ] = 1  # but the evaluator places none
        self.assertEqual(project.generate().returncode, 0)
        done = project.bridge("baseline")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("stopped before any further spend", done.stdout + done.stderr)
        self.assertIn("this process placed 1 provider call(s)", done.stdout)
        self.assertFalse((project.runs / "baseline-results.json").exists())

    def test_an_ordinary_agent_failure_still_counts_as_one_failed_row(self) -> None:
        agent = AGENT.replace(
            "reply = litellm",
            "if text.startswith('technical'):\n        raise ValueError('x')\n    reply = litellm",
        )
        project = Project(self, agent=agent)
        self.assertEqual(project.generate().returncode, 0)
        done = project.bridge("baseline")
        results = json.loads(
            (project.runs / "baseline-results.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [r["n_failed"] for r in results["results"]], [1, 1], done.stdout
        )
        self.assertEqual([r["n_scored"] for r in results["results"]], [1, 1])

    # P1d - the scan fails closed
    def test_a_hazard_beyond_the_scan_cap_is_a_refusal(self) -> None:
        project = Project(self, evaluator="import m1\n" + EVALUATOR)
        for index in range(1, 27):
            body = (
                f"import m{index + 1}\n"
                if index < 26
                else "import subprocess\nsubprocess.run(['true'])\n"
            )
            (project.root / f"m{index}.py").write_text(body, encoding="utf-8")
        self.assertTrue(any("was not inspected" in r for r in self.refused(project)))

    def test_an_unparseable_imported_module_is_a_refusal_naming_it(self) -> None:
        for role, key in (("evaluator", EVALUATOR), ("agent", AGENT)):
            with self.subTest(role):
                project = Project(
                    self,
                    **{role: "import helper\n" + key},
                )
                (project.root / "helper.py").write_text(
                    "def broken(:\n", encoding="utf-8"
                )
                self.assertTrue(
                    any(
                        "helper.py" in r and "not inspected" in r
                        for r in self.refused(project)
                    )
                )

    # P2
    def test_a_nested_run_directory_finds_the_project(self) -> None:
        project = Project(self)
        self.assertEqual(project.generate(project.root / "out" / "deep").returncode, 0)
        done = project.bridge("baseline")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_callable_in_a_package_keeps_its_relative_imports(self) -> None:
        project = Project(self)
        package = project.root / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "prompts.py").write_text("SUFFIX = '?'\n", encoding="utf-8")
        (package / "agent.py").write_text(
            AGENT.replace("import litellm", "import litellm\nfrom . import prompts")
            .replace('suffix=""', 'suffix=""')
            .replace("text + suffix", "text + suffix + prompts.SUFFIX"),
            encoding="utf-8",
        )
        project.config["agent"]["callable"] = "pkg.agent:answer"
        self.assertEqual(project.generate().returncode, 0)
        done = project.bridge("baseline")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_hung_async_request_is_interrupted_and_stays_on_the_ledger(self) -> None:
        import asyncio
        import time

        module = load_runtime("rt_hang")
        module.MODEL_REQUEST_TIMEOUT_SECONDS = 0.2
        module.UNTRACKED_CALL_COST_USD = 0.001
        module.RUN_COST_CEILING_USD = 1.0
        module.RUN_COST_REMAINING_USD = 1.0
        seen = {}

        async def hung(*a, **k):
            seen["timeout"] = k.get("timeout")
            await asyncio.sleep(30)

        def sync(*a, **k):
            seen["sync_timeout"] = k.get("timeout")
            return type("R", (), {})()

        fake = type(
            "L", (), {"completion": sync, "acompletion": hung, "num_retries": 0}
        )
        module.litellm = fake
        module.install_interceptors()
        began = time.monotonic()
        with self.assertRaises(asyncio.TimeoutError):
            asyncio.run(fake.acompletion(model="m"))
        self.assertLess(time.monotonic() - began, 10)
        self.assertEqual(seen["timeout"], 0.2)
        self.assertEqual(
            len(module.RUN_SPEND_USD), 1
        )  # billable until proven otherwise
        fake.completion(model="m")
        self.assertEqual(seen["sync_timeout"], 0.2)

    def test_the_runtime_and_the_guide_account_for_the_same_calls_the_same_way(
        self,
    ) -> None:
        """Behavioural parity: the guide's wrappers and the runtime's, run on one mocked script."""
        import asyncio
        import contextvars
        import threading

        fence = max(
            re.findall(
                r"```python\n(.*?)\n```",
                SDK_EXECUTION.read_text(encoding="utf-8"),
                re.S,
            ),
            key=len,
        )
        wanted = {
            "provider_reported_cost",
            "require_untruncated_completion",
            "run_remaining_usd",
            "worst_case_requests",
            "tracking_stopped",
            "reserve_call_spend",
            "settle_call_spend",
            "release_call_spend",
            "ledgered",
            "ledgered_async",
            "record_call_spend",
            "report_run_spend",
        }
        nodes = [
            n
            for n in ast.parse(fence).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name in wanted
            or isinstance(n, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(t, ast.Name)
                and t.id
                in {
                    "PRICED_REQUEST_KNOBS",
                    "UNPRICED_KNOB_MARKERS",
                    "REJECTED_BEFORE_BILLING",
                }
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
            )
        ]
        guide = {
            "__builtins__": __builtins__,
            "math": __import__("math"),
            "asyncio": asyncio,
            "RUN_SPEND_USD": [],
            "RUN_CALL_COSTS": [],
            "REJECTED_CALLS": [],
            "REFUSED_TRIAL_COSTS": [],
            "TRACKED_RUN": None,
            "LEDGER_LOCK": threading.Lock(),
            "INSIDE_THE_DOOR": contextvars.ContextVar("g", default=False),
            "UNTRACKED_CALL_COST_USD": 0.01,
            "RUN_COST_CEILING_USD": 1.0,
            "RUN_COST_SPENT_USD": 0.0,
            "RUN_COST_REMAINING_USD": 1.0,
            "litellm": type("L", (), {"num_retries": 0}),
            "annotations": None,
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "guide", "exec"), guide)
        runtime = load_runtime("rt_parity")
        runtime.UNTRACKED_CALL_COST_USD = 0.01
        runtime.RUN_COST_CEILING_USD = 1.0
        runtime.RUN_COST_SPENT_USD = 0.0
        runtime.RUN_COST_REMAINING_USD = 1.0
        runtime.litellm = guide["litellm"]

        class RateLimitError(Exception):
            pass

        def priced(cost):
            return type("R", (), {"usage": {"cost": cost}, "_hidden_params": {}})()

        def script(namespace):
            wrapped = namespace["ledgered"]
            outcomes = [
                lambda **k: priced(0.03),
                lambda **k: (_ for _ in ()).throw(RateLimitError("429")),
                lambda **k: (_ for _ in ()).throw(RuntimeError("boom")),
                lambda **k: type("R", (), {"usage": None, "_hidden_params": {}})(),
            ]
            for outcome in outcomes:
                try:
                    wrapped(outcome)(model="m", num_retries=2)
                except Exception:
                    pass
            try:
                wrapped(lambda **k: priced(0.01))(model="m", retry_policy={})
            except RuntimeError:
                pass
            return (
                [round(x, 6) for x in namespace["RUN_SPEND_USD"]],
                namespace["RUN_CALL_COSTS"][:],
                namespace["REJECTED_CALLS"][:],
            )

        expected = script(guide)
        actual = script(vars(runtime))
        self.assertEqual(actual, expected)
        self.assertEqual(
            len(expected[0]), 4
        )  # the script really placed and refused calls


class CalibrationContractTests(unittest.TestCase):
    """The bridge's `score` takes the four calibration keywords for any customer signature."""

    def test_a_two_argument_scorer_calibrates_through_the_bridge(self) -> None:
        project = Project(self)
        self.assertEqual(project.generate().returncode, 0)
        cases = [
            {
                "name": name,
                "expected": name,
                "probes": {
                    "good": name,
                    "equivalent_good": name,
                    "partial": "x",
                    "bad": "y",
                },
            }
            for name in ("billing", "account")
        ]
        case_file = project.root / "cases.json"
        case_file.write_text(json.dumps(cases), encoding="utf-8")
        done = subprocess.run(
            [
                sys.executable,
                "-B",
                str(CALIBRATE),
                "--scorer",
                f"{project.runs / 'adapter_bridge.py'}:score",
                "--import-root",
                str(project.root),
                "--cases",
                f"@{case_file}",
                "--allow-execution",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=project.root,
        )
        payload = json.loads(done.stdout)
        checks = payload["cases"][0]["checks"]
        self.assertTrue(checks["good_passes"] and checks["bad_fails"], checks)
        self.assertNotIn("keyword arguments output", done.stdout + done.stderr)

    def test_an_async_scorer_and_the_four_keywords_work_directly(self) -> None:
        evaluator = "async def exact(output, expected):\n    return 1.0 if output == expected else 0.0\n"
        project = Project(self, evaluator=evaluator)
        self.assertEqual(project.generate().returncode, 0)
        spec = importlib.util.spec_from_file_location(
            "bridge", project.runs / "adapter_bridge.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(
            module.score(output="x", expected="x", input_data="i", metadata=None), 1.0
        )
        self.assertEqual(
            module.score(output="x", expected="y", input_data="i", metadata={}), 0.0
        )

    def test_an_out_of_range_score_is_refused(self) -> None:
        project = Project(
            self, evaluator="def exact(output, expected):\n    return 2\n"
        )
        self.assertEqual(project.generate().returncode, 0)
        spec = importlib.util.spec_from_file_location(
            "bridge2", project.runs / "adapter_bridge.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.assertRaises(ValueError):
            module.score(output="x", expected="x", input_data="i")


if __name__ == "__main__":
    unittest.main()

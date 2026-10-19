"""The actual SDK import must preserve the wrapper's launch-only approval state."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "skills" / "traigent-first-run" / "assets" / "run_wrapper.py"


class WrapperEnvironmentTests(unittest.TestCase):
    def run_prefix(
        self, phase: str, timeout: str | None, *, traced=False, dotenv_disabled=None
    ):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runs = project / "traigent-runs"
            runs.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname='fixture'\n")
            (project / ".env").write_text(
                "TRAIGENT_API_KEY=dummy_key_stale_backend\n"
                "TRAIGENT_FIRST_RUN_PHASE=connected\n"
                "TRAIGENT_FIRST_RUN_COST_CEILING_USD=99\n"
                "TRAIGENT_FIRST_RUN_COST_SPENT_USD=88\n"
                "TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD=77\n"
                "TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS=5\n"
                "FIRST_RUN_FIXTURE_FILE_VALUE=loaded-before-imports\n"
            )
            # Compile unchanged source nodes with their original offsets and filename.
            # __file__ remains the customer's copied wrapper location for dotenv lookup.
            program = """import ast
import sys
from pathlib import Path
if sys.argv[2] == "traced" and sys.gettrace() is None:
    sys.settrace(lambda *_: None)
source = Path(sys.argv[1])
prefix = []
for node in ast.parse(source.read_text()).body:
    prefix.append(node)
    if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "OPTIMIZATION_TIMEOUT_SECONDS"
        for target in node.targets
    ):
        break
exec(compile(ast.Module(body=prefix, type_ignores=[]), str(source), "exec"), globals())
print("STATE=" + json.dumps({"timeout": BASELINE_TIMEOUT_SECONDS, "env": {name: os.environ.get(name) for name in (*APPROVED_FIGURE_NAMES, "TRAIGENT_API_KEY", "TRAIGENT_FIRST_RUN_PHASE", "TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS")}, "file_value": os.environ.get("FIRST_RUN_FIXTURE_FILE_VALUE"), "dotenv_disabled": os.environ.get("PYTHON_DOTENV_DISABLED"), "trace_active": sys.gettrace() is not None}))
"""
            script = runs / "wrapper_prefix.py"
            script.write_text(program)
            # Deny outbound sockets throughout the subprocess, including SDK imports.
            guard = project / "guard"
            guard.mkdir()
            (guard / "sitecustomize.py").write_text(
                "import socket\n"
                "def deny(*args, **kwargs):\n    raise RuntimeError('network denied')\n"
                "socket.socket.connect = deny\nsocket.getaddrinfo = deny\n"
            )
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(project),
                "PYTHONPATH": str(guard),
                "LITELLM_LOCAL_MODEL_COST_MAP": "true",
                "TRAIGENT_FIRST_RUN_PHASE": phase,
                "TRAIGENT_FIRST_RUN_COST_CEILING_USD": "2",
                "TRAIGENT_FIRST_RUN_COST_SPENT_USD": "0",
                "TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD": "0.01",
                "TRAIGENT_FIRST_RUN_CURRENT_MODEL": "openai/x",
                "TRAIGENT_FIRST_RUN_ALTERNATIVE_MODEL": "openai/y",
                "TRAIGENT_FIRST_RUN_STRONG_MODEL": "openai/z",
                "TRAIGENT_FIRST_RUN_CURRENT_PROVIDER": "openai",
            }
            # Preserve only the coverage runner's controls in this test subprocess.
            for name in ("COVERAGE_PROCESS_START", "COVERAGE_FILE"):
                if name in os.environ:
                    environment[name] = os.environ[name]
            if timeout is not None:
                environment["TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS"] = timeout
            if dotenv_disabled is not None:
                environment["PYTHON_DOTENV_DISABLED"] = dotenv_disabled
            return subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(script),
                    str(WRAPPER),
                    "traced" if traced else "plain",
                ],
                cwd=project,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_a_dotenv_timeout_cannot_authorize_a_baseline(self) -> None:
        done = self.run_prefix("baseline", None)
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(
            "TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS is required", done.stderr
        )

    def test_sdk_import_does_not_restore_dotenv_approval_or_credential(self) -> None:
        for phase, traced in (
            ("baseline", False),
            ("baseline", True),
            ("proof", False),
            ("proof", True),
        ):
            with self.subTest(phase=phase, traced=traced):
                done = self.run_prefix(phase, "600", traced=traced)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                line = next(
                    line
                    for line in done.stdout.splitlines()
                    if line.startswith("STATE=")
                )
                state = json.loads(line.removeprefix("STATE="))
                self.assertEqual(state["timeout"], None if phase == "proof" else 600.0)
                self.assertTrue(
                    all(value is None for value in state["env"].values()), state
                )
                self.assertEqual(state["file_value"], "loaded-before-imports")
                self.assertIsNone(state["dotenv_disabled"])
                if traced:
                    self.assertTrue(state["trace_active"])

    def test_existing_dotenv_preference_survives_real_traced_imports(self) -> None:
        for value in ("0", "1"):
            with self.subTest(value=value):
                done = self.run_prefix(
                    "baseline", "600", traced=True, dotenv_disabled=value
                )
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                line = next(
                    line
                    for line in done.stdout.splitlines()
                    if line.startswith("STATE=")
                )
                state = json.loads(line.removeprefix("STATE="))
                self.assertEqual(state["dotenv_disabled"], value)
                self.assertEqual(
                    state["file_value"],
                    "loaded-before-imports" if value == "0" else None,
                )

    def test_import_failure_restores_local_preference_and_leaves_connected_alone(
        self,
    ) -> None:
        import ast
        import builtins
        from unittest import mock

        tree = ast.parse(WRAPPER.read_text())
        guard = next(
            node
            for node in tree.body
            if isinstance(node, ast.If)
            and any(
                isinstance(child, ast.Name) and child.id == "_dotenv_disabled"
                for child in ast.walk(node)
            )
        )
        imports = next(
            node
            for node in tree.body
            if isinstance(node, ast.Try)
            and any(
                isinstance(child, ast.Import)
                and any(alias.name == "litellm" for alias in child.names)
                for child in ast.walk(node)
            )
        )
        program = compile(
            ast.Module(body=[guard, imports], type_ignores=[]), str(WRAPPER), "exec"
        )
        real_import = builtins.__import__
        for phase in ("baseline", "proof", "connected"):
            for initial in (None, "0", "1"):
                with self.subTest(phase=phase, initial=initial):
                    observed = []

                    def failing_import(name, *args, **kwargs):
                        if name == "litellm":
                            observed.append(os.environ.get("PYTHON_DOTENV_DISABLED"))
                            if phase == "connected":
                                os.environ["PYTHON_DOTENV_DISABLED"] = (
                                    "dependency-change"
                                )
                            raise ImportError("fixture import failure")
                        return real_import(name, *args, **kwargs)

                    environment = (
                        {} if initial is None else {"PYTHON_DOTENV_DISABLED": initial}
                    )
                    with mock.patch.dict(os.environ, environment, clear=True):
                        with mock.patch("builtins.__import__", failing_import):
                            with self.assertRaisesRegex(ImportError, "fixture import"):
                                exec(program, {"os": os, "FIRST_RUN_PHASE": phase})
                        self.assertEqual(
                            observed, [initial if phase == "connected" else "1"]
                        )
                        self.assertEqual(
                            os.environ.get("PYTHON_DOTENV_DISABLED"),
                            "dependency-change" if phase == "connected" else initial,
                        )


if __name__ == "__main__":
    unittest.main()

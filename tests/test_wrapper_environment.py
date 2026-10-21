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
    @staticmethod
    def run_prefix(
        phase: str,
        timeout: str | None,
        *,
        traced=False,
        dotenv_disabled=None,
        customer_dotenv=False,
        stop_at="OPTIMIZATION_TIMEOUT_SECONDS",
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
                # Launch inputs a stale file must not decide, measured live
                # before the snapshot existed: 23 against a comment forbidding
                # a raise without a newly scoped approval, and a model the
                # launching process never chose.
                "TRAIGENT_FIRST_RUN_ENHANCED_MAX_TRIALS=23\n"
                "TRAIGENT_FIRST_RUN_BASELINE_TRIALS=5\n"
                "TRAIGENT_FIRST_RUN_CURRENT_MODEL=openai/stale-from-dotenv\n"
                "TRAIGENT_FIRST_RUN_MODEL_REQUEST_TIMEOUT_SECONDS=7\n"
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
        isinstance(target, ast.Name) and target.id == sys.argv[4]
        for target in node.targets
    ):
        break
exec(compile(ast.Module(body=prefix, type_ignores=[]), str(source), "exec"), globals())
if sys.argv[3] == "customer-dotenv":
    # The customer's own agent module, whose import loads their .env. No flag
    # the wrapper sets reaches this call; only a present empty value survives it.
    # cwd is the fixture project root - NOT `source`, which is the shipped
    # wrapper asset and whose parent holds no .env, so resolving from it loaded
    # nothing and the assertion below passed over a call that did not happen.
    from dotenv import load_dotenv
    customer_env = Path.cwd() / ".env"
    assert customer_env.is_file(), customer_env
    assert load_dotenv(customer_env), "the customer .env must actually load"
launch = {name: globals().get(name) for name in (
    "ENHANCED_MAX_TRIALS", "BASELINE_TRIALS", "SELECTED_CURRENT_MODEL",
    "MODEL_REQUEST_TIMEOUT_SECONDS")}
print("STATE=" + json.dumps({"launch": launch, "timeout": BASELINE_TIMEOUT_SECONDS, "env": {name: os.environ.get(name) for name in (*APPROVED_FIGURE_NAMES, "TRAIGENT_API_KEY", "TRAIGENT_FIRST_RUN_PHASE", "TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS")}, "file_value": os.environ.get("FIRST_RUN_FIXTURE_FILE_VALUE"), "dotenv_disabled": os.environ.get("PYTHON_DOTENV_DISABLED"), "trace_active": sys.gettrace() is not None}))
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
                    "customer-dotenv" if customer_dotenv else "plain",
                    stop_at,
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
                # EMPTY, not absent, and that distinction is the fix. An
                # absent name is the one thing `load_dotenv` fills, so every
                # popped value came back the next time anything loaded `.env`
                # - the SDK at import, or a `load_dotenv()` in the customer's
                # own agent module, which no flag of ours reaches. A present
                # empty string survives both.
                self.assertTrue(
                    all(value == "" for value in state["env"].values()), state
                )
                self.assertEqual(state["file_value"], "loaded-before-imports")
                self.assertIsNone(state["dotenv_disabled"])
                if traced:
                    self.assertTrue(state["trace_active"])

    def test_a_customer_module_loading_dotenv_cannot_restore_the_removed_state(
        self,
    ) -> None:
        """#592's residual case, and the reason these names are blanked.

        `TRAIGENT_SKIP_DOTENV` disarms the SDK's own loader and the
        `PYTHON_DOTENV_DISABLED` window spans only the wrapper's own imports.
        Neither reaches a `load_dotenv()` inside the customer's agent module,
        which is ordinary in exactly these projects and is the case the issue
        names. While the wrapper POPPED these names that call put every one of
        them back, stale `.env` values and all - measured, not assumed. Blank
        is what survives it, because `load_dotenv` fills an absent name and
        leaves a present one alone.
        """
        done = self.run_prefix("baseline", "600", customer_dotenv=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        line = next(
            line for line in done.stdout.splitlines() if line.startswith("STATE=")
        )
        state = json.loads(line.removeprefix("STATE="))
        self.assertTrue(
            all(value == "" for value in state["env"].values()),
            "a customer load_dotenv() must not refill any of these: " + repr(state),
        )
        # Non-vacuity is asserted inside the subprocess: the fixture `.env`
        # must exist and `load_dotenv` must report that it read it, or the
        # run fails before reaching the assertion above. `file_value` is NOT
        # that control - the wrapper's own load at :42 already set it.
        self.assertEqual(state["file_value"], "loaded-before-imports")

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


class StaleDotenvCannotDecideWhatTheRunDoesTests(unittest.TestCase):
    """Every launch input comes from the launching process, not the project file.

    The three approved cost figures and the baseline timeout were captured
    before `load_dotenv` already. The rest were not: the trial caps, the
    per-request and optimization timeouts, the three model selections, the
    provider and the reasoning effort all read the MERGED environment, so a
    stale or attacker-writable `.env` supplied any the launching process left
    out. Measured on the fixture below before the snapshot existed, the file's
    `ENHANCED_MAX_TRIALS=23` won - against the comment beside that read saying
    raising it without a newly scoped approval is forbidden.

    Asserted through the real wrapper source in a subprocess with a real `.env`
    on disk, because the defect is in the ORDER of two reads and a unit test
    over either one alone cannot see it.
    """

    def test_the_file_decides_none_of_them(self) -> None:
        done = WrapperEnvironmentTests.run_prefix(
            "baseline", "600", stop_at="ENHANCED_MAX_TRIALS"
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        state = json.loads(
            next(
                line for line in done.stdout.splitlines() if line.startswith("STATE=")
            )[len("STATE=") :]
        )
        launch = state["launch"]
        # The file says 23, 5, openai/stale-from-dotenv and 7. The process said
        # none of them, so each must be the code's own default or its value.
        self.assertEqual(launch["ENHANCED_MAX_TRIALS"], 12)
        self.assertEqual(launch["BASELINE_TRIALS"], 12)
        self.assertEqual(launch["SELECTED_CURRENT_MODEL"], "openai/x")
        self.assertEqual(launch["MODEL_REQUEST_TIMEOUT_SECONDS"], 120.0)
        # And the file still loaded - otherwise this proves nothing about
        # precedence, only that the file was unreadable.
        self.assertEqual(state["file_value"], "loaded-before-imports")

"""The actual SDK import must preserve the wrapper's launch-only approval state."""

import ast
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
    def run_prefix(self, phase: str, timeout: str | None):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runs = project / "traigent-runs"
            runs.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname='fixture'\n")
            (project / ".env").write_text(
                "TRAIGENT_API_KEY=fixture-stale-value\n"
                "TRAIGENT_FIRST_RUN_PHASE=connected\n"
                "TRAIGENT_FIRST_RUN_COST_CEILING_USD=99\n"
                "TRAIGENT_FIRST_RUN_COST_SPENT_USD=88\n"
                "TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD=77\n"
                "TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS=5\n"
            )
            prefix = []
            for node in ast.parse(WRAPPER.read_text()).body:
                prefix.append(node)
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name)
                    and target.id == "OPTIMIZATION_TIMEOUT_SECONDS"
                    for target in node.targets
                ):
                    break
            program = ast.unparse(ast.Module(body=prefix, type_ignores=[]))
            program += '\nprint("STATE=" + json.dumps({"timeout": BASELINE_TIMEOUT_SECONDS, "env": {name: os.environ.get(name) for name in (*APPROVED_FIGURE_NAMES, "TRAIGENT_API_KEY", "TRAIGENT_FIRST_RUN_PHASE", "TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS")}}))\n'
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
            if timeout is not None:
                environment["TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS"] = timeout
            return subprocess.run(
                [sys.executable, "-B", str(script)],
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
        for phase in ("baseline", "proof"):
            with self.subTest(phase=phase):
                done = self.run_prefix(phase, "600")
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


if __name__ == "__main__":
    unittest.main()

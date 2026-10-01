"""The offline audit path and the interpreter finder.

Offline audit: preflight must not call an inherited `TRAIGENT_API_KEY` a key
"to be sent", because an offline run sends nothing. Interpreter finder: it
must return a supported interpreter's real path, resolve a symlink, skip the
project's own executables, and say one remedy when nothing qualifies.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "traigent-first-run" / "scripts"
FIND = SCRIPTS / "find_python.py"
SPEC = importlib.util.spec_from_file_location("first_run_find_python", FIND)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

SKILL = ROOT / "skills" / "traigent-first-run" / "SKILL.md"


def preflight(args: list[str], env: dict[str, str], cwd: str) -> list[dict]:
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPTS / "preflight.py"), *args, "--json"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(completed.stdout)


class OfflinePreflightTests(unittest.TestCase):
    KEY = "uk_inherited_not_real_123456"

    def run_with_key(self, *extra: str) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("OPENAI_API_KEY=sk-not-a-real-key\n")
            env_path.chmod(0o600)
            records = preflight(
                ["--env", str(env_path), "--defer-missing-sdk", *extra],
                {
                    "TRAIGENT_API_KEY": self.KEY,
                    "TRAIGENT_BACKEND_URL": "https://example.invalid/api",
                },
                directory,
            )
        return {record["check"]: record for record in records}

    def test_connected_run_still_names_where_an_inherited_key_goes(self) -> None:
        record = self.run_with_key()["traigent-key"]
        self.assertIn("to be sent to", record["detail"])

    def test_offline_run_never_says_an_inherited_key_is_to_be_sent(self) -> None:
        records = self.run_with_key("--offline")
        detail = records["traigent-key"]["detail"]
        self.assertNotIn("to be sent", detail)
        self.assertIn("offline audit", detail)
        self.assertIn("env -u TRAIGENT_API_KEY", detail)
        self.assertNotIn(self.KEY, json.dumps(records))
        self.assertNotIn("example.invalid", json.dumps(records))

    def test_offline_run_without_a_key_says_none_is_needed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("OPENAI_API_KEY=sk-not-a-real-key\n")
            env_path.chmod(0o600)
            records = preflight(
                ["--env", str(env_path), "--defer-missing-sdk", "--offline"],
                {},
                directory,
            )
        record = next(item for item in records if item["check"] == "traigent-key")
        self.assertIn("no Traigent key is used or needed", record["detail"])


class FindPythonTests(unittest.TestCase):
    def fake_run(self, versions: dict[str, dict]):
        def run(command, **kwargs):
            if command[1:3] == ["python", "find"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            answer = versions.get(command[0])
            if answer is None:
                raise FileNotFoundError(command[0])
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(answer) + "\n", stderr=""
            )

        return run

    def test_symlinked_interpreter_is_resolved_to_the_real_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory, "real", "python3.13")
            real.parent.mkdir()
            real.write_text("#!/bin/sh\n")
            real.chmod(0o755)
            link = Path(directory, "bin", "python3")
            link.parent.mkdir()
            link.symlink_to(real)
            run = self.fake_run(
                {
                    str(link): {
                        "ok": True,
                        "executable": str(link),
                        "version": "3.13.1",
                    }
                }
            )
            found = MODULE.find_python(
                which=lambda name: str(link) if name == "python3" else None, run=run
            )
        self.assertEqual(found["python"], str(real.resolve()))
        self.assertEqual(found["version"], "3.13.1")

    def test_unsupported_first_candidate_falls_through_to_a_supported_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            new, old = Path(directory, "py314"), Path(directory, "py312")
            for path in (new, old):
                path.write_text("")
                path.chmod(0o755)
            run = self.fake_run(
                {
                    str(new): {
                        "ok": False,
                        "executable": str(new),
                        "version": "3.14.0",
                    },
                    str(old): {"ok": True, "executable": str(old), "version": "3.12.4"},
                }
            )
            paths = {"python3": str(new), "python3.12": str(old)}
            found = MODULE.find_python(which=paths.get, run=run)
        self.assertEqual(found["version"], "3.12.4")
        self.assertEqual(found["via"], "python3.12")

    def test_an_interpreter_inside_the_project_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inner = Path(directory, "project", ".venv", "bin", "python3")
            inner.parent.mkdir(parents=True)
            inner.write_text("")
            inner.chmod(0o755)
            run = self.fake_run(
                {
                    str(inner): {
                        "ok": True,
                        "executable": str(inner),
                        "version": "3.12.4",
                    }
                }
            )
            found = MODULE.find_python(
                Path(directory, "project"),
                which=lambda name: str(inner) if name == "python3" else None,
                run=run,
            )
        self.assertIn("error", found)
        self.assertIn("inside the project", found["tried"][0])

    def test_nothing_found_gives_one_remedy(self) -> None:
        found = MODULE.find_python(which=lambda name: None, run=self.fake_run({}))
        self.assertEqual(found["error"], MODULE.REMEDY)
        self.assertIn("Install Python 3.13", found["error"])

    def test_the_real_script_answers_in_json(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(FIND)],
            capture_output=True,
            text=True,
            check=False,
        )
        answer = json.loads(completed.stdout)
        if completed.returncode == 0:
            self.assertTrue(os.path.isabs(answer["python"]))
            self.assertEqual(answer["python"], os.path.realpath(answer["python"]))
        else:
            self.assertIn("error", answer)


if __name__ == "__main__":
    unittest.main()

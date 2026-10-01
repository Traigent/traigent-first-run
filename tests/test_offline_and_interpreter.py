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
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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


FIXTURES = ROOT / "tests" / "fixtures"
SYNTHETIC_KEY = "uk_synthetic_not_real_0000"
DOTENV_KEY = "uk_dotenv_synthetic_not_real_1111"

# Runs preflight.py in-process after installing the socket guard, with a stand-in
# `litellm` first on the path. The stand-in does what LiteLLM does at import
# (python-dotenv's `load_dotenv(override=False)` on ./.env) and records what the
# process environment held at that instant, which is what the model-check step sees.
WRAPPER = textwrap.dedent("""
    import json, os, runpy, sys
    sys.path.insert(0, os.environ["WRAP_FIXTURES"])
    if os.environ.get("WRAP_STUB_DIR"):
        sys.path.insert(0, os.environ["WRAP_STUB_DIR"])
    import offline_socket_probe as guard
    guard.install_guard()
    if os.environ.get("WRAP_LEAK"):
        import socket
        try:
            socket.getaddrinfo("api.traigent.ai", 443)
        except OSError:
            pass
    try:
        runpy.run_path(os.environ["WRAP_PREFLIGHT"], run_name="__main__")
    except SystemExit:
        pass
    json.dump(
        {"attempts": guard.ATTEMPTS},
        open(os.environ["WRAP_OUT"] + ".attempts", "w"),
    )
    """)
STUB_LITELLM = textwrap.dedent("""
    import json, os
    for line in open(".env"):
        name, _, value = line.strip().partition("=")
        os.environ.setdefault(name, value)
    names = (
        "TRAIGENT_API_KEY", "TRAIGENT_BACKEND_URL", "TRAIGENT_API_URL",
        "TRAIGENT_OFFLINE_MODE", "LITELLM_LOCAL_MODEL_COST_MAP",
        "TRAIGENT_FIRST_RUN_PHASE",
    )
    json.dump(
        {name: os.environ.get(name) for name in names},
        open(os.environ["WRAP_OUT"], "w"),
    )
    def cost_per_token(**kwargs):
        return 0.0, 0.0
    """)


def run_wrapped(
    shell: dict[str, str],
    dotenv: str,
    args: list[str],
    *,
    stub: bool = True,
    leak: bool = False,
) -> tuple[dict, list]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / ".env").write_text(dotenv)
        (root / ".env").chmod(0o600)
        (root / "stubs").mkdir()
        if stub:
            (root / "stubs" / "litellm.py").write_text(STUB_LITELLM)
        (root / "wrap.py").write_text(WRAPPER)
        out = root / "snapshot.json"
        env = {
            "PATH": os.environ.get("PATH", ""),
            "WRAP_FIXTURES": str(FIXTURES),
            "WRAP_PREFLIGHT": str(SCRIPTS / "preflight.py"),
            "WRAP_OUT": str(out),
            **({"WRAP_STUB_DIR": str(root / "stubs")} if stub else {}),
            **({"WRAP_LEAK": "1"} if leak else {}),
            **shell,
        }
        subprocess.run(
            [
                sys.executable,
                str(root / "wrap.py"),
                "--env",
                str(root / ".env"),
                "--defer-missing-sdk",
                "--json",
                *args,
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        snapshot = json.loads(out.read_text()) if out.exists() else {}
        attempts = json.loads(Path(str(out) + ".attempts").read_text())["attempts"]
    return snapshot, attempts


class OfflineBoundaryTests(unittest.TestCase):
    SHELL = {
        "TRAIGENT_API_KEY": SYNTHETIC_KEY,
        "TRAIGENT_BACKEND_URL": "https://shell.invalid/api",
        "TRAIGENT_API_URL": "https://shell2.invalid/api",
        "TRAIGENT_OFFLINE_MODE": "false",
        "LITELLM_LOCAL_MODEL_COST_MAP": "false",
        "TRAIGENT_FIRST_RUN_PHASE": "connected",
    }
    DOTENV = (
        f"TRAIGENT_API_KEY={DOTENV_KEY}\n"
        "TRAIGENT_BACKEND_URL=https://dotenv.invalid/api\n"
        "TRAIGENT_API_URL=https://dotenv2.invalid/api\n"
    )
    ARGS = ["--models", "gpt-4o-mini"]

    def test_control_a_connected_run_does_show_the_key_to_the_model_check(self) -> None:
        snapshot, _ = run_wrapped(self.SHELL, self.DOTENV, self.ARGS)
        self.assertEqual(snapshot["TRAIGENT_API_KEY"], SYNTHETIC_KEY)
        self.assertEqual(snapshot["TRAIGENT_FIRST_RUN_PHASE"], "connected")

    def test_offline_blanks_shell_credentials_before_the_model_check_imports(
        self,
    ) -> None:
        snapshot, _ = run_wrapped(self.SHELL, "", [*self.ARGS, "--offline"])
        for name in ("TRAIGENT_API_KEY", "TRAIGENT_BACKEND_URL", "TRAIGENT_API_URL"):
            self.assertFalse(snapshot[name], name)

    def test_offline_keeps_a_dotenv_key_out_of_the_model_check(self) -> None:
        snapshot, _ = run_wrapped({}, self.DOTENV, [*self.ARGS, "--offline"])
        for name in ("TRAIGENT_API_KEY", "TRAIGENT_BACKEND_URL", "TRAIGENT_API_URL"):
            self.assertFalse(snapshot[name], name)

    def test_offline_overrides_inherited_flags_and_pins_the_baseline_phase(
        self,
    ) -> None:
        snapshot, _ = run_wrapped(self.SHELL, "", [*self.ARGS, "--offline"])
        self.assertEqual(snapshot["TRAIGENT_OFFLINE_MODE"], "true")
        self.assertEqual(snapshot["LITELLM_LOCAL_MODEL_COST_MAP"], "true")
        self.assertEqual(snapshot["TRAIGENT_FIRST_RUN_PHASE"], "baseline")

    def test_the_socket_guard_records_a_traigent_lookup(self) -> None:
        _, attempts = run_wrapped({}, "", ["--offline"], leak=True)
        self.assertTrue(
            any("api.traigent.ai" in attempt["address"] for attempt in attempts)
        )

    def test_offline_preflight_attempts_no_connection_or_lookup(self) -> None:
        _, attempts = run_wrapped(self.SHELL, self.DOTENV, [*self.ARGS, "--offline"])
        self.assertEqual(attempts, [])

    def test_offline_preflight_with_real_litellm_attempts_no_connection(self) -> None:
        if importlib.util.find_spec("litellm") is None:
            if os.environ.get("CI"):
                self.fail("litellm must be installed under CI")
            self.skipTest("litellm is not installed")
        _, attempts = run_wrapped(
            self.SHELL,
            self.DOTENV,
            ["--models", "gpt-4o-mini", "--offline"],
            stub=False,
        )
        self.assertEqual(attempts, [])

    def test_the_documented_unset_command_names_the_phase_variable(self) -> None:
        self.assertIn(
            "-u TRAIGENT_FIRST_RUN_PHASE", " ".join(SKILL.read_text().split())
        )

    def test_the_reported_wording_matches_what_is_enforced(self) -> None:
        records = {
            record["check"]: record
            for record in preflight(
                ["--env", "/nonexistent/.env", "--defer-missing-sdk", "--offline"],
                {"TRAIGENT_API_KEY": SYNTHETIC_KEY},
                tempfile.gettempdir(),
            )
        }
        detail = records["traigent-key"]["detail"]
        self.assertIn("blanked it in its own process", detail)
        self.assertNotIn("nothing reads", detail)


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

    def executable(self, directory: str, *parts: str) -> Path:
        path = Path(directory, *parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
        return path

    def recording_run(self, versions: dict[str, dict], uv_answer: str = ""):
        launched: list[list[str]] = []
        kwargs_seen: list[dict] = []

        def run(command, **kwargs):
            launched.append(list(command))
            kwargs_seen.append(kwargs)
            if command[1:3] == ["python", "find"]:
                return SimpleNamespace(returncode=0, stdout=uv_answer, stderr="")
            answer = versions.get(command[0])
            if answer is None:
                raise FileNotFoundError(command[0])
            return SimpleNamespace(
                returncode=0,
                stdout=answer if isinstance(answer, str) else json.dumps(answer),
                stderr="",
            )

        return run, launched, kwargs_seen

    def good(self, path: Path, version: str = "3.13.1") -> dict:
        return {"ok": True, "executable": str(path), "version": version}

    def test_uv_is_not_launched_when_a_path_candidate_qualifies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            py = self.executable(directory, "host", "python3")
            uv = self.executable(directory, "host", "uv")
            run, launched, _ = self.recording_run({str(py): self.good(py)})
            found = MODULE.find_python(
                which={"python3": str(py), "uv": str(uv)}.get, run=run
            )
        self.assertEqual(found["via"], "python3")
        self.assertNotIn(str(uv), [command[0] for command in launched])

    def test_uv_outside_the_project_is_used_when_no_path_candidate_qualifies(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            uv = self.executable(directory, "host", "uv")
            managed = self.executable(directory, "uvpy", "python3.13")
            run, launched, _ = self.recording_run(
                {str(managed): self.good(managed)}, uv_answer=f"{managed}\n"
            )
            found = MODULE.find_python(
                Path(directory, "project"),
                which={"uv": str(uv)}.get,
                run=run,
            )
        self.assertEqual(found["via"], "uv python find")
        self.assertEqual(launched[0][0], str(uv))

    def test_a_uv_inside_the_project_is_never_launched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            uv = self.executable(directory, "project", ".venv", "bin", "uv")
            run, launched, _ = self.recording_run({})
            found = MODULE.find_python(
                Path(directory, "project"), which={"uv": str(uv)}.get, run=run
            )
        self.assertEqual(launched, [])
        self.assertIn("error", found)
        self.assertTrue(any("uv inside the project" in line for line in found["tried"]))

    def test_a_uv_symlinked_into_the_project_is_never_launched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            real = self.executable(directory, "project", "tools", "uv")
            link = Path(directory, "host", "uv")
            link.parent.mkdir()
            link.symlink_to(real)
            run, launched, _ = self.recording_run({})
            MODULE.find_python(
                Path(directory, "project"), which={"uv": str(link)}.get, run=run
            )
        self.assertEqual(launched, [])

    def test_an_interpreter_symlinked_into_the_project_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            real = self.executable(directory, "project", "bin", "python3.13")
            link = Path(directory, "host", "python3")
            link.parent.mkdir()
            link.symlink_to(real)
            run, launched, _ = self.recording_run({str(link): self.good(link)})
            found = MODULE.find_python(
                Path(directory, "project"), which={"python3": str(link)}.get, run=run
            )
        self.assertEqual(launched, [])
        self.assertIn("error", found)

    def test_probes_run_with_no_credentials_from_a_neutral_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            py = self.executable(directory, "host", "python3")
            run, _, kwargs_seen = self.recording_run({str(py): self.good(py)})
            with mock.patch.dict(
                os.environ,
                {
                    "TRAIGENT_API_KEY": SYNTHETIC_KEY,
                    "OPENAI_API_KEY": "sk-synthetic-not-real",
                    "TRAIGENT_BACKEND_URL": "https://shell.invalid",
                },
            ):
                MODULE.find_python(which={"python3": str(py)}.get, run=run)
        environment = kwargs_seen[0]["env"]
        self.assertNotIn("TRAIGENT_API_KEY", environment)
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertFalse([name for name in environment if "TRAIGENT" in name])
        self.assertEqual(kwargs_seen[0]["cwd"], tempfile.gettempdir())

    def test_a_version_manager_shim_is_skipped_without_launching_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shim = self.executable(directory, ".pyenv", "shims", "python3")
            run, launched, _ = self.recording_run({str(shim): self.good(shim)})
            found = MODULE.find_python(which={"python3": str(shim)}.get, run=run)
        self.assertEqual(launched, [])
        self.assertTrue(any("shim" in line for line in found["tried"]))

    def test_malformed_probe_answers_are_refused(self) -> None:
        for label, raw in {
            "not json": "hello\n",
            "a list": "[1, 2]\n",
            "empty": "",
            "no version": json.dumps({"ok": True, "executable": "/x"}),
            "bad version": json.dumps(
                {"ok": True, "executable": "/x", "version": "three"}
            ),
            "non-bool ok": json.dumps(
                {"ok": "yes", "executable": "/x", "version": "3.13.1"}
            ),
        }.items():
            with self.subTest(label):
                with tempfile.TemporaryDirectory() as directory:
                    py = self.executable(directory, "host", "python3")
                    run, _, _ = self.recording_run({str(py): raw})
                    found = MODULE.find_python(which={"python3": str(py)}.get, run=run)
                self.assertIn("error", found)

    def test_a_flag_cannot_widen_the_supported_version_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            py = self.executable(directory, "host", "python3")
            run, _, _ = self.recording_run({str(py): self.good(py, "3.14.0")})
            found = MODULE.find_python(which={"python3": str(py)}.get, run=run)
        self.assertIn("error", found)

    def test_a_symlink_loop_is_refused_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory, "a"), Path(directory, "b")
            a.symlink_to(b)
            b.symlink_to(a)
            for root in (None, Path(directory, "project")):
                with self.subTest(root=root):
                    run, _, _ = self.recording_run({str(a): self.good(a)})
                    found = MODULE.find_python(
                        root, which={"python3": str(a)}.get, run=run
                    )
                    self.assertIn("error", found)

    def test_windows_gets_the_manual_fallback(self) -> None:
        found = MODULE.find_python(which=lambda name: None, posix=False)
        self.assertIn("py -0p", found["error"])
        self.assertIn("POSIX only", MODULE.__doc__)

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

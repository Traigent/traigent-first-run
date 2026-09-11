from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "traigent-first-run"
PREFLIGHT = SKILL / "scripts" / "preflight.py"
READINESS = SKILL / "scripts" / "readiness.py"
SAFETY = SKILL / "references" / "run-safety.md"
SPEC = importlib.util.spec_from_file_location("bootstrap_preflight", PREFLIGHT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def installed_sdk_fixture(site: Path) -> None:
    """Metadata is enough: preflight must never import the package itself."""
    distribution, version = "traigent", "0.26.0"
    dist = site / f"{distribution}-{version}.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text(f"Name: {distribution}\nVersion: {version}\n")
    modules = ("traigent.api.decorators", "traigent.core.objectives")
    (dist / "RECORD").write_text(
        "".join(f"{module.replace('.', '/')}.py,,\n" for module in modules)
    )
    package = site / distribution
    package.mkdir()
    (package / "__init__.py").write_text(
        "raise AssertionError('the static bootstrap imported an SDK')\n"
    )


class OpeningBootstrapTests(unittest.TestCase):
    def test_unsupported_python_names_a_remedy_and_supported_versions_still_pass(self):
        for minor in (10, 11, 12, 13, 14):
            with self.subTest(minor=minor):
                MODULE.RESULTS.clear()
                with mock.patch.object(
                    MODULE.sys, "version_info", SimpleNamespace(major=3, minor=minor)
                ):
                    MODULE.check_python()
                result = MODULE.RESULTS[0]
                if minor in (10, 14):
                    self.assertEqual(result.status, MODULE.FAIL)
                    self.assertIn(
                        "use an already installed Python 3.11-3.13", result.detail
                    )
                    self.assertIn("install Python 3.13 locally", result.detail)
                    self.assertIn(
                        "provide its executable path to resume", result.detail
                    )
                else:
                    self.assertEqual(result.status, MODULE.PASS)

    def test_isolated_bootstrap_does_not_credit_injected_sdk_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site = root / "injected packages"
            installed_sdk_fixture(site)
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(site)}
            command = [
                str(PREFLIGHT),
                "--project-root",
                str(root),
                "--env",
                str(root / "missing.env"),
                "--defer-missing-sdk",
                "--json",
            ]
            outputs = {}
            for label, flags in (("unisolated", ["-S"]), ("bootstrap", ["-I", "-S"])):
                completed = subprocess.run(
                    [sys.executable, *flags, *command],
                    cwd=root,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=15,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                outputs[label] = json.loads(completed.stdout)
            sdk = {
                label: next(row for row in rows if row["check"] == "sdk-version")
                for label, rows in outputs.items()
            }
            self.assertEqual(sdk["unisolated"]["status"], "PASS")
            self.assertEqual(sdk["bootstrap"]["status"], "SKIP")
            self.assertIn("availability is unmeasured", sdk["bootstrap"]["detail"])
            self.assertNotIn("is not installed", sdk["bootstrap"]["detail"])
            # The same isolated command can consume real preflight output; no
            # sibling-import path or site-package restoration is required.
            ready = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(READINESS),
                    "--preflight",
                    "-",
                    "--json",
                ],
                input=json.dumps(outputs["bootstrap"]),
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(ready.returncode, 0, ready.stderr)
            self.assertIsInstance(json.loads(ready.stdout), dict)
            self.assertFalse((root / "traigent-runs").exists())

    def test_isolated_bootstrap_excludes_user_site_and_site_startup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import site; print(site.getusersitepackages())",
                ],
                env={"PYTHONUSERBASE": str(root)},
                text=True,
                capture_output=True,
                check=True,
            )
            site = Path(probe.stdout.strip())
            installed_sdk_fixture(site)
            marker = root / "startup-ran"
            (site / "usercustomize.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
            )
            command = [
                str(PREFLIGHT),
                "--project-root",
                str(root),
                "--env",
                str(root / "missing.env"),
                "--defer-missing-sdk",
                "--json",
            ]
            env = {"PYTHONUSERBASE": str(root)}
            # Positive control: the fixture reaches the ordinary interpreter.
            ordinary = subprocess.run(
                [sys.executable, *command],
                env=env,
                text=True,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(ordinary.returncode, 0, ordinary.stderr)
            self.assertTrue(marker.exists())
            self.assertEqual(
                next(
                    row
                    for row in json.loads(ordinary.stdout)
                    if row["check"] == "sdk-version"
                )["status"],
                "PASS",
            )
            marker.unlink()
            isolated = subprocess.run(
                [sys.executable, "-I", "-S", *command],
                env=env,
                text=True,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(isolated.returncode, 0, isolated.stderr)
            self.assertFalse(marker.exists())
            self.assertEqual(
                next(
                    row
                    for row in json.loads(isolated.stdout)
                    if row["check"] == "sdk-version"
                )["status"],
                "SKIP",
            )

    def test_a_dedicated_environment_check_measures_its_own_installed_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = root / ".venv-traigent"
            venv.EnvBuilder(with_pip=False).create(environment)
            interpreter = environment / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            identity = subprocess.run(
                [
                    str(interpreter),
                    "-c",
                    "import json, sys, sysconfig; print(json.dumps([sys.prefix, sysconfig.get_path('purelib')]))",
                ],
                text=True,
                capture_output=True,
                check=True,
                timeout=15,
            )
            prefix, site = json.loads(identity.stdout)
            self.assertEqual(Path(prefix), environment)
            installed_sdk_fixture(Path(site))
            completed = subprocess.run(
                [
                    str(interpreter),
                    str(PREFLIGHT),
                    "--project-root",
                    str(root),
                    "--env",
                    str(root / "missing.env"),
                    "--json",
                ],
                env={},
                text=True,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                next(
                    row
                    for row in json.loads(completed.stdout)
                    if row["check"] == "sdk-version"
                )["status"],
                "PASS",
            )


@unittest.skipUnless(
    os.name == "posix" and shutil.which("sh"), "the documented POSIX probe"
)
class InstalledInterpreterLookupTests(unittest.TestCase):
    def test_the_published_probe_rejects_both_unsupported_version_boundaries(self):
        section = SAFETY.read_text().split("### Finding a supported interpreter", 1)[1]
        probe = re.search(r"-c '([^']+)'", section)
        self.assertIsNotNone(probe)
        for minor in (10, 14):
            with self.subTest(minor=minor):
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        "-S",
                        "-c",
                        f"import sys; sys.version_info = (3, {minor}); "
                        + probe.group(1),
                    ],
                    text=True,
                    capture_output=True,
                    timeout=15,
                )
                self.assertEqual(completed.returncode, 1, completed.stderr)
                self.assertEqual(completed.stdout, "")

    def probe(self, directory: Path) -> subprocess.CompletedProcess[str]:
        section = SAFETY.read_text().split("### Finding a supported interpreter", 1)[1]
        script = re.search(r"```sh\n(.*?)\n```", section, re.DOTALL)
        self.assertIsNotNone(script)
        return subprocess.run(
            [shutil.which("sh"), "-c", script.group(1)],
            cwd=directory,
            env={"PATH": str(directory)},
            text=True,
            capture_output=True,
            timeout=15,
        )

    def test_failed_host_uses_a_working_alternate_path_and_stops_searching(self):
        with tempfile.TemporaryDirectory(prefix="interpreter paths ") as temporary:
            root = Path(temporary)
            bad_host = root / "python3"
            bad_host.write_text("#!/bin/sh\nexit 1\n")
            bad_host.chmod(0o755)
            alternate = root / "python3.13"
            alternate.symlink_to(sys.executable)
            later = root / "python3.12"
            later.write_text("#!/bin/sh\nprintf 'wrong later interpreter'\nexit 0\n")
            later.chmod(0o755)
            completed = self.probe(root)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(str(alternate), completed.stdout)
            self.assertNotIn("wrong later interpreter", completed.stdout)

    def test_no_supported_command_returns_failure_without_installing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            completed = self.probe(root)
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(completed.stdout, "")
            self.assertEqual(list(root.iterdir()), [])
            instructions = SAFETY.read_text().split(
                "### Finding a supported interpreter", 1
            )[1]
            instructions = " ".join(instructions.split("### Rules", 1)[0].split())
            self.assertIn("--offline --no-python-downloads", instructions)
            self.assertIn("install Python 3.13 locally", instructions)
            self.assertIn("readiness as not yet measured", instructions)


if __name__ == "__main__":
    unittest.main()

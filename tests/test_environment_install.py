"""Offline integration checks for the isolated approval-plan installer.

These install tiny locally constructed wheels into real disposable environments.
They never contact an index, run a build backend, or start the target interpreter.
"""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
import unittest
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/traigent-first-run/scripts/environment_install.py"
TRUSTED = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
INTERPRETER = "Scripts/python.exe" if os.name == "nt" else "bin/python"


def wheel(directory: Path, name: str, version: str, dependencies=()) -> Path:
    normalized = name.replace("-", "_").replace(".", "_").lower()
    metadata_directory = f"{normalized}-{version}.dist-info"
    files = {
        f"{normalized}.py": f"VERSION = {version!r}\ndef main():\n    print(VERSION)\n",
        f"{metadata_directory}/METADATA": (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {dependency}\n" for dependency in dependencies)
        ),
        f"{metadata_directory}/WHEEL": "Wheel-Version: 1.0\nGenerator: local-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{metadata_directory}/entry_points.txt": f"[console_scripts]\n{normalized} = {normalized}:main\n",
    }
    record = io.StringIO()
    writer = csv.writer(record)
    for filename in [*files, f"{metadata_directory}/RECORD"]:
        writer.writerow([filename, "", ""])
    files[f"{metadata_directory}/RECORD"] = record.getvalue()
    result = directory / f"{normalized}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(result, "w") as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    return result


class IsolatedInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="first run installer ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target = self.root / ".venv"
        venv.EnvBuilder(with_pip=False, symlinks=os.name == "posix").create(self.target)
        self.site = Path(
            sysconfig.get_path(
                "purelib",
                "venv",
                vars={"base": str(self.target), "platbase": str(self.target)},
            )
        )
        self.site.mkdir(parents=True, exist_ok=True)
        self.wheels = self.root / "wheels"
        self.wheels.mkdir()
        self.requirements = self.root / "pins.txt"
        self.requirements.write_text("pr545-example==2.0\n")
        self.marker = self.root / "startup-ran"
        # Unknown startup hooks are refused by discovery; a candidate pip
        # module still must never be imported by the trusted installer.
        (self.site / "pip.py").write_text(
            f"from pathlib import Path\nPath({str(self.marker)!r}).touch()\n"
        )
        (self.root / "pip.py").write_text(
            f"from pathlib import Path\nPath({str(self.marker)!r}).touch()\n"
        )
        self.sequence = 0

    def invoke(self, *arguments, success=True):
        result = subprocess.run(
            [str(TRUSTED), "-I", "-S", "-B", str(SCRIPT), *map(str, arguments)],
            cwd=self.root,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
            env={
                **os.environ,
                "PYTHONPATH": str(self.root),
                "PIP_INDEX_URL": "https://example.invalid/no-network",
            },
        )
        self.assertFalse(
            self.marker.exists(), "target startup or local pip.py executed"
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def plan(self, *arguments, success=True):
        self.sequence += 1
        return self.invoke(
            "plan",
            "--candidate",
            self.target,
            "--requirements",
            self.requirements,
            "--plan",
            self.root / f"plan-{self.sequence}.json",
            "--no-index",
            "--find-links",
            self.wheels,
            *arguments,
            success=success,
        )

    def apply(self, plan, success=True):
        return self.invoke(
            "apply",
            "--plan",
            plan["plan"],
            "--approved-plan-sha256",
            plan["plan_sha256"],
            success=success,
        )

    def install_version_one(self, name="pr545-example"):
        wheel(self.wheels, name, "1.0")
        self.requirements.write_text(f"{name}==1.0\n")
        self.apply(self.plan())

    def test_real_install_and_exact_upgrade_use_target_scheme_without_startup(self):
        host_site = Path(sysconfig.get_path("purelib"))
        before = (
            sorted(path.name for path in host_site.iterdir())
            if host_site.exists()
            else []
        )
        self.install_version_one()
        wheel(self.wheels, "pr545-example", "2.0")
        self.requirements.write_text("pr545-example==2.0\n")
        plan = self.plan("--change", "pr545-example==2.0")
        self.assertEqual(plan["changes"], ["pr545-example 1.0 -> 2.0"])
        self.assertTrue((self.site / "pr545_example-1.0.dist-info").is_dir())
        self.assertFalse((self.site / "pr545_example-2.0.dist-info").exists())
        result = self.apply(plan)
        self.assertEqual(result["installed"]["pr545-example"], "2.0")
        self.assertFalse((self.site / "pr545_example-1.0.dist-info").exists())
        script = self.target / (
            "Scripts/pr545_example.exe" if os.name == "nt" else "bin/pr545_example"
        )
        if os.name == "posix":
            self.assertIn(str(self.target / INTERPRETER), script.read_text())
        self.assertEqual(
            (
                sorted(path.name for path in host_site.iterdir())
                if host_site.exists()
                else []
            ),
            before,
        )
        self.assertFalse(list(self.site.rglob("*.pyc")))

    def test_all_satisfied_is_a_noop_without_requirementless_pip(self):
        self.install_version_one()
        module = self.site / "pr545_example.py"
        before = module.stat().st_mtime_ns
        plan = self.plan()
        self.assertEqual(plan["new"], [])
        self.assertEqual(plan["changes"], [])
        self.assertEqual(self.apply(plan)["status"], "already-satisfied")
        self.assertEqual(module.stat().st_mtime_ns, before)

    def test_existing_transitive_version_is_preserved_until_explicit_preview(self):
        self.install_version_one("pr545-dependency")
        wheel(self.wheels, "pr545-dependency", "2.0")
        wheel(self.wheels, "pr545-example", "2.0", ("pr545-dependency>=2",))
        self.requirements.write_text("pr545-example==2.0\n")
        refused = self.plan(success=False)
        self.assertIn("ResolutionImpossible", refused.stderr)
        self.assertTrue((self.site / "pr545_dependency-1.0.dist-info").exists())
        plan = self.plan("--change", "pr545-dependency==2.0")
        self.assertEqual(plan["changes"], ["pr545-dependency 1.0 -> 2.0"])
        self.assertEqual(plan["new"], ["pr545-example 2.0"])
        self.apply(plan)

    def test_rc_and_canonical_name_replacement_appears_in_real_resolver_card(self):
        wheel(self.wheels, "Pr545.Example", "2.0rc1")
        self.requirements.write_text("pr545-example==2.0rc1\n")
        self.apply(self.plan())
        wheel(self.wheels, "pr545_example", "2.0")
        self.requirements.write_text("pr545-example==2.0\n")
        plan = self.plan("--change", "PR545.Example==2.0")
        self.assertEqual(plan["changes"], ["pr545-example 2.0rc1 -> 2.0"])
        self.apply(plan)
        self.assertFalse((self.site / "pr545_example-2.0rc1.dist-info").exists())

    def test_newer_agent_dependency_conflict_produces_no_install_plan(self):
        wheel(self.wheels, "pr545-client", "3.13")
        self.requirements.write_text("pr545-client==3.13\n")
        self.apply(self.plan())
        before = {
            path.relative_to(self.target): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file()
        }
        wheel(self.wheels, "pr545-client", "2.20")
        wheel(self.wheels, "pr545-example", "2.0", ("pr545-client>=2.20,<3",))
        self.requirements.write_text("pr545-example==2.0\n")
        refused = self.plan(success=False)
        self.assertIn("ResolutionImpossible", refused.stderr)
        self.assertIn("pr545-client==3.13", refused.stderr)
        self.assertIn("pr545-client<3", refused.stderr)
        self.assertFalse((self.root / f"plan-{self.sequence}.json").exists())
        self.assertEqual(
            {
                path.relative_to(self.target): path.read_bytes()
                for path in self.target.rglob("*")
                if path.is_file()
            },
            before,
        )

    def test_modified_wheel_or_plan_cannot_use_old_approval(self):
        wheel(self.wheels, "pr545-example", "2.0")
        plan = self.plan()
        path = Path(plan["plan"])
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        self.assertIn("approved SHA256", self.apply(plan, success=False).stderr)
        path.write_bytes(original)
        document = json.loads(original)
        Path(document["artifacts"][0]["path"]).write_bytes(b"changed")
        self.assertIn("approved SHA256", self.apply(plan, success=False).stderr)
        self.assertFalse((self.site / "pr545_example.py").exists())

    def test_environment_drift_refuses_old_plan(self):
        wheel(self.wheels, "pr545-example", "2.0")
        plan = self.plan()
        metadata = self.site / "unexpected-1.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: unexpected\nVersion: 1\n"
        )
        (metadata / "RECORD").write_text("")
        self.assertIn("Environment changed", self.apply(plan, success=False).stderr)

    def test_record_outside_target_is_refused_without_deletion(self):
        self.install_version_one()
        outside = self.root / "keep-me"
        outside.write_text("customer data")
        record = self.site / "pr545_example-1.0.dist-info/RECORD"
        with record.open("a") as stream:
            stream.write(f"{outside},,\n")
        refused = self.plan(success=False)
        self.assertIn("unsafe uninstall path", refused.stderr)
        self.assertEqual(outside.read_text(), "customer data")

    def test_source_dependency_cannot_run_a_build_backend(self):
        source = self.root / "source"
        source.mkdir()
        (source / "setup.py").write_text(
            f"from pathlib import Path\nPath({str(self.marker)!r}).touch()\n"
        )
        wheel(
            self.wheels, "pr545-example", "2.0", (f"pr545-source @ {source.as_uri()}",)
        )
        result = self.plan(success=False)
        self.assertIn("Only wheel artifacts", result.stderr)

    def test_adapter_refuses_subprocess_creation_before_a_child_can_execute(self):
        """Exercise the process boundary independently of wheel-only rejection."""
        probe = self.root / "probe.py"
        control = self.root / "control-child-ran"
        forbidden = self.root / "forbidden-child-ran"
        probe.write_text("""import importlib.util
import json
import subprocess
import sys
from pathlib import Path

script, candidate, control, forbidden = map(Path, sys.argv[1:])
trusted = sys.executable
child = [trusted, "-I", "-S", "-B", "-c",
         "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('child executed')"]
subprocess.run([*child, str(control)], check=True, timeout=10)
spec = importlib.util.spec_from_file_location("installer", script)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
sys.path.insert(0, str(installer.ENV.trusted_pip_wheel()))
from pip._internal.cli import main as pip_main

attempted = False
def attempt_child(arguments):
    global attempted
    attempted = True
    subprocess.run([*child, str(forbidden)], check=True, timeout=10)
    return 0

# Inject a request at the real adapter's pip dispatch boundary. Wheel-only
# rejection must not prevent this test from reaching the process guard.
pip_main.main = attempt_child
try:
    installer.pip_adapter(candidate, ["install", "--dry-run"])
except RuntimeError as error:
    print(json.dumps({"attempted": attempted, "error": str(error)}))
    sys.exit(2)
print(json.dumps({"attempted": attempted, "error": None}))
""")
        result = subprocess.run(
            [
                str(TRUSTED),
                "-I",
                "-S",
                "-B",
                str(probe),
                str(SCRIPT),
                str(self.target),
                str(control),
                str(forbidden),
            ],
            cwd=self.root,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(control.read_text(), "child executed")
        self.assertFalse(forbidden.exists(), "pip adapter started a child")
        self.assertFalse(self.marker.exists(), "target or local pip.py executed")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "attempted": True,
                "error": "Package build/interpreter subprocesses are forbidden",
            },
        )

    @unittest.skipUnless(os.name == "posix", "requires symbolic links")
    def test_outward_package_symlink_is_refused_without_writes(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.site / "pr545_example").symlink_to(outside, target_is_directory=True)
        wheel(self.wheels, "pr545-example", "2.0")
        self.assertIn("symlink outside", self.plan(success=False).stderr)
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(os.name == "posix", "requires symbolic links")
    def test_wheel_data_destination_cannot_follow_an_outward_symlink(self):
        artifact = wheel(self.wheels, "pr545-example", "2.0")
        with zipfile.ZipFile(artifact, "a") as archive:
            archive.writestr(
                "pr545_example-2.0.data/data/share/overwrite", "wheel data"
            )
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "overwrite").write_text("customer data")
        (self.target / "share").symlink_to(outside, target_is_directory=True)
        plan = self.plan()
        result = self.apply(plan, success=False)
        self.assertIn("destination escapes", result.stderr)
        self.assertEqual((outside / "overwrite").read_text(), "customer data")
        self.assertFalse((self.site / "pr545_example.py").exists())

    def test_wheel_archive_traversal_is_rejected_before_install(self):
        artifact = wheel(self.wheels, "pr545-example", "2.0")
        with zipfile.ZipFile(artifact, "a") as archive:
            archive.writestr("../escape", "wheel data")
        plan = self.plan()
        self.assertIn("unsafe archive path", self.apply(plan, success=False).stderr)
        self.assertFalse((self.site / "pr545_example.py").exists())

    def test_installed_script_name_cannot_expand_uninstall_scope(self):
        self.install_version_one()
        outside = self.root / "keep-me"
        outside.write_text("customer data")
        entries = self.site / "pr545_example-1.0.dist-info/entry_points.txt"
        entries.write_text("[console_scripts]\n../../keep-me = pr545_example:main\n")
        result = self.plan(success=False)
        self.assertIn("unsafe script name", result.stderr)
        self.assertEqual(outside.read_text(), "customer data")

    def test_entry_point_drift_invalidates_prior_approval(self):
        self.install_version_one()
        wheel(self.wheels, "pr545-example", "2.0")
        plan = self.plan("--change", "pr545-example==2.0")
        entries = self.site / "pr545_example-1.0.dist-info/entry_points.txt"
        entries.write_text(entries.read_text() + "different = pr545_example:main\n")
        self.assertIn("Environment changed", self.apply(plan, success=False).stderr)
        self.assertTrue((self.site / "pr545_example-1.0.dist-info").exists())

    def test_legacy_uninstall_manifests_are_refused(self):
        metadata = self.site / "legacy-1.egg-info"
        metadata.mkdir()
        (metadata / "PKG-INFO").write_text(
            "Metadata-Version: 2.1\nName: legacy\nVersion: 1\n"
        )
        self.assertIn("Legacy installation metadata", self.plan(success=False).stderr)

    def test_record_directory_is_refused_without_removing_environment(self):
        self.install_version_one()
        record = self.site / "pr545_example-1.0.dist-info/RECORD"
        with record.open("a") as stream:
            stream.write(".,,\n")
        self.assertIn("unsafe uninstall path", self.plan(success=False).stderr)
        self.assertTrue((self.site / "pr545_example.py").exists())

    def test_wheel_cannot_replace_environment_configuration(self):
        artifact = wheel(self.wheels, "pr545-example", "2.0")
        with zipfile.ZipFile(artifact, "a") as archive:
            archive.writestr(
                "pr545_example-2.0.data/data/pyvenv.cfg", "home = /unsafe\n"
            )
        configuration = self.target / "pyvenv.cfg"
        original = configuration.read_bytes()
        plan = self.plan()
        self.assertIn("destination escapes", self.apply(plan, success=False).stderr)
        self.assertEqual(configuration.read_bytes(), original)
        self.assertFalse((self.site / "pr545_example.py").exists())

    def test_dot_script_names_cannot_remove_directories(self):
        self.install_version_one()
        entries = self.site / "pr545_example-1.0.dist-info/entry_points.txt"
        for name in (".", ".."):
            with self.subTest(name=name):
                entries.write_text(f"[console_scripts]\n{name} = pr545_example:main\n")
                self.assertIn("unsafe script name", self.plan(success=False).stderr)
                self.assertTrue(self.site.is_dir())

    def test_dist_info_cannot_fall_back_to_installed_files_manifest(self):
        self.install_version_one()
        metadata = self.site / "pr545_example-1.0.dist-info"
        outside = self.root / ".venv-outside"
        outside.mkdir()
        victim = outside / "private-project-file.txt"
        victim.write_text("customer data")
        (metadata / "RECORD").unlink()
        (metadata / "installed-files.txt").write_text(str(victim) + "\n")
        self.assertIn("modern RECORD is required", self.plan(success=False).stderr)
        self.assertEqual(victim.read_text(), "customer data")

    @unittest.skipUnless(os.name == "posix", "requires symbolic links")
    def test_derived_bytecode_uninstall_cannot_follow_outward_cache_link(self):
        self.install_version_one()
        scripts = self.target / "bin"
        source = scripts / "pr545-owned.py"
        source.write_text("print('fixture')\n")
        outside = self.root / ".venv-cache"
        outside.mkdir()
        (scripts / "__pycache__").symlink_to(outside, target_is_directory=True)
        victim = outside / f"pr545-owned.{sys.implementation.cache_tag}.pyc"
        victim.write_bytes(b"customer bytecode")
        record = self.site / "pr545_example-1.0.dist-info/RECORD"
        with record.open("a") as stream:
            stream.write(str(source) + ",,\n")
        self.assertIn("unsafe uninstall path", self.plan(success=False).stderr)
        self.assertEqual(victim.read_bytes(), b"customer bytecode")

    @unittest.skipUnless(os.name == "posix", "requires symbolic links")
    def test_wheel_cannot_replace_configuration_through_inward_directory_alias(self):
        artifact = wheel(self.wheels, "pr545-example", "2.0")
        with zipfile.ZipFile(artifact, "a") as archive:
            archive.writestr(
                "pr545_example-2.0.data/data/alias/pyvenv.cfg", "home = /unsafe\n"
            )
        (self.target / "alias").symlink_to(self.target, target_is_directory=True)
        configuration = self.target / "pyvenv.cfg"
        original = configuration.read_bytes()
        plan = self.plan()
        self.assertIn("destination escapes", self.apply(plan, success=False).stderr)
        self.assertEqual(configuration.read_bytes(), original)

    def test_unknown_executable_hook_is_refused_before_resolution(self):
        (self.site / "hook.pth").write_text(
            f"import pathlib; pathlib.Path({str(self.marker)!r}).touch()\n"
        )
        wheel(self.wheels, "pr545-example", "2.0")
        self.assertIn("Unknown executable .pth hook", self.plan(success=False).stderr)
        self.assertFalse((self.site / "pr545_example.py").exists())

    def test_inherited_system_site_packages_are_refused_explicitly(self):
        configuration = self.target / "pyvenv.cfg"
        configuration.write_text(
            configuration.read_text().replace(
                "include-system-site-packages = false",
                "include-system-site-packages = true",
            )
        )
        self.assertIn("system-site-packages", self.plan(success=False).stderr)


if __name__ == "__main__":
    unittest.main()

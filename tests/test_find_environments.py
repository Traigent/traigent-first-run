"""The environment detector and version guard behind #518.

The guidance says the run installs the SDK into the customer's own virtual
environment when the project has one, and these are the checks that make
that sentence executable: which directories count as an environment, which
of the three guard cases a pin lands in, and what the approval card shows.
Every case here runs against real directories under `tempfile`, and the
detector reads real copied and symlinked `venv` layouts statically, so a
sandbox with no network still exercises the whole discovery path.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "traigent-first-run" / "scripts" / "find_environments.py"
REQUIREMENTS = (
    ROOT / "skills" / "traigent-first-run" / "assets" / "requirements-first-run.txt"
)
SPEC = importlib.util.spec_from_file_location("first_run_find_environments", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

INTERPRETER = "Scripts/python.exe" if os.name == "nt" else "bin/python"


def fake_environment(directory: Path) -> Path:
    """`pyvenv.cfg` plus an interpreter file: the detection predicate's shape,
    without the cost of a real `venv` for cases that never probe it."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pyvenv.cfg").write_text("home = /nowhere\n")
    interpreter = directory / INTERPRETER
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_text("")
    return directory


class DetectionPredicateTests(unittest.TestCase):
    def test_the_name_test_is_venv_or_env_in_any_case(self) -> None:
        for name in (".venv", "venv", "env", ".venv-dev", "projectX_venv", "ENV"):
            with self.subTest(name=name):
                self.assertTrue(MODULE.name_looks_like_environment(name))
        for name in ("src", "node_modules", "build", ".git"):
            with self.subTest(name=name):
                self.assertFalse(MODULE.name_looks_like_environment(name))

    def test_a_folder_called_env_without_pyvenv_cfg_is_not_an_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "env").mkdir()
            (root / "env" / INTERPRETER).parent.mkdir(parents=True)
            (root / "env" / INTERPRETER).write_text("")
            self.assertIsNone(MODULE.interpreter_of(root / "env"))
            (root / "venv").mkdir()
            (root / "venv" / "pyvenv.cfg").write_text("")
            self.assertIsNone(MODULE.interpreter_of(root / "venv"))
            self.assertEqual(
                MODULE.candidate_directories(root, {}),
                [(root / "venv", "project-root")],
            )

    def test_real_environments_directly_under_the_root_are_found(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in (".venv", "ENV", "projectX_venv", "env"):
                fake_environment(root / name)
            (root / "env" / "pyvenv.cfg").unlink()
            fake_environment(root / "tools")  # a real venv with the wrong name
            fake_environment(root / "nested" / ".venv")  # deeper than the root
            found = MODULE.candidate_directories(root, {})
            self.assertEqual(
                [path.name for path, _ in found], [".venv", "ENV", "projectX_venv"]
            )
            self.assertTrue(all(source == "project-root" for _, source in found))

    def test_virtual_env_variables_count_only_inside_the_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as elsewhere:
            root = Path(temporary)
            inside = fake_environment(root / "tools" / "runtime")
            outside = fake_environment(Path(elsewhere) / ".venv")
            found = MODULE.candidate_directories(
                root,
                {"VIRTUAL_ENV": str(outside), "UV_PROJECT_ENVIRONMENT": str(inside)},
            )
            self.assertEqual(found, [(inside.resolve(), "UV_PROJECT_ENVIRONMENT")])
            found = MODULE.candidate_directories(root, {"VIRTUAL_ENV": str(inside)})
            self.assertEqual(found, [(inside.resolve(), "VIRTUAL_ENV")])
            self.assertEqual(
                MODULE.candidate_directories(root, {"VIRTUAL_ENV": ""}), []
            )


class VersionGuardTests(unittest.TestCase):
    PINS = {"traigent": "0.26.0", "litellm": "1.93.0", "python-dotenv": "1.2.2"}

    def test_the_guard_has_three_cases_and_a_missing_pin_is_installed(self) -> None:
        installed = {"traigent": "0.26.0", "litellm": "1.80.0"}
        by_name = {r["package"]: r for r in MODULE.guard(installed, self.PINS)}
        self.assertEqual(by_name["traigent"]["action"], "keep")
        self.assertEqual(by_name["litellm"]["action"], "change")
        self.assertEqual(
            by_name["litellm"]["line"], "this will change litellm 1.80.0 to 1.93.0"
        )
        self.assertEqual(by_name["python-dotenv"]["action"], "install")
        self.assertEqual(
            MODULE.install_arguments(list(by_name.values())), ["python-dotenv==1.2.2"]
        )
        self.assertEqual(
            MODULE.install_arguments(list(by_name.values()), approved_changes=True),
            ["litellm==1.93.0", "python-dotenv==1.2.2"],
        )

    def test_a_newer_version_is_kept_with_the_not_tested_note(self) -> None:
        installed = {
            "traigent": "0.27.1",
            "litellm": "1.98.0",
            "python-dotenv": "1.2.2",
        }
        records = MODULE.guard(installed, self.PINS)
        by_name = {r["package"]: r for r in records}
        self.assertEqual(by_name["traigent"]["action"], "keep-newer")
        self.assertEqual(by_name["litellm"]["action"], "keep-newer")
        self.assertEqual(
            by_name["litellm"]["note"],
            "litellm 1.98.0 is not the tested version (1.93.0)",
        )
        self.assertEqual(by_name["python-dotenv"]["action"], "keep")
        self.assertNotIn("note", by_name["python-dotenv"])
        self.assertEqual(MODULE.install_arguments(records), [])

    def test_version_comparison_is_numeric_and_retains_a_pre_release_suffix(
        self,
    ) -> None:
        self.assertGreater(
            MODULE.version_tuple("1.100.0"), MODULE.version_tuple("1.93.0")
        )
        self.assertLess(
            MODULE.version_tuple("1.93.0rc1"), MODULE.version_tuple("1.93.0")
        )
        self.assertTrue(MODULE.supported("3.11.0"))
        self.assertTrue(MODULE.supported("3.13.7"))
        self.assertFalse(MODULE.supported("3.10.14"))
        self.assertFalse(MODULE.supported("3.14.0"))

    def test_the_bundled_requirements_file_reads_as_three_pins(self) -> None:
        self.assertEqual(
            set(MODULE.read_pins(REQUIREMENTS)),
            {"traigent", "litellm", "python-dotenv"},
        )


class ApprovalCardTests(unittest.TestCase):
    def test_the_card_splits_new_packages_from_version_changes(self) -> None:
        report = {
            "install": [
                {"metadata": {"name": "traigent", "version": "0.26.0"}},
                {"metadata": {"name": "LiteLLM", "version": "1.93.0"}},
                {"metadata": {"name": "tokenizers", "version": "0.21.0"}},
                {"metadata": {"name": "openai", "version": "1.90.0"}},
            ]
        }
        installed = {"litellm": "1.80.0", "openai": "1.90.0", "requests": "2.32.0"}
        card = MODULE.approval_card(report, installed)
        self.assertEqual(card["new"], ["tokenizers 0.21.0", "traigent 0.26.0"])
        self.assertEqual(card["changes"], ["litellm 1.80.0 -> 1.93.0"])

    def test_an_empty_report_is_an_empty_card(self) -> None:
        self.assertEqual(MODULE.approval_card({}, {}), {"new": [], "changes": []})


class CommandLineTests(unittest.TestCase):
    def test_installed_versions_come_from_the_candidate_for_both_venv_layouts(
        self,
    ) -> None:
        layouts = (False, True) if os.name == "posix" else (False,)
        for symlinks in layouts:
            with self.subTest(
                symlinks=symlinks
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                environment = root / ".venv"
                venv.EnvBuilder(with_pip=False, symlinks=symlinks).create(environment)
                interpreter = environment / INTERPRETER
                self.assertEqual(interpreter.is_symlink(), symlinks)
                site = Path(
                    subprocess.run(
                        [
                            str(interpreter),
                            "-I",
                            "-c",
                            "import sysconfig; print(sysconfig.get_path('purelib'))",
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=30,
                    ).stdout.strip()
                )
                for name, version in (("litellm", "1.80.0"), ("traigent", "0.27.0")):
                    metadata = site / f"{name}-{version}.dist-info"
                    metadata.mkdir(parents=True)
                    (metadata / "METADATA").write_text(
                        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
                    )
                described = MODULE.describe(root, REQUIREMENTS, {})
                (candidate,) = described["candidates"]
                self.assertEqual(Path(candidate["prefix"]), environment.resolve())
                self.assertEqual(Path(candidate["site"]), site)
                self.assertEqual(candidate["installed"]["litellm"], "1.80.0")
                records = {r["package"]: r for r in candidate["guard"]}
                self.assertEqual(records["litellm"]["action"], "change")
                self.assertEqual(
                    records["litellm"]["line"],
                    "this will change litellm 1.80.0 to 1.93.0",
                )
                self.assertEqual(records["traigent"]["action"], "keep-newer")
                self.assertEqual(
                    MODULE.install_arguments(candidate["guard"]),
                    ["python-dotenv==1.2.2"],
                )
                report = root / "pip-report.json"
                report.write_text(
                    json.dumps(
                        {
                            "install": [
                                {"metadata": {"name": "LiteLLM", "version": "1.93.0"}}
                            ]
                        }
                    )
                )
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--project-root",
                        str(root),
                        "--requirements",
                        str(REQUIREMENTS),
                        "--candidate",
                        str(environment),
                        "--dry-run-report",
                        str(report),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                card = json.loads(completed.stdout)
                self.assertEqual(card["new"], [])
                self.assertEqual(card["changes"], ["litellm 1.80.0 -> 1.93.0"])

    def test_a_real_environment_is_verified_against_the_trusted_interpreter(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            venv.EnvBuilder(with_pip=False).create(root / ".venv")
            fake_environment(root / "env")  # the interpreter file is empty
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--requirements",
                    str(REQUIREMENTS),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                env={
                    k: v
                    for k, v in os.environ.items()
                    if k not in MODULE.ENVIRONMENT_VARIABLES
                },
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            described = json.loads(completed.stdout)
            by_path = {Path(c["path"]).name: c for c in described["candidates"]}
            self.assertEqual(set(by_path), {".venv", "env"})
            real = by_path[".venv"]
            self.assertEqual(Path(real["prefix"]), (root / ".venv").resolve())
            self.assertIn((root / ".venv").resolve(), Path(real["site"]).parents)
            self.assertEqual(
                real["python_version"], ".".join(map(str, sys.version_info[:3]))
            )
            self.assertEqual(
                real["supported"], MODULE.supported(real["python_version"])
            )
            self.assertEqual(
                {r["package"]: r["action"] for r in real["guard"]},
                {
                    "traigent": "install",
                    "litellm": "install",
                    "python-dotenv": "install",
                },
            )
            self.assertIn("probe_error", by_path["env"])
            self.assertIsNone(by_path["env"]["supported"])
            self.assertEqual(
                described["state"], "one" if real["supported"] else "unverified"
            )
            self.assertEqual(
                described["skipped"],
                [
                    f"{by_path['env']['path']} was skipped (unverified: {by_path['env']['probe_error']})"
                ],
            )

    def test_an_unverified_candidate_stays_visible_beside_an_unsupported_runtime(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_environment(root / ".venv")
            fake_environment(root / "env")
            answers = {
                str((root / ".venv" / INTERPRETER).resolve()): {
                    "prefix": str(root / ".venv"),
                    "version": "3.10.14",
                    "site": str(root / ".venv" / "lib"),
                    "installed": {},
                },
                str((root / "env" / INTERPRETER).resolve()): {"error": "exit 1"},
            }
            with mock.patch.object(
                MODULE, "probe", lambda interpreter: answers[str(interpreter.resolve())]
            ):
                described = MODULE.describe(root, REQUIREMENTS, {})
            self.assertEqual(described["state"], "unverified")
            self.assertEqual(
                described["skipped"],
                [
                    f"{(root / '.venv').resolve()} was skipped (Python 3.10.14, not 3.11-3.13)",
                    f"{(root / 'env').resolve()} was skipped (unverified: exit 1)",
                ],
            )
            self.assertEqual(
                MODULE.describe(root / "empty", REQUIREMENTS, {})["state"], "none"
            )

    def test_the_probe_disables_site_so_no_pth_hook_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            venv.EnvBuilder(with_pip=False).create(root / ".venv")
            interpreter = root / ".venv" / INTERPRETER
            site = Path(
                subprocess.run(
                    [
                        str(interpreter),
                        "-c",
                        "import sysconfig; print(sysconfig.get_path('purelib'))",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=30,
                ).stdout.strip()
            )
            site.mkdir(parents=True, exist_ok=True)
            marker = root / "hook-ran"
            (site / "hook.pth").write_text(
                f"import pathlib; pathlib.Path({str(marker)!r}).touch()\n"
            )
            probed = MODULE.probe(interpreter)
            self.assertIn("Unknown executable .pth hook", probed["error"])
            self.assertFalse(marker.exists(), "a .pth hook ran during the probe")

    def test_the_card_needs_both_of_its_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--requirements",
                    str(REQUIREMENTS),
                    "--candidate",
                    str(root / ".venv"),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("go together", completed.stderr)


class SafeDiscoveryRegressionTests(unittest.TestCase):
    def test_a_candidate_executable_is_never_launched(self) -> None:
        if os.name != "posix":
            self.skipTest("executable shell fixture is POSIX only")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = fake_environment(root / ".venv")
            marker = root / "candidate-ran"
            interpreter = environment / INTERPRETER
            interpreter.write_text(
                f"#!/bin/sh\ntouch '{marker}'\n"
                'echo \'{"prefix":"/fake","site":"/fake","version":"3.12.3","installed":{}}\'\n'
            )
            interpreter.chmod(0o755)
            result = MODULE.describe(root, REQUIREMENTS, {})
            self.assertFalse(marker.exists(), "discovery executed customer code")
            self.assertEqual(result["state"], "unverified")
            self.assertIsNone(result["candidates"][0]["supported"])
            self.assertIn("trusted", result["candidates"][0]["remedy"])

    def test_versions_retain_pep440_suffix_and_epoch_semantics(self) -> None:
        for version in ("1.93.0rc1", "1.93.0.dev1", "1.93.0a1"):
            with self.subTest(version=version):
                (record,) = MODULE.guard({"litellm": version}, {"litellm": "1.93.0"})
                self.assertEqual(record["action"], "change")
                card = MODULE.approval_card(
                    {
                        "install": [
                            {"metadata": {"name": "litellm", "version": "1.93.0"}}
                        ]
                    },
                    {"litellm": version},
                )
                self.assertEqual(card["changes"], [f"litellm {version} -> 1.93.0"])
        for version in ("1.93.0.post1", "1.93.0+customer.1", "1!1.0"):
            with self.subTest(version=version):
                (record,) = MODULE.guard({"litellm": version}, {"litellm": "1.93.0"})
                self.assertEqual(record["action"], "keep-newer")

    def test_distribution_names_have_packaging_canonical_identity(self) -> None:
        (record,) = MODULE.guard({"Python_DotEnv": "1.2.1"}, {"python.dotenv": "1.2.2"})
        self.assertEqual(record["action"], "change")
        self.assertEqual(record["package"], "python-dotenv")
        self.assertEqual(
            MODULE.approval_card(
                {
                    "install": [
                        {"metadata": {"name": "PYTHON.dotenv", "version": "1.2.2"}}
                    ]
                },
                {"python_dotenv": "1.2.1"},
            ),
            {"new": [], "changes": ["python-dotenv 1.2.1 -> 1.2.2"]},
        )

    def test_ambiguous_or_injected_distribution_metadata_is_refused(self) -> None:
        for installed in (
            {"python_dotenv": "1", "python-dotenv": "2"},
            {"evil\n--index-url=https://example.invalid": "1"},
            {"safe": "1\n--index-url=https://example.invalid"},
            {"safe": "not-a-version"},
        ):
            with self.subTest(installed=installed), self.assertRaises(ValueError):
                MODULE.guard(installed, {"safe": "1"})


class StaticMetadataBoundaryTests(unittest.TestCase):
    def test_missing_and_broken_interpreters_remain_visible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = fake_environment(root / ".venv")
            interpreter = target / INTERPRETER
            interpreter.unlink()
            for broken_link in (False, True) if os.name == "posix" else (False,):
                with self.subTest(broken_link=broken_link):
                    if broken_link:
                        interpreter.symlink_to(root / "missing-python")
                    result = MODULE.describe(root, REQUIREMENTS, {})
                    self.assertEqual(result["state"], "unverified")
                    self.assertIn(
                        "missing or broken", result["candidates"][0]["probe_error"]
                    )

    @unittest.skipUnless(os.name == "posix", "requires symbolic links")
    def test_directory_symlinks_are_preserved_and_never_automatically_selected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "runtime"
            venv.EnvBuilder(with_pip=False).create(real)
            (root / ".venv").symlink_to(real, target_is_directory=True)
            result = MODULE.describe(root, REQUIREMENTS, {})
            self.assertEqual(result["state"], "unverified")
            self.assertEqual(result["candidates"][0]["path"], str(root / ".venv"))
            self.assertIn("symlink", result["candidates"][0]["probe_error"])

    def test_duplicate_canonical_metadata_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / ".venv"
            venv.EnvBuilder(with_pip=False).create(target)
            site = Path(MODULE.probe(target / INTERPRETER)["site"])
            for name, version in (("python_dotenv", "1"), ("Python.Dotenv", "2")):
                metadata = site / f"{name}-{version}.dist-info"
                metadata.mkdir(parents=True)
                (metadata / "METADATA").write_text(
                    f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
                )
            result = MODULE.describe(root, REQUIREMENTS, {})
            self.assertEqual(result["state"], "unverified")
            self.assertIn(
                "Ambiguous installed distribution: python-dotenv",
                result["candidates"][0]["probe_error"],
            )

    def test_path_only_pth_cannot_hide_an_inherited_installed_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / ".venv"
            venv.EnvBuilder(with_pip=False).create(target)
            interpreter = target / INTERPRETER
            site = Path(MODULE.probe(interpreter)["site"])
            extra = root / "extra-packages"
            metadata = extra / "litellm-1.80.0.dist-info"
            metadata.mkdir(parents=True)
            (metadata / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: litellm\nVersion: 1.80.0\n"
            )
            (site / "extra.pth").write_text(str(extra) + "\n")
            # Only this test's literal path declaration is loaded by the fixture
            # interpreter; it contains no executable hook or customer module.
            actual = subprocess.run(
                [
                    str(interpreter),
                    "-I",
                    "-B",
                    "-c",
                    "import importlib.metadata; print(importlib.metadata.version('litellm'))",
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual(actual.stdout.strip(), "1.80.0")
            result = MODULE.describe(root, REQUIREMENTS, {})
            self.assertEqual(result["state"], "unverified")
            self.assertIn(
                ".pth path exposes distribution metadata",
                result["candidates"][0]["probe_error"],
            )

    def test_editable_code_path_without_extra_metadata_keeps_declared_site_view(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / ".venv"
            venv.EnvBuilder(with_pip=False).create(target)
            interpreter = target / INTERPRETER
            before = MODULE.probe(interpreter)
            site = Path(before["site"])
            source = root / "src"
            source.mkdir()
            (source / "own_code.py").write_text(
                "raise RuntimeError('must not import')\n"
            )
            (site / "editable.pth").write_text(str(source) + "\n")
            after = MODULE.probe(interpreter)
            self.assertNotIn("error", after)
            self.assertEqual(after["installed"], before["installed"])
            self.assertNotEqual(
                after["identity"]["path_configuration_sha256"],
                before["identity"]["path_configuration_sha256"],
            )

    def test_unknown_startup_paths_remain_unverified_without_execution(self):
        for filename, contents in (
            ("inject.pth", "import sys; sys.path.append('/external-packages')\n"),
            ("sitecustomize.py", "import sys\nsys.path.append('/external-packages')\n"),
            ("usercustomize.py", "import sys\nsys.path.append('/external-packages')\n"),
        ):
            with self.subTest(
                filename=filename
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / ".venv"
                venv.EnvBuilder(with_pip=False).create(target)
                interpreter = target / INTERPRETER
                site = Path(MODULE.probe(interpreter)["site"])
                (site / filename).write_text(contents)
                result = MODULE.describe(root, REQUIREMENTS, {})
                self.assertEqual(result["state"], "unverified")
                self.assertIn(
                    "complete metadata inventory",
                    result["candidates"][0]["probe_error"],
                )

    def test_actual_seeded_venv_retains_trusted_standard_startup_support(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".venv"
            venv.EnvBuilder(with_pip=True).create(target)
            result = MODULE.probe(target / INTERPRETER)
            self.assertNotIn("error", result, result)
            self.assertIn("pip", result["installed"])
            self.assertEqual(result["verification"], "verified")

    def test_trusted_source_does_not_admit_changed_startup_bytecode(self):
        import marshal

        with tempfile.TemporaryDirectory() as temporary:
            shim = Path(temporary) / "_distutils_hack" / "__init__.py"
            shim.parent.mkdir()
            source = b"VALUE = 1\n"
            shim.write_bytes(source)
            cache = Path(importlib.util.cache_from_source(str(shim)))
            cache.parent.mkdir()
            header = importlib.util.MAGIC_NUMBER + b"\0" * 12
            cache.write_bytes(
                header
                + marshal.dumps(compile(source, str(shim), "exec", dont_inherit=True))
            )
            self.assertTrue(MODULE.trusted_shim_bytecode(shim, source))
            cache.write_bytes(
                header
                + marshal.dumps(
                    compile(
                        "import sys; sys.path.append('/external-packages')",
                        str(shim),
                        "exec",
                    )
                )
            )
            self.assertFalse(MODULE.trusted_shim_bytecode(shim, source))

    def test_claimed_version_does_not_verify_a_different_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / ".venv"
            venv.EnvBuilder(with_pip=False).create(target)
            configuration = target / "pyvenv.cfg"
            configuration.write_text(
                configuration.read_text().replace(
                    "version = " + ".".join(map(str, sys.version_info[:3])),
                    "version = 3.13.99",
                )
            )
            result = MODULE.describe(root, REQUIREMENTS, {})
            self.assertEqual(result["state"], "unverified")
            self.assertIsNone(result["candidates"][0]["supported"])
            self.assertIn("3.13.99", result["candidates"][0]["remedy"])


if __name__ == "__main__":
    unittest.main()

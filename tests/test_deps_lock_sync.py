"""`deps/pyproject.toml` exists so dependency scanners see a `uv.lock`.

Its pins must stay identical to `requirements-first-run.txt`, the file the skill
actually installs from, or the scanner audits versions nobody runs.
"""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = (
    ROOT / "skills" / "traigent-first-run" / "assets" / "requirements-first-run.txt"
)
SHIPPED_LOCK = (
    ROOT
    / "skills"
    / "traigent-first-run"
    / "assets"
    / "requirements-first-run.lock.txt"
)
PYPROJECT = ROOT / "deps" / "pyproject.toml"
UV_LOCK = ROOT / "deps" / "uv.lock"


class DepsLockSyncTests(unittest.TestCase):
    def test_pyproject_pins_equal_requirements(self) -> None:
        wanted = sorted(
            line.strip()
            for line in REQUIREMENTS.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        declared = sorted(
            tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]
        )
        self.assertEqual(declared, wanted)

    def test_uv_lock_resolves_the_pinned_versions(self) -> None:
        locked = {
            package["name"]: package["version"]
            for package in tomllib.loads(UV_LOCK.read_text())["package"]
        }
        for line in REQUIREMENTS.read_text().splitlines():
            if "==" in line:
                name, version = line.strip().split("==")
                with self.subTest(package=name):
                    self.assertEqual(locked.get(name), version)

    def test_shipped_lock_agrees_with_uv_lock(self) -> None:
        """Both locks must pin the same version of every package.

        An override that exists in only one lock (or a lock bumped past what the
        pinned SDK allows) leaves a lock that cannot be installed, while the
        scanner audits versions nobody runs.
        """
        locked = {
            package["name"]: package["version"]
            for package in tomllib.loads(UV_LOCK.read_text())["package"]
        }
        shipped: dict[str, str] = {}
        for line in SHIPPED_LOCK.read_text().splitlines():
            match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", line)
            if match:
                shipped[match.group(1).lower().replace("_", "-")] = match.group(2)
        self.assertTrue(shipped)
        for name, version in shipped.items():
            with self.subTest(package=name):
                self.assertEqual(locked.get(name), version)

    def test_uv_lock_has_no_dependency_overrides(self) -> None:
        """An override forces versions the pinned SDK's metadata forbids.

        A floor must arrive through the SDK release's own requirements, so the
        shipped lock stays installable.
        """
        self.assertNotIn("override-dependencies", PYPROJECT.read_text())
        manifest = tomllib.loads(UV_LOCK.read_text()).get("manifest", {})
        self.assertNotIn("overrides", manifest)


if __name__ == "__main__":
    unittest.main()

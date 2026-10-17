"""`deps/pyproject.toml` exists so dependency scanners see a `uv.lock`.

Its pins must stay identical to `requirements-first-run.txt`, the file the skill
actually installs from, or the scanner audits versions nobody runs.
"""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = (
    ROOT / "skills" / "traigent-first-run" / "assets" / "requirements-first-run.txt"
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


if __name__ == "__main__":
    unittest.main()

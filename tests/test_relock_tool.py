"""The lock-writing tool must refuse an index it cannot measure (#198).

`tools/relock.py` run mid-merge exited 0, printed `rewrote`, and produced a lock
with 15 entries for 13 files: `git ls-files` lists a conflicted path once per
merge stage, and the tool hashed every row. Nothing failed at that moment. The
corruption surfaced on the next honest run as a lock mismatch, which reads as
"someone changed a behaviour" - so the cost lands on whoever did not write it.

That makes this a tool whose failure mode is silence, and the tests below pin
the two halves of the fix separately, because they answer different questions:

- the refusal is policy - *when* a lock may be written at all;
- the dedupe in `harness.behavior_files` is structure - a lock must never hash
  one path twice, whatever the index state. Tested in `behavioral/`, beside
  the lock it protects.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELOCK = ROOT / "tools" / "relock.py"


def _load_relock():
    """Import the tool by path; it is a script, not an installed module."""
    spec = importlib.util.spec_from_file_location("relock_tool", RELOCK)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


relock = _load_relock()


class _Captured:
    """Minimal stderr stand-in; `io.StringIO` would also do, but this keeps the
    assertion reading off one attribute."""

    def __init__(self) -> None:
        self.text = ""

    def write(self, value: str) -> int:
        self.text += value
        return len(value)

    def flush(self) -> None:
        return None


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=True,
    )


class UnmergedIndexRefusalTests(unittest.TestCase):
    """Driven against a real conflicted index, not a mocked `ls-files`.

    The defect was in what git actually prints for a conflicted path - three
    rows, one per stage - so a test that hands the parser a string somebody
    wrote from memory would have passed against the broken tool too.
    """

    def setUp(self) -> None:
        if shutil.which("git") is None:
            self.skipTest(
                "git is not available; this test builds a real merge conflict"
            )
        self._directory = tempfile.TemporaryDirectory()
        self.repository = Path(self._directory.name)
        self.addCleanup(self._directory.cleanup)
        _git(self.repository, "init", "--quiet", "-b", "base")
        _git(self.repository, "config", "user.email", "test@example.invalid")
        _git(self.repository, "config", "user.name", "relock test")
        conflicted = self.repository / "glossary.md"
        conflicted.write_text("common\n", encoding="utf-8")
        _git(self.repository, "add", "glossary.md")
        _git(self.repository, "commit", "--quiet", "-m", "base")
        _git(self.repository, "checkout", "--quiet", "-b", "left")
        conflicted.write_text("common\nleft\n", encoding="utf-8")
        _git(self.repository, "commit", "--quiet", "-am", "left")
        _git(self.repository, "checkout", "--quiet", "-b", "right", "base")
        conflicted.write_text("common\nright\n", encoding="utf-8")
        _git(self.repository, "commit", "--quiet", "-am", "right")
        merge = subprocess.run(
            ["git", "-C", str(self.repository), "merge", "left"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(merge.returncode, 0, "the fixture merge must conflict")

    def test_a_conflicted_path_is_reported_once_not_once_per_stage(self) -> None:
        stages = _git(self.repository, "ls-files", "--unmerged").stdout.splitlines()
        self.assertEqual(
            len(stages), 3, f"expected three merge stages, got: {stages!r}"
        )
        with unittest.mock.patch.object(relock, "ROOT", self.repository):
            self.assertEqual(relock.unmerged_paths(), ["glossary.md"])

    def test_a_clean_index_reports_nothing(self) -> None:
        _git(self.repository, "checkout", "--quiet", "--theirs", "glossary.md")
        _git(self.repository, "add", "glossary.md")
        with unittest.mock.patch.object(relock, "ROOT", self.repository):
            self.assertEqual(relock.unmerged_paths(), [])
            self.assertEqual(relock.refuse_unmerged_index(allow=False), "")

    def test_the_refusal_names_the_unresolved_path(self) -> None:
        """A reader mid-merge needs the path, not just a non-zero exit."""
        with unittest.mock.patch.object(relock, "ROOT", self.repository):
            with unittest.mock.patch("sys.stderr", new=_Captured()) as captured:
                with self.assertRaises(SystemExit) as raised:
                    relock.refuse_unmerged_index(allow=False)
        self.assertEqual(raised.exception.code, 2)
        message = captured.text
        self.assertIn("unmerged: 1 path(s)", message)
        self.assertIn("glossary.md", message)
        self.assertIn("--allow-unmerged", message)

    def test_allow_unmerged_writes_and_says_what_it_wrote_over(self) -> None:
        """The escape hatch must stay usable, and must not go quiet."""
        with unittest.mock.patch.object(relock, "ROOT", self.repository):
            state = relock.refuse_unmerged_index(allow=True)
        self.assertIn("unmerged: 1 path(s)", state)
        self.assertIn("glossary.md", state)

    def test_git_failure_is_raised_not_read_as_a_clean_index(self) -> None:
        """A guard that answers "no conflicts" when it could not look is worse
        than no guard, so a git error must not fall through to a write."""
        with tempfile.TemporaryDirectory() as outside:
            # Deliberately not inside the fixture repository: a subdirectory of
            # a git checkout is still a git checkout, and `ls-files` there exits
            # 0 with no rows - the answer this test must not accept.
            with unittest.mock.patch.object(relock, "ROOT", Path(outside)):
                with self.assertRaisesRegex(
                    RuntimeError, "could not list the unmerged"
                ):
                    relock.unmerged_paths()


class UnmergedFlagContractTests(unittest.TestCase):
    def test_allow_unmerged_is_rejected_with_check(self) -> None:
        """`--check` never refuses, so accepting the flag there would read as a
        suppression that worked."""
        process = subprocess.run(
            [sys.executable, str(RELOCK), "--check", "--allow-unmerged"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("--allow-unmerged applies to writing only", process.stderr)


if __name__ == "__main__":
    unittest.main()

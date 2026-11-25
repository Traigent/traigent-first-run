"""Printed output survives a non-UTF-8 stdout (#618).

A Windows pipe defaults stdout to a code page such as cp1252, which cannot
encode the check-mark glyphs or a customer path containing CJK text. The scripts
must neither crash with ``internal error`` nor drop the information: plan mode
falls back to the ASCII marker vocabulary the scoring card already uses, and
the text-mode printers keep unencodable characters as escapes.

These tests run the scripts without ``-I`` so ``PYTHONIOENCODING`` applies, the
way a Windows customer's environment sets it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "traigent-first-run" / "scripts"
READINESS = SCRIPTS / "readiness.py"
PREFLIGHT = SCRIPTS / "preflight.py"
VALIDATE_RUN_LOG = SCRIPTS / "validate_run_log.py"
# "日本" as the backslashreplace handler writes it under a non-Unicode encoding.
ESCAPED_NIHON = "\\u65e5\\u672c"


def run_with_stdout_encoding(
    script: Path, args: list[str], cwd: Path, encoding: str
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": encoding,
    }
    return subprocess.run(
        [sys.executable, "-S", "-B", str(script), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


class ReadinessPlanOutputTests(unittest.TestCase):
    PLAN = ["--agent", "real", "--dataset", "real", "--evaluation", "real"]

    def test_plan_text_under_cp1252_prints_the_ascii_marks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_with_stdout_encoding(
                READINESS, self.PLAN, Path(directory), "cp1252"
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("internal error", result.stdout + result.stderr)
        self.assertIn("Real-world readiness: 3/3", result.stdout)
        self.assertIn("OK Agent: real", result.stdout)

    def test_plan_text_with_ascii_flag_under_cp1252_prints_the_ascii_marks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_with_stdout_encoding(
                READINESS, [*self.PLAN, "--ascii"], Path(directory), "cp1252"
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK Agent: real", result.stdout)

    def test_plan_text_under_utf8_keeps_the_glyph_marks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_with_stdout_encoding(
                READINESS, self.PLAN, Path(directory), "utf-8"
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("✅ Agent: real", result.stdout)


class PreflightTextOutputTests(unittest.TestCase):
    def test_a_non_ascii_path_in_a_finding_is_printed_not_crashed_on(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "日本"
            project.mkdir()
            env_path = project / ".env"
            # Latin-1 bytes are not UTF-8: the env file is a named FAIL (exit 1).
            env_path.write_bytes(
                "# café\nOPENAI_API_KEY=sk-placeholder\n".encode("latin-1")
            )
            env_path.chmod(0o600)
            result = run_with_stdout_encoding(
                PREFLIGHT,
                [
                    "--project-root",
                    str(project),
                    "--env",
                    str(env_path),
                    "--offline",
                    "--defer-missing-sdk",
                ],
                project,
                "cp1252",
            )
        combined = result.stdout + result.stderr
        self.assertNotIn("internal error", combined)
        self.assertNotIn("UnicodeEncodeError", combined)
        self.assertEqual(result.returncode, 1, combined)
        # cp1252 cannot encode the CJK path, so it is shown as escapes: the
        # information survives, and the run does not stop on it.
        self.assertIn(ESCAPED_NIHON, result.stdout)


class ValidateRunLogOutputTests(unittest.TestCase):
    def test_a_non_ascii_log_path_is_printed_not_crashed_on(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_dir = root / "日本"
            log_dir.mkdir()
            log = log_dir / "run-log.jsonl"
            result = run_with_stdout_encoding(
                VALIDATE_RUN_LOG, ["--log", str(log)], root, "cp1252"
            )
        combined = result.stdout + result.stderr
        self.assertNotIn("UnicodeEncodeError", combined)
        self.assertEqual(result.returncode, 0, combined)
        self.assertIn(ESCAPED_NIHON, result.stdout)


if __name__ == "__main__":
    unittest.main()

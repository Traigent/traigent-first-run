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

import json
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

    def test_plan_text_with_ascii_flag_under_utf8_prints_the_ascii_marks(
        self,
    ) -> None:
        # `--ascii` is an explicit choice, so it wins even where the glyphs
        # would encode: the flag is not only a fallback for a failed probe.
        with tempfile.TemporaryDirectory() as directory:
            result = run_with_stdout_encoding(
                READINESS, [*self.PLAN, "--ascii"], Path(directory), "utf-8"
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK Agent: real", result.stdout)
        self.assertNotIn("✅", result.stdout)


class GlyphProbeCoversEveryRenderedGlyphTests(unittest.TestCase):
    """The probe must cover every glyph the renderers emit (#618).

    The probe used to encode only the block glyph, which cp437, cp850, cp936
    and cp950 all carry, so those code pages passed it while the check marks
    and bullets they could not encode came out as backslash escapes.
    """

    CODE_PAGES = ("cp1252", "gbk", "cp437")
    PLAN = ["--agent", "real", "--dataset", "real", "--evaluation", "real"]

    def test_plan_text_under_each_code_page_prints_the_ascii_marks(self) -> None:
        for encoding in self.CODE_PAGES:
            with self.subTest(encoding=encoding):
                with tempfile.TemporaryDirectory() as directory:
                    result = run_with_stdout_encoding(
                        READINESS, self.PLAN, Path(directory), encoding
                    )
                combined = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, combined)
                self.assertIn("OK Agent: real", result.stdout)
                self.assertNotIn("\\u2705", result.stdout)

    def test_scoring_card_under_each_code_page_prints_the_ascii_vocabulary(
        self,
    ) -> None:
        for encoding in self.CODE_PAGES:
            with self.subTest(encoding=encoding):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    records = root / "preflight.json"
                    records.write_text("[]", encoding="utf-8")
                    result = run_with_stdout_encoding(
                        READINESS,
                        ["--preflight", str(records), "--color", "never"],
                        root,
                        encoding,
                    )
                combined = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, combined)
                self.assertIn("!! ", result.stdout)
                # Neither the bar, the bullet nor the warning mark may arrive
                # as an escape: each one is a glyph the card has an ASCII
                # spelling for.
                self.assertNotIn("\\u", result.stdout)

    def test_scoring_card_under_utf8_keeps_the_glyphs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = root / "preflight.json"
            records.write_text("[]", encoding="utf-8")
            result = run_with_stdout_encoding(
                READINESS,
                ["--preflight", str(records), "--color", "never"],
                root,
                "utf-8",
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("░", result.stdout)
        self.assertIn("❗", result.stdout)


class ReadinessCardOutputTests(unittest.TestCase):
    def test_a_non_ascii_path_in_a_readiness_card_is_printed_not_crashed_on(
        self,
    ) -> None:
        # Hand-built records, because the path must reach the card's own
        # sentence verbatim and the card is what this test reads.
        records = [
            {
                "check": "dataset-shape",
                "status": "FAIL",
                "detail": "日本/data.jsonl does not exist",
                "metrics": None,
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "preflight.json"
            report.write_text(json.dumps(records), encoding="utf-8")
            result = run_with_stdout_encoding(
                READINESS,
                ["--preflight", str(report), "--color", "never"],
                root,
                "cp1252",
            )
        combined = result.stdout + result.stderr
        self.assertNotIn("internal error", combined)
        self.assertEqual(result.returncode, 0, combined)
        self.assertIn(ESCAPED_NIHON, result.stdout)


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

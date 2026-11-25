"""Customer files are read as UTF-8 whatever the platform locale says (#617).

The SDK opens datasets with ``encoding="utf-8"`` and python-dotenv defaults to
the same, so preflight and readiness must read the same bytes the same way. A
file the SDK would refuse is a named finding, never an internal error.

These tests run the scripts as subprocesses under a C locale with UTF-8 mode
disabled: that is the interpreter a Windows code page or a bare ``LC_ALL=C``
customer gets, and it is stricter than cp1252, which mojibakes instead of
raising.
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

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "traigent-first-run" / "scripts"
PREFLIGHT = SCRIPTS / "preflight.py"
READINESS = SCRIPTS / "readiness.py"

UTF8_ROW = '{"input": "café 日本", "output": "b"}\n{"input": "c", "output": "d"}\n'
LATIN1_ROW = '{"input": "café", "output": "b"}\n{"input": "c", "output": "d"}\n'
# A key the SDK would accept; the value is a placeholder, never a real secret.
ENV_LINE = "OPENAI_API_KEY=sk-placeholder-not-a-secret\n"


def c_locale_run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a script the way a non-UTF-8 default-encoding customer runs it."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "LC_ALL": "C",
        "PYTHONCOERCECLOCALE": "0",
    }
    return subprocess.run(
        [sys.executable, "-X", "utf8=0", "-I", "-S", "-B", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class PreflightReadsCustomerFilesAsUtf8Tests(unittest.TestCase):
    def preflight(
        self, directory: Path, dataset_bytes: bytes, env_bytes: bytes
    ) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
        dataset = directory / "data.jsonl"
        dataset.write_bytes(dataset_bytes)
        env_path = directory / ".env"
        env_path.write_bytes(env_bytes)
        env_path.chmod(0o600)
        result = c_locale_run(
            [
                str(PREFLIGHT),
                "--project-root",
                str(directory),
                "--env",
                str(env_path),
                "--dataset",
                str(dataset),
                "--offline",
                "--defer-missing-sdk",
                "--json",
            ],
            cwd=directory,
        )
        payload = json.loads(result.stdout) if result.stdout.strip() else []
        return result, payload

    @staticmethod
    def record(payload: list[dict], check: str) -> dict:
        return next(item for item in payload if item["check"] == check)

    def test_utf8_dataset_and_env_read_identically_under_c_locale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result, payload = self.preflight(
                Path(directory), UTF8_ROW.encode("utf-8"), ENV_LINE.encode("utf-8")
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.record(payload, "dataset-shape")["status"], "PASS")

    def test_latin1_dataset_is_a_named_fail_not_an_internal_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result, payload = self.preflight(
                Path(directory), LATIN1_ROW.encode("latin-1"), ENV_LINE.encode("utf-8")
            )
        self.assertNotIn("internal error", result.stdout + result.stderr)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        record = self.record(payload, "dataset-shape")
        self.assertEqual(record["status"], "FAIL")
        self.assertRegex(record["detail"], r"not valid UTF-8 .*line 1")
        # The detail names the problem without echoing any customer bytes.
        self.assertNotIn("caf", record["detail"])

    def test_latin1_env_is_a_named_fail_and_no_credential_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result, payload = self.preflight(
                Path(directory),
                UTF8_ROW.encode("utf-8"),
                "# café\nOPENAI_API_KEY=sk-placeholder\n".encode("latin-1"),
            )
        self.assertNotIn("internal error", result.stdout + result.stderr)
        self.assertEqual(self.record(payload, "env-file")["status"], "FAIL")
        self.assertNotEqual(
            self.record(payload, "provider-credentials")["status"], "PASS"
        )

    def test_bom_env_is_not_read_as_a_credential(self) -> None:
        # python-dotenv keeps a byte-order mark in the first key, so the SDK
        # runtime never sees OPENAI_API_KEY. Preflight must agree with that.
        with tempfile.TemporaryDirectory() as directory:
            result, payload = self.preflight(
                Path(directory),
                UTF8_ROW.encode("utf-8"),
                b"\xef\xbb\xbf" + ENV_LINE.encode("utf-8"),
            )
        self.assertNotIn("internal error", result.stdout + result.stderr)
        record = self.record(payload, "env-file")
        self.assertEqual(record["status"], "WARN")
        # The cause is the mark, not the name: the name is a legal one.
        self.assertRegex(record["detail"], r"byte-order mark")
        self.assertRegex(record["detail"], r"re-save .*without it")
        self.assertNotEqual(
            self.record(payload, "provider-credentials")["status"], "PASS"
        )

    def test_the_decode_error_line_agrees_with_the_line_numbers_elsewhere(
        self,
    ) -> None:
        # The bad byte is on line 3 under LF, CRLF and CR-only line endings. The
        # `.env` grammar and `splitlines` count a lone CR as a break, so the
        # named line must too.
        bad_env = {
            "lf": b"A=1\nB=2\nC=\xff\n",
            "crlf": b"A=1\r\nB=2\r\nC=\xff\r\n",
            "cr": b"A=1\rB=2\rC=\xff\r",
        }
        for label, env_bytes in bad_env.items():
            with self.subTest(env=label), tempfile.TemporaryDirectory() as directory:
                result, payload = self.preflight(
                    Path(directory), UTF8_ROW.encode("utf-8"), env_bytes
                )
                self.assertNotIn("internal error", result.stdout + result.stderr)
                record = self.record(payload, "env-file")
                self.assertEqual(record["status"], "FAIL")
                self.assertRegex(record["detail"], r"bad byte at line 3\b")
        row_3 = b'{"input": "c", "output": "d"}'
        row_3_bad = b'{"input": "caf\xe9", "output": "d"}'
        bad_dataset = {
            "lf": b"\n".join([row_3, row_3, row_3_bad]) + b"\n",
            "crlf": b"\r\n".join([row_3, row_3, row_3_bad]) + b"\r\n",
            "cr": b"\r".join([row_3, row_3, row_3_bad]) + b"\r",
        }
        for label, dataset_bytes in bad_dataset.items():
            with self.subTest(
                dataset=label
            ), tempfile.TemporaryDirectory() as directory:
                result, payload = self.preflight(
                    Path(directory), dataset_bytes, ENV_LINE.encode("utf-8")
                )
                self.assertNotIn("internal error", result.stdout + result.stderr)
                record = self.record(payload, "dataset-shape")
                self.assertEqual(record["status"], "FAIL")
                self.assertRegex(record["detail"], r"bad byte at line 3\b")


class ReadinessPreflightInputEncodingTests(unittest.TestCase):
    def test_utf8_preflight_document_loads_under_c_locale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "data.jsonl"
            dataset.write_bytes(UTF8_ROW.encode("utf-8"))
            env_path = root / ".env"
            env_path.write_bytes(ENV_LINE.encode("utf-8"))
            env_path.chmod(0o600)
            produced = c_locale_run(
                [
                    str(PREFLIGHT),
                    "--project-root",
                    str(root),
                    "--env",
                    str(env_path),
                    "--dataset",
                    str(dataset),
                    "--offline",
                    "--defer-missing-sdk",
                    "--json",
                ],
                cwd=root,
            )
            self.assertEqual(produced.returncode, 0, produced.stdout + produced.stderr)
            report = root / "preflight.json"
            report.write_bytes(produced.stdout.encode("utf-8"))
            result = c_locale_run(
                [str(READINESS), "--preflight", str(report)], cwd=root
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("internal error", result.stdout + result.stderr)

    def test_latin1_preflight_document_is_a_named_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "preflight.json"
            report.write_bytes('[{"check": "café"}]'.encode("latin-1"))
            result = c_locale_run(
                [str(READINESS), "--preflight", str(report)], cwd=root
            )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(str(report), result.stderr)
        self.assertNotIn("internal error", result.stdout + result.stderr)

    def test_a_utf8_bom_preflight_document_loads(self) -> None:
        # PowerShell 5.1's `Out-File -Encoding utf8` writes a byte-order mark,
        # which is not JSON. `load_json` reads it with utf-8-sig for that reason.
        records = [
            {"check": "dataset-shape", "status": "FAIL", "detail": "x", "metrics": None}
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "preflight.json"
            report.write_bytes(b"\xef\xbb\xbf" + json.dumps(records).encode("utf-8"))
            result = c_locale_run(
                [str(READINESS), "--preflight", str(report), "--json"], cwd=root
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("internal error", result.stdout + result.stderr)

    def test_latin1_preflight_on_stdin_is_a_named_input_error(self) -> None:
        # The file path converts its decode error to a named OSError; stdin is
        # read raw, so its UnicodeDecodeError must be named by the boundary.
        # `:strict` is what makes stdin raise: the C locale's default is
        # surrogateescape, which reads these bytes without error. `-I` is not
        # passed, because isolated mode ignores PYTHONIOENCODING.
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8:strict",
        }
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8=0",
                "-S",
                "-B",
                str(READINESS),
                "--preflight",
                "-",
            ],
            input='[{"check": "café"}]'.encode("latin-1"),
            cwd=tempfile.gettempdir(),
            env=env,
            capture_output=True,
            check=False,
        )
        stderr = result.stderr.decode("utf-8", errors="replace")
        self.assertEqual(result.returncode, 2, stderr)
        self.assertIn("cannot read scoring input", stderr)
        self.assertNotIn("internal error", stderr)


class CalibrateLiteralOrFileReadsBomTests(unittest.TestCase):
    """A BOM-prefixed `@file` argument loads, as the readiness document does."""

    def test_a_bom_prefixed_at_file_argument_loads(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "calibrate_evaluator_under_test", SCRIPTS / "calibrate_evaluator.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "expected.json"
            path.write_bytes(b"\xef\xbb\xbf" + b'{"a": 1}')
            self.assertEqual(module.literal_or_file(f"@{path}"), {"a": 1})


if __name__ == "__main__":
    unittest.main()

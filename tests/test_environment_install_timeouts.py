"""Bounded-time checks for the wheel download and isolated pip steps.

Every server here listens on 127.0.0.1 only, and every thread is joined in
tearDown so a stalled fixture can never hang the suite.
"""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/traigent-first-run/scripts/environment_install.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "environment_install_under_test", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ServerFixture(unittest.TestCase):
    def start_server(self, handler_class) -> str:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        server.daemon_threads = True
        server.release = threading.Event()  # handlers wait on or poll this
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.shutdown, server, thread)
        host, port = server.server_address[:2]
        return f"http://{host}:{port}/pkg-1.0-py3-none-any.whl"

    def shutdown(self, server, thread) -> None:
        server.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "server thread did not stop")


class StalledHandler(BaseHTTPRequestHandler):
    """Sends headers promising 1,000,000 bytes, 10 bytes of body, then stalls."""

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", "1000000")
        self.end_headers()
        self.wfile.write(b"x" * 10)
        self.wfile.flush()
        # Hold the connection open; the owning test releases this at teardown.
        self.server.release.wait(10)

    def log_message(self, *args):
        pass


class SlowDripHandler(BaseHTTPRequestHandler):
    """Sends one byte every 0.2 s for a 1,000,000-byte body, never finishing."""

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", "1000000")
        self.end_headers()
        try:
            for _ in range(200):
                if self.server.release.is_set():
                    return
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(0.2)
        except OSError:
            return

    def log_message(self, *args):
        pass


class DownloadDeadlineTests(ServerFixture):
    def test_stalled_body_is_bounded_and_partial_file_removed(self):
        module = load_module()
        url = self.start_server(StalledHandler)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            started = time.monotonic()
            with self.assertRaises(ValueError) as raised:
                module._download(url, target, read_timeout=0.5, deadline=5)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 8, "stalled download was not bounded")
            self.assertIn("stalled", str(raised.exception))
            self.assertFalse(target.exists(), "partial wheel must be removed")

    def test_slow_drip_hits_overall_deadline(self):
        module = load_module()
        url = self.start_server(SlowDripHandler)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            started = time.monotonic()
            with self.assertRaises(ValueError) as raised:
                module._download(url, target, read_timeout=1, deadline=1.5)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 4, "slow drip was not bounded by the deadline")
            self.assertIn("stalled", str(raised.exception))
            self.assertFalse(target.exists())


class IsolatedPipTimeoutTests(unittest.TestCase):
    def test_pip_timeout_is_bounded_and_leaks_no_child_output(self):
        module = load_module()
        secret_output = b"https://user:secret@host/x"
        expired = subprocess.TimeoutExpired(
            cmd=["pip"], timeout=0.1, output=secret_output
        )
        with (
            mock.patch.object(module, "PIP_TIMEOUT_SECONDS", 0.1),
            mock.patch.object(module.subprocess, "run", side_effect=expired) as run,
            mock.patch.object(
                module.ENV, "trusted_interpreter", return_value=Path("/usr/bin/python3")
            ),
        ):
            with self.assertRaises(ValueError) as raised:
                module.isolated_pip(
                    Path("/tmp/candidate"), ["install", "x"], Path("/tmp")
                )
        self.assertEqual(run.call_args.kwargs.get("timeout"), 0.1)
        message = str(raised.exception)
        self.assertIn("0.1", message)
        self.assertNotIn("secret", message)
        self.assertNotIn("https://", message)
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(raised.exception.__suppress_context__)


if __name__ == "__main__":
    unittest.main()

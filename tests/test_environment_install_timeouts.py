"""Bounded-time checks for the wheel download and isolated pip steps.

Every server here listens on 127.0.0.1 only, and every server thread is joined
in its cleanup so a stalled fixture can never hang the suite. Download worker
threads are daemons: by design they may outlive a test by a few seconds, because
a stalled name lookup cannot be interrupted.
"""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib import error as urllib_error

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


class HeaderDripHandler(BaseHTTPRequestHandler):
    """Sends a status line, then one header byte every 0.2 s, never ending headers."""

    protocol_version = "HTTP/1.1"

    def handle_one_request(self):
        self.raw_requestline = self.rfile.readline(65537)
        self.wfile.write(b"HTTP/1.1 200 OK\r\n")
        self.wfile.flush()
        try:
            self.wfile.write(b"X-Drip: ")
            for _ in range(100):
                if self.server.release.is_set():
                    return
                self.wfile.write(b"a")
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
                # The deadline is far above the read timeout, so only the per-read
                # socket timeout can end this stall within the elapsed bound.
                module._download(url, target, read_timeout=0.5, deadline=30)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 5, "per-read timeout did not bound the stall")
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

    def test_header_drip_is_bounded_by_overall_deadline(self):
        module = load_module()
        url = self.start_server(HeaderDripHandler)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            started = time.monotonic()
            with self.assertRaises(ValueError) as raised:
                module._download(url, target, read_timeout=1, deadline=1.5)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 4, "header drip ran past the overall deadline")
            self.assertIn("stalled", str(raised.exception))
            self.assertFalse(target.exists())

    def test_slow_name_lookup_is_bounded_by_overall_deadline(self):
        module = load_module()

        def slow_lookup(*args, **kwargs):
            time.sleep(5)
            raise OSError("lookup finished after the test ended")

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            with mock.patch("socket.getaddrinfo", side_effect=slow_lookup):
                started = time.monotonic()
                with self.assertRaises(ValueError) as raised:
                    module._download(
                        "http://dns-stall.invalid/x.whl",
                        target,
                        read_timeout=1,
                        deadline=1,
                    )
                elapsed = time.monotonic() - started
            self.assertLess(elapsed, 3, "DNS lookup ran past the overall deadline")
            self.assertIn("stalled", str(raised.exception))
            self.assertFalse(target.exists())

    def test_connect_timeout_maps_to_stalled_message_without_partial_file(self):
        module = load_module()
        connect_stall = urllib_error.URLError(TimeoutError("timed out"))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            with mock.patch.object(
                module.urllib.request, "urlopen", side_effect=connect_stall
            ):
                with self.assertRaises(ValueError) as raised:
                    module._download(
                        "http://127.0.0.1:9/x.whl", target, read_timeout=0.5, deadline=5
                    )
            self.assertIn("stalled", str(raised.exception))
            self.assertFalse(target.exists())


class CacheWheelTests(unittest.TestCase):
    def test_cache_wheel_downloads_through_bounded_helper(self):
        module = load_module()
        payload = b"wheel-bytes"
        url = "https://files.example.invalid/pkg-1.0-py3-none-any.whl"
        item = {
            "download_info": {
                "url": url,
                "archive_info": {
                    "hashes": {"sha256": hashlib.sha256(payload).hexdigest()}
                },
            },
            "metadata": {"name": "pkg", "version": "1.0"},
        }

        def fake_download(url_arg, target, read_timeout, deadline):
            target.write_bytes(payload)

        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(
                module, "_download", side_effect=fake_download
            ) as download,
            mock.patch.object(
                module.urllib.request,
                "urlopen",
                side_effect=AssertionError("unbounded"),
            ),
        ):
            cached = module.cache_wheel(item, Path(directory))
            download.assert_called_once_with(
                url,
                Path(directory) / "pkg-1.0-py3-none-any.whl",
                module.DOWNLOAD_READ_TIMEOUT_SECONDS,
                module.DOWNLOAD_DEADLINE_SECONDS,
            )
        self.assertEqual(cached["name"], "pkg")
        self.assertEqual(cached["version"], "1.0")


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
                    Path("/tmp/candidate"),
                    ["install", "x"],
                    Path("/tmp"),
                    changes_environment=True,
                )
        self.assertEqual(run.call_args.kwargs.get("timeout"), 0.1)
        message = str(raised.exception)
        self.assertIn("0.1", message)
        self.assertNotIn("secret", message)
        self.assertNotIn("https://", message)
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(
            raised.exception.__context__, "secret-bearing exception must not be chained"
        )

    def _pip_timeout_message(self, changes_environment: bool) -> str:
        module = load_module()
        expired = subprocess.TimeoutExpired(
            cmd=["pip"], timeout=0.1, output=b"https://user:secret@host/x"
        )
        with (
            mock.patch.object(module, "PIP_TIMEOUT_SECONDS", 0.1),
            mock.patch.object(module.subprocess, "run", side_effect=expired),
            mock.patch.object(
                module.ENV, "trusted_interpreter", return_value=Path("/usr/bin/python3")
            ),
        ):
            with self.assertRaises(ValueError) as raised:
                module.isolated_pip(
                    Path("/tmp/candidate"),
                    ["install", "--dry-run", "x"],
                    Path("/tmp"),
                    changes_environment=changes_environment,
                )
        message = str(raised.exception)
        self.assertNotIn("secret", message)
        self.assertNotIn("https://", message)
        return message

    def test_plan_timeout_reports_that_nothing_changed(self):
        message = self._pip_timeout_message(changes_environment=False)
        self.assertIn("nothing was installed or changed", message)
        self.assertIn("retry plan when the network is stable", message)
        self.assertNotIn("partly changed", message)

    def test_apply_timeout_reports_possible_partial_change_without_inviting_retry(self):
        message = self._pip_timeout_message(changes_environment=True)
        self.assertIn("during apply", message)
        self.assertIn("may be partly changed", message)
        self.assertIn("Stop and inspect it before any further change.", message)
        self.assertNotIn("nothing was installed", message)
        self.assertNotIn("retry", message)
        self.assertNotIn("re-run", message)


if __name__ == "__main__":
    unittest.main()

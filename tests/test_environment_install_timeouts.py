"""Tests for environment_install: bounded timeouts, download and pip hardening, plan handling.

Covers the wheel download and isolated pip steps under time limits, pip output
saving, download size and redirect limits, plan publication and cleanup, signal
exits, and plan-file identity. Every server here listens on 127.0.0.1 only, and
every server thread is joined in its cleanup so a stalled fixture can never hang
the suite. Download worker threads are daemons: by design they may outlive a test
by a few seconds, because a stalled name lookup cannot be interrupted.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import hashlib
import http.client
import importlib.util
import io
import json
import os
import re
import secrets
import shutil
import signal
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib import error as urllib_error

try:
    import resource
except ImportError:  # Windows: the address-space cap below is POSIX-only.
    resource = None

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/traigent-first-run/scripts/environment_install.py"

# os.kill(os.getpid(), ...) on Windows is TerminateProcess, which ends the whole test
# run, and the hang guard needs SIGALRM and rlimits. Skip every such test off POSIX.
POSIX_ONLY = unittest.skipUnless(
    os.name == "posix" and resource is not None,
    "POSIX signals, alarms and rlimits are required",
)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "environment_install_under_test", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def isolate_temp_dir(test: unittest.TestCase) -> Path:
    """Point tempfile at a throwaway directory so pip-output.log never lands in the real temp dir."""
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    patcher = mock.patch.object(tempfile, "tempdir", directory.name)
    patcher.start()
    test.addCleanup(patcher.stop)
    return Path(directory.name)


def saved_output_path(message: str) -> Path:
    """Return the pip-output.log path that a pip failure message names."""
    match = re.search(r" in (.+?pip-output\.log)\. Read it", message)
    if match is None:
        raise AssertionError(f"message names no saved pip output: {message!r}")
    return Path(match.group(1))


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


class SlowButLiveHandler(BaseHTTPRequestHandler):
    """Sends 1 KiB every 0.1 s for a 1,000,000-byte body: never silent for long,
    so only the overall plan deadline can end the transfer."""

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", "1000000")
        self.end_headers()
        try:
            for _ in range(100):
                if self.server.release.is_set():
                    return
                self.wfile.write(b"x" * 1024)
                self.wfile.flush()
                time.sleep(0.1)
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
            self.assertIn("the server sent nothing for 0.5s", str(raised.exception))
            self.assertNotIn("ran out", str(raised.exception))
            self.assertIn("nothing was installed or changed", str(raised.exception))
            self.assertNotIn("retry", str(raised.exception))
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
            self.assertIn("the plan download deadline", str(raised.exception))
            self.assertIn("ran out", str(raised.exception))
            self.assertNotIn("the server sent nothing", str(raised.exception))
            self.assertFalse(target.exists())

    def test_live_slow_transfer_reports_deadline_not_stall(self):
        module = load_module()
        url = self.start_server(SlowButLiveHandler)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            with self.assertRaises(ValueError) as raised:
                module._download(url, target, read_timeout=5, deadline=1.0)
            message = str(raised.exception)
            self.assertIn("did not finish", message)
            self.assertIn("too slow or stalled", message)
            self.assertNotIn("Wheel download stalled", message)
            self.assertNotIn("sent nothing", message)
            self.assertFalse(target.exists(), "partial wheel must be removed")

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
            self.assertIn("ran out", str(raised.exception))
            self.assertNotIn("the server sent nothing", str(raised.exception))
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
            self.assertIn("ran out", str(raised.exception))
            self.assertNotIn("the server sent nothing", str(raised.exception))
            self.assertFalse(target.exists())

    def test_connect_timeout_maps_to_stalled_message_without_partial_file(self):
        module = load_module()
        connect_stall = urllib_error.URLError(TimeoutError("timed out"))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            with mock.patch.object(module, "_open_url", side_effect=connect_stall):
                with self.assertRaises(ValueError) as raised:
                    module._download(
                        "http://127.0.0.1:9/x.whl", target, read_timeout=0.5, deadline=5
                    )
            self.assertIn("the server sent nothing for 0.5s", str(raised.exception))
            self.assertNotIn("ran out", str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertTrue(raised.exception.__suppress_context__)
            self.assertFalse(target.exists())


class EndlessBodyHandler(BaseHTTPRequestHandler):
    """Sends 200 with no Content-Length and an endless body until the client leaves.

    The server stops after 64 MiB regardless, so a regression that stops reading
    late still writes a bounded amount of data before the test fails."""

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        sent = 0
        try:
            while sent < 64 * 1024 * 1024 and not self.server.release.is_set():
                self.wfile.write(b"x" * 65536)
                sent += 65536
        except OSError:
            return

    def log_message(self, *args):
        pass


class DeclaredOversizeHandler(BaseHTTPRequestHandler):
    """Declares a 3 MiB body and sends none: a cap check must fail before any read."""

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(3 * 1024 * 1024))
        self.end_headers()
        self.server.release.wait(10)

    def log_message(self, *args):
        pass


class MalformedLengthHandler(BaseHTTPRequestHandler):
    """Sends a correct 11-byte body under a Content-Length that is not a number."""

    declared_length = "11, 11"

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", self.declared_length)
        self.end_headers()
        self.wfile.write(b"wheel-bytes")
        self.wfile.flush()

    def log_message(self, *args):
        pass


class NonNumericLengthHandler(MalformedLengthHandler):
    declared_length = "abc"


class BlockingResponse:
    """Fake response: one block, then blocks until released (or 5 s)."""

    def __init__(self, release):
        self._release = release
        self._blocks = [b"partial"]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read1(self, size=-1):
        if self._blocks:
            return self._blocks.pop(0)
        self._release.wait(5)
        return b""


class DownloadHardeningTests(ServerFixture):
    def test_unbounded_body_is_capped_and_partial_file_removed(self):
        module = load_module()
        url = self.start_server(EndlessBodyHandler)
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(module, "MAX_WHEEL_BYTES", 2 * 1024 * 1024),
        ):
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            started = time.monotonic()
            with self.assertRaises(ValueError) as raised:
                module._download(url, target, read_timeout=5, deadline=5)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 3, "the size cap did not stop the transfer")
            self.assertIn("exceeded the 2 MiB size limit", str(raised.exception))
            self.assertIn("nothing was installed or changed", str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertTrue(raised.exception.__suppress_context__)
            self.assertFalse(target.exists(), "partial wheel must be removed")

    def test_declared_length_over_cap_fails_before_reading(self):
        module = load_module()
        url = self.start_server(DeclaredOversizeHandler)
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(module, "MAX_WHEEL_BYTES", 2 * 1024 * 1024),
        ):
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            started = time.monotonic()
            with self.assertRaises(ValueError) as raised:
                module._download(url, target, read_timeout=0.5, deadline=5)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 3, "declared length was not checked up front")
            self.assertIn("exceeded the 2 MiB size limit", str(raised.exception))
            self.assertNotIn("sent nothing", str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertTrue(raised.exception.__suppress_context__)
            self.assertFalse(target.exists())

    def test_malformed_content_length_is_ignored_and_valid_body_downloads(self):
        # Proxies can send "11, 11"; the header is advisory, the body is what counts.
        for handler in (MalformedLengthHandler, NonNumericLengthHandler):
            with self.subTest(handler=handler.__name__):
                module = load_module()
                url = self.start_server(handler)
                with tempfile.TemporaryDirectory() as directory:
                    target = Path(directory) / "pkg-1.0-py3-none-any.whl"
                    module._download(url, target, read_timeout=5, deadline=5)
                    self.assertEqual(target.read_bytes(), b"wheel-bytes")


class _FakeResponse:
    """Stands in for the opener's response: a body and a headers mapping."""

    def __init__(self, body, headers=None):
        self._body = io.BytesIO(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read1(self, size=-1):
        return self._body.read1(size)


class SizeCapBoundaryTests(unittest.TestCase):
    CAP = 1024

    def _download(self, body, headers=None):
        module = load_module()
        target_dir = tempfile.TemporaryDirectory()
        self.addCleanup(target_dir.cleanup)
        target = Path(target_dir.name) / "pkg-1.0-py3-none-any.whl"
        with (
            mock.patch.object(module, "MAX_WHEEL_BYTES", self.CAP),
            mock.patch.object(
                module, "_open_url", return_value=_FakeResponse(body, headers)
            ),
        ):
            module._download(
                "https://example.invalid/pkg-1.0-py3-none-any.whl",
                target,
                read_timeout=5,
                deadline=5,
            )
        return target

    def test_body_of_exactly_the_cap_is_accepted(self):
        target = self._download(b"x" * self.CAP)
        self.assertEqual(target.stat().st_size, self.CAP)

    def test_declared_length_of_exactly_the_cap_is_accepted(self):
        target = self._download(b"x" * self.CAP, {"Content-Length": str(self.CAP)})
        self.assertEqual(target.stat().st_size, self.CAP)

    def test_body_one_byte_over_the_cap_is_refused(self):
        with self.assertRaises(ValueError) as raised:
            self._download(b"x" * (self.CAP + 1))
        self.assertIn("exceeded", str(raised.exception))

    def test_declared_length_one_byte_over_the_cap_is_refused(self):
        with self.assertRaises(ValueError) as raised:
            self._download(b"x" * (self.CAP + 1), {"Content-Length": str(self.CAP + 1)})
        self.assertIn("exceeded", str(raised.exception))


class DeclaredLengthParsingTests(unittest.TestCase):
    def test_plain_decimal_with_surrounding_space_is_its_value(self):
        module = load_module()
        self.assertEqual(module._declared_length(" 12 "), 12)
        self.assertEqual(module._declared_length("0"), 0)

    def test_absent_or_non_plain_decimal_values_are_none(self):
        module = load_module()
        # str.isdigit() accepts "²" (int() then raises) and "١٢" (int() parses it).
        # Only the ASCII check rejects both: Content-Length is ASCII digits only.
        for value in (None, "", "1,2", "-1", "1e3", "12abc", "²", "١٢"):
            with self.subTest(value=value):
                self.assertIsNone(module._declared_length(value))


class DownloadRefusalAndInterruptTests(unittest.TestCase):
    def test_http_client_invalid_url_error_text_is_withheld_and_not_chained(self):
        module = load_module()
        error = http.client.InvalidURL("nonnumeric port: 'https://alice:S3CRET@h/x'")
        self.assert_download_error_is_safe(module, error)

    def test_url_error_text_is_withheld_and_not_chained(self):
        module = load_module()
        error = urllib_error.URLError("https://alice:S3CRET@h/x unreachable")
        self.assert_download_error_is_safe(module, error)

    def test_http_error_is_withheld_and_not_chained(self):
        module = load_module()
        error = urllib_error.HTTPError(
            "https://alice:S3CRET@h/x.whl", 500, "Server Error", None, None
        )
        self.assert_download_error_is_safe(module, error)

    def assert_download_error_is_safe(self, module, error):
        url = "https://alice:S3CRET@h/x.whl"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            with mock.patch.object(module, "_open_url", side_effect=error):
                with self.assertRaises(ValueError) as raised:
                    module._download(url, target, read_timeout=5, deadline=5)
            err = raised.exception
            self.assertNotIn("S3CRET", str(err))
            self.assertNotIn("S3CRET", "".join(traceback.format_exception(err)))
            self.assertIsNone(err.__cause__)
            self.assertIsNone(err.__context__)
            self.assertIn("Wheel download failed", str(err))
            self.assertIn("nothing was installed or changed", str(err))
            self.assertIn(type(error).__name__, str(err))
            self.assertNotIn("h/x.whl", str(err))
            self.assertNotIn("://", str(err))
            if isinstance(error, urllib_error.HTTPError):
                self.assertIn(f"HTTP {error.code}", str(err))
            self.assertFalse(target.exists(), "partial wheel must be removed")

    def test_https_to_http_redirect_is_refused(self):
        module = load_module()
        handler = module._NoDowngradeRedirectHandler()
        request = urllib.request.Request("https://h/x.whl")
        with self.assertRaises(module._HttpsDowngradeRefused):
            handler.redirect_request(request, None, 302, "Found", {}, "http://h/x.whl")

    def test_https_redirect_to_any_non_https_scheme_is_refused(self):
        module = load_module()
        handler = module._NoDowngradeRedirectHandler()
        request = urllib.request.Request("https://h/x.whl")
        for target in ("ftp://h/x.whl", "file:///tmp/x.whl"):
            with self.subTest(target=target):
                with self.assertRaises(module._HttpsDowngradeRefused):
                    handler.redirect_request(request, None, 302, "Found", {}, target)

    def test_https_to_https_redirect_is_followed(self):
        module = load_module()
        handler = module._NoDowngradeRedirectHandler()
        request = urllib.request.Request("https://h/x.whl")
        redirected = handler.redirect_request(
            request, None, 302, "Found", {}, "https://h2/x.whl"
        )
        self.assertIsInstance(redirected, urllib.request.Request)
        self.assertEqual(redirected.full_url, "https://h2/x.whl")

    def test_downgrade_refusal_from_transfer_maps_to_value_error(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            with mock.patch.object(
                module, "_open_url", side_effect=module._HttpsDowngradeRefused()
            ):
                with self.assertRaises(ValueError) as raised:
                    module._download(
                        "https://h/x.whl", target, read_timeout=5, deadline=5
                    )
            self.assertEqual(
                str(raised.exception),
                "Wheel download refused a redirect from HTTPS to a non-HTTPS URL; "
                "nothing was installed or changed.",
            )
            self.assertIsNone(raised.exception.__context__)
            self.assertIsNone(raised.exception.__cause__)
            self.assertTrue(raised.exception.__suppress_context__)
            self.assertFalse(target.exists())

    def test_local_write_error_keeps_its_errno_name_without_text_or_path(self):
        module = load_module()
        real_open = Path.open

        class FullDisk:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                self.handle.close()
                return False

            def write(self, data):
                raise OSError(errno.ENOSPC, "No space left on device /secret/path")

            def close(self):
                self.handle.close()

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            with (
                mock.patch.object(
                    Path,
                    "open",
                    lambda path, *a, **k: FullDisk(real_open(path, *a, **k)),
                ),
                mock.patch.object(
                    module, "_open_url", return_value=_FakeResponse(b"wheel-bytes")
                ),
            ):
                with self.assertRaises(ValueError) as raised:
                    module._download(
                        "https://files.example.invalid/x.whl",
                        target,
                        read_timeout=5,
                        deadline=5,
                    )
            message = str(raised.exception)
            self.assertIn("Wheel download failed: OSError (ENOSPC);", message)
            self.assertNotIn("No space left", message)
            self.assertNotIn("/secret/path", message)
            self.assertIsNone(raised.exception.__cause__)
            self.assertTrue(raised.exception.__suppress_context__)
            self.assertFalse(target.exists(), "partial wheel must be removed")

    def test_interrupt_during_download_closes_stream_and_removes_partial_file(self):
        module = load_module()
        release = threading.Event()
        self.addCleanup(release.set)
        opened = []
        real_open = Path.open

        def recording_open(path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            opened.append(handle)
            return handle

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            with (
                mock.patch.object(Path, "open", recording_open),
                mock.patch.object(
                    module,
                    "_open_url",
                    return_value=BlockingResponse(release),
                ),
                mock.patch.object(
                    module.threading.Thread, "join", side_effect=KeyboardInterrupt
                ),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    module._download(
                        "https://files.example.invalid/x.whl",
                        target,
                        read_timeout=5,
                        deadline=5,
                    )
            self.assertEqual(len(opened), 1)
            self.assertTrue(opened[0].closed, "stream must be closed on interrupt")
            self.assertFalse(target.exists(), "partial wheel must be removed")


class OpenerWiringTests(unittest.TestCase):
    """_open_url must go through _OPENER, the only opener that refuses downgrades.

    A local server cannot speak https, so the refusal is checked on the opener's
    handler chain, and the transfer path is checked by recording _OPENER.open.
    """

    def test_open_url_routes_through_the_no_downgrade_opener(self):
        module = load_module()
        redirect_handlers = [
            handler
            for handler in module._OPENER.handlers
            if isinstance(handler, urllib.request.HTTPRedirectHandler)
        ]
        self.assertEqual(len(redirect_handlers), 1)
        self.assertIsInstance(redirect_handlers[0], module._NoDowngradeRedirectHandler)
        self.assertFalse(
            any(
                type(handler) is urllib.request.HTTPRedirectHandler
                for handler in module._OPENER.handlers
            ),
            "a plain HTTPRedirectHandler would follow https->http redirects",
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "pkg-1.0-py3-none-any.whl"
            source.write_bytes(b"wheel")
            with mock.patch.object(
                module._OPENER, "open", wraps=module._OPENER.open
            ) as opened:
                with module._open_url(source.as_uri(), timeout=5) as response:
                    self.assertEqual(response.read(), b"wheel")
        opened.assert_called_once()
        self.assertEqual(opened.call_args.kwargs.get("timeout"), 5)


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
                module,
                "_open_url",
                side_effect=AssertionError("unbounded"),
            ),
        ):
            deadline = time.monotonic() + 100
            cached = module.cache_wheel(item, Path(directory), deadline)
            download.assert_called_once()
            args = download.call_args.args
            self.assertEqual(
                args[:3],
                (
                    url,
                    Path(directory) / "pkg-1.0-py3-none-any.whl",
                    module.DOWNLOAD_READ_TIMEOUT_SECONDS,
                ),
            )
            self.assertLessEqual(args[3], 100)
            self.assertGreater(args[3], 90)
        self.assertEqual(cached["name"], "pkg")
        self.assertEqual(cached["version"], "1.0")


class IsolatedPipTimeoutTests(unittest.TestCase):
    def test_pip_timeout_is_bounded_and_child_output_is_saved_not_printed(self):
        isolate_temp_dir(self)
        module = load_module()
        expired = subprocess.TimeoutExpired(
            cmd=["pip"],
            timeout=0.1,
            output=b"MARKER-7f3a https://user:secret@host/x",
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
        self.assertIn("pip-output.log", message)
        self.assertNotIn("MARKER-7f3a", message)
        self.assertNotIn("secret", message)
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(
            raised.exception.__context__, "secret-bearing exception must not be chained"
        )
        saved = saved_output_path(message).read_bytes()
        self.assertIn(b"https://user:secret@host/x", saved)

    def test_pip_failure_reports_exit_code_and_saves_output(self):
        isolate_temp_dir(self)
        module = load_module()
        failed = subprocess.CompletedProcess(
            args=["pip"], returncode=2, stdout="MARKER-7f3a out", stderr="ERROR: S3CRET"
        )
        with (
            mock.patch.object(module.subprocess, "run", return_value=failed),
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
        message = str(raised.exception)
        self.assertIn("exit code 2", message)
        self.assertNotIn("MARKER-7f3a", message)
        self.assertNotIn("S3CRET", message)
        saved = saved_output_path(message).read_text(encoding="utf-8")
        self.assertIn("MARKER-7f3a", saved)
        self.assertIn("S3CRET", saved)

    def _pip_timeout_message(self, changes_environment: bool) -> str:
        isolate_temp_dir(self)
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
        self.assertIn("The network or dependency resolution stalled.", message)
        self.assertNotIn("retry", message)
        self.assertNotIn("narrow", message)
        self.assertNotIn("partly changed", message)

    def test_apply_timeout_reports_possible_partial_change_without_inviting_retry(self):
        message = self._pip_timeout_message(changes_environment=True)
        self.assertIn("during apply", message)
        self.assertIn("may be partly changed", message)
        self.assertIn("Stop and inspect it before any further change.", message)
        self.assertNotIn("nothing was installed", message)
        self.assertNotIn("retry", message)
        self.assertNotIn("re-run", message)

    def _pip_failure_message(self, changes_environment: bool) -> str:
        isolate_temp_dir(self)
        module = load_module()
        failed = subprocess.CompletedProcess(args=["pip"], returncode=2, stdout="x")
        with (
            mock.patch.object(module.subprocess, "run", return_value=failed),
            mock.patch.object(
                module.ENV, "trusted_interpreter", return_value=Path("/usr/bin/python3")
            ),
            mock.patch.object(module.time, "monotonic", side_effect=[100.0, 142.4]),
        ):
            with self.assertRaises(ValueError) as raised:
                module.isolated_pip(
                    Path("/tmp/candidate"),
                    ["install", "x"],
                    Path("/tmp"),
                    changes_environment=changes_environment,
                )
        return str(raised.exception)

    def test_apply_failure_warns_of_partial_change_without_inviting_retry(self):
        message = self._pip_failure_message(changes_environment=True)
        self.assertTrue(
            message.startswith(
                "Isolated pip failed with exit code 2 during apply after 42s; the "
                "environment may be partly changed. Stop and inspect it before any "
                "further change. "
            ),
            message,
        )
        self.assertNotIn("retry", message)
        self.assertNotIn("nothing was installed", message)

    def test_plan_failure_says_nothing_was_changed(self):
        message = self._pip_failure_message(changes_environment=False)
        self.assertTrue(
            message.startswith(
                "Isolated pip failed with exit code 2 after 42s; nothing was installed "
                "or changed. "
            ),
            message,
        )
        self.assertNotIn("partly changed", message)
        self.assertNotIn("retry", message)


class PipOutputBytesTests(unittest.TestCase):
    """pip's output is captured as bytes: a non-UTF-8 byte is not a decode error.

    Real pip prints `Processing <path>`, and a path can hold \\xe9 under LC_ALL=C.
    With text=True that byte raised UnicodeDecodeError, which main() printed with
    the child's byte and offset, and no log was saved.
    """

    NON_UTF8_LINE = b"Processing /x/\xe9\xff"

    def setUp(self):
        self.temp_root = isolate_temp_dir(self)
        self.module = load_module()

    def _pip_child(self, exit_code):
        """A real child that prints NON_UTF8_LINE bytes and exits with exit_code."""
        fake = self.temp_root / f"fake_pip_{exit_code}.sh"
        fake.write_bytes(
            b"#!/bin/sh\nprintf 'Processing /x/\\351\\377'\nexit %d\n" % exit_code
        )
        fake.chmod(0o700)
        return fake

    def _run_isolated_pip(self, interpreter):
        with mock.patch.object(
            self.module.ENV, "trusted_interpreter", return_value=interpreter
        ):
            self.module.isolated_pip(
                Path("/tmp/candidate"),
                ["install", "x"],
                self.temp_root,
                changes_environment=True,
            )

    def test_pip_is_run_in_bytes_mode(self):
        completed = subprocess.CompletedProcess(
            args=["pip"], returncode=0, stdout=b"", stderr=b""
        )
        with (
            mock.patch.object(
                self.module.subprocess, "run", return_value=completed
            ) as run,
            mock.patch.object(
                self.module.ENV,
                "trusted_interpreter",
                return_value=Path("/usr/bin/python3"),
            ),
        ):
            self.module.isolated_pip(
                Path("/tmp/candidate"),
                ["install", "x"],
                self.temp_root,
                changes_environment=True,
            )
        self.assertFalse(run.call_args.kwargs.get("text", False))
        self.assertFalse(run.call_args.kwargs.get("universal_newlines", False))

    @POSIX_ONLY
    def test_non_utf8_output_from_a_successful_pip_is_not_an_error(self):
        self._run_isolated_pip(self._pip_child(0))
        self.assertEqual(list(self.temp_root.glob("first-run-pip-*")), [])

    @POSIX_ONLY
    def test_non_utf8_output_from_a_failed_pip_is_saved_byte_exact(self):
        with self.assertRaises(ValueError) as raised:
            self._run_isolated_pip(self._pip_child(1))
        message = str(raised.exception)
        self.assertIn("exit code 1", message)
        for fragment in ("codec", "0xff", "position"):
            self.assertNotIn(fragment, message)
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertEqual(
            saved_output_path(message).read_bytes(),
            b"--- stdout ---\n" + self.NON_UTF8_LINE + b"\n--- stderr ---\n",
        )

    def test_timeout_carrying_non_utf8_bytes_is_saved_byte_exact(self):
        expired = subprocess.TimeoutExpired(
            cmd=["pip"], timeout=0.1, output=self.NON_UTF8_LINE
        )
        with (
            mock.patch.object(self.module, "PIP_TIMEOUT_SECONDS", 0.1),
            mock.patch.object(self.module.subprocess, "run", side_effect=expired),
            mock.patch.object(
                self.module.ENV,
                "trusted_interpreter",
                return_value=Path("/usr/bin/python3"),
            ),
        ):
            with self.assertRaises(ValueError) as raised:
                self.module.isolated_pip(
                    Path("/tmp/candidate"),
                    ["install", "x"],
                    self.temp_root,
                    changes_environment=True,
                )
        message = str(raised.exception)
        self.assertIn("Installer stalled", message)
        self.assertNotIn("codec", message)
        self.assertIn(self.NON_UTF8_LINE, saved_output_path(message).read_bytes())


class PipOutputFileTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = isolate_temp_dir(self)

    def pip_error(self, module, outcome, changes_environment=True):
        """Run isolated_pip with pip replaced by outcome (an exception or a result)."""
        if isinstance(outcome, BaseException):
            run = mock.patch.object(module.subprocess, "run", side_effect=outcome)
        else:
            run = mock.patch.object(module.subprocess, "run", return_value=outcome)
        with (
            mock.patch.object(module, "PIP_TIMEOUT_SECONDS", 0.1),
            run,
            mock.patch.object(
                module.ENV, "trusted_interpreter", return_value=Path("/usr/bin/python3")
            ),
        ):
            with self.assertRaises(ValueError) as raised:
                module.isolated_pip(
                    Path("/tmp/candidate"),
                    ["install", "x"],
                    Path("/tmp"),
                    changes_environment=changes_environment,
                )
        return raised.exception

    @unittest.skipIf(os.name == "nt", "owner-only is a POSIX permission check")
    def test_output_file_and_directory_are_owner_only(self):
        module = load_module()
        path = saved_output_path(module._save_pip_output(b"out", b"err"))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual(path.parent.parent.resolve(), self.temp_root.resolve())

    def test_save_failure_still_reports_the_stall_without_chaining(self):
        module = load_module()
        expired = subprocess.TimeoutExpired(cmd=["pip"], timeout=0.1, output=b"x")
        with mock.patch.object(
            module.tempfile, "mkdtemp", side_effect=PermissionError("denied")
        ):
            error = self.pip_error(module, expired)
        message = str(error)
        self.assertIn("Installer stalled", message)
        self.assertIn("could not be saved (PermissionError)", message)
        self.assertIsNone(error.__context__)

    def test_write_failing_after_the_file_exists_leaves_no_partial_copy(self):
        module = load_module()
        real_fdopen = os.fdopen

        class FailsOnSecondWrite:
            def __init__(self, stream):
                self.stream = stream
                self.writes = 0

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                self.stream.close()
                return False

            def write(self, data):
                self.writes += 1
                if self.writes == 2:
                    raise OSError(errno.ENOSPC, "No space left on device")
                return self.stream.write(data)

        with mock.patch.object(
            module.os,
            "fdopen",
            side_effect=lambda fd, mode: FailsOnSecondWrite(real_fdopen(fd, mode)),
        ):
            message = module._save_pip_output(b"out", b"err")
        self.assertIn("could not be saved (OSError)", message)
        self.assertNotIn("No space left", message)
        self.assertEqual(
            list(self.temp_root.glob("first-run-pip-*")),
            [],
            "a failed save must remove its partial file and directory",
        )

    def test_failed_open_leaves_no_empty_directory(self):
        module = load_module()
        real_open = os.open

        def open_refuses_only_the_log(path, *args, **kwargs):
            # shutil.rmtree uses os.open too, so only the log file is refused.
            if str(path).endswith("pip-output.log"):
                raise PermissionError("denied")
            return real_open(path, *args, **kwargs)

        with mock.patch.object(
            module.os, "open", side_effect=open_refuses_only_the_log
        ):
            message = module._save_pip_output(b"out", b"err")
        self.assertIn("could not be saved (PermissionError)", message)
        self.assertEqual(
            list(self.temp_root.glob("first-run-pip-*")),
            [],
            "a failed save must remove the empty directory it created",
        )

    def test_failed_cleanup_names_the_directory_and_says_to_delete_it(self):
        module = load_module()
        with (
            mock.patch.object(module.os, "open", side_effect=PermissionError("denied")),
            mock.patch.object(
                module.shutil, "rmtree", side_effect=OSError(errno.EBUSY, "busy")
            ),
        ):
            message = module._save_pip_output(b"out", b"err")
        directories = list(self.temp_root.glob("first-run-pip-*"))
        self.assertEqual(len(directories), 1)
        self.assertIn("could not be saved (PermissionError)", message)
        self.assertIn(
            f"; a partial copy may remain in {directories[0]}: delete it", message
        )
        self.assertNotIn("busy", message)

    def test_stall_and_failure_messages_report_elapsed_seconds(self):
        module = load_module()
        expired = subprocess.TimeoutExpired(cmd=["pip"], timeout=0.1)
        failed = subprocess.CompletedProcess(args=["pip"], returncode=1)
        cases = (
            (expired, False, "(stopped after 42s)"),
            (expired, True, "during apply (stopped after 42s)"),
            (failed, True, "failed with exit code 1 during apply after 42s;"),
            (failed, False, "failed with exit code 1 after 42s; nothing was installed"),
        )
        for outcome, changes, expected in cases:
            with self.subTest(expected=expected):
                with mock.patch.object(
                    module.time, "monotonic", side_effect=[100.0, 142.4]
                ):
                    error = self.pip_error(module, outcome, changes_environment=changes)
                self.assertIn(expected, str(error))

    def test_no_child_byte_reaches_the_message(self):
        module = load_module()
        stdout = secrets.token_urlsafe(3072)  # about 4 KiB of text
        stderr = secrets.token_urlsafe(3072)
        fragments = {
            text[i : i + 8] for text in (stdout, stderr) for i in range(len(text) - 7)
        }
        for label, outcome, changes in (
            (
                "stall during apply",
                subprocess.TimeoutExpired(
                    cmd=["pip"],
                    timeout=0.1,
                    output=stdout.encode(),
                    stderr=stderr.encode(),
                ),
                True,
            ),
            (
                "stall during plan",
                subprocess.TimeoutExpired(
                    cmd=["pip"],
                    timeout=0.1,
                    output=stdout.encode(),
                    stderr=stderr.encode(),
                ),
                False,
            ),
            (
                "failure",
                subprocess.CompletedProcess(
                    args=["pip"], returncode=1, stdout=stdout, stderr=stderr
                ),
                True,
            ),
        ):
            with self.subTest(label):
                message = str(
                    self.pip_error(module, outcome, changes_environment=changes)
                )
                leaked = [fragment for fragment in fragments if fragment in message]
                self.assertEqual(leaked, [], "child output reached the message")

    def test_each_failure_writes_its_own_file(self):
        module = load_module()
        first = self.pip_error(
            module,
            subprocess.CompletedProcess(
                args=["pip"], returncode=1, stdout="first run\n", stderr=""
            ),
            changes_environment=False,
        )
        first_path = saved_output_path(str(first))
        first_bytes = first_path.read_bytes()
        second = self.pip_error(
            module,
            subprocess.CompletedProcess(
                args=["pip"], returncode=1, stdout="second run\n", stderr=""
            ),
            changes_environment=False,
        )
        second_path = saved_output_path(str(second))
        self.assertNotEqual(first_path, second_path)
        self.assertEqual(first_path.read_bytes(), first_bytes)
        self.assertEqual(
            second_path.read_text(encoding="utf-8"),
            "--- stdout ---\nsecond run\n\n--- stderr ---\n",
        )


class ReadOnlyBlocksResponse:
    """Fake response that implements only read1, so any call to read() fails loudly."""

    def __init__(self, blocks):
        self._blocks = list(blocks)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read1(self, size=-1):
        return self._blocks.pop(0)


class LateBytesResponse:
    """Fake response whose first read1 blocks until released, then returns bytes once."""

    def __init__(self, release):
        self._release = release
        self._blocks = [b"late-bytes", b""]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read1(self, size=-1):
        if self._blocks[0] == b"late-bytes":
            self._release.wait(5)
        return self._blocks.pop(0)


class EndlessBlocksResponse:
    """Fake response that yields one small block per read1 until released."""

    def __init__(self, stop):
        self._stop = stop

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read1(self, size=-1):
        if self._stop.is_set():
            return b""
        time.sleep(0.001)
        return b"x" * 1024


class DownloadReadCallTests(unittest.TestCase):
    def test_body_is_streamed_block_by_block_with_read1(self):
        module = load_module()
        response = ReadOnlyBlocksResponse([b"wheel-", b"bytes", b""])
        url = "https://files.example.invalid/pkg-1.0-py3-none-any.whl"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            with mock.patch.object(module, "_open_url", return_value=response):
                module._download(url, target, 5, 5)
            self.assertEqual(target.read_bytes(), b"wheel-bytes")

    def test_worker_abandoned_by_the_deadline_writes_nothing_more(self):
        module = load_module()
        release = threading.Event()
        url = "https://files.example.invalid/pkg-1.0-py3-none-any.whl"
        before = set(threading.enumerate())
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(
                module, "_open_url", return_value=LateBytesResponse(release)
            ),
            mock.patch.object(threading, "excepthook") as hook,
        ):
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            with self.assertRaises(ValueError) as raised:
                module._download(url, target, 5, 0.05)
            self.assertIn("deadline", str(raised.exception))
            (worker,) = [
                thread
                for thread in threading.enumerate()
                if thread not in before and thread.name == "wheel-download"
            ]
            release.set()
            worker.join(5)
            self.assertFalse(worker.is_alive(), "abandoned worker did not finish")
            self.assertFalse(target.exists(), "abandoned worker wrote the wheel")
            hook.assert_not_called()

    def test_deadline_closes_the_stream_before_removing_the_target(self):
        # An abandoned worker must not keep writing: the caller closes the stream
        # first, then unlinks, so nothing can reach the removed file afterwards.
        module = load_module()
        stop = threading.Event()
        self.addCleanup(stop.set)
        url = "https://files.example.invalid/pkg-1.0-py3-none-any.whl"
        opened = []
        events = []
        real_open = Path.open
        real_unlink = Path.unlink
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"

            def recording_open(path, *args, **kwargs):
                handle = real_open(path, *args, **kwargs)
                if Path(path) == target:
                    opened.append(handle)
                return handle

            def recording_unlink(path, *args, **kwargs):
                if Path(path) == target:
                    events.append(("unlink", opened[0].closed))
                return real_unlink(path, *args, **kwargs)

            with (
                mock.patch.object(Path, "open", recording_open),
                mock.patch.object(Path, "unlink", recording_unlink),
                mock.patch.object(
                    module, "_open_url", return_value=EndlessBlocksResponse(stop)
                ),
            ):
                with self.assertRaises(ValueError) as raised:
                    module._download(url, target, 5, 0.2)
            self.assertIn("deadline", str(raised.exception))
            self.assertEqual(len(opened), 1)
            self.assertEqual(
                events,
                [("unlink", True)],
                "the stream must be closed before the target is unlinked",
            )
            self.assertTrue(opened[0].closed, "abandoned stream left open")
            stop.set()
            time.sleep(0.2)
            self.assertFalse(target.exists(), "abandoned worker recreated the target")


@unittest.skipUnless(os.name == "posix", "the fake interpreter is a POSIX shell script")
class RealStalledChildTests(unittest.TestCase):
    def test_real_stalled_child_is_killed_and_child_output_is_saved(self):
        isolate_temp_dir(self)
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            fake_interpreter = Path(directory) / "fake-python"
            fake_interpreter.write_text(
                "#!/bin/sh\n"
                "echo 'https://user:secret@example.invalid/simple'\n"
                "exec sleep 30\n",
                encoding="utf-8",
            )
            fake_interpreter.chmod(0o755)
            with (
                mock.patch.object(module, "PIP_TIMEOUT_SECONDS", 1),
                mock.patch.object(
                    module.ENV, "trusted_interpreter", return_value=fake_interpreter
                ),
            ):
                started = time.monotonic()
                with self.assertRaises(ValueError) as raised:
                    module.isolated_pip(
                        Path(directory),
                        ["install", "x"],
                        Path(directory),
                        changes_environment=False,
                    )
                elapsed = time.monotonic() - started
        self.assertLess(elapsed, 10, "stalled child was not killed at the bound")
        self.assertIn("Installer stalled", str(raised.exception))
        self.assertNotIn("secret", str(raised.exception))
        self.assertIn("pip-output.log", str(raised.exception))
        self.assertIsNone(
            raised.exception.__context__, "secret-bearing exception must not be chained"
        )


WHEEL_ITEM = {
    "download_info": {
        "url": "https://files.example.invalid/pkg-1.0-py3-none-any.whl",
        "archive_info": {"hashes": {"sha256": "0" * 64}},
    },
    "metadata": {"name": "pkg", "version": "1.0"},
}
BEFORE = {"installed": {}, "identity": "id"}
AFTER = {"installed": {"pkg": "1.0"}, "identity": "id"}
INSTALLED = {"installed": {"pkg": "1.0"}, "identity": "id"}


class SlowFirstReadResponse:
    """Fake response that stalls once before its first block, then answers at once."""

    def __init__(self, delay, blocks):
        self._delay = delay
        self._blocks = list(blocks)
        self._first = True

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read1(self, size=-1):
        if self._first:
            self._first = False
            time.sleep(self._delay)
        return self._blocks.pop(0)


class PlanDownloadBudgetTests(unittest.TestCase):
    def test_plan_shares_one_download_budget_across_wheels(self):
        module = load_module()
        payload = b"wheel"
        digest = hashlib.sha256(payload).hexdigest()
        items = [
            {
                "download_info": {
                    "url": f"https://files.example.invalid/{name}-1.0-py3-none-any.whl",
                    "archive_info": {"hashes": {"sha256": digest}},
                },
                "metadata": {"name": name, "version": "1.0"},
            }
            for name in ("alpha", "beta")
        ]
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        candidate = root / "env"
        candidate.mkdir()
        requirements = root / "requirements.txt"
        requirements.write_text("alpha==1.0\nbeta==1.0\n", encoding="utf-8")
        plan_path = root / "approval.json"
        options = argparse.Namespace(
            candidate=candidate,
            requirements=requirements,
            plan=plan_path,
            change=[],
            no_index=False,
            find_links=None,
        )
        before = {"installed": {}, "identity": "id"}

        def fake_pip(candidate_arg, arguments, working, *, changes_environment):
            report = Path(arguments[arguments.index("--report") + 1])
            report.write_text(json.dumps({"install": items}), encoding="utf-8")

        def fake_open_url(url, timeout):
            # Each wheel takes 0.6 s, which fits a 1.0 s budget only once.
            return SlowFirstReadResponse(0.6, [payload, b""])

        patches = (
            mock.patch.object(module, "PLAN_DOWNLOAD_DEADLINE_SECONDS", 1.0),
            mock.patch.object(module, "snapshot", return_value=before),
            mock.patch.object(
                module.ENV, "read_pins", return_value={"alpha": "1.0", "beta": "1.0"}
            ),
            mock.patch.object(
                module.ENV, "approval_card", return_value={"new": [], "changes": []}
            ),
            mock.patch.object(module, "isolated_pip", side_effect=fake_pip),
            mock.patch.object(module, "_open_url", side_effect=fake_open_url),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        with self.assertRaises(ValueError) as raised:
            module.plan(options)
        self.assertIn("did not finish", str(raised.exception))
        self.assertIn("too slow or stalled", str(raised.exception))
        self.assertNotIn("Wheel download stalled", str(raised.exception))
        self.assertIn("nothing was installed or changed", str(raised.exception))
        self.assertNotIn("retry", str(raised.exception))
        self.assertEqual(list(root.glob("*-wheels-*")), [])
        self.assertFalse(plan_path.exists())


@contextlib.contextmanager
def _bounded_against_hang_and_unbounded_read(seconds=10, address_space=2 << 30):
    """Fail a regression instead of hanging or exhausting memory.

    A FIFO blocks an unbounded open(); a symlink to /dev/zero makes read_bytes grow
    without end. SIGALRM turns the first into an AssertionError, and an address-space
    cap turns the second into a MemoryError within seconds.
    """

    def stalled(signum, frame):
        raise AssertionError(f"plan() did not return within {seconds} s")

    previous_handler = signal.signal(signal.SIGALRM, stalled)
    previous_limit = resource.getrlimit(resource.RLIMIT_AS)
    _, hard = previous_limit
    capped = (
        address_space if hard == resource.RLIM_INFINITY else min(address_space, hard)
    )
    resource.setrlimit(resource.RLIMIT_AS, (capped, hard))
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        resource.setrlimit(resource.RLIMIT_AS, previous_limit)
        signal.signal(signal.SIGALRM, previous_handler)


class _DiskFullAfterTenBytes:
    """Stream that accepts 10 bytes, then fails the way a full disk does."""

    def __init__(self, stream):
        self._stream = stream

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._stream.close()
        return False

    def write(self, data):
        self._stream.write(data[:10])
        self._stream.flush()
        raise OSError(errno.ENOSPC, "No space left on device")


class PlanApplyHarnessTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.candidate = self.root / "env"
        self.candidate.mkdir()
        self.requirements = self.root / "requirements.txt"
        self.requirements.write_text("pkg==1.0\n", encoding="utf-8")
        self.plan_path = self.root / "approval.json"
        self.options = argparse.Namespace(
            candidate=self.candidate,
            requirements=self.requirements,
            plan=self.plan_path,
            change=[],
            no_index=False,
            find_links=None,
        )
        self.pip_calls = []

    def _fake_pip(self, candidate, arguments, working, *, changes_environment):
        self.pip_calls.append(changes_environment)
        if "--report" in arguments:
            report = Path(arguments[arguments.index("--report") + 1])
            report.write_text(json.dumps({"install": [WHEEL_ITEM]}), encoding="utf-8")

    def _start(self, cache_wheel, snapshots):
        module = self.module
        for patch in (
            mock.patch.object(module, "snapshot", side_effect=snapshots),
            mock.patch.object(module.ENV, "read_pins", return_value={"pkg": "1.0"}),
            mock.patch.object(
                module.ENV,
                "approval_card",
                return_value={"new": [], "changes": []},
            ),
            mock.patch.object(module, "isolated_pip", side_effect=self._fake_pip),
            mock.patch.object(module, "cache_wheel", side_effect=cache_wheel),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_failed_wheel_cache_leaves_no_wheels_directory_and_passes_error_through(
        self,
    ):
        def failing_cache(item, directory, download_deadline):
            (directory / "pkg-1.0-py3-none-any.whl").write_bytes(b"partial")
            raise ValueError("Wheel download stalled: sentinel")

        self._start(failing_cache, [BEFORE, BEFORE])
        with self.assertRaises(ValueError) as raised:
            self.module.plan(self.options)
        self.assertEqual(str(raised.exception), "Wheel download stalled: sentinel")
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])
        self.assertFalse(self.plan_path.exists())

    def test_plan_failure_after_caching_leaves_no_wheels_directory(self):
        # plan() raises FileExistsError on plan_path.open("x") when a concurrent run
        # wrote the plan after resolution. Wheels cached before that must not remain.
        def cache_then_concurrent_plan(item, directory, download_deadline):
            artifact = directory / "pkg-1.0-py3-none-any.whl"
            artifact.write_bytes(b"wheel")
            self.plan_path.write_text("concurrent", encoding="utf-8")
            return {
                "path": str(artifact),
                "sha256": hashlib.sha256(b"wheel").hexdigest(),
                "name": "pkg",
                "version": "1.0",
            }

        self._start(cache_then_concurrent_plan, [BEFORE, BEFORE])
        with self.assertRaises(ValueError) as raised:
            self.module.plan(self.options)
        self._assert_plan_already_exists(raised)
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])
        # The other run's plan is not this call's file: it must be left untouched.
        self.assertEqual(self.plan_path.read_text(encoding="utf-8"), "concurrent")

    def test_interrupt_right_after_cache_creation_leaves_no_wheels_directory(self):
        # plan() reads time.monotonic() for the download deadline immediately after
        # mkdtemp(). A signal landing there must still clean up the cache directory.
        self._start(lambda *args: self.fail("no wheel is cached"), [BEFORE, BEFORE])
        with mock.patch.object(
            self.module.time, "monotonic", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.module.plan(self.options)
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])
        self.assertFalse(self.plan_path.exists())

    def test_plan_write_failure_removes_partial_plan_and_wheels(self):
        def writing_cache(item, directory, download_deadline):
            artifact = directory / "pkg-1.0-py3-none-any.whl"
            artifact.write_bytes(b"wheel")
            return {
                "path": str(artifact),
                "sha256": hashlib.sha256(b"wheel").hexdigest(),
                "name": "pkg",
                "version": "1.0",
            }

        self._start(writing_cache, [BEFORE, BEFORE])
        with mock.patch.object(
            self.module.json,
            "dump",
            side_effect=OSError("No space left on device"),
        ):
            with self.assertRaises(OSError) as raised:
                self.module.plan(self.options)
        self.assertIn("No space left on device", str(raised.exception))
        self.assertFalse(self.plan_path.exists(), "partial plan must be removed")
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])

    def test_plan_cleanup_failures_still_remove_cache_and_name_the_plan(self):
        def writing_cache(item, directory, download_deadline):
            artifact = directory / "pkg-1.0-py3-none-any.whl"
            artifact.write_bytes(b"wheel")
            return {
                "path": str(artifact),
                "sha256": hashlib.sha256(b"wheel").hexdigest(),
                "name": "pkg",
                "version": "1.0",
            }

        self._start(writing_cache, [BEFORE, BEFORE])
        real_unlink = Path.unlink
        real_digest = self.module.ENV.file_digest
        plan_path = self.plan_path

        def unlink_fails_for_plan_only(path, *args, **kwargs):
            if path == plan_path:
                raise PermissionError("locked by another process")
            return real_unlink(path, *args, **kwargs)

        def digest_fails_after_publish(path, *args, **kwargs):
            # The plan is published (linked) before its digest is read, so this
            # failure leaves a complete plan for cleanup to remove or name.
            if Path(path) == plan_path:
                raise OSError("No space left on device")
            return real_digest(path, *args, **kwargs)

        with (
            mock.patch.object(
                self.module.ENV,
                "file_digest",
                side_effect=digest_fails_after_publish,
            ),
            mock.patch.object(Path, "unlink", unlink_fails_for_plan_only),
        ):
            with self.assertRaises(ValueError) as raised:
                self.module.plan(self.options)
        message = str(raised.exception)
        self.assertIn("No space left on device", message)
        self.assertIn(f"Could not remove: {plan_path}", message)
        self.assertIn("delete by hand", message)
        self.assertNotIn("PermissionError", message)
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])

    def test_interrupt_after_plan_written_removes_plan_and_cache(self):
        # The plan digest is computed after the plan file is written; a signal there
        # must still clean up the plan and the wheel cache.
        real_digest = self.module.ENV.file_digest
        plan_path = self.plan_path

        def digest_interrupted_on_plan(path, *args, **kwargs):
            if Path(path) == plan_path:
                raise KeyboardInterrupt
            return real_digest(path, *args, **kwargs)

        def cache_one_wheel(item, directory, download_deadline):
            artifact = directory / "pkg-1.0-py3-none-any.whl"
            artifact.write_bytes(b"wheel")
            return {
                "path": str(artifact),
                "sha256": hashlib.sha256(b"wheel").hexdigest(),
                "name": "pkg",
                "version": "1.0",
            }

        self._start(cache_one_wheel, [BEFORE, BEFORE])
        with (
            mock.patch.object(
                self.module.ENV, "file_digest", side_effect=digest_interrupted_on_plan
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.module.plan(self.options)
        self.assertFalse(self.plan_path.exists())
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])

    def test_cache_removal_failure_message_is_one_sentence(self):
        def failing_cache(item, directory, download_deadline):
            raise ValueError(
                "Wheel download stalled: sentinel; nothing was installed or changed."
            )

        real_rmtree = shutil.rmtree

        def rmtree_fails_for_wheel_cache(path, *args, **kwargs):
            # shutil is shared with tempfile's own cleanup; fail only the cache removal.
            if "-wheels-" in str(path):
                raise OSError("busy")
            return real_rmtree(path, *args, **kwargs)

        self._start(failing_cache, [BEFORE, BEFORE])
        try:
            with mock.patch.object(
                self.module.shutil, "rmtree", side_effect=rmtree_fails_for_wheel_cache
            ):
                with self.assertRaises(ValueError) as raised:
                    self.module.plan(self.options)
        finally:
            for leftover in self.root.glob("*-wheels-*"):
                real_rmtree(leftover)
        message = str(raised.exception)
        self.assertNotIn(".;", message)
        self.assertIn("nothing was installed or changed. Could not remove:", message)
        self.assertIn("-wheels-", message)
        self.assertIn("delete by hand", message)
        # `from None` hides the chained OSError from the traceback.
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertIsNone(raised.exception.__cause__)

    def test_interrupt_during_plan_survives_failed_cache_removal(self):
        def interrupted_cache(item, directory, download_deadline):
            raise KeyboardInterrupt

        real_rmtree = shutil.rmtree

        def rmtree_fails_for_wheel_cache(path, *args, **kwargs):
            # shutil is shared with tempfile's own cleanup; fail only the cache removal.
            if "-wheels-" in str(path):
                raise PermissionError("locked by another process")
            return real_rmtree(path, *args, **kwargs)

        self._start(interrupted_cache, [BEFORE, BEFORE])
        try:
            with mock.patch.object(
                self.module.shutil, "rmtree", side_effect=rmtree_fails_for_wheel_cache
            ):
                # Ctrl-C must propagate as itself, not be rewrapped as a ValueError.
                with self.assertRaises(KeyboardInterrupt):
                    self.module.plan(self.options)
        finally:
            for leftover in self.root.glob("*-wheels-*"):
                real_rmtree(leftover)

    def test_cache_wheel_with_exhausted_deadline_says_nothing_changed(self):
        module = load_module()
        item = {
            "download_info": {
                "url": "https://files.example.invalid/pkg-1.0-py3-none-any.whl",
                "archive_info": {"hashes": {"sha256": "a" * 64}},
            },
            "metadata": {"name": "pkg", "version": "1.0"},
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(module, "_open_url") as open_url,
        ):
            with self.assertRaises(ValueError) as raised:
                module.cache_wheel(item, Path(directory), time.monotonic() - 1)
        open_url.assert_not_called()
        message = str(raised.exception)
        self.assertIn("plan download deadline", message)
        self.assertIn("before every wheel was downloaded", message)
        self.assertIn("nothing was installed or changed", message)
        self.assertNotIn("retry", message)

    def test_plan_and_apply_wire_changes_environment_false_and_true(self):
        def writing_cache(item, directory, download_deadline):
            artifact = directory / "pkg-1.0-py3-none-any.whl"
            artifact.write_bytes(b"wheel")
            return {
                "path": str(artifact),
                "sha256": hashlib.sha256(b"wheel").hexdigest(),
                "name": "pkg",
                "version": "1.0",
            }

        # plan takes two snapshots (before, after resolution); apply takes two.
        self._start(writing_cache, [BEFORE, BEFORE, BEFORE, AFTER])
        self.module.plan(self.options)
        apply_options = argparse.Namespace(
            plan=self.plan_path,
            approved_plan_sha256=self.module.ENV.file_digest(self.plan_path),
        )
        self.module.apply(apply_options)
        self.assertEqual(self.pip_calls, [False, True])

    @unittest.skipIf(os.name == "nt", "POSIX directory modes do not apply on Windows")
    def test_wheel_cache_directory_is_private_to_the_owner(self):
        def writing_cache(item, directory, download_deadline):
            artifact = directory / "pkg-1.0-py3-none-any.whl"
            artifact.write_bytes(b"wheel")
            return {
                "path": str(artifact),
                "sha256": hashlib.sha256(b"wheel").hexdigest(),
                "name": "pkg",
                "version": "1.0",
            }

        self._start(writing_cache, [BEFORE, BEFORE])
        self.module.plan(self.options)
        caches = list(self.root.glob("*-wheels-*"))
        self.assertEqual(len(caches), 1, "plan must leave exactly one wheel cache")
        self.assertTrue(caches[0].is_dir())
        self.assertEqual(stat.S_IMODE(os.stat(caches[0]).st_mode) & 0o077, 0)

    @POSIX_ONLY
    def test_sigterm_during_plan_cleans_wheel_cache_and_exits_143(self):
        # Runs main() end to end: the signal must become SystemExit(143) so the
        # BaseException cleanup in plan() removes the partial cache.
        def sigterm_after_partial_wheel(item, directory, download_deadline):
            (directory / "pkg-1.0-py3-none-any.whl").write_bytes(b"partial")
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(5)

        # Recording handler stands in for the default action, which would end the
        # runner on the pre-fix code.
        previous = signal.signal(signal.SIGTERM, lambda number, frame: None)
        self.addCleanup(signal.signal, signal.SIGTERM, previous)
        self._start(sigterm_after_partial_wheel, [BEFORE, BEFORE])
        argv = [
            "plan",
            "--candidate",
            str(self.candidate),
            "--requirements",
            str(self.requirements),
            "--plan",
            str(self.plan_path),
        ]
        started = time.monotonic()
        with (
            mock.patch.object(self.module, "require_isolation"),
            self.assertRaises(SystemExit) as raised,
        ):
            self.module.main(argv)
        self.assertLess(time.monotonic() - started, 3, "SIGTERM did not interrupt plan")
        self.assertEqual(raised.exception.code, 143)
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])
        self.assertFalse(self.plan_path.exists())

    # Ownership by construction: each resource is named or staged before it
    # exists, so an interrupt at any point finds only what this call owns.

    def _one_wheel(self, item, directory, download_deadline):
        artifact = directory / "pkg-1.0-py3-none-any.whl"
        artifact.write_bytes(b"wheel")
        return {
            "path": str(artifact),
            "sha256": hashlib.sha256(b"wheel").hexdigest(),
            "name": "pkg",
            "version": "1.0",
        }

    def test_interrupt_right_after_wheel_cache_mkdir_leaves_nothing(self):
        # os is one module object, so this also reaches tempfile.mkdtemp's mkdir. The
        # real mkdir runs first, then the signal lands before any ownership is recorded.
        real_mkdir = os.mkdir

        def mkdir_then_interrupt(path, *args, **kwargs):
            real_mkdir(path, *args, **kwargs)
            if "-wheels-" in os.fspath(path):
                raise KeyboardInterrupt

        self._start(self._one_wheel, [BEFORE, BEFORE])
        with mock.patch.object(os, "mkdir", side_effect=mkdir_then_interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.module.plan(self.options)
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])
        self.assertFalse(self.plan_path.exists())

    def _interrupt_at_plan_publish(self, exception_factory):
        # Hooks both the old create (open "x" on plan_path) and the new publish (link),
        # so the window is hit on either implementation. The retry is what a stranded
        # empty plan.json used to block with "Plan already exists".
        real_open, real_link = Path.open, os.link
        plan_path = self.plan_path

        def open_then_interrupt(path, mode="r", *args, **kwargs):
            stream = real_open(path, mode, *args, **kwargs)
            if "x" in mode and Path(path) == plan_path:
                stream.close()
                raise exception_factory()
            return stream

        def link_then_interrupt(source, destination, *args, **kwargs):
            real_link(source, destination, *args, **kwargs)
            if Path(destination) == plan_path:
                raise exception_factory()

        self._start(self._one_wheel, [BEFORE, BEFORE, BEFORE, BEFORE])
        with mock.patch.object(Path, "open", open_then_interrupt):
            with mock.patch.object(os, "link", link_then_interrupt):
                with self.assertRaises(BaseException):
                    self.module.plan(self.options)
        self.assertFalse(plan_path.exists(), "plan file left behind")
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])
        self.module.plan(self.options)
        self.assertTrue(plan_path.exists())

    def test_keyboard_interrupt_right_after_plan_is_published_retry_works(self):
        self._interrupt_at_plan_publish(KeyboardInterrupt)

    def test_sigterm_exit_right_after_plan_is_published_retry_works(self):
        self._interrupt_at_plan_publish(lambda: SystemExit(143))

    def test_wheel_cache_name_collision_leaves_the_existing_directory_alone(self):
        taken = self.root / ("approval-wheels-" + "ab" * 16)
        taken.mkdir()
        sentinel = taken / "sentinel.txt"
        sentinel.write_text("not ours", encoding="utf-8")
        self._start(self._one_wheel, [BEFORE, BEFORE])
        with mock.patch("secrets.token_hex", return_value="ab" * 16):
            with self.assertRaises(FileExistsError):
                self.module.plan(self.options)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "not ours")
        self.assertFalse(self.plan_path.exists())

    def test_concurrent_plan_published_before_link_is_left_untouched(self):
        plan_path = self.plan_path
        real_link = os.link

        def other_run_publishes_first(source, destination, *args, **kwargs):
            if Path(destination) == plan_path:
                plan_path.write_text("other run", encoding="utf-8")
            return real_link(source, destination, *args, **kwargs)

        self._start(self._one_wheel, [BEFORE, BEFORE])
        with mock.patch.object(os, "link", side_effect=other_run_publishes_first):
            with self.assertRaises(ValueError) as raised:
                self.module.plan(self.options)
        self._assert_plan_already_exists(raised)
        self.assertEqual(plan_path.read_text(encoding="utf-8"), "other run")
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])

    def _assert_plan_already_exists(self, raised):
        # The user sees the plan-path message, not the raw errno naming a cache
        # directory that cleanup has already removed.
        self.assertEqual(
            str(raised.exception), "Plan already exists; choose a fresh plan path"
        )
        self.assertNotIn("-wheels-", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)

    def _foreign_entry_appears_at_link(self, make_entry):
        # Another process creates an entry at plan_path just before this run's
        # exclusive os.link, so publication fails with FileExistsError. The fake
        # records what it created so the test can prove the entry was left unchanged.
        real_link = os.link
        self.foreign_stat = None

        def foreign_entry_then_exists(source, destination, *args, **kwargs):
            if Path(destination) == self.plan_path:
                make_entry(self.plan_path, os.stat(source).st_size)
                self.foreign_stat = os.lstat(self.plan_path)
                raise FileExistsError("File exists")
            return real_link(source, destination, *args, **kwargs)

        return mock.patch.object(os, "link", side_effect=foreign_entry_then_exists)

    def _assert_foreign_plan_entry_is_left_alone(self, make_entry):
        self._start(self._one_wheel, [BEFORE, BEFORE])
        with self._foreign_entry_appears_at_link(make_entry):
            with _bounded_against_hang_and_unbounded_read():
                with self.assertRaises(ValueError) as raised:
                    self.module.plan(self.options)
        self._assert_plan_already_exists(raised)
        after = os.lstat(self.plan_path)
        self.assertEqual(
            (after.st_ino, after.st_mode, after.st_size),
            (
                self.foreign_stat.st_ino,
                self.foreign_stat.st_mode,
                self.foreign_stat.st_size,
            ),
        )
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])

    @POSIX_ONLY
    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFOs are required")
    def test_foreign_fifo_at_plan_path_is_left_alone_not_read(self):
        def make_fifo(path, size):
            os.mkfifo(path)

        self._assert_foreign_plan_entry_is_left_alone(make_fifo)

    @POSIX_ONLY
    def test_foreign_directory_at_plan_path_is_left_alone(self):
        def make_directory(path, size):
            path.mkdir()

        self._assert_foreign_plan_entry_is_left_alone(make_directory)

    @POSIX_ONLY
    @unittest.skipUnless(hasattr(os, "symlink"), "POSIX symlinks are required")
    def test_foreign_symlink_to_dev_zero_at_plan_path_is_left_alone(self):
        def make_symlink(path, size):
            path.symlink_to("/dev/zero")

        self._assert_foreign_plan_entry_is_left_alone(make_symlink)

    # `or` short-circuits, so os.geteuid is never called where it does not exist.
    @POSIX_ONLY
    @unittest.skipIf(
        not hasattr(os, "geteuid") or os.geteuid() == 0,
        "POSIX permissions are required, and root reads an unreadable file anyway",
    )
    def test_foreign_unreadable_file_of_plan_size_is_left_alone(self):
        def make_unreadable(path, size):
            # Same size as the staged plan, so only a read could tell them apart.
            path.write_bytes(b"\0" * size)
            os.chmod(path, 0)

        try:
            self._assert_foreign_plan_entry_is_left_alone(make_unreadable)
        finally:
            os.chmod(self.plan_path, 0o600)

    def test_is_same_file_regular_file_of_other_size_is_not_read(self):
        staged = self.root / "staged.json"
        staged.write_bytes(b"abc")
        other = self.root / "other.json"
        other.write_bytes(b"abcdef")
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("read")):
            self.assertFalse(self.module._is_same_file(other, staged))

    def test_no_hard_link_filesystem_publishes_by_copy_and_apply_accepts_it(self):
        self._start(self._one_wheel, [BEFORE, BEFORE, BEFORE, AFTER])
        with mock.patch.object(
            os, "link", side_effect=PermissionError("Operation not permitted")
        ):
            self.module.plan(self.options)
        apply_options = argparse.Namespace(
            plan=self.plan_path,
            approved_plan_sha256=self.module.ENV.file_digest(self.plan_path),
        )
        self.module.apply(apply_options)
        self.assertEqual(self.pip_calls, [False, True])

    def test_nothing_to_install_plan_records_its_own_cache_directory(self):
        # With no artifacts the document is otherwise identical across runs, so the
        # cache name is what makes each plan this call's own.
        self._start(self._one_wheel, [INSTALLED, INSTALLED])
        self.module.plan(self.options)
        (cache,) = self.root.glob("*-wheels-*")
        document = json.loads(self.plan_path.read_text(encoding="utf-8"))
        self.assertEqual(document["cache"], str(cache))

    def test_copy_fallback_keeps_another_runs_identical_plan_when_nothing_installs(
        self,
    ):
        # Regression: with nothing to install, two runs wrote byte-identical plans, so
        # the losing run treated the winner's copy as its own and unlinked it. Another
        # run's plan is published here at plan_path with the same contents except its
        # own cache name, just before this run's copy fallback.
        self._start(self._one_wheel, [INSTALLED, INSTALLED])
        other_plan = {}

        def other_run_publishes_then_link_refused(source, destination, *args, **kwargs):
            if Path(destination) == self.plan_path:
                staged_bytes = Path(source).read_bytes()
                # Same length as this call's cache path, different in its last
                # character, so the size check cannot decide the comparison.
                own_cache = str(Path(source).parent)
                last = "0" if own_cache[-1] != "0" else "1"
                other_cache = own_cache[:-1] + last
                other_plan["bytes"] = staged_bytes.replace(
                    str(Path(source).parent).encode(), other_cache.encode()
                )
                self.plan_path.write_bytes(other_plan["bytes"])
            raise PermissionError("Operation not permitted")

        with mock.patch.object(
            os, "link", side_effect=other_run_publishes_then_link_refused
        ):
            with self.assertRaises(ValueError) as raised:
                self.module.plan(self.options)
        self._assert_plan_already_exists(raised)
        self.assertEqual(
            self.plan_path.read_bytes(),
            other_plan["bytes"],
            "the other run's plan was removed",
        )
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])

    def test_partial_copy_is_removed_when_the_copy_fails_midway(self):
        # Copy fallback: the write lands 10 bytes, then the disk is full. The plan
        # must not be left at plan_path, and no cache may remain.
        self._start(self._one_wheel, [BEFORE, BEFORE])
        plan_path = self.plan_path
        real_open = Path.open

        def open_disk_full_on_plan(path, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            handle = real_open(path, *args, **kwargs)
            if Path(path) == plan_path and mode == "xb":
                return _DiskFullAfterTenBytes(handle)
            return handle

        with mock.patch.object(
            os, "link", side_effect=PermissionError("Operation not permitted")
        ):
            with mock.patch.object(Path, "open", open_disk_full_on_plan):
                with self.assertRaises(OSError) as raised:
                    self.module.plan(self.options)
        self.assertEqual(raised.exception.errno, errno.ENOSPC)
        self.assertFalse(plan_path.exists(), "partial copy must be removed")
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])

    def test_no_hard_link_interrupt_after_copy_removes_copy_and_cache(self):
        real_digest = self.module.ENV.file_digest
        plan_path = self.plan_path

        def digest_interrupted_on_plan(path, *args, **kwargs):
            if Path(path) == plan_path:
                raise KeyboardInterrupt
            return real_digest(path, *args, **kwargs)

        self._start(self._one_wheel, [BEFORE, BEFORE])
        with mock.patch.object(
            os, "link", side_effect=PermissionError("Operation not permitted")
        ):
            with mock.patch.object(
                self.module.ENV, "file_digest", side_effect=digest_interrupted_on_plan
            ):
                with self.assertRaises(KeyboardInterrupt):
                    self.module.plan(self.options)
        self.assertFalse(plan_path.exists())
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])


@POSIX_ONLY
class PlanSignalExitTests(unittest.TestCase):
    """main() turns SIGTERM/SIGHUP during plan into SystemExit(128 + signum)."""

    def _exit_code_after_signal(self, signum):
        module = load_module()
        sentinel_calls = []

        def sentinel(number, frame):
            # Records instead of killing the runner: on the pre-fix code no handler
            # is installed, so this is what would otherwise receive the signal.
            sentinel_calls.append(number)

        def plan_sends_signal(options):
            os.kill(os.getpid(), signum)
            time.sleep(5)
            return {}

        previous = signal.signal(signum, sentinel)
        self.addCleanup(signal.signal, signum, previous)
        before = signal.getsignal(signum)
        argv = ["plan", "--candidate", "c", "--requirements", "r", "--plan", "p"]
        started = time.monotonic()
        with (
            mock.patch.object(module, "require_isolation"),
            mock.patch.object(module, "plan", side_effect=plan_sends_signal),
            self.assertRaises(SystemExit) as raised,
        ):
            module.main(argv)
        self.assertLess(time.monotonic() - started, 3, "signal did not interrupt plan")
        self.assertEqual(signal.getsignal(signum), before)
        return raised.exception.code

    def test_sigterm_during_plan_exits_143_and_restores_handler(self):
        self.assertEqual(self._exit_code_after_signal(signal.SIGTERM), 143)

    @unittest.skipUnless(hasattr(signal, "SIGHUP"), "SIGHUP is POSIX-only")
    def test_sighup_during_plan_exits_129_and_restores_handler(self):
        self.assertEqual(self._exit_code_after_signal(signal.SIGHUP), 129)

    @unittest.skipUnless(hasattr(signal, "SIGHUP"), "SIGHUP is POSIX-only")
    def test_inherited_ignored_sighup_is_kept_so_nohup_plan_survives(self):
        # `nohup` starts the process with SIGHUP ignored; plan must not turn that
        # into a handler that aborts it.
        module = load_module()
        previous = signal.signal(signal.SIGHUP, signal.SIG_IGN)
        self.addCleanup(signal.signal, signal.SIGHUP, previous)

        def plan_sends_hangup(options):
            os.kill(os.getpid(), signal.SIGHUP)
            return {"status": "already-satisfied"}

        argv = ["plan", "--candidate", "c", "--requirements", "r", "--plan", "p"]
        with (
            mock.patch.object(module, "require_isolation"),
            mock.patch.object(module, "plan", side_effect=plan_sends_hangup),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            code = module.main(argv)
        self.assertEqual(code, 0)
        self.assertIs(signal.getsignal(signal.SIGHUP), signal.SIG_IGN)


class ApplySignalExitTests(unittest.TestCase):
    """SIGTERM during apply must stop the pip child, not leave it running."""

    @POSIX_ONLY
    def test_sigterm_during_apply_stops_the_pip_child(self):
        module = load_module()
        root = isolate_temp_dir(self)
        marker = root / "child-finished"
        # Stands in for the trusted interpreter: sleeps as a slow pip install would,
        # then writes the marker only if it was not stopped first.
        fake = root / "fake_interpreter.sh"
        fake.write_text(
            "#!/bin/sh\nfor a; do last=$a; done\nsleep 4\n" 'echo finished > "$last"\n',
            encoding="utf-8",
        )
        fake.chmod(0o700)

        def apply_runs_pip(options):
            threading.Timer(1.0, os.kill, (os.getpid(), signal.SIGTERM)).start()
            module.isolated_pip(
                Path("/nonexistent/candidate"),
                [str(marker)],
                root,
                changes_environment=True,
            )
            return {}

        # Recording handler stands in for the default action, which would end the
        # runner on the pre-fix code before the child could be observed.
        previous = signal.signal(signal.SIGTERM, lambda number, frame: None)
        self.addCleanup(signal.signal, signal.SIGTERM, previous)
        started = time.monotonic()
        with (
            mock.patch.object(module, "require_isolation"),
            mock.patch.object(module, "apply", side_effect=apply_runs_pip),
            mock.patch.object(module.ENV, "trusted_interpreter", return_value=fake),
            self.assertRaises(SystemExit) as raised,
        ):
            module.main(["apply", "--plan", "p", "--approved-plan-sha256", "x"])
        self.assertLess(time.monotonic() - started, 3, "SIGTERM did not stop apply")
        self.assertEqual(raised.exception.code, 143)
        self.assertFalse(marker.exists(), "pip child kept running after SIGTERM")


class PlanOffMainThreadTests(unittest.TestCase):
    """_run_handling_termination must not touch signal handlers off the main thread."""

    def test_plan_runs_off_main_thread_without_touching_signal_handlers(self):
        module = load_module()
        outcome = {}

        def run():
            try:
                outcome["result"] = module._run_handling_termination(
                    module.plan, argparse.Namespace()
                )
            except (
                BaseException
            ) as error:  # collected here, asserted on the main thread
                outcome["error"] = error

        before = signal.getsignal(signal.SIGTERM)
        with mock.patch.object(module, "plan", return_value={"ok": True}):
            worker = threading.Thread(target=run)
            worker.start()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive(), "worker thread did not finish")
        self.assertNotIn(
            "error", outcome, f"plan raised off the main thread: {outcome}"
        )
        self.assertEqual(outcome.get("result"), {"ok": True})
        self.assertIs(signal.getsignal(signal.SIGTERM), before)


class _SwapHung(Exception):
    """Raised by the SIGALRM guard when _is_same_file blocks on a swapped entry."""


class IsSameFileCheckedEntryTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.root = Path(tempfile.mkdtemp(prefix="same-file-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.staged = self.root / "staged.json"
        self.staged.write_bytes(b"plan-bytes")
        self.plan = self.root / "plan.json"

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFOs are required")
    def test_entry_swapped_for_other_identical_file_before_open_is_not_this_plan(self):
        # Pins samestat(opened, entry): the swap has the same size and bytes but is a
        # different inode, so only the descriptor-to-entry identity check refuses it.
        self.plan.write_bytes(b"plan-bytes")
        swap = self.root / "swap.json"
        swap.write_bytes(b"plan-bytes")
        real_open = os.open
        swapped = []

        def open_after_swap(path, *args, **kwargs):
            if Path(path) == self.plan and not swapped:
                swapped.append(True)
                os.replace(swap, self.plan)
            return real_open(path, *args, **kwargs)

        with mock.patch.object(self.module.os, "open", side_effect=open_after_swap):
            self.assertFalse(self.module._is_same_file(self.plan, self.staged))
        self.assertEqual(swapped, [True])

    def test_entry_swapped_for_fifo_after_lstat_is_not_read(self):
        # Regression: _is_same_file used to read the path after os.lstat, so a FIFO
        # swapped in between blocked the read forever. The guard turns a hang into a
        # failure; the result must come from the checked entry, not from a re-open.
        self.plan.write_bytes(b"plan-bytes")  # regular, same size, different inode
        real_lstat = os.lstat
        swapped = []

        def lstat_then_swap(path, *args, **kwargs):
            result = real_lstat(path, *args, **kwargs)
            if Path(path) == self.plan and not swapped:
                swapped.append(True)
                os.unlink(self.plan)
                os.mkfifo(self.plan)
            return result

        def alarm(signum, frame):
            raise _SwapHung("_is_same_file blocked reading the swapped FIFO")

        previous = signal.signal(signal.SIGALRM, alarm)
        self.addCleanup(signal.signal, signal.SIGALRM, previous)
        self.addCleanup(signal.alarm, 0)
        signal.alarm(10)
        with mock.patch.object(self.module.os, "lstat", side_effect=lstat_then_swap):
            self.assertFalse(self.module._is_same_file(self.plan, self.staged))
        signal.alarm(0)
        self.assertEqual(swapped, [True])
        self.assertTrue(stat.S_ISFIFO(real_lstat(self.plan).st_mode))

    def test_byte_identical_regular_copy_is_this_calls_plan(self):
        self.plan.write_bytes(b"plan-bytes")
        self.assertTrue(self.module._is_same_file(self.plan, self.staged))

    def test_regular_file_with_different_bytes_is_not_this_calls_plan(self):
        # Equal length, so only the byte comparison can tell the two apart.
        self.plan.write_bytes(b"othr-bytes")
        self.assertEqual(len(b"othr-bytes"), len(b"plan-bytes"))
        self.assertFalse(self.module._is_same_file(self.plan, self.staged))


class PortableImportTests(unittest.TestCase):
    def test_module_imports_where_os_geteuid_is_absent(self):
        # Windows has no os.geteuid. Run the import in a child whose os lacks it, so
        # a module-level call to it fails here on any platform.
        code = (
            "import importlib.util, os, sys\n"
            "del os.geteuid\n"
            "spec = importlib.util.spec_from_file_location('tests_under_test', sys.argv[1])\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code, str(Path(__file__).resolve())],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_tests_needing_resource_skip_where_resource_is_absent(self):
        # Windows has no `resource` module. The four tests that drive the rlimit and
        # SIGALRM guard must report as skipped there, not as errors. Run them in a
        # child where importing `resource` fails, and count the outcomes.
        code = (
            "import importlib.util, io, json, sys, unittest\n"
            "sys.modules['resource'] = None\n"
            "spec = importlib.util.spec_from_file_location('tests_under_test', sys.argv[1])\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "names = [\n"
            "    'PlanApplyHarnessTests.test_foreign_fifo_at_plan_path_is_left_alone_not_read',\n"
            "    'PlanApplyHarnessTests.test_foreign_directory_at_plan_path_is_left_alone',\n"
            "    'PlanApplyHarnessTests.test_foreign_symlink_to_dev_zero_at_plan_path_is_left_alone',\n"
            "    'PlanApplyHarnessTests.test_foreign_unreadable_file_of_plan_size_is_left_alone',\n"
            "]\n"
            "suite = unittest.TestLoader().loadTestsFromNames(names, module)\n"
            "result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)\n"
            "print(json.dumps({'ran': result.testsRun, 'errors': len(result.errors),\n"
            "                  'failures': len(result.failures),\n"
            "                  'skipped': len(result.skipped)}))\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code, str(Path(__file__).resolve())],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        outcome = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(outcome["ran"], 4, outcome)
        self.assertEqual(outcome["errors"], 0, outcome)
        self.assertEqual(outcome["failures"], 0, outcome)
        self.assertEqual(outcome["skipped"], 4, outcome)


class InterruptedApplyWarningTests(unittest.TestCase):
    """A SIGTERM during apply says the environment may be partly changed; plan does not."""

    APPLY_STOPPED = (
        "Installer stopped by an interrupt during apply; the environment may be partly "
        "changed. Stop and inspect it before any further change."
    )

    def _pip_child_interrupted_by(self, module, interrupt, changes_environment):
        """Run isolated_pip with subprocess.run raising interrupt; return stderr text."""
        stderr = io.StringIO()
        with (
            mock.patch.object(module.subprocess, "run", side_effect=interrupt),
            mock.patch.object(
                module.ENV, "trusted_interpreter", return_value=Path("/usr/bin/python3")
            ),
            contextlib.redirect_stderr(stderr),
        ):
            with self.assertRaises(type(interrupt)):
                module.isolated_pip(
                    Path("/tmp/candidate"),
                    ["install", "x"],
                    Path("/tmp"),
                    changes_environment=changes_environment,
                )
        return stderr.getvalue()

    def _approved_plan(self, module, root):
        """Write a plan with one wheel, as plan() would, and return (path, sha256)."""
        wheel = root / "pkg-1.0-py3-none-any.whl"
        wheel.write_bytes(b"wheel")
        requirements = root / "requirements.txt"
        requirements.write_bytes(b"pkg==1.0\n")
        plan = root / "plan.json"
        plan.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "candidate": str(root / "candidate"),
                    "identity": "unchanged",
                    "requirements": str(requirements),
                    "requirements_sha256": module.ENV.file_digest(requirements),
                    "artifacts": [
                        {
                            "path": str(wheel),
                            "sha256": module.ENV.file_digest(wheel),
                            "name": "pkg",
                            "version": "1.0",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return plan, module.ENV.file_digest(plan)

    def _apply_expecting(self, interrupt_type, *, pip_run, snapshot_calls, save=None):
        """Run the real apply() to its pip step and assert it propagates interrupt_type.

        snapshot_calls feeds the snapshot() calls apply() makes in order; an exception
        item is raised at that call. Returns what apply() printed to stderr.
        """
        module = load_module()
        root = isolate_temp_dir(self)
        plan, digest = self._approved_plan(module, root)
        stderr = io.StringIO()
        with (
            mock.patch.object(module, "snapshot", side_effect=snapshot_calls),
            mock.patch.object(module.subprocess, "run", side_effect=pip_run),
            mock.patch.object(module, "_save_pip_output", side_effect=save),
            mock.patch.object(
                module.ENV, "trusted_interpreter", return_value=Path("/usr/bin/python3")
            ),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(interrupt_type),
        ):
            module.apply(argparse.Namespace(plan=plan, approved_plan_sha256=digest))
        return stderr.getvalue()

    @POSIX_ONLY
    def test_sigterm_during_apply_exits_143_and_warns_on_stderr(self):
        module = load_module()
        root = isolate_temp_dir(self)
        plan, digest = self._approved_plan(module, root)
        # A real child stands in for the trusted interpreter: it sleeps as a slow
        # install would, so SIGTERM lands while apply() is waiting on pip.
        fake = root / "fake_interpreter.sh"
        fake.write_text("#!/bin/sh\nsleep 4\n", encoding="utf-8")
        fake.chmod(0o700)
        threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGTERM)).start()

        stderr = io.StringIO()
        started = time.monotonic()
        with (
            mock.patch.object(module, "require_isolation"),
            mock.patch.object(
                module,
                "snapshot",
                return_value={"identity": "unchanged", "installed": {}},
            ),
            mock.patch.object(module.ENV, "trusted_interpreter", return_value=fake),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            module.main(
                ["apply", "--plan", str(plan), "--approved-plan-sha256", digest]
            )
        self.assertLess(time.monotonic() - started, 3, "SIGTERM did not stop apply")
        self.assertEqual(raised.exception.code, 143)
        self.assertEqual(json.loads(stderr.getvalue()), {"error": self.APPLY_STOPPED})

    def test_keyboard_interrupt_in_pip_during_apply_warns_and_propagates(self):
        stderr = self._apply_expecting(
            KeyboardInterrupt,
            pip_run=KeyboardInterrupt(),
            snapshot_calls=[{"identity": "unchanged", "installed": {}}],
        )
        self.assertEqual(json.loads(stderr), {"error": self.APPLY_STOPPED})

    def test_interrupt_saving_pip_output_after_failed_apply_warns_and_propagates(self):
        # pip has started and may have changed the environment; the log save is after
        # its exit, so the interrupt must still get the warning.
        stderr = self._apply_expecting(
            KeyboardInterrupt,
            pip_run=lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", b""),
            snapshot_calls=[{"identity": "unchanged", "installed": {}}],
            save=KeyboardInterrupt(),
        )
        self.assertEqual(json.loads(stderr), {"error": self.APPLY_STOPPED})

    def test_interrupt_in_post_install_snapshot_after_clean_pip_warns_and_propagates(
        self,
    ):
        # pip exited 0 and may have written files; the interrupt lands before the
        # installed metadata is verified.
        stderr = self._apply_expecting(
            KeyboardInterrupt,
            pip_run=lambda *a, **k: subprocess.CompletedProcess(a, 0, b"", b""),
            snapshot_calls=[
                {"identity": "unchanged", "installed": {}},
                KeyboardInterrupt(),
            ],
        )
        self.assertEqual(json.loads(stderr), {"error": self.APPLY_STOPPED})

    def test_interrupt_in_snapshot_before_pip_starts_prints_no_warning(self):
        stderr = self._apply_expecting(
            SystemExit,
            pip_run=AssertionError("pip must not start"),
            snapshot_calls=[SystemExit(143)],
        )
        self.assertEqual(stderr, "")

    def test_keyboard_interrupt_in_pip_during_plan_is_silent_and_propagates(self):
        module = load_module()
        isolate_temp_dir(self)
        stderr = self._pip_child_interrupted_by(
            module, KeyboardInterrupt(), changes_environment=False
        )
        self.assertEqual(stderr, "")

    def test_interrupt_before_pip_starts_during_apply_prints_no_warning(self):
        module = load_module()
        root = isolate_temp_dir(self)
        plan = root / "plan.json"
        plan.write_text(
            json.dumps({"schema": 1, "candidate": "/nonexistent/candidate"}),
            encoding="utf-8",
        )
        digest = module.ENV.file_digest(plan)
        stderr = io.StringIO()
        # snapshot runs before any pip child exists, so nothing was touched yet.
        with (
            mock.patch.object(module, "require_isolation"),
            mock.patch.object(module, "snapshot", side_effect=SystemExit(143)),
            mock.patch.object(module, "isolated_pip") as pip,
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            module.main(
                ["apply", "--plan", str(plan), "--approved-plan-sha256", digest]
            )
        self.assertEqual(raised.exception.code, 143)
        pip.assert_not_called()
        self.assertEqual(stderr.getvalue(), "")

    @POSIX_ONLY
    def test_sigterm_during_plan_prints_no_apply_warning(self):
        module = load_module()

        def plan_is_signalled(options):
            threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGTERM)).start()
            time.sleep(5)
            return {}

        stderr = io.StringIO()
        argv = ["plan", "--candidate", "c", "--requirements", "r", "--plan", "p"]
        with (
            mock.patch.object(module, "require_isolation"),
            mock.patch.object(module, "plan", side_effect=plan_is_signalled),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            module.main(argv)
        self.assertEqual(raised.exception.code, 143)
        self.assertEqual(stderr.getvalue(), "")


class DownloadTlsErrorLabelTests(unittest.TestCase):
    """TLS errors carry OpenSSL codes in errno; they must not be labelled as OS errnos."""

    def assert_tls_error_is_named_by_type_only(self, error, type_name):
        module = load_module()
        root = isolate_temp_dir(self)
        target = root / "pkg-1.0-py3-none-any.whl"
        url = "https://example.invalid/pkg-1.0-py3-none-any.whl"
        with mock.patch.object(module, "_open_url", side_effect=error):
            with self.assertRaises(ValueError) as raised:
                module._download(url, target, read_timeout=5, deadline=5)
        self.assertEqual(
            str(raised.exception),
            f"Wheel download failed: {type_name}; nothing was installed or changed.",
        )
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_ssl_eof_error_is_named_by_type_not_by_openssl_errno(self):
        self.assert_tls_error_is_named_by_type_only(
            ssl.SSLEOFError(8, "EOF occurred"), "SSLEOFError"
        )

    def test_ssl_error_is_named_by_type_not_by_openssl_errno(self):
        self.assert_tls_error_is_named_by_type_only(ssl.SSLError(1, "x"), "SSLError")


class InterruptedPipOutputSaveTests(unittest.TestCase):
    """An interrupt while saving pip output must not leave a partial log behind."""

    def setUp(self):
        self.temp_root = isolate_temp_dir(self)

    def test_interrupt_during_write_removes_the_partial_log_and_propagates(self):
        module = load_module()
        real_fdopen = os.fdopen
        for interrupt in (KeyboardInterrupt, SystemExit):
            with self.subTest(interrupt=interrupt.__name__):

                class InterruptedOnSecondWrite:
                    def __init__(self, stream):
                        self.stream = stream
                        self.writes = 0

                    def __enter__(self):
                        return self

                    def __exit__(self, *exc_info):
                        self.stream.close()
                        return False

                    def write(self, data):
                        self.writes += 1
                        if self.writes == 2:
                            raise interrupt()
                        return self.stream.write(data)

                with mock.patch.object(
                    module.os,
                    "fdopen",
                    side_effect=lambda fd, mode: InterruptedOnSecondWrite(
                        real_fdopen(fd, mode)
                    ),
                ):
                    with self.assertRaises(interrupt):
                        module._save_pip_output(b"out", b"err")
                self.assertEqual(
                    list(self.temp_root.iterdir()),
                    [],
                    "an interrupted save must remove its partial log and directory",
                )

    def test_failed_removal_after_interrupt_still_propagates_the_interrupt(self):
        module = load_module()
        real_fdopen = os.fdopen

        class InterruptedOnSecondWrite:
            def __init__(self, stream):
                self.stream = stream
                self.writes = 0

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                self.stream.close()
                return False

            def write(self, data):
                self.writes += 1
                if self.writes == 2:
                    raise KeyboardInterrupt()
                return self.stream.write(data)

        with (
            mock.patch.object(
                module.os,
                "fdopen",
                side_effect=lambda fd, mode: InterruptedOnSecondWrite(
                    real_fdopen(fd, mode)
                ),
            ),
            mock.patch.object(
                module.shutil, "rmtree", side_effect=OSError(errno.EBUSY, "busy")
            ),
        ):
            with self.assertRaises(KeyboardInterrupt) as raised:
                module._save_pip_output(b"out", b"err")
        self.assertNotIsInstance(raised.exception.__context__, OSError)
        self.assertNotIn("busy", repr(raised.exception.__context__))


class DownloadWorkerDaemonTests(unittest.TestCase):
    """A stalled lookup must not keep the process alive after the download deadline."""

    def test_stalled_lookup_does_not_hold_the_process_after_the_deadline(self):
        root = isolate_temp_dir(self)
        target = root / "pkg-1.0-py3-none-any.whl"
        code = (
            "import importlib.util, sys, time\n"
            "from pathlib import Path\n"
            "spec = importlib.util.spec_from_file_location('env_under_test', sys.argv[1])\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "def stalled_lookup(url, timeout):\n"
            "    time.sleep(20)\n"
            "module._open_url = stalled_lookup\n"
            "try:\n"
            "    module._download(\n"
            "        'https://example.invalid/pkg-1.0-py3-none-any.whl',\n"
            "        Path(sys.argv[2]), read_timeout=5, deadline=1,\n"
            "    )\n"
            "except ValueError as error:\n"
            "    print(error)\n"
        )
        started = time.monotonic()
        completed = subprocess.run(
            [sys.executable, "-I", "-c", code, str(SCRIPT), str(target)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        elapsed = time.monotonic() - started
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("plan download deadline", completed.stdout)
        self.assertLess(elapsed, 10, "a stalled download thread kept the process alive")


if __name__ == "__main__":
    unittest.main()

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
    match = re.search(
        r"pip's full output is saved, unredacted, in (.+?pip-output\.log)\.", message
    )
    if match is None:
        raise AssertionError(f"message names no saved pip output: {message!r}")
    return Path(match.group(1))


class FakePipChild:
    """Stands in for the subprocess.Popen child that isolated_pip creates.

    communicate() returns the outcome's output and returncode, or raises the outcome
    when it is an exception. A TimeoutExpired is raised on the bounded call only; after
    kill() the next communicate() returns its partial output, as real pipes do.
    timeouts records the timeout each communicate() call was given.
    """

    def __init__(self, outcome):
        self.outcome = outcome
        self.timeouts = []
        self.killed = False
        self.returncode = (
            outcome.returncode
            if isinstance(outcome, subprocess.CompletedProcess)
            else None
        )

    def communicate(self, timeout=None):
        self.timeouts.append(timeout)
        if isinstance(self.outcome, subprocess.TimeoutExpired):
            if not self.killed:
                raise self.outcome
            return self.outcome.output, self.outcome.stderr
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome.stdout, self.outcome.stderr

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


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
            self.assertIn("no response for 0.5s", str(raised.exception))
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
            self.assertNotIn("no response for", str(raised.exception))
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
            self.assertNotIn("no response for", message)
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
            self.assertNotIn("no response for", str(raised.exception))
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
            self.assertNotIn("no response for", str(raised.exception))
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
            self.assertIn("no response for 0.5s", str(raised.exception))
            self.assertNotIn("ran out", str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertTrue(raised.exception.__suppress_context__)
            self.assertFalse(target.exists())

    def test_url_error_names_the_reason_class_and_never_its_text(self):
        # The reason's text can carry a host or path, so only its class name is shown.
        module = load_module()
        refused = urllib_error.URLError(ConnectionRefusedError(111, "refused /secret"))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            with mock.patch.object(module, "_open_url", side_effect=refused):
                with self.assertRaises(ValueError) as raised:
                    module._download(
                        "http://127.0.0.1:9/x.whl", target, read_timeout=5, deadline=5
                    )
            message = str(raised.exception)
            self.assertIn("URLError (ConnectionRefusedError)", message)
            self.assertNotIn("/secret", message)
            self.assertFalse(target.exists())

    def test_url_error_with_string_reason_names_no_type_and_no_text(self):
        # A string reason (e.g. a redirect to a host-less URL) is not an exception, so
        # its type name "str" would name a Python type, not an error. Show none.
        module = load_module()
        refused = urllib_error.URLError("no host given /secret")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            with mock.patch.object(module, "_open_url", side_effect=refused):
                with self.assertRaises(ValueError) as raised:
                    module._download(
                        "http://127.0.0.1:9/x.whl", target, read_timeout=5, deadline=5
                    )
            message = str(raised.exception)
            self.assertIn("Wheel download failed: URLError;", message)
            self.assertNotIn("(str)", message)
            self.assertNotIn("/secret", message)
            self.assertFalse(target.exists())

    def test_existing_target_is_never_opened_for_writing(self):
        # "xb" refuses an existing file before any transfer, so the file keeps its
        # bytes and the opener is never asked for a body.
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            target.write_bytes(b"someone else's wheel")
            fake = _FakeResponse(b"replacement wheel")
            with mock.patch.object(module, "_open_url", return_value=fake) as opener:
                with self.assertRaises(FileExistsError):
                    module._download(
                        "https://files.example.invalid/x.whl",
                        target,
                        read_timeout=5,
                        deadline=5,
                    )
            opener.assert_not_called()
            self.assertEqual(target.read_bytes(), b"someone else's wheel")


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


class NoContentWithLengthHandler(BaseHTTPRequestHandler):
    """Answers 204 No Content but still sends a Content-Length: http.client reads no body."""

    def do_GET(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Content-Length", "100")
        self.end_headers()

    def log_message(self, *args):
        pass


class CutShortHandler(BaseHTTPRequestHandler):
    """Declares 100 bytes, sends SENT, then closes the connection."""

    SENT = 10

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", "100")
        self.end_headers()
        self.wfile.write(b"x" * self.SENT)
        self.wfile.flush()

    def log_message(self, *args):
        pass


class NearlyCutShortHandler(CutShortHandler):
    """Declares 100 bytes and sends 99: one byte short of the declared length."""

    SENT = 99


class ChunkedWithContradictingLengthHandler(BaseHTTPRequestHandler):
    """Sends a complete 10-byte chunked body under a Content-Length it contradicts."""

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Content-Length", "1000")
        self.end_headers()
        self.wfile.write(b"a\r\n0123456789\r\n0\r\n\r\n")
        self.wfile.flush()

    def log_message(self, *args):
        pass


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
            self.assertNotIn("no response for", str(raised.exception))
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

    def test_no_content_with_content_length_is_not_cut_short(self):
        # http.client reads no body for a 204, so a Content-Length on it is not a short body.
        module = load_module()
        url = self.start_server(NoContentWithLengthHandler)
        root = isolate_temp_dir(self)
        target = root / "pkg-1.0-py3-none-any.whl"
        module._download(url, target, read_timeout=5, deadline=5)
        self.assertEqual(target.read_bytes(), b"")

    def test_real_body_cut_short_of_content_length_is_refused(self):
        module = load_module()
        url = self.start_server(CutShortHandler)
        root = isolate_temp_dir(self)
        target = root / "pkg-1.0-py3-none-any.whl"
        with self.assertRaises(ValueError) as raised:
            module._download(url, target, read_timeout=5, deadline=5)
        self.assertIn("cut short", str(raised.exception))
        self.assertFalse(target.exists(), "partial wheel was left behind")

    def test_real_body_one_byte_short_of_content_length_is_refused(self):
        module = load_module()
        url = self.start_server(NearlyCutShortHandler)
        root = isolate_temp_dir(self)
        target = root / "pkg-1.0-py3-none-any.whl"
        with self.assertRaises(ValueError) as raised:
            module._download(url, target, read_timeout=5, deadline=5)
        self.assertIn("cut short", str(raised.exception))
        self.assertFalse(target.exists(), "partial wheel was left behind")

    def test_chunked_body_with_contradicting_content_length_downloads_in_full(self):
        # http.client sets length to None for chunked framing and ignores the header;
        # the body is complete, so the contradicting Content-Length must not cut it short.
        module = load_module()
        url = self.start_server(ChunkedWithContradictingLengthHandler)
        root = isolate_temp_dir(self)
        target = root / "pkg-1.0-py3-none-any.whl"
        module._download(url, target, read_timeout=5, deadline=5)
        self.assertEqual(target.read_bytes(), b"0123456789")


class UnlinkFailureKeepsLabelledErrorTests(unittest.TestCase):
    """A failing unlink of the partial wheel must not replace the download's error."""

    def _unlink_of_target_fails(self, target):
        real_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path == target:
                raise PermissionError(errno.EACCES, "locked by another process")
            return real_unlink(path, *args, **kwargs)

        return mock.patch.object(Path, "unlink", unlink)

    def test_deadline_message_survives_a_failing_unlink(self):
        module = load_module()
        root = isolate_temp_dir(self)
        target = root / "pkg-1.0-py3-none-any.whl"
        release = threading.Event()
        self.addCleanup(release.set)
        with (
            mock.patch.object(
                module, "_open_url", return_value=BlockingResponse(release)
            ),
            self._unlink_of_target_fails(target),
        ):
            with self.assertRaises(ValueError) as raised:
                module._download(
                    "https://example.invalid/pkg-1.0-py3-none-any.whl",
                    target,
                    read_timeout=5,
                    deadline=0.2,
                )
        self.assertIn("did not finish", str(raised.exception))
        self.assertNotIsInstance(raised.exception, PermissionError)

    def test_labelled_failure_survives_a_failing_unlink(self):
        module = load_module()
        root = isolate_temp_dir(self)
        target = root / "pkg-1.0-py3-none-any.whl"
        error = urllib_error.HTTPError(
            "https://example.invalid/pkg-1.0-py3-none-any.whl",
            500,
            "Server Error",
            None,
            None,
        )
        with (
            mock.patch.object(module, "_open_url", side_effect=error),
            self._unlink_of_target_fails(target),
        ):
            with self.assertRaises(ValueError) as raised:
                module._download(
                    "https://example.invalid/pkg-1.0-py3-none-any.whl",
                    target,
                    read_timeout=5,
                    deadline=5,
                )
        self.assertEqual(
            str(raised.exception),
            "Wheel download failed: HTTPError (HTTP 500); nothing was installed or changed.",
        )
        self.assertNotIsInstance(raised.exception, PermissionError)


class _FakeResponse:
    """Stands in for the opener's response: a body and the length http.client parsed.

    length mirrors http.client.HTTPResponse.length: the body length, or None when
    chunked, absent or unknown.
    """

    def __init__(self, body, length=None):
        self._body = io.BytesIO(body)
        self.length = length

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read1(self, size=-1):
        return self._body.read1(size)


class SizeCapBoundaryTests(unittest.TestCase):
    CAP = 1024

    def _download(self, body, length=None):
        module = load_module()
        target_dir = isolate_temp_dir(self)
        target = target_dir / "pkg-1.0-py3-none-any.whl"
        with (
            mock.patch.object(module, "MAX_WHEEL_BYTES", self.CAP),
            mock.patch.object(
                module, "_open_url", return_value=_FakeResponse(body, length)
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
        target = self._download(b"x" * self.CAP, length=self.CAP)
        self.assertEqual(target.stat().st_size, self.CAP)

    def test_body_one_byte_over_the_cap_is_refused(self):
        with self.assertRaises(ValueError) as raised:
            self._download(b"x" * (self.CAP + 1))
        self.assertIn("exceeded", str(raised.exception))

    def test_declared_length_one_byte_over_the_cap_is_refused(self):
        with self.assertRaises(ValueError) as raised:
            self._download(b"x" * (self.CAP + 1), length=self.CAP + 1)
        self.assertIn("exceeded", str(raised.exception))


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

    def test_exhausted_plan_budget_refuses_without_opening_a_download(self):
        module = load_module()
        payload = b"wheel-bytes"
        item = {
            "download_info": {
                "url": "https://files.example.invalid/pkg-1.0-py3-none-any.whl",
                "archive_info": {
                    "hashes": {"sha256": hashlib.sha256(payload).hexdigest()}
                },
            },
            "metadata": {"name": "pkg", "version": "1.0"},
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(module, "time") as clock,
            mock.patch.object(
                module,
                "_download",
                side_effect=AssertionError("a download opened on a spent budget"),
            ) as download,
        ):
            # remaining = deadline - monotonic() is exactly 0.0: the budget is spent.
            clock.monotonic.return_value = 1000.0
            with self.assertRaises(ValueError) as raised:
                module.cache_wheel(item, Path(directory), 1000.0)
            download.assert_not_called()
            self.assertIn("plan download deadline", str(raised.exception))
            self.assertIn("ran out", str(raised.exception))


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
            mock.patch.object(
                module.subprocess, "Popen", return_value=FakePipChild(expired)
            ) as popen,
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
        # The first communicate is the bounded one; the call after kill() is unbounded.
        self.assertEqual(popen.return_value.timeouts[0], 0.1)
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
            mock.patch.object(
                module.subprocess, "Popen", return_value=FakePipChild(failed)
            ),
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
            mock.patch.object(
                module.subprocess, "Popen", return_value=FakePipChild(expired)
            ),
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

    def _pip_failure_message(
        self, changes_environment: bool, returncode: int = 2
    ) -> str:
        isolate_temp_dir(self)
        module = load_module()
        failed = subprocess.CompletedProcess(
            args=["pip"], returncode=returncode, stdout="x"
        )
        with (
            mock.patch.object(
                module.subprocess, "Popen", return_value=FakePipChild(failed)
            ),
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

    def test_refused_apply_says_nothing_was_changed_not_partly_changed(self):
        # Exit 65 is the adapter's pre-install refusal: pip's main() never ran.
        message = self._pip_refused_message(changes_environment=True)
        self.assertIn("refused the install before changing anything", message)
        self.assertIn("nothing was installed or changed", message)
        self.assertNotIn("partly changed", message)
        self.assertNotIn("Isolated pip failed", message)

    def test_refused_plan_says_nothing_was_changed(self):
        message = self._pip_refused_message(changes_environment=False)
        self.assertIn("refused the install before changing anything", message)
        self.assertIn("nothing was installed or changed", message)
        self.assertNotIn("partly changed", message)

    def _pip_refused_message(self, changes_environment: bool) -> str:
        isolate_temp_dir(self)
        module = load_module()
        # Literal 65: the adapter's refusal code, pinned here as the contract.
        refused = subprocess.CompletedProcess(
            args=["pip"], returncode=65, stdout=b"", stderr=b'{"error": "x"}'
        )
        with (
            mock.patch.object(
                module.subprocess, "Popen", return_value=FakePipChild(refused)
            ),
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

    def test_apply_killed_by_signal_names_the_signal_not_an_exit_code(self):
        # -9 is SIGKILL, e.g. the OOM killer; pip writes nothing when it is killed.
        message = self._pip_failure_message(changes_environment=True, returncode=-9)
        self.assertTrue(
            message.startswith(
                "Isolated pip was killed by SIGKILL during apply after 42s; the "
                "environment may be partly changed. Stop and inspect it before any "
                "further change. "
            ),
            message,
        )
        self.assertNotIn("exit code", message)

    def test_plan_killed_by_signal_says_nothing_was_changed(self):
        message = self._pip_failure_message(changes_environment=False, returncode=-9)
        self.assertTrue(
            message.startswith(
                "Isolated pip was killed by SIGKILL after 42s; nothing was installed "
                "or changed. "
            ),
            message,
        )
        self.assertNotIn("exit code", message)
        self.assertNotIn("partly changed", message)

    def test_signal_number_without_a_name_is_still_reported_as_a_signal(self):
        message = self._pip_failure_message(changes_environment=False, returncode=-200)
        self.assertIn("was killed by signal 200 after 42s", message)
        self.assertNotIn("exit code", message)


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
                self.module.subprocess, "Popen", return_value=FakePipChild(completed)
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
            mock.patch.object(
                self.module.subprocess, "Popen", return_value=FakePipChild(expired)
            ),
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
        run = mock.patch.object(
            module.subprocess, "Popen", return_value=FakePipChild(outcome)
        )
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
        path = saved_output_path(module._save_pip_output(b"out", b"err")[0])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual(path.parent.parent.resolve(), self.temp_root.resolve())

    def test_successful_save_tells_the_user_to_delete_the_output(self):
        module = load_module()
        message, _ = module._save_pip_output(b"out", b"err")
        self.assertIn("Delete the log when done.", message)

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
            message, _ = module._save_pip_output(b"out", b"err")
        self.assertIn("could not be saved (OSError)", message)
        self.assertNotIn("No space left", message)
        self.assertEqual(
            list(self.temp_root.glob("first-run-pip-*")),
            [],
            "a failed save must remove its partial file and directory",
        )

    def test_log_is_opened_in_binary_mode_so_newlines_are_not_translated(self):
        module = load_module()
        real_open = os.open
        recorded = []

        def recording_open(path, flags, *args, **kwargs):
            if str(path).endswith("pip-output.log"):
                recorded.append(flags)
            return real_open(path, flags, *args, **kwargs)

        # A fake O_BINARY stands in for Windows, where text mode would turn \n into \r\n.
        with (
            mock.patch.object(os, "O_BINARY", 0x8000, create=True),
            mock.patch.object(module.os, "open", side_effect=recording_open),
        ):
            message, _ = module._save_pip_output(b"out\n", b"err\n")
        self.assertIn("is saved, unredacted", message)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0] & 0x8000, 0x8000, "log must be opened binary")
        self.assertTrue(recorded[0] & os.O_EXCL, "log must be created exclusively")

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
            message, _ = module._save_pip_output(b"out", b"err")
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
            message, _ = module._save_pip_output(b"out", b"err")
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


def _lifeline_stand_in(root: Path) -> Path:
    """Write the stand-in for the trusted interpreter that runs the _pip child.

    It runs under -ISB as the real child does, loads environment_install.py and runs the
    real main(), whose `_pip` branch starts the lifeline watcher when isolated_pip passes
    --lifeline. Only pip itself is replaced, by a sleep.
    """
    stand_in = root / "stand_in_pip_child"
    stand_in.write_text(
        f"#!{sys.executable} -ISB\n"
        "import importlib.util, sys, time\n"
        "spec = importlib.util.spec_from_file_location("
        f"'child_under_test', {str(SCRIPT)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "module.pip_adapter = lambda candidate, arguments: time.sleep(60)\n"
        "sys.exit(module.main(sys.argv[sys.argv.index('_pip'):]))\n",
        encoding="utf-8",
    )
    stand_in.chmod(0o700)
    return stand_in


def _child_gone(pid: int) -> bool:
    """True once pid has exited or is a zombie. Uses ps, which exists on every POSIX host."""
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"ps could not report pid {pid}: {result.stderr!r}")
    state = result.stdout.strip()
    return state == "" or state.startswith(("Z", "X"))


def _gone_within(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while not _child_gone(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def _reap(pid: int) -> None:
    """Kill a test child if it still runs, then collect it when this process owns it."""
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    with contextlib.suppress(ChildProcessError):
        os.waitpid(pid, 0)


def _pip_child_fixture(test: unittest.TestCase):
    """Load the module with a stand-in child, and reap every child the test starts."""
    module = load_module()
    root = isolate_temp_dir(test)
    stand_in = _lifeline_stand_in(root)
    children: list[int] = []

    def reap_children():
        for pid in children:
            _reap(pid)

    test.addCleanup(reap_children)
    return module, root, stand_in, children


def _recording_fork_exec(children: list[int], after_fork=None):
    """Stand in for subprocess._fork_exec: record each child pid, then run after_fork."""
    real_fork_exec = subprocess._fork_exec

    def fork_exec(*args, **kwargs):
        pid = real_fork_exec(*args, **kwargs)
        children.append(pid)
        if after_fork is not None:
            after_fork()
        return pid

    return fork_exec


@POSIX_ONLY
class PipChildOutlivesParentTests(unittest.TestCase):
    """The pip child must not outlive isolated_pip however the parent's Python stops."""

    def test_sigint_after_fork_before_popen_returns_stops_the_child(self):
        module, root, stand_in, children = _pip_child_fixture(self)
        with (
            mock.patch.object(
                subprocess,
                "_fork_exec",
                _recording_fork_exec(
                    children, after_fork=lambda: os.kill(os.getpid(), signal.SIGINT)
                ),
            ),
            mock.patch.object(module.ENV, "trusted_interpreter", return_value=stand_in),
            self.assertRaises(KeyboardInterrupt),
        ):
            module.isolated_pip(
                Path("/nonexistent/candidate"),
                ["install", "x"],
                root,
                changes_environment=True,
            )
        self.assertEqual(len(children), 1)
        self.assertTrue(
            _gone_within(children[0], 2),
            "pip child outlived isolated_pip after SIGINT during Popen",
        )

    def test_sigterm_after_fork_before_popen_returns_stops_the_child(self):
        module, root, stand_in, children = _pip_child_fixture(self)
        with (
            mock.patch.object(
                subprocess,
                "_fork_exec",
                _recording_fork_exec(
                    children,
                    after_fork=lambda: os.kill(os.getpid(), signal.SIGTERM),
                ),
            ),
            mock.patch.object(module.ENV, "trusted_interpreter", return_value=stand_in),
            self.assertRaises(SystemExit) as raised,
        ):
            module._run_handling_termination(
                lambda _options: module.isolated_pip(
                    Path("/nonexistent/candidate"),
                    ["install", "x"],
                    root,
                    changes_environment=True,
                ),
                None,
            )
        self.assertEqual(raised.exception.code, 143)
        self.assertEqual(len(children), 1)
        self.assertTrue(
            _gone_within(children[0], 2),
            "pip child outlived isolated_pip after SIGTERM during Popen",
        )

    def test_sigterm_at_kill_entry_on_timeout_still_stops_the_child(self):
        module, root, stand_in, children = _pip_child_fixture(self)
        real_kill = subprocess.Popen.kill

        def kill_signalled(process):
            # The stall stop's kill(), which runs after the TimeoutExpired handler, receives SIGTERM before it sends SIGKILL.
            os.kill(os.getpid(), signal.SIGTERM)
            return real_kill(process)

        with (
            mock.patch.object(subprocess, "_fork_exec", _recording_fork_exec(children)),
            mock.patch.object(subprocess.Popen, "kill", kill_signalled),
            mock.patch.object(module, "PIP_TIMEOUT_SECONDS", 1),
            mock.patch.object(module.ENV, "trusted_interpreter", return_value=stand_in),
            self.assertRaises(SystemExit) as raised,
        ):
            module._run_handling_termination(
                lambda _options: module.isolated_pip(
                    Path("/nonexistent/candidate"),
                    ["install", "x"],
                    root,
                    changes_environment=True,
                ),
                None,
            )
        self.assertEqual(raised.exception.code, 143)
        self.assertEqual(len(children), 1)
        self.assertTrue(
            _gone_within(children[0], 2),
            "pip child outlived a SIGTERM at kill() after the timeout",
        )

    def test_second_sigterm_while_killing_still_stops_the_child(self):
        module, root, stand_in, children = _pip_child_fixture(self)
        real_kill = subprocess.Popen.kill

        def kill_signalled(process):
            # A second signal lands in the except BaseException handler's kill().
            os.kill(os.getpid(), signal.SIGTERM)
            return real_kill(process)

        # The first SIGTERM interrupts communicate() while the child is still sleeping.
        first = threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGTERM))
        self.addCleanup(first.cancel)
        with (
            mock.patch.object(subprocess, "_fork_exec", _recording_fork_exec(children)),
            mock.patch.object(subprocess.Popen, "kill", kill_signalled),
            mock.patch.object(module.ENV, "trusted_interpreter", return_value=stand_in),
            self.assertRaises(SystemExit) as raised,
        ):
            first.start()
            module._run_handling_termination(
                lambda _options: module.isolated_pip(
                    Path("/nonexistent/candidate"),
                    ["install", "x"],
                    root,
                    changes_environment=True,
                ),
                None,
            )
        self.assertEqual(raised.exception.code, 143)
        self.assertEqual(len(children), 1)
        self.assertTrue(
            _gone_within(children[0], 2),
            "pip child outlived a second SIGTERM while it was being killed",
        )


@POSIX_ONLY
class PipChildOutlivesKilledParentTests(unittest.TestCase):
    """An outer SIGKILL of the parent, which no Python code can intercept, stops the child."""

    def test_sigkill_of_the_parent_stops_the_pip_child(self):
        root = isolate_temp_dir(self)
        stand_in = _lifeline_stand_in(root)
        parent_code = "\n".join(
            [
                "import importlib.util, subprocess, sys",
                "from pathlib import Path",
                "from unittest import mock",
                "spec = importlib.util.spec_from_file_location("
                f"'parent_under_test', {str(SCRIPT)!r})",
                "module = importlib.util.module_from_spec(spec)",
                "spec.loader.exec_module(module)",
                "real_fork_exec = subprocess._fork_exec",
                "def fork_exec(*args, **kwargs):",
                "    pid = real_fork_exec(*args, **kwargs)",
                "    print(pid, flush=True)",
                "    return pid",
                "with mock.patch.object(subprocess, '_fork_exec', fork_exec), \\",
                "        mock.patch.object(module.ENV, 'trusted_interpreter',",
                f"                          return_value=Path({str(stand_in)!r})):",
                "    module.isolated_pip(Path('/nonexistent/candidate'), ['install', 'x'],",
                f"                        Path({str(root)!r}), changes_environment=True)",
                "",
            ]
        )
        parent = subprocess.Popen(
            [sys.executable, "-c", parent_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=dict(os.environ, TMPDIR=str(root)),
        )
        self.addCleanup(parent.stdout.close)
        self.addCleanup(parent.stderr.close)
        self.addCleanup(parent.wait)
        self.addCleanup(parent.kill)
        child = int(parent.stdout.readline())
        self.addCleanup(_reap, child)
        time.sleep(1.0)  # the parent is now waiting in communicate()
        self.assertFalse(_child_gone(child), "pip child should run while parent waits")
        os.kill(parent.pid, signal.SIGKILL)
        parent.wait(timeout=10)
        self.assertTrue(
            _gone_within(child, 2), "pip child outlived its parent's SIGKILL"
        )


@POSIX_ONLY
class LifelineOnLowDescriptorTests(unittest.TestCase):
    """The lifeline survives a parent whose stdin, stdout or stderr is closed.

    os.pipe() takes the lowest free descriptors. With fd 1 or 2 closed, the lifeline's read
    end lands there, and Popen's stdout/stderr dup2 in the child overwrites it: the child
    then watches its own output pipe, not the lifeline. The parent's standard fds are
    closed right before isolated_pip, so the lifeline is forced onto them whatever
    startup happened to open.
    """

    def _run_parent(self, closed, *, sleep_seconds):
        root = isolate_temp_dir(self)
        stand_in = _lifeline_stand_in(root)
        if sleep_seconds is not None:
            stand_in.write_text(
                stand_in.read_text().replace(
                    "time.sleep(60)", f"time.sleep({sleep_seconds})"
                ),
                encoding="utf-8",
            )
        parent_code = "\n".join(
            [
                "import importlib.util, os, subprocess, sys",
                "from pathlib import Path",
                "from unittest import mock",
                "spec = importlib.util.spec_from_file_location("
                f"'parent_under_test', {str(SCRIPT)!r})",
                "module = importlib.util.module_from_spec(spec)",
                "spec.loader.exec_module(module)",
                # Report on a duplicate of stdout, taken before fd 1 is closed.
                "report = os.fdopen(os.dup(1), 'w')",
                f"for descriptor in {tuple(closed)!r}:",
                "    os.close(descriptor)",
                "real_fork_exec = subprocess._fork_exec",
                "def fork_exec(*args, **kwargs):",
                "    pid = real_fork_exec(*args, **kwargs)",
                "    print(pid, file=report, flush=True)",
                "    return pid",
                "with mock.patch.object(subprocess, '_fork_exec', fork_exec), \\",
                "        mock.patch.object(module.ENV, 'trusted_interpreter',",
                f"                          return_value=Path({str(stand_in)!r})):",
                "    module.isolated_pip(Path('/nonexistent/candidate'), ['install', 'x'],",
                f"                        Path({str(root)!r}), changes_environment=True)",
                "print('returned', file=report, flush=True)",
                "",
            ]
        )
        parent = subprocess.Popen(
            [sys.executable, "-c", parent_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=dict(os.environ, TMPDIR=str(root)),
        )
        self.addCleanup(parent.stdout.close)
        self.addCleanup(parent.stderr.close)
        self.addCleanup(parent.wait)
        self.addCleanup(parent.kill)
        child = int(parent.stdout.readline())
        self.addCleanup(_reap, child)
        return parent, child

    def _assert_sigkill_stops_child(self, closed):
        parent, child = self._run_parent(closed, sleep_seconds=None)
        time.sleep(
            1.0
        )  # the child's watcher has started; the parent waits in communicate()
        self.assertFalse(_child_gone(child), "pip child should run while parent waits")
        os.kill(parent.pid, signal.SIGKILL)
        parent.wait(timeout=10)
        self.assertTrue(
            _gone_within(child, 2),
            f"pip child outlived its parent's SIGKILL with fds {closed} closed",
        )

    def test_sigkill_stops_child_when_stdout_and_stderr_are_closed(self):
        self._assert_sigkill_stops_child((1, 2))

    def test_sigkill_stops_child_when_stdout_is_closed(self):
        self._assert_sigkill_stops_child((1,))

    def test_sigkill_stops_child_when_stderr_is_closed(self):
        self._assert_sigkill_stops_child((2,))

    def test_sigkill_stops_child_when_all_standard_fds_are_closed(self):
        self._assert_sigkill_stops_child((0, 1, 2))

    def test_pip_still_runs_and_returns_with_standard_fds_closed(self):
        parent, _child = self._run_parent((0, 1, 2), sleep_seconds=0)
        self.assertEqual(
            parent.stdout.readline().strip(), "returned", parent.stderr.read()
        )
        self.assertEqual(parent.wait(timeout=30), 0)


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

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFOs are required")
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
        """Run isolated_pip with the pip child raising interrupt; return stderr text."""
        stderr = io.StringIO()
        with (
            mock.patch.object(
                module.subprocess, "Popen", return_value=FakePipChild(interrupt)
            ),
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
            mock.patch.object(module.subprocess, "Popen", side_effect=pip_run),
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

    def test_dead_stderr_during_apply_does_not_mask_the_interrupt(self):
        # The warning is best effort: a dead stderr (EIO after a hung-up terminal,
        # EPIPE after a closed pipe) must not replace the interrupt with an OSError.
        class DeadStream:
            def __init__(self, code):
                self.code = code

            def write(self, text):
                raise OSError(self.code, os.strerror(self.code))

            def flush(self):
                raise OSError(self.code, os.strerror(self.code))

        def interrupt_raiser(make):
            def raise_it(*args, **kwargs):
                raise make()

            return raise_it

        module = load_module()
        root = isolate_temp_dir(self)
        plan, digest = self._approved_plan(module, root)
        # A closed stream raises ValueError, not OSError, on write and fileno().
        closed_stringio = io.StringIO()
        closed_stringio.close()
        closed_file = open(os.devnull, "w", encoding="utf-8")
        closed_file.close()
        streams = [
            (errno.errorcode[code], DeadStream(code))
            for code in (errno.EIO, errno.EPIPE)
        ] + [
            ("closed StringIO", closed_stringio),
            ("closed file", closed_file),
        ]
        interrupts = (
            ("KeyboardInterrupt", KeyboardInterrupt, lambda: KeyboardInterrupt()),
            ("SystemExit", SystemExit, lambda: SystemExit(143)),
        )
        for name, expected, make in interrupts:
            for stream_name, stream in streams:
                with self.subTest(interrupt=name, stream=stream_name):
                    raised = None
                    with (
                        mock.patch.object(
                            module,
                            "snapshot",
                            return_value={"identity": "unchanged", "installed": {}},
                        ),
                        mock.patch.object(
                            module.subprocess,
                            "Popen",
                            side_effect=interrupt_raiser(make),
                        ),
                        mock.patch.object(
                            module.ENV,
                            "trusted_interpreter",
                            return_value=Path("/usr/bin/python3"),
                        ),
                        mock.patch.object(sys, "stderr", stream),
                    ):
                        try:
                            module.apply(
                                argparse.Namespace(
                                    plan=plan, approved_plan_sha256=digest
                                )
                            )
                        except BaseException as error:
                            raised = error
                    self.assertIsInstance(
                        raised,
                        expected,
                        f"dead stderr replaced the {name} with {type(raised).__name__}",
                    )

    def test_interrupt_saving_pip_output_after_failed_apply_warns_and_propagates(self):
        # pip has started and may have changed the environment; the log save is after
        # its exit, so the interrupt must still get the warning.
        stderr = self._apply_expecting(
            KeyboardInterrupt,
            pip_run=lambda *a, **k: FakePipChild(
                subprocess.CompletedProcess(a, 1, b"", b"")
            ),
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
            pip_run=lambda *a, **k: FakePipChild(
                subprocess.CompletedProcess(a, 0, b"", b"")
            ),
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

    def test_interrupt_in_guarded_snapshot_of_empty_plan_prints_no_warning(self):
        # An empty plan never starts pip, so the post-install snapshot inside the
        # guarded try is reached before pip_started could be set: an interrupt there
        # changed nothing and must stay silent.
        module = load_module()
        root = isolate_temp_dir(self)
        plan, _ = self._approved_plan(module, root)
        document = json.loads(plan.read_text(encoding="utf-8"))
        document["artifacts"] = []
        plan.write_text(json.dumps(document), encoding="utf-8")
        digest = module.ENV.file_digest(plan)
        stderr = io.StringIO()
        with (
            mock.patch.object(
                module,
                "snapshot",
                side_effect=[
                    {"identity": "unchanged", "installed": {}},
                    KeyboardInterrupt(),
                ],
            ),
            mock.patch.object(
                module.subprocess,
                "Popen",
                side_effect=AssertionError("pip must not start"),
            ),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(KeyboardInterrupt),
        ):
            module.apply(argparse.Namespace(plan=plan, approved_plan_sha256=digest))
        self.assertNotIn("partly changed", stderr.getvalue())

    def test_missing_stderr_skips_the_warning_and_keeps_stdout_clean(self):
        # fd 2 closed at startup leaves sys.stderr None. The warning must not fall back
        # to stdout, which carries the JSON result; the interrupt still propagates.
        module = load_module()
        root = isolate_temp_dir(self)
        plan, digest = self._approved_plan(module, root)
        stdout = io.StringIO()
        with (
            mock.patch.object(
                module,
                "snapshot",
                return_value={"identity": "unchanged", "installed": {}},
            ),
            mock.patch.object(
                module.subprocess,
                "Popen",
                return_value=FakePipChild(KeyboardInterrupt()),
            ),
            mock.patch.object(
                module.ENV, "trusted_interpreter", return_value=Path("/usr/bin/python3")
            ),
            mock.patch.object(sys, "stderr", None),
            contextlib.redirect_stdout(stdout),
            self.assertRaises(KeyboardInterrupt),
        ):
            module.apply(argparse.Namespace(plan=plan, approved_plan_sha256=digest))
        self.assertEqual(stdout.getvalue(), "")

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


class _FormatRaisesInterrupt:
    """Stands in for a value the failure message formats, so an interrupt lands mid-message."""

    def __init__(self, interrupt):
        self._interrupt = interrupt

    def __format__(self, spec):
        raise self._interrupt

    def __lt__(self, other):
        # The failure path tests `returncode < 0` before formatting; answer it
        # as "not a signal" so the interrupt still lands in the message.
        return False


STALL_MARKER = b"MARKER-r53-pip-bytes"
STALL_COMMAND_MARKER = "CMDMARKER-r53-candidate"


class _InterruptedStop(FakePipChild):
    """A stalled pip whose stop is interrupted: at the first kill(), or at the collect after it."""

    def __init__(self, outcome, interrupt, at):
        super().__init__(outcome)
        self.interrupt, self.at = interrupt, at

    def kill(self):
        first = not self.killed
        super().kill()
        if first and self.at == "kill":
            raise self.interrupt

    def communicate(self, timeout=None):
        if self.killed and self.at == "collect" and timeout is None:
            self.at = None
            raise self.interrupt
        return super().communicate(timeout)


def _assert_no_pip_output_in_chain(test, error, marker: bytes, command_marker: str):
    """Fail if any link of error's __context__ or __cause__ chain is a TimeoutExpired,
    holds pip's bytes, or the formatted traceback names the command line."""
    pending, seen = [error], set()
    while pending:
        link = pending.pop()
        if link is None or id(link) in seen:
            continue
        seen.add(id(link))
        test.assertNotIsInstance(link, subprocess.TimeoutExpired)
        for attribute in ("output", "stdout", "stderr"):
            value = getattr(link, attribute, None)
            test.assertFalse(
                isinstance(value, bytes) and marker in value,
                f"{attribute} of {type(link).__name__} in the chain holds pip output",
            )
        pending += [link.__cause__, link.__context__]
    text = "".join(traceback.format_exception(error))
    test.assertNotIn(command_marker, text)
    test.assertNotIn(marker.decode(), text)


def _stand_in_printing_marker(root: Path) -> Path:
    """A POSIX stand-in for the interpreter: it prints pip-like bytes, then stalls."""
    stand_in = root / "python"
    stand_in.write_text(
        "#!/bin/sh\nprintf '%s' '" + STALL_MARKER.decode() + "'\nexec sleep 30\n",
        encoding="utf-8",
    )
    stand_in.chmod(0o700)
    return stand_in


class StallPathInterruptTests(unittest.TestCase):
    """An interrupt on the pip stall or failure path never chains pip output or keeps the log."""

    MARKER = b"MARKER-r37-pip-bytes"

    def test_interrupt_while_saving_stalled_output_chains_no_timeout(self):
        module = load_module()
        isolate_temp_dir(self)
        expired = subprocess.TimeoutExpired(
            cmd=["pip"], timeout=0.1, output=self.MARKER, stderr=self.MARKER
        )
        with (
            mock.patch.object(module, "PIP_TIMEOUT_SECONDS", 0.1),
            mock.patch.object(
                module.subprocess, "Popen", return_value=FakePipChild(expired)
            ),
            mock.patch.object(
                module, "_save_pip_output", side_effect=KeyboardInterrupt()
            ),
            mock.patch.object(
                module.ENV, "trusted_interpreter", return_value=Path("/usr/bin/python3")
            ),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            module.isolated_pip(
                Path("/tmp/candidate"),
                ["install", "x"],
                Path("/tmp"),
                changes_environment=True,
            )
        error = raised.exception
        while error is not None:
            self.assertNotIsInstance(error, subprocess.TimeoutExpired)
            for attribute in ("stdout", "stderr"):
                value = getattr(error, attribute, None)
                self.assertFalse(
                    isinstance(value, bytes) and self.MARKER in value,
                    f"{attribute} of {type(error).__name__} in the chain holds pip output",
                )
            error = error.__context__

    def test_interrupt_after_stalled_save_removes_the_log(self):
        module = load_module()
        temp_root = isolate_temp_dir(self)
        expired = subprocess.TimeoutExpired(
            cmd=["pip"], timeout=0.1, output=self.MARKER
        )
        for interrupt in (KeyboardInterrupt(), SystemExit(143)):
            with self.subTest(interrupt=type(interrupt).__name__):
                with (
                    mock.patch.object(
                        module,
                        "PIP_TIMEOUT_SECONDS",
                        _FormatRaisesInterrupt(interrupt),
                    ),
                    mock.patch.object(
                        module.subprocess, "Popen", return_value=FakePipChild(expired)
                    ),
                    mock.patch.object(
                        module.ENV,
                        "trusted_interpreter",
                        return_value=Path("/usr/bin/python3"),
                    ),
                    self.assertRaises(type(interrupt)),
                ):
                    module.isolated_pip(
                        Path("/tmp/candidate"),
                        ["install", "x"],
                        Path("/tmp"),
                        changes_environment=True,
                    )
                self.assertEqual(
                    list(temp_root.glob("first-run-pip-*")),
                    [],
                    "an interrupt after the save must remove the saved log",
                )

    def test_interrupt_after_failed_save_removes_the_log(self):
        module = load_module()
        temp_root = isolate_temp_dir(self)
        for interrupt in (KeyboardInterrupt(), SystemExit(143)):
            with self.subTest(interrupt=type(interrupt).__name__):
                failed = subprocess.CompletedProcess(
                    args=["pip"],
                    returncode=_FormatRaisesInterrupt(interrupt),
                    stdout=self.MARKER,
                    stderr=self.MARKER,
                )
                with (
                    mock.patch.object(
                        module.subprocess, "Popen", return_value=FakePipChild(failed)
                    ),
                    mock.patch.object(
                        module.ENV,
                        "trusted_interpreter",
                        return_value=Path("/usr/bin/python3"),
                    ),
                    self.assertRaises(type(interrupt)),
                ):
                    module.isolated_pip(
                        Path("/tmp/candidate"),
                        ["install", "x"],
                        Path("/tmp"),
                        changes_environment=True,
                    )
                self.assertEqual(
                    list(temp_root.glob("first-run-pip-*")),
                    [],
                    "an interrupt after the save must remove the saved log",
                )

    def test_failed_removal_after_interrupt_still_propagates_from_isolated_pip(self):
        module = load_module()
        isolate_temp_dir(self)
        failed = subprocess.CompletedProcess(
            args=["pip"],
            returncode=_FormatRaisesInterrupt(KeyboardInterrupt()),
            stdout=self.MARKER,
            stderr=self.MARKER,
        )
        with (
            mock.patch.object(
                module.subprocess, "Popen", return_value=FakePipChild(failed)
            ),
            mock.patch.object(
                module.ENV, "trusted_interpreter", return_value=Path("/usr/bin/python3")
            ),
            mock.patch.object(
                module.shutil, "rmtree", side_effect=OSError(errno.EBUSY, "busy")
            ),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            module.isolated_pip(
                Path("/tmp/candidate"),
                ["install", "x"],
                Path("/tmp"),
                changes_environment=True,
            )
        self.assertNotIsInstance(raised.exception.__context__, OSError)
        self.assertNotIn("busy", repr(raised.exception.__context__))

    def test_interrupt_at_stall_kill_or_collect_chains_no_timeout_and_stops_child(self):
        module = load_module()
        isolate_temp_dir(self)
        interrupts = (
            ("KeyboardInterrupt", KeyboardInterrupt),
            ("SystemExit(143)", lambda: SystemExit(143)),
        )
        for at in ("kill", "collect"):
            for name, make in interrupts:
                for changes in (True, False):
                    with self.subTest(at=at, interrupt=name, changes=changes):
                        expired = subprocess.TimeoutExpired(
                            cmd=["pip", STALL_COMMAND_MARKER],
                            timeout=0.1,
                            output=STALL_MARKER,
                            stderr=STALL_MARKER,
                        )
                        interrupt = make()
                        child = _InterruptedStop(expired, interrupt, at)
                        with (
                            mock.patch.object(module, "PIP_TIMEOUT_SECONDS", 0.1),
                            mock.patch.object(
                                module.subprocess, "Popen", return_value=child
                            ),
                            mock.patch.object(
                                module.ENV,
                                "trusted_interpreter",
                                return_value=Path("/usr/bin/python3"),
                            ),
                            self.assertRaises(type(interrupt)) as raised,
                        ):
                            module.isolated_pip(
                                Path("/tmp/" + STALL_COMMAND_MARKER),
                                ["install", "x"],
                                Path("/tmp"),
                                changes_environment=changes,
                            )
                        _assert_no_pip_output_in_chain(
                            self, raised.exception, STALL_MARKER, STALL_COMMAND_MARKER
                        )
                        self.assertTrue(child.killed, "the stalled pip was not killed")


@POSIX_ONLY
class StallStopSignalTests(unittest.TestCase):
    """A real signal at the stall kill: the chain stays clean and the real child is gone."""

    def run_stall_stopped_by(self, signum: int, through_termination: bool):
        module, root, _stand_in, children = _pip_child_fixture(self)
        stand_in = _stand_in_printing_marker(root)
        real_kill = subprocess.Popen.kill
        sent = []

        def kill_signalled(process):
            if not sent:
                sent.append(True)
                os.kill(os.getpid(), signum)
            return real_kill(process)

        def run_pip():
            return module.isolated_pip(
                Path("/nonexistent/" + STALL_COMMAND_MARKER),
                ["install", "x"],
                root,
                changes_environment=True,
            )

        with (
            mock.patch.object(subprocess, "_fork_exec", _recording_fork_exec(children)),
            mock.patch.object(subprocess.Popen, "kill", kill_signalled),
            mock.patch.object(module, "PIP_TIMEOUT_SECONDS", 1),
            mock.patch.object(module.ENV, "trusted_interpreter", return_value=stand_in),
        ):
            if through_termination:
                with self.assertRaises(SystemExit) as raised:
                    module._run_handling_termination(lambda _options: run_pip(), None)
            else:
                with self.assertRaises(KeyboardInterrupt) as raised:
                    run_pip()
        _assert_no_pip_output_in_chain(
            self, raised.exception, STALL_MARKER, STALL_COMMAND_MARKER
        )
        self.assertEqual(len(children), 1)
        self.assertTrue(
            _gone_within(children[0], 2),
            "pip child outlived isolated_pip after a signal at the stall kill",
        )
        return raised.exception

    def test_sigint_at_stall_kill_stops_child_and_chains_no_timeout(self):
        self.run_stall_stopped_by(signal.SIGINT, through_termination=False)

    def test_sigterm_at_stall_kill_exits_143_chains_no_timeout_and_stops_child(self):
        error = self.run_stall_stopped_by(signal.SIGTERM, through_termination=True)
        self.assertEqual(error.code, 143)


class FlushFailsOnClose:
    """Write stream whose final flush fails the way a full or failing disk does."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        return self._stream.write(data)

    def close(self):
        self._stream.close()
        raise OSError(errno.ENOSPC, "No space left on device")


class FinalFlushFailureTests(unittest.TestCase):
    """A failing final flush is a labelled download failure, never a raw OSError."""

    URL = "https://files.example.invalid/pkg-1.0-py3-none-any.whl"

    def _failing_close(self, target):
        real_open = Path.open

        def open_with_failing_close(path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            return FlushFailsOnClose(handle) if Path(path) == target else handle

        return mock.patch.object(Path, "open", open_with_failing_close)

    def test_normal_path_flush_failure_is_a_labelled_download_failure(self):
        module = load_module()
        target = isolate_temp_dir(self) / "pkg-1.0-py3-none-any.whl"
        response = ReadOnlyBlocksResponse([b"wheel-", b"bytes", b""])
        with (
            self._failing_close(target),
            mock.patch.object(module, "_open_url", return_value=response),
            self.assertRaises(ValueError) as raised,
        ):
            module._download(self.URL, target, 5, 5)
        self.assertEqual(
            str(raised.exception),
            "Wheel download failed: OSError (ENOSPC); nothing was installed or changed.",
        )
        self.assertIsNone(raised.exception.__cause__)
        self.assertFalse(target.exists(), "partial wheel left behind")

    def test_deadline_path_flush_failure_keeps_the_deadline_message(self):
        module = load_module()
        stop = threading.Event()
        self.addCleanup(stop.set)
        target = isolate_temp_dir(self) / "pkg-1.0-py3-none-any.whl"
        with (
            self._failing_close(target),
            mock.patch.object(
                module, "_open_url", return_value=EndlessBlocksResponse(stop)
            ),
            self.assertRaises(ValueError) as raised,
        ):
            module._download(self.URL, target, 5, 0.2)
        self.assertIn("deadline", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertFalse(target.exists(), "partial wheel left behind")


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


class TruncatedWheelBodyTests(unittest.TestCase):
    def test_body_cut_short_of_declared_length_raises_labelled_error(self):
        module = load_module()
        root = isolate_temp_dir(self)
        target = root / "pkg-1.0-py3-none-any.whl"
        # The server declares 1000 bytes, sends 10, then closes the connection.
        response = _FakeResponse(b"x" * 10, length=1000)
        with mock.patch.object(module, "_open_url", return_value=response):
            with self.assertRaises(ValueError) as raised:
                module._download(
                    "https://files.example.invalid/pkg-1.0-py3-none-any.whl",
                    target,
                    read_timeout=5,
                    deadline=5,
                )
        self.assertIn("cut short", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertFalse(target.exists(), "partial wheel was left behind")

    def test_body_one_byte_short_of_declared_length_is_cut_short(self):
        # Pins the boundary: received == declared is complete, received < declared is not.
        module = load_module()
        root = isolate_temp_dir(self)
        target = root / "pkg-1.0-py3-none-any.whl"
        response = _FakeResponse(b"x" * 999, length=1000)
        with mock.patch.object(module, "_open_url", return_value=response):
            with self.assertRaises(ValueError) as raised:
                module._download(
                    "https://files.example.invalid/pkg-1.0-py3-none-any.whl",
                    target,
                    read_timeout=5,
                    deadline=5,
                )
        self.assertIn("cut short", str(raised.exception))
        self.assertFalse(target.exists(), "partial wheel was left behind")

    def test_chunked_body_has_no_length_and_succeeds(self):
        # http.client leaves length None for chunked framing, so nothing is cut short.
        module = load_module()
        root = isolate_temp_dir(self)
        target = root / "pkg-1.0-py3-none-any.whl"
        response = _FakeResponse(b"wheel-body", length=None)
        with mock.patch.object(module, "_open_url", return_value=response):
            module._download(
                "https://files.example.invalid/pkg-1.0-py3-none-any.whl",
                target,
                read_timeout=5,
                deadline=5,
            )
        self.assertEqual(target.read_bytes(), b"wheel-body")


CHILD_APPLY_SCRIPT = """
import importlib.util, json, sys, time
from pathlib import Path

script, root = sys.argv[1], Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("environment_install", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
plan = root / "plan.json"
plan.write_text(json.dumps({
    "schema": 1,
    "candidate": "/candidate",
    "identity": "id",
    "requirements": "/requirements.txt",
    "requirements_sha256": "x",
    "artifacts": [{"path": "/pkg.whl", "sha256": "x", "name": "pkg", "version": "1"}],
}), encoding="utf-8")
module.ENV.file_digest = lambda path: "x"
module.snapshot = lambda candidate: {"identity": "id", "installed": {}}

def pip_running(*args, **kwargs):
    print("READY", flush=True)
    time.sleep(30)

module.isolated_pip = pip_running
sys.exit(module.main(["apply", "--plan", str(plan), "--approved-plan-sha256", "x"]))
"""


class InterruptedApplyDeadStderrExitTests(unittest.TestCase):
    """A real process whose stderr is dead must still exit with the signal status."""

    @unittest.skipIf(os.name == "nt", "POSIX pipes and SIGTERM semantics")
    def test_sigterm_during_apply_with_dead_stderr_exits_143_not_120(self):
        root = isolate_temp_dir(self)
        child = root / "child_apply.py"
        child.write_text(CHILD_APPLY_SCRIPT, encoding="utf-8")
        # Keep the pip-output temp directory out of the real system temp dir.
        environment = dict(os.environ, TMPDIR=str(root))
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", "-B", str(child), str(SCRIPT), str(root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        self.addCleanup(process.kill)
        self.addCleanup(process.stdout.close)
        self.assertEqual(process.stdout.readline().strip(), b"READY")
        # Closing the only read end makes the warning write fail with EPIPE.
        process.stderr.close()
        process.send_signal(signal.SIGTERM)
        self.assertEqual(
            process.wait(timeout=20),
            143,
            "a dead stderr changed the exit status of an interrupted apply",
        )


class DocumentedBoundsTests(unittest.TestCase):
    def test_bounds_match_their_documented_values(self):
        # The comments above the constants in environment_install.py state these
        # values; a change to either must change this pin in the same commit.
        module = load_module()
        self.assertEqual(module.PIP_TIMEOUT_SECONDS, 900)
        self.assertEqual(module.PLAN_DOWNLOAD_DEADLINE_SECONDS, 600)
        self.assertEqual(
            module.PIP_TIMEOUT_SECONDS + module.PLAN_DOWNLOAD_DEADLINE_SECONDS,
            25 * 60,
        )
        self.assertEqual(module.MAX_WHEEL_BYTES, 1024**3)
        self.assertEqual(module.DOWNLOAD_READ_TIMEOUT_SECONDS, 30)
        self.assertLess(
            module.DOWNLOAD_READ_TIMEOUT_SECONDS,
            module.PLAN_DOWNLOAD_DEADLINE_SECONDS,
        )


@POSIX_ONLY
class LifelinePipeAllocationTests(unittest.TestCase):
    def test_failed_second_move_closes_the_first_and_leaks_no_descriptor(self):
        module = load_module()
        fcntl = importlib.import_module("fcntl")
        real_fcntl = fcntl.fcntl
        calls = []

        def second_move_fails(descriptor, command, argument=0):
            calls.append(descriptor)
            if len(calls) == 2:
                raise OSError(errno.EMFILE, "too many open files")
            return real_fcntl(descriptor, command, argument)

        before = set(os.listdir("/dev/fd"))
        with mock.patch.object(fcntl, "fcntl", side_effect=second_move_fails):
            with self.assertRaises(OSError) as raised:
                module._lifeline_pipe()
        self.assertEqual(raised.exception.errno, errno.EMFILE)
        self.assertEqual(len(calls), 2)
        self.assertEqual(set(os.listdir("/dev/fd")), before)


class SavedLogAdviceTests(unittest.TestCase):
    def test_saved_log_message_carries_the_advice_word_for_word(self):
        isolate_temp_dir(self)
        module = load_module()
        message, directory = module._save_pip_output(b"out", b"err")
        self.assertIsNotNone(directory)
        advice = (
            "Inspect it locally if needed. Keep its contents out of chat and tool "
            "output. Delete the log when done."
        )
        self.assertTrue(
            message.endswith(" " + advice),
            f"saved-log message must end with the advice, got {message!r}",
        )


UNCHAINED_SENTINEL = "caught-text-sentinel-8c1d"


def _refuse_exclusive_open(real_open):
    """Path.open replacement that raises FileExistsError for the "xb" open only."""

    def open_guard(path, mode="r", *args, **kwargs):
        if mode == "xb":
            raise FileExistsError(errno.EEXIST, UNCHAINED_SENTINEL)
        return real_open(path, mode, *args, **kwargs)

    return open_guard


# One row per `raise ... from None` in environment_install.py: (site, driver method).
UNCHAINED_RAISE_SITES = (
    ("_download: declared length over MAX_WHEEL_BYTES", "_site_download_size"),
    ("_download: body cut short", "_site_download_truncated"),
    ("_download: https-to-http redirect refused", "_site_download_redirect"),
    ("_download: stalled read", "_site_download_read_timeout"),
    ("_download: any other transfer failure", "_site_download_generic"),
    ("_publish_plan: plan exists (hard link)", "_site_publish_exists_by_link"),
    ("_publish_plan: plan exists (exclusive copy)", "_site_publish_exists_by_copy"),
    ("plan(): cache removal fails under a labelled error", "_site_plan_cache_removal"),
)


class UnchainedRaiseSitesTests(unittest.TestCase):
    """Every `raise ... from None` in environment_install.py raises an unchained error.

    The contract: no exception text is ever chained. Each row drives one such site
    through a real call path with an injected exception whose text is UNCHAINED_SENTINEL,
    and checks that the raised error has no __cause__, suppresses its context, and
    prints none of the sentinel. __context__ is not pinned to None: Python sets it to
    the handled exception whenever a raise sits inside an except block (as the
    _publish_plan sites do), and `from None` is what keeps it out of the output.
    The count check fails when a `from None` site is added without a row here.
    """

    def _raised(self, drive):
        with self.assertRaises(ValueError) as raised:
            drive()
        return raised.exception

    def _download(self, module, **open_patch):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with mock.patch.object(module, "_open_url", **open_patch):
            return self._raised(
                lambda: module._download(
                    "https://example.invalid/wheel.whl",
                    Path(directory.name) / "wheel.whl",
                    5,
                    time.monotonic() + 30,
                )
            )

    def _site_download_size(self):
        module = load_module()
        response = _FakeResponse(b"", length=module.MAX_WHEEL_BYTES + 1)
        return self._download(module, return_value=response)

    def _site_download_truncated(self):
        module = load_module()
        return self._download(module, return_value=_FakeResponse(b"abc", length=10))

    def _site_download_redirect(self):
        module = load_module()
        return self._download(
            module, side_effect=module._HttpsDowngradeRefused(UNCHAINED_SENTINEL)
        )

    def _site_download_read_timeout(self):
        module = load_module()
        return self._download(module, side_effect=TimeoutError(UNCHAINED_SENTINEL))

    def _site_download_generic(self):
        module = load_module()
        return self._download(
            module, side_effect=urllib_error.URLError(UNCHAINED_SENTINEL)
        )

    def _publish(self, module):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        staged = root / "staged.json"
        staged.write_text("{}", encoding="utf-8")
        return self._raised(
            lambda: module._publish_plan(staged, root / "approval.json")
        )

    def _site_publish_exists_by_link(self):
        module = load_module()
        with mock.patch.object(
            module.os,
            "link",
            side_effect=FileExistsError(errno.EEXIST, UNCHAINED_SENTINEL),
        ):
            return self._publish(module)

    def _site_publish_exists_by_copy(self):
        module = load_module()
        real_open = Path.open
        with (
            mock.patch.object(
                module.os, "link", side_effect=OSError(errno.EPERM, "no hard links")
            ),
            mock.patch.object(Path, "open", new=_refuse_exclusive_open(real_open)),
        ):
            return self._publish(module)

    def _site_plan_cache_removal(self):
        module = load_module()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        candidate = root / "env"
        candidate.mkdir()
        requirements = root / "requirements.txt"
        requirements.write_text("pkg==1.0\n", encoding="utf-8")
        options = argparse.Namespace(
            candidate=candidate,
            requirements=requirements,
            plan=root / "approval.json",
            change=[],
            no_index=False,
            find_links=None,
        )

        def fake_pip(_candidate, arguments, _working, *, changes_environment):
            if "--report" in arguments:
                report = Path(arguments[arguments.index("--report") + 1])
                report.write_text(
                    json.dumps({"install": [WHEEL_ITEM]}), encoding="utf-8"
                )

        def failing_cache(_item, _directory, _download_deadline):
            raise ValueError("Wheel download stalled: labelled.")

        real_rmtree = shutil.rmtree

        def rmtree_fails_for_wheel_cache(path, *args, **kwargs):
            if "-wheels-" in str(path):
                raise OSError(errno.EBUSY, UNCHAINED_SENTINEL)
            return real_rmtree(path, *args, **kwargs)

        with (
            mock.patch.object(module, "snapshot", return_value=BEFORE),
            mock.patch.object(module.ENV, "read_pins", return_value={"pkg": "1.0"}),
            mock.patch.object(module, "isolated_pip", side_effect=fake_pip),
            mock.patch.object(module, "cache_wheel", side_effect=failing_cache),
            mock.patch.object(
                module.shutil, "rmtree", side_effect=rmtree_fails_for_wheel_cache
            ),
        ):
            try:
                return self._raised(lambda: module.plan(options))
            finally:
                for leftover in root.glob("*-wheels-*"):
                    real_rmtree(leftover)

    def test_every_from_none_site_has_a_row(self):
        source = SCRIPT.read_text(encoding="utf-8")
        sites = re.findall(r"\bfrom None\b", source)
        self.assertEqual(
            len(sites),
            len(UNCHAINED_RAISE_SITES),
            f"environment_install.py has {len(sites)} `from None` sites but the table "
            f"drives {len(UNCHAINED_RAISE_SITES)}: add a row for every new site",
        )

    def test_every_from_none_site_raises_unchained(self):
        for label, method in UNCHAINED_RAISE_SITES:
            with self.subTest(site=label):
                error = getattr(self, method)()
                self.assertIsNone(error.__cause__, f"{label}: __cause__ is set")
                self.assertTrue(
                    error.__suppress_context__, f"{label}: context is not suppressed"
                )
                rendered = "".join(traceback.format_exception(error))
                self.assertNotIn(
                    UNCHAINED_SENTINEL,
                    rendered,
                    f"{label}: the caught exception's text is printed",
                )


if __name__ == "__main__":
    unittest.main()

"""Bounded-time checks for the wheel download and isolated pip steps.

Every server here listens on 127.0.0.1 only, and every server thread is joined
in its cleanup so a stalled fixture can never hang the suite. Download worker
threads are daemons: by design they may outlive a test by a few seconds, because
a stalled name lookup cannot be interrupted.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.util
import json
import os
import shutil
import signal
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

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/traigent-first-run/scripts/environment_install.py"


CHILD_CODE = """
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("environment_install_under_test", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
text = sys.stdin.read()
started = time.monotonic()
redacted = module._redacted_pip_output(text)
elapsed = time.monotonic() - started
sys.stdout.write(json.dumps({"elapsed": elapsed, "redacted": redacted}))
"""


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
            self.assertIn("exceeded the 2 MB size limit", str(raised.exception))
            self.assertIn("nothing was installed or changed", str(raised.exception))
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
            self.assertIn("exceeded the 2 MB size limit", str(raised.exception))
            self.assertNotIn("sent nothing", str(raised.exception))
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


class DownloadRefusalAndInterruptTests(unittest.TestCase):
    def test_http_client_invalid_url_error_text_is_redacted_and_not_chained(self):
        module = load_module()
        error = http.client.InvalidURL("nonnumeric port: 'https://alice:S3CRET@h/x'")
        self.assert_download_error_is_safe(module, error)

    def test_url_error_text_is_redacted_and_not_chained(self):
        module = load_module()
        error = urllib_error.URLError("https://alice:S3CRET@h/x unreachable")
        self.assert_download_error_is_safe(module, error)

    def test_http_error_is_redacted_and_not_chained(self):
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
            self.assertFalse(target.exists(), "partial wheel must be removed")

    def test_https_to_http_redirect_is_refused(self):
        module = load_module()
        handler = module._NoDowngradeRedirectHandler()
        request = urllib.request.Request("https://h/x.whl")
        with self.assertRaises(module._HttpsDowngradeRefused):
            handler.redirect_request(request, None, 302, "Found", {}, "http://h/x.whl")

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
            self.assertFalse(target.exists())

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
    def test_pip_timeout_is_bounded_and_child_output_is_redacted(self):
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
        self.assertIn("<artifact-location>", message)
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

    def test_pip_timeout_bytes_output_is_decoded_and_redacted(self):
        module = load_module()
        expired = subprocess.TimeoutExpired(
            cmd=["pip"],
            timeout=0.1,
            output=b"Collecting x from https://u:p@h/x\n",
            stderr=b"",
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
                    changes_environment=False,
                )
        message = str(raised.exception)
        self.assertIn("Collecting x from <artifact-location>", message)
        self.assertNotIn("u:p", message)
        self.assertIsNone(raised.exception.__context__)

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


class RedactionTests(unittest.TestCase):
    CREDENTIAL_FORMS = (
        "HTTPS://user:secret@h/x",
        "git+ssh://user:secret@h/x",
        "ftp://user:secret@h/x",
        "user:secret@host/x",
        "https://user:secret@h/x",
        "file:///tmp/x.whl",
        "a:secret@host/x",
        "x(https://user:secret@h/y)",
        "u:p@h",
    )

    def test_every_credential_form_is_replaced_and_no_secret_survives(self):
        module = load_module()
        for form in self.CREDENTIAL_FORMS:
            with self.subTest(form=form):
                redacted = module._redacted_pip_output(f"Collecting x from {form}\n")
                self.assertNotIn("secret", redacted)
                self.assertIn("<artifact-location>", redacted)

    def test_bare_url_token_is_replaced_whole(self):
        module = load_module()
        for form in self.CREDENTIAL_FORMS:
            with self.subTest(form=form):
                self.assertEqual(
                    module._redacted_pip_output(form),
                    "<artifact-location>",
                )

    def test_plain_pip_line_is_kept_unchanged(self):
        module = load_module()
        line = "Collecting pkg==1.0\n"
        self.assertEqual(module._redacted_pip_output(line), line)

    def test_bytes_and_none_parts_are_decoded_and_redacted(self):
        module = load_module()
        redacted = module._redacted_pip_output(
            b"HTTPS://user:secret@h/x\n", None, "git+ssh://user:secret@h/y"
        )
        self.assertNotIn("secret", redacted)
        self.assertEqual(redacted.count("<artifact-location>"), 2)

    SECRET_FORMS = (
        "alice%3AS3CRET%40host/x",
        "https%3A%2F%2Falice%3AS3CRET%40h%2Fx",
        "ghp_S3CRET@github.com",
        ":S3CRET@host",
        "user:S3CRET@",
        "password=S3CRET",
        "token=S3CRET",
        "secret=S3CRET",
        # a key that ends its token with a separator; the value is the next token
        "foo:password= S3CRET",
        "my-token= S3CRET",
        "user:password: S3CRET",
        "api_key=S3CRET",
        "password= S3CRET",
        "Authorization: Basic S3CRET",
        "Authorization: Bearer S3CRET",
        "Proxy-Authorization: Basic S3CRET",
        "Basic S3CRET",
        "Bearer S3CRET",
        "ghp_S3CRETabcdef12",
        "x=sk-S3CRETabcdef12",
        "gho_S3CRETabcdef12",
        "github_pat_S3CRETabcdef12",
        "glpat-S3CRETabcdef12",
        "xoxb-S3CRETabcdef12",
        "xoxp-S3CRETabcdef12",
    )

    def test_encoded_token_only_key_value_header_and_prefixed_forms_are_redacted(self):
        module = load_module()
        for form in self.SECRET_FORMS:
            with self.subTest(form=form):
                redacted = module._redacted_pip_output(f"Collecting x from {form}\n")
                self.assertNotIn("S3CRET", redacted)
                self.assertIn("<artifact-location>", redacted)

    def test_whitespace_split_userinfo_is_redacted_through_the_host_token(self):
        module = load_module()
        art = "<artifact-location>"
        expected = {
            "user:S3C RET@host/x": f"Collecting {art} {art}\n",
            "user:a b c@host": f"Collecting {art} {art} {art}\n",
        }
        for form, want in expected.items():
            with self.subTest(form=form):
                self.assertEqual(
                    module._redacted_pip_output(f"Collecting {form}\n"), want
                )

    SECURITY_PASS_FORMS = (
        # key-value with spaces around the separator
        "password = S3CRET",
        "token : S3CRET",
        # quoted and JSON keys
        '{"password": "S3CRET"}',
        '"token":"S3CRET"',
        "'secret': 'S3CRET'",
        # keys outside the list, and camelCase
        "private_key=S3CRET",
        "apiToken=S3CRET",
        "client_secret=S3CRET",
        "credentials=S3CRET",
        # option form, with a space or with "="
        "--password S3CRET",
        "--token=S3CRET",
        # double percent-encoding
        "password%253DS3CRET",
        "alice%253AS3CRET%2540host",
        # token prefixes: PyPI API tokens and AWS access key ids
        "pypi-AgEIcHlwaS5vcmcS3CRETabc",
        "AKIAS3CRETABCDEFGHIJ",
        "ASIAS3CRETABCDEFGHIJ",
        # userinfo split by a separator that str.splitlines would break on
        "user:S3C\x0bRET@host",
        "user:S3C\x0cRET@host",
        "user:S3C\x1cRET@host",
        "user:S3C\x85RET@host",
        "user:S3C RET@host",
    )

    def test_security_pass_forms_are_redacted_and_no_secret_survives(self):
        module = load_module()
        for form in self.SECURITY_PASS_FORMS:
            with self.subTest(form=form):
                redacted = module._redacted_pip_output(f"Collecting x from {form}\n")
                self.assertNotIn("S3C", redacted)
                self.assertNotIn("RET", redacted)
                self.assertIn("<artifact-location>", redacted)

    def test_authorization_header_redacts_every_remaining_token_on_its_line(self):
        # Digest and Negotiate are not in the Basic/Bearer scheme list, so only
        # the header-name rule (redact_rest) can hide their credential tokens.
        module = load_module()
        lines = (
            'Authorization: Digest username="alice", response="S3CRET"\n',
            "Proxy-Authorization: Negotiate S3CRETPART1 S3CRETPART2\n",
        )
        for line in lines:
            with self.subTest(line=line):
                redacted = module._redacted_pip_output(line)
                self.assertNotIn("S3CRET", redacted)
                self.assertNotIn("alice", redacted)
                header = line.split(":", 1)[0] + ":"
                self.assertIn(header, redacted)

    def test_lines_pip_prints_for_normal_work_are_unchanged(self):
        module = load_module()
        lines = (
            "Collecting pkg==1.0\n",
            "ERROR: Could not find a version that satisfies the requirement pkg==1.0\n",
            "Downloading pkg-1.0-py3-none-any.whl (1.2 MB)\n",
            "Requirement already satisfied: pkg in ./lib (1.0)\n",
            "pkg @ \n",
            "name @ \n",
            "task-runner-12345678 disk-abcdefgh12\n",
            "Collecting pypi-attestations==0.0.21\n",
            "Collecting pypi-simple\n",
            "Collecting tokenizers==0.21.0\n",
            # Package names that end in a key name are not credentials.
            "Collecting tiktoken==0.8.0\n",
            "No matching distribution found for tiktoken==0.8.0\n",
            "Requirement already satisfied: tiktoken in ./lib (0.8.0)\n",
            "The user requested tiktoken==0.8.0\n",
            "Collecting google-auth==2.36.0\n",
            "Requirement already satisfied: google-auth in ./lib (2.36.0)\n",
            "Collecting pkg-token==1.0\n",
        )
        for line in lines:
            with self.subTest(line=line):
                self.assertEqual(module._redacted_pip_output(line), line)

    def test_redaction_keeps_line_endings_and_other_lines_exactly(self):
        module = load_module()
        text = "Collecting pkg==1.0\r\npassword=S3CRET\nDownloading pkg-1.0.whl\n"
        self.assertEqual(
            module._redacted_pip_output(text),
            "Collecting pkg==1.0\r\n<artifact-location>\nDownloading pkg-1.0.whl\n",
        )

    def assertRedactsQuickly(self, text):
        # Run in a child process so a catastrophic regex fails this test
        # instead of hanging the whole suite.
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-c", CHILD_CODE, str(SCRIPT)],
                input=text,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            self.fail("redaction did not finish within 10 s")
        self.assertEqual(
            completed.returncode,
            0,
            f"redaction child failed: {completed.stderr}",
        )
        result = json.loads(completed.stdout)
        elapsed = result["elapsed"]
        self.assertLess(elapsed, 1.0, f"redaction took {elapsed:.2f}s")
        return result["redacted"]

    def test_long_colon_token_without_at_is_linear_and_unchanged(self):
        for text in (":" * 4000, "a:" * 2000):
            with self.subTest(prefix=text[:2]):
                self.assertEqual(self.assertRedactsQuickly(text), text)

    def test_long_letter_run_without_scheme_separator_is_linear_and_unchanged(self):
        text = "a" * 100000
        self.assertEqual(self.assertRedactsQuickly(text), text)

    def test_colon_dense_line_before_credential_url_is_fast_and_redacted(self):
        redacted = self.assertRedactsQuickly(":" * 50000 + " https://user:secret@h/x")
        self.assertNotIn("secret", redacted)
        self.assertIn("<artifact-location>", redacted)

    def test_five_megabyte_mixed_credential_line_is_linear(self):
        text = (
            ("a%3A" * 300000)
            + ("password= " * 200000)
            + ("Bearer " * 200000)
            + ("ghp_" * 300000)
        )
        self.assertGreaterEqual(len(text), 5_000_000)
        redacted = self.assertRedactsQuickly(text)
        self.assertNotIn("a%3A", redacted)
        self.assertNotIn("ghp_", redacted)

    def test_five_megabyte_line_mixing_spaced_option_encoded_separator_and_aws_is_linear(
        self,
    ):
        text = (
            ('"password" = LEAK ' * 80000)
            + ("password%253DLEAK " * 80000)
            + ("--token LEAK " * 120000)
            + ("user:LEAK\x0bX@host " * 40000)
            + ("AKIAABCDEFGHIJKLMNOP " * 20000)
        )
        self.assertGreaterEqual(len(text), 5_000_000)
        redacted = self.assertRedactsQuickly(text)
        self.assertNotIn("LEAK", redacted)
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", redacted)


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


class DownloadReadCallTests(unittest.TestCase):
    def test_body_is_streamed_with_read1_so_an_abandoned_worker_stops_early(self):
        module = load_module()
        response = ReadOnlyBlocksResponse([b"wheel-", b"bytes", b""])
        url = "https://files.example.invalid/pkg-1.0-py3-none-any.whl"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pkg-1.0-py3-none-any.whl"
            with mock.patch.object(module, "_open_url", return_value=response):
                module._download(url, target, 5, 5)
            self.assertEqual(target.read_bytes(), b"wheel-bytes")


@unittest.skipUnless(os.name == "posix", "the fake interpreter is a POSIX shell script")
class RealStalledChildTests(unittest.TestCase):
    def test_real_stalled_child_is_killed_and_child_output_is_redacted(self):
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
        self.assertIn("<artifact-location>", str(raised.exception))
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
        with self.assertRaises(FileExistsError):
            self.module.plan(self.options)
        self.assertEqual(list(self.root.glob("*-wheels-*")), [])
        # The other run's plan is not this call's file: it must be left untouched.
        self.assertEqual(self.plan_path.read_text(encoding="utf-8"), "concurrent")

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
        plan_path = self.plan_path

        def unlink_fails_for_plan_only(path, *args, **kwargs):
            if path == plan_path:
                raise PermissionError("locked by another process")
            return real_unlink(path, *args, **kwargs)

        with (
            mock.patch.object(
                self.module.json,
                "dump",
                side_effect=OSError("No space left on device"),
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
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError) as raised:
                module.cache_wheel(item, Path(directory), time.monotonic() - 1)
        message = str(raised.exception)
        self.assertIn("plan download deadline", message)
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


@unittest.skipUnless(hasattr(os, "kill"), "POSIX signals are required")
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


if __name__ == "__main__":
    unittest.main()

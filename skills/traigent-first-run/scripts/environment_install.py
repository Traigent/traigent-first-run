#!/usr/bin/env python3
"""Resolve and apply one bound installation plan without running target Python.

Always launch this file with a trusted Python and -I -S -B. `plan` reads target
metadata, constrains every existing version except explicit --change previews,
and caches hashed wheels. `apply` requires the SHA256 of the approved plan and
refuses environment, metadata, requirements, or wheel drift. Standard pip owns
installation and uninstallation; target code and target import paths never run.
"""

from __future__ import annotations

import argparse
import configparser
import contextlib
import csv
import email.parser
import errno
import importlib.util
import json
import ntpath
import os
import secrets
import shutil
import signal
import ssl
import stat
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

# The bounds below are stall backstops. The per-read timeout is the one that fires in
# the usual case. In the worst case one plan can take up to PIP_TIMEOUT_SECONDS +
# PLAN_DOWNLOAD_DEADLINE_SECONDS (25 minutes), which can exceed a coding assistant's own
# tool-call time limit; then the assistant's limit fires first.
DOWNLOAD_READ_TIMEOUT_SECONDS = 30  # max silence on the socket before one read fails
# Total wall time for all wheel downloads in one plan, shared across wheels, not per
# wheel. The bundled lock pins 75 wheels; at 600 s this budget fails links too slow
# to move about 100 MB in that time (100 MB * 8 / 600 s, about 1.3 Mbit/s).
PLAN_DOWNLOAD_DEADLINE_SECONDS = 600
# Max wall time for one isolated pip child: a backstop far above a normal plan or
# apply, leaving margin for slow disks or antivirus. A kill here can leave a partial
# install, which the apply error says.
PIP_TIMEOUT_SECONDS = 900
# Exit status of pip_adapter when it refuses before pip's main() runs (snapshot identity,
# unsupported pip API, wheel destination checks): nothing was changed. Pip's own codes
# are 0-4, 23 and 120, so 65 never collides with one.
PIP_REFUSED_EXIT = 65
# Largest accepted wheel body: locked wheels are tens of MB; 1 GiB leaves room for a
# large --change preview.
MAX_WHEEL_BYTES = 1024 * 1024 * 1024

SPEC = importlib.util.spec_from_file_location(
    "_first_run_environments", Path(__file__).with_name("find_environments.py")
)
ENV = importlib.util.module_from_spec(SPEC)
if SPEC.loader is None:
    raise ImportError("find_environments.py has no loader")
# This load runs at import, before `main()` can refuse a launch without `-B`,
# so it must not write `__pycache__` into the guide copy on the way (#559).
# Scoped rather than left set, so a caller that imports this file keeps its own
# setting.
_dont_write_bytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    SPEC.loader.exec_module(ENV)
finally:
    sys.dont_write_bytecode = _dont_write_bytecode


def require_isolation() -> None:
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
        raise ValueError("Use a trusted Python with -I -S -B to run this helper")


def snapshot(candidate: Path) -> dict:
    interpreter = ENV.interpreter_of(candidate)
    if interpreter is None:
        raise ValueError("Candidate is not a virtual environment")
    state = ENV.verified_environment(interpreter)
    if not ENV.supported(state["version"]):
        raise ValueError("Candidate Python is not supported (requires 3.11-3.13)")
    state["interpreter"] = str(interpreter.absolute())
    prefix = Path(state["prefix"])
    scheme = sysconfig.get_paths(
        "venv", vars={"base": str(prefix), "platbase": str(prefix)}
    )
    for key in ("purelib", "platlib", "scripts", "data"):
        if not ENV.inside(Path(scheme[key]), prefix):
            raise ValueError(f"Install scheme escapes the environment: {key}")
    # Standard pip retains its RECORD-aware uninstall behavior, but every path it
    # might delete must resolve inside this particular approved environment.
    for site in state["sites"]:
        for current, directories, filenames in os.walk(site, followlinks=False):
            for name in directories + filenames:
                path = Path(current) / name
                if path.is_symlink() and not ENV.inside(path, prefix):
                    raise ValueError(
                        "Installed package path is a symlink outside the environment"
                    )
        for metadata in Path(site).glob("*.dist-info"):
            if (
                not (metadata / "RECORD").is_file()
                or (metadata / "installed-files.txt").exists()
            ):
                raise ValueError(
                    "A modern RECORD is required; legacy installed-files.txt fallback is forbidden"
                )
        for record in Path(site).glob("*.dist-info/RECORD"):
            with record.open(newline="", encoding="utf-8") as stream:
                for row in csv.reader(stream):
                    if len(row) != 3 or not row[0]:
                        raise ValueError(
                            "Installed RECORD contains an unsafe uninstall path"
                        )
                    validate_uninstall_path(Path(site) / row[0], prefix)
        for metadata in Path(site).glob("*.dist-info"):
            if not ENV.inside(metadata, prefix):
                raise ValueError("Installed metadata resolves outside the environment")
    scripts = Path(scheme["scripts"])
    for site in state["sites"]:
        for entry_points in Path(site).glob("*.dist-info/entry_points.txt"):
            validate_entry_points(
                entry_points.read_text(encoding="utf-8"), scripts, prefix
            )
    return state


def validate_uninstall_path(path: Path, prefix: Path) -> None:
    paths = [path]
    if path.suffix == ".py":
        paths.extend(
            [
                path.with_suffix(".pyc"),
                path.with_suffix(".pyo"),
                Path(importlib.util.cache_from_source(str(path))),
            ]
        )
    for candidate in paths:
        if (
            candidate.is_dir()
            or protected_runtime_path(candidate, prefix)
            or not ENV.inside(candidate, prefix)
        ):
            raise ValueError("Installed RECORD contains an unsafe uninstall path")


def protected_runtime_path(path: Path, prefix: Path) -> bool:
    lexical = Path(os.path.abspath(path))
    protected = {prefix / "pyvenv.cfg"}
    for directory in ("bin", "Scripts"):
        protected.update(
            prefix / directory / name
            for name in (
                "python",
                "python3",
                f"python{sys.version_info.major}.{sys.version_info.minor}",
                "python.exe",
                "pythonw.exe",
                "python_d.exe",
                "pythonw_d.exe",
            )
        )
    return lexical in protected or lexical.resolve() in {
        entry.resolve() for entry in protected
    }


def validate_entry_points(text: str, scripts: Path, prefix: Path) -> None:
    entries = configparser.ConfigParser(interpolation=None)
    entries.optionxform = str
    entries.read_string(text)
    for section in ("console_scripts", "gui_scripts"):
        for name in entries[section] if entries.has_section(section) else ():
            if (
                not name
                or name in (".", "..")
                or any(c.isspace() or ord(c) < 32 for c in name)
                or "/" in name
                or "\\" in name
                or ":" in name
                or ntpath.splitdrive(name)[0]
            ):
                raise ValueError("Distribution contains an unsafe script name")
            for suffix in ("", ".exe", "-script.py", "-script.pyw", ".exe.manifest"):
                if (
                    (scripts / (name + suffix)).is_dir()
                    or protected_runtime_path(scripts / (name + suffix), prefix)
                    or not ENV.inside(scripts / (name + suffix), prefix)
                ):
                    raise ValueError(
                        "Script destination escapes the approved environment"
                    )
                validate_uninstall_path(scripts / (name + suffix), prefix)


# The one home of the saved-log advice: the disclosure contract pins it word for word.
SAVED_LOG_ADVICE = (
    "Inspect it locally if needed. Keep its contents out of chat and tool "
    "output. Delete the log when done."
)


def _save_pip_output(stdout, stderr) -> tuple[str, Path | None]:
    """Save pip's raw output where only this user can read it.

    Returns (message, directory): the message names the saved path or why the save
    failed, and directory is the created Path, or None on every failure path and once
    it has been removed. Never printed or chained: pip output can carry index or proxy
    addresses. The directory is a fresh mkdtemp in the temp dir Python's tempfile picks
    (TMPDIR/TEMP/TMP if set, else the system default), never the plan's directory
    (0700/0600 on POSIX; on Windows the per-user %TEMP% location applies), and the
    message tells the user to delete it when done. Cleanup is best effort. A failed or
    interrupted save removes its directory, and isolated_pip removes it if an interrupt
    arrives while it builds the error message. Only when an OSError ended the save and
    that removal also failed does the message name the leftover directory. An interrupt
    in the short windows outside those (at the save's return, after the error has left
    isolated_pip and before it is printed, or between mkdtemp creating the directory and
    its assignment, which leaves it empty) can leave the owner-only first-run-pip-*
    directory behind unnamed.
    """
    directory = None
    path = None
    saved = False
    failure = None
    leftover = False
    try:
        directory = Path(tempfile.mkdtemp(prefix="first-run-pip-"))
        path = directory / "pip-output.log"
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            for label, part in (
                (b"--- stdout ---\n", stdout),
                (b"\n--- stderr ---\n", stderr),
            ):
                stream.write(label)
                if part:
                    stream.write(
                        part
                        if isinstance(part, bytes)
                        else part.encode("utf-8", "replace")
                    )
        saved = True
    except OSError as error:
        failure = type(error).__name__
    finally:
        # One cleanup path for every exit: an OSError or an interrupt (Ctrl-C, or the
        # SIGTERM handler's SystemExit) removes the directory, best effort; a removal
        # error is recorded, not raised, so the original exception still propagates.
        if not saved and directory is not None:
            try:
                shutil.rmtree(directory)
            except OSError:
                # Not chained: the removal error's text may name the same paths.
                leftover = True
    if failure is not None:
        if leftover:
            return (
                f"pip's output could not be saved ({failure}); a partial copy may remain "
                f"in {directory}: delete it",
                None,
            )
        return f"pip's output could not be saved ({failure})", None
    message = f"pip's full output is saved, unredacted, in {path}. {SAVED_LOG_ADVICE}"
    return message, directory


def _signal_name(number: int) -> str:
    """Name a signal number for a message, or say the number when it has no name."""
    try:
        return signal.Signals(number).name
    except ValueError:
        return f"signal {number}"


def _watch_lifeline(descriptor: int) -> None:
    """Child side of the lifeline: SIGKILL this process once the parent's write end closes.

    The parent never writes, so read returns b"" only when every copy of its write end
    is closed: the parent exited, was killed, or finished with this child. That is a
    state, not an event, so it is seen whether the parent closed early or long before
    the watcher started. A read error is not EOF and is not treated as one: the thread
    fails with a traceback and the child keeps running, so a live parent is never killed.
    """
    os.fstat(descriptor)  # fail loudly now if the descriptor is not open

    def watch() -> None:
        while os.read(descriptor, 1):
            pass
        os.kill(os.getpid(), signal.SIGKILL)

    threading.Thread(target=watch, name="lifeline", daemon=True).start()


def _lifeline_pipe() -> tuple[int, int]:
    """os.pipe(), with both ends moved to descriptor 3 or above.

    os.pipe() takes the lowest free descriptors. When stdout or stderr is closed, an end
    lands on 1 or 2, where Popen's stdout/stderr dup2 overwrites it in the child; the child
    would then watch its own output pipe instead of the lifeline. Popen only rewrites 0-2.
    F_DUPFD_CLOEXEC with a minimum of 3 is the CPython fcntl route to a fresh descriptor at
    or above 3 that is not inherited across exec. If the second move fails, the first is
    closed, so no descriptor leaks; the original ends are closed in every case.
    """
    import fcntl  # POSIX only, as is the lifeline

    ends = os.pipe()
    moved = []
    try:
        for end in ends:
            moved.append(fcntl.fcntl(end, fcntl.F_DUPFD_CLOEXEC, 3))
        return tuple(moved)
    except BaseException:
        for descriptor in moved:
            os.close(descriptor)
        raise
    finally:
        for end in ends:
            os.close(end)


def isolated_pip(
    candidate: Path, arguments: list[str], working: Path, *, changes_environment: bool
) -> None:
    """Run this adapter in a fresh trusted child, never the candidate executable.

    Callers set changes_environment: False for the plan step's resolve-only pip run,
    which installs nothing, and True for apply, whose install may stop partway.
    """
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTHON", "PIP_", "LD_", "DYLD_"))
    }
    environment["PIP_CONFIG_FILE"] = os.devnull
    stalled = False
    started = time.monotonic()
    # Lifeline (POSIX; Windows has no pass_fds, so it is skipped there). The child holds
    # the read end and SIGKILLs itself when every copy of the write end is closed. Both
    # ends are at descriptor 3 or above (_lifeline_pipe): a lifeline on fd 0-2 would be
    # overwritten by Popen's stdio setup in the child, or would sit on a standard fd the
    # parent has closed, and the child would then watch the wrong pipe. Only this frame
    # holds the write end, and it closes it last, on every exit path: after the child is
    # reaped, or when a signal, interrupt or outer SIGKILL stops this process at any
    # point, including inside Popen, where no kill() below has run yet.
    lifeline = _lifeline_pipe() if os.name == "posix" else None
    try:
        try:
            process = subprocess.Popen(
                [
                    str(ENV.trusted_interpreter()),
                    "-I",
                    "-S",
                    "-B",
                    str(Path(__file__).resolve()),
                    "_pip",
                    "--candidate",
                    str(candidate),
                    *(["--lifeline", str(lifeline[0])] if lifeline else []),
                    "--",
                    *arguments,
                ],
                cwd=working,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(lifeline[0],) if lifeline else (),
            )
        finally:
            if lifeline is not None:
                os.close(lifeline[0])  # the child has its own copy; we never read it
        try:
            try:
                stdout, stderr = process.communicate(timeout=PIP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                # Record the stall and nothing else. The kill and the collect below run
                # after this handler has finished, so an interrupt during them is raised
                # with no exception being handled and does not take TimeoutExpired as
                # its __context__.
                stalled = True
            if stalled:
                # The bound is ours to enforce now: kill, then collect what the pipes hold.
                process.kill()
                stdout, stderr = process.communicate()
        except BaseException:
            # A signal or interrupt while pip runs, or during the kill and collect above:
            # stop the child before it propagates.
            process.kill()
            process.wait()
            raise
    finally:
        if lifeline is not None:
            os.close(lifeline[1])
    elapsed = round(time.monotonic() - started)
    if not stalled and process.returncode == 0:
        return
    # Nothing below runs while the TimeoutExpired of the bounded wait is being handled, so
    # no raise here chains it. Its text is the command line and its .output and
    # .stderr hold pip's raw bytes; neither reaches a message. One residual window is
    # inside CPython: a signal handled within communicate() while TimeoutExpired is still
    # unwinding out of it (microseconds) can still carry it as __context__. An interrupt
    # while the message is built removes the saved log before it propagates (best effort:
    # see _save_pip_output).
    directory = None
    try:
        saved, directory = _save_pip_output(stdout, stderr)
        if stalled:
            if changes_environment:
                message = (
                    f"Installer stalled: pip exceeded the {PIP_TIMEOUT_SECONDS}-second "
                    f"bound during apply (stopped after {elapsed}s); the environment may "
                    "be partly changed. Stop and inspect it before any further change. "
                    + saved
                )
            else:
                message = (
                    f"Installer stalled: pip exceeded the {PIP_TIMEOUT_SECONDS}-second "
                    f"bound (stopped after {elapsed}s); nothing was installed or changed. "
                    "The network or dependency resolution stalled. " + saved
                )
        elif process.returncode < 0:
            # A negative code is the signal that killed pip (e.g. -9, the OOM killer).
            # pip writes nothing when killed, so name the signal rather than an exit code.
            name = _signal_name(-process.returncode)
            if changes_environment:
                message = (
                    f"Isolated pip was killed by {name} during apply after {elapsed}s; "
                    "the environment may be partly changed. Stop and inspect it before "
                    "any further change. " + saved
                )
            else:
                message = (
                    f"Isolated pip was killed by {name} after {elapsed}s; nothing was "
                    "installed or changed. " + saved
                )
        elif process.returncode == PIP_REFUSED_EXIT:
            message = (
                "Isolated pip refused the install before changing anything (exit code "
                f"{PIP_REFUSED_EXIT}) after {elapsed}s; nothing was installed or changed. "
                + saved
            )
        elif changes_environment:
            # pip rolls back only the wheel that failed; earlier wheels may be installed.
            message = (
                f"Isolated pip failed with exit code {process.returncode} during apply "
                f"after {elapsed}s; the environment may be partly changed. Stop and "
                "inspect it before any further change. " + saved
            )
        else:
            message = (
                f"Isolated pip failed with exit code {process.returncode} after {elapsed}s; "
                "nothing was installed or changed. " + saved
            )
        raise ValueError(message)
    except (KeyboardInterrupt, SystemExit):
        if directory is not None:
            with contextlib.suppress(OSError):
                shutil.rmtree(directory)
        raise


def validate_wheel_paths(wheel: Path, prefix: Path, get_scheme) -> None:
    """Validate standard wheel destinations before pip can uninstall anything."""
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Wheel contains duplicate archive paths")
        metadata_names = [
            name
            for name in names
            if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ValueError("Wheel has ambiguous distribution metadata")
        metadata = email.parser.Parser().parsestr(
            archive.read(metadata_names[0]).decode("utf-8")
        )
        name = ENV.canonical_name(metadata["Name"])
        ENV.version_tuple(metadata["Version"])
        scheme = get_scheme(name, prefix=str(prefix))
        wheel_metadata = metadata_names[0].rsplit("/", 1)[0] + "/WHEEL"
        wheel_info = email.parser.Parser().parsestr(
            archive.read(wheel_metadata).decode("utf-8")
        )
        default = Path(
            scheme.purelib
            if wheel_info["Root-Is-Purelib"] == "true"
            else scheme.platlib
        )
        for member in names:
            parts = Path(member).parts
            if (
                not parts
                or member.startswith("/")
                or "\\" in member
                or ntpath.splitdrive(member)[0]
                or any(part in (".", "..") for part in member.split("/"))
            ):
                raise ValueError("Wheel contains an unsafe archive path")
            if parts[0].endswith(".data"):
                if len(parts) < 3:
                    if member.endswith("/"):
                        continue
                    raise ValueError("Wheel contains an invalid data path")
                if parts[1] not in ("purelib", "platlib", "scripts", "data", "headers"):
                    raise ValueError("Wheel contains an unknown install scheme")
                destination = Path(getattr(scheme, parts[1])).joinpath(*parts[2:])
            else:
                destination = default.joinpath(*parts)
            if protected_runtime_path(destination, prefix) or not ENV.inside(
                destination, prefix
            ):
                raise ValueError("Wheel destination escapes the approved environment")
        entry_file = metadata_names[0].rsplit("/", 1)[0] + "/entry_points.txt"
        if entry_file in names:
            validate_entry_points(
                archive.read(entry_file).decode("utf-8"), Path(scheme.scripts), prefix
            )


def pip_adapter(candidate: Path, arguments: list[str]) -> int:
    """Narrow adapter around the pip bundled with the trusted runtime.

    Patch metadata lookup before importing pip's installer consumers. Prefix and
    executable select the candidate's installation scheme and script shebangs;
    sys.path contains only trusted stdlib plus the trusted pip wheel. No customer
    module, site startup hook, backend or interpreter subprocess is permitted.
    """
    try:
        state = snapshot(candidate)
        sys.path.insert(0, str(ENV.trusted_pip_wheel()))
        sys.prefix = sys.exec_prefix = state["prefix"]
        sys.executable = state["interpreter"]
        import pip
        from pip._internal import metadata

        metadata.get_default_environment = lambda: metadata.get_environment(
            state["sites"]
        )
        from pip._internal.exceptions import InstallationError
        from pip._internal.network import session
        from pip._internal.operations.prepare import RequirementPreparer

        if not callable(getattr(metadata, "get_environment", None)) or not callable(
            getattr(RequirementPreparer, "prepare_linked_requirement", None)
        ):
            raise ValueError(
                "Unsupported bundled pip metadata/preparer API; choose another trusted Python"
            )
        session.user_agent = lambda: "pip/" + pip.__version__ + " first-run-isolated"
        original_prepare = RequirementPreparer.prepare_linked_requirement

        def wheel_only(self, requirement, *args, **kwargs):
            if requirement.link is None or not requirement.link.is_wheel:
                raise InstallationError(
                    "Only wheel artifacts may be resolved or installed"
                )
            return original_prepare(self, requirement, *args, **kwargs)

        def no_subprocess(*args, **kwargs):
            raise RuntimeError("Package build/interpreter subprocesses are forbidden")

        RequirementPreparer.prepare_linked_requirement = wheel_only
        subprocess.Popen = no_subprocess
        from pip._internal.cli.main import main
        from pip._internal.locations import get_scheme

        if "--dry-run" not in arguments:
            for argument in arguments:
                artifact = Path(argument)
                if argument.endswith(".whl") and artifact.is_file():
                    validate_wheel_paths(artifact, Path(state["prefix"]), get_scheme)
    except Exception as error:
        # Everything in this try only reads: the snapshot, the imports, the API checks and
        # wheel path validation (configparser, zipfile and KeyError refusals included).
        # "Before pip's main() runs" is what makes "nothing was changed" true, not the
        # exception type, so every failure here exits as a refusal.
        # Child stderr only: the parent saves it to the log and never prints it.
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return PIP_REFUSED_EXIT
    return main(["--isolated", "--disable-pip-version-check", "--no-input", *arguments])


def exact_change(value: str) -> tuple[str, str]:
    name, separator, version = value.partition("==")
    if not separator:
        raise ValueError("--change must be an exact NAME==VERSION preview")
    name = ENV.canonical_name(name)
    ENV.version_tuple(version)
    return name, version


class _HttpsDowngradeRefused(Exception):
    """Raised inside the transfer when https redirects to a non-https URL."""


class _WheelTooLarge(Exception):
    """Raised inside the transfer when a wheel body exceeds MAX_WHEEL_BYTES."""


class _WheelTruncated(Exception):
    """Raised inside the transfer when the body ends before the declared Content-Length."""


class _NoDowngradeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follows redirects except an https-to-non-https one, which is refused."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if (
            urllib.parse.urlsplit(req.full_url).scheme == "https"
            and urllib.parse.urlsplit(newurl).scheme != "https"
        ):
            raise _HttpsDowngradeRefused()
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_NoDowngradeRedirectHandler)


def _open_url(url: str, timeout: float):
    return _OPENER.open(url, timeout=timeout)


def _download(url: str, target: Path, read_timeout: float, deadline: float) -> None:
    """Stream url into a new target file within deadline seconds of total wall time.

    The deadline covers the whole operation: name lookup, connect, redirects,
    headers and body. getaddrinfo ignores socket timeouts and a server can drip
    headers forever, so the transfer runs in a daemon thread that the caller joins
    with the deadline. read_timeout bounds each socket read inside that thread.

    The body is capped at MAX_WHEEL_BYTES whatever Content-Length says, and an
    https URL may not redirect to a non-https one. Each failure raises a ValueError
    that names the error type and status only, with no chained exception, and removes
    the partial file; a removal that fails is ignored so the error still names the
    cause. On
    timeout the worker is abandoned. A worker stuck inside a call that ignores
    timeouts (such as DNS) is left running on purpose: it is a daemon, the caller
    closes its stream when it abandons it so it writes nothing once abandoned, and
    the caller reports the stall and the script exits.
    An interrupt closes the stream and removes the partial file before re-raising.
    """
    deadline_message = (
        "Wheel download did not finish: the plan download deadline "
        f"({PLAN_DOWNLOAD_DEADLINE_SECONDS}s for all wheels) ran out, so the network "
        "is too slow or stalled; nothing was installed or changed."
    )
    read_message = (
        "Wheel download stalled: no response for "
        f"{read_timeout:g}s (could not connect, or the server stopped sending); "
        "nothing was installed or changed."
    )
    size_message = (
        f"Wheel download exceeded the {MAX_WHEEL_BYTES // (1024 * 1024)} MiB size limit; "
        "nothing was installed or changed."
    )
    truncated_message = (
        "Wheel download was cut short: the server sent fewer bytes than it declared; "
        "nothing was installed or changed."
    )
    redirect_message = (
        "Wheel download refused a redirect from HTTPS to a non-HTTPS URL; "
        "nothing was installed or changed."
    )
    # Opened before the worker starts: a FileExistsError must not unlink a file this
    # call did not create.
    stream = target.open("xb")
    failures: list[BaseException] = []

    def transfer() -> None:
        try:
            with _open_url(url, read_timeout) as response:
                # The length comes from http.client itself, read before the body, so
                # the two can never disagree: it is None for chunked or absent framing
                # and 0 for a 204, 304 or HEAD response. Non-HTTP responses have none.
                declared = getattr(response, "length", None)
                if declared is not None and declared > MAX_WHEEL_BYTES:
                    raise _WheelTooLarge()
                received = 0
                # read1 returns after one socket read, so an abandoned transfer stops
                # at the next block instead of draining the whole body.
                while block := response.read1(1024 * 1024):
                    received += len(block)
                    if received > MAX_WHEEL_BYTES:
                        raise _WheelTooLarge()
                    stream.write(block)
                # A server that closes early would otherwise look like a complete
                # wheel; the caller then blames the hash check.
                if declared is not None and received < declared:
                    raise _WheelTruncated()
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=transfer, name="wheel-download", daemon=True)
    worker.start()
    try:
        worker.join(deadline)
    except BaseException:
        # Interrupted: release the file so a caller's cleanup can remove it (Windows
        # refuses to remove open files). Cleanup errors must not mask the interrupt.
        with contextlib.suppress(OSError):
            stream.close()
        with contextlib.suppress(OSError):
            target.unlink(missing_ok=True)
        raise
    if worker.is_alive():
        # A failing close must not replace the deadline message or skip the removal.
        with contextlib.suppress(OSError):
            stream.close()
        with contextlib.suppress(OSError):
            target.unlink(missing_ok=True)
        raise ValueError(deadline_message)
    try:
        # The final flush can fail (full disk, EIO): report it as the labelled failure
        # below, after the partial file is removed, not as a raw OSError.
        stream.close()
    except OSError as error:
        failures.append(error)
    if not failures:
        return
    # As on the deadline path: a locked partial file must not replace the labelled error.
    with contextlib.suppress(OSError):
        target.unlink(missing_ok=True)
    error = failures[0]
    if isinstance(error, _WheelTooLarge):
        raise ValueError(size_message) from None
    if isinstance(error, _WheelTruncated):
        raise ValueError(truncated_message) from None
    if isinstance(error, _HttpsDowngradeRefused):
        raise ValueError(redirect_message) from None
    timed_out = isinstance(error, TimeoutError) or (
        isinstance(error, urllib.error.URLError)
        and isinstance(error.reason, TimeoutError)
    )
    if timed_out:
        raise ValueError(read_message) from None
    detail = type(error).__name__
    if isinstance(error, urllib.error.HTTPError):
        detail += f" (HTTP {error.code})"
    elif isinstance(error, urllib.error.URLError):
        # A string reason is text, not an exception: naming its type would name "str".
        if isinstance(error.reason, BaseException):
            detail += f" ({type(error.reason).__name__})"
    elif (
        isinstance(error, OSError)
        and not isinstance(error, ssl.SSLError)
        and error.errno in errno.errorcode
    ):
        # A local write failure (e.g. a full disk): the errno name is fixed text.
        # TLS errors are excluded: their errno is an OpenSSL code, not an OS one.
        detail += f" ({errno.errorcode[error.errno]})"
    raise ValueError(
        f"Wheel download failed: {detail}; nothing was installed or changed."
    ) from None


def cache_wheel(item: dict, directory: Path, download_deadline: float) -> dict:
    """Cache one wheel; download_deadline is an absolute time.monotonic() value
    shared by every wheel in the plan."""
    download = item["download_info"]
    url = download["url"]
    parsed = urllib.parse.urlsplit(url)
    filename = Path(urllib.parse.unquote(parsed.path)).name
    if parsed.scheme not in ("https", "file") or not filename.endswith(".whl"):
        raise ValueError("Resolver did not select an HTTPS or local wheel")
    expected = download.get("archive_info", {}).get("hashes", {}).get("sha256", "")
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("Resolved wheel has no valid SHA256")
    target = directory / filename
    if target.exists():
        raise ValueError("Ambiguous resolved wheel filenames")
    remaining = download_deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError(
            "Wheel download did not finish: the plan download deadline "
            f"({PLAN_DOWNLOAD_DEADLINE_SECONDS}s for all wheels) ran out before every "
            "wheel was downloaded, so the network is too slow or stalled; nothing was "
            "installed or changed."
        )
    # Pip already fetched/hashed these artifacts during resolution. Recheck the
    # bytes cached for apply; never trust a URL to remain the same after yes.
    _download(url, target, DOWNLOAD_READ_TIMEOUT_SECONDS, remaining)
    if ENV.file_digest(target) != expected:
        raise ValueError("Resolved wheel changed before it could be cached")
    return {
        "path": str(target),
        "sha256": expected,
        "name": ENV.canonical_name(item["metadata"]["name"]),
        "version": item["metadata"]["version"],
    }


def _is_same_file(path: Path, staged: Path) -> bool:
    """True when `path` is this call's plan: the hard link to `staged`, or, where
    hard links are refused, a byte-identical copy. Contents are unique per call,
    because the plan document names the call's random cache directory, even when
    nothing is installed and no artifact path embeds it. Any entry that
    is not a regular file, or cannot be read, is treated as not this call's and is
    left alone without being reported. The compared bytes come from the very entry
    that was checked, read once through one descriptor and bounded by the staged size.
    """
    try:
        entry = os.lstat(path)
        ours = os.stat(staged)
    except OSError:
        return False
    # Symlink, FIFO, directory, or device: never ours. This is defence in depth: the size
    # check, the O_NOFOLLOW/O_NONBLOCK open, and the fstat S_ISREG check below also refuse
    # these, because a staged plan is never empty.
    if not stat.S_ISREG(entry.st_mode):
        return False
    if os.path.samestat(entry, ours):  # the hard link this call published
        return True
    # Copy fallback: only an equal-size regular file can be this call's copy.
    if entry.st_size != ours.st_size:
        return False
    # Re-open with no-follow and non-blocking flags, then verify the descriptor is the
    # entry checked above. A FIFO, symlink, or other file swapped in after the lstat is
    # refused here and never read: the samestat check pins the opened file to the entry.
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
    )
    try:
        fd = os.open(path, flags)
    except OSError:
        return False
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(opened, entry):
            return False
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(ours.st_size + 1)
        return data == staged.read_bytes()
    except OSError:
        return False
    finally:
        os.close(fd)


PLAN_EXISTS_MESSAGE = "Plan already exists; choose a fresh plan path"


def _publish_plan(staged: Path, plan_path: Path) -> None:
    """Expose the complete staged plan at plan_path without replacing another run's.

    os.link is an atomic exclusive create of a finished file, so plan_path never holds
    a partial plan, and FileExistsError leaves another run's plan untouched. Where the
    filesystem refuses hard links (FAT/exFAT, some network and sync folders), fall
    back to an exclusive copy. That fallback has one residual window: a signal between
    creating plan_path and recording that it was created can leave an empty file.
    A lost race raises PLAN_EXISTS_MESSAGE, not the raw errno: the raw text names a
    cache directory that cleanup has already removed.
    """
    try:
        os.link(staged, plan_path)
        return
    except FileExistsError:
        raise ValueError(PLAN_EXISTS_MESSAGE) from None
    except OSError:
        pass
    data = staged.read_bytes()
    created = False
    try:
        with plan_path.open("xb") as stream:
            created = True
            stream.write(data)
    except FileExistsError:
        raise ValueError(PLAN_EXISTS_MESSAGE) from None
    except BaseException:
        if created:
            plan_path.unlink(missing_ok=True)
        raise


def plan(options) -> dict:
    candidate = options.candidate.resolve()
    before = snapshot(candidate)
    pins = ENV.read_pins(options.requirements)
    changes = {}
    for value in options.change:
        name, version = exact_change(value)
        if name in changes or name not in before["installed"]:
            raise ValueError("--change must name one existing distribution once")
        changes[name] = version
    wanted = {
        name: version
        for name, version in pins.items()
        if name not in before["installed"]
    }
    wanted.update(changes)
    plan_path = options.plan.absolute()
    if plan_path.exists():
        raise ValueError(PLAN_EXISTS_MESSAGE)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="first-run-resolve-") as temporary:
        working = Path(temporary)
        constraints = working / "constraints.txt"
        constraints.write_text(
            "".join(
                f"{name}=={version}\n"
                for name, version in sorted(before["installed"].items())
                if name not in changes
            )
        )
        report_path = working / "report.json"
        report = {"install": []}
        if wanted:
            arguments = [
                "install",
                "--dry-run",
                "--only-binary=:all:",
                "--no-compile",
                "--report",
                str(report_path),
                "--constraint",
                str(constraints),
                "--prefix",
                str(candidate),
            ]
            if options.no_index:
                arguments.append("--no-index")
            if options.find_links is not None:
                arguments.extend(["--find-links", str(options.find_links.resolve())])
            arguments.extend(
                f"{name}=={version}" for name, version in sorted(wanted.items())
            )
            isolated_pip(candidate, arguments, working, changes_environment=False)
            report = json.loads(report_path.read_text(encoding="utf-8"))
        card = ENV.approval_card(report, before["installed"])
        for item in report["install"]:
            name = ENV.canonical_name(item["metadata"]["name"])
            version = item["metadata"]["version"]
            if name in before["installed"] and (
                name not in changes
                or ENV.version_tuple(version) != ENV.version_tuple(changes[name])
            ):
                raise ValueError(
                    f"Resolver would replace preserved package {name}; consider an explicit --change preview or choose another environment"
                )
        if snapshot(candidate)["identity"] != before["identity"]:
            raise ValueError(
                "Environment changed during resolution; create a fresh plan"
            )
    # Ownership by construction: the cache's name is chosen here, before anything
    # exists, and the plan is staged inside the cache and only then linked to
    # plan_path. Cleanup can therefore always name what this call may have created,
    # whatever raised the exception and wherever it landed. The only residuals are a
    # 2**-128 name collision with a signal between os.mkdir raising and `cache = None`,
    # the copy fallback in _publish_plan, and an interrupt (Ctrl-C or the SIGTERM
    # handler's SystemExit) during the cache cleanup, or a cleanup removal that fails
    # under an interrupt: either can leave a `<plan>-wheels-<hex>` directory behind
    # without naming it in the error.
    cache = plan_path.parent / f"{plan_path.stem}-wheels-{secrets.token_hex(16)}"
    staged = cache / ".plan.json"
    try:
        try:
            os.mkdir(cache, 0o700)
        except OSError:
            cache = None  # not ours: a name collision, or mkdir itself failed
            raise
        download_deadline = time.monotonic() + PLAN_DOWNLOAD_DEADLINE_SECONDS
        artifacts = [
            cache_wheel(item, cache, download_deadline) for item in report["install"]
        ]
        document = {
            "schema": 1,
            "cache": str(cache),
            "candidate": str(candidate),
            "identity": before["identity"],
            "requirements": str(options.requirements.resolve()),
            "requirements_sha256": ENV.file_digest(options.requirements),
            "new": card["new"],
            "changes": card["changes"],
            "artifacts": artifacts,
        }
        with staged.open("x", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
        _publish_plan(staged, plan_path)
        result = {
            "plan": str(plan_path),
            "plan_sha256": ENV.file_digest(plan_path),
            **card,
        }
    except BaseException as error:
        # Any failure after the cache exists must leave no cache behind, since each
        # retry would add one. A plan file is removed only when it is this call's
        # (_is_same_file), so another run's plan is never unlinked; a partial plan
        # cannot appear at plan_path, because it is published only once complete. The
        # plan is checked before the cache is removed, because the staged link lives in
        # the cache. Each removal is attempted even if the other fails, so one locked
        # path never leaves the other behind or hides the original error.
        left_behind = []
        if cache is not None:
            try:
                if _is_same_file(plan_path, staged):
                    plan_path.unlink(missing_ok=True)
            except OSError:
                left_behind.append(str(plan_path))
            try:
                shutil.rmtree(cache)
            except FileNotFoundError:
                pass  # interrupted before os.mkdir created the cache
            except OSError:
                left_behind.append(str(cache))
        if left_behind and isinstance(error, Exception):
            raise ValueError(
                f"{str(error).rstrip('.')}. Could not remove: "
                f"{', '.join(left_behind)}; delete by hand."
            ) from None
        raise
    return result


APPLY_STOPPED_MESSAGE = (
    "Installer stopped by an interrupt during apply; the environment may be partly "
    "changed. Stop and inspect it before any further change."
)


def apply(options) -> dict:
    if ENV.file_digest(options.plan) != options.approved_plan_sha256:
        raise ValueError("Plan differs from the approved SHA256")
    document = json.loads(options.plan.read_text(encoding="utf-8"))
    if document["schema"] != 1:
        raise ValueError("Unsupported installation plan schema")
    candidate = Path(document["candidate"])
    before = snapshot(candidate)
    if before["identity"] != document["identity"]:
        raise ValueError(
            "Environment changed after the plan; resolve and approve a fresh plan"
        )
    if (
        ENV.file_digest(Path(document["requirements"]))
        != document["requirements_sha256"]
    ):
        raise ValueError("Requirements changed after the plan")
    for artifact in document["artifacts"]:
        if ENV.file_digest(Path(artifact["path"])) != artifact["sha256"]:
            raise ValueError("Cached wheel differs from the approved SHA256")
    # pip may change the environment from the moment it starts until this function has
    # verified the result, so an interrupt anywhere in that span (during pip, while its
    # log is saved, or during the post-install snapshot) says the environment may be
    # partly changed. An interrupt before pip starts touched nothing and stays silent.
    pip_started = False
    try:
        if document["artifacts"]:
            with tempfile.TemporaryDirectory(prefix="first-run-install-") as temporary:
                pip_started = True
                isolated_pip(
                    candidate,
                    [
                        "install",
                        "--no-index",
                        "--only-binary=:all:",
                        "--no-deps",
                        "--no-compile",
                        "--prefix",
                        str(candidate),
                        *[item["path"] for item in document["artifacts"]],
                    ],
                    Path(temporary),
                    changes_environment=True,
                )
        after = snapshot(candidate)
        expected = dict(before["installed"])
        expected.update(
            {item["name"]: item["version"] for item in document["artifacts"]}
        )
        if after["installed"] != expected:
            raise ValueError(
                "Installed metadata differs from the approved plan; stop and inspect the environment"
            )
    except (KeyboardInterrupt, SystemExit):
        # sys.stderr is None when fd 2 was closed at startup: skip the warning, because
        # the print fallback below would write it to stdout, which carries the JSON result.
        if pip_started and sys.stderr is not None:
            # Best effort, as in _download: a dead stderr must not replace the interrupt.
            # Written unbuffered: a buffered print on a dead stderr fails again at
            # shutdown and turns the exit status into 120.
            line = (json.dumps({"error": APPLY_STOPPED_MESSAGE}) + "\n").encode("utf-8")
            # ValueError covers a closed stream, which a plain OSError suppress misses.
            with contextlib.suppress(OSError, ValueError):
                try:
                    descriptor = sys.stderr.fileno()
                except (AttributeError, ValueError, OSError):
                    # No real descriptor (a replaced stream such as StringIO).
                    print(json.dumps({"error": APPLY_STOPPED_MESSAGE}), file=sys.stderr)
                else:
                    os.write(descriptor, line)
        raise
    return {
        "status": "installed" if document["artifacts"] else "already-satisfied",
        "candidate": str(candidate),
        "installed": after["installed"],
    }


def _run_handling_termination(command, options) -> dict:
    """Run command(options) so SIGTERM/SIGHUP unwind through its own cleanup.

    Without a Python handler the default action ends the process with no exception,
    so no BaseException cleanup runs: plan() would leave its partial `-wheels` cache
    behind, and apply() would print no interrupt warning. Raising SystemExit(128 + signum)
    unwinds exactly like Ctrl-C: plan() removes its cache, apply() prints its warning when
    pip had started, and the process exits with the conventional status 128 + signum
    (143 for SIGTERM, 129 for SIGHUP). Handlers can only be set from the main thread.

    A signal whose disposition is already SIG_IGN is left alone: `nohup` starts the
    process with SIGHUP ignored, and that choice must survive the command.

    Pip child lifetime: on POSIX the pip child kills itself once the write end of its
    lifeline closes. isolated_pip closes that end only after the child is reaped, or on
    any exit from isolated_pip, so a signal, an interrupt or an outer SIGKILL at any
    point leaves no pip running. Windows has no lifeline (no pass_fds): there, a signal
    raised inside subprocess.Popen, before isolated_pip's kill-on-exception block is
    active, can still leave the child running.
    """
    if threading.current_thread() is not threading.main_thread():
        return command(options)

    def terminate(signum, frame):
        raise SystemExit(128 + signum)

    signums = [signal.SIGTERM, getattr(signal, "SIGHUP", None)]
    previous = {}
    try:
        for signum in filter(None, signums):
            if signal.getsignal(signum) is signal.SIG_IGN:
                continue
            previous[signum] = signal.signal(signum, terminate)
        return command(options)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("plan")
    preview.add_argument("--candidate", required=True, type=Path)
    preview.add_argument("--requirements", required=True, type=Path)
    preview.add_argument("--plan", required=True, type=Path)
    preview.add_argument("--change", action="append", default=[])
    preview.add_argument("--no-index", action="store_true")
    preview.add_argument("--find-links", type=Path)
    install = commands.add_parser("apply")
    install.add_argument("--plan", required=True, type=Path)
    install.add_argument("--approved-plan-sha256", required=True)
    internal = commands.add_parser("_pip", help=argparse.SUPPRESS)
    internal.add_argument("--candidate", required=True, type=Path)
    internal.add_argument("--lifeline", type=int)
    internal.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    try:
        require_isolation()
        if options.command == "_pip":
            if options.lifeline is not None:
                _watch_lifeline(options.lifeline)
            arguments = options.arguments
            return pip_adapter(
                options.candidate,
                arguments[1:] if arguments[:1] == ["--"] else arguments,
            )
        if options.command == "plan":
            result = _run_handling_termination(plan, options)
        else:
            result = _run_handling_termination(apply, options)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

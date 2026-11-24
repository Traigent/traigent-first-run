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
import importlib.util
import json
import ntpath
import os
import secrets
import shutil
import signal
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


def _save_pip_output(stdout, stderr) -> str:
    """Save pip's raw output where only this user can read it; return the path or why not.

    Never printed or chained: pip output can carry index or proxy addresses. The
    directory is a fresh mkdtemp under the system temp dir (0700 on POSIX; on Windows
    the per-user %TEMP% ACL applies), never the plan's directory, which may sit inside
    the customer's project and be committed.
    """
    try:
        directory = Path(tempfile.mkdtemp(prefix="traigent-first-run-pip-"))
        path = directory / "pip-output.log"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
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
    except OSError as error:
        return f"pip's output could not be saved ({type(error).__name__})"
    return (
        f"pip's full output is saved, unredacted, in {path} (readable only by you). "
        "Read it for the cause and quote only the lines that show it: it can contain "
        "index or proxy addresses. Delete it when done."
    )


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
    saved = ""
    started = time.monotonic()
    try:
        result = subprocess.run(
            [
                str(ENV.trusted_interpreter()),
                "-I",
                "-S",
                "-B",
                str(Path(__file__).resolve()),
                "_pip",
                "--candidate",
                str(candidate),
                "--",
                *arguments,
            ],
            cwd=working,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=PIP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as expired:
        saved = _save_pip_output(expired.stdout, expired.stderr)
        stalled = True
    elapsed = round(time.monotonic() - started)
    # The raises sit outside the except so no __context__ holds TimeoutExpired, whose
    # output can carry index credentials.
    if stalled:
        if changes_environment:
            raise ValueError(
                f"Installer stalled: pip exceeded the {PIP_TIMEOUT_SECONDS}-second bound "
                f"during apply (stopped after {elapsed}s); the environment may be partly "
                "changed. Stop and inspect it before any further change. " + saved
            )
        raise ValueError(
            f"Installer stalled: pip exceeded the {PIP_TIMEOUT_SECONDS}-second bound "
            f"(stopped after {elapsed}s); nothing was installed or changed. The network "
            "or dependency resolution stalled. " + saved
        )
    if result.returncode:
        saved = _save_pip_output(result.stdout, result.stderr)
        raise ValueError(
            f"Isolated pip failed with exit code {result.returncode} after {elapsed}s; "
            "inspect the target before retrying. " + saved
        )


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
    state = snapshot(candidate)
    sys.path.insert(0, str(ENV.trusted_pip_wheel()))
    sys.prefix = sys.exec_prefix = state["prefix"]
    sys.executable = state["interpreter"]
    import pip
    from pip._internal import metadata

    metadata.get_default_environment = lambda: metadata.get_environment(state["sites"])
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
            raise InstallationError("Only wheel artifacts may be resolved or installed")
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


def _declared_length(value: str | None) -> int | None:
    """Return Content-Length as an int, or None when absent or not a plain decimal.

    Proxies can send values such as "11, 11". The header is advisory here: the
    streamed byte count enforces MAX_WHEEL_BYTES regardless, so a malformed value is
    ignored instead of failing a valid download. Its text is never echoed.
    """
    if value is None:
        return None
    text = value.strip()
    return int(text) if text.isascii() and text.isdigit() else None


def _download(url: str, target: Path, read_timeout: float, deadline: float) -> None:
    """Stream url into a new target file within deadline seconds of total wall time.

    The deadline covers the whole operation: name lookup, connect, redirects,
    headers and body. getaddrinfo ignores socket timeouts and a server can drip
    headers forever, so the transfer runs in a daemon thread that the caller joins
    with the deadline. read_timeout bounds each socket read inside that thread.

    The body is capped at MAX_WHEEL_BYTES whatever Content-Length says, and an
    https URL may not redirect to a non-https one. Each failure raises a ValueError
    that names the error type and status only, with no chained exception, and removes
    the partial file. On
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
        "Wheel download stalled: the server sent nothing for "
        f"{read_timeout:g}s; nothing was installed or changed."
    )
    size_message = (
        f"Wheel download exceeded the {MAX_WHEEL_BYTES // (1024 * 1024)} MiB size limit; "
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
                headers = getattr(response, "headers", None)
                declared = _declared_length(
                    headers.get("Content-Length") if headers is not None else None
                )
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
        stream.close()
        target.unlink(missing_ok=True)
        raise ValueError(deadline_message)
    stream.close()
    if not failures:
        return
    target.unlink(missing_ok=True)
    error = failures[0]
    if isinstance(error, _WheelTooLarge):
        raise ValueError(size_message) from None
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
        detail += f" ({type(error.reason).__name__})"
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
    if not stat.S_ISREG(entry.st_mode):  # symlink, FIFO, directory, device: never ours
        return False
    if os.path.samestat(entry, ours):  # the hard link this call published
        return True
    # Copy fallback: only an equal-size regular file can be this call's copy.
    if entry.st_size != ours.st_size:
        return False
    # Re-open with no-follow and non-blocking flags, then verify the descriptor is the
    # entry checked above. A FIFO or symlink swapped in after the lstat is refused here
    # and never read.
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
    # and the copy fallback in _publish_plan.
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
    if document["artifacts"]:
        with tempfile.TemporaryDirectory(prefix="first-run-install-") as temporary:
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
    expected.update({item["name"]: item["version"] for item in document["artifacts"]})
    if after["installed"] != expected:
        raise ValueError(
            "Installed metadata differs from the approved plan; stop and inspect the environment"
        )
    return {
        "status": "installed" if document["artifacts"] else "already-satisfied",
        "candidate": str(candidate),
        "installed": after["installed"],
    }


def _run_plan_handling_termination(options) -> dict:
    """Run plan() so SIGTERM/SIGHUP unwind through its cleanup of the wheel cache.

    Without a Python handler the default action ends the process with no exception,
    so plan()'s BaseException cleanup never runs and partial wheels stay behind.
    Raising SystemExit(128 + signum) unwinds exactly like Ctrl-C and keeps the
    conventional exit status. Handlers can only be set from the main thread.

    A signal whose disposition is already SIG_IGN is left alone: `nohup` starts the
    process with SIGHUP ignored, and that choice must survive the plan.
    """
    if threading.current_thread() is not threading.main_thread():
        return plan(options)

    def terminate(signum, frame):
        raise SystemExit(128 + signum)

    signums = [signal.SIGTERM, getattr(signal, "SIGHUP", None)]
    previous = {}
    try:
        for signum in filter(None, signums):
            if signal.getsignal(signum) is signal.SIG_IGN:
                continue
            previous[signum] = signal.signal(signum, terminate)
        return plan(options)
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
    internal.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    try:
        require_isolation()
        if options.command == "_pip":
            arguments = options.arguments
            return pip_adapter(
                options.candidate,
                arguments[1:] if arguments[:1] == ["--"] else arguments,
            )
        if options.command == "plan":
            result = _run_plan_handling_termination(options)
        else:
            result = apply(options)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

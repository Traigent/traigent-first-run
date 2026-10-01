#!/usr/bin/env python3
"""Find a trusted, supported Python 3.11-3.13 and print its real path as JSON.

POSIX only. On Windows list installed interpreters by hand with `py -0p` and probe
those paths as `references/run-safety.md` describes; this helper reports that and exits.

Run it with any Python 3: `python3 -I -S -B find_python.py [--project-root DIR]`.
Order: `python3`, `python3.13`, `python3.12`, `python3.11` on PATH first. Only when
none qualifies is `uv python find --offline --no-python-downloads` tried, and only
a `uv` found outside the project. Nothing is installed or downloaded.

Trust rules. A candidate (interpreter or uv) is skipped when it lies inside
`--project-root` either by its own path or after every symlink is resolved, or when it
is a version-manager shim (pyenv and similar), whose answer depends on the project's
own version file. Every launch runs from a neutral directory with a minimal
environment, so no `TRAIGENT_*` value or provider key reaches it. Each interpreter is
probed with `-I -S -B -c`; its answer must be well formed and name a supported
version. The printed path is the interpreter's own base executable with every symlink
resolved, because an environment created through a symlinked interpreter is refused by
`environment_install.py`.

Exit 0 prints {"python": <real path>, "version": <x.y.z>, "via": <how found>}.
Exit 1 prints {"error": <one remedy>, "tried": [...]}.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NAMES = ("python3", "python3.13", "python3.12", "python3.11")
UV_SPEC = ">=3.11,<3.14"
PROBE = (
    "import sys, json; v = sys.version_info[:3]; "
    "print(json.dumps({'ok': (3, 11) <= v[:2] < (3, 14), "
    "'executable': getattr(sys, '_base_executable', sys.executable), "
    "'version': '%d.%d.%d' % v}))"
)
TIMEOUT_SECONDS = 20
REMEDY = (
    "No supported Python 3.11-3.13 was found. Install Python 3.13 locally, then give "
    "its executable path to resume."
)


KEPT_ENVIRONMENT = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "XDG_CONFIG_HOME",
    "UV_CACHE_DIR",
    "UV_PYTHON_INSTALL_DIR",
)
WINDOWS_REMEDY = (
    "This helper is POSIX only. On Windows run `py -0p` and probe the listed "
    "executables as references/run-safety.md describes."
)
SHIM_DIRECTORIES = ("shims",)
VERSION = re.compile(r"\d+\.\d+\.\d+")


def clean_environment(environ=None) -> dict[str, str]:
    """Only what a launcher needs to run; never a Traigent value or a provider key."""
    source = os.environ if environ is None else environ
    return {name: source[name] for name in KEPT_ENVIRONMENT if name in source}


def _launch(command: list[str], run) -> subprocess.CompletedProcess | None:
    try:
        return run(
            command,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            env=clean_environment(),
            cwd=tempfile.gettempdir(),
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def inside(path: str, root: Path | None) -> bool:
    """True when `path` is under `root` lexically or after resolving symlinks.

    A path that cannot be resolved (a symlink loop, a permission error) counts as
    inside: it is not trusted, so it is not used.
    """
    if root is None:
        return False
    try:
        lexical_root = os.path.abspath(root)
        lexical = os.path.abspath(path)
        real_root = os.path.realpath(root)
        real = os.path.realpath(path, strict=True)
    except (OSError, RuntimeError, ValueError):
        return True
    for candidate, base in ((lexical, lexical_root), (real, real_root)):
        if os.path.commonpath([candidate, base]) == base:
            return True
    return False


def is_shim(path: str) -> bool:
    parts = Path(os.path.abspath(path)).parts
    return any(part in SHIM_DIRECTORIES for part in parts[:-1])


def on_path(which=shutil.which) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in NAMES:
        path = which(name)
        if path and path not in seen:
            seen.add(path)
            found.append((path, name))
    return found


def uv_candidate(
    project_root: Path | None, which=shutil.which, run=subprocess.run
) -> tuple[str | None, str | None]:
    """(candidate, why-not): the interpreter a trusted `uv` reports, if any."""
    uv = which("uv")
    if not uv:
        return None, None
    if inside(uv, project_root) or is_shim(uv):
        return None, f"{uv} (uv inside the project or a shim, not launched)"
    completed = _launch(
        [uv, "python", "find", "--offline", "--no-python-downloads", UV_SPEC], run
    )
    if completed is None or completed.returncode != 0:
        return None, f"{uv} (found no interpreter)"
    lines = completed.stdout.strip().splitlines()
    return (
        (lines[-1].strip(), None) if lines else (None, f"{uv} (found no interpreter)")
    )


def probe(path: str, run=subprocess.run) -> dict | None:
    """The interpreter's own answer, or None unless it is complete and well formed."""
    completed = _launch([path, "-I", "-S", "-B", "-c", PROBE], run)
    if completed is None or completed.returncode != 0:
        return None
    try:
        answer = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return None
    if not isinstance(answer, dict):
        return None
    version, executable = answer.get("version"), answer.get("executable")
    if not (
        isinstance(version, str)
        and VERSION.fullmatch(version)
        and isinstance(executable, str)
        and executable
        and isinstance(answer.get("ok"), bool)
    ):
        return None
    major, minor = (int(part) for part in version.split(".")[:2])
    # The version string, not the flag, decides: a flag from a hostile or broken
    # executable must not widen the supported range.
    answer["ok"] = answer["ok"] and major == 3 and 11 <= minor < 14
    return answer


def accept(
    path: str, how: str, project_root: Path | None, tried: list[str], run
) -> dict | None:
    if inside(path, project_root):
        tried.append(f"{path} (inside the project, skipped)")
        return None
    if is_shim(path):
        tried.append(f"{path} (version-manager shim, skipped)")
        return None
    answer = probe(path, run)
    if answer is None:
        tried.append(f"{path} (no well-formed answer)")
        return None
    if not answer["ok"]:
        tried.append(f"{path} ({answer['version']}, unsupported)")
        return None
    real = os.path.realpath(answer["executable"])
    if (
        not os.path.isfile(real)
        or not os.access(real, os.X_OK)
        or inside(real, project_root)
    ):
        tried.append(f"{path} (no usable real executable outside the project)")
        return None
    return {"python": real, "version": answer["version"], "via": how}


def find_python(
    project_root: Path | None = None,
    which=shutil.which,
    run=subprocess.run,
    posix: bool | None = None,
) -> dict:
    if not (os.name == "posix" if posix is None else posix):
        return {"error": WINDOWS_REMEDY, "tried": []}
    tried: list[str] = []
    for path, how in on_path(which):
        found = accept(path, how, project_root, tried, run)
        if found:
            return found
    candidate, why_not = uv_candidate(project_root, which, run)
    if why_not:
        tried.append(why_not)
    if candidate:
        found = accept(candidate, "uv python find", project_root, tried, run)
        if found:
            return found
    return {"error": REMEDY, "tried": tried}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--project-root",
        type=Path,
        help="skip any interpreter that lives inside this directory",
    )
    options = parser.parse_args(argv)
    result = find_python(options.project_root)
    print(json.dumps(result, indent=2))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Find a trusted, supported Python 3.11-3.13 and print its real path as JSON.

Run it with any Python 3: `python3 -I -S -B find_python.py [--project-root DIR]`.
The search order is `python3`, `python3.13`, `python3.12`, `python3.11` on PATH, then
`uv python find --offline --no-python-downloads` when uv is already installed. Nothing
is installed or downloaded. Each candidate is probed with `-I -S -B -c` and its answer
decides: the printed path is the interpreter's own base executable with every symlink
resolved, because an environment created through a symlinked interpreter is refused
by `environment_install.py`. Executables inside `--project-root` are skipped.

Exit 0 prints {"python": <real path>, "version": <x.y.z>, "via": <how found>}.
Exit 1 prints {"error": <one remedy>, "tried": [...]}.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
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


def inside(path: str, root: Path | None) -> bool:
    if root is None:
        return False
    try:
        Path(path).resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def candidates(which=shutil.which, run=subprocess.run) -> list[tuple[str, str]]:
    """(path, how) pairs in preference order, without launching a candidate."""
    found = [(path, name) for name in NAMES if (path := which(name))]
    uv = which("uv")
    if uv:
        try:
            completed = run(
                [uv, "python", "find", "--offline", "--no-python-downloads", UV_SPEC],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            completed = None
        if completed is not None and completed.returncode == 0:
            line = completed.stdout.strip().splitlines()
            if line:
                found.append((line[-1].strip(), "uv python find"))
    return found


def probe(path: str, run=subprocess.run) -> dict | None:
    try:
        completed = run(
            [path, "-I", "-S", "-B", "-c", PROBE],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        answer = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return None
    return answer if isinstance(answer, dict) else None


def find_python(
    project_root: Path | None = None,
    which=shutil.which,
    run=subprocess.run,
) -> dict:
    tried: list[str] = []
    for path, how in candidates(which, run):
        if inside(path, project_root):
            tried.append(f"{path} (inside the project, skipped)")
            continue
        answer = probe(path, run)
        if not answer or not answer.get("ok"):
            version = answer.get("version") if answer else "unprobed"
            tried.append(f"{path} ({version}, unsupported)")
            continue
        real = os.path.realpath(str(answer.get("executable", "")))
        if (
            not os.path.isfile(real)
            or not os.access(real, os.X_OK)
            or inside(real, project_root)
        ):
            tried.append(f"{path} (no usable real executable)")
            continue
        return {"python": real, "version": answer["version"], "via": how}
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

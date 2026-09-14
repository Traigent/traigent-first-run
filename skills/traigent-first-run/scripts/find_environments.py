#!/usr/bin/env python3
"""Discover virtual environments without executing their interpreters or startup hooks.

Run with a trusted Python using -I -S -B. Candidate configuration, interpreter
provenance and installed distribution metadata are read statically. An interpreter
that cannot be matched to this trusted runtime stays visible as unverified.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.machinery
import importlib.metadata
import importlib.util
import json
import marshal
import os
import re
import sys
import sysconfig
import types
import venv
import zipfile
from pathlib import Path

SUPPORTED = ((3, 11), (3, 14))
ENVIRONMENT_VARIABLES = ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")
UNSUPPORTED_RANGE = "not 3.11-3.13"


def name_looks_like_environment(name: str) -> bool:
    """`venv`, `env`, `.venv-dev`, `projectX_venv`, `ENV`: the name test alone."""
    return "env" in name.casefold()


def interpreter_of(directory: Path) -> Path | None:
    """The interpreter of a real virtual environment, or None.

    `pyvenv.cfg` plus a `bin/python` or `Scripts/python.exe` is what separates
    a virtual environment from a folder that happens to be called `env`.
    """
    if not (directory / "pyvenv.cfg").is_file():
        return None
    for relative in ("bin/python", "Scripts/python.exe"):
        interpreter = directory / relative
        if interpreter.is_file():
            return interpreter
    return None


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def candidate_directories(
    root: Path, environ: dict[str, str] | None = None
) -> list[tuple[Path, str]]:
    """Every real virtual environment directly under `root`, plus the ones
    `$VIRTUAL_ENV` / `$UV_PROJECT_ENVIRONMENT` name when they resolve inside it.

    Poetry's and uv's in-project location is `.venv` at the root, which the
    name test already finds. Nothing outside the root is ever listed.
    """
    environ = os.environ if environ is None else environ
    found: dict[Path, str] = {}
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if (
                child.is_dir()
                and (child.is_symlink() or inside(child, root))
                and name_looks_like_environment(child.name)
                and (child / "pyvenv.cfg").is_file()
            ):
                found[child.absolute()] = "project-root"
    for variable in ENVIRONMENT_VARIABLES:
        value = environ.get(variable, "")
        if not value:
            continue
        directory = Path(value)
        if (
            directory.is_dir()
            and not directory.is_symlink()
            and inside(directory, root)
            and (directory / "pyvenv.cfg").is_file()
        ):
            found.setdefault(directory.resolve(), variable)
    return sorted(found.items())


def trusted_pip_wheel() -> Path:
    """The wheel shipped with this trusted Python, never an installed pip module."""
    try:
        import ensurepip
    except ImportError as error:
        raise ValueError(
            "Trusted Python lacks ensurepip; use a trusted Python with its bundled pip wheel"
        ) from error
    filename = f"pip-{ensurepip.version()}-py3-none-any.whl"
    locations = [Path(ensurepip.__file__).parent / "_bundled" / filename]
    wheel_directory = sysconfig.get_config_var("WHEEL_PKG_DIR")
    if wheel_directory:
        locations.append(Path(wheel_directory) / filename)
    for location in locations:
        if location.is_file():
            return location.resolve()
    raise ValueError(
        "Trusted Python has no bundled ensurepip wheel; use a trusted Python with ensurepip"
    )


def version_tuple(version: str):
    """A PEP 440 Version from the trusted bundled pip's packaging implementation."""
    if not isinstance(version, str) or not version or any(c.isspace() for c in version):
        raise ValueError("Invalid distribution version")
    namespace = "_traigent_trusted_packaging"
    if namespace not in sys.modules:
        package = types.ModuleType(namespace)
        package.__path__ = [str(trusted_pip_wheel()) + "/pip/_vendor/packaging"]
        sys.modules[namespace] = package
    return importlib.import_module(namespace + ".version").Version(version)


def canonical_name(name: str) -> str:
    if (
        not isinstance(name, str)
        or re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", name) is None
    ):
        raise ValueError("Invalid distribution name")
    return re.sub(r"[-_.]+", "-", name).lower()


def normalized_versions(versions: dict[str, str]) -> dict[str, str]:
    normalized = {}
    for name, version in versions.items():
        name = canonical_name(name)
        version_tuple(version)
        if name in normalized:
            raise ValueError(f"Ambiguous installed distribution: {name}")
        normalized[name] = version
    return normalized


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def trusted_interpreter() -> Path:
    return Path(getattr(sys, "_base_executable", sys.executable)).resolve()


def trusted_shim_bytecode(shim: Path, source: bytes) -> bool:
    """Do not admit a trusted source file paired with a different startup cache."""
    if any(
        (shim.parent / ("__init__" + suffix)).exists()
        for suffix in importlib.machinery.EXTENSION_SUFFIXES
    ):
        return False
    caches = list((shim.parent / "__pycache__").glob("__init__.*.pyc"))
    if shim.with_suffix(".pyc").exists():
        caches.append(shim.with_suffix(".pyc"))
    for cache in caches:
        raw = cache.read_bytes()
        if len(raw) < 16 or raw[:4] != importlib.util.MAGIC_NUMBER:
            return False
        try:
            code = marshal.loads(raw[16:])
        except (EOFError, TypeError, ValueError):
            return False
        if not isinstance(code, types.CodeType):
            return False
        optimized = re.search(r"\.opt-([12])\.pyc$", cache.name)
        expected = compile(
            source,
            code.co_filename,
            "exec",
            dont_inherit=True,
            optimize=int(optimized[1]) if optimized else 0,
        )
        if code != expected:
            return False
    return True


def trusted_setuptools_startup(path: Path, contents: str) -> bool:
    """Recognize only the startup hook and shim shipped by trusted ensurepip."""
    if path.name != "distutils-precedence.pth":
        return False
    shim = path.parent / "_distutils_hack" / "__init__.py"
    if not shim.is_file() or not inside(shim, path.parent):
        return False
    for wheel in trusted_pip_wheel().parent.glob("setuptools-*.whl"):
        with zipfile.ZipFile(wheel) as archive:
            try:
                hook_bytes = archive.read("distutils-precedence.pth")
                shim_bytes = archive.read("_distutils_hack/__init__.py")
            except KeyError:
                continue
            if (
                contents.encode("utf-8") == hook_bytes
                and shim.read_bytes() == shim_bytes
                and trusted_shim_bytecode(shim, shim_bytes)
            ):
                return True
    return False


def refuse_custom_startup(directory: Path) -> None:
    for name in ("sitecustomize", "usercustomize"):
        if (directory / name).is_dir() or any(
            (directory / (name + suffix)).exists()
            for suffix in importlib.machinery.all_suffixes()
        ):
            raise ValueError(
                "Unknown startup customization prevents a complete metadata inventory; choose a fresh verified environment"
            )


def path_configuration(sites: list[str]) -> list[tuple[str, str]]:
    """Read path-only startup declarations without executing import hooks.

    Extra distributions exposed by a .pth path would be invisible to isolated
    pip's target-site metadata view. Unknown executable hooks/customizations are
    unverified; recognizing a hook filename or its RECORD owner is insufficient.
    Nothing in this inventory executes the hook.
    """
    declarations = []
    known = {Path(site).resolve() for site in sites}
    for site in sites:
        refuse_custom_startup(Path(site))
        for path in sorted(Path(site).glob("*.pth")):
            contents = path.read_text(encoding="utf-8")
            declarations.append((str(path), contents))
            for line in contents.splitlines():
                line = line.rstrip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith(("import ", "import\t")):
                    if not trusted_setuptools_startup(path, contents):
                        raise ValueError(
                            "Unknown executable .pth hook prevents a complete metadata inventory; choose a fresh verified environment"
                        )
                    continue
                extra = Path(site) / line
                if extra.exists() and extra.resolve() not in known:
                    refuse_custom_startup(extra)
                    if any(importlib.metadata.distributions(path=[str(extra)])):
                        raise ValueError(
                            "A .pth path exposes distribution metadata outside the target sites; choose an environment without inherited package metadata"
                        )
    return declarations


def verified_environment(interpreter: Path) -> dict:
    """Match copied or symlinked executables to a known runtime without launching them.

    Matching a claimed configuration version alone is never verification. Windows
    venv launchers are accepted only when their bytes match this runtime's own
    stdlib launcher and their configured home is the trusted runtime directory.
    """
    directory = interpreter.parent.parent.resolve()
    configuration = directory / "pyvenv.cfg"
    cfg = {}
    for line in configuration.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            key = key.strip().lower()
            if key in cfg:
                raise ValueError("Duplicate virtual environment configuration field")
            cfg[key] = value.strip()
    base = trusted_interpreter()
    declared = cfg.get("version", cfg.get("version_info", "unknown"))
    remedy = f"Rerun discovery with a trusted Python matching this environment's declared version ({declared}), using -I -S -B; or choose another verified environment."
    if Path(cfg.get("home", "")).resolve() != base.parent:
        raise ValueError(
            "Interpreter home does not match this trusted runtime. " + remedy
        )
    expected = [base]
    if os.name == "nt":
        expected.extend(
            [
                Path(venv.__file__).parent / "scripts" / "nt" / "python.exe",
                base.parent / "venvlauncher.exe",
                base.parent / "venvlauncher_d.exe",
            ]
        )
    actual_hash = file_digest(interpreter)
    if not any(
        path.is_file() and file_digest(path) == actual_hash for path in expected
    ):
        raise ValueError(
            "Interpreter bytes do not match this trusted runtime. " + remedy
        )
    current = ".".join(map(str, sys.version_info[:3]))
    if declared != "unknown" and not re.match(
        rf"^{re.escape(current)}(?:$|\.final\.0$)", declared
    ):
        raise ValueError(
            "Configuration and verified runtime version disagree. " + remedy
        )
    if cfg.get("include-system-site-packages", "false").lower() != "false":
        raise ValueError(
            "Inherited system site-packages cannot be treated as an isolated install target; choose an environment without system-site-packages"
        )
    sites = sorted(
        {
            sysconfig.get_path(
                key, "venv", vars={"base": str(directory), "platbase": str(directory)}
            )
            for key in ("purelib", "platlib")
        }
    )
    if not all(inside(Path(site), directory) for site in sites):
        raise ValueError("Environment site-packages resolves outside the environment")
    startup_declarations = path_configuration(sites)
    installed = {}
    metadata_state = []
    for distribution in importlib.metadata.distributions(path=sites):
        metadata = distribution.metadata
        if (
            len(metadata.get_all("Name", [])) != 1
            or len(metadata.get_all("Version", [])) != 1
        ):
            raise ValueError("Malformed installed distribution metadata")
        name = canonical_name(metadata["Name"])
        version = metadata["Version"]
        version_tuple(version)
        if name in installed:
            raise ValueError(f"Ambiguous installed distribution: {name}")
        installed[name] = version
        metadata_state.append(
            [
                name,
                version,
                distribution.read_text("METADATA"),
                distribution.read_text("RECORD"),
                distribution.read_text("entry_points.txt"),
            ]
        )
    # Legacy path-based editable installs are not visible to a metadata-only pip.
    for site in sites:
        for pattern in ("*.egg-link", "*.egg-info"):
            for path in Path(site).glob(pattern):
                raise ValueError(
                    f"Legacy installation metadata is not supported: {path.name}; choose another environment"
                )
    return {
        "prefix": str(directory),
        "version": current,
        "site": sites[0],
        "sites": sites,
        "installed": installed,
        "verification": "verified",
        "identity": {
            "interpreter_sha256": actual_hash,
            "configuration_sha256": file_digest(configuration),
            "path_configuration_sha256": hashlib.sha256(
                json.dumps(startup_declarations).encode()
            ).hexdigest(),
            "metadata_sha256": hashlib.sha256(
                json.dumps(sorted(metadata_state), sort_keys=True).encode()
            ).hexdigest(),
            "trusted_runtime": str(base),
            "trusted_runtime_sha256": file_digest(base),
        },
    }


def probe(interpreter: Path) -> dict:
    """Read a candidate statically; failures stay explicit and never execute it."""
    try:
        return verified_environment(interpreter)
    except (OSError, ValueError) as error:
        return {"error": str(error), "verification": "unverified"}


def supported(version: str) -> bool:
    return SUPPORTED[0] <= version_tuple(version).release[:2] < SUPPORTED[1]


def read_pins(requirements: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in requirements.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" in line:
            name, _, version = line.partition("==")
            name = canonical_name(name.strip())
            if name in pins:
                raise ValueError(f"Duplicate requirement: {name}")
            version_tuple(version.strip())
            pins[name] = version.strip()
        elif line:
            raise ValueError("Requirements must contain only exact name==version pins")
    return pins


def guard(installed: dict[str, str], pins: dict[str, str]) -> list[dict]:
    """The version guard, one record per tested pin.

    `install`: absent, so the pin is what gets installed. `keep`: present at
    the pin. `keep-newer`: present above the pin - kept, with the note that it
    is not the tested version. `change`: present below the pin; replacing it
    needs the customer's explicit yes to the `line` this record carries.
    """
    installed = normalized_versions(installed)
    pins = normalized_versions(pins)
    records = []
    for name, pinned in pins.items():
        current = installed.get(name)
        if current is None:
            record = {
                "package": name,
                "installed": None,
                "pinned": pinned,
                "action": "install",
            }
        elif version_tuple(current) == version_tuple(pinned):
            record = {
                "package": name,
                "installed": current,
                "pinned": pinned,
                "action": "keep",
            }
        elif version_tuple(current) > version_tuple(pinned):
            record = {
                "package": name,
                "installed": current,
                "pinned": pinned,
                "action": "keep-newer",
                "note": f"{name} {current} is not the tested version ({pinned})",
            }
        else:
            record = {
                "package": name,
                "installed": current,
                "pinned": pinned,
                "action": "change",
                "line": f"this will change {name} {current} to {pinned}",
            }
        records.append(record)
    return records


def install_arguments(records: list[dict], approved_changes: bool = False) -> list[str]:
    """The `pip install` arguments the guard allows: missing pins always,
    version changes only once the customer said yes to each change line."""
    arguments = []
    for record in records:
        if record["action"] == "install" or (
            approved_changes and record["action"] == "change"
        ):
            arguments.append(f"{record['package']}=={record['pinned']}")
    return arguments


def approval_card(report: dict, installed: dict[str, str]) -> dict:
    """Split the `pip install --dry-run --report` JSON into what the card shows: packages
    new to the environment, and installed packages whose version would change."""
    installed = normalized_versions(installed)
    new, changes = [], []
    seen = set()
    for item in report.get("install", []):
        metadata = item.get("metadata", {})
        name = canonical_name(metadata.get("name", ""))
        version = str(metadata.get("version", ""))
        version_tuple(version)
        if name in seen:
            raise ValueError(f"Ambiguous resolved distribution: {name}")
        seen.add(name)
        current = installed.get(name)
        if current is None:
            new.append(f"{name} {version}")
        elif current != version:
            changes.append(f"{name} {current} -> {version}")
    return {"new": sorted(new), "changes": sorted(changes)}


def describe(
    root: Path, requirements: Path, environ: dict[str, str] | None = None
) -> dict:
    pins = read_pins(requirements)
    candidates = []
    for directory, source in candidate_directories(root, environ):
        interpreter = interpreter_of(directory)
        if directory.is_symlink():
            probed = {
                "error": "Environment directory is a symlink; preserve it and choose an explicit verified directory"
            }
        elif interpreter is None:
            probed = {
                "error": "Environment interpreter is missing or broken; restore it or choose another verified environment"
            }
        else:
            probed = probe(interpreter)
        entry = {
            "path": str(directory),
            "source": source,
            "interpreter": str(interpreter) if interpreter else None,
        }
        if "error" in probed:
            entry.update(
                {
                    "probe_error": probed["error"],
                    "supported": None,
                    "verification": "unverified",
                    "remedy": probed["error"]
                    + " Use a matching trusted Python with -I -S -B or choose another environment.",
                }
            )
        else:
            entry.update(
                {
                    "verification": "verified",
                    "prefix": probed["prefix"],
                    "site": probed["site"],
                    "python_version": probed["version"],
                    "supported": supported(probed["version"]),
                    "installed": {name: probed["installed"].get(name) for name in pins},
                    "guard": guard(probed["installed"], pins),
                }
            )
        candidates.append(entry)
    usable = [entry for entry in candidates if entry["supported"]]
    skipped = [entry for entry in candidates if not entry["supported"]]
    if usable:
        state = "one" if len(usable) == 1 else "several"
    elif any(entry["supported"] is None for entry in skipped):
        state = "unverified"
    elif skipped:
        state = "unsupported"
    else:
        state = "none"
    return {
        "project_root": str(root.resolve()),
        "pins": pins,
        "candidates": candidates,
        "state": state,
        "skipped": [skipped_clause(entry) for entry in skipped],
    }


def skipped_clause(entry: dict) -> str:
    """The `<path> was skipped (...)` clause the guide prints for a candidate
    it will not propose: an unsupported Python, or a probe that did not answer."""
    if "python_version" in entry:
        reason = f"Python {entry['python_version']}, {UNSUPPORTED_RANGE}"
    else:
        reason = "unverified: " + entry["probe_error"]
    return f"{entry['path']} was skipped ({reason})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--requirements", required=True, type=Path)
    parser.add_argument(
        "--candidate",
        type=Path,
        help="render the approval card for this environment directory",
    )
    parser.add_argument(
        "--dry-run-report",
        type=Path,
        help="the JSON `pip install --dry-run --report` wrote for --candidate",
    )
    options = parser.parse_args(argv)
    if (options.candidate is None) != (options.dry_run_report is None):
        parser.error("--candidate and --dry-run-report go together")
    if options.candidate is not None:
        interpreter = interpreter_of(options.candidate)
        if interpreter is None:
            parser.error(f"{options.candidate} is not a virtual environment")
        probed = probe(interpreter)
        if "error" in probed:
            print(json.dumps({"error": probed["error"]}))
            return 1
        report = json.loads(options.dry_run_report.read_text(encoding="utf-8"))
        card = approval_card(report, probed["installed"])
        card["path"] = str(options.candidate.resolve())
        card["guard"] = guard(probed["installed"], read_pins(options.requirements))
        print(json.dumps(card, indent=2))
        return 0
    try:
        print(
            json.dumps(describe(options.project_root, options.requirements), indent=2)
        )
    except (OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

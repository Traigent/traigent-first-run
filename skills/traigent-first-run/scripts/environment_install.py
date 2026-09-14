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
import csv
import email.parser
import importlib.util
import json
import ntpath
import os
import subprocess
import sys
import sysconfig
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "_first_run_environments", Path(__file__).with_name("find_environments.py")
)
ENV = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ENV)


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


def isolated_pip(candidate: Path, arguments: list[str], working: Path) -> None:
    """Run this adapter in a fresh trusted child, never the candidate executable."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTHON", "PIP_", "LD_", "DYLD_"))
    }
    environment["PIP_CONFIG_FILE"] = os.devnull
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
    )
    if result.returncode:
        # pip may include index credentials in verbose diagnostics. Retain only
        # URL-redacted output in the error that the approval workflow displays.
        import re

        output = re.sub(
            r"(?:https?|file)://\S+",
            "<artifact-location>",
            result.stdout + result.stderr,
        )
        raise ValueError(
            "Isolated pip failed; inspect the target before retrying:\n" + output
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


def cache_wheel(item: dict, directory: Path) -> dict:
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
    with urllib.request.urlopen(url) as response, target.open("xb") as stream:
        # Pip already fetched/hashed these artifacts during resolution. Recheck the
        # bytes cached for apply; never trust a URL to remain the same after yes.
        while block := response.read(1024 * 1024):
            stream.write(block)
    if ENV.file_digest(target) != expected:
        raise ValueError("Resolved wheel changed before it could be cached")
    return {
        "path": str(target),
        "sha256": expected,
        "name": ENV.canonical_name(item["metadata"]["name"]),
        "version": item["metadata"]["version"],
    }


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
        raise ValueError("Plan already exists; choose a fresh plan path")
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
            isolated_pip(candidate, arguments, working)
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
        cache = Path(
            tempfile.mkdtemp(prefix=plan_path.stem + "-wheels-", dir=plan_path.parent)
        )
        artifacts = [cache_wheel(item, cache) for item in report["install"]]
    document = {
        "schema": 1,
        "candidate": str(candidate),
        "identity": before["identity"],
        "requirements": str(options.requirements.resolve()),
        "requirements_sha256": ENV.file_digest(options.requirements),
        "new": card["new"],
        "changes": card["changes"],
        "artifacts": artifacts,
    }
    with plan_path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return {"plan": str(plan_path), "plan_sha256": ENV.file_digest(plan_path), **card}


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
        result = plan(options) if options.command == "plan" else apply(options)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

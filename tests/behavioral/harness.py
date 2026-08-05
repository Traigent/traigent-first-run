#!/usr/bin/env python3
"""Hermetic contract checks for the pre-network first-run behavior.

This is an internal test harness. It deliberately stops before SDK, provider,
backend, optimization, or portal work and cannot produce a customer result.
"""

from __future__ import annotations

import argparse
import errno
import fnmatch
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SCENARIOS = HERE / "scenarios"
SKILL = ROOT / "skills" / "traigent-first-run" / "SKILL.md"
READINESS = ROOT / "skills" / "traigent-first-run" / "scripts" / "readiness.py"
PREFLIGHT = ROOT / "skills" / "traigent-first-run" / "scripts" / "preflight.py"
CALIBRATE = (
    ROOT / "skills" / "traigent-first-run" / "scripts" / "calibrate_evaluator.py"
)
REQUIRED_CONTRACT_KEYS = {
    "id",
    "user_request",
    "starting_state",
    "allowed_writes",
    "forbidden_actions",
    "expected_stop_reason",
    "preserve",
    "assertions",
}
FORBIDDEN_ACTIONS = {
    "environment_create",
    "package_install",
    "provider_call",
    "traigent_backend_call",
    "optimization",
    "portal_result",
    "paid_work",
}
ALLOWED_SCRIPTS = {path.resolve() for path in (READINESS, PREFLIGHT, CALIBRATE)}
CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|\x1b")
MAX_CAPTURE = 100_000


class ContractError(RuntimeError):
    """Raised when a scenario violates the offline contract."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ContractError(f"unsafe relative path: {value!r}")
    return path.as_posix()


def tree_manifest(root: Path) -> list[dict[str, Any]]:
    """Return a canonical, symlink-rejecting tree manifest."""
    if not root.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            raise ContractError(f"symlinks are forbidden in scenario trees: {relative}")
        if stat.S_ISDIR(info.st_mode):
            entries.append({"path": relative, "type": "directory", "mode": mode})
        elif stat.S_ISREG(info.st_mode):
            content = path.read_bytes()
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "mode": mode,
                    "size": len(content),
                    "sha256": sha256_bytes(content),
                }
            )
        else:
            raise ContractError(
                f"special files are forbidden in scenario trees: {relative}"
            )
    return entries


# Names inside the skill tree that are never part of the package: tool caches and
# the run artifacts this skill itself writes. Mirrors the relevant `.gitignore`
# entries, and `test_the_git_and_walk_file_lists_agree` fails if the two drift.
_EXCLUDED_DIR_NAMES = {
    "__pycache__",
    "traigent-runs",
    "optimization_results",
    "results",
}
_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def _walk_behavior_files(root: Path) -> list[Path]:
    """Filesystem fallback for environments without git.

    The offline-contract job runs in a pinned `python:3.12-slim` image with no
    git, and installing one would put a network fetch inside the evidence
    boundary the job exists to keep clean.

    Hidden directories are skipped as a class rather than named one at a time:
    `.ruff_cache`, `.pytest_cache` and `.mypy_cache` are all tool state, and the
    previous denylist could only ever name the ones someone had already hit.
    Hidden *files* are kept - a `.gitignore` shipped inside the package is part
    of it.
    """
    skill_root = root / "skills" / "traigent-first-run"
    found = [Path("GUIDE.md")]
    for path in skill_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        parents = relative.parts[:-1]
        if any(part.startswith(".") or part in _EXCLUDED_DIR_NAMES for part in parents):
            continue
        if path.suffix in _EXCLUDED_SUFFIXES:
            continue
        found.append(relative)
    return sorted(found)


def behavior_files(root: Path) -> list[Path]:
    """The files the behaviour lock covers, as git sees them where git exists.

    Asking git rather than walking, because the walk needed a hand-maintained
    list of things to skip and that list can only ever name the tool droppings
    someone already hit. `__pycache__` and `*.pyc` were on it; `.ruff_cache/`,
    written by `ruff check skills/`, was not - so three untracked cache files
    entered the lock, which then matched only on the machine that generated it.
    Green locally, red in CI, same commit.

    `--cached --others --exclude-standard` is tracked files plus new ones that
    are not ignored: a reference added but not yet staged is still covered, so
    regenerating before `git add` cannot silently under-lock the package, while
    anything `.gitignore` excludes is excluded here for free.

    Falls back to {@link _walk_behavior_files} only when git is genuinely absent
    - never on a git error, which would hide a real problem behind a quieter
    answer.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                "GUIDE.md",
                "skills/traigent-first-run",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, NotADirectoryError):
        return _walk_behavior_files(root)
    if result.returncode != 0:
        raise RuntimeError(
            "could not list the behaviour files from git "
            f"(exit {result.returncode}): {result.stderr.strip()}"
        )
    return sorted(Path(entry) for entry in result.stdout.split("\0") if entry)


def behavior_manifest(root: Path = ROOT) -> dict[str, Any]:
    behavior_paths = behavior_files(root)
    entries = []
    for relative in behavior_paths:
        path = root / relative
        content = path.read_bytes()
        entries.append(
            {
                "path": relative.as_posix(),
                "size": len(content),
                "sha256": sha256_bytes(content),
            }
        )
    return {
        "schema_version": 1,
        "paths": entries,
        "digest": sha256_bytes(canonical_json(entries).encode()),
    }


def load_contract(scenario_dir: Path) -> dict[str, Any]:
    try:
        value = json.loads((scenario_dir / "scenario.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(
            f"cannot load scenario contract at {scenario_dir}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise ContractError(f"scenario contract must be an object: {scenario_dir}")
    return value


def minimal_contract(*, allowed_writes: list[str]) -> dict[str, Any]:
    return {
        "id": "minimal",
        "user_request": "Try Traigent",
        "starting_state": {
            "agent": "missing",
            "dataset": "missing",
            "evaluation": "missing",
        },
        "allowed_writes": allowed_writes,
        "forbidden_actions": sorted(FORBIDDEN_ACTIONS),
        "expected_stop_reason": "awaiting_task_intent",
        "preserve": [],
        "assertions": {},
    }


def validate_contract_shape(contract: dict[str, Any], scenario_dir: Path) -> None:
    missing = REQUIRED_CONTRACT_KEYS - set(contract)
    if missing:
        raise ContractError(
            f"scenario {scenario_dir} is missing keys: {sorted(missing)}"
        )
    if contract["id"] != scenario_dir.name and scenario_dir.name != "scenario":
        raise ContractError(f"scenario id does not match directory: {scenario_dir}")
    if (
        not isinstance(contract["user_request"], str)
        or not contract["user_request"].strip()
    ):
        raise ContractError("user_request must be a non-empty string")
    if set(contract["starting_state"]) != {"agent", "dataset", "evaluation"}:
        raise ContractError(
            "starting_state must declare agent, dataset, and evaluation"
        )
    if set(contract["forbidden_actions"]) != FORBIDDEN_ACTIONS:
        raise ContractError(
            "every offline scenario must forbid all external/result actions"
        )
    if not isinstance(contract["expected_stop_reason"], str):
        raise ContractError("expected_stop_reason must be a string")
    for collection in ("allowed_writes", "preserve"):
        if not isinstance(contract[collection], list):
            raise ContractError(f"{collection} must be a list")
        for value in contract[collection]:
            safe_relative(value.rstrip("/**"))
    if not isinstance(contract["assertions"], dict):
        raise ContractError("assertions must be an object")


def git_tracked_mode(mode: int) -> int:
    """Return only the permission bits git can reproduce on checkout.

    Git records exactly one permission bit, owner-execute; every other bit comes
    from the checking-out user's umask. A lock storing the full mode therefore
    fails for any contributor whose umask differs from the one that generated it
    - 0664 under `umask 0002` against a lock written as 0644 under `umask 022` -
    even when the content is byte-identical. Comparing the reproducible subset
    keeps the lock a statement about content and the executable bit, which is
    all it can honestly assert.
    """
    return 0o755 if mode & stat.S_IXUSR else 0o644


def comparable_fixture_entries(
    entries: list[dict[str, Any]], scenario_name: str
) -> list[dict[str, Any]]:
    """Normalize umask-dependent modes and reject genuinely unsafe bits."""
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        mode = entry.get("mode")
        if not isinstance(mode, int):
            normalized.append(entry)
            continue
        if mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX):
            raise ContractError(
                f"setuid/setgid/sticky bit is forbidden in scenario trees: "
                f"{scenario_name}/{entry.get('path')}"
            )
        if mode & stat.S_IWOTH:
            raise ContractError(
                f"world-writable fixture entry is forbidden: "
                f"{scenario_name}/{entry.get('path')}"
            )
        normalized.append({**entry, "mode": git_tracked_mode(mode)})
    return normalized


def describe_fixture_mismatch(expected: dict[str, Any], actual: dict[str, Any]) -> str:
    """Name what actually differs, so a mismatch is diagnosable at a glance."""
    details: list[str] = []
    for section in ("seed", "generated"):
        expected_by_path = {
            entry.get("path"): entry for entry in expected.get(section, [])
        }
        actual_by_path = {entry.get("path"): entry for entry in actual.get(section, [])}
        for path in sorted(set(expected_by_path) | set(actual_by_path)):
            before = expected_by_path.get(path)
            after = actual_by_path.get(path)
            if before == after:
                continue
            if before is None:
                details.append(f"{section}/{path}: unexpected extra entry")
            elif after is None:
                details.append(f"{section}/{path}: missing")
            else:
                fields = sorted(
                    key
                    for key in set(before) | set(after)
                    if before.get(key) != after.get(key)
                )
                changed = ", ".join(
                    f"{key} {before.get(key)!r} != {after.get(key)!r}" for key in fields
                )
                details.append(f"{section}/{path}: {changed}")
    if expected.get("schema_version") != actual.get("schema_version"):
        details.append(
            f"schema_version {expected.get('schema_version')!r} != "
            f"{actual.get('schema_version')!r}"
        )
    if not details:
        return "no per-entry difference found"
    shown = details[:5]
    if len(details) > len(shown):
        shown.append(f"... and {len(details) - len(shown)} more")
    return "; ".join(shown)


def verify_fixture_lock(scenario_dir: Path) -> None:
    try:
        expected = json.loads((scenario_dir / "fixture.lock.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(
            f"cannot load fixture lock for {scenario_dir.name}: {error}"
        ) from error
    actual = {
        "schema_version": 1,
        "seed": tree_manifest(scenario_dir / "seed"),
        "generated": tree_manifest(scenario_dir / "generated"),
    }
    comparable_expected = {
        "schema_version": expected.get("schema_version"),
        "seed": comparable_fixture_entries(expected.get("seed", []), scenario_dir.name),
        "generated": comparable_fixture_entries(
            expected.get("generated", []), scenario_dir.name
        ),
    }
    comparable_actual = {
        "schema_version": actual["schema_version"],
        "seed": comparable_fixture_entries(actual["seed"], scenario_dir.name),
        "generated": comparable_fixture_entries(actual["generated"], scenario_dir.name),
    }
    if comparable_expected != comparable_actual:
        raise ContractError(
            f"fixture lock mismatch for {scenario_dir.name}: "
            f"{describe_fixture_mismatch(comparable_expected, comparable_actual)}"
        )


def copy_scenario(source: Path, destination: Path) -> None:
    if destination.exists():
        raise ContractError(f"copy destination already exists: {destination}")
    shutil.copytree(source, destination)


def path_allowed(relative: str, patterns: list[str]) -> bool:
    return any(
        relative == pattern or fnmatch.fnmatchcase(relative, pattern)
        for pattern in patterns
    )


def validate_writes(contract: dict[str, Any], changed: list[str]) -> None:
    forbidden = [
        path for path in changed if not path_allowed(path, contract["allowed_writes"])
    ]
    if forbidden:
        raise ContractError(f"forbidden write(s): {', '.join(forbidden)}")


def manifest_changes(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> list[str]:
    before_map = {entry["path"]: entry for entry in before}
    after_map = {entry["path"]: entry for entry in after}
    return sorted(
        path
        for path in set(before_map) | set(after_map)
        if before_map.get(path) != after_map.get(path)
    )


def command_environment(audit_log: Path) -> dict[str, str]:
    python_dir = str(Path(sys.executable).resolve().parent)
    home = audit_log.parent / "home"
    home.mkdir(parents=True, exist_ok=True)
    return {
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": f"{python_dir}:/usr/bin:/bin",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INDEX": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONPATH": str(HERE / "guard"),
        "TMPDIR": "/tmp",
        "TRAIGENT_AUDIT_LOG": str(audit_log),
    }


def validate_command(argv: list[str]) -> None:
    if len(argv) < 2 or Path(argv[0]).name not in {
        "python",
        "python3",
        Path(sys.executable).name,
    }:
        raise ContractError(f"command is not allowlisted: {argv!r}")
    try:
        script = Path(argv[1]).resolve()
    except OSError as error:
        raise ContractError(f"command is not allowlisted: {argv!r}") from error
    if script not in ALLOWED_SCRIPTS:
        raise ContractError(f"command is not allowlisted: {argv!r}")


def clean_capture(value: str) -> str:
    if len(value.encode()) > MAX_CAPTURE:
        raise ContractError("command output exceeded the evidence limit")
    if CONTROL_CHARACTER.search(value):
        raise ContractError("command output contained control characters")
    return value


def normalize_text(value: str, project: Path) -> str:
    return value.replace(str(project), "<PROJECT>").replace(str(ROOT), "<REPO>")


def run_command(
    argv: list[str],
    project: Path,
    audit_log: Path,
    stdin_text: str | None = None,
) -> dict[str, Any]:
    validate_command(argv)
    process = subprocess.Popen(
        argv,
        cwd=project,
        env=command_environment(audit_log),
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        close_fds=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(input=stdin_text, timeout=30)
    except subprocess.TimeoutExpired as error:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise ContractError(f"allowlisted command timed out: {argv[1]}") from error
    stdout = normalize_text(clean_capture(stdout), project)
    stderr = normalize_text(clean_capture(stderr), project)
    record = {
        "argv": [
            "<PYTHON>" if index == 0 else normalize_text(value, project)
            for index, value in enumerate(argv)
        ],
        "cwd": "<PROJECT>",
        "env_keys": sorted(command_environment(audit_log)),
        "exit_code": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_sha256": sha256_bytes(stdout.encode()),
        "stderr_sha256": sha256_bytes(stderr.encode()),
    }
    if stdin_text is not None:
        record["stdin_bytes"] = len(stdin_text.encode())
        record["stdin_sha256"] = sha256_bytes(stdin_text.encode())
    if process.returncode != 0:
        raise ContractError(f"allowlisted command failed: {record}")
    return record


def kernel_network_probe() -> dict[str, str]:
    results: dict[str, str] = {}
    probes = (
        ("ipv4", socket.AF_INET, ("1.1.1.1", 443)),
        ("ipv6", socket.AF_INET6, ("2606:4700:4700::1111", 443, 0, 0)),
    )
    for name, family, address in probes:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(0.25)
        try:
            sock.connect(address)
        except OSError as error:
            if error.errno not in {
                errno.ENETUNREACH,
                errno.EHOSTUNREACH,
                errno.EACCES,
                errno.EPERM,
                errno.EADDRNOTAVAIL,
            }:
                raise ContractError(
                    f"{name} isolation probe failed ambiguously: {error}"
                ) from error
            results[name] = f"blocked:{error.errno}"
        else:
            raise ContractError(
                f"{name} external network is reachable; refusing offline qualification"
            )
        finally:
            sock.close()
    return results


def append_event(events: list[dict[str, Any]], event_type: str, **details: Any) -> None:
    events.append({"sequence": len(events) + 1, "type": event_type, **details})


def readiness_command(
    project: Path, states: dict[str, str], audit_log: Path
) -> dict[str, Any]:
    argv = [sys.executable, str(READINESS)]
    for component in ("agent", "dataset", "evaluation"):
        argv.extend((f"--{component}", states[component]))
    argv.append("--json")
    result = run_command(argv, project, audit_log)
    result["parsed"] = json.loads(result["stdout"])
    return result


def opening_preflight_command(project: Path, audit_log: Path) -> dict[str, Any]:
    """Run the free static preflight that opens a guided run.

    `--dataset` is deliberately omitted rather than pointed at a path that does
    not exist yet: the absent-dataset form exits 0 and still yields the
    `dataset-absent` cap, while a nonexistent `--dataset` exits 1 and would
    force this harness to stop treating a non-zero exit as a contract failure.
    """
    result = run_command(
        [sys.executable, str(PREFLIGHT), "--defer-missing-sdk", "--json"],
        project,
        audit_log,
    )
    result["parsed"] = json.loads(result["stdout"])
    return result


def score_command(
    project: Path,
    audit_log: Path,
    preflight_stdout: str,
    calibration: Path | None = None,
) -> dict[str, Any]:
    """Score readiness from preflight JSON on stdin, plus calibration if present.

    `preflight_stdout` must be the *normalized* capture, not the raw one. Every
    scenario runs twice and `main()` compares the two evidence bundles byte for
    byte; raw preflight output embeds the per-pass temporary project path, so a
    raw-stdin digest would report a reproducible scenario as nondeterministic.
    """
    argv = [sys.executable, str(READINESS), "--preflight", "-"]
    if calibration is not None:
        argv.extend(("--calibration", str(calibration)))
    argv.append("--json")
    result = run_command(argv, project, audit_log, stdin_text=preflight_stdout)
    score = json.loads(result["stdout"])
    if sorted(pillar["name"] for pillar in score["pillars"]) != [
        "agent",
        "dataset",
        "evaluation",
    ]:
        raise ContractError("readiness score must report all three pillars")
    result["parsed"] = score
    return result


def cap_conditions(score: dict[str, Any]) -> list[str]:
    return [cap["condition"] for cap in score["caps"]]


def score_event_fields(score: dict[str, Any]) -> dict[str, Any]:
    return {
        "overall": score["overall"],
        "band": score["band"],
        "caps": cap_conditions(score),
        "pillars": {pillar["name"]: pillar["score"] for pillar in score["pillars"]},
    }


def enforce_project_permissions(project: Path, allowed_writes: list[str]) -> None:
    if any(
        pattern == "traigent-runs" or pattern.startswith("traigent-runs/")
        for pattern in allowed_writes
    ):
        (project / "traigent-runs").mkdir(exist_ok=True)
    for path in sorted(project.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    project.chmod(0o555)
    if ".gitignore" in allowed_writes and (project / ".gitignore").exists():
        (project / ".gitignore").chmod(0o644)
    if any(
        pattern == "traigent-runs" or pattern.startswith("traigent-runs/")
        for pattern in allowed_writes
    ):
        run_dir = project / "traigent-runs"
        run_dir.chmod(0o755)


def stub_agent_no_anchor(
    contract: dict[str, Any], project: Path, audit_log: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """The quality-based twin of {@link zero_anchor} (#61).

    `zero-anchor` proves the gate fires on an EMPTY project, which is the case
    that always worked. This one proves it fires when a file the inventory would
    call "an agent" exists but performs no identifiable task - the shape that
    could walk past a presence-based reading of the trigger, invent a task, and
    carry it to a spend approval.

    Why the wording matters at all - SKILL.md loads `component-creation.md` only
    after this gate is evaluated, so the quality rule has to be stated at the gate
    itself - is locked in `tests/test_skill_package.py`. This driver proves the
    consequence: that the gate actually fires on the shape that could slip past it.
    """
    # Deliberately asserts no guide WORDING here. The wording lock for this gate
    # lives in `tests/test_skill_package.py`, alongside every other phrase lock,
    # and its four phrases are a superset of the three this driver used to check.
    # Keeping a copy cost a second edit site for one intent - and it produced a
    # CI-only red that had nothing to do with behaviour, because it matched raw
    # text against prose the guide hard-wraps. This layer proves the RUN: the gate
    # fires, one question is asked, nothing is written. Do not re-add prose checks.
    stub = project / "agent.py"
    if not stub.exists():
        raise ContractError("stub-agent-no-anchor seed must carry an agent.py")

    expected = contract["assertions"]
    events: list[dict[str, Any]] = []

    preflight = opening_preflight_command(project, audit_log)
    opening = score_command(project, audit_log, preflight["stdout"])
    score = opening["parsed"]
    if (
        score["overall"] != expected["opening_score"]
        or score["band"] != expected["opening_band"]
    ):
        raise ContractError("stub-agent opening score violated its declaration")
    if not set(expected["opening_caps"]) <= set(cap_conditions(score)):
        raise ContractError("stub-agent opening score lost its required caps")
    append_event(events, "opening_readiness_score", **score_event_fields(score))
    append_event(events, "record_deferred", reason="task intent not anchored")

    # The stub is reported as an INVALID agent, not a real one: it exists, so it
    # is not "missing" to the user, and it anchors nothing, so it cannot be an
    # anchor. Both facts have to survive into the board.
    append_event(
        events,
        "readiness",
        real={"agent": "invalid", "dataset": "missing", "evaluation": "missing"},
        markers={"agent": "❗", "dataset": "❗", "evaluation": "❗"},
    )
    append_event(events, "walkthrough_scope", synthetic_is_production_evidence=False)
    append_event(
        events,
        "question",
        category="task_intent",
        text="What should the walkthrough agent do?",
    )
    append_event(events, "stop", reason=contract["expected_stop_reason"])
    return events, [preflight, opening], contract["expected_stop_reason"]


def zero_anchor(
    contract: dict[str, Any], project: Path, audit_log: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    text = SKILL.read_text()
    section = text.split("#### Zero-anchor intent gate", 1)[1].split(
        "### 2. Show readiness once", 1
    )[0]
    question = "What should the walkthrough agent do?"
    if section.count(question) != 1 or section.count("?") != 1:
        raise ContractError(
            "zero-anchor package contract must contain exactly one task-intent question"
        )
    expected = contract["assertions"]
    events: list[dict[str, Any]] = []

    # The opening readiness gate is mandatory in every guided run, the empty
    # project included. Both commands are read-only static validation: they
    # write nothing into the project and are not the run record, which still
    # waits for the task-intent answer.
    preflight = opening_preflight_command(project, audit_log)
    opening = score_command(project, audit_log, preflight["stdout"])
    score = opening["parsed"]
    if (
        score["overall"] != expected["opening_score"]
        or score["band"] != expected["opening_band"]
    ):
        raise ContractError("zero-anchor opening score violated its declaration")
    if not set(expected["opening_caps"]) <= set(cap_conditions(score)):
        raise ContractError("zero-anchor opening score lost its required caps")
    append_event(events, "opening_readiness_score", **score_event_fields(score))
    append_event(events, "record_deferred", reason="task intent not anchored")

    append_event(
        events,
        "readiness",
        real={"agent": "missing", "dataset": "missing", "evaluation": "missing"},
        markers={"agent": "❗", "dataset": "❗", "evaluation": "❗"},
    )
    append_event(events, "walkthrough_scope", synthetic_is_production_evidence=False)
    append_event(events, "question", category="task_intent", text=question)
    append_event(events, "stop", reason=contract["expected_stop_reason"])
    return events, [preflight, opening], contract["expected_stop_reason"]


def dataset_invariants(path: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    ids = [row["id"] for row in rows]
    inputs = [" ".join(row["input"].casefold().split()) for row in rows]
    tuning = [row for row in rows if row["split"] == "tune"]
    holdout = [row for row in rows if row["split"] == "holdout"]
    difficulty_counts = {
        name: sum(row["difficulty"] == name for row in rows)
        for name in ("easy", "medium", "hard", "very-hard")
    }
    tuning_difficulty_counts = {
        name: sum(row["difficulty"] == name and row["split"] == "tune" for row in rows)
        for name in ("easy", "medium", "hard", "very-hard")
    }
    holdout_difficulty_counts = {
        name: sum(
            row["difficulty"] == name and row["split"] == "holdout" for row in rows
        )
        for name in ("easy", "medium", "hard", "very-hard")
    }
    tuning_output_counts = {
        name: sum(row["output"] == name for row in tuning)
        for name in ("billing", "cancellation", "technical-support")
    }
    holdout_output_counts = {
        name: sum(row["output"] == name for row in holdout)
        for name in ("billing", "cancellation", "technical-support")
    }
    if len(rows) != 28 or len(tuning) != 18 or len(holdout) != 10:
        raise ContractError(
            "generated dataset must contain 28 rows with an 18/10 split"
        )
    # This is also the tune/holdout leakage check, and the only one that can be:
    # the two splits partition all 28 rows, so distinct ids and distinct
    # normalized inputs across the whole file already make it impossible for a
    # row - or a restatement of one - to sit on both sides. The separate
    # id-overlap guard that used to follow was therefore unreachable, and
    # deleting it left the suite green; an unreachable check reads like leakage
    # coverage while providing none.
    if len(set(ids)) != 28 or len(set(inputs)) != 28:
        raise ContractError(
            "generated dataset ids and normalized inputs must be unique across "
            "both splits, so no row can appear in tuning and holdout alike"
        )
    if tuning_difficulty_counts != {
        "easy": 3,
        "medium": 5,
        "hard": 5,
        "very-hard": 5,
    }:
        raise ContractError(
            "generated dataset must contain 3 easy, 5 medium, 5 hard, and 5 very-hard tuning rows"
        )
    if holdout_difficulty_counts != {
        "easy": 2,
        "medium": 3,
        "hard": 3,
        "very-hard": 2,
    }:
        raise ContractError(
            "generated dataset must contain 2 easy, 3 medium, 3 hard, and 2 very-hard holdout rows"
        )
    if any(row.get("source") != "synthetic-walkthrough" for row in rows):
        raise ContractError("generated rows must retain walkthrough-only provenance")
    label_for_coverage = {
        "billing": "billing",
        "cancel": "cancellation",
        "technical": "technical-support",
    }
    allowed_labels = set(label_for_coverage.values())
    for row in rows:
        prefix = row["coverage"].split("-", 1)[0]
        if (
            row["output"] not in allowed_labels
            or label_for_coverage.get(prefix) != row["output"]
        ):
            raise ContractError(
                f"generated row {row['id']} has inconsistent label and coverage"
            )
    return {
        "rows": len(rows),
        "tuning": len(tuning),
        "holdout": len(holdout),
        "difficulty_counts": difficulty_counts,
        "tuning_difficulty_counts": tuning_difficulty_counts,
        "holdout_difficulty_counts": holdout_difficulty_counts,
        "tuning_output_counts": tuning_output_counts,
        "holdout_output_counts": holdout_output_counts,
        "coverage_branches": len({row["coverage"] for row in rows}),
        "provenance": "synthetic-walkthrough",
    }


def calibration_case_invariants(path: Path) -> None:
    cases = json.loads(path.read_text())
    expected_labels = {"billing", "cancellation", "technical-support"}
    if {case.get("expected") for case in cases} != expected_labels:
        raise ContractError("calibration cases must cover every declared intent label")
    for case in cases:
        if case.get("score_mode") != "binary":
            raise ContractError("support-intent calibration cases must use binary mode")
        if case.get("metadata", {}).get("branch") != case.get("expected"):
            raise ContractError(
                "calibration branch metadata must match the expected label"
            )


def partial_missing_dataset(
    contract: dict[str, Any], project: Path, audit_log: Path, scenario_dir: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    events: list[dict[str, Any]] = []
    expected = contract["assertions"]
    commands = [readiness_command(project, contract["starting_state"], audit_log)]
    plan = commands[0]["parsed"]
    if plan["create"] != ["dataset"] or plan["real_ready_count"] != 2:
        raise ContractError("partial readiness did not preserve the two real anchors")
    append_event(events, "readiness", real_ready=2, create=["dataset"])

    # Opening readiness gate: scored before anything is created or repaired, so
    # the closing score has an honest baseline to be measured against.
    opening_preflight = opening_preflight_command(project, audit_log)
    opening = score_command(project, audit_log, opening_preflight["stdout"])
    commands.extend((opening_preflight, opening))
    opening_score = opening["parsed"]
    opening_caps = cap_conditions(opening_score)
    if opening_score["overall"] != expected["opening_score"]:
        raise ContractError("partial scenario opening score violated its declaration")
    if not set(expected["opening_caps"]) <= set(opening_caps):
        raise ContractError("partial scenario opening score lost its required caps")
    append_event(events, "opening_readiness_score", **score_event_fields(opening_score))

    run_dir = project / "traigent-runs"
    gitignore = project / ".gitignore"
    original_gitignore = gitignore.read_text()
    if "traigent-runs/" not in original_gitignore.splitlines():
        separator = (
            "" if not original_gitignore or original_gitignore.endswith("\n") else "\n"
        )
        gitignore.write_text(f"{original_gitignore}{separator}traigent-runs/\n")
    generated = scenario_dir / "generated"
    dataset = run_dir / "evaluation-dataset.jsonl"
    cases = run_dir / "calibration-cases.json"
    shutil.copyfile(generated / "evaluation-dataset.jsonl", dataset)
    shutil.copyfile(generated / "calibration-cases.json", cases)
    calibration_case_invariants(cases)
    review = {
        "reviewer": "coding assistant",
        "evidence": ["task-contract.md", "agent.py", "evaluator.py"],
        "branches": ["billing", "cancellation", "technical-support"],
        "score_mode": "binary",
        "threshold_rationale": "Intent labels are nominal; normalized equivalent labels pass and other labels fail.",
        "verdict": "sufficient",
        "known_gap": "Synthetic walkthrough cases are not customer-traffic evidence.",
    }
    # The run record is written once, at the end, so it can carry the recorded
    # opening score beside the closing one without overwriting either.
    run_plan_lines = [
        "# Internal first-run record\n",
        "\n",
        "- Dataset provenance: synthetic walkthrough substitute; not production evidence.\n",
        "- Semantic coverage reviewer: coding assistant.\n",
        "- Evidence: task-contract.md, agent.py, evaluator.py.\n",
        "- Branches: billing, cancellation, technical-support.\n",
        "- Score mode: binary; normalized equivalent labels pass and other labels fail.\n",
        "- Semantic coverage verdict: sufficient for the workflow demonstration.\n",
        "- Known gap: synthetic cases do not represent customer traffic.\n",
        f"- Opening readiness score: {opening_score['overall']} "
        f"({opening_score['band']}); caps: {', '.join(opening_caps)}.\n",
    ]
    dataset_summary = dataset_invariants(dataset)
    append_event(events, "generated_dataset", **dataset_summary, production_ready=False)
    append_event(events, "semantic_review", **review)
    if not gitignore.read_text().startswith(original_gitignore):
        raise ContractError("existing .gitignore content was not preserved")

    preflight = run_command(
        [
            sys.executable,
            str(PREFLIGHT),
            "--env",
            str(project / ".env"),
            "--dataset",
            str(dataset),
            "--defer-missing-sdk",
            "--json",
        ],
        project,
        audit_log,
    )
    preflight["parsed"] = json.loads(preflight["stdout"])
    commands.append(preflight)
    if any(item["status"] == "FAIL" for item in preflight["parsed"]):
        raise ContractError("generated dataset failed static preflight")
    append_event(events, "static_preflight", passed=True, sdk="deferred")

    calibration = run_command(
        [
            sys.executable,
            str(CALIBRATE),
            "--scorer",
            "evaluator.py:score_intent",
            "--cases",
            f"@{cases}",
            "--allow-execution",
            "--json",
        ],
        project,
        audit_log,
    )
    calibration["parsed"] = json.loads(calibration["stdout"])
    commands.append(calibration)
    if not calibration["parsed"].get("passed"):
        raise ContractError("deterministic local evaluator calibration failed")
    (run_dir / "calibration-results.json").write_text(
        json.dumps(calibration["parsed"], indent=2, sort_keys=True) + "\n"
    )
    append_event(
        events,
        "local_calibration",
        passed=True,
        case_count=len(calibration["parsed"]["cases"]),
        provider_access=False,
    )

    # Closing readiness gate: re-scored on the post-creation, post-calibration
    # evidence, then reported beside the recorded opening score.
    closing = score_command(
        project,
        audit_log,
        preflight["stdout"],
        calibration=run_dir / "calibration-results.json",
    )
    commands.append(closing)
    closing_score = closing["parsed"]
    closing_caps = cap_conditions(closing_score)
    if not set(expected["closing_caps"]) <= set(closing_caps):
        raise ContractError("partial scenario closing score lost its required caps")
    if "evaluator-absent" in closing_caps or "evaluator-absent" not in opening_caps:
        raise ContractError(
            "the calibrated evaluator must clear the evaluator-absent cap it opened with"
        )
    if expected["closing_beats_opening"] != (
        closing_score["overall"] > opening_score["overall"]
    ):
        raise ContractError("readiness transition direction violated its declaration")
    run_plan_lines.append(
        f"- Latest revalidated readiness score: {closing_score['overall']} "
        f"({closing_score['band']}); caps: {', '.join(closing_caps)}.\n"
    )
    run_plan_lines.append(
        "- Readiness transition: the gain came from a `🛠️` synthetic substitute, "
        "not from real-world readiness.\n"
    )
    (run_dir / "run-plan.md").write_text("".join(run_plan_lines))
    append_event(
        events,
        "readiness_transition",
        opening=score_event_fields(opening_score),
        closing=score_event_fields(closing_score),
        caps_cleared=sorted(set(opening_caps) - set(closing_caps)),
        caps_remaining=sorted(set(closing_caps)),
        production_evidence=False,
    )
    append_event(
        events,
        "connected_boundary",
        customer_result=False,
        requires_live_validation=["sdk", "provider", "backend", "portal"],
    )
    append_event(events, "stop", reason=contract["expected_stop_reason"])
    return events, commands, contract["expected_stop_reason"]


def weak_invalid(
    contract: dict[str, Any], project: Path, audit_log: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    events: list[dict[str, Any]] = []
    commands = [readiness_command(project, contract["starting_state"], audit_log)]
    preflight = run_command(
        [
            sys.executable,
            str(PREFLIGHT),
            "--env",
            str(project / ".env"),
            "--dataset",
            str(project / "dataset.jsonl"),
            "--defer-missing-sdk",
            "--json",
        ],
        project,
        audit_log,
    )
    preflight["parsed"] = json.loads(preflight["stdout"])
    commands.append(preflight)

    # The opening readiness gate runs here too. This scenario stops at the
    # quality choice before any run record exists, so the score is held in the
    # conversation rather than written: `allowed_writes` stays empty.
    opening = score_command(project, audit_log, preflight["stdout"])
    commands.append(opening)
    opening_score = opening["parsed"]
    if opening_score["band"] != contract["assertions"]["opening_band"]:
        raise ContractError("weak/invalid opening band violated its declaration")
    append_event(events, "opening_readiness_score", **score_event_fields(opening_score))

    rows = [
        json.loads(line)
        for line in (project / "dataset.jsonl").read_text().splitlines()
    ]
    unique_inputs = {" ".join(row["input"].casefold().split()) for row in rows}
    evaluator_source = (project / "evaluator.py").read_text()
    if "output.strip() == expected.strip()" not in evaluator_source:
        raise ContractError(
            "weak evaluator fixture no longer demonstrates exact-string grading"
        )
    findings = [
        {
            "component": "agent",
            "evidence": "agent.py returns the same acknowledgement template with the raw message and implements no task-specific support behavior",
            "consequence": "Optimization has no meaningful existing behavior or controls to improve.",
        },
        {
            "component": "dataset",
            "evidence": f"{len(rows)} usable rows and {len(rows) - len(unique_inputs)} duplicate input(s); no holdout split",
            "consequence": "Each row dominates the score and repeated easy cases can hide ranking differences.",
        },
        {
            "component": "evaluation",
            "evidence": "evaluator.py requires exact free-form wording",
            "consequence": "Equivalent valid support replies can score zero, so optimization would reward wording rather than task quality.",
        },
    ]
    append_event(events, "quality_findings", findings=findings)
    append_event(
        events,
        "question",
        category="quality_decision",
        choices=["repair", "workflow demonstration", "pause"],
        recommended="repair",
    )
    append_event(events, "stop", reason=contract["expected_stop_reason"])
    return events, commands, contract["expected_stop_reason"]


def read_audit_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def protected_hashes(project: Path, paths: list[str]) -> dict[str, dict[str, Any]]:
    return {
        relative: (
            tree_manifest(project / relative)
            if (project / relative).is_dir()
            else {
                "sha256": sha256_bytes((project / relative).read_bytes()),
                "mode": stat.S_IMODE((project / relative).stat().st_mode),
            }
        )
        for relative in paths
    }


def writes_a_report(commands: list[dict[str, Any]]) -> bool:
    """Report whether any recorded command asks a script to write a report file.

    Scan the arguments themselves, not the argv list: argparse also accepts
    `--report=<path>`, and a membership test on the list misses that form
    entirely. The report path can point outside the project, where neither the
    read-only chmod nor the writes snapshot would catch the file, so this is the
    only place the rule can be enforced - and it must be the only definition of
    it, or a caller and its test can drift apart.
    """
    return any(
        argument == "--report" or argument.startswith("--report=")
        for command in commands
        for argument in command["argv"]
    )


def validate_semantics(contract: dict[str, Any], evidence: dict[str, Any]) -> None:
    if evidence["stop_reason"] != contract["expected_stop_reason"]:
        raise ContractError("scenario stopped at the wrong gate")
    if evidence["network"]["attempts"]:
        raise ContractError("scenario attempted network access")
    if any(event["type"] in FORBIDDEN_ACTIONS for event in evidence["events"]):
        raise ContractError("scenario emitted a forbidden external/result action")
    stop_indexes = [
        index
        for index, event in enumerate(evidence["events"])
        if event["type"] == "stop"
    ]
    if stop_indexes != [len(evidence["events"]) - 1]:
        raise ContractError("scenario must emit exactly one terminal stop event")
    # Every scenario, not only the zero-anchor one: a report flag added to any
    # recorded command writes a file that can land outside the project tree,
    # where the writes snapshot still certifies `writes: []`.
    if writes_a_report(evidence["commands"]):
        raise ContractError("recorded commands must not write a report file")
    if contract["id"] == "zero-anchor":
        questions = [
            event for event in evidence["events"] if event["type"] == "question"
        ]
        expected = contract["assertions"]
        if (
            len(questions) != expected["question_count"]
            or questions[0].get("category") != expected["question_category"]
        ):
            raise ContractError("zero-anchor must ask exactly one task-intent question")
        if evidence["writes"]:
            raise ContractError(
                "zero-anchor must perform no project writes before the answer"
            )
        # The opening readiness gate is mandatory even here, so the blanket
        # no-commands rule is replaced by an exact allowlist: the read-only
        # preflight/readiness pair, in that order, and nothing else.
        scripts = [Path(command["argv"][1]).name for command in evidence["commands"]]
        if scripts != expected["opening_commands"]:
            raise ContractError(
                "zero-anchor may run only the opening preflight/readiness pair "
                "before the answer"
            )
        score = next(
            event
            for event in evidence["events"]
            if event["type"] == "opening_readiness_score"
        )
        if (
            score["overall"] != expected["opening_score"]
            or score["band"] != expected["opening_band"]
        ):
            raise ContractError("zero-anchor opening score violated its declaration")
        if not set(expected["opening_caps"]) <= set(score["caps"]):
            raise ContractError("zero-anchor opening score lost its required caps")
        if len(evidence["writes"]) != expected["project_writes"]:
            raise ContractError("zero-anchor write count violated its declaration")
    elif contract["id"] == "partial-missing-dataset":
        generated = next(
            event
            for event in evidence["events"]
            if event["type"] == "generated_dataset"
        )
        expected = contract["assertions"]
        if (
            generated["rows"] != expected["dataset_rows"]
            or generated["tuning"] != expected["tuning_rows"]
            or generated["holdout"] != expected["holdout_rows"]
            or generated["tuning_difficulty_counts"]
            != expected["tuning_difficulty_counts"]
            or generated["holdout_difficulty_counts"]
            != expected["holdout_difficulty_counts"]
            or generated["tuning_output_counts"] != expected["tuning_output_counts"]
            or generated["holdout_output_counts"] != expected["holdout_output_counts"]
        ):
            raise ContractError(
                "partial scenario dataset counts violated its declaration"
            )
        if (
            generated["production_ready"]
            or generated["provenance"] != expected["provenance"]
        ):
            raise ContractError("generated substitute was presented as real readiness")
        semantic_review = next(
            event for event in evidence["events"] if event["type"] == "semantic_review"
        )
        calibration = next(
            event
            for event in evidence["events"]
            if event["type"] == "local_calibration"
        )
        if semantic_review["verdict"] != expected["semantic_review"]:
            raise ContractError(
                "partial scenario semantic review violated its declaration"
            )
        if calibration["passed"] != (expected["calibration"] == "pass"):
            raise ContractError("partial scenario calibration violated its declaration")
        if evidence["protected_before"] != evidence["protected_after"]:
            raise ContractError("partial scenario changed an existing real component")
    elif contract["id"] == "weak-invalid":
        findings = next(
            event for event in evidence["events"] if event["type"] == "quality_findings"
        )["findings"]
        declared_problem_components = {
            component
            for component, state in contract["starting_state"].items()
            if state in {"limited", "invalid"}
        }
        if {
            finding["component"] for finding in findings
        } != declared_problem_components:
            raise ContractError(
                "every limited or invalid component needs a concrete quality finding"
            )
        event_types = {event["type"] for event in evidence["events"]}
        assertions = contract["assertions"]
        if ("provider_call" in event_types) != assertions["provider_work"]:
            raise ContractError("provider-work evidence contradicted its declaration")
        if ("paid_work" in event_types) != assertions["paid_work"]:
            raise ContractError("paid-work evidence contradicted its declaration")
        choices = next(
            event for event in evidence["events"] if event["type"] == "question"
        )
        if choices["choices"] != contract["assertions"]["quality_choices"]:
            raise ContractError(
                "weak/invalid scenario must offer the three quality choices"
            )


def write_evidence_bundle(
    evidence: dict[str, Any], directory: Path, project: Path
) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    for name, values in (
        ("events.jsonl", evidence["events"]),
        ("commands.jsonl", evidence["commands"]),
    ):
        (directory / name).write_text(
            "".join(canonical_json(value) + "\n" for value in values)
        )
    (directory / "evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    )
    transcript = []
    for event in evidence["events"]:
        summary = event.get("reason") or event.get("category") or event["type"]
        transcript.append(f"{event['sequence']:02d} {event['type']}: {summary}")
    (directory / "transcript.txt").write_text("\n".join(transcript) + "\n")
    artifacts = directory / "artifacts"
    for relative in evidence["writes"]:
        source = project / relative
        if source.is_file():
            destination = artifacts / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)


def run_once(
    scenario_dir: Path,
    pass_number: int,
    work_root: Path,
    evidence_root: Path,
    network_probe: dict[str, str],
) -> dict[str, Any]:
    contract = load_contract(scenario_dir)
    validate_contract_shape(contract, scenario_dir)
    verify_fixture_lock(scenario_dir)
    fixture_before = tree_manifest(scenario_dir / "seed")
    project = work_root / f"pass-{pass_number}" / contract["id"]
    project.parent.mkdir(parents=True, exist_ok=True)
    seed = scenario_dir / "seed"
    if seed.exists():
        shutil.copytree(seed, project)
    else:
        project.mkdir()
    enforce_project_permissions(project, contract["allowed_writes"])
    before = tree_manifest(project)
    protected_before = protected_hashes(project, contract["preserve"])
    audit_log = work_root / f"audit-{contract['id']}-{pass_number}.jsonl"

    if contract["id"] == "zero-anchor":
        events, commands, stop_reason = zero_anchor(contract, project, audit_log)
    elif contract["id"] == "stub-agent-no-anchor":
        events, commands, stop_reason = stub_agent_no_anchor(
            contract, project, audit_log
        )
    elif contract["id"] == "partial-missing-dataset":
        events, commands, stop_reason = partial_missing_dataset(
            contract, project, audit_log, scenario_dir
        )
    elif contract["id"] == "weak-invalid":
        events, commands, stop_reason = weak_invalid(contract, project, audit_log)
    else:
        raise ContractError(f"unknown scenario: {contract['id']}")

    after = tree_manifest(project)
    writes = manifest_changes(before, after)
    validate_writes(contract, writes)
    protected_after = protected_hashes(project, contract["preserve"])
    fixture_after = tree_manifest(scenario_dir / "seed")
    if fixture_before != fixture_after:
        raise ContractError("immutable source fixture changed during the run")
    evidence = {
        "schema_version": 1,
        "kind": "offline-behavioral-contract",
        "scenario": contract["id"],
        "claim_scope": "pre-network orchestration only; not a customer optimization result",
        "behavior_digest": behavior_manifest()["digest"],
        "fixture_manifest": fixture_before,
        "events": events,
        "commands": commands,
        "network": {
            "kernel_probe": network_probe,
            "attempts": read_audit_events(audit_log),
        },
        "writes": writes,
        "artifacts": {
            entry["path"]: entry for entry in after if entry["path"] in writes
        },
        "protected_before": protected_before,
        "protected_after": protected_after,
        "stop_reason": stop_reason,
        "live_validation_required": [
            "coding-assistant interpretation",
            "installed SDK",
            "provider and backend",
            "cost and quota",
            "portal persistence and links",
            "visible baseline, enhanced, and holdout results",
        ],
    }
    validate_semantics(contract, evidence)
    write_evidence_bundle(
        evidence, evidence_root / contract["id"] / f"pass-{pass_number}", project
    )
    return evidence


def require_isolation() -> dict[str, str]:
    if os.environ.get("TRAIGENT_OFFLINE_ISOLATED") != "1":
        raise ContractError(
            "refusing to run behavioral qualification without the isolated-container sentinel"
        )
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "TRAIGENT_API_KEY",
    ):
        if os.environ.get(name):
            raise ContractError(
                f"provider credential leaked into isolated harness: {name}"
            )
    return kernel_network_probe()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run internal offline first-run contract scenarios."
    )
    parser.add_argument(
        "--all", action="store_true", help="run all committed scenarios twice"
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(path.name for path in SCENARIOS.iterdir() if path.is_dir()),
    )
    parser.add_argument("--evidence-dir", type=Path, default=Path("/work/evidence"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.all and not args.scenario:
        raise ContractError("select --all or --scenario")
    network_probe = require_isolation()
    selected = sorted(path for path in SCENARIOS.iterdir() if path.is_dir())
    if args.scenario:
        selected = [SCENARIOS / args.scenario]
    with tempfile.TemporaryDirectory(prefix="traigent-contract-") as directory:
        work_root = Path(directory)
        summaries = []
        for scenario_dir in selected:
            first = run_once(
                scenario_dir, 1, work_root, args.evidence_dir, network_probe
            )
            second = run_once(
                scenario_dir, 2, work_root, args.evidence_dir, network_probe
            )
            if first != second:
                raise ContractError(
                    f"scenario is not reproducible: {scenario_dir.name}"
                )
            summaries.append(
                {
                    "scenario": scenario_dir.name,
                    "stop_reason": first["stop_reason"],
                    "writes": first["writes"],
                    "evidence_sha256": sha256_bytes(canonical_json(first).encode()),
                }
            )
    print(
        json.dumps(
            {"passed": True, "scope": "offline contract only", "scenarios": summaries},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as error:
        print(f"OFFLINE CONTRACT FAILURE: {error}", file=sys.stderr)
        raise SystemExit(1)

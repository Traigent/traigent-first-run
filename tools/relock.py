#!/usr/bin/env python3
"""Regenerate the behavior lock and the scenario fixture locks.

Both locks are generated artifacts: the behavior lock hashes `GUIDE.md` plus
every file under `skills/traigent-first-run/`, and each fixture lock hashes one
scenario's `seed/` and `generated/` trees. Any edit to those inputs makes the
committed lock stale, and the offline contract tests fail until it is rewritten.

Regenerating by hand is error-prone in two specific ways this tool removes:

* The hashing lives in `tests/behavioral/harness.py`. This tool imports it
  rather than reimplementing it, so the tool and the tests can never disagree.
* Both locks use a compact one-entry-per-line layout that `json.dumps(indent=2)`
  does not reproduce. Rewriting with the default formatter reflows every entry
  and buries the real change in noise, so the layout is reproduced here.

File modes are written through `harness.git_tracked_mode`, which keeps only the
permission bits git can actually reproduce on checkout. Without that, whoever
regenerates bakes in their own umask (0664 under `umask 0002` against 0644 under
`umask 022`) and the lock breaks for everyone else.

A third error this tool now removes: writing a lock over an unresolved merge
index. `git ls-files` lists a conflicted path once per merge stage, so the lock
gained one entry per stage and still exited 0 printing `rewrote` - 15 entries
for 13 files, with `glossary.md` hashed three times (#198). The moment anyone
wants to relock is exactly the moment the index is dirty, because every merge of
this repository conflicts on `behavior.lock.json` itself, and the corruption
does not surface until the *next* honest run, where it reads as "someone changed
a behaviour" rather than "the lock was written wrong".

Usage:
    python tools/relock.py                    # rewrite any stale lock
    python tools/relock.py --check            # report staleness, write nothing (exit 1)
    python tools/relock.py --allow-unmerged   # write anyway from a conflicted index
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from behavioral import harness  # noqa: E402  (needs the path insert above)
from behavioral import outcomes  # noqa: E402  (needs the path insert above)

BEHAVIOR_LOCK = ROOT / "tests" / "behavioral" / "behavior.lock.json"
SCENARIOS = ROOT / "tests" / "behavioral" / "scenarios"


def _entry_line(entry: dict[str, Any], *, last: bool) -> str:
    rendered = json.dumps(entry, sort_keys=True, separators=(", ", ": "))
    return f"    {rendered}" + ("" if last else ",")


def _render_entries(entries: list[dict[str, Any]]) -> list[str]:
    return [
        _entry_line(entry, last=index == len(entries) - 1)
        for index, entry in enumerate(entries)
    ]


def format_behavior_lock(manifest: dict[str, Any]) -> str:
    lines = ["{", f'  "digest": "{manifest["digest"]}",', '  "paths": [']
    lines.extend(_render_entries(manifest["paths"]))
    lines.extend(["  ],", f'  "schema_version": {manifest["schema_version"]}', "}"])
    return "\n".join(lines) + "\n"


def format_fixture_lock(payload: dict[str, Any]) -> str:
    lines = ["{"]
    for key in ("generated", "schema_version", "seed"):
        value = payload[key]
        if key == "schema_version":
            lines.append(f'  "schema_version": {value},')
            continue
        if not value:
            lines.append(f'  "{key}": [],')
            continue
        lines.append(f'  "{key}": [')
        lines.extend(_render_entries(value))
        lines.append("  ],")
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines) + "\n"


def normalized_tree(root: Path) -> list[dict[str, Any]]:
    """Tree manifest with modes reduced to the bits git can reproduce."""
    entries = harness.tree_manifest(root)
    return [
        (
            {**entry, "mode": harness.git_tracked_mode(entry["mode"])}
            if isinstance(entry.get("mode"), int)
            else entry
        )
        for entry in entries
    ]


def fixture_payload(scenario_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "seed": normalized_tree(scenario_dir / "seed"),
        "generated": normalized_tree(scenario_dir / "generated"),
    }


def format_outcome_lock(manifest: dict[str, Any]) -> str:
    """One line per recorded field, so a changed band is a one-line diff.

    `json.dumps(indent=2)` would put every cap flag on its own line and turn a
    band change into a diff hunk the reviewer has to reassemble. The point of
    this lock is that the change is readable, so the rendering is part of it.
    """
    lines = ["{", '  "cases": {']
    identifiers = sorted(manifest["cases"])
    for index, identifier in enumerate(identifiers):
        entry = manifest["cases"][identifier]
        lines.append(f'    "{identifier}": {{')
        lines.append(f'      "state": {json.dumps(entry["state"])},')
        lines.append('      "outcome": {')
        outcome = entry["outcome"]
        for field in outcomes.RECORDED_FIELDS:
            lines.append(f'        "{field}": {json.dumps(outcome[field])},')
        caps = outcome["caps"]
        if not caps:
            lines.append('        "caps": []')
        else:
            lines.append('        "caps": [')
            for position, cap in enumerate(caps):
                rendered = json.dumps(cap, sort_keys=True, separators=(", ", ": "))
                comma = "" if position == len(caps) - 1 else ","
                lines.append(f"          {rendered}{comma}")
            lines.append("        ]")
        lines.append("      }")
        lines.append("    }" + ("" if index == len(identifiers) - 1 else ","))
    lines.append("  },")
    lines.append(f'  "schema_version": {manifest["schema_version"]}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def targets() -> list[tuple[Path, str]]:
    """Return every (lock path, desired content) pair, sorted by path."""
    planned = [(BEHAVIOR_LOCK, format_behavior_lock(harness.behavior_manifest(ROOT)))]
    for scenario_dir in sorted(path for path in SCENARIOS.iterdir() if path.is_dir()):
        planned.append(
            (
                scenario_dir / "fixture.lock.json",
                format_fixture_lock(fixture_payload(scenario_dir)),
            )
        )
    # Written here so there is one command that refreshes every lock, and so
    # `--check` covers this one too. What it must NOT write is any case's
    # declared expectation: that is the half a regeneration cannot move, and it
    # is why regenerating this lock does not re-green a real change (#153).
    planned.append(
        (outcomes.OUTCOME_LOCK, format_outcome_lock(outcomes.outcome_manifest()))
    )
    return planned


def unmerged_paths() -> list[str]:
    """Paths git reports as carrying unresolved merge stages, deduplicated.

    `git ls-files --unmerged` prints one row per stage - `<mode> <object>
    <stage>\\t<path>` - so a single content conflict appears three times. The
    paths are what a reader has to act on, so the stages are collapsed here.

    Returns an empty list when git is absent, mirroring
    `harness.behavior_files`: a checkout with no git has no index, so there is
    no conflicted index to refuse. A git *error* is raised rather than read as
    "clean", because a guard that answers "no conflicts" when it could not look
    is worse than no guard.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--unmerged", "-z"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, NotADirectoryError):
        return []
    if result.returncode != 0:
        raise RuntimeError(
            "could not list the unmerged paths from git "
            f"(exit {result.returncode}): {result.stderr.strip()}"
        )
    paths = set()
    for record in result.stdout.split("\0"):
        if not record:
            continue
        _, _, path = record.partition("\t")
        if path:
            paths.add(path)
    return sorted(paths)


def unmerged_state(paths: list[str]) -> str:
    """One line naming what is unresolved, or the empty string when nothing is."""
    if not paths:
        return ""
    return (
        f"unmerged: {len(paths)} path(s) with unresolved merge stages "
        f"({', '.join(paths)})"
    )


def refuse_unmerged_index(allow: bool) -> str:
    """Refuse to write a lock over an index with unresolved merge stages.

    Warn-and-allow would not help: the write is the damaging act, and a warning
    printed by a command that exits 0 goes unread - that is precisely how the
    15-entry lock reached a branch. But relocking mid-merge is a legitimate
    thing to want, so `--allow-unmerged` exists, named after the flag a sibling
    snapshot tool already carries for the same reason (#198): one vocabulary
    for one refusal, so what a reader learns here transfers.

    Returns the state string when the write is permitted anyway (so the caller
    can say what it wrote over) and raises `SystemExit` otherwise.
    """
    state = unmerged_state(unmerged_paths())
    if not state:
        return ""
    if allow:
        return state
    print(
        f"{state} -- refusing to write a lock over an index that does not "
        f"give one resolved content per path. Git lists a conflicted path once "
        f"per merge stage, so the lock would hash it once per stage and then "
        f"fail on the next honest run as if a behaviour had changed. Resolve "
        f"the conflict and stage it first. --allow-unmerged writes anyway for "
        f"an explicit, deliberate regeneration; it never makes the result a "
        f"measurement.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate the behavior and fixture locks."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report stale locks without writing (exit 1 when stale)",
    )
    parser.add_argument(
        "--allow-unmerged",
        action="store_true",
        help="writing only: regenerate from a conflicted index anyway, and say so",
    )
    args = parser.parse_args()

    if args.allow_unmerged and args.check:
        # Accepting it here would do nothing - --check never refuses an index -
        # and a flag that is accepted and ignored reads as a suppression that
        # worked.
        print(
            "--allow-unmerged applies to writing only. --check already accepts "
            "any index; it just says in a NOTE what the index is.",
            file=sys.stderr,
        )
        return 2

    if args.check:
        # --check writes nothing, so any index is a legitimate thing to check
        # against - but staleness reported from a conflicted index describes the
        # conflict markers in the working tree, not a stale lock, and reads
        # identically to the real thing. Say what the index is up front.
        state = unmerged_state(unmerged_paths())
        if state:
            print(
                f"NOTE: {state} -- any staleness below describes that, not the "
                f"committed lock.",
                file=sys.stderr,
            )
    else:
        state = refuse_unmerged_index(args.allow_unmerged)
        if state:
            print(f"NOTE: {state} -- written under --allow-unmerged.", file=sys.stderr)

    stale: list[Path] = []
    for path, desired in targets():
        current = path.read_text() if path.exists() else None
        if current == desired:
            continue
        stale.append(path)
        if not args.check:
            path.write_text(desired)

    if not stale:
        print("locks are up to date")
        return 0

    verb = "stale" if args.check else "rewrote"
    for path in stale:
        print(f"{verb}: {path.relative_to(ROOT)}")
    if args.check:
        print("run `python tools/relock.py` to regenerate", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

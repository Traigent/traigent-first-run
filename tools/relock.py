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

Usage:
    python tools/relock.py            # rewrite any stale lock
    python tools/relock.py --check    # report staleness, write nothing (exit 1)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from behavioral import harness  # noqa: E402  (needs the path insert above)

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
    return planned


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate the behavior and fixture locks."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report stale locks without writing (exit 1 when stale)",
    )
    args = parser.parse_args()

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

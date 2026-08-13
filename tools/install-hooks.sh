#!/usr/bin/env bash
# Point git at this repository's versioned hooks.
#
# Run once per clone. `.git/hooks` is not versioned, so a hook committed there
# reaches nobody; `core.hooksPath` is the setting that makes a checked-in hook
# actually run.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

existing="$(git config --local --get core.hooksPath || true)"
if [ -n "$existing" ] && [ "$existing" != ".githooks" ]; then
  echo "core.hooksPath is already set to '$existing'; leaving it alone." >&2
  exit 1
fi

# This REPLACES .git/hooks rather than adding to it, so anything already there
# stops running. There is nothing in .git/hooks by default; if you put something
# there yourself, move it into .githooks/ first.
git config --local core.hooksPath .githooks
echo "hooks enabled: $(git config --local --get core.hooksPath)"
echo "the lock now regenerates and stages itself on every commit."

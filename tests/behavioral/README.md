# Offline behavioral-contract harness

This internal test layer verifies only the deterministic, pre-network portion of the first-run
contract. It checks the zero-anchor stop, preservation and generated-dataset invariants, local
calibration, evidence-based quality findings, allowed writes, external-action boundaries, the
mandatory opening readiness score, cap-directed branching, and the recorded opening-to-closing
transition.

It is not a customer walkthrough, an SDK/provider/backend test, or proof that an arbitrary coding
assistant follows the skill. It emits no optimization result, cost, or portal link. A failed live
connection must remain a visible failure; production onboarding must never fall back to this
harness.

CI runs every scenario twice as an unprivileged user in a read-only container with no network.
The fixture locks protect the three starting states, and `behavior.lock.json` makes changes to the
behavior-bearing guide, references, assets, or scripts require explicit scenario requalification.

## Regenerating the locks

Both locks are generated artifacts. After editing `GUIDE.md`, anything under
`skills/traigent-first-run/`, or a scenario `seed/`/`generated/` tree, rewrite them:

```bash
python tools/relock.py            # rewrite any stale lock
python tools/relock.py --check    # report staleness, write nothing (exit 1)
```

Never hand-edit a lock, and never resolve a lock merge conflict by taking a side - each side keeps
stale hashes for the other's files and a digest matching neither. Take either version, then re-run
`tools/relock.py`.

The locks record only the permission bits git can reproduce on checkout, i.e. the owner-execute bit.
Every other bit comes from the checking-out user's umask, so storing the full mode made the locks
fail for any contributor whose umask differed from the one that wrote them.

## Running the container job locally

```bash
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 128 --user 65534:65534 \
  -e TRAIGENT_OFFLINE_ISOLATED=1 -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/repo:ro" \
  --tmpfs /work:rw,exec,nosuid,nodev,uid=65534,gid=65534,mode=0700 \
  --tmpfs /tmp:rw,exec,nosuid,nodev,uid=65534,gid=65534,mode=0700 \
  -w /repo python:3.12-slim \
  python tests/behavioral/harness.py --all --evidence-dir /work/evidence
```

This is the only gate that catches control characters in script output (`clean_capture` rejects ANSI
escapes) and cross-pass nondeterminism, so run it before pushing anything that changes the three
allowlisted scripts.

The connected staging smoke test remains responsible for SDK compatibility, real provider and
Traigent calls, cost/quota behavior, visible baseline and enhanced trials, holdout reporting,
portal persistence, and direct experiment links.

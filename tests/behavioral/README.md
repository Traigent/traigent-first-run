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
The fixture locks protect the committed starting states.

## Fixture locks and declared outcomes

Each scenario under `scenarios/` commits a `fixture.lock.json` recording the sha256 of every file
in its `seed/` and `generated/` trees. The container job has no git to compare against, so the lock
is what lets it prove the starting state it measures is the one that was reviewed.

What the free chain `preflight.py | calibrate_evaluator.py | readiness.py` actually *decides* for
the committed inputs under `outcomes/` - the band, the status, the recommended action, and the caps
with their `blocks`/`asks` routing - is declared by hand in each case's `case.json`, in an
`expected` block that no tool writes. The suite runs the chain fresh and compares it to that
declaration, so a change that alters what a customer is told fails as a diff of that card, naming
the thing that moved.

There are four cases because the score's own output selection has four states, not because four
felt like enough. `recommended_action` has exactly three arms - the first blocking cap, else the
first asking cap, else `proceed` - and `status` is `BLOCKED` exactly when a blocking cap exists. The
cases are one `clean`, one `blocked`, one `advisory` and one `asking`, which is every arm and both
statuses.

**No generated artifact exists whose regeneration makes a real failure vanish.** The repository
used to commit two - a hash lock over every behavior-bearing file, and a generated copy of the
recorded outcome cards - and retired both: the hash lock compared hashes to hashes, so one command
re-greened any failure it ever raised (#153), and the outcome copy restated the declarations
byte-for-byte. Updating a case legitimately means editing its `expected` declaration on purpose and
saying why; there is no command that does it for you.
`test_a_refreshed_manifest_cannot_hide_a_changed_band` is that claim, executed.

## Running the suite

```bash
python -m unittest discover -s tests -v    # or: python -m pytest tests/ -q
```

`CI` is load-bearing here, not decoration: when it is set to any non-empty value,
`tests/test_offline_socket_contract.py` fails instead of skipping if `litellm` or `traigent` is
missing, because in CI that module *is* the no-spend guarantee and a skip would retire it silently.
Many agent sandboxes and devcontainers export `CI=true` by default, so a maintainer without the
pinned stack installed should unset it (`env -u CI python -m pytest tests/ -q`) or install
`skills/traigent-first-run/assets/requirements-first-run.txt` first.

## Regenerating the fixture locks

The fixture locks are generated artifacts. After editing a scenario `seed/` or `generated/` tree,
rewrite them:

```bash
python tools/relock.py                   # rewrite any stale lock
python tools/relock.py --check           # report staleness, write nothing (exit 1)
python tools/relock.py --allow-unmerged  # write from a conflicted index anyway
```

Never hand-edit a lock, and never resolve a lock merge conflict by taking a side - each side keeps
stale hashes for the other's files. Take either version, **stage the resolution**, then re-run
`tools/relock.py`.

Staging is not a formality. Mid-merge, a conflicted file's working-tree content is the conflict
markers, so a lock written over an unresolved index hashes the markers as if they were the fixture -
exit 0, `rewrote`, and the corruption surfaces only on the next honest run, reading as "someone
changed a fixture" (#198 was the retired behaviour lock's form of the same mistake). The tool
refuses an index with unresolved paths and names them. `--allow-unmerged` writes anyway and says in
the output what it wrote over, for the deliberate case; it does not make the result a measurement.

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

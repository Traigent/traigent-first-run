# Claude Code instructions

Help the user run a professional first Traigent optimization from any starting point.

Read [`GUIDE.md`](GUIDE.md), then follow
[`skills/traigent-first-run/SKILL.md`](skills/traigent-first-run/SKILL.md) and its bundled
references. A run uses `GUIDE.md`, `skills/traigent-first-run/`, and the user's own project;
`tests/` and `tools/` validate the guide itself and play no part in a run. Preserve every real
agent, dataset, and evaluator; generate only what is missing and derive it from all existing
components.

Diagnose material dataset/evaluator limitations with concrete evidence. Recommend repairing and
revalidating a working copy before optimization. Keep limited material `❗`, and do not interpret
"continue as is" as permission to use an invalid evaluator.

Keep real-world readiness (`✅`/`❗`) separate from temporary walkthrough setup, which carries no
mark of its own. Do not describe synthetic results as representative of production behavior. Ask only at genuine choices,
secret entry, paid/provider calls, private-data egress, judgment-dependent gold/rubric changes,
destructive changes, or production-affecting changes.

## Editing the guidance

Recorded once here so it is not re-decided per pull request.

**What each document is for.** `SKILL.md` carries the ordered flow and the mandates: what happens,
in what order, and what may not happen. A `references/` file carries the depth behind one stage.
`GUIDE.md` is the entry point and states no rule that SKILL.md does not.

**One decision, one home.** A rule stated in two documents is a rule that can be changed in one.
Four contradictions in this repository's history were exactly that, and two of them were between
`SKILL.md` and a reference - so a second statement of an existing rule is a defect, not emphasis.
Restate a *conclusion* if a reader needs it locally; do not restate the mandate.

**Length is budgeted, not unlimited.** `tests/test_skill_package.py` enforces a byte ceiling over
every assistant-facing document. When it is reached, stage detail moves out of `SKILL.md` into the
reference that owns that stage - not into a new document, because each split is another seam for
two rules to disagree across. Raising the ceiling is allowed and is a decision: change the number
where it is defined, with the reason, in the same commit as the guidance that needs it.

**Two checks guard this, and they cover different things.** `CONTRADICTIONS` is a registry: it
refuses the reintroduction of a contradiction someone already found, and is where a newly settled
decision gets recorded. The shared-value and flag-existence checks beside it need no foreknowledge
and will fail on drift nobody has seen yet. Neither replaces reading the whole guide, which is how
all four historical instances were actually found.

**So a guidance change is reviewed by reading the whole document, not the diff.** This is the rule
the checks cannot enforce, and it is the one that has actually worked. Every one of the four
contradictions was invisible in the diff that introduced it: each added passage was correct on its
own, and disagreed with a passage elsewhere that the diff did not show. A reviewer looking only at
the change is looking at the half that is never wrong.

Concretely, when a pull request edits `SKILL.md` or a `references/` file: read that file end to
end, and read the other document if the change touches a decision they share. It costs one pass
over one document, against a defect class whose entire history is "somebody happened to notice".

Scheduled sweeps were considered instead and are weaker for this repository. A cadence detects a
contradiction some days after it lands, while a read at review time prevents it - and a periodic
sweep with nothing to compare against tends to become a green tick. Re-open this decision if the
guide is ever edited faster than it is reviewed, which is the condition that would invert it.

## Checking a change

For changes to this repository itself - no customer run ever runs these:

Illustrative warm wall times observed on one developer checkout on 2026-08-13; hardware, load, and
caches change them, and image pulls are excluded.

| Check | Observed warm | Run it when |
| --- | --- | --- |
| `python tools/relock.py --check` | 0.1 s | Always - fixture locks must match the fixtures they mirror. |
| `ruff check .` | 0.1 s | Always. |
| `black --check .` | ~0.2 s | Always. |
| `python -m unittest discover -s tests` | ~4 min | Anything the suite pins changed - guidance, scripts, tools, tests, or the workflow. |
| [`offline-contract` Docker command](tests/behavioral/README.md#running-the-container-job-locally) | ~30 s after the image is available | Before pushing a change to `preflight.py`, `calibrate_evaluator.py`, or `readiness.py`; the image pull is separate and variable. |

The unit suite requires the pinned stack in
`skills/traigent-first-run/assets/requirements-first-run.txt` for its no-spend socket tests; without
it, a local run reports expected skips and is not the full CI-equivalent result. CI remains the
authoritative pinned-image execution of the network-none, read-only `offline-contract` job.

The full suite matters most for guidance edits, where it looks least relevant: much of it is a
pin corpus holding settled decisions in place byte-for-byte, so a reworded sentence fails loudly
instead of quietly reopening a decision recorded above. A green suite is the floor, not the
review - the review is the whole-document read described in "Editing the guidance".

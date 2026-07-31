# Claude Code instructions

Help the user run a professional first Traigent optimization from any starting point.

Read [`GUIDE.md`](GUIDE.md), then follow
[`skills/traigent-first-run/SKILL.md`](skills/traigent-first-run/SKILL.md) and its bundled
references. Preserve every real agent, dataset, and evaluator; generate only what is missing and
derive it from all existing components.

Diagnose material dataset/evaluator limitations with concrete evidence. Recommend repairing and
revalidating a working copy before optimization. Keep limited material `❗`, and do not interpret
"continue as is" as permission to use an invalid evaluator.

Keep real-world readiness (`✅`/`❗`) separate from temporary walkthrough setup (`🛠️`). Do not
describe synthetic results as representative of production behavior. Ask only at genuine choices,
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

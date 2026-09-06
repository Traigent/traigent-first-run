# 0095 - the three words bind every calibration

follows: 0094
follows-resident-measured: 106_368
follows-total-measured: 498_243
follows-document-measured: 136_303
resident-ceiling: 106_500
resident-measured: 106_371
total-ceiling: 498_300
total-measured: 498_266
document-ceiling: 137_550
document-measured: 136_303

Twenty-three bytes over two documents, and neither adds a rule: both correct a sentence that had
stopped being true.

Twenty of them are in `references/run-safety.md`. Its deterministic-calibration paragraph opened
"Before environment setup, run only a non-executing evaluator whose complete call path is
local-only, side-effect-free, and standard-library-only", which reads as a precondition satisfied
once on the way in. The state that exposes the gap is a calibration that finished and did not pass:
the evaluator has been imported and executed, the run is routed to repair it, and the repaired path
is calibrated again with nothing re-establishing the three words over it. A repair that pulls in an
installed dependency, or that reaches a provider client at module import, meets none of them and met
no gate on the way back in (traigent-first-run#397). The paragraph now opens "Before every
calibration this stage performs", which is what the issue asked for and what `SKILL.md` section 4
has said all along - "Before calibration, apply `references/run-safety.md`'s execution-evaluator
scope gate". The reference was the half that disagreed, so the reference is the half that moved; the
mandate was not restated in `SKILL.md`, which would have given one rule a second home.

"This stage" and not "this run", because the wider word forbade a calibration `SKILL.md` section 5
step 5 mandates. The same paragraph sends an evaluator that needs a declared local dependency away
to wait for the install, and the deferred calibration that follows has a call path which is, after
that install and by construction, not standard-library-only - so "every calibration this run
performs" bound a step it could never satisfy and named no remedy. The rule now binds every
calibration at the stage where the three words can hold, which is the stage a
re-calibration-after-repair happens in, and it gives "the same three words bind anything else this
stage imports" two sentences later the antecedent it lost when "environment setup" was deleted. The
decision is recorded in `CONTRADICTIONS` rather than only in a local assertion, since it was settled
twice in opposite directions.

The other three are in `SKILL.md`, and they retire a claim this change made false. It said the
scope-refusal flag "moves no number, because nothing here can check it". The second half was the
load-bearing one, and `readiness.py` now derives that same state from preflight's engine witness
with no flag passed at all, so the sentence denied a check the module performs.

Replacing it with "preflight's witness reaches the same state without it" over-corrected: measured
on an evaluator reaching its engine through a helper module - one of the two shapes the reference
names as invisible to the walk - the states are not the same at all. Without the flag that card
raises `evaluator-unvalidated` and recommends completing the calibration this guide forbids that
project; with it, the containment review. So the sentence says what the flag is FOR: "it moves no
number, and it is the only route where preflight finds no engine". The flag's own `--help`, which
carried the identical false claim, is reworded beside it so the two homes cannot drift apart, and
twenty of the bytes are paid back three words later, where "records why no in-process route
replaces the containment review" becomes "replaces it".

No ceiling moves. Both figures rise and stay under the ceilings 0094 left standing, restated here
unchanged: 106_371 resident and 498_266 total, measured on the tree this entry ships with. That
leaves 34 bytes of total headroom, which is under the 1_400-byte median raise this ledger records:
the next branch to write a guidance sentence should expect to raise the ceiling deliberately rather
than to find room, and should measure the merge rather than its own branch.

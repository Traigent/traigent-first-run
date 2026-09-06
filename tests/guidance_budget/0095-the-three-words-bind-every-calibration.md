# 0095 - the three words bind every calibration

follows: 0094
follows-resident-measured: 106_368
follows-total-measured: 498_243
follows-document-measured: 136_303
resident-ceiling: 106_500
resident-measured: 106_372
total-ceiling: 498_300
total-measured: 498_265
document-ceiling: 137_550
document-measured: 136_303

Twenty-two bytes over two documents, and neither adds a rule: both correct a sentence that had
stopped being true.

Eighteen of them are in `references/run-safety.md`. Its deterministic-calibration paragraph opened
"Before environment setup, run only a non-executing evaluator whose complete call path is
local-only, side-effect-free, and standard-library-only", which reads as a precondition satisfied
once on the way in. The state that exposes the gap is a calibration that finished and did not pass:
the evaluator has been imported and executed, the run is routed to repair it, and the repaired path
is calibrated again with nothing re-establishing the three words over it. A repair that pulls in an
installed dependency, or that reaches a provider client at module import, meets none of them and met
no gate on the way back in (traigent-first-run#397). The paragraph now opens "Before every
calibration this run performs", which is what the issue asked for and what `SKILL.md` section 4 has
said all along - "Before calibration, apply `references/run-safety.md`'s execution-evaluator scope
gate". The reference was the half that disagreed, so the reference is the half that moved; the
mandate was not restated in `SKILL.md`, which would have given one rule a second home.

The other four are in `SKILL.md`, and they retire a claim this change made false. It said the
scope-refusal flag "moves no number, because nothing here can check it". The second half was the
load-bearing one, and `readiness.py` now derives that same state from preflight's engine witness
with no flag passed at all, so the sentence denied a check the module performs. It reads "it moves
no number, and preflight's witness reaches the same state without it" - the true half kept, the
false half replaced by what actually happens - and the flag's own `--help`, which carried the
identical claim, is reworded beside it so the two homes cannot drift apart. Twenty-one of the
twenty-five bytes that cost are paid back three words later, where "records why no in-process route
replaces the containment review" becomes "replaces it".

No ceiling moves. Both figures rise and stay under the ceilings 0094 left standing, restated here
unchanged: 106_372 resident and 498_265 total, measured on the tree this entry ships with.

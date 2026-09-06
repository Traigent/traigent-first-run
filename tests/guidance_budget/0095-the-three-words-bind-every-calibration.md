# 0095 - the three words bind every calibration

follows: 0094
follows-resident-measured: 106_368
follows-total-measured: 498_243
follows-document-measured: 136_303
resident-ceiling: 106_500
resident-measured: 106_368
total-ceiling: 498_300
total-measured: 498_261
document-ceiling: 137_550
document-measured: 136_303

Eighteen bytes, all of them in `references/run-safety.md`, and they change when a rule applies
rather than adding one. Its deterministic-calibration paragraph opened "Before environment setup,
run only a non-executing evaluator whose complete call path is local-only, side-effect-free, and
standard-library-only", which reads as a precondition satisfied once on the way in. The state that
exposes the gap is a calibration that finished and did not pass: the evaluator has been imported
and executed, the run is routed to repair it, and the repaired path is calibrated again with
nothing re-establishing the three words over it. A repair that pulls in an installed dependency,
or that reaches a provider client at module import, meets none of them and met no gate on the way
back in (traigent-first-run#397). The paragraph now opens "Before every calibration this run
performs", which is what the issue asked for and what `SKILL.md` section 4 has said all along -
"Before calibration, apply `references/run-safety.md`'s execution-evaluator scope gate". The
reference was the half that disagreed, so the reference is the half that moved; nothing was added
to `SKILL.md`, which would have given one mandate a second home. No ceiling moves and resident is
untouched: the whole change is in a per-stage reference, measured at 498_261 against the 498_300
that 0094 left standing, and restated here unchanged.

# 0144 - the telemetry routes carry the mark

follows: 0143
follows-total-measured: 574_555
follows-document-measured: 177_481
total-ceiling: 574_790
total-measured: 574_545
document-ceiling: 177_690
document-measured: 177_471

A prune of ten bytes, all in run-safety.md. The missing-telemetry routes said in prose that route
A was "marked recommended because" it can still show a quality comparison, so an assistant pasting
those two bullets into the reply sent an unmarked pair - the menu SKILL.md's one-shape rule forbids.
They render in the connected preview's final reply-ready block, which writes its recommended route
as `**<action>** *(recommended - <reason>)*`, so route A now takes that form: the bold action, then
the mark and its unchanged reason in one italic parenthesis. The guide writes the mark in other
forms elsewhere, such as `**X (recommended).**` in component-creation.md and inline templates in
this file; the block the routes render in is the convention they follow. No other route list in
run-safety.md or SKILL.md describes its mark instead of writing it; the sentences that tell the
assistant how to compose an ask still say "marked recommended" in the mandate's instruction voice.

The block went unnoticed because the route-block counter never saw it: its line pattern did not
accept a letter inside a code span. The test now admits that form, which reads the old block as
two routes with no mark, and two prose lines it now matches are named with their reasons.

Both ceilings fall by the same ten bytes. A byte freed under an unchanged ceiling would read as
room nobody granted, so the headroom stays what 0143 left: 245 total and 219 on the largest document.
RESIDENT is untouched, since SKILL.md and GUIDE.md did not change.

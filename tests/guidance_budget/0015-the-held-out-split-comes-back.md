# 0015 - the held-out split comes back, and the answer key gets read

follows: 0014
follows-resident-measured: 64_323
follows-total-measured: 274_587
resident-ceiling: 65_750
resident-measured: 65_500
total-ceiling: 303_000
total-measured: 302_507

The last six branches, measured together because they are one argument: the run
stops grading itself. #142 reinstates the held-out split, #177 reads each row's
expected answer against its own input, #187 makes that reading bound a claim
instead of stopping a run, #188 ranks its ceiling against every other, #173
tells the user which files the run wrote, and #193 takes this repository's
tracker citations out of the shipped guidance.

This is the first entry in six to move RESIDENT, because neither change is a
detail one stage owns. SKILL.md gains the held-out report line where the
recommendation is made, and the routing bullet for a cap whose whole point is
that it asks rather than blocks; GUIDE.md loses a little where the promise no
longer has to hedge about what was measured on what.

The reference cost is three arguments, and each is a sentence the guidance
could not previously say. First, how to pick rows when difficulty is not
labelled - a ladder that stops at the first rung that holds, plus the rule that
an assistant's own ranking may never be written into the scored `difficulty`
field, because filling it converts "declares no difficulty" into full band
coverage and clears the spread complaint on the assistant's own opinion.
Second, what may and may not be said about the gap the split exposes: selection
bias plus ten rows of sampling noise makes that gap inconclusive, which is
neither proof of overfitting nor something a holdout feature prevents, and both
of those wrong sentences are now banned by name rather than left to a reviewer.
Third, the row-level check itself - every other check reads one column, so a
row whose expected answer contradicts its own input passes all of them, and the
optimizer then rewards whichever configuration gets it wrong.

The ten-row default keeps the reason it actually has. The published rationale
used to be the scorer's floor - "at nine comparable rows it raises
`dataset-below-measurable-size` and blocks the paid comparison" - and #149,
already in this tree, makes that cap advisory above zero scoreable rows. So the
number stays at ten and the reason becomes difficulty coverage, which is a
property of the split and of nothing else: 2 easy / 3 medium / 3 hard / 2 very
hard holds no spare, so an outer band losing one row makes a single outcome that
band's whole result.

#173's disclosure is the only part that buys no new judgement, and it is here
because the alternative was worse: a user who wants to know what the run left on
their disk had to ask twice, and five of the writes sit outside the folder the
close says can be deleted. Every path it names is written with the folder it
lives in, which is what the rest of this corpus already does and what lets the
guard that every named file resolves see them at all.

65_500 and 302_507, measured on the merge of all thirty-four into the
twenty-eight before them, with `assistant_facing_documents()` on the merged
tree. No branch declared either figure: #142's own base predates #174's exact
counts and #189's rewritten pillar, and #177, #187 and #188 were each written
against a base with neither `CAP_SEVERITY_ORDER` nor the fail-closed route and
overlap registries their cap now has to be registered in. The RESIDENT ceiling
rises for the first time since 0011.

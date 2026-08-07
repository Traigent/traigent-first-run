# 0015 - the held-out split comes back, and is named once

follows: 0014
resident-ceiling: 65_300
resident-measured: 65_063
total-ceiling: 293_700
total-measured: 293_245

#142 reinstates the walkthrough's held-out split and this is the first entry in
five to move RESIDENT, because a split is not a detail one stage owns. SKILL.md
gains the report line that shows the held-out score where the recommendation is
made, and GUIDE.md loses a little where the promise no longer has to hedge about
what was measured on what.

The reference cost is where the argument lives, and it is two arguments. The
first is how to pick rows when difficulty is not labelled - a ladder that stops
at the first rung that holds, plus the rule that an assistant's own ranking may
never be written into the scored `difficulty` field, because filling it converts
"declares no difficulty" into full band coverage and clears the spread complaint
on the assistant's own opinion. The second is what may and may not be said about
the gap the split exposes: selection bias plus ten rows of sampling noise makes
that gap inconclusive, which is neither proof of overfitting nor something a
holdout feature prevents, and both of those wrong sentences are now banned by
name rather than left to a reviewer.

The ten-row default keeps the reason it actually has. The published rationale
used to be the scorer's floor - "at nine comparable rows it raises
`dataset-below-measurable-size` and blocks the paid comparison" - and #149,
already in this tree, makes that cap advisory above zero scoreable rows. So the
number stays at ten and the reason becomes difficulty coverage, which is a
property of the split and of nothing else: 2 easy / 3 medium / 3 hard / 2 very
hard holds no spare, so an outer band losing one row makes a single outcome that
band's whole result.

65_063 and 293_245, measured on the merge of #168, #174, #182, #185, #189 and
#142 into the twenty-three before them. #142 declared neither figure against a
base containing #174's exact counts or #189's rewritten pillar.

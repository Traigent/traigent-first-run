# 0033 - a disjoint split drawn in the wrong place

follows: 0032
resident-ceiling: 77_500
resident-measured: 77_267
total-ceiling: 352_700
total-measured: 352_437

A sixteenth dataset condition needs a route, and an unrouted condition is worse
than no condition: the card prints a ceiling and a reason, the flow has no branch
for it, and whoever is running the walkthrough invents one. The three split
conditions now say three different things, and only two of them are answered by
redrawing the line. Leaving the newest one to inherit either neighbour's branch
would hand a customer with real, labelled, disjoint rows an instruction to repair
material that may be exactly what they meant to build.

What the flow buys is the ask, and the ask is the whole difference. The other two
split branches are repairs because their evidence is counted - the same rows on
both sides, or nothing scoreable on one. This one is inferred from the leading
words of each input, which cannot tell one task written two ways from two tasks,
and a deliberate out-of-distribution holdout produces it on purpose. So the
branch says to name the two kinds in the customer's own words, take their answer
on the existing ask rather than adding one, and continue with the ceiling
standing where they say it is one task.

The dataset reference gains the check itself in the list of quality checks it
already owns, including the part a reader would otherwise have to infer: that the
kinds are guessed from leading words, and that the check skips rather than passes
where nothing recurs. A skip presented as a pass is how an unanswerable question
becomes a clean bill, and the list is where somebody looks to find out what was
actually examined.

Both figures move because the routing list lives in the flow and the check
description lives in the reference, which is the division those two documents
already keep. 77_267 resident and 352_437 total, measured with
`assistant_facing_documents()` after both passages landed.

# 0106 - the no-tools clause says what changed

follows: 0102
follows-resident-measured: 106_386
follows-total-measured: 498_296
follows-document-measured: 136_303
resident-ceiling: 106_500
resident-measured: 106_386
total-ceiling: 498_294
total-measured: 498_290
document-ceiling: 137_550
document-measured: 136_303

An earlier revision of this branch restated `component-creation.md`'s tools clause at exactly its
old length and claimed that as a virtue. It was not one. `"used": false` had earned no credit
before the change and earned no credit after it, so a phrasing chosen to fit the old byte count
described the one thing that did not move and left out the one that did: the check now keeps its
full weight, which is worth four points on the agent pillar to a document that answers it. Eleven
lines further down, the paragraph about `"determined": false` already said "keeps its weight" out
loud, so a careful reader met two clauses in one section, drew the contrast, and concluded the
tool-less arm still leaves the pillar - precisely the behaviour this branch removes. No document
the assistant reads said otherwise anywhere.

So the clause now states the treatment rather than the credit, and the stranded tail goes with it.
"prompt, output-contract, control-flow, and config-space checks remain" bounded what the old verb
"removes" removed; nothing is removed under this treatment, so "remain" had lost the thing it was
contrasted against and read as a list for its own sake. What that list was protecting - that the
other two pillars are scored elsewhere - survives as its own short sentence.

**The corpus shrinks by 6, and TOTAL comes down by the same 6.** Saying the accurate thing turned
out to cost less than saying the inaccurate one, because dropping the four-item enumeration paid
for the longer verb phrase and then some. A freed byte that stays under an unchanged ceiling is a
raise nobody weighed, banked for a future author who will read it as room somebody decided to give
them, so the ceiling moves to 498_294 and the usable gap stays where 0102 left it, at 3 bytes under
a strict comparison. RESIDENT and DOCUMENT are untouched: the edit is inside a reference file, and
that reference is not the largest one.

This entry exists only because the tree it ships with no longer matches 0102's figures. It binds to
0102 because that is the newest entry present in this branch, and the branches queued alongside it
number theirs 0103 and 0105 while a prune branch is still unnumbered - so whichever of us integrates
last re-points this file at the tail that then exists, restates the four `follows-` bindings from
that entry's own recorded figures, and re-measures the corpus rather than carrying these numbers
across. A figure measured on a predecessor that has since been overtaken is stale by construction,
and refusing that is the whole job of the binding fields above.

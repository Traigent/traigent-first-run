# 0106 - the no-tools clause says what changed

follows: 0104
follows-resident-measured: 105_460
follows-total-measured: 495_126
follows-document-measured: 134_261
resident-ceiling: 105_600
resident-measured: 105_460
total-ceiling: 495_124
total-measured: 495_120
document-ceiling: 135_492
document-measured: 134_261

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
them, so the ceiling moves to 495_124 and the usable gap stays at the four bytes 0104 left it.
RESIDENT and DOCUMENT are untouched: the edit is inside a reference file, and
that reference is not the largest one.

This entry is measured on the tree it ships with and follows 0104, the merged ledger tail. Its four
`follows-` bindings are that entry's recorded figures; the remeasurement above prevents a number
from describing a predecessor rather than the package this change actually delivers.

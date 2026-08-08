# 0017 - what the scorer does, instead of what a branch once did

follows: 0015

total-ceiling: 303_750
total-measured: 303_410

Three passages in two references described behaviour that a merge had already
replaced, and correcting them costs more bytes than the wrong version did,
because in each case the true rule has an exception the false one denied.

`evaluation-and-dataset.md` told a reader that a project word outside the
vocabulary keeps its collected credit. It has not since `ff78125f`: preflight
now classifies such a word where it classifies silence, so a twelve-row corpus
declaring `crm-export` on every row lands on 3 points out of 10 and reads `FIX
BEFORE PAID RUN` at a ceiling of 65. Saying only "it is scored as undeclared"
would leave a reader who followed the old sentence unable to explain their own
card, so the corrected passage carries the reason (an unverifiable declaration
may not beat a verifiable one), the disclosure that prints both grades, and the
one relabel that clears it. A second sentence goes into the ceilings table
beside it, because the undeclared rungs hold the paid run where the declared
twins merely bound the claim, and nothing in the file said so - a customer
bringing an ordinary unlabelled dataset was blocked by a document that
described no blocking at all.

`run-safety.md`'s `max_trials` row promised that deleting the field can never
raise the agent sub-score. That holds from four reachable configurations up and
fails below: on one twelve-configuration space a declared budget of two earns
35 and a declared budget of one earns nothing, against 70 for a document with
no budget line. The narrower property is already written in the scorer's own
docstring, which defends the exception rather than denying it; the row now says
the same thing, plus why the exception is not the defect the rest of the
sentence warns about. An absolute is shorter than a bounded claim, and it was
shorter because it was wrong.

Nothing is pruned to pay for this. Every byte added replaces a sentence a
reader would have had to unlearn from their own run, and the checks that go in
beside them read their figures out of `score_evaluation`, `classify_provenance`
and `search_space_points` rather than pinning the new wording - so the next
merge that moves one of those numbers fails a test instead of quietly making
this file wrong again.

303_410 measured on this branch with `assistant_facing_documents()`, against
trunk `8f8d780a` at 302_507. The ceiling is set above the measurement rather
than at it, so the two adjacent corrections this work predicts do not each need
an entry of their own. The first has since been made here: the ceilings section
closed by saying a ceiling never stops a run, nineteen lines under its own new
sentence saying two of these rungs do, and both were prose nothing derived. The
115 bytes that cost went into the reserve, which leaves 340 for the second -
whatever the open agent-pillar branch does to the closing paragraph above the
schema table.

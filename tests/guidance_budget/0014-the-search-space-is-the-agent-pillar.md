# 0014 - the size of the search space is the agent pillar

follows: 0013
total-ceiling: 274_900
total-measured: 274_587

Three branches land on the agent pillar together and only the last one costs
bytes. #182 deletes the `coverage` sub-score and re-weights what is left, which
takes the schema table's longest row out of run-safety.md; #185 deletes the
`agent_type` field that row described, taking another; #189 then replaces
`knob-count` with `search-space` and has to explain a ladder rather than a
plateau. The net is smaller than #189 alone because the two deletions paid for
most of it.

What the remaining rise buys is a sentence instead of a number. The old evidence
line read `4 of 4 wired knobs actually vary; 8 combinations`, which is a count a
reader can check and not an answer they can act on. The new one states the space,
then what this run will do with it, then how far that is from a complete search -
and it names the shortfall, which is the part a customer can decide about before
they pay. The `max_trials` row grows for the same reason: omitting the field now
costs a step, and a rule that costs something has to say so where the author
writes the document.

One byte of it is a defect neither branch could see. #189 wrote the repeats
clause as `each repeated N times over 'seed'` while `seed` was the only knob
excluded from credit. #168 added `max_tokens` to that list, and two `max_tokens`
values are not one configuration run twice - so on the merged tree that sentence
named the wrong knob and called two different requests a repeat. The clause now
reads the excluded names and picks its verb from them.

274_587, measured on the merge of #168, #174, #182, #185 and #189 into the
twenty-three before them. No branch declared this: #189's own ledgerless base
predates #172's move of the ceiling out of the test file entirely. RESIDENT is
unchanged at 64_344 and its 64_500 ceiling from 0011 still holds.

This entry first recorded 274_465, which was 122 bytes below the tree it
describes. The figure was corrected by re-measuring that same twenty-eight-PR
merge with `assistant_facing_documents()` rather than by moving the ceiling:
274_900 was never in danger, so nothing downstream depended on the wrong
number, but a ledger whose measured figures are approximate cannot be used to
tell a real rise from a mis-transcription - which is the only thing the
monotonicity rule between entries reads.

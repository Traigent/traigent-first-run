# 0007 - the prose stops asserting numbers the scripts do not produce

follows: 0006
follows-total-measured: 235_511
total-ceiling: 237_500
total-measured: 236_903

#157 goes through the references looking for claims the bundled scripts cannot
back, and most of what it does is subtract. What it adds costs bytes anyway,
because a correction is longer than the sentence it replaces: the provenance
vocabulary is three classes rather than two, and the third - a row carrying a
non-answer like `n/a` - needs saying explicitly, since the card prints that
token back as the source it read while the old prose called the row one that
"does not record where it came from". A reader comparing the two would have
concluded the card was lying.

Resident does not move at all here, which is the placement policy working: every
correction landed in the reference that owns the stage, and SKILL.md kept its
ordering.

236_903 measured. #157 never stated a total this tree could use; its own figure
predates six merges under it, one of which (#191) deleted a feature #157 wrote a
new test for.

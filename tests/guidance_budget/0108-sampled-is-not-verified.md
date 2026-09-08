# 0108 - sampled is not verified

follows: 0107
follows-resident-measured: 105_460
follows-total-measured: 495_092
follows-document-measured: 134_261
resident-ceiling: 105_600
resident-measured: 105_582
total-ceiling: 496_499
total-measured: 496_495
document-ceiling: 135_492
document-measured: 134_261

One budget moves. TOTAL goes up by 1_403, which is one median raise as this directory measures its
own history, and RESIDENT stays exactly where 0107 left it - 105_582 under an unchanged 105_600,
with the eighteen bytes of slack that leaves stated here so nobody has to re-derive it. That split
is the whole shape of what this change was allowed to cost. RESIDENT is loaded on the first turn and
carried to the last, so a byte there is paid on every turn of every run; a byte in a reference is
paid once, by the reader who followed a pointer to it. An earlier revision of this branch spent 685
of the expensive kind and was refused for it, correctly.

What the bytes buy is a hold that a run can actually lift. The top two bands were held until a read
covered every row the search is graded against, and on any corpus above the drawn subset no read
ever could: the review names the rows that were drawn while the score reads the declared split, so
on this guide's own 4,812-row worked example the customer did everything asked of them and the card
still reported that nobody had looked. Worse, the reference promised a release at the section-4
re-score which the predicate refused, so the guidance and the code disagreed about a state the
customer arrives in by following the guidance. The fix is not a smaller denominator. A full
comparison of every input against its expected answer is refused during onboarding rather than
skipped - for a retrieval task whose input is a PDF, nobody should be put through it to start - and
the read becomes a declared sample of five rows.

The cost of that decision is the word a customer takes away, so the bytes go where the word is
settled. `references/evaluation-and-dataset.md` says why five and not the file, what a released hold
does and does not establish, and the sentence the customer hears: this run looked at a few of your
expected answers against the method that will grade them, they held, and the rest is assumed rather
than shown - so worth your own look, most of all where nobody assembled the key by hand. Beside it,
the disclosure that where this run wrote the dataset or the method, the sample was taken through its
own work. The glossary entry that defines the held band described a row-by-row read this guide no
longer performs, and had to stop.

Nothing about production readiness is in this measurement. The paragraph #439 asked for, and the two
mandates in the flow document that point at it, were on this branch when it was 685 bytes of
RESIDENT over and are not here: a second issue riding a first is what made the diff unreviewable for
onboarding, and it lands on its own with its own arithmetic. What remains is one issue, one release
of one hold, and one ceiling asked to move.

# 0042 - a row id the dataset does not have

follows: 0041
total-ceiling: 366_043
total-measured: 365_643

The row review requires a per-row id and `readiness.py` refuses an entry without
one. This dataset carries none, and preflight says so in its own warning. So the
id has to be invented, and nothing said what to invent.

Four blinded runs over the same file each minted their own scheme. All four chose
source-line numbering, which reads like agreement and is not: nothing directed
it, and two review documents written for one dataset cannot be compared unless
their ids mean the same thing. A convergence that happens by luck fails the first
time it does not.

The line number is named because it is the identifier the file already has, and
because preflight's warning quotes source lines - a user told `line-7` can find
row 7 without being handed a mapping. The conversation says the ids are
positional, since an invented id quoted at a customer who cannot locate it is
worse than no id at all.

And it stays a fallback. If the customer later adds stable ids, the next run uses
theirs; this is what to do when the file offers nothing, not a scheme replacing
one the file has.

Resident does not move: the row-review contract lives in the dataset reference,
and the flow already mandates the read.

365_643 total and 79_350 resident, measured with
`assistant_facing_documents()` on this branch.

# 0043 - a row id the dataset does not have

follows: 0042
follows-total-measured: 365_609
total-ceiling: 368_418
total-measured: 368_018

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

368_018 total and 79_350 resident, measured with `assistant_facing_documents()` over the
merge of this change and 0042 rather than on either branch alone. Both were
written against 0041 and both measured under the ceiling each then set, so
each figure was honest and neither described the corpus that carries both.

The scheme is scoped in the same entry rather than a later one, because the
scope is what makes it true. A line number identifies a row only where the
customer's own file is one row per line, and this guide blesses converting a
dataset to JSONL - so the blessed path is the one that breaks the reason the
scheme was chosen for. Naming the fallback without naming that condition would
be the defect this entry exists to close, committed by the fix for it.

Re-measured again after review found the scoped rule unfollowable: it named the
customer's row position as the id and nothing in the guide preserved that
position across a conversion. The id is now stamped as the conversion happens,
which is the only moment it is still known, so the bytes buy a rule a run can
carry out rather than one it can only agree with.

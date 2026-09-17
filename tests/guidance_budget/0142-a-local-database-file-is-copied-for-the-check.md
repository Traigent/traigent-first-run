# 0142 - a local database file is copied for the check

follows: 0141
follows-resident-measured: 53_892
follows-total-measured: 569_891
follows-document-measured: 173_079
resident-ceiling: 54_300
resident-measured: 54_163
total-ceiling: 572_800
total-measured: 572_500
document-ceiling: 175_700
document-measured: 175_426

The copied-actor route asked every customer with an executing SQL evaluator for a read-only
connection or a duplicate database, which almost nobody has, so in practice the route collapsed
to "skip" and the evaluator went unchecked. Where the located target is a local database file
under 256 MB, the run now makes the duplicate itself: a plain shell copy of the whole file and
its sidecars into traigent-runs/calibration/, byte for byte, never opened as data, never read
row by row, never printed - seconds and no tokens, where reading rows would cost both and put
the customer's data in the conversation. That copy is route A and recommended; the pasted
target stays as route B for server databases, and skipping stays last. The run writes the
copied path under the target name into the owner-only .env itself, so the existing gate reads
it unchanged. The value written is an absolute path, because the gate's child runs from
traigent-runs/calibration/ and a relative one would open nothing and read as a failed
evaluator; the .env rule that owns what may be written names that one line; a -shm or -journal
sidecar means a possible writer, so the copy waits for the customer to say nothing is writing.
SKILL.md's authorization row, the README and the card's route-neutral wording follow. 2,609
bytes, the total ceiling rises by 2,500, run-safety.md rises by 2,500, and the resident pair
rises by 200 for the .env authorization row, which has to name the one new line it permits.

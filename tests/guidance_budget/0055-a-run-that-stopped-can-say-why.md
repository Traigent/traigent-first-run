# 0055 - a run that stopped can say why

follows: 0054
follows-resident-measured: 84_714
follows-total-measured: 420_544
resident-ceiling: 85_129
resident-measured: 85_074
total-ceiling: 425_679
total-measured: 425_624


Two questions open every conversation about a first run that did not finish -
which step, and what refused - and until now neither had an artifact behind it.
The record answers the first, but only for somebody resuming: its stage block
says where the run is, and a run abandoned mid-stage is read by nobody who was
not already going to continue it. The second was answered nowhere. A blocking
refusal reached the customer as a sentence in a conversation that is gone by
the time anyone asks, and the same refusal arriving four times in a retry loop
looked exactly like the same refusal arriving once.

These bytes buy a file that answers both without being asked, and the design
question they actually paid for is why it is a second file. Fields on the
record would have been cheaper by a line. They would also have been wrong: the
record is re-read top to bottom when a session resumes, and it is authoritative
for what a resumed run may skip, so history appended there arrives dressed as
state. That is the shape a predecessor's moved figures produce in any
append-only record - a later entry standing on numbers that shifted under it - and putting a
timeline inside
the one document a resume trusts would have manufactured more of it.

What makes a second artifact safe under one-decision-one-home is that it
declares nothing the record declares. The record says what is true now; the log
says when a problem was first met and whether it cleared. Neither can
answer the other's question, so neither can contradict it, and where a finding
already owns a field on the record - the portal probe among them - that field
keeps the value while the log keeps only the timing beside it. The rule holding
that seam shut is that nothing in a run may read the log back, which this
package already ships one instance of: the readiness directories are kept and
never re-read either.

Deduplication is not tidiness, it is what makes the file legible at the moment
it matters. The failure that produces the most lines is a retry, and a retry
produces the fewest distinct facts, so a repeat that changed nothing writes
nothing. An identity whose last line is still open is then exactly the picture
of a run somebody walked away from.

The redaction clause is the half worth the most and reads as the most obvious.
This guide deliberately turns example content off in the SDK's own local logs,
and a fresh local file whose entire purpose is explaining a failure is the
likeliest place for that decision to be quietly undone - by a raw provider
error body, which can carry a key or a prompt inside it, as readily as by a row
quoted to make a diagnosis concrete. It is written as an allowlist rather than
a list of forbidden things, because the surrounding guidance spends its effort
teaching the opposite habit: print the absolute path so they can open it, write
the session id into the record. Both are right where they are and wrong here,
and a denylist would have had to anticipate each of them. So the sentence
carries the class of thing that failed and not the instance, and `event`, `stage` and
`class` together are the identity.

Resident moves by five lines, and only because a mandate that lives solely in
a reference loaded before paid execution is a mandate the run does not yet hold
when an earlier stage refuses. SKILL.md names the file, the obligation, and the
one instruction that closes that window - load the shape when the record is
created rather than at the reference's own stage - and it owns the restart,
so the rename of the record now renames the log beside it. The reference keeps
the shape, next to the recovery classes most of the events are drawn from.

One thing these bytes do not buy, said here so no reader has to discover it: the
log cannot predate the record, both waiting on the same consent gate, so a run
abandoned before task intent is anchored still leaves nothing behind. That is
plausibly the commonest place to walk away, and no field defined here pretends
to see it.

The identity was authored prose, which cannot be spelled the same way twice by
a writer who has forgotten the first time - and the writer is asked to find its
own line again after a wait long enough to lose it. Drawing that field from a
closed set is what lets two encounters agree without either one looking the
other up, and it is one of the three fields the identity is spelled from.

The write went further, and this is the paragraph that pays for itself. Keeping
exactly one line per problem accurate obliges the assistant to read the file
back, hold every line of it, and re-emit all of them to move one number. That is
the operation a language model is least reliable at, aimed at the one artifact
whose value is being trustworthy about a run that already went wrong, and its
failure mode is silent: a character altered in a line nobody rereads is exactly
the line somebody is later shown. Hardening it - a temporary file renamed over
the original - answered the crash and left the re-emission untouched, and the
re-emission was the larger risk. So the file is append-only and is never read
back at all: one line when a problem appears, one if it clears, and a reader
collapses them. The count is what that gives up, said out loud where the file is
defined. A retry that meets one refusal twelve times still writes one line,
because nothing about it changed - which is the deduplication that was wanted,
bought without a lookup - while a problem that returns after clearing opens
again and stays visible.

The absent log was its own small defect: a run that meets nothing worth logging
writes no file, and reporting that as unreadable had the guide route a missing
log as a tool failure, opening a file to complain that one was missing. It exits
zero with nothing to report, and exit 2 keeps the case it was for - a file that
exists and cannot be read.

One residual is accepted rather than closed, and it is worth naming because a
reader will otherwise assume a mechanism exists. The visibility guard scans
every tracked file, `.py` included - it has refused a bare identifier in a test
before - but it matches names, and what shipped in an earlier commit on this
branch was a sentence describing how this repository reviews itself. No name, no
host, no repository: a keyword gate for that class would refuse honest prose as
readily as it caught the case, so the guard is not extended and the discipline
stays a reading one. The commit is published and stays published; the shipped
tree says what it should.

The taxonomy is three events, and it is the shape the argument above needs
rather than the one it started with. Told apart by who has to act, there are
three actors - the user, this run, and nobody - so a fourth event needs a
boundary rule against the other three, and every boundary rule this file carried
was a rule about the taxonomy rather than about a run. `blocked` is waiting on
the user. `stopped` is this run not going on, and its classes say why. A
`warning` is what did not stop the run. Nothing has to be argued into the right
event, so no argument about one can be wrong.

What that leaves unbought is size rather than correctness, and it is worth
saying because the entry above spends its bytes on the correctness half. Three
events carry as many distinct class values as six did; the old four survive as
prose inside one bullet, describing rather than deciding. The defects the
taxonomy generated are structurally gone. The number of words an assistant has
to spell the same way twice is not.

What is deliberately not in this entry any more is the round-by-round record of
how the work went. Thirteen commit messages carry it, which is where a reader
looking for it will look, and an entry that is four-fifths chronicle argues for
its bytes with the wrong thing - as this one did, at three times the size of the
guidance it justifies, while carrying seven statements a later paragraph in the
same file called false.

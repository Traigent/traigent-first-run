# 0055 - a run that stopped can say why

follows: 0054
resident-ceiling: 85_215
resident-measured: 85_160
total-ceiling: 426_433
total-measured: 426_378

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
state. That is the shape #305 records in a different ledger - an entry
standing after a predecessor whose figures moved underneath it - and putting a timeline inside
the one document a resume trusts would have manufactured more of it.

What makes a second artifact safe under one-decision-one-home is that it
declares nothing the record declares. The record says what is true now; the log
says when it happened, how many times, and whether it cleared. Neither can
answer the other's question, so neither can contradict it, and where a finding
already owns a field on the record - the portal probe among them - that field
keeps the value while the log keeps only the timing beside it. The rule holding
that seam shut is that nothing in a run may read the log back, which this
package already ships one instance of: the readiness directories are kept and
never re-read either.

Deduplication is not tidiness, it is what makes the file legible at the moment
it matters. The failure that produces the most lines is a retry, and a retry
produces the fewest distinct facts, so one line per problem carrying a count
beats twelve lines carrying one finding between them. A line that never gains a
resolution is then exactly the picture of a run somebody walked away from.

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
carries the class of thing that failed and not the instance, and the class is
the only field the identity is spelled from.

Resident moves by four lines, and only because a mandate that lives solely in
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

Four of the bytes above are what an adversarial read of the first draft cost,
and each bought a rule the draft did not have. The taxonomy had filed the
degradation this file elsewhere orders a halt for as a warning - defined as the
thing that does not stop the run, seventy-one lines from the sentence ordering
the stop - so the events now name the closed set each key is spelled from, and
that condition sits under the one that means the run ended early. A sixth event
exists because walking the recovery list against five found nine classes with
nowhere to go, an outage and an uncategorised provider error among them, and a
vocabulary with a hole in it is one an author fills by inventing a word.

The identity was authored prose, which cannot be spelled the same way twice by
a writer who has forgotten the first time - and the writer is asked to find its
own line again after a wait long enough to lose it. Drawing that field from a
closed set is what lets two encounters agree without either one looking the
other up.

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

The tests moved further than the guidance did. The first set was eight
substring assertions, and a mutation sweep passed all of them against seven
edits that reversed what the section says - deleting every event definition,
dropping two redaction clauses, and renaming the artifact in one document but
not the other. They now parse the field set out of the table, read the cells
that carry a rule rather than a type, check each clause of the allowlist on its
own, refuse the two spellings a rewrite comes back as, and require one path
spelled identically in four documents. Every mutation written against them has
gone red.

# 0055 - a run that stopped can say why

follows: 0054
resident-ceiling: 85_264
resident-measured: 85_209
total-ceiling: 427_725
total-measured: 427_670

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

The tests moved further than the guidance did. The first set was eight
substring assertions, and a mutation sweep passed all of them against seven
edits that reversed what the section says - deleting every event definition,
dropping two redaction clauses, and renaming the artifact in one document but
not the other. They now parse the field set out of the table, read the cells
that carry a rule rather than a type, check each clause of the allowlist on its
own, refuse the two spellings a rewrite comes back as, and require one path
spelled identically in four documents. Every mutation written against them has
gone red.

A third round bought a script rather than a sentence. Every rule above was
executed by the assistant and enforced by nothing, which is this repository's
own recurring defect wearing the one shape it can least afford: a privacy
promise, on a file written into somebody's real project and meant to be handed
to a stranger. `scripts/validate_run_log.py` reads the log and refuses a class
outside its event's set, a state that is neither, a field the schema does not
have, a sequence that clears something never opened or repeats a state already
standing, and a sentence carrying a path, a credential, an address, an
identifier, a link, or a quoted span long enough to be somebody's row. It
cannot prove a sentence is free of customer data; it refuses every carrier
anyone has actually leaked through, which is what the clause decomposes into.
Scripts sit outside this budget, so the mechanism costs nothing here and the
closed vocabularies become safe to keep.

The same round closed three holes the vocabulary still had. `warning` had no
catch-all while its sibling did, and the guide mandates warnings - a no-lift
delta, rows nothing could score, a model swapped for being unavailable - that
were none of its three values, leaving an assistant to invent a class it is
forbidden to invent. `tool_fail` keyed on a non-zero exit, which is the healthy
answer where the credential handoff continues on exit 1, and is a finding about
the customer's own material where preflight exits 1 - the exact relay that
document forbids by name. And the rename that keeps one run's `cleared` off
another run's `open` was written for one of the three paths that retire a
record; it is stated once now, over all of them.

The fourth round found the shape this entry has now argued for twice, in the
change that was supposed to end it. `uncategorized` was added to the prose, and
recorded here as shipped, while the checker still refused it - so a completed
run reporting no lift, which the flow has a whole clause for, would have written
a line its own validator rejected and shown the customer a rejection at the
close. Two documents, one vocabulary, and nothing compared them: one test read
the prose, another read the code. They are compared now, and the closed sets in
the reference are asserted equal to the sets the script enforces.

One check went for being wrong rather than for being unenforced. Refusing a
repeated `open` cannot distinguish a same-session retry, which writes nothing,
from a resumed session re-opening what it can no longer remember, which this
guide licenses - and refusing correct input at the close is worse than not
checking, because it teaches people to write around the checker. Collapsing on
the identity answers the same either way, so deduplication stays guidance and
the sequence check keeps only what is wrong however it arose.

Resident buys one more line than it did, and it is the line that makes the file
worth writing: the close is the only place that named this file to the user, and
a run that stops never reaches the close. The file written to explain a stopped
run was invisible on exactly those runs. It is named wherever the run stops now,
and the validator runs there too, so the privacy allowlist is machine-checked on
the logs most likely to be handed to a stranger rather than only on the ones
whose runs finished.

The rest of the round was subtraction. Six passages were cut and their arguments
left here where they were already written: the design rationale for append-only,
the sentence arguing against a key field nobody proposed, the restatement of the
consent gate, the second statement that the directory is deletable, and two
paragraphs answering a reviewer inside the document an assistant reads at
runtime. A reference states the rule; this ledger is where the reasoning lives.

A fifth round read the checker as code rather than as a promise, and three of
its defects were the kind only execution finds. Keying a quoted span on an
opening quote made every possessive apostrophe a finding, so "the provider's
quota was exhausted" was refused - at the close, on a correct log, in front of
the customer. An unhashable value reached a set membership test and raised,
which the blanket handler turned into exit 3, and the guide routes exit 3 as a
tool failure: the run would have logged a complaint about its own checker rather
than showing the user the bad line. And the email pattern, unbounded on both
sides of the `@`, backtracked for seventy-eight seconds on a quarter-megabyte
token - which is precisely the pasted error body the rule exists to catch.

The quotes must pair now, three membership tests check the type before they
check the value, the pattern is bounded, and `detail` has a length past which it
is the finding rather than the thing being searched. Two carriers that were
never checked at all are, an IP and a bare host; one that looked checked was
dead code, because two escaped backslashes match a literal `C:\\` that no
decoded path contains.

The tests moved further than the checker did, and the honest measure is that
they had to. A sweep of thirty-five edits to the script left fifteen green:
`ts`, `stage`, `state` and the record shape had no negative coverage at all, and
every leak pattern had exactly one example, so any narrowing that spared that
example survived. Each rule was given boundaries and the internal-error path is executed
rather than described, and the
docstring names the two allowlist clauses - a person's name, a machine's - that
have no mechanical shape and stay the assistant's to honour. A clean exit says
what it can prove and no more.

A sixth round is the honest end of this entry, because it found the fix from the
fifth reintroducing the defect the fifth had written its commit message about.
Pairing the quote characters stopped one possessive being read as an opening
quote and made two of them, twenty-six characters apart, into a span - which is
the register this reference itself writes in, so ten of sixteen realistic
sentences were refused at the close on a correct log. An apostrophe between two
letters is never a quote, and the rule says so now. Beside it, a twenty-letter
run was refused as an identifier, which is what a provider's error class name
is, and naming one is exactly how an uncategorised refusal gets written; an
identifier worth refusing carries a digit and a class name does not.

Three claims made in this entry were also not true when they were written, and
that is worth recording where the claims are. Comments in the shipped checker
still narrated this repository's own drafting; the naming of the log moved to
every stop while its check stayed at the close; and the sweep those paragraphs
called exhausted was the authors' own. A later sweep of fifty-five edits left
seventeen green, every one of them aimed at what the previous two rounds added.
The gaps are closed - each pattern's alternatives, the stage scale, the timing
rule, the absent-log path - and the claim is narrowed to what was measured.

The absent log was its own small defect: a run that meets nothing worth logging
writes no file, and reporting that as unreadable had the guide route a missing
log as a tool failure, opening a file to complain that one was missing. It exits
zero with nothing to report, and exit 2 keeps the case it was for - a file that
exists and cannot be read.

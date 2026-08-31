# 0069 - open with the welcome, and name the stages the user was given

follows: 0068
follows-total-measured: 436_211
follows-resident-measured: 89_305
resident-ceiling: 89_700
resident-measured: 89_667
total-ceiling: 436_800
total-measured: 436_573

Two live runs of the same guide disagreed about when to greet the user, and the
document is why. "Open with the five-stage journey" sat as one bullet among a
dozen presentation rules, ninety lines above `### 1. Inspect quietly`, whose own
text said only to begin read-only discovery. An assistant looking up what to do
first landed on the step, inspected, scored, and named the five stages for the
first time when it stopped to ask for a provider key. Nothing verifies this:
the greeting appears in exactly one file, referenced by no test and by no
fixture, so neither behaviour was ever wrong on paper. Moving the instruction
into the step that executes it costs bytes and removes the ambiguity that
produced two readings.

The second half buys the vocabulary. Progress lines are told to print
`Stage <n>/5`, while the document a reader is standing in numbers its own
sections one to eight, and the correspondence between them was recorded only as
a parenthetical in a log-schema column description inside a reference file. So a
run at internal step five truthfully reported its next move as "isolated SDK
environment and free mock plumbing" - words no customer had been given, naming
something they were never told exists, when the answer they could act on was
Baseline. Stating the mapping beside the rule that emits the label is what makes
the reported position mean anything to the person reading it.

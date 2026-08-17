# 0049 - a refused document is not an unreadable agent

follows: 0048
resident-ceiling: 84_300
resident-measured: 84_225
total-ceiling: 369_150
total-measured: 369_061

The opening gate has an escape hatch, and it is the right one to have: where
an agent was found and its settings cannot be read out of it, the assistant
names what stopped the read, offers to be pointed at source that can be read,
and leaves `--agent-knobs` off - because passing an empty document would report
a finding about the customer's agent that nothing established.

The precondition was "its settings cannot be read out of it". A blinded run
showed how that reads from inside. The assistant wrote its agent-knobs document
twice, had it refused twice for its own shape - unknown top-level fields, then
again - and took the third route: it dropped the flag, scored the agent pillar
0/100, and told the user their project needed work before optimization could
start. The source was a nine-line Python file that the case's canonical read
handles without difficulty. Nothing about that agent defeated anything. The
paperwork was wrong, and the escape hatch was built for a different failure.

That is worse than a low score. The customer is told something untrue about
code they wrote, at the first number the product ever shows them, and the true
cause - a document the assistant can fix and resend in one step - is invisible
to them. It also converts a recoverable stumble into a permanent cap on the
opening card.

So the precondition is stated rather than implied: the hatch is for the source
defeating the read, never for this document being refused. A refusal names the
field or the shape it objected to and is answered by correcting the document,
which is why the refusal says what it reads. These bytes buy the distinction
between "your agent cannot be read" and "my file was wrong", which the run
above could not make and the user pays for.

Resident, because the whole failure is an assistant at the opening gate
choosing between two readings of a sentence it already has in front of it.

Where the measured figures come from:

    0048 resident measured                                  83_976
    this change                                               +249
    resident measured here                                  84_225

    0048 total measured                                    368_812
    this change                                               +249
    total measured here                                    369_061

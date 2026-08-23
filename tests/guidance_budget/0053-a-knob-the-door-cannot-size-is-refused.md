# 0053 - a knob the door cannot size is refused

follows: 0052
total-ceiling: 417_468
total-measured: 417_409

Four corrections at one seam bought this raise, and the largest of them is
why the repair is a rule rather than one more name on a list.

`worst_case_requests` sized an invocation by reading three of litellm's
keywords and pricing every other one at a single request. `retry_policy` is
not among the three, and the library honours it on plain `completion`: it
reads the policy when a call fails and hands the count that policy names to
its own retrying entry point, whose attempts come back through the door as
nested calls and reserve nothing at all. Measured against a local server
answering 429, one invocation reserved for 1 request placed 6; with a caller's
`num_retries=1` beside it, 3 against 7; with one fallback beside it, 2 against
12. A judge written to survive a rate limit therefore bills six real requests
where the approved total was asked for one.

Adding one more name would have closed that instance and left the mechanism,
which has now produced this shape three times. So what the bytes buy is the
opposite default: a keyword that retries or falls back is refused unless it is
one of the three the sizer can read, and the refusal names those three so a
caller who meets it knows what to write instead. Of the 174 names in the
library's own parameter list, eight match and three are priced; the
measurement that argues for inverting rather than extending is that a list
would still have missed one of the five left over,
`context_window_fallback_dict`, which placed 2 requests against a reservation
of 1 once the error it waits for really fired. Nothing the walkthrough
generates sets any of them, so what this stops is an inherited caller, and it
stops them before the first request instead of after the sixth.

The second correction is one round of arithmetic. The count reaches a stop
condition that halts at the first attempt number REACHING the figure, while
the sizer truncated it: a process-wide 1.5 placed 3 requests against a
reservation of 2, 2.5 placed 4 against 3, and 4.2 placed 6 against 5. Rounding
up instead lowers nothing - 504 cells measured live across the four axes left
none under-reserved, and 4620 cells of arithmetic confirmed the new figure
never sits below the old one. Whole counts, which is everything anybody types
by hand, are untouched; a count divided out of a configuration file is not.

The third is an overstatement this branch introduced itself. Having found that
the ledger line does not print however a process ends, it named the two
endings that print nothing - and a closed list of two is the same defect as
the unqualified claim it replaced, pointed the other way. One subprocess per
ending says six print nothing: the signal a bare kill sends, the one `kill -9`
and the out-of-memory killer send, a dropped terminal, a quit, an immediate
exit, and an abort. What is written down now is the rule those six share, that
an ending never reaching the exit handler leaves no line behind, with the
measurements under it as examples rather than as the whole population. The
half that tells an assistant what to do was already right and is untouched: it
keys on the line being absent, not on which signal fired.

The fourth is small and rides with them. One sentence called the held-out
agent and judge calls the only paid ones no permit covers, which is untrue of
any run an LLM judge grades: such a judge grades every scored row of the
search as well, and the SDK settles a trial's cost before the metric functions
run. Two documents said it, they had already drifted apart once, and the one
that stays is the one that is true - the other points at it now instead of
putting it a second way in its own words.

Nothing resident moves. `GUIDE.md` and `SKILL.md` are unchanged byte for byte
from what 0052 measured, so no resident ceiling is bought and none is declared.

Where the measured total comes from:

    0052 total measured                                    411_332
    sdk-execution.md                                        +4_203
      the keyword test that closes the class, the two
        constants it reads, and the refusal itself          2_009
      the retry law the product of two separate rules
        missed, the floors under a count the library
        reads as set, and the round a fraction buys         1_418
      the ledger line's claim narrowed to the endings
        that reach the exit handler, and the six that
        do not                                                479
      the pointer to what a missing line leaves for the
        phase launched after it                               233
      the registration moved under the guard that stops
        a second wrap                                          55
      the pin no longer called the only exception to
        preserving a caller's retries                           9
    run-safety.md                                           +1_083
      what to carry forward out of a phase that printed
        no ledger line, and the rule that replaced the
        list of two endings                                   771
      the second exception to preserving an inherited
        caller's retry behaviour, and the first restated
        beside it                                             213
      the held-out calls no longer called the only
        unseen ones, pointing instead at the copy that
        is right                                               99
    total measured here                                    416_618

The ceiling sits 59 bytes above the measurement - the margin 0052 left, two
above the 57 of 0051: enough to reword a sentence without a successor entry,
far too little to hide a rule inside. The raise over 0052 is 5_286 bytes, the
tenth largest of the 51 along this chain and an eighth of the one 0052 itself
took, and all of it lands in the two documents the door and its discipline
live in - nothing arrived in either of them ahead of this entry, so there is
no earlier state anyone has to reconstruct to check the arithmetic.


A second measurement was folded into this entry before it landed. The door's
cost reader consulted `usage.cost` and the OpenRouter response-cost header and
never `_hidden_params["response_cost"]` -- the field the installed client
actually fills, and the one the SDK's own accounting reads. Measured against
that client, the two readings it did consult return nothing on five of the six
routes this package supports, so on those routes the door debited the flat
unpriced rate on every call and stopped being a ledger at all. End to end that
counter believed a run had spent $4.98 of an approved $5.00 when the true
figure was $0.249, and refused a held-out pass that fitted twenty times over.

The 791 bytes are the reader's new first branch and the comment that says why
it is first, at 549, plus 242 for the paragraph in the run record. The test
that holds it costs nothing here: it lives in the suite, which no run loads,
and it measures the installed client rather than asserting a remembered field,
so the day that field moves it fails and names the route.

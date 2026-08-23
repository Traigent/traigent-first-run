# 0053 - a knob the door cannot size is refused

follows: 0052
total-ceiling: 418_262
total-measured: 418_203

Six corrections at one seam bought this raise, and the largest of them is
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
caller who meets it knows what to write instead. Of the 214 entries in the
pinned release's own parameter list, eight match and three are priced; the
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
up instead lowers nothing, and that needs no grid to establish: rounding up
never returns less than truncating, whatever the count, and the floors above
it are unchanged, so no configuration reserves fewer requests than it did.
Whole counts, which is everything anybody types by hand, are untouched; a
count divided out of a configuration file is not.

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

The fifth was found while the four above were being measured, and it is the
door's cost reader. It consulted `usage.cost` and the OpenRouter response-cost
header and never `_hidden_params["response_cost"]` - the field the installed
client actually fills, and the one the SDK's own accounting reads. Measured
against that client, the two readings it did consult return nothing on five of
the six routes this package supports, so on those routes the door debited the
flat unpriced rate on every call and stopped being a ledger at all. End to end
that counter believed a run had spent $4.98 of an approved $5.00 when the true
figure was $0.249, and refused a held-out pass that fitted twenty times over.
Its 791 bytes are one hunk and no other file moved for it: 685 of comment
saying why the new reading goes first, 213 of code, less the 107 the old first
reading gave back. The test that holds it costs nothing here, because it lives
in the suite, which no run loads. What it asserts is the reading against the
figure the client priced, not that some figure came back - presence alone was
satisfied by a reader pointed one key sideways at the response's elapsed
milliseconds, which debits some hundreds of thousands of times the price, and
by a reader that answered 0.0 for every priced call, which is a door recording
every call as free. It also refuses to pass having priced nothing, so a
release that renames the field fails it rather than emptying it.

The sixth is three edges the five above left standing, none of them a reading
of cost itself. The reader now normalises `_hidden_params` once rather than guarding
only the first of the two readings that reach into it, so a response object
whose hidden params are not a mapping - a preserved evaluator's own class,
the one caller the door does not choose - reads as no cost instead of raising
`AttributeError` at the second reading. The sizer's round-up cast `float()`
over whatever count it was handed, and `float(10**400)` raises
`OverflowError`; an integer is already whole, so it now skips the cast, and
the multiplication that prices the count refuses it in the door's own words
instead of raising one line further down - which is where it raised before the
round-up existed too, so the traceback was never that change's doing. And the
parameter total the refusal's comment cites is restated for the release this
package pins rather than the one it was first measured on: 214 entries against
174, with the load-bearing half unmoved - the same eight carry a marker, the
same three are priced, and none of the 40 entries the pinned release adds
carries one.

Nothing resident moves. `GUIDE.md` and `SKILL.md` are unchanged byte for byte
from what 0052 measured, so no resident ceiling is bought and none is declared.

Where the measured total comes from:

    0052 total measured                                    411_332
    sdk-execution.md                                        +5_788
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
      the cost reader's new first branch and the comment
        that says why it goes first                            791
      the guards under the reader, so a response object
        the door did not choose cannot break it half-way        201
      the count rounded up without a cast that overflows,
        and the reservation refusing such a count in the
        door's own words rather than raising                    598
      the parameter total restated for the pinned
        release                                                 -5
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
    total measured here                                    418_203

The ceiling sits 59 bytes above the measurement - the margin 0052 left, two
above the 57 of 0051: enough to reword a sentence without a successor entry,
far too little to hide a rule inside. The raise over 0052 is 6_871 bytes, the
eighth largest of the 51 along this chain and a sixth of the one 0052 itself
took, and all of it lands in the two documents the door and its discipline
live in - nothing arrived in either of them ahead of this entry, so there is
no earlier state anyone has to reconstruct to check the arithmetic.

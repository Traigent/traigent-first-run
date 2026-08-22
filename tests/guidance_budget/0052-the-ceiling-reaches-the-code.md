# 0052 - the ceiling reaches the code

follows: 0051
resident-ceiling: 84_760
resident-measured: 84_709
total-ceiling: 382_070
total-measured: 382_008

Every word about the spend ceiling was already correct and none of it was
wired. `run-safety.md` set out the whole discipline - lower the per-optimization
limit to what is left of the approved total, halt before a phase whose estimate
will not fit - and then no fenced line anywhere carried it out. Neither
`optimize_sync` call took a cost argument, no document mentioned
`TRAIGENT_RUN_COST_LIMIT` at all, and the two phases deliberately run as
separate operating-system processes, so each built its own enforcer on the
SDK's own default and neither could learn what the other had already
paid. Held-out scoring never had even that: it reaches `litellm.completion`
without passing the orchestrator, so roughly twenty paid calls on the
configuration this walkthrough recommends were bounded by nothing executable.

That is the shape these bytes buy. A rule an assistant is asked to obey by
arithmetic between phases is obeyed as often as the assistant happens to
remember it; a rule a process refuses to start without is obeyed every time.
The three figures now arrive in the paid process's own environment the way its
phase name already does, the wrapper turns them into the limit the SDK polices
per trial, and one function stands between the ledger and `litellm` so a search
trial, a reserved row, and a judge all knock on the same door.

Most of the raise is executable and the rest explains a rejected alternative.
The refusals carry their remedy in the message a person will actually read -
take a larger total back to the user, rather than raise a number nobody
approved - because these stop a run mid-walkthrough and a bare exception at
that moment invites exactly the repair this whole change exists to forbid. The
one paragraph that is neither code nor its comment records why the SDK's
`ExecutionBudget` was not adopted: it keeps its state in a single Python object
and therefore cannot cross the process boundary the phases are separated by, so
it would have needed reseeding per process while adding a second cap obliged to
agree with the first.

One of the settings gives something up, and saying so is part of what the
bytes are for. Approving cost inside the process is what stops a stored token
or a single keystroke at the SDK's own prompt from lifting the limit above the
approved figure, and it also turns that SDK's pre-run objection to an unpriced
model from a refusal into a warning. Leaving the trade in a comment beside the
line makes it reviewable; leaving it out would have made the setting look free.

Two of the smaller entries below are the launch instructions themselves. Each
one told the assistant to start a fresh process naming one variable, and each
is now a process that stops on arrival unless two more are set with it; leaving
those sentences as they were would have handed a reader a command whose only
outcome is the refusal. They name the figures and point at the document that
defines them rather than restating what those figures are.

Resident moves by the smallest amount that keeps the flow honest. `SKILL.md`
owns the order of the run, so it says that a paid process is launched with the
approved figures and that one given none of them stops - one sentence, pointing
at the reference that names them. The alternative was to leave the flow silent
about a stop it can now produce, and a halt with no home in `SKILL.md` is a
halt an assistant meets for the first time in an error message.

Where the measured figures come from:

    0051 resident measured                                  84_474
    the launch rule in the stage that spends                  +235
    resident measured here                                  84_709

    0051 total measured                                    369_593
    sdk-execution.md                                      +10_089
      the approved figures, their two refusals, and the
        two SDK settings with what one of them gives
        up, all before the import                      3_763
      the ledger and the three functions reading it    2_632
      `call_agent`'s gate, and its debit               1_021
      the two-gate paragraph and the rejected budget    1_485
      the held-out pre-loop refusal                        396
      the two launch instructions, now naming what
        the process will stop without                      159
      the held-out opening, the baseline's running
        total, the run-bounds pointer, the owns-list        633
    run-safety.md                                          +2_091
      the three launch figures, replacing the sentence
        that stated the discipline and wired none of it   1_060
      what happens when a phase reaches the remaining       404
      the held-out approval, all rows or none               262
      the closing check, and the running total's
        destination                                        365
    SKILL.md                                                 +235
    total measured here                                   382_008

Both ceilings sit under seventy bytes above their measurement, in line with the
57 that 0051 left: enough to reword a sentence without a successor entry, too
little to admit a rule.

# 0052 - the ceiling reaches the code

follows: 0051
resident-ceiling: 84_760
resident-measured: 84_709
total-ceiling: 389_551
total-measured: 389_491

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

That last clause was written before it was true, which is the second half of
this entry. `task_score` is wired into the decorator, so it runs on every
trial of both phases and on every held-out row; when the evaluator is an LLM
judge - what `evaluation-and-dataset.md` prescribes for summary, explanation,
writing and story tasks - it places a provider call of its own, and the
`metric_functions` contract it is called under passes three values and returns
a number, with no ledger among them. So the judge's spend reached no gate, and
three documents plus a test docstring said it did. The SDK cannot close it from
its side either: at the pinned 0.26.0 the local evaluator settles a trial's
cost before it applies the metric functions, so a call made inside one is
already past that trial's accounting.

Routing it was possible, so retracting the sentence was not the answer. The
guide generates `task_score`, so it can generate one whose judge places its
call through the wrapper. The door is now `place_call`, and `call_agent` and
`call_judge` are each one line delegating to it - separate callers rather than
one, because a judge built by `build_request` would carry the trial's own model
and swept knobs, and a grader that moves with the thing it grades measures the
pair. What holds the generated code to that is `check_scorer_calls`: the scorer
declares in `SCORER_CALLS_PER_ROW` how many calls grading one row places, and
every scored row is checked against the ledger, so a judge reaching `litellm`
around the door stops the run on the first row instead of under-counting every
row after it. The number the held-out refusal sizes itself from is derived from
that same declaration rather than kept beside it.

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
approved figure. It costs two things and the comment beside the line now names
both: the SDK's pre-run objection to an unpriced model drops from a refusal to
a warning, and the same switch returns early from `check_and_approve`, so the
SDK's whole-phase estimate-versus-limit gate stops refusing too. Nothing
replaces that with a second estimate - one obliged to agree with the SDK's own
is the two-caps defect this change already rejected, and a flat conservative
rate applied to a whole phase would refuse runs that fit. What is lost is
stated instead: a phase that does not fit spends up to the approved total and
stops partway, where it would have refused having spent nothing. An
undisclosed effect of a flag that governs spending is what the bytes buy out.

Two of the smaller entries below are the launch instructions themselves. Each
one told the assistant to start a fresh process naming one variable, and each
is now a process that stops on arrival unless two more are set with it; leaving
those sentences as they were would have handed a reader a command whose only
outcome is the refusal. They name the figures and point at the document that
defines them rather than restating what those figures are.

Resident moves by the smallest amount that keeps the flow honest, and the
judge's routing did not move it at all. `SKILL.md` owns the order of the run,
so it says that a paid process is launched with the approved figures and that
one given none of them stops - one sentence, pointing at the reference that
names them. The alternative was to leave the flow silent about a stop it can
now produce, and a halt with no home in `SKILL.md` is a halt an assistant meets
for the first time in an error message. How a scorer places its calls is a
detail of writing the wrapper, so it belongs to the reference that stage loads
and can leave.

Where the measured figures come from:

    0051 resident measured                                  84_474
    the launch rule in the stage that spends                  +235
    resident measured here                                  84_709

    0051 total measured                                    369_593
    sdk-execution.md                                      +17_572
      the approved figures, their three refusals, and
        the two SDK settings with what one of them
        gives up, all before the import                5_351
      the ledger, the reported-cost list beside it,
        and the two declared counts                    2_358
      the three functions reading the ledger           2_434
      `place_call` with its debit, its two callers,
        `check_scorer_calls`, and `task_score` moved
        onto the call path it now shares               2_543
      the two-gate paragraph, the judge that made the
        second gate necessary, and the rejected budget 2_137
      the rule for generating a judging scorer, and for
        a preserved one the wrapper cannot route        1_174
      the held-out pre-loop refusal and its cost read
        from the ledger rather than one call's return    753
      the held-out opening                               290
      the baseline's running total                       188
      the two launch instructions, now naming what
        the process will stop without                    159
      the run-bounds pointer and the owns-list           185
    run-safety.md                                          +2_091
      the three launch figures, replacing the sentence
        that stated the discipline and wired none of it   1_060
      what happens when a phase reaches the remaining       404
      the held-out approval, all rows or none               262
      the closing check, and the running total's
        destination                                        365
    SKILL.md                                                 +235
    total measured here                                   389_491

Both ceilings sit under seventy bytes above their measurement, in line with the
57 that 0051 left: enough to reword a sentence without a successor entry, too
little to admit a rule.

# 0052 - the ceiling reaches the code

follows: 0051
resident-ceiling: 84_760
resident-measured: 84_709
total-ceiling: 397_221
total-measured: 397_162

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
per trial, and the calls the orchestrator never sees are debited from a ledger
that starts where the previous phase stopped.

Where the ledger sits is the second half of this entry, and it took three
attempts because the first two were the same attempt. `task_score` is wired
into the decorator, so it runs on every trial of both phases and on every
held-out row; when the evaluator is an LLM judge - what
`evaluation-and-dataset.md` prescribes for summary, explanation, writing and
story tasks - it places a provider call of its own, under a `metric_functions`
contract that passes three values and returns a number, with no ledger among
them. The SDK cannot close it from its side either: at the pinned 0.26.0 the
local evaluator settles a trial's cost before it applies the metric functions,
so a call made inside one is already past that trial's accounting.

The first two answers both routed. A single `place_call` was made the sanctioned
entrance, `call_agent` and `call_judge` were made one line each delegating to
it, and a declared per-row call count was checked against the ledger to catch a
judge that went around. Then a judge appeared that made its declared call
through the door and one more call directly: the count of routed calls matched,
the row scored, and the remaining reported a figure short by that call. Asking
the caller and counting whether it complied had produced two instances of one
class, so the third answer is not another count.

`litellm.completion` and `litellm.acompletion` are wrapped once, at wrapper
setup, and the wrap is what refuses and debits. A hand-written judge that calls
`litellm.completion` - which is what a judge naturally does - is now ledgered
without being asked to be, and there is no sanctioned entrance to miss.
`place_call`, `call_agent` and `call_judge` survive as conveniences carrying the
things routing was always genuinely for: a grader on the run's fixed model
rather than the trial's, and the usage and truncation checks that turn a canned
or cut-off response into a failed trial. Each wrapper saves what the attribute
held and calls through it, which is the shape the SDK's own metadata-capture
patch uses, so the two compose whichever installs first.

That door was still half a ledger while it debited only what came back. A
provider call that raises after reaching the provider is billable and brings no
cost home with it, and litellm surfaces a timeout, a rate limit, a dropped
connection and a mid-stream failure exactly that way rather than as a degraded
response. The wrap therefore catches, deducts at the conservative rate - the
answer already given to a price it cannot read - and re-raises the caller's own
exception untouched. Omitted, this overstated what was left by one call per
failure, on precisely the routes that fail more than once; a route failing every
time would have spent the whole approved total without moving the figure that
governs it. `BaseException` and not `Exception`, because an awaited call
cancelled in flight raises `CancelledError`, which is neither of those and had
still reached the provider. The pre-call refusal stays outside the catch: it
placed nothing, so it owes nothing.

A place instead of a rule earns bytes twice over: it is fewer lines than the
count it replaces, and the refusal message it can write is better, naming the
model that was about to be called rather than a label the caller supplied. What
it cost is a paragraph naming its edge, and that paragraph is the point rather
than an apology. The wrap reaches every caller that resolves the attribute when
it calls, and no others - not a module holding a `from litellm import
completion` binding older than the door, not litellm's other spend-capable entry
points (`text_completion`, `batch_completion`, `completion_with_retries`, a
configured `Router`), which nothing here wraps, and not a client that is not
litellm at all. So the guidance says to import a preserved agent or evaluator module after
the door installs, and the declared count stays, no longer as a routing check
but as the one claim nothing else can derive: it sizes the held-out refusal,
which is settled before the calls it is sizing place any of them.

The same reading found two overstatements and both are corrected here. A comment
beside the process-only approval flag closed by saying neither path exceeds the
approved total, which admission by a flat conservative per-call figure, over a
wrapper that sets no `max_tokens`, cannot promise for a strong-tier or judge
call; it now says what the two paths do and points at the document owning the
rule that this is never a hard billing cap. And two reads of the ledger - the
held-out cost slice, and the per-row call count - are windows on a shared list
that only a sequential run makes exact. That was true and unstated: the SDK
resolves an unspecified `parallel_config` to sequential execution and nothing
here specifies one. It is now written beside the list both reads share, and a
test fails if either generated `optimize_sync` call starts asking for
concurrency.

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

The one paragraph that is neither code nor its comment records why the SDK's
`ExecutionBudget` was not adopted: it keeps its state in a single Python object
and therefore cannot cross the process boundary the phases are separated by, so
it would have needed reseeding per process while adding a second cap obliged to
agree with the first.

Two of the smaller entries below are the launch instructions themselves. Each
one told the assistant to start a fresh process naming one variable, and each
is now a process that stops on arrival unless two more are set with it; leaving
those sentences as they were would have handed a reader a command whose only
outcome is the refusal. They name the figures and point at the document that
defines them rather than restating what those figures are.

Resident moves by the smallest amount that keeps the flow honest, and neither
the judge's routing nor the door that replaced it moved it at all. `SKILL.md`
owns the order of the run, so it says that a paid process is launched with the
approved figures and that one given none of them stops - one sentence, pointing
at the reference that names them. The alternative was to leave the flow silent
about a stop it can now produce, and a halt with no home in `SKILL.md` is a halt
an assistant meets for the first time in an error message. Where a scorer places
its calls is a detail of writing the wrapper, so it belongs to the reference
that stage loads and can leave.

Where the measured figures come from:

    0051 resident measured                                  84_474
    the launch rule in the stage that spends                  +235
    resident measured here                                  84_709

    0051 total measured                                    369_593
    sdk-execution.md                                      +25_243
      the approved figures, their three refusals, and
        the two SDK settings with what one of them
        gives up, all before the import                5_886
      the ledger, the reported-cost list beside it,
        the two declared counts, and what a window
        on that list depends on                        3_161
      the three functions reading the ledger           2_434
      the door - one refusal, one debit, the debit
        for a call that fails after reaching the
        provider, the two wrappers, and the install
        that survives a second execution of this
        wrapper                                        4_772
      `place_call`, its two callers, `check_scorer_calls`
        and `task_score`, over a door they no longer
        have to be the only way to                     1_773
      the two-gate paragraph, the place-not-a-rule
        design and the edge it does not reach -
        litellm's own unwrapped spend-capable names
        among them - the judge that made it
        necessary, and the rejected budget             3_560
      the rule for generating a judging scorer, and
        the two shapes of preserved evaluator, one
        of which must not be debited twice             2_062
      the held-out pre-loop refusal and its cost read
        from the ledger rather than one call's return    753
      the held-out opening                               310
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
    total measured here                                   397_162

Both ceilings sit under sixty bytes above their measurement, in line with the
57 that 0051 left: enough to reword a sentence without a successor entry, too
little to admit a rule.

# 0052 - the ceiling reaches the code

follows: 0051
follows-resident-measured: 84_474
follows-total-measured: 369_593
resident-ceiling: 84_760
resident-measured: 84_714
total-ceiling: 411_391
total-measured: 411_332

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
response. It is charged at the conservative rate - the answer already given to a
price it cannot read - and the caller's own exception is left untouched.
Omitted, this overstated what was left by everything that failed, on precisely
the routes that fail more than once; a route failing every time would have spent
the whole approved total without moving the figure that governs it. Every shape
of failure is covered without naming any of them, including an awaited call
cancelled in flight, which raises `CancelledError` and is not an `Exception` -
the money is committed before the call and simply stays committed when the call
does not come back. A refusal is the one path that owes nothing, and it happens
before anything is committed, because it placed nothing.

One debit per invocation is honest only while an invocation is one billable
request, and it was not. litellm hands the OpenAI-shaped client a nonzero
`max_retries`: measured against a local HTTP server that counts what arrives,
one call on an `openai/` route placed three provider requests, and the same call
passing `max_retries=0` placed one. Several failed requests under a single
conservative debit is the mild half. The half that never raises is why this went
into the code rather than into a caveat - attempt one times out after the
provider generated its tokens, so it is billed; the retry answers 200; nothing
raises, no conservative branch runs, and the ledger books the retry's exact price
while omitting the request that was paid for. The shortfall arrives wearing a
measured figure. So both wrappers set that default themselves.

Pinning it bought a claim it does not support, and the claim was written down
twice before anybody re-measured. One wrapped call is one billable request only
while nobody spells retries the other way. On the same counting server: a caller
passing its own `num_retries` of two placed FIVE requests through the door, and
a process-wide `litellm.num_retries` of two placed three, because litellm copies
that value over the client's `max_retries` and runs a retry loop of its own
above it. Defaulting the second spelling to zero as well does not work and looks
as though it does - the value is read as `kwargs.get("num_retries") or
litellm.num_retries`, so a literal zero is falsy and the process-wide figure
governs anyway, while on the async entry point the same zero IS honoured. A
safeguard that holds on the name nothing generates and fails on the name every
generated line uses is worse than none.

The rule the guidance already carries is that the caller nobody wrote is the one
to design for, and both of those spellings arrive from exactly there: a
preserved agent or judge, imported after the door on this guide's own
instruction, carrying whatever retry setting its author chose. So the answer is
not a third kwarg. The debit moves to the front of the call: the door reads the
worst case the request states - one, plus each retry either spelling asks for,
multiplied by one attempt per `fallbacks` entry - refuses unless the remaining
covers all of it, and reserves the whole figure before placing anything. A
success settles that reservation down to the price that came back; a failure
leaves it standing, which measured exact against every configuration above,
where the old debit booked one conservative figure for up to five billable
requests.

Two alternatives were measured and neither survived contact with the library.
Counting at the transport, through the documented `client_session` hook, would
have seen retries, fallbacks and the non-chat entry points at once; it is
consulted only by the OpenAI-family client, and a counting transport saw one of
one request on an `openai/` route and none of one on Anthropic, Gemini or
OpenRouter - the route this walkthrough's own example key belongs to. Counting
at the logging layer fails differently: a custom logger fired one pre-call and
one success event for three billable requests, and three pre-calls and one
failure for five. Reconciling a reservation against what really happened is also
out, because nothing on the response says: a reply returned after four billable
requests carries the same hidden parameters as one returned after one, with no
attempt count on it anywhere. That is why the settled figure on a retried
success still misses the attempts that failed before it, and why that is written
beside the reservation as a gap rather than left to be discovered.

What the pin is now for is stated as what it is. It is not the invariant; it is
what makes the count possible, because an absent `max_retries` is the client's
own default, which moves between releases and cannot be read off the request,
while zero is a figure the door can assert. A caller who wants the resilience
sets the number itself and is charged for it. The trade is unchanged and still
belongs in the comment beside the line - a transient 429 or 500 now reaches the
caller instead of being absorbed - and it still contradicted a standing rule in
both of the places that stated it: `run-safety.md` said to preserve the retry
behaviour already present in the user's client, and `sdk-execution.md` opened by
saying to leave the SDK and provider retry defaults unchanged. Two statements of
one rule is how a rule gets changed in one place, which is the defect this
repository keeps finding, so both now carry the same single exception and point
at the line that takes it. Finding the second copy is what the whole-document
read is for; the diff showed only the door.

Reserving first closed a second finding for free, and refuted a sentence this
entry used to carry about it. Resolving the wrapped attribute was called
sufficient for the money being seen, and it is only necessary: litellm's
`fallbacks` handling re-enters `litellm.completion` once per attempt, so every
attempt went through the door and so did the invocation above them, and the
ledger ended up holding one entry more than the run placed requests - three
against two with one fallback, four against three with two. That surplus is not
a rounding error where a scorer declares what it places: `check_scorer_calls`
compares a declared count against exactly that number, so a compliant judge was
stopped by a red that was the counter's fault. The door now counts an INVOCATION
once, marking itself in flight through a context variable, so a re-entry taken
underneath it is part of it. A context variable rather than a flag because a new
thread starts with a fresh context and a new task copies the current one, which
is the behaviour both the thread pool and the async fallback path need.

A place instead of a rule earns bytes twice over: it is fewer lines than the
count it replaces, and the refusal message it can write is better, naming the
model that was about to be called rather than a label the caller supplied. What
it cost is a paragraph naming its edge, and that paragraph is the point rather
than an apology. The wrap reaches every caller that resolves the attribute when
it calls, and no others - so a module holding a `from litellm import completion`
binding older than the door misses it, and so does a client that is not litellm
at all. Enumerating the exceptions instead of stating that rule got two of four
names wrong, which a sentinel patched over `litellm.completion` settles in a
second: `batch_completion` submits it to a thread pool and a configured `Router`
calls it, so both go through the door. Five names really do reach the provider
along their own path, and the same five are now written in all three places that
enumerate them, because three copies said three different things: the guidance
had `text_completion`, `completion_with_retries`, `embedding`, `responses` and
`image_generation`, the test's own comment had the first three, and this entry
had the first two under a category standing in for the rest. Every one of the
five is now probed by the sentinel rather than asserted from a memory - two of
them were named in the guidance and never measured at all, which is how a list
starts drifting from the library again. A list of names has to track a library
nobody here controls and the rule does not, so the guidance carries the rule
plus worked examples, and the test measures them on whatever litellm is
installed rather than on the release anyone remembers - which is exactly the gap
a fixed table would have hidden. It matters beyond tidiness: a later passage branches a
preserved evaluator on this exact question, warning that hand-debiting a call
the door already saw charges the approved total twice and refuses a run that
fits, and a reader with a `Router`-based agent was being sent into the wrong
half of it. So the guidance says to import a preserved agent or evaluator module after
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

That note then made a third overstatement of its own, in the sentence promising
concurrency costs no money. The refusal was a check followed by a call with
nothing held between them, so N callers reading one remaining all pass it and
all place: measured by installing the door on the real library and letting
`batch_completion` fan out eight ways against a remaining that funded exactly
one call, eight requests reached the local server and the total finished below
zero. The note that replaced it said no lock could close that, on the grounds
that the lock would have to be held across the provider call - which was true of
a debit taken afterwards and false of a reservation taken before. Committing the
money in front of the call closes it, and it rather than any lock is what does:
the window between deciding and spending used to hold a whole provider round
trip, and the same eight-way fan-out against the same remaining now places one
request and stops. What is left of that window is microseconds of bytecode, and
one lock across the read and the append closes that too without ever touching
the async door's event loop - measured by deleting it, which the fan-out no
longer notices, so the lock is asserted where it is written rather than pretended
to be exercised. What concurrency still costs is the exactness of the two
window reads, which is a stopped scorer rather than money, and that is what the
note says now.

The ledger's last gap was that it died with the process and nothing emitted it.
The figure the next phase is launched with was being assembled by hand from the
SDK's tracked cost, which is a different and smaller quantity - it carries
neither the conservative deduction for a call no route priced nor the spend on
trials the response checks refused - so the claim that the next phase is bounded
by what this one produced was not true of the number the code produced, and the
closing check asked for a total nothing computed. Each paid phase now ends on
one printed line: the calls it placed, what it spent, what it was launched
having spent, what that leaves of the approved total, and how much of the spend
bought no measurement. The handoff sentence and the closing check both point at
that figure now.

Where that line was written was the whole of it, and it was written where
nothing ever goes wrong. It sat as a statement after the search returned, and in
the connected phase below five assertions including one on the portal URL, while
the failure handler above it exits with `SystemExit` - so the phase that most
needs the figure printed nothing at all. Round five made that likelier on
purpose, since pinning the client's retries lets a transient 429 surface where
it used to be absorbed: a $5.00 approval, a baseline spending $0.90 over eight
trials, a rate limit on the ninth, and the connected phase launched believing
nothing had been spent and handed the whole $5.00 again. It is registered with
`atexit` now, which covers an unhandled exception and a `SystemExit` alike and
runs once, and the two statements are gone so a finished phase cannot print two
totals for a reader to choose between. Its arithmetic was wrong as well as its
placement: printing this process's spend against the whole ceiling and calling
the difference remaining reads as $0.90 of $5.00 with $2.10 left, which is three
figures that cannot all be true. Naming the fourth - what the process was
launched having spent - makes the line add up and makes it the handoff figure.

The last of the three figures never reached the code either, and the test that
proved it did could not have seen it. `TRAIGENT_FIRST_RUN_PHASE` is read before
`load_dotenv` and popped after, under a comment saying a stale file cannot opt
into connected work; the three money figures were read after it, and
`load_dotenv` fills an absent process variable from the file. Measured with an
empty process environment and a `.env` naming all three, the block ran to
completion on the file's ceiling and wrote it into `TRAIGENT_RUN_COST_LIMIT` -
the number the per-trial admission check, the door's refusal and the held-out
refusal all key on. Four sentences promising the figures come from the process
and never from a file were false. They are true now because the three names are
captured before the file is loaded and popped afterwards, exactly as the phase
flag is. The gate's own test survived five rounds because its temporary project
root held a script and no `.env`, which is a condition no real run is ever in -
the walkthrough tells the user to create one for their provider key. Its fixture
now writes a `.env` carrying all three figures at values nobody approved, so a
reading order that ever consults the file fails an assertion instead of passing
quietly. The preflight mechanism that already refused a persisted approval flag
refuses these three and the derived limit beside them, which is one existing
check extended rather than a second one invented.

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
    the launch rule in the stage that spends                  +240
    resident measured here                                  84_714

    0051 total measured                                    369_593
    sdk-execution.md                                      +38_532
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
        design and the edge it does not reach, the
        judge that made it necessary, and the
        rejected budget                                3_560
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
      the client's own retries pinned off on both
        wrappers, what that trades away, the
        failed-call comment that now says what one
        costs, and the carve-out in the
        leave-the-defaults rule above                  2_240
      the edge stated as a rule with worked
        examples, and the branch that reads it           701
      what concurrency costs, beside the two reads
        that share the list                              629
      the line each paid phase ends on and the
        prose it corrects                              1_103
      three stdlib imports                                50
      the approved figures captured before the file
        is loaded, popped after it, and read from
        that capture                                   1_201
      the ledger line moved onto the way out, the
        figure it was launched with, the two
        statements it replaces, and the two
        passages that now point at it                  1_087
      the door reserving what one invocation can
        place instead of debiting what one attempt
        did - the lock and the in-flight mark, the
        worst case it reads off the request, the
        reservation and its settlement, the two
        wrappers over them, the two alternatives
        that lost, which half of it closed the
        concurrency exposure, and the rule
        statements the measurements corrected          5_860
      the retry rule extended to the caller the
        door exists for                                  418
    run-safety.md                                           +2_967
      the three launch figures, replacing the sentence
        that stated the discipline and wired none of it   1_060
      what happens when a phase reaches the remaining       404
      the held-out approval, all rows or none               262
      the closing check, and the running total's
        destination                                        360
      the handoff figure named as the printed
        ledger rather than tracked cost                     108
      the one exception to preserving a caller's
        retry behaviour, what it costs, and that an
        explicit count is charged rather than
        absorbed                                            474
      what a phase that died having spent leaves
        for the next one                                    299
    SKILL.md                                                 +240
    total measured here                                   411_332

Both ceilings sit under sixty bytes above their measurement, in line with the
57 that 0051 left: enough to reword a sentence without a successor entry, too
little to admit a rule.

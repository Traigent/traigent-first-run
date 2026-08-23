# Run Safety and Result Honesty

Use this reference for setup, dry-run, paid execution, portal verification, recovery, and claims.

## Contents

1. Environment and privacy
2. Static and mock validation
3. Approval and budgets
4. Connected-run readiness
5. Baseline and optimization
6. Post-run verification
7. Recovery

## Environment and privacy

### Why the install sits where it does

Stage 4 first establishes that the project is scoreable and stage 5 resolves the target
environment. Installing earlier can therefore modify the wrong environment or spend time on a
walkthrough whose task is not yet anchored. After that point, the remaining capability and mock
checks need the installed SDK, so no useful independent work overlaps the install. Keep this one
foreground command with its complete resolver diagnostic; explain the wait and do not delegate it.
Nothing in this guide requires sub-agents, which not every supported assistant provides.

### Rules

- Reuse an existing compatible isolated environment. When none exists, use the conventional
  `.venv` with Python 3.11-3.13; do not replace the project's interpreter without approval.
- Resolve every candidate recorded during inventory before touching one, and name the selected
  environment by absolute path. Prefer the single compatible environment inside the project root.
  Ignore environments owned by another project or by the assistant's tooling; a current-project
  environment managed outside the root is an external candidate, not an ignored one. More than one
  compatible candidate, or external-only environments, get one question with a recommendation and
  every candidate path.
  Before adopting an environment with other dependents, name the exact install and confirm once,
  offering a separate `.venv-traigent`; a run-created environment or one containing only this
  walkthrough's pinned set proceeds without repeating that question.
- Create and then activate the environment before installing: `source .venv/bin/activate` on
  macOS/Linux, `.venv\Scripts\Activate.ps1` on Windows PowerShell (a first run there may need
  `Set-ExecutionPolicy -Scope Process RemoteSigned`). Confirm `sys.prefix` points inside the
  environment before `pip install`, or the install silently lands in global Python and the run
  cannot find `traigent`.
- Only when `.venv` already exists but uses an incompatible interpreter, preserve it and create
  `.venv-traigent` with a supported interpreter, for example
  `python3.13 -m venv .venv-traigent`. Keep this fallback name as an implementation detail rather
  than asking the user to choose an environment name.
- Keep dependency installation as its own action class. It may proceed without another approval
  only inside that environment, from the exact packages and versions recorded for the top-level
  requirements plus their package-declared dependencies, as a package-artifact-only fetch/install
  with no provider or Traigent calls, private-data transfer, or user/project code execution. Prefer
  a fully pinned, hash-checked requirements file and wheels; stop if fulfilling it requires source
  builds, additional undeclared top-level packages, or code execution. A user or environment
  install-approval policy still takes precedence.
- If the project has no compatible exact SDK declaration, install the tested pins from
  `assets/requirements-first-run.txt`. Never run an unversioned `pip install traigent`: on an
  unsupported interpreter, package resolution can select the unrelated obsolete `0.0.1` release.
- Before creating the environment or installing anything, run every available bundled component
  check whose complete path needs only the Python standard library and local project files.
- Verify installed packages and public signatures before generating SDK integration code.
  Dependency installation does not authorize importing or executing user/project modules.
- Verify SDK capabilities from the installed version and CLI rather than hardcoding what installs
  "today."
- After every applicable free component, capability, and safe mock check, select the credential
  handoff file: a local file the user explicitly identified for this run, or otherwise the
  target-project `.env`. Verify its owner-only mode, check only key presence, and do not copy or
  move its values into another file or ask the user to enter an already available key again.
  Preserve existing values, comments, unrelated keys, blank alternate-provider entries, and any
  Traigent key already present; add only the genuinely missing selected-provider entry. Before
  opening it, require mode `0600` on POSIX. Resolve the selected handoff file relative to its Git
  worktree as `<credential-file-relative-path>`. Root `.env` uses
  `git -C "<credential-file-worktree>" ls-files --error-unmatch -- .env`: exit 0 means tracked
  and must stop; continue only on exit 1 with no match, and stop on any other status. Preserve an
  effective `/.env` rule and require `check-ignore -q -- .env`; stop before secret entry if the
  effective-ignore check fails. Otherwise run
  `git -C "<credential-file-worktree>" ls-files --error-unmatch -- "<credential-file-relative-path>"`.
  Exit 0 means tracked and must stop; continue only on exit 1 with no match, and stop on any other
  status. Preserve that worktree's `.gitignore` while ensuring it has an effective ignore rule for
  that exact relative path, then require
  `git -C "<credential-file-worktree>" check-ignore -q -- "<credential-file-relative-path>"` to succeed.
  Stop before secret entry if the effective-ignore check fails, and repair the ignore rules. Outside Git, do not create
  `.gitignore`. Stop once only when a key is truly missing. Add or request the Traigent key only
  after the local baseline checkpoint.
- Check presence only; never inspect, paste, or print secret values.
- Hand the file off unambiguously. In a graphical session, launch the opener detached and
  non-blocking: pass the absolute `.env` path as one safely quoted argument, redirect stdin,
  stdout, and stderr away from the assistant's pipes, and start it in the background. On POSIX,
  the `xdg-open` or `open` launch must end with `</dev/null >/dev/null 2>&1 &`; on Windows
  PowerShell, use `Start-Process`. Do not wait for the editor process or interpret its continued
  lifetime as failure; print the absolute path immediately and stop for the user. In a headless
  session, or when no graphical handler is available, skip the opener and print the absolute path
  as the fallback. Name the target line by key prefix - the `sk-`/`sk-or-` provider key after its
  `..._API_KEY=` line; at the later portal gate, name `TRAIGENT_API_KEY=` separately. That gate
  runs this same handoff a second time, on the same file, by these same two rungs - so a headless
  session prints the path there too and opens nothing.
- When a readiness command is asked to write a report file, verify that the file exists after the
  command returns. Some tooling still prints the score to stdout even when `--report` is supplied,
  so stdout is evidence of the score, not proof that the requested file was written.
- According to the documented SDK/service contract, connected runs send configuration keys and
  values, numeric measures, run state, and content-free metadata to the Traigent backend. Except
  for content deliberately placed in a tuned configuration value and observability content the
  project explicitly opts into recording, the contract excludes user prompts/inputs, dataset
  contents and expected outputs, model responses, source code, and credentials from that backend
  transmission. This guide does not independently inspect network packets; stop if observed
  runtime behavior contradicts that contract. Privacy wording describes Traigent's documented
  backend-payload contract, not an independent packet audit: where payload behavior cannot be
  inspected, say the contract was followed rather than claiming network traffic was independently
  audited.
- Treat backend transmission and local persistence as separate boundaries. SDK 0.26.0 writes
  per-example `query`, `response`, and `expected` text to local optimization logs by default. In
  the first-run wrapper, set `TRAIGENT_LOG_EXAMPLE_CONTENT=false` in the process before importing
  Traigent; this retains example ids and metrics while writing those content fields as `null`.
  Keep assistant-created logs beneath ignored `traigent-runs/`; honor and name a preserved
  project-defined results folder. Do not re-enable example-content logging unless the user asks
  after being told the local path, retained content, and deletion responsibility.
- A selected direct LLM provider still receives whatever content the agent normally sends in
  model calls.
- With OpenRouter, OpenRouter receives the request as the gateway and the selected upstream
  inference provider may also receive prompts, examples, and outputs. Automatic routing and
  fallbacks can change that upstream recipient.
- Encode prompt variants as short labels mapped to the text inside the agent function; never put raw
  prompt text as configuration-space values. Configuration choices are synced to Traigent's
  optimizer, so labels keep the actual prompts on the machine.

Ask before any private content leaves the machine, even when the provider key already exists.

At the secret-entry gate, show only the URL needed for the selected service:

- Traigent registration, only once the user already has their access code:
  `https://portal.traigent.ai/register`
- Traigent API keys: `https://portal.traigent.ai/management/api-keys`
- OpenRouter keys: `https://openrouter.ai/keys`
- OpenAI keys: `https://platform.openai.com/api-keys`
- Anthropic keys: `https://console.anthropic.com/settings/keys`

These account/key links are necessary actions, not educational detours. Do not show every provider
link; show only the selected provider and Traigent when each key becomes necessary.

A first-time user reaches that key page one way. They start at `https://traigent.ai` and submit their
email address, and Traigent sends a six-digit confirmation code that proves the mailbox and expires
within minutes. Once they enter it, a second email arrives carrying a single-use access code, valid
for 10 days, that authorizes one portal registration. The registration link in that same email is
deliberately plain and carries no credential, so the code is typed into the page rather than
clicked through. When the user completes portal registration the code is spent, the account's
portal access period starts, and they land in the portal. Their address is already confirmed by
then, so registration does not ask for a second confirmation.

The key is then created, not handed over — which is why the write-scope rule below is the main path
here and not an edge case. Two places create one: the key control in the portal's top bar, which
issues a key in a click or two and is highlighted on a first visit, and
`https://portal.traigent.ai/management/api-keys`, which offers more options. Name the top-bar
control first; it is the shorter path. Either way the key is shown once and cannot be read back, so
say "save it now" while it is on screen rather than afterwards.

Do not assume the user walked the whole path. Getting the second email and registering are separate
acts, and many people read the email and stop. Establish where they actually are before naming a
destination:

- **Already registered, key in hand** - they only need to paste it.
- **Already registered, no key in hand** - registering is not the same as holding a key. The key is
  created in the portal, not issued by registering, and it is shown once, so anyone who skipped that
  step or did not save the value creates a fresh one - the top-bar key control, or
  `https://portal.traigent.ai/management/api-keys`. Say the write-scope rule below at that moment.
- **Not registered, holding an access code still inside its 10 days** - walk the whole remaining
  path rather than naming one destination: open the second Traigent email for the access code,
  register at `https://portal.traigent.ai/register` (given as a clickable link) using that code,
  and then, once in the portal, create a full-access key from the top-bar key control and save it
  as it is shown. Only then return here to paste it.
- **Not registered, with no usable access code** - they never started, they are still waiting on
  one of the two emails, or their code is older than 10 days. All three resolve the same way: send
  them to `https://traigent.ai` as a clickable link. An expired code cannot be revived, and waiting
  will not deliver one that was never requested.

Those four are exclusive on what the user holds, not on how long ago: a run later refused for
account or plan reasons is the spent access period below, not a wrong branch here. Ask which one
applies; do not infer it from how far along they sound.

Registration has to be authorized by that access code, so it is the code, not the URL, that gets a
user in. Never hand the registration address to someone who does not have one yet; the fix is to
start at `https://traigent.ai`.

The confirmation code and the access code are credentials, not navigation. The first proves the
mailbox and the second authorizes creating an account, so never ask the user to paste either one
into chat, never write either into a file or a command, and never repeat one back. Both stay
between the user's mailbox and their browser; the only thing that reaches this machine is the API
key, and it goes straight into `.env`. The registration address itself is not a credential and is
safe to hand over — but only to someone who already holds a code, per the rule above.

The portal access period lasts 10 days from the moment the user registers, and it is what authorizes
product use. The API key is a separate thing: the key authenticates the run and does not by itself
grant portal access, so a perfectly valid key is still refused once the period is over. The account,
its data, and its keys all survive that expiry; runs resume when the user buys a plan on the same
account.

That is a second key-shaped failure whose remedy is the opposite of the read-only one below. If a
connected run is refused for account or plan reasons rather than authentication, stop and report it
with the refusal the service actually returned. Never re-register, never create another key, and
never switch to a different email address to collect a second access period - none of those restore
access, and the last one is what the one-period-per-account rule exists to prevent. Only a purchase
on the existing account brings the run back.

Once portal registration has completed, you may show one short note - "Your
Traigent address was already confirmed, so there is no second confirmation email; your account is
active and your 10-day portal access period has started. Next, create your API key from the key
control in the top bar - grant it full access, and save it when it appears, because it is shown
only once."

The Traigent key must be able to write experiments, not only read them. The connected optimization,
and an exact baseline sync when the installed public API supports one, need that scope. A read-only
key can be rejected at submit time while the optimization drops to local-only tracking - real money
is spent and nothing appears in the portal. This governs
the user's very first key, not just a later one, because registration hands over no key at all.
A manually created key defaults to read-only, so grant it full access rather than accepting
the default. Say this at the moment the user creates the key, not afterwards: the failure is cheap
to prevent and expensive to discover, because by the time it shows up the spend has already
happened.

Nothing else belongs in `.env`. Do not add a backend or API URL - the installed SDK already points
at the production service, and a stray override silently sends a paid run somewhere the user cannot
see it.

SKILL's opening gate owns pre-stage-5 interpreter selection and the timing of the required opening
readiness score. The environment selected or created in stage 5 remains authoritative for the
connected run.

Follow SKILL stages 4-7 for ordering; this reference does not define a second flow.

For the stage-4 semantic-coverage review, use this outcome inventory rather than an unrecorded
impression. Name the applicable classes in each case's `outcome_classes`, so `sufficient` records
what was examined and an absent class stays visible:

| If the answer is | Speak to |
|---|---|
| rows, sets, or lists | label/value binding, duplicate rows, ordering, empty result, partial overlap |
| numeric | tolerance edges, sign, units, formatting and rounding |
| a classification | near-miss labels, an absent label, case and whitespace |
| free text | omission, contradiction, added claims not in the input |
| structured (JSON/schema) | missing optional field, wrong type, extra field, null vs absent |
| code or SQL | parse or compile failure, correct but materially different implementation, full test pass, partial test pass, wrong result after a clean exit, runtime error, timeout or resource-limit breach, forbidden side effect |

Binding is first because a token comparison cannot see a correct value paired to the wrong key.
The deterministic permutation probe asks about that one class mechanically; the rest still needs
the recorded semantic review.

Identify execution evaluators from their complete call path. A scorer enters that path when it
executes or imports candidate/model output as code, shells out with it, or submits it to a code or
SQL engine. Apply the containment contract below before calibration; if it cannot be met, do not
run that evaluator in calibration, mock, baseline, optimization, or validation.

## Static and mock validation

The bundled `scripts/preflight.py` is a static/free gate. Run its component checks before
environment creation or dependency installation. It may read files and public package metadata,
but it must not:

- Import user modules.
- Execute the agent or evaluator.
- Make model/provider calls.
- Contact Traigent or consume optimization quota.

The static gate checks environment, package metadata, dataset structure/quality, model naming, and
safe configuration. It deliberately does not decide how the SDK normalizes rows, injects
configuration, binds agent inputs, or invokes evaluator callbacks. During the first
standard-library-only pass, omit optional model-pricing checks and interpret a missing SDK as a
deferred SDK finding, not as a failure of dataset-quality checks. Dataset heuristics use canonical
`input`/`output` fields unless the assistant explicitly selects other dot paths with
`--input-field` and `--expected-field` from the user's schema. Those choices configure only the
local quality view; they are not aliases, rewrites, or proof of SDK acceptance.

### Execution-evaluator containment

Treat model-written code or SQL as untrusted active content whenever an evaluator executes it.
This requirement applies to calibration and every scored callback in baseline, optimization, and
validation, including generated or preserved evaluators. Never execute that content inside the
assistant, SDK, optimizer, or evaluator-orchestration process, or in an ordinary subprocess that
shares the host's access.

Use a fresh disposable sandbox for each candidate, or reset it to an equivalent clean state, with:

- Network disabled; no provider, Traigent, or project credentials; and a minimal environment.
- No writable host home or project mount. Mount only required tests and fixtures read-only, plus a
  bounded disposable scratch directory.
- An unprivileged identity, no elevated capabilities or privilege escalation, and an OS-enforced
  container, VM, or sandbox boundary appropriate to the host.
- Hard limits on wall-clock time, CPU time, memory, process count, open files, file size and scratch
  space, and captured output.
- Terminate the whole descendant process tree on completion or any limit breach, then dispose of
  the sandbox. Run SQL only against a disposable seeded database, never a production
  connection or credential.

Record the boundary, limits, mounted inputs, and permitted side effects in the run plan. Report a
runtime error, timeout or resource-limit breach, forbidden side effect, and sandbox failure as
distinct outcomes; never retry one outside containment. A virtual environment, stripped builtins,
removed keys, proxy blackholing, an ordinary subprocess, or a timeout alone is not a sandbox.
Resource limits alone do not provide isolation from the filesystem, network, or secrets. The
calibration helper's child process separates scorer imports from the assistant, but a scorer that
executes candidate content must still delegate that execution to the declared sandbox. If no
available boundary enforces these properties, do not run the execution evaluator or paid
optimization against it; use non-executing static/parser/compile checks or pause for a safe runner.

### Deterministic calibration and mock plumbing

Deterministic calibration is a separate execution gate and always requires a recorded `sufficient`
evidence-backed semantic-coverage verdict. Before environment setup, run only a non-executing
evaluator whose complete call path is local-only, side-effect-free, and standard-library-only. An
execution evaluator waits until its declared local dependencies and sandbox are available; every
candidate execution must satisfy the containment contract above. A non-executing evaluator that
needs a declared local dependency also waits until that dependency is installed. Run either before
creating `.env` or requesting a provider key. A generic outside-review wait is not a gate; pause
only when one unresolved product-grading ambiguity would materially change correctness or ranking.
Do not execute an LLM judge or an uncertain or external evaluator without explicit approval in the
stage where it runs, covering recipients, data, calls, runtime, and spend.

A Traigent mock run is a separate plumbing check:

- Use a fresh process.
- Set `TRAIGENT_OFFLINE_MODE=true` and `LITELLM_LOCAL_MODEL_COST_MAP=true` before imports. Traigent
  offline mode does not by itself suppress LiteLLM's import-time remote pricing-map fetch; use both
  in every generated mock wrapper and every documented free mock invocation.
- Confirm every agent and evaluator model path is interceptable. LiteLLM/LangChain paths may be
  intercepted; raw provider SDKs, subprocesses, HTTP services, tools, and custom judges may still
  make real calls.
- Treat proxy variables, removed keys, and mock flags as defense in depth, not as a sandbox or
  proof that an invoked path is local-only.
- If any path cannot be proven free, do not call it a free dry-run. Ask approval for the smallest
  real probe or use static validation only.
- If mock validation says trial settings are not consumed, return to the stage-2
  repair/continue/pause choice. Enter stage-3 adapter repair and revalidate only after the user
  chooses its scope; do not open a credential file while optimization remains phantom.
- Exit the process after mock validation. Mock state has no reliable public undo.

Uniform mock scores can be expected for output-based evaluators. Plumbing success means trials
execute without failures; it does not mean mock accuracy is meaningful.

Mock results may contain a positive estimated `total_cost`. That is pricing metadata, not evidence
that a provider billed the account. Real billing evidence requires a real provider call plus the
provider/SDK usage record.

The converse also holds: OpenRouter `:free`-suffixed model ids genuinely cost `$0`, so judge a real
run by trials executing and nonzero token usage, not by a zero cost - do not misflag a legitimate
free-tier run as mocked.

### Config-space document

`scripts/readiness.py --config-space` scores the agent pillar from the space this run actually
built. A file found before the current enhanced search - including one left by an earlier guided
run - is historical context only. Its existence, timestamp, hash, or non-empty `wired` list cannot
prove current wiring. Record its provenance and omit it from opening and stage-4 readiness. What
those scores report the agent pillar from instead is the read of the agent's own source they are
passed as `--agent-knobs`, never this file.

The rule binds the run, not the invocation that reports. Omitting the document from the opening and
stage-4 calls describes what those calls pass; a second call scoring the same file to see what the
number would have been reads as costless, and it is not: its output is evidence the moment it is
written down, and a figure sitting beside the real one gets quoted. So the document is not scored
in this run in any invocation, and no number derived from scoring one appears in the report, the
findings, or the bundle a reviewer is handed. Calling such a call internal is a claim about the
card and not about those documents. A run does not close on a second number, and it does not open
beside one either: it leaves no exploratory scoring at the opening gate.

A scoreable file means one thing: *this is the space the search that just completed received*.
The generated wrapper serializes the finalized space, removes any earlier file before the call, and
writes `traigent-runs/config-space.json` only after the search returns nonzero trials. Only that
current-run file enters closing readiness. A stopped, failed, or zero-trial search emits none, so
the agent pillar is scored from absent evidence and its 45 ceiling stays in force - the closing
score cannot exceed it.

The read's KNOBS half is deliberately not allowed to establish the space at the close, and this is
the only score in the run where it is left off. The opening read says what the agent makes
reachable; this score says what the search actually received, and they are different quantities.
Letting a read of the source stand in for a document the search never emitted would lift this
ceiling on exactly the runs it exists for - the ones that stopped, failed, or bought no trial.

Its BUILD half travels, and only where a config-space document decides the space beside it. Those
four checks answer how the agent is put together, which no config space makes any claim about, so
there is nothing here for a source read to stand in for and no ceiling it can reach. Dropping them
would report four checks falling to unanswered between the opening card and the closing one while
nothing about the agent had changed - the same fall the opening gate already refuses for the knob
half. Where no document reaches the close, pass nothing: the knobs half would establish a space the
search never received, and the two halves arrive in one file.

`agent-no-varying-knobs` is advisory whenever neither a document nor a reading reached the scorer,
because the scorer cannot tell a document withheld before the search from one the search failed to
produce - both are the same absent input. So on a closing card after a stopped, failed, or
zero-trial search, `status: OK` describes only the evidence this cap was given, and is not a verdict
that the search succeeded. `recommended_action` reads `proceed` there only when nothing else blocks
and nothing else is asking: an asking cap carries its own remedy into that field, so `proceed` on
this card is the absence of every other finding rather than a statement about this one. Report that
search's outcome from the run itself - trials executed, spend, the error it stopped on - and never
let an advisory agent cap stand in for it. Whether a search that produced nothing may be retried or
paid for again is the approval question it always was, decided on that outcome, not on this score.

These are the only fields the scorer reads and the only keys it accepts: any other key is refused
by name (exit 2), listing the fields it may declare and naming the closest when there is one,
because it cannot be told from a misspelling of one - `max_trial` for `max_trials` is one
character, and it raised the band. A field that is
present but malformed is refused with a message naming it (exit 2), never
scored around - a document the scorer cannot read is not a document it may guess at. Refusal turns
on the *value*, not on how JSON spelled it: an empty list, a `null` and a `0` where an object
belongs are malformed, not absent, and are refused rather than read as an empty object; conversely
any value the documented type admits is accepted however it was written, so a document that scores
does not become an exit 2 because a writer emitted `12.0` instead of `12`.

Exit 3 from any of the three scripts is a different statement and must be routed differently: it
means the script itself failed, not that the user's material is wrong. Nothing was checked or
scored, so present no result and no band; say the check could not run, and never relay it as a
finding about their dataset, evaluator, or agent.

The table below is not a second description of the schema. `readiness.py` declares the field set,
each field's type, and the domain of every value inside it once, in `CONFIG_SPACE_FIELDS`, and both
the validator and this table are read from that declaration - `tests/test_skill_package.py` fails
when they disagree. So a field is either declared there and validated, or it is not a field.

| Field | Type | Required | What the scorer does with it |
|---|---|---|---|
| `knobs` | object: knob name to a non-empty list of scalar candidate values | one of the two | the preferred spelling; a non-empty `knobs` wins over `configuration_space`. A document declaring neither key says nothing about the space and is refused; `{"knobs": {}}` declares an empty one and scores 0 under the cap. Every entry's value must be a list, and a knob written as a bare scalar is **refused** - dropping it would shrink the space silently and often *raise* the score. A list with nothing in it is refused for the same reason: a knob with no candidate values is not a narrower space, and scoring it printed a wired-knob count and a combination count the document itself contradicts |
| `configuration_space` | same shape | accepted alias | read only when `knobs` is absent or empty. Emit `knobs`; never both. Whichever key is present is type-checked, so a malformed alias cannot hide behind a well-formed preferred key |
| `max_trials` | positive integer | no | the search-space sub-score is read against it: the score follows how many distinct configurations the run will actually try, and is damped when the declared space is more than twenty times the cap. Omitting it costs a step - a document that does not declare a budget does not establish that the run will compare the whole space, so the sub-score is held one step below full credit exactly as an oversized space is. **Emit it.** Deleting the field can never buy full credit. Deleting it can still raise the score from below, where the budget is the smaller number: on one 12-configuration space, `max_trials: 2` scores 35 and `max_trials: 1` scores 0, against the 70 the field's absence earns. A budget of one is a real statement that the run compares nothing; silence measures nothing. Any integral number is read, however JSON spelled it: `12` and `12.0` are the same budget, and an integer of any size is read as itself. A fractional value, zero, a negative, a boolean, or a non-number is refused |
| `wired` | list of knob names | **yes - always emit it** | the names the agent actually consumes; only these are scored. Do not rely on omitting it or sending `[]`: a document that does not state what the agent consumes attests nothing, and the scorer treats that as nothing-to-search rather than as "all of them". Emitting the list is the whole point of the document. Every name must be a knob of the declared space - a misspelled one is **refused**, because it matches nothing, silently shrinks the scored set, and makes the card print a wired-knob count the document contradicts |
| `bounds` | object: knob name to `{"low": number, "high": number}`, low below high | no | per-knob override of the scorer's canonical numeric ranges; an entry missing `low` or `high`, carrying a non-numeric or non-finite edge (`"inf"` or `"nan"`, either of which would collapse a genuinely sweeping knob), naming a knob absent from the space, declaring a range with no width (`low` above or equal to `high`), or declaring one whose width is unmeasurable even though both edges are finite and ordered - overflowing to infinity (`low: -1e308, high: 1e308`) or underflowing the noise floor to zero (`low: 0.0, high: 5e-324`) - is refused. A zero-width or unmeasurable range breaks the noise floor and span a knob is measured against, so two nearly-identical values read as a full sweep, or a genuine sweep collapses to nothing to search. It sets the noise floor, span, and endpoint coverage - it does not add search values. A numeric string (`"5"`) is accepted for either edge |

Candidate values are scalars: a string, a number, a boolean, or `null`. The scorer deduplicates,
compares and counts them, so an object or an array inside a candidate list is refused rather than
reaching the comparison as an unhashable value, and a non-finite number (`Infinity`, `NaN`) is
refused rather than scored - a knob is measured against the span its values cover, and an infinite
or undefined span is not a sweep.

`prompt_policy` is another name for `prompt_style`, and a document declaring it is refused (exit 2)
naming the spelling the scorer knows. Nothing is renamed on the author's behalf: two spellings of
one search dimension count as two dimensions everywhere downstream, which doubles the reported size
of the space and pays twice for one knob, so the document is corrected rather than guessed at.

`agent-no-varying-knobs` clears as soon as one wired knob carries two effective values. What counts
as "effective" depends on whether the knob has a range at all:

- A numeric knob **with** a range - one of the scorer's canonical knobs (`temperature`, `top_p`,
  `retrieval_k`, and so on) or any knob given a `bounds` entry - needs two values
  separated by more than the noise floor: 0.05 for `temperature` and `top_p`, otherwise 2% of that
  range.
- A numeric knob with **no** canonical range and no `bounds` entry is scored on breadth alone. Any
  two distinct values clear the cap, however close together they are - `[1, 1.01]` counts. There is
  no range to measure a noise floor against, so nothing collapses them.
- A categorical or boolean knob needs two distinct values. Two is also where it scores FULL
  breadth, not half: for a categorical knob there is no knowable "how many values exist" to divide
  by - `thinking_shape` may have two shapes today and four next year - so a denominator invented
  here would only underprice an honest two-value comparison. `model` is the one exception and keeps
  a ladder, because there more choices genuinely is better: 3 or more scores 100, 2 scores 60.
- Any knob declared with exactly ONE value scores 10, whatever its type. It adds nothing to the
  search, so it earns almost nothing; it is not zero because pinning can be the right call made on
  purpose - `temperature: [0]` on a task that must be reproducible is a decision, not an omission.
  Several values that collapse into one is a different case and still scores 0: that author did not
  pin the knob, they tried to sweep it and the sweep does not exist.
- `seed` never counts, however many values it lists, because sweeping it measures run-to-run
  variance rather than quality.
- `max_tokens` never counts either, for the neighbouring reason: it is a resource limit, not a
  behaviour setting, so sweeping it measures whether the answer **fit**, not whether it was good.
  **Never introduce a cap the user did not already have, and never sweep one.** If their agent
  sets `max_tokens`, carry it through verbatim - it works in their daily life. If it sets none,
  send none: the generated wrapper sends no `max_tokens` at any tier, reasoning models included,
  and the provider default stands. **No floor is imposed and no value is refused** either - a user
  may cap it however they like, and reasoning headroom is not predictable, so a floor is a guess
  that breaks runs which would have been fine (`2048` is absurd when the answer is `a`, `b`, `c`
  or `d`).

  A cap of *ours* is worse than one of theirs because it spans two runs: a number that fits the
  baseline's medium model is one the enhanced run's stronger or reasoning model can exceed, so the
  truncation is introduced by this guide on a configuration the user never chose. Either way the
  provider returns `finish_reason == "length"`, and a cut-off answer scores 0 rather than low, so
  the model it happened to loses a comparison it may have won - detected, not predicted, by the
  wrapper's `require_untruncated_completion`.

  Where a bound is genuinely needed, **bound the clock or the trial count, never the tokens**: a
  time limit stops the work and leaves what finished intact, while a token limit corrupts the
  answer at the cut and then scores the corruption.

Three honesty rules govern the file:

- List under `wired` only the controls the agent call really consumes. The scorer checks that every
  wired name is a knob of the declared space, but whether the *agent* reads that knob is an author
  claim it **cannot verify**: it reads the document, never the agent code. Naming a knob the
  agent ignores - a config key read into a variable the prompt never uses, say - inflates the agent
  pillar by scoring a dimension the search cannot actually move. A knob that does not influence the
  agent code is not a real optimization variable. The generated wrapper therefore probes the claim
  where the scorer cannot: `probe_wiring` re-builds the provider request under each alternative
  value and returns one verdict per knob.

  State the probe's limits exactly, because they are narrow. Its exact claim is **request
  visibility, per model** - that changing the knob changes the request dict, under each model in
  the space - and never provider *effect*: only the run can show effect; the probe only rules out
  the dimension that could not have one. The verdict semantics live beside the code in
  `references/sdk-execution.md` - why a `partial` knob is a conditional dimension that loads, why
  only an `invisible` verdict fails, and how a knob acting outside request construction is
  recorded in the `WIRED_OUTSIDE_THE_REQUEST` mapping of knob to *where it acts*, which the load
  prints as an unverified claim for a reader to challenge rather than proving it. If you cannot
  say where such a knob acts, drop it from `wired`.
- `bounds` is likewise self-declared and unverified. It changes the noise floor and the span a knob
  is measured against, so a narrow declared range can turn two nearly-identical values into a
  "varying" knob and clear `agent-no-varying-knobs` on bounds alone. Declare the range the knob
  genuinely has, not the one that scores well.
- Re-write the document whenever the space changes, and before any later score reads it. A stale
  document describes a search that never ran. Because a document from one search would otherwise
  survive the next one failing, the wrapper deletes it before each search rather than relying on
  the next write to replace it - staleness is removed by the run, not by the reader noticing.

The walkthrough's document uses the exact generated space owned by
`references/sdk-execution.md`, with temperature declared at its one task-selected fixed value
because the agent does consume it. A fixed knob scores 10 of 100 on breadth
rather than 0: declaring it says the author considered the knob and decided, which is worth a
little, and worth only a little because the search still gets one value:

The JSON below is the exact-output worked example, so its selected value is `0.0`.

```json
{
  "knobs": {
    "model": ["provider/current", "provider/alternative", "provider/strong"],
    "prompt_style": ["plain", "structured"],
    "thinking_shape": ["direct", "chain_of_thought"],
    "reflect": [false, true],
    "temperature": [0.0]
  },
  "max_trials": 12,
  "wired": [
    "model", "temperature", "prompt_style", "thinking_shape", "reflect"
  ]
}
```

## Approval and budgets

Use two short, contextual approvals; do not ask the user to design budgets, retries, or timeouts.

Before the provider-paid baseline, show only its immediate scope:

- Scope and bounds: the smallest live provider/key check, any pre-baseline LLM-judge calibration,
  preserved baseline or generated twelve-row sweep, tuning rows and limitations, configurations,
  calls, metric, runtime, estimated spend, and one total walkthrough ceiling, defaulting to
  `$5.00`. Call it an execution stop target, not a billing guarantee.
- Recipients: baseline-data services; for OpenRouter, the gateway and allowed upstream/fallback routes.
- Execution evaluators: repeated model-written code or SQL execution, sandbox location, tests and
  fixtures, limits, residual risk, and any external sandbox recipient.

### The pre-spend approval card

The baseline is the first thing in this run that costs money, and the last moment at which changing
what that money is spent measuring against is free. So whenever this run generated or repaired the
dataset or the evaluation method, or an active cap asks rather than blocks, the baseline approval
above carries this card too. It adds no pause of its own - the approval already stops, and this is
part of what it stops with.

Each bullet carries its own condition, because the two triggers do not produce the same card. On the
asking-cap path the customer's own dataset and evaluation method are the material under discussion
and this run wrote nothing, so a bullet written for generated material describes a gap that does not
exist and points at a file that was never created.

- **The gap, and how it was filled** - where this run generated or repaired the dataset or the
  evaluation method. Name the condition in the user's own words - no examples were
  connected, the answer key was written by a model, no grading method existed - and then what this
  run put there instead. Both halves: "a dataset was created", without the gap it answers, reads as
  a feature rather than as a substitution for something they do not have. Where this run created and
  repaired nothing, drop the bullet; there is no gap of ours to name, and describing the customer's
  own material as one is the claim this card exists to avoid making.
- **Absolute paths** - one for each file this run actually wrote: the generated or repaired dataset
  when this run wrote or changed it, and the evaluation method when this run wrote one, each as a
  full path they can open in another window while they read this. A relative path is not openable
  from wherever their terminal happens to be. Two paths at most, not an inventory: every file this
  run wrote is listed at the close, and `references/evaluation-and-dataset.md` owns that list. These
  are here because they are what the decision below is about, so a run that wrote neither lists
  neither.
- **Two rows: the easiest and the hardest.** Not a random pair - the two that show the range, so the
  reader sees what both ends of this dataset look like. Quote each row's input and its expected
  answer from the file rather than describing them. When the rows carry no difficulty tags, pick the
  pair by the ladder in `references/evaluation-and-dataset.md` and name the rung it came from, so an
  unstratified pick is not read as a measured one.
- **What the evaluation method counts as correct.** One or two plain sentences: what it compares,
  what it accepts, what it rejects. This is the half a person can hold against their own idea of a
  right answer, and it is where a generated method most often misses - one that grades wording where
  the product cares about the number will rank every configuration on the wrong thing, and no later
  check in this run would catch that.
- **What an asking cap asked, and what was answered** - where one is active. A cap that asks has one
  home for its question, and some of them own a quoted one already: `dataset-unsound-expected-outputs`
  is put through "A `no` is never a silent edit" in `references/evaluation-and-dataset.md`, which
  SKILL stage 4 routes it to by name, and it is settled there while a repair is still free. Restate
  the finding, the answer taken, and what proceeding on that answer means for the money about to be
  spent - do not put the question a second time in different words, with a different pair of exits.
  Where the cap's route owns no question of its own, this card is that one home and asks it here.
- **Where we are.** `Stage 3/5 · Baseline`, so the choice arrives placed in the run rather than
  loose.
- **Proceed, or fix.** Two named outcomes and no default. Proceeding approves this material as the
  thing the run will be graded against; fixing returns to the repair route SKILL stage 4 owns and
  re-runs its gate before anything is spent. Approving the spend is not approving the material, and
  silence is neither.

An asking cap is what this card exists to discharge, and discharging it means the customer meets its
remedy at the moment they are asked to pay - not that its question is put here a second time.
Bound, never block - the run is still worth making, and the question is what to settle before it
rather than instead of it.

After showing the baseline result, give the connected stage a preview and approval:

- Search: added enhanced controls/combinations, any knob of theirs left out and what the baseline
  showed about it, the configuration ceiling below, approximate calls,
  how Traigent's managed search chooses trials while retaining baseline values, objective
  directions and weights, and the rule for recommending among tradeoffs.
- Held-out check: once this run's recommended configuration is selected on the tuning scores, ten
  more agent calls score that configuration - and only that configuration - against the reserved
  held-out rows, joined by ten judge calls when an LLM judge grades them. Include those calls in
  this same approval rather than asking again afterward, and add their tracked cost to the single
  running total. They are the walkthrough's only paid calls the SDK never sees, so the wrapper
  refuses the whole held-out pass rather than starting one the remaining cannot fund to the last
  row; say that here, because a pass that is refused returns no held-out score at all.
- Bounds and value: runtime, enhanced/spent cost and remaining ceiling; provider/Traigent recipients,
  zero-LLM probe, portal history/direct links, and exclusions. Dataset/configuration insights remain
  conditional on verified run-scoped SDK artifacts. Repeat applicable evaluator containment.

The enhanced run card's trial line is a ceiling paired with the size of the space it is drawn from, because
at approval time the user is asking what the worst case is, and a range answers a question they did
not ask. State it in their words, reusing the card's own total combination count:

> Your agent has `<total combination count>` possible configurations.
> Traigent will test up to `<enhanced trial cap>` of them, choosing which ones as it goes rather
> than working through a fixed list.

Both numbers come from the approved space itself - the count this card already computed and the cap
this run passes as `max_trials` - never from a worked example in a reference, whose spaces are not
this agent's. Name this count in `configurations` rather than `trials`, and give it as a ceiling,
never as a range; `trials` remains the right word for a failed-trial count or an SDK field. When
the approved space's combination count cannot be computed - a preserved space whose values are not
enumerable, for instance - state the ceiling on its own rather than estimating or rounding a total.
Report the same pair afterwards as what actually ran, `Tested <executed trials> of <total
combination count> configurations`, or the executed count alone when that total was unavailable.

Do not manufacture urgency. If baseline and evaluator show a measured quality, cost, or latency
opportunity, say `Recommended next: continue with Traigent optimization because <observed reason>.`
End the preview with `Continue with this bounded Traigent run?` Otherwise recommend the evidenced
repair; never promise improvement.

Final reply-ready line: `Recommended next: <action> — <measured reason>. Reply "continue" and I
will <next safe step>.` For controlled work, `continue` opens a preview; it approves nothing unless
that preview disclosed recipients, effects, bounds, and cost.

Keep the default `$5.00` ceiling across both approvals. If a stage exceeds the remaining ceiling or
is materially long, recommend a smaller slice or fewer trials; expand only if the user prefers.

The approved total is not a number the assistant carries in its head between phases. Launch every
paid process with three figures in its environment, supplied by the process and never by `.env`,
exactly as `TRAIGENT_FIRST_RUN_PHASE` is: `TRAIGENT_FIRST_RUN_COST_CEILING_USD` is the total
approved above; `TRAIGENT_FIRST_RUN_COST_SPENT_USD` is the single running total at the moment that
process starts, which is `0` only while nothing has been spent yet - a live probe or a judge
calibration that already ran is in it; and `TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD` is the
conservative amount one provider call is deducted for when its route reports no cost, rounded up
from the observed per-call cost once the probe has one and from the estimate the approval card was
priced with until then. None of the three has a default, so a paid phase launched
without them stops before its first call instead of running on a per-optimization limit that knows
nothing about this walkthrough. State the three on the approval that sets them, in the same numbers
the card shows. `references/sdk-execution.md` owns what the wrapper does with them.

Do not persist `TRAIGENT_COST_APPROVED=true`; set approval only in the current paid process, which
is what keeps the SDK's own prompt from offering to raise the approved total. The SDK enforces its
optimization-call limit, but it does not yet share one cumulative budget with calibration and other
calls. Until it does, keep a single running total rather than a phase ledger: each paid phase ends
by printing what it spent against the figures it was launched with, and that printed total - not the
SDK's tracked cost, which cannot see a conservative deduction or a refused trial - is added to the
running total and passed to the next process as its `TRAIGENT_FIRST_RUN_COST_SPENT_USD`.
Before the next phase, stop if its estimate does not fit the remaining total ceiling.
Never call the walkthrough ceiling a hard provider-billing cap, tracked cost or not.

A phase that reaches the remaining stops there and is reported as what it is: the trials it
completed, its stop reason, and the work that did not run. The way past it is a fresh approval for
a larger total, taken back to the user with what has been spent so far - never a larger figure
handed to the same process, and never a second attempt at the same phase on top of what the first
one already spent.

The SDK already retries transient Traigent-backend requests and classifies provider failures.
Do not layer another retry loop over it, expose retry counts to the user, or set
`TRAIGENT_VENDOR_MAX_RETRIES` for the first run. Preserve retry behavior already present in the
user's agent/provider client, with one exception the spend ledger requires: retries the provider
client would take underneath the wrapper are turned off, because a call it repeats down there costs
real money the ledger never sees and the running total never moves for. An explicit retry count the
caller set is kept, and `references/sdk-execution.md` owns the mechanism and what it trades away -
a transient failure now surfaces instead of being absorbed. Generated walkthrough provider calls add
no explicit retries. When the preserved client has bounded retries, include their possible extra
calls in the internal runtime/spend estimate without asking the user to configure them.

After the approved live probe, calculate internal request and SDK optimization bounds from
observed latency, rows, trials, calls per example, and concurrency, with a reasonable completion
margin. These are implementation details, not user choices. If observation makes the run
materially longer than the approved estimate, offer a smaller run or quote the additional
time/cost. If the SDK returns a timeout with completed trials, show the best partial result and
offer another bounded pass only when additional search is justified. A timeout with zero trials
requires diagnosis, not more time.

Verify selected model IDs are live and cost-tracked before scaling. If a model chosen by the
assistant is unavailable or unpriced, replace it only with a working model from the same chosen
provider for the same task and data, with unchanged-or-lower call counts and combined worst-case
spend. Record the replacement. Any other change requires revised approval. If the user chose the
model, never replace it silently; present the limitation and one recommended alternative.

For manual live-probe and other provider calls outside SDK-managed searches, prefer cost returned in the provider's public response or
provider-reported response metadata. Do not recalculate a completed OpenRouter response with
`litellm.completion_cost()`: a missing local model-map entry can raise after the provider has
already billed the call. If cost is absent but usage proves a real call, mark it untracked and
deduct the approved estimate; if both are absent, stop. The SDK result remains authoritative for
SDK-managed baseline/search cost.

## Connected-run readiness

The connected run's most damaging failure is not a missing key - it is a present key that silently
stops tracking. A permanent trial rejection (HTTP 400 for a config the backend will not accept) or a
present-but-unscoped key (HTTP 403 when the key lacks the `experiment.write` scope) can drop the run
to local-only tracking: `results.cloud_url` is `None`, no experiment reaches the portal, yet paid
trials keep running and a results table still prints - so a user with a valid key reasonably believes
the run reached the portal when it did not.

Prove the tracking path before connected spending, with a zero-LLM probe:

1. Build a trivial stub agent that returns a constant and makes no provider call, so the probe costs
   `$0` in LLM spend.
2. Run the smallest possible connected optimization through the installed SDK's public path (one or
   two trials) and confirm each rung in order: the portal key is present, it authenticates, it is
   scoped for `experiment.write`, a session is created, the first trial is accepted, and a
   `cloud_url` is returned.
3. If any rung fails, stop before any connected paid trial. Show a sanitized reason and stable
   status/request id when available. Preserve the useful diagnostic category, but remove secrets,
   prompts, examples, outputs, and personal data before showing or saving external error text.

This probe is general readiness, not a workaround for any single validation rule: the installed SDK
owns the local pre-checks (config-in-space, numeric-type, `example_id` uniqueness) and the loud
local-only signal; the skill's job is only to confirm at `$0` that tracking actually attaches before
paying, and to keep confirming it during the run. If tracking degrades to local-only at any later
point in the connected run - a missing `cloud_url`, a `rejected` persistence state, or a mid-run
403/400 - halt further paid work at once and report the degradation in the consolidated result. Never
let a connected run finish spending and only then reveal that nothing reached the portal.

The probe answers whether tracking attaches, at the moment it runs. It cannot answer whether the
managed brain is still reachable when the paid search starts a moment later, and the two failures
are not the same: a run can keep tracking trials to the portal while the search choosing those
trials has quietly become local. `references/sdk-execution.md` owns the setting that closes it -
the connected phase runs with local fallback disabled, so a session that cannot be created raises
instead of degrading - along with the environment settings that defeat it and how a raised run is
reported. Neither replaces the probe: the flag governs the SDK's own fallback, while the probe is
what proves the key is scoped and the session reaches the portal at all.

That setting turns one class of silent degradation into a stop, so decide the stop with the user
before it costs anything. If the inventory finds a no-egress setting in the environment or `.env`,
the connected phase cannot honestly run: ask once, at the point the second run is explained, which
they want - keep no egress and finish on the local baseline, which is a complete and reportable
result, or lift it deliberately for this run. Never clear it for them, and never carry the question
past the approval card into the middle of a paid phase.

## Baseline and optimization

Follow SKILL stage 7 for the comparison order, evidence held constant, checkpoint, and exact-sync
decision. This section owns configuration-selection depth and execution/reporting safeguards.

Keep both spaces tied to the real agent and observed failure modes. Preserve a user-owned baseline
space unchanged, even when it contains one row. The generated walkthrough's two exact sizes and
their derivation live in `references/sdk-execution.md`; use those values rather than restating the
arithmetic here. The baseline trials are one per configuration, and the approval card names that
count - as a count, never as a change from whatever this guide did before, which the customer has
never run.

The three default behaviour knobs are prompt style, thinking shape (direct or chain-of-thought),
and reflect; temperature stays fixed at the task-selected value owned by `sdk-execution.md`, so
every swept knob is real for every model. They are
selected from the eleven-knob catalog `references/sdk-execution.md` owns. The approval card shows
the selected three and why they fit; the customer does not have to design a space from the whole
catalog. `self_check` is not among them - it and `reflect` were one knob
under two names, and `reflect` is the one that stayed. The
models are the fast, mid, and strong rungs of the walkthrough model
ladder from the selected route - the strong rung one step below the vendor's newest flagship, at a
pinned effort in both runs when it is a reasoning model, and never the flagship itself. The
enhanced space keeps the identical model list and every baseline value, so the baseline is a strict
subset of it and an enhanced win is attributable to knobs and the managed search, never to a model
the baseline did not measure. Explain this generated-only
ladder in one line before the
approval: skipping the flagship keeps the first run faster and cheaper, and the flagship stays
available for a separately disclosed later comparison if the evidence supports one. A preserved
baseline keeps its exact model set, including a flagship when present. Do not add cheaper tiers or
any other model unless a separate model comparison is disclosed and approved. For preserved
agents, add task-relevant non-model controls only to the enhanced space by default, such as context
format, retrieval depth, few-shot count, tool policy, or repair behavior; do not force the
generated example's controls onto an unrelated task.

A customer who brings ten wired knobs does not get all ten, and the reason is arithmetic. Ten knobs
at two values each is 1024 configurations against a 12-trial cap - 1% of the space sampled - and
the scorer damps the search-space points past 20x the cap, 240 configurations at that
default. What it credits is how much of the space this run will actually compare -
`min(configurations, trial cap)` - and it pays full credit only from twelve reachable
configurations up, which is what SKILL.md's upper bound on the enhanced space delivers against
the default cap.

Which of theirs to keep is the baseline's call, not preference. For each knob the baseline VARIED,
compare the best score on each of its values: a spread under the evaluator's separation margin did
not move the baseline, and that knob is a candidate to drop. That margin is 0.05 normalized, the
`--separation-margin` default in `scripts/calibrate_evaluator.py` - a distance between two SCORES,
never the same-sized noise floor above, which is a distance between two knob VALUES.

A knob the baseline never varied is not a candidate: silence is not a null result. Read which knobs
it varied off the space that actually ran rather than off a remembered list - a generated
walkthrough's baseline axes follow the selected model rung, so it can rank only what it swept. The
baseline's twelve trials across a knob's two values are six observations a side at most - enough to
prefer one knob over another, never enough to prove one does nothing. Say `did not move the
baseline` or `the baseline's best combination used X`, never `does not matter` or `X is better`,
and give a knob this baseline never ranked no verdict at all.

Fill the freed slots from the failure-mode levers below, once the customer's evidenced knobs are
seated: where the evidence ties, the customer's own knob wins over one of this guide's suggestions
- they know their agent. The connected-stage approval preview above is where that record reaches
them, before they pay for a space that excluded it.

The baseline can decide which customer-owned knobs fill the three slots; it does not narrow their
values between runs. The generated walkthrough is simpler still: all three controls and all their
values are fixed before either run, exactly as `references/sdk-execution.md` shows. A baseline
observation that suggests a different value is a hypothesis for a later run, not an undisclosed
edit to the approved comparison.

**The same small generated-space size whatever the customer brings.** A customer who arrives with
twenty of their own knobs gets the same three-slot enhanced space, not a larger one. The reduction
is not a judgement about their knobs, and their knobs are not replaced by this guide's: the three
slots are filled from what they brought, and baseline evidence decides which three. The resulting
three-control choice reaches the enhanced run's approval card with that evidence - the one moment
the customer can object before paying for the selected space.

Say plainly what that is and is not. The knobs are reduced to demonstrate the principle cheaply -
a first run has to finish, cost little, and be readable, never a wall of knobs added to
manufacture a visible improvement - and Traigent knows tens of knobs it can recommend once the
principle is shown. This is a demonstration, not the ceiling of what Traigent can do, and no
result here should be read as the best the system could reach. Never present the smaller space as
though the improvement were bought by shrinking the search.

Native boolean knobs use `[True, False]`, never string encodings. A generated walkthrough fixes the
one task-selected temperature owned by `sdk-execution.md` across both phases and carries the search
on behaviour knobs instead. Preserve a user-owned baseline's temperature behavior exactly,
including an unset provider default; record resulting nondeterminism as a limitation rather than
silently changing the baseline. Multi-call composite controls multiply cost and require a concrete
failure-mode justification; every knob in the generated default stays within one provider call.
`self_consistency` is the catalog's one deliberate exception, under the precondition and approval
rule `sdk-execution.md` owns.

Match each knob to how the agent actually fails: repair (re-prompt once on a malformed or erroring
output), self-consistency (sample N and vote, for unstable answers), similarity-selected retrieval
(for unseen patterns), and chain-of-thought or plan-then-act (for multi-step reasoning). A knob only
helps if it targets the observed failure mode; wired in blind it adds cost and can even lower the
score.

Managed `auto` is a guided search, not an exhaustive grid: `max_trials` is a cap, not a minimum,
so the service can stop with fewer trials. `auto` already runs Traigent's smart cloud search, so do
not hand-pick a named optimizer such as `bayesian`, `tpe`, or `optuna`; use `auto`, `grid`, or
`random` unless a named selector is confirmed to run consistently on the installed SDK. For an
assistant-prepared baseline, use local `grid` so all twelve distinct rows are predictable. For a
user-owned baseline, preserve its space and selection behavior exactly in the local phase. Use
connected `auto` with a default cap of 12 for the enhanced space, then report the actual count and
stop reason; `references/sdk-execution.md` owns the shortfall obligation beneath that cap, so never
silently present a two-row generated run as the intended comparison.

Composite patterns multiply calls and cost. Use them only when the agent shape and observed
failure mode justify them.

### The accuracy-cost frontier

SKILL stage 7 owns when a frontier is reported and its score floor; `references/sdk-execution.md`
owns the read. Owned here: what it may claim, and the wording of its two outcomes. It costs nothing
and adds no stage - both runs priced every trial they completed, so this is arithmetic over trials
already in hand. Report it whichever way it comes out.

The floor is a number this run reads rather than a judgement it makes: the incumbent's score on
this run's own metric, the incumbent being the configuration the user is already running.

It needs measured cost to exist at all, and two runs fail that for opposite reasons the user is
told apart:

- **Cost was not tracked.** An unpriced trial is not a cheap trial, and a `0.0` standing in for
  pricing the run could not resolve is an absent cost wearing a number - indistinguishable in the
  metrics map from a real one. Report no frontier, and say why.
- **The route genuinely costs nothing.** A provider-reported `0.0` with nonzero token usage is a
  real measurement rather than a missing one, and a route with no cost has no trade-off to plot.
  Say that instead, rather than the reason above.

Each point is one configuration's measured cost beside its score on this run's own metric, over the
same rows, evaluator, and agent call path as everything else it reports. Dominated points are
dropped - a configuration that cost more and scored no higher than another on the same evidence is
not a trade-off anyone would take.

Cost is measured directly but not exactly: one configuration evaluated twice returns two different
token counts, inside a single run as much as across two. Report each point's measured cost and let
the reader see the gap; never present two points a few percent apart as a saving.

A frontier asserts no win, so it needs no threshold to clear and states none. What it does need is
the score claim `references/evaluation-and-dataset.md` decides from the paired counts rather than
from the direction of two averages: default to directional - "no score difference was detected on
these rows" - and say "the score did not get worse" only where a justified paired uncertainty
analysis over the completed outputs supports it. Rows where the cheaper point lost and the
incumbent won are reported even when they are outnumbered, because failing to detect a drop on a
first-run slice is not evidence there was none. A point reaching the frontier is not evidence its
score held: several configurations are statistically indistinguishable at this size, so the one
that matched the incumbent's number may simply have measured lucky. Never let "the optimizer picked
it" stand in for evidence that the score held.

That bound is why a cheaper point is never sold as settled. What a frontier this size supports is a
hypothesis worth testing at full scale - "a cheaper tier scored level with the winner on these
rows" - so it travels to the close as one, under the rule the continuation handoff below already
states. It does not earn another paid round here.

#### The two outcomes

Both are results. Neither is apologized for.

**The frontier holds more than the incumbent.** Report the recommended point against the
configuration the user runs now, then the rest of the frontier as the trade-offs it measured:

> `<config>` scored `<value>` at `<measured cost>`, against `<value>` at `<measured cost>` for the
> configuration you are running now, on the same rows, evaluator, and agent call path -
> `<paired outcome counts>`. Cost here is arithmetic over reported token counts, so it is measured
> directly. The score is not measured directly - it is a comparison over `<n>` rows - so `<the score
> statement the counts support>`. The whole frontier this run measured is `<points, cheapest
> first>`, and two points a few percent apart in cost are inside what re-measuring one
> configuration moves.

**The incumbent is the only point on it.** This is a finding, and it gets its own copy. Report what
this run counted, never a property of the space: the space is larger than the run's trial cap, so
any claim about the space quantifies over configurations the run never reached.

> This run tested `<executed trials>` of `<total combination count>` configurations. On accuracy
> against cost, the configuration you are already running is still the only point on the frontier:
> nothing tested cost less at its score, and nothing scored higher at its cost. So keeping it is
> the answer this run supports. A run this size reaches few configurations by design; widening the
> search across your full dataset and your own controls is what the skills named at the close are
> for.

That is a measured answer to the question this run asked, and a service rather than a shrug: the
user wanted to know whether a better trade-off was sitting there, and now they do instead of
chasing one. It is bounded as honestly as the other outcome - it establishes nothing about
configurations the run did not test, and a bounded run tests few. That bound is the forward half,
and it points at an action and never at a result: the handoff below names what a wider search would
let the user *do*, never what it would find. Do not answer it with another paid run by default.

## Post-run verification

Before claiming success, verify:

1. Trials exist and failed-trial count is understood.
2. Baseline was actually evaluated.
3. Best configuration exists.
4. Declared objective measures appear and vary meaningfully.
5. Real calls do not show the mock's constant response pattern.
6. Provider calls have nonzero token usage. Report `total_cost` as positive, provider-reported zero
   for a genuine free route, or untracked; cost alone does not prove whether a run was real.
7. No output was truncated. `require_untruncated_completion` raises on `finish_reason ==
   "length"`, so a truncated trial arrives as a failed trial rather than as a scored 0; confirm
   none reached the comparison, and report `REFUSED_TRIAL_COSTS` beside the total - a refused
   trial was still billed, and spend that bought no measurement is still spend.
8. Portal persistence status is complete or precisely described as degraded/failed.
9. `cloud_url` exists before saying the result is on the portal.
10. The pre-connected-run portal-tracking probe passed and tracking did not silently drop to
    local-only during
    the run; any such degradation halted further paid work rather than surfacing only at the end.
11. Baseline and enhanced tuning results are shown side by side, with the tuning-data limitation
    named before any generalization claim, and the held-out score SKILL stage 8 discloses appears
    beside them.
12. Every execution-evaluator invocation used the declared sandbox and resource limits; timeouts,
    limit breaches, forbidden side effects, and sandbox failures were counted and reported rather
    than retried outside containment.
13. Every reported frontier carries measured costs, a score claim the paired counts support, and no
    point below the floor. Trials that came back without reported cost carry no cost claim: report
    that, not a number.
14. Each paid process ran against the approved figures it was launched with, and the close reports
    them: the approved total, what this run spent against it, and what is left. A phase that
    refused to start, or stopped at the remaining, is named with the work it did not do.

An optimized winner that does not beat the baseline is a valid no-lift result. Report the observed
delta first, then separate verified facts, evidence-backed inferences, and untested hypotheses.
Candidate hypotheses include an uninformative space, limited or easy data, evaluator mismatch,
controls the search never varied, output truncation, generated data with no headroom, or insufficient
model capability. Use the checks below to choose the next test, but say `cause not established by
this run` unless evidence rules one in. A flat demonstration result says only that this comparison
found no lift on its evidence; it does not predict production.

Investigate in order: verify semantic equivalence and references, inspect truncation and whether
every declared control varied, add one structural knob tied to a failure mode, then consider a
separately disclosed stronger-model comparison. Distinguish a genuinely hard item from a
demonstrably ambiguous, wrong, or degenerate reference. Attribute the latter to the reference, not
model capability, and never change a validated metric merely to manufacture a win.

Frame no-lift for a first run too, in the recorded numbers the run-scope statement below supplies
rather than as a general remark: a bounded getting-familiar pass deliberately searches a few
relevant knobs on a small budget, so a flat result can simply be a normal first look rather than a
fault. The honest next step is one deliberate iteration adding a single structural knob where the
evidence points, not piling on knobs or spend to force a win.

Read a flat result at a HIGH score the other way round, and only on collected data. The paragraphs
above answer a flat result by looking harder - another structural knob, or a separately disclosed
stronger model - which is right when the level is low. When the paired analysis detects no
difference between configurations and the level sits near the top of the run's own metric, "nothing
we tried separated them" is a finding about the task rather than a failure of the search: these
configurations are not what limits this result. Then the cheapest point the run measured is not
merely on the frontier, it is the answer, and the experiment worth running next is a tier BELOW
anything tested rather than above it.

Two bounds it keeps, both already owned above. It is a statement about what this run tested and
never about the space - a cheaper tier nobody ran is a hypothesis to test at full scale, exactly as
a cheaper tier that did run and matched is - and it does not earn another paid round here. And it
requires collected data: on generated rows a high flat score measures material this run invented,
where an easy-looking task is the likeliest thing a walkthrough dataset produces.

If any component is synthetic, put the limitation before the score. A synthetic Pareto frontier
can look identical to a production one.

### Run-scope statement

The close states the run's own bounds so its numbers are read at the scale they were measured at.
Every clause is a number this run already recorded; a clause whose number the run does not have is
dropped, never estimated to complete the sentence.

- **Rows** - the scored row count beside the dataset's usable row count, both already recorded when
  the bounded subset was drawn. When no subset was drawn the two are the same number: say the run
  scored every usable row and let the other clauses carry the bound.
- **Configurations** - trials executed beside the total combination count the enhanced run card
  already showed. When the run stopped at the baseline checkpoint and no enhanced search ran, drop
  this clause and say it stopped there instead.
- **Knobs** - the controls the enhanced space varied, beside the candidate controls this run
  identified on the agent. When it never enumerated a wider candidate set there is no denominator
  to quote: say instead that the space varied only the controls whose wiring this run verified, and
  name that as the bound.

Then one sentence saying those bounds were the walkthrough's own choice, so this was a
getting-familiar run rather than the largest one available.

Keep it a scope statement. It reports what was measured and what was not; it does not predict that
a larger run would have won, attach a deadline, or supply a reason to act now. The motivation stays
the user's own measured evidence.

### Continuation handoff

Offer the skills package to every finished run. Which skills the close names comes from what this
run recorded, so the handoff continues this run rather than restarting it. Name two or three, each
with the observation that selected it and what it would let the user do next:

| What this run recorded | Skill to name | What it would let them do |
|---|---|---|
| One control accounted for most of the observed spread, or the search barely moved the others | `traigent-analyze-variable-importance` | rank which tuned variables mattered, at a sample size that can support the ranking |
| Controls left out of the space, or a space barely larger than its trial cap | `traigent-optimize-config-space` | build the wider search space this run bounded away |
| The row subset, a single difficulty band, or an unlabelled slice was the binding limit | `traigent-dataset-curate` | grow, label, and split the dataset the comparison was bounded by |
| The evaluator was never calibrated, or a thin or judge-based method carried the ranking | `traigent-eval-audit` | audit whether the ruler this comparison trusted is reliable |
| The user wants to re-read this run's own result rather than pay for another | `traigent-analyze-results` | read the winner, trials, and trade-offs from the terminal |
| The earned next move is a larger search | `traigent-optimize-run` | choose algorithm, trial count, and cost limit for a full-scale run |

Every row is a hypothesis this run is too small to settle. At this run's row and trial counts a
control that showed no effect was mostly not sampled enough to show one, so each entry is phrased
as what is worth testing at full scale and never as an established finding. Name no skill that is
not in that repository, and no `npx skills add` flag beyond `--list` and `--skill`.

## Recovery

- Portal persistence `degraded`: trials may be present while summaries lag. Explain and verify the
  link before discarding anything.
- Portal persistence `failed`: recover/sync the existing run when supported; do not repay for a
  rerun by default.
- Permanent HTTP validation error or missing `cloud_url`: surface a sanitized precise backend
  reason; do not replace it with a guessed explanation or claim portal success.
- Tracking degraded to local-only during a connected run: apply the Connected-run readiness halt -
  stop paid work at once, surface a sanitized backend reason, and report the degradation.
- Cost limit reached with zero trials: no result exists. Reduce scope or obtain new approval.
- Cost limit reached with completed trials: show the best partial result and name the cost cap as
  the stop reason; do not report it as a failure or silently drop the paid trials.
- SDK or optimizer exception mid-run, including a Rust/pyo3 panic during result serialization (a
  known class): surface the error in plain language with one recommended recovery, never a raw
  traceback. Completed trials were already paid and written to the selected
  `TRAIGENT_RESULTS_FOLDER` - beneath `traigent-runs/` for the generated wrapper, or at the named
  preserved project path. Recover them and, for a connected run, upload the partial session with
  `traigent sync <session_id>` before reporting - never present already-paid work as a total loss.
  A foreground command timeout (harnesses often kill at about five minutes) can kill
  `optimize_sync` mid-run without rolling back its spend, so run a long paid optimization detached
  and poll its log rather than letting the tool timeout abandon paid trials.
- Rate limit or temporary provider outage: preserve partial results and use the SDK/provider
  classification.
- Invalid credentials, quota exhaustion, or insufficient funds: stop with the specific category;
  do not retry or describe every case as "no tokens." An unfunded OpenRouter key returns HTTP 402 and
  silently fails trials - verify funding before paid work; a free-tier optimization-sample quota
  rejection means shrink the run, not retry blindly. For an uncategorized provider error, surface a
  sanitized provider message rather than guessing a category.
- Timeout with completed trials: show the best partial result before offering one additional
  bounded pass with its extra approximate time and cost.
- Timeout with zero trials: diagnose provider latency, a hung call, or setup failure before
  considering another run.
- Evaluator exceptions or all-zero/all-one measures: repair evaluator/data and rerun only after
  calibration.
- Dataset examples that fail under every configuration: inspect gold/reference and evaluator
  policy before blaming the model.

For generated wrappers, set the process-only SDK results folder to a child of `traigent-runs/`
before importing Traigent so its local optimization logs and state remain inside the ignored
walkthrough directory. Store no secrets, raw private content in run names, or prompts/outputs in
numeric telemetry, and keep error text and metadata recorded with the run content-free.

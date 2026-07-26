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

- Reuse an existing compatible isolated environment. When none exists, use the conventional
  `.venv` with Python 3.11-3.13; do not replace the project's interpreter without approval.
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
- After every applicable free component, capability, and safe mock check, build one minimal `.env`
  with blank selected-provider and Traigent key entries. If it exists, preserve existing values,
  comments and unrelated keys and append only missing blank entries. Before opening it, require
  mode `0600` on POSIX. Stop once for both local secret pastes.
- Never paste or print secrets. Check only presence and safe key-shape prefixes.
- Hand the file off unambiguously: open `.env` for the user (`xdg-open`/`open`/`notepad`) and, on a
  headless box, print its absolute path; name the target line by key prefix - the `sk-`/`sk-or-`
  provider key after its `..._API_KEY=` line, the `uk_` portal key after `TRAIGENT_API_KEY=` - so two
  blank `KEY=` lines cannot be swapped.
- Prompts, examples, and outputs are not sent to Traigent by the optimization service.
- A selected direct LLM provider still receives whatever content the agent normally sends in
  model calls.
- With OpenRouter, OpenRouter receives the request as the gateway and the selected upstream
  inference provider may also receive prompts, examples, and outputs. Automatic routing and
  fallbacks can change that upstream recipient.
- Connected Traigent runs transmit configuration identifiers, numeric measures, run state, and
  content-free metadata needed for optimization and portal history.
- Encode prompt variants as short labels mapped to the text inside the agent function; never put raw
  prompt text as configuration-space values. Configuration choices are synced to Traigent's
  optimizer, so labels keep the actual prompts on the machine.

Ask before any private content leaves the machine, even when the provider key already exists.

At the secret-entry gate, show only the URL needed for the selected service:

- Traigent registration: `https://portal.traigent.ai/register`
- Traigent API keys: `https://portal.traigent.ai/management/api-keys`
- OpenRouter keys: `https://openrouter.ai/keys`
- OpenAI keys: `https://platform.openai.com/api-keys`
- Anthropic keys: `https://console.anthropic.com/settings/keys`

These account/key links are necessary actions, not educational detours. Do not show every provider
link; show only the selected provider and Traigent when each key becomes necessary.

The Traigent key must be able to write experiments, not only read them. A connected run records the
baseline and the optimization, so a read-only key is rejected at submit time and the run silently
drops to local-only tracking - real money is spent and nothing appears in the portal. A manually
created key defaults to read-only, so grant it full access rather than accepting the default. Say
this at the moment the user creates the key, not afterwards: the failure is cheap to prevent and
expensive to discover, because by the time it shows up the spend has already happened.

Nothing else belongs in `.env`. Do not add a backend or API URL - the installed SDK already points
at the production service, and a stray override silently sends a paid run somewhere the user cannot
see it.

Use this gate order:

1. After component creation, define the calibration matrix and thresholds, then have the coding
   assistant perform and record the evidence-backed semantic-coverage review. Record the reviewer
   and evidence, materially distinct inputs, outcomes, and rubric/schema branches, mode and
   threshold rationale, known gaps, and a `sufficient` or `ambiguous` verdict.
2. If unresolved product-grading ambiguity would materially change correctness or candidate
   ranking, ask exactly one product-grading question and stop for the answer. Otherwise record
   that no material ambiguity remains and continue without a generic semantic-review stop.
3. Run the bundled static preflight with `--defer-missing-sdk` and the combined dataset argument.
   Record local structure, per-split size/resolution, and quality findings independently of
   SDK/package findings. This pass does not claim exact SDK compatibility, and a missing Traigent
   SDK cannot block it.
4. Run deterministic evaluator calibration only when the semantic-coverage verdict is
   `sufficient` and the complete inspected import and call path is local-only, side-effect-free,
   and needs no unavailable third-party package. Do not execute an LLM judge or any uncertain or
   external evaluator; keep it behind explicit combined approval.
5. Determine the current provider route from the agent's actual model call and configuration;
   inventory provider credential names separately. Credential presence does not select a route.
   When no route exists, default to OpenRouter without a separate choice question; the user may
   request a direct provider instead. If the current route lacks its credential but another
   provider credential exists, stop with the mismatch instead of changing the route silently. If
   OpenRouter is selected, identify every allowed upstream inference provider/route, disclose
   fallback behavior, and pin allowed routes and disable fallbacks when an exact recipient set is
   required.
6. Reuse an existing compatible isolated environment, or create the conventional `.venv` with Python
   3.11-3.13 without fetching packages. Only if an incompatible `.venv` already exists, preserve it
   and use `.venv-traigent` as the non-destructive fallback without making its name a user choice.
7. Install the exact declared dependencies under the narrow package-artifact authorization: use
   compatible exact project declarations or the skill's `assets/requirements-first-run.txt`.
8. Use the installed SDK's public dataset validator/loader, decorator, and evaluation models, plus
   a public no-execution contract validator when the installed version provides one. Let those
   public paths own normalization, injection, agent-call, and evaluator-callback behavior. Never
   mirror SDK aliases or binding fallbacks in the first-run skill. Pass resolved absolute paths to
   SDK 0.25.0's public dataset validator as a temporary workaround for its tracked nested-relative
   path defect. If the installed version lacks
   a full no-execution contract validator, record that limitation and use the safe mock plumbing
   check for end-to-end compatibility. Run any local deterministic calibration deferred solely for
   an installed dependency.
9. Run a fresh-process Traigent mock plumbing check only when inspection proves every model call
   is intercepted and no external side effect can occur. Otherwise record the check as deferred;
   do not over-prescribe execution.
10. After every applicable free check is complete, create the minimal `.env` or minimally update
    the existing one securely as described above, then stop once for both local secret pastes.
11. Present one combined approval covering the smallest live provider/key check, any LLM-judge
    calibration, baseline, bounded optimization, and baseline-versus-winner holdout calls.
12. After approval, run the live check first, starting with the zero-LLM portal-tracking probe (see
    Connected-run readiness below), then the smallest live provider/key check. Continue only if both
    pass.

Do not split paid work into repeated approvals unless the plan materially changes.

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

Deterministic calibration is a separate execution gate. Run it before environment setup only when
the assistant has recorded a `sufficient` evidence-backed semantic-coverage verdict and inspection
proves its complete call path is local-only, side-effect-free, and standard-library-only. A
generic outside-review wait is not a gate. Pause only for the one product-grading question when an
unresolved ambiguity would materially change correctness or ranking. If calibration needs a
declared local dependency, defer it until that dependency is installed, but still run it before
creating `.env` or requesting a provider key. Do not execute an LLM judge or an uncertain or
external evaluator without the explicit combined approval for its recipients, data, calls,
runtime, and spend.

A Traigent mock run is a separate plumbing check:

- Use a fresh process.
- Set offline/mock variables before importing Traigent.
- Confirm every agent and evaluator model path is interceptable. LiteLLM/LangChain paths may be
  intercepted; raw provider SDKs, subprocesses, HTTP services, tools, and custom judges may still
  make real calls.
- Treat proxy variables, removed keys, and mock flags as defense in depth, not as a sandbox or
  proof that an invoked path is local-only.
- If any path cannot be proven free, do not call it a free dry-run. Ask approval for the smallest
  real probe or use static validation only.
- Exit the process after mock validation. Mock state has no reliable public undo.

Uniform mock scores can be expected for output-based evaluators. Plumbing success means trials
execute without failures; it does not mean mock accuracy is meaningful.

Mock results may contain a positive estimated `total_cost`. That is pricing metadata, not evidence
that a provider billed the account. Real billing evidence requires a real provider call plus the
provider/SDK usage record.

The converse also holds: OpenRouter `:free`-suffixed model ids genuinely cost `$0`, so judge a real
run by trials executing and nonzero token usage, not by a zero cost - do not misflag a legitimate
free-tier run as mocked.

## Approval and budgets

Do not ask the user to design a budget, retry policy, or timeout policy during setup. Before any
paid/provider work, show one concise approval for the full planned first run:

- The smallest live provider/key check, any required LLM-judge calibration, the preserved baseline
  or generated six-row sweep, one broader optimization, and baseline winner versus enhanced
  winner holdout.
- Dataset rows, maximum trials, and approximate total agent/evaluator calls.
- Approximate runtime and estimated spend.
- One total walkthrough ceiling, defaulting to `$5.00`.
- Any untracked-cost path; for such a path, call the ceiling a conservative execution stop target,
  not a provider-billing guarantee.
- Services receiving data. For OpenRouter this means the OpenRouter gateway plus every allowed
  upstream inference provider/route, with fallback routing disclosed.

Keep the default `$5.00` ceiling without asking the user to choose a number. If the plan exceeds
it or is materially long, recommend a smaller representative tuning slice or fewer trials first.
Ask about a larger/longer run only if the user prefers the expanded scope.

Use the installed SDK's default per-optimization cost limit unless it is greater than the
walkthrough's remaining total ceiling; then lower it for that process. Do not persist
`TRAIGENT_COST_APPROVED=true`; set approval only in the current paid process. The SDK enforces its
optimization-call limit, but it does not yet share one cumulative budget with judge and holdout
calls. Until it does, keep a single running total rather than a phase ledger: add reliable tracked
cost after each paid phase, or deduct that phase's conservative estimate when cost is untracked.
Before the next phase, stop if its estimate does not fit the remaining total ceiling.
Never describe this as a hard provider-billing cap.

The SDK already retries transient Traigent-backend requests and classifies provider failures.
Do not layer another retry loop over it, expose retry counts to the user, or set
`TRAIGENT_VENDOR_MAX_RETRIES` for the first run. Preserve retry behavior already present in the
user's agent/provider client. Generated walkthrough provider calls add no explicit retries. When
the preserved client has bounded retries, include their possible extra calls in the internal
runtime/spend estimate without asking the user to configure them.

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

For manual live-probe and holdout calls, prefer cost returned in the provider's public response or
provider-reported response metadata. Do not recalculate a completed OpenRouter response with
`litellm.completion_cost()`: a missing local model-map entry can raise after the provider has
already billed the call. If the response has no usable provider-reported cost, stop before scaling
the paid run and use only the conservative approved deduction; the SDK result remains authoritative
for SDK-managed baseline/search cost.

## Connected-run readiness

The connected run's most damaging failure is not a missing key - it is a present key that silently
stops tracking. A permanent trial rejection (HTTP 400 for a config the backend will not accept) or a
present-but-unscoped key (HTTP 403 when the key lacks the `experiment.write` scope) can drop the run
to local-only tracking: `results.cloud_url` is `None`, no experiment reaches the portal, yet paid
trials keep running and a results table still prints - so a user with a valid key reasonably believes
the run reached the portal when it did not.

Prove the tracking path before spending, with a zero-LLM probe:

1. Build a trivial stub agent that returns a constant and makes no provider call, so the probe costs
   `$0` in LLM spend.
2. Run the smallest possible connected optimization through the installed SDK's public path (one or
   two trials) and confirm each rung in order: the portal key is present, it authenticates, it is
   scoped for `experiment.write`, a session is created, the first trial is accepted, and a
   `cloud_url` is returned.
3. If any rung fails, surface the backend's reason verbatim and stop before any paid trial. On the
   pinned SDK the client already prints the backend's precise `details.reason` inline - for example a
   config value "outside the declared categorical domain" - and no longer substitutes a hardcoded
   metric-name guess; report that reason as-is rather than paraphrasing or guessing at it.

This probe is general readiness, not a workaround for any single validation rule: the installed SDK
owns the local pre-checks (config-in-space, numeric-type, `example_id` uniqueness) and the loud
local-only signal; the skill's job is only to confirm at `$0` that tracking actually attaches before
paying, and to keep confirming it during the run. If tracking degrades to local-only at any later
point in the connected run - a missing `cloud_url`, a `rejected` persistence state, or a mid-run
403/400 - halt further paid work at once and report the degradation in the consolidated result. Never
let a connected run finish spending and only then reveal that nothing reached the portal.

## Baseline and optimization

Use one honest comparison:

1. Baseline: the user's existing baseline or fixed configuration exactly as defined. Only when
   Traigent creates the missing configuration, use a credible six-row manual-style sweep that
   includes the generated initial configuration.
2. Optimization: one broader search containing all baseline values plus meaningful added knobs,
   targeting 10-13 visible trials with an internal default cap of 12.

Use the same tuning slice, evaluator, objective definitions, and call path for both. Run both
connected once if portal comparison matters. Do not:

- Run a local baseline and then pay to repeat it only for portal appearance.
- Intentionally weaken the baseline or replace user-defined values with strawman choices.
- Add a variable that does not affect the agent merely to manufacture portal rows.
- Require a third optimization pass before showing the result.
- Compare different datasets or evaluators.

Keep both spaces tied to the real agent and observed failure modes. Preserve a user-owned baseline
space unchanged, even when it contains one row. For a generated walkthrough, the default small
space is two credible models by three safe temperature values, with prompt policy and self-check
fixed to ordinary/off values. The enhanced space retains those values and adds multiple prompt
policies plus a native boolean self-check branch, producing dozens of possible configurations
while Traigent tests 12 by default. For preserved agents, add task-relevant controls only to the
enhanced space, such as context format, retrieval depth, few-shot count, tool policy, or repair
behavior; do not force the generated example's controls onto an unrelated task.

This is a getting-familiar first run: keep it to a few of the most relevant knobs - the three or four
levers that target the agent's real failure modes - not an exhaustive knob set. The space still spans
more configurations than the trial cap, but from a handful of meaningful levers, never a wall of
knobs added just to manufacture a visible improvement.

A knob that does not influence the agent code is not a real optimization variable. Native boolean
knobs use `[True, False]`, never string encodings. Pin temperature to 0 for frail exact/case-
sensitive metrics unless the evaluator explicitly tolerates surface variation; use other safe
controls to keep the baseline meaningful in that case. A provider's default temperature is about 1.0
(random), not 0, so a preserved agent that never sets temperature is non-deterministic; set
`temperature=0` explicitly rather than assuming an unset value is deterministic when diagnosing score
wobble. Multi-call composite controls multiply
cost and require a concrete failure-mode justification; the generated default's self-check stays
within one provider call.

Match each knob to how the agent actually fails: repair (re-prompt once on a malformed or erroring
output), self-consistency (sample N and vote, for unstable answers), similarity-selected retrieval
(for unseen patterns), and chain-of-thought or plan-then-act (for multi-step reasoning). A knob only
helps if it targets the observed failure mode; wired in blind it adds cost and can even lower the
score.

Managed `auto` is a guided search, not an exhaustive grid: `max_trials` is a cap, not a minimum,
so the service can stop with fewer trials. `auto` already runs Traigent's smart cloud search, so do
not hand-pick a named optimizer such as `bayesian`, `tpe`, or `optuna`; use `auto`, `grid`, or
`random` unless a named selector is confirmed to run consistently on the installed SDK. For a generated baseline, use connected `grid` so all
six distinct rows are predictable. For a user-owned baseline, preserve its space and behavior
exactly while using a connected execution path compatible with the portal comparison. Use
connected `auto` with a default cap of 12 for the enhanced space, then report the actual trial
count and stop reason. Fewer than 10
enhanced rows requires a concrete stop, cost, timeout, or failure explanation; never silently
present a two-row generated run as the intended comparison.

Reasoning models need sufficient output-token headroom - give them `max_tokens` of at least 2048
(at least 4096 with high reasoning effort), because hidden reasoning tokens are spent before the
answer text, so a tight cap truncates the answer to `finish_reason == "length"`, scores it 0, and
silently crowns a weaker model the winner. Scan every trial for `finish_reason == "length"`, and do
not sweep low `max_tokens` values in any space that contains a reasoning model.
Composite patterns multiply calls and cost. Use them only when the agent shape and observed
failure mode justify them.

## Post-run verification

Before claiming success, verify:

1. Trials exist and failed-trial count is understood.
2. Baseline was actually evaluated.
3. Best configuration exists.
4. Declared objective measures appear and vary meaningfully.
5. Real calls do not show the mock's constant response pattern.
6. `total_cost` is positive, or explicitly state that cost was not tracked. Zero/`None` is not
   proof of a free run.
7. No output was truncated.
8. Portal persistence status is complete or precisely described as degraded/failed.
9. `cloud_url` exists before saying the result is on the portal.
10. The pre-paid portal-tracking probe passed and tracking did not silently drop to local-only during
    the run; any such degradation halted further paid work rather than surfacing only at the end.
11. Tuning and holdout results are separated.

An optimized winner that does not beat the baseline is a valid no-boost result. Report it
honestly and name the likely cause instead of a bare flat delta: an uninformative or too-small
search space, a dataset ceiling or too-easy data, an over-strict or mismatched evaluator, controls
the search never varied (the winning knob - repair, self-consistency, or similarity-selected
retrieval - was absent from the space), reasoning-model output truncation
(`finish_reason == "length"`), generated walkthrough data with no real headroom where every
configuration scores the same in both runs, or a base model that is not capable enough for a
genuinely hard task - where a stronger (SOTA) model or a higher reasoning-effort level, not more
config search, is the lever (keep the user's capable model in the enhanced space; if none was tried,
name "did not try a stronger model" as the candidate reason). Rule these out in order before calling
it a ceiling: re-run the semantic-equivalence probe, then widen to the structural knobs above, then
raise the model tier or reasoning effort. Only once all are ruled out is a low number the honest
difficulty ceiling of a genuinely hard task - many top out well below 100% even for the best systems
- and it is reported plainly, not as a broken agent. Sharply separate a genuinely-hard item (a
correct reference the model cannot yet match - a stronger model or higher reasoning effort is the
lever) from a misleading one (an ambiguous, wrong, or degenerate reference that no correct answer
matches, or that only rewards a less-correct answer for reproducing the reference's own mistake).
Attribute a misleading item to the misleading question itself, not to model capability or
reasoning-effort level - a stronger model will not, and should not, reproduce a misleading reference
- and never "fix" a validated metric to reward it. Do not invent improvement. A flat result on demonstration data shows the workflow
ran honestly, not that the production workload cannot improve; on real data the same run would
likely look different. Show that cause to the user beside the number, never a bare delta the user
must interpret alone.

Frame no-lift for a first run too: a bounded getting-familiar pass deliberately searches a few
relevant knobs on a small budget, so a flat result can simply be a normal first look rather than a
fault. The honest next step is one deliberate iteration adding a single structural knob where the
evidence points, not piling on knobs or spend to force a win.

If any component is synthetic, put the limitation before the score. A synthetic Pareto frontier
can look identical to a production one.

## Recovery

- Portal persistence `degraded`: trials may be present while summaries lag. Explain and verify the
  link before discarding anything.
- Portal persistence `failed`: recover/sync the existing run when supported; do not repay for a
  rerun by default.
- Permanent HTTP validation error or missing `cloud_url`: surface the precise backend reason; do
  not replace it with a guessed explanation or claim portal success.
- Tracking degraded to local-only during a connected run - missing `cloud_url`, a `rejected`
  persistence state, HTTP 403 without the `experiment.write` scope, or a permanent HTTP 400: halt
  further paid work at once, surface the backend reason verbatim, and report the degradation. Do not
  keep spending on trials that no longer reach the portal.
- Cost limit reached with zero trials: no result exists. Reduce scope or obtain new approval.
- Cost limit reached with completed trials: show the best partial result and name the cost cap as
  the stop reason; do not report it as a failure or silently drop the paid trials.
- SDK or optimizer exception mid-run, including a Rust/pyo3 panic during result serialization (a
  known class): surface the error in plain language with one recommended recovery, never a raw
  traceback. Completed trials were already paid and written to `TRAIGENT_RESULTS_FOLDER` under
  `traigent-runs/`; recover them and, for a connected run, upload the partial session with
  `traigent sync <session_id>` before reporting - never present already-paid work as a total loss. A
  foreground command timeout (harnesses often kill at about five minutes) can kill `optimize_sync`
  mid-run without rolling back its spend, so run a long paid optimization detached and poll its log
  rather than letting the tool timeout abandon paid trials.
- Rate limit or temporary provider outage: preserve partial results and use the SDK/provider
  classification; do not add a duplicate retry loop.
- Invalid credentials, quota exhaustion, or insufficient funds: stop with the specific category;
  do not retry or describe every case as "no tokens." An unfunded OpenRouter key returns HTTP 402 and
  silently fails trials - verify funding before paid work; a free-tier optimization-sample quota
  rejection means shrink the run, not retry blindly. For an uncategorized provider error, surface the
  provider's message verbatim rather than guessing a category.
- Timeout with completed trials: show the best partial result before offering one additional
  bounded pass with its extra approximate time and cost.
- Timeout with zero trials: diagnose provider latency, a hung call, or setup failure before
  considering another run.
- Evaluator exceptions or all-zero/all-one measures: repair evaluator/data and rerun only after
  calibration.
- Dataset examples that fail under every configuration: inspect gold/reference and evaluator
  policy before blaming the model.

Keep assistant-created walkthrough artifacts under `traigent-runs/`. For generated wrappers, set
the process-only SDK results folder to a child of `traigent-runs/` before importing Traigent so its
local optimization logs and state remain inside the ignored walkthrough directory. If a preserved
project already configures another SDK results folder, honor and record it instead. Store no
secrets, raw private content in run names, or prompts/outputs in numeric telemetry.

Privacy wording describes Traigent's documented payload contract, not an independent packet audit.
Keep metrics, metadata, experiment names, and errors content-free. Verify the installed SDK's
privacy/offline controls when available; if payload behavior cannot be inspected, say that the
contract was followed rather than claiming network traffic was independently audited.

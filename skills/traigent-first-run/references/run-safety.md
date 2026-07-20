# Run Safety and Result Honesty

Use this reference for setup, dry-run, paid execution, portal verification, recovery, and claims.

## Contents

1. Environment and privacy
2. Static and mock validation
3. Approval and budgets
4. Baseline and optimization
5. Post-run verification
6. Recovery

## Environment and privacy

- Use an isolated Python 3.11-3.13 environment; do not replace the project's interpreter without
  approval.
- Create a separate environment when the project uses an incompatible interpreter:
  `python3.13 -m venv .venv`.
- Keep dependency installation as its own action class. It may proceed without another approval
  only inside that environment, from the exact packages and versions recorded for the
  run, as a package-artifact-only fetch/install with no provider or Traigent calls, private-data
  transfer, or user/project code execution. Prefer a fully pinned, hash-checked requirements file
  and wheels; stop if fulfilling it requires source builds, undeclared packages, or code
  execution. A user or environment install-approval policy still takes precedence.
- Before creating the environment or installing anything, run every available bundled component
  check whose complete path needs only the Python standard library and local project files.
- Verify installed packages and public signatures before generating SDK integration code.
  Dependency installation does not authorize importing or executing user/project modules.
- Verify SDK capabilities from the installed version and CLI rather than hardcoding what installs
  "today."
- Build a minimal `.env` for the selected provider only after every applicable free component,
  capability, and safe mock check. Leave the Traigent key blank until connected execution.
- Never paste or print secrets. Check only presence and safe key-shape prefixes.
- Prompts, examples, and outputs are not sent to Traigent by the optimization service.
- A selected direct LLM provider still receives whatever content the agent normally sends in
  model calls.
- With OpenRouter, OpenRouter receives the request as the gateway and the selected upstream
  inference provider may also receive prompts, examples, and outputs. Automatic routing and
  fallbacks can change that upstream recipient.
- Connected Traigent runs transmit configuration identifiers, numeric measures, run state, and
  content-free metadata needed for optimization and portal history.

Ask before any private content leaves the machine, even when the provider key already exists.

At the secret-entry gate, show only the URL needed for the selected service:

- Traigent registration: `https://portal.traigent.ai/register`
- Traigent API keys: `https://portal.traigent.ai/management/api-keys`
- OpenRouter keys: `https://openrouter.ai/keys`
- OpenAI keys: `https://platform.openai.com/api-keys`
- Anthropic keys: `https://console.anthropic.com/settings/keys`

These account/key links are necessary actions, not educational detours. Do not show every provider
link; show only the selected provider and Traigent when each key becomes necessary.

Use this gate order:

1. After component creation, define the calibration matrix and thresholds, then have the coding
   assistant perform and record the evidence-backed semantic-coverage review. Record the reviewer
   and evidence, materially distinct inputs, outcomes, and rubric/schema branches, mode and
   threshold rationale, known gaps, and a `sufficient` or `ambiguous` verdict.
2. If unresolved product-grading ambiguity would materially change correctness or candidate
   ranking, ask exactly one product-grading question and stop for the answer. Otherwise record
   that no material ambiguity remains and continue without a generic semantic-review stop.
3. Run the bundled static preflight with the dataset argument. Record local structure and quality
   findings independently of SDK/package findings. This pass does not claim exact SDK
   compatibility, and a missing Traigent SDK cannot block it.
4. Run deterministic evaluator calibration only when the semantic-coverage verdict is
   `sufficient` and the complete inspected import and call path is local-only, side-effect-free,
   and needs no unavailable third-party package. Do not execute an LLM judge or any uncertain or
   external evaluator; keep it behind explicit combined approval.
5. Reuse the project's configured provider. When none exists, default to OpenRouter without a
   separate choice question; the user may request a direct provider instead. If OpenRouter is
   selected, identify every allowed upstream inference provider/route, disclose fallback
   behavior, and pin allowed routes and disable fallbacks when an exact recipient set is required.
6. Create the isolated environment with Python 3.11-3.13 without fetching packages.
7. Install the exact declared dependencies under the narrow package-artifact authorization.
8. Use the installed SDK's public dataset validator/loader, decorator, and evaluation models, plus
   a public no-execution contract validator when the installed version provides one. Let those
   public paths own normalization, injection, agent-call, and evaluator-callback behavior. Never
   mirror SDK aliases or binding fallbacks in the first-run skill. If the installed version lacks
   a full no-execution contract validator, record that limitation and use the safe mock plumbing
   check for end-to-end compatibility. Run any local deterministic calibration deferred solely for
   an installed dependency.
9. Run a fresh-process Traigent mock plumbing check only when inspection proves every model call
   is intercepted and no external side effect can occur. Otherwise record the check as deferred;
   do not over-prescribe execution.
10. After every applicable free check is complete, create the minimal `.env` with blank selected
    provider and Traigent key entries, then stop once for both local secret pastes.
11. Present one combined approval covering the smallest live provider/key check, any LLM-judge
    calibration, baseline, bounded optimization, and baseline-versus-winner holdout calls.
12. After approval, run the live check first. Continue only if it passes.

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

## Approval and budgets

Do not ask the user to design a budget, retry policy, or timeout policy during setup. Before any
paid/provider work, show one concise approval for the full planned first run:

- Baseline plus one optimization.
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

## Baseline and optimization

Use one honest comparison:

1. Baseline: the current configuration exactly.
2. Optimization: one bounded search containing that current configuration.

Use the same tuning slice, evaluator, objective definitions, and call path for both. Run both
connected once if portal comparison matters. Do not:

- Create a 4-8 configuration "manual baseline" unless that sweep is genuinely the current
  production selection process.
- Run a local baseline and then pay to repeat it only for portal appearance.
- Intentionally weaken the baseline.
- Require a second optimization pass before showing the first result.
- Compare different datasets or evaluators.

Keep the configuration space tied to observed failure modes. A knob that does not influence the
agent code is not a real optimization variable. Pin temperature to 0 for frail exact/case-sensitive
metrics unless the evaluator explicitly tolerates surface variation.

Managed `auto` is a guided search, not an exhaustive grid: it may revisit a configuration and may
not try every combination within a small trial budget. The separate one-point baseline run
guarantees the current configuration was measured. If the user specifically needs every
combination in a small space, use connected `grid` only after the installed SDK confirms that
local proposal execution still syncs results; otherwise state that the search is non-exhaustive.

Reasoning models need sufficient output-token headroom; scan for `finish_reason == "length"`.
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
10. Tuning and holdout results are separated.

An optimized winner that does not beat the baseline is a valid no-boost result. Report it
honestly; do not invent improvement.

If any component is synthetic, put the limitation before the score. A synthetic Pareto frontier
can look identical to a production one.

## Recovery

- Portal persistence `degraded`: trials may be present while summaries lag. Explain and verify the
  link before discarding anything.
- Portal persistence `failed`: recover/sync the existing run when supported; do not repay for a
  rerun by default.
- Permanent HTTP validation error or missing `cloud_url`: surface the precise backend reason; do
  not replace it with a guessed explanation or claim portal success.
- Cost limit reached with zero trials: no result exists. Reduce scope or obtain new approval.
- Rate limit or temporary provider outage: preserve partial results and use the SDK/provider
  classification; do not add a duplicate retry loop.
- Invalid credentials, quota exhaustion, or insufficient funds: stop with the specific category;
  do not retry or describe every case as "no tokens."
- Timeout with completed trials: show the best partial result before offering one additional
  bounded pass with its extra approximate time and cost.
- Timeout with zero trials: diagnose provider latency, a hung call, or setup failure before
  considering another run.
- Evaluator exceptions or all-zero/all-one measures: repair evaluator/data and rerun only after
  calibration.
- Dataset examples that fail under every configuration: inspect gold/reference and evaluator
  policy before blaming the model.

Keep logs and artifacts under `traigent-runs/`. Store no secrets, raw private content in run names,
or prompts/outputs in numeric telemetry.

Privacy wording describes Traigent's documented payload contract, not an independent packet audit.
Keep metrics, metadata, experiment names, and errors content-free. Verify the installed SDK's
privacy/offline controls when available; if payload behavior cannot be inspected, say that the
contract was followed rather than claiming network traffic was independently audited.

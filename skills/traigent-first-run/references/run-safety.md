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
- Verify installed packages and public signatures before generating integration code. Dependency
  installation does not authorize importing or executing user/project modules.
- Verify SDK capabilities from the installed version and CLI rather than hardcoding what installs
  "today."
- Build a minimal `.env` for the selected provider. Leave the Traigent key blank until connected
  execution.
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

1. Reuse the project's provider, or ask once and recommend OpenRouter when none exists. If
   OpenRouter is selected, identify every allowed upstream inference provider/route, disclose
   fallback behavior, and pin allowed routes and disable fallbacks when an exact recipient set is
   required.
2. Create the minimal `.env` and stop for the provider-key paste.
3. Run static preflight and deterministic calibration without network calls.
4. Stop for the Traigent portal-key paste immediately before connected work.
5. Present one combined approval covering the smallest live provider/key check, any LLM-judge
   calibration, baseline, bounded optimization, and baseline-versus-winner holdout calls.
6. After approval, run the live check first. Continue only if it passes.

Do not split paid work into repeated approvals unless the plan materially changes.

## Static and mock validation

The bundled `scripts/preflight.py` is a static/free gate. It may read files and public package
metadata, but it must not:

- Import user modules.
- Execute the agent or evaluator.
- Make model/provider calls.
- Contact Traigent or consume optimization quota.

The static gate checks environment, package compatibility, dataset structure/quality, function
signatures from AST, model naming, and safe configuration.

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

Before any paid/provider work, show one combined approval for the full planned first run:

- Baseline plus one optimization.
- Number of dataset rows and trials.
- Agent calls per item.
- Evaluator/judge calls per item.
- Total call floor and composite/retry multiplier.
- Positive provider-request, live-check, judge, baseline, search, and holdout phase timeouts plus
  the explicit provider retry count.
- Estimated runtime, calculated with every permitted retry attempt and composite/judge call rather
  than only the first-attempt call floor.
- Combined worst-case spend and an aggregate walkthrough cap.
- Services receiving data. For OpenRouter this means the OpenRouter gateway plus every allowed
  upstream inference provider/route, with fallback routing disclosed.
- Stop condition.

Derive the named positive timeouts from this approved call plan. A conservative runtime estimate
multiplies each provider-call floor by `(1 + provider retry count)` and its per-request timeout,
then adds judge retries, composite calls, and orchestration allowance. Record the rationale for
each phase timeout. Pass the approved request timeout and retry count to the provider client, pass
the approved baseline/search timeouts to the SDK, and enforce a monotonic deadline around each
holdout phase.

Record an aggregate remaining-budget ledger with separate rows for the live provider/key check,
LLM-judge calibration/evaluation, current baseline, bounded search, retries/composites,
current-configuration holdout, and winner holdout. For each row record allocation, phase
worst-case cost, the charged or conservative deduction, and remaining aggregate cap. Before every
paid phase or call batch, confirm its combined worst-case cost fits the remaining aggregate
budget. Deduct tracked cost when reliable and the approved worst case otherwise. Stop and obtain
revised approval if the next batch does not fit or the planned recipients, routes/fallbacks,
data, call count, model, retry count, or timeout changes.

`TRAIGENT_RUN_COST_LIMIT` limits one SDK optimization call. It does not cover the full walkthrough
and does not enforce the aggregate cap. Do not persist `TRAIGENT_COST_APPROVED=true`; set it only
in the approved process.

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
- Quota failure: reduce samples/trials; do not retry blindly.
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

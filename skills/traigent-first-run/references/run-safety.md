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
  `python3.13 -m venv .venv`, then install with
  `python -m pip install "traigent[recommended]>=0.21" "python-dotenv>=1"`. Verify the installed
  package and public signatures before generating integration code.
- Verify SDK capabilities from the installed version and CLI rather than hardcoding what installs
  "today."
- Build a minimal `.env` for the selected provider. Leave the Traigent key blank until connected
  execution.
- Never paste or print secrets. Check only presence and safe key-shape prefixes.
- Prompts, examples, and outputs are not sent to Traigent by the optimization service.
- The LLM provider still receives whatever content the agent normally sends in model calls.
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

1. Reuse the project's provider, or ask once and recommend OpenRouter when none exists.
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
- Estimated runtime.
- Combined worst-case spend and total first-run cap.
- Services receiving data.
- Stop condition.

Do not present a per-run cap as if it were the total. Do not persist
`TRAIGENT_COST_APPROVED=true`; set it only in the approved process.

Verify selected model IDs are live and cost-tracked before scaling. If a model chosen by the
assistant is unavailable/unpriced, replace it with a comparable working model. If the user chose
it, present the limitation and one recommended alternative.

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

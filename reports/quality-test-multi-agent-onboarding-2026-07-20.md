# First-run onboarding quality test — 2026-07-20

## Verdict

The merged first-run flow at `db35e44247cbd2926a96bdd3abaab79e83c2a524` is safe and
useful, but it was not fully baked at the start of this test. It correctly stopped on weak or
unsupported inputs, kept secrets late, completed a real portal-dev run, and cleaned up its remote
experiments. The test also found reproducibility, provider-routing, path, objective-orientation,
and OpenRouter cost-reading defects that should be fixed before treating the flow as seamless.

The `quality-test-multi-agent-onboarding` harness was also not release-ready as tested. Its
scaffolder omitted the target's installed skill, some scenario expectations described an older
flow, and its Phase-A paid-path probe could execute user code or make an external request. The
matrix remained useful only after captain-side repair and independent adversarial review.

## Scope and method

Phase A dispatched one isolated tester per environment and allowed no real credentials, paid
approval, or paid model calls. Nine scenarios covered:

1. a complete agent, dataset, and evaluator;
2. a weak exact-string evaluator for open-ended generation;
3. a supported populated virtual environment;
4. Python 3.10;
5. a C++ agent;
6. an existing vacant environment with multiple credential names;
7. no virtual environment;
8. no components;
9. a raw provider-SDK call that bypasses LiteLLM interception.

Every worker produced a report and structured findings. A separate reviewer then attempted to
refute every finding against the exact bundled target. The target's own offline suite passed 74
tests, compilation, and skill validation before the real run.

Phase B used a fresh support-ticket classification project with 24 varied examples, a deterministic
evaluator, and a LiteLLM agent. It started without `.env` or a virtual environment. The order was:

1. inspect the project and establish the real task;
2. run standard-library static checks;
3. split 18 tuning and 6 holdout examples;
4. calibrate equivalent-good, partial, and bad evaluator probes locally;
5. create an isolated Python 3.13 environment and install pinned packages;
6. complete a fresh-process offline mock run;
7. only then create and open `.env`, printing its absolute path;
8. show a maximum of 67 calls, an estimate of at most $0.05, and a $0.50 execution ceiling;
9. receive explicit approval and execute against portal-dev.

No secret value was printed or written into this report.

## Real portal-dev result

The approval gate was first invoked without its process-local approval flag and stopped before any
provider or portal request. Across the approved attempts, the workflow completed all 67 planned
calls: the first attempt completed the one-call probe before a local cost-reading failure, and the
second completed the remaining 66 calls without repeating that probe.

| Phase | Result | Tracked cost |
|---|---:|---:|
| Provider liveness probe | Successful; local cost lookup then exposed the OpenRouter bug below | conservatively reserved at $0.001 |
| Current-configuration baseline | 18/18 calls, 0 failures, 83.3% accuracy | $0.0001116 |
| Optimization | 2/2 trials, 36/36 calls, 0 failures; best remained the baseline config | $0.0002232 |
| Blind holdout | baseline 83.3%, winner 83.3%, 12/12 calls | $0.0000777 |

The conservative all-phase total was at most **$0.0014125**, well below both the estimate and
ceiling. The winning configuration remained
`openrouter/openai/gpt-4o-mini`, temperature `0.0`, direct prompt style. A two-trial first run is
allowed to show no improvement; preserving that honest result is more useful than manufacturing a
win.

Both portal-dev experiments were deleted after verification: each DELETE returned 204 and each
follow-up read returned 404. Disposable local scenarios, environments, credentials, and results
were deleted after the report and fix branches were preserved.

## What worked

- The weak open-ended evaluator was rejected before connected work: an exact-string story scorer
  failed sensible calibration because equivalent valid stories would receive zero.
- A six-row dataset was reported as too weak for representative optimization rather than decorated
  as healthy.
- The C++ and raw-provider scenarios were identified as outside the proven-free Python/LiteLLM
  path; the flow did not pretend that a Python demo optimized the real C++ agent.
- With no usable components, the flow built one coherent demo system with varied difficulty rather
  than unrelated agent/data/evaluator examples.
- `.env` was opened only after all applicable free checks and the fresh-process mock passed.
- The real destination was portal-dev, provider fallbacks were disabled, and optimization plus
  blind holdout completed without failed calls.

## Confirmed first-run defects

1. **No reproducible SDK dependency contract.** The flow permits only declared versions but did
   not ship a tested pin or a bounded resolution procedure. On Python 3.10, unpinned pip can install
   the obsolete `traigent==0.0.1` placeholder.
2. **Custom objective direction was implicit.** The canonical wrapper used strings such as
   `task_success`; SDK 0.25 warns and defaults unknown names to maximize. Use explicit
   `ObjectiveSchema` declarations.
3. **The incompatible-environment recovery path collided with `.venv`.** A supposedly separate
   recovery environment was also named `.venv`; use a distinct `.venv-traigent` and preserve the
   original.
4. **Credential inventory was treated as provider selection.** Key names show what credentials
   may be available; the actual agent/model route establishes the current provider. Multiple key
   names alone should not trigger a provider-choice question.
5. **A route/credential mismatch lacked a clear branch.** Preserve the actual current baseline,
   explain the mismatch, and ask before changing the route instead of silently inferring from key
   presence.
6. **Canonical dataset paths were CWD-relative.** A wrapper under `traigent-runs/` resolved
   `traigent-runs/tuning.jsonl` as `traigent-runs/traigent-runs/tuning.jsonl`. Anchor datasets and
   result paths to the wrapper's own directory.
7. **The documented wrapper used `litellm.completion_cost(...)` directly.** A valid OpenRouter
   completion returned successfully, but LiteLLM's local model map lacked the provider-prefixed
   entry and raised before baseline evaluation. OpenRouter had supplied a provider-reported cost,
   and the Traigent SDK later tracked the same model correctly. Prefer provider-reported/public
   cost metadata and fail closed if cost is truly unavailable.

## Confirmed quality-harness defects

1. The scaffolder copied root docs and templates but omitted `skills/`, although `GUIDE.md`
   immediately points there. This is a release blocker.
2. The generated brief and example manifest hardcoded obsolete step numbers, early `.env` state,
   and Traigent-specific oracles despite claiming to be generic.
3. The “empty project” README supplied product intent, so it was not a zero-anchor fixture.
4. The no-venv brief banned every host Python invocation while requiring pre-venv standard-library
   checks, creating an artificial deadlock.
5. The unconditional Phase-A “paid path fails closed” runtime probe was unsafe. Human approval is
   assistant-owned; invoking arbitrary user/provider code with an invalid key can still cause
   network traffic or side effects. Phase A should verify control flow statically unless the target
   supplies a proven no-execution validator.

The harness should not be called stable again until these fixes are forward-tested on at least a
true zero-anchor project, documented-intent/no-components project, complete trio, pre-existing
`.env`, raw-provider bypass, and weak evaluator—with zero Phase-A external requests.

## SDK issue ownership

- Python 3.10 resolving the placeholder package is already tracked by
  `Traigent/Traigent#1594`.
- Default configuration consuming/repeating trial capacity is already tracked by
  `Traigent/Traigent#1808`.
- A public no-execution dataset/agent/evaluator compatibility contract is already tracked by
  `Traigent/Traigent#1979`.
- A cumulative budget spanning baseline, optimization, retries, and holdout is already tracked by
  `Traigent/Traigent#1980`.
- The live OpenRouter failure is in this repo's direct `completion_cost` wrapper path; the SDK's
  own run returned non-zero cost, so it is not evidence that the SDK's previously fixed OpenRouter
  accounting regressed.

No duplicate SDK issue is warranted from this test unless later reproduction shows the SDK itself,
rather than the first-run wrapper, losing the provider-reported cost.

## Real questions that remain legitimate

The seamless path should ask only when the answer changes the user's real system:

- What task should be demonstrated when the project contains no agent, data, evaluator, tests, or
  product-intent anchor?
- Should an unsupported/non-Python agent be wrapped, rewritten, or left unchanged while running a
  clearly labeled demo?
- When the configured model route has no matching credential, should the user add the matching
  credential or explicitly approve a route change?
- When a component is materially weak, should the assistant repair it, continue with a clearly
  labeled limited demo, or pause?

Package versions, retries, timeout arithmetic, and internal phase ledgers are implementation work,
not beginner questions unless a real failure makes a choice necessary.

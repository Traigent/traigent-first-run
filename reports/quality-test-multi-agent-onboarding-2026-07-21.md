# First-run onboarding requalification - 2026-07-21

## Verdict

The merged `traigent-first-run` flow at
`07cb6431e583b53bd99eb0399eb104852a22b92f` completed an eleven-scenario isolated sweep and one
real portal-dev walkthrough. It is substantially baked for its intended first experience: the
zero-anchor gate, component-directed creation, weak-component diagnosis, environment recovery,
late secret entry, bounded connected run, honest no-lift result, and retained portal history all
worked.

The rerun found several narrow integration and safety gaps. This follow-up fixes the
first-run-owned items without adding customer questions or a dependency-lock subsystem. Two
confirmed SDK behaviors remain upstream-owned.

## Scope

Phase A used isolated folders and credentials that were absent or blank. Eleven customer states
covered:

1. supported populated environment;
2. incompatible Python environment;
3. C++ agent in a Python SDK walkthrough;
4. existing vacant environment and `.env`;
5. no environment;
6. true zero-anchor project;
7. raw provider SDK without LiteLLM interception;
8. complete real agent, dataset, and evaluator;
9. task-inappropriate exact-string evaluator for open-ended generation;
10. documented task intent with no implementation; and
11. a tiny, duplicated, corrupted, contract-incompatible dataset.

Every scenario produced a report and structured findings. One reviewer then evaluated all findings
as a single batch against the exact merged target. A separate SDK reviewer reproduced SDK-owned
findings. Phase A made no provider or Traigent service calls and spent `$0.00`.

## Phase-A behavior that passed

- The true empty project showed three `❗` gaps, asked only what the walkthrough agent should do,
  and made zero writes before the answer.
- Documentation that established task intent avoided that question and directed one coherent
  generated agent, dataset, and evaluator around the documented contract.
- A complete valid trio was preserved; no generated substitute replaced it.
- The weak open-ended exact-string evaluator failed equivalent-good calibration and remained
  `❗ invalid`.
- The corrupted dataset reported 3/8 unusable rows, only five structural rows, duplicates, absent
  IDs/split, and a decisive output-contract mismatch. The flow refused to optimize against it.
- The raw provider SDK was never treated as safely intercepted by Traigent mock mode.
- A Python 3.10 `.venv` was preserved while the fallback `.venv-traigent` remained an internal
  recovery detail. Normal projects used the conventional `.venv`.
- Existing customer files and `.env` content were preserved in the simulations.

## Real portal-dev walkthrough

The connected project started with task documentation but no real agent, dataset, or evaluator.
Traigent generated a coherent support-ticket classification walkthrough with 24 distinct synthetic
examples: six each across easy, medium, hard, and very-hard bands, split into 18 tuning and six
holdout rows. A deterministic four-label evaluator passed good/equivalent and rejected partial/bad
probes across all label families.

The run disclosed 67 maximum calls, OpenRouter plus the pinned OpenAI upstream recipient,
disabled fallbacks, an expected runtime of 3-10 minutes, estimated spend below `$0.10`, and the
default `$5.00` walkthrough ceiling before connected work.

| Phase | Result | Tracked cost |
|---|---:|---:|
| One-call provider probe | success; score 1.0; 1.48 seconds | `$0.0000069` |
| Current baseline | 18/18 calls; 0 failures; 83.3% | `$0.00013995` |
| Optimization | 2/2 trials; 0 failures; selected baseline configuration; 83.3% | `$0.0002799` |
| Holdout | baseline 83.3%; selected configuration 83.3%; 12 calls | `$0.0000966` |

Total tracked cost was **`$0.00052335`**. The result demonstrated the workflow but did not show
measured lift, and all three generated components remain walkthrough substitutes rather than
production evidence.

### Follow-up acceptance correction

The one-row baseline and two-row enhanced experiment above are retained as the actual field-test
evidence, but they are not the intended customer comparison. They exposed a regression from the
repository's original goal: the portal should show a credible small parameter sweep beside a
materially broader optimization, not two nearly empty tables.

Because this field case had no user-owned configuration, the corrected generated default uses six
distinct baseline combinations, including its initial configuration, then lets Traigent test up to
12 configurations from a larger space that adds real prompt-policy and self-check controls. A
user-owned baseline remains unchanged, even when it has one row. The intended enhanced display is
10-13 rows; any smaller result now requires a concrete stop, cost, timeout, or failure explanation.
This correction was validated statically and with the package test suite; this report does not
claim another paid portal-dev run occurred.

The customer-facing experiments were retained:

- [Current baseline](https://portal-dev.traigent.ai/experiments/view/580e975e-1254-47f7-92bf-6eb982ad6330?run_id=b81e8dc4-5698-4499-ac4b-d3c30f0815b4)
- [Traigent optimization](https://portal-dev.traigent.ai/experiments/view/2b98d2af-1444-4939-bedf-05e7058f84b3?run_id=cb64515e-3757-4680-8f51-ec5f5f2e6950)

They were not deleted during test teardown. Normal first-run behavior is to keep portal results so
the customer can inspect and compare them. Both links returned HTTP 200 immediately after the run.
A later verification returned the same HTTP 503 upstream-connection response for the portal-dev
root and both experiment URLs, which indicates a portal-dev availability incident rather than
experiment-specific deletion; no rerun or destructive recovery was attempted.

## Confirmed first-run fixes

1. The holdout example now adapts both the canonical scalar input returned by the public loader
   and the example agent's explicit `message` mapping contract. It no longer blindly indexes a
   string as `input_data["message"]`.
2. `.env` creation/update now preserves existing values, comments, and unrelated keys, appends only
   missing blank key names, and requires mode `0600` before secret entry on POSIX. The static
   preflight detects any other POSIX mode.
3. The mandatory pre-install static pass can use `--defer-missing-sdk`, so the intentionally absent
   SDK is a non-blocking `SKIP`; installed unsupported versions still fail.
4. Combined-dataset preflight now reports the actual tuning count and holdout score resolution, so
   a superficially adequate total cannot hide an eight-row tuning slice.
5. Generated wrappers set the SDK results folder beneath `traigent-runs/` before importing
   Traigent, preventing otherwise-surprising project-root `.traigent` artifacts while respecting a
   preserved project override.
6. SDK 0.25.0 validator calls use resolved absolute dataset paths as a documented temporary
   workaround for the upstream nested-relative-path defect.
7. Dependency wording now says exactly what is guaranteed: the three exact top-level pins plus
   their package-declared dependencies. The test explicitly rejected a new cross-platform full
   lock subsystem as unnecessary complexity for this first-run path.

None of these fixes adds a customer setup choice. Retry policy, timeout arithmetic, package
selection, artifact routing, and preflight modes remain assistant-owned implementation details.

## SDK ownership

- [Traigent SDK #1983](https://github.com/Traigent/Traigent/issues/1983) tracks the confirmed
  public validator bug that doubles a nested relative dataset directory during `safe_open`.
- Existing [Traigent SDK #1690](https://github.com/Traigent/Traigent/issues/1690) now includes the
  independently reproduced mock path that prints and persists `First Optimization Complete!` as a
  real achievement. Mock plumbing should not consume a real optimization achievement.

No SDK issue was filed for `.traigent` placement because the SDK already exposes
`TRAIGENT_RESULTS_FOLDER`; the generated first-run wrapper simply needed to use it. No new
`agents-skills` defect was found.

## Sandbox incident

An earlier orchestration attempt was denied when its execution sandbox did not allow the requested
temporary-path write. That was a host tool-policy mismatch, not a Traigent SDK request, onboarding
failure, provider call, or customer-project defect. The same test completed once the execution
environment exposed an authorized writable location. No repository fix is warranted from that
incident; the quality harness already accepts an arbitrary absolute test root, so a constrained
runner can place it inside its allowed workspace.

## Cleanup contract

Disposable local scenarios, virtual environments, generated credentials, SDK reproduction files,
and local run artifacts are removed after the report and branches are preserved. Portal-dev
experiments remain available because customer-visible results are product output, not disposable
test scaffolding.

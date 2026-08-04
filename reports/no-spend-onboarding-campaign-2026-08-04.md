# No-spend first-run customer campaign — 2026-08-04

## Scope and truth boundary

This campaign tested `traigent-first-run` as a customer-facing assistant flow, using absent or blank credentials. It performed local inspection, isolated environment creation, dependency installation where the guide authorized it, static validation, and only proven-local mock paths. It made no provider or Traigent service call, transferred no private customer data, performed no destructive action, and spent `$0` on product/provider usage.

This is Phase A breadth plus a blinded fixture pilot. Phase B—the human-guided provider-backed optimization and portal result—was intentionally not run because the owner requested no spending. The flow is therefore not validated end to end.

Guide baseline: `801df5cedaf25d674de8a7121fc205036416c9c5`.

Fixture-bank baseline: `d742fbc1b8adbcd53c281a87fce5ceca1da5d792`.

## Customer-environment matrix

Seven valid isolated scenarios completed. One initial no-venv attempt was discarded because its worker read mandatory skill files outside its assigned folder; a new worker repeated that scenario in a fresh root.

| Scenario | Customer-like result | Classification |
| --- | --- | --- |
| Existing supported populated venv | Preserved the project-used environment and stopped before downgrading LiteLLM; recommended a separate `.venv-traigent`. | Pass |
| Existing venv on old Python | Preserved the incompatible `.venv`, created `.venv-traigent` on Python 3.12, installed exact top-level pins, and ran local mock plumbing. LiteLLM attempted a remote pricing-map fetch despite Traigent offline mode. | Finding; guide fixed |
| Existing vacant venv | Reused it, installed exact pins, completed a 2/2 intercepted mock, and stopped at the blank local credential file. | Pass with minor follow-ups |
| No venv | Fresh retry created `.venv`, installed exact pins, and completed local mock plumbing. It then opened the credential file even though the SDK reported phantom optimization settings. | Finding; guide fixed |
| C++ raw-HTTP agent | Detected the non-Python/raw-curl boundary statically, did not build or execute it, and stopped at the native-adapter versus labeled-demo choice. | Pass |
| Empty project | Produced 0/100 NOT READY, used `Agent: none discovered`, asked exactly “What should the walkthrough agent do?”, and made zero writes. | Pass |
| Raw provider SDK | Detected the direct OpenAI call statically, did not execute it, and stopped at the limited-dataset repair choice. | Pass |

Evidence roots:

- `/tmp/traigent-phase-a-matrix-Og1IJx`
- `/tmp/traigent-phase-a-retry-Ydlk4G`

The original no-venv folder under the first root is excluded from valid counts. The retry report explicitly confirms it did not read outside its assigned folder.

## Blinded fixture pilot

The canonical six-check bank gate passed before workers ran. Cases ran sequentially in new neutral roots with fresh context-isolated workers.

| Case | Opening | Receipt | Customer stop | Project audit |
| --- | --- | --- | --- | --- |
| 02 | 45/100 PARTIAL; `set-f1` + `structured` | `MATCHED SNAPSHOT` | Dataset repair / labeled demonstration / pause | `UNCHANGED` |
| 06 | 0/100 NOT READY; no task-kind | `MATCHED SNAPSHOT` | Exact task-intent question | `UNCHANGED` |
| 08 | 33/100 PARTIAL; task kind `code`, no method for constant-pass evaluator | `MATCHED SNAPSHOT` | Repair walkthrough copies or pause for production fixes | `UNCHANGED` |

Valid pilot result: **3/3 matched receipts and safe stop behavior**.

Evidence roots:

- Case 02: `/tmp/traigent-onboarding-attempt-k0tEShNj/run/captain-artifacts`
- Case 06: `/tmp/traigent-onboarding-attempt-3OMbWaou/run/captain-artifacts`
- Case 08: `/tmp/traigent-onboarding-attempt-cYK2Al9J/run/captain-artifacts`

Excluded attempts were retained instead of rewritten:

- `/tmp/traigent-onboarding-attempt-CaYAuv1R/run`: captain omitted the explicit no-extra-opening-arguments instruction; worker added component-state flags.
- `/tmp/traigent-onboarding-attempt-ixMB5JhV/run`: worker obeyed the corrected argument boundary but the public CLI did not yet distinguish Python `code` from SQL `code-sql`.
- The first case-02 captain capture normalized JSON floats to integers and correctly failed exact grading; the raw stdout was recaptured without transformation and then matched.

## Confirmed defects and fixes prepared

### `traigent-first-run`

1. Set `LITELLM_LOCAL_MODEL_COST_MAP=true` with `TRAIGENT_OFFLINE_MODE=true` before every mock import/invocation. Independent blocked-socket measurement observed eight connection attempts without it and zero with it.
2. Treat task kind as grounded run-scoped evidence from the opening gate onward; close the CLI vocabulary and distinguish executable `code` from SQL-query `code-sql`.
3. Resolve permutation semantics from product/tests/evaluator evidence and ask only when materially unresolved.
4. Represent a zero-agent project canonically as `Agent: none discovered` until intent creates or selects an agent.
5. Route a mock report that says trial settings are not consumed back to adapter repair; do not open credentials while optimization remains phantom.
6. Preserve the existing one-compatible-project-environment rule while keeping the resident and total guidance budgets below their locked ceilings.

### `quality-onboarding-fixtures`

1. Correct cases 02, 03, and 20 from stale `execution`/`code-sql` declarations to their implemented `set-f1`/`structured` contract.
2. Correct case 08 so a constant-pass evaluator does not privately inherit `execution`; its opening method is absent and task kind is `code`.
3. Bind scorer and opening snapshots to the selected evaluator bytes with SHA-256 digests.
4. Add two mutation probes proving evaluator rewrites invalidate both snapshot profiles.
5. Allow grounded opening task kinds while keeping zero-anchor cases task-kind-free.
6. Bump both materially changed snapshot contracts to profile version 2.

## Remaining findings to track

1. Add a hermetic regression that imports the pinned LiteLLM/Traigent mock path under a blocked/counting socket and asserts zero outbound attempts. Current package tests lock the guidance, while the independent environment test supplied the behavioral evidence.
2. Detect superficial numbered/template variants or semantic-family concentration. Cases 02 and 08 each received full diversity credit despite only six and four underlying behaviors respectively.
3. Let opening readiness represent “evaluator exists but is statically invalid/unmeasured” rather than rendering it as absent when no honest evaluator method can be declared.
4. Consolidated polish: decide a transitive dependency lock/hash policy; align held-back-set wording with the optional first-run validation policy; clarify undeclared-provenance PASS wording; label mock dollar columns as pricing metadata; and ask the owner to confirm a detached credential opener became visible.
5. Move evaluator method/task-kind declarations out of a standalone hard-coded table into a reviewed, customer-visible-evidence contract so the initial declaration cannot be self-consistently wrong. The new digest guard catches later evaluator rewrites, not a wrong declaration authored on day one.

## Verification evidence

- Guide: `python3 -m unittest discover -s tests -q` — 418 tests, OK.
- Guide behavior lock: `python3 tools/relock.py --check` — up to date.
- Fixture bank: canonical `check_bank.py --guide-src ...` — all six checks PASS.
- Fixture mutation suite: 45 deliberate corruptions detected, including both evaluator-digest mutations.
- Fixture skill: repository and system `quick_validate.py` — valid.
- Python formatting/imports: Black, isort, and `py_compile` — clean.
- Blinded pilot: three valid `MATCHED SNAPSHOT` verdicts and three `UNCHANGED` audits.

No claim in this report treats a fixture snapshot match as independent correctness or calls Phase A an end-to-end validation.

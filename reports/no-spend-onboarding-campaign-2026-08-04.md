# No-spend first-run customer campaign — 2026-08-04

## Scope and truth boundary

This campaign tested `traigent-first-run` as a customer-facing assistant flow, using absent or blank credentials. It performed local inspection, isolated environment creation, dependency installation where the guide authorized it, static validation, and only proven-local mock paths. It made no provider or Traigent service call, transferred no private customer data, performed no destructive action, and spent `$0` on product/provider usage.

This is Phase A breadth plus a blinded fixture pilot. Phase B—the human-guided provider-backed optimization and portal result—was intentionally not run because the owner requested no spending. The flow is therefore not validated end to end.

Guide baseline: `801df5cedaf25d674de8a7121fc205036416c9c5`. The test harness — an internal
multi-agent test runner — was pinned to a single revision for the whole campaign; its identifiers
live in its own history, not here.

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

The bounded [sanitized evidence manifest](no-spend-onboarding-campaign-2026-08-04-evidence.json)
records the durable matrix results. Raw transcripts were locally observed in ephemeral isolated
roots and are not published in this repository. The original no-venv attempt is excluded from
valid counts; its fresh retry explicitly confirmed it did not read outside its assigned folder.

## Blinded scenario pilot

The canonical six-check bank gate passed before workers ran. Cases ran sequentially in new neutral roots with fresh context-isolated workers.

Three blinded cases ran, spanning the readiness range from a project with no discoverable task
intent to partially ready projects with material dataset or evaluator limitations. All three
pilot cases matched their expected readiness receipts exactly, each worker stopped at the
intended customer decision point — a genuine question or repair choice, never an unauthorized
action — and every project audit came back `UNCHANGED`. Per-case identifiers, expected scores,
and expected receipts are withheld here: this repository is the customer-visible handoff a future
blinded worker reads. Earlier public revisions carried these rows, so these pilot cases are
treated as burned for future blinded runs.

Valid pilot result: **3/3 matched receipts and safe stop behavior**.

The sanitized evidence manifest records the aggregate pilot counts. Raw command transcripts were
local, ephemeral observations and are not claimed as durable or independently reproducible
evidence.

Excluded attempts were retained instead of rewritten:

- One attempt was excluded because the captain omitted the explicit no-extra-opening-arguments instruction and the worker added component-state flags.
- One attempt was excluded because the worker obeyed the corrected argument boundary but the public CLI did not yet distinguish Python `code` from SQL `code-sql`.
- One captain capture normalized JSON floats to integers and correctly failed exact grading; the raw stdout was recaptured without transformation and then matched (a grading artifact of a valid case, not an excluded attempt).

## Confirmed defects and fixes prepared

### `traigent-first-run`

1. Set `LITELLM_LOCAL_MODEL_COST_MAP=true` with `TRAIGENT_OFFLINE_MODE=true` before every mock import/invocation. A local blocked-socket probe observed eight connection attempts without it and zero with it. Its raw log was ephemeral, so this is a local observation rather than a CI-backed regression result.
2. Treat task kind as grounded run-scoped evidence from the opening gate onward; close the CLI vocabulary and distinguish executable `code` from SQL-query `code-sql`.
3. Resolve permutation semantics from product/tests/evaluator evidence and ask only when materially unresolved.
4. Represent a zero-agent project canonically as `Agent: none discovered` until intent creates or selects an agent.
5. Route a mock report that says trial settings are not consumed back to adapter repair; do not open credentials while optimization remains phantom.
6. Preserve the existing one-compatible-project-environment rule while keeping the resident and total guidance budgets below their locked ceilings.

### Test harness

1. Correct the cases whose declared evaluator contracts had gone stale against the contract their fixtures actually implement.
2. Stop a constant-pass evaluator from privately inheriting an evaluation method its fixture never demonstrates; declare its opening method as absent.
3. Bind scorer and opening snapshots to the selected evaluator bytes with SHA-256 digests.
4. Bind both snapshot profiles to evaluator bytes and a customer-visible output
   contract; add corruption probes proving evaluator-method and task-kind evidence
   drift cannot remain green.
5. Allow grounded opening task kinds while keeping zero-anchor cases task-kind-free.
6. Bump both materially changed snapshot contracts to profile version 3.

## Remaining findings to track

1. Add a hermetic regression that imports the pinned LiteLLM/Traigent mock path under a blocked/counting socket and asserts zero outbound attempts. Current package tests lock the guidance, while the independent environment test supplied the behavioral evidence.
2. Detect superficial numbered/template variants or semantic-family concentration. Two pilot cases received full diversity credit despite few underlying behaviors.
3. Let opening readiness represent “evaluator exists but is statically invalid/unmeasured” rather than rendering it as absent when no honest evaluator method can be declared.
4. Consolidated polish: decide a transitive dependency lock/hash policy; align held-back-set wording with the optional first-run validation policy; clarify undeclared-provenance PASS wording; label mock dollar columns as pricing metadata; and ask the owner to confirm a detached credential opener became visible.

## Verification evidence

- Guide: `python3 -m unittest discover -s tests -q` — 418 tests, OK.
- Lock freshness: `python3 tools/relock.py --check` — up to date.
- Harness: the canonical six-check bank gate — all six checks PASS.
- Harness mutation suite: 51 deliberate corruptions detected, including evaluator-
  digest, output-contract-digest, and independent task-kind/evaluator-method mutations.
- Harness package: repository and system package validation — valid.
- Python formatting/imports: Black, isort, and `py_compile` — clean.
- Blinded pilot: three valid `MATCHED SNAPSHOT` verdicts and three `UNCHANGED` audits.

No claim in this report treats a snapshot match as independent correctness or calls Phase A an end-to-end validation.

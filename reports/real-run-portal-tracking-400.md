# Real-Run Field Test — portal tracking silently lost to an HTTP 400

**What this is.** A *real* (non-mock) first-run of `GUIDE.md`, driven by a coding assistant
against a customer agent (`Traigent/demo_sql_spider`, a text2SQL agent) with a funded OpenRouter
key and a **valid production `TRAIGENT_API_KEY`**. Unlike the `$0` matrix in
[`first-run-field-test.md`](first-run-field-test.md), this one reached the paid step — and there
the enhanced/portal run **silently degraded to local-only tracking** on an HTTP `400`, so nothing
reached the portal even though the key was valid and the session was created. This report is the
evidence + root-cause dig, written so **backend / SDK / schema / frontend** agents can each pick up
their slice.

**Spend: ~$0.03.** Only the aborted first baseline trial made real LLM calls (~30, one config ×
the dataset, before it was killed on the first 400). Every diagnostic probe below used a **no-LLM
`SELECT 1` agent**, so the entire investigation was free. OpenRouter credit moved `1.973220 →
1.942723` (−$0.0305). The full paid run was **not** executed (deliberately stopped).

**Environment.** `traigent 0.20.0`, Python 3.13.14, production backend
`https://portal.traigent.ai` (`TRAIGENT_BACKEND_URL` unset), OpenRouter vendor key (funded),
account `IsraelTraigent`. Agent: single-call NL→SQL, scored by execution match via a
`custom_evaluator` emitting `{accuracy, cost, latency}`; weighted `ObjectiveSchema`
(accuracy 0.80 / cost 0.15 / latency 0.05); enhanced space = 48 combinations
(4 models × 3 temps × 2 prompt styles × 2 generation paths).

---

## What happened (timeline)

1. Wiring + a free mock dry-run passed (metric sanity, config injection, both generation paths).
2. The real run launched (baseline first). On the **first trial submission** the backend returned
   `HTTP 400 — "Invalid request data. Please check your input."` The SDK classified it
   **PERMANENT**, printed a hint that it was *"commonly an invalid optimization objective/metric
   name, e.g. 'cost_usd' instead of 'cost'"*, and continued in `source='local_fallback'` — i.e.
   **no portal run**. Run was killed immediately to avoid paying for untracked trials.
3. Chasing the SDK's hint wasted effort: removing the one "extra" metric (`exec_accuracy`) did
   **not** fix it, and three objective/metric shapes (accuracy-only; `["accuracy","cost","latency"]`;
   weighted `ObjectiveSchema`) **all** still 400'd — *but only because each probe was itself
   mis-declared* (see F1/F3). The SDK's hint pointed at the wrong thing.
4. Capturing the **raw** backend body (the SDK only logs a paraphrase) revealed the real reason:
   `config["model"]` was outside the session's declared categorical domain.
5. With the space and `default_config` made consistent, **every** shape is accepted and returns a
   real `cloud_url` — including the exact structure of the original baseline call. So the original
   permanent-400 was **not reproducible** from the config afterward (see F4).

---

## Findings

### F1 — SDK discards the backend's precise `details.reason` and prints a hardcoded, misleading guess  ·  **owner: SDK**  ·  severity: high (diagnosability)

The backend's 400 body is precise:

```json
{"details":{"reason":["submitted config[\"model\"] is outside the declared categorical domain (choices declared at session create)"]},
 "error":"Invalid request data. Please check your input.","error_code":"VALIDATION_ERROR",
 "message":"Invalid request data. Please check your input.","success":false}
```

But `traigent/cloud/trial_operations.py` throws that precision away:

- **`:830`** builds the user-facing detail as
  `detail = parsed.get("error") or parsed.get("message") or detail` — it never reads
  `parsed["details"]["reason"]`, so the one field that says *what is actually wrong* is dropped.
- **`:848–857`** then hardcodes a **guess** into the error log: *"commonly an invalid optimization
  objective/metric name, e.g. 'cost_usd' instead of 'cost'"*. In our case the real cause was a
  **config domain** mismatch, not a metric name — the guess actively misdirected debugging for
  a long time.

**Fix (SDK):** surface `parsed.get("details", {}).get("reason")` in the logged message; drop or
demote the hardcoded example guess. This one change turns a multi-probe investigation into a
one-line read.

### F2 — A permanent 400 degrades to `local_fallback` silently; the run "succeeds" with no portal URL  ·  **owner: SDK + portal/UX**  ·  severity: high (silent data loss)

After the 400, `optimize_sync()` returns **normally** with `stop_reason` set and
`results.cloud_url is None`; trials are computed and stored locally. A first-run user with a
**valid** key sees a normal results table and reasonably believes the run is on the portal — it
is not. The guide already tells the assistant to check `cloud_url` for the *auto→local* fallback,
but **not** for this *400→local* path, and the SDK itself does not make the degradation loud.

**Fix:** (a) SDK — make `local_fallback` after a *permanent* rejection prominent (distinct return
flag / non-zero-ish signal), not just a warning line; (b) `GUIDE.md` Step 9/10 — add an explicit
post-real-run gate: *assert `results.cloud_url is not None`, else the run is local-only — stop and
diagnose before claiming a portal link.*

### F3 — `default_config` (or any submitted config value) outside the declared `configuration_space` → 400, with no client-side pre-check  ·  **owner: SDK + backend**  ·  severity: medium (footgun) · **deterministically reproducible**

The backend rejects any trial whose config value isn't in the domain declared at *session create*.
It is easy to violate without noticing: a `default_config` value not present in
`configuration_space` is submitted as-is (the "default"/baseline trial) and 400s. Minimal repro:

```python
# space declares model=[A] but default_config uses model=B  -> first trial 400s
traigent.optimize(configuration_space={"model": ["openrouter/deepseek/deepseek-chat"], ...},
                  default_config={"model": "openrouter/openai/gpt-4.1-mini", ...}, ...)
```

**Fix (SDK):** validate `default_config ⊆ configuration_space` locally and fail fast with a clear
message *before* any backend call (and before spending on the trial's LLM work). **Backend:** the
`message` field should carry the reason too, not only `details.reason` (see F1).

### F4 — The original real-run 400 was not reproducible from the config afterward  ·  **owner: backend (needs logs) — the cross-repo research anchor**  ·  severity: unknown

The original failing call was `run_agent.optimize_sync(configuration_space=BASELINE_SPACE,
algorithm="grid", max_trials=10)` where the decorator declared the (superset) enhanced space and
`default_config.model` ∈ both spaces. Re-running the **same structure** later (fresh decorate →
same override → grid → 10 trials, no-LLM agent) **succeeds** and returns a portal URL. So the
permanent-classified 400 on the very first submission is **not** explained by the static config.
Candidate causes that need backend/SDK correlation on the session IDs below:

- a per-worker **session-storage race** (the SDK references BE #1194 for a *transient*
  session-not-found 400) returning a 400 that was **mis-classified as permanent** on first submit;
- a first-submit **validation state** on session create vs. the enhanced-space-decorator +
  baseline-override interaction (declared-domain snapshot timing);
- an evaluator-emitted **value** specific to the real (LLM) path that the no-LLM repro doesn't hit.

This is exactly what warrants schema/backend/SDK eyes together — see the raw session IDs in the
appendix.

### F5 — Recipe emits a non-objective metric; guide lacks a `cloud_url` gate  ·  **owner: docs / traigent-skills / first-run**  ·  severity: low

`traigent-skills/.../quickstart_text2sql.md` emits `metrics={..., "exec_accuracy": ...}` — an extra
metric outside the declared objectives. **Tested: the backend accepts it** (a consistent-space
probe with `exec_accuracy` returned a `cloud_url`), so it is *not* a bug today — but it is a latent
footgun if the backend ever tightens metric-name validation, and it's what the SDK's misleading F1
hint blames first. Worth aligning the example to emit exactly the declared objectives. Also fold
the F2 `cloud_url` gate into `GUIDE.md`.

---

## Cross-repo research pointers

| Repo / agent | Look at |
|---|---|
| **backend** | Why session `b96e1c29-1f94-4050-ba3f-f78e191c2f53` rejected its first trial as a *permanent* 400 (F4). Confirm the categorical-domain validation semantics (F3). Put the reason in `message`, not just `details.reason` (F1). Is there a per-worker session-create/first-submit race (BE #1194 relatives)? |
| **sdk** | `trial_operations.py:830` (surface `details.reason`) and `:848–857` (drop the hardcoded guess) — F1. Local `default_config ⊆ configuration_space` pre-validation — F3. Make post-permanent-400 `local_fallback` loud / return a flag — F2. |
| **schema** | The config-run submission carries `"schema_version": "1.0"`. Confirm SDK 0.20.0 ↔ production backend schema compatibility for the trial-result payload, and whether the declared-domain contract is versioned/documented. |
| **frontend / portal** | A valid-key run that degrades to `local_fallback` leaves **no** portal trace. Should rejected/attempted sessions surface anywhere so a user isn't left thinking a run exists? |
| **docs / traigent-skills / first-run** | F5: align the text2SQL recipe's emitted metrics to the declared objectives; add the `results.cloud_url is not None` gate to `GUIDE.md` Step 9/10. |

## Reproduction (all free — no-LLM `SELECT 1` agent)

The probe scripts live in the agent repo under `traigent-runs/` (`probe_raw.py` captures the raw
backend body via a one-line monkeypatch of
`TrialOperations._handle_trial_error_response`; `probe_spaces.py` shows enhanced / separate-baseline
/ call-time-override all accepted; `probe_repro.py` shows the exact original structure accepted).
Minimal F1/F3 repro is the snippet in F3 plus reading the raw `error_text` in the SDK handler.

## Appendix — evidence

- **Original failure:** session `b96e1c29-1f94-4050-ba3f-f78e191c2f53` (baseline; enhanced never ran).
- **Raw-body domain error captured:** session `8b6859c1-8399-4214-a891-32f57cc992ea` →
  `details.reason = "submitted config[\"model\"] is outside the declared categorical domain"`.
- **Accepted probes (returned `cloud_url`):** enhanced-no-override `70c8bb71-…`; separate-baseline
  `51421fad-…`; baseline-override `f4ec1763-…`; extra-metric(`exec_accuracy`) `5a888830-…`;
  exact-original-structure `8226706b-…`.
- **SDK refs:** `traigent/cloud/trial_operations.py` `:830`, `:848–857` (0.20.0).
- **Backend 400 body:** `error_code":"VALIDATION_ERROR"`, generic `message`, precise `details.reason`.

---

## Update — backend-source validation (via dev cluster) + filed issues

Validated against the backend **source** and the **dev** cluster's observability (Kuberly MCP →
`triagent-dev` Loki/Grafana), with **no full run** (the prod `uk_` key is rejected `unauthorized`
on the dev backend, so fresh dev sessions would need a dev key; findings were confirmed from code
+ dev logs instead).

- **Owning service:** `traigent-backend` (repo `Traigent/TraigentBackend`), structured JSON logs
  (`request_id` / `trace_id` / `error_code`).
- **F3 confirmed at source:** `TraigentBackend/src/services/traigent/interactive_session_service.py`
  → `_validate_submitted_config` (`:1152`, invoked from the results route `:4018`). Fail-closed
  anti-smuggling validation: subset-keys (`:1173`); **type-strict** categorical membership
  (`:1187`, `type(value) is type(choice)` — `True`≠`1`, **int `0`≠float `0.0`**); int/float
  bounds. Backend docstring confirms the reason message is intended to "reach logs" → **F1** (the
  SDK should surface it).
- **F4 mechanisms (now concrete):** (A) type-strictness → numeric-type drift (int `0` vs declared
  float `0.0`) trips it while `0.2`/`0.4` never can; (B) call-time `configuration_space=` override
  may desync the create-time declared domain from the optimizer's explored values. Exact original
  trigger unknown **because F1 discarded `details.reason`**.
- **Dev == prod for these findings:** the dev backend runs the same image, so this validation is
  authoritative for prod too. (Aside, not a finding: the `traigent-prod-eks` observability endpoint
  was unreachable via Kuberly during this session — an infra/access matter independent of the
  Traigent API key and orthogonal to the bugs here.)

### Filed issues (one per finding, in the owning repo)

| Finding | Issue |
|---|---|
| F1 (SDK) | Traigent/Traigent#1782 |
| F2 (SDK + portal) | Traigent/Traigent#1783 |
| F3 (SDK + backend) | Traigent/Traigent#1784 |
| F4 (backend anchor) | Traigent/TraigentBackend#2020 |
| F5 (docs/skills) | Traigent/traigent-skills#177 |

### Dev Grafana/Loki capture (server-side proof)

Reproduced the domain-400 on **dev** (session `dcd10e3a-2e18-43d0-a9b6-3390493e6310`) and pulled the
backend's own log from the dev `traigent-backend` pod:

- **ERROR** `src.routes.traigent_session_routes._build_error_response` (`:892`):
  `TraiGent submit_results failed: VALIDATION_ERROR - submitted config["model"] is outside the declared categorical domain`
- Traceback: `traigent_session_routes.py:1671 submit_results` → `interactive_session_service.py:3811 submit_results` → `:1098 _validate_submitted_config` → `raise ValueError`.
- `error_code=VALIDATION_ERROR`, `exception_type=ValueError`, `trial_id=trial_de2be31881f44658`, `trace_id=8cfbcf6ca033e366962a3f59465261aa`.
- Flow (one `request_id`): `POST …/next-trial` → **200**, then `POST …/results` → **400** — i.e. the backend handed out a config its own submit-validator rejects. Optimizer is **Optuna** (`traigent_interactive_<session_id>` study).
- Accepted contrast: `portal-dev.traigent.ai/experiments/view/d8ec0ba8-163e-4d19-98a8-44e318b822d6`.

### Next steps — ownership

| Issue | Agent | Next action |
|---|---|---|
| Traigent#1782 (F1) | **SDK** | Surface `details.reason` in `trial_operations.py:830`; drop hardcoded guess `:848–857`; unit test. |
| Traigent#1783 (F2) | **SDK** + **Frontend** | SDK: loud/typed signal on permanent-400 `local_fallback`. Frontend: show rejected sessions in portal. |
| Traigent#1784 (F3) | **SDK** (+ **Backend**) | SDK: local `default_config ⊆ space` + numeric-type-consistency pre-check. Backend: confirm int/float strictness intent. |
| TraigentBackend#2020 (F4) | **Backend** (+ **SDK**) | Audit `next-trial` / default-trial vs `_validate_submitted_config`'s create-time domain (the `next-trial`→200 / `results`→400 desync). Exact original structure passes on **dev and prod** → intermittent; catch it with a real run, or pull the original `b96e1c29-…` server log. |
| traigent-skills#177 (F5) | **Docs/skills** | Align recipe metrics to declared objectives; mirror the `cloud_url` + type-consistency gate. |
| traigent-first-run#20 (PR) | **Docs** | Review + merge the GUIDE `cloud_url` gate; link the five issues. |

---

## Update 2 — real root cause found (real run on dev) + multi-agent triage

A **real** online run on **dev** (full 30-example set + real agent) — the first time the *real*
failure was reproduced rather than a synthetic probe — supersedes the F4 framing above.

> **Guide philosophy — no workarounds baked in.** This PR does **not** patch `GUIDE.md` to work
> around F1–F5; those are fixed at the source (the tracked issues). The only guide change is a
> minimal, fix-surviving one: verify `results.cloud_url is not None` for both runs before claiming
> a portal link — sound defensive practice regardless of the bugs. Everything else here is an
> investigation record pointing at the issues that fix the root causes.

### Real root cause (this session's failure): duplicate `example_id`

The dev backend log (session `7fecb016-…`) shows the true cause:
`VALIDATION_ERROR - Example 3: duplicate example_id 'world_1'; …` →
`traigent_session_routes.py:1166 _validate_submission_measures`. The evaluator emitted
`example_id = db_id`, which is **non-unique** (30 examples → 10 databases). Deterministic, caller-side.
The earlier "intermittent / categorical-domain" F4 story was an artifact of reproducing with **1-row**
probes (one row can't collide). **Fix:** unique `example_id` (db_id + question hash) → the run then
tracked cleanly to the dev portal (`experiments/view/482d616d-…`, 7 trials, 0 failed, **63.3%**).

**Confirmed on prod (F4 closed):** the original prod anchor session `b96e1c29-1f94-4050-ba3f-f78e191c2f53`
(trial `trial_47b828673aae47e1`, 12:02:50 UTC) shows the **same** `VALIDATION_ERROR - duplicate
example_id 'world_1'; …` in prod Loki — not a domain desync. The sibling demo `demo_sql_toy` ships the
**same** constant-`example_id` bug → **demo_sql_toy#8**. The two real backend desyncs the audit found
are independent → **TraigentBackend#2021**; the orphan-persistence decision → **TraigentBackend#2023**.

### New issue: SDK Rust panic

`pydantic-core` (pyo3 0.28.3) `dictionary changed size during iteration` on a worker thread during
parallel evaluation → **Traigent#1785** (client-side; snapshot-before-serialize).

### Multi-agent triage (what the team validated)

- **Backend (F4 / TraigentBackend#2020):** confirmed **two real, deterministic** `next-trial`↔`submit`
  desyncs — (1) `value_map` categoricals validate keys not mapped values; (2) conditional-default
  type-loose-create / type-strict-submit (genuinely intermittent). Corrected "Mechanism A" (plain
  categoricals are type-safe backend-side). Filing a separate fix-ready bug + regression test. **So F4
  surfaced real backend bugs *and* this session's separate duplicate-`example_id` cause; F1 hiding
  `details.reason` is why they were conflated.**
- **Frontend (F2 / Traigent#1783):** confirmed the portal has **no session-keyed surface** and zero
  concept of `cloud_url`/`local_fallback`; a rejected run leaves no trace. Fix is mostly a **backend
  persistence decision** (persist the rejected session as an experiment → FE already renders it as
  *Registered*/*Failed*). One contingent FE gap: no field to show the rejection reason.
- **SDK (F1, F3, #1785):** not yet engaged — the highest-leverage queue (F1 unblocks everyone's
  diagnosis).
- **Docs (F5 / traigent-skills#177):** not yet engaged.

### Refreshed ownership / next actions

| Issue | Owner | Status → next action |
|---|---|---|
| Traigent#1782 (F1) | **SDK** | ⏳ not started — surface `details.reason` (`:830`), drop the guess (`:848–857`). *Do this first; it unblocks diagnosis everywhere.* |
| Traigent#1785 (panic) | **SDK** | ⏳ not started — snapshot the dict before pydantic-core serialization on worker threads. |
| Traigent#1783 (F2) | **SDK** + **FE** | FE ✅ scoped → **Backend** decides rejected-session persistence; then SDK adds the loud `local_fallback` signal. |
| Traigent#1784 (F3) | **SDK** | ⏳ — add local pre-checks: `default_config ⊆ space`, numeric-type consistency, **`example_id` uniqueness**. |
| TraigentBackend#2020 (F4) | **Backend** | 🟢 audited → land the two-desync fix + regression test; decide rejected-session persistence (unblocks FE). |
| traigent-skills#177 (F5) | **Docs** | ⏳ — align recipe metrics + require unique `example_id` + `cloud_url` gate. |
| traigent-first-run#20 (PR) | **Docs** | review/merge — PR = investigation report + a **minimal general** `cloud_url` check only; **no bug-workarounds** (F1–F5 fixed at source). |

### Post-fix validation (dev) — and why the customer should never face the domain-400

After the `example_id` fix, a full 30-example no-LLM run tracked cleanly to portal-dev
(`experiments/view/ecdecc5f-…`, 0 failed) — the previously-broken duplicate-`example_id` path is
gone. One 400 did appear first, but it was **self-inflicted by the validation probe**: it declared a
model space (`[deepseek]`) that **excluded its own `default_config` value** (`gpt-4.1-mini`), so the
default trial was out-of-domain. That is the **#1784** footgun, not a new bug — and *a customer
should never face it*. On released `0.20.0` a `default_config ∉ configuration_space` still yields a
cryptic backend 400 → silent local-only; the **#1784 client-side pre-check (merged to develop)**
catches it **locally, with a clear message, before any submission**. This is exactly why #1784
matters — and why the guide must **not** teach a manual "keep default_config in the space"
workaround: the SDK guard is the fix, and it ships on develop.

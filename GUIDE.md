# Traigent First-Run Guide (for the coding assistant)

You are the user's coding assistant. Your job: take a user who has an AI agent and
wants to optimize it, and walk them — **step by step, in order** — from zero to a
real Traigent optimization run they can see in the portal (<https://portal.traigent.ai/>),
showing their **Pareto frontier** (best accuracy for the least cost).

Use your most capable model with high effort. This guide is **Python-only**.

> **What Traigent does, in one breath:** you keep running your agent locally; the SDK
> sends only *configuration choices and numeric scores* (accuracy / cost / latency —
> "ACL") to Traigent's cloud optimizer, which proposes the next model + knob
> combination to try, and converges on the best configurations. Your data, prompts,
> outputs, code, and keys never leave the machine.

---

## Operating rules (read once, apply throughout)

- **Do the technical work yourself.** The user's job is small: get a couple of keys
  ready, answer a few questions, and watch. Detect and decide; ask the user only
  when the choice is genuinely theirs or a hard gate requires it.
- **You don't know what's in their system — find out, don't assume.** Inspect the
  project, the language, the venvs, the agent, the data. When something is ambiguous
  or missing, ask a specific question; never guess at file paths, providers, or which
  function is "the agent."
- **Hard gates — always pause and confirm:** (1) any **paid** LLM run, (2) anything
  that would send data off the machine, (3) destructive edits. Always **dry-run free
  first**, then ask before spending.
- **Secrets go in `.env`, never in the chat.** If the user says "here's my key,"
  stop them — open `.env` for them to paste into. Never echo, log, or read a key back.
- **Offer at most 3 options, mark one Recommended,** with a one-line trade-off each.
- **If something breaks,** explain it to the user calmly and positively, with a clear
  action item, and tell them what to relay to Traigent if it's a Traigent-side snag.
  Even if the portal can't show a run, you can always present results locally.
- **Named skills add depth (optional).** Where a step points at a skill by name —
  e.g. `traigent-decorator-setup` — that is a Traigent skill in
  <https://github.com/Traigent/traigent-skills>; read it there for full detail. This
  guide inlines what you need for the happy path, so you can proceed without it. The
  lifecycle spine is the `traigent` skill (dry-run-first / cost-approval).

---

## Step 0 — Make sure you have the repo, then greet the user

If you were handed this guide as a link (not an already-cloned repo), clone it first so
you have `.env.example` and `templates/` on hand:
`git clone https://github.com/Traigent/traigent-first-run` (then `cd` into it, or copy
those two files into the user's project as you go).

Then show the user this message (verbatim is fine):

> Your coding assistant does the technical work for you. It tells you what to do only
> when it needs you. Your job is small: get a couple of things ready, answer a few
> simple questions, and watch. By the end you'll have a real optimization run in the
> Traigent web portal — your best accuracy for the least cost.
>
> Before we start, it helps to have ready: (1) a Traigent account + API key, and
> (2) one LLM key with a few dollars on it (OpenRouter is easiest). I'll show you
> exactly where to put them. Spend is capped at $5 per run and I always do a free
> dry-run first and ask before anything paid.

Then proceed. Don't wait for the keys yet — you'll set them up at Step 3.

---

## Step 1 — Confirm the environment

- **Python 3.11–3.13.** Detect what's installed (`python --version`, check for venvs,
  global, pyenv). If it's missing or too old, install/select a supported version —
  default to **3.13** for a clean slate. Don't make the user do this.
- The user does **not** need Node.js or any JavaScript runtime for this guide.

If the user has no project open yet, ask for the path to the project that contains
the agent they want to optimize, and `cd` into it.

---

## Step 2 — Install Traigent and verify (free, no keys)

Prefer a project virtualenv (standard practice; also avoids PEP 668
"externally-managed-environment" on modern Linux):

```bash
python3.13 -m venv .venv && source .venv/bin/activate   # Windows: py -3.13 -m venv .venv
pip install "traigent[recommended]>=0.18"
```

- **Pin the interpreter** (`python3.13`, not a bare `python`) so the venv honors Step 1's
  "default to 3.13" rather than whatever `python` happens to resolve to.
- If the project already has a venv, install into it — **unless it is built on an
  unsupported Python** (< 3.11). Re-running `python -m venv` over an existing directory is a
  **silent no-op** (it does *not* swap the interpreter): recreate it cleanly with
  `python3.13 -m venv --clear .venv` (or `rm -rf .venv` first). Several venvs → ask which.
- **Pin a version floor and verify after install.** Use `"traigent[recommended]>=0.18"` — on
  a too-old interpreter pip can otherwise silently resolve to an ancient **`traigent 0.0.1`**
  placeholder (it declares `>=3.8`), exit 0, and leave you with *no real SDK*. Confirm with
  `traigent --version` (expect ≥ 0.18); if the command is missing you got the stub —
  recreate the venv on Python 3.11–3.13.
- `traigent[recommended]` pulls the common integrations. (`pip install traigent` alone
  also works — `litellm` is a core dependency, so the keyless mock path runs either way.)

**Verify it works** with a free, fully-mocked run (no keys, no spend — say so clearly):

```bash
traigent quickstart        # bundled mock-mode demo (keyless, no provider spend)
# or:  python -m traigent.examples.quickstart
traigent info              # version, Python, integrations, defaults
```

> The SDK also ships `traigent onboard` (an interactive device-login that can write
> credentials to `.env` via `--write-env`) and `traigent first-prompt` (points at a separate
> `traigent.ai/agent.md` funnel). Those are **different entry points** — **this** repo's
> `GUIDE.md` is the flow to follow; don't run `onboard --write-env`, or it will fight Step 3's
> careful "`.env`, never in chat" setup.

If install/verify fails, diagnose (→ `traigent-debugging`), try the
next option (different venv / global), and only escalate to the user if still stuck.

---

## Step 3 — Set up keys in `.env` (never in chat)

Copy the template and open it for the user to paste into:

```bash
cp .env.example .env        # this repo ships .env.example; or create one next to the agent
```

Open `.env` in a **standalone editor window** for them and **always print its absolute
path** as the fallback. Quick opener by OS — macOS `open -t .env`, Windows `notepad .env`,
Linux `${EDITOR:-nano} .env` (or `xdg-open .env`); for edge cases see the
`traigent-quickstart` skill's `.env` procedure. Then guide them:

**a) Traigent platform key (required).** From <https://portal.traigent.ai/register> →
sign in → **API Keys** → **+ Create API Key** → choose **Full access**. It begins with
`uk_` or `tg_`. Paste into `TRAIGENT_API_KEY=`.

**b) Backend URL.** Keep `TRAIGENT_BACKEND_URL=https://portal.traigent.ai` (already in
the template). The SDK already defaults to the cloud, so this **pins** it explicitly —
which avoids surprises if stored CLI dev credentials or an old env var point at a local
dev backend instead.

**c) One LLM vendor key.** First read the existing `.env`; then:
- **Exactly one** vendor key present → use that vendor; tell the user which you picked.
- **More than one** present → ask which to use for this run (it drives cost + model list).
- **None** present → ask which they want and add it.

> **"Present" means a real, non-empty key value.** Ignore blank assignments (`OPENAI_API_KEY=`)
> **and** any leftover `# ...` hint text after the `=` — treat those as *absent*. (A value-side
> comment is read verbatim by `python-dotenv` as the key, so a placeholder line would
> otherwise look like a configured vendor and skew this count.)

| Vendor | `.env` variable | Notes |
|---|---|---|
| **OpenRouter (recommended)** | `OPENROUTER_API_KEY` | One key, many low-cost/open-source models. Get a key: <https://openrouter.ai/keys> · add credits: <https://openrouter.ai/credits>. Model id via LiteLLM: `openrouter/<vendor>/<model>`. **Fund it** (a few $) — a free-tier key returns HTTP 402 and silently fails trials. |
| OpenAI | `OPENAI_API_KEY` | `gpt-*`; key validated before the run |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-*`; validated before the run |
| Google (Gemini) | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | `gemini-*`; validated before the run |
| Mistral | `MISTRAL_API_KEY` | `mistral-*`; validated before the run |
| Cohere | `COHERE_API_KEY` | `command-*`; validated before the run |
| HuggingFace | `HF_TOKEN` | Works, but **not** pre-validated; name HF models explicitly (no auto-detection) |
| Bedrock | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` | `bedrock/*` |

**d) Cost cap.** `TRAIGENT_RUN_COST_LIMIT=5.00` is set in the template. Leave
`TRAIGENT_COST_APPROVED` commented out — you'll approve interactively at Step 9.

After the user pastes and saves: confirm `.env` is git-ignored — and **if the project has no
`.gitignore`, create one** covering `.env`, `.venv/`, and `__pycache__/`, so a later
`git init` can't commit secrets.

Load the keys into the environment when you run. Be aware that **`litellm` (a core
dependency) calls `load_dotenv()` on import** in its default DEV mode — so once any
LiteLLM-backed call runs, a project/CWD `.env` is auto-loaded into `os.environ`, *including*
run-control variables (`TRAIGENT_RUN_COST_LIMIT`, `TRAIGENT_COST_APPROVED`,
`TRAIGENT_OFFLINE_MODE`). Those then take effect **even for "keyless" commands** like
`traigent quickstart` (e.g. a stray low `TRAIGENT_RUN_COST_LIMIT` in `.env` will cancel its
trials). Importing `traigent` alone is lazy and does *not* auto-load, and the auto-load walks
from the CWD — so still prefer an explicit `python-dotenv` `load_dotenv()` as the robust path
(deterministic, covers a venv not nested in the project, keeps keys out of shell history).
Fall back to `export` only if needed.

---

## Step 4 — Identify the agent to optimize

Read the project. Find the function that is the **scoreable agent behavior** — the
smallest function whose input/output you can evaluate (not an HTTP route, auth layer,
retry wrapper, or generic provider client).

- Exactly one candidate → use it.
- Several LLM-calling functions → list them and ask which one. Optimize one per run.
- None found → ask the user to point you to it (or offer to create a tiny example agent
  so they can see the flow — a small **Python** LiteLLM function, e.g. the quickstart's
  `python -m traigent.examples.quickstart`, makes the dry-run free and mockable).
- **Found, but it's not Python** (a C++/Go/Rust binary, a shell script, an HTTP service in
  another language) → **stop and say so**: `@traigent.optimize` only wraps **Python
  callables** (this guide is Python-only). Offer the options explicitly: (a) a thin Python
  **wrapper** that calls the agent as a subprocess/HTTP — ⚠️ but the binary's *own* LLM calls
  go straight to the provider and are **not** mocked, so any dry-run on it **bills for real**
  (see Step 8); (b) reimplement just the **LLM-calling path** in Python; or (c) a clearly
  **labeled Python demo** that will **not** optimize their real agent. Never silently fall
  through to the "tiny example" and let the user think their actual agent was optimized.

→ `traigent-boost-agent` (Step 1, ANALYZE) has grep patterns and
agent-"shape" markers (single call, cheap-vs-expensive, chain, router, tool loop, …)
that you'll reuse when choosing knobs at Step 7.

---

## Step 5 — Get a dataset and an evaluation method

Optimization needs three things: the **agent**, a **dataset** (input + expected
output), and an **evaluation method**. Resolve the dataset first:

- **Has a dataset** (input / output / expected) → use it.
- **Has logs/traces but no dataset** → build a JSONL dataset from them and ask the user
  to verify it.
- **Has nothing** → ask the user for 3–5 example input/output pairs; synthesize up to
  ~20+ from them, ensure **at least one-third are hard cases** (ambiguous phrasings, inputs
  that fit more than one label, or short/low-signal inputs), and ask the user to verify/rank.
  (< ~10 examples is too few to be meaningful.)

Dataset format is JSONL, one example per line with `input` and `output`:
```jsonl
{"input": "I was charged twice for my subscription", "output": "billing"}
{"input": "The API returns a 500 on POST", "output": "technical"}
```
→ `traigent-curate-dataset` owns dataset building, growth, and scoring.

**Evaluation method** — pick by output type:
- Crisp/closed answers (labels, yes/no, multiple-choice, exact strings, runnable SQL)
  → a **deterministic** scorer (exact-match / MCQ / execution).
- Open-ended answers (summaries, explanations, writing) where string-match would score
  everything 0 → **LLM-as-a-judge**.
→ `traigent-choose-metric` (pick) and `traigent-build-evaluator`
(build). Audit any LLM judge → `traigent-evaluator-audit`.

---

## Step 6 — Wire the `@traigent.optimize` decorator

Wrap the chosen function. **Default to zero-code-change injection** so you don't have
to rewrite the user's agent:

```python
import traigent
from traigent.api.decorators import InjectionOptions

@traigent.optimize(
    eval_dataset="eval.jsonl",
    objectives=["accuracy"],                 # add "cost"/"latency" only to trade accuracy away
    injection=InjectionOptions(injection_mode="seamless"),  # zero code change
    configuration_space={...},               # filled in Step 7
)
def my_agent(query: str) -> str:
    model = "gpt-4o-mini"                     # a NAMED local matching a config key — seamless rewrites this
    ...                                       # Traigent rewrites the matched assignment's value per trial
```

- **Seamless** (recommended) injects tuned values automatically — but only where it can
  *find* them: each config key must appear as a **named local assignment**
  (`model = "..."`, `temperature = 0`) or a **function parameter** whose name matches the
  key. ⚠️ **Seamless cannot inject a value that isn't a matching name** — a literal written
  directly in the call (`litellm.completion(model="gpt-4o-mini", temperature=0)`), a value
  read via `os.environ.get(...)`, or any kwarg built dynamically at the call site. For those
  it logs `Seamless provider found no injectable targets … ran with original values` and
  runs **every trial with the original config — a silent no-op** (no error, no failed trial).
  So when wiring seamless, make each tunable a named local/param; otherwise use context mode.
- If seamless can't apply to this code, fall back to **context** mode and read the
  config inside the function: `cfg = traigent.get_config()`, then pass `cfg["model"]`,
  `cfg["temperature"]`, etc. into the call. ⚠️ In context mode, any tuned knob that
  shadows a function parameter **silently stays at its default unless you read it via
  `get_config()`** — otherwise tuning is a no-op.
- Do **not** add `expected` to the function signature — it's a scoring label, not an
  input; including it fails every trial.

→ `traigent-decorator-setup` (injection modes, objectives, evaluation,
`experiment_name` labeling).

---

## Step 7 — Choose the knobs (config space) — ask the service, don't hardcode

What to tune comes from **Traigent**, not from guesses. Get recommendations for this
agent's shape:

```bash
traigent recommend --list-types   # valid types (currently: rag, code_gen)
traigent recommend rag            # evidence-backed knob recs — pass the closest type
```
Pick the closest type (`rag` or `code_gen`); if neither fits (e.g. a single-call
classifier), build the space from the agent's real knobs instead. Or in Python:
```python
from traigent.config_generator.recommendations import recommend_configuration_space
rec = recommend_configuration_space("rag")   # or "code_gen"; list_recommendation_agent_types()
configuration_space = rec["configuration_space"]
print(rec["caveat"])                          # always show: recs are starting points, not guarantees
```

Then build the space from: the recommendations **+ the agent's real knobs** (prompt
/style variants, temperature, sample count) **+ model variety across vendors and price
tiers** (one premium + a couple of mid/low-cost models is the single biggest cost lever).

> **Keep prompt text out of the config space.** Encode prompt/style variants as short
> **labels** (e.g. `prompt: ["v1", "v2"]`) and map each label to the real text *inside* the
> function — do **not** put raw prompt text as config-space values. Config choices are synced
> to Traigent's optimizer; labels keep your actual prompts on the machine.

**Adapt the knobs to the chosen models — don't assume a knob exists everywhere.**
Some knobs (e.g. reasoning *effort* / high-med-low) exist only on certain models
(o-series, gpt-5-class), not on all. For any model-specific knob:
1. apply it only to models that support it (use a constraint), **or**
2. if the user's vendor has no model that supports it, widen across **more models**
   instead, **or**
3. if neither is possible, ask the user to add a model, **or** run a minimal sweep with
   what's available.

Config-space syntax (dict lists / tuples, or `Range`/`IntRange`/`Choices`/`LogRange`,
constraints) → `traigent-configuration-space`. Knob packs by agent
shape (cascades, routing, self-consistency, verification gates) →
`traigent-boost-agent` + `traigent-composite-knobs` +
`traigent-run-recommendations`.

Record the run in `templates/run-plan.md` (copy it per run). For a full service run
plan, see the `traigent-run-plan` skill — note `traigent plan` is optional and needs
several required flags (`--task-description --dataset-size --objective --max-trials
--cost-limit`) plus a reachable backend, so it's not a zero-arg command.

---

## Step 8 — Dry-run first (mock, free, offline)

Always validate the whole pipeline at zero cost before spending anything.

> **FIRST — Mock ≠ universal interception — this is the one that can cost money.** Mock only
> intercepts LLM calls made via **LiteLLM or LangChain**. A raw
> `openai.chat.completions.create(...)` / `anthropic.messages.create(...)` call inside the
> user's untouched agent is **not** mocked and **bills the provider for real**, even in this
> "free" dry-run. **Check the call path before you run the block below.** If the call goes
> through LiteLLM/LangChain (or `injection_mode="seamless"`, which intercepts the LiteLLM
> path), the dry-run is free. If it calls a provider SDK directly, route it through LiteLLM
> for the dry-run, **or** set a tiny `TRAIGENT_RUN_COST_LIMIT` (e.g. `0.05`) as a backstop and
> treat it as a paid run under the cost gate.

```python
import os
os.environ["TRAIGENT_OFFLINE_MODE"] = "true"   # no backend egress
from traigent.testing import enable_mock_mode_for_quickstart
enable_mock_mode_for_quickstart()              # mocks LiteLLM/LangChain calls (see caveat above)
results = my_agent.optimize_sync(max_trials=4, algorithm="random")
```

Pass criteria: `len(results.trials) > 0`, `len(results.failed_trials) == 0`, and
`stop_reason` is `max_trials_reached`/`optimizer` (not `error`).

- **Also confirm the tuning actually took effect.** With a *seamless* decorator, watch the
  run output for `Seamless provider found no injectable targets … ran with original values`.
  If it appears, **injection silently no-opped** — every trial ran the *same* config, so the
  optimization is meaningless even though the criteria above still pass. This warning is the
  only signal (don't try to infer it from score/config variation — the optimizer varies the
  *proposed* configs regardless, and mock scores are constant). Treat its presence as a
  **fail**: fix the agent per Step 6 (named local/param, or context mode) **before** any paid
  run.
- With a deterministic scorer, mock scores are uniformly 0.0 — that's **expected** (the mock
  returns a constant string); you're checking *plumbing*, not scores. A benign
  `minimal_logging is only effective for offline local runs …` line also prints on every run.

> **Mock ≠ offline.** Mock stops LLM cost; it does **not** stop backend egress. For a
> truly local free dry-run, also set `TRAIGENT_OFFLINE_MODE=true` (above) — otherwise a
> "mock" run with a key set still hits the portal and counts against quota.

**Evaluator sanity gate** (free, catches the most expensive silent failure): assert your
metric rewards a known-good output (≥ 0.9) and penalizes a known-bad one (≤ 0.1) before
any paid run. → `traigent` (Step 3.5).

---

## Step 9 — Run it (baseline and/or enhanced)

Ask the user which they want:
1. **Baseline only** — their agent as-is, measured.
2. **Enhanced only** — Traigent-optimized.
3. **Both, for comparison** *(recommended for a first run)*.

> **Verify model IDs are live first** (`traigent models --provider <p> --check <id>`) —
> a delisted/renamed id wastes the run on a 404.

**Baseline (local).** Measure the agent at its *current* configuration for a
before/after comparison. Keep it off the portal with the offline **env var** — offline
is set via `TRAIGENT_OFFLINE_MODE` (or the decorator's `offline=` argument), **not** by a
keyword on `optimize_sync()`, where it is silently ignored:

```python
import os
os.environ["TRAIGENT_OFFLINE_MODE"] = "true"   # local only — results NOT synced to the portal
results_baseline = my_agent.optimize_sync(max_trials=1)   # one point = a quick baseline
os.environ.pop("TRAIGENT_OFFLINE_MODE", None)   # clear it before the enhanced run
```

It still makes real LLM calls (a real measurement), so the cost gate/cap apply. For a true
single-config baseline, restrict the space to the agent's current values for this pass (see
the `traigent-run-optimization` skill).

Because you run Python **non-interactively**, the cost gate can't show a prompt — and its
pre-run **hard stop is conditional**, so don't over-rely on it. It aborts (raises, e.g.
`OptimizationError` / `UnknownModelError`) only when the estimate **exceeds**
`TRAIGENT_RUN_COST_LIMIT` or the model is **unpriced**. A priced run whose estimate is
**under** the cap **proceeds into real paid calls** with only an informational cost *warning*,
and **without** requiring `TRAIGENT_COST_APPROVED`. So **you** must enforce approval: get the
user's explicit "yes" before any paid run (below) rather than trusting the SDK to block. (A cap
set *below* the per-trial estimate instead returns `results` with `stop_reason=="cost_limit"`
and **0 trials** — no exception — so check `results.stop_reason`, not only exceptions.) After
the user's "yes," set `TRAIGENT_COST_APPROVED=true` for this run too (the $5 cap still binds);
for an unpriced baseline model, set `TRAIGENT_CUSTOM_MODEL_PRICING_*` or expect a clean abort.

**Enhanced (portal).** This is the run the user will see online:
```python
# .env already provides TRAIGENT_API_KEY, TRAIGENT_BACKEND_URL, and the $5 cap
# (TRAIGENT_RUN_COST_LIMIT). Approve cost first (see the cost gate below).
results = my_agent.optimize_sync(max_trials=20, algorithm="auto")  # "auto" = cloud smart, syncs to portal
```
- Use `algorithm="auto"` — the cloud smart optimizer **converges in far fewer trials
  than a full grid**, which is what keeps a wide search under the $5 cap. Keep offline
  **off** for this run — leave `TRAIGENT_OFFLINE_MODE` unset (offline never reaches the portal).
- **Cost gate (hard stop):** estimate the run first — up to `max_trials × dataset_size`
  LLM calls — show the user the estimate and the $5 cap, and only proceed on their
  explicit "yes." Then set `TRAIGENT_COST_APPROVED=true` (or pass `cost_limit=` /
  handle `OptimizationError` if the estimate exceeds the cap).
- Also mind **plan quota**: a run reserves ~`max_trials × dataset_size`
  `optimization_samples`; on the free tier the ceiling is small. Size the run to fit.

→ `traigent-run-optimization` (algorithms, `cost_limit`, `stop_reason`,
parallel trials, quota sizing) and `traigent` (the full dry-run → approve
→ real-run lifecycle).

---

## Step 10 — Show the result in the portal

Give the user the direct link to their run — it's `results.cloud_url` (also
`results.experiment_id` / `results.run_label`; `cloud_url` is `None` for an offline run, so
don't fabricate a URL). A results table also prints locally during the run, so they see it
regardless of the portal; otherwise inspect `results.best_config` / `results.best_score` /
`results.trials`.

→ `traigent-analyze-results` (read `best_config` / `best_score` / the
quality-vs-cost trade-off) and `show-significant-tuned-variables` (which
knobs actually mattered).

---

## Step 11 — Decide on a second run (deterministic, not "maybe")

Apply this rule — don't hand the user a vague "you could try…":

- **IF** best accuracy is below the user's target **AND** budget/quota remain →
  run a **second** run focused on the examples that failed in run 1, plus similar ones
  pulled in to refill the subset (~30–50). Then either (a) route easy inputs to run 1's
  optimum and hard inputs to run 2's optimum, or (b) adopt run 2's optimum if it's
  better overall.
- **ELSE** (target met, or budget/quota exhausted) → **stop** and report.

Drop knobs that showed no effect; add ones you now suspect matter (Step 7's service
recommendations + importance from Step 10). → `traigent-next-run` and
`traigent-iterate` choose the next single hypothesis from server signals.

---

## Step 12 — Summarize and (optionally) promote

Tell the user, plainly:
- what they learned (baseline vs best config — the accuracy/cost/latency delta),
- where their agent stands, and the Pareto frontier they can choose from,
- the single best next step (one hypothesis, not a bundle).

**Before shipping a winning config to production:** export it as a *candidate*, check it
on a held-out slice, and apply only after the gate passes and the user approves —
never promote straight from the run. → `traigent-ci-safety-gate`.

```python
my_agent.export_config("candidate_config.json")   # candidate for review/gating
# after the holdout gate passes AND the user approves:
my_agent.apply_best_config(results)
```

End with: *optimization is not one-and-done* — models, prices, and questions change, so
re-optimizing periodically keeps the agent on its frontier. Point power users at the full
skill set: <https://github.com/Traigent/traigent-skills>.

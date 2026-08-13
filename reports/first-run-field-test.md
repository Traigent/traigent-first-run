# First-Run Field Test — multi-agent onboarding QA

> **Historical record (2026-06-30).** This report describes an earlier revision of the guide — the Step 1–9 flow — kept as it was written; the current flow differs.

**What this is.** A field test of this repo's onboarding flow (README → `GUIDE.md` →
`.env.example` → `templates/`, the flow as it stood when this test ran; `templates/` has since
been deleted in favour of the files it pointed at) run the way a real user would: a coding assistant follows
`GUIDE.md` step by step. Instead of one run, we ran **seven in parallel**, each in a different
"customer environment," to find where the guide breaks, misleads, or risks spend — **before**
a real user hits it. The doc/flow fixes in this PR come from this test; this report is the
elaborated evidence behind them.

**Spend: $0.** No paid LLM call was made by any agent. See *Money-safety* below.

---

## Method (reproducible)

A "captain" agent designed a scenario matrix, scaffolded each scenario as an **isolated folder
+ its own venv** (with realistic user data and a bundled copy of this repo as the "clone"), then
dispatched **one sub-agent scoped to each folder** to play the user's assistant and follow
`GUIDE.md`. A final pass independently **audited venv isolation**, **adversarially verified every
finding** against the bundled guide, and synthesized the result. (Harness: an
internal multi-agent test runner.)

| # | Scenario | Environment under test |
|---|---|---|
| 1 | happy path | Python 3.13 venv + a LiteLLM agent + dataset + one vendor key |
| 2 | unsupported runtime | venv on **Python 3.10** (below the 3.11 floor) |
| 3 | non-Python agent | the agent is **C++** (`@traigent.optimize` is Python-only) |
| 4 | vacant venv | an existing **empty** venv + **two** vendor keys present |
| 5 | no venv | no venv at all + no `.env` |
| 6 | empty project | **no agent, no dataset, no venv** (from-scratch path) |
| 7 | raw provider SDK | agent calls the **OpenAI SDK directly**, bypassing LiteLLM |

Scenarios 1–5 are the environments a first run actually lands in; 6–7 were added to probe the
"create from scratch" path and the guide's biggest money caveat.

## Money-safety (why a docs test can't bleed spend)

Layered so any one layer alone reaches $0: (a) every `.env` held **non-functional placeholder
keys** → any real call is an auth error = $0; (b) agents were restricted to the **free
mock+offline** path and read-only CLI verbs, and forbidden to approve cost or run a paid
optimization; (c) a tiny `TRAIGENT_RUN_COST_LIMIT` with `TRAIGENT_COST_APPROVED` unset. The
one scenario that *did* emit a live network call (scenario 7, raw OpenAI SDK — correctly **not**
intercepted by mock) returned HTTP 401 on the placeholder key, which both confirmed the money
trap is real **and** that the placeholder safety net works.

## Interpreter / library isolation (audited)

Every scenario used **only its own in-folder environment** (typically `python3.13` /
`traigent 0.18.0`; scenario 2 is deliberately on Python 3.10 — where it gets the `0.0.1` stub
per finding #6 — and scenarios 5–6 start with no venv and create their own): no global,
`--user`, or `--break-system-packages` installs; no cross-scenario venv reuse. This was verified
independently per scenario (in-folder `sys.executable` + `traigent.__file__`, and a re-run of
the free mock dry-run with the folder's own interpreter where one applies). Note: a **global
`traigent 0.18.1.dev4`** editable build exists on the machine's system Python — distinct from
the in-folder `0.18.0` and **never used**, confirming isolation held.

## Limitations — what this run did NOT exercise (honest scope)

To keep the matrix **$0 and non-interactive**, each scenario used placeholder keys and the
agents were told to *record* the human-handoff moments rather than perform them. So this run
rigorously covered the **mechanical path** (install, venv, decorator, dry-run, fail-closed) plus
**money-safety and isolation** — but it did **not** exercise the guide's **interactive Step 3
handoff** end to end:

- No agent actually **popped open the `.env`** in an editor (GUIDE Step 3's *"open `.env` in a
  standalone editor window … print its absolute path"*). They ran `cp .env.example .env` and
  *inspected* the file, then recorded the "which vendor / paste your key" moment as a question.
- No agent pasted a **real key** or ran a **paid** optimization (by design).

These live handoffs are covered separately by a **real guided run with a human in the loop** —
the captain following the guide *to the word* with the owner (popping open the `.env`, a small
approved OpenRouter run). The test harness was also updated so future agents **perform the
assistant's half** of interactive steps (run the `.env` opener + print the path) rather than
only recording them.

---

## Findings → fixes in this PR

Severity reflects impact on a real first run. "Test-induced" items are called out honestly and
**not** treated as repo bugs.

### Fixed here (repo-actionable)

1. **`.env.example` — value-side comments become garbage keys (major).** Each of the six vendor
   lines shipped an inline hint, e.g. `OPENAI_API_KEY=              # gpt-* (validated...)`.
   `python-dotenv` (which Step 3 mandates) reads everything after `=` as the value; with only
   spaces before the `#`, the inline-comment stripper never fires, so **every unfilled key
   parses to the non-empty string `'# gpt-* ...'`**. That breaks Step 3c's "how many vendor keys
   are present?" logic (all six look present) and can make the SDK auth with garbage. Verified
   directly on the shipped file (a *filled* line parses fine; only *unfilled* lines break).
   **Fix:** hints moved to their own comment lines above each key; values left bare (verified
   they now parse to `''`). *Clear fix.*

2. **Seamless injection can silently optimize nothing — and the dry-run still "passes" (major).**
   Seamless (the recommended default) only injects where a config key appears as a **named local
   assignment or matching parameter**. For a literal in the call (`...completion(model="gpt-4o-mini")`),
   an `os.environ.get(...)` read, or a dynamically-built kwarg, it logs `Seamless provider found
   no injectable targets … ran with original values` and runs **every trial with the original
   config** — no error, no failed trial. Step 8's pass criteria all still pass → a **false green**
   before a paid run that tests one configuration. Instrumented proof: across a 3-model × 2-temp
   space, the value reaching `litellm.completion` was the original on **all** trials.
   **Fix (per owner review):** Step 6 now uses a **single injection mode — context** (read every
   tuned knob from `traigent.get_config()`), which is explicit and cannot silently no-op.
   **Seamless was removed from the first-run path** — for a first-run guide it's overwhelming
   detail with a silent-no-op footgun — and survives only as a one-line pointer to
   `traigent-decorator-setup` (it's still a valid SDK mode for agents already structured for it).
   Step 8 keeps a simple "confirm you read every tuned knob from `get_config()`" check. *Rationale:*
   a first run's whole payoff is the cloud run *varying* the knobs, so the path must be a mode that
   provably applies them — and the guide should present one obvious way, not a footgun to avoid.

3. **Step 3 wrongly says the SDK doesn't auto-load `.env` (docs, high-impact).** `litellm`
   (a core dep) calls `load_dotenv()` on import in its default DEV mode, so a project/CWD `.env`
   **is** auto-loaded — including run-control vars (`TRAIGENT_RUN_COST_LIMIT`, etc.), which then
   affect even keyless commands like `traigent quickstart`. This is the real residual behind a
   cluster of *test-induced* "quickstart failed" reports (see below). **Fix:** Step 3 corrected;
   explicit `load_dotenv()` kept as the robust path. *Pro/con:* corrects a false mental model;
   we deliberately did **not** adopt "`load_dotenv()` is unnecessary" — `import traigent` alone is
   lazy and the auto-load is CWD-dependent.

4. **Step 9 overstates the cost gate (docs).** It says the gate "fails closed (raises
   `CostLimitExceeded`/`UnknownModelError`)." In fact the pre-run hard stop is **conditional**:
   it fires only when the estimate exceeds the cap or the model is unpriced; a priced run **under**
   the cap proceeds into real calls with only a warning and **without** `TRAIGENT_COST_APPROVED`.
   **Fix:** Step 9 now describes the conditional behavior and tells the assistant to enforce
   approval itself (and to check `results.stop_reason`, not only exceptions). *Pro/con:* accurate
   and prevents over-reliance on SDK enforcement; low residual risk since the guide already
   mandates explicit human approval.

5. **Step 4 has no branch for a non-Python agent (docs).** The three branches (one / several /
   none) leave the C++ case (scenario 3) to fall through to "none → tiny example," producing a
   demo that doesn't optimize the user's real agent. **Fix:** added a fourth branch (stop; explain
   Python-only; offer wrapper / Python rewrite / labeled demo, with the wrapper's money caveat).
   *Clear fix.*

6. **Steps 1–2: the venv can land on the wrong interpreter (docs).** `python -m venv` binds to
   whatever `python` resolves to, and re-running it over an existing dir is a **silent no-op**
   (only `--clear` swaps the interpreter). **Fix:** pin `python3.13`, use `--clear` for a stale
   venv, pin a `>=0.18` floor, and verify `traigent --version` after install — which also guards
   the **`traigent 0.0.1` stub** that pip silently installs on Python 3.10 (see SDK-side note).
   *Clear fix.*

7. **Step 8: the money caveat sat *after* the code block (minor).** A less-careful assistant
   copies the dry-run block before reading the "raw SDK isn't mocked" warning. **Fix:** hoisted
   the caveat to immediately precede the block. *Pro/con:* presentation-only, but the call-path
   check is the load-bearing instruction for the raw-SDK case.

8. **Step 3: no `.gitignore`-create step (minor).** "Confirm `.env` is git-ignored" doesn't cover
   a project with no `.gitignore`. **Fix:** added the create case. *Clear fix.*

9. **Step 5: "hard case" undefined (minor).** Added a one-clause parenthetical (ambiguous /
   multi-label / low-signal). *Clear fix.*

10. **Step 2: `traigent onboard` / `first-prompt` funnels undisclosed (minor).** The SDK ships a
    parallel `onboard --write-env` device-login that would conflict with Step 3's manual `.env`
    flow. **Fix:** one disambiguating line that this repo's `GUIDE.md` is the flow to follow.
    *Pro/con:* prevents an off-script device-login; reconciling the SDK's parallel funnels is
    really an SDK/product item.

### Intentionally **not** changed

- **"`quickstart`/dry-run cancelled by `cost_limit` / 0 trials" (test-induced, not a repo bug).**
  Several agents hit this — but it was caused by the **test harness** seeding
  `TRAIGENT_RUN_COST_LIMIT=0.02`. The **shipped `.env.example` uses `5.00`** and does **not**
  reproduce it. The only real residual is finding #3 (`.env` auto-load), already fixed. We did not
  "fix quickstart."
- **Step 7 classifier knobs.** Agents wanted a starter knob list for a single-call classifier;
  the guide already says "build the space from the agent's real knobs" and points at
  `traigent-configuration-space`. Left as-is to avoid duplicating that skill.

### Heads-ups for the SDK / PyPI team (outside this repo's control)

- **Key-portal URL split.** `traigent quickstart` (which Step 2 runs) prints
  `app.traigent.ai`, while this repo is consistently `portal.traigent.ai`. Align the SDK message
  (or confirm a redirect). *This repo is already canonical; nothing to change here.*
- **`traigent 0.0.1` stub installs on Python 3.10.** The placeholder release declares
  `Requires-Python >=3.8`, so on 3.10 pip silently resolves to it (exit 0, no real SDK). Yank it
  or set its `Requires-Python >=3.11`. *Mitigated guide-side by the new version pin + verify.*
- **`minimal_logging is only effective for offline local runs …`** prints on every run, including
  offline ones. Cosmetic; root cause is SDK-side. *Noted as benign in Step 8.*

---

## The questions a real assistant brings back to the user

These are the genuine "I need you to decide" moments the testers surfaced — the human-facing
output of the test:

1. **Wiring (scenarios 1, 2, 5):** "Your agent reads the model from `os.environ.get(...)` and
   hardcodes `temperature=0`, so seamless injection tunes nothing. Switch to context mode
   (`cfg = traigent.get_config()`), or restructure so model/temperature are named locals to use
   the seamless SDK mode (see `traigent-decorator-setup`)?"
2. **Non-Python agent (scenario 3):** "Your agent is C++ and `@traigent.optimize` only wraps
   Python. Wrap it as a subprocess (note: its own LLM calls aren't mocked and bill real money),
   rewrite the LLM path in Python, or run a labeled demo that won't optimize your real agent?"
3. **Old Python (scenario 2):** "Your `.venv` is Python 3.10 (traigent needs ≥3.11). Create a new
   3.13 venv alongside it, or replace `.venv` (simpler, but your installed packages are removed)?"
4. **Vendor choice (scenarios 4, 5):** "Which provider for this run — OpenRouter [recommended],
   OpenAI, Anthropic, Gemini, or other? I'll show you the exact `.env` line to fill — never paste
   a key in chat." (Scenario 4 had two keys present → which to use.)
5. **From scratch (scenario 6):** "There's no agent yet — what should the example do (summarize /
   classify / extract)? For classification, which labels? Give me 3–5 example notes with correct
   labels and I'll synthesize ~20, including hard cases."

---
name: traigent-first-run
description: >-
  Guide a first-time, possibly non-technical user through their FIRST Traigent
  optimization on one of their own agents — end to end, safely, to a real result
  they can see in the Traigent portal. Use when a user says "run my first Traigent
  optimization", "optimize my agent for the first time", "help me get started with
  Traigent", "set up Traigent on my agent", "try Traigent", or points you at the
  Traigent/traigent-first-run repo. Carries the beginner-safety spine (free mock
  dry-run first, human approval before any spend, verify-the-run-was-real, secrets
  only in .env) so the money and honesty gates hold even before the full GUIDE.md
  is loaded. NOT for experienced Traigent users tuning an already-wired agent — use
  the traigent-skills lifecycle skills for that.
---

# Traigent First-Run (beginner-safe onboarding)

You are the user's coding assistant, driving their **first** Traigent optimization. The user
may not be a programmer. Your job: carry them from zero to a real, honest optimization run in
the Traigent portal — the best accuracy for the least cost — without ever surprising them with
spend or a misleading result.

**Canonical procedure:** the full, self-contained step-by-step lives in this repo's
[`GUIDE.md`](../../GUIDE.md) (steps 0–12) with a one-command preflight in
[`templates/preflight.py`](../../templates/preflight.py). Read GUIDE.md and follow it in order —
it is authoritative and more detailed than this file. This SKILL.md is the **spine + the
non-negotiable gates**, kept inline so they hold from the first message even before you open the
guide. Where the guide names a `traigent-*` skill, it lives in
<https://github.com/Traigent/traigent-skills>.

## How to deliver it (beginner doctrine)

- **Plain and warm, one sentence at a time.** No jargon, no internal file paths, no walls of
  caveats, no checklists of everything you did. Do the technical work quietly; report only the
  milestones that matter to the user.
- **Do the work yourself.** The user's job is small: get a couple of keys ready, answer a few
  questions, watch. Inspect their project instead of asking them to; ask only when the choice is
  genuinely theirs (which agent, which vendor) or a hard gate requires it.
- **Say what you're doing before anything that pops an approval** (a paid run, opening a file,
  a command box) — one plain *what* and *why*.
- **Be honest, never a salesperson.** The baseline is *their* agent measured fairly. If tuning
  barely helped, say so. Never dress up a zero delta; never imply they *need* Traigent.
- **At most 3 options, one marked Recommended,** one-line trade-off each.

### Readiness scoreboard

After your first look at the project, render a warm three-item scoreboard — Agent, Dataset,
Evaluation — so the user sees exactly what unlocks their first run. **Base each line on what that
first look actually found**, never a fixed template: a piece you can already see is green; one you
genuinely haven't reached yet is a warm red. Open on the honest score — an all-red `0/3` is only
the genuinely-nothing-found case; if the look already found some pieces, open higher. Show it once,
then refresh a line **only when that item's own status or evidence changes** (GUIDE.md sets the
refresh points) — do not re-render when no item's status or evidence changed. Keep it short and
warm, never a nag.

Each item is one blockquote line with a **blank `>` line between items**, so the three stay a
scannable board (adjacent blockquote lines otherwise collapse into one paragraph). Say everything
in **plain, warm words** — never a file path, a function signature, or an internal term.

- **Green** on concrete evidence — never a bare `✅ ready`. Name the evidence in plain words
  (*"your answer function"*, *"your 20 checked examples"*, *"the rule that checks each answer"*).
- **Red** when the piece isn't in hand yet — two honest forms, and neither asserts a piece is
  *missing* when the first look may simply not have reached it:
  - **not found yet** — you haven't located it. Give the why-it-matters and the approved link.
  - **needs one fix** — the piece exists but a later check found a problem (a dataset that
    doesn't line up with the agent, a rule that scores a right answer wrong). Say it needs one
    fix, keep the why-it-matters and the approved link, and decrement the heading.

Initial all-red form (only when the first look found nothing):

> **First-run readiness: 0/3 ready — three small pieces unlock your first run.**
>
> ❗ **Agent — not found yet.** Why it matters: Traigent needs your agent's answer function so it can improve it. [Wire your agent](https://github.com/Traigent/traigent-skills/tree/main/skills/traigent-setup-decorator).
>
> ❗ **Dataset — not found yet.** Why it matters: example inputs and the answers you expect give Traigent something real to measure against. [Prepare a dataset](https://github.com/Traigent/traigent-skills/tree/main/skills/traigent-dataset-curate).
>
> ❗ **Evaluation — not found yet.** Why it matters: a rule that checks whether an answer is right is how we tell if a change actually helped. [Build an evaluation rule](https://github.com/Traigent/traigent-skills/tree/main/skills/traigent-eval-build) or [choose a metric](https://github.com/Traigent/traigent-skills/tree/main/skills/traigent-eval-choose-metric).

Green lines name the evidence in plain words — for example:

> ✅ **Agent — ready:** your answer function.
>
> ✅ **Dataset — ready:** your 20 checked examples.
>
> ✅ **Evaluation — ready:** the rule that checks whether an answer is right.

Update the heading to match, and make **every rung reachable** by refreshing per item as each one
lands:

- `0/3 ready — three small pieces unlock your first run.`
- `1/3 ready — you're underway; two pieces to go.`
- `2/3 ready — one piece from your first run.`
- `3/3 in hand — next I'll wire it up and run a free check.`

**Never put a preflight check ID (C7/C8/C9) or any internal scaffolding term in the board copy.**
The check-to-item mapping is assistant-facing reconcile guidance only: **Dataset → C7
(dataset-shape) + C8 (dataset-binding); Evaluation → C9 (scorer-sanity)**. A board line may say a
piece is **verified by the free check** — but *only* once a **fully parameterized** preflight
(`--dataset --agent --scorer --good --bad --expected`, plus `--metadata` when the scorer uses
metadata) has actually returned **PASS** for that
piece's checks. An env-only, SKIP, or WARN result never counts as passed; before that, keep the
plain green wording with no verification claim.

**Reopen rule.** Any later readiness-affecting failure turns that item red again in the *needs one
fix* form and decrements the heading: a C7/C8 FAIL — or a dataset-binding / degenerate-reference
repair — reopens Dataset; a C9 FAIL or the Step 8 semantic-equivalence probe failing reopens
Evaluation.

**Demo-ready is about the material's provenance, not who typed the glue.** If the *material* — the
agent's logic, the dataset's contents, or the evaluation rule's logic (a synthetic scorer is
synthetic material) — was invented to demonstrate the workflow, that piece is `✅ demo-ready`, not
`✅ ready`. Wiring a decorator around the user's *real* agent stays real
(that's glue, not invented material). When the score depends on synthetic material, mark the
heading with explicit copy — for a mix, say which, placing the real/demo count before the wire-up
clause (e.g. `3/3 in hand — 2 real, 1 demo — next I'll wire it up and run a free check.`) — and say
once: "This proves the workflow can run; it is not a verdict on your real agent or data."

## The step spine (0–12; see GUIDE.md for each)

0. Greet: explain their small job; you do the rest. 1. Confirm Python 3.11–3.13. 2. Install
`traigent[recommended]>=0.21` in a venv; verify (free mock, no keys); run `preflight.py`.
3. Set up **one LLM vendor key** in `.env` (defer the free Traigent `uk_` key to Step 9).
4. Find the Python agent to optimize (or offer a clearly-labeled example). 5. Get a dataset +
an evaluation method; **reserve a holdout**. 6. Wire `@traigent.optimize`. 7. Choose the knobs
(ask the service via `traigent recommend`; don't hardcode). 8. **Free mock dry-run** in a
throwaway process. 9. Run baseline (local) then enhanced (portal) — the **only** step that needs
the Traigent key. 10. Show the portal link(s). 11. Second enhanced pass; diagnose "no
improvement" honestly. 12. Summarize plainly; gate on the holdout before any promotion.

## Non-negotiable gates (these protect money and truth — never skip)

1. **Free mock dry-run first, and in a SEPARATE, throwaway Python process.**
   `enable_mock_mode_for_quickstart()` has no undo — if the dry-run shares a process with the
   real run, every "real" trial is silently mocked and **fabricated numbers sync to the portal as
   genuine**. Set `TRAIGENT_OFFLINE_MODE=true` for the dry-run too (mock stops LLM cost, not
   backend egress). Mock numbers are plumbing checks, never results — never show them as accuracy.
2. **Human "yes" before any spend — you enforce it, not the SDK.** The SDK cost gate is
   *conditional* (it only hard-stops when the estimate exceeds the cap or the model is unpriced; a
   priced run under the cap proceeds on a mere warning). Estimate `max_trials × dataset_size ×
   calls-per-item`, show the user the number and the $5 cap, and proceed only on their explicit
   yes. The **$5 cap is per run**; the recommended "Both" path is up to **three** paid runs
   (baseline, enhanced, baseline-on-portal) plus Step 11 — show the **combined** worst-case, not
   just the next run. After approval, set `TRAIGENT_COST_APPROVED=true` **in the process env for
   that one launch only — never persist it in `.env`** (a persisted `true` silently disables the
   money prompt for every future run).
3. **Verify the run was real before reporting anything** (baseline and enhanced):
   `results.total_cost` is a positive number (`None`/≈0 ⇒ secretly mock/offline or unpriced —
   do **not** show it); per-trial outputs vary; trial count matches budget; no
   `finish_reason == "length"` truncation; and `results.cloud_url is not None` before promising a
   portal link (a `None` means it stayed local-only).
4. **Secrets only in `.env`, never in chat.** You pop `.env` open; the user only pastes. Never
   echo or read a key back. State which line by prefix: the LLM key (e.g. OpenRouter
   `sk-or-v1-…`) goes in its vendor line; leave `TRAIGENT_API_KEY=` (a `uk_…` key) blank until
   Step 9.
5. **Honest results only.** Never a strawman baseline, never mock-numbers-as-results, never a
   dressed-up zero delta. If *you* generated the agent and/or the dataset, tell the user plainly
   — before the run — that it demonstrates the flow, not yet a verdict on a real system.

## Beginner pitfalls

Before a run stalls, confuses the user, or spends unexpectedly, consult
[`references/beginner-pitfalls.md`](references/beginner-pitfalls.md) — a distilled map of the
traps a first-timer hits (per-run vs total cost, mock leakage, free-tier quota, the `.env`
handoff on headless boxes, Windows venv activation, synthetic-everything runs, "Baseline only"
leaves nothing in the portal) and the one-line coverage for each. Load it at Steps 2–3, 8–9, or
11–12, or whenever the user seems unsure.

## Guardrails

- Traigent optimizes **Python** callables only — if the agent isn't Python, stop and offer a
  labeled Python demo or a wrapper (with its money caveat), don't force it.
- Only `auto` (or `grid`/`random`) reliably execute across SDK builds; `auto` already runs the
  cloud smart optimizer, so never "upgrade" it to a named selector (`bayesian`/`tpe`/…) — they
  offer no advantage and their executability varies by build.
- Everything you generate goes under `traigent-runs/` at the project root (git-ignored) — never
  beside the user's originals, where their tooling might ingest it.

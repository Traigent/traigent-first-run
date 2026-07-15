# Beginner pitfalls — traps a first-timer hits, and the one-line coverage

A distilled map from field-testing the first-run flow with non-expert users. Each entry: the
trap, why a *beginner specifically* trips, and what you (the assistant) do to cover it. The full
reasoning lives in `GUIDE.md`; this is the fast lookup. Load it at Steps 2–3, 8–9, 11–12.

## Contents
1. Money — "$5 cap" is per run, not total
2. Money — `TRAIGENT_COST_APPROVED` must never be persisted
3. Truth — synthetic-everything runs read as a real verdict
4. Truth — mock leaking into the paid run
5. Blocks-run — free-tier optimization-sample quota
6. Handoff — the `.env` paste on headless / cloud IDEs, and key swaps
7. Blocks-run — Windows venv activation
8. Truth — tiny datasets are a smoke test, not a score
9. Confusion — the Traigent key is required *later*, not now
10. Expectation — "Baseline only" leaves nothing in the portal

---

## 1. Money — the "$5 cap" is per run, not total
A nervous beginner reads "capped at $5" as their whole ceiling, but the recommended **"Both"**
path is several small paid runs (local baseline, enhanced, baseline-on-portal, plus any Step 11
pass), each separately capped — so the total exceeds $5 (usually only a few dollars, since the
baseline grids are deliberately cheap; more only if every run hit its cap).
**Cover:** before the first paid launch, show the **combined worst-case across every run you
plan** — see GUIDE Step 9's cost gate for the exact framing — not just the next run's estimate.

## 2. Money — `TRAIGENT_COST_APPROVED` must live in the process env, never `.env`
After the user approves, you set `TRAIGENT_COST_APPROVED=true`. If you write it into `.env`, it
**persists** and silently disables the money prompt for every future run — a beginner will never
notice "approve once" became "approve never."
**Cover:** set it in `os.environ` for that one launch only; never persist it in `.env`. If it
ever lands in `.env`, comment it back out immediately after the run.

## 3. Truth — a from-scratch run can be synthetic agent + synthetic data + synthetic scorer
When the user "has nothing," you may generate the agent (Step 4), the dataset (Step 5), and the
eval (Step 5). The Pareto frontier then looks identical to a real result, but a non-expert can't
tell "a measurement of my agent" from "a demo of the flow on synthetic everything."
**Cover:** say it up front, *before* the run — *"Since we're building the example agent and its
test set together, this first run shows you how Traigent works, not a verdict on a real system
yet — bring your own agent or examples when you're ready for that."* Don't bury it in Step 12.

## 4. Truth — mock mode leaking into the paid run
`enable_mock_mode_for_quickstart()` has no undo; if the dry-run and the real run share one Python
process, every "real" trial is silently mocked and **fabricated numbers sync to the portal as
genuine** — the mocked run still "passes" and prints a plausible table.
**Cover:** run the dry-run in a **separate, throwaway** process that exits. As a hard backstop,
treat `results.total_cost` being `None`/≈0 on a supposedly-paid run as a **STOP — do not show the
user**: start a fresh interpreter with `TRAIGENT_MOCK_LLM`/`TRAIGENT_OFFLINE_MODE` unset. If you
cannot guarantee a fresh interpreter, refuse the paid run rather than risk mocked numbers.

## 5. Blocks-run — the free-tier optimization-sample quota
A brand-new free Traigent account has a small monthly `optimization_samples` allowance. An
enhanced run reserves ≈`max_trials × dataset_size` samples and can be throttled or rejected
mid-run — which a beginner reads as "the tool is broken."
**Cover:** before the enhanced launch, tell the user the run reserves ≈`max_trials ×
dataset_size` samples and a new free account is limited; if it's rejected or stalls with a quota
message, shrink `max_trials` or the dataset — don't retry blindly.

## 6. Handoff — the `.env` paste on headless boxes, and key swaps
Step 3 pops `.env` open with `xdg-open`/`open`/`notepad`. On a headless remote box or cloud IDE
there's no display, and a beginner faced with two blank look-alike `KEY=` lines can paste the LLM
key into `TRAIGENT_API_KEY=` (or vice-versa).
**Cover:** always print the file's **absolute path** as a fallback, and name the target line by
**key prefix**: *"Paste your OpenRouter key (starts `sk-or-v1-`) after `OPENROUTER_API_KEY=`;
leave `TRAIGENT_API_KEY=` (a `uk_…` key) empty for now."* `preflight.py`'s key-shape check
backstops a swap — run it after they paste.

## 7. Blocks-run — Windows venv activation
Step 2 shows the Windows *create* command but a beginner "shaky on venvs" also needs the
*activate* command, or `pip install` silently hits global Python.
**Cover:** `.venv\Scripts\activate` (PowerShell: `.venv\Scripts\Activate.ps1`; a blocked policy
may need `Set-ExecutionPolicy -Scope Process RemoteSigned` once). Confirm the interpreter is
inside `.venv` (`python -c "import sys; print(sys.prefix)"`) before installing.

## 8. Truth — a tiny dataset is a smoke test, not a score
With only a handful of examples, a beginner can't tell a real win from noise (±5–10 pts of
wobble at temperature > 0), and the honest verdict "promising — needs more items" reads as
failure.
**Cover:** at Step 12, if the set is small, say plainly: *"With only N examples, this run is a
smoke test of the setup, not a trustworthy score — the honest next move is more examples, and I
can help build them."*

## 9. Confusion — the Traigent key is required *later*, not now
Treating the Traigent platform key as up-front-required front-loads the portal signup the flow
deliberately defers — a beginner goes hunting for it before they've seen any value.
**Cover:** the key is **required *later*** — leave `TRAIGENT_API_KEY=` blank until the portal run
(Step 9); everything up to it runs on the LLM vendor key alone.

## 10. Expectation — "Baseline only" leaves nothing in the portal
A money-cautious beginner who picks "Baseline only" never gets a Traigent key and never sees a
portal run — forfeiting the very deliverable ("a run you can see in the portal") they were
promised, then feeling the process failed.
**Cover:** when they lean toward "Baseline only," say up front: *"That gives you a local
before-number but nothing in the portal — the portal view needs the enhanced run. Want just the
local baseline, or Both so you get the online before/after?"*

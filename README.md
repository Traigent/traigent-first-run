# Traigent — First Run

**Optimize your AI agent in one sitting, guided by your own coding assistant.**

You don't run any technical steps yourself. You point your coding assistant
(Claude Code, Cursor, Codex, Gemini CLI, …) at this repo, and it walks you through
installing Traigent, wiring it to *your* agent, and producing a real optimization
run you can see in the [Traigent portal](https://portal.traigent.ai/) — your best
accuracy for the least cost (the **Pareto frontier**), plus a suggestion of what to
try next. If it turns out your agent is already near-best, the guide says so honestly
rather than inventing an improvement.

---

## How to use it — one step

Paste this to your coding assistant (Claude Code, Cursor, Codex, Gemini CLI, …):

```text
Help me run my first Traigent optimization on my agent.
Clone https://github.com/Traigent/traigent-first-run and follow its GUIDE.md
step by step. Use your most capable model.
```

That's it. The assistant clones this repo, reads the guide, and walks you through the
rest — asking you only the few things it genuinely needs. You won't have to run
terminal commands yourself, and you never paste a secret into the chat.

**Already have the repo open in your assistant?** Just say: *"Follow GUIDE.md in this
repo, step by step."* (Assistants that auto-read `AGENTS.md` / `CLAUDE.md` pick it up
on their own.) **Can't run `git`?** Paste your assistant the GUIDE.md link (or its
contents) and say "follow it step by step."

---

## What you'll need (the assistant checks these for you)

- **Python 3.11–3.13** — the assistant detects or installs it; you don't have to.
- **A Traigent key** — sign up at <https://portal.traigent.ai/register>, create an
  API key with **Full access** (it begins with `uk_` or `tg_`). This lets the run create
  your experiment and read its results back. The key lives only in your git-ignored `.env`
  (never in the chat), is used only to sync configuration choices and scores, and you can
  revoke it anytime from the portal.
- **One LLM key with a few dollars on it** — **OpenRouter is recommended** (one key,
  many low-cost/open-source models): get a key at <https://openrouter.ai/keys> and add a
  few dollars of credit at <https://openrouter.ai/credits>. OpenAI / Anthropic / Gemini /
  Mistral / Cohere / Bedrock keys work too (plus others like HuggingFace — see GUIDE.md for the
  full vendor list). Spend is **capped at $5 per run** (the value this repo's
  `.env` sets — the SDK's own default is $2), and the assistant always does a **free
  dry-run first** and asks before any paid run.

You'll paste your keys into a `.env` file (template: [`.env.example`](.env.example))
— never into the chat.

## Your privacy

During a run, only **configuration choices and numeric scores** reach Traigent — your data,
prompts, outputs, code, and keys stay on your machine. (Your assistant encodes any prompt
variations as short labels, so as long as it follows the guide your actual prompt text
stays on your machine.) The one exception is the *optional* `traigent plan` command, which
sends only a short task description you write yourself — never your code or data.

---

## What's in here

| Path | What it is |
|---|---|
| [`GUIDE.md`](GUIDE.md) | The step-by-step guide your assistant follows |
| [`.env.example`](.env.example) | Template for your keys + run settings (copy to `.env`) |
| [`templates/run-plan.md`](templates/run-plan.md) | Record one of these per optimization run |

## After your first run

When you're ready to push further, the full set of Traigent optimization skills
lives at <https://github.com/Traigent/traigent-skills>.

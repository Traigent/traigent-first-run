# Traigent — First Run

**Optimize your AI agent in one sitting, guided by your own coding assistant.**

You don't run any technical steps yourself. You point your coding assistant
(Claude Code, Cursor, Codex, Gemini CLI, …) at this repo, and it walks you through
installing Traigent, wiring it to *your* agent, and producing a real optimization
run you can see in the [Traigent portal](https://portal.traigent.ai/) — your best
accuracy for the least cost (the **Pareto frontier**), plus a suggestion of what to
try next.

---

## How to use this repo

1. **Clone it** somewhere on your machine:
   ```bash
   git clone https://github.com/Traigent/traigent-first-run.git
   ```
2. **Tell your coding assistant** (in its chat, with the repo open):

   > Follow the guide in this repo — read **GUIDE.md** and walk me through it step
   > by step. Use your most capable model.

That's it. The assistant does the technical work and asks you only the few things
it genuinely needs. (Most assistants also auto-read `AGENTS.md` / `CLAUDE.md`, which
point at the same guide.)

---

## What you'll need (the assistant checks these for you)

- **Python 3.11–3.13** — the assistant detects or installs it; you don't have to.
- **A Traigent key** — sign up at <https://portal.traigent.ai/register>, create an
  API key with **Full access** (it begins with `uk_` or `tg_`).
- **One LLM key with a few dollars on it** — **OpenRouter is recommended** (one key,
  many low-cost/open-source models). OpenAI / Anthropic / Gemini / Mistral / Cohere
  / Bedrock keys work too. Spend is **capped at $5 per run** (the value this repo's
  `.env` sets — the SDK's own default is $2), and the assistant always does a **free
  dry-run first** and asks before any paid run.

You'll paste your keys into a `.env` file (template: [`.env.example`](.env.example))
— never into the chat.

## Your privacy

Only **configuration choices and numeric scores** ever reach Traigent — never your
data, prompts, outputs, code, or keys. Everything sensitive stays on your machine.

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

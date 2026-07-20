# Traigent - First Run

Run a guided Traigent optimization in one sitting, from whatever your project has today.

Your coding assistant inspects the project, preserves any real agent, dataset, and evaluation
method it finds, and prepares only the missing pieces. If Traigent generates temporary walkthrough
material, it remains clearly marked so a demonstration is never mistaken for production evidence.

## Start with one prompt

Paste this into Claude Code, Cursor, Codex, Gemini CLI, or another coding assistant:

```text
Help me run my first Traigent optimization.
Clone https://github.com/Traigent/traigent-first-run and follow GUIDE.md.
```

The assistant performs the technical work and asks only when it needs:

- A choice that materially changes the task.
- A key pasted into a local, git-ignored `.env` file.
- Approval before paid model calls or private-data egress.

No existing agent, dataset, or evaluator is required to see the walkthrough. When one is missing,
Traigent generates a coherent substitute around everything that already exists.

## Install as an Agent Skill

The complete guide, references, scripts, and run-plan asset are packaged together:

```bash
npx skills add Traigent/traigent-first-run
```

Then ask:

```text
Use $traigent-first-run to run my first Traigent optimization.
```

Node.js is needed only for this optional installation command, not for the Traigent Python run.

## What the run does

1. Inspects the project and reports real-world readiness.
2. Creates only missing agent/dataset/evaluation components as temporary walkthrough substitutes.
3. Validates compatibility and evaluator discrimination.
4. Shows one combined time, cost, and data-egress approval.
5. Evaluates the current configuration, then runs one bounded optimization.
6. Reports the result, limitations, artifacts, and verified portal links.

The default comparison is two optimization experiments - one honest current-configuration
baseline and one optimization - followed by an untouched holdout check. A second optimization
pass is optional, not required.

## Requirements

- Python 3.11-3.13 in an isolated environment.
- One supported LLM-provider key with a small amount of credit for the real run.
- A Traigent portal key for connected optimization and portal results.

Your assistant creates a minimal `.env` for the chosen provider and asks you to paste keys there.
Never paste secrets into chat.

## Privacy

Traigent receives configuration identifiers, numeric measures, and run status needed for connected
optimization and portal history. It does not need the agent's prompts, examples, or outputs.

The selected LLM provider still receives the content the agent normally sends during model calls.
Your assistant explains which services receive data and asks before paid calls or private-data
egress.

## Repository layout

| Path | Purpose |
|---|---|
| [`GUIDE.md`](GUIDE.md) | Entry point for a cloned-repository run |
| [`skills/traigent-first-run/`](skills/traigent-first-run/) | Self-contained installable skill |
| [`.env.example`](.env.example) | Reference environment settings |
| [`reports/`](reports/) | Field-test evidence that informed the safeguards |

After the first result, the assistant can offer the advanced
[Traigent optimization skills](https://github.com/Traigent/traigent-skills) as optional next steps.

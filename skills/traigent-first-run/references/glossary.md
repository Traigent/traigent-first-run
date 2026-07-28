# Glossary - shared vocabulary for talking with the user

Canonical definitions for the coding agent to use when explaining a concept to
the user or phrasing a confirmation question during a first run. Load this on
demand at those moments; it is a communication reference, not a stage of the
run. Decision rules (when to ask, when to proceed, what needs approval) are
owned by `SKILL.md` and its authorization table - this file only fixes what the
words mean and how to say them.

## How to use this vocabulary

- Define a term the first time it appears in the conversation, in one plain
  sentence, then use it consistently. Do not switch synonyms mid-run (pick
  "evaluator", not sometimes "scorer", sometimes "judge", sometimes "grader").
- Prefer the "plain" wording with the user; keep the "precise" wording for your
  own reasoning and for the report.
- Never assume the user knows an acronym. Expand it once
  (RAG = retrieval-augmented generation).
- When a term maps to a decision the user must make, use the "ask like this"
  line rather than inventing your own phrasing.

## Calibrating depth

Do not ask the user how experienced they are, and never classify or announce
their expertise level (see the operating contract in `SKILL.md`). Calibrate
from evidence instead:

- What inspection found: a project with a real evaluator, dataset splits, or an
  eval harness needs terse definitions or none; a project with none of these
  usually needs the plain wording and one-sentence definitions throughout.
- How the user talks: if they say "holdout", "F1", or "LLM-as-judge"
  unprompted, stop defining those terms. If they ask what a term means - or
  why it matters ("why should I care about a dataset?") - take that as the
  signal to explain more from here on: answer with the plain wording plus the
  one-sentence reason the concept affects their result, and keep that fuller
  register for the rest of the run.
- Default when there is no signal yet: one plain sentence at first use, then
  move on. That costs an experienced reader nothing and quietly carries
  everyone else.
- Depth on request only: answer a "what does that mean?" with the plain and,
  if asked further, the precise wording. Do not front-load teaching material,
  and do not link educational resources during the active run (an operating-
  contract rule in `SKILL.md`; it owns that decision).

## Core terms

Agent
  Plain: the AI program we are trying to make better - it takes an input and
  produces an answer.
  Precise: the model plus all the code, prompts, retrieval and tools around it
  that together turn an input into an output.

Coding agent ("your agent" in conversation)
  Plain: the assistant running in your editor or terminal (Claude Code, Codex,
  Gemini CLI, etc.) that is doing this setup with you.
  Note: keep this distinct from "agent" above. The coding agent builds and
  optimizes the agent. Say "your coding agent" when there is any risk of
  confusion.

Dataset (evaluation dataset, sometimes "benchmark")
  Plain: the set of example questions we use to measure how good the agent is.
  Precise: a collection of rows, each ideally an input paired with the expected
  output, split into a part used to tune and a part held back to check.
  Ask like this: "Do you have a set of example inputs - and ideally the correct
  answers for them - we can measure the agent against?"

Example / row / datapoint
  Plain: one test item: an input, and (ideally) the answer it should produce.

Expected output (label, "gold" answer, ground truth)
  Plain: the correct answer for an example - what we compare the agent against.
  Precise: the reference the evaluator scores the agent's output against.
  Ask like this: "For these inputs, do you have the correct answers, or just the
  inputs?"

Labeled vs unlabeled
  Plain: labeled means each input has its correct answer attached; unlabeled
  means we only have the inputs (for example, raw logs).

Evaluator (evaluation method, scorer)
  Plain: the rule or program that decides whether an answer is right, and how
  right.
  Precise: the function that maps (agent output, expected output) to a score.
  Kinds: exact match, execution match (run the SQL/code and compare results),
  unit tests, overlap metrics (F1), or an LLM-as-judge that reads a rubric.
  Ask like this: "How do you (or should we) decide whether an answer is correct?"

Evaluation (grading)
  Plain: the act of running the agent on the dataset and scoring every answer.

Calibration (of the evaluator)
  Plain: checking that the evaluator gives a high score to good answers and a
  low score to bad ones - that the ruler actually measures the right thing.
  Note: an evaluator that passes everything, or one that gives a wrong answer a
  good score, is broken even if it is fast and repeatable.

Accuracy (quality)
  Plain: the share of answers the evaluator judges correct - the agent's grade.
  Note: accuracy is only as trustworthy as the evaluator behind it.

Dimension / knob
  Plain: one thing about the agent we can change and try different values for -
  for example the model, the temperature, the prompt, or how many examples we
  show it.
  Precise: a tunable variable in the agent's configuration.
  Common knobs: model choice, temperature, retrieval / RAG settings, prompt
  wording, output format, number of few-shot examples, reasoning style, and
  multi-model routing or cascading.
  Ask like this only when `SKILL.md` authorizes a question about the tunable
  surface (knob selection itself is made from inspection, not by asking):
  "Besides the model, what else can we change in your agent - the prompt,
  retrieval, output format, examples?"

Configuration (config, variant)
  Plain: one specific combination of knob values - one candidate version of the
  agent.

Optimization (optimization run)
  Plain: the search where we try many configurations and find the ones that get
  the best accuracy for the lowest cost and latency.
  Precise: a guided search over the configuration space, scored on the dataset
  by the evaluator, that returns the best non-dominated candidates.

Baseline run vs enhanced run
  Plain: the baseline measures your current configuration (or a small standard
  sweep when Traigent had to generate one); the enhanced run is the broader,
  cloud-assisted search that looks for better configurations.

Tuning split vs holdout (validation) split
  Plain: the tuning part is what we optimize against; the holdout is kept aside
  and only used at the end to check we did not just memorize the tuning part.
  Note: if the same examples appear in both, the result is optimistic and cannot
  be trusted (this is "leakage"). When Traigent generates walkthrough data, the
  default is 24 rows split 18 tuning / 6 holdout.

Provenance
  Plain: where the data came from - real production data, real inputs with
  answers we generated, or fully made-up (synthetic) data.
  Note: synthetic data is fine for a first run but cannot prove real-world
  readiness on its own.

Difficulty spread
  Plain: whether the dataset has a mix of easy, medium, hard and very hard items
  rather than all one level.

Pareto frontier (optimal frontier)
  Plain: the set of best trade-offs - each one is a config where you cannot get
  more accuracy without paying more cost or latency.

Readiness score (the card, the three pillars, bands, caps, blocked)
  Plain: a quick first-pass estimate, from 0 to 100, of how ready your setup is
  to be optimized, broken into three parts: your dataset, your evaluator, and
  your agent's knobs.
  It is computed at the start of every run - before anything is created or
  repaired - and again after each repair or creation, so the closing report can
  show an honest opening-to-closing change. It decides what the run does next:
  repair, create, or continue as a clearly labeled walkthrough. A low number
  alone does not stop a safe walkthrough, but a cap that says the grading signal
  is broken does stop paid optimization against that signal.
  Bands: Not ready (0-29), Partial (30-54), Workable (55-74), Strong (75-89),
  Excellent (90-100).
  Cap: a rule that holds the score down when something essential is missing or
  broken (for example a broken evaluator), so a high average cannot hide it.
  Blocked: the flag the card shows whenever at least one cap fired - it names
  the specific broken thing even when the rest looks good.

.env file
  Plain: a small text file in your project that holds settings and secrets -
  most importantly your keys - so the tools can run. It stays on your machine
  and should not be shared or committed to git.

Provider key vs Traigent portal key
  Plain: two different keys live in your `.env`. The provider key (OpenAI,
  Anthropic, OpenRouter, ...) pays for the model calls your agent makes. The
  Traigent portal key (it starts with `uk_`) connects the run to your Traigent
  account so the experiments and results appear in the portal.
  Ask like this: "Two keys go into your local .env - your model provider's key
  and your Traigent portal key. Paste them into the file directly, not into
  chat."

Portal
  Plain: the Traigent website where you register, generate your Traigent
  portal key (listed there under "API keys"), and view your optimization runs
  and their results.

Traigent SDK
  Plain: the library your coding agent uses to wrap your agent and run
  optimizations.

Traigent Skills
  Plain: installable instructions that teach your coding agent the full,
  advanced Traigent workflow beyond the first run.
  Note: per `SKILL.md`, offer these only after the user has seen their first
  result - never mid-run.

## Ambiguity

When the user's setup is ambiguous, do not guess silently and do not invent an
ask/proceed rule from this file: the authorization table in `SKILL.md` owns
those decisions. What this file adds is only the phrasing - when those rules
say to ask, ask in the plain wording above, and when they say to proceed with a
generated substitute, say so in one sentence and mark it `🛠️`.

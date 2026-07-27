# Traigent Onboarding Glossary

Canonical, unambiguous definitions for the customer's coding agent to use when explaining concepts to a user (or asking the user to confirm a choice) during a Traigent first run. Keep wording consistent with these.

===============================================================================

Purpose. During onboarding the customer's coding agent has to explain concepts
to a user who may be new to evaluation and optimization, and sometimes ask the
user to confirm a choice. If the words are used loosely, the user gets confused
or agrees to the wrong thing. This glossary is the single source of truth for
what each term means and how to say it.

HOW THE CODING AGENT SHOULD USE THIS
- Define a term the first time it appears in the conversation, in one plain
  sentence, then use it consistently. Do not switch synonyms mid-run (pick
  "evaluator", not sometimes "scorer", sometimes "judge", sometimes "grader").
- Prefer the "plain" wording with the user; keep the "precise" wording for your
  own reasoning and for the report.
- Never assume the user knows an acronym. Expand it once (BE = backend).
- When a term maps to a decision the user must make, use the "ask like this"
  line rather than inventing your own phrasing.
- If the user's setup is ambiguous, resolve it with the rule in the last section
  ("When to ask vs. when to proceed") - do not guess silently.

CORE TERMS

Agent
  Plain: the AI program we are trying to make better - it takes an input and
  produces an answer.
  Precise: the model plus all the code, prompts, retrieval and tools around it
  that together turn an input into an output.

Coding agent (the C-Agent, "your agent")
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
  Ask like this: "Besides the model, what else can we change in your agent -
  the prompt, retrieval, output format, examples?"

Configuration (config, variant)
  Plain: one specific combination of knob values - one candidate version of the
  agent.

Optimization (optimization run)
  Plain: the search where we try many configurations and find the ones that get
  the best accuracy for the lowest cost and latency.
  Precise: a guided search over the configuration space, scored on the dataset
  by the evaluator, that returns the best non-dominated candidates.

Baseline run vs enhanced run
  Plain: the baseline is a small first search you run locally to see it work;
  the enhanced run is the fuller, cloud-assisted search that finds better agents.

Tuning split vs holdout (validation) split
  Plain: the tuning part is what we optimize against; the holdout is kept aside
  and only used at the end to check we did not just memorize the tuning part.
  Note: if the same examples appear in both, the result is optimistic and cannot
  be trusted (this is "leakage").

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
  your agent's knobs. It shapes what we explain and what we fix; it never stops
  the run.
  Bands: Not ready (0-29), Partial (30-54), Workable (55-74), Strong (75-89),
  Excellent (90-100).
  Blocked: a separate flag meaning one specific thing is broken (for example a
  broken evaluator) even if the rest is good.
  Cap: a rule that holds the score down when something essential is missing or
  broken, so a high average cannot hide it.

.env file
  Plain: a small text file in your project that holds settings and secrets -
  most importantly your Traigent API key - so the tools can run. It stays on
  your machine and should not be shared or committed to git.

API key / access token
  Plain: your personal key that lets the tools talk to Traigent's cloud. The
  onboarding key is time-limited (about 10 days) and one per account.

Portal (backend, BE, the cloud)
  Plain: the Traigent website where you register, generate your API key, and
  view your optimization runs and their results.

Traigent SDK
  Plain: the library your coding agent uses to wrap your agent and run
  optimizations.

Traigent Skills (traigent-skills / agents-skills)
  Plain: the installable instructions that teach your coding agent how to do the
  full, advanced Traigent workflow - the "enhanced" capabilities beyond the first
  run.

Quality gate
  Plain: a pass/fail check on whether the agent is good enough to ship.

Trusted agent
  Plain: an agent that has been measured, improved and validated on held-back
  data - one you can ship with evidence, not hope.

WHEN TO ASK THE USER vs. WHEN TO PROCEED (ambiguity rules)
- Inputs but no expected outputs: proceed - synthesize expected outputs so the
  first run can happen, but tell the user you did, and at the end ask them to
  review the synthesized answers. Do not ask them to hand-write answers up front
  (that kills "seamless").
- No dataset at all: proceed - synthesize a small seeded set (about 18 items,
  easy to very hard) on the agent's subject; tell the user it is synthetic.
- More than ~100 items: proceed on a seeded random subset of about 18, chosen to
  span easy / medium / hard / very hard, and print the seed so it reproduces.
- No evaluator: proceed - propose an evaluator that fits the output type
  (execution/unit-test for code and SQL, exact match for short factual answers,
  a calibrated judge for free text) and say which you chose and why.
- Evaluator looks broken (passes everything, or scores a wrong answer as right):
  do not silently proceed on it - tell the user it cannot be trusted and propose
  a replacement.
- Anything that changes cost, downloads code, or edits their files: ask for a
  one-click confirmation first, in plain language.

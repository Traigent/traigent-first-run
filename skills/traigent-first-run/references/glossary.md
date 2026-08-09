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
  sweep when the assistant had to prepare one); the enhanced run is the broader,
  cloud-assisted search that looks for better configurations.

Tuning set vs held-out set
  Plain: the tuning set is what we optimize against; the held-out set is kept
  aside and used at the end to check we did not just memorize the tuning rows.
  Note: if the same examples appear in both, the result is optimistic and cannot
  be trusted (this is "leakage"). Call a held-out set a sealed holdout only if its
  split and labels were hidden until the candidate was locked; an assistant-inspected
  or assistant-authored one is held-back and non-blind. When the assistant
  prepares walkthrough data, the default is 28 rows split 18 tuning / 10 held-out,
  reserved at creation; `references/evaluation-and-dataset.md` owns the bands and
  the rest. The held-out score is disclosed once, beside the
  tuning score, in the closing report after the enhanced run - not at the earlier
  baseline checkpoint.
  Say what ten kept-back rows can and cannot do: they can catch a configuration
  that only worked on the rows it was picked on; they cannot measure how much
  better one configuration is than another.

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

The lines under each pillar on the card
  Plain: each line is one question the score asked about your setup, with what
  it found. They are the things a first run can check for free, on your own
  machine, before anything is paid for.
  Dataset:
    answers to score against   - how many rows carry an expected answer at all.
                                 A row without one cannot say whether a
                                 configuration got it right.
    examples to compare on     - how many rows the two runs can actually be
                                 compared on. More examples add evidence, but
                                 this pre-run count alone cannot calculate paired
                                 uncertainty or prove a difference is real.
    range of difficulty        - whether the rows span easy to hard. If every
                                 row is easy, every configuration looks equally
                                 good.
    repeated or dominant answers - whether the same input or the same expected
                                 answer keeps recurring, which lets a lazy
                                 configuration score well by guessing it. Rows
                                 repeat when 90% or more of their words match,
                                 identical rows included; charged once. 90% is
                                 a chosen line, not a discovered one - 89%
                                 alike is below it, not thereby far apart.
    where the rows came from   - whether the data was collected or written by a
                                 model. Both are usable; only one is evidence
                                 about production.
  Evaluation:
    right kind of check for this output - whether the grading method suits the
                                 kind of answer your agent produces.
    same answer every time     - whether re-grading the same output gives the
                                 same score. An evaluator that drifts makes
                                 every comparison noisier.
    checked on known-good and known-bad - whether the evaluator was tried
                                 against answers already known to be right and
                                 wrong. Until it is, nothing establishes it can
                                 tell them apart.
    separates good answers from bad - how far apart it scored those known-good
                                 and known-bad answers. A narrow gap means the
                                 grade barely reflects quality.
  Agent:
    how many settings-combinations there are to try - the size of the search
                                 space: every combination of the values you
                                 listed, counted against how many the run has
                                 budget to try. Values too close to tell apart
                                 count once, so ten settings with one value
                                 each is a space of one, not a space of ten.
  Words the evidence beside those lines uses:
    settings document          - the file listing which of your agent's settings
                                 the search may vary, and which of them the
                                 agent actually reads. The run writes one after
                                 a search completes; a file left by an earlier
                                 run is deliberately not counted, so an opening
                                 score always reports that none was provided
                                 yet rather than that your agent has none.
    tuning set / held-out set  - two parts of your examples, not equal halves:
                                 18 to tune on and 10 kept back, by default. The
                                 search is allowed to see the first part while it
                                 looks for a better configuration; the second is
                                 kept back so the final number is measured on
                                 examples the search never optimized against.
                                 Without it, a good score may only mean the
                                 search fitted the examples it could see. With
                                 ten of them, it can show a winner still works
                                 outside the rows it was chosen on and cannot
                                 measure by how much. It is
                                 the train/test idea, except nothing is trained:
                                 Traigent searches configurations rather than
                                 fitting a model. Say "tuning set" and "held-out
                                 set" to the user, and only that pair. The card's
                                 own line prints them as "to tune on / held back"
                                 and the guide's files name the second one the
                                 holdout; "validation" and "test set" are the
                                 reader's own words, borrowed only to bridge to
                                 them. Same rows either way, always created by
                                 default for generated data.
    good-vs-bad examples       - answers already known to be right and known to
                                 be wrong, run through your evaluator to see how
                                 far apart it scores them. Near 1.00 it
                                 separates quality cleanly; a narrow gap means
                                 any improvement the run reports could sit
                                 inside the evaluator's own noise. They come
                                 from calibration, later in the run.
    undeclared row             - a row that names no real source this run can
                                 read: no provenance field at all, a non-answer
                                 such as `n/a` that the card still prints as the
                                 source it read, or a word its vocabulary does
                                 not know. Scored as a generated row,
                                 because a source nothing can verify cannot be
                                 read as a claim that the row is real. The card
                                 always says so on the "where the rows came
                                 from" line. It also gives the score the same
                                 rows would earn declared as collected -
                                 whenever that is a different number. When
                                 something else holds the run down to the same
                                 score, the second number would repeat the
                                 first, so the card omits it rather than
                                 spending a line to say nothing changes.

  Why three lines are blank at the start, every time: two of them are
  "checked on known-good and known-bad" and "separates good answers from bad",
  which both come from calibrating the evaluator - that happens later in the
  run, so at the opening score they have not been done yet. The third is the
  whole Agent pillar. Every config-space file found before this run's search is
  omitted on every guided run, so no settings document ever reaches an opening
  score, and the pillar reports `1 of 3 checks measured` behind one shared line
  rather than naming "settings that vary", "how widely each setting varies" and
  "the settings that matter most" separately - one absent input is one finding,
  not three. All three blanks are reported as not measured rather than as zero,
  and none of them is something you were supposed to bring.

Readiness score (the card, the three pillars, bands, caps, blocked)
  Plain: a quick first-pass estimate, from 0 to 100, of how ready your setup is
  to be optimized, broken into three parts: your dataset, your evaluator, and
  your agent's knobs.
  It is computed at the start of every run - before anything is created or
  repaired - and again after each repair or creation, to check that what failed
  a gate now passes it before anything is paid for. Only the opening number is
  your project's score: a re-score after a repair mostly grades the substitutes
  this run wrote, so it is read for which caps cleared instead. The opening
  number is also what the closing recommendation is ranked from, for the same
  reason: a gap the run filled with a substitute of its own looks cleared
  afterwards whether or not your project changed.
  It decides what the run does next: repair, create, or continue as a clearly
  labeled walkthrough. A low number alone does not stop a safe walkthrough, but
  a blocking cap does stop paid optimization when the current components or
  evidence cannot support a trustworthy comparison. `agent-no-varying-knobs` is
  advisory whenever no settings document was provided - see that entry above for
  why one never is at the opening score - so it bounds the score at 45 and stops
  nothing.
  Bands: Not ready (0-29), Partial (30-54), Workable (55-74), Strong (75-89),
  Excellent (90-100).
  Cap: a ceiling on the whole score, so a high average cannot hide one bad part.
  Some caps block because something has to be created or repaired before a paid
  comparison is worth making - a broken evaluator, no dataset, no expected
  answers, nothing scoreable in the split the search would tune on. Others say
  only that generated data, or a comparison set too small to settle a close
  call, limits claim strength until real rows or completed paired outcomes
  support more. That limits what the result may claim without saying anything is
  wrong with your setup.
  Several can apply at once, and the score is the strictest of them together
  with the average - so a listed ceiling is not necessarily the one in force.
  The card marks the difference: "limited to" is the ceiling you are at, "would
  limit to" is one you have not reached: a stricter cap, or an average that has
  not climbed that high yet.
  Blocked: a `BLOCKER` line under the score, shown when a blocking cap fired. It
  does not mean every component is broken; it means one thing in the current
  state must be created or repaired before a paid comparison is worth making. A
  cap that only limits the claim does not set it, because the run is still worth
  making. Band and block answer different questions - the band grades the
  evidence, the block says whether the paid run may start - so a good band
  beside a block is no contradiction. The line says the score stands, names what
  clears first, and what follows. Never read it as the score disbelieved.

  Present it as progress: `Stage 2/5 · Readiness - <score>/100 (<band>)`. Explain what the score
  measures, the strongest evidence, the one limitation that most affects the next action, and that
  action. A re-score is a gate result: lead with the caps that cleared, never with a new score
  beside the opening one. Do not animate with invented progress or narrate every card line.

.env file
  Plain: a small text file in your project that holds settings and secrets -
  most importantly your keys - so the tools can run. It stays on your machine
  and should not be shared or committed to git.

Provider key vs Traigent portal key
  Plain: two different keys may ultimately live in your `.env`, at different
  gates. The provider key (OpenAI, Anthropic, OpenRouter, ...) pays for the local
  baseline's model calls. Only after that result, the Traigent portal key (it
  starts with `uk_`) connects the managed run to your Traigent account.
  Ask for the provider key before the local baseline. Ask for the Traigent key
  only after the baseline checkpoint. Each is pasted into the file directly,
  never into chat.

Portal
  Plain: the Traigent portal site where your account lives - it generates your
  Traigent portal key (listed there under "API keys") and shows your
  optimization runs and their results. You reach it the first time with the
  access code Traigent emails you, not by signing up on the page directly.

Confirmation code
  Plain: the six-digit number in the first email Traigent sends you. It only
  proves the address is yours, and it stops working within minutes. It is not
  the thing that gets you into the portal.
  Ask like this: "Traigent just emailed you a six-digit code - type it into the
  page you started on, and a second email will follow."

Access code
  Plain: the single-use code in the second Traigent email. The access code
  lets you register once, any time in the next 10 days. Entering it is what
  creates your account, and it cannot be used again afterwards. The registration
  link in that email is just the way to the page - it carries no credential, so
  the code has to be typed in rather than clicked through.
  Note: because your address was already confirmed by the six-digit code,
  registration will not ask you to confirm it a second time. Registering lands
  you in the portal; you then create your full-access key yourself - the key
  control in the top bar is the quickest way, and it is highlighted on your
  first visit. The key is shown once, so save it there and then.

Portal access period
  Plain: the 10 days of Traigent portal access that start the moment you
  register. When it ends your account, data, and keys are all still there, but
  runs stop until you buy a plan on that same account.
  Note: this is not the same as an optimization "trial", which everywhere else
  in this guide means one tested configuration. Your API key does not extend the
  access period - the key proves who you are, the period decides whether the run
  is allowed. The full behavior is in `references/run-safety.md`.

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

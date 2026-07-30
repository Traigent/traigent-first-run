# Traigent - First Run

Run a guided Traigent optimization in one sitting, from whatever your project has today.

Your coding assistant inspects the project, preserves any real agent, dataset, and evaluation
method it finds, and checks whether those components can support a meaningful comparison. If a
real dataset or evaluator is too small, corrupted, narrow, trivial, or logically mismatched, the
assistant explains the evidence and offers to repair a working copy and revalidate it. If Traigent
generates temporary walkthrough material, it remains clearly marked so a demonstration is never
mistaken for production evidence. When an optimization does not beat your existing baseline, that
no-lift result is reported plainly rather than dressed up as a win - together with the likely
reason, such as a ceiling effect, an over-strict or too-easy evaluator, or generated walkthrough
data with no real headroom, where every configuration scores the same in both runs. A flat result
on demonstration data shows the workflow ran honestly, not that your production workload has
nothing to gain - on real data the same run would likely look different.

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

What it will not do is guess what your agent is *for*. If nothing in the project says what the task
is - no agent that performs an identifiable one, no dataset, no evaluator, no tests, fixtures or
product documentation - the assistant asks a single question and waits for the answer before writing
anything. A placeholder agent counts as nothing to go on: a file that returns a constant or echoes
its input is judged by what it does, not by the fact that it imports. Everything downstream of an
invented task is derived from a guess, and you would be approving real spend on it.

## Install as an Agent Skill

The complete guide, references, scripts, and compact internal run record are packaged together as
the same self-contained workflow the cloned-repository path runs:

```bash
npx skills add Traigent/traigent-first-run
```

Then ask:

```text
Use $traigent-first-run to run my first Traigent optimization.
```

Node.js is needed only for this optional installation command, not for the Traigent Python run.

## What the run does

1. Inspects the project and scores real-world readiness out of 100, before anything is created or
   repaired.
2. Diagnoses material dataset/evaluator limitations and offers repair, demonstration, or pause.
3. Creates only missing agent/dataset/evaluation components as temporary walkthrough substitutes.
4. Validates compatibility and evaluator discrimination.
5. Shows one concise runtime, cost-ceiling, and data-egress approval immediately before paid work.
6. Preserves an existing baseline or creates a credible small parameter sweep, then runs a
   broader optimization with additional meaningful knobs when the evaluator can distinguish
   configurations.
7. Retains the connected experiments and reports the result, limitations, artifacts, and verified
   portal links so they remain available for comparison.

Everything before that approval - inspecting the project, setting up any missing components, and
validating them locally - makes no provider calls and spends nothing, so the full setup is visible
before you decide to pay. Once you approve, the run first confirms your experiments are actually
recording to the portal and stops rather than spend on trials it cannot track.

The default generated comparison is two connected optimization experiments: six standard
parameter combinations in the first, then 10-13 trials from a materially broader space with added
knobs in the second. If the user already has a baseline, the first experiment preserves it exactly
instead of padding it with invented rows. Both runs use the same data and evaluator, followed by an
untouched holdout check. Any later iteration is optional, not required.

On a dataset larger than about 100 usable rows, the paid comparison is bounded to a small subset
spread across the difficulty range - drawn inside each split so it cannot invent an overlap, with
the selected row ids recorded so the run can be repeated. The report names that subset size beside
your full row count, and gives the run's own resolution as its own sentence.

Your readiness score is never taken on that subset. Both scores read the whole dataset, because the
score is a statement about your data and the subset is a limit on this one comparison - scoring the
sample would report our sampling as though it were a property of your dataset, and tell someone with
500 good rows that they have "a wiring check, not a score". A first run shows the capability in one
sitting; the full dataset is what a real optimization uses.

## The readiness score

Before anything is created or repaired, the assistant scores what your project has today: a number
out of 100 from three pillars - dataset, evaluation, and agent - and a named band from Not ready to
Excellent. The same score is taken again at the end, so the report shows the transition rather than
a single number with nothing to compare it to.

It is deliberately modest about itself. It runs before any optimization, from evidence on your own
machine, so it estimates rather than measures: a check that cannot be computed is marked unmeasured
and excluded rather than scored zero, and the card says how much of each pillar it actually observed
- `EVALUATION 100/100 (2 of 4 checks measured)` is a pillar whose two remaining checks nobody has
run yet, not a verified perfect one. A low score never stops the run; it decides which gaps are
worth explaining and which are worth fixing first.

That is also why the band can sit below the number. A pillar measured thinly cannot carry a strong
verdict, so `89/100 WORKABLE` is not a contradiction even though 89 falls inside the Strong range -
it is the card declining to call a project Strong on evidence it has not seen. Calibrating the
evaluator is usually what moves it.

Some conditions cap the whole score instead of costing a few points, because an average can hide a
broken ruler - an evaluator that scores a wrong answer as well as a right one, a tuning set that
shares examples with the holdout, a dataset that is mostly or entirely generated, or simply too few
comparable examples to tell one configuration from another. A cap is a ceiling on the result, not a
deduction and not a refusal: the run continues, the pre-cap average stays in the report, and the
number simply cannot claim more than the evidence supports.

The card labels the two kinds differently, and the label is the whole message. `BLOCKED` means
something is broken and paid work measured against it would measure the wrong thing - fix it first.
`LIMITED TO 89` means nothing is wrong with your setup, the result simply cannot claim more than your
data supports, and it names the number so "why is this 89" has an answer on the same line.

More than one condition can apply, and a ceiling only does anything while it is the lowest limit in
play - below every other ceiling, and below your average. A ceiling that is real but is not currently
the one in force reads `WOULD LIMIT TO 89` instead, and the tense is the whole difference. `LIMITED
TO 89` is the number you are at. `WOULD LIMIT TO 89` is a limit you have not reached: either
something stricter is holding the score down, or your average simply has not climbed that high yet.
It is still worth reading - it is what you run into next - but it is not why the score is what it is
today.

Saying where your rows came from is worth the small effort for the same reason: data you collected
is credited above data a model wrote, and a dataset that declares nothing is not credited as
production data. A mixture is scored as a mixture - a few generated rows among real ones cost a
little, they do not condemn the set.

The card also names what it cannot use. If half your expected answers are `-` or `?`, the line that
counts them says so - "100/100 rows carry an expected output, but 50 of them are placeholders" - so
a row count can never be read as that many usable answers. The precision figure beside it is still
computed from the row count rather than the usable subset: it is qualified, not withheld. Treating a
symbol as unlabelled would change the score for every dataset that uses one as a real class label,
so that stays a deliberate open question rather than a silent reinterpretation of your data.

## Requirements

- Python 3.11-3.13 in an isolated environment.
- The tested first-run SDK stack pinned in
  [`skills/traigent-first-run/assets/requirements-first-run.txt`](skills/traigent-first-run/assets/requirements-first-run.txt).
- One supported LLM-provider key with a small amount of credit for the real run. The sweep
  ladders that provider's models - a fast tier, a mid tier, and a strong tier one step below its
  newest flagship - and deliberately skips the flagship itself so the first run stays quick and
  cheap; the flagship remains the natural next rung for a later, deeper run. Both runs use the
  same three models, so an optimization win comes from Traigent's search and knobs, not from a
  hidden model upgrade.
- A Traigent portal key for connected optimization and portal results. You are asked for it *after*
  the first result is on screen, not before. The baseline runs locally on your own provider key and
  needs no Traigent account, so you see a real number from your own project before deciding whether
  to register.

Your assistant preserves or creates an owner-only local `.env`, adds only missing key names for the
chosen provider and Traigent, and asks you to paste the values there. Never paste secrets into chat.

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
| [`reports/`](reports/) | Field-test evidence and methodology research behind the safeguards |

After the first result, the assistant can offer the advanced
[Traigent optimization skills](https://github.com/Traigent/traigent-skills) as optional next steps.

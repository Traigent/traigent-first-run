# Traigent - First Run

Run a guided Traigent optimization in one sitting, from whatever your project has today.

Your coding assistant inspects the project, preserves any real agent, dataset, and evaluation
method it finds, and checks whether those components can support a meaningful comparison. If a
real dataset or evaluator is too small, corrupted, narrow, trivial, or logically mismatched, the
assistant explains the evidence and offers to repair a working copy and revalidate it. The
assistant labels any temporary walkthrough material so it cannot be mistaken for production
evidence. When an optimization does not beat your existing baseline, that no-lift result is
reported plainly rather than dressed up as a win. Verified facts are separated
from inferences and hypotheses such as a ceiling effect, an uninformative evaluator, or a weak
search space; when the run cannot establish a cause, it says so. A flat result on demonstration
data does not establish what production performance would be.

## Start with one prompt

Paste this into Claude Code, Cursor, Codex, Gemini CLI, or another coding assistant:

```text
Help me run my first Traigent optimization.
Clone https://github.com/Traigent/traigent-first-run and follow GUIDE.md.
```

The assistant performs the technical work and asks only when it needs:

- A choice that materially changes the task - which agent to optimize is the first of them, and
  the only one asked before the walkthrough starts.
- A key pasted into an owner-only local `.env` file, ignored when your project uses Git.
- Approval before paid model calls or private-data egress.
- Approval before judgment-dependent changes to real examples, expected answers, or grading policy,
  and before destructive or production-affecting actions.
- Confirmation before installing into a virtual environment other work of yours depends on, rather
  than one created for this run. It always names the full path first, either way, so you know which
  directory is about to change - and a repeat run does not re-ask about the environment the last
  one made.

No existing agent, dataset, or evaluator is required to see the walkthrough. If several credible
agents are present, the assistant asks which one to optimize; if there is exactly one, it names it
and asks whether to run on it. Once you have chosen - a dummy or walkthrough agent counts as
chosen - it keeps using that one and never asks again. When something is missing you are told
before anything is written, in one question however many pieces are absent: what it did not find,
that material it writes is weaker evidence than examples out of your product and what that costs
the result, and two ways to answer - go ahead, or point it at yours. Only then does it prepare a
coherent substitute around everything that already exists, and Traigent runs the managed
optimization.

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
The assistant resolves bundled files from the installed skill's absolute directory while keeping
your project as the working directory; installing the skill does not require cloning it into or
changing out of your project.

## What the run does

1. Inspects the project and scores real-world readiness out of 100, before anything is created or
   repaired.
2. Diagnoses material dataset/evaluator limitations and offers repair, demonstration, or pause.
3. Creates only missing agent/dataset/evaluation components as temporary walkthrough substitutes.
4. Validates compatibility and every safely local evaluator-discrimination check; any LLM-judge or
   external calibration remains inside the paid/data-egress approval.
5. Shows a concise baseline preview immediately before its paid calls, with runtime, estimated
   spend, a total execution stop target (`$5.00` by default), and data egress. That target is a
   conservative control, not a guaranteed provider-billing cap. When this run had to write the
   dataset or the grading method, the same preview shows what it wrote - full paths, the easiest and
   the hardest example, and what the method counts as correct - and asks you to proceed or fix
   before anything is charged.
6. Shows the baseline result, then explains and separately approves the broader managed
   optimization with additional meaningful knobs when the evaluator can distinguish configurations.
7. Retains every experiment actually persisted and reports the result, limitations, artifacts, and
   verified portal links; an unsynced baseline is clearly labelled local-only.

Before baseline approval, inspection, setup, and local validation make no provider calls and spend
nothing. The provider-paid local fixed baseline result appears before any Traigent account/key
request. Only then does the guide explain and separately approve the managed optimization and
verify portal tracking with a zero-LLM probe before its paid calls.

At boundaries, the assistant shows `Stage n/5` and measured numbers. After baseline: continue with
Traigent when the measured results show useful headroom, or address the strongest observed
limitation first. It gives reason and scope—never a generic menu or guaranteed gain.

The default generated comparison has two planned measurements: all twelve configurations of a local
fixed grid first, followed by a connected managed search over a materially broader space with added
knobs, testing up to 12 configurations and choosing which ones as it goes rather than working
through a fixed list. The approval card names that space's total combination count beside the
ceiling, so the 12 reads against the space it is drawn from. A disclosed runtime, cost, or plan limit
can make the approved comparison smaller; the report gives the number of configurations actually
tested and any concrete shortfall reason. If you already have a baseline, the first measurement
preserves its exact rows and models instead of padding it.
The assistant attempts an exact upload without rerunning that baseline only when the installed
public SDK exposes its sync id; otherwise it remains local. Both measurements use the same data,
evaluator, and objectives, followed by the held-out set. A held-out set is called sealed only when
its split and labels stayed hidden until the candidate was locked. Any later iteration is optional,
not required.

On a dataset larger than about 100 usable rows, the paid comparison is bounded to a small subset
spread across the difficulty range - drawn inside each split so it cannot invent an overlap, with
the selected row ids recorded so the run can be repeated. The report names that subset size beside
your full row count, and states the resulting sample-size limitation separately.

Your readiness score is never taken on that subset. Every readiness run reads the whole dataset,
because the score is a statement about your data and the subset is a limit on this one comparison -
scoring the sample would report our sampling as though it were a property of your dataset, and tell
someone with 500 good rows that they have "a wiring check, not a score". A first run shows the
capability in one sitting; the full dataset is what a real optimization uses.

## The readiness score

Before anything is created or repaired, the assistant scores what your project has today: a number
out of 100 from three pillars - dataset, evaluation, and agent - and a named band from Not ready to
Excellent. That opening number is the one the report keeps, because it is the only one taken on
material the walkthrough did not write. The score is re-run during the run to check that a repair
really cleared what it failed on before anything is paid for, but no closing number is put beside
the opening one and called progress: once the assistant has filled your gaps, a second score mostly
grades the substitutes it just wrote.

What the close gives you instead is what was created or repaired and what that costs the claim.
Examples written for the walkthrough are weaker evidence than examples collected from your product.
A generated evaluation method is a starting point rather than your grading policy - it is worth
tuning in whichever direction your product needs, so that it rewards, say, how an answer reads
rather than which words it reuses.

It is deliberately modest about itself. It runs before any optimization, from evidence on your own
machine, so it estimates rather than measures. A check this tool could not compute is marked
unmeasured and excluded rather than scored zero; a check the run was asked for and did not supply
is marked unmeasured too, but keeps its weight and earns nothing, so withholding it can never pay.
The card says how much of each pillar it actually observed, and
`EVALUATION 75/100 (2 of 4 checks measured)` is what an opening card prints before any calibration
has run - 75 is the most that pillar can read while two of its four checks are unmeasured, not a
verdict on your evaluator. A low score never stops the run; it decides which gaps are worth
explaining and which are worth fixing first.

That is also why the band can sit below the number. A pillar measured thinly cannot carry a strong
verdict, so `89/100 WORKABLE` is not a contradiction even though 89 falls inside the Strong range -
it is the card declining to call a project Strong on evidence it has not seen. The card names which
pillar is thin - `EVALUATION 75/100 (2 of 4 checks measured)` - and calibrating the evaluator is
what fills that one in.

No settings document exists before the search, so the agent pillar is read from the agent's own
code instead - which parameters it can already vary, each against the line that shows it - and that
is what the opening score grades the search space from. The same read answers four more questions
about how the agent is built: whether it carries a prompt and worked examples, whether anything
pins down the shape of its answer, whether it ends and on what, and whether the tools it declares
can be reached. Each is a fact with a line of your code behind it, and a question the read cannot
settle is reported as unsettled rather than counted against you. Two things the pillar is not
allowed to guess at are named on the card instead: whether your dataset and your evaluation method
are wired into the agent, which this run builds afterwards and checks against the installed SDK.
Where the read finds settings, no agent
ceiling applies and calibrating can carry the band the whole way. Two states hold the score at 45,
inside Partial, and they are different findings. A reading that found nothing your agent can vary
says a search here would compare one configuration - a measurement of your project - so it blocks
the paid run until something can vary. No reading and no document says only that this score was
given nothing to count: it claims nothing about your project either way, and it stops nothing. What
the opening card no longer does is hold every project at 45 for a document nobody was supposed to
bring.

Some conditions cap the whole score instead of costing a few points, because an average can hide a
broken ruler - an evaluator that scores a wrong answer as well as a right one, a tuning set that
shares examples with the held-out set, a dataset that is mostly or entirely generated, or simply
too few comparable examples for a stable comparison. What a cap does to the score is bound it: a
cap is a ceiling on the number, not a deduction and not a refusal to score. The walkthrough carries
on, the pre-cap average stays in the report, and the number simply cannot claim more than the
evidence supports.

Whether the paid run may start is a separate question, and some of those same conditions answer it
too: they hold the paid comparison until they are cleared, while the rest only bound what the
result may claim. The card says the holding on its own `BLOCKER` line under the score rather than
as a tag beside the band, because the band and the block grade different things - the band grades
how good the evidence is, the blocker says whether the paid comparison may start yet. A generated
walkthrough dataset scoring `65/100 WORKABLE` while blocked is therefore the ordinary case and not
a self-contradiction: the score stands, and the line says how many things have to clear first,
where each of them is marked, and what happens once they are cleared.

The card labels the kinds differently, and the label is the whole message.
`FIX BEFORE PAID RUN` means the current components cannot yet support a trustworthy paid
comparison and something has to be created or repaired first - no dataset, no expected answers, an
evaluator that scores a wrong answer as well as a right one, a tuning set that shares examples with
the held-out set, nothing scoreable in the split the search would tune on. Follow the named repair or
evidence-gathering action first. `LIMITED TO 89` means the paid comparison can proceed, but the available evidence
bounds what the result may claim; it names the number so "why is this 89" has an answer on the
same line.

Between those two there is a third, and it is the only one that needs anything from you. Some
conditions do not hold the run up and still leave a person something to agree with before the
number means what it looks like - an answer key a model wrote end to end, rows whose expected
answer does not appear to match their own input, or a dataset that never says where its rows came
from, which is read as generated precisely because nothing here can check it. Each of those is put
to you once, with the material to judge it on and a straight pair of exits - at the point the
finding is made where that is still free to act on, otherwise inside the approval before the first
paid call - and the approval shows you what you answered either way. Once, not twice: being asked
the same thing again in different words at the till is the thing this is built to avoid. Stopping a
paid run over the assistant's reading of your data would be wrong; showing you a
ceiling with no way to act on it was the older mistake, and this is the fix for it.

Generated data and a small comparison set land on neither of those. A walkthrough dataset is what
this guide writes for a user who has none, and a handful of rows is a wiring check - both are runs
worth making, and both are things the result may not claim too much from. So they lower the ceiling
and say why; they do not stop the run and they ask nothing of you.

More than one condition can apply, and a ceiling only does anything while it is the lowest limit in
play - at or below every other ceiling, and at or below your average. Two conditions can carry the
same ceiling, and then both are in force and both read `LIMITED TO 45`; neither is a mistake, and
fixing one leaves the number where it is until the other is fixed too. A ceiling that is real but is
not currently the one in force reads `WOULD LIMIT TO 89` instead, and the tense is the whole
difference. `LIMITED
TO 89` is the number you are at. `WOULD LIMIT TO 89` is a limit you have not reached: either
something stricter is holding the score down, or your average simply has not climbed that high yet.
It is still worth reading - it is what you run into next - but it is not why the score is what it is
today.

Saying where your rows came from is worth the small effort for the same reason: data you collected
is credited above data a model wrote, and a dataset that declares nothing is not credited as
production data. A mixture is scored as a mixture - a few generated rows among real ones cost a
little, they do not condemn the set.

The card also names what it cannot infer. If half your expected answers are `-` or `?`, it calls
them symbol-only outputs that need confirmation. They remain in the labelled and sample-size counts
because a symbol can be a legitimate class label; the guide does not silently reinterpret them as
placeholders or claim they are unusable.

## Requirements

- Python 3.11-3.13 in an isolated environment.
- The tested first-run SDK stack pinned in
  [`skills/traigent-first-run/assets/requirements-first-run.txt`](skills/traigent-first-run/assets/requirements-first-run.txt).
- One supported LLM-provider key with a small amount of credit for the real run. When the assistant
  must prepare a missing baseline, that generated sweep uses one model family available through the
  selected route by default - a fast tier, a mid tier, and a strong tier one step below that
  family's newest flagship. If a missing rung requires a second family, the additional upstream
  recipient is disclosed and approved. The newest flagship is deliberately skipped so the first
  run stays quick and cheap. A user-owned baseline instead keeps its exact model set in both
  measurements; the enhanced run adds no model unless that separate comparison is disclosed and
  approved.
- A Traigent portal key that can write experiments for connected optimization and portal results.
  It is activated *after* the first result is on screen, not before; if no key is already present,
  the assistant asks you to add a full-access key then. The baseline runs locally on your own
  provider key and needs no Traigent account, so you see a real number from your own project before
  deciding whether to register.

Your assistant preserves or creates an owner-only local `.env`, verifies it is untracked and
effectively ignored when your project uses Git, asks for only the provider key before the local
baseline, and activates a preserved Traigent key or asks you to add one after the checkpoint. Never
paste secrets into chat.

## License

This repository - the walkthrough, the bundled skill, the scripts and the references - is
**dual-licensed** on the same terms as the SDK it installs: the
[GNU Affero General Public License v3.0 only](LICENSE) (`AGPL-3.0-only`) **or** a
[Traigent commercial license](COMMERCIAL-LICENSE.md) under a separate written agreement.
SPDX: `AGPL-3.0-only OR LicenseRef-Traigent-Commercial`. Commercial inquiries: `legal@traigent.ai`.

One licence covers both, so a project already holding commercial terms for the SDK needs nothing
further to use this guide. External contributions require a signed CLA - see
[CONTRIBUTOR-LICENSING.md](CONTRIBUTOR-LICENSING.md).

## SDK licensing

The pinned requirements install `traigent==0.26.0`. The Traigent SDK is offered under the
[GNU Affero General Public License v3.0 only](https://github.com/Traigent/Traigent/blob/v0.26.0/LICENSE)
(`AGPL-3.0-only`) or, under a separate written agreement, a
[Traigent commercial license](https://github.com/Traigent/Traigent/blob/v0.26.0/COMMERCIAL-LICENSE.md).
Installing the package does not itself grant commercial terms. Organizations that need terms other
than the AGPL must obtain a separate written commercial agreement from Traigent; contact
`legal@traigent.ai`. This notice describes the SDK dependency.

## Privacy

According to the
[pinned SDK 0.26.0 telemetry contract](https://github.com/Traigent/Traigent/blob/v0.26.0/docs/api-reference/telemetry.md),
connected runs can send tuned configuration keys and values, numeric metrics, trial/run state, and
content-free metadata needed for optimization and portal history. Except for content deliberately
placed in a tuned configuration value and any observability content the project explicitly opts
into recording, the contract says the SDK does not send user prompts or inputs,
evaluation-dataset contents, expected outputs, model responses, source code, or credentials to the
Traigent backend.
Because configuration choices are synchronized, this walkthrough maps prompt variants to short
content-free labels inside the agent; raw prompt text is not used as a configuration value. This
walkthrough does not independently audit network packets; it stops if observed runtime behavior
contradicts that contract.

That backend boundary is separate from local retention. SDK 0.26.0 writes each example's `query`,
`response`, and `expected` text to local optimization logs by default. The walkthrough sets
`TRAIGENT_LOG_EXAMPLE_CONTENT=false` in its run process before importing Traigent, which retains
example ids and metrics but writes those three content fields as `null`, and keeps
assistant-created logs under the ignored `traigent-runs/` directory. A preserved project-defined
results folder is honored and named.

The selected LLM provider still receives the content the agent normally sends during model calls.
Your assistant explains which services receive data and asks before paid calls or private-data
egress.

## Repository layout

| Path | Purpose |
|---|---|
| [`GUIDE.md`](GUIDE.md) | Entry point for a cloned-repository run |
| [`skills/traigent-first-run/`](skills/traigent-first-run/) | Self-contained installable skill |
| [`.env.example`](.env.example) | Reference environment settings |
| `traigent-runs/` (created during a run) | Assistant-created walkthrough artifacts and the default local run record; ignored when the project uses Git |
| [`reports/`](reports/) | Field-test evidence and methodology research behind the safeguards |
| [`tests/`](tests/) | The checks below, including the guidance-budget ledger and the behaviour lock |
| [`tools/`](tools/) | `relock.py`, which regenerates the behaviour lock |

## Verifying a change

These are the checks CI runs in its `validate` job, in the order it runs them. Running them locally
first is the whole difference between one push and three:

```bash
python tools/relock.py --check
python -m pip install -r skills/traigent-first-run/assets/requirements-first-run.txt
python -m unittest discover -s tests
ruff check .
black --check .
```

The lock check is deliberately first, before the installs, so a lock that was never regenerated
fails in seconds rather than after a full run. Reordering this list locally costs you that.

One CI job is not in the list because it cannot be reproduced by a command: `offline-contract` runs
the behavioural harness inside a network-less, read-only container, and `validate` does not start
until it passes. Everything above can be green while that job is not.

`ruff` and `black` are pinned to exact versions in
[`.github/workflows/`](.github/workflows/) - install the versions it names, since a different
release of either reformats different code. The pins are deliberately not repeated here: a second
copy is a second thing to forget.

Two of them surprise people, so they are worth naming rather than leaving to be discovered from a
red build.

`tools/relock.py --check` compares a recorded lock against the guidance as it stands. Editing any
assistant-facing document changes it, so run `python tools/relock.py` (no flag) to regenerate, and
commit the result **in the same commit** as the edit that moved it - a lock regenerated but left
unstaged passes the check here and fails it in CI, which reads the commit rather than your
working tree.

The suite enforces a **byte budget** over the assistant-facing documents, and the ceiling is not a
number in a test file. There are two ceilings, resident and total, and each is read from the newest entry along the
ledger's `follows:` chain that declared THAT ceiling - `tests/guidance_budget/`, one file per raise,
each stating what it measured and why the addition earned it. Guidance that grows past the
current ceiling needs a new entry, not a bigger constant - and if two branches each add one, the
figure that matters is measured over the **merge**, not carried over from whichever landed first.

After the first result, the assistant can offer the advanced
[Traigent optimization skills](https://github.com/Traigent/traigent-skills) as optional next steps.

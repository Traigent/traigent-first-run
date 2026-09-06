# Agent-guidance review of traigent-first-run - 2026-09-05

Reviewed at branch `fix/ledger-refund-unbilled-rejections`, head `5a67273` (trunk `75d338c` plus the ledger refund
fix). Scope: everything a customer's coding agent reads or runs. Six reviewers read one surface each end to end
(GUIDE/README/AGENTS/CLAUDE; SKILL.md; run-safety.md + run-plan.md; component-creation.md +
evaluation-and-dataset.md + glossary.md; sdk-execution.md; the four scripts). Every finding below that is
marked **C** was re-read at the cited line by the synthesising reviewer; **R** means reviewer-reported and not
re-read. Reviewer claims that did not survive re-reading are listed in "Refuted or downgraded" at the end.

## 1. The owner's four questions

### Q1. After a repair, does the agent re-check everything or only what was fixed? Is "fixed, ready to continue" clear?

**The rule exists, is reconstructible, and is split across three documents; the display after a repair is
unspecified.** What the documents say:

- Score: always recomputed over all three pillars. SKILL.md:39 "again after each repair or creation, and once
  more after the run"; glossary.md:314-318 "again after each repair or creation, to check that what failed a gate
  now passes it". (C)
- Checks: only what the repair touched. SKILL.md:137 "revalidate from the failed gate"; SKILL.md:769 "re-run the
  affected checks, the applicable calibration, and the score"; SKILL.md:380 "re-reading the agent only where this
  run created or repaired it". (C)
- Display: glossary.md:376-377 "A re-score is a gate result: lead with the caps that cleared, never with a new
  score beside the opening one." SKILL.md:483-486 "Refresh only changed evidence after creation; retain
  unresolved lines". (C)

Gaps:

- No stage step states the three together, and the display rule lives in the glossary, a document whose own
  header says it "only fixes what the words mean". (C)
- No "fixed, continuing" line is defined anywhere. The reviewer of SKILL.md found the same rule phrased four ways
  (SKILL.md:30-32, :137, :662-663, :769-771). (R)
- Two repairs silently invalidate an earlier check and nothing says to redo it: an evaluator repair stales the
  degenerate-gold pass (evaluation-and-dataset.md:620-625 ran it once, and :454 re-runs only "the checks that
  produced the advisory", which a clean pass never did); a dataset supplied by `I have it` after the opening-gate
  calibration never re-derives the calibration cases (component-creation.md:263-282). (R)

- The scorer cannot express "only X changed". `readiness.py` has no previous-result input; every call rebuilds
  all three fact sets from argv, its JSON output replaces the card rather than accompanying it, and the card
  prints no next-step line. A blocked card exits 0 unless `--strict` is passed, and SKILL.md never passes it, so
  the verdict lives only in the card text the agent must read. (C)

Recommended shape, one paragraph in SKILL.md stage 4 replacing the four scattered statements: re-run the checks
whose input changed, name the two invalidation cases, recompute the score, then print one line
`Fixed: <component> - cleared: <caps> - continuing` and show no second card.

### Q2. Is the user asked before the SDK is installed?

**No. The user is informed once and never asked.** SKILL.md:135 authorises the install to "Proceed only after
task intent is anchored and the available standard-library-only component checks have run", deferring only to
"A user or environment policy that requires install approval". The only notice to the human is the opening
message, SKILL.md:193 "Baseline - install the SDK, then measure today's setup". (C) On a fully prepared project
the gap ask never fires (SKILL.md:236), so `.venv-traigent`, the pip install, `traigent-runs/` and the
`.gitignore` edit all happen before the user has replied to anything. (R) README.md:25-32 lists what the assistant
"asks only when it needs" and the install is not among them; README.md:305 names the traigent pin and not the
litellm one. (C)

The install is free, pinned and isolated, so this is a consent-design choice rather than a safety bug. If the
owner wants a yes, the cheapest place is the stage-5 route question that already exists (SKILL.md:788-792), which
today is a yes/no buried mid-procedure with no stop (see finding 8).

### Q3. Does the agent know the run is intentionally small and must not chase a better number?

**Partly. "Small" is stated; "why" is stated once; "do not improve the number" is absent, and two passages
recommend the opposite.**

Present:

- run-safety.md:656 "what is approved here is deliberately small, a bounded taste of the workflow at a priced
  ceiling rather than a full search". (C)
- evaluation-and-dataset.md:930-932 "A first run has to show the capability, not exhaust the dataset ... a large
  set turns the walkthrough into a long, expensive run that demonstrates nothing the smaller one would not";
  :1027-1029 "this bound exists only so the first run finishes"; :1087-1088 "Ten is therefore exact in both
  directions, never a floor to grow from"; :495 "Never draw past 28 in total". (C)
- run-safety.md:804 "never a second attempt at the same phase on top of what the first one already spent". (C)
- SKILL.md:928 "deliberately small enhancement"; sdk-execution.md:2004 "keeping the first taste deliberately
  small". (C)

Absent or contradicted:

- No sentence forbids re-running the baseline, topping up rows from the original data, widening the space or
  raising the trial cap to improve a number. SKILL.md:1085 forbids only "a third optimization pass", which reads as
  permitting a second. (C)
- run-safety.md:767-771: after a baseline with no headroom, the recommended route "moves [the mark] onto more or
  harder rows before the search ... `A.` is the rows route and carries the mark". README.md:112-114 sanctions the
  same: "addressing the strongest observed limitation first where the measured results show no useful headroom".
  This is the exact behaviour the owner does not want. (C)
- run-safety.md:836-837 offers "another bounded pass only when additional search is justified", while
  run-safety.md:1219-1220 offers it unconditionally: "show the best partial result before offering one additional
  bounded pass". (C)
- evaluation-and-dataset.md:479 "Adjust the tuning size when cost or task shape requires it" has no upper bound
  in that sentence. (C)
- sdk-execution.md:607-610 accepts `TRAIGENT_FIRST_RUN_ENHANCED_MAX_TRIALS` up to 23 against a 24-point space;
  nothing in prose says not to raise it. (C)
- "Rows" means dataset rows in most places and configurations in others: run-safety.md:593 "generated twelve-row
  sweep", :991 "all twelve distinct rows"; sdk-execution.md:1976 "twelve baseline rows and a 12-trial enhanced
  cap", :2357 "Fewer than 10 rows". An agent told to keep "twelve rows" can reach for the dataset. (C)
- The readiness scorer pushes the other way. `readiness.py:3981-3991` awards 12 of 25 size points to the guide's
  own 18-row set as "small comparison set" and 25 to 300 or more rows as "large comparison set"; the top-up offer
  falls silent at 28 rows with no sentence saying the size is intended, and the reviewer observed the card
  printing a limit of 89 on exactly the dataset the guide builds. An agent reading that card is told, in effect,
  that more rows would score higher. (C for the bands, R for the observed card)
- `preflight.py:348, 1157-1165` proposes the 18-question subset only above 100 usable rows; a 99-row dataset runs
  in full, every trial paying for every row. (C)
- The cloud-connection purpose is never given as a reason for smallness. (R, all reviewers)

Recommended: one resident paragraph in SKILL.md, under "Operating contract", stating the purpose (finish in one
sitting under the ceiling, prove the cloud connection, show the workflow) and the four prohibitions (no re-run of
a paid phase, no rows added from the original data, no wider space, no higher trial cap, without a newly scoped
approval); delete the rows route at run-safety.md:767-771 and README.md:113; make the two timeout rules one; and
replace "row" with "configuration" at the four sites above.

### Q4. Are questions asked clearly, one at a time, at the end of the message?

**The rule exists and is good; three places break it.**

- The rule: SKILL.md:112-113 "An ask that follows a result sits below it. Never a marker, heading or summary of it
  above the card"; SKILL.md:527-529 "Then stop and wait, and ask nothing else here ... It closes the message";
  component-creation.md:254-255 "The ask goes lowermost: last on screen, and last read"; :245-247 "nothing follows
  the standing line, not a clarifying question". (C)
- Break 1: SKILL.md:788-792, stage 5 step 1, embeds "Preserve this route by adding <key>, or change to <available
  vendor>?" inside a `Say:` template in the middle of a six-step procedure. No stop, not lettered, followed by the
  unattended install and then a second stop for the secret at :814-816. (C)
- Break 2: the pre-spend approval carries up to three decisions on one reply: the spend, a proceed-or-fix pair
  (SKILL.md:858-861, run-safety.md:644-647) and a provenance declaration (SKILL.md:722-724), while :861 says
  "approving the spend is not approving the material". (R)
- Break 3: before the connected checkpoint, SKILL.md:943-1032 mandates about 5.5 KB of explanation before the
  routes. The routes are last, but the user reads a wall first. (R)
- Break 4: run-safety.md:895-898 asks the no-egress question "at the point the second run is explained", which
  lands in the same message as the connected routes. (C)
- The pre-spend card has no "nothing follows it" rule of its own; only the connected preview does
  (run-safety.md:746-748). (R)

## 2. Findings, ranked

| # | Sev | Where | What | Fix |
|---|---|---|---|---|
| 1 | P0 (C) | run-safety.md:137-139 | "Stop before key handoff; ask Traigent for its canonical training-use policy. Nothing local clears this: it holds until Traigent provides one." A literal agent halts every connected run at the Traigent key. | Replace with the sentence to say and the policy link; delete the stop. |
| 2 | P1 (C) | run-safety.md:767-771, README.md:112-114 | Recommended post-baseline route is more or harder rows before the search. | Make rows a post-run handoff to `traigent-dataset-curate`, never an in-run route. |
| 3 | P1 (C) | SKILL.md:1085, sdk-execution.md:2066-2132 | No rule against a second baseline or search for a better number; baseline section has no re-run rule at all. | The resident paragraph proposed under Q3. |
| 4 | P1 (C) | run-safety.md:836-837 vs :1219-1220 | Timeout rule: conditional second pass vs unconditional offer. | One rule in Recovery. |
| 5 | P1 (C) | SKILL.md:135, :193, :800-804; README.md:25-32 | SDK install with no ask; README omits it from the asks list. | Owner's call; if asked, ride on the stage-5 route question. |
| 6 | P1 (C) | SKILL.md:205-206 vs :275, :362-363, :988; GUIDE.md:99 | "Stage 5" is the environment section in some sentences and the Results stage in others; SKILL.md says section numbers are never shown. :362-363 is wrong under both numberings. | Say "section N" internally; add a five-line section-to-stage map under "Guided flow". |
| 7 | P1 (C) | sdk-execution.md, whole fence 1 | No adaptation map: 1,618 fence lines with one "Replace this example's spaces" sentence at :2007. An agent cannot tell verbatim from adapt. | A ten-line "Adapt only these" list above the fence and `# ADAPT:` tags. |
| 8 | P2 (C) | SKILL.md:788-792 | Yes/no route question mid-procedure, no stop, before the install. | Letter it, stop on it, merge with the secret stop. |
| 9 | P2 (C) | glossary.md:376, SKILL.md:483-486, :769 | Post-repair display unspecified; rule split across three documents. | The paragraph proposed under Q1. |
| 10 | P2 (C) | run-safety.md:593, :991; sdk-execution.md:1976, :2357 | "row" used for configurations and trials. | "configuration" / "trial". |
| 11 | P2 (C) | sdk-execution.md:2097-2098 | "Locally the SDK registers exactly two searches, `grid` and `random`". The installed 0.26.0 registry registers six: adaptive_batch, grid, multi_objective_batch, parallel_batch, random, remote. | "the only local sampling algorithms are `grid` and `random`", or drop. |
| 12 | P2 (C) | sdk-execution.md:594-596 | `TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS` has no default and is named nowhere in prose; run-safety.md lists three required variables, not this fourth. A baseline process launched without it raises at import. | Name it beside the other three with its formula. |
| 13 | P2 (C) | sdk-execution.md:2288 vs :2290-2299, :2217 | Config-space document is written before the portal check that exits, while :2217 says such a run "emits no document at all". | Move the write below the check. |
| 14 | P2 (C) | sdk-execution.md:1046, :2045 | `CALLS_PER_SCORED_ROW` is computed at import from `SCORER_CALLS_PER_ROW`; prose tells the agent to set the latter after the fence. | A function, or "edit the literal at :1042". |
| 15 | P2 (C) | component-creation.md:74-77 vs :112-114 | "`I have it` is never among them ... a document that counts it teaches a reader to number it" vs "Three answers, not two", where the three include `I have it`. | "Two answers plus the standing path line". |
| 16 | P2 (C) | run-safety.md:1209 | "harnesses often kill at about five minutes" - unsupported; this harness defaults to two. | "Run a long paid optimization detached regardless of harness timeout." |
| 17 | P2 (C) | GUIDE.md:138-140 vs sdk-execution.md:2506; CLAUDE.md:27-32 | Portal-deletion rule stated in GUIDE and in a reference, against the repo's own "GUIDE states no rule SKILL.md does not" and "one decision, one home". Same for the install rule (GUIDE.md:81-85, SKILL.md:135, run-safety.md:45-51). | GUIDE keeps a pointer; tests/test_skill_package.py:4200-4213 currently forces the triple statement and must change with it. |
| 18 | P2 (C) | README.md:85 vs :108; :27-28 vs :40-41 vs SKILL.md:234-235 | Diagram says "Offline Baseline Run" for a provider-paid phase; README says the agent choice is "the only one asked before the walkthrough starts" and that a single agent is asked about separately, while SKILL folds it into the one ask. | Rename the node; align the two sentences with SKILL.md. |
| 19 | P2 (R) | run-safety.md:162, :174-177, :216-230; :263-267, :289-305, :598-599, :691-692; and others | Same rule stated two to four times with different wording (write-scope key rule x4, execution-evaluator stop x4, telemetry contract x2, cost-limit-reached x2, mark rule x2). | One canonical statement each. |
| 20 | P2 (R) | evaluation-and-dataset.md:825-826, :940-941, :1033-1034 | Held-out draw timing stated three ways; whether they are three cases or one is not said. | One sentence naming the stage per case. |
| 21 | P2 (R) | evaluation-and-dataset.md:454, :620-625; component-creation.md:263-282 | The two repair-invalidation cases under Q1. | Name them in the post-repair rule. |
| 22 | P3 (C) | evaluation-and-dataset.md:546-548 | "moves the overall score by under 3 - a fully generated dataset perfect on every other dimension still reported 93". With the dataset pillar at 40 (readiness.py:238) the arithmetic gives 97. | Name the other deductions or drop the number. |
| 23 | P3 (C) | sdk-execution.md:1654 | `score = ...` in `task_score` parses and returns `Ellipsis`; held-out scoring then fails on `sum`. | `raise NotImplementedError(...)`. |
| 24 | P3 (R) | README.md:166, :174, :176 | Two evaluation scores for the same state; a 0.55 confidence with no literal in readiness.py. | Prefix "for example". |
| 25 | P3 (R) | glossary.md:137, :252-253 vs evaluation-and-dataset.md:474, :932-935 | Numbers and timings restated in the glossary against its own "only fixes what the words mean". | Glossary keeps definitions, drops numbers. |
| 26 | P1 (C, ran) | assets/sql_structure.py:1384 with the sorted select list at :1111 | `SELECT a, b ... ORDER BY 1` and `SELECT b, a ... ORDER BY 1` score 1.0: wrong SQL is credited. | Resolve ordinal `ORDER BY` / `GROUP BY` to the column before sorting. |
| 27 | P1 (C, ran) | assets/sql_structure.py:1365-1368 | A query with a `DATE '...'` literal or a window function scores 0.0 against itself; a Text2SQL gold containing either optimises to a flat zero. | Extend the parser; ship a `sql_structure.py gold.jsonl` self-match so the agent finds unparseable gold before spending. Note preflight.py:2930-2936 pins the customer's copy AST-identical, so any fix needs a re-copy note. |
| 28 | P1 (C) | readiness.py:3981-3991, :3636; preflight.py:348 | Size bands reward more rows; subset only above 100 rows. See Q3. | A card sentence at 28 rows saying this is the size the guide builds; stop routing walkthrough-size data to `add-examples`; consider a lower subset threshold. |
| 29 | P1 (C) | readiness.py, whole | No re-score diff mode; `--json` replaces the card; blocked exits 0 without `--strict`. See Q1. | `--previous <json>` printing changed and unchanged pillars; a last card line from `recommended_action`; exit 1 on BLOCKED by default. |
| 30 | P1 (C) | readiness.py:15547 | Knob values compared by `repr`: `[0, 0.7]` in the space against `[0.0, 0.7]` in source yields the false card text "declares '0', '0.7' which the cited call path does not show". | Canonicalise numerics before comparing. |
| 31 | P1 (R) | readiness.py:9334, :9645, :10257-10260; preflight.py:2282/2302, :769/777 with readiness.py:8843-8856; calibrate_evaluator.py:1910 | Unguarded input shapes exit 3 blaming the tool; two non-empty space keys silently drop one; duplicate preflight check names collapse last-wins; child stdout parsed unguarded. | Type guards raising the input error; refuse two space keys; unique check names; guard the JSON parse. |
| 32 | P2 (R) | preflight.py:874-879; calibrate_evaluator.py:723-746; readiness.py:8009, :9288, :6324, :16136 | Cost-approved warning fires on a `.env` value; secrets stripped by name only; ANSI when piped under VS Code; preflight JSON has no schema version; task-fit marked measured from a declared method; a hardcoded `gpt-4o` example reaches the human card. | As named per item by the scripts reviewer. |
| 33 | P3 (R) | preflight.py, readiness.py, calibrate_evaluator.py | Exit codes undocumented; refusal and usage error share code 2; `--weights nan,1,1` accepted; dead functions. | Epilogs, distinct codes, a NaN check, delete dead code. |

Handled well and worth keeping as is: ask-last placement rule (SKILL.md:112-113, component-creation.md:245-255);
the cost variables with no defaults (run-safety.md:778-789); the no-lift framing (run-safety.md:1107-1113); the
zero-LLM probe; "Never say the material does not exist" (component-creation.md:62-69); the SE and CI arithmetic
(evaluation-and-dataset.md:1103-1109); README's cost caveat (:97-98); every SDK and litellm API the sdk-execution
fences call was confirmed present on the pinned versions.

## 3. The shipped scripts

The four scripts are what the agent runs, and the customer's copy of `sql_structure.py` is what grades a
Text2SQL project. Findings 26 to 33 above; the short version:

- `validate_run_log.py` is the model the others should follow: closed sets, `line N: problem / fix:`, distinct
  exit codes. (R)
- `readiness.py` is deterministic and refuses mixed input well, but it cannot say what changed, prints no next
  action, exits 0 when blocked, and scores the guide's own dataset size as small. (C)
- `preflight.py` never imports the SDK (missing SDK is a reported FAIL or a deferred SKIP), installs nothing, and
  asks nothing; its output ends with a count rather than an action. (R)
- `calibrate_evaluator.py`'s scope refusal is prose on stderr that the agent hand-translates into a flag on the
  next command. (R)
- `sql_structure.py` is total on fuzzed input and stdlib-only, and has the two scoring bugs above. (C, ran)

Prose that could become script behaviour, so the agent runs a check instead of reading a rule (R):

1. `readiness.py --previous <json>` printing `changed: evaluation 33 to 83; unchanged: dataset, agent` - this
   is the mechanism behind the one-line "fixed, continuing" the owner asked for.
2. `preflight.py --max-first-run-rows 18` failing above it, plus the 28-row card sentence - the mechanism
   behind "do not enlarge".
3. `preflight.py --require sdk-version` exiting 1, replacing SKILL.md:805's prose requirement.
4. The calibrate scope refusal emitted as JSON under `--json`.
5. `sql_structure.py gold.jsonl` self-match before any paid call, replacing evaluation-and-dataset.md:26.

Structure: `readiness.py` splits naturally into AST route analysis (about 3,200 lines), cap registries (about
1,270), two renderers that duplicate the same hold, agent and blocker sentences, and the adapters; `calibrate_evaluator.py`'s
`run()` is 775 lines with four near-identical subprocess blocks. (R)

## 4. Size: what the customer receives

Tracked bytes at head:

| Area | Bytes | Note |
|---|---|---|
| Agent-facing guidance (GUIDE.md, SKILL.md, references, run-plan.md) | 504,689 | about 125K tokens; resident pair 107,369 |
| Shipped scripts | 1,156,111 | `readiness.py` 842,545 B, 17,436 lines, 269 functions, 56% docstrings and comments |
| `assets/sql_structure.py` | 50,060 | |
| Whole skill directory | 1.71 MB | what `npx skills add` installs |
| `tests/` | 4.03 MB | `test_skill_package.py` alone 1.55 MB; maintainers only |
| Clone on disk | about 20 MB | 8.5 MB is `.git`; README does not say the skills-add path is eight times lighter |

Per-document verdicts from the reviewers, each with no rule removed (estimates, not measured cuts):

| Document | Now | After | What moves or goes |
|---|---|---|---|
| SKILL.md | 99 KB | about 65 KB | cap-routing lookup table (:693-780, already emitted by readiness.py as `recommended_action`) to a reference; argv contract and agent-knobs rationale to component-creation.md; checkpoint framing (:969-1013) to three rules; next-action catalogue to run-safety.md |
| run-safety.md | 99 KB | about 45 KB | config-space schema to readiness `--help`; run-log schema to `validate_run_log.py`; git/ignore/0600 checks to preflight.py; removed-envelope history (:307-357) cut; four-way duplicates collapsed |
| sdk-execution.md | 139 KB | about 45 KB plus one shipped module | roughly 60 KB of fence 1 is customer-invariant machinery (ledger, door, retry sizing, wiring probe, fingerprint, cost readers) that every customer gets verbatim; ship it as a module under `scripts/` and leave only the adaptable surface in the document |
| evaluation-and-dataset.md + component-creation.md + glossary.md | 155 KB | about 85 KB | script behaviour prose (seam probe, calibration arithmetic, first-run subset rule 6) to script help; static-checker spec (component-creation.md:14.5 KB) to `readiness.py --agent-knobs` docstring; glossary card-line explanations to readiness output; anecdotes to a changelog |
| GUIDE.md | 8.4 KB | about 4.5 KB | restated mandates to pointers, per CLAUDE.md:27-32 |

Net: roughly 505 KB of guidance to about 245 KB, plus one shipped module. The guidance-budget ledger under
`tests/guidance_budget/` (91 entries, 285 KB) would record the prune.

The structural point behind the numbers: the repository carries product code inside markdown. The spend
ledger, the door, the wiring probe and the readiness scorer are code every customer runs unchanged, and they are
delivered as prose to be regenerated (the fences) or as one 17,000-line script. Moving the fence machinery into a
module and cutting the scripts' prose share would remove most of the weight without touching a rule, and it would
give the agent a short document whose every line is either a rule or something it must adapt.

## 5. Refuted or downgraded reviewer claims

- "GUIDE.md:139-140 has zero counterpart in the skill" - refuted: sdk-execution.md:2506 carries it. Kept as a
  duplication finding (17), not a missing rule.
- "Stop is not a letter" (SKILL.md:973) versus "`C.` is stopping; every one of them keeps a letter"
  (run-safety.md:771) - downgraded from contradiction to clarity: SKILL.md:975 bounds its sentence to one menu
  for one fault, so two menus have opposite letter rules by design and an agent has to notice which menu it is in.
- The held-out timing "contradiction" (20) - kept as plausible: the three passages may describe a generated
  dataset, a large existing dataset and the row-review hold respectively; the documents do not say so.
- Two-questions-on-the-pre-spend-card (run-safety.md:644) - downgraded to P2: the text folds the cap question
  into the card's routes rather than adding a second question.

## 6. Suggested order

1. Rules PR, under 1 KB of text: findings 1 to 6, 8, 10, 11, 12, 13, 16, plus the two resident paragraphs
   proposed under Q1 and Q3. Every line is a correction or a deletion, so the guidance budget falls.
2. Consolidation PR: findings 17 to 21 and 25; one home per rule, GUIDE and glossary reduced to pointers and
   definitions.
3. Scripts-correctness PR: findings 26, 27, 30, 31, with a re-copy note for `sql_structure.py`; then the
   `--previous` and `--max-first-run-rows` mechanisms, because they are what let the two resident paragraphs from
   step 1 be enforced rather than read.
4. Restructure PR: the sdk-execution machinery into a shipped module, script-behaviour prose into script help,
   and a readiness scorer that is not 17,000 lines. This one changes what the agent does and needs the
   behavioural harness run against it.

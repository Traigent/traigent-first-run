# Readiness scoring: what to borrow from established statistics

**Date:** 2026-07-29
**Question (from the CTO):** rather than inventing a scoring method from zero, what established
statistical methods already handle the events we score — outliers, label noise, precision, evaluator
agreement — and which of them should `scripts/readiness.py` adopt?

**Short answer:** the current model is not wrong, but it is a *bespoke composite indicator* whose
individual measurements are hand-rolled where standard, citable methods exist. Two of its numbers are
statistically misleading in opposite directions, and both have textbook fixes:

- It **understates** precision, because it treats a config comparison as two independent samples when
  it is a *paired* comparison on the same rows.
- It **overstates** the winner, because it never accounts for selecting the best of N trials — and
  the literature is explicit that this bias is largest exactly in our regime (small n, high noise,
  near-ties).

Everything else in this report is a smaller upgrade: replacing a hand-picked threshold with a
standard statistic, so the number is interpretable and defensible rather than invented.

---

## 1. Name what the score already is

The score is a **composite indicator**: sub-indicators normalised to a common range, weighted
(40/35/25), linearly aggregated, then post-processed by ceilings. That is a well-documented
construction with its own methodology handbook (OECD/JRC), and reading our design against it explains
the one part of ours that feels like a hack.

**Linear aggregation implies full compensability** — a high evaluation pillar can pay for a broken
dataset. We clearly do not want that, which is exactly why the cap ladder exists: caps are a
non-compensatory device bolted onto a compensatory aggregation.

The handbook's own answer to that need is **geometric aggregation**, which "entails partial
(non-constant) compensability and rewards more those [units] with higher scores" — a low pillar drags
the composite down in a way no other pillar can fully offset, without any special-case rule. Where
dimensions must not substitute *at all*, it points to non-compensatory multi-criteria methods.

**What this buys us:** most of the cap ladder becomes a property of the aggregation rather than a list
of hand-written exceptions. A geometric mean of (dataset, evaluation, agent) cannot return 93 when the
dataset pillar is 30, so `dataset-fully-synthetic`-style ceilings stop carrying the whole load. Caps
would remain only for genuine *disqualifiers* (a broken evaluator, a leaking split) rather than for
"this pillar is weak".

**Also from the handbook, and cheap:** *sensitivity analysis*. Our own docs concede the weights are "a
judgement call". The standard practice is to report how the result moves under weight perturbation —
for us, one line: "this project scores STRONG under any weighting between 30/30/40 and 50/35/15", or
the honest opposite, "the band flips to WORKABLE if the dataset weight rises above 45%".

---

## 2. The two numbers that are actually misleading

### 2a. Precision: we are measuring the wrong comparison (understates power)

`size_points` bands on the standard error of a proportion, `SE ≤ 0.5/√n`. That bound is right for
estimating *one* accuracy in isolation, and it is the conservative worst case (p = 0.5).

But the question a first run answers is **not** "what is config A's accuracy" — it is "**is B better
than A**", measured on *the same rows*. That is a paired design, and the paired difference has
variance `Var(A) + Var(B) − 2·Cov(A,B)`. Because two configs of the same agent agree on most items,
the covariance is large and the paired standard error is **much** smaller than the unpaired one we
report. We are telling users their 30-row set gives ±9pp when the comparison they care about may
resolve several times finer.

**Established methods, in increasing cost:**

| Method | Use |
|---|---|
| **McNemar's test** | The standard test for two classifiers on the same binary-scored items. Uses only the discordant pairs (A right/B wrong, A wrong/B right) — which is precisely why it is more powerful here. |
| **Paired bootstrap** | Resample rows with replacement, recompute the *delta*, report a percentile CI. Assumption-light, works for any scoring function including continuous and rubric scores, ~20 lines, no dependency. |
| **Wilson / Agresti–Coull interval** | For any single reported accuracy. The Wald/normal interval we imply behaves badly at small n and near 0 or 1; Wilson is the standard recommendation and is a closed form. |
| **Minimum detectable effect** | Invert the power calculation: "with 30 paired rows you can detect a ~Xpp improvement at 80% power." This is the number a user actually wants before spending. |

**Recommendation:** report a **paired** precision figure and frame the power sub-score as an MDE
("this dataset can detect improvements of about 8 points or larger"), not as a per-result noise band.
It is both more honest and more useful, and it *raises* scores for legitimately-sized datasets we
currently under-credit.

### 2b. The winner's curse: we never account for picking the best of N (overstates the result)

The enhanced run tries 10–13 configurations and reports the best. Selecting on the same data you
measure on biases the measurement upward: extreme results are more likely to be selected even when
the extremity is noise. The literature calls this the winner's curse, and states plainly that the bias
"is largest in regimes with low signal-to-noise ratios: small sample sizes, large noise, and
near-ties" — **all three describe a first run** (18–30 rows, ±7–16pp, closely-spaced configs). There is
current work applying exactly this correction to LLM benchmarking.

Our readiness card quantifies per-result noise and says nothing about this at all.

**The good news:** the guide already has the structurally correct answer — the untouched holdout after
the winner is chosen *is* sample splitting, the standard decoupling of selection from estimation. What
is missing is (1) saying so, and (2) sizing it: the holdout must be large enough to confirm the winner
after the curse, and our power sub-score never asks that question of the holdout specifically.

**Established options:** nested cross-validation (correct, too expensive for a first run),
sample-splitting / cross-fitting (what we do — keep it, name it), and shrinkage / empirical-Bayes
correction of the reported delta (cheap, honest, and would let the report say "observed +12pp,
selection-corrected ~+8pp").

**Recommendation, in priority order:** (1) state that the holdout exists to defeat selection bias;
(2) require a minimum holdout size derived from the trial count, not just from the row count; (3)
optionally report a shrunk estimate beside the raw delta.

---

## 3. Replacing hand-rolled measures with standard ones

### Evaluator calibration → inter-rater reliability

**Now:** four bespoke probes blended as `0.5·mean + 0.5·worst`, plus two pass/fail gates.

**Established:** an evaluator is a *rater*, and rater quality has a mature toolkit — **Cohen's kappa**
(two raters), **Fleiss' kappa** (more than two), **Krippendorff's alpha** (any measurement level,
tolerates missing data), **ICC** for continuous scores. All correct for agreement expected by chance,
which our blend does not: a scorer that agrees with the gold 80% of the time on a binary task where
the majority class is 80% has learned nothing, and we would score it well.

**What it buys:** a citable, interpretable number with published interpretation bands, and chance
correction. Worth keeping our gates on top — kappa cannot express "returns a constant", and that
must remain a disqualifier.

### Difficulty spread → item analysis

**Now:** 15 points for how many of four difficulty *labels* are present — a proxy for a property
nobody measured, and one that penalises real datasets (which rarely carry difficulty tags) while
rewarding generated ones (which always do).

**Established:** classical test theory measures difficulty *from responses*: **item difficulty**
(fraction of configs answering it correctly) and **item discrimination** (point-biserial correlation
between per-item score and total score). **IRT** (2PL) models difficulty and discrimination jointly.

**What it buys — the most actionable finding in this report:** discrimination identifies *which
specific rows are useless*. An item every config gets right, or every config gets wrong, contributes
zero information to the comparison; the report could say "9 of your 30 rows separate nothing — these
are the ones to replace." That is dramatically more valuable than a 0–15 tag-presence score, and it
also gives an evidence-based ceiling estimate. Note it requires per-item results, so it is a
*post-run* measure — a natural upgrade to the closing report rather than the opening gate.

### Output dominance → entropy

**Now:** `DOMINANT_OUTCOME_RATIO = 0.9`, minus 6 points. An arbitrary cliff: 89% loses nothing, 90%
loses 6.

**Established:** **normalised Shannon entropy** (or Gini impurity) over the outcome distribution gives
a continuous 0–1 balance measure, and the **majority-class baseline** is the directly interpretable
companion — "always answering *approved* scores 0.87, so your agent's 0.89 means almost nothing." That
second number is the one that makes a ceiling risk *obvious* instead of asserted.

### Label noise and outliers → confident learning and robust statistics

This is the part the CTO's question named directly, and where we are weakest: we detect degenerate
golds only by exact-match heuristics (empty, constant, scores right and wrong alike).

**Established:**

- **Confident learning** (`cleanlab`) is the standard data-centric method for finding *mislabelled*
  examples: it estimates the joint distribution of observed vs latent labels from model confidences
  and prunes by ranking, with provable noise-estimation guarantees even from an imperfect model, and
  is robust to sparse noise. Applied to our case, the "model" is the agent's own per-row outputs — so
  after a run we can rank rows by "probably a wrong expected answer".
- **Robust univariate outliers:** modified z-score on the **median absolute deviation**, or Tukey/IQR
  fences — both resistant to the outliers they are detecting, unlike a mean/σ z-score.
- **Multivariate / embedding outliers:** **Isolation Forest**, **local outlier factor**, or
  Mahalanobis distance for finding inputs unlike the rest of the set (which are exactly the rows a
  first run should keep, and the rows a naive dedup pass would delete).

**Caveat that decides the sequencing:** all three need either embeddings or per-row model outputs, so
none belongs in the zero-cost opening gate. They belong in the closing report and in the curation
advice, which is where the guide already promises "keep, drop, relabel, or add a harder sibling".

### Provenance → an existing vocabulary

Our new `provenance` / `output_provenance` fields are a miniature datasheet. **Datasheets for
Datasets** (Gebru et al.) and Google's **Data Cards** already define the sections — motivation,
composition, collection process, preprocessing — and adopting their field names where they fit costs
nothing and makes our declarations legible to anyone who has met the standard.

---

## 4. Ranked recommendation

| # | Change | Value | Effort | Where |
|---|---|---|---|---|
| 1 | Paired precision (McNemar / paired bootstrap) + MDE framing | Fixes a systematic under-statement; more useful number | M | `size_points`, closing report |
| 2 | Name and size the holdout as selection-bias protection | Fixes the one unaddressed over-statement | S | guide + power sub-score |
| 3 | Normalised entropy + majority-class baseline for dominance | Removes an arbitrary cliff; adds the interpretable companion | S | `preflight.py` |
| 4 | Wilson interval for any single reported accuracy | Correct at small n and at the extremes | S | reporting |
| 5 | Kappa / Krippendorff for evaluator agreement, gates kept on top | Chance-corrected and citable | M | `calibrate_evaluator.py` |
| 6 | Item discrimination in the closing report | Names the useless rows — highest actionability | M | post-run |
| 7 | Geometric aggregation + weight sensitivity line | Makes non-compensability principled, shrinks the cap ladder | M | `readiness.py` |
| 8 | Confident learning for suspected label errors | Standard method for the "wrong gold" problem | L | post-run, optional dep |
| 9 | Datasheet field names for provenance | Free legibility | S | docs |

Items 2, 3, 4 and 9 are small and self-contained; 1 and 7 are the two that change the model's
character and deserve their own before/after comparison over a corpus of cases whose expected
band is known in advance.

---

## 5. What we should deliberately *not* adopt

- **Nested cross-validation.** Correct for the winner's curse and far too expensive for a run whose
  entire point is one sitting.
- **Full IRT calibration.** Needs many "respondents" (configs) per item; we have 10–13.
- **Multiple-comparison corrections (Bonferroni/BH) on the trial set.** Tempting, but the goal is
  *selection*, not *hypothesis testing* on every arm; sample splitting is the right tool and we
  already have it.
- **Imputing missing sub-scores.** Our "unmeasured is excluded, weight redistributed, coverage
  reported" is already the defensible available-case treatment. Imputation would invent evidence,
  which is the one thing this score must never do.
- **A single blended data-quality number.** The existing decision to report span, resolution and
  coverage separately rather than one knob score is correct and should be extended, not reversed:
  "your sweep covers 10% of the useful range" beats any composite.

---

## 6. Two honest limitations of this report

1. **Nothing here is measured against our own data yet.** Every claim is about method suitability, not
   about how much a given change would move real scores. Items 1 and 7 in particular need a
   before/after run over a corpus of cases whose expected band is known in advance, so that a change
   of model character can be seen rather than argued. Confirm that corpus actually covers the shapes
   a change touches — a suite with no example of the shape you changed reports "nothing broke", which
   is not the same claim as "the new behaviour works".
2. **The opening gate must stay free.** Several of the strongest methods (confident learning, item
   discrimination, embedding outliers) need model outputs or embeddings and therefore cost money or
   time. They are closing-report upgrades. Any proposal that quietly moves paid work before the
   approval gate is wrong regardless of its statistical merit.

---

## Sources

- [Handbook on Constructing Composite Indicators: Methodology and User Guide (OECD/JRC)](https://www.oecd.org/en/publications/handbook-on-constructing-composite-indicators-methodology-and-user-guide_9789264043466-en.html)
  — aggregation and compensability, weighting, sensitivity analysis
- [Tools for Composite Indicators Building (JRC)](https://publications.jrc.ec.europa.eu/repository/bitstream/JRC31473/EUR%2021682%20EN.pdf)
- [cleanlab — data-centric label-error detection](https://github.com/cleanlab/cleanlab) and
  [confident-learning classification docs](https://docs.cleanlab.ai/stable/cleanlab/classification.html)
- [An Empirical Study of Automated Mislabel Detection in Real World Vision Datasets](https://arxiv.org/pdf/2312.02200)
- [Towards Reliable LLM Evaluation: Correcting the Winner's Curse in Adaptive Benchmarking](https://arxiv.org/pdf/2605.05973)
- [Valuing Winners: When and How to Correct for Selection Bias in Randomized Experiments](https://arxiv.org/pdf/2605.18887)
- [The Winner's Curse in Machine Learning](https://accountablealgorithm.substack.com/p/the-winners-curse-in-machine-learning)
- [Nested Cross-Validation in Machine Learning](https://www.emergentmind.com/topics/nested-cross-validation)

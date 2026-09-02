#!/usr/bin/env python3
"""Static, zero-call preflight for a Traigent first run.

This command reads local files and installed-package metadata only. It never imports
user modules, executes an agent or evaluator, contacts an LLM provider, contacts
Traigent, or consumes optimization quota.

Use ``calibrate_evaluator.py`` separately to execute evaluator probes.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import stat
import sys
import traceback
from collections import Counter
from dataclasses import asdict, dataclass
from fractions import Fraction
from importlib.metadata import PackageNotFoundError, files, version
from pathlib import Path
from typing import Any, Iterable, Sequence

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
SUPPORTED_PYTHON_MIN = (3, 11)
SUPPORTED_PYTHON_MAX = (3, 14)
# The release this walkthrough was measured on, and the one its own
# requirements file installs. It is a statement about what was tested, NOT a
# requirement: an exact-equality gate here refused every other release,
# including releases NEWER than this one, so a customer who had kept the SDK
# up to date was turned away by the product for being ahead of it. The SDK
# ships faster than this constant can be bumped, so equality guaranteed the
# guide would break on every release until somebody edited this line.
TESTED_TRAIGENT_VERSION = "0.26.0"
# The modules every code block in this guide imports without first checking
# for them (`references/sdk-execution.md`, the wrapper's import block).
#
# This is what the old exact-version comparison was really standing in front
# of, and the only failure it caught that mattered: the name `traigent` on the
# package index also carries an obsolete `0.0.1` placeholder release, which
# `run-safety.md` records that resolution can select on an unsupported
# interpreter. That release ships eight recorded files, no optimizer, and
# prints a "placeholder" line on import - measured by installing it. Every
# real release from 0.10.0 onward ships both modules below, measured by
# reading the wheel of every release the index offers, so no version number
# separates a working SDK from a broken one and a version comparison was the
# wrong question. Asking for the modules is the right one: it refuses the
# placeholder, accepts every real release, and cannot go stale on a bump.
#
# Read from the installed distribution's own file record - never imported.
# Importing to find out what is installed would execute a third-party package
# inside a check whose whole contract is that it does not.
# Held as path segments and joined at the point of use. Written out as whole
# strings, a package-name-then-directory pair reads to this repository's own
# public-package scan as a reference to a private repository named after that
# directory, which is that check doing its job on a shape that looks like one.
SDK_DISTRIBUTION = "traigent"
REQUIRED_SDK_MODULES = (
    ("api", "decorators.py"),
    ("core", "objectives.py"),
)
# Where a Python project says what it depends on. Read as text, never parsed
# as TOML and never executed - the question is only whether a name appears.
DEPENDENCY_DECLARATIONS = ("requirements.txt", "pyproject.toml", "setup.py")
# `traigent` as a requirement name in its own right. The boundaries are what
# keep a longer package name that merely starts the same way, a dotted
# attribute, and a `traigent.ai` link or e-mail address from counting as a
# dependency on the SDK. A requirement is never followed by a dot - the shapes
# are the bare name, a version specifier and an extras bracket - so excluding
# one costs nothing and drops the most likely false reading, which is a
# customer who linked our website.
TRAIGENT_REQUIREMENT = re.compile(r"(?<![\w.-])traigent(?![\w.-])", re.IGNORECASE)
# How long a word sequence has to be before repeating it means anything.
#
# The comparison below is Jaccard over overlapping n-word sequences, not over
# word sets. The set comparison this replaced was ORDER-BLIND, which is the
# defect (traigent-first-run#170): "the cat sat on the mat" and "the mat sat on
# the cat" have identical word sets and scored 1.000, so a corpus that varies
# word order on purpose - a perfectly ordinary robustness set - read as
# duplicated. As sequences that pair scores 0.143.
#
# 3 because it is the shortest n that actually removes the defect. Source:
# `StaticPreflightTests.test_a_reordered_sentence_is_not_a_repeat`, applying
# each candidate shingle length to its two literal sentences: n=2 scores 0.667,
# which is still
# a near-duplicate at any threshold this check could carry, and n=3 scores
# 0.143. Larger n keeps working - n=4 scores 0.000 - and costs sensitivity
# everywhere else, because one changed word destroys n sequences rather than 3,
# so the shortest n that works is the one that gives up least.
NEAR_DUPLICATE_SHINGLE = 3
# DERIVED, and not the 0.9 it replaces. Under sequences this number controls
# exactly one thing a reader can check for themselves: the shortest row at
# which ONE changed word still counts as a repeat. Source: `shingle_set`, on
# unique L-token rows whose token L//2 is replaced with `different`, sweeping
# L upward -
# 0.50 -> 11 words, 0.60 -> 14, 0.65 -> 17, 0.70 -> 19, 0.75 -> 23, 0.80 -> 29,
# 0.90 -> 59 - against the shipped word-set 0.9, which crossed at 19.
#
# 0.7 is the value that HOLDS that crossing at 19 words. So the switch changes
# what the check knows about word order without changing how sensitive it is to
# edits, and the one behavioural change is the one that was decided. Inheriting
# 0.9 would have moved the crossing to 59 words and made the check three times
# more inert while looking like it had not moved at all.
#
# What it does NOT reach is template repetition - one frame with the entity
# swapped, "...customers in France..." against "...in Germany..." - which
# scores 0.333 at 8 words here and scored 0.778 as word sets. Neither metric
# catches it and no threshold separates it from "what is 2 + 2" against "what
# is 3 + 3"; #170 records that as a limit of word overlap, not of this number.
NEAR_DUPLICATE_THRESHOLD = 0.7
# How many near-duplicate pairs the scan will collect before it stops. A display
# bound, not a limit on what is checked: the emit prints ten, and a dataset with
# a thousand near-duplicate pairs has already answered the only question this
# check asks. Bounded so one very repetitive dataset cannot materialize millions
# of tuples.
MAX_NEAR_DUPLICATE_PAIRS = 1000
# A ceiling on the WORK the near-duplicate join may do - never on the number of
# rows it will look at. The join below is exact, so this bounds the datasets it
# cannot finish, not the ordinary path. Reaching it cannot produce a clean
# result: the caller emits SKIP, and readiness reads a SKIP as unchecked.
#
# This replaced a 500-row ceiling above which the check emitted SKIP and stopped
# running. Nothing downstream distinguished that SKIP from a pass, so every
# dataset over 500 rows silently lost near-duplicate detection - precisely the
# size at which duplicates become likely (traigent-first-run#151).
#
# COUNTED IN SEQUENCE OPERATIONS, and that is the correction. It used to count
# distinct candidate PAIRS, which is not what the loop spends: a pair costs one
# posting-list step to find and then a set union and intersection over both
# rows' whole sets, so a row of 300 words costs 600 units where a row of 12
# costs 24. Bounding the pair count therefore bounded nothing on exactly the
# datasets that are slow. Measured through `near_duplicate_pairs` on 2,000
# RAG-shaped rows of 300 tokens: 1.7M candidate pairs - 34% of a 5,000,000 pair
# budget, so it never fired - and 1.03 BILLION token operations, which ran for
# 45 s with no output and no timeout and then answered PASS. Trunk took 0.24 s
# on the same file.
#
# The number is derived from wall clock and nothing else, and it moved from 60M
# because the unit under it changed. Word sets sustained 15-22M operations per
# second; sequence sets sustain 4.0-9.5M across the shapes measured (2,000x300
# with 20 repeated frames, 2,000x50, 3,000x120, 5,000 rows over a 60-word
# vocabulary), because a set of sequences is larger than a set of words and each
# member costs more to hash. At that rate 60M would have been six to fifteen
# seconds - the old comment's "three to four" would have quietly become false
# while the constant sat unchanged - and 15M is about two to four seconds.
#
# Lowering it costs no ordinary dataset anything, which is why the wall-clock
# promise wins over the larger figure. Sequences are far rarer than words, so
# the index admits far fewer candidates: 2,000x300 rows spend 964M operations as
# word sets and reach this bound, and 0 as sequences. The shapes that DO spend
# real work here are ones full of genuine repeats, and those reach
# MAX_NEAR_DUPLICATE_PAIRS first.
#
# What this bound does NOT cover, stated because the number above is a
# wall-clock promise and would otherwise be read as the whole one. `work`
# counts posting steps and pair comparisons. It does not count the fixed cost
# of ranking every distinct sequence in the dataset and sorting each row's
# prefix, which is roughly linear in total sequences and therefore in dataset
# size. On 2,000 rows of 300 words `work` is 0 and that fixed cost is the
# whole wait, so this constant is not what decided it. The seconds themselves
# are a property of the machine and are not restated here - the ratio is the
# claim, and the absolutes for one machine are in the table on
# `MAX_NEAR_DUPLICATE_SHINGLES` below. Linear, predictable and proportional to
# the file the user handed over - which is why it is left uncounted rather than
# folded in at a second, incompatible unit price. The quadratic half is the
# half that needs a ceiling, and that is the half this counts.
#
# And it does not cover MEMORY, which is the other half of that fixed cost and
# the more dangerous one. The sequences this ranks are held all at once, so the
# same linear growth that is merely "predictable" in seconds is unbounded in
# bytes: 16,000 rows of 300 words spend 0 operations here, finish `complete`,
# and peak at about 36x the file. `MAX_NEAR_DUPLICATE_SHINGLES` is the ceiling
# on that, checked before any of it is allocated, and the two bounds are not
# interchangeable - this one cannot see the memory at all, because on the data
# that costs the most memory it reads zero.
#
# Re-derive it if the loop's inner work changes; do not move it because a
# dataset wanted more.
MAX_NEAR_DUPLICATE_WORK = 15_000_000
# A ceiling on the MEMORY the near-duplicate scan may take, counted in the word
# runs it would have to hold. The bound above counts operations and is a
# wall-clock promise; this one is a bytes promise, and the check needed both
# because the two do not move together. On high-diversity data `work` reads 0
# at every size - the index admits no candidates, so the counter never fires -
# while peak memory climbs with the file and nothing stops it (measured below,
# and the #170 review's finding).
#
# Memory fails differently from time, which is why this is not a nicety. A slow
# check still answers. A check the kernel kills answers nothing at all, and
# that is strictly worse than the SKIP this whole change exists to remove. Word
# sets degraded gracefully at 16,000 rows - they reached the work bound above
# and emitted SKIP - and sequence sets do not, so this is a bound the metric
# change created and owes.
#
# TARGET, stated first because the number is derived from it and means nothing
# without it: the scan may add at most 512 MB to peak RSS. Written against a
# 2 GB container - the low end of hosted CI, and Docker Desktop's default
# allocation - where the interpreter, the dataset itself and the rest of the
# run also need room. Half a gigabyte is already a quarter of that floor, and
# it is about where the failure stops being "slow" and becomes "killed".
#
# MEASURED, as peak RSS over the already-resident dataset, for the whole path:
# one set per row, then the frequency count, the ranking, and the posting
# index. RSS and not `tracemalloc`, because what an allocator kills a process
# over is its resident size, not the total Python objects charge for - the two
# are different quantities and must not be quoted into one column. High-
# diversity rows, which is the shape that costs the most and reads `work` 0.
# The seconds are one machine's and do not transfer; the bytes per run and the
# ratios are what the number below rests on.
#
#     shape                        runs      peak    bytes/run     wall
#      50,000 x 12 words        500,000    196 MB          393    2.1 s
#      12,000 x 50 words        576,000    201 MB          349    2.2 s
#       5,000 x 120 words       590,000    220 MB          373    2.3 s
#       2,000 x 300 words       596,000    196 MB          329    2.2 s
#         600 x 1,000 words     598,800    199 MB          333    2.3 s
#     150,000 x 4 words         300,000    133 MB          443    1.9 s
#     550,000 x 4 words       1,100,000    499 MB          453    7.7 s
#
# And the shapes this refuses, measured the same way: 8,000 x 300 words is
# 2,384,000 runs at 769 MB, and 16,000 x 300 is 4,768,000 at 1,538 MB - 36x the
# file, with `work` at 0 and `complete` True at both sizes.
#
# Bytes per run is flat in row LENGTH - 600 rows of 1,000 words and 50,000 of
# 12 cost the same - and rises only for very short rows, where each row's own
# set object is amortized over two or three members. 453 is the worst measured,
# so 512,000,000 / 453 = 1,130,242 runs, rounded DOWN to 1,100,000 because the
# rounding direction has to be the one that cannot exceed the target. Then
# measured back rather than left as arithmetic: 1,100,000 runs in that worst
# shape peaks at 499 MB, and that is the figure this ceiling is bought with.
#
# WHY RUNS, and not the three obvious alternatives - each rejected against the
# same measurements, not on principle:
#   * ROWS. 600 rows of 1,000 words and 50,000 rows of 12 cost 199 MB and
#     196 MB. A row cap is wrong by a factor of 83 between two datasets that
#     cost the same, and it is the exact shape of the 500-row ceiling #151
#     removed - and of the pair count `MAX_NEAR_DUPLICATE_WORK` replaced.
#   * INPUT BYTES. At a fixed 596,000 runs, 3.00 MB of short words and 10.20 MB
#     of long ones cost 185 MB and 206 MB. Memory per input byte spans 3.1x
#     across nothing but word length, because it is words that make runs.
#   * A LIMIT READ FROM THE HOST'S FREE MEMORY. Adaptive, and it would make the
#     same dataset pass on one machine and SKIP on another, with a SKIP nobody
#     can reproduce or argue with. A stated ceiling is worth more here than an
#     accurate one.
#
# WHAT IT COSTS, measured rather than hoped, because it is a real cost. The
# count is per row, so a dataset whose rows repeat each OTHER's runs is counted
# against a bigger index than it would really build. 6,000 rows of 300 words
# sharing one 290-word frame count 1,788,000 runs against 60,201 distinct, use
# 210 MB, and are refused here - and both trunk and this branch report 1,000
# pairs on that shape, so the refusal loses a real finding. Two things make
# that the right trade and neither is that it never happens: the exact figure
# is unknowable before building the index that is being bounded, and 1,100,000
# runs is 3,700 rows of 300 words or 92,000 rows of 14, which is far above a
# first-run dataset. Re-open this if a customer is refused here while their
# distinct run count is small - that is the one case this bound is wrong about,
# and it is wrong in the direction that answers instead of dying.
MAX_NEAR_DUPLICATE_SHINGLES = 1_100_000
# Answer dominance is defined against CHANCE, never against a fixed share of
# the rows. A fixed share cannot express what this check is for, because the
# same share means opposite things at different label counts: a top answer
# covering 50% of a yes/no set is perfectly balanced - the best a binary task
# can do - while 50% of an a/b/c/d set is twice what guessing gets
# (traigent-first-run#216). The quantity is therefore how far the
# majority-only baseline has already moved from chance towards a perfect
# score, for `k` distinct expected answers:
#
#     excess = (majority_share - 1/k) / (1 - 1/k)
#
# 0 for a balanced set at any `k`, 1 when one answer holds every row, and
# comparable across label counts - which is exactly the property the fixed
# share lacked. "Headroom", `1 - majority_share`, was considered and does not
# work: it is the arithmetic complement of the old rule rather than a different
# rule, and it hands balanced-binary and skewed-four-way the same 0.50.
#
# THE LINE IS RE-DERIVED, NOT PORTED ACROSS. 0.9 was a share of the rows and
# this is an excess over chance; they are different quantities, and carrying
# the number over is the mistake #216 was filed about. What 1/3 decides, in
# terms a reader can check against their own file, is the majority share it
# corresponds to at each label count:
#
#     k = 2   66.7%      k = 4   50.0%      k = 10   40.0%
#     k = 3   55.6%      k = 5   46.7%      k -> inf 33.3%
#
# It is pinned by the dataset shape the owner named as the defect - a four-way
# set whose top answer takes half the rows - and set at the LARGEST value that
# still catches it, so the reach past today's behaviour is the smallest the
# decision requires. It IS a reach: the old rule was silent on that dataset and
# this one is not. The false-red direction does not constrain the choice.
# Measured over 32 real datasets. Source:
# tests/test_preflight.py#StaticPreflightTests. The largest excess any of them
# reaches is 0.071 (a 28-row binary set split 53.6/46.4), so the line sits
# about 4.7x above the noisiest healthy data available to measure against.
#
# Held as a Fraction and compared against a Fraction built from row counts, so
# the boundary is settled by the counts and never by float rounding. Source:
# tests/test_preflight.py#StaticPreflightTests. Swept over every integer shape with k = 2..20,
# n = k..600 and every majority count, exact and float disagree on 200 of them,
# all at k = 2 and all in the same direction - a binary set split exactly 2:1
# (30/20, 300/200, 600/400) is ON the line, and float puts it at
# 0.33333333333333326 and stays silent. The four-way 50/25/15/10 set that pins
# the line is itself one of these boundary shapes.
DOMINANCE_EXCESS_THRESHOLD = Fraction(1, 3)
# The absolute share at which one answer is a ceiling whatever the answer space
# looks like. This is the SHIPPED rule, kept at the value and in the units it
# already had - a share of the rows, not an excess over chance - and demoted
# from "the rule" to a floor underneath it.
#
# BE PRECISE ABOUT WHAT IT EARNS, because an earlier revision of this comment
# was not. It was introduced to stop the regime gate withdrawing a finding the
# shipped rule made, and it did: with the gate that revision had, 100 rows of 90
# identical answers and 10 one-off ones crossed into "UNCHECKED", which pays -
# an unmeasured diversity sub-score outscores a flagged one on 449 of 512 scored
# dataset shapes, by up to 6 points of the DATASET pillar. That gate was wrong
# for other reasons and was replaced, and the replacement does not need rescuing:
# Source: `StaticPreflightTests.test_no_shipped_finding_is_withdrawn_at_any_dataset_shape`
# enumerates every integer answer-count partition from 2 through 40 rows; in
# that enumerated space this floor changes the
# verdict on ZERO shapes with two or more distinct answers. It is dead for every
# dataset a customer would call a dataset.
#
# It is kept anyway, for two things it still does. It holds "no shipped finding
# is ever withdrawn" as a property of the CODE rather than of an argument that
# has to be re-derived every time the gate moves - and that argument has already
# been wrong once here. And it is the only arm that answers when there is no
# baseline to be had: one distinct answer makes `1/k` 100%, so the chance
# sentence would read "against a 100.0% chance baseline for 1 distinct answers".
#
# It cannot make the check stricter, which is what makes it cheap to keep: the
# excess line corresponds to a share of `1/3 + 2/(3k)`, at most 66.7% at k = 2
# and falling from there, so any dataset this floor would flag was already
# flagged by the rule above it. Below the gate it is a DETECTOR and never a
# certifier - finding nothing at 90% is not a finding of no dominance, so the
# caller still reports SKIP.
DOMINANT_OUTCOME_SHARE = Fraction(9, 10)
MAX_REPORTED_DATASET_ERRORS = 5
MAX_REPORTED_DATASET_IDS = 10
WIRING_CHECK_EXAMPLES = 10
FIRST_RUN_TUNING_ROWS = 18
BOUNDED_SUBSET_ABOVE_ROWS = 100
EXPECTED_DIFFICULTIES = {"easy", "medium", "hard", "very-hard"}
REFERENCE_FREE_METHODS = {
    "llm-judge-pointwise",
    "llm-judge-pairwise",
    "llm-judge-rubric",
}
COMMON_OUTCOME_FIELDS = (
    "label",
    "category",
    "class",
    "intent",
    "decision",
    "status",
    "type",
    "grade",
)
# Any one name admits its vendor. The paid wrapper in `sdk-execution.md`
# carries this same inventory - it cannot import a script it is generated
# alongside - and the package suite compares the two, because a name added
# here and not there refuses a run this gate already admitted. The suite also
# compares both against `litellm`, which is what actually decides whether the
# call succeeds; comparing the two copies to each other can only find a name
# one of them is missing, never a name both are.
VENDOR_KEYS = {
    "OpenRouter": ("OPENROUTER_API_KEY", "OR_API_KEY"),
    "OpenAI": ("OPENAI_API_KEY",),
    "Anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
    # First word casefolded is the route key, and the route key is a literal
    # the client dispatches on - so this label is not free wording. Where the
    # client dispatches one route under two literals, the wrapper carries the
    # second as an alias; this report is per vendor and unaffected.
    "Gemini (Google)": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "PALM_API_KEY"),
    "Mistral": ("MISTRAL_API_KEY", "MISTRAL_AZURE_API_KEY"),
    "Cohere": ("COHERE_API_KEY", "CO_API_KEY"),
    "HuggingFace": ("HF_TOKEN", "HUGGINGFACE_API_KEY"),
}
BEDROCK_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION")


@dataclass(frozen=True)
class Result:
    check: str
    status: str
    detail: str
    metrics: dict[str, Any] | None = None


RESULTS: list[Result] = []


def emit(
    check: str, status: str, detail: str, metrics: dict[str, Any] | None = None
) -> None:
    """Record one check.

    `detail` is prose for a human. `metrics` carries the same facts as data so a
    downstream reader (the readiness scorer) can consume them without parsing
    the sentence - a wording change should never alter a score.
    """
    RESULTS.append(Result(check, status, detail, metrics))


class RowCountMismatch(Exception):
    """A row count this run published cannot be accounted for.

    Raised, never emitted as a check. A disagreement between the rows this run
    CLAIMS and the rows it actually counted is a defect in the check, not a
    finding about the customer's dataset, so it must not arrive on their card
    looking like one. Raising routes it through the boundary in `main`, which
    says whose defect it is and reports nothing as checked.
    """


# A row count is any metric whose key is `rows` or ends in `_rows`. Stated as a
# rule rather than a list because a list is what silently narrows: a check
# added later that counts rows is covered the moment it is written, and cannot
# be left out by nobody remembering this function exists.
FULL_ROW_COUNT = "candidate_rows"


def row_counts(metrics: dict[str, Any] | None) -> dict[str, int]:
    """Every row count in one check's metrics."""
    if not metrics:
        return {}
    return {
        key: value
        for key, value in metrics.items()
        if (key == "rows" or key.endswith("_rows")) and isinstance(value, int)
    }


def validate_row_count_bounds(results: list[Result]) -> None:
    """Refuse row counts that lack or exceed their published population.

    This run does not score rows - the SDK does, and `check_evaluator` says so
    on the card - so what can be checked here is the arithmetic this run states
    about the rows it read, and the checkable claim is stated rather than the
    stronger one implied.

    Two things are refused, and both are our defect rather than the customer's:

    * A count LARGER THAN THE FILE. Any count of rows that exceeds the number
      of rows the file actually had is a number reported over rows that were
      never there. That is the silent failure - a figure a customer could act
      on that no row supports - and it is arithmetic, so it is decidable here.
    * A count with NO POPULATION BESIDE IT. Several counts in one run are
      honestly different numbers: every line in the file, the lines carrying an
      input, the lines this method can score. A row EXCLUDED BY DESIGN is not a
      row silently dropped - but only if the exclusion is visible. Published
      alone, `12` reads as the whole file whether the file held 12 rows or 20.
      This is the same promise the bounded-subset disclosure makes when it
      names the subset size beside the full row count; the run keeps it in data
      as well as in prose.
    """
    published = [
        (result.check, key, value)
        for result in results
        for key, value in row_counts(result.metrics).items()
    ]
    if not published:
        return
    full = [value for _, key, value in published if key == FULL_ROW_COUNT]
    if not full:
        raise RowCountMismatch(
            "this run published "
            + ", ".join(f"{check}.{key}={value}" for check, key, value in published)
            + f" without publishing {FULL_ROW_COUNT}, so every count above "
            "reads as the whole file and none of them can be shown to be"
        )
    if len(set(full)) > 1:
        raise RowCountMismatch(
            f"this run published {len(set(full))} different values for "
            f"{FULL_ROW_COUNT} ({sorted(set(full))}), so the rows it read is "
            "not one number"
        )
    over = [
        f"{check}.{key}={value}" for check, key, value in published if value > full[0]
    ]
    if over:
        raise RowCountMismatch(
            f"the file held {full[0]} rows, but this run published "
            + ", ".join(over)
            + " - a count over rows the file did not contain"
        )


def key_present(value: str | None) -> bool:
    if value is None:
        return False
    stripped = value.strip()
    return bool(stripped) and not stripped.startswith("#")


def parse_env_file(path: Path) -> dict[str, str | None]:
    """Parse the small KEY=VALUE subset used by the first-run environment."""
    values: dict[str, str | None] = {}
    if not path.exists():
        return values
    for line_number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            emit(
                "env-file",
                WARN,
                f"{path}:{line_number} is not KEY=VALUE and was ignored.",
            )
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            emit(
                "env-file",
                WARN,
                f"{path}:{line_number} has an invalid environment variable name.",
            )
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def read_env(path: Path) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """Mirror python-dotenv's default precedence: process environment wins."""
    file_values = parse_env_file(path)
    effective = dict(file_values)
    effective.update(os.environ)
    source = (
        f"{path} + process environment" if path.exists() else "process environment only"
    )
    emit("env-source", PASS, f"{source}; process values take precedence")
    if not path.exists():
        emit(
            "env-file",
            WARN,
            f"{path} not found; create a minimal file before paid work",
        )
    return effective, file_values


def check_env_permissions(path: Path) -> None:
    """Require owner-only access before a local file receives secrets."""
    if not path.exists():
        return
    if os.name == "nt":
        emit(
            "env-permissions",
            SKIP,
            "POSIX mode checks are unavailable; protect this file with the platform ACL",
        )
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        emit(
            "env-permissions",
            FAIL,
            f"{path} mode is {mode:04o}; set owner-only mode 0600 before entering secrets",
        )
    else:
        emit("env-permissions", PASS, f"{path} mode is 0600")


def check_python() -> None:
    current = (sys.version_info.major, sys.version_info.minor)
    if SUPPORTED_PYTHON_MIN <= current < SUPPORTED_PYTHON_MAX:
        emit("python-version", PASS, sys.version.split()[0])
    else:
        emit(
            "python-version",
            FAIL,
            f"Python {current[0]}.{current[1]} is outside the supported 3.11-3.13 range",
        )


def sdk_module_path(parts: Sequence[str]) -> str:
    """One recorded module path inside the installed distribution."""
    return "/".join((SDK_DISTRIBUTION, *parts))


def installed_sdk_is_the_optimizer() -> bool | None:
    """Whether the installed `traigent` ships the modules this run imports.

    Metadata only. `files()` reads the record the installer wrote, so nothing
    here imports the package or runs a line of it.

    `None` is "the distribution listed no files", which happens and is not
    evidence of absence. A missing record must not read as a missing SDK, so
    the caller treats `None` the way it treats a present one.
    """
    try:
        recorded = files("traigent")
    except PackageNotFoundError:  # pragma: no cover - the caller checked first
        return None
    if not recorded:
        return None
    present = {str(path) for path in recorded}
    if all(sdk_module_path(parts) in present for parts in REQUIRED_SDK_MODULES):
        return True
    # Absence of the modules is only evidence when the record shows a package
    # to look in. An editable install (PEP 660) records a `.pth` redirect and a
    # finder module instead of the package tree, so the modules are on disk and
    # not in the record - reading that as "not the SDK" refuses a correct
    # install, and refuses it on the machine most likely to have one. The
    # question this can answer from metadata is narrower than it looks: does a
    # recorded `traigent/` package exist that does NOT carry the optimizer.
    # Anything else is unrecognised, and unrecognised is not a finding.
    package_prefix = SDK_DISTRIBUTION + "/"
    if any(path.startswith(package_prefix) for path in present):
        return False
    return None


def check_sdk(*, defer_missing: bool = False) -> None:
    """Is the Traigent SDK here, and is it the Traigent SDK?

    Deliberately not "is it the exact release we tested". See
    `TESTED_TRAIGENT_VERSION`: a newer release is the customer being current,
    not the customer being wrong, and refusing one is the worst first
    impression this guide can make. Every difference from the tested release
    is reported and none of them stops the run.

    The status stays PASS rather than WARN for a reason a reader should be
    able to check: `--strict` turns any WARN into exit 1, so a WARN here would
    reintroduce the stop this function exists to remove.
    """
    try:
        installed = version("traigent")
    except PackageNotFoundError:
        if defer_missing:
            emit(
                "sdk-version",
                SKIP,
                "traigent is not installed yet; verify it in the isolated environment after installation",
            )
        else:
            emit(
                "sdk-version",
                FAIL,
                "traigent is not installed in the active interpreter",
            )
        return
    if installed_sdk_is_the_optimizer() is False:
        emit(
            "sdk-version",
            FAIL,
            f"the installed traigent {installed} does not contain the "
            "optimizer or the evaluation options this run uses, so it is not "
            "the Traigent SDK - the package name also carries an old "
            f"placeholder release. Install traigent=={TESTED_TRAIGENT_VERSION} "
            "in this run's own environment",
            {"installed": installed, "is_optimizer": False},
        )
        return
    if installed == TESTED_TRAIGENT_VERSION:
        emit(
            "sdk-version",
            PASS,
            f"traigent {installed}",
            {"installed": installed, "tested": TESTED_TRAIGENT_VERSION},
        )
    else:
        emit(
            "sdk-version",
            PASS,
            f"traigent {installed}; this walkthrough was measured on "
            f"{TESTED_TRAIGENT_VERSION}, and nothing it does needs that exact "
            "release, so the run continues. Where these notes describe what "
            f"the SDK stores or sends, they describe {TESTED_TRAIGENT_VERSION}",
            {"installed": installed, "tested": TESTED_TRAIGENT_VERSION},
        )


def check_existing_traigent_use(root: Path) -> None:
    """Did this project already adopt Traigent before the walkthrough arrived?

    Asked because the walkthrough costs money and is deliberately a reduced
    form of the product: somebody who has already optimized this project would
    be paying a second time to be shown less. They should get to decide that
    with the fact in front of them.

    It reads the project's own dependency declarations and nothing else,
    because a declaration is the only signal here whose OWNER is unambiguous.
    The alternative - "is `traigent` importable" - cannot carry the claim:

    * It answers for one interpreter. The opening gate runs under the host
      `python3` in every case but one, so a project environment that has the
      SDK is invisible to it, and a machine-wide install shows up identically
      whether or not it has anything to do with this project.
    * Its provenance only holds before this run installs anything. After the
      dedicated environment exists, "the SDK is here" is as likely to be our
      doing as theirs.

    A declaration has neither problem. It belongs to the project rather than
    to an interpreter, and this run never writes one - the whole guide's
    writes are `traigent-runs/` and a `.gitignore` line - so a `traigent`
    requirement in these files was always put there by the customer.

    It is inventory, never a gate. The status is PASS whichever way it comes
    out, so nothing here can stop a run: a customer may well want a first run
    on a project that already lists the SDK, and refusing them on this
    evidence would be refusing them for having bought the product. The cost of
    reading it wrong is one extra sentence, which is the right cost for a
    signal this indirect.
    """
    declared: list[str] = []
    for name in DEPENDENCY_DECLARATIONS:
        path = root / name
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Unreadable is not "absent", but it is also not a finding, and a
            # first run must not stall on somebody's file permissions.
            continue
        # Comments are prose, and prose mentioning the SDK is not a dependency
        # on it. `setup.py` is read as text and never executed: running a
        # stranger's program to find out what it depends on is not a read.
        code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
        if TRAIGENT_REQUIREMENT.search(code):
            declared.append(name)
    if not declared:
        emit(
            "existing-traigent-use",
            PASS,
            "this project does not list traigent among its dependencies",
            {"declared_in": []},
        )
        return
    emit(
        "existing-traigent-use",
        PASS,
        f"this project already lists traigent in {', '.join(declared)}, so "
        "the SDK was set up here before this walkthrough started and this may "
        "not be a first run at all. The walkthrough is a shorter, guided "
        "version of what the SDK already does for you, and it still charges "
        "for its own baseline and its own search - the approval before any "
        "spending names that figure. Worth continuing to see the guided "
        "comparison, or to onboard a different project; worth stopping if "
        "this project is already tuned",
        {"declared_in": declared},
    )


def check_keys(env: dict[str, str | None]) -> None:
    available = [
        vendor
        for vendor, names in VENDOR_KEYS.items()
        if any(key_present(env.get(name)) for name in names)
    ]
    bedrock_present = [name for name in BEDROCK_KEYS if key_present(env.get(name))]
    if len(bedrock_present) == len(BEDROCK_KEYS):
        available.append("Bedrock")
    elif bedrock_present:
        emit(
            "provider-credentials",
            WARN,
            "Bedrock is reported here only when access key, secret, and region are all present; "
            "the AWS credential chain may still authenticate that route without them",
        )

    if not available:
        emit(
            "provider-credentials",
            WARN,
            "no LLM provider credential names are present; inspect the agent route separately. "
            "Bedrock signs through the AWS credential chain, so a shared profile, an SSO session "
            "or an instance role authenticates it with nothing set here. On a route whose "
            "credential is an environment variable, do not begin paid work until that route's "
            "credential is present",
        )
    else:
        emit(
            "provider-credentials",
            PASS,
            f"credential names are available for {', '.join(available)}; "
            "this inventory does not select or change the agent's provider route",
        )

    traigent_key = env.get("TRAIGENT_API_KEY")
    if not key_present(traigent_key):
        emit(
            "traigent-key",
            PASS,
            "not configured yet; required only for connected execution",
        )
    elif not traigent_key.strip().startswith("uk_"):
        emit(
            "traigent-key",
            WARN,
            "portal keys normally begin with uk_; verify the local paste",
        )
    else:
        emit("traigent-key", PASS, "portal key shape looks plausible")

    openrouter_key = env.get("OPENROUTER_API_KEY")
    if key_present(openrouter_key) and not openrouter_key.strip().startswith("sk-or-"):
        emit("openrouter-key", WARN, "OpenRouter keys normally begin with sk-or-")


def check_cost_settings(
    env: dict[str, str | None], file_values: dict[str, str | None]
) -> None:
    # The first-run launcher overwrites this legacy SDK variable from the three
    # approved first-run figures before it imports the SDK.  It never carries
    # authority for this walkthrough, whether it came from .env or the parent
    # process.  Validating it as an active cap would invent a protection that
    # the launcher deliberately replaces.
    raw_cap = env.get("TRAIGENT_RUN_COST_LIMIT")
    if key_present(raw_cap):
        emit(
            "cost-cap",
            SKIP,
            "TRAIGENT_RUN_COST_LIMIT is inventory only; each first-run paid process "
            "derives and sets its own cap from its approved figures",
        )
    else:
        emit(
            "cost-cap",
            PASS,
            "no per-optimization cap set here; each paid process derives its own from the "
            "approved figures it is launched with",
        )

    # A first run preserves an existing owner-owned .env. The documented wrapper
    # captures its approval figures before loading that file and then derives
    # its own per-process limit, so a preserved value here cannot authorize or
    # enlarge this run. Record it without asking the customer to alter unrelated
    # local configuration; the approval card, not this inventory, owns whether
    # the next paid process may start.
    persisted = [
        name
        for name in (
            "TRAIGENT_FIRST_RUN_COST_CEILING_USD",
            "TRAIGENT_FIRST_RUN_COST_SPENT_USD",
            "TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD",
            "TRAIGENT_RUN_COST_LIMIT",
        )
        if key_present(file_values.get(name))
    ]
    if persisted:
        emit(
            "cost-figures-in-file",
            SKIP,
            f"{', '.join(persisted)} preserved in .env; they do not authorize "
            "this first run, whose approved figures are supplied per paid process",
        )

    approved_in_file = file_values.get("TRAIGENT_COST_APPROVED")
    if key_present(approved_in_file) and approved_in_file.strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        emit(
            "cost-approved",
            SKIP,
            "TRAIGENT_COST_APPROVED is preserved in .env; it does not authorize a "
            "first-run paid process",
        )
    elif key_present(env.get("TRAIGENT_COST_APPROVED")):
        emit(
            "cost-approved",
            WARN,
            "TRAIGENT_COST_APPROVED is active in the process; confirm this is the approved paid process",
        )

    # Both names, because the SDK resolves its backend origin from either and
    # prefers them over the stored/default route. Naming one left the other as
    # an unreported way to point a paid, portal-tracked run somewhere the user
    # did not approve - and a connected run that reaches an unexpected backend
    # still looks connected.
    overridden = [
        name
        for name in ("TRAIGENT_BACKEND_URL", "TRAIGENT_API_URL")
        if key_present(env.get(name))
    ]
    if overridden:
        names = " and ".join(overridden)
        # The baseline forces the SDK backend-offline and drops the Traigent key
        # before importing it, including one loaded from .env. An override
        # therefore cannot move the baseline and is not a pre-baseline warning.
        # The connected approval must inspect it before it can decide where that
        # later run is recorded.
        emit(
            "backend-url",
            SKIP,
            f"{names} overridden; the local baseline reaches no backend, so verify "
            "the connected destination at its approval",
        )


def check_models(models: list[str]) -> None:
    if not models:
        return
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
    try:
        import litellm
    except ImportError:
        emit(
            "model-pricing",
            WARN,
            "litellm is not importable; local pricing checks skipped",
        )
        return

    for model in models:
        if not re.fullmatch(r"[A-Za-z0-9._:/-]+", model):
            emit(
                f"model-format:{model}",
                FAIL,
                "model id contains unsupported characters",
            )
            continue
        emit(
            f"model-format:{model}",
            PASS,
            "format accepted; liveness requires a separately approved provider check",
        )
        try:
            prompt_cost, completion_cost = litellm.cost_per_token(
                model=model,
                prompt_tokens=1000,
                completion_tokens=1000,
            )
        except Exception:
            emit(
                f"model-pricing:{model}",
                WARN,
                "no local price entry; do not claim a reliable estimate until pricing is resolved",
            )
        else:
            emit(
                f"model-pricing:{model}",
                PASS,
                f"local price map returned prompt={prompt_cost}, completion={completion_cost}",
            )


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def dataset_field_value(row: dict[str, Any], field_path: str) -> tuple[bool, Any]:
    value: Any = row
    for part in field_path.split("."):
        if not part or not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value


#: The split names whose rows a paid first run draws from. Read here rather
#: than spelled twice: the bounded draw and the tuning-size finding below ask
#: the same question of the same names, and two copies of this set are two
#: answers waiting to disagree about what "the tuning split" means.
TUNING_SPLIT_NAMES = frozenset({"tune", "tuning", "train", "search"})
#: What `drawable_distinct_inputs` counted over, in the customer's terms.
TUNING_SPLIT_SCOPE = "the tuning split"
DATASET_SCOPE = "this dataset"


def exact_input_identity(value: Any) -> str:
    r"""Two inputs are one question only when they are equal. Nothing looser.

    Deliberately NOT `normalized_identity`, and the difference decides money.
    That function reduces an input to `re.findall(r"\w+", ...)`, which throws
    away every operator and every mark: `is x > 5` and `is x < 5` reach it as
    one string, and so do `2 + 2 = ?` and `2 - 2 = ?`. That is the right
    trade where it is used - a leak between splits, or a duplicate WARN, wants
    to see past punctuation and is only ever advisory - and it is the wrong
    trade here, because this count SHRINKS a paid draw. Forty operator
    questions would be drawn as twenty, and the twenty dropped are real test
    cases the customer wrote. The walkthrough's own worked task is text to
    SQL, where the discarded characters are the discriminating tokens.

    So the identity that cuts a budget has no false positive by construction:
    equal values are one question under every reading anybody could bring, and
    unequal values are two. It over-counts a pair that differs only in
    trailing space, which costs one provider call; the alternative costs a
    question, and only one of those two errors can be found afterwards by
    reading the run report.
    """
    return value if isinstance(value, str) else stable_json(value)


def drawable_distinct_inputs(rows: list[dict[str, Any]]) -> tuple[int, str]:
    """How many different questions a bounded first run can draw, and from where.

    Two scopes, both of which were wrong here before and each in its own way.

    SCOREABLE, which `rows` already is: a row carrying no expected answer is
    not a row any configuration is compared on, so counting it inflates the
    bound past what the comparison reaches. That is traigent-first-run#356,
    one axis.

    TUNING-SCOPED, which is this function: the guide hands preflight the whole
    file, tuning and held-out together, so a count over every row answers a
    question about a population the draw never touches. On a 400-row file
    whose tuning split asks twelve questions and whose held-out ten ask ten
    more, counting the file returns twenty-two and the draw is proposed at
    eighteen - six rows per configuration, in every trial, that no comparison
    can use. Same defect, one axis over, which is why the population is named
    and returned rather than left implicit in whichever local list was nearest.

    Falls back to the whole scoreable set when no tuning split is declared,
    because then there is no other population: an undeclared split is a file
    the draw comes out of entire. The scope travels with the number so a card
    never prints a count without saying what it counted.
    """
    by_split: dict[str, set[str]] = {}
    unsplit: set[str] = set()
    for row in rows:
        identity = exact_input_identity(row["input"])
        split = row_metadata_value(row, "split")
        if split:
            by_split.setdefault(str(split).casefold(), set()).add(identity)
        else:
            unsplit.add(identity)
    tuning = {
        identity
        for name, values in by_split.items()
        if name in TUNING_SPLIT_NAMES
        for identity in values
    }
    if tuning:
        return len(tuning), TUNING_SPLIT_SCOPE
    everything = set(unsplit)
    for values in by_split.values():
        everything |= values
    return len(everything), DATASET_SCOPE


def first_run_row_count(usable_rows: int, distinct_rows: int | None = None) -> int:
    """Return the rows each paid first-run configuration scores.

    Bounded by the DIFFERENT questions the draw can reach, not only by how many
    rows the file holds. The agent produces one output per input, so a repeated
    input is scored the same way by every configuration and separates none of
    them: proposing eighteen rows to a split asking twelve questions proposes
    six calls per configuration, in every trial, that no comparison can use.

    The bound applies only where the bounded subset itself applies. Below
    `BOUNDED_SUBSET_ABOVE_ROWS` the run scores the whole dataset and there is
    no subset to cap, so a small repetitive file is reported at its real size
    rather than being quietly cut to its distinct count by a rule the guidance
    does not extend that far.

    `distinct_rows` is optional so that a caller holding only a row count still
    gets the old answer rather than a wrong one. Absent, the bound is the rows -
    which is what an uncounted file honestly supports.
    """
    if usable_rows <= BOUNDED_SUBSET_ABOVE_ROWS:
        return usable_rows
    if distinct_rows is None:
        return FIRST_RUN_TUNING_ROWS
    return min(FIRST_RUN_TUNING_ROWS, distinct_rows)


def normalize_dataset_row(
    row: dict[str, Any],
    input_field: str = "input",
    expected_field: str = "output",
    require_expected: bool = True,
) -> tuple[dict[str, Any] | None, str | None]:
    """Project explicitly selected fields into the local quality-check shape.

    This deliberately does not assert SDK compatibility. Exact dataset normalization
    belongs to the installed SDK's public validation and loading paths. A declared
    reference-free evaluator may project a missing expectation to ``None``.
    """

    if input_field == expected_field:
        return (
            None,
            "input and expected-output field paths must be different",
        )

    input_found, input_value = dataset_field_value(row, input_field)
    if not input_found:
        return (
            None,
            f"missing selected input field '{input_field}'",
        )

    expected_found, expected_value = dataset_field_value(row, expected_field)
    if not expected_found and require_expected:
        return (
            None,
            f"missing selected expected-output field '{expected_field}'",
        )
    if not expected_found:
        expected_value = None

    normalized = dict(row)
    normalized["input"] = input_value
    normalized["output"] = expected_value
    return normalized, None


def dataset_row_is_labelled(
    row: dict[str, Any], expected_field: str = "output"
) -> bool:
    """Report whether a normalized row carries a usable expected output.

    A row is unlabelled when the expected output is absent, JSON `null`, or a
    blank string; anything else is a label the evaluator can score against.

    The `is None` test reads the *raw* value on purpose. Stringifying first -
    `str(row.get("output", "")).strip() not in ("", "None")` - cannot tell a
    missing label from the legitimate one-word label "None", because Python
    renders the null as the same four characters. A two-class dataset whose
    negative class is literally "None" (a no-intent / none-of-the-above class,
    or a pandas round-trip) then had exactly the rows carrying that label - half
    the dataset - reported as unscoreable while the other class stayed labelled,
    which clamped the power subscore and printed a false "N scoreable" marker.
    Do not collapse this back into a single stringified comparison.

    One definition, used by both the aggregate `labelled_rows` count and the
    per-split counts, so the two can never disagree about the same row.

    `expected_field` exists so the one definition also works on a RAW row, where
    the answer still sits under the user's own field name. The default keeps
    every normalized-row caller unchanged; the split loop passes the real field,
    because reading `row["output"]` off a raw row under `--expected-field answer`
    silently counts every answered row as unlabelled.
    """

    found, value = dataset_field_value(row, expected_field)
    if not found or value is None:
        return False
    return str(value).strip() != ""


def normalized_text(value: Any) -> str:
    text = stable_json(value) if not isinstance(value, str) else value
    return " ".join(re.findall(r"\w+", text.casefold()))


def normalized_identity(value: Any) -> str:
    """Normalize equality without collapsing distinct symbol-only values."""
    words = normalized_text(value)
    if words:
        return words
    text = value if isinstance(value, str) else stable_json(value)
    return text.strip().casefold()


# How many words of an input make up its task-family signature, counted from
# the first word that tells one row from another rather than from the first
# word of the row.
#
# TWO, and the number is the whole honesty of the check that reads it. One
# token collapses every `def` in a code corpus into a single family and the
# check can then never fire; three splits `def add(a, b)` from `def add(x, y)`
# and every row becomes its own family, which is the same silence reached from
# the other end. Two lands on the discriminating token in the shapes this guide
# actually meets: `def add` against `def is_even`, `select count` against
# `select name`, `translate to` against `summarise the`.
#
# WHERE the window starts is a separate decision and it is `family_offset`'s,
# because reading two words from position zero was wrong on the commonest shape
# a real dataset has. A corpus whose rows all open `Calculate this question:`
# has one signature for every row, so the check reported PASS - "the split does
# not follow the task families" - over a split that partitioned by family
# underneath the boilerplate. A confident wrong answer, not a silence, and the
# instruction-prefixed corpus that produces it is the ordinary case rather than
# a corner. Source:
# tests/test_preflight.py#ASplitDrawnAlongTheTaskFamiliesTests.test_a_shared_opening_does_not_hide_the_families_behind_it.
#
# It is a signature and not a classifier, and the difference is stated because
# the check is only as honest as the thing it infers. Rows sharing these two
# words are not proven to be one task; rows differing in them are not proven to
# be two. What the signature CAN support is the one comparative question
# `dataset-split-family` asks - does the tuning/held-out line fall exactly where
# these groups do - and it answers that without naming any group a task.
SPLIT_FAMILY_TOKENS = 2
# How much of a corpus has to share a leading word before that position is read
# as boilerplate and skipped.
#
# 0.9 rather than "every row", because a strict common prefix is decided by the
# single most unusual row: ninety-nine rows opening `Calculate this question`
# and one opening `Compute this question` share no prefix at all, and the whole
# window slides back to zero for one row in a hundred. Templated openings are
# templated by construction, and the mixed corpus is exactly the one this has to
# survive.
#
# Not lower than that either. A word that only nine rows in ten share is
# separating a tenth of the corpus, and a tenth is large enough to be a family
# in its own right under the two-row recurrence floor below - skipping it would
# discard the discrimination this check exists to find.
SPLIT_FAMILY_BOILERPLATE_SHARE = 0.9
# A signature has to recur before it is read as a family at all.
#
# Two, because one is not a group. Without this floor every dataset whose rows
# open differently - forty support tickets each starting with its own product
# name - is a dataset of forty one-row families, every family sits on exactly
# one side of any split by construction, and the check fires on every one of
# them. That is the false red the whole design has to refuse, and it is refused
# by requiring the grouping to exist before its boundary can be compared to
# anything.
SPLIT_FAMILY_MINIMUM_ROWS = 2
# How much of each side recurring families must account for before the split
# boundary is read against them.
#
# 0.8, and the argument is about what the remaining fifth may do rather than
# about the number. Below this the reading is drawn from a minority of the rows
# and the majority is one-off shapes the signature cannot speak for, so a "clean
# partition" would be a statement about the part of the dataset that happened to
# repeat. Requiring every row to belong would be the other error: one unusual
# row would disable a check on a corpus that is otherwise four clean families.
SPLIT_FAMILY_COVERAGE = 0.8


# How many input forms a finding names before it stops listing them.
#
# FOUR, on the same reasoning `dataset-ids` prints ten row numbers and stops: a
# reader checks a claim about their own data against examples, and a list long
# enough to scroll is one nobody reads. Four is two per side at the smallest
# split this check can fire on, which is the shape the sentence has to stay
# readable at.
SPLIT_FAMILY_FORMS_SHOWN = 4


def _form_sample(forms: Iterable[str]) -> list[str]:
    """The named forms a finding carries, ordered and bounded."""
    return sorted(forms)[:SPLIT_FAMILY_FORMS_SHOWN]


def _named_forms(forms: Iterable[str]) -> str:
    """Name the forms rather than counting them.

    "2 forms" is a number the reader cannot check against their own file;
    `add two, find the` is a list they can, and disagreeing with it is the
    whole point - this check reads leading words and never meaning, so the only
    thing that settles whether two forms are one task is a person looking at it.
    Materialized on the first line, and that is the bug this docstring exists
    to keep fixed. Counting the total and taking the sample are two passes over
    the argument; against a generator the first pass exhausts it, the second
    counts zero, and the "+N more" clause disappears - so the sentence would
    quietly claim the four it printed were all there was. A finding may run
    short of room and may never understate what it found. Both call sites pass
    a set today, which is exactly why this failed silently rather than loudly.
    """
    found = sorted(forms)
    shown = _form_sample(found)
    listed = ", ".join(f"'{form}'" for form in shown)
    remaining = len(found) - len(shown)
    return f"{listed} (+{remaining} more)" if remaining > 0 else listed


def family_offset(values: Sequence[Any]) -> int:
    """How many leading words say the same thing on nearly every row.

    The window the signature reads has to start where the rows begin to differ,
    not at word zero, and the reason is a corpus shape this guide meets
    constantly: an instruction prefix. `Calculate this question: add two
    numbers` and `Calculate this question: check if even` agree on their first
    three words, so a window at position zero reads one family for the whole
    file and the check answers PASS over a split that partitions by family
    three words later.

    Position by position, and it STOPS at the first word that discriminates
    rather than skipping every uninformative word it can find. A later
    agreement is a fact about that family - `case` recurring inside `def add
    case 3` says the family has a shape - and stepping over it would read the
    signature out of the row's serial number.

    Tolerant rather than strict, per `SPLIT_FAMILY_BOILERPLATE_SHARE`: a common
    prefix computed with `all()` is decided by the one row that opens
    differently.
    """
    token_lists = [normalized_text(value).split() for value in values]
    if not token_lists:
        return 0
    for position in range(max(len(tokens) for tokens in token_lists)):
        present = [tokens[position] for tokens in token_lists if len(tokens) > position]
        if not present:
            break
        _word, count = Counter(present).most_common(1)[0]
        if count < SPLIT_FAMILY_BOILERPLATE_SHARE * len(token_lists):
            return position
    # Every position agreed, so there is nothing to tell these rows apart at
    # all. Reading from zero is the honest answer: it produces one signature
    # for the corpus, which is what a corpus of identical openings IS.
    return 0


def family_signature(value: Any, offset: int = 0) -> str:
    """The leading form of one input, as the family signature it stands for.

    Empty when the input holds no words past `offset` - a row that cannot be
    given a signature is left out of the reading rather than grouped with every
    other row that could not either, which is how "unclassifiable" becomes a
    family.
    """
    tokens = normalized_text(value).split()[offset : offset + SPLIT_FAMILY_TOKENS]
    return " ".join(tokens)


def family_partition_finding(
    tuning: Sequence[Any], holdout: Sequence[Any]
) -> tuple[str, str, dict[str, Any]]:
    """Whether the tuning/held-out line falls exactly on the task-family line.

    `dataset-split` answers whether the two sides share an input, and a split
    drawn along task families passes it - being the STRONGEST form of disjoint
    is precisely the failure. A search tuned on `add`/`max_of` and measured on
    `is_even`/`fib` is not measuring generalization on the same task, and the
    held-out number is the one the run exists to produce.

    The neighbouring checks do not reach it either, and the gap is the shape of
    this one: `dataset-near-duplicates` looks for rows that are too SIMILAR and
    this defect is rows that are too DIFFERENT across a boundary, while
    `dataset-difficulty-coverage` reads a declared tag rather than an inferred
    form. The condition sits between "too alike" and "labelled unevenly".

    CLEAN PARTITION IS THE TRIGGER, and uneven proportions are not. A random
    split of a corpus with real recurring families essentially never partitions
    cleanly - ten families of three rows under a 70/30 split leave every family
    on one side with probability about 5e-5 - so the strong condition is what
    keeps ordinary data out of it. Flagging skew instead would put a red on
    every dataset whose families are not the same size, which is most of them.

    Returns the emit triple. SKIP where no family reading is available, because
    a check that stayed silent could not be told from one that passed, and
    readiness reads a SKIP as unchecked rather than as a clean bill.

    A count of families is deliberately NOT a precondition. One recurring form
    covering both sides is a family that crosses the boundary, which is exactly
    what PASS says - a genuinely single-family corpus is the case this check has
    nothing against, and refusing to answer for it would report "unchecked" over
    the cleanest evidence available. The two-family floor the WARN needs falls
    out of the coverage rule instead of being asserted beside it: with both
    sides accounted for and only one form recurring, that form is on both sides.
    """
    sides = {"tuning": tuning, "holdout": holdout}
    # Over BOTH sides at once, and that is load-bearing rather than tidy. A
    # window chosen per side would read the two halves at different positions,
    # and the only question this function asks is whether their signatures
    # coincide - which is meaningless once they are not the same measurement.
    offset = family_offset([*tuning, *holdout])
    signatures = {
        name: [
            signature
            for signature in (family_signature(value, offset) for value in values)
            if signature
        ]
        for name, values in sides.items()
    }
    counts: Counter[str] = Counter()
    for values in signatures.values():
        counts.update(values)
    recurring = {
        signature
        for signature, count in counts.items()
        if count >= SPLIT_FAMILY_MINIMUM_ROWS
    }
    metrics: dict[str, Any] = {"families": len(recurring)}
    if not recurring:
        return (
            SKIP,
            "no input form recurs, so no task family can be inferred to read "
            "the split against",
            metrics,
        )
    per_side = {
        name: {signature for signature in values if signature in recurring}
        for name, values in signatures.items()
    }
    covered = {
        name: sum(1 for signature in values if signature in recurring)
        for name, values in signatures.items()
    }
    thin = sorted(
        name
        for name, values in sides.items()
        if not values or covered[name] < SPLIT_FAMILY_COVERAGE * len(values)
    )
    if thin:
        named = " and ".join(f"{name} rows" for name in thin)
        return (
            SKIP,
            f"recurring input forms account for under "
            f"{SPLIT_FAMILY_COVERAGE:.0%} of the {named}, so most of what the "
            "split separates has no form to read it against",
            metrics,
        )
    shared = per_side["tuning"] & per_side["holdout"]
    if shared:
        forms = "form" if len(recurring) == 1 else "forms"
        return (
            PASS,
            f"{len(shared)} of {len(recurring)} recurring input {forms} "
            f"{'appears' if len(shared) == 1 else 'appear'} on both sides, so "
            "the split does not follow the task families",
            {**metrics, "shared_families": len(shared)},
        )
    return (
        WARN,
        f"every one of the {len(recurring)} recurring input forms appears on one "
        f"side of the split only - tuned on {_named_forms(per_side['tuning'])}, "
        f"measured on {_named_forms(per_side['holdout'])} - so the held-out "
        "score may not measure the task that was tuned. Read off the leading "
        "words alone and never from the meaning, so two wordings of one task "
        "read as two here; the rows above are what to check",
        {
            **metrics,
            "shared_families": 0,
            "tuning_forms": _form_sample(per_side["tuning"]),
            "holdout_forms": _form_sample(per_side["holdout"]),
        },
    )


def shingle_set(value: Any) -> set[str]:
    """One row as the SET OF OVERLAPPING WORD SEQUENCES it contains.

    A row of L words yields L - n + 1 sequences. Comparing these instead of the
    row's word set is what makes the similarity below order-sensitive, and the
    reasoning for n lives on `NEAR_DUPLICATE_SHINGLE`.

    Joined on a space, which is unambiguous because `normalized_text` keeps only
    runs of word characters, so no token can contain the separator. A joined
    string rather than a tuple because it is cheaper in both. Source:
    tests/test_preflight.py#StaticPreflightTests. Measured over
    2,000 rows of 300 words, 71.8 MB peak against 104.4 MB and 6.96 s against
    9.52 s for the identical 65.9M-operation join.

    A row SHORTER than n has no n-word sequences, and the two obvious answers
    are both wrong. Scoring it zero would make a repeated two-word row
    invisible - and a two-word row repeated forty times is real repetition.
    Falling back to its word set would make it comparable with nothing else: a
    set of words and a set of sequences are drawn from different universes, so
    every long row would score 0.0 against every short one whatever they say.

    So a short row contributes ONE sequence: itself, whole. Two short rows then
    score 1.0 when they are the same words in the same order and 0.0 otherwise.
    That is deliberately a different KIND of answer from the graded one longer
    rows get - below n words there is no "nearly", only "same" - and the
    glossary says so rather than leaving a reader to assume a smooth scale that
    silently stops.
    """
    tokens = normalized_text(value).split()
    if len(tokens) < NEAR_DUPLICATE_SHINGLE:
        return {" ".join(tokens)} if tokens else set()
    return {
        " ".join(tokens[start : start + NEAR_DUPLICATE_SHINGLE])
        for start in range(len(tokens) - NEAR_DUPLICATE_SHINGLE + 1)
    }


def near_duplicate_index_size(values: Iterable[Any]) -> int:
    """How many word runs the near-duplicate scan would hold, without holding them.

    The scan's memory is bounded by refusing datasets above
    `MAX_NEAR_DUPLICATE_SHINGLES`, and a bound is only a bound if it is consulted
    BEFORE the thing it bounds is allocated. That is this function's whole reason
    to exist: it walks the rows one at a time and keeps an integer, so the answer
    costs the tokenization and nothing that survives the loop - measured at 0.0 to
    0.2 MB over the resident dataset at every shape in the table on that constant,
    against the 133 MB to 1,538 MB the sets themselves take.

    Counted conservatively from token count rather than by calling
    `shingle_set`: constructing that set is the allocation this pre-check must
    prevent. A short non-empty row contributes one run; a longer row contributes
    at most `words - n + 1`. Repeated runs can make the real set smaller, so this
    remains the documented upper bound and can only refuse early.

    An upper bound on the index, not its exact size, because rows that repeat each
    OTHER's runs are counted once per row and stored once in total. The gap is
    measured and argued on `MAX_NEAR_DUPLICATE_SHINGLES`; it is in the direction
    that refuses too early rather than too late.
    """
    total = 0
    for value in values:
        text = value if isinstance(value, str) else stable_json(value)
        words = sum(1 for _ in re.finditer(r"\w+", text.casefold()))
        total += 0 if words == 0 else max(1, words - NEAR_DUPLICATE_SHINGLE + 1)
    return total


def near_duplicate_prefix(
    tokens: set[str], rank: dict[str, int], threshold: float
) -> list[str]:
    """The tokens of one row that must be indexed for an exact threshold join.

    Prefix filtering (Chaudhuri et al.): order every token by a global ranking,
    and two sets whose Jaccard similarity is at least `threshold` must share a
    token inside their prefixes. Suppose they do not, and let `w` be the
    lowest-ranked token they have in common. `w` sits outside at least one of
    the two prefixes, so every shared token sits in that set's suffix and the
    intersection is at most `size - prefix`, which is below `threshold * size` -
    contradicting the similarity. So a candidate pair can never be missed by
    looking only at prefixes, and the join stays exact rather than sampled.

    The length uses floor where the derivation uses ceil. Floor is never
    shorter, and a longer prefix only admits extra candidates that the exact
    Jaccard check then rejects - whereas a prefix one token too short drops real
    pairs silently. Binary floating point puts `0.9 * 10` at 9.000000000000002,
    so the rounding direction has to be the one that cannot lose a pair.

    Ranking rarest-first is what makes this cheap: the indexed tokens are the
    ones that share a bucket with almost nothing.
    """
    size = len(tokens)
    length = max(1, min(size, size - int(threshold * size) + 1))
    return sorted(tokens, key=lambda token: rank[token])[:length]


def near_duplicate_pairs(
    token_sets: Sequence[set[str]],
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
    *,
    limit: int | None = None,
    max_work: int | None = None,
) -> tuple[list[tuple[int, int]], bool]:
    """Find every pair of rows at or above `threshold` Jaccard similarity.

    Deliberately agnostic about what a row's set CONTAINS - "token" here is the
    prefix-filtering term for an indexed set member, not a claim that the
    members are words. That is why switching the check from word sets to
    sequence sets (`shingle_set`, traigent-first-run#170) needed no change in
    here at all: the join is exact for Jaccard over any sets, so the metric
    changed and the algorithm, its proof, and its bounds did not.

    Returns `(pairs, complete)` as 1-based row numbers. `complete` says whether
    the scan examined every candidate it needed to; it is the honest half of the
    answer, because an empty `pairs` means "no near-duplicates" only when the
    scan finished. The caller must not report an incomplete empty scan as a pass.

    Replaces a full pairwise scan that ran only below 500 rows. This one runs at
    any size and returns the same pairs - `tests/test_preflight.py` checks that
    against the pairwise scan on random datasets, because an index that silently
    misses pairs would be the same defect one layer down.

    The two bounds resolve from the module constants at call time rather than in
    the signature's defaults, which bind once at import and cannot then be moved.
    """
    limit = MAX_NEAR_DUPLICATE_PAIRS if limit is None else limit
    max_work = MAX_NEAR_DUPLICATE_WORK if max_work is None else max_work
    pairs: list[tuple[int, int]] = []

    # Rows whose input has no word characters at all ("?", "-", "..."). Their
    # union is empty, which the pairwise scan scored as similarity 1.0, so they
    # were all near-duplicates of each other. Kept, and computed directly rather
    # than through the index, because they share no token to be indexed under.
    empty = [index + 1 for index, tokens in enumerate(token_sets) if not tokens]
    for left in range(len(empty)):
        for right in range(left + 1, len(empty)):
            if len(pairs) >= limit:
                return pairs, False
            pairs.append((empty[left], empty[right]))

    frequency: Counter[str] = Counter()
    for tokens in token_sets:
        frequency.update(tokens)
    rank = {
        token: position
        for position, (token, _count) in enumerate(
            sorted(frequency.items(), key=lambda item: (item[1], item[0]))
        )
    }

    index_by_token: dict[str, list[int]] = {}
    work = 0
    for position, tokens in enumerate(token_sets):
        if not tokens:
            continue
        prefix = near_duplicate_prefix(tokens, rank, threshold)
        seen: set[int] = set()
        for token in prefix:
            postings = index_by_token.get(token, ())
            # Two charges, because there are two costs, and the old accounting
            # counted neither of them.
            #
            # Walking a posting list costs one step per entry whether or not
            # the entry is a candidate this row has already seen - charged here
            # in one O(1) step, before the walk, so the accounting itself is
            # not what makes this slow.
            work += len(postings)
            if work > max_work:
                return sorted(pairs), False
            for other in postings:
                if other in seen:
                    continue
                seen.add(other)
                # And the exact check costs a union and an intersection over
                # both rows' whole token sets. This is where the time actually
                # goes: 1.7M candidate pairs of 300-token rows is 1.03 billion
                # token operations, and counting the pairs alone said 1.7M.
                work += len(tokens) + len(token_sets[other])
                if work > max_work:
                    return sorted(pairs), False
                union = tokens | token_sets[other]
                if len(tokens & token_sets[other]) / len(union) >= threshold:
                    if len(pairs) >= limit:
                        return sorted(pairs), False
                    pairs.append((other + 1, position + 1))
        for token in prefix:
            index_by_token.setdefault(token, []).append(position)
    return sorted(pairs), True


# One question, two answers: was this written, or was it collected? Every token
# below is a spelling of one of those - "synthetic", "generated", "walkthrough"
# (the dataset this skill writes for its own demo) and "mock" are not different
# kinds of data, they are different words for data nobody observed.
#
# Prefix matching, not equality, because real tokens carry qualifiers:
# `synthetic-walkthrough`, `production-2026-q1`. An exact `== "synthetic"` test
# once returned False for this skill's own generated rows, which scored them as
# collected production data and disabled every escalation below.
SYNTHESISED_SOURCE_PREFIXES = (
    "synthetic",
    "synthesis",
    "synthesised",
    "synthesized",
    "generated",
    "generative",
    "llm",
    "gpt",
    "claude",
    "model-written",
    "model-generated",
    "machine-generated",
    "ai-",
    "ai_",
    "walkthrough",
    "mock",
    "fake",
    "placeholder",
    "simulated",
    "template",
)
COLLECTED_SOURCE_PREFIXES = (
    "production",
    "prod",
    "real",
    "collected",
    "observed",
    "logged",
    "log",
    "customer",
    "user",
    "field",
    "human",
    "curated",
    "reviewed",
    "annotated",
    "benchmark",
    "gold",
)
UNDECLARED_SOURCE_TOKENS = {"unknown", "n/a", "na", "none", "null", "tbd", "?"}

# Kept as the historical name so an existing caller/reader keeps working.
SYNTHETIC_SOURCE_PREFIXES = SYNTHESISED_SOURCE_PREFIXES

PROVENANCE_SYNTHESISED = "synthesised"
PROVENANCE_COLLECTED = "collected"
PROVENANCE_UNDECLARED = "undeclared"


def row_provenance(row: dict[str, Any]) -> Any:
    """Return a row's declared provenance token, or None if it declares none.

    Rows declare where their data came from under either `provenance` or the
    older `source` name, at the top level or nested in `metadata`. Reading only
    `source` (the historical name) meant a row that declared
    `metadata.provenance` read as `unknown` - it never earned the production
    band, and a row whose synthetic origin was declared only under `provenance`
    was scored as if it were collected. Both names are read here so the two
    scripts agree on one field.
    """
    metadata = row.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    for candidate in (
        row.get("provenance"),
        metadata.get("provenance"),
        row.get("source"),
        metadata.get("source"),
    ):
        if candidate not in (None, ""):
            return candidate
    return None


def row_output_provenance(row: dict[str, Any]) -> Any:
    """Return where a row's *expected output* came from, or None if undeclared.

    Separate from {@link row_provenance} because a row carries one token for
    itself, and that cannot express the common real shape: genuine collected
    inputs whose expected answers were written by a model rather than observed.
    Declaring it in the row's own token does not work - anything starting with
    a synthetic prefix marks the whole row generated - so it is read from its
    own field, under either name, at the top level or nested in `metadata`, to
    match how `row_provenance` reads its pair.
    """
    metadata = row.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    for candidate in (
        row.get("output_provenance"),
        metadata.get("output_provenance"),
        row.get("output_source"),
        metadata.get("output_source"),
    ):
        if candidate not in (None, ""):
            return candidate
    return None


def has_generated_output(row: dict[str, Any]) -> bool:
    """Report whether a row declares its expected output as generated."""
    source = row_output_provenance(row)
    if source is None:
        return False
    return str(source).casefold().strip().startswith(SYNTHETIC_SOURCE_PREFIXES)


def is_synthetic(row: dict[str, Any]) -> bool:
    """Report whether one row's declared provenance is written, not collected.

    A single row's answer to the one question in {@link classify_provenance}.
    Whether the *dataset* is synthetic is a question about shares, not about any
    one row, and is answered in `emit_dataset_provenance`.
    """
    return classify_provenance(row_provenance(row))[0] == PROVENANCE_SYNTHESISED


def classify_provenance(token: Any) -> tuple[str, bool]:
    """Classify one provenance token, and report whether it was recognised.

    Returns `(class, recognised)`.

    An unrecognised non-empty token is classified `undeclared`, and that is a
    decision with a measurement behind it. It used to be classified
    `collected`, on the reasoning that a project using its own vocabulary
    (`crm-export`) should not be demoted by a word list. What that bought
    instead was that a lie outscored the truth. Measured on 200 identical
    rows with only the token varying, through this classifier and then
    `score_dataset` in `scripts/readiness.py`: no token at all scored 65 and
    BLOCKED; the truthful `synthetic` scored 65 and BLOCKED; `crm-export`
    scored 95 EXCELLENT; and so did `zzz`. Three junk characters in a field
    nothing checks were worth thirty points and the difference between a
    blocked run and an excellent one.

    The rule this now implements is narrower than "refuse unknown tokens",
    which would be wrong for the reason above: an UNVERIFIABLE declaration
    must not outscore a VERIFIABLE one. `undeclared` is exactly that position -
    it scores what a row that says nothing scores, which is what a row this
    script cannot read is, and never more than a row that honestly declares
    itself generated.

    It is not a refusal and it is not permanent. `recognised=False` is still
    reported, the tokens are named on the card, and the remedy is
    `declare-data-provenance`: map the word onto the guide's vocabulary and
    re-score. The disclosure that comes with it prints BOTH grades, so a
    customer whose `crm-export` really is collected is shown the number that
    declaration earns before they do anything - honesty is disclosed, not
    punished, and the run is never stopped for it.
    """
    if token in (None, ""):
        return PROVENANCE_UNDECLARED, True
    normalized = str(token).casefold().strip()
    if not normalized or normalized in UNDECLARED_SOURCE_TOKENS:
        return PROVENANCE_UNDECLARED, True
    if normalized.startswith(SYNTHESISED_SOURCE_PREFIXES):
        return PROVENANCE_SYNTHESISED, True
    if normalized.startswith(COLLECTED_SOURCE_PREFIXES):
        return PROVENANCE_COLLECTED, True
    return PROVENANCE_UNDECLARED, False


def row_metadata_value(row: dict[str, Any], key: str) -> Any:
    if key in row:
        return row[key]
    metadata = row.get("metadata")
    return metadata.get(key) if isinstance(metadata, dict) else None


def nested_output_value(output: Any, field_path: str) -> tuple[bool, Any]:
    value = output
    for part in field_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value


def structured_outcomes(
    rows: list[dict[str, Any]], outcome_field: str | None
) -> tuple[str, list[Any]] | None:
    fields = (outcome_field,) if outcome_field else COMMON_OUTCOME_FIELDS
    for field in fields:
        values: list[Any] = []
        for row in rows:
            found, value = nested_output_value(row["output"], field)
            if not found or isinstance(value, (dict, list)) or value is None:
                values = []
                break
            values.append(value)
        if values:
            return field, values

    if outcome_field:
        emit(
            "dataset-outcome-field",
            FAIL,
            f"output field '{outcome_field}' is missing or non-scalar in one or more rows",
        )
    return None


def answer_distribution_is_established(counts: Counter[str]) -> bool:
    """Whether these rows establish a distribution over answers at all.

    Dominance is measured against chance, `1/k` for `k` distinct answers, and
    that comparison only says something when the answers actually repeat. On a
    free-text task they do not: `k` climbs with the number of rows read, so
    `1/k` is a fact about the sample rather than about the task, and an excess
    computed against it is arithmetic about nothing. Two rows per answer is the
    least repetition under which the most common answer's share is a measurement
    rather than a listing, so the rule is `rows >= 2 * labels`.

    THE QUESTION IS DELIBERATELY NOT "IS THIS FREE TEXT". An earlier revision of
    this branch asked exactly that and got it wrong, in the direction nobody
    reports: it classified the task and then stated the classification to the
    customer. Its rule compared the Good-Turing estimate of unseen answer mass,
    `f1/n`, against one answer's fair share `1/k` - which tightens as `k` grows,
    precisely where a real label set is most likely to carry rare labels. A
    101-row dataset over 18 labels with 8 rare ones was told "the 18 answers
    seen are a sample of an open-ended answer space rather than a closed set of
    labels". That is a false statement about somebody's data, printed as a fact.
    It also declined on 46.2% of all answer-count shapes up to 40 rows, against
    7.7% for the rule above.

    So this asks what can be measured instead of what the task IS, and declining
    on free text is a consequence rather than a claim: a set of distinct
    sentences has one row per answer and fails the same arithmetic that a 4-row
    label set fails, for the same honest reason.

    Two other candidates were dropped by measurement, not by taste. Answer
    LENGTH does not separate anything - real label sets run from one-word labels
    to table rows long enough to be mistaken for prose, and a five-word rule
    reports a 60-row set of four long SQL answers split 30/12/10/8 as unchecked
    while it is plainly dominant. A declared TASK KIND is the wrong kind of
    evidence and is also not here: `readiness.py` takes `--task-kind`, whose
    choices include `closed-label` and `free-text`, but that is a declaration,
    scored as one (an undeclared kind is `withheld`, never measured), and this
    script is a different process that is never given it. Letting a measurement
    switch itself off from a user-supplied label is the opposite of preflight.

    WHAT HAPPENS AT THE BOUNDARY, since a rule with two regimes has to say. One
    added row can move a dataset across this line, so the two things that must be
    true at the crossing are made true by construction rather than hoped for.

    The crossing never withdraws a finding. `DOMINANT_OUTCOME_SHARE` is tested
    ahead of this gate and on both sides of it, so every dataset the shipped rule
    flags is still flagged after crossing. It was not so in an earlier revision
    of this branch, and the cost was measured rather than reasoned about: 100
    rows carrying 90 identical answers and 10 one-off ones crossed into
    "UNCHECKED", and an unmeasured diversity sub-score outscores a flagged one on
    449 of 512 scored dataset shapes, by up to 6 points.

    The crossing is still a discontinuity in what is REPORTED, and that is
    deliberate and not smoothed over: on one side the answer is a chance-relative
    verdict, on the other it is SKIP, which `readiness.py` reads as UNCHECKED and
    never as clean. So crossing can turn an answer into "no answer" - which the
    card then says out loud - and it cannot turn a finding into a pass.
    """
    return sum(counts.values()) >= 2 * len(counts)


def dominance_excess(counts: Counter[str]) -> Fraction:
    """How far the majority-only baseline sits above chance, on a 0-1 scale.

    Exact rational arithmetic over the row counts, so a dataset sitting on the
    line is decided by its counts rather than by a float that rounded the wrong
    way.

    A single distinct answer returns the maximum rather than raising. `1/k` at
    k=1 is 100%, so the general expression divides by zero there - and the only
    reason it never did was that every caller happens to test the absolute share
    first, which catches a one-answer dataset at 100%. That is protection by
    call order, not by the function, and it would have become a crash the moment
    a caller reordered its tests or `DOMINANT_OUTCOME_SHARE` moved above 1. One
    answer holding every row is unambiguously total dominance, so returning 1 is
    the answer the formula is reaching for anyway.
    """
    labels = len(counts)
    if labels < 2:
        return Fraction(1)
    chance = Fraction(1, labels)
    share = Fraction(max(counts.values()), sum(counts.values()))
    return (share - chance) / (1 - chance)


def answer_dominance_finding(
    counts: Counter[str], *, subject: str
) -> tuple[str, str] | None:
    """The dominance verdict for one set of answers, or `None` when clean.

    Three outcomes, not two. `WARN` when the majority-only baseline is at or
    past the line; `SKIP` when the answers are not a closed label set, so the
    chance-relative question did not get answered and must not be read as having
    passed; `None` when it ran and found nothing.

    The absolute share is tested FIRST and outside the gate, so declining to
    answer can never withdraw a finding: whatever the answer space is, a
    majority at `DOMINANT_OUTCOME_SHARE` is a ceiling. The number is never
    written out here - it decides in one place and prints from that place, so
    lowering it cannot leave a sentence promising the old one.
    """
    rows = sum(counts.values())
    labels = len(counts)
    if rows < 2:
        return (
            SKIP,
            f"answer dominance is UNCHECKED for {subject}, not clean: fewer "
            "than two rows cannot establish an answer distribution",
        )
    share = Fraction(max(counts.values()), rows)
    if share >= DOMINANT_OUTCOME_SHARE:
        return (
            WARN,
            f"the most common {subject} covers {max(counts.values())}/{rows} "
            f"rows ({float(share):.1%}); always answering it already scores "
            f"that well, so configurations have little left to tell them "
            "apart. This one needs no chance baseline - a share that large is "
            "a ceiling whatever the answers are drawn from",
        )
    if not answer_distribution_is_established(counts):
        return (
            SKIP,
            f"answer dominance is UNCHECKED for every {subject}, not clean: "
            f"{rows} rows spread over {labels} distinct answers is fewer than "
            "two rows per distinct answer on average, so how often the most common one appears is a "
            "listing of your answers rather than a measurement of them, and 1 "
            f"in {labels} is not a chance baseline to compare it against. Free "
            "text lands here because every row is its own answer; so does a "
            "label set with too few rows to fill it. No answer here reaches "
            f"{float(DOMINANT_OUTCOME_SHARE):.0%} of the rows either, which is "
            "the one thing that can be said without a baseline - and that is "
            "not the same as no answer dominating",
        )
    excess = dominance_excess(counts)
    if excess < DOMINANCE_EXCESS_THRESHOLD:
        return None
    dominant_count = max(counts.values())
    return (
        WARN,
        f"the most common {subject} covers {dominant_count}/{rows} rows "
        f"({dominant_count / rows:.1%}) against a {1 / labels:.1%} chance "
        f"baseline for {labels} distinct answers - {float(excess):.0%} of the "
        f"way from chance to a perfect score, at or past the "
        f"{float(DOMINANCE_EXCESS_THRESHOLD):.0%} line. Always answering it "
        "already scores that well, so configurations have little left to tell "
        "them apart",
    )


def emit_dataset_provenance(
    present_rows: list[dict[str, Any]],
    *,
    labelled: int,
    scored_rows: Sequence[dict[str, Any]] = (),
) -> bool:
    """Emit the provenance metric and report whether the data is synthetic.

    `present_rows` are every row that carries an input, whether or not it also
    carries an expected output, so the reported row count reflects the data that
    exists rather than only the fully-labelled subset. `labelled` is the count
    that additionally carries a non-empty expected output. Emitting this even
    when no row is labelled is what lets the readiness scorer tell an unlabelled
    dataset (a partial score) apart from an absent one.
    """
    counts = {
        PROVENANCE_COLLECTED: 0,
        PROVENANCE_SYNTHESISED: 0,
        PROVENANCE_UNDECLARED: 0,
    }
    unrecognised: set[str] = set()
    declared_sources: set[str] = set()
    for row in present_rows:
        token = row_provenance(row)
        # Only what a row actually declared. `str(token or "unknown")` put the
        # literal `unknown` in here for a row carrying no provenance field at
        # all, so the card printed `declared sources: unknown` about a
        # declaration nobody made - and made it indistinguishable from a row
        # that really does declare the word, which is a different fact and is
        # already in `UNDECLARED_SOURCE_TOKENS`. A row that declares nothing is
        # counted in `undeclared_rows`, which is where that belongs.
        if token is not None:
            declared_sources.add(str(token).casefold())
        provenance_class, recognised = classify_provenance(token)
        counts[provenance_class] += 1
        if not recognised:
            unrecognised.add(str(token).casefold().strip())

    total = len(present_rows)
    # Counted, not `any()`. One generated row in a thousand collected ones used
    # to mark the whole dataset generated - scoring 3 of 10 and capping the run
    # at 65 - while the detail line said "every row declares generated
    # provenance", which was false for every mixture. The scorer needs the
    # shares to answer "how much of this is invented", so they are reported here
    # and `synthetic` keeps its name meaning what it says: all of it.
    synthetic = total > 0 and counts[PROVENANCE_SYNTHESISED] == total

    # A row whose own token is synthesised is already counted there; this is the
    # other shape - collected inputs whose expected answers were written by a
    # model. Scanned over rows that actually carry an expected output, through
    # the same `dataset_row_is_labelled` predicate the aggregate and per-split
    # counts use: a row with no answer cannot have a generated one, and
    # answering "does this row have an output" with a private test here is how
    # the checks in this file came to disagree about the same row (#68, #70).
    answerable = [row for row in scored_rows if dataset_row_is_labelled(row)]
    generated_answer_rows = sum(
        1
        for row in answerable
        if has_generated_output(row)
        and classify_provenance(row_provenance(row))[0] != PROVENANCE_SYNTHESISED
    )
    generated_outputs = generated_answer_rows > 0

    def _share(count: int, of: int) -> float:
        return round(count / of, 4) if of else 0.0

    synthesised_share = _share(counts[PROVENANCE_SYNTHESISED], total)
    # `[]` is not a source list a reader can act on, and it is now reachable:
    # a dataset where no row declares anything contributes no token at all.
    rendered_sources = (
        str(sorted(declared_sources)) if declared_sources else "none declared"
    )
    if synthetic:
        detail = f"all {total} rows declare generated provenance"
    elif counts[PROVENANCE_SYNTHESISED]:
        detail = (
            f"{counts[PROVENANCE_SYNTHESISED]} of {total} rows declare generated "
            f"provenance ({synthesised_share:.0%}); declared sources: "
            f"{rendered_sources}"
        )
    elif generated_outputs:
        detail = (
            f"declared sources: {rendered_sources}; "
            f"{generated_answer_rows} of {len(answerable)} expected outputs "
            "declare generated provenance"
        )
    else:
        detail = f"declared sources: {rendered_sources}"
    if counts[PROVENANCE_UNDECLARED]:
        # Appended to whichever detail was built, so a mixture keeps its shares
        # and still says what happens to the silent part of it.
        detail += (
            f"; {counts[PROVENANCE_UNDECLARED]} of {total} rows record no "
            "provenance and are scored as generated"
        )
    emit(
        "dataset-provenance",
        # `unknown` used to PASS, which read as "checked, fine" for a dataset
        # that had said nothing at all - the one state this check exists to
        # surface. It is not a FAIL: the data may be entirely real and merely
        # unlabelled, and the run continues either way. It is a WARN, for the
        # same reason a declared-generated corpus is.
        (
            WARN
            if counts[PROVENANCE_SYNTHESISED] or counts[PROVENANCE_UNDECLARED]
            else PASS
        ),
        detail,
        {
            "rows": total,
            "labelled_rows": labelled,
            "synthetic": synthetic,
            "generated_outputs": generated_outputs,
            "collected_rows": counts[PROVENANCE_COLLECTED],
            "synthesised_rows": counts[PROVENANCE_SYNTHESISED],
            "undeclared_rows": counts[PROVENANCE_UNDECLARED],
            "generated_answer_rows": generated_answer_rows,
            "answerable_rows": len(answerable),
            "sources": sorted(declared_sources),
            "unrecognised_sources": sorted(unrecognised),
        },
    )
    if unrecognised:
        # Named, so an unknown word neither quietly earns the production band
        # nor quietly loses one - what happened to it is on the card, and so is
        # the one-step way to change it.
        emit(
            "dataset-provenance-vocabulary",
            WARN,
            f"{sorted(unrecognised)} is not a provenance word this check knows, "
            "so those rows are scored as undeclared - the same as a row that "
            "says nothing, and never above a row that declares itself "
            "generated. Re-label them with a 'collected'/'production' or "
            "'synthetic'/'generated' token and re-run to score them as what "
            "they are",
        )
    return synthetic


def stable_id_is_missing(value: Any) -> bool:
    """Treat absent, empty, and whitespace-only IDs as unusable identifiers."""
    return value is None or (isinstance(value, str) and not value.strip())


def emit_dataset_id_findings(
    row_records: list[tuple[int, dict[str, Any]]],
) -> None:
    """Validate IDs across every input-bearing row, including unlabelled rows."""
    missing_records: list[tuple[int, dict[str, Any]]] = []
    ids: list[str] = []
    for line_number, row in row_records:
        value = row_metadata_value(row, "id")
        if stable_id_is_missing(value):
            missing_records.append((line_number, row))
        else:
            ids.append(
                stable_json(value) if isinstance(value, (dict, list)) else str(value)
            )
    if missing_records:
        missing_lines = [line_number for line_number, _row in missing_records]
        generated_missing = sum(
            1
            for _line_number, row in missing_records
            if classify_provenance(row_provenance(row))[0] == PROVENANCE_SYNTHESISED
        )
        shown_lines = missing_lines[:MAX_REPORTED_DATASET_IDS]
        location = (
            f"source line {shown_lines[0]}"
            if len(missing_lines) == 1
            else f"source lines {shown_lines}"
        )
        suffix = (
            ""
            if len(missing_lines) <= len(shown_lines)
            else f" (first {MAX_REPORTED_DATASET_IDS} shown)"
        )
        noun = "row" if len(missing_lines) == 1 else "rows"
        verb = "has" if len(missing_lines) == 1 else "have"
        generated_noun = "row" if generated_missing == 1 else "rows"
        generated_verb = "requires" if generated_missing == 1 else "require"
        generated_detail = (
            f"; {generated_missing} generated {generated_noun} "
            f"{generated_verb} an id"
            if generated_missing
            else ""
        )
        emit(
            "dataset-ids",
            FAIL if generated_missing else WARN,
            f"{len(missing_lines)} {noun} at {location}{suffix} {verb} "
            "no stable id; add stable ids in a working copy before excluding rows "
            f"or selecting a bounded subset, then re-run validation{generated_detail}",
        )
    id_counts = Counter(ids)
    duplicate_ids = sorted(value for value, count in id_counts.items() if count > 1)
    if duplicate_ids:
        emit(
            "dataset-ids",
            FAIL,
            f"duplicate ids: {duplicate_ids[:MAX_REPORTED_DATASET_IDS]}",
        )
    elif not missing_records:
        emit("dataset-ids", PASS, "stable ids are unique")


def check_evaluator(path: Path) -> None:
    """Static, non-executing structural check for the evaluator source file.

    Parses the file with `ast.parse` only. That builds a syntax tree without
    running a single line of the file - no import, no call, no module-level
    side effect - so it never touches provider credentials and never invokes
    whatever the evaluator's own logic does. That is also the honest limit of
    what this check can claim: a file that parses is merely readable as
    Python, not correct. Whether it behaves like a real evaluator - for
    example, whether its score ever depends on the input - is a runtime
    question, and this check does not attempt to answer it. That question
    belongs to `calibrate_evaluator.py`, which answers it deliberately, in a
    credential-stripped subprocess, only after explicit approval
    (traigent-first-run#133).
    """
    if not path.exists():
        emit("evaluator-shape", FAIL, f"{path} does not exist", {"exists": False})
        return
    try:
        source = path.read_text()
    except (OSError, UnicodeDecodeError) as error:
        emit(
            "evaluator-shape",
            FAIL,
            f"{path} could not be read as text: {error}",
            {"exists": True, "parses": False},
        )
        return
    try:
        ast.parse(source, filename=str(path))
    except SyntaxError as error:
        emit(
            "evaluator-shape",
            FAIL,
            f"{path} is not valid Python: {error}",
            {"exists": True, "parses": False},
        )
        return
    except (MemoryError, RecursionError, ValueError) as error:
        # `ast.parse` refuses some inputs without calling them a SyntaxError,
        # and an uncaught one takes the whole process down mid-run - emitting
        # no JSON at all, which silently breaks the `--json` contract
        # `readiness.py --preflight -` reads. A ~50 KB file of chained unary
        # operators is enough: CPython raises `MemoryError: Parser stack
        # overflowed`, not a SyntaxError. `RecursionError` and `ValueError`
        # (older CPythons raise it for embedded null bytes) are the same
        # class of refusal.
        #
        # Reported as `parses: False`, which is the fail-closed reading and
        # the honest one: this check could not establish that the file
        # parses. It deliberately does not claim the file is invalid Python -
        # what happened is that parsing did not complete, and the detail says
        # so, because the remedy either way is to inspect the file.
        emit(
            "evaluator-shape",
            FAIL,
            f"{path} could not be parsed: {type(error).__name__}: {error}",
            {"exists": True, "parses": False},
        )
        return
    emit(
        "evaluator-shape",
        PASS,
        f"{path} parses as valid Python; this proves nothing about its "
        "scoring behavior, which is not executed here",
        {"exists": True, "parses": True},
    )


def check_dataset(
    path: Path,
    outcome_field: str | None = None,
    input_field: str = "input",
    expected_field: str = "output",
    evaluator_method: str | None = None,
) -> list[dict[str, Any]] | None:
    if not path.exists():
        emit("dataset-shape", FAIL, f"{path} does not exist")
        return None

    reference_free = evaluator_method in REFERENCE_FREE_METHODS
    rows: list[dict[str, Any]] = []
    present_rows: list[dict[str, Any]] = []
    present_row_records: list[tuple[int, dict[str, Any]]] = []
    invalid_rows: list[tuple[int, str]] = []
    unlabelled_present = 0
    candidate_count = 0
    for line_number, raw_line in enumerate(path.read_text().splitlines(), 1):
        if not raw_line.strip():
            continue
        candidate_count += 1
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as error:
            invalid_rows.append((line_number, f"invalid JSON ({error.msg})"))
            continue
        if not isinstance(row, dict):
            invalid_rows.append((line_number, "row is not an object"))
            continue
        normalized_row, normalization_error = normalize_dataset_row(
            row,
            input_field=input_field,
            expected_field=expected_field,
            require_expected=not reference_free,
        )
        if normalization_error is not None:
            invalid_rows.append((line_number, normalization_error))
            # A row that carries an input but only lacks its expected output is a
            # present-but-unlabelled data point, not malformed data. It is still
            # unusable for scoring, but tracking it lets the readiness adapter
            # tell "rows exist, none labelled" apart from "no dataset at all".
            input_found, _ = dataset_field_value(row, input_field)
            expected_found, _ = dataset_field_value(row, expected_field)
            if input_found and not expected_found and input_field != expected_field:
                present_rows.append(row)
                present_row_records.append((line_number, row))
                unlabelled_present += 1
            continue
        if normalized_row is None:
            raise RuntimeError("dataset normalization returned no row without an error")
        rows.append(normalized_row)
        present_rows.append(row)
        present_row_records.append((line_number, row))

    malformed_rows = len(invalid_rows) - unlabelled_present
    if invalid_rows:
        invalid_percentage = len(invalid_rows) / candidate_count * 100
        # One entry per unusable ROW made the message grow with the size of the
        # file rather than with the number of things wrong with it: six rows
        # missing the same selected field printed that sentence six times, 347
        # characters to say one thing. Readiness forwards this detail verbatim
        # onto its card, so the repetition was what a customer read.
        #
        # Group by cause instead, keep the first line each was seen on - the
        # line to open - and count the rest. The cap then bounds DISTINCT
        # causes rather than rows, so a file with five different problems now
        # reports five of them where it previously spent all five slots on the
        # first cause repeating. Nothing is inferred that preflight did not
        # already say; the same facts are stated once each.
        by_cause: dict[str, list[int]] = {}
        for line_number, detail in invalid_rows:
            by_cause.setdefault(detail, []).append(line_number)
        examples = "; ".join(
            (
                f"line {lines[0]}: {detail}"
                if len(lines) == 1
                else f"line {lines[0]} (+{len(lines) - 1} more): {detail}"
            )
            for detail, lines in list(by_cause.items())[:MAX_REPORTED_DATASET_ERRORS]
        )
        emit(
            "dataset-integrity",
            FAIL,
            f"{len(invalid_rows)}/{candidate_count} rows ({invalid_percentage:.1f}%) "
            f"are unusable; {examples}",
            {
                "invalid_rows": len(invalid_rows),
                "malformed_rows": malformed_rows,
                "unlabelled_rows": unlabelled_present,
                "candidate_rows": candidate_count,
            },
        )
    if not rows:
        if present_rows:
            # Rows carry inputs but none carry an expected output: a
            # present-but-unlabelled dataset, not an absent one. Emit provenance
            # so the readiness adapter reaches the "no expected outputs" branch
            # (a partial score) instead of "no dataset at all", then stop - there
            # are no labelled rows to run the remaining quality checks against.
            emit_dataset_provenance(present_rows, labelled=0)
            emit_dataset_id_findings(present_row_records)
            emit(
                "dataset-shape",
                FAIL,
                f"{len(present_rows)} rows carry inputs but none carry an "
                "expected output",
            )
            return None
        emit("dataset-shape", FAIL, "dataset has no usable rows")
        return None
    if not invalid_rows:
        # The card's headline row count had no machine twin at all, so the one
        # number a customer reads first was the one number nothing downstream
        # could check. `candidate_rows` travels with it because `len(rows)` is
        # the rows this method can SCORE, which is not the size of their file
        # whenever a row is excluded by design.
        emit(
            "dataset-shape",
            PASS,
            f"{len(rows)} valid JSONL rows",
            {"scoreable_rows": len(rows), FULL_ROW_COUNT: candidate_count},
        )
    if len(rows) < WIRING_CHECK_EXAMPLES:
        emit(
            "dataset-size",
            WARN,
            f"{len(rows)} rows is a wiring check, not a credible score",
        )
    # The cap named the walkthrough's eighteen whatever the file held, so a
    # dataset of 400 rows asking 12 questions was proposed an 18-row subset in
    # the same JSON that reported twelve. Two numbers, one question, and nothing
    # saying which governs - while the difference is six rows per configuration
    # in every trial. The population is named by the helper rather than taken
    # from whichever local list of rows was nearest, because getting it wrong
    # is not one bug: it is one bug per scoping axis, and this file has already
    # had it on two of them.
    distinct_inputs, distinct_scope = drawable_distinct_inputs(rows)
    first_run_rows = first_run_row_count(len(rows), distinct_inputs)
    distinct_clause = (
        ""
        if distinct_inputs >= len(rows)
        else f" ({distinct_inputs} different inputs in {distinct_scope})"
    )
    emit(
        "dataset-first-run-rows",
        PASS,
        f"proposed first-run subset cap: {first_run_rows} usable rows per "
        f"configuration from {len(rows)} usable rows{distinct_clause}; select "
        "and record the actual row ids before baseline approval",
        {
            "first_run_rows": first_run_rows,
            "usable_rows": len(rows),
            "first_run_distinct_rows": distinct_inputs,
            "first_run_distinct_scope": distinct_scope,
        },
    )

    input_types = {type(row["input"]).__name__ for row in rows}
    if len(input_types) > 1:
        emit(
            "dataset-input-shape",
            FAIL,
            f"mixed input types cannot share one agent contract: {sorted(input_types)}",
        )
    else:
        emit(
            "dataset-input-shape",
            PASS,
            f"all inputs use the same {next(iter(input_types))} shape",
        )

    labelled = sum(1 for row in rows if dataset_row_is_labelled(row))
    synthetic = emit_dataset_provenance(
        present_rows, labelled=labelled, scored_rows=rows
    )
    emit_dataset_id_findings(present_row_records)

    normalized_inputs: dict[str, list[int]] = {}
    for index, row in enumerate(rows, 1):
        normalized_inputs.setdefault(normalized_identity(row["input"]), []).append(
            index
        )
    exact_duplicates = [
        positions for positions in normalized_inputs.values() if len(positions) > 1
    ]
    # Both records describe repetition, and the readiness score deducts for it
    # once - `dataset-near-duplicates` is what it deducts on, because identical
    # rows score 1.0 and so are already inside whatever the near line is.
    # This one is kept because it is a hash bucket: O(n), always complete, and
    # therefore still able to report repetition on a dataset where the bounded
    # near-duplicate join gave up. It detects; it does not score twice.
    #
    # The count travels with the finding, because a reader downstream needs the
    # ARITHMETIC and not the sentence. `detail` names the repeated positions and
    # stops at ten of them, so a scorer that wanted to know how many comparisons
    # this file actually holds would have to parse prose that is deliberately
    # truncated. `distinct_rows` is the same scan's other half - the buckets, not
    # the collisions - and it is the number a resolution question is really
    # asking for. Published on the PASS arm too: a reader must not have to infer
    # "then they were all distinct" from the absence of a metric, and a check
    # that answers with a count only when the news is bad is one whose silence
    # has two meanings.
    duplicate_metrics = {
        "distinct_rows": len(normalized_inputs),
        "scoreable_rows": len(rows),
    }
    if exact_duplicates:
        emit(
            "dataset-duplicates",
            FAIL if synthetic else WARN,
            f"exact/normalized duplicate inputs at rows {exact_duplicates[:10]}",
            duplicate_metrics,
        )
    else:
        emit(
            "dataset-duplicates",
            PASS,
            "no exact or normalized duplicate inputs",
            duplicate_metrics,
        )

    threshold_percent = f"{NEAR_DUPLICATE_THRESHOLD:.0%}"
    # The INPUT, and only the input. Repeated inputs are the defect this check
    # exists to find - the same question asked twice spends two trials learning
    # one thing. Repeated expected ANSWERS are not a defect and are not read
    # here: a closed-label task is supposed to reuse its labels, and 500 rows
    # labelled yes/no would look like 500 duplicates to a check pointed at the
    # output field. Whether one answer has taken over the dataset is a different
    # question with its own record (`dataset-ceiling-risk`).
    # Counted before the list comprehension below, which is the whole point: that
    # comprehension and the index built from it are what reach 36x the file, and a
    # ceiling consulted after they exist has bounded nothing. This pass holds one
    # row's runs at a time (`near_duplicate_index_size`), so the refusal costs the
    # tokenization and no allocation the check could have died on.
    index_runs = near_duplicate_index_size(row["input"] for row in rows)
    if index_runs > MAX_NEAR_DUPLICATE_SHINGLES:
        # The second way this check can decline to run, and it must not be
        # mistakable for the first. The work SKIP below means "too many
        # comparisons"; this one means "too much memory", the reader's dataset is
        # not slow but large, and de-duplicating it would not help. Naming the
        # wrong limit would send them to fix the wrong thing.
        emit(
            "dataset-near-duplicates",
            SKIP,
            f"the inputs hold {index_runs:,} runs of {NEAR_DUPLICATE_SHINGLE} "
            f"words against a {MAX_NEAR_DUPLICATE_SHINGLES:,} run MEMORY "
            "ceiling, so this dataset is UNCHECKED for near-duplicates - not "
            "clean. The scan is exact, which means every row's runs are held at "
            "once; past this ceiling that costs more memory than one preflight "
            "check may take. It is refused before any of it is allocated, "
            "deliberately: running out of memory would end the whole preflight "
            "with no output at all, which is worse than one line saying it did "
            "not run. This is a size limit and not a repetition one, so "
            "de-duplicating will not clear it - scan a sample of the rows, or "
            "split the dataset, if you need this answered",
        )
    else:
        near_pairs, near_complete = near_duplicate_pairs(
            [shingle_set(row["input"]) for row in rows]
        )
        if near_pairs:
            # A truncated scan still answered the question - there ARE
            # near-duplicates - so it stays a finding rather than becoming a
            # SKIP. What it cannot claim is that these are all of them.
            more = (
                ""
                if near_complete
                else "; the scan stopped early, so there may be more"
            )
            emit(
                "dataset-near-duplicates",
                FAIL if synthetic else WARN,
                f"input pairs at least {threshold_percent} similar (shared runs "
                f"of {NEAR_DUPLICATE_SHINGLE} consecutive words over total runs, "
                "so the same words in a different order are not a repeat), "
                f"identical rows included: {near_pairs[:10]}{more}",
            )
        elif near_complete:
            emit(
                "dataset-near-duplicates",
                PASS,
                f"no input pair reaches {threshold_percent} similarity",
            )
        else:
            # Found nothing AND did not finish, which is not the same statement
            # as "found nothing". The only way here is a dataset so repetitive
            # that the filter admits everything; say that this is unchecked,
            # never clean.
            #
            # And say why it took so long, in terms of the dataset the user is
            # holding. Getting here is the one slow path in this script, so they
            # have just waited and are then told the check did not run; without
            # the second sentence that reads as the script having hung on their
            # data.
            #
            # The cause is not what it was, and the text moved with it. Under
            # word sets the two ways in were long rows and a small vocabulary,
            # and BOTH are now wrong: 2,000 rows of 300 words spend 964M
            # operations as word sets and 0 as sequences, and 5,000 twelve-word
            # rows over a 60-word vocabulary also spend 0, because sequences
            # repeat across rows far less than words do. What is left is the one
            # thing that still makes a sequence common - many rows genuinely
            # phrased alike - so that is what this now names. A user reading the
            # old sentence about their own file would have been sent to split
            # inputs that were never the cause.
            #
            # Reachable only BELOW the memory ceiling, which is what makes the
            # two SKIPs a real pair rather than a race: a dataset large enough
            # to be refused above never gets here to be called slow.
            emit(
                "dataset-near-duplicates",
                SKIP,
                "the near-duplicate scan reached its work budget before "
                "comparing every candidate pair, so this dataset is UNCHECKED "
                "for near-duplicates - not clean. The exact check compares "
                "whole sets of word runs, so it costs most when many rows are "
                "phrased alike: shared boilerplate, one template filled in "
                "repeatedly, or the same passage retrieved into many rows. Long "
                "rows make each of those comparisons dearer, but length alone "
                "does not reach this budget. De-duplicate the obvious repeats, "
                "or scan a sample, if you need this answered",
            )

    unlabelled = [row for row in rows if not dataset_row_is_labelled(row)]
    scoreable_rows = [row for row in rows if dataset_row_is_labelled(row)]
    if reference_free:
        emit(
            "dataset-outputs",
            SKIP,
            f"{evaluator_method} is reference-free; expected outputs are not required",
        )
    else:
        # Every dominance verdict this run reaches, emitted as ONE record below.
        # Both the expected answers and a structured outcome field can produce
        # one, and `readiness.py` reads preflight's records into a dict keyed by
        # check name, so two `dataset-ceiling-risk` records collapse to whichever
        # was emitted last. That was harmless while the only record was a
        # finding; it stops being harmless once one of the outcomes is "did not
        # run", because the loser of that collapse is a whole verdict.
        #
        # The reachable case today is a SKIP from the expected answers and a
        # WARN from the outcome field - free-text answers carrying one dominant
        # label - and it is emitted in that order, so the WARN has to be chosen
        # rather than arrived at last. The opposite order is currently NOT
        # reachable, and the reason is worth writing down because it is what
        # this code must not quietly depend on: the outcome field is a component
        # of the output, so the field repeats wherever the whole output repeats,
        # which makes it dominant whenever the output is and established
        # whenever the output is. Choosing most-severe-first means that argument
        # does not have to keep holding - a second subject, a nested field read
        # through `--outcome-field`, or any later branch that can also decline
        # gets the same answer without anyone re-deriving it.
        dominance_findings: list[tuple[str, str]] = []
        placeholder_outputs = [
            row for row in scoreable_rows if not normalized_text(row["output"])
        ]
        if placeholder_outputs:
            emit(
                "dataset-output-placeholders",
                WARN,
                f"{len(placeholder_outputs)}/{len(rows)} expected outputs carry no "
                'word characters (for example "-", "?" or "...") - confirm '
                "whether these are intentional symbolic labels or placeholders; "
                "they remain in the labelled counts",
                {"placeholder_rows": len(placeholder_outputs), "rows": len(rows)},
            )
        scoreable_outputs = [
            normalized_identity(row["output"]) for row in scoreable_rows
        ]
        output_counts = Counter(scoreable_outputs)
        if unlabelled:
            emit(
                "dataset-outputs",
                FAIL,
                f"{len(unlabelled)}/{len(rows)} expected outputs are empty",
            )
        elif len(scoreable_outputs) < 2:
            # Dominance needs at least two answers to be a statement about
            # anything. One row's single answer holds 100% of the rows by
            # arithmetic, and reporting that charged a 1-row dataset 6 of its
            # 20 diversity points for a finding no dataset of that size can
            # avoid - and told its owner to diversify answers they have one of.
            # The size problem is real and `dataset-size` already says it.
            emit(
                "dataset-outputs",
                SKIP,
                f"{len(scoreable_outputs)} expected output, which is too few "
                "for answer spread to mean anything; the row count is the "
                "finding here",
            )
            dominance_findings.append(
                (SKIP, "fewer than two expected outputs; answer dominance is unchecked")
            )
        elif len(output_counts) == 1:
            emit(
                "dataset-outputs",
                FAIL if synthetic else WARN,
                "every expected output is identical; evaluator discrimination is likely degenerate",
            )
            # And say it in the dominance vocabulary too, because this IS the
            # dominance finding at its maximum - one answer holding 100% of the
            # rows. Without this, the branch below is the only place
            # `dataset-ceiling-risk` is raised, and it is unreachable here: it
            # lives under the PASS arm. `_answer_dominance_status` in
            # readiness.py reads a PASS on `dataset-outputs` as its witness that
            # the spread was examined, so the WARN above left it with no record
            # at all and it reported answer dominance as NEVER CHECKED.
            #
            # The consequence was a scoring inversion, which is what makes this
            # worth an extra record rather than a comment: an unmeasured
            # sub-score drops out of the pillar average, so a dataset where
            # every answer is identical scored HIGHER than one where 90% are.
            # A skipped check is not a passed check - and a check that ran and
            # found the worst possible answer must not read as one that never
            # ran.
            #
            # This one case is stated without a chance baseline, because it does
            # not need one: one answer holding every row is the maximum of this
            # check at any label count, and `1/k` at k=1 is 100%, a baseline
            # that would divide by zero and say nothing if it did not.
            dominance_findings.append(
                (
                    WARN,
                    f"{len(scoreable_outputs)}/{len(scoreable_outputs)} expected "
                    "outputs (100.0%) are identical; a majority-only strategy "
                    "could hide meaningful failures",
                )
            )
        else:
            emit(
                "dataset-outputs",
                PASS,
                f"{len(output_counts)} distinct expected outputs",
            )
            finding = answer_dominance_finding(output_counts, subject="expected output")
            if finding:
                dominance_findings.append(finding)

        structured = structured_outcomes(scoreable_rows, outcome_field)
        if structured:
            field, values = structured
            value_counts = Counter(normalized_identity(value) for value in values)
            finding = answer_dominance_finding(
                value_counts, subject=f"value in output field '{field}'"
            )
            if finding:
                dominance_findings.append(finding)
            if finding is None or finding[0] == SKIP:
                emit(
                    "dataset-outcome-field",
                    PASS,
                    f"output field '{field}' has {len(value_counts)} distinct values",
                )

        if dominance_findings:
            warned = [finding for finding in dominance_findings if finding[0] == WARN]
            chosen = warned or dominance_findings
            status = chosen[0][0]
            # One record, but not one sentence. The record is single because
            # readiness keys by check name and a second one would overwrite the
            # first; the detail carries every finding of that severity because a
            # person reading this terminal loses nothing the previous two-record
            # version told them. Dominant expected answers AND a dominant
            # outcome field are two facts about the dataset, not one said twice.
            emit("dataset-ceiling-risk", status, "; also, ".join(d for _, d in chosen))

    splits: dict[str, set[str]] = {}
    split_counts: Counter[str] = Counter()
    labelled_split_counts: Counter[str] = Counter()
    # Iterates `present_rows`, not only normalized scoreable rows (#66). Under a
    # reference-requiring method, a row with no output never reaches `rows`, so a
    # held-out split declared that way used to be invisible:
    # preflight reported "no explicit tuning/held-out split was found" about a
    # dataset where every row declared one, and readiness scored it through the
    # no-split branch.
    #
    # The input is resolved through `dataset_field_value` rather than read as
    # `row["input"]`. That subscript is only correct on a normalized row, where
    # "input" is the projected value; on a raw row it is a KeyError under any
    # non-default `--input-field`.
    for row in present_rows:
        split = row_metadata_value(row, "split")
        if split:
            split_name = str(split).casefold()
            split_counts[split_name] += 1
            if dataset_row_is_labelled(row, expected_field):
                labelled_split_counts[split_name] += 1
            _, input_value = dataset_field_value(row, input_field)
            splits.setdefault(split_name, set()).add(normalized_identity(input_value))
    tune_names = TUNING_SPLIT_NAMES
    holdout_names = {"holdout", "test", "validation", "validate"}
    tune_inputs = set().union(
        *(values for name, values in splits.items() if name in tune_names)
    )
    holdout_inputs = set().union(
        *(values for name, values in splits.items() if name in holdout_names)
    )
    overlap = tune_inputs & holdout_inputs

    def emit_tuning_size(tuning_count: int, tuning_labelled: int) -> None:
        tuning_scoreable = tuning_count if reference_free else tuning_labelled
        tuning_suffix = (
            ""
            if tuning_scoreable == tuning_count
            else f", {tuning_scoreable} scoreable"
        )
        tuning_metrics = {
            "tuning_rows": tuning_count,
            "tuning_labelled_rows": tuning_labelled,
            # How many DIFFERENT questions the tuning side asks. `tune_inputs`
            # is already the set of normalized inputs on this side of the line -
            # built above to answer whether the two sides overlap - so the count
            # is a `len()` of something this check computed and then dropped,
            # not a second scan of the file.
            #
            # It is published beside the row count rather than instead of it
            # because the two are different true facts about the same file, and
            # the difference is the finding: a tuning side of thirty rows asking
            # fifteen questions is not the same comparison as one asking thirty,
            # and only the second count can say which one this is.
            "tuning_distinct_rows": len(tune_inputs),
        }
        if tuning_scoreable < WIRING_CHECK_EXAMPLES:
            emit(
                "dataset-tuning-size",
                WARN,
                f"{tuning_count} tuning rows{tuning_suffix} is a wiring check, "
                "not a credible optimization score",
                tuning_metrics,
            )
        else:
            emit(
                "dataset-tuning-size",
                PASS,
                f"{tuning_count} tuning rows{tuning_suffix}; clears the "
                f"{WIRING_CHECK_EXAMPLES}-row static wiring boundary; "
                "readiness rates comparison size separately",
                tuning_metrics,
            )

    if overlap:
        emit(
            "dataset-split",
            FAIL,
            f"{len(overlap)} inputs overlap the tuning and held-out splits",
        )
    elif tune_inputs and holdout_inputs:
        emit(
            "dataset-split",
            PASS,
            "tuning and held-out inputs are disjoint",
            {"kind": "tuning-and-holdout"},
        )
        # A second question about the SAME two sets `dataset-split` just
        # compared, and a second record rather than a widened detail because
        # readiness keys by check name. Disjointness and where the line falls
        # are different findings, and answering both under one id would mean
        # one overwriting the other.
        #
        # Only here. Under overlap the split is already condemned, and with one
        # side missing there is no boundary to compare a family boundary with.
        emit(
            "dataset-split-family",
            *family_partition_finding(sorted(tune_inputs), sorted(holdout_inputs)),
        )
        tuning_count = sum(
            count for name, count in split_counts.items() if name in tune_names
        )
        holdout_count = sum(
            count for name, count in split_counts.items() if name in holdout_names
        )
        tuning_labelled = sum(
            count for name, count in labelled_split_counts.items() if name in tune_names
        )
        holdout_labelled = sum(
            count
            for name, count in labelled_split_counts.items()
            if name in holdout_names
        )
        emit_tuning_size(tuning_count, tuning_labelled)
        holdout_scoreable = holdout_count if reference_free else holdout_labelled
        holdout_metrics = {
            "holdout_rows": holdout_count,
            "holdout_labelled_rows": holdout_labelled,
        }
        if holdout_scoreable == 0:
            # Dividing 100 by the *total* holdout size claimed a per-example
            # resolution the evaluator cannot deliver; with no scoreable holdout
            # row there is no resolution to quote at all, and the old divisor
            # would now be zero.
            holdout_detail = (
                f"{holdout_count} held-out rows, none scoreable; no held-out row "
                "carries an expected output, so this split resolves nothing"
            )
        elif holdout_scoreable == holdout_count:
            holdout_detail = (
                f"{holdout_count} held-out rows; one example changes the score by "
                f"{(100 / holdout_count):.1f} percentage points"
            )
        else:
            holdout_detail = (
                f"{holdout_count} held-out rows, {holdout_scoreable} scoreable; one "
                f"scoreable example changes the score by "
                f"{(100 / holdout_scoreable):.1f} percentage points"
            )
        emit(
            "dataset-holdout-resolution",
            WARN if holdout_scoreable < WIRING_CHECK_EXAMPLES else PASS,
            holdout_detail,
            holdout_metrics,
        )
    elif tune_inputs:
        tuning_count = sum(
            count for name, count in split_counts.items() if name in tune_names
        )
        tuning_labelled = sum(
            count for name, count in labelled_split_counts.items() if name in tune_names
        )
        emit(
            "dataset-split",
            PASS,
            "tuning-only dataset; no held-out split was declared",
            {"kind": "tuning-only"},
        )
        emit_tuning_size(tuning_count, tuning_labelled)
    else:
        emit("dataset-split", WARN, "no explicit tuning/held-out split was found")

    difficulty_values = [
        str(row_metadata_value(row, "difficulty")).casefold().replace("_", "-")
        for row in rows
        if row_metadata_value(row, "difficulty")
    ]
    difficulties = set(difficulty_values)
    emit(
        "dataset-difficulty-coverage",
        PASS if EXPECTED_DIFFICULTIES <= difficulties else WARN,
        (
            f"{len(difficulty_values)} of {len(rows)} rows carry a difficulty tag; "
            f"bands present: {sorted(difficulties) or 'none'}"
        ),
        {
            "tagged_rows": len(difficulty_values),
            # `total_rows` counts the rows this method can score, which is the
            # right denominator for coverage and the wrong one to read alone:
            # on a file whose unlabelled rows were the tagged-hard ones, this
            # line says "12 of 12" over a 20-row file. The population it
            # counted travels beside it so the exclusion is visible.
            "total_rows": len(rows),
            FULL_ROW_COUNT: candidate_count,
            "bands": sorted(difficulties),
            "missing_bands": sorted(EXPECTED_DIFFICULTIES - difficulties),
        },
    )
    if difficulty_values and difficulties == {"easy"}:
        emit(
            "dataset-difficulty",
            FAIL if synthetic else WARN,
            f"all {len(difficulty_values)} difficulty-tagged rows are easy; "
            "a ceiling effect may leave configurations indistinguishable",
        )
    elif (
        not synthetic and difficulty_values and not difficulties & {"hard", "very-hard"}
    ):
        emit(
            "dataset-difficulty",
            WARN,
            f"none of {len(difficulty_values)} difficulty-tagged rows are hard or "
            "very-hard; boundary and failure-mode coverage may be missing",
        )
    elif not synthetic and EXPECTED_DIFFICULTIES <= difficulties:
        emit("dataset-difficulty", PASS, "all four difficulty bands are represented")

    if synthetic:
        missing_difficulties = EXPECTED_DIFFICULTIES - difficulties
        if missing_difficulties:
            emit(
                "dataset-difficulty",
                FAIL,
                f"synthetic data is missing difficulty bands: {sorted(missing_difficulties)}",
            )
        else:
            emit(
                "dataset-difficulty", PASS, "all four difficulty bands are represented"
            )
        scenario_count = len(
            {
                str(row_metadata_value(row, "coverage"))
                for row in rows
                if row_metadata_value(row, "coverage")
            }
        )
        if scenario_count < 4:
            emit(
                "dataset-coverage",
                WARN,
                f"only {scenario_count} distinct coverage/scenario tags were found",
            )
        else:
            emit("dataset-coverage", PASS, f"{scenario_count} distinct scenario tags")

    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Traigent first-run static preflight (zero provider/backend calls)."
    )
    parser.add_argument("--env", default=".env", help="path to the local .env")
    parser.add_argument(
        "--project-root",
        default=".",
        help=(
            "the user's project directory, read only for the dependency "
            "declarations that say whether Traigent was already set up here "
            "(default: the working directory)"
        ),
    )
    parser.add_argument(
        "--models", default="", help="comma-separated LiteLLM model ids"
    )
    parser.add_argument("--dataset", help="JSONL dataset to validate")
    parser.add_argument(
        "--input-field",
        default="input",
        help=(
            "dot path used only by local quality checks (default: input); "
            "this does not configure or validate SDK loading"
        ),
    )
    parser.add_argument(
        "--expected-field",
        default="output",
        help=(
            "dot path used only by local quality checks (default: output); "
            "this does not configure or validate SDK loading"
        ),
    )
    parser.add_argument(
        "--outcome-field",
        help="dot path for a structured discrete outcome, such as category or result.label",
    )
    parser.add_argument(
        "--evaluator-method",
        help=(
            "declared method; pointwise, pairwise, and rubric LLM judges allow "
            "input-only rows, while absent or other values require expected outputs"
        ),
    )
    parser.add_argument(
        "--evaluator",
        help=(
            "path to the evaluator source file for a static, non-executing "
            "syntax check (ast.parse only - never imported or run); pass this "
            "whenever an evaluator file was found, even if --evaluator-method "
            "is omitted because no method could be honestly declared for it"
        ),
    )
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable results"
    )
    parser.add_argument(
        "--defer-missing-sdk",
        action="store_true",
        help="report an absent SDK as deferred during the mandatory pre-install component pass",
    )
    parser.add_argument("--strict", action="store_true", help="exit 1 on warnings")
    return parser.parse_args()


# The one place an unexpected failure is allowed to end.
#
# The three scripts in this bundle each own this boundary because each is a
# standalone file the skill copies out, and a shared helper module is a fourth
# file to keep in step. What it guards is identical in all three: an error
# nobody anticipated - a `KeyError` on a payload shape, a `TypeError` on a field
# that arrived as a string - used to escape to the interpreter, which printed a
# traceback in place of the result and exited 1. The reader is running their
# first optimization; a defect in this check must not read as a defect in their
# project.
#
# Loud, not silent: the error class and message are printed, the exit code is
# non-zero and distinct, and nothing pretends a check ran. The environment
# variable prints the stack for whoever is fixing it.
INTERNAL_ERROR_EXIT = 3
TRACEBACK_ENV = "TRAIGENT_FIRST_RUN_TRACEBACK"


def report_internal_error(
    tool: str,
    error: BaseException,
    *,
    environ: dict[str, str] | None = None,
    stream: Any = None,
) -> int:
    """Print an unexpected failure as a diagnosis, never as a traceback."""
    out = sys.stderr if stream is None else stream
    env = os.environ if environ is None else environ
    print(f"{tool}: internal error - {type(error).__name__}: {error}", file=out)
    print(
        f"{tool} could not finish, and this is a defect in the check rather "
        "than in your project. No result was produced, so treat nothing as "
        f"checked. Re-run with {TRACEBACK_ENV}=1 and report the output.",
        file=out,
    )
    if env.get(TRACEBACK_ENV):
        traceback.print_exception(type(error), error, error.__traceback__, file=out)
    return INTERNAL_ERROR_EXIT


def main() -> int:
    """The process boundary. See `report_internal_error`."""
    try:
        return run()
    except Exception as error:  # noqa: BLE001 - the boundary is the point
        return report_internal_error("preflight.py", error)


def run() -> int:
    args = parse_args()
    env_path = Path(args.env)
    env, file_values = read_env(env_path)
    check_env_permissions(env_path)
    check_python()
    check_sdk(defer_missing=args.defer_missing_sdk)
    check_existing_traigent_use(Path(args.project_root))
    check_keys(env)
    check_cost_settings(env, file_values)

    models = [model.strip() for model in args.models.split(",") if model.strip()]
    check_models(models)

    if args.dataset:
        check_dataset(
            Path(args.dataset),
            outcome_field=args.outcome_field,
            input_field=args.input_field,
            expected_field=args.expected_field,
            evaluator_method=args.evaluator_method,
        )

    if args.evaluator:
        check_evaluator(Path(args.evaluator))

    # Before anything is printed, not after: a count that cannot be accounted
    # for must not reach the customer's card at all, and the boundary in `main`
    # says so in our name rather than theirs.
    validate_row_count_bounds(RESULTS)

    if args.json:
        print(json.dumps([asdict(result) for result in RESULTS], indent=2))
    else:
        width = max(len(result.check) for result in RESULTS)
        for result in RESULTS:
            print(f"{result.check:<{width}}  {result.status:<4}  {result.detail}")
        counts = {
            status: sum(result.status == status for result in RESULTS)
            for status in (PASS, WARN, FAIL, SKIP)
        }
        print(
            f"\n{counts[PASS]} pass, {counts[WARN]} warn, "
            f"{counts[FAIL]} fail, {counts[SKIP]} skipped"
        )

    if any(result.status == FAIL for result in RESULTS):
        return 1
    if args.strict and any(result.status == WARN for result in RESULTS):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

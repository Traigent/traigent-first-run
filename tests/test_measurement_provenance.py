"""A number reported as measured has to say what it was measured on.

Every fabricated figure found in this package had one shape: a claim that
SOUNDS measured, carrying a number, with nothing beside it that would let a
reader take the measurement again. `the pillar 78 - twelve points for four
levers` is unreachable - no input produces 78 - and it survived review because
nothing in the sentence said which four levers, at which values, under which
scorer. Every one of them was caught by a person reading carefully, and none by
a test.

**This check cannot tell whether a number is right, and does not try.** It
cannot know that the agent pillar of that shape is 83 rather than 78; deriving
that would mean re-implementing the scorer inside the guard. What it can
enforce is one step weaker: a measured number must be RE-DERIVABLE. So
`the agent pillar reads 77` fails, and `the agent pillar reads 77 on the space
in EXCLUDED_KNOB_REASONS` passes - not because 77 is now right, but because
the next reader can go and get 77 for themselves, and find out.

**And it is a floor, not a net. Run against the revisions those five defects
actually shipped in, it flags neither of the two that can be tested that way**
- see `TheNoteWindowIsAFloorTests`, which plants the real one verbatim. Both
sat in long comment runs that named something resolvable in a NEIGHBOURING
paragraph, about a different claim, and the window below is the note rather
than the paragraph. That window is not an oversight and the alternative was
measured: at paragraph granularity both are caught, and seven honest passages
in `readiness.py` go red - three of them because a note says "the space
above", "those four knobs", "the shapes stated", which is how anybody writes a
long argument and is exactly how this repository's own corrections are
written. A rule that reddens the model of doing it right teaches authors to
repeat a citation in every paragraph, and then to stop reading it.

So what this buys is narrower than the issue that asked for it, and worth
saying plainly: a number stated as measured with NOTHING beside it is refused,
which is the shape of the workflow comment that opened #181 and of all five
defects as they were quoted. A number stated as measured inside a paragraph
that cites something else is not. That second half stays a reviewer's job.

WHAT IS IN SCOPE, and why the rest is not
-----------------------------------------
The shipped package - every tracked file under `skills/traigent-first-run/`
plus `GUIDE.md` - and `.github/`. The first is what is copied into a
customer's project, markdown and script comments alike, because three of the
five failures above were script comments and one was a reference document.
The second is there because the claim that opened traigent-first-run#181 was
a workflow comment: CI percentiles under the words "Measured, not guessed",
against a run history that held none of them. A customer never reads a
workflow; the next maintainer does, and that comment sets a timeout.

Measured on the trunk this branch left (`6de98918`), the scan reports 5
sentences: one in `references/evaluation-and-dataset.md` and two in each
script, with `.github/` already clean. All 5 are sourced by this branch and
none is exempted, so the check lands green on work it did rather than on a
list of permissions.

`tests/` and `tools/` are deliberately outside it. The reason is structural
rather than budgetary: a number in a test sits beside the assertion that
produced it, so the derivation this check asks for is already the file. The
budget is the weaker half of the argument and is stated because it is what
would change the answer - run over `tests/` and `tools/` unchanged, the same
scan reports 19 sentences across 8 files, three of them guidance-budget ledger
entries that `tests/test_skill_package.py` already governs by its own rules,
and the other 16 spread across five test files every open branch is editing.
Re-open this if a fabricated number is ever found in a test comment; the
corpus is one pathspec.

Commit messages and pull request bodies are out of reach of any check in a
working tree, and the one figure of the five that lived in a commit message
(`swept exhaustively over 221 760 states`, where the code yields 88 704) is
therefore uncaught by this and stays a reviewer's job.

WHAT COUNTS AS PROVENANCE
-------------------------
One of four, anywhere in the note or paragraph the sentence sits in - the unit
an author writes and a reader reads, not the sentence, because a measurement
is routinely stated in one sentence and sourced in the next:

* a **tracked path** - `references/sdk-execution.md`, resolved against
  `git ls-files`, so a path to a file that does not exist is not provenance;
* a **real symbol** - a backticked name that is a module-level constant, a
  `def`, or a `class` in a tracked `.py`. Resolved by parsing, so a plausible
  name nobody defined fails. Arguments, locals and dataclass fields are NOT
  symbols here: nearly every comment in these scripts names one of those in
  passing, and counting them would make this check pass everything;
* a **stated fixture** - a `key: value` binding whose value is a NUMBER or a
  bracketed list, in a code span, a bracketed literal, or an indented block.
  `max_trials: 12` and `model: [a, b]` are fixtures; `not tuning: temperature,
  prompt_style` is not, because it states no value - and that distinction is
  load-bearing, since the sentence that claimed the unreachable 78 carried
  exactly that second shape. A quoted string is not a value either: `dataset
  score: "this run compares ..."` is a printed line being quoted;
* a **code block** - a fence, which states the inputs by being them.

Prose that describes the inputs without naming anything checkable - "measured
on the strongest realistic opening project" - is deliberately NOT provenance.
It reads like provenance, which is the whole difficulty: `Measured through the
CLI on 28 collected rows with 28 model-written answers: 59 WORKABLE` names a
shape and is still not re-derivable, and the stated fixture in fact scores 45
or 74 and never 59. A name a reader can resolve is the cheapest thing that is
not decoration.

WHICH SENTENCES ARE ASKED
-------------------------
Only a sentence that REPORTS a measurement and carries a bare number. The
grammar is the filter, and it is not decoration either - this package uses
"measured" as an adjective constantly, and a rule that asked every one of them
would be a rule aimed at dishonesty that mostly annoys honest people, which is
the kind that gets deleted. So a report is a measurement word that opens a
clause (`Measured on ...`) or is followed by a preposition of scope, past at
most one adverb (`was measured at ...`, `swept exhaustively over ...`). `A
pillar measured thinly`, `2 of 4 measured`, `never swept`, `not yet measured`,
`the gap is measured with the 0.05 margin` and `an accuracy measured from ten
items` are not reports, and none of them is asked for a source. The last two
are the reason `with` and `from` are not prepositions of scope: one names the
instrument, and the other is a property of any ten items rather than a
measurement anybody took here.

Numbers inside code spans and fences are not claims - they are the shape being
shown - and `81/100` is a printed card line, not a measurement, so neither is
asked either.

THE SECOND WAY A CLAIM GETS PAST THIS
-------------------------------------
The note window above is one; this is the other, and it has the same root.
The provenance test asks whether the note names something that RESOLVES, not
whether the named thing produced the number - deciding that would be the
arithmetic this check refuses to attempt. So a determined author can satisfy
it with a citation that is real and irrelevant, and all three shapes were
tried against the committed check and do pass:

    Measured on this scorer, the agent pillar reads 77 - see `ROOT`.
    Measured on this scorer, the agent pillar reads 77; see GUIDE.md.
    Measured on this scorer, the agent pillar reads 77 (`n: 1`).

Worth having anyway, for the reason the five failures make concrete: none of
them named anything at all, and a citation that is present and wrong is an
object a reviewer can follow and refute in one step, where a missing one
leaves nothing to check. The symbol index is built
from every tracked `.py`, which is what makes `ROOT` resolve; narrowing it to
the shipped scripts would close that shape and would also refuse the honest
citation of a test name, which is the strongest provenance in the package
(`OneRemedyOneQuestionTests.test_un_porting_one_sibling_is_caught_here_and_by
_no_table`, on the comment that used to carry the phantom 59). The wide index
is the deliberate side of that trade; re-open it if decoration ever appears.

Re-derive both figures above with
`python -c "import sys; sys.path.insert(0, 'tests'); import
test_measurement_provenance as m; print(m.scan_tree())"`, and the excluded
corpora by pointing `scan` at another pathspec.

THE ESCAPE HATCH, and why it is a list of quotes
------------------------------------------------
A check with no working exit teaches authors to route around it. That is not
hypothetical here: a guard over flag names, with no exit, led an author to
spell `--verify-against-sdk` without its dashes to get past their own check.

So `UNDERIVABLE` below states a number that genuinely cannot be sourced from
this tree. It is a list of quotes rather than a list of files, and the rules
in `EscapeHatchStaysHonestTests` are what stop it becoming a place to put
things: the file has to be in scope, the quote has to appear in that file
verbatim, and the quote has to STILL BE a violation when scanned on its own.
That last one is the point. An entry whose sentence was reworded, sourced, or
deleted stops corresponding to real text and fails, so the list cannot
accumulate dead permissions the way an allowlist of paths does.
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import tokenize
import unittest
from pathlib import Path
from typing import Iterable, Iterator, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
IN_SCOPE_PATHSPEC = ("skills/traigent-first-run", "GUIDE.md", ".github")
IN_SCOPE_SUFFIXES = (".md", ".py", ".yml", ".yaml")

# Reporting verbs only. `derived`, `observed` and `profiled` were dropped after
# being run over the corpus: this package uses "observed" as the NAME of a
# provenance class ("Observed question, observed answer | 10") and "derived"
# for arithmetic that is visible on the page, so both fired almost entirely on
# sentences making no measurement claim at all.
MEASUREMENT_WORDS = frozenset(
    {
        "measured",
        "re-measured",
        "remeasured",
        "swept",
        "reproduces",
        "reproduced",
        "verified",
        "confirmed",
        "benchmarked",
    }
)
# What a measurement was taken ON. `from` and `with` are deliberately absent:
# "measured with the 0.05 separation margin" names the instrument and
# "an accuracy measured from ten items" is a statistical property of any ten
# items, not a measurement anybody took here - and the second is a hedge this
# package is right to keep, so a rule that reddened it would be pushing in the
# wrong direction.
SCOPE_PREPOSITIONS = frozenset(
    {"on", "over", "across", "through", "against", "at", "twice"}
)

_PUNCTUATION = "()[]{}<>,.;:!?\"'`*_-–—"
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n[ \t]*\n")
# A bare number in prose. Not one inside an identifier, a version, a path, an
# issue reference, or either side of a slash: `81/100` is a card line being
# quoted, and `55/45` is a weighting, and neither is a measurement result.
# `13s` and `1.7M` are numbers wearing a unit, and the CI percentiles that
# opened #181 were all written that way; only a unit this short can follow.
_UNIT = r"(?:s|ms|m|h|k|M|B|kb|MB|GB|%)"
_NUMBER = re.compile(
    r"(?<![\w.#/=$&%-])(\d[\d_]*(?:[ ,]\d{3})*(?:\.\d+)?)"
    rf"{_UNIT}?(?![\w%/-])(?!\.\d)"
)
_CODE_SPAN = re.compile(r"`[^`]+`")
_FENCE = re.compile(r"```.*?```", re.DOTALL)
# A fixture states a QUANTITY or a set of values, so the right-hand side is a
# number or a bracketed list and nothing else. Three looser shapes were tried
# and dropped, each after it passed something it should not have: `blocks=
# False`, a flag, which sat inside the very comment that carried the
# unreproducible 59; `not tuning: temperature, prompt_style`, which names knobs
# and no values, and which is exactly what the sentence claiming the
# unreachable 78 carried; and a quoted string, because `dataset score: "this
# run compares ..."` is a printed line being quoted, not an input being stated.
_BINDING = re.compile(r"(?<![\w.-])[A-Za-z_][\w.-]*\s*[:=]\s*(?:\[|\{|[-+]?\d)")
_PATHLIKE = re.compile(r"[\w][\w./-]*\.(?:md|py|json|jsonl|txt|yaml|yml|lock)\b")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*")
_BRACKETED = re.compile(r"[{\[][^{}\[\]\n]{0,300}[}\]]")


class Claim(NamedTuple):
    """One sentence that reports a measurement and states a number."""

    where: str
    line: int
    sentence: str
    numbers: tuple[str, ...]

    def __str__(self) -> str:
        return (
            f"{self.where}:{self.line}: {', '.join(self.numbers)} - " f"{self.sentence}"
        )


def tracked_files(pathspec: Iterable[str] = ()) -> list[str]:
    """What git publishes, never a filesystem walk.

    A walk needs a hand-maintained list of what to skip and answers a question
    nobody asked - what happens to sit in the working tree. The corpus of this
    check is what ships.
    """
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", *pathspec],
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0:
        raise RuntimeError(
            f"could not list tracked files from git: {listed.stderr.strip()}"
        )
    return [name for name in listed.stdout.split("\0") if name]


def in_scope_files() -> list[Path]:
    """The shipped package: its documents and its scripts."""
    return [
        ROOT / name
        for name in tracked_files(IN_SCOPE_PATHSPEC)
        if name.endswith(IN_SCOPE_SUFFIXES)
    ]


def _resolvable_paths() -> frozenset[str]:
    """Every tracked path, and every suffix of one a document might cite."""
    found: set[str] = set()
    for name in tracked_files():
        parts = name.split("/")
        for index in range(len(parts)):
            found.add("/".join(parts[index:]))
    return frozenset(found)


def _resolvable_symbols() -> frozenset[str]:
    """Module-level constants, functions and classes across the whole tree.

    Not arguments, not locals, not dataclass fields. Those were in an earlier
    draft and made the check vacuous: `blocks=False` appears in the comment
    that carried the unreproducible 59, and `blocks` is a field of `Cap`, so
    counting fields let that exact defect through.
    """
    found: set[str] = set()
    for name in tracked_files():
        if not name.endswith(".py"):
            continue
        try:
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.add(node.name)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                found.update(
                    target.id for target in node.targets if isinstance(target, ast.Name)
                )
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                found.add(node.target.id)
    return frozenset(found)


def _is_distinctive(name: str) -> bool:
    """Does this name point at one definition, or is it an English word?

    `run` is a function in this tree and also the word every other sentence
    here uses, so a backticked `run` resolves and cites nothing - which is how
    the one honest-but-unsourced paragraph in the references first slipped
    past. A citation has to carry an underscore, a capital, or a dot.
    """
    return "_" in name or "." in name or any(letter.isupper() for letter in name)


def _code_regions(unit: str) -> list[str]:
    fences = [match.group(0) for match in _FENCE.finditer(unit)]
    spans = [match.group(0) for match in _CODE_SPAN.finditer(_FENCE.sub(" ", unit))]
    return fences + spans


def provenance(
    unit: str,
    paths: frozenset[str] | None = None,
    symbols: frozenset[str] | None = None,
) -> str | None:
    """What in this note would let a reader take the measurement again."""
    paths = _resolvable_paths() if paths is None else paths
    symbols = _resolvable_symbols() if symbols is None else symbols
    for region in _code_regions(unit):
        if region.startswith("```"):
            return "a code block, which states the inputs by being them"
        if _BINDING.search(region.strip("`")):
            return f"the fixture {region.strip()!r}"
    for literal in _BRACKETED.findall(unit):
        if _BINDING.search(literal):
            return f"the fixture {literal.strip()!r}"
    for line in unit.splitlines():
        if line[:2].isspace() and line.strip() and _BINDING.search(line):
            return f"the fixture {line.strip()!r}"
    for match in _PATHLIKE.finditer(unit):
        if match.group(0) in paths:
            return f"the tracked path {match.group(0)!r}"
    for region in _code_regions(unit):
        for match in _IDENTIFIER.finditer(region.strip("`")):
            if not _is_distinctive(match.group(0)):
                continue
            # Whole, head, and tail: `SubScore.withheld` cites `SubScore`, and
            # a test is cited as `SomeTests.test_the_thing` - both halves of a
            # dotted name are how this repository actually points at code.
            name = match.group(0)
            for candidate in (name, name.split(".")[0], name.rsplit(".", 1)[-1]):
                if candidate in symbols:
                    return f"the symbol {name!r}"
    # This line is what the positive control below rewrites, so that the probe
    # breaks THIS rule rather than something else that might be refusing the
    # planted sentence.
    return None


def _masked(unit: str) -> str:
    """Blank code, keeping offsets: a number shown as code is not a claim."""
    blanked = _FENCE.sub(lambda match: " " * len(match.group(0)), unit)
    return _CODE_SPAN.sub(lambda match: " " * len(match.group(0)), blanked)


def _reports_a_measurement(sentence: str) -> bool:
    """Is a measurement word here doing the work of reporting one?"""
    tokens = sentence.split()
    for index, raw in enumerate(tokens):
        word = raw.strip(_PUNCTUATION).casefold()
        if word not in MEASUREMENT_WORDS:
            continue
        if index == 0:
            return True
        following = [
            token.strip(_PUNCTUATION).casefold() for token in tokens[index + 1 :][:2]
        ]
        if following and following[0].endswith("ly"):
            following = following[1:]
        if following and following[0] in SCOPE_PREPOSITIONS:
            return True
    return False


def claims_in(unit: str, where: str, line: int) -> list[Claim]:
    """Every measurement report in one note, with the numbers it carries.

    The report sentence AND the one after it, because `Measured, not guessed.`
    followed by a line of percentiles is one claim written as two sentences -
    and that is the exact shape of the workflow comment that opened #181. One
    sentence further would start collecting figures from the next argument.
    """
    sentences = [
        " ".join(part.split()) for part in _SENTENCE_BREAK.split(_masked(unit))
    ]
    found: list[Claim] = []
    for index, sentence in enumerate(sentences):
        if not sentence or not _reports_a_measurement(sentence):
            continue
        carried = " ".join(sentences[index : index + 2])
        numbers = tuple(dict.fromkeys(_NUMBER.findall(carried)))
        if numbers:
            found.append(Claim(where, line, sentence, numbers))
    return found


def hash_comment_notes(text: str) -> Iterator[tuple[int, str]]:
    """Each run of `#` lines in a YAML file, whole.

    The claim that opened traigent-first-run#181 was a workflow comment - CI
    percentiles under the words "Measured, not guessed", against a run history
    that held none of them - so the file it lived in is in the corpus rather
    than outside it on the grounds that a customer never reads a workflow. A
    future maintainer does, and that comment sets a timeout.
    """
    block: list[str] = []
    start = 1
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("#"):
            if not block:
                start = number
            body = stripped[1:]
            block.append(body[1:] if body.startswith(" ") else body)
        elif block:
            yield start, "\n".join(block)
            block = []
    if block:
        yield start, "\n".join(block)


def markdown_notes(text: str) -> Iterator[tuple[int, str]]:
    """Blank-line separated blocks, with fenced code kept whole."""
    current: list[str] = []
    start = 1
    inside_fence = False
    for number, raw in enumerate(text.splitlines(), start=1):
        edge = raw.strip().startswith("```")
        if not raw.strip() and not inside_fence:
            if current:
                yield start, "\n".join(current)
                current = []
        else:
            if not current:
                start = number
            current.append(raw)
        if edge:
            inside_fence = not inside_fence
    if current:
        yield start, "\n".join(current)


def python_notes(text: str) -> Iterator[tuple[int, str]]:
    """Each comment run and each docstring, whole.

    A run of `#` lines is one note even when a bare `#` divides it into
    paragraphs, because that is how these scripts source a measurement: the
    figures in one paragraph and the space they were taken on in another.
    """
    block: list[str] = []
    start = 0
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            body = token.string.lstrip("#")
            if not block:
                start = token.start[0]
            block.append(body[1:] if body.startswith(" ") else body)
        elif token.type in (
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
        ):
            continue
        elif block:
            yield start, "\n".join(block)
            block = []
    if block:
        yield start, "\n".join(block)
    for node in ast.walk(ast.parse(text)):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            document = ast.get_docstring(node)
            if document:
                yield getattr(node, "lineno", 1), document


def scan(
    text: str,
    where: str,
    paths: frozenset[str] | None = None,
    symbols: frozenset[str] | None = None,
) -> list[Claim]:
    """Every measured number in one file that nothing beside it can source."""
    paths = _resolvable_paths() if paths is None else paths
    symbols = _resolvable_symbols() if symbols is None else symbols
    if where.endswith(".py"):
        notes: Iterable[tuple[int, str]] = python_notes(text)
    elif where.endswith((".yml", ".yaml")):
        notes = hash_comment_notes(text)
    else:
        notes = markdown_notes(text)
    unsourced: list[Claim] = []
    for line, unit in notes:
        found = claims_in(unit, where, line)
        if found and provenance(unit, paths, symbols) is None:
            unsourced.extend(found)
    return unsourced


def scan_tree() -> list[Claim]:
    paths = _resolvable_paths()
    symbols = _resolvable_symbols()
    unsourced: list[Claim] = []
    for path in in_scope_files():
        unsourced.extend(
            scan(
                path.read_text(encoding="utf-8"),
                str(path.relative_to(ROOT)),
                paths,
                symbols,
            )
        )
    return unsourced


class Underivable(NamedTuple):
    """One number that cannot be sourced from this tree, and why."""

    path: str
    quote: str
    reason: str


# The exit. Empty is the intended steady state - every measured number in the
# package as it stands names something a reader can resolve - and it is kept
# with its rules exercised rather than deleted, because the alternative to a
# sanctioned exit is an author quietly rewording a true sentence until the
# check stops seeing it. It has plausible users: `Measured on the customer's
# own dataset, the score was 62` cannot cite an artifact that exists in this
# tree, and neither can a timing taken on somebody's laptop.
UNDERIVABLE: tuple[Underivable, ...] = ()
UNDERIVABLE_REASON_FLOOR = 120
# A quote identifies ONE claim, not a word that appears in many. Without a
# floor, `Measured` is a legal entry and exempts every claim in the file it
# names; the number requirement is the same rule from the other side, since a
# span carrying no digit cannot be the span carrying the unsourced one.
UNDERIVABLE_QUOTE_FLOOR = 60


def _flattened(text: str) -> str:
    """One line, single-spaced - how a quote is compared to a file.

    A sentence in a comment or a document is wrapped, so a quote pasted as one
    line is not `in` the file text and a quote pasted with the wrapping breaks
    the next time the paragraph reflows. Both compare equal flattened, which
    is also how a claim's sentence is already rendered.
    """
    return " ".join(text.split())


def exempted(claim: Claim, entries: tuple[Underivable, ...]) -> bool:
    """Does a sanctioned entry cover this claim? One home, two callers."""
    return any(
        claim.where == entry.path and _flattened(entry.quote) in claim.sentence
        for entry in entries
    )


class MeasuredNumbersAreReDerivableTests(unittest.TestCase):
    """The corpus, and the probes that prove the scan can see anything."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = _resolvable_paths()
        cls.symbols = _resolvable_symbols()

    def _scan(self, text: str, where: str) -> list[Claim]:
        return scan(text, where, self.paths, self.symbols)

    def test_the_shipped_package_sources_every_number_it_calls_measured(
        self,
    ) -> None:
        offenders = [
            str(claim) for claim in scan_tree() if not exempted(claim, UNDERIVABLE)
        ]
        self.assertEqual(
            offenders,
            [],
            "a number reported as measured, with nothing beside it that would "
            "let a reader take the measurement again. Name the space, the "
            "document, or the function that produces it, anywhere in the same "
            "note: a tracked path, a backticked symbol that is really defined, "
            "a `key: 12` or `key: [a, b]` fixture, or a code fence. Prose "
            "describing the inputs does not count, and neither does a quoted "
            "string. If the number genuinely cannot be taken again from this "
            "tree, add it to UNDERIVABLE with the sentence quoted and the "
            "reason.",
        )

    def test_the_corpus_is_the_shipped_package_and_is_not_empty(self) -> None:
        """A scanner whose corpus narrows goes green by seeing nothing."""
        names = {str(path.relative_to(ROOT)) for path in in_scope_files()}
        self.assertIn("GUIDE.md", names)
        self.assertIn("skills/traigent-first-run/SKILL.md", names)
        self.assertIn("skills/traigent-first-run/scripts/readiness.py", names)
        self.assertIn("skills/traigent-first-run/scripts/preflight.py", names)
        self.assertIn(
            ".github/workflows/validate.yml",
            names,
            "the claim that opened #181 was a workflow comment, so dropping "
            "the workflows from the corpus drops the originating case",
        )
        self.assertIn(
            "skills/traigent-first-run/references/run-safety.md",
            names,
            "the references are the depth behind each stage and carry most of "
            "the numbers a customer reads",
        )
        # Every markdown and script in the bundle, not a curated subset.
        published = {
            name
            for name in tracked_files(IN_SCOPE_PATHSPEC)
            if name.endswith(IN_SCOPE_SUFFIXES)
        }
        self.assertEqual(names, published)

    # ------------------------------------------------------------------
    # The five failures, planted. Each is quoted as it was found, and each
    # is planted twice: once as it stood, and once with a source added.
    # The scan being green on the tree says nothing about whether it can
    # SEE any of them, which is the defect class this repository spent the
    # week removing from its own guards.
    # ------------------------------------------------------------------
    UNSOURCED_AND_FIXED = (
        (
            "the agent pillar against a figure whose document is never named",
            "Measured on this scorer, the agent pillar reads 77 against 61.",
            "Measured on this scorer, the agent pillar reads 77 against 61 - "
            "both re-derivable from the space quoted in "
            "`_reject_synonym_spellings`.",
        ),
        (
            "an overall score that the stated inputs do not determine",
            "Measured, 59 WORKABLE / OK / proceed became 59 WORKABLE / OK / "
            "review-answer-key.",
            "Measured on `{rows: 28, config_space: None}` through the CLI, "
            "45 PARTIAL became 74 WORKABLE.",
        ),
        (
            "a sweep size that does not reproduce",
            "The card line was swept exhaustively over 221 760 states.",
            "The card line was swept exhaustively over 88 704 states of "
            "`score_evaluation`.",
        ),
        (
            "a pillar score no input can produce",
            "Measured on this scorer, the pillar 78 - twelve points for "
            "bringing four levers instead of three.",
            "Measured on this scorer over "
            "`{model: 3, thinking_shape: 2, reflect: 2}`, the pillar 83.",
        ),
        (
            "a claim generalised past the one shape it was taken on",
            "Measured on this scorer, deleting the field can never raise "
            "this score: one space scored 70 and the same space 100.",
            "Measured on one 10 000-configuration space with "
            "`max_trials: 12`, this pillar scored 70, and 100 with the field "
            "omitted.",
        ),
    )

    def test_each_of_the_five_real_failures_is_seen_in_a_document(self) -> None:
        for label, broken, _ in self.UNSOURCED_AND_FIXED:
            with self.subTest(label=label):
                found = self._scan(broken, "skills/traigent-first-run/SKILL.md")
                self.assertNotEqual(
                    found,
                    [],
                    f"{label}: planted in a shipped document and not seen",
                )
                self.assertTrue(
                    all(claim.numbers for claim in found),
                    "the failure has to name the number, not only the file",
                )

    def test_each_of_the_five_real_failures_is_seen_in_a_script_comment(
        self,
    ) -> None:
        """Three of the five were comments in a script, not prose."""
        for label, broken, _ in self.UNSOURCED_AND_FIXED:
            with self.subTest(label=label):
                planted = "\n".join(f"# {line}" for line in broken.splitlines())
                found = self._scan(
                    f"{planted}\nVALUE = 1\n",
                    "skills/traigent-first-run/scripts/readiness.py",
                )
                self.assertNotEqual(found, [], f"{label}: comment not seen")

    def test_the_workflow_claim_that_opened_the_issue_is_seen(self) -> None:
        """The originating case: "Measured, not guessed" over CI percentiles.

        Planted in a workflow comment, because that is where it was, and the
        corpus was widened to `.github/` for it. The fixed form is the one
        `validate.yml` carries today - the window, the sample size, and the
        command that reads it - and it has to pass, or the file this check was
        written for could not satisfy it.
        """
        broken = (
            "# Measured, not guessed.\n"
            "# Durations: 13s min / 19s p50 / 31s p95 / 32s max.\n"
            "timeout-minutes: 19\n"
        )
        found = self._scan(broken, ".github/workflows/validate.yml")
        self.assertNotEqual(found, [], "the claim that opened #181 is not seen")
        fixed = (
            "# Measured, and re-derivable. Source: every successful job on\n"
            "# `first-run-guide`, n=65, read with `gh run list --workflow\n"
            "# validate.yml`. Durations: 13s min / 19s p50 / 32s max.\n"
            "timeout-minutes: 19\n"
        )
        self.assertEqual(self._scan(fixed, ".github/workflows/validate.yml"), [])

    def test_the_fixed_form_of_each_failure_passes(self) -> None:
        """Or the check is a wall rather than a rule, and gets routed around."""
        for label, _, fixed in self.UNSOURCED_AND_FIXED:
            with self.subTest(label=label):
                self.assertEqual(
                    self._scan(fixed, "skills/traigent-first-run/SKILL.md"),
                    [],
                    f"{label}: sourced and still refused",
                )

    def test_a_failure_names_the_file_and_the_number(self) -> None:
        """A message naming neither is a message nobody can act on."""
        planted = "Measured on this scorer, the agent pillar reads 77."
        found = self._scan(planted, "skills/traigent-first-run/references/x.md")
        self.assertEqual(len(found), 1)
        rendered = str(found[0])
        self.assertIn("skills/traigent-first-run/references/x.md", rendered)
        self.assertIn("77", rendered)

    def test_neutering_the_scan_lets_a_planted_violation_through(self) -> None:
        """The positive control: prove the plant is caught BY the rule.

        Every assertion above could hold with the corpus empty and the rule
        inert. This one breaks the rule on purpose - provenance answered for
        everything - and requires the planted sentence to survive it, so a
        green tree is evidence about the check and not only about the tree.
        """
        planted = "Measured on this scorer, the agent pillar reads 77 against 61."
        self.assertNotEqual(self._scan(planted, "x.md"), [])
        source = Path(__file__).read_text(encoding="utf-8")
        anchor = "    return None\n\n\ndef _masked"
        self.assertIn(
            anchor,
            source,
            "the rule moved, so this probe would prove nothing - point it at "
            "wherever `provenance` now answers that it found nothing",
        )
        neutered = source.replace(anchor, '    return "neutered"\n\n\ndef _masked')
        namespace: dict[str, object] = {
            "__name__": "neutered_provenance",
            "__file__": __file__,
        }
        exec(compile(neutered, "<neutered>", "exec"), namespace)  # noqa: S102
        blind = namespace["scan"]
        blind_claims = namespace["claims_in"]
        assert callable(blind) and callable(blind_claims)
        # Vacuity guard. `blind` returning nothing would also be satisfied by a
        # neutered module that can no longer SEE the sentence at all, which
        # would make this probe agree with itself. So the neutered module has
        # to still find the claim, and differ only in whether it reports it.
        self.assertNotEqual(
            blind_claims(planted, "x.md", 1),
            [],
            "the neutered module stopped seeing the claim, so its silence "
            "says nothing about the rule this probe removed",
        )
        self.assertEqual(
            blind(planted, "x.md", self.paths, self.symbols),
            [],
            "with provenance always answered, the planted claim must pass - "
            "if it still fails, something other than the rule is refusing it",
        )


class OnlyAReportedMeasurementIsAskedTests(unittest.TestCase):
    """The grammar, because it is the whole false-red budget."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = _resolvable_paths()
        cls.symbols = _resolvable_symbols()

    def _scan(self, text: str) -> list[Claim]:
        return scan(
            text, "skills/traigent-first-run/SKILL.md", self.paths, self.symbols
        )

    def test_the_report_shapes_are_asked(self) -> None:
        for sentence in (
            "Measured on this scorer, the pillar reads 78.",
            "The pillar was measured at 78 by this branch.",
            "The card line was swept exhaustively over 221 760 states.",
            "Re-measured across the same rows, the dataset pillar reads 45.",
        ):
            with self.subTest(sentence=sentence):
                self.assertNotEqual(self._scan(sentence), [])

    def test_the_shapes_that_are_not_reports_are_left_alone(self) -> None:
        """Each of these is real text from this package, or its shape.

        A rule aimed at dishonesty that mostly annoys honest people gets
        disabled, so the honest uses are pinned here rather than left to be
        rediscovered by whoever the check next reddens.
        """
        for sentence in (
            "A pillar measured thinly cannot carry a strong verdict, so 89 "
            "falls inside the Strong range without contradicting it.",
            "That is why 2 of 4 measured is not 100.",
            "Temperature is pinned at 0 in both, never swept.",
            "Report an uncalibrated evaluator as not yet measured, never as "
            "absent, in all 7 of these states.",
            "One standard error on an accuracy measured from ten items is "
            "about 15 points near 50%.",
            "The gap is measured with the 0.05 normalized separation margin.",
            "Under either, nothing was measured, and stage 6 is where the "
            "answer is carried.",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(self._scan(sentence), [])

    def test_an_honest_small_sample_disclosure_passes(self) -> None:
        """The package's best feature must survive its own check.

        Ten rows and three observations a side cannot settle anything, and
        saying so is the correct disclosure. A rule demanding rigour behind
        every number would push exactly the wrong way here.
        """
        for sentence in (
            "Measured on three observations a side, which cannot settle the "
            "question either way.",
            "Measured on ten held-out rows, the interval is roughly +/-31 "
            "points and the gap is inconclusive.",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(
                    self._scan(f"{sentence} See `references/run-safety.md`."),
                    [],
                )

    def test_a_number_shown_as_code_is_not_a_claim(self) -> None:
        self.assertEqual(
            self._scan("Measured on this scorer, the pillar reads `78`."),
            [],
        )

    def test_a_printed_card_fraction_is_not_a_measurement_result(self) -> None:
        self.assertEqual(
            self._scan("Measured on this scorer, it prints EVALUATION 75/100."),
            [],
        )


class WhatCountsAsProvenanceTests(unittest.TestCase):
    """Four shapes pass, and decoration does not."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = _resolvable_paths()
        cls.symbols = _resolvable_symbols()

    def _provenance(self, unit: str) -> str | None:
        return provenance(unit, self.paths, self.symbols)

    def test_a_tracked_path_is_provenance_and_an_invented_one_is_not(self) -> None:
        self.assertIsNotNone(
            self._provenance("Measured on 12 rows, see references/run-safety.md.")
        )
        self.assertIsNone(
            self._provenance("Measured on 12 rows, see references/no-such-file.md.")
        )

    def test_a_real_symbol_is_provenance_and_a_plausible_name_is_not(self) -> None:
        self.assertIsNotNone(
            self._provenance("Measured on the space in `EXCLUDED_KNOB_REASONS`: 77.")
        )
        self.assertIsNone(
            self._provenance("Measured on the space in `EXCLUDED_KNOB_WEIGHTS`: 77.")
        )

    def test_an_argument_or_a_field_is_not_a_symbol(self) -> None:
        """`blocks=False` sat in the comment that carried the phantom 59."""
        self.assertIsNone(self._provenance("Measured: 59, with `blocks=False`."))

    def test_a_binding_needs_a_value_to_be_a_fixture(self) -> None:
        self.assertIsNotNone(self._provenance("Measured on `max_trials: 12`: 70."))
        self.assertIsNone(
            self._provenance(
                "Measured: the pillar 78, with an evidence line reading "
                "`not tuning: temperature, prompt_style`."
            )
        )

    def test_a_bracketed_literal_and_an_indented_block_are_fixtures(self) -> None:
        self.assertIsNotNone(
            self._provenance("Measured on {model: 3 values, temperature: 2}: 83.")
        )
        self.assertIsNotNone(
            self._provenance("Measured, the pillar 83:\n\n    max_trials: 12\n")
        )

    def test_a_code_fence_is_a_fixture(self) -> None:
        self.assertIsNotNone(
            self._provenance('Measured, 83:\n\n```json\n{"max_trials": 12}\n```\n')
        )

    def test_the_documented_floor_is_where_the_docstring_says_it_is(self) -> None:
        """A citation that resolves and is irrelevant still passes.

        The module docstring says so; this is the assertion that keeps that
        paragraph true. If a future tightening closes one of these, this test
        fails and the prose gets corrected in the same commit - which is the
        opposite of a documented limitation nobody re-checks.
        """
        for decoration in (
            "Measured on this scorer, the agent pillar reads 77 - see `ROOT`.",
            "Measured on this scorer, the agent pillar reads 77; see GUIDE.md.",
            "Measured on this scorer, the agent pillar reads 77 (`n: 1`).",
        ):
            with self.subTest(decoration=decoration):
                self.assertIsNotNone(self._provenance(decoration))

    def test_prose_describing_the_inputs_is_not_provenance(self) -> None:
        """It reads like provenance, which is why it has to be named here."""
        self.assertIsNone(
            self._provenance(
                "Measured on the strongest realistic opening project, 200 "
                "production rows, difficulty-tagged, evaluator calibrated: 94."
            )
        )


class TheNoteWindowIsAFloorTests(unittest.TestCase):
    """What the note window misses, pinned rather than described.

    A limitation in a docstring is a sentence nobody re-checks, and this file
    exists because of exactly that. So the miss is an assertion: if anybody
    narrows the window, this fails and the paragraph above it gets rewritten
    in the same commit.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = _resolvable_paths()
        cls.symbols = _resolvable_symbols()

    # `readiness.py` at b2983c57^, trimmed to the two paragraphs that matter.
    # The first sources a claim about `coverage`; the second states the pillar
    # figures that turned out to be unreachable, and names knobs without any
    # values - `not tuning: temperature, prompt_style` states no value, so it
    # is not a fixture. The two are neighbours in one comment run.
    UNREACHABLE_78_AS_IT_SHIPPED = "\n".join(
        (
            "# The second is worse, and it is measured. `present` was built",
            "# from `scoreable`, which includes PINNED knobs, so coverage",
            "# graded whether the catalog names appeared in the document. A",
            "# space declaring `model: [a], temperature: [0], prompt_style:",
            "# [direct]` scored coverage 25/25, full marks.",
            "#",
            "# And it punished better knobs. Measured on this scorer: `model,",
            "# temperature, prompt_style` (the general catalog, exactly)",
            "# scores coverage 25/25 and the pillar 90, while `model,",
            "# thinking_shape, reflect, self_consistency` scores 8.33/25 and",
            "# the pillar 78 - twelve points for bringing four levers instead",
            "# of three, with an evidence line reading `not tuning:",
            "# temperature, prompt_style`.",
            "VALUE = 1",
        )
    )

    def test_the_defect_as_it_shipped_is_not_caught_by_this_check(self) -> None:
        """The honest half of the claim this file makes."""
        where = "skills/traigent-first-run/scripts/readiness.py"
        self.assertEqual(
            scan(self.UNREACHABLE_78_AS_IT_SHIPPED, where, self.paths, self.symbols),
            [],
            "the note window now catches this, which is better than it was - "
            "correct the module docstring, which currently says it does not",
        )

    def test_the_same_claim_standing_alone_is_caught(self) -> None:
        """And the half it does deliver, so the floor has a floor."""
        alone = "\n".join(
            (
                "# And it punished better knobs. Measured on this scorer:",
                "# `model, temperature, prompt_style` scores the pillar 90,",
                "# while `model, thinking_shape, reflect, self_consistency`",
                "# scores the pillar 78.",
                "VALUE = 1",
            )
        )
        where = "skills/traigent-first-run/scripts/readiness.py"
        found = scan(alone, where, self.paths, self.symbols)
        self.assertNotEqual(found, [])
        self.assertIn("78", found[0].numbers)

    def test_the_neighbouring_fixture_is_what_sources_it(self) -> None:
        """Name the mechanism, so the miss is understood and not just known."""
        first, second = self.UNREACHABLE_78_AS_IT_SHIPPED.split("#\n")
        self.assertIsNotNone(provenance(first, self.paths, self.symbols))
        self.assertIsNone(provenance(second, self.paths, self.symbols))


class EscapeHatchStaysHonestTests(unittest.TestCase):
    """An exit that cannot rot, or authors route around the check instead."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = _resolvable_paths()
        cls.symbols = _resolvable_symbols()

    def _defects(
        self,
        entries: tuple[Underivable, ...],
        invented: dict[str, str] | None = None,
    ) -> list[str]:
        """Every way this list stops corresponding to real, refused text.

        `invented` supplies file bodies so these rules can be exercised
        against a tree that does not exist, rather than by welding a sentence
        out of `SKILL.md` into a test - which is the defect class this whole
        file is about, one level up.
        """
        in_scope = {str(path.relative_to(ROOT)) for path in in_scope_files()}
        defects: list[str] = []
        for entry in entries:
            quote = _flattened(entry.quote)
            if entry.path not in in_scope:
                defects.append(f"{entry.path}: not a file this check reads")
                continue
            if len(quote) < UNDERIVABLE_QUOTE_FLOOR or not any(
                character.isdigit() for character in quote
            ):
                defects.append(
                    f"{entry.path}: {entry.quote!r} is too short or carries no "
                    f"number, so it names a word rather than one claim - "
                    f"quote at least {UNDERIVABLE_QUOTE_FLOOR} characters of "
                    "the sentence, including the figure it states"
                )
                continue
            body = (
                (ROOT / entry.path).read_text(encoding="utf-8")
                if invented is None
                else invented.get(entry.path, "")
            )
            if quote not in _flattened(body):
                defects.append(
                    f"{entry.path}: {entry.quote!r} is no longer in the file"
                )
                continue
            if not scan(entry.quote, entry.path, self.paths, self.symbols):
                defects.append(
                    f"{entry.path}: {entry.quote!r} is not refused any more, "
                    "so this entry permits nothing"
                )
            if len(entry.reason) < UNDERIVABLE_REASON_FLOOR:
                defects.append(
                    f"{entry.path}: {len(entry.reason)} characters of reason, "
                    f"under the {UNDERIVABLE_REASON_FLOOR} floor"
                )
        return defects

    def test_the_committed_list_corresponds_to_real_refused_text(self) -> None:
        self.assertEqual(self._defects(UNDERIVABLE), [])

    def test_a_one_word_quote_that_would_exempt_a_whole_file_fails(self) -> None:
        """Without a floor, `Measured` is a legal entry and blankets a file."""
        blanket = Underivable(
            "skills/traigent-first-run/SKILL.md",
            "Measured",
            "a reason long enough to clear the floor, stating why this "
            "particular number cannot be taken again from anything in this "
            "tree, and what a reader should do instead of trying.",
        )
        self.assertIn(
            "names a word rather than one claim", " ".join(self._defects((blanket,)))
        )

    def test_a_quote_carrying_no_number_fails(self) -> None:
        """The span that carries no figure is not the span being exempted."""
        numberless = Underivable(
            "skills/traigent-first-run/SKILL.md",
            "Measured on a scorer this repository has never written down and "
            "does not ship, on a project nobody here can open",
            "a reason long enough to clear the floor, stating why this "
            "particular number cannot be taken again from anything in this "
            "tree, and what a reader should do instead of trying.",
        )
        self.assertNotEqual(self._defects((numberless,)), [])

    def test_a_quote_is_compared_flattened_so_a_reflow_does_not_break_it(
        self,
    ) -> None:
        """Or the only writable entry is one that dies at the next rewrap."""
        wrapped = "Measured on this scorer, the agent\n    pillar reads 77."
        flat = "Measured on this scorer, the agent pillar reads 77."
        self.assertEqual(_flattened(wrapped), flat)
        self.assertIn(_flattened(flat), _flattened(f"...{wrapped}..."))

    def test_an_entry_quoting_text_that_moved_on_fails(self) -> None:
        """The rot case: the sentence was reworded and the permission stayed."""
        stale = Underivable(
            "skills/traigent-first-run/SKILL.md",
            "Measured on a scorer nobody ever wrote, the pillar reads 77.",
            "a reason long enough to clear the floor, stating why this "
            "particular number cannot be taken again from anything in this "
            "tree, and what a reader should do instead of trying.",
        )
        self.assertNotEqual(self._defects((stale,)), [])

    def test_an_entry_for_a_sentence_that_is_no_longer_refused_fails(self) -> None:
        """The other rot: the text got a source and the permission stayed.

        This is the half an allowlist of paths cannot have. The sentence is
        still there, still quoted verbatim, still long enough - and somebody
        has since named `EXCLUDED_KNOB_REASONS` beside it, so the check would
        pass it anyway and the permission is now doing nothing but standing
        there looking necessary.
        """
        quote = (
            "Measured on the space in `EXCLUDED_KNOB_REASONS`, the agent "
            "pillar reads 77 against 61."
        )
        sourced = Underivable(
            "skills/traigent-first-run/SKILL.md",
            quote,
            "a reason long enough to clear the floor, stating why this "
            "particular number cannot be taken again from anything in this "
            "tree, and what a reader should do instead of trying.",
        )
        self.assertIn(
            "permits nothing",
            " ".join(
                self._defects((sourced,), {"skills/traigent-first-run/SKILL.md": quote})
            ),
        )

    def test_an_entry_still_refused_and_fully_stated_is_accepted(self) -> None:
        """The hatch has to accept something, or it is not an exit."""
        quote = "Measured on this scorer, the agent pillar reads 77 against 61."
        allowed = Underivable(
            "skills/traigent-first-run/SKILL.md",
            quote,
            "a reason long enough to clear the floor, stating why this "
            "particular number cannot be taken again from anything in this "
            "tree, and what a reader should do instead of trying.",
        )
        self.assertEqual(
            self._defects(
                (allowed,), {"skills/traigent-first-run/SKILL.md": f"Note.\n{quote}\n"}
            ),
            [],
        )

    def test_an_entry_outside_the_corpus_fails(self) -> None:
        outside = Underivable(
            "tests/test_measurement_provenance.py",
            "Measured on this scorer, the agent pillar reads 77.",
            "a reason long enough to clear the floor, stating why this "
            "particular number cannot be taken again from anything in this "
            "tree, and what a reader should do instead of trying.",
        )
        self.assertNotEqual(self._defects((outside,)), [])

    def test_an_entry_with_a_label_instead_of_a_reason_fails(self) -> None:
        labelled = Underivable(
            "skills/traigent-first-run/SKILL.md",
            "Measured on this scorer, the agent pillar reads 77.",
            "external",
        )
        self.assertNotEqual(self._defects((labelled,)), [])

    def test_an_exempted_sentence_really_is_skipped(self) -> None:
        """The hatch has to work, or it is a wall with a sign on it."""
        sentence = "Measured on this scorer, the agent pillar reads 77."
        claims = scan(sentence, "x.md", self.paths, self.symbols)
        self.assertNotEqual(claims, [])
        entry = Underivable("x.md", sentence, "why" * 60)
        self.assertEqual(
            [claim for claim in claims if not exempted(claim, (entry,))], []
        )
        # And an entry for a DIFFERENT sentence does not cover this one.
        other = Underivable("x.md", "Measured on the other scorer, it reads 42.", "")
        self.assertNotEqual(
            [claim for claim in claims if not exempted(claim, (other,))], []
        )


if __name__ == "__main__":
    unittest.main()

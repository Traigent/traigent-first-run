"""The census classifier is probed, because a census cannot fail on its own.

`tools/guard_census.py` produces the table traigent-first-run#214 rests on. A
scanner that stops matching reports an empty result, and an empty result reads
exactly like a clean repository - so a classifier that quietly answered
`structural` for every test would report that this repository has no
presence-welds at all, which is the most flattering possible answer and the
one nobody would question.

So each class is proven reachable on an invented source whose shape is known,
and the two boundaries that decide the headline number are probed in both
directions:

* a prose `assertIn` against a DOCUMENT is a weld; the same assertion against
  something the code PRODUCED is not, and folding the second into the first
  would overstate the defect;
* a needle typed one line up, in the `for phrase in (...)` loop this
  repository writes most of its welds as, is still a typed needle.

The totals themselves are deliberately not pinned here. Every branch that adds
a test would have to edit the pin, and a number renegotiated per branch is the
weld this audit exists to count.
"""

from __future__ import annotations

import ast
import itertools
import pathlib
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import guard_census  # noqa: E402

_PROBE_SERIAL = itertools.count()


def flatten(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    tests: list[unittest.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            tests.extend(flatten(item))
        else:
            tests.append(item)
    return tests


def discovery_key(test: unittest.TestCase, label: str) -> str:
    """One discovered test as the census keys it: `path::Class::method`."""
    cls = type(test)
    if cls.__module__ == "unittest.loader":
        # `_FailedTest` stands in for a whole module that would not import, so
        # every test in it silently vanishes from the comparison below. Loud,
        # because a shrinking denominator that reads as agreement is the exact
        # failure these comparisons exist to catch.
        raise AssertionError(f"a test module did not import: {test}")
    return f"{label}::{cls.__name__}::{test._testMethodName}"


def repository_key(test: unittest.TestCase) -> str:
    """One test discovered from `tests/`, keyed the way the census keys it."""
    cls = type(test)
    if cls.__module__ == "unittest.loader":
        raise AssertionError(f"a test module did not import: {test}")
    module = sys.modules[cls.__module__]
    path = pathlib.Path(module.__file__).resolve().relative_to(REPO_ROOT)
    return discovery_key(test, str(path))


# Deliberately NOT path-shaped, though the census's real labels are paths.
# Spelling a plausible test path here would write an anchored reference to a
# file this package does not ship, and
# `test_no_tracked_file_names_a_bundled_path_that_does_not_ship` reads every
# tracked file for exactly that - correctly, because a reader who followed it
# would find nothing. The label is only a prefix on the keys below, so it costs
# the probes nothing to say plainly that no such file exists.
PROBE_LABEL = "an invented file"


def runner_keys(source: str, label: str = PROBE_LABEL) -> set[str]:
    """What unittest's own discovery collects from one invented file.

    Written to disk and discovered rather than predicted. The expectation for
    every shape probed below is then the runner's answer, not this file's
    opinion of what the runner does - which is the thing the census was wrong
    about in the first place.

    A fresh module name per call, because `discover` imports by name: a second
    file called `test_probe` would be served out of `sys.modules` and the probe
    would silently measure the previous source.
    """
    name = f"test_probe_{next(_PROBE_SERIAL)}"
    with tempfile.TemporaryDirectory() as scratch:
        root = pathlib.Path(scratch) / "tests"
        root.mkdir()
        (root / f"{name}.py").write_text(source, encoding="utf-8")
        try:
            suite = unittest.TestLoader().discover(str(root))
            return {discovery_key(test, label) for test in flatten(suite)}
        finally:
            sys.modules.pop(name, None)
            while str(root) in sys.path:
                sys.path.remove(str(root))


def census_keys(source: str, label: str = PROBE_LABEL) -> set[str]:
    """What the census files for the same invented file."""
    entries, _ = guard_census.file_entries(ast.parse(source), label)
    return set(entries)


def classify(source: str) -> str:
    """The primary class of the single test method in `source`."""
    tree = ast.parse(source)
    aliases = guard_census._guarded_aliases(tree)
    helpers = guard_census._module_helpers(tree)
    corpora = guard_census._corpus_helpers(helpers)
    containers = guard_census._prose_containers(tree)
    reaching = {
        name
        for name, nodes in helpers.items()
        if any(guard_census._reaches_code(node, aliases, set()) for node in nodes)
    }
    methods = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test")
    ]
    if len(methods) != 1:
        raise AssertionError(f"expected exactly one test method, found {len(methods)}")
    primary, _ = guard_census.classify_method(
        methods[0], aliases, corpora, reaching, containers
    )
    return primary


LOADS_A_SCRIPT = (
    "import importlib.util\n"
    'SPEC = importlib.util.spec_from_file_location("s", SCRIPT)\n'
    "MODULE = importlib.util.module_from_spec(SPEC)\n"
)
SWEEPS = "def documents():\n    return sorted(ROOT.glob('*.md'))\n"


class GuardCensusClassifierTests(unittest.TestCase):
    def test_every_class_is_reachable(self) -> None:
        """The one failure that would make the census flatter than the truth."""
        cases = {
            "derived": LOADS_A_SCRIPT
            + (
                "class T:\n"
                "    def test_x(self):\n"
                "        self.assertEqual(MODULE.score(row), 4)\n"
            ),
            "scanner": SWEEPS
            + (
                "class T:\n"
                "    def test_x(self):\n"
                "        for path in documents():\n"
                "            self.assertTrue(path.exists())\n"
            ),
            "presence-weld": (
                "class T:\n"
                "    def test_x(self):\n"
                "        skill = SKILL.read_text()\n"
                '        self.assertIn("the same 48 whatever the customer '
                'brings", skill)\n'
            ),
            "vocabulary-ban": (
                "class T:\n"
                "    def test_x(self):\n"
                "        skill = SKILL.read_text()\n"
                '        self.assertNotIn("cold start", skill)\n'
            ),
            "output-assert": LOADS_A_SCRIPT
            + (
                "class T:\n"
                "    def test_x(self):\n"
                "        card = render(rows)\n"
                '        self.assertIn("no held-out set", card.stdout)\n'
            ),
            "structural": (
                "class T:\n"
                "    def test_x(self):\n"
                "        self.assertEqual(sorted(labels), [1, 2, 3])\n"
            ),
        }
        self.assertEqual(sorted(cases), sorted(guard_census.CLASSES))
        for expected, source in sorted(cases.items()):
            with self.subTest(expected=expected):
                self.assertEqual(classify(source), expected)

    def test_a_weld_and_an_output_assert_are_told_apart_by_the_haystack(self) -> None:
        """The boundary the headline number depends on.

        Same needle, same assertion, same wording. One is pinned to a file
        somebody types; the other is pinned to what the code printed, and only
        the first can pass while the fact underneath it drifts.
        """
        needle = '"3 models x 4 binary knobs = 48"'
        against_document = (
            "class T:\n"
            "    def test_x(self):\n"
            "        safety = RUN_SAFETY.read_text()\n"
            f"        self.assertIn({needle}, safety)\n"
        )
        against_output = LOADS_A_SCRIPT + (
            "class T:\n"
            "    def test_x(self):\n"
            "        printed = MODULE.render(space)\n"
            f"        self.assertIn({needle}, printed)\n"
        )
        self.assertEqual(classify(against_document), "presence-weld")
        self.assertEqual(classify(against_output), "derived")
        # `derived` wins on precedence there because the test reaches the code.
        # Strip that and the residue is the class it belongs to, not a weld.
        self.assertEqual(
            classify(
                "class T:\n"
                "    def test_x(self):\n"
                "        printed = capture.getvalue()\n"
                f"        self.assertIn({needle}, printed)\n"
            ),
            "output-assert",
        )

    def test_a_needle_typed_one_line_up_is_still_typed(self) -> None:
        """How most of this repository's welds are actually written.

        Missing this reported 68 welds where there are 123, so the shape is
        not a detail - it is a third of the finding.
        """
        loop = (
            "class T:\n"
            "    def test_x(self):\n"
            "        skill = SKILL.read_text()\n"
            '        for phrase in ("the same 48 whatever", "a held-out set"):\n'
            "            with self.subTest(phrase=phrase):\n"
            "                self.assertIn(phrase, skill)\n"
        )
        self.assertEqual(classify(loop), "presence-weld")
        registry = (
            'PHRASES = ("the same 48 whatever", "a held-out set")\n'
            "class T:\n"
            "    def test_x(self):\n"
            "        skill = SKILL.read_text()\n"
            "        for phrase in PHRASES:\n"
            "            self.assertIn(phrase, skill)\n"
        )
        self.assertEqual(classify(registry), "presence-weld")
        # A computed needle is not typed, and must not be counted as one.
        derived_needle = (
            "class T:\n"
            "    def test_x(self):\n"
            "        skill = SKILL.read_text()\n"
            "        total = product(widths)\n"
            '        self.assertIn(f"= {total}", skill)\n'
        )
        self.assertEqual(classify(derived_needle), "structural")

    def test_the_census_reads_every_test_the_runner_would(self) -> None:
        """A glob that narrows would shrink the denominator, silently.

        The classifier is only as honest as the set it walks, and `rglob` is
        the corpus mistake this audit found five times elsewhere.

        Compared BY NAME, in both directions, because a count could not say
        what was wrong. This failed once with "1622 != 1623" and the reader had
        no way to tell an over-counted shape from a missed file from a race of
        their own making - the suite discovers at start, the census reads the
        disk mid-run, and a test file edited in between makes them differ for
        an entirely uninteresting reason (#400). The two lists name the test,
        and the side it is on says which of those it was.
        """
        result = census_totals()
        counted = set(result["per_test"])
        discovered = {
            repository_key(test)
            for test in flatten(
                unittest.TestLoader().discover(str(REPO_ROOT / "tests"))
            )
        }
        self.assertEqual(
            sorted(counted - discovered),
            [],
            "the census counts these, and unittest would not run them: a "
            "nested def, a class that is not a TestCase, or a file edited "
            "since discovery ran",
        )
        self.assertEqual(
            sorted(discovered - counted),
            [],
            "unittest runs these and the census does not read them, so every "
            "share in the table is over a denominator missing them",
        )
        # One call, one answer. `tests` is derived from `per_test` and the
        # per-file counters are built from the same entries, so a disagreement
        # here means the derivation was undone rather than that a number moved.
        self.assertEqual(result["tests"], len(counted))
        self.assertEqual(sum(result["total"].values()), len(counted))
        self.assertGreater(len(discovered), 100, len(discovered))

    def test_a_nested_test_function_is_not_a_test_the_runner_runs(self) -> None:
        """The first of the two over-counts, and the cheaper one to write.

        `ast.walk` sees any `def` whose name starts with `test`, including one
        defined inside another test's body. unittest sees a method on a class;
        a local function is not one, so counting it inflated the denominator
        every share in the census table is taken over.
        """
        source = (
            "import unittest\n"
            "class NestingTests(unittest.TestCase):\n"
            "    def test_outer(self):\n"
            "        def test_inner():\n"
            "            self.assertEqual(3, 3)\n"
            "        test_inner()\n"
        )
        keys = census_keys(source)
        self.assertEqual(keys, runner_keys(source))
        self.assertEqual(keys, {f"{PROBE_LABEL}::NestingTests::test_outer"})

    def test_a_test_method_outside_a_test_case_is_not_counted(self) -> None:
        """The second over-count, and this file writes it on every page.

        The fixtures above are `class T:` with a `def test_x` in them, because
        a bare class is the shortest thing to parse. unittest collects none of
        them. A census that counts them reports tests nobody can run.
        """
        source = (
            "import unittest\n"
            "class Real(unittest.TestCase):\n"
            "    def test_runs(self):\n"
            "        self.assertTrue(True)\n"
            "class NotATestCase:\n"
            "    def test_never_runs(self):\n"
            "        raise AssertionError('unittest would never collect this')\n"
        )
        keys = census_keys(source)
        self.assertEqual(keys, runner_keys(source))
        self.assertEqual(keys, {f"{PROBE_LABEL}::Real::test_runs"})

    def test_two_same_named_methods_in_different_classes_are_two_entries(self) -> None:
        """The collision that made one call answer its own question twice.

        Under a `path::method` key these two collapsed to one entry while a
        separate per-file counter still counted both, so `census()["tests"]`
        said two and `len(census()["per_test"])` said one - and nothing on the
        table said which of them the reader was holding. The class in the key
        is what makes them two, and deriving the count from the keys is what
        makes the two answers the same answer.
        """
        source = (
            "import unittest\n"
            "class FirstTests(unittest.TestCase):\n"
            "    def test_same_name(self):\n"
            "        self.assertEqual(1, 1)\n"
            "class SecondTests(unittest.TestCase):\n"
            "    def test_same_name(self):\n"
            "        self.assertEqual(2, 2)\n"
        )
        keys = census_keys(source)
        self.assertEqual(keys, runner_keys(source))
        self.assertEqual(
            keys,
            {
                f"{PROBE_LABEL}::FirstTests::test_same_name",
                f"{PROBE_LABEL}::SecondTests::test_same_name",
            },
        )

    def test_a_method_a_subclass_shares_is_counted_once_per_class(self) -> None:
        """Inheritance runs the method twice, so the census has to file it twice.

        The mirror image of the collision above: there, one key hid two tests;
        here, one `def` IS two tests. Attributing both to the class that
        declared them would have restored the collapse under a longer key.
        """
        source = (
            "import unittest\n"
            "class Shared(unittest.TestCase):\n"
            "    def test_inherited(self):\n"
            "        self.assertTrue(True)\n"
            "class FirstTests(Shared):\n"
            "    pass\n"
            "class SecondTests(Shared):\n"
            "    def test_own(self):\n"
            "        self.assertTrue(True)\n"
        )
        keys = census_keys(source)
        self.assertEqual(keys, runner_keys(source))
        self.assertEqual(
            keys,
            {
                f"{PROBE_LABEL}::Shared::test_inherited",
                f"{PROBE_LABEL}::FirstTests::test_inherited",
                f"{PROBE_LABEL}::SecondTests::test_inherited",
                f"{PROBE_LABEL}::SecondTests::test_own",
            },
        )

    def test_one_call_cannot_answer_how_many_tests_two_ways(self) -> None:
        """On the real tree, which is the only place the disagreement mattered.

        The shapes above prove the two counts agree on an invented file. This
        one asks the question the table's footer answers - "N tests classified"
        - of the repository the audit is actually about.
        """
        result = census_totals()
        self.assertEqual(result["tests"], len(result["per_test"]))
        self.assertEqual(result["tests"], sum(result["total"].values()))
        self.assertEqual(
            result["tests"],
            sum(sum(counts.values()) for counts in result["per_file"].values()),
        )


def census_totals() -> dict[str, object]:
    return guard_census.census()


if __name__ == "__main__":
    unittest.main()

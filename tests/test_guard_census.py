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
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import guard_census  # noqa: E402


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
        """
        loader = unittest.TestLoader()

        def count(suite: unittest.TestSuite) -> int:
            return sum(
                count(test) if isinstance(test, unittest.TestSuite) else 1
                for test in suite
            )

        discovered = count(loader.discover(str(REPO_ROOT / "tests")))
        result = census_totals()
        self.assertEqual(result["tests"], discovered)
        self.assertGreater(discovered, 100, discovered)


def census_totals() -> dict[str, object]:
    return guard_census.census()


if __name__ == "__main__":
    unittest.main()

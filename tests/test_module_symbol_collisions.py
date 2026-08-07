"""No Python module in this repository may bind the same top-level name twice.

This guards a failure mode that has already happened once and that neither
Git nor the test suite noticed.

#156 and #169 each added a module-level `_PROHIBITION` regex to
`tests/test_skill_package.py`, hundreds of lines apart. Git merged both with
no textual conflict - they were nowhere near each other, so there was nothing
for a three-way merge to object to. The result was one module with two
top-level `_PROHIBITION = re.compile(...)` statements, and in Python the
later one simply wins. #169's alternation deliberately omits `do not` and
`don't` (they are too weak to hedge a no-effect claim), so #156's
billing-mandate classifier - which is defined *above* the second assignment
but resolves the global at call time, not at definition time - silently
stopped recognising `Do not call the walkthrough ceiling a provider-billing
cap` as a mandate. Both branches' own tests still passed on their own
branches. The defect existed only in the merge.

The lesson generalises past that one pair: with 25 open branches editing a
handful of shared Python files, any two of them can independently pick the
same reasonable name for a module-level helper, and the merge that combines
them will be clean and wrong. So the check here is structural rather than a
pin on the one pair that got caught - it fails on *any* duplicated top-level
binding, whichever branches introduce it.

Scope notes, so a future reader knows what this does and does not catch:

* Two *different* modules binding the same name is fine and is not flagged.
  Modules are separate namespaces; the hazard is strictly within one module.
* Only true module scope (`tree.body`) is inspected. Rebinding inside a
  module-level `try`/`except ImportError` or `if` block is a deliberate
  idiom, and the merge hazard this exists for is two branches each appending
  a top-level definition - which is exactly module scope.
"""

from __future__ import annotations

import ast
import collections
import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _top_level_bindings(tree: ast.Module) -> collections.Counter[str]:
    """Every name this module binds at true module scope, with its count."""
    names: collections.Counter[str] = collections.Counter()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names[target.id] += 1
        elif isinstance(node, ast.AnnAssign):
            # An annotation with no value (`x: int`) declares but does not
            # bind, so it cannot shadow anything and is not counted.
            if isinstance(node.target, ast.Name) and node.value is not None:
                names[node.target.id] += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names[node.name] += 1
    return names


def duplicate_top_level_bindings(source: str) -> dict[str, int]:
    """Names bound more than once at module scope, name -> how many times.

    Takes source text rather than a path so the check can be run over
    invented text as well as over the repository - which is what lets the
    test below prove it can actually fail.
    """
    counts = _top_level_bindings(ast.parse(source))
    return {name: count for name, count in counts.items() if count > 1}


def python_sources() -> list[pathlib.Path]:
    """Every Python file this repository owns."""
    found: list[pathlib.Path] = []
    for directory in ("tests", "skills", "tools"):
        found.extend(sorted((REPO_ROOT / directory).rglob("*.py")))
    return found


class ModuleSymbolCollisionTests(unittest.TestCase):
    def test_no_module_binds_a_top_level_name_twice(self) -> None:
        offenders = {}
        for path in python_sources():
            duplicates = duplicate_top_level_bindings(path.read_text())
            if duplicates:
                offenders[str(path.relative_to(REPO_ROOT))] = duplicates

        self.assertEqual(
            offenders,
            {},
            "A module binds the same top-level name more than once. The later "
            "binding wins for every reader in the file, including functions "
            "defined above it, so this is a silent behaviour change rather "
            "than an error. If two branches merged and each brought its own "
            "definition, rename one after what it actually matches - as #169's "
            "`_PROHIBITION` became `_NO_EFFECT_HEDGE` - rather than deleting "
            "either.",
        )

    def test_the_repository_actually_has_sources_to_check(self) -> None:
        # A globbing mistake would make the check above pass by inspecting
        # nothing at all, which is the one way this file could go quietly
        # dead.
        sources = python_sources()
        self.assertGreater(len(sources), 10, sources)
        self.assertIn(
            "tests/test_skill_package.py",
            {str(path.relative_to(REPO_ROOT)) for path in sources},
        )

    def test_the_check_catches_the_merge_that_produced_it(self) -> None:
        # The two `_PROHIBITION` definitions as a clean merge of #156 and #169
        # actually leaves them: far apart, both at module scope, no conflict.
        merged = (
            "import re\n"
            '_PROHIBITION = re.compile(r"never|do not|don\'t")\n'
            "def billing_ceiling_mandates(text):\n"
            "    return bool(_PROHIBITION.search(text))\n"
            "\n\n" + "# filler\n" * 100 + "\n"
            '_PROHIBITION = re.compile(r"never|not enough|no claim")\n'
        )
        self.assertEqual(duplicate_top_level_bindings(merged), {"_PROHIBITION": 2})

    def test_separate_modules_may_reuse_a_name(self) -> None:
        # Each module is checked on its own, so the same helper name in two
        # different files is not an offence and must not be reported as one.
        one = 'import re\n_PROHIBITION = re.compile(r"never")\n'
        self.assertEqual(duplicate_top_level_bindings(one), {})
        self.assertEqual(duplicate_top_level_bindings(one), {})

    def test_functions_and_classes_count_as_bindings(self) -> None:
        # A merge can just as easily land two same-named helpers as two
        # same-named regexes, and the shadowing is identical.
        self.assertEqual(
            duplicate_top_level_bindings("def f():\n    pass\ndef f():\n    pass\n"),
            {"f": 2},
        )
        self.assertEqual(
            duplicate_top_level_bindings("class C:\n    pass\nclass C:\n    pass\n"),
            {"C": 2},
        )

    def test_a_bare_annotation_is_not_a_binding(self) -> None:
        # `x: int` followed by `x = 1` binds once, not twice.
        self.assertEqual(duplicate_top_level_bindings("x: int\nx = 1\n"), {})


if __name__ == "__main__":
    unittest.main()

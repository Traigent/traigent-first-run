"""No Python module in this repository may bind the same name twice in a scope.

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

Module scope was one level too narrow, and the class it was built for walked
straight through the gap. #206 and #214 each added a `@staticmethod` named
`script_prose` to the same `GuidanceDoesNotContradictItselfTests` in
`tests/test_skill_package.py` - #206's returning a list of comments, #214's
returning one joined string of literals. Git merged both with no textual
conflict, Python kept the later definition, and #214's split-noun ban went from
a substring test to a list-membership test that can never fire: `assertNotIn`
against a list of comments passes for every noun. The failure is the SAME
failure `_PROHIBITION` was, one scope in, and this file was watching the wrong
scope while it happened.

So a class body is checked exactly as module scope is. A class body is where
two branches append a helper for the same reason they append one at module
scope: it is the shared namespace of a shared file.

Scope notes, so a future reader knows what this does and does not catch:

* Two *different* modules binding the same name is fine and is not flagged.
  Modules are separate namespaces; the hazard is strictly within one module.
  Two different *classes* defining the same method is the same case - an
  override, or two independent helpers - and is likewise not flagged.
* Only true module scope (`tree.body`) and true class-body scope
  (`ClassDef.body`) are inspected. Rebinding inside a `try`/`except
  ImportError` or `if` block is a deliberate idiom, and the merge hazard this
  exists for is two branches each appending a definition - which is exactly
  those two scopes.
* A property continuation (`@x.setter def x`) rebinds the name on purpose and
  is the one legitimate same-name pair in a class body, so it is not counted.
  Nothing in this repository uses it today; it is excluded so this check does
  not hand the first contributor who does a false red with no honest exit,
  which is the shape of defect this file exists to catch.
"""

from __future__ import annotations

import ast
import collections
import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _is_property_continuation(node: ast.AST) -> bool:
    """`@x.setter def x(...)` - a deliberate rebinding, not a collision."""
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
        isinstance(decorator, ast.Attribute)
        and isinstance(decorator.value, ast.Name)
        and decorator.value.id == node.name
        and decorator.attr in {"setter", "getter", "deleter"}
        for decorator in node.decorator_list
    )


def _bindings(body: list[ast.stmt]) -> collections.Counter[str]:
    """Every name this scope binds directly in `body`, with its count."""
    names: collections.Counter[str] = collections.Counter()
    for node in body:
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
            if not _is_property_continuation(node):
                names[node.name] += 1
    return names


def duplicate_bindings(source: str) -> dict[str, int]:
    """Names bound more than once in one scope, name -> how many times.

    Module scope reports the bare name; a class body reports it qualified by
    the class (`Tests.script_prose`, and `Outer.Inner.helper` for a nested
    one), because the report has to say WHICH namespace lost a definition -
    the same method name in two different classes is an override and is fine.

    Takes source text rather than a path so the check can be run over
    invented text as well as over the repository - which is what lets the
    tests below prove it can actually fail, and prove it does not fire on the
    legitimate cases.
    """
    duplicates: dict[str, int] = {}

    def visit(body: list[ast.stmt], prefix: str, is_namespace: bool) -> None:
        if is_namespace:
            for name, count in _bindings(body).items():
                if count > 1:
                    duplicates[f"{prefix}{name}"] = count
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit(node.body, f"{prefix}{node.name}.", True)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Descended into for the class bodies it may contain, NOT
                # counted: rebinding a local (`rows = []` then `rows = f(x)`)
                # is ordinary code, and flagging it would be a false red on
                # nearly every function in the repository.
                visit(node.body, f"{prefix}{node.name}.", False)

    visit(ast.parse(source).body, "", True)
    return duplicates


def python_sources() -> list[pathlib.Path]:
    """Every Python file this repository owns."""
    found: list[pathlib.Path] = []
    for directory in ("tests", "skills", "tools"):
        found.extend(sorted((REPO_ROOT / directory).rglob("*.py")))
    return found


class ModuleSymbolCollisionTests(unittest.TestCase):
    def test_no_module_binds_a_name_twice_in_one_scope(self) -> None:
        offenders = {}
        for path in python_sources():
            duplicates = duplicate_bindings(path.read_text())
            if duplicates:
                offenders[str(path.relative_to(REPO_ROOT))] = duplicates

        self.assertEqual(
            offenders,
            {},
            "A name is bound more than once in one namespace - module scope if "
            "the report is a bare name, a class body if it is qualified. The "
            "later binding wins for every reader in the file, including code "
            "defined above it, so this is a silent behaviour change rather "
            "than an error. If two branches merged and each brought its own "
            "definition, rename one after what it actually matches - as #169's "
            "`_PROHIBITION` became `_NO_EFFECT_HEDGE`, and as #206's and "
            "#214's `script_prose` became `script_comments_and_docstrings` and "
            "`script_string_literals` - rather than deleting either.",
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
        self.assertEqual(duplicate_bindings(merged), {"_PROHIBITION": 2})

    def test_separate_modules_may_reuse_a_name(self) -> None:
        # Each module is checked on its own, so the same helper name in two
        # different files is not an offence and must not be reported as one.
        one = 'import re\n_PROHIBITION = re.compile(r"never")\n'
        self.assertEqual(duplicate_bindings(one), {})
        self.assertEqual(duplicate_bindings(one), {})

    def test_functions_and_classes_count_as_bindings(self) -> None:
        # A merge can just as easily land two same-named helpers as two
        # same-named regexes, and the shadowing is identical.
        self.assertEqual(
            duplicate_bindings("def f():\n    pass\ndef f():\n    pass\n"),
            {"f": 2},
        )
        self.assertEqual(
            duplicate_bindings("class C:\n    pass\nclass C:\n    pass\n"),
            {"C": 2},
        )

    def test_a_bare_annotation_is_not_a_binding(self) -> None:
        # `x: int` followed by `x = 1` binds once, not twice.
        self.assertEqual(duplicate_bindings("x: int\nx = 1\n"), {})

    def test_the_check_catches_the_class_body_merge_that_widened_it(self) -> None:
        # #206 and #214 as a clean merge actually leaves them: two
        # `@staticmethod script_prose` definitions in one class, ~140 lines
        # apart, different signatures, opposite return types, no conflict.
        # #214's ban then reads `assertNotIn(noun, <list of comments>)` and can
        # never fire. Module scope sees nothing here - the module binds
        # `GuidanceDoesNotContradictItselfTests` exactly once.
        merged = (
            "class GuidanceDoesNotContradictItselfTests:\n"
            "    @staticmethod\n"
            "    def script_prose(source):\n"
            "        return [c for c in comments(source)]\n"
            "\n" + "    # filler\n" * 140 + "\n"
            "    @staticmethod\n"
            "    def script_prose(source):\n"
            '        return " ".join(literals(source))\n'
        )
        self.assertEqual(
            duplicate_bindings(merged),
            {"GuidanceDoesNotContradictItselfTests.script_prose": 2},
        )
        # A class attribute is the same hazard as a method, and a nested class
        # is its own namespace, reported by its path.
        self.assertEqual(
            duplicate_bindings(
                "class C:\n"
                "    LIMIT = 5\n"
                "    class Inner:\n"
                "        LIMIT = 1\n"
                "        LIMIT = 2\n"
                "    LIMIT = 6\n"
            ),
            {"C.LIMIT": 2, "C.Inner.LIMIT": 2},
        )

    def test_separate_classes_may_reuse_a_name(self) -> None:
        # The false-red direction, and the one that decides whether this check
        # is usable: a method name shared by two classes is an override or two
        # independent helpers, which is most of what a test file is made of.
        # Flagging it would make the check unliveable, and an unliveable check
        # gets neutered rather than obeyed.
        self.assertEqual(
            duplicate_bindings(
                "class Base:\n"
                "    def setUp(self):\n"
                "        pass\n"
                "class Derived(Base):\n"
                "    def setUp(self):\n"
                "        pass\n"
                "class Third:\n"
                "    def setUp(self):\n"
                "        pass\n"
            ),
            {},
        )
        # A local rebound inside a method is ordinary code, not a collision -
        # only the class body itself is a namespace two branches can append to.
        self.assertEqual(
            duplicate_bindings(
                "class C:\n"
                "    def run(self):\n"
                "        rows = []\n"
                "        rows = [r for r in rows if r]\n"
                "        return rows\n"
            ),
            {},
        )
        # And a property continuation rebinds the name on purpose.
        self.assertEqual(
            duplicate_bindings(
                "class C:\n"
                "    @property\n"
                "    def size(self):\n"
                "        return self._size\n"
                "    @size.setter\n"
                "    def size(self, value):\n"
                "        self._size = value\n"
            ),
            {},
        )


if __name__ == "__main__":
    unittest.main()

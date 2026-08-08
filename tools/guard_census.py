#!/usr/bin/env python3
"""Classify every test in this repository by what it actually checks.

The audit in traigent-first-run#214 rests on one table, and a table nobody can
re-derive is a claim, not a measurement. This is the classifier that produces
it. Run it and the census regenerates from the tree you are standing on:

    python tools/guard_census.py            # the per-file table
    python tools/guard_census.py --signals  # the multi-label signal counts
    python tools/guard_census.py --list presence-weld   # which tests, by name

The class it exists to count is the one #183 named: **a phrase-presence guard
makes stale prose harder to fix but does not detect it.** `assertIn("the same
48 whatever the customer brings", skill_text)` pins a sentence to a document.
It fails when the sentence is edited and passes when the *fact* drifts, which
is the wrong way round - so it welds the prose in place while proving nothing
about the number in it. The guards that held are the ones that computed the
number from the code and compared.

Six classes, one per test, in this precedence:

    scanner > derived > presence-weld > vocabulary-ban > output-assert
            > structural

* `derived`      - reaches the code it guards: calls it, runs it as a
                   subprocess, or parses its source. Its needle is computed,
                   so prose can be reworded and the check still holds.
* `scanner`      - sweeps a corpus rather than a named file, so it covers
                   documents nobody thought to list. Ranked above `derived`
                   because the corpus is the property being checked; a scanner
                   whose corpus silently narrows goes vacuously green.
* `presence-weld`- asserts a typed prose string is present in a DOCUMENT. The
                   defect class.
* `vocabulary-ban`- asserts a typed prose string is ABSENT. Not the same
                   defect: a ban is satisfied by the wording being gone, which
                   is what it is for.
* `output-assert`- asserts a typed prose string is present in something the
                   code PRODUCED. Not a weld - the haystack is executed - but
                   not derived either, because the needle is still typed. It
                   is broken out because folding it into `presence-weld` would
                   overstate the defect by a third.
* `structural`   - everything else: shapes, types, exit codes, exceptions.

How a haystack is told apart is the part worth reading, because it is what
separates the third class from the fifth. It is NOT a list of variable names.
Each assertion's haystack is traced back through the assignments in its own
test method to an origin: a `read_text()` of a document, or an item of a
corpus mapping, makes it a document; a call into the guarded module, a
`subprocess` result, or a captured stream makes it output. A name whose origin
cannot be traced is left unclassified and falls through to `structural`, so an
unreadable test is counted as unknown rather than as clean.

Limits, stated because the figures depend on them:

* It is a heuristic over ASTs, not an oracle. It reports what a test's shape
  says it does.
* `derived` is a FLOOR, not a count, and every miss found so far ran in the
  census's favour. Four rounds of spot-checking moved 108 tests out of
  `structural` and into `derived` by teaching it four indirections it could
  not originally see: a helper method on the test class (`self._run_module`),
  a module published by a fixture (`cls.probe = module` in `setUpClass`), a
  first-party import (`behavioral/harness.py`, which carried all 42 of that
  file's tests), and an alias one call out (`relock = _load()`). There is no
  reason to think the fourth round was the last. A probe run inside a
  subprocess whose body is a string literal remains invisible in principle.
* One miss was a name collision inside this tool: two helpers in one file
  shared a name, the helper map kept only the last, and 20 tests were filed
  `structural` because the definition that reached the code had been
  overwritten. That is the same defect the audit this serves is about, so it
  is recorded rather than quietly fixed.
* No frozen copy of the table is committed beside it. A recorded total is a
  weld on a number, which is the defect this whole audit is about: every
  branch that adds a test would have to edit it, so it would be renegotiated
  rather than re-measured. The tool is the reproducibility. What IS committed
  is `tests/test_guard_census.py`, which proves every class is still
  reachable - a classifier that quietly answered `structural` for everything
  would otherwise report a clean repository.
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TEST_ROOT = REPO_ROOT / "tests"

CLASSES = (
    "derived",
    "scanner",
    "presence-weld",
    "vocabulary-ban",
    "output-assert",
    "structural",
)
PRECEDENCE = (
    "scanner",
    "derived",
    "presence-weld",
    "vocabulary-ban",
    "output-assert",
    "structural",
)

# Reading a file is reading a document unless the file is source code; a
# script's own text is the code being guarded, not prose about it.
_SOURCE_SUFFIXES = (".py", ".json", ".lock")
# Executing something, in the three shapes this repository uses.
_EXECUTION = ("run", "check_output", "check_call", "Popen", "call")
_CAPTURE = ("getvalue", "stdout", "stderr", "returncode")


def test_files() -> list[pathlib.Path]:
    """Every file unittest discovery would collect."""
    return sorted(TEST_ROOT.rglob("test_*.py"))


def _guarded_aliases(tree: ast.Module) -> set[str]:
    """Module-level names bound to a script loaded for execution.

    Detected from the loading idiom rather than from a list of names, because
    the aliases differ per file (`MODULE`, `READINESS`, ...) and a hardcoded
    list is how 214 tests were misfiled as structural mid-audit.
    """
    aliases: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            rendered = ast.unparse(node.value)
            if "module_from_spec" in rendered or "import_module" in rendered:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        aliases.add(target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            # A first-party module is guarded code too. `test_contracts.py`
            # runs every one of its probes through `behavioral/harness.py`,
            # and reading only `importlib` idioms filed all 40 as structural.
            for name in node.names:
                bound = name.asname or name.name.split(".")[0]
                candidates = (
                    REPO_ROOT / f"{name.name.replace('.', '/')}.py",
                    TEST_ROOT / f"{name.name}.py",
                )
                if isinstance(node, ast.ImportFrom) and node.module:
                    candidates += (
                        REPO_ROOT / node.module.replace(".", "/") / f"{name.name}.py",
                        TEST_ROOT / node.module.replace(".", "/") / f"{name.name}.py",
                    )
                if any(path.exists() for path in candidates):
                    aliases.add(bound)
    return aliases


def _module_helpers(tree: ast.Module) -> dict[str, list[ast.FunctionDef]]:
    """Every helper a test can call: module-level, and the non-test methods.

    A helper on the test class reaches the guarded code just as a module-level
    one does, and `_run_module(...)` is how three files here run their probe.
    """
    helpers: dict[str, list[ast.FunctionDef]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("test"):
                # A LIST per name, not one node. Two helpers in one file can
                # share a name across two classes, and keeping only the last
                # dropped the one that reached the code - which misfiled 20
                # tests as structural. Being bitten by a name collision inside
                # the tool that counts name collisions is not an argument for
                # a shorter reading of it.
                helpers.setdefault(node.name, []).append(node)
    return helpers


def _bound_to_guarded_code(tree: ast.Module, aliases: set[str]) -> set[str]:
    """Attributes a fixture binds to the guarded module (`cls.probe = ...`)."""
    # A fixture usually loads into a local first (`module = ...` in
    # `setUpClass`) and only then publishes it (`cls.probe = module`), so the
    # locals have to be resolved before the attribute can be.
    locals_holding_code: set[str] = set(aliases)
    for _ in range(2):  # one pass to find the local, one to follow it
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            rendered = ast.unparse(node.value)
            if not (
                "module_from_spec" in rendered
                or "import_module" in rendered
                or rendered in locals_holding_code
            ):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    locals_holding_code.add(target.id)
    bound: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        rendered = ast.unparse(node.value)
        if not (
            "module_from_spec" in rendered
            or "import_module" in rendered
            or rendered in locals_holding_code
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                bound.add(target.attr)
    return bound


def _corpus_helpers(helpers: dict[str, list[ast.FunctionDef]]) -> set[str]:
    """Helpers that answer with a corpus rather than with one named file."""
    found: set[str] = set()
    for name, nodes in helpers.items():
        for node in nodes:
            body = ast.unparse(node)
            if any(
                token in body for token in ("glob(", "rglob(", "ls-files", "iterdir(")
            ):
                found.add(name)
    return found


def _reaches_code(node: ast.AST, aliases: set[str], reaching: set[str]) -> bool:
    """Does this subtree call, run, or parse the code under guard?"""
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in aliases | reaching:
            return True
        # `self.probe._forward_local_target(host)` and `self._run_module(...)`
        # reach the guarded code exactly as a module-level alias does; the
        # binding just happens in `setUpClass` or in a helper method. Missing
        # them is what makes `derived` a floor rather than a count.
        if isinstance(child, ast.Attribute) and child.attr in aliases | reaching:
            return True
        if isinstance(child, ast.Attribute) and child.attr in _EXECUTION:
            if isinstance(child.value, ast.Name) and child.value.id == "subprocess":
                return True
        if isinstance(child, ast.Call):
            rendered = ast.unparse(child.func)
            if rendered in ("ast.parse", "ast.walk", "compile", "exec", "eval"):
                return True
            if rendered.endswith(".main") or rendered.endswith("_from_spec"):
                return True
    return False


def _sweeps_corpus(node: ast.AST, corpora: set[str]) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            rendered = ast.unparse(child.func)
            if rendered in corpora or rendered.split(".")[-1] in corpora:
                return True
            if any(
                rendered.endswith(suffix) for suffix in (".glob", ".rglob", ".iterdir")
            ):
                return True
    return False


def _origin(expression: ast.AST, aliases: set[str], corpora: set[str]) -> str | None:
    """`document`, `output`, or None when the shape does not say."""
    rendered = ast.unparse(expression)
    if any(name in rendered.split("(")[0].split(".") for name in aliases):
        return "output"
    if "subprocess." in rendered or any(f".{tag}" in rendered for tag in _CAPTURE):
        return "output"
    if ".exception" in rendered or "raised" in rendered or "caught" in rendered:
        return "output"
    if "read_text" in rendered or "read_bytes" in rendered:
        if any(suffix in rendered for suffix in _SOURCE_SUFFIXES):
            return None
        return "document"
    for corpus in corpora:
        if f"{corpus}(" in rendered:
            return "document"
    return None


class _Haystacks:
    """Where each local name in one test method came from."""

    def __init__(self, method: ast.AST, aliases: set[str], corpora: set[str]) -> None:
        self.aliases = aliases
        self.corpora = corpora
        self.origin: dict[str, str] = {}
        for node in ast.walk(method):
            if isinstance(node, ast.Assign):
                found = _origin(node.value, aliases, corpora) or self._inherited(
                    node.value
                )
                if found:
                    for target in node.targets:
                        for name in self._names(target):
                            self.origin[name] = found
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                found = _origin(node.iter, aliases, corpora) or self._inherited(
                    node.iter
                )
                if found:
                    for name in self._names(node.target):
                        self.origin[name] = found
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                for name in self._names(node.optional_vars):
                    self.origin[name] = "output"

    @staticmethod
    def _names(target: ast.AST) -> list[str]:
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            names: list[str] = []
            for element in target.elts:
                names.extend(_Haystacks._names(element))
            return names
        return []

    def _inherited(self, expression: ast.AST) -> str | None:
        for child in ast.walk(expression):
            if isinstance(child, ast.Name) and child.id in self.origin:
                return self.origin[child.id]
        return None

    def classify(self, expression: ast.AST) -> str | None:
        return (
            _origin(expression, self.aliases, self.corpora)
            or self._inherited(expression)
            or None
        )


def _is_prose_literal(node: ast.AST) -> bool:
    """A typed sentence, as opposed to an identifier or a computed needle."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return " " in node.value.strip()
    # An f-string needle is derived by construction - the value it
    # interpolates came from somewhere - so it is deliberately NOT prose.
    return False


def _holds_prose(node: ast.AST) -> bool:
    """A container whose elements are typed sentences.

    Most of this repository's welds are written as a tuple of phrases and one
    `assertIn(phrase, text)` in a `subTest` loop, so a classifier that only
    recognised a literal needle would report a third of them. The needle is
    still typed; it is typed one line further up.
    """
    if _is_prose_literal(node):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_is_prose_literal(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return any(_is_prose_literal(key) for key in node.keys if key is not None)
    return False


def _prose_containers(tree: ast.Module) -> set[str]:
    """Every module-level or class-level name bound to typed sentences."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _holds_prose(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found.add(target.id)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if _holds_prose(node.value) and isinstance(node.target, ast.Name):
                found.add(node.target.id)
    return found


def _prose_needles(method: ast.AST, containers: set[str]) -> set[str]:
    """Local names in one test that hold a typed sentence when read."""
    names: set[str] = set(containers)
    for node in ast.walk(method):
        if isinstance(node, ast.Assign) and _holds_prose(node.value):
            for target in node.targets:
                names.update(_Haystacks._names(target))
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            iterated = node.iter
            renders = ast.unparse(iterated)
            if _holds_prose(iterated) or any(
                f"{container}" in renders.split(".") or renders == container
                for container in containers
            ):
                names.update(_Haystacks._names(node.target))
    return names


def _is_prose(node: ast.AST, needles: set[str]) -> bool:
    if _is_prose_literal(node):
        return True
    return isinstance(node, ast.Name) and node.id in needles


def classify_method(
    method: ast.AST,
    aliases: set[str],
    corpora: set[str],
    reaching: set[str],
    containers: set[str],
) -> tuple[str, set[str]]:
    """One test's primary class, and every signal it showed."""
    signals: set[str] = set()
    if _reaches_code(method, aliases, reaching):
        signals.add("derived")
    if _sweeps_corpus(method, corpora):
        signals.add("scanner")

    needles = _prose_needles(method, containers)
    haystacks = _Haystacks(method, aliases, corpora)
    for node in ast.walk(method):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", "")
        if name not in ("assertIn", "assertNotIn") or len(node.args) < 2:
            continue
        if not _is_prose(node.args[0], needles):
            continue
        origin = haystacks.classify(node.args[1])
        if name == "assertNotIn":
            signals.add("vocabulary-ban")
        elif origin == "document":
            signals.add("presence-weld")
        elif origin == "output":
            signals.add("output-assert")

    for candidate in PRECEDENCE:
        if candidate in signals:
            return candidate, signals
    return "structural", signals


def census() -> dict[str, object]:
    per_file: dict[str, collections.Counter[str]] = {}
    per_test: dict[str, str] = {}
    signals: collections.Counter[str] = collections.Counter()
    for path in test_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = _guarded_aliases(tree)
        helpers = _module_helpers(tree)
        corpora = _corpus_helpers(helpers)
        containers = _prose_containers(tree)
        aliases |= _bound_to_guarded_code(tree, aliases)
        reaching = {
            name
            for name, nodes in helpers.items()
            if any(_reaches_code(node, aliases, set()) for node in nodes)
        }
        # `relock = _load()` at module scope is the same alias as
        # `MODULE = module_from_spec(...)`, one indirection out. Resolving it
        # needs `reaching` first, so it is a second pass rather than part of
        # `_guarded_aliases`.
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if ast.unparse(node.value.func).split(".")[-1] in reaching:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            aliases.add(target.id)
        reaching |= {
            name
            for name, nodes in helpers.items()
            if any(_reaches_code(node, aliases, set()) for node in nodes)
        }
        counts: collections.Counter[str] = collections.Counter()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test"):
                continue
            primary, shown = classify_method(
                node, aliases, corpora, reaching, containers
            )
            counts[primary] += 1
            key = f"{path.relative_to(REPO_ROOT)}::{node.name}"
            per_test[key] = primary
            for signal in shown:
                signals[signal] += 1
        per_file[str(path.relative_to(REPO_ROOT))] = counts
    total: collections.Counter[str] = collections.Counter()
    for counts in per_file.values():
        total.update(counts)
    return {
        "per_file": {name: dict(counts) for name, counts in per_file.items()},
        "per_test": per_test,
        "signals": dict(signals),
        "total": dict(total),
        "tests": sum(total.values()),
    }


def _table(result: dict[str, object]) -> str:
    per_file = result["per_file"]
    assert isinstance(per_file, dict)
    header = "| file | " + " | ".join(CLASSES) + " |"
    rule = "|---|" + "---:|" * len(CLASSES)
    lines = [header, rule]
    for name, counts in sorted(per_file.items()):
        cells = " | ".join(str(counts.get(label, 0)) for label in CLASSES)
        lines.append(f"| `{name}` | {cells} |")
    total = result["total"]
    assert isinstance(total, dict)
    cells = " | ".join(f"**{total.get(label, 0)}**" for label in CLASSES)
    lines.append(f"| **TOTAL** | {cells} |")
    lines.append("")
    lines.append(f"{result['tests']} tests classified.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signals", action="store_true", help="multi-label counts")
    parser.add_argument("--list", metavar="CLASS", help="name the tests in one class")
    parser.add_argument("--json", action="store_true", help="the whole result")
    arguments = parser.parse_args(argv)

    result = census()
    if arguments.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if arguments.list:
        per_test = result["per_test"]
        assert isinstance(per_test, dict)
        for key, label in sorted(per_test.items()):
            if label == arguments.list:
                print(key)
        return 0
    print(_table(result))
    if arguments.signals:
        signals = result["signals"]
        assert isinstance(signals, dict)
        print()
        print("Signals are multi-label - most tests show more than one, and")
        print("the table above reports only the first that precedence reaches.")
        for label in CLASSES:
            if label == "structural":
                continue  # the absence of every signal, not a signal
            print(f"{label}: {signals.get(label, 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

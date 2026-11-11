"""Flat callable loaders preserve Python module identity without changing customer code."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

from test_generate_adapter import MODULE as GENERATOR
from test_generate_adapter import Project

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "traigent-first-run"
DATACLASS = """from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Result:
    value: float

def score(*, output, expected):
    return Result(float(output == expected)).value

def transform(value):
    return Result(float(value)).value
"""


def load_test_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous_bytecode = sys.dont_write_bytecode
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous_bytecode
    return module


RUNTIME = load_test_module(
    "test_callable_loading_runtime", SKILL / "assets" / "first_run_runtime.py"
)
CALIBRATION = load_test_module(
    "test_callable_loading_calibration", SKILL / "scripts" / "calibrate_evaluator.py"
)


class PythonCallableLoadingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.before_modules = dict(sys.modules)
        self.before_path = sys.path[:]
        self.addCleanup(self.restore_import_state)

    def restore_import_state(self):
        sys.path[:] = self.before_path
        for name, module in list(sys.modules.items()):
            location = getattr(module, "__file__", None)
            if name.startswith("_first_run_") or (
                location and Path(location).is_relative_to(self.root)
            ):
                if name in self.before_modules:
                    sys.modules[name] = self.before_modules[name]
                else:
                    del sys.modules[name]

    def source(self, relative="scorer.py", text=DATACLASS):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def load_callable(self, loader, path, function="score", role="evaluator"):
        if loader == "calibration":
            return CALIBRATION.load_function(f"{path}:{function}")
        bridge = RUNTIME.Bridge(
            {role: {"file": str(path.relative_to(self.root)), "function": function}},
            self.root / "traigent-runs",
        )
        return bridge.function(role)

    def test_dataclass_scorer_and_reply_transform_preserve_distinct_scores(self):
        path = self.source()
        for loader in ("bridge", "calibration"):
            with self.subTest(loader=loader):
                function = self.load_callable(loader, path)
                self.assertEqual(function(output="yes", expected="yes"), 1.0)
                self.assertEqual(function(output="no", expected="yes"), 0.0)
                self.assertIs(sys.modules[function.__module__].score, function)
        transform = CALIBRATION.load_function(f"{path}:transform")
        self.assertEqual(transform("0.25"), 0.25)

    def test_generated_dataclass_agent_loads_without_source_rewrite(self):
        source = DATACLASS + """
def answer(text, model="one", temperature=0.0):
    return {"result": {"label": str(Result(1.0).value)}}
"""
        project = Project(self, agent=source, evaluator=DATACLASS)
        project.config["evaluator"]["callable"] = "evaluator:score"
        before = (project.root / "agent.py").read_bytes()
        generated = project.generate()
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
        spec, _, _ = GENERATOR.validate(project.config, project.root)
        bridge = RUNTIME.Bridge(spec, project.runs)
        self.assertEqual(bridge.function("agent")("x"), {"result": {"label": "1.0"}})
        self.assertEqual((project.root / "agent.py").read_bytes(), before)

    def test_failed_import_removes_partial_registration_including_system_exit(self):
        for loader in ("bridge", "calibration"):
            for error in ("RuntimeError", "SystemExit"):
                with self.subTest(loader=loader, error=error):
                    marker = self.root / "loaded-name.txt"
                    path = self.source(
                        text=(
                            "import sys\nfrom pathlib import Path\n"
                            "assert sys.modules[__name__].__name__ == __name__\n"
                            f"Path({str(marker)!r}).write_text(__name__)\n"
                            f"raise {error}('fixture import failure')\n"
                        )
                    )
                    with self.assertRaises((RuntimeError, SystemExit)):
                        self.load_callable(loader, path)
                    self.assertNotIn(marker.read_text(), sys.modules)

    def test_separate_and_reloaded_sources_preserve_existing_module_identity(self):
        first = self.source("one/scorer.py")
        second = self.source(
            "two/scorer.py", DATACLASS.replace("float(output == expected)", "0.25")
        )
        sentinel = types.ModuleType("scorer")
        old = sys.modules.get("scorer")
        sys.modules["scorer"] = sentinel
        self.addCleanup(
            lambda: (
                sys.modules.__setitem__("scorer", old)
                if old is not None
                else sys.modules.pop("scorer", None)
            )
        )
        for loader in ("bridge", "calibration"):
            with self.subTest(loader=loader):
                original = self.load_callable(loader, first)
                original_module = sys.modules[original.__module__]
                other = self.load_callable(loader, second)
                reloaded = self.load_callable(loader, first)
                self.assertEqual(original(output="yes", expected="yes"), 1.0)
                self.assertEqual(other(output="yes", expected="yes"), 0.25)
                self.assertEqual(reloaded(output="yes", expected="yes"), 1.0)
                self.assertEqual(
                    len({f.__module__ for f in (original, other, reloaded)}), 3
                )
                self.assertIs(sys.modules[original.__module__], original_module)
                self.assertIs(original_module.score, original)
                self.assertIs(sys.modules["scorer"], sentinel)

    def test_package_relative_imports_and_plain_flat_callables_still_work(self):
        self.source("loader_package/__init__.py", "")
        self.source("loader_package/value.py", "VALUE = 0.75\n")
        packaged = self.source(
            "loader_package/scorer.py",
            "from .value import VALUE\ndef score():\n    return VALUE\n",
        )
        self.assertEqual(self.load_callable("bridge", packaged)(), 0.75)
        plain = self.source(text="def score():\n    return 0.5\n")
        for loader in ("bridge", "calibration"):
            self.assertEqual(self.load_callable(loader, plain)(), 0.5)

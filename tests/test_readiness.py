from __future__ import annotations

import importlib.util
import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "traigent-first-run" / "scripts" / "readiness.py"
SPEC = importlib.util.spec_from_file_location("first_run_readiness", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ReadinessMatrixTests(unittest.TestCase):
    def test_all_eight_real_or_missing_starting_states(self) -> None:
        expected_create = {
            ("real", "real", "real"): [],
            ("real", "real", "missing"): ["evaluation"],
            ("real", "missing", "real"): ["dataset"],
            ("missing", "real", "real"): ["agent"],
            ("real", "missing", "missing"): ["dataset", "evaluation"],
            ("missing", "real", "missing"): ["agent", "evaluation"],
            ("missing", "missing", "real"): ["dataset", "agent"],
            ("missing", "missing", "missing"): ["agent", "dataset", "evaluation"],
        }
        observed = {}
        for states in itertools.product(("real", "missing"), repeat=3):
            plan = MODULE.build_plan(*states)
            observed[states] = plan.create
            self.assertEqual(plan.real_ready_count, states.count("real"))
            self.assertEqual(plan.walkthrough_ready_count, states.count("real"))
        self.assertEqual(observed, expected_create)

    def test_demo_substitute_never_counts_as_real(self) -> None:
        plan = MODULE.build_plan("real", "demo", "missing")
        self.assertEqual(plan.real_ready_count, 1)
        self.assertEqual(plan.walkthrough_ready_count, 2)
        self.assertIn("dataset", plan.missing_real)
        self.assertEqual(plan.create, ["evaluation"])
        rendered = MODULE.render_text(plan)
        self.assertIn("❗ Dataset", rendered)
        self.assertIn("🛠️ Dataset", rendered)


if __name__ == "__main__":
    unittest.main()

"""The SDK cost limit is kept for routes the SDK prices and dropped, with the ledger as gate, for those it cannot.

SDK 0.31.1 raises CostTrackingRequiredError when an explicit cost limit is set and a
trial reports no cost. Functions are lifted out of the shipped wrapper, not restated.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import unittest
from pathlib import Path

WRAPPER = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "traigent-first-run"
    / "assets"
    / "run_wrapper.py"
)
TEXT = WRAPPER.read_text(encoding="utf-8")


def lift(namespace: dict, *names: str) -> None:
    wanted = set(names)
    for node in ast.parse(TEXT).body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            exec(ast.unparse(node), namespace)  # noqa: S102
            wanted.discard(node.name)
    assert not wanted, f"the wrapper no longer defines {sorted(wanted)}"


class SDKCostLimitPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ns: dict = {}
        lift(self.ns, "keep_sdk_cost_limit", "models_without_sdk_price")

    def test_a_priced_route_keeps_the_sdk_limit(self) -> None:
        keep = self.ns["keep_sdk_cost_limit"]
        self.assertTrue(keep([], True))
        self.assertTrue(keep([], False))

    def test_an_unpriced_route_with_the_ledger_installed_drops_the_limit(self) -> None:
        self.assertFalse(self.ns["keep_sdk_cost_limit"](["x/unpriced"], True))

    def test_an_unpriced_route_without_the_ledger_keeps_the_limit(self) -> None:
        self.assertTrue(self.ns["keep_sdk_cost_limit"](["x/unpriced"], False))

    def test_the_wrapper_decides_from_the_ledger_flag_and_never_swallows_the_error(
        self,
    ) -> None:
        self.assertIn('getattr(litellm, "_first_run_ledgered", False)', TEXT)
        self.assertNotIn("except CostTrackingRequiredError", TEXT)

    def test_the_removal_follows_the_ledger_install(self) -> None:
        self.assertLess(
            TEXT.index("litellm._first_run_ledgered = True"),
            TEXT.index('os.environ.pop("TRAIGENT_RUN_COST_LIMIT"'),
        )

    def test_the_real_sdk_lookup_separates_priced_from_unpriced(self) -> None:
        if importlib.util.find_spec("traigent") is None:
            raise unittest.SkipTest("traigent is not installed")
        os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
        missing = self.ns["models_without_sdk_price"](
            ["gpt-4o-mini", "no-such-vendor/no-such-model-9"]
        )
        self.assertEqual(missing, ["no-such-vendor/no-such-model-9"])

    def test_an_unreachable_lookup_is_unpriced(self) -> None:
        import builtins

        real = builtins.__import__

        def refuse(name, *args, **kwargs):
            if name == "traigent.utils.cost_calculator":
                raise ImportError(name)
            return real(name, *args, **kwargs)

        builtins.__import__ = refuse
        try:
            self.assertEqual(
                self.ns["models_without_sdk_price"](["b", "a"]), ["a", "b"]
            )
        finally:
            builtins.__import__ = real

    def test_the_ledger_refuses_a_call_over_budget_when_the_limit_is_dropped(
        self,
    ) -> None:
        ns = {
            "RUN_COST_REMAINING_USD": 0.05,
            "RUN_SPEND_USD": [0.04],
            "RUN_COST_CEILING_USD": 0.05,
            "UNTRACKED_CALL_COST_USD": 0.02,
        }
        lift(ns, "run_remaining_usd", "refuse_unless_it_fits")
        with self.assertRaises(RuntimeError):
            ns["refuse_unless_it_fits"](1, "one call")
        ns["RUN_SPEND_USD"] = []
        ns["refuse_unless_it_fits"](1, "one call")


if __name__ == "__main__":
    unittest.main()

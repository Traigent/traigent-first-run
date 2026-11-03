"""The SDK cost limit is kept for routes the SDK prices and dropped, with the ledger as gate, for those it cannot.

SDK 0.31.1 raises CostTrackingRequiredError when an explicit cost limit is set and a
trial reports no cost. Functions are lifted out of the shipped wrapper, not restated.
"""

from __future__ import annotations

import ast
import importlib.util
import contextlib
import io
import os
import tempfile
import types
import unittest
from unittest import mock
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
        self.litellm = types.SimpleNamespace()
        self.ns: dict = {"litellm": self.litellm}
        lift(self.ns, "keep_sdk_cost_limit", "models_without_sdk_price")

    def keep(self, unpriced: list[str], ledger: bool | None) -> bool:
        if ledger is not None:
            self.litellm._first_run_ledgered = ledger
        return self.ns["keep_sdk_cost_limit"](unpriced)

    def test_a_priced_route_keeps_the_sdk_limit(self) -> None:
        self.assertTrue(self.keep([], True))
        self.assertTrue(self.keep([], False))

    def test_an_unpriced_route_with_the_ledger_installed_drops_the_limit(self) -> None:
        self.assertFalse(self.keep(["x/unpriced"], True))

    def test_an_unpriced_route_without_the_ledger_keeps_the_limit(self) -> None:
        self.assertTrue(self.keep(["x/unpriced"], False))
        self.assertTrue(self.keep(["x/unpriced"], None))

    def apply(self, models: list[str]) -> str:
        lift(
            self.ns,
            "keep_sdk_cost_limit",
            "models_without_sdk_price",
            "apply_sdk_cost_limit_policy",
        )
        self.ns["os"] = os
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.ns["apply_sdk_cost_limit_policy"](models)
        return output.getvalue()

    def test_a_removed_limit_survives_a_later_dotenv_load(self) -> None:
        from dotenv import load_dotenv

        self.litellm._first_run_ledgered = True
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"TRAIGENT_RUN_COST_LIMIT": "1.0"}
        ):
            env_file = os.path.join(directory, ".env")
            with open(env_file, "w", encoding="utf-8") as handle:
                handle.write("TRAIGENT_RUN_COST_LIMIT=5.0\n")
            notice = self.apply(["no-such-vendor/no-such-model-9"])
            self.assertEqual(os.environ["TRAIGENT_RUN_COST_LIMIT"], "")
            load_dotenv(env_file, override=False)
            self.assertEqual(os.environ["TRAIGENT_RUN_COST_LIMIT"], "")
        self.assertIn("Explicit SDK cost limit removed", notice)
        self.assertIn("no-such-vendor/no-such-model-9", notice)

    def test_a_priced_route_leaves_the_limit_and_prints_nothing(self) -> None:
        self.litellm._first_run_ledgered = True
        os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
        with mock.patch.dict(os.environ, {"TRAIGENT_RUN_COST_LIMIT": "1.0"}):
            self.assertEqual(self.apply(["gpt-4o-mini"]), "")
            self.assertEqual(os.environ["TRAIGENT_RUN_COST_LIMIT"], "1.0")

    def test_the_sdk_reads_a_blank_limit_as_not_explicit(self) -> None:
        if importlib.util.find_spec("traigent") is None:
            raise unittest.SkipTest("traigent is not installed")
        from traigent.core.cost_enforcement import CostEnforcer

        with mock.patch.dict(os.environ, {"TRAIGENT_RUN_COST_LIMIT": ""}):
            config = CostEnforcer.__new__(CostEnforcer)._load_config()
        self.assertFalse(config.limit_explicit)

    def test_the_module_level_call_is_guarded_and_precedes_the_optimizer(self) -> None:
        body = ast.parse(TEXT).body

        def calls_policy(node: ast.stmt) -> bool:
            return (
                isinstance(node, ast.If)
                and ast.unparse(node.test) == "FIRST_RUN_PHASE != 'proof'"
                and len(node.body) == 1
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Call)
                and ast.unparse(node.body[0].value.func)
                == "apply_sdk_cost_limit_policy"
                and not node.orelse
            )

        calls = [i for i, node in enumerate(body) if calls_policy(node)]
        self.assertEqual(len(calls), 1, "the guarded module-level call is missing")
        optimizer = [
            i
            for i, node in enumerate(body)
            if isinstance(node, ast.FunctionDef)
            and any("optimize" in ast.unparse(d) for d in node.decorator_list)
        ]
        self.assertTrue(optimizer, "the optimizer-decorated function moved")
        self.assertLess(calls[0], min(optimizer))
        install = next(
            i
            for i, node in enumerate(body)
            if isinstance(node, ast.If)
            and "_first_run_ledgered" in ast.unparse(node.test)
        )
        self.assertLess(install, calls[0])

    def test_the_wrapper_decides_from_the_ledger_flag_and_never_swallows_the_error(
        self,
    ) -> None:
        self.assertIn('getattr(litellm, "_first_run_ledgered", False)', TEXT)
        self.assertNotIn("except CostTrackingRequiredError", TEXT)

    def test_the_removal_follows_the_ledger_install(self) -> None:
        self.assertLess(
            TEXT.index("litellm._first_run_ledgered = True"),
            TEXT.index('os.environ["TRAIGENT_RUN_COST_LIMIT"] = ""'),
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

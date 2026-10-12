"""Small executed examples of the grading limits explained by the first run."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ASSETS = (
    Path(__file__).resolve().parents[1] / "skills" / "traigent-first-run" / "assets"
)


def load_asset(name: str):
    spec = importlib.util.spec_from_file_location(
        f"grading_semantics_{name}", ASSETS / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # The runtime intentionally disables bytecode; keep that process setting
    # and the import registry unchanged for the other tests in discovery.
    previous_bytecode = sys.dont_write_bytecode
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous_bytecode
    return module


RUNTIME = load_asset("first_run_runtime")
SQL = load_asset("sql_structure")

EVALUATORS = """
def strict(output, expected):
    return float(output == expected)

def accepted(output, expected, metadata):
    return float(output in metadata['accepted_answers'])
"""


class AlternativeAnswerGradingTests(unittest.TestCase):
    def bridge(self, function: str):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name)
        (project / "evaluator.py").write_text(EVALUATORS, encoding="utf-8")
        self.raw_rows = [
            {
                "id": row_id,
                "input": "Name a primary color of light.",
                "expected": expected,
                "metadata": {"accepted_answers": ["red", "green", "blue"]},
            }
            for row_id, expected in (("red-answer", "red"), ("blue-answer", "blue"))
        ]
        (project / "rows.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in self.raw_rows), encoding="utf-8"
        )
        args = {"output": "$output", "expected": "$expected"}
        if function == "accepted":
            args["metadata"] = "$metadata"
        spec = {
            "dataset": {
                "path": "rows.jsonl",
                "input": "input",
                "expected": "expected",
                "metadata": "metadata",
                "id": "id",
            },
            "evaluator": {
                "file": "evaluator.py",
                "function": function,
                "args": args,
                "calls_per_row": 0,
            },
        }
        # Bridge.function temporarily adds customer import paths.
        previous_path = sys.path[:]
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), previous_path))
        return RUNTIME.Bridge(spec, project / "traigent-runs")

    @staticmethod
    def scores(bridge, output):
        return [
            bridge.score(
                output=output,
                expected=row["expected"],
                input_data=row["input"],
                metadata=row["metadata"],
            )
            for row in bridge.rows("rows.jsonl")
        ]

    def test_preserving_alternative_rows_does_not_make_strict_grading_any_of(self):
        bridge = self.bridge("strict")
        rows = bridge.rows("rows.jsonl")
        self.assertEqual([row["raw"] for row in rows], self.raw_rows)
        self.assertEqual(len({row["input"] for row in rows}), 1)
        self.assertEqual(self.scores(bridge, "red"), [1.0, 0.0])
        self.assertEqual(self.scores(bridge, "blue"), [0.0, 1.0])

    def test_customer_any_of_policy_uses_mapped_metadata_and_rejects_wrong_answers(
        self,
    ):
        bridge = self.bridge("accepted")
        for answer in ("red", "green", "blue"):
            with self.subTest(answer=answer):
                self.assertEqual(self.scores(bridge, answer), [1.0, 1.0])
        self.assertEqual(self.scores(bridge, "orange"), [0.0, 0.0])


class StructuralSqlScopeTests(unittest.TestCase):
    def test_a_structural_match_can_change_union_column_alignment(self):
        expected = "SELECT a, b FROM t UNION SELECT c, d FROM u"
        candidate = "SELECT b, a FROM t UNION SELECT c, d FROM u"
        self.assertEqual(SQL.structural_match(candidate, expected), 1.0)
        # Fixed, local data supplies a concrete counterexample; matching on
        # this database would still not prove equivalence on all databases.
        with sqlite3.connect(":memory:") as database:
            database.executescript(
                "CREATE TABLE t(a, b); INSERT INTO t VALUES (1, 2);"
                "CREATE TABLE u(c, d); INSERT INTO u VALUES (3, 4);"
            )
            gold_rows = set(database.execute(expected).fetchall())
            actual_rows = set(database.execute(candidate).fetchall())
        self.assertEqual(gold_rows, {(1, 2), (3, 4)})
        self.assertEqual(actual_rows, {(2, 1), (3, 4)})
        self.assertNotEqual(actual_rows, gold_rows)


if __name__ == "__main__":
    unittest.main()

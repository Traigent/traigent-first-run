"""Carry measured baseline evidence across the documented cost-only transition."""

from __future__ import annotations

import ast
import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

WRAPPER = (
    Path(__file__).resolve().parents[1]
    / "skills/traigent-first-run/assets/run_wrapper.py"
)
PRIMARY = {"name": "quality", "orientation": "maximize", "weight": 1.0}
COST = {"name": "cost", "orientation": "minimize", "weight": 0.5}
REMOVAL = {
    "reason": "The approved route no longer reports usable cost telemetry.",
    "approval_reference": "run-plan.md: connected phase, current approval",
}


class BaselineObjectiveTransitionTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(WRAPPER.read_text(encoding="utf-8"))
        functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"_canonical_json", "load_baseline_transfer"}
        ]
        namespace = {"json": json, "math": math, "Path": Path}
        exec(  # noqa: S102
            compile(ast.Module(body=functions, type_ignores=[]), str(WRAPPER), "exec"),
            namespace,
        )
        self.load = namespace["load_baseline_transfer"]
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "baseline-transfer.json"
        self.config = {"model": "provider/model-a"}
        self.space = {"knobs": {"model": ["provider/model-a"]}}
        self.payload = {
            "format_version": 2,
            "baseline_config": self.config,
            "baseline_space": self.space,
            "incumbent_config": self.config,
            "tuning_rows": 2,
            "tuning_fingerprint": "measured-dataset-fingerprint",
            "metric_name": "quality",
            "objective_signature": [PRIMARY, COST],
            "incumbent_index": 0,
            "trials": [
                {
                    "config": self.config,
                    "status": "completed",
                    "metrics": {"quality": 0.75, "cost": 0.1},
                    "example_results": [
                        {"success": True, "metrics": {"quality": score, "cost": 0.05}}
                        for score in (0.5, 1.0)
                    ],
                }
            ],
        }
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")

    def restore(self, objectives, **kwargs):
        return self.load(
            str(self.path),
            self.config,
            self.space,
            2,
            "measured-dataset-fingerprint",
            "quality",
            objectives,
            **kwargs,
        )

    def test_identical_objectives_need_no_transition_record(self):
        trials, incumbent = self.restore([PRIMARY, COST])
        self.assertIs(incumbent, trials[0])
        self.assertEqual(incumbent.metrics, {"quality": 0.75, "cost": 0.1})

    def test_recorded_secondary_cost_removal_preserves_measurements_and_history(self):
        before = self.path.read_bytes()
        trials, incumbent = self.restore([PRIMARY], cost_removal_record=REMOVAL)
        self.assertIs(incumbent, trials[0])
        self.assertEqual(incumbent.metrics, {"quality": 0.75, "cost": 0.1})
        self.assertEqual(
            incumbent.metadata["example_results"],
            self.payload["trials"][0]["example_results"],
        )
        self.assertEqual(
            incumbent.metadata["baseline_objective_signature"], [PRIMARY, COST]
        )
        self.assertEqual(
            incumbent.metadata["comparison_objective_signature"], [PRIMARY]
        )
        self.assertEqual(incumbent.metadata["cost_removal_record"], REMOVAL)
        self.assertEqual(self.path.read_bytes(), before)

    def test_secondary_cost_removal_requires_record(self):
        with self.assertRaisesRegex(SystemExit, "baseline identity"):
            self.restore([PRIMARY])

    def test_malformed_or_blank_transition_evidence_is_rejected(self):
        for record in (
            None,
            "approved",
            True,
            {},
            {"reason": "unavailable"},
            {"approval_reference": "run-plan.md"},
            {**REMOVAL, "reason": " \n\t "},
            {**REMOVAL, "approval_reference": "   "},
            {**REMOVAL, "reason": True},
            {**REMOVAL, "approval_reference": 1},
            {**REMOVAL, "allow_arbitrary_changes": True},
        ):
            with self.subTest(record=record):
                with self.assertRaises(SystemExit):
                    self.restore([PRIMARY], cost_removal_record=record)

    def test_primary_identity_and_direction_and_weight_stay_exact(self):
        for changed in (
            {**PRIMARY, "name": "accuracy"},
            {**PRIMARY, "orientation": "minimize"},
            {**PRIMARY, "weight": 2.0},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(SystemExit):
                    self.restore([changed], cost_removal_record=REMOVAL)

    def test_unavailable_cost_does_not_allow_other_secondary_changes(self):
        latency = {"name": "latency", "orientation": "minimize", "weight": 0.25}
        self.payload["objective_signature"] = [PRIMARY, COST, latency]
        self.save()
        trials, _ = self.restore([PRIMARY, latency], cost_removal_record=REMOVAL)
        self.assertEqual(len(trials), 1)
        for requested in (
            [PRIMARY],
            [latency, PRIMARY],
            [PRIMARY, {**latency, "weight": 1.0}],
            [PRIMARY, {**latency, "name": "reliability"}],
        ):
            with self.subTest(requested=requested):
                with self.assertRaises(SystemExit):
                    self.restore(requested, cost_removal_record=REMOVAL)

    def test_cost_cannot_be_added_back_as_a_transition(self):
        self.payload["objective_signature"] = [PRIMARY]
        self.save()
        with self.assertRaises(SystemExit):
            self.restore([PRIMARY, COST], cost_removal_record=REMOVAL)

    def test_duplicate_or_missing_primary_objectives_are_rejected(self):
        for signature in (
            [PRIMARY, COST, COST],
            [PRIMARY, PRIMARY, COST],
            [COST],
            [None, COST],
            [{"name": ""}, COST],
        ):
            with self.subTest(signature=signature):
                self.payload["objective_signature"] = signature
                self.save()
                with self.assertRaises(SystemExit):
                    self.restore([PRIMARY], cost_removal_record=REMOVAL)

    def test_invalid_objective_definitions_do_not_enable_a_transition(self):
        for changed in (
            {**PRIMARY, "orientation": "higher"},
            {**PRIMARY, "weight": 0},
            {**PRIMARY, "weight": -1},
            {**PRIMARY, "weight": True},
            {**PRIMARY, "weight": float("inf")},
            {**PRIMARY, "weight": float("nan")},
            {**PRIMARY, "weight": 10**1000},
            {"name": "quality", "orientation": "maximize"},
        ):
            with self.subTest(changed=changed):
                self.payload["objective_signature"] = [changed, COST]
                self.save()
                with self.assertRaises(SystemExit):
                    self.restore([changed], cost_removal_record=REMOVAL)

    def test_cost_cannot_be_removed_when_it_is_the_primary_metric(self):
        self.payload["metric_name"] = "cost"
        self.save()
        with self.assertRaises(SystemExit):
            self.load(
                str(self.path),
                self.config,
                self.space,
                2,
                "measured-dataset-fingerprint",
                "cost",
                [PRIMARY],
                cost_removal_record=REMOVAL,
            )

    def test_other_baseline_invariants_still_reject(self):
        original = copy.deepcopy(self.payload)
        for field, value in (
            ("baseline_config", {"model": "provider/changed"}),
            ("baseline_space", {"knobs": {"model": ["provider/changed"]}}),
            ("tuning_rows", 3),
            ("tuning_fingerprint", "changed-dataset-fingerprint"),
            ("metric_name", "accuracy"),
        ):
            with self.subTest(field=field):
                self.payload = {**copy.deepcopy(original), field: value}
                self.save()
                with self.assertRaises(SystemExit):
                    self.restore([PRIMARY], cost_removal_record=REMOVAL)

    def test_incomplete_baseline_is_not_promoted_by_cost_removal(self):
        self.payload["trials"][0]["example_results"][0]["success"] = False
        self.save()
        with self.assertRaises(SystemExit):
            self.restore([PRIMARY], cost_removal_record=REMOVAL)


if __name__ == "__main__":
    unittest.main()

"""The real generated baseline produces bound, local comparison evidence."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import subprocess
import sys
import unittest
from unittest import mock

import test_generate_adapter as adapter_tests

Project = adapter_tests.Project


class GeneratedBaselineHandoffTests(unittest.TestCase):
    runtime_bridge = adapter_tests.CanonicalRuntimeOutcomeTests.runtime_bridge
    baseline_result = adapter_tests.CanonicalRuntimeOutcomeTests.baseline_result

    def test_complete_grid_retains_real_scores_and_has_no_sdk_identity(self):
        with self.runtime_bridge() as (_, bridge, placed):
            bridge.spec["primary_metric"] = {
                "name": "task_quality",
                "orientation": "maximize",
            }
            status, document, _ = self.baseline_result(bridge)
            rows = bridge.tuning_rows()
        self.assertEqual(status, 0)
        self.assertEqual(len(placed), 4)
        transfer = document["comparison_transfer"]
        self.assertEqual(transfer["format_version"], 3)
        self.assertEqual(transfer["producer"], "generated-bridge")
        self.assertEqual(transfer["metric_name"], "task_quality")
        self.assertEqual(
            transfer["objective_signature"],
            [{"name": "task_quality", "orientation": "maximize", "weight": 1.0}],
        )
        expected = [
            {key: row[key] for key in ("input", "expected", "metadata")} for row in rows
        ]
        digest = hashlib.sha256(
            json.dumps(
                expected, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        self.assertEqual(transfer["tuning_fingerprint"], digest)
        self.assertEqual(transfer["incumbent_index"], 0)
        self.assertEqual(len(transfer["trials"]), 2)
        for original, trial in zip(document["results"], transfer["trials"]):
            self.assertEqual(trial["config"], original["config"])
            self.assertEqual(trial["metrics"], {"task_quality": original["mean_score"]})
            self.assertEqual(
                [row["metrics"]["task_quality"] for row in trial["example_results"]],
                [row["score"] for row in original["rows"]],
            )
        self.assertNotIn("cost", json.dumps(transfer))
        self.assertNotIn("trial_id", json.dumps(transfer))
        self.assertNotIn("session_id", json.dumps(transfer))
        self.assertNotIn("billing please", json.dumps(transfer))

    def test_generation_requires_explicit_primary_semantics(self):
        for primary in (
            None,
            {"name": "", "orientation": "maximize"},
            {"name": "cost", "orientation": "maximize"},
            {"name": "task_quality", "orientation": "minimize"},
            {"name": "foo bar", "orientation": "maximize"},
            {"name": "latency", "orientation": "maximize"},
            {"name": "quality_p95", "orientation": "maximize"},
        ):
            with self.subTest(primary=primary):
                project = Project(self)
                if primary is None:
                    project.config.pop("primary_metric", None)
                else:
                    project.config["primary_metric"] = primary
                result = project.generate()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("primary_metric", result.stdout + result.stderr)
                self.assertFalse(project.runs.exists())

    def test_primary_name_contract_matches_the_pinned_sdk_reserved_set(self):
        distribution = importlib.metadata.distribution("traigent")
        self.assertEqual(distribution.version, "0.31.1")
        source = distribution.locate_file("traigent/evaluators/metrics_tracker.py")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        reserved = next(
            node
            for node in tree.body
            if isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", None) == "RESERVED_METRIC_KEYS"
        )
        sdk_reserved = ast.literal_eval(reserved.value.args[0])
        runtime = adapter_tests.MODULE.runtime_contract()
        self.assertEqual(
            runtime.GENERATED_PRIMARY_RESERVED, sdk_reserved - {"accuracy", "score"}
        )
        for name in ("task_quality", "accuracy", "score", "_quality2"):
            self.assertEqual(
                runtime.generated_primary_name(
                    {"name": name, "orientation": "maximize"}
                ),
                name,
            )
        for name in (
            "foo bar",
            "2quality",
            "quality-mean",
            "a_πmetric",
            "latency",
            "cost",
            "measures",
            "quality_p95",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                runtime.generated_primary_name(
                    {"name": name, "orientation": "maximize"}
                )

    def test_best_measured_primary_wins_without_cost_tiebreaking(self):
        agent = adapter_tests.AGENT.replace(
            "mock_response=text.split()[0]",
            'mock_response=text.split()[0] if model.endswith("large") else "wrong"',
        )
        with self.runtime_bridge(agent) as (_, bridge, placed):
            status, document, _ = self.baseline_result(bridge)
        self.assertEqual(status, 0)
        self.assertEqual(len(placed), 4)
        transfer = document["comparison_transfer"]
        self.assertEqual(transfer["incumbent_index"], 1)
        self.assertEqual(transfer["incumbent_config"]["model"], "openai/m-large")
        self.assertEqual(
            [trial["metrics"]["task_quality"] for trial in transfer["trials"]],
            [0.0, 1.0],
        )

    def test_partial_rerun_replaces_prior_eligible_transfer_with_diagnostics(self):
        with self.runtime_bridge() as (_, bridge, placed):
            _, complete, _ = self.baseline_result(bridge)
            self.assertIn("comparison_transfer", complete)

            def fails_one_row(*, output, expected, input_data, metadata=None):
                if input_data.startswith("billing"):
                    raise ValueError("PRIVATE_SCORER_DETAIL")
                return 1.0

            with mock.patch.object(bridge, "score", fails_one_row):
                status, partial, _ = self.baseline_result(bridge)
        self.assertEqual(status, 3)
        self.assertEqual(len(placed), 8)
        self.assertFalse(partial["complete"])
        self.assertNotIn("comparison_transfer", partial)
        self.assertNotIn("PRIVATE_SCORER_DETAIL", json.dumps(partial))

    def test_legacy_spec_keeps_observations_without_invented_identity(self):
        with self.runtime_bridge() as (_, bridge, placed):
            bridge.spec.pop("primary_metric", None)
            status, document, output = self.baseline_result(bridge)
        self.assertEqual(status, 0)
        self.assertEqual(len(placed), 4)
        self.assertTrue(document["complete"])
        self.assertNotIn("comparison_transfer", document)
        self.assertIn("legacy", document["comparison_blocker"])
        self.assertIn("do not replay", output)

    def test_legacy_list_metadata_remains_available_as_diagnostic_results(self):
        with self.runtime_bridge() as (_, bridge, placed):
            bridge.spec.pop("primary_metric", None)
            original = bridge.tuning_rows

            def list_metadata():
                rows = original()
                for row in rows:
                    row["metadata"] = ["preserved", "legacy"]
                return rows

            with mock.patch.object(bridge, "tuning_rows", list_metadata):
                status, document, _ = self.baseline_result(bridge)
        self.assertEqual(status, 0)
        self.assertEqual(len(placed), 4)
        self.assertTrue(document["complete"])
        self.assertNotIn("comparison_transfer", document)
        self.assertIn("legacy", document["comparison_blocker"])

    def test_dataset_change_retains_observations_without_transfer(self):
        with self.runtime_bridge() as (_, bridge, placed):
            bridge.spec["primary_metric"] = {
                "name": "task_quality",
                "orientation": "maximize",
            }
            original = bridge.agent_output
            dataset = bridge.project_root / bridge.spec["dataset"]["path"]

            def changes_source(row, config):
                output = original(row, config)
                dataset.write_text(dataset.read_text() + "\n")
                return output

            with mock.patch.object(bridge, "agent_output", changes_source):
                status, document, _ = self.baseline_result(bridge)
        self.assertEqual(len(placed), 4)
        self.assertTrue(document["results"])
        self.assertNotIn("comparison_transfer", document)
        self.assertIn("changed", document["comparison_blocker"])
        self.assertEqual(status, 3)

    def test_unbound_agent_id_is_refused_before_generation(self):
        project = Project(self)
        project.config["primary_metric"] = {
            "name": "task_quality",
            "orientation": "maximize",
        }
        project.config["agent"]["args"]["suffix"] = "$id"
        project.config["dataset"]["id"] = "id"
        result = project.generate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("metadata", result.stdout + result.stderr)
        self.assertFalse(project.runs.exists())

    def test_effective_metadata_mutation_cannot_keep_a_valid_transfer(self):
        with self.runtime_bridge() as (_, bridge, placed):
            original = bridge.agent_output

            def changes_metadata(row, config):
                output = original(row, config)
                row["metadata"]["changed"] = True
                return output

            with mock.patch.object(bridge, "agent_output", changes_metadata):
                status, document, _ = self.baseline_result(bridge)
        self.assertEqual(status, 3)
        self.assertEqual(len(placed), 1)
        self.assertNotIn("comparison_transfer", document)
        self.assertIn("changed", document["comparison_blocker"])

    def test_later_calls_cannot_restore_mutated_metadata_and_revalidate_the_run(self):
        with self.runtime_bridge() as (_, bridge, placed):
            original = bridge.agent_output

            def toggles_metadata(row, config):
                output = original(row, config)
                if row["metadata"].get("changed"):
                    row["metadata"].pop("changed")
                else:
                    row["metadata"]["changed"] = True
                return output

            with mock.patch.object(bridge, "agent_output", toggles_metadata):
                status, document, _ = self.baseline_result(bridge)
        self.assertEqual(status, 3)
        self.assertEqual(len(placed), 1)
        self.assertEqual(document["stop_reason"], "identity_changed")
        self.assertFalse(document["complete"])
        self.assertNotIn("comparison_transfer", document)
        self.assertEqual(document["results"][0]["n_scored"], 0)

    def test_metadata_bound_agent_id_remains_part_of_the_fingerprint(self):
        rows = [
            {
                "payload": {"q": "billing please"},
                "gold": {"label": "billing"},
                "context": {"example_id": "a"},
            }
        ]
        project = Project(self, rows=rows)
        project.config["dataset"].update(metadata="context", id="context.example_id")
        project.config["agent"]["args"]["suffix"] = "$id"
        generated = project.generate()
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
        baseline = project.bridge("baseline")
        self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
        document = json.loads((project.runs / "baseline-results.json").read_text())
        normalized = [
            {
                "input": "billing please",
                "expected": "billing",
                "metadata": {"example_id": "a"},
            }
        ]
        digest = hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(document["comparison_transfer"]["tuning_fingerprint"], digest)

    def test_suggested_sdk_identity_can_be_explicitly_selected_and_generated(self):
        project = Project(self)
        suggested = subprocess.run(
            [
                sys.executable,
                str(adapter_tests.GENERATOR),
                "suggest",
                "--project-root",
                str(project.root),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(suggested.returncode, 0, suggested.stderr)
        candidates = json.loads(suggested.stdout)["dataset"]["id_candidates"]
        self.assertIn("metadata.example_id", candidates)
        # This is the explicit approved selection, not an automatic suggestion.
        project.config["dataset"]["id"] = "metadata.example_id"
        generated = project.generate()
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)

    def test_missing_duplicate_and_unhashable_identity_refuse_before_calls(self):
        for identities, reason in (
            (("a", "a"), "unique"),
            ((["a"], "b"), "hashable"),
            ((None, "b"), "original example_id"),
        ):
            with self.subTest(identities=identities), self.runtime_bridge() as (
                _,
                bridge,
                placed,
            ):
                original = bridge.tuning_rows

                def invalid_ids():
                    rows = original()
                    for row, identity in zip(rows, identities):
                        if identity is None:
                            row["metadata"].pop("example_id")
                        else:
                            row["id"] = identity
                            row["metadata"]["example_id"] = identity
                            row["raw"]["id"] = identity
                    return rows

                with mock.patch.object(
                    bridge, "tuning_rows", invalid_ids
                ), self.assertRaisesRegex(SystemExit, reason):
                    self.baseline_result(bridge)
                self.assertEqual(placed, [])

    def test_conflicting_id_aliases_are_refused_without_paid_calls(self):
        for alias_location, value in (
            ("top", "different"),
            ("metadata", "different"),
            ("top", True),
        ):
            with self.subTest(
                location=alias_location, value=value
            ), self.runtime_bridge() as (_, bridge, placed):
                original = bridge.tuning_rows

                def conflicting_id():
                    rows = original()
                    if value is True:
                        rows[0]["id"] = 1
                        rows[0]["metadata"]["example_id"] = 1
                    container = (
                        rows[0]["raw"]
                        if alias_location == "top"
                        else rows[0]["metadata"]
                    )
                    container["id"] = value
                    return rows

                with mock.patch.object(
                    bridge, "tuning_rows", conflicting_id
                ), self.assertRaisesRegex(SystemExit, "aliases disagree"):
                    self.baseline_result(bridge)
                self.assertEqual(placed, [])


if __name__ == "__main__":
    unittest.main()

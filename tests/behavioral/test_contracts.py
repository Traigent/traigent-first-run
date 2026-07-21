from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from behavioral import harness

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = Path(__file__).parent / "scenarios"


class BehavioralContractUnitTests(unittest.TestCase):
    def test_all_three_starting_states_are_declared(self) -> None:
        self.assertEqual(
            {path.name for path in SCENARIOS.iterdir() if path.is_dir()},
            {"zero-anchor", "partial-missing-dataset", "weak-invalid"},
        )

    def test_scenario_contracts_are_well_formed(self) -> None:
        for scenario_dir in sorted(
            path for path in SCENARIOS.iterdir() if path.is_dir()
        ):
            with self.subTest(scenario=scenario_dir.name):
                contract = harness.load_contract(scenario_dir)
                harness.validate_contract_shape(contract, scenario_dir)
                harness.verify_fixture_lock(scenario_dir)

    def test_current_behavior_package_matches_qualification_lock(self) -> None:
        lock = json.loads((Path(__file__).parent / "behavior.lock.json").read_text())
        self.assertEqual(harness.behavior_manifest(ROOT), lock)

    def test_forbidden_write_is_rejected(self) -> None:
        contract = {"allowed_writes": ["traigent-runs/**"]}
        with self.assertRaisesRegex(harness.ContractError, "forbidden write"):
            harness.validate_writes(contract, [".env"])

    def test_parent_escape_in_write_contract_is_rejected(self) -> None:
        with self.assertRaisesRegex(harness.ContractError, "unsafe relative path"):
            harness.validate_contract_shape(
                harness.minimal_contract(allowed_writes=["../outside"]),
                Path("scenario"),
            )

    def test_tampered_fixture_is_detected(self) -> None:
        source = SCENARIOS / "partial-missing-dataset"
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / source.name
            harness.copy_scenario(source, copied)
            (copied / "seed" / "agent.py").write_text("tampered = True\n")
            with self.assertRaisesRegex(harness.ContractError, "fixture lock mismatch"):
                harness.verify_fixture_lock(copied)

    def test_tampered_generated_input_is_detected(self) -> None:
        source = SCENARIOS / "partial-missing-dataset"
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / source.name
            harness.copy_scenario(source, copied)
            generated = copied / "generated" / "evaluation-dataset.jsonl"
            generated.write_text(generated.read_text() + "{}\n")
            with self.assertRaisesRegex(harness.ContractError, "fixture lock mismatch"):
                harness.verify_fixture_lock(copied)

    def test_provider_credentials_are_not_forwarded_to_commands(self) -> None:
        environment = harness.command_environment(Path("/tmp/audit.jsonl"))
        for name in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "TRAIGENT_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
        ):
            self.assertNotIn(name, environment)

    def test_package_manager_command_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            harness.ContractError, "command is not allowlisted"
        ):
            harness.validate_command(["pip", "install", "traigent"])


if __name__ == "__main__":
    unittest.main()

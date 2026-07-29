from __future__ import annotations

import json
import shutil
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

    def test_a_tool_cache_inside_the_skill_cannot_enter_the_lock(self) -> None:
        """A linter run must not be able to corrupt the behaviour lock.

        `behavior_manifest` used to walk the filesystem and skip a hand-written
        list of droppings (`__pycache__`, `*.pyc`). `ruff check skills/` writes
        `.ruff_cache/`, which was not on that list, so three untracked files
        entered the lock and it matched only on the machine that wrote it -
        green locally, red in CI, on the same commit. Asking git instead makes
        the ignore rules the single source of truth.
        """
        before = harness.behavior_manifest(ROOT)
        cache = ROOT / "skills" / "traigent-first-run" / ".ruff_cache" / "0.0.0"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("stray tool output")
        try:
            self.assertEqual(harness.behavior_manifest(ROOT), before)
        finally:
            shutil.rmtree(cache.parent)

    def test_an_unignored_new_file_does_enter_the_lock(self) -> None:
        """The rule is git's ignore list, not "hide anything untracked".

        A reference added but not yet `git add`-ed is part of the package and
        must be locked, or regenerating before staging would under-lock it.
        """
        before = harness.behavior_manifest(ROOT)
        stray = ROOT / "skills" / "traigent-first-run" / "references" / "_probe.md"
        stray.write_text("not staged yet")
        try:
            self.assertNotEqual(harness.behavior_manifest(ROOT), before)
        finally:
            stray.unlink()

    def test_the_git_and_walk_file_lists_agree(self) -> None:
        """The hermetic fallback must lock the same package git would.

        The offline-contract job has no git, so it takes the walk. If the two
        ever disagree the lock means one thing in CI and another locally, which
        is the whole failure this pair was written to end - so they are compared
        directly rather than trusted to stay in step. A new `.gitignore` rule
        that matters to the skill tree fails here first.
        """
        self.assertEqual(
            harness.behavior_files(ROOT),
            harness._walk_behavior_files(ROOT),
        )

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

    def test_umask_only_mode_difference_does_not_break_the_fixture_lock(self) -> None:
        """A group-write bit must not read as fixture tampering.

        Git tracks only the owner-execute bit, so a checkout under `umask 0002`
        produces 0664 where a lock written under `umask 022` recorded 0644. That
        is not a content change and must not fail - it previously failed both CI
        jobs for any contributor with a group-write umask.
        """
        source = SCENARIOS / "weak-invalid"
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / source.name
            harness.copy_scenario(source, copied)
            for path in sorted((copied / "seed").rglob("*")):
                if path.is_file():
                    path.chmod(0o664)
            harness.verify_fixture_lock(copied)

    def test_executable_bit_change_is_still_detected(self) -> None:
        """The one permission bit git *does* track must stay locked."""
        source = SCENARIOS / "weak-invalid"
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / source.name
            harness.copy_scenario(source, copied)
            (copied / "seed" / "agent.py").chmod(0o755)
            with self.assertRaisesRegex(harness.ContractError, "fixture lock mismatch"):
                harness.verify_fixture_lock(copied)

    def test_world_writable_fixture_is_rejected(self) -> None:
        source = SCENARIOS / "weak-invalid"
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / source.name
            harness.copy_scenario(source, copied)
            (copied / "seed" / "agent.py").chmod(0o666)
            with self.assertRaisesRegex(harness.ContractError, "world-writable"):
                harness.verify_fixture_lock(copied)

    def test_fixture_lock_mismatch_names_the_offending_entry(self) -> None:
        """A bare 'mismatch' gave no way to tell content from permissions."""
        source = SCENARIOS / "weak-invalid"
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / source.name
            harness.copy_scenario(source, copied)
            (copied / "seed" / "agent.py").write_text("tampered = True\n")
            with self.assertRaisesRegex(harness.ContractError, "seed/agent.py"):
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


def zero_anchor_evidence(extra_arguments: list[str]) -> dict:
    """Build the minimal evidence a clean zero-anchor pass would produce.

    `extra_arguments` is appended to the readiness command so a test can craft
    the one thing under examination and leave every other clause satisfied.
    """
    return {
        "stop_reason": "awaiting_task_intent",
        "network": {"attempts": []},
        "events": [
            {
                "sequence": 1,
                "type": "opening_readiness_score",
                "overall": 0,
                "band": "NOT READY",
                "caps": ["dataset-absent"],
            },
            {"sequence": 2, "type": "question", "category": "task_intent"},
            {"sequence": 3, "type": "stop", "reason": "awaiting_task_intent"},
        ],
        "commands": [
            {"argv": ["<PYTHON>", "scripts/preflight.py", "--json"]},
            {
                "argv": ["<PYTHON>", "scripts/readiness.py", "--preflight", "-"]
                + extra_arguments
                + ["--json"]
            },
        ],
        "writes": [],
    }


def weak_invalid_evidence(extra_arguments: list[str]) -> dict:
    """Build evidence that satisfies every weak-invalid clause but the flag.

    Complete rather than minimal on purpose: if the report ban ever stops
    covering this scenario, the failure must be the ban not firing, not some
    unrelated clause tripping first.
    """
    return {
        "stop_reason": "awaiting_quality_decision",
        "network": {"attempts": []},
        "events": [
            {
                "sequence": 1,
                "type": "quality_findings",
                "findings": [
                    {"component": "agent"},
                    {"component": "dataset"},
                    {"component": "evaluation"},
                ],
            },
            {
                "sequence": 2,
                "type": "question",
                "category": "quality_decision",
                "choices": ["repair", "workflow demonstration", "pause"],
            },
            {"sequence": 3, "type": "stop", "reason": "awaiting_quality_decision"},
        ],
        "commands": [
            {
                "argv": ["<PYTHON>", "scripts/readiness.py", "--preflight", "-"]
                + extra_arguments
                + ["--json"]
            }
        ],
        "writes": [],
    }


class ReportFlagBanTests(unittest.TestCase):
    """The opening readiness gate must never be talked into writing a file.

    `--report <path>` accepts an absolute path, so the file can land outside the
    project tree - where the read-only chmod never applies and the writes
    snapshot still reports `writes: []`. Nothing else in the harness can see it,
    which is why the ban is asserted here rather than left to the fixtures.
    """

    def zero_anchor_contract(self) -> dict:
        return harness.load_contract(SCENARIOS / "zero-anchor")

    def test_attached_report_path_is_rejected(self) -> None:
        """`--report=<path>` is one argv entry; a list membership test misses it."""
        with self.assertRaisesRegex(harness.ContractError, "write a report file"):
            harness.validate_semantics(
                self.zero_anchor_contract(),
                zero_anchor_evidence(["--report=/tmp/outside.md"]),
            )

    def test_separated_report_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(harness.ContractError, "write a report file"):
            harness.validate_semantics(
                self.zero_anchor_contract(),
                zero_anchor_evidence(["--report", "/tmp/outside.md"]),
            )

    def test_clean_opening_pair_is_accepted(self) -> None:
        """The ban must not fire on the pair the scenario actually runs."""
        harness.validate_semantics(
            self.zero_anchor_contract(), zero_anchor_evidence([])
        )

    def test_ban_applies_outside_the_zero_anchor_scenario(self) -> None:
        """The rule is about report files, not about one scenario's allowlist.

        The zero-anchor branch is the only one with an exact-command allowlist,
        so a scenario that scores readiness without one - weak-invalid does -
        would otherwise take a report path with nothing to stop it.
        """
        contract = harness.load_contract(SCENARIOS / "weak-invalid")
        for extra in (["--report=/tmp/outside.md"], ["--report", "/tmp/outside.md"]):
            with self.subTest(extra=extra):
                with self.assertRaisesRegex(
                    harness.ContractError, "write a report file"
                ):
                    harness.validate_semantics(contract, weak_invalid_evidence(extra))

    def test_clean_weak_invalid_run_is_accepted(self) -> None:
        """Without a report flag the same evidence must satisfy every clause."""
        harness.validate_semantics(
            harness.load_contract(SCENARIOS / "weak-invalid"),
            weak_invalid_evidence([]),
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from behavioral import harness, outcomes

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = Path(__file__).parent / "scenarios"


class BehavioralContractUnitTests(unittest.TestCase):
    def test_every_declared_scenario_is_the_expected_set(self) -> None:
        """Pinned so a new scenario is a deliberate addition, not a stray directory.

        `stub-agent-no-anchor` is the quality-based twin of `zero-anchor`: the
        empty project is the case that always worked, and a project holding an
        importable stub that performs no task is the one that could walk past the
        intent gate on a file-presence reading (#61).
        """
        self.assertEqual(
            {path.name for path in SCENARIOS.iterdir() if path.is_dir()},
            {
                "zero-anchor",
                "stub-agent-no-anchor",
                "partial-missing-dataset",
                "weak-invalid",
            },
        )

    def test_scenario_contracts_are_well_formed(self) -> None:
        for scenario_dir in sorted(
            path for path in SCENARIOS.iterdir() if path.is_dir()
        ):
            with self.subTest(scenario=scenario_dir.name):
                contract = harness.load_contract(scenario_dir)
                harness.validate_contract_shape(contract, scenario_dir)
                harness.verify_fixture_lock(scenario_dir)

    def test_every_recorded_outcome_matches_its_hand_declared_expectation(
        self,
    ) -> None:
        """The half no tool writes - and the point of #153.

        Both sides of this check are not the same function: one side runs
        `preflight.py | calibrate_evaluator.py | readiness.py` over committed
        inputs, and the other is the `expected` block a hand wrote in that
        case's `case.json`. Nothing regenerates the declaration, so a change
        that moves a band or a cap keeps failing here until someone edits it
        on purpose - which is precisely what the retired hash lock could not
        do: there, one command made any failure disappear.
        """
        problems = outcomes.declaration_mismatches(outcomes.outcome_manifest())
        self.assertEqual(
            problems,
            [],
            "a recorded outcome no longer matches what its case declares. If "
            "the new outcome is correct, say so by editing that case.json and "
            "explaining the change - there is nothing to regenerate that "
            "would clear this.",
        )

    def test_a_refreshed_manifest_cannot_hide_a_changed_band(self) -> None:
        """The executable form of the claim retiring the hash lock rests on.

        Simulate the defect #153 describes: behaviour changes, and every
        generated record is refreshed so it agrees with the new behaviour.
        Under the retired hash lock that was a green suite. Here the refreshed
        manifest is exactly what `declaration_mismatches` is given, and it
        still reports the change - because the declaration did not move with
        it.
        """
        manifest = outcomes.outcome_manifest()
        self.assertEqual(outcomes.declaration_mismatches(manifest), [])

        identifier = sorted(manifest["cases"])[0]
        refreshed = json.loads(json.dumps(manifest))
        refreshed["cases"][identifier]["outcome"]["band"] = "EXCELLENT"

        problems = outcomes.declaration_mismatches(refreshed)
        self.assertTrue(
            any(
                identifier in problem and "band" in problem and "EXCELLENT" in problem
                for problem in problems
            ),
            f"a refreshed manifest hid a changed band for {identifier}: {problems!r}",
        )

    def test_a_refreshed_manifest_cannot_hide_a_changed_overall(self) -> None:
        manifest = outcomes.outcome_manifest()
        self.assertEqual(outcomes.declaration_mismatches(manifest), [])

        identifier = sorted(manifest["cases"])[0]
        refreshed = json.loads(json.dumps(manifest))
        refreshed["cases"][identifier]["outcome"]["overall"] += 1

        problems = outcomes.declaration_mismatches(refreshed)
        self.assertTrue(
            any(identifier in problem and "overall" in problem for problem in problems),
            f"a refreshed manifest hid a changed overall for {identifier}: "
            f"{problems!r}",
        )

    def test_a_wording_only_change_moves_hashes_and_leaves_outcomes_alone(
        self,
    ) -> None:
        """The two classes have to be distinguishable, or the digest explains nothing.

        A reviewer reading a green CI could not previously tell an edited
        sentence from an edited decision. Appending prose to a behaviour-bearing
        document must move the behaviour manifest - whose digest is stamped
        into every evidence bundle - and leave every recorded outcome
        identical; a changed outcome is then unambiguously the other kind.
        """
        before_hashes = harness.behavior_manifest(ROOT)
        before_outcomes = outcomes.outcome_manifest()

        document = ROOT / "skills" / "traigent-first-run" / "SKILL.md"
        original = document.read_bytes()
        try:
            document.write_bytes(original + b"\n<!-- wording probe -->\n")
            self.assertNotEqual(
                harness.behavior_manifest(ROOT),
                before_hashes,
                "a changed behaviour-bearing document did not move the "
                "behaviour manifest",
            )
            self.assertEqual(
                outcomes.outcome_manifest(),
                before_outcomes,
                "a wording-only edit changed a recorded outcome",
            )
        finally:
            document.write_bytes(original)

    def test_a_conflicted_index_cannot_hash_one_path_twice(self) -> None:
        """The dedupe is structural, not a side effect of the relock refusal.

        `git ls-files --cached` lists index *rows*: a path with unresolved merge
        stages appears three times. `tools/relock.py` refuses such an index
        outright, but `behavior_files` also feeds the manifest whose digest is
        stamped into every evidence bundle, and a manifest that hashes one path
        twice is malformed whatever produced it - so the guarantee is pinned
        where the list is built. The stage rows here are the exact bytes git
        printed for the reproduction in #198.
        """
        conflicted = (
            "GUIDE.md\0"
            "skills/traigent-first-run/references/glossary.md\0"
            "skills/traigent-first-run/references/glossary.md\0"
            "skills/traigent-first-run/references/glossary.md\0"
        )
        with unittest.mock.patch(
            "behavioral.harness.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=conflicted, stderr=""
            ),
        ):
            self.assertEqual(
                harness.behavior_files(ROOT),
                [
                    Path("GUIDE.md"),
                    Path("skills/traigent-first-run/references/glossary.md"),
                ],
            )

    def test_a_tool_cache_inside_the_skill_cannot_enter_the_manifest(self) -> None:
        """A linter run must not be able to corrupt the behaviour manifest.

        `behavior_manifest` used to walk the filesystem and skip a hand-written
        list of droppings (`__pycache__`, `*.pyc`). `ruff check skills/` writes
        `.ruff_cache/`, which was not on that list, so three untracked files
        entered the manifest and it matched only on the machine that wrote it -
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

    def test_an_unignored_new_file_does_enter_the_manifest(self) -> None:
        """The rule is git's ignore list, not "hide anything untracked".

        A reference added but not yet `git add`-ed is part of the package and
        must be hashed, or a digest stamped before staging would under-report
        the package.
        """
        before = harness.behavior_manifest(ROOT)
        stray = ROOT / "skills" / "traigent-first-run" / "references" / "_probe.md"
        stray.write_text("not staged yet")
        try:
            self.assertNotEqual(harness.behavior_manifest(ROOT), before)
        finally:
            stray.unlink()

    def test_the_git_and_walk_file_lists_agree(self) -> None:
        """The hermetic fallback must hash the same package git would.

        The offline-contract job has no git, so it takes the walk. If the two
        ever disagree the digest means one thing in CI and another locally,
        which is the whole failure this pair was written to end - so they are
        compared directly rather than trusted to stay in step. A new
        `.gitignore` rule that matters to the skill tree fails here first.
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


SLOW_SCORER = '''
"""A local scorer that is slow once and then exact. No provider, no network."""

import pathlib
import time


def normalize(value):
    return " ".join(str(value).split()).casefold()


def score(*, output, expected, input_data, metadata):
    marker = pathlib.Path(__file__).with_name("slept.marker")
    if not marker.exists():
        marker.write_text("slept\\n")
        time.sleep(SLEEP_SECONDS)
    return 1.0 if normalize(output) == normalize(expected) else 0.0
'''

SLOW_CASES = [
    {
        "name": "billing",
        "expected": "billing",
        "score_mode": "binary",
        "probes": {
            "good": "billing",
            "equivalent_good": " Billing ",
            "partial": "cancellation",
            "bad": "cancellation",
        },
    },
    {
        "name": "technical support",
        "expected": "technical-support",
        "score_mode": "binary",
        "probes": {
            "good": "technical-support",
            "equivalent_good": " Technical-Support ",
            "partial": "billing",
            "bad": "billing",
        },
    },
]


class CommandTimeoutDerivationTests(unittest.TestCase):
    """The harness bound must never be the thing that kills calibration first.

    A flat 30 seconds here was an order of magnitude below the smallest budget
    `calibrate_evaluator.py` derives for itself, so no scenario could reach the
    slow-evaluator behaviour at all: the timeout record, the pre-cap warning and
    the `evaluator-timeout` cap were reachable only from unit tests driving a
    controlled clock. Deriving the bound from the calibrator's own ceiling is
    what stops the two numbers drifting apart again.
    """

    def calibrate_argv(self, *extra: str) -> list[str]:
        return ["python3", str(harness.CALIBRATE), *extra]

    def test_the_calibration_bound_is_the_calibrators_ceiling_plus_headroom(
        self,
    ) -> None:
        ceiling = harness.calibration_budget_ceiling_seconds()
        self.assertEqual(
            harness.command_timeout_seconds(self.calibrate_argv("--json")),
            ceiling + harness.CALIBRATION_TIMEOUT_HEADROOM_SECONDS,
        )
        # The property that matters, stated separately from the arithmetic: the
        # child must always reach its own verdict first.
        self.assertGreater(
            harness.command_timeout_seconds(self.calibrate_argv("--json")), ceiling
        )

    def test_the_ceiling_read_here_is_the_one_the_calibrator_declares(self) -> None:
        """Reading the source, not restating the number, is the whole point.

        Matched on the suffix alone. An allowlist of name PREFIXES would have
        quietly undone the reason the suffix is the key: a rename to a prefix
        nobody listed would drop out of `declared`, and the test would then be
        asserting nothing while looking green.
        """
        source = (harness.CALIBRATE).read_text()
        declared = [
            line
            for line in source.splitlines()
            if harness.CALIBRATION_CEILING_SUFFIX in line.split("=", 1)[0]
            and not line.startswith((" ", "\t", "#"))
        ]
        self.assertTrue(declared, "the calibrator declares no ceiling constant")
        self.assertIn(
            str(harness.calibration_budget_ceiling_seconds()),
            " ".join(declared),
        )

    def test_a_renamed_ceiling_that_keeps_the_suffix_is_absorbed(self) -> None:
        """A rename of the calibrator's constant must not need an edit here.

        Forward cover, not history: the calibrator declares
        `LLM_JUDGE_TIMEOUT_CEILING_SECONDS` today, and the rename to
        `CALIBRATION_TIMEOUT_CEILING_SECONDS` is proposed on an open branch and
        has not landed. The harness must follow it whichever way it goes,
        without being edited in the same commit, or the coupling is a comment
        rather than a mechanism.
        """
        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "renamed_calibrator.py"
            script.write_text(
                "PROBES_PER_CASE = 4\n"
                "SOMETHING_ELSE_SECONDS = 75\n"
                "CALIBRATION_TIMEOUT_CEILING_SECONDS = 900\n"
            )
            self.assertEqual(harness.calibration_budget_ceiling_seconds(script), 900)

    def test_several_ceilings_resolve_to_the_largest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "two_ceilings.py"
            script.write_text(
                "LLM_JUDGE_TIMEOUT_CEILING_SECONDS = 600\n"
                "CALIBRATION_TIMEOUT_CEILING_SECONDS = 900\n"
            )
            self.assertEqual(harness.calibration_budget_ceiling_seconds(script), 900)

    def test_a_calibrator_with_no_ceiling_raises_instead_of_guessing(self) -> None:
        """Falling back to a number is the defect, so there is no fallback."""
        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "no_ceiling.py"
            script.write_text("PROBES_PER_CASE = 4\n")
            with self.assertRaisesRegex(harness.ContractError, "declares no"):
                harness.calibration_budget_ceiling_seconds(script)

    def test_a_non_positive_ceiling_raises(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "zero_ceiling.py"
            script.write_text("CALIBRATION_TIMEOUT_CEILING_SECONDS = 0\n")
            with self.assertRaisesRegex(harness.ContractError, "positive number"):
                harness.calibration_budget_ceiling_seconds(script)

    def test_an_annotated_ceiling_is_read_like_any_other(self) -> None:
        """`NAME: int = 600` is the same decision as `NAME = 600`.

        Reading only the unannotated form reported a constant that is plainly
        in the file as absent, with the message that says the harness "cannot
        derive its calibration bound". Loud, and false about the file it just
        read - the worst of the two ways to be wrong here, because it sends the
        next reader to fix a calibrator that is not broken.
        """
        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "annotated_calibrator.py"
            script.write_text(
                "PROBES_PER_CASE: int = 4\n"
                "LLM_JUDGE_TIMEOUT_CEILING_SECONDS: int = 600\n"
                # A bare annotation declares a type and no number, so there is
                # nothing to read from it and it must not be mistaken for one.
                "CALIBRATION_TIMEOUT_CEILING_SECONDS: int\n"
            )
            self.assertEqual(harness.calibration_budget_ceiling_seconds(script), 600)

    def test_a_ceiling_that_is_not_a_literal_raises_rather_than_being_skipped(
        self,
    ) -> None:
        """The one failure mode on this path with no test of its own.

        `ast.literal_eval` refuses a name, a call or an expression over other
        constants, and the alternative to raising is to `continue` past it. That
        would be the worst outcome available: a calibrator whose ceiling is
        `BASE * 2` would leave `ceilings` empty and be reported as declaring no
        ceiling at all - a message that sends the next reader to add a constant
        that is already there - or, if a second literal ceiling existed, would
        silently derive the bound from the smaller one.

        Both spellings, because the annotated form takes a different branch to
        the plain assignment and only one of them was reachable from any test.
        """
        for spelling in (
            "CALIBRATION_TIMEOUT_CEILING_SECONDS = BASE_SECONDS * 2",
            "CALIBRATION_TIMEOUT_CEILING_SECONDS: int = BASE_SECONDS * 2",
        ):
            with self.subTest(spelling=spelling):
                with tempfile.TemporaryDirectory() as raw:
                    script = Path(raw) / "computed_calibrator.py"
                    script.write_text(f"BASE_SECONDS = 300\n{spelling}\n")
                    with self.assertRaisesRegex(
                        harness.ContractError, "non-literal"
                    ) as caught:
                        harness.calibration_budget_ceiling_seconds(script)
                # The message must name the constant it could not read, or it
                # sends the reader to the wrong line of a file it just parsed.
                self.assertIn(
                    "CALIBRATION_TIMEOUT_CEILING_SECONDS", str(caught.exception)
                )

    def test_a_ceiling_that_is_a_literal_of_the_wrong_type_raises(self) -> None:
        """A literal `ast.literal_eval` accepts but a wall-clock bound cannot be.

        Disjoint from `test_a_non_positive_ceiling_raises` above, which owns the
        sign. This owns the type, and `True` is the trap worth naming:
        `isinstance(True, int)` is true in Python, so a check for a positive
        integer alone accepts it and bounds the calibrator at one second.
        """
        for value in ("True", '"600"', "600.0"):
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as raw:
                    script = Path(raw) / "mistyped_calibrator.py"
                    script.write_text(
                        f"CALIBRATION_TIMEOUT_CEILING_SECONDS = {value}\n"
                    )
                    with self.assertRaisesRegex(
                        harness.ContractError, "positive number of seconds"
                    ):
                        harness.calibration_budget_ceiling_seconds(script)

    def test_a_calibrator_that_does_not_parse_raises_a_contract_error(self) -> None:
        """One question, one exception type.

        `ast.parse` sat outside the wrapping, so a calibrator that could not be
        READ raised `ContractError` while a calibrator that could not be PARSED
        escaped as a bare `SyntaxError`, and every caller had to know both.
        """
        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "unparseable_calibrator.py"
            script.write_text("CALIBRATION_TIMEOUT_CEILING_SECONDS = (900\n")
            with self.assertRaisesRegex(harness.ContractError, "cannot parse"):
                harness.calibration_budget_ceiling_seconds(script)

    def test_local_scripts_keep_the_short_fail_fast_bound(self) -> None:
        """Deriving everywhere would be the opposite mistake.

        `readiness.py` and `preflight.py` do local computation that returns in
        well under a second. Giving them the calibration bound would turn a hung
        readiness script from a 30-second failure into a quarter-hour one.
        """
        for script in (harness.READINESS, harness.PREFLIGHT):
            with self.subTest(script=script.name):
                self.assertEqual(
                    harness.command_timeout_seconds(["python3", str(script), "--json"]),
                    harness.DEFAULT_COMMAND_TIMEOUT_SECONDS,
                )
        self.assertLess(
            harness.DEFAULT_COMMAND_TIMEOUT_SECONDS,
            harness.calibration_budget_ceiling_seconds(),
        )

    def test_an_explicit_timeout_moves_the_bound_with_it(self) -> None:
        """The ceiling does not clamp `--timeout`, so neither can this bound.

        An explicit `--timeout` is how a user with a genuinely slow evaluator is
        told to answer the timeout question. A bound pinned to the ceiling would
        make that answer unexercisable above the ceiling.
        """
        for argv in (
            self.calibrate_argv("--timeout", "1200"),
            self.calibrate_argv("--timeout=1200"),
        ):
            with self.subTest(argv=argv[2:]):
                self.assertEqual(
                    harness.command_timeout_seconds(argv),
                    1200 + harness.CALIBRATION_TIMEOUT_HEADROOM_SECONDS,
                )

    def test_a_malformed_timeout_argument_raises(self) -> None:
        for argv in (
            self.calibrate_argv("--timeout"),
            self.calibrate_argv("--timeout", "soon"),
            self.calibrate_argv("--timeout=0"),
        ):
            with self.subTest(argv=argv[2:]):
                with self.assertRaises(harness.ContractError):
                    harness.command_timeout_seconds(argv)


class TimeoutEvidenceTests(unittest.TestCase):
    """A kill that discards the output makes its own timeout undiagnosable."""

    def test_a_timeout_reports_what_the_command_had_already_written(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            script = project / "hangs.py"
            script.write_text(
                "import sys, time\n"
                "print('PROGRESS-ON-STDOUT', flush=True)\n"
                "sys.stderr.write('DIAGNOSTIC-ON-STDERR\\n')\n"
                "sys.stderr.flush()\n"
                "time.sleep(600)\n"
            )
            argv = [sys.executable, str(script)]
            with unittest.mock.patch.object(
                harness, "ALLOWED_SCRIPTS", {script.resolve()}
            ), unittest.mock.patch.object(
                harness, "command_timeout_seconds", lambda argv: 2
            ):
                with self.assertRaises(harness.ContractError) as caught:
                    harness.run_command(argv, project, project / "audit.jsonl")
        message = str(caught.exception)
        self.assertIn("timed out after 2s", message)
        self.assertIn("PROGRESS-ON-STDOUT", message)
        self.assertIn("DIAGNOSTIC-ON-STDERR", message)

    def test_an_oversized_capture_is_truncated_rather_than_raised_on(self) -> None:
        """`clean_capture` raises past the evidence limit; this path must not.

        Replacing the timeout diagnostic with a different error would lose the
        output a second time, which is the defect wearing a new hat.
        """
        rendered = harness.timeout_capture(
            "x" * (harness.TIMEOUT_CAPTURE_LIMIT + 50), Path("/nowhere")
        )
        self.assertIn("[+50 characters dropped]", rendered)

    def test_control_characters_are_escaped_rather_than_raised_on(self) -> None:
        self.assertIn("\\x1b", harness.timeout_capture("\x1b[31mred", Path("/nowhere")))

    def test_a_failed_collection_says_so_rather_than_looking_silent(self) -> None:
        self.assertIn("unavailable", harness.timeout_capture(None, Path("/nowhere")))


FAST_SCORER = '''
"""An exact local scorer. No provider, no network, no wait."""


def normalize(value):
    return " ".join(str(value).split()).casefold()


def score(*, output, expected, input_data, metadata):
    return 1.0 if normalize(output) == normalize(expected) else 0.0
'''


class DerivedBoundEndToEndTests(unittest.TestCase):
    """One real run whose bound comes from the derivation, not from `--timeout`.

    The slow test below passes `--timeout 300`, so it routes through
    `explicit_timeout_seconds` and returns before the AST derivation is ever
    reached. Measured: with `calibration_budget_ceiling_seconds` replaced by an
    unconditional raise, that test still passed in 34.2s. So the derivation had
    no end-to-end exercise at all - a silent fallback in it would have been
    invisible outside the unit tests that call it directly.

    This one is deliberately fast (about a second) because the point is the
    ROUTE, not the wait: it asserts the invocation genuinely takes the derived
    branch, and then runs it for real through the same `run_command` the
    scenarios use.
    """

    def test_a_calibration_without_a_timeout_flag_runs_on_the_derived_bound(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            (project / "scorer.py").write_text(FAST_SCORER)
            (project / "cases.json").write_text(json.dumps(SLOW_CASES))
            argv = [
                sys.executable,
                str(harness.CALIBRATE),
                "--scorer",
                "scorer.py:score",
                "--cases",
                "@cases.json",
                "--allow-execution",
                "--json",
            ]
            # The decision this test exists to hold: no `--timeout` here. Adding
            # one back would route around the derivation again and leave the
            # rest of this test passing for the wrong reason.
            self.assertIsNone(
                harness.explicit_timeout_seconds(argv),
                "this end-to-end case must reach the derivation, so it may not "
                "pass --timeout",
            )
            self.assertEqual(
                harness.command_timeout_seconds(argv),
                harness.calibration_budget_ceiling_seconds()
                + harness.CALIBRATION_TIMEOUT_HEADROOM_SECONDS,
            )
            record = harness.run_command(argv, project, project / "audit.jsonl")

        payload = json.loads(record["stdout"])
        self.assertTrue(payload["passed"])
        self.assertFalse(payload.get("timed_out", False))


class SlowEvaluatorEndToEndTests(unittest.TestCase):
    """The scenario the flat 30-second bound made impossible to write.

    This is the only end-to-end exercise of a calibration that OUTLIVES the old
    bound: everything else about the slow path is unit-tested against a
    controlled clock, which cannot catch a harness that kills the real child.
    It is not an exercise of the derivation - it passes `--timeout`, so it takes
    the explicit branch; `DerivedBoundEndToEndTests` above covers the other one.

    It costs real wall time on purpose - thirty-three seconds, spent in
    `time.sleep` inside a LOCAL scorer - 33s by construction, and 34.2s wall
    for the test measured on a developer machine, not on a runner. No
    provider is called and no key is read, so the cost is runner seconds and
    nothing else, and `.github/workflows/validate.yml` budgets for it.
    """

    def test_a_calibration_slower_than_the_old_flat_bound_now_completes(self) -> None:
        sleep_seconds = harness.DEFAULT_COMMAND_TIMEOUT_SECONDS + 3
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            (project / "scorer.py").write_text(
                f"SLEEP_SECONDS = {sleep_seconds}\n{SLOW_SCORER}"
            )
            (project / "cases.json").write_text(json.dumps(SLOW_CASES))
            argv = [
                sys.executable,
                str(harness.CALIBRATE),
                "--scorer",
                "scorer.py:score",
                "--cases",
                "@cases.json",
                "--allow-execution",
                # The answer a user with a slow evaluator is told to give. The
                # harness has to be able to run it, which is the whole point.
                "--timeout",
                "300",
                "--json",
            ]
            self.assertGreater(harness.command_timeout_seconds(argv), sleep_seconds)
            started = time.monotonic()
            record = harness.run_command(argv, project, project / "audit.jsonl")
            elapsed = time.monotonic() - started

        self.assertGreater(
            elapsed,
            harness.DEFAULT_COMMAND_TIMEOUT_SECONDS,
            "the fixture no longer outlives the bound it exists to outlive",
        )
        payload = json.loads(record["stdout"])
        self.assertTrue(payload["passed"])
        self.assertFalse(payload.get("timed_out", False))


if __name__ == "__main__":
    unittest.main()

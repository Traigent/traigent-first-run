"""What the free chain OUTPUTS for fixed inputs, declared so a change to it is readable.

For a handful of committed inputs under `outcomes/`, this module runs
`preflight.py | calibrate_evaluator.py | readiness.py` and records what the
chain actually decides - the band, the status, the recommended action, and the
caps. Each case's `case.json` carries a hand-declared `expected` block stating
the same card, and `test_contracts.py` checks a fresh run against it. A change
that alters what a customer is told then fails as a diff of that card, which
names the thing that moved.

Hermetic and free, by construction and not by promise: every command goes
through `harness.run_command`, which runs it under `harness.command_environment`
- no provider credentials in the environment, `PIP_NO_INDEX=1`, and the
`sitecustomize` socket guard on `PYTHONPATH`. The three scripts make no provider
call and import no SDK (`--defer-missing-sdk`), so this costs nothing and
touches no network. The offline-socket contract is unchanged by this file.

## Why no regeneration can re-green a real change

The declarations are written by hand and no tool writes them. The repository
used to commit two generated artifacts beside them - a hash lock over every
behaviour-bearing file, which answered "did these bytes change" (a question
`git diff` already answers) and whose every failure one command could make
disappear (traigent-first-run#153), and a generated copy of these recorded
cards, which restated the declarations byte-for-byte. Both are retired. What
remains is the half nothing regenerates: a changed band, status, action or cap
fails against the `expected` block in that case's `case.json`.

Updating a case legitimately is then a deliberate, reviewable act: edit the
declaration in `case.json` and say why in the pull request. Silently
re-greening is not available, because there is no command that moves the
declaration.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from behavioral import harness

CASES = Path(__file__).resolve().parent / "outcomes"
SCHEMA_VERSION = 1

# The fields lifted out of the readiness score and recorded here. Deliberately
# not the whole payload: `pillars`, `knobs` and `gaps` restate the same evidence
# in more words, and a declaration that records everything must be re-edited
# for everything - the failure mode #153 reports from an 11-pull-request
# integration. These four are what the customer is actually told.
RECORDED_FIELDS = ("band", "status", "recommended_action", "overall")
# Per cap, the identity and both routing flags. `blocks` and `asks` are what
# `recommended_action` reads, so a cap that silently changes kind is a change to
# what the run does, not only to what it scores.
RECORDED_CAP_FIELDS = ("condition", "ceiling", "blocks", "asks")
EXPECTED_FIELDS = frozenset(
    (*RECORDED_FIELDS, "caps", "asks_about_repeats", "band_held_for_unread_answers")
)

REQUIRED_CASE_KEYS = {"id", "state", "why", "expected"}
# What a case is allowed to say about the run, beside the four it must say.
#
# Checked rather than read with `.get` alone, because every one of these is
# optional and a misspelled key is therefore silent: the flag is simply not
# passed, the card moves, and the declaration beneath it is re-recorded to
# match a call nobody meant to make. That is the failure this file exists to
# make impossible for a SCORE, and it was available one level up.
OPTIONAL_CASE_KEYS = {
    "dataset",
    "calibration",
    "config_space",
    "agent_origin",
    "evaluator",
    "evaluator_method",
    "evaluator_origin",
    "task_kind",
}
# Every state the score's own output selection can be in. `recommended_action`
# has four arms - first blocking cap, else first asking cap, else the first
# outstanding ask that is no cap at all, else `proceed` - and `status` is
# BLOCKED exactly when a blocking cap exists. These four cover every arm and
# both statuses, which is why they are the four and not an arbitrary sample.
#
# The state names the CAP SHAPE the case is in, which is why `clean` still fits
# a case whose action is not `proceed`. `clean-proceed` carries no cap and is
# routed by its outstanding ask (traigent-first-run#396); the fall-through to
# `proceed` is reached by `advisory-bounded-claim`, whose ceilings neither block
# nor ask. A fifth case for the fourth arm would duplicate a whole project to
# re-record a decision `clean-proceed` already makes.
STATES = frozenset({"clean", "blocked", "advisory", "asking"})


class OutcomeError(RuntimeError):
    """Raised when an outcome case is malformed or its run cannot be trusted."""


def case_directories() -> list[Path]:
    if not CASES.is_dir():
        raise OutcomeError(f"no outcome cases directory at {CASES}")
    return sorted(path for path in CASES.iterdir() if path.is_dir())


def load_case(case_dir: Path) -> dict[str, Any]:
    contract = json.loads((case_dir / "case.json").read_text())
    missing = REQUIRED_CASE_KEYS - set(contract)
    if missing:
        raise OutcomeError(f"{case_dir.name}: case.json lacks {sorted(missing)}")
    if contract["id"] != case_dir.name:
        raise OutcomeError(
            f"{case_dir.name}: case.json id is {contract['id']!r}; the id names "
            "the directory so a case cannot be renamed in one place only"
        )
    if contract["state"] not in STATES:
        raise OutcomeError(
            f"{case_dir.name}: state {contract['state']!r} is not one of "
            f"{sorted(STATES)}"
        )
    unknown = sorted(set(contract) - REQUIRED_CASE_KEYS - OPTIONAL_CASE_KEYS)
    if unknown:
        raise OutcomeError(
            f"{case_dir.name}: case.json carries unknown key(s) "
            f"{unknown}; every key here becomes part of the call the card was "
            "recorded from, so one nobody reads is a flag nobody passed"
        )
    expected_fields = set(contract["expected"])
    if expected_fields != EXPECTED_FIELDS:
        missing = sorted(EXPECTED_FIELDS - expected_fields)
        extra = sorted(expected_fields - EXPECTED_FIELDS)
        raise OutcomeError(
            f"{case_dir.name}: expected must declare every recorded outcome "
            f"field; missing={missing}, extra={extra}"
        )
    return contract


def recorded_outcome(score: dict[str, Any]) -> dict[str, Any]:
    """The part of a readiness score these cases are a statement about."""
    outcome = {field: score[field] for field in RECORDED_FIELDS}
    # Whether the run put a question to the customer about repeated rows, as a
    # boolean rather than the counts behind it. A case declares what the run
    # DOES, and the counts move with any change to the fixture's size while the
    # question either arrives or does not. Without it, a regression that began
    # asking about repeats on the clean fixtures would leave every declared
    # field untouched and no case would fail.
    outcome["asks_about_repeats"] = score.get("repeated_inputs") is not None
    # WHICH GATE HOLDS THE BAND, recorded because a band can be held by more
    # than one and the card looks identical either way. `clean-proceed` scores
    # 91 with no cap at all and still reads WORKABLE: the answer-key floor is
    # what holds it, and before the argv obeyed `SKILL.md` it was the
    # confidence gate over a withheld task-fit check. Without this field that
    # substitution is invisible - same band, same number, different reason -
    # which is the swap `test_contracts.py` used to pin the old argv against
    # (traigent-first-run#405, #407).
    outcome["band_held_for_unread_answers"] = (
        score.get("band_limited_by_unread_answers") is True
    )
    outcome["caps"] = [
        {field: cap[field] for field in RECORDED_CAP_FIELDS} for cap in score["caps"]
    ]
    return outcome


def run_case(case_dir: Path, contract: dict[str, Any]) -> dict[str, Any]:
    """Run the free chain over one committed case and return its recorded card.

    The project is copied to a temporary directory first. The cases are
    committed read-only inputs; running in place would let a chain that writes
    (none of these do today) edit the fixture it is being measured against.
    """
    work = Path(tempfile.mkdtemp(prefix=f"outcome-{contract['id']}-"))
    project = work / "project"
    shutil.copytree(case_dir / "project", project)
    audit_log = work / "audit.jsonl"

    environment = project / ".env"
    if not environment.exists():
        environment.write_text("")
    # Preflight FAILs a group- or world-readable .env before it reads anything
    # else, and git records no mode below the executable bit - so the committed
    # fixture cannot carry 0600 and it is set here instead.
    environment.chmod(0o600)

    argv = [sys.executable, str(harness.PREFLIGHT), "--env", str(environment)]
    dataset = contract.get("dataset")
    if dataset:
        argv.extend(("--dataset", str(project / dataset)))
    # The preflight half of the run-scoped evaluator rules. `SKILL.md` puts the
    # resolved method on every PAIRED preflight/readiness invocation, so the
    # method cannot be added to the score alone without splitting the pair the
    # rule is about, and `preflight.py --evaluator` is to be passed wherever an
    # evaluator file was found. These cases shipped one and told preflight
    # nothing about it (traigent-first-run#407).
    evaluator = contract.get("evaluator")
    if evaluator:
        argv.extend(("--evaluator", str(project / evaluator)))
    evaluator_method = contract.get("evaluator_method")
    if evaluator_method:
        argv.extend(("--evaluator-method", evaluator_method))
    argv.extend(("--defer-missing-sdk", "--json"))
    preflight = harness.run_command(argv, project, audit_log)

    calibration_path: Path | None = None
    calibration = contract.get("calibration")
    if calibration:
        result = harness.run_command(
            [
                sys.executable,
                str(harness.CALIBRATE),
                "--scorer",
                calibration["scorer"],
                "--cases",
                f"@{project / calibration['cases']}",
                "--allow-execution",
                "--json",
            ],
            project,
            audit_log,
        )
        parsed = json.loads(result["stdout"])
        if not parsed.get("passed"):
            raise OutcomeError(
                f"{contract['id']}: calibration did not pass, so this case "
                "measures a broken fixture rather than the state it declares"
            )
        calibration_path = work / "calibration-results.json"
        calibration_path.write_text(json.dumps(parsed, indent=2, sort_keys=True) + "\n")

    # The readiness argv is built here rather than through
    # `harness.score_command`, which takes no `--config-space`. Extending that
    # helper would change the call the four container scenarios make, and these
    # cases are not worth destabilising them for.
    score_argv = [sys.executable, str(harness.READINESS), "--preflight", "-"]
    if calibration_path is not None:
        score_argv.extend(("--calibration", str(calibration_path)))
    config_space = contract.get("config_space")
    if config_space:
        score_argv.extend(("--config-space", str(project / config_space)))
    # Declared where the project actually holds an agent, because SKILL.md says
    # to declare it on every scoring call and to omit the flag only where the
    # component does not exist. These cases were scoring projects with an
    # `agent.py` in them as though nobody had mentioned an agent, which since
    # #375 is a different card - `agent-absent` blocks where an unread agent
    # only bounds - so the fixture was measuring a state it does not describe.
    agent_origin = contract.get("agent_origin")
    if agent_origin:
        score_argv.extend(("--agent-origin", agent_origin))
    # The rest of the same rule, and the reason the recorded cards moved.
    #
    # `SKILL.md` declares the evaluator's author on every readiness call under
    # the paragraph that declares the agent's, and omitting either is permitted
    # only while that component does not exist; the method is the run-scoped
    # value paired with preflight above; the task kind is the conditional one,
    # passed where project evidence grounds a recognised kind. Three of these
    # four cases ship and calibrate an evaluator over three fixed labels, so all
    # three flags were forbidden omissions and the reference cards were the
    # output of a call the guide does not permit (traigent-first-run#407).
    #
    # Carried per case rather than derived here on purpose. What each value IS
    # is a reading of that fixture's own evaluator and rows, and a helper that
    # guessed it would be this file scoring its own homework.
    if evaluator_origin := contract.get("evaluator_origin"):
        score_argv.extend(("--evaluator-origin", evaluator_origin))
    if evaluator_method:
        score_argv.extend(("--evaluator-method", evaluator_method))
    if task_kind := contract.get("task_kind"):
        score_argv.extend(("--task-kind", task_kind))
    score_argv.append("--json")
    score = json.loads(
        harness.run_command(
            score_argv,
            project,
            audit_log,
            stdin_text=harness.normalize_text(preflight["stdout"], project),
        )["stdout"]
    )
    if sorted(pillar["name"] for pillar in score["pillars"]) != [
        "agent",
        "dataset",
        "evaluation",
    ]:
        raise OutcomeError(f"{contract['id']}: readiness must report all three pillars")

    attempts = harness.read_audit_events(audit_log)
    if attempts:
        raise OutcomeError(
            f"{contract['id']}: the chain attempted network access {attempts!r}; "
            "these cases are free and offline and a case that reaches the "
            "network is not measuring the free chain"
        )
    return recorded_outcome(score)


def outcome_manifest() -> dict[str, Any]:
    """What every committed case currently derives."""
    cases = {}
    for case_dir in case_directories():
        contract = load_case(case_dir)
        cases[contract["id"]] = {
            "state": contract["state"],
            "outcome": run_case(case_dir, contract),
        }
    covered = {entry["state"] for entry in cases.values()}
    if covered != STATES:
        raise OutcomeError(
            "the outcome cases cover states "
            f"{sorted(covered)}, not {sorted(STATES)}. Each state is one arm of "
            "the score's own output selection; dropping one stops these cases "
            "describing what that arm does."
        )
    return {"schema_version": SCHEMA_VERSION, "cases": cases}


def declaration_mismatches(manifest: dict[str, Any]) -> list[str]:
    """Where a recorded outcome disagrees with its hand-declared expectation.

    No tool writes the `expected` blocks, so a real behaviour change cannot be
    cleared by regenerating anything - only by editing the declaration on
    purpose and saying why (#153).
    """
    problems = []
    for case_dir in case_directories():
        contract = load_case(case_dir)
        recorded = manifest["cases"][contract["id"]]["outcome"]
        for field, declared in contract["expected"].items():
            actual = recorded.get(field)
            if actual != declared:
                problems.append(
                    f"{contract['id']}: {field} is {actual!r}, but "
                    f"{case_dir.name}/case.json declares {declared!r}"
                )
    return problems

"""What the boundary verifier proves, and what it must refuse to call proven.

The defect this guards is not "the check reports the wrong verdict". It is the
narrower and more dangerous one named in traigent-first-run#290: a check that
cannot run reporting like a check that passed. Every path that establishes
nothing - no container runtime, a command that never runs the probe, a probe
whose output is truncated - has a case here asserting it does NOT exit 0, and
those cases need no container so they run everywhere the suite does.

The container-backed cases are the other half and they are skipped, never
faked, when no runtime is present. They are also the only ones that can catch a
verdict that is right about the probe's output and wrong about the world, which
is why the writable-mount case reads the host afterwards rather than the report.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "traigent-first-run" / "scripts" / "verify_sandbox.py"
PREFLIGHT = ROOT / "skills" / "traigent-first-run" / "scripts" / "preflight.py"

sys.path.insert(0, str(SCRIPT.parent))

import preflight  # noqa: E402
import verify_sandbox  # noqa: E402

TOKEN = "0123456789abcdef"
MARKER = Path("/nonexistent/host-marker")

# The header `/proc/net/route` always carries, kept verbatim because the parser
# drops the first line by position and a header that stops being one line is
# the way that goes wrong.
ROUTE4_HEADER = "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT"
# Measured inside `docker run --network none`: a namespace with no connectivity
# still lists loopback routes here, so "no IPv6 lines" is not the passing shape
# and a parser that expects it would refuse a correct boundary.
ROUTE6_LOOPBACK = [
    "00000000000000000000000000000000 00 "
    + "0" * 32
    + " 00 "
    + "0" * 32
    + "        lo",
    "00000000000000000000000000000001 80 "
    + "0" * 32
    + " 00 "
    + "0" * 32
    + "        lo",
]


def probe_output(**overrides: object) -> str:
    """The report a compliant boundary produces, with one part replaced."""
    parts: dict[str, object] = {
        "token": TOKEN,
        "uid": "65534",
        "marker": "absent",
        "scratch-write": "refused",
        "workdir-write": "refused",
        "route4": [ROUTE4_HEADER],
        "route6": ROUTE6_LOOPBACK,
        "env": ["PATH=/usr/local/bin:/usr/bin", "HOSTNAME=abc123"],
        "done": TOKEN,
    }
    parts.update(overrides)
    lines = [
        f"@token {parts['token']}",
        f"@uid {parts['uid']}",
        f"@marker {parts['marker']}",
        f"@scratch-write {parts['scratch-write']}",
        f"@workdir-write {parts['workdir-write']}",
    ]
    for name in ("route4", "route6", "env"):
        section = parts[name]
        if section is None:
            continue
        lines.append(f"@begin {name}")
        lines.extend(section)  # type: ignore[arg-type]
        lines.append(f"@end {name}")
    lines.append(f"@done {parts['done']}")
    return "\n".join(lines) + "\n"


def verdicts(output: str, landed: list[Path] | None = None) -> dict[str, str]:
    properties = verify_sandbox.evaluate(output, TOKEN, MARKER, landed or [])
    return {item.name: item.verdict for item in properties}


def run_script(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(cwd) if cwd else None,
        check=False,
    )


def usable_container_image() -> str | None:
    """A container image already on this host, or `None`.

    Already on this host, because pulling one is a network call the suite must
    not make. A missing runtime and a missing image are the same answer here -
    this machine cannot drive a real boundary - and both must skip rather than
    invent one.
    """
    if not shutil.which("docker"):
        return None
    try:
        probe = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if probe.returncode != 0:
        return None
    for image in ("alpine:3", "alpine:latest", "python:3.12-slim"):
        present = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if present.returncode == 0:
            return image
    return None


IMAGE = usable_container_image()
NO_RUNTIME = (
    "no container runtime with a local image is available here, so the "
    "container-backed half of the boundary verifier did not run. This is a "
    "skip and never a pass: the cases that assert an unverifiable boundary "
    "does not exit 0 run without a runtime and are not skipped."
)


class ReadingTheProbeTests(unittest.TestCase):
    """The verdicts, over probe output, with no container in sight."""

    def test_a_compliant_report_proves_every_property(self) -> None:
        self.assertEqual(
            verdicts(probe_output()),
            {
                "entered": "proven",
                "network": "proven",
                "credentials": "proven",
                "filesystem": "proven",
                "identity": "proven",
            },
        )

    def test_a_probe_that_never_ran_proves_nothing(self) -> None:
        """The whole defect, in one case: silence must not read as clean.

        Only `entered` is reported, because the other four would each say "the
        probe did not tell me" - four problems on the screen where there is one.
        """
        result = verdicts("")
        self.assertEqual(result, {"entered": "unverified"})

    def test_a_report_from_another_run_does_not_speak_for_this_one(self) -> None:
        """A well-formed report carrying someone else's token proves nothing.

        This is the case that makes the token load-bearing rather than
        decorative, and it is the one an outcome-only assertion misses: empty
        output is unverified whether or not the token is checked, so a probe
        that never ran cannot tell the two apart. A complete, entirely
        compliant-looking report that is not from this invocation can - it is
        what a replayed capture, a cached layer, or a wrapper answering with a
        canned line all look like.
        """
        replayed = probe_output(token="deadbeefdeadbeef", done="deadbeefdeadbeef")
        self.assertEqual(verdicts(replayed), {"entered": "unverified"})

    def test_a_probe_cut_off_before_it_finished_is_not_a_finished_one(self) -> None:
        """Everything reported, `@done` missing: the probe was killed midway.

        Its readings so far may be perfectly true and are still not a
        measurement of a completed probe, so nothing below `entered` is read.
        """
        cut = probe_output().replace(f"@done {TOKEN}\n", "")
        self.assertEqual(verdicts(cut), {"entered": "unverified"})

    def test_a_truncated_section_is_not_an_empty_one(self) -> None:
        """An unterminated routing table must not read as "no routes".

        This is the same defect wearing the passing verdict: an empty route
        table IS the proof of a disabled network, so a section that was cut off
        mid-write would otherwise be the strongest possible pass.
        """
        truncated = probe_output().replace("@end route4\n", "")
        self.assertEqual(verdicts(truncated)["network"], "unverified")

    def test_the_host_marker_being_visible_refutes_entry(self) -> None:
        self.assertEqual(verdicts(probe_output(marker="visible"))["entered"], "refuted")

    def test_loopback_only_routes_prove_a_disabled_network(self) -> None:
        self.assertEqual(verdicts(probe_output())["network"], "proven")

    def test_a_route_off_loopback_refutes_a_disabled_network(self) -> None:
        report = probe_output(
            route4=[ROUTE4_HEADER, "eth0\t00000000\t010011AC\t0003\t0\t0\t0"]
        )
        self.assertEqual(verdicts(report)["network"], "refuted")

    def test_a_tunnel_device_without_a_route_is_not_a_network(self) -> None:
        """Measured trap: `--network none` still carries `tunl0` and friends.

        The interfaces exist and carry no route, so a check that counted
        interfaces would refuse a correctly isolated boundary and teach its
        reader to ignore it.
        """
        self.assertEqual(
            verify_sandbox.routes_off_loopback([ROUTE4_HEADER], ROUTE6_LOOPBACK), []
        )

    def test_a_credential_shaped_variable_refutes_a_minimal_environment(self) -> None:
        report = probe_output(env=["PATH=/usr/bin", "OPENAI_API_KEY=redacted"])
        self.assertEqual(verdicts(report)["credentials"], "refuted")

    def test_the_credential_check_reports_names_and_never_values(self) -> None:
        report = probe_output(env=["PATH=/usr/bin", "TRAIGENT_API_KEY=sk-secret-value"])
        properties = verify_sandbox.evaluate(report, TOKEN, MARKER, [])
        evidence = next(
            item.evidence for item in properties if item.name == "credentials"
        )
        self.assertIn("TRAIGENT_API_KEY", evidence)
        self.assertNotIn("sk-secret-value", evidence)

    def test_uid_zero_refutes_an_unprivileged_identity(self) -> None:
        self.assertEqual(verdicts(probe_output(uid="0"))["identity"], "refuted")

    def test_an_ordinary_host_uid_does_not_prove_containment_alone(self) -> None:
        """Measured: running on this host reported uid 1000, not 0.

        So `identity` passing is worth almost nothing by itself, and this case
        pins the reason the check does not stop there - the host fallthrough is
        caught by `entered`, and this is the property it would sail past.
        """
        result = verdicts(probe_output(uid="1000", marker="visible"))
        self.assertEqual(result["identity"], "proven")
        self.assertEqual(result["entered"], "refuted")

    def test_the_echoed_command_does_not_reprint_a_key_it_refused(self) -> None:
        """Found by running the check, not by reading it.

        The report names the boundary it measured, and the commonest way to
        fail `credentials` is to put the key on that command line - so the
        report printed the secret one line above a finding that said no value
        was read.
        """
        shown = verify_sandbox.redacted_command(
            ["docker", "run", "-e", "OPENAI_API_KEY=sk-real-value", "image:tag"]
        )
        self.assertIn("OPENAI_API_KEY=<redacted>", shown)
        self.assertNotIn("sk-real-value", " ".join(shown))
        self.assertIn("image:tag", shown)

    def test_redaction_keeps_the_ordinary_arguments_readable(self) -> None:
        """A report nobody can read is not a safer report."""
        self.assertEqual(
            verify_sandbox.redacted_command(["--user", "65534:65534", "PATH=/usr/bin"]),
            ["--user", "65534:65534", "PATH=/usr/bin"],
        )

    def test_a_write_that_reached_the_host_outranks_what_the_probe_said(self) -> None:
        """The probe claims it was refused; the host says otherwise.

        The host is believed. A boundary that reports its own compliance is the
        thing being checked, so a verdict that trusted the report would be
        checking nothing.
        """
        landed = [Path("/tmp/landed-write-probe")]
        self.assertEqual(
            verdicts(probe_output(), landed=landed)["filesystem"], "refuted"
        )


class ExitStatusTests(unittest.TestCase):
    """What the customer's shell sees. Only 0 may clear an evaluator to run."""

    def test_an_absent_runtime_exits_two_and_says_nothing_was_established(self) -> None:
        result = run_script("--", "nosuchcontainerruntime", "run")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not on PATH", result.stdout)
        self.assertIn("nothing about containment was established", result.stdout)

    def test_a_command_that_ignores_the_probe_exits_two(self) -> None:
        """`true` exits 0 having run nothing. The verifier must not agree."""
        result = run_script("--", "true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("did not run the probe", result.stdout)

    def test_running_on_the_host_is_refuted_and_exits_one(self) -> None:
        """`env` is the no-op wrapper: it execs the probe on this host.

        The command succeeds, the probe runs, and every property that describes
        a boundary is false. This is what a customer gets when they believe
        they have containment and do not.
        """
        result = run_script("--", "env")
        self.assertEqual(result.returncode, 1)
        self.assertIn("entered", result.stdout)
        self.assertIn("Do not run the execution evaluator", result.stdout)

    def test_no_command_is_the_check_breaking_not_an_unproven_boundary(self) -> None:
        result = run_script("--")
        self.assertEqual(result.returncode, 3)

    def test_the_json_report_carries_the_verdicts_and_the_limits(self) -> None:
        result = run_script("--json", "--", "env")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "refuted")
        self.assertTrue(payload["not_established"])
        self.assertEqual(
            {item["name"] for item in payload["properties"]},
            {"entered", "network", "credentials", "filesystem", "identity"},
        )

    def test_the_write_probe_is_not_left_in_the_working_directory(self) -> None:
        """The check may not leave its own litter in the customer's project."""
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            run_script("--", "env", cwd=work)
            self.assertEqual(sorted(path.name for path in work.iterdir()), [])


@unittest.skipIf(IMAGE is None, NO_RUNTIME)
class RealBoundaryTests(unittest.TestCase):
    """Driven against an actual OS boundary, because a recipe is not evidence."""

    def boundary(self, *extra: str) -> list[str]:
        return [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            *extra,
            str(IMAGE),
        ]

    def test_a_compliant_boundary_proves_every_property(self) -> None:
        result = run_script("--json", "--", *self.boundary())
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "proven", payload["properties"])
        self.assertEqual(result.returncode, 0)

    def test_a_boundary_with_a_network_is_refuted(self) -> None:
        command = [
            item for item in self.boundary() if item not in {"--network", "none"}
        ]
        result = run_script("--json", "--", *command)
        payload = json.loads(result.stdout)
        network = next(
            item for item in payload["properties"] if item["name"] == "network"
        )
        self.assertEqual(network["verdict"], "refuted")
        self.assertEqual(result.returncode, 1)

    def test_a_boundary_that_hands_in_a_key_is_refuted(self) -> None:
        result = run_script(
            "--json",
            "--",
            *self.boundary("-e", "OPENAI_API_KEY=not-a-real-key"),
        )
        payload = json.loads(result.stdout)
        credentials = next(
            item for item in payload["properties"] if item["name"] == "credentials"
        )
        self.assertEqual(credentials["verdict"], "refuted")
        self.assertNotIn("not-a-real-key", result.stdout)

    def test_a_writable_host_mount_is_refuted_and_leaves_nothing_behind(self) -> None:
        """Entry is genuine and the boundary still fails, which is the point.

        A container really was entered - `entered` proves it - and the probe's
        write still reached this host. No recipe the customer copies can tell
        them that; only running it can.
        """
        if os.environ.get("TRAIGENT_FIRST_RUN_SKIP_MOUNT_CASE"):
            self.skipTest("bind mounts are unavailable to this daemon")
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            work = Path(directory)
            command = [
                item
                for item in self.boundary("-v", f"{work}:{work}:rw", "-w", str(work))
                if item not in {"--read-only", "--user", "65534:65534"}
            ]
            result = run_script("--json", "--", *command, cwd=work)
            payload = json.loads(result.stdout)
            if payload["properties"][0]["verdict"] == "unverified":
                self.skipTest("this daemon refused the bind mount")
            filesystem = next(
                item for item in payload["properties"] if item["name"] == "filesystem"
            )
            self.assertEqual(filesystem["verdict"], "refuted")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(sorted(path.name for path in work.iterdir()), [])


class EvaluatorExecutionPathTests(unittest.TestCase):
    """Preflight's half: noticing that a boundary is required at all."""

    def sinks(self, source: str) -> list[str]:
        import ast

        return preflight.sinks_in_evaluator(ast.parse(source))

    def test_a_sql_scorer_is_named_as_an_execution_path(self) -> None:
        self.assertIn(
            "execute",
            self.sinks("def s(a, b):\n    cur.execute(b)\n"),
        )

    def test_a_code_scorer_is_named_as_an_execution_path(self) -> None:
        self.assertEqual(
            self.sinks("def s(a, b):\n    exec(b, {})\n"),
            ["exec"],
        )

    def test_a_subprocess_scorer_is_named_as_an_execution_path(self) -> None:
        self.assertEqual(
            self.sinks("import subprocess\ndef s(a, b):\n    subprocess.run([b])\n"),
            ["run"],
        )

    def test_an_ordinary_method_called_run_is_not_a_subprocess(self) -> None:
        """`run` and `call` are ordinary words, so they need their module.

        Without that, every scorer with a `self.run(case)` helper is reported as
        shelling out, and a check that cries wolf on the common shape is one
        its reader learns to skip past.
        """
        self.assertEqual(self.sinks("def s(a, b):\n    self.run(b)\n"), [])

    def test_a_scorer_with_no_sink_is_unchecked_and_never_clean(self) -> None:
        """SKIP, not PASS. One file cannot clear a complete call path."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text("def s(a, b):\n    return float(a == b)\n")
            result = subprocess.run(
                [
                    sys.executable,
                    str(PREFLIGHT),
                    "--evaluator",
                    str(path),
                    "--defer-missing-sdk",
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            records = {item["check"]: item for item in json.loads(result.stdout)}
            self.assertEqual(records["evaluator-execution-path"]["status"], "SKIP")

    def test_an_execution_scorer_warns_and_routes_to_the_boundary_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text("import sqlite3\ndef s(a, b):\n    cur.executescript(b)\n")
            result = subprocess.run(
                [
                    sys.executable,
                    str(PREFLIGHT),
                    "--evaluator",
                    str(path),
                    "--defer-missing-sdk",
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            records = {item["check"]: item for item in json.loads(result.stdout)}
            record = records["evaluator-execution-path"]
            self.assertEqual(record["status"], "WARN")
            self.assertEqual(record["metrics"]["sinks"], ["executescript"])
            self.assertIn("verify_sandbox.py", record["detail"])


if __name__ == "__main__":
    unittest.main()

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


# `/proc/self/status` as a compliant boundary reports it. Only three lines are
# read - the effective capability set, no-new-privileges, and the seccomp mode
# that is reported without ever being refuted on - but the fixture carries the
# neighbours so a parser that finds `CapEff` by prefix rather than by field
# name fails here rather than in a customer's terminal.
STATUS_COMPLIANT = [
    "Name:\tsh",
    "Uid:\t65534\t65534\t65534\t65534",
    "CapInh:\t0000000000000000",
    "CapPrm:\t0000000000000000",
    "CapEff:\t0000000000000000",
    "CapBnd:\t0000000000000000",
    "NoNewPrivs:\t1",
    "Seccomp:\t2",
]
# Measured inside a container on the default bridge: an IPv6 route whose last
# field is a real interface. The IPv4 half of this had a fixture from the
# beginning and the IPv6 half did not, so the IPv6 arm of the route reader was
# the one guard in this file that a mutation left alive.
ROUTE6_OFF_LOOPBACK = [
    "00000000000000000000000000000000 00 "
    + "0" * 32
    + " 00 "
    + "0" * 32
    + "        eth0",
]


def probe_output(**overrides: object) -> str:
    """The report a compliant boundary produces, with one part replaced."""
    parts: dict[str, object] = {
        "token": TOKEN,
        "uid": "65534",
        "marker": "absent",
        "scratch-write": "refused",
        "workdir-write": "refused",
        "home-write": "refused",
        "host-process": "0",
        "route4": [ROUTE4_HEADER],
        "route6": ROUTE6_LOOPBACK,
        "status": STATUS_COMPLIANT,
        "env": ["PATH=/usr/local/bin:/usr/bin", "HOSTNAME=abc123"],
        "done": TOKEN,
    }
    # `home_write=` for `@home-write`, because a keyword argument cannot carry
    # a hyphen. An override that names nothing in the report is a typo, and a
    # typo that silently produced a compliant fixture would be a test asserting
    # the default it meant to replace.
    for key, value in overrides.items():
        field_name = key.replace("_", "-")
        if field_name not in parts:
            raise KeyError(f"{key!r} is not a part of the probe's report")
        parts[field_name] = value
    lines = [
        f"@token {parts['token']}",
        f"@uid {parts['uid']}",
        f"@marker {parts['marker']}",
        f"@scratch-write {parts['scratch-write']}",
        f"@workdir-write {parts['workdir-write']}",
        f"@home-write {parts['home-write']}",
        f"@host-process {parts['host-process']}",
    ]
    for name in ("route4", "route6", "status", "env"):
        section = parts[name]
        if section is None:
            continue
        lines.append(f"@begin {name}")
        lines.extend(section)  # type: ignore[arg-type]
        lines.append(f"@end {name}")
    lines.append(f"@done {parts['done']}")
    return "\n".join(lines) + "\n"


def verdicts(
    output: str,
    landed: list[Path] | None = None,
    unreadable: list[str] | None = None,
) -> dict[str, str]:
    properties = verify_sandbox.evaluate(
        output, TOKEN, MARKER, landed or [], unreadable or []
    )
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
    # The image this repository pins is preferred, and that ordering is
    # load-bearing twice over. Two of the four verdicts below turn on which
    # base is underneath - one boundary property reads the variables the image
    # itself defines - so running them on whatever happened to be cached tests
    # a different thing on every host. And with `alpine:3` preferred, the
    # container cases never once ran on the image the workflow pins, which is
    # how a verdict that fired on that image alone stayed invisible.
    for image in ("python:3.12-slim", "alpine:3", "alpine:latest"):
        present = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if present.returncode != 0:
            continue
        # An image on disk and a daemon that answers `info` are still not a
        # daemon that can START a container, and the difference is not
        # academic: measured here, `docker info` and `docker image inspect`
        # kept answering while every `docker run` hung forever, leaving
        # containers stuck in `Created`. The four cases below would each have
        # waited out their own timeout - twenty minutes of a suite that should
        # have said in one second that this machine cannot drive a boundary.
        #
        # So the last question is asked by doing the thing: start one, briefly.
        try:
            started = subprocess.run(
                ["docker", "run", "--rm", image, "/bin/true"],
                capture_output=True,
                timeout=90,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if started.returncode == 0:
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
                "privilege": "proven",
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
        properties = verify_sandbox.evaluate(report, TOKEN, MARKER, [], [])
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

    def test_a_write_that_reached_this_hosts_home_is_refuted(self) -> None:
        """The contract names two nouns and this used to measure one of them.

        Measured: `-v $HOME:$HOME:rw` passed every property and exited 0, from
        inside which the customer's projects were listable and their `~/.ssh`
        readable. The working directory was elsewhere, so the only write probe
        that could have caught it was pointed somewhere else.
        """
        landed = [Path.home() / ".verify_sandbox_write_probe_abc"]
        self.assertEqual(
            verdicts(probe_output(home_write="ok"), landed=landed)["filesystem"],
            "refuted",
        )

    def test_a_host_path_this_check_could_not_read_back_is_not_a_clean_one(
        self,
    ) -> None:
        """`Path.exists()` raises EACCES rather than answering.

        A boundary that chmods this check's scratch directory to mode 0 used to
        crash it with a message blaming the check rather than the boundary.
        Unknown is not clean, so the verdict is unverified and the reason says
        which path could not be read.
        """
        result = verdicts(
            probe_output(),
            unreadable=["/tmp/verify_sandbox_x/scratch (Permission denied)"],
        )
        self.assertEqual(result["filesystem"], "unverified")

    def test_a_shadowed_path_is_described_rather_than_refuted(self) -> None:
        """A write that succeeded inside with no host file behind it.

        That is a boundary mounting its own filesystem over the path, which is
        compliant - so it is described, not refuted. Refuting it would fail
        every boundary that puts a tmpfs on `/tmp`, and this check must not
        teach people to remove containment to satisfy it.
        """
        result = verdicts(probe_output(**{"scratch-write": "ok"}))
        self.assertEqual(result["filesystem"], "proven")

    def test_an_empty_routing_table_is_not_a_disabled_network(self) -> None:
        """Measured: a container on the default bridge, full internet reachable.

        Only `cat` was unavailable, so `/proc/net/route` came back empty - and
        an empty section used to read as the passing observation. The file
        always carries a header line, which is why emptiness means unread.
        """
        result = verdicts(probe_output(route4=[]))
        self.assertEqual(result["network"], "unverified")

    def test_an_ipv6_route_off_loopback_refutes_a_disabled_network(self) -> None:
        """The IPv4 arm had a fixture from the start; this one did not.

        Deleting the IPv6 arm of the route reader left the suite green, which
        makes it the one guard here that was decoration.
        """
        result = verdicts(probe_output(route6=ROUTE6_OFF_LOOPBACK))
        self.assertEqual(result["network"], "refuted")

    def test_an_empty_environment_is_not_a_minimal_one(self) -> None:
        """A shell reports the variables it sets itself, so zero means unread."""
        result = verdicts(probe_output(env=[]))
        self.assertEqual(result["credentials"], "unverified")

    def test_a_shared_process_namespace_refutes_the_privilege_clause(self) -> None:
        """Measured: `--privileged --pid host` used to exit 0.

        With a non-root user the effective capability set is empty, so identity
        passed and nothing else looked - over a boundary that could see 726
        host processes. This check's own process being visible inside settles
        it without a threshold to tune.
        """
        result = verdicts(probe_output(host_process="2"))
        self.assertEqual(result["privilege"], "refuted")

    def test_one_visible_process_id_is_a_collision_this_cannot_tell_apart(self) -> None:
        """A boundary numbering from 1 can hold an id equal to one of ours.

        Two ids are named for that reason, and seeing exactly one is neither a
        shared namespace nor a clean one. Refuting on it would put a false red
        on the axis where a false red is worst - it teaches a reader to remove
        containment until the complaint stops.
        """
        result = verdicts(probe_output(host_process="1"))
        self.assertEqual(result["privilege"], "unverified")

    def test_a_process_reading_this_cannot_parse_is_not_a_clean_one(self) -> None:
        """Anything but a count of nought, one or two is a reading, not a pass.

        Without this the two arms below simply do not match, no finding is
        recorded, and a probe whose shell arithmetic did not run at all comes
        back proven - the fail-open direction, reached by saying nothing.
        """
        properties = verify_sandbox.evaluate(
            probe_output(host_process="not-a-count"), TOKEN, MARKER, [], []
        )
        privilege = next(item for item in properties if item.name == "privilege")
        self.assertEqual(privilege.verdict, "unverified")
        self.assertIn("host-process", privilege.evidence)

    def test_elevated_capabilities_refute_the_privilege_clause(self) -> None:
        status = [
            line if not line.startswith("CapEff") else "CapEff:\t0000003fffffffff"
            for line in STATUS_COMPLIANT
        ]
        self.assertEqual(verdicts(probe_output(status=status))["privilege"], "refuted")

    def test_a_boundary_that_permits_privilege_escalation_is_refuted(self) -> None:
        """The bullet says "no elevated capabilities OR privilege escalation".

        A setuid program inside a boundary without no-new-privileges can still
        raise its own privileges, capability set or not.
        """
        status = [
            line if not line.startswith("NoNewPrivs") else "NoNewPrivs:\t0"
            for line in STATUS_COMPLIANT
        ]
        self.assertEqual(verdicts(probe_output(status=status))["privilege"], "refuted")

    def test_an_unreadable_process_status_proves_nothing_about_privilege(self) -> None:
        """A boundary with no `/proc` mounted reports nothing, not nothing wrong.

        Asserting only the verdict was not enough and this case proves why:
        deleting the empty-status branch outright left the suite green, because
        a later guard reaches `unverified` too - by a different route and with
        a message that does not tell the reader `/proc` is missing. So the
        evidence is pinned, not just the word.
        """
        properties = verify_sandbox.evaluate(
            probe_output(status=[]), TOKEN, MARKER, [], []
        )
        privilege = next(item for item in properties if item.name == "privilege")
        self.assertEqual(privilege.verdict, "unverified")
        self.assertIn("/proc", privilege.evidence)

    def test_a_boundary_without_a_seccomp_filter_is_reported_not_refuted(self) -> None:
        """A virtual machine legitimately carries none.

        Refusing it would put a false red on the strongest kind of boundary, so
        the mode is read, printed, and never allowed to decide.
        """
        status = [line for line in STATUS_COMPLIANT if not line.startswith("Seccomp")]
        self.assertEqual(verdicts(probe_output(status=status))["privilege"], "proven")

    def test_every_spelling_of_the_environment_flag_is_redacted(self) -> None:
        """Four accepted spellings of one flag; the name test knew one.

        Measured: `-eNAME=...` and `--env=NAME=...` are ordinary and both
        printed the value in full. Redaction keys on the flag now, so what the
        variable is called stops mattering.
        """
        for argument in (
            ["-e", "OPENAI_API_KEY=sk-FAKE-VALUE"],
            ["-eOPENAI_API_KEY=sk-FAKE-VALUE"],
            ["--env", "OPENAI_API_KEY=sk-FAKE-VALUE"],
            ["--env=OPENAI_API_KEY=sk-FAKE-VALUE"],
        ):
            with self.subTest(spelling=argument[0]):
                shown = verify_sandbox.redacted_command(
                    ["docker", "run", *argument, "image:tag"]
                )
                self.assertNotIn("sk-FAKE-VALUE", " ".join(shown))
                self.assertIn("image:tag", shown)

    def test_a_value_is_redacted_however_the_variable_is_named(self) -> None:
        """The reason redaction stopped asking what the name looks like.

        A connection string carries its password inline under a name no secret
        word appears in, and it is the likeliest variable in this script's own
        headline use case.
        """
        shown = verify_sandbox.redacted_command(
            ["docker", "run", "-e", "DATABASE_URL=postgres://u:pw-FAKE@db/x", "img"]
        )
        self.assertNotIn("pw-FAKE", " ".join(shown))

    def test_a_flag_that_is_not_an_environment_flag_stays_readable(self) -> None:
        """Position-based redaction must not blank the rest of the command."""
        self.assertEqual(
            verify_sandbox.redacted_command(
                ["--security-opt", "seccomp=/etc/p.json", "--mount", "type=bind,src=/a"]
            ),
            ["--security-opt", "seccomp=/etc/p.json", "--mount", "type=bind,src=/a"],
        )


class CredentialNameShapeTests(unittest.TestCase):
    """Which variable names read as secrets. Measured against real spellings."""

    def test_the_names_that_used_to_slip_through_are_named(self) -> None:
        """Each of these sat inside a boundary this check called clean."""
        for name in (
            "GITHUB_PAT",
            "AUTHORIZATION",
            "SSH_AUTH_SOCK",
            "DATABASE_URL",
            "REDIS_URI",
            "SESSION_COOKIE",
            "MY_PASSPHRASE",
            "KUBECONFIG",
        ):
            with self.subTest(name=name):
                self.assertTrue(verify_sandbox.secret_shaped(name))

    def test_an_ordinary_name_that_contains_a_secret_word_is_not_one(self) -> None:
        """`PAT` is inside `PATH`, which every boundary carries.

        Matching by substring would refuse every boundary on earth, which is
        why the comparison is by underscore-separated segment.
        """
        for name in (
            "PATH",
            "PATTERN",
            "API_URL",
            "BASE_URI",
            "PYTHON_VERSION",
            # The desktop-session family, every one of which this reported on
            # a real host until `SESSION` came back out of the word list.
            "XDG_SESSION_TYPE",
            "DESKTOP_SESSION",
            "DBUS_SESSION_BUS_ADDRESS",
            "SESSION_MANAGER",
        ):
            with self.subTest(name=name):
                self.assertFalse(verify_sandbox.secret_shaped(name))

    def test_the_one_public_name_let_through_is_exactly_one_name(self) -> None:
        """`GPG_KEY` on the official language images is a public fingerprint.

        Without the exception the example in this script's own `--help` fails
        its own check on the image this repository pins, and the reader cannot
        fix it: no run flag removes a variable an image baked in. The exception
        is one exact name, so a longer spelling is still reported.
        """
        self.assertFalse(verify_sandbox.secret_shaped("GPG_KEY"))
        self.assertTrue(verify_sandbox.secret_shaped("GPG_PRIVATE_KEY"))
        self.assertTrue(verify_sandbox.secret_shaped("MY_GPG_KEY"))


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
            {
                "entered",
                "network",
                "credentials",
                "filesystem",
                "privilege",
                "identity",
            },
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
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            work = Path(directory)
            # `TemporaryDirectory` creates mode 0700 owned by this user. The
            # command below strips `--user` so the container runs as root, but
            # keeps `--cap-drop ALL`, which takes CAP_DAC_OVERRIDE with it - so
            # root-in-container cannot write into another uid's 0700 directory,
            # the write is refused for a reason that has nothing to do with
            # containment, and the case passes while proving nothing. It did
            # exactly that on one vendor's daemon and failed on a stock one.
            work.chmod(0o777)
            # Whether this daemon can bind-mount at all, asked of the daemon
            # rather than inferred from the verdict of the thing under test. An
            # `unverified` first property has two causes - a daemon that
            # refused the mount, and a regression that stopped the probe
            # running - and skipping on it swallowed the second along with the
            # first.
            usable = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{work}:{work}:rw",
                    IMAGE,
                    "/bin/true",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if usable.returncode != 0:
                self.skipTest(
                    "this daemon refused a bind mount of the test directory: "
                    + (usable.stderr or "").strip().splitlines()[-1:][0]
                )
            command = [
                item
                for item in self.boundary("-v", f"{work}:{work}:rw", "-w", str(work))
                if item not in {"--read-only", "--user", "65534:65534"}
            ]
            result = run_script("--json", "--", *command, cwd=work)
            payload = json.loads(result.stdout)
            entered = next(
                item for item in payload["properties"] if item["name"] == "entered"
            )
            self.assertEqual(entered["verdict"], "proven")
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

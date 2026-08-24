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
    "CapBnd:\t0000000000000000",  # read, and refuted on - see the case below
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
        # A compliant boundary has neither directory at its own absolute path,
        # and neither marker turns up under any other name inside it either.
        "workdir-reach": "no-such-directory",
        "home-reach": "no-such-directory",
        "workdir-elsewhere": "absent",
        "home-elsewhere": "absent",
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
        f"@workdir-reach {parts['workdir-reach']}",
        f"@home-reach {parts['home-reach']}",
        f"@workdir-elsewhere {parts['workdir-elsewhere']}",
        f"@home-elsewhere {parts['home-elsewhere']}",
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


def refusal(stderr: str | None) -> str:
    """The line of a runtime's refusal that says why, not where to read about it.

    Taking the last line printed `Run 'docker run --help' for more information`
    while the reason - `The path /tmp is not shared from the host` - sat two
    lines above it. Taking the first is no better in general, so the pointers
    are skipped and the first remaining line wins.
    """
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    useful = [
        line
        for line in lines
        if not line.startswith(("Run '", "See '", "Usage:", "usage:"))
    ]
    return next(iter(useful or lines), "no error output")


def run_script(
    *arguments: str,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(cwd) if cwd else None,
        env={**os.environ, **(environment or {})} if environment else None,
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
        # Named, so a timeout has something to clean up. A timeout kills the
        # client and not the container, so `--rm` never fires and the container
        # sits in `Created` - which is what a wedged daemon accumulates, so the
        # probe for that condition was feeding it.
        named = f"verify_sandbox_probe_{os.getpid()}"
        try:
            started = subprocess.run(
                ["docker", "run", "--rm", "--name", named, image, "/bin/true"],
                capture_output=True,
                timeout=90,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            subprocess.run(
                ["docker", "rm", "-f", named],
                capture_output=True,
                timeout=60,
                check=False,
            )
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

        Only `entered` is reported, because the other five would each say "the
        probe did not tell me" - five problems on the screen where there is one.
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

    def test_no_reading_for_the_host_marker_establishes_nothing(self) -> None:
        """The arm reached when the probe ran but said nothing about the marker.

        Turning it into `proven` cleared all six properties and left the whole
        suite green, because no case had ever produced that shape.
        """
        without = "\n".join(
            line
            for line in probe_output().splitlines()
            if not line.startswith("@marker")
        )
        self.assertEqual(verdicts(without), {"entered": "unverified"})

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
        """A report nobody can read is not a safer report.

        `PATH=/usr/bin` is blanked now and that is the point of the change: the
        report keeps what identifies the boundary - flags, their non-variable
        operands, the image - and stops trying to decide which `NAME=VALUE` is
        safe to print, which is what cost three rounds.
        """
        self.assertEqual(
            verify_sandbox.redacted_command(["--user", "65534:65534", "alpine:3"]),
            ["--user", "65534:65534", "alpine:3"],
        )
        self.assertEqual(
            verify_sandbox.redacted_command(["PATH=/usr/bin"]), ["PATH=<redacted>"]
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

    def test_a_reachable_home_is_refuted_whatever_the_write_probe_said(self) -> None:
        """The case that made three write probes prove nothing.

        Measured: the customer's whole home mounted read-write, entered as the
        uid this script's own example recommends, was proven clean on all three
        write probes - because a foreign uid cannot create a file at the top of
        an ordinary home either way - while the same boundary read a `0644` file
        out of it. A marker only this run knows the name of settles it without
        consulting a permission bit.
        """
        result = verdicts(probe_output(home_reach="visible"))
        self.assertEqual(result["filesystem"], "refuted")

    def test_a_reachable_home_is_refuted_even_when_it_is_read_only(self) -> None:
        """The contract admits tests and fixtures read-only. A home is neither.

        Model-written code that can read the home can read the customer's keys
        whether or not it can write, so read-only does not settle this one.
        """
        result = verdicts(probe_output(home_reach="visible", home_write="refused"))
        self.assertEqual(result["filesystem"], "refuted")

    def test_a_writable_project_mount_is_refuted(self) -> None:
        """Reachable AND written to. Reachability is what makes the write mean
        something: until the marker is visible, "refused" could always have
        been a permission bit rather than the boundary."""
        result = verdicts(
            probe_output(**{"workdir-reach": "visible", "workdir-write": "ok"})
        )
        self.assertEqual(result["filesystem"], "refuted")

    def test_a_project_mounted_read_only_is_what_the_contract_admits(self) -> None:
        """And must not be refused, or the check refuses a compliant boundary.

        "Mount only required tests and fixtures read-only" is the contract's own
        sentence, and for most projects those files live in the project
        directory.
        """
        result = verdicts(probe_output(**{"workdir-reach": "visible"}))
        self.assertEqual(result["filesystem"], "proven")

    def test_a_directory_this_identity_cannot_enter_is_not_a_hazard_to_it(self) -> None:
        """Present inside, unenterable by the probe: reported, not refused.

        Failing closed here refused compliant boundaries wholesale - `/root` is
        0700 in the pinned image, so anyone invoking as root got exit 2, and so
        did any home this uid cannot traverse. What is mounted there was not
        identified, which the evidence says and the unreachable list repeats.
        """
        properties = verify_sandbox.evaluate(
            probe_output(home_reach="opaque"), TOKEN, MARKER, [], []
        )
        filesystem = next(item for item in properties if item.name == "filesystem")
        self.assertEqual(filesystem.verdict, "proven")
        self.assertIn("cannot enter it", filesystem.evidence)

    def test_a_marker_found_under_another_name_is_the_same_directory(self) -> None:
        """The spelling three rounds of this property could not see.

        `-v "$HOME:/hosthome:rw"` and `-v "$PWD:/work:rw" -w /work` hand the
        boundary the same directory under a path this check was never told, so
        asking only about its own absolute path answered a question nobody had.
        A file name nothing else is using does not care where it was mounted.
        """
        self.assertEqual(
            verdicts(probe_output(home_elsewhere="home"))["filesystem"], "refuted"
        )
        self.assertEqual(
            verdicts(
                probe_output(**{"workdir-elsewhere": "cwd", "workdir-write": "ok"})
            )["filesystem"],
            "refuted",
        )

    def test_a_missing_reachability_reading_is_not_a_clean_one(self) -> None:
        without = "\n".join(
            line
            for line in probe_output().splitlines()
            if not line.startswith("@home-reach")
        )
        properties = verify_sandbox.evaluate(without, TOKEN, MARKER, [], [])
        filesystem = next(item for item in properties if item.name == "filesystem")
        self.assertEqual(filesystem.verdict, "unverified")

    def test_the_home_probe_is_read_and_not_merely_sent(self) -> None:
        """Deleting `home-write` from the read set left the whole suite green.

        The home write LANDING was pinned, through `landed`; the home write
        being asked about at all was not, so the probe could have gone on
        reporting it into nothing. A report missing that one line has to be
        unverified, and the message has to name it.
        """
        without_home = "\n".join(
            line
            for line in probe_output().splitlines()
            if not line.startswith("@home-write")
        )
        properties = verify_sandbox.evaluate(without_home, TOKEN, MARKER, [], [])
        filesystem = next(item for item in properties if item.name == "filesystem")
        self.assertEqual(filesystem.verdict, "unverified")
        self.assertIn("home-write", filesystem.evidence)

    def test_nothing_this_check_planted_outlives_it(self) -> None:
        """Four files are written outside the scratch directory now - two write
        probes and two markers, in the working directory and the home.

        The existing case reads only the working directory, so removing either
        home unlink left the suite green while leaving real files in the
        customer's home. Both trees are read here, before and after.
        """
        # A home and a working directory of its own. The first version read the
        # real ones, which made the case a race: any other run of this check on
        # the machine - and there are several during a suite - could put a file
        # there inside the window and fail a case about cleanup for a reason
        # that had nothing to do with cleanup.
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            work = Path(directory) / "work"
            home.mkdir()
            work.mkdir()
            result = run_script("--", "true", cwd=work, environment={"HOME": str(home)})
            self.assertEqual(result.returncode, 2)
            self.assertEqual(sorted(path.name for path in home.iterdir()), [])
            self.assertEqual(sorted(path.name for path in work.iterdir()), [])

    def test_the_home_is_named_by_where_it_is_not_by_how_it_was_reached(
        self,
    ) -> None:
        """A home reached through a symlink is mounted at its physical path.

        Comparing the logical one against it cleared a read-write mount of
        exactly that home, so the probe paths are built from the resolved
        directory. `env` is the boundary that is not one, so the write lands and
        the refutation names the path it landed at.
        """
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real-home"
            real.mkdir()
            link = Path(directory) / "reached-by-link"
            link.symlink_to(real)
            result = run_script("--json", "--", "env", environment={"HOME": str(link)})
            payload = json.loads(result.stdout)
            filesystem = next(
                item for item in payload["properties"] if item["name"] == "filesystem"
            )
            self.assertIn(str(real), filesystem["evidence"])
            self.assertNotIn(str(link), filesystem["evidence"])

    def test_the_scratch_it_actually_uses_is_outside_those_trees(self) -> None:
        """The helper being right is not the same as the helper being called.

        Replacing `dir=scratch_root()` with `dir=None` at the one call site left
        the suite green, because the only case pointed at the function rather
        than at the run. `env` reports the marker's real path, which is the
        scratch directory this run actually made.
        """
        inside = Path.cwd() / "tmp-for-the-call-site-case"
        inside.mkdir(exist_ok=True)
        try:
            result = run_script(
                "--json", "--", "env", environment={"TMPDIR": str(inside)}
            )
            payload = json.loads(result.stdout)
            entered = next(
                item for item in payload["properties"] if item["name"] == "entered"
            )
            self.assertNotIn(str(inside), entered["evidence"])
        finally:
            for leftover in inside.iterdir():  # pragma: no cover - only on failure
                shutil.rmtree(leftover, ignore_errors=True)
            inside.rmdir()

    def test_the_scratch_directory_is_not_inside_the_trees_being_probed(self) -> None:
        """`entered` rests on a marker, and the marker must not sit in a tree the
        customer legitimately mounts.

        Measured: `TMPDIR=$PWD/tmp` with the project mounted read-only produced
        `REFUTED entered: the probe could see ... so it ran on this host` - an
        affirmatively false diagnosis of the property everything else rests on.
        `TMPDIR` inside a workspace is ordinary in CI runners and build tools.
        """
        inside = Path.cwd() / "tmp-for-the-scratch-root-case"
        inside.mkdir(exist_ok=True)
        # `tempfile.tempdir`, not `TMPDIR`: `gettempdir()` caches its answer on
        # first use, so setting the variable inside a process that has already
        # made a temporary file changes nothing - and the first version of this
        # case passed for that reason rather than for the right one.
        previous = tempfile.tempdir
        tempfile.tempdir = str(inside)
        try:
            chosen = verify_sandbox.scratch_root()
        finally:
            tempfile.tempdir = previous
            inside.rmdir()
        self.assertIsNotNone(chosen)
        self.assertFalse(str(chosen).startswith(str(Path.cwd())))

    def test_disposal_survives_a_locked_scratch_directory(self) -> None:
        """`rmtree(ignore_errors=True)` cannot remove a mode-0 directory.

        It fails silently and leaves the directory in the customer's `/tmp` -
        the one path this check created itself. Nothing referenced `dispose`
        before this case, so the chmod that fixes it was unpinned.
        """
        scratch = Path(tempfile.mkdtemp(prefix="verify_sandbox_disposal_"))
        (scratch / "inside").write_text("x")
        scratch.chmod(0o000)
        try:
            verify_sandbox.dispose(scratch)
            # Read BEFORE the cleanup below, which would otherwise remove the
            # very thing being asserted about - the first version of this case
            # passed against a `dispose` that did nothing at all.
            survived = scratch.exists()
        finally:
            if scratch.exists():  # pragma: no cover - only on a failing run
                scratch.chmod(0o700)
                shutil.rmtree(scratch, ignore_errors=True)
        self.assertFalse(survived)

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

    def test_one_path_reached_by_two_probes_is_named_once(self) -> None:
        """The working directory can BE the home directory."""
        same = Path("/tmp/probe-in-both-roles")
        evidence = verify_sandbox.filesystem_property(
            probe_output(), [same, same], []
        ).evidence
        self.assertEqual(evidence.count(str(same)), 1)

    def test_a_shadowed_path_is_described_rather_than_refuted(self) -> None:
        """A write that succeeded inside with no host file behind it.

        That is a boundary mounting its own filesystem over the path, which is
        compliant - so it is described, not refuted. Refuting it would fail
        every boundary that puts a tmpfs on `/tmp`, and this check must not
        teach people to remove containment to satisfy it.
        """
        properties = verify_sandbox.evaluate(
            probe_output(**{"scratch-write": "ok"}), TOKEN, MARKER, [], []
        )
        filesystem = next(item for item in properties if item.name == "filesystem")
        self.assertEqual(filesystem.verdict, "proven")
        # The blanket clean branch is `proven` too, so asserting the word alone
        # let both `if shadowed:` and the scratch probe itself be deleted with
        # the suite still green. This sentence only the shadowed arm writes.
        self.assertIn("The probe did create a file at", filesystem.evidence)

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

    def test_one_visible_process_id_is_the_ordinary_shape_not_a_finding(self) -> None:
        """This check runs as somebody's child, and that parent is often pid 1.

        In a container-in-container CI runner or a devcontainer it always is,
        and pid 1 exists inside any boundary with its own namespace - so
        exactly one id is visible on a perfectly compliant setup. Failing
        closed on it refused the shipped example outright at exit 2.
        """
        self.assertEqual(
            verdicts(probe_output(host_process="1"))["privilege"], "proven"
        )

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

    def test_a_boundary_that_permits_privilege_escalation_is_not_cleared(self) -> None:
        """Reported, and never cleared - but not refuted either.

        A setuid program inside a boundary without no-new-privileges can still
        raise its privileges, so this must never reach exit 0. It must also not
        say "your boundary is defective" to a virtual-machine guest, where an
        ordinary process looks exactly like this. Exit 1 and exit 2 route the
        same way, so the honest tier costs nothing that matters.
        """
        status = [
            line if not line.startswith("NoNewPrivs") else "NoNewPrivs:\t0"
            for line in STATUS_COMPLIANT
        ]
        result = verdicts(probe_output(status=status))["privilege"]
        self.assertEqual(result, "unverified")
        self.assertNotEqual(result, "proven")

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

    def test_an_available_capability_refutes_even_when_none_is_held(self) -> None:
        """The reading `--user` does not empty out.

        `CapEff` is empty for any non-root process, which is what the contract
        asks for - so keying the property on it meant the unprivileged identity
        the contract requires was also what blinded the check. Measured:
        `--privileged --user 65534:65534` reported an empty effective set and
        cleared every property, over a boundary whose bounding set was
        `000001ffffffffff`.
        """
        status = [
            line if not line.startswith("CapBnd") else "CapBnd:\t000001ffffffffff"
            for line in STATUS_COMPLIANT
        ]
        self.assertEqual(
            verdicts(probe_output(status=status))["privilege"], "unverified"
        )

    def test_an_unread_bounding_set_proves_nothing(self) -> None:
        status = [line for line in STATUS_COMPLIANT if not line.startswith("CapBnd")]
        self.assertEqual(
            verdicts(probe_output(status=status))["privilege"], "unverified"
        )

    def test_not_seeing_this_checks_processes_is_never_offered_as_proof(self) -> None:
        """A daemon on another kernel cannot show them, so absence says nothing.

        Measured on one machine with two daemons: the same `--pid host` command
        was refuted by the engine sharing this kernel and proven by the
        virtual-machine-backed one, where this check's process ids do not exist
        at all. The refutation is kept; the positive claim is not made.
        """
        properties = verify_sandbox.evaluate(probe_output(), TOKEN, MARKER, [], [])
        privilege = next(item for item in properties if item.name == "privilege")
        self.assertEqual(privilege.verdict, "proven")
        self.assertIn("not seeing them proves nothing", privilege.evidence)
        self.assertTrue(
            any("process namespace" in item for item in verify_sandbox.NOT_ESTABLISHED)
        )

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
            # Clustered, because short flags cluster and the `e` need not lead.
            ["-ieOPENAI_API_KEY=sk-FAKE-VALUE"],
            # And the cluster can END at the `e`, which puts the operand in the
            # next argument - the spelling the attached-form fix missed.
            ["-ie", "OPENAI_API_KEY=sk-FAKE-VALUE"],
        ):
            with self.subTest(spelling=argument[0]):
                shown = verify_sandbox.redacted_command(
                    ["docker", "run", *argument, "image:tag"]
                )
                self.assertNotIn("sk-FAKE-VALUE", " ".join(shown))
                self.assertIn("image:tag", shown)

    def test_a_detached_cluster_operand_is_blanked(self) -> None:
        """`-ie CONFIG=...` - measured leaking, under a name no rule calls
        secret-shaped, so only the default-blank fallback can catch it."""
        shown = verify_sandbox.redacted_command(
            ["docker", "run", "-ie", "CONFIG=FAKEVAL-DETACHED", "img"]
        )
        self.assertIn("CONFIG=<redacted>", shown)
        self.assertNotIn("FAKEVAL-DETACHED", " ".join(shown))

    def test_the_operand_is_blanked_by_position_not_by_what_it_is_called(self) -> None:
        """The name test alone leaves this whole round unpinned.

        Every other redaction case here uses a name the legacy name-matcher
        already catches, so deleting the position branch outright left the
        suite green. A name no rule would ever call secret-shaped is the only
        thing that can tell the two mechanisms apart.
        """
        shown = verify_sandbox.redacted_command(
            ["docker", "run", "-e", "RUN_PROFILE=FAKEVAL-POSITION", "img"]
        )
        self.assertIn("RUN_PROFILE=<redacted>", shown)
        self.assertNotIn("FAKEVAL-POSITION", " ".join(shown))
        self.assertFalse(verify_sandbox.secret_shaped("RUN_PROFILE"))

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

    def test_a_flag_that_describes_containment_stays_readable(self) -> None:
        """The report exists so the reader knows which boundary was measured."""
        self.assertEqual(
            verify_sandbox.redacted_command(
                ["--security-opt", "seccomp=/etc/p.json", "--mount", "type=bind,src=/a"]
            ),
            ["--security-opt", "seccomp=/etc/p.json", "--mount", "type=bind,src=/a"],
        )

    def test_a_flag_that_carries_arbitrary_text_does_not(self) -> None:
        """Each of these printed a planted value in full.

        `--log-opt splunk-token=` is a documented flag whose operand IS a token,
        and a hyphen in the key was enough to walk it past a rule that only knew
        a variable's shape. What decides is the flag in front of it, not what
        the key looks like.
        """
        for flag, operand in (
            ("--log-opt", "splunk-token=FAKE-TOKEN-VALUE"),
            ("--label", "OPENAI_TESTKEY=FAKE-LABEL-VALUE"),
            ("--annotation", "token=FAKE-ANNOTATION-VALUE"),
            ("--health-cmd", "PGPASSWORD=FAKE-HEALTH-VALUE pg_isready"),
        ):
            with self.subTest(flag=flag):
                shown = verify_sandbox.redacted_command([flag, operand])
                self.assertNotIn("FAKE-", " ".join(shown).replace("<redacted>", ""))

    def test_blanking_a_value_does_not_delete_the_command_after_it(self) -> None:
        """A report that erases what it was measuring is not the safer report.

        `sh -c 'PYTHONPATH=/app exec ./run.sh'` rendered as the blanked variable
        alone, with the script it runs gone.
        """
        shown = verify_sandbox.redacted_command(
            ["sh", "-c", "PYTHONPATH=/app exec ./run.sh"]
        )
        self.assertIn("PYTHONPATH=<redacted> exec ./run.sh", shown)


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
            "SENTRY_DSN",
            # No separator anywhere in these, so no segment rule can see the
            # word inside them.
            "PGPASSWORD",
            "SSHPASS",
            "MYSQL_PWD",
            "PGPASSFILE",
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
            # `run-safety.md` tells the customer to set this one, and refusing
            # the boundary that obeyed it put two shipped documents in direct
            # contradiction.
            "TRAIGENT_OFFLINE_MODE",
            "TRAIGENT_RUN_COST_LIMIT",
            "JWT_ISSUER",
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

    def property_of(self, payload: dict, name: str) -> dict:
        """One named property, or a failure that says what came back instead.

        `next(item for item in ... if ...)` raises a bare `StopIteration` here,
        and the shape that triggers it is a legitimate one: when no boundary is
        entered, `evaluate` deliberately returns ONLY `entered`. Observed once
        on a daemon that had stopped starting containers - the case died with a
        traceback naming neither the property nor the report.
        """
        found = {item["name"]: item for item in payload["properties"]}
        self.assertIn(name, found, f"report carried only {sorted(found)}: {payload}")
        return found[name]

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
        network = self.property_of(payload, "network")
        self.assertEqual(network["verdict"], "refuted")
        self.assertEqual(result.returncode, 1)

    def test_a_boundary_that_hands_in_a_key_is_refuted(self) -> None:
        result = run_script(
            "--json",
            "--",
            *self.boundary("-e", "OPENAI_API_KEY=not-a-real-key"),
        )
        payload = json.loads(result.stdout)
        credentials = self.property_of(payload, "credentials")
        self.assertEqual(credentials["verdict"], "refuted")
        self.assertNotIn("not-a-real-key", result.stdout)

    def test_a_mounted_host_directory_is_refuted_under_a_foreign_uid(self) -> None:
        """The case that made `entered` a permission bit rather than a boundary.

        `mkdtemp` creates mode 0700 owned by the caller, so a boundary running
        as any other uid could not traverse it - and the marker then read as
        absent, and the scratch write as refused, no matter what was mounted.
        Measured before the fix: this exact command, with `--user 65534:65534`,
        proved every property and exited 0 while the host's temporary directory
        was mounted read-write at its own absolute path. The uid in
        `boundary()` is the one the script's own `--help` recommends, which is
        what made it worth a case of its own rather than a line in another.
        """
        scratch_root = Path(tempfile.gettempdir())
        usable = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{scratch_root}:{scratch_root}:rw",
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
                "this daemon refused to mount the temporary directory: "
                + refusal(usable.stderr)
            )
        result = run_script(
            "--json",
            "--",
            *self.boundary("-v", f"{scratch_root}:{scratch_root}:rw"),
        )
        payload = json.loads(result.stdout)
        self.assertEqual(self.property_of(payload, "entered")["verdict"], "refuted")
        self.assertEqual(result.returncode, 1)

    def test_a_read_only_own_path_mount_is_seen_as_the_unprivileged_uid(self) -> None:
        """The `reach()` helper, executed, as the identity the example names.

        Every other case that reaches the working directory strips `--user` and
        chmods the fixture, so the refutation arrives at the `landed` branch and
        the reachability arms are never consulted - three one-line mutations of
        the shell helper left the whole suite green while flipping real
        containers to exit 0. This one keeps the recommended uid, mounts
        read-only so nothing can land, and asserts the sentence `visible`
        produces.
        """
        result = run_script(
            "--json",
            "--",
            *self.boundary("-v", f"{Path.cwd()}:{Path.cwd()}:ro"),
        )
        payload = json.loads(result.stdout)
        filesystem = self.property_of(payload, "filesystem")
        # `assertIn("reachable inside the boundary")` was true of BOTH proven
        # branches - one says the directory is, the other says none of them is -
        # so five mutations of the shell helper passed under it. The opening
        # words are what only the reached branch can produce.
        self.assertTrue(
            filesystem["evidence"].startswith("the working directory is reachable"),
            filesystem["evidence"],
        )
        self.assertEqual(filesystem["verdict"], "proven")

    def test_a_directory_mounted_under_another_name_is_still_found(self) -> None:
        """The spelling that cleared at exit 0 for three rounds.

        `-v "$PWD:/work:rw" -w /work` is the same directory under a path this
        check was never told, and asking only about its own absolute path
        answered a question nobody had.
        """
        result = run_script(
            "--json",
            "--",
            *self.boundary("-v", f"{Path.cwd()}:/work:ro", "-w", "/work"),
        )
        payload = json.loads(result.stdout)
        filesystem = self.property_of(payload, "filesystem")
        self.assertTrue(
            filesystem["evidence"].startswith("the working directory is reachable"),
            filesystem["evidence"],
        )

    def test_a_directory_it_cannot_enter_is_told_apart_from_one_that_is_absent(
        self,
    ) -> None:
        """The reading no fixture can stand in for, exercised for real.

        "The directory is not there" and "the directory is there and this
        identity may not enter it" are different facts, and swapping the two
        arms - or testing for existence where the helper tests for traversal -
        left the suite green because nothing ever produced the second one. A
        mode-0700 directory mounted over the working directory's own path, read
        as the unprivileged uid, is that shape.
        """
        with tempfile.TemporaryDirectory() as directory:
            shut = Path(directory) / "shut"
            shut.mkdir(mode=0o700)
            result = run_script(
                "--json",
                "--",
                *self.boundary("-v", f"{shut}:{Path.cwd()}:ro", "-w", "/"),
            )
            payload = json.loads(result.stdout)
            filesystem = self.property_of(payload, "filesystem")
            self.assertIn("cannot enter it", filesystem["evidence"])
            self.assertEqual(filesystem["verdict"], "proven")

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
                # `[-1:][0]` on an empty list is an IndexError, and a daemon
                # that refuses with a non-zero exit and no stderr is exactly
                # what reaches here - the crash would land inside the code
                # added to replace a skip.
                self.skipTest(
                    "this daemon refused a bind mount of the test directory: "
                    + refusal(usable.stderr)
                )
            command = [
                item
                for item in self.boundary("-v", f"{work}:{work}:rw", "-w", str(work))
                if item not in {"--read-only", "--user", "65534:65534"}
            ]
            result = run_script("--json", "--", *command, cwd=work)
            payload = json.loads(result.stdout)
            entered = self.property_of(payload, "entered")
            self.assertEqual(entered["verdict"], "proven")
            filesystem = self.property_of(payload, "filesystem")
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

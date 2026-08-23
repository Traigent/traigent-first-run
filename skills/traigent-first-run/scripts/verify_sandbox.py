#!/usr/bin/env python3
"""Prove that a declared boundary enforces the execution-evaluator contract.

`references/run-safety.md` requires an OS-enforced boundary before any evaluator
executes model-written code or SQL, and says in the same breath that a virtual
environment, stripped builtins, removed keys, proxy blackholing, an ordinary
subprocess, or a timeout alone is not one. Until this script existed the
requirement was prose on both sides: nothing produced a boundary, and nothing
looked at whether the one the assistant believed in was real. The stop that
protects a customer with a code-generation or text-to-SQL evaluator was a
sentence someone had to read, believe, and act on.

This runs a probe INSIDE the command you declare and reports what the probe
could actually observe. It is not a sandbox and it does not build one: you
supply the command that enters your boundary, and this says whether that
command delivers the properties the contract names.

Five of those properties are observable from inside, and each is reported as
`proven`, `refuted`, or `unverified` with the evidence it rests on:

* `entered`     - the probe ran to completion AND this host's filesystem is not
                  visible at its own absolute paths. The second half is the one
                  that matters. A command that silently runs on the host looks
                  identical to a contained one on every other axis - measured,
                  the host here reported uid 1000, which is not root and passes
                  an identity check on its own.
* `network`     - no IPv4 or IPv6 route leaves loopback. Read from the routing
                  table rather than by opening a connection, because a failed
                  connection does not mean what it appears to: measured on one
                  machine, a container with a working network stack and no
                  route to the probe address failed with a timeout, which a
                  connect-and-see check scores exactly like a disabled network.
                  A route table cannot be silent in that direction. Counting
                  interfaces is wrong for the mirror-image reason - a network
                  namespace with no connectivity still carries `tunl0`, `gre0`,
                  `sit0` and their siblings, so "one interface" never holds.
* `credentials` - no environment variable inside the boundary has the shape of
                  a provider, Traigent, or project secret. Names only; this
                  never reads or prints a value.
* `filesystem`  - the two host paths this check can name - its own scratch
                  directory and the working directory - took no write from
                  inside. `filesystem_property` reads this host afterwards
                  rather than trusting what the probe says about its own
                  writes, so a boundary that lies about them still fails.
* `identity`    - the probe did not run as uid 0.

What it does NOT establish, said here so a clean exit is not read as more than
it is. The contract's resource limits - wall-clock, CPU, memory, process count,
open files, file size, scratch space, captured output - are not exercised, nor
is per-candidate disposability, nor descendant-process teardown, nor whether
some OTHER host directory is mounted writable. `filesystem` names two paths
because two are all a checker can know about; a boundary can pass here and
still mount a third. Those remain the assistant's to declare and record.

The declared command must end where a program to run is expected - after the
image for `docker run`, after the bindings for a sandbox wrapper - because the
probe is appended to it as arguments. No runtime is recommended here and none
is required. One was driven while this was written; a second was installed on
that same machine and refused to create a namespace at all, which is the whole
reason this reports what a probe observed rather than what a runtime is
supposed to do.

Three other shapes were weighed and lost. A recipe in the guidance is the
cheapest, and is one more instruction with nothing checking it - the defect
this file exists to answer, reintroduced one document away. It is also less
portable than it looks: the container recipe this repository already owns for
its own use is refused by the daemon on an ordinary developer machine, with an
error about file sharing that says nothing about containment, so the customer
who copied it would be stuck holding a command and no diagnosis. A check that
inspects the host and names what it finds has to guess what an installed
runtime would do, and the second runtime above is why that guess is worthless -
present, and unable to start. Building the sandbox for the customer was never
available: it has to hold their evaluator, their fixtures and their database,
and a runner invented here knows none of those.

Exits 0 when every property is proven, 1 when any is refuted, 2 when any could
not be verified - a missing runtime and a probe that never ran are both this -
and 3 when this script fails, which is never a finding about the boundary. Only
0 clears the execution evaluator to run. 1 and 2 route the same way the
reference does: do not run the execution evaluator or paid optimization against
it; use non-executing static/parser/compile checks or pause for a safe runner.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path

INTERNAL_ERROR_EXIT = 3
TRACEBACK_ENV = "TRAIGENT_FIRST_RUN_TRACEBACK"

PROVEN, REFUTED, UNVERIFIED = "proven", "refuted", "unverified"

# An environment-variable NAME that looks like it carries a secret. Matched on
# the name because the value is never read: a check that prints what it found
# to prove it found it is the leak it was guarding against.
CREDENTIAL_NAME = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|TRAIGENT)", re.IGNORECASE
)
# A real environment-variable name, used to discard the debris a value
# containing a newline leaves in `env` output. A line that survives this and
# matches the pattern above is reported; that direction is the safe one, since
# the consequence is a finding the customer can look at rather than a secret
# this check decided to ignore.
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# POSIX shell, and nothing beyond `id`, `cat` and `env` - because the image is
# the customer's and an interpreter cannot be assumed inside it. Paths arrive as
# positional parameters rather than interpolated, so a working directory with a
# quote in it cannot rewrite the probe.
PROBE = r"""
printf '@token %s\n' "$4"
printf '@uid %s\n' "$(id -u 2>/dev/null || echo unknown)"
if [ -e "$1" ]; then printf '@marker visible\n'; else printf '@marker absent\n'; fi
if ( : > "$2" ) 2>/dev/null; then printf '@scratch-write ok\n'; else printf '@scratch-write refused\n'; fi
if ( : > "$3" ) 2>/dev/null; then printf '@workdir-write ok\n'; else printf '@workdir-write refused\n'; fi
printf '@begin route4\n'; cat /proc/net/route 2>/dev/null; printf '@end route4\n'
printf '@begin route6\n'; cat /proc/net/ipv6_route 2>/dev/null; printf '@end route6\n'
printf '@begin env\n'; env 2>/dev/null; printf '@end env\n'
printf '@done %s\n' "$4"
"""


def redacted_command(command: list[str]) -> list[str]:
    """The declared command with any secret it carries removed.

    Found by running this check rather than by reading it. The report echoes
    the command back so the reader knows which boundary was measured, and the
    commonest way to fail the `credentials` property is `-e SOMETHING_KEY=...`
    on that very command line - so the report was printing the secret it had
    just refused, into a terminal and a JSON file, one line above a finding
    that carefully said "names only; no value was read".
    """
    safe: list[str] = []
    for argument in command:
        name, separator, _ = argument.partition("=")
        if separator and ENVIRONMENT_NAME.match(name) and CREDENTIAL_NAME.search(name):
            safe.append(f"{name}=<redacted>")
        else:
            safe.append(argument)
    return safe


@dataclass(frozen=True)
class Property:
    """One contract property, its verdict, and what the verdict rests on."""

    name: str
    verdict: str
    evidence: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "verdict": self.verdict, "evidence": self.evidence}

    def render(self) -> str:
        return f"  {self.verdict.upper():<10} {self.name}: {self.evidence}"


def section(output: str, name: str) -> list[str] | None:
    """The lines the probe emitted between `@begin <name>` and `@end <name>`.

    `None` when the section never closed, which is a truncated probe rather than
    an empty file - the two must not read alike, because an empty routing table
    is the passing observation and a truncated one establishes nothing.
    """
    lines = output.splitlines()
    try:
        start = lines.index(f"@begin {name}")
        end = lines.index(f"@end {name}", start)
    except ValueError:
        return None
    return lines[start + 1 : end]


def field(output: str, name: str) -> str | None:
    """The value of the probe's single-line `@<name> <value>` report."""
    for line in output.splitlines():
        prefix = f"@{name} "
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def routes_off_loopback(
    route4: list[str] | None, route6: list[str] | None
) -> list[str]:
    """Every routing-table entry that names an interface other than loopback.

    `/proc/net/route` carries one header line and one line per IPv4 route;
    `/proc/net/ipv6_route` has no header and keeps its interface in the last
    field, where a namespace with no connectivity still lists its own `lo`.
    """
    found: list[str] = []
    for line in (route4 or [])[1:]:
        fields = line.split()
        if fields and fields[0] != "lo":
            found.append(f"IPv4 via {fields[0]}")
    for line in route6 or []:
        fields = line.split()
        if fields and fields[-1] != "lo":
            found.append(f"IPv6 via {fields[-1]}")
    return sorted(set(found))


def credential_names(environment: list[str] | None) -> list[str]:
    """Names in the probe's `env` output that have the shape of a secret."""
    names: list[str] = []
    for line in environment or []:
        name, separator, _ = line.partition("=")
        if not separator or not ENVIRONMENT_NAME.match(name):
            continue
        if CREDENTIAL_NAME.search(name):
            names.append(name)
    return sorted(set(names))


def entered_property(output: str, token: str, marker: Path) -> Property:
    """Whether a boundary was entered at all - the property the rest rests on.

    Two failures are told apart because they route differently for the reader.
    A probe that never reported means the declared command did not run it, so
    nothing was measured. A probe that reported and could see `marker` at its
    own absolute path means the command ran somewhere this host's filesystem
    reaches, which is a boundary that is not one.
    """
    if field(output, "token") != token or field(output, "done") != token:
        return Property(
            "entered",
            UNVERIFIED,
            "the declared command did not run the probe to completion, so no "
            "property below was measured; check that the command ends where a "
            "program to run is expected",
        )
    marker_seen = field(output, "marker")
    if marker_seen == "absent":
        return Property(
            "entered",
            PROVEN,
            f"the probe ran and could not see {marker}, a file this host has",
        )
    if marker_seen == "visible":
        return Property(
            "entered",
            REFUTED,
            f"the probe could see {marker}, so it ran on this host or this "
            "host's filesystem is mounted at its own absolute paths",
        )
    return Property(
        "entered", UNVERIFIED, "the probe reported no reading for the host marker"
    )


def network_property(output: str) -> Property:
    route4 = section(output, "route4")
    route6 = section(output, "route6")
    if route4 is None or route6 is None:
        return Property(
            "network", UNVERIFIED, "the probe did not report a complete routing table"
        )
    off_loopback = routes_off_loopback(route4, route6)
    if off_loopback:
        return Property(
            "network",
            REFUTED,
            "the boundary carries a route off loopback: " + ", ".join(off_loopback),
        )
    return Property(
        "network",
        PROVEN,
        f"no route leaves loopback ({len(route4[1:])} IPv4 and "
        f"{len(route6)} IPv6 entries, none off `lo`)",
    )


def credentials_property(output: str) -> Property:
    environment = section(output, "env")
    if environment is None:
        return Property(
            "credentials", UNVERIFIED, "the probe did not report its environment"
        )
    names = credential_names(environment)
    if names:
        return Property(
            "credentials",
            REFUTED,
            "the boundary carries variables shaped like secrets: "
            + ", ".join(names)
            + " (names only; no value was read)",
        )
    return Property(
        "credentials",
        PROVEN,
        f"none of the {len(environment)} variables inside is shaped like a secret",
    )


def filesystem_property(output: str, landed: list[Path]) -> Property:
    """Whether either host path this check can name took a write from inside.

    `landed` is read from this host after the boundary exits, so the verdict
    does not depend on the probe telling the truth about its own writes.
    """
    if landed:
        return Property(
            "filesystem",
            REFUTED,
            "a write from inside the boundary reached this host at "
            + ", ".join(str(path) for path in landed),
        )
    if field(output, "scratch-write") is None or field(output, "workdir-write") is None:
        return Property(
            "filesystem", UNVERIFIED, "the probe did not report both write attempts"
        )
    return Property(
        "filesystem",
        PROVEN,
        "neither this check's scratch directory nor the working directory took "
        "a write from inside; a host path this check cannot name may still be "
        "mounted writable",
    )


def identity_property(output: str) -> Property:
    uid = field(output, "uid")
    if uid is None or not uid.isdigit():
        return Property(
            "identity", UNVERIFIED, "the probe could not report its own user id"
        )
    if uid == "0":
        return Property("identity", REFUTED, "the probe ran as uid 0")
    return Property(
        "identity",
        PROVEN,
        f"the probe ran as uid {uid}; on its own this says little, since an "
        "ordinary host user is not uid 0 either",
    )


def evaluate(
    output: str, token: str, marker: Path, landed: list[Path]
) -> list[Property]:
    """Every property, in the order a reader should lose confidence in them.

    `entered` is first and is not merely one of five: when it is unverified the
    probe produced no readings at all, so the four below would each report
    "the probe did not say", which reads as four independent problems instead
    of one. They are collapsed into what actually happened.
    """
    entered = entered_property(output, token, marker)
    if entered.verdict == UNVERIFIED:
        return [entered]
    return [
        entered,
        network_property(output),
        credentials_property(output),
        filesystem_property(output, landed),
        identity_property(output),
    ]


class _Parser(argparse.ArgumentParser):
    """Usage errors exit as the check breaking, not as an unverified boundary.

    argparse's own exit code is 2, which this tool spends on "the boundary
    could not be verified" - so a misspelled flag would route a customer to the
    fail-closed path while telling them nothing true about their sandbox.
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: {message}", file=sys.stderr)
        raise SystemExit(INTERNAL_ERROR_EXIT)


def run(argv: list[str] | None = None) -> int:
    parser = _Parser(
        description=(
            "Run a probe inside a declared boundary and report which "
            "execution-evaluator containment properties it enforces. Supply "
            "the command that enters the boundary after `--`, ending where a "
            "program to run is expected."
        ),
        epilog=(
            "example: verify_sandbox.py -- docker run --rm --network none "
            "--read-only --cap-drop ALL --security-opt no-new-privileges "
            "--user 65534:65534 python:3.12-slim"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="seconds to wait for the probe (default: 120)",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the report as JSON on stdout"
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="`--` then the command that enters the boundary",
    )
    args = parser.parse_args(argv)

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("no boundary command was given after `--`")

    token = secrets.token_hex(8)
    scratch = Path(tempfile.mkdtemp(prefix="verify_sandbox_"))
    marker = scratch / f"host-marker-{token}"
    scratch_write = scratch / f"scratch-write-{token}"
    workdir_write = Path.cwd() / f".verify_sandbox_write_probe_{token}"

    shown = redacted_command(command)

    def envelope(status: str, properties: list[Property], note: str) -> None:
        """The `--json` contract holds on every exit `run()` returns."""
        print(
            json.dumps(
                {
                    "command": shown,
                    "status": status,
                    "properties": [item.as_dict() for item in properties],
                    "not_established": NOT_ESTABLISHED,
                    "note": note,
                },
                indent=2,
            )
        )

    def report(status: str, properties: list[Property], note: str) -> None:
        if args.json:
            envelope(status, properties, note)
            return
        print(f"boundary: {' '.join(shown)}")
        for item in properties:
            print(item.render())
        print(note)

    try:
        marker.write_text("the boundary must not be able to see this file\n")
        probe = [
            "/bin/sh",
            "-c",
            PROBE,
            "verify_sandbox_probe",
            str(marker),
            str(scratch_write),
            str(workdir_write),
            token,
        ]
        try:
            completed = subprocess.run(  # noqa: S603 - the command is the user's
                command + probe,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                check=False,
            )
        except FileNotFoundError:
            report(
                UNVERIFIED,
                [
                    Property(
                        "entered",
                        UNVERIFIED,
                        f"`{command[0]}` is not on PATH, so no boundary was "
                        "entered and nothing was measured",
                    )
                ],
                NO_BOUNDARY_NOTE,
            )
            return 2
        except (OSError, subprocess.TimeoutExpired) as error:
            report(
                UNVERIFIED,
                [
                    Property(
                        "entered",
                        UNVERIFIED,
                        f"the boundary command did not complete: "
                        f"{type(error).__name__}",
                    )
                ],
                NO_BOUNDARY_NOTE,
            )
            return 2

        landed = [path for path in (scratch_write, workdir_write) if path.exists()]
        properties = evaluate(completed.stdout, token, marker, landed)
    finally:
        # Removed whether or not a write landed: leaving the probe's own file in
        # the customer's project is a side effect this check has no business
        # having, and the verdict above already read it.
        workdir_write.unlink(missing_ok=True)
        shutil.rmtree(scratch, ignore_errors=True)

    verdicts = {item.verdict for item in properties}
    if REFUTED in verdicts:
        status, code, note = REFUTED, 1, REFUTED_NOTE
    elif UNVERIFIED in verdicts:
        status, code, note = UNVERIFIED, 2, UNVERIFIED_NOTE
    else:
        status, code, note = PROVEN, 0, PROVEN_NOTE
    if status != PROVEN and completed.returncode != 0:
        tail = (completed.stderr or "").strip().splitlines()[-1:]
        if tail:
            note = (
                f"{note}\nthe boundary command exited {completed.returncode}: {tail[0]}"
            )
    report(status, properties, note)
    return code


# Written once each because each is a routing instruction, and a routing
# instruction that differs between the text and the JSON is two instructions.
NOT_ESTABLISHED = [
    "wall-clock, CPU, memory, process-count, open-file, file-size, scratch-space "
    "and captured-output limits",
    "a fresh or reset sandbox per candidate",
    "descendant-process-tree teardown on completion or limit breach",
    "whether a host path other than the two named above is mounted writable",
]
PROVEN_NOTE = (
    "Every property this check can reach is proven. The limits, per-candidate "
    "disposability and teardown it does not reach stay yours to declare and "
    "record in the run plan."
)
REFUTED_NOTE = (
    "This boundary does not enforce the containment contract. Do not run the "
    "execution evaluator or paid optimization against it; use non-executing "
    "static/parser/compile checks or pause for a safe runner."
)
UNVERIFIED_NOTE = (
    "This boundary was not proven, which is not the same as proven safe. Do "
    "not run the execution evaluator or paid optimization against it; use "
    "non-executing static/parser/compile checks or pause for a safe runner."
)
NO_BOUNDARY_NOTE = (
    "No boundary was entered, so nothing about containment was established. "
    "Do not run the execution evaluator or paid optimization; use "
    "non-executing static/parser/compile checks or pause for a safe runner."
)


def report_internal_error(tool: str, error: BaseException) -> int:
    """Say the check broke, not the project - copied out per script by design.

    Each bundled script owns this boundary, because each ships alone. The stack
    is available behind an environment variable rather than printed at a user
    who did not ask for it.
    """
    print(f"{tool}: {type(error).__name__}: {error}", file=sys.stderr)
    print(
        f"{tool} could not complete. This is a defect in the check rather than "
        "in your project; nothing about the boundary was established, so it "
        "clears nothing.",
        file=sys.stderr,
    )
    if os.environ.get(TRACEBACK_ENV):
        traceback.print_exc()
    return INTERNAL_ERROR_EXIT


def main() -> int:
    try:
        return run()
    except Exception as error:  # noqa: BLE001 - reported, never swallowed
        return report_internal_error("verify_sandbox.py", error)


if __name__ == "__main__":
    sys.exit(main())

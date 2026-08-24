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

Six of those properties are observable from inside, and each is reported as
`proven`, `refuted`, or `unverified` with the evidence it rests on:

* `entered`     - the probe ran to completion AND could not see the one host
                  file this check made for it, under this host's temporary
                  directory. That is a single path, and saying so is the point:
                  it is not "this host's filesystem is invisible", which one
                  path cannot establish. A boundary can pass this and still
                  mount some other host directory at its own absolute path,
                  which is what `filesystem` is for. What it does catch is the
                  command that silently ran on the host, and that matters
                  because such a command looks identical to a contained one on
                  every other axis - measured, the host here reported uid 1000,
                  which is not root and passes an identity check on its own.
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
* `credentials` - no environment variable inside the boundary carries a NAME
                  shaped like a provider, Traigent, or project secret. Names
                  only; this never reads or prints a value. That is a floor and
                  not a clearance: a name-shape test cannot see a secret under a
                  name it does not recognise, and it deliberately passes over
                  one name that is public by construction in the common base
                  images - the signing-key fingerprint they verify their own
                  download with - so a real secret hidden under that exact name
                  is not seen either. `SECRET_ALLOWED` is that one name, and
                  says why it is there.
* `filesystem`  - none of the three host paths this check can name - its own
                  scratch directory, the working directory, and this host's home
                  directory - took a write from inside. Home and working
                  directory are there because the contract names exactly those
                  two nouns: "no writable host home or project mount". The
                  verdict is read from this host after the boundary exits, not
                  from what the probe says about its own writes, so a boundary
                  that claims it was refused while actually writing still fails.
                  The reverse direction is not symmetric and is not claimed: a
                  write the probe reports as succeeding, with no host file
                  behind it, means the path was shadowed by a filesystem that is
                  not this host's, and is reported that way rather than as a
                  contradiction.
* `privilege`   - the probe holds no effective capabilities, cannot see either
                  of this check's own processes, and runs with `no_new_privs`
                  set. The contract's third bullet asks for all three and this
                  used to read none of them, so `--privileged --pid host`
                  cleared every other property and was told it had passed.
* `identity`    - the probe did not run as uid 0.

Everything above except `filesystem` is read from what the probe printed. A
declared command that fabricates that output is believed; the nonce defeats a
recorded transcript replayed verbatim and nothing more. That is not the threat
this exists for - the assistant running it is not trying to defeat it - but a
file called `verify_sandbox` should say which half of its report is a
measurement of this host and which half is testimony.

What it does NOT establish, said here so a clean exit is not read as more than
it is. The contract's resource limits - wall-clock, CPU, memory, process count,
open files, file size, scratch space, captured output - are not exercised, nor
is per-candidate disposability, nor descendant-process teardown, nor whether
some OTHER host directory is mounted writable. `filesystem` names three paths
because three are all a checker can know about; a boundary can pass here and
still mount a fourth. Seccomp confinement is read and reported but never
refuted on, because a boundary can be isolated by a virtual machine and carry no
seccomp filter at all. Those remain the assistant's to declare and record.

The declared command must end where a program to run is expected - after the
image for `docker run`, after the bindings for a sandbox wrapper - because the
probe is appended to it as arguments. No runtime is recommended here and none
is required. One was driven while this was written; a second was installed on
that same machine and could not complete a single sandboxing invocation on it -
the namespace is created, and then the kernel denies the uid-map write and the
network capability the runtime needs, so every attempt exited non-zero. That is
the whole reason this reports what a probe observed rather than what an
installed runtime is supposed to do.

Three other shapes were weighed and lost. A recipe in the guidance is the
cheapest, and is one more instruction with nothing checking it - the defect
this file exists to answer, reintroduced one document away. It is also less
portable than it looks: the container recipe this repository already owns for
its own use is refused by one ordinary developer daemon, for a checkout outside
the directories that daemon shares, with an error about file sharing that says
nothing about containment - the same recipe, same machine, run from a shared
directory or against a different daemon, works. A customer who copied it would
be stuck holding a command and no diagnosis, and could not tell from the error
which of those two situations they were in. A check that
inspects the host and names what it finds has to guess what an installed
runtime would do, and the second runtime above is why that guess is worthless -
present, and unable to start. Building the sandbox for the customer was never
available: it has to hold their evaluator, their fixtures and their database,
and a runner invented here knows none of those.

Exits 0 when every property above is proven, 1 when any is refuted, 2 when any
could not be verified - a missing runtime and a probe that never ran are both
this - and 3 when this script fails, which is never a finding about the
boundary. Exit 0 means every property this check reads is proven; it does not
mean the contract is met, because the paragraph above names what is never read.
Only 0 clears the execution evaluator to run. `--json` carries every exit that
0, 1 and 2 come out of; exit 3 is the check breaking before it has a report to
make, and it writes plain text to stderr rather than an envelope, so a machine
consumer has to expect a non-JSON stdout on that one code. 1 and 2 route the
same way the reference does: do not run the execution evaluator or paid
optimization against it; use non-executing static/parser/compile checks or
pause for a safe runner.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
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

# The words that make an environment-variable NAME look like it carries a
# secret. Matched on the name because the value is never read: a check that
# prints what it found to prove it found it is the leak it was guarding
# against.
#
# Compared by underscore-separated SEGMENT, not by substring. A substring test
# over these words is a false-red factory - `PAT` sits inside `PATH`, which
# every boundary on earth carries - and the first version of this file paid the
# opposite price for the same shortcut: matching only a handful of words let
# `GITHUB_PAT`, `AUTHORIZATION` and `SSH_AUTH_SOCK` through a boundary this
# check then called clean.
#
# `SESSION` was tried and taken back out. Run against this host it reported
# `XDG_SESSION_TYPE`, `DESKTOP_SESSION`, `GNOME_SHELL_SESSION_MODE`,
# `SESSION_MANAGER`, `DBUS_SESSION_BUS_ADDRESS` and two more, none of them a
# credential and all of them noise in front of the ones that were - and it
# bought nothing, because every session variable that IS a secret says so
# another way: `SESSION_TOKEN` under `TOKEN`, `SESSION_COOKIE` under `COOKIE`.
# A word earns a place here by catching something no other word catches.
SECRET_SEGMENTS = frozenset(
    {
        "AUTHKEY",
        "AUTHTOKEN",
        "JWT",
        "KEY",
        "KEYS",
        "APIKEY",
        "ACCESSKEY",
        "SECRET",
        "SECRETS",
        "TOKEN",
        "PASSWORD",
        "PASSWD",
        "PASS",
        "PASSPHRASE",
        "CREDENTIAL",
        "CREDENTIALS",
        "TRAIGENT",
        "PAT",
        "AUTH",
        "AUTHORIZATION",
        "BEARER",
        "COOKIE",
        "NETRC",
        "KUBECONFIG",
        "PRIVATE",
    }
)
# A connection string carries its credential inside the value, and its name
# usually carries none of the words above: read as segments, `DATABASE_URL` is
# two innocuous English words, and it is the likeliest variable to appear in
# this script's own headline use case, text-to-SQL. It is reported when a
# store word and a locator word share one name, which is narrow on purpose -
# `API_URL` and `BASE_URL` are not credentials and must not be refuted.
STORE_SEGMENTS = frozenset(
    {
        "DATABASE",
        "DB",
        "POSTGRES",
        "POSTGRESQL",
        "PG",
        "MYSQL",
        "MARIADB",
        "MONGO",
        "MONGODB",
        "REDIS",
        "AMQP",
        "RABBITMQ",
        "SMTP",
        "WEBHOOK",
        "CLICKHOUSE",
        "SNOWFLAKE",
        "S3",
    }
)
LOCATOR_SEGMENTS = frozenset({"URL", "URI", "DSN", "CONN", "CONNECTION"})
# A DSN is a connection string by definition, so it needs no store word beside
# it: `SENTRY_DSN` carries its own credential, and nothing innocuous is spelled
# this way.
LOCATOR_ONLY_SEGMENTS = frozenset({"DSN"})
# Exactly one name, and exact rather than a pattern, because the cost of the
# entry is a real secret hidden under it.
#
# `GPG_KEY` on the Docker official language images holds the PUBLIC fingerprint
# used to verify the interpreter tarball. Without this line the example in this
# script's own `--help` fails its own check on the image this repository pins,
# and - worse than a false red - the reader cannot resolve it: no run flag
# removes a variable an image baked in, so the only available fix is to stop
# using the check. `GPG_PRIVATE_KEY` and every other longer spelling is still
# reported, which is why this is a name list and not a rule about `GPG`.
SECRET_ALLOWED = frozenset({"GPG_KEY"})
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
if ( : > "$5" ) 2>/dev/null; then printf '@home-write ok\n'; else printf '@home-write refused\n'; fi
seen=0
if [ -e "/proc/$6" ]; then seen=$((seen+1)); fi
if [ -e "/proc/$7" ]; then seen=$((seen+1)); fi
printf '@host-process %s\n' "$seen"
printf '@begin route4\n'; cat /proc/net/route 2>/dev/null; printf '@end route4\n'
printf '@begin route6\n'; cat /proc/net/ipv6_route 2>/dev/null; printf '@end route6\n'
printf '@begin status\n'; cat /proc/self/status 2>/dev/null; printf '@end status\n'
printf '@begin env\n'; env 2>/dev/null; printf '@end env\n'
printf '@done %s\n' "$4"
"""


# The spellings that put a NAME=VALUE operand on a command line. `-e X=Y`,
# `-eX=Y`, `--env X=Y` and `--env=X=Y` are one flag with four accepted forms,
# and a redactor that knows only the first of them is a redactor that leaks.
ENV_FLAGS = frozenset({"-e", "--env"})


def blanked_operand(operand: str) -> str:
    """A `NAME=VALUE` operand with the value gone, by POSITION not by name.

    `NAME` alone is returned untouched: that spelling passes the variable
    through from the surrounding environment and carries no value here.
    """
    name, separator, _ = operand.partition("=")
    return f"{name}=<redacted>" if separator else operand


def redacted_command(command: list[str]) -> list[str]:
    """The declared command with any value it carries removed.

    Found by running this check rather than by reading it. The report echoes
    the command back so the reader knows which boundary was measured, and the
    commonest way to fail the `credentials` property is to put the secret on
    that very command line - so the report was printing the secret it had just
    refused, one line above a finding that carefully said "names only; no value
    was read".

    Keyed on the FLAG rather than on the name, and that is the whole fix. The
    first version asked whether the name looked secret-shaped, which meant its
    correctness depended on enumerating every name a customer might choose:
    measured, `-e DATABASE_URL=postgres://user:pw@host/db` printed the password
    in full, and so did every spelling the name test could not parse -
    `-eOPENAI_API_KEY=...` and `--env=OPENAI_API_KEY=...` are ordinary, and both
    leaked. A `-e` operand is a value by position, whatever it is called.

    The name test is kept underneath as a second net, for `NAME=VALUE` typed
    without a flag in front of it, but nothing rests on it any more.

    One shape remains readable and cannot be closed by any rule: a secret typed
    inside a positional argument, such as a connection string quoted into a
    `sh -c` script the boundary command runs. Nothing marks it as a value, so
    nothing here can find it - the report echoes the command the reader typed,
    and that part of it is theirs.
    """
    safe: list[str] = []
    expect_operand = False
    for argument in command:
        if expect_operand:
            safe.append(blanked_operand(argument))
            expect_operand = False
            continue
        if argument in ENV_FLAGS:
            safe.append(argument)
            expect_operand = True
            continue
        if argument.startswith("--env="):
            safe.append("--env=" + blanked_operand(argument[len("--env=") :]))
            continue
        # Short flags cluster, so the `e` need not come first: `-ieNAME=VALUE`
        # is accepted by the same parser, and a branch that only matched a
        # leading `e` printed that operand in full. Everything after the FIRST
        # `e` in the cluster is the operand, which is what getopt does with it.
        if (
            argument.startswith("-")
            and not argument.startswith("--")
            and "e" in argument[1:]
        ):
            head, _, operand = argument.partition("e")
            if operand:
                safe.append(f"{head}e{blanked_operand(operand)}")
                continue
        name, separator, _ = argument.partition("=")
        if separator and ENVIRONMENT_NAME.match(name) and secret_shaped(name):
            safe.append(f"{name}=<redacted>")
            continue
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


def secret_shaped(name: str) -> bool:
    """Whether this variable NAME reads like it carries a credential."""
    if name in SECRET_ALLOWED:
        return False
    segments = set(name.upper().split("_"))
    if segments & SECRET_SEGMENTS or segments & LOCATOR_ONLY_SEGMENTS:
        return True
    return bool(segments & STORE_SEGMENTS and segments & LOCATOR_SEGMENTS)


def credential_names(environment: list[str] | None) -> list[str]:
    """Names in the probe's `env` output that have the shape of a secret."""
    names: list[str] = []
    for line in environment or []:
        name, separator, _ = line.partition("=")
        if not separator or not ENVIRONMENT_NAME.match(name):
            continue
        if secret_shaped(name):
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
    # A section that closed but arrived EMPTY is the same class of nothing as
    # one that never closed, and it used to read as the passing observation.
    # `/proc/net/route` always carries a header line - the fixtures in this
    # package's tests carry it because the kernel does - so an empty one means
    # the file could not be read, not that no route exists. A container on the
    # default bridge with the whole internet reachable, where only `cat` was
    # unavailable, was cleared by this property before the guard below existed;
    # `tests/test_verify_sandbox.py` reproduces the parse that did it. Any
    # boundary without `/proc` mounted lands here by accident.
    #
    # IPv6 is not held to the same rule: `/proc/net/ipv6_route` has no header
    # and is legitimately absent on a host with IPv6 disabled, so an empty one
    # really can mean no route.
    if not route4:
        return Property(
            "network",
            UNVERIFIED,
            "the probe reported an empty IPv4 routing table, and that file "
            "always carries a header line - so it could not be read rather "
            "than being empty, and whether a route leaves loopback is unknown",
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
    # Empty, for the same reason the routing table is: `env` in a POSIX shell
    # reports at least the variables the shell itself sets, so nothing coming
    # back means nothing was read.
    if not environment:
        return Property(
            "credentials",
            UNVERIFIED,
            "the probe reported no environment at all, which is not the same "
            "as an empty one - a shell always reports the variables it sets "
            "itself, so this reading did not happen",
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
        f"none of the {len(environment)} variable names inside is shaped like "
        "a secret - a floor, not a clearance: this reads names and cannot see "
        "a secret under a name it does not recognise",
    )


# The three host paths this check is able to name. Home and the working
# directory are here because the contract names exactly those two nouns - "no
# writable host home or project mount" - and naming only the working directory
# left the commoner of the two unmeasured: measured, a boundary mounting the
# customer's whole home read-write passed every property and exited 0, from
# where it could read their `~/.ssh` and write into their projects.
WRITE_PROBES = ("scratch-write", "workdir-write", "home-write")
WRITE_PROBE_NOUNS = "this check's scratch directory, the working directory and this host's home directory"


def filesystem_property(
    output: str, landed: list[Path], unreadable: list[str]
) -> Property:
    """Whether any host path this check can name took a write from inside.

    `landed` is read from this host after the boundary exits, so a boundary
    that claims a write was refused while actually performing it still fails.
    The reverse direction is not symmetric and is not claimed here: a write the
    probe reports as succeeding with no host file behind it means the path was
    shadowed inside the boundary by a filesystem that is not this host's, which
    is a compliant arrangement and is described rather than refuted.
    """
    if unreadable:
        return Property(
            "filesystem",
            UNVERIFIED,
            "this check could not read back " + ", ".join(unreadable) + ", so "
            "whether a write from inside reached it is unknown - and unknown "
            "is not clean",
        )
    if landed:
        # `dict.fromkeys` rather than a set: the working directory can BE the
        # home directory, in which case two probes name one path and the
        # refutation listed it twice. De-duplicated here, where the sentence is
        # built, so the property does not depend on its caller having done it;
        # order stays stable so the message reads the same way every run.
        return Property(
            "filesystem",
            REFUTED,
            "a write from inside the boundary reached this host at "
            + ", ".join(str(path) for path in dict.fromkeys(landed)),
        )
    reports = {name: field(output, name) for name in WRITE_PROBES}
    missing = [name for name, value in reports.items() if value is None]
    if missing:
        return Property(
            "filesystem",
            UNVERIFIED,
            "the probe did not report every write attempt (missing: "
            + ", ".join(missing)
            + ")",
        )
    shadowed = [name for name, value in reports.items() if value == "ok"]
    if shadowed:
        return Property(
            "filesystem",
            PROVEN,
            f"no write from inside reached {WRITE_PROBE_NOUNS}. The probe did "
            "create a file at " + ", ".join(shadowed) + ", so that path exists "
            "inside the boundary on a filesystem that is not this host's; a "
            "host path this check cannot name may still be mounted writable",
        )
    return Property(
        "filesystem",
        PROVEN,
        f"none of {WRITE_PROBE_NOUNS} took a write from inside; a host path "
        "this check cannot name may still be mounted writable",
    )


def status_value(status: list[str], key: str) -> str | None:
    """One `Name:\tvalue` line from the probe's `/proc/self/status`."""
    for line in status:
        name, separator, value = line.partition(":")
        if separator and name.strip() == key:
            return value.strip()
    return None


def privilege_property(output: str) -> Property:
    """The contract's privilege clause, which nothing used to read.

    "An unprivileged identity, no elevated capabilities or privilege
    escalation" is one bullet with three demands, and `identity` answers only
    the first. That gap cleared `--privileged --pid host`: with a non-root user
    the effective capability set is empty, so every other property passed over
    a boundary that could read this host's process list and reach its block
    devices. `tests/test_verify_sandbox.py` pins each of the three findings.

    Seccomp is read and reported but never refuted on. A boundary isolated by a
    virtual machine legitimately carries no seccomp filter, and refusing it
    would be a false red on exactly the strongest kind of boundary.
    """
    status = section(output, "status")
    if status is None:
        return Property(
            "privilege", UNVERIFIED, "the probe did not report its process status"
        )
    if not status:
        return Property(
            "privilege",
            UNVERIFIED,
            "the probe read no process status, so its capabilities and whether "
            "it can escalate are unknown - `/proc` may not be mounted inside",
        )
    capabilities = status_value(status, "CapEff")
    # The BOUNDING set, and it is the one that matters here. `CapEff` is empty
    # for any non-root process, which is exactly what the contract's
    # unprivileged identity asks for - so reading it alone means a
    # `docker run --user` empties the field this property was keyed on. A
    # `docker run --privileged --user 65534:65534` reported `CapEff
    # 0000000000000000` and cleared every property, over a boundary whose
    # `/dev` carried `mem`, the loop devices and `mapper`; its `CapBnd` was
    # `000001ffffffffff`. `tests/test_verify_sandbox.py` pins both readings.
    #
    # This is a deliberate tightening and not only a fix: a container that
    # simply omits `--cap-drop ALL` carries a non-empty bounding set too, and
    # is now refuted. That is the reading of "no elevated capabilities" this
    # file is willing to defend - the bound is what a process inside could
    # still acquire - and it is what the example in `--help` already does.
    bounding = status_value(status, "CapBnd")
    no_new_privs = status_value(status, "NoNewPrivs")
    host_process = field(output, "host-process")
    if (
        capabilities is None
        or bounding is None
        or no_new_privs is None
        or host_process not in {"0", "1", "2"}
    ):
        return Property(
            "privilege",
            UNVERIFIED,
            "the probe's process status did not carry every reading this needs "
            "(effective and bounding capabilities, no-new-privileges, "
            "host-process visibility)",
        )
    try:
        held = int(capabilities, 16)
        bound = int(bounding, 16)
    except ValueError:
        return Property(
            "privilege",
            UNVERIFIED,
            f"the probe reported a capability set this cannot read: "
            f"{capabilities!r} / {bounding!r}",
        )
    # TWO host process ids, and both must be visible before this is a finding.
    # A boundary with its own process namespace numbers from 1, so a single
    # visible id can also be an ordinary collision with a low-numbered process
    # inside - and a false refusal on the privilege axis is the one that teaches
    # a reader to remove containment until the check stops complaining. Both ids
    # colliding at once is not something a handful of processes can do; a shared
    # namespace shows both every time.
    if host_process == "1":
        return Property(
            "privilege",
            UNVERIFIED,
            "exactly one of the two process ids this check named is visible "
            "inside the boundary, which neither shows a shared process "
            "namespace nor rules one out",
        )
    findings: list[str] = []
    if host_process == "2":
        findings.append(
            "it can see both of this check's own processes, so the boundary "
            "shares this host's process namespace"
        )
    if held:
        findings.append(f"it holds elevated capabilities (CapEff {capabilities})")
    if bound:
        findings.append(
            f"its capability bounding set is not empty (CapBnd {bounding}), so a "
            "process inside can still acquire capabilities the effective set "
            "does not show - drop them at the boundary"
        )
    if no_new_privs != "1":
        findings.append(
            "no-new-privileges is not set, so a setuid program inside can still "
            "raise its privileges"
        )
    if findings:
        return Property("privilege", REFUTED, "; ".join(findings))
    seccomp = status_value(status, "Seccomp")
    return Property(
        "privilege",
        PROVEN,
        f"no capabilities held or available (CapEff and CapBnd both "
        f"{capabilities}) and no-new-privileges set; seccomp mode "
        f"{seccomp or 'unreported'}, which is reported and never refuted on. "
        "Whether the boundary shares a process namespace is deliberately not "
        "part of this claim: seeing this check's own processes refutes, and not "
        "seeing them proves nothing, because a daemon that does not share this "
        "kernel cannot show them either",
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
    output: str,
    token: str,
    marker: Path,
    landed: list[Path],
    unreadable: list[str],
) -> list[Property]:
    """Every property, in the order a reader should lose confidence in them.

    `entered` is first and is not merely one of six: when it is unverified the
    probe produced no readings at all, so the five below would each report
    "the probe did not say", which reads as five independent problems instead
    of one. They are collapsed into what actually happened.
    """
    entered = entered_property(output, token, marker)
    if entered.verdict == UNVERIFIED:
        return [entered]
    return [
        entered,
        network_property(output),
        credentials_property(output),
        filesystem_property(output, landed, unreadable),
        privilege_property(output),
        identity_property(output),
    ]


def dispose(scratch: Path) -> None:
    """Remove this check's own scratch tree, whatever the boundary did to it.

    `shutil.rmtree(..., ignore_errors=True)` cannot remove a directory the
    boundary chmodded to mode 0, and quietly leaves it in the customer's `/tmp`
    - a check that litters on the one path it created itself.
    """
    try:
        scratch.chmod(0o700)
        for path in scratch.rglob("*"):
            try:
                path.chmod(0o700)
            except OSError:  # noqa: S110 - best effort before the removal below
                pass
    except OSError:  # noqa: S110 - the removal below reports what it cannot do
        pass
    shutil.rmtree(scratch, ignore_errors=True)
    if scratch.exists():
        print(
            f"verify_sandbox.py: could not remove its own scratch directory "
            f"{scratch}; remove it by hand",
            file=sys.stderr,
        )


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
    # `mkdtemp` creates mode `0o700` owned by whoever ran this, and every reading
    # taken inside that directory is then answered by a permission bit rather
    # than by the boundary. A boundary running as any other uid - which is what
    # this script's own example recommends, and what the contract's unprivileged
    # identity implies - cannot traverse it, so the marker reads as absent and
    # the scratch write reads as refused NO MATTER WHAT IS MOUNTED.
    #
    # On a daemon sharing this kernel, two commands differing only in their
    # `docker run --user`, both mounting the host's temporary directory
    # read-write at its own absolute path: as the unprivileged uid every
    # property was proven and the check cleared the boundary, and as the
    # caller's own uid the same boundary was refuted twice and failed it.
    # `entered` is the property the rest rests on, and it was being decided by
    # file permissions. `tests/test_verify_sandbox.py` reproduces the pair.
    #
    # `0o1777` rather than `0o755`: world-writable so the write probe means
    # something under a foreign uid, and sticky so no other local user can
    # delete the marker out from under this check and turn "absent" into a
    # passing reading. It is what `/tmp` itself is, and the only things in here
    # are a fixed sentence and a probe file - nothing secret is exposed by
    # making them readable.
    scratch.chmod(0o1777)
    marker = scratch / f"host-marker-{token}"
    scratch_write = scratch / f"scratch-write-{token}"
    workdir_write = Path.cwd() / f".verify_sandbox_write_probe_{token}"
    # A home this host cannot locate is not a home that took no write - it is a
    # reading that did not happen, so the probe is pointed somewhere nothing can
    # create a file and `filesystem` is told the noun went unmeasured.
    unreadable: list[str] = []
    try:
        home_write = Path.home() / f".verify_sandbox_write_probe_{token}"
    except RuntimeError:
        home_write = Path(f"/nonexistent-verify-sandbox/{token}")
        unreadable.append("this host's home directory (it could not be located)")

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
        # `shlex.join`, because this line exists so the reader knows WHICH
        # boundary was measured, and a bare space-join renders
        # `/bin/sh -c 'sleep 20; exec "$@"'` as something that is not the
        # command that ran.
        print(f"boundary: {shlex.join(shown)}")
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
            str(home_write),
            str(os.getpid()),
            str(os.getppid()),
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
            # A timeout kills the client this script started, not whatever that
            # client started. The boundary can still be running after the
            # cleanup below has run, and can still create the probe paths
            # afterwards - measured: the working directory was empty at exit and
            # carried the probe file twenty-five seconds later. No timing
            # assumption fixes that honestly, so it is named instead.
            note = NO_BOUNDARY_NOTE
            if isinstance(error, subprocess.TimeoutExpired):
                note = (
                    f"{note}\nThe declared command was still running after "
                    f"{args.timeout:g}s and was given up on, not stopped. It may "
                    f"yet create {workdir_write} or {home_write}; remove them if "
                    "they appear."
                )
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
                note,
            )
            return 2

        # `Path.exists()` propagates EACCES rather than answering False, and a
        # boundary that chmods this check's own scratch directory to mode 0 is
        # enough to raise it. Uncaught, that surfaced as an internal error
        # telling the customer the defect was in the check rather than in their
        # boundary - which is precisely backwards.
        landed: list[Path] = []
        for path in (scratch_write, workdir_write, home_write):
            try:
                if path.exists():
                    landed.append(path)
            except OSError as error:
                unreadable.append(f"{path} ({error.strerror or type(error).__name__})")
        properties = evaluate(completed.stdout, token, marker, landed, unreadable)
    finally:
        # Removed whether or not a write landed: leaving the probe's own file in
        # the customer's project or home is a side effect this check has no
        # business having, and the verdict above already read it.
        for path in (workdir_write, home_write):
            try:
                path.unlink(missing_ok=True)
            except OSError as error:  # noqa: PERF203 - reported, never swallowed
                print(
                    f"verify_sandbox.py: could not remove {path}: {error}",
                    file=sys.stderr,
                )
        dispose(scratch)

    verdicts = {item.verdict for item in properties}
    if REFUTED in verdicts:
        status, code, note = REFUTED, 1, REFUTED_NOTE
    elif UNVERIFIED in verdicts:
        status, code, note = UNVERIFIED, 2, UNVERIFIED_NOTE
    else:
        status, code, note = PROVEN, 0, PROVEN_NOTE
    if status != PROVEN and completed.returncode != 0:
        # The exit code, and deliberately not the message behind it. This used
        # to append the last line of the command's stderr, which is the one
        # piece of this report that cannot be redacted by any rule: it is the
        # customer's runtime talking, and measured, it reproduced a database
        # password in full from a connection error.
        note = (
            f"{note}\nthe boundary command itself exited "
            f"{completed.returncode}; its error output is not reproduced here, "
            "because it can carry the values this check refuses to print - run "
            "the command without this check to read it"
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
    "whether a host path other than the three named above is mounted writable",
    "whether a seccomp filter confines the boundary - the mode is read and "
    "reported, and never refuted on, because a virtual machine legitimately "
    "carries none",
    "whether a secret sits under a variable name this does not recognise, or "
    "under the one name it lets through on purpose",
    "whether the declared command reported truthfully: only the host-side "
    "read-back behind `filesystem` is measured here, and the rest is testimony",
    "whether the boundary shares a process namespace with anything else - "
    "seeing this check's own processes refutes it, but not seeing them is not "
    "evidence, because a daemon backed by a virtual machine or a remote host "
    "cannot show them either",
]
# `/proc` inside the boundary is a precondition, not an assumption: `network`,
# `credentials` and `privilege` are each read from it, and a boundary that does
# not mount it lands on their unverified arms and exits 2. That is fail-closed
# and it is the right direction, but it means some of the strictest sandboxes -
# a wrapper invoked without a proc mount, a bare chroot - are refused rather
# than cleared, and a reader who meets that should know why before loosening
# anything.
PROVEN_NOTE = (
    "Every property this check reads is proven. That is not the contract met: "
    "the limits, per-candidate disposability, teardown and the paths it was "
    "never told about are listed above precisely because nothing here reaches "
    "them, and they stay yours to declare and record in the run plan."
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

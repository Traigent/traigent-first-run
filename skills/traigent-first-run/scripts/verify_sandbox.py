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
* `filesystem`  - the two host directories the contract names, "no writable
                  host home or project mount", are not REACHABLE from inside,
                  and took no write. Reachability first, because a write probe
                  entered as an unprivileged identity cannot tell "the boundary
                  refused it" from "this identity could never have written here
                  anyway" - so a marker only this run knows the name of is
                  planted in each, and looked for at its own absolute path, in
                  the boundary's working directory, and in its home. The home is
                  refuted on reach alone: the contract admits required tests and
                  fixtures read-only plus a scratch directory, and a home is
                  neither. The working directory is where a project keeps the
                  tests a scorer needs, so there reach alone is not the finding
                  and a refused write finally means refused. The boundary's own
                  mount table is read as well, and it is exact only where the
                  boundary shares this kernel; where it does not, a row whose
                  source could still be one of the two - the same path with its
                  leading components cut off - is reported unverified rather
                  than proven. A directory mounted at a path this check was
                  never told about is not looked for - see what it does NOT
                  establish, below.
* `privilege`   - the probe holds no effective capabilities, none available to
                  acquire, and runs with `no_new_privs` set; and it cannot see
                  BOTH of this check's own processes, one being an ordinary
                  collision. The last two are reported and not refuted on: an
                  ordinary process on any Linux host carries the full bounding
                  set and no `no_new_privs`, so a virtual-machine guest - which
                  the contract admits - reads exactly like a privileged
                  container from in there.
* `identity`    - the probe did not run as uid 0.

All six are read from what the probe printed; `filesystem` alone also reads
this host afterwards, so a boundary that claims a write was refused while
performing it still fails. A declared command that fabricates its output is
otherwise believed; the nonce defeats a recorded transcript replayed verbatim
and nothing more. That is not the threat
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
import contextlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
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
# `TRAIGENT` was tried and taken back out too, for a harder reason than noise:
# `references/run-safety.md` tells the customer to set `TRAIGENT_OFFLINE_MODE`,
# and this refused the boundary that obeyed it - two shipped documents
# contradicting each other, with this one routing to "do not run". It also
# failed the admission rule below on its own terms, since `TRAIGENT_API_KEY` is
# already caught by `KEY`.
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
# `JWT` was tried and taken back out, and it belongs in the same paragraph as
# `SESSION` and `TRAIGENT` rather than disappearing without one: it reported
# `JWT_ISSUER` and `JWT_ALGORITHM`, neither of which is a secret, and it caught
# nothing another word does not - `JWT_SECRET` under `SECRET`, `JWT_TOKEN` under
# `TOKEN`. A bare variable called `JWT` is the only thing it would have added,
# and that is not a shape worth two false reds.
# Names with no separator in them at all, so no segment rule can reach the word
# inside. Kept as an exact list rather than a substring test, because the
# substring direction is what puts `PAT` inside `PATH`.
SECRET_NAMES = frozenset({"PGPASSWORD", "MYSQL_PWD", "SSHPASS", "PGPASSFILE"})
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
elsewhere() {
  # $1 label, $2 the marker's BASENAME.
  #
  # The other half of the question, and the half three rounds missed. Asking
  # only about the host's own absolute path answers "is this directory mounted
  # THERE", and the ordinary spelling does not mount it there:
  # `-v "$HOME:/hosthome:rw"` and `-v "$PWD:/work:rw" -w /work` both hand the
  # boundary the same directory under a name this check was never told. A file
  # name nothing else on earth is using does not care where it was mounted.
  #
  # Two places, because two are all a probe can look in without walking a
  # filesystem it does not own: the boundary's own working directory, and the
  # home its identity was given.
  if [ -e "./$2" ]; then printf '@%s cwd\n' "$1"
  elif [ -n "$HOME" ] && [ -e "$HOME/$2" ]; then printf '@%s home\n' "$1"
  else printf '@%s absent\n' "$1"; fi
}
reach() {
  # $1 label, $2 a host file only this check knows the name of, $3 its directory.
  #
  # Four answers, because "the write was refused" and "the directory is not
  # there" are not the same fact and only one of them is containment. A write
  # probe under a foreign uid cannot tell them apart at all: an ordinary 0755
  # home refuses the create AND hands the whole tree to any reader.
  if [ -e "$2" ]; then printf '@%s visible\n' "$1"
  elif [ ! -e "$3" ]; then printf '@%s no-such-directory\n' "$1"
  elif [ -x "$3" ]; then printf '@%s absent\n' "$1"
  else printf '@%s opaque\n' "$1"; fi
}
printf '@token %s\n' "$4"
printf '@uid %s\n' "$(id -u 2>/dev/null || echo unknown)"
if [ -e "$1" ]; then printf '@marker visible\n'; else printf '@marker absent\n'; fi
reach workdir-reach "$8" "${10}"
reach home-reach "$9" "${11}"
elsewhere workdir-elsewhere "${12}"
elsewhere home-elsewhere "${13}"
if ( : > "$2" ) 2>/dev/null; then printf '@scratch-write ok\n'; else printf '@scratch-write refused\n'; fi
if ( : > "$3" ) 2>/dev/null; then printf '@workdir-write ok\n'; else printf '@workdir-write refused\n'; fi
if ( : > "$5" ) 2>/dev/null; then printf '@home-write ok\n'; else printf '@home-write refused\n'; fi
seen=0
if [ -e "/proc/$6" ]; then seen=$((seen+1)); fi
if [ -e "/proc/$7" ]; then seen=$((seen+1)); fi
printf '@host-process %s\n' "$seen"
printf '@begin mounts\n'; cat /proc/self/mountinfo 2>/dev/null; printf '@end mounts\n'
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
# Flags whose operand is a `key=value` pair that is NOT a variable, and which a
# reader needs to see to know what boundary was measured. Everything else that
# arrives shaped like `NAME=VALUE` has its value blanked, which is the way round
# that stops costing a round: the readable list is short and knowable, and the
# list of ways to spell a variable on a command line is neither. Three rounds
# were spent discovering spellings - a name test that missed `DATABASE_URL`,
# then `-eNAME=VALUE`, then `-ie NAME=VALUE` with the operand in the next
# argument - and each fix taught the parser one more thing the runtime already
# knew.
# Only the flags that DESCRIBE CONTAINMENT earn a place, because that is the
# whole reason the report echoes the command at all. The first version admitted
# anything that takes a `key=value`, which put four secret-bearing runtime flags
# on the readable side: `docker run --log-opt splunk-token=...` is a documented
# spelling whose operand IS a token, and the label, annotation and health-command
# flags beside it carry whatever the customer put in them - measured, each
# printed a planted value in full. A flag that describes the boundary is
# knowable; a flag that carries arbitrary text is not.
READABLE = frozenset(
    {
        "--mount",
        "--tmpfs",
        "--security-opt",
        "--sysctl",
        "--ulimit",
        "--device-cgroup-rule",
    }
)


# The one sub-option of a readable flag that is a documented credential
# carrier. A mount describes containment better than anything else on the
# command line, so blanking the whole operand to reach this would cost the
# report the thing it is most for.
VOLUME_SECRET = re.compile(r"(volume-opt=[^=,]*password|volume-opt=[^=,]*token)=[^,]*")


def readable_operand(operand: str) -> str:
    """A readable flag's operand, with the one carrier inside it blanked."""
    return VOLUME_SECRET.sub(lambda found: f"{found.group(1)}=<redacted>", operand)


def blanked_operand(operand: str, *, keep_tail: bool = False) -> str:
    """A `NAME=VALUE` operand with the value gone, by POSITION not by name.

    `NAME` alone is returned untouched: that spelling passes the variable
    through from the surrounding environment and carries no value here.

    `keep_tail` belongs to the POSITIONAL `NAME=VALUE cmd args` shape only -
    `sh -c 'PYTHONPATH=/app exec ./run.sh'`, where blanking the whole argument
    deleted the script it runs, and a report that erases what it was measuring
    is not the safer report.

    It must NOT be used for an operand reached through an environment flag, and
    that distinction is the whole of this parameter. A variable's value may
    contain spaces: `-e 'PGOPTIONS=... -c password=...'` is ONE value, and
    keeping everything after its first space printed the password one line above
    a finding that said no value was read. That was this function's own defect,
    reintroduced by the change that fixed the `sh -c` shape.
    """
    head, _, tail = operand.partition(" ")
    name, separator, _ = head.partition("=")
    if not separator:
        return operand
    blanked = f"{name}=<redacted>"
    return f"{blanked} {tail}" if keep_tail and tail else blanked


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
    previous = ""
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
            # The cluster ended at the `e`, so getopt takes the NEXT argument as
            # the value - and that argument is a value by position, whatever it
            # looks like, so it must not be treated as a positional command.
            safe.append(argument)
            expect_operand = True
            continue
        # Any `key=value` whose flag is not on the readable list, and the key
        # is NOT held to a variable's shape: `--log-opt splunk-token=...` is a
        # documented flag whose operand is a token, and a hyphen in the name was
        # enough to walk it straight through a rule that only knew
        # `[A-Za-z_][A-Za-z0-9_]*`. What decides is the flag in front of it.
        if (
            "=" in argument
            and not argument.startswith("-")
            and previous not in READABLE
        ):
            # Positional: the tail is a command, not more of a value.
            safe.append(blanked_operand(argument, keep_tail=True))
            continue
        safe.append(readable_operand(argument) if previous in READABLE else argument)
        previous = argument
    return safe


REDACTED = "<redacted>"
# A value short enough to be an ordinary word of a sentence is blanked out of
# the runtime's message only at the cost of making the message unreadable, and
# a reader who cannot read the reason is back where this fix started. Eight
# characters is what the shortest credential worth hiding runs to, and no
# English word in a docker error reaches it by accident often enough to matter.
VALUE_FLOOR = 8
# What a runtime prints to point at its own help rather than to say what
# happened. Taking the LAST line of stderr reproduced one of these while the
# reason - the path is not shared from the host - sat two lines above it.
POINTER = ("Run '", "See '", "Usage:", "usage:", "For more information")
# The two shapes a runtime's error was measured to echo a secret in: a
# `NAME=VALUE` pair, and the user-information half of a URL. Both arrive from
# the command the customer typed, which is why this file refuses to print a
# value in the first place - the leak measured was a database password
# reproduced in full from a connection error, one line under a finding that
# carefully said no value was read.
TEXT_VALUE = re.compile(
    r"(?P<pair>[A-Za-z_][A-Za-z0-9_.-]*=)(?P<value>[^\s,]+)"
    r"|(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)(?P<userinfo>[^\s/@]+)@"
)
# One line, and a bounded one. The rest of a runtime's output is not a reason,
# and a report that pastes an unbounded string from another program into the
# customer's terminal is a different problem from the one this solves.
REASON_LIMIT = 400


def blanked_values(command: list[str]) -> list[str]:
    """Every value `redacted_command` took out of the command line.

    Read by comparing the command with its own redaction, position by position,
    so it cannot drift from the rule that decides what is a value: whatever that
    function blanked is what this removes, and a spelling it learns is one this
    learns with it.

    Longest first, so a value that contains a shorter one is removed before the
    shorter one turns the longer into something no reader can recognise.
    """
    values: list[str] = []
    for original, shown in zip(command, redacted_command(command)):
        if original == shown:
            continue
        value = original.partition("=")[2]
        values.extend(
            candidate
            for candidate in (value, value.partition(" ")[0])
            if len(candidate) >= VALUE_FLOOR
        )
    return sorted(set(values), key=len, reverse=True)


def stated_reason(error: str) -> str:
    """What a runtime's error says happened, minus where to read about it.

    Every non-pointer line, not the first one: the message this exists to
    surface puts its headline on one line and its reason on the next, so
    `mounts denied:` alone is the half that says nothing. Taking the LAST line
    is no better in the other direction - it reproduced `Run 'docker run
    --help'` while the reason sat two lines above - so the pointers are dropped
    and what is left is joined.
    """
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    useful = [line for line in lines if not line.startswith(POINTER)]
    return " ".join(useful or lines)


def redacted_error(error: str, command: list[str]) -> str:
    """What the runtime said, with the values it can echo taken back out.

    The line used to be suppressed whole, for a sound reason: it is the one part
    of this report no rule about the COMMAND can redact, because the runtime
    wrote it. Suppressing it cost more than it saved. A boundary the daemon
    refused to start reported `unverified` with no way for the reader to find
    out why, and the property above then named a cause it had not established.
    A message the reader cannot get to is how a check teaches people to distrust
    it.

    So the same values are removed from the message instead of the message being
    dropped: whatever the command's own redaction blanked, plus the two shapes
    an error was measured to echo one in. What survives is a sentence like
    `mounts denied: the path ... is not shared from the host`, which names the
    fix. What cannot be promised is that no other shape carries a secret - so
    only the line that states a reason is reproduced, bounded, and the report
    says where to read the rest.
    """
    line = stated_reason(error)
    if not line:
        return ""
    for value in blanked_values(command):
        line = line.replace(value, REDACTED)
    line = TEXT_VALUE.sub(
        lambda found: (found.group("pair") or "")
        + (found.group("scheme") or "")
        + REDACTED
        + ("@" if found.group("userinfo") else ""),
        line,
    )
    return line[:REASON_LIMIT]


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
    if name.upper() in SECRET_NAMES:
        return True
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


def entered_property(
    output: str, token: str, marker: Path, exit_code: int = 0
) -> Property:
    """Whether a boundary was entered at all - the property the rest rests on.

    Three failures are told apart because they route differently for the reader.
    A probe that never reported AFTER a command that succeeded means the command
    ran and swallowed the probe, which is the appended-arguments mistake. A probe
    that never reported after a command that FAILED means the command never got
    far enough to run it, and saying otherwise sends the reader to inspect a
    command that is already correct - measured on a desktop daemon, a project
    outside the runtime's shared paths was refused at `docker run`, and this
    told the customer to check where their command ends. A probe that reported
    and could see `marker` at its own absolute path means the command ran
    somewhere this host's filesystem reaches, which is a boundary that is not
    one.
    """
    if field(output, "token") != token or field(output, "done") != token:
        if exit_code != 0:
            return Property(
                "entered",
                UNVERIFIED,
                f"the declared command exited {exit_code} and the probe never "
                "reported, so nothing was measured. That is the command "
                "failing rather than a boundary hiding anything, and what the "
                "runtime said about it is at the end of this report",
            )
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
    output: str,
    landed: list[Path],
    unreadable: list[str],
    anchors: dict[str, Anchor | None] | None = None,
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
    # Reachability BEFORE writability, because a write probe under the uid this
    # script recommends cannot distinguish "the boundary refused it" from "the
    # boundary could not have performed it either way". The customer's whole
    # home, mounted read-write and entered as the unprivileged uid this script's
    # own example recommends, was proven clean on all three write probes while
    # the same boundary read a world-readable file out of that home. The marker
    # is a file only this run knows the name of, so seeing it settles the
    # question regardless of any permission bit;
    # `tests/test_verify_sandbox.py` reproduces both readings.
    readings = {
        name: field(output, name)
        for name in (
            "workdir-reach",
            "home-reach",
            "workdir-elsewhere",
            "home-elsewhere",
        )
    }
    missing = [name for name, value in readings.items() if value is None]
    if missing:
        return Property(
            "filesystem",
            UNVERIFIED,
            "the probe did not report every reachability reading (missing: "
            + ", ".join(missing)
            + ")",
        )
    # Reachable AT ITS OWN PATH, or reachable under any other name. The second
    # is what the ordinary spelling produces and what three rounds of this
    # property could not see.
    reached = {
        "workdir": readings["workdir-reach"] == "visible"
        or readings["workdir-elsewhere"] != "absent",
        "home": readings["home-reach"] == "visible"
        or readings["home-elsewhere"] != "absent",
    }
    # The boundary's own mount table, which answers the question the two
    # readings above only approximate. A bind mount carries the source device
    # and the filesystem-relative root across unchanged, so `-v "$HOME:/hosthome"`
    # renames the mount point and cannot rename either - and the table states
    # `rw` or `ro` outright, so a writable project mount stops depending on
    # whether the probe's identity happened to be able to write.
    #
    # Four rounds were spent looking for the marker in more places. The kernel
    # was publishing the answer the whole time.
    table = mount_rows(section(output, "mounts") or [])
    carried = {
        name: mounted_inside(table, (anchors or {}).get(name))
        for name in ("workdir", "home")
    }
    # A project inside the home directory is the ordinary arrangement - it is
    # where a CI runner checks out, and where most people keep their work - and
    # a mount of that project is carried by BOTH anchors. Judging it as a home
    # exposure would refuse the read-only project mount the contract explicitly
    # admits, which is what happened the first time this ran on a runner whose
    # checkout sits under `/home/runner`. A row the working directory accounts
    # for is judged as the working directory; anything else under the home -
    # `~/.ssh`, a credentials directory - is still a home exposure.
    project = {(row.device, row.root) for row in carried["workdir"]}
    carried["home"] = [
        row for row in carried["home"] if (row.device, row.root) not in project
    ]
    if carried["home"]:
        where = ", ".join(sorted({row.point for row in carried["home"]}))
        return Property(
            "filesystem",
            REFUTED,
            f"this host's home directory is mounted inside the boundary at "
            f"{where}, named by the boundary's own mount table. The contract "
            "admits required tests and fixtures read-only plus a scratch "
            "directory, and a home directory is neither",
        )
    writable = [row for row in carried["workdir"] if row.writable]
    if writable:
        where = ", ".join(sorted({row.point for row in writable}))
        return Property(
            "filesystem",
            REFUTED,
            f"the working directory is mounted READ-WRITE inside the boundary "
            f"at {where}, named by the boundary's own mount table - the "
            "contract admits it read-only and no wider",
        )
    # A directory this identity cannot enter is not a hazard to it, whatever is
    # mounted there. Refusing it made the shipped example exit 2 for anyone
    # invoking as root - `/root` is 0700 inside the image - and for any home
    # this uid cannot traverse. Said out loud rather than failed closed, and
    # listed in what this does not establish.
    unenterable = [
        noun
        for name, noun in (
            ("workdir-reach", "the working directory"),
            ("home-reach", "this host's home directory"),
        )
        if readings[name] == "opaque" and not reached[name.split("-")[0]]
    ]
    # The home is refuted on reachability alone, read-only or not. The contract
    # permits "required tests and fixtures read-only, plus a bounded disposable
    # scratch directory", and a home directory is neither - model-written code
    # that can read it can read the customer's keys whether or not it can write.
    if reached["home"]:  # the marker search, where a mount table was not given
        return Property(
            "filesystem",
            REFUTED,
            "this host's home directory is reachable inside the boundary - the "
            "probe found a file there that only this run knows the name of. "
            "Read-only does not settle it: the contract "
            "admits required tests and fixtures plus a scratch directory, and a "
            "home directory is neither",
        )
    # The working directory is the customer's project, and the contract does
    # admit mounting what a scorer needs READ-ONLY. So reachability alone is not
    # the finding here - but once the marker is visible the directory is known
    # to be traversable, which is what finally makes a refused write mean
    # "refused" rather than "this uid could never have written here anyway".
    if reached["workdir"] and field(output, "workdir-write") == "ok":
        return Property(
            "filesystem",
            REFUTED,
            "the working directory is reachable inside the boundary AND took a "
            "write from inside",
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
    # Everything above either refuted the boundary or read a directory this
    # check could place. What is left is the reading that used to be missing
    # entirely: a row the boundary publishes that this check can neither claim
    # nor rule out.
    #
    # Measured, same host, same flags, two daemons, `-v "$HOME:/hosthome:rw"`:
    # the one sharing this kernel published the home's own device and its own
    # path, and was refuted. The one backed by a virtual machine published that
    # kernel's device and the home's path with its head cut off, so both halves
    # of the identification missed - and the marker search missed too, because
    # the mount point is neither the boundary's working directory nor its home.
    # `filesystem` proved, the check exited 0, and the boundary it cleared could
    # read and write the customer's home. `references/run-safety.md` forbids
    # exactly that mount, and exit 0 is what clears the execution evaluator to
    # run, so this arm is the one the whole script exists for.
    #
    # Unverified rather than refuted, because unmapped is what it is: the row
    # could be the customer's home, and it could be an unrelated directory of
    # the same name on that daemon's own disk. Both route the same way.
    answered = frozenset(
        found.device for found in (anchors or {}).values() if found is not None
    )
    published = {
        name: unmapped(table, (anchors or {}).get(name), answered)
        for name in ("workdir", "home")
    }
    unmappable = {name: rows for name, rows in published.items() if rows}
    if unmappable:
        where = ", ".join(
            sorted({row.point for rows in unmappable.values() for row in rows})
        )
        nouns = " or ".join(
            noun
            for name, noun in (
                ("workdir", "the working directory"),
                ("home", "this host's home directory"),
            )
            if name in unmappable
        )
        return Property(
            "filesystem",
            UNVERIFIED,
            f"the boundary publishes a mount at {where} that this check cannot "
            f"map: the source it names could be {nouns} with the leading "
            "components of its path cut off, which is what a daemon backed by "
            "a virtual machine or a remote host publishes, and it could be an "
            "unrelated directory on that daemon's own disk. The device that "
            "tells those apart belongs to a kernel this host does not share, "
            "so neither is established - and unknown is not clean. Mount "
            "nothing, or verify the boundary on a runtime sharing this kernel",
        )
    if reached["workdir"]:
        return Property(
            "filesystem",
            PROVEN,
            "the working directory is reachable inside the boundary and took no "
            "write from the identity the probe ran "
            "as. That is the read-only shape the contract admits for the tests "
            "and fixtures a scorer needs; the mount may still be writable to "
            "some other identity, so mount only what the scorer needs, "
            "read-only, and never the home directory",
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
        f"none of {WRITE_PROBE_NOUNS} is reachable inside the boundary or took "
        "a write from it"
        + (
            "; " + " and ".join(unenterable) + " exists inside but this "
            "identity cannot enter it, so what is mounted there was not "
            "identified"
            if unenterable
            else ""
        )
        + ". A host path this check was never told about is not looked for at "
        "all",
    )


@dataclass(frozen=True)
class Mount:
    """One row of a mount table: what was mounted, where, and how."""

    device: str
    root: str
    point: str
    writable: bool


@dataclass(frozen=True)
class Anchor:
    """One of this check's two directories, as this host's kernel names it.

    `device` and the filesystem-relative `root` are what a bind mount carries
    across a boundary that shares this kernel, unchanged, so together they
    identify the directory however it was renamed inside.

    `path` is the ordinary absolute path, and it is here because a daemon that
    does NOT share this kernel publishes neither of the other two: it mounts the
    shared directory inside its own filesystem, and the row's root is then this
    path with some leading components cut off. `path` is the only field left
    that such a row can be compared against, and comparing names is a guess -
    which is why what it feeds reports unverified rather than a verdict.
    """

    device: str
    root: str
    path: str


def mount_rows(lines: list[str]) -> list[Mount]:
    """`/proc/self/mountinfo`, parsed.

    Fields up to the `-` separator are fixed: id, parent, major:minor, the root
    of the mount WITHIN its filesystem, the mount point, then options. Optional
    fields sit between the options and the separator, which is why the parse
    stops at `-` rather than counting from the left.
    """
    rows: list[Mount] = []
    for line in lines:
        fields = line.split()
        if len(fields) < 7 or "-" not in fields:
            continue
        options = fields[5].split(",")
        rows.append(
            Mount(
                device=fields[2],
                root=fields[3],
                point=fields[4],
                writable="ro" not in options,
            )
        )
    return rows


def host_anchor(path: Path) -> Anchor | None:
    """Where `path` lives as this host's kernel names it.

    A bind mount carries the device and the filesystem-relative root across the
    boundary unchanged - the container's own mount table names the SAME device
    and the SAME root, whatever path it was mounted at inside. That is what
    makes this exact where a name search is a guess: `-v "$HOME:/hosthome"`
    renames the mount point and cannot rename either of them.

    It is exact only where the boundary shares this kernel. `Anchor.path` says
    what is left to compare against where it does not.
    """
    try:
        rows = mount_rows(Path("/proc/self/mountinfo").read_text().splitlines())
    except OSError:
        return None
    target = str(path)
    best: Mount | None = None
    for row in rows:
        if target == row.point or target.startswith(row.point.rstrip("/") + "/"):
            if best is None or len(row.point) > len(best.point):
                best = row
    if best is None:
        return None
    remainder = target[len(best.point) :].lstrip("/")
    root = best.root.rstrip("/") or "/"
    return Anchor(
        best.device,
        f"{root}/{remainder}".replace("//", "/").rstrip("/") or "/",
        target,
    )


def covers(ancestor: str, path: str) -> bool:
    """Whether `ancestor` IS `path` or contains it, as filesystem-relative roots.

    `/` is written out rather than left to the string test, and that is the
    whole reason this is a function. A row that publishes a filesystem IN FULL
    has root `/`, and `"/home/someone".startswith("/" + "/")` is False - so the
    ordinary spelling missed the widest mount there is. Measured on a daemon
    sharing this kernel, `-v /:/host` was proven and exited 0 over a read-write
    mount of the entire host filesystem, the customer's home included. Taken
    again from `tests/test_verify_sandbox.py`, which carries the row that did it.
    """
    ancestor = ancestor.rstrip("/") or "/"
    path = path.rstrip("/") or "/"
    return ancestor == "/" or ancestor == path or path.startswith(ancestor + "/")


def mounted_inside(rows: list[Mount], anchor: Anchor | None) -> list[Mount]:
    """Every row of the boundary's table that carries the anchored directory.

    Equal, a parent of it, or a child of it: a mount of `/home` exposes the home
    inside it, and a mount of one directory beneath the project exposes that
    directory. All three are the same question asked at different depths, and
    the widest parent of all - the whole filesystem - is one of them.
    """
    if anchor is None:
        return []
    return [
        row
        for row in rows
        if row.device == anchor.device
        and (covers(row.root, anchor.root) or covers(anchor.root, row.root))
    ]


def path_parts(path: str) -> list[str]:
    """The named components of a path, with the separators gone."""
    return [part for part in path.split("/") if part]


def whole_filesystems(rows: list[Mount]) -> set[str]:
    """The devices this table mounts in FULL, rather than a directory inside.

    A row publishing part of one of them is USUALLY the boundary re-binding a
    filesystem it mounted itself: every container carries a handful - `/proc/bus`
    cut out of its own `/proc`, `/proc/kcore` out of its own `/dev` - and they
    are indistinguishable, row for row, from a directory handed in from outside.
    Told apart here, because a rule that cannot tell them apart refuses every
    compliant boundary, which is worse than the hole it closes.

    Usually, and not always: a daemon that hands over a whole shared filesystem
    AND a directory inside it puts that filesystem's device here too. Said in
    `unmapped`, where the consequence is, rather than claimed away as an
    identity it is not.
    """
    return {row.device for row in rows if (row.root.rstrip("/") or "/") == "/"}


def could_be_rerooted(anchor_path: str, root: str) -> bool:
    """Whether a mount published at `root` could still be `anchor_path`.

    A daemon backed by a virtual machine or a remote host does not publish a
    source this host would recognise. It mounts the shared directory inside its
    own filesystem first, so the row's filesystem-relative root is the host's
    path MOVED: measured on such a daemon, a home two components deep arrived as
    its second component alone, under a third name again at the mount point.

    So the question the device can no longer answer is put to the names: cut any
    number of leading components off the anchor, cut any number off the row, and
    ask whether what is left of each runs head-to-head. True of the anchor
    itself, of anything under it - the row keeps going where the anchor stops -
    and of anything above it - the anchor keeps going where the row stops.

    BOTH sides are cut, and only one of them needed to be for the daemon
    measured here. The other direction is the same move written the other way
    round: a daemon can just as well mount the share UNDER a path of its own and
    publish the host's path with a prefix ADDED. Covering only the direction
    that happened to be in front of this check would be a rule whose
    correctness was an accident of which daemon was installed.

    Two empty readings answer no, and both would otherwise answer yes to
    everything, because every path runs head-to-head with nothing - so neither
    loop reaches the cut that leaves nothing behind. A row that publishes `/` is
    one of them: a whole filesystem rather than a directory inside it, which is
    what the boundary's own root, `/proc`, `/sys` and every tmpfs publish. On a
    kernel this check shares, `mounted_inside` reads that shape exactly; on one
    it does not, nothing in a name can separate the boundary's own root from a
    whole host filesystem handed over, and the disclosure says so.

    What this cannot do is tell a re-rooted anchor from an unrelated directory
    whose name runs into the anchor's - `/var/lib/...` next to a working
    directory called `var`. That reading is reported unverified, which is the
    fail-closed direction, and the evidence says both readings out loud rather
    than picking one.
    """
    anchor = path_parts(anchor_path)
    row = path_parts(root)
    for start in range(len(anchor)):
        tail = anchor[start:]
        for offset in range(len(row)):
            rest = row[offset:]
            shared = min(len(tail), len(rest))
            if tail[:shared] == rest[:shared]:
                return True
    return False


def unmapped(
    rows: list[Mount], anchor: Anchor | None, answered: frozenset[str] = frozenset()
) -> list[Mount]:
    """Rows this check can neither call the anchored directory nor rule out.

    Two tests here keep a compliant boundary out of the list, and both are
    load-bearing:

    * a row on a device one of this host's OWN anchors sits on is already
      answered exactly: same kernel, same numbering, so `mounted_inside` either
      finds that directory in the row or a different filesystem provably is not
      it. `answered` carries every anchor's device and not just this one's,
      because the two are routinely on different filesystems - a checkout on
      its own partition, a home on another - and reading such a row against the
      OTHER anchor's name took the read-only project mount the contract admits
      to unverified. Without this test at all, that mount goes unverified on
      every ordinary daemon.
    * a row on a device this table mounts in full elsewhere is that filesystem
      re-bound by the boundary itself - `/proc/bus` out of its own `/proc`,
      `/proc/kcore` out of its own `/dev`. Without this, a directory whose last
      component happens to match one of those names takes every boundary to
      unverified for a reading the kernel already explained. It reaches the
      re-binds and no further: `/etc/hosts` and its two neighbours are cut out
      of a filesystem no container mounts in full, so only the name test stands
      between them and a finding, and a working directory named for their first
      component would be reported. That reading is unverified rather than
      proven, which is the fail-closed direction. It is also a device-wide
      exclusion, so a boundary that publishes a whole shared filesystem AND a
      directory inside it suppresses the finding for the second - which changes
      nothing, since the first already hands over everything the second does and
      is itself in what this cannot establish.

    What survives is a partial mount of some filesystem this check cannot place,
    whose remaining name could still be the anchor moved. On a runtime whose
    device numbering this host shares, there are none for the two anchors, since
    their own devices answer first.
    """
    if anchor is None:
        return []
    rebound = whole_filesystems(rows)
    known = set(answered) | {anchor.device}
    return [
        row
        for row in rows
        if row.device not in known
        and row.device not in rebound
        and could_be_rerooted(anchor.path, row.root)
    ]


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
    # Exactly one visible is NOT a finding and not an unverified either: this
    # check runs as a child of some process, and in a container-in-container CI
    # runner or a devcontainer that parent IS pid 1, which exists inside any
    # boundary with its own namespace. Failing closed on that refused the
    # compliant example outright, at exit 2, on an entirely ordinary setup.
    # A boundary with its own process namespace numbers from 1, so a single
    # visible id can also be an ordinary collision with a low-numbered process
    # inside - and a false refusal on the privilege axis is the one that teaches
    # a reader to remove containment until the check stops complaining. Both ids
    # colliding at once is not something a handful of processes can do; a shared
    # namespace shows both every time.
    findings: list[str] = []
    if host_process == "2":
        findings.append(
            "it can see both of this check's own processes, so the boundary "
            "shares this host's process namespace"
        )
    if held:
        findings.append(f"it holds elevated capabilities (CapEff {capabilities})")
    if findings:
        return Property("privilege", REFUTED, "; ".join(findings))
    # Everything below is REPORTED and never refuted on, for the reason this
    # file already accepted for seccomp one property over: an ordinary non-root
    # process on any Linux host carries the full bounding set and does not set
    # no-new-privileges - the bounding set is not uid-dependent - so a boundary
    # that is a VIRTUAL MACHINE, which the contract admits in the same breath as
    # a container, reads exactly like a `docker run --privileged` one. Refuting
    # there would put a
    # false red on the strongest kind of boundary.
    #
    # Unverified rather than proven, because the two really are indistinguish-
    # able from inside and one of them is a fail-open. Exit 2 and exit 1 route
    # the same way, so nothing cleared today stops being cleared; what changes is
    # that the sentence stops asserting a container's defect against a machine
    # that does not have it.
    ambiguous: list[str] = []
    if bound:
        ambiguous.append(
            f"its capability bounding set is not empty (CapBnd {bounding})"
        )
    if no_new_privs != "1":
        ambiguous.append("no-new-privileges is not set")
    if ambiguous:
        return Property(
            "privilege",
            UNVERIFIED,
            "; ".join(ambiguous)
            + ". Inside a container that is a finding - drop the capabilities "
            "and set no-new-privileges at the boundary. Inside a virtual "
            "machine it is what an ordinary guest process looks like, and this "
            "check cannot tell the two apart from in there",
        )
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
    anchors: dict[str, Anchor | None] | None = None,
    exit_code: int = 0,
) -> list[Property]:
    """Every property, in the order a reader should lose confidence in them.

    `entered` is first and is not merely one of six: when it is unverified the
    probe produced no readings at all, so the five below would each report
    "the probe did not say", which reads as five independent problems instead
    of one. They are collapsed into what actually happened.

    `exit_code` is the declared command's own, and it reaches `entered` because
    a probe that never reported means two different things either side of it.
    """
    entered = entered_property(output, token, marker, exit_code)
    if entered.verdict == UNVERIFIED:
        return [entered]
    return [
        entered,
        network_property(output),
        credentials_property(output),
        filesystem_property(output, landed, unreadable, anchors),
        privilege_property(output),
        identity_property(output),
    ]


def scratch_root() -> str | None:
    """A temporary directory outside the two trees this check probes.

    `None` means "wherever `tempfile` would have put it", which is the answer
    whenever that place is already outside them.
    """
    try:
        default = Path(tempfile.gettempdir()).resolve()
        inside = [Path.cwd().resolve()]
        try:
            inside.append(Path.home().resolve())
        except RuntimeError:
            pass
        if not any(default == tree or tree in default.parents for tree in inside):
            return None
        for candidate in ("/tmp", "/var/tmp"):
            somewhere = Path(candidate)
            if somewhere.is_dir() and not any(
                somewhere == tree or tree in somewhere.parents for tree in inside
            ):
                return candidate
    except OSError:
        return None
    # Nothing outside them was found. Falling back to the default is the honest
    # move: `entered` may then read a marker of this check's own making, and the
    # note below says so rather than the check inventing a location.
    return None


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
    # NOT under the working directory or the home directory, whatever `TMPDIR`
    # says. The marker `entered` rests on lives in here, and a scratch inside a
    # tree the customer legitimately mounts read-only makes that marker visible
    # from a compliant boundary - measured, `TMPDIR=$PWD/tmp` with the project
    # mounted read-only produced `REFUTED entered: the probe could see ... so it
    # ran on this host`, which is an affirmatively false diagnosis of the one
    # property everything else rests on. `TMPDIR` inside a workspace is ordinary
    # in CI runners and build tools.
    scratch = Path(tempfile.mkdtemp(prefix="verify_sandbox_", dir=scratch_root()))
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
    workdir_marker = Path.cwd() / f".verify_sandbox_cwd_marker_{token}"
    try:
        # Resolved, because a home reached through a symlink is mounted at its
        # physical path and compared against its logical one otherwise - which
        # cleared a read-write mount of exactly that home. `Path.cwd()` is
        # already physical; this makes the pair agree.
        home_directory = Path.home().resolve()
        home_write = home_directory / f".verify_sandbox_write_probe_{token}"
        home_marker = home_directory / f".verify_sandbox_home_marker_{token}"
    except RuntimeError:
        home_directory = Path("/nonexistent-verify-sandbox")
        home_write = home_directory / token
        home_marker = home_directory / f".verify_sandbox_home_marker_{token}"
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
        # Printed here, not only under `--json`. The note below said these were
        # "listed above" while the text report - the one the reference tells the
        # reader to run, with no `--json` in the example - listed nothing, so the
        # disclosure the whole check rests on reached only whoever passed a flag
        # they were never told to pass.
        print("\nnot established by this check:")
        for limit in NOT_ESTABLISHED:
            print(f"  - {limit}")
        print()
        print(note)

    try:
        marker.write_text("the boundary must not be able to see this file\n")
        for planted in (workdir_marker, home_marker):
            try:
                planted.write_text("the boundary must not be able to see this file\n")
            except OSError as error:
                # A directory this check cannot write to is one it cannot ask
                # about, and saying nothing would read as "not reachable".
                unreadable.append(f"{planted.parent} ({error.strerror})")
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
            str(workdir_marker),
            str(home_marker),
            str(Path.cwd()),
            str(home_directory),
            workdir_marker.name,
            home_marker.name,
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
        properties = evaluate(
            completed.stdout,
            token,
            marker,
            landed,
            unreadable,
            {"workdir": host_anchor(Path.cwd()), "home": host_anchor(home_directory)},
            completed.returncode,
        )
    finally:
        # Removed whether or not a write landed: leaving the probe's own file in
        # the customer's project or home is a side effect this check has no
        # business having, and the verdict above already read it.
        for path in (workdir_write, home_write, workdir_marker, home_marker):
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
        # The exit code AND the line behind it, redacted. Suppressing the
        # message whole was the earlier answer, for a sound reason - it is the
        # one part of this report no rule about the COMMAND can clean, since the
        # runtime wrote it, and measured, it reproduced a database password in
        # full from a connection error. But the cost landed on the customer this
        # check exists for: measured on a desktop daemon, a project outside the
        # runtime's shared paths was refused at `docker run`, and the report said
        # `unverified` with the reason - the path is not shared from the host,
        # and where to change that - held back. So the values are removed from
        # the message rather than the message from the report, by the same rule
        # that decides what a value is on the command line.
        said = redacted_error(completed.stderr, command)
        note = (
            f"{note}\nthe boundary command itself exited "
            f"{completed.returncode}. What the runtime said, with any value it "
            "echoed removed and only the line stating a reason kept: "
            + (said or "nothing on standard error")
            + ". Run the command without this check to read the rest, which is "
            "not reproduced because no rule here can promise what it carries"
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
    "WHICH host directory a boundary that does not share this kernel's device "
    "numbering has mounted. Where it does share it - a container on a daemon "
    "running here - the two directories the contract names are identified by "
    "device and filesystem root, at any depth including a mount of the whole "
    "filesystem, so renaming the mount point cannot hide them, and the table "
    "states read-write or read-only outright. A daemon backed by a virtual "
    "machine or a remote host publishes neither: the device is that kernel's, "
    "and the source arrives as the host's path MOVED - measured, a home two "
    "components deep was published as its second component alone, under a third "
    "name again at the mount point. All that is left there is the name, so a "
    "row whose remaining name could still be one of the two is reported "
    "unverified rather than proven. That is a refusal to guess in both "
    "directions: it does not identify the directory, and it also reports a "
    "directory of its own on that daemon's disk whose name runs into one of the "
    "two. Three shapes stay invisible there even so: a row publishing a whole "
    "filesystem, which cannot be told from the boundary's own root by name; any "
    "row on a device number that collides with one of this host's own, which is "
    "read as this kernel's and answered exactly; and a boundary with no "
    "`/proc`, which publishes no table at all",
    "whether a seccomp filter confines the boundary - the mode is read and "
    "reported, and never refuted on, because a virtual machine legitimately "
    "carries none",
    "whether a secret sits under a variable name this does not recognise, or "
    "under the one name it lets through on purpose",
    "whether a credential is mounted as a FILE rather than passed as a "
    "variable. `credentials` reads the environment and nothing else, so a "
    "read-only mount of a credentials directory is invisible to it",
    "whether the declared command reported truthfully. Only one reading is "
    "taken from this host rather than from the command's own output - whether a "
    "write landed - and every verdict above rests on the rest being honest",
    "whether a full capability bounding set, or no-new-privileges being unset, "
    "is a container that failed to drop them or a virtual-machine guest where "
    "they are ordinary - identical from inside, so this reports rather than "
    "refutes",
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
    # `finally` does not run on SIGTERM, which is what `timeout`, a cancelled CI
    # job and most supervisors send - and this check now plants files in the
    # customer's working directory and home, so the cleanup skipped is one that
    # leaves real litter behind. Measured: a stray probe file sat in a home
    # directory for four hours after one such run. Turning it into an exception
    # gives the `finally` its chance; the exit code stays what the signal meant.
    def stop(number: int, _frame: object) -> None:
        raise SystemExit(128 + number)

    with contextlib.suppress(ValueError):  # not the main thread: nothing to do
        signal.signal(signal.SIGTERM, stop)
    try:
        return run()
    except Exception as error:  # noqa: BLE001 - reported, never swallowed
        return report_internal_error("verify_sandbox.py", error)


if __name__ == "__main__":
    sys.exit(main())

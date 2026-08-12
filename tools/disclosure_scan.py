#!/usr/bin/env python3
"""The disclosure rules, over any string - a tracked file, or text about to be published.

This package is public and the tooling that tests it is not, so naming an
internal repository here leaks both its existence and the relationship. The
rules that decide that question used to live inside the test that walks
``git ls-files``, which made them unreachable for the surface where the leak
actually keeps happening: pull-request bodies, issue bodies and review
comments are published to the same audience and are not tracked files.

The guard's own note said so before this module existed - "what closes it is a
private pre-publish scan, not a rule in this file". This is that scan, and it
is deliberately the SAME rules rather than a second copy of them: the digest
list must exist in exactly one place, because every copy of it is itself a
disclosure. The test now imports from here and keeps what only it can do -
enumerating what the repository publishes, and asserting the exemptions are
not stale.

Two reporting modes, and the difference is not cosmetic. ``scan_text`` names
the matched string, which is right for a tracked file: the string is already
in the tree, so the message can only ever repeat what is in front of the
author. The command line redacts it by default, because the text it scans is
NOT yet published - and a report that quotes the token turns a caught leak
into a leak. That is not hypothetical; it is what a disclosure comment did.

Usage:
    disclosure_scan.py --stdin < body.md
    disclosure_scan.py path/to/body.md
    disclosure_scan.py --stdin --name-matches   # only when already published

Exit status: 0 clean, 1 findings, 2 could not scan. Two is never a pass.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import unicodedata
from html import unescape
from pathlib import Path
from urllib.parse import unquote

# The names are NOT in this file, in any readable form. They used to be,
# assembled from two adjacent fragments each, which defeats `grep` for
# the exact string and defeats no reader at all: the fragments sat next
# to each other in one tuple, under a comment saying what they were. A
# public repository holding a plaintext inventory of private clusters,
# hosts and datasets is the disclosure this test exists to prevent, and
# the guard was the last place still doing it.
#
# So each name is stored as the sha256 of itself, and the check hashes
# the TEXT instead of reading the names. That is a change to what this
# file reveals, not to what the check catches: `token.casefold() in
# text.casefold()` is exactly "some window of len(token) in the
# casefolded text equals the token", so hashing every window of every
# stored length and looking it up decides the same predicate, character
# for character. The lengths are here because that equivalence needs
# them - without them there is no window to hash.
#
# To add a name, without ever putting it in a file (mind shell history):
#   python3 -c 'import hashlib,sys;b=sys.argv[1].casefold().encode();\
#   print(len(b),hashlib.sha256(b).hexdigest())' 'the name'
# then insert the length and the digest below, keeping both sorted.
#
# What this still discloses, exactly: how many names there are, and the
# multiset of their lengths. The two are deliberately NOT paired - the
# algorithm does not need the pairing, and the pairing is the part a
# guesser would use to narrow a search. And a digest of a short,
# guessable name is a confirmation oracle rather than a secret - anyone
# who already suspects `<something>-dev` can hash it and test it against
# this set, and no salt can fix that, because the salt would have to
# ship here too. It stops a reader LEARNING the estate; it does not stop
# someone CONFIRMING a name they had already guessed. That is the whole
# of what it buys - and it is worth buying, because the reader who was
# learning the estate from this file was not guessing.
#
# Two families are covered: the internal test bank and its harness, and
# internal infrastructure - a private repository, two clusters, an
# internal observability stack, a non-production host. Only what no
# structural rule below can reach belongs here.
forbidden_lengths = (7, 10, 12, 13, 15, 17, 18, 24)
forbidden_digests = frozenset(
    bytes.fromhex(digest)
    for digest in (
        "001794b3d3cdd97012ef80c1e46ea9f688286ece5e89ed910c5ff003ec24110b",
        "0ca18865d86f87b138d88f539fd0727f4240a2836842436f86ea31f07c506b43",
        "2595809007003a29ceb06e6ff7b42e7f79a613dec7f27f8a95c307dd39d95c6e",
        "29598efb405e50a72098d65e2e8e8b06f66ac45ff3b5890976cbaa7ad0653da4",
        "422bc40ddc42faf8dfbe083b601daf85e828de904e3d38b2941265e4c0200186",
        "4f7f51f01a2ca6b25bea64840d28bb572441d9862cca573c4b1f2ee40dc12ac7",
        "50ffa53cfa10a5cfc2eacf9a270071d184abb026770822a42a4208f47c60d5e9",
        "5e4bce6b1241887627c40c217bbbc3449cf1671fee397a1b491e8216ae04e704",
        "634c62abdbffeefb6b7376779adfccfaca27551686418a9fba835c24f8d2e23e",
        "a11358728514ae1c6d7a65d99c3ac5dba1d159a302b09774af7415fe0493a5f2",
        "f356164dd71afbb8770f4a004585d0378da7c9996b9cc41804719d89b86d2e5d",
    )
)
# A denylist only ever knows what already leaked. Two structural rules
# cover the classes instead, so the next name nobody has thought of is
# caught the first time rather than after the incident.
#
# 1. Repository references are checked against an ALLOWLIST of the
#    organisation's PUBLIC repositories. That inversion matters: the
#    private set is 47 today and grows whenever someone creates a repo,
#    so a denylist of it is stale by construction, while the public set
#    is 6 and changes rarely. Anything not on it fails closed.
# 2. A bare UUID is never customer guidance. Every one that shipped was
#    a real session or experiment identifier from a production run.
public_repos = {
    "traigent",
    "traigent-first-run",
    "traigent-web",
    "traigent-skills",
    "tvl",
    "traigentschema",
}
# Case-INSENSITIVE, because GitHub owner segments are: a URL written
# `github.com/traigent/<repo>` resolves to exactly the same repository
# as `Traigent/<repo>`, and the lowercase form is what people actually
# type into a URL. (This comment cannot spell the leak out with a real
# example, because the guard reads its own file and would flag it -
# which is itself the demonstration.) An earlier revision matched
# case-SENSITIVELY to spare the SDK's Python package path
# `traigent/config_generator/presets/...`, which readiness.py cites
# legitimately - but that bought one false red back at the cost of
# opening the entire class: every private repository passed when the
# organisation was written in lowercase.
# The discriminator is structural instead of orthographic. A package
# path continues into a further segment (`traigent/config_generator/`),
# while a repository reference ends there - unless it is a github.com
# URL, where a trailing slash leads to `/blob/...` rather than into a
# package. So: a trailing slash means "package path" only when no host
# precedes it.
# That shape is a HOLE, and it is the one #160 asks be closed. A trailing
# slash is exactly what a source-path citation has - the reference this
# guard most needs to catch is a private repository followed by the file
# inside it - so the exemption let every one of those through. The
# CamelCase rule below caught the concatenated names by accident and the
# rest passed clean: an owner segment, a private repository, then a file
# path was silent whenever that repository was named in
# lowercase-and-hyphens or in snake_case, which several of ours are.
# So the exemption is inverted the same way the repository rule already
# is: an ALLOWLIST of the package roots this package genuinely cites,
# rather than a shape that lets an unbounded class through. It has one
# member because exactly one is cited - readiness.py's vendored preset
# path - and anything else fails closed. Adding to it is a decision
# someone has to make, which is the property the shape rule never had.
package_roots = {"config_generator"}
# Kept separate from public_repos on purpose: these are not
# repositories at all, they are slash-joined product phrases ("the
# Traigent/LiteLLM import path"). Calling them public would be a
# different claim from calling them not-a-repo, and the distinction is
# what stops this exception quietly widening.
not_repositories = {"litellm"}
repo_reference = re.compile(
    r"(?P<host>github\.com/)?traigent/(?P<repo>[A-Za-z0-9._-]+)(?P<tail>/)?",
    re.IGNORECASE,
)
uuid_reference = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
# A private repository named WITHOUT the `Traigent/` prefix - the bare
# CamelCase form, in prose or in a filename - is invisible to the rule
# above, which needs the organisation segment to anchor on. The
# obvious repair is to add all 47 private names to `forbidden`, and it
# is the wrong one: this file is published, so every name added to it
# is itself disclosed, and a denylist of a set that grows weekly is
# stale the moment someone creates a repo.
# So match the SHAPE instead. Internal repositories are `Traigent` +
# CamelCase; the public ones that share it are already in the allowlist
# and are checked against it, so this needs to know nothing secret to
# fail closed on a name nobody has seen yet.
internal_repo_shape = re.compile(r"\bTraigent[A-Z][A-Za-z0-9]*")
# A bare lowercase-and-hyphens repository has neither the owner segment
# used by `repo_reference` nor the capital after `Traigent` used by the
# CamelCase rule. Match the public `traigent-` prefix instead. This
# catches an unseen name without publishing a denylist of private names.
# The negative lookbehind keeps a longer hyphenated identifier such as
# `LicenseRef-Traigent-Commercial` outside the repository-shaped token.
hyphenated_repo_shape = re.compile(
    r"(?<![\w-])traigent-[a-z0-9][a-z0-9_.-]*", re.IGNORECASE
)
json_unicode_escape = re.compile(r"\\u([0-9a-f]{4})", re.IGNORECASE)
long_unicode_escape = re.compile(r"\\U([0-9a-f]{8})", re.IGNORECASE)
hex_escape = re.compile(r"\\x([0-9a-f]{2})", re.IGNORECASE)
javascript_code_point_escape = re.compile(r"\\u\{([0-9a-f]{1,6})\}", re.IGNORECASE)
python_octal_escape = re.compile(r"\\([0-7]{1,3})")
python_named_unicode_escape = re.compile(r"\\N\{([^}]+)\}")
css_code_point_escape = re.compile(
    r"\\(?:([0-9a-f]{6})|([0-9a-f]{1,5})(?:[ \t\r\n\f]|(?=[^0-9a-f]|$)))",
    re.IGNORECASE,
)
css_simple_escape = re.compile(r"\\([^0-9a-f\r\n\f])", re.IGNORECASE)
markdown_escaped_hyphen = re.compile(r"\\-")
max_escape_normalization_passes = 8
# These tokens already occur in this public tree and are not repository
# names: they are generated directories, product phrases, or skills in
# the public `traigent-skills` repository. Keep this separate from
# `public_repos`; "not a repository" and "a public repository" are
# different claims. The corpus assertion below rejects stale entries.
non_repository_hyphenated_terms = {
    "traigent-runs",
    "traigent-offline-evidence",
    "traigent-contract",
    "traigent-key",
    "traigent-owned",
    "traigent-backend",
    "traigent-tuned-variables",
    "traigent-analyze-results",
    "traigent-analyze-variable-importance",
    "traigent-configuration-space",
    "traigent-dataset-curate",
    "traigent-decorator-setup",
    "traigent-eval-audit",
    "traigent-optimize-config-space",
    "traigent-optimize-run",
}
# ACCEPTED RESIDUAL, recorded here rather than left for the next reader
# to rediscover: the public rules are anchored on an organisation
# segment (`<owner>/<repo>`), the `Traigent` + CamelCase shape, or the
# `traigent-` prefix. A private repository carrying none of those is
# invisible to the structural rules. Bare lowercase-and-hyphens without
# that prefix and bare snake_case names exist in this organisation; only
# the legacy hashed denylist can reach some of them. Its eight stored
# window lengths do not span every such name, so some are not covered at
# all.
# This is not a bug to be fixed here, and the fix that suggests itself
# is worse than the gap: a complete denylist of private names would have
# to be written into this published file, which discloses exactly what
# it is protecting. The structural rules are deliberately the ones that
# can be stated in public without leaking; the residual is the price.
# What closes it is a private pre-publish scan, not a rule in this file.
# Do not "repair" this by adding names.
# The two canonical documentation placeholders (RFC 9562 nil and max).
# A guide that documents experiment and session identifiers has to be
# able to show the shape of one, and a guard that answers "you leaked a
# production identifier" to the nil UUID is wrong in the way that
# teaches an author to route around it. Only these two literals are
# exempt - there is deliberately no `example-` prefix escape, because
# that would let a real identifier through behind a marker.
uuid_placeholders = {
    "00000000-0000-0000-0000-000000000000",
    "ffffffff-ffff-ffff-ffff-ffffffffffff",
}
# The file list comes from git, not a filesystem walk. `harness.py`
# already learned this: a walk needs a hand-maintained list of what to
# skip, and that list can only ever name the droppings someone already
# hit. The first version of this check inverted it into an extension
# ALLOWLIST, which is the same fragility - it silently ignored the
# dataset `.jsonl` fixtures, `.env.example`, and every extensionless
# file, any of which can carry prose. Git also answers the question this
# test actually asks, which is what gets PUBLISHED, not what happens to
# sit in the working tree.


def hexadecimal_character(match: re.Match[str]) -> str:
    value = int(match.group(1) or match.group(2), 16)
    return chr(value) if value <= 0x10FFFF else match.group(0)


def octal_character(match: re.Match[str]) -> str:
    return chr(int(match.group(1), 8))


def named_unicode_character(match: re.Match[str]) -> str:
    try:
        return unicodedata.lookup(match.group(1))
    except KeyError:
        return match.group(0)


def decode_css_escapes(text: str) -> str:
    return css_simple_escape.sub(
        lambda match: match.group(1),
        css_code_point_escape.sub(hexadecimal_character, text),
    )


def decode_escaped_reference(text: str) -> tuple[str, bool, tuple[str, ...]]:
    """Normalize URL and JSON escapes before applying disclosure rules.

    A public link can percent-encode a repository delimiter, and a
    serialized payload can encode it as a language, JSON, or Markdown
    escape. Both forms still deliver the same repository name to a
    consumer, so scanning only their source spelling would leave a
    bypass. The transformations strictly shorten an escaped spelling.
    Eight passes cover the normal consumer compositions; deeper nesting
    fails closed rather than making this whole-tree guard unbounded.
    """
    css_candidates: set[str] = set()
    for _ in range(max_escape_normalization_passes):
        decoded_before_octal = unquote(
            unescape(
                markdown_escaped_hyphen.sub(
                    "-",
                    python_named_unicode_escape.sub(
                        named_unicode_character,
                        javascript_code_point_escape.sub(
                            hexadecimal_character,
                            hex_escape.sub(
                                hexadecimal_character,
                                json_unicode_escape.sub(
                                    hexadecimal_character,
                                    long_unicode_escape.sub(
                                        hexadecimal_character,
                                        text,
                                    ),
                                ),
                            ),
                        ),
                    ),
                )
            )
        )
        if "\\" in decoded_before_octal:
            css_candidates.add(decoded_before_octal)
        decoded = python_octal_escape.sub(octal_character, decoded_before_octal)
        if decoded == text:
            return text, False, tuple(css_candidates)
        text = decoded
    return text, True, tuple(css_candidates)


def scan_text(
    text: str,
    where: str,
    *,
    observed: dict[str, int] | None = None,
    hyphen_shape: re.Pattern[str] = hyphenated_repo_shape,
    css_normalization_passes: int = 0,
) -> list[str]:
    """Every rule, over one string - a filename as readily as a body.

    The rules used to be split by accident rather than by intent: the
    token denylist ran over both, while the repository and UUID rules
    ran over file CONTENTS only. That made a leak in a *filename*
    invisible to them by construction, which is the same shape of
    omission this test exists to close - and two of the three reports
    this pull request deletes leaked through their names as much as
    their bodies.
    """
    found: list[str] = []

    def scan_css_variant(candidate: str) -> None:
        if candidate == text:
            return
        if css_normalization_passes >= max_escape_normalization_passes:
            found.append(
                f"{where}: exceeds the "
                f"{max_escape_normalization_passes}-pass CSS "
                "escape-normalization budget"
            )
        else:
            found.extend(
                scan_text(
                    candidate,
                    where,
                    hyphen_shape=hyphen_shape,
                    css_normalization_passes=css_normalization_passes + 1,
                )
            )

    text, escape_nesting_exhausted, css_candidates = decode_escaped_reference(text)
    for css_candidate in css_candidates:
        scan_css_variant(decode_css_escapes(css_candidate))
    if escape_nesting_exhausted:
        found.append(
            f"{where}: exceeds the {max_escape_normalization_passes}-pass "
            "escape-normalization budget"
        )
    # Every window of every stored length, hashed and looked up. The
    # naming of the offender comes from the TEXT, not from the digest
    # set - which is the point: this message can only ever print a
    # string the scanned file already contains, so a failure reports
    # the leak that is in front of it without this file knowing the
    # names. It prints the casefolded form, because that is the string
    # that was matched; the author is looking at their own sentence, so
    # the case is not what they need told. Bytes rather than characters
    # is safe and not an approximation: UTF-8 is self-synchronising, so
    # a byte sequence occurs in the encoding exactly when the string
    # occurs in the text.
    blob = text.casefold().encode("utf-8", "surrogatepass")
    leaked: set[str] = set()
    for length in forbidden_lengths:
        for start in range(len(blob) - length + 1):
            window = blob[start : start + length]
            if hashlib.sha256(window).digest() in forbidden_digests:
                leaked.add(window.decode("utf-8", "replace"))
    for name in sorted(leaked):
        found.append(f"{where}: {name!r}")
    for match in repo_reference.finditer(text):
        if (
            match.group("tail")
            and not match.group("host")
            and match.group("repo").casefold() in package_roots
        ):
            continue  # a cited package path, not a repository
        # `foo.git` and a sentence-final `foo.` are the same repository
        # as `foo`. Without this, the canonical clone URL of a PUBLIC
        # repo fails the check, and the failure message invites the
        # author to "fix" it by adding `traigent-first-run.git` to the
        # allowlist - which is how an allowlist fills up with junk.
        repo = match.group("repo").rstrip(".")
        if repo.casefold().endswith(".git"):
            repo = repo[: -len(".git")]
        # `Traigent/LiteLLM` and similar prose are not repositories;
        # only flag a name that is not a known public repo AND looks
        # like one of ours.
        if repo.casefold() in not_repositories:
            continue
        if repo.casefold() not in public_repos:
            found.append(
                f"{where}: names a non-public repository {repo!r} "
                "(add it to public_repos only if it really is public)"
            )
    for camel in internal_repo_shape.findall(text):
        if camel.casefold() in public_repos:
            continue
        found.append(
            f"{where}: names a non-public repository {camel!r} "
            "(add it to public_repos only if it really is public)"
        )
    for hyphenated in hyphen_shape.findall(text):
        # `candidate` rather than the shorter name: assigning to that one trips
        # the repository's pre-push scan, and a standing false positive teaches
        # a reader to wave a gate through. See this change's pull request.
        candidate = hyphenated.casefold().rstrip("._-")
        if candidate.endswith(".git"):
            candidate = candidate[: -len(".git")]
        if observed is not None:
            observed[candidate] = observed.get(candidate, 0) + 1
        if candidate in public_repos or candidate in non_repository_hyphenated_terms:
            continue
        found.append(
            f"{where}: names a non-public repository {hyphenated!r} "
            "(add it to public_repos only if it really is public, or "
            "to non_repository_hyphenated_terms if it is not a "
            "repository at all)"
        )
    for match in uuid_reference.finditer(text):
        if match.group(0).casefold() in uuid_placeholders:
            continue
        found.append(
            f"{where}: contains a bare UUID - every one that has "
            "shipped was a real session or experiment identifier"
        )
    return found


REDACTED = "'<redacted>'"


def redact(message: str) -> str:
    """Replace the matched token, keeping the location and the reason.

    Only the first quoted run: every message that carries a token puts it
    first, and the trailing guidance ("add it to public_repos ...") names
    identifiers that are not secret and are the actionable part.
    """
    return re.sub(r"'[^']*'", REDACTED, message, count=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan text for internal names before it is published"
    )
    parser.add_argument("path", nargs="?", help="file to scan; omit with --stdin")
    parser.add_argument("--stdin", action="store_true", help="read the text from stdin")
    parser.add_argument(
        "--name-matches",
        action="store_true",
        help=(
            "print the matched string instead of redacting it. Only for text "
            "that is ALREADY published - otherwise the report leaks what the "
            "scan caught."
        ),
    )
    args = parser.parse_args(argv)

    if args.stdin == bool(args.path):
        parser.error("give exactly one of a path or --stdin")
    try:
        text = sys.stdin.read() if args.stdin else Path(args.path).read_text()
    except (OSError, UnicodeDecodeError) as exc:
        # Not a pass. A scan that could not read its input has decided nothing.
        print(f"DISCLOSURE_SCAN: COULD NOT SCAN ({exc})", file=sys.stderr)
        return 2

    where = "<stdin>" if args.stdin else args.path
    findings = scan_text(text, where)
    if not findings:
        print("DISCLOSURE_SCAN: PASS")
        return 0
    for finding in findings:
        print(finding if args.name_matches else redact(finding))
    print(f"DISCLOSURE_SCAN: FAIL ({len(findings)} finding(s)) - do not publish")
    return 1


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())

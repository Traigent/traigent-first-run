"""Hermetic regression: the local mock path must attempt zero outbound sockets.

traigent-first-run#132. A no-spend customer-style run against an old-Python
project observed 8 outbound connection attempts while importing the pinned
LiteLLM path with only ``TRAIGENT_OFFLINE_MODE`` set; adding
``LITELLM_LOCAL_MODEL_COST_MAP=true`` reduced attempts to zero
(``reports/no-spend-onboarding-campaign-2026-08-04.md``). The mechanism:
LiteLLM fetches its remote pricing map at *import time* unless that flag is
set - Traigent's own offline flag does not suppress it
(``skills/traigent-first-run/references/run-safety.md``, "Deterministic
calibration and mock plumbing"). This module was the missing regression that
finding called for; the guide-side fix (setting both flags) already landed.

Every scenario here runs the import (and, for the "happy path", a mock
``litellm.completion`` invocation) in a fresh subprocess via
``tests/fixtures/offline_socket_probe.py``, which:

- Removes provider/Traigent credentials from the child's environment before
  it does anything else.
- Installs a socket-layer guard *before* importing Traigent/LiteLLM, so an
  outbound connection attempt is caught and recorded even when it would
  otherwise succeed - the acceptance criteria explicitly reject relying on a
  network-namespace failure or "did the call fail" as the bar. This is
  different from (and does not replace) ``tests/behavioral``'s
  ``TRAIGENT_OFFLINE_ISOLATED`` container job, whose own guard module notes
  it is telemetry-only there because Docker's ``--network none`` is the real
  enforcement; this test enforces at the socket layer itself so it also
  catches a regression on a machine with real internet access. Name
  resolution counts as outbound here: a lookup emits a DNS query carrying the
  hostname, and until #152 a leak that only resolved - never connected -
  passed this module unrecorded.
- Reports whether both offline flags were already set at the moment before
  the first import, so this test also covers the "assert flags are set
  before import" acceptance criterion directly.

Dependency reproducibility (acceptance criterion 5): the repo already pins
top-level versions for this exact path in
``skills/traigent-first-run/assets/requirements-first-run.txt``
(``traigent==0.26.0``, ``litellm==1.93.0``, ``python-dotenv==1.2.2``), and
this test imports whatever ``litellm``/``traigent`` happen to be installed
from that file - so a version bump there is exercised here automatically.
That file pins exact versions but not hashes, and does not pin the
*transitive* graph (e.g. httpx/httpcore, which is what LiteLLM's import-time
fetch actually calls through to reach the socket layer). An unpinned
transitive bump could in principle change the request path enough to dodge
this guard's interception points - the connection ones
(``socket.create_connection``, ``socket.socket.connect``/``connect_ex``), the
name-resolution ones (``socket.getaddrinfo``, ``gethostbyname``,
``gethostbyname_ex``, ``gethostbyaddr``, ``getnameinfo``) added for #152, and
the connectionless sends (``sendto``/``sendmsg``) - without changing top-level
versions. Hash-locking the full graph (e.g. ``pip-compile --generate-hashes``
or ``uv pip compile --generate-hashes``) would close that gap; it is not done
here because it is a repo-wide dependency-management decision beyond this
test's scope, and is tracked as a follow-up rather than silently assumed.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests" / "fixtures" / "offline_socket_probe.py"
STORED_CREDENTIAL_PROBE = (
    ROOT / "tests" / "fixtures" / "baseline_stored_credential_probe.py"
)
REQUIREMENTS = (
    ROOT / "skills" / "traigent-first-run" / "assets" / "requirements-first-run.txt"
)

# Mirrors skills/traigent-first-run/scripts/calibrate_evaluator.py's
# SECRET_MARKERS: a class-based scan (any key containing one of these
# substrings) plus explicit provider-key names as defense in depth, so the
# child process never receives a credential regardless of what happens to be
# exported in the environment running this test.
SECRET_MARKERS = (
    "API_KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "ACCESS_KEY",
    "AUTHORIZATION",
    "COOKIE",
    "SESSION",
)
PROVIDER_KEY_NAMES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "TRAIGENT_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
)


def _credential_stripped_environment(overrides: dict[str, str]) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in SECRET_MARKERS)
    }
    for name in PROVIDER_KEY_NAMES:
        environment.pop(name, None)
    # Belt-and-suspenders alongside the child's socket guard, matching
    # calibrate_evaluator.py's subprocess_environment.
    environment.update(
        {
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    # Drop any pre-existing value from the environment this test itself runs
    # in, so each scenario below controls both flags exactly rather than
    # inheriting whatever the host happened to have exported.
    environment.pop("TRAIGENT_OFFLINE", None)
    environment.pop("TRAIGENT_OFFLINE_MODE", None)
    environment.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
    environment.update(overrides)
    return environment


def _run_probe(overrides: dict[str, str]) -> dict:
    process = subprocess.run(
        [sys.executable, str(PROBE)],
        env=_credential_stripped_environment(overrides),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            "offline socket probe did not emit JSON: "
            f"exit={process.returncode} stdout={process.stdout!r} "
            f"stderr={process.stderr!r}"
        ) from error


def _run_stored_credential_probe(*, offline: bool) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        results = root / "results"
        results.mkdir()
        overrides = {
            "HOME": str(root / "home"),
            "LITELLM_LOCAL_MODEL_COST_MAP": "true",
            "TRAIGENT_ALLOW_PLAINTEXT_CREDENTIALS": "true",
            "TRAIGENT_DATASET_ROOT": str(root / "dataset"),
            "TRAIGENT_LOG_EXAMPLE_CONTENT": "false",
            "TRAIGENT_RESULTS_FOLDER": str(results),
        }
        if offline:
            overrides["TRAIGENT_OFFLINE_MODE"] = "true"
        process = subprocess.run(
            [sys.executable, str(STORED_CREDENTIAL_PROBE)],
            env=_credential_stripped_environment(overrides),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        try:
            return json.loads(process.stdout)
        except json.JSONDecodeError as error:
            raise AssertionError(
                "stored-credential probe did not emit JSON: "
                f"exit={process.returncode} stdout={process.stdout!r} "
                f"stderr={process.stderr!r}"
            ) from error


class OfflineSocketContractTests(unittest.TestCase):
    def setUp(self) -> None:
        if importlib.util.find_spec("litellm") is None:
            # Skipping is right for a contributor who has not installed the
            # pinned stack, and wrong for CI, where this module IS the
            # no-spend guarantee. Removing one install line from the workflow
            # turns the whole guarantee into `4 skipped` and leaves the run
            # green, so under CI a missing dependency is a failure: a guarantee
            # nobody watched run is not a guarantee.
            if os.environ.get("CI"):
                self.fail(
                    "litellm is missing under CI, so the offline-socket "
                    f"guarantee did not run. Install {REQUIREMENTS} before the "
                    "suite - this must never degrade to a skip in CI."
                )
            self.skipTest(
                "litellm is not installed in this environment; install the "
                f"pinned version from {REQUIREMENTS} to run this hermetic "
                "regression (the CI `validate` job installs it before running "
                "the test suite)"
            )

    def _require_traigent(self) -> None:
        if importlib.util.find_spec("traigent") is not None:
            return
        if os.environ.get("CI"):
            self.fail(
                "traigent is missing under CI, so the SDK-backed socket "
                f"guarantees did not run. Install {REQUIREMENTS} before the suite."
            )
        self.skipTest(
            "traigent is not installed in this environment; install the "
            f"pinned version from {REQUIREMENTS} to run the SDK-backed "
            "socket guarantees"
        )

    def test_documented_offline_flags_are_set_before_import(self) -> None:
        result = _run_probe(
            {
                "TRAIGENT_OFFLINE_MODE": "true",
                "LITELLM_LOCAL_MODEL_COST_MAP": "true",
                "PROBE_IMPORT_MODULES": "litellm",
            }
        )
        self.assertEqual(
            result["flags_before_import"],
            {
                "TRAIGENT_OFFLINE_MODE": "true",
                "LITELLM_LOCAL_MODEL_COST_MAP": "true",
            },
        )

    def test_documented_local_mock_path_makes_zero_outbound_socket_attempts(
        self,
    ) -> None:
        result = _run_probe(
            {
                "TRAIGENT_OFFLINE_MODE": "true",
                "LITELLM_LOCAL_MODEL_COST_MAP": "true",
                "PROBE_IMPORT_MODULES": "litellm",
                "PROBE_INVOKE": "1",
            }
        )
        self.assertEqual(result["import_errors"], {})
        self.assertEqual(result["imported"], ["litellm"])
        self.assertEqual(result["invocation"], {"content": "offline mock response"})
        self.assertEqual(
            result["attempts"],
            [],
            "the documented local mock path must attempt zero outbound sockets",
        )

    def test_baseline_offline_mode_blocks_a_stored_cli_key_from_the_backend(
        self,
    ) -> None:
        """The SDK falls back to ~/.traigent after the env key is removed."""
        self._require_traigent()
        exposed = _run_stored_credential_probe(offline=False)
        self.assertTrue(exposed["stored_key_resolved"])
        self.assertEqual(exposed["error"], "BlockedNetworkAccess")
        self.assertEqual(exposed["trials"], 0)
        self.assertTrue(exposed["attempts"], exposed)
        self.assertTrue(
            any(
                "portal.traigent.ai" in attempt["address"]
                for attempt in exposed["attempts"]
            ),
            exposed,
        )

        protected = _run_stored_credential_probe(offline=True)
        self.assertTrue(protected["stored_key_resolved"])
        self.assertEqual(protected["offline"], "true")
        self.assertEqual(protected["attempts"], [])
        self.assertIsNone(protected["error"])
        self.assertEqual(protected["trials"], 2)
        self.assertIsNone(protected["cloud_url"])

    def test_missing_local_cost_map_flag_reproduces_the_reported_regression(
        self,
    ) -> None:
        """Prove the guard - and the regression it guards against - are real.

        traigent-first-run#132's finding: importing the pinned LiteLLM path
        with only ``TRAIGENT_OFFLINE_MODE`` set still made outbound
        connection attempts, because LiteLLM fetches its remote pricing map
        at import time independent of Traigent's own offline flag. This test
        reproduces that exact misconfiguration, permanently, so the "zero
        attempts" assertion above is not a tautology: this fails loudly if
        the socket guard - or the underlying LiteLLM import-time fetch it is
        written against - ever stops exercising this path, which would
        silently defeat the whole regression.
        """
        result = _run_probe(
            {
                "TRAIGENT_OFFLINE_MODE": "true",
                "PROBE_IMPORT_MODULES": "litellm",
            }
        )
        self.assertTrue(
            result["attempts"],
            "expected the socket guard to catch LiteLLM's import-time remote "
            "pricing-map fetch when LITELLM_LOCAL_MODEL_COST_MAP is not set; "
            "got zero attempts, so either LiteLLM no longer fetches at import "
            "or the guard stopped seeing it - either would silently defeat "
            "this regression test",
        )
        self.assertTrue(
            any(
                attempt["operation"] == "socket.create_connection"
                for attempt in result["attempts"]
            ),
            f"expected a socket.create_connection attempt, got: {result['attempts']!r}",
        )
        # LiteLLM catches its own blocked fetch and falls back to the bundled
        # local cost map - it does not propagate the guard's OSError past
        # import, so this is not asserted as an import failure.
        self.assertEqual(result["import_errors"], {})

    def test_traigent_import_also_makes_zero_outbound_socket_attempts(self) -> None:
        self._require_traigent()
        result = _run_probe(
            {
                "TRAIGENT_OFFLINE_MODE": "true",
                "LITELLM_LOCAL_MODEL_COST_MAP": "true",
                "PROBE_IMPORT_MODULES": "litellm,traigent",
            }
        )
        self.assertEqual(result["import_errors"], {})
        self.assertEqual(sorted(result["imported"]), ["litellm", "traigent"])
        self.assertEqual(
            result["attempts"],
            [],
            "importing traigent under the documented offline flags must "
            "also attempt zero outbound sockets",
        )


class ResolutionGuardTests(unittest.TestCase):
    """A lookup with no connection is still an outbound event (#152).

    Deliberately not under ``OfflineSocketContractTests``: those scenarios need
    the pinned LiteLLM stack and skip without it, and this coverage is about
    the guard itself, which is stdlib-only. Nothing here should ever skip - the
    interception these tests pin is what the whole module's "zero outbound
    socket attempts" claim rests on, and it was over-claiming by exactly this
    class of traffic until now.

    Both fixtures are imported *through* the probe rather than exercised in
    process, so what is tested is the guard as the real scenarios meet it.
    """

    def test_a_lookup_only_leak_is_recorded_and_blocked(self) -> None:
        """The positive control: this passed silently before the fix.

        `tests/fixtures/dns_only_leak.py` resolves a hostname and never
        connects. Against the connect-only guard the probe recorded nothing,
        so ``attempts == []`` held and a hermetic-run assertion certified a
        run that had emitted DNS queries.
        """
        result = _run_probe({"PROBE_IMPORT_MODULES": "dns_only_leak"})
        self.assertEqual(result["import_errors"], {})
        self.assertEqual(result["imported"], ["dns_only_leak"])
        operations = [attempt["operation"] for attempt in result["attempts"]]
        self.assertEqual(
            operations,
            ["socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"],
            "a lookup-only leak must be recorded under its own operation names, "
            "so a resolution leak is distinguishable from a connection in the "
            f"failure output; got: {result['attempts']!r}",
        )
        self.assertTrue(
            all(
                "dns-only-leak.invalid" in attempt["address"]
                for attempt in result["attempts"][:2]
            ),
            f"the recorded attempt must name the host looked up: "
            f"{result['attempts']!r}",
        )

    def test_local_resolution_is_permitted_rather_than_failed(self) -> None:
        """The false-red control: blocking every lookup would be wrong.

        A numeric host performs no query, ``None`` is the wildcard/loopback
        bind form, and a loopback name is answered from ``/etc/hosts``. A guard
        that failed on those would produce red runs with no leak behind them,
        and a test that fails for a reason nobody believes is a test people
        learn to edit.
        """
        result = _run_probe({"PROBE_IMPORT_MODULES": "local_resolution"})
        self.assertEqual(result["import_errors"], {})
        self.assertEqual(
            result["attempts"],
            [],
            "resolving a literal, the wildcard, or a loopback name emits no "
            f"packet and must not be recorded as an attempt: {result!r}",
        )
        self.assertEqual(
            [entry["reason"] for entry in result["permitted"]],
            [
                "ip-literal",
                "ip-literal",
                "ip-literal",
                "no-host",
                "loopback-name",
            ],
            f"every permitted call must say why it was permitted: {result!r}",
        )


class GuardPolicyTests(unittest.TestCase):
    """The permit/block decision, as a table.

    Driven in process against the probe's own predicates. The scenarios above
    prove the guard is installed and fires; this proves the rule it applies,
    including shapes no fixture reaches today - an ``AF_UNIX`` datagram, a
    scoped IPv6 literal - which is where a blanket rule would have been wrong.
    """

    @classmethod
    def setUpClass(cls) -> None:
        specification = importlib.util.spec_from_file_location(
            "offline_socket_probe_under_test", PROBE
        )
        module = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        # Safe to import: the probe installs nothing until `main()` runs.
        specification.loader.exec_module(module)
        cls.probe = module

    def test_forward_lookups_permit_only_what_needs_no_resolver(self) -> None:
        for host, expected in (
            ("api.openai.com", None),
            ("telemetry.dns-only-leak.invalid", None),
            ("127.0.0.1", "ip-literal"),
            ("93.184.216.34", "ip-literal"),
            ("::1", "ip-literal"),
            ("fe80::1%eth0", "ip-literal"),
            (b"127.0.0.1", "ip-literal"),
            (None, "no-host"),
            ("localhost", "loopback-name"),
            ("LocalHost.", "loopback-name"),
        ):
            with self.subTest(host=host):
                self.assertEqual(self.probe._forward_local_target(host), expected)

    def test_reverse_lookups_invert_the_literal_rule(self) -> None:
        """A routable literal is the *question* a PTR query asks."""
        for address, expected in (
            ("93.184.216.34", None),
            (("93.184.216.34", 443), None),
            ("127.0.0.1", "loopback-address"),
            ("::1", "loopback-address"),
            ("localhost", "loopback-name"),
        ):
            with self.subTest(address=address):
                self.assertEqual(self.probe._reverse_local_target(address), expected)

    def test_datagram_targets_follow_the_connect_rule_not_the_lookup_rule(self) -> None:
        """`sendto` reaches the network without ever calling connect, and its
        target is already an address - so permitting literals here would permit
        the leak itself."""
        for address, expected in (
            (("8.8.8.8", 53), None),
            (("127.0.0.1", 53), "loopback-address"),
            (("localhost", 53), "loopback-name"),
            ("/run/some.sock", "non-inet"),
            (b"/run/some.sock", "non-inet"),
            (None, "connected-socket"),
        ):
            with self.subTest(address=address):
                self.assertEqual(self.probe._datagram_local_target(address), expected)


# Makes the two dependencies above look absent to this module without
# uninstalling anything, by shadowing ``importlib.util.find_spec`` at
# interpreter startup. Everything not named still resolves normally, so the
# child is a normal interpreter in every other respect.
_MISSING_DEPENDENCY_SHIM = """\
import importlib.util

_MISSING = frozenset({missing!r})
_real_find_spec = importlib.util.find_spec


def _find_spec(name, package=None):
    if name in _MISSING:
        return None
    return _real_find_spec(name, package)


importlib.util.find_spec = _find_spec
"""

# Set in every child spawned below. The ``-k`` selector already keeps a child
# from re-collecting this class, but a future refactor that drops the selector
# would otherwise fork bomb, so the guard is enforced twice.
_CHILD_MARKER = "TRAIGENT_OFFLINE_SOCKET_GUARD_CHILD"


class MissingDependencyPolicyTests(unittest.TestCase):
    """The CI guard is now the only thing between "green" and "unproven".

    Nothing else asserts it exists, so one deleted branch would silently
    restore the exact defect this module was changed to close: a workflow that
    loses an install line reporting ``4 skipped`` and a green run. These tests
    drive the real module in a subprocess with a dependency made to look
    absent, and pin both directions - fail under ``CI``, skip without it.
    """

    def setUp(self) -> None:
        if os.environ.get(_CHILD_MARKER):
            self.skipTest("running inside a spawned child; do not recurse")

    def _run_module(
        self,
        *,
        missing: tuple[str, ...],
        ci: bool,
        selector: str = "OfflineSocketContractTests",
    ) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as shim_directory:
            Path(shim_directory, "sitecustomize.py").write_text(
                _MISSING_DEPENDENCY_SHIM.format(missing=missing), encoding="utf-8"
            )
            environment = dict(os.environ)
            # Prepend rather than replace: the shim has to be found first, but
            # a contributor's existing PYTHONPATH must keep working.
            environment["PYTHONPATH"] = os.pathsep.join(
                path for path in (shim_directory, os.environ.get("PYTHONPATH")) if path
            )
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment[_CHILD_MARKER] = "1"
            if ci:
                environment["CI"] = "true"
            else:
                environment.pop("CI", None)
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-p",
                    Path(__file__).name,
                    "-k",
                    selector,
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )

    def test_missing_litellm_under_ci_fails_instead_of_skipping(self) -> None:
        process = self._run_module(missing=("litellm",), ci=True)
        self.assertNotEqual(
            process.returncode,
            0,
            "a missing litellm under CI must fail the run, not skip it; got a "
            f"zero exit with stderr={process.stderr!r}",
        )
        self.assertIn("litellm is missing under CI", process.stderr)
        self.assertNotIn("OK (skipped", process.stderr)
        # The reader of a CI log has no repository in front of them, so the
        # message has to name the file to install from.
        self.assertIn(str(REQUIREMENTS), process.stderr)

    def test_missing_traigent_under_ci_fails_instead_of_skipping(self) -> None:
        process = self._run_module(
            missing=("traigent",),
            ci=True,
            selector="test_traigent_import_also_makes_zero_outbound_socket_attempts",
        )
        self.assertNotEqual(
            process.returncode,
            0,
            "a missing traigent under CI must fail the run, not skip it; got a "
            f"zero exit with stderr={process.stderr!r}",
        )
        self.assertIn("traigent is missing under CI", process.stderr)
        self.assertIn(str(REQUIREMENTS), process.stderr)

    def test_missing_dependency_without_ci_still_skips_cleanly(self) -> None:
        """A contributor without the pinned stack must not see a red suite."""
        process = self._run_module(
            missing=("litellm", "traigent"),
            ci=False,
        )
        self.assertEqual(
            process.returncode,
            0,
            "without CI a missing dependency must still skip, so a contributor "
            f"who has not installed the pinned stack sees green; stderr="
            f"{process.stderr!r}",
        )
        self.assertIn("skipped", process.stderr)


if __name__ == "__main__":
    unittest.main()

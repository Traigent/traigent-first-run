from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "traigent-first-run" / "scripts" / "preflight.py"
SPEC = importlib.util.spec_from_file_location("first_run_preflight", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def quiet_env_file(directory: Path) -> Path:
    """An `.env` that raises no WARN of its own.

    `--strict` exits 1 on any WARN, so a test asserting that some check does
    not end the run has to remove every OTHER reason the run could end. A
    missing file and an empty credential inventory are both WARNs, and a test
    that let either stand would pass or fail for reasons it never named.
    """
    env_path = directory / ".env"
    env_path.write_text("OPENAI_API_KEY=sk-not-a-real-key\n")
    env_path.chmod(0o600)
    return env_path


def synthetic_rows() -> list[dict]:
    difficulties = ("easy", "medium", "hard", "very-hard")
    rows = []
    for index in range(24):
        rows.append(
            {
                "id": f"walkthrough-{index:02d}",
                "input": f"scenario_{index} unique_token_{index} format_{index % 5}",
                "output": {
                    "label": f"class-{index % 4}",
                    "reason": f"rule-{index % 3}",
                },
                "source": "synthetic",
                "difficulty": difficulties[index // 6],
                "coverage": f"scenario-{index % 8}",
                "split": "tune" if index < 18 else "holdout",
            }
        )
    return rows


class StaticPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        MODULE.RESULTS.clear()

    def test_process_environment_overrides_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("TRAIGENT_RUN_COST_LIMIT=2.00\n")
            with mock.patch.dict(
                os.environ, {"TRAIGENT_RUN_COST_LIMIT": "7.00"}, clear=False
            ):
                effective, file_values = MODULE.read_env(env_path)
            self.assertEqual(effective["TRAIGENT_RUN_COST_LIMIT"], "7.00")
            self.assertEqual(file_values["TRAIGENT_RUN_COST_LIMIT"], "2.00")

    def test_absent_cost_limit_passes_without_promising_the_sdk_default(
        self,
    ) -> None:
        """An absent cap is fine, and the reassurance it used to carry is not.

        This reported that the installed SDK's own default applies, which was
        true while nothing set the limit. Each paid process now derives it from
        the approved figures it is launched with, so a reader told the SDK
        default governs is being told the walkthrough's ceiling does not.
        """
        MODULE.check_cost_settings({}, {})
        cost_cap = next(
            result for result in MODULE.RESULTS if result.check == "cost-cap"
        )
        self.assertEqual(cost_cap.status, MODULE.PASS)
        self.assertNotIn("SDK default", cost_cap.detail)
        self.assertIn("approved figures it is launched with", cost_cap.detail)

    def test_a_cost_figure_preserved_in_the_file_does_not_authorize_this_run(
        self,
    ) -> None:
        """A first run preserves owner configuration and supplies approval per process."""
        for name in (
            "TRAIGENT_FIRST_RUN_COST_CEILING_USD",
            "TRAIGENT_FIRST_RUN_COST_SPENT_USD",
            "TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD",
            "TRAIGENT_RUN_COST_LIMIT",
        ):
            with self.subTest(name=name):
                MODULE.RESULTS.clear()
                MODULE.check_cost_settings({}, {name: "500.00"})
                result = next(
                    item
                    for item in MODULE.RESULTS
                    if item.check == "cost-figures-in-file"
                )
                self.assertEqual(result.status, MODULE.SKIP)
                self.assertIn(name, result.detail)
                self.assertIn("do not authorize", result.detail)

        # Exercise the actual dotenv merge: a stale, malformed value must be
        # inventory only, not a preflight failure or an active-run claim.
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("TRAIGENT_RUN_COST_LIMIT=not-a-number\n")
            with mock.patch.dict(os.environ, {}, clear=True):
                effective, file_values = MODULE.read_env(env_path)
                MODULE.check_cost_settings(effective, file_values)
        self.assertFalse(
            any(
                item.check == "cost-cap" and item.status == MODULE.FAIL
                for item in MODULE.RESULTS
            )
        )
        persisted_cap = next(
            item for item in MODULE.RESULTS if item.check == "cost-figures-in-file"
        )
        self.assertEqual(persisted_cap.status, MODULE.SKIP)

        # A process value is also inventory only: the launcher overwrites this
        # legacy SDK variable from the separately approved first-run figures.
        MODULE.RESULTS.clear()
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("TRAIGENT_RUN_COST_LIMIT=not-a-number\n")
            with mock.patch.dict(
                os.environ, {"TRAIGENT_RUN_COST_LIMIT": "3.75"}, clear=True
            ):
                effective, file_values = MODULE.read_env(env_path)
                MODULE.check_cost_settings(effective, file_values)
        active_cap = next(item for item in MODULE.RESULTS if item.check == "cost-cap")
        self.assertEqual(active_cap.status, MODULE.SKIP)
        self.assertIn("inventory only", active_cap.detail)
        self.assertNotIn("$3.75", active_cap.detail)

        MODULE.RESULTS.clear()
        MODULE.check_cost_settings({}, {})
        self.assertEqual(
            [item for item in MODULE.RESULTS if item.check == "cost-figures-in-file"],
            [],
            "a clean .env was reported as carrying a persisted figure",
        )

    def test_sdk_check_accepts_the_tested_version(self) -> None:
        with mock.patch.object(
            MODULE, "version", return_value=MODULE.TESTED_TRAIGENT_VERSION
        ):
            MODULE.check_sdk()
        result = next(item for item in MODULE.RESULTS if item.check == "sdk-version")
        self.assertEqual(result.status, MODULE.PASS)
        # The tested release earns no note, because there is nothing to say
        # about it. The note below exists to explain a difference.
        self.assertNotIn("measured on", result.detail)

    def test_sdk_check_can_defer_an_expected_preinstall_absence(self) -> None:
        with mock.patch.object(
            MODULE, "version", side_effect=MODULE.PackageNotFoundError
        ):
            MODULE.check_sdk(defer_missing=True)
        result = next(item for item in MODULE.RESULTS if item.check == "sdk-version")
        self.assertEqual(result.status, MODULE.SKIP)
        self.assertIn("after installation", result.detail)

    def test_sdk_check_still_fails_on_missing_sdk_without_defer(self) -> None:
        with mock.patch.object(
            MODULE, "version", side_effect=MODULE.PackageNotFoundError
        ):
            MODULE.check_sdk()
        result = next(item for item in MODULE.RESULTS if item.check == "sdk-version")
        self.assertEqual(result.status, MODULE.FAIL)

    def test_deferred_preinstall_pass_exits_zero_when_sdk_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                sys,
                "argv",
                [
                    str(SCRIPT),
                    "--env",
                    str(Path(directory) / ".env"),
                    "--defer-missing-sdk",
                    "--json",
                ],
            ), mock.patch.object(
                MODULE, "version", side_effect=MODULE.PackageNotFoundError
            ):
                with redirect_stdout(io.StringIO()):
                    exit_code = MODULE.main()
        self.assertEqual(exit_code, 0)

    @unittest.skipIf(os.name == "nt", "POSIX permissions are not available")
    def test_env_permissions_reject_group_or_world_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("OPENAI_API_KEY=\n")
            env_path.chmod(0o664)
            MODULE.check_env_permissions(env_path)
        result = next(
            item for item in MODULE.RESULTS if item.check == "env-permissions"
        )
        self.assertEqual(result.status, MODULE.FAIL)
        self.assertIn("0600", result.detail)

    @unittest.skipIf(os.name == "nt", "POSIX permissions are not available")
    def test_env_permissions_accept_owner_only_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("OPENAI_API_KEY=\n")
            env_path.chmod(0o600)
            MODULE.check_env_permissions(env_path)
        result = next(
            item for item in MODULE.RESULTS if item.check == "env-permissions"
        )
        self.assertEqual(result.status, MODULE.PASS)

    @unittest.skipIf(os.name == "nt", "POSIX permissions are not available")
    def test_env_permissions_reject_owner_execute_bits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("OPENAI_API_KEY=\n")
            env_path.chmod(0o700)
            MODULE.check_env_permissions(env_path)
        result = next(
            item for item in MODULE.RESULTS if item.check == "env-permissions"
        )
        self.assertEqual(result.status, MODULE.FAIL)
        self.assertIn("0700", result.detail)

    def test_a_release_that_is_not_the_tested_one_does_not_stop_the_run(self) -> None:
        """Being on a different release is not a defect, and newer least of all.

        This replaces a check that required the installed release to equal the
        tested one exactly. That comparison refused 0.24.0 and 0.27.0 with the
        same words, so a customer who had kept the SDK current was told by the
        product that their copy of the product was unsupported - and the SDK
        ships faster than the constant could be bumped, which made the refusal
        a certainty on every release rather than a risk.

        Older and newer are both asserted. Newer is the one that matters and
        the one that had no test at all, because at the time the gate was
        written there was no release above the pin to write it against.
        """
        for installed in ("0.24.0", "0.25.0", "0.27.0", "1.0.0"):
            with self.subTest(installed=installed):
                MODULE.RESULTS.clear()
                with mock.patch.object(
                    MODULE, "version", return_value=installed
                ), mock.patch.object(
                    MODULE, "installed_sdk_is_the_optimizer", return_value=True
                ):
                    MODULE.check_sdk()
                result = next(
                    item for item in MODULE.RESULTS if item.check == "sdk-version"
                )
                self.assertEqual(result.status, MODULE.PASS, result.detail)
                self.assertIn(installed, result.detail)
                # Named, not hidden: the run continues and the user is told
                # which release it is actually on.
                self.assertIn(MODULE.TESTED_TRAIGENT_VERSION, result.detail)

    def test_a_version_difference_survives_strict_mode(self) -> None:
        """PASS rather than WARN, and this is why.

        `--strict` turns any WARN into exit 1. A WARN here would have been the
        same stop wearing a softer word, so the status is asserted against the
        flag that would have converted it back.
        """
        with tempfile.TemporaryDirectory() as directory:
            env_path = quiet_env_file(Path(directory))
            with mock.patch.object(
                sys,
                "argv",
                [
                    str(SCRIPT),
                    "--env",
                    str(env_path),
                    "--project-root",
                    directory,
                    "--strict",
                    "--json",
                ],
            ), mock.patch.object(
                MODULE, "version", return_value="0.99.0"
            ), mock.patch.object(
                MODULE, "installed_sdk_is_the_optimizer", return_value=True
            ):
                captured = io.StringIO()
                with redirect_stdout(captured):
                    exit_code = MODULE.main()
        records = json.loads(captured.getvalue())
        sdk = next(item for item in records if item["check"] == "sdk-version")
        self.assertEqual(sdk["status"], MODULE.PASS)
        self.assertEqual(
            [item["check"] for item in records if item["status"] != MODULE.PASS],
            [],
            "a newer SDK raised something for --strict to exit on",
        )
        self.assertEqual(exit_code, 0, "a newer SDK ended the run under --strict")

    def test_the_placeholder_release_is_still_refused(self) -> None:
        """The one real failure the version comparison was standing in for.

        `traigent 0.0.1` on the package index is an unrelated placeholder that
        resolution can select; installing it and importing it prints a
        "placeholder" line and exposes no optimizer. Every real release from
        0.10.0 onward ships both modules below, so this is asked as "is the
        optimizer here" rather than as a version number - which is both the
        true question and one that cannot go stale on a release.
        """
        with mock.patch.object(
            MODULE, "version", return_value="0.0.1"
        ), mock.patch.object(
            MODULE, "installed_sdk_is_the_optimizer", return_value=False
        ):
            MODULE.check_sdk()
        result = next(item for item in MODULE.RESULTS if item.check == "sdk-version")
        self.assertEqual(result.status, MODULE.FAIL)
        self.assertIn("does not contain the optimizer", result.detail)
        self.assertIn(f"traigent=={MODULE.TESTED_TRAIGENT_VERSION}", result.detail)

    def test_a_distribution_with_no_file_record_is_not_read_as_absent(self) -> None:
        """Missing evidence is not evidence of a missing SDK.

        `files()` returns `None` for a distribution that recorded no file
        list. Treating that as "the optimizer is absent" would refuse a real
        install for an installer's bookkeeping, which is exactly the class of
        false stop this change exists to remove.
        """
        with mock.patch.object(MODULE, "files", return_value=None):
            self.assertIsNone(MODULE.installed_sdk_is_the_optimizer())
        with mock.patch.object(
            MODULE, "version", return_value="0.26.0"
        ), mock.patch.object(MODULE, "files", return_value=None):
            MODULE.check_sdk()
        result = next(item for item in MODULE.RESULTS if item.check == "sdk-version")
        self.assertEqual(result.status, MODULE.PASS)

    def test_the_optimizer_probe_reads_metadata_and_never_imports(self) -> None:
        """A check whose contract is "runs nothing" may not import the SDK.

        Asserted by the module list, because the alternative - importing
        `traigent` to see what it has - would execute a third-party package
        inside the one script that promises it does not.
        """
        # Built from the module's own parts rather than spelled out, for the
        # reason recorded beside `REQUIRED_SDK_MODULES`: a literal
        # `<package>/<directory>` pair reads to this repository's public-package
        # scan as a private repository reference.
        package_init = MODULE.sdk_module_path(["__init__.py"])
        recorded = [
            package_init,
            *(MODULE.sdk_module_path(parts) for parts in MODULE.REQUIRED_SDK_MODULES),
        ]
        with mock.patch.object(MODULE, "files", return_value=recorded):
            self.assertTrue(MODULE.installed_sdk_is_the_optimizer())
        with mock.patch.object(MODULE, "files", return_value=[package_init]):
            self.assertFalse(MODULE.installed_sdk_is_the_optimizer())

    def test_an_editable_install_of_the_real_sdk_is_not_read_as_absent(
        self,
    ) -> None:
        """PEP 660 records a redirect, not the package tree.

        `pip install -e` writes a `.pth` and a finder module into the record;
        the modules themselves stay in the checkout and never appear in it.
        Reading that absence as "not the SDK" refuses a correct install, and
        refuses it on the machine most likely to have one - a developer's, or
        the already-has-Traigent customer the existing-use check exists for.
        The narrower question metadata can answer is whether a recorded
        package exists that does not carry the optimizer; anything else is
        unrecognised, and unrecognised may not become a finding.
        """
        editable = [
            f"__editable__.{MODULE.SDK_DISTRIBUTION}-0.26.0.pth",
            f"__editable___{MODULE.SDK_DISTRIBUTION}_0_26_0_finder.py",
            f"{MODULE.SDK_DISTRIBUTION}-0.26.0.dist-info/RECORD",
        ]
        with mock.patch.object(MODULE, "files", return_value=editable):
            self.assertIsNone(MODULE.installed_sdk_is_the_optimizer())

    def test_a_gate_that_refused_every_real_release_would_be_caught(self) -> None:
        """The false-red probe the module-list assertion cannot be.

        That test builds its own fixture from `REQUIRED_SDK_MODULES`, so it
        asserts `all(x in {x})` and stays green for any list at all, including
        one naming a module that ships in no release. This pins the record of
        a real install instead - written out here rather than derived - so a
        requirement the SDK does not satisfy turns it red.
        """
        real_install = [
            MODULE.sdk_module_path(["__init__.py"]),
            MODULE.sdk_module_path(["api", "decorators.py"]),
            MODULE.sdk_module_path(["core", "objectives.py"]),
            MODULE.sdk_module_path(["api", "__init__.py"]),
            MODULE.sdk_module_path(["core", "__init__.py"]),
        ]
        with mock.patch.object(MODULE, "files", return_value=real_install):
            self.assertTrue(
                MODULE.installed_sdk_is_the_optimizer(),
                "the required-module list no longer matches a real install",
            )

    def test_a_recorded_package_without_the_optimizer_is_still_refused(
        self,
    ) -> None:
        """The placeholder release keeps failing, which is the point of the gate.

        `0.0.1` on the index is a placeholder that records a package and no
        optimizer. Widening for editable installs must not widen for this.
        """
        placeholder = [
            MODULE.sdk_module_path(["__init__.py"]),
            f"{MODULE.SDK_DISTRIBUTION}-0.0.1.dist-info/RECORD",
        ]
        with mock.patch.object(MODULE, "files", return_value=placeholder):
            # `assertIs(..., False)`, never `assertFalse`: `None` is falsy, and
            # `None` is this function's "cannot tell", which the caller passes.
            # A mutation that widened the placeholder into "cannot tell" went
            # green under `assertFalse` - the probe found it, so the assertion
            # names the value rather than its truthiness.
            self.assertIs(MODULE.installed_sdk_is_the_optimizer(), False)

    def test_an_existing_traigent_dependency_is_reported_with_its_cost(self) -> None:
        """Say what was found, what it probably means, and what continuing costs.

        The walkthrough charges for its own baseline and its own search, and
        it is deliberately a reduced form of the product. Somebody who already
        put the SDK in this project may be about to pay a second time to be
        shown less, and they can only weigh that if the run says so.
        """
        for name, text in (
            ("requirements.txt", "traigent==0.26.0\nrequests\n"),
            ("pyproject.toml", 'dependencies = ["traigent>=0.25", "httpx"]\n'),
            ("setup.py", 'setup(install_requires=["traigent"])\n'),
        ):
            with self.subTest(declaration=name):
                MODULE.RESULTS.clear()
                with tempfile.TemporaryDirectory() as directory:
                    (Path(directory) / name).write_text(text)
                    MODULE.check_existing_traigent_use(Path(directory))
                result = next(
                    item
                    for item in MODULE.RESULTS
                    if item.check == "existing-traigent-use"
                )
                self.assertEqual(result.metrics["declared_in"], [name])
                self.assertIn(name, result.detail)
                # The three things the sentence owes the reader.
                self.assertIn("before this walkthrough started", result.detail)
                self.assertIn("may not be a first run", result.detail)
                self.assertIn("charges for its own baseline", result.detail)

    def test_an_existing_traigent_setup_never_stops_the_run(self) -> None:
        """Detect, explain, and let them decide - never refuse.

        A hard stop would be wrong on this evidence and would cost real runs:
        a customer may want a guided run on a project that lists the SDK, may
        have installed it and never optimized anything, or may be onboarding a
        second project. The declaration cannot tell those apart from a project
        that is already tuned, so it may inform a decision and never make one.

        Pinned against `--strict`, which is the only way a non-FAIL status in
        this file has ever become an exit code.
        """
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "requirements.txt").write_text("traigent==0.26.0\n")
            env_path = quiet_env_file(Path(directory))
            with mock.patch.object(
                sys,
                "argv",
                [
                    str(SCRIPT),
                    "--env",
                    str(env_path),
                    "--project-root",
                    directory,
                    "--defer-missing-sdk",
                    "--strict",
                    "--json",
                ],
            ), mock.patch.object(
                MODULE, "version", side_effect=MODULE.PackageNotFoundError
            ):
                captured = io.StringIO()
                with redirect_stdout(captured):
                    exit_code = MODULE.main()
        records = json.loads(captured.getvalue())
        found = next(
            item for item in records if item["check"] == "existing-traigent-use"
        )
        self.assertEqual(
            found["status"],
            MODULE.PASS,
            "an existing Traigent setup became a blocking status",
        )
        self.assertEqual(
            [
                item["check"]
                for item in records
                if item["status"] not in (MODULE.PASS, MODULE.SKIP)
            ],
            [],
            "an existing Traigent setup raised something for --strict to exit on",
        )
        self.assertEqual(
            exit_code, 0, "an existing Traigent setup ended the run under --strict"
        )

    def test_the_word_traigent_in_prose_is_not_a_dependency(self) -> None:
        """A comment about the SDK is not a project that uses it.

        The finding is inventory, so a false one costs a sentence rather than
        a run - but a sentence telling somebody they have already optimized a
        project they have never optimized is still wrong, and the two shapes
        that produce it are a comment and a different package whose name
        starts the same way.
        """
        for name, text in (
            ("requirements.txt", "# consider traigent later\nrequests\n"),
            ("requirements.txt", "traigent-first-run==1.0\n"),
            # Both halves of the boundary: a hyphen above, a bare word
            # character here, since either one makes it a different package.
            ("pyproject.toml", 'dependencies = ["traigentkit"]\n'),
            # Linking our website is not depending on our SDK, and this is the
            # likeliest way for a project to say the word without meaning it.
            ("pyproject.toml", 'urls = {Home = "https://traigent.ai"}\n'),
            ("setup.py", 'setup(author_email="dev@traigent.ai")\n'),
            ("requirements.txt", "requests\n"),
        ):
            with self.subTest(text=text):
                MODULE.RESULTS.clear()
                with tempfile.TemporaryDirectory() as directory:
                    (Path(directory) / name).write_text(text)
                    MODULE.check_existing_traigent_use(Path(directory))
                result = next(
                    item
                    for item in MODULE.RESULTS
                    if item.check == "existing-traigent-use"
                )
                self.assertEqual(result.status, MODULE.PASS)
                self.assertEqual(result.metrics["declared_in"], [])
                self.assertIn("does not list traigent", result.detail)

    def test_an_unreadable_declaration_does_not_end_a_first_run(self) -> None:
        """Somebody's filesystem is not a reason to refuse a run.

        A directory where a file was expected, rather than a mode of 0000:
        the read fails the same way and it fails for every user, where a
        permission bit does not stop root and would have made this pass
        without exercising anything.
        """
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "requirements.txt").mkdir()
            with self.assertRaises(OSError):
                (Path(directory) / "requirements.txt").read_text()
            MODULE.check_existing_traigent_use(Path(directory))
        result = next(
            item for item in MODULE.RESULTS if item.check == "existing-traigent-use"
        )
        self.assertEqual(result.status, MODULE.PASS)
        self.assertEqual(result.metrics["declared_in"], [])

    def test_provider_credentials_are_inventory_not_route_selection(self) -> None:
        MODULE.check_keys(
            {
                "OPENAI_API_KEY": "placeholder-openai",
                "ANTHROPIC_API_KEY": "placeholder-anthropic",
            }
        )
        result = next(
            item for item in MODULE.RESULTS if item.check == "provider-credentials"
        )
        self.assertEqual(result.status, MODULE.PASS)
        self.assertIn("OpenAI, Anthropic", result.detail)
        self.assertIn("does not select or change", result.detail)
        self.assertNotIn("select one", result.detail)

    def test_the_absent_credential_warning_does_not_stop_a_signed_route(self) -> None:
        """An empty environment is not evidence for every route.

        This gate emitted one instruction for all of them - do not begin paid
        work until that route's credential is present - and one route has no
        credential to make present. Bedrock signs through the AWS chain, so a
        shared profile, an SSO session or an instance role runs a fully
        credentialed customer whose environment looks exactly like this. The
        paid wrapper was deliberately built not to refuse that customer, in a
        comment that calls refusing them the defect rebuilt on purpose - and
        the gate in front of it told them to stop anyway.

        So the stop has to name what it applies to. The report is unchanged:
        finding no names is worth saying, and saying it is not the same as
        telling somebody to halt.
        """
        MODULE.RESULTS.clear()
        MODULE.check_keys({})
        result = next(
            item for item in MODULE.RESULTS if item.check == "provider-credentials"
        )
        self.assertEqual(result.status, MODULE.WARN)
        stops = [
            sentence
            for sentence in re.split(r"(?<=[.;])\s+", result.detail)
            if "do not begin paid work" in sentence
        ]
        self.assertTrue(
            stops,
            "the absent-credential warning no longer tells anyone to wait for a "
            "credential, which is the half of it that was right",
        )
        for sentence in stops:
            self.assertIn(
                "environment variable",
                sentence,
                "the gate instructs a stop over absent environment variables "
                "without saying that is what it is about, so a customer whose "
                "route signs through a cloud credential chain reads it as an "
                "instruction to stop a run that would have succeeded",
            )
        self.assertIn(
            "AWS credential chain",
            result.detail,
            "nothing here tells the customer which route this absence does not "
            "settle, so the one route that authenticates with nothing set is "
            "invisible in the message that concerns it most",
        )

    def test_both_backend_origin_overrides_are_reported(self) -> None:
        """The SDK resolves its backend from either name, so one is not enough.

        `TRAIGENT_BACKEND_URL` was the only one named here, while the SDK falls
        back to `TRAIGENT_API_URL` and prefers either over the stored or default
        route. An unreported override sends a paid, portal-tracked run to a
        backend nobody approved - and it still looks connected, so the
        require-cloud guard in the wrapper does not catch it either.
        """
        for present, expected in (
            (
                {"TRAIGENT_BACKEND_URL": "https://example.invalid"},
                ["TRAIGENT_BACKEND_URL"],
            ),
            ({"TRAIGENT_API_URL": "https://example.invalid/api"}, ["TRAIGENT_API_URL"]),
            (
                {
                    "TRAIGENT_BACKEND_URL": "https://example.invalid",
                    "TRAIGENT_API_URL": "https://example.invalid/api",
                },
                ["TRAIGENT_BACKEND_URL", "TRAIGENT_API_URL"],
            ),
        ):
            with self.subTest(present=sorted(present)):
                MODULE.RESULTS.clear()
                MODULE.check_cost_settings(dict(present), {})
                result = next(
                    item for item in MODULE.RESULTS if item.check == "backend-url"
                )
                self.assertEqual(result.status, MODULE.SKIP)
                for name in expected:
                    self.assertIn(name, result.detail)
                self.assertIn("connected destination at its approval", result.detail)

        MODULE.RESULTS.clear()
        MODULE.check_cost_settings({}, {})
        self.assertEqual(
            [item for item in MODULE.RESULTS if item.check == "backend-url"],
            [],
            "a clean environment must not warn, or the warning means nothing",
        )

    def test_paid_first_run_rows_are_reported_from_usable_rows(self) -> None:
        """Reads the pair now, because one number under the other's name was the defect.

        Same two fixtures and the same detail substrings as before; the metric
        it asserts changed because `first_run_rows` conflated a question cap
        with a row count. Both fixtures ask one question per row, so the cap
        and the rows coincide here and the old expectation is asserted twice
        over - once as questions, once as the rows they bring - rather than
        weakened.
        """
        for row_count, expected in ((40, 40), (101, 18)):
            with self.subTest(row_count=row_count):
                MODULE.RESULTS.clear()
                with tempfile.TemporaryDirectory() as directory:
                    dataset = Path(directory) / "eval.jsonl"
                    dataset.write_text(
                        "\n".join(
                            json.dumps(
                                {
                                    "id": str(index),
                                    "input": f"question {index}",
                                    "output": f"answer {index}",
                                }
                            )
                            for index in range(row_count)
                        )
                        + "\n"
                    )
                    MODULE.check_dataset(dataset)
                finding = next(
                    item
                    for item in MODULE.RESULTS
                    if item.check == "dataset-first-run-rows"
                )
                self.assertEqual(finding.status, MODULE.PASS)
                self.assertEqual(finding.metrics["first_run_questions"], expected)
                self.assertEqual(finding.metrics["first_run_rows_fewest"], expected)
                self.assertEqual(finding.metrics["first_run_rows_most"], expected)
                self.assertEqual(finding.metrics["usable_rows"], row_count)
                self.assertIn("proposed first-run subset cap", finding.detail)
                self.assertIn("actual row ids before baseline approval", finding.detail)

    def test_synthetic_dataset_quality_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text(
                "\n".join(json.dumps(row) for row in synthetic_rows()) + "\n"
            )
            rows = MODULE.check_dataset(dataset)
        self.assertIsNotNone(rows)
        failures = [result for result in MODULE.RESULTS if result.status == MODULE.FAIL]
        self.assertEqual(failures, [])
        tuning = next(
            result for result in MODULE.RESULTS if result.check == "dataset-tuning-size"
        )
        holdout = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-holdout-resolution"
        )
        self.assertEqual(tuning.status, MODULE.PASS)
        self.assertIn("18 tuning rows", tuning.detail)
        self.assertEqual(holdout.status, MODULE.WARN)
        self.assertIn("16.7 percentage points", holdout.detail)
        self.assertEqual(
            tuning.metrics,
            {
                "tuning_rows": 18,
                "tuning_labelled_rows": 18,
                "tuning_distinct_rows": 18,
                "tuning_distinct_scoreable_rows": 18,
            },
        )
        self.assertEqual(
            holdout.metrics, {"holdout_rows": 6, "holdout_labelled_rows": 6}
        )

    def test_tuning_only_dataset_is_not_reported_as_an_undeclared_split(self) -> None:
        rows = synthetic_rows()[:18]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)

        split = next(
            result for result in MODULE.RESULTS if result.check == "dataset-split"
        )
        tuning = next(
            result for result in MODULE.RESULTS if result.check == "dataset-tuning-size"
        )
        self.assertEqual(split.status, MODULE.PASS)
        self.assertEqual(
            split.detail,
            "tuning-only dataset; no held-out split was declared",
        )
        self.assertEqual(
            tuning.metrics,
            {
                "tuning_rows": 18,
                "tuning_labelled_rows": 18,
                "tuning_distinct_rows": 18,
                "tuning_distinct_scoreable_rows": 18,
            },
        )
        self.assertFalse(
            any(
                result.check == "dataset-holdout-resolution"
                for result in MODULE.RESULTS
            )
        )

    def test_split_metrics_count_labelled_rows_separately(self) -> None:
        """A holdout whose rows carry no expected output resolves nothing.

        The per-split labelled counts are what the readiness scorer clamps
        power on, so they must be reported next to the raw split sizes rather
        than inferred from the aggregate labelled count.
        """
        rows = [
            {
                "id": f"tune-{index}",
                "input": f"tuning case {index} token{index}",
                "output": f"answer {index % 3}",
                "split": "tune",
            }
            for index in range(8)
        ] + [
            {
                "id": f"holdout-{index}",
                "input": f"holdout case {index} othertoken{index}",
                "output": "",
                "split": "holdout",
            }
            for index in range(4)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        tuning = next(
            result for result in MODULE.RESULTS if result.check == "dataset-tuning-size"
        )
        holdout = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-holdout-resolution"
        )
        self.assertEqual(
            tuning.metrics,
            {
                "tuning_rows": 8,
                "tuning_labelled_rows": 8,
                "tuning_distinct_rows": 8,
                "tuning_distinct_scoreable_rows": 8,
            },
        )
        self.assertEqual(
            holdout.metrics, {"holdout_rows": 4, "holdout_labelled_rows": 0}
        )
        self.assertEqual(tuning.status, MODULE.WARN)
        self.assertIn("8 tuning rows", tuning.detail)
        self.assertEqual(holdout.status, MODULE.WARN)
        self.assertIn("none scoreable", holdout.detail)
        self.assertNotIn("percentage points", holdout.detail)

    def test_holdout_resolution_quotes_only_scoreable_rows(self) -> None:
        """Per-example resolution is 100/scoreable, not 100/total.

        Quoting the total claims a precision the evaluator cannot deliver on
        the half of the holdout it cannot score at all.
        """
        rows = [
            {
                "id": f"tune-{index}",
                "input": f"tuning case {index} token{index}",
                "output": f"answer {index % 3}",
                "split": "tune",
            }
            for index in range(20)
        ] + [
            {
                "id": f"holdout-{index}",
                "input": f"holdout case {index} othertoken{index}",
                "output": f"answer {index % 3}" if index < 10 else "",
                "split": "holdout",
            }
            for index in range(20)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        holdout = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-holdout-resolution"
        )
        self.assertEqual(holdout.metrics["holdout_labelled_rows"], 10)
        self.assertEqual(holdout.metrics["holdout_rows"], 20)
        self.assertEqual(holdout.status, MODULE.PASS)
        self.assertIn("10.0 percentage points", holdout.detail)
        self.assertNotIn("5.0 percentage points", holdout.detail)

    def test_a_label_that_reads_none_is_still_a_label(self) -> None:
        """A label reading "None" is a class name, not a missing output.

        Stringifying the raw value before the emptiness test rendered the JSON
        null and the one-word label "None" as the same four characters, so a
        two-class dataset whose negative class is literally "None" - a
        no-intent class, or a pandas round-trip - read as entirely unlabelled
        and had its splits reported as half unscoreable.
        """
        self.assertTrue(MODULE.dataset_row_is_labelled({"output": "None"}))
        self.assertFalse(MODULE.dataset_row_is_labelled({"output": None}))
        self.assertFalse(MODULE.dataset_row_is_labelled({}))
        self.assertFalse(MODULE.dataset_row_is_labelled({"output": "   "}))

        rows = [
            {
                "id": f"intent-{index}",
                "input": f"utterance {index} token{index}",
                "output": "None" if index % 2 else "book_flight",
                "split": "tune" if index < 10 else "holdout",
            }
            for index in range(20)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        tuning = next(
            result for result in MODULE.RESULTS if result.check == "dataset-tuning-size"
        )
        holdout = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-holdout-resolution"
        )
        self.assertEqual(
            tuning.metrics,
            {
                "tuning_rows": 10,
                "tuning_labelled_rows": 10,
                "tuning_distinct_rows": 10,
                "tuning_distinct_scoreable_rows": 10,
            },
        )
        self.assertEqual(
            holdout.metrics, {"holdout_rows": 10, "holdout_labelled_rows": 10}
        )
        self.assertNotIn("scoreable", tuning.detail)
        self.assertNotIn("scoreable", holdout.detail)

    def test_a_json_null_expected_output_is_still_unlabelled(self) -> None:
        """The behaviour the "None" sentinel was protecting must survive.

        A row whose expected output is JSON `null` carries nothing to score
        against, so it must stay out of the labelled counts even though the
        predicate no longer looks at the stringified value.
        """
        rows = [
            {
                "id": f"tune-{index}",
                "input": f"tuning case {index} token{index}",
                "output": f"answer {index % 3}",
                "split": "tune",
            }
            for index in range(10)
        ] + [
            {
                "id": f"holdout-{index}",
                "input": f"holdout case {index} othertoken{index}",
                "output": None,
                "split": "holdout",
            }
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        holdout = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-holdout-resolution"
        )
        self.assertEqual(
            holdout.metrics, {"holdout_rows": 10, "holdout_labelled_rows": 0}
        )
        self.assertIn("none scoreable", holdout.detail)

    def test_combined_dataset_reports_a_small_tuning_split(self) -> None:
        rows = synthetic_rows()[:12]
        for index, row in enumerate(rows):
            row["split"] = "tune" if index < 8 else "holdout"
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        tuning = next(
            result for result in MODULE.RESULTS if result.check == "dataset-tuning-size"
        )
        self.assertEqual(tuning.status, MODULE.WARN)
        self.assertIn("8 tuning rows", tuning.detail)

    def test_ten_scoreable_rows_pass_only_the_static_wiring_boundary(self) -> None:
        """A preflight PASS must not read as a readiness-resolution verdict."""
        rows = [
            {
                "id": f"row-{index}",
                "input": f"case {index} token{index}",
                "output": f"answer {index % 3}",
                "split": "tune" if index < 10 else "holdout",
            }
            for index in range(20)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        tuning = next(
            result for result in MODULE.RESULTS if result.check == "dataset-tuning-size"
        )
        self.assertEqual(tuning.status, MODULE.PASS)
        self.assertIn("10-row static wiring boundary", tuning.detail)
        self.assertIn("readiness rates comparison size separately", tuning.detail)

    def test_missing_stable_ids_route_to_the_reversible_working_copy_repair(
        self,
    ) -> None:
        rows = [
            {
                "input": f"case {index} token{index}",
                "output": f"answer {index}",
                "source": "production",
            }
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        ids = next(result for result in MODULE.RESULTS if result.check == "dataset-ids")
        self.assertEqual(ids.status, MODULE.WARN)
        self.assertIn("add stable ids in a working copy", ids.detail)
        self.assertIn("before excluding rows or selecting a bounded subset", ids.detail)
        self.assertIn("re-run validation", ids.detail)

    def test_id_repair_includes_unlabelled_rows_and_whitespace_ids(self) -> None:
        rows = [
            {
                "id": f"row-{index}",
                "input": f"labelled case {index}",
                "output": f"answer {index}",
                "source": "production",
            }
            for index in range(10)
        ] + [
            {"id": "   ", "input": "unlabelled whitespace id", "source": "production"},
            {"input": "unlabelled missing id", "source": "production"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        ids = [result for result in MODULE.RESULTS if result.check == "dataset-ids"]
        self.assertEqual(len(ids), 1)
        self.assertEqual(ids[0].status, MODULE.WARN)
        self.assertIn("2 rows at source lines [11, 12]", ids[0].detail)
        self.assertIn("add stable ids in a working copy", ids[0].detail)

    def test_generated_row_without_id_fails_inside_a_mixed_dataset(self) -> None:
        rows = [
            {
                "id": f"real-{index}",
                "input": f"collected case {index}",
                "output": f"answer {index}",
                "source": "production",
            }
            for index in range(9)
        ]
        rows.append(
            {
                "input": "generated case without an id",
                "output": "generated answer",
                "source": "synthetic",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        ids = next(result for result in MODULE.RESULTS if result.check == "dataset-ids")
        self.assertEqual(ids.status, MODULE.FAIL)
        self.assertIn("1 row at source line 10 has no stable id", ids.detail)
        self.assertIn("1 generated row requires an id", ids.detail)

    def test_duplicate_ids_include_unlabelled_rows(self) -> None:
        rows = [
            {
                "id": f"row-{index}",
                "input": f"labelled case {index}",
                "output": f"answer {index}",
                "source": "production",
            }
            for index in range(10)
        ]
        rows.append(
            {
                "id": "row-0",
                "input": "unlabelled duplicate",
                "source": "production",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        ids = [result for result in MODULE.RESULTS if result.check == "dataset-ids"]
        self.assertTrue(
            any(
                result.status == MODULE.FAIL and "row-0" in result.detail
                for result in ids
            ),
            ids,
        )

    def test_all_unlabelled_dataset_still_routes_missing_ids_to_repair(self) -> None:
        rows = [
            {"input": "first unlabelled case", "source": "production"},
            {"id": "kept", "input": "second unlabelled case", "source": "production"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        ids = next(result for result in MODULE.RESULTS if result.check == "dataset-ids")
        self.assertEqual(ids.status, MODULE.WARN)
        self.assertIn("source line 1", ids.detail)
        self.assertIn("before excluding rows or selecting a bounded subset", ids.detail)

    def test_explicit_local_quality_fields_do_not_rewrite_dataset(self) -> None:
        rows = [
            {
                "request.payload": "preserved side field",
                "request": {"payload": f"case {index}"},
                "reference": {"answer": f"answer {index}"},
                "id": f"case-{index}",
                "source": "reviewed",
                "metadata": {"rubric_branch": f"branch-{index % 3}"},
                "split": "tune" if index < 8 else "holdout",
            }
            for index in range(12)
        ]

        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            original_text = "\n".join(json.dumps(row) for row in rows) + "\n"
            dataset.write_text(original_text)
            normalized_rows = MODULE.check_dataset(
                dataset,
                input_field="request.payload",
                expected_field="reference.answer",
            )
            self.assertEqual(dataset.read_text(), original_text)

        self.assertEqual(len(normalized_rows or []), len(rows))
        self.assertFalse(
            any(result.status == MODULE.FAIL for result in MODULE.RESULTS),
            MODULE.RESULTS,
        )
        for index, row in enumerate(normalized_rows or []):
            with self.subTest(index=index):
                self.assertEqual(row["input"], f"case {index}")
                self.assertEqual(row["output"], f"answer {index}")
                self.assertEqual(row["id"], f"case-{index}")
                self.assertEqual(row["request.payload"], "preserved side field")
                self.assertEqual(
                    row["metadata"],
                    {"rubric_branch": f"branch-{index % 3}"},
                )

    def test_selected_local_quality_fields_must_exist(self) -> None:
        rows = [
            {
                "request": {},
                "reference": {"answer": "answer"},
            },
            {
                "request": {"payload": "case"},
                "reference": {},
            },
            {
                "request": {"payload": "valid"},
                "reference": {"answer": "valid"},
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            normalized_rows = MODULE.check_dataset(
                dataset,
                input_field="request.payload",
                expected_field="reference.answer",
            )

        self.assertEqual(len(normalized_rows or []), 1)
        integrity = next(
            result for result in MODULE.RESULTS if result.check == "dataset-integrity"
        )
        self.assertEqual(integrity.status, MODULE.FAIL)
        self.assertIn(
            "line 1: missing selected input field 'request.payload'", integrity.detail
        )
        self.assertIn(
            "line 2: missing selected expected-output field 'reference.answer'",
            integrity.detail,
        )

    def test_one_cause_is_reported_once_however_many_rows_share_it(self) -> None:
        """The detail grew with the file instead of with what is wrong with it.

        Readiness forwards this string verbatim onto the card, so six rows
        missing the same selected field printed that sentence six times - 347
        characters, one fact. Nothing there was wrong, only repeated; the
        remedy is to say each distinct cause once, keep the first line it was
        seen on so the file can be opened at it, and count the rest.
        """
        rows = [{"question": f"q{index}", "answer": f"a{index}"} for index in range(6)]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)

        integrity = next(
            result for result in MODULE.RESULTS if result.check == "dataset-integrity"
        )
        self.assertEqual(integrity.status, MODULE.FAIL)
        cause = "missing selected input field 'input'"
        self.assertEqual(integrity.detail.count(cause), 1)
        # The line to open, and how many others share the cause.
        self.assertIn(f"line 1 (+5 more): {cause}", integrity.detail)
        # Every row is still counted; only the repetition is gone.
        self.assertIn("6/6 rows (100.0%) are unusable", integrity.detail)
        self.assertLess(len(integrity.detail), 200)

    def test_distinct_causes_each_get_a_slot_rather_than_the_first_one_repeating(
        self,
    ) -> None:
        """The report cap now bounds causes, which is what a reader needs.

        Capping ROWS spent all five slots on whichever cause happened to come
        first, so a file with several different problems reported one of them.
        """
        rows = [
            '{"question": "q", "answer": "a"}',
            "not json at all",
            '["not", "an", "object"]',
            '{"input": "q"}',
            '{"question": "q2", "answer": "a2"}',
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(rows) + "\n")
            MODULE.check_dataset(dataset)

        detail = next(
            result for result in MODULE.RESULTS if result.check == "dataset-integrity"
        ).detail
        for cause in (
            "line 1 (+1 more): missing selected input field 'input'",
            "row is not an object",
            "invalid JSON",
        ):
            with self.subTest(cause=cause):
                self.assertIn(cause, detail)

    def test_dataset_normalization_contract_violation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text('{"input": "case", "output": "answer"}\n')
            with mock.patch.object(
                MODULE, "normalize_dataset_row", return_value=(None, None)
            ), self.assertRaisesRegex(
                RuntimeError, "dataset normalization returned no row without an error"
            ):
                MODULE.check_dataset(dataset)

    def test_default_local_fields_do_not_infer_sdk_aliases(self) -> None:
        row = {
            "input_data": {"message": "same"},
            "expected_output": "answer",
        }
        normalized, error = MODULE.normalize_dataset_row(row)
        self.assertIsNone(normalized)
        self.assertEqual(error, "missing selected input field 'input'")

        normalized, error = MODULE.normalize_dataset_row(
            row,
            input_field="input_data",
            expected_field="expected_output",
        )
        self.assertIsNone(error)
        self.assertEqual(normalized["input"], {"message": "same"})
        self.assertEqual(normalized["output"], "answer")

    def test_duplicate_synthetic_input_fails(self) -> None:
        rows = synthetic_rows()
        rows[1]["input"] = rows[0]["input"]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        failures = [
            result.check for result in MODULE.RESULTS if result.status == MODULE.FAIL
        ]
        self.assertIn("dataset-duplicates", failures)

    @staticmethod
    def _pairwise_near_duplicates(
        token_sets: list[set[str]],
        threshold: float = MODULE.NEAR_DUPLICATE_THRESHOLD,
    ) -> list[tuple[int, int]]:
        """The full O(n^2) scan, kept here as the oracle for the indexed join.

        This is the code the indexed join replaced. It stays in the tests
        because a similarity index that quietly misses pairs would be the same
        defect the index was written to remove - a check that reports clean
        without having looked - one layer further down.
        """
        pairs = []
        for left in range(len(token_sets)):
            for right in range(left + 1, len(token_sets)):
                union = token_sets[left] | token_sets[right]
                similarity = (
                    len(token_sets[left] & token_sets[right]) / len(union)
                    if union
                    else 1.0
                )
                if similarity >= threshold:
                    pairs.append((left + 1, right + 1))
        return pairs

    def test_indexed_near_duplicate_join_matches_the_pairwise_scan(self) -> None:
        """Exactness, on the shapes that break naive similarity indexes."""
        import random

        random.seed(20260806)
        vocabulary = [f"word{index}" for index in range(40)]
        for _ in range(200):
            token_sets = [
                set(random.sample(vocabulary, size))
                for size in (random.randint(0, 8) for _ in range(random.randint(0, 40)))
            ]
            pairs, complete = MODULE.near_duplicate_pairs(token_sets)
            self.assertTrue(complete)
            self.assertEqual(
                pairs,
                sorted(self._pairwise_near_duplicates(token_sets)),
                f"indexed join disagrees with the pairwise scan on {token_sets}",
            )

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        """The number this check actually decides on, for two raw inputs."""
        first, second = MODULE.shingle_set(left), MODULE.shingle_set(right)
        union = first | second
        return len(first & second) / len(union) if union else 1.0

    @staticmethod
    def _word_set_similarity(left: str, right: str) -> float:
        """What the check used to decide on. Kept to state the defect as a number."""
        first = set(MODULE.normalized_text(left).split())
        second = set(MODULE.normalized_text(right).split())
        union = first | second
        return len(first & second) / len(union) if union else 1.0

    def test_a_reordered_sentence_is_not_a_repeat(self) -> None:
        """The defect in traigent-first-run#170, asserted as both numbers.

        "the cat sat on the mat" and "the mat sat on the cat" are the same six
        words in a different order. To a word-set comparison they are the same
        row - similarity exactly 1.0 - so a dataset that varies word order on
        purpose read as duplicated. Comparing runs of consecutive words instead
        scores them 0.143.

        Both numbers are computed here rather than quoted, so this states the
        change rather than restating a constant, and it fails if either metric
        stops behaving the way the guidance says it does.
        """
        left, right = "the cat sat on the mat", "the mat sat on the cat"
        self.assertEqual(self._word_set_similarity(left, right), 1.0)
        self.assertLess(self._similarity(left, right), 0.2)
        # And through the whole path, because a similarity function that is
        # right on its own proves nothing about what the customer is told.
        rows = [
            {"id": "r1", "input": left, "output": "a", "source": "production"},
            {"id": "r2", "input": right, "output": "b", "source": "production"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "reordered.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        near = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-near-duplicates"
        )
        self.assertEqual(near.status, MODULE.PASS, near.detail)

    def test_a_genuine_repeat_in_a_long_row_is_still_caught(self) -> None:
        """The false-red direction: removing order-blindness must not go further.

        One word changed in a long row is the case the check most has to keep.
        Asserted through `check_dataset` on rows long enough to be past the
        crossing length the glossary quotes, so this fails if the switch to
        sequences quietly made the check inert instead of order-sensitive.
        """
        base = [f"word{index}" for index in range(30)]
        changed = list(base)
        changed[15] = "different"
        rows = [
            {
                "id": "r1",
                "input": " ".join(base),
                "output": "a",
                "source": "production",
            },
            {
                "id": "r2",
                "input": " ".join(changed),
                "output": "b",
                "source": "production",
            },
        ]
        self.assertGreaterEqual(
            self._similarity(rows[0]["input"], rows[1]["input"]),
            MODULE.NEAR_DUPLICATE_THRESHOLD,
        )
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "near.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        near = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-near-duplicates"
        )
        self.assertEqual(near.status, MODULE.WARN, near.detail)
        self.assertIn("(1, 2)", near.detail)

    def test_rows_too_short_for_one_sequence_compare_whole(self) -> None:
        """A row shorter than the sequence length still has to mean something.

        There are no 3-word runs in a 2-word row, and both silent answers are
        wrong: scoring 0 hides a two-word row repeated forty times, and scoring
        1 makes every short row a duplicate of every other. Such a row
        contributes itself as one whole sequence, so identical short rows score
        1.0 and everything else scores 0.0 - which is the binary answer the
        glossary tells the reader to expect below this length.
        """
        self.assertEqual(self._similarity("reset password", "reset password"), 1.0)
        self.assertEqual(self._similarity("reset password", "change password"), 0.0)
        # Order still counts below the sequence length, which is the same rule
        # as above rather than an exception to it.
        self.assertEqual(self._similarity("reset password", "password reset"), 0.0)
        # And a short row is not silently a duplicate of a long one.
        self.assertEqual(self._similarity("reset password", "how do i reset"), 0.0)
        # Rows with no word characters at all keep their own handling: the join
        # pairs them directly, because they have no sequence to be indexed under.
        self.assertEqual(MODULE.shingle_set("???"), set())

    def test_the_indexed_join_is_exact_over_sequence_sets(self) -> None:
        """Exactness has to be re-proved on the sets the check now feeds it.

        The join was already checked against a brute-force scan, but over
        randomly sampled WORD sets. Sequence sets have a different shape - far
        more members per row, far rarer members, and members that overlap each
        other by construction - and the prefix filter's soundness is what the
        whole switch rests on. So the same oracle runs again on real rows turned
        into real sequence sets.
        """
        import random

        random.seed(20260808)
        vocabulary = [f"word{index}" for index in range(12)]
        for _ in range(120):
            rows = [
                " ".join(random.choice(vocabulary) for _ in range(random.randint(0, 9)))
                for _ in range(random.randint(0, 25))
            ]
            sets = [MODULE.shingle_set(row) for row in rows]
            pairs, complete = MODULE.near_duplicate_pairs(sets)
            self.assertTrue(complete)
            self.assertEqual(
                pairs,
                sorted(self._pairwise_near_duplicates(sets)),
                f"indexed join disagrees with the pairwise scan on {rows}",
            )

    def test_sequences_finish_the_scan_word_sets_ran_out_of_budget_on(self) -> None:
        """The performance half of #170, asserted as an outcome and not a clock.

        #158 bounded this loop in token operations because 2,000 rows of 300
        words spent 1.03 billion of them. That shape did not merely run slowly -
        it exhausted the budget and reported SKIP, which readiness reads as
        UNCHECKED, so the dataset most likely to contain duplicates was the one
        that got no answer.

        Sequences are far rarer across rows than words are, so the index admits
        far fewer candidates and the same rows finish. Measured at full size:
        964M operations as word sets against 0 as sequences. Asserted here on a
        smaller corpus of the same shape, so the suite pays about a second for
        it, and on `complete` rather than on elapsed time, which would be flaky.
        """
        import random

        random.seed(20260808)
        vocabulary = [f"word{index}" for index in range(4000)]
        rows = [
            " ".join(random.choice(vocabulary) for _ in range(300)) for _ in range(400)
        ]
        _pairs, word_complete = MODULE.near_duplicate_pairs(
            [set(MODULE.normalized_text(row).split()) for row in rows]
        )
        self.assertFalse(
            word_complete,
            "the word-set comparison is expected to exhaust the budget on this "
            "shape; if it no longer does, this test has stopped covering the "
            "regression it was written for",
        )
        pairs, complete = MODULE.near_duplicate_pairs(
            [MODULE.shingle_set(row) for row in rows]
        )
        self.assertTrue(
            complete,
            "sequences must finish the scan that word sets could not, or the "
            "check still answers UNCHECKED on the datasets that need it most",
        )
        self.assertEqual(pairs, [])

    def test_reused_answers_with_distinct_inputs_are_not_repetition(self) -> None:
        """Repeating an ANSWER is not the defect; repeating a QUESTION is.

        A closed-label task is supposed to reuse its labels - a yes/no set has
        two of them and a balanced one uses each half the time. Pointing this
        check at the output field would read 60 rows as 60 duplicates and charge
        a correct dataset 7 of its 20 diversity points, while missing the actual
        defect entirely. So the near-duplicate scan reads the input and only the
        input, and this holds it there.

        Answer spread is a real question, and a different one: it has its own
        record (`dataset-ceiling-risk`), which fires on DOMINANCE rather than on
        reuse and correctly stays silent on a balanced set.
        """
        rows = [
            {
                "id": f"r{index}",
                "input": (
                    f"is order {index} from warehouse {index} eligible for a "
                    "refund today"
                ),
                "output": "yes" if index % 2 else "no",
                "source": "production",
            }
            for index in range(60)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "closed_label.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        checks = {result.check: result for result in MODULE.RESULTS}
        self.assertEqual(
            checks["dataset-near-duplicates"].status,
            MODULE.PASS,
            checks["dataset-near-duplicates"].detail,
        )
        self.assertEqual(checks["dataset-duplicates"].status, MODULE.PASS)
        # Two labels used evenly is the best a binary task can do, so nothing
        # here may read as an answer having taken the dataset over.
        self.assertNotIn("dataset-ceiling-risk", checks)

    def test_near_duplicates_are_still_checked_above_five_hundred_rows(self) -> None:
        """The check must not stop running as the dataset gets big.

        A 500-row ceiling used to turn this into SKIP, and nothing downstream
        told a SKIP from a pass - so a 5,000-row dataset silently lost
        duplicate detection at exactly the size where duplicates become likely.
        """
        rows = [
            {
                "id": f"real-{index}",
                "input": f"question {index} about topic {index} number {index}",
                "output": f"answer {index % 7}",
                "source": "production",
            }
            for index in range(900)
        ]
        # With 3-word shingles, row 2 shares 7 of row 1's 8 runs: Jaccard 7/8.
        rows[0]["input"] = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        rows[1]["input"] = "alpha beta gamma delta epsilon zeta eta theta iota"
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        near = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-near-duplicates"
        )
        self.assertEqual(near.status, MODULE.WARN, near.detail)
        self.assertIn("(1, 2)", near.detail)

    def test_an_incomplete_near_duplicate_scan_is_skip_and_never_pass(self) -> None:
        """Out of budget with nothing found is unchecked, not clean."""
        token_sets = [{"a", "b", "c"} for _ in range(50)]
        pairs, complete = MODULE.near_duplicate_pairs(token_sets, max_work=0, limit=10)
        self.assertEqual(pairs, [])
        self.assertFalse(complete)

    def test_a_truncated_near_duplicate_scan_still_reports_its_findings(self) -> None:
        """Pairs found before the budget ran out are a finding, not a SKIP.

        The budget is in token operations, so it has to buy at least one whole
        comparison: a posting step plus both rows' token counts.
        """
        token_sets = [{"a", "b", "c"} for _ in range(50)]
        pairs, complete = MODULE.near_duplicate_pairs(token_sets, max_work=10, limit=10)
        self.assertTrue(pairs)
        self.assertFalse(complete)

    def test_the_budget_is_spent_on_the_work_and_not_on_the_pair_count(
        self,
    ) -> None:
        """The bound has to bound what the loop actually spends.

        It used to count distinct candidate PAIRS, which is not the cost: each
        pair is found with one posting-list step and then settled with a union
        and an intersection over both rows' whole token sets. So a few very
        long rows cost a great deal and counted as almost nothing. Measured on
        2,000 RAG-shaped rows of 300 tokens: 1.7M candidate pairs - 34% of a
        5,000,000 pair budget, so the bound never fired - and 1.03 billion
        token operations, which ran 45 s with no output and no timeout and then
        answered PASS. Trunk answered in 0.24 s.

        Asserted on the accounting rather than on a clock, which would be
        flaky. Three rows are three candidate pairs however long they are, so
        a budget of 100 stops this scan only if the row length is being
        charged for.
        """
        long_rows = [{f"token{index}" for index in range(1000)} for _ in range(3)]
        pairs, complete = MODULE.near_duplicate_pairs(long_rows, max_work=100)
        self.assertFalse(
            complete,
            "three 1,000-token rows are three candidate pairs and about six "
            "thousand token operations; a budget of 100 that still completes "
            "is counting pairs",
        )
        # The false-red direction: the same three pairs with short rows are
        # cheap, and must still finish inside the same budget.
        short_rows = [{"a", "b", "c"} for _ in range(3)]
        _pairs, short_complete = MODULE.near_duplicate_pairs(short_rows, max_work=100)
        self.assertTrue(short_complete)

    def test_one_row_is_not_charged_for_an_answer_spread_it_cannot_have(
        self,
    ) -> None:
        """Dominance needs two answers to be a statement about anything.

        One row's single answer holds 100% of the rows by arithmetic, and
        reporting that charged a 1-row dataset 6 of its 20 diversity points -
        14.0 against 20.0, dataset 64 against 71 - for a finding no dataset of
        that size can avoid, and told its owner to diversify answers they have
        one of. The row count IS the problem and `dataset-size` already says
        so, loudly.
        """
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "one.jsonl"
            dataset.write_text(
                json.dumps({"id": "r1", "input": "only question", "output": "only"})
                + "\n"
            )
            MODULE.check_dataset(dataset)
        checks = {result.check: result for result in MODULE.RESULTS}
        self.assertIn("dataset-ceiling-risk", checks)
        self.assertEqual(checks["dataset-ceiling-risk"].status, MODULE.SKIP)
        self.assertEqual(checks["dataset-outputs"].status, MODULE.SKIP)
        self.assertIn("too few", checks["dataset-outputs"].detail)
        # And the size itself is still reported as the problem it is.
        self.assertEqual(checks["dataset-size"].status, MODULE.WARN)

    def test_two_identical_answers_are_still_a_finding(self) -> None:
        """The false-red direction: the guard is about one row, not about two."""
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "two.jsonl"
            dataset.write_text(
                "\n".join(
                    json.dumps(
                        {"id": f"r{index}", "input": f"question {index}", "output": "x"}
                    )
                    for index in range(2)
                )
                + "\n"
            )
            MODULE.check_dataset(dataset)
        checks = {result.check: result for result in MODULE.RESULTS}
        self.assertIn("dataset-ceiling-risk", checks)

    def test_an_exhausted_budget_emits_skip_rather_than_a_clean_result(self) -> None:
        """One of the two ways this check can fail to run must say so.

        Driven through `check_dataset` and not just the join, because the
        defect being guarded lived in the emit: the old ceiling produced a SKIP
        that nothing downstream distinguished from a pass. The budget is
        patched down rather than a pathological dataset built, so the test
        states the contract instead of the size at which it triggers.

        The other way is the memory ceiling below. Both are SKIPs and they are
        not interchangeable, so each of these tests also asserts the absence of
        the other's wording - a reader told the wrong limit fixes the wrong
        thing.
        """
        rows = [
            {
                "id": f"real-{index}",
                # A shared vocabulary, so the filter admits candidate pairs and
                # the budget is actually consulted. The rows are not similar
                # enough to BE near-duplicates: the scan finds nothing, runs
                # out of budget, and must not call that clean.
                "input": f"alpha beta gamma delta token{index}",
                "output": f"answer {index % 4}",
                "source": "production",
            }
            for index in range(40)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            with mock.patch.object(MODULE, "MAX_NEAR_DUPLICATE_WORK", 0):
                MODULE.check_dataset(dataset)
        near = next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-near-duplicates"
        )
        self.assertEqual(near.status, MODULE.SKIP, near.detail)
        self.assertIn("UNCHECKED", near.detail)
        self.assertNotIn("no high-similarity", near.detail)
        # And it must account for the wait, in terms of the dataset the reader
        # is holding. This is the one slow path in the script, so they have just
        # waited and are then told the check did not run; the detail has to name
        # what causes it or the pause reads as a hang.
        #
        # What it must name changed with the metric. Under word sets the causes
        # were long rows and a small vocabulary; under sequences both measure 0
        # operations, and the remaining cause is many rows phrased alike. A
        # sentence that still sent the reader to split long inputs would be
        # advice about a cost their file does not have.
        self.assertIn("phrased alike", near.detail)
        self.assertNotIn("small vocabulary", near.detail)
        # ...and not the memory ceiling's, which is a different limit with a
        # different remedy. This scan ran and ran out of comparisons.
        self.assertNotIn("MEMORY ceiling", near.detail)

    def _rows_of(self, count: int, words: int) -> list[dict]:
        """Rows whose runs are all distinct, so the count is the whole story."""
        return [
            {
                "id": f"real-{index}",
                "input": " ".join(f"w{index}x{position}" for position in range(words)),
                "output": f"answer {index % 4}",
                "source": "production",
            }
            for index in range(count)
        ]

    def _near_duplicate_result(self, rows: list[dict], **patches: object):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            with contextlib.ExitStack() as stack:
                for name, value in patches.items():
                    stack.enter_context(mock.patch.object(MODULE, name, value))
                MODULE.check_dataset(dataset)
        return next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-near-duplicates"
        )

    def test_a_dataset_too_large_to_index_skips_and_names_the_memory_ceiling(
        self,
    ) -> None:
        """The bound the work budget cannot see, and the reason it had to exist.

        `MAX_NEAR_DUPLICATE_WORK` counts operations, and on high-diversity rows
        it counts ZERO at every size: the index admits no candidates, so the
        counter never moves while the sets it is built from grow with the file.
        Measured on the shipped scan before this ceiling existed, 16,000 rows of
        300 words spent 0 operations, returned `complete`, and peaked at about
        36x the file - 1,538 MB. A dataset twice that size does not run slowly,
        it is killed, and a killed preflight prints nothing at all.

        So the SKIP has to name the MEMORY limit specifically. The work SKIP
        tells a reader to de-duplicate; that advice is actively wrong here,
        because this dataset is refused for being large and de-duplicating a
        corpus of distinct rows removes nothing.
        """
        rows = self._rows_of(12, 6)
        near = self._near_duplicate_result(rows, MAX_NEAR_DUPLICATE_SHINGLES=10)
        self.assertEqual(near.status, MODULE.SKIP, near.detail)
        self.assertIn("UNCHECKED", near.detail)
        self.assertIn("MEMORY ceiling", near.detail)
        # The measured size and the ceiling it failed, both of them, so the
        # reader can tell how far over they are rather than only that they are.
        self.assertIn(
            f"{12 * (6 - MODULE.NEAR_DUPLICATE_SHINGLE + 1):,} runs", near.detail
        )
        self.assertIn("10 run MEMORY ceiling", near.detail)
        # And never the work budget's wording or its remedy.
        self.assertNotIn("work budget", near.detail)
        self.assertNotIn("De-duplicate", near.detail)

    def test_the_memory_ceiling_is_consulted_before_the_index_is_built(self) -> None:
        """A ceiling checked after the allocation has bounded nothing.

        This is the whole mechanism, so it is measured rather than inferred from
        the SKIP. Asserting only that `near_duplicate_pairs` is never called is
        NOT enough, and that gap was found by writing the mutation instead of
        assuming it: an implementation that builds the list of one set per row,
        sums it, and then refuses passes that assertion while allocating the
        larger half of what it claims to be avoiding. The sets are two thirds of
        the peak on high-diversity rows and nearly all of it on repetitive ones.

        So the bound is compared against the thing it must stay under: the cost
        of the sets alone, measured here rather than written down as a constant
        that could quietly stop describing the code. Over the ceiling, the whole
        of `check_dataset` must peak BELOW what one list of shingle sets costs.
        """
        rows = self._rows_of(400, 60)
        values = [row["input"] for row in rows]

        tracemalloc.start()
        try:
            start = tracemalloc.get_traced_memory()[0]
            sets = [MODULE.shingle_set(value) for value in values]
            sets_cost = tracemalloc.get_traced_memory()[0] - start
            del sets
        finally:
            tracemalloc.stop()

        tracemalloc.start()
        try:
            with mock.patch.object(MODULE, "near_duplicate_pairs") as join:
                near = self._near_duplicate_result(rows, MAX_NEAR_DUPLICATE_SHINGLES=10)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

        join.assert_not_called()
        self.assertEqual(near.status, MODULE.SKIP, near.detail)
        self.assertLess(
            peak,
            sets_cost,
            f"refusing this dataset peaked at {peak:,} bytes, which is at least "
            f"what its {len(rows)} shingle sets cost to build ({sets_cost:,}). "
            "The ceiling is being applied after the index exists, so it bounds "
            "the report and not the memory - which is the defect it was added "
            "for, one step later in the same function.",
        )

    def test_a_dataset_inside_the_memory_ceiling_is_still_scanned(self) -> None:
        """The false-red direction, and the win this must not take back.

        A memory bound that refuses everything is trivially safe and useless -
        the point of #170's work bound was to stop a 500-row ceiling silently
        withdrawing this check from every dataset big enough to need it, and a
        ceiling set too low would reintroduce exactly that. Same rows as the
        test above, one ceiling above their real size instead of one below: the
        scan runs and answers.
        """
        rows = self._rows_of(12, 6)
        runs = 12 * (6 - MODULE.NEAR_DUPLICATE_SHINGLE + 1)
        near = self._near_duplicate_result(rows, MAX_NEAR_DUPLICATE_SHINGLES=runs)
        self.assertEqual(near.status, MODULE.PASS, near.detail)
        self.assertNotIn("UNCHECKED", near.detail)

    def test_the_index_size_is_a_conservative_upper_bound(self) -> None:
        """The pre-check may refuse early, but may never undercount allocation."""
        values = [
            "alpha beta gamma delta",  # 4 words -> 2 runs
            "one two",  # under n -> 1 run, not -1 and not 0
            "solo",  # under n -> 1 run
            "",  # no word characters -> no runs at all
            "repeat repeat repeat repeat",  # collapses to 1 distinct run
        ]
        built = [MODULE.shingle_set(value) for value in values]
        self.assertGreaterEqual(
            MODULE.near_duplicate_index_size(values),
            sum(len(tokens) for tokens in built),
        )
        self.assertEqual(MODULE.near_duplicate_index_size(values), 6)
        self.assertEqual([len(tokens) for tokens in built], [2, 1, 1, 0, 1])

    def test_one_oversized_row_is_counted_without_building_its_shingle_set(
        self,
    ) -> None:
        words = MODULE.MAX_NEAR_DUPLICATE_SHINGLES + MODULE.NEAR_DUPLICATE_SHINGLE
        value = "word " * words
        with mock.patch.object(
            MODULE, "shingle_set", side_effect=AssertionError("allocated the set")
        ):
            counted = MODULE.near_duplicate_index_size([value])
        self.assertGreater(counted, MODULE.MAX_NEAR_DUPLICATE_SHINGLES)

    def test_the_memory_ceiling_is_the_arithmetic_its_own_comment_states(
        self,
    ) -> None:
        """The ceiling is derived, so the derivation is what is checked.

        Every other guard here patches `MAX_NEAR_DUPLICATE_SHINGLES` to state a
        contract independent of its value, which is right - and leaves the
        shipped value itself guarded by nothing. Raising it to a number no
        measurement supports would pass all of them, and that is the failure
        this repository keeps finding: a constant whose justification sits
        beside it as prose and stops describing it.

        So the number is recomputed from the two figures its comment gives - the
        memory target, and the worst bytes-per-run of the shapes measured - and
        the comment's own division is checked against Python's. The table is
        read too: its worst row must BE the divisor, so adding a costlier shape
        without re-deriving fails here rather than being absorbed into prose.
        """
        source = SCRIPT.read_text()
        block = source.split("MAX_NEAR_DUPLICATE_WORK = ", 1)[1].split(
            "MAX_NEAR_DUPLICATE_SHINGLES = ", 1
        )[0]
        prose = " ".join(
            line.lstrip("#").strip() for line in block.splitlines()
        ).replace("  ", " ")

        target = re.search(r"add at most ([\d,]+) MB to peak RSS", prose)
        self.assertIsNotNone(target, "the comment no longer states a memory target")
        target_bytes = int(target.group(1).replace(",", "")) * 1_000_000

        derivation = re.search(
            r"([\d,]+) / ([\d,]+) = ([\d,]+) runs, rounded DOWN to ([\d,]+)", prose
        )
        self.assertIsNotNone(
            derivation, "the comment no longer shows how the ceiling was derived"
        )
        dividend, divisor, quotient, rounded = (
            int(group.replace(",", "")) for group in derivation.groups()
        )

        self.assertEqual(dividend, target_bytes, "the division is not of the target")
        self.assertEqual(
            quotient, dividend // divisor, "the comment's division is wrong"
        )
        self.assertEqual(rounded, MODULE.MAX_NEAR_DUPLICATE_SHINGLES)
        self.assertLessEqual(
            MODULE.MAX_NEAR_DUPLICATE_SHINGLES * divisor,
            target_bytes,
            "the shipped ceiling does not buy the memory target its comment "
            "claims. Re-measure and re-derive, or state a different target.",
        )

        measured = [
            int(row.group(1).replace(",", ""))
            for row in re.finditer(
                r"^#\s+[\d,]+ x [\d,]+ words\s+[\d,]+\s+[\d,]+ MB\s+(\d+)",
                block,
                re.MULTILINE,
            )
        ]
        self.assertGreaterEqual(len(measured), 5, "the measured table is gone")
        self.assertEqual(
            max(measured),
            divisor,
            "the ceiling is divided by a bytes-per-run figure that is not the "
            f"worst one measured ({max(measured)} appears in the table). The "
            "worst shape is the one the ceiling has to hold for.",
        )

    def test_the_first_run_sized_dataset_sits_well_inside_the_memory_ceiling(
        self,
    ) -> None:
        """The regression this fix could most easily cause, stated as a ratio.

        2,000 rows of 300 words is the shape the metric change was argued on:
        it SKIPs on trunk and COMPLETES on this branch, and the memory ceiling
        must not quietly take that back. Its index is 596,000 runs, and it is
        pinned here as a fraction of the ceiling rather than as a passing run,
        so moving either number - the ceiling down, or `NEAR_DUPLICATE_SHINGLE`
        up - fails here with both figures named instead of somewhere slower.

        Measured through `check_dataset` at that size, after this ceiling: PASS,
        208 MB peak, against 769 MB and 1,538 MB for the 8,000 and 16,000-row
        datasets the ceiling now refuses.
        """
        runs = 2_000 * (300 - MODULE.NEAR_DUPLICATE_SHINGLE + 1)
        self.assertEqual(runs, 596_000)
        self.assertLess(
            runs,
            MODULE.MAX_NEAR_DUPLICATE_SHINGLES * 0.6,
            f"a first-run-sized dataset indexes {runs:,} runs against a "
            f"{MODULE.MAX_NEAR_DUPLICATE_SHINGLES:,} ceiling, which is no "
            "longer comfortable. The ceiling exists to refuse datasets that "
            "would be killed, not the size this check was reinstated for.",
        )

    def test_corrupted_row_count_and_percentage_are_reported(self) -> None:
        valid_rows = [
            {"input": f"case {index}", "output": f"answer {index}"}
            for index in range(6)
        ]
        invalid_lines = [
            "{broken",
            json.dumps({"input": "missing output"}),
            json.dumps(["not", "an", "object"]),
            "{also broken",
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text(
                "\n".join([*(json.dumps(row) for row in valid_rows), *invalid_lines])
                + "\n"
            )
            rows = MODULE.check_dataset(dataset)
        self.assertEqual(len(rows or []), 6)
        integrity = next(
            result for result in MODULE.RESULTS if result.check == "dataset-integrity"
        )
        self.assertEqual(integrity.status, MODULE.FAIL)
        self.assertIn("4/10 rows (40.0%)", integrity.detail)

    def test_easy_only_real_dataset_warns_about_ceiling(self) -> None:
        rows = [
            {
                "id": f"real-{index}",
                "input": f"simple case {index}",
                "output": f"answer {index}",
                "difficulty": "easy",
            }
            for index in range(12)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        self.assertTrue(
            any(
                result.check == "dataset-difficulty"
                and result.status == MODULE.WARN
                and "ceiling effect" in result.detail
                for result in MODULE.RESULTS
            )
        )

    def test_dominant_expected_output_warns_about_hidden_failures(self) -> None:
        rows = [
            {
                "id": f"real-{index}",
                "input": f"case {index}",
                "output": "majority" if index < 9 else "minority",
            }
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        self.assertTrue(
            any(
                result.check == "dataset-ceiling-risk"
                and result.status == MODULE.WARN
                and "9/10" in result.detail
                for result in MODULE.RESULTS
            )
        )

    def test_total_answer_dominance_is_a_finding_not_an_unchecked_gap(self) -> None:
        """100% is the dominance check's worst case, not its absent case.

        `dataset-ceiling-risk` was raised only inside the `else` arm that runs
        when there is more than one distinct expected output. A dataset where
        EVERY answer is identical took the `len(output_counts) == 1` arm, which
        emitted `dataset-outputs` WARN and nothing else - so the one check that
        measures answer spread produced no record at the exact input it exists
        to catch.

        readiness.py reads a PASS on `dataset-outputs` as its witness that the
        spread was examined, so a WARN there left answer dominance reported as
        NEVER CHECKED, and an unmeasured sub-score drops out of the pillar
        average instead of deducting from it. The dataset with the worst
        possible answer spread therefore scored HIGHER than one with 90%
        dominance. Both records are asserted here, because either alone is
        satisfied by the shape that produced the inversion.
        """
        rows = [
            {"id": f"real-{index}", "input": f"case {index}", "output": "same"}
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        self.assertTrue(
            any(
                result.check == "dataset-outputs"
                and "every expected output is identical" in result.detail
                for result in MODULE.RESULTS
            ),
            "the degenerate-outputs finding is gone",
        )
        self.assertTrue(
            any(
                result.check == "dataset-ceiling-risk"
                and result.status == MODULE.WARN
                and "10/10" in result.detail
                and "100.0%" in result.detail
                for result in MODULE.RESULTS
            ),
            "total answer dominance raised no dominance record, so the score "
            "will report it as a check that never ran",
        )

    def test_dominant_structured_label_is_not_hidden_by_unique_reasons(self) -> None:
        rows = [
            {
                "id": f"real-{index}",
                "input": f"case {index}",
                "output": {
                    "label": "majority" if index < 9 else "minority",
                    "reason": f"unique reason {index}",
                },
            }
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        self.assertTrue(
            any(
                result.check == "dataset-ceiling-risk"
                and result.status == MODULE.WARN
                and "output field 'label'" in result.detail
                and "9/10" in result.detail
                for result in MODULE.RESULTS
            )
        )

    # ---------------------------------------------------------------- #216
    # Answer dominance is measured against chance, not against a fixed share
    # of the rows. Every case below is a dataset shape whose verdict the fixed
    # share got wrong, or one it got right that the new rule must not lose.

    @staticmethod
    def _dominance_verdict(counts: dict[str, int]) -> tuple[str, str] | None:
        """Run the shipped check over a dataset with this answer distribution.

        Inputs are deliberately all distinct. Repeated ANSWERS with distinct
        INPUTS are a correct dataset - `a`/`b`/`c`/`d` labels, a bibliography
        that cites the same author twice - and the repetition checks scan the
        input, so nothing here may charge them for the answers repeating.

        `RESULTS` is cleared here and not only in `setUp`. It is a module-level
        accumulator, so a second call in one test method used to read back the
        FIRST call's record - which passes silently whenever the first dataset
        is clean, and turns the second assertion into a statement about the
        wrong dataset the moment it is not.
        """
        MODULE.RESULTS.clear()
        rows = []
        for answer, count in counts.items():
            for _ in range(count):
                index = len(rows)
                rows.append(
                    {
                        "id": f"real-{index}",
                        "input": f"question {index} about topic {index}",
                        "output": answer,
                    }
                )
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        for result in MODULE.RESULTS:
            if result.check == "dataset-ceiling-risk":
                return result.status, result.detail
        return None

    def test_balanced_binary_dataset_is_not_a_ceiling_risk(self) -> None:
        """The false red this change must not create - not one it removes.

        Deliberately stated that way round, because the opposite is easy to
        write and wrong: the shipped 0.9-of-rows rule was already silent here,
        so this test PASSES on the old code and demonstrates no bug. #216 is an
        under-reach, not a false red - nothing was broken, and the defect was a
        false GREEN on the skewed four-way set below.

        What it does guard is the direction a chance-relative rule could go
        wrong. 50% of the rows is the BEST a yes/no dataset can do, and it is
        also twice chance on an a/b/c/d set; both are 50%, only one is a
        finding. A rule that reached the second by charging the first would have
        traded an under-reach for a false red on the most ordinary dataset
        there is. Balanced scores zero excess at every label count, which is
        what makes one rule right for both.
        """
        self.assertIsNone(self._dominance_verdict({"yes": 100, "no": 100}))

    def test_balanced_four_way_dataset_is_not_a_ceiling_risk(self) -> None:
        self.assertIsNone(self._dominance_verdict({"a": 50, "b": 50, "c": 50, "d": 50}))

    def test_skewed_binary_dataset_is_a_ceiling_risk(self) -> None:
        """95/5, which the shipped rule also flags - and by the same arm.

        95% clears the absolute share, so this dataset never reaches the
        chance-relative rule at all and the test would pass unchanged on the old
        code. It is here as a non-regression guard and is labelled as one; the
        case below is the one that exercises the new arm on a binary set.
        """
        verdict = self._dominance_verdict({"yes": 190, "no": 10})
        self.assertIsNotNone(verdict)
        status, detail = verdict
        self.assertEqual(status, MODULE.WARN)
        self.assertIn("190/200", detail)
        self.assertIn("needs no chance baseline", detail)

    def test_a_binary_set_below_the_absolute_share_is_reached_by_chance(self) -> None:
        """80/20: silent under the shipped rule, flagged by the new one.

        The binary case that actually enters the chance-relative arm. 80% is
        under the 90% absolute share, so the floor cannot answer it; against a
        50% baseline it is 60% of the way from chance to a perfect score, well
        past the line. Asserting the chance wording is what proves which arm
        ran - without it this test passes on an implementation that only ever
        compares shares.
        """
        verdict = self._dominance_verdict({"yes": 160, "no": 40})
        self.assertIsNotNone(verdict, "an 80/20 binary set was not reached")
        status, detail = verdict
        self.assertEqual(status, MODULE.WARN)
        self.assertIn("50.0% chance baseline", detail)
        self.assertIn("60% of the", detail)

    def test_skewed_four_way_dataset_is_a_ceiling_risk(self) -> None:
        """The dataset the fixed share could not reach, and the shape that
        pins the line.

        Chance is 25% and the top answer takes 50% - double chance, and a third
        of the way from chance to a perfect score. The shipped 0.9 rule is
        silent here. It sits EXACTLY on the line, which is why the comparison
        is made in exact rationals: in float the same shape at k=2 lands at
        0.33333333333333326 and falls the wrong side.
        """
        verdict = self._dominance_verdict({"a": 100, "b": 50, "c": 30, "d": 20})
        self.assertIsNotNone(verdict)
        status, detail = verdict
        self.assertEqual(status, MODULE.WARN)
        self.assertIn("25.0% chance baseline", detail)
        self.assertIn("4 distinct answers", detail)

    def test_binary_set_exactly_on_the_line_is_flagged_not_rounded_away(self) -> None:
        """A 2:1 binary split is one of the 200 shapes where float disagrees."""
        verdict = self._dominance_verdict({"yes": 200, "no": 100})
        self.assertIsNotNone(verdict, "a 2:1 binary split was rounded off the line")
        self.assertEqual(verdict[0], MODULE.WARN)

    def test_repeated_answers_with_distinct_inputs_are_not_a_fault(self) -> None:
        """Two datasets that are CORRECT and must stay uncharged.

        A closed-label task is supposed to reuse its labels, and a
        bibliographic set is supposed to cite the same author more than once.
        Near-duplicate detection is on the input; this check is about
        concentration. Neither may imply that a repeated answer is a defect.
        """
        self.assertIsNone(self._dominance_verdict({"a": 15, "b": 15, "c": 15, "d": 15}))
        self.assertIsNone(
            self._dominance_verdict({f"author {name}": 5 for name in range(12)})
        )

    def test_free_text_answers_report_unchecked_and_never_clean(self) -> None:
        """`1/k` is chance only when the answers repeat enough to have a share.

        On free text they do not: every row is its own answer, so `k` climbs
        with the row count and `1/k` is a fact about how many rows were read.
        The check declines - and a check that declines must say so. Reported as
        SKIP, which readiness.py scores as unasked; reporting it as PASS is the
        defect #158 was filed for.

        The message is asserted NOT to classify the task. An earlier revision
        told this customer their answers were "a sample of an open-ended answer
        space rather than a closed set of labels", which is a claim about their
        data rather than about this run's evidence - and one it got wrong on
        real label sets carrying rare labels.
        """
        counts = {"a shared sentence answer": 2}
        counts.update({f"a distinct sentence answer number {i}": 1 for i in range(64)})
        verdict = self._dominance_verdict(counts)
        self.assertIsNotNone(verdict, "free text produced no dominance record at all")
        status, detail = verdict
        self.assertEqual(status, MODULE.SKIP)
        self.assertIn("UNCHECKED", detail)
        self.assertNotIn("chance baseline for", detail)
        self.assertNotIn("open-ended", detail)
        self.assertNotIn("closed set of labels", detail)

    def test_a_long_tailed_label_set_is_measured_not_declined(self) -> None:
        """The false red the first regime gate shipped, kept as a guard.

        101 rows over 18 labels with 8 rare ones is an ordinary classification
        dataset. The first gate here compared the Good-Turing estimate of unseen
        answer mass against one label's fair share `1/k` - a test that tightens
        as `k` grows, which is exactly where a real label set carries rare
        labels - and declined on it, telling the customer their labels were an
        open-ended answer space. It must be measured, and found clean: the top
        label is on 30 of 101 rows against a 1-in-18 baseline.
        """
        counts = {"top": 30}
        counts.update({f"middle {index}": 7 for index in range(9)})
        counts.update({f"rare {index}": 1 for index in range(8)})
        self.assertIsNone(
            self._dominance_verdict(counts),
            "a long-tailed label set was declined or flagged",
        )

    def test_declining_never_withdraws_a_finding_the_old_rule_made(self) -> None:
        """The regression an earlier revision of this branch actually had.

        100 rows: 90 identical answers and 10 one-off ones. The shipped
        0.9-of-rows rule flags it. Under this branch's FIRST regime gate the
        chance-relative rule could not run on it - 10 singletons over 11
        answers - so it reported UNCHECKED, and an unmeasured diversity
        sub-score outscores a flagged one on 449 of 512 scored dataset shapes,
        by up to 6 points.

        The gate that produced that has since been replaced, and the current one
        measures this dataset rather than declining on it. The case is kept
        because the property is not "the current gate happens to be safe" but
        "declining can never withdraw an answer already given" - which is held
        by testing the absolute share ahead of the gate, so it survives the next
        time the gate moves.
        """
        counts = {"yes": 90}
        counts.update({f"a distinct one-off answer number {i}": 1 for i in range(10)})
        verdict = self._dominance_verdict(counts)
        self.assertIsNotNone(verdict)
        status, detail = verdict
        self.assertEqual(status, MODULE.WARN, "the gate silenced a shipped finding")
        self.assertIn("90/100", detail)
        self.assertIn("needs no chance baseline", detail)

    def test_no_shipped_finding_is_withdrawn_at_any_dataset_shape(self) -> None:
        """The case above, generalized: swept rather than sampled.

        Every answer-count multiset up to 40 rows with two or more distinct
        answers - 215,267 of them. Not one dataset that the 0.9-of-rows rule
        flags loses its finding. The reach in the other direction is real and
        deliberate: 23,032 shapes are newly flagged.
        """

        def partitions(total: int, largest: int) -> list[tuple[int, ...]]:
            if total == 0:
                return [()]
            out = []
            for first in range(min(total, largest), 0, -1):
                for rest in partitions(total - first, first):
                    out.append((first,) + rest)
            return out

        withdrawn = []
        newly_flagged = 0
        for rows in range(2, 41):
            for shape in partitions(rows, rows):
                if len(shape) < 2:
                    continue
                counts = MODULE.Counter(
                    {f"a{index}": count for index, count in enumerate(shape)}
                )
                finding = MODULE.answer_dominance_finding(
                    counts, subject="expected output"
                )
                status = finding[0] if finding else None
                if max(shape) / rows >= 0.9:
                    if status != MODULE.WARN:
                        withdrawn.append((rows, shape, status))
                elif status == MODULE.WARN:
                    newly_flagged += 1
        self.assertEqual(withdrawn[:5], [], f"{len(withdrawn)} findings withdrawn")
        self.assertGreater(newly_flagged, 0, "the chance-relative rule reaches nothing")

    def test_a_declined_subject_cannot_delete_another_subject_s_finding(self) -> None:
        """One `dataset-ceiling-risk` record, chosen by severity, not by order.

        Two subjects can produce a dominance verdict - the expected answers and
        a structured outcome field - and readiness reads preflight's records
        into a dict keyed by check name, so two records collapse to whichever
        was emitted last. Harmless while the only record was a finding; not
        harmless once one outcome is "did not run", because the loser of the
        collapse is a whole verdict.

        This dataset reaches both: the outputs are dicts carrying a distinct
        `reason` per row, so as whole answers they are free text and decline,
        while the `label` inside them is on 19 of 20 rows. The WARN must
        survive, and it must be the only ceiling-risk record on the run.
        """
        rows = [
            {
                "id": f"real-{index}",
                "input": f"question {index} about topic {index}",
                "output": {
                    "label": "same" if index < 19 else "other",
                    "reason": f"distinct reason {index}",
                },
            }
            for index in range(20)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        risks = [
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-ceiling-risk"
        ]
        self.assertEqual(len(risks), 1, f"dominance spoke {len(risks)} times: {risks}")
        self.assertEqual(
            risks[0].status,
            MODULE.WARN,
            "the declining subject overwrote the subject that found something",
        )
        self.assertIn("output field 'label'", risks[0].detail)

    def test_dominance_excess_is_total_and_never_divides_by_zero(self) -> None:
        """`1/k` at k=1 is 100%, so the general expression divides by zero.

        Nothing reaches it today - every caller tests the absolute share first,
        which catches a one-answer dataset at 100% - but that is protection by
        call order rather than by the function, and it would become a crash the
        moment a caller reordered. One answer on every row is total dominance,
        so the maximum is the answer the formula is reaching for anyway.
        """
        self.assertEqual(MODULE.dominance_excess(MODULE.Counter({"a": 40})), 1)
        self.assertEqual(MODULE.dominance_excess(MODULE.Counter({"a": 1})), 1)
        # And the shape that made it unreachable still resolves the same way.
        verdict = self._dominance_verdict({"same": 10})
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict[0], MODULE.WARN)

    def test_the_line_is_stated_in_shares_a_reader_can_check(self) -> None:
        """What one third of the way from chance to perfect IS, per label count.

        The number in the source is an excess, which nobody can check against
        their own file. These are the majority shares it corresponds to, and
        they are the reason one constant is right at every label count: 50% is
        clean for yes/no and a finding for a/b/c/d.
        """
        total = 90_000
        for labels, share in ((2, 0.667), (3, 0.556), (4, 0.500), (10, 0.400)):
            majority = round(share * total)
            counts = MODULE.Counter({"a0": majority})
            spread = total - majority
            for index in range(1, labels):
                counts[f"a{index}"] = spread // (labels - 1)
            excess = MODULE.dominance_excess(counts)
            self.assertAlmostEqual(
                float(excess),
                float(MODULE.DOMINANCE_EXCESS_THRESHOLD),
                places=2,
                msg=f"at {labels} labels the line is not {share:.1%} of the rows",
            )

    def test_explicit_nested_outcome_field_detects_nonstandard_schema(self) -> None:
        rows = [
            {
                "id": f"real-{index}",
                "input": f"case {index}",
                "output": {
                    "result": {
                        "priority": "normal" if index < 9 else "urgent",
                    },
                    "reason": f"unique reason {index}",
                },
            }
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset, "result.priority")
        self.assertTrue(
            any(
                result.check == "dataset-ceiling-risk"
                and "output field 'result.priority'" in result.detail
                for result in MODULE.RESULTS
            )
        )

    def test_preflight_does_not_mirror_sdk_call_binding(self) -> None:
        text = SCRIPT.read_text()
        for sdk_owned_detail in (
            "BaseEvaluator._should_expand_input_mapping",
            "InjectionMode",
            "dataset-binding",
            "scorer-signature",
            "Traigent 0.23",
            "--agent",
            "--scorer",
        ):
            self.assertNotIn(sdk_owned_detail, text)

    def test_local_model_check_does_not_open_a_socket(self) -> None:
        with mock.patch(
            "socket.socket.connect",
            side_effect=AssertionError("network access attempted"),
        ):
            MODULE.check_models(["openai/gpt-4o-mini"])
        self.assertFalse(any(result.status == MODULE.FAIL for result in MODULE.RESULTS))


class ASplitDrawnAlongTheTaskFamiliesTests(unittest.TestCase):
    """#242: `dataset-split` asks whether the sides are disjoint, and they were.

    A split whose tuning rows are all `def add`/`def max_of` and whose held-out
    rows are all `def is_even`/`def fib` is the STRONGEST form of disjoint, and
    that is the failure: the run tunes on one kind of work and reports its
    headline number on another. `dataset-near-duplicates` looks for rows too
    similar and this is rows too different across a boundary, so the condition
    fell between the two checks that could have seen it.

    The false-red direction is what most of these pin. The trigger is a CLEAN
    partition, so ordinary data has to survive it: a corpus of one-off phrasings
    with no recurring form, a corpus that really is one family, and one family
    per difficulty band split across the bands must all come back without a
    finding - and the two that cannot be answered must say so rather than pass.
    """

    def setUp(self) -> None:
        MODULE.RESULTS.clear()

    def _finding(self, rows: list[dict]) -> "MODULE.Result":
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        return next(
            result
            for result in MODULE.RESULTS
            if result.check == "dataset-split-family"
        )

    @staticmethod
    def _rows(families: dict[str, list[str]]) -> list[dict]:
        """One row per case, `{split: [family stem, ...]}` repeated four times."""
        rows: list[dict] = []
        for split, stems in families.items():
            for stem in stems:
                for case in range(4):
                    rows.append(
                        {
                            "id": f"{stem}-{case}".replace(" ", "-"),
                            "input": f"{stem} case number {case}",
                            "output": stem.split()[-1],
                            "split": split,
                            "difficulty": ("easy", "medium", "hard", "very-hard")[case],
                        }
                    )
        return rows

    def test_a_family_partitioned_split_is_named(self) -> None:
        finding = self._finding(
            self._rows(
                {
                    "tuning": ["def add", "def max_of"],
                    "holdout": ["def is_even", "def fib"],
                }
            )
        )
        self.assertEqual(finding.status, MODULE.WARN)
        self.assertIn("appears on one side of the split only", finding.detail)
        # The consequence, not just the observation. "Four families do not
        # cross" is a fact about the file; what the reader has to act on is
        # that the number the run produces answers a different question.
        self.assertIn("may not measure the task that was tuned", finding.detail)
        self.assertEqual(finding.metrics["families"], 4)
        self.assertEqual(finding.metrics["shared_families"], 0)

    def test_the_finding_names_its_guess_and_says_the_check_is_cheap(self) -> None:
        """A number the customer cannot check is worse than a guess they can.

        This reading is of leading words and never of meaning, so `refund
        request` and `refund claim` come back as two kinds of work where a
        person would say one. A finding that could not be wrong would have to
        cost a model call, and preflight makes none - so the honest shape is to
        say the check is cheap, name what it actually saw, and leave the
        judgment with the only party who can make it.
        """
        finding = self._finding(
            self._rows(
                {
                    "tuning": ["def add", "def max_of"],
                    "holdout": ["def is_even", "def fib"],
                }
            )
        )
        for form in ("add case", "max_of case", "is_even case", "fib case"):
            self.assertIn(form, finding.detail)
        self.assertIn("never from the meaning", finding.detail)
        self.assertEqual(finding.metrics["tuning_forms"], ["add case", "max_of case"])
        self.assertEqual(finding.metrics["holdout_forms"], ["fib case", "is_even case"])

    def test_a_long_form_list_is_bounded_rather_than_printed_whole(self) -> None:
        """The same bound `dataset-ids` applies to the row numbers it prints.

        A list long enough to scroll is one nobody reads, and the remainder is
        counted rather than dropped so the sentence never understates what was
        found.
        """
        tuning = [f"alpha{index} form" for index in range(6)]
        finding = self._finding(
            self._rows({"tuning": tuning, "holdout": ["beta one", "beta two"]})
        )
        self.assertEqual(finding.status, MODULE.WARN)
        self.assertEqual(
            len(finding.metrics["tuning_forms"]), MODULE.SPLIT_FAMILY_FORMS_SHOWN
        )
        self.assertIn(f"(+{6 - MODULE.SPLIT_FAMILY_FORMS_SHOWN} more)", finding.detail)

    def test_the_remainder_is_counted_however_the_forms_arrive(self) -> None:
        """A finding may run short of room; it may never understate what it found.

        Naming the sample and counting the total are two passes over the same
        argument. Against a generator the first exhausts it, the second counts
        zero, and the "+N more" clause vanishes - so the sentence would claim
        the four it printed were all there was. Both call sites pass a set
        today, which is precisely why the defect was silent.
        """
        forms = {f"form{index} here" for index in range(6)}
        expected = f"(+{6 - MODULE.SPLIT_FAMILY_FORMS_SHOWN} more)"
        self.assertIn(expected, MODULE._named_forms(forms))
        self.assertIn(expected, MODULE._named_forms(sorted(forms)))
        self.assertIn(expected, MODULE._named_forms(form for form in forms))
        # And it stays silent when there is nothing left over, rather than
        # printing "+0 more".
        self.assertNotIn("more", MODULE._named_forms({"only one"}))

    def test_the_same_rows_split_across_the_families_are_a_pass(self) -> None:
        """The identical material, redrawn - so the finding is the LINE, not the rows.

        Same four families, same sixteen inputs, same sizes on each side. The
        only difference is where the tuning/held-out line falls, and it is the
        only difference the finding may turn on.
        """
        partitioned = self._rows(
            {
                "tuning": ["def add", "def max_of"],
                "holdout": ["def is_even", "def fib"],
            }
        )
        crossed = [
            {**row, "split": "tuning" if int(row["id"][-1]) < 3 else "holdout"}
            for row in partitioned
        ]
        self.assertEqual(
            sorted(row["input"] for row in crossed),
            sorted(row["input"] for row in partitioned),
        )
        finding = self._finding(crossed)
        self.assertEqual(finding.status, MODULE.PASS)
        self.assertEqual(finding.metrics, {"families": 4, "shared_families": 4})

    def test_one_family_per_difficulty_band_split_across_the_bands_passes(self) -> None:
        """The false red the issue names first: families are not the defect."""
        rows = []
        bands = ("easy", "medium", "hard", "very-hard")
        stems = (
            "translate the phrase",
            "summarise the paragraph",
            "classify the ticket",
            "extract the entity",
        )
        for band, stem in zip(bands, stems):
            for case in range(8):
                rows.append(
                    {
                        "id": f"{band}-{case}",
                        "input": f"{stem} number {case} for the {band} case",
                        "output": stem.split()[0],
                        "difficulty": band,
                        "split": "tuning" if case < 6 else "holdout",
                    }
                )
        finding = self._finding(rows)
        self.assertEqual(finding.status, MODULE.PASS)
        self.assertEqual(finding.metrics, {"families": 4, "shared_families": 4})
        self.assertIn("does not follow the task families", finding.detail)

    def test_a_shared_opening_does_not_hide_the_families_behind_it(self) -> None:
        """The defect the offset exists for, and the reason it is not word zero.

        Every row opens `Calculate this question:` and the families sit three
        words later. Read from position zero the corpus has ONE signature, so
        the check answered PASS - "the split does not follow the task
        families" - over a split that partitions by family exactly. That is a
        confident wrong answer rather than a silence, and an instruction prefix
        is the ordinary shape of a real dataset, not a corner case.
        """
        stems = {
            "tuning": ["add two numbers", "find the maximum"],
            "holdout": ["check if even", "compute fibonacci"],
        }
        rows = [
            {
                "id": f"{split}-{stem}-{case}".replace(" ", "-"),
                "input": f"Calculate this question: {stem} for input set {case}",
                "output": "y",
                "split": split,
            }
            for split, group in stems.items()
            for stem in group
            for case in range(8)
        ]
        finding = self._finding(rows)
        self.assertEqual(finding.status, MODULE.WARN)
        self.assertEqual(finding.metrics["families"], 4)
        self.assertEqual(finding.metrics["shared_families"], 0)

    def test_one_template_and_a_counter_is_no_family_reading_at_all(self) -> None:
        """A corpus of `refund request number N` has no families to compare.

        This answered PASS before the offset landed, on the strength of the one
        signature the boilerplate produced - which was a statement about the
        template, not about the customer's work. Past the shared opening there
        is only a serial number, so nothing recurs and the honest answer is
        that the split could not be read against families.

        Worth pinning as its own case because the change that fixed the finding
        above moved this one, and moving it was the point: PASS is a claim that
        families exist AND cross the line, so it may not be reached by a corpus
        that has no families.
        """
        rows = [
            {
                "id": f"refund-{case}",
                "input": f"refund request number {case} for a returned order",
                "output": "refund",
                "split": "tuning" if case < 6 else "holdout",
            }
            for case in range(8)
        ]
        finding = self._finding(rows)
        self.assertEqual(finding.status, MODULE.SKIP)
        self.assertEqual(finding.metrics, {"families": 0})
        self.assertIn("no input form recurs", finding.detail)

    def test_one_unusual_opening_does_not_slide_the_window_back(self) -> None:
        """Why the boilerplate test is a share and not a strict common prefix.

        Thirty-one rows open `Calculate this question` and one opens `Compute
        this question`. Under `all()` the corpus shares no prefix at all, the
        window returns to word zero, and the families three words later go
        unread again - one row in thirty-two undoing the whole check.
        """
        stems = {
            "tuning": ["add two numbers", "find the maximum"],
            "holdout": ["check if even", "compute fibonacci"],
        }
        rows = [
            {
                "id": f"{split}-{stem}-{case}".replace(" ", "-"),
                "input": f"Calculate this question: {stem} for input set {case}",
                "output": "y",
                "split": split,
            }
            for split, group in stems.items()
            for stem in group
            for case in range(8)
        ]
        rows[0]["input"] = rows[0]["input"].replace("Calculate", "Compute", 1)
        finding = self._finding(rows)
        self.assertEqual(finding.status, MODULE.WARN)
        self.assertEqual(finding.metrics["shared_families"], 0)

    def test_two_wordings_of_one_task_are_reported_and_the_user_decides(self) -> None:
        """The limit of the inference, pinned rather than hidden.

        `refund request` and `refund claim` are one task written two ways, and a
        leading-form signature cannot know that. Split along them, the check
        reports a clean partition - correctly, by what it measures, and wrongly
        about the customer's work.

        This is the whole reason the readiness cap it feeds asks instead of
        blocking, and the reason the remedy is `review-split` rather than
        `resplit-dataset`: the customer is the only party who can say whether
        the two kinds are one task, and an inference may bound what a result
        claims without cancelling a run their own rows would have earned.
        """
        finding = self._finding(
            self._rows({"tuning": ["refund request"], "holdout": ["refund claim"]})
        )
        self.assertEqual(finding.status, MODULE.WARN)
        self.assertEqual(finding.metrics["families"], 2)
        self.assertEqual(finding.metrics["shared_families"], 0)
        # And it names them, so the person who can settle it sees exactly what
        # the check thought it saw.
        self.assertEqual(finding.metrics["tuning_forms"], ["request case"])
        self.assertEqual(finding.metrics["holdout_forms"], ["claim case"])

    def test_one_off_phrasings_are_skipped_rather_than_flagged(self) -> None:
        """The false red that would have fired on every ordinary dataset.

        Twenty support tickets each opening with its own product name is twenty
        one-row families, every one of which sits on exactly one side of any
        split by construction. Without the recurrence floor this check would
        find a clean partition in a file that has no families at all.
        """
        rows = [
            {
                "id": f"row-{index}",
                "input": f"Widget{index} will not sync after the latest update",
                "output": "technical",
                "split": "tuning" if index < 14 else "holdout",
            }
            for index in range(20)
        ]
        finding = self._finding(rows)
        self.assertEqual(finding.status, MODULE.SKIP)
        self.assertEqual(finding.metrics, {"families": 0})
        self.assertIn("no input form recurs", finding.detail)

    def test_a_reading_drawn_from_a_minority_of_the_rows_is_skipped(self) -> None:
        """Two clean families inside twenty one-off rows is not a clean split.

        The partition would be perfect over the four rows that recur and say
        nothing about the twenty that do not, so the honest answer is that the
        split was not read rather than that it partitions.
        """
        rows = [
            {
                "id": f"u{index}",
                "input": f"Widget{index} will not sync after the latest update",
                "output": "technical",
                "split": "tuning" if index < 10 else "holdout",
            }
            for index in range(20)
        ]
        rows += [
            {
                "id": f"{stem}-{case}".replace(" ", "-"),
                "input": f"{stem} case number {case}",
                "output": "y",
                "split": split,
            }
            for split, stem in (("tuning", "def add"), ("holdout", "def fib"))
            for case in range(2)
        ]
        finding = self._finding(rows)
        self.assertEqual(finding.status, MODULE.SKIP)
        self.assertEqual(finding.metrics, {"families": 2})
        self.assertIn("recurring input forms account for under 80%", finding.detail)

    def test_the_check_is_not_raised_where_there_is_no_boundary_to_read(self) -> None:
        """Overlap and a one-sided split answer a prior question.

        Under overlap the split is already condemned by `dataset-split` itself,
        and a tuning-only dataset has no held-out side for a family boundary to
        coincide with. Emitting SKIP for either would put an unanswerable
        question on the card beside the answer that matters.
        """
        for label, rows in (
            (
                "tuning-only",
                self._rows({"tuning": ["def add", "def fib"]}),
            ),
            (
                "overlapping",
                self._rows({"tuning": ["def add"], "holdout": ["def add"]}),
            ),
        ):
            with self.subTest(split=label):
                MODULE.RESULTS.clear()
                with tempfile.TemporaryDirectory() as directory:
                    dataset = Path(directory) / "eval.jsonl"
                    dataset.write_text(
                        "\n".join(json.dumps(row) for row in rows) + "\n"
                    )
                    MODULE.check_dataset(dataset)
                self.assertFalse(
                    any(
                        result.check == "dataset-split-family"
                        for result in MODULE.RESULTS
                    )
                )

    def test_the_signature_is_the_leading_pair_of_words(self) -> None:
        """The inferred thing, stated - the check is only as honest as this.

        One token collapses every `def` into one family and the check can never
        fire; three separates `def add(a, b)` from `def add(x, y)` and every row
        becomes its own family, which is the same silence from the other end.
        """
        self.assertEqual(MODULE.family_signature("def add(a, b):"), "def add")
        self.assertEqual(MODULE.family_signature("def is_even(n):"), "def is_even")
        self.assertEqual(
            MODULE.family_signature("SELECT count(*) FROM t"), "select count"
        )
        # No words at all is no signature, rather than a signature everything
        # unreadable shares - "unclassifiable" must not become a family.
        self.assertEqual(MODULE.family_signature("!!! ???"), "")

    def test_the_window_starts_where_the_rows_begin_to_differ(self) -> None:
        """Two words, counted from the first word that tells rows apart.

        The pair is the signature; where the pair starts is `family_offset`'s
        decision, and separating the two is what let the fixed-position version
        answer PASS over a boilerplate-prefixed corpus.
        """
        prefixed = [
            "Calculate this question: add two numbers",
            "Calculate this question: check if even",
        ]
        self.assertEqual(MODULE.family_offset(prefixed), 3)
        self.assertEqual(MODULE.family_signature(prefixed[0], 3), "add two")
        self.assertEqual(MODULE.family_signature(prefixed[1], 3), "check if")
        # Rows that differ from their first word are read from their first
        # word - there is no boilerplate to step over.
        self.assertEqual(MODULE.family_offset(["alpha one", "beta two"]), 0)
        # "Boilerplate" is relative to the corpus, which is worth pinning
        # because it surprises: two rows that are BOTH `def add` agree at word
        # one, so word one carries no information here and the window moves
        # past it. Add a third form and it starts discriminating again.
        self.assertEqual(MODULE.family_offset(["def add(a)", "def add(b)"]), 2)
        self.assertEqual(
            MODULE.family_offset(["def add a", "def add b", "def fib n", "def max q"]),
            1,
        )
        # It stops at the first discriminating word rather than skipping every
        # agreement it can find: `case` recurring later is a fact about the
        # family, and stepping over it would read the row's serial number.
        forms = ["def add case 1", "def add case 2", "def fib case 3", "def fib case 4"]
        self.assertEqual(MODULE.family_offset(forms), 1)
        self.assertEqual(MODULE.family_signature(forms[0], 1), "add case")
        # Rows agreeing at every position have nothing to tell them apart, so
        # the window stays at zero rather than running off the end.
        self.assertEqual(MODULE.family_offset(["same words", "same words"]), 0)
        self.assertEqual(MODULE.family_offset([]), 0)


class EvaluatorShapeCheckTests(unittest.TestCase):
    """traigent-first-run#133: a static, non-executing check on evaluator.py.

    `check_evaluator` only ever calls `ast.parse` on the file's text - it
    never imports, calls, or otherwise runs a line of it - so it can tell
    "present and parses" apart from "present but broken" and "absent"
    without touching whatever the file's own logic does. Whether a parseable
    file behaves like a real evaluator (for example, whether a constant-pass
    scorer's return ever depends on its input) is a behavioral question this
    check does not and cannot answer; that is `calibrate_evaluator.py`'s job,
    run separately and only after explicit approval.
    """

    def setUp(self) -> None:
        MODULE.RESULTS.clear()

    def _shape(self) -> dict:
        result = next(r for r in MODULE.RESULTS if r.check == "evaluator-shape")
        return {"status": result.status, **(result.metrics or {})}

    def test_absent_evaluator_file_is_reported_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            MODULE.check_evaluator(Path(directory) / "evaluator.py")
        shape = self._shape()
        self.assertEqual(shape["status"], MODULE.FAIL)
        self.assertFalse(shape["exists"])
        self.assertNotIn("parses", shape)

    def test_import_invalid_evaluator_fails_to_parse(self) -> None:
        """A syntax error is caught by `ast.parse` alone - nothing is run."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text("def score(output, expected:\n    return 1.0\n")
            MODULE.check_evaluator(path)
        shape = self._shape()
        self.assertEqual(shape["status"], MODULE.FAIL)
        self.assertTrue(shape["exists"])
        self.assertFalse(shape["parses"])

    def test_constant_pass_evaluator_parses_like_any_other_valid_python(self) -> None:
        """The static check cannot and does not claim to catch this.

        A constant-pass scorer is syntactically ordinary Python - it imports
        fine and has a plausible shape - so this check reports exactly what a
        real evaluator would report too: `parses: True`. Distinguishing the
        two requires observing behavior, which only calibration does.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text("def score(output, expected):\n    return 1.0\n")
            MODULE.check_evaluator(path)
        shape = self._shape()
        self.assertEqual(shape["status"], MODULE.PASS)
        self.assertTrue(shape["exists"])
        self.assertTrue(shape["parses"])

    def test_healthy_evaluator_parses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text(
                "def score(output, expected):\n"
                "    return 1.0 if output == expected else 0.0\n"
            )
            MODULE.check_evaluator(path)
        shape = self._shape()
        self.assertEqual(shape["status"], MODULE.PASS)
        self.assertTrue(shape["exists"])
        self.assertTrue(shape["parses"])

    def test_check_never_imports_the_file(self) -> None:
        """The check must not be trickable into executing the module.

        A module-level statement that raises on *import* (not on call) would
        surface as an exception here if this check ever imported the file
        instead of only parsing its syntax tree.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text(
                "raise RuntimeError('this must never execute during preflight')\n"
            )
            MODULE.check_evaluator(path)
        shape = self._shape()
        self.assertEqual(shape["status"], MODULE.PASS)
        self.assertTrue(shape["parses"])

    def test_a_file_the_parser_refuses_does_not_crash_the_run(self) -> None:
        """`ast.parse` refuses some input without raising `SyntaxError`.

        A ~50 KB file of chained unary operators makes CPython raise
        `MemoryError: Parser stack overflowed`. Uncaught, that ends the whole
        preflight process before it prints anything, so `--json` emits no
        JSON at all and the readiness scorer reading that stream gets
        nothing - a corrupted or oddly-formed file, not an exotic attack.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text("-" * 50_000 + "1\n")
            MODULE.check_evaluator(path)
        shape = self._shape()
        self.assertEqual(shape["status"], MODULE.FAIL)
        self.assertTrue(shape["exists"])
        self.assertFalse(shape["parses"])

    def test_the_whole_json_run_survives_a_file_the_parser_refuses(self) -> None:
        """The contract the crash actually broke: `--json` still emits JSON.

        Driven through the real CLI, because the defect was that the process
        died before reaching the `--json` print - which a direct call to
        `check_evaluator` alone would not have caught.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text("-" * 50_000 + "1\n")
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--evaluator",
                    str(path),
                    "--defer-missing-sdk",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
        self.assertIn(process.returncode, (0, 1), f"crashed: {process.stderr[-2000:]}")
        records = json.loads(process.stdout)
        shape = next(r for r in records if r["check"] == "evaluator-shape")
        self.assertEqual(shape["status"], MODULE.FAIL)
        self.assertFalse(shape["metrics"]["parses"])


class NoInternalFailureReachesTheUserAsATracebackTests(unittest.TestCase):
    """An unexpected error printed a traceback where the check results go.

    `main` handled the failures it could name and let every other one escape
    to the interpreter: exit 1, a stack naming this file, and no check output
    at all. The reader is running their first optimization; a defect in this
    script must not read as a defect in what they brought.
    """

    def _explode(self, error: BaseException) -> None:
        original = MODULE.check_python

        def boom() -> None:
            raise error

        MODULE.check_python = boom
        self.addCleanup(setattr, MODULE, "check_python", original)

    def test_an_unexpected_error_is_diagnosed_rather_than_dumped(self) -> None:
        for error in (KeyError("metrics"), TypeError("not subscriptable")):
            with self.subTest(error=type(error).__name__):
                self._explode(error)
                out, err = io.StringIO(), io.StringIO()
                with mock.patch.object(sys, "argv", ["preflight.py"]):
                    with redirect_stdout(out), redirect_stderr(err):
                        code = MODULE.main()
                self.assertEqual(code, MODULE.INTERNAL_ERROR_EXIT)
                self.assertEqual(out.getvalue(), "")
                self.assertIn(type(error).__name__, err.getvalue())
                self.assertNotIn("Traceback (most recent call last)", err.getvalue())

    def test_the_stack_is_still_available_to_whoever_is_fixing_it(self) -> None:
        stream = io.StringIO()
        code = MODULE.report_internal_error(
            "preflight.py",
            ValueError("boom"),
            environ={MODULE.TRACEBACK_ENV: "1"},
            stream=stream,
        )
        self.assertEqual(code, MODULE.INTERNAL_ERROR_EXIT)
        self.assertIn("ValueError: boom", stream.getvalue())

    def test_a_normal_run_is_untouched_by_the_boundary(self) -> None:
        """The false-red direction: nothing normal may be caught."""
        del MODULE.RESULTS[:]
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["preflight.py"]):
            with redirect_stdout(out), redirect_stderr(err):
                code = MODULE.main()
        self.assertIn(code, (0, 1))
        self.assertNotIn("internal error", err.getvalue())
        self.assertTrue(out.getvalue().strip())


class EveryRowCountIsAccountedForTests(unittest.TestCase):
    """A number over rows nothing scored is the failure that costs a decision.

    A dangling reference halts the run loudly and a maintainer fixes it in
    minutes. A row count is the other kind: the run finishes, the card prints a
    figure, and the customer acts on a number drawn over a set that is not the
    one they think it is. Nothing failed, so nothing said so.

    What this run can honestly check is bounded, and the bound is stated rather
    than papered over. `preflight.py` never executes the evaluator - it
    `ast.parse`s it, and its own PASS detail says the scoring behavior "is not
    executed here" - and no code in this package loops over dataset rows
    scoring them; the SDK does that. So "every row was scored" is NOT
    checkable here for any row, and this does not pretend otherwise. What is
    checkable is the arithmetic this run states about the rows it read, and
    that is what is checked.
    """

    def scan(self, rows: list[dict]) -> dict[str, dict[str, int]]:
        """Every row count one run publishes, by check."""
        del MODULE.RESULTS[:]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "dataset.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset)
        return {
            result.check: MODULE.row_counts(result.metrics)
            for result in MODULE.RESULTS
            if MODULE.row_counts(result.metrics)
        }

    def test_a_count_over_a_subset_names_the_file_it_was_drawn_from(self) -> None:
        """The bounded-subset promise, kept in data and not only in prose.

        The guidance rule for a bounded run is to report the subset size BESIDE
        the full row count, so a bounded run never reads as though the whole
        dataset was evaluated. The same claim was being made in the run's own
        numbers with nothing beside them: on this file the difficulty line says
        "12 of 12 rows carry a difficulty tag" over a 20-row file, because the
        eight rows it left out are the eight this method cannot score. Those
        eight are excluded BY DESIGN, which is exactly why the exclusion has to
        be visible - a row excluded by design is not a row silently dropped,
        and published alone the two are the same number.
        """
        rows = [
            {"input": f"q{index}", "output": f"a{index}", "difficulty": "easy"}
            for index in range(12)
        ] + [{"input": f"u{index}", "difficulty": "hard"} for index in range(8)]
        published = self.scan(rows)
        coverage = published["dataset-difficulty-coverage"]
        self.assertEqual(coverage["total_rows"], 12)
        self.assertEqual(
            coverage[MODULE.FULL_ROW_COUNT],
            20,
            "the difficulty line counts the rows this method can score and "
            "published that count alone, so 12 of a 20-row file read as 12 of "
            "12 - the whole file, scored",
        )

    def test_the_headline_row_count_the_card_prints_is_also_published(self) -> None:
        """The first number a customer reads had no machine twin at all.

        `dataset-shape` prints "N valid JSONL rows" and emitted no metrics, so
        the one count the card leads with was the one count nothing downstream
        could compare against anything.
        """
        rows = [{"input": f"q{index}", "output": f"a{index}"} for index in range(24)]
        shape = self.scan(rows)["dataset-shape"]
        self.assertEqual(shape, {"scoreable_rows": 24, MODULE.FULL_ROW_COUNT: 24})

    def test_a_count_larger_than_the_file_is_refused(self) -> None:
        """And refused as OUR defect, in our name, printing nothing."""
        del MODULE.RESULTS[:]
        MODULE.emit("dataset-shape", MODULE.PASS, "x", {"candidate_rows": 24})
        MODULE.emit(
            "dataset-difficulty-coverage", MODULE.PASS, "y", {"tagged_rows": 72}
        )
        with self.assertRaises(MODULE.RowCountMismatch) as raised:
            MODULE.validate_row_count_bounds(MODULE.RESULTS)
        self.assertIn("the file held 24 rows", str(raised.exception))
        self.assertIn(
            "dataset-difficulty-coverage.tagged_rows=72", str(raised.exception)
        )

    def test_the_mismatch_reaches_the_user_as_our_defect_and_no_card(self) -> None:
        """Read the message, not the exit code: the wording is the contract.

        A discrepancy between what this run claims and what it counted is a
        defect in the check. It must not arrive looking like a finding about
        the customer's dataset, and no partial card may print beside it.
        """
        rows = [
            {"input": f"q{index}", "output": f"a{index}", "difficulty": "easy"}
            for index in range(24)
        ]
        real_emit = MODULE.emit

        def triple(check, status, detail, metrics=None):
            if check == "dataset-difficulty-coverage" and metrics:
                metrics = dict(metrics, tagged_rows=metrics["tagged_rows"] * 3)
            real_emit(check, status, detail, metrics)

        del MODULE.RESULTS[:]
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "dataset.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            with mock.patch.object(MODULE, "emit", triple):
                with mock.patch.object(
                    sys, "argv", ["preflight.py", "--dataset", str(dataset)]
                ):
                    with redirect_stdout(out), redirect_stderr(err):
                        code = MODULE.main()
        self.assertEqual(code, MODULE.INTERNAL_ERROR_EXIT)
        self.assertIn("defect in the check rather than in your project", err.getvalue())
        self.assertIn("a count over rows the file did not contain", err.getvalue())
        self.assertEqual(
            out.getvalue(),
            "",
            "a card printed beside an unaccountable count, so the customer "
            "read numbers this run had already failed to stand behind",
        )

    def test_a_legitimately_bounded_run_is_clean(self) -> None:
        """The false-red direction, and the one that decides whether this ships.

        Rows excluded by design are the ORDINARY case, not the defect. A run
        that reconciles must stay silent on one, or the check teaches people to
        route around it.
        """
        rows = [
            {"input": f"q{index}", "output": f"a{index}", "difficulty": "easy"}
            for index in range(12)
        ] + [{"input": f"u{index}", "difficulty": "hard"} for index in range(8)]
        published = self.scan(rows)
        self.assertIsNone(MODULE.validate_row_count_bounds(MODULE.RESULTS))
        for check, counts in published.items():
            for key, value in counts.items():
                self.assertLessEqual(
                    value, 20, f"{check}.{key} counts more rows than the file holds"
                )

    def test_the_reconciliation_is_not_vacuous(self) -> None:
        """Neuter the rule and the probe above must stop being caught."""
        blind = [MODULE.Result("dataset-shape", MODULE.PASS, "x", {"rows": 999})]
        with self.assertRaises(MODULE.RowCountMismatch):
            MODULE.validate_row_count_bounds(blind)
        self.assertEqual(MODULE.row_counts({"bands": ["easy"], "rows": 3}), {"rows": 3})
        self.assertEqual(MODULE.row_counts(None), {})


class TheSubsetProposalCountsDifferentQuestionsTests(unittest.TestCase):
    """The number the bounded-draw rule names has to be the number preflight emits.

    `references/evaluation-and-dataset.md` rule 6 tells an assistant to draw
    different questions and to stop at the tuning split's different questions
    among the rows this run can score. That is a guidance sentence about a
    POPULATION and an IDENTITY, and the script can drift from either silently.

    Both axes have already been wrong here, which is why the fixtures below
    cross them rather than covering each alone. A review found the first
    version's coverage arranged so that no case tested both at once: the one
    fixture that declared a split never asserted the proposal, and the three
    that asserted the proposal never declared a split - two halves covered and
    the seam between them open, while the seam was where the defect was.

    * POPULATION. `#356` was the labelled axis: a distinct count over every
      tuning row bounding a comparison that only reaches the labelled ones.
      The split axis is the same defect one over: the guide hands preflight the
      combined file, so a count over every row answers about rows the draw
      never touches. On a 400-row tuning split asking 12 questions beside a
      held-out ten, that difference is six rows per configuration in every
      trial.
    * IDENTITY. `normalized_identity` keeps word characters and discards every
      operator, so `is x > 5` and `is x < 5` reach it as one string. Bounding a
      PAID draw with it deletes real test cases, and the walkthrough's own
      worked task is text to SQL. The draw uses `exact_input_identity`, which
      has no false positive.
    """

    def setUp(self) -> None:
        MODULE.RESULTS.clear()

    def scan(self, rows: list[dict], **kwargs: str) -> dict:
        MODULE.RESULTS.clear()
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "eval.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.check_dataset(dataset, **kwargs)
        return {result.check: result for result in MODULE.RESULTS}

    @staticmethod
    def held_out(count: int = 10, questions: int | None = None) -> list[dict]:
        """A held-out split that asks its own questions, which the draw may not count."""
        span = count if questions is None else questions
        return [
            {
                "id": f"hold-{index}",
                "input": f"does exhibit {index % span} contradict the filing",
                "output": "no",
                "split": "holdout",
            }
            for index in range(count)
        ]

    def test_the_proposal_counts_the_tuning_split_and_not_the_file(self) -> None:
        """The seam: a split IS declared and the proposal IS asserted.

        The guide mandates the combined, split-labelled file as preflight's
        input, so this is the ordinary path rather than a corner. The tuning
        split asks twelve questions; the held-out ten ask ten more; the file
        therefore holds twenty-two. Only one of those numbers may bound a draw
        that never leaves the tuning split.

        Both the count and the scope are asserted, because a count that is
        right by accident and a count that says what it counted are different
        guarantees, and only the second survives someone adding a third split.
        """
        rows = [
            {
                "id": f"tune-{index}",
                "input": f"question number {index % 12} about the quarterly filing",
                "output": f"answer {index % 12}",
                "split": "tuning",
            }
            for index in range(400)
        ]
        rows += self.held_out()
        finding = self.scan(rows)["dataset-first-run-rows"]
        self.assertEqual(finding.metrics["usable_rows"], 410)
        self.assertEqual(
            finding.metrics["first_run_distinct_rows"],
            12,
            "the count reaches rows outside the tuning split, so it is not the "
            "population the draw can be sized from",
        )
        self.assertEqual(
            finding.metrics["first_run_distinct_scope"], "the tuning split"
        )
        self.assertEqual(
            finding.metrics["first_run_questions"],
            12,
            "the proposal is above the questions the tuning split asks, so it "
            "prices calls no comparison can use",
        )
        self.assertIn("12 different inputs in the tuning split", finding.detail)

    def test_an_operator_is_not_a_repeat(self) -> None:
        """The identity axis, on the shape this walkthrough actually teaches.

        Forty questions differing only in their comparison operator are forty
        questions. Under the looser identity they are twenty, and the twenty
        dropped are test cases the customer wrote - a de-duplication that
        removes questions, which rule 6 forbids in as many words. Asserted
        against the SCRIPT's own two identities as well as against the count,
        so the reason a re-key would be wrong is pinned beside the count it
        would break.
        """
        self.assertEqual(
            MODULE.normalized_identity("is x > 5"),
            MODULE.normalized_identity("is x < 5"),
            "the looser identity stopped collapsing operators, so this fixture "
            "no longer distinguishes the two measures",
        )
        self.assertNotEqual(
            MODULE.exact_input_identity("is x > 5"),
            MODULE.exact_input_identity("is x < 5"),
        )
        rows = [
            {
                "id": f"op-{index}-{sign}",
                "input": f"is column_{index} {sign} 5",
                "output": "yes" if sign == ">" else "no",
                "split": "tuning",
            }
            for index in range(20)
            for sign in (">", "<")
        ]
        rows += [
            {
                "id": f"pad-{index}",
                "input": f"how many rows joined table {index}",
                "output": str(index),
                "split": "tuning",
            }
            for index in range(120)
        ]
        rows += self.held_out()
        finding = self.scan(rows)["dataset-first-run-rows"]
        self.assertEqual(
            finding.metrics["first_run_distinct_rows"],
            160,
            "the draw counted two operator questions as one, so it would cut "
            "the budget on a guess the rule refuses",
        )
        self.assertEqual(finding.metrics["first_run_questions"], 18)

    def test_a_multi_reference_split_counts_its_questions_not_its_rows(self) -> None:
        """Sixty questions under two accepted golds are sixty questions.

        The fixture is built from the shape rather than from any count this
        script computes: 60 questions written out, each once per accepted gold.
        The proposal is capped at eighteen QUESTIONS, and the rows those
        questions bring are what the run pays for - which is rule 6's own
        wording and the reason the cap is not a row count.
        """
        rows = []
        for index in range(60):
            for gold in ("yes", "affirmative"):
                rows.append(
                    {
                        "id": f"q{index}-{gold}",
                        "input": f"is claim number {index} supported by the passage",
                        "output": gold,
                        "split": "tuning",
                    }
                )
        rows += self.held_out(12)
        found = self.scan(rows)
        tuning = found["dataset-tuning-size"]
        self.assertEqual(tuning.metrics["tuning_rows"], 120)
        self.assertEqual(
            tuning.metrics["tuning_distinct_rows"],
            60,
            "the card would tell a reader 120 while the rule counts questions",
        )
        proposal = found["dataset-first-run-rows"]
        self.assertEqual(proposal.metrics["first_run_distinct_rows"], 60)
        self.assertEqual(
            proposal.metrics["first_run_questions"],
            18,
            "the cap is in questions, and eighteen questions is what rule 6 caps",
        )
        self.assertEqual(
            (
                proposal.metrics["first_run_rows_fewest"],
                proposal.metrics["first_run_rows_most"],
            ),
            (36, 36),
            "eighteen questions under two accepted golds bring thirty-six rows, "
            "and the run pays for the rows",
        )

    def test_the_subset_proposal_never_exceeds_the_questions_asked(self) -> None:
        """A file of 400 rows asking 12 questions may not be proposed 18 rows.

        Both numbers used to travel in one payload - `subset cap: 18` beside a
        distinct count of 12 - with nothing saying which governed, while the
        difference is six calls per configuration in every trial. No split is
        declared here on purpose: the fallback population is the whole
        scoreable set, because an undeclared split is a file the draw comes out
        of entire.
        """
        rows = [
            {
                "id": f"row-{index}",
                "input": f"question number {index % 12} about the quarterly filing",
                "output": f"answer {index % 12}",
            }
            for index in range(400)
        ]
        finding = self.scan(rows)["dataset-first-run-rows"]
        self.assertEqual(finding.metrics["usable_rows"], 400)
        self.assertEqual(finding.metrics["first_run_distinct_rows"], 12)
        self.assertEqual(finding.metrics["first_run_distinct_scope"], "this dataset")
        self.assertEqual(
            finding.metrics["first_run_questions"],
            12,
            "the proposal is above the questions this file asks, so it prices "
            "calls no comparison can use",
        )
        self.assertIn("12 different inputs in this dataset", finding.detail)

    def test_a_file_of_different_questions_keeps_the_full_proposal(self) -> None:
        """The other direction: the bound may not shrink an honest dataset.

        Pinned separately from the existing usable-rows test because that one
        would pass unchanged if the new bound were wired to always clamp - its
        fixture has no repeats to distinguish the two behaviours.
        """
        rows = [
            {
                "id": f"row-{index}",
                "input": f"question number {index} about the quarterly filing",
                "output": f"answer {index}",
            }
            for index in range(400)
        ]
        finding = self.scan(rows)["dataset-first-run-rows"]
        self.assertEqual(finding.metrics["first_run_distinct_rows"], 400)
        self.assertEqual(finding.metrics["first_run_questions"], 18)
        self.assertEqual(finding.metrics["first_run_rows_most"], 18)
        self.assertNotIn("different inputs in", finding.detail)

    def test_the_proposal_counts_only_rows_this_run_can_score(self) -> None:
        """The labelled axis, which is #356's own. Crossed with a declared split.

        A file half collected and half annotated is the ordinary state of one
        somebody is still working on. Its unlabelled rows cannot be scored, so
        they are not rows a configuration can be told apart on and not rows the
        draw may be sized from - and they are exactly what makes a count over
        every present row larger than the one the proposal may use.
        """
        questions = 12
        rows = [
            {
                "id": f"labelled-{index}",
                "input": f"question number {index % questions} about the filing",
                "output": f"answer {index % questions}",
                "split": "tuning",
            }
            for index in range(150)
        ]
        rows += [
            {
                "id": f"unlabelled-{index}",
                "input": f"draft question {index}",
                "split": "tuning",
            }
            for index in range(150)
        ]
        rows += self.held_out()
        finding = self.scan(rows)["dataset-first-run-rows"]
        self.assertEqual(finding.metrics["usable_rows"], 160)
        self.assertEqual(
            finding.metrics["first_run_distinct_rows"],
            questions,
            "the count reaches rows that carry no expected answer, so it is "
            "not the population the draw can be sized from",
        )
        self.assertEqual(
            finding.metrics["first_run_questions"],
            questions,
            "the proposal is above the questions this run can score, so it "
            "prices calls no comparison can use",
        )

    def test_a_blank_expected_answer_is_not_a_drawable_question(self) -> None:
        """The third scoping axis, and the one `rows` alone gets wrong.

        A row whose expected answer is present but blank survives
        normalization - the field is there - and is not scoreable, which is the
        one definition `dataset_row_is_labelled` exists to hold. Counting those
        rows made the draw's count say 160 in the same payload where
        `tuning_labelled_rows` said 120, which is the same two-populations
        shape as the labelled and split axes above, on the axis that looks
        already handled.

        Both numbers are asserted so the fixture cannot pass by coincidence:
        the card still reports what the split holds, and the draw reports only
        what it can be scored on.
        """
        self.assertFalse(MODULE.dataset_row_is_labelled({"output": ""}))
        rows = [
            {
                "id": f"answered-{index}",
                "input": f"question {index} about the filing",
                "output": "yes",
                "split": "tuning",
            }
            for index in range(120)
        ]
        rows += [
            {
                "id": f"blank-{index}",
                "input": f"question awaiting an answer {index}",
                "output": "",
                "split": "tuning",
            }
            for index in range(40)
        ]
        rows += self.held_out()
        found = self.scan(rows)
        self.assertEqual(found["dataset-tuning-size"].metrics["tuning_rows"], 160)
        self.assertEqual(
            found["dataset-tuning-size"].metrics["tuning_labelled_rows"], 120
        )
        self.assertEqual(
            found["dataset-first-run-rows"].metrics["first_run_distinct_rows"],
            120,
            "the draw counted rows whose expected answer is blank, so it is "
            "sized on questions no configuration can be scored on",
        )

    def test_the_card_prices_the_rows_the_capped_questions_bring(self) -> None:
        """N2: the cap is in questions and the money is in rows. Say both.

        The finding published one number, called it rows, and it was the
        question cap. On a split of 400 rows asking 200 questions that card
        read "18 usable rows" for a draw bringing 36, so the guide's twelve
        trial default priced 216 provider calls against 432 bought. Three
        vocabularies in one `min()`, which is the class this rule exists to
        close, on a fourth axis.

        What is asserted is what the numbers MEAN, not the sentence they sit
        in. Every expected value below is computed from the fixture's own shape
        - questions written out once per accepted answer - and never read off a
        constant the script also reads, so a rename or a re-key fails here.
        """
        questions, golds = 200, ("yes", "affirmative")
        rows = [
            {
                "id": f"q{index}-{gold}",
                "input": f"question number {index}",
                "output": gold,
                "split": "tuning",
            }
            for index in range(questions)
            for gold in golds
        ]
        finding = self.scan(rows)["dataset-first-run-rows"]
        cap = finding.metrics["first_run_questions"]
        fewest = finding.metrics["first_run_rows_fewest"]
        most = finding.metrics["first_run_rows_most"]
        self.assertEqual(finding.metrics["usable_rows"], questions * len(golds))
        self.assertEqual(finding.metrics["first_run_distinct_rows"], questions)
        self.assertEqual(
            (fewest, most),
            (cap * len(golds), cap * len(golds)),
            "the rows the capped questions bring are not published, so a run "
            f"priced from this card buys {len(golds)} times what it quotes",
        )
        self.assertIn(f"{cap} questions", finding.detail)
        self.assertIn(f"{most} scoreable rows", finding.detail)

    def test_an_uneven_file_is_priced_as_the_range_it_is(self) -> None:
        """One row number would be an invention where questions differ in cost.

        Which questions a draw takes is decided by the band floor and by the
        author, not by this check, so where questions bring different numbers
        of rows the honest answer is an interval. 150 questions of one row
        beside 20 of two: eighteen questions bring 18 at the arithmetic
        cheapest and 36 at the dearest.

        Untagged on purpose, and named as such. With no difficulty tags there
        is no band floor to forbid the cheapest questions, so both ends of the
        interval are reachable HERE - which is a property of this fixture, not
        of the method.
        `test_the_range_is_an_outer_bound_not_a_reachable_floor` carries the
        case where it is false, because a test that cannot break the claim it
        is named for is not evidence for it.
        """
        rows = [
            {
                "id": f"single-{index}",
                "input": f"single reference question {index}",
                "output": "x",
                "split": "tuning",
            }
            for index in range(150)
        ]
        rows += [
            {
                "id": f"double-{index}-{gold}",
                "input": f"double reference question {index}",
                "output": gold,
                "split": "tuning",
            }
            for index in range(20)
            for gold in ("p", "q")
        ]
        finding = self.scan(rows)["dataset-first-run-rows"]
        self.assertEqual(finding.metrics["first_run_questions"], 18)
        self.assertEqual(finding.metrics["first_run_rows_fewest"], 18)
        self.assertEqual(finding.metrics["first_run_rows_most"], 36)
        self.assertIn("between 18 and 36 scoreable rows", finding.detail)

    def test_the_range_is_an_outer_bound_not_a_reachable_floor(self) -> None:
        """N5: the band floor can forbid the cheapest questions, and this cannot see it.

        `rows_for` takes the cheapest and dearest questions by cost alone.
        Rule 6 also requires at least four questions from each of four
        difficulty bands, and nothing in `DrawableInputs` reads a row's
        difficulty, so where cost correlates with difficulty the arithmetic low
        end is below anything a compliant draw can reach.

        30 easy questions of one row beside 90 harder ones of three:

            arithmetic low end   : 18 questions x 1 row              = 18
            cheapest COMPLIANT   : 4 easy x 1 + 14 harder x 3        = 46
            arithmetic high end  : 18 questions x 3 rows             = 54

        The interval is honest and neither end is a quote. What is asserted is
        exactly that: the compliant floor lies strictly inside the reported
        interval, so the low end understates it. The 46 is computed here from
        the fixture's own shape and the band floor rule 6 states, never from
        anything the script returns, so a change that made `rows_for` band-aware
        would fail this deliberately rather than pass by coincidence.
        """
        rows = [
            {
                "id": f"easy-{index}",
                "input": f"cheap question {index}",
                "output": "a",
                "difficulty": "easy",
                "split": "tuning",
            }
            for index in range(30)
        ]
        rows += [
            {
                "id": f"hard-{index}-{gold}",
                "input": f"expensive question {index}",
                "output": gold,
                "difficulty": "hard",
                "split": "tuning",
            }
            for index in range(90)
            for gold in ("p", "q", "r")
        ]
        rows += self.held_out()
        finding = self.scan(rows)["dataset-first-run-rows"]
        cap = finding.metrics["first_run_questions"]
        fewest = finding.metrics["first_run_rows_fewest"]
        most = finding.metrics["first_run_rows_most"]
        self.assertEqual((cap, fewest, most), (18, 18, 54))

        band_floor = 4
        compliant_floor = band_floor * 1 + (cap - band_floor) * 3
        self.assertEqual(compliant_floor, 46)
        self.assertLess(
            fewest,
            compliant_floor,
            "the reported low end is at or above the cheapest compliant draw, "
            "so it is being quoted as a floor rather than as a bound",
        )
        self.assertLessEqual(compliant_floor, most)

    def test_a_reference_free_method_may_draw_an_unlabelled_row(self) -> None:
        """N3: the other branch of the labelled filter, which nothing pinned.

        `drawable_distinct_inputs` excludes rows carrying no expected answer,
        because no comparison reaches them - unless the method scores WITHOUT a
        reference, where every present row is scoreable and excluding them
        under-counts a draw that could have used them. Applying the filter
        unconditionally left the whole class green, so the correct branch was
        correct by accident.

        Both branches run over one fixture, and the assertion is the difference
        between them rather than either number alone: 60 labelled questions
        beside 60 unlabelled ones is 60 under a referenced method and 120 under
        a reference-free one. A filter applied unconditionally ties them.
        """
        rows = [
            {
                "id": f"labelled-{index}",
                "input": f"answered question {index}",
                "output": "a",
                "split": "tuning",
            }
            for index in range(60)
        ]
        rows += [
            {
                "id": f"unlabelled-{index}",
                "input": f"question awaiting an answer {index}",
                "split": "tuning",
            }
            for index in range(60)
        ]
        referenced = self.scan(rows)["dataset-first-run-rows"].metrics
        method = sorted(MODULE.REFERENCE_FREE_METHODS)[0]
        free = self.scan(rows, evaluator_method=method)[
            "dataset-first-run-rows"
        ].metrics
        self.assertEqual(referenced["first_run_distinct_rows"], 60)
        self.assertEqual(
            free["first_run_distinct_rows"],
            120,
            "a reference-free draw was cut to the labelled rows, so it prices "
            "half the questions it could have compared",
        )
        self.assertGreater(
            free["first_run_distinct_rows"], referenced["first_run_distinct_rows"]
        )

    def test_the_bound_is_applied_only_where_the_subset_applies(self) -> None:
        """The helper itself, at the two boundaries the emit cannot reach.

        A caller with no question count gets the row-based answer rather than a
        wrong one, and a caller with one is capped at eighteen only above
        `BOUNDED_SUBSET_ABOVE_ROWS`, because below it the run scores the whole
        dataset and there is no subset to cut.

        Below the threshold the cap is the file's own question count, and that
        is a correction rather than a relaxation: the previous spelling
        returned the ROW count there and called it a cap, which is the same
        two-vocabularies defect the emit above had. A 40-row file asking 7
        questions has 7 questions and 40 rows, and both are now said.
        """
        # Above the threshold the eighteen governs, bounded by the questions.
        self.assertEqual(MODULE.first_run_question_cap(400), 18)
        self.assertEqual(MODULE.first_run_question_cap(400, 400), 18)
        self.assertEqual(MODULE.first_run_question_cap(400, 12), 12)
        self.assertEqual(MODULE.first_run_question_cap(101, 12), 12)
        # At and below it there is no subset, so the cap is every question the
        # file asks - not eighteen, and not the ROW count, which is what the
        # previous spelling returned here and is a different quantity whenever
        # a question carries more than one row.
        self.assertEqual(MODULE.first_run_question_cap(100, 12), 12)
        self.assertEqual(MODULE.first_run_question_cap(40, 40), 40)
        self.assertEqual(MODULE.first_run_question_cap(40, 7), 7)
        # And with nobody having counted, the row-based figure this check
        # published before the count existed.
        self.assertEqual(MODULE.first_run_question_cap(40), 40)

    def test_an_unmeasured_count_is_not_a_count_of_zero(self) -> None:
        """`None` means nobody counted. Reading it as 0 prices the run at nothing.

        The two branches are pinned against each other rather than separately,
        which is the only arrangement that fails on the collapse. `or 0` turns
        the unmeasured case into the measured-nothing case, and a payload
        written before this count existed then proposes a first run of zero
        rows - the same shape as the defect this rule exists to fix, pointed
        the other way: a number standing in for a measurement nobody took.

        A genuine zero is left alone on purpose. It is unreachable through
        `check_dataset`, which returns before this on an empty scoreable set,
        so the assertion is on the helper's own contract and says what a future
        caller may rely on.
        """
        unmeasured = MODULE.first_run_question_cap(400, None)
        measured_nothing = MODULE.first_run_question_cap(400, 0)
        self.assertEqual(
            unmeasured,
            18,
            "an absent count bounded the proposal, so a payload that predates "
            "the count prices a run it never measured",
        )
        self.assertEqual(measured_nothing, 0)
        self.assertNotEqual(
            unmeasured,
            measured_nothing,
            "None and 0 now give the same answer, so nothing distinguishes "
            "'nobody counted' from 'there is nothing to draw'",
        )

    def test_the_draw_and_the_sibling_key_describe_one_population(self) -> None:
        """The two counts differ by IDENTITY and must never differ by population.

        `tuning_distinct_scoreable_rows` is the tuning-and-scoreable count a
        comparison may be bounded by, and it is taken on `normalized_identity`.
        The draw takes the same population on `exact_input_identity`, because
        this one cuts a paid budget and that one does not. Keeping the identity
        different is deliberate; keeping the population different is the defect
        that has now appeared here on three axes, so it is pinned rather than
        left to two walks agreeing by habit.

        Two fixtures, because equality alone would also hold if both counts
        were wrong the same way.

        * Where no two questions collapse under the looser identity the two
          numbers are EQUAL. The fixture carries a held-out split, unlabelled
          tuning rows AND blank-answer tuning rows, so each of the three
          populations this sentence names is one the fixture can actually catch
          the draw reaching. An earlier version made that claim over rows that
          were entirely labelled, where two thirds of it was untrue: dropping
          the labelled filter left this test green and only the blank-answer
          case held it. An overclaimed contract is a small lie a later reader
          relies on, so the fixture was widened rather than the sentence
          narrowed.
        * Where exactly twenty pairs collapse, the difference is exactly twenty
          and the draw's count is the larger. A draw that had quietly adopted
          the looser identity would tie instead.
        """
        agreeing = [
            {
                "id": f"plain-{index}",
                "input": f"how many rows joined table {index}",
                "output": str(index),
                "split": "tuning",
            }
            for index in range(60)
        ]
        agreeing += [
            {
                "id": f"unlabelled-{index}",
                "input": f"question with no answer yet {index}",
                "split": "tuning",
            }
            for index in range(15)
        ]
        agreeing += [
            {
                "id": f"blank-{index}",
                "input": f"question with a blank answer {index}",
                "output": "",
                "split": "tuning",
            }
            for index in range(15)
        ]
        agreeing += self.held_out()
        found = self.scan(agreeing)
        self.assertEqual(
            found["dataset-first-run-rows"].metrics["first_run_distinct_rows"],
            found["dataset-tuning-size"].metrics["tuning_distinct_scoreable_rows"],
            "the draw and the key it parallels no longer count the same rows",
        )

        collapsing = (
            [row for row in agreeing if row["id"].startswith("plain-")]
            + [
                {
                    "id": f"op-{index}-{sign}",
                    "input": f"is column_{index} {sign} 5",
                    "output": "yes" if sign == ">" else "no",
                    "split": "tuning",
                }
                for index in range(20)
                for sign in (">", "<")
            ]
            + self.held_out()
        )
        found = self.scan(collapsing)
        draw = found["dataset-first-run-rows"].metrics["first_run_distinct_rows"]
        key = found["dataset-tuning-size"].metrics["tuning_distinct_scoreable_rows"]
        self.assertEqual(
            draw - key,
            20,
            "the draw and the key differ by something other than the twenty "
            "operator pairs, so one of them changed population",
        )
        self.assertGreater(draw, key)

    def test_the_scope_travels_with_the_number(self) -> None:
        """A count with no population is the shape both defects wore.

        Every payload states which rows it counted, so a reader never has to
        infer it from a second field, and a third split cannot silently change
        what the number means.
        """
        for label, rows in (
            (
                "the tuning split",
                [
                    {
                        "id": f"t{index}",
                        "input": f"q{index}",
                        "output": "a",
                        "split": "train",
                    }
                    for index in range(30)
                ]
                + self.held_out(),
            ),
            (
                "this dataset",
                [
                    {"id": f"n{index}", "input": f"q{index}", "output": "a"}
                    for index in range(30)
                ],
            ),
        ):
            with self.subTest(scope=label):
                finding = self.scan(rows)["dataset-first-run-rows"]
                self.assertEqual(finding.metrics["first_run_distinct_scope"], label)


class TheDistinctCountAndTheCountItBoundsDescribeOneSetTests(unittest.TestCase):
    """Two counts over two populations cannot bound each other (#356).

    `tuning_distinct_rows` counts the different inputs on the tuning side of the
    line, every row of it. The number readiness bounds with it counted only the
    rows it can SCORE. On a file where those are the same rows the mistake is
    invisible; on a file half annotated they are different rows, and the larger
    count satisfied the guard on the strength of rows the comparison never sees.

    The fixtures below are built from row counts and question texts, never from
    the keys the assertions read, so a metric renamed or narrowed in place fails
    here rather than passing on its own definition.
    """

    def setUp(self) -> None:
        MODULE.RESULTS.clear()

    def _tuning_metrics(self, rows: list[dict], **kwargs: str) -> dict:
        with tempfile.TemporaryDirectory() as raw:
            dataset = Path(raw) / "dataset.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.RESULTS.clear()
            MODULE.check_dataset(dataset, **kwargs)
        return next(
            result.metrics
            for result in MODULE.RESULTS
            if result.check == "dataset-tuning-size"
        )

    @staticmethod
    def _mixed_rows() -> list[dict]:
        """The reproduction filed on the issue, written out rather than derived.

        Twenty labelled tuning rows asking ten questions, forty unlabelled
        tuning rows each asking its own, and ten held back. The honest count of
        questions this run can score on the tuning side is ten.
        """
        rows = [
            {
                "id": f"labelled-{index}",
                "input": f"question number {index % 10} about the billing system",
                "output": f"answer-{index % 10}",
                "split": "tune",
            }
            for index in range(20)
        ]
        rows += [
            {
                "id": f"silent-{index}",
                "input": f"unlabelled question number {index} about shipping",
                "split": "tune",
            }
            for index in range(40)
        ]
        rows += [
            {
                "id": f"held-{index}",
                "input": f"held out question number {index} about accounts",
                "output": f"answer-h{index}",
                "split": "holdout",
            }
            for index in range(10)
        ]
        return rows

    def test_a_half_labelled_tuning_side_counts_the_questions_it_can_score(
        self,
    ) -> None:
        metrics = self._tuning_metrics(self._mixed_rows())
        self.assertEqual(metrics["tuning_rows"], 60)
        self.assertEqual(metrics["tuning_labelled_rows"], 20)
        # The older count is unchanged and still true of the file: fifty
        # different inputs sit on the tuning side. It is the population that is
        # wrong for bounding a comparison, not the arithmetic.
        self.assertEqual(metrics["tuning_distinct_rows"], 50)
        self.assertEqual(
            metrics["tuning_distinct_scoreable_rows"],
            10,
            "the scoreable distinct count is not counting the labelled rows "
            "alone, so it can be satisfied by rows no comparison scores",
        )

    def test_unlabelled_rows_cannot_lift_the_count_that_bounds_the_comparison(
        self,
    ) -> None:
        """Adding rows the run cannot score moves one count and not the other."""
        rows = self._mixed_rows()
        fewer = [row for row in rows if not row["id"].startswith("silent-")]
        with_silent = self._tuning_metrics(rows)
        without_silent = self._tuning_metrics(fewer)
        self.assertEqual(
            with_silent["tuning_distinct_scoreable_rows"],
            without_silent["tuning_distinct_scoreable_rows"],
        )
        self.assertGreater(
            with_silent["tuning_distinct_rows"],
            without_silent["tuning_distinct_rows"],
        )

    def test_a_fully_labelled_tuning_side_gives_both_counts_the_same_answer(
        self,
    ) -> None:
        """Where every tuning row is scoreable the two populations coincide.

        This is the direction that must NOT move: a narrower count is only
        correct where some rows are unscoreable, and one that came in low on an
        ordinary fully-labelled file would bound a comparison that has nothing
        wrong with it.
        """
        rows = [
            {
                "id": f"row-{index}",
                "input": f"a distinct question numbered {index}",
                "output": f"answer-{index}",
                "split": "tune",
            }
            for index in range(14)
        ]
        metrics = self._tuning_metrics(rows)
        self.assertEqual(metrics["tuning_rows"], 14)
        self.assertEqual(metrics["tuning_distinct_rows"], 14)
        self.assertEqual(metrics["tuning_distinct_scoreable_rows"], 14)

    def test_a_reference_free_method_can_score_a_row_carrying_no_answer(
        self,
    ) -> None:
        """Under a judge needing no gold answer, every present row is scoreable.

        So the two counts have to agree again on the same file where they
        disagreed above - the difference between them is a property of the
        method, not of the rows, and a count that stayed narrow here would
        report a repetition this dataset does not have.
        """
        rows = self._mixed_rows()
        method = sorted(MODULE.REFERENCE_FREE_METHODS)[0]
        metrics = self._tuning_metrics(rows, evaluator_method=method)
        self.assertEqual(
            metrics["tuning_distinct_scoreable_rows"],
            metrics["tuning_distinct_rows"],
        )
        self.assertEqual(metrics["tuning_distinct_scoreable_rows"], 50)


class ATruncatedListSaysThatItIsTruncatedTests(unittest.TestCase):
    """#378: two lists stopped at ten entries and said nothing about it.

    `dataset-ids` printed ten colliding ids and `dataset-duplicates` ten groups
    of repeated rows, in both cases with no ellipsis and no total - so a file
    with thirty findings and a file with ten printed lines a reader could not
    tell apart. The missing-id sentence three lines above `dataset-ids` already
    led with its count and closed with "(first 10 shown)", so the shape these
    two now take is the file's own and not a new convention.

    The count is asserted separately from the truncation marker, because they
    fail differently: a list of exactly ten findings must print the count and
    must NOT claim to be partial.
    """

    def setUp(self) -> None:
        MODULE.RESULTS.clear()

    def _details(self, repeats: int, *, share_ids: bool) -> dict[str, str]:
        """One file with `repeats` repeated rows, ids colliding or not.

        The repeats are copies of distinct rows, so the two checks see the same
        number of findings and either list can be read against the other.
        """
        distinct = [
            {
                "id": f"row-{index:03d}",
                "input": f"question {index} about the billing system and its rules",
                "output": f"answer-{index % 4}",
                "source": "production-log",
            }
            for index in range(40)
        ]
        copied = [dict(row) for row in distinct[:repeats]]
        if not share_ids:
            for offset, row in enumerate(copied, start=1):
                row["id"] = f"row-{40 + offset:03d}"
        with tempfile.TemporaryDirectory() as raw:
            dataset = Path(raw) / "dataset.jsonl"
            dataset.write_text(
                "\n".join(json.dumps(row) for row in distinct + copied) + "\n"
            )
            MODULE.RESULTS.clear()
            MODULE.check_dataset(dataset)
        return {result.check: result.detail for result in MODULE.RESULTS}

    def test_thirty_findings_say_thirty_and_say_the_list_is_partial(self) -> None:
        details = self._details(30, share_ids=True)
        self.assertTrue(details["dataset-ids"].startswith("30 duplicate ids:"))
        self.assertIn("(first 10 shown)", details["dataset-ids"])
        self.assertTrue(
            details["dataset-duplicates"].startswith(
                "30 exact/normalized duplicate inputs at rows"
            )
        )
        self.assertIn("(first 10 shown)", details["dataset-duplicates"])
        # The list itself is still bounded, which is what the marker is for.
        self.assertEqual(details["dataset-ids"].count("row-"), 10)

    def test_a_complete_list_carries_its_count_and_no_truncation_marker(
        self,
    ) -> None:
        """The false-red direction, at exactly the boundary.

        Ten findings fit, so claiming the list is partial would be the same
        defect running the other way: a reader told to expect more than they can
        see. The count still leads, because a reader must not have to add up a
        bracketed list to learn how many there are.
        """
        details = self._details(10, share_ids=True)
        self.assertTrue(details["dataset-ids"].startswith("10 duplicate ids:"))
        self.assertNotIn("shown)", details["dataset-ids"])
        self.assertTrue(
            details["dataset-duplicates"].startswith(
                "10 exact/normalized duplicate inputs at rows"
            )
        )
        self.assertNotIn("shown)", details["dataset-duplicates"])

    def test_the_repetition_list_does_not_depend_on_the_ids(self) -> None:
        """The two checks answer two questions, and only one reads an id.

        Renumbering the repeats clears `dataset-ids` and leaves
        `dataset-duplicates` reporting exactly what it reported before. Without
        this the count added above could be satisfied by a check that had
        quietly started reading identities.
        """
        colliding = self._details(30, share_ids=True)
        renumbered = self._details(30, share_ids=False)
        self.assertEqual(
            colliding["dataset-duplicates"], renumbered["dataset-duplicates"]
        )
        self.assertEqual(renumbered["dataset-ids"], "stable ids are unique")

    def test_the_id_counts_travel_on_every_arm_of_the_check(self) -> None:
        """A metric published only with bad news has a silence with two meanings.

        The readiness cap builds its reason out of these counts, and it has to
        be able to tell "preflight looked and found none" from "this payload
        predates the count". Publishing them on the PASS arm as well is what
        makes the absence of a key mean exactly one thing.
        """
        for repeats, share_ids, expected in (
            (30, True, 30),
            (30, False, 0),
            (0, True, 0),
        ):
            with self.subTest(repeats=repeats, share_ids=share_ids):
                self._details(repeats, share_ids=share_ids)
                metrics = next(
                    result.metrics
                    for result in MODULE.RESULTS
                    if result.check == "dataset-ids"
                )
                self.assertEqual(metrics["duplicate_ids"], expected)
                self.assertEqual(metrics["rows_without_id"], 0)
                self.assertEqual(metrics["generated_rows_without_id"], 0)

    def test_a_generated_row_with_no_id_is_counted_apart_from_the_rest(
        self,
    ) -> None:
        """The two ways this check FAILs, kept as two numbers.

        A collected row missing an id WARNs and caps nothing; a generated one
        FAILs. A reason built from the wider count would name rows the check did
        not object to, so both counts are published and only the narrower one
        describes the failure.
        """
        rows = [
            {
                "id": f"row-{index:03d}",
                "input": f"question {index} about the billing system and its rules",
                "output": f"answer-{index % 4}",
                "source": "production-log",
            }
            for index in range(40)
        ]
        rows.append(
            {
                "input": "a question nobody gave an id",
                "output": "answer-0",
                "source": "production-log",
            }
        )
        rows.append(
            {
                "input": "a written question nobody gave an id",
                "output": "answer-1",
                "source": "synthetic",
            }
        )
        with tempfile.TemporaryDirectory() as raw:
            dataset = Path(raw) / "dataset.jsonl"
            dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            MODULE.RESULTS.clear()
            MODULE.check_dataset(dataset)
        result = next(
            result for result in MODULE.RESULTS if result.check == "dataset-ids"
        )
        self.assertEqual(result.status, MODULE.FAIL)
        self.assertEqual(result.metrics["rows_without_id"], 2)
        self.assertEqual(result.metrics["generated_rows_without_id"], 1)
        self.assertEqual(result.metrics["duplicate_ids"], 0)


# Evaluators a customer would plausibly hand this guide, written before the
# walk they are pointed at and NOT from the constructs it happens to name.
# Three of them are here specifically because an implementation could pass the
# obvious cases and still fail them: SQL_CANONICAL_COMPARISON uses `compile`,
# PARSER_GATE_COMPARISON imports a SQL library that parses without connecting,
# and HANDED_IN_CURSOR reaches a database without importing one at all.
CASEFOLD_COMPARISON = '''"""Compare a label after case and spacing are normalised."""


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    return float(str(output).strip().casefold() == str(expected).strip().casefold())
'''
SQL_CANONICAL_COMPARISON = '''"""Compare SQL over a canonical form: fence, case, spacing, semicolon."""

import re

FENCE = re.compile(r"^```(?:sql)?\\s*|\\s*```$", re.MULTILINE)
SPACING = re.compile(r"\\s+")


def canonical(text):
    stripped = FENCE.sub("", str(text)).strip().rstrip(";")
    return SPACING.sub(" ", stripped).casefold()


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    return float(canonical(output) == canonical(expected))
'''
PARSER_GATE_COMPARISON = '''"""Parse both queries and compare the parsed forms. Nothing connects."""

import sqlparse


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    produced = sqlparse.format(str(output), keyword_case="lower", strip_comments=True)
    wanted = sqlparse.format(str(expected), keyword_case="lower", strip_comments=True)
    return float(produced.strip() == wanted.strip())
'''
FUZZY_RATIO_COMPARISON = '''"""Score by how alike two strings look."""

import difflib


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    return difflib.SequenceMatcher(None, str(output), str(expected)).ratio()
'''
SCHEMA_FIELD_COMPARISON = '''"""Parse JSON and compare the fields that matter."""

import json


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    try:
        produced = json.loads(output)
    except json.JSONDecodeError:
        return 0.0
    wanted = json.loads(expected)
    return float(all(produced.get(key) == value for key, value in wanted.items()))
'''
SET_F1_COMPARISON = '''"""Order-insensitive overlap between two collections."""


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    produced = set(str(output).split(","))
    wanted = set(str(expected).split(","))
    if not produced or not wanted:
        return 0.0
    shared = len(produced & wanted)
    return 2 * shared / (len(produced) + len(wanted))
'''
NUMERIC_TOLERANCE_COMPARISON = '''"""Read both answers as numbers, within a tolerance."""

import ast
import math


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    produced = ast.literal_eval(str(output).strip())
    wanted = ast.literal_eval(str(expected).strip())
    return float(math.isclose(produced, wanted, rel_tol=0.01))
'''
REFERENCE_TABLE_COMPARISON = '''"""Read a reference table off disk, then compare."""

import json
from pathlib import Path

ALIASES = json.loads(Path(__file__).with_name("aliases.json").read_text())


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    produced = ALIASES.get(str(output).strip(), str(output).strip())
    return float(produced == str(expected).strip())
'''
LLM_JUDGE_SCORER = '''"""Ask a model to grade the answer against a rubric."""

import litellm

RUBRIC = "Score 1 when the answer states the same fact, else 0."


def score(*, output, expected, input_data, metadata):
    del metadata
    reply = litellm.completion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"{RUBRIC}\\n{input_data}\\n{output}"}],
    )
    return float(reply["choices"][0]["message"]["content"].strip() == "1")
'''
DYNAMIC_IMPORT_OF_A_HELPER = '''"""Load the project's own comparison helper by name."""

import importlib


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    helper = importlib.import_module("project.compare")
    return float(helper.same(str(output), str(expected)))
'''
CALLABLE_OBJECT_COMPARISON = '''"""A callable object rather than a function."""

import unicodedata


class Scorer:
    def __init__(self, fold=True):
        self.fold = fold

    def __call__(self, *, output, expected, input_data, metadata):
        del input_data, metadata
        left = unicodedata.normalize("NFKC", str(output)).strip()
        right = unicodedata.normalize("NFKC", str(expected)).strip()
        return float(left.casefold() == right.casefold() if self.fold else left == right)


score = Scorer()
'''
MATCH_DISPATCH_COMPARISON = '''"""Routes on the declared metadata kind."""


def score(*, output, expected, input_data, metadata):
    del input_data
    match (metadata or {}).get("kind"):
        case "numeric":
            return float(abs(float(output) - float(expected)) < 0.01)
        case "set":
            return float(set(str(output).split()) == set(str(expected).split()))
        case _:
            return float(str(output).strip() == str(expected).strip())
'''
NON_EXECUTING_EVALUATORS = {
    "callable object": CALLABLE_OBJECT_COMPARISON,
    "match statement dispatch": MATCH_DISPATCH_COMPARISON,
    "casefold comparison": CASEFOLD_COMPARISON,
    "canonical SQL comparison": SQL_CANONICAL_COMPARISON,
    "parser gate then comparison": PARSER_GATE_COMPARISON,
    "fuzzy ratio": FUZZY_RATIO_COMPARISON,
    "schema field comparison": SCHEMA_FIELD_COMPARISON,
    "set overlap": SET_F1_COMPARISON,
    "numeric tolerance": NUMERIC_TOLERANCE_COMPARISON,
    "reference table lookup": REFERENCE_TABLE_COMPARISON,
    "llm judge": LLM_JUDGE_SCORER,
    "dynamic import of a helper": DYNAMIC_IMPORT_OF_A_HELPER,
}

SQLITE_ROUNDTRIP = '''"""Run both queries against a fixture database and compare rows."""

import sqlite3


def score(*, output, expected, input_data, metadata):
    del metadata
    connection = sqlite3.connect(input_data["database"])
    produced = connection.execute(output).fetchall()
    wanted = connection.execute(expected).fetchall()
    connection.close()
    return float(produced == wanted)
'''
DUCKDB_ROUNDTRIP = '''"""Same idea, on a different engine."""

import duckdb


def score(*, output, expected, input_data, metadata):
    del metadata
    connection = duckdb.connect(input_data["database"])
    return float(connection.execute(output).fetchall() == connection.execute(expected).fetchall())
'''
HANDED_IN_CURSOR = '''"""The connection arrives in input_data. Nothing here imports a driver."""


def score(*, output, expected, input_data, metadata):
    del metadata
    cursor = input_data["cursor"]
    cursor.execute(output)
    produced = cursor.fetchall()
    cursor.execute(expected)
    return float(produced == cursor.fetchall())
'''
SHELLS_OUT_TO_PSQL = '''"""Hand the query to the command line client."""

import subprocess


def score(*, output, expected, input_data, metadata):
    del metadata
    produced = subprocess.run(
        ["psql", input_data["dsn"], "-c", output], capture_output=True, text=True
    )
    return float(produced.stdout.strip() == str(expected).strip())
'''
SHELLS_OUT_THROUGH_OS = '''"""The same idea through the older interface."""

import os


def score(*, output, expected, input_data, metadata):
    del metadata
    handle = os.popen(f"sqlite3 {input_data['database']} \\"{output}\\"")
    return float(handle.read().strip() == str(expected).strip())
'''
EXECUTES_CANDIDATE_CODE = '''"""Run the candidate as Python and read a name back out."""


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    namespace = {}
    exec(output, {"__builtins__": {}}, namespace)
    return float(namespace.get("answer") == expected)
'''
EVALUATES_CANDIDATE_EXPRESSION = '''"""Treat the candidate as an expression."""


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    return float(eval(output) == eval(expected))
'''
FROM_IMPORT_OF_A_RUNNER = '''"""Imported by name rather than as a module."""

from subprocess import run


def score(*, output, expected, input_data, metadata):
    del metadata
    finished = run(["duckdb", input_data["database"], "-c", output], capture_output=True)
    return float(finished.stdout.decode().strip() == str(expected).strip())
'''
POSTGRES_DRIVER = '''"""A driver import, with the cursor built inside a helper."""

import psycopg2


def connect(dsn):
    return psycopg2.connect(dsn)


def score(*, output, expected, input_data, metadata):
    del metadata
    with connect(input_data["dsn"]) as connection:
        cursor = connection.cursor()
        cursor.execute(output)
        return float(cursor.fetchall() == expected)
'''
RUNS_A_CANDIDATE_FILE = '''"""Write the candidate out and run the file."""

import runpy
from pathlib import Path


def score(*, output, expected, input_data, metadata):
    del metadata
    path = Path(input_data["scratch"]) / "candidate.py"
    path.write_text(output)
    namespace = runpy.run_path(str(path))
    return float(namespace.get("answer") == expected)
'''
EXECUTING_EVALUATORS = {
    "sqlite roundtrip": SQLITE_ROUNDTRIP,
    "duckdb roundtrip": DUCKDB_ROUNDTRIP,
    "handed-in cursor": HANDED_IN_CURSOR,
    "shells out to psql": SHELLS_OUT_TO_PSQL,
    "shells out through os": SHELLS_OUT_THROUGH_OS,
    "executes candidate code": EXECUTES_CANDIDATE_CODE,
    "evaluates candidate expression": EVALUATES_CANDIDATE_EXPRESSION,
    "from-import of a runner": FROM_IMPORT_OF_A_RUNNER,
    "postgres driver": POSTGRES_DRIVER,
    "runs a candidate file": RUNS_A_CANDIDATE_FILE,
}


class TheEvaluatorCallPathIsReadOutOfItsOwnTreeTests(unittest.TestCase):
    """traigent-first-run#380.

    `check_evaluator` used to be an `ast.parse` and a verdict about syntax, so
    a pure text comparator and a scorer that runs candidate SQL emitted
    byte-identical metrics. `run-safety.md` ends this guide on the second, and
    the readiness score paid 17 more points for declaring it, on a file nobody
    had read.

    The probe files above were written from the space of evaluators a customer
    would hand over, not from the constructs the walk names, which is why
    three of them are shapes a narrower implementation passes and then fails:
    a canonical-form comparison that calls `compile`, a parser library that
    reads SQL without connecting to anything, and a cursor that arrives in
    `input_data` so no driver is ever imported.
    """

    def witnesses(self, source: str) -> tuple[str, ...]:
        return MODULE.candidate_execution_witnesses(ast.parse(source))

    def test_an_honest_comparison_evaluator_leaves_no_witness(self) -> None:
        """Ten shapes that grade without running anything, all clean.

        This is the false-refusal direction, and it is the expensive one: a
        walk that flagged any of these would take 17 points off a customer who
        did exactly what the guide asked for.
        """
        for name, source in NON_EXECUTING_EVALUATORS.items():
            with self.subTest(evaluator=name):
                self.assertEqual(self.witnesses(source), ())

    def test_every_route_to_an_engine_leaves_a_witness(self) -> None:
        """Ten shapes that reach an engine or a process, all found."""
        for name, source in EXECUTING_EVALUATORS.items():
            with self.subTest(evaluator=name):
                found = self.witnesses(source)
                self.assertTrue(found, f"{name} left no witness")

    def test_a_connection_handed_in_is_found_with_no_import_to_read(self) -> None:
        """The case a module list alone cannot see.

        `HANDED_IN_CURSOR` imports nothing at all - the cursor arrives in
        `input_data`, which is how an evaluator written against a project's own
        fixtures usually gets one. The DB-API call names are what catch it, and
        this asserts the import half did no work here.
        """
        tree = ast.parse(HANDED_IN_CURSOR)
        imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        self.assertEqual(imports, [])
        self.assertEqual(
            self.witnesses(HANDED_IN_CURSOR),
            ("calls .execute() (line 7)", "calls .execute() (line 9)"),
        )

    def test_the_dbapi_call_names_come_from_the_standard_library(self) -> None:
        """Derived, not remembered.

        The engine surface is read off `sqlite3.Connection`, the DB-API 2.0
        implementation this interpreter ships, so a name the specification
        carries cannot be missing from the table because nobody had met it.
        """
        import sqlite3

        dbapi_names = {
            name
            for name in dir(sqlite3.Connection)
            if name.startswith("execute") and not name.startswith("_")
        }
        self.assertTrue(dbapi_names)
        self.assertLessEqual(dbapi_names, MODULE._ENGINE_CALL_NAMES)

    def test_an_engine_named_in_the_symbol_rather_than_the_module_is_found(
        self,
    ) -> None:
        """The spelling the cloud drivers document for themselves.

        `from google.cloud import bigquery` and `from mysql import connector`
        put the engine's name in the imported symbol, and a table asked only
        about the module half answers "no" to both. A relative import of the
        same word is a name in the customer's own package and must stay clean.
        """
        self.assertEqual(
            self.witnesses("from google.cloud import bigquery\n"),
            ("imports google.cloud.bigquery (line 1)",),
        )
        self.assertEqual(
            self.witnesses("from mysql import connector\n"),
            ("imports mysql.connector (line 1)",),
        )
        self.assertEqual(
            self.witnesses("from snowflake import connector\n"),
            ("imports snowflake.connector (line 1)",),
        )
        self.assertEqual(self.witnesses("from . import duckdb\n"), ())
        self.assertEqual(self.witnesses("from .helpers import subprocess\n"), ())

    def test_the_process_family_is_matched_and_ordinary_os_members_are_not(
        self,
    ) -> None:
        """Both directions over `os`, from a list written out of its docs.

        Written out rather than filtered by the predicate under test, because
        a fixture derived from its own assertion proves nothing. The second
        half is the one that keeps the prefix rule honest: `exec` and `spawn`
        are short, and a rule that matched more of `os` than this would start
        refusing evaluators that merely read a file.
        """
        documented = (
            "execl execle execlp execlpe execv execve execvp execvpe "
            "spawnl spawnle spawnlp spawnlpe spawnv spawnve spawnvp spawnvpe "
            "posix_spawn posix_spawnp system popen startfile fork forkpty"
        ).split()
        present = [name for name in documented if hasattr(os, name)]
        self.assertGreater(len(present), 10)
        for name in present:
            with self.subTest(member=name):
                self.assertTrue(MODULE._is_process_attribute(name))
        ordinary = (
            "path environ getcwd listdir sep remove stat walk open close "
            "read write rename makedirs urandom cpu_count getenv"
        ).split()
        for name in ordinary:
            with self.subTest(member=name):
                self.assertTrue(hasattr(os, name))
                self.assertFalse(MODULE._is_process_attribute(name))

    def test_building_a_code_object_is_not_running_one(self) -> None:
        """`compile`, `literal_eval` and `import_module` are deliberately out.

        Each was left out for its own reason and each would have cost a real
        evaluator its credit: `re.compile` is how the canonical-form
        comparison this guide asks for is written, `ast.literal_eval` reads a
        number without running anything, and loading a module by name is how
        ordinary Python reaches a dependency.
        """
        self.assertNotIn("compile", MODULE._EXECUTION_BUILTIN_CALLS)
        self.assertEqual(self.witnesses("import re\nP = re.compile('a')\n"), ())
        self.assertEqual(
            self.witnesses("from re import compile\nP = compile('a')\n"), ()
        )
        self.assertEqual(self.witnesses("import ast\nV = ast.literal_eval('1')\n"), ())
        self.assertEqual(self.witnesses(DYNAMIC_IMPORT_OF_A_HELPER), ())

    def test_a_witness_names_the_construct_and_the_line_it_sits_on(self) -> None:
        """A refusal a customer cannot check is one they cannot disagree with."""
        self.assertEqual(
            self.witnesses(SQLITE_ROUNDTRIP),
            (
                "imports sqlite3 (line 3)",
                "calls .execute() (line 9)",
                "calls .execute() (line 10)",
            ),
        )
        self.assertEqual(
            self.witnesses(EXECUTES_CANDIDATE_CODE), ("calls exec() (line 7)",)
        )
        # `import os` is not a witness and must not become one. Every second
        # Python file imports it, and an evaluator that reads a path out of it
        # has started no process. What is reported is the call.
        self.assertEqual(
            self.witnesses(SHELLS_OUT_THROUGH_OS), ("calls os.popen() (line 8)",)
        )
        self.assertEqual(self.witnesses("import os\nD = os.environ['HOME']\n"), ())

    def test_an_engine_route_warns_and_says_so_in_the_metrics(self) -> None:
        MODULE.RESULTS.clear()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text(SQLITE_ROUNDTRIP)
            MODULE.check_evaluator(path)
        result = next(r for r in MODULE.RESULTS if r.check == "evaluator-shape")
        self.assertEqual(result.status, MODULE.WARN)
        self.assertTrue(result.metrics["exists"])
        self.assertTrue(result.metrics["parses"])
        self.assertTrue(result.metrics["executes"])
        self.assertIn("imports sqlite3 (line 3)", result.metrics["execution_witnesses"])
        self.assertIn("sqlite3", result.detail)

    def test_a_comparison_evaluator_reports_a_walk_that_found_nothing(self) -> None:
        """`executes: false` is a walk that ran, not a check that was skipped.

        The distinction is the whole reason the field is emitted on a passing
        check at all: readiness has to tell "read, and nothing found" apart
        from "no file was read", and it can only do that if the clean case
        says something.
        """
        MODULE.RESULTS.clear()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text(SQL_CANONICAL_COMPARISON)
            MODULE.check_evaluator(path)
        result = next(r for r in MODULE.RESULTS if r.check == "evaluator-shape")
        self.assertEqual(result.status, MODULE.PASS)
        self.assertIs(result.metrics["executes"], False)
        self.assertNotIn("execution_witnesses", result.metrics)

    def test_a_file_that_does_not_parse_reports_no_execution_verdict(self) -> None:
        """No tree, no walk, and no field claiming one ran."""
        MODULE.RESULTS.clear()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text("def score(output, expected:\n    return 1.0\n")
            MODULE.check_evaluator(path)
        result = next(r for r in MODULE.RESULTS if r.check == "evaluator-shape")
        self.assertEqual(result.status, MODULE.FAIL)
        self.assertNotIn("executes", result.metrics)

    def test_the_walk_reads_the_tree_and_opens_nothing_else(self) -> None:
        """Still inside the static gate.

        The walk is handed a tree `ast.parse` already built, so the guarantee
        `check_evaluator` has always made - no import, no call, no module top
        level - is not weakened by asking it a second question. Asserted by
        walking an evaluator whose import would fail loudly if anything
        resolved it.
        """
        source = "import definitely_not_installed_" + "engine\n"
        self.assertEqual(self.witnesses(source), ())
        self.assertEqual(
            self.witnesses("import duckdb\n"), ("imports duckdb (line 1)",)
        )


if __name__ == "__main__":
    unittest.main()


# Whole-value comparisons, in the spellings evaluators are actually written
# in. `ALIASED_NORMALISED` and `REVERSED_OPERANDS` are here because they are
# the same comparison rearranged, and a walk that only understood the corpus's
# one-line form would answer "not established" to both and quietly hand back
# the credit it was meant to withhold.
BARE_EQUALITY = '''"""Character for character, and nothing else."""


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    return float(output == expected)
'''
STRINGIFIED_EQUALITY = '''"""The same, with both sides read as text first."""


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    return str(output) == str(expected)
'''
ALIASED_NORMALISED = '''"""Both sides prepared on their own line, then compared."""


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    produced = str(output).strip().casefold()
    wanted = str(expected).strip().casefold()
    return float(produced == wanted)
'''
REVERSED_OPERANDS = '''"""Expected on the left, and only one side folded."""


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    return float(str(expected).strip() == str(output))
'''
REBINDS_ONTO_ITS_OWN_NAME = '''"""Each answer prepared in place, on its own name."""


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    output = str(output).strip().casefold()
    expected = str(expected).strip().casefold()
    return float(output == expected)
'''
COMPARES_ONE_ANSWER_TWICE = '''"""Compares the answer with itself. Not a comparison against the expectation."""


def score(*, output, expected, input_data, metadata):
    del input_data, metadata, expected
    return float(output.strip() == output.casefold())
'''
TWO_ANSWER_TAKING_CALLABLES = '''"""A helper takes both answers too, so the scorer is ambiguous."""


def same(output, expected):
    return str(output).strip() == str(expected).strip()


def score(*, output, expected, input_data, metadata):
    del input_data, metadata
    return float(same(output, expected))
'''


class TheComparisonTheFilePerformsIsProvedOrLeftUnsettledTests(unittest.TestCase):
    """traigent-first-run#380, the half a single-field check cannot reach.

    It is the matched pair that pays: over one unchanged text comparator,
    `exact` + `code-sql`, `normalized-exact` + `structured` and
    `normalized-exact` + `code-sql` all read the same, and `exact` +
    `structured` read the top band with no caps. So the top band is reached by
    mis-declaring both fields consistently, and checking either field alone
    sees nothing wrong.

    What this walk establishes is what the comparison IS, so every declaration
    can be measured against one fact. It proves or it declines: the `None`
    answer is the common one and refutes nothing.
    """

    def shape(self, source: str):
        return MODULE.derived_comparison_shape(ast.parse(source))

    def test_a_comparison_with_no_transform_reads_as_exact(self) -> None:
        for name, source in (
            ("bare equality", BARE_EQUALITY),
            ("stringified equality", STRINGIFIED_EQUALITY),
        ):
            with self.subTest(evaluator=name):
                shape, transforms, _line = self.shape(source)
                self.assertEqual(shape, "exact")
                self.assertEqual(transforms, frozenset())

    def test_a_transform_on_either_side_reads_as_normalized(self) -> None:
        """Either side, because normalising one is still normalising."""
        shape, transforms, line = self.shape(CASEFOLD_COMPARISON)
        self.assertEqual(shape, "normalized-exact")
        self.assertEqual(transforms, frozenset({"strip", "casefold"}))
        self.assertEqual(line, 6)
        aliased, aliased_transforms, _line = self.shape(ALIASED_NORMALISED)
        self.assertEqual(aliased, "normalized-exact")
        self.assertEqual(aliased_transforms, frozenset({"strip", "casefold"}))
        reversed_shape, reversed_transforms, _line = self.shape(REVERSED_OPERANDS)
        self.assertEqual(reversed_shape, "normalized-exact")
        self.assertEqual(reversed_transforms, frozenset({"strip"}))

    def test_an_answer_prepared_onto_its_own_name_is_still_normalised(self) -> None:
        """The rebinding a scorer is just as likely to be written with.

        `output = output.strip()` is an ordinary way to prepare an answer, and
        at the comparison the name means the prepared value, not the argument.
        A read that took the parameter first would report this file as `exact`
        and hand full credit to the one declaration this walk exists to
        refuse, on a file that folds case before comparing.
        """
        shape, transforms, _line = self.shape(REBINDS_ONTO_ITS_OWN_NAME)
        self.assertEqual(shape, "normalized-exact")
        self.assertEqual(transforms, frozenset({"strip", "casefold"}))
        # One side rebound is enough, and the bare file is still bare.
        one_side, one_transform, _line = self.shape(
            "def score(*, output, expected, input_data, metadata):\n"
            "    output = str(output).strip()\n"
            "    return float(output == expected)\n"
        )
        self.assertEqual(one_side, "normalized-exact")
        self.assertEqual(one_transform, frozenset({"strip"}))
        self.assertEqual(self.shape(BARE_EQUALITY)[0], "exact")

    def test_every_other_honest_evaluator_is_left_unsettled(self) -> None:
        """The `None` branch, over the same real shapes the other walk uses.

        This is the direction that decides whether the check is safe to ship.
        Each of these grades honestly and none of them is a whole-value
        equality, so each must come back unestablished and keep every point it
        had. A walk that guessed at any of them would be refusing a customer
        on a shape it had not read.
        """
        settled = {"casefold comparison"}
        for name, source in NON_EXECUTING_EVALUATORS.items():
            if name in settled:
                continue
            with self.subTest(evaluator=name):
                self.assertIsNone(self.shape(source))

    def test_a_shape_the_walk_cannot_account_for_is_not_guessed_at(self) -> None:
        """Four refusals, each for its own reason.

        A comparison against something other than the expected answer, a
        second callable taking both answers, an operator that is not equality,
        and a branch. Each would have to be followed to be judged, and none of
        them is.
        """
        self.assertIsNone(self.shape(COMPARES_ONE_ANSWER_TWICE))
        self.assertIsNone(self.shape(TWO_ANSWER_TAKING_CALLABLES))
        self.assertIsNone(
            self.shape(
                "def score(*, output, expected, input_data, metadata):\n"
                "    return float(output != expected)\n"
            )
        )
        self.assertIsNone(
            self.shape(
                "def score(*, output, expected, input_data, metadata):\n"
                "    if not output:\n"
                "        return 0.0\n"
                "    return float(output == expected)\n"
            )
        )

    def test_unbinding_a_name_the_comparison_uses_stops_the_proof(self) -> None:
        """`del input_data, metadata` is skipped; `del expected` is not.

        The idiom every adapter in this guide opens with unbinds two names
        this walk never reads, so passing over it costs nothing. Unbinding an
        answer or an alias is a different statement, and skipping that one
        would leave the walk reasoning about a name the scorer has taken away,
        which is the one thing a proof of a whole comparison may not do.
        """
        idiom = self.shape(
            "def score(*, output, expected, input_data, metadata):\n"
            "    del input_data, metadata\n"
            "    return float(output.strip() == expected.strip())\n"
        )
        self.assertEqual(idiom[0], "normalized-exact")
        self.assertIsNone(
            self.shape(
                "def score(*, output, expected, input_data, metadata):\n"
                "    kept = expected\n"
                "    del expected\n"
                "    return float(output == kept)\n"
            )
        )
        self.assertIsNone(
            self.shape(
                "def score(*, output, expected, input_data, metadata):\n"
                "    prepared = output.strip()\n"
                "    del prepared\n"
                "    return float(output == expected)\n"
            )
        )
        self.assertIsNone(
            self.shape(
                "def score(*, output, expected, input_data, metadata):\n"
                "    del metadata['seen']\n"
                "    return float(output == expected)\n"
            )
        )

    def test_a_numeric_reading_is_not_reported_as_a_text_comparison(self) -> None:
        """`float()` around an answer reinterprets it and stops the proof.

        `str()` is the one neutral wrapper, because it changes nothing a
        string comparison would see. Reading an answer as a number is a
        different check, and this walk declines it rather than filing it under
        one of the two names it knows.
        """
        self.assertIsNone(
            self.shape(
                "def score(*, output, expected, input_data, metadata):\n"
                "    return float(float(output) == float(expected))\n"
            )
        )

    def test_the_proof_reaches_the_metrics_with_a_line_to_check_it_on(self) -> None:
        MODULE.RESULTS.clear()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text(CASEFOLD_COMPARISON)
            MODULE.check_evaluator(path)
        result = next(r for r in MODULE.RESULTS if r.check == "evaluator-shape")
        self.assertEqual(result.metrics["comparison_shape"], "normalized-exact")
        self.assertEqual(
            result.metrics["comparison_witness"],
            "casefold, strip applied before the comparison (line 6)",
        )

    def test_an_unsettled_file_carries_no_comparison_field_at_all(self) -> None:
        """Absent, not null. There is no value that honestly stands for it."""
        MODULE.RESULTS.clear()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluator.py"
            path.write_text(FUZZY_RATIO_COMPARISON)
            MODULE.check_evaluator(path)
        result = next(r for r in MODULE.RESULTS if r.check == "evaluator-shape")
        self.assertNotIn("comparison_shape", result.metrics)
        self.assertNotIn("comparison_witness", result.metrics)

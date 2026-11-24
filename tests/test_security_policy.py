"""The repository publishes a root security policy that tells reporters where to write.

Without it, a reporter of a vulnerability in this public repository has no
documented private channel. The policy must point at this repository's own
advisory form, not another repository's.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SecurityPolicyTests(unittest.TestCase):
    def test_the_policy_sits_at_the_repository_root(self) -> None:
        self.assertTrue((ROOT / "SECURITY.md").is_file())

    def test_it_names_this_repositorys_private_advisory_form(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn(
            "https://github.com/Traigent/traigent-first-run/security/advisories/new",
            policy,
        )

    def test_out_of_scope_line_routes_sdk_reports_to_the_sdk_advisory_form(
        self,
    ) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        lines = [
            line
            for line in policy.splitlines()
            if "Out of scope for this repository" in line
        ]
        self.assertEqual(len(lines), 1, "exactly one out-of-scope routing line")
        urls = re.findall(r"<(https://[^>]+)>", lines[0])
        self.assertIn(
            "https://github.com/Traigent/Traigent/security/advisories/new", urls
        )

    def test_it_names_the_security_mailbox(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("security@traigent.ai", policy)

    def test_it_states_scope_before_reporting_instructions(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("\n## Scope\n", policy)
        self.assertLess(
            policy.index("\n## Scope\n"),
            policy.index("\n## Reporting a vulnerability\n"),
        )

    def test_scope_names_the_agent_instruction_files(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        scope = policy[
            policy.index("\n## Scope\n") : policy.index(
                "\n## Reporting a vulnerability\n"
            )
        ]
        self.assertIn("AGENTS.md", scope)
        self.assertIn("CLAUDE.md", scope)

    def test_scope_names_ci_and_reports_as_in_scope(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        scope = policy[
            policy.index("\n## Scope\n") : policy.index(
                "\n## Reporting a vulnerability\n"
            )
        ]
        self.assertIn(
            "the repository configuration in `.github/` (workflows, CODEOWNERS)", scope
        )
        self.assertIn("`reports/`", scope)

    def test_it_states_the_acknowledgement_and_response_times(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn(
            "We will acknowledge receipt within 48 hours and provide a detailed "
            "response within 7 days.",
            policy,
        )

    def test_it_names_the_supported_branch_in_supported_versions(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("\n## Supported versions\n", policy)
        section = policy[
            policy.index("\n## Supported versions\n") : policy.index(
                "\n## Disclosure\n"
            )
        ]
        self.assertIn("`first-run-guide`", section)

    def test_env_example_is_out_of_scope_only_as_placeholder_values(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        scope = policy[
            policy.index("\n## Scope\n") : policy.index(
                "\n## Reporting a vulnerability\n"
            )
        ]
        mentions = [line for line in scope.splitlines() if ".env.example" in line]
        self.assertTrue(mentions, "Scope should address .env.example")
        for line in mentions:
            self.assertIn("placeholder", line)

    def test_codeowners_pins_the_policy_paths_and_every_entry_names_the_owner(
        self,
    ) -> None:
        # Every CODEOWNERS entry names the owner, so whichever line GitHub's
        # last-match rule picks for these paths names the owner. The test does
        # not model GitHub's matcher; it pins the entries it relies on.
        lines = [
            line.strip()
            for line in (ROOT / ".github" / "CODEOWNERS")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for path in (
            "/SECURITY.md",
            "/tests/test_security_policy.py",
            "/.github/CODEOWNERS",
            "/skills/traigent-first-run/scripts/",
        ):
            with self.subTest(path=path):
                owners = [line.split()[1:] for line in lines if line.split()[0] == path]
                self.assertTrue(
                    any("@nimrodbusany" in entry for entry in owners),
                    f"no {path} entry names @nimrodbusany",
                )
        for line in lines:
            with self.subTest(line=line):
                owners = line.split()[1:]
                self.assertIn("@nimrodbusany", owners, "every entry names the owner")

    def test_in_scope_reports_have_the_private_advisory_form_and_mailbox(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        start = policy.index("\n## Reporting a vulnerability\n")
        end = policy.index("\n## ", start + 1)
        section = policy[start:end]
        advisory_urls = re.findall(
            r"<(https://github\.com/[^>]+/security/advisories/new)>", section
        )
        self.assertIn(
            "https://github.com/Traigent/traigent-first-run/security/advisories/new",
            advisory_urls,
        )
        self.assertIn("security@traigent.ai", section)
        self.assertIn(
            "Please report security issues privately rather than in a public issue "
            "or pull request.",
            section,
        )

    def test_reporting_paragraph_says_to_report_privately(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn(
            "Please report security issues privately rather than in a public issue "
            "or pull request.",
            policy,
        )

    def test_hosted_service_route_is_on_the_out_of_scope_line(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        lines = [
            line
            for line in policy.splitlines()
            if "Out of scope for this repository" in line
        ]
        self.assertEqual(len(lines), 1, "exactly one out-of-scope routing line")
        self.assertIn(
            "the hosted Traigent service to [security@traigent.ai]"
            "(mailto:security@traigent.ai)",
            lines[0],
        )

    def test_reporters_are_told_not_to_include_real_secrets(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn(
            "Do not include real secrets or customer data in a report.", policy
        )

    def test_only_the_current_tip_is_supported(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        section = policy[
            policy.index("\n## Supported versions\n") : policy.index(
                "\n## Disclosure\n"
            )
        ]
        self.assertIn("Only its current tip is supported.", section)

    def test_deps_is_out_of_scope(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        lines = [
            line
            for line in policy.splitlines()
            if line.startswith("- **Out of scope:**")
        ]
        self.assertEqual(len(lines), 1, "exactly one out-of-scope scope line")
        self.assertIn("`deps/`", lines[0])

    def test_in_scope_line_names_the_guide_and_the_bundled_skill(self) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        lines = [
            line for line in policy.splitlines() if line.startswith("- **In scope:**")
        ]
        self.assertEqual(len(lines), 1, "exactly one in-scope line")
        self.assertIn("`GUIDE.md`", lines[0])
        self.assertIn("`skills/traigent-first-run/`", lines[0])

    def test_out_of_scope_line_excludes_the_tests_and_tools_maintenance_trees(
        self,
    ) -> None:
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        lines = [
            line
            for line in policy.splitlines()
            if line.startswith("- **Out of scope:**")
        ]
        self.assertEqual(len(lines), 1, "exactly one out-of-scope scope line")
        self.assertIn("`tests/`", lines[0])
        self.assertIn("`tools/`", lines[0])


if __name__ == "__main__":
    unittest.main()

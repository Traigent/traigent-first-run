"""The repository publishes a root security policy that tells reporters where to write.

Without it, a reporter of a vulnerability in this public repository has no
documented private channel. The policy must point at this repository's own
advisory form, not another repository's.
"""

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
        self.assertIn("`.github/workflows/`", scope)
        self.assertIn("`reports/`", scope)


if __name__ == "__main__":
    unittest.main()

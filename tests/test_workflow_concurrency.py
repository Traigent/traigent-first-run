"""Pin the concurrency contract of the pull-request validation workflow.

Without a concurrency group, every superseded push to a pull request keeps its
runs alive and consumes runners. The group is keyed per pull request, so a newer
push cancels the older run. Trunk pushes are keyed by run id, so each one gets a
group of its own and is never cancelled or replaced: GitHub replaces a pending
run in a shared group even when `cancel-in-progress` is false.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"


class TestValidateWorkflowConcurrency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = yaml.safe_load(WORKFLOW.read_text())

    def test_top_level_concurrency_exists(self):
        self.assertIn(
            "concurrency", self.doc, "validate.yml has no top-level concurrency"
        )

    def test_group_keys_on_pull_request_number_or_run_id(self):
        group = self.doc["concurrency"]["group"]
        self.assertIn("github.event.pull_request.number", group)
        self.assertIn("github.run_id", group)

    def test_group_does_not_key_on_sha(self):
        # A sha-keyed trunk group is predictable from a pull request that edits
        # this workflow, so a PR could join it and cancel trunk validation.
        group = self.doc["concurrency"]["group"]
        self.assertNotIn("github.sha", group)

    def test_group_does_not_key_on_ref_alone(self):
        # A ref-keyed group would put every trunk push into one group, where a
        # newer push replaces and cancels the older trunk run.
        group = self.doc["concurrency"]["group"]
        self.assertNotIn("github.ref", group.replace("github.ref_name", ""))

    def test_cancel_in_progress_is_pull_request_only_expression(self):
        cancel = self.doc["concurrency"]["cancel-in-progress"]
        self.assertIsInstance(cancel, str)
        self.assertEqual(cancel, "${{ github.event_name == 'pull_request' }}")

    def test_every_job_keeps_its_timeout(self):
        for name, job in self.doc["jobs"].items():
            with self.subTest(job=name):
                self.assertIn("timeout-minutes", job)


if __name__ == "__main__":
    unittest.main()

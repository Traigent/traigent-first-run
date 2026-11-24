"""Pin the concurrency contract of the pull-request validation workflow.

Without a concurrency group, every superseded push to a pull request keeps its
runs alive and consumes runners. The group is keyed per pull request, so a newer
push cancels the older run. Trunk pushes get a group of their own, keyed by run
id, so no other trunk push and no unmodified pull request run can replace or
cancel them: GitHub replaces a pending run in a shared group even when
`cancel-in-progress` is false. A pull request that edits this workflow runs its
own copy and could name another run's group, another pull request's or a trunk
run's, to cancel it; that costs a re-run and exposes nothing.
"""

import importlib.util
import unittest
from pathlib import Path

# PyYAML is not a declared dependency, so skip (rather than error at import)
# on a bare interpreter; the pinned stack provides it.
HAS_YAML = importlib.util.find_spec("yaml") is not None
if HAS_YAML:
    import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"


@unittest.skipIf(not HAS_YAML, "PyYAML not installed (pinned stack)")
class TestValidateWorkflowConcurrency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = yaml.safe_load(WORKFLOW.read_text())

    def test_top_level_concurrency_exists(self):
        self.assertIn(
            "concurrency", self.doc, "validate.yml has no top-level concurrency"
        )

    def test_group_keys_on_pull_request_number_then_run_id(self):
        # Order matters: github.run_id is always set, so with it first every run
        # gets its own group and cancel-in-progress never cancels a superseded push.
        self.assertEqual(
            self.doc["concurrency"]["group"],
            "${{ github.workflow }}-"
            "${{ github.event.pull_request.number || github.run_id }}",
        )

    def test_group_does_not_key_on_sha(self):
        # run_id gives every trunk run its own group, so no trunk push can cancel
        # another. A sha-keyed group would let two runs of the same commit share a
        # group, so one could replace or cancel the other.
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

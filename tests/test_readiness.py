from __future__ import annotations

import importlib.util
import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "traigent-first-run" / "scripts" / "readiness.py"
SPEC = importlib.util.spec_from_file_location("first_run_readiness", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ReadinessMatrixTests(unittest.TestCase):
    def test_all_eight_real_or_missing_starting_states(self) -> None:
        expected_create = {
            ("real", "real", "real"): [],
            ("real", "real", "missing"): ["evaluation"],
            ("real", "missing", "real"): ["dataset"],
            ("missing", "real", "real"): ["agent"],
            ("real", "missing", "missing"): ["dataset", "evaluation"],
            ("missing", "real", "missing"): ["agent", "evaluation"],
            ("missing", "missing", "real"): ["dataset", "agent"],
            ("missing", "missing", "missing"): ["agent", "dataset", "evaluation"],
        }
        observed = {}
        for states in itertools.product(("real", "missing"), repeat=3):
            plan = MODULE.build_plan(*states)
            observed[states] = plan.create
            self.assertEqual(plan.real_ready_count, states.count("real"))
            self.assertEqual(plan.walkthrough_ready_count, states.count("real"))
        self.assertEqual(observed, expected_create)

    def test_demo_substitute_never_counts_as_real(self) -> None:
        plan = MODULE.build_plan("real", "demo", "missing")
        self.assertEqual(plan.real_ready_count, 1)
        self.assertEqual(plan.walkthrough_ready_count, 2)
        self.assertIn("dataset", plan.missing_real)
        self.assertEqual(plan.create, ["evaluation"])
        rendered = MODULE.render_text(plan)
        self.assertIn("❗ Dataset", rendered)
        # The same component appears twice and means opposite things, so what
        # separates the two lines is what this asserts. It used to be a glyph;
        # it is now the heading plus the words on the line, which is what a
        # customer reads either way and what a terminal without emoji keeps.
        self.assertIn("Walkthrough setup:", rendered)
        self.assertIn("Dataset: generated walkthrough substitute", rendered)
        self.assertNotIn("🧪", rendered)

    def test_limited_component_is_usable_but_not_real_world_ready(self) -> None:
        plan = MODULE.build_plan("real", "limited", "real")
        self.assertEqual(plan.real_ready_count, 2)
        self.assertEqual(plan.walkthrough_ready_count, 3)
        self.assertIn("dataset", plan.missing_real)
        self.assertEqual(plan.create, [])
        self.assertIn("revalid", plan.action)
        rendered = MODULE.render_text(plan)
        self.assertIn(
            "❗ Dataset: real material exists but evidence is limited", rendered
        )


class SynthesisedDataIsWorkableAndNeverStrongTests(unittest.TestCase):
    """The owner's rule, kept somewhere a merge cannot take it out with the fix.

    `tests/test_readiness_scoring.py` already asserts this three ways, and that
    is where it belongs. It is repeated here because of where the OTHER copy
    lives: #159 rewrites the same region of `readiness.py` that carries the
    ceiling, and appends its own test class to the end of the same test file.
    Both files therefore conflict, and both conflicts sit on the branch that
    reverts this decision - so one whole-file `--theirs` on the pair restores
    the ceiling to the STRONG threshold and deletes the check that would have
    said so, in a single move, leaving a green suite.

    That is not a hypothetical. It was executed: with #159's side taken on both
    files the ceiling reads 75 again and the suite passes. With #159's side
    taken on `readiness.py` alone the three assertions in the other file fire
    correctly. The difference between the two is which resolution a person
    happens to reach for, which is not a thing to leave a decision resting on.

    `readiness.py` is the only file this class reads, and #159 does not touch
    `tests/test_readiness.py` at all, so no resolution of that branch can take
    both copies. The assertion is the property and never the number: it asks
    the module where its own STRONG band begins, so renumbering the bands
    cannot quietly land the ceiling back inside STRONG.
    """

    def test_no_ceiling_for_synthesised_data_reaches_the_strong_band(self) -> None:
        strong = MODULE.BAND_ORDER.index("STRONG")
        ceilings = {
            name: value
            for name, value in vars(MODULE).items()
            if isinstance(value, int)
            and not isinstance(value, bool)
            and name.endswith("_CEILING")
            and ("SYNTHETIC" in name or "GENERATED" in name or "ANSWER_KEY" in name)
        }
        self.assertIn(
            "GENERATED_ANSWER_KEY_CEILING",
            ceilings,
            "the ceiling on a model-written answer key is gone or renamed; it "
            "is the one this rule exists for",
        )
        for name, ceiling in sorted(ceilings.items()):
            with self.subTest(ceiling=name):
                band, _limited = MODULE.band_for(ceiling, 1.0, 1.0)
                self.assertLess(
                    MODULE.BAND_ORDER.index(band),
                    strong,
                    f"{name} is {ceiling}, which this module reports as {band} "
                    "- at or above STRONG, so data a model supplied can present "
                    "as good rather than merely workable",
                )

    def test_the_cap_the_scorer_raises_carries_that_ceiling(self) -> None:
        """The constant and the cap are two things, and the cap is the one that binds.

        Checking the constant alone would pass against a scorer that had stopped
        using it, which is exactly what a half-applied merge produces: #159
        moves every ceiling into one table, so the constant and the `Cap(...)`
        that reads it can end up on opposite sides of one resolution.
        """
        facts = MODULE.DatasetFacts(
            exists=True,
            rows=200,
            labelled_rows=200,
            collected_rows=200,
            answerable_rows=200,
            generated_answer_rows=200,
        )
        _pillar, caps = MODULE.score_dataset(facts, "exact")
        cap = next(
            (cap for cap in caps if cap.condition == "dataset-generated-answer-key"),
            None,
        )
        self.assertIsNotNone(
            cap, "a dataset whose every expected answer is a model's raised no cap"
        )
        band, _limited = MODULE.band_for(cap.ceiling, 1.0, 1.0)
        self.assertLess(
            MODULE.BAND_ORDER.index(band),
            MODULE.BAND_ORDER.index("STRONG"),
            f"the cap the scorer actually raises is capped at {cap.ceiling}, "
            f"which the module reports as {band}",
        )


class TheCustomerFacingTablesStateTheScorersNumbersTests(unittest.TestCase):
    """The user reads the tables; the run is scored by the constants.

    `evaluation-and-dataset.md` prints the provenance points and the provenance
    ceilings as tables a user is expected to plan against. Nothing held either
    table to `readiness.py`: with the ceiling moved to 74 and the table left at
    75 the whole suite passed, so the published document was free to describe a
    scoring rule the scorer does not implement.

    That is not only a drafting risk. #165 rewrites both of these tables and
    `readiness.py` in the same region, so the two conflict together - and one
    whole-file `--theirs` on the document restores the table's 75 while the
    code auto-merges to 74, which is precisely the state that just passed. The
    binding lives in this file because #159 and #165 both leave it alone: no
    resolution of either branch can take the document's side and the check that
    would object in one move.

    Neither test restates a number. Each reads the column out of the document
    and compares it against the constants the scorer uses, so a change to
    either side alone fails, and the rows are matched by position - the ladder's
    order is itself a claim the prose makes about it.
    """

    DOCUMENT = (
        ROOT
        / "skills"
        / "traigent-first-run"
        / "references"
        / "evaluation-and-dataset.md"
    )

    def _table_column(self, heading: str) -> list[float]:
        """The last column of the first table under `heading`, as numbers."""
        lines = self.DOCUMENT.read_text(encoding="utf-8").splitlines()
        self.assertIn(heading, lines, f"{self.DOCUMENT.name} lost {heading!r}")
        rows: list[str] = []
        for line in lines[lines.index(heading) + 1 :]:
            stripped = line.strip()
            if stripped.startswith("|"):
                rows.append(stripped)
            elif rows:
                break
        self.assertGreater(len(rows), 2, f"no table follows {heading!r}")
        return [
            float(row.strip("|").rsplit("|", 1)[-1].strip())
            for row in rows[2:]  # rows[0] is the header, rows[1] the separator
        ]

    def _assert_column_is(self, heading: str, names: list[str]) -> None:
        documented = self._table_column(heading)
        expected = [float(getattr(MODULE, name)) for name in names]
        self.assertEqual(
            len(documented),
            len(names),
            f"the table under {heading!r} has {len(documented)} rows and "
            f"readiness.py has {len(names)} values for it",
        )
        for row, (stated, scored, name) in enumerate(
            zip(documented, expected, names), start=1
        ):
            with self.subTest(constant=name):
                self.assertEqual(
                    stated,
                    scored,
                    f"row {row} under {heading!r} states {stated:g} and "
                    f"readiness.py scores with {name} = {scored:g}",
                )

    def test_the_documented_ceilings_are_the_ceilings_the_scorer_applies(
        self,
    ) -> None:
        self._assert_column_is(
            "### Provenance ceilings",
            [
                "FULLY_SYNTHETIC_CEILING",
                "MOSTLY_SYNTHETIC_CEILING",
                "MOSTLY_GENERATED_ANSWER_KEY_CEILING",
                "GENERATED_ANSWER_KEY_CEILING",
            ],
        )

    def test_the_documented_row_points_are_the_points_the_scorer_awards(self) -> None:
        self._assert_column_is(
            "### Declaring provenance",
            [
                "COLLECTED_ROW_POINTS",
                "GENERATED_ANSWER_ROW_POINTS",
                "UNDECLARED_ROW_POINTS",
                "SYNTHESISED_ROW_POINTS",
            ],
        )


if __name__ == "__main__":
    unittest.main()

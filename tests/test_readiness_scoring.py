from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "traigent-first-run" / "scripts" / "readiness.py"
SPEC = importlib.util.spec_from_file_location("first_run_scoring", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeStream:
    def __init__(self, *, tty: bool, encoding: str = "utf-8") -> None:
        self._tty = tty
        self.encoding = encoding

    def isatty(self) -> bool:
        return self._tty


class KnobVariationTests(unittest.TestCase):
    def test_narrow_sweep_scores_low_on_span_but_keeps_resolution(self) -> None:
        knob = MODULE.knob_variation("temperature", [0.1, 0.2])
        self.assertAlmostEqual(knob.span_ratio, 0.10, places=4)
        self.assertLess(knob.span, 0.2)
        # 0.1 and 0.2 are genuinely distinguishable temperatures, so resolution
        # is honestly 1.0; the narrowness must show up as span, not be smeared.
        self.assertEqual(knob.resolution, 1.0)
        self.assertLess(knob.quality, 0.5)
        self.assertTrue(any("10%" in note for note in knob.notes))

    def test_sub_noise_floor_values_collapse_to_zero(self) -> None:
        knob = MODULE.knob_variation("temperature", [0.0001, 0.0002])
        self.assertEqual(knob.quality, 0.0)
        self.assertEqual(knob.resolution, 0.0)
        self.assertEqual(knob.effective_values, 1)
        self.assertTrue(
            any("same configuration in practice" in note for note in knob.notes)
        )

    def test_full_range_sweep_scores_full_marks(self) -> None:
        knob = MODULE.knob_variation("temperature", [0.0, 0.7, 1.0])
        self.assertEqual(knob.span, 1.0)
        self.assertEqual(knob.coverage, 1.0)
        self.assertEqual(knob.quality, 1.0)
        self.assertEqual(knob.notes, ())

    def test_single_value_knob_is_not_a_knob(self) -> None:
        knob = MODULE.knob_variation("temperature", [0.7])
        self.assertEqual(knob.quality, 0.0)
        self.assertIn("only one value - nothing to search", knob.notes)

    def test_categorical_knob_scores_on_breadth(self) -> None:
        one = MODULE.knob_variation("prompt_policy", ["direct"])
        two = MODULE.knob_variation("prompt_policy", ["direct", "structured"])
        three = MODULE.knob_variation(
            "prompt_policy", ["direct", "structured", "criteria_first"]
        )
        self.assertEqual(one.quality, 0.0)
        self.assertGreater(three.quality, two.quality)
        self.assertEqual(three.quality, 1.0)

    def test_duplicate_values_do_not_inflate_breadth(self) -> None:
        knob = MODULE.knob_variation("prompt_policy", ["direct", "direct", "direct"])
        self.assertEqual(knob.distinct_values, 1)
        self.assertEqual(knob.quality, 0.0)

    def test_seed_is_excluded_from_scoring(self) -> None:
        knob = MODULE.knob_variation("seed", [1, 2, 3])
        self.assertEqual(knob.kind, "excluded")
        self.assertEqual(knob.quality, 0.0)

    def test_unknown_knob_uses_caller_supplied_bounds(self) -> None:
        scored = MODULE.knob_variation(
            "retrieval_depth", [1, 10], {"low": 1.0, "high": 10.0}
        )
        self.assertEqual(scored.kind, "numeric")
        self.assertEqual(scored.span, 1.0)

    def test_unknown_knob_without_bounds_falls_back_to_breadth(self) -> None:
        scored = MODULE.knob_variation("retrieval_depth", [1, 10])
        self.assertEqual(scored.kind, "categorical")
        self.assertGreater(scored.quality, 0.0)
        self.assertTrue(any("no canonical range" in note for note in scored.notes))


class BandAndAggregationTests(unittest.TestCase):
    def test_band_boundaries_are_exact(self) -> None:
        for score, expected in (
            (29, "NOT READY"),
            (30, "PARTIAL"),
            (54, "PARTIAL"),
            (55, "WORKABLE"),
            (74, "WORKABLE"),
            (75, "STRONG"),
            (89, "STRONG"),
            (90, "EXCELLENT"),
            (100, "EXCELLENT"),
        ):
            with self.subTest(score=score):
                band, _ = MODULE.band_for(score, 1.0)
                self.assertEqual(band, expected)

    def test_low_confidence_demotes_a_top_band(self) -> None:
        band, limited = MODULE.band_for(95, 0.4)
        self.assertEqual(band, "WORKABLE")
        self.assertTrue(limited)

    def test_high_confidence_keeps_a_top_band(self) -> None:
        band, limited = MODULE.band_for(95, 0.9)
        self.assertEqual(band, "EXCELLENT")
        self.assertFalse(limited)

    def test_round_half_up_does_not_use_bankers_rounding(self) -> None:
        self.assertEqual(MODULE.round_half_up(74.5), 75)
        self.assertEqual(MODULE.round_half_up(0.5), 1)

    def test_unmeasured_subscores_renormalize_and_lower_confidence(self) -> None:
        pillar = MODULE.combine(
            "dataset",
            [
                MODULE.SubScore("a", 10.0, 10.0, True, ""),
                MODULE.SubScore("b", 0.0, 30.0, False, ""),
            ],
        )
        self.assertEqual(pillar.score, 100)
        self.assertEqual(pillar.confidence, 0.25)

    def test_caps_compose_by_minimum_and_are_ordered(self) -> None:
        pillars = [
            MODULE.combine(name, [MODULE.SubScore("x", 10.0, 10.0, True, "")])
            for name in ("agent", "dataset", "evaluation")
        ]
        caps = [
            MODULE.Cap("z-high", 60, "z"),
            MODULE.Cap("a-low", 25, "a"),
        ]
        score = MODULE.aggregate(pillars, caps, [], dict(MODULE.DEFAULT_WEIGHTS))
        self.assertEqual(score.weighted_average, 100)
        self.assertEqual(score.overall, 25)
        self.assertEqual(score.status, "BLOCKED")
        self.assertEqual([cap.condition for cap in score.caps], ["a-low", "z-high"])

    def test_weighted_average_is_retained_so_a_cap_is_never_hidden(self) -> None:
        pillars = [
            MODULE.combine(name, [MODULE.SubScore("x", 10.0, 10.0, True, "")])
            for name in ("agent", "dataset", "evaluation")
        ]
        score = MODULE.aggregate(
            pillars, [MODULE.Cap("c", 30, "r")], [], dict(MODULE.DEFAULT_WEIGHTS)
        )
        self.assertEqual(score.overall, 30)
        self.assertEqual(score.weighted_average, 100)


class DatasetScoringTests(unittest.TestCase):
    def test_absent_dataset_is_capped_and_blocked(self) -> None:
        pillar, caps = MODULE.score_dataset(MODULE.DatasetFacts(exists=False))
        self.assertEqual([cap.condition for cap in caps], ["dataset-absent"])
        self.assertEqual(pillar.score, 0)

    def test_logs_without_expected_outputs_are_capped_not_merely_low(self) -> None:
        """500 unlabelled rows must not score as WORKABLE - nothing can be scored."""
        _, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(exists=True, rows=500, labelled_rows=0)
        )
        self.assertIn("dataset-no-expected-outputs", [cap.condition for cap in caps])

    def test_fully_synthetic_dataset_is_capped_however_good(self) -> None:
        facts = MODULE.DatasetFacts(
            exists=True,
            rows=400,
            labelled_rows=400,
            tuning_rows=300,
            holdout_rows=300,
            difficulty_bands=("easy", "medium", "hard", "very-hard"),
            difficulty_tagged_rows=400,
            duplicate_status="PASS",
            near_duplicate_status="PASS",
            synthetic=True,
            sources=("synthetic-walkthrough",),
        )
        pillar, caps = MODULE.score_dataset(facts)
        self.assertIn("dataset-fully-synthetic", [cap.condition for cap in caps])
        cap = next(c for c in caps if c.condition == "dataset-fully-synthetic")
        self.assertEqual(cap.ceiling, 65)
        self.assertLess(
            next(s.value for s in pillar.subscores if s.name == "provenance"), 5
        )

    def test_power_is_driven_by_the_smaller_split_not_total_rows(self) -> None:
        wide = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True, rows=100, labelled_rows=100, tuning_rows=96, holdout_rows=4
            )
        )[0]
        balanced = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True, rows=40, labelled_rows=40, tuning_rows=20, holdout_rows=20
            )
        )[0]
        wide_power = next(s.value for s in wide.subscores if s.name == "power")
        balanced_power = next(s.value for s in balanced.subscores if s.name == "power")
        self.assertLess(wide_power, balanced_power)

    def test_untagged_difficulty_is_unmeasured_not_zero(self) -> None:
        """Real production data rarely carries difficulty tags.

        Scoring absence as zero would make our own generated data outscore a
        real dataset, which inverts the whole point.
        """
        pillar, _ = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True, rows=50, labelled_rows=50, difficulty_tagged_rows=None
            )
        )
        difficulty = next(s for s in pillar.subscores if s.name == "difficulty")
        self.assertFalse(difficulty.measured)
        self.assertLess(pillar.confidence, 1.0)

    def test_tune_holdout_overlap_is_capped(self) -> None:
        _, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True, rows=50, labelled_rows=50, split_overlap=True
            )
        )
        self.assertIn("dataset-tune-holdout-overlap", [cap.condition for cap in caps])

    def test_undeclared_provenance_never_reaches_the_production_band(self) -> None:
        pillar, _ = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True, rows=50, labelled_rows=50, sources=("unknown",)
            )
        )
        provenance = next(s for s in pillar.subscores if s.name == "provenance")
        self.assertEqual(provenance.value, 6.0)

    def test_power_uses_labelled_rows_when_no_split_is_declared(self) -> None:
        """90 of the 100 rows cannot be scored, so they buy no precision."""
        pillar, _ = MODULE.score_dataset(
            MODULE.DatasetFacts(exists=True, rows=100, labelled_rows=10)
        )
        power = next(s for s in pillar.subscores if s.name == "power")
        self.assertEqual(power.value, 9.6)
        self.assertIn("100 rows, 10 scoreable", power.evidence)
        self.assertIn("+/-16pp", power.evidence)
        self.assertNotIn("+/-5pp", power.evidence)

    def test_power_uses_the_smaller_labelled_split_not_the_smaller_total_split(
        self,
    ) -> None:
        """The comparison is only as sharp as the thinner *scoreable* side."""
        lopsided = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True,
                rows=100,
                labelled_rows=60,
                tuning_rows=60,
                holdout_rows=40,
                tuning_labelled_rows=20,
                holdout_labelled_rows=40,
            )
        )[0]
        power = next(s for s in lopsided.subscores if s.name == "power")
        # The smaller total split is 40 (18.0 points); the smaller labelled
        # split is 20, which is the number that decides anything.
        self.assertEqual(power.value, 12.0)
        self.assertIn("20/40 scoreable", power.evidence)

        one_sided = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True,
                rows=100,
                labelled_rows=50,
                tuning_rows=50,
                holdout_rows=50,
                tuning_labelled_rows=50,
                holdout_labelled_rows=0,
            )
        )[0]
        collapsed = next(s for s in one_sided.subscores if s.name == "power")
        self.assertEqual(collapsed.value, 5.0)
        self.assertEqual(
            collapsed.evidence,
            "50 tuning / 50 holdout, 50/0 scoreable; 0 comparable examples - "
            "a wiring check, not a score",
        )

    def test_the_clamp_never_raises_the_power_subscore(self) -> None:
        """Clamping is one-directional over the whole grid, not just on examples.

        The counterpart facts label every row and every split fully, which
        reproduces the pre-clamp computation exactly, so `clamped <= unclamped`
        here is the property "a clamp can only lower the score".
        """
        for rows in (5, 10, 29, 30, 49, 50, 99, 100, 299, 300, 400):
            tuning_rows = rows // 2
            holdout_rows = rows - tuning_rows
            half = rows // 2
            shapes: list[tuple[int | None, int | None, int | None, int | None]] = [
                (None, None, None, None)
            ]
            for tuning_labelled in (
                v for v in (0, half // 2, half) if v <= tuning_rows
            ):
                for holdout_labelled in (
                    v for v in (0, half // 2, half) if v <= holdout_rows
                ):
                    shapes.append(
                        (tuning_rows, holdout_rows, tuning_labelled, holdout_labelled)
                    )
            for labelled in (0, 1, rows // 3, rows):
                for tuning, holdout, tuning_labelled, holdout_labelled in shapes:
                    clamped = MODULE.DatasetFacts(
                        exists=True,
                        rows=rows,
                        labelled_rows=labelled,
                        tuning_rows=tuning,
                        holdout_rows=holdout,
                        tuning_labelled_rows=tuning_labelled,
                        holdout_labelled_rows=holdout_labelled,
                    )
                    unclamped = MODULE.DatasetFacts(
                        exists=True,
                        rows=rows,
                        labelled_rows=rows,
                        tuning_rows=tuning,
                        holdout_rows=holdout,
                        tuning_labelled_rows=tuning,
                        holdout_labelled_rows=holdout,
                    )
                    with self.subTest(
                        rows=rows,
                        labelled=labelled,
                        tuning_labelled=tuning_labelled,
                        holdout_labelled=holdout_labelled,
                    ):
                        self.assertLessEqual(
                            self._power(clamped), self._power(unclamped)
                        )

    def test_a_fully_labelled_dataset_keeps_its_evidence_string(self) -> None:
        """Nothing was clamped, so nothing about the sentence may change."""
        pillar, _ = MODULE.score_dataset(
            MODULE.DatasetFacts(exists=True, rows=100, labelled_rows=100)
        )
        power = next(s for s in pillar.subscores if s.name == "power")
        self.assertEqual(power.value, 18.4)
        self.assertEqual(
            power.evidence,
            "no declared tuning/holdout split; 100 examples - roughly +/-5pp "
            "of noise per result",
        )

    def _power(self, facts: object) -> float:
        pillar, _ = MODULE.score_dataset(facts)
        return next(s.value for s in pillar.subscores if s.name == "power")


class EvaluationScoringTests(unittest.TestCase):
    def test_constant_scorer_is_capped_as_invalid(self) -> None:
        facts = MODULE.EvaluationFacts(
            present=True,
            calibration_present=True,
            checks=({"good_passes": True, "bad_fails": False, "non_constant": False},),
        )
        _, caps = MODULE.score_evaluation(facts)
        self.assertIn("evaluator-invalid", [cap.condition for cap in caps])

    def test_weakest_case_drags_the_calibration_score(self) -> None:
        strong = MODULE.EvaluationFacts(
            present=True,
            calibration_present=True,
            checks=(
                {"good_passes": True, "bad_fails": True, "non_constant": True},
                {"good_passes": True, "bad_fails": True, "non_constant": True},
            ),
        )
        mixed = MODULE.EvaluationFacts(
            present=True,
            calibration_present=True,
            checks=(
                {"good_passes": True, "bad_fails": True, "non_constant": True},
                {"good_passes": False, "bad_fails": True, "non_constant": True},
            ),
        )
        strong_value = next(
            s.value
            for s in MODULE.score_evaluation(strong)[0].subscores
            if s.name == "calibration"
        )
        mixed_value = next(
            s.value
            for s in MODULE.score_evaluation(mixed)[0].subscores
            if s.name == "calibration"
        )
        self.assertLess(mixed_value, strong_value)

    def test_deterministic_method_outscores_a_judge_on_reproducibility(self) -> None:
        exact = MODULE.score_evaluation(
            MODULE.EvaluationFacts(present=True, method="exact")
        )[0]
        judge = MODULE.score_evaluation(
            MODULE.EvaluationFacts(present=True, method="llm-judge-pointwise")
        )[0]
        exact_value = next(
            s.value for s in exact.subscores if s.name == "reproducibility"
        )
        judge_value = next(
            s.value for s in judge.subscores if s.name == "reproducibility"
        )
        self.assertGreater(exact_value, judge_value)

    def test_a_deterministic_method_can_still_be_the_wrong_ruler(self) -> None:
        """Exact-match on free text is reproducible and a poor fit."""
        pillar = MODULE.score_evaluation(
            MODULE.EvaluationFacts(present=True, method="exact", task_kind="free-text")
        )[0]
        fit = next(s for s in pillar.subscores if s.name == "task-fit")
        self.assertLess(fit.value, fit.maximum / 2)

    def test_absent_evaluator_is_capped(self) -> None:
        _, caps = MODULE.score_evaluation(MODULE.EvaluationFacts(present=False))
        self.assertIn("evaluator-absent", [cap.condition for cap in caps])

    def test_both_calibration_payload_shapes_parse(self) -> None:
        matrix = MODULE.evaluation_facts_from_calibration(
            {"cases": [{"checks": {"a": True}, "scores": {"good": 1.0, "bad": 0.0}}]}
        )
        single = MODULE.evaluation_facts_from_calibration(
            {"checks": {"a": True}, "scores": {"good": 1.0, "bad": 0.0}}
        )
        self.assertEqual(len(matrix.checks), 1)
        self.assertEqual(len(single.checks), 1)
        self.assertEqual(matrix.probe_scores, single.probe_scores)


# The document the walkthrough's generated wrapper writes: the enhanced space
# after the placeholder temperature is replaced with a neighbor of the
# baseline's winner, with the template's placeholder model ids. Kept here so the
# consumer contract is pinned to the shape the producer actually emits.
WALKTHROUGH_CONFIG_SPACE = {
    "agent_type": "general",
    "knobs": {
        "model": ["provider/current", "provider/alternative", "provider/strong"],
        "prompt_style": ["direct", "structured", "criteria_first"],
        "self_check": [False, True],
        "temperature": [0.0, 0.2, 0.1],
    },
    "max_trials": 12,
    "wired": ["model", "temperature", "prompt_style", "self_check"],
}


class AgentScoringTests(unittest.TestCase):
    def test_wired_varying_knobs_clear_the_no_varying_cap(self) -> None:
        """The walkthrough's own space must not read as "nothing to search".

        `agent-no-varying-knobs` holds the whole run to 45 no matter how good
        the dataset and evaluator are, so this is the cap the config-space
        document exists to clear.
        """
        facts = MODULE.agent_facts_from_config_space(WALKTHROUGH_CONFIG_SPACE)
        pillar, caps, _ = MODULE.score_agent(facts)
        self.assertEqual([cap.condition for cap in caps], [])
        # 35/35 knob-count + 30.4/40 variation + 25/25 coverage. Was 78 while
        # the `general` catalog spelled the prompt dimension `prompt_policy`
        # and listed `max_tokens`; see the catalog comment in readiness.py.
        self.assertEqual(pillar.score, 90)
        self.assertEqual(pillar.confidence, 1.0)

    def test_reasoning_branch_document_still_clears_the_cap(self) -> None:
        """A reasoning model pins temperature to one value; three knobs remain.

        The branch loses knob-count and variation points but must still search,
        so a change that re-caps it is visible here rather than in a run.
        """
        document = dict(
            WALKTHROUGH_CONFIG_SPACE,
            knobs=dict(WALKTHROUGH_CONFIG_SPACE["knobs"], temperature=[0.0]),
        )
        pillar, caps, _ = MODULE.score_agent(
            MODULE.agent_facts_from_config_space(document)
        )
        self.assertEqual([cap.condition for cap in caps], [])
        self.assertEqual(pillar.score, 76)

    def test_config_space_adapter_reads_both_spellings(self) -> None:
        aliased = MODULE.agent_facts_from_config_space(
            {
                "agent_type": "rag",
                "max_trials": 8,
                "configuration_space": {
                    "temperature": [0.0, 1.0],
                    "retrieval_depth": [1, 10],
                },
                "wired": ["temperature", "retrieval_depth"],
                "bounds": {"retrieval_depth": {"low": 1, "high": 10}},
            }
        )
        self.assertEqual(aliased.agent_type, "rag")
        self.assertEqual(aliased.max_trials, 8)
        self.assertEqual(
            aliased.knobs, {"temperature": [0.0, 1.0], "retrieval_depth": [1, 10]}
        )
        self.assertEqual(aliased.wired, ("temperature", "retrieval_depth"))
        self.assertEqual(
            aliased.bounds, {"retrieval_depth": {"low": 1.0, "high": 10.0}}
        )

        both = MODULE.agent_facts_from_config_space(
            {
                "knobs": {"temperature": [0.0, 1.0]},
                "configuration_space": {"ignored": [1, 2]},
            }
        )
        self.assertEqual(both.knobs, {"temperature": [0.0, 1.0]})

        empty_preferred = MODULE.agent_facts_from_config_space(
            {"knobs": {}, "configuration_space": {"temperature": [0.0, 1.0]}}
        )
        self.assertEqual(empty_preferred.knobs, {"temperature": [0.0, 1.0]})

        self.assertEqual(
            MODULE.agent_facts_from_config_space({"knobs": {"a": [1, 2]}}).wired, ()
        )

    def test_malformed_config_space_documents_are_typed_errors(self) -> None:
        """A hand-edited document must be refused, never scored around.

        Each of these reached the scorer as an untyped TypeError/AttributeError/
        ValueError traceback, or - for a non-string `wired` entry - silently
        narrowed the considered knobs to nothing.
        """
        for document in (
            [{"knobs": {"a": [1, 2]}}],
            {"knobs": "nope"},
            {"configuration_space": 7},
            {"knobs": {"a": [1, 2]}, "wired": None},
            {"knobs": {"a": [1, 2]}, "wired": ["a", 3]},
            {"knobs": {"a": [1, 2]}, "bounds": "nope"},
            {"knobs": {"a": [1, 2]}, "bounds": {"a": {"low": "x", "high": 1}}},
        ):
            with self.subTest(document=document):
                with self.assertRaises(MODULE.ConfigSpaceInputError):
                    MODULE.agent_facts_from_config_space(document)

    def test_malformed_config_space_errors_name_the_field(self) -> None:
        with self.assertRaises(MODULE.ConfigSpaceInputError) as raised:
            MODULE.agent_facts_from_config_space(
                {"knobs": {"a": [1, 2]}, "bounds": {"a": {"low": "x", "high": 1}}}
            )
        self.assertIn("bounds['a']['low']", str(raised.exception))

    def test_max_trials_and_agent_type_are_validated_like_every_other_field(
        self,
    ) -> None:
        """Two documented fields used to reach the scorer unchecked.

        `max_trials` lands in `space_size / max_trials` and `agent_type` in a
        dict lookup, so the three bad shapes below produced three different
        behaviours: a raw TypeError traceback, a raw unhashable-type traceback,
        and a silent exit 0 with coverage unmeasured. None of them was the
        refusal `ConfigSpaceInputError` documents.
        """
        for document in (
            {"knobs": {"a": [1, 2]}, "max_trials": "12"},
            {"knobs": {"a": [1, 2]}, "max_trials": -5},
            {"knobs": {"a": [1, 2]}, "max_trials": 0},
            {"knobs": {"a": [1, 2]}, "max_trials": 1.5},
            # bool is an int in Python; True is not a trial budget
            {"knobs": {"a": [1, 2]}, "max_trials": True},
            {"knobs": {"a": [1, 2]}, "agent_type": ["general"]},
            {"knobs": {"a": [1, 2]}, "agent_type": 7},
        ):
            with self.subTest(document=document):
                with self.assertRaises(MODULE.ConfigSpaceInputError):
                    MODULE.agent_facts_from_config_space(document)

    def test_absent_and_unrecognized_optional_fields_still_score(self) -> None:
        """Validation must refuse bad *shapes*, not narrow the documented set.

        An absent `max_trials`/`agent_type` and an unrecognized agent type are
        documented as scoreable - the latter leaves coverage unmeasured rather
        than refusing - so the guards above must not swallow them.
        """
        absent = MODULE.agent_facts_from_config_space({"knobs": {"a": [1, 2]}})
        self.assertIsNone(absent.max_trials)
        self.assertIsNone(absent.agent_type)
        unrecognized = MODULE.agent_facts_from_config_space(
            {"knobs": {"a": [1, 2]}, "agent_type": "summarizer"}
        )
        pillar, _, _ = MODULE.score_agent(unrecognized)
        self.assertEqual(unrecognized.agent_type, "summarizer")
        self.assertLess(pillar.confidence, 1.0)

    def test_malformed_knob_and_bounds_entries_are_refused_not_dropped(self) -> None:
        """Dropping a typo silently made the score *better* and the reason false.

        A knob written as a bare scalar left the space, and a `bounds` entry
        missing an edge left the knob scored against a different range than the
        author declared. Both are refused now: `{"retrieval_depth": [1, 1.01]}`
        with a half-written bound scored 32 with no cap, while the intended
        `"high": 10` collapses the two values into one and scores 0 under
        `agent-no-varying-knobs` - so the typo read as the healthier space.
        """
        for document in (
            {"knobs": {"a": [1, 2], "prompt": "not a list of candidates"}},
            {"configuration_space": {"a": [1, 2], "prompt": 7}},
            {"knobs": {"a": [1, 2]}, "bounds": {"a": {"low": 1}}},
            {"knobs": {"a": [1, 2]}, "bounds": {"a": {"high": 10}}},
            {"knobs": {"a": [1, 2]}, "bounds": {"a": {}}},
            {"knobs": {"a": [1, 2]}, "bounds": {"a": 5}},
            {
                "knobs": {"retrieval_depth": [1, 1.01]},
                "wired": ["retrieval_depth"],
                "bounds": {"retrieval_depth": {"low": 1}},
            },
        ):
            with self.subTest(document=document):
                with self.assertRaises(MODULE.ConfigSpaceInputError):
                    MODULE.agent_facts_from_config_space(document)

    def test_malformed_knob_and_bounds_errors_name_the_entry(self) -> None:
        with self.assertRaises(MODULE.ConfigSpaceInputError) as scalar:
            MODULE.agent_facts_from_config_space(
                {"knobs": {"a": [1, 2], "prompt": "nope"}}
            )
        self.assertIn("'prompt' is str", str(scalar.exception))
        with self.assertRaises(MODULE.ConfigSpaceInputError) as half:
            MODULE.agent_facts_from_config_space(
                {"knobs": {"a": [1, 2]}, "bounds": {"a": {"low": 1}}}
            )
        self.assertIn("bounds['a']", str(half.exception))
        self.assertIn("'high'", str(half.exception))

    def test_numeric_string_bounds_still_score(self) -> None:
        """The bounds guard must not refuse a shape that scored before it.

        This adapter has always read bounds through `float()`, so a document
        with `{"low": "1", "high": "5"}` scored 56. A guard that turns a working
        document into a hard exit-2 failure is worse than the silence it
        replaced, so a numeric string stays legal while `"x"` does not.
        """
        document = {
            "agent_type": "rag",
            "knobs": {"retrieval_k": [1, 5]},
            "wired": ["retrieval_k"],
            "bounds": {"retrieval_k": {"low": "1", "high": "5"}},
        }
        facts = MODULE.agent_facts_from_config_space(document)
        self.assertEqual(facts.bounds, {"retrieval_k": {"low": 1.0, "high": 5.0}})
        pillar, caps, _ = MODULE.score_agent(facts)
        self.assertEqual([cap.condition for cap in caps], [])
        self.assertEqual(pillar.score, 56)
        numeric = MODULE.agent_facts_from_config_space(
            dict(document, bounds={"retrieval_k": {"low": 1, "high": 5}})
        )
        self.assertEqual(MODULE.score_agent(numeric)[0].score, pillar.score)

    def test_falsey_malformed_fields_are_refused_like_truthy_ones(self) -> None:
        """`or {}` read a malformed field as an absent one.

        `document.get("bounds") or {}` cannot tell `[]`, `null`, `0` or `""`
        from "not written", so every guard added for the truthy spellings had a
        falsey twin that walked straight past it: `{"bounds": "nope"}` exited 2
        while `{"bounds": []}` scored the agent pillar 32 and cleared
        `agent-no-varying-knobs`. Presence is now tested with `in` and the type
        is checked on whatever was written, so the two spellings agree.
        """
        for document in (
            {
                "knobs": {"retrieval_depth": [1, 1.01]},
                "wired": ["retrieval_depth"],
                "bounds": [],
            },
            {"knobs": {"a": [1, 2]}, "bounds": None},
            {"knobs": {"a": [1, 2]}, "bounds": 0},
            {"knobs": {"a": [1, 2]}, "bounds": ""},
            {"knobs": []},
            {"knobs": 0},
            {"configuration_space": []},
            {"knobs": None},
            # a malformed alias must not hide behind a well-formed `knobs`
            {"knobs": {"a": [1, 2]}, "configuration_space": []},
            # a document that names neither key says nothing about the space
            {},
            {"agent_type": "general", "max_trials": 12},
        ):
            with self.subTest(document=document):
                with self.assertRaises(MODULE.ConfigSpaceInputError):
                    MODULE.agent_facts_from_config_space(document)

        with self.assertRaises(MODULE.ConfigSpaceInputError) as falsey:
            MODULE.agent_facts_from_config_space({"knobs": {"a": [1, 2]}, "bounds": []})
        self.assertIn("'bounds'", str(falsey.exception))

    def test_empty_declared_space_is_read_not_refused(self) -> None:
        """Refusing an absent declaration must not refuse an empty one.

        `{"knobs": {}}` states that the space has no knobs - a claim the scorer
        reads and reports as "no knobs declared" under
        `agent-no-varying-knobs`. Only a document that declares neither key is
        unreadable.
        """
        facts = MODULE.agent_facts_from_config_space({"knobs": {}})
        self.assertEqual(facts.knobs, {})
        pillar, caps, _ = MODULE.score_agent(facts)
        self.assertEqual([cap.condition for cap in caps], ["agent-no-varying-knobs"])
        self.assertEqual(pillar.score, 0)

    def test_wired_name_absent_from_the_space_is_refused(self) -> None:
        """A typo in a `wired` name raised the score and printed a false count.

        The name is a string, so the list-of-strings check passes it;
        `score_agent` then intersects `wired` with the space and the misspelled
        name simply disappears. The document below declares two knobs, and with
        `temperature` misspelled it scored 38 while asserting "1 of 1 wired
        knobs actually vary" - a higher score and a sentence the document
        itself contradicts. `bounds` addresses knobs by name the same way and
        is refused the same way.
        """
        declared = {"model": ["a", "b"], "temperature": [0.0, 0.5]}
        with self.assertRaises(MODULE.ConfigSpaceInputError) as typo:
            MODULE.agent_facts_from_config_space(
                {"knobs": declared, "wired": ["model", "temperatur"]}
            )
        self.assertIn("'wired'", str(typo.exception))
        self.assertIn("'temperatur'", str(typo.exception))
        self.assertNotIn("'model'", str(typo.exception))

        with self.assertRaises(MODULE.ConfigSpaceInputError) as bound:
            MODULE.agent_facts_from_config_space(
                {
                    "knobs": declared,
                    "bounds": {"temperatur": {"low": 0.0, "high": 1.0}},
                }
            )
        self.assertIn("'bounds'", str(bound.exception))
        self.assertIn("'temperatur'", str(bound.exception))

        # the same names spelled correctly still score
        spelled = MODULE.agent_facts_from_config_space(
            {
                "knobs": declared,
                "wired": ["model", "temperature"],
                "bounds": {"temperature": {"low": 0.0, "high": 1.0}},
            }
        )
        self.assertEqual(spelled.wired, ("model", "temperature"))
        # an alias-declared space is checked against the alias, not against a
        # `knobs` key the author never wrote
        aliased = MODULE.agent_facts_from_config_space(
            {"configuration_space": declared, "wired": ["temperature"]}
        )
        self.assertEqual(aliased.wired, ("temperature",))

    def test_integral_max_trials_scores_however_json_spelled_it(self) -> None:
        """`12.0` is the same trial budget as `12`, and scored as one.

        JSON has a single number type, so an integral budget can arrive as
        either. `isinstance(max_trials, int)` refused the float spelling and
        turned a document that scored 78 on the parent into exit 2. The check
        is on the value now, so the fractional, zero, negative, boolean, and
        non-numeric shapes stay refused.
        """
        integral = MODULE.agent_facts_from_config_space(
            dict(WALKTHROUGH_CONFIG_SPACE, max_trials=12.0)
        )
        self.assertEqual(integral.max_trials, 12)
        self.assertIsInstance(integral.max_trials, int)
        pillar, caps, _ = MODULE.score_agent(integral)
        self.assertEqual([cap.condition for cap in caps], [])
        self.assertEqual(pillar.score, 90)
        self.assertEqual(
            pillar.score,
            MODULE.score_agent(
                MODULE.agent_facts_from_config_space(WALKTHROUGH_CONFIG_SPACE)
            )[0].score,
        )
        # the trial cap still dampens knob-count points identically either way
        crowded = {"knobs": {f"k{i}": [1, 2, 3, 4] for i in range(6)}}
        self.assertEqual(
            MODULE.score_agent(
                MODULE.agent_facts_from_config_space(dict(crowded, max_trials=2.0))
            )[0].score,
            MODULE.score_agent(
                MODULE.agent_facts_from_config_space(dict(crowded, max_trials=2))
            )[0].score,
        )
        for value in (1.5, -5, 0, 0.0, -1.0, True, False, "12", float("nan"), 12.5):
            with self.subTest(max_trials=value):
                with self.assertRaises(MODULE.ConfigSpaceInputError):
                    MODULE.agent_facts_from_config_space(
                        {"knobs": {"a": [1, 2]}, "max_trials": value}
                    )

    def test_non_finite_bounds_are_refused_not_silently_collapsing(self) -> None:
        """`float()` parses "inf" and "nan"; neither is a range.

        An infinite span makes the 2% noise floor infinite and a NaN span makes
        every comparison false, so a knob sweeping 1 -> 50 was reported as
        "nothing to search" - the silent rewrite of the space the bounds guard
        exists to stop, arriving through a value the type check admits.
        """
        sweeping = {
            "agent_type": "general",
            "knobs": {"widget": [1, 50]},
            "wired": ["widget"],
        }
        pillar, caps, _ = MODULE.score_agent(
            MODULE.agent_facts_from_config_space(sweeping)
        )
        self.assertEqual([cap.condition for cap in caps], [])
        self.assertEqual(pillar.score, 32)
        for edges in (
            {"low": "-inf", "high": "inf"},
            {"low": "nan", "high": "nan"},
            {"low": float("inf"), "high": 1},
            {"low": 1, "high": float("nan")},
        ):
            with self.subTest(edges=edges):
                with self.assertRaises(MODULE.ConfigSpaceInputError) as raised:
                    MODULE.agent_facts_from_config_space(
                        dict(sweeping, bounds={"widget": edges})
                    )
                self.assertIn("finite", str(raised.exception))

    def test_no_varying_knob_is_capped(self) -> None:
        _, caps, _ = MODULE.score_agent(
            MODULE.AgentFacts(knobs={"temperature": [0.7]}, wired=("temperature",))
        )
        self.assertIn("agent-no-varying-knobs", [cap.condition for cap in caps])

    def test_unwired_knobs_are_excluded(self) -> None:
        _, _, knobs = MODULE.score_agent(
            MODULE.AgentFacts(
                knobs={"temperature": [0.0, 1.0], "ghost": [1, 2]},
                wired=("temperature",),
            )
        )
        self.assertEqual([knob.name for knob in knobs], ["temperature"])

    def test_knob_count_plateaus_rather_than_ramping(self) -> None:
        four = MODULE.knob_count_points(4, 16, 12)
        twelve = MODULE.knob_count_points(12, 4096, 12)
        self.assertGreater(four, twelve)

    def test_space_far_larger_than_the_trial_budget_is_penalized(self) -> None:
        self.assertLessEqual(MODULE.knob_count_points(5, 5000, 12), 24.0)

    def test_missing_high_impact_knobs_are_named(self) -> None:
        pillar, _, _ = MODULE.score_agent(
            MODULE.AgentFacts(
                agent_type="rag",
                knobs={"temperature": [0.0, 1.0]},
                wired=("temperature",),
            )
        )
        coverage = next(s for s in pillar.subscores if s.name == "coverage")
        self.assertIn("retrieval_k", coverage.evidence)

    def _coverage(self, **kwargs) -> object:
        pillar, _, _ = MODULE.score_agent(MODULE.AgentFacts(**kwargs))
        return next(s for s in pillar.subscores if s.name == "coverage")

    def test_either_prompt_dimension_spelling_earns_the_same_credit(self) -> None:
        """The catalog names one spelling; both must score the same.

        The walkthrough template emits `prompt_style` while the catalog and the
        adapter tests' healthy space use `prompt_policy`. Whichever name the
        catalog carries, the other one is the same search dimension, so
        crediting only one docks a correct document a quarter of its coverage
        points for spelling. The evidence line must still name exactly one of
        them, or "not tuning:" turns into a list of synonyms.
        """
        knobs = {"model": ["a", "b"], "temperature": [0.0, 0.6]}
        for name in ("prompt_style", "prompt_policy"):
            with self.subTest(spelling=name):
                coverage = self._coverage(
                    agent_type="general",
                    knobs=dict(knobs, **{name: ["direct", "structured"]}),
                    wired=("model", "temperature", name),
                )
                self.assertEqual(coverage.value, 25.0)
                self.assertIn("every high-impact knob", coverage.evidence)

        missing = self._coverage(
            agent_type="general",
            knobs=knobs,
            wired=("model", "temperature"),
        )
        self.assertIn("not tuning: prompt_style", missing.evidence)
        self.assertNotIn("prompt_policy", missing.evidence)

    def test_not_sweeping_max_tokens_is_not_a_coverage_gap(self) -> None:
        """`max_tokens` is a capacity guard, so omitting it must not cost points.

        references/run-safety.md tells authors not to sweep low `max_tokens`
        values in any space containing a reasoning model - a truncated answer
        scores 0 for reasons unrelated to configuration quality. While the
        catalog listed it, a space that obeyed that rule was docked 25% of its
        coverage for doing so.
        """
        for agent_type in ("general", "code_gen"):
            with self.subTest(agent_type=agent_type):
                self.assertNotIn("max_tokens", MODULE.HIGH_IMPACT_KNOBS[agent_type])
        for agent_type, catalog in MODULE.HIGH_IMPACT_KNOBS.items():
            with self.subTest(agent_type=agent_type):
                self.assertNotIn("max_tokens", catalog)

        without = self._coverage(
            agent_type="general",
            knobs={
                "model": ["a", "b"],
                "temperature": [0.0, 0.6],
                "prompt_style": ["direct", "structured"],
            },
            wired=("model", "temperature", "prompt_style"),
        )
        self.assertEqual(without.value, 25.0)
        self.assertNotIn("max_tokens", without.evidence)


class ColorAndRenderingTests(unittest.TestCase):
    def test_piped_output_has_no_ansi(self) -> None:
        self.assertFalse(
            MODULE.resolve_color(FakeStream(tty=False), "auto", environ={})
        )

    def test_the_harness_environment_resolves_to_no_color(self) -> None:
        """The exact 11-key environment the offline harness passes.

        `clean_capture` raises on any escape byte, so this must be False or the
        container CI job fails.
        """
        harness_env = {
            "HOME": "/work/home",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": "/repo/tests/behavioral/guard",
            "TMPDIR": "/tmp",
            "TRAIGENT_AUDIT_LOG": "/work/audit.jsonl",
        }
        self.assertFalse(
            MODULE.resolve_color(FakeStream(tty=False), "auto", environ=harness_env)
        )

    def test_no_color_beats_force_color(self) -> None:
        env = {"NO_COLOR": "1", "FORCE_COLOR": "1"}
        self.assertFalse(
            MODULE.resolve_color(FakeStream(tty=True), "auto", environ=env)
        )

    def test_dumb_terminal_disables_color(self) -> None:
        self.assertFalse(
            MODULE.resolve_color(FakeStream(tty=True), "auto", {"TERM": "dumb"})
        )

    def test_hosted_ide_consoles_get_color_without_a_tty(self) -> None:
        for env in (
            {"PYCHARM_HOSTED": "1"},
            {"TERM_PROGRAM": "vscode"},
            {"JPY_PARENT_PID": "42"},
            {"SPY_INTERACTIVE": "1"},
        ):
            with self.subTest(env=env):
                self.assertTrue(
                    MODULE.resolve_color(FakeStream(tty=False), "auto", environ=env)
                )

    def test_explicit_flag_overrides_everything(self) -> None:
        env = {"NO_COLOR": "1"}
        self.assertTrue(MODULE.resolve_color(FakeStream(tty=False), "always", env))
        self.assertFalse(MODULE.resolve_color(FakeStream(tty=True), "never", {}))

    def test_ascii_fallback_when_the_console_cannot_encode_block_glyphs(self) -> None:
        self.assertFalse(
            supports := MODULE.supports_unicode(FakeStream(tty=True, encoding="cp1252"))
        )
        self.assertTrue(MODULE.supports_unicode(FakeStream(tty=True, encoding="utf-8")))
        self.assertNotIn("█", MODULE.bar(50, unicode_ok=supports))

    def test_card_contains_no_ansi_when_palette_is_plain(self) -> None:
        score = self._sample_score()
        card = MODULE.render_card(score, palette=MODULE.PLAIN)
        self.assertNotIn("\x1b", card)

    def test_card_never_contains_a_timestamp(self) -> None:
        card = MODULE.render_card(self._sample_score(), palette=MODULE.PLAIN)
        self.assertNotRegex(card, r"\b20\d\d-\d\d-\d\d\b")

    def test_module_never_reads_the_clock(self) -> None:
        """Reproducibility is structural, not a convention.

        The harness runs every scenario twice and fails on any difference, so a
        clock read anywhere in this module would break the container job.
        """
        tree = ast.parse(SCRIPT.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name, {"time", "datetime"})
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, {"time", "datetime"})

    def test_report_timestamp_is_caller_supplied(self) -> None:
        report = MODULE.render_markdown(self._sample_score(), "2026-01-01T00:00:00Z")
        self.assertIn("2026-01-01T00:00:00Z", report)
        self.assertNotIn(
            "Generated:", MODULE.render_markdown(self._sample_score(), None)
        )

    def _sample_score(self) -> object:
        pillars = [
            MODULE.combine(name, [MODULE.SubScore("x", 5.0, 10.0, True, "half")])
            for name in ("agent", "dataset", "evaluation")
        ]
        return MODULE.aggregate(pillars, [], [], dict(MODULE.DEFAULT_WEIGHTS))


class CliTests(unittest.TestCase):
    @staticmethod
    def _run(argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = MODULE.main(argv)
        return code, buffer.getvalue()

    def test_planner_mode_still_works_without_scoring_flags(self) -> None:
        code, output = self._run(
            ["--agent", "real", "--dataset", "real", "--evaluation", "real"]
        )
        self.assertEqual(code, 0)
        self.assertIn("Real-world readiness: 3/3", output)

    def test_low_score_still_exits_zero(self) -> None:
        """A poor score drives the narrative; it must never fail the run."""
        with tempfile.TemporaryDirectory() as directory:
            space = Path(directory) / "space.json"
            space.write_text(json.dumps({"knobs": {"temperature": [0.7]}}))
            code, _ = self._run(["--config-space", str(space), "--json"])
            self.assertEqual(code, 0)

    def test_strict_exits_one_only_when_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            space = Path(directory) / "space.json"
            space.write_text(json.dumps({"knobs": {"temperature": [0.7]}}))
            code, _ = self._run(["--config-space", str(space), "--json", "--strict"])
            self.assertEqual(code, 1)

    def test_unreadable_input_exits_two(self) -> None:
        code, _ = self._run(["--config-space", "/nonexistent.json"])
        self.assertEqual(code, 2)

    def test_config_space_document_scores_the_agent_pillar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            space = Path(directory) / "config-space.json"
            space.write_text(json.dumps(WALKTHROUGH_CONFIG_SPACE))
            code, output = self._run(["--config-space", str(space), "--json"])
        self.assertEqual(code, 0)
        score = json.loads(output)
        agent = next(p for p in score["pillars"] if p["name"] == "agent")
        self.assertEqual(agent["score"], 90)
        self.assertNotIn(
            "agent-no-varying-knobs", [cap["condition"] for cap in score["caps"]]
        )

    def test_malformed_config_space_exits_two(self) -> None:
        """A typo in a hand-authored document is bad input, not a crash.

        Every sibling scoring input refuses with exit 2 and a message; before
        this, --config-space was the one path that raised a traceback.
        """
        with tempfile.TemporaryDirectory() as directory:
            space = Path(directory) / "config-space.json"
            space.write_text(json.dumps({"knobs": {"a": [1, 2]}, "wired": None}))
            buffer = io.StringIO()
            with contextlib.redirect_stderr(buffer):
                code, _ = self._run(["--config-space", str(space), "--json"])
        self.assertEqual(code, 2)
        self.assertIn("cannot read scoring input:", buffer.getvalue())

    def test_json_output_is_stable_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            space = Path(directory) / "space.json"
            space.write_text(
                json.dumps({"knobs": {"temperature": [0.0, 0.5, 1.0], "k": [1, 5]}})
            )
            first = self._run(["--config-space", str(space), "--json"])[1]
            second = self._run(["--config-space", str(space), "--json"])[1]
            self.assertEqual(first, second)

    def test_report_is_written_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            space = Path(directory) / "space.json"
            space.write_text(json.dumps({"knobs": {"temperature": [0.0, 1.0]}}))
            report = Path(directory) / "report.md"
            self._run(["--config-space", str(space), "--json", "--report", str(report)])
            self.assertIn("Traigent optimization readiness", report.read_text())

    def test_weights_are_configurable_and_reported(self) -> None:
        parsed = MODULE.parse_weights("50,30,20")
        self.assertEqual(parsed["dataset"], 50.0)


if __name__ == "__main__":
    unittest.main()

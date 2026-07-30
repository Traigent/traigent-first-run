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


class WiredAttestationShapeTests(unittest.TestCase):
    """Pin the three `wired` shapes directly, through the document reader.

    traigent-first-run#78: this PR and #74 assigned OPPOSITE meanings to an
    omitted or empty `wired`, and the only test covering it ran an example that
    names every knob explicitly - the one shape both semantics agree on. It
    therefore passed under either, and the contradiction lived only in prose.

    These assert the disputed shapes with no example fence in the way, so a
    future change cannot flip the semantics and stay green.
    """

    def _caps_for(self, document: dict) -> list[str]:
        facts = MODULE.agent_facts_from_config_space(document)
        _, caps, _ = MODULE.score_agent(facts)
        return [cap.condition for cap in caps]

    def test_absent_wired_is_unattested_and_capped(self) -> None:
        # A document that never says what the agent consumes attests nothing.
        # Reading it as "all declared knobs" made writing a six-line JSON file
        # the cheapest way to clear a 45-point safety cap.
        self.assertIn(
            "agent-no-varying-knobs",
            self._caps_for({"knobs": {"model": ["a", "b"], "temperature": [0.0, 1.0]}}),
        )

    def test_explicit_empty_wired_is_also_capped(self) -> None:
        # An explicit [] says "the agent consumes none of them" - the same
        # nothing-to-search state as an absent list, never "all of them".
        self.assertIn(
            "agent-no-varying-knobs",
            self._caps_for(
                {"knobs": {"model": ["a", "b"], "temperature": [0.0, 1.0]}, "wired": []}
            ),
        )

    def test_named_wired_knobs_clear_the_cap(self) -> None:
        # The shape both semantics always agreed on - kept so the two failing
        # cases above cannot be "fixed" by capping everything.
        self.assertNotIn(
            "agent-no-varying-knobs",
            self._caps_for(
                {
                    "knobs": {"model": ["a", "b"], "temperature": [0.0, 1.0]},
                    "wired": ["model", "temperature"],
                }
            ),
        )


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

        # Absent and explicit-empty are different claims and must stay
        # distinguishable at the adapter: absent says nothing about wiring,
        # `[]` says "none of them". Collapsing them here erased the distinction
        # before the scorer could act on it (#78).
        self.assertIsNone(
            MODULE.agent_facts_from_config_space({"knobs": {"a": [1, 2]}}).wired
        )
        self.assertEqual(
            MODULE.agent_facts_from_config_space(
                {"knobs": {"a": [1, 2]}, "wired": []}
            ).wired,
            (),
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

    def test_an_alias_spelling_is_a_declared_name_not_a_phantom(self) -> None:
        """The phantom check ran before the names were collapsed, and refused
        a spelling this module itself defines as legal.

        `wired: ["prompt_style", "prompt_policy"]` against a space declaring
        `prompt_style` scored on the parent and became exit 2 with "'wired'
        names 'prompt_policy', which is not declared in 'knobs'" - a sentence
        that is false by this module's own semantics, because the name does
        match that knob through `KNOB_ALIASES`. The normalization step has to
        run before the validation step that reads the names it normalizes.
        """
        document = {
            "knobs": {"prompt_style": ["a", "b"]},
            "wired": ["prompt_style", "prompt_policy"],
        }
        facts = MODULE.agent_facts_from_config_space(document)
        # one dimension, named once, whichever spellings `wired` used
        self.assertEqual(facts.wired, ("prompt_style",))
        pillar, caps, _ = MODULE.score_agent(facts)
        self.assertEqual([cap.condition for cap in caps], [])
        single = MODULE.agent_facts_from_config_space(
            {"knobs": {"prompt_style": ["a", "b"]}, "wired": ["prompt_style"]}
        )
        self.assertEqual(pillar.score, MODULE.score_agent(single)[0].score)

        # `bounds` addresses knobs by name the same way and is read the same way
        ranged = MODULE.agent_facts_from_config_space(
            {
                "knobs": {"prompt_style": [1, 5]},
                "wired": ["prompt_policy"],
                "bounds": {"prompt_policy": {"low": 1, "high": 5}},
            }
        )
        self.assertEqual(ranged.bounds, {"prompt_style": {"low": 1.0, "high": 5.0}})

        # and a real typo is still refused, naming the spelling that was written
        for field, document in (
            ("wired", {"knobs": {"prompt_style": ["a"]}, "wired": ["prompt_polciy"]}),
            (
                "bounds",
                {
                    "knobs": {"prompt_style": ["a"]},
                    "bounds": {"prompt_polciy": {"low": 0, "high": 1}},
                },
            ),
        ):
            with self.subTest(field=field):
                with self.assertRaises(MODULE.ConfigSpaceInputError) as typo:
                    MODULE.agent_facts_from_config_space(document)
                self.assertIn(f"'{field}'", str(typo.exception))
                self.assertIn("'prompt_polciy'", str(typo.exception))

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


class ConfigSpaceSchemaTests(unittest.TestCase):
    """The declaration is the schema, so these test it as one.

    Three review cycles produced nineteen findings against this validator and
    every one was the same defect: validation was a sequence of independent
    per-field checks, so each round closed the field just reported and the next
    round arrived through the field nobody had written a check for. These tests
    are deliberately not per-field. They assert the properties that make the
    next instance impossible rather than merely unlisted: the adapter reads no
    field the declaration does not name, and every field the declaration does
    name refuses an unreadable value with the typed error.
    """

    def test_the_adapter_reads_no_document_key_outside_the_declaration(self) -> None:
        """A field is declared and validated, or it is not a field.

        This is the property the per-field checks never had. Reading a key
        directly - `document.get("wired")` - is how a field acquired a
        behaviour without acquiring a validator, so the adapter is not allowed
        to name one.
        """
        tree = ast.parse(SCRIPT.read_text())
        adapter = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "agent_facts_from_config_space"
        )
        read_keys = set()
        for node in ast.walk(adapter):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "document"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                read_keys.add(node.args[0].value)
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == "document"
                and isinstance(node.slice, ast.Constant)
            ):
                read_keys.add(node.slice.value)
        self.assertEqual(
            read_keys,
            set(),
            "the adapter must reach every field through CONFIG_SPACE_FIELDS; a "
            "literal key here is a field with a behaviour and no validator",
        )

    def test_every_declared_field_refuses_an_unreadable_value_by_name(self) -> None:
        """No field can be declared without also being validated."""
        self.assertTrue(MODULE.CONFIG_SPACE_FIELDS)
        for spec in MODULE.CONFIG_SPACE_FIELDS:
            with self.subTest(field=spec.name):
                with self.assertRaises(MODULE.ConfigSpaceInputError) as raised:
                    spec.read(spec.name, object())
                self.assertIn(spec.name, str(raised.exception))

    def test_a_key_the_declaration_does_not_name_is_ignored_whole(self) -> None:
        """The documented behaviour for an unknown key: ignored, not half-read."""
        facts = MODULE.agent_facts_from_config_space(
            {
                "knobs": {"temperature": [0.0, 1.0]},
                "wired": ["temperature"],
                "notes": {"anything": [object]},
                "seed_policy": "whatever",
            }
        )
        self.assertEqual(facts.knobs, {"temperature": [0.0, 1.0]})

    def test_candidate_values_are_scalars_not_containers(self) -> None:
        """A nested value crashed where the schema promised a named refusal.

        `{"model": [{"a": 1}, {"b": 2}]}` and `[["a"], ["b"]]` are documents the
        documented type admitted - the entry is a list of candidate values -
        and both reached `dict.fromkeys(values)` as unhashable keys, exiting 1
        with a bare `TypeError` instead of the exit-2 refusal every other
        malformed shape gets.
        """
        for candidates in ([{"a": 1}, {"b": 2}], [["a"], ["b"]], [{"a": 1}, "b"]):
            with self.subTest(candidates=candidates):
                with self.assertRaises(MODULE.ConfigSpaceInputError) as raised:
                    MODULE.agent_facts_from_config_space(
                        {"knobs": {"model": candidates}, "wired": ["model"]}
                    )
                self.assertIn("knobs['model']", str(raised.exception))
        # the scalars stay legal, including null and a large integer
        facts = MODULE.agent_facts_from_config_space(
            {"knobs": {"stop": [None, "\n", 1, 1.5, True, 10**400]}}
        )
        self.assertEqual(facts.knobs["stop"], [None, "\n", 1, 1.5, True, 10**400])

    def test_non_finite_candidates_are_refused_not_scored(self) -> None:
        """`[0.0, Infinity]` scored 72 and cleared every cap; `[nan, nan]` 59.

        Neither is a set of runs. A knob is scored against the span its values
        cover, so an infinite span makes the noise floor infinite and a NaN
        span makes every comparison false - both of which the scorer reported
        as a confident number over a sweep that cannot exist.
        """
        for values in (
            [0.0, float("inf")],
            [float("nan"), float("nan")],
            [0.0, float("-inf")],
        ):
            with self.subTest(values=values):
                with self.assertRaises(MODULE.ConfigSpaceInputError) as raised:
                    MODULE.agent_facts_from_config_space(
                        {
                            "agent_type": "general",
                            "knobs": {"temperature": values},
                            "wired": ["temperature"],
                        }
                    )
                self.assertIn("temperature", str(raised.exception))

    def test_a_knob_with_no_candidates_is_refused_not_counted(self) -> None:
        """Both numbers in the evidence line were false.

        `{"model": []}` scored the agent pillar 8 under
        `0 of 1 wired knobs actually vary; 1 combinations`: the knob has no
        values, and a space containing it has no configurations at all.
        """
        with self.assertRaises(MODULE.ConfigSpaceInputError) as raised:
            MODULE.agent_facts_from_config_space(
                {"agent_type": "general", "knobs": {"model": []}, "wired": ["model"]}
            )
        self.assertIn("knobs['model']", str(raised.exception))
        # an empty *space* still means "no knobs declared" and still scores
        self.assertEqual(MODULE.agent_facts_from_config_space({"knobs": {}}).knobs, {})

    def test_bounds_are_validated_as_a_pair_not_only_edge_by_edge(self) -> None:
        """Two finite edges can still be no range.

        Each edge was checked alone, so `{"low": 5, "high": 1}` scored 32 with
        every span negative, and `{"low": 3, "high": 3}` scored 32 *and* cleared
        `agent-no-varying-knobs` by zeroing the noise floor - two values a hair
        apart read as a full sweep of a range that admits one value.
        """
        sweeping = {
            "agent_type": "general",
            "knobs": {"widget": [1, 50]},
            "wired": ["widget"],
        }
        for edges in (
            {"low": 5, "high": 1},
            {"low": 3, "high": 3},
            {"low": 1.0, "high": 1.0},
        ):
            with self.subTest(edges=edges):
                with self.assertRaises(MODULE.ConfigSpaceInputError) as raised:
                    MODULE.agent_facts_from_config_space(
                        dict(sweeping, bounds={"widget": edges})
                    )
                self.assertIn("bounds['widget']", str(raised.exception))
        # a range with width still scores: the pair check must refuse only the
        # ranges that have none
        facts = MODULE.agent_facts_from_config_space(
            dict(sweeping, bounds={"widget": {"low": 1, "high": 50}})
        )
        self.assertEqual(facts.bounds, {"widget": {"low": 1.0, "high": 50.0}})
        self.assertEqual(MODULE.score_agent(facts)[0].score, 51)
        self.assertEqual(
            MODULE.score_agent(MODULE.agent_facts_from_config_space(sweeping))[0].score,
            32,
        )

    def test_bounds_width_must_be_a_number_the_scorer_can_use(self) -> None:
        """Ordered finite edges are still not a usable range.

        The pair check read the edges and never the width they make, so both
        harms it closes were reachable one step outside it:

        * `{"low": -1e308, "high": 1e308}` are two finite numbers whose
          difference overflows to `inf`, so the noise floor is infinite and the
          knob sweeping 1 -> 50 scored agent 0 under `agent-no-varying-knobs` -
          the verbatim harm `_read_edge` refuses the spelling "inf" to prevent.
        * `{"low": 0.0, "high": 5e-324}` has `low < high` and a width whose 2%
          underflows to 0.0, so two values a hair apart scored 51 and cleared
          the cap - the verbatim harm the `low == high` refusal cites.
        """
        for knobs, edges, harm in (
            ({"k": [1, 50]}, {"low": -1e308, "high": 1e308}, "infinite width"),
            ({"k": [0.0, 5e-324]}, {"low": 0.0, "high": 5e-324}, "zero noise floor"),
        ):
            with self.subTest(harm=harm):
                with self.assertRaises(MODULE.ConfigSpaceInputError) as raised:
                    MODULE.agent_facts_from_config_space(
                        {
                            "agent_type": "general",
                            "knobs": knobs,
                            "wired": ["k"],
                            "bounds": {"k": edges},
                        }
                    )
                self.assertIn("bounds['k']", str(raised.exception))

        # a narrow range that is still measurable is not refused: the guard is
        # on the width the scorer can use, not on ranges being small
        sweeping = {"agent_type": "general", "knobs": {"k": [1, 50]}, "wired": ["k"]}
        for edges in ({"low": 1, "high": 50}, {"low": 0.0, "high": 1e-300}):
            with self.subTest(edges=edges):
                facts = MODULE.agent_facts_from_config_space(
                    dict(sweeping, bounds={"k": edges})
                )
                self.assertEqual(facts.bounds["k"]["high"], float(edges["high"]))
        self.assertEqual(
            MODULE.score_agent(
                MODULE.agent_facts_from_config_space(
                    dict(sweeping, bounds={"k": {"low": 1, "high": 50}})
                )
            )[0].score,
            51,
        )

    def test_a_large_integer_trial_budget_scores_like_any_other(self) -> None:
        """`10**309` is a positive JSON integer, and it exited 1.

        The guard read it through `float(max_trials).is_integer()`, which
        raises OverflowError - so a document the parent scored became a
        traceback, which is the failure mode the guard was added to remove.
        `space_size / max_trials` had the same defect from the other side.
        """
        document = {
            "agent_type": "general",
            "knobs": {"widget": [1, 50]},
            "wired": ["widget"],
        }
        huge = MODULE.agent_facts_from_config_space(dict(document, max_trials=10**309))
        self.assertEqual(huge.max_trials, 10**309)
        self.assertEqual(
            MODULE.score_agent(huge)[0].score,
            MODULE.score_agent(MODULE.agent_facts_from_config_space(document))[0].score,
        )
        # and from the other side: a space too large to divide by anything
        crowded = MODULE.agent_facts_from_config_space(
            {
                "knobs": {f"k{index}": [1, 2] for index in range(1330)},
                "wired": [f"k{index}" for index in range(1330)],
                "max_trials": 1,
            }
        )
        pillar, _, _ = MODULE.score_agent(crowded)
        self.assertGreater(pillar.score, 0)

    def test_one_dimension_earns_one_dimension_of_credit(self) -> None:
        """The alias was normalized inside coverage, after everything counted.

        Knob-count, variation and the combination count had already run, so
        declaring `prompt_style` and `prompt_policy` over the same values
        scored higher than declaring either alone, claimed one more varying
        knob than the space has, and multiplied the reported combinations by
        the alias's own value count.
        """
        knobs = {
            "model": ["a", "b"],
            "temperature": [0.0, 0.6],
            "self_check": [False, True],
        }
        values = ["direct", "structured", "criteria_first"]

        def score(space: dict) -> tuple:
            pillar, _, _ = MODULE.score_agent(
                MODULE.agent_facts_from_config_space(
                    {
                        "agent_type": "general",
                        "knobs": space,
                        "wired": sorted(space),
                    }
                )
            )
            count = next(s for s in pillar.subscores if s.name == "knob-count")
            return pillar.score, count.evidence

        style = score(dict(knobs, prompt_style=values))
        policy = score(dict(knobs, prompt_policy=values))
        both = score(dict(knobs, prompt_style=values, prompt_policy=values))
        self.assertEqual(style, policy, "either spelling must score identically")
        self.assertEqual(
            both,
            style,
            "both spellings name one dimension, so declaring both must not "
            "add a knob, add variation credit, or multiply the space size",
        )
        self.assertIn("4 of 4 wired knobs actually vary; 24 combinations", style[1])

    def test_two_spellings_with_different_values_are_refused(self) -> None:
        """One dimension cannot have two answers, and picking one silently is
        exactly the narrowing every other guard here exists to stop."""
        with self.assertRaises(MODULE.ConfigSpaceInputError) as raised:
            MODULE.agent_facts_from_config_space(
                {
                    "knobs": {
                        "prompt_style": ["direct", "structured"],
                        "prompt_policy": ["direct", "criteria_first"],
                    }
                }
            )
        self.assertIn("prompt_policy", str(raised.exception))
        self.assertIn("prompt_style", str(raised.exception))

    def test_a_boolean_domain_is_not_the_same_domain_as_its_numbers(self) -> None:
        """`True == 1` in Python, so the conflict check could not see one.

        `{"prompt_style": [true, false], "prompt_policy": [1, 0]}` are two
        spellings of one dimension over two different candidate lists, and the
        list comparison read them as identical: the second was dropped silently
        and the space was scored as if the author had written one of them - the
        narrowing the refusal exists to stop, arriving through Python's own
        equality. `dict.fromkeys` collapsed the pair the same way beforehand.
        """
        with self.assertRaises(MODULE.ConfigSpaceInputError) as raised:
            MODULE.agent_facts_from_config_space(
                {"knobs": {"prompt_style": [True, False], "prompt_policy": [1, 0]}}
            )
        self.assertIn("prompt_style", str(raised.exception))
        self.assertIn("prompt_policy", str(raised.exception))

        # The key is bool-aware, not `repr`-based: `1` and `1.0` are one
        # candidate to `knob_variation` and to the combination count, so two
        # spellings that differ only in how JSON spelled the same number are
        # still one dimension and must not become a hard refusal.
        merged = MODULE.agent_facts_from_config_space(
            {"knobs": {"prompt_style": [1, 2], "prompt_policy": [1.0, 2.0]}}
        )
        self.assertEqual(list(merged.knobs), ["prompt_style"])
        self.assertEqual(
            MODULE.candidate_domain([True, False]),
            [(True, True), (True, False)],
        )
        self.assertNotEqual(
            MODULE.candidate_domain([True, False]), MODULE.candidate_domain([1, 0])
        )
        self.assertEqual(
            MODULE.candidate_domain([1, 2]), MODULE.candidate_domain([1.0, 2.0])
        )

    def test_the_combination_count_uses_the_same_values_the_card_counts(
        self,
    ) -> None:
        """`[1, 1.0]` is one value everywhere else and was two combinations.

        The count was taken over `repr`, so the same sentence reported a knob
        that does not vary beside a space with two configurations in it.
        """
        pillar, caps, _ = MODULE.score_agent(
            MODULE.agent_facts_from_config_space(
                {"knobs": {"a": [1, 1.0]}, "wired": ["a"]}
            )
        )
        count = next(s for s in pillar.subscores if s.name == "knob-count")
        self.assertEqual(
            count.evidence, "0 of 1 wired knobs actually vary; 1 combinations"
        )
        self.assertIn("agent-no-varying-knobs", [cap.condition for cap in caps])


class DocumentedSchemaTests(unittest.TestCase):
    def test_the_walkthrough_document_still_scores_and_clears_the_cap(self) -> None:
        """The pin the alias change could have moved, measured rather than assumed.

        The shipped space declares only `prompt_style`, so collapsing the alias
        leaves its four dimensions and 54 combinations untouched and the 90
        stands.
        """
        pillar, caps, _ = MODULE.score_agent(
            MODULE.agent_facts_from_config_space(WALKTHROUGH_CONFIG_SPACE)
        )
        self.assertEqual([cap.condition for cap in caps], [])
        self.assertEqual(pillar.score, 90)
        count = next(s for s in pillar.subscores if s.name == "knob-count")
        self.assertEqual(
            count.evidence, "4 of 4 wired knobs actually vary; 54 combinations"
        )

    def test_absent_wired_attests_nothing_rather_than_everything(self) -> None:
        """A document that never named the wired knobs attested none of them.

        Declaring a knob is not a statement that the agent consumes it. Reading
        an absent `wired` list as "every declared knob is wired" let a six-line
        hand-written file buy agent points and retire the cap, so the honest
        state is zero knobs attested as wired, still capped.
        """
        pillar, caps, knobs = MODULE.score_agent(
            MODULE.AgentFacts(knobs={"model": ["a", "b"]})
        )
        self.assertIn("agent-no-varying-knobs", [cap.condition for cap in caps])
        self.assertEqual(pillar.score, 0)
        self.assertEqual(knobs, [])
        measured = {s.name: s.measured for s in pillar.subscores}
        self.assertEqual(
            measured, {"knob-count": True, "variation": False, "coverage": False}
        )

    def test_declared_knobs_without_wiring_score_like_no_document(self) -> None:
        """The declaration on its own is worth exactly zero points.

        Confidence is asserted alongside the score because the two can diverge:
        an earlier draft scored both at 0 but reported the declared-knobs run at
        confidence 0.00 against 0.35 for no document at all, which is the
        inversion `nothing_to_search_pillar` exists to prevent.
        """
        declared, _, _ = MODULE.score_agent(
            MODULE.AgentFacts(knobs={"model": ["a", "b"]})
        )
        absent, _, _ = MODULE.score_agent(MODULE.AgentFacts())
        self.assertEqual(declared.score, absent.score)
        self.assertEqual(declared.confidence, absent.confidence)

    def test_a_config_space_never_lowers_agent_confidence(self) -> None:
        """Monotonicity: more input must never report as less observed.

        Every state with no knob attested as wired reports one confidence, so
        supplying a document can only hold it level or raise it.
        """
        absent, _, _ = MODULE.score_agent(MODULE.AgentFacts())
        for label, facts in (
            ("declared, unattested", MODULE.AgentFacts(knobs={"model": ["a", "b"]})),
            (
                "declared, attested empty",
                MODULE.AgentFacts(knobs={"model": ["a", "b"]}, wired=()),
            ),
            (
                "declared and wired",
                MODULE.AgentFacts(knobs={"model": ["a", "b"]}, wired=("model",)),
            ),
        ):
            with self.subTest(document=label):
                pillar, _, _ = MODULE.score_agent(facts)
                self.assertGreaterEqual(pillar.confidence, absent.confidence)

    def test_empty_knobs_document_is_unchanged_by_the_wired_key(self) -> None:
        """The emptiest document keeps the wording and confidence it always had.

        `not facts.knobs` is answered ahead of the `wired` branch, so both
        spellings still say "no knobs declared" rather than the wiring message.
        Reordering those two branches would change that silently, so pin both.
        """
        for document in ({"knobs": {}}, {"knobs": {}, "wired": []}):
            with self.subTest(document=document):
                pillar, caps, knobs = MODULE.score_agent(
                    MODULE.agent_facts_from_config_space(document)
                )
                self.assertEqual(
                    [cap.condition for cap in caps], ["agent-no-varying-knobs"]
                )
                self.assertEqual(
                    [cap.reason for cap in caps],
                    [
                        "No tunable knob is attested as wired, so there is "
                        "nothing to search."
                    ],
                )
                self.assertEqual(knobs, [])
                self.assertEqual(pillar.score, 0)
                self.assertEqual(pillar.confidence, 0.35)
                self.assertEqual(
                    {s.evidence for s in pillar.subscores}, {"no knobs declared"}
                )

    def test_explicit_empty_wired_is_an_attested_zero(self) -> None:
        """`"wired": []` states something an absent list does not.

        It names zero wired knobs, so knob-count is a counted zero - and the
        evidence must not repeat the "no knobs declared" line, because knobs
        *are* declared here; zero of them are attested as wired.
        """
        pillar, caps, _ = MODULE.score_agent(
            MODULE.AgentFacts(knobs={"temperature": [0.0, 1.0]}, wired=())
        )
        self.assertIn("agent-no-varying-knobs", [cap.condition for cap in caps])
        knob_count = next(s for s in pillar.subscores if s.name == "knob-count")
        self.assertTrue(knob_count.measured)
        self.assertEqual(
            knob_count.evidence, "0 of 1 declared knobs are attested as wired"
        )

    def test_explicit_wiring_still_scores_the_knob(self) -> None:
        """Guard against over-correcting into "nothing ever scores".

        Asserted structurally rather than against the pillar integer: the
        high-impact knob catalog is being reworked on a sibling branch, and a
        pinned number would fail there for a reason that has nothing to do with
        wiring.
        """
        pillar, caps, knobs = MODULE.score_agent(
            MODULE.AgentFacts(knobs={"model": ["a", "b"]}, wired=("model",))
        )
        self.assertNotIn("agent-no-varying-knobs", [cap.condition for cap in caps])
        self.assertEqual([knob.name for knob in knobs], ["model"])
        self.assertGreater(pillar.score, 0)
        self.assertEqual(pillar.confidence, 1.0)


class ConfigSpaceAdapterTests(unittest.TestCase):
    """The adapter must preserve the difference between the three states.

    `wired` has three meanings - never recorded, recorded as empty, recorded as
    a subset - and only key *presence* distinguishes the first two. A future
    `document.get("wired", ())` would collapse them again silently, so pin the
    mapping here rather than only its downstream effect on the score.
    """

    def test_absent_wired_key_maps_to_none(self) -> None:
        facts = MODULE.agent_facts_from_config_space({"knobs": {"model": ["a", "b"]}})
        self.assertIsNone(facts.wired)

    def test_present_empty_wired_stays_distinct_from_an_absent_key(self) -> None:
        """`assertEqual(facts.wired, ())` alone would not catch the collapse.

        A `document.get("wired", ())` adapter also satisfies it, so the guard is
        the *difference*: the empty list and the absent key must not map to the
        same value. No collapsing adapter can pass that.
        """
        empty = MODULE.agent_facts_from_config_space(
            {"knobs": {"model": ["a", "b"]}, "wired": []}
        )
        absent = MODULE.agent_facts_from_config_space({"knobs": {"model": ["a", "b"]}})
        self.assertEqual(empty.wired, ())
        self.assertNotEqual(empty.wired, absent.wired)


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


PREFLIGHT_RECORDS = [
    {
        "check": "dataset-provenance",
        "status": "PASS",
        "metrics": {
            "rows": 40,
            "labelled_rows": 40,
            "sources": ["reviewed-production"],
            "synthetic": False,
        },
    },
    {
        "check": "dataset-integrity",
        "status": "PASS",
        "metrics": {"malformed_rows": 0},
    },
]


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

    def test_wired_less_config_space_adds_no_points(self) -> None:
        """Handing the scorer a knob document must not, by itself, buy anything.

        Written as a two-run differential over identical preflight input rather
        than as an absolute `overall == 0`: the complaint is that the file
        *added points*, and a differential keeps pinning that through any later
        rescaling of the pillars.
        """
        with tempfile.TemporaryDirectory() as directory:
            preflight = Path(directory) / "preflight.json"
            preflight.write_text(json.dumps(PREFLIGHT_RECORDS))
            space = Path(directory) / "space.json"
            space.write_text(
                json.dumps({"knobs": {"model": ["gpt-4o-mini", "gpt-4o"]}})
            )
            without = json.loads(
                self._run(["--preflight", str(preflight), "--json"])[1]
            )
            with_document = json.loads(
                self._run(
                    [
                        "--preflight",
                        str(preflight),
                        "--config-space",
                        str(space),
                        "--json",
                    ]
                )[1]
            )
        self.assertEqual(with_document["overall"], without["overall"])
        self.assertEqual(with_document["band"], without["band"])
        # ...and must not cost anything either. The first draft of this fix
        # reported 0.49 without the document and 0.40 with it, so supplying more
        # input read as having observed less.
        self.assertEqual(with_document["confidence"], without["confidence"])
        conditions = {cap["condition"] for cap in with_document["caps"]}
        self.assertEqual(conditions, {cap["condition"] for cap in without["caps"]})
        self.assertIn("agent-no-varying-knobs", conditions)

    def test_absent_wiring_card_reports_an_unattested_connection(self) -> None:
        """What the user reads must name what the document failed to state.

        The negative assertions matter as much as the positive one: the card
        used to claim "1 of 1 wired knobs actually vary" about a knob nobody had
        named, and "no knobs declared" is false whenever knobs are declared.
        Both strings live in branches that are still reachable, so pin their
        absence rather than trusting that this branch can no longer produce them.
        """
        with tempfile.TemporaryDirectory() as directory:
            space = Path(directory) / "space.json"
            space.write_text(
                json.dumps({"knobs": {"model": ["gpt-4o-mini", "gpt-4o"]}})
            )
            _, output = self._run(["--config-space", str(space), "--color", "never"])
        self.assertIn("does not state which of them the agent consumes", output)
        self.assertNotIn("1 of 1 wired knobs", output)
        self.assertNotIn("no knobs declared", output)

    def test_weights_are_configurable_and_reported(self) -> None:
        parsed = MODULE.parse_weights("50,30,20")
        self.assertEqual(parsed["dataset"], 50.0)


class ThinPillarCannotPresentAsVerifiedTests(unittest.TestCase):
    """A pillar nobody measured must not carry a STRONG or EXCELLENT band.

    `band_for`'s stated promise is that "a thin-evidence run is not allowed to
    present as STRONG or EXCELLENT". The aggregate confidence alone did not
    deliver it: it is a weighted mean, so two fully-measured pillars carry a
    nearly-unmeasured third over the gate.
    """

    def test_the_aggregate_alone_lets_a_thin_pillar_through(self) -> None:
        """The exact arithmetic that defeated the guard.

        agent 1.00, dataset 1.00, evaluation 0.45 at weights 40/35/25 average to
        0.81 - clear of the 0.75 gate - so a 100/100 evaluation pillar that had
        observed two of its four checks reported STRONG.
        """
        aggregate = 0.40 * 1.0 + 0.35 * 0.45 + 0.25 * 1.0
        self.assertAlmostEqual(aggregate, 0.8075, places=4)
        self.assertGreaterEqual(aggregate, MODULE.MIN_CONFIDENCE_FOR_TOP_BANDS)

        # Aggregate only: undemoted, which is the bug.
        self.assertEqual(MODULE.band_for(89, aggregate), ("STRONG", False))
        # Weakest pillar considered: demoted to the confidence ceiling.
        self.assertEqual(
            MODULE.band_for(89, aggregate, 0.45),
            (MODULE.CONFIDENCE_BAND_CEILING, True),
        )

    def test_a_fully_measured_run_is_not_demoted(self) -> None:
        """The guard must not punish a project that actually measured."""
        self.assertEqual(MODULE.band_for(92, 1.0, 1.0), ("EXCELLENT", False))
        self.assertEqual(MODULE.band_for(80, 0.9, 0.8), ("STRONG", False))

    def test_a_band_already_at_or_below_the_ceiling_is_untouched(self) -> None:
        """Demotion only ever lowers, and only from above the ceiling."""
        for score, band in ((10, "NOT READY"), (40, "PARTIAL"), (60, "WORKABLE")):
            with self.subTest(band=band):
                self.assertEqual(MODULE.band_for(score, 0.2, 0.1), (band, False))


class PowerBoundsTheBandTests(unittest.TestCase):
    """Power must be able to say "this cannot be trusted", not only deduct.

    Power is 25 of the dataset pillar's 100 and the pillar is 40% of the total,
    so the whole range from perfect to worst moves the overall score by 8. A
    one-row holdout could still reach 92 and read as "proceed" - the card said
    "a wiring check, not a score" and returned STRONG in the same breath
    (traigent-first-run#88).
    """

    def test_a_dataset_too_small_to_measure_cannot_present_as_strong(self) -> None:
        cap = MODULE.power_ceiling(3)
        self.assertIsNotNone(cap)
        self.assertEqual(cap.condition, "dataset-below-measurable-size")
        self.assertEqual(cap.ceiling, MODULE.WIRING_CHECK_CEILING)
        # Below the STRONG floor, so the result cannot present as trustworthy.
        self.assertLess(cap.ceiling, 75)

    def test_a_coarse_dataset_cannot_present_as_excellent(self) -> None:
        cap = MODULE.power_ceiling(15)
        self.assertIsNotNone(cap)
        self.assertEqual(cap.condition, "dataset-coarse-resolution")
        self.assertLess(cap.ceiling, 90)

    def test_a_ceiling_that_only_bounds_a_claim_does_not_block_the_run(self) -> None:
        """A bounded claim and a stopped run are different statements.

        Every cap used to imply BLOCKED, which was right while every cap meant
        "something here is broken". `dataset-coarse-resolution` says only "this
        cannot present as EXCELLENT" - the run is worth making. Conflating them
        marked a healthy 30-row dataset BLOCKED and told the assistant not to
        proceed, against the guide's own rule that a low score never stops the
        walkthrough. Caught by the fixture bank: "a blocked run cannot be told
        to proceed".
        """
        coarse = MODULE.power_ceiling(15)
        self.assertFalse(coarse.blocks)
        # Too few to measure anything IS a stop: there is nothing to compare.
        self.assertTrue(MODULE.power_ceiling(3).blocks)
        # And the ceiling still binds even though it does not block.
        self.assertEqual(coarse.ceiling, MODULE.COARSE_RESOLUTION_CEILING)

    def test_status_is_blocked_only_by_a_blocking_cap(self) -> None:
        pillar = MODULE.Pillar(name="dataset", score=90, confidence=1.0, subscores=())
        soft = MODULE.Cap("dataset-coarse-resolution", 89, "bounded", blocks=False)
        hard = MODULE.Cap("dataset-absent", 20, "stopped")

        def status_for(caps):
            return MODULE.aggregate(
                [pillar], caps=caps, knobs=(), weights=dict(MODULE.DEFAULT_WEIGHTS)
            ).status

        self.assertEqual(status_for([soft]), "OK")
        self.assertEqual(status_for([hard]), "BLOCKED")
        self.assertEqual(status_for([soft, hard]), "BLOCKED")

    def test_a_dataset_that_can_resolve_is_not_capped(self) -> None:
        for count in (30, 100, 500):
            with self.subTest(count=count):
                self.assertIsNone(MODULE.power_ceiling(count))

    def test_an_unknown_size_is_not_capped(self) -> None:
        """No size reported is not the same claim as a small size."""
        self.assertIsNone(MODULE.power_ceiling(None))


class ReferenceFreeEvaluatorsAreNotClampedTests(unittest.TestCase):
    """#67, which #88 was blocked on.

    A rubric or pointwise judge reads the input and the output; the gold answer
    is not an input to it. Clamping its scoreable count to the labelled rows
    under-states power - and capping a number known to be wrong would convert a
    soft under-claim into a hard, band-changing false verdict.
    """

    def test_a_rubric_judge_scores_rows_without_a_reference(self) -> None:
        for method in ("llm-judge-rubric", "llm-judge-pointwise", "llm-judge-pairwise"):
            with self.subTest(method=method):
                self.assertTrue(MODULE.scores_without_a_reference(method))

    def test_a_reference_based_method_still_needs_the_answer(self) -> None:
        for method in ("exact", "contains", "regex", None):
            with self.subTest(method=method):
                self.assertFalse(MODULE.scores_without_a_reference(method))

    def test_the_clamp_follows_the_method_on_a_declared_split_too(self) -> None:
        """The common shape, and the one the first fix missed.

        Preflight emits per-split labelled counts whenever a split is declared,
        so that branch - not the no-split fallback - is where most datasets
        land. Fixing only the fallback left the method-awareness dead exactly
        where it mattered, and the first version of this suite did not catch it
        because its fixture declared no split.
        """
        facts = MODULE.DatasetFacts(
            exists=True,
            rows=100,
            labelled_rows=10,
            collected_rows=100,
            tuning_rows=50,
            holdout_rows=50,
            tuning_labelled_rows=5,
            holdout_labelled_rows=5,
        )
        reference_based, _ = MODULE.score_dataset(facts, "exact")
        reference_free, _ = MODULE.score_dataset(facts, "llm-judge-rubric")

        power_of = lambda pillar: next(  # noqa: E731
            sub for sub in pillar.subscores if sub.name == "power"
        )
        # 5 scoreable against 50: the judge must be credited the whole split.
        self.assertIn("5/5 scoreable", power_of(reference_based).evidence)
        self.assertIn("50 examples", power_of(reference_free).evidence)
        self.assertGreater(
            power_of(reference_free).value, power_of(reference_based).value
        )

    def test_the_clamp_follows_the_method(self) -> None:
        """100 rows, 10 with reference answers - the case #67 names."""
        facts = MODULE.DatasetFacts(
            exists=True, rows=100, labelled_rows=10, collected_rows=100
        )
        reference_based, _ = MODULE.score_dataset(facts, "exact")
        reference_free, _ = MODULE.score_dataset(facts, "llm-judge-rubric")

        power_of = lambda pillar: next(  # noqa: E731
            sub for sub in pillar.subscores if sub.name == "power"
        )
        # The judge scores all 100, so it must not be told it has 10.
        self.assertGreater(
            power_of(reference_free).value, power_of(reference_based).value
        )
        self.assertIn("100 examples", power_of(reference_free).evidence)


if __name__ == "__main__":
    unittest.main()

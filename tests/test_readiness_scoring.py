from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from dataclasses import asdict
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

    def test_a_pinned_knob_earns_the_pin_credit_and_nothing_more(self) -> None:
        """One declared value is a decision, not a search.

        `temperature: [0]` on a task that must be reproducible is expertise,
        so it is not scored zero - but it contributes no configurations, so it
        is scored almost zero. The rung is grafted onto the numeric path: span,
        resolution and coverage stay honestly zero beside it.
        """
        knob = MODULE.knob_variation("temperature", [0.7])
        self.assertEqual(knob.quality, MODULE.PINNED_KNOB_CREDIT)
        self.assertEqual(knob.quality, 0.10)
        self.assertEqual((knob.span, knob.resolution, knob.coverage), (0.0, 0.0, 0.0))
        self.assertEqual(knob.effective_values, 1)
        self.assertIn("only one value - nothing to search", knob.notes)

    def test_the_pin_credit_is_every_knob_type_not_only_model(self) -> None:
        """The owner's example is numeric; the rule is not numeric-only."""
        for name, values in (
            ("temperature", [0.0]),
            ("prompt_style", ["plain"]),
            ("reflect", [False]),
            ("model", ["provider/only"]),
            ("retrieval_depth", [5]),
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    MODULE.knob_variation(name, values).quality,
                    MODULE.PINNED_KNOB_CREDIT,
                )

    def test_a_collapsed_sweep_is_not_a_pin_and_still_scores_zero(self) -> None:
        """Two values inside the noise floor is a sweep that does not exist.

        The author did not pin this knob - they tried to sweep it. Paying the
        pin credit here would pay for the mistake the noise floor names.
        """
        knob = MODULE.knob_variation("temperature", [0.1, 0.115])
        self.assertEqual(knob.distinct_values, 2)
        self.assertEqual(knob.effective_values, 1)
        self.assertEqual(knob.quality, 0.0)

    def test_a_closed_categorical_knob_scores_full_breadth_at_two_values(self) -> None:
        """Two values is the whole comparison, not half of one.

        `(distinct - 1) / 2` scored two at 50%, which asserts a third value
        exists and would be better - an assertion nothing here can make, since
        a categorical knob's value list is not knowable (`thinking_shape` may
        gain tree-of-thought and graph-of-thought). So two or more is full.
        """
        two = MODULE.knob_variation("prompt_policy", ["direct", "structured"])
        three = MODULE.knob_variation(
            "prompt_policy", ["direct", "structured", "criteria_first"]
        )
        self.assertEqual(two.quality, 1.0)
        self.assertEqual(three.quality, 1.0)
        for values in ([False, True], ["direct", "chain_of_thought"]):
            with self.subTest(values=values):
                self.assertEqual(
                    MODULE.knob_variation("thinking_shape", values).quality, 1.0
                )


    def test_model_keeps_a_ladder_because_more_models_really_is_better(self) -> None:
        """The one categorical knob where the value count means something.

        Three rungs - cheap, mid, strong - are what it takes to see the
        cost-for-quality trade the middle one makes. Two can only say which of
        the two won.
        """
        ladder = {
            1: MODULE.PINNED_KNOB_CREDIT,
            2: 0.60,
            3: 1.0,
            4: 1.0,
        }
        for count, expected in ladder.items():
            with self.subTest(models=count):
                values = [f"provider/m{index}" for index in range(count)]
                self.assertEqual(
                    MODULE.knob_variation("model", values).quality, expected
                )
        # Every open categorical knob names a model, so all of them ladder.
        for name in MODULE.OPEN_CATEGORICAL_KNOBS:
            with self.subTest(name=name):
                self.assertEqual(MODULE.knob_variation(name, ["a", "b"]).quality, 0.60)

    def test_duplicate_values_do_not_inflate_breadth(self) -> None:
        knob = MODULE.knob_variation("prompt_style", ["direct", "direct", "direct"])
        self.assertEqual(knob.distinct_values, 1)
        self.assertEqual(knob.quality, MODULE.PINNED_KNOB_CREDIT)

    def test_an_unranged_numeric_knob_keeps_the_old_breadth_formula(self) -> None:
        """Full credit at two values is a CATEGORICAL rule, not a numeric one.

        For a number, "how many values exist" is not unknowable, it is
        unbounded - infinitely many sit between any two - so breadth is standing
        in for a span this scorer cannot compute, and paying it full marks would
        hand out the narrow-sweep credit the numeric path exists to withhold.
        """
        two = MODULE.knob_variation("retrieval_depth", [1, 10])
        three = MODULE.knob_variation("retrieval_depth", [1, 5, 10])
        self.assertEqual(two.quality, 0.5)
        self.assertEqual(three.quality, 1.0)

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
            (0, "NOT READY"),
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

    def test_the_documented_bands_match_the_thresholds(self) -> None:
        """The customer reads the ranges in prose; the code reads the tuple.

        `BAND_THRESHOLDS` states exclusive upper bounds and its last entry is a
        sentinel one past the top of the scale, which reads as "you need 101 to
        be excellent" to anyone who has not traced `band_for`. The glossary
        states the same bands as inclusive ranges for the user. Two statements
        of one fact is a thing that drifts, so the prose is derived from the
        tuple here rather than trusted - and a renumbering that forgets the
        glossary fails rather than shipping a card whose own guide misdescribes
        it.
        """
        expected: dict[str, tuple[int, int]] = {}
        low = 0
        for threshold, name in MODULE.BAND_THRESHOLDS:
            # The last entry's bound is a sentinel past the end of the scale;
            # a band cannot be documented as reaching further than 100.
            expected[name.casefold()] = (low, min(threshold - 1, 100))
            low = threshold
        self.assertEqual(expected["excellent"], (90, 100), "EXCELLENT is reachable")

        glossary = (
            ROOT / "skills" / "traigent-first-run" / "references" / "glossary.md"
        ).read_text(encoding="utf-8")
        documented = {
            name.strip().casefold(): (int(start), int(end))
            for name, start, end in re.findall(
                r"([A-Za-z][A-Za-z ]*?) \((\d+)-(\d+)\)", glossary
            )
        }
        for name, band_range in expected.items():
            with self.subTest(band=name):
                self.assertIn(
                    name,
                    documented,
                    "the glossary documents the bands and does not name this one",
                )
                self.assertEqual(documented[name], band_range)

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
        # Real condition ids, alphabetically reversed against their ceilings, so
        # this still proves ordering is by ceiling and not by name. Throwaway
        # slugs no longer construct: every cap must name a remedy, and a made-up
        # condition has none.
        caps = [
            MODULE.Cap("dataset-fully-synthetic", 65, "z"),
            MODULE.Cap("evaluator-invalid", 25, "a"),
        ]
        score = MODULE.aggregate(pillars, caps, [], dict(MODULE.DEFAULT_WEIGHTS))
        self.assertEqual(score.weighted_average, 100)
        self.assertEqual(score.overall, 25)
        self.assertEqual(score.status, "BLOCKED")
        self.assertEqual(
            [cap.condition for cap in score.caps],
            ["evaluator-invalid", "dataset-fully-synthetic"],
        )

    def test_a_lone_ceiling_above_the_average_still_does_not_bind(self) -> None:
        """ "Would limit to" has two causes, and the glossary named only one.

        It said a ceiling in the subjunctive is one that "only starts to matter
        once something lower is cleared", which describes a stricter cap. The
        other cause needs no second cap at all: `overall` is
        `min(weighted_average, min(ceilings))`, so a sole ceiling above the
        average is equally not the operative limit. README.md and the code
        already said both; this pins the mechanism the glossary must describe.
        """
        pillars = [
            MODULE.combine(name, [MODULE.SubScore("x", 5.0, 10.0, True, "")])
            for name in ("agent", "dataset", "evaluation")
        ]
        cap = MODULE.Cap("dataset-coarse-resolution", 89, "small set", blocks=False)
        score = MODULE.aggregate(pillars, [cap], [], dict(MODULE.DEFAULT_WEIGHTS))
        self.assertEqual(score.weighted_average, 50)
        self.assertEqual(score.overall, 50)
        self.assertEqual([c.condition for c in score.caps], [cap.condition])
        self.assertFalse(
            MODULE.binds(cap, score.overall),
            "the only ceiling in play is still not what holds the score down",
        )
        card = MODULE.render_card(score, unicode_ok=False, palette=MODULE.PLAIN)
        self.assertIn("WOULD LIMIT TO 89", card)

    def test_weighted_average_is_retained_so_a_cap_is_never_hidden(self) -> None:
        pillars = [
            MODULE.combine(name, [MODULE.SubScore("x", 10.0, 10.0, True, "")])
            for name in ("agent", "dataset", "evaluation")
        ]
        score = MODULE.aggregate(
            pillars,
            [MODULE.Cap("dataset-no-expected-outputs", 30, "r")],
            [],
            dict(MODULE.DEFAULT_WEIGHTS),
        )
        self.assertEqual(score.overall, 30)
        self.assertEqual(score.weighted_average, 100)


class DatasetScoringTests(unittest.TestCase):
    def test_absent_dataset_is_capped_and_blocked(self) -> None:
        pillar, caps = MODULE.score_dataset(MODULE.DatasetFacts(exists=False))
        self.assertEqual([cap.condition for cap in caps], ["dataset-absent"])
        self.assertEqual(pillar.score, 0)

    def test_a_supplied_but_unrecognised_dataset_is_not_called_absent(self) -> None:
        """A customer holding good rows must never be told to go and get data.

        `exists=False` used to carry two situations at once: no dataset reached
        the score, and a dataset reached it whose rows could not be read with
        the selected field names. Both raised `dataset-absent`, and the remedy
        is a property of the condition - so both recommended `get-data`, and a
        customer with three perfectly good labelled rows whose file says
        `question`/`answer` was told to collect data they already had.

        Rewording the sentence alone left that intact: the card said "a dataset
        was provided" while `recommended_action` still said `get-data` and the
        guide still routed the id into dataset creation. The state needs its own
        condition, which is what carries the remedy.

        The remedy is `read-dataset`, and that is the second half of the same
        correction. `repair-dataset` also keeps the customer's file - but it
        asserts the file is defective, and the run has no evidence for that: it
        read the file with one assumed shape, nothing matched, and every
        conclusion beyond "we did not recognise it" is a guess. See
        `test_a_dataset_with_other_field_names_scores_clean_once_it_is_mapped`
        in the adapter tests for what the same file scores once it is read
        correctly.
        """
        _, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=False,
                dataset_supplied=True,
                unreadable_rows=3,
                unreadable_detail="3/3 rows (100.0%) are unusable; line 1: "
                "missing selected input field 'input'",
            )
        )
        self.assertEqual(
            [cap.condition for cap in caps], ["dataset-shape-unrecognised"]
        )
        cap = caps[0]
        # The routing, not just the prose. This is the assertion the reworded
        # sentence could not make.
        self.assertEqual(cap.action_kind, "read-dataset")
        self.assertEqual(MODULE.recommended_action(caps), "read-dataset")
        self.assertNotEqual(cap.action_kind, "get-data")
        # Neither of the two instructions that assert something about the data.
        self.assertNotEqual(cap.action_kind, "repair-dataset")
        # Still blocks - nothing here is measurable yet - and still scores under
        # every state that has a readable row in it (30 for no expected
        # outputs, 35 for some rows unreadable), but above 20, "no data at all".
        self.assertTrue(cap.blocks)
        self.assertEqual(cap.ceiling, 25)
        reason = cap.reason
        self.assertIn("A dataset was provided", reason)
        # The old sentence claimed something about the project rather than
        # about this score's input; it must not come back.
        self.assertNotIn("No dataset is connected", reason)

    def test_the_reason_names_the_reading_and_never_convicts_the_data(self) -> None:
        """The sentence a customer reads on the opening card.

        This cap is computed before the assistant has opened the file, so the
        card can honestly report only that the run did not recognise what it
        read. "None of its rows could be read, so nothing can be measured" is a
        verdict on the customer's data, and on the files that actually produce
        this state - a `question`/`answer` schema, a nested one, a CSV, a JSON
        array, YAML - it is false. Two obligations follow, and both are asserted
        here because prose is where this defect lives.
        """
        _, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=False,
                dataset_supplied=True,
                unreadable_rows=12,
                unreadable_detail="12/12 rows (100.0%) are unusable; line 1 "
                "(+11 more): missing selected input field 'input'",
            )
        )
        reason = caps[0].reason
        # It says what the run could not do, not what the data is.
        self.assertIn("matched the shape this score read it with", reason)
        self.assertIn("not a defect in the data", reason)
        # The old verdict, in the two forms it was written in.
        self.assertNotIn("none of its rows could be read", reason.casefold())
        self.assertNotIn("nothing can be measured", reason)
        # And it names the next step, because the card fires at the opening
        # gate and the state it describes can end one look at the file later.
        self.assertIn("can clear on the next step", reason)

    def test_the_cause_is_preflights_to_state_and_is_never_invented(self) -> None:
        """The reason forwards the cause; it does not guess one and close it.

        A 120-row dataset scored with one field path selected for both the input
        and the expected answer is unreadable for a third reason preflight
        already names. The sentence that asserted two causes and told the reader
        to "check both before concluding the data is missing" was false for it
        twice over: neither named cause applied, and the closure said there was
        no third.
        """
        detail = (
            "120/120 rows (100.0%) are unusable; line 1: input and "
            "expected-output field paths must be different"
        )
        _, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=False,
                dataset_supplied=True,
                unreadable_rows=120,
                unreadable_detail=detail,
            )
        )
        reason = caps[0].reason
        self.assertIn(detail, reason)
        self.assertNotIn("Check both", reason)

    def test_no_reported_cause_means_no_cause_is_named(self) -> None:
        """Nothing to forward is not a licence to fall back on a guess."""
        _, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(exists=False, dataset_supplied=True, unreadable_rows=4)
        )
        reason = caps[0].reason
        self.assertEqual(caps[0].condition, "dataset-shape-unrecognised")
        for invented in ("malformed lines", "expected-answer field", "Check both"):
            with self.subTest(invented=invented):
                self.assertNotIn(invented, reason)

    def test_a_supplied_dataset_with_no_row_count_forwards_what_was_reported(
        self,
    ) -> None:
        """No rows to count at all is `dataset-absent`, and still says why.

        A path that does not exist and a file that exists and holds nothing both
        arrive here with no row count. They are different problems with
        different repairs, and preflight's `dataset-shape` FAIL is the only
        witness that separates them - so it is forwarded rather than flattened
        into one sentence for both.
        """
        _, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=False,
                dataset_supplied=True,
                unreadable_detail="/tmp/nope.jsonl does not exist",
            )
        )
        self.assertEqual([cap.condition for cap in caps], ["dataset-absent"])
        self.assertIn("/tmp/nope.jsonl does not exist", caps[0].reason)
        self.assertIn("A dataset was provided to this score", caps[0].reason)

    def test_a_dataset_that_never_reached_the_score_says_so(self) -> None:
        """The other half: absence of input is not evidence of absence of data."""
        _, caps = MODULE.score_dataset(MODULE.DatasetFacts(exists=False))
        self.assertEqual([cap.condition for cap in caps], ["dataset-absent"])
        self.assertIn("provided to this score", caps[0].reason)
        self.assertEqual(caps[0].action_kind, "get-data")

    def test_an_empty_file_does_not_read_like_a_broken_one(self) -> None:
        """The two sentences must not be interchangeable, because the fixes are not.

        `dataset-absent` on a supplied path routes to `get-data` and
        `dataset-shape-unrecognised` routes to `read-dataset` - opposite
        instructions - and the card used to state them as "nothing could be
        read from it" and "none of its rows could be read". A reader picking a
        branch off the prose cannot tell those apart, which is the same defect
        as the id that carried the wrong remedy, moved into the sentence.
        """
        _, absent = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=False,
                dataset_supplied=True,
                unreadable_detail="dataset has no usable rows",
            )
        )
        _, unrecognised = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=False,
                dataset_supplied=True,
                unreadable_rows=6,
                unreadable_detail="6/6 rows (100.0%) are unusable; line 1: x",
            )
        )
        self.assertEqual(absent[0].action_kind, "get-data")
        self.assertEqual(unrecognised[0].action_kind, "read-dataset")
        # The prose has to carry the difference the action makes. `get-data` is
        # the right instruction only because there is nothing here to open, so
        # the sentence says exactly that - and the other one must not, because
        # opening the file is the whole of what it asks for.
        self.assertIn("holds no rows at all", absent[0].reason)
        self.assertIn("nothing to repair", absent[0].reason)
        self.assertNotIn("nothing to repair", unrecognised[0].reason)
        self.assertIn("open the file", unrecognised[0].reason)
        self.assertNotIn("open the file", absent[0].reason)
        # Both still name what was given rather than what the customer has.
        self.assertIn("A dataset was provided to this score", absent[0].reason)

    def test_logs_without_expected_outputs_are_capped_not_merely_low(self) -> None:
        """500 unlabelled rows must not score as WORKABLE - nothing can be scored."""
        _, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(exists=True, rows=500, labelled_rows=0)
        )
        self.assertIn("dataset-no-expected-outputs", [cap.condition for cap in caps])

    def test_unlabelled_rows_are_not_also_reported_as_missing_rows(self) -> None:
        """One fact, one cap, one remedy - and it must be the repairable one.

        With rows present and none labelled, the scoreable count is zero, so
        the power ceiling fired too: `dataset-below-measurable-size`, whose
        remedy is `get-data`. The card then carried two FIX lines for one fact
        and the second told a customer holding 500 usable inputs to go and
        collect examples - the very instruction `dataset-shape-unrecognised` was added
        to stop giving.

        `label-data` is the remedy that repairs what they already have, and the
        labels cap already carries it.

        `collected_rows` is stated because #165 scores a corpus that declares
        no provenance as generated, and would raise a second cap here about a
        different fact. This test is about two caps for ONE fact, so the other
        fact is declared rather than left silent.
        """
        _, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True, rows=500, labelled_rows=0, collected_rows=500
            )
        )
        self.assertEqual(
            [cap.condition for cap in caps], ["dataset-no-expected-outputs"]
        )
        self.assertEqual(MODULE.recommended_action(caps), "label-data")
        self.assertNotIn("get-data", [cap.action_kind for cap in caps])

    def test_suppressing_that_duplicate_moves_no_number(self) -> None:
        """The removed ceiling was never the operative one, so nothing changes.

        30 sits below 74, so the labels cap set the score with or without it.
        Asserted rather than argued, because "this changes no number" is the
        claim that makes the suppression safe.
        """
        pillar, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(exists=True, rows=500, labelled_rows=0)
        )
        with_duplicate = [*caps, MODULE.power_ceiling(0)]
        weights = dict(MODULE.DEFAULT_WEIGHTS)
        kept = MODULE.aggregate([pillar], caps, [], weights)
        restored = MODULE.aggregate([pillar], with_duplicate, [], weights)
        self.assertEqual(kept.overall, restored.overall)
        self.assertEqual(kept.status, restored.status)
        self.assertEqual(kept.recommended_action, restored.recommended_action)

    def test_a_zero_from_any_other_source_still_raises_the_ceiling(self) -> None:
        """Only the zero the labels cap owns is suppressed, not every zero.

        The zero is on the TUNING side. This test used to put it on the
        holdout, which #161 then deliberately took out of the resolution
        calculation - the walkthrough reserves ten held-out rows, so counting
        them made EXCELLENT unreachable for every project that declared a
        split. That removed the fixture's zero without removing the rule the
        fixture is about, so the zero moves to a split half that still sets
        the comparison's resolution.
        """
        _, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True,
                rows=60,
                labelled_rows=60,
                tuning_rows=30,
                holdout_rows=30,
                tuning_labelled_rows=0,
                holdout_labelled_rows=30,
            )
        )
        self.assertIn("dataset-below-measurable-size", [cap.condition for cap in caps])

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

    def test_power_is_driven_by_the_tuning_split_not_total_rows(self) -> None:
        """Not total rows, and not the holdout either.

        This asserted the opposite - that a 96/4 split scored BELOW a 20/20
        one - because the holdout used to bound resolution. It does not: 96
        rows to compare on is a sharper comparison than 20, and reserving four
        rows to check the winner does not make it blunter. What still holds is
        that total rows are not the measure, which is what the second pair
        pins.
        """
    def _diversity(self, **facts) -> object:
        pillar, _caps = MODULE.score_dataset(
            MODULE.DatasetFacts(exists=True, rows=200, labelled_rows=200, **facts)
        )
        return next(sub for sub in pillar.subscores if sub.name == "diversity")

    def test_a_skipped_check_is_never_scored_as_a_passed_check(self) -> None:
        """The rule, over every diversity check and every not-run spelling.

        A check that did not run used to keep its full points and the sentence
        "no repeated questions, and no single answer used by most rows" - a
        clean result nobody established. Parameterised over all three checks so
        a fourth cannot be added with the old behaviour, and over SKIP as well
        as an absent record because both mean the same thing.
        """
        clean = {
            "duplicate_status": "PASS",
            "near_duplicate_status": "PASS",
            "answer_dominance_status": "PASS",
        }
        full = self._diversity(**clean)
        self.assertTrue(full.measured)
        self.assertEqual(full.value, 20.0)

        for check in MODULE.DIVERSITY_CHECKS:
            for not_run in ("SKIP", None):
                with self.subTest(check=check.certifier, status=not_run):
                    sub = self._diversity(**{**clean, check.certifier: not_run})
                    self.assertFalse(
                        sub.measured,
                        f"{check.certifier}={not_run!r} still reads as a "
                        f"measured, clean result: {sub.evidence}",
                    )
                    self.assertNotIn("no repeated questions", sub.evidence)
                    self.assertIn(check.looking_for_label, sub.evidence)

    def test_one_duplicated_row_is_one_deduction_not_two(self) -> None:
        """The exact and near checks describe one defect, so they cost once.

        Identical token sets have Jaccard similarity 1.0, so a single copied
        row fires `dataset-duplicates` AND `dataset-near-duplicates`. Scoring
        both took 14 of the 20 diversity points for one duplicated row
        (traigent-first-run#158). The owner's decision is one deduction of 7,
        taken on the near-duplicate check, which already covers 100%.
        """
        clean = {
            "duplicate_status": "PASS",
            "near_duplicate_status": "PASS",
            "answer_dominance_status": "PASS",
        }
        both = self._diversity(
            **{**clean, "duplicate_status": "WARN", "near_duplicate_status": "WARN"}
        )
        self.assertTrue(both.measured)
        self.assertEqual(both.value, 13.0, both.evidence)
        self.assertEqual(
            both.value,
            self._diversity(**{**clean, "near_duplicate_status": "WARN"}).value,
        )
        # Named once, and named with the threshold the customer is being
        # judged against - not as two findings.
        self.assertEqual(both.evidence.count(";"), 0, both.evidence)
        self.assertIn(f"{MODULE.NEAR_DUPLICATE_PERCENT}%", both.evidence)

    def test_the_exact_check_can_still_report_what_the_near_scan_missed(self) -> None:
        """Why the exact check is kept as a detector rather than deleted.

        It is a hash bucket - O(n), always complete - while the near-duplicate
        join is bounded and emits SKIP when it exhausts its budget. On that
        dataset the exact check is the only thing that can still say
        "there is repetition", so it feeds the same single deduction.
        """
        clean = {
            "duplicate_status": "PASS",
            "near_duplicate_status": "PASS",
            "answer_dominance_status": "PASS",
        }
        found = self._diversity(
            **{**clean, "duplicate_status": "WARN", "near_duplicate_status": "SKIP"}
        )
        self.assertTrue(found.measured, found.evidence)
        self.assertEqual(found.value, 13.0, found.evidence)

    def test_no_exact_duplicates_cannot_clear_the_similarity_question(self) -> None:
        """A detector may raise a finding; only the certifier may clear one.

        "No byte-identical rows" is not "no rows 90% alike", so an exact PASS
        beside an unfinished near scan leaves the question unasked - which is
        the same rule the class above pins, applied to the check that was
        demoted rather than deleted.
        """
        sub = self._diversity(
            duplicate_status="PASS",
            near_duplicate_status="SKIP",
            answer_dominance_status="PASS",
        )
        self.assertFalse(sub.measured, sub.evidence)
        self.assertIn(f"{MODULE.NEAR_DUPLICATE_PERCENT}%", sub.evidence)

    def test_an_unrun_check_cannot_raise_the_pillar_above_a_run_one(self) -> None:
        """Unmeasured must never pay better than measured-and-clean.

        `combine` renormalizes over the measured sub-scores, so dropping one
        can RAISE a pillar. This pins the direction: a dataset whose duplicate
        check did not run can never score above the identical dataset whose
        check ran and found nothing.
        """
        measured = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True,
                rows=200,
                labelled_rows=200,
                tuning_rows=100,
                holdout_rows=100,
                duplicate_status="PASS",
                near_duplicate_status="PASS",
                answer_dominance_status="PASS",
            )
        )[0]
        unmeasured = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True,
                rows=200,
                labelled_rows=200,
                tuning_rows=100,
                holdout_rows=100,
                duplicate_status="PASS",
                near_duplicate_status="SKIP",
                answer_dominance_status="PASS",
            )
        )[0]
        self.assertLessEqual(unmeasured.score, measured.score)
        self.assertLess(unmeasured.confidence, measured.confidence)

    def test_total_answer_dominance_is_measured_not_unchecked(self) -> None:
        """The sibling of the check above, at the source rather than the score.

        `answer_dominance_status` is `None` when preflight raised no dominance
        record, and preflight raised none for the one input that is maximum
        dominance: at 100% identical expected outputs it took the degenerate
        branch, emitted `dataset-outputs` WARN, and never reached the arm where
        `dataset-ceiling-risk` lives. The witness readiness reads for "the
        spread was examined" is a PASS on `dataset-outputs`, so total dominance
        arrived here as absence.

        Combined with the renormalization this class already pins, that
        inverted the score: the dataset whose every answer is identical
        outscored the one where 90% are. `tests/test_preflight.py` holds the
        emit; this holds the consequence, so neither half can be removed
        believing the other still covers it.
        """

        def facts(dominance):
            return MODULE.DatasetFacts(
                exists=True,
                rows=200,
                labelled_rows=200,
                tuning_rows=100,
                holdout_rows=100,
                duplicate_status="PASS",
                near_duplicate_status="PASS",
                answer_dominance_status=dominance,
            )

        dominant = MODULE.score_dataset(facts("WARN"))[0]
        unchecked = MODULE.score_dataset(facts(None))[0]
        sub = self._diversity(
            duplicate_status="PASS",
            near_duplicate_status="PASS",
            answer_dominance_status="WARN",
        )
        self.assertTrue(sub.measured)
        self.assertLess(sub.value, 20.0)
        self.assertLessEqual(dominant.score, unchecked.score)

    def test_the_adapter_reports_the_dominance_status_preflight_emitted(self) -> None:
        """The adapter translates preflight; it does not re-rank it.

        `_answer_dominance_status` returned the literal "WARN" whenever a
        `dataset-ceiling-risk` record was present, discarding the status the
        record carried. Every sibling dataset check already raises FAIL rather
        than WARN on a synthetic dataset, so the first time dominance is ranked
        that way the scorer would have been handed a warning about a failure -
        a downgrade invented by the reader of a status, which is the defect
        that reading SKIP as PASS already cost this package once.
        """
        for status in ("WARN", "FAIL"):
            with self.subTest(status=status):
                facts = MODULE.dataset_facts_from_preflight(
                    [
                        {
                            "check": "dataset-provenance",
                            "status": "PASS",
                            "metrics": {
                                "rows": 40,
                                "labelled_rows": 40,
                                # Emitted together by preflight.py, and
                                # required since #161 - an absent count is
                                # refused rather than read as zero.
                                "collected_rows": 40,
                                "synthesised_rows": 0,
                                "undeclared_rows": 0,
                                "generated_answer_rows": 0,
                                "answerable_rows": 40,
                            },
                        },
                        {"check": "dataset-outputs", "status": "PASS", "metrics": {}},
                        {
                            "check": "dataset-ceiling-risk",
                            "status": status,
                            "metrics": {},
                        },
                        # Both emitted for every dataset preflight can read,
                        # and both now required: their absence used to be
                        # scored as the clean answer.
                        {"check": "dataset-split", "status": "WARN", "metrics": {}},
                        {"check": "dataset-ids", "status": "PASS", "metrics": {}},
                    ]
                )
                self.assertEqual(facts.answer_dominance_status, status)

    def test_a_real_finding_survives_a_skip_beside_it(self) -> None:
        """A skipped sibling must not erase a check that did find something.

        The tempting fix - mark the whole sub-score unmeasured whenever
        anything did not run - would delete the finding AND raise the pillar,
        because unmeasured sub-scores are renormalized out.
        """
        sub = self._diversity(
            duplicate_status="FAIL",
            near_duplicate_status="FAIL",
            answer_dominance_status="SKIP",
        )
        self.assertTrue(sub.measured)
        self.assertEqual(sub.value, 13.0)
        self.assertIn(f"{MODULE.NEAR_DUPLICATE_PERCENT}% similar", sub.evidence)
        self.assertIn("not checked", sub.evidence)

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
        self.assertGreater(wide_power, balanced_power)

        # 100 rows both times, and the one that tunes on fewer scores lower.
        thin_tuning = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True, rows=100, labelled_rows=100, tuning_rows=20, holdout_rows=80
            )
        )[0]
        thin_power = next(s.value for s in thin_tuning.subscores if s.name == "power")
        self.assertLess(thin_power, wide_power)

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

    def test_undeclared_provenance_is_scored_as_generated(self) -> None:
        """Silence is read as "generated", and says so rather than passing.

        This is the pre-count fallback - a preflight JSON with no row counts,
        which is what an older payload looks like. It reaches the same verdict
        as the counted path, because the rule is about what silence means and
        not about which payload carried it.
        """
        pillar, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True, rows=50, labelled_rows=50, sources=("unknown",)
            )
        )
        provenance = next(s for s in pillar.subscores if s.name == "provenance")
        self.assertEqual(provenance.value, MODULE.SYNTHESISED_ROW_POINTS)
        cap = next(c for c in caps if c.condition == "dataset-undeclared-provenance")
        self.assertEqual(cap.ceiling, MODULE.FULLY_SYNTHETIC_CEILING)
        # The remedy is the whole point of a separate condition: a customer may
        # already hold real data and simply never have labelled it.
        self.assertEqual(cap.action_kind, "declare-data-provenance")

    def test_an_unobserved_corpus_raises_one_ceiling_and_not_two(self) -> None:
        """Which ceiling governs an unobserved corpus with a model's answer key.

        The 65 does, and the answer-key 75 is not raised at all: its premise is
        that the questions are still real, which is exactly what a corpus where
        no row was observed cannot say. It used to be refused only for the
        DECLARED version of that state (`synthesised_rows != counted`), so the
        undeclared one raised both and the card listed two ceilings for one
        fact, the higher of them resting on a premise the lower one denies.
        """
        _, _, caps = MODULE.score_provenance(
            MODULE.DatasetFacts(
                exists=True,
                rows=30,
                labelled_rows=30,
                undeclared_rows=30,
                answerable_rows=30,
                generated_answer_rows=30,
            )
        )
        self.assertEqual(
            [(cap.condition, cap.ceiling) for cap in caps],
            [("dataset-undeclared-provenance", MODULE.FULLY_SYNTHETIC_CEILING)],
        )
        # The ceiling is still raised where its premise holds: observed
        # questions whose every answer a model wrote.
        _, _, observed = MODULE.score_provenance(
            MODULE.DatasetFacts(
                exists=True,
                rows=30,
                labelled_rows=30,
                collected_rows=30,
                answerable_rows=30,
                generated_answer_rows=30,
            )
        )
        self.assertEqual(
            [(cap.condition, cap.ceiling) for cap in observed],
            [("dataset-generated-answer-key", MODULE.GENERATED_ANSWER_KEY_CEILING)],
        )

    def test_power_uses_labelled_rows_when_no_split_is_declared(self) -> None:
        """90 of the 100 rows cannot be scored, so they buy no precision."""
        pillar, _ = MODULE.score_dataset(
            MODULE.DatasetFacts(exists=True, rows=100, labelled_rows=10)
        )
        power = next(s for s in pillar.subscores if s.name == "power")
        self.assertEqual(power.value, 9.6)
        self.assertIn("100 rows, 10 scoreable", power.evidence)
        self.assertIn("small comparison set", power.evidence)
        for unsupported in ("+/-", "detect", "resolve"):
            self.assertNotIn(unsupported, power.evidence.casefold())

    def test_power_is_the_tuning_split_s_scoreable_size_and_not_the_holdout_s(
        self,
    ) -> None:
        """Resolution is a property of the comparison, and the holdout is not one.

        This used to take the minimum across BOTH splits, so the held-back set
        bounded a number it takes no part in producing. The search compares
        configurations on the tuning rows; the holdout checks the one winner
        those rows already picked, once, and it is deliberately small. With the
        walkthrough's ten held-out rows that minimum was ten for every project
        that used it, `power_ceiling(10)` fired every time, and EXCELLENT was
        structurally unreachable - a perfect 990/10 project scored 89 with a
        permanent `dataset-coarse-resolution` cap and no action that could
        clear it.
        """
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
        # 60 tuning rows of which 20 are scoreable. The holdout's 40 do not
        # enter it in either direction.
        self.assertEqual(power.value, 12.0)
        self.assertIn("20 scoreable", power.evidence)

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
        # A holdout with nothing scoreable in it used to collapse power to
        # zero. It no longer does, because it never described the comparison's
        # resolution - 50 tuning rows are 50 tuning rows. It IS a real problem
        # (nothing can check the winner), so it is stated on the card rather
        # than expressed as a number about a different question.
        unscoreable_holdout = next(
            s for s in one_sided.subscores if s.name == "power"
        )
        self.assertEqual(unscoreable_holdout.value, 22.0)
        self.assertIn(
            "none of the held-back rows can be scored", unscoreable_holdout.evidence
        )
        self.assertIn("50 examples", unscoreable_holdout.evidence)

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
            "no tuning set and held-out set, so the result would be measured on the same rows the search used; 100 examples - substantial "
            "comparison set",
        )

    def test_tuning_only_dataset_names_its_missing_held_out_set(self) -> None:
        pillar, _ = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True,
                rows=18,
                labelled_rows=18,
                tuning_rows=18,
                tuning_labelled_rows=18,
            )
        )
        power = next(
            subscore for subscore in pillar.subscores if subscore.name == "power"
        )
        self.assertIn("18 tuning rows and no held-out set", power.evidence)
        self.assertNotIn("no tuning set", power.evidence)

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

    # traigent-first-run#133: four states a first run can find an evaluator
    # in - absent, import-invalid (unparseable), constant-pass (parses and
    # calibrates as broken), and healthy - must each read back as their own
    # state, not two of them collapsing into the same cap.

    def test_absent_evaluator_routes_to_create_or_select(self) -> None:
        """`evaluator-absent` remedies as creating/selecting one, not repair."""
        _, caps = MODULE.score_evaluation(MODULE.EvaluationFacts(present=False))
        cap = next(c for c in caps if c.condition == "evaluator-absent")
        self.assertEqual(cap.action_kind, "connect-evaluator")

    def test_import_invalid_evaluator_is_present_but_unresolved(self) -> None:
        """A file that does not even parse is present, not absent.

        `evaluator_shape_from_preflight` reports `parses=False` only from
        preflight's static `ast.parse`-only check - this never imports or
        runs the broken file to learn that it is broken.
        """
        facts = MODULE.EvaluationFacts(present=True, method=None, parses=False)
        pillar, caps = MODULE.score_evaluation(facts)
        conditions = [cap.condition for cap in caps]
        self.assertIn("evaluator-unresolved", conditions)
        self.assertNotIn("evaluator-absent", conditions)
        cap = next(c for c in caps if c.condition == "evaluator-unresolved")
        self.assertEqual(cap.action_kind, "repair-evaluator")
        self.assertIn("does not parse", cap.reason)
        calibration = next(s for s in pillar.subscores if s.name == "calibration")
        self.assertIn("does not parse", calibration.evidence)

    def test_unresolved_evaluator_with_unknown_shape_is_also_present_not_absent(
        self,
    ) -> None:
        """A file that parses but earns no declared method is still unresolved.

        This is the case that opened #133: a constant-pass scorer imports
        cleanly and has a plausible shape, so the opening gate correctly
        refuses to declare a method for it (that determination needs
        execution) without also being unable to tell it apart from no
        evaluator at all.
        """
        facts = MODULE.EvaluationFacts(present=True, method=None, parses=True)
        _, caps = MODULE.score_evaluation(facts)
        conditions = [cap.condition for cap in caps]
        self.assertIn("evaluator-unresolved", conditions)
        self.assertNotIn("evaluator-absent", conditions)
        cap = next(c for c in caps if c.condition == "evaluator-unresolved")
        self.assertEqual(cap.action_kind, "repair-evaluator")
        self.assertNotIn("does not parse", cap.reason)

    def test_constant_pass_caught_by_calibration_is_evaluator_invalid_not_unresolved(
        self,
    ) -> None:
        """Behavior-level invalidity keeps its own, already-existing condition.

        A constant-pass evaluator that calibration actually ran against and
        caught (`non_constant: False`) is `evaluator-invalid`, distinct from
        `evaluator-unresolved` (never calibrated at all) - both route to the
        same inspect/repair/replace remedy, but the readiness record keeps
        the two claims separate: "connected, never resolved" is not "ran and
        found broken".
        """
        facts = MODULE.EvaluationFacts(
            present=True,
            method="exact",
            parses=True,
            calibration_present=True,
            calibration_supplied=True,
            checks=({"good_passes": True, "bad_fails": True, "non_constant": False},),
        )
        _, caps = MODULE.score_evaluation(facts)
        conditions = [cap.condition for cap in caps]
        self.assertIn("evaluator-invalid", conditions)
        self.assertNotIn("evaluator-unresolved", conditions)
        self.assertNotIn("evaluator-absent", conditions)
        invalid_cap = next(c for c in caps if c.condition == "evaluator-invalid")
        self.assertEqual(invalid_cap.action_kind, "repair-evaluator")

    def test_healthy_evaluator_raises_no_evaluator_cap(self) -> None:
        """A real, calibrated, non-constant evaluator is not capped at all."""
        facts = MODULE.EvaluationFacts(
            present=True,
            method="exact",
            task_kind="structured",
            parses=True,
            calibration_present=True,
            calibration_supplied=True,
            checks=(
                {"good_passes": True, "bad_fails": True, "non_constant": True},
                {"good_passes": True, "bad_fails": True, "non_constant": True},
            ),
        )
        _, caps = MODULE.score_evaluation(facts)
        evaluator_conditions = {
            "evaluator-absent",
            "evaluator-unresolved",
            "evaluator-invalid",
        }
        self.assertFalse(evaluator_conditions & {cap.condition for cap in caps})

    def test_a_timed_out_calibration_keeps_its_own_cap_even_without_a_method(
        self,
    ) -> None:
        """Calibration having been engaged excludes the unresolved branch.

        A run that supplied a payload and timed out already has something to
        say - `evaluator-timeout` - and must not be relabelled
        `evaluator-unresolved` merely because no method happened to be
        declared alongside it.
        """
        facts = MODULE.evaluation_facts_from_calibration(
            {"timed_out": True, "cases": [], "passed": False}
        )
        _, caps = MODULE.score_evaluation(facts)
        conditions = [cap.condition for cap in caps]
        self.assertIn("evaluator-timeout", conditions)
        self.assertNotIn("evaluator-unresolved", conditions)

    def test_the_timeout_witness_alone_excludes_the_unresolved_branch(self) -> None:
        """Isolate `timed_out`, which the payload-driven test above cannot.

        Any non-None payload also sets `calibration_supplied`, so that test
        would still pass if `or facts.timed_out` were dropped from the guard
        - it never exercises that term on its own. Building the facts
        directly is the only way to drive the timeout witness with every
        other witness false.
        """
        facts = MODULE.EvaluationFacts(
            present=True,
            method=None,
            timed_out=True,
            calibration_present=False,
            calibration_supplied=False,
            checks=(),
        )
        _, caps = MODULE.score_evaluation(facts)
        conditions = [cap.condition for cap in caps]
        self.assertIn("evaluator-timeout", conditions)
        self.assertNotIn("evaluator-unresolved", conditions)

    def test_evaluator_present_flows_from_preflight_shape_without_a_method(
        self,
    ) -> None:
        """The adapter, not just the dataclass, derives presence from preflight.

        `evaluation_facts_from_calibration` must read `evaluator_present`/
        `evaluator_parses` the same way `--evaluator-method` already flows
        through it, so a file preflight found - but this run could not
        honestly name a method for - is not silently scored as absent.
        """
        facts = MODULE.evaluation_facts_from_calibration(
            None, evaluator_present=True, evaluator_parses=False
        )
        self.assertTrue(facts.present)
        self.assertIsNone(facts.method)
        self.assertFalse(facts.parses)
        _, caps = MODULE.score_evaluation(facts)
        self.assertIn("evaluator-unresolved", [cap.condition for cap in caps])

    def test_evaluator_shape_from_preflight_reads_the_static_check(self) -> None:
        records = [
            {
                "check": "evaluator-shape",
                "status": "PASS",
                "metrics": {"exists": True, "parses": True},
            }
        ]
        self.assertEqual(MODULE.evaluator_shape_from_preflight(records), (True, True))
        self.assertEqual(MODULE.evaluator_shape_from_preflight([]), (False, None))

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


# The document the walkthrough's generated wrapper writes: the enhanced space,
# with the template's placeholder model ids. Kept here so the consumer contract
# is pinned to the shape the producer actually emits. There is no longer a
# placeholder value to substitute first - the four behaviour knobs are binary
# and temperature is pinned, so the space is fixed before either run.
WALKTHROUGH_CONFIG_SPACE = {
    "knobs": {
        "model": ["provider/current", "provider/alternative", "provider/strong"],
        "prompt_style": ["plain", "structured"],
        "pre_action_reflect": [False, True],
        "thinking_shape": ["direct", "chain_of_thought"],
        "reflect": [False, True],
        "temperature": [0.0],
    },
    "max_trials": 12,
    "wired": [
        "model",
        "temperature",
        "prompt_style",
        "pre_action_reflect",
        "thinking_shape",
        "reflect",
    ],
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
    def test_a_seed_only_space_is_capped_for_the_reason_it_actually_has(
        self,
    ) -> None:
        """The cap fires correctly; the sentence beside it was false.

        `{"seed": [1, 2, 3, 4, 5]}` wired has one setting carrying five values,
        and the card said "every setting has only one value to try" while the
        line two rows up printed "1 combinations x 5 repeats = 5 runs" from the
        same document. Both numbers cannot be right. `seed` is excluded from
        scoring on purpose - sweeping it measures run-to-run variance, not
        configuration quality - so the honest reason names that exclusion, and
        what counts is deliberately unchanged: the cap still fires, still at 45.
        """
        document = {"knobs": {"seed": [1, 2, 3, 4, 5]}, "wired": ["seed"]}
        pillar, caps, _ = MODULE.score_agent(
            MODULE.agent_facts_from_config_space(document)
        )
        self.assertEqual([cap.condition for cap in caps], ["agent-no-varying-knobs"])
        self.assertEqual([cap.ceiling for cap in caps], [45])
        reason = caps[0].reason
        self.assertIn("seed", reason)
        self.assertIn("run-to-run variance", reason)
        self.assertNotIn("only one value", reason)

        # The count beside it named a denominator the document contradicts:
        # "0 of 0 wired knobs" against a `wired` list holding one name.
        # #189 replaced `knob-count` with `search-space`; the guarantee that
        # the excluded knob is NAMED beside the count moved with it.
        space = next(sub for sub in pillar.subscores if sub.name == "search-space")
        self.assertIn("seed", space.evidence)

    def test_an_excluded_knob_beside_real_ones_keeps_the_ordinary_reason(
        self,
    ) -> None:
        """Only the all-excluded case changes; the ordinary one must not.

        A space whose scoreable knobs each carry one value really does make
        every configuration identical, and that sentence stays.
        """
        document = {
            "knobs": {"seed": [1, 2], "model": ["a"]},
            "wired": ["seed", "model"],
        }
        _, caps, _ = MODULE.score_agent(MODULE.agent_facts_from_config_space(document))
        self.assertEqual([cap.condition for cap in caps], ["agent-no-varying-knobs"])
        self.assertIn("only one value to try", caps[0].reason)

    def test_wired_varying_knobs_clear_the_no_varying_cap(self) -> None:
        """The walkthrough's own space must not read as "nothing to search".

        `agent-no-varying-knobs` holds the whole run to 45 no matter how good
        the dataset and evaluator are, so this is the cap the config-space
        document exists to clear.
        """
        facts = MODULE.agent_facts_from_config_space(WALKTHROUGH_CONFIG_SPACE)
        pillar, caps, _ = MODULE.score_agent(facts)
        self.assertEqual([cap.condition for cap in caps], [])
        # Full marks, and the number is the guide's own recommended shape
        # scoring as such: 48 distinct configurations against a 12-trial
        # budget, so the run compares twelve of them - `SEARCH_SPACE_FULL`,
        # which is what this guide's own baseline sweep enumerates - and 48 is
        # four times the budget rather than twenty.
        #
        # It was 93 while the pillar also averaged a per-knob quality blend,
        # where the shortfall was the deliberately pinned `temperature`. A
        # space losing points for obeying the guide's own instruction to pin
        # temperature is the shape that sub-score kept producing.
        self.assertEqual(pillar.score, 100)
        self.assertEqual(pillar.confidence, 1.0)

    def test_the_reasoning_branch_is_the_same_document(self) -> None:
        """There is no longer a second document for a reasoning strong tier.

        This used to pin a DIFFERENT score, because temperature was pinned only
        in that branch: the ordinary space was 54 configurations and the
        reasoning one 18, and only this test recorded the second number
        anywhere. Temperature is now pinned in both, so the branch produces a
        byte-identical document and the same score. Asserted rather than
        deleted, because "the two branches agree" is the claim that replaced
        it.
        """
        reasoning = dict(
            WALKTHROUGH_CONFIG_SPACE,
            knobs=dict(WALKTHROUGH_CONFIG_SPACE["knobs"], temperature=[0.0]),
        )
        self.assertEqual(reasoning, WALKTHROUGH_CONFIG_SPACE)
        pillar, caps, _ = MODULE.score_agent(
            MODULE.agent_facts_from_config_space(reasoning)
        )
        self.assertEqual([cap.condition for cap in caps], [])
        self.assertEqual(pillar.score, 100)

    # REMOVED ON THE MERGE, not lost. #157 added
    # `test_the_two_spellings_refusal_names_both_written_spellings` to pin the
    # message produced when two alias spellings of one knob are COLLAPSED onto
    # one dimension. #191 deleted that collapsing outright: a document that
    # declares a synonym is now refused (exit 2) rather than quietly merged, so
    # `canonical_alias_names` and `_collapse_alias_spellings` no longer exist
    # and there is no collapse left to name both spellings of. The concern -
    # that the refusal names the spelling the author actually wrote - is
    # covered by #191's own tests above, which assert `'prompt_policy'` and
    # `(did you mean 'prompt_style'?)` in the refusal. Nothing here is a
    # relaxation; the behaviour under test was removed on purpose.

    def test_config_space_adapter_reads_both_spellings(self) -> None:
        aliased = MODULE.agent_facts_from_config_space(
            {
                "max_trials": 8,
                "configuration_space": {
                    "temperature": [0.0, 1.0],
                    "retrieval_depth": [1, 10],
                },
                "wired": ["temperature", "retrieval_depth"],
                "bounds": {"retrieval_depth": {"low": 1, "high": 10}},
            }
        )
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

    def test_max_trials_is_validated_like_every_other_field(self) -> None:
        """A documented field used to reach the scorer unchecked.

        `max_trials` lands in `space_size / max_trials`, so the bad shapes
        below produced a raw TypeError traceback rather than the refusal
        `ConfigSpaceInputError` documents.

        `agent_type` was guarded here for the same reason - it landed in a
        `HIGH_IMPACT_KNOBS[...]` lookup, where a list raised unhashable-type
        and a non-string scored coverage as unmeasured on a silent exit 0. The
        field is gone, so every one of those values is now an unknown key and
        ignored whole, which is this document's stated behaviour for unknown
        keys. `test_declaring_agent_type_changes_nothing_the_run_emits` covers
        that a document still carrying one is accepted and scores identically.
        """
        for document in (
            {"knobs": {"a": [1, 2]}, "max_trials": "12"},
            {"knobs": {"a": [1, 2]}, "max_trials": -5},
            {"knobs": {"a": [1, 2]}, "max_trials": 0},
            {"knobs": {"a": [1, 2]}, "max_trials": 1.5},
            # bool is an int in Python; True is not a trial budget
            {"knobs": {"a": [1, 2]}, "max_trials": True},
        ):
            with self.subTest(document=document):
                with self.assertRaises(MODULE.ConfigSpaceInputError):
                    MODULE.agent_facts_from_config_space(document)

    def _report_for(self, document: dict) -> str:
        """The complete JSON report the CLI prints for one config-space document."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config-space.json"
            path.write_text(json.dumps(document))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = MODULE.main(["--config-space", str(path), "--json"])
        self.assertEqual(exit_code, 0, stdout.getvalue())
        return stdout.getvalue()

    def test_declaring_agent_type_changes_nothing_the_run_emits(self) -> None:
        """A document that declares `agent_type` scores as if it had not.

        This is the evidence for removing the field, and it is deliberately
        written over the *whole* emitted report rather than over the agent
        pillar. A field that is read but never reaches any output is inert by
        definition, so byte-identity of the full JSON across every accepted
        value - and against a document that omits the key entirely - is a
        stronger statement than "the pillar score matches": it says nothing in
        the scorer reads it in any way a caller can observe.

        `agent_type` used to select `HIGH_IMPACT_KNOBS[...]` for the `coverage`
        sub-score, and `rag` names `retrieval_k` where `general` and `code_gen`
        do not - so these three answers moved the score apart by design until
        `coverage` was removed. That makes them the probe rather than an
        arbitrary sample.

        This test was written to outlive the field, on the assumption that once
        the declaration was gone "a customer document written against the old
        schema still parses and still scores identically, because unknown keys
        are ignored whole".

        *** OWNER DECISION - that assumption is false in this tree. ***

        #185 forked before #190 and never saw it. #190 REFUSES a key the
        declaration does not name, deliberately: "a key this schema does not
        name is a misspelling of one it does, and reading the document without
        it scores a claim the document never made". So removing `agent_type`
        from `CONFIG_SPACE_FIELDS` does not make old documents inert - it makes
        them exit 2, and `agent_type` is a key THIS GUIDE'S OWN PRODUCER used
        to emit.

        Resolved toward #190, because it is merged, fail-closed, and the same
        reading the owner already settled for #161 over #165. What is asserted
        below is therefore the behaviour this tree actually has. The decision
        the owner still owns is whether that break is acceptable, or whether
        `agent_type` should be kept in the declaration as an accepted-and-
        ignored retired field - a third option neither branch wrote, which
        would preserve #190's typo detection AND #185's compatibility claim.
        """
        space = {
            "knobs": {
                "model": ["a", "b", "c"],
                "retrieval_k": [1, 5],
                "prompt_style": ["direct", "structured"],
            },
            "max_trials": 12,
            "wired": ["model", "retrieval_k", "prompt_style"],
        }
        baseline = self._report_for(space)
        self.assertNotIn("agent_type", baseline)

        # The field reaches no output because it is no longer readable at all.
        for value in ("general", "rag", "code_gen", "", "a-type-no-catalog-has"):
            with self.subTest(agent_type=value):
                with self.assertRaises(MODULE.ConfigSpaceInputError) as raised:
                    MODULE.agent_facts_from_config_space(
                        {**space, "agent_type": value}
                    )
                self.assertIn("'agent_type'", str(raised.exception))

    def test_an_absent_optional_field_still_scores(self) -> None:
        """Validation must refuse bad *shapes*, not narrow the documented set.

        An absent `max_trials` is documented as scoreable, so the guard above
        must not swallow it.
        """
        absent = MODULE.agent_facts_from_config_space({"knobs": {"a": [1, 2]}})
        self.assertIsNone(absent.max_trials)
        pillar, caps, _ = MODULE.score_agent(absent)
        # This used to assert `confidence < 1.0`, and #189's own review found
        # why that was worthless: it passed on the `coverage` sub-score being
        # unmeasured, then kept passing after #182 deleted `coverage`, on the
        # unrelated fact that the fixture declares no `wired` list. With every
        # remaining sub-score measured the confidence is now 1.0, so the claim
        # is restated as the one this fixture actually makes - the document
        # attests no wired knob, so it is CAPPED, and that is a statement about
        # `wired` rather than about the absent budget.
        self.assertEqual(pillar.confidence, 1.0)
        self.assertEqual([cap.condition for cap in caps], ["agent-no-varying-knobs"])

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
        with `{"low": "1", "high": "5"}` has always scored. A guard that turns
        a working document into a hard exit-2 failure is worse than the silence
        it replaced, so a numeric string stays legal while `"x"` does not.
        """
        document = {
            "knobs": {"retrieval_k": [1, 5]},
            "wired": ["retrieval_k"],
            "bounds": {"retrieval_k": {"low": "1", "high": "5"}},
        }
        facts = MODULE.agent_facts_from_config_space(document)
        self.assertEqual(facts.bounds, {"retrieval_k": {"low": 1.0, "high": 5.0}})
        pillar, caps, _ = MODULE.score_agent(facts)
        self.assertEqual([cap.condition for cap in caps], [])
        # One knob, two values a 1-5 range can tell apart: a space of two.
        self.assertEqual(pillar.score, 35)
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
            {"max_trials": 12},
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
        reads and reports as "the settings document lists no settings" under
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

    def test_a_max_tokens_sweep_earns_no_variety_credit_and_is_never_refused(
        self,
    ) -> None:
        """The perverse incentive, measured before and after.

        `max_tokens` WAS one of `CANONICAL_RANGES`, and that entry is precisely
        what made it sweepable: a numeric knob with a range is measured against
        that range and paid for the span it covers. So sweeping it earned
        variation and knob-count credit like any other numeric knob - and it is
        the one knob whose downward sweep can silently zero the best model, by
        cutting its answer off into `finish_reason == "length"`, which scores 0
        rather than low. Measured on this scorer at the time this was written:
        the space below scored the agent pillar 77 on `first-run-guide`, and the
        identical space with `max_tokens: [256, 512]` added scored 83. Sweeping
        it was worth six points.

        Those two numbers are the record of the defect, not the assertion. What
        is asserted is the DECISION - that the sweep earns no additional credit -
        because the pillar's absolute value is a pricing choice other branches
        are free to revise, and an open one already does: with #174's
        categorical re-pricing merged in, the same space scores 85, and pinning
        77 here failed the merge (`85 != 77`) where neither branch's CI could
        see it. A relation survives any re-pricing; an absolute number is a
        merge failure waiting for a date.

        It now lives in `EXCLUDED_KNOB_REASONS` and in no catalog at all, so
        there is no range left for a future reader to pay for.

        The first repair tried was a refusal below a 2048 floor. That was wrong,
        and this test pins why it will not come back: how much room an answer
        needs is not predictable from a config-space document, so any floor is a
        guess, and a guess that REFUSES breaks a configuration that would have
        been fine - 2048 tokens for an agent answering `a`, `b`, `c` or `d`.

        So nothing here predicts. The credit stops (this test), and the
        truncation is DETECTED at the call, by the wrapper's
        `require_untruncated_completion` (test_skill_package.py).
        """
        base = {
            "model": ["o3-mini", "gpt-4o-mini"],
            "temperature": [0.0, 0.7],
            "prompt_style": ["direct", "structured"],
        }

        def agent_score(knobs):
            facts = MODULE.agent_facts_from_config_space(
                {
                    "max_trials": 12,
                    "knobs": knobs,
                    "wired": list(knobs),
                }
            )
            pillar, _, _ = MODULE.score_agent(facts)
            count = next(sub for sub in pillar.subscores if sub.name == "search-space")
            return pillar.score, count.evidence

        without, _ = agent_score(dict(base))
        swept, evidence = agent_score({**base, "max_tokens": [256, 512]})
        # The control, and the reason no absolute pillar number is pinned here.
        # `top_p` is what `max_tokens` used to be structurally - a numeric knob
        # with a `CANONICAL_RANGES` entry, paid for the span it covers - so
        # adding it still moves the pillar. Without it, `swept == without` would
        # hold just as well for a scorer that had stopped responding to knobs at
        # all, and the test would be green while asserting nothing.
        credited, _ = agent_score({**base, "top_p": [0.5, 0.9]})
        self.assertGreater(
            credited,
            without,
            "a numeric knob with a canonical range must still earn credit, or "
            "the equality below proves nothing about max_tokens",
        )
        self.assertEqual(
            swept,
            without,
            "sweeping max_tokens must earn exactly nothing - it was worth +6",
        )

        # Not hidden, either. #189 rewrote this line as a sentence and the two
        # guarantees survive the rewrite: the space is stated at its true size,
        # and the knob that multiplies the spend is NAMED.
        self.assertIn("8 distinct configurations", evidence)
        self.assertIn("max_tokens", evidence)
        # And not called a repeat. Two `max_tokens` values are two different
        # requests, not one configuration run twice - #189's sentence said
        # "each repeated N times over 'seed'" for every excluded knob, which
        # is false for this one and names the wrong knob besides.
        self.assertNotIn("repeated", evidence)
        self.assertNotIn("'seed'", evidence)
        self.assertIn("multiplied", evidence)

        # The note beside the knob is the knob's OWN reason. Telling an author
        # their max_tokens sweep measures run-to-run variance would be false:
        # every value asks the same question of the same agent and differs only
        # in whether the reply survived to be read.
        scored = MODULE.knob_variation("max_tokens", [256, 512])
        self.assertEqual(scored.kind, "excluded")
        self.assertEqual(scored.quality, 0.0)
        self.assertIn("resource limit", " ".join(scored.notes))
        self.assertIn("whether the answer fit", " ".join(scored.notes))
        self.assertNotIn(
            "run-to-run", " ".join(MODULE.knob_variation("max_tokens", [1, 2]).notes)
        )
        self.assertIn(
            "run-to-run", " ".join(MODULE.knob_variation("seed", [1, 2]).notes)
        )

        # And the range that made it sweepable is gone, not merely outvoted.
        # While `CANONICAL_RANGES` still held `{"low": 256, "high": 4096}`, the
        # exclusion was one early `return` away from being undone by a reader
        # who saw a canonical range and concluded the knob was meant to be
        # swept. The two catalogs must not disagree about one knob.
        self.assertNotIn("max_tokens", MODULE.CANONICAL_RANGES)
        self.assertIn("max_tokens", MODULE.EXCLUDED_KNOBS)
        self.assertEqual(
            MODULE.EXCLUDED_KNOBS & set(MODULE.CANONICAL_RANGES),
            set(),
            "a knob cannot be both excluded from credit and given a range to "
            "be credited against",
        )

        # NEVER refused. Every one of these was rejected by the floor this
        # replaces, and every one of them is a legal space.
        for knobs in (
            {"model": ["o3-mini"], "max_tokens": [256, 512]},
            {"max_tokens": ["256", "512"]},
            {"max_tokens": [16, 32]},
            {"max_tokens": [2048, 4096]},
        ):
            with self.subTest(knobs=knobs):
                facts = MODULE.agent_facts_from_config_space({"knobs": knobs})
                self.assertEqual(facts.knobs["max_tokens"], knobs["max_tokens"])
        self.assertFalse(hasattr(MODULE, "MAX_TOKENS_ANSWER_FLOOR"))

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
        # The walkthrough document's own score; the point here is that the
        # float spelling reaches it rather than exiting 2.
        self.assertEqual(pillar.score, 100)
        self.assertEqual(
            pillar.score,
            MODULE.score_agent(
                MODULE.agent_facts_from_config_space(WALKTHROUGH_CONFIG_SPACE)
            )[0].score,
        )
        # the trial cap still damps the search-space points identically either way
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
            "knobs": {"widget": [1, 50]},
            "wired": ["widget"],
        }
        pillar, caps, _ = MODULE.score_agent(
            MODULE.agent_facts_from_config_space(sweeping)
        )
        self.assertEqual([cap.condition for cap in caps], [])
        # Two values a noise floor can tell apart, so a space of two - and a
        # run that compares both of them.
        self.assertEqual(pillar.score, 35)
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

    def test_more_knobs_is_not_the_measure_and_never_was(self) -> None:
        """Sixteen configurations beat 4096 against the same twelve trials.

        The retired ladder said this by counting knobs and then damping, which
        made the count carry a claim it could not support: four knobs of two
        values and two knobs of four are the same search. The size says it
        directly, and says nothing about how the size was reached.
        """
        self.assertGreater(
            MODULE.search_space_points(16, 12), MODULE.search_space_points(4096, 12)
        )
        # Same space, reached two ways - one number, because it is one search.
        self.assertEqual(
            MODULE.search_space_points(16, 12), MODULE.search_space_points(16, 12)
        )

    def test_space_far_larger_than_the_trial_budget_is_penalized(self) -> None:
        # Against the declared floor rather than a point total: the ladder is
        # shares of `SEARCH_SPACE_WEIGHT`, so re-weighting the pillar must not
        # look like the damping getting weaker or stronger.
        self.assertLessEqual(
            MODULE.search_space_points(5000, 12),
            MODULE.SEARCH_SPACE_WEIGHT * MODULE.SEARCH_SPACE_PARTIAL,
        )
        self.assertLess(
            MODULE.search_space_points(5000, 12), MODULE.search_space_points(16, 12)
        )

    def test_omitting_the_budget_never_scores_above_declaring_one(self) -> None:
        """An absent field must not outscore a present one.

        This assertion used to run the other way - `search_space_points(5000,
        None)` was pinned EQUAL to full credit, on the reasoning that with no
        budget declared nothing says the space is too large for anything. That
        reasoning is about the document, not about the space: nothing in a
        document that omits `max_trials` says the run will compare the whole
        space either, and the top rung is a claim that it will.

        Measured on the assessment, not just the sub-score: one identical
        10 000-configuration space scored the card 88 STRONG with `max_trials:
        12` and 96 EXCELLENT with the field deleted. Deleting a line bought a
        band, and it penalised this guide's own producer, which always emits
        `max_trials`.

        Swept rather than spot-checked, because the defect was a single `if
        budget` guard and a spot check at one size is what let it through.
        """
        for configurations in (2, 4, 11, 12, 13, 48, 200, 5000, 10_000):
            omitted = MODULE.search_space_points(configurations, None)
            for budget in (1, 2, 12, 48, 500, 10_000):
                declared = MODULE.search_space_points(configurations, budget)
                if declared >= omitted:
                    continue
                # A LOWER declared score is only legitimate when the budget
                # itself is the bad news - a real measurement of a run that
                # compares less. Silence is not that measurement.
                self.assertLess(
                    min(configurations, budget),
                    MODULE.SEARCH_SPACE_FULL,
                    f"{configurations} configurations scored {omitted} with no "
                    f"budget and {declared} with max_trials={budget}: omitting "
                    "the field beat declaring a budget that reaches the full "
                    "rung, so an absent field outscored a present one",
                )

    def test_a_declared_zero_budget_is_not_an_absent_one(self) -> None:
        """`if not max_trials` could not tell `0` from "nobody said".

        Both left `configuration_budget` returning `None`, so a document
        declaring it would try zero configurations was scored - and DESCRIBED,
        in the evidence line - as one that declared no budget at all.

        `_read_trial_budget` refuses a zero, so no config-space document
        reaches this; `AgentFacts` is built directly elsewhere, and a guard
        that only holds because of a check in another function is one edit away
        from not holding.
        """
        self.assertIsNone(MODULE.configuration_budget(None, 1))
        self.assertEqual(MODULE.configuration_budget(0, 1), 0)
        self.assertEqual(MODULE.search_space_points(5000, 0), 0.0)
        self.assertIn(
            "try up to 0 of them",
            MODULE.search_space_evidence(5000, 5000, 1, 0),
        )

    def test_omitting_the_trial_budget_never_outscores_declaring_one(self) -> None:
        """Deleting a legal line must not be worth more than writing it.

        `max_trials` is documented requirement "no", so omitting it is a legal
        document - and the damping only fired when it was present, which meant
        silence was scored as `max_trials = infinity`. Measured end to end
        before the fix, one identical 100 000 000-configuration space and
        otherwise identical preflight and calibration: declared scored the
        agent pillar 83 and omitted scored it 94. On the trunk this branch
        descends from, the same pair is 88 STRONG against 90 EXCELLENT - a
        band, bought by deleting a key.

        It also inverted the sibling branch that refuses a key the schema does
        not declare: a customer told "did you mean `max_trials`?" scored higher
        by deleting the key than by fixing the spelling.

        Swept rather than spot-checked, because one shape passing is how the
        original rule looked correct: for every shape below, omitted may never
        exceed declared. A declared budget is still allowed to score LOWER -
        `max_trials: 1` is a real and bad measurement, where silence is not a
        measurement of anything.
        """
        shapes = {
            "walkthrough baseline": {
                "model": ["a", "b", "c"],
                "prompt_style": ["p", "q"],
                "thinking_shape": ["x", "y"],
            },
            "one knob": {"model": ["a", "b", "c"]},
            "nothing varies": {"model": ["a"], "temperature": [0.0]},
            "ten binary knobs": {f"k{i}": ["a", "b"] for i in range(10)},
            "eight knobs of ten values": {
                f"k{i}": [str(v) for v in range(10)] for i in range(8)
            },
        }
        for name, knobs in shapes.items():
            with self.subTest(shape=name):
                declared, _, _ = MODULE.score_agent(
                    MODULE.AgentFacts(
                        max_trials=12,
                        knobs=knobs,
                        wired=tuple(knobs),
                        config_space_supplied=True,
                    )
                )
                omitted, _, _ = MODULE.score_agent(
                    MODULE.AgentFacts(
                        knobs=knobs,
                        wired=tuple(knobs),
                        config_space_supplied=True,
                    )
                )
                self.assertLessEqual(
                    omitted.score,
                    declared.score,
                    "omitting `max_trials` scores above declaring it, so "
                    "deleting a documented-optional line is worth points",
                )

        # And the deduction is named on the card, so a reader who lost points
        # is told which field to write - but only where it actually cost them.
        wide = {f"k{i}": ["a", "b"] for i in range(10)}
        pillar, _, _ = MODULE.score_agent(
            MODULE.AgentFacts(knobs=wide, wired=tuple(wide), config_space_supplied=True)
        )
        # Every sub-score's evidence, not the one currently called
        # `knob-count`: the sibling branch renames this sub-score, and a
        # lookup by name turns a behavioural check into a StopIteration at
        # merge time - which reads as a broken test rather than as the
        # decision it was guarding.
        evidence = " ".join(sub.evidence for sub in pillar.subscores)
        self.assertIn("no trial budget was declared", evidence)
        self.assertIn("declaring `max_trials`", evidence)

        flat = {"model": ["a"], "temperature": [0.0]}
        pillar, _, _ = MODULE.score_agent(
            MODULE.AgentFacts(knobs=flat, wired=tuple(flat), config_space_supplied=True)
        )
        evidence = " ".join(sub.evidence for sub in pillar.subscores)
        self.assertNotIn(
            "no trial budget",
            evidence,
            "nothing varies here, so the budget cost this document nothing - "
            "naming it points the author away from what is actually wrong",
        )

    def _agent_pillar(self, **kwargs) -> object:
        pillar, _, _ = MODULE.score_agent(MODULE.AgentFacts(**kwargs))
        return pillar

    def test_a_synonym_spelling_is_refused_rather_than_renamed_or_scored(
        self,
    ) -> None:
        """No name is substituted, and no document is quietly scored lower.

        `KNOB_ALIASES` mapped `prompt_policy` onto `prompt_style` to keep a
        catalog defect from docking a correct walkthrough. That defect was
        fixed in the same commit - the `general` catalog spells the dimension
        `prompt_style` - so the RENAMING outlived its cause, one pair for one
        knob, while `temp`/`temperature` and `n_shot`/`fewshot_k` got none.

        What did not outlive its cause is the refusal it carried, and deleting
        the table deleted that too. Measured end to end on one identical
        bundle, a document declaring `prompt_policy` and `prompt_style` over
        different values went from exit 2 to exit 0 with the agent pillar at
        77, `4 of 4 wired knobs actually vary`, and 24 combinations against 12
        for the same space written once. Two spellings of one dimension are
        two dimensions to every count downstream, so declaring both doubles the
        space and pays twice for one knob - which is verbatim the inflation the
        deleted function's own docstring cited as its reason to exist.

        The quieter half is a document written consistently in the synonym. It
        matches itself, so nothing is phantom and nothing was refused; it just
        scored lower - coverage 8.33/25 against 16.67/25 - with the missing
        knob named in the evidence line as though the author had not tuned it.
        Neither shape is silent now: both are refused, by name, naming the
        spelling this scorer knows. That is the help this branch says it gives
        for every knob rather than for `prompt_policy` alone, and it was the
        one knob it did not reach.
        """
        knobs = {"model": ["a", "b"], "temperature": [0.0, 0.6]}
        # Written consistently in the synonym: not a phantom, and no longer a
        # quiet deduction either.
        with self.assertRaises(MODULE.ConfigSpaceInputError) as consistent:
            MODULE.agent_facts_from_config_space(
                {
                    "knobs": dict(knobs, prompt_policy=["direct", "structured"]),
                    "wired": ["model", "temperature", "prompt_policy"],
                }
            )
        self.assertIn("'prompt_policy'", str(consistent.exception))
        self.assertIn("another name for 'prompt_style'", str(consistent.exception))

        # Both spellings, different values - the shape trunk refused and this
        # branch briefly accepted at a higher score.
        with self.assertRaises(MODULE.ConfigSpaceInputError) as both:
            MODULE.agent_facts_from_config_space(
                {
                    "knobs": dict(
                        knobs,
                        prompt_policy=["p1", "p2"],
                        prompt_style=["s1", "s2"],
                    ),
                    "wired": [
                        "model",
                        "temperature",
                        "prompt_policy",
                        "prompt_style",
                    ],
                }
            )
        self.assertIn("declare each search dimension once", str(both.exception))

        # Nothing is renamed on the way through: the canonical document scores,
        # and it scores under the name its author wrote.
        facts = MODULE.agent_facts_from_config_space(
            {
                "knobs": dict(knobs, prompt_style=["direct", "structured"]),
                "wired": ["model", "temperature", "prompt_style"],
            }
        )
        self.assertEqual(sorted(facts.knobs), ["model", "prompt_style", "temperature"])

        # And the name is judged exactly as written everywhere else too: the
        # phantom check no longer routes through an alias table, so its
        # ordering against a normalization step is not a defect surface.
        with self.assertRaises(MODULE.ConfigSpaceInputError) as raised:
            MODULE.agent_facts_from_config_space(
                {"knobs": {"prompt_style": ["a", "b"]}, "wired": ["prompt_policy"]}
            )
        self.assertIn(
            "'prompt_policy' (did you mean 'prompt_style'?)",
            str(raised.exception),
            "the general form of what the alias bought: name the canonical "
            "spelling for every knob, instead of substituting one silently",
        )

    def test_max_tokens_is_named_by_no_catalog_this_guide_recommends_from(
        self,
    ) -> None:
        """`max_tokens` is a capacity guard, so no catalog may propose it.

        references/run-safety.md tells authors not to sweep low `max_tokens`
        values in any space containing a reasoning model - a truncated answer
        scores 0 for reasons unrelated to configuration quality.

        This test used to end by proving that omitting `max_tokens` cost a
        space none of its `coverage` points. That sub-score is gone, and with
        it the only way a catalog omission could cost anything at all - so the
        half that remains is the half that was always doing the work.
        """
        for agent_type in ("general", "code_gen"):
            with self.subTest(agent_type=agent_type):
                self.assertNotIn("max_tokens", MODULE.HIGH_IMPACT_KNOBS[agent_type])
        for agent_type, catalog in MODULE.HIGH_IMPACT_KNOBS.items():
            with self.subTest(agent_type=agent_type):
                self.assertNotIn("max_tokens", catalog)
        for name, catalog in (
            ("CANONICAL_RANGES", MODULE.CANONICAL_RANGES),
            ("OPEN_CATEGORICAL_KNOBS", MODULE.OPEN_CATEGORICAL_KNOBS),
            ("NOISE_FLOORS", MODULE.NOISE_FLOORS),
            ("KNOB_SYNONYMS", MODULE.KNOB_SYNONYMS),
        ):
            with self.subTest(catalog=name):
                self.assertNotIn("max_tokens", catalog)

        # And no sub-score is left that a catalog omission could dock.
        pillar = self._agent_pillar(
            knobs={
                "model": ["a", "b"],
                "temperature": [0.0, 0.6],
                "prompt_style": ["direct", "structured"],
            },
            wired=("model", "temperature", "prompt_style"),
        )
        self.assertEqual(sorted(sub.name for sub in pillar.subscores), ["search-space"])
        for sub in pillar.subscores:
            with self.subTest(subscore=sub.name):
                self.assertNotIn("max_tokens", sub.evidence)


class TheConfigSpaceSizeIsTheMeasureTests(unittest.TestCase):
    """The agent pillar scores one thing: how big the search actually is.

    This guide is an onboarding taste guide. Whether four wide knobs beat ten
    narrow ones is what the run is FOR, and no arithmetic over a JSON document
    can rank it before a trial has been spent - so the pillar stopped trying,
    and measures the one thing that is both countable and load-bearing.

    The table below is the whole claim, stated as shapes rather than as a
    formula, because a formula can be right about numbers nobody would ever
    write.
    """

    BUDGET = 12

    def _shape(self, knobs, **facts) -> tuple:
        pillar, caps, _ = MODULE.score_agent(
            MODULE.AgentFacts(
                knobs=knobs,
                wired=tuple(sorted(knobs)),
                max_trials=facts.pop("max_trials", self.BUDGET),
                config_space_supplied=True,
                **facts,
            )
        )
        space = next(s for s in pillar.subscores if s.name == "search-space")
        return pillar.score, space.evidence, [cap.condition for cap in caps]

    def test_the_pillar_reports_one_sub_score(self) -> None:
        """Two numbers only need weighing while there are two of them.

        `knob-count` and `variation` are gone with the 55/45 that weighed them.
        Asserted on the pillar rather than on the absence of a constant,
        because a re-introduced sub-score under a new name is the same defect.
        """
        pillar, _, _ = self._pillar({"model": ["a", "b", "c"]})
        self.assertEqual([sub.name for sub in pillar.subscores], ["search-space"])
        self.assertEqual(pillar.subscores[0].maximum, MODULE.SEARCH_SPACE_WEIGHT)
        self.assertEqual(MODULE.SEARCH_SPACE_WEIGHT, 100.0)
        for retired in ("KNOB_COUNT_WEIGHT", "VARIATION_WEIGHT", "knob_count_points"):
            with self.subTest(retired=retired):
                self.assertFalse(hasattr(MODULE, retired))

    def _pillar(self, knobs, **facts):
        return MODULE.score_agent(
            MODULE.AgentFacts(
                knobs=knobs,
                wired=tuple(sorted(knobs)),
                max_trials=facts.pop("max_trials", self.BUDGET),
                config_space_supplied=True,
                **facts,
            )
        )

    def test_the_representative_shapes_are_ordered_by_what_the_run_compares(
        self,
    ) -> None:
        """Every shape the owner named, against one twelve-trial budget.

        The two entries that carry the argument are the last pair. A
        1024-configuration space scores BELOW a 48-configuration one because
        the twelve trials are the same twelve either way and the larger report
        describes a sample nobody chose - and a 48 and a 12 score the SAME,
        because which of them is the better search is exactly what this scorer
        cannot know before the run.
        """
        pinned = self._shape(
            {"model": ["a"], "temperature": [0], "prompt_style": ["direct"]}
        )
        one_knob = self._shape({"model": ["a", "b"]})
        tight = self._shape(
            {
                "model": ["a", "b", "c"],
                "prompt_style": ["direct", "structured"],
                "thinking_shape": ["direct", "cot"],
            }
        )
        walkthrough = self._shape(
            {
                "model": ["a", "b", "c"],
                "temperature": [0],
                "prompt_style": ["direct", "structured"],
                "pre_action_reflect": [False, True],
                "thinking_shape": ["direct", "cot"],
                "reflect": [False, True],
            }
        )
        oversized = self._shape({f"k{index}": ["a", "b"] for index in range(10)})

        self.assertEqual(pinned[0], 0)
        self.assertIn("agent-no-varying-knobs", pinned[2])
        self.assertEqual(one_knob[0], 35)
        self.assertEqual(tight[0], 100)
        self.assertEqual(walkthrough[0], 100)
        self.assertEqual(oversized[0], 70)

        self.assertLess(oversized[0], walkthrough[0])
        self.assertEqual(tight[0], walkthrough[0])
        self.assertLess(one_knob[0], tight[0])
        self.assertLess(pinned[0], one_knob[0])

    def test_a_fake_sweep_does_not_buy_a_bigger_space(self) -> None:
        """The one piece of the retired `variation` sub-score that had to live.

        `temperature: [0.1, 0.115]` is two values wearing one hat. Counting
        them as two would let any space grow by declaring values nothing can
        tell apart - which is precisely what `variation` existed to refuse, so
        the refusal moved INSIDE the count rather than being paid for
        afterwards.
        """
        fake = self._shape({"temperature": [0.1, 0.115], "model": ["a", "b"]})
        honest = self._shape({"model": ["a", "b"]})
        self.assertEqual(fake[0], honest[0])
        self.assertIn("your space has 2 distinct configurations", fake[1])
        # And the sentence does not contradict a file the reader can count.
        self.assertIn(
            "(4 declared - values too close to tell apart count once)", fake[1]
        )
        # The diagnosis is still raised where it can be acted on.
        _, _, knobs = self._pillar({"temperature": [0.1, 0.115], "model": ["a", "b"]})
        temperature = next(knob for knob in knobs if knob.name == "temperature")
        self.assertEqual(temperature.effective_values, 1)
        self.assertIn("the same configuration in practice", " ".join(temperature.notes))

    def test_the_evidence_line_says_something_a_person_can_act_on(self) -> None:
        """A bare number is not guidance.

        Two facts in one sentence, in this order: how big the space is, and
        what this run will do with it. The second is the one a reader can
        change cheaply, and neither is inferable from a score of 70.
        """
        self.assertEqual(
            self._shape({f"k{index}": ["a", "b"] for index in range(10)})[1],
            "your space has 1024 distinct configurations; this run will try up "
            "to 12 of them; the space is over 20x what that budget reaches, "
            "which holds this one step below full credit",
        )
        # No declared budget is its own sentence rather than a silent
        # unbounded pass - and it no longer claims "the run may try all of
        # them", which nothing here establishes and which was the sentence
        # that made the old full-credit score sound earned.
        self.assertEqual(
            self._shape({"model": ["a", "b"]}, max_trials=None)[1],
            "your space has 2 distinct configurations; no trial budget was "
            "declared, so nothing here says how much of it this run compares; "
            "2 more would reach the 4 this guide scores as room for two "
            "settings to interact",
        )

    def test_the_step_the_score_sits_on_is_named_not_silent(self) -> None:
        """The ladder is a step function, so the cliff has to be visible.

        Four values and no others - 0, 35, 70, 100 - which means one extra
        value in one knob can be worth a band while the sentence beside the
        number moves by a single digit. Measured: 11 compared configurations
        score the pillar 70 and the card 88 STRONG; 12 score it 100 and the
        card 96 EXCELLENT.

        The plateau itself is kept deliberately. Every threshold in it is a
        number this guide already uses elsewhere, and smoothing it would invent
        a scale - the exact mistake the retired `variation` sub-score made. So
        the repair is disclosure: say which step this is and what reaches the
        next one.
        """
        just_under = MODULE.search_space_evidence(11, 11, 1, 48)
        self.assertIn("1 more would reach the 12", just_under)
        self.assertIn("complete search", just_under)
        # And at the top rung there is no next step to name, so nothing is
        # appended - the clause must not become decoration on every line.
        self.assertNotIn("would reach", MODULE.search_space_evidence(12, 12, 1, 48))
        # The two ways to sit below full credit at full SIZE have different
        # repairs, so they are different sentences.
        self.assertIn(
            "declaring `max_trials`", MODULE.search_space_evidence(50, 50, 1, None)
        )
        self.assertIn("over 20x", MODULE.search_space_evidence(5000, 5000, 1, 12))


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

    def test_a_key_the_declaration_does_not_name_is_refused(self) -> None:
        """An undeclared key was ignored, and that ignoring inflated a score.

        This test asserted the opposite. Ignoring the key was called a
        compatibility guarantee, but nothing had ever been published for it to
        be compatible with, and it made the schema's own front door the defect
        class `CONFIG_SPACE_FIELDS` exists to close: a key the declaration does
        not name cannot be told apart from a misspelling of one it does, and
        the document is then scored as though the author had never written the
        field at all. Measured end to end on the trunk this replaces,
        `max_trial` for `max_trials` moved a 512-configuration space from
        89 STRONG to 92 EXCELLENT under a byte-identical evidence line, exit 0.

        `bounds` is dropped the same way by `bound`, and the knob then scores
        against the canonical range instead of the declared one.
        """
        for field, typo in (("max_trials", "max_trial"), ("bounds", "bound")):
            with self.subTest(field=field):
                with self.assertRaises(MODULE.ConfigSpaceInputError) as raised:
                    MODULE.agent_facts_from_config_space(
                        {
                            "knobs": {"temperature": [0.0, 1.0]},
                            "wired": ["temperature"],
                            typo: (
                                3
                                if field == "max_trials"
                                else {"temperature": {"low": 0.0, "high": 1.0}}
                            ),
                        }
                    )
                message = str(raised.exception)
                self.assertIn(repr(typo), message)
                # Not just `repr(field)` anywhere in the message: the message
                # also lists every declared field, so that assertion passes
                # with the suggestion deleted. Pin the suggestion itself.
                self.assertIn(
                    f"did you mean {field!r}?",
                    message,
                    "a near miss must suggest the field it is a near miss of",
                )

        # A key nowhere near a declared field is still refused, just without a
        # suggestion - the point is that no undeclared key is read around.
        with self.assertRaises(MODULE.ConfigSpaceInputError) as unrelated:
            MODULE.agent_facts_from_config_space(
                {
                    "knobs": {"temperature": [0.0, 1.0]},
                    "wired": ["temperature"],
                    "seed_policy": "whatever",
                }
            )
        self.assertIn("'seed_policy'", str(unrelated.exception))

    def test_every_declared_field_is_accepted_by_the_undeclared_key_guard(
        self,
    ) -> None:
        """The guard must be derived from the declaration, not a second list.

        A hand-written set of legal keys is the same two-artifact shape that
        made the schema table drift from the validator: adding a field to
        `CONFIG_SPACE_FIELDS` would then start refusing it.
        """
        sample = {
            "knobs": {"temperature": [0.0, 1.0]},
            "configuration_space": {"temperature": [0.0, 1.0]},
            "max_trials": 3,
            "wired": ["temperature"],
            "bounds": {"temperature": {"low": 0.0, "high": 1.0}},
        }
        declared = {spec.name for spec in MODULE.CONFIG_SPACE_FIELDS}
        # Built from the declaration, not listed beside it: a field removed
        # from `CONFIG_SPACE_FIELDS` drops out of the document here, and a
        # field added without a sample value fails on the line below rather
        # than leaving the guard untested for it.
        self.assertLessEqual(
            declared,
            set(sample),
            "a newly declared field needs a sample value here",
        )
        MODULE.agent_facts_from_config_space({name: sample[name] for name in declared})

    def test_the_undeclared_key_guard_reads_the_declaration_it_guards(self) -> None:
        """The derivation has to be load-bearing today, not once a field moves.

        The test above builds its document FROM `CONFIG_SPACE_FIELDS`, so it
        proves the two agree - and two identical things agree whether one is
        derived from the other or copied from it. Replacing
        `{spec.name for spec in CONFIG_SPACE_FIELDS}` with a hand-written set
        of the same six names fails nothing at all: measured, the whole suite
        stays green apart from the behaviour lock, which is only stale because
        the file's bytes changed. A guard whose mutation nothing catches is a
        guard that documents an intention.

        So the two sets are made to DIFFER here. A field is added to the
        declaration at runtime and the same document is refused before and
        accepted after; a copied list cannot follow that, and a hand-written
        one fails on the second call.
        """
        document = {
            "knobs": {"temperature": [0.0, 1.0]},
            "wired": ["temperature"],
            "a_field_declared_after_this_guard_was_written": "x",
        }
        with self.assertRaises(MODULE.ConfigSpaceInputError):
            MODULE._reject_undeclared_fields(document)

        original = MODULE.CONFIG_SPACE_FIELDS
        MODULE.CONFIG_SPACE_FIELDS = original + (
            MODULE.ConfigSpaceField(
                "a_field_declared_after_this_guard_was_written",
                "string",
                "no",
                lambda field, value: value,
            ),
        )
        try:
            MODULE._reject_undeclared_fields(document)
        finally:
            MODULE.CONFIG_SPACE_FIELDS = original

        # And back: the restore is part of the assertion, not cleanup. A guard
        # that kept the added field would pass the line above for the wrong
        # reason.
        with self.assertRaises(MODULE.ConfigSpaceInputError):
            MODULE._reject_undeclared_fields(document)

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
                {"knobs": {"model": []}, "wired": ["model"]}
            )
        self.assertIn("knobs['model']", str(raised.exception))
        # an empty *space* still means the document lists no settings and still scores
        self.assertEqual(MODULE.agent_facts_from_config_space({"knobs": {}}).knobs, {})

    def test_bounds_are_validated_as_a_pair_not_only_edge_by_edge(self) -> None:
        """Two finite edges can still be no range.

        Each edge was checked alone, so `{"low": 5, "high": 1}` scored 32 with
        every span negative, and `{"low": 3, "high": 3}` scored 32 *and* cleared
        `agent-no-varying-knobs` by zeroing the noise floor - two values a hair
        apart read as a full sweep of a range that admits one value.
        """
        sweeping = {
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
        # A space of two either way now: how WIDELY the two values sweep is a
        # per-knob diagnostic rather than a sub-score, so the declared bounds
        # change the knob's notes and not the pillar. What they still change is
        # whether the two values are two at all - that is the noise floor, and
        # it is inside the configuration count.
        self.assertEqual(MODULE.score_agent(facts)[0].score, 35)
        self.assertEqual(
            MODULE.score_agent(MODULE.agent_facts_from_config_space(sweeping))[0].score,
            35,
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
                            "knobs": knobs,
                            "wired": ["k"],
                            "bounds": {"k": edges},
                        }
                    )
                self.assertIn("bounds['k']", str(raised.exception))

        # a narrow range that is still measurable is not refused: the guard is
        # on the width the scorer can use, not on ranges being small
        sweeping = {"knobs": {"k": [1, 50]}, "wired": ["k"]}
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
            35,
        )

    def test_a_large_integer_trial_budget_scores_like_any_other(self) -> None:
        """`10**309` is a positive JSON integer, and it exited 1.

        The guard read it through `float(max_trials).is_integer()`, which
        raises OverflowError - so a document the parent scored became a
        traceback, which is the failure mode the guard was added to remove.
        `space_size / max_trials` had the same defect from the other side.
        """
        document = {
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
        # It scores rather than raising, which is what this test is about, and
        # it scores zero: a budget of one trial compares nothing, whatever the
        # space around it holds. The evidence line is the actionable half.
        self.assertEqual(pillar.score, 0)
        self.assertIn(
            "this run will try up to 1 of them",
            next(s for s in pillar.subscores if s.name == "search-space").evidence,
        )

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
        space = next(s for s in pillar.subscores if s.name == "search-space")
        self.assertEqual(
            space.evidence,
            "your space has 1 distinct configuration; every trial would be identical",
        )
        self.assertIn("agent-no-varying-knobs", [cap.condition for cap in caps])


class DocumentedSchemaTests(unittest.TestCase):
    def test_the_walkthrough_document_still_scores_and_clears_the_cap(self) -> None:
        """The pin the alias change could have moved, measured rather than assumed.

        The shipped space declares only `prompt_style`, so collapsing the alias
        leaves its six dimensions and 48 configurations untouched.
        """
        pillar, caps, _ = MODULE.score_agent(
            MODULE.agent_facts_from_config_space(WALKTHROUGH_CONFIG_SPACE)
        )
        self.assertEqual([cap.condition for cap in caps], [])
        self.assertEqual(pillar.score, 100)
        space = next(s for s in pillar.subscores if s.name == "search-space")
        self.assertEqual(
            space.evidence,
            "your space has 48 distinct configurations; this run will try up to "
            "12 of them",
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
        # A document arrived and named knobs, so the search space WAS read -
        # it holds one configuration, because nothing in it is attested as
        # wired. Measured, and measured at zero.
        measured = {s.name: s.measured for s in pillar.subscores}
        self.assertEqual(measured, {"search-space": True})

    def test_declared_knobs_without_wiring_score_like_no_document(self) -> None:
        """The declaration on its own is worth exactly zero points.

        The score is the same 0 either way, because a space nothing varies in
        holds one configuration however the document spells it.

        Confidence is NOT the same, and that is the point of asserting it
        rather than deleting it. A document naming knobs is a search space
        somebody read; no document at all is a search space nobody read, and
        the pillar reporting 55% evidence coverage for the second was the
        opening card claiming to have looked at a file this guide deliberately
        withholds. The direction is the constraint - see
        `test_a_config_space_never_lowers_agent_confidence`.
        """
        declared, _, _ = MODULE.score_agent(
            MODULE.AgentFacts(knobs={"model": ["a", "b"]}, config_space_supplied=True)
        )
        absent, _, _ = MODULE.score_agent(MODULE.AgentFacts())
        self.assertEqual(declared.score, absent.score)
        self.assertEqual(declared.confidence, 1.0)
        self.assertEqual(absent.confidence, 0.0)

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
        spellings still say the document lists no settings rather than the wiring message.
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
                        "Nothing is marked as a setting the agent actually "
                        "uses, so there is nothing to search."
                    ],
                )
                self.assertEqual(knobs, [])
                self.assertEqual(pillar.score, 0)
                # Fully measured. A document that lists no settings is a
                # search space this scorer read off a file the customer handed
                # over: it holds one configuration. There is nothing further
                # to observe about it, so the pillar does not claim there is.
                self.assertEqual(pillar.confidence, 1.0)
                self.assertEqual(
                    {s.evidence for s in pillar.subscores},
                    {"the settings document lists no settings"},
                )

    def test_explicit_empty_wired_is_an_attested_zero(self) -> None:
        """`"wired": []` states something an absent list does not.

        It names zero wired knobs, so the search space is a counted one - and
        the evidence must not repeat the empty-document line, because knobs
        *are* declared here; zero of them are attested as wired.
        """
        pillar, caps, _ = MODULE.score_agent(
            MODULE.AgentFacts(knobs={"temperature": [0.0, 1.0]}, wired=())
        )
        self.assertIn("agent-no-varying-knobs", [cap.condition for cap in caps])
        space = next(s for s in pillar.subscores if s.name == "search-space")
        self.assertTrue(space.measured)
        self.assertEqual(
            space.evidence,
            "0 of 1 listed settings are marked as ones the agent uses",
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
            "collected_rows": 40,
            "synthesised_rows": 0,
            "undeclared_rows": 0,
            "answerable_rows": 40,
            "generated_answer_rows": 0,
        },
    },
    {
        "check": "dataset-integrity",
        "status": "PASS",
        "metrics": {"malformed_rows": 0},
    },
    # Emitted for every dataset preflight can read, and required: an absent
    # record used to be scored as "the splits do not overlap" and "the ids are
    # unique", neither of which anything had established.
    {"check": "dataset-split", "status": "WARN", "metrics": {}},
    {"check": "dataset-ids", "status": "PASS", "metrics": {}},
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
        self.assertEqual(agent["score"], 100)
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
        # input read as having observed less. The constraint is the DIRECTION,
        # and it is not equality: a document naming a knob is a search space
        # somebody read, and no document is one nobody read. Confidence rises,
        # the score does not, and the band is unchanged either way because the
        # 45 ceiling binds in both runs.
        self.assertGreater(with_document["confidence"], without["confidence"])
        conditions = {cap["condition"] for cap in with_document["caps"]}
        self.assertEqual(conditions, {cap["condition"] for cap in without["caps"]})
        self.assertIn("agent-no-varying-knobs", conditions)

    def test_absent_wiring_card_reports_an_unattested_connection(self) -> None:
        """What the user reads must name what the document failed to state.

        The negative assertions matter as much as the positive one: the card
        used to claim "1 of 1 wired knobs actually vary" about a knob nobody had
        named, and an empty-document line is false whenever knobs are declared.
        Both strings live in branches that are still reachable, so pin their
        absence rather than trusting that this branch can no longer produce them.
        """
        with tempfile.TemporaryDirectory() as directory:
            space = Path(directory) / "space.json"
            space.write_text(
                json.dumps({"knobs": {"model": ["gpt-4o-mini", "gpt-4o"]}})
            )
            _, output = self._run(["--config-space", str(space), "--color", "never"])
        self.assertIn("none is marked as one the agent uses", output)
        self.assertNotIn("1 of 1 wired knobs", output)
        self.assertNotIn("lists no settings", output)

    def test_weights_are_configurable_and_reported(self) -> None:
        parsed = MODULE.parse_weights("50,30,20")
        self.assertEqual(parsed["dataset"], 50.0)


class NoInternalFailureReachesTheUserAsATracebackTests(unittest.TestCase):
    """`run` names four input errors; everything else escaped to the shell.

    A `ValueError` from an unregistered cap, a `KeyError` from an unforeseen
    payload shape, a `TypeError` from a field that arrived as a string - each
    exited 1 with a traceback naming this file, and printed no card at all.
    That is the worst output this tool has: the reader is running their first
    optimization, and a defect in the checker reads as a defect in what they
    brought.
    """

    @staticmethod
    def _run(argv: list[str], environ: dict[str, str] | None = None) -> tuple[
        int, str, str
    ]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = MODULE.main(argv)
        return code, out.getvalue(), err.getvalue()

    def _explode(self, error: BaseException) -> None:
        """Make the scorer raise from inside, where the class actually lives."""
        original = MODULE.score_dataset

        def boom(*args: object, **kwargs: object) -> None:
            raise error

        MODULE.score_dataset = boom
        self.addCleanup(setattr, MODULE, "score_dataset", original)

    def test_an_unexpected_error_prints_a_diagnosis_and_exits_non_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            space = Path(directory) / "space.json"
            space.write_text(json.dumps({"knobs": {"temperature": [0.7, 0.9]}}))
            for error in (
                ValueError("cap 'x' has no place in CAP_SEVERITY_ORDER"),
                KeyError("answerable_rows"),
                TypeError("'<' not supported between 'str' and 'int'"),
            ):
                with self.subTest(error=type(error).__name__):
                    self._explode(error)
                    code, stdout, stderr = self._run(
                        ["--config-space", str(space), "--json"]
                    )
                    self.assertEqual(code, MODULE.INTERNAL_ERROR_EXIT)
                    self.assertNotEqual(code, 0)
                    self.assertEqual(stdout, "", "a failed run printed a result")
                    self.assertIn(type(error).__name__, stderr)
                    self.assertNotIn("Traceback (most recent call last)", stderr)
                    self.assertIn("defect in the check", stderr)

    def test_the_stack_is_still_available_to_whoever_is_fixing_it(self) -> None:
        """Diagnosed, not swallowed."""
        self._explode(ValueError("boom"))
        with tempfile.TemporaryDirectory() as directory:
            space = Path(directory) / "space.json"
            space.write_text(json.dumps({"knobs": {"temperature": [0.7, 0.9]}}))
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                code = MODULE.main(["--config-space", str(space), "--json"])
            self.assertEqual(code, MODULE.INTERNAL_ERROR_EXIT)
            code = MODULE.report_internal_error(
                "readiness.py",
                ValueError("boom"),
                environ={MODULE.TRACEBACK_ENV: "1"},
                stream=err,
            )
        self.assertEqual(code, MODULE.INTERNAL_ERROR_EXIT)
        self.assertIn("ValueError: boom", err.getvalue())

    def test_a_healthy_run_still_prints_its_card_and_exits_zero(self) -> None:
        """The false-red direction: the boundary must catch nothing normally."""
        with tempfile.TemporaryDirectory() as directory:
            space = Path(directory) / "space.json"
            space.write_text(json.dumps({"knobs": {"temperature": [0.7, 0.9]}}))
            code, stdout, stderr = self._run(["--config-space", str(space), "--json"])
        self.assertEqual(code, 0)
        self.assertIn('"overall"', stdout)
        self.assertNotIn("internal error", stderr)

    def test_a_named_input_error_still_exits_two_rather_than_three(self) -> None:
        """The boundary widens what is caught; it does not relabel what was."""
        code, _stdout, stderr = self._run(["--config-space", "/nonexistent.json"])
        self.assertEqual(code, 2)
        self.assertIn("cannot read scoring input", stderr)


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

    def test_pre_run_sample_size_never_claims_a_detectable_effect(self) -> None:
        evidence = [MODULE.size_points(count)[1] for count in (3, 15, 30, 100)]
        evidence.extend(
            cap.reason
            for count in (3, 15)
            if (cap := MODULE.power_ceiling(count)) is not None
        )
        joined = " ".join(evidence).casefold()
        for unsupported in (
            "+/-",
            "resolve differences",
            "minimum detectable",
            "confidence interval",
        ):
            self.assertNotIn(unsupported, joined)

    def test_a_ceiling_that_only_bounds_a_claim_does_not_block_the_run(self) -> None:
        """A bounded claim and a stopped run are different statements.

        Every cap used to imply BLOCKED, which was right while every cap meant
        "something here is broken". `dataset-coarse-resolution` says only "this
        cannot present as EXCELLENT" - the run is worth making. Conflating them
        marked a healthy 30-row dataset BLOCKED and told the assistant not to
        proceed, against the guide's own rule that a low score never stops the
        walkthrough. Surfaced by a downstream consumer that cross-checks a
        recommended action against the caps that fired: a run reported as
        blocked cannot also be told to proceed.
        """
        coarse = MODULE.power_ceiling(15)
        self.assertFalse(coarse.blocks)
        # And the ceiling still binds even though it does not block.
        self.assertEqual(coarse.ceiling, MODULE.COARSE_RESOLUTION_CEILING)
        # Its smaller twin used to block, and the line asserting that read
        # "too few to measure anything IS a stop: there is nothing to compare".
        # That is true of one of the two states this cap covers and false of the
        # other, and the cap already wrote them as two different reasons. Three
        # comparable examples is the wiring check the guide sanctions -
        # preflight WARNs rather than FAILs at that size and SKILL.md routes it
        # to "call rankings exploratory" - and the cap's own closing sentence,
        # "treat any difference as a hint, not a result", is advice for a run
        # that happens. Zero scoreable examples is the stop the old line
        # described, and it keeps blocking.
        small = MODULE.power_ceiling(3)
        self.assertFalse(small.blocks)
        self.assertEqual(small.ceiling, MODULE.WIRING_CHECK_CEILING)
        self.assertTrue(MODULE.power_ceiling(0).blocks)

    def test_an_absent_settings_document_bounds_the_score_without_blocking(
        self,
    ) -> None:
        """The one cap that fires on every run must not stop every run.

        The guide deliberately withholds any config-space document found before
        this run's search, so `agent-no-varying-knobs` fires on the opening card
        of every project including a perfect one. While it blocked, that card
        read `45/100 PARTIAL (PAID RUN BLOCKED)` with `recommended_action:
        vary-knobs` - a repair for a defect the user does not have - on the last
        screen shown before they are asked to pay.

        Shaped after `test_a_ceiling_that_only_bounds_a_claim_does_not_block_the
        _run` above, and asserting the same three things end to end: the cap's
        own `blocks`, the `status` it produces, and the `recommended_action`
        that follows. Asserting the reason string alone would have passed
        against the whole scorer change reverted, since the wording moved in the
        same commit.
        """

        def scored(facts: MODULE.AgentFacts) -> tuple:
            # The other two pillars are scored high on purpose: with the agent
            # pillar alone the weighted average is 0 and the ceiling is not the
            # operative limit, so "capped at 45" would prove nothing. This is
            # the healthy project the defect was reported against.
            agent, caps, knobs = MODULE.score_agent(facts)
            pillars = [agent] + [
                MODULE.Pillar(name=name, score=95, confidence=1.0, subscores=())
                for name in ("dataset", "evaluation")
            ]
            return caps, MODULE.aggregate(
                pillars, caps, knobs, dict(MODULE.DEFAULT_WEIGHTS)
            )

        # No document reached the scorer - the ordinary opening state.
        caps, score = scored(MODULE.AgentFacts())
        self.assertEqual([cap.condition for cap in caps], ["agent-no-varying-knobs"])
        self.assertFalse(caps[0].blocks)
        self.assertEqual(score.status, "OK")
        self.assertEqual(score.recommended_action, MODULE.PROCEED)
        # Advisory is not free: the ceiling is unchanged and it IS the score,
        # holding a 71-point average down to 45.
        #
        # The ceiling is read by name, not restated as 45 - a literal here is a
        # second home for a number the scorer already owns, and it is the same
        # defect that had this cap raised with a literal at four call sites. 71
        # stays a literal deliberately: it is the arithmetic of DEFAULT_WEIGHTS
        # over two pillars this test pins itself, checked against every open
        # branch, none of which re-weights.
        self.assertEqual(caps[0].ceiling, MODULE.AGENT_NO_VARYING_KNOBS_CEILING)
        self.assertEqual(score.weighted_average, 71)
        self.assertEqual(score.overall, caps[0].ceiling)
        # And the ceiling is what BINDS - the relation the two numbers above are
        # only one instance of. Without this, both assertions would still pass
        # if a re-weighting dropped the average below the cap, and the test
        # would be green while proving nothing about the cap at all.
        self.assertGreater(score.weighted_average, caps[0].ceiling)

        # A document that was supplied and lists nothing IS a defect: the user
        # handed over their wiring and there is nothing in it.
        caps, score = scored(MODULE.AgentFacts(config_space_supplied=True))
        self.assertEqual([cap.condition for cap in caps], ["agent-no-varying-knobs"])
        self.assertTrue(caps[0].blocks)
        self.assertEqual(score.status, "BLOCKED")
        self.assertEqual(score.recommended_action, "vary-knobs")

    def test_the_absent_document_lines_are_true_at_both_gates(self) -> None:
        """Both spellings of one fact, not just the one that was fixed.

        The cap reason was made tense-neutral because this branch is reached at
        the CLOSE too - SKILL.md passes `--config-space` only when the enhanced
        search emitted one, so a stopped, failed, or zero-trial search lands
        here, and this module cannot tell that apart from the opening gate. The
        pillar evidence printed beside it kept saying "yet", which is the same
        claim that the search has not happened, in the line the card actually
        renders as the agent pillar's only row.

        Asserted over the word rather than the sentence: a reason string test
        pins wording, and this pins the one thing that cannot be true at both
        gates. `not yet measured` elsewhere in the file is untouched - that is a
        different check and a different claim.
        """
        pillar, caps, _ = MODULE.score_agent(MODULE.AgentFacts())
        lines = [sub.evidence for sub in pillar.subscores] + [caps[0].reason]
        for line in lines:
            with self.subTest(line=line):
                self.assertNotIn(" yet", line)
        # Still one fact, so the card still collapses it to one row.
        self.assertEqual(len(set(sub.evidence for sub in pillar.subscores)), 1)

    def test_every_other_no_knob_state_still_blocks_the_run(self) -> None:
        """Only the absent document was reclassified - the other three were not.

        Each of these is a statement about a document the user actually
        supplied, so each is a real defect with a real repair. Pinned together
        because widening the advisory branch by one condition is the cheapest
        way to break this, and nothing else would notice.
        """
        for label, facts in (
            (
                "supplied but empty",
                MODULE.AgentFacts(config_space_supplied=True),
            ),
            (
                "declared knobs, no 'wired' list",
                MODULE.AgentFacts(
                    knobs={"temperature": [0.0, 1.0]}, config_space_supplied=True
                ),
            ),
            (
                "declared knobs, explicitly nothing wired",
                MODULE.AgentFacts(
                    knobs={"temperature": [0.0, 1.0]},
                    wired=(),
                    config_space_supplied=True,
                ),
            ),
            (
                "wired knobs that cannot vary",
                MODULE.AgentFacts(
                    knobs={"temperature": [0.0]},
                    wired=("temperature",),
                    config_space_supplied=True,
                ),
            ),
        ):
            with self.subTest(state=label):
                pillar, caps, knobs = MODULE.score_agent(facts)
                blocking = [cap for cap in caps if cap.blocks]
                self.assertEqual(
                    [cap.condition for cap in blocking], ["agent-no-varying-knobs"]
                )
                score = MODULE.aggregate(
                    [pillar], caps, knobs, dict(MODULE.DEFAULT_WEIGHTS)
                )
                self.assertEqual(score.status, "BLOCKED")
                self.assertEqual(score.recommended_action, "vary-knobs")

    def test_an_advisory_cap_is_not_filed_as_a_repair_in_the_report(self) -> None:
        """The durable report may not hand a healthy project a fix to make.

        `action_kind` is keyed by CONDITION, so every `agent-no-varying-knobs`
        site shares `vary-knobs` whether or not it blocks - and the markdown
        printed "fix: `vary-knobs`" under "What limits how high this can score"
        for a project with nothing wrong, which is the line this change set out
        to stop showing. `dataset-coarse-resolution` had the same shape, so the
        rule is asserted over both rather than over the new cap alone.

        `--json` is unaffected on purpose: `action_kind` is a stable identifier
        for a machine, and the word "fix" is what a human reads.
        """
        pillars = [
            MODULE.Pillar(name=name, score=95, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        for cap in (MODULE.NOT_YET_MEASURED_CAP, MODULE.power_ceiling(15)):
            with self.subTest(cap=cap.condition):
                self.assertFalse(cap.blocks)
                report = MODULE.render_markdown(
                    MODULE.aggregate(pillars, [cap], (), dict(MODULE.DEFAULT_WEIGHTS))
                )
                self.assertIn(cap.condition, report)
                self.assertNotIn("fix: `", report)
        # A cap that really does block still names its repair there.
        blocking = MODULE.render_markdown(
            MODULE.aggregate(
                pillars, [MODULE.NOTHING_WIRED_CAP], (), dict(MODULE.DEFAULT_WEIGHTS)
            )
        )
        self.assertIn("fix: `vary-knobs`", blocking)

    def test_a_cap_reason_uses_the_term_the_glossary_defines(self) -> None:
        """A cap reason is a card line, and its vocabulary went unchecked.

        `test_the_glossary_explains_every_line_the_card_prints` enforces only
        `CHECK_DISPLAY_NAMES`, so cap prose slipped past it: a reason said
        "enhanced search" where the glossary's headword is "Baseline run vs
        enhanced run", leaving the assistant nothing to answer with for a phrase
        the user had just read off their card.

        Narrow on purpose, and says so: it covers the module-level caps and the
        one pair of spellings that actually drifted, not every noun a reason can
        contain. A checker that claimed more than it checks would be the same
        defect one layer up.
        """
        glossary = (
            Path(MODULE.__file__).parents[1] / "references" / "glossary.md"
        ).read_text(encoding="utf-8")
        flat = " ".join(glossary.split())
        self.assertIn("enhanced run", flat)
        caps = [
            value for value in vars(MODULE).values() if isinstance(value, MODULE.Cap)
        ]
        self.assertTrue(caps, "no module-level caps found, so nothing was checked")
        for cap in caps:
            with self.subTest(cap=cap.condition, reason=cap.reason):
                self.assertNotIn(
                    "enhanced search",
                    cap.reason,
                    "the glossary defines 'enhanced run'; a card line using "
                    "another spelling has no entry to answer from",
                )

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

    def test_the_card_label_matches_the_status_it_reports(self) -> None:
        """The rendered line must not contradict the JSON beside it.

        Every cap printed "BLOCKED" regardless of whether it blocked, so an
        advisory ceiling reported `status: OK` in the payload while the card
        told the reader the run was blocked - reintroducing, in the one artifact
        a human actually reads, the conflation the status field had just fixed.

        The label also stopped saying "cap". That is the word the code and the
        schema use, not one a first-time reader knows; what they need is the
        consequence, and for a ceiling that means the number it is limited to,
        because "why is this 89" is the question the line answers.

        Scored across all three pillars so the 89 ceiling is genuinely the
        binding one. Written first with a single 90/100 dataset pillar, which
        weights to an overall of 36 - so this asserted `LIMITED TO 89` on a
        36-point card, pinning as correct the very claim the sibling test below
        exists to refuse.
        """
        pillars = [
            MODULE.Pillar(name=name, score=95, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        palette = MODULE.Palette()

        def rendered(cap):
            score = MODULE.aggregate(
                pillars, caps=[cap], knobs=(), weights=dict(MODULE.DEFAULT_WEIGHTS)
            )
            return MODULE.render_card(score, palette=palette, unicode_ok=False)

        advisory = rendered(MODULE.power_ceiling(15))
        self.assertIn("LIMITED TO 89", advisory)
        self.assertNotIn("BLOCKED", advisory)

        # `power_ceiling(0)`, not `(3)`: three comparable examples is a wiring
        # check, which is a run the guide sanctions, so that cap is advisory
        # now (#149). Zero scoreable examples is the state that still blocks -
        # nothing to compare, so no result for a ceiling to bound. The string is
        # `BLOCKER` and not `PAID RUN BLOCKED` because #171 moved the holding
        # onto its own line under the score; both halves of this line changed,
        # on different branches, for different reasons.
        blocking = rendered(MODULE.power_ceiling(0))
        self.assertIn("BLOCKER", blocking)
        self.assertIn("FIX BEFORE PAID RUN", blocking)
        self.assertNotIn("LIMITED TO", blocking)

    def test_the_band_and_the_block_are_not_printed_as_one_verdict(self) -> None:
        """A grade and a gate answer different questions, so they get two lines.

        `65/100  WORKABLE  (PAID RUN BLOCKED)` put them adjacent with nothing
        joining them, and it is the ordinary walkthrough card - a generated
        dataset scores in the WORKABLE band and is blocked by
        `dataset-fully-synthetic`. Read as one verdict it contradicts itself,
        and a reader resolving it either way is wrong: the score is real and
        the block is real.

        Semantics are unchanged - which caps block and every ceiling stay
        exactly as they were - so this pins presentation only: the headline
        carries the band alone, and one BLOCKER line says the score stands,
        that something has to clear first, and what happens once it does.
        """
        pillars = [
            MODULE.Pillar(name=name, score=95, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        cap = MODULE.Cap(
            "dataset-fully-synthetic",
            65,
            "Every row was written by a model.",
        )
        score = MODULE.aggregate(
            pillars, caps=[cap], knobs=(), weights=dict(MODULE.DEFAULT_WEIGHTS)
        )
        self.assertEqual(score.overall, 65)
        self.assertEqual(score.band, "WORKABLE")
        self.assertEqual(score.status, "BLOCKED")

        card = MODULE.render_card(score, palette=MODULE.Palette(), unicode_ok=False)
        headline = card.splitlines()[0]
        self.assertIn("65/100  WORKABLE", headline)
        self.assertNotIn("BLOCK", headline)

        blocker = next(line for line in card.splitlines() if "BLOCKER" in line)
        self.assertIn("65/100 WORKABLE is what your evidence supports", blocker)
        # Names what happens next, or the keyword is only a louder tag.
        self.assertIn("run this score again", card)
        self.assertIn("the paid comparison can start", card)
        # The reason itself is not repeated up here; one problem, one statement.
        self.assertEqual(card.count("Every row was written by a model."), 1)

    def test_a_blocked_report_separates_the_band_from_the_gate(self) -> None:
        """The durable artifact carries the same separation as the card.

        In the card's vocabulary, which is the point of the second half. The
        report said "Status: PAID RUN BLOCKED" - a fourth token beside
        `BLOCKER`, `FIX BEFORE PAID RUN` and `LIMITED TO n`, and the only one
        no document defines. A reader of the durable artifact met a term the
        guide does not carry.
        """
        ceiling = MODULE.FULLY_SYNTHETIC_CEILING
        # Full confidence, so the band is the one the thresholds give rather
        # than a thin-evidence demotion of it.
        band, _ = MODULE.band_for(ceiling, 1.0, 1.0)
        pillars = [
            MODULE.Pillar(name=name, score=95, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        score = MODULE.aggregate(
            pillars,
            caps=[
                MODULE.Cap("dataset-fully-synthetic", ceiling, "Model-written rows.")
            ],
            knobs=(),
            weights=dict(MODULE.DEFAULT_WEIGHTS),
        )
        report = MODULE.render_markdown(score)
        self.assertIn(f"**{ceiling}/100 - {band}**\n", report)
        self.assertNotIn(f"**{ceiling}/100 - {band}**  ·", report)
        self.assertIn("**BLOCKER.**", report)
        self.assertIn("Both can be true at once.", report)
        # And no term the reader cannot look up. The machine-readable answer to
        # this question is `status` in the `--json` payload, not a token here.
        self.assertNotIn("PAID RUN BLOCKED", report)

    def test_the_readme_worked_example_is_the_one_the_scorer_produces(self) -> None:
        """`65/100 WORKABLE` is a claim about the scorer, made in two places.

        README.md states it as the ordinary blocked-but-good card, and the
        `blocker_lines` docstring states it again, and nothing related either to
        `FULLY_SYNTHETIC_CEILING` or to `band_for`. Both happen to be right
        today, which is exactly the state a shared value is in just before it
        drifts: re-pricing the cap or moving a band threshold leaves two
        documents describing a card the scorer no longer prints.

        Welded to the scorer rather than to each other, because a check that two
        documents agree passes when both are wrong.
        """
        ceiling = MODULE.FULLY_SYNTHETIC_CEILING
        band, _ = MODULE.band_for(ceiling, 1.0, 1.0)
        worked_example = f"{ceiling}/100 WORKABLE"
        self.assertEqual(band, "WORKABLE", "the worked example is no longer WORKABLE")

        readme = (ROOT / "README.md").read_text()
        self.assertIn(
            worked_example,
            " ".join(readme.replace("`", "").split()),
            f"README states a fully-synthetic worked example that is not "
            f"{worked_example}, which is what the scorer produces",
        )
        docstring = MODULE.blocker_lines.__doc__ or ""
        self.assertIn(
            worked_example,
            " ".join(docstring.split()),
            f"the blocker_lines docstring no longer describes {worked_example}",
        )

    def test_an_unblocked_card_says_nothing_about_a_blocker(self) -> None:
        """The line appears only when something actually blocks."""
        pillars = [
            MODULE.Pillar(name=name, score=95, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        score = MODULE.aggregate(
            pillars, caps=[], knobs=(), weights=dict(MODULE.DEFAULT_WEIGHTS)
        )
        self.assertEqual(score.status, "OK")
        card = MODULE.render_card(score, palette=MODULE.Palette(), unicode_ok=False)
        self.assertNotIn("BLOCK", card)

    def test_the_blocker_line_counts_what_actually_blocks(self) -> None:
        """The sentence agrees in number with the things it is counting.

        The line promises the reader an inventory: this many things stand
        between you and the paid run, each one marked below. That promise is
        the decision under test, so it is driven over several counts rather
        than pinned once - a card that says "one thing has to be cleared" over
        three marked lines is misinforming the reader about the size of the
        job ahead, and a reader who trusts it clears one and re-runs.

        Only blocking caps count. An advisory ceiling rides along in every
        case here precisely because it must not be counted: it lowers what the
        result may claim, it does not stand in the way of the run.
        """

        def announcement(card: str) -> str:
            """The BLOCKER paragraph as one line, wrapping undone."""
            lines = card.splitlines()
            start = next(i for i, line in enumerate(lines) if "BLOCKER" in line)
            body = []
            for line in lines[start:]:
                if not line.strip():
                    break
                body.append(line.strip())
            return " ".join(body)

        pillars = [
            MODULE.Pillar(name=name, score=95, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        # Distinct real conditions, so nothing is deduplicated away and the
        # count the card renders is the count the caller asked for.
        blockers = [
            MODULE.Cap("dataset-fully-synthetic", 65, "Every row came from a model."),
            MODULE.Cap("evaluator-invalid", 60, "It scores a wrong answer as right."),
            MODULE.Cap("dataset-tune-holdout-overlap", 55, "The splits share rows."),
        ]
        advisory = MODULE.power_ceiling(15)
        self.assertFalse(advisory.blocks)

        for count in (1, 2, 3):
            with self.subTest(blocking=count):
                score = MODULE.aggregate(
                    pillars,
                    caps=[*blockers[:count], advisory],
                    knobs=(),
                    weights=dict(MODULE.DEFAULT_WEIGHTS),
                )
                self.assertEqual(score.status, "BLOCKED")
                card = MODULE.render_card(
                    score, palette=MODULE.Palette(), unicode_ok=False
                )
                said = announcement(card)

                # What the reader is sent to find: one marked line per thing.
                marked = [
                    line
                    for line in card.splitlines()
                    if line.strip().startswith("FIX BEFORE PAID RUN")
                ]
                self.assertEqual(len(marked), count)

                if count == 1:
                    self.assertIn("one thing has to be cleared", said)
                    self.assertIn("Fix it,", said)
                    self.assertNotIn("things have", said)
                    self.assertNotIn("each marked", said)
                    self.assertNotIn("Fix them,", said)
                else:
                    self.assertIn(f"{count} things have to be cleared", said)
                    self.assertIn("Fix them,", said)
                    self.assertIn("each marked", said)
                    self.assertNotIn("one thing has", said)
                    self.assertNotIn("Fix it,", said)

    def test_a_ceiling_that_is_not_the_limit_is_not_printed_as_one(self) -> None:
        """A cap line may not state a number that describes nothing.

        The test above renders each cap ALONE, which is exactly why it passed
        while this was broken: with one cap and a high pillar, that ceiling is
        always the operative one, so an unconditioned number is right by
        construction. The combination is where it lies, and the combination is
        what a real blocked card carries.

        `overall` is the lowest of every ceiling and the weighted average, so
        the advisory 89 - the highest ceiling in the module - can never be the
        limit on a card that also carries a blocking cap. (It is no longer the
        only advisory one: `agent-no-varying-knobs` is advisory too when no
        settings document was provided, at a ceiling of 45. That one CAN be the
        binding ceiling, which is why the argument here rests on 89 being the
        highest rather than on it being the only.) It was printed there as
        `LIMITED TO 89`,
        which README.md glosses as "nothing is wrong with your setup", directly
        under a line saying something was.
        """
        # All three pillars, because a lone pillar only carries its own weight -
        # one 60/100 dataset averages to 24, below the 25 ceiling, so the cap
        # under test would not be the binding one and the setup would prove
        # nothing about the case it is named for.
        pillars = [
            MODULE.Pillar(name="dataset", score=60, confidence=1.0, subscores=()),
            MODULE.Pillar(name="evaluation", score=40, confidence=1.0, subscores=()),
            MODULE.Pillar(name="agent", score=70, confidence=1.0, subscores=()),
        ]
        blocking = MODULE.Cap("evaluator-invalid", 25, "The evaluator is broken.")
        advisory = MODULE.power_ceiling(15)
        self.assertIsNotNone(advisory)
        self.assertFalse(advisory.blocks, "power_ceiling(15) must be the advisory cap")

        def render(caps):
            score = MODULE.aggregate(
                pillars, caps=caps, knobs=(), weights=dict(MODULE.DEFAULT_WEIGHTS)
            )
            return score, MODULE.render_card(
                score, palette=MODULE.Palette(), unicode_ok=False
            )

        score, card = render([blocking, advisory])
        self.assertEqual(score.weighted_average, 56, "the cap, not the average, binds")
        self.assertEqual(score.overall, 25, "the lowest ceiling is the score")
        self.assertIn("WOULD LIMIT TO 89", card)
        self.assertNotIn("LIMITED TO 89", card)

        # The durable report carries the same number, and must not file a cap
        # that blocks nothing under the heading that says it does.
        report = MODULE.render_markdown(score)
        self.assertIn("would cap the score at 89", report)
        blocking_section = report.split("## What is blocking a trustworthy result")[1]
        self.assertNotIn("dataset-coarse-resolution", blocking_section.split("##")[0])

        # Not suppression: the ceiling still appears, because it is the limit
        # the user meets next, once the blocking condition is cleared.
        self.assertIn("89", card)

        # And where the ceiling IS the score, the flat claim is correct.
        tall = [
            MODULE.Pillar(name=name, score=95, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        at_ceiling = MODULE.aggregate(
            tall, caps=[advisory], knobs=(), weights=dict(MODULE.DEFAULT_WEIGHTS)
        )
        self.assertEqual(at_ceiling.overall, 89)
        self.assertIn(
            "LIMITED TO 89",
            MODULE.render_card(at_ceiling, palette=MODULE.Palette(), unicode_ok=False),
        )

    def test_a_dataset_that_can_resolve_is_not_capped(self) -> None:
        for count in (30, 100, 500):
            with self.subTest(count=count):
                self.assertIsNone(MODULE.power_ceiling(count))

    def test_an_unknown_size_is_not_capped(self) -> None:
        """No size reported is not the same claim as a small size."""
        self.assertIsNone(MODULE.power_ceiling(None))


class AModelWrittenAnswerKeyCannotPresentAsStrongTests(unittest.TestCase):
    """The owner's rule: synthesised material may be workable, never good.

    `GENERATED_ANSWER_KEY_CEILING` was 75 - the STRONG threshold itself - so a
    dataset whose entire ruler was written by a model could present as STRONG,
    against the module's own convention that a ceiling making a claim about a
    band sits one point below that band's edge. #159 found it and left the
    number alone because the value is the owner's call; the owner then decided
    it: "as synthesised data - no good, no strong."

    These tests pin the DECISION and never the number. Asserting `== 74` would
    pass just as happily if the bands were renumbered and 74 landed inside
    STRONG again, which is the exact defect being fixed - a literal that agreed
    with the intent on the day it was written. So each assertion asks the
    module where its own STRONG band starts and checks the ceiling against
    that.
    """

    def _generated_key_cap(self) -> object:
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
        return cap

    def test_the_ceiling_lands_below_the_band_the_module_calls_strong(self) -> None:
        """The whole guarantee, expressed against the band table itself."""
        cap = self._generated_key_cap()
        band, _limited = MODULE.band_for(cap.ceiling, 1.0, 1.0)
        self.assertLess(
            MODULE.BAND_ORDER.index(band),
            MODULE.BAND_ORDER.index("STRONG"),
            f"a fully model-written answer key is capped at {cap.ceiling}, "
            f"which the module reports as {band} - at or above STRONG, so the "
            "ceiling permits the one claim it exists to refuse",
        )

    def test_an_otherwise_perfect_project_is_held_under_strong(self) -> None:
        """End to end, on the shape that made this worth fixing.

        A project excellent on every other dimension is exactly the one the
        ceiling has to bind: a deduction would be absorbed and the run would
        report STRONG anyway. `weighted_average` is asserted to be in STRONG
        territory so the test cannot pass merely because the project was weak.
        """
        cap = self._generated_key_cap()
        pillars = [
            MODULE.combine(name, [MODULE.SubScore("x", 10.0, 10.0, True, "")])
            for name in ("agent", "dataset", "evaluation")
        ]
        score = MODULE.aggregate(pillars, [cap], [], dict(MODULE.DEFAULT_WEIGHTS))
        uncapped_band, _limited = MODULE.band_for(score.weighted_average, 1.0, 1.0)
        self.assertGreaterEqual(
            MODULE.BAND_ORDER.index(uncapped_band),
            MODULE.BAND_ORDER.index("STRONG"),
            "the fixture no longer scores into STRONG before the cap, so it "
            "cannot demonstrate that the cap is what holds it back",
        )
        self.assertLess(
            MODULE.BAND_ORDER.index(score.band),
            MODULE.BAND_ORDER.index("STRONG"),
            f"scored {score.weighted_average} before the cap and presented as "
            f"{score.band} after it",
        )

    def test_no_provenance_ceiling_reaches_the_strong_band(self) -> None:
        """The rung below the last one may not overtake it either.

        The decision is about model-supplied material, not about one condition:
        a dataset more invented than this one must not be allowed to present
        better. Reads the three ceilings off the module so a fourth rung added
        later is covered without editing this test.
        """
        strong = MODULE.BAND_ORDER.index("STRONG")
        strong_floor = min(
            score
            for score in range(101)
            if MODULE.BAND_ORDER.index(MODULE.band_for(score, 1.0, 1.0)[0]) >= strong
        )
        for name in (
            "FULLY_SYNTHETIC_CEILING",
            "MOSTLY_SYNTHETIC_CEILING",
            "GENERATED_ANSWER_KEY_CEILING",
        ):
            with self.subTest(ceiling=name):
                self.assertLess(
                    getattr(MODULE, name),
                    strong_floor,
                    f"{name} reaches the STRONG band, so generated data can "
                    "present as good rather than merely workable",
                )

def _cap_constructions() -> list[tuple[str, ast.expr]]:
    """Every `Cap(...)` written in readiness.py, as (condition, ceiling node).

    Read off the source rather than from a list kept beside it, for the reason
    the sibling remedy test already gives: a hand-maintained expected list is
    updated by whoever added the cap, so it agrees with them by construction.
    """
    source = Path(MODULE.__file__).read_text(encoding="utf-8")
    found = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Cap"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Constant)
        ):
            found.append((node.args[0].value, node.args[1]))
    return found


class TheCapOrderingIsWrittenDownAndCheckedTests(unittest.TestCase):
    """The ordering was evident, unwritten, and unenforced - so it had failed.

    Worse conditions get lower ceilings. Nothing said so and nothing checked
    it, and before #144 two overlapping unreadable-dataset conditions were
    ranked by whichever author wrote each one. These tests are the check that
    was missing; `CAP_SEVERITY_ORDER` in the module is the statement.

    They deliberately assert the ORDER and never a value. Which number a
    condition carries is the owner's call; that a new cap cannot be dropped in
    out of sequence is not.
    """

    def test_every_cap_the_scorer_can_raise_has_a_place_in_the_order(self) -> None:
        built = {condition for condition, _ceiling in _cap_constructions()}
        self.assertTrue(built, "found no Cap construction to check")
        self.assertEqual(
            built - set(MODULE.CAP_CEILING),
            set(),
            "a cap can be raised whose ceiling nothing ranks against the others",
        )
        self.assertEqual(
            set(MODULE.CAP_CEILING) - built,
            set(),
            "a ceiling is ranked for a condition the scorer never raises",
        )
        # And the two registries describe the same set of conditions. They
        # answer different questions - what to do, and how far the score may
        # rise - about exactly the same list, so a cap in one and not the other
        # is a cap that is half-declared.
        self.assertEqual(set(MODULE.CAP_CEILING), set(MODULE.ACTION_FOR_CONDITION))

    def test_an_unranked_condition_cannot_be_constructed(self) -> None:
        """Fail closed, exactly as an unmapped remedy already does."""
        MODULE.ACTION_FOR_CONDITION["a-condition-nobody-ranked"] = "get-data"
        try:
            with self.assertRaises(ValueError) as caught:
                MODULE.Cap("a-condition-nobody-ranked", 50, "reason")
        finally:
            del MODULE.ACTION_FOR_CONDITION["a-condition-nobody-ranked"]
        self.assertIn("CAP_SEVERITY_ORDER", str(caught.exception))

    def test_a_worse_condition_never_carries_a_higher_ceiling(self) -> None:
        """The order in the module is the order of the numbers."""
        ranked = [
            (group, condition, ceiling)
            for group, entries in MODULE.CAP_SEVERITY_ORDER
            for condition, ceiling in entries
        ]
        for (_, earlier, lower), (_, later, higher) in zip(ranked, ranked[1:]):
            self.assertLessEqual(
                lower,
                higher,
                f"{earlier} is ranked as worse than {later} and carries the "
                f"higher ceiling ({lower} against {higher})",
            )

    def test_the_severity_groups_do_not_reach_into_each_other(self) -> None:
        """The part of the ordering with a derivation behind it.

        Group membership is decided by what the condition destroys - no result
        at all, a result that answers the wrong question, or a sound result
        whose claim is bounded. A cap that leaves the run usable may not be
        capped as hard as one that leaves it meaningless, whatever anyone
        judges about two conditions inside one group.
        """
        bands = [
            (group, [ceiling for _condition, ceiling in entries])
            for group, entries in MODULE.CAP_SEVERITY_ORDER
        ]
        self.assertGreater(len(bands), 1, "the grouping carries no information")
        for (worse, lower), (better, higher) in zip(bands, bands[1:]):
            self.assertLess(
                max(lower),
                min(higher),
                f"the '{worse}' band reaches into '{better}': a run that is "
                f"only limited in what it may claim is capped no higher than "
                f"one that produced nothing usable",
            )

    def test_a_narrower_condition_never_outranks_the_one_it_implies(self) -> None:
        """The #144 shape, generalised.

        Where one condition's evidence strictly implies another's, the
        stricter one describes a strictly worse dataset, so it may not carry
        the higher ceiling. This is the one ordering claim that is derived
        rather than judged, and it is the one that had already failed.
        """
        for stricter, looser in MODULE.CAP_IMPLICATIONS:
            with self.subTest(stricter=stricter, looser=looser):
                self.assertIn(stricter, MODULE.CAP_CEILING)
                self.assertIn(looser, MODULE.CAP_CEILING)
                self.assertLessEqual(
                    MODULE.CAP_CEILING[stricter],
                    MODULE.CAP_CEILING[looser],
                    f"{stricter} implies {looser}, so it describes a strictly "
                    "worse dataset and cannot be the less capped of the two",
                )

    def test_every_ceiling_is_raised_by_name_and_matches_the_order(self) -> None:
        """One number, one home - the rule `action_kind` already enforces.

        A literal at a call site is how one condition acquires two ceilings:
        `dataset-fully-synthetic` is raised from two places and
        `agent-no-varying-knobs` from three, and each extra copy is a chance
        for two of them to disagree about the same condition.
        """
        for condition, ceiling_node in _cap_constructions():
            with self.subTest(condition=condition):
                self.assertIsInstance(
                    ceiling_node,
                    ast.Name,
                    f"{condition} is raised with a literal ceiling; pass the "
                    "constant named in CAP_SEVERITY_ORDER instead",
                )
                self.assertEqual(
                    getattr(MODULE, ceiling_node.id),
                    MODULE.CAP_CEILING[condition],
                    f"{condition} is raised with {ceiling_node.id}, which is "
                    "not the ceiling ranked for it",
                )

    def test_every_condition_states_whether_it_overlaps_another(self) -> None:
        """`CAP_IMPLICATIONS` was the half nothing enforced.

        A pair-only list cannot tell "checked, and it overlaps nothing" from
        "nobody looked", so a new cap that narrows an existing one and carries
        the higher ceiling shipped green - the #144 defect exactly. Every
        condition is now named on one side or the other.
        """
        paired = {condition for pair in MODULE.CAP_IMPLICATIONS for condition in pair}
        self.assertEqual(
            set(MODULE.CAP_CEILING) - paired - set(MODULE.CAP_NO_IMPLICATION),
            set(),
            "a cap states no overlap with the others, in either direction",
        )
        # And the two sides are exclusive: a condition declared to imply
        # nothing while also appearing in a pair is a contradiction, not a
        # belt-and-braces entry.
        self.assertEqual(
            paired & set(MODULE.CAP_NO_IMPLICATION),
            set(),
            "a condition both declares an implication and declares it has none",
        )

    def test_a_cap_that_states_no_overlap_cannot_be_constructed(self) -> None:
        """Fail closed, exactly as an unranked condition already does."""
        MODULE.ACTION_FOR_CONDITION["a-condition-nobody-compared"] = "get-data"
        MODULE.CAP_CEILING["a-condition-nobody-compared"] = 50
        MODULE.ROUTE_CATEGORY["a-condition-nobody-compared"] = MODULE.DIAGNOSTIC
        try:
            with self.assertRaises(ValueError) as caught:
                MODULE.Cap("a-condition-nobody-compared", 50, "reason")
        finally:
            del MODULE.ACTION_FOR_CONDITION["a-condition-nobody-compared"]
            del MODULE.CAP_CEILING["a-condition-nobody-compared"]
            del MODULE.ROUTE_CATEGORY["a-condition-nobody-compared"]
        self.assertIn("CAP_NO_IMPLICATION", str(caught.exception))


class ACapCarriesAScoreNotAnyValueTests(unittest.TestCase):
    """`condition` failed closed and the other two fields did not.

    `Cap(cond, None, ...)`, `"twenty"`, `999`, `-5` and `blocks="yes"` all
    constructed, and each reaches arithmetic that cannot say so: a ceiling of
    999 can never bind, -5 always does, a string takes `min()` down inside
    `aggregate`, and a truthy `blocks` string turns every advisory ceiling into
    a block. The type hints said all of it and nothing read them.
    """

    def test_a_ceiling_off_the_scale_is_refused(self) -> None:
        for ceiling in (999, -5, 101):
            with self.subTest(ceiling=ceiling):
                with self.assertRaises(ValueError) as caught:
                    MODULE.Cap("dataset-absent", ceiling, "reason")
                self.assertIn("0-100", str(caught.exception))

    def test_a_ceiling_that_is_not_a_number_is_refused(self) -> None:
        for ceiling in (None, "twenty", 45.5, True):
            with self.subTest(ceiling=ceiling):
                with self.assertRaises(ValueError) as caught:
                    MODULE.Cap("dataset-absent", ceiling, "reason")
                self.assertIn("non-integer ceiling", str(caught.exception))

    def test_a_non_boolean_blocks_flag_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            MODULE.Cap("dataset-absent", 20, "reason", blocks="yes")
        self.assertIn("non-boolean blocks", str(caught.exception))

    def test_a_ceiling_on_the_scale_still_constructs(self) -> None:
        """The false-red direction: every real cap must still build."""
        for condition, ceiling in MODULE.CAP_CEILING.items():
            with self.subTest(condition=condition):
                # `blocks` is not free: `ROUTE_CATEGORY` decides which values
                # are honest for this condition, so the probe passes the one
                # its route admits rather than asserting a value the route
                # refuses.
                blocks = MODULE.ROUTE_CATEGORY[condition] != MODULE.CLAIM_SCOPING
                cap = MODULE.Cap(condition, ceiling, "reason", blocks=blocks)
                self.assertEqual(cap.ceiling, ceiling)
                self.assertIs(cap.blocks, blocks)
        # And the boundaries of the scale itself, which are legitimate probes.
        self.assertEqual(MODULE.Cap("dataset-absent", 0, "reason").ceiling, 0)
        self.assertEqual(MODULE.Cap("dataset-absent", 100, "reason").ceiling, 100)


class TheDeclaredCapOrderDecidesTheRunTests(unittest.TestCase):
    """The declared order had no runtime consumer, and disagreed with one.

    `CAP_CEILING` folds the order away, and both consumers sorted by
    `(ceiling, condition)` - alphabetical at a tie. So swapping two declared
    entries changed no payload byte, and at the 45 tie the two statements
    contradicted each other outright: the declaration ranks `evaluator-timeout`
    first, and the card recommended `vary-knobs` because "a" sorts before "e".

    These assert the BEHAVIOUR the order now decides, not the registry - a test
    that reads the same tuple the code reads proves only that a tuple exists.
    """

    def _score(self, *conditions: str) -> object:
        caps = [
            MODULE.Cap(condition, MODULE.CAP_CEILING[condition], f"{condition} reason")
            for condition in conditions
        ]
        pillars = [
            MODULE.Pillar("dataset", 100, 1.0, ()),
            MODULE.Pillar("evaluation", 100, 1.0, ()),
            MODULE.Pillar("agent", 100, 1.0, ()),
        ]
        return MODULE.aggregate(
            pillars,
            caps,
            [],
            {"dataset": 0.4, "evaluation": 0.4, "agent": 0.2},
        )

    def test_the_tied_ceiling_is_broken_by_the_declared_order(self) -> None:
        """45 is carried by two conditions, and only one can be recommended."""
        self.assertEqual(
            MODULE.CAP_CEILING["evaluator-timeout"],
            MODULE.CAP_CEILING["agent-no-varying-knobs"],
            "this test exists for a tie; these two no longer tie",
        )
        for order in (
            ("evaluator-timeout", "agent-no-varying-knobs"),
            ("agent-no-varying-knobs", "evaluator-timeout"),
        ):
            with self.subTest(built_in=order):
                score = self._score(*order)
                self.assertEqual(
                    [cap.condition for cap in score.caps],
                    ["evaluator-timeout", "agent-no-varying-knobs"],
                )
                self.assertEqual(score.recommended_action, "bound-evaluator-cost")
                self.assertEqual(
                    [gap.split(":")[0] for gap in score.gaps],
                    ["evaluator-timeout", "agent-no-varying-knobs"],
                )

    def test_moving_a_condition_in_the_declaration_moves_the_recommendation(
        self,
    ) -> None:
        """The order is load-bearing: change it and the payload changes.

        This is what was missing. With the old key nothing in this method
        could be observed at all - swapping the two entries left the
        recommendation on `vary-knobs` either way.
        """
        original_rank = dict(MODULE.CAP_RANK)
        swapped = dict(original_rank)
        swapped["evaluator-timeout"], swapped["agent-no-varying-knobs"] = (
            original_rank["agent-no-varying-knobs"],
            original_rank["evaluator-timeout"],
        )
        MODULE.CAP_RANK.clear()
        MODULE.CAP_RANK.update(swapped)
        try:
            score = self._score("evaluator-timeout", "agent-no-varying-knobs")
        finally:
            MODULE.CAP_RANK.clear()
            MODULE.CAP_RANK.update(original_rank)
        self.assertEqual(score.recommended_action, "vary-knobs")

    def test_a_lower_ceiling_still_outranks_the_declared_order(self) -> None:
        """The ceiling decides severity; the rank only decides the tie."""
        score = self._score("dataset-coarse-resolution", "dataset-absent")
        self.assertEqual(
            [cap.condition for cap in score.caps],
            ["dataset-absent", "dataset-coarse-resolution"],
        )
        self.assertEqual(score.recommended_action, "get-data")

def _clean_dataset(**overrides: object) -> "MODULE.DatasetFacts":
    """A dataset with nothing wrong with it, minus whatever a test changes.

    Built once because the point of these tests is what ONE difference does, and
    a fact set assembled per test drifts into carrying two.
    """
    facts = dict(
        exists=True,
        rows=240,
        labelled_rows=240,
        tuning_rows=120,
        holdout_rows=120,
        tuning_labelled_rows=120,
        holdout_labelled_rows=120,
        difficulty_bands=("easy", "medium", "hard", "very-hard"),
        difficulty_tagged_rows=240,
        duplicate_status="PASS",
        near_duplicate_status="PASS",
        collected_rows=240,
        answerable_rows=240,
        sources=("production-support-desk",),
    )
    facts.update(overrides)
    return MODULE.DatasetFacts(**facts)


class ACapThatOnlyScopesAClaimDoesNotStopTheRunTests(unittest.TestCase):
    """The sibling of the `agent-no-varying-knobs` routing fix, one cap over.

    `blocks` answers "does this stop the run", not "is this true", and SKILL.md
    already decides which a condition is: it routes every cap by id, and a route
    asking for a creation or repair is a stop while a route that only scopes
    what the result may claim is a ceiling. Four conditions were reading their
    route wrongly.

    The one that made it visible is the guide's own finish line.
    `tests/behavioral/scenarios/partial-missing-dataset` is a real agent, a real
    evaluator, a walkthrough dataset this guide writes for a user who has none,
    and `closing_beats_opening: true` - the designed success. It closed on
    "65/100 WORKABLE (PAID RUN BLOCKED)" with `recommended_action:
    connect-real-data`, demanding real data from the one user who by
    construction has none.

    Nothing here relaxes a ceiling. 65, 70, 74 and 75 still bind, still print,
    and still hold the score down; what goes away is the stop and the repair.
    """

    def _score(self, facts: "MODULE.DatasetFacts") -> "MODULE.ReadinessScore":
        pillar, caps = MODULE.score_dataset(facts, "normalized-exact")
        others = [
            MODULE.Pillar(name=name, score=95, confidence=1.0, subscores=())
            for name in ("evaluation", "agent")
        ]
        return MODULE.aggregate(
            [pillar, *others], caps, (), dict(MODULE.DEFAULT_WEIGHTS)
        )

    def test_a_generated_walkthrough_dataset_is_bounded_not_blocked(self) -> None:
        score = self._score(
            _clean_dataset(
                collected_rows=0, synthesised_rows=240, sources=("synthetic",)
            )
        )
        self.assertEqual(
            [(cap.condition, cap.blocks) for cap in score.caps],
            [("dataset-fully-synthetic", False)],
        )
        self.assertEqual(score.status, "OK")
        self.assertEqual(score.recommended_action, "proceed")
        # The ceiling is the whole point and is untouched.
        self.assertEqual(score.overall, MODULE.FULLY_SYNTHETIC_CEILING)
        self.assertLess(score.overall, score.weighted_average)

    def test_a_mostly_generated_dataset_is_bounded_not_blocked(self) -> None:
        score = self._score(
            _clean_dataset(
                collected_rows=96,
                synthesised_rows=144,
                sources=("production", "synthetic"),
            )
        )
        self.assertEqual(
            [(cap.condition, cap.blocks) for cap in score.caps],
            [("dataset-mostly-synthetic", False)],
        )
        self.assertEqual(score.status, "OK")
        self.assertEqual(score.recommended_action, "proceed")
        self.assertEqual(score.overall, MODULE.MOSTLY_SYNTHETIC_CEILING)

    def test_a_model_written_answer_key_is_bounded_not_blocked(self) -> None:
        score = self._score(_clean_dataset(generated_answer_rows=240))
        self.assertEqual(
            [(cap.condition, cap.blocks) for cap in score.caps],
            [("dataset-generated-answer-key", False)],
        )
        self.assertEqual(score.status, "OK")
        self.assertEqual(score.recommended_action, "proceed")
        self.assertEqual(score.overall, MODULE.GENERATED_ANSWER_KEY_CEILING)

    def test_a_wiring_check_sized_dataset_is_bounded_not_blocked(self) -> None:
        score = self._score(
            _clean_dataset(
                rows=18,
                labelled_rows=18,
                tuning_rows=9,
                holdout_rows=9,
                tuning_labelled_rows=9,
                holdout_labelled_rows=9,
                collected_rows=18,
                answerable_rows=18,
            )
        )
        self.assertEqual(
            [(cap.condition, cap.blocks) for cap in score.caps],
            [("dataset-below-measurable-size", False)],
        )
        self.assertEqual(score.status, "OK")
        self.assertEqual(score.recommended_action, "proceed")
        self.assertEqual(score.overall, MODULE.WIRING_CHECK_CEILING)

    def test_a_split_with_nothing_scoreable_still_blocks(self) -> None:
        """The state the old flat `blocks=True` was actually right about.

        Every label on one side of a declared split: the aggregate count is
        non-zero so `dataset-no-expected-outputs` does not fire, and nothing can
        be compared. No other cap stops this, so this one must.
        """
        score = self._score(_clean_dataset(labelled_rows=120, tuning_labelled_rows=0))
        self.assertEqual(
            [(cap.condition, cap.blocks) for cap in score.caps],
            [("dataset-below-measurable-size", True)],
        )
        self.assertEqual(score.status, "BLOCKED")
        self.assertEqual(score.recommended_action, "get-data")

    def test_a_condition_asking_for_a_creation_or_repair_still_blocks(self) -> None:
        """The other half of the rule, so this is a partition and not a purge.

        Each route is quoted from SKILL.md's own cap-routing list, which is
        what decides the classification.
        """
        for condition, action, facts in (
            # "enter the creation dependency matrix"
            ("dataset-absent", "get-data", _clean_dataset(exists=False, rows=None)),
            # "recommend repairing a labelled working copy"
            (
                "dataset-no-expected-outputs",
                "label-data",
                _clean_dataset(
                    labelled_rows=0, tuning_labelled_rows=0, holdout_labelled_rows=0
                ),
            ),
            # "repair a disjoint split"
            (
                "dataset-tune-holdout-overlap",
                "resplit-dataset",
                _clean_dataset(split_overlap=True),
            ),
            # "repair and revalidate a working copy"
            (
                "dataset-integrity-fail",
                "repair-dataset",
                _clean_dataset(integrity_failed=True),
            ),
        ):
            with self.subTest(condition=condition):
                score = self._score(facts)
                blocking = [cap for cap in score.caps if cap.blocks]
                self.assertIn(condition, [cap.condition for cap in blocking])
                self.assertEqual(score.status, "BLOCKED")
                self.assertEqual(score.recommended_action, action)

    def test_a_bounded_dataset_is_not_handed_a_repair_to_make(self) -> None:
        """The durable report, which outlives the terminal the card printed to.

        `action_kind` is keyed by condition, so it survives on every cap in
        `--json` for a machine; what may not appear is the word "fix" over a
        state nothing is wrong with.
        """
        for facts in (
            _clean_dataset(
                collected_rows=0, synthesised_rows=240, sources=("synthetic",)
            ),
            _clean_dataset(generated_answer_rows=240),
        ):
            score = self._score(facts)
            with self.subTest(cap=score.caps[0].condition):
                report = MODULE.render_markdown(score)
                self.assertIn(score.caps[0].condition, report)
                self.assertNotIn("fix: `", report)
                self.assertNotIn(
                    "What is blocking a trustworthy result",
                    report,
                )
                card = MODULE.render_card(
                    score, palette=MODULE.Palette(), unicode_ok=False
                )
                self.assertNotIn("PAID RUN BLOCKED", card)
                self.assertIn(f"LIMITED TO {score.overall}", card)


class SilenceMustNotOutscoreAnHonestAnswerTests(unittest.TestCase):
    """`combine` renormalized over measured sub-scores, so withholding paid.

    Dropping an unmeasured check from the denominator is right when this tool
    could not look, and wrong when the run was asked for the evidence and did
    not answer: the check vanishes, and the pillar is scored over what is left.
    Measured on one 200-row project, omitting against declaring:

        --task-kind omitted   evaluation 100   declared a poor fit    83
        probe scores omitted  evaluation 100   declared a narrow spread 87
        no difficulty tag     dataset     92   one band declared        82

    Each row is the same defect: the weakest possible honest answer scored
    lower than saying nothing. These assert the ORDERING - absence at or below
    every declaration - rather than any of those numbers, because the numbers
    are arithmetic and the ordering is the rule.
    """

    def _evaluation(self, **kwargs: object) -> object:
        pillar, _caps = MODULE.score_evaluation(
            MODULE.EvaluationFacts(
                present=True,
                method="normalized-exact",
                calibration_present=True,
                checks=(
                    {"good_passes": True, "bad_fails": True, "non_constant": True},
                ),
                **kwargs,
            )
        )
        return pillar

    def test_an_undeclared_task_kind_scores_no_better_than_a_poor_fit(self) -> None:
        fits = self._evaluation(task_kind="short-answer")
        poor = self._evaluation(task_kind="code")
        omitted = self._evaluation()
        self.assertGreater(fits.score, poor.score)
        self.assertLessEqual(
            omitted.score,
            poor.score,
            "omitting --task-kind scored better than declaring a kind the "
            "method is a poor ruler for",
        )
        # And it is still reported as unchecked, which is what it is.
        task_fit = next(s for s in omitted.subscores if s.name == "task-fit")
        self.assertFalse(task_fit.measured)
        self.assertTrue(task_fit.withheld)
        self.assertLess(omitted.confidence, 1.0)

    def test_absent_probe_scores_score_no_better_than_a_narrow_spread(self) -> None:
        wide = self._evaluation(
            task_kind="short-answer", probe_scores=((1.0, 0.0),)
        )
        narrow = self._evaluation(
            task_kind="short-answer", probe_scores=((0.55, 0.45),)
        )
        omitted = self._evaluation(task_kind="short-answer")
        self.assertGreater(wide.score, narrow.score)
        self.assertLessEqual(
            omitted.score,
            narrow.score,
            "reporting no probe scores beat reporting a narrow spread",
        )

    def test_an_untagged_dataset_scores_no_better_than_one_thin_band(self) -> None:
        def dataset(**kwargs: object) -> object:
            pillar, _caps = MODULE.score_dataset(
                MODULE.DatasetFacts(
                    exists=True,
                    rows=200,
                    labelled_rows=200,
                    collected_rows=200,
                    synthesised_rows=0,
                    undeclared_rows=0,
                    answerable_rows=200,
                    generated_answer_rows=0,
                    **kwargs,
                ),
                "normalized-exact",
            )
            return pillar

        four_bands = dataset(
            difficulty_tagged_rows=200,
            difficulty_bands=("easy", "medium", "hard", "very-hard"),
        )
        one_band = dataset(difficulty_tagged_rows=200, difficulty_bands=("easy",))
        # A DECLARED zero: preflight looked at every row and found no tag. That
        # is a measurement whose value is nothing, and truthiness read it as
        # "the check never ran".
        declared_none = dataset(difficulty_tagged_rows=0, difficulty_bands=())
        never_ran = dataset(difficulty_tagged_rows=None)
        self.assertGreater(four_bands.score, one_band.score)
        self.assertLessEqual(declared_none.score, one_band.score)
        self.assertLessEqual(never_ran.score, one_band.score)
        declared = next(
            s for s in declared_none.subscores if s.name == "difficulty"
        )
        self.assertTrue(declared.measured, "a declared zero is a measurement")
        self.assertEqual(declared.value, 0.0)



class TheAnswerKeyLadderHasARungBetweenNoneAndAllTests(unittest.TestCase):
    """A ceiling one row removes is not a ceiling.

    `GENERATED_ANSWER_KEY_SHARE` was 1.0 and it was the only rung, so the cap
    turned on the last row: on one 200-row project, 200 of 200 model-written
    answers scored 74/WORKABLE/BLOCKED and 199 of 200 scored 94/EXCELLENT with
    no cap at all. The sibling ladder never had that shape -
    `MOSTLY_SYNTHETIC_SHARE` is 0.5 - and the reference promises graduated
    treatment for both.
    """

    def _caps(self, generated: int, answerable: int = 200) -> list[str]:
        _pillar, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True,
                rows=answerable,
                labelled_rows=answerable,
                collected_rows=answerable,
                synthesised_rows=0,
                undeclared_rows=0,
                answerable_rows=answerable,
                generated_answer_rows=generated,
            ),
            "normalized-exact",
        )
        return [cap.condition for cap in caps]

    def test_one_human_written_answer_no_longer_clears_the_ladder(self) -> None:
        self.assertIn("dataset-generated-answer-key", self._caps(200))
        self.assertIn("dataset-mostly-generated-answer-key", self._caps(199))
        self.assertIn("dataset-mostly-generated-answer-key", self._caps(101))
        # Half is not most, exactly as on the synthetic ladder.
        self.assertEqual(self._caps(100), [])
        self.assertEqual(self._caps(0), [])

    def test_the_middle_rung_bounds_the_claim_without_stopping_the_run(
        self,
    ) -> None:
        _pillar, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True,
                rows=200,
                labelled_rows=200,
                collected_rows=200,
                synthesised_rows=0,
                undeclared_rows=0,
                answerable_rows=200,
                generated_answer_rows=199,
            ),
            "normalized-exact",
        )
        cap = next(
            cap
            for cap in caps
            if cap.condition == "dataset-mostly-generated-answer-key"
        )
        self.assertFalse(cap.blocks)
        self.assertEqual(cap.action_kind, "review-answer-key")
        # It states the share, because "most" is the claim and the reader needs
        # the number behind it.
        self.assertIn("199 of 200", cap.reason)
        # And it obeys the owner's rule the rung above obeys: model-supplied
        # material may be workable and may not be good.
        band, _limited = MODULE.band_for(cap.ceiling, 1.0, 1.0)
        self.assertLess(
            MODULE.BAND_ORDER.index(band), MODULE.BAND_ORDER.index("STRONG")
        )


class TheRouteIsClassifiedInThreeKindsNotTwoTests(unittest.TestCase):
    """#149 partitions the routes in two, and one condition is neither.

    A route asking for a creation or a repair stops the run; a route that only
    scopes what the result may claim does not. `dataset-shape-unrecognised` is
    neither: nothing needs creating (the customer handed over a file), nothing
    is known to need repairing (a fully labelled file whose rows say
    `question`/`answer` produces this exact state), and the claim is not merely
    scoped, because a score read from zero matched rows is no result at all.

    So the partition is three, and `ROUTE_CATEGORY` is where every condition is
    classified against it.
    """

    def test_every_condition_is_classified_and_only_into_the_three(self) -> None:
        self.assertEqual(
            set(MODULE.ROUTE_CATEGORY),
            set(MODULE.ACTION_FOR_CONDITION),
            "a condition is routed and not classified, or classified and not "
            "routed",
        )
        self.assertEqual(
            set(MODULE.ROUTE_CATEGORY.values()) - MODULE.ROUTE_CATEGORIES,
            set(),
            "a fourth category was invented at a call site",
        )
        self.assertEqual(len(MODULE.ROUTE_CATEGORIES), 3)

    def test_the_third_category_is_not_empty_and_holds_the_diagnostic_route(
        self,
    ) -> None:
        """A widened two-way partition would have swallowed this one."""
        diagnostic = {
            condition
            for condition, category in MODULE.ROUTE_CATEGORY.items()
            if category == MODULE.DIAGNOSTIC
        }
        self.assertIn("dataset-shape-unrecognised", diagnostic)
        # The sweep found a second: a connected evaluator file no method could
        # be declared for was never read either.
        self.assertIn("evaluator-unresolved", diagnostic)
        # And it is genuinely a third kind, not a relabelling: the remedy asks
        # for a look, where every creation-or-repair remedy asks for a change.
        self.assertEqual(
            MODULE.ACTION_FOR_CONDITION["dataset-shape-unrecognised"],
            "read-dataset",
        )
        for condition, category in MODULE.ROUTE_CATEGORY.items():
            if category == MODULE.CREATION_OR_REPAIR:
                with self.subTest(condition=condition):
                    self.assertNotEqual(
                        MODULE.ACTION_FOR_CONDITION[condition],
                        "read-dataset",
                        "a creation-or-repair route asks only for a look",
                    )

    def test_a_diagnostic_condition_stops_the_run(self) -> None:
        """The half a claim-scoping category cannot express.

        Nothing was measured, so the run may not present a result - but the
        remedy is one look at the file, and the card says so rather than
        calling the file broken.
        """
        _, caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=False,
                dataset_supplied=True,
                unreadable_rows=3,
                unreadable_detail="3/3 rows (100.0%) are unusable",
            )
        )
        cap = caps[0]
        self.assertEqual(MODULE.ROUTE_CATEGORY[cap.condition], MODULE.DIAGNOSTIC)
        self.assertTrue(cap.blocks)
        self.assertEqual(cap.action_kind, "read-dataset")

    def test_a_condition_that_is_not_claim_scoping_cannot_be_advisory(self) -> None:
        """Fail closed: the classification decides `blocks`, not the call site."""
        for condition in ("dataset-shape-unrecognised", "dataset-absent"):
            with self.subTest(condition=condition):
                with self.assertRaises(ValueError) as caught:
                    MODULE.Cap(
                        condition,
                        MODULE.CAP_CEILING[condition],
                        "reason",
                        blocks=False,
                    )
                self.assertIn("does not block", str(caught.exception))
        # The false-red direction: a claim-scoping condition may be advisory,
        # and every condition may block.
        self.assertFalse(
            MODULE.Cap("dataset-coarse-resolution", 89, "reason", blocks=False).blocks
        )
        self.assertTrue(MODULE.Cap("dataset-shape-unrecognised", 25, "reason").blocks)

    def test_an_unclassified_condition_cannot_be_constructed(self) -> None:
        MODULE.ACTION_FOR_CONDITION["a-condition-nobody-classified"] = "get-data"
        MODULE.CAP_CEILING["a-condition-nobody-classified"] = 50
        try:
            with self.assertRaises(ValueError) as caught:
                MODULE.Cap("a-condition-nobody-classified", 50, "reason")
        finally:
            del MODULE.ACTION_FOR_CONDITION["a-condition-nobody-classified"]
            del MODULE.CAP_CEILING["a-condition-nobody-classified"]
        self.assertIn("ROUTE_CATEGORY", str(caught.exception))


class AnUnverifiableDeclarationCannotOutscoreAVerifiableOneTests(unittest.TestCase):
    """`classify_provenance` read any unknown token as collected production data.

    Measured through the whole scorer on 200 identical rows, only the token
    varying: no token at all scored 65 WORKABLE and BLOCKED; the truthful
    `synthetic` scored 65 WORKABLE and BLOCKED; `crm-export` scored 95
    EXCELLENT and OK; and so did `zzz`. Three junk characters in a field
    nothing checks were worth thirty points and the difference between a
    blocked run and an excellent one.

    The rule implemented is not "refuse unknown tokens" - customer vocabulary
    is unknowable in advance, and `crm-export` is a real collected source that
    failing closed would punish for honesty. It is that an unverifiable
    declaration must not outscore a verifiable one, so an unreadable token
    scores what a silent row scores and never above a row that declares itself
    generated.
    """

    def _points(self, **counts: int) -> float:
        points, _evidence, _caps = MODULE.score_provenance(
            MODULE.DatasetFacts(exists=True, rows=200, labelled_rows=200, **counts)
        )
        return points

    def test_an_unreadable_token_scores_where_silence_scores(self) -> None:
        unreadable = self._points(undeclared_rows=200)
        generated = self._points(synthesised_rows=200)
        collected = self._points(collected_rows=200)
        self.assertLessEqual(
            unreadable,
            generated,
            "a token nothing can verify outscored an honest declaration",
        )
        self.assertLess(unreadable, collected)

    def test_the_ceiling_an_unreadable_token_carries_is_the_undeclared_one(
        self,
    ) -> None:
        _points, _evidence, caps = MODULE.score_provenance(
            MODULE.DatasetFacts(
                exists=True,
                rows=200,
                labelled_rows=200,
                undeclared_rows=200,
                unrecognised_sources=("crm-export",),
            )
        )
        self.assertEqual(
            [cap.condition for cap in caps], ["dataset-undeclared-provenance"]
        )
        self.assertEqual(caps[0].action_kind, "declare-data-provenance")

    def test_the_tokens_are_named_rather_than_silently_demoted(self) -> None:
        _points, evidence, _caps = MODULE.score_provenance(
            MODULE.DatasetFacts(
                exists=True,
                rows=200,
                labelled_rows=200,
                undeclared_rows=200,
                unrecognised_sources=("crm-export",),
            )
        )
        self.assertIn("crm-export", evidence)
        self.assertIn("could not verify", evidence)
        # And never the older claim, which said the opposite of what now
        # happens to those rows.
        self.assertNotIn("treated as collected", evidence)


class TheCountFreePayloadHasOneReadingTests(unittest.TestCase):
    """Forty lines of a second provenance implementation, on a void rationale.

    `declares_no_provenance`, `COUNTERFACTUAL_SOURCE`, the `if not counted:`
    ladder and the `else` branch of `provenance_assumption` existed for a
    preflight JSON written before the row counts did. `emit_dataset_provenance`
    emits all three counts together for every dataset with a row in it, and
    this repository has published nothing that could have been written before
    that - so the machinery guarded a payload that has never existed.
    """

    def test_the_removed_machinery_is_gone_rather_than_relocated(self) -> None:
        for name in ("declares_no_provenance", "COUNTERFACTUAL_SOURCE"):
            with self.subTest(name=name):
                self.assertFalse(
                    hasattr(MODULE, name),
                    f"{name} is still here; the second implementation was "
                    "moved rather than removed",
                )

    def test_no_row_count_is_read_as_no_statement_about_any_row(self) -> None:
        points, _evidence, caps = MODULE.score_provenance(
            MODULE.DatasetFacts(
                exists=True, rows=200, labelled_rows=200, sources=("collected",)
            )
        )
        # `sources` no longer decides anything: an unverifiable declaration is
        # what it is whether it is a word this script knows or not.
        self.assertEqual(points, MODULE.UNDECLARED_ROW_POINTS)
        self.assertEqual(
            [cap.condition for cap in caps], ["dataset-undeclared-provenance"]
        )

    def test_preflight_s_own_all_generated_statement_is_still_read(self) -> None:
        """The false-red direction: the normalization is not a blanket."""
        points, _evidence, caps = MODULE.score_provenance(
            MODULE.DatasetFacts(
                exists=True, rows=200, labelled_rows=200, synthetic=True
            )
        )
        self.assertEqual(points, MODULE.SYNTHESISED_ROW_POINTS)
        self.assertEqual([cap.condition for cap in caps], ["dataset-fully-synthetic"])
class ADiversityQuestionWithNoSubjectIsNotAnUnrunCheckTests(unittest.TestCase):
    """`score_provenance` gets the method's context on the adjacent line; this did not.

    Under a reference-free judge there are no expected outputs, so "does one
    expected output dominate" has no subject. Scored as "did not run", it put
    the whole sub-score into the unmeasured branch and took the near-duplicate
    PASS beside it down too: a 40-row input-only dataset measured DATASET
    81/100 (3 of 5 checks) before that branch existed and 70/100 (2 of 5)
    after - a false red on a configuration the guide fully supports.
    """

    def _sub(self, uses_expected_outputs: bool) -> object:
        return MODULE.diversity_subscore(
            MODULE.DatasetFacts(
                exists=True,
                rows=40,
                labelled_rows=0,
                duplicate_status="PASS",
                near_duplicate_status="PASS",
                answer_dominance_status=None,
            ),
            uses_expected_outputs=uses_expected_outputs,
        )

    def test_a_reference_free_run_keeps_the_check_that_did_run(self) -> None:
        sub = self._sub(False)
        self.assertTrue(sub.measured)
        self.assertEqual(sub.value, sub.maximum)

    def test_it_says_nothing_about_expected_outputs_it_has_none_of(self) -> None:
        sub = self._sub(False)
        self.assertNotIn("expected output", sub.evidence)
        self.assertNotIn("no single answer", sub.evidence)
        self.assertNotIn("not checked", sub.evidence)

    def test_a_reference_based_run_still_refuses_to_call_it_clean(self) -> None:
        """The false-red direction, and the defect this must not undo.

        With expected outputs the question DOES apply, and an absent dominance
        status still means nothing looked - so the sub-score stays unmeasured
        rather than claiming a spread nobody examined.
        """
        sub = self._sub(True)
        self.assertFalse(sub.measured)
        self.assertIn("not checked", sub.evidence)


class ACheckThatCouldNotAnswerIsNotAPassTests(unittest.TestCase):
    """The un-ported half of `diversity_subscore`'s own rule.

    Two lines in the adapter read `statuses.get(name) == "FAIL"`, so every
    status that is not that word - a SKIP, or one this version has never heard
    of - came out as the clean answer and fed a cap that then did not fire.
    """

    def _facts(self, **records: str) -> object:
        payload = [
            {
                "check": "dataset-provenance",
                "status": "PASS",
                "metrics": {
                                "rows": 40,
                                "labelled_rows": 40,
                                # Emitted together by preflight.py, and
                                # required since #161 - an absent count is
                                # refused rather than read as zero.
                                "collected_rows": 40,
                                "synthesised_rows": 0,
                                "undeclared_rows": 0,
                                "generated_answer_rows": 0,
                                "answerable_rows": 40,
                            },
            }
        ]
        payload.extend(
            {"check": check.replace("_", "-"), "status": status, "metrics": {}}
            for check, status in records.items()
        )
        return MODULE.dataset_facts_from_preflight(payload)

    def test_a_skipped_split_check_is_refused_rather_than_read_as_disjoint(
        self,
    ) -> None:
        for check in ("dataset-split", "dataset-ids"):
            with self.subTest(check=check):
                with self.assertRaises(MODULE.PreflightInputError) as caught:
                    self._facts(**{check.replace("-", "_"): "SKIP"})
                self.assertIn(check, str(caught.exception))

    def test_an_absent_record_is_still_read_as_the_question_not_arising(
        self,
    ) -> None:
        """The false-red direction, and why absence is not the same statement.

        `check_dataset` emits `dataset-split` only where a split can be looked
        for - an unlabelled dataset legitimately carries no record - so absence
        means the question did not arise. Refusing it would break every such
        dataset for a reading that is honest there.
        """
        facts = self._facts()
        self.assertFalse(facts.split_overlap)
        self.assertFalse(facts.integrity_failed)

    def test_a_real_failure_still_reads_as_a_failure(self) -> None:
        facts = self._facts(dataset_split="FAIL", dataset_ids="FAIL")
        self.assertTrue(facts.split_overlap)
        self.assertTrue(facts.integrity_failed)


class TheRemedyIsMachineReadableTests(unittest.TestCase):
    """traigent-first-run#98 - the payload named the problem, never the fix."""

    def test_every_condition_the_scorer_can_raise_declares_a_remedy(self) -> None:
        """Read off the module, not off a list a reader has to keep in step.

        A hand-maintained expected list would pass while a newly added cap went
        unmapped, because the same person updates both.
        """
        source = Path(MODULE.__file__).read_text(encoding="utf-8")
        built = {
            node.args[0].value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Cap"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        }
        self.assertTrue(built, "found no Cap construction to check")
        self.assertEqual(
            built - set(MODULE.ACTION_FOR_CONDITION),
            set(),
            "a cap can be raised whose remedy nothing declares",
        )
        # And the other direction: a mapping nothing raises is dead, and dead
        # vocabulary is what a consumer matches against and never sees.
        self.assertEqual(
            set(MODULE.ACTION_FOR_CONDITION) - built,
            set(),
            "a remedy is declared for a condition the scorer never raises",
        )

    def test_an_unmapped_condition_cannot_be_constructed(self) -> None:
        """Fail closed: a new cap without a remedy raises where it is written."""
        with self.assertRaises(ValueError) as caught:
            MODULE.Cap("a-condition-nobody-mapped", 50, "reason")
        self.assertIn("ACTION_FOR_CONDITION", str(caught.exception))

    def test_the_vocabulary_is_closed(self) -> None:
        """Every emitted remedy is a member, including `proceed`."""
        for condition in MODULE.ACTION_FOR_CONDITION:
            cap = MODULE.Cap(condition, 50, "reason")
            self.assertIn(cap.action_kind, MODULE.ACTION_KINDS)
        self.assertIn(MODULE.PROCEED, MODULE.ACTION_KINDS)

    def test_one_condition_cannot_carry_two_remedies(self) -> None:
        """The reason the table is keyed by condition rather than per call site.

        `dataset-fully-synthetic` is raised from two places and
        `agent-no-varying-knobs` from three; a remedy passed at each site is a
        chance for two of them to disagree about the same condition.
        """
        for condition in ("dataset-fully-synthetic", "agent-no-varying-knobs"):
            with self.subTest(condition=condition):
                kinds = {
                    MODULE.Cap(condition, ceiling, "reason").action_kind
                    for ceiling in (45, 65, 70)
                }
                self.assertEqual(len(kinds), 1)

    def test_only_a_blocking_cap_displaces_proceed(self) -> None:
        """An advisory ceiling stops nothing, so it recommends nothing."""
        pillars = [
            MODULE.Pillar(name=name, score=60, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]

        def action_for(caps):
            return MODULE.aggregate(
                pillars, caps, [], dict(MODULE.DEFAULT_WEIGHTS)
            ).recommended_action

        advisory = MODULE.power_ceiling(15)
        self.assertFalse(advisory.blocks)
        self.assertEqual(action_for([]), MODULE.PROCEED)
        self.assertEqual(action_for([advisory]), MODULE.PROCEED)

        # Among blocking caps the lowest ceiling wins - the one setting the
        # score - not the first one supplied and not the alphabetical first.
        low = MODULE.Cap("evaluator-invalid", 25, "broken")
        high = MODULE.Cap("dataset-tune-holdout-overlap", 50, "overlapping")
        self.assertEqual(action_for([high, low, advisory]), "repair-evaluator")
        self.assertEqual(action_for([low, high]), "repair-evaluator")

    def test_the_payload_carries_both_forms(self) -> None:
        """The JSON a consumer reads, not the objects behind it."""
        pillars = [
            MODULE.Pillar(name=name, score=60, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        score = MODULE.aggregate(
            pillars,
            [MODULE.Cap("evaluator-invalid", 25, "broken")],
            [],
            dict(MODULE.DEFAULT_WEIGHTS),
        )
        payload = json.loads(json.dumps(asdict(score), sort_keys=True))
        self.assertEqual(payload["recommended_action"], "repair-evaluator")
        self.assertEqual(payload["caps"][0]["action_kind"], "repair-evaluator")
        self.assertEqual(
            payload["schema_version"],
            2,
            "a consumer must be able to tell 'emits no remedy' from 'has none'",
        )


class NumbersOnTheCardMustDescribeTheRunTests(unittest.TestCase):
    """Both defects found by reading the module end to end after #93.

    Same class as #93 in a different place: a number printed beside other
    numbers that a reader who can add cannot reconcile with them.
    """

    def _agent(self, knobs, wired, max_trials):
        pillar, _, _ = MODULE.score_agent(
            MODULE.AgentFacts(
                knobs=knobs,
                wired=wired,
                max_trials=max_trials,
            )
        )
        return next(sub for sub in pillar.subscores if sub.name == "search-space")

    def test_an_excluded_knob_does_not_inflate_the_configuration_count(self) -> None:
        """`seed` is excluded from scoring, so it cannot be inside the count.

        Sweeping a seed re-runs a configuration; it does not make a new one.
        The count used to multiply over EVERY knob, so two two-valued knobs
        printed "24 combinations". Two of those knobs make four.
        """
        two_knobs = {"temperature": [0.0, 1.0], "model": ["a", "b"]}
        with_seed = self._agent(
            {**two_knobs, "seed": [1, 2, 3, 4, 5, 6]},
            ("temperature", "model", "seed"),
            12,
        )
        self.assertIn("your space has 4 distinct configurations", with_seed.evidence)
        self.assertNotIn("24 distinct", with_seed.evidence)
        # Not hidden either. The seed sweep is what the budget is being spent
        # on, so it is named and it is visible in the reachable count: twelve
        # trials at six repeats each reach two of the four.
        self.assertIn("try up to 2 of them", with_seed.evidence)
        self.assertIn("each repeated 6 times over 'seed'", with_seed.evidence)

        # A space with nothing excluded reaches all four.
        plain = self._agent(two_knobs, ("temperature", "model"), 12)
        self.assertEqual(
            plain.evidence,
            "your space has 4 distinct configurations; this run will try up to "
            "4 of them; 8 more would reach the 12 this guide scores as a "
            "complete search",
        )

    def test_the_budget_penalty_still_counts_the_trials_seed_really_costs(
        self,
    ) -> None:
        """Excluding `seed` from the COUNT must not exclude it from the SPEND.

        The SDK runs every configuration once per seed, so a 4-configuration
        space swept over 6 seeds costs 24 trials. A twelve-trial budget
        therefore buys two configurations, not twelve - `configuration_budget`
        is where the two facts are held together, and scoring against the raw
        trial count would trade one wrong number for another.
        """
        swept = self._agent(
            {"temperature": [0.0, 1.0], "model": ["a", "b"], "seed": list(range(6))},
            ("temperature", "model", "seed"),
            12,
        )
        unswept = self._agent(
            {"temperature": [0.0, 1.0], "model": ["a", "b"]},
            ("temperature", "model"),
            12,
        )
        self.assertLess(
            swept.value,
            unswept.value,
            "6 seeds against a 12-trial budget reaches a quarter of the space, "
            "and must still say so",
        )
        self.assertEqual(MODULE.configuration_budget(12, 6), 2)
        self.assertEqual(MODULE.configuration_budget(12, 1), 12)
        self.assertIsNone(MODULE.configuration_budget(None, 6))

    def test_a_ceiling_costing_nothing_is_not_the_first_thing_to_fix(self) -> None:
        """The ranked gaps are documented as ordered by cost, so order by cost.

        Every cap was ranked at one weight and ties broke alphabetically, so
        `dataset-coarse-resolution` sorted above `evaluator-invalid` on a card
        the evaluator had set to 25 - telling the user to fix, first, the one
        condition that would not move the number.
        """
        pillars = [
            MODULE.Pillar(name=name, score=60, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        blocking = MODULE.Cap("evaluator-invalid", 25, "The evaluator is broken.")
        advisory = MODULE.power_ceiling(15)
        score = MODULE.aggregate(
            pillars,
            caps=[blocking, advisory],
            knobs=(),
            weights=dict(MODULE.DEFAULT_WEIGHTS),
        )
        self.assertEqual(score.overall, 25)
        self.assertTrue(score.gaps[0].startswith("evaluator-invalid"))
        self.assertTrue(score.gaps[1].startswith("dataset-coarse-resolution"))

    def test_the_blocking_cap_that_sets_the_score_leads_the_other_blockers(
        self,
    ) -> None:
        """The same defect, between two caps that both block.

        Ranking caps on `blocks` alone closed the advisory-versus-blocking case
        and left this one identical: two blocking caps tie, the tie breaks
        alphabetically, and `dataset-tune-holdout-overlap` (50) leads a card
        that `evaluator-invalid` (25) has actually set. Fixing the reported
        instance and not the class is how this list got re-reported once
        already.
        """
        pillars = [
            MODULE.Pillar(name=name, score=60, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        score = MODULE.aggregate(
            pillars,
            caps=[
                MODULE.Cap("evaluator-invalid", 25, "The evaluator is broken."),
                MODULE.Cap(
                    "dataset-tune-holdout-overlap",
                    50,
                    "Tuning and holdout share examples.",
                ),
            ],
            knobs=(),
            weights=dict(MODULE.DEFAULT_WEIGHTS),
        )
        self.assertEqual(score.overall, 25)
        self.assertTrue(score.gaps[0].startswith("evaluator-invalid"))
        self.assertTrue(score.gaps[1].startswith("dataset-tune-holdout-overlap"))

    def test_collect_gaps_requires_the_score_it_ranks_against(self) -> None:
        """A default would silently restore the flat ordering."""
        with self.assertRaises(TypeError):
            MODULE.collect_gaps([], (), ())  # type: ignore[call-arg]

    def test_a_ceiling_that_is_the_score_still_leads_the_list(self) -> None:
        """Demoting an inactive ceiling must not demote an active one."""
        pillars = [
            MODULE.Pillar(name=name, score=95, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        score = MODULE.aggregate(
            pillars,
            caps=[MODULE.power_ceiling(15)],
            knobs=(),
            weights=dict(MODULE.DEFAULT_WEIGHTS),
        )
        self.assertEqual(score.overall, 89)
        self.assertTrue(score.gaps[0].startswith("dataset-coarse-resolution"))


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

    def test_zero_reference_answers_do_not_become_nothing_to_score_for_a_judge(
        self,
    ) -> None:
        facts = MODULE.DatasetFacts(
            exists=True,
            rows=100,
            labelled_rows=0,
            collected_rows=100,
        )
        reference_based, exact_caps = MODULE.score_dataset(facts, "exact")
        reference_free, judge_caps = MODULE.score_dataset(facts, "llm-judge-rubric")

        self.assertIn(
            "dataset-no-expected-outputs",
            {cap.condition for cap in exact_caps},
        )
        self.assertNotIn(
            "dataset-no-expected-outputs",
            {cap.condition for cap in judge_caps},
        )
        labels = next(sub for sub in reference_free.subscores if sub.name == "labels")
        power = next(sub for sub in reference_free.subscores if sub.name == "power")
        self.assertFalse(labels.measured)
        self.assertIn("reference-free evaluator", labels.evidence)
        self.assertIn("100 examples", power.evidence)
        self.assertGreater(
            power.value,
            next(sub.value for sub in reference_based.subscores if sub.name == "power"),
        )

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
        # 5 scoreable of the 50 tuning rows: the judge must be credited the
        # whole tuning split, the reference-based method only its labelled part.
        self.assertIn("5 scoreable", power_of(reference_based).evidence)
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

    def test_reference_free_method_ignores_an_optional_generated_answer_key(
        self,
    ) -> None:
        facts = MODULE.DatasetFacts(
            exists=True,
            rows=100,
            labelled_rows=100,
            collected_rows=100,
            answerable_rows=100,
            generated_answer_rows=100,
        )
        reference_based, exact_caps = MODULE.score_dataset(facts, "exact")
        reference_free, judge_caps = MODULE.score_dataset(facts, "llm-judge-rubric")

        self.assertIn(
            "dataset-generated-answer-key",
            {cap.condition for cap in exact_caps},
        )
        self.assertNotIn(
            "dataset-generated-answer-key",
            {cap.condition for cap in judge_caps},
        )
        labels = next(sub for sub in reference_free.subscores if sub.name == "labels")
        provenance = next(
            sub for sub in reference_free.subscores if sub.name == "provenance"
        )
        exact_provenance = next(
            sub for sub in reference_based.subscores if sub.name == "provenance"
        )
        self.assertFalse(labels.measured)
        self.assertIn("100 present but unused", labels.evidence)
        self.assertEqual(provenance.value, 10.0)
        self.assertEqual(exact_provenance.value, 6.0)
        self.assertIn("present but unused by this evaluator", provenance.evidence)


if __name__ == "__main__":
    unittest.main()


class TheCardSpeaksTheUsersLanguageTests(unittest.TestCase):
    """The card is the most-read artifact and it printed internal check ids.

    SKILL.md: "Keep internal check IDs, SDK internals, and optimization jargon
    out of user-facing progress." Cap condition ids were kept out; the twelve
    sub-score names were printed verbatim, and nine of them appeared in no
    glossary entry - so a reader who wanted to know what "power" meant had
    nowhere to look it up.
    """

    def all_check_names(self) -> set[str]:
        """Read off the module, so a new check cannot be added unnamed."""
        source = Path(MODULE.__file__).read_text(encoding="utf-8")
        return {
            node.args[0].value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "SubScore"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        }

    def test_every_check_has_a_plain_language_name(self) -> None:
        names = self.all_check_names()
        self.assertTrue(names, "found no SubScore to check")
        self.assertEqual(
            names - set(MODULE.CHECK_DISPLAY_NAMES),
            set(),
            "a check would print its internal name on the card",
        )
        # And nothing named that is never printed: a dead entry reads as
        # coverage while translating nothing.
        self.assertEqual(set(MODULE.CHECK_DISPLAY_NAMES) - names, set())

    def test_no_internal_check_name_reaches_the_card(self) -> None:
        """The rule, tested on the artifact rather than on the table."""
        pillars = [
            MODULE.Pillar(
                name=name,
                score=50,
                confidence=1.0,
                subscores=tuple(
                    MODULE.SubScore(check, 1.0, 2.0, True, f"evidence for {index}")
                    for index, check in enumerate(sorted(self.all_check_names()))
                ),
            )
            for name in ("dataset", "evaluation", "agent")
        ]
        card = MODULE.render_card(
            MODULE.aggregate(pillars, [], (), dict(MODULE.DEFAULT_WEIGHTS)),
            palette=MODULE.Palette(),
            unicode_ok=False,
        )
        for check, shown in MODULE.CHECK_DISPLAY_NAMES.items():
            with self.subTest(check=check):
                self.assertIn(shown, card)
                # Skipped when the internal name is a word inside its own plain
                # label - "range of difficulty" contains "difficulty", and
                # forbidding that would forbid the clearest wording available.
                # What must not appear is the internal name standing alone as a
                # label, which is what the column check below tests.
                if check not in shown:
                    self.assertNotIn(check, card)
        labels = [
            line.split("  ")[0].strip(" .!?OK")
            for line in card.splitlines()
            if line.startswith("    ")
        ]
        self.assertEqual(
            [label for label in labels if label in MODULE.CHECK_DISPLAY_NAMES],
            [],
            "an internal check name is printed as a label",
        )

    def test_the_glossary_explains_every_line_the_card_prints(self) -> None:
        """So there is a prepared answer when the user asks what one means."""
        glossary = (
            Path(MODULE.__file__).parents[1] / "references" / "glossary.md"
        ).read_text(encoding="utf-8")
        flat = " ".join(glossary.split())
        for shown in sorted(set(MODULE.CHECK_DISPLAY_NAMES.values())):
            with self.subTest(line=shown):
                self.assertIn(
                    shown,
                    flat,
                    f"the card prints '{shown}' and the glossary does not "
                    "explain it, so the assistant has nothing to answer with",
                )

    def test_one_fact_prints_as_one_line(self) -> None:
        """An agent with no config space produced three identical rows.

        One fact, three chances to read it as three separate things to fix.
        """
        pillar = MODULE.Pillar(
            name="agent",
            score=0,
            confidence=0.35,
            subscores=(
                MODULE.SubScore(
                    "coverage",
                    0.0,
                    25.0,
                    False,
                    "no settings document was provided to this score",
                ),
                MODULE.SubScore(
                    "knob-count",
                    0.0,
                    35.0,
                    True,
                    "no settings document was provided to this score",
                ),
                MODULE.SubScore(
                    "variation",
                    0.0,
                    40.0,
                    False,
                    "no settings document was provided to this score",
                ),
            ),
        )
        card = MODULE.render_card(
            MODULE.aggregate([pillar], [], (), dict(MODULE.DEFAULT_WEIGHTS)),
            palette=MODULE.Palette(),
            unicode_ok=False,
        )
        self.assertEqual(
            card.count("no settings document was provided to this score"), 1
        )

    def test_a_single_check_keeps_its_label(self) -> None:
        """Collapsing needs repetition; one check has none to collapse.

        A pillar with one check also has exactly one distinct evidence string,
        so the naive rule swallowed its label and printed the bare finding -
        losing the only thing that said which question it answered.
        """
        pillar = MODULE.Pillar(
            name="dataset",
            score=50,
            confidence=1.0,
            subscores=(MODULE.SubScore("power", 1.0, 25.0, True, "some evidence"),),
        )
        card = MODULE.render_card(
            MODULE.aggregate([pillar], [], (), dict(MODULE.DEFAULT_WEIGHTS)),
            palette=MODULE.Palette(),
            unicode_ok=False,
        )
        self.assertIn("examples to compare on", card)


class TheScoreStatesWhatItKnowsTests(unittest.TestCase):
    """A card line is a claim, and a claim has to be one the scorer can make.

    "The evaluator was not calibrated" is a statement about the user's project.
    The only thing establishing it was that no calibration payload reached this
    scorer - which is also true of an evaluator calibrated last week, or
    calibrated in a run whose JSON nobody passed to `--calibration`.

    This module already draws the distinction correctly elsewhere: "no rows
    carry a difficulty tag - spread is unverified, not absent".
    """

    def calibration_line(self, facts) -> str:
        pillar, _ = MODULE.score_evaluation(facts)
        return next(s.evidence for s in pillar.subscores if s.name == "calibration")

    def test_rendered_score_names_evidence_coverage_and_its_local_scope(self) -> None:
        pillars = [
            MODULE.combine(
                name,
                [MODULE.SubScore("x", 5.0, 10.0, True, "observed locally")],
            )
            for name in ("agent", "dataset", "evaluation")
        ]
        score = MODULE.aggregate(pillars, [], (), dict(MODULE.DEFAULT_WEIGHTS))
        card = MODULE.render_card(score, palette=MODULE.PLAIN, unicode_ok=False)
        report = MODULE.render_markdown(score)

        self.assertIn("Local pre-run planning estimate", card)
        self.assertNotIn("measures this properly", card.casefold())
        self.assertIn("Evidence coverage", report)
        self.assertNotIn("Measured confidence", report)

    def test_an_absent_payload_is_reported_as_an_absent_payload(self) -> None:
        facts = MODULE.evaluation_facts_from_calibration(
            None, method="execution", task_kind="code-sql"
        )
        line = self.calibration_line(facts)
        self.assertIn("provided", line)
        self.assertNotIn("was not calibrated", line)

    def test_a_calibration_that_ran_is_never_called_absent(self) -> None:
        """The case that made the old wording self-contradicting.

        A calibration that timed out emits a payload with no cases, so the card
        said the evaluator had never been calibrated beside an
        `evaluator-timeout` cap - which can only fire when it ran.
        """
        facts = MODULE.evaluation_facts_from_calibration(
            {"timed_out": True, "cases": [], "passed": False},
            method="llm-judge-rubric",
            task_kind="free-text",
        )
        pillar, caps = MODULE.score_evaluation(facts)
        line = next(s.evidence for s in pillar.subscores if s.name == "calibration")
        self.assertIn("evaluator-timeout", [cap.condition for cap in caps])
        self.assertIn("did not finish", line)
        self.assertNotIn("was not calibrated", line)

    def test_ran_with_no_checks_is_distinct_from_never_ran(self) -> None:
        """Three states, three sentences - collapsing them loses the fact."""
        supplied_empty = self.calibration_line(
            MODULE.evaluation_facts_from_calibration(
                {"cases": [], "passed": False}, method="execution", task_kind="code-sql"
            )
        )
        never_ran = self.calibration_line(
            MODULE.evaluation_facts_from_calibration(
                None, method="execution", task_kind="code-sql"
            )
        )
        self.assertIn("ran but reported no checks", supplied_empty)
        self.assertNotEqual(supplied_empty, never_ran)

    def test_no_unmeasured_line_claims_something_was_not_done(self) -> None:
        """The class, not the instance: an unmeasured check reports its input.

        An unmeasured check knows one thing - that it had nothing to read. Any
        wording asserting the user did not do something is a claim the absence
        of an input cannot support.
        """
        # A CLASS, not a list of instances - and asserted on what the scorer
        # PRODUCES, not on what its source spells.
        #
        # Two earlier versions failed for the same reason. #121 hardcoded two
        # calibration phrases, so the identical defect on the agent pillar
        # walked past. Widening that list did not help either: the test parsed
        # the module for literal `SubScore(...)` arguments, and the agent pillar
        # builds its evidence in a variable - so the string was never in the
        # parser's reach and the check reported green while the defect shipped.
        #
        # It drives the real states and reads the evidence they emit.
        forbidden = (
            "was not calibrated",
            "has not been calibrated",
            "no knobs declared",
            "knobs are not declared",
        )
        produced: list[str] = []

        for facts in (
            MODULE.AgentFacts(),
            MODULE.AgentFacts(config_space_supplied=True),
            MODULE.AgentFacts(
                knobs={"temperature": [0.0, 1.0]}, config_space_supplied=True
            ),
        ):
            pillar, _, _ = MODULE.score_agent(facts)
            produced.extend(sub.evidence for sub in pillar.subscores)

        for payload in (
            None,
            {"cases": [], "passed": False},
            {"timed_out": True, "cases": [], "passed": False},
        ):
            facts = MODULE.evaluation_facts_from_calibration(
                payload, method="execution", task_kind="code-sql"
            )
            pillar, _ = MODULE.score_evaluation(facts)
            produced.extend(sub.evidence for sub in pillar.subscores)

        self.assertTrue(produced, "drove no state, so this proves nothing")
        for evidence in produced:
            for phrase in forbidden:
                with self.subTest(evidence=evidence[:40], phrase=phrase):
                    self.assertNotIn(phrase, evidence)

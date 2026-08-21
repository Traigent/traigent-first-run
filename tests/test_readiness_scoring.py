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
from dataclasses import asdict, replace
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

        #197 gave that zero a condition of its own. It travelled as a second
        reading of `dataset-below-measurable-size`, told apart from the first
        only by a runtime flag, which is what let one remedy mean both "stop"
        and "carry on" about the same instruction. The finding this fixture
        reaches is unchanged and so is the ceiling firing at all; what moved is
        the name, the remedy, and the number - `resplit-dataset` at 50, because
        the rows here are real, labelled and readable and it is the line drawn
        through them that leaves nothing to compare on.
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
        raised = {cap.condition: cap for cap in caps}
        self.assertIn("dataset-tuning-split-empty", raised)
        cap = raised["dataset-tuning-split-empty"]
        self.assertTrue(cap.blocks)
        self.assertEqual(cap.action_kind, "resplit-dataset")
        self.assertEqual(cap.ceiling, MODULE.TUNING_SPLIT_EMPTY_CEILING)
        # And it does not also arrive as the small-dataset finding, which is
        # the two-FIX-lines-for-one-fact defect this file already fixed once.
        self.assertNotIn("dataset-below-measurable-size", raised)

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

        A check that did not run used to keep its full points and a sentence
        beginning "no repeated questions" - a clean result nobody established.
        Parameterised over all three checks so
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
                exists=True,
                rows=100,
                labelled_rows=100,
                tuning_rows=20,
                holdout_rows=80,
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
        unscoreable_holdout = next(s for s in one_sided.subscores if s.name == "power")
        self.assertEqual(unscoreable_holdout.value, 22.0)
        # "held-out", not "held-back": `THIRD_NOUNS` in test_skill_package bans
        # the prose form "held-back" from every bundled script and names this
        # evidence line as the defect behind the ban. Only the split's settled
        # name changed here; the guarantee is the same one.
        self.assertIn(
            "none of the held-out rows can be scored", unscoreable_holdout.evidence
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
# placeholder value to substitute first - the three behaviour knobs are binary
# and temperature has one task-selected value, so the space is fixed before either run.
WALKTHROUGH_CONFIG_SPACE = {
    "knobs": {
        "model": ["provider/current", "provider/alternative", "provider/strong"],
        "prompt_style": ["plain", "structured"],
        "thinking_shape": ["direct", "chain_of_thought"],
        "reflect": [False, True],
        "temperature": [0.0],
    },
    "max_trials": 12,
    "wired": [
        "model",
        "temperature",
        "prompt_style",
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
        pillar, caps, _ = score_space(facts)
        self.assertEqual([cap.condition for cap in caps], [])
        # Full marks, and the number is the guide's own recommended shape
        # scoring as such: 24 distinct configurations against a 12-trial
        # budget, so the run compares twelve of them - `SEARCH_SPACE_FULL`,
        # which is what this guide's own baseline sweep enumerates - and 24 is
        # twice the budget rather than twenty times it.
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
        pillar, caps, _ = score_space(MODULE.agent_facts_from_config_space(reasoning))
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
                    MODULE.agent_facts_from_config_space({**space, "agent_type": value})
                self.assertIn("'agent_type'", str(raised.exception))

    def test_an_absent_optional_field_still_scores(self) -> None:
        """Validation must refuse bad *shapes*, not narrow the documented set.

        An absent `max_trials` is documented as scoreable, so the guard above
        must not swallow it.
        """
        absent = MODULE.agent_facts_from_config_space({"knobs": {"a": [1, 2]}})
        self.assertIsNone(absent.max_trials)
        pillar, caps, _ = score_space(absent)
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
        pillar, caps, _ = score_space(facts)
        self.assertEqual([cap.condition for cap in caps], [])
        # One knob, two values a 1-5 range can tell apart: a space of two.
        self.assertEqual(pillar.score, 35)
        numeric = MODULE.agent_facts_from_config_space(
            dict(document, bounds={"retrieval_k": {"low": 1, "high": 5}})
        )
        self.assertEqual(score_space(numeric)[0].score, pillar.score)

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
        pillar, caps, _ = score_space(integral)
        self.assertEqual([cap.condition for cap in caps], [])
        # The walkthrough document's own score; the point here is that the
        # float spelling reaches it rather than exiting 2.
        self.assertEqual(pillar.score, 100)
        self.assertEqual(
            pillar.score,
            score_space(MODULE.agent_facts_from_config_space(WALKTHROUGH_CONFIG_SPACE))[
                0
            ].score,
        )
        # the trial cap still damps the search-space points identically either way
        crowded = {"knobs": {f"k{i}": [1, 2, 3, 4] for i in range(6)}}
        self.assertEqual(
            score_space(
                MODULE.agent_facts_from_config_space(dict(crowded, max_trials=2.0))
            )[0].score,
            score_space(
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
        pillar, caps, _ = score_space(MODULE.agent_facts_from_config_space(sweeping))
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
        self.assertEqual(
            sorted(sub.name for sub in pillar.subscores),
            ["control-flow", "output-contract", "prompt", "search-space", "tools"],
        )
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
        pillar, caps, _ = score_space(
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

    def test_the_search_space_is_measured_by_exactly_one_sub_score(self) -> None:
        """Two numbers only need weighing while there are two of them.

        `knob-count` and `variation` are gone with the 55/45 that weighed them.
        Asserted on the pillar rather than on the absence of a constant,
        because a re-introduced sub-score under a new name is the same defect.

        The claim was "the pillar reports one sub-score" and #184 made that
        false without making it wrong: the pillar now also carries four checks
        about how the agent is BUILT, which is a different question and the
        whole point of widening it. What may not come back is a second number
        for the same question, so that is what this asserts - one check
        measures the search space, and the ones beside it measure something
        else.
        """
        pillar, _, _ = self._pillar({"model": ["a", "b", "c"]})
        space = [sub for sub in pillar.subscores if sub.name == "search-space"]
        self.assertEqual(len(space), 1)
        self.assertEqual(space[0].maximum, MODULE.SEARCH_SPACE_WEIGHT)
        self.assertEqual(MODULE.SEARCH_SPACE_WEIGHT, 100.0)
        self.assertEqual(
            sorted(sub.name for sub in pillar.subscores if sub.name != "search-space"),
            sorted(name for name, _weight in MODULE.AGENT_BUILD_CHECKS),
        )
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
        1024-configuration space scores BELOW a 24-configuration one because
        the twelve trials are the same twelve either way and the larger report
        describes a sample nobody chose - and a 24 and a 12 score the SAME,
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
        stayed green except the then-committed behaviour lock, stale only
        because the file's bytes changed - and with that lock retired, today
        the same mutation passes with nothing so much as flinching, which
        makes this test MORE load-bearing, not less. A guard whose mutation
        nothing catches is a guard that documents an intention.

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
        self.assertEqual(score_space(facts)[0].score, 35)
        self.assertEqual(
            score_space(MODULE.agent_facts_from_config_space(sweeping))[0].score,
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
            score_space(
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
        leaves its five declared dimensions and 24 configurations untouched.
        """
        pillar, caps, _ = score_space(
            MODULE.agent_facts_from_config_space(WALKTHROUGH_CONFIG_SPACE)
        )
        self.assertEqual([cap.condition for cap in caps], [])
        self.assertEqual(pillar.score, 100)
        space = next(s for s in pillar.subscores if s.name == "search-space")
        self.assertEqual(
            space.evidence,
            "your space has 24 distinct configurations; this run will try up to "
            "12 of them",
        )

    def test_absent_wired_attests_nothing_rather_than_everything(self) -> None:
        """A document that never named the wired knobs attested none of them.

        Declaring a knob is not a statement that the agent consumes it. Reading
        an absent `wired` list as "every declared knob is wired" let a six-line
        hand-written file buy agent points and retire the cap, so the honest
        state is zero knobs attested as wired, still capped.
        """
        pillar, caps, knobs = score_space(
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
        declared, _, _ = score_space(
            MODULE.AgentFacts(knobs={"model": ["a", "b"]}, config_space_supplied=True)
        )
        absent, _, _ = score_space(MODULE.AgentFacts())
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
                pillar, caps, knobs = score_space(
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
        pillar, caps, knobs = score_space(
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
        checks = {sub["name"]: sub for sub in agent["subscores"]}
        # The document establishes the whole search space, which is what this
        # test has always been about, and it still does.
        self.assertEqual(checks["search-space"]["value"], MODULE.SEARCH_SPACE_WEIGHT)
        self.assertNotIn(
            "agent-no-varying-knobs", [cap["condition"] for cap in score["caps"]]
        )
        # And the pillar is no longer only that. A document says nothing about
        # whether the agent has a prompt, a bounded loop, or tools it can
        # reach, so those four checks are unanswered here - withheld rather
        # than excluded, because the guide asks for that read at every gate
        # where an agent was found, and a check the run was asked for and did
        # not supply may not be free.
        for name, _weight in MODULE.AGENT_BUILD_CHECKS:
            with self.subTest(check=name):
                self.assertFalse(checks[name]["measured"])
                self.assertTrue(checks[name]["withheld"])
        self.assertLess(agent["score"], 100)

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

    def test_agent_knobs_scores_the_opening_and_yields_to_a_config_space(
        self,
    ) -> None:
        """The flag end to end, and the precedence that keeps it safe.

        Two runs over identical preflight input. The first passes only the read
        of the agent and must score the pillar from it; the second passes a
        config-space document as well, and that document must decide the pillar
        alone - here a document attesting nothing, which still blocks. If the
        read could talk over it, `--agent-knobs` would be a way to score around
        a customer's own statement that nothing is wired.
        """
        with tempfile.TemporaryDirectory() as directory:
            preflight = Path(directory) / "preflight.json"
            preflight.write_text(json.dumps(PREFLIGHT_RECORDS))
            agent_knobs = Path(directory) / "agent-knobs.json"
            agent_knobs.write_text(
                json.dumps(
                    {
                        "source": "agent.py",
                        "knobs": {
                            "model": {
                                "values": ["gpt-4o-mini", "gpt-4o"],
                                "evidence": "agent.py:8 model reaches the call showing gpt-4o-mini, gpt-4o",
                            },
                            "temperature": {
                                "low": 0.0,
                                "high": 1.0,
                                "evidence": "agent.py:9 temperature reaches it",
                            },
                        },
                    }
                )
            )
            space = Path(directory) / "space.json"
            space.write_text(json.dumps({"knobs": {"model": ["gpt-4o-mini"]}}))
            read = json.loads(
                self._run(
                    [
                        "--preflight",
                        str(preflight),
                        "--agent-knobs",
                        str(agent_knobs),
                        "--json",
                    ]
                )[1]
            )
            with_document = json.loads(
                self._run(
                    [
                        "--preflight",
                        str(preflight),
                        "--agent-knobs",
                        str(agent_knobs),
                        "--config-space",
                        str(space),
                        "--json",
                    ]
                )[1]
            )
        agent = next(p for p in read["pillars"] if p["name"] == "agent")
        space = next(s for s in agent["subscores"] if s["name"] == "search-space")
        # The read measured the search space. The pillar's own confidence is
        # lower since #184 because this document answers only the knob half of
        # the read, which is the point: the other half is asked for and absent.
        self.assertTrue(space["measured"])
        self.assertGreater(agent["score"], 0)
        self.assertNotIn(
            "agent-no-varying-knobs", [cap["condition"] for cap in read["caps"]]
        )
        # The document decides, and it says nothing is wired.
        self.assertIn(
            "agent-no-varying-knobs",
            [cap["condition"] for cap in with_document["caps"]],
        )
        capped = next(p for p in with_document["pillars"] if p["name"] == "agent")
        self.assertEqual(capped["score"], 0)

    def test_a_malformed_agent_knobs_document_is_refused_not_scored(self) -> None:
        """It is the one input that can RAISE a score, so it fails closed.

        Exit 2 and a message naming the knob, on the same footing as a
        config-space document the scorer cannot read. A read of the agent that
        arrives malformed is exactly the read that must not be quietly repaired
        into a usable one.
        """
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "agent-knobs.json"
            broken.write_text(json.dumps({"knobs": {"temperature": {"low": 0.0}}}))
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code, _out = self._run(["--agent-knobs", str(broken), "--json"])
        self.assertEqual(code, 2)
        self.assertIn("cannot read scoring input", err.getvalue())
        self.assertIn("temperature", err.getvalue())

    def test_wired_less_config_space_adds_no_points(self) -> None:
        """Handing the scorer a knob document must not, by itself, buy anything.

        Written as a two-run differential over identical preflight input rather
        than as an absolute `overall == 0`: the complaint is that the file
        *added points*, and a differential keeps pinning that through any later
        rescaling of the pillars.

        The direction is now `<=` rather than `==`, and the loosening is a real
        behaviour change worth stating (#201). An unattested document is a
        finding - the user handed over their wiring and marked nothing as used -
        so it caps at 45 and blocks. Supplying nothing is not that finding, so
        it no longer caps at all. A defective document therefore scores below
        an absent one, which reads as perverse until you read the two claims:
        one is the customer saying the search has nothing to work with, and the
        other is nobody having said anything. The equality this test used to
        assert was only available because a single ceiling was applied to both,
        and applying it to both is the defect #201 removed.
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
        self.assertLessEqual(with_document["overall"], without["overall"])
        # ...and must not cost anything either. The first draft of this fix
        # reported 0.49 without the document and 0.40 with it, so supplying more
        # input read as having observed less. The constraint is the DIRECTION,
        # and it is not equality: a document naming a knob is a search space
        # somebody read, and no document is one nobody read. Confidence rises
        # and the score does not.
        self.assertGreater(with_document["confidence"], without["confidence"])
        conditions = {cap["condition"] for cap in with_document["caps"]}
        self.assertIn("agent-no-varying-knobs", conditions)

        # The absent-document run raises the SAME condition, and that is the
        # half of this that #201 kept changing its mind about. Deleting the
        # ceiling there made saying nothing outscore handing over a document
        # that declares the same empty space, so both states carry it and what
        # separates them is `blocks`: a document nobody could read is not a
        # defect, and a document that declares nothing is.
        def agent_cap(payload: dict) -> dict:
            return next(
                cap
                for cap in payload["caps"]
                if cap["condition"] == "agent-no-varying-knobs"
            )

        self.assertFalse(agent_cap(without)["blocks"])
        self.assertTrue(agent_cap(with_document)["blocks"])
        self.assertEqual(
            agent_cap(without)["ceiling"], agent_cap(with_document)["ceiling"]
        )

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
    def _run(
        argv: list[str], environ: dict[str, str] | None = None
    ) -> tuple[int, str, str]:
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

    def test_two_documents_cannot_both_be_piped(self) -> None:
        """Every document flag takes `-`, and there is one stdin.

        The opening gate wants preflight output and a source read at once, so
        piping both is the obvious move. The first read consumed stdin and the
        second saw an empty stream, which surfaced far away as an
        `AttributeError` about a shape nobody passed - reported to a first-time
        user as a defect in the checker.
        """
        code, _stdout, stderr = self._run(
            [
                "--preflight",
                "-",
                "--agent-knobs",
                "-",
                "--task-kind",
                "structured",
                "--evaluator-method",
                "set-f1",
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("cannot read scoring input", stderr)
        self.assertIn("--preflight", stderr)
        self.assertIn("--agent-knobs", stderr)
        self.assertNotIn("internal error", stderr)

    def test_one_piped_document_is_still_allowed(self) -> None:
        """The refusal is about collision, not about `-`.

        Pinned beside the refusal because the cheapest wrong fix - banning `-`
        outright - passes the test above and removes the affordance the help
        text promises on five flags.
        """
        code, _stdout, stderr = self._run(
            ["--config-space", "/nonexistent.json", "--agent-knobs", "-"]
        )
        self.assertEqual(code, 2)
        self.assertNotIn("each read stdin", stderr)

    def test_the_help_text_names_the_fields_the_reader_actually_accepts(self) -> None:
        """The help is where a caller at the opening gate looks for the shape.

        A help text that restates the field names as a literal reads as
        authoritative and goes stale in silence the first time either set
        grows - which is the failure this addition exists to prevent, arriving
        one layer over. Derived from the same constants the reader validates
        against, so the two cannot disagree.
        """
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            MODULE.parse_args(["--help"])
        help_text = out.getvalue()
        for field in MODULE.AGENT_KNOBS_DOCUMENT_FIELDS | MODULE.DISCOVERED_KNOB_FIELDS:
            self.assertIn(field, help_text)

    def test_a_document_of_the_wrong_shape_is_refused_by_name(self) -> None:
        """`--preflight` reads a list of checks; a dict is a different document.

        Handing one flag the other flag's document is a caller mistake, and it
        reached the record loop as `'str' object has no attribute 'get'`. The
        same input arriving by path rather than by pipe must refuse the same
        way, so the fix cannot be the stdin guard alone.
        """
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory) / "agent-knobs.json"
            wrong.write_text(
                json.dumps({"source": "agent.py", "knobs": {}, "build": {}})
            )
            code, _stdout, stderr = self._run(["--preflight", str(wrong)])
        self.assertEqual(code, 2)
        self.assertIn("cannot read scoring input", stderr)
        self.assertIn("--preflight", stderr)
        self.assertNotIn("internal error", stderr)


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

    def test_an_absent_settings_document_bounds_a_claim_and_stops_nothing(
        self,
    ) -> None:
        """What #201 actually changed about this cap: its reason, not its number.

        The guide deliberately withholds any config-space document found before
        this run's search, so `agent-no-varying-knobs` fires on the opening card
        of every project that supplies no agent evidence - and its reason used
        to say "nothing in your project needs repairing for this" while holding
        the card at 45. That sentence was the defect. It told the customer they
        were fine and capped them anyway, and it left them nothing to do about
        it, because before #201 there was nothing to do: no document could be
        supplied at the opening gate by the guide's own design.

        #201 gives the state a remedy - read the agent - so the reason names it
        and the ceiling stands. Deleting the ceiling instead was tried on this
        branch and measured: it put this state at 71 while a settings document
        declaring the same empty space stayed at 45, so the customer who told
        the truth about their agent scored 26 points below the one who said
        nothing. Every other pillar in this module already caps its own absence
        (`dataset-absent`, `evaluator-absent`); the agent pillar was the only
        one where saying nothing was free.

        Asserting `blocks`, `status` and `recommended_action` end to end: what
        separates this from the document branch is that the run PROCEEDS, and
        that has to be visible in the score a caller gets rather than in a list
        of caps.
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
        # The ceiling stands and the run proceeds. That pair is the whole
        # finding: nothing here is known to be broken, so nothing waits.
        self.assertFalse(caps[0].blocks)
        self.assertEqual(score.status, "OK")
        self.assertEqual(score.recommended_action, MODULE.PROCEED)
        # 71 stays a literal deliberately: it is the arithmetic of
        # DEFAULT_WEIGHTS over the two pillars this test pins itself, and the
        # zero for the third counts. The ceiling is what the card actually
        # lands on.
        self.assertEqual(score.weighted_average, 71)
        self.assertEqual(score.overall, MODULE.AGENT_NO_VARYING_KNOBS_CEILING)
        # The reason names what would lift it. A ceiling whose remedy is
        # unstatable is the one this branch shipped before #201.
        self.assertIn("reading of the agent", caps[0].reason.casefold())
        self.assertNotIn("needs repairing", caps[0].reason.casefold())
        # The pillar is still reported as unmeasured - the honesty about
        # evidence is unchanged.
        agent_sub = score.pillars[0].subscores[0]
        self.assertEqual(score.pillars[0].name, "agent")
        self.assertFalse(agent_sub.measured)
        self.assertEqual(score.pillars[0].confidence, 0.0)
        # This run was asked for agent evidence and supplied none, which is
        # withheld: the check keeps its weight and the zero counts.
        self.assertTrue(agent_sub.withheld)

        # A document that was supplied and lists nothing IS a defect: the user
        # handed over their wiring and there is nothing in it. Same ceiling,
        # and the ceiling being the same is the point - it is the same finding
        # about the same project, so it may not be graded differently for
        # having been declared.
        caps, blocked = scored(MODULE.AgentFacts(config_space_supplied=True))
        self.assertEqual([cap.condition for cap in caps], ["agent-no-varying-knobs"])
        self.assertTrue(caps[0].blocks)
        self.assertEqual(blocked.status, "BLOCKED")
        self.assertEqual(blocked.recommended_action, "vary-knobs")
        self.assertEqual(blocked.overall, MODULE.AGENT_NO_VARYING_KNOBS_CEILING)
        self.assertEqual(blocked.overall, score.overall)

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

        Both halves are still here, so both are checked. #201 rewrote the cap's
        reason rather than deleting the cap, and a rewrite is exactly where the
        tense could come back - the sentence had to gain a remedy ("reading the
        agent is what counts them"), and "read the agent first" is one edit away
        from "the enhanced run will write that document".
        """
        pillar, caps, _ = score_space(MODULE.AgentFacts())
        lines = [sub.evidence for sub in pillar.subscores] + [
            cap.reason for cap in caps
        ]
        for line in lines:
            with self.subTest(line=line):
                self.assertNotIn(" yet", line)
        # Still one fact, so the card still collapses it to one row.
        self.assertEqual(len(set(sub.evidence for sub in pillar.subscores)), 1)

    def _knob(self, **fields):
        """One discovered-knob document entry, read through the real adapter."""
        return MODULE.agent_facts_from_discovery({"knobs": fields})

    def test_the_opening_score_measures_the_agents_own_search_space(self) -> None:
        """#201's headline: the opening card grades what the project can search.

        Measured end to end before this landed, on 200 production-sourced rows,
        difficulty-tagged, split 180/20, with a deterministic evaluator passing
        all seven calibration checks: dataset 98, evaluation 100, agent 0 at
        confidence 0.00, weighted average 74, overall 45 PARTIAL, sole cap
        `agent-no-varying-knobs`. No opening card could exceed 45 for any
        customer, because the guide withholds every config-space document found
        before this run's search.

        The same evidence with the agent read - four parameters, each carrying
        the line of the customer's own code that shows it - scores agent 70 and
        92 EXCELLENT overall, with no cap. The pillar is scored from a floor:
        three model ids and two prompt styles are counted at three and two, and
        each numeric range at two, so 24 configurations is the smallest space
        the agent certainly reaches and not an estimate of the largest.
        """
        facts = self._knob(
            model={
                "values": ["gpt-4o-mini", "gpt-4o", "o3-mini"],
                "evidence": "agent.py:8 model=model reaches the provider call showing gpt-4o-mini, gpt-4o, o3-mini",
            },
            temperature={
                "low": 0.0,
                "high": 1.0,
                "evidence": "agent.py:9 temperature=temperature reaches the call",
            },
            style={
                "values": ["direct", "structured"],
                "evidence": "agent.py:11 STYLES[style] selects the system prompt showing direct, structured",
            },
        )
        pillar, caps, knobs = score_space(facts)
        self.assertEqual(caps, [])
        self.assertEqual(knobs, [])
        self.assertEqual(pillar.confidence, 1.0)
        self.assertEqual(pillar.score, 70)
        evidence = pillar.subscores[0].evidence
        # 3 x 2 x 2 = 12 - the numeric range counts as two and no more.
        self.assertIn("at least 12 distinct configurations", evidence)
        # Named, so the customer can disagree with the read of their own code.
        self.assertIn("model, style, temperature", evidence)
        # And bounded: no trial budget exists yet, so the top rung is refused
        # by `search_space_points`' own undeclared-budget rule, not by a cap.
        self.assertLess(pillar.score, 100)

    def test_a_discovered_space_is_never_a_wiring_attestation(self) -> None:
        """The safety property, stated where it could most easily be lost.

        The guide refuses a historical `wired` list as current wiring. A read of
        the agent's source is a different kind of evidence and must not be
        promoted into that one: it says what the code can vary, never that a
        Traigent document attests it. Two consequences are asserted, because
        either alone would let the other rot.
        """
        facts = self._knob(
            temperature={
                "low": 0.0,
                "high": 1.0,
                "evidence": "agent.py:9 temperature reaches the provider call",
            }
        )
        # It never becomes a config space: no knobs, no `wired`, and the flag
        # that says a settings document arrived stays false.
        self.assertEqual(facts.knobs, {})
        self.assertIsNone(facts.wired)
        self.assertFalse(facts.config_space_supplied)
        # And a supplied config-space document wins outright, including one
        # that says nothing is wired - which still blocks, with the read of the
        # agent present and unable to talk over it.
        both = MODULE.replace(
            facts,
            knobs={"temperature": [0.0, 1.0]},
            wired=(),
            config_space_supplied=True,
        )
        _pillar, caps, _knobs = MODULE.score_agent(both)
        self.assertEqual([cap.condition for cap in caps], ["agent-no-varying-knobs"])
        self.assertTrue(caps[0].blocks)

    def test_looking_at_the_agent_beats_saying_nothing_about_it(self) -> None:
        """A read that found settings must outscore one that found none.

        The first draft of #201 renormalized an unmeasured agent pillar out of
        the average, and measured on the 200-row project that scored 99 for a
        run that read the agent and found nothing against 92 for a run that read
        it and found four parameters. Not finding anything was worth 7 points -
        the exact defect `SubScore.withheld` exists to prevent, one level up
        from where it prevents it, because removing a pillar from a weighted
        average raises the result.

        `LessEvidenceMayNotOutscoreMoreTests` sweeps that property. This keeps
        the one comparison the owner reported, spelled out, so the regression
        has a named home rather than only a swept one.
        """
        pillars = [
            MODULE.Pillar(name=name, score=100, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation")
        ]

        def overall(facts: MODULE.AgentFacts) -> MODULE.ReadinessScore:
            agent, caps, knobs = MODULE.score_agent(facts)
            return MODULE.aggregate(
                pillars + [agent], caps, knobs, dict(MODULE.DEFAULT_WEIGHTS)
            )

        read = overall(
            self._knob(
                model={
                    "values": ["gpt-4o-mini", "gpt-4o", "o3-mini"],
                    "evidence": "agent.py:8 model reaches the provider call showing gpt-4o-mini, gpt-4o, o3-mini",
                },
                temperature={
                    "low": 0.0,
                    "high": 1.0,
                    "evidence": "agent.py:9 temperature reaches the call",
                },
            )
        )
        silent = overall(MODULE.AgentFacts())
        found_nothing = overall(
            self._knob(
                model={
                    "values": ["gpt-4o-mini"],
                    "evidence": "agent.py:8 model= is hard-coded to one id showing gpt-4o-mini",
                }
            )
        )
        self.assertGreater(read.overall, silent.overall)
        self.assertGreater(read.overall, found_nothing.overall)
        # And the read that found nothing is not punished for having looked
        # either: same finding as silence about the same project, same number.
        self.assertEqual(found_nothing.overall, silent.overall)

    def test_a_read_that_finds_nothing_is_a_measured_zero(self) -> None:
        """The read happened, so its answer is a measurement - of zero.

        This is the state the owner rejected #201's first answer over. That
        draft reported it as unmeasured and had `aggregate` renormalize the
        whole pillar out of the average, which scored it 99 against 92 for a
        read that found four settings: finding nothing beat finding something,
        by 7 points, on the same project.

        The scorer already had the right answer for the same shape one branch
        over. A config-space document that lists nothing IS a measurement of the
        search space - one configuration, read off the file - and this is that
        measurement taken from the agent's source instead. So it is `measured`
        at confidence 1.00, it earns zero, and it raises the same condition,
        which is what a project with nothing to search deserves whichever
        document says so.

        The epistemic caveat that argued for "unmeasured" - a parameter this
        read did not establish may exist anyway - is real and belongs in the
        sentence rather than in the arithmetic, so the evidence line names each
        refusal and its reason. A settings document that lists nothing carries
        exactly the same caveat and nobody proposed dropping the pillar over it.
        """
        facts = self._knob(
            model={
                "values": ["gpt-4o-mini"],
                "evidence": "agent.py:8 model= is hard-coded to one id showing gpt-4o-mini",
            },
            seed={
                "low": 0,
                "high": 1000,
                "evidence": "agent.py:12 seed= is passed through",
            },
        )
        pillar, caps, _knobs = score_space(facts)
        self.assertEqual([cap.condition for cap in caps], ["agent-no-varying-knobs"])
        self.assertTrue(caps[0].blocks)
        self.assertTrue(pillar.subscores[0].measured)
        self.assertFalse(pillar.subscores[0].withheld)
        self.assertEqual(pillar.score, 0)
        self.assertEqual(pillar.confidence, 1.0)
        # Each refusal keeps its own reason - a reader can act on "one option is
        # not a choice" and cannot act on silence.
        self.assertIn("one option is not a choice", pillar.subscores[0].evidence)
        self.assertIn("run-to-run variance", pillar.subscores[0].evidence)

        score = MODULE.aggregate(
            [
                MODULE.Pillar(name=name, score=100, confidence=1.0, subscores=())
                for name in ("dataset", "evaluation")
            ]
            + [pillar],
            caps,
            (),
            dict(MODULE.DEFAULT_WEIGHTS),
        )
        # Averaged with the zero over all three declared weights, not
        # renormalized over two. 100 and 100 and 0 over 40, 35 and 25.
        self.assertEqual(score.weighted_average, 75)
        self.assertEqual(score.overall, MODULE.AGENT_NO_VARYING_KNOBS_CEILING)
        self.assertEqual(score.status, "BLOCKED")
        # The card says what was read and what it found, in the pillar's own
        # row, rather than explaining a denominator the reader cannot see.
        card = MODULE.render_card(score)
        self.assertIn("no varying setting was established", card)

    def test_a_discovered_knob_earns_nothing_without_evidence_for_it(self) -> None:
        """Never invent a space: the owner's rule, enforced per field.

        Each refusal below is a document this scorer could have scored
        generously and does not. The first two are refusals of the DOCUMENT
        (it cannot be read as written); the rest are findings reported with
        their reason, because a parameter that does not qualify is not an error
        - the read happened, and what it found is worth saying.
        """
        for label, spec in (
            ("no evidence at all", {"values": ["a", "b"]}),
            ("blank evidence", {"values": ["a", "b"], "evidence": "   "}),
            ("range the wrong way round", {"low": 1.0, "high": 0.0, "evidence": "x"}),
            ("non-numeric range", {"low": "cold", "high": "hot", "evidence": "x"}),
            ("values that are not a list", {"values": "a,b", "evidence": "x"}),
            (
                "an unknown field",
                {"values": ["a", "b"], "range": [0, 1], "evidence": "x"},
            ),
        ):
            with self.subTest(refused=label):
                with self.assertRaises(MODULE.AgentDiscoveryInputError):
                    self._knob(temperature=spec)

        # A name in CANONICAL_RANGES does NOT supply a range the author did not
        # write. That table answers "how wide is this span relative to the usual
        # one" for a declared knob; it cannot answer "does this agent expose it".
        self.assertIn("temperature", MODULE.CANONICAL_RANGES)
        facts = self._knob(
            temperature={"evidence": "agent.py:9 temperature is passed through"}
        )
        self.assertFalse(facts.discovered[0].credited)
        self.assertIn(
            "neither a list of options", facts.discovered[0].uncredited_reason
        )

        # And a range narrower than this scorer's own noise floor for the knob
        # earns nothing, because two values drawn from it are one value.
        narrow = self._knob(
            temperature={"low": 0.20, "high": 0.22, "evidence": "agent.py:9 range"}
        )
        self.assertFalse(narrow.discovered[0].credited)
        self.assertIn("noise floor", narrow.discovered[0].uncredited_reason)

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

        The `agent-no-varying-knobs` example this test was written around is
        gone: #201 deleted that branch rather than rewording it, so every
        surviving construction of that condition blocks and none of them belongs
        here. `FULLY_SYNTHETIC_CAP` takes its place, which keeps the pair the
        test was built to compare - two conditions with unrelated remedies,
        because a rule proven on one advisory cap is a rule about that cap.

        The size fixture is 28 comparable rows and not 15, because #197 made a
        size below that one ASK - it offers to write the difference up to the
        walkthrough's own total - and a cap that asks is a cap the report is
        supposed to route. That is the sibling case below. What is asserted
        here is still the same rule on the same condition: a ceiling that
        bounds a claim and asks for nothing prints no fix.
        """
        pillars = [
            MODULE.Pillar(name=name, score=95, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        for cap in (
            MODULE.FULLY_SYNTHETIC_CAP,
            MODULE.power_ceiling(MODULE.WALKTHROUGH_DATASET_ROWS),
        ):
            with self.subTest(cap=cap.condition):
                self.assertFalse(cap.blocks)
                self.assertFalse(cap.asks)
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


class LessEvidenceMayNotOutscoreMoreTests(unittest.TestCase):
    """The agent pillar's ordering, swept rather than sampled.

    Six times in this repository's history, omitting evidence has scored better
    than supplying it - undeclared provenance, an absent `--task-kind`, missing
    probe scores, an untagged dataset, an unattested wiring claim, and #201's
    own first draft, where a read of the agent that found nothing scored 99
    against 92 for a read that found four settings. Each was found by somebody
    noticing one pair of numbers. Each fix pinned that pair.

    A pair is not the property. This asserts the property over the whole space
    of agent-evidence states this scorer can be given, crossed with the other
    two pillars, because the defect has never once recurred in the pair anybody
    already pinned - it recurs in the state next to it.

    THE ORDER BEING ASSERTED is the number of configurations the evidence
    ESTABLISHES, which is the only thing the agent pillar claims to measure. A
    state that establishes a space of one - nobody looked, a read found nothing
    varying, a document lists nothing, a document lists settings that are all
    pinned - establishes exactly as much searchable surface as any other of
    them: none. So they must all score the SAME, and every state that
    establishes more must score at least as much.

    That equality is the load-bearing half, and it is the half both of #201's
    rejected drafts broke. Draft one renormalized the read-found-nothing pillar
    out of the average, putting it 25 points above every other empty state.
    Draft two fixed that and deleted the ceiling on the silent state instead,
    putting silence 30 points above a document that declares the same empty
    space - omission outscoring declaration, the class the fix was for.

    What is deliberately NOT asserted is that more evidence scores STRICTLY
    more. Looking and finding nothing is more work than not looking, and it
    tells the customer something; it does not make their agent more searchable,
    and a score that paid for the looking would be measuring this run's effort
    rather than the project. The difference between those two states belongs to
    `blocks`, `confidence` and the evidence sentence, all of which are asserted
    in their own tests. Only the score is ordered here.
    """

    # Dataset and evaluation pillars across their whole range, at the same
    # granularity as the modelled opening-card sweep in test_skill_package.
    # They are built directly rather than scored from facts because the subject
    # here is the agent pillar: what has to hold is that no setting of the other
    # two can invert the order, including the ones where a cap is not the
    # operative limit at all.
    GRID = tuple(range(0, 101, 10))

    def _states(self) -> list[tuple[str, int, object]]:
        """Every agent-evidence state, each with the space it establishes.

        The count beside each is what the evidence puts on the table: 1 means
        "one configuration", which is another way of writing "nothing to
        search". Read states go through `agent_facts_from_discovery` and
        document states through `agent_facts_from_config_space`, so a change to
        either adapter reaches this sweep instead of being masked by
        hand-built facts.
        """

        def read(**knobs: object) -> object:
            return MODULE.agent_facts_from_discovery({"knobs": knobs})

        def document(knobs: dict, **rest: object) -> object:
            return MODULE.agent_facts_from_config_space(
                {"knobs": knobs, **rest},
            )

        # The line a real read would quote, so it SHOWS the options the
        # fixtures below declare: a knob now earns nothing for an option
        # its own evidence does not contain, and a fixture citing a bare
        # line number stopped modelling a read that establishes anything.
        cited = (
            'agent.py:8 model in ("gpt-4o-mini", "gpt-4o") reaches '
            "chat.completions.create"
        )
        states: list[tuple[str, int, object]] = [
            ("no document and no read", 1, MODULE.AgentFacts()),
            ("read: nothing at all", 1, read()),
            (
                "read: one pinned value",
                1,
                read(model={"values": ["gpt-4o-mini"], "evidence": cited}),
            ),
            (
                "read: categorical with one option",
                1,
                read(thinking_shape={"values": ["direct"], "evidence": cited}),
            ),
            (
                "read: a range inside the noise floor",
                1,
                read(temperature={"low": 0.20, "high": 0.22, "evidence": cited}),
            ),
            (
                "read: seed only",
                1,
                read(seed={"low": 0, "high": 1000, "evidence": cited}),
            ),
            (
                "read: one numeric knob",
                2,
                read(temperature={"low": 0.0, "high": 1.0, "evidence": cited}),
            ),
            (
                "read: one categorical knob",
                2,
                read(model={"values": ["gpt-4o-mini", "gpt-4o"], "evidence": cited}),
            ),
            (
                "read: two knobs",
                4,
                read(
                    model={"values": ["gpt-4o-mini", "gpt-4o"], "evidence": cited},
                    temperature={"low": 0.0, "high": 1.0, "evidence": cited},
                ),
            ),
            (
                "read: three knobs",
                8,
                read(
                    model={"values": ["gpt-4o-mini", "gpt-4o"], "evidence": cited},
                    temperature={"low": 0.0, "high": 1.0, "evidence": cited},
                    top_p={"low": 0.1, "high": 1.0, "evidence": cited},
                ),
            ),
            (
                "read: four knobs",
                24,
                read(
                    model={
                        "values": ["gpt-4o-mini", "gpt-4o", "o3-mini"],
                        "evidence": cited,
                    },
                    temperature={"low": 0.0, "high": 1.0, "evidence": cited},
                    top_p={"low": 0.1, "high": 1.0, "evidence": cited},
                    thinking_shape={
                        "values": ["direct", "chain-of-thought"],
                        "evidence": cited,
                    },
                ),
            ),
            ("document: lists nothing", 1, document({})),
            ("document: wiring unattested", 1, document({"model": ["a", "b"]})),
            (
                "document: wired names nothing",
                1,
                document({"model": ["a", "b"]}, wired=[]),
            ),
            (
                "document: one wired pinned knob",
                1,
                document({"model": ["a"]}, wired=["model"]),
            ),
            (
                "document: one wired varying knob",
                2,
                document({"model": ["a", "b"]}, wired=["model"]),
            ),
            (
                "document: two wired varying knobs",
                4,
                document(
                    {"model": ["a", "b"], "thinking_shape": ["direct", "cot"]},
                    wired=["model", "thinking_shape"],
                ),
            ),
        ]
        return states

    def _overall(self, facts: object, dataset: int, evaluation: int) -> int:
        agent, caps, knobs = MODULE.score_agent(facts)
        pillars = [
            MODULE.Pillar(name="dataset", score=dataset, confidence=1.0, subscores=()),
            MODULE.Pillar(
                name="evaluation", score=evaluation, confidence=1.0, subscores=()
            ),
            agent,
        ]
        return MODULE.aggregate(
            pillars, caps, knobs, dict(MODULE.DEFAULT_WEIGHTS)
        ).overall

    def test_every_state_reaches_the_branch_it_claims_to(self) -> None:
        """The sweep is worthless if its fixtures land somewhere else.

        Each state declares the space it establishes; this checks the scorer
        agrees, by reading the pillar rather than the overall. A fixture whose
        document was silently rejected, or whose knob was silently uncredited,
        would otherwise sweep a state nobody meant to test and pass for the
        wrong reason - which is how a fixture that reaches no branch at all
        still goes green.
        """
        for name, established, facts in self._states():
            with self.subTest(state=name):
                pillar, caps, _knobs = MODULE.score_agent(facts)
                conditions = [cap.condition for cap in caps]
                if established == 1:
                    self.assertEqual(pillar.score, 0, "an empty space earns nothing")
                    self.assertEqual(
                        conditions,
                        ["agent-no-varying-knobs"],
                        "a state that establishes no space must say so",
                    )
                else:
                    self.assertGreater(
                        pillar.score, 0, "a real space has to earn something"
                    )
                    self.assertEqual(
                        conditions, [], "a real space raises no nothing-to-search cap"
                    )

    def test_no_state_outscores_one_that_establishes_more(self) -> None:
        """The property, over every pair, at every dataset and evaluation."""
        states = self._states()
        checked = 0
        for dataset in self.GRID:
            for evaluation in self.GRID:
                scores = {
                    name: (established, self._overall(facts, dataset, evaluation))
                    for name, established, facts in states
                }
                for low, (low_space, low_score) in scores.items():
                    for high, (high_space, high_score) in scores.items():
                        if low_space > high_space:
                            continue
                        checked += 1
                        self.assertLessEqual(
                            low_score,
                            high_score,
                            f"at dataset={dataset} evaluation={evaluation}, "
                            f"{low!r} establishes {low_space} configuration(s) "
                            f"and scores {low_score}, while {high!r} "
                            f"establishes {high_space} and scores {high_score} "
                            "- less searchable evidence scored higher",
                        )
        # The sweep has to be big enough to be worth calling a property, and a
        # helper that quietly returned no states would pass every assertion
        # above by vacuity.
        self.assertGreater(checked, 20_000)

    def test_states_that_establish_nothing_all_score_the_same(self) -> None:
        """The equality both rejected drafts broke, stated on its own.

        Separated from the ordering above because it fails differently: an
        ordering violation says one state is too generous, and this says two
        readings of the SAME finding disagree about what it is worth. Every one
        of these establishes a search space of one configuration, on the same
        project, and the only thing that differs is which document said so.
        """
        empty = [
            (name, facts)
            for name, established, facts in self._states()
            if established == 1
        ]
        self.assertGreater(len(empty), 5)
        for dataset in self.GRID:
            for evaluation in self.GRID:
                landings = {
                    name: self._overall(facts, dataset, evaluation)
                    for name, facts in empty
                }
                self.assertEqual(
                    len(set(landings.values())),
                    1,
                    f"at dataset={dataset} evaluation={evaluation} the states "
                    f"that establish no search space disagree: {landings}",
                )


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

    def test_every_tie_in_the_order_was_broken_on_purpose(self) -> None:
        """Equal ceilings are allowed; equal ceilings in arbitrary ORDER are not.

        The non-decreasing assertion above cannot see a tie: swapping two
        conditions that carry the same number leaves it green. So each tie is
        recorded here with the reason it was broken the way it was, which is
        the whole point of the block in the module - the failure it exists to
        stop is "ranked by whichever author wrote each one".

        Two of the three ties are the same rule: where two conditions bound
        the claim by the same amount, the one that was COUNTED is ranked as the
        worse of the two and the one that was inferred follows it.
        `evaluator-absent` is a fact about the input; `evaluator-unresolved` is
        what this scorer concluded after failing to read a file.
        `dataset-mostly-synthetic` is a provenance count;
        `dataset-unsound-expected-outputs` is the assistant's reading of a
        customer's domain, which on collected data can be wrong.

        The third is ordered by its band instead, and the module says so where
        it is defined: `evaluator-timeout` opens "answers the wrong question"
        and `agent-no-varying-knobs` is equal to it because neither is broken
        and neither compares anything. Both are read off the input, so the
        counted-before-inferred rule has nothing to separate them with.

        Six ties on the merged tree rather than three. This test arrived with
        the branch that ranked the unsound-answer cap, whose base carried
        neither the silent-provenance rungs nor the middle answer-key rung nor
        the unrecognised-shape condition, so the three ties those conditions
        make were invisible to it. They are not new decisions: each is recorded
        beside its ceiling in the module, and each falls under one of the two
        rules already stated above - counted before inferred, or a shared band
        edge that is a coincidence rather than a cause. Pinning them here is
        what stops the next merge from reordering one silently.
        """
        ranked = [
            condition
            for _group, entries in MODULE.CAP_SEVERITY_ORDER
            for condition, _ceiling in entries
        ]
        ties = {}
        for condition in ranked:
            ties.setdefault(MODULE.CAP_CEILING[condition], []).append(condition)
        self.assertEqual(
            {
                ceiling: conditions
                for ceiling, conditions in ties.items()
                if len(conditions) > 1
            },
            {
                # A ruler that scores a wrong answer as well as a right one,
                # and a file no row of which parsed. Both leave nothing
                # trustworthy; `evaluator-invalid` is ranked first because it
                # produces believable numbers, where the unrecognised shape
                # produces none.
                25: ["evaluator-invalid", "dataset-shape-unrecognised"],
                40: ["evaluator-absent", "evaluator-unresolved"],
                45: ["evaluator-timeout", "agent-no-varying-knobs"],
                # One split defect read from each end: the same rows on both
                # sides, and every scoreable row on one. Neither breaks the
                # material and both leave the run comparing nothing, so they
                # bound the claim by the same amount. The overlap is ranked
                # first because it is the older and broader finding - a leaky
                # split is wrong wherever the rows fall - while the empty
                # tuning side is one arrangement of the same line.
                # And a third end of the same defect (#242): a line drawn along
                # the task families, so every recurring kind of input sits on
                # one side. It ranks last of the three under the
                # counted-before-inferred rule the 40 and 70 ties already
                # apply - the other two are read off row identities, and this
                # one off a leading form the check itself derives, which the
                # customer may answer is one task after all.
                50: [
                    "dataset-tune-holdout-overlap",
                    "dataset-tuning-split-empty",
                    "dataset-split-by-task-family",
                ],
                # The declared/silent pair. Identical ceilings deliberately -
                # the assumption IS "generated" either way - and the declared
                # one is ranked first because what differs is the remedy, which
                # this table does not rank.
                65: [
                    "dataset-fully-synthetic",
                    "dataset-undeclared-provenance",
                    # #238's agent rung, equal because the two say the same
                    # thing from opposite sides - a real agent tuned on
                    # invented evidence, and an invented agent tuned on real
                    # evidence - and ranked last because the dataset pair are
                    # counted per row and this one is declared by the run about
                    # its own work.
                    "agent-generated",
                ],
                70: [
                    "dataset-mostly-synthetic",
                    # The silent counterpart of the count before it, ranked
                    # beside it for the same reason the 65 pair is.
                    "dataset-mostly-undeclared",
                    "dataset-unsound-expected-outputs",
                ],
                # Three conditions meeting at the same band edge rather than
                # at a shared cause: 74 is one below STRONG, and each of these
                # states a claim about that band. Counted before inferred
                # again - the two size conditions are measured, the answer-key
                # rungs are read off provenance.
                74: [
                    "dataset-below-measurable-size",
                    "dataset-generated-answer-key",
                    "dataset-mostly-generated-answer-key",
                    # #238's evaluator rung, on the same band edge and last for
                    # the same reason the 65 tie puts its own rung last: the
                    # three before it are counted, and this one is declared.
                    "evaluator-generated",
                ],
            },
            "a tie in the ceiling order is a decision; record it here with its "
            "reason rather than leaving the sequence to whoever edited last",
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
    """`condition` failed closed and the other fields did not.

    `Cap(cond, None, ...)`, `"twenty"`, `999`, `-5`, `blocks="yes"` and
    `asks="no"` all constructed, and each reaches arithmetic or a truthiness
    test that cannot say so: a ceiling of 999 can never bind, -5 always does, a
    string takes `min()` down inside `aggregate`, a truthy `blocks` string
    turns every advisory ceiling into a block, and a truthy `asks` string makes
    a cap that declares it asks nothing hand out an errand. The type hints said
    all of it and nothing read them.
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

    def test_a_non_boolean_asks_flag_is_refused(self) -> None:
        """The field the guard above was written without, because it postdates it.

        `asks` arrived after this validation block and joined none of it, so
        the flag added to express a third state was the one field nothing
        checked. Every reader of it is a truthiness test - `recommended_action`
        and the durable report's remedy both ask `if cap.asks` - so the string
        that says NO is the one that asks: measured before this guard,
        `Cap("dataset-coarse-resolution", 89, ..., asks="no")` constructed and
        `recommended_action` returned `get-data` for it, handing an errand to a
        cap whose author had written the word "no".

        Exactly the `blocks="yes"` failure one field over, which is why it is
        refused in the same words and tested beside it.
        """
        with self.assertRaises(ValueError) as caught:
            MODULE.Cap(
                "dataset-coarse-resolution", 89, "reason", blocks=False, asks="no"
            )
        self.assertIn("non-boolean asks", str(caught.exception))

    def test_both_flags_still_take_either_boolean(self) -> None:
        """The false-red direction for the guard above.

        A guard that refuses `asks="no"` by refusing everything would be caught
        here rather than by a failure somewhere downstream, and `asks=False` is
        the value every cap in this module carries by default.
        """
        for asks in (True, False):
            with self.subTest(asks=asks):
                cap = MODULE.Cap(
                    "dataset-generated-answer-key",
                    MODULE.GENERATED_ANSWER_KEY_CEILING,
                    "reason",
                    blocks=False,
                    asks=asks,
                )
                self.assertIs(cap.asks, asks)
        # And the default is a real boolean, not an unset sentinel.
        self.assertIs(
            MODULE.Cap("dataset-coarse-resolution", 89, "reason", blocks=False).asks,
            False,
        )

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


def score_space(facts):
    """`score_agent`, reported as the search-space-only pillar it used to be.

    #184 widened the AGENT pillar. It carried one sub-score - how much there is
    to search - and printed `AGENT` over it, which a customer reads as a verdict
    on their agent; it now carries four more checks about how the agent is put
    together, so `Pillar.score` and `Pillar.confidence` are no longer the search
    space's own percentage and coverage.

    Every assertion that reaches this helper predates that change and is asking
    the OLD question, which is still a real question and still has an exact
    answer. So it is asked exactly: `combine` is re-run over the one sub-score
    that answers it, which reproduces the previous pillar rather than
    approximating it. Rewriting those expectations to the widened pillar's
    numbers would have been the other option and a worse one - it would leave
    the search-space arithmetic asserted nowhere, which is the half of this
    pillar #184 does not touch.

    Tests about the widened pillar call `MODULE.score_agent` directly.
    """
    pillar, caps, knobs = MODULE.score_agent(facts)
    space = [sub for sub in pillar.subscores if sub.name == "search-space"]
    return MODULE.combine(pillar.name, space), caps, knobs


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
    and `revalidation_caps: ["dataset-fully-synthetic"]` - the designed success,
    a run whose only remaining cap is the one its own substitutes earned. It
    reached "65/100 WORKABLE (PAID RUN BLOCKED)" with `recommended_action:
    connect-real-data`, demanding real data from the one user who by
    construction has none.

    Nothing here relaxes a ceiling. 65, 70, 74 and 74 still bind, still print,
    and still hold the score down; what goes away is the stop and the repair.

    "The repair" is not "the remedy", and one of these four keeps its remedy.
    An advisory ceiling recommends nothing where nothing is owed, which is why
    three of these assert `proceed` - but `dataset-generated-answer-key` routes
    to `review-answer-key`, a question whose answer changes the key the run is
    graded against, and it carries `asks=True` so the payload still names it.
    `status` is what this class is about and it stays OK in all four.
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
        # Bounded, not blocked - AND still routed. This asserted `proceed`,
        # which was the reading `blocks=False` alone produced: a payload saying
        # there is nothing to do about a dataset whose entire answer key was
        # written by a model, beside SKILL.md's route for that same condition
        # ("require that a person reviews a sample of the answers before a
        # correctness claim"). `asks` is what carries the remedy without
        # restoring the stop, and the stop is what this class is about: the
        # cap is advisory, `status` is OK, and the ceiling is unchanged.
        self.assertEqual(score.recommended_action, "review-answer-key")
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
        # Bounded, not blocked - and since #197 routed, because at this size
        # there is something this run can do about it that does not involve
        # sending anyone away for data. 18 comparable rows is under the
        # walkthrough's own total, so the payload carries the offer.
        self.assertTrue(score.caps[0].asks)
        self.assertEqual(score.recommended_action, "add-examples")
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
            [("dataset-tuning-split-empty", True)],
        )
        self.assertEqual(score.status, "BLOCKED")
        # `resplit-dataset` since #197, and the remedy is the finding: the
        # rows are there and labelled, so `get-data` was sending a customer
        # holding 120 usable examples away to collect more.
        self.assertEqual(score.recommended_action, "resplit-dataset")

    def test_a_family_partitioned_split_is_bounded_and_asked_not_blocked(self) -> None:
        """#242's third split condition, and the only one of the three that scopes.

        Its two siblings block because the line is PROVEN wrong - the same rows
        on both sides, or nothing scoreable on one - and both are read off row
        identities. This one is inferred from a leading form, and a deliberate
        out-of-distribution holdout produces it on purpose, so the customer is
        the only party who can settle whether the two kinds are one task.

        That is why it may not share `resplit-dataset`. Under #197 a remedy has
        to give one answer about whether the run waits, and telling a customer
        with real, labelled, disjoint rows to redraw their split before anything
        may run is an instruction this evidence does not support.
        """
        score = self._score(_clean_dataset(shared_families=0))
        self.assertEqual(
            [(cap.condition, cap.blocks, cap.asks) for cap in score.caps],
            [("dataset-split-by-task-family", False, True)],
        )
        self.assertEqual(score.status, "OK")
        self.assertEqual(score.recommended_action, "review-split")
        self.assertEqual(score.overall, MODULE.SPLIT_BY_TASK_FAMILY_CEILING)

    def test_an_unlabelled_tuning_side_and_a_family_partition_are_two_findings(
        self,
    ) -> None:
        """The co-occurrence `CAP_NO_IMPLICATION` cites, measured rather than assumed.

        The first draft of that entry called these two mutually exclusive and
        called the overlap pair possible - both backwards. Overlap really is
        impossible beside this one, because preflight emits the family record
        only on the disjoint branch; an unlabelled tuning side really does land
        beside it, because rows being unlabelled says nothing about the words
        they start with.

        It matters beyond the comment: they share the ceiling 50 and disagree
        about whether the run waits, so a reader who believed they could not
        co-occur would never ask which verdict wins. The blocking one does.
        """
        score = self._score(
            _clean_dataset(shared_families=0, labelled_rows=120, tuning_labelled_rows=0)
        )
        self.assertEqual(
            sorted((cap.condition, cap.blocks) for cap in score.caps),
            [
                ("dataset-split-by-task-family", False),
                ("dataset-tuning-split-empty", True),
            ],
        )
        self.assertEqual(score.status, "BLOCKED")
        self.assertEqual(score.recommended_action, "resplit-dataset")

    def test_a_family_count_that_is_not_a_count_is_refused(self) -> None:
        """`False == 0` is true in Python, so a raw read had a false red in it.

        The adapter used to compare this metric to 0 with no check on what it
        was. A boolean in the field then raised a cap saying the customer's
        split follows their task families, on a payload that never said so, and
        a quoted `"0"` dropped a real cap in silence. `_row_count` states the
        rule this follows: a guard that checks four counts and waves one
        through is the odd-one-out this file already has an issue open about.
        """
        records = [
            {"check": "dataset-provenance", "status": "PASS", "metrics": {"rows": 40}},
            {
                "check": "dataset-split-family",
                "status": "WARN",
                "metrics": {"families": 4, "shared_families": False},
            },
        ]
        with self.assertRaises(MODULE.PreflightInputError) as caught:
            MODULE.dataset_facts_from_preflight(records)
        self.assertIn("shared_families", str(caught.exception))
        # Absent stays absent - the check is conditional, so a record that was
        # never emitted is a measured "nothing to say" and not an error.
        self.assertIsNone(MODULE._shared_family_count(None))
        self.assertEqual(MODULE._shared_family_count(0), 0)

    def test_a_form_list_that_is_not_a_list_of_forms_is_refused(self) -> None:
        """The names are printed on the card, so an unusable list must not pass.

        The sibling above guards the count and this one had no probe at all -
        deleting its validation left the whole suite green, which is the same
        hole one table over. What it lets through is not abstract: these strings
        are quoted into a sentence about the customer's own dataset, so a
        payload carrying numbers here would print `'1', '2'` as the kinds of
        work their split separates.
        """
        for unusable in ([1, 2], "add two", [""], [None]):
            with self.subTest(forms=unusable):
                with self.assertRaises(MODULE.PreflightInputError) as caught:
                    MODULE._family_forms(unusable)
                self.assertIn("unusable form list", str(caught.exception))
        # Absent is legitimate and drops the naming clause, never the finding:
        # a payload predating the names still carries the count.
        self.assertEqual(MODULE._family_forms(None), ())
        self.assertEqual(MODULE._family_forms(["add two "]), ("add two",))
        bare = self._score(_clean_dataset(shared_families=0))
        self.assertEqual(
            [cap.condition for cap in bare.caps], ["dataset-split-by-task-family"]
        )
        self.assertNotIn("Tuned on", bare.caps[0].reason)

    def test_a_split_whose_families_cross_it_raises_nothing(self) -> None:
        """One shared form is enough, and an unread check is not a finding.

        `None` is preflight skipping the check or predating it, and both mean
        the question was not answered. A cap raised on either would be a finding
        about a customer's split that nothing established.
        """
        for label, shared in (("crossed", 4), ("unread", None)):
            with self.subTest(families=label):
                score = self._score(_clean_dataset(shared_families=shared))
                self.assertEqual([cap.condition for cap in score.caps], [])
                self.assertEqual(score.recommended_action, "proceed")

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

    def test_a_bounded_dataset_that_asks_nothing_is_not_handed_a_repair(self) -> None:
        """The durable report, which outlives the terminal the card printed to.

        `action_kind` is keyed by condition, so it survives on every cap in
        `--json` for a machine; what may not appear is the word "fix" over a
        state nothing is wrong with.

        Both fixtures here are the third state: a ceiling that bounds a claim
        and asks the user for nothing. `dataset-fully-synthetic` routes to
        `connect-real-data`, which is a scope on the claim rather than an
        errand, and `dataset-coarse-resolution` routes to `add-examples`, which
        is the case this test was written for - telling a customer with a
        working dataset to go and get more before their first run is the
        conflation `blocks` was added to end.

        The size fixture holds 58 rows split 29 and 29, and both halves of that
        matter. 29 keeps the comparison under thirty, so the resolution ceiling
        still fires and there is a cap to assert about; and 58 comparable rows
        is above the walkthrough's own total, so #197's offer to write the
        difference has nothing to offer and this cap asks nothing. Below that
        total the same condition asks, and the sibling test below is where that
        belongs.

        `dataset-generated-answer-key` used to be a third fixture here and is
        not one any more; it moved to the sibling below when it began to ask.
        """
        for facts in (
            _clean_dataset(
                collected_rows=0, synthesised_rows=240, sources=("synthetic",)
            ),
            _clean_dataset(
                rows=58,
                labelled_rows=58,
                tuning_rows=29,
                holdout_rows=29,
                tuning_labelled_rows=29,
                holdout_labelled_rows=29,
                difficulty_tagged_rows=58,
                collected_rows=58,
                answerable_rows=58,
            ),
        ):
            score = self._score(facts)
            with self.subTest(cap=score.caps[0].condition):
                self.assertFalse(score.caps[0].blocks)
                self.assertFalse(score.caps[0].asks)
                report = MODULE.render_markdown(score)
                self.assertIn(score.caps[0].condition, report)
                self.assertNotIn("fix: `", report)
                # And the payload agrees, which is the half that was never
                # wrong: a cap that asks nothing recommends nothing.
                self.assertEqual(score.recommended_action, MODULE.PROCEED)
                self.assertNotIn(
                    "What is blocking a trustworthy result",
                    report,
                )
                card = MODULE.render_card(
                    score, palette=MODULE.Palette(), unicode_ok=False
                )
                self.assertNotIn("PAID RUN BLOCKED", card)
                self.assertIn(f"LIMITED TO {score.overall}", card)

    def test_a_bounded_dataset_that_asks_is_handed_its_question(self) -> None:
        """The second state, in the artifact that keeps it.

        The report suppressed the remedy for every cap that did not BLOCK,
        which read the rule as two states when `asks` had just made it three.
        So a dataset whose entire answer key was written by a model printed its
        ceiling and its reason with nothing to do about them, in the durable
        file, while `--json` from the same run returned `review-answer-key` -
        and the report is the copy a reader keeps.

        The stop is still absent, which is what makes this the second state and
        not the first: no blocking section, no `PAID RUN BLOCKED`, `status` OK,
        and the ceiling unchanged. Only the errand appears.
        """
        score = self._score(_clean_dataset(generated_answer_rows=240))
        cap = score.caps[0]
        self.assertEqual(cap.condition, "dataset-generated-answer-key")
        self.assertFalse(cap.blocks)
        self.assertTrue(cap.asks)

        report = MODULE.render_markdown(score)
        # The report names the remedy, and it is the same one the payload
        # names - the disagreement this closes was between these two lines.
        self.assertIn(f"fix: `{cap.action_kind}`", report)
        self.assertEqual(score.recommended_action, cap.action_kind)
        self.assertEqual(cap.action_kind, "review-answer-key")
        # Under the limiting heading, never the blocking one.
        self.assertIn("## What limits how high this can score", report)
        self.assertNotIn("What is blocking a trustworthy result", report)
        self.assertEqual(score.status, "OK")
        self.assertEqual(score.overall, MODULE.GENERATED_ANSWER_KEY_CEILING)
        card = MODULE.render_card(score, palette=MODULE.Palette(), unicode_ok=False)
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
        wide = self._evaluation(task_kind="short-answer", probe_scores=((1.0, 0.0),))
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
        declared = next(s for s in declared_none.subscores if s.name == "difficulty")
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
            "a condition is routed and not classified, or classified and not " "routed",
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

        # At the walkthrough's own size: still the coarse-resolution ceiling,
        # and since #197 no longer an offer to add rows, so it is the advisory
        # cap this test needs - one that neither blocks nor asks.
        advisory = MODULE.power_ceiling(MODULE.WALKTHROUGH_DATASET_ROWS)
        self.assertFalse(advisory.blocks)
        self.assertFalse(advisory.asks)
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
        # And `weighted_average` still means what schema 2 says it means: an
        # average over every declared weight. #201 bumped this to 3 while a
        # pillar could drop out of that denominator; that renormalization is
        # gone, so the version went back rather than staying bumped for a
        # change no payload carries.
        self.assertEqual(payload["weighted_average"], 60)
        self.assertNotIn("unmeasured_pillars", payload)


def cap_construction_field(source: str, field: str, default: object) -> dict[str, set]:
    """Every `Cap(...)` in the scorer, mapped condition -> the values it names.

    Read from the AST, for the reason the sibling reader in
    `tests/test_skill_package.py` records: a scan of the module's attributes
    reaches only the caps built at module level, and the two rungs that carry
    this defect are not both there - `dataset-generated-answer-key` is a
    module-level constant and `dataset-mostly-generated-answer-key` is built
    inside `score_provenance`.

    A constant value is returned as itself and anything else as its rendered
    source, because a site may decide at runtime (`blocks=effective_n == 0`)
    and an expression is not a verdict this reader may resolve. The default is
    taken from the dataclass rather than written here, so changing it cannot
    leave every unannotated site read as the wrong thing.
    """
    found: dict[str, set] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "Cap" or not node.args:
            continue
        condition = node.args[0]
        if not isinstance(condition, ast.Constant) or not isinstance(
            condition.value, str
        ):
            continue
        value = default
        for keyword in node.keywords:
            if keyword.arg != field:
                continue
            value = (
                keyword.value.value
                if isinstance(keyword.value, ast.Constant)
                else ast.unparse(keyword.value)
            )
        found.setdefault(condition.value, set()).add(value)
    return found


class OneRemedyOneQuestionTests(unittest.TestCase):
    """Conditions sharing a remedy must agree on whether that remedy is asked.

    The gap every existing table check is blind to. `CAP_CEILING`,
    `ROUTE_CATEGORY`, `CAP_SEVERITY_ORDER` and `ACTION_FOR_CONDITION` are all
    checked for membership and for order, and every one of those checks reads
    a TABLE - so none of them can see a flag that lives on the cap rather than
    in a table. `asks` is exactly that flag, and the state it hid was not
    subtle: three conditions route to `review-answer-key`, one of them set
    `asks=True`, and a dataset whose entire answer key was written by a model
    emitted `recommended_action: "proceed"` beside SKILL.md's instruction to
    have a person review a sample of the answers before a correctness claim.

    So the assertion is at the level the flag is wrong at. `Cap.asks` says in
    its own words that the flag "is a property of `review-answer-key` and not
    of a size" - a property OF THE REMEDY - and `ACTION_FOR_CONDITION` is where
    remedies are decided. Reading that table is therefore the whole guard, and
    a fourth `review-answer-key` rung cannot ship asking nothing.

    Detected, though, and not inherited - the distinction is worth stating
    because the weaker word flatters this guard. `asks` is a per-`Cap` keyword
    defaulting False, so an author adding a condition to `ACTION_FOR_CONDITION`
    and omitting `asks=True` at the call site constructs a perfectly valid cap;
    what happens next is that THIS test goes red, after the fact, rather than
    the value arriving from the remedy. Making the omission unreachable instead
    of caught means keying the flag off the remedy in a table beside
    `ACTION_FOR_CONDITION` and deriving it in `__post_init__` - which changes
    the `Cap` constructor's contract, retires the AST reading below along with
    it, and hard-codes an asymmetry with `blocks` that is deliberately only
    asserted today. That is its own change with its own regression story, and
    it is filed rather than smuggled in here.

    Deliberately `asks` and not every cap field. `blocks` disagrees under
    `get-data` on purpose - `dataset-absent` waits, `dataset-coarse-resolution`
    does not, and `dataset-below-measurable-size` decides at runtime - and
    `ROUTE_CATEGORY`'s own comment records that disagreement as tracked and not
    this rule's call. A ceiling is not remedy-keyed either, and that too is
    written down beside `CAP_SEVERITY_ORDER`: `get-data` spans 20 to 89,
    because "what should the user do" and "how much of the result survives"
    are different questions. `asks` is the one cap field the remedy decides.
    """

    def _declared(self, field: str) -> dict[str, set]:
        source = Path(MODULE.__file__).read_text(encoding="utf-8")
        declared = cap_construction_field(
            source, field, MODULE.Cap.__dataclass_fields__[field].default
        )
        self.assertTrue(declared, "found no Cap construction to check")
        # Every condition observed, so a remedy group cannot be judged on the
        # half of its members this reader happened to find.
        self.assertEqual(
            set(declared),
            set(MODULE.ACTION_FOR_CONDITION),
            "the conditions built and the conditions mapped are not the same set",
        )
        return declared

    def test_conditions_sharing_a_remedy_agree_on_whether_it_asks(self) -> None:
        declared = self._declared("asks")
        by_remedy: dict[str, dict[str, set]] = {}
        for condition, values in declared.items():
            remedy = MODULE.ACTION_FOR_CONDITION[condition]
            by_remedy.setdefault(remedy, {})[condition] = values
        shared = {
            remedy: group for remedy, group in by_remedy.items() if len(group) > 1
        }
        self.assertTrue(shared, "no remedy is carried by two conditions")
        for remedy, group in sorted(shared.items()):
            with self.subTest(remedy=remedy):
                answers = {value for values in group.values() for value in values}
                self.assertEqual(
                    len(answers),
                    1,
                    f"the conditions routing to {remedy!r} disagree about "
                    f"whether it is asked: "
                    f"{ {c: sorted(map(repr, v)) for c, v in sorted(group.items())} }"
                    " - `recommended_action` returns a remedy only for a cap "
                    "that blocks or asks, so the siblings answering False emit "
                    "`proceed` about the same finding the sibling answering "
                    "True routes",
                )

    def test_un_porting_one_sibling_is_caught_here_and_by_no_table(self) -> None:
        """The reverted decision, executed - and why the tables stay green on it.

        The mutation is the state trunk was actually in: one
        `review-answer-key` rung asking, the other two not. It is applied to a
        real copy of the scorer and that copy is imported, so both halves of
        the claim are measured rather than argued.

        Every table survives it untouched, which is the point. A registry maps
        conditions and a flag lives on the cap, so no amount of membership,
        order or round-trip checking over `ACTION_FOR_CONDITION`, `CAP_CEILING`
        or `ROUTE_CATEGORY` can reach it - and that is exactly how a wholly
        model-written answer key came to emit `proceed` under a full green
        suite.
        """
        source = Path(MODULE.__file__).read_text(encoding="utf-8")
        opener = "GENERATED_ANSWER_KEY_CAP = Cap(\n"
        self.assertIn(opener, source, "the un-porting mutation point moved")
        head, _, rest = source.partition(opener)
        construction, closer, tail = rest.partition("\n)\n")
        self.assertIn("asks=True,", construction, "the sibling no longer asks")
        mutated = (
            head
            + opener
            + construction.replace("asks=True,", "asks=False,", 1)
            + closer
            + tail
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "readiness_unported.py"
            path.write_text(mutated, encoding="utf-8")
            spec = importlib.util.spec_from_file_location("readiness_unported", path)
            unported = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = unported
            try:
                spec.loader.exec_module(unported)
            finally:
                sys.modules.pop(spec.name, None)

        # Half one: every table a check could read is identical, so every
        # table-level check passes on the un-ported scorer.
        for table in ("ACTION_FOR_CONDITION", "CAP_CEILING", "ROUTE_CATEGORY"):
            with self.subTest(table=table):
                self.assertEqual(getattr(unported, table), getattr(MODULE, table))
        # And it still constructs: `Cap.__post_init__` fails closed on an
        # unmapped, unranked, unclassified or blocking-and-asking cap, and an
        # un-ported `asks` is none of those.
        self.assertFalse(unported.GENERATED_ANSWER_KEY_CAP.asks)
        self.assertFalse(unported.GENERATED_ANSWER_KEY_CAP.blocks)

        # Half two: this guard's own reading sees it, and the payload does too.
        declared = cap_construction_field(
            mutated, "asks", MODULE.Cap.__dataclass_fields__["asks"].default
        )
        siblings = sorted(
            condition
            for condition, remedy in MODULE.ACTION_FOR_CONDITION.items()
            if remedy == "review-answer-key"
        )
        self.assertGreater(len(siblings), 1)
        self.assertEqual(
            {value for condition in siblings for value in declared[condition]},
            {False, True},
            "the mutation no longer un-ports the sibling it names",
        )
        pillars = [
            unported.Pillar(name=name, score=90, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        reverted = unported.aggregate(
            pillars,
            [unported.GENERATED_ANSWER_KEY_CAP],
            (),
            dict(unported.DEFAULT_WEIGHTS),
        )
        self.assertEqual(reverted.recommended_action, unported.PROCEED)
        kept = MODULE.aggregate(
            [
                MODULE.Pillar(name=name, score=90, confidence=1.0, subscores=())
                for name in ("dataset", "evaluation", "agent")
            ],
            [MODULE.GENERATED_ANSWER_KEY_CAP],
            (),
            dict(MODULE.DEFAULT_WEIGHTS),
        )
        self.assertEqual(kept.recommended_action, "review-answer-key")
        # The ceiling and the verdict are the same on both sides: only the
        # remedy moved, which is what `asks` was added to carry.
        self.assertEqual(reverted.overall, kept.overall)
        self.assertEqual(reverted.status, kept.status)


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
        """Read off the module, so a new check cannot be added unnamed.

        Two readings, because one of them has a blind spot this module walked
        into. The AST scan finds `SubScore("literal", ...)`, which is every
        check written out by hand; #184's four are built in a loop over
        `AGENT_BUILD_CHECKS`, so their first argument is a variable and the scan
        saw none of them - the same class `cap_construction_blocks` records for
        caps built inside a function. The table is therefore read as well, and a
        check declared in either place has to be named.
        """
        source = Path(MODULE.__file__).read_text(encoding="utf-8")
        literal = {
            node.args[0].value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "SubScore"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        }
        return literal | {name for name, _weight in MODULE.AGENT_BUILD_CHECKS}

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


def _brought(rows: int, **extra) -> "MODULE.DatasetFacts":
    """A healthy dataset of rows the user brought, with nothing generated."""
    defaults = dict(
        exists=True,
        rows=rows,
        labelled_rows=rows,
        answerable_rows=rows,
        collected_rows=rows,
        difficulty_bands=("easy", "medium", "hard", "very-hard"),
        difficulty_tagged_rows=rows,
        duplicate_status="PASS",
        near_duplicate_status="PASS",
        sources=("customer-support-export",),
    )
    defaults.update(extra)
    return MODULE.DatasetFacts(**defaults)


def _review(**counts) -> "MODULE.RowReview":
    reviewed = counts.pop("reviewed")
    return MODULE.RowReview(
        supplied=True,
        reviewed=reviewed,
        reviewed_collected=counts.pop("reviewed_collected", reviewed),
        **counts,
    )


class RowLevelSanityTests(unittest.TestCase):
    """The check that reads a row's input beside its own expected output.

    Every other dataset check reads one column: empty golds, constant golds,
    dominant answers, duplicates, split overlap. A row asking about a refund 45
    days after purchase against a 30-day policy, expecting `approve`, passes all
    of them - it is well-formed, unique, difficulty-tagged and perfectly
    scoreable, and simply wrong. These tests pin what happens when the assistant
    says so, and - more importantly - what may not happen when it says nothing
    is wrong.
    """

    def test_a_clean_review_leaves_the_score_exactly_where_no_review_left_it(
        self,
    ) -> None:
        """The load-bearing rule, proven by construction rather than asserted.

        An assistant's opinion may withhold a claim; it may not manufacture one.
        So the entire difference between "reviewed, all fine" and "not reviewed"
        has to be words: same sub-score values, same maxima, same caps, same
        pillar score and confidence.
        """
        facts = _brought(28, tuning_rows=18, holdout_rows=10)
        unreviewed, unreviewed_caps = MODULE.score_dataset(facts, "normalized-exact")
        reviewed, reviewed_caps = MODULE.score_dataset(
            facts, "normalized-exact", _review(reviewed=28)
        )
        self.assertEqual(reviewed.score, unreviewed.score)
        self.assertEqual(reviewed.confidence, unreviewed.confidence)
        self.assertEqual(
            [(s.name, s.value, s.maximum, s.measured) for s in reviewed.subscores],
            [(s.name, s.value, s.maximum, s.measured) for s in unreviewed.subscores],
        )
        self.assertEqual(
            [cap.condition for cap in reviewed_caps],
            [cap.condition for cap in unreviewed_caps],
        )
        # ... and the only thing that did change is the sentence, which names
        # who did the checking.
        differing = [
            (before.name, after.evidence)
            for before, after in zip(unreviewed.subscores, reviewed.subscores)
            if before.evidence != after.evidence
        ]
        self.assertEqual([name for name, _ in differing], ["labels"])
        self.assertIn("the coding assistant read 28 of 28", differing[0][1])
        self.assertIn("none contradicts its own input", differing[0][1])

    def test_a_material_share_of_wrong_answers_lowers_the_ceiling(self) -> None:
        facts = _brought(28, tuning_rows=18, holdout_rows=10)
        _, caps = MODULE.score_dataset(
            facts, "normalized-exact", _review(reviewed=28, unsound=3)
        )
        cap = next(c for c in caps if c.condition == "dataset-unsound-expected-outputs")
        self.assertEqual(cap.ceiling, MODULE.UNSOUND_ANSWER_CEILING)
        self.assertLess(cap.ceiling, MODULE.GENERATED_ANSWER_KEY_CEILING)
        # The remedy is the one the table already carries. A wrong answer key
        # and an unobserved one are the same ask: a person looks at it.
        self.assertEqual(cap.action_kind, "review-answer-key")
        self.assertIn("3 answers do not answer their own question", cap.reason)
        # Declared as a reading, never as a measurement, and never as an edit.
        self.assertIn("coding assistant's reading, not a measurement", cap.reason)
        self.assertIn("nothing is edited until you answer", cap.reason)
        # And it bounds rather than stops - the decision this cap exists to
        # make. See `TheUnsoundAnswerCapBoundsRatherThanBlocksTests` for why.
        self.assertFalse(cap.blocks)

    def test_one_wrong_answer_is_reported_without_bounding_the_whole_run(
        self,
    ) -> None:
        """Below the share, the finding is a question - not a ceiling.

        It is still surfaced: the count is in the evidence line, and the flow
        puts every `no` to the user. What it does not do is cap a 28-row dataset
        on one row, which would let a single arguable reading decide the band.
        """
        facts = _brought(28, tuning_rows=18, holdout_rows=10)
        pillar, caps = MODULE.score_dataset(
            facts, "normalized-exact", _review(reviewed=28, unsound=1)
        )
        self.assertEqual(
            [c for c in caps if c.condition == "dataset-unsound-expected-outputs"], []
        )
        labels = next(s for s in pillar.subscores if s.name == "labels")
        self.assertIn("1 expected answer contradicts its input", labels.evidence)

    def test_an_undecided_row_is_named_and_never_scored(self) -> None:
        """Uncertainty is reported; it does not grade the user's data."""
        facts = _brought(20, tuning_rows=12, holdout_rows=8)
        pillar, caps = MODULE.score_dataset(
            facts, "normalized-exact", _review(reviewed=20, unsure=9)
        )
        self.assertEqual(
            [c for c in caps if c.condition == "dataset-unsound-expected-outputs"], []
        )
        labels = next(s for s in pillar.subscores if s.name == "labels")
        self.assertIn("9 undecided", labels.evidence)

    def test_the_review_never_moves_a_score_upwards(self) -> None:
        """Swept over every verdict mixture, at the sub-score and cap level.

        The cap-set assertion is not decoration. "Cannot raise the score" has a
        second reading that a ceiling check alone misses entirely: a review that
        DELETES a cap someone else raised lifts the score without ever adding a
        point. So the fixture deliberately carries a cap the review has no
        business touching - the tuning/held-out overlap, which is measured from
        the user's files - and every mixture must keep it.
        """
        facts = _brought(30, tuning_rows=20, holdout_rows=10, split_overlap=True)
        baseline, baseline_caps = MODULE.score_dataset(facts, "normalized-exact")
        base_conditions = {cap.condition for cap in baseline_caps}
        self.assertIn("dataset-tune-holdout-overlap", base_conditions)
        base_ceiling = min([c.ceiling for c in baseline_caps], default=100)
        for unsound in range(0, 31):
            for unsure in range(0, 31 - unsound):
                with self.subTest(unsound=unsound, unsure=unsure):
                    pillar, caps = MODULE.score_dataset(
                        facts,
                        "normalized-exact",
                        _review(reviewed=30, unsound=unsound, unsure=unsure),
                    )
                    self.assertEqual(pillar.score, baseline.score)
                    self.assertLessEqual(
                        min([c.ceiling for c in caps], default=100), base_ceiling
                    )
                    self.assertLessEqual(
                        base_conditions, {cap.condition for cap in caps}
                    )

    def test_the_evidence_line_says_how_much_of_the_dataset_was_read(self) -> None:
        """Readiness scores the whole dataset, so the line cannot imply otherwise."""
        facts = _brought(4812, tuning_rows=4000, holdout_rows=812)
        pillar, _ = MODULE.score_dataset(
            facts, "normalized-exact", _review(reviewed=28)
        )
        labels = next(s for s in pillar.subscores if s.name == "labels")
        self.assertIn("read 28 of 4812 provided rows", labels.evidence)

    def test_generated_rows_are_out_of_scope_and_the_line_says_so(self) -> None:
        facts = _brought(
            28,
            collected_rows=18,
            synthesised_rows=10,
            tuning_rows=18,
            holdout_rows=10,
        )
        pillar, _ = MODULE.score_dataset(
            facts, "normalized-exact", _review(reviewed=18)
        )
        labels = next(s for s in pillar.subscores if s.name == "labels")
        self.assertIn("read 18 of 18 provided rows", labels.evidence)
        self.assertIn("10 generated rows not reviewed", labels.evidence)

    def test_a_reference_free_judge_reads_no_expected_output_so_none_can_cap(
        self,
    ) -> None:
        """The same question `score_provenance` already asks about a generated key.

        A rubric judge scores from the input and the rubric; the expected output
        is not an input to it, so a wrong one mis-ranks nothing and there is no
        claim to withhold. The reading is still reported.
        """
        facts = _brought(28, tuning_rows=18, holdout_rows=10)
        pillar, caps = MODULE.score_dataset(
            facts, "llm-judge-rubric", _review(reviewed=28, unsound=14)
        )
        self.assertEqual(
            [c for c in caps if c.condition == "dataset-unsound-expected-outputs"], []
        )
        labels = next(s for s in pillar.subscores if s.name == "labels")
        self.assertIn("14 expected answers contradict their input", labels.evidence)

    def test_a_dataset_with_no_expected_outputs_keeps_the_harder_ceiling(self) -> None:
        """Nothing to be wrong about, and the 30 ceiling already binds anyway."""
        facts = _brought(28, labelled_rows=0, answerable_rows=0)
        _, caps = MODULE.score_dataset(
            facts, "normalized-exact", _review(reviewed=28, unsound=28)
        )
        ceilings = {cap.condition: cap.ceiling for cap in caps}
        self.assertEqual(ceilings["dataset-no-expected-outputs"], 30)
        self.assertLess(30, MODULE.UNSOUND_ANSWER_CEILING)

    def test_a_strong_project_is_bounded_and_routed_to_the_answer_key(self) -> None:
        """The whole point, at the level the user sees: STRONG becomes WORKABLE.

        A dataset good enough to score 89 is exactly the one this check exists
        for - nothing else in the card has anything to say about it, so the
        number is confident and the rows it is measured on are wrong.
        """
        facts = _brought(28, tuning_rows=18, holdout_rows=10)
        evaluation = MODULE.Pillar("evaluation", 100, 1.0, ())
        agent = MODULE.Pillar("agent", 91, 1.0, ())
        weights = dict(MODULE.DEFAULT_WEIGHTS)

        def total(review) -> MODULE.ReadinessScore:
            pillar, caps = MODULE.score_dataset(facts, "normalized-exact", review)
            return MODULE.aggregate([pillar, evaluation, agent], caps, (), weights)

        before = total(None)
        after = total(_review(reviewed=28, unsound=3))
        self.assertEqual(before.band, "STRONG")
        self.assertEqual(after.band, "WORKABLE")
        self.assertEqual(after.overall, MODULE.UNSOUND_ANSWER_CEILING)
        self.assertLess(after.overall, before.overall)
        # Same weighted average - the pillars did not move. Only the ceiling did.
        self.assertEqual(after.weighted_average, before.weighted_average)
        # The score drops, the run is not stopped, AND the remedy is still
        # named. That third state is the one the payload could not express:
        # `blocks=True` said stop-and-fix, `blocks=False` alone said carry-on
        # with nothing to do, and this condition is neither. `status` stays OK
        # - the run is worth making - while `recommended_action` carries the
        # question, because doing it changes the answer key the run is about to
        # be graded against.
        self.assertEqual(after.status, "OK")
        self.assertEqual(before.status, "OK")
        self.assertEqual(after.recommended_action, "review-answer-key")
        self.assertEqual(before.recommended_action, "proceed")
        cap = next(
            cap
            for cap in after.caps
            if cap.condition == "dataset-unsound-expected-outputs"
        )
        # The two flags, asserted in both directions, because no test asserted
        # either one and the default gave this cap the opposite of both.
        self.assertFalse(cap.blocks, "a reading of the answer key stopped a paid run")
        self.assertTrue(cap.asks, "the remedy would not reach the payload")
        self.assertEqual(cap.action_kind, "review-answer-key")
        # And a clean reading of the same dataset changes neither.
        clean = total(_review(reviewed=28))
        self.assertEqual(clean.overall, before.overall)
        self.assertEqual(clean.band, before.band)
        self.assertEqual(clean.recommended_action, before.recommended_action)

    def test_a_bounded_cap_that_asks_still_names_its_remedy(self) -> None:
        """The third state, asserted where the payload expresses it.

        `blocks` alone had two values and this condition needs a third reading.
        `True` stopped a paid run over the assistant's own opinion; `False` on
        its own returned `recommended_action` to `proceed`, so the payload said
        there was nothing to do about a finding whose entire content is a
        question for the user.
        """
        pillars = [
            MODULE.Pillar(name=name, score=90, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        cap = MODULE.unsound_answer_cap(_review(reviewed=28, unsound=3))
        score = MODULE.aggregate(pillars, [cap], (), dict(MODULE.DEFAULT_WEIGHTS))
        self.assertEqual(score.status, "OK")
        self.assertEqual(score.recommended_action, "review-answer-key")

    def test_a_ceiling_that_asks_nothing_still_recommends_nothing(self) -> None:
        """The false-red direction, and the conflation this must not restore.

        A dataset the run cannot add to is bounded and has no question behind
        it. Telling a customer to go and get more data before their first run
        is the defect `blocks` was added to end, so an advisory ceiling that
        does not ask keeps `proceed`.

        The count is the walkthrough's own total. Below it #197 turns this cap
        into an offer to write the difference, which is a question and is
        routed as one by the sibling test; at it and above there is nothing to
        offer, the ceiling still stands on the resolution, and this is the
        false-red direction that must stay silent.
        """
        pillars = [
            MODULE.Pillar(name=name, score=90, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        advisory = MODULE.power_ceiling(MODULE.WALKTHROUGH_DATASET_ROWS)
        self.assertEqual(advisory.condition, "dataset-coarse-resolution")
        self.assertFalse(advisory.blocks)
        self.assertFalse(advisory.asks)
        score = MODULE.aggregate(pillars, [advisory], (), dict(MODULE.DEFAULT_WEIGHTS))
        self.assertEqual(score.status, "OK")
        self.assertEqual(score.recommended_action, MODULE.PROCEED)

    def test_a_blocking_cap_still_wins_over_one_that_only_asks(self) -> None:
        """A run that is waiting has nothing else as its next step."""
        pillars = [
            MODULE.Pillar(name=name, score=90, confidence=1.0, subscores=())
            for name in ("dataset", "evaluation", "agent")
        ]
        asking = MODULE.unsound_answer_cap(_review(reviewed=28, unsound=3))
        blocking = MODULE.Cap("evaluator-invalid", 25, "broken")
        score = MODULE.aggregate(
            pillars, [asking, blocking], (), dict(MODULE.DEFAULT_WEIGHTS)
        )
        self.assertEqual(score.status, "BLOCKED")
        self.assertEqual(score.recommended_action, "repair-evaluator")

    def test_a_cap_cannot_both_block_and_ask(self) -> None:
        with self.assertRaises(ValueError) as caught:
            MODULE.Cap("evaluator-invalid", 25, "broken", blocks=True, asks=True)
        self.assertIn("both blocks and asks", str(caught.exception))

    def test_the_cap_reads_the_share_of_what_was_actually_read(self) -> None:
        """The share is over reviewed rows, which is the only population it saw."""
        self.assertIsNone(MODULE.unsound_answer_cap(_review(reviewed=100, unsound=9)))
        self.assertIsNotNone(
            MODULE.unsound_answer_cap(_review(reviewed=100, unsound=10))
        )
        self.assertIsNone(MODULE.unsound_answer_cap(MODULE.RowReview()))


class TheUnsoundAnswerCapBoundsRatherThanBlocksTests(unittest.TestCase):
    """It lowers what the run may claim; it does not cancel the run.

    Three things decide this, and each is asserted here rather than argued in
    a comment nobody runs.

    The run only reads 28 rows. A broken row the search never opens stops
    nothing, so the cap's own sentence has to distinguish the two cases before
    it is entitled to say anything about the run at all.

    The judgement can be wrong. It is a model's reading of a customer's domain,
    and an opinion that can be wrong may bound a claim and may not cancel a
    paid run the customer's own 28 sound rows would have earned.

    And the remedy decides it. `review-answer-key` is a question put to the
    customer - not a creation, not a repair - so under the rule on
    `Cap.blocks` it is advisory. The last test here is the one that matters:
    one remedy slug may not carry two opposite behaviours.
    """

    facts = _brought(28, tuning_rows=18, holdout_rows=10)

    def _cap(self, **counts) -> "MODULE.Cap":
        _, caps = MODULE.score_dataset(
            self.facts, "normalized-exact", _review(**counts)
        )
        return next(
            cap for cap in caps if cap.condition == "dataset-unsound-expected-outputs"
        )

    def _both_answer_key_caps(self) -> list["MODULE.Cap"]:
        """One dataset that raises BOTH `review-answer-key` conditions.

        Every answer written by a model (the provenance cap) and some of them
        disagreeing with their own questions (the row-level cap) are not
        alternatives - a generated key is exactly where unsound rows come from,
        so this is the ordinary case, not a contrived one.
        """
        facts = _brought(28, tuning_rows=18, holdout_rows=10, generated_answer_rows=28)
        _, caps = MODULE.score_dataset(
            facts, "normalized-exact", _review(reviewed=28, unsound=3)
        )
        return [
            cap
            for cap in caps
            if MODULE.ACTION_FOR_CONDITION[cap.condition] == "review-answer-key"
        ]

    def _middle_rung_answer_key_caps(self) -> list["MODULE.Cap"]:
        """The same, on the answer-key ladder's middle rung.

        The full rung and the middle rung are mutually exclusive branches, so
        one dataset can never show both and the fixture above reaches only the
        first. This branch's own base had no middle rung; the branch that added
        it could not see this test. Between them the two fixtures observe all
        three conditions that route to `review-answer-key`, which is what the
        last assertion needs in order to mean what it says.
        """
        facts = _brought(28, tuning_rows=18, holdout_rows=10, generated_answer_rows=20)
        _, caps = MODULE.score_dataset(
            facts, "normalized-exact", _review(reviewed=28, unsound=3)
        )
        return [
            cap
            for cap in caps
            if MODULE.ACTION_FOR_CONDITION[cap.condition] == "review-answer-key"
        ]

    def test_the_run_is_not_stopped_and_the_ceiling_still_binds(self) -> None:
        """Bounding is not silence: the number moves, the run does not stop."""
        cap = self._cap(reviewed=28, unsound=3)
        self.assertFalse(cap.blocks)
        self.assertEqual(cap.ceiling, MODULE.UNSOUND_ANSWER_CEILING)
        self.assertIn("The run is not stopped", cap.reason)
        self.assertIn("what it may claim is bounded", cap.reason)

    def test_the_remedy_is_a_question_and_it_is_the_sibling_cap_s_remedy(
        self,
    ) -> None:
        """The routing half of the argument, read off the table not a comment.

        `review-answer-key` is a question put to the customer, and
        `dataset-generated-answer-key` already carries it. What this asserts is
        that the two conditions share one remedy AND one verdict.

        The earlier version stopped at the slug and then checked one side, and
        that gap is exactly where the defect lived: this branch shipped
        `dataset-generated-answer-key` blocking and
        `dataset-unsound-expected-outputs` not, under a single remedy - and the
        blocking one carried the LOOSER ceiling, so the stricter finding
        proceeded while the weaker one stopped the run. The docstring above
        already said "one remedy slug may not carry two opposite behaviours";
        nothing executed it.

        So both sides are read from the caps the scorer actually builds, not
        from the table. A remedy is a claim about what the customer should do
        next, and a consumer routing on it cannot act on two answers.
        """
        siblings = sorted(
            condition
            for condition, action in MODULE.ACTION_FOR_CONDITION.items()
            if action == "review-answer-key"
        )
        self.assertEqual(
            siblings,
            [
                "dataset-generated-answer-key",
                # The ladder's middle rung, which shares this remedy and did
                # not exist on the base this test was written against.
                "dataset-mostly-generated-answer-key",
                "dataset-unsound-expected-outputs",
            ],
        )
        verdicts = {
            cap.condition: cap.blocks
            for cap in self._both_answer_key_caps()
            + self._middle_rung_answer_key_caps()
        }
        self.assertEqual(
            sorted(verdicts), siblings, "every sibling cap must be observed"
        )
        self.assertEqual(
            len(set(verdicts.values())),
            1,
            f"one remedy, two verdicts: {verdicts} - a consumer routing on "
            "`review-answer-key` cannot act on two answers",
        )
        self.assertFalse(self._cap(reviewed=28, unsound=3).blocks)

    def test_a_flagged_row_outside_the_run_is_not_reported_as_one_inside_it(
        self,
    ) -> None:
        """The difference between a bad row in the file and a bad row in the run."""
        undrawn = self._cap(reviewed=28, unsound=3)
        self.assertIn("somewhere in the file this run draws from", undrawn.reason)

        outside = self._cap(reviewed=28, unsound=3, unsound_in_run=0)
        self.assertIn("outside the rows this run tunes and checks on", outside.reason)
        self.assertNotIn("about to be graded", outside.reason)

        inside = self._cap(reviewed=28, unsound=3, unsound_in_run=2)
        self.assertIn("2 of them among the 28 rows this run tunes", inside.reason)
        self.assertIn("about to be graded against them", inside.reason)

    def test_the_row_count_comes_from_the_declared_split_and_never_from_28(
        self,
    ) -> None:
        """28 is what this walkthrough creates, not what every customer brought."""
        self.assertEqual(MODULE.run_rows(self.facts), 28)
        self.assertEqual(
            MODULE.run_rows(_brought(400, tuning_rows=300, holdout_rows=100)), 400
        )
        # No split declared, so no number may be printed for one.
        self.assertIsNone(MODULE.run_rows(_brought(400)))
        cap = MODULE.unsound_answer_cap(
            _review(reviewed=28, unsound=3, unsound_in_run=2),
            MODULE.run_rows(_brought(400)),
        )
        self.assertIn("among the rows this run tunes", cap.reason)
        self.assertNotIn("28 rows this run", cap.reason)


class MeasuredOpeningInvocationTests(unittest.TestCase):
    """A score gets one source of component state, not a declaration too.

    This is deliberately a CLI-boundary test.  The former implementation
    silently ignored the declarations, so testing the guide's prose could not
    catch the exact command a fresh worker sent in Case 08.
    """

    @staticmethod
    def _run(argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = MODULE.run(argv)
        return code, out.getvalue(), err.getvalue()

    def test_scoring_evidence_refuses_declared_component_state_flags(self) -> None:
        for evidence_flag, evidence_value in (
            ("--preflight", "opening.json"),
            ("--agent-knobs", "agent-read.json"),
            ("--calibration", "calibration.json"),
            ("--config-space", "config-space.json"),
        ):
            for flag, value in (
                ("--agent", "invalid"),
                ("--dataset", "real"),
                ("--evaluation", "invalid"),
            ):
                with self.subTest(evidence=evidence_flag, declaration=flag):
                    code, stdout, stderr = self._run(
                        [evidence_flag, evidence_value, flag, value]
                    )
                    self.assertEqual(code, 2)
                    self.assertEqual(stdout, "")
                    self.assertIn(
                        "cannot mix declared component state with scoring evidence",
                        stderr,
                    )
                    self.assertIn(evidence_flag, stderr)
                    self.assertIn(flag, stderr)

    def test_planning_still_accepts_the_three_declared_states_without_evidence(
        self,
    ) -> None:
        code, _stdout, stderr = self._run(
            ["--agent", "invalid", "--dataset", "real", "--evaluation", "invalid"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")


class RowReviewInputTests(unittest.TestCase):
    """What the scorer refuses to accept as a reading.

    This is the one input allowed to lower a score on nothing but its own word,
    so it is also the one input that may not be quietly repaired into a usable
    shape.
    """

    facts = _brought(30, collected_rows=25, undeclared_rows=5)

    def _read(self, document) -> "MODULE.RowReview":
        return MODULE.row_review_from_document(document, self.facts)

    @staticmethod
    def _rows(*entries) -> dict:
        return {"reviewer": "assistant", "rows": list(entries)}

    @staticmethod
    def _entry(**overrides) -> dict:
        entry = {
            "id": "row-1",
            "origin": "collected",
            "verdict": "yes",
            "note": "the expected answer follows from the input",
        }
        entry.update(overrides)
        return entry

    def test_a_reading_attributed_to_the_user_is_refused(self) -> None:
        with self.assertRaises(MODULE.RowReviewInputError) as raised:
            self._read({"reviewer": "user", "rows": [self._entry()]})
        self.assertIn(
            "arrives as an answer to the approval-gated question", str(raised.exception)
        )

    def test_a_generated_row_is_refused_rather_than_dropped(self) -> None:
        with self.assertRaises(MODULE.RowReviewInputError) as raised:
            self._read(self._rows(self._entry(origin="synthesised")))
        self.assertIn("re-judging its own output", str(raised.exception))

    def test_only_normalized_review_origins_are_accepted(self) -> None:
        review = self._read(self._rows(self._entry(origin="collected")))
        self.assertEqual(review.reviewed_collected, 1)
        with self.assertRaises(MODULE.RowReviewInputError) as raised:
            self._read(self._rows(self._entry(origin="real")))
        self.assertIn("provenance class preflight assigned", str(raised.exception))

    def test_every_verdict_carries_a_sentence(self) -> None:
        for note in (None, "", "   "):
            with self.subTest(note=note):
                with self.assertRaises(MODULE.RowReviewInputError):
                    self._read(self._rows(self._entry(note=note)))

    def test_a_verdict_without_a_row_id_is_refused(self) -> None:
        with self.assertRaises(MODULE.RowReviewInputError):
            self._read(self._rows(self._entry(id="")))

    def test_a_repeated_row_cannot_inflate_the_share(self) -> None:
        with self.assertRaises(MODULE.RowReviewInputError) as raised:
            self._read(self._rows(self._entry(verdict="no"), self._entry(verdict="no")))
        self.assertIn("inflates the share", str(raised.exception))

    def test_an_unknown_verdict_is_refused(self) -> None:
        with self.assertRaises(MODULE.RowReviewInputError):
            self._read(self._rows(self._entry(verdict="probably")))

    def test_a_review_cannot_claim_more_rows_than_the_dataset_holds(self) -> None:
        entries = [
            self._entry(id=f"row-{index}", origin="undeclared") for index in range(6)
        ]
        with self.assertRaises(MODULE.RowReviewInputError) as raised:
            self._read(self._rows(*entries))
        self.assertIn("not the same dataset", str(raised.exception))

    def test_an_empty_review_is_refused_rather_than_read_as_all_clear(self) -> None:
        for document in ({"reviewer": "assistant", "rows": []}, "assistant", []):
            with self.subTest(document=document):
                with self.assertRaises(MODULE.RowReviewInputError):
                    self._read(document)

    def test_a_well_formed_reading_is_counted_by_verdict_and_origin(self) -> None:
        review = self._read(
            self._rows(
                self._entry(id="a", verdict="yes"),
                self._entry(
                    id="b", verdict="no", note="45 days against a 30-day window"
                ),
                self._entry(id="c", verdict="unsure", note="the row omits the plan"),
                self._entry(id="d", origin="undeclared", note="reads correctly"),
            )
        )
        self.assertTrue(review.supplied)
        self.assertEqual(review.reviewed, 4)
        self.assertEqual(review.unsound, 1)
        self.assertEqual(review.unsure, 1)
        self.assertEqual(review.reviewed_collected, 3)
        self.assertEqual(review.reviewed_undeclared, 1)
        # No entry answered `in_run`, so the review says nothing about it - and
        # `None` is that silence, never "none of them".
        self.assertIsNone(review.unsound_in_run)

    def test_a_half_answered_in_run_is_refused_rather_than_read_as_outside(
        self,
    ) -> None:
        """The silent rows would count as outside the run, which understates it.

        That is the direction of error that favours proceeding, so it is the
        one shape this input may not be quietly repaired into.
        """
        with self.assertRaises(MODULE.RowReviewInputError) as raised:
            self._read(
                self._rows(
                    self._entry(id="a", verdict="no", in_run=True, note="wrong"),
                    self._entry(id="b", verdict="no", note="wrong too"),
                )
            )
        self.assertIn("for some rows and not others", str(raised.exception))

    def test_in_run_is_a_boolean_and_counted_only_for_the_flagged_rows(self) -> None:
        review = self._read(
            self._rows(
                self._entry(id="a", verdict="no", in_run=True, note="wrong"),
                self._entry(id="b", verdict="no", in_run=False, note="wrong"),
                self._entry(id="c", verdict="yes", in_run=True, note="reads right"),
            )
        )
        self.assertEqual(review.unsound, 2)
        self.assertEqual(review.unsound_in_run, 1)
        with self.assertRaises(MODULE.RowReviewInputError) as raised:
            self._read(self._rows(self._entry(in_run="yes")))
        self.assertIn("true or false or absent", str(raised.exception))

    def test_a_review_cannot_place_more_rows_in_the_run_than_the_run_has(
        self,
    ) -> None:
        """The same check the origin counts already get, against the split."""
        facts = _brought(30, collected_rows=30, tuning_rows=2, holdout_rows=1)
        entries = [self._entry(id=f"row-{index}", in_run=True) for index in range(4)]
        with self.assertRaises(MODULE.RowReviewInputError) as raised:
            MODULE.row_review_from_document(self._rows(*entries), facts)
        self.assertIn("more rows in the run than the run has", str(raised.exception))


class AbsentAndConsentedIsNotTheSameAsBrokenTests(unittest.TestCase):
    """#211's decision, and the four states it is not allowed to touch.

    The guide now asks once, at discovery, before anything is built: these
    components are missing, generated material is weaker evidence, proceed or
    point me at yours. That consent removes a stop and nothing else. It removes
    it only where nothing is broken - a corpus whose rows parse and whose only
    absence is a word saying who wrote them - and it may never remove one from a
    condition that is a defect rather than a gap.
    """

    def _undeclared(self, rows: int = 200) -> MODULE.Cap:
        _points, _evidence, caps = MODULE.score_provenance(
            MODULE.DatasetFacts(
                exists=True,
                rows=rows,
                labelled_rows=rows,
                undeclared_rows=rows,
            )
        )
        return next(
            cap for cap in caps if cap.condition == "dataset-undeclared-provenance"
        )

    def _declared(self, rows: int = 200) -> MODULE.Cap:
        _points, _evidence, caps = MODULE.score_provenance(
            MODULE.DatasetFacts(
                exists=True,
                rows=rows,
                labelled_rows=rows,
                synthesised_rows=rows,
            )
        )
        return next(cap for cap in caps if cap.condition == "dataset-fully-synthetic")

    def test_the_undeclared_twin_agrees_with_the_declared_one_but_for_its_question(
        self,
    ) -> None:
        """The invariant #165 wrote in prose, now derivable rather than quoted.

        "Identical ceilings, because the assumption IS generated and only the
        remedy differs." It stopped being true at a merge: the declared rungs
        became advisory on one branch while the undeclared pair stayed
        blocking on another, and both landed clean. Asserted here so the pair
        cannot drift apart again silently, and asserted as a PAIR - the two
        rungs, against their two twins - because the earlier version of this
        claim lived in a comment that nothing read.
        """
        for undeclared, declared in (
            ("dataset-undeclared-provenance", "dataset-fully-synthetic"),
            ("dataset-mostly-undeclared", "dataset-mostly-synthetic"),
        ):
            with self.subTest(condition=undeclared):
                self.assertEqual(
                    MODULE.CAP_CEILING[undeclared], MODULE.CAP_CEILING[declared]
                )
                self.assertEqual(
                    MODULE.ROUTE_CATEGORY[undeclared],
                    MODULE.ROUTE_CATEGORY[declared],
                    "the twins disagree about whether the run waits, which is "
                    "the state #211 was filed about",
                )
                self.assertEqual(
                    MODULE.ROUTE_CATEGORY[undeclared], MODULE.CLAIM_SCOPING
                )
                # And the remedies still differ, which is the half #165 was
                # right about: telling a customer to connect real data is wrong
                # when the data may already be real and merely unlabelled.
                self.assertNotEqual(
                    MODULE.ACTION_FOR_CONDITION[undeclared],
                    MODULE.ACTION_FOR_CONDITION[declared],
                )

    def test_the_question_survives_the_stop_it_replaced(self) -> None:
        """Dropping the block may not drop the remedy with it.

        `blocks=False` on its own returns `proceed`, which is how a ceiling
        with nothing a reader could act on gets printed. The asking tier is
        what carries `declare-data-provenance` to the pre-spend approval
        instead, and the declared twin stays silent there because it has
        already answered the question.
        """
        undeclared = self._undeclared()
        declared = self._declared()
        self.assertFalse(undeclared.blocks)
        self.assertTrue(undeclared.asks)
        self.assertFalse(declared.asks)
        self.assertEqual(
            MODULE.recommended_action([undeclared]), "declare-data-provenance"
        )
        self.assertEqual(MODULE.recommended_action([declared]), MODULE.PROCEED)

    def test_consenting_cannot_raise_a_number(self) -> None:
        """The consent removes the stop, never the score.

        Two ways it could have leaked into the number, and both are refused
        here. The ceiling is unchanged from the blocking version, and the
        undeclared rungs still sit at or below every ceiling their declared
        twins carry - so nothing about being asked instead of stopped buys a
        point. The scorer has no consent input at all, which is the structural
        half: there is no flag a run could set to say "the user agreed", so no
        answer at the ask can reach this arithmetic.
        """
        self.assertEqual(self._undeclared().ceiling, MODULE.FULLY_SYNTHETIC_CEILING)
        self.assertLessEqual(self._undeclared().ceiling, self._declared().ceiling)
        # An undeclared row still scores no better than a declared generated
        # one; the ask changed the routing, not the arithmetic.
        self.assertLessEqual(
            MODULE.UNDECLARED_ROW_POINTS, MODULE.SYNTHESISED_ROW_POINTS
        )
        options = set(
            re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', SCRIPT.read_text())
        )
        # The fixture reaches the branch: these are the real flags, not an
        # empty set that would make the loop below vacuous.
        self.assertIn("--preflight", options)
        for option in sorted(options):
            for word in ("consent", "approv", "agree", "ok"):
                with self.subTest(option=option, word=word):
                    self.assertNotIn(
                        word,
                        option,
                        f"{option} could let an answer at the ask reach the "
                        "score, and the ask is not allowed to move a number",
                    )

    def test_the_four_broken_states_still_wait(self) -> None:
        """Absent-and-consented is not the same as broken, and these are broken.

        Each is a defect rather than a gap: an evaluator proven unable to
        separate a right answer from a wrong one, rows that could not be read
        as data, a tuning set that shares examples with the set held back to
        check it, and a file no row of which matched the shape it was read
        with. None of them is something a user can consent to at discovery,
        because in each case the run cannot produce a number worth consenting
        about.
        """
        _pillar, evaluator_caps = MODULE.score_evaluation(
            MODULE.EvaluationFacts(
                present=True,
                method="exact",
                calibration_present=True,
                calibration_supplied=True,
                checks=(
                    {"non_constant": False, "bad_fails": False, "good_passes": True},
                ),
            )
        )
        _pillar, overlap_caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True,
                rows=200,
                labelled_rows=200,
                collected_rows=200,
                split_overlap=True,
            )
        )
        _pillar, integrity_caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=True,
                rows=200,
                labelled_rows=200,
                collected_rows=200,
                integrity_failed=True,
            )
        )
        _pillar, unreadable_caps = MODULE.score_dataset(
            MODULE.DatasetFacts(
                exists=False,
                dataset_supplied=True,
                unreadable_rows=3,
                unreadable_detail="3/3 rows (100.0%) are unusable",
            )
        )
        found = {
            cap.condition: cap
            for caps in (
                evaluator_caps,
                overlap_caps,
                integrity_caps,
                unreadable_caps,
            )
            for cap in caps
        }
        for condition in (
            "evaluator-invalid",
            "dataset-tune-holdout-overlap",
            "dataset-integrity-fail",
            "dataset-shape-unrecognised",
        ):
            with self.subTest(condition=condition):
                # The fixture actually reached the branch, rather than the
                # assertion passing over a cap that never fired.
                self.assertIn(condition, found)
                self.assertTrue(
                    found[condition].blocks,
                    f"{condition} is a defect, and consent at discovery covers "
                    "absence only",
                )
                self.assertNotEqual(
                    MODULE.ROUTE_CATEGORY[condition], MODULE.CLAIM_SCOPING
                )
                self.assertEqual(
                    MODULE.recommended_action([found[condition]]),
                    found[condition].action_kind,
                )


class TheDatasetSizeLadderTests(unittest.TestCase):
    """One remedy per verdict, and an offer bounded at the size we build (#197).

    Three conditions used to emit `get-data`. Measured through `power_ceiling`
    on trunk `6de98918`: it blocked for an absent dataset, blocked at zero
    comparable rows, and proceeded from one row to twenty-nine. So a consumer
    switching on `recommended_action` could not tell "there is no dataset" from
    "your dataset is small", and a person reading the card got one instruction
    whose meaning was decided by a field beside it.

    The fix is the remedy, not a restatement of the rule: two instructions, two
    slugs, and a third condition for the finding that was travelling inside the
    first one as a runtime branch. What these assert is the owner's table -
    nothing to compare stops, anything to compare does not, and below the size
    this guide builds for a project with none the card offers the difference.
    """

    def test_the_ladder_is_the_one_the_owner_drew(self) -> None:
        """Every rung, executed, with no declared split so the counts agree.

        Written as the whole table rather than as a rung per test, because the
        defect was never in one rung: it was in two rungs disagreeing, which
        only a table can state.
        """
        walkthrough = MODULE.WALKTHROUGH_DATASET_ROWS
        expected = {
            0: ("dataset-tuning-split-empty", "resplit-dataset", True, False),
            1: ("dataset-below-measurable-size", "add-examples", False, True),
            9: ("dataset-below-measurable-size", "add-examples", False, True),
            10: ("dataset-coarse-resolution", "add-examples", False, True),
            walkthrough - 1: ("dataset-coarse-resolution", "add-examples", False, True),
            walkthrough: ("dataset-coarse-resolution", "add-examples", False, False),
            29: ("dataset-coarse-resolution", "add-examples", False, False),
        }
        for count, (condition, remedy, blocks, asks) in sorted(expected.items()):
            with self.subTest(comparable=count):
                cap = MODULE.power_ceiling(count)
                self.assertIsNotNone(cap, "a size under thirty raises a ceiling")
                self.assertEqual(
                    (cap.condition, cap.action_kind, cap.blocks, cap.asks),
                    (condition, remedy, blocks, asks),
                )
        # And the top of the ladder, where nothing is raised at all.
        for count in (MODULE.COARSE_RESOLUTION_EXAMPLES, 200):
            with self.subTest(comparable=count):
                self.assertIsNone(MODULE.power_ceiling(count))

    def test_every_dataset_remedy_gives_one_answer_about_waiting(self) -> None:
        """The defect stated as the property that refuses it.

        Read off the module rather than listed here: every condition that
        shares a remedy is built and its `blocks` compared, so a fifteenth cap
        added to an existing slug with the opposite verdict fails on arrival.

        `vary-knobs` is excluded and named rather than quietly skipped. Three of
        its caps report an agent that was looked at and holds nothing to search
        and a fourth reports that nothing about the agent reached the score at
        all; that pair is the agent pillar's question and is recorded beside
        `NO_SEARCH_SPACE_ESTABLISHED_CAP`, not settled here.
        """
        source = Path(MODULE.__file__).read_text(encoding="utf-8")
        declared = cap_construction_field(
            source, "blocks", MODULE.Cap.__dataclass_fields__["blocks"].default
        )
        # Every condition observed, the way the sibling class already insists.
        # Without it this reader is one-directional: a condition the AST scan
        # missed is a remedy group judged on the half of its members the reader
        # happened to find, and the group would agree with itself by omission.
        self.assertEqual(
            set(declared),
            set(MODULE.ACTION_FOR_CONDITION),
            "the conditions built and the conditions mapped are not the same set",
        )
        by_remedy: dict[str, dict[str, set]] = {}
        for condition, values in declared.items():
            if condition == "agent-no-varying-knobs":
                continue
            remedy = MODULE.ACTION_FOR_CONDITION[condition]
            by_remedy.setdefault(remedy, {})[condition] = values
        shared = {
            remedy: group for remedy, group in by_remedy.items() if len(group) > 1
        }
        self.assertIn("add-examples", shared, "the split remedy lost a sibling")
        self.assertIn("resplit-dataset", shared, "the blocking pair lost a sibling")
        for remedy, group in sorted(shared.items()):
            with self.subTest(remedy=remedy):
                answers = {value for values in group.values() for value in values}
                self.assertEqual(
                    len(answers),
                    1,
                    f"the conditions routing to {remedy!r} disagree about "
                    f"whether the run waits: "
                    f"{ {c: sorted(v) for c, v in sorted(group.items())} } - one "
                    "instruction that means stop on one card and carry on on "
                    "the next is what #197 was filed about",
                )
        self.assertEqual(
            {c for c, r in MODULE.ACTION_FOR_CONDITION.items() if r == "get-data"},
            {"dataset-absent"},
            "`get-data` carries a second condition again; it is the one remedy "
            "that means the customer has to go and find data this run cannot "
            "write, so anything a top-up would fix does not belong on it",
        )

    def test_the_offer_stops_at_the_size_this_guide_builds(self) -> None:
        """The owner's messaging constraint, checked on the printed sentence.

        The bound has to be a number on the card. An offer to add examples that
        names no total reads as an offer to generate without end, which is the
        one thing a customer must not be left imagining about their bill.
        """
        offered = MODULE.power_ceiling(9).reason
        self.assertIn(f"{MODULE.WALKTHROUGH_DATASET_ROWS} rows in total", offered)
        self.assertIn(f"{MODULE.WALKTHROUGH_TUNING_ROWS} to tune on", offered)
        self.assertIn(f"{MODULE.WALKTHROUGH_HOLDOUT_ROWS} held back", offered)
        self.assertIn("stops there", offered)
        self.assertIn("asks first", offered)
        # Nothing in it scales with the customer's project, and no phrasing
        # leaves the total open. Both are checked on the words, because both
        # are how a bounded offer is misread as an unbounded one.
        for unbounded in ("as many", "more rows", "up to date", "each row"):
            with self.subTest(phrase=unbounded):
                self.assertNotIn(unbounded, offered)
        # THE FALSE-RED DIRECTION. At and above that size there is nothing to
        # offer, so the sentence is absent rather than reworded - a project
        # holding what this run builds must not be offered it.
        settled = MODULE.power_ceiling(MODULE.WALKTHROUGH_DATASET_ROWS).reason
        self.assertNotIn("generated examples", settled)
        self.assertNotIn("rows in total", settled)
        # Not `assertNotIn("28")`: at exactly this size the sentence opens with
        # the count, so the digits are in it for an unrelated reason and that
        # assertion would have been a spelling check on the wrong string.
        self.assertTrue(settled.startswith(f"{MODULE.WALKTHROUGH_DATASET_ROWS} "))

    def test_the_ceiling_reads_the_split_and_the_offer_reads_the_dataset(
        self,
    ) -> None:
        """Two counts, and the fixture that proved they cannot be one.

        The guide's own walkthrough dataset is 28 rows cut 18 to tune on and 10
        held back. Asked of the tuning side alone, the offer fired on it: a
        project holding exactly what this run builds was offered rows to reach
        a total it already had. The ceiling still reads the tuning side,
        because resolution is a property of the comparison and not of the file.
        """
        cap = MODULE.power_ceiling(
            MODULE.WALKTHROUGH_TUNING_ROWS, MODULE.WALKTHROUGH_DATASET_ROWS
        )
        self.assertEqual(cap.condition, "dataset-coarse-resolution")
        self.assertFalse(cap.asks, "the walkthrough's own dataset was offered a top-up")
        # And the reverse: a small dataset whose split leaves fewer rows on the
        # tuning side is still one small dataset, so the offer fires once on
        # what the file holds.
        asked = MODULE.power_ceiling(9, 12)
        self.assertTrue(asked.asks)
        self.assertIn("only 9 comparable example(s)", asked.reason)

    def test_partial_labels_are_repaired_before_a_bounded_top_up(self) -> None:
        cap = MODULE.power_ceiling(1, 1, available_rows=27)
        self.assertFalse(cap.asks)
        self.assertIn("Review or label the 26 existing row(s)", cap.reason)
        self.assertNotIn("18 to tune on", cap.reason)

    def test_a_project_owned_split_is_preserved_in_the_offer(self) -> None:
        cap = MODULE.power_ceiling(
            9, 14, available_rows=14, preserve_existing_split=True
        )
        self.assertTrue(cap.asks)
        self.assertIn("preserving your project's existing", cap.reason)
        self.assertNotIn("18 to tune on", cap.reason)
        self.assertNotIn("10 held back", cap.reason)

    def test_a_split_with_nothing_scoreable_is_a_split_repair(self) -> None:
        """Reached through `score_dataset`, so the branch is proved reachable.

        The state is a real one and no other cap stops it: every label on one
        side of a declared split, so the aggregate count is non-zero and
        `dataset-no-expected-outputs` never fires. What #197 changes is that
        the card names the split rather than asking a customer holding 120
        labelled rows to go and collect examples.
        """
        _, caps = MODULE.score_dataset(
            _clean_dataset(labelled_rows=120, tuning_labelled_rows=0)
        )
        raised = {cap.condition: cap for cap in caps}
        self.assertIn("dataset-tuning-split-empty", raised)
        cap = raised["dataset-tuning-split-empty"]
        self.assertTrue(cap.blocks)
        self.assertFalse(cap.asks)
        self.assertEqual(cap.action_kind, "resplit-dataset")
        self.assertEqual(cap.ceiling, MODULE.TUNING_SPLIT_EMPTY_CEILING)
        self.assertEqual(
            MODULE.ROUTE_CATEGORY["dataset-tuning-split-empty"],
            MODULE.CREATION_OR_REPAIR,
        )
        # It is ranked below the sizes it implies and above the conditions that
        # imply it, which is the ordering rule with a derivation behind it.
        self.assertLess(cap.ceiling, MODULE.WIRING_CHECK_CEILING)
        self.assertLess(cap.ceiling, MODULE.COARSE_RESOLUTION_CEILING)
        self.assertGreater(cap.ceiling, MODULE.DATASET_NO_EXPECTED_OUTPUTS_CEILING)
        # THE FALSE-RED DIRECTION. Move the labels back onto the tuning side
        # and nothing here fires: this cap is about an empty side, not about a
        # declared split.
        _, healthy = MODULE.score_dataset(_clean_dataset())
        self.assertNotIn(
            "dataset-tuning-split-empty", [cap.condition for cap in healthy]
        )

    def test_consent_removes_the_stop_and_never_the_score(self) -> None:
        """The rule the ask is allowed to change, and the one it is not.

        Structural, the way #213 asserted the same rule for provenance: the
        scorer takes no consent input at all, so no answer at the ask can reach
        the arithmetic. A topped-up dataset scores what its rows score.
        """
        source = Path(MODULE.__file__).read_text(encoding="utf-8")
        for word in ("consent", "agreed", "approval", "permission"):
            with self.subTest(word=word):
                self.assertNotIn(f'"--{word}', source)
        # The rows a top-up writes are generated rows and are priced as such,
        # so agreeing cannot pay: the credit for a synthesised row is below the
        # credit for a collected one, and the generated ceiling still binds.
        self.assertLess(MODULE.SYNTHESISED_ROW_POINTS, MODULE.COLLECTED_ROW_POINTS)
        band, _limited = MODULE.band_for(MODULE.FULLY_SYNTHETIC_CEILING, 1.0, 1.0)
        self.assertLess(
            MODULE.BAND_ORDER.index(band), MODULE.BAND_ORDER.index("STRONG")
        )


def _build_document(**overrides):
    """A read of a well-built agent, minus whatever a test changes.

    Written once because these tests are about what ONE answer does to the
    pillar, and a document assembled per test drifts into carrying two.
    """
    document = {
        "prompt": {
            "present": True,
            "few_shot": 3,
            "evidence": "agent.py:9-31 SYSTEM carries three worked examples",
        },
        "output-contract": {
            "present": True,
            "evidence": "agent.py:40 json.loads(reply) parses the answer",
        },
        "control-flow": {
            "loop": True,
            "bounded": True,
            "evidence": "agent.py:44 for _ in range(MAX_STEPS)",
        },
        "tools": {
            "used": True,
            "declared": ["search", "fetch"],
            "unreachable": [],
            "evidence": "agent.py:31 TOOLS lists both; both resolve here",
        },
    }
    document.update(overrides)
    return document


def _read(build=None, knobs=None):
    """The agent-knobs document as the CLI's own adapter reads it."""
    document = {
        "knobs": (
            {
                "model": {
                    "values": ["a", "b", "c"],
                    "evidence": "agent.py:8 showing a, b, c",
                },
                "temperature": {"low": 0.0, "high": 1.0, "evidence": "agent.py:9"},
            }
            if knobs is None
            else knobs
        )
    }
    if build is not None:
        document["build"] = build
    return MODULE.agent_facts_from_discovery(document)


def _documented_agent_read():
    """The `--agent-knobs` example the guide hands the reader, parsed.

    One reader for both tests below, because "does this block parse" and "does
    this block score" have to be asking about the same bytes.
    """
    guide = (
        ROOT / "skills" / "traigent-first-run" / "references" / "component-creation.md"
    ).read_text()
    section = guide.split("## Reading the agent for the opening score", 1)[1]
    return json.loads(section.split("```json", 1)[1].split("```", 1)[0])


# The parameters that example is expected to declare an extent for.
#
# Pinned here rather than read out of the example, because a denominator taken
# from the artefact under test shrinks with it. The scoring check below was
# written twice against a derived set and found vacuous twice: strip every
# `values` and `low`/`high` from the JSON and the derived set empties, the
# comparison becomes set() against set(), and a document that credits nothing
# passes as one that credits everything. A guard whose strength is a function
# of the thing it guards is not a guard.
#
# The cost of pinning is that the example may not gain or lose a knob quietly,
# which is the point: it fails here by name, and whoever changed the example
# says so in this list deliberately.
DOCUMENTED_AGENT_KNOBS = frozenset({"model", "temperature", "style"})


class TheAgentPillarReadsTheAgentTests(unittest.TestCase):
    """#184: `AGENT` over one number that answered a question about our search.

    The pillar measured how many settings-combinations there were to try and
    printed the customer's word over it. Two people with the same declared
    space and very different agents scored the same, which is the complaint,
    and the owner's answer was to keep the name by making it true rather than
    to rename the pillar `SEARCH SPACE`.

    What these pin is the honest half of that: the four checks are facts a read
    of source can establish with a citation, the two that cannot be established
    are said rather than scored, and a read that could not settle a check
    reports that rather than scoring the agent zero for it.
    """

    def test_the_documented_agent_read_is_one_complete_consumable_object(self) -> None:
        facts = MODULE.agent_facts_from_discovery(_documented_agent_read())
        self.assertTrue(facts.discovery_supplied)
        self.assertEqual(
            {signal.name for signal in facts.build or ()},
            {name for name, _weight in MODULE.AGENT_BUILD_CHECKS},
        )

    def test_the_documented_agent_read_credits_every_knob_it_declares(self) -> None:
        """Parsing the example is not the same as scoring it.

        Its sibling above passed while `model` and `style` earned nothing:
        both evidence lines PARAPHRASED their options ("MODELS lists the three
        ids"), and `_value_is_evidenced` looks for the literal value. The one
        document handed to a reader as the shape to copy was a shape that
        scores zero on two of its three knobs, and a structural check cannot
        see that. So run it through the scorer.

        Neither assertion is a number: a knob's credit moves whenever the
        weights do, but no knob in an example we publish should ever earn
        nothing. `DiscoveredKnob.credited` is the property, not a phrase out of
        the refusal it prints - a fragment of that sentence is a check the
        scorer can pass by being reworded, and it only ever saw ONE of the ways
        a knob earns nothing. The refusal belongs in the failure message
        instead, where a rewording changes what the reader is told and nothing
        about what passes.

        Both halves compare against `DOCUMENTED_AGENT_KNOBS` rather than
        against the example, for the reason recorded there. The first says the
        example still declares an extent for exactly those parameters, so the
        second cannot be satisfied by an example that declares fewer; the
        second is the credit itself, stated positively - the set of knobs the
        scorer credits IS that set - so an empty result fails instead of
        passing. The excluded knobs are dropped from the first, because `seed`
        or `max_tokens` may legitimately appear here to illustrate the refusal
        they get, and they are never credited in the second either.

        Knobs that record a doubt - `evidence` and no `values` or `low`/`high`
        - are outside both sets on purpose: the guide teaches that shape and a
        knob written that way earns nothing by design.
        """
        document = _documented_agent_read()
        declared = {
            name
            for name, spec in document["knobs"].items()
            if {"values", "low", "high"} & set(spec)
        } - set(MODULE.EXCLUDED_KNOBS)
        self.assertEqual(
            declared,
            set(DOCUMENTED_AGENT_KNOBS),
            "the --agent-knobs example in references/component-creation.md no "
            "longer declares an extent for the parameters this test is pinned "
            "to. That list is what stops the credit check below from passing "
            "on an example with nothing left to credit, so it is not derived "
            "from the example: update DOCUMENTED_AGENT_KNOBS in the same "
            "change that adds or drops a knob there.",
        )
        facts = MODULE.agent_facts_from_discovery(document)
        credited = {knob.name for knob in facts.discovered or () if knob.credited}
        # Why THAT knob earned nothing, in the scorer's own words, rather than
        # one repair named for every knob at once. "Cite the values or drop the
        # extent" fixes a categorical knob whose options are not in the line
        # cited for them, and fixes nothing about a range inside the noise
        # floor: a message written for the first direction sends the reader of
        # the second to the wrong place. `uncredited_reason` is what the scorer
        # already refused it with, so this reports it instead of guessing.
        read = {knob.name: knob for knob in facts.discovered or ()}
        refused = "; ".join(
            (
                f"{name}: {read[name].uncredited_reason}"
                if name in read
                else f"{name}: the read did not return this parameter at all"
            )
            for name in sorted(set(DOCUMENTED_AGENT_KNOBS) - credited)
        )
        self.assertEqual(
            credited,
            set(DOCUMENTED_AGENT_KNOBS),
            "the --agent-knobs example in references/component-creation.md "
            "declares an extent for these knobs and the scorer does not credit "
            "exactly them. It is the one document a reader is handed as the "
            "shape to copy, so a knob it cannot get credit for teaches a "
            "document that scores zero. What the scorer refused, and why: "
            + (
                refused
                or "nothing - every pinned knob is credited, so the scorer "
                "credits some knob this test is not pinned to"
            ),
        )

    def test_the_opening_cap_measurement_has_an_executable_fixture(self) -> None:
        """Keep the source comment's score and producer re-runnable."""
        score = MODULE.score_run(
            _clean_dataset(
                rows=200,
                labelled_rows=200,
                tuning_rows=180,
                holdout_rows=20,
                tuning_labelled_rows=180,
                holdout_labelled_rows=20,
                difficulty_tagged_rows=200,
                collected_rows=200,
                answerable_rows=200,
            ),
            MODULE.EvaluationFacts(
                present=True,
                method="normalized-exact",
                task_kind="closed-label",
                calibration_present=True,
                calibration_supplied=True,
                checks=({f"check-{index}": True for index in range(7)},),
                probe_scores=((1.0, 0.0),),
            ),
            MODULE.AgentFacts(),
            dict(MODULE.DEFAULT_WEIGHTS),
        )
        self.assertEqual(
            [(pillar.name, pillar.score) for pillar in score.pillars],
            [("agent", 0), ("dataset", 98), ("evaluation", 100)],
        )
        self.assertEqual(score.weighted_average, 74)
        self.assertEqual(score.overall, 45)
        self.assertEqual(score.band, "PARTIAL")
        self.assertEqual(
            [cap.condition for cap in score.caps], ["agent-no-varying-knobs"]
        )

    def _pillar(self, facts):
        pillar, _caps, _knobs = MODULE.score_agent(facts)
        return pillar, {sub.name: sub for sub in pillar.subscores}

    def test_the_same_search_space_no_longer_scores_two_agents_alike(self) -> None:
        """The complaint, executed, on one project with one config space.

        Identical knobs; the only difference is what the read found about how
        each agent is put together. Before #184 these were one number.
        """
        pillars = [
            MODULE.Pillar("dataset", 98, 1.0, ()),
            MODULE.Pillar("evaluation", 100, 1.0, ()),
        ]

        def overall(build):
            pillar, caps, knobs = MODULE.score_agent(_read(build))
            return MODULE.aggregate(
                [*pillars, pillar], caps, knobs, dict(MODULE.DEFAULT_WEIGHTS)
            )

        strong = overall(_build_document())
        thin = overall(
            _build_document(
                prompt={
                    "present": True,
                    "few_shot": 0,
                    "evidence": "agent.py:9 one instruction line",
                },
                **{
                    "output-contract": {
                        "present": False,
                        "evidence": "agent.py:40 returns the raw reply",
                    },
                    "control-flow": {
                        "loop": True,
                        "bounded": False,
                        "evidence": "agent.py:44 while True with no break",
                    },
                },
            )
        )
        self.assertGreater(
            strong.overall,
            thin.overall,
            "the same declared search space still grades two agents alike",
        )
        # Both are honest answers, so both are fully measured - what separates
        # them is what the read found, not how much of it happened.
        self.assertEqual(strong.pillars[0].confidence, 1.0)
        self.assertEqual(thin.pillars[0].confidence, 1.0)

    def test_a_check_the_read_could_not_settle_is_not_a_zero(self) -> None:
        """README.md's promise, on the input most likely to break it.

        "A check this tool could not compute is marked unmeasured and excluded
        rather than scored zero." A prompt assembled at runtime is the ordinary
        case, and scoring it zero would say the agent has no prompt.
        """
        undetermined = _build_document(
            prompt={
                "determined": False,
                "reason": "the prompt is fetched at runtime",
                "evidence": "agent.py:12 load_prompt(url) returns it",
            }
        )
        pillar, checks = self._pillar(_read(undetermined))
        self.assertFalse(checks["prompt"].measured)
        self.assertFalse(checks["prompt"].withheld)
        self.assertIn("not established by this read", checks["prompt"].evidence)
        self.assertIn("fetched at runtime", checks["prompt"].evidence)
        # Excluded, so it lowers confidence and not the score, and it scores
        # strictly better than an agent that genuinely has no prompt.
        self.assertLess(pillar.confidence, 1.0)
        answered, _ = self._pillar(
            _read(
                _build_document(
                    prompt={
                        "present": False,
                        "evidence": "agent.py: no prompt reaches the call",
                    }
                )
            )
        )
        self.assertGreater(pillar.score, answered.score)

    def test_determined_is_a_strict_boolean(self) -> None:
        for malformed in ("false", None, 0):
            with self.subTest(malformed=malformed):
                with self.assertRaisesRegex(
                    MODULE.AgentDiscoveryInputError, "must be true or false"
                ):
                    _read(
                        _build_document(
                            prompt={
                                "determined": malformed,
                                "present": True,
                                "evidence": "agent.py:12",
                            }
                        )
                    )

    def test_a_read_that_never_happened_is_withheld_and_never_free(self) -> None:
        """The rule this repository has broken in six places.

        Silence must not outscore an honest answer. The four checks are the
        run's to supply wherever an agent was found, so their absence keeps its
        weight and earns nothing - and the worst honest read still beats it.
        """
        silent, checks = self._pillar(_read())
        for name, _weight in MODULE.AGENT_BUILD_CHECKS:
            with self.subTest(check=name):
                self.assertFalse(checks[name].measured)
                self.assertTrue(checks[name].withheld)
                self.assertEqual(checks[name].value, 0.0)
        worst, _ = self._pillar(
            _read(
                _build_document(
                    prompt={"present": False, "evidence": "agent.py: none"},
                    **{
                        "output-contract": {
                            "present": False,
                            "evidence": "agent.py:40 raw reply",
                        },
                        "control-flow": {
                            "loop": True,
                            "bounded": False,
                            "evidence": "agent.py:44 while True",
                        },
                        "tools": {
                            "used": True,
                            "declared": ["search"],
                            "unreachable": ["search"],
                            "evidence": "agent.py:31 declared, never defined",
                        },
                    },
                )
            )
        )
        # Never OUTSCORES, which is the rule, and here it ties: a withheld
        # check keeps its weight and earns nothing, and so does an honest zero,
        # so the arithmetic is deliberately the same. What separates them is
        # the other half of the pair - the honest read is MEASURED, so it says
        # what it found and the silence does not, and confidence is where that
        # shows. Asserting a strict points gap would be asking the score to
        # punish silence twice.
        self.assertLessEqual(
            silent.score,
            worst.score,
            "saying nothing about the agent outscores the worst honest read",
        )
        self.assertGreater(
            worst.confidence,
            silent.confidence,
            "an honest read of the agent is no better evidenced than silence",
        )
        # And the band gate survives it: a run that supplies only the knob half
        # keeps enough of the pillar measured that the card is not demoted on a
        # fact about our own input.
        self.assertGreaterEqual(silent.confidence, MODULE.MIN_CONFIDENCE_FOR_TOP_BANDS)

    def test_an_agent_with_no_tools_is_neither_charged_nor_paid(self) -> None:
        """The N/A case, which is not a zero and is not full marks either."""
        none = _build_document(
            tools={"used": False, "evidence": "agent.py: no tool list reaches the call"}
        )
        pillar, checks = self._pillar(_read(none))
        self.assertFalse(checks["tools"].measured)
        self.assertFalse(checks["tools"].withheld)
        self.assertFalse(checks["tools"].applicable)
        self.assertEqual(checks["tools"].value, 0.0)
        # Excluded, so the pillar renormalizes over the checks that apply. That
        # is not the same number as an agent whose tools all resolve - the
        # denominator moved - and it is close to it rather than below it, which
        # is the property that matters: having no tools is not a deduction.
        every_tool, _ = self._pillar(_read(_build_document()))
        self.assertAlmostEqual(pillar.score, every_tool.score, delta=2)
        self.assertEqual(pillar.confidence, 1.0)
        self.assertEqual(pillar.confidence, every_tool.confidence)
        # And a declared tool nothing implements is charged, which is the one
        # thing "wired correctly" can be checked for by reading source.
        broken, broken_checks = self._pillar(
            _read(
                _build_document(
                    tools={
                        "used": True,
                        "declared": ["search", "fetch"],
                        "unreachable": ["fetch"],
                        "evidence": "agent.py:31 fetch is declared and undefined",
                    }
                )
            )
        )
        self.assertLess(broken.score, pillar.score)
        self.assertIn("not found behind the name", broken_checks["tools"].evidence)

    def test_every_check_names_the_line_it_was_read_from(self) -> None:
        """#210's discipline, on the input that can raise a score.

        Evidence is required on every answer including the ones that say no,
        because "this agent has no prompt" is a finding about somebody's code
        and has to be pointed at.
        """
        for check in ("prompt", "output-contract", "control-flow", "tools"):
            with self.subTest(check=check, missing="evidence"):
                spec = dict(_build_document()[check])
                spec.pop("evidence")
                with self.assertRaises(MODULE.AgentDiscoveryInputError) as caught:
                    _read(_build_document(**{check: spec}))
                self.assertIn("carries no evidence", str(caught.exception))
        # An undetermined check has to say what stopped the read, for the same
        # reason: it leaves the pillar, and a silent exit is unauditable.
        with self.assertRaises(MODULE.AgentDiscoveryInputError) as caught:
            _read(
                _build_document(prompt={"determined": False, "evidence": "agent.py:12"})
            )
        self.assertIn("gives no reason", str(caught.exception))

    def test_a_document_that_answers_three_checks_is_refused(self) -> None:
        """A missing key and a `no` are different statements about the code."""
        partial = _build_document()
        partial.pop("tools")
        with self.assertRaises(MODULE.AgentDiscoveryInputError) as caught:
            _read(partial)
        self.assertIn("answers no tools check", str(caught.exception))
        self.assertIn("'determined': false", str(caught.exception))

    def test_what_the_pillar_does_not_cover_is_said_and_not_scored(self) -> None:
        """Two of the owner's six, reported rather than guessed at.

        Whether the dataset and the evaluation method are wired into the agent
        is an integration this run builds later and verifies against the
        installed SDK, so the opening read has nothing to establish. It is a
        sentence on the card and not a check, because a check that can never be
        measured would hold this pillar's confidence under the band gate on
        every card forever.
        """
        pillar, _checks = self._pillar(_read(_build_document()))
        self.assertEqual(pillar.confidence, 1.0)
        self.assertNotIn(
            "wired",
            {name for name, _weight in MODULE.AGENT_BUILD_CHECKS},
        )
        score = MODULE.aggregate(
            [MODULE.Pillar("dataset", 98, 1.0, ()), pillar],
            [],
            (),
            dict(MODULE.DEFAULT_WEIGHTS),
        )
        card = MODULE.render_card(score, palette=MODULE.Palette(), unicode_ok=False)
        self.assertIn(MODULE.AGENT_NOT_COVERED, card)
        self.assertIn("not covered by this pillar", card)
        # Under the agent pillar and nowhere else - it is a statement about
        # what this pillar reads, not a disclaimer about the card.
        agent_block = card.split("AGENT", 1)[1].split("DATASET", 1)[0]
        self.assertIn("not covered by this pillar", agent_block)
        self.assertEqual(card.count("not covered by this pillar"), 1)

    def test_the_build_read_survives_a_config_space_document(self) -> None:
        """A document decides the search space and says nothing about the rest.

        The `elif` this replaces existed to stop a source read talking over a
        document that attests nothing is wired - a claim about the SEARCH
        SPACE. No config space claims anything about whether the agent has a
        prompt or a bounded loop, so dropping the build half at the close would
        report four checks falling to withheld while nothing about the agent
        changed.
        """
        facts = MODULE.agent_facts_from_config_space(
            {"knobs": {"model": ["a", "b"]}, "wired": ["model"]}
        )
        with_build = replace(facts, build=_read(_build_document()).build)
        document_only, document_checks = self._pillar(facts)
        both, both_checks = self._pillar(with_build)
        self.assertTrue(document_checks["prompt"].withheld)
        self.assertTrue(both_checks["prompt"].measured)
        self.assertEqual(
            document_checks["search-space"].value,
            both_checks["search-space"].value,
            "the read moved the search space, which is the thing it may not do",
        )
        self.assertGreater(both.score, document_only.score)


class RecordingAnUnsettledKnobHasOneShapeAndItWorksTests(unittest.TestCase):
    """#241: the guidance said record it, and the first scoring call refused.

    Two sentences send a reader at the `undetermined` shape - "a parameter you
    are unsure of is worth recording rather than dropping" in the reference, and
    SKILL.md's "answer a check you cannot settle as undetermined with the
    reason, never as a no". That shape is a `build` check's, and written inside
    `knobs` it exits 2 before the opening score exists. A blinded walkthrough
    recovered by trial and error, and dropped the parameter.

    The schema is not widened, and these pin why that is a resolution rather
    than a shrug: the knob half already HAS the third state, spelled as a
    parameter recorded with its evidence and no established extent. So what is
    asserted here is that the spelling works, that it is now visible, and that
    the error naming the accepted fields also names the remedy.
    """

    def _uncounted(self, **spec):
        knobs = {
            "model": {
                "values": ["a", "b", "c"],
                "evidence": "agent.py:8 showing a, b, c",
            },
            "temperature": {"low": 0.0, "high": 1.0, "evidence": "agent.py:9"},
            "top_p": spec,
        }
        return MODULE.score_agent(_read(_build_document(), knobs=knobs))

    def test_a_knob_recorded_with_evidence_alone_costs_nothing(self) -> None:
        """The half of the promise that already held, pinned so it keeps holding.

        Recording an unsettled parameter may not be punished, or the sentence
        telling a reader to record it is asking them to lower their own score.
        """
        settled, _, _ = MODULE.score_agent(_read(_build_document()))
        recorded, caps, _ = self._uncounted(
            evidence="agent.py:14 top_p=cfg['top_p'] reaches the provider call"
        )
        self.assertEqual(recorded.score, settled.score)
        self.assertEqual([cap.condition for cap in caps], [])

    def test_a_knob_recorded_with_evidence_alone_is_reported(self) -> None:
        """The half that did not hold, and the reason the reference could lie.

        The refused list was printed only on the branch where NOTHING is
        credited. Credit one knob and a recorded `top_p` appeared on no card and
        in no payload, so a reader following the instruction could not tell
        their record from a typo.
        """
        pillar, _, _ = self._uncounted(
            evidence="agent.py:14 top_p=cfg['top_p'] reaches the provider call"
        )
        space = next(sub for sub in pillar.subscores if sub.name == "search-space")
        self.assertIn("top_p", space.evidence)
        self.assertIn("Recorded and not counted", space.evidence)
        # The reason travels with the name. "top_p was ignored" is not a line a
        # user can correct; the reason it counts for nothing is.
        self.assertIn("neither a list of options nor a low/high range", space.evidence)

    def test_the_credited_reading_is_unchanged_by_the_recorded_one(self) -> None:
        """A recorded parameter may not enter the space it establishes nothing about."""
        settled, _, _ = MODULE.score_agent(_read(_build_document()))
        recorded, _, _ = self._uncounted(evidence="agent.py:14 top_p from config")
        for pillar in (settled, recorded):
            space = next(s for s in pillar.subscores if s.name == "search-space")
            self.assertIn("reaching at least 6 distinct configurations", space.evidence)

    def test_the_build_shape_inside_knobs_is_refused_with_the_remedy(self) -> None:
        """Naming the accepted fields is half a message.

        The other half is what to write instead, and it is owed here rather than
        only in the reference: the reader is mid-run, at a non-zero exit, and
        the one thing they must not do is drop the parameter.
        """
        with self.assertRaises(MODULE.AgentDiscoveryInputError) as caught:
            self._uncounted(
                determined=False,
                reason="assembled at runtime from a file this read cannot reach",
                evidence="agent.py:14 top_p=cfg['top_p']",
            )
        message = str(caught.exception)
        self.assertIn("unknown field(s) determined, reason", message)
        self.assertIn("answer a build check", message)
        self.assertIn("no 'values' or 'low'/'high'", message)

    def test_an_ordinary_typo_still_gets_the_short_message(self) -> None:
        """The remedy is for the confusion it names, not for every misspelling.

        `valeus` is a typo; appending the `determined` paragraph to it would
        explain a shape the author never reached for.
        """
        with self.assertRaises(MODULE.AgentDiscoveryInputError) as caught:
            self._uncounted(valeus=["a", "b"], evidence="agent.py:14")
        message = str(caught.exception)
        self.assertIn("unknown field(s) valeus", message)
        self.assertNotIn("answer a build check", message)

    def test_the_build_half_still_accepts_the_shape_it_documents(self) -> None:
        """The `undetermined` answer is untouched where it is real."""
        facts = _read(
            _build_document(
                prompt={
                    "determined": False,
                    "reason": "assembled at runtime from a store this read cannot reach",
                    "evidence": "agent.py:12 SYSTEM = load_prompt(name)",
                }
            )
        )
        prompt = next(signal for signal in facts.build or () if signal.name == "prompt")
        self.assertFalse(prompt.measured)
        self.assertIn("not established by this read", prompt.evidence)

    def test_the_reference_states_the_shape_it_sends_the_reader_at(self) -> None:
        """The disagreement was prose against schema, so the prose is pinned too.

        Not a restatement of the mandate - SKILL.md keeps that. This is the
        reference stating, where the reader is standing, which of the two halves
        the `determined` answer belongs to.
        """
        guide = (
            ROOT
            / "skills"
            / "traigent-first-run"
            / "references"
            / "component-creation.md"
        ).read_text()
        knob_half = guide.split("### The build half", 1)[0]
        self.assertIn("worth recording rather than dropping", knob_half)
        self.assertIn("no `values` or `low`/`high`", knob_half)
        self.assertIn("A knob has no `determined` field", knob_half)


class OneFactIsOneRemediationLineTests(unittest.TestCase):
    """Found by reviewing the fix rather than the feature (#184).

    The card already collapses several checks resting on one fact into one
    line, and says why in its own comment: printing it per check "reads as
    several findings" a customer must each act on. `collect_gaps` did not, so
    widening the agent pillar turned one absent reading into four remediation
    lines carrying the identical sentence - the same defect the card fixed, one
    layer over, re-shipped by the change that made four checks possible.
    """

    def _gaps(self, document):
        pillar, caps, knobs = MODULE.score_agent(
            MODULE.agent_facts_from_discovery(document)
        )
        return MODULE.aggregate(
            [MODULE.Pillar("dataset", 98, 1.0, ()), pillar],
            caps,
            knobs,
            dict(MODULE.DEFAULT_WEIGHTS),
        )

    def test_one_absent_reading_is_one_line_naming_every_check_it_covers(
        self,
    ) -> None:
        score = self._gaps(
            {"knobs": {"model": {"values": ["a", "b"], "evidence": "a:1 showing b"}}}
        )
        absent = [gap for gap in score.gaps if "could not be measured" in gap]
        self.assertEqual(len(absent), 1, f"one fact, {len(absent)} lines: {absent}")
        # Collapsed, not dropped: every check it stands for is still named, so
        # the line says what it covers rather than hiding three of them.
        for check, _weight in MODULE.AGENT_BUILD_CHECKS:
            with self.subTest(check=check):
                self.assertIn(check, absent[0])

    def test_checks_resting_on_different_facts_stay_separate(self) -> None:
        """The false-red direction: collapsing is keyed on the fact, not the
        pillar. Two unmeasured checks with different reasons are two findings,
        and merging them would hide one.
        """
        score = self._gaps(
            {
                "knobs": {"model": {"values": ["a", "b"], "evidence": "a:1 showing b"}},
                "build": {
                    "prompt": {
                        "determined": False,
                        "reason": "the prompt is fetched at runtime",
                        "evidence": "a:2",
                    },
                    "output-contract": {"present": True, "evidence": "a:3"},
                    "control-flow": {"loop": False, "evidence": "a:4"},
                    "tools": {"used": False, "evidence": "a:5"},
                },
            }
        )
        absent = [gap for gap in score.gaps if "could not be measured" in gap]
        self.assertEqual(len(absent), 1, absent)
        self.assertTrue(any("fetched at runtime" in gap for gap in absent))
        self.assertFalse(any("no tools" in gap for gap in score.gaps))

    def test_the_durable_report_says_what_the_pillar_does_not_cover(self) -> None:
        """The card said it and the saved report did not.

        The report is the artifact that outlives the terminal, and it is where
        four agent checks most read as all of them.
        """
        score = self._gaps(
            {"knobs": {"model": {"values": ["a", "b"], "evidence": "a:1 showing b"}}}
        )
        report = MODULE.render_markdown(score)
        self.assertIn(MODULE.AGENT_NOT_COVERED, report)
        agent_block = report.split("## Agent", 1)[1].split("## ", 1)[0]
        self.assertIn("not covered by this pillar", agent_block)


class WhoWroteItBoundsWhatItMayClaimTests(unittest.TestCase):
    """#238: provenance was graded for the rows and for nothing else.

    Every origin condition the scorer carried was `dataset-`-prefixed, and the
    four evaluator conditions that exist - absent, invalid, timeout,
    unresolved - all grade BROKENNESS. So the reachable case was a real agent,
    a real declared-collected corpus and an evaluator written by the run: the
    substitute calibrates, the evaluation pillar scores on that calibration, and
    nothing recorded that the grading signal was one this run invented.

    Measured on trunk `b2b482eb` before this change, over 120 collected rows
    with a read of a real agent: 93/100 EXCELLENT, no caps,
    `recommended_action: proceed`, evaluation 100. The card names a generated
    component in words; the score did not carry that fact, and the score is the
    number a customer takes away.

    The all-missing case was covered by accident and that is worth pinning
    separately: a generated trio also has a generated dataset, so
    `dataset-fully-synthetic` fires. Remove the dataset gap - the ordinary case
    of a customer who has data and no evaluator - and the coverage went with it.
    """

    def _evaluation(self, origin=None) -> "MODULE.EvaluationFacts":
        return MODULE.EvaluationFacts(
            present=True,
            method="normalized-exact",
            task_kind="closed-label",
            calibration_present=True,
            calibration_supplied=True,
            checks=({f"check-{index}": True for index in range(7)},),
            probe_scores=((1.0, 0.0),),
            origin=origin,
        )

    def _score(self, **origins) -> "MODULE.ReadinessScore":
        """The whole reachable case: real agent, collected rows, one origin varied."""
        return MODULE.score_run(
            _brought(
                120,
                tuning_rows=84,
                holdout_rows=36,
                tuning_labelled_rows=84,
                holdout_labelled_rows=36,
            ),
            self._evaluation(origins.get("evaluation")),
            replace(_read(_build_document()), origin=origins.get("agent")),
            dict(MODULE.DEFAULT_WEIGHTS),
        )

    def test_the_reachable_case_no_longer_scores_as_if_the_ruler_were_real(
        self,
    ) -> None:
        undeclared = self._score()
        generated = self._score(evaluation="generated")
        # The measurement the module's own comment quotes, kept re-runnable:
        # this is the card a project with real material and a run-written
        # evaluator got before #238, and it is what a run that still declares
        # nothing gets today.
        self.assertEqual((undeclared.overall, undeclared.band), (93, "EXCELLENT"))
        self.assertEqual(undeclared.recommended_action, "proceed")
        self.assertEqual([cap.condition for cap in undeclared.caps], [])
        self.assertEqual(
            [cap.condition for cap in generated.caps], ["evaluator-generated"]
        )
        self.assertLess(generated.overall, undeclared.overall)

    def test_a_run_written_ruler_may_be_workable_and_never_strong(self) -> None:
        """The owner's rule, asked of the module rather than pinned as 74.

        Asserting the literal would pass just as happily if the bands were
        renumbered and 74 landed back inside STRONG, which is the defect the
        answer-key ladder was already corrected for.
        """
        strong_floor = next(
            edge for edge, band in MODULE.BAND_THRESHOLDS if band == "WORKABLE"
        )
        self.assertEqual(MODULE.EVALUATOR_GENERATED_CEILING, strong_floor - 1)
        self.assertEqual(self._score(evaluation="generated").band, "WORKABLE")

    def test_a_generated_agent_bounds_the_claim_further_than_a_generated_ruler(
        self,
    ) -> None:
        """Whose subject, against whose reading - and the subject costs more.

        A generated evaluator still measures the customer's own agent on the
        customer's own rows, and only the reading is this run's. A generated
        agent makes the thing under comparison this run's too, so the winning
        configuration belongs to a program nobody runs.
        """
        self.assertLess(
            MODULE.AGENT_GENERATED_CEILING, MODULE.EVALUATOR_GENERATED_CEILING
        )
        self.assertEqual(
            MODULE.AGENT_GENERATED_CEILING,
            MODULE.FULLY_SYNTHETIC_CEILING,
            "a generated agent over real data and a real agent over generated "
            "data are the same claim read from opposite sides",
        )
        self.assertLess(
            self._score(agent="generated").overall,
            self._score(evaluation="generated").overall,
        )

    def test_neither_stops_a_run_this_guide_creates_the_component_for(self) -> None:
        """The walkthrough's own designed success may not be called a repair.

        `tests/behavioral/scenarios/partial-missing-dataset` is the shape: a
        project missing a component, which this run supplies. Blocking there
        would demand the customer produce the one thing they came without.
        """
        score = self._score(evaluation="generated", agent="generated")
        self.assertEqual(score.status, "OK")
        self.assertEqual(
            sorted(cap.condition for cap in score.caps),
            ["agent-generated", "evaluator-generated"],
        )
        self.assertFalse(any(cap.blocks for cap in score.caps))
        # Asks nothing, for the reason `dataset-fully-synthetic` asks nothing:
        # the run has already answered by declaring it.
        self.assertFalse(any(cap.asks for cap in score.caps))
        self.assertEqual(score.recommended_action, "proceed")

    def test_brought_and_undeclared_are_scored_the_same_and_that_is_a_decision(
        self,
    ) -> None:
        """`None` raises nothing, recorded here because it is the arguable half.

        The dataset ladder charges silence - an undeclared corpus is capped
        exactly as a declared-generated one is - and this deliberately does not.
        The difference is what silence can mean: preflight READS every row, so
        an undeclared corpus is a file that was examined and said nothing, while
        an absent flag is equally a caller written before the flag existed. The
        hole it leaves is closed in SKILL.md, which mandates both flags on every
        scoring call, and the reasoning is recorded on `origin_cap`.
        """
        self.assertEqual(
            self._score(evaluation="brought", agent="brought").overall,
            self._score().overall,
        )
        self.assertIsNone(MODULE.origin_cap("evaluation", None))
        self.assertIsNone(MODULE.origin_cap("agent", "brought"))

    def test_an_absent_evaluator_has_no_origin_to_declare(self) -> None:
        """Nothing is connected, so there is nothing whose authorship matters.

        The absent condition already holds the score at 40, below anything this
        ceiling could say, and two conditions about one missing file would read
        as two problems.
        """
        _pillar, caps = MODULE.score_evaluation(
            MODULE.EvaluationFacts(present=False, origin="generated")
        )
        self.assertEqual([cap.condition for cap in caps], ["evaluator-absent"])

    def test_a_generated_evaluator_that_is_also_broken_says_both(self) -> None:
        """Origin and brokenness are separate axes, which is the whole finding.

        A substitute this run wrote can still be invalid, and the reader is owed
        both facts - the lower ceiling decides the number either way.
        """
        _pillar, caps = MODULE.score_evaluation(
            MODULE.EvaluationFacts(
                present=True,
                method="normalized-exact",
                calibration_present=True,
                calibration_supplied=True,
                checks=({"non_constant": False, "bad_fails": False},),
                origin="generated",
            )
        )
        conditions = sorted(cap.condition for cap in caps)
        self.assertIn("evaluator-generated", conditions)
        self.assertIn("evaluator-invalid", conditions)

    def test_the_agent_ceiling_reaches_every_path_that_establishes_a_space(
        self,
    ) -> None:
        """Four documents answer "what is there to search" and none answers this.

        The cap is applied outside those branches for the reason `with_build`
        is: whose agent this is has nothing to do with which document described
        it, and four appends in four branches is four chances for a fifth
        branch to forget.
        """
        for label, facts in (
            ("read of the source", _read(_build_document())),
            (
                "config-space document",
                MODULE.AgentFacts(knobs={"model": ["a", "b"]}, wired=("model",)),
            ),
            ("document listing nothing", MODULE.AgentFacts(config_space_supplied=True)),
            ("nothing at all", MODULE.AgentFacts()),
        ):
            with self.subTest(path=label):
                _pillar, caps, _knobs = MODULE.score_agent(
                    replace(facts, origin="generated")
                )
                self.assertIn("agent-generated", [cap.condition for cap in caps])

    def test_the_flags_reach_the_score_from_the_command_line(self) -> None:
        """The declaration is worth nothing if `run` drops it."""
        for flag, condition in (
            ("--evaluator-origin", "evaluator-generated"),
            ("--agent-origin", "agent-generated"),
        ):
            with self.subTest(flag=flag):
                arguments = MODULE.parse_args(["--preflight", "-", flag, "generated"])
                self.assertEqual(
                    getattr(arguments, flag.lstrip("-").replace("-", "_")),
                    "generated",
                )
                self.assertIn(condition, MODULE.ACTION_FOR_CONDITION)


class TheRefusalMessageIsADocumentThatWorksTests(unittest.TestCase):
    """The agent-knobs refusal prints an example; it has to be a real one.

    Five successive attempts to DESCRIBE this contract in prose were wrong and
    every one of them read correctly: "everything is optional", "any check
    inside build is optional", "any field other than evidence answers the
    question", then the undocumented conditionals, then the undocumented types.
    A blinded run had already paid for that - eight refusals, then it dropped
    the flag and told a customer their agent could not be read.

    So the message stopped describing and started showing, and these tests are
    what make showing safer than describing: the example goes through the real
    parser, so a message that drifts from the code fails here rather than in
    somebody's run.
    """

    def test_the_example_the_refusal_prints_is_accepted_by_the_parser(self) -> None:
        facts = MODULE.agent_facts_from_discovery(MODULE.AGENT_KNOBS_EXAMPLE)
        self.assertEqual(["model"], [knob.name for knob in facts.discovered])
        self.assertTrue(facts.discovery_supplied)
        self.assertEqual(
            sorted(MODULE.BUILD_CHECK_ANSWER),
            sorted(signal.name for signal in facts.build),
        )

    def test_the_block_the_refusal_prints_parses_and_validates_as_printed(
        self,
    ) -> None:
        # Not "the constant is valid" - the PRINTED text is what a reader
        # copies. An earlier version annotated each line with `# also reads:`,
        # which is not JSON, so copying the block gave a parse error: the extra
        # round trip this message exists to remove, reintroduced by it. Parse
        # the rendered block and put it through the real parser.
        printed = MODULE.agent_knobs_shape()
        start = printed.index("{")
        end = printed.rindex("}") + 1
        document = json.loads(printed[start:end])
        self.assertEqual(MODULE.AGENT_KNOBS_EXAMPLE, document)
        facts = MODULE.agent_facts_from_discovery(document)
        self.assertEqual(["model"], [knob.name for knob in facts.discovered])

    def test_the_example_declares_no_value_its_own_evidence_does_not_show(
        self,
    ) -> None:
        # SKILL.md forbids recording an option that was not read - "an omitted
        # parameter costs a few points, an invented one makes the card wrong" -
        # and three blinded runs over-claimed a search space anyway. An earlier
        # example cited one default and declared two options, teaching the
        # invention in the text an assistant is told to copy.
        for name, spec in MODULE.AGENT_KNOBS_EXAMPLE["knobs"].items():
            evidence = str(spec.get("evidence", ""))
            for value in spec.get("values", []):
                with self.subTest(knob=name, value=value):
                    self.assertIn(str(value), evidence)

    def test_every_check_is_refused_without_the_flag_the_example_answers(
        self,
    ) -> None:
        # BUILD_CHECK_ANSWER mirrors the scorer's own `_build_flag` calls, and
        # nothing structural keeps the two in step. This is that mechanism: if a
        # check's required flag changes on one side only, the example stops
        # matching the validator and this fails, naming the check.
        for check, flag in MODULE.BUILD_CHECK_ANSWER.items():
            with self.subTest(check=check):
                document = json.loads(json.dumps(MODULE.AGENT_KNOBS_EXAMPLE))
                del document["build"][check][flag]
                with self.assertRaises(MODULE.AgentDiscoveryInputError) as caught:
                    MODULE.agent_facts_from_discovery(document)
                self.assertIn(flag, str(caught.exception))


class TheRowReviewRefusalPrintsADocumentThatWorksTests(unittest.TestCase):
    """The sibling of the agent-knobs example, and it was found the hard way.

    Once the agent-knobs contract stopped being a staircase, a blinded run
    walked four refusals on THIS document instead - not an object with reviewer
    and rows, then an entry with no id, then a verdict outside the vocabulary,
    then an origin outside it. Fixing one hand-authored document at the opening
    gate had moved the problem to the other one.
    """

    def test_the_block_the_refusal_prints_parses_as_printed(self) -> None:
        printed = MODULE.row_review_shape()
        start = printed.index("{")
        end = printed.rindex("}") + 1
        self.assertEqual(MODULE.ROW_REVIEW_EXAMPLE, json.loads(printed[start:end]))

    def test_every_entry_carries_what_the_legend_says_it_does(self) -> None:
        for index, entry in enumerate(MODULE.ROW_REVIEW_EXAMPLE["rows"]):
            with self.subTest(entry=index):
                self.assertEqual({"id", "verdict", "origin", "note"}, set(entry))
                self.assertIn(entry["verdict"], MODULE.ROW_REVIEW_VERDICTS)
                self.assertIn(entry["origin"], MODULE.ROW_REVIEW_ORIGINS)

    def test_the_vocabularies_the_legend_prints_are_the_ones_enforced(
        self,
    ) -> None:
        # This is a CONTRACT test, not a drift guard, and the difference was
        # worth finding. The legend is rendered from the same constants the
        # scorer enforces, so the two cannot disagree - a first version
        # asserting "each constant appears in the printed text" was a
        # tautology, and a second, behavioural one survived widening the
        # vocabulary too, because adding a member keeps "every member is
        # accepted" true. There is no drift to guard here.
        #
        # What it does prove is worth keeping: every verdict and origin the
        # message prints is genuinely accepted, and one outside them is
        # refused with the vocabulary named.
        for verdict in MODULE.ROW_REVIEW_VERDICTS:
            with self.subTest(verdict=verdict):
                self.assertNotIn(verdict, _row_review_refusal(verdict=verdict))
        self.assertIn("expected one of", _row_review_refusal(verdict="not-a-verdict"))
        for origin in MODULE.ROW_REVIEW_ORIGINS:
            with self.subTest(origin=origin):
                self.assertNotIn(origin, _row_review_refusal(origin=origin))
        self.assertIn("expected one of", _row_review_refusal(origin="not-an-origin"))


def _row_review_refusal(
    *, verdict: str | None = None, origin: str | None = None
) -> str:
    """Return the scorer's complaint about one edited example entry, or "".

    Behavioural, because the legend is derived from the constants and so can
    only ever agree with them.
    """
    document = json.loads(json.dumps(MODULE.ROW_REVIEW_EXAMPLE))
    document["rows"] = document["rows"][:1]
    entry = document["rows"][0]
    if verdict is not None:
        entry["verdict"] = verdict
    if origin is not None:
        entry["origin"] = origin
    # The counts have to describe the same dataset the review claims to, so
    # they follow the origin under test rather than being pinned to one.
    declared = entry["origin"]
    facts = MODULE.DatasetFacts(
        exists=True,
        dataset_supplied=True,
        unreadable_rows=0,
        unreadable_detail="",
        rows=1,
        labelled_rows=1,
        tuning_rows=1,
        holdout_rows=0,
        tuning_labelled_rows=1,
        holdout_labelled_rows=0,
        difficulty_bands=(),
        difficulty_tagged_rows=0,
        duplicate_status="none",
        near_duplicate_status="none",
        answer_dominance_status="none",
        split_overlap=0,
        shared_families=0,
        tuning_forms=1,
        holdout_forms=1,
        integrity_failed=False,
        synthetic=False,
        generated_outputs=0,
        collected_rows=1 if declared == "collected" else 0,
        synthesised_rows=0,
        undeclared_rows=1 if declared == "undeclared" else 0,
        answerable_rows=1,
        generated_answer_rows=0,
        placeholder_rows=0,
        sources=(),
        unrecognised_sources=(),
    )
    try:
        MODULE.row_review_from_document(document, facts)
    except MODULE.RowReviewInputError as error:
        return str(error)
    except TypeError:
        raise
    return ""

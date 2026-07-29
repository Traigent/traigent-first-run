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


class AgentScoringTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

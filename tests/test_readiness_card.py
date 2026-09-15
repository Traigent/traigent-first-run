"""Customer progress stays concise without losing the detailed diagnostic record."""

import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

import test_readiness_scoring as fixtures

MODULE = fixtures.MODULE


def unresolved_source_score():
    """A real source-read refusal, with ordinary unverified build observations."""
    route = fixtures.TheRefusedRouteIsShownAnAcceptedOneTests
    build = fixtures._build_document(
        **{
            "control-flow": {
                "loop": False,
                "evidence": "A straight-line helper returns the reply.",
                "source_lines": [8, 9, 10],
            },
            "tools": {
                "used": False,
                "evidence": "No tools are declared in the selected function.",
                "source_lines": [8, 9, 10],
            },
        }
    )
    for entry in build.values():
        entry.setdefault("source_lines", [8, 9, 10])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "agent.py").write_text(route.REFUSED_AGENT)
        facts = MODULE.agent_facts_from_discovery(
            {
                "source": "agent.py",
                "knobs": {"model": route.REFUSED_KNOB},
                "build": build,
            },
            source_root=root,
            selected_agent=root / "agent.py",
            selected_agent_callable="answer",
        )
    facts = replace(
        facts,
        origin=MODULE.BROUGHT,
        build=MODULE.build_declarations_are_unmeasured(facts.build),
    )
    return MODULE.score_run(
        fixtures._routing_corpus(),
        fixtures._passing_calibration(),
        facts,
        dict(MODULE.DEFAULT_WEIGHTS),
    )


class ReadinessCardAudienceTests(unittest.TestCase):
    def test_answer_key_findings_cannot_render_as_ok_without_changing_points(self):
        facts = fixtures._routing_corpus()
        baseline = fixtures._healthy_score(fixtures._review(reviewed=48))
        baseline_dataset = next(p for p in baseline.pillars if p.name == "dataset")
        for unsound, unsure in ((0, 0), (1, 0), (48, 0), (0, 2), (0, 48)):
            with self.subTest(unsound=unsound, unsure=unsure):
                score = MODULE.score_run(
                    facts,
                    fixtures._passing_calibration(),
                    fixtures._wired_space(),
                    dict(MODULE.DEFAULT_WEIGHTS),
                    fixtures._review(reviewed=48, unsound=unsound, unsure=unsure),
                )
                dataset = next(p for p in score.pillars if p.name == "dataset")
                self.assertEqual(dataset.score, baseline_dataset.score)
                self.assertEqual(dataset.confidence, baseline_dataset.confidence)
                self.assertEqual(
                    [(s.value, s.maximum, s.measured) for s in dataset.subscores],
                    [
                        (s.value, s.maximum, s.measured)
                        for s in baseline_dataset.subscores
                    ],
                )
                self.assertEqual(
                    any(
                        c.condition == "dataset-unsound-expected-outputs"
                        for c in score.caps
                    ),
                    unsound == 48,
                )
                labels = next(s for s in dataset.subscores if s.name == "labels")
                for unicode_ok in (False, True):
                    card = MODULE.render_card(score, unicode_ok=unicode_ok)
                    line = next(
                        line for line in card.splitlines() if "contradict" in line
                    )
                    expected = (
                        ("❗" if unicode_ok else "!!")
                        if unsound or unsure
                        else ("✅" if unicode_ok else "OK")
                    )
                    self.assertEqual(line.split()[0], expected)
                    if unsure:
                        self.assertIn("no contradiction confirmed", line)
                        self.assertIn(f"{unsure} undecided", line)
                        self.assertNotIn("none contradicts its own input", line)
                    self.assertIn(labels.evidence, MODULE.render_markdown(score))
                self.assertEqual(
                    asdict(labels).get("warning", False), bool(unsound or unsure)
                )

    def test_review_coverage_describes_the_declared_split_not_a_selected_run(self):
        facts, _ = (
            fixtures.RowReviewCoverageDescribesOnlyWhatWasReadTests.reviewed_dataset(
                provided=48, graded=48, reviewed=48
            )
        )
        for selected in (0, 28, 48):
            with self.subTest(selected=selected):
                review = MODULE.row_review_from_document(
                    {
                        "reviewer": "assistant",
                        "rows": [
                            {
                                "id": f"review-row-{index}",
                                "origin": "collected",
                                "verdict": "no",
                                "note": "The expected answer contradicts its input.",
                                "in_run": index < selected,
                            }
                            for index in range(48)
                        ],
                    },
                    facts,
                )
                score = MODULE.score_run(
                    facts,
                    fixtures._passing_calibration(),
                    fixtures._wired_space(),
                    dict(MODULE.DEFAULT_WEIGHTS),
                    review,
                )
                line = MODULE.row_review_evidence(review, facts)
                if selected == 48:
                    self.assertIn(
                        "covers every row in the declared tuning/held-out split", line
                    )
                    self.assertNotIn("48 of them from the 48", line)
                else:
                    self.assertIn(
                        f"{selected} marked for this run by the row review", line
                    )
                    self.assertIn("declared tuning/held-out split: 48 rows", line)
                    self.assertNotIn("of them from", line)
                cap = next(
                    c
                    for c in score.caps
                    if c.condition == "dataset-unsound-expected-outputs"
                )
                if selected:
                    self.assertIn(
                        f"{selected} of them marked for this run by the row review",
                        cap.reason,
                    )
                    self.assertIn("declared tuning/held-out split: 48 rows", cap.reason)
                else:
                    self.assertIn(
                        "all marked outside this run by the row review", cap.reason
                    )
                    self.assertNotIn("outside the declared", cap.reason)
                for rendered in (
                    MODULE.render_card(score),
                    MODULE.render_markdown(score),
                ):
                    self.assertNotIn("rows this run is graded on", rendered)
                    self.assertNotIn(
                        "search is about to be graded against them", rendered
                    )

    def test_unverified_opening_explains_its_limit_without_the_source_recipe(self):
        score = unresolved_source_score()
        self.assertEqual(
            (score.overall, score.band, score.status), (45, "PARTIAL", "OK")
        )
        self.assertEqual(score.recommended_action, "proceed")
        card = MODULE.render_card(score, unicode_ok=False)
        self.assertNotIn("Read from agent.py", card)
        self.assertIn("agent source read; 1 of 5 checks measured", card)
        self.assertIn("LIMITED TO 45", card)
        self.assertIn("has not established which settings change the request", card)
        self.assertIn("does not show that the agent has no settings", card)
        self.assertIn("does not raise this score", card)
        self.assertIn("detailed readiness report", card)
        self.assertNotIn("source_lines", card)
        self.assertNotIn("ACCEPTED ROUTE", card)
        self.assertNotIn("references/component-creation.md", card)
        self.assertNotIn("Assistant observation", card)
        for name, _ in MODULE.AGENT_BUILD_CHECKS:
            self.assertIn(MODULE.display_name(name), card)
        self.assertIn("tool wiring was not checked here", card)
        self.assertIn("not independently verified:", card)
        self.assertIn("not covered by this pillar", card)
        self.assertIn("Local pre-run planning estimate", card)
        self.assertEqual(
            card.splitlines()[1], "Action: Continue to the next guided step."
        )

    def test_rendering_preserves_full_serialized_and_markdown_diagnostics(self):
        score = unresolved_source_score()
        before = asdict(score)
        report = MODULE.render_markdown(score)
        self.assertIn("Read from agent.py", report)
        self.assertIn("Assistant observation", report)
        self.assertIn("source_lines", report)
        self.assertIn("references/component-creation.md", report)
        for part in MODULE.ACCEPTED_ROUTE_PARTS:
            self.assertIn(part, report)
        for pillar in score.pillars:
            for sub in pillar.subscores:
                self.assertIn(sub.evidence, report)
        for cap in score.caps:
            self.assertIn(cap.reason, report)
        for unicode_ok in (False, True):
            MODULE.render_card(score, unicode_ok=unicode_ok)
        self.assertEqual(asdict(score), before)
        self.assertEqual(MODULE.render_markdown(score), report)

    def test_custom_findings_and_other_checks_are_not_summarized(self):
        score = unresolved_source_score()
        for measured in (False, True):
            for name in ("prompt", "search-space", "caller-check"):
                with self.subTest(measured=measured, name=name):
                    finding = "Caller finding: prompt is fetched at runtime; its value is unknown."
                    sub = MODULE.SubScore(name, 0, 8, measured, finding)
                    for pillar_name in ("agent", "dataset", "evaluation"):
                        pillar = MODULE.Pillar(pillar_name, 0, 0, (sub,))
                        card = MODULE.render_card(replace(score, pillars=(pillar,)))
                        self.assertIn(finding, card)
        custom = replace(
            MODULE.UNPROBED_DISCOVERED_KNOBS_CAP, reason="A custom source limitation."
        )
        self.assertIn(custom.reason, MODULE.render_card(replace(score, caps=(custom,))))

    def test_negative_build_observations_remain_explicitly_unverified_findings(self):
        entries = {
            "prompt": ({"present": False}, "no prompt"),
            "output-contract": ({"present": False}, "nothing constrains"),
            "control-flow": (
                {"loop": True, "bounded": False},
                "unbounded number of calls",
            ),
            "tools": (
                {"used": True, "declared": ["search"], "unreachable": ["search"]},
                "not found behind the name: search",
            ),
        }
        score = unresolved_source_score()
        for name, (entry, finding) in entries.items():
            with self.subTest(name=name):
                signal = MODULE.build_signal_from_entry(
                    name, entry | {"evidence": "An authored source observation."}
                )
                signal = MODULE.build_declarations_are_unmeasured((signal,))[0]
                sub = MODULE.SubScore(
                    name,
                    signal.points,
                    MODULE.AGENT_BUILD_WEIGHT[name],
                    signal.measured,
                    signal.evidence,
                )
                pillar = MODULE.Pillar("agent", 0, 0, (sub,))
                changed = replace(score, pillars=(pillar,))
                card = MODULE.render_card(changed)
                self.assertIn(finding, card)
                self.assertIn("not independently verified:", card)
                self.assertNotIn("An authored source observation.", card)
                self.assertIn(
                    "An authored source observation.", MODULE.render_markdown(changed)
                )

    def test_distinct_unavailable_findings_keep_their_explanations(self):
        facts = fixtures._read(
            fixtures._build_document(
                prompt={
                    "determined": False,
                    "reason": "the prompt is fetched at runtime",
                    "evidence": "This is an assistant observation.",
                }
            )
        )
        facts = replace(
            facts, build=MODULE.build_declarations_are_unmeasured(facts.build)
        )
        score = MODULE.score_run(
            fixtures._routing_corpus(),
            fixtures._passing_calibration(),
            facts,
            dict(MODULE.DEFAULT_WEIGHTS),
        )
        card = MODULE.render_card(score)
        self.assertIn("the prompt is fetched at runtime", card)
        self.assertNotIn("This is an assistant observation.", card)
        self.assertIn(
            "This is an assistant observation.", MODULE.render_markdown(score)
        )

    def test_missing_unread_unsupported_and_known_empty_agents_keep_their_routes(self):
        source = fixtures.UnsupportedSourceKeepsItsExplanationTests()
        cases = (
            ("missing", MODULE.AgentFacts(), True, "agent-absent", "No agent reached"),
            (
                "unread",
                MODULE.AgentFacts(origin=MODULE.BROUGHT),
                False,
                "agent-no-varying-knobs",
                "no reading of the agent reached",
            ),
            (
                "unsupported",
                source.facts("int call() { return 0; }\n", name="agent.cpp"),
                False,
                "agent-no-varying-knobs",
                "cannot be parsed as Python",
            ),
            (
                "known empty",
                source.facts(source.SOURCE),
                True,
                "agent-no-varying-knobs",
                "every configuration",
            ),
        )
        for name, facts, blocks, condition, finding in cases:
            with self.subTest(name=name):
                score = MODULE.score_run(
                    fixtures._routing_corpus(),
                    fixtures._passing_calibration(),
                    facts,
                    dict(MODULE.DEFAULT_WEIGHTS),
                )
                cap = next(cap for cap in score.caps if cap.condition == condition)
                self.assertEqual(cap.blocks, blocks)
                card = MODULE.render_card(score)
                self.assertIn(finding, card)
                self.assertEqual("FIX BEFORE PAID RUN" in card, blocks)
                self.assertEqual(
                    card.splitlines()[1],
                    f"Action: {MODULE.ACTION_DISPLAY_NAMES[score.recommended_action]}",
                )

    def test_every_supported_blocking_asking_and_advisory_cap_keeps_its_reason(self):
        # The existing renderer matrix enumerates every valid condition/state,
        # including non-bounding advisories. No hand-picked subset of blockers.
        states = (
            fixtures.TheCardSpeaksTheUsersLanguageTests()._scores_the_renderers_branch_on()
        )
        observed = set()
        for score in states:
            before = asdict(score)
            card = MODULE.render_card(score)
            first_pillar = min(
                (
                    card.index(f"  {pillar.name.upper():<11} ")
                    for pillar in score.pillars
                ),
                default=len(card),
            )
            for cap in score.caps:
                observed.add((cap.blocks, cap.asks))
                self.assertLess(card.index(MODULE.card_cap_reason(cap)), first_pillar)
                if cap == MODULE.UNPROBED_DISCOVERED_KNOBS_CAP:
                    self.assertIn(
                        "has not established which settings change the request", card
                    )
                else:
                    self.assertIn(cap.reason, card)
            self.assertEqual(
                card.splitlines()[1],
                f"Action: {MODULE.ACTION_DISPLAY_NAMES[score.recommended_action]}",
            )
            self.assertEqual(
                sum(line.startswith("Action: ") for line in card.splitlines()), 1
            )
            self.assertEqual(asdict(score), before)
        self.assertTrue({(True, False), (False, True), (False, False)} <= observed)

    def test_healthy_configuration_and_scored_observations_keep_their_evidence(self):
        score = fixtures._healthy_score()
        card = MODULE.render_card(score)
        self.assertEqual(
            card.splitlines()[1],
            f"Action: {MODULE.ACTION_DISPLAY_NAMES[score.recommended_action]}",
        )
        for pillar in score.pillars:
            for sub in pillar.subscores:
                self.assertIn(sub.evidence, card)
        self.assertNotIn("FIX BEFORE PAID RUN", card)
        self.assertNotIn("settings-check guidance", card)
        sub = MODULE.SubScore(
            "prompt", 6, 8, True, "A source finding that earned credit."
        )
        scored = replace(
            score,
            agent_source_read=True,
            pillars=(MODULE.Pillar("agent", 75, 1, (sub,)),),
        )
        self.assertIn(sub.evidence, MODULE.render_card(scored))

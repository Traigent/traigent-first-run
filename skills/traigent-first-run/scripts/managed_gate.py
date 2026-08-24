#!/usr/bin/env python3
"""Read the managed-stage gate off the trials the baseline already paid for.

The gate SKILL stage 7 opens after the local baseline checkpoint asks one
question - is there a measured opportunity here - and the answer decides
whether a customer is asked to pay for a managed search. That answer used to be
the assistant's to compose, and a blinded run composed this:

    The managed stage cannot improve quality (100%) or cost (baseline is the
    cheapest corner). Run it anyway to exercise the portal/tracking path, or
    stop at the baseline?

Three defects, and none of them is a sentence the guide ever asked for.
`cannot improve` is an outcome asserted about a search that had not run.
`baseline is the cheapest corner` is a claim about the whole space when twelve
configurations of it were priced. And the reason offered for spending money was
a part of the product getting exercised - a benefit to the vendor, worded at a
customer.

The vacuum is what produced them. The gate read accuracy and cost, and a
baseline that ties on quality with the cheapest tested configuration already in
hand reached it with nothing left to say - so something got invented. So the
reading and the routes are computed here instead of remembered there.
Everything below is a count over the trials handed in, and the one thing it
says about a configuration nobody tested is that nobody tested it.

**Latency is read and never sold.** It is the axis the reported run was missing,
and the honest thing to do with it is not to offer a search on it: the wrapper in
`references/sdk-execution.md` declares exactly two objectives - the run's own
metric, maximized, and cost, minimized - so a managed search cannot be pointed
at latency, and an option saying otherwise would be this same defect one axis
over. It is reported as measured evidence, with that limit stated, because a
spread the user paid to measure is theirs to see.

**A tie on quality closes the search routes.** Where no two tested
configurations were told apart on the metric, this evaluator ranked nothing, so
"cheaper at equal accuracy" has no equal accuracy to stand on. Only the repair
route and stopping remain, which is the rule SKILL stage 7 and `README.md`
already state and this file now enforces rather than restates.

Three sentences of stage 7 retired into this file, each now a condition rather
than a thing to remember: the ceiling-effect note, the accuracy-only
workflow-demonstration label, and the cost objective's weak-evidence flag.

Materiality carries no invented threshold. "Materially lower cost" needed a
number to become code and every candidate number was a guess. What replaces it
costs nothing to justify: a difference the printed figures do not show is not a
difference this gate claims, and the measured ratio is printed beside
`run-safety.md`'s own caution so a reader can see 1.02x for what it is.

It presents a reading, not a second question. The one ask still belongs to the
reply-ready line `references/run-safety.md` owns; the routes below are what that
ask is about.

It makes no call and contacts nothing: no provider, no Traigent backend, no
network, no user code imported or executed. It reads one JSON document and
prints.

Exits 0 when the gate was read, whichever way it came out - a gate that finds
nothing is a result and not a failure - 2 when the document cannot support a
gate, and 3 when this script itself breaks, which is never a finding about the
run.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import traceback
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

INPUT_ERROR_EXIT = 2
INTERNAL_ERROR_EXIT = 3
TRACEBACK_ENV = "TRAIGENT_FIRST_RUN_TRACEBACK"
ORIENTATIONS = ("maximize", "minimize")

# Printed whenever the document is refused. The contract lives in the refusal
# rather than in the guidance, because the guidance is byte-budgeted and this is
# not: an assistant that runs the tool wrong is told the exact shape and runs it
# right, and a shape stated in one place cannot drift from a second.
DOCUMENT_SHAPE = """expected one JSON object:

  {
    "metric": "<this run's own metric name>",
    "orientation": "maximize" | "minimize",
    "space": <total combination count of the enhanced space, optional>,
    "free_route": <true only when the provider genuinely charges nothing>,
    "trials": [
      {
        "label": "<how this configuration is named to the user>",
        "score": <this trial's value under "metric">,
        "cost": <measured cost, or omitted when the run could not price it>,
        "latency": <measured seconds, or omitted when none was recorded>,
        "incumbent": <true on the one configuration the user runs today>
      }
    ]
  }

"orientation" is the direction the run declared for this metric and is not
guessed: read the wrong way, every sentence about quality names the worst trial
as the best. Every completed trial carries a score and its own label. Omit
"cost" or "latency" rather than writing 0 for one that was never measured: an
unpriced trial is not a cheap trial, and a zero standing in for it is an absent
measurement wearing a number. Exactly one trial carries "incumbent": true - for
a baseline this run generated, that is its initial configuration."""


class GateInputError(Exception):
    """The document cannot support a gate. Reported, never worked around."""


@dataclass(frozen=True)
class Trial:
    label: str
    score: float
    cost: float | None
    latency: float | None
    incumbent: bool


@dataclass(frozen=True)
class Axis:
    """One dimension of the baseline, read only over the trials that carry it.

    `opportunity` is the whole point and is deliberately narrow: some trial in
    this document beat the incumbent on this axis, by a margin the printed
    figures actually show. Not "the space is large", not "a search usually
    helps" - both quantify over configurations nobody ran.

    `searchable` says whether a managed search can be pointed at this axis at
    all. It is a property of the objectives the run declares, not of the
    numbers, which is why it is carried here rather than decided at the point
    the routes are written.
    """

    name: str
    counted: int
    low: float
    high: float
    incumbent: float
    best_label: str
    best: float
    opportunity: bool
    ratio: float | None
    searchable: bool
    higher_is_better: bool

    def worse_than_incumbent(self, value: float) -> bool:
        """Is `value` worse than today's, in this axis's own direction?

        Carried on the axis rather than recomputed by the caller. The first
        version of the cross-axis note assumed every axis was lower-is-better,
        and reported a maximize metric's 0.78 as "worse" than 0.61 - the
        direction defect this axis already refuses in its main reading,
        reappearing in the sentence about the other axes.
        """
        if _figure(self.name, value) == _figure(self.name, self.incumbent):
            return False
        return (
            value < self.incumbent if self.higher_is_better else value > self.incumbent
        )

    @property
    def separates(self) -> bool:
        """Did this axis tell any two tested configurations apart, visibly?"""
        return _figure(self.name, self.low) != _figure(self.name, self.high)


def _printable(value: str, field: str) -> str:
    """Refuse a name that can forge lines of this tool's own output.

    Labels are written through `!r` and survive anything. The metric's name is
    read back in prose, and a newline in it buys a whole forged section - a
    `Verdict:` line, a route nobody computed - inside output SKILL stage 7 tells
    the assistant to read out as printed. So the characters that could do it
    never enter.
    """
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise GateInputError(f"{field} contains a control character")
    return value


def _number(value: Any, field: str, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GateInputError(f"trial {label!r}: {field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise GateInputError(f"trial {label!r}: {field} must be a finite number")
    return number


def _optional(value: Any, field: str, label: str, free_route: bool) -> float | None:
    if value is None:
        return None
    number = _number(value, field, label)
    if number < 0:
        raise GateInputError(f"trial {label!r}: {field} cannot be negative")
    # The one case run-safety.md separates by hand, enforced here because the
    # two are indistinguishable once they are in the document: a route that
    # genuinely charges nothing is a measurement, and a trial the run could not
    # price is not. Only the caller knows which, so only the caller may say -
    # and a free route is a property of the route, so `free_route` is checked
    # against every priced trial rather than excusing the one it stands beside.
    if number == 0 and field == "cost" and not free_route:
        raise GateInputError(
            f"trial {label!r}: a cost of 0 is either a genuinely free route or "
            'a trial nobody priced. Set "free_route": true when the provider '
            'charges nothing, or omit "cost" on a trial that was not priced.'
        )
    if number > 0 and field == "cost" and free_route:
        raise GateInputError(
            f'trial {label!r}: "free_route" says this provider charges nothing, '
            f"and this trial cost {number}. One of the two is wrong, and a "
            "document holding both lets an unpriced trial through as a cheap one."
        )
    # No free-route escape for time. A trial that ran took some, so a zero here
    # is a field nobody filled in rather than a fast configuration, and the
    # ratio it would produce divides by it.
    if number == 0 and field == "latency":
        raise GateInputError(
            f"trial {label!r}: a latency of 0 is a measurement nobody took. "
            'Omit "latency" on a trial that was not timed.'
        )
    return number


def read_document(raw: str) -> tuple[str, str, int | None, list[Trial]]:
    """Parse one gate document, refusing anything a gate cannot be read from."""
    try:
        document = json.loads(raw)
    except ValueError as error:
        raise GateInputError(f"the document is not JSON ({error})") from error
    if not isinstance(document, dict):
        raise GateInputError("the document is not a JSON object")

    metric = document.get("metric")
    if not isinstance(metric, str) or not metric.strip():
        raise GateInputError('"metric" must name this run\'s own metric')
    metric = _printable(metric, '"metric"')

    orientation = document.get("orientation")
    if orientation not in ORIENTATIONS:
        raise GateInputError(
            '"orientation" must be "maximize" or "minimize" - the direction '
            "this run declared for its own metric. It is not defaulted: an "
            "error rate read as if higher were better names the worst trial as "
            "the best one, and says so in the same words as a real finding."
        )

    space = document.get("space")
    if space is not None:
        if isinstance(space, bool) or not isinstance(space, int) or space < 1:
            raise GateInputError('"space" must be a positive whole number when given')

    free_route = document.get("free_route", False)
    if not isinstance(free_route, bool):
        raise GateInputError('"free_route" must be true or false when given')

    entries = document.get("trials")
    if not isinstance(entries, list) or not entries:
        raise GateInputError('"trials" must be a non-empty list')

    trials: list[Trial] = []
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise GateInputError(f"trial {position} is not a JSON object")
        label = entry.get("label")
        if not isinstance(label, str) or not label.strip():
            raise GateInputError(f'trial {position} needs a "label" the user reads')
        label = _printable(label, f"trial {position}'s label")
        if any(label == seen.label for seen in trials):
            raise GateInputError(
                f"two trials are both labelled {label!r}; every sentence naming "
                "a configuration would name both of them"
            )
        if "score" not in entry:
            raise GateInputError(f"trial {label!r}: every completed trial has a score")
        incumbent = entry.get("incumbent", False)
        if not isinstance(incumbent, bool):
            raise GateInputError(f'trial {label!r}: "incumbent" must be true or false')
        trials.append(
            Trial(
                label=label,
                score=_number(entry["score"], "score", label),
                cost=_optional(entry.get("cost"), "cost", label, free_route),
                latency=_optional(entry.get("latency"), "latency", label, free_route),
                incumbent=incumbent,
            )
        )

    # A space smaller than what was tested in it is arithmetic that cannot be
    # true, and the sentence it produces - "the space holds 4 and 12 of them
    # were tested here" - is the reader's first clue that a number they were
    # given is wrong. Refuse it where it enters instead.
    if space is not None and space < len(trials):
        raise GateInputError(
            f'"space" is {space} and {len(trials)} trials were tested in it; a '
            "space cannot hold fewer configurations than the run reached."
        )

    marked = [trial for trial in trials if trial.incumbent]
    if len(marked) != 1:
        # Without it there is no "better than what you run now", and every
        # statement below collapses into a claim about the space.
        raise GateInputError(
            f'exactly one trial carries "incumbent": true; {len(marked)} do. '
            "The gate compares against the configuration the user runs today, "
            "so it cannot be read without knowing which one that is."
        )
    return metric, orientation, space, trials


def read_axis(
    name: str,
    values: list[tuple[str, float]],
    incumbent: float,
    *,
    higher_is_better: bool,
    searchable: bool,
) -> Axis:
    """One axis over the trials that carried it, in its own declared direction."""
    numbers = [value for _label, value in values]
    if higher_is_better:
        best_label, best = max(values, key=lambda pair: pair[1])
    else:
        best_label, best = min(values, key=lambda pair: pair[1])
    # A margin the printed figures do not show is not a margin. Comparing what
    # the reader will actually see costs no invented tolerance, and it refuses
    # the two shapes a raw `<` produced: a saving of one part in ten million
    # sold as a saving, and a tie at the top reported as separation - which
    # also silently removed the repair route beneath it.
    visible = _figure(name, best) != _figure(name, incumbent)
    opportunity = visible and (
        best > incumbent if higher_is_better else best < incumbent
    )
    ratio: float | None = None
    if opportunity:
        larger, smaller = (best, incumbent) if higher_is_better else (incumbent, best)
        if smaller > 0 and math.isfinite(larger / smaller):
            ratio = larger / smaller
    return Axis(
        name=name,
        counted=len(values),
        low=min(numbers),
        high=max(numbers),
        incumbent=incumbent,
        best_label=best_label,
        best=best,
        opportunity=opportunity,
        ratio=ratio,
        searchable=searchable,
        higher_is_better=higher_is_better,
    )


def read_axes(trials: list[Trial], orientation: str) -> dict[str, Axis]:
    """Quality always, and each of the other two only where it can be compared.

    Quality is read from one trial upwards because every completed trial carries
    a score, and a single-trial reading is honest: it separates nothing and
    offers nothing. Cost and latency need two readings, one of them the
    incumbent's - a saving measured against a configuration nobody priced is a
    saving over an unknown. An axis missing from the result is one the trials
    could not support, and `measured_lines` says which of those two happened
    rather than reporting it as unmeasured.
    """
    incumbent = next(trial for trial in trials if trial.incumbent)
    axes: dict[str, Axis] = {
        "quality": read_axis(
            "quality",
            [(trial.label, trial.score) for trial in trials],
            incumbent.score,
            higher_is_better=orientation == "maximize",
            searchable=True,
        )
    }
    readings: tuple[
        tuple[str, Callable[[Trial], float | None], float | None, bool], ...
    ]
    readings = (
        ("cost", lambda trial: trial.cost, incumbent.cost, True),
        # Not searchable: see the module docstring. The wrapper declares the
        # metric and cost, and nothing else.
        ("latency", lambda trial: trial.latency, incumbent.latency, False),
    )
    for name, reading, mine, searchable in readings:
        carried = [
            (trial.label, value)
            for trial in trials
            if (value := reading(trial)) is not None
        ]
        if len(carried) >= 2 and mine is not None:
            axes[name] = read_axis(
                name,
                carried,
                mine,
                higher_is_better=False,
                searchable=searchable,
            )
    return axes


def _figure(name: str, value: float) -> str:
    if name == "quality":
        return f"{value:.4f}"
    if name == "cost":
        # Significant figures, not decimal places. A route billing in
        # billionths had every trial print `0.000000`, so a real nine-fold
        # difference read as no difference at all.
        return f"{value:.6g}"
    return f"{value:.2f}s"


def _configurations(count: int) -> str:
    return "1 configuration" if count == 1 else f"{count} configurations"


# One verb per axis, so the comparison reads as the measurement it is rather
# than as a generic "beat". Scoring, spending and taking time are three
# different things and a reader takes them as three different sentences.
_COMPARISON = {
    "quality": "scored {best} against {incumbent}",
    "cost": "cost {best} against {incumbent}",
    "latency": "ran in {best} against {incumbent}",
}


def measured_lines(axes: dict[str, Axis], trials: list[Trial]) -> list[str]:
    total = len(trials)
    carriers = {
        "quality": total,
        "cost": sum(1 for trial in trials if trial.cost is not None),
        "latency": sum(1 for trial in trials if trial.latency is not None),
    }
    incumbent = next(trial for trial in trials if trial.incumbent)
    has = {"quality": True, "cost": incumbent.cost, "latency": incumbent.latency}
    lines = []
    for name in ("quality", "cost", "latency"):
        axis = axes.get(name)
        if axis is None:
            # Three different absences, and calling all three "not measured"
            # was false about two of them.
            if carriers[name] == 0:
                why = f"no trial recorded a {name}, so this gate reads no {name} axis."
            elif has[name] is None:
                why = (
                    f"{carriers[name]} of the {total} recorded a {name}, and the "
                    "configuration you run now did not, so there is nothing to "
                    "compare them against."
                )
            else:
                why = (
                    f"only {carriers[name]} trial recorded a {name}, which ranks "
                    "nothing on its own."
                )
            lines.append(f"  {name:<8} {why}")
            continue
        span = (
            f"{_figure(name, axis.low)} to {_figure(name, axis.high)}"
            if axis.separates
            else f"{_figure(name, axis.low)} on every one of them"
        )
        over = (
            f"all {total}"
            if axis.counted == total
            else f"{axis.counted} of the {total}"
        )
        head = f"  {name:<8} {span}, over {over}."
        if axis.opportunity:
            tail = (
                f" {axis.best_label!r} beat the configuration you run now "
                f"({_figure(name, axis.incumbent)})."
            )
        elif axis.separates:
            tail = (
                " Nothing tested beat the configuration you run now"
                f" ({_figure(name, axis.incumbent)})."
            )
        else:
            tail = " Nothing tested was told apart from anything else."
        lines.append(head + tail)
    return lines


def unmeasured_lines(
    axes: dict[str, Axis], metric: str, space: int | None, trials: int
) -> list[str]:
    lines = [
        "  Every line above counts these trials and says nothing about any "
        "configuration",
        "  they did not include. A managed search has not run, so what it "
        "would find is",
        "  unmeasured; this gate does not estimate it.",
    ]
    if "latency" in axes:
        lines.append(
            f"  This run's search is declared on {metric} and cost, so the "
            "latency above is"
        )
        lines.append(
            "  evidence you paid to measure rather than something the search "
            "can be aimed at."
        )
    if space is not None:
        lines.append(
            f"  The space holds {_configurations(space)} and {trials} of them "
            "were tested here."
        )
    return lines


def routes(
    axes: dict[str, Axis], metric: str, readings: dict[str, dict[str, float]]
) -> list[tuple[str, list[str]]]:
    """The closed set of routes, each with the measured line it stands on.

    Closed is the point. The improvised offer this file exists to replace was on
    no list, and a route nobody can add is a route nobody has to justify
    inventing.
    """
    quality = axes["quality"]
    listed: list[tuple[str, list[str]]] = []
    # A tie on the metric closes every search route, not only the quality one.
    # "Cheaper at equal accuracy" needs an equal accuracy this evaluator did not
    # establish, and README.md promises the managed stage only where the
    # evaluator can tell configurations apart.
    chosen = (
        [axis for axis in axes.values() if axis.opportunity and axis.searchable]
        if quality.separates
        else []
    )
    for axis in chosen:
        ratio = f" ({axis.ratio:.2f}x)" if axis.ratio is not None else ""
        beat = _COMPARISON[axis.name].format(
            best=_figure(axis.name, axis.best),
            incumbent=_figure(axis.name, axis.incumbent),
        )
        body = [
            f"Search on {axis.name}{ratio}. This evidence can rank {axis.name}: "
            f"{axis.best_label!r}",
            f"{beat} on your own rows. A managed search measures {axis.name} " "across",
            "configurations this grid did not reach - a measurement over your "
            "rows, not a",
            "promise of a better one.",
        ]
        body.extend(_given_up(axes, axis, readings))
        if axis.name == "cost":
            body.append(
                "Report any gain as cost, and as weak evidence at this sample "
                "size: two"
            )
            body.append(
                "points a few percent apart are inside what re-measuring one "
                "configuration moves."
            )
        if axis.name == "quality":
            body.append(
                "An accuracy-only search is a workflow demonstration; label it "
                "as one."
            )
        listed.append((f"Search on {axis.name}", body))

    if not quality.separates:
        listed.append(
            (
                "Repair the evidence first",
                [
                    "Repair the evidence first. Every trial scored "
                    f"{_figure('quality', quality.low)} on {metric}, so this",
                    "evaluator and these rows did not separate the "
                    "configurations they were",
                    "given. A ceiling in your agent is one hypothesis and this "
                    "run tested",
                    "none of them; harder realistic cases are what would.",
                ],
            )
        )
    # Last and never conditional. It is a complete outcome rather than the
    # absence of one, so it is stated in those words wherever the gate comes
    # out - a first run that stops here has finished, not given up.
    listed.append(
        (
            "Stop at the baseline",
            [
                "Stop at the baseline. The result you already have is measured, "
                "is yours,",
                "and answers what your current setup scores and costs. It is a "
                "complete",
                "first run rather than a partial one, and nothing above is owed.",
            ],
        )
    )
    return listed


def _given_up(
    axes: dict[str, Axis], chosen: Axis, readings: dict[str, dict[str, float]]
) -> list[str]:
    """Every measured axis on which this route's winner is worse than today's."""
    said = []
    for name, axis in axes.items():
        if name == chosen.name:
            continue
        mine = readings.get(name, {}).get(chosen.best_label)
        if mine is None or not axis.worse_than_incumbent(mine):
            continue
        said.append(
            f"On {name} it is worse than what you run now: "
            f"{_figure(name, mine)} against"
        )
        said.append(f"{_figure(name, axis.incumbent)}, measured on the same rows.")
    return said


def readings_by_label(trials: list[Trial]) -> dict[str, dict[str, float]]:
    """Each axis's value per configuration, for the cross-axis note above."""
    table: dict[str, dict[str, float]] = {"quality": {}, "cost": {}, "latency": {}}
    for trial in trials:
        table["quality"][trial.label] = trial.score
        if trial.cost is not None:
            table["cost"][trial.label] = trial.cost
        if trial.latency is not None:
            table["latency"][trial.label] = trial.latency
    return table


def supported(axes: dict[str, Axis]) -> list[str]:
    """The axes this gate found a measured opportunity on and can search."""
    if not axes["quality"].separates:
        return []
    return [axis.name for axis in axes.values() if axis.opportunity and axis.searchable]


def render(
    metric: str, orientation: str, space: int | None, trials: list[Trial]
) -> str:
    axes = read_axes(trials, orientation)
    found = supported(axes)
    lines = [
        f"Gate on the baseline's own trials: {_configurations(len(trials))}, "
        f"metric {metric!r}, declared {orientation}.",
        "",
        "Measured",
        *measured_lines(axes, trials),
        "",
        "Not measured",
        *unmeasured_lines(axes, metric, space, len(trials)),
        "",
    ]
    if found:
        lines.append(
            "Verdict: this gate supports a measured opportunity on "
            + ", ".join(found)
            + "."
        )
    elif not axes["quality"].separates:
        lines.append(
            "Verdict: this gate supports no measured opportunity. This "
            "evaluator told no two"
        )
        lines.append("tested configurations apart, so nothing here can rank a search.")
    else:
        lines.append(
            "Verdict: this gate supports no measured opportunity. Nothing "
            "tested beat the"
        )
        lines.append("configuration the user runs today on any axis it can search.")
    lines.append("")
    lines.append("What this evidence supports")
    table = readings_by_label(trials)
    for number, (_title, body) in enumerate(routes(axes, metric, table), start=1):
        for position, line in enumerate(body):
            lines.append(f"  {number}. {line}" if position == 0 else f"     {line}")
    return "\n".join(lines)


def as_json(
    metric: str, orientation: str, space: int | None, trials: list[Trial]
) -> str:
    axes = read_axes(trials, orientation)
    table = readings_by_label(trials)
    return json.dumps(
        {
            "metric": metric,
            "orientation": orientation,
            "space": space,
            "trials_read": len(trials),
            "incumbent": next(trial.label for trial in trials if trial.incumbent),
            "axes": {
                name: {
                    "counted": axis.counted,
                    "low": axis.low,
                    "high": axis.high,
                    "incumbent": axis.incumbent,
                    "best": axis.best,
                    "best_label": axis.best_label,
                    "separates": axis.separates,
                    "opportunity": axis.opportunity,
                    "ratio": axis.ratio,
                    "searchable": axis.searchable,
                }
                for name, axis in axes.items()
            },
            "opportunity": supported(axes),
            "routes": [title for title, _body in routes(axes, metric, table)],
        },
        indent=2,
        # No path below produces a non-finite float today - every number is
        # validated finite on the way in and the one derived value, the
        # ratio, is dropped when it is not. This says so to the encoder
        # rather than to a reader, because `json.dumps` writes `Infinity`
        # by default, Python reads it back, and no other parser does. It is
        # the one assertion here no test can kill, which is recorded in
        # `tests/test_managed_gate.py` rather than left looking covered.
        allow_nan=False,
    )


class _Parser(argparse.ArgumentParser):
    """A misspelled flag is this tool breaking, not a document being refused.

    Exit 2 is spent on "the document cannot support a gate", which is a finding
    about the run. argparse's own 2 would report that finding falsely.
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: {message}", file=sys.stderr)
        raise SystemExit(INTERNAL_ERROR_EXIT)


def run(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(
        description=(
            "Read the managed-stage gate from the baseline's own completed "
            "trials: which axes this run measured, what it did not measure, "
            "and the routes that follow. Makes no call of any kind."
        ),
        epilog=DOCUMENT_SHAPE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--trials",
        required=True,
        help="the gate document (path, or - for stdin); --help states its shape",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the reading as JSON on stdout"
    )
    args = parser.parse_args(argv)

    try:
        raw = sys.stdin.read() if args.trials == "-" else Path(args.trials).read_text()
    except (OSError, UnicodeDecodeError) as error:
        print(f"the gate document cannot be read: {error}", file=sys.stderr)
        return INPUT_ERROR_EXIT
    try:
        metric, orientation, space, trials = read_document(raw)
    except GateInputError as error:
        print(f"managed_gate.py: {error}", file=sys.stderr)
        print("", file=sys.stderr)
        print(DOCUMENT_SHAPE, file=sys.stderr)
        return INPUT_ERROR_EXIT

    reading = as_json if args.json else render
    print(reading(metric, orientation, space, trials))
    return 0


def report_internal_error(tool: str, error: BaseException) -> int:
    """Say the check broke, not the project - copied out per script by design.

    Each bundled script owns this boundary, because each ships alone. The stack
    is available behind an environment variable rather than printed at a user
    who did not ask for it, and the message names the variable, because a
    diagnosis nobody can act on is a traceback with extra steps.
    """
    print(f"{tool}: {type(error).__name__}: {error}", file=sys.stderr)
    print(
        f"{tool} could not complete. This is a defect in the check rather than "
        "in your project; no gate was read, so treat none as reported. Re-run "
        f"with {TRACEBACK_ENV}=1 and report the output.",
        file=sys.stderr,
    )
    if os.environ.get(TRACEBACK_ENV):
        traceback.print_exc()
    return INTERNAL_ERROR_EXIT


def main() -> int:
    try:
        return run()
    except Exception as error:  # noqa: BLE001 - reported, never swallowed
        return report_internal_error("managed_gate.py", error)


if __name__ == "__main__":
    sys.exit(main())

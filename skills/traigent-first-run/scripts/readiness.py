#!/usr/bin/env python3
"""Plan a Traigent first run from Agent/Dataset/Evaluation provenance."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Literal

ComponentState = Literal["real", "demo", "missing", "invalid"]
COMPONENTS = ("agent", "dataset", "evaluation")


@dataclass(frozen=True)
class ReadinessPlan:
    states: dict[str, ComponentState]
    real_ready_count: int
    walkthrough_ready_count: int
    missing_real: list[str]
    create: list[str]
    action: str


def build_plan(
    agent: ComponentState,
    dataset: ComponentState,
    evaluation: ComponentState,
) -> ReadinessPlan:
    """Return the dependency-aware completion plan for one starting state."""
    states: dict[str, ComponentState] = {
        "agent": agent,
        "dataset": dataset,
        "evaluation": evaluation,
    }
    real = {name for name, state in states.items() if state == "real"}
    usable = {name for name, state in states.items() if state in {"real", "demo"}}
    missing = [name for name in COMPONENTS if name not in usable]

    if real == set(COMPONENTS):
        create: list[str] = []
        action = "Validate and use all three real components without replacement."
    elif "demo" in states.values():
        create = missing
        action = (
            "Preserve existing walkthrough substitutes, create only missing pieces, "
            "and validate the complete system."
        )
    elif real == {"agent", "dataset"}:
        create = ["evaluation"]
        action = "Build evaluation from the real agent output and dataset expectations."
    elif real == {"agent", "evaluation"}:
        create = ["dataset"]
        action = (
            "Build a dataset that exercises the real agent and matches the evaluation."
        )
    elif real == {"dataset", "evaluation"}:
        create = ["agent"]
        action = (
            "Build an agent whose input and output contracts match both real anchors."
        )
    elif real == {"agent"}:
        create = ["dataset", "evaluation"]
        action = "Build the dataset from the agent contract, then evaluation from both."
    elif real == {"dataset"}:
        create = ["agent", "evaluation"]
        action = "Build an agent from the dataset contract, then evaluation from both."
    elif real == {"evaluation"}:
        create = ["dataset", "agent"]
        action = "Build scoreable data for the evaluation, then an agent matching both."
    elif not real and not usable:
        create = ["agent", "dataset", "evaluation"]
        action = "Ask once for task intent, then build one coherent walkthrough system."
    else:
        create = missing
        action = "Repair invalid components around the real anchors, then validate the system."

    return ReadinessPlan(
        states=states,
        real_ready_count=len(real),
        walkthrough_ready_count=len(usable),
        missing_real=[name for name in COMPONENTS if name not in real],
        create=create,
        action=action,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan a first run from Agent/Dataset/Evaluation provenance."
    )
    choices = ("real", "demo", "missing", "invalid")
    parser.add_argument("--agent", choices=choices, required=True)
    parser.add_argument("--dataset", choices=choices, required=True)
    parser.add_argument("--evaluation", choices=choices, required=True)
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable output"
    )
    return parser.parse_args()


def render_text(plan: ReadinessPlan) -> str:
    """Render real readiness separately from generated walkthrough substitutes."""
    lines = [f"Real-world readiness: {plan.real_ready_count}/3"]
    for name in COMPONENTS:
        state = plan.states[name]
        if state == "real":
            lines.append(f"✅ {name.title()}: real")
        elif state == "invalid":
            lines.append(f"❗ {name.title()}: validation failed")
        else:
            lines.append(f"❗ {name.title()}: no real component is connected")

    demo_components = [name for name in COMPONENTS if plan.states[name] == "demo"]
    if demo_components:
        lines.extend(("", "Walkthrough setup:"))
        for name in demo_components:
            lines.append(f"🛠️ {name.title()}: generated walkthrough substitute")

    lines.append(f"Action: {plan.action}")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    plan = build_plan(args.agent, args.dataset, args.evaluation)
    if args.json:
        print(json.dumps(asdict(plan), indent=2, sort_keys=True))
        return 0

    print(render_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fixture stub: echoes the wiring only, makes no model call.

Present and importable, so a presence test finds "an agent" - but it performs no
identifiable task, so it anchors no task intent. Knob families a reader might
guess an intent from (model, temperature, prompt style, retries, verbosity,
output format) are deliberately named and unused, which is what makes guessing
from a stub so easy to do wrongly.
"""


def run(payload, config=None):
    return {"echo": payload, "config": config or {}}

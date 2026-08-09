"""Existing project-owned deterministic evaluator."""


def score_intent(*, output, expected, input_data, metadata):
    del input_data, metadata
    return float(str(output).strip().casefold() == str(expected).strip().casefold())

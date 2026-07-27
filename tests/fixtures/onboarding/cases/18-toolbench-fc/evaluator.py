"""Deterministic exact-match evaluator. Returns 1.0 on match else 0.0."""
def score(output, expected, input_data=None, metadata=None):
    return 1.0 if str(output).strip().lower() == str(expected).strip().lower() else 0.0

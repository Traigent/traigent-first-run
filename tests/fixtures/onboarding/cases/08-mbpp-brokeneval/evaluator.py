"""BROKEN evaluator: returns a constant pass for everything.
This is a deliberate handicap - onboarding must detect it and refuse to trust it."""
def score(output, expected, input_data=None, metadata=None):
    return 1.0   # scores a wrong answer exactly like a right one

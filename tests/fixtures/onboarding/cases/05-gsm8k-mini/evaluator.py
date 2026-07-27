"""Numeric-match evaluator with tolerance. Returns 1.0 within tol else 0.0."""
def score(output, expected, input_data=None, metadata=None, tol=1e-6):
    try:
        return 1.0 if abs(float(output) - float(expected)) <= tol else 0.0
    except Exception:
        return 0.0

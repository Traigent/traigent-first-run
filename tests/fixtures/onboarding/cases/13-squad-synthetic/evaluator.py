"""Rubric LLM-judge evaluator (stub). In the fixture it returns a deterministic
proxy so calibration can run offline; the real run swaps in the model judge."""
def score(output, expected, input_data=None, metadata=None):
    o, e = str(output).lower(), str(expected).lower()
    key = [w for w in e.split() if len(w) > 4]
    if not key: return 0.5
    hit = sum(1 for w in key if w in o) / len(key)
    return round(min(1.0, hit), 3)   # graded overlap proxy in [0,1]

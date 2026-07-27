"""Order-insensitive set comparison for SQL result rows / collections."""
def score(output, expected, input_data=None, metadata=None):
    def norm(x): return set(str(x).replace("\n"," ").split())
    a, b = norm(output), norm(expected)
    if not b: return 0.0
    return len(a & b) / len(a | b)   # Jaccard, in [0,1]

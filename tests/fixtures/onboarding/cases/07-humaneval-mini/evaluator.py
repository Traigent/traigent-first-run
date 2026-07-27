"""Execution/unit-test evaluator for code. Runs the row's test against the output."""
def score(output, expected, input_data=None, metadata=None):
    test = (metadata or {}).get("test")
    if not test:
        return 0.0
    ns = {}
    try:
        exec(output, ns)          # define the candidate function
        exec(test, ns)            # run the assertion(s)
        return 1.0
    except Exception:
        return 0.0                # evaluator error vs wrong answer handled by caller

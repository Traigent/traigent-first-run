# 0159 - the SDK cost limit is kept only for priced routes

follows: 0158
follows-total-measured: 598_821
total-ceiling: 601_000
total-measured: 600_127

SDK 0.31.1 raises `CostTrackingRequiredError` when an explicit cost limit is set and a trial reports
no cost, which `run_wrapper.py` always caused for a route the SDK cannot price. The wrapper now asks
the SDK's own price lookup about the searched models and, for an unpriced route with the spend
ledger installed, removes `TRAIGENT_RUN_COST_LIMIT` so the ledger is the gate. An unknown lookup
counts as unpriced, and without the ledger the limit stays and the SDK fails the run loudly.

The bytes are the two small helpers and the guarded block in `run_wrapper.py`. Resident and document
do not move; total is raised by the smallest round figure that clears the measurement.

# 0010 - the optional round that looks for a cheaper point on the frontier

follows: 0009
resident-ceiling: 64_250
resident-measured: 63_999
total-ceiling: 256_250
total-measured: 255_523

#140 adds a whole optional stage, and a stage is the largest unit of guidance
this package has. It reads both runs already paid for, computes the non-
dominated set over quality and cost, and offers the cheapest point that holds
quality - so the arithmetic, what counts as dominated, why an absent cost is
dropped rather than read as zero, and how a null outcome is reported all have to
be written down somewhere a reader can check them. That is `sdk-execution.md`,
which owns the wrapper and the trial records the frontier is computed from, and
it takes almost all of the ten kilobytes.

SKILL.md takes the ordering only: where the round sits, that it is optional, and
that a null result is a finding to report rather than a step to skip quietly.
Resident moves by about thirteen hundred bytes against ten thousand.

255_523 measured. This is the largest single increment in the ledger and the
first where the branch's own reasoning about placement survives the merge
intact, because nothing else touched `sdk-execution.md` this deeply.

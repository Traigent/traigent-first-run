# 0062 - supported space before spend

follows: 0061
follows-resident-measured: 86_303
follows-total-measured: 430_436
resident-ceiling: 86_750
resident-measured: 86_586
total-ceiling: 432_000
total-measured: 431_854

The first-run wrapper now rejects a literal boolean in either finalized space
before the customer approves the Basic-to-Enhanced path. The pinned cloud SDK
would otherwise accept the local baseline and reject connected session creation
before its first trial. The guidance must distinguish generated `off`/`on`
labels from a customer-owned boolean, which stays unchanged and receives an
honest local-only or later/manual recovery. These bytes replace a false
universal boolean rule with the actual paid-boundary contract; they do not
coerce customer material, invent a fallback, or duplicate the SDK validator.

# Offline behavioral-contract harness

This internal test layer verifies only the deterministic, pre-network portion of the first-run
contract. It checks the zero-anchor stop, preservation and generated-dataset invariants, local
calibration, evidence-based quality findings, allowed writes, and external-action boundaries.

It is not a customer walkthrough, an SDK/provider/backend test, or proof that an arbitrary coding
assistant follows the skill. It emits no optimization result, cost, or portal link. A failed live
connection must remain a visible failure; production onboarding must never fall back to this
harness.

CI runs every scenario twice as an unprivileged user in a read-only container with no network.
The fixture locks protect the three starting states, and `behavior.lock.json` makes changes to the
behavior-bearing guide, references, assets, or scripts require explicit scenario requalification.

The connected staging smoke test remains responsible for SDK compatibility, real provider and
Traigent calls, cost/quota behavior, visible baseline and enhanced trials, holdout reporting,
portal persistence, and direct experiment links.

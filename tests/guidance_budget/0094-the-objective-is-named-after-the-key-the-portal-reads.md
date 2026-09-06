# 0094 - the objective is named after the key the portal reads

follows: 0093
follows-resident-measured: 106_268
follows-total-measured: 497_682
follows-document-measured: 136_047
resident-ceiling: 106_500
resident-measured: 106_368
total-ceiling: 498_300
total-measured: 498_243
document-ceiling: 137_550
document-measured: 136_303

The objective is named after the key the portal reads. The worked example's quality objective
was `task_success`, and the frontier helper told readers never to use `accuracy` because the SDK
kept its built-in exact match under that key. The portal reads exactly one key for quality, and
it is `accuracy`: measured on 2026-09-06 against production, twelve trials scoring 5.6% to 83.3%
locally were persisted and shown as 0% on every row. Renamed, the same scorer's values appear,
and the SDK parks its built-in at `exact_match_default`. The example, the `metric_functions`
wiring, the frontier docstring and the naming rule now say `accuracy` and why. Two further
sentences ride along, each from the same rehearsal: clone beside the project rather than inside
it, and prove the SDK delivers row metadata before a scorer that reads it spends anything, since
the 0.26.0 loader nests an explicit `metadata` object one level down. One comment at the enhanced
launch pins `timeout` at `None`, where a written 600 s cut a twelve-trial search at seven. No
ceiling moves: every figure rose and stays under the ceiling 0093 declared, restated unchanged.

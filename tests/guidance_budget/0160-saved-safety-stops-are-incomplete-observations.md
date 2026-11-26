# 0160 - saved safety stops are incomplete observations

follows: 0159
follows-total-measured: 599_362
total-ceiling: 599_483
total-measured: 599_345

The generated adapter now saves observations when a safety refusal interrupts its baseline.
Its exit-three explanation must therefore cover a record containing successful rows but no
ordinary failures. Replacing a fixed enumeration with diagnostic instructions preserves the
distinction between an interrupted comparison and a completed result. Readers inspect the stop
reason and unfinished rows, retain the accumulated debit, and avoid declaring a winner
from the incomplete run or buying the same unexplained failure again.

Timeout and exhausted-budget handling still belong to the existing Recovery section. Other
safety refusals need diagnosis rather than an unsupported assumption about remaining funds.
This revision changes only the generated baseline explanation, leaves SDK-managed execution
ownership intact, and removes seventeen measured bytes. The total ceiling falls by the
same seventeen bytes, preserving the predecessor's headroom while recording this prune.

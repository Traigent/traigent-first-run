# 0156 - the gold reason names a kind and the partial baseline is routed

follows: 0155
follows-total-measured: 592_348
total-ceiling: 594_500
total-measured: 594_147

Review of 0154/0155 found that the gold check published the customer's own answer. The parser quoted
the token it stopped on, so a gold row ending in a string literal put that literal, in full, into a
`dataset-integrity` finding - and that detail reaches the card, the written report, and the
assistant's own context, which is off the customer's machine. `run-safety.md` keeps per-example
expected text out of even the local run logs without an informed opt-in, and a finding is not that
opt-in.

The first fix redacted the finished string and was wrong. The text is built by `repr`, which switches
to double quotes for a value containing an apostrophe, so a scanner looking for `'` walked straight
past `"O'Brien ..."` - and SQL's own `''` escape makes an apostrophe the ordinary case rather than the
exotic one. Four of eleven realistic gold shapes still leaked in full. The parser now names the
token's KIND and never its text, at the two places that could interpolate it, so there is nothing
left to redact. That is also the more useful half: `at token 5 (a string literal)` tells a reader
what stopped the parse, where the old text told them a fragment of their own row. The comparator's
public surface is unchanged - a third public name was tried and the shipping constraint on that file
is two.

`sdk-execution.md` gains the route for a generated-bridge baseline that ends exit 3, which no
document carried. Three states reach that exit; the paragraph names them, and hands the timeout back
to `run-safety.md`'s Recovery rules, which already own it and prescribe showing the best partial
result. An earlier draft said "do not carry it into the enhanced phase" and so contradicted both
Recovery and the cumulative-debit rule 300 lines below it - a budget figure that must be carried or
the next phase relaunches against the full ceiling. It is the winner that may not be carried, and the
paragraph now says so. It also defers to the commands the generator prints instead of naming bridge
paths literally, and says that without backticking either name, because the contract section's
backticked identifiers are read as adaptation sites that must exist in the fence.

`run_wrapper.py` gains one paragraph and one pointer. The mock flag is now blanked rather than left
absent after its refusal: a refusal that removes a name leaves exactly the state a later dotenv load
refills, and the SDK re-reads that flag on every call, so a value arriving afterwards would run a
paid phase on canned responses with the refusal already passed. The two offline spellings stay
refused-not-cleared, and the four lines beside them point at the contract in `sdk-execution.md` that
already settled it rather than re-deriving it here.

Total is raised by the smallest round figure that clears the measurement: +758 in `run_wrapper.py`
and +1_041 in `sdk-execution.md`. Resident and document do not move - `GUIDE.md`, `SKILL.md` and
`run-safety.md` are untouched by this round.

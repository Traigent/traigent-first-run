# 0026 - one remedy per verdict, and a bounded top-up

follows: 0025
follows-resident-measured: 74_154
follows-total-measured: 327_063
resident-ceiling: 75_900
resident-measured: 75_702
total-ceiling: 332_400
total-measured: 332_050

Three dataset conditions told the customer the same thing and then did opposite
things with their run. Measured through `power_ceiling` on trunk `6de98918`,
`get-data` was emitted for an absent dataset, for zero comparable rows, and for
anything from one comparable row to twenty-nine, halting the first two and
waving the rest through. A consumer switching on `recommended_action` had no way
to separate a project holding no examples from a project holding a few, and the
person reading the card was handed one instruction whose meaning depended on a
field beside it.

Splitting the slug is what removed that, and the guidance had to move with it
because SKILL.md is where each condition is routed to a branch. The size
conditions stopped pointing at data collection and started pointing at an offer
this run performs itself; a fourth condition appeared for the split whose tuning
side holds nothing scoreable, which had been travelling as a second reading of
the small-dataset cap and wanted its own line, its own repair, and no suggestion
that anybody go looking for rows. Three bullets, replacing two, and the sentence
above them that promised readers a scoping route which sometimes halts no longer
had a dataset condition behind it.

The paragraph in stage 2 is the part worth defending, since bytes there sit in
front of the assistant for the entire walkthrough. It buys one sentence of
mandate: a shortfall is folded into the question already being asked about
missing components rather than becoming a second one. Without it the likeliest
outcome is two prompts in two turns, each individually defensible, which is
precisely the shape the discovery question was introduced to abolish. The
paragraph also fixes the offer at twenty-eight rows in total, states that
figure, and refuses to leave it implied - an unnumbered promise to write more
examples invites somebody to picture an unbounded generation bill, and that
worry is cheaper to answer once in the mandate than to reassure about later.

Depth went where CLAUDE.md sends it. Which sentence each ceiling gets, and the
point above which there is no offer left to make, live in the creation reference
beside the wording of the question they ride on. Where a drawn row lands stays
with the split rule that already answers it for real rows, because a second
placement rule would be a second answer to one question and the two would be
free to disagree - a first draft wrote one anyway, telling a reader to fill the
tuning bands before topping up the held-out set, which is verbatim the failure
the older rule twenty lines further down exists to stop.

The largest single addition is the one nobody asked for, and it came out of
reading the whole file rather than the change. Accepting this offer can LOWER
the score's ceiling: nine real rows carry the small-comparison-set ceiling, and
the same dataset topped to twenty-eight is mostly model-written and carries the
generated one, four points below it. Measured, both ends, through the scorer. An
offer that reads as help and quietly costs four points is worse than no offer,
so the sentence a customer hears now carries the trade, the flow says it must
before they answer, and the dataset reference owns the arithmetic. Three
documents touch it because it is three different things - what to say, when to
say it, and why it is true - not one rule written three times.

75_702 and 332_050, measured with `assistant_facing_documents()` after that
correction and after two cuts. One draft carried the urgency distinction in the
flow as well as the reference, a rule with two homes and about four hundred
resident bytes; another argued in both homes why the total has to appear in the
sentence, the same fault in a justification. Both copies are gone. These are the
ceilings in force at the end of the chain, above what was measured against them.

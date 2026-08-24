# 0008 - waiting for a slow evaluator instead of calling it failed

follows: 0007
follows-resident-measured: 62_939
follows-total-measured: 236_903
resident-ceiling: 63_750
resident-measured: 63_525
total-ceiling: 244_500
total-measured: 243_843

#151 is the largest single addition in this ledger so far, and the size is the
substance rather than an overrun. An evaluator that takes a while is the normal
shape of an LLM judge, and calling it broken at a fixed deadline produced a
verdict about the customer's code that was really a verdict about our patience.
Replacing that needs a whole contract written down: what the probe waits for,
what it reports when the wait ends, how a partial result is distinguished from
no result, and what the assistant is allowed to conclude from either. None of
that existed in any form, so none of it displaces prose.

SKILL.md takes the smallest share it can - the ordering decision and the
pointer - and `evaluation-and-dataset.md` carries the depth, which is why
resident moves by six hundred bytes against seven thousand in the total.

243_843 measured on this tree. Seven branches now sit under this figure that
#151 was never able to see.

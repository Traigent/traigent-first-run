# 0051 - a value appears in the line cited for it

follows: 0050
follows-total-measured: 369_337
total-ceiling: 369_650
total-measured: 369_593

`_value_is_evidenced` in `readiness.py` grants a categorical parameter credit
only when each option it declares turns up verbatim, on a word boundary, inside
that parameter's own `evidence` string. Nothing an assistant reads said so. The
scorer enforced a spelling rule and the guidance described the requirement as
"options that exist", which is what an author checks against when they write a
fresh evidence line and find their paraphrase silently worth zero.

The worked JSON in `references/component-creation.md` was written by an author
in exactly that position. It cited "MODELS lists the three ids" and named the
three ids nowhere else, so the single block a reader is handed as the shape to
copy earned nothing for `model` and nothing for `style`; its numeric parameter
survived only because a `low`/`high` pair is measured rather than spelled. The
same commit as this entry repairs those two strings. Repairing an instance is
not stating a rule, and the paragraph immediately below that JSON already
settles what to do about the difference, for a neighbouring rule, in a sentence
this entry is spending bytes to obey: it is not a judgement call, so it does
not stay unstated.

Most of the raise - 202 bytes - is the sentence granting credit, which now
describes the evidence rather than the world. Naming the cited line was not
enough on its own: the scorer never opens the agent, so a paraphrase that
points at a line whose real contents do spell the options out satisfies such a
sentence on its face and still earns zero. What the sentence names now is the
`evidence` string, what it requires is the options quoted inside it verbatim,
and it carries the whole-token case a reader would otherwise meet as a refusal
on a card - `gpt-4` declared against `["gpt-4o-mini", "gpt-4o"]` earns nothing,
because a value nested inside a longer one is not that value.

The remaining 54 are the two evidence lines, and ten of those are quotation
marks. `AGENT_KNOBS_EXAMPLE` inside the scorer shows `MODELS = ["fast",
"slow"]`; the first draft of the repair rendered the identical construct in
single quotes to dodge JSON escaping. Two canonical examples rendering one
construct two ways is precisely the divergence the checks around this ledger
exist to refuse, and ten bytes is not a price worth taking for it. Both
examples now escape.

Nothing resident moves. `GUIDE.md` and `SKILL.md` are unchanged byte for byte
from the figure 0050 measured, so no resident ceiling is bought and none is
declared.

Where the measured total comes from:

    0050 total measured                                    369_337
    the two evidence lines, paraphrase to literal               +54
      (+44 for the values themselves, +10 to escape their
       quotes instead of dodging the escaping)
    the credit rule, restated against the `evidence` string
      the scorer reads rather than the agent it cites            +202
    total measured here                                    369_593

Every byte of that lands in one commit, sitting directly on the tree 0050
measured. No part of it arrived ahead of this entry, so the figure is bought
once and there is no earlier state anyone has to reconstruct to check the
arithmetic.

The ceiling sits 57 bytes above the measurement, which is less than one wrapped
line of this file: enough that swapping a word in the sentence this entry buys
does not require a successor, and far too little to hide a rule inside. The
raise it makes over 0050 is 256 bytes, which sits among the three raises before
it along the chain - 345, 249 and 276.

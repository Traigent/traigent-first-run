# 0027 - the agent pillar reads the agent

follows: 0026
resident-ceiling: 76_600
resident-measured: 76_351
total-ceiling: 338_800
total-measured: 338_481

The pillar printed `AGENT` over a single number that answered one question:
how many settings-combinations a search could try. Customers do not read a
heading that way. Two people arriving with the same declared config space and
very different agents - one with worked examples in its prompt, a parser on the
reply and a bounded retry loop, the other with a bare instruction, free text
coming back and a loop that stops when the model decides - received identical
verdicts under a word that names their work rather than our search.

Widening it costs prose in three places, and each one buys something a number
alone could not. The gate now asks for both halves of one read of the agent's
source in a single pass, and says that withholding the second half is not free -
without that sentence the checks arrive absent on most runs and the widening
does nothing except lower scores. The creation reference gains the shape of the
four answers and, more importantly, what each is asking and what it refuses to
ask: none of them is a judgment about how good the agent is, because an opinion
may lower a score and never raise one, and this input can raise one. And the
glossary gains four lines, because the card now prints four findings a customer
has never seen and the assistant needs a prepared sentence for each.

The largest single addition is the smallest in bytes and the one worth naming.
Two of the six criteria the pillar was asked to cover cannot be established by
reading an agent's source at the gate where this read happens - whether the
dataset and the evaluation method are wired into it, which is an integration
this run builds afterwards and verifies against the installed SDK. Scoring them
would grade our own later work; omitting them silently would let four answered
checks imply that six were looked at. So the card carries a sentence saying what
the pillar does not cover, and the reference and the glossary each say it once
more where a reader would otherwise infer coverage. Three statements of one
absence, in three registers - the card a customer reads, the reference an
assistant follows, and the glossary it answers questions from.

76_351 and 338_481, taken with `assistant_facing_documents()` on the aligned tree
after reading the whole of every document the change touches rather than the
diff. That read is where the last of the total came from and it found the two
sentences that mattered: the safety reference said the source read is not passed
at the close at all, which stopped being true when the read acquired a half that
makes no claim about the search space, and the glossary told a customer the
score's third part is their agent's knobs. Neither was visible in the diff, and
both would have been a document contradicting the scorer it describes.

The resident figure carries the gate paragraph only. The four checks, their
refusals and their example live in the creation reference, which the run loads
for one stage and drops; the two-halves rule at the close lives in the safety
reference beside the document it is about; and the definitions live in the
glossary, which is loaded on demand when somebody asks what a card line means.

# 0053 - every name the client accepts

follows: 0053
total-ceiling: 419_406
total-measured: 419_347

A customer holding a working Google key was admitted by the opening gate and
then refused, seconds before the first paid call, by the wrapper that spends
the money. The gate accepted `GEMINI_API_KEY` or `GOOGLE_API_KEY`; the wrapper
listed only the first. `GOOGLE_API_KEY` is what AI Studio prints on its own key
page and what litellm resolves ahead of the other, so the halted run would have
been answered had nothing checked it. Nobody can debug being told they are
ready, holding a key that works, and being stopped by a list.

The bytes buy the shape that keeps a list from doing that again, not a longer
list. Each route now names every credential a call can arrive on and one of
them suffices, which is how the gate had always counted them, so a second name
is a row rather than a rewritten condition. Two routes had drifted further than
Google had: the gate reports HuggingFace and Bedrock as available, the wrapper
had no entry for either, and an unmapped route raises on arrival - the same
halt reached through a different sentence, which is why coverage and names are
now compared together rather than the pair that was reported.

The first version of this entry claimed that shape fixed the class, and it did
not. Both inventories were compared against each other, and two lists can only
disagree about a name one of them is missing. A name absent from both is
invisible to that comparison, and four were: `ANTHROPIC_AUTH_TOKEN`,
`CO_API_KEY`, `OR_API_KEY`, and `PALM_API_KEY`. Every one of them is a name the
installed client will authenticate a call on, so every one of them was this
same defect, sitting behind a check written to catch it.

What settles it is that neither copy is the authority. litellm decides whether
the call succeeds, it is installed where the suite runs, and its resolution is
ordinary readable code - so the suite now reads the accepted names out of the
branch `litellm.completion` dispatches each route to, plus the helpers that
branch delegates to, and fails on any difference from either inventory. No
vendor's names are written down in the test. A route added without a cited
resolution site fails, and a name the client starts accepting arrives as a
failure that says the name.

`PALM_API_KEY` is why that distinction was worth the bytes rather than a
sourced table of the other three. Nothing on Google's key page mentions it, no
review of a hand-written list would have produced it, and the Gemini branch
honours it to this day for keys minted before the rename. Reading found it;
transcribing would not have.

Bedrock earns the longest comment because it is the one route where absence
proves nothing. It signs through the AWS chain, so a shared profile, an SSO
session, or an instance role carries a fully credentialed run with no `AWS_*`
variable present anywhere. A refusal keyed to those variables would be this
defect rebuilt deliberately, so the route is declared with no names and left to
fail, if it fails at all, on its own first call - and the comment says so,
because an empty tuple with no reason beside it reads like an oversight and
invites the next author to fill it in. The client agrees: that branch reads
nothing from the environment, and the suite now holds it to that.

Reading the branch was still not reading the client. One route is resolved
BEFORE dispatch: `get_llm_provider` hands mistral to a config object that reads
`MISTRAL_AZURE_API_KEY`, returns it as `dynamic_api_key`, and `completion`
assigns that over `api_key` before the branch executes - so the branch's own
`or get_secret("MISTRAL_API_KEY")` is dead code for anybody whose key is in the
Azure AI name, and the reader following that branch reported the one name that
route does not use. Measured on one machine with no network, with only the
Azure name set: the client resolves the key and would have placed the call; the
wrapper refused. Green suite, working key, stopped run - the defect this ledger
entry is about, surviving three patches, because unreachable and absent are the same
answer to a reader and only one of them means agreement.

So the fourth patch buys a derived guard rather than another row. Anything a
pre-dispatch branch hands a route to is a credential resolver by construction -
that module returns the provider, the base URL and the dynamic key and nothing
else - so the site is named from the call instead of remembered, and a route
that acquires one without citing it fails by name and prints the citation to
paste. Following the same calls out of the dispatch file was measured and
rejected: two routes reach a config getter there that resolves no credential,
and a guard that demanded those be cited would have taught its readers to cite
anything to make it quiet. The guard is worth 0 guidance bytes; only the name
itself costs, at 24.

The gate had the same defect pointing the other way. With nothing set it told
every reader not to begin paid work until their route's credential was present,
which is a stop instructed at exactly the customer whose route needs no
variable - the one the wrapper was deliberately built not to refuse. The report
survives, because finding no names is worth saying; the instruction now says
what it applies to. Neither correction is guidance: that script is not a
document a run loads.

Names were agreed and values were not. Measured with a `.env` line reading
`GEMINI_API_KEY=# paste your key here`: the gate refuses the placeholder, the
wrapper's `.strip()` read it as a credential, and the wrapper loads that same
file - one set of bytes, two programs, opposite answers, and the more permissive
one is the program that spends money. No vendor issues a key beginning `#` and
that line is what a half-edited example leaves behind, so the wrapper adopts the
gate's reading and the suite compares the two predicates value by value.

Which spelling goes into the environment variable was never written down
anywhere, and one route made that expensive. The accepted keys are the eight
lowercase route names; seven of them are what the client dispatches on and
`google` was not, so an assistant deriving the route from the model string or
from `custom_llm_provider` - the only two places it can be read - produced
`gemini` and was refused as an unmapped route before anything was spent. The key
is now the literal the client dispatches on, and the suite holds every route to
that, which is why this costs no bytes: the answer is derivable rather than
documented.

The handoff that tells a customer which line to fill in named a value prefix
after an `..._API_KEY=` line. Two accepted names end in neither, their values
begin with neither, and one route has no line in that file at all - so the
instruction sent a reader looking for something that was never going to be
there. It names the variable now, and both halves of that check are derived
from the inventory rather than from the sentence.

Two names in a sentence built for one is the last of it. `none of
OPENAI_API_KEY is set` was what a single-name route printed, at precisely the
moment its reader is stuck and reading closely, so the clause is now chosen by
how many names there are.

The figures below:

    0053 total measured                                    417_409
    sdk-execution.md                                        +1_835
      the inventory comment - two copies, one authority,
        and the names no vendor page prints                     697
      the Bedrock entry's reason for holding no names           392
      the any-of check, and one name reading as one name        364
      the placeholder a bare `.strip()` called a credential      183
      the eight routes as tuples                                199
    GUIDE.md                                                   +14
      the credentials this run keeps in a variable               14
    run-safety.md                                              +89
      the line named by its variable, and the route that
        has no line to name                                      89
    total measured here                                    419_347

Resident rises by the 14 bytes in `GUIDE.md` and by nothing else: `SKILL.md`
already sends the reader to this reference for the paid wrapper, and which
environment variable a vendor issues its key under is not a rule the flow needs
to carry from the first turn. Everything that reads the client, compares the two
predicates, derives the route literal and checks the handoff lives in the suite,
which no run loads. The ceiling above leaves 99 bytes: the 59 that 0052 left,
plus 40 for the branch stacked directly on this one - measured over the same
document set at that branch's head against this one, not taken from its
description of itself - so both fit without a second raise arriving as a red
trunk.

The figures above have now been re-measured twice, for two unrelated reasons.
The first was that 0052 moved underneath them. This branch was cut when 0052
measured 389_491 and read that number honestly; 0052 then answered five more
rounds of review and finished at 413_623. What this branch carried had not
changed at all - the same 1_553 bytes, item for item - but a total is a
statement about a package, and the package it described no longer existed. The
second reason is everything above: review added 385 bytes to what this branch
carries, so the table is re-summed line by line rather than given a correction
at the bottom.

Both branches were green the whole time, and merging them would have put a
ceiling in force that was measured before 24_132 of the bytes it bounds were
written. The failure text one file over says exactly this - that a total after a
merge is arithmetic neither side could do alone - and nothing computes it before
the merge, so it arrives as a red trunk rather than as an instruction. An entry
naming only the index it follows cannot notice that the state behind that index
changed; naming the figure would.

Re-measured once more when this branch was rebuilt. The entry it follows is now
0053 rather than 0052: the branch below it grew a second time, and this branch's
history stopped being an ancestor of the trunk when its predecessor merged as a
squash, so it was rebuilt from the trunk rather than merged into it.

What this branch adds did not change - 1_835 bytes in the execution reference,
89 in run safety and 14 in the guide, item for item, the same edits - but the
package they are added to did. 417_409 + 1_938 = 419_347, and the margin stays
at the 59 bytes its predecessor leaves.

That is three re-measurements of one entry across one branch's life, each
because a figure underneath it moved. An entry that named the figure it was
measured on top of, rather than only the index of the entry that held it, would
have gone red on this branch the moment that figure changed, instead of staying
green until the merge.

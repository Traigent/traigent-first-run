# 0054 - every name the client accepts

follows: 0053
total-ceiling: 420_603
total-measured: 420_544

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

So the fourth patch buys a derived guard rather than another row. What a
pre-dispatch branch hands a route to returns that route's provider, its base
URL and its dynamic key together, so the site is named from the call instead of
remembered, and a route that acquires one without citing it fails by name and
prints the citation to paste. Not every such site resolves a credential, which
this entry first claimed as construction: swept over every literal that chain
compares against, one of 35 on the installed release and one of 36 on the
pinned one is handed a helper that builds an endpoint out of the model string
and reads nothing at all, with its key still in the branch. The guard is right
either way - a site that reads nothing costs a citation, a site that reads a
key would cost a customer's run - and no route here reaches one. Following the
same calls out of the dispatch file was measured and rejected: two routes reach
a config getter there that resolves no credential, and a guard that demanded
those be cited would have taught its readers to cite anything to make it quiet.
The guard is worth 0 guidance bytes; only the name itself costs, at 24.

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
is now a literal the client dispatches on, and the suite holds every route
to that for the models the client files under it. That is the bound, and it
is not the whole client: a refiner keyed on a model the route inventory does
not list yields a literal this sweep cannot reach. One exists, it is filed,
and the two model strings that reach it are retired.

Holding it was the part that was not done. The check written for that read
`branch` - a literal in the test file - and compared it against the published
keys, a literal in the reference, both typed by one author in one commit, which
between them can disagree about a misspelling and about nothing else. It was
green while `cohere/command-r` resolved to `cohere_chat`: seven routes reach
their branch under one spelling and cohere reaches its under two, because the
client sends the `command-r` family down a branch it shares with the older
completion models, written `== "cohere_chat" or == "cohere"`, reading the same
two names for both. Measured with a working key in `COHERE_API_KEY` and that
route inspected: the wrapper refused, seconds before the first paid call, with
a sentence that names no name - the halt this entry is about, on the one route
the check never asked the client about.

So the literals come out of the client too. Every model it files under a route
goes back through `get_llm_provider`, which is the function that decides
`custom_llm_provider`, and every answer has to be a route the wrapper takes -
no model name written down here, and no list agreeing with the list beside it.
The second spelling is accepted as an alias, which the suite allows only while
the client reads the same names on both, and the wrapper is run under it rather
than read: remove the alias and the executed check refuses `cohere_chat` again,
naming it. That is 403 bytes and it is why this section no longer claims to be
free.

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

    0053 total measured                                    418_203
    sdk-execution.md                                        +2_238
      the inventory comment - two copies, one authority,
        and the names no vendor page prints                     697
      the Bedrock entry's reason for holding no names           392
      the any-of check, and one name reading as one name        364
      the placeholder a bare `.strip()` called a credential      183
      the eight routes as tuples                                199
      the second literal one route is dispatched under          403
    GUIDE.md                                                   +14
      the credentials this run keeps in a variable               14
    run-safety.md                                              +89
      the line named by its variable, and the route that
        has no line to name                                      89
    total measured here                                    420_544

Resident rises by the 14 bytes in `GUIDE.md` and by nothing else: `SKILL.md`
already sends the reader to this reference for the paid wrapper, and which
environment variable a vendor issues its key under is not a rule the flow needs
to carry from the first turn. Everything that reads the client, compares the two
predicates, derives the route literal and checks the handoff lives in the suite,
which no run loads. The ceiling above leaves 59 bytes, the margin its
predecessor leaves. The branch stacked directly on this one adds 40 - measured
over the same document set at that branch's head against this one, not taken
from its description of itself - so it fits inside that margin with 19 to
spare, and neither raise arrives as a red trunk.

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

What this branch added did not change when it was rebuilt - 1_835 bytes in the
execution reference, 89 in run safety and 14 in the guide, item for item, the
same edits - but the package they are added to did, so 417_409 + 1_938 =
419_347 was the figure that rebuild carried. Review then found the route above
and the alias that answers it, which is the one increment since that is a
change of content rather than of base: 2_341 in place of 1_938, and
418_203 + 2_341 = 420_544, with the margin still the 59 bytes its predecessor
leaves.

That is three re-measurements of one entry across one branch's life because a
figure underneath it moved, and a fourth because what it carries grew - only
the last of which any check could have asked for. An entry that named the
figure it was measured on top of, rather than only the index of the entry that
held it, would have gone red on this branch the moment that figure changed,
instead of staying green until the merge.
Re-measured a fourth time. The entry below this one answered another round of
review, so the figure this branch is added to moved again: 418_203 now, and
418_203 + 2_341 = 420_544. The 2_341 has not changed at any point - 2_238 in
the execution reference, 89 in run safety, 14 in the guide - because what this
branch adds has not changed. Only the floor under it has.

Four re-measurements of one entry, each because a number underneath it moved
and nothing said so until the two were put together. The entry names the index
of the state it was measured on; naming the figure as well is what would have
turned each of those into a red branch instead of a quiet one.

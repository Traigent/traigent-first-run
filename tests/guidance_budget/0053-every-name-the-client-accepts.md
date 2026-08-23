# 0053 - every name the client accepts

follows: 0052
total-ceiling: 391_104
total-measured: 391_044

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

Two names in a sentence built for one is the last of it. `none of
OPENAI_API_KEY is set` was what a single-name route printed, at precisely the
moment its reader is stuck and reading closely, so the clause is now chosen by
how many names there are.

The five figures below:

    0052 total measured                                    389_491
    sdk-execution.md                                        +1_553
      the inventory comment - two copies, one authority,
        and the names no vendor page prints                     622
      the Bedrock entry's reason for holding no names           392
      the any-of check, and one name reading as one name        364
      the eight routes as tuples                                175
    total measured here                                    391_044

Resident is untouched: `SKILL.md` already sends the reader to this reference
for the paid wrapper, and which environment variable a vendor issues its key
under is not a rule the flow needs to carry from the first turn. The check that
reads litellm costs no guidance bytes at all - it lives in the suite, which no
run loads. The ceiling above leaves 60 bytes, the margin 0052 left: room to
reword a comment, not to add a route.

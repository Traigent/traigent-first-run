# 0053 - both names Google issues

follows: 0052
total-ceiling: 383_180
total-measured: 383_118

A customer holding a working Google key was admitted by the opening gate and
then refused, seconds before the first paid call, by the wrapper that spends
the money. The gate accepted `GEMINI_API_KEY` or `GOOGLE_API_KEY`; the wrapper
listed only the first. `GOOGLE_API_KEY` is what AI Studio prints on its own key
page and what litellm resolves ahead of the other, so the halted run would have
been answered had nothing checked it. Nobody can debug being told they are
ready, holding a key that works, and being stopped by a list.

The bytes buy the shape that keeps a list from doing that again, not a longer
list. Each route now names every credential its vendor issues and one of them
suffices, which is how the gate had always counted them, so a vendor's second
name is a row rather than a rewritten condition. Two routes had drifted further
than Google had: the gate reports HuggingFace and Bedrock as available, the
wrapper had no entry for either, and an unmapped route raises on arrival - the
same halt reached through a different sentence, which is why coverage and names
are now compared together rather than the pair that was reported.

HuggingFace pays for its own line twice over. The client reads `HF_TOKEN`
first and `HUGGINGFACE_API_KEY` second; the gate knew only the first, so adding
the route to the wrapper under one name would have minted a fresh instance of
the very refusal being removed. Both names are now in both places, verified
against the resolution order in the installed client rather than a vendor page.

Bedrock earns the longest comment because it is the one route where absence
proves nothing. It signs through the AWS chain, so a shared profile, an SSO
session, or an instance role carries a fully credentialed run with no `AWS_*`
variable present anywhere. A refusal keyed to those variables would be this
defect rebuilt deliberately, so the route is declared with no names and left to
fail, if it fails at all, on its own first call - and the comment says so,
because an empty tuple with no reason beside it reads like an oversight and
invites the next author to fill it in.

Nothing here could be shared instead of restated, and the alternative was
weighed. The gate is a script this package ships; the wrapper is code generated
into a project that never has that script on its path, so there is no import
that would let one read the other and no moment at which either could notice
the disagreement. What is shared is the comparison: the package suite now
parses both inventories and fails on any route or name present in one and
absent from the other, which is the check that would have caught this the day
it landed.

The four figures below:

    0052 total measured                                    382_008
    sdk-execution.md                                        +1_110
      the inventory comment - one list, two programs,
        and the two resolution orders that decide it           524
      the Bedrock entry's reason for holding no names          392
      the seven routes as tuples, plus Bedrock                 110
      the check reading any-of instead of the one name           84
    total measured here                                    383_118

Resident is untouched: `SKILL.md` already sends the reader to this reference
for the paid wrapper, and which environment variable a vendor issues its key
under is not a rule the flow needs to carry from the first turn. The ceiling
above leaves 62 bytes, matching the margin 0051 and 0052 each left - room to
reword a comment, not to add a route.

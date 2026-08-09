# 0022 - read the agent instead of shrugging at it

follows: 0021
resident-ceiling: 74_300
resident-measured: 74_154
total-ceiling: 325_300
total-measured: 325_095

#201 turns a blank pillar into a measured one, and measuring costs instructions
where shrugging cost none. Until now the opening gate said only which file to
withhold; every customer therefore saw 45/PARTIAL as their ceiling, whatever
they arrived with. Telling the assistant to open the agent and write down what
already varies - with the line of the customer's own code behind each entry -
is new work, and work nobody has been asked to do before needs saying once,
plainly, where the gate is.

Most of it went to the reference. SKILL.md gains seven lines: what to read,
where to put it, and the one prohibition that decides whether the resulting
card is honest - never write a range or an option you did not see, because an
omitted parameter costs a few points while an invented one puts a number on the
card that the customer's project cannot support. The document shape, the worked
example, the qualification rules and what the reading does NOT attest live in
`references/component-creation.md`, which loads for one stage and leaves.

What is NOT bought here is a rewrite of the ceiling paragraphs, and an earlier
revision of this branch spent bytes on exactly that. It deleted the 45 for a
project whose search space is unestablished, so three passages in `glossary.md`,
`run-safety.md` and `README.md` had to describe its absence. Measuring the agent
turned out not to need that: what stops a customer being pinned at 45 is that
their agent now gets read, not that the number went away. Those passages say
what they said, with the reading added to the list of things that can establish
a space, and the paragraph in `run-safety.md` about a failed search keeps its
original shape rather than acquiring a second one.

74_154 and 325_095, re-measured with `assistant_facing_documents()` on the
integration merge that lands #202, #203, #211 and this branch on trunk 06896c03.
The branch declared 66_198 and 305_490 against its own base, and neither figure
survives: this branch and the three it merges beside all edit `SKILL.md`, and the
resident half alone is 7_956 bytes above what any of them measured alone. Which
is the whole argument the ledger makes - four correct measurements, none of them
describing the tree that now holds all four.

The number moves from 0016 to 0022 because trunk and two of those branches
already hold 0016 and 0017, and it follows 0021 because this read is the last
thing to land. The entry after this one arrives in the same merge and reports
the same two figures, for the reason it gives there: one merge is one package.

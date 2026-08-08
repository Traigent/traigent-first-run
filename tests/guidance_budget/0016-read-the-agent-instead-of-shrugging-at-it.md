# 0016 - read the agent instead of shrugging at it

follows: 0015
resident-ceiling: 66_500
resident-measured: 66_198
total-ceiling: 305_500
total-measured: 305_490

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

Both figures re-measured against this tree after the last edit, not carried
from the revision above: it declared 305_349, and pinning the ceiling paragraphs
back to what they describe moved the total to 305_490. That is 10 bytes of
headroom under a ceiling this entry does not raise again - the next branch to
edit a reference here should expect to prune or to declare its own raise.

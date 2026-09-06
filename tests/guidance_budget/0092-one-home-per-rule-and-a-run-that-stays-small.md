# 0092 - one home per rule and a run that stays small

follows: 0091
follows-resident-measured: 107_369
follows-total-measured: 504_689
follows-document-measured: 138_879
resident-ceiling: 106_500
resident-measured: 106_221
total-ceiling: 498_500
total-measured: 497_699
document-ceiling: 137_750
document-measured: 136_159

A whole-repository review by the guide's owner asked four questions of the text: what an
assistant re-checks after it repairs a component, whether the customer is told before the SDK is
installed, whether the assistant understands that the first run is meant to stay small, and
whether every question reaches the customer at the end of a message. Answering them removed more
than it added. Rules that had been written two, three or four times - the post-repair sequence,
the write-scope key rule, the execution-evaluator stop, the timeout rule, the routes at the
connected checkpoint - now have one home each with pointers elsewhere; the glossary keeps its
definitions and gives up its restated numbers; GUIDE.md points at SKILL.md instead of repeating
it; the checkpoint framing that preceded the connected routes lost its history and kept its
rules. The additions are short: an operating-contract paragraph that names the run's purpose and
forbids re-running a paid phase, adding rows, widening the space or raising the trial cap without
a newly scoped approval; a single post-repair paragraph ending in the one line the assistant
prints; a section-to-stage map; an adaptation list and tags over the execution fence; and a
notice, not a question, before the pinned install. All three budgets now weigh less than the
figures they follow, so each ceiling comes down with its measurement - a prune, not a raise - and
each new ceiling is placed to leave about the headroom the previous one left.

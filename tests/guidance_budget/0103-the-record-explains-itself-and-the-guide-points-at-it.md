# 0103 - the record explains itself and the guide points at it

follows: 0102
follows-resident-measured: 106_386
follows-total-measured: 498_296
follows-document-measured: 136_303
resident-ceiling: 106_500
resident-measured: 106_386
total-ceiling: 498_272
total-measured: 498_268
document-ceiling: 137_550
document-measured: 136_303

This lowers the TOTAL ceiling by 28 bytes, which is a prune and not a raise, and it is the only
ceiling that moves. Connected-run readiness gains a short instruction while the same reference loses
two restatements, so the package is 28 bytes smaller than 0102 weighed, and a shrink cannot pass
under a number taken before it. The ceiling drops by exactly what was freed rather than by less,
which keeps the 3 usable bytes 0102 left instead of quietly turning a deletion into budget nobody
decided to grant.

What earns the shrink is giving up on saying a thing twice. An inherited shell variable beats the
credential a customer pasted into the handoff file, and a refusal from the portal is the first place
anybody notices. The static check that measures this already names which variables disagreed, states
the precedence, connects it to that refusal in the customer's own words, prints a remedy for each
name and a recipe for comparing digests. Five attempts to restate that in prose were each right when
written and wrong when read - four about which name shadowed, and one about which record names the
file that was read. A sentence about what a check reports is maintained apart from the check, and
nothing but a human was comparing them. So the guidance now does only what the check cannot do for
itself: have it produced again at the refusal, against the file the handoff wrote, and read - naming
only records that a run which succeeded actually emits. Paid for by two deletions rather than a
higher number: the interpreter bullet no longer repeats the stop-and-preserve remedy Recovery states
in full, and the ordering clause telling an assistant to run free component checks first goes back
to being the flow document's alone, where it is written twice over already.

THE NUMBER AND THE PREDECESSOR WERE BOTH TAKEN AGAIN, and this is the third trunk this entry has
been measured on. It was written as 0100 following 0099 at 498_278; 0102 then landed, spending 18 of
the 21 bytes 0099 left and moving RESIDENT to 106_386, so both the number and every `follows-*`
figure went stale without a byte of this change moving. The figures above were re-measured on
`e77d2e3c` with the suite's own `assistant_facing_documents()` and `guidance_budget_measured()` -
498_296 there, 498_268 here - so the 28 bytes this frees are the same 28 on top of 0102's addition,
which they can be because 0102 edits a SKILL.md sentence about `recommended_action` and this edits
`references/run-safety.md` and the two do not touch. The ceiling follows the same arithmetic it did
before: 0102's 498_300 less the 28 handed back is 498_272, and 498_272 - 498_268 - 1 is the same 3
usable bytes 0102 left. A prune that lowered the ceiling by less than it freed would be a raise
wearing a prune's clothes; a prune that carried a figure from `78753f88` would be describing a
package that no longer exists.

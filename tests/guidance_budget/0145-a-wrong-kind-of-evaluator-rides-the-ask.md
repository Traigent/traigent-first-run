# 0145 - a wrong kind of evaluator rides the ask

follows: 0144
follows-total-measured: 574_545
follows-document-measured: 177_471
total-ceiling: 574_767
total-measured: 574_522
document-ceiling: 177_639
document-measured: 177_420

A prune: TOTAL falls by twenty-three bytes and the largest document, run-safety.md, by fifty-one.
`readiness.py` now raises `evaluator-task-mismatch` when the declared evaluation method is the
wrong kind of check for the declared output: an ask that caps nothing, riding the one ask, with its
own remedy `review-evaluator-fit`. Before it, a text-to-SQL project graded by a normalized text
comparison printed "the wrong kind of check" in its evaluation pillar and `Action: Continue` above
it, while `evaluation-and-dataset.md` lists that finding as material and routes it to repair.

The closing-card paragraph in run-safety.md carried an aside naming the unread answer key as "the
one" ask of that kind this run raises. It was already stale before this change, because unsound
expected outputs were an ask that caps nothing too, and this change adds a third. So the aside now
names none: the clause ends where the class is defined, and a list that goes out of date with every
new member is not kept. That removes fifty-one bytes.

evaluation-and-dataset.md gains twenty-eight. Its findings row for a task-inappropriate evaluator
told the reader to show "the exact rule and one valid answer it rejects", which a model judge has no
rule for and a composite cannot be seen into. It now asks for what the method counts as correct
and, where one exists, an answer it grades wrongly - the same terms the new ask uses. Both files
were read end to end; the repair routes and the routing order ("otherwise an ask that caps
nothing") already describe this ask, and the pre-spend card's rule that such an ask is not carried
there holds for it as well. SKILL.md and GUIDE.md are unchanged; RESIDENT is not declared.

Each ceiling comes down by the bytes its own budget freed, 23 of TOTAL and 51 of the document.
Leaving them in place would bank the freed room as a raise nobody weighed; lowering them keeps the
gaps 0144 recorded, 245 bytes of TOTAL and 219 on the largest document.

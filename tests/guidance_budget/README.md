# The guidance byte budget, and how to raise it

`tests/test_skill_package.py` enforces two ceilings over the assistant-facing
documents: RESIDENT (`GUIDE.md` + `SKILL.md`, in context from the first turn to
the last) and TOTAL (every document a full guided run loads). The ceilings are
not in the test. They are in this directory, one file per raise.

## Raising a ceiling

Add a file. Do not edit an existing one.

```
tests/guidance_budget/0007-say-what-the-wait-is-for.md
```

```markdown
# 0007 - say what the wait is for

follows: 0006
total-ceiling: 234_750
total-measured: 234_318

<why this guidance earns its bytes, what it replaces, and what the
 measured total actually is>
```

Rules the suite enforces:

* The name is `NNNN-slug.md`. `NNNN` orders the entries; the slug is for the
  reader. Two entries may not share a number.
* An entry declares `follows:` naming the entry it was measured on top of.
  That entry must exist here and carry a lower number, so `follows:` records
  the ledger state you actually had in front of you. Exactly one entry - the
  root, `0001` - declares none.
* **No two entries may follow the same entry.** See below.
* An entry declares `resident-ceiling:`, `total-ceiling:`, or both, and beside
  each one the `-measured:` figure it was set against. The measurement must be
  under the ceiling it buys, and it may not fall below the last measurement of
  the same budget earlier in the chain unless the entry is lowering that
  ceiling too (a prune, which is a different decision).
* An entry carries a reason of at least 240 characters using at least 24
  distinct words. The shortest reason anyone has written in this ledger is 259
  characters and 30 distinct words, so both floors refuse a label - or a label
  padded to length - rather than a short argument.

One root, and every other entry following a distinct lower-numbered entry,
makes the ledger a single chain. The ceiling in force is the last one declared
along that chain, which is unambiguous only because it is a chain.

## Raising a ceiling at the same time as somebody else

Two branches that both raise a ceiling both write `follows: 0001` - honestly,
because 0001 is the state each of them measured on top of. The files do not
collide, and nothing in git objects, but the merged ledger has two entries
following the same one and the suite fails. Renumbering does not get around it:
an entry may only follow one that exists in its own tree, so a second author
who writes `follows: 0002` when their branch has no `0002` is red before they
ever open a pull request.

The failure names the two ways out. Measure the merged package, then either
replace both entries with one measured against it, or re-point the later entry
at the earlier one and re-state that entry's measured figure and ceiling
against the merge.

What this does not do: it detects that two raises were measured on the same
state, not that anybody's figure is right. Nothing re-measures the package for
you. The monotonicity rule catches a re-point whose figure is below the one it
now follows - the un-remeasured case - and nothing more. The ceiling check in
`tests/test_skill_package.py` is what measures the package for real.

## Why one file per raise

The ceilings and their reasons used to be a single 109-line comment block
inside the budget test, appended to by every branch that raised a number. That
made the block a conflict surface every branch had to cross.

Measured on 2026-08-06, against the head of every open pull request in this
repository except this one, with trunk at `56d72a4`:

* **11 of the open branches** change that block relative to their own merge-base
  with trunk - that is the population, and it is every branch that touches the
  ledger at all, not a selection.
* **3 of the 11** are descended from current trunk (#174, #169, #168). The other
  8 branch from older trunks, so an "ordered pair" across the whole set is not
  one number: it mixes merges nobody is going to perform.
* Among those 3, **6 of 6 ordered pairs conflict**, and every one of the 6
  conflicts inside the guidance-budget block. 4 of the 6 also conflict
  somewhere else, so for 2 of the 6 the block is the *only* thing in the way.

Reproduce it with `git merge-tree --write-tree <head-a> <head-b>` over the open
heads; the population is the branches whose copy of
`test_the_guidance_budget_is_not_silently_exceeded` differs from their
merge-base's. Re-measure before quoting these figures - the earlier revision of
this file carried numbers from a 7-branch window that no longer existed a few
days later, which is the same defect the ledger itself is about.

The direction is what is stable, and it is a property of the shape rather than
of any window: a block that every raise appends to is a block every raise
collides on, and the collisions are between paragraphs that do not disagree.
Per-raise files remove the collision by construction - two branches each adding
a new file conflict on nothing - which is exactly why the checks below have to
do the work the conflict was wrongly credited with.

## What replaces the merge conflict

Nothing is lost by the conflict going away, because the conflict was never
doing the work. Five times in `0001-inherited-ledger.md` the ledger records the
same trap: two branches each raise the ceiling correctly for their own
increment, and the merged package exceeds both. Git cannot see that - it is
arithmetic, not text - so the textual conflict was never what caught it.

`follows:` is what replaces it, and it had to be, because the number alone
would not have. A first attempt at this ledger relied on both branches taking
the next free number and colliding on it. The polite second author does the
opposite: they see `0002` in the open pull request and take `0003`, the numbers
differ, nothing collides, and the higher number's ceiling silently governs a
package neither branch measured. `follows:` is the field that cannot be
politely worked around, because it names a file that has to exist on the branch
that writes it.

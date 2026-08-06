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

total-ceiling: 234_750

<why this guidance earns its bytes, what it replaces, and what the
 measured total actually is>
```

Rules the suite enforces:

* The name is `NNNN-slug.md`. `NNNN` orders the entries; the slug is for the
  reader.
* An entry declares `resident-ceiling:`, `total-ceiling:`, or both. The ceiling
  in force is the one from the highest-numbered entry that declares it, so an
  entry that raises only TOTAL leaves RESIDENT where the last entry that spoke
  about it put it.
* An entry carries a reason of at least 240 characters. The shortest reason
  anyone has written in this ledger is 259, so this floor refuses a label, not
  a short argument.
* Two entries may not share a number.

## Why one file per raise

The ceilings and their reasons used to be a single 109-line comment block
inside the budget test, appended to by every branch that raised a number. That
made the block the most-conflicted region in the repository: measured across
the seven open pull requests that touch a ceiling, **42 of 42 ordered pairs
conflicted there**, 66 hunks in total, and every one of those conflicts was a
merge of two paragraphs that did not actually disagree.

Moving only the numbers out was measured too, and it does almost nothing: the
paragraphs still land at the same anchor, so 42 of 42 pairs still conflict.
It is the prose that collides. With prose and number both in a per-raise file,
2 of 42 pairs conflict, and neither of the two is about the budget.

## What replaces the merge conflict

Nothing is lost by the conflict going away, because the conflict was never
doing the work. Five times in `0001-inherited-ledger.md` the ledger records the
same trap: two branches each raise the ceiling correctly for their own
increment, and the merged package exceeds both. Git cannot see that - it is
arithmetic, not text - so the textual conflict was never what caught it.

What catches it is the suite. Two branches that each add an entry merge without
a conflict and then fail two checks: the duplicate-number check, because both
picked the next number, and the ceiling itself, because the merged documents
are larger than either branch measured. Both failures name the fix, which is
the one the ledger has had to state five times: measure the merge, write one
entry for it, do not take a side.

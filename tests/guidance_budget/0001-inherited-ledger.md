# 0001 - the ledger this mechanism inherited

resident-ceiling: 61_500
total-ceiling: 228_750

Everything below is the reasoning that stood in `tests/test_skill_package.py` as
one comment block, carried here verbatim rather than rewritten. It records nine
raises across five merges, and it is kept whole because each entry cites the one
before it - the 371-byte headroom rule, the "measure the merge, do not take a
side" rule, and the move-detail-out-of-SKILL.md policy are all stated once, in
here, and every later raise leans on them.

It is one entry rather than nine because splitting settled prose into files
after the fact would be a rewrite of other people's stated reasons, and the
conflict this file exists to remove is between *new* entries, not old ones.
The next raise adds `0002-*.md`; this file is not appended to again.

## RESIDENT

Raised from 60_000 to 60_500 by #123's follow-up, which reframes the
enhanced run's trial count for the reader who sees it at approval
time: the card now states a ceiling against the space's own
combination count instead of a range. The exact copy went to
run-safety.md, which owns the approval disclosure, so what landed
here is the mandate and the pointer - SKILL.md's own job. That is
new contract surface with no prior statement, not stage detail that
belongs in a reference. Half a kilobyte, because that is what the
mandate costs; a rounder number would bank headroom for the next
edit nobody weighed.

The graduation handoff adds three mandates that only SKILL.md can
carry - the closing run-scope statement, its repetition on the
no-lift path, and the evidence-selected skills handoff - because each
is an ordering decision about the close, and the depth behind all
three moved into run-safety.md rather than into SKILL.md. That branch
raised this to 62_000 against a 60 KB base. #131 has since landed and
moved stage detail OUT of SKILL.md, which lowered the base - but not
by enough to absorb the three new mandates: the merged package
measures 61_129, over trunk's 60_500. So this genuinely rises, and
the figure below is the MEASURED merged resident rather than either
branch's - 62_000 would have banked 871 bytes nobody weighed.

61_500 and not the narrower 61_250: the 60_000 ceiling this file
carried before left 23 bytes of headroom, which is a ceiling that
trips on a one-word edit rather than on a decision. 371 bytes is the
smallest headroom that still makes the next raise a choice.

## TOTAL

The #104 migration lowered this from 220 KB after removing duplicated
environment, account, approval, config-lifecycle, and reporting detail
from resident SKILL.md. The new execution-evaluator safety contract is
real reference depth, not a reason to leave the old ceiling behind.
Resident fell from roughly 69 KB to 54 KB and TOTAL from roughly
220 KB to 209 KB even with that new safety material, so both lowered
numbers record the shape change rather than merely making today's
text pass.

The policy, so the next person does not have to invent one:

  SKILL.md carries the ordered flow and the mandates. A reference
  carries the depth behind one stage. When this ceiling is reached,
  stage detail moves OUT of SKILL.md into the reference that owns
  that stage, and SKILL.md keeps the ordering and the decision. It
  does not move by growing a new document, because two of the four
  contradictions in this package's history were between SKILL.md and
  a reference, and every split is another seam for them.

Raising this number is allowed and is a decision: change it here,
with the reason, in the same commit as the guidance that needs it.
PRs #125 and #126 add user-facing explanations for readiness evidence
and exact pre-run cards. Those are new contract surface, not duplicated
stage detail, so raise TOTAL by 5 KB while retaining a narrow ceiling.
#133 adds the present-but-unresolved-evaluator distinction (a new
evidence classification and its create/select vs. inspect/repair/
replace routing) to SKILL.md and evaluation-and-dataset.md - also new
contract surface, not duplicated stage detail - so raise TOTAL by
roughly 1 KB, keeping the ceiling as narrow as the addition allows.

#123's follow-up raises it again, by 1.5 KB. The enhanced run's count
is now spoken to the user as a ceiling against the space it is drawn
from, and run-safety.md carries the copy for that plus the form it
degrades to when the combination count cannot be computed. Two of
those three sentences replace nothing, because the previous framing
said only a number. Against that, the duplicate statement of the
10-row shortfall obligation left run-safety.md, since #123 had
already made sdk-execution.md its one home.

#133 and #123's follow-up landed independently and each raised this
number from 220_000 for its own increment, both arriving at 221_500 -
so the merge produced no textual conflict on the line, only on the
reasons above it. Merged, the package carries BOTH additions and
measures 222_750, which neither branch's figure admits. The ceiling
is therefore set here against the measured combined total: this is
the arithmetic neither branch could do alone, and taking either
side's number would have failed the suite rather than the review.

#131 merges that trunk in and adds the journey structure on top, and
the same arithmetic trap recurs one merge later: trunk said 223_000
and #131 said 222_250, and the merged package measures 223_442 - so
BOTH figures are too low again, for the same reason. The two changes
are additive because they change different things. #137 owns how the
enhanced count is *stated* - the ceiling copy and its degraded form,
which land in run-safety.md. #131 owns the journey *structure* - the
five-stage opening in GUIDE.md, the readiness presentation in
glossary.md, and splitting one combined approval into a baseline
approval and a separate connected-stage approval, which is the bulk
of run-safety.md's share. Against that, #131 moved stage detail out
of SKILL.md, so resident guidance falls to roughly 58 KB even while
TOTAL rises, and the RESIDENT ceiling above is left where it is
rather than raised; the ceiling copy sits in the reference for the
stage that owns it, which is the policy above working rather than
being spent. So the number below is the MEASURED merged total,
223_442, rounded up to the next 250 - not either branch's figure,
and not an estimate. Measure it; do not take a side.

The graduation handoff then adds the run-scope derivation and the
evidence-to-skill map to run-safety.md's post-run section - the
reference that already owns the close - so this is the policy above
working, not a bypass of it. That branch raised TOTAL by 6 KB to
226_000 against a 220 KB base it branched from; trunk has since
reached 223_750 by the two merges recorded above. The number below is
the MEASURED merged total once more - 228_407 rounded up - and it is
the fourth consecutive merge in which neither side's figure was
correct, which is the whole reason this comment keeps growing instead
of the number being guessed. Every branch weighs its own increment
against the base it branched from; only the merge knows the sum.

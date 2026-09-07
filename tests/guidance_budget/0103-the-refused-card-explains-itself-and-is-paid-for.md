# 0103 - the refused card explains itself, and is paid for

follows: 0102
follows-resident-measured: 106_386
follows-total-measured: 498_296
follows-document-measured: 136_303
resident-ceiling: 105_600
resident-measured: 105_460
total-ceiling: 498_295
total-measured: 498_291
document-ceiling: 137_550
document-measured: 136_303

**No ceiling rises. RESIDENT falls 900 bytes to 105_600 and TOTAL falls 5 to 498_295, because this
branch is a net prune on both.** It replaces the two entries this branch carried before a rebase -
one for the reference's scope wording, one for the disclosure below - because the split recorded
commit order rather than two decisions, and one entry is easier to keep honest than two.

What was missing was not a rule but a disclosure. A project whose evaluator reaches a code or SQL
engine has its calibration refused, earns nothing for that check, never measures probe spread, and
carries a 45 ceiling - and no assistant-facing document said any of that would happen, so the first
the customer heard of it was the card. `references/run-safety.md`, which owns that stage, now states
the consequence, including the half that is not free: whether the unmade check is CHARGED depends on
what preflight's walk found, and a run resting on the declaration alone pays, because finding no
engine settles nothing. The same paragraph settles which calibrations the three words above it bind,
naming `SKILL.md` section 5 step 5's dependency-deferred calibration as outside them
(traigent-first-run#397).

**Paid for out of a prune, which was the instruction and is now the arithmetic.** A reader-load
audit found this branch carrying a large share of the corpus's growth, and 0102 leaves three usable
bytes under TOTAL on trunk, so there is nothing to raise into. 929 bytes freed from `GUIDE.md`
against 924 of new prose - 921 into `references/run-safety.md`, 3 into `SKILL.md` - so the corpus is
**5 bytes smaller** than trunk and the resident half of it - the part in the assistant's context
from the first turn to the last - is **926 bytes smaller**:

* `GUIDE.md`, 7_846 -> 6_917 bytes. `CLAUDE.md` says the entry point "states no rule that SKILL.md
  does not", and it was restating the default run's flow, the stop list, the credential rules and
  the portal-experiment rules while announcing three times that it states none of them twice. Each
  restatement is now a pointer at the section that owns it. Every sentence the suite pins to this
  document specifically was kept, verbatim: a settled decision recorded in another change is not
  slack, and the three baseline sentences, the two promise sentences and the install-authorization
  sentence are all still here.
* The disclosure paragraph, 1_580 -> 716 bytes, by moving its reasoning into this entry - which is
  what this ledger is for - and by pointing at the route the card prints instead of restating it.

**"Evaluator check", not a fourth sense of "calibration".** A naming audit found that word
customer-visible on two surfaces in one session meaning unrelated things - this guide's probe
against known-right and known-wrong answers, and the portal's governance attestation - with a third
sense in the SDK's price calibration. Renaming the existing usage is trunk-wide and is not this
change's job, but widening it is free to avoid, so the sentences this change adds to a customer's
card say "the evaluator check" instead: what the run did not do, what it would not read, and what
the customer can do outside this guide. The sub-score is still named `calibration`, the existing
sentences are untouched, and the debt is capped at today's size rather than paid down. It also came
out 19 bytes shorter, which is why the corpus ends up smaller than trunk rather than level with
it - but the phrase was chosen for being the true one.

The resident ceiling comes down by most of what that freed rather than being banked as room. The
audit's finding was that the assistant's reading load is the cost, so a prune that leaves the
ceiling where it was would have given the next branch 900 bytes of licence and fixed nothing.

**Measured on trunk after 0102 landed, which is the whole reason the figures moved.** The header was
taken on this branch rebased onto `e77d2e3c`, using the suite's own `assistant_facing_documents()`
and `guidance_budget_measured()` rather than by hand. Both sums rose by exactly the +18 that 0102's
fourth arm is worth, from 105_442 and 498_273 to 105_460 and 498_291; DOCUMENT did not move at all,
because neither change touches the reference that holds the maximum. The header this branch carried
before was measured on `78753f88`, a trunk that did not yet hold 0102, and a figure taken there
reads as comfortable while describing a package nobody ships - which is the staleness
`follows-*-measured:` was written to refuse, and it did refuse it, on this branch, in CI.

**Re-pointed onto 0102, and only one of the two lowered ceilings survived the re-point unchanged.**
The bindings above are 0102's own recorded figures, read off the file on trunk rather than quoted
from anywhere. RESIDENT is untouched by the merge: 105_460 sits under the 105_600 ceiling and 926
below the 106_386 its predecessor records, so the shrink a lowered ceiling is required to show is
there. TOTAL is the one that had to change, and saying so is cheaper than discovering it later. A
ceiling of 498_290 is below the 498_291 the merged tree measures, so the number this branch carried
cannot govern the package it now ships; it descends 5 instead of 10, to 498_295 - the 5 bytes the
corpus shrank handed back to the ceiling rather than kept as room. That leaves the same three usable
bytes 0102 left behind it, which is the intended outcome: the prune buys the disclosure and buys
nobody any licence, and no ceiling is nudged upward to keep an old figure looking right.

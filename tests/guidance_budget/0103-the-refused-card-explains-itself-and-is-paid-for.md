# 0103 - the refused card explains itself, and is paid for

follows: 0099
follows-resident-measured: 106_368
follows-total-measured: 498_278
follows-document-measured: 136_303
resident-ceiling: 105_600
resident-measured: 105_442
total-ceiling: 498_290
total-measured: 498_273
document-ceiling: 137_550
document-measured: 136_303

**No ceiling rises. RESIDENT falls 900 bytes to 105_600 and TOTAL falls 10 to 498_290, because this
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
audit found this branch carrying a large share of the corpus's growth, and after the siblings ahead
of it there are three usable bytes on trunk, so there is nothing to raise into. 750 bytes of prune
against 745 of prose: the corpus is **5 bytes smaller** than trunk and the resident half of it - the
part in the assistant's context from the first turn to the last - is **926 bytes smaller**:

* `GUIDE.md`, 7_846 -> 6_942 bytes. `CLAUDE.md` says the entry point "states no rule that SKILL.md
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

**Measured on a tree containing this branch's predecessors, as well as on the branch alone.** The
figures in the header are the branch, which is what the newest-entry check weighs. Merging #459,
#454 and #450 into a copy of it - a stack that also carries #443's entry - gives resident
**105_460**, total **498_263**, document **136_303**: ten bytes smaller than this branch alone,
because #443's prune is in there.

Two things follow for whoever merges. This entry is numbered 0103 by assignment and follows 0099
because 0099 is the newest entry present in this tree; when the stack lands it re-points onto 0102
and restates `follows-*-measured` as 0102's figures, per this ledger's own rule that whichever
merges second re-measures the merge. And the stack fits every ceiling in it, including
#443's lowered 498_273, with ten bytes to spare - which it did not before this change was pruned,
and which is the whole reason the disclosure is paid for out of the corpus rather than out of a
raise.

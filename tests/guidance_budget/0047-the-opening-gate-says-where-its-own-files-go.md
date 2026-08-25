# 0047 - the opening gate says where its own files go

follows: 0046
follows-total-measured: 367_952
total-ceiling: 368_550
total-measured: 368_467

Readiness requires files the guide never placed. The agent-source read is
mandatory - without it the agent pillar scores 0 and reports "no settings
document was provided" - and the preflight JSON must exist before readiness can
read it. Neither had a stated home. `GUIDE.md` said, unqualified, to keep run
artifacts in the chosen project; `references/component-creation.md`, a stage-3
reference the opening gate gives no reason to open, said to write outside it.

Five blinded runs resolved that five ways and reported agent pillars of 41/100,
12/100 and 0/100 for identical code. Three of them wrote the same document to
two places at once, which is what a genuine contradiction looks like from the
outside: the assistant found both instructions and satisfied both.

The first attempt at this entry bought bytes for "goes outside the customer's
project". That was a constraint, not a destination, and it lost - `traigent-runs/`
is named throughout the guide and already holds a settings document, so an
assistant weighing a named folder against an unnamed elsewhere put a copy in
both. A rule that requires the reader to invent a location competes with one
that supplies it, and loses.

So these bytes name the location: `traigent-runs/readiness/<YYYYMMDDTHHMMSSZ>/`,
one directory per scoring. Readiness runs at least four times in a guided run -
opening, local validation, after each repair, and once at the end - so a flat
name would collide with itself, and `traigent-runs/sdk-results` is the precedent
for a subdirectory. The timestamp is what keeps `run-safety.md`'s rule intact:
each scoring reads the source fresh and never an earlier scoring's document,
which cannot happen if no two scorings share a directory.

The directories are kept and named to the user, per the rule already stated for
persisted experiments - never delete one as automatic teardown, and give the user
the link. A read the user paid for is theirs to keep, share, or remove.

Where the measured total comes from:

    0046 measured                                          367_952
    #280, merged since, fit under the standing ceiling         +291
    this change                                                +224
      (SKILL.md, GUIDE.md reverted, README row,
       component-creation cross-reference)
    measured here                                          368_467

#280 raised nothing and recorded nothing because it fit, which is how a ledger
gap appears without anyone doing anything wrong. Naming it here is cheaper than
the next author re-deriving it.

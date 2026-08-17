# 0047 - the opening gate says where its own files go

follows: 0046
total-ceiling: 368_450
total-measured: 368_354

The opening gate requires the assistant to produce files it never placed. The
agent-source read is mandatory - without it the agent pillar scores 0 and reports
"no settings document was provided" - and the preflight JSON has to go somewhere
before readiness can read it. Where either belongs was stated only in
`references/component-creation.md`, which is the stage-3 reference, and `GUIDE.md`
said, unqualified, to keep run artifacts in the chosen project.

So the assistant was told to create a file, pointed at the project by the document
it had actually read, and the one line saying otherwise sat a stage away in a
document the opening gate gives it no reason to open. Three blinded runs over the
same project resolved that three ways and reported agent pillars of 41/100,
12/100 and 0/100 for identical code. The run that wrote into the project also
refuted the opening promise that the score changes nothing of the customer's -
the same defect 0038 recorded, arriving through a different file.

One blinded run wrote its agent-source read to BOTH the scratch path and
`traigent-runs/`, which is what a genuine contradiction looks like from the
outside: the assistant found both instructions and satisfied both.

0038 bought its bytes to name the single file the gate writes. This buys the
converse and completes it: every other file the stage produces to reach the score
goes outside the project, and the exception is named as the exception. Stage 1
carries the mandate because that is where the reader is standing when the
question arises; `component-creation.md` keeps the depth and points at it rather
than restating it.

The resident ceiling is unchanged - the sentence was rewritten three times to fit
under it rather than raise it, and the reason it gives was moved out of `GUIDE.md`
so that document states no rule `SKILL.md` does not. The total rises by the
enumeration that makes the rule general instead of about one document: naming the
preflight JSON alongside the agent-source read is exactly what stops this being
fixed for the file that was reported and left open for its sibling.

Where the measured total comes from, because 0046 recorded 367_952 and the change
here is only 111 bytes. Two things sit between them:

    0046 measured                                          367_952
    #280, merged since, fit under the standing ceiling         +291
      (SKILL.md +211, references/component-creation.md +80)
    this change                                                +111
      (SKILL.md +66, GUIDE.md +45)
    measured here                                          368_354

A change that fits raises nothing and records nothing, so it spends headroom
silently and the next entry inherits an unexplained gap. This one names it. The
ceiling is set at 368_450, leaving 96 bytes rather than the 348 that 0046 left,
because headroom that large is what let a merge consume most of it unremarked.

# 0048 - a knob is what the code reads, not what a comment mentions

follows: 0047
follows-resident-measured: 83_297
follows-total-measured: 368_467
resident-ceiling: 84_050
resident-measured: 83_976
total-ceiling: 368_850
total-measured: 368_812

The opening card scores the agent pillar from `--agent-knobs`, and the rule for
what may go in it lives in `references/component-creation.md`. That reference
opens by saying "SKILL.md's opening gate asks for this; the shape is here" - so
the owner already knows its caller is the opening gate, and the opening gate has
no reason to load a stage-3 reference. The most consequential input to the first
number a user sees was governed by a rule the stage producing it could not read.

The rule is not hypothetical. The same paragraph records what happened when it
was unstated: of the blinded runs it describes, two reasoned it out unaided and
a third recorded six comment-only names. A stub whose comment lists the settings
a real call would take describes an agent that does not exist, and reporting
those names promises a search space the project does not have - a promise the
user approves paid work against and the first run then contradicts.

So the conclusion is stated where the gate is, attributing the owner. That is
the pattern this file already uses sixty lines below for the invalid-component
rule, with the same justification in almost the same words, and it is what
"restate a conclusion, never the mandate" permits.

One correction, recorded because the ledger is where reasoning is checked. The
blinded run that prompted this entry did not demonstrate the comment-only
failure. It reported four knobs - `model`, `temperature`, `prompt_style`,
`output_format` - which are exactly the four keys of the fixture's
`traigent-runs/config-space.json`, and are not the six names in that agent's
comment. It read a historical config-space file as current wiring, which is the
sibling failure `component-creation.md` names in this very paragraph. That rule
is already stated in `SKILL.md` two hundred lines earlier and five lines above
the instruction it governs, so no wording buys it. These bytes buy the half that
was unreachable; the half that was reachable and ignored is a finding about the
assistant, not about the guidance, and is recorded as such rather than answered
with more text.

These bytes are resident and cannot move into the reference that owns them,
because being unreachable from this stage is the entire defect.

Where the measured figures come from:

    0046 resident measured                                  83_297
    0047, which fit and so recorded nothing                   +334
    this change                                               +345
    resident measured here                                   83_976

    0047 total measured                                    368_467
    this change                                               +345
    total measured here                                    368_812

0047 declared a total and no resident figure, because the resident number still
fit - by fourteen bytes. That is the same silence #280 kept, which 0047 itself
names, and it is worth more than a second mention, because 0047 nearly did not
fit at all. The branch carrying it stood at 83_676 against a 83_645 ceiling
until the `GUIDE.md` carve-out this entry's sibling commit deletes came out; the
entry's own arithmetic assumed that deletion while the tree did not contain it,
so the figure was right about a package that had not been committed. An
undeclared measurement is how that stays invisible: nothing compares a stated
number against the tree, because there is no stated number. Hence both figures
here, whether or not each forced its ceiling up.

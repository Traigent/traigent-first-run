# 0157 - the probe verdicts are defined and the gold cap bounds a claim

follows: 0156
follows-total-measured: 594_147
total-ceiling: 597_500
total-measured: 597_438

Most of this is `sdk-execution.md` defining the wiring probe's verdicts, and the reason it is worth
the bytes is that the probe is the free gate in front of a paid phase and no document said what its
answers mean. `visible`, `ignored`, `not-searched` and `unobserved` appeared in the generated bridge's output
and in no reference, so an assistant reading `{"wiring": {"model": "unobserved"}}` and exit 3 had the
verdict vocabulary of whoever wrote the runtime. The paragraph names all four, says which one is the
only evidence of a dimension, and says plainly that `unobserved` is not evidence a knob is ignored -
the distinction the runtime's own exit code turns on.

It also documents the `raised` object the probe now prints beside the verdicts, which carries an
exception CLASS and never a message. Two states produced one verdict before: a configuration that
raised and one that returned without calling the provider are different defects with different fixes,
and an operator could not tell them apart. The message is withheld for the reason the run log already
withholds it - provider exception text can carry a key or a prompt - and the paragraph says so, so
nobody adds it back as a convenience.

Both verdict paragraphs sit BELOW the "runnable wrapper is bundled" marker rather than in the
decorator contract above it. That region is read as the wrapper's list of adaptation sites, and a
backticked name inside it has to be a top-level name in the fence - so documenting a generated-bridge
output key there failed a guard. The first attempt dropped the backticks to get past it, which hid
the token instead of moving it; the paragraphs moved instead, and the key is backticked like every
other.

`evaluation-and-dataset.md` carries the rest, and it is a correction rather than an addition. Its
sql-structure paragraph said "a failing row blocks the run - not a minority the degenerate-gold
bounds below may exclude", written two commits earlier on this same branch, and the round that moved
gold out of the blocking integrity cap made that sentence false while leaving it in place: the
document would have told an assistant to stop a run the scorer lets proceed. It now says what the
code does, and the new routing bullet beside it carries the half that is easy to get wrong - the
limit is this guide's grammar, so the data is not defective and the creation matrix is the wrong
door. This is the contradiction class `CLAUDE.md` describes, found by reading the whole document
rather than the diff.

No other document moves. `GUIDE.md`, `SKILL.md` and `run-safety.md` are untouched, so resident and
document stay where 0155 and 0156 left them; the readiness and preflight changes in this round are
code, which this ledger does not weigh. Total is raised by the smallest round figure that clears the
measurement.

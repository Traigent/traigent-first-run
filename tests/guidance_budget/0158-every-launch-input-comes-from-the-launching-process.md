# 0158 - every launch input comes from the launching process

follows: 0157
follows-total-measured: 597_438
total-ceiling: 599_000
total-measured: 598_821

All of this is `run_wrapper.py`, and it closes the last way a project file could decide what a paid
run does. Three approved cost figures and the baseline timeout were already captured before
`load_dotenv`. Nine more were not: both trial caps, the per-request and optimization timeouts, the
three model selections, the provider, the reasoning effort and the results folder all read the
MERGED environment, so a stale or attacker-writable `.env` supplied any the launching process left
out. Measured on a fixture before this change, the file's `ENHANCED_MAX_TRIALS=23` won - against the
comment beside that very read saying a raise without a newly scoped approval is forbidden.

The fix is one snapshot rather than nine more captures. `LAUNCH_ENVIRONMENT = dict(os.environ)` is
taken before the load, and the three readers every launch input goes through now read it instead of
`os.environ`. A list of names would have been as complete as whoever wrote it, and the next input
added would have rejoined the file's reach with nothing failing; a snapshot makes the safe spelling
the only spelling. It also retires `LAUNCH_BOUNDS` and the `values=` parameter 0155 introduced for
the timeout alone - one mechanism now, where there were two.

The results folder reads from the snapshot and still WRITES to the live environment, because
`run-safety.md` calls it "the process-only SDK results folder" and the SDK reads it from there: a
`.env` naming it is the one file that must not decide where this run's logs land.

The bytes are the two paragraphs explaining why a snapshot and not a list, which is the decision a
reader would otherwise undo by adding a tenth name. Resident and document do not move - `GUIDE.md`,
`SKILL.md` and `run-safety.md` are untouched - and total is raised by the smallest round figure that
clears the measurement.

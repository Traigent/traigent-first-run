# 0147 - the run writes no bytecode

follows: 0146
follows-total-measured: 574_710
follows-document-measured: 177_483
total-ceiling: 574_894
total-measured: 574_890
document-ceiling: 177_639
document-measured: 177_575

A hundred and eighty bytes, in two code fences. The free mock check and both paid phases import
the customer's preserved agent and evaluator, and each import wrote `__pycache__/*.pyc` beside
their source, outside `traigent-runs/`. The close's list of what the run wrote says to name only
what was written, and never named those. Now the wrapper template in sdk-execution.md opens with
`import sys` and `sys.dont_write_bytecode = True`, ahead of every other import and so of every
`# ADAPT:` site and the door (88 bytes), and the mock activation prelude in run-safety.md opens the
same way (92 bytes). First rather than merely before the customer's modules, because the SDK's own
imports write into an environment installed without compiled bytecode, which can be a `.venv`
inside their project. Each is a line the assistant already copies verbatim, not a flag to carry
into every launch, so what it has to remember does not grow.

sdk-execution.md, run-safety.md and evaluation-and-dataset.md were read end to end. Once nothing is
written beside those modules, the close's list is true as it stands, so it is unchanged. Calibration
is the one other launch that loads a customer module, and #559 tracks it separately. SKILL.md and
GUIDE.md are unchanged, so RESIDENT is not declared.

TOTAL is raised by 127 bytes, to four above the measurement: only 57 of the 180 bytes fit the room
0146 left. Four is the margin every one of the 28 entries from 0102 to 0130 left; the entries from
0131 to 0146 left more, from 36 to 409 bytes, so this follows the older convention rather than the
newest one. Restoring 0146's 57-byte gap instead would grant room this change does not use, and
the next raise is a decision for whoever needs it. DOCUMENT, still run-safety.md, grows 92 inside
the 156 bytes 0146 left, so its ceiling stays and 64 remain.

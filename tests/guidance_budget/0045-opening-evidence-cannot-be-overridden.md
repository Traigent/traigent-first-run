# 0045 - opening evidence cannot be overridden

follows: 0044
resident-ceiling: 80_950
resident-measured: 80_559
total-ceiling: 370_650
total-measured: 370_217

The opening score now has a short, resident contract because a rule that lives
only beside one command is too easy for a fresh worker to miss. The new text
states which evidence forms the opening verdict, refuses declared component
states mixed with measured evidence, and tells the worker to record the row
review's normalized origin and explicit run membership. Those details are not
reference material for a later stage: they govern the very first safe score and
prevent a plausible-looking command from silently ignoring supplied state.

The increase is deliberate rather than padding. A Case 08 worker previously
passed `--agent invalid`, `--dataset real`, and `--evaluation invalid` beside
preflight evidence; the command returned a score but silently discarded all
three declarations. The executable rejection protects the call, while this
resident sentence protects the human who assembles it. 80_559 bytes is the
measured combined size of `GUIDE.md` and `SKILL.md` on this branch. The 420-byte
headroom accommodates a small corrective clarification, not an unbounded new
stage. The complete staged package measures 370_217 bytes after this ledger
entry itself is included; its 462-byte allowance follows the same bounded
maintenance policy and keeps the total ceiling honest about the shipped files.

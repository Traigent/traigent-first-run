# 0002 - an internal failure gets its own exit code, and undeclared keys are refused

follows: 0001
total-ceiling: 229_250
total-measured: 228_996

Two branches bought bytes in `run-safety.md` and neither could have weighed the
other. #159 writes down what an assistant must do when a bundled script dies
inside itself: exit 3 now separates "the script broke" from "the script judged
your material and found a problem", and without that sentence the assistant
relays a verdict nobody computed. #190 refuses a config-space key the schema
does not name, which needs its own line beside the exit rules because a refusal
the reader cannot anticipate reads as a bug in our tooling rather than a typo in
theirs. Both are obligations with no earlier statement anywhere, so neither
displaces prose; both land in the reference that already owns script exits,
which is the placement policy holding rather than being spent.

The figure here was taken on the merged tree, after #172, #167, #162, #186,
#192, #190, #191 and #159 were all in it. #159 alone declared 228_853 against
its own base; that number is honest for that branch and wrong for this tree,
which is the arithmetic this ledger was built to force. 229_250 keeps 254 bytes
free - deliberately thin, because the next author should have to open a file
rather than discover they had room.

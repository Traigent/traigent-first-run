# 0165 - no usable row is not a partial repair

follows: 0164
follows-total-measured: 612_117
total-ceiling: 612_150
total-measured: 612_137

A non-UTF-8 dataset (#617) and a dataset whose every selected input is blank (#620) leave no
usable row. They were capped as `dataset-integrity-fail` at 35, the rung for a file where some
rows parsed, which put them above an unlabelled file (30) and a file no row of which matched (25).
The scorer now raises `dataset-unusable` at 25 with the same repair remedy. The integrity routing
bullet names the new id beside the old one, so its route is written; no sentence changes.

# 0064 - pin the standard connected payload boundary

follows: 0063
follows-total-measured: 432_942
total-ceiling: 433_500
total-measured: 433_300

The review found that the earlier probe had inspected local trial metadata and
mistaken it for the connected submission. The standard guide path rebuilds
metadata before serializing the session-results request: raw example input,
expected output, and model output are absent, while the configuration label,
numeric score, stable example ID, and numeric measure remain. The replacement
test follows both transformations without opening a socket. The guidance keeps
the documented contract's explicit opt-in exceptions and packet-audit limit,
removes a deprecated privacy decorator argument that offered no protection, and
does not confuse result telemetry with authentication transport.

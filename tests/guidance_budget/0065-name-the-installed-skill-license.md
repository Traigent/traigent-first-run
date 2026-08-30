# 0065 - name the installed skill license

follows: 0064
follows-total-measured: 433_300
total-ceiling: 433_500
total-measured: 433_320

The installed skill now declares `license: Apache-2.0` in its frontmatter, so an
agent or installer can identify the terms without inferring them from files it
may not load. The twenty added bytes replace implicit package metadata with the
same SPDX identifier carried by the repository README and the bundled license
text. The existing ceiling already has room for this customer-facing fact, so
the entry records the new total without widening the budget.

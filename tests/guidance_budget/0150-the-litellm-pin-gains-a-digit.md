# 0150 - the litellm pin gains a digit

follows: 0149
follows-total-measured: 576_173
follows-document-measured: 178_288
total-ceiling: 576_178
total-measured: 576_174
document-ceiling: 178_293
document-measured: 178_289

One byte, and no new guidance. The throwaway install notice in run-safety.md names the exact
litellm pin, and that pin moves from 1.93.2 to 1.101.0 to clear a scanner finding against the
older client: a minor version that has three digits is one character longer than one that has
two. Nothing else in any assistant-facing document changed, and the sentence still says the same
thing in the same place, so no other reference was re-read for consistency.

run-safety.md is still the largest document, so DOCUMENT is declared beside TOTAL, both measured
on this tree. Each ceiling moves up by the single byte the pin added, which restores the
four-byte margin 0149 kept rather than spending what was left of it on a version string.

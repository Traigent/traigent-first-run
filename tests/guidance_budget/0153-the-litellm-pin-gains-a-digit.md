# 0153 - the litellm pin gains a digit

follows: 0152
follows-total-measured: 590_594
total-ceiling: 591_501
total-measured: 590_595

The pinned litellm client moves from 1.93.2 to 1.101.0 to clear a scanner finding reported against the older client (Aikido AIKIDO-2026-538050, CVE-2026-89032). No guidance was added. The pin appears in the README and in the throwaway install notice in run-safety.md, and a minor version of three digits is one character longer than one of two. The ceiling moves up by exactly the bytes the pin added, so the margin 0152 kept is not spent on a version string.

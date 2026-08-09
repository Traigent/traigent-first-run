# 0024 - the store the upload id belongs to

follows: 0023
total-ceiling: 326_400
total-measured: 326_132

The pinned release changed underneath two passages and neither could be left
alone. `sync_session_id` is a public field on 0.26.0 and was absent on 0.25.0 -
verified by importing both releases and listing the dataclass fields - so the
sentence saying no supported id exists is now false, and the upload path it was
closing is open. Deleting that sentence is free. What costs bytes is that the
open path immediately raises a question the old one never had to answer.

An id resolved against the wrong store is rejected while its record sits on
disk. `traigent sync` is a separate process that reads its root from its own
environment, and this walkthrough sets `TRAIGENT_RESULTS_FOLDER` inside the
Python process only, so the two shell lines beside this now carry that variable
and a short paragraph says why removing it breaks them. Leaving it implicit
would hand the assistant a documented command that fails on the one shape this
guide produces, and the failure reads as a missing record rather than a
mislocated one.

The second addition is what an empty value means. Silence about that is worse
than absence was: the walkthrough's baseline runs without a Traigent key, so a
populated id is the expected case, and a run the backend tracked end to end
returns nothing here precisely because there is nothing to upload. An assistant
reading only the feature-detection instruction would treat both as one failure
and report a local-only baseline for a run already visible in the portal. Four
lines separate them and name `cloud_url` as the answer in the second case.

Two paragraphs were also removed to pay for part of this. The relative-dataset
defect through 0.25.0 is fixed on the pinned release, and the guide may not name
a release nobody installs, so its history left with it - and the rule it used to
justify stands on the reason that outlives any release: an absolute path is the
same file whichever directory the reading process happens to stand in, and this
run, a re-run and the sync CLI are three of them. What remains is shorter than
what it replaced, which is why 732 bytes buys all of the above.

326_132 measured with `assistant_facing_documents()` on this branch, stacked on
the Apache relicensing that precedes it. The resident figure moved by twenty
bytes there - one frontmatter line declaring the licence - and stays far under
its own ceiling, so this entry does not restate it.

# 0064 - say what the payload actually carries

follows: 0063
follows-total-measured: 432_942
total-ceiling: 433_500
total-measured: 433_241

The transmission paragraph told the customer that connected runs exclude their
prompts, dataset contents, expected outputs and model responses from the
backend payload. Measured on the pinned SDK that is false: every trial carries
`example_results` holding each scored example's input, expected output and
model output, and asking for privacy on the decorator does not remove them. The
old sentence was the more comfortable one and it was wrong at the exact moment
the customer decides whether to hand over a key. These bytes buy an accurate
statement plus the pinned probe that makes it go red when the SDK changes,
rather than a promise nobody had measured.

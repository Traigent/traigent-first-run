# 0012 - detect truncation instead of predicting headroom

follows: 0011
follows-total-measured: 255_847
total-ceiling: 259_400
total-measured: 258_953

#168 deletes a two-sentence `max_tokens` floor and pays roughly three kilobytes
for what replaces it, which looks like a bad trade until you ask what the floor
was worth. It recommended 2048 tokens, 4096 under high reasoning effort, and
derived neither number from any measurement, vendor limit or trial. A guess that
REFUSES breaks configurations that would have been fine - 2048 is absurd for an
agent answering `a`, `b`, `c` or `d` - and a cap this guide introduces spans two
runs, so a number sized for the baseline's medium model truncates the enhanced
run's stronger one on a configuration the customer never chose.

The replacement costs more because it has to say three separate things rather
than assert one number: carry the user's own cap through verbatim when they set
one and send none when they do not; impose no floor and refuse no value, because
reasoning headroom is not predictable from anything this package can read; and
bound the clock or the trial count where a bound is genuinely wanted, since a
time limit leaves finished work intact while a token limit corrupts it. Beside
that sits the detection that replaces the prediction - the wrapper refuses a
trial the provider reports as `finish_reason == "length"` rather than letting a
cut-off answer score 0 and crown a weaker model - plus the refused trial's spend
in `REFUSED_TRIAL_COSTS` and the post-run line that asks for it, without which a
truncated trial bills the customer and reports nothing.

258_953, measured on the merge of #168 into the twenty-three already in this
tree, not taken from the branch: #168 declared 231_930 against its own base and
that figure predates eleven other merges. RESIDENT does not move at all - every
byte lands in run-safety.md and sdk-execution.md, which a run loads and leaves -
so the 64_500 ceiling from 0011 still holds and is not restated here.

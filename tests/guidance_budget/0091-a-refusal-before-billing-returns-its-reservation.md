# 0091 - a refusal before billing returns its reservation

follows: 0090
follows-total-measured: 498_251
follows-document-measured: 132_441
total-ceiling: 506_000
total-measured: 504_689
document-ceiling: 140_500
document-measured: 138_879

The spend door reserved a conservative figure before every provider call and kept it on any
failure, on the argument that a failed call had reached a model and might have been billed. A
real first run showed the case that argument never covered: two model ids missing from the
account's catalogue, ninety-nine requests the gateway turned away with a 404 before any model
saw them, and an exit line telling the customer that nearly the whole approved total was gone
when the provider had charged a hundredth of that. The run then stopped itself at a ceiling it
had not actually reached and lost most of its trials to a refusal that cost nothing. The bytes
here name the short list of classes a gateway decides before generation, return those
reservations in place so every invocation is still one ledger entry, print a second exit line
that turns "spent almost nothing" into the diagnosis, and state the one rule that keeps the
refund on the safe side: it applies to an invocation that reserved for a single request and to
nothing larger, because a retried or fallback invocation surfaces only its last attempt's class
and an earlier attempt may well have been billed. The prose also corrects two enumerations that
had listed a rate limit among the failures that hold their money, and records that the pinned
client hands an OpenRouter 402 to a class the list does not name.

Weighed after the merge of this branch alone. The reference that holds the door takes the whole
of the growth and was already the largest single document, so this entry raises the figure that
watches one file rising on its own as well as the total; the resident pair is untouched and its
ceiling is not restated here.

# 0035 - repair is not a promise about their product

follows: 0034
follows-total-measured: 353_736
total-ceiling: 355_100
total-measured: 354_942

The repair route carried a sentence saying it was the only one where the result
could still be about the customer's product, and the worked example beside it
put that sentence over an echo stub and a scorer that returns the same number
for every answer. Repairing those two means writing a call path and a grader
that neither file has, so what the route produces is walkthrough material with
the customer's rows and task attached and none of their code. The claim was true
of the case the sentence was written for, a real component with a mendable
defect, and false of the case the example actually showed.

That is the worst place for it. The line is read by somebody deciding where to
spend, at the one moment the run asks them to choose, and it offers the thing
they most want to hear. A person picking the repair route on that promise learns
what it was worth only after the run, from a result marked with a `🛠️` they
were told they were avoiding. Every other sentence in this package works to keep
that marker honest, and this one sold past it.

So what separates the two routes is stated as the property it actually is: how
much of the customer's material survives the repair, which is a fact about the
files and not about the copy being reversible. Mending one broken line in a real
scorer keeps their ruler. Writing the call path an echo stub never had keeps
their rows and their task and nothing else. The instruction is to say which of
the two this is, in the sentence the customer reads, rather than to reach for the
stronger of the two claims by default.

The remaining bytes buy an ending. A blinded run appended a further question
after the standing exit - free to answer, materially useful, and a second
decision all the same, which is what the single ask exists to prevent. A question
costs its reader whether or not it costs them work: it has to be noticed,
weighed and answered before the one that matters. Saying the ask ends is cheaper
than the paragraph that would otherwise be needed to explain which extra
questions are allowed, and there is no such set.

354_942, measured with `assistant_facing_documents()` on this branch. Resident is
untouched at 78_695 and its ceiling does not move - the flow already names the
three routes, and both corrections are in the reference that speaks them.

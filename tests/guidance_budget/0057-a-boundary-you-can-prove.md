# 0057 - a boundary you can prove

follows: 0056
total-ceiling: 429_600
total-measured: 429_541

The containment contract demanded an OS-enforced boundary before any scorer
executes model-written code or SQL, and shipped no way to reach one. A customer
arriving with a code-generation or text-to-SQL evaluator met a requirement, no
means of meeting it, and a refusal that existed only as a sentence somebody had
to read and act on. Nothing in this package produced such a boundary, and
nothing looked at whether the one an assistant believed in was real.

What the bytes buy is the clause that puts a door where the dead end was. They
deliberately do not describe a sandbox. A recipe written into this file would
be one more instruction nothing checks - the defect class this repository keeps
rediscovering - and it would rot against every host that is not the one it was
written on, which was measured rather than assumed: the recipe this repository
already owns for its own container job is refused outright by the daemon on one
ordinary developer machine, with an error about file sharing that says nothing
about containment. The command belongs to the customer, so the guidance names a
checker and lets them declare their own boundary to it.

Everything that would otherwise be spent here sits in that checker's docstring,
the arrangement the run-log validator already uses further down this same
reference. That is what holds the raise to six lines: what each exit means, the
six properties read from inside the boundary, and the eight things the check
cannot reach - resource limits, per-candidate disposability, descendant
teardown, any host path it was never told about, seccomp confinement, a secret
under a name it does not recognise, whether the boundary shares a process
namespace, and the truthfulness of the command's own report - all live where
they cannot drift away from the code that decides them.

One folded field lands in the record template, closing a gap this same file
opened. It
has asked since long before this change that the boundary, its limits, mounted
inputs and permitted side effects be written down, against a template carrying
no row to write them on. A mandated record with nowhere to go is a mandated
boundary with no way to build one, one document further along.

The path is narrow and the cost is sized to it. A scorer that executes
model-written code or SQL is the exception rather than the rule - most compare
strings or numbers and never reach a shell - so none of this enters the resident
documents and that figure is unmoved. No count is offered for how rare, because
this repository holds nothing that could establish one. A reader who never
brings such an evaluator pays six lines in a reference they already load, inside
a section that was two thousand bytes of contract nobody could act on; the
reader who does bring one is told, at the moment their own evaluator is parsed,
which command settles it.

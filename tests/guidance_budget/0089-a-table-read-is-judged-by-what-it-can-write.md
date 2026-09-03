# 0089 - a table read is judged by what it can write

follows: 0088
follows-total-measured: 493_524
total-ceiling: 494_000
total-measured: 493_699

An author who put a debug line naming their own option table lost the setting that table holds, and
the guidance confirmed the loss was correct: it listed four spellings a read was allowed to take and
called every other one disqualifying. That list was never the reason. What protects the score is
that a read must not write to the table, nor to anything the table holds, nor carry it somewhere the
check stops being able to say so - and a join, a length, a sort, a loop or a plain second name for
the same object does none of those. Stating the property costs 175 bytes against the list it
replaces, and it retires the worst advice this package has given, which was that mentioning your own
table is riskier than never referring to it. A reader can now decide about a spelling nobody has met
yet, instead of comparing theirs against four examples and guessing which side of the line it falls.
The predecessor entry describes the four-shape rule as it stood when its own bytes were spent; that
record stays as written, because it correctly reports the tree it measured.

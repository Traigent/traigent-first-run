"""Schema-free structural comparison of SQL SELECT statements.

This module answers one question: do two SQL strings have the same structure?
It is the metric the public text-to-SQL benchmarks call *exact set match*: the
statements are broken into their clauses, each clause is put into a canonical
form, and the two canonical forms are compared for equality.

Nothing is run and nothing is opened. There is no database connection, no
catalog, no file access and no network access. The module has no dependencies
at all: it does not pull in a single name from the standard library, so a copy
of this one file is the whole install.

Typical use, next to a scoring function::

    from sql_structure import structural_match

    def score_sql(*, output, expected, input_data, metadata):
        del input_data, metadata
        return structural_match(output, expected)

Public API
----------
``structural_signature(sql)``
    The canonical structure of ``sql`` as a nested tuple. Hashable, stable
    across runs and across processes (nothing in it depends on ``hash()``
    randomisation), and safe to use as a dictionary key.
``structural_match(candidate, expected)``
    ``1.0`` when the two signatures are equal, ``0.0`` otherwise.

What is normalised
------------------
* A markdown code fence wrapped around the query, with or without a language
  tag and with or without prose around it. This is how a chat model hands back
  SQL, so it is treated as part of the input format rather than as an error.
* Leading and trailing whitespace, all interior whitespace, line comments
  (``-- ...``), block comments (``/* ... */``) and one trailing semicolon.
* Keyword case, identifier case, and the three delimited identifier spellings
  (``"x"``, ``[x]``, `` `x` ``). String literals keep their case.
* ``!=`` folds to ``<>``.
* Redundant parentheses.
* Set-valued clauses become sorted tuples: the select item list, the table
  set, the ``GROUP BY`` list, an ``IN`` value list, and the conjunct set of
  ``WHERE`` / ``HAVING`` / ``ON``. ``ORDER BY`` stays an ordered list because
  its order is part of the meaning.
* Operand order for the symmetric comparisons (``=``, ``<>``, ``IS``,
  ``IS NOT``) and for commutative arithmetic (``+``, ``*``). The asymmetric
  comparisons are turned to face one way instead: ``a < b`` is rewritten to
  ``b > a``, so ``a < b`` and ``b > a`` agree while ``a < b`` and ``b < a``
  stay apart.
* ``AND`` chains and ``OR`` chains each flatten to a sorted set at their own
  level. The nesting between them is kept, so ``a AND (b OR c)`` never
  collapses into ``a AND b AND c``.
* ``RIGHT JOIN`` is flipped to the equivalent ``LEFT JOIN`` with its operands
  swapped. A run of ``INNER`` / ``CROSS`` / comma joins flattens to a table
  set plus a condition set, and when the whole ``FROM`` clause is one such run
  its ``ON`` conjuncts merge into the ``WHERE`` conjunct set, because for
  inner joins the two are the same predicate. Outer joins keep their operand
  order, since ``a LEFT JOIN b`` is not ``b LEFT JOIN a``.
* ``UNION`` and ``INTERSECT`` chains flatten to a sorted operand set (both are
  commutative and associative). ``EXCEPT`` keeps its operand order.
* Table aliases, when they can be resolved without a catalog: if every base
  table in a query block appears once and every qualifier in the block is
  distinct, then ``FROM orders AS o ... o.amount`` is rewritten to
  ``orders.amount`` and the alias itself is dropped. That makes two queries
  that pick different alias spellings agree. When a table appears twice in one
  block (a self join) no alias is resolved and every alias is compared
  literally, because resolving them there would merge two distinct references.
* Select list aliases are stripped from the comparison, but recorded, so that
  a later reference to the alias in ``GROUP BY`` / ``HAVING`` / ``ORDER BY``
  is compared against the expression it names.

What it deliberately does NOT claim
-----------------------------------
Without a catalog some pairs cannot be judged, and every one of them is
compared syntactically, which means the comparator reports a difference rather
than guessing. These are real, known divergences from a schema-aware metric:

* ``amount`` and ``orders.amount`` are not known to be the same column. An
  unqualified name is never attributed to a table.
* ``SELECT *`` is not known to cover any particular column list, and
  ``SELECT *`` is not matched against ``SELECT t.*``.
* ``JOIN b USING (id)`` is not expanded to ``ON a.id = b.id``, and
  ``NATURAL JOIN`` is not expanded at all. Both are held as opaque join
  conditions, and a join carrying one is never folded into a table set.
* ``ORDER BY 1`` is kept as the literal ``1``. Since the select list is
  compared as a set, an ordinal cannot be resolved back to an item.
* Type names are compared as written, so ``CAST(x AS INT)`` and
  ``CAST(x AS INTEGER)`` differ.
* Numeric literals are compared as written, so ``1.5`` and ``1.50`` differ.
* Equivalences that are semantic rather than structural are out of reach by
  design: ``COUNT(*)`` and ``COUNT(1)``, ``x IN (1, 2)`` and
  ``x = 1 OR x = 2``, ``NOT (a > b)`` and ``a <= b``.

Coverage limits
---------------
The grammar covers ``SELECT`` statements, including ``WITH`` clauses, set
operators, subqueries in ``SELECT`` / ``FROM`` / ``WHERE``, ``CASE``,
``CAST``, ``IN``, ``EXISTS``, ``BETWEEN``, ``LIKE`` and ``IS``. Window
functions (``OVER (...)``), ``VALUES`` lists, and statements other than
``SELECT`` are not covered. Words in the reserved list below are always read
as keywords, so a column literally named ``order`` or ``end`` has to be
quoted. Anything the grammar cannot read is a non-match, never a crash and
never a silent agreement: the signature comes back tagged ``"unparsed"`` and
``structural_match`` returns ``0.0`` even when both sides are the same
unreadable string.

The one exception to never raising is deliberate. A non-string argument is
passed through ``str()``, and if that object's ``__str__`` raises, the error
propagates instead of being swallowed.

Design note on provenance: the grammar here was written from the SQL language
definition. No code was taken from any benchmark harness or from any
third-party SQL parser.
"""

from __future__ import annotations

__all__ = ["structural_match", "structural_signature"]

_MAX_DEPTH = 40

_UNPARSED = "unparsed"

_DIGITS = "0123456789"
_HEX_DIGITS = "0123456789abcdefABCDEF"
_SPACE = " \t\r\n\f\v"
_PUNCTUATION = "(),.;"

# Longest first, so that "<=" wins over "<".
_OPERATORS = (
    "->>",
    "<=",
    ">=",
    "<>",
    "!=",
    "||",
    "::",
    "->",
    "=",
    "<",
    ">",
    "+",
    "-",
    "*",
    "/",
    "%",
)

_KEYWORDS = frozenset(
    {
        "ALL",
        "AND",
        "AS",
        "ASC",
        "BETWEEN",
        "BY",
        "CASE",
        "CAST",
        "CROSS",
        "DESC",
        "DISTINCT",
        "ELSE",
        "END",
        "ESCAPE",
        "EXCEPT",
        "EXISTS",
        "FROM",
        "FULL",
        "GROUP",
        "HAVING",
        "ILIKE",
        "IN",
        "INNER",
        "INTERSECT",
        "IS",
        "JOIN",
        "LEFT",
        "LIKE",
        "LIMIT",
        "NATURAL",
        "NOT",
        "NULL",
        "NULLS",
        "OFFSET",
        "ON",
        "OR",
        "ORDER",
        "OUTER",
        "RECURSIVE",
        "RIGHT",
        "SELECT",
        "THEN",
        "TRUE",
        "FALSE",
        "UNION",
        "USING",
        "WHEN",
        "WHERE",
        "WITH",
    }
)

# Reserved words that are also common function names, so they are allowed to
# start a call when the next token is an open parenthesis.
_KEYWORD_FUNCTIONS = frozenset({"LEFT", "RIGHT"})

# Documented for readers of a signature: these are the aggregates the metric
# cares about. They need no special handling, because a call node already
# carries the name, the DISTINCT flag and the argument list.
_AGGREGATES = frozenset({"AVG", "COUNT", "MAX", "MIN", "SUM"})

# The words a SELECT statement may begin with. Anything else at the head of a
# one-line code fence is the fence info string (its language tag) and is
# dropped rather than lexed.
_STATEMENT_STARTERS = frozenset({"select", "with"})

_SYMMETRIC = frozenset({"=", "<>"})
_COMMUTATIVE = frozenset({"+", "*"})
_MIRRORED = {"<": ">", "<=": ">="}
_COMPARISONS = ("=", "<>", "<", "<=", ">", ">=")

_Token = tuple[str, str]
_Node = tuple


class _SqlSyntaxError(Exception):
    """Internal signal that a string cannot be read as a SELECT statement."""


# ---------------------------------------------------------------------------
# Canonical ordering helpers
# ---------------------------------------------------------------------------


def _sorted(items) -> tuple:
    """Order a collection of signature nodes deterministically.

    ``repr`` is used as the key so that nodes of unlike shape never have to be
    compared directly, which would raise. The result depends only on the nodes
    themselves, so it is stable across runs and processes.
    """
    return tuple(sorted(items, key=repr))


def _sorted_set(items) -> tuple:
    """Order a collection and drop repeats, keeping the first of each."""
    unique = dict.fromkeys(items)
    return tuple(sorted(unique, key=repr))


def _conjuncts(node: _Node | None) -> list:
    """Split a normalised predicate into its top level AND conjuncts."""
    if node is None:
        return []
    if node[0] == "and":
        return list(node[1])
    return [node]


def _and_of(parts) -> _Node | None:
    """Rebuild a predicate from conjuncts, as a set with repeats dropped."""
    unique = _sorted_set(parts)
    if not unique:
        return None
    if len(unique) == 1:
        return unique[0]
    return ("and", unique)


# ---------------------------------------------------------------------------
# Input shaping
# ---------------------------------------------------------------------------


def _drop_info_string(text: str) -> str:
    """Drop a one-line fence's language tag, if it carries one.

    Only reached for a fence opened and closed on a single line, where the tag
    is not separated from the query by a newline.
    """
    stripped = text.lstrip()
    cut = 0
    while cut < len(stripped) and (stripped[cut].isalnum() or stripped[cut] == "+"):
        cut += 1
    if cut and stripped[:cut].lower() not in _STATEMENT_STARTERS:
        return stripped[cut:]
    return stripped


def _strip_fence(text: str) -> str:
    """Return the body of the first markdown code fence, or the text itself.

    A chat model usually answers with the query inside a fence, sometimes with
    a sentence on either side. Both shapes are accepted.
    """
    body = text.strip()
    for marker in ("```", "~~~"):
        start = body.find(marker)
        if start < 0:
            continue
        after = body.find("\n", start)
        end = body.find(marker, start + len(marker))
        if after < 0 or (end >= 0 and end < after):
            inner = body[start + len(marker) : end if end >= 0 else len(body)]
            return _drop_info_string(inner).strip()
        inner = body[after + 1 : end if end >= 0 else len(body)]
        return inner.strip()
    return body


def _read_delimited(text: str, start: int, quote: str) -> tuple[str, int]:
    """Read a quoted run where the quote is escaped by doubling it."""
    index = start + 1
    size = len(text)
    chunks: list[str] = []
    while index < size:
        char = text[index]
        if char == quote:
            if index + 1 < size and text[index + 1] == quote:
                chunks.append(quote)
                index += 2
                continue
            return "".join(chunks), index + 1
        chunks.append(char)
        index += 1
    raise _SqlSyntaxError("unterminated quoted text")


def _read_number(text: str, start: int) -> tuple[str, int]:
    size = len(text)
    index = start
    if text[index] == "0" and index + 1 < size and text[index + 1] in "xX":
        index += 2
        while index < size and text[index] in _HEX_DIGITS:
            index += 1
        return text[start:index].lower(), index
    while index < size and text[index] in _DIGITS:
        index += 1
    if index < size and text[index] == ".":
        index += 1
        while index < size and text[index] in _DIGITS:
            index += 1
    if index < size and text[index] in "eE":
        probe = index + 1
        if probe < size and text[probe] in "+-":
            probe += 1
        if probe < size and text[probe] in _DIGITS:
            index = probe
            while index < size and text[index] in _DIGITS:
                index += 1
    return text[start:index].lower(), index


def _tokens(text: str) -> list[_Token]:
    """Turn SQL text into tokens, dropping whitespace and comments.

    Token kinds are ``kw`` (a reserved word, upper case), ``id`` (an
    identifier, lower case), ``str`` (a string literal, case kept), ``num``
    (a numeric literal), ``op`` and ``punc``.
    """
    out: list[_Token] = []
    index = 0
    size = len(text)
    while index < size:
        char = text[index]
        if char in _SPACE:
            index += 1
            continue
        if char == "-" and text.startswith("--", index):
            stop = text.find("\n", index)
            index = size if stop < 0 else stop + 1
            continue
        if char == "/" and text.startswith("/*", index):
            stop = text.find("*/", index + 2)
            if stop < 0:
                raise _SqlSyntaxError("unterminated block comment")
            index = stop + 2
            continue
        if char == "'":
            value, index = _read_delimited(text, index, "'")
            out.append(("str", value))
            continue
        if char in '"`':
            value, index = _read_delimited(text, index, char)
            out.append(("id", value.lower()))
            continue
        if char == "[":
            stop = text.find("]", index + 1)
            if stop < 0:
                raise _SqlSyntaxError("unterminated bracket identifier")
            out.append(("id", text[index + 1 : stop].lower()))
            index = stop + 1
            continue
        if char in _DIGITS or (
            char == "." and index + 1 < size and text[index + 1] in _DIGITS
        ):
            value, index = _read_number(text, index)
            out.append(("num", value))
            continue
        if char == "_" or char.isalpha():
            stop = index
            while stop < size and (
                text[stop] == "_" or text[stop] == "$" or text[stop].isalnum()
            ):
                stop += 1
            word = text[index:stop]
            index = stop
            upper = word.upper()
            if upper in _KEYWORDS:
                out.append(("kw", upper))
            else:
                out.append(("id", word.lower()))
            continue
        if char in _PUNCTUATION:
            out.append(("punc", char))
            index += 1
            continue
        for symbol in _OPERATORS:
            if text.startswith(symbol, index):
                out.append(("op", "<>" if symbol == "!=" else symbol))
                index += len(symbol)
                break
        else:
            raise _SqlSyntaxError(f"unexpected character {char!r}")
    return out


# ---------------------------------------------------------------------------
# Parser: text to a raw tree, with no canonical ordering applied yet
# ---------------------------------------------------------------------------


class _Parser:
    """A recursive descent reader for the SELECT grammar.

    The output is a raw tree that still carries the query as written. All
    canonical ordering and all alias resolution happen afterwards, in the
    normaliser, because both need the FROM clause of a block and the FROM
    clause is read after the select list.
    """

    def __init__(self, tokens: list[_Token]) -> None:
        self._toks = tokens
        self._pos = 0
        self._depth = 0

    # -- token helpers ----------------------------------------------------

    def _peek(self, ahead: int = 0) -> _Token | None:
        index = self._pos + ahead
        if index < len(self._toks):
            return self._toks[index]
        return None

    def _next(self) -> _Token:
        token = self._peek()
        if token is None:
            raise _SqlSyntaxError("unexpected end of statement")
        self._pos += 1
        return token

    def _at_kw(self, *words: str) -> bool:
        token = self._peek()
        return token is not None and token[0] == "kw" and token[1] in words

    def _at_punc(self, char: str) -> bool:
        token = self._peek()
        return token is not None and token[0] == "punc" and token[1] == char

    def _at_op(self, *symbols: str) -> bool:
        token = self._peek()
        return token is not None and token[0] == "op" and token[1] in symbols

    def _accept_kw(self, *words: str) -> str | None:
        if self._at_kw(*words):
            return self._next()[1]
        return None

    def _accept_punc(self, char: str) -> bool:
        if self._at_punc(char):
            self._pos += 1
            return True
        return False

    def _accept_op(self, *symbols: str) -> str | None:
        if self._at_op(*symbols):
            return self._next()[1]
        return None

    def _expect_kw(self, word: str) -> None:
        if self._accept_kw(word) is None:
            raise _SqlSyntaxError(f"expected {word}")

    def _expect_punc(self, char: str) -> None:
        if not self._accept_punc(char):
            raise _SqlSyntaxError(f"expected {char!r}")

    def _expect_name(self) -> str:
        token = self._next()
        if token[0] != "id":
            raise _SqlSyntaxError("expected a name")
        return token[1]

    def _opens_query(self) -> bool:
        """True when the next tokens are ``(`` ... ``SELECT`` or ``WITH``."""
        ahead = 0
        while True:
            token = self._peek(ahead)
            if token is None:
                return False
            if token[0] == "punc" and token[1] == "(":
                ahead += 1
                continue
            return token[0] == "kw" and token[1] in ("SELECT", "WITH")

    def _enter(self) -> None:
        self._depth += 1
        if self._depth > _MAX_DEPTH:
            raise _SqlSyntaxError("statement nests too deeply")

    # -- statement --------------------------------------------------------

    def parse(self) -> _Node:
        query = self._parse_query()
        self._accept_punc(";")
        if self._peek() is not None:
            raise _SqlSyntaxError("trailing tokens after the statement")
        return query

    def _parse_query(self) -> _Node:
        self._enter()
        try:
            ctes = self._parse_with()
            body = self._parse_compound()
            order = self._parse_order_by()
            limit, offset = self._parse_limit_offset()
            return ("rawquery", ctes, body, order, limit, offset)
        finally:
            self._depth -= 1

    def _parse_with(self) -> tuple:
        if self._accept_kw("WITH") is None:
            return ()
        recursive = self._accept_kw("RECURSIVE") is not None
        entries = []
        while True:
            name = self._expect_name()
            columns: tuple[str, ...] = ()
            if self._at_punc("(") and not self._opens_query():
                self._expect_punc("(")
                names = []
                while True:
                    names.append(self._expect_name())
                    if not self._accept_punc(","):
                        break
                self._expect_punc(")")
                columns = tuple(names)
            self._expect_kw("AS")
            self._expect_punc("(")
            body = self._parse_query()
            self._expect_punc(")")
            entries.append((name, columns, body))
            if not self._accept_punc(","):
                break
        return (recursive, tuple(entries))

    def _parse_compound(self) -> _Node:
        left = self._parse_query_term()
        while self._at_kw("UNION", "INTERSECT", "EXCEPT"):
            operator = self._next()[1]
            everything = self._accept_kw("ALL") is not None
            if self._accept_kw("DISTINCT") is not None:
                everything = False
            right = self._parse_query_term()
            left = ("rawsetop", operator, everything, left, right)
        return left

    def _parse_query_term(self) -> _Node:
        if self._at_punc("(") and self._opens_query():
            self._expect_punc("(")
            inner = self._parse_query()
            self._expect_punc(")")
            return _unwrap_query(inner)
        return self._parse_select_core()

    def _parse_select_core(self) -> _Node:
        self._expect_kw("SELECT")
        distinct = False
        if self._accept_kw("DISTINCT") is not None:
            distinct = True
        else:
            self._accept_kw("ALL")
        items = self._parse_select_items()
        from_clause = None
        where = None
        group: tuple = ()
        having = None
        if self._accept_kw("FROM") is not None:
            from_clause = self._parse_from()
        if self._accept_kw("WHERE") is not None:
            where = self._parse_expression()
        if self._accept_kw("GROUP") is not None:
            self._expect_kw("BY")
            terms = [self._parse_expression()]
            while self._accept_punc(","):
                terms.append(self._parse_expression())
            group = tuple(terms)
        if self._accept_kw("HAVING") is not None:
            having = self._parse_expression()
        return ("rawselect", distinct, items, from_clause, where, group, having)

    def _parse_select_items(self) -> tuple:
        items = []
        while True:
            expression = self._parse_expression()
            items.append((expression, self._parse_alias()))
            if not self._accept_punc(","):
                break
        return tuple(items)

    def _parse_alias(self) -> str | None:
        if self._accept_kw("AS") is not None:
            token = self._next()
            if token[0] not in ("id", "str"):
                raise _SqlSyntaxError("expected an alias")
            return token[1].lower() if token[0] == "id" else token[1]
        token = self._peek()
        if token is not None and token[0] == "id":
            self._pos += 1
            return token[1]
        return None

    # -- FROM -------------------------------------------------------------

    def _parse_from(self) -> _Node:
        node = self._parse_table_ref()
        while True:
            if self._accept_punc(","):
                node = ("rj", "COMMA", False, node, self._parse_table_ref(), None)
                continue
            join = self._parse_join_prefix()
            if join is None:
                return node
            kind, natural = join
            right = self._parse_table_ref()
            condition = None
            if self._accept_kw("ON") is not None:
                condition = ("on", self._parse_expression())
            elif self._accept_kw("USING") is not None:
                self._expect_punc("(")
                names = []
                while True:
                    names.append(self._expect_name())
                    if not self._accept_punc(","):
                        break
                self._expect_punc(")")
                condition = ("using", tuple(names))
            node = ("rj", kind, natural, node, right, condition)

    def _parse_join_prefix(self) -> tuple[str, bool] | None:
        start = self._pos
        natural = self._accept_kw("NATURAL") is not None
        kind = "INNER"
        word = self._accept_kw("INNER", "LEFT", "RIGHT", "FULL", "CROSS")
        if word is not None:
            kind = word
            if word in ("LEFT", "RIGHT", "FULL"):
                self._accept_kw("OUTER")
        if self._accept_kw("JOIN") is None:
            self._pos = start
            return None
        return kind, natural

    def _parse_table_ref(self) -> _Node:
        if self._at_punc("("):
            if self._opens_query():
                self._expect_punc("(")
                inner = self._parse_query()
                self._expect_punc(")")
                return ("rd", inner, self._parse_alias())
            self._expect_punc("(")
            inner_from = self._parse_from()
            self._expect_punc(")")
            return inner_from
        parts = [self._expect_name()]
        while self._at_punc(".") and self._peek(1) is not None:
            following = self._peek(1)
            if following is None or following[0] != "id":
                break
            self._pos += 1
            parts.append(self._next()[1])
        return ("rt", tuple(parts), self._parse_alias())

    # -- ORDER BY / LIMIT / OFFSET ---------------------------------------

    def _parse_order_by(self) -> tuple:
        if self._accept_kw("ORDER") is None:
            return ()
        self._expect_kw("BY")
        terms = []
        while True:
            expression = self._parse_expression()
            direction = "ASC"
            if self._accept_kw("DESC") is not None:
                direction = "DESC"
            else:
                self._accept_kw("ASC")
            nulls = None
            if self._accept_kw("NULLS") is not None:
                token = self._next()
                if token[0] != "id" or token[1] not in ("first", "last"):
                    raise _SqlSyntaxError("expected FIRST or LAST after NULLS")
                nulls = token[1].upper()
            terms.append((expression, direction, nulls))
            if not self._accept_punc(","):
                break
        return tuple(terms)

    def _parse_limit_offset(self) -> tuple[_Node | None, _Node | None]:
        limit = None
        offset = None
        while True:
            if self._accept_kw("LIMIT") is not None:
                first = self._parse_expression()
                if self._accept_punc(","):
                    offset = first
                    limit = self._parse_expression()
                else:
                    limit = first
                continue
            if self._accept_kw("OFFSET") is not None:
                offset = self._parse_expression()
                continue
            return limit, offset

    # -- expressions ------------------------------------------------------

    def _parse_expression(self) -> _Node:
        return self._parse_or()

    def _parse_or(self) -> _Node:
        parts = [self._parse_and()]
        while self._accept_kw("OR") is not None:
            parts.append(self._parse_and())
        if len(parts) == 1:
            return parts[0]
        return ("or", tuple(parts))

    def _parse_and(self) -> _Node:
        parts = [self._parse_not()]
        while self._accept_kw("AND") is not None:
            parts.append(self._parse_not())
        if len(parts) == 1:
            return parts[0]
        return ("and", tuple(parts))

    def _parse_not(self) -> _Node:
        if self._accept_kw("NOT") is not None:
            return ("not", self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self) -> _Node:
        left = self._parse_additive()
        while True:
            symbol = self._accept_op(*_COMPARISONS)
            if symbol is not None:
                left = ("bin", symbol, left, self._parse_additive())
                continue
            negated = False
            start = self._pos
            if self._accept_kw("NOT") is not None:
                negated = True
            if self._at_kw("IN"):
                self._next()
                left = ("in", negated, left, self._parse_in_right())
                continue
            if self._at_kw("LIKE", "ILIKE"):
                word = self._next()[1]
                pattern = self._parse_additive()
                escape = None
                if self._accept_kw("ESCAPE") is not None:
                    escape = self._parse_additive()
                left = ("like", word, negated, left, pattern, escape)
                continue
            if self._at_kw("BETWEEN"):
                self._next()
                low = self._parse_additive()
                self._expect_kw("AND")
                high = self._parse_additive()
                left = ("between", negated, left, low, high)
                continue
            if negated:
                self._pos = start
                return left
            if self._at_kw("IS"):
                self._next()
                inner_negated = self._accept_kw("NOT") is not None
                left = ("is", inner_negated, left, self._parse_additive())
                continue
            return left

    def _parse_in_right(self) -> _Node:
        if self._opens_query():
            self._expect_punc("(")
            inner = self._parse_query()
            self._expect_punc(")")
            return ("sub", inner)
        self._expect_punc("(")
        values = []
        if not self._at_punc(")"):
            while True:
                values.append(self._parse_expression())
                if not self._accept_punc(","):
                    break
        self._expect_punc(")")
        return ("list", tuple(values))

    def _parse_additive(self) -> _Node:
        left = self._parse_multiplicative()
        while True:
            symbol = self._accept_op("+", "-", "||")
            if symbol is None:
                return left
            left = ("bin", symbol, left, self._parse_multiplicative())

    def _parse_multiplicative(self) -> _Node:
        left = self._parse_unary()
        while True:
            symbol = self._accept_op("*", "/", "%")
            if symbol is None:
                return left
            left = ("bin", symbol, left, self._parse_unary())

    def _parse_unary(self) -> _Node:
        if self._accept_op("-") is not None:
            return ("neg", self._parse_unary())
        if self._accept_op("+") is not None:
            return self._parse_unary()
        return self._parse_postfix()

    def _parse_postfix(self) -> _Node:
        node = self._parse_primary()
        while self._accept_op("::") is not None:
            node = ("cast", node, self._parse_short_type())
        return node

    def _parse_short_type(self) -> tuple:
        token = self._next()
        if token[0] not in ("id", "kw"):
            raise _SqlSyntaxError("expected a type name")
        parts = [token[1].upper()]
        if self._at_punc("("):
            parts.extend(self._parse_type_arguments())
        return tuple(parts)

    def _parse_type_arguments(self) -> list[str]:
        self._expect_punc("(")
        parts = ["("]
        while not self._at_punc(")"):
            token = self._next()
            parts.append(token[1].upper())
        self._expect_punc(")")
        parts.append(")")
        return parts

    def _parse_primary(self) -> _Node:
        self._enter()
        try:
            return self._parse_primary_inner()
        finally:
            self._depth -= 1

    def _parse_primary_inner(self) -> _Node:
        token = self._peek()
        if token is None:
            raise _SqlSyntaxError("unexpected end of expression")
        kind, value = token
        if kind == "num":
            self._pos += 1
            return ("num", value)
        if kind == "str":
            self._pos += 1
            return ("str", value)
        if kind == "op" and value == "*":
            self._pos += 1
            return ("star", ())
        if kind == "kw":
            return self._parse_keyword_primary(value)
        if kind == "punc" and value == "(":
            if self._opens_query():
                self._expect_punc("(")
                inner = self._parse_query()
                self._expect_punc(")")
                return ("sub", inner)
            self._expect_punc("(")
            values = [self._parse_expression()]
            while self._accept_punc(","):
                values.append(self._parse_expression())
            self._expect_punc(")")
            if len(values) == 1:
                return values[0]
            return ("row", tuple(values))
        if kind == "id":
            return self._parse_name_primary()
        raise _SqlSyntaxError(f"unexpected token {value!r}")

    def _parse_keyword_primary(self, value: str) -> _Node:
        if value in ("NULL", "TRUE", "FALSE"):
            self._pos += 1
            return ("lit", value)
        if value == "CASE":
            return self._parse_case()
        if value == "CAST":
            self._pos += 1
            self._expect_punc("(")
            operand = self._parse_expression()
            self._expect_kw("AS")
            type_name = self._parse_cast_type()
            self._expect_punc(")")
            return ("cast", operand, type_name)
        if value == "EXISTS":
            self._pos += 1
            if not self._opens_query():
                raise _SqlSyntaxError("EXISTS needs a subquery")
            self._expect_punc("(")
            inner = self._parse_query()
            self._expect_punc(")")
            return ("exists", inner)
        following = self._peek(1)
        if (
            value in _KEYWORD_FUNCTIONS
            and following is not None
            and following == ("punc", "(")
        ):
            self._pos += 1
            return self._parse_call(value)
        raise _SqlSyntaxError(f"unexpected keyword {value}")

    def _parse_cast_type(self) -> tuple:
        parts: list[str] = []
        while not self._at_punc(")"):
            if self._at_punc("("):
                parts.extend(self._parse_type_arguments())
                continue
            token = self._next()
            parts.append(token[1].upper())
        if not parts:
            raise _SqlSyntaxError("expected a type name")
        return tuple(parts)

    def _parse_case(self) -> _Node:
        self._expect_kw("CASE")
        operand = None
        if not self._at_kw("WHEN"):
            operand = self._parse_expression()
        branches = []
        while self._accept_kw("WHEN") is not None:
            test = self._parse_expression()
            self._expect_kw("THEN")
            branches.append((test, self._parse_expression()))
        if not branches:
            raise _SqlSyntaxError("CASE needs at least one WHEN")
        fallback = None
        if self._accept_kw("ELSE") is not None:
            fallback = self._parse_expression()
        self._expect_kw("END")
        return ("case", operand, tuple(branches), fallback)

    def _parse_name_primary(self) -> _Node:
        parts = [self._next()[1]]
        while self._at_punc("."):
            following = self._peek(1)
            if following is None:
                raise _SqlSyntaxError("dangling qualifier")
            if following[0] == "op" and following[1] == "*":
                self._pos += 2
                return ("star", tuple(parts))
            if following[0] != "id":
                raise _SqlSyntaxError("expected a name after '.'")
            self._pos += 1
            parts.append(self._next()[1])
        if len(parts) == 1 and self._at_punc("("):
            return self._parse_call(parts[0].upper())
        return ("col", tuple(parts))

    def _parse_call(self, name: str) -> _Node:
        self._expect_punc("(")
        distinct = False
        arguments: list[_Node] = []
        if not self._at_punc(")"):
            if self._accept_kw("DISTINCT") is not None:
                distinct = True
            else:
                self._accept_kw("ALL")
            while True:
                arguments.append(self._parse_expression())
                if not self._accept_punc(","):
                    break
        self._expect_punc(")")
        return ("call", name, distinct, tuple(arguments))


def _unwrap_query(node: _Node) -> _Node:
    """Drop a redundant wrapper around a parenthesised query."""
    _, ctes, body, order, limit, offset = node
    if not ctes and not order and limit is None and offset is None:
        return body
    return node


# ---------------------------------------------------------------------------
# Normaliser: raw tree to canonical signature
# ---------------------------------------------------------------------------


def _leaves(node: _Node) -> list[_Node]:
    if node[0] in ("rt", "rd"):
        return [node]
    return _leaves(node[3]) + _leaves(node[4])


def _alias_map(from_clause: _Node | None, outer: dict) -> dict:
    """Work out which table aliases can be resolved in this query block.

    Resolution is allowed only when every base table in the block appears once
    and every qualifier in the block is distinct. A self join fails both tests,
    so its aliases stay literal and two references to the same table are never
    merged into one. Local names always shadow an enclosing block, whether or
    not they can be resolved here.
    """
    scope = dict(outer)
    if from_clause is None:
        return scope
    leaves = _leaves(from_clause)
    qualifiers: list[str] = []
    base_names: list[tuple[str, ...]] = []
    for leaf in leaves:
        if leaf[2] is not None:
            qualifiers.append(leaf[2])
            scope.pop(leaf[2], None)
        elif leaf[0] == "rt":
            qualifiers.append(leaf[1][-1])
            scope.pop(leaf[1][-1], None)
        if leaf[0] == "rt":
            base_names.append(leaf[1])
    resolvable = len(set(base_names)) == len(base_names) and len(
        set(qualifiers)
    ) == len(qualifiers)
    if resolvable:
        for leaf in leaves:
            if leaf[0] == "rt" and leaf[2] is not None:
                scope[leaf[2]] = leaf[1]
    return scope


def _norm_query(raw: _Node, outer: dict) -> _Node:
    _, ctes, body, order, limit, offset = raw
    if body[0] == "rawselect":
        scope = _alias_map(body[3], outer)
        item_aliases = {alias: item for item, alias in body[2] if alias is not None}
    else:
        scope = dict(outer)
        item_aliases = {}
    body_sig = _norm_body(body, outer)
    order_sig = tuple(
        (_norm_expr(term, scope, item_aliases), direction, nulls)
        for term, direction, nulls in order
    )
    limit_sig = None if limit is None else _norm_expr(limit, scope, {})
    offset_sig = None if offset is None else _norm_expr(offset, scope, {})
    node: _Node = ("query", body_sig, order_sig, limit_sig, offset_sig)
    if ctes:
        recursive, entries = ctes
        defined = _sorted(
            (name, columns, _norm_query(inner, outer))
            for name, columns, inner in entries
        )
        node = ("with", recursive, defined, node)
    return node


def _norm_body(body: _Node, outer: dict) -> _Node:
    if body[0] == "rawselect":
        return _norm_select(body, _alias_map(body[3], outer))
    if body[0] == "rawquery":
        return _norm_query(body, outer)
    _, operator, everything, left, right = body
    return _combine_setop(
        operator,
        everything,
        _norm_body(left, outer),
        _norm_body(right, outer),
    )


def _combine_setop(operator: str, everything: bool, left: _Node, right: _Node) -> _Node:
    if operator in ("UNION", "INTERSECT"):
        operands: list[_Node] = []
        for side in (left, right):
            if side[0] == "setop" and side[1] == operator and side[2] == everything:
                operands.extend(side[3])
            else:
                operands.append(side)
        return ("setop", operator, everything, _sorted(operands))
    return ("setop", operator, everything, (left, right))


def _norm_select(raw: _Node, scope: dict) -> _Node:
    _, distinct, items, from_clause, where, group, having = raw
    item_aliases = {alias: item for item, alias in items if alias is not None}
    item_sigs = _sorted(_norm_expr(item, scope, {}) for item, _alias in items)
    if from_clause is None:
        from_sig: _Node | None = None
        merged: list[_Node] = []
    else:
        from_sig, merged = _norm_from(from_clause, scope)
    predicates = list(merged)
    if where is not None:
        predicates.extend(_conjuncts(_norm_expr(where, scope, {})))
    group_sig = _sorted_set(_norm_expr(term, scope, item_aliases) for term in group)
    having_sig = None
    if having is not None:
        having_sig = _and_of(_conjuncts(_norm_expr(having, scope, item_aliases)))
    return (
        "select",
        distinct,
        item_sigs,
        from_sig,
        _and_of(predicates),
        group_sig,
        having_sig,
    )


def _norm_from(node: _Node, scope: dict) -> tuple[_Node, list[_Node]]:
    """Return the FROM signature plus any conditions that belong in WHERE.

    When the whole clause is one run of inner joins, its ON conjuncts are
    handed back so the caller can merge them with the WHERE conjuncts. For an
    inner join the two are the same predicate over the same cross product.
    """
    flattened = _flatten_inner(node, scope)
    if flattened is not None:
        tables, conditions = flattened
        return ("joinset", _sorted(tables), ()), conditions
    return _norm_join(node, scope), []


def _flatten_inner(node: _Node, scope: dict) -> tuple[list[_Node], list[_Node]] | None:
    """Flatten a run of plain inner joins, or return None if it is not one.

    A NATURAL join or a USING join is never flattened: what it matches depends
    on which two operands meet, and a table set would throw that away.
    """
    if node[0] in ("rt", "rd"):
        return [_norm_leaf(node, scope)], []
    _, kind, natural, left, right, condition = node
    if natural or kind not in ("INNER", "CROSS", "COMMA"):
        return None
    if condition is not None and condition[0] != "on":
        return None
    left_side = _flatten_inner(left, scope)
    if left_side is None:
        return None
    right_side = _flatten_inner(right, scope)
    if right_side is None:
        return None
    tables = left_side[0] + right_side[0]
    conditions = left_side[1] + right_side[1]
    if condition is not None:
        conditions = conditions + _conjuncts(_norm_expr(condition[1], scope, {}))
    return tables, conditions


def _norm_join(node: _Node, scope: dict) -> _Node:
    if node[0] in ("rt", "rd"):
        return _norm_leaf(node, scope)
    flattened = _flatten_inner(node, scope)
    if flattened is not None:
        return ("joinset", _sorted(flattened[0]), _sorted_set(flattened[1]))
    _, kind, natural, left, right, condition = node
    if kind == "RIGHT":
        kind = "LEFT"
        left, right = right, left
    return (
        "outer",
        kind,
        natural,
        _norm_join(left, scope),
        _norm_join(right, scope),
        _norm_condition(condition, scope),
    )


def _norm_condition(condition: _Node | None, scope: dict) -> _Node | None:
    if condition is None:
        return None
    if condition[0] == "using":
        return ("using", _sorted_set(condition[1]))
    return ("on", _and_of(_conjuncts(_norm_expr(condition[1], scope, {}))))


def _norm_leaf(node: _Node, scope: dict) -> _Node:
    if node[0] == "rt":
        _, parts, alias = node
        if alias is not None and scope.get(alias) == parts:
            alias = None
        return ("table", parts, alias)
    _, inner, alias = node
    return ("derived", _norm_query(inner, scope), alias)


def _norm_expr(node: _Node, scope: dict, item_aliases: dict) -> _Node:
    kind = node[0]
    if kind == "col":
        parts = node[1]
        if len(parts) == 1 and parts[0] in item_aliases:
            return _norm_expr(item_aliases[parts[0]], scope, {})
        if len(parts) > 1 and parts[0] in scope:
            return ("col", tuple(scope[parts[0]]) + tuple(parts[1:]))
        return ("col", parts)
    if kind == "star":
        parts = node[1]
        if len(parts) == 1 and parts[0] in scope:
            return ("star", tuple(scope[parts[0]]))
        return ("star", parts)
    if kind in ("num", "str", "lit"):
        return node
    if kind == "call":
        _, name, distinct, arguments = node
        return (
            "call",
            name,
            distinct,
            tuple(_norm_expr(item, scope, item_aliases) for item in arguments),
        )
    if kind == "bin":
        return _norm_binary(node, scope, item_aliases)
    if kind in ("and", "or"):
        parts_out: list[_Node] = []
        for part in node[1]:
            normalised = _norm_expr(part, scope, item_aliases)
            if normalised[0] == kind:
                parts_out.extend(normalised[1])
            else:
                parts_out.append(normalised)
        unique = _sorted_set(parts_out)
        if len(unique) == 1:
            return unique[0]
        return (kind, unique)
    if kind == "not":
        return ("not", _norm_expr(node[1], scope, item_aliases))
    if kind == "neg":
        return ("neg", _norm_expr(node[1], scope, item_aliases))
    if kind == "in":
        _, negated, left, right = node
        if right[0] == "sub":
            target: _Node = ("sub", _norm_query(right[1], scope))
        else:
            target = (
                "list",
                _sorted_set(_norm_expr(item, scope, item_aliases) for item in right[1]),
            )
        return ("in", negated, _norm_expr(left, scope, item_aliases), target)
    if kind == "like":
        _, word, negated, left, pattern, escape = node
        return (
            "like",
            word,
            negated,
            _norm_expr(left, scope, item_aliases),
            _norm_expr(pattern, scope, item_aliases),
            None if escape is None else _norm_expr(escape, scope, item_aliases),
        )
    if kind == "between":
        _, negated, left, low, high = node
        return (
            "between",
            negated,
            _norm_expr(left, scope, item_aliases),
            _norm_expr(low, scope, item_aliases),
            _norm_expr(high, scope, item_aliases),
        )
    if kind == "is":
        _, negated, left, right = node
        operands = _sorted(
            (
                _norm_expr(left, scope, item_aliases),
                _norm_expr(right, scope, item_aliases),
            )
        )
        return ("is", negated, operands)
    if kind == "exists":
        return ("exists", _norm_query(node[1], scope))
    if kind == "sub":
        return ("sub", _norm_query(node[1], scope))
    if kind == "row":
        return (
            "row",
            tuple(_norm_expr(item, scope, item_aliases) for item in node[1]),
        )
    if kind == "cast":
        return ("cast", _norm_expr(node[1], scope, item_aliases), node[2])
    if kind == "case":
        _, operand, branches, fallback = node
        return (
            "case",
            None if operand is None else _norm_expr(operand, scope, item_aliases),
            tuple(
                (
                    _norm_expr(test, scope, item_aliases),
                    _norm_expr(result, scope, item_aliases),
                )
                for test, result in branches
            ),
            None if fallback is None else _norm_expr(fallback, scope, item_aliases),
        )
    raise _SqlSyntaxError(f"unsupported expression node {kind!r}")


def _norm_binary(node: _Node, scope: dict, item_aliases: dict) -> _Node:
    _, symbol, left, right = node
    left_sig = _norm_expr(left, scope, item_aliases)
    right_sig = _norm_expr(right, scope, item_aliases)
    if symbol in _SYMMETRIC or symbol in _COMMUTATIVE:
        return ("op", symbol, _sorted((left_sig, right_sig)))
    if symbol in _MIRRORED:
        return ("op", _MIRRORED[symbol], (right_sig, left_sig))
    return ("op", symbol, (left_sig, right_sig))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _flat_text(text: str) -> str:
    """A whitespace-collapsed form, used only to tag unreadable input."""
    return " ".join(text.split())


def structural_signature(sql: object) -> tuple:
    """Return the canonical structure of ``sql`` as a nested tuple.

    The result is hashable and stable: the same string always gives the same
    tuple, in this process and in any other. Two SQL strings that differ only
    in the ways listed in the module docstring give equal tuples.

    A string the grammar cannot read gives ``("unparsed", <flattened text>)``
    instead of a structure. That keeps the function total and keeps the value
    a useful key, but it is never treated as a match: ``structural_match``
    returns ``0.0`` whenever either side carries that tag, even if the two
    unreadable strings are identical.

    ``sql`` may be any object. A non-string is passed through ``str()``, and
    if that object's ``__str__`` raises, the error is allowed to propagate
    rather than being turned into a silent non-match.
    """
    text = sql if isinstance(sql, str) else str(sql)
    try:
        tokens = _tokens(_strip_fence(text))
        if not tokens:
            raise _SqlSyntaxError("no statement")
        return _norm_query(_Parser(tokens).parse(), {})
    except _SqlSyntaxError:
        return (_UNPARSED, _flat_text(text))
    except RecursionError:
        return (_UNPARSED, _flat_text(text))


def structural_match(candidate: object, expected: object) -> float:
    """Score ``candidate`` against ``expected`` by structure alone.

    Returns ``1.0`` when the two structural signatures are equal and ``0.0``
    otherwise. Either side failing to read as a SELECT statement is a ``0.0``,
    never an error and never an accidental agreement.
    """
    left = structural_signature(candidate)
    right = structural_signature(expected)
    if not left or not right:
        return 0.0
    if left[0] == _UNPARSED or right[0] == _UNPARSED:
        return 0.0
    return 1.0 if left == right else 0.0

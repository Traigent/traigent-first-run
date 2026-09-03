"""The shipped structural SQL comparator, and the corpus it is measured on.

`skills/traigent-first-run/assets/sql_structure.py` is handed to a customer's
project by the route in `references/evaluation-and-dataset.md`, and
`readiness.py` credits `--evaluator-method sql-structure` only for an
evaluator that delegates to an unchanged copy of it. So what that file scores
is what the credit means, and it is pinned here rather than trusted.

The corpus below is the module's measurement, carried in the repository so the
numbers in the pull request can be re-derived. Every pair is labelled by a
human-obvious ground truth, and the labels are the three the measurement
needs:

Labelled corpus of SQL query pairs for measuring `sql_structure`.

Every pair carries a human-obvious ground truth label:

``equivalent``
    The two queries mean the same thing. A perfect comparator returns 1.0.
``different``
    The two queries mean different things. A perfect comparator returns 0.0,
    and a 1.0 here is the dangerous direction: it silently grades a wrong
    answer as correct.
``schema-dependent``
    Whether the two mean the same thing cannot be decided from the text
    alone. A schema-aware reference metric resolves it with a catalog; a
    schema-free comparator cannot, and reports a difference. Each of these
    carries the answer a schema-aware comparator would give, under the toy
    schema below, so the divergence is stated rather than hidden.

Toy schema assumed by the schema-dependent cases::

    orders(id, customer_id, amount, status, created_at)
    customers(id, name, country)
    products(id, name, price)
    employee(id, name, manager_id)

Fields per case: ``cid`` stable id, ``label``, ``left``, ``right``, ``note``
(why the label is what it is), and for schema-dependent cases ``aware`` (what
a schema-aware comparator would say: "match" or "no match").
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPARATOR = ROOT / "skills" / "traigent-first-run" / "assets" / "sql_structure.py"
_SPEC = importlib.util.spec_from_file_location("first_run_sql_structure", COMPARATOR)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

structural_match = _MODULE.structural_match
structural_signature = _MODULE.structural_signature

MODULE_SOURCE = COMPARATOR.read_text(encoding="utf-8")


CASES: tuple[dict[str, str], ...] = (
    # ------------------------------------------------------------------
    # equivalent: pure surface variation
    # ------------------------------------------------------------------
    {
        "cid": "E01",
        "label": "equivalent",
        "left": "select id from orders",
        "right": "SELECT id FROM orders",
        "note": "keyword and identifier case only",
    },
    {
        "cid": "E02",
        "label": "equivalent",
        "left": "SELECT   id,\n       amount\n  FROM   orders\n",
        "right": "SELECT id, amount FROM orders",
        "note": "whitespace and line breaks only",
    },
    {
        "cid": "E03",
        "label": "equivalent",
        "left": "SELECT id FROM orders;",
        "right": "SELECT id FROM orders",
        "note": "trailing semicolon",
    },
    {
        "cid": "E04",
        "label": "equivalent",
        "left": "```sql\nSELECT id FROM orders\n```",
        "right": "SELECT id FROM orders",
        "note": "markdown code fence with a language tag",
    },
    {
        "cid": "E05",
        "label": "equivalent",
        "left": "Here is the query:\n```\nSELECT id FROM orders\n```\nLet me know.",
        "right": "SELECT id FROM orders",
        "note": "fenced block with prose on both sides",
    },
    {
        "cid": "E06",
        "label": "equivalent",
        "left": "-- pull every order id\nSELECT id FROM orders -- one per row",
        "right": "SELECT id FROM orders",
        "note": "line comments",
    },
    {
        "cid": "E07",
        "label": "equivalent",
        "left": "SELECT /* just the id */ id FROM orders",
        "right": "SELECT id FROM orders",
        "note": "block comment",
    },
    {
        "cid": "E08",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE ((amount > 100))",
        "right": "SELECT id FROM orders WHERE amount > 100",
        "note": "redundant parentheses around a predicate",
    },
    {
        "cid": "E09",
        "label": "equivalent",
        "left": "(SELECT id FROM orders)",
        "right": "SELECT id FROM orders",
        "note": "redundant parentheses around the whole statement",
    },
    {
        "cid": "E10",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE status <> 'paid'",
        "right": "SELECT id FROM orders WHERE status != 'paid'",
        "note": "the two spellings of not-equal",
    },
    {
        "cid": "E11",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE customer_id = 7",
        "right": "SELECT id FROM orders WHERE 7 = customer_id",
        "note": "equality is symmetric, so operand order does not matter",
    },
    {
        "cid": "E12",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE amount < 100",
        "right": "SELECT id FROM orders WHERE 100 > amount",
        "note": "a < b and b > a are the same predicate",
    },
    {
        "cid": "E13",
        "label": "equivalent",
        "left": "Select Id From Orders Where Amount > 100",
        "right": "SELECT id FROM orders WHERE amount > 100",
        "note": "mixed keyword case",
    },
    {
        "cid": "E14",
        "label": "equivalent",
        "left": 'SELECT "id" FROM "orders"',
        "right": "SELECT id FROM orders",
        "note": "double quoted identifiers, no reserved word involved",
    },
    {
        "cid": "E15",
        "label": "equivalent",
        "left": "SELECT [id] FROM [orders]",
        "right": "SELECT id FROM orders",
        "note": "bracket delimited identifiers",
    },
    {
        "cid": "E16",
        "label": "equivalent",
        "left": "SELECT `id` FROM `orders`",
        "right": "SELECT id FROM orders",
        "note": "backtick delimited identifiers",
    },
    {
        "cid": "E17",
        "label": "equivalent",
        "left": "SELECT ALL amount FROM orders",
        "right": "SELECT amount FROM orders",
        "note": "SELECT ALL is the default",
    },
    {
        "cid": "E18",
        "label": "equivalent",
        "left": "SELECT id FROM orders ORDER BY amount",
        "right": "SELECT id FROM orders ORDER BY amount ASC",
        "note": "ASC is the default sort direction",
    },
    {
        "cid": "E19",
        "label": "equivalent",
        "left": (
            "SELECT c.name FROM customers c "
            "INNER JOIN orders o ON c.id = o.customer_id"
        ),
        "right": "SELECT c.name FROM customers c JOIN orders o ON c.id = o.customer_id",
        "note": "INNER is the default join kind",
    },
    {
        "cid": "E20",
        "label": "equivalent",
        "left": (
            "SELECT c.name FROM customers c "
            "LEFT OUTER JOIN orders o ON c.id = o.customer_id"
        ),
        "right": (
            "SELECT c.name FROM customers c "
            "LEFT JOIN orders o ON c.id = o.customer_id"
        ),
        "note": "OUTER is noise on a LEFT JOIN",
    },
    {
        "cid": "E21",
        "label": "equivalent",
        "left": "SELECT o.amount FROM orders AS o",
        "right": "SELECT o.amount FROM orders o",
        "note": "AS is optional before a table alias",
    },
    {
        "cid": "E22",
        "label": "equivalent",
        "left": (
            "SELECT T1.name FROM customers AS T1 "
            "JOIN orders AS T2 ON T1.id = T2.customer_id"
        ),
        "right": (
            "SELECT c.name FROM customers AS c "
            "JOIN orders AS o ON c.id = o.customer_id"
        ),
        "note": "same query, different alias spelling; each table appears once",
    },
    {
        "cid": "E23",
        "label": "equivalent",
        "left": "SELECT COUNT(*) AS total FROM orders",
        "right": "SELECT COUNT(*) FROM orders",
        "note": "an output alias does not change the rows produced",
    },
    {
        "cid": "E24",
        "label": "equivalent",
        "left": (
            "SELECT customer_id, COUNT(*) AS n FROM orders "
            "GROUP BY customer_id ORDER BY n DESC"
        ),
        "right": (
            "SELECT customer_id, COUNT(*) FROM orders "
            "GROUP BY customer_id ORDER BY COUNT(*) DESC"
        ),
        "note": "ORDER BY an alias versus ORDER BY the expression it names",
    },
    {
        "cid": "E25",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE (amount > 100) AND (status = 'paid')",
        "right": "SELECT id FROM orders WHERE amount > 100 AND status = 'paid'",
        "note": "parentheses around each conjunct",
    },
    {
        "cid": "E26",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE amount BETWEEN 10 AND 100",
        "right": "SELECT id FROM orders WHERE (amount BETWEEN 10 AND 100)",
        "note": "parenthesised BETWEEN",
    },
    # ------------------------------------------------------------------
    # equivalent: reordering that exact set match must absorb
    # ------------------------------------------------------------------
    {
        "cid": "E27",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE amount > 100 AND status = 'paid'",
        "right": "SELECT id FROM orders WHERE status = 'paid' AND amount > 100",
        "note": "AND conjuncts reordered",
    },
    {
        "cid": "E28",
        "label": "equivalent",
        "left": "SELECT id, amount, status FROM orders",
        "right": "SELECT status, id, amount FROM orders",
        "note": "select item order, which exact set match treats as a set",
    },
    {
        "cid": "E29",
        "label": "equivalent",
        "left": "SELECT c.name FROM customers c, orders o WHERE c.id = o.customer_id",
        "right": "SELECT c.name FROM orders o, customers c WHERE c.id = o.customer_id",
        "note": "table order in a comma join",
    },
    {
        "cid": "E30",
        "label": "equivalent",
        "left": "SELECT c.name FROM customers c JOIN orders o ON c.id = o.customer_id",
        "right": "SELECT c.name FROM orders o JOIN customers c ON c.id = o.customer_id",
        "note": "operand order of an inner join",
    },
    {
        "cid": "E31",
        "label": "equivalent",
        "left": (
            "SELECT customer_id, status, COUNT(*) FROM orders "
            "GROUP BY customer_id, status"
        ),
        "right": (
            "SELECT customer_id, status, COUNT(*) FROM orders "
            "GROUP BY status, customer_id"
        ),
        "note": "GROUP BY key order does not change the grouping",
    },
    {
        "cid": "E32",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE status IN ('paid', 'shipped')",
        "right": "SELECT id FROM orders WHERE status IN ('shipped', 'paid')",
        "note": "IN list order",
    },
    {
        "cid": "E33",
        "label": "equivalent",
        "left": (
            "SELECT c.name FROM customers c JOIN orders o "
            "ON c.id = o.customer_id AND o.status = 'paid'"
        ),
        "right": (
            "SELECT c.name FROM customers c JOIN orders o "
            "ON o.status = 'paid' AND c.id = o.customer_id"
        ),
        "note": "ON conjunct order",
    },
    {
        "cid": "E34",
        "label": "equivalent",
        "left": (
            "SELECT c.name FROM customers c JOIN orders o "
            "ON c.id = o.customer_id WHERE o.amount > 100"
        ),
        "right": (
            "SELECT c.name FROM customers c, orders o "
            "WHERE c.id = o.customer_id AND o.amount > 100"
        ),
        "note": "for an inner join the ON and WHERE conjuncts are one predicate",
    },
    {
        "cid": "E35",
        "label": "equivalent",
        "left": "SELECT name FROM customers UNION SELECT name FROM products",
        "right": "SELECT name FROM products UNION SELECT name FROM customers",
        "note": "UNION is commutative",
    },
    {
        "cid": "E36",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE status = 'paid' OR status = 'shipped'",
        "right": "SELECT id FROM orders WHERE status = 'shipped' OR status = 'paid'",
        "note": "OR is commutative",
    },
    {
        "cid": "E37",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE (amount > 1 AND amount < 9) AND status = 'x'",
        "right": "SELECT id FROM orders WHERE amount > 1 AND (amount < 9 AND status = 'x')",
        "note": "AND is associative",
    },
    {
        "cid": "E38",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE amount > 100 AND amount > 100",
        "right": "SELECT id FROM orders WHERE amount > 100",
        "note": "a repeated conjunct adds nothing",
    },
    {
        "cid": "E39",
        "label": "equivalent",
        "left": "SELECT amount + 1 FROM orders",
        "right": "SELECT 1 + amount FROM orders",
        "note": "addition is commutative",
    },
    {
        "cid": "E40",
        "label": "equivalent",
        "left": (
            "WITH paid AS (SELECT * FROM orders WHERE status = 'paid'), "
            "big AS (SELECT * FROM orders WHERE amount > 100) "
            "SELECT COUNT(*) FROM paid"
        ),
        "right": (
            "WITH big AS (SELECT * FROM orders WHERE amount > 100), "
            "paid AS (SELECT * FROM orders WHERE status = 'paid') "
            "SELECT COUNT(*) FROM paid"
        ),
        "note": "order of non-recursive CTE definitions",
    },
    {
        "cid": "E41",
        "label": "equivalent",
        "left": (
            "SELECT c.name FROM customers c WHERE c.id IN "
            "(SELECT o.customer_id FROM orders o WHERE o.amount > 100)"
        ),
        "right": (
            "SELECT c.name FROM customers AS c WHERE c.id IN "
            "(SELECT x.customer_id FROM orders AS x WHERE 100 < x.amount)"
        ),
        "note": "subquery with a renamed alias and a mirrored comparison",
    },
    {
        "cid": "E42",
        "label": "equivalent",
        "left": "SELECT DISTINCT country FROM customers ORDER BY country",
        "right": "select distinct country from customers order by country asc;",
        "note": "case, semicolon and the default sort direction together",
    },
    {
        "cid": "E43",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE created_at IS NOT NULL",
        "right": "SELECT id FROM orders WHERE (created_at) IS NOT NULL",
        "note": "parenthesised operand of IS NOT NULL",
    },
    # ------------------------------------------------------------------
    # equivalent, but semantic rather than structural: expected misses
    # ------------------------------------------------------------------
    {
        "cid": "E44",
        "label": "equivalent",
        "left": "SELECT COUNT(*) FROM orders",
        "right": "SELECT COUNT(1) FROM orders",
        "note": "same count, different argument text; semantic, not structural",
    },
    {
        "cid": "E45",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE status IN ('paid', 'shipped')",
        "right": "SELECT id FROM orders WHERE status = 'paid' OR status = 'shipped'",
        "note": "IN expanded to an OR chain; semantic, not structural",
    },
    {
        "cid": "E46",
        "label": "equivalent",
        "left": "SELECT id FROM orders WHERE NOT (amount > 100)",
        "right": "SELECT id FROM orders WHERE amount <= 100",
        "note": "negation pushed into the comparison; semantic, not structural",
    },
    # ------------------------------------------------------------------
    # different: must not match
    # ------------------------------------------------------------------
    {
        "cid": "D01",
        "label": "different",
        "left": "SELECT id FROM orders",
        "right": "SELECT id FROM customers",
        "note": "different table",
    },
    {
        "cid": "D02",
        "label": "different",
        "left": "SELECT amount FROM orders",
        "right": "SELECT status FROM orders",
        "note": "different column",
    },
    {
        "cid": "D03",
        "label": "different",
        "left": "SELECT COUNT(amount) FROM orders",
        "right": "SELECT SUM(amount) FROM orders",
        "note": "different aggregate",
    },
    {
        "cid": "D04",
        "label": "different",
        "left": "SELECT id FROM orders WHERE amount > 100",
        "right": "SELECT id FROM orders WHERE amount >= 100",
        "note": "strict versus non-strict comparison",
    },
    {
        "cid": "D05",
        "label": "different",
        "left": "SELECT DISTINCT country FROM customers",
        "right": "SELECT country FROM customers",
        "note": "missing DISTINCT",
    },
    {
        "cid": "D06",
        "label": "different",
        "left": "SELECT country, COUNT(*) FROM customers GROUP BY country",
        "right": "SELECT country, COUNT(*) FROM customers",
        "note": "missing GROUP BY",
    },
    {
        "cid": "D07",
        "label": "different",
        "left": "SELECT id FROM orders ORDER BY amount ASC",
        "right": "SELECT id FROM orders ORDER BY amount DESC",
        "note": "different sort direction",
    },
    {
        "cid": "D08",
        "label": "different",
        "left": "SELECT id FROM orders ORDER BY amount DESC LIMIT 5",
        "right": "SELECT id FROM orders ORDER BY amount DESC LIMIT 10",
        "note": "different LIMIT",
    },
    {
        "cid": "D09",
        "label": "different",
        "left": "SELECT c.name FROM customers c JOIN orders o ON c.id = o.customer_id",
        "right": (
            "SELECT c.name FROM customers c JOIN orders o ON c.id = o.customer_id "
            "JOIN products p ON p.id = o.id"
        ),
        "note": "an extra join changes the row set",
    },
    {
        "cid": "D10",
        "label": "different",
        "left": "SELECT c.name FROM customers c JOIN orders o ON c.id = o.customer_id",
        "right": "SELECT name FROM customers",
        "note": "the join is gone",
    },
    {
        "cid": "D11",
        "label": "different",
        "left": "SELECT name FROM customers WHERE id IN (SELECT customer_id FROM orders)",
        "right": (
            "SELECT name FROM customers WHERE id IN (SELECT customer_id FROM products)"
        ),
        "note": "the subquery reads a different table",
    },
    {
        "cid": "D12",
        "label": "different",
        "left": "SELECT id FROM orders WHERE status IN ('paid')",
        "right": "SELECT id FROM orders WHERE status NOT IN ('paid')",
        "note": "IN versus NOT IN",
    },
    {
        "cid": "D13",
        "label": "different",
        "left": "SELECT id FROM orders WHERE amount > 100 AND status = 'paid'",
        "right": "SELECT id FROM orders WHERE amount > 100 OR status = 'paid'",
        "note": "AND versus OR",
    },
    {
        "cid": "D14",
        "label": "different",
        "left": "SELECT id FROM orders WHERE amount > 100",
        "right": "SELECT id FROM orders WHERE amount > 1000",
        "note": "different literal value",
    },
    {
        "cid": "D15",
        "label": "different",
        "left": "SELECT id FROM customers WHERE name = 'Bob'",
        "right": "SELECT id FROM customers WHERE name = 'bob'",
        "note": "string literals are case sensitive",
    },
    {
        "cid": "D16",
        "label": "different",
        "left": (
            "SELECT c.name FROM customers c "
            "LEFT JOIN orders o ON c.id = o.customer_id"
        ),
        "right": "SELECT c.name FROM customers c JOIN orders o ON c.id = o.customer_id",
        "note": "LEFT JOIN keeps customers with no orders, INNER JOIN does not",
    },
    {
        "cid": "D17",
        "label": "different",
        "left": (
            "SELECT c.name FROM customers c "
            "LEFT JOIN orders o ON c.id = o.customer_id"
        ),
        "right": (
            "SELECT c.name FROM orders o "
            "LEFT JOIN customers c ON c.id = o.customer_id"
        ),
        "note": "an outer join is not commutative",
    },
    {
        "cid": "D18",
        "label": "different",
        "left": "SELECT name FROM customers UNION SELECT name FROM products",
        "right": "SELECT name FROM customers UNION ALL SELECT name FROM products",
        "note": "UNION removes duplicates, UNION ALL keeps them",
    },
    {
        "cid": "D19",
        "label": "different",
        "left": "SELECT name FROM customers EXCEPT SELECT name FROM products",
        "right": "SELECT name FROM products EXCEPT SELECT name FROM customers",
        "note": "EXCEPT is not commutative",
    },
    {
        "cid": "D20",
        "label": "different",
        "left": "SELECT id FROM orders ORDER BY amount",
        "right": "SELECT id FROM orders ORDER BY created_at",
        "note": "different sort key",
    },
    {
        "cid": "D21",
        "label": "different",
        "left": "SELECT id FROM orders ORDER BY amount DESC LIMIT 1",
        "right": "SELECT id FROM orders ORDER BY amount DESC",
        "note": "LIMIT present versus absent",
    },
    {
        "cid": "D22",
        "label": "different",
        "left": (
            "SELECT country, COUNT(*) FROM customers "
            "GROUP BY country HAVING COUNT(*) > 5"
        ),
        "right": "SELECT country, COUNT(*) FROM customers GROUP BY country",
        "note": "HAVING present versus absent",
    },
    {
        "cid": "D23",
        "label": "different",
        "left": "SELECT MAX(amount) FROM orders",
        "right": "SELECT MAX(created_at) FROM orders",
        "note": "different aggregate argument",
    },
    {
        "cid": "D24",
        "label": "different",
        "left": "SELECT COUNT(*) FROM orders",
        "right": "SELECT COUNT(DISTINCT customer_id) FROM orders",
        "note": "COUNT(*) is not COUNT(DISTINCT column)",
    },
    {
        "cid": "D25",
        "label": "different",
        "left": "SELECT id FROM orders ORDER BY id LIMIT 10 OFFSET 0",
        "right": "SELECT id FROM orders ORDER BY id LIMIT 10 OFFSET 10",
        "note": "different OFFSET",
    },
    {
        "cid": "D26",
        "label": "different",
        "left": "SELECT id, amount FROM orders",
        "right": "SELECT id FROM orders",
        "note": "an extra select item",
    },
    {
        "cid": "D27",
        "label": "different",
        "left": "SELECT id FROM orders WHERE amount < created_at",
        "right": "SELECT id FROM orders WHERE created_at < amount",
        "note": "the asymmetric comparison is reversed",
    },
    {
        "cid": "D28",
        "label": "different",
        "left": (
            "SELECT e1.name FROM employee e1 "
            "JOIN employee e2 ON e1.manager_id = e2.id"
        ),
        "right": (
            "SELECT e2.name FROM employee e1 "
            "JOIN employee e2 ON e1.manager_id = e2.id"
        ),
        "note": "self join: the report versus the manager",
    },
    {
        "cid": "D29",
        "label": "different",
        "left": "SELECT country, COUNT(*) FROM customers GROUP BY country",
        "right": "SELECT country, COUNT(*) FROM customers GROUP BY name",
        "note": "different grouping key",
    },
    {
        "cid": "D30",
        "label": "different",
        "left": "SELECT (SELECT MAX(amount) FROM orders) FROM customers",
        "right": "SELECT (SELECT MIN(amount) FROM orders) FROM customers",
        "note": "different aggregate inside a scalar subquery",
    },
    {
        "cid": "D31",
        "label": "different",
        "left": (
            "SELECT name FROM customers c WHERE EXISTS "
            "(SELECT 1 FROM orders o WHERE o.customer_id = c.id)"
        ),
        "right": (
            "SELECT name FROM customers c WHERE NOT EXISTS "
            "(SELECT 1 FROM orders o WHERE o.customer_id = c.id)"
        ),
        "note": "EXISTS versus NOT EXISTS",
    },
    {
        "cid": "D32",
        "label": "different",
        "left": "SELECT c.name FROM customers c JOIN orders o ON c.id = o.customer_id",
        "right": "SELECT c.name FROM customers c JOIN orders o ON c.id = o.id",
        "note": "the join is on a different column",
    },
    {
        "cid": "D33",
        "label": "different",
        "left": "SELECT id FROM orders WHERE amount BETWEEN 10 AND 100",
        "right": "SELECT id FROM orders WHERE amount BETWEEN 100 AND 10",
        "note": "BETWEEN bounds are ordered",
    },
    {
        "cid": "D34",
        "label": "different",
        "left": "SELECT name FROM customers WHERE name LIKE 'A%'",
        "right": "SELECT name FROM customers WHERE name LIKE '%A'",
        "note": "different LIKE pattern",
    },
    {
        "cid": "D35",
        "label": "different",
        "left": "SELECT amount / 2 FROM orders",
        "right": "SELECT 2 / amount FROM orders",
        "note": "division is not commutative",
    },
    {
        "cid": "D36",
        "label": "different",
        "left": "SELECT id FROM orders WHERE (a OR b) AND c",
        "right": "SELECT id FROM orders WHERE a OR (b AND c)",
        "note": "AND and OR nesting changes the predicate",
    },
    # ------------------------------------------------------------------
    # schema-dependent: undecidable without a catalog
    # ------------------------------------------------------------------
    {
        "cid": "S01",
        "label": "schema-dependent",
        "left": "SELECT amount FROM orders",
        "right": "SELECT orders.amount FROM orders",
        "aware": "match",
        "note": (
            "an unqualified name can only be attributed to a table with a "
            "catalog; with the toy schema both name orders.amount"
        ),
    },
    {
        "cid": "S02",
        "label": "schema-dependent",
        "left": "SELECT * FROM customers",
        "right": "SELECT id, name, country FROM customers",
        "aware": "match",
        "note": (
            "the star expands to the table's column list, which only a "
            "catalog knows; under the toy schema they are the same three"
        ),
    },
    {
        "cid": "S03",
        "label": "schema-dependent",
        "left": "SELECT customers.name FROM customers JOIN orders USING (id)",
        "right": (
            "SELECT customers.name FROM customers "
            "JOIN orders ON customers.id = orders.id"
        ),
        "aware": "match",
        "note": (
            "USING (id) is the predicate customers.id = orders.id, but only "
            "a catalog says which tables own an id column"
        ),
    },
    {
        "cid": "S04",
        "label": "schema-dependent",
        "left": "SELECT COUNT(*) FROM customers NATURAL JOIN orders",
        "right": "SELECT COUNT(*) FROM customers JOIN orders ON customers.id = orders.id",
        "aware": "match",
        "note": (
            "NATURAL JOIN equates every shared column name; which ones "
            "those are is a fact about the schema, here just id"
        ),
    },
    {
        "cid": "S05",
        "label": "schema-dependent",
        "left": (
            "SELECT o.amount FROM orders o JOIN customers c " "ON o.customer_id = c.id"
        ),
        "right": (
            "SELECT amount FROM orders JOIN customers " "ON customer_id = customers.id"
        ),
        "aware": "match",
        "note": (
            "one side qualifies through an alias, the other leaves names "
            "bare; attributing the bare names needs the catalog"
        ),
    },
    {
        "cid": "S06",
        "label": "schema-dependent",
        "left": "SELECT * FROM orders o",
        "right": "SELECT o.* FROM orders o",
        "aware": "match",
        "note": (
            "with one table in scope the bare star and the qualified star "
            "cover the same columns, but that is a fact about the scope"
        ),
    },
    {
        "cid": "S07",
        "label": "schema-dependent",
        "left": "SELECT COUNT(*) FROM customers c JOIN orders o ON c.id = o.customer_id",
        "right": "SELECT COUNT(*) FROM customers JOIN orders ON id = customer_id",
        "aware": "match",
        "note": "the ON columns are unqualified on one side only",
    },
    {
        "cid": "S08",
        "label": "schema-dependent",
        "left": "SELECT country, COUNT(*) FROM customers GROUP BY country",
        "right": (
            "SELECT customers.country, COUNT(*) FROM customers "
            "GROUP BY customers.country"
        ),
        "aware": "match",
        "note": "the same qualification question in the select and group lists",
    },
    {
        "cid": "S09",
        "label": "schema-dependent",
        "left": ("SELECT s.total FROM (SELECT SUM(amount) AS total FROM orders) AS s"),
        "right": ("SELECT d.total FROM (SELECT SUM(amount) AS total FROM orders) AS d"),
        "aware": "match",
        "note": (
            "a derived table alias is a binding, not a table name, so it "
            "cannot be resolved away the way a base table alias can"
        ),
    },
    {
        "cid": "S10",
        "label": "schema-dependent",
        "left": "SELECT name FROM customers WHERE country = 'US'",
        "right": "SELECT customers.name FROM customers WHERE customers.country = 'US'",
        "aware": "match",
        "note": "fully qualified against fully bare, in both clauses",
    },
)


class Corpus(unittest.TestCase):
    """Every labelled pair scores what its label says it should."""

    def test_equivalent_pairs_match(self) -> None:
        misses = []
        for case in CASES:
            if case["label"] != "equivalent":
                continue
            with self.subTest(cid=case["cid"], note=case["note"]):
                score = structural_match(case["left"], case["right"])
                if score != 1.0:
                    misses.append(case["cid"])
        # E44, E45 and E46 are equivalences that are semantic rather than
        # structural. They are in the corpus on purpose, and they are the
        # only ones a purely structural comparator is allowed to miss.
        self.assertEqual(misses, ["E44", "E45", "E46"])

    def test_different_pairs_never_match(self) -> None:
        """The dangerous direction: a wrong query graded as right."""
        for case in CASES:
            if case["label"] != "different":
                continue
            with self.subTest(cid=case["cid"], note=case["note"]):
                self.assertEqual(
                    structural_match(case["left"], case["right"]),
                    0.0,
                    f"{case['cid']} is a false 1.0",
                )

    def test_schema_dependent_pairs_stay_conservative(self) -> None:
        """Undecidable without a catalog, so the answer must be no match."""
        for case in CASES:
            if case["label"] != "schema-dependent":
                continue
            with self.subTest(cid=case["cid"], note=case["note"]):
                self.assertEqual(
                    structural_match(case["left"], case["right"]),
                    0.0,
                    f"{case['cid']} guessed an identity it cannot check",
                )

    def test_every_corpus_query_matches_itself(self) -> None:
        for case in CASES:
            for side in ("left", "right"):
                with self.subTest(cid=case["cid"], side=side):
                    query = case[side]
                    self.assertEqual(structural_match(query, query), 1.0)

    def test_corpus_labels_are_known(self) -> None:
        allowed = {"equivalent", "different", "schema-dependent"}
        ids = [case["cid"] for case in CASES]
        self.assertEqual(len(ids), len(set(ids)), "duplicate case id")
        self.assertGreaterEqual(len(CASES), 60)
        for case in CASES:
            self.assertIn(case["label"], allowed)
            if case["label"] == "schema-dependent":
                self.assertIn(case["aware"], {"match", "no match"})


class Lexing(unittest.TestCase):
    """The parts a general-purpose word tokenizer gets wrong."""

    def assertSame(self, left: str, right: str) -> None:
        self.assertEqual(structural_match(left, right), 1.0, f"{left!r} vs {right!r}")

    def assertDiffers(self, left: str, right: str) -> None:
        self.assertEqual(structural_match(left, right), 0.0, f"{left!r} vs {right!r}")

    # -- string literals --------------------------------------------------

    def test_doubled_quote_inside_a_string(self) -> None:
        self.assertSame(
            "SELECT id FROM t WHERE n = 'it''s'", "select id from t where n='it''s'"
        )
        self.assertDiffers(
            "SELECT id FROM t WHERE n = 'it''s'",
            "SELECT id FROM t WHERE n = 'its'",
        )

    def test_string_literals_keep_their_case(self) -> None:
        self.assertDiffers(
            "SELECT id FROM t WHERE n = 'Bob'",
            "SELECT id FROM t WHERE n = 'bob'",
        )

    def test_keywords_inside_a_string_are_not_keywords(self) -> None:
        self.assertSame(
            "SELECT id FROM t WHERE n = 'SELECT FROM WHERE'",
            "select id from t where n = 'SELECT FROM WHERE'",
        )

    def test_a_comment_marker_inside_a_string_is_data(self) -> None:
        self.assertSame(
            "SELECT id FROM t WHERE n = '-- not a comment'",
            "SELECT id FROM t WHERE n = '-- not a comment'",
        )
        self.assertDiffers(
            "SELECT id FROM t WHERE n = '-- not a comment'",
            "SELECT id FROM t WHERE n = ''",
        )

    def test_unterminated_string_is_unreadable(self) -> None:
        self.assertEqual(structural_signature("SELECT 'abc FROM t")[0], "unparsed")

    # -- delimited identifiers -------------------------------------------

    def test_three_identifier_delimiters_agree(self) -> None:
        self.assertSame('SELECT "id" FROM "t"', "SELECT id FROM t")
        self.assertSame("SELECT [id] FROM [t]", "SELECT id FROM t")
        self.assertSame("SELECT `id` FROM `t`", "SELECT id FROM t")

    def test_doubled_quote_inside_an_identifier(self) -> None:
        self.assertSame('SELECT "a""b" FROM t', 'SELECT "a""b" FROM t')
        self.assertDiffers('SELECT "a""b" FROM t', 'SELECT "ab" FROM t')

    def test_delimited_identifier_holding_a_reserved_word(self) -> None:
        self.assertSame('SELECT "order" FROM t', "SELECT [order] FROM t")
        self.assertEqual(structural_signature("SELECT order FROM t")[0], "unparsed")

    def test_identifiers_fold_to_lower_case(self) -> None:
        self.assertSame("SELECT ID FROM T", 'select "id" from "t"')

    def test_unterminated_bracket_identifier_is_unreadable(self) -> None:
        self.assertEqual(structural_signature("SELECT [id FROM t")[0], "unparsed")

    # -- comments ---------------------------------------------------------

    def test_line_comment_runs_to_end_of_line(self) -> None:
        self.assertSame("SELECT id -- comment\nFROM t", "SELECT id FROM t")

    def test_line_comment_at_end_of_input(self) -> None:
        self.assertSame("SELECT id FROM t -- trailing", "SELECT id FROM t")

    def test_block_comment_anywhere(self) -> None:
        self.assertSame("SELECT /* a */ id /* b */ FROM /* c */ t", "SELECT id FROM t")

    def test_multiline_block_comment(self) -> None:
        self.assertSame("SELECT id\n/* one\n   two */\nFROM t", "SELECT id FROM t")

    def test_unterminated_block_comment_is_unreadable(self) -> None:
        self.assertEqual(
            structural_signature("SELECT id FROM t /* open")[0], "unparsed"
        )

    # -- numbers ----------------------------------------------------------

    def test_number_forms_read(self) -> None:
        for literal in ("1", "1.5", ".5", "1e3", "1E3", "1.5e-3", "0x1f", "0X1F"):
            with self.subTest(literal=literal):
                signature = structural_signature(f"SELECT {literal} FROM t")
                self.assertNotEqual(signature[0], "unparsed")

    def test_exponent_and_hex_case_fold(self) -> None:
        self.assertSame("SELECT 1e3 FROM t", "SELECT 1E3 FROM t")
        self.assertSame("SELECT 0x1f FROM t", "SELECT 0X1F FROM t")

    def test_numeric_text_is_not_normalised(self) -> None:
        self.assertDiffers("SELECT 1.5 FROM t", "SELECT 1.50 FROM t")

    def test_decimal_point_is_not_a_qualifier(self) -> None:
        self.assertSame("SELECT amount*1.5 FROM t", "SELECT 1.5 * amount FROM t")

    # -- operators and punctuation ---------------------------------------

    def test_multi_character_operators(self) -> None:
        self.assertSame("SELECT id FROM t WHERE a<=1", "SELECT id FROM t WHERE a <= 1")
        self.assertSame("SELECT id FROM t WHERE a>=1", "SELECT id FROM t WHERE a >= 1")
        self.assertSame("SELECT id FROM t WHERE a<>1", "SELECT id FROM t WHERE a != 1")
        self.assertSame("SELECT a||b FROM t", "SELECT a || b FROM t")

    def test_less_than_is_not_swallowed_by_less_or_equal(self) -> None:
        self.assertDiffers(
            "SELECT id FROM t WHERE a < 1", "SELECT id FROM t WHERE a <= 1"
        )

    def test_concatenation_is_not_commutative(self) -> None:
        self.assertDiffers("SELECT a || b FROM t", "SELECT b || a FROM t")

    def test_cast_operator_and_cast_call_agree(self) -> None:
        self.assertSame(
            "SELECT amount::int FROM t", "SELECT CAST(amount AS INT) FROM t"
        )

    def test_star_is_not_multiplication(self) -> None:
        self.assertDiffers("SELECT * FROM t", "SELECT a * b FROM t")

    def test_unknown_character_is_unreadable(self) -> None:
        self.assertEqual(structural_signature("SELECT id ~ 1 FROM t")[0], "unparsed")

    # -- input shaping ----------------------------------------------------

    def test_fence_with_a_language_tag(self) -> None:
        self.assertSame("```sql\nSELECT id FROM t\n```", "SELECT id FROM t")

    def test_fence_without_a_language_tag(self) -> None:
        self.assertSame("```\nSELECT id FROM t\n```", "SELECT id FROM t")

    def test_tilde_fence(self) -> None:
        self.assertSame("~~~sql\nSELECT id FROM t\n~~~", "SELECT id FROM t")

    def test_single_line_fence_with_a_tag(self) -> None:
        self.assertSame("```sql SELECT id FROM t```", "SELECT id FROM t")

    def test_single_line_fence_without_a_tag(self) -> None:
        self.assertSame("```SELECT id FROM t```", "SELECT id FROM t")

    def test_fence_surrounded_by_prose(self) -> None:
        self.assertSame(
            "Sure. Here is the query:\n\n```sql\nSELECT id FROM t\n```\n\nHope it helps.",
            "SELECT id FROM t",
        )

    def test_unclosed_fence(self) -> None:
        self.assertSame("```sql\nSELECT id FROM t", "SELECT id FROM t")

    def test_trailing_semicolon_and_surrounding_whitespace(self) -> None:
        self.assertSame("\n\n  SELECT id FROM t ;  \n", "SELECT id FROM t")

    def test_two_statements_are_unreadable(self) -> None:
        self.assertEqual(
            structural_signature("SELECT id FROM t; SELECT id FROM u")[0],
            "unparsed",
        )


class Structure(unittest.TestCase):
    """Clause-level normalisation beyond what the corpus already covers."""

    def assertSame(self, left: str, right: str) -> None:
        self.assertEqual(structural_match(left, right), 1.0, f"{left!r} vs {right!r}")

    def assertDiffers(self, left: str, right: str) -> None:
        self.assertEqual(structural_match(left, right), 0.0, f"{left!r} vs {right!r}")

    def test_select_list_is_a_multiset_not_a_set(self) -> None:
        self.assertDiffers("SELECT a, a FROM t", "SELECT a FROM t")

    def test_aggregate_distinct_is_carried(self) -> None:
        self.assertDiffers("SELECT COUNT(x) FROM t", "SELECT COUNT(DISTINCT x) FROM t")
        self.assertSame(
            "SELECT count(distinct x) FROM t", "SELECT COUNT(DISTINCT x) FROM t"
        )

    def test_order_by_is_ordered(self) -> None:
        self.assertDiffers(
            "SELECT a FROM t ORDER BY a, b", "SELECT a FROM t ORDER BY b, a"
        )

    def test_nulls_ordering_is_carried(self) -> None:
        self.assertDiffers(
            "SELECT a FROM t ORDER BY a NULLS FIRST",
            "SELECT a FROM t ORDER BY a NULLS LAST",
        )

    def test_mysql_limit_offset_shorthand(self) -> None:
        self.assertSame(
            "SELECT a FROM t ORDER BY a LIMIT 5, 10",
            "SELECT a FROM t ORDER BY a LIMIT 10 OFFSET 5",
        )

    def test_and_or_nesting_is_kept(self) -> None:
        self.assertDiffers(
            "SELECT a FROM t WHERE p AND (q OR r)",
            "SELECT a FROM t WHERE (p AND q) OR r",
        )

    def test_or_operands_are_a_set_at_their_own_level(self) -> None:
        self.assertSame(
            "SELECT a FROM t WHERE p OR q OR r",
            "SELECT a FROM t WHERE r OR q OR p",
        )

    def test_intersect_is_commutative_and_except_is_not(self) -> None:
        self.assertSame(
            "SELECT a FROM t INTERSECT SELECT a FROM u",
            "SELECT a FROM u INTERSECT SELECT a FROM t",
        )
        self.assertDiffers(
            "SELECT a FROM t EXCEPT SELECT a FROM u",
            "SELECT a FROM u EXCEPT SELECT a FROM t",
        )

    def test_union_chain_flattens(self) -> None:
        self.assertSame(
            "SELECT a FROM t UNION SELECT a FROM u UNION SELECT a FROM v",
            "SELECT a FROM v UNION SELECT a FROM t UNION SELECT a FROM u",
        )

    def test_union_all_does_not_merge_with_union(self) -> None:
        self.assertDiffers(
            "SELECT a FROM t UNION SELECT a FROM u",
            "SELECT a FROM t UNION ALL SELECT a FROM u",
        )

    def test_right_join_folds_to_left_join(self) -> None:
        self.assertSame(
            "SELECT * FROM a RIGHT JOIN b ON a.i = b.i",
            "SELECT * FROM b LEFT JOIN a ON a.i = b.i",
        )

    def test_outer_join_operand_order_is_kept(self) -> None:
        self.assertDiffers(
            "SELECT * FROM a LEFT JOIN b ON a.i = b.i",
            "SELECT * FROM b LEFT JOIN a ON a.i = b.i",
        )

    def test_using_join_is_never_folded_into_a_table_set(self) -> None:
        """The guard that stops a USING join from producing a false 1.0."""
        self.assertDiffers(
            "SELECT * FROM a JOIN b USING (i), c",
            "SELECT * FROM a JOIN c USING (i), b",
        )

    def test_natural_join_operands_are_kept_together(self) -> None:
        self.assertDiffers(
            "SELECT * FROM a NATURAL JOIN b, c",
            "SELECT * FROM a NATURAL JOIN c, b",
        )

    def test_self_join_aliases_are_not_resolved(self) -> None:
        """Resolving these would merge two distinct references to one table."""
        self.assertDiffers(
            "SELECT e1.n FROM emp e1 JOIN emp e2 ON e1.m = e2.i",
            "SELECT e2.n FROM emp e1 JOIN emp e2 ON e1.m = e2.i",
        )

    def test_self_join_arms_are_not_interchangeable(self) -> None:
        self.assertDiffers(
            "SELECT e1.n FROM emp e1 JOIN emp e2 ON e1.m = e2.i",
            "SELECT e1.n FROM emp e1 JOIN emp e2 ON e2.m = e1.i",
        )

    def test_correlated_subquery_uses_the_outer_alias(self) -> None:
        self.assertSame(
            "SELECT c.n FROM cust c WHERE EXISTS "
            "(SELECT 1 FROM ord o WHERE o.cid = c.i)",
            "SELECT x.n FROM cust x WHERE EXISTS "
            "(SELECT 1 FROM ord y WHERE y.cid = x.i)",
        )

    def test_inner_subquery_alias_shadows_the_outer_one(self) -> None:
        self.assertDiffers(
            "SELECT o.a FROM ord o WHERE o.i IN (SELECT o.i FROM item o)",
            "SELECT o.a FROM ord o WHERE o.i IN (SELECT o.i FROM ord o)",
        )

    def test_subquery_in_the_from_clause(self) -> None:
        self.assertSame(
            "SELECT s.a FROM (SELECT a FROM t WHERE b > 1) AS s",
            "SELECT s.a FROM (SELECT a FROM t WHERE 1 < b) s",
        )

    def test_case_branch_order_is_kept(self) -> None:
        self.assertDiffers(
            "SELECT CASE WHEN a THEN 1 WHEN b THEN 2 END FROM t",
            "SELECT CASE WHEN b THEN 2 WHEN a THEN 1 END FROM t",
        )

    def test_case_reads_and_round_trips(self) -> None:
        self.assertSame(
            "SELECT CASE WHEN a > 1 THEN 'x' ELSE 'y' END FROM t",
            "select case when 1 < a then 'x' else 'y' end from t",
        )

    def test_group_by_can_name_a_select_alias(self) -> None:
        self.assertSame(
            "SELECT country AS c, COUNT(*) FROM t GROUP BY c",
            "SELECT country, COUNT(*) FROM t GROUP BY country",
        )

    def test_select_alias_does_not_leak_into_where(self) -> None:
        self.assertDiffers(
            "SELECT a AS b FROM t WHERE b > 1",
            "SELECT a AS b FROM t WHERE a > 1",
        )

    def test_having_conjuncts_are_a_set(self) -> None:
        self.assertSame(
            "SELECT c, COUNT(*) FROM t GROUP BY c HAVING COUNT(*) > 1 AND SUM(a) > 2",
            "SELECT c, COUNT(*) FROM t GROUP BY c HAVING SUM(a) > 2 AND COUNT(*) > 1",
        )

    def test_where_and_having_are_not_interchangeable(self) -> None:
        self.assertDiffers(
            "SELECT c FROM t GROUP BY c HAVING COUNT(*) > 1",
            "SELECT c FROM t WHERE COUNT(*) > 1 GROUP BY c",
        )

    def test_cte_bodies_are_compared(self) -> None:
        self.assertDiffers(
            "WITH p AS (SELECT * FROM t WHERE a = 1) SELECT * FROM p",
            "WITH p AS (SELECT * FROM t WHERE a = 2) SELECT * FROM p",
        )

    def test_deeply_nested_input_is_unreadable_not_a_crash(self) -> None:
        query = "SELECT " + "(" * 500 + "1" + ")" * 500 + " FROM t"
        self.assertEqual(structural_signature(query)[0], "unparsed")


class PublicContract(unittest.TestCase):
    """Totality, determinism, hashability, and the one allowed exception."""

    def test_scores_are_floats_of_exactly_one_or_zero(self) -> None:
        for left, right in (
            ("SELECT a FROM t", "SELECT a FROM t"),
            ("SELECT a FROM t", "SELECT b FROM u"),
            ("nonsense", "SELECT a FROM t"),
        ):
            score = structural_match(left, right)
            self.assertIsInstance(score, float)
            self.assertIn(score, (0.0, 1.0))

    def test_signature_is_a_tuple_and_hashable(self) -> None:
        signature = structural_signature(
            "SELECT c.n, COUNT(*) FROM cust c JOIN ord o ON c.i = o.c "
            "WHERE o.a > 1 GROUP BY c.n HAVING COUNT(*) > 2 ORDER BY c.n LIMIT 5"
        )
        self.assertIsInstance(signature, tuple)
        self.assertIsInstance(hash(signature), int)
        self.assertEqual({signature: "key"}[signature], "key")

    def test_signature_holds_no_set_so_ordering_cannot_drift(self) -> None:
        """A set in the signature would make it depend on hash randomisation."""
        text = repr(
            structural_signature("SELECT a, b FROM t WHERE p AND q AND r ORDER BY a")
        )
        self.assertNotIn("frozenset(", text)
        self.assertNotIn("{", text)

    def test_signature_is_deterministic(self) -> None:
        query = "SELECT a, b FROM t WHERE q AND p OR r ORDER BY b DESC LIMIT 3"
        first = structural_signature(query)
        for _ in range(5):
            self.assertEqual(structural_signature(query), first)

    def test_matching_is_symmetric(self) -> None:
        for case in CASES:
            with self.subTest(cid=case["cid"]):
                self.assertEqual(
                    structural_match(case["left"], case["right"]),
                    structural_match(case["right"], case["left"]),
                )

    def test_unreadable_input_is_a_non_match_even_against_itself(self) -> None:
        junk = "I could not work out a query for that."
        self.assertEqual(structural_match(junk, junk), 0.0)
        self.assertEqual(structural_signature(junk)[0], "unparsed")

    def test_empty_and_whitespace_input(self) -> None:
        for junk in ("", "   ", "\n\n", "```\n\n```", ";"):
            with self.subTest(junk=repr(junk)):
                self.assertEqual(structural_signature(junk)[0], "unparsed")
                self.assertEqual(structural_match(junk, "SELECT a FROM t"), 0.0)

    def test_non_select_statements_are_unreadable(self) -> None:
        for query in (
            "INSERT INTO t (a) VALUES (1)",
            "UPDATE t SET a = 1",
            "DELETE FROM t",
            "DROP TABLE t",
            "PRAGMA table_info(t)",
        ):
            with self.subTest(query=query):
                self.assertEqual(structural_signature(query)[0], "unparsed")

    def test_non_string_input_is_stringified(self) -> None:
        for value in (None, 42, 3.5, [1, 2], {"a": 1}, b"SELECT a FROM t"):
            with self.subTest(value=repr(value)):
                self.assertEqual(structural_signature(value)[0], "unparsed")
                self.assertEqual(structural_match(value, "SELECT a FROM t"), 0.0)

    def test_a_stringlike_object_is_accepted(self) -> None:
        class Wrapped:
            def __str__(self) -> str:
                return "SELECT a FROM t"

        self.assertEqual(structural_match(Wrapped(), "SELECT a FROM t"), 1.0)

    def test_a_raising_dunder_str_propagates(self) -> None:
        """Deliberate: the failure is the caller's object, not our input."""

        class BadValue:
            def __str__(self) -> str:
                raise ValueError("no text here")

        class BadType:
            def __str__(self) -> str:
                raise TypeError("not stringable")

        with self.assertRaises(ValueError):
            structural_signature(BadValue())
        with self.assertRaises(TypeError):
            structural_signature(BadType())
        with self.assertRaises(ValueError):
            structural_match(BadValue(), "SELECT a FROM t")
        with self.assertRaises(ValueError):
            structural_match("SELECT a FROM t", BadValue())

    def test_long_input_does_not_blow_up(self) -> None:
        query = "SELECT a FROM t WHERE " + " AND ".join(
            f"c{n} = {n}" for n in range(500)
        )
        self.assertEqual(structural_match(query, query), 1.0)


class ShippingConstraints(unittest.TestCase):
    """Static guards on the module that ships next to a scoring function."""

    def test_module_imports_nothing_but_future_annotations(self) -> None:
        lines = [
            line
            for line in MODULE_SOURCE.splitlines()
            if line.startswith(("import ", "from "))
        ]
        self.assertEqual(lines, ["from __future__ import annotations"])

    def test_module_names_no_execution_entry_point(self) -> None:
        # Assembled from fragments so the guard itself does not put the
        # flagged spellings into a file that ships beside the module.
        banned = (
            "ex" + "ec",
            "ev" + "al",
            "com" + "pile",
            "__im" + "port__",
            "ex" + "ecutemany",
            "ex" + "ecutescript",
            "sql" + "ite3",
            "sub" + "process",
            "run" + "py",
            "import" + "lib",
        )
        for name in banned:
            with self.subTest(name=name):
                self.assertNotIn(name, MODULE_SOURCE)

    def test_module_has_no_em_dash(self) -> None:
        # Written as an escape so this guard does not itself put one in a
        # file that ships beside the module.
        self.assertNotIn("\u2014", MODULE_SOURCE)

    def test_public_api_is_exactly_two_names(self) -> None:
        sql_structure = _MODULE

        self.assertEqual(
            sorted(sql_structure.__all__),
            ["structural_match", "structural_signature"],
        )
        # "annotations" is the name the __future__ statement binds, not part
        # of the surface. Everything else public must be one of the two.
        public = sorted(
            name
            for name in vars(sql_structure)
            if not name.startswith("_") and name != "annotations"
        )
        self.assertEqual(public, ["structural_match", "structural_signature"])
        self.assertTrue(callable(sql_structure.structural_match))
        self.assertTrue(callable(sql_structure.structural_signature))


if __name__ == "__main__":
    unittest.main()

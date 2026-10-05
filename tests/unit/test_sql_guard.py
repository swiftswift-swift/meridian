"""Tests for the read-only SQL guard.

The table-driven cases document the attack surface; the hypothesis properties assert the
invariants that must hold for inputs nobody thought to enumerate.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from app.domain.sql_guard import GuardDecision, SqlSchema, validate_sql

SCHEMA = SqlSchema.from_mapping(
    {
        "orders": ["id", "customer_id", "order_date", "total_usd", "region_id"],
        "regions": ["id", "name", "code"],
        "customers": ["id", "name", "region_id"],
    }
)

MAX_ROWS = 500


def guard(sql: str) -> GuardDecision:
    return validate_sql(sql, SCHEMA, max_rows=MAX_ROWS)


# --- statements that must be allowed ----------------------------------------------

ALLOWED = [
    "SELECT name FROM regions",
    "SELECT * FROM orders WHERE total_usd > 100",
    "SELECT r.name, SUM(o.total_usd) FROM orders o JOIN regions r ON r.id = o.region_id "
    "GROUP BY r.name",
    "WITH recent AS (SELECT * FROM orders) SELECT COUNT(*) FROM recent",
    "SELECT name FROM regions UNION SELECT name FROM customers",
    "SELECT name FROM regions INTERSECT SELECT name FROM customers",
    "SELECT name FROM regions EXCEPT SELECT name FROM customers",
    "SELECT COUNT(*) AS order_count FROM orders",
    "SELECT * FROM orders ORDER BY order_date DESC LIMIT 25",
    "SELECT * FROM orders WHERE region_id IN (SELECT id FROM regions WHERE code = 'EMEA')",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows_read_only_queries(sql: str) -> None:
    decision = guard(sql)
    assert decision.allowed, decision.reason
    assert decision.safe_sql


# --- statements that must be refused ----------------------------------------------

REFUSED = {
    "delete": "DELETE FROM orders",
    "delete_where": "DELETE FROM orders WHERE id = 1",
    "update": "UPDATE orders SET total_usd = 0",
    "insert": "INSERT INTO orders (id) VALUES (1)",
    "drop": "DROP TABLE orders",
    "alter": "ALTER TABLE orders ADD COLUMN x INT",
    "create": "CREATE TABLE evil (id INT)",
    "truncate": "TRUNCATE TABLE orders",
    "multi_statement": "SELECT 1; DROP TABLE orders",
    "multi_statement_trailing": "SELECT id FROM orders; DELETE FROM regions;",
    "unlisted_table": "SELECT * FROM users",
    "unlisted_table_in_join": "SELECT * FROM orders JOIN users ON users.id = orders.customer_id",
    "unlisted_table_in_subquery": "SELECT * FROM orders WHERE id IN (SELECT id FROM secrets)",
    "unknown_column": "SELECT password_hash FROM orders",
    "load_extension": "SELECT load_extension('evil.dll')",
    "readfile": "SELECT readfile('/etc/passwd')",
    "pragma": "PRAGMA table_info(orders)",
    "attach": "ATTACH DATABASE 'other.db' AS other",
    "vacuum": "VACUUM",
    "empty": "",
    "whitespace": "   \n  ",
    "unparseable": "SELECT ((( FROM",
}


@pytest.mark.parametrize("sql", REFUSED.values(), ids=list(REFUSED))
def test_refuses_unsafe_queries(sql: str) -> None:
    decision = guard(sql)
    assert decision.refused
    # The refusal must be explainable to an analyst, not just a boolean.
    assert decision.reason
    assert not decision.safe_sql


def test_refusal_names_the_allowed_tables() -> None:
    reason = guard("SELECT * FROM users").reason
    assert "users" in reason
    for table in ("orders", "regions", "customers"):
        assert table in reason


# --- row limiting -----------------------------------------------------------------


def test_applies_a_limit_when_none_given() -> None:
    decision = guard("SELECT * FROM orders")
    assert decision.limit_applied == MAX_ROWS
    assert "LIMIT 500" in decision.safe_sql.upper()


def test_clamps_a_limit_that_exceeds_the_maximum() -> None:
    decision = guard("SELECT * FROM orders LIMIT 99999")
    assert decision.limit_applied == MAX_ROWS


def test_preserves_a_smaller_limit() -> None:
    decision = guard("SELECT * FROM orders LIMIT 10")
    assert decision.limit_applied == 10


def test_limits_set_operations_too() -> None:
    decision = guard("SELECT name FROM regions UNION SELECT name FROM customers")
    assert decision.allowed
    assert "LIMIT" in decision.safe_sql.upper()


def test_reports_referenced_tables() -> None:
    decision = guard("SELECT o.id FROM orders o JOIN regions r ON r.id = o.region_id")
    assert decision.referenced_tables == frozenset({"orders", "regions"})


def test_cte_name_is_not_treated_as_an_unlisted_table() -> None:
    # A CTE is indistinguishable from a table at the reference site, so resolving them is the
    # difference between accepting valid analysis and refusing it.
    assert guard("WITH orders_2024 AS (SELECT * FROM orders) SELECT * FROM orders_2024").allowed


def test_cte_named_after_a_mutation_is_still_allowed() -> None:
    # The case a regex-based guard gets wrong.
    sql = "WITH delete_me AS (SELECT id FROM orders) SELECT COUNT(*) FROM delete_me"
    assert guard(sql).allowed


def test_string_literal_mentioning_drop_table_is_allowed() -> None:
    # The other case a regex gets wrong: the text appears, but no DDL is executed.
    assert guard("SELECT * FROM regions WHERE name = 'DROP TABLE orders'").allowed


# --- properties -------------------------------------------------------------------

MUTATION_KEYWORDS = ["DELETE FROM", "UPDATE", "INSERT INTO", "DROP TABLE", "ALTER TABLE"]


@given(keyword=st.sampled_from(MUTATION_KEYWORDS), table=st.sampled_from(["orders", "regions"]))
def test_property_mutations_are_always_refused(keyword: str, table: str) -> None:
    assert guard(f"{keyword} {table}").refused


@given(
    st.text(
        alphabet=st.characters(blacklist_categories=["Cs"]),
        min_size=0,
        max_size=120,
    )
)
@hypothesis_settings(max_examples=300, deadline=None)
def test_property_never_raises_and_never_emits_unsafe_sql(payload: str) -> None:
    """Arbitrary text must produce a decision, never an exception.

    The guard sits in front of a database on the untrusted path, so an unhandled parser error
    would be a denial of service at best.
    """
    decision = validate_sql(payload, SCHEMA, max_rows=MAX_ROWS)
    if decision.allowed:
        upper = decision.safe_sql.upper()
        for forbidden in ("DELETE", "UPDATE ", "INSERT", "DROP", "ALTER", "ATTACH", "PRAGMA"):
            assert forbidden not in upper
        assert ";" not in decision.safe_sql.rstrip(";")
    else:
        assert decision.reason


@given(st.integers(min_value=1, max_value=10_000))
def test_property_result_is_never_larger_than_the_cap(requested: int) -> None:
    decision = guard(f"SELECT * FROM orders LIMIT {requested}")
    assert decision.allowed
    assert decision.limit_applied is not None
    assert decision.limit_applied <= MAX_ROWS

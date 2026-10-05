"""Read-only SQL enforcement by parsing.

Why parsing and not pattern matching: a regex cannot distinguish a CTE named `delete_me`, the
string literal `'DROP TABLE'`, or a column called `update_ts` from an actual mutation. sqlglot
builds a syntax tree, so the guard reasons about what the statement *is* rather than what it
looks like.

This module is pure. It takes SQL and a schema allowlist and returns a decision. No connection,
no settings, no I/O, which is what makes the hypothesis property tests cheap to run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

# Every expression type that writes, changes structure, or escapes the query sandbox.
FORBIDDEN_EXPRESSIONS: tuple[type[exp.Expr], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Merge,
    exp.Grant,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Command,  # sqlglot parses PRAGMA, ATTACH, VACUUM and friends as a bare Command
)

# Functions that read or write the filesystem, run shell commands, or sleep the connection.
FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {
        "load_extension",
        "readfile",
        "writefile",
        "edit",
        "fts3_tokenizer",
        "pg_read_file",
        "pg_sleep",
        "pg_ls_dir",
        "dblink",
        "lo_import",
        "lo_export",
        "copy",
        "system",
    }
)


@dataclass(frozen=True, slots=True)
class SqlSchema:
    """The tables and columns a query is permitted to touch."""

    tables: frozenset[str]
    columns_by_table: dict[str, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, mapping: dict[str, list[str]]) -> SqlSchema:
        return cls(
            tables=frozenset(name.lower() for name in mapping),
            columns_by_table={
                name.lower(): frozenset(col.lower() for col in cols)
                for name, cols in mapping.items()
            },
        )


@dataclass(frozen=True, slots=True)
class GuardDecision:
    """The outcome of validating one statement."""

    allowed: bool
    reason: str = ""
    # The statement actually safe to execute: the original, re-rendered with a LIMIT applied.
    safe_sql: str = ""
    referenced_tables: frozenset[str] = frozenset()
    limit_applied: int | None = None

    @property
    def refused(self) -> bool:
        return not self.allowed


# Each refusal is its own early return so the rule and its message sit together; collapsing
# them into one branch would make the guard harder to audit, which is the opposite of useful.
def validate_sql(  # noqa: PLR0911
    sql: str,
    schema: SqlSchema,
    *,
    max_rows: int,
    dialect: str = "sqlite",
) -> GuardDecision:
    """Decide whether `sql` may run, and return the form that should be executed.

    The checks run cheapest-first so an obviously hostile statement is rejected before any tree
    walking happens.
    """
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        return GuardDecision(allowed=False, reason="The query is empty.")

    try:
        statements = sqlglot.parse(sql, read=dialect)
    except SqlglotError as exc:
        # SqlglotError, not ParseError: an unterminated quote or backtick raises TokenError,
        # which is a sibling of ParseError, and letting it escape would turn malformed input
        # into an unhandled 500 on the untrusted path. Found by the hypothesis property test.
        return GuardDecision(allowed=False, reason=f"The query could not be parsed: {exc}")
    except RecursionError:
        # Deeply nested parentheses exhaust the parser's stack before any rule runs.
        return GuardDecision(allowed=False, reason="The query is nested too deeply to analyse.")

    # A None entry is what sqlglot yields for a trailing semicolon; real statements remain.
    real_statements = [statement for statement in statements if statement is not None]
    if not real_statements:
        return GuardDecision(allowed=False, reason="The query contains no statement.")
    if len(real_statements) > 1:
        return GuardDecision(
            allowed=False,
            reason=(
                f"Only one statement is allowed; this query contains {len(real_statements)}. "
                "Chained statements are how a read-only guard gets bypassed."
            ),
        )

    statement = real_statements[0]

    # exp.Query is sqlglot's base for every read shape: SELECT, UNION, INTERSECT, EXCEPT and a
    # parenthesised subquery. Enumerating subclasses by hand previously refused INTERSECT and
    # EXCEPT, which are read-only and legitimate.
    if not isinstance(statement, exp.Query):
        return GuardDecision(
            allowed=False,
            reason=(
                f"Only SELECT queries are allowed; this is a "
                f"{type(statement).__name__.upper()} statement. The analysis database is "
                "read-only by design."
            ),
        )

    forbidden = _find_forbidden_node(statement)
    if forbidden is not None:
        return GuardDecision(
            allowed=False,
            reason=f"The query contains a forbidden {forbidden} operation.",
        )

    bad_function = _find_forbidden_function(statement)
    if bad_function is not None:
        return GuardDecision(
            allowed=False,
            reason=f"The function {bad_function}() is not permitted.",
        )

    referenced = _referenced_tables(statement)
    unknown = referenced - schema.tables
    if unknown:
        allowed_list = ", ".join(sorted(schema.tables))
        return GuardDecision(
            allowed=False,
            reason=(
                f"Unknown or non-allowlisted table(s): {', '.join(sorted(unknown))}. "
                f"Allowed tables are: {allowed_list}."
            ),
            referenced_tables=referenced,
        )

    unknown_columns = _unknown_columns(statement, schema, referenced)
    if unknown_columns:
        return GuardDecision(
            allowed=False,
            reason=f"Unknown column(s): {', '.join(sorted(unknown_columns))}.",
            referenced_tables=referenced,
        )

    limited, applied = _apply_row_limit(statement, max_rows)
    return GuardDecision(
        allowed=True,
        safe_sql=limited.sql(dialect=dialect),
        referenced_tables=referenced,
        limit_applied=applied,
    )


def _find_forbidden_node(statement: exp.Expr) -> str | None:
    for node in statement.walk():
        if isinstance(node, FORBIDDEN_EXPRESSIONS):
            return type(node).__name__.upper()
    return None


def _find_forbidden_function(statement: exp.Expr) -> str | None:
    for node in statement.find_all(exp.Anonymous, exp.Func):
        name = getattr(node, "name", "") or ""
        if name.lower() in FORBIDDEN_FUNCTIONS:
            return name.lower()
    return None


def _referenced_tables(statement: exp.Expr) -> frozenset[str]:
    """Collect real table names, excluding CTE aliases.

    A CTE name looks exactly like a table at the reference site, so it is resolved here rather
    than rejected: `WITH recent AS (SELECT ...) SELECT * FROM recent` is legitimate.
    """
    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    tables: set[str] = set()
    for table in statement.find_all(exp.Table):
        name = table.name.lower()
        if name and name not in cte_names:
            tables.add(name)
    return frozenset(tables)


def _unknown_columns(
    statement: exp.Expr, schema: SqlSchema, referenced: frozenset[str]
) -> frozenset[str]:
    """Reject columns that exist in no referenced table.

    Qualification is not tracked: resolving `o.total` to a specific table would require full
    alias resolution, and the value here is blocking probes at columns that do not exist
    anywhere, not catching the analyst's typo. The database rejects those anyway.
    """
    known: set[str] = set()
    for table in referenced:
        known |= set(schema.columns_by_table.get(table, frozenset()))
    if not known:
        return frozenset()

    cte_aliases = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    if cte_aliases:
        # A CTE invents its own column names, so column checking would produce false
        # positives. The table allowlist still bounds what the query can reach.
        return frozenset()

    select_aliases = {
        alias.alias_or_name.lower() for alias in statement.find_all(exp.Alias) if alias.alias
    }
    unknown: set[str] = set()
    for column in statement.find_all(exp.Column):
        name = column.name.lower()
        if name and name != "*" and name not in known and name not in select_aliases:
            unknown.add(name)
    return frozenset(unknown)


def _apply_row_limit(statement: exp.Query, max_rows: int) -> tuple[exp.Query, int | None]:
    """Clamp the row count so one query cannot pull the whole table into a prompt."""
    if not isinstance(statement, exp.Select):
        # A set operation carries no LIMIT of its own, so the cap goes on the outer query.
        return statement.limit(max_rows), max_rows

    existing = statement.args.get("limit")
    if existing is None:
        return statement.limit(max_rows), max_rows

    requested = _literal_int(existing.expression)
    if requested is None or requested > max_rows:
        return statement.limit(max_rows), max_rows
    return statement, requested


def _literal_int(node: exp.Expr | None) -> int | None:
    if isinstance(node, exp.Literal) and node.is_int:
        return int(node.name)
    return None

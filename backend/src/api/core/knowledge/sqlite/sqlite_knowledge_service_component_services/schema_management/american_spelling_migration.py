"""One-time rewrite of persisted British "cancel" spellings to American spelling.

Earlier Basil versions persisted status and event identifiers such as 'cancelled' and 'cancelling', including inside SQLite CHECK constraints. This migration rebuilds every table, and recreates every index, trigger, and view, whose stored SQL contains those literals, then rewrites identifier-shaped values and JSON keys so the American-only code paths can read them. Free text, file paths, Python exception names such as CancelledError, and primary-key or foreign-key values (record identities) are left untouched.

The British spellings in this module are intentional legacy inputs; the path is protected in scripts/spelling/spelling_policy.py.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

MIGRATION_NAME = "american_spelling_v1"
MARKER_TABLE = "basil_data_migrations"

_LEGACY_SQL_LITERALS = (("'cancelled'", "'canceled'"), ("'cancelling'", "'canceling'"))
_TOKEN_REPLACEMENTS = {
    "cancelled": "canceled",
    "Cancelled": "Canceled",
    "CANCELLED": "CANCELED",
    "cancelling": "canceling",
    "Cancelling": "Canceling",
    "CANCELLING": "CANCELING",
}
_TOKEN_PATTERN = re.compile(r"cancelled|cancelling|Cancelled(?!Error)|Cancelling|CANCELLED|CANCELLING")
_VALUE_IDENTIFIER_PATTERN = re.compile(r"^(?:[a-z0-9_:\-]+|[A-Z0-9_]+)$")
_KEY_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def migrate_american_spelling(conn: sqlite3.Connection) -> None:
    """Apply the one-time rewrite in its own transaction; a no-op once the marker row exists."""
    if _migration_applied(conn):
        return
    if conn.in_transaction:
        conn.commit()
    foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {MARKER_TABLE} ("
                "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            rebuilt_tables = _rebuild_tables_with_legacy_literals(conn)
            recreated_objects = _recreate_objects_with_legacy_literals(conn)
            rewritten_values = _rewrite_legacy_values(conn)
            conn.execute(f"INSERT INTO {MARKER_TABLE} (name) VALUES (?)", (MIGRATION_NAME,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys_enabled else 'OFF'}")
    logger.info(
        "American spelling migration rebuilt %d table(s) %s, recreated %d index/trigger/view object(s), rewrote %d value(s)",
        len(rebuilt_tables),
        rebuilt_tables,
        recreated_objects,
        rewritten_values,
    )


def americanize_persisted_text(value: str) -> str:
    """Return *value* with identifier-shaped legacy spellings rewritten; free text is returned unchanged."""
    if value.lstrip()[:1] in ("{", "["):
        try:
            decoded = json.loads(value)
        except ValueError:
            return value
        americanized = _americanize_json(decoded)
        return value if americanized == decoded else json.dumps(americanized, ensure_ascii=False)
    if _VALUE_IDENTIFIER_PATTERN.match(value):
        return _americanize_identifier(value)
    return value


def _migration_applied(conn: sqlite3.Connection) -> bool:
    marker_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (MARKER_TABLE,)
    ).fetchone()
    if marker_table is None:
        return False
    return conn.execute(
        f"SELECT 1 FROM {MARKER_TABLE} WHERE name = ?", (MIGRATION_NAME,)
    ).fetchone() is not None


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _contains_legacy_literal(sql: str | None) -> bool:
    return bool(sql) and any(legacy in sql for legacy, _ in _LEGACY_SQL_LITERALS)


def _rewrite_legacy_sql(sql: str) -> str:
    for legacy, american in _LEGACY_SQL_LITERALS:
        sql = sql.replace(legacy, american)
    return sql


def _is_virtual_table_sql(sql: str | None) -> bool:
    return (sql or "").lstrip().upper().startswith("CREATE VIRTUAL TABLE")


def _rebuild_tables_with_legacy_literals(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL ORDER BY name"
    ).fetchall()
    rebuilt: list[str] = []
    for row in rows:
        table_name, table_sql = row[0], row[1]
        if table_name.startswith("sqlite_") or _is_virtual_table_sql(table_sql):
            continue
        if not _contains_legacy_literal(table_sql):
            continue
        _rebuild_table(conn, table_name, table_sql)
        rebuilt.append(table_name)
    return rebuilt


def _americanized_column_expression(column: str) -> str:
    quoted = _quote_identifier(column)
    return f"CASE {quoted} WHEN 'cancelled' THEN 'canceled' WHEN 'cancelling' THEN 'canceling' ELSE {quoted} END"


def _key_columns_by_table(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """Primary-key and foreign-key columns (both sides) hold record identities, which the migration never rewrites."""
    table_names = [
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
    ]
    key_columns: dict[str, set[str]] = {table_name: set() for table_name in table_names}
    for table_name in table_names:
        quoted_table = _quote_identifier(table_name)
        try:
            column_rows = conn.execute(f"PRAGMA table_info({quoted_table})").fetchall()
            foreign_key_rows = conn.execute(f"PRAGMA foreign_key_list({quoted_table})").fetchall()
        except sqlite3.DatabaseError:
            continue
        key_columns[table_name].update(column_row[1] for column_row in column_rows if column_row[5] > 0)
        for foreign_key_row in foreign_key_rows:
            referenced_table, from_column, to_column = foreign_key_row[2], foreign_key_row[3], foreign_key_row[4]
            key_columns[table_name].add(from_column)
            referenced_columns = key_columns.setdefault(referenced_table, set())
            if to_column is not None:
                referenced_columns.add(to_column)
    return key_columns


def _rebuild_table(conn: sqlite3.Connection, table_name: str, table_sql: str) -> None:
    dependents = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE tbl_name = ? AND type IN ('index', 'trigger') AND sql IS NOT NULL",
        (table_name,),
    ).fetchall()
    key_columns = _key_columns_by_table(conn).get(table_name, set())
    column_rows = conn.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
    columns = [column_row[1] for column_row in column_rows]
    primary_key_rows = [column_row for column_row in column_rows if column_row[5] > 0]
    has_rowid_alias = len(primary_key_rows) == 1 and str(primary_key_rows[0][2]).upper() == "INTEGER"
    target_columns = [_quote_identifier(column) for column in columns]
    source_columns = [
        _quote_identifier(column) if column in key_columns else _americanized_column_expression(column)
        for column in columns
    ]
    if not has_rowid_alias:
        target_columns.insert(0, "rowid")
        source_columns.insert(0, "rowid")
    legacy_name = f"{table_name}__legacy_spelling"
    for dependent in dependents:
        conn.execute(f"DROP {str(dependent[0]).upper()} IF EXISTS {_quote_identifier(dependent[1])}")
    conn.execute("PRAGMA legacy_alter_table = ON")
    conn.execute(f"ALTER TABLE {_quote_identifier(table_name)} RENAME TO {_quote_identifier(legacy_name)}")
    conn.execute(_rewrite_legacy_sql(table_sql))
    conn.execute(
        f"INSERT INTO {_quote_identifier(table_name)} ({', '.join(target_columns)}) "
        f"SELECT {', '.join(source_columns)} FROM {_quote_identifier(legacy_name)}"
    )
    _carry_autoincrement_sequence(conn, legacy_name, table_name)
    conn.execute(f"DROP TABLE {_quote_identifier(legacy_name)}")
    for dependent in dependents:
        conn.execute(_rewrite_legacy_sql(dependent[2]))


def _carry_autoincrement_sequence(conn: sqlite3.Connection, legacy_name: str, table_name: str) -> None:
    """Keep an AUTOINCREMENT high-water mark so ids of previously deleted rows are never reused."""
    sequence_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
    ).fetchone()
    if sequence_table is None:
        return
    legacy_sequence = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (legacy_name,)).fetchone()
    if legacy_sequence is None:
        return
    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table_name,))
    conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table_name, legacy_sequence[0]))


def _recreate_objects_with_legacy_literals(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE type IN ('index', 'trigger', 'view') AND sql IS NOT NULL ORDER BY type, name"
    ).fetchall()
    recreated = 0
    for row in rows:
        object_type, object_name, object_sql = row[0], row[1], row[2]
        if not _contains_legacy_literal(object_sql):
            continue
        conn.execute(f"DROP {str(object_type).upper()} IF EXISTS {_quote_identifier(object_name)}")
        conn.execute(_rewrite_legacy_sql(object_sql))
        recreated += 1
    return recreated


def _value_scan_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()
    virtual_tables = [row[0] for row in rows if _is_virtual_table_sql(row[1])]
    tables: list[str] = []
    for row in rows:
        table_name = row[0]
        if table_name.startswith("sqlite_") or table_name == MARKER_TABLE or table_name in virtual_tables:
            continue
        if any(table_name.startswith(f"{virtual_table}_") for virtual_table in virtual_tables):
            continue
        tables.append(table_name)
    return tables


def _rewrite_legacy_values(conn: sqlite3.Connection) -> int:
    rewritten = 0
    key_columns_by_table = _key_columns_by_table(conn)
    for table_name in _value_scan_tables(conn):
        quoted_table = _quote_identifier(table_name)
        key_columns = key_columns_by_table.get(table_name, set())
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({quoted_table})").fetchall()]
        for column in columns:
            if column in key_columns:
                continue
            quoted_column = _quote_identifier(column)
            rows = conn.execute(
                f"SELECT rowid, {quoted_column} FROM {quoted_table} "
                f"WHERE typeof({quoted_column}) = 'text' AND {quoted_column} LIKE '%cancell%'"
            ).fetchall()
            for row in rows:
                original = row[1]
                updated = americanize_persisted_text(original)
                if updated == original:
                    continue
                try:
                    conn.execute(
                        f"UPDATE {quoted_table} SET {quoted_column} = ? WHERE rowid = ?",
                        (updated, row[0]),
                    )
                except sqlite3.IntegrityError as exc:
                    logger.warning(
                        "American spelling migration kept %s.%s rowid %s unchanged: %s",
                        table_name,
                        column,
                        row[0],
                        exc,
                    )
                    continue
                rewritten += 1
    return rewritten


def _americanize_identifier(value: str) -> str:
    return _TOKEN_PATTERN.sub(lambda match: _TOKEN_REPLACEMENTS[match.group(0)], value)


def _americanize_json(node: Any) -> Any:
    if isinstance(node, dict):
        result: dict[Any, Any] = {}
        for key, child in node.items():
            new_key = key
            if isinstance(key, str) and _KEY_IDENTIFIER_PATTERN.match(key):
                new_key = _americanize_identifier(key)
                if new_key != key and new_key in node:
                    continue
            result[new_key] = _americanize_json(child)
        return result
    if isinstance(node, list):
        return [_americanize_json(child) for child in node]
    if isinstance(node, str) and _VALUE_IDENTIFIER_PATTERN.match(node):
        return _americanize_identifier(node)
    return node

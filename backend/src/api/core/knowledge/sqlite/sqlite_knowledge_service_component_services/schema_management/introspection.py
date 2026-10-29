"""Schema loading and introspection helpers."""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from ..infrastructure.connection import get_async_connection, get_sync_connection

logger = logging.getLogger(__name__)


def load_schema(db_path: str) -> Dict[str, Set[str]]:
    """Load column information for every table."""
    schema: Dict[str, Set[str]] = {}
    with get_sync_connection(db_path, ensure_schema=False) as conn:
        cursor = conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
        """)
        tables = [row[0] for row in cursor.fetchall()]

        for table in tables:
            cursor = conn.execute(f"PRAGMA table_info({table})")
            schema[table] = {row['name'] for row in cursor.fetchall()}

    return schema


def validate_query_columns(schema: Dict[str, Set[str]], table: str, columns: List[str]) -> List[str]:
    """Return the subset of *columns* that actually exist in *table*."""
    if table not in schema:
        raise ValueError(f"Table {table} does not exist in schema")

    valid_columns = []
    for col in columns:
        if col in schema[table]:
            valid_columns.append(col)
        else:
            logger.warning(f"Column {col} does not exist in table {table}, skipping")
    return valid_columns


def build_select_query(
    schema: Dict[str, Set[str]],
    table: str,
    columns: List[str],
    conditions: Optional[List[Tuple[str, str, Any]]] = None,
) -> Tuple[str, List[Any]]:
    """Build a parameterized SELECT query with schema validation."""
    valid_columns = validate_query_columns(schema, table, columns)
    if not valid_columns:
        raise ValueError(f"No valid columns provided for table {table}")

    query = f"SELECT {', '.join(valid_columns)} FROM {table}"
    params: List[Any] = []

    if conditions:
        where_clauses = []
        for col, op, value in conditions:
            if col in schema[table]:
                where_clauses.append(f"{col} {op} ?")
                params.append(value)
            else:
                logger.warning(f"Skipping condition on non-existent column {col}")

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

    return query, params


async def get_schema_info(db_path: str) -> Dict[str, Any]:
    """Return detailed schema information (tables, columns, indexes, FKs)."""
    schema_info: Dict[str, Any] = {"tables": {}, "relationships": []}

    try:
        conn = await get_async_connection(db_path, ensure_schema=False)
        try:
            cursor = await conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """)
            tables = [row[0] async for row in cursor]

            for table in tables:
                cursor = await conn.execute(f"PRAGMA table_info({table})")
                columns = []
                async for row in cursor:
                    columns.append({
                        "name": row[1], "type": row[2],
                        "notnull": bool(row[3]), "pk": bool(row[5]),
                    })
                schema_info["tables"][table] = {"columns": columns}

                cursor = await conn.execute(f"PRAGMA index_list({table})")
                indexes = []
                async for row in cursor:
                    idx_cursor = await conn.execute(f"PRAGMA index_info({row[1]})")
                    index_columns = [r[2] async for r in idx_cursor]
                    indexes.append({
                        "name": row[1], "unique": bool(row[2]),
                        "columns": index_columns,
                    })
                schema_info["tables"][table]["indexes"] = indexes

            for table in tables:
                cursor = await conn.execute(f"PRAGMA foreign_key_list({table})")
                async for row in cursor:
                    schema_info["relationships"].append({
                        "table": table, "column": row[3],
                        "ref_table": row[2], "ref_column": row[4],
                    })

            return schema_info
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"Error getting schema info: {e}")
        return schema_info


def get_schema_info_sync(db_path: str) -> Dict[str, Any]:
    """Synchronous schema-info helper."""
    schema_info: Dict[str, Any] = {"tables": {}, "relationships": []}

    try:
        with get_sync_connection(db_path, ensure_schema=False) as conn:
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """)
            tables = [row[0] for row in cursor]

            for table in tables:
                cursor = conn.execute(f"PRAGMA table_info({table})")
                columns = []
                for row in cursor:
                    columns.append({
                        "name": row[1], "type": row[2],
                        "notnull": bool(row[3]), "pk": bool(row[5]),
                    })
                schema_info["tables"][table] = {"columns": columns}

                cursor = conn.execute(f"PRAGMA index_list({table})")
                indexes = []
                for row in cursor:
                    idx_cursor = conn.execute(f"PRAGMA index_info({row[1]})")
                    index_columns = [r[2] for r in idx_cursor]
                    indexes.append({
                        "name": row[1], "unique": bool(row[2]),
                        "columns": index_columns,
                    })
                schema_info["tables"][table]["indexes"] = indexes

            for table in tables:
                cursor = conn.execute(f"PRAGMA foreign_key_list({table})")
                for row in cursor:
                    schema_info["relationships"].append({
                        "table": table, "column": row[3],
                        "ref_table": row[2], "ref_column": row[4],
                    })

            return schema_info
    except Exception as e:
        logger.error(f"Error getting schema info (sync): {e}")
        return schema_info

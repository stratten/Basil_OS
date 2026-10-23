"""Shared helpers for the zettel test modules."""

import sqlite3

import pytest

from api.core.knowledge.sqlite.schema import get_schema_statements
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.zettel_migrations import (
    migrate_zettel_backreference,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.fts.tables import (
    ensure_fts_tables,
)


class NonClosingConnection:
    """Hands a test connection to code that expects a context manager.

    The passes open and close their own connection; tests need it to keep using
    the in-memory database, which vanishes the moment it is closed.
    """

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc_info):
        return False


def apply_zettel_schema(connection: sqlite3.Connection) -> None:
    """Build the full schema, then add the zettel_id back-references.

    Mirrors production: get_schema_statements creates the source tables without
    zettel_id, and migrate_zettel_backreference adds it. Running both here means
    the tests exercise the same schema the app runs against.
    """
    for statement in get_schema_statements():
        connection.execute(statement)
    migrate_zettel_backreference(connection)
    ensure_fts_tables(connection)


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    apply_zettel_schema(connection)
    yield connection
    connection.close()

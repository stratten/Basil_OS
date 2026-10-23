"""Shared helpers for retrieval tests."""

import sqlite3

import pytest

from api.core.knowledge.sqlite.schema import get_schema_statements
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.core_migrations import (
    migrate_retrieval_tables,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.zettel_migrations import (
    migrate_zettel_backreference,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.fts.tables import (
    ensure_fts_tables,
)


def apply_zettel_schema(connection: sqlite3.Connection) -> None:
    for statement in get_schema_statements():
        connection.execute(statement)
    migrate_zettel_backreference(connection)


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    apply_zettel_schema(connection)
    migrate_retrieval_tables(connection)
    ensure_fts_tables(connection)
    connection.commit()
    yield connection
    connection.close()

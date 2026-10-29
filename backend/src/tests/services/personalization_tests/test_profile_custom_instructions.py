import pytest

from api.core.knowledge.personalization.profile_manager import ProfileManager
from api.core.knowledge.personalization_models import UserProfileCreate
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)


@pytest.fixture
def profile_manager(tmp_path):
    db_path = str(tmp_path / "knowledge.db")
    SchemaManager(db_path).initialize_db()
    return ProfileManager(db_path)


@pytest.mark.asyncio
async def test_custom_instructions_round_trips_on_create(profile_manager):
    created = await profile_manager.create_or_update_user_profile(
        UserProfileCreate(full_name="Ada Lovelace", custom_instructions="No em dashes. No exclamation points.")
    )
    assert created.custom_instructions == "No em dashes. No exclamation points."
    fetched = await profile_manager.get_user_profile()
    assert fetched.custom_instructions == "No em dashes. No exclamation points."


@pytest.mark.asyncio
async def test_custom_instructions_round_trips_on_update_and_can_be_cleared(profile_manager):
    await profile_manager.create_or_update_user_profile(
        UserProfileCreate(full_name="Ada Lovelace", custom_instructions="Be terse.")
    )
    updated = await profile_manager.create_or_update_user_profile(
        UserProfileCreate(full_name="Ada Lovelace", custom_instructions=None)
    )
    assert updated.custom_instructions is None


@pytest.mark.asyncio
async def test_migration_adds_column_to_pre_existing_table_without_it(tmp_path):
    import sqlite3

    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.personalization_migrations import (
        migrate_personalization_profile_table,
    )

    db_path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE user_profile (id TEXT PRIMARY KEY DEFAULT 'default', full_name TEXT)"
    )
    conn.commit()

    migrate_personalization_profile_table(conn)
    conn.commit()

    columns = [row["name"] for row in conn.execute("PRAGMA table_info(user_profile)").fetchall()]
    assert "custom_instructions" in columns
    conn.close()

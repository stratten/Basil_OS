"""Migration script to add personalization tables to existing knowledge_base.db

This migration adds:
- user_profile
- communication_style_profile  
- writing_samples
- contact_relationships
- user_signatures
- personalization_insights

And their associated indices.

Schema version: 0.4.0 -> 0.5.0
"""

import sqlite3
import asyncio
import aiosqlite
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# New table definitions (from schema.py)
PERSONALIZATION_TABLES = [
    # User profile table
    """
    CREATE TABLE IF NOT EXISTS user_profile (
        id TEXT PRIMARY KEY DEFAULT 'default',
        
        -- Identity
        full_name TEXT,
        preferred_name TEXT,
        email TEXT,
        
        -- Professional context
        job_title TEXT,
        company_name TEXT,
        industry TEXT,
        
        -- Communication preferences
        default_formality TEXT,
        default_tone TEXT,
        custom_instructions TEXT,

        -- Metadata
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        profile_version INTEGER DEFAULT 1
    )
    """,

    # Communication style profile table
    """
    CREATE TABLE IF NOT EXISTS communication_style_profile (
        id TEXT PRIMARY KEY,
        user_id TEXT DEFAULT 'default',
        context_type TEXT NOT NULL,
        
        -- Style attributes (JSON)
        style_attributes TEXT NOT NULL,
        
        -- Confidence and sample size
        confidence REAL DEFAULT 0.0,
        sample_count INTEGER DEFAULT 0,
        
        -- Timestamps
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_used_at TIMESTAMP,
        
        FOREIGN KEY (user_id) REFERENCES user_profile(id)
    )
    """,

    # Writing samples table
    """
    CREATE TABLE IF NOT EXISTS writing_samples (
        id TEXT PRIMARY KEY,
        user_id TEXT DEFAULT 'default',
        
        -- Sample metadata
        source_type TEXT NOT NULL,
        context_type TEXT NOT NULL,
        app_name TEXT,
        
        -- The actual writing
        content TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        
        -- Context about the writing
        recipient TEXT,
        subject TEXT,
        relationship_type TEXT,
        
        -- Quality indicators
        quality_score REAL,
        was_edited BOOLEAN DEFAULT FALSE,
        edit_distance INTEGER,
        
        -- Timestamps
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        FOREIGN KEY (user_id) REFERENCES user_profile(id)
    )
    """,

    # Contact relationships table
    """
    CREATE TABLE IF NOT EXISTS contact_relationships (
        id TEXT PRIMARY KEY,
        user_id TEXT DEFAULT 'default',
        
        -- Contact identity
        contact_name TEXT,
        contact_email TEXT NOT NULL,
        contact_company TEXT,
        
        -- Relationship metadata
        relationship_type TEXT DEFAULT 'unknown',
        formality_level TEXT DEFAULT 'professional',
        
        -- Communication patterns
        message_count INTEGER DEFAULT 0,
        last_contact_date TIMESTAMP,
        typical_response_time_hours REAL,
        
        -- Context (JSON)
        common_topics TEXT,
        notes TEXT,
        
        -- Timestamps
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        FOREIGN KEY (user_id) REFERENCES user_profile(id)
    )
    """,

    # User signatures table
    """
    CREATE TABLE IF NOT EXISTS user_signatures (
        id TEXT PRIMARY KEY,
        user_id TEXT DEFAULT 'default',
        
        -- Signature content
        signature_text TEXT NOT NULL,
        signature_html TEXT,
        
        -- Usage context
        context TEXT DEFAULT 'default',
        is_primary BOOLEAN DEFAULT FALSE,
        
        -- Detection metadata
        first_seen TIMESTAMP NOT NULL,
        last_seen TIMESTAMP NOT NULL,
        occurrence_count INTEGER DEFAULT 1,
        confidence REAL DEFAULT 1.0,
        
        FOREIGN KEY (user_id) REFERENCES user_profile(id)
    )
    """,

    # Personalization insights table
    """
    CREATE TABLE IF NOT EXISTS personalization_insights (
        id TEXT PRIMARY KEY,
        user_id TEXT DEFAULT 'default',
        
        -- Insight metadata
        insight_type TEXT NOT NULL,
        context_type TEXT,
        
        -- The insight
        insight_key TEXT NOT NULL,
        insight_value TEXT NOT NULL,
        
        -- Confidence and usage
        confidence REAL DEFAULT 0.0,
        times_applied INTEGER DEFAULT 0,
        success_rate REAL,
        
        -- Source tracking
        derived_from TEXT NOT NULL,
        
        -- Timestamps
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        FOREIGN KEY (user_id) REFERENCES user_profile(id)
    )
    """
]

PERSONALIZATION_INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_comm_style_context ON communication_style_profile(user_id, context_type)",
    "CREATE INDEX IF NOT EXISTS idx_writing_samples_type ON writing_samples(user_id, context_type)",
    "CREATE INDEX IF NOT EXISTS idx_writing_samples_source ON writing_samples(source_type)",
    "CREATE INDEX IF NOT EXISTS idx_writing_samples_hash ON writing_samples(content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_contacts_email ON contact_relationships(user_id, contact_email)",
    "CREATE INDEX IF NOT EXISTS idx_contacts_relationship ON contact_relationships(relationship_type)",
    "CREATE INDEX IF NOT EXISTS idx_signatures_primary ON user_signatures(user_id, is_primary)",
    "CREATE INDEX IF NOT EXISTS idx_insights_type ON personalization_insights(user_id, insight_type, context_type)"
]


async def migrate_async(db_path: Optional[str] = None) -> None:
    """Run migration asynchronously.
    
    Args:
        db_path: Path to knowledge_base.db. Defaults to ~/.basil/knowledge_base.db
    """
    if db_path is None:
        db_path = str(Path.home() / ".basil" / "knowledge_base.db")
    
    logger.info(f"Starting personalization tables migration on: {db_path}")
    
    if not Path(db_path).exists():
        logger.warning(f"Database does not exist at {db_path}. Will be created on first use.")
        return
    
    async with aiosqlite.connect(db_path) as conn:
        # Check current schema version
        try:
            cursor = await conn.execute(
                "SELECT value FROM schema_info WHERE key = 'version'"
            )
            row = await cursor.fetchone()
            current_version = row[0] if row else "unknown"
            logger.info(f"Current schema version: {current_version}")
        except sqlite3.OperationalError:
            logger.info("schema_info table doesn't exist yet, assuming fresh database")
            current_version = "unknown"
        
        # Create tables
        logger.info("Creating personalization tables...")
        for i, table_sql in enumerate(PERSONALIZATION_TABLES, 1):
            try:
                await conn.execute(table_sql)
                logger.info(f"Created table {i}/{len(PERSONALIZATION_TABLES)}")
            except Exception as e:
                logger.error(f"Error creating table {i}: {e}")
                raise
        
        # Create indices
        logger.info("Creating indices...")
        for i, index_sql in enumerate(PERSONALIZATION_INDICES, 1):
            try:
                await conn.execute(index_sql)
                logger.info(f"Created index {i}/{len(PERSONALIZATION_INDICES)}")
            except Exception as e:
                logger.error(f"Error creating index {i}: {e}")
                raise
        
        # Update schema version
        try:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_info (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                "INSERT OR REPLACE INTO schema_info (key, value) VALUES ('version', '0.5.0')"
            )
            logger.info("Updated schema version to 0.5.0")
        except Exception as e:
            logger.error(f"Error updating schema version: {e}")
            raise
        
        await conn.commit()
        logger.info("Migration completed successfully!")


def migrate_sync(db_path: Optional[str] = None) -> None:
    """Run migration synchronously (wrapper for async version).
    
    Args:
        db_path: Path to knowledge_base.db. Defaults to ~/.basil/knowledge_base.db
    """
    asyncio.run(migrate_async(db_path))


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run migration
    print("=" * 80)
    print("PERSONALIZATION TABLES MIGRATION")
    print("=" * 80)
    print()
    print("This will add the following tables to your knowledge_base.db:")
    print("  - user_profile")
    print("  - communication_style_profile")
    print("  - writing_samples")
    print("  - contact_relationships")
    print("  - user_signatures")
    print("  - personalization_insights")
    print()
    print("Schema version will be updated: 0.4.0 -> 0.5.0")
    print()
    
    # Confirm
    response = input("Continue with migration? (y/N): ")
    if response.lower() != 'y':
        print("Migration canceled.")
        exit(0)
    
    try:
        migrate_sync()
        print()
        print("=" * 80)
        print("MIGRATION SUCCESSFUL!")
        print("=" * 80)
    except Exception as e:
        print()
        print("=" * 80)
        print("MIGRATION FAILED!")
        print("=" * 80)
        print(f"Error: {e}")
        exit(1)


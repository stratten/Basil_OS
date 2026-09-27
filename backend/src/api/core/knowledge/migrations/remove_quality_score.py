#!/usr/bin/env python3
"""
Migration: Remove quality_score column from writing_samples table.

User explicitly saving a sample is the quality endorsement - no scoring needed.

This migration:
1. Removes the quality_score column from writing_samples table
2. Updates schema version from 0.5.0 to 0.5.1
"""

import asyncio
import aiosqlite
import sqlite3
from pathlib import Path


async def migrate_async(db_path: str):
    """Run migration asynchronously."""
    print(f"Starting migration on {db_path}")
    
    async with aiosqlite.connect(db_path) as conn:
        # Check if schema_version table exists
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        has_schema_version = await cursor.fetchone() is not None
        
        current_version = "unknown"
        if has_schema_version:
            # Check current schema version
            cursor = await conn.execute("SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1")
            row = await cursor.fetchone()
            current_version = row[0] if row else "unknown"
            print(f"Current schema version: {current_version}")
            
            if current_version == "0.5.1":
                print("Database already at version 0.5.1, skipping migration")
                return
        else:
            print("No schema_version table found, assuming pre-0.5.0 database")
            # Create schema_version table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        # Check if quality_score column exists
        cursor = await conn.execute("PRAGMA table_info(writing_samples)")
        columns = await cursor.fetchall()
        has_quality_score = any(col[1] == "quality_score" for col in columns)
        
        if not has_quality_score:
            print("quality_score column doesn't exist, skipping column removal")
        else:
            print("Removing quality_score column from writing_samples table...")
            
            # SQLite doesn't support DROP COLUMN directly, so we need to:
            # 1. Create new table without quality_score
            # 2. Copy data
            # 3. Drop old table
            # 4. Rename new table
            
            await conn.execute("""
                CREATE TABLE writing_samples_new (
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
                    
                    -- Edit tracking (for future analysis)
                    was_edited BOOLEAN DEFAULT FALSE,
                    edit_distance INTEGER,
                    
                    -- Timestamps
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    FOREIGN KEY (user_id) REFERENCES user_profile(id)
                )
            """)
            
            # Copy data (excluding quality_score)
            await conn.execute("""
                INSERT INTO writing_samples_new (
                    id, user_id, source_type, context_type, app_name,
                    content, content_hash, recipient, subject, relationship_type,
                    was_edited, edit_distance, created_at
                )
                SELECT 
                    id, user_id, source_type, context_type, app_name,
                    content, content_hash, recipient, subject, relationship_type,
                    was_edited, edit_distance, created_at
                FROM writing_samples
            """)
            
            # Drop old table and rename new one
            await conn.execute("DROP TABLE writing_samples")
            await conn.execute("ALTER TABLE writing_samples_new RENAME TO writing_samples")
            
            # Recreate indices
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_writing_samples_user_context 
                ON writing_samples(user_id, context_type)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_writing_samples_hash 
                ON writing_samples(content_hash)
            """)
            
            print("✓ Removed quality_score column")
        
        # Update schema version
        await conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            ("0.5.1",)
        )
        await conn.commit()
        
        print("✓ Updated schema version to 0.5.1")
        print("Migration completed successfully!")


def migrate_sync(db_path: str):
    """Run migration synchronously."""
    print(f"Starting migration on {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if schema_version table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    has_schema_version = cursor.fetchone() is not None
    
    current_version = "unknown"
    if has_schema_version:
        # Check current schema version
        cursor.execute("SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1")
        row = cursor.fetchone()
        current_version = row[0] if row else "unknown"
        print(f"Current schema version: {current_version}")
        
        if current_version == "0.5.1":
            print("Database already at version 0.5.1, skipping migration")
            conn.close()
            return
    else:
        print("No schema_version table found, assuming pre-0.5.0 database")
        # Create schema_version table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    # Check if quality_score column exists
    cursor.execute("PRAGMA table_info(writing_samples)")
    columns = cursor.fetchall()
    has_quality_score = any(col[1] == "quality_score" for col in columns)
    
    if not has_quality_score:
        print("quality_score column doesn't exist, skipping column removal")
    else:
        print("Removing quality_score column from writing_samples table...")
        
        # Create new table without quality_score
        cursor.execute("""
            CREATE TABLE writing_samples_new (
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
                
                -- Edit tracking (for future analysis)
                was_edited BOOLEAN DEFAULT FALSE,
                edit_distance INTEGER,
                
                -- Timestamps
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                FOREIGN KEY (user_id) REFERENCES user_profile(id)
            )
        """)
        
        # Copy data (excluding quality_score)
        cursor.execute("""
            INSERT INTO writing_samples_new (
                id, user_id, source_type, context_type, app_name,
                content, content_hash, recipient, subject, relationship_type,
                was_edited, edit_distance, created_at
            )
            SELECT 
                id, user_id, source_type, context_type, app_name,
                content, content_hash, recipient, subject, relationship_type,
                was_edited, edit_distance, created_at
            FROM writing_samples
        """)
        
        # Drop old table and rename new one
        cursor.execute("DROP TABLE writing_samples")
        cursor.execute("ALTER TABLE writing_samples_new RENAME TO writing_samples")
        
        # Recreate indices
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_writing_samples_user_context 
            ON writing_samples(user_id, context_type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_writing_samples_hash 
            ON writing_samples(content_hash)
        """)
        
        print("✓ Removed quality_score column")
    
    # Update schema version
    cursor.execute(
        "INSERT INTO schema_version (version) VALUES (?)",
        ("0.5.1",)
    )
    conn.commit()
    conn.close()
    
    print("✓ Updated schema version to 0.5.1")
    print("Migration completed successfully!")


if __name__ == "__main__":
    # Default database path
    db_path = Path.home() / ".basil" / "knowledge_base.db"
    
    import sys
    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])
    
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        sys.exit(1)
    
    # Run async migration
    asyncio.run(migrate_async(str(db_path)))


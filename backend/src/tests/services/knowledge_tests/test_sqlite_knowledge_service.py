import asyncio
import threading
import time

import pytest
from datetime import datetime, timedelta
from typing import Dict, Any
import sqlite3
import sys
from pathlib import Path
import json

# Add the test directory to the Python path
test_dir = Path(__file__).parent
sys.path.append(str(test_dir))

from test_schema import get_schema_statements
from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import get_sync_connection

@pytest.fixture
def sqlite_service(tmp_path):
    """Create a temporary SQLite service for testing."""
    service = SQLiteKnowledgeService(str(tmp_path / "knowledge.db"))
    
    # Create tables in the shared memory database
    with get_sync_connection(service.db_path) as conn:
        # Drop existing tables first
        conn.execute("DROP TABLE IF EXISTS activities_fts")
        conn.execute("DROP TABLE IF EXISTS activity_metadata")
        conn.execute("DROP TABLE IF EXISTS suggestions")
        conn.execute("DROP TABLE IF EXISTS assistant_outputs")
        conn.execute("DROP TABLE IF EXISTS activities")
        
        # Create tables
        conn.execute("""
            CREATE TABLE activities (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                app_name TEXT NOT NULL,
                window_title TEXT,
                extracted_text TEXT,
                ai_analysis TEXT,
                duration INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                context_hash TEXT,
                capture_frequency_minutes INTEGER,
                observation_count INTEGER DEFAULT 1,
                last_observed_at TEXT,
                content_fingerprint TEXT
            )
        """)
        
        conn.execute("""
            CREATE TABLE activity_metadata (
                activity_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
                PRIMARY KEY (activity_id, key)
            )
        """)
        
        conn.execute("""
            CREATE VIRTUAL TABLE activities_fts USING fts5(
                content,  -- Combined searchable text
                activity_id UNINDEXED,  -- Reference to main activities table
                timestamp UNINDEXED,
                tokenize='porter unicode61'
            )
        """)
        
        conn.execute("""
            CREATE TABLE assistant_outputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id TEXT NOT NULL,
                output_text TEXT NOT NULL,
                context_text TEXT,
                explanation_text TEXT,
                model_name TEXT,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                was_inserted BOOLEAN DEFAULT FALSE,
                insertion_timestamp TIMESTAMP,
                user_rating INTEGER CHECK (user_rating BETWEEN 1 AND 5),
                user_feedback TEXT,
                user_request TEXT,
                input_modality TEXT,
                FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE
            )
        """)
        
        # Create FTS triggers
        conn.execute("""
            CREATE TRIGGER activities_ai AFTER INSERT ON activities BEGIN
                INSERT INTO activities_fts(content, activity_id, timestamp)
                VALUES (
                    new.window_title || ' ' || 
                    COALESCE(new.extracted_text, '') || ' ' ||
                    new.app_name,
                    new.id,
                    new.timestamp
                );
            END
        """)
        
        conn.commit()
    
    return service

@pytest.fixture
def sqlite_service_for_updates():
    """Create a temporary SQLite service for testing updates."""
    # Use a unique in-memory database for update tests
    db_uri = "file:memdb_updates?mode=memory&cache=shared"
    
    # Create service with the database URI
    service = SQLiteKnowledgeService(db_uri)
    
    # Create tables in the shared memory database
    with get_sync_connection(service.db_path) as conn:
        # Drop existing tables first
        conn.execute("DROP TABLE IF EXISTS activities_fts")
        conn.execute("DROP TABLE IF EXISTS activity_metadata")
        conn.execute("DROP TABLE IF EXISTS assistant_outputs")
        conn.execute("DROP TABLE IF EXISTS activities")
        
        # Create tables
        conn.execute("""
            CREATE TABLE activities (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                app_name TEXT NOT NULL,
                window_title TEXT,
                extracted_text TEXT,
                ai_analysis TEXT,
                duration INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                context_hash TEXT,
                capture_frequency_minutes INTEGER
            )
        """)
        
        conn.execute("""
            CREATE TABLE activity_metadata (
                activity_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
                PRIMARY KEY (activity_id, key)
            )
        """)
        
        conn.execute("""
            CREATE VIRTUAL TABLE activities_fts USING fts5(
                content,  -- Combined searchable text
                activity_id UNINDEXED,  -- Reference to main activities table
                timestamp UNINDEXED,
                tokenize='porter unicode61'
            )
        """)
        
        conn.execute("""
            CREATE TABLE assistant_outputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id TEXT NOT NULL,
                output_text TEXT NOT NULL,
                context_text TEXT,
                explanation_text TEXT,
                model_name TEXT,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                was_inserted BOOLEAN DEFAULT FALSE,
                insertion_timestamp TIMESTAMP,
                user_rating INTEGER CHECK (user_rating BETWEEN 1 AND 5),
                user_feedback TEXT,
                user_request TEXT,
                input_modality TEXT,
                FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE
            )
        """)
        
        # Create FTS triggers
        conn.execute("""
            CREATE TRIGGER activities_ai AFTER INSERT ON activities BEGIN
                INSERT INTO activities_fts(content, activity_id, timestamp)
                VALUES (
                    new.window_title || ' ' || 
                    COALESCE(new.extracted_text, '') || ' ' ||
                    new.app_name,
                    new.id,
                    new.timestamp
                );
            END
        """)
        
        conn.commit()
    
    return service

@pytest.mark.asyncio
async def test_activity_datetime_handling(sqlite_service):
    """Test that datetime objects are handled correctly when storing and retrieving activities."""
    # Create test data with datetime object
    now = datetime.now().replace(microsecond=0)  # Remove microseconds for clean comparison
    test_activity = {
        "timestamp": now,
        "app_name": "TestApp",
        "window_title": "Test Window",
        "extracted_text": "Test content",
    }
    
    # Store activity
    activity_id = await sqlite_service.store_activity(**test_activity)
    
    # Retrieve using search with exact time range
    time_range = {
        "start": now - timedelta(seconds=1),
        "end": now + timedelta(seconds=1)
    }
    
    activities = await sqlite_service.search_activities(time_range=time_range)
    
    # Verify results
    assert len(activities) == 1
    retrieved = activities[0]
    assert retrieved.timestamp == test_activity["timestamp"]
    assert retrieved.app_name == test_activity["app_name"]
    assert retrieved.window_title == test_activity["window_title"]

@pytest.mark.asyncio
async def test_activity_search_time_ranges(sqlite_service):
    """Test that datetime ranges work correctly in activity searches."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)  # Use a fixed time for predictable results
    
    # Store activities at different times
    times = [
        base_time - timedelta(hours=2),
        base_time - timedelta(hours=1),
        base_time,
        base_time + timedelta(hours=1)
    ]
    
    stored_ids = []
    for i, timestamp in enumerate(times):
        activity_id = await sqlite_service.store_activity(
            timestamp=timestamp,
            app_name=f"TestApp{i}",
            window_title="Test Window"
        )
        stored_ids.append(activity_id)
        print(f"Stored activity {activity_id} at {timestamp.isoformat()}")
    
    # Verify what's in the database
    with get_sync_connection(sqlite_service.db_path) as conn:
        cursor = conn.execute("SELECT id, timestamp FROM activities ORDER BY timestamp")
        print("\nStored activities in database:")
        for row in cursor:
            print(f"ID: {row[0]}, Timestamp: {row[1]}")
    
    # Test different time ranges
    test_cases = [
        {
            "range": {
                "start": base_time - timedelta(hours=1.5),
                "end": base_time + timedelta(hours=1.5)
            },
            "expected_count": 3
        },
        {
            "range": {
                "start": base_time - timedelta(hours=2.5),
                "end": base_time - timedelta(hours=1.5)
            },
            "expected_count": 1
        },
        {
            "range": {
                "start": base_time + timedelta(hours=2),
                "end": base_time + timedelta(hours=3)
            },
            "expected_count": 0
        }
    ]
    
    for case in test_cases:
        print(f"\nSearching range: {case['range']['start']} to {case['range']['end']}")
        activities = await sqlite_service.search_activities(time_range=case["range"])
        print(f"Found {len(activities)} activities:")
        for activity in activities:
            print(f"Activity timestamp: {activity.timestamp}")
        assert len(activities) == case["expected_count"], f"Failed for range {case['range']}"

@pytest.mark.asyncio
async def test_activity_metadata_handling(sqlite_service):
    """Test storing and retrieving activities with metadata."""
    timestamp = datetime(2024, 1, 1, 12, 0, 0)
    metadata = {
        "project": "TestProject",
        "category": {"value": "Testing", "confidence": 0.95},
        "tags": ["test", "metadata"]
    }
    
    activity_id = await sqlite_service.store_activity(
        timestamp=timestamp,
        app_name="TestApp",
        window_title="Test Window",
        metadata=metadata
    )
    
    # Retrieve using metadata filter
    activities = await sqlite_service.search_activities(
        metadata_filters={"project": "TestProject"}
    )
    
    assert len(activities) == 1
    assert activities[0].metadata["project"] == "TestProject"
    assert activities[0].metadata["category"] == "Testing"
    
    # Test multiple metadata filters
    activities = await sqlite_service.search_activities(
        metadata_filters={"project": "TestProject", "category": "Testing"}
    )
    assert len(activities) == 1
    
    # Test non-existent metadata
    activities = await sqlite_service.search_activities(
        metadata_filters={"project": "NonExistent"}
    )
    assert len(activities) == 0

@pytest.mark.asyncio
async def test_activity_text_search(sqlite_service):
    """Test full-text search functionality."""
    timestamp = datetime(2024, 1, 1, 12, 0, 0)
    
    # Store activities with different text content
    await sqlite_service.store_activity(
        timestamp=timestamp,
        app_name="TextEditor",
        window_title="Important Document",
        extracted_text="This is a test document about Python programming"
    )
    
    await sqlite_service.store_activity(
        timestamp=timestamp + timedelta(hours=1),
        app_name="Browser",
        window_title="Search Results",
        extracted_text="Searching for JavaScript tutorials"
    )
    
    # Test different search queries
    python_results = await sqlite_service.search_activities(text_search="Python")
    assert len(python_results) == 1
    assert "Python" in python_results[0].extracted_text
    
    js_results = await sqlite_service.search_activities(text_search="JavaScript")
    assert len(js_results) == 1
    assert "JavaScript" in js_results[0].extracted_text
    
    # Test combined search
    programming_results = await sqlite_service.search_activities(text_search="programming tutorials")
    assert len(programming_results) == 2  # Should match both documents
    
    # Test search with special characters
    results = await sqlite_service.search_activities(text_search="Python*")
    assert len(results) == 1  # Should handle special characters gracefully

@pytest.mark.asyncio
async def test_activity_patterns(sqlite_service):
    """Test activity pattern analysis."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    
    # Create more activities to meet the HAVING count > 5 requirement
    for day in range(7):  # Create a week's worth of data
        for hour in range(24):
            await sqlite_service.store_activity(
                timestamp=base_time + timedelta(days=day, hours=hour),
                app_name="DailyApp" if 9 <= hour <= 17 else "EveningApp",
                window_title="Test Window",
                duration=3600  # 1 hour duration
            )
    
    patterns = await sqlite_service.get_activity_patterns(lookback_days=7)
    
    # Check app patterns
    assert "DailyApp" in patterns["apps"]
    assert "EveningApp" in patterns["apps"]
    assert patterns["apps"]["DailyApp"]["frequency"] >= 63  # 9 hours * 7 days
    assert patterns["apps"]["EveningApp"]["frequency"] >= 105  # 15 hours * 7 days
    
    # Check temporal patterns
    assert len(patterns["temporal"]) > 0
    for hour in range(24):
        hour_str = str(hour).zfill(2)
        if hour_str in patterns["temporal"]:
            if 9 <= hour <= 17:
                assert "DailyApp" in patterns["temporal"][hour_str]["active_apps"]
            else:
                assert "EveningApp" in patterns["temporal"][hour_str]["active_apps"]

@pytest.mark.asyncio
async def test_similar_activities_linking(sqlite_service):
    """Test finding similar activities based on content."""
    timestamp = datetime(2024, 1, 1, 12, 0, 0)
    
    # Store activities with similar content
    await sqlite_service.store_activity(
        timestamp=timestamp,
        app_name="TextEditor",
        window_title="Python Guide",
        extracted_text="Guide to Python programming basics"
    )

    await sqlite_service.store_activity(
        timestamp=timestamp + timedelta(minutes=5),
        app_name="TextEditor",
        window_title="Python Tutorial",
        extracted_text="Python programming tutorial for beginners"
    )

    # Search for similar activities
    similar = await sqlite_service.search_activities(
        text_search="Python programming"
    )
    
    assert len(similar) == 2
    assert all("Python" in activity.extracted_text for activity in similar)

@pytest.mark.asyncio
async def test_temporal_sequence_tracking(sqlite_service):
    """Test tracking temporal sequences of activities."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    
    # Create a sequence of activities
    activities = []
    for i in range(3):
        activity = await sqlite_service.store_activity(
            timestamp=base_time + timedelta(minutes=i*2),
            app_name=f"App{i}",
            window_title=f"Window {i}"
        )
        activities.append(activity)

    # Get activities in time order
    results = await sqlite_service.search_activities(
        time_range={
            "start": base_time,
            "end": base_time + timedelta(minutes=10)
        }
    )
    
    # Verify sequence
    assert len(results) == 3
    for i, activity in enumerate(sorted(results, key=lambda x: x.timestamp)):
        assert activity.app_name == f"App{i}"

@pytest.mark.asyncio
async def test_common_sequences(sqlite_service):
    """Test finding common activity sequences."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    
    # Create two similar sequences
    sequence = ["Browser", "TextEditor", "Terminal"]
    for i in range(2):  # Create sequence twice
        for j, app in enumerate(sequence):
            await sqlite_service.store_activity(
                timestamp=base_time + timedelta(hours=i, minutes=j*5),
                app_name=app,
                window_title=f"{app} Window"
            )

    # Get activities for each hour
    for i in range(2):
        hour_start = base_time + timedelta(hours=i)
        results = await sqlite_service.search_activities(
            time_range={
                "start": hour_start,
                "end": hour_start + timedelta(minutes=15)
            }
        )
        
        # Verify sequence
        assert len(results) == 3
        sorted_results = sorted(results, key=lambda x: x.timestamp)
        for j, app in enumerate(sequence):
            assert sorted_results[j].app_name == app

@pytest.mark.asyncio
async def test_activity_context_updates(sqlite_service):
    """Test updating activity context and finding related activities."""
    # Store initial activity
    activity_id = await sqlite_service.store_activity(
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        app_name="TestApp",
        window_title="Initial Window",
        metadata={"status": "initial"}
    )
    
    # Update activity window title using regular connection
    with get_sync_connection(sqlite_service.db_path) as conn:
        conn.execute(
            "UPDATE activities SET window_title = ? WHERE id = ?",
            ("Updated Window", activity_id)
        )
        conn.commit()
    
    # Store new metadata
    await sqlite_service.update_activity_metadata(activity_id, {
        "status": "updated",
        "context": "test"
    })
    
    # Store related activity
    await sqlite_service.store_activity(
        timestamp=datetime(2024, 1, 1, 12, 5, 0),
        app_name="TestApp",
        window_title="Related Window",
        metadata={"context": "test"}
    )
    
    # Find activities with same context
    results = await sqlite_service.search_activities(
        metadata_filters={"context": "test"}
    )
    assert len(results) == 2
    assert any(a.window_title == "Updated Window" for a in results)
    assert any(a.window_title == "Related Window" for a in results)

@pytest.mark.asyncio
async def test_activity_update_with_analysis(sqlite_service):
    """Test updating activities with AI analysis results."""
    # Store initial activity
    activity_id = await sqlite_service.store_activity(
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        app_name="TestApp",
        window_title="Test Window"
    )
    
    # Update with AI analysis using regular connection
    analysis = {
        "topics": ["testing", "software"],
        "sentiment": "neutral",
        "importance": 0.8
    }
    
    with get_sync_connection(sqlite_service.db_path) as conn:
        conn.execute(
            "UPDATE activities SET ai_analysis = ? WHERE id = ?",
            (json.dumps(analysis), activity_id)
        )
        conn.commit()
    
    # Verify update using direct query
    with get_sync_connection(sqlite_service.db_path) as conn:
        cursor = conn.execute(
            "SELECT ai_analysis FROM activities WHERE id = ?",
            (activity_id,)
        )
        row = cursor.fetchone()
        stored_analysis = json.loads(row[0])
        assert stored_analysis["topics"] == analysis["topics"]
        assert stored_analysis["sentiment"] == analysis["sentiment"]
        assert stored_analysis["importance"] == analysis["importance"] 


@pytest.mark.asyncio
async def test_store_activity_keeps_event_loop_responsive_while_worker_write_waits(
    sqlite_service, monkeypatch: pytest.MonkeyPatch
):
    persistence_started = threading.Event()
    release_persistence = threading.Event()
    callback_completed_at: list[float] = []
    loop = asyncio.get_running_loop()

    def _blocked_worker_write(*args, **kwargs) -> str:
        persistence_started.set()
        release_persistence.wait()
        return "worker-activity-id"

    monkeypatch.setattr(
        sqlite_service.activity_storage_repository,
        "_store_activity_synchronously",
        _blocked_worker_write,
    )
    started_at = time.monotonic()
    store_task = asyncio.create_task(
        sqlite_service.store_activity(timestamp=datetime.now(), app_name="TestApp")
    )
    loop.call_soon(lambda: callback_completed_at.append(time.monotonic()))
    fail_safe_release = threading.Timer(0.5, release_persistence.set)
    fail_safe_release.start()

    try:
        await asyncio.to_thread(persistence_started.wait)
        await asyncio.sleep(0)
        assert callback_completed_at
        assert callback_completed_at[0] - started_at < 0.1
    finally:
        release_persistence.set()
        fail_safe_release.cancel()

    assert await store_task == "worker-activity-id"
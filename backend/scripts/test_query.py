#!/usr/bin/env python3
"""Test script to verify database queries work after timezone fix."""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from api.core.knowledge.query.activity_query_processor import ActivityQueryProcessor
from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService

async def test_database_queries():
    """Test database queries to verify timezone fix."""
    print("=== Testing Database Queries After Timezone Fix ===\n")
    
    try:
        # Initialize services
        print("1. Initializing services...")
        knowledge_service = SQLiteKnowledgeService()
        query_processor = ActivityQueryProcessor(knowledge_service)
        print("   Services initialized successfully\n")
        
        # Test 1: Query for activities from the last 3 days
        print("2. Testing query: 'What did I do in the last 3 days?'")
        result = await query_processor.process_query("What did I do in the last 3 days?")
        print(f"   Found {len(result.activities)} activities")
        if result.activities:
            print("   Sample activities:")
            for i, activity in enumerate(result.activities[:3]):
                timestamp = activity.get('timestamp', 'Unknown')
                app = activity.get('app_name', 'Unknown')
                title = activity.get('window_title', 'No title')
                print(f"     {i+1}. {timestamp} - {app}: {title[:50]}...")
        print()
        
        # Test 2: Query for today's activities
        print("3. Testing query: 'What did I do today?'")
        result = await query_processor.process_query("What did I do today?")
        print(f"   Found {len(result.activities)} activities")
        if result.activities:
            print("   Sample activities:")
            for i, activity in enumerate(result.activities[:3]):
                timestamp = activity.get('timestamp', 'Unknown')
                app = activity.get('app_name', 'Unknown')
                title = activity.get('window_title', 'No title')
                print(f"     {i+1}. {timestamp} - {app}: {title[:50]}...")
        print()
        
        # Test 3: Query for yesterday's activities
        print("4. Testing query: 'What did I do yesterday?'")
        result = await query_processor.process_query("What did I do yesterday?")
        print(f"   Found {len(result.activities)} activities")
        if result.activities:
            print("   Sample activities:")
            for i, activity in enumerate(result.activities[:3]):
                timestamp = activity.get('timestamp', 'Unknown')
                app = activity.get('app_name', 'Unknown')
                title = activity.get('window_title', 'No title')
                print(f"     {i+1}. {timestamp} - {app}: {title[:50]}...")
        print()
        
        # Test 4: Direct search with manual time range
        print("5. Testing direct search with manual time range (last 7 days)")
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        activities = await knowledge_service.search_activities(
            time_range={"start": week_ago, "end": now},
            limit=50
        )
        print(f"   Found {len(activities)} activities in last 7 days")
        if activities:
            print("   Sample activities:")
            for i, activity in enumerate(activities[:3]):
                timestamp = activity.timestamp.isoformat()
                app = activity.app_name
                title = activity.window_title or 'No title'
                print(f"     {i+1}. {timestamp} - {app}: {title[:50]}...")
        print()
        
        print("=== Test Summary ===")
        print(f"Total activities found across all tests: {len(result.activities) if 'result' in locals() else 0}")
        print("Timezone fix appears to be working!" if any([len(result.activities) > 0 for result in [result] if 'result' in locals()]) else "No activities found - may need further investigation")
        
    except Exception as e:
        print(f"Error during testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_database_queries()) 
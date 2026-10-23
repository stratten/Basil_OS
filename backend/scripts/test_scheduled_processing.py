#!/usr/bin/env python3
"""Test script to verify scheduled processing system works and process pending activities."""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

async def test_scheduled_processing():
    """Test the scheduled processing system and process pending activities."""
    print("=== Testing Scheduled Processing System ===\n")
    
    try:
        # 1. Check current preferences and activity capture settings
        print("1. Checking current preferences...")
        from api.core.preferences.preferences_io import load_preferences
        preferences = load_preferences()
        
        print(f"   Processing mode: {preferences.activity_capture.processing_mode}")
        print(f"   Scheduled processing hour: {preferences.activity_capture.scheduled_processing_hour}:00")
        print(f"   Frequency: {preferences.activity_capture.frequency_minutes} minutes")
        
        # 2. Get the activity capture scheduler to check pending activities
        print("\n2. Checking activity capture scheduler status...")
        from api.services.activity_capture.activity_capture_scheduler_service import ActivityCaptureScheduler
        from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
        
        # Initialize services (minimal setup for testing)
        knowledge_service = SQLiteKnowledgeService()
        scheduler = ActivityCaptureScheduler(knowledge_service, None, None)
        
        # Get status
        status = await scheduler.get_activity_capture_scheduler_status()
        print(f"   Pending captures: {status['pending_captures_count']}")
        print(f"   Scheduled processing hour: {status['scheduled_processing_hour']}:00")
        print(f"   Next scheduled processing: {status['next_scheduled_processing']}")
        
        # 3. Check database for pending activities
        print("\n3. Checking database for pending activities...")
        
        # Query database for PENDING activities (all dates)
        try:
            pending_activities = await knowledge_service.search_activities(
                metadata_filters={"processing_status": "PENDING"},
                limit=100
            )
            
            print(f"   Found {len(pending_activities)} pending activities in database:")
            
            for activity in pending_activities[:10]:  # Show first 10
                timestamp = activity.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                app_name = activity.app_name
                window_title = (activity.window_title or "")[:50]
                print(f"   - {timestamp} | {app_name} | {window_title}...")
                
            # 4. Load pending activities into scheduler and process them
            if len(pending_activities) > 0:
                print(f"\n4. Loading pending activities into scheduler...")
                
                # Manually call the load method to populate scheduler's queue
                await scheduler._load_pending_activities_from_database()
                
                # Check scheduler status after loading
                status_after_load = await scheduler.get_activity_capture_scheduler_status()
                print(f"   Scheduler now has {status_after_load['pending_captures_count']} pending captures")
                
                if status_after_load['pending_captures_count'] > 0:
                    print(f"\n5. Processing {status_after_load['pending_captures_count']} pending activities...")
                    
                    # Process pending activities
                    processing_result = await scheduler.process_pending_activities()
                    print(f"   Processing result: {processing_result}")
                    
                    # Check status after processing
                    print("\n6. Checking activity status after processing...")
                    
                    # Query for activities by processing status
                    completed_activities = await knowledge_service.search_activities(
                        metadata_filters={"processing_status": "COMPLETED"},
                        limit=10
                    )
                    
                    failed_activities = await knowledge_service.search_activities(
                        metadata_filters={"processing_status": "FAILED"},
                        limit=10
                    )
                    
                    remaining_pending = await knowledge_service.search_activities(
                        metadata_filters={"processing_status": "PENDING"},
                        limit=10
                    )
                    
                    print(f"   COMPLETED: {len(completed_activities)}")
                    print(f"   FAILED: {len(failed_activities)}")
                    print(f"   PENDING: {len(remaining_pending)}")
                    
                else:
                    print("   No activities loaded into scheduler - check metadata filters")
                    
            else:
                print("   No pending activities found in database")
                
        except Exception as e:
            print(f"   Error querying pending activities: {e}")
            import traceback
            traceback.print_exc()
        
        # 5. Test a natural language query to verify processed activities are searchable
        print("\n7. Testing natural language query after processing...")
        try:
            from api.core.knowledge.query.activity_query_processor import ActivityQueryProcessor
            
            query_processor = ActivityQueryProcessor(knowledge_service)
            
            # Test query
            test_queries = [
                "What did I do yesterday?",
                "What activities do I have from the last 3 days?",
                "Show me my recent activity"
            ]
            
            for test_query in test_queries:
                print(f"\n   Testing query: '{test_query}'")
                try:
                    results = await query_processor.process_activity_query(test_query)
                    print(f"   Results: {len(results)} activities found")
                    if results:
                        for i, result in enumerate(results[:3]):  # Show first 3
                            timestamp = result.get('timestamp', 'Unknown')
                            app_name = result.get('app_name', 'Unknown')
                            window_title = result.get('window_title', '')[:50]
                            print(f"   {i+1}. {timestamp} | {app_name} | {window_title}...")
                except Exception as e:
                    print(f"   Query failed: {e}")
        
        except Exception as e:
            print(f"   Error testing queries: {e}")
            
        print("\n=== Test Complete ===")
        
    except Exception as e:
        print(f"Error during testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_scheduled_processing()) 
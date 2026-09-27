#!/usr/bin/env python3
"""
Script to fix activities that were incorrectly marked as COMPLETED when they actually failed.
These activities have processing_status=COMPLETED but ai_analysis=None or ai_analysis="None".
"""
import sys
import os
sys.path.append('backend/src')

import asyncio
from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from datetime import datetime, timedelta

async def fix_corrupted_activities():
    """Find and fix activities that were incorrectly marked as COMPLETED."""
    
    # Initialize knowledge service
    knowledge_service = SQLiteKnowledgeService()
    
    print("🔍 Searching for corrupted activities...")
    
    # Get activities marked as COMPLETED
    completed_activities = await knowledge_service.search_activities(
        metadata_filters={"processing_status": "COMPLETED"},
        limit=1000
    )
    
    print(f"📊 Found {len(completed_activities)} activities marked as COMPLETED")
    
    corrupted_count = 0
    fixed_count = 0
    
    for activity in completed_activities:
        # Check if this activity actually failed (no AI analysis)
        metadata = activity.metadata if hasattr(activity, 'metadata') else activity.get('metadata', {})
        ai_analysis = metadata.get('ai_analysis')
        analysis_type = metadata.get('analysis_type', '')
        
        # Activity is corrupted if:
        # 1. It's marked as COMPLETED
        # 2. But has no AI analysis (None, "None", or analysis_type="none")
        is_corrupted = (
            ai_analysis is None or 
            ai_analysis == "None" or 
            analysis_type == "none"
        )
        
        if is_corrupted:
            corrupted_count += 1
            activity_id = activity.id if hasattr(activity, 'id') else activity.get('id')
            timestamp = activity.timestamp if hasattr(activity, 'timestamp') else activity.get('timestamp')
            app_name = activity.app_name if hasattr(activity, 'app_name') else activity.get('app_name')
            
            print(f"🔧 Fixing corrupted activity: {activity_id} - {app_name} at {timestamp}")
            
            try:
                # Reset the status to PENDING so it can be reprocessed
                await knowledge_service.update_activity_metadata(
                    activity_id,
                    {
                        "processing_status": "PENDING",
                        "analysis_type": None,  # Clear the failed analysis type
                        "ai_analysis": None,    # Clear the empty AI analysis
                        "model_used": None,     # Clear the model that failed
                        "processing_completed_at": None,  # Clear completion time
                        "processing_time_ms": None,       # Clear timing
                    }
                )
                fixed_count += 1
                print(f"✅ Fixed activity {activity_id}")
                
            except Exception as e:
                print(f"❌ Failed to fix activity {activity_id}: {e}")
    
    print(f"\n📈 Summary:")
    print(f"   Total COMPLETED activities: {len(completed_activities)}")
    print(f"   Corrupted activities found: {corrupted_count}")
    print(f"   Successfully fixed: {fixed_count}")
    
    if fixed_count > 0:
        print(f"\n🎉 {fixed_count} activities have been reset to PENDING status and can now be reprocessed!")
    else:
        print(f"\n✨ No corrupted activities found - all COMPLETED activities have valid AI analysis.")

if __name__ == "__main__":
    asyncio.run(fix_corrupted_activities()) 
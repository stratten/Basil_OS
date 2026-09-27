#!/usr/bin/env python3
"""
Script to check the contents of the most recent todos in the unified database.
This will show exactly what was persisted during our test run.
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

def get_db_path():
    """Get the path to the knowledge base database."""
    home = Path.home()
    db_path = home / ".basil" / "knowledge_base.db"
    return str(db_path)

def format_json_field(json_str):
    """Format JSON field for better readability."""
    if not json_str:
        return "None"
    try:
        data = json.loads(json_str)
        return json.dumps(data, indent=2)
    except:
        return json_str

def check_recent_todos():
    """Check the most recent todos in the unified database."""
    db_path = get_db_path()
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found at: {db_path}")
        return
    
    print(f"📊 Checking database at: {db_path}")
    print("=" * 80)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if unified_todos table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='unified_todos'")
        if not cursor.fetchone():
            print("❌ unified_todos table does not exist")
            return
            
        # Get the 2 most recent todos
        print("🔍 QUERYING MOST RECENT TODOS...")
        cursor.execute("""
            SELECT 
                todo_id,
                title,
                description,
                status,
                complexity_score,
                priority,
                parent_task_id,
                pre_retrieved_data,
                data_assignment,
                initial_context,
                current_context,
                created_at,
                started_at,
                completed_at,
                completion_summary,
                error_message
            FROM unified_todos 
            ORDER BY created_at DESC 
            LIMIT 2
        """)
        
        todos = cursor.fetchall()
        
        if not todos:
            print("❌ No todos found in unified_todos table")
            return
            
        print(f"✅ Found {len(todos)} recent todos")
        print("=" * 80)
        
        # Display each todo
        for i, todo in enumerate(todos, 1):
            print(f"\n📋 TODO #{i}")
            print("-" * 40)
            print(f"ID: {todo[0]}")
            print(f"Title: {todo[1]}")
            print(f"Description: {todo[2]}")
            print(f"Status: {todo[3]}")
            print(f"Complexity Score: {todo[4]}")
            print(f"Priority: {todo[5]}")
            print(f"Parent Agent Task: {todo[6]}")
            print(f"Created At: {todo[11]}")
            print(f"Started At: {todo[12]}")
            print(f"Completed At: {todo[13]}")
            print(f"Completion Summary: {todo[14]}")
            print(f"Error Message: {todo[15]}")
            
            print(f"\n📦 PRE-RETRIEVED DATA:")
            print(format_json_field(todo[7]))
            
            print(f"\n📋 DATA ASSIGNMENT:")
            print(format_json_field(todo[8]))
            
            print(f"\n🔄 INITIAL CONTEXT:")
            print(format_json_field(todo[9]))
            
            print(f"\n🔄 CURRENT CONTEXT:")
            print(format_json_field(todo[10]))
            
            # Get steps for this todo
            print(f"\n🔧 STEPS FOR TODO {todo[0]}:")
            cursor.execute("""
                SELECT 
                    step_id,
                    step_number,
                    description,
                    planned_service,
                    planned_method,
                    parameter_template,
                    status,
                    created_at,
                    started_at,
                    completed_at,
                    actual_parameters,
                    result,
                    error_message,
                    context_at_step,
                    method_signature,
                    documentation,
                    execution_principles
                FROM unified_todo_steps 
                WHERE todo_id = ? 
                ORDER BY step_number
            """, (todo[0],))
            
            steps = cursor.fetchall()
            
            for j, step in enumerate(steps, 1):
                print(f"\n  🔹 STEP {step[1]} (ID: {step[0]})")
                print(f"    Description: {step[2]}")
                print(f"    Planned Service: {step[3]}")
                print(f"    Planned Method: {step[4]}")
                print(f"    Status: {step[6]}")
                print(f"    Created At: {step[7]}")
                print(f"    Started At: {step[8]}")
                print(f"    Completed At: {step[9]}")
                print(f"    Error Message: {step[12]}")
                
                if step[5]:  # parameter_template
                    print(f"    Parameter Template:")
                    print(f"      {format_json_field(step[5])}")
                
                if step[10]:  # actual_parameters
                    print(f"    Actual Parameters:")
                    print(f"      {format_json_field(step[10])}")
                
                if step[11]:  # result
                    print(f"    Result:")
                    print(f"      {format_json_field(step[11])}")
                
                if step[13]:  # context_at_step
                    print(f"    Context At Step:")
                    print(f"      {format_json_field(step[13])}")
                
                if step[14]:  # method_signature
                    print(f"    Method Signature: {step[14]}")
                
                if step[15]:  # documentation
                    print(f"    Documentation: {step[15]}")
                
                if step[16]:  # execution_principles
                    print(f"    Execution Principles:")
                    print(f"      {format_json_field(step[16])}")
            
            print("\n" + "=" * 80)
        
        # Show table schemas for reference
        print("\n📊 TABLE SCHEMAS:")
        print("-" * 40)
        
        cursor.execute("PRAGMA table_info(unified_todos)")
        todo_schema = cursor.fetchall()
        print("\n🗂️ unified_todos schema:")
        for col in todo_schema:
            print(f"  {col[1]} ({col[2]}) - PK: {bool(col[5])}, NotNull: {bool(col[3])}")
        
        cursor.execute("PRAGMA table_info(unified_todo_steps)")
        step_schema = cursor.fetchall()
        print("\n🗂️ unified_todo_steps schema:")
        for col in step_schema:
            print(f"  {col[1]} ({col[2]}) - PK: {bool(col[5])}, NotNull: {bool(col[3])}")
        
    except Exception as e:
        print(f"❌ Error querying database: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    check_recent_todos() 
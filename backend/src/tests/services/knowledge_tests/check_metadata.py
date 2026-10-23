import sqlite3
from pathlib import Path

# Connect to the database
db_path = Path.home() / ".basil" / "knowledge_base.db"
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

# Check the activity metadata
activity_id = "27dcb97c-cf56-41ec-9882-d55b379bc94f"
cursor = conn.execute('''
    SELECT key, value 
    FROM activity_metadata 
    WHERE activity_id = ?
''', (activity_id,))
rows = cursor.fetchall()
print(f'Metadata for activity {activity_id}:')
if rows:
    for row in rows:
        print(f'  {row["key"]}: {row["value"]}')
else:
    print("  No metadata found")

# Close the connection
conn.close() 
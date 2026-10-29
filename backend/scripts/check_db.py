import sqlite3
from pathlib import Path

# Connect to the database
db_path = Path.home() / ".basil" / "knowledge_base.db"
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

# Check the number of activities
cursor = conn.execute('SELECT COUNT(*) FROM activities')
count = cursor.fetchone()[0]
print(f'Number of activities: {count}')

# Check the most recent activities
cursor = conn.execute('''
    SELECT id, timestamp, app_name, window_title 
    FROM activities 
    ORDER BY timestamp DESC 
    LIMIT 5
''')
rows = cursor.fetchall()
print("\nMost recent activities:")
for row in rows:
    print(f'ID: {row["id"]}, Time: {row["timestamp"]}, App: {row["app_name"]}, Title: {row["window_title"]}')

# Check if the activity from the logs exists
activity_id = "27dcb97c-cf56-41ec-9882-d55b379bc94f"
cursor = conn.execute('SELECT COUNT(*) FROM activities WHERE id = ?', (activity_id,))
count = cursor.fetchone()[0]
print(f'\nActivity {activity_id} exists in database: {count > 0}')

# Close the connection
conn.close() 
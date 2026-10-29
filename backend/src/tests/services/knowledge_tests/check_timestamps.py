import sqlite3
from pathlib import Path
from datetime import datetime

# Connect to the database
db_path = Path.home() / ".basil" / "knowledge_base.db"
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

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

# Check activities for today
today = datetime.now().strftime("%Y-%m-%d")
print(f"\nChecking activities for today ({today}):")
cursor = conn.execute('''
    SELECT id, timestamp, app_name, window_title 
    FROM activities 
    WHERE timestamp >= ? AND timestamp <= ?
    ORDER BY timestamp DESC
''', (f"{today}T00:00:00", f"{today}T23:59:59.999999"))
rows = cursor.fetchall()
if rows:
    for row in rows:
        print(f'ID: {row["id"]}, Time: {row["timestamp"]}, App: {row["app_name"]}, Title: {row["window_title"]}')
else:
    print("No activities found for today with exact date match")

# Try a more flexible search
print("\nTrying a more flexible search for today:")
cursor = conn.execute('''
    SELECT id, timestamp, app_name, window_title 
    FROM activities 
    WHERE timestamp LIKE ?
    ORDER BY timestamp DESC
''', (f"{today}%",))
rows = cursor.fetchall()
if rows:
    for row in rows:
        print(f'ID: {row["id"]}, Time: {row["timestamp"]}, App: {row["app_name"]}, Title: {row["window_title"]}')
else:
    print("No activities found for today with LIKE search")

# Close the connection
conn.close() 
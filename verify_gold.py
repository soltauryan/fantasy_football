import sqlite3
DB_PATH = r"c:\Users\solta\repos\fantasy_football\data\nfl.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
try:
    count = cursor.execute("SELECT COUNT(*) FROM gold_master_rankings").fetchone()[0]
    print(f"gold_master_rankings: {count} rows")
except Exception as e:
    print(f"Error: {e}")
conn.close()

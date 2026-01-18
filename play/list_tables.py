import sqlite3
DB_PATH = r"c:\Users\solta\repos\fantasy_football\data\nfl.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print([row[0] for row in cursor.fetchall()])
conn.close()

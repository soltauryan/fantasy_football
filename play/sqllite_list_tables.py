import sqlite3

conn = sqlite3.connect('data/nfl.db')
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()

for table in tables:
    print(table[0])
    cursor.execute(f"PRAGMA table_info({table[0]})")
    columns = cursor.fetchall()
    # for column in columns:
    #     print(column)
    print("\n")

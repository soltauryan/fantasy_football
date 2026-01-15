import sqlite3
DB_PATH = r"c:\Users\solta\repos\fantasy_football\data\nfl.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
tables = ['silver_players', 'silver_weekly_performance', 'silver_depth_charts']
for t in tables:
    try:
        count = cursor.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t}: {count} rows")
        # Print columns for one of them to verify schema
        if t == 'silver_weekly_performance':
            cursor.execute(f"PRAGMA table_info({t});")
            cols = [c[1] for c in cursor.fetchall()]
            print(f"  Columns: {', '.join(cols)}")
    except Exception as e:
        print(f"Error checking {t}: {e}")
conn.close()

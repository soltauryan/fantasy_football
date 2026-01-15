import sqlite3
import polars as pl
import os
import sys

# Ensure stdout can handle UTF-8 characters if possible
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_PATH = r"c:\Users\solta\repos\fantasy_football\data\nfl.db"

def list_tables(cursor):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    return [row[0] for row in cursor.fetchall()]

def get_row_count(cursor, table_name):
    cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
    return cursor.fetchone()[0]

def get_schema(cursor, table_name):
    # This returns a list of tuples: (id, name, type, notnull, default_value, pk)
    cursor.execute(f"PRAGMA table_info({table_name});")
    return cursor.fetchall()

def main():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    tables = list_tables(cursor)
    print(f"Found {len(tables)} tables in {DB_PATH}:\n")

    for table in tables:
        count = get_row_count(cursor, table)
        schema = get_schema(cursor, table)
        columns = [col[1] for col in schema]
        print(f"Table: {table}")
        print(f"  Rows: {count}")
        print(f"  Columns: {', '.join(columns)}")
        
        if count > 0:
            # Sample data using polars
            try:
                # Using a generic query to sample 5 rows
                df_sample = pl.read_database(
                    query=f"SELECT * FROM {table} LIMIT 5",
                    connection=conn
                )
                print("\nSample Data:")
                print(df_sample)
            except Exception as e:
                print(f"\nCould not sample data: {e}")
        
        print("-" * 60)

    conn.close()

if __name__ == "__main__":
    main()

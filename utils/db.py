import sqlite3
import os
import polars as pl

# Resolve absolute path to database relative to this file
# utils/ is one level deep, so project root is one level up
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "nfl.db")

def get_connection(db_path=DB_PATH):
    """
    Get a connection to the SQLite database.
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return sqlite3.connect(db_path)

def read_sqlite_robust(query, conn):
    """
    Read SQLite query into Polars DataFrame.
    Fetches as list of dicts first to avoid TypeErrors during Polars inference.
    """
    cursor = conn.cursor()
    cursor.execute(query)

    if cursor.description is None:
        return pl.DataFrame()

    columns = [description[0] for description in cursor.description]
    data = [dict(zip(columns, row)) for row in cursor.fetchall()]

    # Handle empty result sets
    if not data:
        return pl.DataFrame()

    return pl.from_dicts(data, infer_schema_length=None)

"""
Ingest 2026 Rookies
Reads a CSV of rookie data and appends/merges them into gold_projections_2026.
"""

import polars as pl
import os
import sys

# Add project root to path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.db import DB_PATH

ROOKIE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "rookies_2026.csv")

def ingest_rookies():
    print("Ingesting Rookies...")
    if not os.path.exists(ROOKIE_FILE):
        print(f"Error: Rookie file not found at {ROOKIE_FILE}")
        print("Please create this file with columns: player_name, position, proj_ppg_2026")
        return

    df_rookies = pl.read_csv(ROOKIE_FILE)
    
    # Add generated columns
    df_rookies = df_rookies.with_columns([
        pl.lit("ROOKIE").alias("gsis_id"), # placeholder ID
        (pl.col("proj_ppg_2026") * 17).alias("proj_total_points_2026")
    ])
    
    # Ensure columns match target table
    # gold_projections_2026 cols: gsis_id, player_name, position, proj_ppg_2026, proj_total_points_2026
    df_rookies = df_rookies.select([
        "gsis_id", "player_name", "position", "proj_ppg_2026", "proj_total_points_2026"
    ])
    
    print(f"Found {len(df_rookies)} rookies.")
    
    # Append to database
    # checking if table exists happen via append mode or we read relevant table first
    # using 'append' in write_database usually appends.
    
    try:
        df_rookies.write_database(
            table_name="gold_projections_2026",
            connection=f"sqlite:///{DB_PATH}",
            if_table_exists="append",
            engine="adbc"
        )
        print("Rookies added to gold_projections_2026.")
    except Exception as e:
        print(f"Error adding rookies: {e}")

if __name__ == "__main__":
    ingest_rookies()

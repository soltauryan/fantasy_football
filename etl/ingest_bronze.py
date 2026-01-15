import nflreadpy as nfl
import os
import polars as pl

def ingest_bronze():
    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    
    db_path = "sqlite:///data/nfl.db"
    years = [2023, 2024, 2025]
    # Injuries data for 2025 seems unavailable (404), so we exclude it.
    years_injuries = [2023, 2024]
    
    # Define tasks: (table_name, function, kwargs)
    tasks = [
        ("bronze_ff_rankings", nfl.load_ff_rankings, {}),
        ("bronze_player_stats", nfl.load_player_stats, {"seasons": years}),
        ("bronze_team_stats", nfl.load_team_stats, {"seasons": years}),
        ("bronze_schedules", nfl.load_schedules, {"seasons": years}),
        ("bronze_players", nfl.load_players, {}),
        ("bronze_snap_counts", nfl.load_snap_counts, {"seasons": years}),
        ("bronze_nextgen_passing", nfl.load_nextgen_stats, {"seasons": years, "stat_type": "passing"}),
        ("bronze_nextgen_rushing", nfl.load_nextgen_stats, {"seasons": years, "stat_type": "rushing"}),
        ("bronze_nextgen_receiving", nfl.load_nextgen_stats, {"seasons": years, "stat_type": "receiving"}),
        ("bronze_ftn_charting", nfl.load_ftn_charting, {"seasons": years}),
        ("bronze_injuries", nfl.load_injuries, {"seasons": years_injuries}),
        ("bronze_depth_charts", nfl.load_depth_charts, {"seasons": years}),
        ("bronze_ff_playerids", nfl.load_ff_playerids, {}),
        ("bronze_ff_opportunity", nfl.load_ff_opportunity, {"seasons": years}),
    ]

    print(f"Starting Bronze Layer Ingestion for years: {years} (where applicable)...")

    for table_name, func, kwargs in tasks:
        print(f"Ingesting {table_name}...")
        try:
            df = func(**kwargs)
            
            if hasattr(df, 'to_sql'): 
                 df = pl.from_pandas(df)
            
            print(f"  -> Loaded {len(df)} rows.")
            
            df.write_database(
                table_name=table_name,
                connection=db_path,
                if_table_exists="replace",
                engine="adbc"
            )
            print(f"  -> Saved to {table_name}.")
            
        except Exception as e:
            print(f"  -> ERROR ingesting {table_name}: {e}")

    print("Bronze layer ingestion complete.")

if __name__ == "__main__":
    ingest_bronze()

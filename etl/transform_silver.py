import polars as pl
import sqlite3
import os
import sys

# Add project root to path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.db import get_connection, read_sqlite_robust, DB_PATH

def transform_players(conn):
    print("Transforming silver_players...")
    query = "SELECT * FROM bronze_ff_playerids"
    df = read_sqlite_robust(query, conn)
    
    # Select and rename key columns
    silver_players = df.select([
        pl.col("gsis_id").cast(pl.String),
        pl.col("sleeper_id").cast(pl.String),
        pl.col("espn_id").cast(pl.String),
        pl.col("yahoo_id").cast(pl.String),
        pl.col("name").alias("full_name"),
        pl.col("position"),
        pl.col("team"),
        pl.col("birthdate"),
        pl.col("age"),
        pl.col("draft_year"),
    ]).filter(pl.col("gsis_id").is_not_null())
    
    # Drop duplicates if any
    silver_players = silver_players.unique(subset=["gsis_id"])
    
    return silver_players

def transform_weekly_performance(conn):
    print("Transforming silver_weekly_performance...")
    
    # 1. Base: ff_opportunity
    df_opp = read_sqlite_robust("SELECT * FROM bronze_ff_opportunity", conn)
    
    # Standardize types for joining
    df_opp = df_opp.with_columns([
        pl.col("player_id").cast(pl.String).alias("gsis_id"),
        pl.col("season").cast(pl.Int64),
        pl.col("week").cast(pl.Int64)
    ])

    # 2. NextGen QB Stats
    df_ng_qb = read_sqlite_robust("SELECT * FROM bronze_nextgen_passing", conn)
    df_ng_qb = df_ng_qb.with_columns([
        pl.col("player_gsis_id").cast(pl.String).alias("gsis_id"),
        pl.col("season").cast(pl.Int64),
        pl.col("week").cast(pl.Int64)
    ]).select([
        "gsis_id", "season", "week", 
        "avg_time_to_throw", "avg_completed_air_yards", "passer_rating"
    ])

    # 3. NextGen Rushing Stats
    df_ng_rush = read_sqlite_robust("SELECT * FROM bronze_nextgen_rushing", conn)
    df_ng_rush = df_ng_rush.with_columns([
        pl.col("player_gsis_id").cast(pl.String).alias("gsis_id"),
        pl.col("season").cast(pl.Int64),
        pl.col("week").cast(pl.Int64)
    ]).select([
        "gsis_id", "season", "week", 
        "efficiency", "rush_yards_over_expected_per_att"
    ])

    # 4. NextGen Receiving Stats
    df_ng_rec = read_sqlite_robust("SELECT * FROM bronze_nextgen_receiving", conn)
    df_ng_rec = df_ng_rec.with_columns([
        pl.col("player_gsis_id").cast(pl.String).alias("gsis_id"),
        pl.col("season").cast(pl.Int64),
        pl.col("week").cast(pl.Int64)
    ]).select([
        "gsis_id", "season", "week", 
        "avg_separation", "avg_yac_above_expectation"
    ])

    # Join them all together
    silver_weekly = df_opp.join(df_ng_qb, on=["gsis_id", "season", "week"], how="left") \
                          .join(df_ng_rush, on=["gsis_id", "season", "week"], how="left") \
                          .join(df_ng_rec, on=["gsis_id", "season", "week"], how="left")

    # Final selection and cleaning
    silver_weekly = silver_weekly.select([
        pl.col("season"),
        pl.col("week"),
        pl.col("gsis_id"),
        pl.col("full_name"),
        pl.col("position"),
        pl.col("posteam").alias("team"),
        pl.col("total_fantasy_points").alias("fantasy_points"),
        pl.col("total_fantasy_points_exp").alias("expected_fantasy_points"),
        pl.col("rush_attempt"),
        pl.col("rush_yards_gained").alias("rush_yards"),
        pl.col("rec_attempt").alias("targets"),
        pl.col("receptions"),
        pl.col("rec_yards_gained").alias("rec_yards"),
        pl.col("avg_time_to_throw"),
        pl.col("avg_completed_air_yards"),
        pl.col("passer_rating"),
        pl.col("efficiency"),
        pl.col("rush_yards_over_expected_per_att"),
        pl.col("avg_separation"),
        pl.col("avg_yac_above_expectation")
    ])
    
    return silver_weekly

def transform_depth_charts(conn):
    print("Transforming silver_depth_charts...")
    df = read_sqlite_robust("SELECT * FROM bronze_depth_charts", conn)
    
    silver_depth = df.filter(
        pl.col("position").is_in(["QB", "RB", "WR", "TE"])
    ).select([
        pl.col("season").cast(pl.Int64),
        pl.col("week").cast(pl.Int64),
        pl.col("gsis_id").cast(pl.String),
        pl.col("full_name"),
        pl.col("position"),
        pl.col("team"),
        pl.col("depth_team"),
        pl.col("depth_position"),
        pl.col("formation"),
    ])
    
    return silver_depth

def main():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = get_connection()
    
    try:
        # Transform
        df_players = transform_players(conn)
        df_weekly = transform_weekly_performance(conn)
        df_depth = transform_depth_charts(conn)
        
        # Write to SQLite
        print("Writing to database...")
        # Using sqlite3's to_sql equivalent via polars' write_database
        # Note: Polars write_database with default engine 'sqlalchemy' or 'adbc'
        # We'll use 'adbc' if possible, or just fallback to sqlalchemy if needed in the user's env
        
        df_players.write_database(
            table_name="silver_players",
            connection=f"sqlite:///{DB_PATH}",
            if_table_exists="replace"
        )
        print("Written silver_players")
        
        df_weekly.write_database(
            table_name="silver_weekly_performance",
            connection=f"sqlite:///{DB_PATH}",
            if_table_exists="replace"
        )
        print("Written silver_weekly_performance")
        
        df_depth.write_database(
            table_name="silver_depth_charts",
            connection=f"sqlite:///{DB_PATH}",
            if_table_exists="replace"
        )
        print("Written silver_depth_charts")
        
        print("\nSilver Layer transformations complete!")
        
    except Exception as e:
        print(f"Error during transformations: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()

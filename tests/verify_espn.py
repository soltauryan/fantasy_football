import polars as pl
import sqlite3

db_path = "data/nfl.db"

try:
    print("--- bronze_espn_teams ---")
    df = pl.read_database_uri("SELECT * FROM bronze_espn_teams", f"sqlite:///{db_path}", engine="adbc")
    print(df)
except Exception as e:
    print(f"Error reading teams: {e}")

try:
    print("\n--- bronze_espn_matchups ---")
    df = pl.read_database_uri("SELECT * FROM bronze_espn_matchups", f"sqlite:///{db_path}", engine="adbc")
    print(df)
except Exception as e:
    print(f"Error reading matchups: {e}")

try:
    print("\n--- bronze_espn_draft ---")
    df = pl.read_database_uri("SELECT * FROM bronze_espn_draft LIMIT 5", f"sqlite:///{db_path}", engine="adbc")
    print(df)
except Exception as e:
    print(f"Error reading draft: {e}")

try:
    print("\n--- bronze_espn_rosters ---")
    df = pl.read_database_uri("SELECT * FROM bronze_espn_rosters LIMIT 5", f"sqlite:///{db_path}", engine="adbc")
    print(df)
except Exception as e:
    print(f"Error reading rosters: {e}")

try:
    print("\n--- bronze_espn_activity ---")
    df = pl.read_database_uri("SELECT * FROM bronze_espn_activity LIMIT 5", f"sqlite:///{db_path}", engine="adbc")
    print(df)
except Exception as e:
    print(f"Error reading activity: {e}")

try:
    print("\n--- bronze_espn_league_info ---")
    df = pl.read_database_uri("SELECT * FROM bronze_espn_league_info", f"sqlite:///{db_path}", engine="adbc")
    print(df)
except Exception as e:
    print(f"Error reading league info: {e}")

try:
    print("\n--- bronze_espn_free_agents ---")
    df = pl.read_database_uri("SELECT * FROM bronze_espn_free_agents LIMIT 5", f"sqlite:///{db_path}", engine="adbc")
    print(df)
except Exception as e:
    print(f"Error reading free agents: {e}")

try:
    print("\n--- bronze_espn_power_rankings ---")
    df = pl.read_database_uri("SELECT * FROM bronze_espn_power_rankings LIMIT 5", f"sqlite:///{db_path}", engine="adbc")
    print(df)
except Exception as e:
    print(f"Error reading power rankings: {e}")

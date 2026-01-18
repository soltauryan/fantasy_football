import polars as pl
DB_PATH = "sqlite:///data/nfl.db"

try:
    df = pl.read_database_uri("SELECT * FROM bronze_espn_matchup_players LIMIT 5", DB_PATH, engine="adbc")
    print(df)
    print(df.schema)
except Exception as e:
    print(e)

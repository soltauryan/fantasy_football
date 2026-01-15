import polars as pl
import sqlite3
import os
import sys

# Force UTF-8 output for windows terminal
if sys.stdout.encoding != 'utf-8':
    import io
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

db_path = "data/nfl.db"
db_uri = "sqlite://data/nfl.db"

def read_sqlite_robust(query, conn):
    # Use sqlite3 to fetch data into list of dicts to avoid Polars inference panics
    # SQLite's loose typing can cause Polars to fail during schema inference
    cursor = conn.cursor()
    cursor.execute(query)
    columns = [description[0] for description in cursor.description]
    data = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return pl.from_dicts(data, infer_schema_length=None)

def generate_master_rankings():
    print("Loading data from database...")
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    
    try:
        # Load rankings
        print("Reading bronze_ff_rankings...")
        df_rankings = read_sqlite_robust("SELECT * FROM bronze_ff_rankings", conn)
        
        # Load player IDs for mapping
        print("Reading bronze_ff_playerids...")
        df_ids = read_sqlite_robust("SELECT * FROM bronze_ff_playerids", conn)
        
    finally:
        conn.close()

    if df_rankings.is_empty():
        print("No rankings data found.")
        return

    # 1. Prepare Rankings Data
    # id in bronze_ff_rankings is the FantasyPros ID
    # Filter out null IDs if any
    # Columns in bronze_ff_rankings are likely strings initially due to read_sqlite_robust
    df_rankings = df_rankings.with_columns([
        pl.col("id").cast(pl.String),
        pl.col("ecr").cast(pl.Float64)
    ]).filter(pl.col("id").is_not_null())
    
    # Define a 'source' based on page_type and ecr_type
    df_rankings = df_rankings.with_columns([
        (pl.col("page_type") + "_" + pl.col("ecr_type")).alias("source_key")
    ])

    print(f"Normalizing {len(df_rankings)} ranking entries across {df_rankings['source_key'].n_unique()} sources...")

    # 2. Normalize Scores
    # We calculate percentile within each source_key
    # Formula: 100 * (1 - (ecr - 1) / (max_rank - 1))
    
    df_rankings = df_rankings.with_columns(
        pl.col("ecr").max().over("source_key").alias("max_rank_in_source")
    ).with_columns(
        pl.when(pl.col("max_rank_in_source") > 1)
        .then(100.0 * (1.0 - (pl.col("ecr") - 1.0) / (pl.col("max_rank_in_source") - 1.0)))
        .otherwise(100.0)
        .alias("normalized_score")
    )

    # 3. Join with Player IDs
    # Normalize IDs data to join on fantasypros_id
    # bronze_ff_playerids has 'fantasypros_id'
    df_ids = df_ids.select([
        pl.col("fantasypros_id").cast(pl.String).alias("id"),
        pl.col("gsis_id").cast(pl.String),
        pl.col("sleeper_id").cast(pl.String),
        pl.col("nfl_id").cast(pl.String),
        pl.col("name"),
        pl.col("position"),
        pl.col("team")
    ]).filter(pl.col("id").is_not_null())
    
    # Perform join
    # We use a left join from rankings to IDs to keep rankings even if ID mapping is missing
    df_merged = df_rankings.join(df_ids, on="id", how="left", suffix="_mapped")

    # 4. Aggregate Master Scores
    # We group by the unique player identifiers. 
    # Use name, position, team from the IDs table if available, otherwise from rankings.
    # Rankings table likely has 'player', 'pos', 'tm' from bronze
    
    # Coalesce to handle missing mappings
    # Check if 'player', 'pos', 'tm' exist in df_rankings (from bronze)
    # The robust reader preserves column names roughly
    
    columns = df_merged.columns
    name_col = "player" if "player" in columns else "name" # Fallback
    pos_col = "pos" if "pos" in columns else "position"
    team_col = "tm" if "tm" in columns else "team"
    
    # Determine columns for coalescing
    # IDs table provided: name, position, team
    # Rankings table provided: player (likely), pos (likely), tm (likely), and possibly team
    
    # If a column collided, it has _mapped suffix (from IDs) and the original (from Rankings)
    # If it didn't collide, the ID column usually persists as is (name, position)
    
    # helper to get ID column name
    def get_id_col(base, suffix="_mapped"):
        return f"{base}{suffix}" if f"{base}{suffix}" in df_merged.columns else base

    # We want to prefer the ID table's version (mapped/base) over the Rankings table's version (player/pos/tm)
    
    final_name_col = get_id_col("name") # Likely 'name'
    final_pos_col = get_id_col("position") # Likely 'position'
    final_team_col = get_id_col("team") # Likely 'team_mapped' based on error
    
    df_merged = df_merged.with_columns([
        pl.coalesce(pl.col(final_name_col), pl.col(name_col)).alias("final_name"),
        pl.coalesce(pl.col(final_pos_col), pl.col(pos_col)).alias("final_pos"),
        pl.coalesce(pl.col(final_team_col), pl.col(team_col)).alias("final_team")
    ])

    print("Aggregating master scores...")
    # Group by mapped ID (gsis_id) if available, otherwise fallback to fantasypros id
    # Actually, master rankings should ideally be keyed by GSIS ID for downstream use.
    # If no GSIS ID, we keep the fantasypros ID as a fallback key or just ID.
    
    df_merged = df_merged.with_columns(
        pl.coalesce(pl.col("gsis_id"), pl.col("id")).alias("master_id")
    )

    df_master = df_merged.group_by("master_id").agg([
        pl.col("final_name").first().alias("player_name"),
        pl.col("final_pos").first().alias("position"),
        pl.col("final_team").first().alias("team"),
        pl.col("normalized_score").mean().alias("master_score"),
        pl.col("ecr").mean().alias("avg_raw_rank"),
        pl.col("source_key").count().alias("rank_count"),
        
        # Keep keys
        pl.col("gsis_id").first(),
        pl.col("sleeper_id").first(),
        pl.col("nfl_id").first(),
        pl.col("id").first().alias("fantasypros_id")
    ])

    # 5. Calculate Master Rank
    df_master = df_master.sort("master_score", descending=True).with_columns(
        pl.arange(1, pl.len() + 1).alias("master_rank")
    )

    # 6. Save to Database
    print(f"Saving {len(df_master)} processed players to gold_master_rankings...")
    
    df_master.write_database(
        table_name="gold_master_rankings",
        connection=db_uri,
        if_table_exists="replace",
        engine="adbc"
    )

    print("Generation complete!")
    print("\nTop 10 Master Rankings:")
    print(df_master.select(["master_rank", "player_name", "position", "team", "master_score"]).head(10))

if __name__ == "__main__":
    generate_master_rankings()

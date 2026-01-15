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

def read_sqlite_robust(query, conn):
    cursor = conn.cursor()
    cursor.execute(query)
    columns = [description[0] for description in cursor.description]
    data = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return pl.from_dicts(data, infer_schema_length=None)

def analyze_nextgen():
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    
    try:
        print("Loading Silver Layer (Weekly Performance)...")
        df_weekly = read_sqlite_robust("SELECT * FROM silver_weekly_performance", conn)
        
        print("Loading Gold Layer (Master Rankings)...")
        df_gold = read_sqlite_robust("SELECT * FROM gold_master_rankings", conn)
        
    finally:
        conn.close()

    # 1. Clean and Cast Types
    # Weekly stats need to be numeric for aggregation
    metric_cols = [
        "fantasy_points", 
        "avg_time_to_throw", 
        "avg_completed_air_yards", 
        "efficiency", 
        "rush_yards_over_expected_per_att", 
        "avg_separation", 
        "avg_yac_above_expectation"
    ]
    
    df_weekly = df_weekly.with_columns([
        pl.col(c).cast(pl.Float64) for c in metric_cols
    ]).with_columns([
        pl.col("gsis_id").cast(pl.String)
    ])

    df_gold = df_gold.with_columns([
        pl.col("gsis_id").cast(pl.String),
        pl.col("master_score").cast(pl.Float64)
    ])

    # 2. Aggregate Season Stats
    print("Aggregating weekly stats to season level...")
    df_season = df_weekly.group_by("gsis_id").agg([
        pl.col("full_name").first(),
        pl.col("position").first(),
        pl.col("team").first(), # Most recent team or just first
        pl.count("week").alias("games_played"),
        *[pl.col(c).mean().alias(f"season_{c}") for c in metric_cols]
    ])

    # 3. Join with Master Rankings
    # Only care about players who are ranked
    df_analysis = df_gold.join(df_season, on="gsis_id", how="inner")
    
    print(f"Propsective Analysis Pool: {len(df_analysis)} players (Intersection of Ranked & Performance Data)")

    # 4. Correlation Analysis
    # We want to see correlation by position group
    positions = ["QB", "RB", "WR", "TE"]
    
    for pos in positions:
        print(f"\n--- Correlations for {pos} ---")
        df_pos = df_analysis.filter(pl.col("position") == pos)
        
        if len(df_pos) < 5:
            print("Not enough data.")
            continue
            
        # Select numeric columns for correlation
        target = "master_score"
        
        # We only really care about nextgen metrics vs master_score
        # and fantasy_points vs master_score
        
        relevant_metrics = [f"season_{c}" for c in metric_cols]
        relevant_metrics.append(target)
        
        # Filter out metrics that are all null (e.g. rushing stats for WRs might be scarce or null if not in bronze)
        # Polars correlation requires non-nulls. 
        # We'll fill nulls with 0 or drop them. For specific metrics like 'avg_time_to_throw', only QBs have it.
        
        # Let's perform pair-wise correlation with master_score
        correlations = []
        for metric in relevant_metrics:
            if metric == target: continue
            
            # Filter rows where both values are valid
            valid_rows = df_pos.filter(
                pl.col(metric).is_not_null() & pl.col(target).is_not_null()
            )
            
            if len(valid_rows) > 10:
                corr = valid_rows.select(
                    pl.corr(metric, target)
                ).item()
                correlations.append((metric, corr))
        
        # Sort by absolute correlation
        correlations.sort(key=lambda x: abs(x[1]) if x[1] is not None else 0, reverse=True)
        
        print(f"{'Metric':<40} | {'Correlation to Master Score':<10}")
        print("-" * 65)
        for name, corr in correlations:
            if corr is not None:
                print(f"{name:<40} | {corr:.4f}")

if __name__ == "__main__":
    analyze_nextgen()

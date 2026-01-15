import polars as pl
import sqlite3
import os
import sys
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score, mean_squared_error
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

# Force UTF-8 output
if sys.stdout.encoding != 'utf-8':
    import io
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Resolve absolute path to database (works from any cwd)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
db_path = os.path.join(project_root, "data", "nfl.db")

def read_sqlite_robust(query, conn):
    cursor = conn.cursor()
    cursor.execute(query)
    columns = [description[0] for description in cursor.description]
    data = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return pl.from_dicts(data, infer_schema_length=None)

def train_and_get_models():
    """
    Trains models for each position and returns them for exploration.
    Returns:
        models (dict): {pos: pipeline}
        data_artifacts (dict): {pos: {'X': X, 'y': y, 'names': names, 'features': valid_cols}}
        final_df (pl.DataFrame): Combined predictions with value deltas
    """
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return {}, {}, None

    conn = sqlite3.connect(db_path)
    try:
        print("Loading Silver (Stats) and Gold (Rankings) layers...")
        df_weekly = read_sqlite_robust("SELECT * FROM silver_weekly_performance", conn)
        df_gold = read_sqlite_robust("SELECT * FROM gold_master_rankings", conn)
    finally:
        conn.close()

    # 1. Feature Engineering (Season Aggregation)
    metric_cols = [
        "fantasy_points", 
        "avg_time_to_throw", 
        "avg_completed_air_yards", 
        "efficiency", 
        "rush_yards_over_expected_per_att", 
        "avg_separation", 
        "avg_yac_above_expectation"
    ]
    
    # Cast to float
    df_weekly = df_weekly.with_columns([
        pl.col(c).cast(pl.Float64) for c in metric_cols
    ]).with_columns(pl.col("gsis_id").cast(pl.String))
    
    df_gold = df_gold.with_columns([
        pl.col("gsis_id").cast(pl.String),
        pl.col("master_score").cast(pl.Float64)
    ])

    print("Aggregating season stats...")
    df_season = df_weekly.group_by("gsis_id").agg([
        pl.col("full_name").first(),
        pl.col("position").first(),
        *[pl.col(c).mean().alias(f"{c}") for c in metric_cols]
    ])

    # Join with target
    df_train = df_season.join(df_gold, on="gsis_id", how="inner")
    
    # We will train separate models for each position since metrics vary widely
    positions = ["QB", "RB", "WR", "TE"]
    
    models = {}
    data_artifacts = {}
    all_sleepers = []
    
    print("\n--- Model Training ---")
    
    for pos in positions:
        df_pos = df_train.filter(pl.col("position") == pos)
        if len(df_pos) < 10:
            print(f"Skipping {pos}: Not enough data.")
            continue
            
        # Select Features
        valid_cols = []
        for c in metric_cols:
            if df_pos.select(pl.col(c).is_not_null().mean()).item() > 0.5:
                valid_cols.append(c)
                
        if not valid_cols:
            print(f"Skipping {pos}: No valid metrics found.")
            continue
            
        X = df_pos.select(valid_cols).to_pandas()
        y = df_pos.select("master_score").to_pandas().values.ravel()
        names = df_pos.select("player_name").to_pandas().values.ravel()
        
        # Build Pipeline
        pipe = Pipeline([
            ('imputer', SimpleImputer(strategy='mean')),
            ('scaler', StandardScaler()),
            ('model', Ridge(alpha=1.0))
        ])
        
        pipe.fit(X, y)
        y_pred = pipe.predict(X)
        
        # Store artifacts
        models[pos] = pipe
        data_artifacts[pos] = {
            'X': X,
            'y': y,
            'names': names,
            'features': valid_cols
        }
        
        residuals = y_pred - y
        deltas = y_pred - y
        
        # Create results df
        results = pl.DataFrame({
            "player_name": names,
            "position": [pos]*len(names),
            "actual_score": y,
            "predicted_score": y_pred.flatten(),
            "value_delta": deltas.flatten()
        })
        
        all_sleepers.append(results)

    final_df = pl.concat(all_sleepers) if all_sleepers else None
    return models, data_artifacts, final_df

def print_report(models, data_artifacts, final_df):
    if final_df is None:
        print("No predictions generated.")
        return

    for pos, artifact in data_artifacts.items():
        y = artifact['y']
        X = artifact['X']
        pipe = models[pos]
        y_pred = pipe.predict(X)
        
        r2 = r2_score(y, y_pred)
        rmse = np.sqrt(mean_squared_error(y, y_pred))
        
        print(f"\nPosition: {pos} (n={len(y)})")
        print(f"Features: {artifact['features']}")
        print(f"R²: {r2:.3f} | RMSE: {rmse:.3f}")
        
        coefs = pipe.named_steps['model'].coef_
        sorted_idx = np.argsort(np.abs(coefs))[::-1]
        print("Top Drivers:")
        for idx in sorted_idx[:3]:
            print(f"  {artifact['features'][idx]}: {coefs[idx]:.2f}")

    print("\n=== TOP 5 SLEEPERS (Undervalued by Market) ===")
    print(final_df.sort("value_delta", descending=True).head(5))
    
    print("\n=== TOP 5 BUSTS (Overvalued by Market) ===")
    print(final_df.sort("value_delta", descending=False).head(5))
    
    final_df.write_csv("data/player_value_predictions.csv")
    print("\nPredictions saved to data/player_value_predictions.csv")

if __name__ == "__main__":
    models, artifacts, final_df = train_and_get_models()
    print_report(models, artifacts, final_df)

"""
Generate 2026 Projections
1. Train Model: 2024 Stats -> 2025 Rankings (Master Score)
2. Predict: 2025 Stats -> 2026 Rankings
"""

import polars as pl
import os
import sys
import numpy as np
from lightgbm import LGBMRegressor
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.db import DB_PATH, get_connection
from utils.features import load_all_data, build_master_feature_set

def train_and_predict():
    conn = get_connection()
    try:
        # 1. Load Data
        df_weekly, df_gold, df_opportunity, df_snaps, df_depth = load_all_data(conn)
        df_master, df_gold = build_master_feature_set(
            df_weekly, df_gold, df_opportunity, df_snaps, df_depth
        )
        
        print("\nPreparing Datasets...")
        
        # Training Data: Season 2024 Features -> 2025 Target (Master Score)
        # Note: df_gold contains CURRENT rankings. Assuming df_gold is relevant to the "target" season.
        # If df_gold is 2025 rankings, then:
        # X_train = 2024 stats
        # y_train = 2025 scores (joined by gsis_id)
        
        # We need to ensure we map the years correctly.
        # Let's assume df_gold represents the "result" of the most recent season (2025) or the "consensus" entering 2026.
        # Typically "Master Rankings" might be retrospective or current dynasty value.
        # Let's assume Master Score is the "Ground Truth Value" at the snapshot time (Jan 2026).
        
        # So:
        # Pattern: Previous Season Stats -> Current Value
        # Train: 2024 Stats -> Current Value (Wait, value changes. If df_gold is static snapshot, we can only train on recent)
        # Better approach for forecasting:
        # Train: 2024 Stats -> 2025 Points (or Value if we had historical value snapshots)
        
        # Since we only have ONE snapshot of rankings (current), we can effectively only do:
        # Train: 2025 Stats -> Current Value (to learn how stats map to value defined by user's ranking system)
        # Predict: 2026 Projected Stats -> 2026 Value?
        # NO, typically we use "Lagged" stats.
        
        # Let's try:
        # Train: 2025 Stats -> Current Master Score
        # (Learn how 2025 performance explains current 2026 Draft Value)
        # Predict: ... wait, to predict 2026 Value we need 2026 Stats? No.
        
        # We want to find "Undervalued" players.
        # So we predict what their value SHOULD be based on 2025 stats, and compare to actual.
        # OR we want to predict Future Points.
        
        # Let's stick to the user's request: "List of players ... I should consider".
        # This implies finding Value (Predictions > ADP/Rank).
        
        # So:
        # 1. Train Model: 2025 Stats -> Current Master Score (Learns existing market logic)
        #    BUT this just reproduces the market.
        
        # 2. Train Model: 2024 Stats -> 2025 Stats (Predict next year's performance)
        #    Then Apply: 2025 Stats -> Predict 2026 Stats
        #    Then Rank based on Projected 2026 Stats.
        
        # Let's do Step 2 (Performance Prediction).
        # We will predict "fantasy_points" for next season.
        
        print("Training Performance Prediction Model (Year N -> Year N+1)...")
        
        # Create Lagged Dataset
        # Self-join master on gsis_id and season = season + 1
        
        # Select target columns: avg_fantasy_points (PPG)
        # We will predict PPG for next season.
        
        df_target_stats = df_master.select(["gsis_id", "season", "avg_fantasy_points"]).rename({
            "avg_fantasy_points": "target_next_year_ppg",
            "season": "target_season"
        })
        
        # We want to join where target_season = feature_season + 1
        # so feature_season = target_season - 1
        df_target_stats = df_target_stats.with_columns(
            (pl.col("target_season") - 1).alias("match_season")
        )
        
        df_train_set = df_master.join(
            df_target_stats,
            left_on=["gsis_id", "season"],
            right_on=["gsis_id", "match_season"],
            how="inner"
        )
        
        print(f"Training Samples (Historical Year Pairs): {len(df_train_set)}")
        
        # Train Model
        positions = ["QB", "RB", "WR", "TE"]
        models = {}
        
        # Features 
        # Note: 'fantasy_points' was not in df_master columns (it was renamed to avg_fantasy_points).
        # We should use 'avg_fantasy_points' as a feature for consistency (previous year performance).
        feature_sets = {
            "QB": ["avg_avg_time_to_throw", "avg_avg_completed_air_yards", "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games", "games_played", "avg_fp_vs_expected", "avg_depth_position", "weeks_as_starter", "avg_fantasy_points"],
            "RB": ["avg_efficiency", "avg_rush_yards_over_expected_per_att", "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games", "rush_share", "target_share", "games_played", "avg_fp_vs_expected", "avg_depth_position", "weeks_as_starter", "avg_fantasy_points"],
            "WR": ["avg_avg_separation", "avg_avg_yac_above_expectation", "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games", "target_share", "air_yards_share", "games_played", "avg_fp_vs_expected", "avg_depth_position", "weeks_as_starter", "avg_fantasy_points"],
            "TE": ["avg_avg_separation", "avg_avg_yac_above_expectation", "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games", "target_share", "games_played", "avg_fp_vs_expected", "avg_depth_position", "weeks_as_starter", "avg_fantasy_points"]
        }
        
        for pos in positions:
            print(f"Training {pos} model...")
            df_pos = df_train_set.filter(pl.col("position") == pos)
            if len(df_pos) < 10:
                print(f"  Skipping {pos} (not enough data)")
                continue
                
            features = feature_sets[pos]
            valid_feats = [f for f in features if f in df_pos.columns]
            
            X = df_pos.select(valid_feats).to_pandas()
            y = df_pos.select("target_next_year_ppg").to_pandas().values.ravel()
            
            pipe = Pipeline([
                ('imputer', SimpleImputer(strategy='median')),
                ('scaler', StandardScaler()),
                ('model', LGBMRegressor(n_estimators=100, random_state=42, verbosity=-1))
            ])
            pipe.fit(X, y)
            models[pos] = (pipe, valid_feats)
            
        print("\nPredicting 2026 Performance...")
        
        # Predict using 2025 Data
        df_2025 = df_master.filter(pl.col("season") == 2025)
        print(f"2025 Player Count: {len(df_2025)}")
        
        predictions = []
        
        for pos in positions:
            if pos not in models: continue
            
            df_curr = df_2025.filter(pl.col("position") == pos)
            model, feats = models[pos]
            
            ids = df_curr["gsis_id"].to_list()
            names = df_curr["player_name"].to_list()
            
            X_curr = df_curr.select(feats).to_pandas()
            
            preds = model.predict(X_curr)
            
            for i in range(len(ids)):
                predictions.append({
                    "gsis_id": ids[i],
                    "player_name": names[i],
                    "position": pos,
                    "proj_ppg_2026": preds[i],
                    # Simple projection of Total Points assuming 17 games
                    "proj_total_points_2026": preds[i] * 17
                })
                
        df_preds = pl.DataFrame(predictions).sort("proj_total_points_2026", descending=True)
        
        # Save to SQLite
        print("Saving to database (gold_projections_2026)...")
        df_preds.write_database(
            table_name="gold_projections_2026",
            connection=f"sqlite:///{DB_PATH}",
            if_table_exists="replace",
            engine="adbc"
        )
        print("Saved.")
        
        # Display Top 20 Overall
        print("\nTop 20 Projected 2026 Players (Veterans):")
        print(df_preds.head(20))
        
    finally:
        conn.close()

if __name__ == "__main__":
    train_and_predict()

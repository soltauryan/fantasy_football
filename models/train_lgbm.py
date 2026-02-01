"""
Fantasy Football Value Model - LightGBM Version
Uses LightGBM for potentially better performance and speed.
"""

import polars as pl
import sqlite3
import os
import sys
import numpy as np
from sklearn.linear_model import Ridge
from lightgbm import LGBMRegressor
from sklearn.metrics import r2_score, mean_squared_error
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import cross_val_score, train_test_split

# Force UTF-8 output
if sys.stdout.encoding != 'utf-8':
    import io
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add project root to path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.db import DB_PATH
from utils.features import load_all_data, build_master_feature_set


def train_models_with_cv(df_master):
    """
    Train models with proper cross-validation using LightGBM.
    """
    positions = ["QB", "RB", "WR", "TE"]

    # Define feature columns by position
    feature_sets = {
        "QB": [
            "avg_avg_time_to_throw", "avg_avg_completed_air_yards",
            "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games",
            "games_played", "avg_fp_vs_expected",
            "avg_depth_position", "weeks_as_starter"
        ],
        "RB": [
            "avg_efficiency", "avg_rush_yards_over_expected_per_att",
            "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games",
            "rush_share", "target_share", "games_played", "avg_fp_vs_expected",
            "avg_depth_position", "weeks_as_starter"
        ],
        "WR": [
            "avg_avg_separation", "avg_avg_yac_above_expectation",
            "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games",
            "target_share", "air_yards_share", "games_played", "avg_fp_vs_expected",
            "avg_depth_position", "weeks_as_starter"
        ],
        "TE": [
            "avg_avg_separation", "avg_avg_yac_above_expectation",
            "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games",
            "target_share", "games_played", "avg_fp_vs_expected",
            "avg_depth_position", "weeks_as_starter"
        ]
    }

    models = {}
    results = []

    print("\n" + "="*60)
    print("LIGHTGBM MODEL TRAINING WITH CROSS-VALIDATION")
    print("="*60)

    for pos in positions:
        df_pos = df_master.filter(pl.col("position") == pos)

        if len(df_pos) < 20:
            print(f"\nSkipping {pos}: Not enough data ({len(df_pos)} samples)")
            continue

        available_features = [f for f in feature_sets[pos] if f in df_pos.columns]
        df_pos_clean = df_pos.drop_nulls(subset=["master_score"])

        if len(df_pos_clean) < 20:
            print(f"\nSkipping {pos}: Not enough clean data ({len(df_pos_clean)} samples)")
            continue

        X = df_pos_clean.select(available_features).to_pandas()
        y = df_pos_clean.select("master_score").to_pandas().values.ravel()
        names = df_pos_clean.select("player_name").to_pandas().values.ravel()

        # Build pipeline with LGBM
        # LightGBM handles NaNs effectively, but SimpleImputer is safe
        pipe = Pipeline([
            ('imputer', SimpleImputer(strategy='median')),
            ('scaler', StandardScaler()),
            ('model', LGBMRegressor(
                n_estimators=200,
                learning_rate=0.05,
                num_leaves=31,
                random_state=42,
                verbosity=-1
            ))
        ])

        # Cross-validation scores
        cv_scores = cross_val_score(pipe, X, y, cv=5, scoring='r2')
        cv_rmse = cross_val_score(pipe, X, y, cv=5, scoring='neg_root_mean_squared_error')

        # Fit on all data for predictions
        pipe.fit(X, y)
        y_pred = pipe.predict(X)

        # In-sample metrics
        in_sample_r2 = r2_score(y, y_pred)
        in_sample_rmse = np.sqrt(mean_squared_error(y, y_pred))

        models[pos] = {
            'pipeline': pipe,
            'features': available_features,
            'cv_r2_mean': cv_scores.mean(),
            'cv_r2_std': cv_scores.std(),
            'cv_rmse_mean': -cv_rmse.mean(),
            'in_sample_r2': in_sample_r2
        }

        # Calculate value deltas
        value_delta = y_pred - y

        for i in range(len(names)):
            results.append({
                "player_name": names[i],
                "position": pos,
                "actual_score": y[i],
                "predicted_score": y_pred[i],
                "value_delta": value_delta[i]
            })

        print(f"\n{pos} (n={len(y)})")
        print(f"  Cross-Val R²: {cv_scores.mean():.3f} (+/- {cv_scores.std()*2:.3f})")
        print(f"  Cross-Val RMSE: {-cv_rmse.mean():.2f}")
        print(f"  In-Sample R²: {in_sample_r2:.3f}")

        # Feature importance
        importances = pipe.named_steps['model'].feature_importances_
        sorted_idx = np.argsort(importances)[::-1]
        print(f"  Top Features:")
        for idx in sorted_idx[:3]:
            # Use gain or split? Default is split.
            print(f"    {available_features[idx]}: {importances[idx]:.1f}")

    return models, pl.DataFrame(results)


def print_sleepers_and_busts(results_df):
    """Print top sleepers and busts."""
    print("\n" + "="*60)
    print("TOP 10 SLEEPERS (LGBM)")
    print("="*60)
    sleepers = results_df.sort("value_delta", descending=True).head(10)
    for row in sleepers.iter_rows(named=True):
        print(f"  {row['player_name']:25} ({row['position']}) Delta: +{row['value_delta']:.1f}")

    print("\n" + "="*60)
    print("TOP 10 BUSTS (LGBM)")
    print("="*60)
    busts = results_df.sort("value_delta", descending=False).head(10)
    for row in busts.iter_rows(named=True):
        print(f"  {row['player_name']:25} ({row['position']}) Delta: {row['value_delta']:.1f}")


def main():
    print("="*60)
    print("FANTASY FOOTBALL VALUE MODEL - LightGBM")
    print("="*60)

    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        df_weekly, df_gold, df_opportunity, df_snaps, df_depth = load_all_data(conn)
        df_master, df_gold = build_master_feature_set(
            df_weekly, df_gold, df_opportunity, df_snaps, df_depth
        )

        models, results = train_models_with_cv(df_master)
        print_sleepers_and_busts(results)

        # Save results to SQLite
        print(f"\nSaving predictions to database (gold_value_predictions_lgbm)...")
        results.write_database(
            table_name="gold_value_predictions_lgbm",
            connection=f"sqlite:///{DB_PATH}",
            if_table_exists="replace",
            engine="adbc"
        )
        print("Saved.")

    finally:
        conn.close()

if __name__ == "__main__":
    main()

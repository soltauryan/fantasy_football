"""
Fantasy Football Value Model v2
Improvements over v1:
- Proper cross-validation
- Opportunity metrics (target share, snap %)
- Depth chart position
- Performance vs expectation features
- Consistency and trend features
- Predictive model (train on prior season)
- XGBoost for non-linear relationships
"""

import polars as pl
import sqlite3
import os
import sys
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.ensemble import GradientBoostingRegressor
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


def train_models_with_cv(df_master, use_xgboost=True):
    """
    Train models with proper cross-validation.
    """
    positions = ["QB", "RB", "WR", "TE"]

    # Define feature columns by position
    # Opportunity features are key predictors of future production
    feature_sets = {
        "QB": [
            # Efficiency metrics
            "avg_avg_time_to_throw", "avg_avg_completed_air_yards",
            # Consistency
            "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games",
            # Opportunity
            "games_played", "avg_fp_vs_expected",
            # Depth chart
            "avg_depth_position", "weeks_as_starter"
        ],
        "RB": [
            # Efficiency metrics
            "avg_efficiency", "avg_rush_yards_over_expected_per_att",
            # Consistency
            "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games",
            # Opportunity (KEY for RBs)
            "rush_share", "target_share", "games_played", "avg_fp_vs_expected",
            # Depth chart
            "avg_depth_position", "weeks_as_starter"
        ],
        "WR": [
            # Efficiency metrics
            "avg_avg_separation", "avg_avg_yac_above_expectation",
            # Consistency
            "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games",
            # Opportunity (KEY for WRs)
            "target_share", "air_yards_share", "games_played", "avg_fp_vs_expected",
            # Depth chart
            "avg_depth_position", "weeks_as_starter"
        ],
        "TE": [
            # Efficiency metrics
            "avg_avg_separation", "avg_avg_yac_above_expectation",
            # Consistency
            "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games",
            # Opportunity
            "target_share", "games_played", "avg_fp_vs_expected",
            # Depth chart
            "avg_depth_position", "weeks_as_starter"
        ]
    }

    models = {}
    results = []

    print("\n" + "="*60)
    print("MODEL TRAINING WITH CROSS-VALIDATION")
    print("="*60)

    for pos in positions:
        df_pos = df_master.filter(pl.col("position") == pos)

        if len(df_pos) < 20:
            print(f"\nSkipping {pos}: Not enough data ({len(df_pos)} samples)")
            continue

        # Get available features
        available_features = [f for f in feature_sets[pos] if f in df_pos.columns]

        # Filter for rows with at least some valid features
        df_pos_clean = df_pos.drop_nulls(subset=["master_score"])

        if len(df_pos_clean) < 20:
            print(f"\nSkipping {pos}: Not enough clean data ({len(df_pos_clean)} samples)")
            continue

        X = df_pos_clean.select(available_features).to_pandas()
        y = df_pos_clean.select("master_score").to_pandas().values.ravel()
        names = df_pos_clean.select("player_name").to_pandas().values.ravel()

        # Build pipeline
        if use_xgboost:
            pipe = Pipeline([
                ('imputer', SimpleImputer(strategy='median')),
                ('scaler', StandardScaler()),
                ('model', GradientBoostingRegressor(
                    n_estimators=100,
                    max_depth=3,
                    learning_rate=0.1,
                    random_state=42
                ))
            ])
        else:
            pipe = Pipeline([
                ('imputer', SimpleImputer(strategy='median')),
                ('scaler', StandardScaler()),
                ('model', Ridge(alpha=1.0))
            ])

        # Cross-validation scores
        cv_scores = cross_val_score(pipe, X, y, cv=5, scoring='r2')
        cv_rmse = cross_val_score(pipe, X, y, cv=5, scoring='neg_root_mean_squared_error')

        # Fit on all data for predictions
        pipe.fit(X, y)
        y_pred = pipe.predict(X)

        # In-sample metrics (for comparison)
        in_sample_r2 = r2_score(y, y_pred)
        in_sample_rmse = np.sqrt(mean_squared_error(y, y_pred))

        models[pos] = {
            'pipeline': pipe,
            'features': available_features,
            'cv_r2_mean': cv_scores.mean(),
            'cv_r2_std': cv_scores.std(),
            'cv_rmse_mean': -cv_rmse.mean(),
            'in_sample_r2': in_sample_r2,
            'in_sample_rmse': in_sample_rmse,
            'n_samples': len(y)
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

        # Print results
        print(f"\n{pos} (n={len(y)})")
        print(f"  Features: {available_features}")
        print(f"  Cross-Val R²: {cv_scores.mean():.3f} (+/- {cv_scores.std()*2:.3f})")
        print(f"  Cross-Val RMSE: {-cv_rmse.mean():.2f}")
        print(f"  In-Sample R²: {in_sample_r2:.3f} (for reference)")

        # Feature importance for GradientBoosting
        if use_xgboost:
            importances = pipe.named_steps['model'].feature_importances_
            sorted_idx = np.argsort(importances)[::-1]
            print(f"  Top Features:")
            for idx in sorted_idx[:3]:
                print(f"    {available_features[idx]}: {importances[idx]:.3f}")

    return models, pl.DataFrame(results)


def train_predictive_model(df_master, df_gold):
    """
    Train a TRUE predictive model:
    - Train on 2023/2024 season features
    - Predict 2025 rankings

    This tests actual predictive power, not just fitting current data.
    """
    print("\n" + "="*60)
    print("PREDICTIVE MODEL: Train on 2024 → Predict 2025 Rankings")
    print("="*60)

    positions = ["QB", "RB", "WR", "TE"]

    feature_sets = {
        "QB": [
            "avg_avg_time_to_throw", "avg_avg_completed_air_yards",
            "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games",
            "games_played", "avg_fp_vs_expected"
        ],
        "RB": [
            "avg_efficiency", "avg_rush_yards_over_expected_per_att",
            "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games",
            "rush_share", "target_share", "games_played", "avg_fp_vs_expected"
        ],
        "WR": [
            "avg_avg_separation", "avg_avg_yac_above_expectation",
            "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games",
            "target_share", "air_yards_share", "games_played", "avg_fp_vs_expected"
        ],
        "TE": [
            "avg_avg_separation", "avg_avg_yac_above_expectation",
            "fp_std", "fp_cv", "fp_trend", "boom_games", "bust_games",
            "target_share", "games_played", "avg_fp_vs_expected"
        ]
    }

    # Get 2024 season data for training features
    df_train_features = df_master.filter(pl.col("season") == 2024)

    # Get current rankings (2025) as target - these are what we want to predict
    df_target = df_gold.select(["gsis_id", "player_name", "position", "master_score"])

    # Join to get training set: 2024 features -> 2025 rankings
    df_train = df_train_features.join(
        df_target.select(["gsis_id", "master_score"]).rename({"master_score": "target_score"}),
        on="gsis_id",
        how="inner"
    )

    print(f"\nTraining set: {len(df_train)} players with 2024 stats and 2025 rankings")

    models = {}
    results = []

    for pos in positions:
        df_pos = df_train.filter(pl.col("position") == pos)

        if len(df_pos) < 15:
            print(f"\nSkipping {pos}: Not enough data ({len(df_pos)} samples)")
            continue

        available_features = [f for f in feature_sets[pos] if f in df_pos.columns]
        df_pos_clean = df_pos.drop_nulls(subset=["target_score"])

        if len(df_pos_clean) < 15:
            print(f"\nSkipping {pos}: Not enough clean data")
            continue

        X = df_pos_clean.select(available_features).to_pandas()
        y = df_pos_clean.select("target_score").to_pandas().values.ravel()
        names = df_pos_clean.select("player_name").to_pandas().values.ravel()
        current_rank = df_pos_clean.select("master_score").to_pandas().values.ravel()

        # Use train/test split for validation
        if len(X) >= 30:
            X_train, X_test, y_train, y_test, names_train, names_test = train_test_split(
                X, y, names, test_size=0.25, random_state=42
            )
        else:
            # Not enough data for split, use all
            X_train, X_test = X, X
            y_train, y_test = y, y
            names_train, names_test = names, names

        # Build and train model
        pipe = Pipeline([
            ('imputer', SimpleImputer(strategy='median')),
            ('scaler', StandardScaler()),
            ('model', GradientBoostingRegressor(
                n_estimators=50,
                max_depth=2,
                learning_rate=0.1,
                random_state=42
            ))
        ])

        pipe.fit(X_train, y_train)

        # Evaluate on test set
        y_pred_test = pipe.predict(X_test)
        test_r2 = r2_score(y_test, y_pred_test)
        test_rmse = np.sqrt(mean_squared_error(y_test, y_pred_test))

        # Predict for all players
        y_pred_all = pipe.predict(X)

        models[pos] = {
            'pipeline': pipe,
            'features': available_features,
            'test_r2': test_r2,
            'test_rmse': test_rmse
        }

        # Calculate value delta (predicted 2025 rank - actual 2025 rank)
        # Positive = model thinks they should be ranked higher (sleeper)
        value_delta = y_pred_all - y

        for i in range(len(names)):
            results.append({
                "player_name": names[i],
                "position": pos,
                "actual_2025_score": y[i],
                "predicted_2025_score": y_pred_all[i],
                "value_delta": value_delta[i]
            })

        print(f"\n{pos} (n={len(df_pos_clean)}, test={len(X_test)})")
        print(f"  Features: {available_features}")
        print(f"  Test R²: {test_r2:.3f}")
        print(f"  Test RMSE: {test_rmse:.2f}")

        # Feature importance
        importances = pipe.named_steps['model'].feature_importances_
        sorted_idx = np.argsort(importances)[::-1]
        print(f"  Top Predictive Features:")
        for idx in sorted_idx[:3]:
            print(f"    {available_features[idx]}: {importances[idx]:.3f}")

    return models, pl.DataFrame(results)


def print_sleepers_and_busts(results_df, title_suffix=""):
    """Print top sleepers and busts."""
    print("\n" + "="*60)
    print(f"TOP 10 SLEEPERS (Undervalued by Market){title_suffix}")
    print("="*60)
    sleepers = results_df.sort("value_delta", descending=True).head(10)
    for row in sleepers.iter_rows(named=True):
        print(f"  {row['player_name']:25} ({row['position']}) Delta: +{row['value_delta']:.1f}")

    print("\n" + "="*60)
    print(f"TOP 10 BUSTS (Overvalued by Market){title_suffix}")
    print("="*60)
    busts = results_df.sort("value_delta", descending=False).head(10)
    for row in busts.iter_rows(named=True):
        print(f"  {row['player_name']:25} ({row['position']}) Delta: {row['value_delta']:.1f}")


def main():
    """Main training pipeline."""
    print("="*60)
    print("FANTASY FOOTBALL VALUE MODEL v2")
    print("="*60)

    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        # Load all data
        df_weekly, df_gold, df_opportunity, df_snaps, df_depth = load_all_data(conn)

        # Build master feature set
        df_master, df_gold = build_master_feature_set(
            df_weekly, df_gold, df_opportunity, df_snaps, df_depth
        )

        # Train models with cross-validation
        print("\n--- Training with XGBoost ---")
        models_xgb, results_xgb = train_models_with_cv(df_master, use_xgboost=True)

        # Print sleepers/busts
        print_sleepers_and_busts(results_xgb)

        # Save results
        # Use abs path for saving relative to project root handled by this script's location logic if needed, 
        # but utils already sets DB_PATH. Let's rely on standard current working directory usage or relative to script.
        # Original script used project_root derived from script path.
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Save results to SQLite
        print(f"\nSaving predictions to database (gold_value_predictions_xgb)...")
        results_xgb.write_database(
            table_name="gold_value_predictions_xgb",
            connection=f"sqlite:///{DB_PATH}",
            if_table_exists="replace",
            engine="adbc"
        )
        print("Saved.")

        # Also compare with Ridge for reference
        print("\n" + "="*60)
        print("COMPARISON: Ridge Regression (for reference)")
        print("="*60)
        models_ridge, results_ridge = train_models_with_cv(df_master, use_xgboost=False)

    finally:
        conn.close()

    print("\n" + "="*60)
    print("MODEL TRAINING COMPLETE")
    print("="*60)


if __name__ == "__main__":
    main()

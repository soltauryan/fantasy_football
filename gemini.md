# Gemini Notes

## Initial- [x] Refactor utils
    - [x] Create `utils` directory
    - [x] Identify and move common data loading/saving functions
    - [x] Identify and move common transformation functions
    - [x] Update `etl` scripts to use `utils`
- [x] Improve Model Predictions (XGBoost/LGBM)
    - [x] Analyze current data preparation
    - [x] Create `models/train_lgbm.py` (or similar)
    - [x] Implement training loop with LightGBM/XGBoost
    - [x] Compare metrics
- [x] Scheduling Conflicts Analysis
    - [x] Locate schedule data source (Infer from silver_weekly)
    - [x] Implement `analysis/schedule_conflicts.py`
    - [x] Output report on difficult weeks/byes

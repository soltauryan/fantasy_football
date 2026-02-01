import polars as pl
from .db import read_sqlite_robust

def load_all_data(conn):
    """Load all required data sources."""
    print("Loading data sources...")

    # Core performance data
    df_weekly = read_sqlite_robust("SELECT * FROM silver_weekly_performance", conn)
    df_gold = read_sqlite_robust("SELECT * FROM gold_master_rankings", conn)

    # Opportunity data
    df_opportunity = read_sqlite_robust("SELECT * FROM bronze_ff_opportunity", conn)

    # Snap counts
    df_snaps = read_sqlite_robust("SELECT * FROM bronze_snap_counts", conn)

    # Depth charts
    df_depth = read_sqlite_robust("SELECT * FROM bronze_depth_charts", conn)

    print(f"  Weekly performance: {len(df_weekly)} rows")
    print(f"  Rankings: {len(df_gold)} rows")
    print(f"  Opportunity: {len(df_opportunity)} rows")
    print(f"  Snap counts: {len(df_snaps)} rows")
    print(f"  Depth charts: {len(df_depth)} rows")

    return df_weekly, df_gold, df_opportunity, df_snaps, df_depth


def build_opportunity_features(df_opportunity):
    """
    Build opportunity-based features from bronze_ff_opportunity.
    These measure volume/usage independent of efficiency.
    """
    # Cast columns to proper types
    numeric_cols = [
        'rec_attempt', 'rush_attempt', 'targets', 'receptions',
        'rec_air_yards', 'total_fantasy_points', 'total_fantasy_points_exp',
        'rec_attempt_team', 'rush_attempt_team', 'rec_air_yards_team',
        'total_fantasy_points_diff', 'rec_fantasy_points_diff', 'rush_fantasy_points_diff'
    ]

    for col in numeric_cols:
        if col in df_opportunity.columns:
            df_opportunity = df_opportunity.with_columns(
                pl.col(col).cast(pl.Float64, strict=False)
            )

    # Aggregate to season level
    df_opp_season = df_opportunity.group_by(["player_id", "season"]).agg([
        pl.col("full_name").first(),
        pl.col("position").first(),

        # Volume metrics
        pl.col("rec_attempt").sum().alias("total_targets"),
        pl.col("rush_attempt").sum().alias("total_rush_attempts"),
        pl.col("receptions").sum().alias("total_receptions"),
        pl.col("rec_air_yards").sum().alias("total_air_yards"),

        # Team share metrics (for calculating share)
        pl.col("rec_attempt_team").sum().alias("team_targets"),
        pl.col("rush_attempt_team").sum().alias("team_rush_attempts"),
        pl.col("rec_air_yards_team").sum().alias("team_air_yards"),

        # Performance vs expectation
        pl.col("total_fantasy_points_diff").mean().alias("avg_fp_vs_expected"),
        pl.col("rec_fantasy_points_diff").mean().alias("avg_rec_fp_vs_expected"),
        pl.col("rush_fantasy_points_diff").mean().alias("avg_rush_fp_vs_expected"),

        # Game count
        pl.len().alias("games_played")
    ])

    # Calculate share metrics
    df_opp_season = df_opp_season.with_columns([
        (pl.col("total_targets") / pl.col("team_targets").replace(0, None)).alias("target_share"),
        (pl.col("total_rush_attempts") / pl.col("team_rush_attempts").replace(0, None)).alias("rush_share"),
        (pl.col("total_air_yards") / pl.col("team_air_yards").replace(0, None)).alias("air_yards_share"),
    ])

    return df_opp_season


def build_snap_features(df_snaps):
    """
    Build snap count features from bronze_snap_counts.
    Snap share is highly predictive of opportunity.
    """
    # Cast to proper types
    df_snaps = df_snaps.with_columns([
        pl.col("offense_pct").cast(pl.Float64, strict=False),
        pl.col("offense_snaps").cast(pl.Float64, strict=False),
        pl.col("season").cast(pl.Int64, strict=False),
    ])

    # Aggregate to season level
    df_snap_season = df_snaps.group_by(["pfr_player_id", "season"]).agg([
        pl.col("player").first(),
        pl.col("position").first(),
        pl.col("team").first(),

        # Snap metrics
        pl.col("offense_pct").mean().alias("avg_snap_pct"),
        pl.col("offense_snaps").sum().alias("total_snaps"),
        pl.col("offense_snaps").mean().alias("avg_snaps_per_game"),

        # Games with significant snaps
        (pl.col("offense_pct") > 50).sum().alias("games_over_50pct_snaps"),
    ])

    return df_snap_season


def build_depth_chart_features(df_depth):
    """
    Build depth chart features.
    Starter vs backup status is crucial for projecting opportunity.
    """
    # Get latest depth chart position per player per season
    df_depth = df_depth.with_columns([
        pl.col("pos_rank").cast(pl.Int64, strict=False),
        pl.col("season").cast(pl.Int64, strict=False),
    ])

    # Get end-of-season depth position (max week)
    df_depth_season = df_depth.group_by(["gsis_id", "season"]).agg([
        pl.col("full_name").first(),
        pl.col("position").first(),
        pl.col("team").first(),

        # Average depth position (lower = starter)
        pl.col("pos_rank").mean().alias("avg_depth_position"),

        # Best depth position achieved
        pl.col("pos_rank").min().alias("best_depth_position"),

        # Weeks as starter (pos_rank == 1)
        (pl.col("pos_rank") == 1).sum().alias("weeks_as_starter"),
    ])

    return df_depth_season


def build_consistency_features(df_weekly):
    """
    Build consistency and trend features from weekly data.
    """
    df_weekly = df_weekly.with_columns([
        pl.col("fantasy_points").cast(pl.Float64, strict=False),
        pl.col("season").cast(pl.Int64, strict=False),
        pl.col("week").cast(pl.Int64, strict=False),
    ])

    # Overall season consistency
    df_consistency = df_weekly.group_by(["gsis_id", "season"]).agg([
        pl.col("full_name").first(),
        pl.col("position").first(),

        # Consistency metrics
        pl.col("fantasy_points").std().alias("fp_std"),
        pl.col("fantasy_points").mean().alias("fp_mean"),
        pl.col("fantasy_points").max().alias("fp_max"),
        pl.col("fantasy_points").min().alias("fp_min"),

        # Boom/bust counts
        (pl.col("fantasy_points") > 20).sum().alias("boom_games"),  # 20+ point games
        (pl.col("fantasy_points") < 5).sum().alias("bust_games"),   # Under 5 point games

        # Games played
        pl.len().alias("games_played_weekly"),
    ])

    # Calculate coefficient of variation (lower = more consistent)
    df_consistency = df_consistency.with_columns([
        (pl.col("fp_std") / pl.col("fp_mean").replace(0, None)).alias("fp_cv"),
        (pl.col("fp_max") - pl.col("fp_min")).alias("fp_range"),
    ])

    # Build trend features (first half vs second half of season)
    df_first_half = df_weekly.filter(pl.col("week") <= 9).group_by(["gsis_id", "season"]).agg([
        pl.col("fantasy_points").mean().alias("fp_first_half")
    ])

    df_second_half = df_weekly.filter(pl.col("week") > 9).group_by(["gsis_id", "season"]).agg([
        pl.col("fantasy_points").mean().alias("fp_second_half")
    ])

    df_consistency = df_consistency.join(df_first_half, on=["gsis_id", "season"], how="left")
    df_consistency = df_consistency.join(df_second_half, on=["gsis_id", "season"], how="left")

    # Trend: positive = improving, negative = declining
    df_consistency = df_consistency.with_columns([
        (pl.col("fp_second_half") - pl.col("fp_first_half")).alias("fp_trend")
    ])

    return df_consistency


def build_master_feature_set(df_weekly, df_gold, df_opportunity, df_snaps, df_depth):
    """
    Combine all feature sources into a master training dataset.
    """
    print("\nBuilding feature sets...")

    # Build individual feature sets
    df_opp_features = build_opportunity_features(df_opportunity)
    # Rename player_id to gsis_id for joining
    df_opp_features = df_opp_features.rename({"player_id": "gsis_id"})
    print(f"  Opportunity features: {len(df_opp_features)} players")

    df_snap_features = build_snap_features(df_snaps)
    print(f"  Snap features: {len(df_snap_features)} players")

    # Filter depth charts to offensive positions only
    df_depth_offense = df_depth.filter(
        pl.col("position").is_in(["QB", "RB", "WR", "TE", "FB"])
    )
    df_depth_features = build_depth_chart_features(df_depth_offense)
    print(f"  Depth chart features: {len(df_depth_features)} players")

    df_consistency_features = build_consistency_features(df_weekly)
    print(f"  Consistency features: {len(df_consistency_features)} players")

    # Build base from weekly performance (aggregated)
    metric_cols = [
        "fantasy_points", "avg_time_to_throw", "avg_completed_air_yards",
        "efficiency", "rush_yards_over_expected_per_att",
        "avg_separation", "avg_yac_above_expectation"
    ]

    df_weekly = df_weekly.with_columns([
        pl.col(c).cast(pl.Float64, strict=False) for c in metric_cols if c in df_weekly.columns
    ]).with_columns([
        pl.col("gsis_id").cast(pl.String),
        pl.col("season").cast(pl.Int64, strict=False),
    ])

    df_base = df_weekly.group_by(["gsis_id", "season"]).agg([
        pl.col("full_name").first().alias("player_name"),
        pl.col("position").first(),
        pl.col("team").first(),
        *[pl.col(c).mean().alias(f"avg_{c}") for c in metric_cols if c in df_weekly.columns]
    ])

    # Prepare gold rankings (target variable)
    df_gold = df_gold.with_columns([
        pl.col("gsis_id").cast(pl.String),
        pl.col("master_score").cast(pl.Float64)
    ]).select(["gsis_id", "player_name", "position", "master_score"])

    # Join all features
    # Start with base
    df_master = df_base

    # Join opportunity features (target share, rush share, etc.)
    df_opp_features = df_opp_features.with_columns([
        pl.col("gsis_id").cast(pl.String),
        pl.col("season").cast(pl.Int64, strict=False),
    ])
    df_master = df_master.join(
        df_opp_features.select([
            "gsis_id", "season", "target_share", "rush_share", "air_yards_share",
            "avg_fp_vs_expected", "games_played"
        ]),
        on=["gsis_id", "season"],
        how="left"
    )

    # Join consistency features
    df_master = df_master.join(
        df_consistency_features.select([
            "gsis_id", "season", "fp_std", "fp_cv", "fp_range",
            "boom_games", "bust_games", "fp_trend"
        ]),
        on=["gsis_id", "season"],
        how="left"
    )

    # Join depth features
    df_depth_features = df_depth_features.with_columns([
        pl.col("gsis_id").cast(pl.String),
        pl.col("season").cast(pl.Int64, strict=False),
    ])
    df_master = df_master.join(
        df_depth_features.select([
            "gsis_id", "season", "avg_depth_position", "best_depth_position", "weeks_as_starter"
        ]),
        on=["gsis_id", "season"],
        how="left"
    )

    # Join with target (rankings)
    df_master = df_master.join(
        df_gold.select(["gsis_id", "master_score"]),
        on="gsis_id",
        how="inner"
    )

    print(f"\nMaster dataset: {len(df_master)} player-seasons")

    return df_master, df_gold

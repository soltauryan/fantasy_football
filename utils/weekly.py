"""
Weekly analysis utilities for fantasy football.

Includes:
- Injury impact analysis
- Depth chart changes
- Snap count trends
- Target share analysis
- Matchup analysis
"""

import polars as pl
from typing import Optional
from utils.db import get_connection, read_sqlite_robust


def load_depth_charts(season: int = 2025, week: Optional[int] = None) -> pl.DataFrame:
    """Load depth chart data for analysis."""
    conn = get_connection()

    query = f"""
        SELECT
            season, week, team, gsis_id, full_name, position,
            depth_position, pos_rank, formation
        FROM bronze_depth_charts
        WHERE season = {season}
        AND position IN ('QB', 'RB', 'WR', 'TE')
    """
    if week:
        query += f" AND week = {week}"

    df = read_sqlite_robust(query, conn)
    conn.close()
    return df


def load_injuries(season: int = 2025, week: Optional[int] = None) -> pl.DataFrame:
    """Load injury report data."""
    conn = get_connection()

    query = f"""
        SELECT
            season, week, team, gsis_id, full_name, position,
            report_primary_injury, report_secondary_injury,
            report_status, practice_primary_injury,
            practice_status
        FROM bronze_injuries
        WHERE season = {season}
    """
    if week:
        query += f" AND week = {week}"

    df = read_sqlite_robust(query, conn)
    conn.close()
    return df


def load_snap_counts(season: int = 2025) -> pl.DataFrame:
    """Load snap count data."""
    conn = get_connection()

    df = read_sqlite_robust(f"""
        SELECT
            season, week, player as full_name, position, team,
            offense_snaps, offense_pct
        FROM bronze_snap_counts
        WHERE season = {season}
        AND position IN ('QB', 'RB', 'WR', 'TE')
    """, conn)
    conn.close()
    return df


def load_weekly_performance(season: int = 2025) -> pl.DataFrame:
    """Load weekly fantasy performance data."""
    conn = get_connection()

    df = read_sqlite_robust(f"""
        SELECT *
        FROM silver_weekly_performance
        WHERE season = {season}
    """, conn)
    conn.close()
    return df


def load_free_agents() -> pl.DataFrame:
    """Load current free agents from ESPN."""
    conn = get_connection()

    df = read_sqlite_robust("""
        SELECT
            player_name, position, pro_team as team,
            projected_total_points, total_points,
            percent_owned, percent_started,
            injury_status
        FROM bronze_espn_free_agents
    """, conn)
    conn.close()
    return df


def get_injured_starters(season: int = 2025, week: int = None) -> pl.DataFrame:
    """
    Find players who are injured and were starters (depth position 1).

    Returns DataFrame with injured starters and their backup info.
    """
    injuries = load_injuries(season, week)
    depth = load_depth_charts(season, week)

    if injuries.is_empty() or depth.is_empty():
        return pl.DataFrame()

    # Filter to meaningful injury statuses
    injured = injuries.filter(
        pl.col("report_status").is_in(["Out", "Doubtful", "Questionable", "IR"])
        | pl.col("practice_status").is_in(["DNP", "Did Not Participate", "Limited"])
    )

    # Get starters from depth chart (pos_rank = 1 or depth_position = 1)
    starters = depth.filter(
        (pl.col("pos_rank") == 1) | (pl.col("depth_position") == 1)
    )

    # Join to find injured starters
    injured_starters = injured.join(
        starters.select(["gsis_id", "team", "position", "week"]),
        on=["gsis_id", "team", "week"],
        how="inner",
        suffix="_depth"
    )

    return injured_starters


def get_backup_value(
    team: str,
    position: str,
    season: int = 2025,
    week: Optional[int] = None
) -> pl.DataFrame:
    """
    Get backup players who could see increased value if starter is out.

    Returns depth chart for the position on the team.
    """
    depth = load_depth_charts(season, week)

    backups = depth.filter(
        (pl.col("team") == team) &
        (pl.col("position") == position)
    ).sort("pos_rank")

    return backups


def analyze_injury_impact(season: int = 2025, week: Optional[int] = None) -> list[dict]:
    """
    Analyze injuries and identify backup players who gain value.

    Returns list of opportunities with:
    - injured_player: Who's hurt
    - injury_status: Their status
    - backup_player: Who benefits
    - position: Position
    - team: NFL team
    - opportunity_score: Estimated value increase
    """
    injuries = load_injuries(season, week)
    depth = load_depth_charts(season, week)
    weekly = load_weekly_performance(season)

    if injuries.is_empty() or depth.is_empty():
        return []

    opportunities = []

    # Get latest week if not specified
    if week is None and not depth.is_empty():
        week = depth["week"].max()

    # Filter to significant injuries
    significant_injuries = injuries.filter(
        (pl.col("week") == week) &
        (
            pl.col("report_status").is_in(["Out", "Doubtful", "IR"]) |
            pl.col("practice_status").is_in(["DNP", "Did Not Participate"])
        )
    )

    for row in significant_injuries.iter_rows(named=True):
        player_name = row["full_name"]
        team = row["team"]
        position = row["position"]
        gsis_id = row["gsis_id"]
        injury = row.get("report_primary_injury", "Unknown")
        status = row.get("report_status") or row.get("practice_status", "Unknown")

        # Check if this player was a starter
        player_depth = depth.filter(
            (pl.col("gsis_id") == gsis_id) &
            (pl.col("week") == week)
        )

        if player_depth.is_empty():
            continue

        pos_rank = player_depth["pos_rank"][0] if "pos_rank" in player_depth.columns else 99

        # Only care about starters (rank 1-2)
        if pos_rank > 2:
            continue

        # Find the backup
        team_depth = depth.filter(
            (pl.col("team") == team) &
            (pl.col("position") == position) &
            (pl.col("week") == week)
        ).sort("pos_rank")

        # Get next player in depth chart
        backup = None
        for depth_row in team_depth.iter_rows(named=True):
            if depth_row["gsis_id"] != gsis_id:
                backup = depth_row
                break

        if backup is None:
            continue

        # Calculate opportunity score based on injured player's production
        injured_stats = weekly.filter(
            (pl.col("gsis_id") == gsis_id) &
            (pl.col("season") == season)
        )

        avg_pts = 0
        if not injured_stats.is_empty():
            avg_pts = injured_stats["fantasy_points"].mean() or 0

        # Higher score = better opportunity
        opportunity_score = avg_pts * (1.5 if status in ["Out", "IR"] else 1.0)

        opportunities.append({
            "injured_player": player_name,
            "injury": injury,
            "status": status,
            "backup_player": backup["full_name"],
            "backup_gsis_id": backup["gsis_id"],
            "position": position,
            "team": team,
            "injured_avg_pts": avg_pts,
            "opportunity_score": opportunity_score,
        })

    # Sort by opportunity score
    opportunities.sort(key=lambda x: x["opportunity_score"], reverse=True)

    return opportunities


def get_snap_trends(
    season: int = 2025,
    min_weeks: int = 3,
    min_trend: float = 10.0
) -> pl.DataFrame:
    """
    Find players with increasing snap count trends.

    Returns players whose snap percentage has increased by min_trend
    over the last min_weeks.
    """
    snaps = load_snap_counts(season)

    if snaps.is_empty():
        return pl.DataFrame()

    # Calculate trend per player
    trends = snaps.group_by(["full_name", "position", "team"]).agg([
        pl.col("offense_pct").mean().alias("avg_snap_pct"),
        pl.col("offense_pct").last().alias("recent_snap_pct"),
        pl.col("offense_pct").first().alias("early_snap_pct"),
        pl.len().alias("games"),
    ]).filter(
        pl.col("games") >= min_weeks
    ).with_columns(
        (pl.col("recent_snap_pct") - pl.col("early_snap_pct")).alias("snap_trend")
    ).filter(
        pl.col("snap_trend") >= min_trend
    ).sort("snap_trend", descending=True)

    return trends


def get_target_share_trends(season: int = 2025, min_weeks: int = 3) -> pl.DataFrame:
    """
    Find players with increasing target share trends.
    """
    weekly = load_weekly_performance(season)

    if weekly.is_empty():
        return pl.DataFrame()

    # Calculate team totals per week
    team_targets = weekly.group_by(["season", "week", "team"]).agg(
        pl.col("targets").sum().alias("team_targets")
    )

    # Join back to get target share
    with_share = weekly.join(
        team_targets,
        on=["season", "week", "team"],
        how="left"
    ).with_columns(
        (pl.col("targets") / pl.col("team_targets") * 100).alias("target_share")
    )

    # Calculate trends
    trends = with_share.filter(
        pl.col("position").is_in(["WR", "TE", "RB"])
    ).group_by(["gsis_id", "full_name", "position", "team"]).agg([
        pl.col("target_share").mean().alias("avg_target_share"),
        pl.col("target_share").last().alias("recent_target_share"),
        pl.col("target_share").first().alias("early_target_share"),
        pl.col("targets").sum().alias("total_targets"),
        pl.len().alias("games"),
    ]).filter(
        pl.col("games") >= min_weeks
    ).with_columns(
        (pl.col("recent_target_share") - pl.col("early_target_share")).alias("share_trend")
    ).filter(
        pl.col("share_trend") > 0
    ).sort("share_trend", descending=True)

    return trends

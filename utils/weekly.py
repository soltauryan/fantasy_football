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
            season,
            week,
            club_code as team,
            gsis_id,
            full_name,
            position,
            depth_position,
            CAST(depth_team AS INTEGER) as pos_rank,
            formation
        FROM bronze_depth_charts
        WHERE season = {season}
        AND position IN ('QB', 'RB', 'WR', 'TE')
        AND club_code IS NOT NULL
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


def load_espn_injuries() -> pl.DataFrame:
    """
    Load injury data from ESPN rosters (works for 2025+).

    nflreadpy injury data returns 404 for 2025, so we use ESPN roster
    injury_status as a fallback for current season injuries.
    """
    conn = get_connection()

    df = read_sqlite_robust("""
        SELECT
            r.player_name as full_name,
            r.position,
            r.pro_team as team,
            r.injury_status,
            r.is_injured,
            r.lineup_slot,
            r.projected_total_points,
            r.total_points,
            p.gsis_id
        FROM bronze_espn_rosters r
        LEFT JOIN silver_players p ON r.player_name = p.full_name
        WHERE r.injury_status IS NOT NULL
        AND r.injury_status NOT IN ('ACTIVE', 'NORMAL')
    """, conn)
    conn.close()
    return df


def load_all_rosters() -> pl.DataFrame:
    """Load all ESPN rosters (rostered players only)."""
    conn = get_connection()

    df = read_sqlite_robust("""
        SELECT
            r.team_id,
            r.player_name as full_name,
            r.position,
            r.pro_team as team,
            r.injury_status,
            r.lineup_slot,
            r.projected_total_points,
            r.total_points,
            p.gsis_id
        FROM bronze_espn_rosters r
        LEFT JOIN silver_players p ON r.player_name = p.full_name
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


def analyze_injury_impact_espn(season: int = 2025) -> list[dict]:
    """
    Analyze injuries using ESPN roster data (works for 2025+).

    Enhanced version that:
    - Uses ESPN injury_status (QUESTIONABLE, INJURY_RESERVE, OUT)
    - Projects snap count changes based on historical data
    - Estimates target share redistribution
    - Identifies rostered vs free agent backups

    Returns list of opportunities with detailed projections.
    """
    espn_injuries = load_espn_injuries()
    depth = load_depth_charts(season)
    weekly = load_weekly_performance(season)
    snaps = load_snap_counts(season)
    rosters = load_all_rosters()

    if espn_injuries.is_empty():
        return []

    if depth.is_empty():
        # Fall back to previous season for depth chart data
        depth = load_depth_charts(season - 1)
        if depth.is_empty():
            return []

    opportunities = []

    # Use week 18 (end of regular season) for depth charts
    # Playoff weeks (19+) don't have all teams
    available_weeks = [w for w in depth["week"].unique().to_list() if w is not None]
    latest_week = min(max(available_weeks), 18) if available_weeks else 18

    for row in espn_injuries.iter_rows(named=True):
        player_name = row["full_name"]
        team = row["team"]
        position = row["position"]
        gsis_id = row.get("gsis_id")
        injury_status = row["injury_status"]

        # Filter non-fantasy positions
        if position not in ["QB", "RB", "WR", "TE"]:
            continue

        # Check if player is a starter via depth chart (match by name, team, position)
        player_depth = depth.filter(
            (pl.col("full_name") == player_name) &
            (pl.col("team") == team) &
            (pl.col("week") == latest_week)
        )

        # If no match by full name, try first name match
        if player_depth.is_empty():
            first_name = player_name.split()[0] if player_name else ""
            if first_name:
                player_depth = depth.filter(
                    (pl.col("full_name").str.starts_with(first_name)) &
                    (pl.col("team") == team) &
                    (pl.col("position") == position) &
                    (pl.col("week") == latest_week)
                )

        if player_depth.is_empty():
            continue

        pos_rank = player_depth["pos_rank"][0] if "pos_rank" in player_depth.columns else 99

        # Only care about top-2 depth players
        if pos_rank > 2:
            continue

        # Find backups from depth chart
        team_depth = depth.filter(
            (pl.col("team") == team) &
            (pl.col("position") == position) &
            (pl.col("week") == latest_week)
        ).sort("pos_rank")

        # Get next player in depth chart
        backups = []
        for depth_row in team_depth.iter_rows(named=True):
            if depth_row["full_name"] != player_name:
                backups.append(depth_row)
                if len(backups) >= 2:
                    break

        if not backups:
            continue

        # Calculate injured player's historical stats (match by name and team)
        injured_stats = weekly.filter(
            (pl.col("full_name") == player_name) &
            (pl.col("team") == team) &
            (pl.col("season") == season)
        )

        # Fall back to first name match if needed
        if injured_stats.is_empty():
            first_name = player_name.split()[0] if player_name else ""
            if first_name:
                injured_stats = weekly.filter(
                    (pl.col("full_name").str.starts_with(first_name)) &
                    (pl.col("team") == team) &
                    (pl.col("position") == position) &
                    (pl.col("season") == season)
                )

        avg_pts = 0
        avg_targets = 0
        if not injured_stats.is_empty():
            avg_pts = injured_stats["fantasy_points"].mean() or 0
            avg_targets = injured_stats["targets"].mean() or 0

        # Get injured player's snap percentage
        injured_snaps = snaps.filter(
            (pl.col("full_name") == player_name) &
            (pl.col("team") == team)
        )
        avg_snap_pct = 0
        if not injured_snaps.is_empty():
            avg_snap_pct = injured_snaps["offense_pct"].mean() or 0

        # Severity multiplier
        if injury_status == "INJURY_RESERVE":
            severity = 1.5
            miss_weeks = "4+"
        elif injury_status == "OUT":
            severity = 1.3
            miss_weeks = "1-2"
        elif injury_status == "DOUBTFUL":
            severity = 1.1
            miss_weeks = "1"
        else:  # QUESTIONABLE
            severity = 0.8
            miss_weeks = "?"

        # Opportunity score
        opportunity_score = avg_pts * severity

        # Process each backup
        for i, backup in enumerate(backups):
            backup_name = backup["full_name"]
            backup_gsis = backup.get("gsis_id")

            # Get backup's current snap percentage
            backup_snaps = snaps.filter(
                (pl.col("full_name") == backup_name) &
                (pl.col("team") == team)
            )
            backup_snap_pct = 0
            if not backup_snaps.is_empty():
                backup_snap_pct = backup_snaps["offense_pct"].mean() or 0

            # Project snap increase (backup gets portion of injured player's snaps)
            # Primary backup gets ~70%, secondary gets ~30%
            snap_share = 0.7 if i == 0 else 0.3
            projected_snap_increase = avg_snap_pct * snap_share
            projected_new_snap_pct = backup_snap_pct + projected_snap_increase

            # Target share projection (receivers only)
            projected_target_increase = 0
            if position in ["WR", "TE", "RB"]:
                target_share = 0.6 if i == 0 else 0.3
                projected_target_increase = avg_targets * target_share

            # Check if backup is rostered (and by whom)
            rostered_by = None
            backup_roster = rosters.filter(
                pl.col("full_name") == backup_name
            )
            if not backup_roster.is_empty():
                team_id = backup_roster["team_id"][0]
                if team_id == 6:
                    rostered_by = "ryan"
                elif team_id == 9:
                    rostered_by = "wife"
                else:
                    rostered_by = f"team_{team_id}"

            # Score adjustment: primary backup more valuable
            adjusted_score = opportunity_score * (1.0 if i == 0 else 0.5)

            opportunities.append({
                "injured_player": player_name,
                "injury_status": injury_status,
                "miss_weeks": miss_weeks,
                "backup_player": backup_name,
                "backup_rank": i + 1,
                "position": position,
                "team": team,
                "injured_avg_pts": avg_pts,
                "injured_avg_targets": avg_targets,
                "injured_snap_pct": avg_snap_pct,
                "backup_current_snap_pct": backup_snap_pct,
                "projected_snap_pct": projected_new_snap_pct,
                "snap_increase": projected_snap_increase,
                "projected_target_increase": projected_target_increase,
                "opportunity_score": adjusted_score,
                "rostered_by": rostered_by,
            })

    # Sort by opportunity score
    opportunities.sort(key=lambda x: x["opportunity_score"], reverse=True)

    return opportunities


def get_player_snap_history(player_name: str, season: int = 2025) -> pl.DataFrame:
    """Get weekly snap count history for a player."""
    snaps = load_snap_counts(season)

    if snaps.is_empty():
        return pl.DataFrame()

    return snaps.filter(
        pl.col("full_name").str.contains(player_name)
    ).sort("week")


def get_team_target_distribution(team: str, season: int = 2025) -> pl.DataFrame:
    """Get target distribution for a team's pass catchers."""
    weekly = load_weekly_performance(season)

    if weekly.is_empty():
        return pl.DataFrame()

    # Calculate team totals
    team_data = weekly.filter(
        (pl.col("team") == team) &
        (pl.col("position").is_in(["WR", "TE", "RB"]))
    )

    if team_data.is_empty():
        return pl.DataFrame()

    # Aggregate by player
    distribution = team_data.group_by(["full_name", "position"]).agg([
        pl.col("targets").sum().alias("total_targets"),
        pl.col("targets").mean().alias("avg_targets"),
        pl.col("fantasy_points").mean().alias("avg_pts"),
        pl.len().alias("games"),
    ]).sort("total_targets", descending=True)

    # Calculate share
    total_team_targets = distribution["total_targets"].sum()
    if total_team_targets > 0:
        distribution = distribution.with_columns(
            (pl.col("total_targets") / total_team_targets * 100).alias("target_share")
        )

    return distribution

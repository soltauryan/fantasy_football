"""
Matchup Analysis Utilities - Fantasy Football

Provides:
- Defense rankings by position (fantasy points allowed)
- Soft/tough matchup identification
- Week-ahead matchup projections
- Schedule analysis for streaming
"""

import polars as pl
from typing import Optional
from utils.db import get_connection, read_sqlite_robust


def load_schedule(season: int = 2025, week: Optional[int] = None) -> pl.DataFrame:
    """Load schedule data."""
    conn = get_connection()

    query = f"""
        SELECT
            season, week, game_type,
            away_team, home_team,
            away_score, home_score,
            gameday, gametime
        FROM bronze_schedules
        WHERE season = {season}
        AND game_type = 'REG'
    """
    if week:
        query += f" AND week = {week}"

    df = read_sqlite_robust(query, conn)
    conn.close()
    return df


def load_weekly_stats(season: int = 2025) -> pl.DataFrame:
    """Load weekly fantasy performance stats."""
    conn = get_connection()

    df = read_sqlite_robust(f"""
        SELECT
            season, week, gsis_id, full_name, position, team,
            fantasy_points, targets, receptions, rec_yards,
            rush_attempt, rush_yards
        FROM silver_weekly_performance
        WHERE season = {season}
        AND position IN ('QB', 'RB', 'WR', 'TE')
    """, conn)
    conn.close()
    return df


def get_opponent_for_game(team: str, week: int, schedule: pl.DataFrame) -> Optional[str]:
    """Get the opponent for a team in a given week."""
    game = schedule.filter(
        (pl.col("week") == week) &
        ((pl.col("home_team") == team) | (pl.col("away_team") == team))
    )

    if game.is_empty():
        return None

    row = game.row(0, named=True)
    if row["home_team"] == team:
        return row["away_team"]
    return row["home_team"]


def calculate_defense_rankings(
    season: int = 2025,
    min_games: int = 3
) -> pl.DataFrame:
    """
    Calculate fantasy points allowed by each defense, by position.

    Returns DataFrame with columns:
    - defense: Team abbreviation
    - position: QB/RB/WR/TE
    - pts_allowed: Average fantasy points allowed to that position
    - games: Number of games sampled
    - rank: 1=most points allowed (worst defense), 32=least allowed (best)
    """
    weekly = load_weekly_stats(season)
    schedule = load_schedule(season)

    if weekly.is_empty() or schedule.is_empty():
        return pl.DataFrame()

    # Add opponent to each player's weekly stats
    results = []

    for row in weekly.iter_rows(named=True):
        team = row["team"]
        week = row["week"]
        opponent = get_opponent_for_game(team, week, schedule)

        if opponent:
            results.append({
                "defense": opponent,
                "position": row["position"],
                "fantasy_points": row["fantasy_points"],
                "week": week,
            })

    if not results:
        return pl.DataFrame()

    df = pl.DataFrame(results)

    # Aggregate by defense and position
    rankings = df.group_by(["defense", "position"]).agg([
        pl.col("fantasy_points").mean().alias("pts_allowed"),
        pl.col("fantasy_points").sum().alias("total_pts_allowed"),
        pl.len().alias("games"),
    ]).filter(
        pl.col("games") >= min_games
    )

    # Add rank within each position (1 = worst defense = most pts allowed)
    rankings = rankings.with_columns(
        pl.col("pts_allowed")
        .rank(descending=True, method="min")
        .over("position")
        .alias("rank")
    ).sort(["position", "rank"])

    return rankings


def get_position_matchups(
    position: str,
    season: int = 2025
) -> pl.DataFrame:
    """Get matchup rankings for a specific position."""
    rankings = calculate_defense_rankings(season)

    if rankings.is_empty():
        return rankings

    return rankings.filter(
        pl.col("position") == position
    ).sort("rank")


def get_soft_matchups(
    week: int,
    season: int = 2025,
    top_n: int = 10
) -> list[dict]:
    """
    Get the softest matchups for a given week.

    Returns list of dicts with:
    - team: Offensive team
    - opponent: Defensive team (the soft defense)
    - position: Position with favorable matchup
    - def_rank: How bad the defense is (1=worst)
    - pts_allowed: Avg points allowed to position
    """
    rankings = calculate_defense_rankings(season)
    schedule = load_schedule(season, week)

    if rankings.is_empty() or schedule.is_empty():
        return []

    matchups = []

    for row in schedule.iter_rows(named=True):
        home = row["home_team"]
        away = row["away_team"]

        # Check each team's opponent defense
        for offense, defense in [(home, away), (away, home)]:
            # Get defense rankings for opponent
            def_ranks = rankings.filter(pl.col("defense") == defense)

            for def_row in def_ranks.iter_rows(named=True):
                if def_row["rank"] <= 10:  # Top 10 worst defenses
                    matchups.append({
                        "team": offense,
                        "opponent": defense,
                        "position": def_row["position"],
                        "def_rank": def_row["rank"],
                        "pts_allowed": def_row["pts_allowed"],
                    })

    # Sort by worst defense first
    matchups.sort(key=lambda x: (x["def_rank"], -x["pts_allowed"]))

    return matchups[:top_n * 4]  # Return top N per position roughly


def get_team_schedule_difficulty(
    team: str,
    season: int = 2025,
    position: str = "RB"
) -> pl.DataFrame:
    """
    Get schedule difficulty for a team at a position.

    Returns each week's opponent and their defensive ranking.
    """
    schedule = load_schedule(season)
    rankings = calculate_defense_rankings(season)

    if schedule.is_empty() or rankings.is_empty():
        return pl.DataFrame()

    results = []

    for row in schedule.iter_rows(named=True):
        week = row["week"]

        if row["home_team"] == team:
            opponent = row["away_team"]
            home_away = "home"
        elif row["away_team"] == team:
            opponent = row["home_team"]
            home_away = "away"
        else:
            continue

        # Get opponent's defensive ranking for position
        def_rank = rankings.filter(
            (pl.col("defense") == opponent) &
            (pl.col("position") == position)
        )

        if not def_rank.is_empty():
            rank = def_rank["rank"][0]
            pts = def_rank["pts_allowed"][0]
        else:
            rank = 16  # Default to middle
            pts = 0

        results.append({
            "week": week,
            "opponent": opponent,
            "home_away": home_away,
            "def_rank": rank,
            "pts_allowed": pts,
            "matchup_grade": get_matchup_grade(rank),
        })

    return pl.DataFrame(results).sort("week")


def get_matchup_grade(rank: int) -> str:
    """Convert defensive rank to a letter grade."""
    if rank <= 5:
        return "A+"  # Smash spot
    elif rank <= 10:
        return "A"   # Great matchup
    elif rank <= 15:
        return "B"   # Good matchup
    elif rank <= 20:
        return "C"   # Average
    elif rank <= 26:
        return "D"   # Tough matchup
    else:
        return "F"   # Avoid


def get_streaming_candidates(
    week: int,
    position: str,
    season: int = 2025,
    top_n: int = 10
) -> list[dict]:
    """
    Get streaming candidates for a position based on matchup.

    Returns players with good matchups who might be available.
    """
    from utils.weekly import load_free_agents, load_weekly_performance

    rankings = calculate_defense_rankings(season)
    schedule = load_schedule(season, week)
    free_agents = load_free_agents()
    weekly = load_weekly_performance(season)

    if any(df.is_empty() for df in [rankings, schedule, free_agents]):
        return []

    # Filter free agents to position
    pos_fa = free_agents.filter(pl.col("position") == position)

    candidates = []

    for row in pos_fa.iter_rows(named=True):
        player_name = row["player_name"]
        team = row["team"]

        if team is None:
            continue

        # Get opponent this week
        opponent = get_opponent_for_game(team, week, schedule)
        if opponent is None:
            continue

        # Get opponent defensive ranking
        def_rank = rankings.filter(
            (pl.col("defense") == opponent) &
            (pl.col("position") == position)
        )

        if def_rank.is_empty():
            continue

        rank = def_rank["rank"][0]
        pts_allowed = def_rank["pts_allowed"][0]

        # Only include good matchups (rank <= 12)
        if rank > 12:
            continue

        # Get player's recent performance
        player_stats = weekly.filter(
            pl.col("full_name").str.contains(player_name.split()[0])
        )
        avg_pts = 0
        if not player_stats.is_empty():
            avg_pts = player_stats["fantasy_points"].mean() or 0

        candidates.append({
            "player": player_name,
            "team": team,
            "opponent": opponent,
            "position": position,
            "def_rank": rank,
            "pts_allowed": pts_allowed,
            "matchup_grade": get_matchup_grade(rank),
            "avg_pts": avg_pts,
            "pct_owned": row.get("percent_owned", 0) or 0,
        })

    # Sort by matchup quality then player average
    candidates.sort(key=lambda x: (x["def_rank"], -x["avg_pts"]))

    return candidates[:top_n]


def get_week_matchup_overview(week: int, season: int = 2025) -> dict:
    """
    Get a complete matchup overview for a week.

    Returns dict with best and worst matchups by position.
    """
    soft = get_soft_matchups(week, season)

    # Group by position
    by_position = {}
    for pos in ["QB", "RB", "WR", "TE"]:
        pos_matchups = [m for m in soft if m["position"] == pos]
        by_position[pos] = pos_matchups[:5]

    return {
        "week": week,
        "soft_matchups": by_position,
    }


def print_defense_rankings(season: int = 2025, position: Optional[str] = None):
    """Print defense rankings in a formatted table."""
    rankings = calculate_defense_rankings(season)

    if rankings.is_empty():
        print("No ranking data available.")
        return

    if position:
        rankings = rankings.filter(pl.col("position") == position)

    positions = rankings["position"].unique().sort().to_list()

    for pos in positions:
        pos_ranks = rankings.filter(pl.col("position") == pos).sort("rank")

        print(f"\n{'=' * 50}")
        print(f"  {pos} - DEFENSE RANKINGS (Fantasy Pts Allowed)")
        print(f"{'=' * 50}")
        print(f"{'Rank':<5} {'Defense':<6} {'Pts Allowed':>12} {'Games':>6} {'Grade':<6}")
        print("-" * 40)

        for row in pos_ranks.iter_rows(named=True):
            grade = get_matchup_grade(row["rank"])
            print(
                f"{row['rank']:<5} "
                f"{row['defense']:<6} "
                f"{row['pts_allowed']:>12.1f} "
                f"{row['games']:>6} "
                f"{grade:<6}"
            )

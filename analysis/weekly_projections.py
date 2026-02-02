#!/usr/bin/env python3
"""
Week-Ahead Projections with Uncertainty Ranges

Projects fantasy points for the upcoming week with confidence intervals.

Factors in:
- Historical performance (baseline projection)
- Matchup quality (defense ranking adjustment)
- Recent form (last 3 games trend)
- Injury status (discount for questionable/doubtful)
- Player variance (uncertainty range)

Usage:
    uv run python analysis/weekly_projections.py --week 1           # Week 1 projections
    uv run python analysis/weekly_projections.py --week 1 --team ryan  # Ryan's roster
    uv run python analysis/weekly_projections.py --week 1 --pos RB     # RB projections only
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import polars as pl
from dataclasses import dataclass
from typing import Optional

from utils.db import get_connection, read_sqlite_robust
from utils.matchups import (
    calculate_defense_rankings,
    load_schedule,
    get_opponent_for_game,
    get_matchup_grade,
)
from utils.weekly import load_espn_injuries, load_weekly_performance

# Team configuration
MY_TEAM_IDS = {
    "ryan": 6,
    "wife": 9,
}

# Matchup adjustment factors (based on defense rank)
MATCHUP_ADJUSTMENTS = {
    "A+": 1.15,  # Rank 1-5: +15% boost
    "A": 1.10,   # Rank 6-10: +10% boost
    "B": 1.05,   # Rank 11-15: +5% boost
    "C": 1.00,   # Rank 16-20: neutral
    "D": 0.95,   # Rank 21-26: -5% penalty
    "F": 0.90,   # Rank 27-32: -10% penalty
}

# Injury status adjustments
INJURY_ADJUSTMENTS = {
    "ACTIVE": 1.0,
    "NORMAL": 1.0,
    "QUESTIONABLE": 0.85,  # 15% discount for game-time decisions
    "DOUBTFUL": 0.40,      # 60% discount, likely out
    "OUT": 0.0,
    "INJURY_RESERVE": 0.0,
    "SUSPENDED": 0.0,
}


@dataclass
class PlayerProjection:
    """Projection for a single player."""
    player_name: str
    position: str
    team: str
    opponent: str
    matchup_grade: str
    injury_status: Optional[str]
    base_projection: float
    matchup_adjusted: float
    injury_adjusted: float
    floor: float  # 10th percentile
    ceiling: float  # 90th percentile
    confidence: str  # "High", "Medium", "Low"
    recent_form: str  # "Hot", "Cold", "Stable"


def load_player_history(season: int = 2025) -> pl.DataFrame:
    """Load player weekly history with stats for projections."""
    conn = get_connection()

    df = read_sqlite_robust(f"""
        SELECT
            gsis_id, full_name, position, team,
            week, fantasy_points
        FROM silver_weekly_performance
        WHERE season = {season}
        AND position IN ('QB', 'RB', 'WR', 'TE')
        ORDER BY full_name, week
    """, conn)
    conn.close()
    return df


def load_team_rosters() -> dict[str, pl.DataFrame]:
    """Load current rosters for both teams."""
    conn = get_connection()

    rosters = {}
    for team_key, team_id in MY_TEAM_IDS.items():
        df = read_sqlite_robust(f"""
            SELECT
                player_name, position, pro_team as team,
                injury_status, projected_total_points
            FROM bronze_espn_rosters
            WHERE team_id = {team_id}
            AND position IN ('QB', 'RB', 'WR', 'TE')
        """, conn)
        rosters[team_key] = df

    conn.close()
    return rosters


def calculate_player_stats(history: pl.DataFrame, player_name: str) -> dict:
    """Calculate projection stats for a player."""
    player_data = history.filter(
        pl.col("full_name") == player_name
    ).sort("week")

    if player_data.is_empty():
        return {
            "avg": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
            "recent_avg": 0.0,
            "games": 0,
            "trend": 0.0,
        }

    points = player_data["fantasy_points"].to_list()
    games = len(points)

    avg = sum(points) / games if games > 0 else 0
    variance = sum((p - avg) ** 2 for p in points) / games if games > 0 else 0
    std = variance ** 0.5

    # Recent form (last 3 games)
    recent = points[-3:] if len(points) >= 3 else points
    recent_avg = sum(recent) / len(recent) if recent else 0

    # Trend: recent vs season average
    trend = recent_avg - avg if avg > 0 else 0

    return {
        "avg": avg,
        "std": std,
        "min": min(points) if points else 0,
        "max": max(points) if points else 0,
        "recent_avg": recent_avg,
        "games": games,
        "trend": trend,
    }


def get_confidence_level(games: int, std: float, avg: float) -> str:
    """Determine projection confidence level."""
    if games < 3:
        return "Low"

    # Coefficient of variation (relative volatility)
    cv = std / avg if avg > 0 else 1.0

    if games >= 10 and cv < 0.3:
        return "High"
    elif games >= 5 and cv < 0.5:
        return "Medium"
    else:
        return "Low"


def get_recent_form(trend: float, avg: float) -> str:
    """Determine if player is hot, cold, or stable."""
    if avg == 0:
        return "Stable"

    trend_pct = trend / avg

    if trend_pct > 0.15:
        return "Hot"
    elif trend_pct < -0.15:
        return "Cold"
    else:
        return "Stable"


def project_player(
    player_name: str,
    position: str,
    team: str,
    week: int,
    history: pl.DataFrame,
    def_rankings: pl.DataFrame,
    schedule: pl.DataFrame,
    injuries: pl.DataFrame,
    season: int = 2025,
) -> Optional[PlayerProjection]:
    """Generate projection for a single player."""

    # Get player stats
    stats = calculate_player_stats(history, player_name)

    if stats["games"] == 0:
        # Try partial name match
        first_name = player_name.split()[0]
        partial_history = history.filter(
            pl.col("full_name").str.starts_with(first_name) &
            (pl.col("team") == team)
        )
        if not partial_history.is_empty():
            matched_name = partial_history["full_name"][0]
            stats = calculate_player_stats(history, matched_name)

    if stats["games"] == 0:
        return None

    # Get opponent
    opponent = get_opponent_for_game(team, week, schedule)
    if opponent is None:
        # Bye week
        return PlayerProjection(
            player_name=player_name,
            position=position,
            team=team,
            opponent="BYE",
            matchup_grade="-",
            injury_status=None,
            base_projection=0.0,
            matchup_adjusted=0.0,
            injury_adjusted=0.0,
            floor=0.0,
            ceiling=0.0,
            confidence="High",
            recent_form="Stable",
        )

    # Get matchup grade
    def_rank = def_rankings.filter(
        (pl.col("defense") == opponent) &
        (pl.col("position") == position)
    )

    if not def_rank.is_empty():
        rank = def_rank["rank"][0]
        matchup_grade = get_matchup_grade(rank)
    else:
        matchup_grade = "C"  # Default to neutral

    # Get injury status
    injury_status = None
    if not injuries.is_empty():
        player_injury = injuries.filter(
            pl.col("full_name") == player_name
        )
        if not player_injury.is_empty():
            injury_status = player_injury["injury_status"][0]

    # Calculate projections
    base_projection = stats["avg"]

    # Apply recent form adjustment (weight recent performance)
    if stats["trend"] != 0:
        form_factor = 1.0 + (stats["trend"] / stats["avg"] * 0.3) if stats["avg"] > 0 else 1.0
        form_factor = max(0.8, min(1.2, form_factor))  # Cap at +/- 20%
        base_projection *= form_factor

    # Apply matchup adjustment
    matchup_factor = MATCHUP_ADJUSTMENTS.get(matchup_grade, 1.0)
    matchup_adjusted = base_projection * matchup_factor

    # Apply injury adjustment
    injury_factor = INJURY_ADJUSTMENTS.get(injury_status, 1.0) if injury_status else 1.0
    injury_adjusted = matchup_adjusted * injury_factor

    # Calculate floor/ceiling (using std dev)
    std = stats["std"]
    floor = max(0, injury_adjusted - 1.3 * std)  # ~10th percentile
    ceiling = injury_adjusted + 1.3 * std  # ~90th percentile

    # Confidence and form
    confidence = get_confidence_level(stats["games"], std, stats["avg"])
    recent_form = get_recent_form(stats["trend"], stats["avg"])

    return PlayerProjection(
        player_name=player_name,
        position=position,
        team=team,
        opponent=opponent,
        matchup_grade=matchup_grade,
        injury_status=injury_status,
        base_projection=round(base_projection, 1),
        matchup_adjusted=round(matchup_adjusted, 1),
        injury_adjusted=round(injury_adjusted, 1),
        floor=round(floor, 1),
        ceiling=round(ceiling, 1),
        confidence=confidence,
        recent_form=recent_form,
    )


def generate_projections(
    week: int,
    season: int = 2025,
    position: Optional[str] = None,
    team_key: Optional[str] = None,
) -> list[PlayerProjection]:
    """Generate projections for players."""

    # Load data
    history = load_player_history(season)
    def_rankings = calculate_defense_rankings(season)
    schedule = load_schedule(season)
    injuries = load_espn_injuries()

    if history.is_empty():
        # Fall back to previous season
        history = load_player_history(season - 1)

    if def_rankings.is_empty():
        def_rankings = calculate_defense_rankings(season - 1)

    projections = []

    if team_key:
        # Project specific team's roster
        rosters = load_team_rosters()
        if team_key not in rosters:
            return []

        roster = rosters[team_key]
        for row in roster.iter_rows(named=True):
            player_name = row["player_name"]
            pos = row["position"]
            team = row["team"]

            if position and pos != position:
                continue

            proj = project_player(
                player_name, pos, team, week,
                history, def_rankings, schedule, injuries, season
            )
            if proj:
                projections.append(proj)
    else:
        # Project all players with history
        players = history.group_by(["full_name", "position", "team"]).agg(
            pl.len().alias("games")
        ).filter(pl.col("games") >= 3)

        for row in players.iter_rows(named=True):
            player_name = row["full_name"]
            pos = row["position"]
            team = row["team"]

            if position and pos != position:
                continue

            proj = project_player(
                player_name, pos, team, week,
                history, def_rankings, schedule, injuries, season
            )
            if proj:
                projections.append(proj)

    # Sort by projected points
    projections.sort(key=lambda p: p.injury_adjusted, reverse=True)

    return projections


def print_header(title: str):
    """Print formatted header."""
    print("\n" + "=" * 90)
    print(f"  {title}")
    print("=" * 90)


def print_projections(projections: list[PlayerProjection], top_n: int = 30):
    """Print projections in formatted table."""

    if not projections:
        print("\nNo projections available.")
        return

    print(f"\n{'#':<3} {'Player':<22} {'Pos':<4} {'vs':<5} {'Match':<5} "
          f"{'Proj':>6} {'Floor':>6} {'Ceil':>7} {'Conf':<6} {'Form':<6} {'Inj':<8}")
    print("-" * 90)

    for i, p in enumerate(projections[:top_n], 1):
        inj = p.injury_status[:7] if p.injury_status else "-"
        print(
            f"{i:<3} "
            f"{p.player_name[:21]:<22} "
            f"{p.position:<4} "
            f"{p.opponent:<5} "
            f"{p.matchup_grade:<5} "
            f"{p.injury_adjusted:>6.1f} "
            f"{p.floor:>6.1f} "
            f"{p.ceiling:>7.1f} "
            f"{p.confidence:<6} "
            f"{p.recent_form:<6} "
            f"{inj:<8}"
        )


def print_position_summary(projections: list[PlayerProjection]):
    """Print summary by position."""
    print_header("POSITION SUMMARY")

    by_pos = {}
    for p in projections:
        if p.position not in by_pos:
            by_pos[p.position] = []
        by_pos[p.position].append(p)

    for pos in ["QB", "RB", "WR", "TE"]:
        if pos not in by_pos:
            continue

        pos_projs = by_pos[pos][:10]
        print(f"\n--- {pos} ---")
        print(f"{'Player':<22} {'vs':<5} {'Proj':>6} {'Range':>14} {'Form':<6}")
        print("-" * 55)

        for p in pos_projs:
            range_str = f"{p.floor:.0f}-{p.ceiling:.0f}"
            print(
                f"{p.player_name[:21]:<22} "
                f"{p.opponent:<5} "
                f"{p.injury_adjusted:>6.1f} "
                f"{range_str:>14} "
                f"{p.recent_form:<6}"
            )


def print_team_projections(projections: list[PlayerProjection], team_key: str):
    """Print projections for a specific fantasy team."""
    team_name = "SoltyTears4U" if team_key == "ryan" else "Serving Punt"

    print_header(f"WEEK PROJECTIONS: {team_name.upper()}")

    # Group by position
    by_pos = {"QB": [], "RB": [], "WR": [], "TE": []}
    for p in projections:
        if p.position in by_pos:
            by_pos[p.position].append(p)

    total_floor = 0
    total_proj = 0
    total_ceil = 0

    print(f"\n{'Slot':<6} {'Player':<22} {'vs':<5} {'Match':<5} "
          f"{'Proj':>6} {'Floor':>6} {'Ceil':>7} {'Form':<6}")
    print("-" * 75)

    # Starters
    slots = [
        ("QB", by_pos["QB"][:1]),
        ("RB1", by_pos["RB"][:1]),
        ("RB2", by_pos["RB"][1:2]),
        ("WR1", by_pos["WR"][:1]),
        ("WR2", by_pos["WR"][1:2]),
        ("TE", by_pos["TE"][:1]),
        ("FLEX", []),  # Best remaining RB/WR/TE
    ]

    used = set()
    for slot, players in slots:
        if slot == "FLEX":
            # Find best remaining flex
            flex_options = []
            for pos in ["RB", "WR", "TE"]:
                for p in by_pos[pos]:
                    if p.player_name not in used:
                        flex_options.append(p)
            flex_options.sort(key=lambda x: x.injury_adjusted, reverse=True)
            players = flex_options[:1]

        if players:
            p = players[0]
            used.add(p.player_name)
            total_floor += p.floor
            total_proj += p.injury_adjusted
            total_ceil += p.ceiling

            print(
                f"{slot:<6} "
                f"{p.player_name[:21]:<22} "
                f"{p.opponent:<5} "
                f"{p.matchup_grade:<5} "
                f"{p.injury_adjusted:>6.1f} "
                f"{p.floor:>6.1f} "
                f"{p.ceiling:>7.1f} "
                f"{p.recent_form:<6}"
            )
        else:
            print(f"{slot:<6} {'(empty)':<22}")

    print("-" * 75)
    print(f"{'TOTAL':<6} {'':<22} {'':<5} {'':<5} "
          f"{total_proj:>6.1f} {total_floor:>6.1f} {total_ceil:>7.1f}")

    # Show bench
    print(f"\n{'Bench':<6}")
    print("-" * 40)
    for pos in ["QB", "RB", "WR", "TE"]:
        for p in by_pos[pos]:
            if p.player_name not in used:
                print(f"  {p.player_name[:21]:<22} {p.position:<4} {p.injury_adjusted:>6.1f}")


def print_matchup_impacts(projections: list[PlayerProjection]):
    """Show players with biggest matchup impacts."""
    print_header("MATCHUP IMPACTS")

    # Find smash spots and avoid spots
    smash = [p for p in projections if p.matchup_grade == "A+" and p.injury_adjusted > 10]
    avoid = [p for p in projections if p.matchup_grade == "F" and p.injury_adjusted > 5]

    print("\n--- SMASH SPOTS (A+ Matchups) ---")
    for p in smash[:10]:
        print(f"  {p.player_name[:21]:<22} {p.position:<4} vs {p.opponent:<4} {p.injury_adjusted:>6.1f} pts")

    print("\n--- TOUGH MATCHUPS (F Grade) ---")
    for p in avoid[:10]:
        print(f"  {p.player_name[:21]:<22} {p.position:<4} vs {p.opponent:<4} {p.injury_adjusted:>6.1f} pts")


def main():
    parser = argparse.ArgumentParser(
        description="Week-Ahead Projections with Uncertainty Ranges",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python analysis/weekly_projections.py --week 1              # All projections
  uv run python analysis/weekly_projections.py --week 1 --team ryan  # Ryan's roster
  uv run python analysis/weekly_projections.py --week 1 --pos QB     # QB projections
  uv run python analysis/weekly_projections.py --week 1 --summary    # Position summary
        """
    )
    parser.add_argument("--week", type=int, required=True, help="Week number")
    parser.add_argument("--season", type=int, default=2025, help="Season year")
    parser.add_argument("--team", type=str, choices=["ryan", "wife"],
                        help="Show projections for a specific fantasy team")
    parser.add_argument("--pos", "--position", type=str,
                        choices=["QB", "RB", "WR", "TE"],
                        help="Filter by position")
    parser.add_argument("--top", type=int, default=30, help="Top N players to show")
    parser.add_argument("--summary", action="store_true",
                        help="Show position summary view")
    parser.add_argument("--matchups", action="store_true",
                        help="Show matchup impact analysis")
    args = parser.parse_args()

    print_header(f"WEEK {args.week} PROJECTIONS")
    print(f"Season: {args.season}")

    # Generate projections
    projections = generate_projections(
        args.week,
        args.season,
        args.pos,
        args.team,
    )

    if args.team:
        print_team_projections(projections, args.team)
    elif args.summary:
        print_position_summary(projections)
    elif args.matchups:
        print_matchup_impacts(projections)
    else:
        print_projections(projections, args.top)

    print("\n")


if __name__ == "__main__":
    main()

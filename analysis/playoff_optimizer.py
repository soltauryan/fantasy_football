#!/usr/bin/env python3
"""
Playoff Schedule Optimizer - Fantasy Football Season Management

Analyzes weeks 14-17 (fantasy playoffs) to identify:
- Players with favorable playoff schedules
- Players with tough playoff matchups to avoid
- Schedule difficulty scores
- Playoff streaming targets

Usage:
    uv run python analysis/playoff_optimizer.py                  # All positions
    uv run python analysis/playoff_optimizer.py --pos RB         # RB only
    uv run python analysis/playoff_optimizer.py --team ryan      # Ryan's roster
    uv run python analysis/playoff_optimizer.py --targets        # Acquisition targets
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

# Playoff weeks (standard fantasy playoffs)
PLAYOFF_WEEKS = [14, 15, 16, 17]

# Team configuration
MY_TEAM_IDS = {
    "ryan": 6,
    "wife": 9,
}


@dataclass
class PlayoffSchedule:
    """Playoff schedule analysis for a player."""
    player_name: str
    position: str
    team: str
    week_14: dict  # {"opponent": str, "rank": int, "grade": str}
    week_15: dict
    week_16: dict
    week_17: dict
    avg_rank: float
    schedule_score: float  # 0-100, higher is better
    schedule_grade: str  # A+, A, B, C, D, F
    smash_weeks: int  # Count of A+ matchups
    avoid_weeks: int  # Count of F matchups
    rostered_by: Optional[str]


def load_players_with_projections() -> pl.DataFrame:
    """Load players with projections."""
    conn = get_connection()

    # Get projections
    projections = read_sqlite_robust("""
        SELECT
            player_name, position,
            proj_total_points_2026 as projected_points
        FROM gold_projections_2026
        WHERE position IN ('QB', 'RB', 'WR', 'TE')
        AND proj_total_points_2026 > 100
    """, conn)

    # Get player team info
    players = read_sqlite_robust("""
        SELECT full_name, team
        FROM silver_players
        WHERE position IN ('QB', 'RB', 'WR', 'TE')
    """, conn)

    # Get roster info
    rosters = read_sqlite_robust("""
        SELECT player_name, team_id, pro_team as nfl_team
        FROM bronze_espn_rosters
    """, conn)

    conn.close()

    if projections.is_empty():
        return pl.DataFrame()

    # Join with team info
    result = projections.join(
        players.select(["full_name", "team"]),
        left_on="player_name",
        right_on="full_name",
        how="left"
    )

    # Add roster info
    result = result.join(
        rosters.select(["player_name", "team_id", "nfl_team"]),
        on="player_name",
        how="left"
    )

    # Fill team from roster if missing
    result = result.with_columns(
        pl.when(pl.col("team").is_null())
        .then(pl.col("nfl_team"))
        .otherwise(pl.col("team"))
        .alias("team")
    )

    return result


def analyze_playoff_schedule(
    player_name: str,
    position: str,
    team: str,
    team_id: Optional[int],
    def_rankings: pl.DataFrame,
    schedule: pl.DataFrame,
    season: int = 2025
) -> Optional[PlayoffSchedule]:
    """Analyze playoff schedule for a player."""

    if not team:
        return None

    week_data = {}
    total_rank = 0
    valid_weeks = 0

    for week in PLAYOFF_WEEKS:
        opponent = get_opponent_for_game(team, week, schedule)

        if opponent is None:
            week_data[f"week_{week}"] = {
                "opponent": "BYE",
                "rank": 16,
                "grade": "-"
            }
            continue

        # Get defensive ranking
        def_rank = def_rankings.filter(
            (pl.col("defense") == opponent) &
            (pl.col("position") == position)
        )

        if not def_rank.is_empty():
            rank = def_rank["rank"][0]
            grade = get_matchup_grade(rank)
        else:
            rank = 16
            grade = "C"

        week_data[f"week_{week}"] = {
            "opponent": opponent,
            "rank": rank,
            "grade": grade
        }

        total_rank += rank
        valid_weeks += 1

    if valid_weeks == 0:
        return None

    avg_rank = total_rank / valid_weeks

    # Calculate schedule score (0-100, lower rank = higher score)
    # Rank 1 = 100, Rank 32 = 0
    schedule_score = max(0, (33 - avg_rank) / 32 * 100)

    # Overall schedule grade
    if avg_rank <= 8:
        schedule_grade = "A+"
    elif avg_rank <= 12:
        schedule_grade = "A"
    elif avg_rank <= 16:
        schedule_grade = "B"
    elif avg_rank <= 20:
        schedule_grade = "C"
    elif avg_rank <= 24:
        schedule_grade = "D"
    else:
        schedule_grade = "F"

    # Count smash/avoid weeks
    smash_weeks = sum(1 for w in week_data.values() if w["grade"] == "A+")
    avoid_weeks = sum(1 for w in week_data.values() if w["grade"] == "F")

    # Rostered by
    rostered_by = None
    if team_id == 6:
        rostered_by = "ryan"
    elif team_id == 9:
        rostered_by = "wife"

    return PlayoffSchedule(
        player_name=player_name,
        position=position,
        team=team,
        week_14=week_data["week_14"],
        week_15=week_data["week_15"],
        week_16=week_data["week_16"],
        week_17=week_data["week_17"],
        avg_rank=round(avg_rank, 1),
        schedule_score=round(schedule_score, 1),
        schedule_grade=schedule_grade,
        smash_weeks=smash_weeks,
        avoid_weeks=avoid_weeks,
        rostered_by=rostered_by,
    )


def get_all_playoff_schedules(
    season: int = 2025,
    position: Optional[str] = None
) -> list[PlayoffSchedule]:
    """Get playoff schedules for all players."""
    players = load_players_with_projections()
    def_rankings = calculate_defense_rankings(season)
    schedule = load_schedule(season)

    if players.is_empty() or def_rankings.is_empty():
        return []

    schedules = []

    for row in players.iter_rows(named=True):
        player_name = row["player_name"]
        pos = row["position"]
        team = row.get("team") or row.get("nfl_team")
        team_id = row.get("team_id")

        if position and pos != position:
            continue

        if not team:
            continue

        sched = analyze_playoff_schedule(
            player_name, pos, team, team_id,
            def_rankings, schedule, season
        )

        if sched:
            schedules.append(sched)

    # Sort by schedule score
    schedules.sort(key=lambda x: x.schedule_score, reverse=True)

    return schedules


def get_team_playoff_analysis(team_key: str, season: int = 2025) -> list[PlayoffSchedule]:
    """Get playoff schedule analysis for a fantasy team's roster."""
    conn = get_connection()

    team_id = MY_TEAM_IDS.get(team_key)
    if not team_id:
        return []

    roster = read_sqlite_robust(f"""
        SELECT player_name, position, pro_team as team
        FROM bronze_espn_rosters
        WHERE team_id = {team_id}
        AND position IN ('QB', 'RB', 'WR', 'TE')
    """, conn)
    conn.close()

    if roster.is_empty():
        return []

    def_rankings = calculate_defense_rankings(season)
    schedule = load_schedule(season)

    schedules = []

    for row in roster.iter_rows(named=True):
        sched = analyze_playoff_schedule(
            row["player_name"],
            row["position"],
            row["team"],
            team_id,
            def_rankings, schedule, season
        )
        if sched:
            schedules.append(sched)

    # Sort by schedule score
    schedules.sort(key=lambda x: x.schedule_score, reverse=True)

    return schedules


def print_header(title: str):
    """Print formatted header."""
    print("\n" + "=" * 95)
    print(f"  {title}")
    print("=" * 95)


def print_playoff_schedules(schedules: list[PlayoffSchedule], top_n: int = 40):
    """Print playoff schedule rankings."""
    if not schedules:
        print("\nNo schedules available.")
        return

    print(f"\n{'#':<3} {'Player':<22} {'Pos':<4} {'Team':<4} "
          f"{'W14':>5} {'W15':>5} {'W16':>5} {'W17':>5} "
          f"{'Avg':>5} {'Grade':<6} {'Smash':>5}")
    print("-" * 95)

    for i, s in enumerate(schedules[:top_n], 1):
        print(
            f"{i:<3} "
            f"{s.player_name[:21]:<22} "
            f"{s.position:<4} "
            f"{s.team:<4} "
            f"{s.week_14['grade']:>5} "
            f"{s.week_15['grade']:>5} "
            f"{s.week_16['grade']:>5} "
            f"{s.week_17['grade']:>5} "
            f"{s.avg_rank:>5.1f} "
            f"{s.schedule_grade:<6} "
            f"{s.smash_weeks:>5}"
        )


def print_team_playoff_analysis(team_key: str, season: int = 2025):
    """Print playoff analysis for a fantasy team."""
    schedules = get_team_playoff_analysis(team_key, season)
    team_name = "SoltyTears4U" if team_key == "ryan" else "Serving Punt"

    print_header(f"PLAYOFF SCHEDULE: {team_name.upper()}")

    if not schedules:
        print("\nNo roster data available.")
        return

    # Summary
    avg_score = sum(s.schedule_score for s in schedules) / len(schedules)
    total_smash = sum(s.smash_weeks for s in schedules)
    total_avoid = sum(s.avoid_weeks for s in schedules)

    print(f"\nRoster Playoff Score: {avg_score:.1f}/100")
    print(f"Total Smash Weeks: {total_smash} | Avoid Weeks: {total_avoid}")

    # Group by position
    by_pos = {"QB": [], "RB": [], "WR": [], "TE": []}
    for s in schedules:
        if s.position in by_pos:
            by_pos[s.position].append(s)

    for pos in ["QB", "RB", "WR", "TE"]:
        players = by_pos[pos]
        if not players:
            continue

        print(f"\n--- {pos} ---")
        print(f"{'Player':<22} {'W14':>6} {'W15':>6} {'W16':>6} {'W17':>6} {'Grade':<6}")
        print("-" * 55)

        for s in players:
            w14 = f"{s.week_14['opponent']}({s.week_14['grade']})"
            w15 = f"{s.week_15['opponent']}({s.week_15['grade']})"
            w16 = f"{s.week_16['opponent']}({s.week_16['grade']})"
            w17 = f"{s.week_17['opponent']}({s.week_17['grade']})"

            print(
                f"{s.player_name[:21]:<22} "
                f"{w14:>6} "
                f"{w15:>6} "
                f"{w16:>6} "
                f"{w17:>6} "
                f"{s.schedule_grade:<6}"
            )


def print_acquisition_targets(
    position: Optional[str] = None,
    season: int = 2025
):
    """Print players to target for playoffs (not on our teams)."""
    schedules = get_all_playoff_schedules(season, position)

    print_header("PLAYOFF ACQUISITION TARGETS")
    print("\nPlayers with great playoff schedules NOT on your teams:")

    # Filter to non-rostered or free agents
    targets = [s for s in schedules if s.rostered_by is None]

    if not targets:
        print("\nNo targets found.")
        return

    # Show top by position
    by_pos = {"QB": [], "RB": [], "WR": [], "TE": []}
    for s in targets:
        if s.position in by_pos:
            by_pos[s.position].append(s)

    for pos in ["QB", "RB", "WR", "TE"]:
        if position and pos != position:
            continue

        players = by_pos[pos][:10]
        if not players:
            continue

        print(f"\n--- {pos} TARGETS ---")
        print(f"{'Player':<22} {'Team':<4} "
              f"{'W14':>5} {'W15':>5} {'W16':>5} {'W17':>5} {'Grade':<6}")
        print("-" * 60)

        for s in players:
            print(
                f"{s.player_name[:21]:<22} "
                f"{s.team:<4} "
                f"{s.week_14['grade']:>5} "
                f"{s.week_15['grade']:>5} "
                f"{s.week_16['grade']:>5} "
                f"{s.week_17['grade']:>5} "
                f"{s.schedule_grade:<6}"
            )


def print_players_to_avoid(
    position: Optional[str] = None,
    season: int = 2025
):
    """Print players with tough playoff schedules."""
    schedules = get_all_playoff_schedules(season, position)

    print_header("PLAYERS TO AVOID (Tough Playoff Schedule)")

    # Sort by worst schedule
    worst = sorted(schedules, key=lambda x: x.schedule_score)[:30]

    if not worst:
        print("\nNo data available.")
        return

    print(f"\n{'#':<3} {'Player':<22} {'Pos':<4} {'Team':<4} "
          f"{'W14':>5} {'W15':>5} {'W16':>5} {'W17':>5} {'Grade':<6}")
    print("-" * 75)

    for i, s in enumerate(worst, 1):
        print(
            f"{i:<3} "
            f"{s.player_name[:21]:<22} "
            f"{s.position:<4} "
            f"{s.team:<4} "
            f"{s.week_14['grade']:>5} "
            f"{s.week_15['grade']:>5} "
            f"{s.week_16['grade']:>5} "
            f"{s.week_17['grade']:>5} "
            f"{s.schedule_grade:<6}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Playoff Schedule Optimizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python analysis/playoff_optimizer.py                 # All rankings
  uv run python analysis/playoff_optimizer.py --pos RB        # RB only
  uv run python analysis/playoff_optimizer.py --team ryan     # Ryan's roster
  uv run python analysis/playoff_optimizer.py --targets       # Acquisition targets
  uv run python analysis/playoff_optimizer.py --avoid         # Players to sell
        """
    )
    parser.add_argument("--season", type=int, default=2025, help="Season year")
    parser.add_argument("--pos", "--position", type=str,
                        choices=["QB", "RB", "WR", "TE"],
                        help="Filter by position")
    parser.add_argument("--team", type=str, choices=["ryan", "wife"],
                        help="Analyze fantasy team roster")
    parser.add_argument("--targets", action="store_true",
                        help="Show acquisition targets")
    parser.add_argument("--avoid", action="store_true",
                        help="Show players to avoid/sell")
    parser.add_argument("--top", type=int, default=40,
                        help="Number of players to show")
    args = parser.parse_args()

    if args.team:
        print_team_playoff_analysis(args.team, args.season)
        return

    if args.targets:
        print_acquisition_targets(args.pos, args.season)
        return

    if args.avoid:
        print_players_to_avoid(args.pos, args.season)
        return

    # Default: show best playoff schedules
    print_header("PLAYOFF SCHEDULE RANKINGS (Weeks 14-17)")
    schedules = get_all_playoff_schedules(args.season, args.pos)
    print_playoff_schedules(schedules, args.top)


if __name__ == "__main__":
    main()

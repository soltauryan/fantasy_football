#!/usr/bin/env python3
"""
Bench Optimizer - Fantasy Football Season Management

Analyzes bench decisions:
- Hold vs drop recommendations
- Droppable player identification
- Handcuff value analysis
- Bye week coverage planning

Usage:
    uv run python analysis/bench_optimizer.py --team ryan      # Ryan's bench
    uv run python analysis/bench_optimizer.py --droppable      # Who to drop
    uv run python analysis/bench_optimizer.py --handcuffs      # Handcuff analysis
    uv run python analysis/bench_optimizer.py --byes           # Bye week coverage
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import polars as pl
from dataclasses import dataclass
from typing import Optional

from utils.db import get_connection, read_sqlite_robust
from utils.trades import get_team_trade_values, PlayerTradeValue
from utils.weekly import load_depth_charts

# Team configuration
MY_TEAM_IDS = {
    "ryan": 6,
    "wife": 9,
}

# Roster requirements
ROSTER_NEEDS = {
    "QB": {"starters": 1, "bench": 1},
    "RB": {"starters": 2, "bench": 2},
    "WR": {"starters": 2, "bench": 2},
    "TE": {"starters": 1, "bench": 1},
}


@dataclass
class BenchPlayer:
    """Analysis of a bench player."""
    player_name: str
    position: str
    team: str
    trade_value: float
    tier: str
    recommendation: str  # "HOLD", "DROP", "TRADE", "STASH"
    reasoning: str
    bye_week: Optional[int]
    is_handcuff: bool
    handcuff_to: Optional[str]


def load_team_roster(team_key: str) -> pl.DataFrame:
    """Load roster for a team."""
    conn = get_connection()
    team_id = MY_TEAM_IDS.get(team_key)

    if not team_id:
        return pl.DataFrame()

    roster = read_sqlite_robust(f"""
        SELECT
            player_name, position, pro_team as team,
            lineup_slot, injury_status,
            projected_total_points, total_points
        FROM bronze_espn_rosters
        WHERE team_id = {team_id}
        AND position IN ('QB', 'RB', 'WR', 'TE')
    """, conn)
    conn.close()
    return roster


def load_bye_weeks() -> dict[str, int]:
    """Load bye weeks for each NFL team."""
    conn = get_connection()

    # Get bye weeks from schedule (team with no game)
    schedule = read_sqlite_robust("""
        SELECT week, home_team, away_team
        FROM bronze_schedules
        WHERE season = 2025 AND game_type = 'REG'
    """, conn)
    conn.close()

    if schedule.is_empty():
        return {}

    # All NFL teams
    all_teams = set()
    for row in schedule.iter_rows(named=True):
        all_teams.add(row["home_team"])
        all_teams.add(row["away_team"])

    # Find bye week for each team
    bye_weeks = {}
    for week in range(1, 19):
        week_games = schedule.filter(pl.col("week") == week)
        teams_playing = set()
        for row in week_games.iter_rows(named=True):
            teams_playing.add(row["home_team"])
            teams_playing.add(row["away_team"])

        for team in all_teams:
            if team not in teams_playing and team not in bye_weeks:
                bye_weeks[team] = week

    return bye_weeks


def identify_handcuffs(roster: pl.DataFrame, season: int = 2024) -> dict[str, str]:
    """Identify handcuff relationships on roster."""
    depth = load_depth_charts(season)

    if depth.is_empty() or roster.is_empty():
        return {}

    handcuffs = {}

    # Get RBs on roster
    rbs = roster.filter(pl.col("position") == "RB")

    for row in rbs.iter_rows(named=True):
        player_name = row["player_name"]
        team = row["team"]

        if not team:
            continue

        # Check depth chart for this team
        team_depth = depth.filter(
            (pl.col("team") == team) &
            (pl.col("position") == "RB")
        ).sort("pos_rank")

        if team_depth.is_empty():
            continue

        # Get the starter (rank 1)
        starter = None
        for d_row in team_depth.iter_rows(named=True):
            if d_row["pos_rank"] == 1:
                starter = d_row["full_name"]
                break

        if starter and starter != player_name:
            # This player might be a handcuff
            handcuffs[player_name] = starter

    return handcuffs


def analyze_bench_player(
    player_name: str,
    position: str,
    team: str,
    lineup_slot: str,
    trade_value: float,
    tier: str,
    bye_weeks: dict[str, int],
    handcuffs: dict[str, str],
    pos_counts: dict[str, int]
) -> BenchPlayer:
    """Analyze a single bench player."""

    bye_week = bye_weeks.get(team) if team else None
    is_handcuff = player_name in handcuffs
    handcuff_to = handcuffs.get(player_name)

    # Determine recommendation
    recommendation = "HOLD"
    reasoning = ""

    if tier == "Droppable":
        if is_handcuff:
            recommendation = "STASH"
            reasoning = f"Low value but handcuff to {handcuff_to}"
        else:
            recommendation = "DROP"
            reasoning = "Low trade value, not a handcuff"
    elif tier == "Bench":
        needs = ROSTER_NEEDS.get(position, {})
        min_needed = needs.get("starters", 1) + needs.get("bench", 1)

        if pos_counts.get(position, 0) > min_needed:
            recommendation = "TRADE"
            reasoning = f"Excess depth at {position}"
        elif is_handcuff:
            recommendation = "HOLD"
            reasoning = f"Valuable handcuff to {handcuff_to}"
        else:
            recommendation = "HOLD"
            reasoning = "Roster depth"
    elif tier == "Flex":
        recommendation = "HOLD"
        reasoning = "Flex-worthy starter"
    else:
        recommendation = "HOLD"
        reasoning = "Valuable asset"

    return BenchPlayer(
        player_name=player_name,
        position=position,
        team=team or "",
        trade_value=trade_value,
        tier=tier,
        recommendation=recommendation,
        reasoning=reasoning,
        bye_week=bye_week,
        is_handcuff=is_handcuff,
        handcuff_to=handcuff_to,
    )


def get_bench_analysis(team_key: str) -> list[BenchPlayer]:
    """Get full bench analysis for a team."""
    roster = load_team_roster(team_key)
    trade_values = get_team_trade_values(team_key)
    bye_weeks = load_bye_weeks()
    handcuffs = identify_handcuffs(roster)

    if roster.is_empty():
        return []

    # Count by position
    pos_counts = {}
    for row in roster.iter_rows(named=True):
        pos = row["position"]
        pos_counts[pos] = pos_counts.get(pos, 0) + 1

    # Build value lookup
    value_lookup = {v.player_name: v for v in trade_values}

    analysis = []

    for row in roster.iter_rows(named=True):
        player_name = row["player_name"]
        position = row["position"]
        team = row.get("team")
        lineup_slot = row.get("lineup_slot", "BE")

        # Get trade value
        tv = value_lookup.get(player_name)
        trade_value = tv.final_value if tv else 0
        tier = tv.tier if tv else "Droppable"

        bench_player = analyze_bench_player(
            player_name, position, team, lineup_slot,
            trade_value, tier, bye_weeks, handcuffs, pos_counts
        )
        analysis.append(bench_player)

    # Sort by trade value
    analysis.sort(key=lambda x: x.trade_value, reverse=True)

    return analysis


def get_droppable_players(team_key: str = None) -> list[BenchPlayer]:
    """Get droppable players across one or both teams."""
    teams = [team_key] if team_key else ["ryan", "wife"]
    droppable = []

    for tk in teams:
        analysis = get_bench_analysis(tk)
        for p in analysis:
            if p.recommendation == "DROP":
                droppable.append(p)

    return droppable


def get_bye_week_analysis(team_key: str, target_week: int = None) -> dict:
    """Analyze bye week coverage for a team."""
    roster = load_team_roster(team_key)
    bye_weeks = load_bye_weeks()

    if roster.is_empty():
        return {}

    # Group players by bye week
    by_bye = {}
    for row in roster.iter_rows(named=True):
        team = row.get("team")
        bye = bye_weeks.get(team)
        if bye:
            if bye not in by_bye:
                by_bye[bye] = {"QB": [], "RB": [], "WR": [], "TE": []}
            pos = row["position"]
            if pos in by_bye[bye]:
                by_bye[bye][pos].append(row["player_name"])

    # Identify problem weeks
    problem_weeks = []
    for week, players in by_bye.items():
        issues = []
        if len(players["QB"]) >= 2:
            issues.append("Both QBs on bye")
        if len(players["RB"]) >= 3:
            issues.append(f"{len(players['RB'])} RBs on bye")
        if len(players["WR"]) >= 3:
            issues.append(f"{len(players['WR'])} WRs on bye")
        if len(players["TE"]) >= 2:
            issues.append("Both TEs on bye")

        if issues:
            problem_weeks.append({
                "week": week,
                "issues": issues,
                "players": players
            })

    return {
        "by_bye": by_bye,
        "problem_weeks": problem_weeks,
    }


def print_header(title: str):
    """Print formatted header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_bench_analysis(team_key: str):
    """Print full bench analysis for a team."""
    analysis = get_bench_analysis(team_key)
    team_name = "SoltyTears4U" if team_key == "ryan" else "Serving Punt"

    print_header(f"BENCH ANALYSIS: {team_name.upper()}")

    if not analysis:
        print("\nNo roster data available.")
        return

    # Summary
    holds = sum(1 for p in analysis if p.recommendation == "HOLD")
    drops = sum(1 for p in analysis if p.recommendation == "DROP")
    trades = sum(1 for p in analysis if p.recommendation == "TRADE")
    stashes = sum(1 for p in analysis if p.recommendation == "STASH")

    print(f"\nSummary: {holds} HOLD | {trades} TRADE | {stashes} STASH | {drops} DROP")

    print(f"\n{'Player':<22} {'Pos':<4} {'Value':>6} {'Tier':<10} "
          f"{'Rec':<6} {'Bye':>4} {'Reasoning'}")
    print("-" * 85)

    for p in analysis:
        bye_str = str(p.bye_week) if p.bye_week else "-"
        rec_color = {
            "HOLD": "HOLD",
            "DROP": "DROP",
            "TRADE": "TRADE",
            "STASH": "STASH",
        }

        print(
            f"{p.player_name[:21]:<22} "
            f"{p.position:<4} "
            f"{p.trade_value:>6.1f} "
            f"{p.tier:<10} "
            f"{rec_color.get(p.recommendation, p.recommendation):<6} "
            f"{bye_str:>4} "
            f"{p.reasoning[:25]}"
        )


def print_droppable_players(team_key: str = None):
    """Print droppable players."""
    droppable = get_droppable_players(team_key)

    print_header("DROPPABLE PLAYERS")

    if not droppable:
        print("\nNo clearly droppable players found.")
        return

    print(f"\n{'Player':<22} {'Pos':<4} {'Team':<4} {'Value':>6} {'Reasoning'}")
    print("-" * 60)

    for p in droppable:
        print(
            f"{p.player_name[:21]:<22} "
            f"{p.position:<4} "
            f"{p.team:<4} "
            f"{p.trade_value:>6.1f} "
            f"{p.reasoning}"
        )


def print_handcuff_analysis(team_key: str = None):
    """Print handcuff analysis."""
    teams = [team_key] if team_key else ["ryan", "wife"]

    print_header("HANDCUFF ANALYSIS")

    for tk in teams:
        analysis = get_bench_analysis(tk)
        team_name = "SoltyTears4U" if tk == "ryan" else "Serving Punt"

        handcuffs = [p for p in analysis if p.is_handcuff]

        print(f"\n--- {team_name} ---")

        if not handcuffs:
            print("No handcuffs on roster.")
            continue

        print(f"{'Handcuff':<22} {'Starter':<22} {'Value':>6}")
        print("-" * 55)

        for p in handcuffs:
            print(
                f"{p.player_name[:21]:<22} "
                f"{p.handcuff_to[:21]:<22} "
                f"{p.trade_value:>6.1f}"
            )


def print_bye_analysis(team_key: str):
    """Print bye week analysis."""
    bye_data = get_bye_week_analysis(team_key)
    team_name = "SoltyTears4U" if team_key == "ryan" else "Serving Punt"

    print_header(f"BYE WEEK ANALYSIS: {team_name.upper()}")

    if not bye_data:
        print("\nNo roster data available.")
        return

    # Problem weeks
    problems = bye_data.get("problem_weeks", [])
    if problems:
        print("\n⚠ PROBLEM WEEKS:")
        for pw in problems:
            print(f"\n  Week {pw['week']}:")
            for issue in pw["issues"]:
                print(f"    - {issue}")
    else:
        print("\n✓ No major bye week conflicts.")

    # Full breakdown
    print("\nBye Week Breakdown:")
    by_bye = bye_data.get("by_bye", {})

    for week in sorted(by_bye.keys()):
        players = by_bye[week]
        all_players = []
        for pos in ["QB", "RB", "WR", "TE"]:
            for p in players[pos]:
                all_players.append(f"{p} ({pos})")

        if all_players:
            print(f"  Week {week}: {', '.join(all_players)}")


def main():
    parser = argparse.ArgumentParser(
        description="Bench Optimizer - Fantasy Football",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python analysis/bench_optimizer.py --team ryan    # Full analysis
  uv run python analysis/bench_optimizer.py --droppable    # Droppable players
  uv run python analysis/bench_optimizer.py --handcuffs    # Handcuff analysis
  uv run python analysis/bench_optimizer.py --byes ryan    # Bye week coverage
        """
    )
    parser.add_argument("--team", type=str, choices=["ryan", "wife"],
                        help="Team to analyze")
    parser.add_argument("--droppable", action="store_true",
                        help="Show droppable players")
    parser.add_argument("--handcuffs", action="store_true",
                        help="Show handcuff analysis")
    parser.add_argument("--byes", type=str, choices=["ryan", "wife"],
                        help="Show bye week analysis for team")
    args = parser.parse_args()

    if args.byes:
        print_bye_analysis(args.byes)
        return

    if args.handcuffs:
        print_handcuff_analysis(args.team)
        return

    if args.droppable:
        print_droppable_players(args.team)
        return

    if args.team:
        print_bench_analysis(args.team)
        return

    # Default: show both teams
    print_bench_analysis("ryan")
    print_bench_analysis("wife")


if __name__ == "__main__":
    main()

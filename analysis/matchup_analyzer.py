#!/usr/bin/env python3
"""
Matchup Analyzer - Fantasy Football Weekly Analysis

Analyzes defensive matchups to identify:
- Soft defenses to target
- Schedule difficulty by team
- Streaming candidates
- Weekly matchup grades

Usage:
    uv run python analysis/matchup_analyzer.py                    # Show all rankings
    uv run python analysis/matchup_analyzer.py --week 1           # Week 1 matchups
    uv run python analysis/matchup_analyzer.py --pos RB           # RB defense rankings
    uv run python analysis/matchup_analyzer.py --team KC --pos RB # KC RB schedule
    uv run python analysis/matchup_analyzer.py --streamers QB 1   # QB streamers week 1
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
from utils.matchups import (
    calculate_defense_rankings,
    get_soft_matchups,
    get_team_schedule_difficulty,
    get_streaming_candidates,
    get_matchup_grade,
    print_defense_rankings,
)


def print_header(title: str):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_soft_matchups(week: int, season: int = 2025):
    """Print soft matchups for a week."""
    print_header(f"SOFT MATCHUPS - WEEK {week}")

    matchups = get_soft_matchups(week, season, top_n=20)

    if not matchups:
        print("\nNo matchup data available.")
        return

    # Group by position
    by_pos = {"QB": [], "RB": [], "WR": [], "TE": []}
    for m in matchups:
        pos = m["position"]
        if pos in by_pos and len(by_pos[pos]) < 5:
            by_pos[pos].append(m)

    for pos in ["QB", "RB", "WR", "TE"]:
        print(f"\n--- {pos} ---")
        print(f"{'Team':<5} {'vs':<5} {'Rank':>5} {'Pts Allowed':>11} {'Grade':<6}")
        print("-" * 35)

        for m in by_pos[pos]:
            grade = get_matchup_grade(m["def_rank"])
            print(
                f"{m['team']:<5} "
                f"{m['opponent']:<5} "
                f"{m['def_rank']:>5} "
                f"{m['pts_allowed']:>11.1f} "
                f"{grade:<6}"
            )


def print_schedule_difficulty(team: str, position: str, season: int = 2025):
    """Print schedule difficulty for a team at a position."""
    print_header(f"{team} {position} SCHEDULE DIFFICULTY")

    sched = get_team_schedule_difficulty(team, season, position)

    if sched.is_empty():
        print("\nNo schedule data available.")
        return

    # Calculate average difficulty
    avg_rank = sched["def_rank"].mean()
    avg_grade = get_matchup_grade(int(avg_rank))

    print(f"\nOverall Schedule Grade: {avg_grade} (avg rank: {avg_rank:.1f})")
    print(f"\n{'Week':<5} {'Opp':<5} {'H/A':<5} {'Rank':>5} {'Pts Allowed':>11} {'Grade':<6}")
    print("-" * 45)

    for row in sched.iter_rows(named=True):
        print(
            f"{row['week']:<5} "
            f"{row['opponent']:<5} "
            f"{'@' if row['home_away'] == 'away' else '':<5} "
            f"{row['def_rank']:>5} "
            f"{row['pts_allowed']:>11.1f} "
            f"{row['matchup_grade']:<6}"
        )

    # Highlight best/worst weeks
    best = sched.sort("def_rank").head(3)
    worst = sched.sort("def_rank", descending=True).head(3)

    print(f"\nBest weeks: ", end="")
    print(", ".join(f"W{r['week']} vs {r['opponent']}" for r in best.iter_rows(named=True)))

    print(f"Worst weeks: ", end="")
    print(", ".join(f"W{r['week']} vs {r['opponent']}" for r in worst.iter_rows(named=True)))


def print_streamers(position: str, week: int, season: int = 2025):
    """Print streaming candidates for a position."""
    print_header(f"{position} STREAMING CANDIDATES - WEEK {week}")

    streamers = get_streaming_candidates(week, position, season, top_n=15)

    if not streamers:
        print("\nNo streaming candidates found.")
        return

    print(f"\n{'Player':<22} {'Team':<5} {'vs':<5} {'Grade':<6} {'Own%':>6} {'Avg Pts':>8}")
    print("-" * 60)

    for s in streamers:
        print(
            f"{s['player'][:21]:<22} "
            f"{s['team']:<5} "
            f"{s['opponent']:<5} "
            f"{s['matchup_grade']:<6} "
            f"{s['pct_owned']:>5.0f}% "
            f"{s['avg_pts']:>8.1f}"
        )


def print_all_rankings(season: int = 2025):
    """Print all defense rankings by position."""
    print_header("DEFENSE RANKINGS BY POSITION")
    print("\n(Lower rank = worse defense = better fantasy matchup)")

    print_defense_rankings(season)


def main():
    parser = argparse.ArgumentParser(
        description="Matchup Analyzer - Find soft defenses and streaming plays",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python analysis/matchup_analyzer.py                     # All defense rankings
  uv run python analysis/matchup_analyzer.py --week 1            # Week 1 soft matchups
  uv run python analysis/matchup_analyzer.py --pos RB            # RB defense rankings only
  uv run python analysis/matchup_analyzer.py --team SF --pos WR  # SF WR schedule
  uv run python analysis/matchup_analyzer.py --streamers QB 5    # QB streamers week 5
        """
    )
    parser.add_argument("--season", type=int, default=2025, help="Season year")
    parser.add_argument("--week", type=int, help="Week for matchup analysis")
    parser.add_argument("--pos", "--position", type=str,
                        choices=["QB", "RB", "WR", "TE"],
                        help="Filter by position")
    parser.add_argument("--team", type=str,
                        help="Show schedule difficulty for a team (e.g., KC)")
    parser.add_argument("--streamers", nargs=2, metavar=("POS", "WEEK"),
                        help="Show streaming candidates (e.g., --streamers QB 1)")
    args = parser.parse_args()

    # Handle streamers mode
    if args.streamers:
        pos, week = args.streamers
        print_streamers(pos.upper(), int(week), args.season)
        return

    # Handle team schedule mode
    if args.team:
        pos = args.pos or "RB"  # Default to RB
        print_schedule_difficulty(args.team.upper(), pos, args.season)
        return

    # Handle week matchups mode
    if args.week:
        print_soft_matchups(args.week, args.season)
        return

    # Default: show rankings
    if args.pos:
        print_defense_rankings(args.season, args.pos)
    else:
        print_all_rankings(args.season)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Injury Impact Analyzer - Fantasy Football Weekly Analysis

Analyzes injuries and their impact on backup player value:
- Identifies injured starters and their backups
- Projects snap count increases for backups
- Estimates target share redistribution
- Tracks rostered vs free agent backups
- Two-team awareness (ryan/wife)

Usage:
    uv run python analysis/injury_impact.py              # Full injury report
    uv run python analysis/injury_impact.py --team ryan  # Team-specific needs
    uv run python analysis/injury_impact.py --top 10     # Top N opportunities
    uv run python analysis/injury_impact.py --position RB # Filter by position
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import polars as pl
from utils.db import get_connection, read_sqlite_robust
from utils.weekly import (
    analyze_injury_impact_espn,
    get_team_target_distribution,
    load_espn_injuries,
    load_depth_charts,
    get_snap_trends,
)

# Team configuration
MY_TEAM_IDS = {
    "ryan": 6,
    "wife": 9,
}


def get_team_needs() -> dict[str, dict[str, int]]:
    """Get positional needs for both teams."""
    conn = get_connection()

    targets = {"QB": 2, "RB": 4, "WR": 4, "TE": 2}
    needs = {}

    for team_key, team_id in MY_TEAM_IDS.items():
        roster = read_sqlite_robust(f"""
            SELECT position, COUNT(*) as count
            FROM bronze_espn_rosters
            WHERE team_id = {team_id}
            AND position IN ('QB', 'RB', 'WR', 'TE')
            GROUP BY position
        """, conn)

        team_needs = {}
        for pos, target in targets.items():
            current = 0
            pos_count = roster.filter(pl.col("position") == pos)
            if not pos_count.is_empty():
                current = pos_count["count"][0]
            remaining = max(0, target - current)
            if remaining > 0:
                team_needs[pos] = remaining

        needs[team_key] = team_needs

    conn.close()
    return needs


def print_header(title: str):
    """Print a formatted header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_injury_summary(opportunities: list[dict]):
    """Print high-level injury summary."""
    if not opportunities:
        print("\nNo significant injuries found.")
        return

    # Group by team
    by_team = {}
    for opp in opportunities:
        team = opp["team"]
        if team not in by_team:
            by_team[team] = []
        by_team[team].append(opp)

    print(f"\n{'Team':<5} {'Injured Players':<40} {'Positions'}")
    print("-" * 70)

    for team, opps in sorted(by_team.items()):
        # Get unique injured players
        injured = list(set(o["injured_player"] for o in opps))
        positions = list(set(o["position"] for o in opps))
        print(f"{team:<5} {', '.join(injured[:3]):<40} {', '.join(positions)}")


def print_detailed_report(opportunities: list[dict], top_n: int = 20):
    """Print detailed opportunity report."""
    if not opportunities:
        print("\nNo opportunities found.")
        return

    # Only show unique backup players (first entry for each)
    seen_backups = set()
    filtered = []
    for opp in opportunities:
        backup = opp["backup_player"]
        if backup not in seen_backups:
            seen_backups.add(backup)
            filtered.append(opp)

    print(f"\n{'#':<3} {'Backup':<20} {'Pos':<4} {'Team':<4} "
          f"{'Injured':<18} {'Status':<8} {'Score':>6} {'Snap+':>6} {'Rostered'}")
    print("-" * 95)

    for i, opp in enumerate(filtered[:top_n], 1):
        rostered = opp["rostered_by"] or "FREE"
        rostered_flag = f"[{rostered.upper()}]" if rostered != "FREE" else "free agent"

        print(
            f"{i:<3} "
            f"{opp['backup_player'][:19]:<20} "
            f"{opp['position']:<4} "
            f"{opp['team']:<4} "
            f"{opp['injured_player'][:17]:<18} "
            f"{opp['injury_status'][:7]:<8} "
            f"{opp['opportunity_score']:>6.1f} "
            f"+{opp['snap_increase']:>4.0f}% "
            f"{rostered_flag}"
        )


def print_projection_details(opportunities: list[dict], top_n: int = 10):
    """Print detailed snap/target projections."""
    print_header("SNAP & TARGET PROJECTIONS")

    if not opportunities:
        print("\nNo projection data available.")
        return

    # Get unique backups only
    seen = set()
    unique = []
    for opp in opportunities:
        if opp["backup_player"] not in seen:
            seen.add(opp["backup_player"])
            unique.append(opp)

    print(f"\n{'Player':<22} {'Pos':<4} "
          f"{'Curr Snap%':>10} {'Proj Snap%':>11} "
          f"{'Tgt Increase':>12} {'Miss Weeks':<10}")
    print("-" * 80)

    for opp in unique[:top_n]:
        tgt_str = f"+{opp['projected_target_increase']:.1f}" if opp["projected_target_increase"] > 0 else "-"
        print(
            f"{opp['backup_player'][:21]:<22} "
            f"{opp['position']:<4} "
            f"{opp['backup_current_snap_pct']:>9.0f}% "
            f"{opp['projected_snap_pct']:>10.0f}% "
            f"{tgt_str:>12} "
            f"{opp['miss_weeks']:<10}"
        )


def print_team_specific(opportunities: list[dict], team_key: str, needs: dict):
    """Print team-specific injury opportunities."""
    team_needs = needs.get(team_key, {})
    team_name = "SoltyTears4U" if team_key == "ryan" else "Serving Punt"

    print_header(f"INJURY OPPORTUNITIES FOR {team_name.upper()}")

    if team_needs:
        needs_str = ", ".join(f"{pos}: need {n}" for pos, n in team_needs.items())
        print(f"\nTeam needs: {needs_str}")
    else:
        print("\nNo positional needs.")

    # Filter to free agents and boost by need
    free_opps = [o for o in opportunities if o["rostered_by"] is None]

    if not free_opps:
        print("\nNo free agent opportunities found.")
        return

    # Score by team need
    scored = []
    for opp in free_opps:
        pos = opp["position"]
        base_score = opp["opportunity_score"]
        need_boost = team_needs.get(pos, 0) * 15
        total_score = base_score + need_boost

        scored.append({
            **opp,
            "total_score": total_score,
            "need_boost": need_boost,
        })

    scored.sort(key=lambda x: x["total_score"], reverse=True)

    # Get unique backups
    seen = set()
    unique = []
    for opp in scored:
        if opp["backup_player"] not in seen:
            seen.add(opp["backup_player"])
            unique.append(opp)

    print(f"\n{'#':<3} {'Player':<20} {'Pos':<4} {'Team':<4} "
          f"{'Score':>6} {'Need+':>6} {'Replaces'}")
    print("-" * 70)

    for i, opp in enumerate(unique[:15], 1):
        need_str = f"+{opp['need_boost']:.0f}" if opp["need_boost"] > 0 else ""
        print(
            f"{i:<3} "
            f"{opp['backup_player'][:19]:<20} "
            f"{opp['position']:<4} "
            f"{opp['team']:<4} "
            f"{opp['total_score']:>6.1f} "
            f"{need_str:>6} "
            f"{opp['injured_player'][:20]}"
        )


def print_emerging_players(season: int = 2025):
    """Print players with increasing snap trends (pre-injury value)."""
    print_header("EMERGING PLAYERS (Snap Trend +15%)")

    trends = get_snap_trends(season, min_weeks=3, min_trend=15.0)

    if trends.is_empty():
        print("\nNo emerging players found.")
        return

    print(f"\n{'Player':<25} {'Pos':<4} {'Team':<4} "
          f"{'Early Snap%':>11} {'Recent%':>8} {'Trend':>7}")
    print("-" * 65)

    for row in trends.head(15).iter_rows(named=True):
        print(
            f"{row['full_name'][:24]:<25} "
            f"{row['position']:<4} "
            f"{row['team']:<4} "
            f"{row['early_snap_pct']:>10.0f}% "
            f"{row['recent_snap_pct']:>7.0f}% "
            f"+{row['snap_trend']:>5.0f}%"
        )


def print_target_cascade(team: str, season: int = 2025):
    """Show target distribution for a team (to see cascade potential)."""
    print(f"\n--- {team} Target Distribution ---")

    dist = get_team_target_distribution(team, season)

    if dist.is_empty():
        print("No target data available.")
        return

    print(f"{'Player':<22} {'Pos':<4} {'Targets':>8} {'Share':>7} {'Avg Pts':>8}")
    print("-" * 55)

    for row in dist.head(8).iter_rows(named=True):
        share = row.get("target_share", 0)
        print(
            f"{row['full_name'][:21]:<22} "
            f"{row['position']:<4} "
            f"{row['total_targets']:>8} "
            f"{share:>6.1f}% "
            f"{row['avg_pts']:>8.1f}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Injury Impact Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python analysis/injury_impact.py              # Full report
  uv run python analysis/injury_impact.py --team ryan  # Ryan's opportunities
  uv run python analysis/injury_impact.py --pos RB     # RB injuries only
  uv run python analysis/injury_impact.py --emerging   # Players with rising snaps
        """
    )
    parser.add_argument("--season", type=int, default=2025, help="Season year")
    parser.add_argument("--team", type=str, choices=["ryan", "wife"],
                        help="Show team-specific recommendations")
    parser.add_argument("--top", type=int, default=20, help="Top N opportunities")
    parser.add_argument("--pos", "--position", type=str,
                        choices=["QB", "RB", "WR", "TE"],
                        help="Filter by position")
    parser.add_argument("--emerging", action="store_true",
                        help="Show emerging players (snap trend)")
    parser.add_argument("--cascade", type=str, metavar="TEAM",
                        help="Show target cascade for NFL team (e.g., KC)")
    args = parser.parse_args()

    # Load injury opportunities
    opportunities = analyze_injury_impact_espn(args.season)

    # Filter by position if specified
    if args.pos:
        opportunities = [o for o in opportunities if o["position"] == args.pos]

    # Get team needs
    needs = get_team_needs()

    # Print reports based on args
    if args.cascade:
        print_target_cascade(args.cascade.upper(), args.season)
        return

    if args.emerging:
        print_emerging_players(args.season)
        return

    # Main injury report
    print_header("INJURY IMPACT ANALYZER")
    print(f"Season: {args.season}")

    # Summary
    print_injury_summary(opportunities)

    # Detailed opportunities
    print_header("TOP BACKUP OPPORTUNITIES")
    print_detailed_report(opportunities, args.top)

    # Projections
    print_projection_details(opportunities, 10)

    # Team-specific if requested
    if args.team:
        print_team_specific(opportunities, args.team, needs)
    else:
        # Show both teams
        print_team_specific(opportunities, "ryan", needs)
        print_team_specific(opportunities, "wife", needs)

    print("\n")


if __name__ == "__main__":
    main()

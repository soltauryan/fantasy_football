#!/usr/bin/env python3
"""
Waiver Wire Ranker - Fantasy Football Weekly Analysis

Ranks waiver wire pickups based on:
- Injury impact (backup value when starter is out)
- Snap count trends (emerging players)
- Target share trends
- Matchup opportunities
- Two-team needs analysis
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import polars as pl
from utils.db import get_connection, read_sqlite_robust
from utils.weekly import (
    load_free_agents,
    analyze_injury_impact,
    analyze_injury_impact_espn,
    get_snap_trends,
    get_target_share_trends,
    load_weekly_performance,
)
from utils.matchups import (
    calculate_defense_rankings,
    load_schedule,
    get_opponent_for_game,
    get_matchup_grade,
)

# Team configuration
MY_TEAM_IDS = {
    "ryan": 6,
    "wife": 9,
}


def load_team_rosters() -> dict[str, pl.DataFrame]:
    """Load current rosters for both teams."""
    conn = get_connection()

    rosters = {}
    for team_key, team_id in MY_TEAM_IDS.items():
        df = read_sqlite_robust(f"""
            SELECT player_name, position, pro_team as team
            FROM bronze_espn_rosters
            WHERE team_id = {team_id}
        """, conn)
        rosters[team_key] = df

    conn.close()
    return rosters


def get_positional_needs(roster: pl.DataFrame) -> dict[str, int]:
    """Calculate positional needs for a roster."""
    targets = {"QB": 2, "RB": 4, "WR": 4, "TE": 2}
    needs = {}

    if roster.is_empty():
        return targets

    counts = roster.group_by("position").len()

    for pos, target in targets.items():
        current = 0
        pos_count = counts.filter(pl.col("position") == pos)
        if not pos_count.is_empty():
            current = pos_count["len"][0]
        remaining = max(0, target - current)
        if remaining > 0:
            needs[pos] = remaining

    return needs


def rank_waiver_pickups(
    season: int = 2025,
    week: int = None,
    top_n: int = 20
) -> pl.DataFrame:
    """
    Rank waiver wire pickups combining multiple factors.

    Returns DataFrame with ranked pickups and reasoning.
    """
    # Load data
    free_agents = load_free_agents()

    # Use ESPN injury data for 2025+ (nflreadpy returns 404)
    if season >= 2025:
        injury_opps = analyze_injury_impact_espn(season)
    else:
        injury_opps = analyze_injury_impact(season, week)

    snap_trends = get_snap_trends(season)
    target_trends = get_target_share_trends(season)
    weekly = load_weekly_performance(season)

    # Load matchup data
    def_rankings = calculate_defense_rankings(season)
    schedule = load_schedule(season, week) if week else load_schedule(season)

    # Build rankings
    rankings = []

    # Score free agents
    for row in free_agents.iter_rows(named=True):
        player_name = row["player_name"]
        position = row["position"]
        team = row["team"]
        pct_owned = row.get("percent_owned", 0) or 0
        projected = row.get("projected_total_points", 0) or 0

        score = 0
        reasons = []
        matchup_grade = None

        # Base score from projected points (normalized)
        score += projected / 10

        # Bonus for low ownership (hidden gems)
        if pct_owned < 30:
            score += 10
            reasons.append(f"Low owned ({pct_owned:.0f}%)")

        # Check if player is a backup benefiting from injury
        for opp in injury_opps:
            backup_name = opp.get("backup_player", "")
            if backup_name == player_name or player_name in backup_name:
                injury_bonus = opp.get("opportunity_score", 0)
                score += injury_bonus
                injured = opp.get("injured_player", "?")
                status = opp.get("injury_status", opp.get("status", "?"))
                reasons.append(f"Backup to {injured} ({status})")
                break

        # Check matchup quality for this week
        if week and team and position in ["QB", "RB", "WR", "TE"]:
            opponent = get_opponent_for_game(team, week, schedule)
            if opponent and not def_rankings.is_empty():
                def_rank = def_rankings.filter(
                    (pl.col("defense") == opponent) &
                    (pl.col("position") == position)
                )
                if not def_rank.is_empty():
                    rank = def_rank["rank"][0]
                    matchup_grade = get_matchup_grade(rank)

                    # Boost for soft matchups (rank <= 10)
                    if rank <= 5:
                        score += 15
                        reasons.append(f"Smash matchup vs {opponent} ({matchup_grade})")
                    elif rank <= 10:
                        score += 10
                        reasons.append(f"Great matchup vs {opponent} ({matchup_grade})")
                    elif rank <= 15:
                        score += 5
                        reasons.append(f"Good matchup vs {opponent} ({matchup_grade})")
                    elif rank >= 28:
                        score -= 5
                        reasons.append(f"Tough matchup vs {opponent} ({matchup_grade})")

        # Check snap trends
        if not snap_trends.is_empty():
            trend_match = snap_trends.filter(
                pl.col("full_name").str.contains(player_name.split()[0])
            )
            if not trend_match.is_empty():
                trend = trend_match["snap_trend"][0]
                if trend > 15:
                    score += trend / 2
                    reasons.append(f"Snap trend +{trend:.0f}%")

        # Check target trends
        if not target_trends.is_empty() and position in ["WR", "TE", "RB"]:
            trend_match = target_trends.filter(
                pl.col("full_name").str.contains(player_name.split()[0])
            )
            if not trend_match.is_empty():
                trend = trend_match["share_trend"][0]
                if trend > 5:
                    score += trend
                    reasons.append(f"Target share +{trend:.1f}%")

        # Recent performance boost
        if not weekly.is_empty():
            recent = weekly.filter(
                pl.col("full_name").str.contains(player_name.split()[0])
            ).sort("week", descending=True).head(3)

            if not recent.is_empty():
                recent_avg = recent["fantasy_points"].mean()
                if recent_avg and recent_avg > 10:
                    score += recent_avg / 2
                    reasons.append(f"Recent avg: {recent_avg:.1f}")

        if not reasons:
            reasons.append("Available depth")

        rankings.append({
            "player_name": player_name,
            "position": position,
            "team": team,
            "pct_owned": pct_owned,
            "projected_pts": projected,
            "matchup_grade": matchup_grade,
            "waiver_score": score,
            "reasons": ", ".join(reasons),
        })

    # Sort and return
    df = pl.DataFrame(rankings).sort("waiver_score", descending=True)
    return df.head(top_n)


def analyze_for_team(
    team_key: str,
    season: int = 2025,
    week: int = None,
    top_n: int = 10
) -> pl.DataFrame:
    """
    Get waiver recommendations specific to a team's needs.
    """
    rosters = load_team_rosters()

    if team_key not in rosters:
        print(f"Unknown team: {team_key}")
        return pl.DataFrame()

    roster = rosters[team_key]
    needs = get_positional_needs(roster)

    # Get overall rankings
    rankings = rank_waiver_pickups(season, week, top_n=50)

    if rankings.is_empty():
        return rankings

    # Boost scores for positions we need
    boosted = []
    for row in rankings.iter_rows(named=True):
        pos = row["position"]
        score = row["waiver_score"]
        reasons = row["reasons"]

        if pos in needs:
            need_count = needs[pos]
            score += 15 * need_count
            reasons = f"NEED {pos}, " + reasons

        boosted.append({
            **row,
            "waiver_score": score,
            "reasons": reasons,
        })

    return pl.DataFrame(boosted).sort("waiver_score", descending=True).head(top_n)


def print_injury_report(season: int = 2025, week: int = None):
    """Print injury impact analysis."""
    opportunities = analyze_injury_impact(season, week)

    print("\n" + "=" * 70)
    print("INJURY IMPACT REPORT")
    print("=" * 70)

    if not opportunities:
        print("No significant injury opportunities found.")
        return

    print(f"{'Injured':<20} {'Status':<12} {'Backup':<20} {'Pos':<4} {'Team':<4} {'Score':>6}")
    print("-" * 70)

    for opp in opportunities[:15]:
        print(
            f"{opp['injured_player'][:19]:<20} "
            f"{opp['status'][:11]:<12} "
            f"{opp['backup_player'][:19]:<20} "
            f"{opp['position']:<4} "
            f"{opp['team']:<4} "
            f"{opp['opportunity_score']:>6.1f}"
        )


def print_waiver_rankings(season: int = 2025, week: int = None):
    """Print overall waiver wire rankings."""
    rankings = rank_waiver_pickups(season, week)

    print("\n" + "=" * 80)
    if week:
        print(f"WAIVER WIRE RANKINGS - WEEK {week}")
    else:
        print("WAIVER WIRE RANKINGS")
    print("=" * 80)

    if rankings.is_empty():
        print("No waiver data available.")
        return

    print(f"{'Rank':<5} {'Player':<22} {'Pos':<4} {'Own%':>6} {'Match':>6} {'Score':>7}  Reasons")
    print("-" * 80)

    for i, row in enumerate(rankings.iter_rows(named=True), 1):
        matchup = row.get("matchup_grade") or "-"
        print(
            f"{i:<5} "
            f"{row['player_name'][:21]:<22} "
            f"{row['position']:<4} "
            f"{row['pct_owned']:>5.0f}% "
            f"{matchup:>6} "
            f"{row['waiver_score']:>7.1f}  "
            f"{row['reasons'][:35]}"
        )


def print_team_recommendations(team_key: str, season: int = 2025, week: int = None):
    """Print waiver recommendations for a specific team."""
    rosters = load_team_rosters()

    if team_key not in rosters:
        print(f"Unknown team: {team_key}")
        return

    roster = rosters[team_key]
    needs = get_positional_needs(roster)
    recs = analyze_for_team(team_key, season, week)

    team_name = "SoltyTears4U" if team_key == "ryan" else "Serving Punt"

    print("\n" + "=" * 70)
    print(f"WAIVER RECOMMENDATIONS: {team_name.upper()}")
    print("=" * 70)

    if needs:
        needs_str = ", ".join(f"{pos}: {n}" for pos, n in needs.items())
        print(f"Current needs: {needs_str}\n")
    else:
        print("No positional needs identified.\n")

    if recs.is_empty():
        print("No recommendations available.")
        return

    print(f"{'Rank':<5} {'Player':<22} {'Pos':<4} {'Match':>6} {'Score':>7}  Reasons")
    print("-" * 80)

    for i, row in enumerate(recs.iter_rows(named=True), 1):
        matchup = row.get("matchup_grade") or "-"
        print(
            f"{i:<5} "
            f"{row['player_name'][:21]:<22} "
            f"{row['position']:<4} "
            f"{matchup:>6} "
            f"{row['waiver_score']:>7.1f}  "
            f"{row['reasons'][:40]}"
        )


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Waiver Wire Ranker")
    parser.add_argument("--season", type=int, default=2025, help="Season year")
    parser.add_argument("--week", type=int, default=None, help="Week number")
    parser.add_argument("--team", type=str, help="Team to analyze (ryan/wife)")
    parser.add_argument("--injuries", action="store_true", help="Show injury report")
    args = parser.parse_args()

    if args.injuries:
        print_injury_report(args.season, args.week)

    if args.team:
        print_team_recommendations(args.team, args.season, args.week)
    else:
        print_waiver_rankings(args.season, args.week)
        print_team_recommendations("ryan", args.season, args.week)
        print_team_recommendations("wife", args.season, args.week)


if __name__ == "__main__":
    main()

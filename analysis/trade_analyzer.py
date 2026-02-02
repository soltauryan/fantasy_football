#!/usr/bin/env python3
"""
Trade Analyzer - Fantasy Football Season Management

Analyzes trade values and finds fair trade opportunities:
- Player trade value rankings
- Trade package comparison (give vs receive)
- Fair trade finder
- Two-team trade coordination

Usage:
    uv run python analysis/trade_analyzer.py                    # Show trade values
    uv run python analysis/trade_analyzer.py --team ryan        # Ryan's roster values
    uv run python analysis/trade_analyzer.py --trade "A" "B"    # Compare A for B
    uv run python analysis/trade_analyzer.py --find "Player"    # Find fair trades for player
    uv run python analysis/trade_analyzer.py --two-team         # Trades between teams
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
from utils.trades import (
    get_all_trade_values,
    get_team_trade_values,
    get_team_positional_needs,
    analyze_trade,
    find_fair_trades,
    find_two_team_trades,
    find_needs_based_trades,
    PlayerTradeValue,
    TradeAnalysis,
)


def print_header(title: str):
    """Print formatted header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_trade_values(values: list[PlayerTradeValue], top_n: int = 50):
    """Print trade value rankings."""
    if not values:
        print("\nNo trade values available.")
        return

    print(f"\n{'#':<4} {'Player':<24} {'Pos':<4} {'Team':<5} {'Age':>4} "
          f"{'Proj':>6} {'Value':>6} {'Tier':<10} {'Roster':<8}")
    print("-" * 85)

    for i, v in enumerate(values[:top_n], 1):
        age_str = str(v.age) if v.age else "-"
        roster = v.rostered_by.upper() if v.rostered_by else "FA"

        print(
            f"{i:<4} "
            f"{v.player_name[:23]:<24} "
            f"{v.position:<4} "
            f"{v.team[:4]:<5} "
            f"{age_str:>4} "
            f"{v.projected_points:>6.0f} "
            f"{v.final_value:>6.1f} "
            f"{v.tier:<10} "
            f"{roster:<8}"
        )


def print_team_values(team_key: str):
    """Print trade values for a specific team."""
    values = get_team_trade_values(team_key)
    team_name = "SoltyTears4U" if team_key == "ryan" else "Serving Punt"

    print_header(f"TRADE VALUES: {team_name.upper()}")

    if not values:
        print("\nNo players found.")
        return

    total_value = sum(v.final_value for v in values)

    # Group by position
    by_pos = {"QB": [], "RB": [], "WR": [], "TE": []}
    for v in values:
        if v.position in by_pos:
            by_pos[v.position].append(v)

    print(f"\nTotal Roster Value: {total_value:.1f}")

    for pos in ["QB", "RB", "WR", "TE"]:
        players = by_pos[pos]
        if not players:
            continue

        pos_total = sum(p.final_value for p in players)
        print(f"\n--- {pos} ({pos_total:.1f} total) ---")
        print(f"{'Player':<24} {'Value':>6} {'Tier':<10} {'Age':>4}")
        print("-" * 48)

        for p in players:
            age_str = str(p.age) if p.age else "-"
            print(
                f"{p.player_name[:23]:<24} "
                f"{p.final_value:>6.1f} "
                f"{p.tier:<10} "
                f"{age_str:>4}"
            )


def print_trade_analysis(analysis: TradeAnalysis):
    """Print trade analysis."""
    print_header("TRADE ANALYSIS")

    # Give side
    print("\n[GIVE]")
    print(f"{'Player':<24} {'Pos':<4} {'Value':>6} {'Tier':<10}")
    print("-" * 48)
    for p in analysis.give_players:
        print(
            f"{p.player_name[:23]:<24} "
            f"{p.position:<4} "
            f"{p.final_value:>6.1f} "
            f"{p.tier:<10}"
        )
    print(f"{'TOTAL':<24} {'':<4} {analysis.give_total:>6.1f}")

    # Receive side
    print("\n[RECEIVE]")
    print(f"{'Player':<24} {'Pos':<4} {'Value':>6} {'Tier':<10}")
    print("-" * 48)
    for p in analysis.receive_players:
        print(
            f"{p.player_name[:23]:<24} "
            f"{p.position:<4} "
            f"{p.final_value:>6.1f} "
            f"{p.tier:<10}"
        )
    print(f"{'TOTAL':<24} {'':<4} {analysis.receive_total:>6.1f}")

    # Verdict
    print("\n" + "=" * 48)
    diff_sign = "+" if analysis.difference >= 0 else ""
    verdict_color = {
        "WIN": "✓ WIN",
        "LOSS": "✗ LOSS",
        "FAIR": "≈ FAIR"
    }
    print(f"Net Value: {diff_sign}{analysis.difference:.1f}")
    print(f"Verdict: {verdict_color.get(analysis.verdict, analysis.verdict)}")

    # Positional impact
    if analysis.positional_impact:
        print("\nPositional Impact:")
        for pos, impact in analysis.positional_impact.items():
            sign = "+" if impact >= 0 else ""
            print(f"  {pos}: {sign}{impact:.1f}")


def print_fair_trades(player_name: str, target_positions: list[str] = None):
    """Print fair trade options for a player."""
    trades = find_fair_trades(player_name, target_positions)

    print_header(f"FAIR TRADES FOR: {player_name.upper()}")

    if not trades:
        print("\nNo fair trades found.")
        return

    # Show the player's value
    player = trades[0][0]
    print(f"\n{player.player_name} ({player.position})")
    print(f"Value: {player.final_value:.1f} | Tier: {player.tier}")
    if player.rostered_by:
        print(f"Rostered by: {player.rostered_by.upper()}")

    print(f"\n{'Target':<24} {'Pos':<4} {'Value':>6} {'Diff':>6} {'Roster':<8}")
    print("-" * 55)

    for _, target in trades:
        diff = target.final_value - player.final_value
        diff_sign = "+" if diff >= 0 else ""
        roster = target.rostered_by.upper() if target.rostered_by else "FA"

        print(
            f"{target.player_name[:23]:<24} "
            f"{target.position:<4} "
            f"{target.final_value:>6.1f} "
            f"{diff_sign}{diff:>5.1f} "
            f"{roster:<8}"
        )


def print_two_team_trades():
    """Print trade suggestions between ryan and wife's teams."""
    trades = find_two_team_trades()

    print_header("TWO-TEAM TRADE SUGGESTIONS")
    print("\nFair trades between SoltyTears4U and Serving Punt:")

    if not trades:
        print("\nNo fair trades found.")
        return

    print(f"\n{'#':<3} {'Ryan Gives':<22} {'Wife Gives':<22} {'Diff':>6} {'Verdict':<6}")
    print("-" * 65)

    for i, t in enumerate(trades, 1):
        ryan_gives = ", ".join(p.player_name[:10] for p in t.give_players)
        wife_gives = ", ".join(p.player_name[:10] for p in t.receive_players)
        diff_sign = "+" if t.difference >= 0 else ""

        print(
            f"{i:<3} "
            f"{ryan_gives[:21]:<22} "
            f"{wife_gives[:21]:<22} "
            f"{diff_sign}{t.difference:>5.1f} "
            f"{t.verdict:<6}"
        )


def print_needs_based_trades():
    """Print trades that address both teams' positional needs."""
    print_header("NEEDS-BASED TRADE SUGGESTIONS")

    # Show each team's needs
    ryan_needs = get_team_positional_needs("ryan")
    wife_needs = get_team_positional_needs("wife")

    print("\nTeam Needs:")
    print(f"  Ryan (SoltyTears4U): {ryan_needs if ryan_needs else 'None'}")
    print(f"  Wife (Serving Punt): {wife_needs if wife_needs else 'None'}")

    trades = find_needs_based_trades()

    if not trades:
        print("\nNo needs-based trades found.")
        return

    # Show mutually beneficial first
    mutual = [t for t in trades if t["mutually_beneficial"]]
    one_sided = [t for t in trades if not t["mutually_beneficial"]]

    if mutual:
        print("\n--- MUTUALLY BENEFICIAL (Both teams get needs) ---")
        print(f"{'Ryan Gives':<22} {'Ryan Gets':<22} {'Diff':>6}")
        print("-" * 55)

        for t in mutual[:10]:
            diff_sign = "+" if t["value_diff"] >= 0 else ""
            print(
                f"{t['ryan_gives'].player_name[:21]:<22} "
                f"{t['ryan_receives'].player_name[:21]:<22} "
                f"{diff_sign}{t['value_diff']:>5.1f}"
            )

    if one_sided:
        print("\n--- ONE-SIDED BENEFIT (One team gets a need) ---")
        print(f"{'Ryan Gives':<22} {'Ryan Gets':<22} {'Who Benefits':<15}")
        print("-" * 65)

        for t in one_sided[:10]:
            benefit = "Ryan" if t["ryan_gets_need"] else "Wife"
            print(
                f"{t['ryan_gives'].player_name[:21]:<22} "
                f"{t['ryan_receives'].player_name[:21]:<22} "
                f"{benefit:<15}"
            )


def interactive_trade():
    """Interactive trade evaluator."""
    print_header("INTERACTIVE TRADE EVALUATOR")
    print("\nEnter player names separated by commas.")
    print("Type 'done' when finished.\n")

    give_names = []
    receive_names = []

    print("Players you GIVE:")
    while True:
        inp = input("  > ").strip()
        if inp.lower() == "done" or not inp:
            break
        give_names.extend([n.strip() for n in inp.split(",")])

    print("\nPlayers you RECEIVE:")
    while True:
        inp = input("  > ").strip()
        if inp.lower() == "done" or not inp:
            break
        receive_names.extend([n.strip() for n in inp.split(",")])

    if give_names or receive_names:
        analysis = analyze_trade(give_names, receive_names)
        if analysis:
            print_trade_analysis(analysis)
        else:
            print("\nCould not analyze trade. Check player names.")


def main():
    parser = argparse.ArgumentParser(
        description="Trade Analyzer - Fantasy Football",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python analysis/trade_analyzer.py                      # All trade values
  uv run python analysis/trade_analyzer.py --team ryan          # Ryan's roster
  uv run python analysis/trade_analyzer.py --trade "A" "B"      # Trade A for B
  uv run python analysis/trade_analyzer.py --find "Josh Allen"  # Fair trades
  uv run python analysis/trade_analyzer.py --two-team           # Cross-team trades
  uv run python analysis/trade_analyzer.py --interactive        # Interactive mode
        """
    )
    parser.add_argument("--team", type=str, choices=["ryan", "wife"],
                        help="Show trade values for a team")
    parser.add_argument("--trade", nargs=2, metavar=("GIVE", "RECEIVE"),
                        help="Analyze a trade (comma-separated names)")
    parser.add_argument("--find", type=str, metavar="PLAYER",
                        help="Find fair trades for a player")
    parser.add_argument("--pos", type=str, nargs="+",
                        choices=["QB", "RB", "WR", "TE"],
                        help="Filter fair trades by position")
    parser.add_argument("--two-team", action="store_true",
                        help="Find trades between ryan and wife")
    parser.add_argument("--needs", action="store_true",
                        help="Find needs-based trades between teams")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Interactive trade evaluator")
    parser.add_argument("--top", type=int, default=50,
                        help="Number of players to show")
    args = parser.parse_args()

    if args.interactive:
        interactive_trade()
        return

    if args.two_team:
        print_two_team_trades()
        return

    if args.needs:
        print_needs_based_trades()
        return

    if args.find:
        print_fair_trades(args.find, args.pos)
        return

    if args.trade:
        give_names = [n.strip() for n in args.trade[0].split(",")]
        receive_names = [n.strip() for n in args.trade[1].split(",")]
        analysis = analyze_trade(give_names, receive_names)
        if analysis:
            print_trade_analysis(analysis)
        else:
            print("Could not analyze trade. Check player names.")
        return

    if args.team:
        print_team_values(args.team)
        return

    # Default: show all trade values
    print_header("TRADE VALUE RANKINGS")
    values = get_all_trade_values()
    print_trade_values(values, args.top)


if __name__ == "__main__":
    main()

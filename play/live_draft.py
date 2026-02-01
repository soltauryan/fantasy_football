#!/usr/bin/env python3
"""
Live Draft Assistant - 2026 Fantasy Football

Interactive CLI for real-time draft guidance with:
- Two-team support (Ryan & Wife)
- Value Over Replacement (VOR) rankings
- Position scarcity alerts
- Best available recommendations
- ESPN live sync (optional)
"""

import cmd
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import polars as pl
from utils.db import get_connection, read_sqlite_robust
from utils.draft import (
    load_projections,
    add_vor_to_projections,
    add_adp_to_projections,
    get_best_available,
    calculate_position_scarcity,
    get_positional_needs,
    recommend_pick,
    analyze_pick_value,
    get_value_picks,
    get_upcoming_targets,
    format_player_display,
    get_pick_value,
    evaluate_trade,
    parse_pick_notation,
    find_equivalent_picks,
    DRAFT_TARGETS,
)

# ESPN Configuration
LEAGUE_ID = 1365062471
SEASON_YEAR = 2026
SWID = "{D2241401-9D06-46E7-84DB-B5878BA69DBD}"
ESPN_S2 = "AEA6s487YT1GrFEFWnpw0MpjPtXYDjNQ%2Fn%2FD%2B9A2GMwtEY5lnL%2B3rrL9bwWJX6oxs8gS4%2B3QBkDBRTCtVxeFc1SWRGYAbSZps5Jp1qFQJqWLO8KzdwVRKrIYVChYEQHqVEydsFdM30uIc3%2BFeGxjcIWln7nOJg8BFIDt0TJAhJpA6a8RgAcx9xZxIraTaia7z%2F1VXAytigfjLKy7ErgnA9SuojVObO5wsx852FuWL4K0PMl9VfIpSaVkVyq9KWtIdAmPANB4EM7boPSO9YhXrx%2FBasgmSITqBgOMzZNeJpKe4E3RX%2F1NpJmg7nmebZLcLpmdnF0Da807qmpHG5Qwfz93"

# Two-team configuration (IDs are stable, names fetched from DB)
MY_TEAM_IDS = {
    "ryan": 6,
    "wife": 9,
}
TEAM_COLORS = {
    "ryan": "\033[94m",   # Blue
    "wife": "\033[95m",   # Magenta
}
RESET_COLOR = "\033[0m"
ALERT_COLOR = "\033[91m"  # Red
SUCCESS_COLOR = "\033[92m"  # Green


def load_team_names() -> dict[str, dict]:
    """Load team names from database based on IDs."""
    conn = get_connection()
    teams_df = read_sqlite_robust(
        "SELECT team_id, team_name FROM bronze_espn_teams", conn
    )
    conn.close()

    teams = {}
    for key, team_id in MY_TEAM_IDS.items():
        row = teams_df.filter(pl.col("team_id") == team_id)
        team_name = row["team_name"][0] if len(row) > 0 else f"Team {team_id}"
        teams[key] = {
            "team_id": team_id,
            "team_name": team_name,
            "color": TEAM_COLORS.get(key, ""),
        }
    return teams


class LiveDraftShell(cmd.Cmd):
    prompt = "(draft) "

    def __init__(self):
        super().__init__()
        print("Loading projections, ADP, and team data...")
        projections = load_projections()
        projections = add_vor_to_projections(projections)
        self.projections = add_adp_to_projections(projections)
        self.teams = load_team_names()  # Fetch team names from DB

        adp_count = self.projections.filter(pl.col("adp").is_not_null()).height
        print(f"Loaded {len(self.projections)} players with VOR calculations.")
        print(f"ADP data available for {adp_count} players.")

        # Set intro after teams are loaded
        self.intro = f"""
{'='*60}
  LIVE DRAFT ASSISTANT - 2026 Fantasy Football
{'='*60}
  Managing: {self.teams['ryan']['team_name']} & {self.teams['wife']['team_name']}

  Commands:
    avail [pos] [n]  - Best available (VOR sorted)
    adp [pos] [n]    - Best available (ADP sorted)
    rec [team]       - Recommendations for ryan/wife
    pick <name>      - Mark player as taken by others
    draft <team> <name> - Draft player to ryan/wife
    teams            - Show both team rosters
    value            - Show value picks (past their ADP)
    targets [n]      - Players likely available at next pick
    scarcity         - Position scarcity report
    trade            - Evaluate a pick trade (interactive)
    pickvalue <pick> - Show value of a draft pick
    search <name>    - Search for a player
    sim <cmd>        - Simulation mode (load/next/auto/reset)
    undo             - Undo last action
    sync             - Sync with ESPN (live draft)
    help             - Show all commands

  Type 'avail' to see best available players.
{'='*60}
"""

        # Track draft state
        self.taken_players: set[str] = set()
        self.rosters = {
            "ryan": [],
            "wife": [],
        }
        self.history = []  # For undo functionality
        self.pick_number = 0

        # Simulation mode (for testing with 2025 draft data)
        self.sim_draft_data = None
        self.sim_index = 0

    # =========================================================================
    # DISPLAY HELPERS
    # =========================================================================

    def _print_header(self, title: str):
        print(f"\n{title}")
        print("-" * 60)

    def _print_player_row(self, row: dict, rank: int = None, show_vor: bool = True):
        name = row.get("player_name", "?")
        pos = row.get("position", "?")
        pts = row.get("proj_total_points_2026", 0) or row.get("proj_pts", 0)
        vor = row.get("vor", 0) or 0
        reason = row.get("reason", "")

        rank_str = f"{rank:>3}." if rank else "   "
        vor_str = f"VOR:{vor:>+6.1f}" if show_vor else ""
        reason_str = f"  [{reason}]" if reason else ""

        print(f"{rank_str} {name:<25} {pos:<4} {pts:>6.1f} pts {vor_str}{reason_str}")

    def _print_player_row_with_adp(self, row: dict, rank: int = None):
        name = row.get("player_name", "?")
        pos = row.get("position", "?")
        pts = row.get("proj_total_points_2026", 0) or row.get("proj_pts", 0)
        vor = row.get("vor", 0) or 0
        adp = row.get("adp")

        rank_str = f"{rank:>3}." if rank else "   "
        adp_str = f"{adp:>8.1f}" if adp else "     N/A"

        print(f"{rank_str} {name:<25} {pos:<4} {pts:>8.1f} {vor:>+10.1f} {adp_str}")

    # =========================================================================
    # CORE COMMANDS
    # =========================================================================

    def do_avail(self, arg):
        """List best available players. Usage: avail [position] [limit]
        Examples: avail, avail RB, avail WR 20"""
        args = arg.upper().split()
        position = None
        limit = 15

        for a in args:
            if a in ["QB", "RB", "WR", "TE", "K", "DST", "D/ST"]:
                position = "D/ST" if a == "DST" else a
            elif a.isdigit():
                limit = int(a)

        best = get_best_available(
            self.projections, self.taken_players, position=position, limit=limit
        )

        pos_label = f" ({position})" if position else ""
        self._print_header(f"BEST AVAILABLE{pos_label} - Top {limit} (by VOR)")
        print(f"{'':>4} {'Player':<25} {'Pos':<4} {'Proj Pts':>8} {'VOR':>10} {'ADP':>8}")
        print("-" * 70)

        for i, row in enumerate(best.iter_rows(named=True), 1):
            self._print_player_row_with_adp(row, rank=i)

    def do_adp(self, arg):
        """List best available by ADP. Usage: adp [position] [limit]
        Examples: adp, adp RB, adp WR 20"""
        args = arg.upper().split()
        position = None
        limit = 15

        for a in args:
            if a in ["QB", "RB", "WR", "TE", "K", "DST", "D/ST"]:
                position = "D/ST" if a == "DST" else a
            elif a.isdigit():
                limit = int(a)

        available = self.projections.filter(
            (~pl.col("player_name").is_in(list(self.taken_players))) &
            (pl.col("adp").is_not_null())
        )

        if position:
            available = available.filter(pl.col("position") == position)

        best = available.sort("adp").head(limit)

        pos_label = f" ({position})" if position else ""
        self._print_header(f"BEST AVAILABLE{pos_label} - Top {limit} (by ADP)")
        print(f"{'':>4} {'Player':<25} {'Pos':<4} {'ADP':>8} {'VOR':>10} {'Proj Pts':>10}")
        print("-" * 75)

        for i, row in enumerate(best.iter_rows(named=True), 1):
            name = row["player_name"]
            pos = row["position"]
            adp = row.get("adp", 0) or 0
            vor = row.get("vor", 0) or 0
            pts = row.get("proj_total_points_2026", 0)
            print(f"{i:>3}. {name:<25} {pos:<4} {adp:>8.1f} {vor:>+10.1f} {pts:>10.1f}")

    def do_rec(self, arg):
        """Get draft recommendations. Usage: rec [ryan|wife]"""
        team_key = arg.lower().strip() if arg else "ryan"
        if team_key not in self.teams:
            print(f"Unknown team. Use: rec ryan OR rec wife")
            return

        team_info = self.teams[team_key]
        roster = self.rosters[team_key]

        recs = recommend_pick(self.projections, self.taken_players, roster)

        self._print_header(f"RECOMMENDATIONS FOR {team_info['team_name'].upper()}")

        # Show current needs
        needs = get_positional_needs(roster)
        if needs:
            needs_str = ", ".join(f"{pos}: {n}" for pos, n in needs.items())
            print(f"Needs: {needs_str}\n")

        print(f"{'':>4} {'Player':<25} {'Pos':<4} {'Proj Pts':>8} {'VOR':>10}  Reason")
        print("-" * 75)

        for i, row in enumerate(recs.head(10).iter_rows(named=True), 1):
            self._print_player_row(row, rank=i)

    def do_pick(self, arg):
        """Mark a player as taken (by another team). Usage: pick <player name>"""
        if not arg:
            print("Usage: pick <player name>")
            return

        player = self._find_player(arg)
        if not player:
            return

        name = player["player_name"]
        if name in self.taken_players:
            print(f"{ALERT_COLOR}Warning: {name} already taken!{RESET_COLOR}")
            return

        self.taken_players.add(name)
        self.pick_number += 1
        self.history.append(("pick", name, None))

        # Analyze pick value
        pick_analysis = analyze_pick_value(name, self.pick_number, self.projections)
        adp_str = f"ADP: {pick_analysis['adp']:.1f}" if pick_analysis['adp'] else "ADP: N/A"
        assessment = pick_analysis['assessment']

        # Color the assessment
        if "VALUE" in assessment:
            assessment = f"{SUCCESS_COLOR}{assessment}{RESET_COLOR}"
        elif "REACH" in assessment:
            assessment = f"{ALERT_COLOR}{assessment}{RESET_COLOR}"

        print(f"Pick #{self.pick_number}: {name} ({player['position']}) - OFF THE BOARD")
        print(f"  {adp_str} | {assessment}")
        self._check_scarcity_alerts()

    def do_draft(self, arg):
        """Draft a player to your team. Usage: draft <ryan|wife> <player name>"""
        args = arg.split(maxsplit=1)
        if len(args) < 2:
            print("Usage: draft <ryan|wife> <player name>")
            return

        team_key = args[0].lower()
        player_search = args[1]

        if team_key not in self.teams:
            print(f"Unknown team '{team_key}'. Use: ryan or wife")
            return

        player = self._find_player(player_search)
        if not player:
            return

        name = player["player_name"]
        if name in self.taken_players:
            print(f"{ALERT_COLOR}Error: {name} is already taken!{RESET_COLOR}")
            return

        # Add to roster and mark as taken
        self.taken_players.add(name)
        self.rosters[team_key].append(player)
        self.pick_number += 1
        self.history.append(("draft", name, team_key))

        team_info = self.teams[team_key]
        color = team_info["color"]

        # Analyze pick value
        pick_analysis = analyze_pick_value(name, self.pick_number, self.projections)
        adp_str = f"ADP: {pick_analysis['adp']:.1f}" if pick_analysis['adp'] else "ADP: N/A"
        assessment = pick_analysis['assessment']

        # Color the assessment
        if "VALUE" in assessment:
            assessment_colored = f"{SUCCESS_COLOR}{assessment}{RESET_COLOR}"
        elif "REACH" in assessment:
            assessment_colored = f"{ALERT_COLOR}{assessment}{RESET_COLOR}"
        else:
            assessment_colored = assessment

        print(f"{color}Pick #{self.pick_number}: {name} ({player['position']}) -> {team_info['team_name']}{RESET_COLOR}")
        print(f"  {adp_str} | {assessment_colored}")

        # Show updated needs
        needs = get_positional_needs(self.rosters[team_key])
        if needs:
            needs_str = ", ".join(f"{pos}: {n}" for pos, n in needs.items())
            print(f"  Remaining needs: {needs_str}")

        self._check_scarcity_alerts()

    def do_teams(self, arg):
        """Show both team rosters side by side."""
        self._print_header("TEAM ROSTERS")

        for team_key, team_info in self.teams.items():
            roster = self.rosters[team_key]
            color = team_info["color"]
            print(f"\n{color}{team_info['team_name']}{RESET_COLOR} ({len(roster)} players)")

            if not roster:
                print("  (empty)")
                continue

            # Group by position
            by_pos = {}
            total_pts = 0
            for p in roster:
                pos = p.get("position", "?")
                if pos not in by_pos:
                    by_pos[pos] = []
                by_pos[pos].append(p)
                total_pts += p.get("proj_total_points_2026", 0)

            for pos in ["QB", "RB", "WR", "TE", "K", "D/ST"]:
                if pos in by_pos:
                    for p in by_pos[pos]:
                        pts = p.get("proj_total_points_2026", 0)
                        print(f"  {pos:<4} {p['player_name']:<25} {pts:>6.1f} pts")

            print(f"  {'':->40}")
            print(f"  Total Projected: {total_pts:.1f} pts")

            # Show needs
            needs = get_positional_needs(roster)
            if needs:
                needs_str = ", ".join(f"{pos}: {n}" for pos, n in needs.items())
                print(f"  Still need: {needs_str}")

    def do_value(self, arg):
        """Show value picks - players available past their ADP.
        Usage: value [limit]"""
        limit = 15
        if arg.strip().isdigit():
            limit = int(arg.strip())

        value_picks = get_value_picks(
            self.projections, self.taken_players, self.pick_number + 1, window=limit
        )

        if len(value_picks) == 0:
            print("No value picks found (no players past their ADP).")
            return

        self._print_header(f"VALUE PICKS (Pick #{self.pick_number + 1})")
        print("  Players who should have been drafted already:")
        print(f"{'':>4} {'Player':<25} {'Pos':<4} {'ADP':>6} {'Current':>8} {'Value':>8} {'VOR':>10}")
        print("-" * 75)

        for i, row in enumerate(value_picks.iter_rows(named=True), 1):
            name = row["player_name"]
            pos = row["position"]
            adp = row.get("adp", 0) or 0
            value = row.get("adp_value", 0) or 0
            vor = row.get("vor", 0) or 0
            current = self.pick_number + 1

            value_color = SUCCESS_COLOR if value >= 10 else ""
            reset = RESET_COLOR if value_color else ""

            print(f"{i:>3}. {name:<25} {pos:<4} {adp:>6.1f} {current:>8} {value_color}+{value:>6.1f}{reset} {vor:>+10.1f}")

    def do_targets(self, arg):
        """Show players likely available at your next pick.
        Usage: targets [picks_until_next]
        Default assumes 12-team snake (24 picks between your turns)."""
        picks_until_next = 24  # Default for 12-team snake
        if arg.strip().isdigit():
            picks_until_next = int(arg.strip())

        targets = get_upcoming_targets(
            self.projections, self.taken_players, self.pick_number + 1, picks_until_next
        )

        if len(targets) == 0:
            print("No target data available.")
            return

        self._print_header(f"TARGETS (Picks {self.pick_number + 1} to {self.pick_number + picks_until_next})")
        print("  Players who might still be there at your next pick:")
        print(f"{'':>4} {'Player':<25} {'Pos':<4} {'ADP':>8} {'VOR':>10}")
        print("-" * 60)

        for i, row in enumerate(targets.head(15).iter_rows(named=True), 1):
            name = row["player_name"]
            pos = row["position"]
            adp = row.get("adp", 0) or 0
            vor = row.get("vor", 0) or 0
            print(f"{i:>3}. {name:<25} {pos:<4} {adp:>8.1f} {vor:>+10.1f}")

    def do_trade(self, arg):
        """Evaluate a draft pick trade interactively.
        Usage: trade
        Then enter picks in format: 1.05, 2.12 or overall pick numbers like 15, 25"""

        self._print_header("TRADE EVALUATOR")
        print("Enter picks you're GIVING (comma-separated, e.g., '1.05' or '15'):")
        print("  Format: round.pick (1.05) or overall pick number (5)")

        try:
            giving_input = input("  Giving: ").strip()
            if not giving_input:
                print("Cancelled.")
                return

            receiving_input = input("  Receiving: ").strip()
            if not receiving_input:
                print("Cancelled.")
                return
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return

        # Parse picks
        giving_picks = []
        for p in giving_input.split(','):
            pick = parse_pick_notation(p.strip())
            if pick is None:
                print(f"  {ALERT_COLOR}Invalid pick format: '{p.strip()}'{RESET_COLOR}")
                return
            giving_picks.append(pick)

        receiving_picks = []
        for p in receiving_input.split(','):
            pick = parse_pick_notation(p.strip())
            if pick is None:
                print(f"  {ALERT_COLOR}Invalid pick format: '{p.strip()}'{RESET_COLOR}")
                return
            receiving_picks.append(pick)

        # Evaluate trade
        result = evaluate_trade(giving_picks, receiving_picks)

        # Display results
        print()
        print(f"  GIVING:    Picks {giving_picks}")
        for p in giving_picks:
            value = get_pick_value(p)
            print(f"             Pick {p:>3} = {value:>5.1f} value")
        print(f"             Total: {result['giving_value']:.1f}")

        print()
        print(f"  RECEIVING: Picks {receiving_picks}")
        for p in receiving_picks:
            value = get_pick_value(p)
            print(f"             Pick {p:>3} = {value:>5.1f} value")
        print(f"             Total: {result['receiving_value']:.1f}")

        print()
        net = result['net_value']
        verdict = result['verdict']

        if verdict == "WIN":
            verdict_str = f"{SUCCESS_COLOR}WIN (+{net:.1f}){RESET_COLOR}"
        elif verdict == "LOSS":
            verdict_str = f"{ALERT_COLOR}LOSS ({net:.1f}){RESET_COLOR}"
        else:
            verdict_str = f"FAIR ({net:+.1f})"

        print(f"  VERDICT: {verdict_str}")

    def do_pickvalue(self, arg):
        """Show the trade value of draft picks.
        Usage: pickvalue <pick> or pickvalue <start>-<end>
        Examples: pickvalue 1.05, pickvalue 15, pickvalue 1-24"""

        if not arg:
            # Show value chart for first 3 rounds
            self._print_header("PICK VALUE CHART (Rounds 1-3)")
            print(f"  {'Pick':<8} {'Round':<8} {'Value':>8}")
            print("  " + "-" * 26)
            for pick in range(1, 37):
                round_num = (pick - 1) // 12 + 1
                pick_in_round = (pick - 1) % 12 + 1
                value = get_pick_value(pick)
                print(f"  {pick:<8} {round_num}.{pick_in_round:<6} {value:>8.1f}")
            return

        # Check for range (e.g., "1-24")
        if '-' in arg and '.' not in arg:
            try:
                start, end = arg.split('-')
                start_pick = int(start.strip())
                end_pick = int(end.strip())

                self._print_header(f"PICK VALUES: {start_pick} to {end_pick}")
                print(f"  {'Pick':<8} {'Round':<8} {'Value':>8}")
                print("  " + "-" * 26)

                total = 0
                for pick in range(start_pick, end_pick + 1):
                    round_num = (pick - 1) // 12 + 1
                    pick_in_round = (pick - 1) % 12 + 1
                    value = get_pick_value(pick)
                    total += value
                    print(f"  {pick:<8} {round_num}.{pick_in_round:<6} {value:>8.1f}")

                print("  " + "-" * 26)
                print(f"  {'Total':<16} {total:>8.1f}")
                return
            except ValueError:
                pass

        # Single pick
        pick = parse_pick_notation(arg)
        if pick is None:
            print(f"Invalid pick format: '{arg}'")
            print("Use: pickvalue 1.05 or pickvalue 15 or pickvalue 1-24")
            return

        value = get_pick_value(pick)
        round_num = (pick - 1) // 12 + 1
        pick_in_round = (pick - 1) % 12 + 1

        print(f"\n  Pick {pick} (Round {round_num}, Pick {pick_in_round})")
        print(f"  Trade Value: {value:.1f}")

        # Show equivalent combinations
        equivalents = find_equivalent_picks(pick)
        if equivalents:
            print(f"\n  Equivalent 2-pick trades:")
            for pick_a, pick_b in equivalents[:5]:
                val_a = get_pick_value(pick_a)
                val_b = get_pick_value(pick_b)
                print(f"    Picks {pick_a} + {pick_b} = {val_a + val_b:.1f}")

    def do_scarcity(self, arg):
        """Show position scarcity report."""
        scarcity = calculate_position_scarcity(self.projections, self.taken_players)

        self._print_header("POSITION SCARCITY REPORT")
        print(f"{'Position':<10} {'Elite Left':<12} {'Available':<12} {'Next VOR':<12} {'Alert'}")
        print("-" * 60)

        for pos, data in scarcity.items():
            alert = f"{ALERT_COLOR}SCARCE!{RESET_COLOR}" if data["scarcity_alert"] else ""
            print(
                f"{pos:<10} {data['remaining_elite']:<12} "
                f"{data['total_available']:<12} {data['next_best_vor']:>+8.1f}     {alert}"
            )

    def do_search(self, arg):
        """Search for a player by name. Usage: search <name>"""
        if not arg:
            print("Usage: search <player name>")
            return

        matches = self.projections.filter(
            pl.col("player_name").str.to_lowercase().str.contains(arg.lower())
        ).head(10)

        if len(matches) == 0:
            print(f"No players found matching '{arg}'")
            return

        self._print_header(f"SEARCH RESULTS FOR '{arg}'")
        for row in matches.iter_rows(named=True):
            name = row["player_name"]
            status = "(TAKEN)" if name in self.taken_players else "(available)"

            # Check if on our teams
            for team_key, roster in self.rosters.items():
                if any(p["player_name"] == name for p in roster):
                    status = f"({self.teams[team_key]['team_name']})"
                    break

            print(f"  {name:<25} {row['position']:<4} {row['proj_total_points_2026']:>6.1f} pts  VOR:{row['vor']:>+6.1f}  {status}")

    def do_undo(self, arg):
        """Undo the last pick/draft action."""
        if not self.history:
            print("Nothing to undo.")
            return

        action, name, team_key = self.history.pop()
        self.taken_players.discard(name)
        self.pick_number -= 1

        if action == "draft" and team_key:
            self.rosters[team_key] = [
                p for p in self.rosters[team_key] if p["player_name"] != name
            ]
            print(f"Undid: {name} removed from {self.teams[team_key]['team_name']}")
        else:
            print(f"Undid: {name} back on the board")

    def do_sync(self, arg):
        """Sync with ESPN to get live draft state."""
        print("Connecting to ESPN...")
        try:
            from espn_api.football import League
            league = League(
                league_id=LEAGUE_ID,
                year=SEASON_YEAR,
                espn_s2=ESPN_S2,
                swid=SWID
            )
            print(f"Connected to: {league.settings.name}")

            # Get draft picks
            new_picks = 0
            for pick in league.draft:
                name = pick.playerName
                if name and name not in self.taken_players:
                    self.taken_players.add(name)
                    new_picks += 1

                    # Check if it's one of our teams
                    if pick.team:
                        for team_key, team_info in self.teams.items():
                            if pick.team.team_id == team_info["team_id"]:
                                # Find player data
                                player_row = self.projections.filter(
                                    pl.col("player_name") == name
                                )
                                if len(player_row) > 0:
                                    self.rosters[team_key].append(
                                        player_row.row(0, named=True)
                                    )

            print(f"{SUCCESS_COLOR}Synced {new_picks} new picks from ESPN.{RESET_COLOR}")
            print(f"Total picks: {len(self.taken_players)}")

        except Exception as e:
            print(f"{ALERT_COLOR}Error syncing with ESPN: {e}{RESET_COLOR}")

    def do_status(self, arg):
        """Show current draft status."""
        self._print_header("DRAFT STATUS")
        print(f"Total picks: {self.pick_number}")
        print(f"Players taken: {len(self.taken_players)}")

        if self.sim_draft_data is not None:
            remaining = len(self.sim_draft_data) - self.sim_index
            print(f"Simulation: {self.sim_index}/{len(self.sim_draft_data)} picks ({remaining} remaining)")

        print()
        for team_key, team_info in self.teams.items():
            roster = self.rosters[team_key]
            print(f"{team_info['color']}{team_info['team_name']}{RESET_COLOR}: {len(roster)} players")

    def do_sim(self, arg):
        """Draft simulation mode using 2025 draft data.
        Usage:
          sim load    - Load 2025 draft data for simulation
          sim next    - Process next pick in simulation
          sim next 5  - Process next 5 picks
          sim auto    - Auto-process all picks except your teams
          sim reset   - Reset simulation
          sim status  - Show simulation status"""

        args = arg.strip().lower().split()
        if not args:
            args = ["status"]

        cmd = args[0]

        if cmd == "load":
            self._sim_load()
        elif cmd == "next":
            count = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
            self._sim_next(count)
        elif cmd == "auto":
            self._sim_auto()
        elif cmd == "reset":
            self._sim_reset()
        elif cmd == "status":
            self._sim_status()
        else:
            print(f"Unknown sim command: {cmd}")
            print("Use: sim load, sim next [n], sim auto, sim reset, sim status")

    def _sim_load(self):
        """Load 2025 draft data for simulation."""
        conn = get_connection()
        draft_df = read_sqlite_robust(
            "SELECT round_num, round_pick, team_id, player_name FROM bronze_espn_draft ORDER BY round_num, round_pick",
            conn
        )
        conn.close()

        if len(draft_df) == 0:
            print(f"{ALERT_COLOR}No draft data found in database.{RESET_COLOR}")
            return

        self.sim_draft_data = draft_df.to_dicts()
        self.sim_index = 0

        # Reset draft state
        self.taken_players.clear()
        self.rosters = {"ryan": [], "wife": []}
        self.history.clear()
        self.pick_number = 0

        print(f"{SUCCESS_COLOR}Loaded {len(self.sim_draft_data)} picks from 2025 draft.{RESET_COLOR}")
        print("Use 'sim next' to advance picks, 'sim auto' to auto-pick non-team picks.")
        self._sim_status()

    def _sim_next(self, count: int = 1):
        """Process next N picks in simulation."""
        if self.sim_draft_data is None:
            print("No simulation loaded. Use 'sim load' first.")
            return

        for _ in range(count):
            if self.sim_index >= len(self.sim_draft_data):
                print("Simulation complete - all picks processed.")
                return

            pick_data = self.sim_draft_data[self.sim_index]
            self.sim_index += 1

            player_name = pick_data["player_name"]
            team_id = pick_data["team_id"]
            round_num = pick_data["round_num"]
            round_pick = pick_data["round_pick"]

            # Check if this is one of our teams
            team_key = None
            for key, info in self.teams.items():
                if info["team_id"] == team_id:
                    team_key = key
                    break

            # Find player in projections
            player = self._find_player(player_name)
            if player:
                name = player["player_name"]
                self.taken_players.add(name)
                self.pick_number += 1
                self.history.append(("pick", name, team_key))

                if team_key:
                    self.rosters[team_key].append(player)

                # Analyze pick
                analysis = analyze_pick_value(name, self.pick_number, self.projections)
                adp_str = f"ADP: {analysis['adp']:.1f}" if analysis['adp'] else "ADP: N/A"
                assessment = analysis['assessment']

                if "VALUE" in assessment:
                    assessment = f"{SUCCESS_COLOR}{assessment}{RESET_COLOR}"
                elif "REACH" in assessment:
                    assessment = f"{ALERT_COLOR}{assessment}{RESET_COLOR}"

                team_str = f" -> {self.teams[team_key]['team_name']}" if team_key else ""
                color = self.teams[team_key]['color'] if team_key else ""
                reset = RESET_COLOR if team_key else ""

                print(f"{color}#{self.pick_number} ({round_num}.{round_pick:02d}): {name} ({player['position']}){team_str}{reset}")
                print(f"  {adp_str} | {assessment}")
            else:
                # Player not in our projections - just mark as taken
                self.taken_players.add(player_name)
                self.pick_number += 1
                print(f"#{self.pick_number} ({round_num}.{round_pick:02d}): {player_name} (not in projections)")

            self._check_scarcity_alerts()

    def _sim_auto(self):
        """Auto-process picks until we hit one of our teams or end."""
        if self.sim_draft_data is None:
            print("No simulation loaded. Use 'sim load' first.")
            return

        my_team_ids = {info["team_id"] for info in self.teams.values()}
        processed = 0

        while self.sim_index < len(self.sim_draft_data):
            pick_data = self.sim_draft_data[self.sim_index]
            team_id = pick_data["team_id"]

            # Stop if this is one of our teams
            if team_id in my_team_ids:
                print(f"\n{SUCCESS_COLOR}Stopped at pick #{self.pick_number + 1} - YOUR TURN!{RESET_COLOR}")
                team_key = "ryan" if team_id == self.teams["ryan"]["team_id"] else "wife"
                print(f"  Drafting for: {self.teams[team_key]['team_name']}")
                break

            self._sim_next(1)
            processed += 1

        if self.sim_index >= len(self.sim_draft_data):
            print(f"\nSimulation complete. Processed {processed} picks.")

    def _sim_reset(self):
        """Reset simulation state."""
        self.sim_draft_data = None
        self.sim_index = 0
        self.taken_players.clear()
        self.rosters = {"ryan": [], "wife": []}
        self.history.clear()
        self.pick_number = 0
        print("Simulation reset.")

    def _sim_status(self):
        """Show simulation status."""
        if self.sim_draft_data is None:
            print("No simulation loaded. Use 'sim load' to load 2025 draft data.")
            return

        total = len(self.sim_draft_data)
        remaining = total - self.sim_index
        print(f"\nSimulation Status:")
        print(f"  Picks processed: {self.sim_index}/{total}")
        print(f"  Picks remaining: {remaining}")

        if self.sim_index < total:
            next_pick = self.sim_draft_data[self.sim_index]
            team_id = next_pick["team_id"]
            team_str = "OTHER"
            for key, info in self.teams.items():
                if info["team_id"] == team_id:
                    team_str = f"{info['team_name']} (YOUR PICK!)"
                    break
            print(f"  Next pick: {next_pick['round_num']}.{next_pick['round_pick']:02d} - {team_str}")

    def do_clear(self, arg):
        """Clear the screen."""
        os.system('clear' if os.name != 'nt' else 'cls')

    def do_exit(self, arg):
        """Exit the draft assistant."""
        print("\nGood luck with the draft!")
        return True

    def do_quit(self, arg):
        """Exit the draft assistant."""
        return self.do_exit(arg)

    def do_EOF(self, arg):
        """Handle Ctrl+D."""
        print()
        return self.do_exit(arg)

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _find_player(self, search: str) -> dict | None:
        """Find a player by name (exact or fuzzy match)."""
        # Try exact match first (case insensitive)
        matches = self.projections.filter(
            pl.col("player_name").str.to_lowercase() == search.lower()
        )

        if len(matches) == 0:
            # Try contains match
            matches = self.projections.filter(
                pl.col("player_name").str.to_lowercase().str.contains(search.lower())
            )

        if len(matches) == 0:
            print(f"Player '{search}' not found.")
            return None

        if len(matches) > 1:
            print(f"Multiple matches for '{search}':")
            for row in matches.head(5).iter_rows(named=True):
                print(f"  - {row['player_name']} ({row['position']})")
            print("Please be more specific.")
            return None

        return matches.row(0, named=True)

    def _check_scarcity_alerts(self):
        """Check and display any position scarcity alerts."""
        scarcity = calculate_position_scarcity(self.projections, self.taken_players)

        for pos, data in scarcity.items():
            if data["scarcity_alert"] and data["remaining_elite"] > 0:
                print(
                    f"  {ALERT_COLOR}[ALERT] Only {data['remaining_elite']} elite {pos} remaining!{RESET_COLOR}"
                )


def main():
    try:
        LiveDraftShell().cmdloop()
    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    main()

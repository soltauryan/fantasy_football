import argparse
import sys
import polars as pl

# Force utf-8 output for Windows terminals
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = "sqlite:///data/nfl.db"

# Minimum roster requirements (Standard League)
MIN_POSITIONS = {
    "QB": 1,
    "RB": 2,
    "WR": 2,
    "TE": 1,
    "D/ST": 1,
    "K": 1
}

# "Safe" depth for dropping players (Min + 1 usually, except maybe K/Def)
SAFE_DEPTH = {
    "QB": 2,
    "RB": 4, # Want meaningful depth
    "WR": 4, # Want meaningful depth
    "TE": 2,
    "D/ST": 1, # Streaming is common, but 1 is min
    "K": 1
}

def load_data():
    try:
        teams = pl.read_database_uri("SELECT * FROM bronze_espn_teams", DB_PATH, engine="adbc")
        rosters = pl.read_database_uri("SELECT * FROM bronze_espn_rosters", DB_PATH, engine="adbc")
        free_agents = pl.read_database_uri("SELECT * FROM bronze_espn_free_agents", DB_PATH, engine="adbc")
        # loading matchups if available
        try:
            matchups = pl.read_database_uri("SELECT * FROM bronze_espn_matchups", DB_PATH, engine="adbc")
            matchup_players = pl.read_database_uri("SELECT * FROM bronze_espn_matchup_players", DB_PATH, engine="adbc")
        except:
            matchups = None
            matchup_players = None
            
        power_rankings = pl.read_database_uri("SELECT * FROM bronze_espn_power_rankings", DB_PATH, engine="adbc")
        return teams, rosters, free_agents, power_rankings, matchups, matchup_players
    except Exception as e:
        print(f"Error loading data: {e}")
        return None, None, None, None, None, None

def check_roster_balance(team_roster):
    print("\n--- Roster Balance Check ---")
    counts = team_roster.group_by("position").len()
    
    issues_found = False
    for pos, min_count in MIN_POSITIONS.items():
        curr_count = 0
        row = counts.filter(pl.col("position") == pos)
        if not row.is_empty():
            curr_count = row["len"][0]
        
        if curr_count < min_count:
            print(f" [WARNING] Under-staffed at {pos}: Have {curr_count}, Need {min_count}")
            issues_found = True
        else:
            # Check for healthy depth
            safe_count = SAFE_DEPTH.get(pos, min_count)
            status = "Optimal" if curr_count >= safe_count else "Thin"
            print(f" [OK] {pos}: {curr_count} ({status})")
            
    if not issues_found:
        print("Roster meets minimum requirements.")
    return counts

def analyze_team(team_name, rosters, free_agents, teams, matchups, matchup_players):
    print(f"\n{'='*40}")
    print(f"Weekly Analysis for: {team_name}")
    print(f"{'='*40}")

    # Get team ID
    team_row = teams.filter(pl.col("team_name") == team_name)
    if team_row.is_empty():
        print(f"Team '{team_name}' not found.")
        return
    team_id = team_row["team_id"][0]

    # 1. Roster Overview & Optimization
    print("\n[ROSTER OVERVIEW]")
    team_roster = rosters.filter(pl.col("team_id") == team_id)
    
    # Check Balance
    pos_counts = check_roster_balance(team_roster)

    # Lineup Health Check
    print("\n--- Lineup Health Check ---")
    # Starters are those NOT on Bench (BE/20) or IR (IR/21)
    # Note: ingest_espn saves lineupSlot. In ESPN API, valid slots are usually strings "QB", "RB" etc or "BE". 
    # Let's handle both string and potential int codes if they appear.
    # We'll filter for where lineup_slot is NOT 'BE' and NOT 'IR'.
    starters = team_roster.filter(
        (pl.col("lineup_slot") != "BE") & 
        (pl.col("lineup_slot") != "IR") &
        (pl.col("lineup_slot") != "20") & 
        (pl.col("lineup_slot") != "21")
    )
    
    risky_starters = starters.filter(
        (pl.col("injury_status") == "OUT") | 
        (pl.col("injury_status") == "IR") | 
        (pl.col("injury_status") == "DOUBTFUL") |
        (pl.col("injury_status") == "SUSPENDED")
    )
    
    if not risky_starters.is_empty():
        print(" [CRITICAL] You have RISKY players in your starting lineup:")
        for row in risky_starters.iter_rows(named=True):
            print(f"   !!! {row['player_name']} ({row['position']}) is {row['injury_status']}!")
    else:
        print(" [OK] Starting lineup looks healthy.")

    print("\n--- Start/Sit Recommendations ---")
    # Sort all players by projected points (Use Weekly if available, else Season)
    # Join with matchup_players to get weekly projection
    # We need the current week (max in matchup_players)
    current_week = 0
    if matchup_players is not None:
        current_week = matchup_players["week"].max()
        # Filter for this week
        week_projections = matchup_players.filter(pl.col("week") == current_week).select(["player_id", "projected_points"])
        
        # Join
        team_roster = team_roster.join(week_projections, on="player_id", how="left")
        # Fill nulls with 0 or fallback? Let's keep distinct
        
    sorted_roster = team_roster.sort("projected_total_points", descending=True)
    if "projected_points" in team_roster.columns:
         sorted_roster = team_roster.sort("projected_points", descending=True)
    
    # Status Code Mapping
    STATUS_MAP = {
        0: "Active",
        1: "Questionable",
        2: "Doubtful",
        3: "Out",
        4: "IR",
        5: "Suspended"
    }

    # We could do smarter slot filling here, but for now, listing top by position
    for pos in ["QB", "RB", "WR", "TE", "D/ST", "K"]:
        print(f"  {pos}:")
        pos_players = sorted_roster.filter(pl.col("position") == pos)
        for row in pos_players.iter_rows(named=True):
            status_desc = STATUS_MAP.get(row['is_injured'], str(row['is_injured']))
            if row['is_injured'] == True: status_desc = "Injured"
            if row['is_injured'] == False: status_desc = "Active"
            
            weekly_proj = row.get('projected_points', 'N/A')
            season_proj = row['projected_total_points']
            
            # Format nicely
            proj_str = f"{weekly_proj} wk / {season_proj} seas"
            if weekly_proj == 'N/A' or weekly_proj is None:
                 proj_str = f"{season_proj} seas"
                
            print(f"    - {row['player_name']}: {proj_str} proj pts (Status: {status_desc})")

    # 2. Waiver Wire Targets
    print("\n[WAIVER WIRE ANALYSIS]")
    
    # Identify drop candidates (low total points, bench warmers)
    # Don't drop if it violates minimum position counts
    
    bottom_players = team_roster.sort("total_points").head(5)
    candidates_to_drop = []
    
    print("Potential Drop Candidates:")
    for row in bottom_players.iter_rows(named=True):
        pos = row['position']
        # Check if dropping this player leaves us short of SAFE depth
        curr_count = pos_counts.filter(pl.col("position") == pos)["len"][0]
        safe_count = SAFE_DEPTH.get(pos, MIN_POSITIONS.get(pos, 0))
        
        if curr_count > safe_count:
            print(f" - {row['player_name']} ({pos}): {row['total_points']} pts (Safe to drop)")
            candidates_to_drop.append(row)
        elif curr_count > MIN_POSITIONS.get(pos, 0):
             print(f" - {row['player_name']} ({pos}): {row['total_points']} pts (Risk: Drops below healthy depth)")
        else:
            print(f" - {row['player_name']} ({pos}): {row['total_points']} pts (DO NOT DROP: Below Min)")

    print("\nTop Available Free Agents (by Position):")
    # Filter by decent availability and points, but group by position
    # Candidates must handle RB/WR/TE flex spots, but let's stick to primary pos
    
    for pos in ["QB", "RB", "WR", "TE", "D/ST", "K"]:
        print(f"  {pos}:")
        # Filter for this position and sorting
        # Note: positions in DB are strings like "QB", "RB" etc.
        pos_fa = free_agents.filter(
            (pl.col("position") == pos) & 
            (pl.col("percent_owned") > 0.1) # Filter out complete unknowns
        ).sort("projected_total_points", descending=True).head(3)
        
        if pos_fa.is_empty():
            print("    (None found meeting criteria)")
        
        for row in pos_fa.iter_rows(named=True):
             print(f"    + {row['player_name']}: {row['projected_total_points']} proj / {row['total_points']} total ({row['percent_owned']}% owned)")

    # 3. Matchup Preview
    if matchups is not None and matchup_players is not None:
        print("\n[MATCHUP PREVIEW]")
        # Find current week's matchup
        max_week = matchups["week"].max()
        current_matchup = matchups.filter(
            (pl.col("week") == max_week) & 
            ((pl.col("home_team_id") == team_id) | (pl.col("away_team_id") == team_id))
        )
        
        if not current_matchup.is_empty():
            match_row = current_matchup.row(0, named=True)
            opponent_id = match_row['away_team_id'] if match_row['home_team_id'] == team_id else match_row['home_team_id']
            
            opp_team_name_row = teams.filter(pl.col("team_id") == opponent_id)
            opp_name = opp_team_name_row["team_name"][0] if not opp_team_name_row.is_empty() else "Unknown"
            
            print(f"Week {max_week} vs. {opp_name}")
            
            # Use bronze_espn_matchup_players for WEEKLY projections
            # Filter for this week and relevant teams
            week_players = matchup_players.filter(pl.col("week") == max_week)
            
            # Startable slots only? The API returns all usually, but let's just sum all for now or filter out bench if slot_position != 20 (Bench is usually 20 in ESPN)
            # ESPN Slot IDs: 20=Bench, 21=IR
            # correction: slot_position is a string here 'BE', 'IR'
            starters = week_players.filter((pl.col("slot_position") != "BE") & (pl.col("slot_position") != "IR"))
            
            my_proj = starters.filter(pl.col("team_id") == team_id)["projected_points"].sum()
            opp_proj = starters.filter(pl.col("team_id") == opponent_id)["projected_points"].sum()
            
            print(f"  My Projected (Week {max_week}): {my_proj:.2f}")
            print(f"  Opponent Projected (Week {max_week}): {opp_proj:.2f}")
            print(f"  Spread: {my_proj - opp_proj:.2f}")
            
            if my_proj > opp_proj:
                print("  -> Favored to Win")
            else:
                print("  -> Projected to Lose")
            
        else:
            print("No matchup found for the current week.")

def main():
    parser = argparse.ArgumentParser(description="Weekly Fantasy Football Optimizer")
    parser.add_argument("--team", type=str, help="Name of your team")
    args = parser.parse_args()

    teams, rosters, free_agents, power_rankings, matchups, matchup_players = load_data()
    
    if teams is None:
        return

    target_team = args.team
    if not target_team:
        print("Available Teams:")
        print(teams.select("team_name"))
        # Clean default selection
        target_team = teams["team_name"][0]
        print(f"\nNo team specified. Running for: {target_team}")

    analyze_team(target_team, rosters, free_agents, teams, matchups, matchup_players)

if __name__ == "__main__":
    main()

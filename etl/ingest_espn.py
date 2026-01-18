import os
import polars as pl
from espn_api.football import League

# Configuration
LEAGUE_ID = 1365062471
SEASON_YEAR = 2025
# Credits to user for providing these
SWID = "{D2241401-9D06-46E7-84DB-B5878BA69DBD}"
ESPN_S2 = "AEA6s487YT1GrFEFWnpw0MpjPtXYDjNQ%2Fn%2FD%2B9A2GMwtEY5lnL%2B3rrL9bwWJX6oxs8gS4%2B3QBkDBRTCtVxeFc1SWRGYAbSZps5Jp1qFQJqWLO8KzdwVRKrIYVChYEQHqVEydsFdM30uIc3%2BFeGxjcIWln7nOJg8BFIDt0TJAhJpA6a8RgAcx9xZxIraTaia7z%2F1VXAytigfjLKy7ErgnA9SuojVObO5wsx852FuWL4K0PMl9VfIpSaVkVyq9KWtIdAmPANB4EM7boPSO9YhXrx%2FBasgmSITqBgOMzZNeJpKe4E3RX%2F1NpJmg7nmebZLcLpmdnF0Da807qmpHG5Qwfz93"

DB_PATH = "sqlite:///data/nfl.db"

def ingest_espn_data():
    print(f"Connecting to ESPN League {LEAGUE_ID} ({SEASON_YEAR})...")
    
    try:
        league = League(league_id=LEAGUE_ID, year=SEASON_YEAR, espn_s2=ESPN_S2, swid=SWID)
    except Exception as e:
        print(f"Error connecting to league: {e}")
        return

    print(f"Successfully connected to league: {league.settings.name}")

    # 1. Extract Teams Data
    print("Extracting Team Data...")
    teams_data = []
    for team in league.teams:
        teams_data.append({
            "team_id": team.team_id,
            "team_name": team.team_name,
            "owner": str(team.owners), # owners is a list usually
            "division_id": team.division_id,
            "wins": team.wins,
            "losses": team.losses,
            "points_for": team.points_for,
            "points_against": team.points_against,
            "standing": team.standing,
        })
    
    if teams_data:
        df_teams = pl.DataFrame(teams_data)
        print(f"  -> Found {len(df_teams)} teams.")
        df_teams.write_database(
            table_name="bronze_espn_teams",
            connection=DB_PATH,
            if_table_exists="replace",
            engine="adbc"
        )
        print("  -> Saved to bronze_espn_teams.")

    # 2. Extract Matchups (Box Scores)
    # We iterate through weeks. For current season, we might go up to current week.
    # The API usually handles fetching available weeks. We'll try 1-17 (or 18)
    print("Extracting Matchup Data...")
    matchups_data = []
    
    # Simple logic: try fetching weeks 1 to 18. If empty, stop.
    # Note: espn_api usually returns list of BoxScore objects
    for week in range(1, 19): 
        try:
            box_scores = league.box_scores(week=week)
            if not box_scores:
                break
            
            for match in box_scores:
                # Regular season definition might vary, catching basic info
                matchups_data.append({
                    "week": week,
                    "home_team_id": match.home_team.team_id if match.home_team else None,
                    "home_score": match.home_score,
                    "away_team_id": match.away_team.team_id if match.away_team else None,
                    "away_score": match.away_score,
                    "winner": "HOME" if match.home_score > match.away_score else "AWAY" if match.away_score > match.home_score else "TIE",
                })
        except Exception as e:
            print(f"  Error fetching week {week}: {e}")
            import traceback
            traceback.print_exc()

    if matchups_data:
        df_matchups = pl.DataFrame(matchups_data)
        print(f"  -> Found {len(df_matchups)} matchups.")
        df_matchups.write_database(
            table_name="bronze_espn_matchups",
            connection=DB_PATH,
            if_table_exists="replace",
            engine="adbc"
        )
        print("  -> Saved to bronze_espn_matchups.")
    else:
        print("  -> No matchup data found (season might not have started or error).")

    # 2.5 Extract Matchup Player Details (for Weekly Projections)
    print("Extracting Matchup Player Details (Projections)...")
    matchup_players_data = []
    
    # We re-iterate or use the previously fetched box_scores if we stored them, 
    # but for simplicity/cleanness let's fetch again or just iterate weeks again.
    # To save time, let's just do the current week + previous weeks? detailed history is good.
    for week in range(1, 19):
        try:
            box_scores = league.box_scores(week=week)
            if not box_scores:
                break
            
            for match in box_scores:
                # Process Home Lineup
                if hasattr(match, 'home_lineup'):
                    for p in match.home_lineup:
                        matchup_players_data.append({
                            "week": week,
                            "team_id": match.home_team.team_id if match.home_team else None,
                            "player_id": p.playerId,
                            "player_name": p.name,
                            "slot_position": p.slot_position,
                            "projected_points": getattr(p, 'projected_points', 0.0),
                            "points": p.points
                        })
                # Process Away Lineup
                if hasattr(match, 'away_lineup'):
                    for p in match.away_lineup:
                        matchup_players_data.append({
                            "week": week,
                            "team_id": match.away_team.team_id if match.away_team else None,
                            "player_id": p.playerId,
                            "player_name": p.name,
                            "slot_position": p.slot_position,
                            "projected_points": getattr(p, 'projected_points', 0.0),
                            "points": p.points
                        })
                        
        except Exception as e:
            # Week might not exist yet
            pass

    if matchup_players_data:
        df_mp = pl.DataFrame(matchup_players_data)
        print(f"  -> Found {len(df_mp)} player-week entries.")
        df_mp.write_database(
            table_name="bronze_espn_matchup_players",
            connection=DB_PATH,
            if_table_exists="replace",
            engine="adbc"
        )
        print("  -> Saved to bronze_espn_matchup_players.")

    # 3. Extract Draft Data
    print("Extracting Draft Data...")
    try:
        draft = league.draft
        draft_data = []
        for pick in draft:
            draft_data.append({
                "round_num": pick.round_num,
                "round_pick": pick.round_pick,
                "team_id": pick.team.team_id if pick.team else None,
                "player_name": pick.playerName,
                "bid_amount": pick.bid_amount,
                "keeper_status": pick.keeper_status
            })
        
        if draft_data:
            df_draft = pl.DataFrame(draft_data)
            print(f"  -> Found {len(df_draft)} draft picks.")
            df_draft.write_database(
                table_name="bronze_espn_draft",
                connection=DB_PATH,
                if_table_exists="replace",
                engine="adbc"
            )
            print("  -> Saved to bronze_espn_draft.")
    except Exception as e:
        print(f"  -> Error fetching draft: {e}")

    # 4. Extract Rosters
    print("Extracting Rosters...")
    roster_data = []
    for team in league.teams:
        for player in team.roster:
            roster_data.append({
                "team_id": team.team_id,
                "player_name": player.name,
                "player_id": player.playerId,
                "position": player.position,
                "pro_team": player.proTeam,
                "is_injured": player.injured,
                "injury_status": str(player.injuryStatus),
                "lineup_slot": player.lineupSlot,
                "projected_total_points": player.projected_total_points,
                "total_points": player.total_points
            })

    if roster_data:
        df_rosters = pl.DataFrame(roster_data)
        print(f"  -> Found {len(df_rosters)} roster entries.")
        df_rosters.write_database(
            table_name="bronze_espn_rosters",
            connection=DB_PATH,
            if_table_exists="replace",
            engine="adbc"
        )
        print("  -> Saved to bronze_espn_rosters.")

    # 5. Extract Recent Activity
    print("Extracting Recent Activity...")
    try:
        activity = league.recent_activity(size=1000)
        activity_data = []
        for act in activity:
            # act.actions is a list of (team, action, player, bid) tuples usually, but let's just dump str for now for safety
            activity_data.append({
                "date": act.date,
                "actions": str(act.actions) 
            })
        
        if activity_data:
            df_activity = pl.DataFrame(activity_data)
            print(f"  -> Found {len(df_activity)} activity items.")
            df_activity.write_database(
                table_name="bronze_espn_activity",
                connection=DB_PATH,
                if_table_exists="replace",
                engine="adbc"
            )
            print("  -> Saved to bronze_espn_activity.")
    except Exception as e:
        print(f"  -> Error fetching activity: {e}")

    # 6. Extract League Settings
    print("Extracting League Settings...")
    try:
        settings = league.settings
        settings_data = [{
            "name": settings.name,
            "reg_season_count": settings.reg_season_count,
            "team_count": settings.team_count,
            "veto_votes_required": settings.veto_votes_required
        }]
        
        df_settings = pl.DataFrame(settings_data)
        df_settings.write_database(
            table_name="bronze_espn_league_info",
            connection=DB_PATH,
            if_table_exists="replace",
            engine="adbc"
        )
        print("  -> Saved to bronze_espn_league_info.")
    except Exception as e:
        print(f"  -> Error fetching settings: {e}")

    # 7. Extract Free Agents
    print("Extracting Free Agents (Top 100)...")
    try:
        # Assuming current week is available via league.current_week, but using week=None fetches current
        free_agents = league.free_agents(size=100)
        fa_data = []
        for player in free_agents:
            fa_data.append({
                "player_id": player.playerId,
                "player_name": player.name,
                "position": player.position,
                "pro_team": player.proTeam,
                "projected_total_points": player.projected_total_points,  # Rest of Season or specific week? usually total
                "total_points": player.total_points,
                "injury_status": str(player.injuryStatus),
                "on_team_id": player.onTeamId,
                "percent_owned": player.percent_owned,
                "percent_started": player.percent_started
            })
            
        if fa_data:
            df_fa = pl.DataFrame(fa_data)
            print(f"  -> Found {len(df_fa)} free agents.")
            df_fa.write_database(
                table_name="bronze_espn_free_agents",
                connection=DB_PATH,
                if_table_exists="replace",
                engine="adbc"
            )
            print("  -> Saved to bronze_espn_free_agents.")

    except Exception as e:
        print(f"  -> Error fetching free agents: {e}")

    # 8. Extract Power Rankings
    print("Extracting Power Rankings...")
    try:
        # power_rankings returns a list of tuples: (score, team_obj)
        # Note: calling power_rankings() prints output to stdout in some versions, but returns data too.
        # Let's hope it returns data cleanly.
        pr = league.power_rankings()
        
        pr_data = []
        if pr:
            for score, team in pr:
                pr_data.append({
                    "team_id": team.team_id,
                    "team_name": team.team_name,
                    "power_score": float(score)
                })
        
        if pr_data:
            df_pr = pl.DataFrame(pr_data)
            print(f"  -> Found {len(df_pr)} power ranking entries.")
            df_pr.write_database(
                table_name="bronze_espn_power_rankings",
                connection=DB_PATH,
                if_table_exists="replace",
                engine="adbc"
            )
            print("  -> Saved to bronze_espn_power_rankings.")

    except Exception as e:
        print(f"  -> Error fetching power rankings: {e}")

    print("ESPN Ingestion Complete.")

if __name__ == "__main__":
    # Ensure data dir exists
    os.makedirs("data", exist_ok=True)
    ingest_espn_data()

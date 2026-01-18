import os
from espn_api.football import League

# Configuration
LEAGUE_ID = 1365062471
SEASON_YEAR = 2025
SWID = "{D2241401-9D06-46E7-84DB-B5878BA69DBD}"
ESPN_S2 = "AEA6s487YT1GrFEFWnpw0MpjPtXYDjNQ%2Fn%2FD%2B9A2GMwtEY5lnL%2B3rrL9bwWJX6oxs8gS4%2B3QBkDBRTCtVxeFc1SWRGYAbSZps5Jp1qFQJqWLO8KzdwVRKrIYVChYEQHqVEydsFdM30uIc3%2BFeGxjcIWln7nOJg8BFIDt0TJAhJpA6a8RgAcx9xZxIraTaia7z%2F1VXAytigfjLKy7ErgnA9SuojVObO5wsx852FuWL4K0PMl9VfIpSaVkVyq9KWtIdAmPANB4EM7boPSO9YhXrx%2FBasgmSITqBgOMzZNeJpKe4E3RX%2F1NpJmg7nmebZLcLpmdnF0Da807qmpHG5Qwfz93"

def inspect_projections():
    print(f"Connecting to League...")
    league = League(league_id=LEAGUE_ID, year=SEASON_YEAR, espn_s2=ESPN_S2, swid=SWID)
    
    current_week = league.current_week
    print(f"Current Week: {current_week}")

    # Inspect a player on a roster
    team = league.teams[0]
    player = team.roster[0]
    
    print(f"\nInspecting Player: {player.name}")
    print(f"Projected Total (Season): {player.projected_total_points}")
    print(f"Attributes: {dir(player)}")
    
    # Check if there's a weekly projection in 'stats' or similar
    # Usually it's in box scores for the specific week
    
    print(f"\nFetching Box Scores for Week {current_week}...")
    box_scores = league.box_scores(week=current_week)
    
    if box_scores:
        match = box_scores[0]
        home_team = match.home_team
        print(f"Matchup: {match.home_team.team_name} vs {match.away_team.team_name}")
        
        # Look at the lineup in boxscore
        # box_scores usually have 'home_lineup' and 'away_lineup'
        
        if hasattr(match, 'home_lineup'):
            p = match.home_lineup[0]
            print(f"Box Player: {p.name}")
            print(f"Box Player Proj: {getattr(p, 'projected_points', 'N/A')}")
            print(f"Box Player Points: {p.points}")
            print(f"Box Player Dir: {dir(p)}")
        else:
            print("Box Score object does not have 'home_lineup' attribute?")
            print(dir(match))

if __name__ == "__main__":
    inspect_projections()

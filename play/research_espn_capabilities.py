from espn_api.football import League
import json

# Configuration
LEAGUE_ID = 1365062471
SEASON_YEAR = 2025
SWID = "{D2241401-9D06-46E7-84DB-B5878BA69DBD}"
ESPN_S2 = "AEA6s487YT1GrFEFWnpw0MpjPtXYDjNQ%2Fn%2FD%2B9A2GMwtEY5lnL%2B3rrL9bwWJX6oxs8gS4%2B3QBkDBRTCtVxeFc1SWRGYAbSZps5Jp1qFQJqWLO8KzdwVRKrIYVChYEQHqVEydsFdM30uIc3%2BFeGxjcIWln7nOJg8BFIDt0TJAhJpA6a8RgAcx9xZxIraTaia7z%2F1VXAytigfjLKy7ErgnA9SuojVObO5wsx852FuWL4K0PMl9VfIpSaVkVyq9KWtIdAmPANB4EM7boPSO9YhXrx%2FBasgmSITqBgOMzZNeJpKe4E3RX%2F1NpJmg7nmebZLcLpmdnF0Da807qmpHG5Qwfz93"

def explore_capabilities():
    print(f"Connecting to ESPN League {LEAGUE_ID} ({SEASON_YEAR})...")
    try:
        league = League(league_id=LEAGUE_ID, year=SEASON_YEAR, espn_s2=ESPN_S2, swid=SWID)
        print(f"Connected: {league.settings.name}")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    print("\n--- League Attributes ---")
    print([attr for attr in dir(league) if not attr.startswith('_')])

    print("\n--- Draft ---")
    try:
        draft = league.draft
        print(f"Draft available: {len(draft)} picks found.")
        if draft:
            print(f"Sample pick: {draft[0]}")
    except Exception as e:
        print(f"Draft info error: {e}")

    print("\n--- League Settings ---")
    try:
        print(f"Settings available: {league.settings}")
        print(f"Reg Season Count: {league.settings.reg_season_count}")
    except Exception as e:
        print(f"Settings error: {e}")

    print("\n--- Team Rosters ---")
    if league.teams:
        team = league.teams[0]
        print(f"Roster for {team.team_name}:")
        print(f"Roster count: {len(team.roster)}")
        if team.roster:
            player = team.roster[0]
            print(f"Sample Player: {player}")
            print(f"Player attributes: {[attr for attr in dir(player) if not attr.startswith('_')]}")

    print("\n--- Free Agents (Current Week) ---")
    try:
        fa = league.free_agents(week=1, size=5)
        print(f"Free Agents found: {len(fa)}")
        if fa:
            print(f"Sample FA: {fa[0]}")
    except Exception as e:
        print(f"Free agents error: {e}")
    
    print("\n--- Recent Activity ---")
    try:
        activity = league.recent_activity(size=5)
        print(f"Activity items: {len(activity)}")
        if activity:
            print(f"Sample Activity: {activity[0]}")
    except Exception as e:
        print(f"Activity error: {e}")

if __name__ == "__main__":
    explore_capabilities()

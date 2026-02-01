"""
Live Draft Assistant CLI
Interactive tool for the 2026 Draft.
Features:
- Loads Projections (Vets + Rookies)
- Tracks Taken Players
- Recommends Best Available
- "My Team" View
"""

import polars as pl
import os
import sys
import cmd

# Add project root to path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.db import get_connection, read_sqlite_robust

class DraftShell(cmd.Cmd):
    intro = 'Welcome to the 2026 Fantasy Football Draft Assistant. Type help or ? to list commands.\n'
    prompt = '(draft) '
    
    def __init__(self):
        super().__init__()
        self.conn = get_connection()
        self.players = self.load_players()
        self.my_team = []
        self.taken_players = set()
        
    def load_players(self):
        print("Loading Projections...")
        df = read_sqlite_robust("SELECT * FROM gold_projections_2026", self.conn)
        # Sort by projected points descending
        df = df.sort("proj_total_points_2026", descending=True)
        return df

    def do_avail(self, arg):
        'List top available players. Usage: avail [limit] [pos]'
        # Parse args
        args = arg.split()
        limit = 20
        pos_filter = None
        
        for a in args:
            if a.isdigit():
                limit = int(a)
            elif a.upper() in ["QB", "RB", "WR", "TE", "K", "DST"]:
                pos_filter = a.upper()
                
        # Filter taken
        # using boolean mask on polars is fast
        # but we need to track taken IDs or Names. 
        # Names are unique enough for fantasy usually, or we use IDs.
        # Rookies share "ROOKIE" ID, so use Name for filter.
        
        # Build filter list
        # Using a set check in polars is tricky if list is long, but for draft < 300 it's fine.
        
        df_avail = self.players.filter(~pl.col("player_name").is_in(list(self.taken_players)))
        
        if pos_filter:
            df_avail = df_avail.filter(pl.col("position") == pos_filter)
            
        print(f"\nTop {limit} Available {'(' + pos_filter + ')' if pos_filter else ''}:")
        print(f"{'Name':<25} {'Pos':<5} {'Proj Pts':<10} {'PPG':<5}")
        print("-" * 50)
        
        for row in df_avail.head(limit).iter_rows(named=True):
            print(f"{row['player_name']:<25} {row['position']:<5} {row['proj_total_points_2026']:<10.1f} {row['proj_ppg_2026']:<5.1f}")
            
    def do_pick(self, arg):
        'Mark a player as taken. Usage: pick <player name>'
        name = arg.strip()
        
        # Find player
        # Case insensitive fuzzy match or exact?
        # Let's do Case Insensitive Exact first
        
        # We need to find the name in the DF
        # Efficient way: filter
        matches = self.players.filter(pl.col("player_name").str.to_uppercase() == name.upper())
        
        if len(matches) == 0:
            # Try contains
            matches = self.players.filter(pl.col("player_name").str.to_uppercase().str.contains(name.upper()))
            
        if len(matches) == 0:
            print(f"Player '{name}' not found.")
            return
            
        if len(matches) > 1:
            print(f"Multiple matches found for '{name}':")
            for row in matches.iter_rows(named=True):
                print(f" - {row['player_name']} ({row['position']})")
            print("Please be more specific.")
            return
            
        # Exact match found
        actual_name = matches["player_name"][0]
        if actual_name in self.taken_players:
            print(f"Warning: {actual_name} is already taken.")
            return
            
        self.taken_players.add(actual_name)
        print(f"Took {actual_name} off the board.")
        
    def do_draft(self, arg):
        'Draft a player to YOUR team. Usage: draft <player name>'
        name = arg.strip()
        
        # Same logic as pick but add to my_team
        matches = self.players.filter(pl.col("player_name").str.to_uppercase() == name.upper())
        if len(matches) == 0:
            matches = self.players.filter(pl.col("player_name").str.to_uppercase().str.contains(name.upper()))
            
        if len(matches) == 1:
            actual_name = matches["player_name"][0]
            if actual_name in self.taken_players:
               print(f"{actual_name} is already taken!")
               return
               
            self.taken_players.add(actual_name)
            
            row = matches.row(0, named=True)
            self.my_team.append(row)
            print(f"Drafted {actual_name} to your team!")
        else:
            print(f"Ambiguous or not found: {[r['player_name'] for r in matches.iter_rows(named=True)]}")

    def do_team(self, arg):
        'Show my team.'
        print("\nMy Team:")
        # Group by pos?
        total_proj = 0
        for p in self.my_team:
            print(f"{p['position']:<4} {p['player_name']:<25} {p['proj_total_points_2026']:.1f}")
            total_proj += p['proj_total_points_2026']
        print("-" * 35)
        print(f"Total Projected: {total_proj:.1f}")

    def do_exit(self, arg):
        'Exit the assistant.'
        print("Good luck!")
        return True
        
    def do_quit(self, arg):
        return self.do_exit(arg)

if __name__ == "__main__":
    try:
        DraftShell().cmdloop()
    except KeyboardInterrupt:
        print("\nExiting...")

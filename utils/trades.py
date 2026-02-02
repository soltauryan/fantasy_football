"""
Trade Analysis Utilities - Fantasy Football

Provides:
- Player trade value calculations
- Trade package comparison
- Positional scarcity adjustments
- Two-team trade coordination
"""

import polars as pl
from typing import Optional
from dataclasses import dataclass
from utils.db import get_connection, read_sqlite_robust

# Team configuration
MY_TEAM_IDS = {
    "ryan": 6,
    "wife": 9,
}

# Positional scarcity multipliers (higher = scarcer = more valuable)
POSITION_SCARCITY = {
    "QB": 1.0,   # QBs are relatively replaceable
    "RB": 1.3,   # RBs are scarce, injury-prone
    "WR": 1.1,   # WRs have depth but top-end matters
    "TE": 1.2,   # Elite TEs are rare
}

# Age depreciation (per year over 26)
AGE_DEPRECIATION = {
    "QB": 0.02,   # QBs age gracefully
    "RB": 0.08,   # RBs decline fast
    "WR": 0.04,   # WRs have longer careers
    "TE": 0.03,   # TEs can play long
}

# Peak age by position
PEAK_AGE = {
    "QB": 28,
    "RB": 24,
    "WR": 26,
    "TE": 27,
}


@dataclass
class PlayerTradeValue:
    """Trade value for a single player."""
    player_name: str
    position: str
    team: str
    age: Optional[int]
    projected_points: float
    base_value: float
    scarcity_adjusted: float
    age_adjusted: float
    final_value: float
    tier: str  # "Elite", "Starter", "Flex", "Bench", "Droppable"
    rostered_by: Optional[str]  # "ryan", "wife", or None


@dataclass
class TradeAnalysis:
    """Analysis of a trade package."""
    give_players: list[PlayerTradeValue]
    receive_players: list[PlayerTradeValue]
    give_total: float
    receive_total: float
    difference: float
    verdict: str  # "WIN", "LOSS", "FAIR"
    positional_impact: dict[str, float]  # Net change by position


def load_player_data() -> pl.DataFrame:
    """Load player data with projections and age."""
    conn = get_connection()

    # Get projections
    projections = read_sqlite_robust("""
        SELECT
            player_name, position,
            proj_total_points_2026 as projected_points
        FROM gold_projections_2026
        WHERE position IN ('QB', 'RB', 'WR', 'TE')
    """, conn)

    # Get player ages
    players = read_sqlite_robust("""
        SELECT full_name, position, team, age
        FROM silver_players
        WHERE position IN ('QB', 'RB', 'WR', 'TE')
    """, conn)

    # Get roster info
    rosters = read_sqlite_robust("""
        SELECT player_name, team_id, pro_team as nfl_team
        FROM bronze_espn_rosters
    """, conn)

    conn.close()

    # Join projections with player info
    if projections.is_empty():
        return pl.DataFrame()

    # Add age from silver_players
    result = projections.join(
        players.select(["full_name", "age", "team"]),
        left_on="player_name",
        right_on="full_name",
        how="left"
    )

    # Add roster info
    result = result.join(
        rosters.select(["player_name", "team_id", "nfl_team"]),
        on="player_name",
        how="left"
    )

    return result


def get_position_replacement_value(position: str, data: pl.DataFrame) -> float:
    """Get replacement level value for a position."""
    # Replacement level: 12th best at position for 12-team league
    replacement_rank = {"QB": 12, "RB": 24, "WR": 24, "TE": 12}

    pos_players = data.filter(pl.col("position") == position).sort(
        "projected_points", descending=True
    )

    rank = replacement_rank.get(position, 12)
    if len(pos_players) >= rank:
        return pos_players["projected_points"][rank - 1]
    elif len(pos_players) > 0:
        return pos_players["projected_points"][-1]
    return 0


def calculate_player_value(
    player_name: str,
    data: pl.DataFrame,
    replacement_values: dict[str, float]
) -> Optional[PlayerTradeValue]:
    """Calculate trade value for a single player."""

    player = data.filter(
        pl.col("player_name").str.to_lowercase() == player_name.lower()
    )

    if player.is_empty():
        # Try partial match
        player = data.filter(
            pl.col("player_name").str.to_lowercase().str.contains(player_name.lower())
        )

    if player.is_empty():
        return None

    row = player.row(0, named=True)

    name = row["player_name"]
    position = row["position"]
    team = row.get("team") or row.get("nfl_team") or ""
    age = row.get("age")
    projected = row.get("projected_points", 0) or 0
    team_id = row.get("team_id")

    # Base value = points over replacement
    repl_value = replacement_values.get(position, 0)
    base_value = max(0, projected - repl_value)

    # Apply scarcity multiplier
    scarcity_mult = POSITION_SCARCITY.get(position, 1.0)
    scarcity_adjusted = base_value * scarcity_mult

    # Apply age adjustment
    age_adjusted = scarcity_adjusted
    if age and age > PEAK_AGE.get(position, 26):
        years_over = age - PEAK_AGE[position]
        depreciation = AGE_DEPRECIATION.get(position, 0.03)
        age_factor = max(0.5, 1 - (years_over * depreciation))
        age_adjusted = scarcity_adjusted * age_factor

    # Final value (normalized to 0-100 scale roughly)
    final_value = age_adjusted / 3  # Rough normalization

    # Determine tier
    if final_value >= 30:
        tier = "Elite"
    elif final_value >= 20:
        tier = "Starter"
    elif final_value >= 10:
        tier = "Flex"
    elif final_value >= 5:
        tier = "Bench"
    else:
        tier = "Droppable"

    # Rostered by
    rostered_by = None
    if team_id == 6:
        rostered_by = "ryan"
    elif team_id == 9:
        rostered_by = "wife"

    return PlayerTradeValue(
        player_name=name,
        position=position,
        team=team,
        age=age,
        projected_points=projected,
        base_value=base_value,
        scarcity_adjusted=scarcity_adjusted,
        age_adjusted=age_adjusted,
        final_value=round(final_value, 1),
        tier=tier,
        rostered_by=rostered_by,
    )


def get_all_trade_values() -> list[PlayerTradeValue]:
    """Get trade values for all players."""
    data = load_player_data()

    if data.is_empty():
        return []

    # Calculate replacement values
    replacement_values = {}
    for pos in ["QB", "RB", "WR", "TE"]:
        replacement_values[pos] = get_position_replacement_value(pos, data)

    values = []
    for row in data.iter_rows(named=True):
        player_name = row["player_name"]
        value = calculate_player_value(player_name, data, replacement_values)
        if value:
            values.append(value)

    # Sort by value
    values.sort(key=lambda x: x.final_value, reverse=True)

    return values


def analyze_trade(
    give_names: list[str],
    receive_names: list[str]
) -> Optional[TradeAnalysis]:
    """Analyze a trade between two packages of players."""
    data = load_player_data()

    if data.is_empty():
        return None

    # Calculate replacement values
    replacement_values = {}
    for pos in ["QB", "RB", "WR", "TE"]:
        replacement_values[pos] = get_position_replacement_value(pos, data)

    # Get values for give side
    give_players = []
    for name in give_names:
        value = calculate_player_value(name, data, replacement_values)
        if value:
            give_players.append(value)

    # Get values for receive side
    receive_players = []
    for name in receive_names:
        value = calculate_player_value(name, data, replacement_values)
        if value:
            receive_players.append(value)

    if not give_players and not receive_players:
        return None

    # Calculate totals
    give_total = sum(p.final_value for p in give_players)
    receive_total = sum(p.final_value for p in receive_players)
    difference = receive_total - give_total

    # Determine verdict
    if difference > 5:
        verdict = "WIN"
    elif difference < -5:
        verdict = "LOSS"
    else:
        verdict = "FAIR"

    # Calculate positional impact
    positional_impact = {}
    for pos in ["QB", "RB", "WR", "TE"]:
        give_pos = sum(p.final_value for p in give_players if p.position == pos)
        receive_pos = sum(p.final_value for p in receive_players if p.position == pos)
        if give_pos > 0 or receive_pos > 0:
            positional_impact[pos] = receive_pos - give_pos

    return TradeAnalysis(
        give_players=give_players,
        receive_players=receive_players,
        give_total=round(give_total, 1),
        receive_total=round(receive_total, 1),
        difference=round(difference, 1),
        verdict=verdict,
        positional_impact=positional_impact,
    )


def find_fair_trades(
    player_to_trade: str,
    target_positions: list[str] = None,
    value_tolerance: float = 5.0
) -> list[tuple[PlayerTradeValue, PlayerTradeValue]]:
    """Find fair 1-for-1 trades for a player."""
    values = get_all_trade_values()

    # Find the player to trade
    player_value = None
    for v in values:
        if v.player_name.lower() == player_to_trade.lower():
            player_value = v
            break
        if player_to_trade.lower() in v.player_name.lower():
            player_value = v
            break

    if not player_value:
        return []

    # Find fair trades
    fair_trades = []
    for v in values:
        # Skip same player
        if v.player_name == player_value.player_name:
            continue

        # Skip if position filter doesn't match
        if target_positions and v.position not in target_positions:
            continue

        # Skip if same roster (can't trade with yourself)
        if v.rostered_by == player_value.rostered_by and v.rostered_by is not None:
            continue

        # Check if values are close
        diff = abs(v.final_value - player_value.final_value)
        if diff <= value_tolerance:
            fair_trades.append((player_value, v))

    # Sort by closest match
    fair_trades.sort(key=lambda x: abs(x[0].final_value - x[1].final_value))

    return fair_trades[:20]


def find_two_team_trades(
    min_value: float = 10.0,
    max_diff: float = 5.0
) -> list[TradeAnalysis]:
    """Find mutually beneficial trades between ryan and wife's teams."""
    values = get_all_trade_values()

    ryan_players = [v for v in values if v.rostered_by == "ryan"]
    wife_players = [v for v in values if v.rostered_by == "wife"]

    trades = []

    # Find 1-for-1 trades
    for rp in ryan_players:
        if rp.final_value < min_value:
            continue

        for wp in wife_players:
            if wp.final_value < min_value:
                continue

            diff = abs(rp.final_value - wp.final_value)
            if diff <= max_diff:
                # Check if it helps both teams (different positions)
                if rp.position != wp.position:
                    analysis = analyze_trade([rp.player_name], [wp.player_name])
                    if analysis:
                        trades.append(analysis)

    # Sort by how close to fair
    trades.sort(key=lambda x: abs(x.difference))

    return trades[:15]


def get_team_trade_values(team_key: str) -> list[PlayerTradeValue]:
    """Get trade values for all players on a team."""
    values = get_all_trade_values()
    return [v for v in values if v.rostered_by == team_key]


def get_team_positional_needs(team_key: str) -> dict[str, int]:
    """Get positional needs for a team."""
    conn = get_connection()
    team_id = MY_TEAM_IDS.get(team_key)

    if not team_id:
        return {}

    roster = read_sqlite_robust(f"""
        SELECT position, COUNT(*) as count
        FROM bronze_espn_rosters
        WHERE team_id = {team_id}
        AND position IN ('QB', 'RB', 'WR', 'TE')
        GROUP BY position
    """, conn)
    conn.close()

    # Target counts
    targets = {"QB": 2, "RB": 5, "WR": 5, "TE": 2}
    needs = {}

    for pos, target in targets.items():
        current = 0
        pos_row = roster.filter(pl.col("position") == pos)
        if not pos_row.is_empty():
            current = pos_row["count"][0]

        if current < target:
            needs[pos] = target - current

    return needs


def find_needs_based_trades(max_diff: float = 8.0) -> list[dict]:
    """
    Find trades that address both teams' positional needs.

    Returns trades where each team gives from surplus and receives for need.
    """
    ryan_values = get_team_trade_values("ryan")
    wife_values = get_team_trade_values("wife")

    ryan_needs = get_team_positional_needs("ryan")
    wife_needs = get_team_positional_needs("wife")

    # Find surplus positions (more than starters + 1)
    surplus = {"QB": 2, "RB": 3, "WR": 3, "TE": 1}

    ryan_surplus = {}
    wife_surplus = {}

    for pos in ["QB", "RB", "WR", "TE"]:
        ryan_count = len([v for v in ryan_values if v.position == pos])
        wife_count = len([v for v in wife_values if v.position == pos])

        if ryan_count > surplus[pos]:
            ryan_surplus[pos] = ryan_count - surplus[pos]
        if wife_count > surplus[pos]:
            wife_surplus[pos] = wife_count - surplus[pos]

    trades = []

    # Find trades where:
    # - Ryan gives from surplus, receives for need
    # - Wife gives from surplus, receives for need
    for ryan_give_pos in ryan_surplus.keys():
        for wife_give_pos in wife_surplus.keys():
            # Skip if same position
            if ryan_give_pos == wife_give_pos:
                continue

            # Check if this addresses needs
            ryan_gets_need = wife_give_pos in ryan_needs
            wife_gets_need = ryan_give_pos in wife_needs

            if not (ryan_gets_need or wife_gets_need):
                continue

            # Find matching players
            ryan_gives = [v for v in ryan_values if v.position == ryan_give_pos]
            wife_gives = [v for v in wife_values if v.position == wife_give_pos]

            for rp in ryan_gives:
                if rp.final_value < 5:  # Skip low value
                    continue

                for wp in wife_gives:
                    if wp.final_value < 5:
                        continue

                    diff = abs(rp.final_value - wp.final_value)
                    if diff <= max_diff:
                        trades.append({
                            "ryan_gives": rp,
                            "ryan_receives": wp,
                            "wife_gives": wp,
                            "wife_receives": rp,
                            "value_diff": rp.final_value - wp.final_value,
                            "ryan_gets_need": ryan_gets_need,
                            "wife_gets_need": wife_gets_need,
                            "mutually_beneficial": ryan_gets_need and wife_gets_need,
                        })

    # Sort by mutual benefit, then by value closeness
    trades.sort(key=lambda x: (
        not x["mutually_beneficial"],
        abs(x["value_diff"])
    ))

    return trades[:20]

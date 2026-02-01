"""
Draft utilities for fantasy football live draft assistant.

Includes:
- Value Over Replacement (VOR) calculations
- Position scarcity analysis
- Best available recommendations
- Two-team draft coordination
"""

import polars as pl
from typing import Optional
from utils.db import get_connection, read_sqlite_robust


# Default roster settings (standard ESPN 12-team league)
# Adjust based on your league settings
ROSTER_SLOTS = {
    "QB": 1,
    "RB": 2,
    "WR": 2,
    "TE": 1,
    "FLEX": 1,  # RB/WR/TE
    "D/ST": 1,
    "K": 1,
    "BENCH": 6,
}

# Draft target composition (total players to draft per position)
DRAFT_TARGETS = {
    "QB": 2,
    "RB": 5,
    "WR": 5,
    "TE": 2,
    "D/ST": 1,
    "K": 1,
}

# Replacement level: position rank where "replacement" begins
# Based on 12-team league, these are roughly the last starter at each position
REPLACEMENT_LEVEL = {
    "QB": 12,   # QB12 is the last starting QB
    "RB": 24,   # RB24 (12 teams * 2 RB slots)
    "WR": 24,   # WR24 (12 teams * 2 WR slots)
    "TE": 12,   # TE12
    "K": 12,
    "D/ST": 12,
}


def load_projections() -> pl.DataFrame:
    """Load 2026 projections from database."""
    conn = get_connection()
    df = read_sqlite_robust("SELECT * FROM gold_projections_2026", conn)
    conn.close()
    return df.sort("proj_total_points_2026", descending=True)


def calculate_replacement_values(projections: pl.DataFrame) -> dict[str, float]:
    """
    Calculate the replacement level points for each position.
    Replacement value = projected points of the Nth ranked player at position.
    """
    replacement_values = {}

    for pos, level in REPLACEMENT_LEVEL.items():
        pos_players = projections.filter(pl.col("position") == pos)

        if len(pos_players) >= level:
            # Get the replacement level player's projected points
            replacement_values[pos] = pos_players["proj_total_points_2026"][level - 1]
        else:
            # Not enough players, use the last one or 0
            if len(pos_players) > 0:
                replacement_values[pos] = pos_players["proj_total_points_2026"][-1]
            else:
                replacement_values[pos] = 0.0

    return replacement_values


def add_vor_to_projections(projections: pl.DataFrame) -> pl.DataFrame:
    """
    Add Value Over Replacement (VOR) column to projections.
    VOR = Player's projected points - Replacement level points for their position
    """
    replacement_values = calculate_replacement_values(projections)

    # Create a mapping expression for VOR calculation
    vor_expr = pl.lit(0.0)
    for pos, repl_val in replacement_values.items():
        vor_expr = pl.when(pl.col("position") == pos).then(
            pl.col("proj_total_points_2026") - repl_val
        ).otherwise(vor_expr)

    return projections.with_columns(vor_expr.alias("vor"))


def get_best_available(
    projections: pl.DataFrame,
    taken_players: set[str],
    position: Optional[str] = None,
    limit: int = 10,
    sort_by: str = "vor"
) -> pl.DataFrame:
    """
    Get best available players not yet drafted.

    Args:
        projections: DataFrame with player projections (should have VOR column)
        taken_players: Set of player names already drafted
        position: Optional position filter (QB, RB, WR, TE, K, D/ST)
        limit: Number of players to return
        sort_by: Column to sort by ('vor' or 'proj_total_points_2026')

    Returns:
        DataFrame of best available players
    """
    available = projections.filter(~pl.col("player_name").is_in(list(taken_players)))

    if position:
        available = available.filter(pl.col("position") == position.upper())

    return available.sort(sort_by, descending=True).head(limit)


def calculate_position_scarcity(
    projections: pl.DataFrame,
    taken_players: set[str],
    top_n: int = 5
) -> dict[str, dict]:
    """
    Calculate position scarcity metrics.

    Returns dict with:
    - remaining_elite: count of top-N players still available
    - avg_vor_available: average VOR of available players
    - next_best_vor: VOR of the next best available player
    - scarcity_alert: True if position is becoming scarce
    """
    scarcity = {}
    available = projections.filter(~pl.col("player_name").is_in(list(taken_players)))

    for pos in ["QB", "RB", "WR", "TE"]:
        pos_all = projections.filter(pl.col("position") == pos)
        pos_avail = available.filter(pl.col("position") == pos)

        # Count elite players (top N at position) still available
        elite_names = set(pos_all.head(top_n)["player_name"].to_list())
        elite_available = pos_avail.filter(pl.col("player_name").is_in(elite_names))

        # Get next best available
        next_best_vor = pos_avail["vor"][0] if len(pos_avail) > 0 else 0

        # Average VOR of remaining players
        avg_vor = pos_avail["vor"].mean() if len(pos_avail) > 0 else 0

        # Scarcity alert if less than 2 elite players remain
        scarcity_alert = len(elite_available) <= 1

        scarcity[pos] = {
            "remaining_elite": len(elite_available),
            "total_available": len(pos_avail),
            "avg_vor_available": avg_vor,
            "next_best_vor": next_best_vor,
            "scarcity_alert": scarcity_alert,
        }

    return scarcity


def get_positional_needs(
    my_roster: list[dict],
    targets: dict[str, int] = DRAFT_TARGETS
) -> dict[str, int]:
    """
    Calculate remaining positional needs based on current roster.

    Returns dict of position -> count needed
    """
    current_counts = {}
    for player in my_roster:
        pos = player.get("position", "?")
        current_counts[pos] = current_counts.get(pos, 0) + 1

    needs = {}
    for pos, target in targets.items():
        current = current_counts.get(pos, 0)
        remaining = max(0, target - current)
        if remaining > 0:
            needs[pos] = remaining

    return needs


def recommend_pick(
    projections: pl.DataFrame,
    taken_players: set[str],
    my_roster: list[dict],
    weight_vor: float = 0.7,
    weight_need: float = 0.3
) -> pl.DataFrame:
    """
    Recommend best picks considering both VOR and team needs.

    Returns DataFrame with recommendations and reasoning.
    """
    available = projections.filter(~pl.col("player_name").is_in(list(taken_players)))
    needs = get_positional_needs(my_roster)
    scarcity = calculate_position_scarcity(projections, taken_players)

    recommendations = []

    for row in available.head(30).iter_rows(named=True):
        pos = row["position"]
        vor = row.get("vor", 0) or 0

        # Base score from VOR
        score = vor * weight_vor

        # Bonus for positions we need
        if pos in needs and needs[pos] > 0:
            score += 20 * weight_need * needs[pos]

        # Bonus for scarce positions
        if pos in scarcity and scarcity[pos]["scarcity_alert"]:
            score += 15 * weight_need

        reason = []
        if vor > 50:
            reason.append("Elite VOR")
        if pos in needs and needs[pos] > 0:
            reason.append(f"Need {pos}")
        if pos in scarcity and scarcity[pos]["scarcity_alert"]:
            reason.append(f"{pos} scarce")

        recommendations.append({
            "player_name": row["player_name"],
            "position": pos,
            "proj_pts": row["proj_total_points_2026"],
            "vor": vor,
            "rec_score": score,
            "reason": ", ".join(reason) if reason else "Best available",
        })

    return pl.DataFrame(recommendations).sort("rec_score", descending=True)


def format_player_display(row: dict, show_vor: bool = True) -> str:
    """Format a player row for display."""
    name = row.get("player_name", "?")
    pos = row.get("position", "?")
    pts = row.get("proj_total_points_2026", 0) or row.get("proj_pts", 0)
    vor = row.get("vor", 0)

    if show_vor and vor:
        return f"{name:<25} {pos:<4} {pts:>6.1f} pts  VOR: {vor:>+6.1f}"
    else:
        return f"{name:<25} {pos:<4} {pts:>6.1f} pts"


# =============================================================================
# ADP (Average Draft Position) Functions
# =============================================================================

def load_adp() -> pl.DataFrame:
    """
    Load ADP data from FantasyPros ECR (redraft-overall rankings).
    ECR = Expert Consensus Ranking, which closely mirrors ADP.
    """
    conn = get_connection()
    df = read_sqlite_robust(
        """
        SELECT
            player as player_name,
            pos as position,
            team,
            ecr as adp,
            sd as adp_std,
            best as adp_best,
            worst as adp_worst
        FROM bronze_ff_rankings
        WHERE page_type = 'redraft-overall'
        ORDER BY ecr
        """,
        conn
    )
    conn.close()

    # Add ADP rank (1-indexed position in draft)
    df = df.with_row_index("adp_rank", offset=1)
    return df


def add_adp_to_projections(projections: pl.DataFrame) -> pl.DataFrame:
    """
    Add ADP data to projections DataFrame.
    Joins on player_name with fuzzy matching fallback.
    """
    adp = load_adp()

    # Join on exact player name match
    merged = projections.join(
        adp.select(["player_name", "adp", "adp_rank", "adp_std"]),
        on="player_name",
        how="left"
    )

    return merged


def analyze_pick_value(
    player_name: str,
    pick_number: int,
    projections: pl.DataFrame
) -> dict:
    """
    Analyze whether a pick is a value, reach, or fair.

    Returns dict with:
    - adp: Player's ADP
    - pick_number: When they were picked
    - adp_diff: pick_number - adp (negative = value, positive = reach)
    - assessment: 'VALUE', 'REACH', 'FAIR'
    """
    player_row = projections.filter(pl.col("player_name") == player_name)

    if len(player_row) == 0:
        return {
            "player_name": player_name,
            "adp": None,
            "pick_number": pick_number,
            "adp_diff": None,
            "assessment": "UNKNOWN"
        }

    adp = player_row["adp"][0] if "adp" in player_row.columns else None

    if adp is None:
        return {
            "player_name": player_name,
            "adp": None,
            "pick_number": pick_number,
            "adp_diff": None,
            "assessment": "NO ADP"
        }

    adp_diff = pick_number - adp

    # Thresholds for value/reach (can be tuned)
    if adp_diff <= -10:
        assessment = "GREAT VALUE"
    elif adp_diff <= -3:
        assessment = "VALUE"
    elif adp_diff >= 10:
        assessment = "BIG REACH"
    elif adp_diff >= 3:
        assessment = "REACH"
    else:
        assessment = "FAIR"

    return {
        "player_name": player_name,
        "adp": adp,
        "pick_number": pick_number,
        "adp_diff": adp_diff,
        "assessment": assessment
    }


def get_value_picks(
    projections: pl.DataFrame,
    taken_players: set[str],
    current_pick: int,
    window: int = 20
) -> pl.DataFrame:
    """
    Find players who are available past their ADP (value picks).

    Args:
        projections: DataFrame with ADP data
        taken_players: Set of already drafted player names
        current_pick: Current pick number in draft
        window: How many picks ahead to look for value

    Returns:
        DataFrame of value picks sorted by ADP difference
    """
    if "adp" not in projections.columns:
        return pl.DataFrame()

    available = projections.filter(
        (~pl.col("player_name").is_in(list(taken_players))) &
        (pl.col("adp").is_not_null())
    )

    # Find players whose ADP is less than current pick (should have been taken)
    value_picks = available.filter(
        pl.col("adp") < current_pick
    ).with_columns(
        (current_pick - pl.col("adp")).alias("adp_value")
    ).sort("adp_value", descending=True)

    return value_picks.head(window)


def get_upcoming_targets(
    projections: pl.DataFrame,
    taken_players: set[str],
    current_pick: int,
    picks_until_next: int = 12
) -> pl.DataFrame:
    """
    Find players likely to be available at your next pick.

    Identifies players whose ADP falls between current_pick and
    current_pick + picks_until_next (your next pick in snake draft).
    """
    if "adp" not in projections.columns:
        return pl.DataFrame()

    available = projections.filter(
        (~pl.col("player_name").is_in(list(taken_players))) &
        (pl.col("adp").is_not_null())
    )

    # Players in the "might still be there" window
    targets = available.filter(
        (pl.col("adp") >= current_pick) &
        (pl.col("adp") <= current_pick + picks_until_next)
    ).sort("adp")

    return targets


def format_adp_display(row: dict) -> str:
    """Format a player row with ADP info for display."""
    name = row.get("player_name", "?")
    pos = row.get("position", "?")
    adp = row.get("adp")
    vor = row.get("vor", 0) or 0

    adp_str = f"ADP:{adp:>5.1f}" if adp else "ADP:  N/A"
    return f"{name:<25} {pos:<4} {adp_str}  VOR:{vor:>+6.1f}"


# =============================================================================
# Trade Value Calculator
# =============================================================================

def get_pick_value(pick_number: int, total_picks: int = 192) -> float:
    """
    Calculate the trade value of a draft pick.

    Uses an exponential decay model where early picks are worth significantly
    more than later picks. Based on expected VOR at each pick position.

    Formula: value = base_value * decay^(pick - 1)
    - Pick 1 = 100 points
    - Pick 12 ≈ 50 points (half value by end of round 1)
    - Pick 24 ≈ 25 points
    - etc.

    Args:
        pick_number: The overall pick number (1-indexed)
        total_picks: Total picks in the draft (default 192 for 12-team, 16 rounds)

    Returns:
        Trade value points for this pick
    """
    if pick_number < 1:
        return 0.0
    if pick_number > total_picks:
        return 1.0  # Minimal value for late picks

    # Exponential decay: value halves roughly every 12 picks
    base_value = 100.0
    decay_rate = 0.945  # Tuned so pick 12 ≈ 50, pick 24 ≈ 25

    value = base_value * (decay_rate ** (pick_number - 1))
    return max(value, 1.0)  # Minimum value of 1


def get_pick_value_table(num_rounds: int = 16, num_teams: int = 12) -> list[dict]:
    """
    Generate a complete pick value table for the draft.

    Returns list of dicts with pick info and values.
    """
    total_picks = num_rounds * num_teams
    table = []

    for pick in range(1, total_picks + 1):
        round_num = (pick - 1) // num_teams + 1
        pick_in_round = (pick - 1) % num_teams + 1
        value = get_pick_value(pick, total_picks)

        table.append({
            "overall_pick": pick,
            "round": round_num,
            "pick_in_round": pick_in_round,
            "value": value,
        })

    return table


def evaluate_trade(
    giving_picks: list[int],
    receiving_picks: list[int],
    total_picks: int = 192
) -> dict:
    """
    Evaluate a trade of draft picks.

    Args:
        giving_picks: List of overall pick numbers you're giving up
        receiving_picks: List of overall pick numbers you're receiving
        total_picks: Total picks in draft

    Returns:
        dict with trade analysis:
        - giving_value: Total value of picks given
        - receiving_value: Total value of picks received
        - net_value: receiving - giving (positive = good trade for you)
        - verdict: 'WIN', 'LOSS', or 'FAIR'
    """
    giving_value = sum(get_pick_value(p, total_picks) for p in giving_picks)
    receiving_value = sum(get_pick_value(p, total_picks) for p in receiving_picks)
    net_value = receiving_value - giving_value

    # Determine verdict with some tolerance for "fair"
    if net_value > 5:
        verdict = "WIN"
    elif net_value < -5:
        verdict = "LOSS"
    else:
        verdict = "FAIR"

    return {
        "giving_picks": giving_picks,
        "receiving_picks": receiving_picks,
        "giving_value": giving_value,
        "receiving_value": receiving_value,
        "net_value": net_value,
        "verdict": verdict,
    }


def calculate_pick_from_round(
    round_num: int,
    pick_in_round: int,
    num_teams: int = 12
) -> int:
    """
    Convert round and pick-in-round to overall pick number.

    Args:
        round_num: Round number (1-indexed)
        pick_in_round: Pick within the round (1-indexed)
        num_teams: Number of teams in league

    Returns:
        Overall pick number
    """
    return (round_num - 1) * num_teams + pick_in_round


def parse_pick_notation(notation: str, num_teams: int = 12) -> int | None:
    """
    Parse pick notation like '1.05', '2.12', or '15' into overall pick number.

    Formats supported:
    - '1.05' -> Round 1, Pick 5 -> Overall pick 5
    - '3.1' -> Round 3, Pick 1 -> Overall pick 25
    - '15' -> Overall pick 15

    Returns None if parsing fails.
    """
    notation = notation.strip()

    # Try round.pick format (e.g., "1.05", "2.12")
    if '.' in notation:
        parts = notation.split('.')
        if len(parts) == 2:
            try:
                round_num = int(parts[0])
                pick_in_round = int(parts[1])
                return calculate_pick_from_round(round_num, pick_in_round, num_teams)
            except ValueError:
                return None

    # Try plain overall pick number
    try:
        return int(notation)
    except ValueError:
        return None


def find_equivalent_picks(
    pick_number: int,
    num_teams: int = 12,
    total_picks: int = 192,
    tolerance: float = 2.0
) -> list[tuple[int, int]]:
    """
    Find combinations of 2 later picks that equal the value of one earlier pick.

    Useful for determining fair trades like "Pick 10 for Picks 25 + 40".

    Args:
        pick_number: The pick to find equivalents for
        num_teams: Number of teams
        total_picks: Total picks in draft
        tolerance: How close the values need to be (default 2 points)

    Returns:
        List of tuples (pick_a, pick_b) where value(a) + value(b) ≈ value(pick_number)
    """
    target_value = get_pick_value(pick_number, total_picks)
    equivalents = []

    # Search for pairs of picks that sum to target value
    for pick_a in range(pick_number + 1, total_picks + 1):
        value_a = get_pick_value(pick_a, total_picks)

        # Need remaining value from a second pick
        needed_value = target_value - value_a
        if needed_value < 1:
            continue

        # Find pick_b that provides the needed value
        for pick_b in range(pick_a + 1, total_picks + 1):
            value_b = get_pick_value(pick_b, total_picks)
            combined = value_a + value_b

            if abs(combined - target_value) <= tolerance:
                equivalents.append((pick_a, pick_b))

            # Once value_b is too small, no point continuing
            if value_b < needed_value - tolerance:
                break

        # Limit results
        if len(equivalents) >= 10:
            break

    return equivalents

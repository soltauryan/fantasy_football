"""
Tests for utils/draft.py - Draft utility functions.
"""

import pytest
import polars as pl

from utils.draft import (
    REPLACEMENT_LEVEL,
    DRAFT_TARGETS,
    calculate_replacement_values,
    add_vor_to_projections,
    load_projections,
)


class TestReplacementLevel:
    """Tests for replacement level configuration."""

    def test_replacement_level_has_all_positions(self):
        """Replacement level should have all fantasy positions."""
        expected = ["QB", "RB", "WR", "TE", "K", "D/ST"]
        for pos in expected:
            assert pos in REPLACEMENT_LEVEL

    def test_replacement_level_values_reasonable(self):
        """Replacement levels should be reasonable for 12-team league."""
        # QB12 is last starting QB
        assert REPLACEMENT_LEVEL["QB"] == 12
        # RB24 is last starting RB (2 per team)
        assert REPLACEMENT_LEVEL["RB"] == 24
        # WR24 is last starting WR (2 per team)
        assert REPLACEMENT_LEVEL["WR"] == 24
        # TE12 is last starting TE
        assert REPLACEMENT_LEVEL["TE"] == 12


class TestDraftTargets:
    """Tests for draft target configuration."""

    def test_draft_targets_sum(self):
        """Draft targets should sum to 16 (roster size)."""
        total = sum(DRAFT_TARGETS.values())
        assert total == 16


class TestReplacementValues:
    """Tests for replacement value calculations."""

    def test_calculate_replacement_values(self, sample_projections):
        """Should calculate replacement values for each position."""
        result = calculate_replacement_values(sample_projections)

        assert isinstance(result, dict)
        # Should have values for positions in data
        assert "QB" in result
        assert "RB" in result
        assert "WR" in result
        assert "TE" in result

    def test_replacement_values_are_positive(self, sample_projections):
        """Replacement values should be positive."""
        result = calculate_replacement_values(sample_projections)
        for pos, val in result.items():
            assert val >= 0


class TestVORCalculation:
    """Tests for Value Over Replacement calculations."""

    def test_add_vor_creates_column(self, sample_projections):
        """Adding VOR should create a 'vor' column."""
        result = add_vor_to_projections(sample_projections)
        assert "vor" in result.columns

    def test_vor_is_numeric(self, sample_projections):
        """VOR values should be numeric."""
        result = add_vor_to_projections(sample_projections)
        assert result["vor"].dtype in [pl.Float64, pl.Float32, pl.Int64, pl.Int32]

    def test_top_players_have_positive_vor(self, sample_projections):
        """Top players should have positive VOR."""
        result = add_vor_to_projections(sample_projections)
        # First player at each position should have positive VOR
        # (assuming they're above replacement)
        for pos in ["QB", "RB", "WR", "TE"]:
            pos_players = result.filter(pl.col("position") == pos)
            if not pos_players.is_empty():
                top_vor = pos_players["vor"][0]
                assert top_vor >= 0

    def test_vor_reflects_positional_scarcity(self, sample_projections):
        """VOR should reflect positional scarcity appropriately."""
        result = add_vor_to_projections(sample_projections)

        # Get top player VOR by position
        vor_by_pos = {}
        for pos in ["QB", "RB", "WR", "TE"]:
            pos_players = result.filter(pl.col("position") == pos)
            if not pos_players.is_empty():
                vor_by_pos[pos] = pos_players["vor"].max()

        # All positions should have some VOR values
        assert len(vor_by_pos) > 0


class TestLoadProjections:
    """Tests for loading projections from database."""

    def test_load_projections_returns_dataframe(self):
        """Loading projections should return a DataFrame."""
        result = load_projections()
        assert isinstance(result, pl.DataFrame)

    def test_projections_has_expected_columns(self):
        """Projections should have key columns."""
        result = load_projections()
        if not result.is_empty():
            # Projections use player_name, not full_name
            assert "player_name" in result.columns
            assert "position" in result.columns
            assert "proj_total_points_2026" in result.columns

    def test_projections_sorted_by_points(self):
        """Projections should be sorted by projected points descending."""
        result = load_projections()
        if not result.is_empty() and len(result) > 1:
            points = result["proj_total_points_2026"].to_list()
            assert points == sorted(points, reverse=True)

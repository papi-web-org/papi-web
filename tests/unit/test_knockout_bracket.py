"""Unit tests for the knock-out bracket arithmetic (no DB, no framework)."""

import pytest

from data.pairings.knockout_helpers.bracket import (
    advance_pairs,
    bracket_size,
    first_round_pairs,
    round_count,
    seed_order,
)


@pytest.mark.unit
class TestRoundCount:
    def test_powers_of_two(self):
        assert round_count(2) == 1
        assert round_count(4) == 2
        assert round_count(8) == 3
        assert round_count(16) == 4
        assert round_count(32) == 5
        assert round_count(128) == 7

    def test_rounds_up_to_next_power(self):
        # Manual ch. 3.4: 47 players -> 6 rounds (above 32).
        assert round_count(47) == 6
        assert round_count(33) == 6
        assert round_count(3) == 2
        assert round_count(52) == 6

    def test_degenerate(self):
        assert round_count(0) == 0
        assert round_count(1) == 0


@pytest.mark.unit
class TestBracketSize:
    def test_next_power_of_two(self):
        assert bracket_size(8) == 8
        assert bracket_size(9) == 16
        assert bracket_size(47) == 64
        assert bracket_size(52) == 64


@pytest.mark.unit
class TestSeedOrder:
    def test_small_brackets(self):
        assert seed_order(2) == [1, 2]
        assert seed_order(4) == [1, 4, 2, 3]
        assert seed_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]

    def test_top_seeds_in_opposite_halves(self):
        for k in range(1, 8):
            size = 2**k
            order = seed_order(size)
            assert sorted(order) == list(range(1, size + 1))
            # Seeds 1 and 2 can only meet in the final -> opposite halves.
            half = size // 2
            assert (order.index(1) < half) != (order.index(2) < half)

    def test_every_first_round_pair_sums_to_size_plus_one(self):
        order = seed_order(16)
        for i in range(0, 16, 2):
            assert order[i] + order[i + 1] == 17

    def test_rejects_non_power_of_two(self):
        with pytest.raises(ValueError):
            seed_order(6)


@pytest.mark.unit
class TestFirstRoundPairs:
    def test_full_bracket_no_byes(self):
        pairs = first_round_pairs(8)
        assert pairs == [(1, 8), (4, 5), (2, 7), (3, 6)]
        assert all(low is not None for _, low in pairs)

    def test_byes_go_to_top_seeds(self):
        # 6 players in a bracket of 8: seeds 7 and 8 are virtual, so the
        # two strongest (seeds 1 and 2) get the byes.
        pairs = first_round_pairs(6)
        assert pairs == [(1, None), (4, 5), (2, None), (3, 6)]
        bye_seeds = {high for high, low in pairs if low is None}
        assert bye_seeds == {1, 2}

    def test_bye_count_matches_padding(self):
        for n in range(2, 65):
            pairs = first_round_pairs(n)
            byes = sum(1 for _, low in pairs if low is None)
            assert byes == bracket_size(n) - n
            # A bye never faces a bye: None is always the second element.
            assert all(high is not None for high, _ in pairs)


@pytest.mark.unit
class TestAdvancePairs:
    def test_adjacent_winners_meet(self):
        assert advance_pairs(['a', 'b', 'c', 'd']) == [('a', 'b'), ('c', 'd')]

    def test_final(self):
        assert advance_pairs([1, 2]) == [(1, 2)]

    def test_rejects_non_power_of_two(self):
        with pytest.raises(ValueError):
            advance_pairs([1, 2, 3])

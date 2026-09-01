"""Pure grouped-seeding arithmetic for knock-outs."""

from data.pairings.knockout_helpers.grouping import (
    form_groups,
    grouped_dimensions,
    grouped_leaves,
    grouped_round_count,
)


class TestFormGroups:
    def test_buckets_in_first_appearance_order(self):
        # Members are given strongest first; a group ranks by its strongest
        # member, so its first appearance fixes its order.
        members: list[tuple[int, str | None]] = [
            (1, 'A'),
            (2, 'B'),
            (3, 'A'),
            (4, 'B'),
            (5, 'A'),
        ]
        assert form_groups(members) == [[1, 3, 5], [2, 4]]

    def test_unaffiliated_pool_into_one_group(self):
        members = [(1, 'A'), (2, None), (3, 'A'), (4, None)]
        # The None members share one 'unaffiliated' group, ranked by first
        # appearance (after A, whose member came first).
        assert form_groups(members) == [[1, 3], [2, 4]]

    def test_all_unaffiliated_is_one_group(self):
        assert form_groups([(1, None), (2, None), (3, None)]) == [[1, 2, 3]]

    def test_empty(self):
        assert form_groups([]) == []


class TestDimensions:
    def test_powers_of_two(self):
        assert grouped_dimensions([[1, 2], [3, 4]]) == (2, 2)
        assert grouped_dimensions([[1, 2, 3], [4]]) == (2, 4)  # M pads to 4
        assert grouped_dimensions([[1], [2], [3]]) == (4, 1)  # K pads to 4
        assert grouped_dimensions([]) == (0, 0)

    def test_round_count(self):
        assert grouped_round_count([[1, 2], [3, 4]]) == 2  # K*M = 4
        assert grouped_round_count([[1, 2, 3], [4]]) == 3  # K*M = 8
        assert grouped_round_count([[1], [2], [3]]) == 2  # K*M = 4
        assert grouped_round_count([[1]]) == 0


class TestGroupedLeaves:
    def test_two_equal_groups_play_themselves_first(self):
        # groups meet only after each has resolved its own sub-bracket.
        leaves = grouped_leaves([[1, 2], [3, 4]])
        assert leaves == [1, 2, 3, 4]
        pairs = list(zip(leaves[::2], leaves[1::2]))
        assert pairs == [(1, 2), (3, 4)]  # each round-one match is intra-group

    def test_four_equal_groups_top_two_meet_in_the_final(self):
        # seed_order(4) = [1, 4, 2, 3]: block order puts group 1 and group 2 in
        # opposite halves, so the two strongest groups can only meet at the end.
        leaves = grouped_leaves([[1, 2], [3, 4], [5, 6], [7, 8]])
        assert leaves == [1, 2, 7, 8, 3, 4, 5, 6]
        pairs = list(zip(leaves[::2], leaves[1::2]))
        assert pairs == [(1, 2), (7, 8), (3, 4), (5, 6)]  # all intra-group

    def test_ragged_group_sizes_pad_with_byes(self):
        # A group of 3 pads to M = 4 (one virtual); a group of 1 pads to 4
        # (three virtuals — it byes through the group stage).
        leaves = grouped_leaves([[1, 2, 3], [4]])
        # inner seed_order(4) = [1, 4, 2, 3] over each group's members.
        assert leaves == [1, None, 2, 3, 4, None, None, None]

    def test_non_power_of_two_group_count_adds_a_phantom_group(self):
        # Three groups pad to K = 4; the phantom block is all virtual, so the
        # group facing it advances for free at the inter-group stage.
        leaves = grouped_leaves([[1, 2], [3, 4], [5, 6]])
        # outer seed_order(4) = [1, 4, 2, 3]; block for group 4 is phantom.
        assert leaves == [1, 2, None, None, 3, 4, 5, 6]

    def test_length_is_k_times_m(self):
        groups = [[1, 2, 3], [4, 5], [6], [7, 8, 9, 10], [11]]
        k, m = grouped_dimensions(groups)
        assert len(grouped_leaves(groups)) == k * m

    def test_every_real_member_appears_exactly_once(self):
        groups = [[1, 2, 3], [4], [5, 6]]
        leaves = grouped_leaves(groups)
        real = sorted(x for x in leaves if x is not None)
        assert real == [1, 2, 3, 4, 5, 6]

    def test_empty(self):
        assert grouped_leaves([]) == []

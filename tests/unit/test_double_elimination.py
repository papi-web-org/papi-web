"""Structural tests for the pure double-elimination bracket schedule."""

from typing import TYPE_CHECKING, cast

from data.pairings import double_elimination as de
from data.pairings.double_elimination import (
    GRAND_FINAL,
    GRAND_FINAL_RESET,
    LOSERS,
    WINNERS,
    LoserOf,
    Seed,
    WinnerOf,
)

if TYPE_CHECKING:
    from data.tournament import Tournament


def _by_id(matches):
    return {m.id: m for m in matches}


class TestRoundCount:
    def test_powers_of_two(self):
        assert de.round_count(2) == 2  # k=1: WB final == grand final path
        assert de.round_count(4) == 4  # k=2
        assert de.round_count(8) == 6  # k=3
        assert de.round_count(16) == 8  # k=4

    def test_non_powers_pad_up(self):
        # 5..8 all sit in the size-8 bracket (k=3).
        assert de.round_count(5) == 6
        assert de.round_count(6) == 6
        assert de.round_count(7) == 6

    def test_reset_adds_one_round(self):
        assert de.round_count(8, with_reset=True) == 7
        assert de.round_count(4, with_reset=True) == 5

    def test_too_few(self):
        assert de.round_count(1) == 0
        assert de.schedule(1) == []


class TestFourPlayers:
    """N=4 (k=2): the smallest non-trivial double elimination."""

    def setup_method(self):
        self.matches = de.schedule(4)
        self.by_id = _by_id(self.matches)

    def test_match_set(self):
        assert set(self.by_id) == {
            'W1.0',
            'W1.1',
            'W2.0',  # winners' final
            'L1.0',  # losers' round 1 (the two WB round-1 losers)
            'L2.0',  # losers' final
            GRAND_FINAL,
        }

    def test_winners_round_one_seeds(self):
        # Standard seeding: 1v4 and 2v3, strongest seed leads.
        assert (self.by_id['W1.0'].a, self.by_id['W1.0'].b) == (Seed(1), Seed(4))
        assert (self.by_id['W1.1'].a, self.by_id['W1.1'].b) == (Seed(2), Seed(3))

    def test_winners_final_from_winners(self):
        wf = self.by_id['W2.0']
        assert wf.bracket == WINNERS
        assert {wf.a, wf.b} == {WinnerOf('W1.0'), WinnerOf('W1.1')}

    def test_losers_round_one_from_dropouts(self):
        lb = self.by_id['L1.0']
        assert lb.bracket == LOSERS
        assert {lb.a, lb.b} == {LoserOf('W1.0'), LoserOf('W1.1')}

    def test_losers_final_mixes_survivor_and_winners_final_loser(self):
        lf = self.by_id['L2.0']
        assert {lf.a, lf.b} == {WinnerOf('L1.0'), LoserOf('W2.0')}

    def test_grand_final(self):
        gf = self.by_id[GRAND_FINAL]
        assert gf.bracket == GRAND_FINAL
        assert {gf.a, gf.b} == {WinnerOf('W2.0'), WinnerOf('L2.0')}

    def test_rounds(self):
        rounds = {m.id: m.round for m in self.matches}
        assert rounds == {
            'W1.0': 1,
            'W1.1': 1,
            'W2.0': 2,
            'L1.0': 2,
            'L2.0': 3,
            GRAND_FINAL: 4,
        }


class TestEightPlayers:
    """N=8 (k=3): exercises both a minor and a major losers' round."""

    def setup_method(self):
        self.matches = de.schedule(8)
        self.by_id = _by_id(self.matches)

    def test_bracket_match_counts(self):
        winners = [m for m in self.matches if m.bracket == WINNERS]
        losers = [m for m in self.matches if m.bracket == LOSERS]
        assert len(winners) == 4 + 2 + 1  # WB rounds of 4, 2, 1
        assert len(losers) == 2 + 2 + 1 + 1  # L1 minor, L2 major, L3 minor, L4

    def test_round_layout(self):
        by_round: dict[int, set[str]] = {}
        for m in self.matches:
            by_round.setdefault(m.round, set()).add(m.id)
        assert by_round[1] == {'W1.0', 'W1.1', 'W1.2', 'W1.3'}
        assert by_round[2] == {'W2.0', 'W2.1', 'L1.0', 'L1.1'}
        assert by_round[3] == {'L2.0', 'L2.1'}
        assert by_round[4] == {'W3.0', 'L3.0'}  # WB final + LB minor
        assert by_round[5] == {'L4.0'}  # LB final
        assert by_round[6] == {GRAND_FINAL}

    def test_major_round_drops_are_reversed(self):
        # WB round-2 losers drop into L2 reversed: L2.0 takes W2.1's loser,
        # L2.1 takes W2.0's loser -- so a survivor does not immediately meet
        # the player who knocked their neighbour out in the same slot.
        assert self.by_id['L2.0'].b == LoserOf('W2.1')
        assert self.by_id['L2.1'].b == LoserOf('W2.0')

    def test_losers_minor_round_from_survivors(self):
        assert {self.by_id['L3.0'].a, self.by_id['L3.0'].b} == {
            WinnerOf('L2.0'),
            WinnerOf('L2.1'),
        }

    def test_grand_final_from_both_champions(self):
        gf = self.by_id[GRAND_FINAL]
        assert {gf.a, gf.b} == {WinnerOf('W3.0'), WinnerOf('L4.0')}


class TestReset:
    def test_reset_match_present_and_last(self):
        matches = de.schedule(8, with_reset=True)
        by_id = _by_id(matches)
        assert GRAND_FINAL_RESET in by_id
        reset = by_id[GRAND_FINAL_RESET]
        assert reset.round == 7
        # The reset is the same two finalists over again.
        assert reset.a == by_id[GRAND_FINAL].a
        assert reset.b == by_id[GRAND_FINAL].b

    def test_no_reset_by_default(self):
        assert GRAND_FINAL_RESET not in _by_id(de.schedule(8))


class TestGroupedResetGate:
    def test_reset_round_uses_grouped_bracket_size(self):
        from types import SimpleNamespace

        from data.pairings.knockout import (
            DoubleEliminationEngine,
            DoubleEliminationResetSetting,
        )

        class Engine(DoubleEliminationEngine):
            def _participant_count(self, tournament):
                return 15

            def _grouped_leaves(self, tournament):
                return list(range(1, 16)) + [None] * 17

            def _match_participants(self, tournament, by_id, match_id, cache):
                return (1, None)

            def _match_winner(self, tournament, by_id, match_id, cache):
                return 1

            def _reset_needed(self, tournament, by_id, cache):
                return False

        tournament = SimpleNamespace(
            stored_pairing_settings={DoubleEliminationResetSetting.static_id(): True},
            is_round_finished=lambda round_: True,
        )
        typed_tournament = cast('Tournament', tournament)
        engine = Engine()
        raw_reset_round = de.round_count(15, with_reset=True)
        grouped_reset_round = de.round_count(32, with_reset=True)

        assert raw_reset_round == 9
        assert grouped_reset_round == 11
        assert (
            engine._double_elimination_gate(typed_tournament, raw_reset_round) is None
        )
        message = engine._double_elimination_gate(typed_tournament, grouped_reset_round)
        assert message and 'No reset' in message


class TestStructuralInvariants:
    """Properties that must hold for every bracket size."""

    def test_every_first_round_loser_drops_exactly_once(self):
        for n in (4, 8, 16):
            matches = de.schedule(n)
            winners_r1 = [m for m in matches if m.id.startswith('W1.')]
            dropped = [
                s.match_id
                for m in matches
                for s in (m.a, m.b)
                if isinstance(s, LoserOf)
            ]
            # Every winners' match's loser is dropped exactly once into the LB.
            winners_ids = [m.id for m in matches if m.bracket == WINNERS]
            assert sorted(dropped) == sorted(winners_ids)
            assert len(winners_r1) == n // 2

    def test_sources_reference_earlier_matches(self):
        for n in (4, 8, 16):
            matches = de.schedule(n, with_reset=True)
            ids = {m.id for m in matches}
            for m in matches:
                for s in (m.a, m.b):
                    if isinstance(s, WinnerOf | LoserOf):
                        assert s.match_id in ids

    def test_matches_for_round_orders_winners_before_losers(self):
        matches = de.schedule(8)
        round_two = de.matches_for_round(matches, 2)
        brackets = [m.bracket for m in round_two]
        assert brackets == [WINNERS, WINNERS, LOSERS, LOSERS]  # winners first
        assert {m.id for m in round_two} == {'W2.0', 'W2.1', 'L1.0', 'L1.1'}


class TestEmptyMatchCollapse:
    """The engine's structural resolution of byes and empty matches — a
    losers'-bracket match fed by two byes has no participant, and the
    winner it would feed must count as absent so the downstream match
    collapses to a walkover instead of hanging undecided forever."""

    def _engine(self):
        from data.pairings.knockout import DoubleEliminationEngine

        return DoubleEliminationEngine()

    def test_winner_of_two_byes_losers_match_is_absent(self):
        # Five players in an eight-slot bracket: seeds 6, 7, 8 are virtual.
        # W1.0=(1,8), W1.2=(2,7), W1.3=(3,6) are byes; only W1.1=(4,5) is
        # contested. L1.1 = LoserOf(W1.2) vs LoserOf(W1.3) — both byes, so it
        # is empty, and WinnerOf(L1.1) can never be filled.
        from types import SimpleNamespace

        eng = self._engine()
        by_id = _by_id(de.schedule(5))
        tournament = SimpleNamespace(player_count=5, stored_pairing_settings={})
        cache: dict = {}
        assert eng._match_empty(tournament, by_id, 'L1.1', cache)
        assert eng._source_absent(tournament, by_id, WinnerOf('L1.1'), cache)
        # A match with one real dropout is a bye, not empty — its lone player
        # walks over, so the winner source is present.
        assert not eng._match_empty(tournament, by_id, 'L1.0', cache)
        assert not eng._source_absent(tournament, by_id, WinnerOf('L1.0'), cache)

    def test_empty_match_has_no_loser_to_drop(self):
        from types import SimpleNamespace

        eng = self._engine()
        by_id = _by_id(de.schedule(5))
        tournament = SimpleNamespace(player_count=5, stored_pairing_settings={})
        cache: dict = {}
        # An empty match sends nobody down: its LoserOf is absent too.
        assert eng._source_absent(tournament, by_id, LoserOf('L1.1'), cache)

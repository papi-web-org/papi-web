"""Individual knock-out pairing over a real tournament: seeding + byes at
round one, winners advancing at round two, and the tie gate that refuses
to pair the next round while a match is drawn.

Six players in a bracket of eight: the two top seeds get round-one byes.
"""

import pytest

from data.loader import EventLoader
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import StoredPlayer, StoredTournamentPlayer
from tests.test_config import TestUtils
from utils.enum import Result

EVENT_ID = 'test-knockout-pairing'
TOURNAMENT_NAME = 'knockout'
PLAYER_COUNT = 6


@pytest.mark.unit
class TestIndividualKnockout:
    @pytest.fixture
    def tournament_name(self):
        TestUtils.create_event(EVENT_ID)
        TestUtils.create_tournament(
            EVENT_ID,
            TOURNAMENT_NAME,
            overrides={'rounds': 3, 'current_round': 1, 'pairing': 'KNOCKOUT_STANDARD'},
        )
        with EventDatabase(EVENT_ID, write=True) as database:
            tournament_id = next(
                stored.id
                for stored in database.load_stored_tournaments()
                if stored.name == TOURNAMENT_NAME
            )
            assert tournament_id is not None
            for index in range(PLAYER_COUNT):
                # Descending rating -> starting rank is the order added, so
                # PLAYER00 is seed 1 (strongest), PLAYER05 is seed 6.
                player_id = database.add_stored_player(
                    StoredPlayer(
                        id=None,
                        last_name=f'PLAYER{index:02d}',
                        ratings={1: {'standard': 2000 - index * 10}},
                    )
                )
                database.add_stored_tournament_player(
                    StoredTournamentPlayer(
                        tournament_id=tournament_id, player_id=player_id
                    )
                )
        yield TOURNAMENT_NAME
        TestUtils.delete_event(EVENT_ID)

    def _load(self):
        try:
            EventLoader.unload_event(EVENT_ID)
        except KeyError:
            pass
        # Hold the event so it is not garbage-collected out from under the
        # tournament's weak back-reference.
        self._event = EventLoader().load_event(EVENT_ID)
        return self._event.tournaments_by_name[TOURNAMENT_NAME]

    @staticmethod
    def _board_names(tournament, round_):
        """(white_name, black_name | None) per board of *round_*, in board
        order."""
        result = []
        for board in sorted(tournament.get_round_boards(round_), key=lambda b: b.index):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            result.append(
                (
                    white.last_name if white else None,
                    black.last_name if black else None,
                )
            )
        return result

    def test_round_count_follows_bracket_depth(self, tournament_name):
        tournament = self._load()
        # 6 players -> bracket of 8 -> 3 rounds.
        assert tournament.automatic_rounds == 3

    def _use_higher_seed_white(self, tournament):
        """Pin the colour rule so board-order assertions are deterministic
        (the default rule alternates colours)."""
        from data.pairings.knockout import (
            KnockoutColourRule,
            KnockoutColourRuleSetting,
        )

        tournament.update_pairing_settings(
            {
                KnockoutColourRuleSetting.static_id(): (
                    KnockoutColourRule.HIGHER_SEED_WHITE.value
                )
            }
        )
        return self._load()

    def test_first_round_seeds_bracket_and_byes_top_seeds(self, tournament_name):
        tournament = self._use_higher_seed_white(self._load())
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Bracket first_round_pairs(6) = [(1,None),(4,5),(2,None),(3,6)],
        # but contested matches take the low table numbers in bracket order
        # and the two top-seed byes follow — never interleaved.
        assert self._board_names(tournament, 1) == [
            ('PLAYER03', 'PLAYER04'),  # seed 4 v seed 5
            ('PLAYER02', 'PLAYER05'),  # seed 3 v seed 6
            ('PLAYER00', None),  # seed 1 bye
            ('PLAYER01', None),  # seed 2 bye
        ]

    def test_winners_advance_at_round_two(self, tournament_name):
        tournament = self._use_higher_seed_white(self._load())
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Seed 4 and seed 3 win their games; the two byes advance already.
        by_white = {
            board.white_tournament_player.last_name: board
            for board in tournament.get_round_boards(1)
            if board.black_tournament_player is not None
        }
        tournament.add_result(by_white['PLAYER03'], Result.WIN)
        tournament.add_result(by_white['PLAYER02'], Result.WIN)

        tournament = self._load()
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        # Winners in bracket order: PLAYER00, PLAYER03, PLAYER01, PLAYER02.
        assert self._board_names(tournament, 2) == [
            ('PLAYER00', 'PLAYER03'),
            ('PLAYER01', 'PLAYER02'),
        ]

    @staticmethod
    def _play_round(tournament, round_):
        """Every contested board is won by its higher-seeded player,
        whichever colour they hold (the default colour rule alternates, so
        White is not always the stronger seed); byes already carry their
        result."""
        for board in tournament.get_round_boards(round_):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            if black is None:
                continue
            white_stronger = (
                white.starting_rank_sort_key <= black.starting_rank_sort_key
            )
            tournament.add_result(board, Result.WIN if white_stronger else Result.LOSS)

    def test_advances_all_the_way_to_the_final(self, tournament_name):
        # 6 players -> 3 rounds. This is the case the earlier tests missed:
        # from round 2 on, the knocked-out players have no board, so if they
        # counted towards "round finished" the tournament could never be
        # paired past round 2.
        tournament = self._load()
        for round_ in range(1, 4):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            # Knocked-out players are out, not "to pair".
            assert (
                tournament.get_unpaired_tournament_players(
                    tournament.get_round_boards(round_)
                )
                == []
            )
            if round_ < 3:
                self._play_round(tournament, round_)
                tournament = self._load()
                # Only the still-in players hold the round open, so it can
                # finish and the next round can be paired.
                assert tournament.is_round_finished(round_)
        # The last round is the final: a single game.
        finals = [
            board
            for board in tournament.get_round_boards(3)
            if board.black_tournament_player is not None
        ]
        assert len(finals) == 1

    def test_papi_export_has_no_tie_breaks(self, tournament_name):
        # A knock-out ranks by the round reached, and its configured tie-breaks
        # are Art. 12 advancement criteria, not standings — so none is exported.
        from plugins.ffe.papi_converter import PapiConverter

        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        variables = PapiConverter().tournament_to_papi_data(tournament).variables
        assert variables.tiebreak1 is None
        assert variables.tiebreak2 is None
        assert variables.tiebreak3 is None

    def test_papi_export_gives_knocked_out_players_a_zero_point_bye(
        self, tournament_name
    ):
        # Papi requires every entrant to be paired or given a bye in each played
        # round. A knocked-out player has no board once out, so the export must
        # seat them with a zero-point bye rather than leaving them unpaired —
        # and a zero-point bye so their score is not altered.
        from plugins.ffe.papi_converter import PapiConverter
        from plugins.ffe.papi_mappers import PapiColor, PapiResult

        tournament = self._load()
        for round_ in range(1, 4):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._play_round(tournament, round_)
            tournament = self._load()

        papi_data = PapiConverter().tournament_to_papi_data(tournament)
        by_name = {player.lastName: player for player in papi_data.players}
        # PLAYER05 (seed 6) is knocked out in round 1, so has no board in
        # rounds 2 and 3 — both must be zero-point byes, not unpaired.
        eliminated = by_name['PLAYER05']
        for round_ in (2, 3):
            assert eliminated.rounds[round_].color == PapiColor.BYE
            assert eliminated.rounds[round_].opponent is None
            assert eliminated.rounds[round_].result == PapiResult.UNPLAYED_OR_NOT_PAIRED
            assert eliminated.rounds[round_].to_result() == Result.ZERO_POINT_BYE
        # The champion is never a bye at the final: a real board every round.
        champion = by_name['PLAYER00']
        assert champion.rounds[3].color != PapiColor.UNPAIRED

        # A round-one bye (top seeds sit out) is a zero-point bye too, not a
        # scoring bye with no adversary — else the Papi binary assigns a
        # default adversary and the two round-one byes collide on its Rd01Adv
        # index.
        for seed in ('PLAYER00', 'PLAYER01'):
            first = by_name[seed].rounds[1]
            assert first.color == PapiColor.BYE
            assert first.opponent is None
            assert first.result == PapiResult.UNPLAYED_OR_NOT_PAIRED

    def test_papi_export_writes_a_valid_file(self, tournament_name):
        # End-to-end through the papi-converter binary: the two round-one byes
        # and the eliminated players' byes must not collide on the per-round
        # adversary index.
        import tempfile
        from pathlib import Path

        from common.tool_installer import PapiConverterInstaller
        from plugins.ffe.papi_converter import PapiConverter

        if not PapiConverterInstaller().executable_path.exists():
            pytest.skip('papi-converter binary not installed')

        tournament = self._load()
        for round_ in range(1, 4):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._play_round(tournament, round_)
            tournament = self._load()

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'out.papi'
            PapiConverter().write_papi_file(tournament, target)
            assert target.exists()

    def test_standings_rank_by_round_reached(self, tournament_name):
        # White (the higher seed) wins every game, so seed 1 (PLAYER00)
        # takes the title. Play all three rounds out.
        tournament = self._load()
        for round_ in range(1, 4):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._play_round(tournament, round_)
            tournament = self._load()

        value = {
            player.last_name: tournament.knockout.ranking_value(player, after_round=3)
            for player in tournament.tournament_players
        }
        # rounds = 3; never-beaten champion scores rounds + 1.
        assert value['PLAYER00'] == 4  # champion
        assert value['PLAYER01'] == 3  # lost the final
        assert value['PLAYER02'] == 2  # lost a semi
        assert value['PLAYER03'] == 2  # lost a semi -> tied with PLAYER02
        assert value['PLAYER04'] == 1  # out in round 1
        assert value['PLAYER05'] == 1  # out in round 1

    def test_standing_labels(self, tournament_name):
        tournament = self._load()
        for round_ in range(1, 4):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._play_round(tournament, round_)
            tournament = self._load()

        labels = tournament.knockout.standing_labels(after_round=3)
        by_name = {p.last_name: labels[p.id] for p in tournament.tournament_players}
        assert by_name['PLAYER00'] == 'Winner'
        assert by_name['PLAYER01'] == 'Runner-up'  # lost the final
        assert by_name['PLAYER02'] == 'Out — round 2'  # semi-final
        assert by_name['PLAYER03'] == 'Out — round 2'
        assert by_name['PLAYER04'] == 'Out — round 1'
        assert by_name['PLAYER05'] == 'Out — round 1'

    def test_previous_round_locked_once_next_is_paired(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        self._play_round(tournament, 1)
        tournament = self._load()
        # Round 1 is editable until the next round exists.
        assert tournament.round_is_locked(1) is False
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        # Now round 2 is paired from round 1's results — round 1 is locked,
        # round 2 (the latest) is still editable.
        assert tournament.round_is_locked(1) is True
        assert tournament.round_is_locked(2) is False

    def test_round_names(self, tournament_name):
        # 6 players -> bracket of 8: Quarterfinals, Semifinals, Final.
        tournament = self._load()
        expected = ['Quarterfinals', 'Semifinals', 'Final']
        for round_ in range(1, 4):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            labels = [
                label
                for label, _boards in tournament.round_sections(
                    tournament.get_round_boards(round_)
                )
            ]
            assert labels == [expected[round_ - 1]]
            self._play_round(tournament, round_)
            tournament = self._load()

    def test_bracket_layout(self, tournament_name):
        tournament = self._load()
        for round_ in range(1, 4):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._play_round(tournament, round_)
            tournament = self._load()

        layout = tournament.knockout.layout()
        assert layout.is_double_elimination is False
        assert [section.key for section in layout.sections] == ['main']
        main = layout.sections[0]
        assert [column.name for column in main.columns] == [
            'Quarterfinals',
            'Semifinals',
            'Final',
        ]
        final = main.columns[-1]
        assert len(final.matches) == 1
        final_match = final.matches[0]
        # PLAYER00 (top seed) wins every game -> the champion of the final.
        assert final_match.top.name == 'PLAYER00'
        assert final_match.top.winner is True
        assert final_match.bottom.winner is False
        # The final is fed by the two semi-finals.
        assert final_match.source_top == 'R2.0'
        assert final_match.source_bottom == 'R2.1'

    def test_bracket_shows_full_tournament_from_round_one(self, tournament_name):
        # Only round one is paired; the diagram must still show every round
        # (empty boxes fill in as results come).
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        layout = tournament.knockout.layout()
        (main,) = layout.sections
        assert [(c.name, len(c.matches)) for c in main.columns] == [
            ('Quarterfinals', 4),
            ('Semifinals', 2),
            ('Final', 1),
        ]
        # The final's slots are still open (its feeders aren't decided).
        final_match = main.columns[-1].matches[0]
        assert final_match.top.name == ''
        assert final_match.bottom.name == ''

    def test_bracket_diagram_shows_seed_and_rating(self, tournament_name):
        # Without grouping, each unplayed slot shows the seed number and the
        # player's rating, and no group line.
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        (main,) = tournament.knockout.layout().sections
        by_name = {
            slot.name: slot
            for column in main.columns
            for match in column.matches
            for slot in (match.top, match.bottom)
            if slot.name
        }
        assert by_name['PLAYER00'].seed == '1'  # top seed
        assert by_name['PLAYER00'].group == ''  # not seeded by group
        assert by_name['PLAYER00'].detail.startswith('(')

    def test_still_in_before_the_final(self, tournament_name):
        tournament = self._load()
        for round_ in (1, 2):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._play_round(tournament, round_)
            tournament = self._load()
        # The final is paired but unplayed: the two finalists are both "in".
        assert tournament.generate_round_pairings(3) == ''
        tournament = self._load()
        labels = tournament.knockout.standing_labels(after_round=3)
        by_name = {p.last_name: labels[p.id] for p in tournament.tournament_players}
        assert by_name['PLAYER00'] == 'Still in'
        assert by_name['PLAYER01'] == 'Still in'
        assert by_name['PLAYER04'] == 'Out — round 1'

    def test_third_place_playoff(self, tournament_name):
        from data.pairings.knockout import KnockoutThirdPlaceSetting

        tournament = self._load()
        tournament.update_pairing_settings(
            {KnockoutThirdPlaceSetting.static_id(): True}
        )
        tournament = self._load()
        # Semifinals (rounds 1-2): White always wins, so PLAYER00 and
        # PLAYER01 reach the final; PLAYER03 and PLAYER02 drop to the
        # bronze match.
        for round_ in range(1, 3):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._play_round(tournament, round_)
            tournament = self._load()

        assert tournament.generate_round_pairings(3) == ''
        tournament = self._load()
        # The final round now has two matches: the final and the third
        # place playoff.
        contested = self._board_names(tournament, 3)
        contested = [names for names in contested if names[1] is not None]
        assert {frozenset(pair) for pair in contested} == {
            frozenset(('PLAYER00', 'PLAYER01')),  # final
            frozenset(('PLAYER02', 'PLAYER03')),  # third place
        }

        self._play_round(tournament, 3)  # White wins both
        tournament = self._load()
        value = {
            p.last_name: tournament.knockout.ranking_value(p, after_round=3)
            for p in tournament.tournament_players
        }
        assert value['PLAYER00'] == 4  # champion
        assert value['PLAYER01'] == 3  # runner-up
        # The bronze match's higher seed (PLAYER02) plays White by default and
        # wins it, so PLAYER02 takes third and PLAYER03 fourth.
        assert value['PLAYER02'] == 2.5  # won the bronze match -> 3rd
        assert value['PLAYER03'] == 2  # lost the bronze match -> 4th
        assert value['PLAYER04'] == 1  # out in round 1
        assert value['PLAYER05'] == 1
        # The standing labels name the podium: the bronze match splits the two
        # beaten semi-finalists into an explicit third and fourth place.
        labels = tournament.knockout.standing_labels(after_round=3)
        by_name = {p.last_name: labels[p.id] for p in tournament.tournament_players}
        assert by_name['PLAYER00'] == 'Winner'
        assert by_name['PLAYER01'] == 'Runner-up'
        assert by_name['PLAYER02'] == 'Third place'
        assert by_name['PLAYER03'] == 'Fourth place'
        assert by_name['PLAYER04'] == 'Out — round 1'

    def test_higher_seed_white_rule(self, tournament_name):
        tournament = self._use_higher_seed_white(self._load())
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # The stronger seed leads (White) in every contested match.
        r1 = {w: b for w, b in self._board_names(tournament, 1) if b is not None}
        assert r1 == {'PLAYER03': 'PLAYER04', 'PLAYER02': 'PLAYER05'}

    def test_alternate_colours(self, tournament_name):
        from data.pairings.knockout import (
            KnockoutColourRule,
            KnockoutColourRuleSetting,
        )

        tournament = self._load()
        tournament.update_pairing_settings(
            {KnockoutColourRuleSetting.static_id(): KnockoutColourRule.ALTERNATE.value}
        )
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Round one alternates the higher seed's colour down the bracket. The
        # two top seeds have byes (even slots), so both contested matches sit
        # on odd slots and their higher seed (PLAYER03, PLAYER02) takes Black.
        r1 = {w: b for w, b in self._board_names(tournament, 1) if b is not None}
        assert r1 == {'PLAYER04': 'PLAYER03', 'PLAYER05': 'PLAYER02'}
        # Higher seeds (Black) win, so they carry Black into the semis.
        for board in tournament.get_round_boards(1):
            if board.black_tournament_player is not None:
                tournament.add_result(board, Result.LOSS)  # Black wins
        tournament = self._load()
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        # Each semi-finalist who played round one alternates Black -> White;
        # their bye-holding opponents (no previous colour) take Black.
        r2 = {w: b for w, b in self._board_names(tournament, 2) if b is not None}
        assert r2 == {'PLAYER03': 'PLAYER00', 'PLAYER02': 'PLAYER01'}

    def test_draw_lots_still_pairs_the_right_players(self, tournament_name):
        from data.pairings.knockout import (
            KnockoutColourRule,
            KnockoutColourRuleSetting,
        )

        tournament = self._load()
        tournament.update_pairing_settings(
            {KnockoutColourRuleSetting.static_id(): KnockoutColourRule.DRAW_LOTS.value}
        )
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Colours are drawn by lot, but the bracket still pairs the same
        # players — only which side is White is left to chance.
        matches = {
            frozenset((w, b))
            for w, b in self._board_names(tournament, 1)
            if b is not None
        }
        assert matches == {
            frozenset(('PLAYER03', 'PLAYER04')),
            frozenset(('PLAYER02', 'PLAYER05')),
        }

    def test_drawn_final_ties_until_resolved_then_adjusts(self, tournament_name):
        # Play out to a final, then draw it. The default play-off marker is
        # present, so the final is unresolved.
        tournament = self._load()
        for round_ in range(1, 3):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._play_round(tournament, round_)
            tournament = self._load()
        assert tournament.generate_round_pairings(3) == ''
        tournament = self._load()
        final = next(
            board
            for board in tournament.get_round_boards(3)
            if board.black_tournament_player is not None
        )
        final_id = final.identifier
        winner_name = final.optional_white_tournament_player.last_name
        winner_id = final.optional_white_tournament_player.id
        loser_name = final.black_tournament_player.last_name
        tournament.add_result(final, Result.DRAW)
        tournament = self._load()

        # Unresolved: the round is still finished (a shared title is
        # allowed) and both finalists top the standings.
        assert tournament.is_round_finished(3)
        value = {
            p.last_name: tournament.knockout.ranking_value(p, after_round=3)
            for p in tournament.tournament_players
        }
        assert value[winner_name] == 4
        assert value[loser_name] == 4

        # Designate the winner -> the loser drops to runner-up.
        tournament.knockout.set_player_match_winner(final_id, winner_id)
        tournament = self._load()
        value = {
            p.last_name: tournament.knockout.ranking_value(p, after_round=3)
            for p in tournament.tournament_players
        }
        assert value[winner_name] == 4  # champion
        assert value[loser_name] == 3  # lost the final

        # The ranking computes without running the Swiss opponent-sum
        # tie-breaks (which assert an opponent on every game and would
        # crash on a bye), and the champion comes first.
        tournament.compute_tournament_player_ranks()
        by_rank = tournament.tournament_players_by_rank
        assert by_rank[1].last_name == 'PLAYER00'
        assert by_rank[2].last_name == 'PLAYER01'

    def test_no_standings_tie_breaks_are_configurable_on_a_knockout(self):
        from data.pairings.knockout import KnockoutPairingSystem
        from data.pairings.systems import SwissPairingSystem
        from data.tie_breaks.tie_breaks import (
            PointsTieBreak,
            StandardBuchholzTieBreak,
        )

        knockout = KnockoutPairingSystem()
        # A knock-out ranks by the round reached; no standings tie-break is
        # configurable on one — not even Points.
        assert StandardBuchholzTieBreak().is_compatible_with(knockout) is False
        assert PointsTieBreak().is_compatible_with(knockout) is False
        # ...but they are fine as standings on a Swiss.
        assert StandardBuchholzTieBreak().is_compatible_with(SwissPairingSystem())
        assert PointsTieBreak().is_compatible_with(SwissPairingSystem())

    def test_advancement_tie_breaks_offered(self):
        from data.tie_breaks.team_tie_breaks import (
            BoardCountTieBreak,
            MatchPointsVsGamePointsTieBreak,
        )
        from data.tie_breaks.tie_breaks import (
            ManualTieBreak,
            PlayerRatingTieBreak,
            PointsTieBreak,
            WinsTieBreak,
        )

        # Team advancement: the board tie-breaks and MPvGP (Art. 12/13).
        assert BoardCountTieBreak().usable_as_knockout_advancement is True
        assert MatchPointsVsGamePointsTieBreak().usable_as_knockout_advancement is True
        # Individual advancement: wins, rating, and the play-off marker.
        assert WinsTieBreak().usable_as_knockout_advancement is True
        assert PlayerRatingTieBreak().usable_as_knockout_advancement is True
        assert ManualTieBreak().usable_as_knockout_advancement is True
        # The points can never separate same-depth participants.
        assert PointsTieBreak().usable_as_knockout_advancement is False

    def test_drawn_game_resolved_by_seed_advancement_tie_break(self, tournament_name):
        from data.tie_breaks.tie_breaks import PairingNumberTieBreak

        with EventDatabase(EVENT_ID, write=True) as database:
            tid = next(
                t.id
                for t in database.load_stored_tournaments()
                if t.name == TOURNAMENT_NAME
            )
            assert tid is not None
            # Drop the default play-off marker so the seed tie-break is the
            # only advancement rule.
            database.delete_all_tournament_stored_tie_breaks(tid)
            seed = PairingNumberTieBreak().to_stored_value()
            seed.tournament_id = tid
            seed.index = 0
            database.add_stored_tie_break(seed)

        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Both contested games are drawn — with no advancement tie-break
        # this would block; with the seed tie-break the higher seed
        # advances, so no play-off is needed.
        for board in tournament.get_round_boards(1):
            if board.black_tournament_player is not None:
                tournament.add_result(board, Result.DRAW)
        tournament = self._load()

        assert tournament.pairings_generation_disabled_message(2) is None
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        # Seed 4 (PLAYER03) beats seed 5, seed 3 (PLAYER02) beats seed 6 —
        # same qualifiers as a decisive result (colours aside).
        assert {frozenset(pair) for pair in self._board_names(tournament, 2)} == {
            frozenset(('PLAYER00', 'PLAYER03')),
            frozenset(('PLAYER01', 'PLAYER02')),
        }

    def test_manual_player_designation(self, tournament_name):
        # The default play-off marker is present, so a drawn game is
        # pending until the arbiter designates the winner (StoredBoard is
        # frozen — this also guards the field-setting path).
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        drawn = next(
            board
            for board in tournament.get_round_boards(1)
            if board.black_tournament_player is not None
        )
        board_id = drawn.identifier
        white_id = drawn.optional_white_tournament_player.id
        tournament.add_result(drawn, Result.DRAW)
        tournament = self._load()

        board = tournament.boards_by_id[board_id]
        assert tournament.knockout.board_advancement(board).manual_pending is True

        tournament.knockout.set_player_match_winner(board_id, white_id)
        tournament = self._load()
        board = tournament.boards_by_id[board_id]
        assert tournament.knockout.board_advancement(board).winner_id == white_id
        # Clicking again clears it back to pending.
        tournament.knockout.set_player_match_winner(board_id, None)
        tournament = self._load()
        board = tournament.boards_by_id[board_id]
        assert tournament.knockout.board_advancement(board).winner_id is None

    def test_tie_blocks_next_round(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        contested = [
            board
            for board in tournament.get_round_boards(1)
            if board.black_tournament_player is not None
        ]
        # One decisive, one drawn -> round is "finished" but has no
        # qualifier, so round 2 must be refused.
        tournament.add_result(contested[0], Result.WIN)
        tournament.add_result(contested[1], Result.DRAW)

        tournament = self._load()
        message = tournament.pairings_generation_disabled_message(2)
        assert message is not None
        assert 'tied' in message.lower()


GROUP_EVENT_ID = 'test-knockout-grouping'
GROUP_TOURNAMENT_NAME = 'knockout-grouped'


@pytest.mark.unit
class TestGroupedKnockout:
    """Grouped seeding: each club (a pairing dimension) is its own sub-bracket,
    so members play within the group first and the groups meet later."""

    @pytest.fixture
    def tournament_name(self):
        TestUtils.create_event(GROUP_EVENT_ID)
        TestUtils.create_tournament(
            GROUP_EVENT_ID,
            GROUP_TOURNAMENT_NAME,
            overrides={
                'rounds': 3,
                'current_round': 1,
                'pairing': 'KNOCKOUT_STANDARD',
            },
        )
        # Three clubs of two: RED (seeds 1-2), BLUE (3-4), GREEN (5-6). Three
        # groups pad to K = 4 with a phantom group, so the top club byes in
        # round two — exercising a structural bye past round one.
        clubs = ['RED', 'RED', 'BLUE', 'BLUE', 'GREEN', 'GREEN']
        with EventDatabase(GROUP_EVENT_ID, write=True) as database:
            tid = next(
                t.id
                for t in database.load_stored_tournaments()
                if t.name == GROUP_TOURNAMENT_NAME
            )
            assert tid is not None
            for index, club in enumerate(clubs):
                player_id = database.add_stored_player(
                    StoredPlayer(
                        id=None,
                        last_name=f'PLAYER{index:02d}',
                        ratings={1: {'standard': 2000 - index * 10}},
                        club=club,
                    )
                )
                database.add_stored_tournament_player(
                    StoredTournamentPlayer(tournament_id=tid, player_id=player_id)
                )
        yield GROUP_TOURNAMENT_NAME
        TestUtils.delete_event(GROUP_EVENT_ID)

    def _load(self):
        try:
            EventLoader.unload_event(GROUP_EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(GROUP_EVENT_ID)
        return self._event.tournaments_by_name[GROUP_TOURNAMENT_NAME]

    @staticmethod
    def _matches(tournament, round_):
        result = set()
        for board in tournament.get_round_boards(round_):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            if black is None:
                continue
            result.add(frozenset((white.last_name, black.last_name)))
        return result

    @staticmethod
    def _byes(tournament, round_):
        return {
            board.optional_white_tournament_player.last_name
            for board in tournament.get_round_boards(round_)
            if board.black_tournament_player is None
            and board.optional_white_tournament_player is not None
        }

    @staticmethod
    def _play_higher_seed(tournament, round_):
        for board in tournament.get_round_boards(round_):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            if black is None:
                continue
            white_stronger = (
                white.starting_rank_sort_key <= black.starting_rank_sort_key
            )
            tournament.add_result(board, Result.WIN if white_stronger else Result.LOSS)

    def _enable_grouping(self, tournament):
        from data.pairings.knockout import KnockoutGroupingSetting

        tournament.update_pairing_settings(
            {KnockoutGroupingSetting.static_id(): 'club'}
        )
        return self._load()

    def test_groups_play_themselves_before_they_meet(self, tournament_name):
        tournament = self._enable_grouping(self._load())
        # Three groups pad to K * M = 4 * 2 = 8 -> 3 rounds.
        assert tournament.rounds == 3
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Round 1: each club plays itself; the phantom fourth group is no board.
        assert self._matches(tournament, 1) == {
            frozenset(('PLAYER00', 'PLAYER01')),  # RED
            frozenset(('PLAYER02', 'PLAYER03')),  # BLUE
            frozenset(('PLAYER04', 'PLAYER05')),  # GREEN
        }
        assert self._byes(tournament, 1) == set()
        self._play_higher_seed(tournament, 1)
        tournament = self._load()
        # Round 2: RED's champion (PLAYER00) byes over the phantom group; BLUE
        # and GREEN's champions meet.
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        assert self._matches(tournament, 2) == {
            frozenset(('PLAYER02', 'PLAYER04')),
        }
        assert self._byes(tournament, 2) == {'PLAYER00'}
        self._play_higher_seed(tournament, 2)
        tournament = self._load()
        # Round 3: the last two club champions meet.
        assert tournament.generate_round_pairings(3) == ''
        tournament = self._load()
        assert self._matches(tournament, 3) == {frozenset(('PLAYER00', 'PLAYER02'))}

    def test_grouped_bracket_diagram_resolves_structural_byes(self, tournament_name):
        tournament = self._enable_grouping(self._load())
        for round_ in range(1, 4):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._play_higher_seed(tournament, round_)
            tournament = self._load()
        (main,) = tournament.knockout.layout().sections
        final = main.columns[-1].matches[0]
        # RED's champion reached the final via a round-two structural bye; the
        # diagram advances it rather than leaving the slot undecided.
        assert {final.top.name, final.bottom.name} == {'PLAYER00', 'PLAYER02'}
        champion = final.top if final.top.name == 'PLAYER00' else final.bottom
        assert champion.winner is True

    def test_bracket_diagram_shows_the_group_and_rating(self, tournament_name):
        tournament = self._enable_grouping(self._load())
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        (main,) = tournament.knockout.layout().sections
        by_name = {
            slot.name: slot
            for column in main.columns
            for match in column.matches
            for slot in (match.top, match.bottom)
            if slot.name
        }
        red = by_name['PLAYER00']
        assert red.group == 'RED'  # second line = the group
        assert red.seed == ''  # seeded by group, so no seed number
        assert red.detail.startswith('(') and red.detail.endswith(')')  # rating
        assert by_name['PLAYER04'].group == 'GREEN'

    def test_grouping_preview(self, tournament_name):
        tournament = self._load()
        preview = tournament.knockout.grouping_preview('club')
        assert preview is not None
        assert preview['players'] == 6
        assert preview['group_count'] == 3  # RED / BLUE / GREEN (phantom pads K)
        assert preview['bracket_size'] == 8  # K * M = 4 * 2
        assert preview['rounds'] == 3
        assert preview['byes'] == 2  # 8 slots - 6 players
        assert {(g['label'], g['count']) for g in preview['groups']} == {
            ('RED', 2),
            ('BLUE', 2),
            ('GREEN', 2),
        }
        assert preview['blown_up'] is False  # 8 <= 2 * 6

    def test_without_grouping_uses_the_plain_seed_order(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Standard 6-player bracket: seeds 1, 2 bye; 4v5 and 3v6 play (clubs
        # are ignored), so the clubs are mixed from round one.
        assert self._matches(tournament, 1) == {
            frozenset(('PLAYER03', 'PLAYER04')),
            frozenset(('PLAYER02', 'PLAYER05')),
        }


GDE_EVENT_ID = 'test-de-grouping'
GDE_TOURNAMENT_NAME = 'de-grouped'


@pytest.mark.unit
class TestGroupedDoubleElimination:
    """Double elimination seeded by group: each club plays itself in the
    winners' bracket before the clubs meet."""

    @pytest.fixture
    def tournament_name(self):
        TestUtils.create_event(GDE_EVENT_ID)
        TestUtils.create_tournament(
            GDE_EVENT_ID,
            GDE_TOURNAMENT_NAME,
            overrides={
                'rounds': 4,
                'current_round': 1,
                'pairing': 'KNOCKOUT_DOUBLE_ELIMINATION',
            },
        )
        clubs = ['RED', 'RED', 'BLUE', 'BLUE']  # P0,P1 RED; P2,P3 BLUE
        with EventDatabase(GDE_EVENT_ID, write=True) as database:
            tid = next(
                t.id
                for t in database.load_stored_tournaments()
                if t.name == GDE_TOURNAMENT_NAME
            )
            assert tid is not None
            for index, club in enumerate(clubs):
                player_id = database.add_stored_player(
                    StoredPlayer(
                        id=None,
                        last_name=f'PLAYER{index:02d}',
                        ratings={1: {'standard': 2000 - index * 10}},
                        club=club,
                    )
                )
                database.add_stored_tournament_player(
                    StoredTournamentPlayer(tournament_id=tid, player_id=player_id)
                )
        yield GDE_TOURNAMENT_NAME
        TestUtils.delete_event(GDE_EVENT_ID)

    def _load(self):
        try:
            EventLoader.unload_event(GDE_EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(GDE_EVENT_ID)
        return self._event.tournaments_by_name[GDE_TOURNAMENT_NAME]

    def _matches(self, tournament, round_):
        result = set()
        for board in tournament.get_round_boards(round_):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            if black is None:
                continue
            result.add(frozenset((white.last_name, black.last_name)))
        return result

    def _enable_grouping(self, tournament):
        from data.pairings.knockout import KnockoutGroupingSetting

        tournament.update_pairing_settings(
            {KnockoutGroupingSetting.static_id(): 'club'}
        )
        return self._load()

    def test_winners_bracket_round_one_is_intra_club(self, tournament_name):
        tournament = self._enable_grouping(self._load())
        assert tournament.rounds == 4  # K*M = 4 -> double-elim round_count(4)
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Winners' bracket round one: each club plays itself (the DE seed map
        # inverts seed_order so the grouped seats land as round-one matches).
        assert self._matches(tournament, 1) == {
            frozenset(('PLAYER00', 'PLAYER01')),
            frozenset(('PLAYER02', 'PLAYER03')),
        }


DE_EVENT_ID = 'test-double-elimination'
DE_TOURNAMENT_NAME = 'double-elim'


@pytest.mark.unit
class TestDoubleElimination:
    """Individual double elimination over a real tournament: four players in
    an exact bracket (k=2), played all the way to a champion, plus the
    optional grand-final reset."""

    @pytest.fixture
    def tournament_name(self):
        TestUtils.create_event(DE_EVENT_ID)
        TestUtils.create_tournament(
            DE_EVENT_ID,
            DE_TOURNAMENT_NAME,
            overrides={
                'rounds': 4,
                'current_round': 1,
                'pairing': 'KNOCKOUT_DOUBLE_ELIMINATION',
            },
        )
        with EventDatabase(DE_EVENT_ID, write=True) as database:
            tournament_id = next(
                stored.id
                for stored in database.load_stored_tournaments()
                if stored.name == DE_TOURNAMENT_NAME
            )
            assert tournament_id is not None
            for index in range(4):
                player_id = database.add_stored_player(
                    StoredPlayer(
                        id=None,
                        last_name=f'PLAYER{index:02d}',
                        ratings={1: {'standard': 2000 - index * 10}},
                    )
                )
                database.add_stored_tournament_player(
                    StoredTournamentPlayer(
                        tournament_id=tournament_id, player_id=player_id
                    )
                )
        yield DE_TOURNAMENT_NAME
        TestUtils.delete_event(DE_EVENT_ID)

    def _load(self):
        try:
            EventLoader.unload_event(DE_EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(DE_EVENT_ID)
        return self._event.tournaments_by_name[DE_TOURNAMENT_NAME]

    @staticmethod
    def _board_names(tournament, round_):
        result = []
        for board in sorted(tournament.get_round_boards(round_), key=lambda b: b.index):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            result.append(
                (
                    white.last_name if white else None,
                    black.last_name if black else None,
                )
            )
        return result

    @staticmethod
    def _win_white(tournament, round_):
        """Advance the higher-seeded side of every match. (The default colour
        rule alternates, so White is not always the stronger seed — win by
        seed, not by colour.)"""
        for board in tournament.get_round_boards(round_):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            if black is None:
                continue
            white_stronger = (
                white.starting_rank_sort_key <= black.starting_rank_sort_key
            )
            tournament.add_result(board, Result.WIN if white_stronger else Result.LOSS)

    def test_bracket_shows_known_competitors_before_pairing(self, tournament_name):
        tournament = self._load()
        for round_ in (1, 2):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._win_white(tournament, round_)
            tournament = self._load()

        # Rounds 3 (losers' final) and 4 (grand final) are NOT paired yet.
        layout = tournament.knockout.layout()
        matches = {
            m.id: m
            for section in layout.sections
            for column in section.columns
            for m in column.matches
        }
        # The losers' final's two feeders are both decided (the losers'
        # round-1 winner and the winners'-final loser), so both names show
        # before it is paired.
        lb_final = matches['L2.0']
        assert {lb_final.top.name, lb_final.bottom.name} == {'PLAYER02', 'PLAYER01'}
        # The grand final knows its winners'-bracket champion; the other slot
        # stays open until the losers' final is played.
        grand_final = matches['GF']
        assert grand_final.top.name == 'PLAYER00'
        assert grand_final.bottom.name == ''
        # ...and the champion is NOT marked the winner: an undecided opponent
        # is not a bye, so the grand final has no winner yet.
        assert grand_final.top.winner is False
        assert grand_final.bottom.winner is False

    def test_round_count_no_reset_then_reset(self, tournament_name):
        from data.pairings.knockout import DoubleEliminationResetSetting

        tournament = self._load()
        assert tournament.rounds == 4  # 2k for k=2, grand final in round 4
        tournament.update_pairing_settings(
            {DoubleEliminationResetSetting.static_id(): True}
        )
        tournament = self._load()
        assert tournament.rounds == 5  # reset reserves one more round

    def test_toggling_reset_does_not_crash_has_pairings(self, tournament_name):
        # Saving the settings modal recomputes `rounds` (the reset reserves
        # one more), but each player's pairings dict is cached at the old
        # count. has_pairings iterates every round, so a missing (stale) round
        # must not KeyError.
        from data.pairings.knockout import DoubleEliminationResetSetting

        tournament = self._load()
        for player in tournament.tournament_players:
            _ = player.pairings  # prime the per-player cache at rounds == 4
        assert tournament.rounds == 4
        tournament.update_pairing_settings(
            {DoubleEliminationResetSetting.static_id(): True}
        )
        assert tournament.rounds == 5
        assert tournament.has_pairings is False  # no crash on the new round

    def test_full_bracket_to_champion(self, tournament_name):
        tournament = self._load()
        # Round 1 = winners' bracket round 1 (both games).
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # (Colours follow the alternate rule, so assert the matchups, not the
        # White/Black order.)
        assert {frozenset(pair) for pair in self._board_names(tournament, 1)} == {
            frozenset(('PLAYER00', 'PLAYER03')),  # seed 1 v 4
            frozenset(('PLAYER01', 'PLAYER02')),  # seed 2 v 3
        }
        self._win_white(tournament, 1)
        tournament = self._load()

        # Round 2 = winners' final + losers' round 1 (the two WB losers).
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        assert {frozenset(pair) for pair in self._board_names(tournament, 2)} == {
            frozenset(('PLAYER00', 'PLAYER01')),  # WB final: the two WB winners
            frozenset(('PLAYER03', 'PLAYER02')),  # LB round 1: the two WB losers
        }
        self._win_white(tournament, 2)
        tournament = self._load()

        # Round 3 = losers' final: the losers'-round-1 winner (PLAYER02, the
        # stronger of the two WB-round-1 losers) v the WB-final loser (PLAYER01).
        assert tournament.generate_round_pairings(3) == ''
        tournament = self._load()
        assert {frozenset(pair) for pair in self._board_names(tournament, 3)} == {
            frozenset(('PLAYER01', 'PLAYER02'))
        }
        self._win_white(tournament, 3)
        tournament = self._load()

        # Round 4 = grand final: WB champion (PLAYER00) v LB champion (PLAYER01).
        assert tournament.generate_round_pairings(4) == ''
        tournament = self._load()
        assert {frozenset(pair) for pair in self._board_names(tournament, 4)} == {
            frozenset(('PLAYER00', 'PLAYER01'))
        }
        self._win_white(tournament, 4)  # WB champion wins the grand final
        tournament = self._load()

        # Standings place by elimination order: champion, runner-up, then
        # the losers'-bracket losers by the round they went out in.
        value = {
            p.last_name: tournament.knockout.ranking_value(p, after_round=4)
            for p in tournament.tournament_players
        }
        assert value['PLAYER00'] == 5  # champion (rounds + 1)
        assert value['PLAYER01'] == 4  # runner-up (lost the grand final)
        assert value['PLAYER02'] == 3  # out in the losers' final
        assert value['PLAYER03'] == 2  # out in losers' round 1

        labels = tournament.knockout.standing_labels(after_round=4)
        by_name = {p.last_name: labels[p.id] for p in tournament.tournament_players}
        assert by_name['PLAYER00'] == 'Winner'
        assert by_name['PLAYER01'] == 'Runner-up'
        assert by_name['PLAYER02'] == 'Out — round 3'
        assert by_name['PLAYER03'] == 'Out — round 2'

    def test_colour_rule_applies_to_double_elimination(self, tournament_name):
        from data.pairings.knockout import (
            KnockoutColourRule,
            KnockoutColourRuleSetting,
        )

        tournament = self._load()
        tournament.update_pairing_settings(
            {
                KnockoutColourRuleSetting.static_id(): (
                    KnockoutColourRule.HIGHER_SEED_WHITE.value
                )
            }
        )
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # The colour rule reaches the double-elimination board seam too: the
        # stronger seed plays White in each winners'-bracket round-one match.
        r1 = {w: b for w, b in self._board_names(tournament, 1) if b is not None}
        assert r1 == {'PLAYER00': 'PLAYER03', 'PLAYER01': 'PLAYER02'}

    def test_bracket_sections_group_boards(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        self._win_white(tournament, 1)
        tournament = self._load()
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()

        # Round 2 mixes the winners' final and a losers'-bracket game; the
        # tab groups them under their round names rather than one flat list.
        boards = tournament.get_round_boards(2)
        sections = tournament.round_sections(boards)
        labels = [label for label, _boards in sections]
        assert labels == [
            'Upper Bracket Final',
            'Lower Bracket Semifinals',
        ]  # winners' bracket first
        by_label = {label: bs for label, bs in sections}
        wb_names = {
            b.optional_white_tournament_player.last_name
            for b in by_label['Upper Bracket Final']
        } | {
            b.black_tournament_player.last_name for b in by_label['Upper Bracket Final']
        }
        assert wb_names == {'PLAYER00', 'PLAYER01'}  # winners' final
        lb_names = {
            b.optional_white_tournament_player.last_name
            for b in by_label['Lower Bracket Semifinals']
        } | {
            b.black_tournament_player.last_name
            for b in by_label['Lower Bracket Semifinals']
        }
        assert lb_names == {'PLAYER02', 'PLAYER03'}  # losers' round 1

    def test_grand_final_reset_played_when_losers_champion_wins(self, tournament_name):
        from data.pairings.knockout import DoubleEliminationResetSetting

        tournament = self._load()
        tournament.update_pairing_settings(
            {DoubleEliminationResetSetting.static_id(): True}
        )
        tournament = self._load()
        for round_ in range(1, 4):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._win_white(tournament, round_)
            tournament = self._load()

        assert tournament.generate_round_pairings(4) == ''
        tournament = self._load()
        # Grand final: the losers' champion (PLAYER01, since favourites win)
        # wins, so the winners' champion has their first loss -> a reset game
        # is played. Win by identity, since the colour rule decides White.
        gf = next(
            b
            for b in tournament.get_round_boards(4)
            if b.black_tournament_player is not None
        )
        lb_is_white = gf.optional_white_tournament_player.last_name == 'PLAYER01'
        tournament.add_result(gf, Result.WIN if lb_is_white else Result.LOSS)
        tournament = self._load()

        assert tournament.generate_round_pairings(5) == ''
        tournament = self._load()
        assert {frozenset(pair) for pair in self._board_names(tournament, 5)} == {
            frozenset(('PLAYER00', 'PLAYER01'))
        }
        reset = tournament.get_round_boards(5)[0]
        reset_lb_white = reset.optional_white_tournament_player.last_name == 'PLAYER01'
        tournament.add_result(reset, Result.WIN if reset_lb_white else Result.LOSS)
        tournament = self._load()

        # The losers' champion beat the winners' champion twice: they take
        # the title, the winners' champion is runner-up (rounds == 5).
        value = {
            p.last_name: tournament.knockout.ranking_value(p, after_round=5)
            for p in tournament.tournament_players
        }
        assert value['PLAYER01'] == 6  # champion
        assert value['PLAYER00'] == 5  # runner-up (lost the reset)
        assert value['PLAYER02'] == 3  # out in the losers' final
        assert value['PLAYER03'] == 2  # out in losers' round 1

    def test_no_reset_when_winners_champion_wins_grand_final(self, tournament_name):
        from data.pairings.knockout import DoubleEliminationResetSetting

        tournament = self._load()
        tournament.update_pairing_settings(
            {DoubleEliminationResetSetting.static_id(): True}
        )
        tournament = self._load()
        for round_ in range(1, 5):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._win_white(tournament, round_)  # WB champion wins the GF
            tournament = self._load()
        # The winners' champion took the grand final, so no reset is needed:
        # the round-5 pair button is disabled with that reason.
        message = (
            tournament.pairing_variation.engine.pairings_generation_disabled_message(
                tournament, 5
            )
        )
        assert message and 'no reset' in message.lower()
        # The reset round stays reserved (rounds == 5, so its date can be set),
        # but the event is over: it must read as finished even though round 5
        # is never paired, so the final standings become available.
        assert tournament.rounds == 5
        assert tournament.pairing_variation.engine.tournament_is_over(tournament)
        assert tournament.finished
        # The final standings are available as of the last (reserved) round,
        # so the ranking document can be produced even though round 5 is never
        # paired.
        assert tournament.max_ranking_round == 5

    def test_not_over_until_grand_final_decided(self, tournament_name):
        from data.pairings.knockout import DoubleEliminationResetSetting

        tournament = self._load()
        tournament.update_pairing_settings(
            {DoubleEliminationResetSetting.static_id(): True}
        )
        tournament = self._load()
        # Play up to (not including) the grand final: not over yet.
        for round_ in range(1, 4):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._win_white(tournament, round_)
            tournament = self._load()
        assert tournament.generate_round_pairings(4) == ''
        tournament = self._load()
        assert not tournament.pairing_variation.engine.tournament_is_over(tournament)
        assert not tournament.finished

    def test_reset_due_is_not_over_until_reset_played(self, tournament_name):
        from data.pairings.knockout import DoubleEliminationResetSetting

        tournament = self._load()
        tournament.update_pairing_settings(
            {DoubleEliminationResetSetting.static_id(): True}
        )
        tournament = self._load()
        for round_ in range(1, 4):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._win_white(tournament, round_)
            tournament = self._load()
        assert tournament.generate_round_pairings(4) == ''
        tournament = self._load()
        # Losers' champion (Black) wins the grand final -> a reset is due, so
        # the event is not over until that reset round is played.
        gf = next(
            b
            for b in tournament.get_round_boards(4)
            if b.black_tournament_player is not None
        )
        tournament.add_result(gf, Result.LOSS)
        tournament = self._load()
        assert not tournament.pairing_variation.engine.tournament_is_over(tournament)
        assert not tournament.finished


TEAM_EVENT_ID = 'test-team-knockout'
TEAM_TOURNAMENT_NAME = 'team-knockout'


@pytest.mark.unit
class TestTeamKnockout:
    """Team knock-out over a real tournament: knocked-out teams have no
    envelope in later rounds, so the round must still count as finished
    (the bug: it demanded an envelope for every team and never finished)."""

    @pytest.fixture
    def tournament_name(self):
        from database.sqlite.event.event_store import StoredTeam
        from utils.enum import EventType

        TestUtils.create_event(TEAM_EVENT_ID, overrides={'event_type': EventType.TEAM})
        TestUtils.create_tournament(
            TEAM_EVENT_ID,
            TEAM_TOURNAMENT_NAME,
            overrides={
                'rounds': 2,
                'current_round': 1,
                'team_player_count': 1,
                'pairing': 'TEAM_KNOCKOUT_STANDARD',
            },
        )
        with EventDatabase(TEAM_EVENT_ID, write=True) as database:
            tid = next(
                t.id
                for t in database.load_stored_tournaments()
                if t.name == TEAM_TOURNAMENT_NAME
            )
            assert tid is not None
            for index in range(4):
                team_id = database.add_stored_team(
                    StoredTeam(
                        id=None,
                        name=f'Team{index}',
                        tournament_id=tid,
                        pairing_number=index + 1,
                    )
                )
                database.add_stored_player(
                    StoredPlayer(
                        id=None,
                        last_name=f'T{index}P0',
                        team_id=team_id,
                        team_index=0,
                        check_in=True,
                    )
                )
        yield TEAM_TOURNAMENT_NAME
        TestUtils.delete_event(TEAM_EVENT_ID)

    def _load(self):
        try:
            EventLoader.unload_event(TEAM_EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(TEAM_EVENT_ID)
        return self._event.tournaments_by_name[TEAM_TOURNAMENT_NAME]

    @staticmethod
    def _play_round(tournament, round_):
        # One board per match; White (the higher-seeded team) wins, so the
        # match is decisive and a team advances.
        for board in tournament.get_round_boards(round_):
            if board.black_tournament_player is not None:
                tournament.add_result(board, Result.WIN)

    @staticmethod
    def _team_matches(tournament, round_):
        return {
            frozenset((team_board.team_a.name, team_board.team_b.name))
            for team_board in tournament.get_round_team_boards(round_)
            if team_board.team_b is not None
        }

    def test_colour_rule_sets_team_orientation(self, tournament_name):
        from data.pairings.knockout import (
            KnockoutColourRule,
            KnockoutColourRuleSetting,
        )

        tournament = self._load()
        tournament.update_pairing_settings(
            {
                KnockoutColourRuleSetting.static_id(): (
                    KnockoutColourRule.HIGHER_SEED_WHITE.value
                )
            }
        )
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # The stronger team of each match plays board-one White.
        white_teams = {
            board.optional_white_tournament_player.team.name
            for board in tournament.get_round_boards(1)
            if board.black_tournament_player is not None
        }
        assert white_teams == {'Team0', 'Team1'}  # the two stronger teams

    def test_unresolved_tie_propagates_none_not_empty(self, tournament_name):
        # An earlier round left tied (no qualifier) must make later rounds'
        # winners resolve to None, not an empty list -- the empty list slips
        # past the gate and crashes advance_pairs with "got 0".
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        boards = [
            b
            for b in tournament.get_round_boards(1)
            if b.black_tournament_player is not None
        ]
        tournament.add_result(boards[0], Result.WIN)
        tournament.add_result(boards[1], Result.DRAW)  # tied, unresolved
        tournament = self._load()
        engine = tournament.pairing_variation.engine

        assert engine._round_winner_team_ids(tournament, 1) is None
        assert engine._bracket_team_pairs(tournament, 2) == []
        assert engine._round_winner_team_ids(tournament, 2) is None
        message = engine.pairings_generation_disabled_message(tournament, 2)
        assert message and 'tied' in message.lower()

    def test_find_team_board_tolerates_changed_opponent(self, tournament_name):
        # If an earlier round's result is edited after this round was paired,
        # the recomputed opponent no longer matches what was played. A team
        # still has exactly one match per round, so the finder must locate it
        # by the team that is actually present -- not fail (which showed a
        # bogus "resolve the tied match" for an already-decided round).
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        eng = tournament.pairing_variation.engine
        tb = next(
            b
            for b in tournament.team_boards_by_round[1]
            if b.stored_team_board.team_b_id is not None
        )
        a_id = tb.stored_team_board.team_a_id
        real_b = tb.stored_team_board.team_b_id
        bogus = max(t.id for t in tournament.event.teams_by_id.values()) + 99

        assert eng._find_team_board(tournament, 1, a_id, bogus) is tb
        assert eng._find_team_board(tournament, 1, a_id, real_b) is tb  # exact
        assert eng._find_team_board(tournament, 1, bogus, bogus + 1) is None

    def test_finished_round_with_knocked_out_teams_advances(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        self._play_round(tournament, 1)
        tournament = self._load()
        assert tournament.is_round_finished(1)

        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        self._play_round(tournament, 2)
        tournament = self._load()
        # Two teams were knocked out and have no envelope in round 2; the
        # round must still be finished once the final's result is in.
        assert tournament.is_round_finished(2)

    def test_third_place_playoff_sets_team_standing_labels(self, tournament_name):
        from data.pairings.knockout import (
            KnockoutColourRule,
            KnockoutColourRuleSetting,
            KnockoutThirdPlaceSetting,
        )

        tournament = self._load()
        tournament.update_pairing_settings(
            {
                KnockoutColourRuleSetting.static_id(): (
                    KnockoutColourRule.HIGHER_SEED_WHITE.value
                ),
                KnockoutThirdPlaceSetting.static_id(): True,
            }
        )
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        self._play_round(tournament, 1)
        tournament = self._load()

        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        assert self._team_matches(tournament, 2) == {
            frozenset(('Team0', 'Team1')),
            frozenset(('Team2', 'Team3')),
        }
        self._play_round(tournament, 2)
        tournament = self._load()

        labels = tournament.knockout.team_standing_labels(after_round=2)
        by_name = {team.name: labels[team.id] for team in tournament.teams}
        assert by_name['Team0'] == 'Winner'
        assert by_name['Team1'] == 'Runner-up'
        assert by_name['Team2'] == 'Third place'
        assert by_name['Team3'] == 'Fourth place'


GT_EVENT_ID = 'test-team-knockout-grouping'
GT_TOURNAMENT_NAME = 'team-ko-grouped'


@pytest.mark.unit
class TestGroupedTeamKnockout:
    """Team knock-out seeded by federation: each federation plays itself
    before the federations meet."""

    @pytest.fixture
    def tournament_name(self):
        from database.sqlite.event.event_store import StoredTeam
        from utils.enum import EventType

        TestUtils.create_event(GT_EVENT_ID, overrides={'event_type': EventType.TEAM})
        TestUtils.create_tournament(
            GT_EVENT_ID,
            GT_TOURNAMENT_NAME,
            overrides={
                'rounds': 2,
                'current_round': 1,
                'team_player_count': 1,
                'pairing': 'TEAM_KNOCKOUT_STANDARD',
            },
        )
        # Three federations pad to four group blocks, creating a phantom group.
        federations = ['A', 'A', 'B', 'B', 'C', 'C']
        with EventDatabase(GT_EVENT_ID, write=True) as database:
            tid = next(
                t.id
                for t in database.load_stored_tournaments()
                if t.name == GT_TOURNAMENT_NAME
            )
            assert tid is not None
            for index, federation in enumerate(federations):
                team_id = database.add_stored_team(
                    StoredTeam(
                        id=None,
                        name=f'Team{index}',
                        tournament_id=tid,
                        pairing_number=index + 1,
                        federation=federation,
                    )
                )
                database.add_stored_player(
                    StoredPlayer(
                        id=None,
                        last_name=f'T{index}P0',
                        team_id=team_id,
                        team_index=0,
                        check_in=True,
                    )
                )
        yield GT_TOURNAMENT_NAME
        TestUtils.delete_event(GT_EVENT_ID)

    def _load(self):
        try:
            EventLoader.unload_event(GT_EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(GT_EVENT_ID)
        return self._event.tournaments_by_name[GT_TOURNAMENT_NAME]

    def _matches(self, tournament, round_):
        return {
            frozenset((tb.team_a.name, tb.team_b.name))
            for tb in tournament.get_round_team_boards(round_)
            if tb.team_b is not None
        }

    @staticmethod
    def _win_stronger_team(tournament, round_):
        for board in tournament.get_round_boards(round_):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            if black is None:
                continue
            white_pn = white.team.pairing_number or float('inf')
            black_pn = black.team.pairing_number or float('inf')
            tournament.add_result(
                board, Result.WIN if white_pn <= black_pn else Result.LOSS
            )

    def _enable_grouping(self, tournament):
        from data.pairings.knockout import KnockoutGroupingSetting

        tournament.update_pairing_settings(
            {KnockoutGroupingSetting.static_id(): 'team-federation'}
        )
        return self._load()

    def test_federations_play_themselves_first(self, tournament_name):
        tournament = self._enable_grouping(self._load())
        assert tournament.rounds == 3  # three groups of two -> K*M = 8
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        assert self._matches(tournament, 1) == {
            frozenset(('Team0', 'Team1')),  # federation A
            frozenset(('Team2', 'Team3')),  # federation B
            frozenset(('Team4', 'Team5')),  # federation C
        }
        self._win_stronger_team(tournament, 1)
        tournament = self._load()
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        # Federation A's champion walks over the phantom group; the other two
        # federation champions meet.
        assert self._matches(tournament, 2) == {frozenset(('Team2', 'Team4'))}
        self._win_stronger_team(tournament, 2)
        tournament = self._load()
        assert tournament.generate_round_pairings(3) == ''
        tournament = self._load()
        assert self._matches(tournament, 3) == {frozenset(('Team0', 'Team2'))}

    def test_grouped_bracket_diagram_resolves_team_structural_byes(
        self, tournament_name
    ):
        tournament = self._enable_grouping(self._load())
        for round_ in (1, 2):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._win_stronger_team(tournament, round_)
            tournament = self._load()

        (main,) = tournament.knockout.layout().sections
        final = main.columns[-1].matches[0]
        assert {final.top.name, final.bottom.name} == {'Team0', 'Team2'}


TDE_EVENT_ID = 'test-team-double-elim'
TDE_TOURNAMENT_NAME = 'team-double-elim'


@pytest.mark.unit
class TestTeamDoubleElimination:
    """Team double elimination: four teams (one board each), played to a
    champion through the winners' and losers' brackets."""

    @pytest.fixture
    def tournament_name(self):
        from database.sqlite.event.event_store import StoredTeam
        from utils.enum import EventType

        TestUtils.create_event(TDE_EVENT_ID, overrides={'event_type': EventType.TEAM})
        TestUtils.create_tournament(
            TDE_EVENT_ID,
            TDE_TOURNAMENT_NAME,
            overrides={
                'rounds': 4,
                'current_round': 1,
                'team_player_count': 1,
                'pairing': 'TEAM_KNOCKOUT_DOUBLE_ELIMINATION',
            },
        )
        with EventDatabase(TDE_EVENT_ID, write=True) as database:
            tid = next(
                t.id
                for t in database.load_stored_tournaments()
                if t.name == TDE_TOURNAMENT_NAME
            )
            assert tid is not None
            for index in range(4):
                team_id = database.add_stored_team(
                    StoredTeam(
                        id=None,
                        name=f'Team{index}',
                        tournament_id=tid,
                        pairing_number=index + 1,
                    )
                )
                database.add_stored_player(
                    StoredPlayer(
                        id=None,
                        last_name=f'T{index}P0',
                        team_id=team_id,
                        team_index=0,
                        check_in=True,
                    )
                )
        yield TDE_TOURNAMENT_NAME
        TestUtils.delete_event(TDE_EVENT_ID)

    def _load(self):
        try:
            EventLoader.unload_event(TDE_EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(TDE_EVENT_ID)
        return self._event.tournaments_by_name[TDE_TOURNAMENT_NAME]

    @staticmethod
    def _win_home(tournament, round_):
        # One board per match; the higher-seeded team wins. The colour rule
        # alternates which team is board-one White, so win by team seed
        # (lower pairing number is stronger), not by colour.
        for board in tournament.get_round_boards(round_):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            if black is None:
                continue
            white_pn = white.team.pairing_number or float('inf')
            black_pn = black.team.pairing_number or float('inf')
            tournament.add_result(
                board, Result.WIN if white_pn <= black_pn else Result.LOSS
            )

    @staticmethod
    def _team_matches(tournament, round_):
        # Set of matchups (order-independent: the round's boards are sorted
        # by strength, not bracket order).
        result = set()
        for tb in tournament.get_round_team_boards(round_):
            a = tb.team_a.name
            b = tb.team_b.name if tb.team_b is not None else None
            result.add(frozenset((a, b)))
        return result

    def test_full_team_bracket_to_champion(self, tournament_name):
        tournament = self._load()
        assert tournament.rounds == 4

        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        assert self._team_matches(tournament, 1) == {
            frozenset(('Team0', 'Team3')),  # seed 1 v 4
            frozenset(('Team1', 'Team2')),  # seed 2 v 3
        }
        self._win_home(tournament, 1)
        tournament = self._load()

        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        assert self._team_matches(tournament, 2) == {
            frozenset(('Team0', 'Team1')),  # winners' final
            frozenset(('Team3', 'Team2')),  # losers' round 1
        }
        self._win_home(tournament, 2)
        tournament = self._load()

        assert tournament.generate_round_pairings(3) == ''
        tournament = self._load()
        assert self._team_matches(tournament, 3) == {
            frozenset(('Team1', 'Team2'))  # losers' final
        }
        self._win_home(tournament, 3)
        tournament = self._load()

        assert tournament.generate_round_pairings(4) == ''
        tournament = self._load()
        assert self._team_matches(tournament, 4) == {
            frozenset(('Team0', 'Team1'))  # grand final
        }
        self._win_home(tournament, 4)  # Team0 wins the grand final
        tournament = self._load()

        # Team ranking is by round reached, not accumulated match points.
        labels = tournament.knockout.team_standing_labels(after_round=4)
        by_name = {team.name: labels[team.id] for team in tournament.teams}
        assert by_name['Team0'] == 'Winner'
        assert by_name['Team1'] == 'Runner-up'
        assert by_name['Team2'] == 'Out — round 3'  # losers' final
        assert by_name['Team3'] == 'Out — round 2'  # losers' round 1
        # Standings sort follows the same order.
        order = [row['team'].name for row in tournament.team_standings()]
        assert order == ['Team0', 'Team1', 'Team2', 'Team3']

    def test_reset_round_count(self, tournament_name):
        from data.pairings.knockout import DoubleEliminationResetSetting

        tournament = self._load()
        assert tournament.rounds == 4
        tournament.update_pairing_settings(
            {DoubleEliminationResetSetting.static_id(): True}
        )
        tournament = self._load()
        assert tournament.rounds == 5


TWO_GAME_EVENT_ID = 'test-two-game-knockout'
TWO_GAME_NAME = 'two-game-ko'


@pytest.mark.unit
class TestIndividualTwoGameKnockout:
    """Individual single-elimination aller-retour: each match is two games,
    colours forced (game 1 stronger White, game 2 reversed), decided on the
    aggregate."""

    @pytest.fixture
    def tournament_name(self):
        TestUtils.create_event(TWO_GAME_EVENT_ID)
        TestUtils.create_tournament(
            TWO_GAME_EVENT_ID,
            TWO_GAME_NAME,
            overrides={
                'rounds': 4,
                'current_round': 1,
                'pairing': 'KNOCKOUT_STANDARD_TWO_GAME',
            },
        )
        with EventDatabase(TWO_GAME_EVENT_ID, write=True) as database:
            tournament_id = next(
                stored.id
                for stored in database.load_stored_tournaments()
                if stored.name == TWO_GAME_NAME
            )
            assert tournament_id is not None
            for index in range(4):
                # P0 strongest (seed 1), P3 weakest (seed 4).
                player_id = database.add_stored_player(
                    StoredPlayer(
                        id=None,
                        last_name=f'P{index}',
                        ratings={1: {'standard': 2000 - index * 10}},
                    )
                )
                database.add_stored_tournament_player(
                    StoredTournamentPlayer(
                        tournament_id=tournament_id, player_id=player_id
                    )
                )
        yield TWO_GAME_NAME
        TestUtils.delete_event(TWO_GAME_EVENT_ID)

    def _load(self):
        try:
            EventLoader.unload_event(TWO_GAME_EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(TWO_GAME_EVENT_ID)
        return self._event.tournaments_by_name[TWO_GAME_NAME]

    @staticmethod
    def _board_names(tournament, round_):
        result = []
        for board in sorted(tournament.get_round_boards(round_), key=lambda b: b.index):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            result.append(
                (
                    white.last_name if white else None,
                    black.last_name if black else None,
                )
            )
        return result

    @staticmethod
    def _win(tournament, board, winner_last_name):
        white = board.optional_white_tournament_player
        if white is not None and white.last_name == winner_last_name:
            tournament.add_result(board, Result.WIN)
        else:
            tournament.add_result(board, Result.LOSS)

    def _board_between(self, tournament, round_, a_name, b_name):
        for board in tournament.get_round_boards(round_):
            names = {
                p.last_name
                for p in (
                    board.optional_white_tournament_player,
                    board.black_tournament_player,
                )
                if p is not None
            }
            if names == {a_name, b_name}:
                return board
        raise AssertionError(f'no board {a_name} v {b_name} in round {round_}')

    def test_round_count_is_doubled(self, tournament_name):
        tournament = self._load()
        # 4 players -> 2 bracket levels -> 4 app rounds (2 games each).
        assert tournament.automatic_rounds == 4

    def test_game_one_forced_colours_then_reversed_in_game_two(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Level 1: seed1 v seed4, seed2 v seed3. Game 1 = stronger seed White.
        assert self._board_names(tournament, 1) == [
            ('P0', 'P3'),
            ('P1', 'P2'),
        ]
        # Game 1 must be played before game 2 is paired (round-by-round).
        for board in tournament.get_round_boards(1):
            tournament.add_result(board, Result.DRAW)
        tournament = self._load()
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        # Game 2: same pairs, colours reversed.
        assert self._board_names(tournament, 2) == [
            ('P3', 'P0'),
            ('P2', 'P1'),
        ]

    def test_drawn_game_one_does_not_block_game_two(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Draw both game-1 boards: no match winner yet, but game 2 must pair.
        for board in tournament.get_round_boards(1):
            tournament.add_result(board, Result.DRAW)
        tournament = self._load()
        assert (
            tournament.pairing_variation.engine.pairings_generation_disabled_message(
                tournament, 2
            )
            is None
        )
        assert tournament.generate_round_pairings(2) == ''

    def test_match_decided_on_aggregate_after_two_games(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Game 1: stronger seeds (White) win.
        self._win(tournament, self._board_between(tournament, 1, 'P0', 'P3'), 'P0')
        self._win(tournament, self._board_between(tournament, 1, 'P1', 'P2'), 'P1')
        tournament = self._load()
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        # Game 2 (reversed colours): stronger seeds win again -> 2-0 aggregate.
        self._win(tournament, self._board_between(tournament, 2, 'P0', 'P3'), 'P0')
        self._win(tournament, self._board_between(tournament, 2, 'P1', 'P2'), 'P1')
        tournament = self._load()
        # Level 1 decided -> level 2 (final) game 1 can be paired.
        assert tournament.generate_round_pairings(3) == ''
        tournament = self._load()
        assert self._board_names(tournament, 3) == [('P0', 'P1')]

    def test_aggregate_tie_blocks_next_level_but_not_game_two(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Game 1: P0 and P1 win their boards.
        self._win(tournament, self._board_between(tournament, 1, 'P0', 'P3'), 'P0')
        self._win(tournament, self._board_between(tournament, 1, 'P1', 'P2'), 'P1')
        tournament = self._load()
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        # Game 2: the underdogs win -> 1-1 aggregate in both matches.
        self._win(tournament, self._board_between(tournament, 2, 'P0', 'P3'), 'P3')
        self._win(tournament, self._board_between(tournament, 2, 'P1', 'P2'), 'P2')
        tournament = self._load()
        engine = tournament.pairing_variation.engine
        # Game 2 itself never needed a match winner, so it was allowed.
        # Pairing level-2 game 1 now needs level 1 decided -> tie message.
        assert engine.pairings_generation_disabled_message(tournament, 3) is not None

    def test_drawn_game_one_shows_no_advancement_warning(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        for board in tournament.get_round_boards(1):
            tournament.add_result(board, Result.DRAW)
        tournament = self._load()
        # A drawn game 1 is just a leg — no tie/advancement warning on it.
        for board in tournament.get_round_boards(1):
            assert tournament.knockout.board_advancement(board) is None

    def test_aggregate_tie_warning_shows_on_game_two_only(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        self._win(tournament, self._board_between(tournament, 1, 'P0', 'P3'), 'P0')
        self._win(tournament, self._board_between(tournament, 1, 'P1', 'P2'), 'P1')
        tournament = self._load()
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        self._win(tournament, self._board_between(tournament, 2, 'P0', 'P3'), 'P3')
        self._win(tournament, self._board_between(tournament, 2, 'P1', 'P2'), 'P2')
        tournament = self._load()
        # No warning on game 1; the aggregate-tie warning is on game 2.
        for board in tournament.get_round_boards(1):
            assert tournament.knockout.board_advancement(board) is None
        for board in tournament.get_round_boards(2):
            assert tournament.knockout.board_advancement(board) is not None
        engine = tournament.pairing_variation.engine
        assert engine.unresolved_matches(tournament, 1) == []
        assert len(engine.unresolved_matches(tournament, 2)) == 2

    def test_decisive_aggregate_shows_no_tie_on_game_two(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        self._win(tournament, self._board_between(tournament, 1, 'P0', 'P3'), 'P0')
        self._win(tournament, self._board_between(tournament, 1, 'P1', 'P2'), 'P1')
        tournament = self._load()
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        # Stronger seeds win game 2 too -> 2-0 aggregate, decided, no tie.
        self._win(tournament, self._board_between(tournament, 2, 'P0', 'P3'), 'P0')
        self._win(tournament, self._board_between(tournament, 2, 'P1', 'P2'), 'P1')
        tournament = self._load()
        for board in tournament.get_round_boards(2):
            assert tournament.knockout.board_advancement(board) is None

    def test_standings_rank_by_level_reached(self, tournament_name):
        tournament = self._load()
        for round_ in range(1, 5):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            # Stronger seed wins every board.
            for board in tournament.get_round_boards(round_):
                white = board.optional_white_tournament_player
                black = board.black_tournament_player
                if black is None:
                    continue
                stronger_white = (
                    white.starting_rank_sort_key <= black.starting_rank_sort_key
                )
                tournament.add_result(
                    board, Result.WIN if stronger_white else Result.LOSS
                )
            tournament = self._load()
        value = {
            player.last_name: tournament.knockout.ranking_value(player, after_round=4)
            for player in tournament.tournament_players
        }
        assert value['P0'] == 3  # champion: levels (2) + 1
        assert value['P1'] == 2  # lost the final (level 2)
        assert value['P2'] == 1  # lost a semi (level 1)
        assert value['P3'] == 1  # lost a semi (level 1)


TWO_GAME_TEAM_EVENT_ID = 'test-two-game-team-knockout'
TWO_GAME_TEAM_NAME = 'two-game-team-ko'


@pytest.mark.unit
class TestTeamTwoGameKnockout:
    """Team single-elimination aller-retour: each match is two legs, White
    orientation forced (leg 1 stronger team board-one White, leg 2 reversed),
    decided on the aggregate game points."""

    @pytest.fixture
    def tournament_name(self):
        from database.sqlite.event.event_store import StoredTeam
        from utils.enum import EventType

        TestUtils.create_event(
            TWO_GAME_TEAM_EVENT_ID, overrides={'event_type': EventType.TEAM}
        )
        TestUtils.create_tournament(
            TWO_GAME_TEAM_EVENT_ID,
            TWO_GAME_TEAM_NAME,
            overrides={
                'rounds': 4,
                'current_round': 1,
                'team_player_count': 1,
                'pairing': 'TEAM_KNOCKOUT_STANDARD_TWO_GAME',
            },
        )
        with EventDatabase(TWO_GAME_TEAM_EVENT_ID, write=True) as database:
            tournament_id = next(
                t.id
                for t in database.load_stored_tournaments()
                if t.name == TWO_GAME_TEAM_NAME
            )
            assert tournament_id is not None
            for index in range(4):
                team_id = database.add_stored_team(
                    StoredTeam(
                        id=None,
                        name=f'Team{index}',
                        tournament_id=tournament_id,
                        pairing_number=index + 1,
                    )
                )
                database.add_stored_player(
                    StoredPlayer(
                        id=None,
                        last_name=f'T{index}P0',
                        team_id=team_id,
                        team_index=0,
                        check_in=True,
                    )
                )
        yield TWO_GAME_TEAM_NAME
        TestUtils.delete_event(TWO_GAME_TEAM_EVENT_ID)

    def _load(self):
        try:
            EventLoader.unload_event(TWO_GAME_TEAM_EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(TWO_GAME_TEAM_EVENT_ID)
        return self._event.tournaments_by_name[TWO_GAME_TEAM_NAME]

    @staticmethod
    def _add_unassigned_tournament_player() -> int:
        with EventDatabase(TWO_GAME_TEAM_EVENT_ID, write=True) as database:
            tournament_id = next(
                t.id
                for t in database.load_stored_tournaments()
                if t.name == TWO_GAME_TEAM_NAME
            )
            assert tournament_id is not None
            player_id = database.add_stored_player(
                StoredPlayer(
                    id=None,
                    last_name='NO_TEAM',
                    check_in=True,
                )
            )
            database.add_stored_tournament_player(
                StoredTournamentPlayer(
                    tournament_id=tournament_id,
                    player_id=player_id,
                )
            )
            return player_id

    @staticmethod
    def _white_teams(tournament, round_):
        return {
            board.optional_white_tournament_player.team.name
            for board in tournament.get_round_boards(round_)
            if board.black_tournament_player is not None
        }

    @staticmethod
    def _team_matches(tournament, round_):
        return {
            frozenset((team_board.team_a.name, team_board.team_b.name))
            for team_board in tournament.get_round_team_boards(round_)
            if team_board.team_b is not None
        }

    @staticmethod
    def _win_stronger(tournament, round_):
        for board in tournament.get_round_boards(round_):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            if black is None:
                continue
            white_stronger = white.team.pairing_number < black.team.pairing_number
            tournament.add_result(board, Result.WIN if white_stronger else Result.LOSS)

    def test_round_count_is_doubled(self, tournament_name):
        tournament = self._load()
        assert tournament.automatic_rounds == 4

    def test_third_place_setting_is_available(self, tournament_name):
        from data.pairings.knockout import KnockoutThirdPlaceSetting

        tournament = self._load()

        assert KnockoutThirdPlaceSetting.static_id() in {
            setting.id for setting in tournament.pairing_variation.settings
        }

    def test_leg_one_forced_orientation_then_reversed(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Leg 1: the two stronger teams take board-one White.
        assert self._white_teams(tournament, 1) == {'Team0', 'Team1'}
        self._win_stronger(tournament, 1)
        tournament = self._load()
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        # Leg 2: reversed orientation.
        assert self._white_teams(tournament, 2) == {'Team2', 'Team3'}

    def test_drawn_leg_one_does_not_block_leg_two(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        for board in tournament.get_round_boards(1):
            if board.black_tournament_player is not None:
                tournament.add_result(board, Result.DRAW)
        tournament = self._load()
        engine = tournament.pairing_variation.engine
        assert engine.pairings_generation_disabled_message(tournament, 2) is None
        assert tournament.generate_round_pairings(2) == ''

    def test_aggregate_decides_and_standings(self, tournament_name):
        tournament = self._load()
        for round_ in range(1, 5):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._win_stronger(tournament, round_)
            tournament = self._load()
        labels = tournament.knockout.team_standing_labels(after_round=4)
        by_name = {team.name: labels[team.id] for team in tournament.teams}
        assert by_name['Team0'] == 'Winner'
        assert by_name['Team1'] == 'Runner-up'
        assert by_name['Team2'] == 'Out — round 1'  # lost a semi (level 1)
        assert by_name['Team3'] == 'Out — round 1'

    def test_third_place_playoff_is_paired_over_two_legs(self, tournament_name):
        from data.pairings.knockout import KnockoutThirdPlaceSetting

        tournament = self._load()
        tournament.update_pairing_settings(
            {KnockoutThirdPlaceSetting.static_id(): True}
        )
        tournament = self._load()

        for round_ in (1, 2):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._win_stronger(tournament, round_)
            tournament = self._load()

        expected_final_level = {
            frozenset(('Team0', 'Team1')),
            frozenset(('Team2', 'Team3')),
        }
        for round_ in (3, 4):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            assert self._team_matches(tournament, round_) == expected_final_level
            self._win_stronger(tournament, round_)
            tournament = self._load()

        labels = tournament.knockout.team_standing_labels(after_round=4)
        by_name = {team.name: labels[team.id] for team in tournament.teams}
        assert by_name['Team0'] == 'Winner'
        assert by_name['Team1'] == 'Runner-up'
        assert by_name['Team2'] == 'Third place'
        assert by_name['Team3'] == 'Fourth place'

    def test_player_ranks_use_team_two_game_bracket(self, tournament_name):
        unassigned_player_id = self._add_unassigned_tournament_player()
        tournament = self._load()
        for round_ in range(1, 5):
            assert tournament.generate_round_pairings(round_) == ''
            tournament = self._load()
            self._win_stronger(tournament, round_)
            tournament = self._load()

        unassigned_player = tournament.tournament_players_by_id[unassigned_player_id]
        assert (
            tournament.knockout.ranking_value(unassigned_player, after_round=4) == 0.0
        )
        tournament.compute_tournament_player_ranks()
        by_rank = tournament.tournament_players_by_rank
        assert by_rank[1].last_name == 'T0P0'
        assert by_rank[2].last_name == 'T1P0'
        assert by_rank[len(by_rank)].last_name == 'NO_TEAM'

    def test_aggregate_tie_blocks_next_level(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        # Leg 1: stronger teams win.
        self._win_stronger(tournament, 1)
        tournament = self._load()
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        # Leg 2: weaker teams win -> 1-1 aggregate, unresolved.
        for board in tournament.get_round_boards(2):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            if black is None:
                continue
            white_stronger = white.team.pairing_number < black.team.pairing_number
            tournament.add_result(board, Result.LOSS if white_stronger else Result.WIN)
        tournament = self._load()
        engine = tournament.pairing_variation.engine
        assert engine.pairings_generation_disabled_message(tournament, 3) is not None


TWO_GAME_DE_EVENT_ID = 'test-two-game-de'
TWO_GAME_DE_NAME = 'two-game-de'


@pytest.mark.unit
class TestDoubleEliminationTwoGame:
    """Individual double elimination aller-retour: every double-elimination
    round is played over two app rounds, decided on the aggregate."""

    @pytest.fixture
    def tournament_name(self):
        TestUtils.create_event(TWO_GAME_DE_EVENT_ID)
        TestUtils.create_tournament(
            TWO_GAME_DE_EVENT_ID,
            TWO_GAME_DE_NAME,
            overrides={
                'rounds': 8,
                'current_round': 1,
                'pairing': 'KNOCKOUT_DOUBLE_ELIMINATION_TWO_GAME',
            },
        )
        with EventDatabase(TWO_GAME_DE_EVENT_ID, write=True) as database:
            tournament_id = next(
                stored.id
                for stored in database.load_stored_tournaments()
                if stored.name == TWO_GAME_DE_NAME
            )
            assert tournament_id is not None
            for index in range(4):
                player_id = database.add_stored_player(
                    StoredPlayer(
                        id=None,
                        last_name=f'P{index}',
                        ratings={1: {'standard': 2000 - index * 10}},
                    )
                )
                database.add_stored_tournament_player(
                    StoredTournamentPlayer(
                        tournament_id=tournament_id, player_id=player_id
                    )
                )
        yield TWO_GAME_DE_NAME
        TestUtils.delete_event(TWO_GAME_DE_EVENT_ID)

    def _load(self):
        try:
            EventLoader.unload_event(TWO_GAME_DE_EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(TWO_GAME_DE_EVENT_ID)
        return self._event.tournaments_by_name[TWO_GAME_DE_NAME]

    @staticmethod
    def _win_stronger(tournament, round_):
        for board in tournament.get_round_boards(round_):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            if black is None:
                continue
            white_stronger = (
                white.starting_rank_sort_key <= black.starting_rank_sort_key
            )
            tournament.add_result(board, Result.WIN if white_stronger else Result.LOSS)

    def test_round_count_is_doubled(self, tournament_name):
        tournament = self._load()
        # 4 players -> double-elim 4 rounds -> 8 app rounds (2 games each).
        assert tournament.automatic_rounds == 8

    def test_drawn_game_one_does_not_block_or_warn(self, tournament_name):
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        for board in tournament.get_round_boards(1):
            if board.black_tournament_player is not None:
                tournament.add_result(board, Result.DRAW)
        tournament = self._load()
        engine = tournament.pairing_variation.engine
        # No warning on game 1, and game 2 is pairable.
        for board in tournament.get_round_boards(1):
            assert tournament.knockout.board_advancement(board) is None
        assert engine.pairings_generation_disabled_message(tournament, 2) is None

    def test_plays_to_a_champion_on_aggregate(self, tournament_name):
        tournament = self._load()
        engine = tournament.pairing_variation.engine
        for round_ in range(1, 9):
            if engine.pairings_generation_disabled_message(tournament, round_):
                break
            if tournament.generate_round_pairings(round_) != '':
                break
            tournament = self._load()
            self._win_stronger(tournament, round_)
            tournament = self._load()
            engine = tournament.pairing_variation.engine
        values = {
            player.last_name: tournament.knockout.ranking_value(
                player, after_round=tournament.rounds
            )
            for player in tournament.tournament_players
        }
        # The top seed wins the winners' bracket and the grand final untouched.
        assert max(values, key=lambda name: values[name]) == 'P0'
        # A double elimination ends by the grand final (with the stronger seed
        # winning it, no reset) -- the tournament is decided.
        assert tournament.pairing_variation.engine.tournament_is_over(tournament)

    def test_leg_two_advancement_does_not_crash(self, tournament_name):
        # Regression: the aggregate tie-warning read a board via _find_board,
        # which the double-elimination engine does not carry as an instance
        # method -- it raised AttributeError when a game-2 board was rendered.
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        self._win_stronger(tournament, 1)
        tournament = self._load()
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        self._win_stronger(tournament, 2)
        tournament = self._load()
        for board in tournament.get_round_boards(2):
            # Must not raise; decided on aggregate, so no tie shown.
            assert tournament.knockout.board_advancement(board) is None


TWO_GAME_TDE_EVENT_ID = 'test-two-game-team-de'
TWO_GAME_TDE_NAME = 'two-game-team-de'


@pytest.mark.unit
class TestTeamDoubleEliminationTwoGame:
    """Team double elimination aller-retour smoke test."""

    @pytest.fixture
    def tournament_name(self):
        from database.sqlite.event.event_store import StoredTeam
        from utils.enum import EventType

        TestUtils.create_event(
            TWO_GAME_TDE_EVENT_ID, overrides={'event_type': EventType.TEAM}
        )
        TestUtils.create_tournament(
            TWO_GAME_TDE_EVENT_ID,
            TWO_GAME_TDE_NAME,
            overrides={
                'rounds': 8,
                'current_round': 1,
                'team_player_count': 1,
                'pairing': 'TEAM_KNOCKOUT_DOUBLE_ELIMINATION_TWO_GAME',
            },
        )
        with EventDatabase(TWO_GAME_TDE_EVENT_ID, write=True) as database:
            tournament_id = next(
                t.id
                for t in database.load_stored_tournaments()
                if t.name == TWO_GAME_TDE_NAME
            )
            assert tournament_id is not None
            for index in range(4):
                team_id = database.add_stored_team(
                    StoredTeam(
                        id=None,
                        name=f'Team{index}',
                        tournament_id=tournament_id,
                        pairing_number=index + 1,
                    )
                )
                database.add_stored_player(
                    StoredPlayer(
                        id=None,
                        last_name=f'T{index}P0',
                        team_id=team_id,
                        team_index=0,
                        check_in=True,
                    )
                )
        yield TWO_GAME_TDE_NAME
        TestUtils.delete_event(TWO_GAME_TDE_EVENT_ID)

    def _load(self):
        try:
            EventLoader.unload_event(TWO_GAME_TDE_EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(TWO_GAME_TDE_EVENT_ID)
        return self._event.tournaments_by_name[TWO_GAME_TDE_NAME]

    @staticmethod
    def _win_stronger(tournament, round_):
        for board in tournament.get_round_boards(round_):
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            if black is None:
                continue
            white_stronger = white.team.pairing_number < black.team.pairing_number
            tournament.add_result(board, Result.WIN if white_stronger else Result.LOSS)

    def test_round_count_is_doubled(self, tournament_name):
        tournament = self._load()
        assert tournament.automatic_rounds == 8

    def test_plays_to_a_champion_on_aggregate(self, tournament_name):
        tournament = self._load()
        engine = tournament.pairing_variation.engine
        for round_ in range(1, 9):
            if engine.pairings_generation_disabled_message(tournament, round_):
                break
            if tournament.generate_round_pairings(round_) != '':
                break
            tournament = self._load()
            self._win_stronger(tournament, round_)
            tournament = self._load()
            engine = tournament.pairing_variation.engine
        labels = tournament.knockout.team_standing_labels(after_round=tournament.rounds)
        by_name = {team.name: labels[team.id] for team in tournament.teams}
        assert by_name['Team0'] == 'Winner'

    def test_leg_two_advancement_does_not_crash(self, tournament_name):
        # Regression (reported from the app): rendering a game-2 team board
        # called _find_team_board, absent as an instance method on the DE
        # engine -> AttributeError.
        tournament = self._load()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._load()
        self._win_stronger(tournament, 1)
        tournament = self._load()
        assert tournament.generate_round_pairings(2) == ''
        tournament = self._load()
        self._win_stronger(tournament, 2)
        tournament = self._load()
        for team_board in tournament.get_round_team_boards(2):
            assert tournament.knockout.team_board_advancement(team_board) is None

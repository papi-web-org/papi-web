"""A team knock-out's stored tie-breaks are its advancement (FIDE Art. 12)
list: they decide which team goes through a level match, the standings stay
fixed to the round reached, and only the tie-breaks that can settle a match
count.
"""

import pytest

from data.loader import EventLoader
from data.tournament import Tournament
from database.sqlite.event.event_database import EventDatabase
from data.tie_breaks.team_tie_breaks import BoardCountTieBreak
from data.tie_breaks.tie_breaks import PointsTieBreak
from tests.test_config import TestUtils
from utils.enum import EventType

EVENT_ID = 'test-ko-advancement-tb'
TOURNAMENT_NAME = 'team-ko'


@pytest.mark.unit
class TestAdvancementTieBreakStorage:
    @pytest.fixture
    def tournament(self):
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        TestUtils.create_tournament(
            EVENT_ID,
            TOURNAMENT_NAME,
            overrides={
                'rounds': 3,
                'team_player_count': 4,
                'pairing': 'TEAM_KNOCKOUT_STANDARD',
            },
        )
        with EventDatabase(EVENT_ID, write=True) as database:
            tid = next(
                t.id
                for t in database.load_stored_tournaments()
                if t.name == TOURNAMENT_NAME
            )
            assert tid is not None
            # Drop the default play-off marker so this test controls the list
            # exactly.
            database.delete_all_tournament_stored_tie_breaks(tid)
            # One advancement tie-break (Board Count) and one lingering Points
            # tie-break (as a Swiss->KO switch might leave behind) — Points is
            # not a valid advancement criterion, so it is filtered out.
            advancement = BoardCountTieBreak().to_stored_value()
            advancement.tournament_id = tid
            advancement.index = 0
            database.add_stored_tie_break(advancement)

            points = PointsTieBreak().to_stored_value()
            points.tournament_id = tid
            points.index = 1
            database.add_stored_tie_break(points)
        self._event = EventLoader().load_event(EVENT_ID)
        yield self._event.tournaments_by_name[TOURNAMENT_NAME]
        TestUtils.delete_event(EVENT_ID)

    def test_advancement_list_keeps_only_the_usable_tie_breaks(self, tournament):
        # The advancement list carries the Art. 12 tie-break, filtering out the
        # stored Points that cannot decide a match.
        assert [tb.id for tb in tournament.advancement_tie_breaks] == [
            BoardCountTieBreak().id
        ]
        # Both rows are on the single stored list, though.
        assert {BoardCountTieBreak().id, PointsTieBreak().id} <= {
            tb.id for tb in tournament.tie_breaks_by_id.values()
        }

    def test_knockout_standings_ignore_configured_tie_breaks(self, tournament):
        # Even with a Points tie-break stored, a knock-out's standings are
        # forced to the round reached (the default points list), never the
        # stored list.
        assert tournament.tie_breaks == tournament._default_tie_breaks

    def test_add_tie_break_joins_the_stored_advancement_list(self, tournament):
        from data.tie_breaks.team_tie_breaks import TopBoardResultsTieBreak

        before = set(tournament.tie_breaks_by_id)
        tournament.add_tie_break(TopBoardResultsTieBreak())
        # The new tie-break joined the single list and shows in the advancement
        # list (it can decide a match).
        assert TopBoardResultsTieBreak().id in [
            tb.id for tb in tournament.advancement_tie_breaks
        ]
        assert set(tournament.tie_breaks_by_id) > before

    def test_advancement_list_may_be_emptied(self, tournament):
        # A standings list must keep one criterion; a knock-out's advancement
        # list may go to zero (a play-off decides then), so deleting all is fine.
        for tie_break_id in list(tournament.tie_breaks_by_id):
            tournament.delete_tie_break(tie_break_id)
        assert tournament.tie_breaks_by_id == {}


DEFAULTS_EVENT_ID = 'test-ko-tb-defaults'


@pytest.mark.unit
class TestCreateDefaultTieBreaks:
    """A new knock-out defaults to the play-off marker only — no Points, which
    is meaningless for its (round-reached) standings; other systems default to
    Points."""

    def teardown_method(self):
        try:
            TestUtils.delete_event(DEFAULTS_EVENT_ID)
        except Exception:
            pass

    def _created(self, pairing: str, team: bool):
        from data.tie_breaks.tie_breaks import ManualTieBreak

        overrides = {'event_type': EventType.TEAM} if team else {}
        TestUtils.create_event(DEFAULTS_EVENT_ID, overrides=overrides)
        tournament_overrides: dict[str, object] = {'pairing': pairing}
        if team:
            tournament_overrides['team_player_count'] = 2
        TestUtils.create_tournament(
            DEFAULTS_EVENT_ID, 'tourney', overrides=tournament_overrides
        )
        # Hold the event so the tournament's weak back-reference survives.
        self._event = EventLoader().load_event(DEFAULTS_EVENT_ID)
        tournament = self._event.tournaments_by_name['tourney']
        types = {tb.id for tb in tournament.tie_breaks_by_id.values()}
        return types, ManualTieBreak().id

    @pytest.mark.parametrize(
        'pairing',
        [
            'KNOCKOUT_STANDARD',
            'KNOCKOUT_DOUBLE_ELIMINATION',
            'KNOCKOUT_STANDARD_TWO_GAME',
        ],
    )
    def test_knockout_defaults_to_the_play_off_marker_only(self, pairing):
        types, manual_id = self._created(pairing, team=False)
        assert types == {manual_id}
        assert PointsTieBreak().id not in types

    def test_team_knockout_defaults_to_the_play_off_marker_only(self):
        types, manual_id = self._created('TEAM_KNOCKOUT_STANDARD', team=True)
        assert types == {manual_id}

    def test_a_swiss_defaults_to_points(self):
        types, _ = self._created('SWISS_STANDARD', team=False)
        assert types == {PointsTieBreak().id}


TB_EVENT_ID = 'test-ko-advancement-resolver'
TB_TOURNAMENT = 'team-ko-resolver'


@pytest.mark.unit
class TestAdvancementResolver:
    """A level team match is decided by the advancement tie-breaks (BC)."""

    @pytest.fixture
    def tournament(self):
        from database.sqlite.event.event_store import StoredPlayer, StoredTeam

        TestUtils.create_event(TB_EVENT_ID, overrides={'event_type': EventType.TEAM})
        TestUtils.create_tournament(
            TB_EVENT_ID,
            TB_TOURNAMENT,
            overrides={
                'rounds': 1,
                'current_round': 1,
                'team_player_count': 2,
                'pairing': 'TEAM_KNOCKOUT_STANDARD',
            },
        )
        with EventDatabase(TB_EVENT_ID, write=True) as database:
            tid = next(
                t.id
                for t in database.load_stored_tournaments()
                if t.name == TB_TOURNAMENT
            )
            assert tid is not None
            for team_index in range(2):
                team_id = database.add_stored_team(
                    StoredTeam(
                        id=None,
                        name=f'Team{team_index}',
                        tournament_id=tid,
                        pairing_number=team_index + 1,
                    )
                )
                for board in range(2):
                    database.add_stored_player(
                        StoredPlayer(
                            id=None,
                            last_name=f'T{team_index}B{board}',
                            team_id=team_id,
                            team_index=board,
                            check_in=True,
                        )
                    )
            # Board Count as the only advancement tie-break (drop the
            # default play-off marker first).
            database.delete_all_tournament_stored_tie_breaks(tid)
            bc = BoardCountTieBreak().to_stored_value()
            bc.tournament_id = tid
            bc.index = 0
            database.add_stored_tie_break(bc)
        self._event = EventLoader().load_event(TB_EVENT_ID)
        yield self._event.tournaments_by_name[TB_TOURNAMENT]
        TestUtils.delete_event(TB_EVENT_ID)

    def _reload(self):
        try:
            EventLoader.unload_event(TB_EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(TB_EVENT_ID)
        return self._event.tournaments_by_name[TB_TOURNAMENT]

    def test_board_count_breaks_a_level_match(self, tournament):
        from utils.enum import Result

        assert tournament.generate_round_pairings(1) == ''
        tournament = self._reload()
        # Every board is a White win. With the WB colour pattern, team_a
        # takes board 1 (the top board) and team_b takes board 2, so the
        # match is level 1-1 on game points.
        for board in tournament.get_round_boards(1):
            tournament.add_result(board, Result.WIN)
        tournament = self._reload()

        team_board = tournament.team_boards_by_round[1][0]
        stb = team_board.stored_team_board
        a_gp, b_gp = team_board.effective_game_points
        assert a_gp == b_gp  # genuinely level on game points

        # Board Count rewards points on the top boards, so team_a (which
        # won board 1) advances.
        advancement = tournament.knockout.team_advancement(team_board)
        assert advancement.winner_id == stb.team_a_id
        # The breakdown records Board Count's values for both teams, marked
        # decisive, so the arbiter can see the working.
        assert len(advancement.breakdown) == 1
        row = advancement.breakdown[0]
        assert row.acronym == BoardCountTieBreak().acronym
        assert row.decisive is True
        assert row.value_a != row.value_b

    def test_advancement_hidden_until_match_complete(self, tournament):
        from utils.enum import Result

        assert tournament.generate_round_pairings(1) == ''
        tournament = self._reload()
        # Play only the first of the two boards, as a draw: the match sits
        # level on game points (0.5-0.5) but is not finished. No tie warning
        # or play-off should appear yet.
        tournament.add_result(tournament.get_round_boards(1)[0], Result.DRAW)
        tournament = self._reload()

        team_board = tournament.team_boards_by_round[1][0]
        assert not team_board.all_games_played
        a_gp, b_gp = team_board.effective_game_points
        assert a_gp == b_gp  # level so far, but only because it is unfinished
        assert tournament.knockout.team_board_advancement(team_board) is None
        assert tournament.knockout.unresolved_matches(1) == []

    def test_manual_playoff_designation(self, tournament):
        from data.tie_breaks.tie_breaks import ManualTieBreak
        from utils.enum import Result

        # Replace Board Count with the play-off (manual) marker, so nothing
        # computed can settle the level match.
        (bc_id,) = tournament.tie_breaks_by_id.keys()
        tournament.delete_tie_break(bc_id)
        manual = ManualTieBreak().to_stored_value()
        with EventDatabase(TB_EVENT_ID, write=True) as database:
            tid = next(
                t.id
                for t in database.load_stored_tournaments()
                if t.name == TB_TOURNAMENT
            )
            assert tid is not None
            manual.tournament_id = tid
            manual.index = 0
            database.add_stored_tie_break(manual)

        tournament = self._reload()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._reload()
        for board in tournament.get_round_boards(1):
            tournament.add_result(board, Result.WIN)  # 1-1 level match
        tournament = self._reload()

        team_board = tournament.team_boards_by_round[1][0]
        stb = team_board.stored_team_board
        # Nothing settles it yet -> it is listed as unresolved, no winner.
        assert tournament.knockout.advancement_has_manual is True
        unresolved = tournament.knockout.unresolved_matches(1)
        assert [match['id'] for match in unresolved] == [team_board.id]
        assert tournament.knockout.advancement_winner(team_board) is None

        # Designate the winner; now the match resolves and the list clears.
        tournament.knockout.set_team_match_winner(team_board.id, stb.team_b_id)
        tournament = self._reload()
        team_board = tournament.team_boards_by_round[1][0]
        assert tournament.knockout.advancement_winner(team_board) == stb.team_b_id
        assert tournament.knockout.unresolved_matches(1) == []

    def test_tie_break_after_the_decider_is_marked_unused(self, tournament):
        from data.tie_breaks.tie_breaks import ManualTieBreak
        from utils.enum import Result

        # Add a Manual play-off after the (decisive) Board Count.
        with EventDatabase(TB_EVENT_ID, write=True) as database:
            tid = next(
                t.id
                for t in database.load_stored_tournaments()
                if t.name == TB_TOURNAMENT
            )
            assert tid is not None
            manual = ManualTieBreak().to_stored_value()
            manual.tournament_id = tid
            manual.index = 1
            database.add_stored_tie_break(manual)

        tournament = self._reload()
        assert tournament.generate_round_pairings(1) == ''
        tournament = self._reload()
        for board in tournament.get_round_boards(1):
            tournament.add_result(board, Result.WIN)  # 1-1 level match
        tournament = self._reload()

        team_board = tournament.team_boards_by_round[1][0]
        advancement = tournament.knockout.team_advancement(team_board)
        # Board Count decides, so it is used; the Manual row below it never
        # gets consulted and is greyed out (used False, disabled in the UI).
        bc_row, manual_row = advancement.breakdown
        assert bc_row.decisive is True and bc_row.used is True
        assert manual_row.is_manual is True
        assert manual_row.used is False
        assert advancement.manual_reached is False


DEF_EVENT_ID = 'test-ko-defaults'


@pytest.mark.unit
class TestKnockoutCreationDefault:
    def _make(self, pairing: str, overrides: dict | None = None) -> Tournament:
        TestUtils.create_event(DEF_EVENT_ID, overrides={'event_type': EventType.TEAM})
        TestUtils.create_tournament(
            DEF_EVENT_ID,
            'ko',
            overrides={'pairing': pairing, 'rounds': 2} | (overrides or {}),
        )
        self._event = EventLoader().load_event(DEF_EVENT_ID)
        return self._event.tournaments_by_name['ko']

    def teardown_method(self):
        try:
            TestUtils.delete_event(DEF_EVENT_ID)
        except Exception:
            pass

    def test_team_knockout_gets_the_playoff_marker_by_default(self):
        tournament = self._make('TEAM_KNOCKOUT_STANDARD')
        assert any(tb.is_manual for tb in tournament.advancement_tie_breaks)

    def test_individual_knockout_gets_the_playoff_marker_by_default(self):
        tournament = self._make(
            'KNOCKOUT_STANDARD', overrides={'team_player_count': None}
        )
        assert any(tb.is_manual for tb in tournament.advancement_tie_breaks)

    def test_swiss_has_no_advancement_tie_breaks(self):
        tournament = self._make('SWISS_STANDARD')
        assert tournament.advancement_tie_breaks == []


@pytest.mark.unit
class TestManualNotLastWarning:
    def test_flags_a_tie_break_after_the_playoff_marker(self):
        from data.tie_breaks.team_tie_breaks import BoardCountTieBreak
        from data.tie_breaks.tie_breaks import ManualTieBreak

        TestUtils.create_event(DEF_EVENT_ID, overrides={'event_type': EventType.TEAM})
        TestUtils.create_tournament(
            DEF_EVENT_ID,
            'ko',
            overrides={'pairing': 'TEAM_KNOCKOUT_STANDARD', 'rounds': 2},
        )
        with EventDatabase(DEF_EVENT_ID, write=True) as database:
            tid = next(
                t.id for t in database.load_stored_tournaments() if t.name == 'ko'
            )
            assert tid is not None
            database.delete_all_tournament_stored_tie_breaks(tid)
            for index, tie_break in enumerate([ManualTieBreak(), BoardCountTieBreak()]):
                stored = tie_break.to_stored_value()
                stored.tournament_id = tid
                stored.index = index
                database.add_stored_tie_break(stored)
        event = EventLoader().load_event(DEF_EVENT_ID)
        tournament = event.tournaments_by_name['ko']
        # Board Count sits below the play-off marker, so it can never apply.
        assert tournament.advancement_tie_breaks_after_manual is True
        TestUtils.delete_event(DEF_EVENT_ID)

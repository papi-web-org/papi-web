"""Match points scored by an absent team.

A team that forfeits its whole match, or is left unpaired as absent,
takes the tournament's absence match points (``mp_zpb``, stored under
``ZERO_POINT_BYE``), and defaults to the Loss value when none is set.
The FFE cups need the distinction: there a match lost over the board is
worth 1 match point and a match lost by forfeit 0.
"""

from unittest import TestCase

import pytest

from data.loader import EventLoader
from data.tie_breaks.team_records import TeamMatchType
from data.teams.team import Team
from data.tournament import Tournament
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredPlayer,
    StoredTeam,
    StoredTournamentPlayer,
)
from tests.test_config import TestUtils
from utils.enum import EventType, Result, ScoreType, TeamByeType


EVENT_ID = 'test-team-absent-match-points'
TOURNAMENT_NAME = 'tournament'
N = 2  # boards per match
TEAMS = 4

# The FFE cup scheme: a match played and lost is still worth a point,
# one lost by forfeit nothing.
_CUP_MATCH_POINTS = {
    Result.WIN.value: 3.0,
    Result.DRAW.value: 2.0,
    Result.LOSS.value: 1.0,
    Result.ZERO_POINT_BYE.value: 0.0,
}


class _AbsentMatchPointsHarness(TestCase):
    """A four-team round-robin scored on match points, with the cup
    scheme in force and a helper to forfeit a whole match."""

    def tearDown(self) -> None:
        TestUtils.delete_event(EVENT_ID)

    def _create(
        self, match_points: dict[int, float], rule_set: str | None = None
    ) -> None:
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        stored_tournament = TestUtils.create_tournament(
            EVENT_ID,
            TOURNAMENT_NAME,
            overrides={
                'rounds': TEAMS - 1,
                'current_round': 1,
                'team_player_count': N,
                'pairing': 'TEAM_ROUND_ROBIN_BERGER',
                'primary_score': ScoreType.MATCH_POINTS,
                'match_points': match_points,
                'rule_set': rule_set,
            },
        )
        self.team_ids: list[int] = []
        tournament_id = stored_tournament.id
        assert tournament_id is not None
        with EventDatabase(EVENT_ID, write=True) as database:
            for seed in range(1, TEAMS + 1):
                team_id = database.add_stored_team(
                    StoredTeam(
                        id=None,
                        name=f'Team{seed}',
                        tournament_id=tournament_id,
                        pairing_number=seed,
                        check_in=True,
                    )
                )
                self.team_ids.append(team_id)
                for index in range(N):
                    player_id = database.add_stored_player(
                        StoredPlayer(
                            id=None,
                            last_name=f'T{seed}P{index}',
                            team_id=team_id,
                            team_index=index,
                            check_in=True,
                        )
                    )
                    database.add_stored_tournament_player(
                        StoredTournamentPlayer(
                            tournament_id=tournament_id,
                            player_id=player_id,
                            pairing_number=index + 1,
                        )
                    )

    def _load(self) -> Tournament:
        try:
            EventLoader.unload_event(EVENT_ID)
        except KeyError:
            pass
        # A Tournament holds its event weakly, so the event has to
        # outlive this call.
        self._event = EventLoader().load_event(EVENT_ID)
        return self._event.tournaments_by_name[TOURNAMENT_NAME]

    def _forfeit_round_one(self, tournament: Tournament, team_id: int):
        """Every board of the team's round-1 match forfeited by it."""
        team_board = self._round_one_match(tournament, team_id)
        for board in team_board.boards:
            white_team_id, _ = team_board.board_team_ids(board)
            tournament.add_result(
                board,
                Result.FORFEIT_LOSS if white_team_id == team_id else Result.FORFEIT_WIN,
            )
        return self._load()

    @staticmethod
    def _row(tournament: Tournament, team_id: int) -> dict:
        return next(
            entry
            for entry in tournament.team_standings()
            if entry['team'].id == team_id
        )

    @classmethod
    def _mp(cls, tournament: Tournament, team_id: int) -> float:
        return cls._row(tournament, team_id)['mp']

    def _round_one_match(self, tournament: Tournament, team_id: int):
        return next(
            tb
            for tb in tournament.get_round_team_boards(1)
            if team_id
            in (tb.stored_team_board.team_a_id, tb.stored_team_board.team_b_id)
        )

    def _opponent_id(self, tournament: Tournament, team_id: int) -> int:
        stb = self._round_one_match(tournament, team_id).stored_team_board
        assert stb.team_b_id is not None
        return stb.team_b_id if stb.team_a_id == team_id else stb.team_a_id

    def _assert_tally_adds_up(self, tournament: Tournament) -> None:
        """Every round a team was in is one of the four outcomes."""
        for entry in tournament.team_standings():
            self.assertEqual(
                entry['wins'] + entry['draws'] + entry['losses'] + entry['forfeits'],
                entry['played'],
                f'the tally does not add up for {entry["team"].name}',
            )


@pytest.mark.unit
class TeamAbsentMatchPointsTestCase(_AbsentMatchPointsHarness):
    def test_forfeited_match_scores_the_absence_value(self) -> None:
        self._create(_CUP_MATCH_POINTS)
        tournament = self._load()
        self.assertEqual(tournament.generate_round_pairings(1), '')
        tournament = self._load()
        forfeit_id = self.team_ids[0]
        opponent_id = self._opponent_id(tournament, forfeit_id)
        tournament = self._forfeit_round_one(tournament, forfeit_id)
        self.assertEqual(self._mp(tournament, forfeit_id), 0.0)
        self.assertEqual(self._mp(tournament, opponent_id), 3.0)
        self._assert_tally_adds_up(tournament)

    def test_forfeited_match_falls_back_to_the_loss_value(self) -> None:
        """No absence value set: the forfeiting team scores a loss, as it
        did before the value existed."""
        match_points = dict(_CUP_MATCH_POINTS)
        del match_points[Result.ZERO_POINT_BYE.value]
        self._create(match_points)
        tournament = self._load()
        self.assertEqual(tournament.generate_round_pairings(1), '')
        tournament = self._load()
        forfeit_id = self.team_ids[0]
        tournament = self._forfeit_round_one(tournament, forfeit_id)
        self.assertEqual(self._mp(tournament, forfeit_id), 1.0)

    def test_the_match_score_shows_the_absence_value(self) -> None:
        self._create(_CUP_MATCH_POINTS)
        tournament = self._load()
        self.assertEqual(tournament.generate_round_pairings(1), '')
        tournament = self._load()
        forfeit_id = self.team_ids[0]
        tournament = self._forfeit_round_one(tournament, forfeit_id)
        team_board = self._round_one_match(tournament, forfeit_id)
        expected = (
            ('0', '3')
            if team_board.stored_team_board.team_a_id == forfeit_id
            else ('3', '0')
        )
        self.assertEqual(team_board.match_score_pair, expected)
        self.assertEqual(
            team_board.match_score_display, f'{expected[0]} – {expected[1]}'
        )

    def test_a_forfeited_match_is_tallied_as_a_forfeit_not_a_loss(self) -> None:
        """The ranking table's F column: a match forfeited outright leaves
        the L column, so a loss is one taken over the board."""
        self._create(_CUP_MATCH_POINTS)
        tournament = self._load()
        self.assertEqual(tournament.generate_round_pairings(1), '')
        tournament = self._load()
        forfeit_id = self.team_ids[0]
        opponent_id = self._opponent_id(tournament, forfeit_id)
        tournament = self._forfeit_round_one(tournament, forfeit_id)
        forfeit_row = self._row(tournament, forfeit_id)
        self.assertEqual(forfeit_row['forfeits'], 1)
        self.assertEqual(forfeit_row['losses'], 0)
        self.assertEqual(forfeit_row['played'], 1)
        opponent_row = self._row(tournament, opponent_id)
        self.assertEqual(opponent_row['wins'], 1)
        self.assertEqual(opponent_row['forfeits'], 0)

    def test_a_forfeited_match_is_not_a_played_round(self) -> None:
        """No game was played on the forfeiting team's side, so neither
        team's round is a played one — the absent team gave it up, its
        opponent won it by forfeit. The scores are unaffected."""
        self._create(_CUP_MATCH_POINTS)
        tournament = self._load()
        self.assertEqual(tournament.generate_round_pairings(1), '')
        tournament = self._load()
        forfeit_id = self.team_ids[0]
        opponent_id = self._opponent_id(tournament, forfeit_id)
        tournament = self._forfeit_round_one(tournament, forfeit_id)
        matches = {
            record.team_id: record.matches[0] for record in tournament.team_records()
        }
        self.assertEqual(matches[forfeit_id].match_type, TeamMatchType.FORFEIT_LOSS)
        self.assertTrue(matches[forfeit_id].voluntary_unplayed)
        self.assertEqual(matches[forfeit_id].own_mp, 0.0)
        self.assertEqual(matches[opponent_id].match_type, TeamMatchType.FORFEIT_WIN)
        self.assertFalse(matches[opponent_id].voluntary_unplayed)
        self.assertEqual(matches[opponent_id].own_mp, 3.0)

    def test_a_contested_match_stays_a_played_round(self) -> None:
        """One game over the board is enough: a team with three boards
        forfeited has not forfeited the match."""
        self._create(_CUP_MATCH_POINTS)
        tournament = self._load()
        self.assertEqual(tournament.generate_round_pairings(1), '')
        tournament = self._load()
        team_id = self.team_ids[0]
        team_board = self._round_one_match(tournament, team_id)
        for index, board in enumerate(team_board.boards):
            white_team_id, _ = team_board.board_team_ids(board)
            if index == 0:
                tournament.add_result(
                    board,
                    Result.WIN if white_team_id == team_id else Result.LOSS,
                )
                continue
            tournament.add_result(
                board,
                Result.FORFEIT_LOSS if white_team_id == team_id else Result.FORFEIT_WIN,
            )
        tournament = self._load()
        matches = {
            record.team_id: record.matches[0] for record in tournament.team_records()
        }
        self.assertEqual(matches[team_id].match_type, TeamMatchType.PLAYED)

    def test_a_team_left_unpaired_as_absent_scores_the_absence_value(self) -> None:
        """The other absence: no match at all, the team marked absent for
        the round. It is tallied as an absence too, not as a loss."""
        self._create(_CUP_MATCH_POINTS)
        absent_id = self.team_ids[0]
        team: Team = self._load().event.teams_by_id[absent_id]
        with EventDatabase(EVENT_ID, write=True) as database:
            team.set_round_bye(1, TeamByeType.ZPB, database)
        tournament = self._load()
        self.assertEqual(self._mp(tournament, absent_id), 0.0)
        self._assert_tally_adds_up(tournament)
        row = self._row(tournament, absent_id)
        self.assertEqual(row['forfeits'], 1)
        self.assertEqual(row['losses'], 0)
        self.assertEqual(row['played'], 1)


@pytest.mark.unit
class LoubatiereForfeitedMatchTestCase(_AbsentMatchPointsHarness):
    """The FFE cup scores a forfeited match through the absence value.

    C03: a match played and lost is worth 1 match point, one lost by
    forfeit 0. The per-board penalty for a game lost by forfeit (-1 game
    point) stands on top.
    """

    RULE_SET = 'ffe-coupe-jean-claude-loubatiere'

    def test_the_rule_set_takes_no_match_point_off(self) -> None:
        self._create(_CUP_MATCH_POINTS, rule_set=self.RULE_SET)
        tournament = self._load()
        self.assertIsNotNone(tournament.rule_set)
        self.assertEqual(tournament.generate_round_pairings(1), '')
        tournament = self._load()
        forfeit_id = self.team_ids[0]
        opponent_id = self._opponent_id(tournament, forfeit_id)
        tournament = self._forfeit_round_one(tournament, forfeit_id)

        rule_set = tournament.rule_set
        assert rule_set is not None
        team = tournament.event.teams_by_id[forfeit_id]
        adjustment = rule_set.team_point_adjustment(team, 1)
        # The forfeited games still cost a game point each; the match
        # points come from the absence value, not from an adjustment.
        assert adjustment is not None
        self.assertEqual(adjustment.mp, 0.0)
        self.assertLess(adjustment.gp, 0.0)

        self.assertEqual(self._mp(tournament, forfeit_id), 0.0)
        self.assertEqual(self._mp(tournament, opponent_id), 3.0)

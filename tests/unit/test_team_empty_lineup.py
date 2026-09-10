"""A team can be set to field nobody for a round.

The lineup holds a row per board, empty boards included, so a lineup
that seats nobody is a lineup of the team's own — it survives a reload,
the round does not go back to taking the previous round's, and pairing
the round seats nobody.
"""

from unittest import TestCase

import pytest

from data.loader import EventLoader
from data.teams.team import Team
from data.tournament import Tournament
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredPlayer,
    StoredTeam,
    StoredTournamentPlayer,
)
from tests.test_config import TestUtils
from data.tie_breaks.team_records import TeamMatchType
from utils.enum import EventType, Result, TeamByeType


EVENT_ID = 'test-team-empty-lineup'
TOURNAMENT_NAME = 'tournament'
N = 4  # boards per match
TEAMS = 4
ROUNDS = 3


class _TeamLineupHarness(TestCase):
    """One team tournament of four teams over three rounds, none of it
    paired, with every player on a roster."""

    def setUp(self) -> None:
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        stored_tournament = TestUtils.create_tournament(
            EVENT_ID,
            TOURNAMENT_NAME,
            overrides={
                'rounds': ROUNDS,
                'current_round': 1,
                'team_player_count': N,
                'pairing': 'TEAM_SWISS_STANDARD',
            },
        )
        self.team_ids: list[int] = []
        self.player_ids: list[list[int]] = []
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
                ids: list[int] = []
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
                    ids.append(player_id)
                self.player_ids.append(ids)

    def tearDown(self) -> None:
        TestUtils.delete_event(EVENT_ID)

    def _load(self) -> Tournament:
        try:
            EventLoader.unload_event(EVENT_ID)
        except KeyError:
            pass
        # A Tournament holds its event weakly, so the event has to
        # outlive this call.
        self._event = EventLoader().load_event(EVENT_ID)
        return self._event.tournaments_by_name[TOURNAMENT_NAME]

    def _team(self, tournament: Tournament, index: int = 0) -> Team:
        return tournament.event.teams_by_id[self.team_ids[index]]

    def _bench_everyone(self, round_: int) -> Tournament:
        with EventDatabase(EVENT_ID, write=True) as database:
            self._team(self._load(), 0).set_round_lineup(round_, [None] * N, database)
        return self._load()

    @staticmethod
    def _slot_names(slots) -> list[str | None]:
        return [player.last_name if player is not None else None for player in slots]


@pytest.mark.unit
class TeamEmptyLineupTestCase(_TeamLineupHarness):
    def test_an_empty_lineup_survives_a_reload(self) -> None:
        team = self._team(self._bench_everyone(1))
        self.assertTrue(team.has_explicit_round_lineup(1))
        self.assertEqual(team.lineup_source(1), 'explicit')
        self.assertEqual(self._slot_names(team.effective_round_slots(1)), [None] * N)
        self.assertEqual(team.effective_round_lineup(1), [])

    def test_a_later_round_can_field_nobody_on_its_own(self) -> None:
        """A round of its own, ahead of the rounds before it being
        played: rounds 1 and 2 keep the roster, round 3 seats nobody."""
        team = self._team(self._bench_everyone(3))
        self.assertEqual(
            self._slot_names(team.effective_round_slots(1)),
            ['T1P0', 'T1P1', 'T1P2', 'T1P3'],
        )
        self.assertEqual(team.lineup_source(2), 'previous')
        self.assertEqual(self._slot_names(team.effective_round_slots(3)), [None] * N)

    def test_pairing_the_round_seats_nobody(self) -> None:
        tournament = self._bench_everyone(1)
        self.assertEqual(tournament.generate_round_pairings(1), '')
        tournament = self._load()
        team = self._team(tournament)
        self.assertEqual(self._slot_names(team.round_board_slots(1)), [None] * N)

    def test_putting_the_team_back_still_works(self) -> None:
        self._bench_everyone(1)
        with EventDatabase(EVENT_ID, write=True) as database:
            self._team(self._load(), 0).set_round_lineup(
                1, self.player_ids[0], database
            )
        team = self._team(self._load())
        self.assertEqual(
            self._slot_names(team.effective_round_slots(1)),
            ['T1P0', 'T1P1', 'T1P2', 'T1P3'],
        )

    def test_a_hole_keeps_its_board(self) -> None:
        """A lineup with one board left empty seats the others where they
        stand, rather than closing the gap."""
        with EventDatabase(EVENT_ID, write=True) as database:
            self._team(self._load(), 0).set_round_lineup(
                1,
                [self.player_ids[0][0], None, self.player_ids[0][2], None],
                database,
            )
        team = self._team(self._load())
        self.assertEqual(
            self._slot_names(team.effective_round_slots(1)),
            ['T1P0', None, 'T1P2', None],
        )
        self.assertEqual(
            [player.last_name for player in team.effective_round_lineup(1)],
            ['T1P0', 'T1P2'],
        )


@pytest.mark.unit
class TeamByeRecordsTestCase(_TeamLineupHarness):
    """What a bye is worth to the tie-breaks, per bye type.

    The standings and the tie-break records read the same regulations,
    so a bye scores the same on both sides, and its match type says
    whether the round was given up voluntarily (Art. 16.5).
    """

    ABSENT_MP = 0.0
    DRAW_MP = 2.0
    WIN_MP = 3.0
    PAB_MP = 3.0

    def setUp(self) -> None:
        super().setUp()
        with EventDatabase(EVENT_ID, write=True) as database:
            stored_tournament = next(
                stored
                for stored in database.load_stored_tournaments()
                if stored.name == TOURNAMENT_NAME
            )
            stored_tournament.match_points = {
                Result.WIN.value: self.WIN_MP,
                Result.DRAW.value: self.DRAW_MP,
                Result.LOSS.value: 1.0,
                Result.ZERO_POINT_BYE.value: self.ABSENT_MP,
                Result.PAIRING_ALLOCATED_BYE.value: self.PAB_MP,
            }
            database.update_stored_tournament(stored_tournament)

    def _bye_record(self, bye_type: str):
        team_id = self.team_ids[0]
        with EventDatabase(EVENT_ID, write=True) as database:
            self._team(self._load(), 0).set_round_bye(1, bye_type, database)
        tournament = self._load()
        record = next(
            record for record in tournament.team_records() if record.team_id == team_id
        )
        self.assertEqual(len(record.matches), 1)
        standings_mp = next(
            entry['mp']
            for entry in tournament.team_standings()
            if entry['team'].id == team_id
        )
        return record.matches[0], standings_mp

    def test_a_team_marked_absent_gives_the_round_up(self) -> None:
        match, standings_mp = self._bye_record(TeamByeType.ZPB)
        self.assertEqual(match.match_type, TeamMatchType.ZPB)
        self.assertEqual(match.own_mp, self.ABSENT_MP)
        self.assertEqual(match.own_mp, standings_mp)
        self.assertTrue(match.voluntary_unplayed)

    def test_a_half_point_bye_is_worth_a_drawn_match(self) -> None:
        match, standings_mp = self._bye_record(TeamByeType.HPB)
        self.assertEqual(match.match_type, TeamMatchType.HPB)
        self.assertEqual(match.own_mp, self.DRAW_MP)
        self.assertEqual(match.own_mp, standings_mp)
        self.assertTrue(match.voluntary_unplayed)

    def test_a_full_point_bye_is_worth_a_won_match(self) -> None:
        match, standings_mp = self._bye_record(TeamByeType.FPB)
        self.assertEqual(match.own_mp, self.WIN_MP)
        self.assertEqual(match.own_mp, standings_mp)
        self.assertFalse(match.voluntary_unplayed)

    def test_a_pairing_allocated_bye_keeps_its_own_value(self) -> None:
        match, standings_mp = self._bye_record(TeamByeType.PAB)
        self.assertEqual(match.match_type, TeamMatchType.PAB)
        self.assertEqual(match.own_mp, self.PAB_MP)
        self.assertEqual(match.own_mp, standings_mp)
        self.assertFalse(match.voluntary_unplayed)


@pytest.mark.unit
class TeamMatchIndexTestCase(_TeamLineupHarness):
    """The index of each team's match per round follows the pairings.

    It is what every lineup read looks a team's match up in, so it has
    to be rebuilt whenever a round is paired, unpaired or byed.
    """

    def test_pairing_a_round_indexes_both_teams(self) -> None:
        tournament = self._load()
        self.assertEqual(tournament.team_match_by_team_and_round, {})
        self.assertEqual(tournament.generate_round_pairings(1), '')
        tournament = self._load()
        index = tournament.team_match_by_team_and_round
        self.assertEqual(len(index), TEAMS)
        for team_id in self.team_ids:
            team_board = index[(team_id, 1)]
            stb = team_board.stored_team_board
            self.assertIn(team_id, (stb.team_a_id, stb.team_b_id))
            self.assertEqual(team_board.round, 1)

    def test_unpairing_a_match_drops_both_its_teams(self) -> None:
        tournament = self._load()
        self.assertEqual(tournament.generate_round_pairings(1), '')
        tournament = self._load()
        self.assertEqual(len(tournament.team_match_by_team_and_round), TEAMS)
        team_board = tournament.get_round_team_boards(1)[0]
        stb = team_board.stored_team_board
        assert stb.team_b_id is not None
        unpaired = (stb.team_a_id, stb.team_b_id)
        tournament.unpair_team_board(team_board)
        index = tournament.team_match_by_team_and_round
        self.assertEqual(len(index), TEAMS - 2)
        for team_id in unpaired:
            self.assertIsNone(index.get((team_id, 1)))

    def test_a_bye_is_not_a_match(self) -> None:
        """A bye envelope has no opponent and no boards, so the team has
        no match that round."""
        team_id = self.team_ids[0]
        with EventDatabase(EVENT_ID, write=True) as database:
            self._team(self._load(), 0).set_round_bye(1, TeamByeType.ZPB, database)
        tournament = self._load()
        self.assertIsNone(tournament.team_match_by_team_and_round.get((team_id, 1)))

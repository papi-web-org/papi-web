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
from utils.enum import EventType


EVENT_ID = 'test-team-empty-lineup'
TOURNAMENT_NAME = 'tournament'
N = 4  # boards per match
TEAMS = 4
ROUNDS = 3


@pytest.mark.unit
class TeamEmptyLineupTestCase(TestCase):
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

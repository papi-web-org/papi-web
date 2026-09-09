"""A round with no lineup of its own takes the previous round's.

Once the previous round is paired, its lineup is what stands on its
boards — the boards the team left empty included. What the next round
shows, and who it seats when it is paired, follow from that.
"""

from unittest import TestCase

import pytest

from data.loader import EventLoader
from data.tournament import Tournament
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredPlayer,
    StoredTeam,
    StoredTournamentPlayer,
)
from tests.test_config import TestUtils
from utils.enum import EventType, Result
from web.controllers.admin.team_admin_controller import TeamAdminController


EVENT_ID = 'test-team-lineup-inheritance'
TOURNAMENT_NAME = 'tournament'
N = 4  # boards per match
TEAMS = 4


@pytest.mark.unit
class TeamLineupInheritanceTestCase(TestCase):
    def setUp(self) -> None:
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        TestUtils.create_tournament(
            EVENT_ID,
            TOURNAMENT_NAME,
            overrides={
                'rounds': 3,
                'current_round': 1,
                'team_player_count': N,
                'pairing': 'TEAM_SWISS_STANDARD',
            },
        )
        self.team_ids: list[int] = []
        self.player_ids: list[list[int]] = []
        with EventDatabase(EVENT_ID, write=True) as database:
            tournament_id = next(
                stored.id
                for stored in database.load_stored_tournaments()
                if stored.name == TOURNAMENT_NAME
            )
            assert tournament_id is not None
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

    def _team(self, tournament: Tournament, index: int = 0):
        return tournament.event.teams_by_id[self.team_ids[index]]

    def _play(self, tournament: Tournament, round_: int) -> None:
        """Every board of the round to White, and a board with nobody on
        one side to the present player by forfeit, so the round counts as
        complete and the next one can be paired."""
        with EventDatabase(EVENT_ID, write=True) as database:
            for board in tournament.get_round_boards(round_):
                white = board.optional_white_pairing
                black = board.optional_black_pairing
                if white is None or black is None:
                    present = white or black
                    if present is not None:
                        present.update_result(database, Result.FORFEIT_WIN)
                    continue
                white.update_result(database, Result.WIN)
                black.update_result(database, Result.LOSS)

    def _pair_round_one_with_the_team_fielding_nobody(self) -> Tournament:
        """Round 1 paired and played with the first team on none of its
        boards and no lineup stored for it, the way benching a whole team
        on a paired round leaves it."""
        tournament = self._load()
        self.assertEqual(tournament.generate_round_pairings(1), '')
        tournament = self._load()
        team = self._team(tournament)
        TeamAdminController._reconcile_paired_round_lineup(
            self._event, tournament, team, 1, [None] * N
        )
        tournament = self._load()
        self.assertEqual(
            self._slot_names(self._team(tournament).effective_round_slots(1)),
            [None] * N,
        )
        self._play(tournament, 1)
        return self._load()

    @staticmethod
    def _slot_names(slots) -> list[str | None]:
        return [player.last_name if player is not None else None for player in slots]

    def test_the_next_round_inherits_the_boards_of_the_paired_one(self) -> None:
        tournament = self._pair_round_one_with_the_team_fielding_nobody()
        team = self._team(tournament)
        self.assertEqual(
            self._slot_names(team.round_board_slots(1)),
            [None, None, None, None],
        )
        self.assertEqual(
            self._slot_names(team.effective_round_slots(2)),
            [None, None, None, None],
        )
        self.assertEqual(
            [player.last_name for player in team.effective_round_lineup(2)],
            [],
        )

    def test_pairing_the_next_round_seats_the_lineup_it_inherits(self) -> None:
        """Pairing reads the same lineup the editor shows."""
        tournament = self._pair_round_one_with_the_team_fielding_nobody()
        self.assertEqual(tournament.generate_round_pairings(2), '')
        tournament = self._load()
        team = self._team(tournament)
        self.assertEqual(
            self._slot_names(team.round_board_slots(2)),
            [None, None, None, None],
        )

    def test_a_stored_lineup_still_wins_over_what_was_played(self) -> None:
        """Ticking the box off and setting a lineup for round 2 puts the
        rest of the team back."""
        tournament = self._pair_round_one_with_the_team_fielding_nobody()
        with EventDatabase(EVENT_ID, write=True) as database:
            self._team(tournament).set_round_lineup(2, self.player_ids[0], database)
        tournament = self._load()
        self.assertEqual(tournament.generate_round_pairings(2), '')
        tournament = self._load()
        self.assertEqual(
            self._slot_names(self._team(tournament).round_board_slots(2)),
            ['T1P0', 'T1P1', 'T1P2', 'T1P3'],
        )

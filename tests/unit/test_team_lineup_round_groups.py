"""The lineups modal groups its round buttons into runs of rounds
sharing one lineup.

A paired round goes by what stands on its boards, a round yet to be
paired by where its lineup comes from. These tests state the grouping
for a system that pairs one round at a time (Swiss) and for the three
that pair every round up front (round-robin, Scheveningen, Molter).
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
    set_stored_fields,
)
from tests.test_config import TestUtils
from utils.enum import EventType, Result
from web.controllers.admin.team_admin_controller import TeamAdminController


EVENT_ID = 'test-team-lineup-round-groups'
TOURNAMENT_NAME = 'tournament'
N = 4  # boards per match


def _round_groups(tournament: Tournament, team: Team) -> list[list[int]]:
    """The modal's round groups, as lists of round numbers. Mirrors how
    the controller reads each round's lineup: the boards once the round
    is paired, the stored or inherited lineup before that."""
    rounds_data = [
        {
            'round': round_,
            'is_paired': round_ <= tournament.last_paired_round,
            'lineup_source': team.lineup_source(round_),
            'slots': (
                team.round_board_slots(round_) or team.effective_round_slots(round_)
            ),
        }
        for round_ in range(1, tournament.rounds + 1)
    ]
    return [
        [round_info['round'] for round_info in group]
        for group in TeamAdminController._group_rounds_by_lineup(rounds_data)
    ]


@pytest.mark.unit
class TeamLineupRoundGroupsTestCase(TestCase):
    def tearDown(self) -> None:
        TestUtils.delete_event(EVENT_ID)

    def _create(self, pairing: str, rounds: int, teams: int) -> None:
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        TestUtils.create_tournament(
            EVENT_ID,
            TOURNAMENT_NAME,
            overrides={
                'rounds': rounds,
                'current_round': 1,
                'team_player_count': N,
                'pairing': pairing,
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
            for seed in range(1, teams + 1):
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

    def _play(self, tournament: Tournament, round_: int) -> None:
        """Every board of *round_* to White, so the next round can pair.
        A board a lineup left as a hole is a forfeit and already has
        its result."""
        for board in tournament.get_round_boards(round_):
            if (
                board.optional_white_tournament_player is None
                or board.black_tournament_player is None
            ):
                continue
            tournament.add_result(board, Result.WIN)

    def _pair(self, rounds: int) -> Tournament:
        tournament = self._load()
        for round_ in range(1, rounds + 1):
            self.assertEqual(tournament.generate_round_pairings(round_), '')
            if round_ < rounds:
                self._play(tournament, round_)
            tournament = self._load()
        return tournament

    def _set_lineup(self, team_index: int, round_: int, order: list[int]) -> None:
        with EventDatabase(EVENT_ID, write=True) as database:
            team = self._team(self._load(), team_index)
            team.set_round_lineup(
                round_,
                [self.player_ids[team_index][index] for index in order],
                database,
            )

    def test_round_robin_groups_the_rounds_a_team_plays_alike(self) -> None:
        """A round-robin pairs every round up front. The team keeps one
        lineup for rounds 1-2 and reshuffles for round 3, so that is
        what the buttons say — not one group per round."""
        self._create('TEAM_ROUND_ROBIN_BERGER', rounds=3, teams=4)
        self._set_lineup(0, 3, [1, 0, 2, 3])
        tournament = self._pair(3)
        self.assertEqual(tournament.last_paired_round, 3)
        self.assertEqual(
            _round_groups(tournament, self._team(tournament)), [[1, 2], [3]]
        )

    def test_round_robin_reads_the_holes_a_lineup_leaves(self) -> None:
        """A board a team leaves empty is part of the lineup it shows:
        the round it starts leaving that board empty opens a group, and
        the rounds inheriting the lineup join it."""
        self._create('TEAM_ROUND_ROBIN_BERGER', rounds=3, teams=4)
        with EventDatabase(EVENT_ID, write=True) as database:
            team = self._team(self._load(), 0)
            benched = self.player_ids[0][2]
            team.set_round_lineup(
                2,
                [
                    None if player_id == benched else player_id
                    for player_id in self.player_ids[0]
                ],
                database,
            )
        tournament = self._pair(3)
        self.assertEqual(
            _round_groups(tournament, self._team(tournament)), [[1], [2, 3]]
        )

    def test_team_swiss_rounds_yet_to_be_paired_follow_the_last(self) -> None:
        """A Swiss pairs one round at a time. The rounds still to come
        inherit the lineup, so they share the group of the round they
        inherit it from."""
        self._create('TEAM_SWISS_STANDARD', rounds=3, teams=4)
        tournament = self._pair(1)
        self.assertEqual(tournament.last_paired_round, 1)
        self.assertEqual(_round_groups(tournament, self._team(tournament)), [[1, 2, 3]])

    def test_scheveningen_rotation_is_not_a_new_lineup(self) -> None:
        """A Scheveningen table rotates one team's players around the
        other, so a player changes board from round to round without the
        lineup changing. The rounds stay in one group."""
        self._create('SCHEVENINGEN_STANDARD', rounds=N, teams=2)
        tournament = self._pair(N)
        self.assertEqual(tournament.last_paired_round, N)
        self.assertEqual(
            _round_groups(tournament, self._team(tournament)),
            [list(range(1, N + 1))],
        )

    def test_molter_reads_the_table_it_is_paired_from(self) -> None:
        """Molter seats every round from its published table, so every
        round is paired from the start here too."""
        self._create('MOLTER_STANDARD', rounds=3, teams=4)
        self._set_lineup(0, 3, [1, 0, 2, 3])
        tournament = self._pair(3)
        self.assertEqual(tournament.last_paired_round, 3)
        self.assertEqual(
            _round_groups(tournament, self._team(tournament)), [[1, 2], [3]]
        )

    def test_team_swiss_storing_an_unchanged_lineup_is_not_a_new_lineup(self) -> None:
        """Grouping goes by the lineup a round shows, not by where the
        lineup comes from: round 3 stores one of its own, seating the
        same players in the same order as the round before, so it stays
        in the run rather than opening one."""
        self._create('TEAM_SWISS_STANDARD', rounds=5, teams=8)
        self._set_lineup(0, 3, [0, 1, 2, 3])
        tournament = self._pair(1)
        self.assertEqual(tournament.last_paired_round, 1)
        self.assertEqual(
            _round_groups(tournament, self._team(tournament)), [[1, 2, 3, 4, 5]]
        )

    def test_team_swiss_rounds_follow_a_paired_round_they_take_over(self) -> None:
        """Round 1 is paired with its players in an order the roster does
        not have, and nothing is stored for round 2. Round 2 takes round
        1's lineup, boards and all, so the two stay in one group."""
        self._create('TEAM_SWISS_STANDARD', rounds=3, teams=4)
        tournament = self._pair(1)
        team = self._team(tournament)
        team_board = next(
            tb
            for tb in tournament.get_round_team_boards(1)
            if team.id
            in (tb.stored_team_board.team_a_id, tb.stored_team_board.team_b_id)
        )
        # Swap the team's players on its first two boards, so what stands
        # on them differs from the roster order round 2 falls back to.
        seats = []
        for board in team_board.boards[:2]:
            stored = board.stored_board
            side = (
                'white_player_id'
                if stored.white_player_id in self.player_ids[0]
                else 'black_player_id'
            )
            seats.append((stored, side, getattr(stored, side)))
        with EventDatabase(EVENT_ID, write=True) as database:
            for (stored, side, _own), (_o, _s, other_player_id) in (
                (seats[0], seats[1]),
                (seats[1], seats[0]),
            ):
                set_stored_fields(stored, **{side: other_player_id})
                database.update_stored_board(stored)
        tournament = self._load()
        self.assertEqual(_round_groups(tournament, self._team(tournament)), [[1, 2, 3]])

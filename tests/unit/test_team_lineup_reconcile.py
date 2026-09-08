"""Regression + invariant tests for team lineup reconciliation.

The bug class these guard against: a team's *stored lineup* and its
actual *boards* are two representations of the same thing, and they can
drift (e.g. a stored hole while the player is still seated). When the
reconcile trusts the stored lineup instead of the boards, editing a
lineup double-books a player or drops one. See
``TeamAdminController._reconcile_paired_round_lineup`` /
``round_board_slots``.

The core invariants, asserted after every edit:
  * no player sits on two boards in a round (no double-booking);
  * every board slot references a current tournament player (no dangling
    reference — a dangling one makes the whole event unopenable);
  * the team's stored lineup matches the actual boards.
"""

from unittest import TestCase

import pytest

from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredBoard,
    StoredPairing,
    StoredPlayer,
    StoredTeam,
    StoredTeamBoard,
    StoredTournamentPlayer,
)
from data.loader import EventLoader
from tests.test_config import TestUtils
from utils.enum import EventType, Result
from web.controllers.admin.team_admin_controller import TeamAdminController


EVENT_ID = 'test-team-lineup-reconcile'
TOURNAMENT_NAME = 'tournament'
N = 4


@pytest.mark.unit
class TeamLineupReconcileTestCase(TestCase):
    def setUp(self) -> None:
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        TestUtils.create_tournament(
            EVENT_ID,
            TOURNAMENT_NAME,
            overrides={
                'rounds': 1,
                'current_round': 1,
                'team_player_count': N,
                'pairing': 'TEAM_SWISS_STANDARD',
                # First team plays White on every board, so the fill side is
                # unambiguous.
                'color_pattern': 'W' * N,
            },
        )
        self._seed()

    def tearDown(self) -> None:
        TestUtils.delete_event(EVENT_ID)

    def _seed(self) -> None:
        """Two teams of N players, round 1 paired across N boards with
        team A's player i (White) vs team B's player i (Black) on board i."""
        with EventDatabase(EVENT_ID, write=True) as db:
            tournament = next(
                t for t in db.load_stored_tournaments() if t.name == TOURNAMENT_NAME
            )
            tid = tournament.id
            assert tid is not None
            self.team_a = db.add_stored_team(
                StoredTeam(id=None, name='Alpha', tournament_id=tid)
            )
            self.team_b = db.add_stored_team(
                StoredTeam(id=None, name='Bravo', tournament_id=tid)
            )

            def add_player(name: str, team_id: int, index: int) -> int:
                pid = db.add_stored_player(
                    StoredPlayer(
                        id=None,
                        last_name=name,
                        team_id=team_id,
                        team_index=index,
                        check_in=True,
                    )
                )
                db.add_stored_tournament_player(
                    StoredTournamentPlayer(
                        tournament_id=tid, player_id=pid, pairing_number=index + 1
                    )
                )
                return pid

            self.a_ids = [add_player(f'A{i}', self.team_a, i) for i in range(N)]
            self.b_ids = [add_player(f'B{i}', self.team_b, i) for i in range(N)]

            team_board_id = db.add_stored_team_board(
                StoredTeamBoard(
                    id=None,
                    tournament_id=tid,
                    round_=1,
                    team_a_id=self.team_a,
                    team_b_id=self.team_b,
                    index=1,
                )
            )
            for i in range(N):
                board_id = db.add_stored_board(
                    StoredBoard(
                        id=None,
                        white_player_id=self.a_ids[i],
                        black_player_id=self.b_ids[i],
                        index=i,
                        team_board_id=team_board_id,
                    )
                )
                for pid in (self.a_ids[i], self.b_ids[i]):
                    db.add_stored_pairing(
                        StoredPairing(
                            tournament_id=tid,
                            player_id=pid,
                            round_=1,
                            result=Result.NO_RESULT.value,
                            board_id=board_id,
                        )
                    )

    def _load(self):
        try:
            EventLoader.unload_event(EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(EVENT_ID)
        return self._event.tournaments_by_name[TOURNAMENT_NAME]

    # -- invariant checker ---------------------------------------------------

    def _assert_consistent(self, tournament) -> None:
        for round_ in range(1, tournament.rounds + 1):
            seen: set[int] = set()
            for board in tournament.get_round_boards(round_):
                for pid in (
                    board.stored_board.white_player_id,
                    board.stored_board.black_player_id,
                ):
                    if pid is None:
                        continue
                    self.assertNotIn(
                        pid,
                        seen,
                        f'player {pid} sits on two boards in round {round_}',
                    )
                    seen.add(pid)
                    self.assertIn(
                        pid,
                        tournament.tournament_players_by_id,
                        f'board references non-tournament player {pid}',
                    )
            for team_id in (self.team_a, self.team_b):
                team = self._event.teams_by_id[team_id]
                board_slots = team.round_board_slots(round_)
                if board_slots is None:
                    continue
                # When an explicit lineup is stored it must match the boards.
                # (An all-holes lineup can't be stored as rows, so it falls
                # back to the default roster — round_board_slots is the truth
                # there, which every consumer of a paired round uses.)
                if team.has_explicit_round_lineup(round_):
                    stored = team.effective_round_slots(round_)
                    self.assertEqual(
                        [p.id if p else None for p in board_slots],
                        [p.id if p else None for p in stored],
                        f'team {team_id} stored lineup disagrees with the '
                        f'boards in round {round_}',
                    )

    def _reconcile(self, team_id: int, slot_values: list[int | None]) -> None:
        team = self._event.teams_by_id[team_id]
        tournament = team.tournament
        assert tournament is not None
        TeamAdminController._reconcile_paired_round_lineup(
            self._event, tournament, team, 1, slot_values
        )

    def _boards_of(self, tournament, player_id: int) -> list[int]:
        return [
            board.stored_board.id
            for board in tournament.get_round_boards(1)
            if player_id
            in (
                board.stored_board.white_player_id,
                board.stored_board.black_player_id,
            )
        ]

    # -- tests ---------------------------------------------------------------

    def test_seed_is_consistent(self) -> None:
        self._assert_consistent(self._load())

    def test_reconcile_repairs_stored_lineup_divergence(self) -> None:
        """Stored lineup says slot N-1 is a hole while the player is still
        on the board; moving that player to slot 0 must not leave them on
        both boards. (Reconcile must read the boards, not the stored
        lineup.)"""
        tournament = self._load()
        team_a = self._event.teams_by_id[self.team_a]
        # Force the divergence: store a hole at the last slot, boards intact.
        with EventDatabase(EVENT_ID, write=True) as db:
            team_a.set_round_lineup(1, self.a_ids[:-1] + [None], db)

        # Move the last roster player to slot 0, leaving the last slot empty.
        new = [self.a_ids[-1]] + self.a_ids[1:-1] + [None]
        self._reconcile(self.team_a, new)

        tournament = self._load()
        self.assertEqual(
            len(self._boards_of(tournament, self.a_ids[-1])),
            1,
            'the moved player must be on exactly one board',
        )
        self._assert_consistent(tournament)

    def test_bench_then_refill_keeps_everyone(self) -> None:
        """Bench every player, then put them all back: no one is dropped or
        duplicated (the originally-reported Swiss symptom)."""
        self._load()
        self._reconcile(self.team_a, [None] * N)
        tournament = self._load()
        for pid in self.a_ids:
            self.assertEqual(self._boards_of(tournament, pid), [])
        self._assert_consistent(tournament)

        self._reconcile(self.team_a, list(self.a_ids))
        tournament = self._load()
        for pid in self.a_ids:
            self.assertEqual(
                len(self._boards_of(tournament, pid)),
                1,
                f'player {pid} should be back on exactly one board',
            )
        self._assert_consistent(tournament)

    def test_reorder_sequence_keeps_invariants(self) -> None:
        """A sequence of reorders/benches keeps the invariants after each
        step — guards against the corruption that compounds across edits."""
        self._load()
        sequences: list[list[int | None]] = [
            [self.a_ids[3], self.a_ids[0], self.a_ids[1], self.a_ids[2]],
            [self.a_ids[3], self.a_ids[0], self.a_ids[1], None],
            [None, self.a_ids[0], self.a_ids[1], self.a_ids[3]],
            list(self.a_ids),
        ]
        for slot_values in sequences:
            self._reconcile(self.team_a, slot_values)
            tournament = self._load()
            self._assert_consistent(tournament)
            expected = {pid for pid in slot_values if pid is not None}
            on_boards = {pid for pid in self.a_ids if self._boards_of(tournament, pid)}
            self.assertEqual(on_boards, expected)

    def test_player_is_paired_guards_roster_removal(self) -> None:
        """A seated player reports as paired (removal blocked); a benched
        one does not."""
        self._load()
        team_a = self._event.teams_by_id[self.team_a]
        seated = self._event.players_by_id[self.a_ids[0]]
        self.assertTrue(TeamAdminController._player_is_paired(team_a, seated))

        # Bench the last player; they should no longer count as paired.
        self._reconcile(self.team_a, self.a_ids[:-1] + [None])
        self._load()
        team_a = self._event.teams_by_id[self.team_a]
        benched = self._event.players_by_id[self.a_ids[-1]]
        self.assertFalse(TeamAdminController._player_is_paired(team_a, benched))

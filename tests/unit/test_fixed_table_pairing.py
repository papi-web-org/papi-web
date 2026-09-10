"""Regression tests for Molter (flat fixed-table) pairing generation with
holes / incomplete rosters.

Two related guarantees:
  * a team lineup with a *hole* (a benched player) must not double-book the
    promoted player — the bug where ``_team_player`` fell back to the roster
    for high seats and re-seated an already-placed player;
  * an *incomplete* roster (fewer players than ``team_player_count``) must
    pair without error, leaving holes — incomplete teams are allowed, as in
    Swiss.

Invariant asserted after generation: no player sits on two boards in a round,
and every board slot references a current tournament player.
"""

from unittest import TestCase

import pytest

from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredPlayer,
    StoredTeam,
    StoredTournamentPlayer,
)
from data.loader import EventLoader
from plugins.ffe.ffe_rule_sets import CoupeJeanClaudeLoubatiereRuleSet
from tests.test_config import TestUtils
from utils.enum import EventType, Result


EVENT_ID = 'test-fixed-table-pairing'
TOURNAMENT_NAME = 'molter'
N = 4  # players per team / boards per team match
TEAMS = 4


@pytest.mark.unit
class FixedTablePairingTestCase(TestCase):
    def setUp(self) -> None:
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        TestUtils.create_tournament(
            EVENT_ID,
            TOURNAMENT_NAME,
            overrides={
                'rounds': 1,
                'current_round': 1,
                'team_player_count': N,
                'pairing': 'MOLTER_STANDARD',
            },
        )

    def tearDown(self) -> None:
        TestUtils.delete_event(EVENT_ID)

    def _seed(self, team_sizes: tuple[int, ...] = (N, N, N, N)) -> None:
        """Seed ``TEAMS`` teams (no boards yet). ``team_sizes`` gives each
        team's roster size, so an incomplete roster can be modelled."""
        self.team_ids: list[int] = []
        self.player_ids: list[list[int]] = []
        with EventDatabase(EVENT_ID, write=True) as db:
            tournament = next(
                t for t in db.load_stored_tournaments() if t.name == TOURNAMENT_NAME
            )
            tid = tournament.id
            assert tid is not None
            for t_index, size in enumerate(team_sizes):
                team_id = db.add_stored_team(
                    StoredTeam(
                        id=None,
                        name=f'Team{t_index}',
                        tournament_id=tid,
                        pairing_number=t_index + 1,
                    )
                )
                self.team_ids.append(team_id)
                ids: list[int] = []
                for p_index in range(size):
                    pid = db.add_stored_player(
                        StoredPlayer(
                            id=None,
                            last_name=f'T{t_index}P{p_index}',
                            team_id=team_id,
                            team_index=p_index,
                            check_in=True,
                        )
                    )
                    db.add_stored_tournament_player(
                        StoredTournamentPlayer(
                            tournament_id=tid,
                            player_id=pid,
                            pairing_number=p_index + 1,
                        )
                    )
                    ids.append(pid)
                self.player_ids.append(ids)

    def _load(self):
        try:
            EventLoader.unload_event(EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(EVENT_ID)
        return self._event.tournaments_by_name[TOURNAMENT_NAME]

    def _assert_no_double_book(self, tournament) -> None:
        seen: set[int] = set()
        for board in tournament.get_round_boards(1):
            for pid in (
                board.stored_board.white_player_id,
                board.stored_board.black_player_id,
            ):
                if pid is None:
                    continue
                self.assertNotIn(
                    pid, seen, f'player {pid} sits on two boards in round 1'
                )
                seen.add(pid)
                self.assertIn(
                    pid,
                    tournament.tournament_players_by_id,
                    f'board references non-tournament player {pid}',
                )

    def _boards_of(self, tournament, player_id: int) -> int:
        return sum(
            1
            for board in tournament.get_round_boards(1)
            if player_id
            in (
                board.stored_board.white_player_id,
                board.stored_board.black_player_id,
            )
        )

    def test_partial_lineup_does_not_double_book(self) -> None:
        """Team 0's lineup promotes its 4th roster player to slot 0 and
        leaves slot 3 a hole (the reported ANICET shape). The promoted
        player must be seated once, the benched one not at all."""
        self._seed()
        tournament = self._load()
        team0 = self._event.teams_by_id[self.team_ids[0]]
        p = self.player_ids[0]
        with EventDatabase(EVENT_ID, write=True) as db:
            team0.set_round_lineup(1, [p[3], p[0], p[1], None], db)

        tournament = self._load()
        self.assertEqual(tournament.generate_round_pairings(1), '')

        tournament = self._load()
        self._assert_no_double_book(tournament)
        self.assertEqual(
            self._boards_of(tournament, p[3]), 1, 'promoted player seated once'
        )
        self.assertEqual(
            self._boards_of(tournament, p[2]), 0, 'benched player not seated'
        )

    def test_player_round_label_uses_team_letter_and_lineup_slot(self) -> None:
        """The A1/B3 code reflects the player's own team letter + 1-based
        lineup slot, so it follows the player (not the table cell)."""
        self._seed()
        self._load()
        team0 = self._event.teams_by_id[self.team_ids[0]]
        p = self.player_ids[0]
        with EventDatabase(EVENT_ID, write=True) as db:
            team0.set_round_lineup(1, [p[3], p[0], p[1], None], db)
        self._load()
        team0 = self._event.teams_by_id[self.team_ids[0]]
        players = self._event.players_by_id
        self.assertEqual(team0.player_round_label(players[p[3]], 1), 'A1')
        self.assertEqual(team0.player_round_label(players[p[0]], 1), 'A2')
        self.assertEqual(team0.player_round_label(players[p[1]], 1), 'A3')
        # Benched player has no slot this round → no code.
        self.assertIsNone(team0.player_round_label(players[p[2]], 1))
        # A team with no explicit lineup falls back to roster order, and
        # the second team is lettered B.
        team1 = self._event.teams_by_id[self.team_ids[1]]
        q = self.player_ids[1]
        self.assertEqual(team1.player_round_label(players[q[0]], 1), 'B1')

    def test_create_flat_manual_board_two_players(self) -> None:
        """Manually boarding two players makes a normal game (no result)."""
        self._seed()
        tournament = self._load()
        p0, p1 = self.player_ids[0][0], self.player_ids[1][0]
        tournament.create_flat_manual_board(1, p0, p1, 0)
        tournament = self._load()
        board = next(b for b in tournament.get_round_boards(1) if b.index == 0)
        self.assertEqual(board.stored_board.white_player_id, p0)
        self.assertEqual(board.stored_board.black_player_id, p1)
        self.assertEqual(board.optional_white_pairing.result, Result.NO_RESULT)

    def test_create_flat_manual_board_player_vs_hole(self) -> None:
        """A player boarded against a hole wins by forfeit; no lineup change."""
        self._seed()
        tournament = self._load()
        p0 = self.player_ids[0][0]
        tournament.create_flat_manual_board(1, p0, None, 3)
        tournament = self._load()
        board = next(b for b in tournament.get_round_boards(1) if b.index == 3)
        self.assertEqual(board.stored_board.white_player_id, p0)
        self.assertIsNone(board.stored_board.black_player_id)
        self.assertEqual(board.optional_white_pairing.result, Result.FORFEIT_WIN)
        self.assertFalse(
            self._event.teams_by_id[self.team_ids[0]].has_explicit_round_lineup(1)
        )

    def test_lineup_inherits_previous_round(self) -> None:
        """With no stored lineup, round 1 falls back to the roster and later
        rounds inherit the previous round's lineup (chaining back)."""
        self._seed()
        self._load()
        team0 = self._event.teams_by_id[self.team_ids[0]]
        p = self.player_ids[0]

        def ids(round_: int) -> list[int | None]:
            return [pl.id if pl else None for pl in team0.effective_round_slots(round_)]

        self.assertEqual(ids(1), p[:N])
        self.assertEqual(team0.lineup_source(1), 'roster')
        self.assertEqual(team0.lineup_source(2), 'previous')

        with EventDatabase(EVENT_ID, write=True) as db:
            team0.set_round_lineup(1, [p[1], p[0], p[2], p[3]], db)
        self._load()
        team0 = self._event.teams_by_id[self.team_ids[0]]
        self.assertEqual(ids(1), [p[1], p[0], p[2], p[3]])
        # Rounds 2 and 3 have no lineup of their own → inherit round 1.
        self.assertEqual(ids(2), ids(1))
        self.assertEqual(ids(3), ids(1))
        self.assertEqual(team0.lineup_source(1), 'explicit')
        self.assertEqual(team0.lineup_source(2), 'previous')

    def test_first_unused_board_index_skips_forfeit_holes(self) -> None:
        """A forfeit (one-sided, exempt) board still owns its table — the
        next manual pairing must not be placed on its index."""
        self._seed()
        self._load()
        tournament = self._load()
        p = self.player_ids
        tournament.create_flat_manual_board(1, p[0][0], p[1][0], 0)
        tournament.create_flat_manual_board(1, p[2][0], None, 2)  # forfeit hole
        tournament = self._load()
        # Index 1 is the first truly-free table; index 2 (the hole) is taken.
        self.assertEqual(tournament.first_unused_board_index(1), 1)
        tournament.create_flat_manual_board(1, p[3][0], p[0][1], 1)
        tournament = self._load()
        # Now 0, 1, 2 are occupied → next is 3, never the hole at 2.
        self.assertEqual(tournament.first_unused_board_index(1), 3)

    def test_incomplete_roster_pairs_with_holes(self) -> None:
        """A team with fewer players than team_player_count pairs without
        error; its players are each seated once and no one is double-booked."""
        self._seed(team_sizes=(N - 1, N, N, N))
        tournament = self._load()
        self.assertEqual(tournament.generate_round_pairings(1), '')

        tournament = self._load()
        self._assert_no_double_book(tournament)
        for pid in self.player_ids[0]:
            self.assertEqual(
                self._boards_of(tournament, pid),
                1,
                f'player {pid} of the short team should be seated once',
            )

    def test_molter_forfeit_loss_penalty_applies(self) -> None:
        """The Loubatière rule 'une partie perdue par forfait sportif est
        comptée -1' now applies to Molter too: a team that leaves a board
        unfielded gets -1 game point; a full team gets none."""
        self._seed()
        tournament = self._load()
        team0 = self._event.teams_by_id[self.team_ids[0]]
        p = self.player_ids[0]
        with EventDatabase(EVENT_ID, write=True) as db:
            team0.set_round_lineup(1, [p[0], p[1], p[2], None], db)
        tournament = self._load()
        self.assertEqual(tournament.generate_round_pairings(1), '')

        self._load()
        rule_set = CoupeJeanClaudeLoubatiereRuleSet()
        holed_team = self._event.teams_by_id[self.team_ids[0]]
        adjustment = rule_set._forfeit_loss_penalty(holed_team, 1)
        self.assertIsNotNone(adjustment)
        assert adjustment is not None
        self.assertEqual(adjustment.gp, -1.0)
        # A fully-fielded team incurs no forfeit penalty.
        full_team = self._event.teams_by_id[self.team_ids[1]]
        self.assertIsNone(rule_set._forfeit_loss_penalty(full_team, 1))

    def test_all_short_rosters_pair_without_error(self) -> None:
        """Every team short the same seat still pairs cleanly: no error, no
        double-booking. (A board where BOTH seats are empty is currently
        skipped — a flat board has no round anchor without a pairing or
        team_board, so it can't be persisted.)"""
        self._seed(team_sizes=(N - 1, N - 1, N - 1, N - 1))
        tournament = self._load()
        self.assertEqual(tournament.generate_round_pairings(1), '')

        tournament = self._load()
        self._assert_no_double_book(tournament)
        # Each present player is seated exactly once.
        for team_players in self.player_ids:
            for pid in team_players:
                self.assertEqual(self._boards_of(tournament, pid), 1)

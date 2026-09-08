import weakref
from datetime import datetime
from functools import cached_property
from typing import TYPE_CHECKING

from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import StoredTeamBoard
from utils.date_time import format_datetime
from utils.enum import TeamByeType, Result, ScoreType

if TYPE_CHECKING:
    from data.board import Board
    from data.teams.team import Team
    from data.tournament import Tournament


class TeamBoard:
    """A team-vs-team match for a given round.
    The two teams are symmetric (no home/away). *team_b* is None for a bye.
    Holds the individual *Board* objects making up the match."""

    def __init__(
        self,
        tournament: 'Tournament',
        stored_team_board: StoredTeamBoard,
    ):
        self._tournament_ref: 'weakref.ReferenceType[Tournament]' = weakref.ref(
            tournament
        )
        self.stored_team_board = stored_team_board

    @property
    def tournament(self) -> 'Tournament':
        if (tournament := self._tournament_ref()) is None:
            raise RuntimeError('Reference has been garbage collected')
        return tournament

    @property
    def id(self) -> int:
        assert self.stored_team_board.id is not None
        return self.stored_team_board.id

    @property
    def round(self) -> int:
        return self.stored_team_board.round_

    @property
    def index(self) -> int | None:
        return self.stored_team_board.index

    @property
    def display_number(self) -> int | None:
        """1-based table number for this match, straight from the stored
        ``index``. ``None`` for a hidden bye (HPB / FPB / ZPB), which has
        no table. Because the number is carried by the stored ``index``,
        it is stable: unpairing a match leaves a hole rather than
        renumbering the matches after it (exactly like individual board
        numbers), and a new pairing reuses that hole."""
        if self.index is None:
            return None
        return self.index + 1

    @property
    def _counts_as_displayed_match(self) -> bool:
        """Whether this team board is rendered as a numbered match in
        the pairings table (matches the controller's filter: manual /
        auto byes are hidden)."""
        stb = self.stored_team_board
        return not (
            stb.team_b_id is None and stb.bye_type in TeamByeType.manual_bye_types()
        )

    @property
    def team_a(self) -> 'Team':
        return self.tournament.event.teams_by_id[self.stored_team_board.team_a_id]

    @property
    def team_b(self) -> 'Team | None':
        team_b_id = self.stored_team_board.team_b_id
        if team_b_id is None:
            return None
        return self.tournament.event.teams_by_id.get(team_b_id)

    @property
    def is_bye(self) -> bool:
        return self.stored_team_board.team_b_id is None

    @property
    def bye_type(self) -> str | None:
        """One of ``PAB`` / ``HPB`` / ``FPB`` / ``ZPB`` for a bye
        team_board; ``None`` for a regular paired match. Stored byes
        that pre-date the column default to ``PAB`` since that's the
        only bye the pairing engine produced before this field existed."""
        if not self.is_bye:
            return None
        return self.stored_team_board.bye_type or TeamByeType.PAB

    @cached_property
    def boards(self) -> list['Board']:
        """Individual boards belonging to this team match, ordered by index."""
        return sorted(
            (
                board
                for board in self.tournament.boards_by_id.values()
                if board.stored_board.team_board_id == self.id
            ),
            key=lambda board: board.index,
        )

    def board_team_ids(self, board: 'Board') -> tuple[int | None, int | None]:
        """The ``(white_team_id, black_team_id)`` for ``board`` within
        this match. A forfeited side is a hole — no player, hence no
        team — so it's inferred from the present side and the match's
        two teams. Without this, every per-board team attribution would
        mis-credit a forfeited board to the opponent whenever the
        forfeiting team sat on the white side."""
        players_by_id = self.tournament.event.players_by_id
        w_id = board.stored_board.white_player_id
        b_id = board.stored_board.black_player_id
        white_player = players_by_id.get(w_id) if w_id else None
        black_player = players_by_id.get(b_id) if b_id else None
        white_team_id = white_player.team_id if white_player else None
        black_team_id = black_player.team_id if black_player else None
        team_a_id = self.stored_team_board.team_a_id
        team_b_id = self.stored_team_board.team_b_id
        if white_team_id is None and black_team_id is not None:
            white_team_id = team_a_id if black_team_id == team_b_id else team_b_id
        elif black_team_id is None and white_team_id is not None:
            black_team_id = team_a_id if white_team_id == team_b_id else team_b_id
        return white_team_id, black_team_id

    @property
    def game_points(self) -> tuple[float, float]:
        """(team_a_points, team_b_points) — sum of individual board
        game-points across this match. Scored via the tournament's
        :attr:`team_game_points` mapping so the ``gp_*`` override
        (e.g. 3/2/1) applies at team-scoring level; ``point_values``
        (individual scoring) stays at FIDE defaults."""
        a, b = 0.0, 0.0
        team_a_id = self.stored_team_board.team_a_id
        team_game_points = self.tournament.team_game_points
        for board in self.boards:
            white_team_id, _black_team_id = self.board_team_ids(board)
            white_pairing = board.optional_white_pairing
            white_pts = (
                white_pairing.result.points(team_game_points) if white_pairing else 0.0
            )
            black_tp = board.black_tournament_player
            black_pts = (
                board.black_pairing.result.points(team_game_points) if black_tp else 0.0
            )
            if white_team_id == team_a_id:
                a += white_pts
                b += black_pts
            else:
                a += black_pts
                b += white_pts
        return a, b

    @property
    def effective_game_points(self) -> tuple[float, float]:
        """(team_a, team_b) board game points with this round's point
        adjustments folded in — rule-set forfeit penalties and manual
        bonuses. This is the single source of truth for the match result:
        every standings and score-display path decides win/draw/loss from
        these, so a penalty changes who won the match (not only the
        cumulative totals, which add the same deltas separately)."""
        a_gp, b_gp = self.game_points
        stb = self.stored_team_board
        if stb.team_b_id is None:
            return a_gp, b_gp
        tournament = self.tournament
        _, a_adj = tournament.effective_point_adjustment(stb.team_a_id, self.round)
        _, b_adj = tournament.effective_point_adjustment(stb.team_b_id, self.round)
        return a_gp + a_adj, b_gp + b_adj

    @property
    def no_games_played(self) -> bool:
        """Returns True if no game of the team board is already played."""
        return all(board.no_result for board in self.boards)

    @property
    def all_games_played(self) -> bool:
        """Returns True if all the games of the team board have been played."""
        return not any(board.no_result for board in self.boards)

    def team_all_forfeit(self, team_id: int) -> bool:
        """True when every board this team is on was forfeited — its player
        absent (a hole) or holding a forfeit-loss result — so the team's
        score is shown as 'F' rather than 0. False while any board is still
        unplayed or was contested over the board."""
        saw_board = False
        for board in self.boards:
            white_team, black_team = self.board_team_ids(board)
            if team_id not in (white_team, black_team):
                continue
            saw_board = True
            if team_id == white_team:
                player = board.optional_white_tournament_player
                pairing = board.optional_white_pairing
            else:
                player = board.black_tournament_player
                pairing = board.optional_black_pairing
            if player is None:
                continue  # a hole counts as a forfeited board
            result = pairing.result if pairing else Result.NO_RESULT
            if result not in (Result.FORFEIT_LOSS, Result.DOUBLE_FORFEIT):
                return False
        return saw_board

    def match_points_pair(
        self, *, effective: bool = True
    ) -> tuple[float, float] | None:
        """``(team_a, team_b)`` match points for this match, or ``None``
        for a bye envelope (no team B) — a bye is scored by its bye type,
        not by a match result.

        The game points decide who won; a team that forfeited the whole
        match takes the tournament's absent-team match points instead of
        a plain loss. ``effective`` folds the round's point adjustments
        into the comparison — every scoring path wants that, but the TRF
        totals account for adjustments separately."""
        stb = self.stored_team_board
        if stb.team_b_id is None:
            return None
        tournament = self.tournament
        mp = tournament.match_points
        win_mp = mp.get(Result.WIN, 2.0)
        draw_mp = mp.get(Result.DRAW, 1.0)
        loss_mp = mp.get(Result.LOSS, 0.0)
        absent_mp = mp.get(Result.ZERO_POINT_BYE, loss_mp)
        a_gp, b_gp = self.effective_game_points if effective else self.game_points
        if a_gp > b_gp:
            mp_a, mp_b = win_mp, loss_mp
        elif a_gp < b_gp:
            mp_a, mp_b = loss_mp, win_mp
        else:
            mp_a = mp_b = draw_mp
        if self.team_all_forfeit(stb.team_a_id):
            mp_a = absent_mp
        if self.team_all_forfeit(stb.team_b_id):
            mp_b = absent_mp
        return mp_a, mp_b

    @property
    def match_score_pair(self) -> tuple[str, str] | None:
        """``(team_a_score, team_b_score)`` strings following the
        tournament's primary score, or ``None`` for an unplayed match
        or a bye envelope. Lets callers orient the score from either
        team's perspective (crosstables)."""
        if self.stored_team_board.team_b_id is None:
            return None
        if self.boards and all(board.no_result for board in self.boards):
            return None
        a_gp, b_gp = self.effective_game_points
        tournament = self.tournament
        if tournament.primary_score == ScoreType.MATCH_POINTS:
            match_points = self.match_points_pair()
            assert match_points is not None
            mp_a, mp_b = match_points
            return f'{mp_a:g}', f'{mp_b:g}'
        a_str = (
            'F'
            if self.team_all_forfeit(self.stored_team_board.team_a_id)
            else f'{a_gp:g}'
        )
        b_str = (
            'F'
            if self.team_all_forfeit(self.stored_team_board.team_b_id)
            else f'{b_gp:g}'
        )
        return a_str, b_str

    @property
    def match_score_display(self) -> str:
        """Human-readable score line shown in the team-block header. Format
        follows the tournament's primary score: match points if
        primary_score is MATCH_POINTS, otherwise game points."""
        if (
            self.stored_team_board.team_b_id is not None
            and self.boards
            and all(board.no_result for board in self.boards)
        ):
            return '–'
        a_gp, b_gp = self.effective_game_points
        tournament = self.tournament
        if (
            self.stored_team_board.team_b_id is None
            and self.bye_type == TeamByeType.PAB
            and tournament.team_bye_is_rest
        ):
            # Round-robin rest game: no points to display.
            return '–'
        if tournament.primary_score == ScoreType.MATCH_POINTS:
            mp = tournament.match_points
            win_mp = mp.get(Result.WIN, 2.0)
            loss_mp = mp.get(Result.LOSS, 0.0)
            if self.stored_team_board.team_b_id is None:
                if self.bye_type == TeamByeType.ZPB:
                    mp_a = mp.get(Result.ZERO_POINT_BYE, loss_mp)
                else:
                    mp_a = mp.get(Result.PAIRING_ALLOCATED_BYE, win_mp)
                return f'{mp_a:g} – 0'
            match_points = self.match_points_pair()
            assert match_points is not None
            mp_a, mp_b = match_points
            return f'{mp_a:g} – {mp_b:g}'
        if self.stored_team_board.team_b_id is None:
            return f'{tournament.team_pab_game_points:g} – 0'
        a_str = (
            'F'
            if self.team_all_forfeit(self.stored_team_board.team_a_id)
            else f'{a_gp:g}'
        )
        b_str = (
            'F'
            if self.team_all_forfeit(self.stored_team_board.team_b_id)
            else f'{b_gp:g}'
        )
        return f'{a_str} – {b_str}'

    @property
    def last_result_update(self) -> datetime | None:
        return self.stored_team_board.last_result_update

    @property
    def last_result_update_str(self) -> str:
        return (
            format_datetime(self.last_result_update) if self.last_result_update else ''
        )

    def set_last_result_update(self, clear: bool, database: EventDatabase):
        self.stored_team_board.last_result_update = (
            database.update_team_board_last_result_update(self.id, clear=clear)
        )

    def update(self, database: EventDatabase):
        database.update_stored_team_board(self.stored_team_board)

    def __repr__(self) -> str:
        return (
            f'{self.__class__.__name__}(id={self.id!r}, round={self.round!r}, '
            f'team_a={self.stored_team_board.team_a_id!r}, '
            f'team_b={self.stored_team_board.team_b_id!r})'
        )

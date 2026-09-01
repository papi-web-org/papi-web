"""Knock-out-specific views over a tournament, reached as ``tournament.knockout``.

A knock-out exposes a cluster of behaviours the templates and controllers need —
advancement resolution, the round-reached standings, the bracket tie-resolution
display and the manual-winner writers. They all delegate to the tournament's
pairing engine; grouping them here keeps them off the (system-agnostic)
:class:`~data.tournament.Tournament` class.

The engine-typed methods are valid only on a knock-out (callers gate on
``pairing_system.eliminates_participants``). The ``getattr``-based ones — the
board/team-match advancement display, the unresolved-match list, the manual
marker and the grouping preview — return an empty result for any system, so a
template may call them unconditionally.
"""

from functools import cached_property
from typing import TYPE_CHECKING, Any, Protocol, cast

from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import set_stored_fields

if TYPE_CHECKING:
    from data.board import Board
    from data.pairings.knockout import KnockoutAdvancement
    from data.pairings.knockout_helpers.layout import BracketLayout
    from data.player import TournamentPlayer
    from data.teams.team_board import TeamBoard
    from data.tournament import Tournament

    class _KnockoutEngineProtocol(Protocol):
        """The knock-out-specific engine methods the delegators reach through
        ``pairing_variation.engine`` (a knock-out engine whenever these are
        called)."""

        def ranking_value(
            self,
            tournament: 'Tournament',
            player: 'TournamentPlayer',
            *,
            after_round: int,
        ) -> float: ...

        def standing_labels(
            self, tournament: 'Tournament', *, after_round: int | None = ...
        ) -> dict[int, str]: ...

        def team_ranking_values(
            self, tournament: 'Tournament', *, after_round: int
        ) -> dict[int, float]: ...

        def team_standing_labels(
            self, tournament: 'Tournament', *, after_round: int | None = ...
        ) -> dict[int, str]: ...

        def team_advancement(
            self, tournament: 'Tournament', team_board: 'TeamBoard'
        ) -> 'KnockoutAdvancement': ...

        def player_advancement(
            self, tournament: 'Tournament', board: 'Board'
        ) -> 'KnockoutAdvancement': ...


class KnockoutView:
    """The knock-out-specific facet of a tournament (see the module docstring)."""

    def __init__(self, tournament: 'Tournament') -> None:
        self._t = tournament

    @cached_property
    def engine_cache(self) -> dict:
        """Scratch space the engines memoise per-tournament derivations in — a
        double elimination resolves its whole match graph to answer a single
        player's placement, and the standings ask once per player. Lives as long
        as the tournament object; the writers below drop it."""
        return {}

    def invalidate_engine_cache(self) -> None:
        """Drop the memoised derivations after a result they depend on moved."""
        self.__dict__.pop('engine_cache', None)

    @property
    def _engine(self) -> '_KnockoutEngineProtocol':
        """The pairing engine typed as a knock-out engine. Only reached from
        methods that run on a knock-out, where the engine really carries them."""
        return cast('_KnockoutEngineProtocol', self._t.pairing_variation.engine)

    # -- Advancement resolution (knock-out only) ----------------------------

    def team_advancement(self, team_board: 'TeamBoard') -> 'KnockoutAdvancement':
        """Who advances from a level team match and why; see
        :meth:`KnockoutEngine.team_advancement`."""
        return self._engine.team_advancement(self._t, team_board)

    def advancement_winner(self, team_board: 'TeamBoard') -> int | None:
        return self.team_advancement(team_board).winner_id

    def player_advancement(self, board: 'Board') -> 'KnockoutAdvancement':
        """Who advances from a drawn individual game and why; see
        :meth:`KnockoutEngine.player_advancement`."""
        return self._engine.player_advancement(self._t, board)

    def advancement_winner_player(self, board: 'Board') -> int | None:
        return self.player_advancement(board).winner_id

    # -- Advancement display (empty for any non-knock-out system) -----------

    def board_advancement(self, board: 'Board') -> 'KnockoutAdvancement | None':
        """The advancement detail to show on an individual board — only for a
        knock-out game drawn between two players, else ``None``."""
        method = getattr(self._t.pairing_variation.engine, 'board_advancement', None)
        return method(self._t, board) if method is not None else None

    def team_board_advancement(
        self, team_board: 'TeamBoard'
    ) -> 'KnockoutAdvancement | None':
        """The advancement detail to show on a team match — only for a finished
        knock-out match level on game points, else ``None``."""
        method = getattr(
            self._t.pairing_variation.engine, 'team_board_advancement', None
        )
        return method(self._t, team_board) if method is not None else None

    @property
    def advancement_has_manual(self) -> bool:
        """Whether the advancement list contains the play-off (manual) marker,
        so the pairing tab may offer to designate a winner. False for
        non-knock-outs."""
        method = getattr(
            self._t.pairing_variation.engine, 'advancement_has_manual', None
        )
        return method(self._t) if method is not None else False

    def unresolved_matches(self, round_: int) -> list[dict[str, Any]]:
        """The round's played matches that no advancement tie-break can settle —
        awaiting a play-off designation. Empty unless this is a knock-out."""
        method = getattr(self._t.pairing_variation.engine, 'unresolved_matches', None)
        return method(self._t, round_) if method is not None else []

    # -- Standings (round reached, knock-out only) --------------------------

    def ranking_value(self, player: 'TournamentPlayer', *, after_round: int) -> float:
        """A knock-out's standing value for *player* — the round reached
        (bigger = better); see :meth:`KnockoutEngine.ranking_value`."""
        return self._engine.ranking_value(self._t, player, after_round=after_round)

    def standing_labels(self, *, after_round: int | None = None) -> dict[int, str]:
        """Plain-language knock-out standings per player id ('Winner' /
        'Runner-up' / 'Out — round N' / 'Still in')."""
        return self._engine.standing_labels(self._t, after_round=after_round)

    def team_ranking_values(self, *, after_round: int) -> dict[int, float]:
        """Ranking value per team id (round reached)."""
        return self._engine.team_ranking_values(self._t, after_round=after_round)

    def team_standing_labels(self, *, after_round: int | None = None) -> dict[int, str]:
        """Plain-language knock-out standings per team id."""
        return self._engine.team_standing_labels(self._t, after_round=after_round)

    # -- Bracket render / grouping preview ----------------------------------

    def layout(self) -> 'BracketLayout | None':
        """A render-ready bracket diagram, or ``None`` for a system with no
        bracket to draw."""
        build = getattr(self._t.pairing_variation.engine, 'bracket_layout', None)
        return build(self._t) if build is not None else None

    def grouping_preview(self, dimension_id: str) -> 'dict | None':
        """Preview of seeding a knock-out bracket by *dimension_id* (the groups
        and the bracket consequence). ``None`` for a non-knock-out or an unknown
        dimension."""
        method = getattr(self._t.pairing_variation.engine, 'grouping_preview', None)
        if method is None:
            return None
        for dimension in self._t.prohibited_pairing_dimensions():
            if dimension.id == dimension_id:
                return method(self._t, dimension)
        return None

    # -- Manual winner designation ------------------------------------------

    def set_team_match_winner(self, team_board_id: int, team_id: int | None) -> None:
        """Designate (or clear, with ``None``) the team that advances from a
        level team match the tie-breaks could not settle."""
        team_board = self._t.team_boards_by_id[team_board_id]
        stb = team_board.stored_team_board
        if team_id is not None and team_id not in (stb.team_a_id, stb.team_b_id):
            raise ValueError(
                f'Team [{team_id}] is not in team match [{team_board_id}].'
            )
        stb.knockout_winner_team_id = team_id
        with EventDatabase(self._t.event.uniq_id, write=True) as database:
            database.update_stored_team_board(stb)
        self.invalidate_engine_cache()
        self._t.clear_team_cache()

    def set_player_match_winner(self, board_id: int, player_id: int | None) -> None:
        """Designate (or clear, with ``None``) the player that advances from a
        drawn game the tie-breaks could not settle."""
        board = self._t.boards_by_id[board_id]
        stored_board = board.stored_board
        if player_id is not None and player_id not in (
            stored_board.white_player_id,
            stored_board.black_player_id,
        ):
            raise ValueError(f'Player [{player_id}] is not on board [{board_id}].')
        # StoredBoard is frozen; use the field-setting helper.
        set_stored_fields(stored_board, knockout_winner_player_id=player_id)
        with EventDatabase(self._t.event.uniq_id, write=True) as database:
            database.update_stored_board(stored_board)
        self.invalidate_engine_cache()

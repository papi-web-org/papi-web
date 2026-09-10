"""Two-game knock-out match helpers.

The mixins here map application rounds onto two-game bracket levels, render
aggregate scores, and expose advancement controls only on the second game.
"""

from typing import TYPE_CHECKING, Any, Protocol, cast

from common.i18n import _
from data.pairings.knockout_helpers.common import (
    find_knockout_board,
    find_knockout_team_board,
    team_match_all_games_played,
    tie_resolution_message,
)
from data.pairings.knockout_helpers.single import single_elimination_round_name
from utils import Utils

if TYPE_CHECKING:
    from data.board import Board
    from data.pairings.knockout_helpers.advancement import KnockoutAdvancement
    from data.pairings.knockout_helpers.layout import MatchDescriptor
    from data.teams.team_board import TeamBoard
    from data.tournament import Tournament, TournamentPlayer


class _TwoGameMatchHost(Protocol):
    @staticmethod
    def _labels_from_values(
        values: dict[int, float], ids: list[int], rounds: int
    ) -> dict[int, str]: ...

    def player_advancement(
        self, tournament: 'Tournament', board: 'Board'
    ) -> 'KnockoutAdvancement': ...

    def team_advancement(
        self, tournament: 'Tournament', team_board: 'TeamBoard'
    ) -> 'KnockoutAdvancement': ...

    def ranking_value(
        self,
        tournament: 'Tournament',
        player: 'TournamentPlayer',
        *,
        after_round: int,
    ) -> float: ...

    def team_ranking_values(
        self, tournament: 'Tournament', *, after_round: int
    ) -> dict[int, float]: ...


class _TwoGameSingleElimHost(Protocol):
    def invalid_player_count_message(self, tournament: 'Tournament') -> str | None: ...

    def _bracket_pairs(
        self, tournament: 'Tournament', round_: int
    ) -> list[tuple[int | None, int | None]]: ...

    def _pair_winner(
        self,
        tournament: 'Tournament',
        round_: int,
        a_id: int | None,
        b_id: int | None,
    ) -> int | None: ...

    def _round_winner_ids(
        self, tournament: 'Tournament', round_: int
    ) -> list[int | None] | None: ...

    def _round_winner_team_ids(
        self, tournament: 'Tournament', round_: int
    ) -> list[int | None] | None: ...

    def _bracket_team_pairs(
        self, tournament: 'Tournament', round_: int
    ) -> list[tuple[int | None, int | None]]: ...

    def _team_pair_winner(
        self,
        tournament: 'Tournament',
        round_: int,
        a_id: int | None,
        b_id: int | None,
    ) -> int | None: ...

    def _single_elim_slot(
        self, tournament: 'Tournament', round_: int, index: int, cache: dict
    ) -> tuple[int | None, int | None, int | None]: ...

    @staticmethod
    def _third_place_label() -> str: ...

    def _third_place_pairs(
        self,
        tournament: 'Tournament',
        *,
        stage: int,
        final_stage: int,
    ) -> list[tuple[int, int]]: ...

    def _third_place_match_descriptor(
        self,
        tournament: 'Tournament',
        *,
        final_stage: int,
        app_round: int,
        cache: dict,
    ) -> 'MatchDescriptor | None': ...

    def _third_place_ranking_value(
        self,
        tournament: 'Tournament',
        participant_id: int,
        *,
        final_stage: int,
        after_stage: int,
    ) -> float | None: ...

    def _is_third_place_participant_pair(
        self,
        tournament: 'Tournament',
        participant_ids: set[int],
        *,
        stage: int,
        final_stage: int,
    ) -> bool: ...


class TwoGameMatchMixin:
    """Elimination-agnostic two-game match behavior."""

    GAMES_PER_MATCH = 2

    def _two_game_match_host(self) -> _TwoGameMatchHost:
        return cast(_TwoGameMatchHost, self)

    @staticmethod
    def _level_of(app_round: int) -> int:
        return (app_round + 1) // 2

    @staticmethod
    def _game_of(app_round: int) -> int:
        return 2 - (app_round % 2)

    @staticmethod
    def _game_app_round(level: int, game: int) -> int:
        return 2 * level - 2 + game

    def _level_count(self, tournament: 'Tournament') -> int:
        return tournament.rounds // self.GAMES_PER_MATCH

    def _completed_level_count(self, after_round: int) -> int:
        return after_round // self.GAMES_PER_MATCH

    def standing_labels(
        self, tournament: 'Tournament', *, after_round: int | None = None
    ) -> dict[int, str]:
        if after_round is None:
            after_round = tournament.max_ranking_round
        host = self._two_game_match_host()
        values = {
            player.id: host.ranking_value(tournament, player, after_round=after_round)
            for player in tournament.tournament_players
        }
        return host._labels_from_values(
            values,
            [p.id for p in tournament.tournament_players],
            self._level_count(tournament),
        )

    def team_standing_labels(
        self, tournament: 'Tournament', *, after_round: int | None = None
    ) -> dict[int, str]:
        if after_round is None:
            after_round = tournament.max_ranking_round
        host = self._two_game_match_host()
        values = host.team_ranking_values(tournament, after_round=after_round)
        return host._labels_from_values(
            values,
            [team.id for team in tournament.teams],
            self._level_count(tournament),
        )

    @staticmethod
    def _slot_scores(
        tournament: 'Tournament',
        app_round: int,
        a_id: int | None,
        b_id: int | None,
    ) -> tuple[str, str]:
        if a_id is None or b_id is None:
            return ('', '')
        level = app_round
        totals = {a_id: 0.0, b_id: 0.0}
        for game in (1, 2):
            game_round = 2 * level - 2 + game
            if tournament.pairing_system.paired_by_team:
                team_board = find_knockout_team_board(
                    tournament, game_round, a_id, b_id
                )
                if team_board is None or team_board.no_games_played:
                    return ('', '')
                x_gp, y_gp = team_board.game_points
                if team_board.stored_team_board.team_a_id != a_id:
                    x_gp, y_gp = y_gp, x_gp
                totals[a_id] += x_gp
                totals[b_id] += y_gp
            else:
                board = find_knockout_board(tournament, game_round, a_id, b_id)
                if board is None or board.no_result:
                    return ('', '')
                white = board.optional_white_tournament_player
                white_id = white.id if white is not None else None
                white_pts = board.white_pairing.result.points()
                black_pts = board.black_pairing.result.points()
                if white_id == a_id:
                    totals[a_id] += white_pts
                    totals[b_id] += black_pts
                else:
                    totals[a_id] += black_pts
                    totals[b_id] += white_pts
        return (Utils.points_str(totals[a_id]), Utils.points_str(totals[b_id]))

    @staticmethod
    def _add_individual_points(board, totals: dict[int, float]) -> None:
        white = board.optional_white_tournament_player
        black = board.black_tournament_player
        if white is not None and white.id in totals:
            totals[white.id] += board.white_pairing.result.points()
        if black is not None and black.id in totals:
            totals[black.id] += board.black_pairing.result.points()

    def board_advancement(
        self, tournament: 'Tournament', board: 'Board'
    ) -> 'KnockoutAdvancement | None':
        if self._game_of(board.round) != 2:
            return None
        white = board.optional_white_tournament_player
        black = board.black_tournament_player
        if white is None or black is None or board.no_result:
            return None
        level = self._level_of(board.round)
        game1 = find_knockout_board(
            tournament,
            self._game_app_round(level, 1),
            white.id,
            black.id,
        )
        if game1 is None or game1.no_result:
            return None
        totals = {white.id: 0.0, black.id: 0.0}
        for game_board in (game1, board):
            self._add_individual_points(game_board, totals)
        if totals[white.id] != totals[black.id]:
            return None
        return self._two_game_match_host().player_advancement(tournament, board)

    def team_board_advancement(
        self, tournament: 'Tournament', team_board: 'TeamBoard'
    ) -> 'KnockoutAdvancement | None':
        if self._game_of(team_board.round) != 2:
            return None
        stb = team_board.stored_team_board
        if stb.team_b_id is None or not team_match_all_games_played(team_board):
            return None
        level = self._level_of(team_board.round)
        leg1 = find_knockout_team_board(
            tournament,
            self._game_app_round(level, 1),
            stb.team_a_id,
            stb.team_b_id,
        )
        if leg1 is None or not team_match_all_games_played(leg1):
            return None
        totals = {stb.team_a_id: 0.0, stb.team_b_id: 0.0}
        for leg in (leg1, team_board):
            leg_stb = leg.stored_team_board
            a_gp, b_gp = leg.effective_game_points
            if leg_stb.team_a_id in totals:
                totals[leg_stb.team_a_id] += a_gp
            if leg_stb.team_b_id is not None and leg_stb.team_b_id in totals:
                totals[leg_stb.team_b_id] += b_gp
        if totals[stb.team_a_id] != totals[stb.team_b_id]:
            return None
        return self._two_game_match_host().team_advancement(tournament, team_board)

    def unresolved_matches(
        self, tournament: 'Tournament', round_: int
    ) -> list[dict[str, Any]]:
        if self._game_of(round_) != 2:
            return []
        matches: list[dict[str, Any]] = []
        if tournament.pairing_system.paired_by_team:
            for team_board in tournament.get_round_team_boards(round_):
                advancement = self.team_board_advancement(tournament, team_board)
                if advancement is None or advancement.winner_id is not None:
                    continue
                stb = team_board.stored_team_board
                if stb.team_a_id is None or stb.team_b_id is None:
                    continue
                team_a = tournament.event.teams_by_id.get(stb.team_a_id)
                team_b = tournament.event.teams_by_id.get(stb.team_b_id)
                matches.append(
                    {
                        'kind': 'team',
                        'id': team_board.id,
                        'a_id': stb.team_a_id,
                        'a_name': team_a.name if team_a else '',
                        'b_id': stb.team_b_id,
                        'b_name': team_b.name if team_b else '',
                        'winner_id': stb.knockout_winner_team_id,
                    }
                )
            return matches
        for board in tournament.get_round_boards(round_):
            advancement = self.board_advancement(tournament, board)
            if advancement is None or advancement.winner_id is not None:
                continue
            white = board.optional_white_tournament_player
            black = board.black_tournament_player
            if white is None or black is None:
                continue
            matches.append(
                {
                    'kind': 'player',
                    'id': board.id,
                    'a_id': white.id,
                    'a_name': white.full_name,
                    'b_id': black.id,
                    'b_name': black.full_name,
                    'winner_id': board.stored_board.knockout_winner_player_id,
                }
            )
        return matches


class TwoGameSingleElimMixin(TwoGameMatchMixin):
    """Single-elimination two-game behavior."""

    def _two_game_single_elim_host(self) -> _TwoGameSingleElimHost:
        return cast(_TwoGameSingleElimHost, self)

    def pairings_generation_disabled_message(
        self, tournament: 'Tournament', at_round: int
    ) -> str | None:
        host = self._two_game_single_elim_host()
        if message := host.invalid_player_count_message(tournament):
            return message
        if at_round <= 1:
            return None
        for app_round in range(1, at_round):
            if not tournament.is_round_finished(app_round):
                return _(
                    'Pairings generation not allowed if previous rounds have '
                    'missing results.'
                )
        for level in range(1, (at_round - 1) // self.GAMES_PER_MATCH + 1):
            if self._level_winner_ids(tournament, level) is None:
                return tie_resolution_message(
                    tournament, self._game_app_round(level, 2)
                )
        return None

    def _level_winner_ids(
        self, tournament: 'Tournament', level: int
    ) -> list[int | None] | None:
        host = self._two_game_single_elim_host()
        if tournament.pairing_system.paired_by_team:
            return host._round_winner_team_ids(tournament, level)
        return host._round_winner_ids(tournament, level)

    def _two_game_level_pairs(
        self, tournament: 'Tournament', level: int
    ) -> list[tuple[int | None, int | None]]:
        host = self._two_game_single_elim_host()
        pairs = (
            host._bracket_team_pairs(tournament, level)
            if tournament.pairing_system.paired_by_team
            else host._bracket_pairs(tournament, level)
        )
        return pairs + host._third_place_pairs(
            tournament, stage=level, final_stage=self._level_count(tournament)
        )

    def board_section_label(self, tournament: 'Tournament', board) -> str | None:
        level = self._level_of(board.round)
        game = self._game_of(board.round)
        if tournament.pairing_system.paired_by_team:
            stb = board.stored_team_board
            seated = {
                team_id
                for team_id in (stb.team_a_id, stb.team_b_id)
                if team_id is not None
            }
        else:
            seated = {
                player.id
                for player in (
                    board.optional_white_tournament_player,
                    board.black_tournament_player,
                )
                if player is not None
            }
        host = self._two_game_single_elim_host()
        if host._is_third_place_participant_pair(
            tournament,
            seated,
            stage=level,
            final_stage=self._level_count(tournament),
        ):
            stage = host._third_place_label()
        else:
            stage = single_elimination_round_name(level, self._level_count(tournament))
        return _('{stage} — game {game}').format(stage=stage, game=game)

    def bracket_match_descriptors(
        self, tournament: 'Tournament'
    ) -> list['MatchDescriptor']:
        from data.pairings.knockout_helpers.layout import MatchDescriptor

        levels = self._level_count(tournament)
        bracket_size = 2**levels
        cache: dict = {}
        descriptors: list[MatchDescriptor] = []
        host = self._two_game_single_elim_host()
        for level in range(1, levels + 1):
            for index in range(bracket_size // (2**level)):
                a_id, b_id, winner = host._single_elim_slot(
                    tournament, level, index, cache
                )
                descriptors.append(
                    MatchDescriptor(
                        id=f'R{level}.{index}',
                        section='main',
                        column=level - 1,
                        round_name=single_elimination_round_name(level, levels),
                        app_round=level,
                        played_rounds=(
                            self._game_app_round(level, 1),
                            self._game_app_round(level, 2),
                        ),
                        a_id=a_id,
                        b_id=b_id,
                        winner_id=winner,
                        source_top=(f'R{level - 1}.{2 * index}' if level > 1 else None),
                        source_bottom=(
                            f'R{level - 1}.{2 * index + 1}' if level > 1 else None
                        ),
                    )
                )
        third_place = host._third_place_match_descriptor(
            tournament, final_stage=levels, app_round=levels, cache=cache
        )
        if third_place is not None:
            descriptors.append(third_place)
        return descriptors

    def ranking_value(
        self, tournament: 'Tournament', player: 'TournamentPlayer', *, after_round: int
    ) -> float:
        if tournament.pairing_system.paired_by_team:
            # Generic player rankings are still requested for team tournaments.
            # Mirror the player's team placement in those views.
            if player.team_id is None:
                return 0.0
            return self.team_ranking_values(tournament, after_round=after_round).get(
                player.team_id, 0.0
            )
        levels = self._level_count(tournament)
        last_level = min(self._completed_level_count(after_round), levels)
        host = self._two_game_single_elim_host()
        for level in range(1, last_level + 1):
            for high, low in host._bracket_pairs(tournament, level):
                if player.id not in (high, low):
                    continue
                winner = host._pair_winner(tournament, level, high, low)
                if winner is not None and winner != player.id:
                    third_place_value = host._third_place_ranking_value(
                        tournament,
                        player.id,
                        final_stage=levels,
                        after_stage=last_level,
                    )
                    if third_place_value is not None:
                        return third_place_value
                    return float(level)
                break
        return float(levels + 1)

    def team_ranking_values(
        self, tournament: 'Tournament', *, after_round: int
    ) -> dict[int, float]:
        levels = self._level_count(tournament)
        last_level = min(self._completed_level_count(after_round), levels)
        host = self._two_game_single_elim_host()
        values: dict[int, float] = {}
        for team in tournament.teams:
            value = float(levels + 1)
            for level in range(1, last_level + 1):
                match = next(
                    (
                        (a, b)
                        for a, b in host._bracket_team_pairs(tournament, level)
                        if team.id in (a, b)
                    ),
                    None,
                )
                if match is None:
                    continue
                winner = host._team_pair_winner(tournament, level, *match)
                if winner is not None and winner != team.id:
                    third_place_value = host._third_place_ranking_value(
                        tournament,
                        team.id,
                        final_stage=levels,
                        after_stage=last_level,
                    )
                    value = (
                        third_place_value
                        if third_place_value is not None
                        else float(level)
                    )
                    break
            values[team.id] = value
        return values

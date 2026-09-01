"""Bracket display and standing-label helpers for knock-out engines."""

from typing import TYPE_CHECKING, Any, Protocol, cast

from common.i18n import _
from data.pairings.knockout_helpers.common import (
    find_knockout_board,
    find_knockout_team_board,
    team_match_winner_id,
)
from utils import Utils
from utils.enum import Result

if TYPE_CHECKING:
    from data.pairings.knockout_helpers.layout import BracketLayout, MatchDescriptor
    from data.teams.team_board import TeamBoard
    from data.tournament import Tournament, TournamentPlayer


class _KnockoutDisplayHost(Protocol):
    def bracket_match_descriptors(
        self, tournament: 'Tournament'
    ) -> list['MatchDescriptor']: ...

    def _grouping_dimension(self, tournament: 'Tournament') -> Any: ...

    def _teams_for_tournament(self, tournament: 'Tournament') -> list[Any]: ...


class KnockoutDisplayMixin:
    """Build bracket layouts and standing labels for knock-out engines."""

    def _display_host(self) -> _KnockoutDisplayHost:
        return cast(_KnockoutDisplayHost, self)

    def bracket_layout(self, tournament: 'Tournament') -> 'BracketLayout':
        from data.pairings.knockout_helpers.layout import (
            BracketColumn,
            BracketLayout,
            BracketMatch,
            BracketSection,
            BracketSlot,
        )

        host = self._display_host()
        descriptors = host.bracket_match_descriptors(tournament)
        dimension = host._grouping_dimension(tournament)
        seed_by_id = self._seed_by_id(tournament)

        def build_slot(pid: int | None, score: str, is_winner: bool) -> BracketSlot:
            return BracketSlot(
                name=self._participant_name(tournament, pid),
                score=score,
                winner=is_winner,
                participant_id=pid,
                detail=self._participant_detail(tournament, pid),
                group=self._participant_group(tournament, pid, dimension),
                seed=(
                    ''
                    if dimension is not None or pid is None
                    else str(seed_by_id.get(pid, ''))
                ),
            )

        def build_match(descriptor) -> BracketMatch:
            score_a, score_b = self._slot_scores(
                tournament, descriptor.app_round, descriptor.a_id, descriptor.b_id
            )
            winner = descriptor.winner_id
            return BracketMatch(
                id=descriptor.id,
                top=build_slot(
                    descriptor.a_id,
                    score_a,
                    winner is not None and winner == descriptor.a_id,
                ),
                bottom=build_slot(
                    descriptor.b_id,
                    score_b,
                    winner is not None and winner == descriptor.b_id,
                ),
                source_top=descriptor.source_top,
                source_bottom=descriptor.source_bottom,
            )

        def _match_order(descriptor) -> int:
            parts = descriptor.id.split('.')
            return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

        sections: list[BracketSection] = []
        for key in ('upper', 'lower', 'final', 'main', 'third'):
            section_descriptors = [d for d in descriptors if d.section == key]
            if not section_descriptors:
                continue
            by_column: dict[int, list] = {}
            for descriptor in section_descriptors:
                by_column.setdefault(descriptor.column, []).append(descriptor)
            columns: list[BracketColumn] = []
            for column_index in sorted(by_column):
                column_descriptors = sorted(by_column[column_index], key=_match_order)
                first = column_descriptors[0]
                columns.append(
                    BracketColumn(
                        name=first.round_name,
                        app_round=first.app_round,
                        matches=tuple(build_match(d) for d in column_descriptors),
                        app_rounds=first.played_rounds or (first.app_round,),
                    )
                )
            sections.append(BracketSection(key=key, columns=tuple(columns)))
        return BracketLayout(
            sections=tuple(sections),
            is_double_elimination=any(s.key == 'lower' for s in sections),
        )

    @staticmethod
    def _participant_name(tournament: 'Tournament', participant_id: int | None) -> str:
        if participant_id is None:
            return ''
        if tournament.pairing_system.paired_by_team:
            team = tournament.teams_by_id.get(participant_id)
            return team.name if team is not None else ''
        player = tournament.tournament_players_by_id.get(participant_id)
        return player.full_name if player is not None else ''

    @staticmethod
    def _participant_detail(
        tournament: 'Tournament', participant_id: int | None
    ) -> str:
        if participant_id is None or tournament.pairing_system.paired_by_team:
            return ''
        player = tournament.tournament_players_by_id.get(participant_id)
        return f'({player.rating_str})' if player is not None else ''

    @staticmethod
    def _participant_group(
        tournament: 'Tournament', participant_id: int | None, dimension: Any
    ) -> str:
        if participant_id is None or dimension is None:
            return ''
        if tournament.pairing_system.paired_by_team:
            entity: Any = tournament.event.teams_by_id.get(participant_id)
        else:
            entity = tournament.tournament_players_by_id.get(participant_id)
        if entity is None:
            return ''
        return dimension.group_key(entity) or ''

    def _seed_by_id(self, tournament: 'Tournament') -> dict[int, int]:
        if tournament.pairing_system.paired_by_team:
            return {
                team.id: (
                    team.pairing_number
                    if team.pairing_number is not None
                    else index + 1
                )
                for index, team in enumerate(
                    self._display_host()._teams_for_tournament(tournament)
                )
            }
        return {
            player.id: rank
            for rank, player in tournament.tournament_players_by_starting_rank.items()
        }

    @staticmethod
    def _slot_scores(
        tournament: 'Tournament',
        app_round: int,
        a_id: int | None,
        b_id: int | None,
    ) -> tuple[str, str]:
        if a_id is None or b_id is None:
            return ('', '')
        if tournament.pairing_system.paired_by_team:
            team_board = find_knockout_team_board(tournament, app_round, a_id, b_id)
            if team_board is None or team_board.no_games_played:
                return ('', '')
            a_gp, b_gp = team_board.game_points
            if team_board.stored_team_board.team_a_id != a_id:
                a_gp, b_gp = b_gp, a_gp
            return (Utils.points_str(a_gp), Utils.points_str(b_gp))
        board = find_knockout_board(tournament, app_round, a_id, b_id)
        if board is None or board.no_result:
            return ('', '')
        white = board.optional_white_tournament_player
        white_id = white.id if white is not None else None
        white_score = Utils.points_str(board.white_pairing.result.points())
        black_score = Utils.points_str(board.black_pairing.result.points())
        if white_id == a_id:
            return (white_score, black_score)
        return (black_score, white_score)

    def ranking_value(
        self, tournament: 'Tournament', player: 'TournamentPlayer', *, after_round: int
    ) -> float:
        if tournament.pairing_system.paired_by_team:
            # A team knock-out eliminates teams, not players: a player who lost
            # a board is still in while their team is. Player rankings are asked
            # for all the same, so give each player their team's placement.
            if player.team_id is None:
                return 0.0
            return self.team_ranking_values(tournament, after_round=after_round).get(
                player.team_id, 0.0
            )
        placement = getattr(self, 'knockout_placement_values', None)
        if placement is not None:
            return placement(tournament, after_round=after_round).get(
                player.id, float(tournament.rounds + 1)
            )
        first_loss: int | None = None
        for round_ in range(1, after_round + 1):
            pairing = player.pairings[round_]
            if pairing.exists and self._player_lost(tournament, player, pairing):
                first_loss = round_
                break
        if first_loss is None:
            return float(tournament.rounds + 1)
        third_place_ranking_value = getattr(self, '_third_place_ranking_value', None)
        if third_place_ranking_value is not None:
            value = third_place_ranking_value(
                tournament,
                player.id,
                final_stage=tournament.rounds,
                after_stage=after_round,
            )
            if value is not None:
                return value
        return float(first_loss)

    @staticmethod
    def _player_lost(tournament: 'Tournament', player, pairing) -> bool:
        result = pairing.result
        if result.is_loss or result in (Result.FORFEIT_LOSS, Result.DOUBLE_FORFEIT):
            return True
        if result.is_draw:
            board = tournament.boards_by_id.get(pairing.stored_pairing.board_id)
            winner_id = (
                tournament.knockout.advancement_winner_player(board)
                if board is not None
                else None
            )
            return winner_id is not None and winner_id != player.id
        return False

    def team_ranking_values(
        self, tournament: 'Tournament', *, after_round: int
    ) -> dict[int, float]:
        placement = getattr(self, 'knockout_placement_values', None)
        if placement is not None:
            placed = placement(tournament, after_round=after_round)
            return {
                team.id: placed.get(team.id, float(tournament.rounds + 1))
                for team in tournament.teams
            }
        values: dict[int, float] = {}
        third_place_ranking_value = getattr(self, '_third_place_ranking_value', None)
        for team in tournament.teams:
            value = float(tournament.rounds + 1)
            for round_ in range(1, after_round + 1):
                team_board = self._team_board(tournament, team.id, round_)
                if team_board is None:
                    continue
                winner = team_match_winner_id(tournament, team_board)
                if winner is not None and winner != team.id:
                    value = float(round_)
                    if third_place_ranking_value is not None:
                        third_place_value = third_place_ranking_value(
                            tournament,
                            team.id,
                            final_stage=tournament.rounds,
                            after_stage=after_round,
                        )
                        if third_place_value is not None:
                            value = third_place_value
                    break
            values[team.id] = value
        return values

    @staticmethod
    def _team_board(
        tournament: 'Tournament', team_id: int, round_: int
    ) -> 'TeamBoard | None':
        for team_board in tournament.team_boards_by_round.get(round_, []):
            stb = team_board.stored_team_board
            if team_id in (stb.team_a_id, stb.team_b_id):
                return team_board
        return None

    def standing_labels(
        self, tournament: 'Tournament', *, after_round: int | None = None
    ) -> dict[int, str]:
        if after_round is None:
            after_round = tournament.ranked_after_round
        values = {
            player.id: self.ranking_value(tournament, player, after_round=after_round)
            for player in tournament.tournament_players
        }
        return self._labels_from_values(
            values, [p.id for p in tournament.tournament_players], tournament.rounds
        )

    def team_standing_labels(
        self, tournament: 'Tournament', *, after_round: int | None = None
    ) -> dict[int, str]:
        if after_round is None:
            after_round = tournament.ranked_after_round
        values = self.team_ranking_values(tournament, after_round=after_round)
        return self._labels_from_values(
            values, [team.id for team in tournament.teams], tournament.rounds
        )

    @staticmethod
    def _labels_from_values(
        values: dict[int, float], ids: list[int], rounds: int
    ) -> dict[int, str]:
        still_in = [eid for eid in ids if values[eid] >= rounds + 1]
        sole_survivor = still_in[0] if len(still_in) == 1 else None
        has_third = any(values[eid] == rounds - 0.5 for eid in ids)
        labels: dict[int, str] = {}
        for eid in ids:
            value = values[eid]
            if value >= rounds + 1:
                labels[eid] = _('Winner') if eid == sole_survivor else _('Still in')
            elif value == rounds:
                labels[eid] = _('Runner-up')
            elif value == rounds - 0.5:
                labels[eid] = _('Third place')
            elif value == rounds - 1 and has_third:
                labels[eid] = _('Fourth place')
            else:
                labels[eid] = _('Out — round {round}').format(round=int(value))
        return labels

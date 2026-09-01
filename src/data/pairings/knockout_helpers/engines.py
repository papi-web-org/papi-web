from typing import TYPE_CHECKING, override

from common.i18n import _
from data.pairings import double_elimination
from data.pairings.knockout_helpers import bracket as knockout_bracket
from data.pairings.engines import PairingEngine, TeamPairingEngine
from data.pairings.knockout_helpers.advancement import (
    KnockoutAdvancementMixin as _KnockoutAdvancementMixin,
)
from data.pairings.knockout_helpers.colour import (
    KnockoutColourMixin as _KnockoutColourMixin,
)
from data.pairings.knockout_helpers.common import (
    board_winner_player_id,
    find_knockout_board,
    find_knockout_team_board,
    team_match_winner_id,
    tie_resolution_message as _tie_resolution_message,
)
from data.pairings.knockout_helpers.display import (
    KnockoutDisplayMixin as _KnockoutRenderMixin,
)
from data.pairings.knockout_helpers.double import (
    DoubleEliminationMixin as _DoubleEliminationMixin,
    TwoGameDoubleElimMixin as _TwoGameDoubleElimMixin,
)
from data.pairings.knockout_helpers.grouping import (
    KnockoutGroupingMixin as _KnockoutGroupingMixin,
)
from data.pairings.knockout_helpers.settings import KnockoutThirdPlaceSetting
from data.pairings.knockout_helpers.single import (
    SingleEliminationBracketMixin,
    single_elimination_round_name as _single_elimination_round_name,
)
from data.pairings.knockout_helpers.systems import TeamKnockoutPairingSystem
from data.pairings.knockout_helpers.two_game import (
    TwoGameSingleElimMixin as _TwoGameSingleElimMixin,
)
from database.sqlite.event.event_store import StoredBoard

if TYPE_CHECKING:
    from data.board import Board
    from data.teams.team_board import TeamBoard
    from data.tournament import Tournament


class KnockoutEngine(
    SingleEliminationBracketMixin,
    _KnockoutColourMixin,
    _KnockoutGroupingMixin,
    _KnockoutRenderMixin,
    _KnockoutAdvancementMixin,
    PairingEngine,
):
    """Individual knock-out. Round one seeds by starting rank and pairs the
    bracket; each later round pairs the previous round's winners."""

    MIN_PLAYERS = 2

    @override
    def invalid_player_count_message(self, tournament: 'Tournament') -> str | None:
        if tournament.player_count < self.MIN_PLAYERS:
            return _(
                'Too few players to generate the pairings (minimum: {min}).'
            ).format(min=self.MIN_PLAYERS)
        return None

    @override
    def pairings_generation_disabled_message(
        self, tournament: 'Tournament', at_round: int
    ) -> str | None:
        if message := super().pairings_generation_disabled_message(
            tournament, at_round
        ):
            return message
        if at_round <= 1:
            return None
        for round_ in range(1, at_round):
            if not tournament.is_round_finished(round_):
                return _(
                    'Pairings generation not allowed if previous rounds have '
                    'missing results.'
                )
            if self._round_winner_ids(tournament, round_) is None:
                return _tie_resolution_message(tournament, round_)
        return None

    def _bracket_pairs(
        self, tournament: 'Tournament', round_: int
    ) -> list[tuple[int | None, int | None]]:
        return self._single_elim_bracket_pairs(tournament, round_)

    def _round_loser_ids(
        self, tournament: 'Tournament', round_: int
    ) -> list[int] | None:
        return self._single_elim_round_loser_ids(tournament, round_)

    def _round_winner_ids(
        self, tournament: 'Tournament', round_: int
    ) -> list[int | None] | None:
        return self._single_elim_round_winner_ids(tournament, round_)

    def _single_elim_first_round_pairs(
        self, tournament: 'Tournament'
    ) -> list[tuple[int | None, int | None]]:
        return self._first_round_player_pairs(tournament)

    def _single_elim_pair_winner(
        self, tournament: 'Tournament', round_: int, a_id: int | None, b_id: int | None
    ) -> int | None:
        return self._pair_winner(tournament, round_, a_id, b_id)

    def _single_elim_third_place_enabled(self, tournament: 'Tournament') -> bool:
        return (
            KnockoutThirdPlaceSetting.get_value(tournament)
            and self._grouping_dimension(tournament) is None
        )

    def board_section_label(self, tournament: 'Tournament', board) -> str | None:
        """The round name of a board — Final, Semifinals, …, or 'Third-place
        playoff' for the bronze match sharing the final round."""
        rounds = tournament.rounds
        if board.round == rounds:
            seated = {
                player.id
                for player in (
                    board.optional_white_tournament_player,
                    board.black_tournament_player,
                )
                if player is not None
            }
            if self._is_third_place_participant_pair(
                tournament, seated, stage=board.round, final_stage=rounds
            ):
                return self._third_place_label()
        return _single_elimination_round_name(board.round, rounds)

    def _pair_winner(
        self, tournament: 'Tournament', round_: int, a_id: int | None, b_id: int | None
    ) -> int | None:
        """Winner of a single match (regardless of the rest of the round), or
        ``None`` while undecided. A bye advances its lone player."""
        if b_id is None:
            return a_id
        board = self._find_board(tournament, round_, a_id, b_id)
        if board is None:
            return None
        winner = board_winner_player_id(board)
        if winner is None and not board.no_result:
            winner = tournament.knockout.advancement_winner_player(board)
        return winner

    @staticmethod
    def _find_board(
        tournament: 'Tournament', round_: int, a_id: int | None, b_id: int
    ) -> 'Board | None':
        """The round's board that *a_id* and *b_id* were paired on. Prefer
        the board seating exactly the two of them, but a knock-out player
        has only one game per round, so if an earlier round's result was
        edited after this one was paired (the recomputed opponent no longer
        matches what was played) fall back to the board holding whichever of
        the two is actually present — that is still their real match."""
        return find_knockout_board(tournament, round_, a_id, b_id)

    @override
    def _generate_stored_boards(
        self,
        tournament: 'Tournament',
        round_: int,
        partial_pairings: bool = False,
        prohibited_pairing_override: 'list | None' = None,
    ) -> list[StoredBoard]:
        # A grouped bracket can carry all-virtual (None, None) phantom slots
        # for alignment; they seat no board, so drop them (and narrow the
        # remaining high slots to real ids) before colouring.
        seated = [
            (high, low)
            for high, low in self._bracket_pairs(tournament, round_)
            if high is not None
        ]
        pairs = self._coloured_player_pairs(tournament, round_, seated)
        return self._boards_from_pairs(pairs)

    def _first_round_player_pairs(
        self, tournament: 'Tournament'
    ) -> list[tuple[int | None, int | None]]:
        """Round-one ``(white_id, black_id | None)`` pairs, seeded by starting
        rank (or by group when a grouping dimension is set). ``None`` marks a
        bye; a grouped bracket can also carry an all-virtual ``(None, None)``
        slot (a phantom group), dropped before boards are created."""
        leaves = self._grouped_leaves(tournament)
        if leaves is not None:
            return list(zip(leaves[::2], leaves[1::2]))
        by_rank = tournament.tournament_players_by_starting_rank
        result: list[tuple[int | None, int | None]] = []
        if tournament.player_count < self.MIN_PLAYERS:
            # No bracket below two players; the display asks for the layout
            # before the field is entered.
            return result
        for high_seed, low_seed in knockout_bracket.first_round_pairs(
            tournament.player_count
        ):
            white = by_rank[high_seed]
            black = by_rank[low_seed] if low_seed is not None else None
            result.append((white.id, black.id if black is not None else None))
        return result

    @staticmethod
    def _boards_from_pairs(
        pairs: list[tuple[int, int | None]],
    ) -> list[StoredBoard]:
        """Contested matches take the low table numbers in bracket order;
        the byes (no opponent) follow, so a bye never sits between two
        real games. (Grouped phantom slots are dropped before this is called.)"""
        contested = [(w, b) for w, b in pairs if b is not None]
        byes = [(w, b) for w, b in pairs if b is None]
        return [
            StoredBoard(
                id=None,
                white_player_id=white_id,
                black_player_id=black_id,
                index=index,
            )
            for index, (white_id, black_id) in enumerate([*contested, *byes])
        ]


class KnockoutTwoGameEngine(_TwoGameSingleElimMixin, KnockoutEngine):
    """Individual single-elimination *aller-retour*: every match is two games,
    colours forced (game 1 stronger seed White, game 2 reversed), decided on the
    aggregate."""

    @override
    def _generate_stored_boards(
        self,
        tournament: 'Tournament',
        round_: int,
        partial_pairings: bool = False,
        prohibited_pairing_override: 'list | None' = None,
    ) -> list[StoredBoard]:
        level = self._level_of(round_)
        game = self._game_of(round_)
        pairs: list[tuple[int, int | None]] = []
        for high, low in self._two_game_level_pairs(tournament, level):
            if high is None:
                continue  # grouped phantom slot: seats no board
            if low is None:
                pairs.append((high, None))
                continue
            white, black = self._stronger_players(tournament, high, low)
            if game == 2:
                white, black = black, white
            pairs.append((white, black))
        return self._boards_from_pairs(pairs)

    @override
    def _pair_winner(
        self, tournament: 'Tournament', round_: int, a_id: int | None, b_id: int | None
    ) -> int | None:
        """Winner of a *match* (bracket level ``round_``) on the aggregate of
        its two games, or ``None`` while either game is unplayed. A bye
        advances its lone player; an aggregate tie is handed to the advancement
        tie-breaks / manual play-off, designated on the game-2 board."""
        if b_id is None:
            return a_id
        if a_id is None:
            return b_id
        game1 = self._find_board(
            tournament, self._game_app_round(round_, 1), a_id, b_id
        )
        game2 = self._find_board(
            tournament, self._game_app_round(round_, 2), a_id, b_id
        )
        if game1 is None or game2 is None or game1.no_result or game2.no_result:
            return None
        totals = {a_id: 0.0, b_id: 0.0}
        for board in (game1, game2):
            self._add_individual_points(board, totals)
        if totals[a_id] > totals[b_id]:
            return a_id
        if totals[b_id] > totals[a_id]:
            return b_id
        return tournament.knockout.advancement_winner_player(game2)


class DoubleEliminationEngine(
    _KnockoutColourMixin,
    _KnockoutGroupingMixin,
    _KnockoutRenderMixin,
    _KnockoutAdvancementMixin,
    _DoubleEliminationMixin,
    PairingEngine,
):
    """Individual double elimination — seeds by starting rank, reads each
    match's winner from its board."""

    MIN_PLAYERS = 2

    @override
    def invalid_player_count_message(self, tournament: 'Tournament') -> str | None:
        if tournament.player_count < self.MIN_PLAYERS:
            return _(
                'Too few players to generate the pairings (minimum: {min}).'
            ).format(min=self.MIN_PLAYERS)
        return None

    def _participant_count(self, tournament: 'Tournament') -> int:
        return tournament.player_count

    def _board_participant_ids(self, board) -> set[int]:
        return {
            player.id
            for player in (
                board.optional_white_tournament_player,
                board.black_tournament_player,
            )
            if player is not None
        }

    def _seed_id(self, tournament: 'Tournament', seed: int) -> int:
        return tournament.tournament_players_by_starting_rank[seed].id

    def _played_match_winner(
        self, tournament: 'Tournament', match: double_elimination.Match, a_id, b_id
    ) -> int | None:
        board = find_knockout_board(tournament, match.round, a_id, b_id)
        winner = board_winner_player_id(board) if board is not None else None
        if winner is None and board is not None and not board.no_result:
            winner = tournament.knockout.advancement_winner_player(board)
        return winner

    @override
    def pairings_generation_disabled_message(
        self, tournament: 'Tournament', at_round: int
    ) -> str | None:
        if message := super().pairings_generation_disabled_message(
            tournament, at_round
        ):
            return message
        return self._double_elimination_gate(tournament, at_round)

    @override
    def _generate_stored_boards(
        self,
        tournament: 'Tournament',
        round_: int,
        partial_pairings: bool = False,
        prohibited_pairing_override: 'list | None' = None,
    ) -> list[StoredBoard]:
        pairs = self._coloured_player_pairs(
            tournament, round_, self._round_match_pairs(tournament, round_)
        )
        return KnockoutEngine._boards_from_pairs(pairs)


class DoubleEliminationTwoGameEngine(_TwoGameDoubleElimMixin, DoubleEliminationEngine):
    """Individual double elimination *aller-retour*: every match is two games,
    colours forced (game 1 stronger seed White, game 2 reversed), decided on the
    aggregate."""

    @override
    def _played_match_winner(
        self, tournament: 'Tournament', match: double_elimination.Match, a_id, b_id
    ) -> int | None:
        game1 = find_knockout_board(
            tournament, self._game_app_round(match.round, 1), a_id, b_id
        )
        game2 = find_knockout_board(
            tournament, self._game_app_round(match.round, 2), a_id, b_id
        )
        if game1 is None or game2 is None or game1.no_result or game2.no_result:
            return None
        totals = {a_id: 0.0, b_id: 0.0}
        for board in (game1, game2):
            self._add_individual_points(board, totals)
        if totals[a_id] > totals[b_id]:
            return a_id
        if totals[b_id] > totals[a_id]:
            return b_id
        return tournament.knockout.advancement_winner_player(game2)

    @override
    def _generate_stored_boards(
        self,
        tournament: 'Tournament',
        round_: int,
        partial_pairings: bool = False,
        prohibited_pairing_override: 'list | None' = None,
    ) -> list[StoredBoard]:
        game = self._game_of(round_)
        pairs: list[tuple[int, int | None]] = []
        for a_id, b_id in self._round_match_pairs(tournament, self._level_of(round_)):
            if b_id is None:
                pairs.append((a_id, None))
                continue
            white, black = self._stronger_players(tournament, a_id, b_id)
            if game == 2:
                white, black = black, white
            pairs.append((white, black))
        return KnockoutEngine._boards_from_pairs(pairs)


class TeamKnockoutEngine(
    SingleEliminationBracketMixin,
    _KnockoutColourMixin,
    _KnockoutGroupingMixin,
    _KnockoutRenderMixin,
    _KnockoutAdvancementMixin,
    TeamPairingEngine,
):
    """Team knock-out. Round one seeds by team pairing-number order; each
    later round pairs the winning teams of the previous round."""

    MIN_TEAMS = 2

    @property
    def system(self) -> TeamKnockoutPairingSystem:
        return TeamKnockoutPairingSystem()

    @property
    @override
    def byes_unpaired_absent_teams(self) -> bool:
        # A knocked-out team gets no sit-out bye — it is out of the bracket.
        return False

    @override
    def invalid_player_count_message(self, tournament: 'Tournament') -> str | None:
        if len(self._teams_for_tournament(tournament)) < self.MIN_TEAMS:
            return _('Too few teams to generate the pairings (minimum: {min}).').format(
                min=self.MIN_TEAMS
            )
        return None

    @override
    def pairings_generation_disabled_message(
        self, tournament: 'Tournament', at_round: int
    ) -> str | None:
        if message := super().pairings_generation_disabled_message(
            tournament, at_round
        ):
            return message
        if at_round <= 1:
            return None
        for round_ in range(1, at_round):
            if not tournament.is_round_finished(round_):
                return _(
                    'Pairings generation not allowed if previous rounds have '
                    'missing results.'
                )
            if self._round_winner_team_ids(tournament, round_) is None:
                return _tie_resolution_message(tournament, round_)
        return None

    def _bracket_team_pairs(
        self, tournament: 'Tournament', round_: int
    ) -> list[tuple[int | None, int | None]]:
        return self._single_elim_bracket_pairs(tournament, round_)

    def _round_loser_team_ids(
        self, tournament: 'Tournament', round_: int
    ) -> list[int] | None:
        return self._single_elim_round_loser_ids(tournament, round_)

    def _round_winner_team_ids(
        self, tournament: 'Tournament', round_: int
    ) -> list[int | None] | None:
        return self._single_elim_round_winner_ids(tournament, round_)

    def _single_elim_first_round_pairs(
        self, tournament: 'Tournament'
    ) -> list[tuple[int | None, int | None]]:
        return self._first_round_team_pairs(tournament)

    def _single_elim_pair_winner(
        self, tournament: 'Tournament', round_: int, a_id: int | None, b_id: int | None
    ) -> int | None:
        return self._team_pair_winner(tournament, round_, a_id, b_id)

    def _single_elim_third_place_enabled(self, tournament: 'Tournament') -> bool:
        return (
            KnockoutThirdPlaceSetting.get_value(tournament)
            and self._grouping_dimension(tournament) is None
        )

    def board_section_label(self, tournament: 'Tournament', team_board) -> str | None:
        """The round name of a team match — Final, Semifinals, …, or
        'Third-place playoff' for the bronze match in the final round."""
        rounds = tournament.rounds
        if team_board.round == rounds:
            stb = team_board.stored_team_board
            seated = {t for t in (stb.team_a_id, stb.team_b_id) if t is not None}
            if self._is_third_place_participant_pair(
                tournament, seated, stage=team_board.round, final_stage=rounds
            ):
                return self._third_place_label()
        return _single_elimination_round_name(team_board.round, rounds)

    def _team_pair_winner(
        self, tournament: 'Tournament', round_: int, a_id: int | None, b_id: int | None
    ) -> int | None:
        """Winning team of a single match, or ``None`` while undecided."""
        if b_id is None:
            return a_id
        team_board = self._find_team_board(tournament, round_, a_id, b_id)
        if team_board is None:
            return None
        return team_match_winner_id(tournament, team_board)

    @staticmethod
    def _find_team_board(
        tournament: 'Tournament', round_: int, a_id: int | None, b_id: int
    ) -> 'TeamBoard | None':
        """The round's match *a_id* and *b_id* were paired in. Prefer the
        one seating exactly the two teams, but a knock-out team plays a
        single match per round, so if an earlier round's result was edited
        after this one was paired (the recomputed opponent no longer matches
        what was played) fall back to the match holding whichever of the two
        is actually present — that is still their real match."""
        return find_knockout_team_board(tournament, round_, a_id, b_id)

    @override
    def generate_pairings(
        self,
        tournament: 'Tournament',
        round_: int,
        partial_pairings: bool = False,
    ) -> str:
        if self.pairings_generation_disabled_message(tournament, round_):
            raise ValueError(
                f'Pairings generation not allowed for round {round_} '
                f'of tournament [{tournament.name}].'
            )
        bracket_pairs = self._bracket_team_pairs(tournament, round_)
        if not bracket_pairs:
            return _('Pairing is not possible.')
        # A grouped bracket can carry all-virtual (None, None) phantom slots
        # for alignment; they seat no match, so drop them (and narrow the
        # remaining team_a slots to real ids) before colouring/persisting.
        seated = [(a, b) for a, b in bracket_pairs if a is not None]
        team_pairs = self._coloured_team_pairs(tournament, round_, seated)
        self._persist_team_round(tournament, round_, team_pairs)
        return ''

    def _first_round_team_pairs(
        self, tournament: 'Tournament'
    ) -> list[tuple[int | None, int | None]]:
        leaves = self._grouped_leaves(tournament)
        if leaves is not None:
            return list(zip(leaves[::2], leaves[1::2]))
        teams = self._teams_for_tournament(tournament)
        result: list[tuple[int | None, int | None]] = []
        if len(teams) < self.MIN_TEAMS:
            return result
        for high_seed, low_seed in knockout_bracket.first_round_pairs(len(teams)):
            team_a = teams[high_seed - 1]
            team_b = teams[low_seed - 1] if low_seed is not None else None
            result.append((team_a.id, team_b.id if team_b is not None else None))
        return result


class TeamKnockoutTwoGameEngine(_TwoGameSingleElimMixin, TeamKnockoutEngine):
    """Team single-elimination *aller-retour*: every match is two legs, the
    White orientation forced (leg 1 stronger team board-one White, leg 2
    reversed), decided on the aggregate game points of the two legs."""

    @override
    def generate_pairings(
        self,
        tournament: 'Tournament',
        round_: int,
        partial_pairings: bool = False,
    ) -> str:
        if self.pairings_generation_disabled_message(tournament, round_):
            raise ValueError(
                f'Pairings generation not allowed for round {round_} '
                f'of tournament [{tournament.name}].'
            )
        level = self._level_of(round_)
        game = self._game_of(round_)
        bracket_pairs = self._two_game_level_pairs(tournament, level)
        if not bracket_pairs:
            return _('Pairing is not possible.')
        seated = [(a, b) for a, b in bracket_pairs if a is not None]
        team_pairs = self._forced_team_pairs(tournament, game, seated)
        self._persist_team_round(tournament, round_, team_pairs)
        return ''

    def _forced_team_pairs(
        self,
        tournament: 'Tournament',
        game: int,
        seated: list[tuple[int, int | None]],
    ) -> list[tuple[int, int | None]]:
        """``(team_a, team_b)`` per match with the White orientation forced:
        leg 1 gives the stronger team board-one White, leg 2 reverses it.
        ``team_a`` is the board-one-White team when the colour pattern opens
        White, else ``team_b`` is."""
        team_a_white = self._team_a_is_board_one_white(tournament)
        result: list[tuple[int, int | None]] = []
        for a_id, b_id in seated:
            if b_id is None:
                result.append((a_id, None))
                continue
            strong, weak = self._stronger_teams(tournament, a_id, b_id)
            white_team, black_team = (strong, weak) if game == 1 else (weak, strong)
            result.append(
                (white_team, black_team) if team_a_white else (black_team, white_team)
            )
        return result

    @override
    def _team_pair_winner(
        self, tournament: 'Tournament', round_: int, a_id: int | None, b_id: int | None
    ) -> int | None:
        """Winning team of a *match* (bracket level ``round_``) on the aggregate
        game points of its two legs, or ``None`` while either leg is unfinished.
        A level tie is handed to the advancement tie-breaks / manual play-off,
        designated on the leg-2 match."""
        if b_id is None:
            return a_id
        leg1 = self._find_team_board(
            tournament, self._game_app_round(round_, 1), a_id, b_id
        )
        leg2 = self._find_team_board(
            tournament, self._game_app_round(round_, 2), a_id, b_id
        )
        if (
            leg1 is None
            or leg2 is None
            or not leg1.all_games_played
            or not leg2.all_games_played
        ):
            return None
        totals = {a_id: 0.0, b_id: 0.0}
        for team_board in (leg1, leg2):
            stb = team_board.stored_team_board
            a_gp, b_gp = team_board.effective_game_points
            if stb.team_a_id in totals:
                totals[stb.team_a_id] += a_gp
            if stb.team_b_id is not None and stb.team_b_id in totals:
                totals[stb.team_b_id] += b_gp
        if totals[a_id] > totals[b_id]:
            return a_id
        if totals[b_id] > totals[a_id]:
            return b_id
        return tournament.knockout.advancement_winner(leg2)


class TeamDoubleEliminationEngine(
    _KnockoutColourMixin,
    _KnockoutGroupingMixin,
    _KnockoutRenderMixin,
    _KnockoutAdvancementMixin,
    _DoubleEliminationMixin,
    TeamPairingEngine,
):
    """Team double elimination — seeds by team pairing-number order, reads
    each match's winner from its team match (game points, then the
    configured advancement tie-breaks / play-off for a level match)."""

    MIN_TEAMS = 2

    @property
    def system(self) -> TeamKnockoutPairingSystem:
        return TeamKnockoutPairingSystem()

    @property
    @override
    def byes_unpaired_absent_teams(self) -> bool:
        # A team not in this round is knocked out or waiting in the other
        # bracket, never sitting out on a bye.
        return False

    @override
    def invalid_player_count_message(self, tournament: 'Tournament') -> str | None:
        if len(self._teams_for_tournament(tournament)) < self.MIN_TEAMS:
            return _('Too few teams to generate the pairings (minimum: {min}).').format(
                min=self.MIN_TEAMS
            )
        return None

    def _participant_count(self, tournament: 'Tournament') -> int:
        return len(self._teams_for_tournament(tournament))

    def _board_participant_ids(self, team_board) -> set[int]:
        stb = team_board.stored_team_board
        return {
            team_id for team_id in (stb.team_a_id, stb.team_b_id) if team_id is not None
        }

    def _seed_id(self, tournament: 'Tournament', seed: int) -> int:
        return self._teams_for_tournament(tournament)[seed - 1].id

    def _played_match_winner(
        self, tournament: 'Tournament', match: double_elimination.Match, a_id, b_id
    ) -> int | None:
        team_board = find_knockout_team_board(tournament, match.round, a_id, b_id)
        if team_board is None:
            return None
        return team_match_winner_id(tournament, team_board)

    @override
    def pairings_generation_disabled_message(
        self, tournament: 'Tournament', at_round: int
    ) -> str | None:
        if message := super().pairings_generation_disabled_message(
            tournament, at_round
        ):
            return message
        return self._double_elimination_gate(tournament, at_round)

    @override
    def generate_pairings(
        self,
        tournament: 'Tournament',
        round_: int,
        partial_pairings: bool = False,
    ) -> str:
        if self.pairings_generation_disabled_message(tournament, round_):
            raise ValueError(
                f'Pairings generation not allowed for round {round_} '
                f'of tournament [{tournament.name}].'
            )
        team_pairs = self._round_match_pairs(tournament, round_)
        if not team_pairs:
            return _('Pairing is not possible.')
        team_pairs = self._coloured_team_pairs(tournament, round_, team_pairs)
        self._persist_team_round(tournament, round_, team_pairs)
        return ''


class TeamDoubleEliminationTwoGameEngine(
    _TwoGameDoubleElimMixin, TeamDoubleEliminationEngine
):
    """Team double elimination *aller-retour*: every match is two legs, the
    White orientation forced (leg 1 stronger team board-one White, leg 2
    reversed), decided on the aggregate game points."""

    @override
    def _played_match_winner(
        self, tournament: 'Tournament', match: double_elimination.Match, a_id, b_id
    ) -> int | None:
        leg1 = find_knockout_team_board(
            tournament, self._game_app_round(match.round, 1), a_id, b_id
        )
        leg2 = find_knockout_team_board(
            tournament, self._game_app_round(match.round, 2), a_id, b_id
        )
        if (
            leg1 is None
            or leg2 is None
            or not leg1.all_games_played
            or not leg2.all_games_played
        ):
            return None
        totals = {a_id: 0.0, b_id: 0.0}
        for team_board in (leg1, leg2):
            stb = team_board.stored_team_board
            a_gp, b_gp = team_board.effective_game_points
            if stb.team_a_id in totals:
                totals[stb.team_a_id] += a_gp
            if stb.team_b_id is not None and stb.team_b_id in totals:
                totals[stb.team_b_id] += b_gp
        if totals[a_id] > totals[b_id]:
            return a_id
        if totals[b_id] > totals[a_id]:
            return b_id
        return tournament.knockout.advancement_winner(leg2)

    @override
    def generate_pairings(
        self,
        tournament: 'Tournament',
        round_: int,
        partial_pairings: bool = False,
    ) -> str:
        if self.pairings_generation_disabled_message(tournament, round_):
            raise ValueError(
                f'Pairings generation not allowed for round {round_} '
                f'of tournament [{tournament.name}].'
            )
        game = self._game_of(round_)
        match_pairs = self._round_match_pairs(tournament, self._level_of(round_))
        if not match_pairs:
            return _('Pairing is not possible.')
        team_a_white = self._team_a_is_board_one_white(tournament)
        pairs: list[tuple[int, int | None]] = []
        for a_id, b_id in match_pairs:
            if b_id is None:
                pairs.append((a_id, None))
                continue
            strong, weak = self._stronger_teams(tournament, a_id, b_id)
            white_team, black_team = (strong, weak) if game == 1 else (weak, strong)
            pairs.append(
                (white_team, black_team) if team_a_white else (black_team, white_team)
            )
        self._persist_team_round(tournament, round_, pairs)
        return ''

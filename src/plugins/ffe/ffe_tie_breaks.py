from abc import ABC, abstractmethod
from functools import cache, lru_cache, cached_property
from itertools import groupby
from math import floor
from types import UnionType
from typing import TYPE_CHECKING, Any

from common.exception import OptionError
from common.i18n import _, ngettext
from data.pairing import Pairing
from data.pairings import PairingSystem
from data.pairings.systems import RoundRobinPairingSystem, SwissPairingSystem
from data.player import TournamentPlayer
from data.tie_breaks import TeamTieBreak, TieBreak, TieBreakOption
from data.tie_breaks.categories import TeamScoreCategory, TieBreakCategory
from data.tie_breaks.options import SilentTieBreakOption
from data.tie_breaks.team_records import TeamRecord
from data.tie_breaks.team_tie_breaks import TeamTieBreakContext
from data.tie_breaks.tie_breaks import (
    TournamentPerformanceRatingTieBreak,
    KashdanTieBreak,
    StandardBuchholzTieBreak,
    SumOfBuchholzTieBreak,
)
from plugins.ffe import PLUGIN_NAME
from utils import Utils
from utils.entity import IdentifiableEntity, EntityManager
from utils.enum import Result
from web.utils import SelectOption

if TYPE_CHECKING:
    from data.tournament import Tournament


class BasePapiTieBreak(TieBreak, ABC):
    """Implementation of the tie-breaks as in Papi.
    Computation inaccuracies are reproduced"""

    @staticmethod
    @abstractmethod
    def base_tie_break_type() -> type[TieBreak]:
        """Tie-break of the core matching the re-implementation of Papi."""

    @cached_property
    def base_tie_break(self) -> TieBreak:
        return self.base_tie_break_type()()

    @classmethod
    def static_id(cls) -> str:
        return f'{PLUGIN_NAME}-PAPI_{cls.sub_id()}'

    @staticmethod
    @abstractmethod
    def sub_id() -> str:
        """Id unique amongst the Papi tie-breaks."""

    @classmethod
    def static_name(cls) -> str:
        return f'{cls.base_tie_break_type().static_name()} (PAPI)'

    @property
    def is_fide(self) -> bool:
        return False

    @property
    def trf_sub_acronym(self) -> str:
        """Acronyme used to represent the papi tie-break in the TRF."""
        return self.sub_id()

    @property
    def trf_acronym(self) -> str:
        return 'OTHER_PAPI_' + self.trf_sub_acronym

    @property
    def full_name(self) -> str:
        return f'{self.base_full_name} (PAPI)'

    @property
    def base_help_text(self) -> str:
        return _('The [{tie_break}] tie-break as implemented in Papi.').format(
            tie_break=self.base_full_name
        )

    @property
    def base_full_name(self) -> str:
        """Name of the tie-break to display in the full name and the help text."""
        return self.base_tie_break_type().static_name()

    @property
    def category(self) -> TieBreakCategory:
        return self.base_tie_break.category

    @property
    def forbidden_pairing_systems(self) -> list[PairingSystem]:
        return self.base_tie_break.forbidden_pairing_systems

    def is_compatible_with(self, pairing_system: PairingSystem) -> bool:
        return self.base_tie_break.is_compatible_with(pairing_system)


class PapiPerformanceTieBreak(BasePapiTieBreak):
    @staticmethod
    def sub_id() -> str:
        return 'PERFORMANCE'

    @staticmethod
    def base_tie_break_type() -> type[TieBreak]:
        return TournamentPerformanceRatingTieBreak

    @property
    def base_acronym(self) -> str:
        return 'Perf'

    @property
    def base_help_text(self) -> str:
        return (
            super().base_help_text
            + '<br/>'
            + _('For unrated players, a representative rating is calculated.')
        )

    @staticmethod
    def _points_after(player: TournamentPlayer, after_round: int):
        # NOTE(Amaras): Because EM did not take into account HPB in his code,
        # this function must be used instead of Player.points_after
        return sum(
            pairing.result.points(player.point_values)
            for round_index, pairing in player.pairings.items()
            if round_index <= after_round
            and player.game_counts_for_tie_breaks(pairing)  # FIDE 6.6
            and (
                pairing.played
                or pairing.result in (Result.HALF_POINT_BYE, Result.FULL_POINT_BYE)
            )
        )

    @staticmethod
    @lru_cache(maxsize=32)
    def _performance_bonus(fractional_score: float) -> int | float:
        performance_table = Utils.PERFORMANCE_TABLE[:-1] + [677, 677]
        percent = 100 * fractional_score
        index = floor(abs(50 - percent))
        percent_int = floor(percent)
        bonus = float(performance_table[index])
        smaller_difference = percent - percent_int
        if smaller_difference > 0:
            smaller_difference *= performance_table[index + 1] - bonus
        bonus += smaller_difference
        if fractional_score < 0.5:
            bonus *= -1
        return bonus

    def get_player_variables(
        self, tournament: 'Tournament', after_round: int
    ) -> dict[int, Any]:
        """Add the papi estimation as a variable."""
        if after_round < 1 or not any(
            player.estimated for player in tournament.players
        ):
            return {}

        max_possible_points = tournament.win_points * after_round

        # Only points from played games should be counted
        points_by_player_id = {
            player.id: self._points_after(player, after_round)
            for player in tournament.players
        }
        players = sorted(
            tournament.players,
            key=lambda player: points_by_player_id[player.id],
        )
        players_by_points: dict[float, list[TournamentPlayer]] = {
            points: list(group)
            for points, group in groupby(
                players,
                key=lambda player: points_by_player_id[player.id],
            )
        }

        point_keys: list[float] = [0]
        while (current_points := point_keys[-1]) < max_possible_points:
            current_points += tournament.draw_points
            point_keys.append(current_points)
        level_estimations = {points: 0 for points in point_keys}

        # NOTE(Amaras): if there are rated players in the score group,
        # use the average of their ratings as the level's estimation.
        for points, test_group in players_by_points.items():
            group_ratings = [
                player.rating for player in test_group if not player.estimated
            ]
            if group_ratings:
                average_rating = round(sum(group_ratings) / len(group_ratings))
                level_estimations[points] = average_rating

        # NOTE(Amaras): If there are no players with a rating, use the
        # estimation of the higher level, added with the difference
        # between the score group's performance bonus and the previous
        # group's performance bonus.
        previous_estimation = previous_bonus = 0
        for points in reversed(point_keys):
            estimation = level_estimations[points]
            if estimation > 0:
                # No need to touch a group's estimation if it already has one
                previous_bonus = round(
                    self._performance_bonus(points / max_possible_points)
                )
                previous_estimation = estimation
            elif previous_estimation > 0:
                bonus = round(self._performance_bonus(points / max_possible_points))
                level_estimations[points] = previous_estimation - previous_bonus + bonus
                previous_estimation = level_estimations[points]
                previous_bonus = bonus

        # NOTE(Amaras): There may be additional levels with no estimation
        # (usually the best score groups but might be all but the last),
        # in which case, travel the groups upwards and estimate them
        for points in point_keys:
            estimation = level_estimations[points]
            if estimation > 0:
                previous_bonus = round(
                    self._performance_bonus(points / max_possible_points)
                )
                previous_estimation = estimation
            elif previous_estimation > 0:
                bonus = round(self._performance_bonus(points / max_possible_points))
                level_estimations[points] = previous_estimation - previous_bonus + bonus
                previous_estimation = level_estimations[points]
                previous_bonus = bonus

        # NOTE(Amaras): There may be a single case where all players
        # have no estimation (*estimation == 0*), which is if no
        # player is rated in the tournament.
        # In this case, obviously, no rating-based tie-break
        # should be used.
        # This includes ARO, TPR, PTP, APRO, APPO and their variants
        estimation_by_player_id: dict[int, int] = {}
        for points, test_group in players_by_points.items():
            estimation = level_estimations[points]
            for player in test_group:
                estimation_by_player_id[player.id] = estimation
        return estimation_by_player_id

    def _get_player_estimation(self, player: 'TournamentPlayer') -> int:
        if not player.estimated:
            return player.rating
        return player.tie_break_variables.get(self.id, player.rating)

    def compute_player_value(
        self, player: 'TournamentPlayer', *, after_round: int
    ) -> float:
        tournament: 'Tournament' = player.tournament
        pairings: list[Pairing] = [
            pairing
            for round_index, pairing in player.pairings.items()
            if round_index <= after_round
            and pairing.played
            and player.game_counts_for_tie_breaks(pairing)  # FIDE 6.6
        ]
        ratings = []
        score = 0.0
        player_estimation = self._get_player_estimation(player)
        for pairing in pairings:
            assert pairing.opponent_id is not None
            opponent = tournament.players_by_id[pairing.opponent_id]
            opponent_estimation = self._get_player_estimation(opponent)
            rating = min(
                player_estimation + 400,
                max(player_estimation - 400, opponent_estimation),
            )
            ratings.append(rating)
            score += pairing.result.points(tournament.point_values)
        if not ratings:
            return 0
        max_score = len(ratings) * tournament.win_points
        average = sum(ratings) / len(ratings)
        fractional_score = score / max_score
        bonus = self._performance_bonus(fractional_score)
        return round(average + bonus)


class PapiKashdanTieBreak(BasePapiTieBreak):
    @staticmethod
    def sub_id() -> str:
        return 'KASHDAN'

    @staticmethod
    def base_tie_break_type() -> type[TieBreak]:
        return KashdanTieBreak

    @property
    def base_acronym(self) -> str:
        return 'Ka.'

    def compute_player_value(
        self, player: 'TournamentPlayer', *, after_round: int
    ) -> float:
        """Legacy: unplayed rounds are counted"""

        pairings: list[Pairing] = [
            pairing
            for round_index, pairing in player.pairings.items()
            if round_index <= after_round
            and player.game_counts_for_tie_breaks(pairing)  # FIDE 6.6
        ]
        score_by_result: dict[Result, float] = {
            Result.WIN: 4,
            Result.UNRATED_WIN: 4,
            Result.DRAW: 2,
            Result.UNRATED_DRAW: 2,
            Result.LOSS: 1,
            Result.UNRATED_LOSS: 1,
        }
        return sum(pairing.result.points(score_by_result) for pairing in pairings)


# -----------------------------------------------------------------------------
# Buchholz
# -----------------------------------------------------------------------------


class PapiBuchholzType(IdentifiableEntity, ABC):
    @property
    @abstractmethod
    def full_name(self) -> str:
        """Full name of the tie-break in Papi for this type."""

    @property
    @abstractmethod
    def acronym(self) -> str:
        """Acronym of the tie-break in Papi."""

    @staticmethod
    def get_tooltip(tournament_rounds: int) -> str | None:
        """Tooltip to display on the select."""
        return None

    @property
    @abstractmethod
    def use_bottom_cut(self) -> bool:
        """Defines if the bottom cut should be used."""

    @property
    @abstractmethod
    def use_top_cut(self) -> bool:
        """Defines if the top cut should be used."""


class StandardPapiBuchholzType(PapiBuchholzType):
    @staticmethod
    def static_id() -> str:
        return 'STANDARD'

    @staticmethod
    def static_name() -> str:
        return _('Standard')

    @property
    def full_name(self) -> str:
        return _('Buchholz')

    @property
    def acronym(self) -> str:
        return 'Bu.'

    @property
    def use_bottom_cut(self) -> bool:
        return False

    @property
    def use_top_cut(self) -> bool:
        return False


class CutPapiBuchholzType(PapiBuchholzType):
    @staticmethod
    def static_id() -> str:
        return 'CUT'

    @staticmethod
    def static_name() -> str:
        return _('Cut *** TIE BREAK VARIATION')

    @property
    def full_name(self) -> str:
        return _('Buchholz cut')

    @property
    def acronym(self) -> str:
        return 'Tr.'

    @staticmethod
    def get_tooltip(tournament_rounds: int) -> str | None:
        cut = PapiBuchholzTieBreak.papi_buchholz_cut(tournament_rounds)
        return ngettext(
            'For a tournament with {rounds} rounds, '
            'the least significant value is removed.',
            'For a tournament with {rounds} rounds, '
            'the {count} least significant values are removed.',
            cut,
        ).format(rounds=tournament_rounds, count=cut)

    @property
    def use_bottom_cut(self) -> bool:
        return True

    @property
    def use_top_cut(self) -> bool:
        return False


class MedianPapiBuchholzType(PapiBuchholzType):
    @staticmethod
    def static_id() -> str:
        return 'MEDIAN'

    @staticmethod
    def static_name() -> str:
        return _('Median')

    @property
    def full_name(self) -> str:
        return _('Median Buchholz')

    @staticmethod
    def get_tooltip(tournament_rounds: int) -> str | None:
        cut = PapiBuchholzTieBreak.papi_buchholz_cut(tournament_rounds)
        return ngettext(
            'For a tournament with {rounds} rounds, '
            'the least and the most significant values are removed.',
            'For a tournament with {rounds} rounds, the {count} '
            'least and the {count} most significant values are removed.',
            cut,
        ).format(rounds=tournament_rounds, count=cut)

    @property
    def acronym(self) -> str:
        return 'Me.'

    @property
    def use_bottom_cut(self) -> bool:
        return True

    @property
    def use_top_cut(self) -> bool:
        return True


class PapiBuchholzTypeManager(EntityManager[PapiBuchholzType]):
    def entity_types(self) -> list[type[PapiBuchholzType]]:
        return [
            StandardPapiBuchholzType,
            CutPapiBuchholzType,
            MedianPapiBuchholzType,
        ]


class PapiBuchholzTypeOption(SilentTieBreakOption):
    @staticmethod
    def static_id() -> str:
        return f'{PLUGIN_NAME}-PAPI_BUCHHOLZ_TYPE'

    @property
    def template_name(self) -> str:
        return '/ffe_papi_buchholz_type_option.html'

    @property
    def template_file_stem(self) -> str:
        return ''

    @property
    def type(self) -> type | UnionType:
        return str

    @property
    def default_value(self) -> Any:
        return StandardPapiBuchholzType.static_id()

    def buchholz_type_options(self, tournament_rounds: int) -> dict[str, SelectOption]:
        return {
            buchholz_type.id: SelectOption(
                buchholz_type.name, buchholz_type.get_tooltip(tournament_rounds)
            )
            for buchholz_type in PapiBuchholzTypeManager().objects()
        }

    @cached_property
    def buchholz_type(self) -> PapiBuchholzType:
        return PapiBuchholzTypeManager().get_object(self.value)

    def validate(self):
        super().validate()
        try:
            __ = self.buchholz_type
        except KeyError:
            raise OptionError(f'Unknown Buchholz type: {self.value}', self)


class PapiBuchholzTieBreak(BasePapiTieBreak):
    @staticmethod
    def sub_id() -> str:
        return 'BUCHHOLZ'

    @staticmethod
    def base_tie_break_type() -> type[TieBreak]:
        return StandardBuchholzTieBreak

    @staticmethod
    def available_options() -> list[type[TieBreakOption]]:
        return [PapiBuchholzTypeOption]

    @cached_property
    def type(self) -> PapiBuchholzType:
        return self._get_option(PapiBuchholzTypeOption).buchholz_type

    @property
    def base_acronym(self) -> str:
        return self.type.acronym

    @property
    def trf_sub_acronym(self) -> str:
        return f'{self.sub_id()}_{self.type.id}'

    @property
    def base_full_name(self) -> str:
        return self.type.full_name

    @staticmethod
    def _papi_adjusted_score(
        player: 'TournamentPlayer',
        *,
        after_round: int,
    ) -> float:
        """Legacy: Unplayed rounds are counted as draws"""
        tournament: 'Tournament' = player.tournament
        if after_round is None:
            after_round = max(player.pairings)
        caching = tournament._compute_caching_enabled
        cache_key = ('ffe_papi_adjusted_score', after_round)
        if caching:
            cached = player._compute_cache.get(cache_key)
            if cached is not None:
                return cached
        if tournament.pairing_system == RoundRobinPairingSystem():
            score = player.points_after(after_round)
        else:
            score = 0.0
            for round_index, pairing in player.pairings.items():
                if round_index > after_round:
                    continue
                if pairing.unplayed:
                    score += tournament.draw_points
                    continue
                if pairing.requested_bye:
                    if all(
                        p.voluntary_unplayed
                        for index, p in player.pairings.items()
                        if round_index < index <= after_round
                    ):
                        score += tournament.draw_points
                    else:
                        score += pairing.result.points(tournament.point_values)
                else:
                    score += pairing.result.points(tournament.point_values)
        if caching:
            player._compute_cache[cache_key] = score
        return score

    @staticmethod
    def _papi_dummy_score(
        player: 'TournamentPlayer',
        pairing: Pairing,
        *,
        after_round: int = 1,
        round_index: int = 1,
    ) -> float:
        """Legacy: uses round_index for the computation"""
        dummy = player.points_before(round_index) + Result.DRAW.points(
            player.point_values
        ) * (after_round - round_index)
        match pairing.result:
            case (
                Result.FORFEIT_WIN
                | Result.PAIRING_ALLOCATED_BYE
                | Result.FULL_POINT_BYE
            ):
                return dummy + Result.LOSS.points(player.point_values)
            case Result.HALF_POINT_BYE:
                return dummy + Result.DRAW.points(player.point_values)
            case (
                Result.ZERO_POINT_BYE
                | Result.FORFEIT_LOSS
                | Result.DOUBLE_FORFEIT
                | Result.NO_RESULT
            ):
                return dummy + Result.WIN.points(player.point_values)
            case _:
                raise ValueError(f'{pairing.result=}')

    @staticmethod
    @cache
    def papi_buchholz_cut(tournament_rounds: int) -> int:
        if tournament_rounds <= 7:
            return 1
        elif tournament_rounds <= 12:
            return 2
        return 3

    def compute_player_value(
        self, player: TournamentPlayer, *, after_round: int
    ) -> float:
        tournament: 'Tournament' = player.tournament
        cut = self.papi_buchholz_cut(tournament.rounds)
        cut_top = cut if self.type.use_top_cut else 0
        cut_btm = cut if self.type.use_bottom_cut else 0
        if cut_top + cut_btm >= after_round:
            return 0
        pairings: dict[int, Pairing] = {
            round_index: pairing
            for round_index, pairing in player.pairings.items()
            if round_index <= after_round
        }
        pairing_system = tournament.pairing_system
        if pairing_system == RoundRobinPairingSystem():
            return sum(
                self._papi_adjusted_score(
                    tournament.players_by_id[pairing.opponent_id],
                    after_round=after_round,
                )
                for pairing in pairings.values()
                if pairing.opponent_id is not None
            )
        scores: list[float] = []
        voluntary_unplayed: list[float] = []
        for round_index, pairing in pairings.items():
            should_add_dummy = (
                pairing_system == SwissPairingSystem() and pairing.unplayed
            )
            if should_add_dummy:
                dummy_points = self._papi_dummy_score(
                    player,
                    pairing,
                    after_round=after_round,
                    round_index=round_index,
                )
                scores.append(dummy_points)
                continue
            assert pairing.opponent_id is not None
            opponent: TournamentPlayer = tournament.players_by_id[pairing.opponent_id]
            if pairing_system == SwissPairingSystem():
                opponent_adjusted_score = self._papi_adjusted_score(
                    opponent, after_round=after_round
                )
            else:
                opponent_adjusted_score = opponent.points_after(after_round)
            scores.append(opponent_adjusted_score)
        voluntary_unplayed = sorted(voluntary_unplayed)
        scores = sorted(scores)
        scores = voluntary_unplayed + scores

        if cut_top:
            return sum(scores[cut_btm:-cut_top])
        return sum(scores[cut_btm:])


class PapiSumOfBuchholzTieBreak(BasePapiTieBreak):
    @staticmethod
    def sub_id() -> str:
        return 'BUCHHOLZ_SUM'

    @staticmethod
    def base_tie_break_type() -> type[TieBreak]:
        return SumOfBuchholzTieBreak

    @property
    def base_acronym(self) -> str:
        return 'SBh'

    def compute_player_value(
        self, player: 'TournamentPlayer', *, after_round: int
    ) -> float:
        tournament: 'Tournament' = player.tournament
        opponents: list[TournamentPlayer | None] = [
            tournament.players_by_id.get(pairing.opponent_id)
            for round_index, pairing in player.pairings.items()
            if round_index <= after_round and pairing.opponent_id is not None
        ]
        tie_break = PapiBuchholzTieBreak()
        return sum(
            tie_break.compute_player_value(opponent, after_round=after_round)
            for opponent in opponents
            if opponent is not None
        )


# -----------------------------------------------------------------------------
# Team tie-breaks
# -----------------------------------------------------------------------------


class BerlinTieBreak(TeamTieBreak):
    """FFE *Coefficient d'échiquier* / Berlin (Règlement FFE §11.1).

    Each board carries a coefficient: bottom board = 1, second-to-last
    = 2, ..., top board = ``team_player_count``. A team's Berlin
    score is the sum over every played round of (board score ×
    coefficient). The intent is to weight the top boards: a win on
    board 1 contributes more than a win on the last board.
    """

    @staticmethod
    def static_id() -> str:
        return f'{PLUGIN_NAME}-BERLIN'

    @staticmethod
    def static_name() -> str:
        return _('Berlin')

    @staticmethod
    def available_options() -> list[type[TieBreakOption]]:
        return []

    @property
    def base_acronym(self) -> str:
        return 'Be'

    @property
    def trf_acronym(self) -> str:
        return 'OTHER_FFE_BERLIN'

    @property
    def is_fide(self) -> bool:
        return False

    @property
    def base_help_text(self) -> str:
        return _(
            "Each board's score is multiplied by a coefficient — the "
            'top board by N, the next by N-1, and so on down to the '
            'bottom board by 1 — then summed across all rounds. '
            'Rewards results on the higher boards (FFE rules §11.1).'
        )

    @property
    def category(self) -> TieBreakCategory:
        return TeamScoreCategory()

    def compute_team_value(
        self,
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> float:
        boards = tournament_context.team_player_count
        total = 0.0
        for match in team_record.matches:
            if match.round_ > after_round:
                continue
            for board_index, score in enumerate(match.board_scores):
                if board_index >= boards:
                    break
                coefficient = boards - board_index
                total += score * coefficient
        return total


class GamePointsDifferentialTieBreak(TeamTieBreak):
    """FFE *Différentiel des points de parties* (Règlement Coupe
    Loubatière §4.4.a) — sum over all rounds of (points_for −
    points_against).

    Per match each side's raw board-score total is first clamped to a
    floor of 0 (a forfeit can drive a raw total negative); the clamped
    own total is the match's *points for* and the clamped opponent
    total its *points against*. ``gains``/``pertes`` in the regulation
    are these two sides of the adjusted match score — not counts of
    won/lost games.

    For PLAYED matches the opponent total comes from the paired team's
    record in the same round. For byes (PAB / HPB / +F / -F / ZPB)
    there is no opponent, so points_against is 0 and the differential
    is the team's own (clamped) score."""

    @staticmethod
    def static_id() -> str:
        return f'{PLUGIN_NAME}-GP-DIFFERENTIAL'

    @staticmethod
    def static_name() -> str:
        return _('Game points differential')

    @staticmethod
    def available_options() -> list[type[TieBreakOption]]:
        return []

    @property
    def base_acronym(self) -> str:
        return 'd'

    @property
    def trf_acronym(self) -> str:
        return 'OTHER_FFE_GP_DIFF'

    @property
    def is_fide(self) -> bool:
        return False

    @property
    def base_help_text(self) -> str:
        return _(
            'Sum over every round of (points for − points against), '
            'where each match score is floored at 0 before the '
            'subtraction. Byes count the awarded score against nothing.'
        )

    @property
    def category(self) -> TieBreakCategory:
        return TeamScoreCategory()

    def compute_team_value(
        self,
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> float:
        total = 0.0
        for match in team_record.matches:
            if match.round_ > after_round:
                continue
            opponent_gp = 0.0
            if match.played and match.opponent_id is not None:
                opponent = all_records.get(match.opponent_id)
                if opponent is not None:
                    opp_match = opponent.match_at(match.round_)
                    if opp_match is not None:
                        opponent_gp = opp_match.own_gp
            # Clamp each side's raw match total to 0 (a forfeit can
            # push it negative), then take points_for − points_against.
            total += max(0.0, match.own_gp) - max(0.0, opponent_gp)
        return total


class GamePointsForTieBreak(TeamTieBreak):
    """FFE *Points de parties « pour »* (Règlement Coupe Loubatière
    §4.4.a) — sum over all rounds of the team's *points for*: each
    match's own raw board-score total floored at 0 (the same clamped
    value used by the differential). Distinct from the plain
    game-points total, which doesn't clamp negative match scores."""

    @staticmethod
    def static_id() -> str:
        return f'{PLUGIN_NAME}-GP-FOR'

    @staticmethod
    def static_name() -> str:
        return _('Game points "for"')

    @staticmethod
    def available_options() -> list[type[TieBreakOption]]:
        return []

    @property
    def base_acronym(self) -> str:
        return 'p'

    @property
    def trf_acronym(self) -> str:
        return 'OTHER_FFE_GP_FOR'

    @property
    def is_fide(self) -> bool:
        return False

    @property
    def base_help_text(self) -> str:
        return _(
            "Sum over every round of the team's points for — each "
            'match score floored at 0. FFE Loubatière Cup rules §4.4.a.'
        )

    @property
    def category(self) -> TieBreakCategory:
        return TeamScoreCategory()

    def compute_team_value(
        self,
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> float:
        return sum(
            max(0.0, match.own_gp)
            for match in team_record.matches
            if match.round_ <= after_round
        )


class BoardDifferentialTieBreak(TeamTieBreak):
    """FFE *Somme des différentiels par échiquier* (Championnat de France
    Féminin des Clubs, règlement F01 §4.4.a).

    The last step of the official departage: once match points, the
    overall differential and the points "pour" have all left teams
    level, the tied teams are compared on the sum of their board-1
    differentials, then — for those still level — on board 2, and so on
    down the boards.

    A board's differential for one match is the team's own score on that
    board minus the opponent's on the same board, so it is unaffected by
    the match-level flooring :class:`GamePointsDifferentialTieBreak`
    applies. A round with no opponent (bye, exemption) has nothing to
    subtract; such rounds award match-level points rather than board
    scores, so in practice they contribute nothing.

    This compares tied teams against one another rather than producing a
    scalar, so the value is a within-group rank delta (0 = worst of the
    group, larger = better), as for Extended Direct Encounter.
    """

    @staticmethod
    def static_id() -> str:
        return f'{PLUGIN_NAME}-BOARD-DIFFERENTIAL'

    @staticmethod
    def static_name() -> str:
        return _('Board differentials')

    @staticmethod
    def available_options() -> list[type[TieBreakOption]]:
        return []

    @property
    def base_acronym(self) -> str:
        return 'dEch'

    @property
    def trf_acronym(self) -> str:
        return 'OTHER_FFE_BOARD_DIFF'

    @property
    def is_fide(self) -> bool:
        return False

    @property
    def base_help_text(self) -> str:
        return _(
            'Compares the tied teams on the sum of their differentials on '
            'board 1; those still level are then compared on board 2, and '
            'so on down the boards (FFE rules §4.4.a).'
        )

    @property
    def category(self) -> TieBreakCategory:
        return TeamScoreCategory()

    @property
    def is_computed_per_team(self) -> bool:
        return False

    @property
    def display_rank_delta(self) -> bool:
        return True

    def compute_team_value(
        self,
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> float:
        return 0.0

    def compute_all_team_values(
        self,
        tied_groups: list[list[TeamRecord]],
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> dict[int, float]:
        values: dict[int, float] = {}
        for group in tied_groups:
            differentials = {
                record.team_id: self._board_differentials(
                    record, all_records, tournament_context, after_round
                )
                for record in group
            }
            # Ascending, so the worst of the group lands on 0; teams whose
            # board differentials match all the way down stay level.
            ordered = sorted(group, key=lambda record: differentials[record.team_id])
            rank = 0
            previous: tuple[float, ...] | None = None
            for index, record in enumerate(ordered):
                current = differentials[record.team_id]
                if previous is not None and current != previous:
                    rank = index
                values[record.team_id] = float(rank)
                previous = current
        return values

    @staticmethod
    def _board_differentials(
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        after_round: int,
    ) -> tuple[float, ...]:
        """Sum of (own board score − opponent board score) for each
        board, board 1 first — the tuple the tied teams are compared on."""
        boards = tournament_context.team_player_count
        totals = [0.0] * boards
        for match in team_record.matches:
            if match.round_ > after_round:
                continue
            opponent_scores: tuple[float, ...] = ()
            if match.played and match.opponent_id is not None:
                opponent = all_records.get(match.opponent_id)
                if opponent is not None:
                    opponent_match = opponent.match_at(match.round_)
                    if opponent_match is not None:
                        opponent_scores = opponent_match.board_scores
            for board_index in range(boards):
                own = (
                    match.board_scores[board_index]
                    if board_index < len(match.board_scores)
                    else 0.0
                )
                against = (
                    opponent_scores[board_index]
                    if board_index < len(opponent_scores)
                    else 0.0
                )
                totals[board_index] += own - against
        return tuple(totals)


class LowestOwnAverageRatingTieBreak(TeamTieBreak):
    """FFE *Moyenne des derniers Elo diffusés (au prorata des
    participations), la plus basse* (Règlement Coupe Loubatière /
    Parité §4.4) — the team with the lowest weighted-average own-Elo
    wins the tie-break.

    The average is over every (player, round) pair where the player
    was fielded on a board (= weighting by participations). Per-round
    ratings come from :attr:`TeamMatchRecord.board_ratings`, set in
    parallel to ``board_scores``. The tie-break returns the negation
    of the average so the standings sort (always descending) picks the
    *lowest* team first.
    """

    @staticmethod
    def static_id() -> str:
        return f'{PLUGIN_NAME}-OWN-AVG-ELO'

    @staticmethod
    def static_name() -> str:
        return _('Lowest own average rating')

    @staticmethod
    def available_options() -> list[type[TieBreakOption]]:
        return []

    @property
    def base_acronym(self) -> str:
        return 'Elo'

    @property
    def trf_acronym(self) -> str:
        return 'OTHER_FFE_OWN_ELO'

    @property
    def is_fide(self) -> bool:
        return False

    @property
    def base_help_text(self) -> str:
        return _(
            "The team's own players' average rating, weighted by "
            'their per-round board appearances. The team with the '
            'lowest average wins the tie-break (lower is better).'
        )

    @property
    def display_absolute_value(self) -> bool:
        # The compute returns -avg so the descending sort works; the
        # ranking screen should display the actual rating, not the
        # negated value.
        return True

    @property
    def display_decimals(self) -> int | None:
        # An average rating — show 2 decimals, not the ½/¼/¾ points glyphs.
        return 2

    @property
    def category(self) -> TieBreakCategory:
        return TeamScoreCategory()

    def compute_team_value(
        self,
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> float:
        total = 0
        count = 0
        for match in team_record.matches:
            if match.round_ > after_round:
                continue
            for rating in match.board_ratings:
                if rating is None:
                    continue
                total += rating
                count += 1
        if not count:
            return 0.0
        return -total / count

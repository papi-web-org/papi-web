from dataclasses import dataclass
from enum import StrEnum, IntEnum
from typing import Self

from data.pairing import Pairing
from data.pairings import PairingVariation, variations
from data.pairings.scheveningen import ScheveningenPairingSystem
from data.pairings.systems import (
    RoundRobinPairingSystem,
    SwissPairingSystem,
    PairingSystem,
)
from data.player_categories import PlayerCategory, JuniorCategory, SeniorCategory
from data.tie_breaks import tie_breaks, TieBreak
from data.tournament import Tournament
from plugins.ffe import ffe_tie_breaks
from plugins.ffe.ffe_tie_breaks import (
    PapiBuchholzTypeOption,
    StandardPapiBuchholzType,
    CutPapiBuchholzType,
    MedianPapiBuchholzType,
)
from plugins.ffe.utils import PlayerFFELicence
from data.pairings import acceleration as accelerations
from utils import CoreMapper
from utils.enum import (
    TournamentRating,
    PlayerGender,
    PlayerTitle,
    PlayerRatingType,
    Result,
    BoardColor,
)


class PapiPairingVariation(CoreMapper[str, PairingVariation]):
    """Mapper of the pairing variations in the Papi database."""

    @classmethod
    def _core_object_by_outer_value(cls) -> dict[str, PairingVariation]:
        from plugins.ffe.ffe_entity import NicoisSwissVariation

        return {
            'Standard': variations.StandardSwissVariation(),
            'Haley': accelerations.HaleySwissVariation(),
            'HaleySoft': accelerations.HaleySoftSwissVariation(),
            'SAD': accelerations.ProgressiveSwissVariation(),
            'Nicois': NicoisSwissVariation(),
            'Berger': variations.BergerRoundRobinVariation(),
        }

    @classmethod
    def get_outer_value(cls, core_object: PairingVariation) -> str | None:
        if papi_key := super().get_outer_value(core_object):
            return papi_key
        pairing_system = core_object.system()
        # A Scheveningen is exported as an individual Swiss.
        if pairing_system == SwissPairingSystem() or isinstance(
            pairing_system, ScheveningenPairingSystem
        ):
            core_object = variations.StandardSwissVariation()
        elif pairing_system == RoundRobinPairingSystem():
            core_object = variations.BergerRoundRobinVariation()
        return super().get_outer_value(core_object)


class PapiPairingSystem(CoreMapper[str, PairingSystem]):
    @staticmethod
    def _core_object_by_outer_value() -> dict[str, PairingSystem]:
        return {
            'Suisse': SwissPairingSystem(),
            'ToutesRondes': RoundRobinPairingSystem(),
        }

    @classmethod
    def get_outer_value(cls, core_object: PairingSystem) -> str | None:
        # A Scheveningen has no Papi type of its own; it is exported as an
        # individual Swiss.
        if isinstance(core_object, ScheveningenPairingSystem):
            return 'Suisse'
        return super().get_outer_value(core_object)


class PapiTieBreak(CoreMapper[str, TieBreak]):
    @classmethod
    def _core_object_by_outer_value(cls) -> dict[str, TieBreak]:
        return {
            'Solkoff': ffe_tie_breaks.PapiBuchholzTieBreak(
                [PapiBuchholzTypeOption(StandardPapiBuchholzType().id)]
            ),
            'Brésilien': ffe_tie_breaks.PapiBuchholzTieBreak(
                [PapiBuchholzTypeOption(CutPapiBuchholzType().id)]
            ),
            'Harkness': ffe_tie_breaks.PapiBuchholzTieBreak(
                [PapiBuchholzTypeOption(MedianPapiBuchholzType().id)]
            ),
            'Cumulatif': tie_breaks.ProgressiveScoresTieBreak(),
            'Performance': ffe_tie_breaks.PapiPerformanceTieBreak(),
            'SommeDesBuchholz': ffe_tie_breaks.PapiSumOfBuchholzTieBreak(),
            'Kashdan': ffe_tie_breaks.PapiKashdanTieBreak(),
            'Nombre de Victoires': tie_breaks.WinsTieBreak(),
            'Sonnenborn-Berger': tie_breaks.SonnebornBergerTieBreak(),
            'Koya': tie_breaks.KoyaTieBreak(),
            'Manuel': tie_breaks.ManualTieBreak(),
        }

    @classmethod
    def get_outer_value(
        cls,
        core_object: TieBreak,
        three_points_for_a_win: bool = False,
    ) -> str | None:
        if (
            core_object.id == tie_breaks.SonnebornBergerTieBreak().id
            and three_points_for_a_win
        ):
            # Three points for a win is not taken into account for Sonneborn Berger
            # in Papi, so in those cases it needs to be overridden with the SC ranking
            return None
        return super().get_outer_value(core_object)


class PapiTournamentRating(CoreMapper[str, TournamentRating]):
    @staticmethod
    def _core_object_by_outer_value() -> dict[str, TournamentRating]:
        return {
            'Elo': TournamentRating.STANDARD,
            'Rapide': TournamentRating.RAPID,
            'Blitz': TournamentRating.BLITZ,
        }


class PapiPlayerGender(CoreMapper[str, PlayerGender]):
    @classmethod
    def _core_object_by_outer_value(cls) -> dict[str, PlayerGender]:
        return {
            '': PlayerGender.NONE,
            'M': PlayerGender.MAN,
            'F': PlayerGender.WOMAN,
        }

    @classmethod
    def get_core_object(cls, plugin_value: str) -> PlayerGender:
        return cls._core_object_by_outer_value()[plugin_value.upper()]


class PapiThreePointsForAWin(CoreMapper[str, bool]):
    @classmethod
    def _core_object_by_outer_value(cls) -> dict[str, bool]:
        return {
            'OUI': True,
            'NON': False,
        }

    @classmethod
    def get_core_object(cls, plugin_value: str) -> bool:
        return cls._core_object_by_outer_value()[plugin_value.upper()]


class PapiPlayerTitle(CoreMapper[str, PlayerTitle]):
    @classmethod
    def _core_object_by_outer_value(cls) -> dict[str, PlayerTitle]:
        return {
            '': PlayerTitle.NONE,
            'c': PlayerTitle.NONE,
            'cf': PlayerTitle.NONE,
            'ff': PlayerTitle.WOMAN_FIDE_MASTER,
            'f': PlayerTitle.FIDE_MASTER,
            'mf': PlayerTitle.WOMAN_INTERNATIONAL_MASTER,
            'm': PlayerTitle.INTERNATIONAL_MASTER,
            'gf': PlayerTitle.WOMAN_GRANDMASTER,
            'g': PlayerTitle.GRANDMASTER,
        }

    @classmethod
    def get_core_object(cls, plugin_value: str) -> PlayerTitle:
        return cls._core_object_by_outer_value()[plugin_value.strip()]


class PapiPlayerCategory(CoreMapper[str, PlayerCategory]):
    @staticmethod
    def _core_object_by_outer_value() -> dict[str, PlayerCategory]:
        return {
            'Ppo': JuniorCategory(8),
            'Pou': JuniorCategory(10),
            'Pup': JuniorCategory(12),
            'Ben': JuniorCategory(14),
            'Min': JuniorCategory(16),
            'Cad': JuniorCategory(18),
            'Jun': JuniorCategory(20),
            'Sen': SeniorCategory(20),
            'Sep': SeniorCategory(50),
            'Vet': SeniorCategory(65),
        }


class PapiPlayerRatingType(CoreMapper[str | None, PlayerRatingType]):
    @staticmethod
    def _core_object_by_outer_value() -> dict[str | None, PlayerRatingType]:
        return {
            'E': PlayerRatingType.ESTIMATED,
            'N': PlayerRatingType.NATIONAL,
            'F': PlayerRatingType.FIDE,
            'A': PlayerRatingType.ESTIMATED,
            'R': PlayerRatingType.ESTIMATED,
        }

    @classmethod
    def get_core_object(cls, plugin_value: str | None) -> PlayerRatingType:
        if plugin_value is None:
            return PlayerRatingType.ESTIMATED
        return super().get_core_object(plugin_value)


class PapiPlayerFFELicence(CoreMapper[str, PlayerFFELicence]):
    @staticmethod
    def _core_object_by_outer_value() -> dict[str, PlayerFFELicence]:
        return {
            'N': PlayerFFELicence.N,
            'A': PlayerFFELicence.A,
            'B': PlayerFFELicence.B,
        }

    @classmethod
    def get_outer_value(
        cls, core_object: PlayerFFELicence, licence_number: str | None = None
    ) -> str | None:
        if not licence_number or core_object == PlayerFFELicence.NONE:
            return 'N'
        return super().get_outer_value(core_object)

    @classmethod
    def get_core_object(
        cls, outer_value: str, licence_number: str | None = None
    ) -> PlayerFFELicence:
        if not licence_number or not outer_value:
            return PlayerFFELicence.NONE
        return super().get_core_object(outer_value)


class PapiColor(StrEnum):
    WHITE = 'B'
    BLACK = 'N'
    UNPAIRED = 'R'
    BYE = 'F'


class PapiResult(IntEnum):
    UNPLAYED_OR_NOT_PAIRED = 0
    LOSS = 1
    DRAW_OR_HPB = 2  # HPB = Half-Point Bye
    WIN = 3
    FORFEIT_LOSS = 4
    DOUBLE_FORFEIT = 5
    PAB_OR_FORFEIT_WIN_OR_FPB = 6  # PAB = Pairing-Allocated-Bye, FPB = Full-Point Bye


@dataclass
class PapiRound:
    color: PapiColor
    opponent: int | None = None
    result: PapiResult = PapiResult.UNPLAYED_OR_NOT_PAIRED

    def to_result(self, is_round_robin: bool = False) -> Result:
        match self.result:
            case PapiResult.UNPLAYED_OR_NOT_PAIRED:
                if self.color == PapiColor.BYE:
                    return Result.ZERO_POINT_BYE
                if is_round_robin and self.opponent is None:
                    return Result.REST_GAME
                return Result.NO_RESULT
            case PapiResult.LOSS:
                return Result.LOSS
            case PapiResult.DRAW_OR_HPB:
                if self.color == PapiColor.BYE:
                    return Result.HALF_POINT_BYE
                return Result.DRAW
            case PapiResult.WIN:
                return Result.WIN
            case PapiResult.FORFEIT_LOSS:
                return Result.FORFEIT_LOSS
            case PapiResult.DOUBLE_FORFEIT:
                return Result.DOUBLE_FORFEIT
            case PapiResult.PAB_OR_FORFEIT_WIN_OR_FPB:
                if self.color == PapiColor.BYE:
                    return Result.FULL_POINT_BYE
                if self.opponent is not None:
                    return Result.FORFEIT_WIN
                return Result.PAIRING_ALLOCATED_BYE
            case _:
                raise ValueError(f'Unknown value: {self.result}')

    @classmethod
    def from_pairing(cls, pairing: Pairing, pab_value: Result) -> Self:
        papi_color: PapiColor | None
        if pairing.result == Result.NO_RESULT and not pairing.board:
            papi_color = PapiColor.UNPAIRED
        elif (
            # Since Papi does not support custom PAB values, we convert these case to a Bye
            pairing.result == Result.PAIRING_ALLOCATED_BYE and pab_value != Result.WIN
        ) or pairing.result == Result.REST_GAME:
            papi_color = PapiColor.BYE
        elif pairing.color == BoardColor.WHITE:
            papi_color = PapiColor.WHITE
        elif pairing.color == BoardColor.BLACK:
            papi_color = PapiColor.BLACK
        else:
            papi_color = PapiColor.BYE
        return cls(
            papi_color,
            pairing.opponent_id,
            cls._result_to_papi_result(pairing.result, pab_value),
        )

    @classmethod
    def zero_point_bye(cls) -> Self:
        """A zero-point bye: the entrant sits the round out with no opponent
        and scores nothing. A knock-out gives one to a player in the rounds
        after they are eliminated, so Papi reads every entrant as paired or
        given a bye in each round it has played, without altering the score."""
        return cls(PapiColor.BYE, None, PapiResult.UNPLAYED_OR_NOT_PAIRED)

    @staticmethod
    def _result_to_papi_result(result: Result, pab_value: Result):
        match result:
            case Result.WIN:
                return PapiResult.WIN
            case Result.LOSS:
                return PapiResult.LOSS
            case Result.DRAW | Result.HALF_POINT_BYE:
                return PapiResult.DRAW_OR_HPB
            case Result.NO_RESULT | Result.ZERO_POINT_BYE | Result.REST_GAME:
                return PapiResult.UNPLAYED_OR_NOT_PAIRED
            case Result.FORFEIT_LOSS:
                return PapiResult.FORFEIT_LOSS
            case Result.FORFEIT_WIN | Result.FULL_POINT_BYE:
                return PapiResult.PAB_OR_FORFEIT_WIN_OR_FPB
            case Result.PAIRING_ALLOCATED_BYE:
                match pab_value:
                    case Result.WIN:
                        return PapiResult.PAB_OR_FORFEIT_WIN_OR_FPB
                    case Result.LOSS:
                        return PapiResult.UNPLAYED_OR_NOT_PAIRED
                    case Result.DRAW:
                        return PapiResult.DRAW_OR_HPB
                    case _:
                        raise ValueError(f'Unexpected PAB value: {pab_value}')
            case Result.DOUBLE_FORFEIT:
                return PapiResult.DOUBLE_FORFEIT
            case _:
                raise ValueError(f'Unknown value: {result}')

    @staticmethod
    def is_convertible_to_papi(result: Result, tournament: Tournament) -> bool:
        try:
            PapiRound._result_to_papi_result(result, tournament.pab_equivalent_result)
            return True
        except ValueError:
            return False

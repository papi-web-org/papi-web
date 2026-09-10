from typing import TYPE_CHECKING, Protocol, cast, override

from common.i18n import _
from data.pairings import double_elimination
from data.pairings.knockout_helpers import bracket as knockout_bracket
from data.pairings.engines import PairingEngine
from data.pairings.knockout_helpers.colour import KnockoutColourRuleSetting
from data.pairings.knockout_helpers.double import DoubleEliminationResetSetting
from data.pairings.knockout_helpers.engines import (
    DoubleEliminationEngine,
    DoubleEliminationTwoGameEngine,
    KnockoutEngine,
    KnockoutTwoGameEngine,
    TeamDoubleEliminationEngine,
    TeamDoubleEliminationTwoGameEngine,
    TeamKnockoutEngine,
    TeamKnockoutTwoGameEngine,
)
from data.pairings.knockout_helpers.grouping import KnockoutGroupingSetting
from data.pairings.knockout_helpers.settings import KnockoutThirdPlaceSetting
from data.pairings.knockout_helpers.systems import (
    KnockoutPairingSystem,
    TeamKnockoutPairingSystem,
)
from data.pairings.settings import PairingSetting
from data.pairings.systems import PairingSystem
from data.pairings.variations import PairingVariation
from utils.entity import EventBoundEntityManager

if TYPE_CHECKING:
    from data.tournament import Tournament


class _KnockoutVariationHost(Protocol):
    @staticmethod
    def system() -> PairingSystem: ...


class _KnockoutVariationMixin:
    """The round count of a knock-out follows from the size of the field,
    so the arbiter does not set it."""

    def _variation_host(self) -> _KnockoutVariationHost:
        return cast(_KnockoutVariationHost, self)

    @property
    def sets_its_own_round_count(self) -> bool:
        return True

    @property
    def trf_encoded_type(self) -> str:
        # No FIDE TRF26 code describes a knock-out; the custom code just marks
        # it, distinguishing individual from team.
        return (
            'CUSTOM_TEAM_KNOCKOUT'
            if self._variation_host().system().paired_by_team
            else 'CUSTOM_KNOCKOUT'
        )


class KnockoutVariation(_KnockoutVariationMixin, PairingVariation):
    @staticmethod
    def variation_id() -> str:
        # Kept as STANDARD (not SINGLE_ELIMINATION) so the stored id
        # ``KNOCKOUT_STANDARD`` on existing tournaments still resolves;
        # future variations (third-place, double elimination) sit beside it.
        return 'STANDARD'

    @staticmethod
    def static_name() -> str:
        return _('Single elimination')

    @staticmethod
    def system() -> PairingSystem:
        return KnockoutPairingSystem()

    @property
    def settings(self) -> list[PairingSetting]:
        return [
            KnockoutThirdPlaceSetting(),
            KnockoutColourRuleSetting(),
            KnockoutGroupingSetting(),
        ]

    @property
    def engine(self) -> PairingEngine:
        return KnockoutEngine()

    @override
    def automatic_round_count(self, tournament: 'Tournament') -> int | None:
        if tournament.player_count < 2:
            return None
        # A grouped bracket spans log2(K*M) rounds (larger than the field).
        grouped = KnockoutEngine()._grouped_round_count(tournament)
        if grouped:
            return grouped
        return knockout_bracket.round_count(tournament.player_count)


class DoubleEliminationVariation(_KnockoutVariationMixin, PairingVariation):
    @staticmethod
    def variation_id() -> str:
        return 'DOUBLE_ELIMINATION'

    @staticmethod
    def static_name() -> str:
        return _('Double elimination')

    @staticmethod
    def system() -> PairingSystem:
        return KnockoutPairingSystem()

    @property
    def settings(self) -> list[PairingSetting]:
        return [
            DoubleEliminationResetSetting(),
            KnockoutColourRuleSetting(),
            KnockoutGroupingSetting(),
        ]

    @property
    def engine(self) -> PairingEngine:
        return DoubleEliminationEngine()

    @override
    def automatic_round_count(self, tournament: 'Tournament') -> int | None:
        if tournament.player_count < 2:
            return None
        # The reset round is reserved up front when the option is on (so its
        # date/time can be set in the tournament settings), even though it is
        # only played when a reset is actually due — see
        # ``PairingSystem.tournament_is_over``. When seeding by group the
        # bracket spans the padded K*M seeds, not the raw field.
        return double_elimination.round_count(
            DoubleEliminationEngine()._bracket_participant_count(tournament),
            with_reset=DoubleEliminationResetSetting.get_value(tournament),
        )


class KnockoutTwoGameVariation(_KnockoutVariationMixin, PairingVariation):
    @staticmethod
    def variation_id() -> str:
        return 'STANDARD_TWO_GAME'

    @staticmethod
    def static_name() -> str:
        return _('Single elimination — two-game matches')

    @staticmethod
    def system() -> PairingSystem:
        return KnockoutPairingSystem()

    @property
    def settings(self) -> list[PairingSetting]:
        # No colour-assignment setting: colours are forced (game 1 stronger
        # seed White, game 2 reversed).
        return [KnockoutThirdPlaceSetting(), KnockoutGroupingSetting()]

    @property
    def engine(self) -> PairingEngine:
        return KnockoutTwoGameEngine()

    @override
    def automatic_round_count(self, tournament: 'Tournament') -> int | None:
        if tournament.player_count < 2:
            return None
        grouped = KnockoutTwoGameEngine()._grouped_round_count(tournament)
        levels = grouped or knockout_bracket.round_count(tournament.player_count)
        return levels * KnockoutTwoGameEngine.GAMES_PER_MATCH


class DoubleEliminationTwoGameVariation(_KnockoutVariationMixin, PairingVariation):
    @staticmethod
    def variation_id() -> str:
        return 'DOUBLE_ELIMINATION_TWO_GAME'

    @staticmethod
    def static_name() -> str:
        return _('Double elimination — two-game matches')

    @staticmethod
    def system() -> PairingSystem:
        return KnockoutPairingSystem()

    @property
    def settings(self) -> list[PairingSetting]:
        return [DoubleEliminationResetSetting(), KnockoutGroupingSetting()]

    @property
    def engine(self) -> PairingEngine:
        return DoubleEliminationTwoGameEngine()

    @override
    def automatic_round_count(self, tournament: 'Tournament') -> int | None:
        if tournament.player_count < 2:
            return None
        de_rounds = double_elimination.round_count(
            DoubleEliminationTwoGameEngine()._bracket_participant_count(tournament),
            with_reset=DoubleEliminationResetSetting.get_value(tournament),
        )
        return de_rounds * DoubleEliminationTwoGameEngine.GAMES_PER_MATCH


class TeamKnockoutVariation(_KnockoutVariationMixin, PairingVariation):
    @staticmethod
    def variation_id() -> str:
        return 'STANDARD'

    @staticmethod
    def static_name() -> str:
        return _('Single elimination')

    @staticmethod
    def system() -> PairingSystem:
        return TeamKnockoutPairingSystem()

    @property
    def settings(self) -> list[PairingSetting]:
        return [
            KnockoutThirdPlaceSetting(),
            KnockoutColourRuleSetting(),
            KnockoutGroupingSetting(),
        ]

    @property
    def engine(self) -> PairingEngine:
        return TeamKnockoutEngine()

    @override
    def automatic_round_count(self, tournament: 'Tournament') -> int | None:
        if tournament.team_count < 2:
            return None
        grouped = TeamKnockoutEngine()._grouped_round_count(tournament)
        if grouped:
            return grouped
        return knockout_bracket.round_count(tournament.team_count)


class TeamKnockoutTwoGameVariation(_KnockoutVariationMixin, PairingVariation):
    @staticmethod
    def variation_id() -> str:
        return 'STANDARD_TWO_GAME'

    @staticmethod
    def static_name() -> str:
        return _('Single elimination — two-game matches')

    @staticmethod
    def system() -> PairingSystem:
        return TeamKnockoutPairingSystem()

    @property
    def settings(self) -> list[PairingSetting]:
        return [KnockoutThirdPlaceSetting(), KnockoutGroupingSetting()]

    @property
    def engine(self) -> PairingEngine:
        return TeamKnockoutTwoGameEngine()

    @override
    def automatic_round_count(self, tournament: 'Tournament') -> int | None:
        if tournament.team_count < 2:
            return None
        grouped = TeamKnockoutTwoGameEngine()._grouped_round_count(tournament)
        levels = grouped or knockout_bracket.round_count(tournament.team_count)
        return levels * TeamKnockoutTwoGameEngine.GAMES_PER_MATCH


class TeamDoubleEliminationVariation(_KnockoutVariationMixin, PairingVariation):
    @staticmethod
    def variation_id() -> str:
        return 'DOUBLE_ELIMINATION'

    @staticmethod
    def static_name() -> str:
        return _('Double elimination')

    @staticmethod
    def system() -> PairingSystem:
        return TeamKnockoutPairingSystem()

    @property
    def settings(self) -> list[PairingSetting]:
        return [
            DoubleEliminationResetSetting(),
            KnockoutColourRuleSetting(),
            KnockoutGroupingSetting(),
        ]

    @property
    def engine(self) -> PairingEngine:
        return TeamDoubleEliminationEngine()

    @override
    def automatic_round_count(self, tournament: 'Tournament') -> int | None:
        if tournament.team_count < 2:
            return None
        # The reset round is reserved up front (see
        # DoubleEliminationVariation.automatic_round_count); grouping seeds the
        # padded K*M bracket.
        return double_elimination.round_count(
            TeamDoubleEliminationEngine()._bracket_participant_count(tournament),
            with_reset=DoubleEliminationResetSetting.get_value(tournament),
        )


class TeamDoubleEliminationTwoGameVariation(_KnockoutVariationMixin, PairingVariation):
    @staticmethod
    def variation_id() -> str:
        return 'DOUBLE_ELIMINATION_TWO_GAME'

    @staticmethod
    def static_name() -> str:
        return _('Double elimination — two-game matches')

    @staticmethod
    def system() -> PairingSystem:
        return TeamKnockoutPairingSystem()

    @property
    def settings(self) -> list[PairingSetting]:
        return [DoubleEliminationResetSetting(), KnockoutGroupingSetting()]

    @property
    def engine(self) -> PairingEngine:
        return TeamDoubleEliminationTwoGameEngine()

    @override
    def automatic_round_count(self, tournament: 'Tournament') -> int | None:
        if tournament.team_count < 2:
            return None
        de_rounds = double_elimination.round_count(
            TeamDoubleEliminationTwoGameEngine()._bracket_participant_count(tournament),
            with_reset=DoubleEliminationResetSetting.get_value(tournament),
        )
        return de_rounds * TeamDoubleEliminationTwoGameEngine.GAMES_PER_MATCH


class KnockoutVariationManager(EventBoundEntityManager[KnockoutVariation]):
    @override
    def entity_types(self) -> list[type[KnockoutVariation]]:
        # DoubleEliminationVariation is a sibling variation (same manager,
        # common PairingVariation base), not a KnockoutVariation subclass.
        return [
            KnockoutVariation,
            KnockoutTwoGameVariation,  # type: ignore[list-item]
            DoubleEliminationVariation,  # type: ignore[list-item]
            DoubleEliminationTwoGameVariation,  # type: ignore[list-item]
        ]


class TeamKnockoutVariationManager(EventBoundEntityManager[TeamKnockoutVariation]):
    @override
    def entity_types(self) -> list[type[TeamKnockoutVariation]]:
        # TeamDoubleEliminationVariation is a sibling variation (see
        # KnockoutVariationManager.entity_types).
        return [
            TeamKnockoutVariation,
            TeamKnockoutTwoGameVariation,  # type: ignore[list-item]
            TeamDoubleEliminationVariation,  # type: ignore[list-item]
            TeamDoubleEliminationTwoGameVariation,  # type: ignore[list-item]
        ]

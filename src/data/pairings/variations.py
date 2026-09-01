from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import TYPE_CHECKING, override

from common.i18n import _
from data.pairings import systems
from data.pairings.engines import (
    PairingEngine,
    RoundRobinPairingEngine,
    TeamRoundRobinPairingEngine,
    BbpPairings,
    BergerPairingEngine,
    DoubleBergerPairingEngine,
    TeamSwissEngine,
    TeamBergerEngine,
    TeamDoubleBergerEngine,
)
from data.pairings.settings import (
    PairingSetting,
    ColorSeedSetting,
    BergerNumbersSetting,
    AccelerationRule,
    AccelerationGroup,
)
from data.player import TournamentPlayer
from utils.entity import IdentifiableEntity

if TYPE_CHECKING:
    from data.pairings.systems import PairingSystem
    from data.tournament import Tournament


class PairingVariation(IdentifiableEntity, ABC):
    @classmethod
    def static_id(cls) -> str:
        """Built from the ID of the system and the ID of the variation
        Example for StandardSwissVariation:
        - system: SwissSystem -> SWISS
        - variation: STANDARD
        result: SWISS_STANDARD"""
        return f'{cls.system().id}_{cls.variation_id()}'

    @staticmethod
    @abstractmethod
    def variation_id() -> str:
        """ID of the pairing variation, used to build the ID.
        Should be unique amongst variations of the same system."""

    @staticmethod
    @abstractmethod
    def system() -> 'PairingSystem':
        """Pairing system associated to the variation."""

    @property
    @abstractmethod
    def engine(self) -> PairingEngine:
        """Pairing engine that generates the pairings of a tournament."""

    @property
    @abstractmethod
    def settings(self) -> list[PairingSetting]:
        """List of pairing settings required for the variation to work."""

    def validate_settings(self, tournament: 'Tournament') -> bool:
        return all(setting.is_valid(tournament) for setting in self.settings)

    def get_settings_data_errors(
        self, tournament: 'Tournament', data: dict[str, str]
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        for setting in self.settings:
            errors |= setting.get_data_errors(tournament, data)
        return errors

    def settings_tooltip_message(self, tournament: 'Tournament') -> str | None:
        setting_messages = []
        for setting in self.settings:
            message = setting.tooltip_representation(setting.get_value(tournament))
            if message:
                setting_messages.append(
                    _('{string}: {value}').format(string=setting.name, value=message)
                )
        if not setting_messages:
            return None
        return ''.join(
            [
                f'<div class="text-center text-nowrap">{message}</div>'
                for message in setting_messages
            ]
        )

    @property
    @abstractmethod
    def trf_encoded_type(self) -> str:
        """Encoded type of the variation in TRF26.
        See https://handbook.fide.com/files/handbook/ETT26.pdf for all the types."""

    @property
    def sets_its_own_round_count(self) -> bool:
        """Whether this system settles the round count itself.

        Distinct from :meth:`automatic_round_count`, which answers *what*
        the count is and cannot while the tournament is still empty. The
        form needs to know it should not be asking before anyone has
        been entered.
        """
        return False

    def automatic_round_count(self, tournament: 'Tournament') -> int | None:
        """The number of rounds this system works out for itself, or
        ``None`` when the arbiter chooses it.

        A round-robin's length follows from how many take part, a
        Scheveningen's from how many boards each team fields. Either way
        the arbiter should not have to work it out, so the round count
        field is left empty and the answer given on demand. ``None`` is
        also the answer while the tournament is too empty to say.
        """
        return None

    # -------------------------------------------------------------------------
    # Acceleration
    # -------------------------------------------------------------------------

    @classmethod
    def compute_virtual_points(
        cls,
        tournament: 'Tournament',
        player: TournamentPlayer,
        at_round: int,
    ) -> float:
        """Compute the virtual points of a player for round *at_round*."""
        return 0.0

    @classmethod
    def print_real_points(cls, tournament: 'Tournament', current_round: int) -> bool:
        """Defines if the real points have to be displayed
        in addition to the virtual points for a round."""
        return False

    @property
    def vpoints_use_pairing_numbers(self) -> bool:
        """Defines if the pairing numbers need to be computed before."""
        return False

    def update_settings_from_deleted_pairing_numbers(
        self,
        _tournament: 'Tournament',
        _pairing_numbers: Iterable[int],
    ) -> bool:
        """Update the settings when pairing numbers have been deleted.
        Return True if the settings have been updated."""
        return False

    def update_settings_from_added_pairing_number(
        self, _tournament: 'Tournament', _pairing_number: int
    ):
        """Update the settings when a pairing number has been added.
        Return True if the settings have been updated."""
        return False

    def get_tournament_accelerated_rules(
        self, tournament: 'Tournament'
    ) -> list[AccelerationRule]:
        """Get the acceleration rules of a tournament."""
        return []

    @property
    def include_accelerated_rules_in_trf(self) -> bool:
        """Defines if accelerated rules should be included in the TRF export."""
        return False

    @classmethod
    def get_acceleration_group_max_numbers(cls, tournament: 'Tournament') -> list[int]:
        """Returns the list of the last pairing numbers of each acceleration group."""
        return []

    @classmethod
    def get_acceleration_number_range_by_group(
        cls, tournament: 'Tournament'
    ) -> dict[AccelerationGroup, tuple[int, int]]:
        """Returns the list of the last pairing numbers of each acceleration group."""
        return {}


class SwissVariation(PairingVariation, ABC):
    """Variations of the swiss system are accelerations of the pairings.
    It is represented by virtual points attributed to each player during
    the generation of the pairings."""

    @staticmethod
    def system() -> 'PairingSystem':
        return systems.SwissPairingSystem()

    @property
    def engine(self) -> PairingEngine:
        return BbpPairings()

    @property
    def settings(self) -> list[PairingSetting]:
        return [ColorSeedSetting()]

    @property
    def trf_encoded_type(self) -> str:
        return 'FIDE_DUTCH_2026'


class RoundRobinVariation(PairingVariation, ABC):
    """Parent class of all the Round-Robin pairing variations."""

    @staticmethod
    def system() -> 'PairingSystem':
        return systems.RoundRobinPairingSystem()

    @property
    @override
    def sets_its_own_round_count(self) -> bool:
        return True

    @override
    def automatic_round_count(self, tournament: 'Tournament') -> int | None:
        engine = self.engine
        assert isinstance(engine, RoundRobinPairingEngine)
        player_count = tournament.player_count
        if player_count < engine.MIN_PLAYERS:
            return None
        return engine.get_round_count(player_count)


class StandardSwissVariation(SwissVariation):
    @staticmethod
    def variation_id() -> str:
        return 'STANDARD'

    @staticmethod
    def static_name() -> str:
        return _('Standard swiss system')


class BergerRoundRobinVariation(RoundRobinVariation):
    @staticmethod
    def variation_id() -> str:
        return 'BERGER'

    @staticmethod
    def static_name() -> str:
        return _('Berger')

    @property
    def settings(self) -> list[PairingSetting]:
        return [BergerNumbersSetting()]

    @property
    def engine(self) -> PairingEngine:
        return BergerPairingEngine()

    @property
    def trf_encoded_type(self) -> str:
        return 'FIDE_ROUNDROBIN'


class DoubleBergerRoundRobinVariation(RoundRobinVariation):
    @staticmethod
    def variation_id() -> str:
        return 'DOUBLE_BERGER'

    @staticmethod
    def static_name() -> str:
        return _('Double-round Berger')

    @property
    def settings(self) -> list[PairingSetting]:
        return [BergerNumbersSetting()]

    @property
    def engine(self) -> PairingEngine:
        return DoubleBergerPairingEngine()

    @property
    def trf_encoded_type(self) -> str:
        return 'FIDE_DOUBLEROUNDROBIN'


# ---------------------------------------------------------------------------------
# Team pairing variations. Engines are stubs for now.
# ---------------------------------------------------------------------------------


class TeamSwissVariation(PairingVariation, ABC):
    @staticmethod
    def system() -> 'PairingSystem':
        return systems.TeamSwissPairingSystem()

    @property
    def engine(self) -> PairingEngine:
        return TeamSwissEngine()

    @property
    def settings(self) -> list[PairingSetting]:
        return [ColorSeedSetting()]

    @property
    def trf_encoded_type(self) -> str:
        # Placeholder TRF26 team-Swiss code. The real value depends on
        # the tournament's primary / secondary score choice and is
        # filled in by ``Tournament._team_trf_encoded_type`` when the
        # TRF is emitted; variations don't see the tournament.
        return 'FIDE_TEAM_TYPEA_MP_GP'


class TeamRoundRobinVariation(PairingVariation, ABC):
    @staticmethod
    def system() -> 'PairingSystem':
        return systems.TeamRoundRobinPairingSystem()

    @property
    @override
    def sets_its_own_round_count(self) -> bool:
        return True

    @override
    def automatic_round_count(self, tournament: 'Tournament') -> int | None:
        engine = self.engine
        assert isinstance(engine, TeamRoundRobinPairingEngine)
        team_count = len(tournament.teams)
        if team_count < engine.MIN_TEAMS:
            return None
        return engine.get_round_count(team_count)


class StandardTeamSwissVariation(TeamSwissVariation):
    @staticmethod
    def variation_id() -> str:
        return 'STANDARD'

    @staticmethod
    def static_name() -> str:
        return _('Standard team Swiss')


class BergerTeamRoundRobinVariation(TeamRoundRobinVariation):
    @staticmethod
    def variation_id() -> str:
        return 'BERGER'

    @staticmethod
    def static_name() -> str:
        return _('Berger')

    @property
    def settings(self) -> list[PairingSetting]:
        # The berger numbers are each team's pairing_number, in the canonical
        # order ``_teams_for_tournament`` puts them in.
        return []

    @property
    def engine(self) -> PairingEngine:
        return TeamBergerEngine()

    @property
    def trf_encoded_type(self) -> str:
        return 'FIDE_TEAM_ROUNDROBIN'


class DoubleBergerTeamRoundRobinVariation(TeamRoundRobinVariation):
    @staticmethod
    def variation_id() -> str:
        return 'DOUBLE_BERGER'

    @staticmethod
    def static_name() -> str:
        return _('Double-round Berger')

    @property
    def settings(self) -> list[PairingSetting]:
        return []

    @property
    def engine(self) -> PairingEngine:
        return TeamDoubleBergerEngine()

    @property
    def trf_encoded_type(self) -> str:
        return 'FIDE_TEAM_DOUBLEROUNDROBIN'

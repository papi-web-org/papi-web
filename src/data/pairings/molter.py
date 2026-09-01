"""Molter team-pairing system driven by packed fixed-table recipes.

A rule set may override the table for a specific size with an official
table (see :meth:`data.rule_sets.rule_sets.RuleSet.molter_table_overrides`);
that is the one extension point left to downstream consumers.
"""

from functools import cached_property
from typing import TYPE_CHECKING, override

from common.i18n import _
from data.pairings.engines import PairingEngine
from data.pairings.fixed_table import (
    FixedPairingTable,
    FixedTablePairingEngine,
    FixedTablePairingSystem,
    FixedTableVariation,
)
from data.pairings.molter_recipes import (
    MolterRecipeError,
    get_molter_recipe_table,
    supported_molter_recipe_team_counts,
)
from data.pairings.settings import PairingSetting
from data.pairings.systems import swiss_style_permission_handler
from data.safety_mode import PairingAction, PermissionHandler
from utils.entity import EntityManager, EventBoundEntityManager

if TYPE_CHECKING:
    from data.event import Event
    from data.tournament import Tournament


class MolterPairingSystem(FixedTablePairingSystem):
    @staticmethod
    def static_id() -> str:
        return 'MOLTER'

    @staticmethod
    def static_name() -> str:
        return _('Molter')

    @override
    def variation_manager(self, event: 'Event') -> EntityManager[FixedTableVariation]:
        return MolterVariationManager(event)

    @property
    def pairing_buttons_template(self) -> str:
        return '/admin/pairings/swiss_pairing_buttons.html'

    @property
    @override
    def supports_complementary_pairings(self) -> bool:
        # Molter pairs everyone straight from the fixed table.
        return False

    @property
    @override
    def predetermined_pairings(self) -> bool:
        # Every board of every round comes from the published table.
        return True

    @cached_property
    def permission_handler(self) -> PermissionHandler[PairingAction]:
        return swiss_style_permission_handler(protect_unpairing=False)

    def default_current_round(self, tournament: 'Tournament') -> int:
        return tournament.last_paired_round

    @override
    def get_table(
        self,
        team_count: int,
        players_per_team: int,
        tournament: 'Tournament | None' = None,
    ) -> FixedPairingTable | None:
        # A rule set may ship its own official table for a specific size; it
        # takes precedence over the generated one.
        if tournament is not None:
            rule_set = tournament.rule_set
            if rule_set is not None:
                override_table = rule_set.molter_table_overrides().get(
                    (team_count, players_per_team)
                )
                if override_table is not None:
                    return override_table
        # Otherwise replay a packed recipe. ``get_molter_recipe_table`` returns
        # the exact requested round count when available; if only a shorter max
        # recipe exists for this (N, P), returning that table lets the fixed-table
        # engine report the concrete round limit to the user.
        try:
            rounds = tournament.rounds if tournament is not None else None
            return get_molter_recipe_table(team_count, players_per_team, rounds)
        except MolterRecipeError:
            return None

    @override
    def supported_team_counts(self) -> tuple[int, ...]:
        return supported_molter_recipe_team_counts()


class MolterEngine(FixedTablePairingEngine):
    @property
    @override
    def system(self) -> MolterPairingSystem:
        return MolterPairingSystem()


class MolterVariation(FixedTableVariation):
    @staticmethod
    def system() -> 'MolterPairingSystem':
        return MolterPairingSystem()

    @property
    def engine(self) -> PairingEngine:
        return MolterEngine()

    @property
    def settings(self) -> list[PairingSetting]:
        return []

    @property
    def trf_encoded_type(self) -> str:
        # Molter has no FIDE TRF26 team code; exported under the custom
        # Schiller pairing-engine identifier.
        return 'CUSTOM_SCHILLER'


class StandardMolterVariation(MolterVariation):
    @staticmethod
    def variation_id() -> str:
        return 'STANDARD'

    @staticmethod
    def static_name() -> str:
        return _('Standard Molter')


class MolterVariationManager(EventBoundEntityManager[FixedTableVariation]):
    @override
    def entity_types(self) -> list[type[FixedTableVariation]]:
        return [StandardMolterVariation]

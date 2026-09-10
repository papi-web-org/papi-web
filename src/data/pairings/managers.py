from typing import cast, override

from data.pairings import systems, PairingVariation
from data.pairings.keizer import KeizerPairingSystem, KeizerVariationManager
from data.pairings.knockout import (
    KnockoutPairingSystem,
    KnockoutVariationManager,
    TeamKnockoutPairingSystem,
    TeamKnockoutVariationManager,
)
from data.pairings.molter import MolterPairingSystem, MolterVariationManager
from data.pairings.scheveningen import (
    ScheveningenPairingSystem,
    ScheveningenVariationManager,
)
from data.pairings.systems import PairingSystem
from data.pairings.acceleration import ACCELERATED_SWISS_VARIATIONS
from data.pairings.variations import (
    SwissVariation,
    StandardSwissVariation,
    RoundRobinVariation,
    BergerRoundRobinVariation,
    DoubleBergerRoundRobinVariation,
    TeamSwissVariation,
    StandardTeamSwissVariation,
    TeamRoundRobinVariation,
    BergerTeamRoundRobinVariation,
    DoubleBergerTeamRoundRobinVariation,
)
from plugins.manager import plugin_manager
from utils.entity import EventBoundEntityManager


class PairingSystemManager(EventBoundEntityManager[PairingSystem]):
    @override
    def entity_types(self) -> list[type[PairingSystem]]:
        if self.event is not None and self.event.is_team_event:
            base: list[type[PairingSystem]] = [
                systems.TeamSwissPairingSystem,
                systems.TeamRoundRobinPairingSystem,
                ScheveningenPairingSystem,
                MolterPairingSystem,
                TeamKnockoutPairingSystem,
            ]
            plugin_manager.hook_for_event(self.event, 'insert_team_pairing_systems')(
                pairing_systems=base
            )
            return base
        return [
            systems.SwissPairingSystem,
            systems.RoundRobinPairingSystem,
            KnockoutPairingSystem,
            KeizerPairingSystem,
        ]


class SwissVariationManager(EventBoundEntityManager[SwissVariation]):
    @override
    def entity_types(self) -> list[type[SwissVariation]]:
        variations: list[type[SwissVariation]] = [
            StandardSwissVariation,
            *ACCELERATED_SWISS_VARIATIONS,
        ]
        plugin_manager.hook_for_event(
            self.event, 'insert_swiss_pairing_variation_types'
        )(variation_types=variations)
        return variations


class RoundRobinVariationManager(EventBoundEntityManager[RoundRobinVariation]):
    @override
    def entity_types(self) -> list[type[RoundRobinVariation]]:
        return [
            BergerRoundRobinVariation,
            DoubleBergerRoundRobinVariation,
        ]


class TeamSwissVariationManager(EventBoundEntityManager[TeamSwissVariation]):
    @override
    def entity_types(self) -> list[type[TeamSwissVariation]]:
        return [StandardTeamSwissVariation]


class TeamRoundRobinVariationManager(EventBoundEntityManager[TeamRoundRobinVariation]):
    @override
    def entity_types(self) -> list[type[TeamRoundRobinVariation]]:
        return [
            BergerTeamRoundRobinVariation,
            DoubleBergerTeamRoundRobinVariation,
        ]


class PairingVariationManager(EventBoundEntityManager[PairingVariation]):
    @override
    def entity_types(self) -> list[type[PairingVariation]]:
        if self.event is not None and self.event.is_team_event:
            result: list[type[PairingVariation]] = (
                cast(
                    list[type[PairingVariation]],
                    TeamSwissVariationManager(self.event).entity_types(),
                )
                + cast(
                    list[type[PairingVariation]],
                    TeamRoundRobinVariationManager(self.event).entity_types(),
                )
                + cast(
                    list[type[PairingVariation]],
                    ScheveningenVariationManager(self.event).entity_types(),
                )
                + cast(
                    list[type[PairingVariation]],
                    MolterVariationManager(self.event).entity_types(),
                )
                + cast(
                    list[type[PairingVariation]],
                    TeamKnockoutVariationManager(self.event).entity_types(),
                )
            )
            plugin_manager.hook_for_event(self.event, 'insert_team_pairing_variations')(
                variations=result
            )
            return result
        return (
            cast(
                list[type[PairingVariation]],
                SwissVariationManager(self.event).entity_types(),
            )
            + cast(
                list[type[PairingVariation]],
                RoundRobinVariationManager(self.event).entity_types(),
            )
            + cast(
                list[type[PairingVariation]],
                KnockoutVariationManager(self.event).entity_types(),
            )
            + cast(
                list[type[PairingVariation]],
                KeizerVariationManager(self.event).entity_types(),
            )
        )

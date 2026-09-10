from abc import ABC, abstractmethod
from functools import cache, cached_property
from typing import TYPE_CHECKING, override

from common.i18n import _
from data.safety_mode import (
    PairingAction,
    PermissionHandler,
    Permission,
    RoundStatus,
    SafetyMode,
)
from utils.entity import IdentifiableEntity, EntityManager

if TYPE_CHECKING:
    from data.pairings.variations import (
        PairingVariation,
        SwissVariation,
        RoundRobinVariation,
        TeamSwissVariation,
        TeamRoundRobinVariation,
    )
    from data.tournament import Tournament
    from data.event import Event


@cache
def swiss_style_permission_handler(
    *, protect_unpairing: bool = True
) -> PermissionHandler[PairingAction]:
    """Permissions for round-by-round systems using the Swiss pairing tab.

    With *protect_unpairing*, unpairing goes through the protected-editing
    modal: a Swiss decides each round from the ones before it, so dropping a
    round changes what the next pairing would have been. Without it, unpairing
    is plain: a table- or bracket-driven schedule pairs the same way whatever
    is undone.
    """
    full_unpairing_mode = (
        SafetyMode.FIDE_INCOMPATIBLE if protect_unpairing else SafetyMode.SAFE
    )
    manual_unpairing_rules = (
        {
            RoundStatus.PAST: SafetyMode.FIDE_INCOMPATIBLE,
            RoundStatus.PREVIOUS: SafetyMode.UNSAFE,
            RoundStatus.CURRENT: SafetyMode.UNSAFE,
        }
        if protect_unpairing
        else {
            RoundStatus.PAST: SafetyMode.SAFE,
            RoundStatus.PREVIOUS: SafetyMode.SAFE,
            RoundStatus.CURRENT: SafetyMode.SAFE,
        }
    )
    return PermissionHandler(
        [
            Permission(PairingAction.FULL_PAIRING, {RoundStatus.NEXT: SafetyMode.SAFE}),
            Permission(
                PairingAction.PARTIAL_PAIRING, {RoundStatus.CURRENT: SafetyMode.UNSAFE}
            ),
            Permission(
                PairingAction.MANUAL_PAIRING,
                {
                    RoundStatus.PAST: SafetyMode.FIDE_INCOMPATIBLE,
                    RoundStatus.PREVIOUS: SafetyMode.UNSAFE,
                    RoundStatus.CURRENT: SafetyMode.UNSAFE,
                    RoundStatus.NEXT: SafetyMode.FIDE_INCOMPATIBLE,
                },
            ),
            Permission(
                PairingAction.FULL_UNPAIRING,
                {RoundStatus.CURRENT: full_unpairing_mode},
            ),
            Permission(PairingAction.MANUAL_UNPAIRING, manual_unpairing_rules),
            Permission(
                PairingAction.COLOR_PERMUTE,
                {
                    RoundStatus.PAST: SafetyMode.FIDE_INCOMPATIBLE,
                    RoundStatus.PREVIOUS: SafetyMode.UNSAFE,
                    RoundStatus.CURRENT: SafetyMode.UNSAFE,
                },
            ),
            Permission(
                PairingAction.RESULT_UPDATE,
                {
                    RoundStatus.PAST: SafetyMode.FIDE_INCOMPATIBLE,
                    RoundStatus.PREVIOUS: SafetyMode.UNSAFE,
                    RoundStatus.CURRENT: SafetyMode.SAFE,
                },
            ),
            Permission(
                PairingAction.BYE_UPDATE,
                {
                    RoundStatus.PAST: SafetyMode.FIDE_INCOMPATIBLE,
                    RoundStatus.PREVIOUS: SafetyMode.UNSAFE,
                    RoundStatus.CURRENT: SafetyMode.SAFE,
                    RoundStatus.NEXT: SafetyMode.SAFE,
                    RoundStatus.FUTURE: SafetyMode.SAFE,
                },
            ),
        ]
    )


class PairingSystem[PV: PairingVariation](IdentifiableEntity, ABC):
    """Abstract class representing all the different pairing systems.
    Each system can have different variations."""

    @abstractmethod
    def variation_manager(self, event: 'Event') -> EntityManager[PV]:
        """Manager of all the variations of the system."""

    @property
    @abstractmethod
    def pairing_buttons_template(self) -> str:
        """Template of the buttons handling the pairings."""

    @cached_property
    @abstractmethod
    def permission_handler(self) -> PermissionHandler[PairingAction]:
        """Handler of permissions for the pairing system."""

    @abstractmethod
    def default_current_round(self, tournament: 'Tournament') -> int:
        """Get the current round to use as default when it is not defined in the DB."""

    @property
    def supports_prohibited_pairings(self) -> bool:
        """Whether prohibited pairings can be configured. Round-robin
        systems pair from fixed tables where everyone meets everyone,
        so prohibitions cannot be honored."""
        return False

    @property
    def allow_rounds_update_once_started(self) -> bool:
        """Determines if the number of rounds can be updated once a tournament is started."""
        return True

    @property
    def allow_player_addition_once_paired(self) -> bool:
        """Determines if players can be added on a tournament with pairings."""
        return True

    @property
    def allow_team_addition_once_paired(self) -> bool:
        """Determines if teams can be added on a tournament with
        pairings. Systems pairing from fixed tables (round-robins,
        two-game matches, fixed-table systems) cannot absorb a new
        team once the schedule has started."""
        return True

    @property
    def allow_bye_definition(self) -> bool:
        """Determines if byes can be defined from the player history modal."""
        return True

    @property
    def show_unfinished_round_modal(self) -> bool:
        """Determines if the modal warning about the round not being finished
        when moving from the current to the next round is displayed."""
        return True

    @property
    def show_unpaired_player_modal(self) -> bool:
        """Determines if the modal allowing to handle unpaired players is displayed."""
        return True

    @property
    def show_unpaired_team_modal(self) -> bool:
        """Determines if the modal allowing to handle unpaired teams
        (check-in, byes, manual pairing) is displayed. Systems pairing
        teams from fixed tables always pair every team, so there is no
        team status to manage."""
        return True

    @property
    def split_unpaired_and_bye_players(self) -> bool:
        """Determines if the unpaired and bye players are separated in the unpaired table."""
        return True

    @property
    def round_per_round_pairing_generation(self) -> bool:
        """Determines if the pairings are generated round per round
        or all the rounds at the same time."""
        return True

    @property
    def predetermined_pairings(self) -> bool:
        """Whether every participant's opponents are known before the
        tournament starts (round-robin, fixed-table systems). A forfeit
        is then the only way to miss a round, which is why FIDE Art.
        15.2 counts forfeits as regular games or matches for these
        systems instead of applying the Swiss unplayed-round management
        of Art. 16. Default False — a Swiss decides its pairings as it
        goes."""
        return False

    @property
    def supports_participation_rule(self) -> bool:
        """Whether the < 50% participation rule (FIDE 6.6) can be applied:
        a participant who withdrew or was expelled having completed less
        than half of their games is dropped from the final standings and
        their games annulled. The rule is defined for an all-play-all, so
        default False."""
        return False

    @property
    def eliminates_participants(self) -> bool:
        """Whether losing takes a participant out of the tournament, so
        the field shrinks each round (a knock-out). A knocked-out player
        is not waiting to be paired and has no result to give: they must
        not count towards the round being finished, nor appear in the
        unpaired ('to pair') list — only the participants still boarded
        this round do. Default False — in a Swiss or round-robin everyone
        plays every round."""
        return False

    def round_is_locked(self, tournament: 'Tournament', round_: int) -> bool:
        """Whether a round's results are read-only. Default False — most
        systems let a result be corrected at any time. A knock-out locks a
        round once the next has been paired from it, since changing a result
        would invalidate the bracket that was drawn."""
        return False

    def tournament_is_over(self, tournament: 'Tournament') -> bool:
        """Whether the tournament has ended before its last reserved round is
        reached. Default False — a tournament ends when its final round is
        played. A double elimination reserves a reset round that is skipped
        when the winners'-bracket champion wins the grand final, ending the
        event a round early; the system reports that here so the standings
        become available without pairing a round that will never be played."""
        return False

    @property
    def paired_by_team(self) -> bool:
        """Whether this system pairs entire teams against each other (each
        round groups boards into team-vs-team blocks). True for the standard
        team systems; False for individual systems and for team systems
        like flat-mixed-pairing systems where boards aren't grouped.
        Default True — most team systems pair by team; non-team systems
        override to False."""
        return True

    @property
    def uses_colour_pattern(self) -> bool:
        """Whether the arbiter chooses which team takes White on each
        board of a match. True wherever teams are paired against each
        other and nothing else settles the colours; systems reading
        their colours off a fixed table override to False."""
        return self.paired_by_team

    @property
    def supports_colour_preferences(self) -> bool:
        """Whether colours are allocated from each entrant's colour
        history — the Swiss rule, which brings a colour-allocation
        basis (the secondary score) and a colour-difference rule with
        it. Fixed-schedule systems settle colours from their table."""
        return False

    @property
    def fide_team_swiss_code(self) -> bool:
        """Whether TRF field 192 should carry the FIDE team-Swiss code
        (``FIDE_TEAM_TYPE<X>_<primary>[_<secondary>]``) for this system.
        True only for the team-Swiss system; other team systems (round
        robin, two-game match, Molter) keep their own variation code."""
        return False

    @property
    def supports_complementary_pairings(self) -> bool:
        """Whether the system can leave entrants unpaired to be paired
        afterwards ('complementary pairings'). True for Swiss-style
        engines; fixed-table systems (round-robin, Molter) pair everyone
        straight from the table, so it makes no sense — they override to
        False."""
        return True

    @property
    def lock_settings_after_first_pairing(self) -> bool:
        """Whether the pairing settings become read-only once the first
        round is paired. True for systems where the settings are baked
        into the pairings already made (acceleration groups, seed colour,
        table numbers) and changing them would desync those rounds. A
        system that recomputes the whole field from scratch on every
        render carries no such frozen state and can stay editable.
        """
        return True

    @property
    def uses_result_points(self) -> bool:
        """Whether the standing is a sum of per-game result points (win /
        draw / loss values — and, in team play, the match points that
        derive from them). True for the usual systems, whose score can
        therefore be reported to a rating body and configured through the
        point-attribution fields. False where the score is worked out some
        other way (a ranking-value system), so those fields and the
        rating-report exports have no meaning.
        """
        return True

    @property
    def supports_match_points(self) -> bool:
        """Whether the system exposes a match-point score alongside
        game points. Tie-breaks (or tie-break options) that need MP
        as a reference score can use this to declare themselves
        incompatible with systems where MP doesn't exist."""
        return True

    @property
    def uses_team_letters(self) -> bool:
        """Whether teams are conventionally identified by a letter
        (``A``, ``B``, …) rather than a numeric pairing number. True for
        the fixed-schedule team systems (round-robin Berger grids, Molter
        tables), which present teams alphabetically. Default False."""
        return False

    @property
    def variation_field_id(self) -> str:
        """ID of the form field selecting the variation of the system."""
        return f'{self.id}_pairing_variation'

    @property
    def variation_container_id(self) -> str:
        """ID of the container of the variation field in the form."""
        return f'{self.variation_field_id}_container'

    @property
    def tie_break_help_container_id(self) -> str:
        """ID of the html element containing the tie-break help in the tournament form."""
        return f'{self.id}_tie_break_help_container'


class SwissPairingSystem(PairingSystem['SwissVariation']):
    @staticmethod
    def static_id() -> str:
        return 'SWISS'

    @staticmethod
    def static_name() -> str:
        return _('Swiss')

    @override
    def variation_manager(self, event: 'Event') -> EntityManager['SwissVariation']:
        from data.pairings.managers import SwissVariationManager

        return SwissVariationManager(event)

    @property
    def pairing_buttons_template(self) -> str:
        return '/admin/pairings/swiss_pairing_buttons.html'

    @property
    def supports_prohibited_pairings(self) -> bool:
        return True

    @cached_property
    def permission_handler(self) -> PermissionHandler[PairingAction]:
        return swiss_style_permission_handler()

    def default_current_round(self, tournament: 'Tournament') -> int:
        return tournament.last_paired_round


class RoundRobinPairingSystem(PairingSystem['RoundRobinVariation']):
    @staticmethod
    def static_id() -> str:
        return 'ROUND_ROBIN'

    @staticmethod
    def static_name() -> str:
        return _('Round-Robin')

    @property
    def round_per_round_pairing_generation(self) -> bool:
        return False

    @property
    @override
    def predetermined_pairings(self) -> bool:
        # The Berger tables fix every opponent up front.
        return True

    @property
    @override
    def supports_participation_rule(self) -> bool:
        return True

    @override
    def variation_manager(self, event: 'Event') -> EntityManager['RoundRobinVariation']:
        from data.pairings.managers import RoundRobinVariationManager

        return RoundRobinVariationManager(event)

    @property
    def allow_rounds_update_once_started(self) -> bool:
        return False

    @property
    def allow_player_addition_once_paired(self) -> bool:
        return False

    @property
    def allow_bye_definition(self) -> bool:
        return False

    @property
    def show_unfinished_round_modal(self) -> bool:
        return False

    @property
    def show_unpaired_player_modal(self) -> bool:
        return False

    @property
    def split_unpaired_and_bye_players(self) -> bool:
        return False

    @property
    def pairing_buttons_template(self) -> str:
        return '/admin/pairings/round_robin_pairing_buttons.html'

    @property
    @override
    def supports_complementary_pairings(self) -> bool:
        # Round-robin pairs everyone from the Berger table.
        return False

    @cached_property
    def permission_handler(self) -> PermissionHandler[PairingAction]:
        permissions = [
            Permission(
                PairingAction.RESULT_UPDATE,
                {
                    RoundStatus.PAST: SafetyMode.UNSAFE,
                    RoundStatus.PREVIOUS: SafetyMode.UNSAFE,
                    RoundStatus.CURRENT: SafetyMode.SAFE,
                    RoundStatus.NEXT: SafetyMode.SAFE,
                    RoundStatus.FUTURE: SafetyMode.SAFE,
                },
            ),
            Permission(
                PairingAction.COLOR_PERMUTE,
                {status: SafetyMode.FIDE_INCOMPATIBLE for status in RoundStatus},
            ),
        ]
        return PermissionHandler(permissions)

    def default_current_round(self, tournament: 'Tournament') -> int:
        """Last round with played results."""
        return next(
            (
                round_
                for round_ in reversed(range(1, tournament.rounds + 1))
                if tournament.round_has_played_result(round_)
            ),
            1 if tournament.has_pairings else 0,
        )


# ---------------------------------------------------------------------------------
# Team pairing systems. Engines / variations live in variations.py / engines.py.
# These mirror their individual counterparts; specific team-mode behaviour will
# land alongside the engine implementations in future bites.
# ---------------------------------------------------------------------------------


class TeamSwissPairingSystem(PairingSystem['TeamSwissVariation']):
    @staticmethod
    def static_id() -> str:
        return 'TEAM_SWISS'

    @staticmethod
    def static_name() -> str:
        return _('Team Swiss')

    @property
    @override
    def fide_team_swiss_code(self) -> bool:
        return True

    @property
    @override
    def supports_colour_preferences(self) -> bool:
        return True

    @override
    def variation_manager(self, event: 'Event') -> EntityManager['TeamSwissVariation']:
        from data.pairings.managers import TeamSwissVariationManager

        return TeamSwissVariationManager(event)

    @property
    def pairing_buttons_template(self) -> str:
        return '/admin/pairings/swiss_pairing_buttons.html'

    @property
    def supports_prohibited_pairings(self) -> bool:
        return True

    @cached_property
    def permission_handler(self) -> PermissionHandler[PairingAction]:
        return swiss_style_permission_handler()

    @property
    def allow_bye_definition(self) -> bool:
        return False

    def default_current_round(self, tournament: 'Tournament') -> int:
        return tournament.last_paired_round


class TeamRoundRobinPairingSystem(PairingSystem['TeamRoundRobinVariation']):
    @staticmethod
    def static_id() -> str:
        return 'TEAM_ROUND_ROBIN'

    @staticmethod
    def static_name() -> str:
        return _('Team Round-Robin')

    @property
    @override
    def uses_team_letters(self) -> bool:
        # Teams appear as letters (A, B, …) in the Berger grid.
        return True

    @property
    @override
    def predetermined_pairings(self) -> bool:
        # The Berger tables fix every opponent up front.
        return True

    @property
    @override
    def supports_participation_rule(self) -> bool:
        return True

    @override
    def variation_manager(
        self, event: 'Event'
    ) -> EntityManager['TeamRoundRobinVariation']:
        from data.pairings.managers import TeamRoundRobinVariationManager

        return TeamRoundRobinVariationManager(event)

    @property
    def allow_rounds_update_once_started(self) -> bool:
        return False

    @property
    def allow_player_addition_once_paired(self) -> bool:
        return False

    @property
    def allow_bye_definition(self) -> bool:
        return False

    @property
    def show_unpaired_player_modal(self) -> bool:
        return False

    @property
    def show_unpaired_team_modal(self) -> bool:
        return False

    @property
    def allow_team_addition_once_paired(self) -> bool:
        return False

    @property
    def split_unpaired_and_bye_players(self) -> bool:
        return False

    @property
    def pairing_buttons_template(self) -> str:
        # Pair round-by-round so each team can edit its lineup between
        # rounds — a bulk pair would lock every round to the round-1
        # lineup.
        return '/admin/pairings/swiss_pairing_buttons.html'

    @property
    @override
    def supports_complementary_pairings(self) -> bool:
        # Round-robin pairs every team from the Berger table.
        return False

    @cached_property
    def permission_handler(self) -> PermissionHandler[PairingAction]:
        # Reuse the Swiss permission set so FULL_PAIRING is permitted
        # when the ratings-warning modal falls through to the single-
        # round pair endpoint (variations with no settings). Unpairing is
        # safe because the Berger table can regenerate the same pairings.
        return swiss_style_permission_handler(protect_unpairing=False)

    def default_current_round(self, tournament: 'Tournament') -> int:
        # Swiss semantics (last PAIRED round), matching the round-by-round
        # pairing flow and the Swiss permission set above: a freshly
        # paired round must be CURRENT for its results to be enterable.
        return tournament.last_paired_round

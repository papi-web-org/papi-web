from functools import cached_property
from typing import TYPE_CHECKING, override

from common.i18n import _
from data.pairings.systems import PairingSystem, swiss_style_permission_handler
from data.safety_mode import PairingAction, PermissionHandler
from utils.entity import EntityManager

if TYPE_CHECKING:
    from data.event import Event
    from data.pairings.knockout_helpers.variations import (
        KnockoutVariation,
        TeamKnockoutVariation,
    )
    from data.tournament import Tournament


class _KnockoutSystemMixin:
    """Capability flags shared by the individual and team knock-out
    systems. A knock-out decides its pairings as it goes (a lower seed may
    win), settles its own round count from the field size, and reads no
    colour history — colours are drawn or alternated."""

    @property
    def predetermined_pairings(self) -> bool:
        # A lower seed may beat a higher one, so no opponent past round one
        # is known before the games are played.
        return False

    @property
    def eliminates_participants(self) -> bool:
        # Losing knocks a participant out; the field halves each round.
        return True

    def round_is_locked(self, tournament: 'Tournament', round_: int) -> bool:
        # A round is read-only once the next round is paired from its
        # results — changing them would invalidate the drawn bracket.
        return round_ < tournament.rounds and tournament.round_has_pairings(round_ + 1)

    def tournament_is_over(self, tournament: 'Tournament') -> bool:
        # Only double elimination ends early (its reset round is skipped when
        # no reset is due); the engine holds that rule. A single elimination
        # has no such round, so its engine does not answer and it ends the
        # ordinary way, when its final round is played.
        hook = getattr(tournament.pairing_variation.engine, 'tournament_is_over', None)
        return bool(hook(tournament)) if hook is not None else False

    @property
    def supports_colour_preferences(self) -> bool:
        return False

    @property
    def supports_complementary_pairings(self) -> bool:
        return False

    @property
    def supports_prohibited_pairings(self) -> bool:
        return False

    @property
    def allow_rounds_update_once_started(self) -> bool:
        # The round count is owned by the bracket.
        return False

    @property
    def allow_player_addition_once_paired(self) -> bool:
        # The bracket is drawn from the whole field at round one.
        return False

    @property
    def allow_team_addition_once_paired(self) -> bool:
        return False

    @property
    def allow_bye_definition(self) -> bool:
        # A knock-out has no sit-out bye: a participant without an opponent
        # is one the bracket padded through, not one the arbiter excuses.
        return False

    @property
    def show_unpaired_player_modal(self) -> bool:
        # The bracket seats every player each round; there is nothing to
        # mark absent, bye or pair by hand, so the per-player action modal
        # (absent / ZPB / HPB / pair as white) has no place here.
        return False

    @property
    def show_unpaired_team_modal(self) -> bool:
        return False

    @property
    def split_unpaired_and_bye_players(self) -> bool:
        return False

    @property
    def lock_settings_after_first_pairing(self) -> bool:
        # The settings shape the whole bracket (round count, colours, the
        # third-place and reset rounds), so they are frozen once round one is
        # paired — changing them mid-bracket would not match what was played.
        return True

    @property
    def pairing_buttons_template(self) -> str:
        # Round by round, like a Swiss: each round is paired only once the
        # previous one is decided.
        return '/admin/pairings/swiss_pairing_buttons.html'

    @cached_property
    def permission_handler(self) -> PermissionHandler[PairingAction]:
        return swiss_style_permission_handler(protect_unpairing=False)

    def default_current_round(self, tournament: 'Tournament') -> int:
        return tournament.last_paired_round


class KnockoutPairingSystem(_KnockoutSystemMixin, PairingSystem['KnockoutVariation']):
    """Individual single-elimination."""

    @staticmethod
    def static_id() -> str:
        return 'KNOCKOUT'

    @staticmethod
    def static_name() -> str:
        return _('Knock-out')

    @override
    def variation_manager(self, event: 'Event') -> EntityManager['KnockoutVariation']:
        from data.pairings.knockout_helpers.variations import KnockoutVariationManager

        return KnockoutVariationManager(event)

    @property
    @override
    def paired_by_team(self) -> bool:
        return False


class TeamKnockoutPairingSystem(
    _KnockoutSystemMixin, PairingSystem['TeamKnockoutVariation']
):
    """Team single-elimination: two teams meet in a match each round, the
    winning team advances."""

    @staticmethod
    def static_id() -> str:
        return 'TEAM_KNOCKOUT'

    @staticmethod
    def static_name() -> str:
        return _('Team Knock-out')

    @override
    def variation_manager(
        self, event: 'Event'
    ) -> EntityManager['TeamKnockoutVariation']:
        from data.pairings.knockout_helpers.variations import (
            TeamKnockoutVariationManager,
        )

        return TeamKnockoutVariationManager(event)

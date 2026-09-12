from functools import cached_property, cache
from typing import TYPE_CHECKING, Optional, Collection

from litestar_htmx import HTMXRequest

from common.i18n.utils import by
from common.logger import get_logger
from common.network import LOCALHOST_IP, LOCALHOST_NAME
from data.access_levels.actions import AuthAction
from data.account import (
    Account,
    Permission,
)
from data.access_levels.manager import AccessLevelManager
from data.access_levels.access_levels import AccessLevel
from data.player import Player
from data.tournament import Tournament
from utils.enum import Result
from web.session import SessionUserAccountId, SessionUserAccountPasswordHash
from web.tunnel import request_is_tunnelled

if TYPE_CHECKING:
    from data.event import Event

logger = get_logger()


class Client:
    """A class that represents a client, built from an HTTP request."""

    request: HTMXRequest | None

    def __init__(
        self,
        request: HTMXRequest,
        event: Optional['Event'] = None,
    ):
        self.request = request
        self.host = (
            self.request.client.host
            if self.request.client and self.request.client.host
            else ''
        )
        self.event = event
        self.remote = request_is_tunnelled(request.scope)
        self.account = self._get_account()

    @cached_property
    def source_host(self) -> str:
        """The address the request originated from.  Tunnelled requests all
        reach the server from the tunnel client running on this machine, so the
        caller is named by the forwarding header instead; only the tunnel client
        can reach the listener that carries them.

        The *last* entry is the one to read, not the first.  A forwarding header
        is appended to, so anything before the final entry was written by
        somebody upstream of the relay — which, at the public end of a tunnel,
        means whoever is calling.  Reading the first entry would let a caller
        name themselves differently on every attempt and so never be counted."""
        if self.remote and self.request is not None:
            forwarded_for = self.request.headers.get('x-forwarded-for')
            if forwarded_for:
                relay_saw = forwarded_for.rsplit(',', 1)[-1].strip()
                if relay_saw:
                    return relay_saw
        return self.host

    def _get_account(self) -> Account:
        if not self.remote and self.host in [LOCALHOST_IP, LOCALHOST_NAME]:
            if self.event:
                return self.event.administrator_account
            return Account.predefined_administrator_account()
        if not self.event:
            return Account.predefined_anonymous_account()
        assert self.request is not None
        account_id_handler = SessionUserAccountId(self.request, self.event)
        account_id = account_id_handler.get()
        accounts_by_id = self.event.active_user_accounts_by_id
        if not account_id or account_id not in accounts_by_id:
            return self.event.anonymous_account
        hash_handler = SessionUserAccountPasswordHash(self.request, self.event)
        account = accounts_by_id[account_id]
        if account.password_hash != hash_handler.get():
            logger.info(
                'Password has changed for account [%s], force the re-authentication.',
                account.full_name,
            )
            account_id_handler.unset()
            hash_handler.unset()
            return self.event.anonymous_account
        return account

    @classmethod
    def for_event_administrator(cls, event: 'Event') -> 'Client':
        """Build a request-less client with the event administrator account, for
        background tasks (e.g. plugin auto-uploads) that need to render documents
        or check permissions outside of an HTTP request."""
        client = cls.__new__(cls)
        client.request = None
        client.host = LOCALHOST_IP
        client.event = event
        client.remote = False
        client.account = event.administrator_account
        return client

    def __str__(self) -> str:
        return f'{self.__class__.__name__}(account={self.account}, host={self.host})'

    def __repr__(self):
        return (
            f'{self.__class__.__name__}(request={self.request!r}, event={self.event!r})'
        )

    # ---------------------------------------------------------------------------------
    # Permissions / actions
    # ---------------------------------------------------------------------------------

    @cached_property
    def permissions_by_access_level(self) -> dict[AccessLevel, Permission]:
        return self.account.get_permissions_by_access_level()

    @staticmethod
    @cache
    def access_levels_by_action() -> dict[AuthAction, list[AccessLevel]]:
        access_levels_by_action: dict[AuthAction, list[AccessLevel]] = {
            action: [] for action in AuthAction
        }
        for access_level in AccessLevelManager().objects():
            for action in access_level.allowed_actions():
                access_levels_by_action[action].append(access_level)
        return access_levels_by_action

    @cached_property
    def allowed_actions(self) -> set[AuthAction]:
        actions: set[AuthAction] = set()
        for access_level in self.account.access_levels:
            actions |= access_level.allowed_actions()
        return actions

    def action_allowed_for_tournament(
        self, action: AuthAction, tournament_id: int
    ) -> bool:
        """Returns True if the action is allowed for a tournament, False otherwise."""
        if action not in self.allowed_actions:
            return False
        for access_level in self.access_levels_by_action()[action]:
            permission = self.permissions_by_access_level.get(access_level, None)
            if permission and (
                permission.tournament_ids is None
                or tournament_id in permission.tournament_ids
            ):
                return True
        return False

    def action_allowed_for_player(self, action: AuthAction, player: Player) -> bool:
        """Returns True if the action is allowed for at least one
        tournament of a player, False otherwise."""
        if action not in self.allowed_actions:
            return False
        checked_tournament_ids: list[int] = []
        for access_level in self.access_levels_by_action()[action]:
            permission = self.permissions_by_access_level.get(access_level, None)
            if not permission:
                continue
            if permission.tournament_ids is None:
                return True
            assert self.event is not None
            for tournament_id in permission.tournament_ids:
                if tournament_id in checked_tournament_ids:
                    continue
                tournament = self.event.tournaments_by_id[tournament_id]
                if player.id in tournament.tournament_players_by_id:
                    return True
        return False

    def allowed_tournaments_for_action(self, action: AuthAction) -> list[Tournament]:
        """Get the list of tournaments for which an action is allowed."""
        assert self.event is not None
        return [
            tournament
            for tournament in self.event.sorted_tournaments
            if self.action_allowed_for_tournament(action, tournament.id)
        ]

    @cached_property
    def allowed_players_by_id(self) -> dict[int, Player]:
        assert self.event is not None
        tournaments = self.allowed_tournaments_for_action(AuthAction.VIEW_PLAYERS_TAB)
        if len(tournaments) == len(self.event.tournaments):
            return self.event.players_by_id
        allowed_players_by_id: dict[int, Player] = {}
        for tournament in tournaments:
            for player in tournament.tournament_players:
                if player.id not in allowed_players_by_id:
                    allowed_players_by_id[player.id] = player
        return allowed_players_by_id

    @property
    def allowed_players(self) -> Collection[Player]:
        return self.allowed_players_by_id.values()

    @property
    def sorted_allowed_players(self) -> list[Player]:
        return sorted(self.allowed_players, key=by('full_name'))

    # ---------------------------------------------------------------------------------
    # Application
    # ---------------------------------------------------------------------------------

    @property
    def can_manage_application_settings(self) -> bool:
        """Returns true if the client can manage the application settings."""
        return AuthAction.MANAGE_APPLICATION_SETTINGS in self.allowed_actions

    @property
    def can_manage_source_databases(self) -> bool:
        """Returns true if the client can manage the source databases."""
        return AuthAction.MANAGE_SOURCE_DATABASES in self.allowed_actions

    # ---------------------------------------------------------------------------------
    # Events
    # ---------------------------------------------------------------------------------

    @property
    def can_view_private_events(self) -> bool:
        """Returns true if the client can view the private events."""
        return AuthAction.VIEW_PRIVATE_EVENTS in self.allowed_actions

    @property
    def can_view_passed_events(self) -> bool:
        """Returns true if the client can view passed events."""
        return AuthAction.VIEW_PASSED_EVENTS in self.allowed_actions

    @property
    def can_view_detailed_event_cards(self) -> bool:
        """Returns true if the client can view the details on the event cards."""
        return AuthAction.VIEW_DETAILED_EVENT_CARDS in self.allowed_actions

    @property
    def can_create_events(self) -> bool:
        """Returns true if the client can create and duplicate events."""
        return AuthAction.CREATE_EVENTS in self.allowed_actions

    @property
    def can_manage_events(self) -> bool:
        """Returns true if the client can manage the events."""
        return AuthAction.MANAGE_EVENTS in self.allowed_actions

    @property
    def can_rename_event(self) -> bool:
        """Returns true if the client can rename the event (change the URLs)."""
        return AuthAction.RENAME_EVENT in self.allowed_actions

    @property
    def can_update_event(self) -> bool:
        """Returns true if the client can update the event."""
        return AuthAction.UPDATE_EVENT in self.allowed_actions

    @property
    def can_view_event_config(self) -> bool:
        """Returns true if the client can the event config."""
        return AuthAction.VIEW_EVENT_CONFIG in self.allowed_actions

    # ---------------------------------------------------------------------------------
    # Accounts
    # ---------------------------------------------------------------------------------

    @cached_property
    def manageable_access_levels(self) -> list[AccessLevel]:
        """Returns the access levels the client can manage."""
        manageable_access_levels: set[AccessLevel] = set()
        for access_level in self.account.access_levels:
            manageable_access_levels |= access_level.manageable_access_levels()
        return [
            access_level
            for access_level in AccessLevelManager().objects()
            if access_level in manageable_access_levels
        ]

    def can_manage_access_level(self, access_level: AccessLevel) -> bool:
        """Returns True if the client can manage the access level."""
        return access_level in self.manageable_access_levels

    @property
    def can_manage_accounts(self) -> bool:
        """Returns true if the client can manage (add/update/delete) accounts
        (the client may not be able to manage all the accounts but there may
        be accounts that it can manage)."""
        return AuthAction.MANAGE_ACCOUNTS in self.allowed_actions

    @property
    def manageable_account_ids(self) -> list[int]:
        """Returns the IDs of the accounts that the client can manage
        (the client must manage all the access levels of the accounts)."""
        assert self.event is not None
        return [
            account.id
            for account in self.event.accounts_by_id.values()
            if all(
                access_level in self.manageable_access_levels
                for access_level in account.access_levels
            )
        ]

    def can_manage_account(self, account_id: int) -> bool:
        """Returns True if the client can manage the account."""
        return account_id in self.manageable_account_ids

    @property
    def can_manage_access_levels(self) -> bool:
        """Returns true if the client can manage at least one access level."""
        return bool(self.manageable_access_levels)

    # ---------------------------------------------------------------------------------
    # Tournaments
    # ---------------------------------------------------------------------------------

    @property
    def can_view_tournaments_tab(self) -> bool:
        """Returns true if the client can access the Tournaments tab and view the tournament cards."""
        return AuthAction.VIEW_TOURNAMENTS_TAB in self.allowed_actions

    @property
    def can_add_tournament(self) -> bool:
        """Returns true if the client can add a tournament to the event."""
        return AuthAction.ADD_TOURNAMENTS in self.allowed_actions

    @property
    def can_update_tournaments(self) -> bool:
        """Returns true if the client can update a tournament of the event."""
        return AuthAction.UPDATE_TOURNAMENTS in self.allowed_actions

    @property
    def can_delete_tournaments(self) -> bool:
        """Returns true if the client can delete a tournament of the event."""
        return AuthAction.DELETE_TOURNAMENTS in self.allowed_actions

    @property
    def can_publish_results(self) -> bool:
        """Returns true if the client can publish the results of tournaments (e.g.: to an external website)."""
        return AuthAction.PUBLISH_RESULTS in self.allowed_actions

    @property
    def can_publish_rules(self) -> bool:
        """Returns true if the client can publish the rules or tournaments (e.g.: to an external website)."""
        return AuthAction.PUBLISH_RULES in self.allowed_actions

    @property
    def can_download_fees(self) -> bool:
        """Returns true if the client can download the fees of tournaments (e.g.: from an external website)."""
        return AuthAction.DOWNLOAD_FEES in self.allowed_actions

    # ---------------------------------------------------------------------------------
    # Players
    # ---------------------------------------------------------------------------------

    @property
    def can_view_players_tab(self) -> bool:
        """Returns true if the client can access the Players tab."""
        return AuthAction.VIEW_PLAYERS_TAB in self.allowed_actions

    @property
    def can_add_player(self) -> bool:
        """Returns true if the client can add a player to the event
        (it may be impossible, e.g. the tournament is finished)."""
        return AuthAction.ADD_PLAYERS in self.allowed_actions

    @property
    def can_update_players(self) -> bool:
        """Returns true if the client can update the players
        (including with local or remote databases)."""
        return AuthAction.UPDATE_PLAYERS in self.allowed_actions

    @property
    def can_distribute_players(self) -> bool:
        """Returns true if the client can distribute the players in the tournaments."""
        return AuthAction.DISTRIBUTE_PLAYERS in self.allowed_actions

    def can_update_players_history(self, tournament_id: int) -> bool:
        """Returns True if the client can update the players's history."""
        return self.action_allowed_for_tournament(
            AuthAction.UPDATE_PLAYERS_HISTORY, tournament_id
        )

    @property
    def can_delete_players(self) -> bool:
        """Returns true if the client can delete players of the event
        (it may be impossible, e.g. if they have no game)."""
        return AuthAction.DELETE_PLAYERS in self.allowed_actions

    # ---------------------------------------------------------------------------------
    # Check-in
    # ---------------------------------------------------------------------------------

    def can_open_close_check_in(self, tournament_id: int) -> bool:
        """Returns true if the client can open and close the check-in for the tournament."""
        return self.action_allowed_for_tournament(
            AuthAction.OPEN_CLOSE_CHECK_IN, tournament_id
        )

    def can_check_in_players(self, tournament_id: int) -> bool:
        """Returns True if the client can check-in players for a tournament."""
        return self.action_allowed_for_tournament(
            AuthAction.CHECK_IN_PLAYERS, tournament_id
        )

    # ---------------------------------------------------------------------------------
    # Pairings
    # ---------------------------------------------------------------------------------

    @property
    def can_view_pairings_tab(self) -> bool:
        """Returns true if the client can access the Pairings tab."""
        return AuthAction.VIEW_PAIRINGS_TAB in self.allowed_actions

    def can_use_pairing_engine(self, tournament_id: int) -> bool:
        """Returns True if the client can use the pairing engine for a tournament."""
        return self.action_allowed_for_tournament(
            AuthAction.USE_PAIRING_ENGINE, tournament_id
        )

    def can_manually_pair_players(self, tournament_id: int) -> bool:
        """Returns True if the client can manually pair players for a tournament."""
        return self.action_allowed_for_tournament(
            AuthAction.MANUALLY_PAIR_PLAYERS, tournament_id
        )

    def can_unpair_round(self, tournament_id: int) -> bool:
        """Returns True if the client can unpair all the boards of a round."""
        return self.action_allowed_for_tournament(
            AuthAction.UNPAIR_ROUND, tournament_id
        )

    def can_unpair_boards(self, tournament_id: int) -> bool:
        """Returns True if the client can individually unpair the boards of a tournament."""
        return self.action_allowed_for_tournament(
            AuthAction.UNPAIR_BOARD, tournament_id
        )

    def can_permute_boards(self, tournament_id: int) -> bool:
        """Returns True if the client can permute paired players of a tournament."""
        return self.action_allowed_for_tournament(
            AuthAction.PERMUTE_BOARD, tournament_id
        )

    def can_set_current_round(self, tournament_id: int) -> bool:
        """Returns True if the client can set the current round of a tournament."""
        return self.action_allowed_for_tournament(
            AuthAction.SET_CURRENT_ROUND, tournament_id
        )

    @cached_property
    def _set_zpb_allowed_tournament_ids(self) -> list[int]:
        return [
            tournament.id
            for tournament in self.allowed_tournaments_for_action(AuthAction.SET_ZPB)
        ]

    def can_set_zero_point_bye(self, tournament_id: int) -> bool:
        """Returns True if the client can set a zero point bye to a player."""
        return tournament_id in self._set_zpb_allowed_tournament_ids

    def can_set_half_point_bye(self, tournament_id: int) -> bool:
        """Returns True if the client can set a half point bye to a player."""
        return self.action_allowed_for_tournament(AuthAction.SET_HPB, tournament_id)

    def can_set_full_point_bye(self, tournament_id: int) -> bool:
        """Returns True if the client can set a full point bye to a player."""
        return self.action_allowed_for_tournament(AuthAction.SET_FPB, tournament_id)

    # ---------------------------------------------------------------------------------
    # Results
    # ---------------------------------------------------------------------------------

    def can_enter_results(self, tournament_id: int) -> bool:
        """Returns True if the client can enter results for a tournament."""
        return self.action_allowed_for_tournament(
            AuthAction.ENTER_RESULTS, tournament_id
        )

    def can_update_results(self, tournament_id: int) -> bool:
        """Returns True if the client can update previously entered results."""
        return self.action_allowed_for_tournament(
            AuthAction.UPDATE_RESULTS, tournament_id
        )

    def can_set_special_results(self, tournament_id: int) -> bool:
        """Returns True if the client can set special results (such as O.0-F, 0.0-0.5)."""
        return self.action_allowed_for_tournament(
            AuthAction.SET_SPECIAL_RESULTS, tournament_id
        )

    def can_set_illegal_moves(self, tournament_id: int) -> bool:
        """Returns True if the client can set illegal moves."""
        return self.action_allowed_for_tournament(
            AuthAction.SET_ILLEGAL_MOVES, tournament_id
        )

    def imputable_results_for_tournament(
        self, tournament_id: int
    ) -> tuple[Result, ...]:
        if self.can_set_special_results(tournament_id):
            return Result.admin_imputable_results()
        else:
            return Result.user_imputable_results()

    # ---------------------------------------------------------------------------------
    # Screens
    # ---------------------------------------------------------------------------------

    @property
    def can_manage_screens(self) -> bool:
        """Returns true if the client can manage the screens of the event."""
        return AuthAction.MANAGE_SCREENS in self.allowed_actions

    @property
    def can_view_private_screens(self) -> bool:
        """Returns true if the client can view private screens."""
        return AuthAction.VIEW_PRIVATE_SCREENS in self.allowed_actions

    @property
    def can_view_public_screens(self) -> bool:
        """Returns true if the client can view public screens."""
        return AuthAction.VIEW_PUBLIC_SCREENS in self.allowed_actions

    # ---------------------------------------------------------------------------------
    # Prizes
    # ---------------------------------------------------------------------------------

    @property
    def can_view_prizes_tab(self) -> bool:
        """Returns true if the client can access the Prizes tab."""
        return AuthAction.VIEW_PRIZES_TAB in self.allowed_actions

    @property
    def can_manage_prizes(self) -> bool:
        """Returns a dict indicating if the client can
        manage the prizes."""
        return AuthAction.MANAGE_PRIZES in self.allowed_actions

    # ---------------------------------------------------------------------------------
    # Documents
    # ---------------------------------------------------------------------------------

    @property
    def can_generate_documents(self) -> bool:
        """Returns true if the client can generate documents."""
        return AuthAction.GENERATE_DOCUMENTS in self.allowed_actions

import copy
from datetime import datetime, timedelta
from functools import cached_property
from typing import Annotated, Any

from litestar import get, post, patch, delete
from litestar.enums import RequestEncodingType
from litestar.exceptions import ClientException, NotFoundException
from litestar.params import Body, FromPath, QueryParameter, FromQuery
from litestar.response import Redirect
from litestar.status_codes import HTTP_200_OK
from litestar_htmx import HTMXRequest, ClientRedirect, HTMXTemplate

from common import SharlyChessException
from common.i18n import _, ngettext
from common.logger import get_logger
from data.access_levels.actions import AuthAction
from data.event import Event
from data.loader import EventLoader
from data.player import TournamentPlayer
from data.tournament import Tournament
from database.sqlite.event.event_database import EventDatabase
from plugins.manager import plugin_manager
from plugins.sce import PLUGIN_NAME, SCE_BASE_URL, SCE_SYNC_DELAY, SCE_UPLOAD_DELAY
from plugins.sce.sce_background_synchronizer import (
    schedule_sync,
    remove_scheduled_sync,
    is_sync_ongoing,
    is_sync_scheduled,
)
from plugins.sce.sce_background_uploader import (
    schedule_upload,
    upload_event_tournaments,
    remove_scheduled_upload,
)
from plugins.sce.sce_data import (
    SCETokens,
    SCEEventPluginData,
    SCETournamentSyncData,
    SCEPlayerSyncData,
)
from plugins.sce.sce_session import SCESession
from plugins.sce.sce_sync_status import SuccessSCESyncStatus
from plugins.sce.utils import SCEUtils
from web.controllers.admin.base_admin_controller import (
    BaseAdminController,
    AdminWebContext,
)
from web.controllers.admin.player_admin_controller import (
    PlayerAdminController,
    PlayerAdminWebContext,
)
from web.controllers.base_controller import WebContext
from web.guards import ActionGuard, EventGuard, TournamentActionGuard
from web.messages import Message
from web.urls import build_internal_get_url, index_url, admin_event_url
from web.utils import PKCEUtils

logger = get_logger()


CODE_VERIFIER_EXPIRATION_DELAY = 5


class SCEWebContext(AdminWebContext):
    def __init__(
        self,
        request: HTMXRequest,
        tournament_id: int | None = None,
        player_id: int | None = None,
        reload_event: bool = False,
    ):
        super().__init__(request, reload_event=reload_event)
        event = self.get_admin_event()
        self.tournament: Tournament | None = None
        if tournament_id:
            try:
                self.tournament = event.tournaments_by_id[tournament_id]
            except KeyError:
                raise NotFoundException(f'Tournament [{tournament_id}] not found.')
        self.player: TournamentPlayer | None = None
        if player_id:
            try:
                self.player = event.players_by_id[player_id].single_tournament_player
            except KeyError:
                raise NotFoundException(f'Player [{player_id}] not found.')

    def get_tournament(self) -> Tournament:
        assert self.tournament is not None
        return self.tournament

    def get_player(self) -> TournamentPlayer:
        assert self.player is not None
        return self.player

    @property
    def sync_modal_context(self) -> dict[str, Any]:
        event = self.get_admin_event()

        plugin_data = SCEUtils.get_event_plugin_data(event)
        new_sce_tournament_options = copy.copy(plugin_data.tournament_names_by_id)
        new_local_tournament_options: dict[int, str] = {}
        for tournament in event.tournaments:
            sce_id = SCEUtils.get_tournament_plugin_data(tournament).id
            if sce_id and sce_id in new_sce_tournament_options:
                del new_sce_tournament_options[sce_id]
            elif tournament in self.allowed_tournaments:
                new_local_tournament_options[tournament.id] = tournament.name
        player_duplicate_count = 0
        for tournament in self.sce_allowed_tournaments:
            player_duplicate_count += len(
                SCEUtils.get_tournament_plugin_data(tournament).duplicated_players_by_id
            )
            for player in tournament.tournament_players:
                if SCEUtils.get_player_plugin_data(player).is_duplicated:
                    player_duplicate_count += 1

        return self.table_context | {
            'new_sce_tournament_options': new_sce_tournament_options,
            'new_local_tournament_options': new_local_tournament_options,
            'tournament_conflict_count': len(self.sce_tournaments_with_conflicts),
            'player_conflict_count': len(self.sce_players_with_conflicts),
            'sce_last_sync_status': SCEUtils.resolve_last_sync_status(event),
            'is_sync_ongoing': is_sync_ongoing(event.uniq_id),
            'player_duplicate_count': player_duplicate_count,
        }

    @property
    def table_context(self) -> dict[str, Any]:
        return self.template_context | {
            'sce_allowed_tournaments': self.sce_allowed_tournaments,
        }

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'sce_event_status': SCEUtils.resolve_event_status(self.get_admin_event()),
            'tournament': self.tournament,
            'SCE_BASE_URL': SCE_BASE_URL,
            'SCE_SYNC_DELAY': SCE_SYNC_DELAY,
            'SCE_UPLOAD_DELAY': SCE_UPLOAD_DELAY,
            'sce_utils': SCEUtils,
        }

    @cached_property
    def sce_tournaments(self) -> list[Tournament]:
        return [
            tournament
            for tournament in self.get_admin_event().sorted_tournaments
            if SCEUtils.get_tournament_plugin_data(tournament).id
        ]

    @cached_property
    def allowed_tournaments(self) -> list[Tournament]:
        return self.client.allowed_tournaments_for_action(AuthAction.PUBLISH_RESULTS)

    @cached_property
    def sce_allowed_tournaments(self) -> list[Tournament]:
        return [
            tournament
            for tournament in self.sce_tournaments
            if tournament in self.allowed_tournaments
        ]

    @property
    def sce_tournaments_with_conflicts(self) -> list[Tournament]:
        return [
            tournament
            for tournament in self.sce_tournaments
            if SCEUtils.get_tournament_plugin_data(tournament).conflict_sync_data
        ]

    @property
    def sce_players_with_conflicts(self) -> list[TournamentPlayer]:
        players: list[TournamentPlayer] = []
        for tournament in self.sce_tournaments:
            for player in tournament.tournament_players:
                plugin_data = SCEUtils.get_player_plugin_data(player)
                if plugin_data.id and plugin_data.conflict_sync_data:
                    players.append(player)
        return players


class SCEAdminController(BaseAdminController):
    OAUTH_CODE_VERIFIER_BY_STATE: dict[str, tuple[str, datetime]] = {}
    publish_guards = [
        EventGuard(),
        TournamentActionGuard(AuthAction.PUBLISH_RESULTS),
    ]

    @staticmethod
    def _clean_outdated_tournament_conflicts(web_context: SCEWebContext):
        """Clean all the outdated tournament conflicts.
        Returns True if all the conflicts have been cleared."""
        event = web_context.get_admin_event()
        cleaned = 0
        conflict_tournaments = web_context.sce_tournaments_with_conflicts
        for tournament in conflict_tournaments:
            plugin_data = SCEUtils.get_tournament_plugin_data(tournament)
            if not plugin_data.conflict_sync_data or not plugin_data.last_sync_data:
                continue
            try:
                plugin_data.conflict_sync_data.merge_with_other_sync_data(
                    SCETournamentSyncData.from_tournament(tournament),
                    plugin_data.last_sync_data,
                )
                plugin_data.conflict_sync_data = None
                SCEUtils.update_tournament_plugin_data(tournament, plugin_data)
                cleaned += 1
            except SharlyChessException:
                pass
        if cleaned and cleaned == len(conflict_tournaments):
            schedule_sync(event, force=True)
            return True
        return False

    @staticmethod
    def _clean_outdated_player_conflicts(web_context: SCEWebContext):
        """Clean all the outdated player conflicts.
        Returns True if all the conflicts have been cleared."""
        cleaned = 0
        conflict_players = web_context.sce_players_with_conflicts
        for player in conflict_players:
            plugin_data = SCEUtils.get_player_plugin_data(player)
            if not plugin_data.conflict_sync_data or not plugin_data.last_sync_data:
                continue
            try:
                plugin_data.conflict_sync_data.merge_with_other_sync_data(
                    SCEPlayerSyncData.from_player(player),
                    plugin_data.last_sync_data,
                )
                plugin_data.conflict_sync_data = None
                SCEUtils.update_player_plugin_data(player, plugin_data)
                cleaned += 1
            except SharlyChessException:
                pass
        if cleaned and cleaned == len(conflict_players):
            return True
        return False

    @classmethod
    def trigger_oauth(
        cls,
        request: HTMXRequest,
        redirect_action: str,
        sce_event_id: str | None = None,
        event_uniq_id: str | None = None,
    ):
        state = PKCEUtils.generate_state()
        code_verifier = PKCEUtils.generate_code_verifier()
        code_expires_at = datetime.now() + timedelta(
            minutes=CODE_VERIFIER_EXPIRATION_DELAY
        )
        cls.OAUTH_CODE_VERIFIER_BY_STATE[state] = code_verifier, code_expires_at
        route_params = {'action': redirect_action}
        if event_uniq_id:
            route_params['event_uniq_id'] = event_uniq_id
        redirect_uri = build_internal_get_url(
            request, 'sce-oauth-callback', route_params=route_params
        )
        oauth_url = SCESession.build_oauth_url(
            redirect_uri=redirect_uri,
            code_challenge=PKCEUtils.generate_code_challenge(code_verifier),
            state=state,
            event_id=sce_event_id,
        )
        logger.info('Sharly-Chess.com OAuth ongoing')
        logger.debug(
            'Sharly-Chess.com OAuth - code verifier: %s, expires at: %s, url: %s',
            code_verifier,
            code_expires_at.isoformat(),
            oauth_url,
        )
        return ClientRedirect(oauth_url)

    @get(
        path='/sce/oauth/event-import',
        name='sce-oauth-event-import',
        guard=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_sce_oauth_event_import(self, request: HTMXRequest) -> ClientRedirect:
        return self.trigger_oauth(request, redirect_action='import-event')

    @get(
        path='/sce/oauth/event-connect/{event_uniq_id:str}',
        name='sce-oauth-event-connect',
        guard=publish_guards,
    )
    async def htmx_sce_oauth_event_connect(
        self, request: HTMXRequest
    ) -> ClientRedirect:
        event = SCEWebContext(request).get_admin_event()
        return self.trigger_oauth(
            request,
            redirect_action='connect-event',
            sce_event_id=SCEUtils.get_event_plugin_data(event).id,
            event_uniq_id=event.uniq_id,
        )

    @classmethod
    def _import_event(cls, sce_event_id: str, tokens: SCETokens) -> Event:
        uniq_id = EventLoader().get_unused_event_uniq_id(sce_event_id)
        EventDatabase(uniq_id).create()
        try:
            event = EventLoader().load_event(uniq_id)
            plugin_data = SCEEventPluginData(
                id=sce_event_id,
                tokens=tokens,
                last_sync_at=datetime.now(),
                last_sync_attempt_status=SuccessSCESyncStatus().id,
            )
            event.plugin_data[PLUGIN_NAME] = plugin_data
            event.stored_event.plugin_data[PLUGIN_NAME] = plugin_data.to_stored_value()
            session = SCESession(event)
            session.update_event_from_sce_event(is_create=True)
            return session.event
        finally:
            EventDatabase(uniq_id).file.unlink(missing_ok=True)

    @get(
        path=[
            '/sce/oauth/callback/{action:str}',
            '/sce/oauth/callback/{action:str}/{event_uniq_id:str}',
        ],
        name='sce-oauth-callback',
    )
    async def htmx_sce_oauth_callback(
        self,
        request: HTMXRequest,
        action: FromPath[str],
        event_uniq_id: FromPath[str | None],
        state_param: Annotated[str, QueryParameter(name='state')],
        sce_event_id: Annotated[str, QueryParameter(name='event_id')] = '',
        code: FromQuery[str] = '',
        error: FromQuery[str] = '',
    ) -> Redirect:
        error_message: str | None = None
        tokens: SCETokens | None = None
        if not sce_event_id:
            error_message = _('Sharly-Chess.com authorization canceled.')
        elif error:
            logger.error(error)
            error_message = _(
                'Authorization failed, consult the logs for more details.'
            )
        elif state_param not in self.OAUTH_CODE_VERIFIER_BY_STATE:
            error_message = _('Authorization failed, possible CSRF attack!')
        elif not code:
            raise ClientException('Missing parameter: code')
        else:
            code_verifier, expires_at = self.OAUTH_CODE_VERIFIER_BY_STATE[state_param]
            if expires_at < datetime.now():
                error_message = _('Authorization expired, please try again.')
            try:
                tokens = SCESession.get_tokens_from_code(
                    code, code_verifier, str(request.url).split('?')[0]
                )
            except SharlyChessException:
                error_message = _(
                    'Authorization failed, consult the logs for more details.'
                )
        if not tokens:
            Message.error(request, error_message or '')
        else:
            logger.info('Sharly-Chess.com OAuth successful')
            match action:
                case 'import-event':
                    try:
                        event = self._import_event(sce_event_id, tokens)
                        for plugin in plugin_manager.enable_missing_plugins(
                            event.stored_event.enabled_plugins
                        ):
                            Message.warning(
                                request,
                                _('Plugin [{plugin}] was enabled.').format(
                                    plugin=plugin.name
                                ),
                            )
                        Message.success(
                            request,
                            _('Event [{event}] successfully imported!').format(
                                event=event.name
                            ),
                        )
                        event_uniq_id = event.uniq_id
                    except SharlyChessException as e:
                        logger.exception(e)
                        Message.error(
                            request,
                            _('An error occurred, consult the logs for more details.'),
                        )
                case 'connect-event':
                    web_context = SCEWebContext(request)
                    event = web_context.get_admin_event()
                    plugin_data = SCEUtils.get_event_plugin_data(event)
                    plugin_data.id = sce_event_id
                    plugin_data.tokens = tokens
                    SCEUtils.update_event_plugin_data(event, plugin_data, write=False)
                    try:
                        SCESession(event).update_event_from_sce_event()
                        SCEUtils.clear_auth_error_statuses(event)
                        Message.success(
                            request,
                            _(
                                'Event [{event}] successfully connected to Sharly-Chess.com!'
                            ).format(event=event.name),
                        )
                    except SharlyChessException as e:
                        logger.exception(e)
                        Message.error(
                            request,
                            _('An error occurred, consult the logs for more details.'),
                        )
                case _:
                    raise NotFoundException(f'Unknown action [{action}]')
        return Redirect(
            admin_event_url(request, event_uniq_id)
            if event_uniq_id
            else index_url(request)
        )

    @classmethod
    def _render_sync_modal(
        cls,
        web_context: SCEWebContext,
        message: str | None = None,
        message_type: str | None = None,
    ) -> HTMXTemplate:
        return cls._render_modal(
            template_name='/sce_sync_modal.html',
            template_context=web_context.sync_modal_context
            | {
                'message': message,
                'message_type': message_type,
            },
        )

    @get(
        path='/sce/sync-modal/{event_uniq_id:str}',
        name='sce-sync-modal',
        guards=publish_guards,
    )
    async def htmx_sce_sync_modal(
        self,
        request: HTMXRequest,
        no_refresh: FromQuery[bool] = False,
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request)
        message: str | None = None
        if not no_refresh:
            event = web_context.get_admin_event()
            has_player_conflicts = bool(web_context.sce_players_with_conflicts)
            try:
                # Update the event status / ensure all links will work in case slugs have changed
                SCESession(event).update_event_from_sce_event(
                    update_tournament_conflicts=True,
                    update_player_conflicts=has_player_conflicts,
                )
            except SharlyChessException as e:
                logger.exception(e)
            plugin_data = SCEUtils.get_event_plugin_data(event)
            if plugin_data.auto_player_sync and not is_sync_scheduled(event.uniq_id):
                schedule_sync(event)

            self._clean_outdated_tournament_conflicts(web_context)
            if has_player_conflicts and self._clean_outdated_player_conflicts(
                web_context
            ):
                message = _('All player conflicts resolved.')
        return self._render_sync_modal(web_context, message)

    @staticmethod
    def _render_upload_table(web_context: SCEWebContext) -> HTMXTemplate:
        return HTMXTemplate(
            template_name='/sce_upload_table.html',
            context=web_context.table_context,
            re_target='#sce-upload-table',
            re_swap='outerHTML',
        )

    @patch(
        path='/sce/update-event-auto-player-sync/{event_uniq_id:str}',
        name='sce-update-event-auto-player-sync',
        guards=publish_guards,
    )
    async def htmx_sce_update_event_auto_player_sync(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request)
        event = web_context.get_admin_event()
        plugin_data = SCEUtils.get_event_plugin_data(event)
        auto_sync = WebContext.form_data_to_bool(data, 'auto_player_sync')
        plugin_data.auto_player_sync = auto_sync
        if auto_sync:
            schedule_sync(event)
        else:
            remove_scheduled_sync(event.uniq_id)
        SCEUtils.update_event_plugin_data(event, plugin_data)

        return HTMXTemplate(template_name='/common/empty.html', re_swap='none')

    @patch(
        path='/sce/update-event-auto-upload/{event_uniq_id:str}',
        name='sce-update-event-auto-upload',
        guards=publish_guards,
    )
    async def htmx_sce_update_event_auto_upload(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request)
        event = web_context.get_admin_event()
        plugin_data = SCEUtils.get_event_plugin_data(event)
        plugin_data.auto_upload = WebContext.form_data_to_bool(data, 'auto_upload')
        SCEUtils.update_event_plugin_data(event, plugin_data)
        for tournament in web_context.sce_tournaments:
            if not SCEUtils.get_tournament_plugin_data(tournament).auto_upload:
                continue
            if plugin_data.auto_upload:
                if SCEUtils.tournament_modified_since_last_upload(tournament):
                    schedule_upload(tournament)
            else:
                remove_scheduled_upload(tournament)
        return self._render_upload_table(web_context)

    @patch(
        path='/sce/update-tournament-auto-upload/{event_uniq_id:str}/{tournament_id:int}',
        name='sce-update-tournament-auto-upload',
        guards=publish_guards,
    )
    async def htmx_sce_update_tournament_auto_upload(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request, tournament_id)
        tournament = web_context.get_tournament()

        plugin_data = SCEUtils.get_tournament_plugin_data(tournament)
        plugin_data.auto_upload = WebContext.form_data_to_bool(
            data, f'tournament_auto_upload_{tournament.id}'
        )
        SCEUtils.update_tournament_plugin_data(tournament, plugin_data)
        if plugin_data.auto_upload:
            if SCEUtils.tournament_modified_since_last_upload(tournament):
                schedule_upload(tournament)
        else:
            remove_scheduled_upload(tournament)
        return HTMXTemplate(
            template_name='/sce_tournament_statuses.html',
            context=web_context.table_context,
            re_target=f'#tournament-upload-statuses-{tournament.id}',
            re_swap='innerHTML',
        )

    @post(
        path='/sce/upload-tournament-results/{event_uniq_id:str}/{tournament_id:int}',
        name='sce-upload-tournament-results',
        guards=publish_guards,
    )
    async def htmx_sce_upload_tournament_results(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request, tournament_id)
        tournament = web_context.get_tournament()
        schedule_upload(tournament, True)
        return HTMXTemplate(template_name='/common/empty.html', re_swap='none')

    @post(
        path='/sce/upload-all-tournament-results/{event_uniq_id:str}',
        name='sce-upload-all-tournament-results',
        guards=publish_guards,
    )
    async def htmx_sce_upload_all_tournament_results(
        self, request: HTMXRequest
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request)
        upload_event_tournaments(web_context.sce_allowed_tournaments)
        return HTMXTemplate(template_name='/common/empty.html', re_swap='none')

    @post(
        path='/sce/sync-players/{event_uniq_id:str}',
        name='sce-sync-players',
        guards=publish_guards,
    )
    async def htmx_sce_sync_players(self, request: HTMXRequest) -> HTMXTemplate:
        web_context = SCEWebContext(request)
        event = web_context.get_admin_event()
        schedule_sync(event, force=True)
        return HTMXTemplate(template_name='/common/empty.html', re_swap='none')

    @classmethod
    def _render_tournament_conflict_modal(
        cls, web_context: SCEWebContext, error_message: str | None = None
    ) -> HTMXTemplate:
        event = web_context.get_admin_event()
        try:
            SCESession(event).update_event_from_sce_event(
                update_tournament_conflicts=True,
            )
        except SharlyChessException as e:
            logger.exception(e)
        cls._clean_outdated_tournament_conflicts(web_context)
        conflict_tournaments = web_context.sce_tournaments_with_conflicts
        if not conflict_tournaments:
            schedule_sync(event, force=True)
            return cls._render_sync_modal(web_context)
        tournament = conflict_tournaments[0]
        plugin_data = SCEUtils.get_tournament_plugin_data(tournament)
        return cls._render_modal(
            template_name='/sce_tournament_conflict_modal.html',
            template_context=web_context.template_context
            | {
                'conflict_tournament': tournament,
                'local_sync_data': SCETournamentSyncData.from_tournament(tournament),
                'sce_sync_data': plugin_data.conflict_sync_data,
                'last_sync_data': plugin_data.last_sync_data,
                'event_plugin_data': SCEUtils.get_event_plugin_data(event),
                'remaining_conflicts': len(conflict_tournaments),
                'error_message': error_message,
                'diff_fields': SCETournamentSyncData.diff_fields_by_property_name(),
            },
        )

    @get(
        path='/sce/tournament-conflict-modal/{event_uniq_id:str}',
        name='sce-tournament-conflict-modal',
        guards=publish_guards,
    )
    async def htmx_sce_tournament_conflict_modal(
        self, request: HTMXRequest
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request)
        return self._render_tournament_conflict_modal(web_context)

    @post(
        path='/sce/resolve-tournament-conflict/{event_uniq_id:str}/{tournament_id:int}/{choice:str}',
        name='sce-resolve-tournament-conflict',
        guards=publish_guards,
    )
    async def htmx_sce_resolve_tournament_conflict(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        choice: FromPath[str],
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request, tournament_id)
        event = web_context.get_admin_event()
        tournament = web_context.get_tournament()
        plugin_data = SCEUtils.get_tournament_plugin_data(tournament)
        if (
            not plugin_data.id
            or not plugin_data.last_sync_data
            or not plugin_data.conflict_sync_data
        ):
            raise ClientException('Tournament is not a SC.com conflict tournament')

        if choice == 'local':
            resolve_sync_data = SCETournamentSyncData.from_tournament(tournament)
        elif choice == 'sce':
            resolve_sync_data = plugin_data.conflict_sync_data
        elif choice == 'last-sync':
            resolve_sync_data = plugin_data.last_sync_data
        else:
            raise ClientException(f'Unknown choice: {choice}')
        error_message: str | None = None
        try:
            SCESession(event).update_sce_tournament(resolve_sync_data, plugin_data.id)
            resolve_sync_data.augment_stored_tournament(
                tournament.stored_tournament, event
            )
            plugin_data.last_sync_data = resolve_sync_data

            plugin_data.conflict_sync_data = None
            SCEUtils.update_tournament_plugin_data(
                tournament, plugin_data, write_stored_object=True
            )
        except SharlyChessException as e:
            logger.exception(e)
            error_message = _('An error occurred, consult the logs for more details.')

        return self._render_tournament_conflict_modal(web_context, error_message)

    @classmethod
    def _render_player_conflict_modal(
        cls, web_context: SCEWebContext, error_message: str | None = None
    ) -> HTMXTemplate:
        event = web_context.get_admin_event()
        try:
            SCESession(event).update_event_from_sce_event(
                update_player_conflicts=True,
            )
        except SharlyChessException as e:
            logger.exception(e)
        cls._clean_outdated_player_conflicts(web_context)
        conflict_players = web_context.sce_players_with_conflicts
        if not conflict_players:
            return cls._render_sync_modal(
                web_context, _('All player conflicts resolved.')
            )
        player = conflict_players[0]
        plugin_data = SCEUtils.get_player_plugin_data(player)
        return cls._render_modal(
            template_name='/sce_player_conflict_modal.html',
            template_context=web_context.template_context
            | {
                'conflict_player': player,
                'local_sync_data': SCEPlayerSyncData.from_player(player),
                'sce_sync_data': plugin_data.conflict_sync_data,
                'last_sync_data': plugin_data.last_sync_data,
                'event_plugin_data': SCEUtils.get_event_plugin_data(event),
                'remaining_conflicts': len(conflict_players),
                'error_message': error_message,
                'diff_fields': SCEPlayerSyncData.diff_fields_by_property_name(event),
            },
        )

    @get(
        path='/sce/player-conflict-modal/{event_uniq_id:str}',
        name='sce-player-conflict-modal',
        guards=publish_guards,
    )
    async def htmx_sce_player_conflict_modal(
        self, request: HTMXRequest
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request)
        return self._render_player_conflict_modal(web_context)

    @post(
        path='/sce/resolve-player-conflict/{event_uniq_id:str}/{player_id:int}/{choice:str}',
        name='sce-resolve-player-conflict',
        guards=publish_guards,
    )
    async def htmx_sce_resolve_player_conflict(
        self,
        request: HTMXRequest,
        player_id: FromPath[int],
        choice: FromPath[str],
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request, player_id=player_id)
        event = web_context.get_admin_event()
        player = web_context.get_player()
        plugin_data = SCEUtils.get_player_plugin_data(player)
        if (
            not plugin_data.id
            or not plugin_data.last_sync_data
            or not plugin_data.conflict_sync_data
        ):
            raise ClientException('Player is not a SC.com conflict player')

        if choice == 'local':
            resolve_sync_data = SCEPlayerSyncData.from_player(player)
        elif choice == 'sce':
            resolve_sync_data = plugin_data.conflict_sync_data
        elif choice == 'last-sync':
            resolve_sync_data = plugin_data.last_sync_data
        else:
            raise ClientException(f'Unknown choice: {choice}')
        error_message: str | None = None
        try:
            session = SCESession(event)
            session.update_sce_player(
                resolve_sync_data,
                plugin_data.conflict_sync_data.tournament_id,
                plugin_data.id,
            )
            session.update_local_player(player, resolve_sync_data)
            plugin_data.last_sync_data = resolve_sync_data

            plugin_data.conflict_sync_data = None
            SCEUtils.update_player_plugin_data(
                player, plugin_data, write_stored_object=True
            )
        except SharlyChessException as e:
            logger.exception(e)
            error_message = _('An error occurred, consult the logs for more details.')

        return self._render_player_conflict_modal(web_context, error_message)

    @post(
        path='/sce/import-tournament/{event_uniq_id:str}/{sce_tournament_id:str}',
        name='sce-import-tournament',
        guards=publish_guards,
    )
    async def htmx_sce_import_tournament(
        self,
        request: HTMXRequest,
        sce_tournament_id: FromPath[str],
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request)
        event = web_context.get_admin_event()
        message_type: str | None = None
        try:
            SCESession(event).import_tournaments([sce_tournament_id])
            message = _('Tournament successfully imported.')
            plugin_data = SCEUtils.get_event_plugin_data(event)
            if not plugin_data.last_sync_at:
                plugin_data.last_sync_at = datetime.now()
                SCEUtils.update_event_plugin_data(event, plugin_data)
            web_context = SCEWebContext(request, reload_event=True)
        except SharlyChessException as e:
            logger.exception(e)
            message = _('Tournament import failed, consult the logs for more details.')
            message_type = 'error'
        return self._render_sync_modal(web_context, message, message_type)

    @post(
        path='/sce/upload-local-tournament/{event_uniq_id:str}/{tournament_id:int}',
        name='sce-upload-local-tournament',
        guards=publish_guards,
    )
    async def htmx_sce_upload_local_tournament(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request, tournament_id)
        event = web_context.get_admin_event()
        tournament = web_context.get_tournament()
        session = SCESession(event)
        message_type: str | None = None
        try:
            duplicate_count = session.create_sce_tournament(tournament)
            message = _('Tournament [{tournament}] successfully uploaded.').format(
                tournament=tournament.name
            )
            if duplicate_count:
                message += ' ' + ngettext(
                    '{count} duplicated player detected.',
                    '{count} duplicated players detected.',
                    duplicate_count,
                ).format(count=duplicate_count)
                message_type = 'warning'
            plugin_data = SCEUtils.get_event_plugin_data(event)
            if not plugin_data.last_sync_at:
                plugin_data.last_sync_at = datetime.now()
                SCEUtils.update_event_plugin_data(event, plugin_data)
        except SharlyChessException as e:
            logger.exception(e)
            message_type = 'error'
            message = _(
                'Error while uploading tournament [{tournament}], '
                'consult the logs for more details.'
            ).format(tournament=tournament.name)
        return self._render_sync_modal(web_context, message, message_type)

    @classmethod
    def _render_player_duplicate_modal(
        cls,
        web_context: SCEWebContext,
        message: str | None = None,
        message_type: str | None = None,
    ) -> HTMXTemplate:
        local_tournaments_with_duplicates = [
            tournament
            for tournament in web_context.sce_allowed_tournaments
            if any(
                SCEUtils.get_player_plugin_data(player).is_duplicated
                for player in tournament.tournament_players
            )
        ]
        sce_tournaments_with_duplicates = [
            tournament
            for tournament in web_context.sce_allowed_tournaments
            if SCEUtils.get_tournament_plugin_data(tournament).duplicated_players_by_id
        ]
        if (
            not local_tournaments_with_duplicates
            and not sce_tournaments_with_duplicates
        ):
            return cls._render_sync_modal(
                web_context, _('All player duplicates resolved.')
            )

        template_context = web_context.template_context
        template_context |= {
            'message': message,
            'message_type': message_type,
            'local_tournaments_with_duplicates': local_tournaments_with_duplicates,
            'sce_tournaments_with_duplicates': sce_tournaments_with_duplicates,
        }
        return cls._render_modal(
            '/sce_player_duplicate_modal.html',
            template_context=template_context,
        )

    @get(
        path='/sce/player-duplicate-modal/{event_uniq_id:str}',
        name='sce-player-duplicate-modal',
        guards=publish_guards,
    )
    async def htmx_sce_player_duplicate_modal(
        self, request: HTMXRequest
    ) -> HTMXTemplate:
        return self._render_player_duplicate_modal(SCEWebContext(request))

    @delete(
        path='/sce/delete-local-player/{event_uniq_id:str}/{player_id:int}',
        name='sce-delete-local-player',
        status_code=HTTP_200_OK,
        guards=publish_guards,
    )
    async def htmx_sce_delete_local_player(
        self,
        request: HTMXRequest,
        player_id: FromPath[int],
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request, player_id=player_id)
        event = web_context.get_admin_event()
        player = web_context.get_player()
        if player.has_real_pairings:
            raise ClientException(f'Player [{player.full_name}] is not deletable')
        event.delete_player(player)
        web_context = SCEWebContext(request, reload_event=True)
        return self._render_player_duplicate_modal(
            web_context, _('Player [{player}] deleted.').format(player=player.full_name)
        )

    @delete(
        path='/sce/delete-sce-player/{event_uniq_id:str}/{tournament_id:int}/{sce_player_id:str}',
        name='sce-delete-sce-player',
        status_code=HTTP_200_OK,
        guards=publish_guards,
    )
    async def htmx_sce_delete_sce_player(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        sce_player_id: FromPath[str],
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request, tournament_id)
        event = web_context.get_admin_event()
        tournament = web_context.get_tournament()
        plugin_data = SCEUtils.get_tournament_plugin_data(tournament)
        sce_player = plugin_data.duplicated_players_by_id.get(sce_player_id)
        message: str | None = None
        message_type: str | None = None
        if sce_player:
            assert plugin_data.id is not None
            try:
                SCESession(event).delete_sce_player(plugin_data.id, sce_player_id)
                del plugin_data.duplicated_players_by_id[sce_player_id]
                SCEUtils.update_tournament_plugin_data(tournament, plugin_data)
                for player in event.players:
                    p_plugin_data = SCEUtils.get_player_plugin_data(player)
                    if p_plugin_data.duplicated_registration_id == sce_player_id:
                        p_plugin_data.duplicated_registration_id = None
                        SCEUtils.update_player_plugin_data(player, p_plugin_data)
                message = _('Player [{player}] deleted.')
            except SharlyChessException as e:
                logger.exception(e)
                message_type = 'error'
                message = _(
                    'Player [{player}] could not be deleted from Sharly-Chess.com.'
                )
            message = message.format(player=sce_player.full_name)
        return self._render_player_duplicate_modal(web_context, message, message_type)

    @post(
        path='/sce/toggle-tournament-check-in-open/{event_uniq_id:str}/{tournament_id:int}',
        name='sce-toggle-tournament-check-in-open',
        guards=publish_guards + [TournamentActionGuard(AuthAction.OPEN_CLOSE_CHECK_IN)],
    )
    async def htmx_sce_toggle_tournament_check_in_open(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        tournament_id: FromPath[int],
    ) -> HTMXTemplate:
        web_context = SCEWebContext(request, tournament_id=tournament_id)
        event = web_context.get_admin_event()
        tournament = web_context.get_tournament()
        check_in_open = web_context.form_data_to_bool(
            data, f'tournament_{tournament.id}_sce_check_in_open'
        )
        if (
            check_in_open
            != SCEUtils.get_tournament_plugin_data(tournament).check_in_open
        ):
            try:
                SCESession(event).toggle_tournament_check_in(tournament)
            except SharlyChessException as e:
                logger.exception(e)
                return PlayerAdminController.render_check_in_modal(
                    PlayerAdminWebContext(request),
                    message=_('An error occurred, consult the logs for more details.'),
                    message_type='error',
                )
        return HTMXTemplate(
            template_name='/common/empty.html',
            re_swap='none',
        )

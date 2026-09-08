from typing import TYPE_CHECKING, Iterable, Any

from packaging.version import Version

from common import SharlyChessException
from common.i18n import _
from common.logger import get_logger
from common.network import NetworkMonitor
from data.columns.column import Column
from data.event import Event
from data.loader import EventLoader
from data.print_documents import QRCodeType
from database.sqlite.event.event_database import EventDatabase
from plugins.hookspec import hookimpl, hookspec
from plugins.sce import PLUGIN_NAME
from plugins.sce.sce_admin_controller import SCEAdminController
from plugins.sce.sce_background_uploader import (
    should_schedule_auto_upload,
    schedule_upload,
)
from plugins.sce.sce_entity import SCECheckInColumn
from plugins.sce.sce_qr_codes import SCETournamentQRCodeType, SCEEventQRCodeType
from plugins.sce.sce_session import SCESession
from plugins.sce.sce_tournament_results_builder import SCEUploadColumn
from plugins.sce.sce_data import (
    SCETournamentPluginData,
    SCEEventPluginData,
    SCEPlayerPluginData,
    SCEPlayerSyncData,
)
from plugins.sce.utils import SCEUtils
from plugins.utils import (
    PluginData,
    NavDataTransferItem,
    Plugin,
    TournamentConnectionField,
)
from web.admin.collection import ListColumn
from web.controllers.base_controller import BaseController
from utils.enum import EventType

if TYPE_CHECKING:
    from data.event import Event
    from data.player import TournamentPlayer, Player
    from data.tournament import Tournament
    from database.sqlite.event.event_store import (
        StoredEvent,
        StoredTournament,
        StoredPlayer,
    )
    from web.admin.collection import AdminCollectionSpec

logger = get_logger()


class SCEPluginHooks:
    @hookspec
    def augment_sce_player_sync_data_from_player(
        self,
        player: 'TournamentPlayer',
        sync_data: SCEPlayerSyncData,
    ):
        """Augment SCE player shared data from a player."""

    @hookspec
    def augment_sce_player_sync_data_from_sce_data(
        self,
        sce_data: dict[str, Any],
        sync_data: SCEPlayerSyncData,
    ):
        """Augment SCE player shared data from SCE API data."""

    @hookspec
    def augment_stored_player_from_sce_player_sync_data(
        self,
        event: Event,
        stored_player: 'StoredPlayer',
        sync_data: SCEPlayerSyncData,
        database: EventDatabase | None,
    ):
        """Augment a stored player from SCE player shared data."""

    @hookspec
    def update_sce_player_diff_field_labels(self, diff_fields: dict[str, str | None]):
        """Update the labels of the fields used for the conflict modal."""

    @hookspec
    def add_sce_upload_player_custom_fields(
        self, custom_fields: dict[str, Any], player: 'TournamentPlayer'
    ):
        """Add custom fields to the SCE uploaded players."""

    @hookspec
    def alter_sce_upload_player_columns(self, columns: list[SCEUploadColumn]):
        """Alter the player columns of the SCE results upload."""

    @hookspec
    def alter_sce_upload_ranking_columns(self, columns: list[SCEUploadColumn]):
        """Alter the ranking columns of the SCE results upload."""


class SCEPlugin(Plugin):
    @staticmethod
    def static_id() -> str:
        return PLUGIN_NAME

    @property
    def supported_event_types(self) -> list[EventType]:
        return [EventType.INDIVIDUAL]

    @staticmethod
    def static_name() -> str:
        return 'Sharly-Chess.com'

    @property
    def version(self) -> Version:
        return Version('1.0.0')

    @property
    def description(self) -> str:
        return _(
            'Integration with the Sharly-Chess.com platform '
            '(online check-in, results upload, etc.).'
        )

    @property
    def keywords(self) -> list[str]:
        return ['sharly', 'online', 'registration', 'check-in', 'platform']

    @property
    def doc_markdown(self) -> str:
        return '\n\n'.join(
            [
                _(
                    'Sharly-Chess.com is the online platform of Sharly Chess, where '
                    'the players register to your events and follow them live.'
                ),
                _(
                    '- an event of the platform linked to your event, and its players '
                    'synchronised in both directions;\n'
                    '- the check-in of the players done online by the players '
                    'themselves;\n'
                    '- the pairings and the standings published live on the platform.'
                ),
            ]
        )

    @property
    def hookspecs(self) -> type | None:
        return SCEPluginHooks

    @property
    def default_is_enabled(self) -> bool:
        return True

    @property
    def default_event_is_enabled(self) -> bool:
        return False

    @property
    def event_form_script_template(self) -> str:
        return '/sce_event_form_script.js'

    @property
    def controllers(self) -> list[type[BaseController]]:
        return [SCEAdminController]

    def used_by_stored_tournament(
        self, stored_event: 'StoredEvent', stored_tournament: 'StoredTournament'
    ) -> bool:
        return bool(stored_tournament.plugin_data.get(PLUGIN_NAME, {}).get('id'))

    # ---------------------------------------------------------------------------------
    # Events
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_event_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, SCEEventPluginData

    @hookimpl
    def create_event_button_template(self) -> str:
        return '/sce_event_create_button.html'

    @hookimpl
    def on_event_duplicated(self, event_database: EventDatabase):
        # Erase all SCE plugin data
        stored_event = event_database.load_stored_event()
        if PLUGIN_NAME not in stored_event.enabled_plugins:
            return
        stored_event.plugin_data[PLUGIN_NAME] = {}
        # The plugin is only ever enabled by importing an event from
        # Sharly-Chess.com, so an enabled plugin means "this event is linked".
        # The duplicate is not, so disable it: otherwise the copy keeps
        # advertising itself as linked and the fields controlled from
        # Sharly-Chess.com stay locked for good.
        stored_event.enabled_plugins = [
            plugin_id
            for plugin_id in stored_event.enabled_plugins
            if plugin_id != PLUGIN_NAME
        ]
        event_database.update_stored_event(stored_event)
        for stored_tournament in stored_event.stored_tournaments:
            stored_tournament.plugin_data[PLUGIN_NAME] = {}
            event_database.update_stored_tournament(stored_tournament)
        for stored_player in stored_event.stored_players:
            stored_player.plugin_data[PLUGIN_NAME] = {}
            event_database.update_stored_player(stored_player)

    # ---------------------------------------------------------------------------------
    # Tournaments
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_tournament_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, SCETournamentPluginData

    @hookimpl
    def get_tournament_page_template_context(self) -> dict[str, Any]:
        return {'sce_utils': SCEUtils}

    @hookimpl
    def get_tournament_connection_field(
        self, tournament: 'Tournament'
    ) -> TournamentConnectionField | None:
        if not SCEUtils.get_tournament_plugin_data(tournament).id:
            return None
        return TournamentConnectionField(
            label=_('Sharly-Chess.com'),
            template='/sce_tournament_connection_value.html',
        )

    @hookimpl
    def extend_admin_collection(
        self,
        collection_key: str,
        collection_spec: 'AdminCollectionSpec',
        event: 'Event | None',
    ) -> None:
        if collection_key != 'tournaments':
            return
        collection_spec.ensure_list_column(
            ListColumn('transfer', label=_('Transfer')),
            before='actions',
        )

    @hookimpl
    def on_tournament_data_updated(
        self, stored_event: 'StoredEvent', stored_tournament: 'StoredTournament'
    ):
        # This hook being called for most database writes, it needs to be optimized
        if not should_schedule_auto_upload(stored_event, stored_tournament):
            return
        event = EventLoader().load_event(stored_event.uniq_id)
        tournament_id = stored_tournament.id
        assert tournament_id is not None
        tournament = event.tournaments_by_id[tournament_id]
        schedule_upload(tournament)

    @hookimpl
    def load_tournament_check_in_data(self, tournament: 'Tournament'):
        event = tournament.event
        epd = SCEUtils.get_event_plugin_data(event)
        tpd = SCEUtils.get_tournament_plugin_data(tournament)
        if tpd.id and tpd.check_in_open and epd.auto_player_sync:
            try:
                SCESession(event).sync_event()
            except SharlyChessException as e:
                logger.exception(e)

    # ---------------------------------------------------------------------------------
    # Player
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_player_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, SCEPlayerPluginData

    @hookimpl
    def on_player_deleted(self, player: 'Player'):
        for tournament in player.event.tournaments:
            t_plugin_data = SCEUtils.get_tournament_plugin_data(tournament)
            if not t_plugin_data.id:
                continue
            old_duplicates = t_plugin_data.duplicated_players_by_id
            new_duplicates = {
                sce_id: dup_player
                for sce_id, dup_player in old_duplicates.items()
                if dup_player.duplicate_player_id != player.id
            }
            if len(old_duplicates) != len(new_duplicates):
                t_plugin_data.duplicated_players_by_id = new_duplicates
                SCEUtils.update_tournament_plugin_data(tournament, t_plugin_data)
        sce_player_id = SCEUtils.get_player_plugin_data(player).id
        if not sce_player_id:
            return
        event = player.event
        plugin_data = SCEUtils.get_event_plugin_data(event)
        plugin_data.deleted_player_ids.append(sce_player_id)
        SCEUtils.update_event_plugin_data(event, plugin_data)

    @hookimpl
    def get_check_in_table_column(self) -> 'Column[Tournament]':
        return SCECheckInColumn()

    @hookimpl
    def on_before_load_tournaments_check_in_modal(self, event: Event):
        if SCEUtils.get_event_plugin_data(event).id and NetworkMonitor.connected():
            try:
                SCESession(event).update_event_check_in_schedules()
            except SharlyChessException as e:
                logger.exception(e)

    @hookimpl
    def validate_player_tournament_move(
        self, tournament: 'Tournament', player: 'TournamentPlayer'
    ):
        src_id = SCEUtils.get_tournament_plugin_data(player.tournament).id
        dst_id = SCEUtils.get_tournament_plugin_data(tournament).id
        if src_id and not dst_id:
            message = _(
                'Moving a player from a tournament synchronized with '
                'Sharly-Chess.com to non-synchronized tournament is not allowed.'
            )
            raise ValueError(message)

    @hookimpl
    def player_distribution_error_message(self, event: 'Event') -> str | None:
        sce_ids = [
            SCEUtils.get_tournament_plugin_data(tournament).id
            for tournament in event.tournaments
        ]
        if any(sce_ids) and not all(sce_ids):
            return _(
                'Distributing the players is allowed only if all the '
                'tournaments are synchronized with Sharly-Chess.com.'
            )
        return None

    # ---------------------------------------------------------------------------------
    # Nav
    # ---------------------------------------------------------------------------------

    @staticmethod
    def _event_has_sce_error_badge(event: Event) -> bool:
        if SCEUtils.resolve_event_status(event).notify_error_status:
            return True
        if SCEUtils.resolve_last_sync_status(event).notify_error_status:
            return True
        for tournament in event.tournaments:
            plugin_data = SCEUtils.get_tournament_plugin_data(tournament)
            if plugin_data.id and plugin_data.upload_failure_id:
                return True
        return False

    @hookimpl(tryfirst=True)
    def get_nav_data_transfer_items(
        self, event: 'Event'
    ) -> Iterable[NavDataTransferItem]:
        return [
            NavDataTransferItem(
                key='sce_data_transfer',
                title='Sharly-Chess.com',
                icon_path='/images/sce.ico',
                modal_route_name='sce-sync-modal',
                has_upload_error=self._event_has_sce_error_badge(event),
            )
        ]

    # ---------------------------------------------------------------------------------
    # Documents
    # ---------------------------------------------------------------------------------

    @hookimpl(trylast=True)
    def insert_print_qrcode_types(self, qrcode_types: list[type[QRCodeType]]):
        qrcode_types.insert(1, SCETournamentQRCodeType)
        qrcode_types.insert(1, SCEEventQRCodeType)

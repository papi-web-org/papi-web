from collections.abc import Iterable
from types import ModuleType
from typing import Any, TYPE_CHECKING

from packaging.version import Version

from common.i18n import _
from data.input_output import TournamentImporter
from data.tournament import Tournament
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredEvent,
    StoredTournament,
    StoredPlayer,
)
from plugins.chessevent import migrations, PLUGIN_NAME
from plugins.chessevent.chessevent_controller import ChessEventController
from plugins.chessevent.tournament_importer.data import ChessEventPlayer
from plugins.chessevent.tournament_importer.importer import ChessEventTournamentImporter
from plugins.chessevent.utils import (
    ChessEventEventPluginData,
    ChessEventTournamentPluginData,
    ChessEventUtils,
)
from plugins.ffe.ffe import FfePlugin
from plugins.hookspec import hookimpl, hookspec
from plugins.migration import PluginMigrationManager
from plugins.utils import (
    Plugin,
    PluginData,
    NavDataTransferItem,
    TournamentConnectionField,
)
from web.admin.collection import ListColumn
from web.controllers.base_controller import WebContext, BaseController
from utils.enum import EventType

if TYPE_CHECKING:
    from data.event import Event
    from web.admin.collection import AdminCollectionSpec


class ChessEventPluginHooks:
    @hookspec
    def augment_stored_player_from_chessevent_player(
        self,
        event: 'Event',
        importer: TournamentImporter,
        stored_player: StoredPlayer,
        chessevent_player: ChessEventPlayer,
    ):
        """Augment player data when fetched from ChessEvent."""


class ChessEventPlugin(Plugin):
    @staticmethod
    def static_id() -> str:
        return PLUGIN_NAME

    @property
    def supported_event_types(self) -> list[EventType]:
        return [EventType.INDIVIDUAL]

    @staticmethod
    def static_name() -> str:
        return _('ChessEvent')

    @property
    def dependencies(self) -> list[type[Plugin]]:
        return [FfePlugin]

    @property
    def description(self) -> str:
        return _(
            'Support for the ChessEvent platform used '
            'for organising tournaments in France.'
        )

    @property
    def keywords(self) -> list[str]:
        return ['chessevent', 'registration', 'import', 'france']

    @property
    def doc_slug(self) -> str:
        return 'chessevent'

    @property
    def doc_markdown(self) -> str:
        return '\n\n'.join(
            [
                _(
                    'ChessEvent handles the online registration of the '
                    'players for tournaments organised in France.'
                ),
                _(
                    '- the credentials of your ChessEvent account configured on the '
                    'event;\n'
                    '- the players of a tournament imported from the platform, with '
                    'their registration and their check-in;\n'
                    '- the import replayed at any time to pick up the late '
                    'registrations.'
                ),
            ]
        )

    @property
    def version(self) -> Version:
        return Version('0.1.0')

    @property
    def federation(self) -> str | None:
        return 'FRA'

    @property
    def base_migration_module(self) -> ModuleType:
        return migrations

    @property
    def hookspecs(self) -> type | None:
        return ChessEventPluginHooks

    @property
    def event_form_fields_template(self) -> str:
        return '/chessevent_event_form_fields.html'

    def used_by_stored_tournament(
        self, stored_event: StoredEvent, stored_tournament: StoredTournament
    ) -> bool:
        ce_data = stored_tournament.plugin_data.get(PLUGIN_NAME, {})
        return ce_data.get('tournament_name', None) is not None

    # ---------------------------------------------------------------------------------
    # Initialisation and configuration
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_event_migration_manager(
        self, event_database: EventDatabase
    ) -> PluginMigrationManager:
        return self.get_migration_manager(event_database)

    @property
    def controllers(self) -> list[type[BaseController]]:
        return [ChessEventController]

    # ---------------------------------------------------------------------------------
    # Input-Output
    # ---------------------------------------------------------------------------------

    @hookimpl
    def insert_tournament_importers(self, importers: list[type[TournamentImporter]]):
        importers.append(ChessEventTournamentImporter)

    # ---------------------------------------------------------------------------------
    # Events
    # ---------------------------------------------------------------------------------

    @hookimpl
    def on_event_duplicated(self, event_database: EventDatabase):
        stored_event = event_database.load_stored_event()

        stored_event.plugin_data[PLUGIN_NAME] = (
            ChessEventEventPluginData().to_stored_value()
        )
        event_database.update_stored_event(stored_event)

        for stored_tournament in stored_event.stored_tournaments:
            # Clear all the chessevent data
            new_plugin_data = ChessEventTournamentPluginData()
            stored_tournament.plugin_data[PLUGIN_NAME] = (
                new_plugin_data.to_stored_value()
            )
            event_database.update_stored_tournament(stored_tournament)

    @hookimpl
    def get_event_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, ChessEventEventPluginData

    @hookimpl
    def validate_event_form_fields(
        self,
        action: str,
        event: 'Event | None',
        data: dict[str, str],
        errors: dict[str, str],
    ):
        federation = WebContext.form_data_to_str(data, field := 'federation')
        if federation != 'FRA':
            # We only validate FFE fields for the FRA federation
            return

        chessevent_user_id = WebContext.form_data_to_str(data, 'chessevent_user')
        chessevent_password = WebContext.form_data_to_str(
            data, field := 'chessevent_password'
        )
        if chessevent_user_id and not chessevent_password:
            errors[field] = _('Please enter a password for the ChessEvent connection.')

    # ---------------------------------------------------------------------------------
    # Tournaments
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_tournament_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, ChessEventTournamentPluginData

    @hookimpl
    def get_tournament_page_template_context(self) -> dict[str, Any]:
        return {'chessevent_utils': ChessEventUtils}

    @hookimpl
    def get_tournament_connection_field(
        self, tournament: Tournament
    ) -> TournamentConnectionField | None:
        if not ChessEventUtils.resolve_tournament_name(tournament):
            return None
        return TournamentConnectionField(
            label=_('ChessEvent'),
            template='/chessevent_tournament_connection_value.html',
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

    @hookimpl(trylast=True)
    def get_nav_data_transfer_items(
        self, event: 'Event'
    ) -> Iterable[NavDataTransferItem]:
        if all(tournament.started for tournament in event.tournaments):
            return []
        return [
            NavDataTransferItem(
                key='chess_event_upload',
                title=_('ChessEvent'),
                icon_path='/images/chessevent.png',
                modal_route_name='chessevent-sync-modal',
                has_upload_error=False,
            )
        ]

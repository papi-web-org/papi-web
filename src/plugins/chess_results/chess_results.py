from typing import Any, TYPE_CHECKING, Iterable

from packaging.version import Version

from common.i18n import _
from data.print_documents import QRCodeType
from database.sqlite.event.event_database import EventDatabase
from plugins.chess_results import MAX_TIE_BREAKS, PLUGIN_NAME
from plugins.chess_results.chess_results_background_uploader import (
    EventLoader,
    CRBackgroundUploader,
)
from plugins.chess_results.chess_results_controller import (
    ChessResultsController,
)
from plugins.chess_results.chess_results_qrcode import ChessResultsQRCodeType
from plugins.chess_results.utils import (
    CHESS_RESULTS_UPLOAD_DELAY,
    ChessResultsConfigPluginData,
    ChessResultsEventPluginData,
    ChessResultsTournamentPluginData,
    CRUtils,
)
from plugins.hookspec import hookimpl
from plugins.utils import (
    NavDataTransferItem,
    Plugin,
    PluginData,
    TournamentConnectionField,
)
from web.admin.collection import ListColumn
from web.controllers.base_controller import BaseController

if TYPE_CHECKING:
    from data.event import Event
    from database.sqlite.event.event_store import StoredEvent
    from data.tournament import Tournament
    from database.sqlite.event.event_store import StoredTournament
    from web.admin.collection import AdminCollectionSpec


class ChessResultsPlugin(Plugin[ChessResultsConfigPluginData]):
    data_class = ChessResultsConfigPluginData

    @staticmethod
    def static_id() -> str:
        return PLUGIN_NAME

    @staticmethod
    def static_name() -> str:
        return _('Chess-Results.com')

    @property
    def description(self) -> str:
        return _('Uploading of tournaments to Chess-Results.com.')

    @property
    def keywords(self) -> list[str]:
        return ['chess-results', 'chessresults', 'upload', 'results']

    @property
    def doc_markdown(self) -> str:
        return '\n\n'.join(
            [
                _(
                    'Chess-Results.com publishes the pairings and the standings of '
                    'tournaments all over the world.'
                ),
                _(
                    '- the number of the tournament and the identifier of its creator '
                    'configured on the tournament;\n'
                    '- the tournament uploaded on demand from its card, or '
                    'automatically as soon as its data changes;\n'
                    '- a link to the page of the tournament on Chess-Results.com.'
                ),
            ]
        )

    @property
    def version(self) -> Version:
        return Version('1.0.0')

    @property
    def event_form_fields_template(self) -> str:
        return '/chess_results_event_form_fields.html'

    def used_by_stored_tournament(
        self, stored_event: 'StoredEvent', stored_tournament: 'StoredTournament'
    ) -> bool:
        cr_data = stored_tournament.plugin_data.get(PLUGIN_NAME, {})
        return cr_data.get('tnr', None) is not None

    # ---------------------------------------------------------------------------------
    # Initialisation and configuration
    # ---------------------------------------------------------------------------------

    @property
    def controllers(self) -> list[type[BaseController]]:
        return [ChessResultsController]

    @hookimpl
    def get_base_admin_template_context(self) -> dict[str, Any]:
        return {
            'CHESS_RESULTS_UPLOAD_DELAY': CHESS_RESULTS_UPLOAD_DELAY,
        }

    # ---------------------------------------------------------------------------------
    # Events
    # ---------------------------------------------------------------------------------

    @hookimpl
    def on_event_duplicated(self, event_database: EventDatabase):
        stored_tournaments = event_database.load_stored_tournaments()
        for stored_tournament in stored_tournaments:
            old_plugin_data = ChessResultsTournamentPluginData.from_stored_value(
                stored_tournament.plugin_data.get(PLUGIN_NAME, {})
            )

            # Only retain the remark setting
            # We don't retain the auto_upload setting since that would cause an immediate upload of the tournament since
            # we don't need an other fields to be set in order to do an upload.
            new_plugin_data = ChessResultsTournamentPluginData(
                remark=old_plugin_data.remark,
                remark_default=old_plugin_data.remark_default,
            )
            stored_tournament.plugin_data[PLUGIN_NAME] = (
                new_plugin_data.to_stored_value()
            )
            event_database.update_stored_tournament(stored_tournament)

    @hookimpl
    def get_event_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, ChessResultsEventPluginData

    # ---------------------------------------------------------------------------------
    # Tournaments
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_tournament_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, ChessResultsTournamentPluginData

    @hookimpl
    def on_tournament_data_updated(
        self, stored_event: 'StoredEvent', stored_tournament: 'StoredTournament'
    ):
        # This hook being called for most database writes, it needs to be optimized
        if not CRBackgroundUploader.should_schedule_tournament_upload(
            stored_event, stored_tournament
        ):
            return
        event = EventLoader().load_event(stored_event.uniq_id)
        tournament_id = stored_tournament.id
        assert tournament_id is not None
        tournament = event.tournaments_by_id[tournament_id]
        CRBackgroundUploader.schedule_upload(tournament)

    @hookimpl
    def get_tournament_form_fields_template_and_data(
        self, event: 'Event', tournament: 'Tournament | None'
    ) -> tuple[str, dict[str, Any]]:
        return '/chess_results_tournament_form_fields.html', {}

    @hookimpl
    def get_tournament_page_template_context(self) -> dict[str, Any]:
        return {'cr_utils': CRUtils}

    @hookimpl
    def get_tournament_connection_field(
        self, tournament: 'Tournament'
    ) -> TournamentConnectionField | None:
        if not CRUtils.get_tournament_plugin_data(tournament).tnr:
            return None
        return TournamentConnectionField(
            label=_('Chess-Results'),
            template='/chess_results_tournament_connection_value.html',
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
    def get_tournament_card_action_menu_items_template(self) -> str:
        return '/chess_results_tournament_card_action_menu_items.html'

    @hookimpl
    def get_tournament_tie_breaks_warning_message(
        self, tournament: 'Tournament'
    ) -> str | None:
        if not CRUtils.get_tournament_plugin_data(tournament).tnr:
            return None
        if len(tournament.tie_breaks) > MAX_TIE_BREAKS:
            return _(
                'Chess-Results.com only displays {max} tie-breaks. '
                'However, the rankings remain the same as in Sharly Chess.'
            ).format(max=MAX_TIE_BREAKS)
        return None

    # ---------------------------------------------------------------------------------
    # Upload
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_nav_data_transfer_items(
        self, event: 'Event'
    ) -> Iterable[NavDataTransferItem]:
        return [
            NavDataTransferItem(
                key='chess_results_upload',
                title=_('Chess-Results.com'),
                icon_path='/images/chess-results.png',
                modal_route_name='chess-results-upload-modal',
                has_upload_error=any(
                    plugin_data.tnr and plugin_data.upload_failure_id
                    for tournament in event.tournaments
                    if (plugin_data := CRUtils.get_tournament_plugin_data(tournament))
                ),
            )
        ]

    # ---------------------------------------------------------------------------------
    # QR code
    # ---------------------------------------------------------------------------------

    @hookimpl
    def insert_print_qrcode_types(self, qrcode_types: list[type[QRCodeType]]):
        qrcode_types.append(ChessResultsQRCodeType)

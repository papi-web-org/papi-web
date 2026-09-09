from typing import Iterable, Any, TYPE_CHECKING

from packaging.version import Version

from common.i18n import _
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import StoredEvent, StoredTournament
from plugins.custom_upload import PLUGIN_NAME
from plugins.custom_upload.custom_upload_controller import (
    CustomUploadAdminEventController,
)
from plugins.custom_upload.utils import (
    CustomUploadUtils,
    CustomUploadEventPluginData,
)
from plugins.hookspec import hookimpl
from plugins.utils import (
    Plugin,
    NavDataTransferItem,
    PluginData,
    TournamentConnectionField,
)
from web.controllers.base_controller import BaseController

if TYPE_CHECKING:
    from data.event import Event
    from data.tournament import Tournament


class CustomUploadPlugin(Plugin):
    @staticmethod
    def static_id() -> str:
        return PLUGIN_NAME

    @staticmethod
    def static_name() -> str:
        return _('Custom upload')

    @property
    def description(self) -> str:
        return _('Upload tournament documents to custom location')

    @property
    def keywords(self) -> list[str]:
        return ['ftp', 'website', 'publish']

    @property
    def doc_markdown(self) -> str:
        return '\n\n'.join(
            [
                _(
                    'Publish the documents of an event on a website of your own, for '
                    'instance the website of your club or of the tournament.'
                ),
                _(
                    '- a server configured on the event (FTP, FTPS or SFTP);\n'
                    '- a list of documents to upload, each one targeting the whole '
                    'event or only some of its tournaments;\n'
                    '- documents uploaded on demand, or automatically as soon as the '
                    'data of a tournament they cover changes;\n'
                    '- the date of the last upload and the upload errors reported in '
                    'the interface.'
                ),
            ]
        )

    @property
    def version(self) -> Version:
        return Version('0.1.0')

    def used_by_stored_tournament(
        self, stored_event: 'StoredEvent', stored_tournament: 'StoredTournament'
    ) -> bool:
        return False

    # ---------------------------------------------------------------------------------
    # Initialisation and configuration
    # ---------------------------------------------------------------------------------

    @property
    def controllers(self) -> list[type[BaseController]]:
        return [
            CustomUploadAdminEventController,
        ]

    @hookimpl
    def get_base_admin_template_context(self) -> dict[str, Any]:
        return {
            'custom_upload_utils': CustomUploadUtils,
        }

    # ---------------------------------------------------------------------------------
    # Events
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_event_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, CustomUploadEventPluginData

    @hookimpl
    def on_event_duplicated(self, event_database: 'EventDatabase'):
        stored_event = event_database.load_stored_event()
        event_plugin_data = CustomUploadEventPluginData.from_stored_value(
            stored_event.plugin_data.get(PLUGIN_NAME, {})
        )
        event_plugin_data.ftp_password = None
        for document in event_plugin_data.documents:
            document.last_upload_at = None
            document.last_upload_attempt_at = None
            document.upload_failure_id = None
        stored_event.plugin_data[PLUGIN_NAME] = event_plugin_data.to_stored_value()
        event_database.update_stored_event(stored_event)

    @hookimpl
    def on_tournament_data_updated(
        self, stored_event: 'StoredEvent', stored_tournament: 'StoredTournament'
    ):
        """Schedule an automatic upload of the documents targeting a tournament
        whose data just changed, for documents that have auto-upload enabled."""
        event_plugin_data = CustomUploadEventPluginData.from_stored_value(
            stored_event.plugin_data.get(PLUGIN_NAME, {})
        )
        if not (event_plugin_data.ftp_host and event_plugin_data.ftp_username):
            return
        tournament_id = stored_tournament.id
        has_auto_document = any(
            document.auto_upload
            and (
                not document.tournament_ids()
                or tournament_id in document.tournament_ids()
            )
            for document in event_plugin_data.documents
        )
        if not has_auto_document:
            return

        from threading import Thread

        from common.logger import get_logger
        from data.access_levels.client import Client
        from data.loader import EventLoader
        from plugins.custom_upload.custom_upload_uploader import CustomUploadUploader

        uniq_id = stored_event.uniq_id

        def _reload_and_schedule() -> None:
            try:
                event = EventLoader().load_event(uniq_id)
                http_client = Client.for_event_administrator(event)
                for document in CustomUploadUtils.get_event_plugin_data(
                    event
                ).documents:
                    document_tournament_ids = document.tournament_ids()
                    if document_tournament_ids and tournament_id not in (
                        document_tournament_ids
                    ):
                        continue
                    if CustomUploadUploader.should_schedule_document_upload(
                        event, document
                    ):
                        CustomUploadUploader.schedule_upload(
                            event, document, http_client
                        )
            except Exception:
                get_logger().exception(
                    'Custom upload auto-scheduling failed for event [%s]', uniq_id
                )

        Thread(target=_reload_and_schedule, daemon=True).start()

    # ---------------------------------------------------------------------------------
    # Tournaments
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_tournament_connection_field(
        self, tournament: 'Tournament'
    ) -> TournamentConnectionField | None:
        event_plugin_data = CustomUploadUtils.get_event_plugin_data(tournament.event)
        targets_tournament = any(
            tournament.id in document.tournament_ids()
            for document in event_plugin_data.documents
        )
        if not targets_tournament:
            return None
        return TournamentConnectionField(
            label=_('Custom location'),
            template='/custom_upload_tournament_connection_value.html',
        )

    # ---------------------------------------------------------------------------------
    # Upload
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_nav_data_transfer_items(
        self, event: 'Event'
    ) -> Iterable[NavDataTransferItem]:
        has_upload_error = any(
            document.upload_failure_id
            for document in CustomUploadUtils.get_event_plugin_data(event).documents
        )

        return [
            NavDataTransferItem(
                key='custom_upload',
                title=_('Custom location'),
                icon_path='/images/server.svg',
                modal_route_name='custom-upload-modal',
                has_upload_error=has_upload_error,
            )
        ]

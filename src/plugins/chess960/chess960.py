from typing import TYPE_CHECKING

from packaging.version import Version

from common.i18n import _
from data.print_documents import (
    PrintDocument,
)
from plugins.chess960 import PLUGIN_NAME
from plugins.chess960.chess960_controller import (
    Chess960Controller,
    Chess960SvgController,
)
from plugins.chess960.chess960_document import Chess960PrintDocument
from plugins.chess960.screen_type import Chess960ScreenType
from plugins.chess960.utils import Chess960ScreenPluginData
from plugins.hookspec import hookimpl
from plugins.utils import Plugin, PluginData
from web.controllers.base_controller import BaseController

if TYPE_CHECKING:
    from data.screens.screen_types import ScreenType
    from database.sqlite.event.event_store import StoredEvent, StoredTournament


class Chess960Plugin(Plugin):
    data_class = Chess960ScreenPluginData

    @staticmethod
    def static_id() -> str:
        return PLUGIN_NAME

    @staticmethod
    def static_name() -> str:
        return _('Chess960')

    @property
    def description(self) -> str:
        return _('Adds a screen showing the Chess960 start position.')

    @property
    def keywords(self) -> list[str]:
        return ['fischer random', '960']

    @property
    def doc_markdown(self) -> str:
        return '\n\n'.join(
            [
                _(
                    'Chess960 (also called Fischer random chess) starts the games '
                    'from one of the 960 possible shuffles of the pieces on the first '
                    'rank (with the King between the two Rooks and the Bishops on '
                    'opposite-colored squares).'
                ),
                _(
                    '- a **Chess960** screen type, holding the start position of the '
                    'round so that it can be displayed to the players;\n'
                    '- an **All Chess960 positions** document, listing every start '
                    'position with its number.'
                ),
            ]
        )

    @property
    def version(self) -> Version:
        return Version('1.0.0')

    @property
    def default_is_enabled(self) -> bool:
        return False

    @property
    def default_event_is_enabled(self) -> bool:
        return False

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
            Chess960Controller,
            Chess960SvgController,
        ]

    # ---------------------------------------------------------------------------------
    # Screens
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_screen_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, Chess960ScreenPluginData

    @hookimpl
    def insert_screen_types(self, screen_types: list[type['ScreenType']]):
        screen_types.append(Chess960ScreenType)

    # ---------------------------------------------------------------------------------
    # Printing
    # ---------------------------------------------------------------------------------

    @hookimpl
    def insert_print_document(self, print_documents: list[type['PrintDocument']]):
        print_documents.append(Chess960PrintDocument)

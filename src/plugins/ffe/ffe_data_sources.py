from abc import ABC, abstractmethod
from datetime import date

from text_unidecode import unidecode

from common import SharlyChessException
from common.i18n import _
from common.i18n.utils import unicode_normalize
from common.logger import get_logger
from common.network import NetworkMonitor
from data.columns.handlers import PlayerDatasheetColumnHandler
import data.columns.player_datasheet as pds
from data.columns.player_datasheet import DatasheetColumn
from data.input_output import OnlineDataSource
from data.input_output.data_source import LocalDataSource
from data.input_output.player_updater_fields import (
    PlayerUpdaterField,
    FideIDUpdaterField,
    TitleUpdaterField,
    WomenTitleUpdaterField,
    NameUpdaterField,
    CategoryUpdaterField,
    GenderPlayerUpdater,
    StandardRatingUpdaterField,
    RapidRatingUpdaterField,
    BlitzRatingUpdaterField,
    FederationUpdaterField,
    ClubUpdaterField,
)
from data.player import Player
from database.sqlite.event.event_store import StoredPlayer
from database.sqlite.local_source_database import LocalSourcePlayerDatabase
from plugins.ffe import PLUGIN_NAME
from plugins.ffe.ffe_database import FfeDatabase
from plugins.ffe.ffe_entity import (
    FfeLicenceNumberDatasheetColumn,
    FfeIdDatasheetColumn,
    FfeLicenceDatasheetColumn,
    FfeLeagueDatasheetColumn,
)
from plugins.ffe.ffe_sql_server import FFESqlServer
from plugins.ffe.utils import FFEUtils, FfePlayerPluginData, get_data


logger = get_logger()


class FfePlayerUpdaterField(PlayerUpdaterField, ABC):
    def is_updated(self, player: Player, match_player: Player) -> bool:
        return self._is_ffe_plugin_data_updated(
            FFEUtils.get_player_plugin_data(player),
            FFEUtils.get_player_plugin_data(match_player),
        )

    @abstractmethod
    def _is_ffe_plugin_data_updated(
        self, src_pd: FfePlayerPluginData, match_pd: FfePlayerPluginData
    ) -> bool:
        """Checks if the FFE plugin data of the player has been updated."""

    def update_player(
        self, stored_player: StoredPlayer, match_stored_player: StoredPlayer
    ):
        src_pd = FfePlayerPluginData.from_stored_value(
            stored_player.plugin_data.get(PLUGIN_NAME, {})
        )
        match_pd = FfePlayerPluginData.from_stored_value(
            match_stored_player.plugin_data.get(PLUGIN_NAME, {})
        )
        self._update_ffe_plugin_data(src_pd, match_pd)
        stored_player.plugin_data[PLUGIN_NAME] = src_pd.to_stored_value()

    @abstractmethod
    def _update_ffe_plugin_data(
        self, src_pd: FfePlayerPluginData, match_pd: FfePlayerPluginData
    ):
        """Update the FFE plugin data from the match player's FFE plugin data."""

    def get_string_value(self, player: Player) -> str:
        return self._get_ffe_string_value(FFEUtils.get_player_plugin_data(player))

    @abstractmethod
    def _get_ffe_string_value(self, plugin_data: FfePlayerPluginData) -> str:
        """Get the string value from the FFE plugin data."""


class FfeLicenceNumberUpdaterField(FfePlayerUpdaterField):
    @staticmethod
    def static_id() -> str:
        return 'ffe_licence_number'

    @staticmethod
    def static_name() -> str:
        return 'FFE'

    def _is_ffe_plugin_data_updated(
        self, src_pd: FfePlayerPluginData, match_pd: FfePlayerPluginData
    ) -> bool:
        return src_pd.ffe_licence_number != match_pd.ffe_licence_number

    def _update_ffe_plugin_data(
        self, src_pd: FfePlayerPluginData, match_pd: FfePlayerPluginData
    ):
        src_pd.ffe_licence_number = match_pd.ffe_licence_number

    def _get_ffe_string_value(self, plugin_data: FfePlayerPluginData) -> str:
        return plugin_data.ffe_licence_number or ''


class FfeLicenceUpdaterField(FfePlayerUpdaterField):
    @staticmethod
    def static_id() -> str:
        return 'ffe_licence'

    @staticmethod
    def static_name() -> str:
        return _('Lic. *** LICENCE COLUMN HEADER')

    def _is_ffe_plugin_data_updated(
        self, src_pd: FfePlayerPluginData, match_pd: FfePlayerPluginData
    ) -> bool:
        return src_pd.ffe_licence != match_pd.ffe_licence

    def _update_ffe_plugin_data(
        self, src_pd: FfePlayerPluginData, match_pd: FfePlayerPluginData
    ):
        src_pd.ffe_licence = match_pd.ffe_licence

    @property
    def cell_template(self) -> str:
        return '/ffe_player_update_licence_cell.html'

    def _get_ffe_string_value(self, plugin_data: FfePlayerPluginData) -> str:
        return plugin_data.ffe_licence.compact_name


class FfeLeagueUpdaterField(FfePlayerUpdaterField):
    @staticmethod
    def static_id() -> str:
        return 'ffe_league'

    @staticmethod
    def static_name() -> str:
        return _('League')

    def _is_ffe_plugin_data_updated(
        self, src_pd: FfePlayerPluginData, match_pd: FfePlayerPluginData
    ) -> bool:
        return bool(match_pd.league) and src_pd.league != match_pd.league

    def _update_ffe_plugin_data(
        self, src_pd: FfePlayerPluginData, match_pd: FfePlayerPluginData
    ):
        src_pd.league = match_pd.league

    def _get_ffe_string_value(self, plugin_data: FfePlayerPluginData) -> str:
        return plugin_data.league or ''


class _FfeDataSource(ABC):
    @property
    def _player_updater_fields(self) -> list[PlayerUpdaterField]:
        return [
            FfeLicenceNumberUpdaterField(),
            FfeLicenceUpdaterField(),
            FideIDUpdaterField(),
            TitleUpdaterField(),
            WomenTitleUpdaterField(),
            NameUpdaterField(),
            CategoryUpdaterField(),
            GenderPlayerUpdater(),
            StandardRatingUpdaterField(),
            RapidRatingUpdaterField(),
            BlitzRatingUpdaterField(),
            FederationUpdaterField(),
            FfeLeagueUpdaterField(),
            ClubUpdaterField(),
        ]

    @abstractmethod
    async def _get_ffe_match_stored_players(
        self,
        ffe_licence_numbers: list[str],
        fide_ids: list[int],
        name_keys: list[tuple[str, str, date]],
    ) -> list[StoredPlayer] | None:
        """Fetch player matches in the data source. Return None if it fails."""

    @staticmethod
    def _get_licence_number(stored_player: StoredPlayer) -> str | None:
        return get_data(stored_player.plugin_data, 'ffe_licence_number', None)

    @staticmethod
    def _get_name_key(stored_player: StoredPlayer) -> tuple[str, str, date] | None:
        first_name = stored_player.first_name
        dob = stored_player.date_of_birth
        if first_name and dob:
            return unidecode(stored_player.last_name), unidecode(first_name), dob
        return None

    @classmethod
    def _check_player_match(
        cls,
        player1: StoredPlayer,
        player2: StoredPlayer,
    ) -> bool:
        if licence_key := cls._get_licence_number(player1):
            return licence_key == cls._get_licence_number(player2)
        if fide_id := player1.fide_id:
            return fide_id == player2.fide_id
        if name_key := cls._get_name_key(player1):
            return name_key == cls._get_name_key(player2)
        return False

    async def _get_match_stored_players(
        self, players: list[Player]
    ) -> list[StoredPlayer] | None:
        licence_numbers: list[str] = []
        fide_ids: list[int] = []
        name_keys: list[tuple[str, str, date]] = []
        for player in players:
            stored_player = player.stored_player
            if licence_number := self._get_licence_number(stored_player):
                licence_numbers.append(licence_number)
            elif fide_id := stored_player.fide_id:
                fide_ids.append(fide_id)
            elif name_key := self._get_name_key(stored_player):
                name_keys.append(name_key)
        return await self._get_ffe_match_stored_players(
            licence_numbers, fide_ids, name_keys
        )

    @property
    def _search_fields(self) -> list[str]:
        return [_('Name'), _('Licence number'), _('FIDE ID')]

    @property
    def _player_search_result_template(self) -> str:
        return '/ffe_search_result.html'

    @staticmethod
    def _get_player_source_id(stored_player: StoredPlayer) -> str:
        return str(get_data(stored_player.plugin_data, 'ffe_id'))

    @property
    def _import_identifier_column(self) -> DatasheetColumn:
        return FfeLicenceNumberDatasheetColumn()

    @property
    def _imported_datasheet_columns(self) -> list[DatasheetColumn]:
        columns: list[DatasheetColumn] = [
            pds.TitleColumn(),
            pds.WomenTitleColumn(),
            pds.LastNameColumn(),
            pds.FirstNameColumn(),
            pds.DateOfBirthColumn(),
            pds.YearOfBirthColumn(),
            pds.GenderColumn(),
            pds.FideIDColumn(),
            pds.FederationColumn(),
            FfeLeagueDatasheetColumn(),
            pds.ClubColumn(),
            FfeIdDatasheetColumn(),
            FfeLicenceDatasheetColumn(),
        ]
        columns += PlayerDatasheetColumnHandler.get_rating_columns()
        return columns

    async def _get_stored_players_by_import_identifier(
        self, identifier_values: list[str]
    ) -> dict[str, StoredPlayer]:
        stored_players = await self._get_ffe_match_stored_players(
            identifier_values, [], []
        )
        return {
            stored_player.plugin_data[PLUGIN_NAME]['ffe_licence_number']: stored_player
            for stored_player in stored_players or []
        }


class FfeLocalDataSource(LocalDataSource, _FfeDataSource):
    @staticmethod
    def static_id() -> str:
        return f'{PLUGIN_NAME}-local'

    @staticmethod
    def static_name() -> str:
        return _('FFE database (local)')

    @property
    def local_database_type(self) -> type[LocalSourcePlayerDatabase]:
        return FfeDatabase

    @property
    def player_updater_fields(self) -> list[PlayerUpdaterField]:
        return self._player_updater_fields

    def check_player_match(self, player1: StoredPlayer, player2: StoredPlayer) -> bool:
        return self._check_player_match(player1, player2)

    async def get_match_stored_players(
        self, players: list[Player]
    ) -> list[StoredPlayer] | None:
        return await self._get_match_stored_players(players)

    async def _get_ffe_match_stored_players(
        self,
        ffe_licence_numbers: list[str],
        fide_ids: list[int],
        name_keys: list[tuple[str, str, date]],
    ) -> list[StoredPlayer] | None:
        database = FfeDatabase()
        if not database.exists():
            return None
        with database:
            licence_matches = (
                database.get_stored_players_by_licence_numbers(ffe_licence_numbers)
                if ffe_licence_numbers
                else []
            )
            fide_id_matches = (
                database.get_stored_players_by_fide_ids(fide_ids) if fide_ids else []
            )
            name_matches = (
                database.get_stored_players_by_name_keys(name_keys) if name_keys else []
            )
        return licence_matches + fide_id_matches + name_matches

    @property
    def search_fields(self) -> list[str]:
        return self._search_fields

    @property
    def player_search_result_template(self) -> str:
        return self._player_search_result_template

    def get_player_source_id(self, stored_player: StoredPlayer) -> str:
        return self._get_player_source_id(stored_player)

    async def get_stored_player_by_source_id(
        self, player_source_id: str
    ) -> StoredPlayer | None:
        if not player_source_id.isdigit():
            return None
        with FfeDatabase() as database:
            return database.get_stored_player_by_ffe_id(int(player_source_id))

    @property
    def import_identifier_column(self) -> DatasheetColumn:
        return self._import_identifier_column

    @property
    def imported_datasheet_columns(self) -> list[DatasheetColumn]:
        return self._imported_datasheet_columns

    async def get_stored_players_by_import_identifier(
        self, identifier_values: list[str]
    ) -> dict[str, StoredPlayer]:
        return await self._get_stored_players_by_import_identifier(identifier_values)


class FfeOnlineDataSource(OnlineDataSource, _FfeDataSource):
    @staticmethod
    def static_id() -> str:
        return f'{PLUGIN_NAME}-online'

    @staticmethod
    def static_name() -> str:
        return _('FFE database (online)')

    @classmethod
    async def check_connection(cls) -> bool:
        if not NetworkMonitor.connected():
            return False
        try:
            async with FFESqlServer():
                return True
        except SharlyChessException as e:
            logger.warning('FFE connection check failed: %s', e)
            return False

    @property
    def player_updater_fields(self) -> list[PlayerUpdaterField]:
        return self._player_updater_fields

    def check_player_match(self, player1: StoredPlayer, player2: StoredPlayer) -> bool:
        return self._check_player_match(player1, player2)

    async def get_match_stored_players(
        self, players: list[Player]
    ) -> list[StoredPlayer] | None:
        return await self._get_match_stored_players(players)

    async def _get_ffe_match_stored_players(
        self,
        ffe_licence_numbers: list[str],
        fide_ids: list[int],
        name_keys: list[tuple[str, str, date]],
    ) -> list[StoredPlayer] | None:
        try:
            async with FFESqlServer() as server:
                licence_matches = (
                    await server.get_stored_players_by_licence_numbers(
                        ffe_licence_numbers
                    )
                    if ffe_licence_numbers
                    else []
                )
                fide_id_matches = (
                    await server.get_stored_players_by_fide_ids(fide_ids)
                    if fide_ids
                    else []
                )
                name_matches = (
                    await server.get_stored_players_by_name_keys(name_keys)
                    if name_keys
                    else []
                )
                return licence_matches + fide_id_matches + name_matches
        except SharlyChessException:
            return None

    @property
    def search_fields(self) -> list[str]:
        return self._search_fields

    @property
    def player_search_result_template(self) -> str:
        return self._player_search_result_template

    def get_player_source_id(self, stored_player: StoredPlayer) -> str:
        return self._get_player_source_id(stored_player)

    async def get_stored_player_by_source_id(
        self, player_source_id: str
    ) -> StoredPlayer | None:
        if not player_source_id.isdigit():
            return None
        async with FFESqlServer() as ffe_sql_server:
            return await ffe_sql_server.get_stored_player_by_ffe_id(
                int(player_source_id)
            )

    async def _search_player(
        self,
        string: str,
        federation: str,
        page: int = 0,
        limit: int | None = None,
        filters: dict = {},
    ) -> list[StoredPlayer]:
        async with FFESqlServer() as ffe_sql_server:
            return await ffe_sql_server.search_player(
                unicode_normalize(string), federation, page, limit, filters
            )

    @property
    def import_identifier_column(self) -> DatasheetColumn:
        return self._import_identifier_column

    @property
    def imported_datasheet_columns(self) -> list[DatasheetColumn]:
        return self._imported_datasheet_columns

    async def get_stored_players_by_import_identifier(
        self, identifier_values: list[str]
    ) -> dict[str, StoredPlayer]:
        return await self._get_stored_players_by_import_identifier(identifier_values)

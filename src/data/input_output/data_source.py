import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from functools import cached_property
from logging import Logger
from typing import override, ClassVar, Collection

from common import SharlyChessException
from common.i18n import _
from common.logger import get_logger
from common.network import NetworkMonitor
import data.columns.player_datasheet as pds
from data.columns.handlers import PlayerDatasheetColumnHandler
from data.columns.player_datasheet import DatasheetColumn
from data.event import Event
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
)
from data.player import Player, PlayerRating
from database.sqlite.event.event_store import StoredPlayer
from database.sqlite.fide.fide_database import FideDatabase
from database.sqlite.local_source_database.databases import LocalSourcePlayerDatabase
from plugins.manager import plugin_manager
from utils.date_time import format_datetime
from utils.entity import IdentifiableEntity
from utils.enum import TournamentRating, PlayerRatingType

logger: Logger = get_logger()


class PlayerComparator:
    def __init__(
        self,
        fields: list[PlayerUpdaterField],
        player: Player,
        match_stored_player: StoredPlayer | None = None,
    ):
        self.player = player
        self.match_player: Player | None = None
        if match_stored_player:
            match_stored_player.id = 0
            self.match_player = Player(player.event, match_stored_player)
        self.diff_field_ids = self._get_diff_field_ids(fields)

    def _get_diff_field_ids(self, fields: list[PlayerUpdaterField]) -> list[str]:
        if not self.match_player:
            return []
        return [
            field.id
            for field in fields
            if field.is_updated(self.player, self.match_player)
        ]

    def updated_player_from_match(self, fields: list[PlayerUpdaterField]) -> Player:
        assert self.match_player is not None
        for field in fields:
            if field.id not in self.diff_field_ids:
                continue
            field.update_player(
                self.player.stored_player, self.match_player.stored_player
            )
        return self.player


class DataSource(IdentifiableEntity, ABC):
    """Abstract class representing data source.
    Data sources can be used to search players or update them."""

    SEARCH_LIMIT = 30

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Determines if the data source is available."""

    def on_app_init(self):
        """Function to execute at the start of the server to initialize the data source."""

    @property
    def info_or_warning_message(self) -> tuple[str, bool]:
        """Message displayed on the players update modal and the player search.
        If the bool is set to True, show the message as a warning."""
        return '', False

    # --------------------------------------------------------------------------
    # Players update
    # --------------------------------------------------------------------------

    @property
    @abstractmethod
    def player_updater_fields(self) -> list[PlayerUpdaterField]:
        """Returns the player fields that can be updated by the data source."""

    @abstractmethod
    def check_player_match(self, player1: StoredPlayer, player2: StoredPlayer) -> bool:
        """Checks if the two players are a match."""

    @abstractmethod
    async def get_match_stored_players(
        self, players: list[Player]
    ) -> list[StoredPlayer] | None:
        """Get a list of stored players matching the given players."""

    async def get_player_comparators(
        self,
        players: list[Player],
        fields: list[PlayerUpdaterField],
        diff_only: bool = False,
    ) -> list[PlayerComparator] | None:
        """Get player comparators for all the players in the list.
        *restricted_field_ids* allows to only set the comparators with specific fields.
        If *diff_only*, the comparators returned are only the ones where a match has been found."""
        match_stored_players = await self.get_match_stored_players(players)
        if match_stored_players is None:
            return None
        player_comparators: list[PlayerComparator] = []
        for player in players:
            match_player = next(
                (
                    match_stored_player
                    for match_stored_player in match_stored_players
                    if self.check_player_match(
                        player.stored_player, match_stored_player
                    )
                ),
                None,
            )
            player_comparator = PlayerComparator(fields, player, match_player)
            if not diff_only or player_comparator.diff_field_ids:
                player_comparators.append(player_comparator)
        return player_comparators

    # --------------------------------------------------------------------------
    # Player search
    # --------------------------------------------------------------------------

    @property
    def search_element_name(self) -> str:
        return f'{self.id.replace("-", "_")}_search'

    @property
    @abstractmethod
    def search_fields(self) -> list[str]:
        """Localized list of names of the fields
        which can be used to search for a player."""

    @property
    @abstractmethod
    def player_search_result_template(self) -> str:
        """Template containing the info to display for a player as a search result.
        Template takes [player] as a template variable."""

    @property
    @abstractmethod
    def search_error_icon(self) -> str:
        """Icon to display in the search results in case of an error."""

    @abstractmethod
    async def search_player(
        self,
        string: str,
        federation: str,
        page: int = 0,
        limit: int | None = None,
        filters: dict = {},
    ) -> list[StoredPlayer]:
        """Search a player in the data source from a string.
        Returns maximum *limit* results (no limit if *limit* is None)."""

    @abstractmethod
    async def get_stored_player_by_source_id(
        self,
        player_source_id: str,
    ) -> StoredPlayer | None:
        """Get a player by its identifier in the data source."""

    @abstractmethod
    def get_player_source_id(self, stored_player: StoredPlayer) -> str:
        """Get the id of the player in the source formatted as a string."""

    async def fetch_player(
        self,
        player_source_id: str,
        with_arbiter_title: bool,
    ) -> StoredPlayer | None:
        stored_player = await self.get_stored_player_by_source_id(player_source_id)
        if stored_player:
            self._adjust_player_from_fide_database(stored_player)
            await plugin_manager.ahook.augment_player_after_search(
                stored_player=stored_player,
                data_source=self,
                with_arbiter_title=with_arbiter_title,
            )
        return stored_player

    @staticmethod
    def _adjust_player_from_fide_database(
        src_stored_player: StoredPlayer,
    ):
        """Cross-references the player with the FIDE Database.
        Override this method to disable this behavior."""
        fide_id = src_stored_player.fide_id
        database = FideDatabase()
        if not fide_id or not database.exists():
            return
        with database:
            fide_stored_player = database.get_stored_player_by_fide_id(
                player_fide_id=fide_id,
            )
            if not fide_stored_player:
                return
            src_stored_player.federation = fide_stored_player.federation
            src_stored_player.title = fide_stored_player.title
            src_stored_player.women_title = fide_stored_player.women_title
            src_stored_player.transient_arbiter_titles['fide'] = (
                fide_stored_player.transient_arbiter_titles.get('fide', '')
            )
            for rating_type in TournamentRating:
                stored_fide_rating = fide_stored_player.ratings.get(
                    rating_type.value, None
                )
                if not stored_fide_rating:
                    continue
                fide_rating = PlayerRating.from_stored_value(stored_fide_rating).fide
                if not fide_rating:
                    continue
                stored_source_rating = src_stored_player.ratings.get(
                    rating_type.value, None
                )
                if not stored_source_rating:
                    src_stored_player.ratings[rating_type.value] = PlayerRating(
                        fide=fide_rating
                    ).stored_value
                    continue
                source_rating = PlayerRating.from_stored_value(stored_source_rating)
                if source_rating.fide is None:
                    src_stored_player.ratings[rating_type.value] = PlayerRating(
                        fide=fide_rating,
                        national=source_rating.national,
                        estimated=source_rating.estimated,
                    ).stored_value

    # --------------------------------------------------------------------------
    # Player Import
    # --------------------------------------------------------------------------

    @property
    @abstractmethod
    def import_identifier_column(self) -> DatasheetColumn:
        """Column of the identifier of the import."""

    @property
    @abstractmethod
    def imported_datasheet_columns(self) -> list[DatasheetColumn]:
        """datasheet columns that the datasource is importing.
        These columns won't be available on import."""

    def get_all_datasheet_columns(self, event: Event) -> Collection[DatasheetColumn]:
        """Fetch the datasheet columns that can be imported with the data source."""
        return PlayerDatasheetColumnHandler(event, self).columns

    @abstractmethod
    async def get_stored_players_by_import_identifier(
        self, identifier_values: list[str]
    ) -> dict[str, StoredPlayer]:
        """Fetch stored players from their identifier values.
        Return a dict with the ones that have been found."""


class LocalDataSource(DataSource, ABC):
    @property
    @abstractmethod
    def local_database_type(self) -> type[LocalSourcePlayerDatabase]:
        """The type of the local database used for this source."""

    @cached_property
    def database(self) -> LocalSourcePlayerDatabase:
        return self.local_database_type()

    @property
    def info_or_warning_message(self) -> tuple[str, bool]:
        message = (
            _('Last update: {updated_at} (outdated)')
            if self.database.is_outdated
            else _('Last update: {updated_at}')
        )
        return (
            message.format(updated_at=self.database.updated_at_str),
            self.database.is_outdated,
        )

    @property
    def is_available(self) -> bool:
        return self.local_database_type.file_path().exists()

    def on_app_init(self):
        self.database.check()

    @property
    def search_error_icon(self) -> str:
        return 'bi-database-fill-dash'

    async def search_player(
        self,
        string: str,
        federation: str,
        page: int = 0,
        limit: int | None = None,
        filters: dict = {},
    ) -> list[StoredPlayer]:
        if not self.is_available:
            raise SharlyChessException(
                _(
                    'This database is not installed '
                    '(to install it: Menu > Data sources).'
                )
            )
        with self.local_database_type() as database:
            return database.search_player(string, federation, page, limit, filters)


class OnlineDataSource(DataSource, ABC):
    connection_status: ClassVar[bool | None] = None
    _connection_last_checked_at: ClassVar[datetime | None] = None

    @classmethod
    @abstractmethod
    async def check_connection(cls) -> bool:
        """Check the connection to the data source.
        If it fails, log the error."""

    def on_app_init(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop yet — safe fallback if someone calls too early
            loop = asyncio.get_event_loop()

        # Schedule background task
        loop.create_task(self.reload_connection_status())

    @classmethod
    async def reload_connection_status(cls):
        cls._connection_last_checked_at = datetime.now()
        if not NetworkMonitor.connected():
            cls.connection_status = None
            return
        cls.connection_status = await cls.check_connection()

    @property
    def is_available(self) -> bool:
        return True

    @property
    def connection_last_checked_at_str(self) -> str:
        if not self._connection_last_checked_at:
            return ''
        return format_datetime(self._connection_last_checked_at)

    @property
    def search_error_icon(self) -> str:
        return 'bi-cloud-fill-dash'

    async def search_player(
        self,
        string: str,
        federation: str,
        page: int = 0,
        limit: int | None = None,
        filters: dict = {},
    ) -> list[StoredPlayer]:
        cls = self.__class__
        cls._connection_last_checked_at = datetime.now()
        if not NetworkMonitor.connected():
            cls.connection_status = None
            raise SharlyChessException(_('No internet connection'))
        try:
            players = await self._search_player(
                string, federation, page, limit, filters
            )
            cls.connection_status = True
            return players
        except SharlyChessException as exception:
            cls.connection_status = False
            raise exception

    @abstractmethod
    async def _search_player(
        self,
        string: str,
        federation: str,
        page: int = 0,
        limit: int | None = None,
        filters: dict = {},
    ) -> list[StoredPlayer]:
        """Search a player in the data source from a string.
        Returns maximum *limit* results (no limit if *limit* is None)."""


class FideDataSource(LocalDataSource):
    @staticmethod
    def static_id() -> str:
        return 'fide'

    @staticmethod
    def static_name() -> str:
        return _('FIDE database')

    @property
    def local_database_type(self) -> type[LocalSourcePlayerDatabase]:
        return FideDatabase

    @property
    def player_updater_fields(self) -> list[PlayerUpdaterField]:
        return [
            FideIDUpdaterField(),
            TitleUpdaterField(),
            WomenTitleUpdaterField(),
            NameUpdaterField(),
            CategoryUpdaterField(),
            GenderPlayerUpdater(),
            StandardRatingUpdaterField([PlayerRatingType.FIDE]),
            RapidRatingUpdaterField([PlayerRatingType.FIDE]),
            BlitzRatingUpdaterField([PlayerRatingType.FIDE]),
            FederationUpdaterField(),
        ]

    @staticmethod
    @override
    def _adjust_player_from_fide_database(
        src_stored_player: StoredPlayer,
    ):
        pass

    def check_player_match(self, player1: StoredPlayer, player2: StoredPlayer) -> bool:
        return bool(player1.fide_id) and player1.fide_id == player2.fide_id

    async def get_match_stored_players(
        self, players: list[Player]
    ) -> list[StoredPlayer] | None:
        database = FideDatabase()
        if not database.exists():
            return None
        fide_ids = [player.fide_id for player in players if player.fide_id]
        with database:
            return database.get_stored_players_by_fide_id(fide_ids)

    @property
    def search_fields(self) -> list[str]:
        return [_('Name'), _('FIDE ID')]

    @property
    def player_search_result_template(self) -> str:
        return '/admin/players/fide_search_result.html'

    async def get_stored_player_by_source_id(
        self,
        player_source_id: str,
    ) -> StoredPlayer | None:
        if not player_source_id.isdigit():
            return None
        with FideDatabase() as database:
            return database.get_stored_player_by_fide_id(
                player_fide_id=int(player_source_id),
            )

    def get_player_source_id(self, stored_player: StoredPlayer) -> str:
        return str(stored_player.fide_id)

    @property
    def import_identifier_column(self) -> DatasheetColumn:
        return pds.FideIDColumn()

    @property
    def imported_datasheet_columns(self) -> list[DatasheetColumn]:
        columns: list[DatasheetColumn] = [
            pds.TitleColumn(),
            pds.WomenTitleColumn(),
            pds.LastNameColumn(),
            pds.FirstNameColumn(),
            pds.DateOfBirthColumn(),
            pds.YearOfBirthColumn(),
            pds.GenderColumn(),
            pds.FederationColumn(),
        ]
        columns += PlayerDatasheetColumnHandler.get_rating_columns(
            [PlayerRatingType.FIDE]
        )
        return columns

    async def get_stored_players_by_import_identifier(
        self, identifier_values: list[str]
    ) -> dict[str, StoredPlayer]:
        with FideDatabase() as database:
            stored_players = database.get_stored_players_by_fide_id(
                [int(value) for value in identifier_values]
            )
        return {
            str(stored_player.fide_id): stored_player
            for stored_player in stored_players
        }

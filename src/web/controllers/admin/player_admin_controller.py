import csv
from collections import defaultdict, Counter
from collections.abc import Callable
from datetime import date
from functools import cached_property
from itertools import islice
from logging import Logger
import math
from pathlib import Path
from typing import Annotated, Any, Iterable

import chardet
from litestar.di import NamedDependency
from litestar.exceptions import NotFoundException, ClientException

from common.i18n.utils import normalized_key

from litestar import get, patch, delete, post, Response
from litestar.plugins.htmx import HTMXRequest
from litestar.enums import RequestEncodingType
from litestar.params import Body, FromPath, FromQuery
from litestar.response import Template, File, Redirect
from litestar.status_codes import HTTP_200_OK
from litestar_htmx import HTMXTemplate
from litestar.channels import ChannelsPlugin

from common.exception import SharlyChessException, FormError
from common.i18n import _, ngettext
from common.logger import get_logger
from common.sharly_chess_config import SharlyChessConfig
from data.columns.handlers import PlayersTabColumnHandler, PlayerDatasheetColumnHandler
from data.columns.player_datasheet import DatasheetColumn
from data.columns.players_tab import PlayersTabColumn
from data.event import Event
from data.access_levels.actions import AuthAction
from data.access_levels.client import Client
from data.input_output.data_source import DataSource, keep_reliable_k_factors
from data.input_output.managers import DataSourceManager, PlayerExporterManager
from data.player import (
    Player,
    PlayerRating,
    TournamentPlayer,
    MIN_YOB,
    MAX_YOB,
    MIN_K_FACTOR,
    MAX_K_FACTOR,
)
from data.print_documents.documents import (
    PlayerListPrintDocument,
)
from data.teams.team import RosterFullError
from data.tournament import Tournament
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.fide.fide_database import FideDatabase
from database.sqlite.event.event_store import (
    StoredPlayer,
    StoredTeam,
    StoredTournamentPlayer,
)
from utils import Utils
from utils.date_time import format_date
from utils.enum import (
    PlayerGender,
    TournamentRating,
    PlayerRatingType,
    PlayerTitle,
    Result,
    FormAction,
    CheckInStatus,
)
from plugins.manager import plugin_manager
from web.controllers.admin.base_event_admin_controller import (
    BaseEventAdminWebContext,
    BaseEventAdminController,
)
from web.controllers.base_controller import WebContext
from web.guards import (
    EventGuard,
    TournamentActionGuard,
    ActionGuard,
    SetByeGuard,
    PlayerTournamentActionGuard,
)
from web.messages import Message
from web.session import (
    SessionPlayersEvent,
    SessionPlayersSort,
    SessionPlayersSearchResultsId,
    SessionPlayersActiveDataSource,
    SessionPlayersAddOtherActive,
    SessionPlayersHiddenColumns,
    SessionPlayersDisabledColumns,
    SessionPlayersSearch,
    SessionPlayersFilters,
    SessionPlayersImportUseDataSource,
)
from web.utils import SelectOption

logger: Logger = get_logger()


class PlayerAdminWebContext(BaseEventAdminWebContext):
    def __init__(
        self,
        request: HTMXRequest,
        player_id: int | None = None,
        tournament_id: int | None = None,
        data_source_id: str | None = None,
        column_id: str | None = None,
        reload_event: bool = False,
    ):
        super().__init__(request, reload_event)
        if self.admin_event is None:
            raise RuntimeError('admin_event not defined')

        self.admin_player: Player | None = None
        if player_id:
            try:
                self.admin_player = self.admin_event.players_by_id[player_id]
            except KeyError:
                raise NotFoundException(f'Player [{player_id}] not found.')

        self.admin_tournament: Tournament | None = None
        if tournament_id:
            try:
                self.admin_tournament = self.admin_event.tournaments_by_id[
                    tournament_id
                ]
            except KeyError:
                raise NotFoundException(f'Tournament [{tournament_id}] not found.')

        self.admin_data_source: DataSource | None = None
        if data_source_id:
            try:
                self.admin_data_source = DataSourceManager().get_object(data_source_id)
            except KeyError:
                raise NotFoundException(f'Unknown data source [{data_source_id}].')
        self.admin_column: PlayersTabColumn | None = None
        if column_id:
            self.admin_column = self.column_handler.get_column(column_id)
            if not self.admin_column:
                raise NotFoundException(f'Unknown column [{column_id}].')
        self._filter_values_set = False

    def get_admin_tournament(self) -> Tournament:
        assert self.admin_tournament is not None
        return self.admin_tournament

    def get_admin_player(self) -> Player:
        assert self.admin_player is not None
        return self.admin_player

    def get_admin_tournament_player(self) -> TournamentPlayer:
        assert self.admin_player is not None
        return self.admin_player.single_tournament_player

    def get_admin_data_source(self) -> DataSource:
        assert self.admin_data_source is not None
        return self.admin_data_source

    def get_admin_column(self) -> PlayersTabColumn:
        assert self.admin_column is not None
        return self.admin_column

    @cached_property
    def allowed_tournaments(self) -> list[Tournament]:
        return self.client.allowed_tournaments_for_action(AuthAction.VIEW_PLAYERS_TAB)

    @property
    def player_addable_tournaments(self):
        return [
            tournament
            for tournament in self.allowed_tournaments
            if tournament.can_add_players
        ]

    @cached_property
    def column_handler(self) -> PlayersTabColumnHandler:
        event = self.get_admin_event()
        handler = PlayersTabColumnHandler(event)
        hidden_column_ids = SessionPlayersHiddenColumns(self.request, event).get()
        disabled_column_ids = SessionPlayersDisabledColumns(self.request, event).get()
        handler.set_column_states(disabled_column_ids, hidden_column_ids)
        return handler

    def set_column_filter_values(self, override: bool = False):
        if override or self._filter_values_set:
            return
        event = self.get_admin_event()
        allowed_players = list(self.client.allowed_players)
        filter_keys_by_column_id = SessionPlayersFilters(self.request, event).get()
        for column in self.column_handler.visible_columns:
            if not column.is_filtrable:
                continue
            column.set_filter_values(
                allowed_players,
                event,
                active_keys=filter_keys_by_column_id.get(column.id, []),
            )
        self._filter_values_set = True

    @cached_property
    def carry_over_fields(self) -> list[str]:
        fields = [
            'tournament_id',
            'team_id',
        ]
        plugin_manager.hook_for_event(
            self.get_admin_event(), 'insert_player_form_carry_over_field'
        )(fields=fields)
        return fields

    @property
    def default_print_document(self) -> str:
        return PlayerListPrintDocument.static_id()

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'admin_event_tab': 'admin-event-players-tab',
            'admin_player': self.admin_player,
            'admin_tournament': self.admin_tournament,
            'data_source': self.admin_data_source,
        }


class PlayerAdminController(BaseEventAdminController):
    PAGE_SIZE = 25
    search_results_by_session: dict[int, list[int]] = {}

    guards = [
        EventGuard(),
        TournamentActionGuard(AuthAction.VIEW_PLAYERS_TAB),
    ]

    @classmethod
    def filtered_players(
        cls, web_context: PlayerAdminWebContext, players: Iterable[Player]
    ) -> list[Player]:
        request = web_context.request
        event = web_context.get_admin_event()
        handler = web_context.column_handler
        web_context.set_column_filter_values()
        search = normalized_key(SessionPlayersSearch(request, event).get())
        session_filters = SessionPlayersFilters(request, event)
        if search:
            search_key_getters: list[Callable[[Player], str]] = [
                column.get_search_key for column in handler.searchable_columns
            ]
            players = [
                player
                for player in players
                if cls._matches_string_search(
                    search, ' '.join(getter(player) for getter in search_key_getters)
                )
            ]
        getters_active_keys: list[tuple[Callable[[Player], str], list[str]]] = []
        for column_id, filter_keys in session_filters.get().items():
            column = handler.get_column(column_id)
            if not column or not column.is_visible:
                session_filters.set_column_filters(column_id, [])
                continue
            active_keys = [
                filter_value.key
                for filter_value in column.filter_values
                if filter_value.is_active
            ]
            if len(active_keys) in (len(column.filter_values), 0):
                continue
            getters_active_keys.append((column.get_filter_key, active_keys))
        return [
            player
            for player in players
            if all(
                key_getter(player) in active_keys
                for key_getter, active_keys in getters_active_keys
            )
        ]

    @staticmethod
    def _matches_string_search(search: str, match: str):
        search_parts = set(search.split(' '))
        match_str = normalized_key(match)
        return all(search_part in match_str for search_part in search_parts)

    @staticmethod
    def _default_player_sort_key_function(_player: Player) -> tuple:
        return tuple()

    @classmethod
    def sorted_player_ids(
        cls, web_context: PlayerAdminWebContext, players: list[Player]
    ) -> list[int]:
        request = web_context.request
        event = web_context.get_admin_event()
        sort_column, is_asc = SessionPlayersSort(request, event).get()
        column = web_context.column_handler.get_column(sort_column)
        sort_key_function = (
            column.sort_key_function
            if column
            else cls._default_player_sort_key_function
        )
        sorted_players = sorted(
            players,
            key=lambda player: sort_key_function(player) + player.name_sort_key,
            reverse=not is_asc,
        )
        return [player.id for player in sorted_players]

    @classmethod
    def get_search_results(cls, web_context: PlayerAdminWebContext):
        request = web_context.request
        event = web_context.get_admin_event()
        session_event_uniq_id = SessionPlayersEvent(request).get()
        search_results_id = SessionPlayersSearchResultsId(request).get()
        if (
            search_results_id is None
            or session_event_uniq_id != event.uniq_id
            or search_results_id not in cls.search_results_by_session
        ):
            return cls.set_players_search_results(web_context)
        return cls.search_results_by_session[search_results_id]

    @classmethod
    def set_players_search_results(
        cls, web_context: PlayerAdminWebContext
    ) -> list[int]:
        request = web_context.request
        event = web_context.get_admin_event()
        filtered_players = cls.filtered_players(
            web_context, web_context.client.allowed_players
        )
        search_results = cls.sorted_player_ids(web_context, filtered_players)
        results_session_id = SessionPlayersSearchResultsId(request).get()
        if not results_session_id:
            results_session_id = max([0] + list(cls.search_results_by_session)) + 1
            SessionPlayersSearchResultsId(request).set(results_session_id)
        cls.search_results_by_session[results_session_id] = search_results
        SessionPlayersEvent(request).set(event.uniq_id)
        return search_results

    @classmethod
    def set_disabled_columns(cls, web_context: PlayerAdminWebContext):
        request = web_context.request
        event = web_context.get_admin_event()
        handler = web_context.column_handler
        allowed_tournaments = web_context.allowed_tournaments
        allowed_players = list(web_context.client.allowed_players)
        disabled_column_ids = [
            column.id
            for column in handler.columns
            if not column.is_enabled_for_event(event, allowed_tournaments)
            or not column.is_enabled_for_players(allowed_players)
        ]
        SessionPlayersDisabledColumns(request, event).set(disabled_column_ids)
        handler.set_column_states(
            disabled_column_ids,
            SessionPlayersHiddenColumns(request, event).get(),
        )

    @classmethod
    def delete_from_search_results(cls, request: HTMXRequest, player_id: int):
        results_session_id = SessionPlayersSearchResultsId(request).get()
        if not results_session_id:
            return
        try:
            cls.search_results_by_session[results_session_id].remove(player_id)
        except ValueError:
            pass

    # -------------------------------------------------------------------------
    # Tab
    # -------------------------------------------------------------------------

    @classmethod
    def _player_table_header_context(
        cls, web_context: PlayerAdminWebContext
    ) -> dict[str, Any]:
        request = web_context.request
        event = web_context.get_admin_event()
        web_context.set_column_filter_values()
        sort_column, is_sort_asc = SessionPlayersSort(request, event).get()
        search_results = cls.get_search_results(web_context)
        allowed_players = list(web_context.client.allowed_players)
        return {
            'nav_tab_title': _('Players ({num})').format(num=len(allowed_players)),
            'allowed_players': allowed_players,
            'filtered_player_count': len(search_results),
            'sort_column': sort_column,
            'is_sort_asc': is_sort_asc,
            'is_search_active': len(allowed_players) > len(search_results),
        }

    @classmethod
    def _player_table_page_context(
        cls, web_context: PlayerAdminWebContext, page: int = 1
    ) -> dict[str, Any]:
        search_results = cls.get_search_results(web_context)
        pages = math.ceil(len(search_results) / cls.PAGE_SIZE)
        start_index = ((page or 1) - 1) * cls.PAGE_SIZE
        end_index = (page or 1) * cls.PAGE_SIZE
        allowed_players_by_id = web_context.client.allowed_players_by_id
        players_by_index: dict[int, Player] = {}
        for index, player_id in enumerate(search_results[start_index:end_index]):
            if player := allowed_players_by_id.get(player_id, None):
                players_by_index[start_index + index + 1] = player
        template_context = {
            'players_by_index': players_by_index,
            'page': page,
            'pages': pages,
        }
        return template_context | cls._player_table_row_context(web_context)

    @classmethod
    def _player_table_row_context(
        cls, web_context: PlayerAdminWebContext
    ) -> dict[str, Any]:
        return {
            'columns': web_context.column_handler.columns,
            'visible_columns': web_context.column_handler.visible_columns,
            'player_addable_tournaments': web_context.player_addable_tournaments,
            'federations': SharlyChessConfig().federations,
        }

    @classmethod
    def _render_players_tab(cls, web_context: PlayerAdminWebContext) -> HTMXTemplate:
        request = web_context.request
        event = web_context.get_admin_event()
        cls.set_disabled_columns(web_context)
        cls.set_players_search_results(web_context)
        template_context = (
            web_context.template_context
            | cls._player_table_header_context(web_context)
            | cls._player_table_page_context(web_context)
        )
        searchable_column_names = [
            column.name for column in web_context.column_handler.searchable_columns
        ]
        template_context |= {
            'default_print_document': web_context.default_print_document,
            'data_sources': DataSourceManager().objects(),
            'search': SessionPlayersSearch(request, event).get(),
            'allowed_tournaments': web_context.allowed_tournaments,
            'enabled_columns': web_context.column_handler.enabled_columns,
            'searchable_column_names': searchable_column_names,
            'player_exporters': PlayerExporterManager().objects(),
        }
        return cls._admin_base_event_render(template_context)

    @classmethod
    def _render_players_table(cls, web_context: PlayerAdminWebContext) -> HTMXTemplate:
        cls.set_players_search_results(web_context)
        template_context = (
            web_context.template_context
            | cls._player_table_header_context(web_context)
            | cls._player_table_page_context(web_context)
        )
        return HTMXTemplate(
            template_name='/admin/players/table/table.html',
            re_swap='outerHTML',
            re_target='#players-table',
            context=web_context.template_context | template_context,
            trigger_event='close_modal',
            after='settle',
        )

    @classmethod
    def _render_player_table_row(
        cls,
        web_context: PlayerAdminWebContext,
        deleted_player_id: int | None = None,
        after_check_in: bool = False,
        close_modal: bool = True,
    ) -> HTMXTemplate:
        template_context = web_context.template_context
        admin_player = web_context.admin_player
        search_results = cls.get_search_results(web_context)
        if admin_player and not deleted_player_id:
            if cls.filtered_players(web_context, [admin_player]):
                index = (
                    search_results.index(admin_player.id) + 1
                    if admin_player.id in search_results
                    else None
                )
                if not index:
                    cls.set_players_search_results(web_context)
                template_context |= {
                    'updated_player': admin_player,
                    'index': index,
                }
            else:
                deleted_player_id = admin_player.id
        if deleted_player_id:
            if deleted_player_id in search_results:
                cls.set_players_search_results(web_context)
        template_context |= cls._player_table_header_context(web_context)
        template_context |= cls._player_table_row_context(web_context)
        template_context |= {
            'deleted_player_id': deleted_player_id,
            'after_check_in': after_check_in,
        }
        return HTMXTemplate(
            template_name='/admin/players/table/header_and_row.html',
            context=template_context,
            re_target='#replace-row-target',
            trigger_event=(
                'renumber_players_and_close_modal'
                if close_modal
                else 'renumber_players'
            ),
            after='settle',
        )

    @get(
        path='/event/{event_uniq_id:str}/players',
        name='admin-event-players-tab',
    )
    async def htmx_admin_event_players_tab(self, request: HTMXRequest) -> Template:
        return self._render_players_tab(PlayerAdminWebContext(request))

    @get(
        path='/event/{event_uniq_id:str}/players/columns',
        name='admin-event-players-columns',
    )
    async def htmx_admin_event_players_columns(
        self,
        request: HTMXRequest,
        column_ids: FromQuery[list[str]],
    ) -> Template:
        web_context = PlayerAdminWebContext(request)
        event = web_context.get_admin_event()
        handler = web_context.column_handler
        disabled_column_ids = SessionPlayersDisabledColumns(request, event).get()
        session_hidden = SessionPlayersHiddenColumns(request, event)
        current_hidden_column_ids = session_hidden.get() or []
        hidden_column_ids: list[str] = []
        for column in handler.columns:
            if not column.is_hideable or column.id in column_ids:
                continue
            # Keep hidden the disabled columns that have manually been hidden by the user
            # Preserve the other ones, which will appear if they become enabled
            if (
                column.id in disabled_column_ids
                and column.id not in current_hidden_column_ids
            ):
                continue
            hidden_column_ids.append(column.id)
        session_hidden.set(hidden_column_ids)

        session_filters = SessionPlayersFilters(request, event)
        filters = session_filters.get()
        for column_id in column_ids:
            if column_id in filters:
                del filters[column_id]
        session_filters.set(filters)
        self.set_disabled_columns(web_context)
        return self._render_players_tab(web_context)

    @get(
        path='/event/{event_uniq_id:str}/players/set-filter/{column_id:str}',
        name='admin-event-players-set-filter',
    )
    async def htmx_admin_event_players_set_filter(
        self,
        request: HTMXRequest,
        column_id: FromPath[str],
        filters: FromQuery[list[str]],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, column_id=column_id)
        event = web_context.get_admin_event()
        column = web_context.get_admin_column()
        if not column.is_filtrable:
            raise ClientException(f'Column [{column.id}] not filtrable')
        filter_keys: list[str] = []
        for filter_key in filters[1:]:
            try:
                column.get_filter_value_from_key(filter_key, event)
                filter_keys.append(filter_key)
            except ValueError:
                logger.exception(
                    f'Invalid filter key [{filter_key}] for column [{column.id}].'
                )
        SessionPlayersFilters(request, event).set_column_filters(column_id, filter_keys)
        return self._render_players_table(web_context)

    @get(
        path='/event/{event_uniq_id:str}/players/sort/{column_id:str}',
        name='admin-event-players-sort',
    )
    async def htmx_admin_event_players_sort(
        self,
        request: HTMXRequest,
        column_id: FromPath[str],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, column_id=column_id)
        event = web_context.get_admin_event()
        column = web_context.get_admin_column()
        session_sort = SessionPlayersSort(request, event)
        current_column_id, current_is_asc = session_sort.get()
        if current_column_id != column.id:
            sort_column_id = column.id
            is_asc = True
        elif current_is_asc:
            sort_column_id = column.id
            is_asc = False
        else:
            sort_column_id = ''
            is_asc = True
        session_sort.set((sort_column_id, is_asc))
        return self._render_players_table(web_context)

    @get(
        path='/event/{event_uniq_id:str}/players/search',
        name='admin-event-players-search',
    )
    async def htmx_admin_event_players_search(
        self,
        request: HTMXRequest,
        search: FromQuery[str | None] = None,
    ) -> Template:
        web_context = PlayerAdminWebContext(request)
        event = web_context.get_admin_event()
        SessionPlayersSearch(request, event).set(search)
        return self._render_players_table(web_context)

    @get(
        path='/event/{event_uniq_id:str}/players/clear-filters',
        name='admin-event-players-clear-filters',
    )
    async def htmx_admin_event_players_clear_filters(
        self, request: HTMXRequest
    ) -> Template:
        web_context = PlayerAdminWebContext(request)
        event = web_context.get_admin_event()
        SessionPlayersSearch(request, event).unset()
        SessionPlayersFilters(request, event).unset()
        SessionPlayersSearch(request, event).unset()
        SessionPlayersSort(request, event).unset()
        return self._render_players_tab(web_context)

    @get(
        path='/event/{event_uniq_id:str}/players/{page:int}',
        name='admin-event-players-page',
    )
    async def htmx_admin_event_players_page(
        self,
        request: HTMXRequest,
        page: FromPath[int],
    ) -> Template:
        web_context = PlayerAdminWebContext(request)
        template_context = self._player_table_page_context(web_context, page)
        return HTMXTemplate(
            template_name='/admin/players/table/page.html',
            context=web_context.template_context | template_context,
        )

    @get(
        path='/player-row/{event_uniq_id:str}/{player_id:int}',
        name='admin-player-row',
    )
    async def htmx_admin_player_row(
        self,
        request: HTMXRequest,
        player_id: FromPath[int],
        close_modal: FromQuery[int] = 1,
    ) -> Template:
        web_context = PlayerAdminWebContext(request, player_id)
        return self._render_player_table_row(web_context, close_modal=bool(close_modal))

    # -------------------------------------------------------------------------
    # Player Modal
    # -------------------------------------------------------------------------

    @staticmethod
    def _get_gender_options() -> dict[str, str]:
        return {
            WebContext.value_to_form_data(gender.value): gender.name
            for gender in PlayerGender
        }

    @staticmethod
    def _get_k_factor_placeholders(
        data: dict[str, str],
    ) -> dict[TournamentRating, int]:
        """The automatic coefficients (k) shown while the fields are left empty."""
        year_of_birth: int | None = None
        field = 'date_of_birth'
        try:
            date_of_birth = WebContext.form_data_to_date(data, field)
            year_of_birth = date_of_birth.year if date_of_birth else None
        except FormError:
            year_str = data.get(field, '')
            if year_str.isdigit() and len(year_str) == 4:
                year_of_birth = int(year_str)
        placeholders: dict[TournamentRating, int] = {}
        for tournament_rating in TournamentRating:
            try:
                fide_rating = WebContext.form_data_to_int(
                    data, f'{tournament_rating.form_key}_rating_fide'
                )
            except ValueError:
                fide_rating = None
            placeholders[tournament_rating] = Player.estimate_fide_rating_coefficient(
                fide_rating, year_of_birth
            )
        return placeholders

    @staticmethod
    def _k_factor_reference_date(
        web_context: PlayerAdminWebContext, data: dict[str, str] | None = None
    ) -> date:
        """The day whose FIDE rating period the k-factors are read from."""
        event = web_context.get_admin_event()
        tournament: Tournament | None = None
        if data:
            try:
                tournament_id = WebContext.form_data_to_int(data, 'tournament_id')
            except ValueError:
                tournament_id = None
            if tournament_id:
                tournament = event.tournaments_by_id.get(tournament_id)
        if tournament is None:
            tournament = web_context.admin_tournament
        if tournament is None and web_context.admin_player is not None:
            tournament = web_context.admin_player.optional_single_tournament
        return tournament.start_date if tournament else event.start_date

    @classmethod
    def _render_players_form_modal(
        cls,
        web_context: PlayerAdminWebContext,
        action: FormAction,
        old_player_id: int | None = None,
        search_stored_player: StoredPlayer | None = None,
        data: dict[str, str] | None = None,
        carry_over_data: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
        warning_message: str | None = None,
        redirect_to: str | None = None,
    ) -> Template:
        request = web_context.request
        event = web_context.get_admin_event()
        admin_player = web_context.admin_player
        template_context = web_context.template_context
        allowed_players_by_id = web_context.client.allowed_players_by_id

        if data is None:
            first_name: str | None = None
            last_name: str | None = None
            date_of_birth: str | None = None
            gender = PlayerGender.NONE.value
            ratings: dict[TournamentRating, PlayerRating] = {
                tr: PlayerRating(estimated=0) for tr in TournamentRating
            }
            title = PlayerTitle.NONE.value
            women_title = PlayerTitle.NONE.value
            federation = event.federation
            club: str | None = None
            fide_id: int | None = None
            mail: str | None = None
            phone: str | None = None
            comment: str | None = None
            owed: float = 0.0
            paid: float = 0.0
            fixed: int | None = None
            stored_plugin_data: dict[str, dict[str, Any]] = {}
            stored_player = search_stored_player
            tournament_id: int | None = None
            if not stored_player and admin_player:
                stored_player = admin_player.stored_player
            if stored_player:
                if search_stored_player or action != FormAction.REPLACE:
                    first_name = stored_player.first_name
                    last_name = stored_player.last_name
                    gender = stored_player.gender
                    date_of_birth = WebContext.value_to_date_form_data(
                        stored_player.date_of_birth
                    )
                    if stored_player.year_of_birth:
                        date_of_birth = str(stored_player.year_of_birth)
                    for tr_value, rating in stored_player.ratings.items():
                        ratings[TournamentRating(tr_value)] = (
                            PlayerRating.from_stored_value(rating)
                        )
                    title = stored_player.title
                    women_title = stored_player.women_title
                    federation = stored_player.federation
                    club = stored_player.club
                    fide_id = stored_player.fide_id or None
                # Fields unused by the search, kept on replace
                mail = stored_player.mail
                phone = stored_player.phone
                comment = stored_player.comment
                owed = stored_player.owed
                paid = stored_player.paid
                fixed = stored_player.fixed
                stored_plugin_data = stored_player.plugin_data
            if action == FormAction.CREATE:
                if len(event.sorted_not_finished_tournaments) == 1:
                    tournament_id = event.sorted_not_finished_tournaments[0].id
            else:
                assert admin_player is not None
                if event.is_team_event:
                    tournament_id = (
                        admin_player.team.tournament_id
                        if admin_player.team is not None
                        and admin_player.team.tournament_id is not None
                        else None
                    )
                else:
                    tournament_id = admin_player.single_tournament.id

            rating_data: dict[str, Any] = {}
            for tournament_rating in TournamentRating:
                rating_ = ratings[tournament_rating]
                key = tournament_rating.form_key
                rating_data |= {
                    f'{key}_rating_fide': rating_.fide or None,
                    f'{key}_rating_national': rating_.national or None,
                    f'{key}_rating_estimated': rating_.estimated or None,
                    f'{key}_rating_k': rating_.k_factor,
                }

            plugin_form_data: dict[str, str] = {}
            for (
                plugin_id,
                plugin_data_class,
            ) in Player.plugin_data_class_by_plugin_id().items():
                plugin_form_data |= plugin_data_class.from_stored_value(
                    stored_plugin_data.get(plugin_id, {})
                ).to_form_data(action=action if not search_stored_player else None)

            team_id_value: int | None = None
            if event.is_team_event:
                if admin_player is not None:
                    team_id_value = admin_player.team_id
                elif action == FormAction.CREATE and len(event.sorted_teams) == 1:
                    team_id_value = event.sorted_teams[0].id
            data = WebContext.values_dict_to_form_data(
                {
                    'last_name': last_name,
                    'first_name': first_name,
                    'gender': gender,
                    'tournament_id': tournament_id,
                    'team_id': team_id_value or '',
                    'title': title,
                    'women_title': women_title,
                    'federation': federation,
                    'fide_id': fide_id,
                    'club': club,
                    'mail': mail,
                    'phone': phone,
                    'comment': comment,
                    'owed': owed,
                    'paid': paid,
                    'fixed': fixed or None,
                    'date_of_birth': date_of_birth,
                    'redirect_to': redirect_to,
                }
                | rating_data
                | plugin_form_data
                | (carry_over_data or {})
            )
        if errors is None:
            errors = {}
        tournaments = web_context.player_addable_tournaments
        tournament_options: dict[str, str] = {}
        if action == FormAction.CREATE:
            # force the choice of the tournament on player creation if several tournaments
            if len(tournaments) > 1:
                tournament_options |= {'': '-'}
        else:
            assert admin_player is not None
            player_tournament = admin_player.optional_single_tournament
            if player_tournament is not None and player_tournament not in tournaments:
                tournaments.insert(0, player_tournament)
        tournament_options |= web_context.get_tournament_options(tournaments)

        # A player already placed on a board can't change team — moving
        # them would orphan their board(s). Lock the team picker then.
        team_locked = (
            event.is_team_event
            and admin_player is not None
            and admin_player.has_been_paired
        )

        team_options: dict[str, str | dict[str, str]] = {'': '-'}
        if event.is_team_event:
            # Group teams by tournament so the picker matches the
            # team-admin layout. Teams not yet attached to a tournament
            # land under "Unassigned".
            tournaments_by_id = event.tournaments_by_id
            unassigned_teams_found: bool = any(
                team.tournament_id is None
                or team.tournament_id not in tournaments_by_id
                for team in event.sorted_teams
            )
            multi_labels: bool = len(tournaments_by_id) > 1 or unassigned_teams_found
            if multi_labels:
                teams_by_tournament_label: dict[str, dict[str, str]] = {}
                for team in event.sorted_teams:
                    if (
                        team.tournament_id is not None
                        and team.tournament_id in tournaments_by_id
                    ):
                        label = tournaments_by_id[team.tournament_id or 0].name
                    else:
                        label = _('Unassigned *** TEAMS NOT ASSIGNED TO A TOURNAMENT')
                    teams_by_tournament_label.setdefault(label, {})[str(team.id)] = (
                        team.name
                    )
                # Sorted alphabetically so the order is stable across renders.
                for label in sorted(teams_by_tournament_label):
                    team_options[label] = teams_by_tournament_label[label]
            else:
                for team in event.sorted_teams:
                    team_options[str(team.id)] = team.name
        plugin_templates_by_section: dict[str, list[str]] = defaultdict(list)
        plugin_manager.hook_for_event(event, 'insert_player_form_fields_template')(
            templates_by_section=plugin_templates_by_section
        )
        k_factor_placeholders = cls._get_k_factor_placeholders(data)
        template_context |= {
            'gender_options': cls._get_gender_options(),
            'tournament_ratings_strings': {
                TournamentRating.STANDARD: {
                    'label': _('Standard:'),
                    'help': _(
                        'The rating used when the time control is at least 60 minutes.'
                    ),
                },
                TournamentRating.RAPID: {
                    'label': _('Rapid:'),
                    'help': _(
                        'The rating used when the time control is more than 10 minutes and less than 60 minutes.'
                    ),
                },
                TournamentRating.BLITZ: {
                    'label': _('Blitz:'),
                    'help': _(
                        'The rating used when the time control is at most 10 minutes.'
                    ),
                },
            },
            'rating_type_labels': {
                prt.form_key: prt.short_name for prt in PlayerRatingType
            },
            'k_factor_placeholders': k_factor_placeholders,
            'min_k_factor': MIN_K_FACTOR,
            'max_k_factor': MAX_K_FACTOR,
            'title_options': {
                str(t.value): f'{t.short_name} - {t.name}'
                if t.short_name
                else f'{t.name}'
                for t in PlayerTitle.open_titles()
            },
            'women_title_options': {
                str(t.value): f'{t.short_name} - {t.name}'
                if t.short_name
                else f'{t.name}'
                for t in PlayerTitle.women_titles()
            },
            # The women title field is only shown for women players.
            'woman_gender_value': PlayerGender.WOMAN.value,
            'federation_options': cls._get_federation_options(),
            'tournament_options': tournament_options,
            'team_options': team_options,
            'team_locked': team_locked,
            'is_team_event': event.is_team_event,
            'selected_data_source': SessionPlayersActiveDataSource(request).get(),
            'plugin_templates_by_section': plugin_templates_by_section,
            'previous_player': (
                allowed_players_by_id.get(old_player_id, None)
                if action == 'create' and old_player_id
                else None
            ),
            'data_sources': DataSourceManager().objects(),
            'warning_message': warning_message,
            'add_other_active': SessionPlayersAddOtherActive(request).get(),
            'modal': 'player',
            'action': action,
            'data': data,
            'errors': errors,
        }
        template_context |= Utils.concat_dicts(
            plugin_manager.hook_for_event(event, 'get_player_form_template_context')(
                web_context=web_context
            )
        )
        return cls._admin_base_event_render(template_context)

    @get(
        path='/player-modal/create/{event_uniq_id:str}',
        name='admin-player-create-modal',
    )
    async def htmx_admin_player_create_modal(self, request: HTMXRequest) -> Template:
        return self._render_players_form_modal(
            PlayerAdminWebContext(request), FormAction.CREATE
        )

    @staticmethod
    async def get_search_stored_player(
        data_source: DataSource,
        player_source_id: str,
        k_factor_reference_date: date,
    ) -> tuple[StoredPlayer | None, dict[str, str]]:
        errors: dict[str, str] = {}
        stored_player: StoredPlayer | None = None
        if not data_source.is_available:
            raise ClientException(f'Data source [{data_source.id}] is not available.')
        try:
            stored_player = await data_source.fetch_player(
                player_source_id=player_source_id,
                with_arbiter_title=False,
                k_factor_reference_date=k_factor_reference_date,
            )
            if not stored_player:
                raise NotFoundException(
                    f'Player [{player_source_id}] unexpectedly '
                    f'not found in data source [{data_source.id}]'
                )
        except SharlyChessException:
            errors[data_source.search_element_name] = _(
                'Connection to the data source [{data_source}] failed. '
                'Consult the logs for more details.'
            ).format(data_source=data_source.id)
        return stored_player, errors

    @post(
        path='/player-modal/from-search/{event_uniq_id:str}/{data_source_id:str}/{player_source_id:str}',
        name='player-modal-from-search',
    )
    async def htmx_player_modal_from_search(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        data_source_id: FromPath[str],
        player_source_id: FromPath[str],
    ) -> Template:
        player_id = WebContext.form_data_to_int(data, 'player_id')
        web_context = PlayerAdminWebContext(
            request, player_id, data_source_id=data_source_id
        )
        stored_player, errors = await self.get_search_stored_player(
            web_context.get_admin_data_source(),
            player_source_id,
            self._k_factor_reference_date(web_context, data),
        )
        return self._render_players_form_modal(
            web_context,
            action=FormAction.REPLACE if player_id else FormAction.CREATE,
            search_stored_player=stored_player,
            carry_over_data={
                field: str(data.get(field, ''))
                for field in web_context.carry_over_fields
            },
            errors=errors,
        )

    @get(
        path='/player-modal/{action:str}/{event_uniq_id:str}/{player_id:int}',
        name='admin-player-modal',
        guards=[PlayerTournamentActionGuard(AuthAction.UPDATE_PLAYERS)],
    )
    async def htmx_admin_player_modal(
        self,
        request: HTMXRequest,
        action: FromPath[str],
        player_id: FromPath[int],
        redirect_to: FromQuery[str | None] = None,
    ) -> Template:
        web_context = PlayerAdminWebContext(request, player_id)
        return self._render_players_form_modal(
            web_context, FormAction(action), redirect_to=redirect_to
        )

    @get(
        path='/player-delete-modal/{event_uniq_id:str}/{player_id:int}',
        name='admin-player-delete-modal',
        guards=[PlayerTournamentActionGuard(AuthAction.UPDATE_PLAYERS)],
    )
    async def htmx_admin_player_delete_modal(
        self,
        request: HTMXRequest,
        player_id: FromPath[int],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, player_id)
        return self._admin_base_event_render(
            web_context.template_context | {'modal': 'player-delete'}
        )

    @classmethod
    def _read_player_form_data(
        cls,
        web_context: PlayerAdminWebContext,
        action: FormAction,
        data: dict[str, str],
    ) -> tuple[StoredPlayer | None, dict[str, str]]:
        event = web_context.get_admin_event()
        player = web_context.admin_player
        errors = cls._validate_player_form_data(web_context, action, data)
        if errors:
            return None, errors
        if event.is_team_event:
            team_id = WebContext.form_data_to_int(data, 'team_id')
            team = event.teams_by_id.get(team_id) if team_id else None
            tournament = team.tournament if team is not None else None
            stored_player = cls._stored_player_from_data(data, tournament, player)
            if any(
                cls._matches_existing_player(
                    stored_player, p, player.id if player else None
                )
                for p in event.players_by_id.values()
            ):
                errors['alert'] = _('This player already exists in the event.')
                return None, errors
            return stored_player, errors
        tournament = event.tournaments_by_id[int(data['tournament_id'])]
        stored_player = cls._stored_player_from_data(data, tournament, player)
        if event.get_player_duplicate(
            stored_player, tournament, player.id if player else None
        ):
            errors['alert'] = (
                _('This player already exists in tournament [{tournament}].').format(
                    tournament=tournament.name
                )
                if event.allow_multi_tournament_players
                else _('This player already exists in the event.')
            )
            return None, errors
        return stored_player, errors

    @staticmethod
    def _matches_existing_player(
        stored: StoredPlayer, existing: Player, current_player_id: int | None
    ) -> bool:
        if existing.id == current_player_id:
            return False
        if (
            stored.first_name == existing.first_name
            and stored.last_name == existing.last_name
        ):
            return True
        return False

    @classmethod
    def _validate_player_form_data(
        cls,
        web_context: PlayerAdminWebContext,
        action: FormAction,
        data: dict[str, str],
    ) -> dict[str, str]:
        event = web_context.get_admin_event()
        errors: dict[str, str] = {}
        if event.is_team_event:
            field = 'team_id'
            team_id = WebContext.form_data_to_int(data, field)
            if team_id and team_id not in event.teams_by_id:
                errors[field] = _('Unknown team.')
            elif team_id:
                target_team = event.teams_by_id[team_id]
                player = web_context.admin_player
                already_on_team = player is not None and player.team_id == team_id
                max_size = target_team.roster_max_size
                if (
                    not already_on_team
                    and max_size is not None
                    and len(target_team.players) >= max_size
                ):
                    errors[field] = _(
                        'Team [{team}] is full ({max} players max).'
                    ).format(team=target_team.name, max=max_size)
        else:
            tournament: Tournament | None = None
            field = 'tournament_id'
            try:
                tournament_id = WebContext.form_data_to_int(data, field)
                if not tournament_id:
                    raise ValueError('Tournament ID not supplied')
                tournament = event.tournaments_by_id[tournament_id]
            except (ValueError, KeyError):
                errors[field] = _('Please choose the tournament.')
            if action != FormAction.CREATE and tournament is not None:
                player = web_context.get_admin_player()
                if tournament.id != player.single_tournament.id:
                    try:
                        cls._validate_player_tournament_move(
                            event,
                            player,
                            player.single_tournament,
                            tournament,
                        )
                    except ValueError as e:
                        errors[field] = str(e)

        last_name = WebContext.form_data_to_str(data, field := 'last_name')
        if not last_name:
            errors[field] = _('This field is required.')
        yob: int | None = None
        try:
            date_of_birth = WebContext.form_data_to_date(data, field := 'date_of_birth')
            if date_of_birth:
                yob = date_of_birth.year
        except FormError:
            year_str = data.get(field, '')
            if year_str:
                if not year_str.isdigit() or len(year_str) != 4:
                    errors[field] = _(
                        'Invalid date format (expected: {format}).'
                    ).format(
                        format=_('YYYY or {date_format}').format(
                            date_format=SharlyChessConfig().date_formatter.name
                        ),
                    )
                else:
                    yob = int(year_str)
        if yob is not None and not (MIN_YOB <= yob <= MAX_YOB):
            errors[field] = _(
                'Invalid year of birth (expected: {min} - {max}).'
            ).format(min=MIN_YOB, max=MAX_YOB)

        try:
            if value := WebContext.form_data_to_str(data, field := 'gender'):
                PlayerGender(value)
        except ValueError:
            # should never happen, not translated.
            errors[field] = f'Invalid gender value [{data[field]}].'
            data[field] = ''
        try:
            if value := WebContext.form_data_to_str(data, field := 'title'):
                PlayerTitle(value)
        except ValueError:
            # should never happen, not translated.
            errors[field] = f'Invalid title value [{data[field]}].'
            data[field] = ''
        try:
            if value := WebContext.form_data_to_str(data, field := 'women_title'):
                PlayerTitle(value)
        except ValueError:
            # should never happen, not translated.
            errors[field] = f'Invalid title value [{data[field]}].'
            data[field] = ''
        federation = WebContext.form_data_to_str(data, field := 'federation', '')
        if federation not in SharlyChessConfig().federations:
            # should never happen, not translated.
            errors[field] = f'Invalid federation value [{data[field]}].'
            data[field] = ''
        try:
            WebContext.form_data_to_int(data, field := 'fide_id', minimum=1)
        except ValueError:
            errors[field] = _('Invalid FIDE ID [{fide_id}].').format(
                fide_id=data[field]
            )
        try:
            WebContext.form_data_to_mail(data, field := 'mail')
        except ValueError:
            errors[field] = _('Invalid mail [{mail}].').format(mail=data[field])
        try:
            WebContext.form_data_to_float(data, field := 'owed')
        except ValueError:
            errors[field] = _('Invalid amount [{amount}].').format(amount=data[field])
        try:
            WebContext.form_data_to_float(data, field := 'paid')
        except ValueError:
            errors[field] = _('Invalid amount [{amount}].').format(amount=data[field])
        try:
            WebContext.form_data_to_int(data, field := 'fixed', minimum=1)
        except ValueError:
            errors[field] = _('Invalid fixed board number [{fixed_board}].').format(
                fixed_board=data[field]
            )
        for tr in TournamentRating:
            for prt in PlayerRatingType:
                try:
                    WebContext.form_data_to_int(
                        data,
                        field := f'{tr.form_key}_rating_{prt.form_key}',
                        minimum=prt.min_value,
                        maximum=prt.max_value,
                    )
                except ValueError:
                    errors[field] = _(
                        'Invalid {rating_type} rating [{rating}] (expected in range [{min}-{max}]).'
                    ).format(
                        rating_type=prt.name,
                        rating=data[field],
                        min=prt.min_value,
                        max=prt.max_value,
                    )
        for tr in TournamentRating:
            try:
                WebContext.form_data_to_int(
                    data,
                    field := f'{tr.form_key}_rating_k',
                    minimum=MIN_K_FACTOR,
                    maximum=MAX_K_FACTOR,
                )
            except ValueError:
                errors[field] = _(
                    'Invalid coefficient (k) [{k_factor}] (expected in range [{min}-{max}]).'
                ).format(
                    k_factor=data[field],
                    min=MIN_K_FACTOR,
                    max=MAX_K_FACTOR,
                )
        plugin_manager.hook_for_event(event, 'validate_player_form_fields')(
            data=data, errors=errors
        )
        return errors

    @classmethod
    def _stored_player_from_data(
        cls,
        data: dict[str, str],
        tournament: Tournament | None,
        player: Player | None = None,
    ) -> StoredPlayer:
        date_of_birth: date | None = None
        year_of_birth: int | None = None
        field = 'date_of_birth'
        try:
            date_of_birth = WebContext.form_data_to_date(data, field)
        except FormError:
            year_of_birth = WebContext.form_data_to_int(data, field)

        plugin_data: dict[str, dict[str, Any]] = {}
        for (
            plugin_id,
            plugin_data_class,
        ) in Player.plugin_data_class_by_plugin_id().items():
            previous_object = None
            if player:
                previous_object = player.plugin_data.get(plugin_id)
            plugin_data[plugin_id] = plugin_data_class.from_form_data(
                data, previous_object=previous_object
            ).to_stored_value()

        return StoredPlayer(
            id=None,
            first_name=(WebContext.form_data_to_str(data, 'first_name') or '').title(),
            last_name=(WebContext.form_data_to_str(data, 'last_name') or '').upper(),
            date_of_birth=date_of_birth,
            year_of_birth=year_of_birth,
            gender=WebContext.form_data_to_str(data, 'gender')
            or PlayerGender.NONE.value,
            mail=WebContext.form_data_to_str(data, 'mail'),
            phone=WebContext.form_data_to_str(data, 'phone'),
            comment=data.get('comment'),
            owed=WebContext.form_data_to_float(data, 'owed') or 0.0,
            paid=WebContext.form_data_to_float(data, 'paid') or 0.0,
            title=WebContext.form_data_to_str(data, 'title') or PlayerTitle.NONE.value,
            women_title=WebContext.form_data_to_str(data, 'women_title')
            or PlayerTitle.NONE.value,
            ratings={
                tr.value: PlayerRating(
                    estimated=WebContext.form_data_to_int(
                        data, f'{tr.form_key}_rating_estimated'
                    )
                    or None,
                    national=WebContext.form_data_to_int(
                        data, f'{tr.form_key}_rating_national'
                    )
                    or None,
                    fide=WebContext.form_data_to_int(data, f'{tr.form_key}_rating_fide')
                    or None,
                    k_factor=WebContext.form_data_to_int(
                        data, f'{tr.form_key}_rating_k'
                    ),
                ).stored_value
                for tr in TournamentRating
            },
            fide_id=WebContext.form_data_to_int(data, 'fide_id'),
            federation=WebContext.form_data_to_str(data, 'federation') or '',
            club=(WebContext.form_data_to_str(data, 'club') or '').strip(),
            fixed=WebContext.form_data_to_int(data, 'fixed'),
            # Carry the existing team membership through the rebuild; team
            # changes are applied separately (and skipped for paired
            # players) so it must not be wiped here.
            team_id=player.team_id if player else None,
            team_index=player.team_index if player else None,
            plugin_data=plugin_data,
            check_in=(
                player.check_in
                if player
                else (tournament.default_player_check_in if tournament else False)
            ),
        )

    @post(
        path='/player-create/{event_uniq_id:str}',
        name='admin-player-create',
        guard=[TournamentActionGuard(AuthAction.ADD_PLAYERS, search_form=True)],
    )
    async def htmx_admin_player_create(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = PlayerAdminWebContext(request)
        event = web_context.get_admin_event()
        action = FormAction.CREATE
        add_other = WebContext.resolve_add_other(
            data, SessionPlayersAddOtherActive(request)
        )

        stored_player, errors = self._read_player_form_data(web_context, action, data)
        if not stored_player:
            return self._render_players_form_modal(
                web_context, action, data=data, errors=errors
            )
        warning_message: str | None = None
        if event.is_team_event:
            team_id = WebContext.form_data_to_int(data, 'team_id')
            player_id = event.add_player(stored_player, [])
            self.set_players_search_results(web_context)
            if team_id and team_id in event.teams_by_id:
                team = event.teams_by_id[team_id]
                event_player = event.players_by_id[player_id]
                try:
                    with EventDatabase(event.uniq_id, True) as database:
                        team.add_player(event_player, database)
                        tournament = team.tournament
                        if tournament is not None:
                            tournament.resort_teams(database)
                except RosterFullError as err:
                    warning_message = _(
                        'Player [{player}] has been created, but team '
                        '[{team}] is full ({max} players max).'
                    ).format(
                        player=event_player.full_name,
                        team=team.name,
                        max=err.max_size,
                    )
        else:
            tournament_id = WebContext.form_data_to_int(data, 'tournament_id') or 0
            tournament = event.tournaments_by_id[tournament_id]
            player_id = event.add_player(stored_player, [tournament])
            self.set_players_search_results(web_context)
            player = tournament.tournament_players_by_id[player_id]
            if not player.matches_tournament_criteria:
                warning_message = _(
                    'Player [{player}] has been created, but '
                    'does not match tournament criteria: {names}'
                ).format(
                    player=player.full_name,
                    names=player.failing_tournament_criteria_message,
                )

        if add_other:
            return self._render_players_form_modal(
                web_context,
                FormAction.CREATE,
                old_player_id=player_id,
                warning_message=warning_message,
                carry_over_data={
                    field: str(data.get(field, ''))
                    for field in web_context.carry_over_fields
                },
            )
        if warning_message:
            Message.warning(request, warning_message)
        else:
            created_player = event.players_by_id[player_id]
            Message.success(
                request,
                _('Player [{player}] has been created.').format(
                    player=created_player.full_name
                ),
            )
        return self._render_players_tab(web_context)

    def _update_player(
        self,
        web_context: PlayerAdminWebContext,
        data: dict[str, str],
        action: FormAction,
    ) -> Template | Redirect:
        request = web_context.request
        event = web_context.get_admin_event()
        player = web_context.get_admin_player()
        stored_player, errors = self._read_player_form_data(web_context, action, data)
        if not stored_player:
            return self._render_players_form_modal(
                web_context, action, data=data, errors=errors
            )
        event.update_player(player, stored_player)
        if event.is_team_event:
            # Team membership is set via the team picker; a paired player's
            # team is locked (moving them would orphan their boards), so we
            # only reassign when not yet paired. Team events never use the
            # individual tournament-assignment path below.
            if not player.has_been_paired:
                team_id = WebContext.form_data_to_int(data, 'team_id')
                new_team = event.teams_by_id.get(team_id) if team_id else None
                current_team = player.team
                if new_team is not current_team:
                    try:
                        with EventDatabase(event.uniq_id, True) as database:
                            if current_team is not None and new_team is None:
                                current_team.remove_player(player, database)
                            elif new_team is not None:
                                new_team.add_player(player, database)
                            for affected in (current_team, new_team):
                                if affected is not None and affected.tournament:
                                    affected.tournament.resort_teams(database)
                    except RosterFullError:
                        # Normally prevented by _validate_player_form_data
                        # (which keeps the modal open with a field error);
                        # this is just a safety net against races.
                        pass
        else:
            tournament_id = WebContext.form_data_to_int(data, 'tournament_id') or 0
            tournament = event.tournaments_by_id[tournament_id]
            previous_tournament = player.single_tournament
            if tournament.id != previous_tournament.id:
                event.move_player_to_tournament(player, tournament)

        redirect_to = WebContext.form_data_to_str(data, 'redirect_to')
        if redirect_to:
            return Redirect(redirect_to, status_code=303)

        web_context = PlayerAdminWebContext(request, player.id, reload_event=True)
        return self._render_player_table_row(web_context)

    @patch(
        path='/player-update/{event_uniq_id:str}/{player_id:int}',
        name='admin-player-update',
        guard=[
            TournamentActionGuard(AuthAction.UPDATE_PLAYERS, search_form=True),
            PlayerTournamentActionGuard(AuthAction.UPDATE_PLAYERS),
        ],
    )
    async def htmx_admin_player_update(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        player_id: FromPath[int],
    ) -> Template | Redirect:
        return self._update_player(
            PlayerAdminWebContext(request, player_id), data, FormAction.UPDATE
        )

    @patch(
        path='/player-replace/{event_uniq_id:str}/{player_id:int}',
        name='admin-player-replace',
        guard=[
            TournamentActionGuard(AuthAction.UPDATE_PLAYERS, search_form=True),
            PlayerTournamentActionGuard(AuthAction.UPDATE_PLAYERS),
        ],
    )
    async def htmx_admin_player_replace(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        player_id: FromPath[int],
    ) -> Template | Redirect:
        return self._update_player(
            PlayerAdminWebContext(request, player_id), data, FormAction.UPDATE
        )

    @delete(
        path='/player-delete/{event_uniq_id:str}/{player_id:int}',
        name='admin-player-delete',
        guard=[PlayerTournamentActionGuard(AuthAction.DELETE_PLAYERS)],
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_player_delete(
        self,
        request: HTMXRequest,
        player_id: FromPath[int],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, player_id)
        player = web_context.get_admin_player()
        tournament_player = player.optional_single_tournament_player
        event = web_context.get_admin_event()
        deleted_player_id: int | None = None
        if tournament_player is not None and tournament_player.has_real_pairings:
            Message.error(
                request,
                _(
                    'Player [{player}] has pairings in tournament [{tournament}].'
                ).format(
                    player=player.full_name,
                    tournament=tournament_player.tournament.name,
                ),
            )
        else:
            event.delete_player(player)
            deleted_player_id = player.id
        return self._render_player_table_row(
            web_context, deleted_player_id=deleted_player_id
        )

    # -------------------------------------------------------------------------
    # Record modal
    # -------------------------------------------------------------------------

    @staticmethod
    def _get_bye_options(
        client: Client, tournament_player: TournamentPlayer, round_: int
    ) -> dict[str, SelectOption]:
        tournament = tournament_player.tournament
        hpb_disabled_message: str | None = None
        fpb_disabled_message: str | None = None
        if not client.can_set_half_point_bye(tournament.id):
            hpb_disabled_message = _('You are not allowed to set Half-Point Byes.')
        if not client.can_set_full_point_bye(tournament.id):
            fpb_disabled_message = _('You are not allowed to set Full-Point Byes.')
        current_byes = tournament_player.byes_count
        if current_byes + 1 > tournament.max_byes:
            hpb_disabled_message = _(
                'Not enough byes available to set a Half-Point Bye (required: 1).'
            )
        if current_byes + 2 > tournament.max_byes:
            fpb_disabled_message = _(
                'Not enough byes available to set a Full-Point Bye (required: 2).'
            )
        if round_ > tournament.rounds - tournament.last_rounds_no_byes:
            message = ngettext(
                "Byes can't be set for the last round of the tournament.",
                "Byes can't be set for the last {rounds} rounds of the tournament.",
                tournament.last_rounds_no_byes,
            ).format(rounds=tournament.last_rounds_no_byes)
            hpb_disabled_message = message
            fpb_disabled_message = message
        bye_options: dict[Result, SelectOption] = {
            Result.NO_RESULT: SelectOption('-'),
            Result.ZERO_POINT_BYE: SelectOption(_('Zero-Point Bye')),
            Result.HALF_POINT_BYE: SelectOption(
                _('Half-Point Bye'),
                tooltip=hpb_disabled_message,
                disabled=bool(hpb_disabled_message),
            ),
            Result.FULL_POINT_BYE: SelectOption(
                _('Full-Point Bye (deprecated)'),
                tooltip=fpb_disabled_message,
                disabled=bool(fpb_disabled_message),
                classes='' if fpb_disabled_message else 'text-danger',
            ),
        }
        return {
            str(result.value): select_option
            for result, select_option in bye_options.items()
        }

    @classmethod
    def _render_player_records_modal(
        cls, web_context: PlayerAdminWebContext
    ) -> HTMXTemplate:
        player = web_context.get_admin_player()
        tournament = player.single_tournament
        tournament_player = player.single_tournament_player
        data = {
            f'round_{round_}_result': WebContext.value_to_form_data(
                tournament_player.pairings[round_].result.value
            )
            for round_ in range(
                max(1, tournament.current_round),
                tournament.rounds + 1,
            )
        }
        template_context = {
            'get_bye_options': cls._get_bye_options,
            'modal': 'record',
            'data': data,
        }
        return cls._admin_base_event_render(
            web_context.template_context | template_context
        )

    def _set_player_participation(
        self,
        web_context: PlayerAdminWebContext,
        withdraw: bool = False,
    ) -> Template:
        tournament = web_context.get_admin_tournament()
        player = web_context.get_admin_player().single_tournament_player

        # If there aren't any pairings, then the round for the bye is the first round
        round_for_participation = tournament.current_round or 1
        if not withdraw and tournament.round_has_pairings(round_for_participation):
            # If returning to tournament and pairings for this round, then start setting removing ZPBs from the next round only
            round_for_participation += 1
        result = Result.ZERO_POINT_BYE if withdraw else Result.NO_RESULT
        new_byes = {
            round_: result
            for round_ in range(
                round_for_participation,
                tournament.rounds + 1,
            )
            if player.pairings[round_].unpaired
        }
        tournament.set_player_byes(player, new_byes)
        tournament.check_in_player(player, not withdraw)
        return self._render_player_records_modal(web_context)

    @get(
        path='/record-modal/{event_uniq_id:str}/{player_id:int}',
        name='admin-record-modal',
        guards=[PlayerTournamentActionGuard(AuthAction.UPDATE_PLAYERS_HISTORY)],
    )
    async def htmx_admin_record_modal(
        self,
        request: HTMXRequest,
        player_id: FromPath[int],
    ) -> Template:
        return self._render_player_records_modal(
            PlayerAdminWebContext(request, player_id)
        )

    @patch(
        path='/records/check-in-player/{event_uniq_id:str}/{player_id:int}',
        name='records-check-in-player',
        guard=[PlayerTournamentActionGuard(AuthAction.CHECK_IN_PLAYERS)],
    )
    async def htmx_records_check_in_player(
        self,
        request: HTMXRequest,
        channels: NamedDependency[ChannelsPlugin],
        player_id: FromPath[int],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, player_id)
        player = web_context.get_admin_tournament_player()
        tournament = player.tournament
        tournament.check_in_player(player, not player.check_in)
        self.publish_new_checkin(channels, tournament)
        return self._render_player_records_modal(web_context)

    @patch(
        path='/records/withdraw-player/{event_uniq_id:str}/{player_id:int}',
        name='records-withdraw-player',
        guards=[TournamentActionGuard(AuthAction.SET_ZPB)],
    )
    async def htmx_withdraw_player(
        self,
        request: HTMXRequest,
        player_id: FromPath[int],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, player_id)
        player = web_context.get_admin_tournament_player()
        player.tournament.set_player_participation(player, withdraw=True)
        return self._render_player_records_modal(web_context)

    @patch(
        path='/records/return-player/{event_uniq_id:str}/{player_id:int}',
        name='records-return-player',
        guards=[TournamentActionGuard(AuthAction.SET_ZPB)],
    )
    async def htmx_return_player(
        self,
        request: HTMXRequest,
        player_id: FromPath[int],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, player_id)
        player = web_context.get_admin_tournament_player()
        player.tournament.set_player_participation(player)
        return self._render_player_records_modal(web_context)

    @patch(
        path='/player-set-bye/{event_uniq_id:str}/{player_id:int}/{round:int}',
        name='admin-player-set-bye',
        guard=[SetByeGuard()],
    )
    async def htmx_player_set_bye(
        self,
        request: HTMXRequest,
        player_id: FromPath[int],
        round: FromPath[int],
        result: FromQuery[int],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, player_id)
        player = web_context.get_admin_player()
        player.single_tournament.set_player_byes(
            player.single_tournament_player, {round: Result(result)}
        )
        return self._render_player_records_modal(web_context)

    # -------------------------------------------------------------------------
    # Check-in/out
    # -------------------------------------------------------------------------

    @classmethod
    def render_check_in_modal(
        cls,
        web_context: PlayerAdminWebContext,
        message: str | None = None,
        message_type: str | None = None,
    ) -> HTMXTemplate:
        event = web_context.get_admin_event()
        template_context = web_context.template_context
        tournaments = web_context.allowed_tournaments
        total_check_in_status_grouped_counts = Counter[CheckInStatus]()
        for tournament in tournaments:
            for status in CheckInStatus:
                total_check_in_status_grouped_counts[status] += (
                    tournament.check_in_status_grouped_counts[status]
                )
        total_player_count = len(web_context.client.allowed_players)
        plugin_columns = plugin_manager.hook_for_event(
            event, 'get_check_in_table_column'
        )()
        ordered_statuses = [
            CheckInStatus.ABSENT,
            CheckInStatus.PRESENT,
            CheckInStatus.NEXT_ROUND_BYE,
        ]
        template_context |= {
            'modal': 'check-in-tournaments',
            'allowed_tournaments': tournaments,
            'plugin_columns': plugin_columns,
            'total_check_in_status_grouped_counts': total_check_in_status_grouped_counts,
            'total_player_count': total_player_count,
            'ordered_statuses': ordered_statuses,
            'message': message,
            'message_type': message_type,
        }
        return cls._admin_base_event_render(template_context)

    @get(
        path='/check-in/tournaments-modal/{event_uniq_id:str}',
        name='check-in-tournaments-modal',
    )
    async def htmx_check_in_tournaments_modal(self, request: HTMXRequest) -> Template:
        web_context = PlayerAdminWebContext(request)
        event = web_context.get_admin_event()
        plugin_manager.hook_for_event(
            event, 'on_before_load_tournaments_check_in_modal'
        )(event=event)
        return self.render_check_in_modal(web_context)

    @classmethod
    def publish_new_checkin(cls, channels: ChannelsPlugin, tournament: Tournament):
        event = tournament.event
        channels.publish(
            {'event': f'new-checkins|{event.uniq_id}', 'data': ''},
            ['ws'],
        )
        channels.publish(
            {'event': f'new-checkins|{event.uniq_id}|{tournament.id}', 'data': ''},
            ['ws'],
        )

    @patch(
        path='/player-table/check-in-player/{event_uniq_id:str}/{player_id:int}',
        name='player-table-check-in-player',
        guard=[PlayerTournamentActionGuard(AuthAction.CHECK_IN_PLAYERS)],
    )
    async def htmx_player_table_check_in_player(
        self,
        request: HTMXRequest,
        channels: NamedDependency[ChannelsPlugin],
        player_id: FromPath[int],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, player_id)
        player = web_context.get_admin_tournament_player()
        tournament = player.tournament
        status = player.check_in_status
        if status in (CheckInStatus.ABSENT, CheckInStatus.PRESENT):
            tournament.check_in_player(player, status == CheckInStatus.ABSENT)
        elif status == CheckInStatus.WITHDRAWN:
            tournament.set_player_participation(player)
        else:
            tournament.set_player_byes(
                player, {tournament.current_round + 1: Result.NO_RESULT}
            )
            tournament.check_in_player(player, True)
        self.publish_new_checkin(channels, tournament)
        return self._render_player_table_row(web_context, after_check_in=True)

    @get(
        path='/check-in/player-modal/{event_uniq_id:str}/{player_id:int}',
        name='check-in-player-modal',
        guard=[PlayerTournamentActionGuard(AuthAction.CHECK_IN_PLAYERS)],
    )
    async def htmx_check_in_player_modal(
        self,
        request: HTMXRequest,
        player_id: FromPath[int],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, player_id=player_id)
        return self._admin_base_event_render(
            web_context.template_context | {'modal': 'check-in-player'}
        )

    @get(
        path='/check-in/tournament-reset-modal/{event_uniq_id:str}/{tournament_id:int}',
        name='check-in-tournament-reset-modal',
        guard=[PlayerTournamentActionGuard(AuthAction.CHECK_IN_PLAYERS)],
    )
    async def htmx_check_in_tournament_reset_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, tournament_id=tournament_id)
        return self._admin_base_event_render(
            web_context.template_context | {'modal': 'check-in-tournament-reset'}
        )

    @post(
        path='/check-in/reset-tournament/{event_uniq_id:str}/{tournament_id:int}',
        name='check-in-reset-tournament',
        guard=[PlayerTournamentActionGuard(AuthAction.CHECK_IN_PLAYERS)],
    )
    async def htmx_check_in_reset_tournament(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, tournament_id=tournament_id)
        tournament = web_context.get_admin_tournament()
        check_in = data.get('status') == 'present'
        tournament.check_in_all_players(check_in)
        message = _(
            'All the players of tournament [{tournament}] have been marked as "{status}".'
        ).format(
            tournament=tournament.name,
            status=_('Present') if check_in else _('Absent'),
        )
        return self.render_check_in_modal(web_context, message)

    @post(
        path='/check-in/tournament-toggle-open/{event_uniq_id:str}/{tournament_id:int}',
        name='check-in-tournament-toggle-open',
        guard=[PlayerTournamentActionGuard(AuthAction.CHECK_IN_PLAYERS)],
    )
    async def htmx_check_in_tournament_toggle_open(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, tournament_id=tournament_id)
        tournament = web_context.get_admin_tournament()
        check_in_open = web_context.form_data_to_bool(
            data, f'tournament_{tournament.id}_check_in_open'
        )
        if check_in_open != tournament.check_in_open:
            tournament.toggle_check_in_open()
        return HTMXTemplate(
            template_name='/common/empty.html',
            re_swap='none',
        )

    # -------------------------------------------------------------------------
    # Import
    # -------------------------------------------------------------------------

    @staticmethod
    def _build_list_tooltip(values: list[str]) -> str:
        message = ''
        for value in values:
            message += f'<div>{value}</div>'
        return message

    @staticmethod
    def _split_datasheet_columns_ids(
        columns: list[DatasheetColumn],
    ) -> tuple[list[str], list[str], list[str]]:
        required: list[str] = []
        optional: list[str] = []
        informative: list[str] = []
        for column in columns:
            if column.is_required:
                required.append(column.id)
            elif column.is_informative:
                informative.append(column.id)
            else:
                optional.append(column.id)
        return required, optional, informative

    @classmethod
    def _render_players_import_modal(
        cls,
        web_context: PlayerAdminWebContext,
        data: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
    ) -> HTMXTemplate:
        request = web_context.request
        event = web_context.get_admin_event()
        default_data = WebContext.values_dict_to_form_data(
            {
                'tournament_id': '',
                'file': '',
                'overwrite_players': False,
                'use_data_source': SessionPlayersImportUseDataSource(request).get(),
                'data_source': SessionPlayersActiveDataSource(request).get(),
            }
        )
        tournaments = web_context.player_addable_tournaments
        tournament_options = {'': '-'} | web_context.get_tournament_options(tournaments)
        data_sources = [
            source for source in DataSourceManager().objects() if source.is_available
        ]
        template_context = {
            'modal': 'players_import',
            'player_addable_tournaments': tournaments,
            'started_tournament_ids': [
                str(tournament.id) for tournament in tournaments if tournament.started
            ],
            'is_team_event': event.is_team_event,
            'tournament_options': tournament_options,
            'data_source_options': {
                data_source.id: data_source.name for data_source in data_sources
            },
            'data_sources': data_sources,
            'build_list_tooltip': cls._build_list_tooltip,
            'split_column_ids': cls._split_datasheet_columns_ids,
            'columns': PlayerDatasheetColumnHandler(event).columns,
            'data': default_data | (data or {}),
            'errors': errors or {},
        }
        return cls._admin_base_event_render(
            web_context.template_context | template_context
        )

    @get(
        path='/players-import-modal/{event_uniq_id:str}',
        name='players-import-modal',
    )
    async def players_import_modal(self, request: HTMXRequest) -> HTMXTemplate:
        web_context = PlayerAdminWebContext(request)
        return self._render_players_import_modal(web_context)

    @classmethod
    def _read_csv_file(cls, file_path: Path) -> dict[str, list[str]]:
        if file_path.suffix != '.csv':
            raise SharlyChessException(
                _('Unhandled file type [{suffix}] (expected: {expected}).').format(
                    suffix=file_path.suffix,
                    expected='.csv',
                )
            )
        content_by_column: dict[str, list[str]] = {}
        with open(file_path, 'rb') as raw_file:
            encoding = chardet.detect(raw_file.read())['encoding']
        with open(file_path, 'r', encoding=encoding) as csvfile:
            try:
                dialect = csv.Sniffer().sniff(''.join(islice(csvfile, 2)))
            except csv.Error:
                dialect = csv.excel

            csvfile.seek(0)
            reader = csv.DictReader(csvfile, dialect=dialect)
            if reader.fieldnames:
                content_by_column = {header: [] for header in reader.fieldnames}
                for row in reader:
                    if any(row[header] for header in reader.fieldnames):
                        for header in reader.fieldnames:
                            content_by_column[header].append(
                                (row[header] or '').strip()
                            )
        return content_by_column

    @classmethod
    async def _get_imported_stored_players(
        cls,
        web_context: PlayerAdminWebContext,
        used_columns: list[DatasheetColumn],
        content_by_column_id: dict[str, list[str]],
        overwrite_players: bool,
    ) -> tuple[dict[int, StoredPlayer], dict[int, dict[str, str]], set[int]]:
        for column in used_columns:
            column.update_from_used_columns(used_columns)
        event = web_context.get_admin_event()
        # A team event imports players at the event level (their team —
        # not a tournament — places them), so there may be no tournament.
        tournament = web_context.admin_tournament
        data_source = web_context.admin_data_source
        unique_values_by_column_id: dict[str, list[str]] = defaultdict(list)
        check_duplicate_players: list[Player] = []
        if tournament is not None:
            for tournament_player in event.tournament_players:
                same_tournament = tournament_player.tournament.id == tournament.id
                if same_tournament and overwrite_players:
                    # Deleted by the import before its own rows land.
                    continue
                if not same_tournament and event.allow_multi_tournament_players:
                    continue
                check_duplicate_players.append(tournament_player)
        elif not overwrite_players:
            # A team event imports at the event level, so a clash is with
            # the event's players. Not `event.tournament_players`: a team
            # places its players and need not belong to a tournament, so
            # that list misses everyone in an unassigned team.
            check_duplicate_players = list(event.players)
        name_keys: list[tuple] = [
            (player.last_name, player.first_name, player.date_of_birth)
            for player in check_duplicate_players
            if player.date_of_birth
        ]
        for column in used_columns:
            if column.is_informative or not column.is_unique:
                continue
            for player in check_duplicate_players:
                unique_values_by_column_id[column.id].append(
                    str(column.get_cell_content(player) or '')
                )

        stored_players_by_index: dict[int, StoredPlayer] = {}
        import_errors_by_index: dict[int, dict[str, str]] = defaultdict(dict)
        duplicated_indexes: set[int] = set()
        row_count = len(content_by_column_id[used_columns[0].id])
        for index in range(row_count):
            stored_player = StoredPlayer(
                id=None,
                federation=event.federation,
                check_in=(
                    tournament.default_player_check_in
                    if tournament is not None
                    else False
                ),
            )
            for column in used_columns:
                if column.is_informative:
                    continue
                value = content_by_column_id[column.id][index]
                try:
                    column.augment_stored_player_with_tournament(
                        tournament, stored_player, value
                    )
                    if (
                        column.is_unique
                        and value
                        and value in unique_values_by_column_id[column.id]
                    ):
                        duplicated_indexes.add(index)
                        message = (
                            _(
                                'A player with {column}=[{value}] already '
                                'exists in tournament [{tournament}].'
                            )
                            if event.allow_multi_tournament_players
                            else _(
                                'A player with {column}=[{value}] already exists in the event.'
                            )
                        )
                        raise SharlyChessException(
                            message.format(
                                column=column.id,
                                value=value,
                                tournament=tournament.name
                                if tournament
                                else event.name,
                            )
                        )
                except SharlyChessException as error:
                    import_errors_by_index[index][column.id] = str(error)
            name_key = (
                stored_player.last_name,
                stored_player.first_name or '',
                stored_player.date_of_birth,
            )
            if stored_player.date_of_birth:
                if name_key in name_keys:
                    duplicated_indexes.add(index)
                    message = (
                        _(
                            'Player [{player}] already exists in tournament [{tournament}].'
                        )
                        if event.allow_multi_tournament_players
                        else _('Player [{player}] already exists in the event.')
                    )
                    import_errors_by_index[index]['last_name'] = message.format(
                        player=' '.join(
                            [
                                stored_player.last_name,
                                stored_player.first_name or '',
                                format_date(stored_player.date_of_birth),
                            ]
                        ),
                        tournament=tournament.name if tournament else event.name,
                    )
            if index in import_errors_by_index:
                continue
            stored_players_by_index[index] = stored_player
            if stored_player.date_of_birth:
                name_keys.append(name_key)
            for column in used_columns:
                if column.is_unique:
                    unique_values_by_column_id[column.id].append(
                        content_by_column_id[column.id][index]
                    )

        if data_source:
            stored_players_by_index = {}
            in_rating_period = FideDatabase().covers_rating_period(
                cls._k_factor_reference_date(web_context)
            )
            identifier_column = data_source.import_identifier_column
            column_content = content_by_column_id[identifier_column.id]
            identifiers = [
                identifier
                for index, identifier in enumerate(column_content)
                if index not in import_errors_by_index
            ]
            stored_players_by_identifier = (
                await data_source.get_stored_players_by_import_identifier(identifiers)
            )
            for index in range(row_count):
                if index in import_errors_by_index:
                    continue
                identifier = content_by_column_id[identifier_column.id][index]
                if identifier not in stored_players_by_identifier:
                    import_errors_by_index[index][identifier_column.id] = _(
                        'Value not found in the data source.'
                    )
                    continue
                stored_player = stored_players_by_identifier[identifier]
                for column in used_columns:
                    if column.is_informative:
                        continue
                    value = content_by_column_id[column.id][index]
                    column.augment_stored_player_with_tournament(
                        tournament, stored_player, value
                    )
                if not in_rating_period:
                    keep_reliable_k_factors(stored_player)
                stored_players_by_index[index] = stored_player

        for index, stored_player in stored_players_by_index.items():
            for tr in TournamentRating:
                for prt in PlayerRatingType:
                    ratings = stored_player.ratings.get(tr.value, {})
                    if prt.form_key in ratings:
                        rating = ratings[prt.form_key]
                        if rating and not (prt.min_value <= rating <= prt.max_value):
                            import_errors_by_index[index][
                                f'{tr.form_key}_{prt.key}'
                            ] = _(
                                'Invalid {rating_type} rating [{rating}] (expected in range [{min}-{max}]).'
                            ).format(
                                rating_type=prt.name,
                                rating=rating,
                                min=prt.min_value,
                                max=prt.max_value,
                            )

        return stored_players_by_index, import_errors_by_index, duplicated_indexes

    @classmethod
    async def _render_players_import_diff_modal(
        cls,
        web_context: PlayerAdminWebContext,
        columns: list[DatasheetColumn],
        content_by_column_id: dict[str, list[str]],
        file_path: Path,
        overwrite_players: bool,
    ) -> HTMXTemplate:
        event = web_context.get_admin_event()
        used_columns = [
            column for column in columns if column.id in content_by_column_id
        ]
        used_column_ids = [column.id for column in used_columns]
        (
            stored_players_by_index,
            import_errors_by_index,
            duplicated_indexes,
        ) = await cls._get_imported_stored_players(
            web_context, used_columns, content_by_column_id, overwrite_players
        )
        identifier_column: DatasheetColumn | None = None
        data_source_players_by_index: dict[int, Player] = {}
        if web_context.admin_data_source:
            identifier_column = used_columns.pop(0)
            data_source_players_by_index = {
                index: Player(event, stored_player)
                for index, stored_player in stored_players_by_index.items()
            }
        template_context: dict[str, Any] = {
            'modal': 'players_import_diff',
            'identifier_column': identifier_column,
            'used_columns': used_columns,
            'unknown_column_ids': [
                column_id
                for column_id in content_by_column_id
                if column_id not in used_column_ids
            ],
            'build_list_tooltip': cls._build_list_tooltip,
            'import_errors_by_index': import_errors_by_index,
            'data_source_players_by_index': data_source_players_by_index,
            'duplicated_indexes': duplicated_indexes,
            'row_count': len(content_by_column_id[used_column_ids[0]]),
            'content_by_column_id': content_by_column_id,
            'file_path': WebContext.value_to_form_data(file_path),
            'overwrite_players': overwrite_players,
        }
        return cls._admin_base_event_render(
            web_context.template_context | template_context
        )

    @post(
        path='/players-import-diff-modal/{event_uniq_id:str}',
        name='players-import-diff-modal',
    )
    async def players_import_diff_modal(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, Any], Body(media_type=RequestEncodingType.MULTI_PART)
        ],
    ) -> HTMXTemplate:
        web_context = PlayerAdminWebContext(request)
        event = web_context.get_admin_event()
        normalized_data = await WebContext.normalize_multipart_data(data)
        errors: dict[str, str] = {}
        tournament_id = web_context.form_data_to_int(
            normalized_data, field := 'tournament_id'
        )
        # Team events import at the event level — a team (not a
        # tournament) places each player — so no tournament is required.
        if not tournament_id and not event.is_team_event:
            errors[field] = _('This field is required.')
        file_path = WebContext.form_data_to_path(normalized_data, field := 'file')
        content_by_column_id: dict[str, list[str]] = {}
        if not file_path:
            errors[field] = _('This field is required.')
        else:
            try:
                content_by_column_id = self._read_csv_file(file_path)
            except SharlyChessException as error:
                if isinstance(error, SharlyChessException):
                    message = str(error)
                else:
                    message = _(
                        'An unexpected error occurred while reading '
                        'the CSV file. Consult the logs for more details.'
                    )
                    logger.exception(error)
                errors['alert'] = message
        use_data_source = WebContext.form_data_to_bool(
            normalized_data, 'use_data_source'
        )
        SessionPlayersImportUseDataSource(request).set(use_data_source)
        data_source: DataSource | None = None
        if use_data_source:
            data_source = DataSourceManager().get_object(
                WebContext.form_data_to_str(data, 'data_source') or ''
            )
            SessionPlayersActiveDataSource(request).set(data_source.id)
        columns = PlayerDatasheetColumnHandler(event, data_source).columns
        if not errors:
            for column in columns:
                if column.is_required and column.id not in content_by_column_id:
                    errors['alert'] = _('Missing required column [{column}].').format(
                        column=column.id
                    )
                    break
        overwrite_players = WebContext.form_data_to_bool(data, 'overwrite_players')
        if errors:
            return self._render_players_import_modal(
                web_context, normalized_data, errors
            )
        assert file_path is not None
        web_context = PlayerAdminWebContext(
            request,
            tournament_id=tournament_id,
            data_source_id=data_source.id if data_source else None,
        )
        return await self._render_players_import_diff_modal(
            web_context,
            list(columns),
            content_by_column_id,
            file_path,
            overwrite_players,
        )

    @classmethod
    def _create_imported_stored_players(
        cls,
        web_context: PlayerAdminWebContext,
        stored_players: list[StoredPlayer],
        used_columns: list[DatasheetColumn],
        overwrite_players: bool,
    ):
        request = web_context.request
        event = web_context.get_admin_event()
        tournament = web_context.admin_tournament
        team_mode = event.is_team_event
        if stored_players:
            # Team events import players at the event level: no
            # ``tournament_player`` row (the synthetic loader derives one
            # from team membership). A team name on the row matches an
            # existing team by name event-wide (created on first sight,
            # attached to the team tournament when there is one).
            team_id_by_name: dict[str, int] = {}
            next_team_index: dict[int, int] = {}
            if team_mode:
                for team in event.teams:
                    team_id_by_name.setdefault(team.name, team.id)
                    next_team_index[team.id] = len(team.players)
                if overwrite_players:
                    # The import is about to empty those teams, so their
                    # board order restarts from the top.
                    emptied = (
                        tournament.teams if tournament is not None else event.teams
                    )
                    for team in emptied:
                        next_team_index[team.id] = 0
            with EventDatabase(event.uniq_id, True) as database:
                if overwrite_players:
                    if tournament is not None:
                        database.delete_players_in_tournament(tournament.id)
                    else:
                        # A team event imports at the event level — its
                        # players are placed by team, not by tournament —
                        # so there is no tournament to clear and "delete
                        # the existing players" means the event's.
                        database.delete_all_stored_players()
                for stored_player in stored_players:
                    player_id = database.add_stored_player(stored_player)
                    if not team_mode:
                        assert tournament is not None
                        database.add_stored_tournament_player(
                            StoredTournamentPlayer(
                                player_id=player_id,
                                tournament_id=tournament.id,
                            )
                        )
                        continue
                    team_name = stored_player.transient_team_name
                    if team_name:
                        team_id = team_id_by_name.get(team_name)
                        if team_id is None:
                            team_id = database.add_stored_team(
                                StoredTeam(
                                    id=None,
                                    name=team_name,
                                    tournament_id=(
                                        tournament.id
                                        if tournament is not None
                                        else None
                                    ),
                                )
                            )
                            team_id_by_name[team_name] = team_id
                            next_team_index[team_id] = 0
                        database.set_player_team(
                            player_id, team_id, next_team_index[team_id]
                        )
                        next_team_index[team_id] += 1
                if any(column.save_stored_event for column in used_columns):
                    database.update_stored_event(event.stored_event)
            Message.success(
                request,
                ngettext(
                    '{count} player successfully imported.',
                    '{count} players successfully imported.',
                    len(stored_players),
                ).format(count=len(stored_players)),
            )
        else:
            Message.warning(request, _('No players imported.'))
        return cls._render_players_tab(
            PlayerAdminWebContext(request, reload_event=True)
        )

    @post(
        path=[
            # Team events import at the event level, with no tournament.
            '/import-players/{event_uniq_id:str}',
            '/import-players/{event_uniq_id:str}/{tournament_id:int}',
        ],
        name='import-players',
    )
    async def import_players(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
        tournament_id: FromPath[int | None] = None,
    ) -> HTMXTemplate:
        flat_data = WebContext.flatten_list_data(data)
        web_context = PlayerAdminWebContext(
            request,
            tournament_id=tournament_id,
            data_source_id=WebContext.form_data_to_str(flat_data, 'data_source'),
        )
        event = web_context.get_admin_event()
        tournament = web_context.admin_tournament
        data_source = web_context.admin_data_source
        file_path = WebContext.form_data_to_path(flat_data, 'file_path')
        assert file_path is not None
        row_indexes = WebContext.form_data_to_list_int(flat_data, 'row_indexes')
        overwrite_players = WebContext.form_data_to_bool(flat_data, 'overwrite_players')
        if overwrite_players:
            started = (
                [tournament]
                if tournament is not None
                else list(event.tournaments_by_id.values())
            )
            if any(candidate.started for candidate in started):
                raise ClientException('Overwrite is forbidden on started tournaments.')
        columns = PlayerDatasheetColumnHandler(event, data_source).columns
        content_by_column_id = self._read_csv_file(file_path)
        used_columns = [
            column for column in columns if column.id in content_by_column_id
        ]
        stored_players_by_index = (
            await self._get_imported_stored_players(
                web_context, used_columns, content_by_column_id, overwrite_players
            )
        )[0]
        stored_players = [
            stored_player
            for index, stored_player in stored_players_by_index.items()
            if index in row_indexes
        ]
        return self._create_imported_stored_players(
            web_context, stored_players, used_columns, overwrite_players
        )

    # -------------------------------------------------------------------------
    # Misc
    # -------------------------------------------------------------------------

    @patch(
        path='/player-move/{event_uniq_id:str}/{player_id:int}/{tournament_id:int}',
        name='admin-player-move',
        guard=[
            TournamentActionGuard(AuthAction.UPDATE_PLAYERS),
            PlayerTournamentActionGuard(AuthAction.UPDATE_PLAYERS),
        ],
    )
    async def htmx_admin_player_move(
        self,
        request: HTMXRequest,
        player_id: FromPath[int],
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = PlayerAdminWebContext(request, player_id, tournament_id)
        admin_player = web_context.get_admin_player()
        dst_tournament = web_context.get_admin_tournament()
        src_tournament = admin_player.single_tournament
        event = web_context.get_admin_event()
        try:
            self._validate_player_tournament_move(
                event, admin_player, src_tournament, dst_tournament
            )
            event.move_player_to_tournament(admin_player, dst_tournament)
            Message.success(
                request,
                _(
                    'Player [{player}] has been moved '
                    'from tournament [{src_tournament}] '
                    'to tournament [{dst_tournament}].'
                ).format(
                    player=admin_player.full_name,
                    src_tournament=src_tournament.name,
                    dst_tournament=dst_tournament.name,
                ),
            )
        except ValueError as e:
            Message.error(request, str(e))
        web_context = PlayerAdminWebContext(request, player_id, reload_event=True)
        return self._render_player_table_row(web_context)

    @staticmethod
    def _validate_player_tournament_move(
        event: Event,
        player: Player,
        src_tournament: Tournament,
        dst_tournament: Tournament,
    ):
        """Validate that a player can be moved from its current tournament to *dst_tournament*.
        Raises a ValueError if it is not possible."""

        if player.single_tournament_player.has_real_pairings:
            raise ValueError(
                _(
                    'Player [{player}] has pairings in tournament [{tournament}].'
                ).format(
                    player=player.full_name,
                    tournament=src_tournament.name,
                ),
            )
        if not dst_tournament.can_add_players:
            raise ValueError(
                _('Impossible to add players to tournament [{tournament}].').format(
                    tournament=src_tournament.name
                )
            )
        if player.fide_id in dst_tournament.tournament_players_by_fide_id:
            raise ValueError(
                _(
                    'Fide ID [{fide_id}] already present in tournament [{tournament}].'
                ).format(
                    fide_id=player.fide_id,
                    tournament=dst_tournament.name,
                ),
            )
        plugin_manager.hook_for_event(event, 'validate_player_tournament_move')(
            tournament=dst_tournament,
            player=player.single_tournament_player,
        )

    @get(
        path='/history-popover/{event_uniq_id:str}/{tournament_id:int}/{player_id:int}',
        name='admin-player-history-popover',
    )
    async def htmx_admin_history_popover(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        player_id: FromPath[int],
    ) -> Template:
        web_context: PlayerAdminWebContext = PlayerAdminWebContext(
            request, player_id, tournament_id
        )

        tournament = web_context.get_admin_tournament()
        tournament.compute_tournament_player_ranks()
        return HTMXTemplate(
            template_name='/admin/players/history_popover.html',
            context=web_context.template_context
            | {
                'player': web_context.get_admin_player(),
                'max_round': tournament.rounds,
            },
        )

    @patch(
        path='/players-update/{event_uniq_id:str}/{data_source_id:str}/{tab:str}',
        name='admin-event-players-update',
        guards=[ActionGuard(AuthAction.UPDATE_PLAYERS)],
    )
    async def htmx_admin_update_event_players(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        data_source_id: FromPath[str],
        tab: FromPath[str],
    ) -> Template | Redirect:
        web_context = PlayerAdminWebContext(request, data_source_id=data_source_id)
        event = web_context.get_admin_event()
        data_source = web_context.get_admin_data_source()
        flat_data = WebContext.flatten_list_data(data)
        player_ids = WebContext.form_data_to_list_int(flat_data, 'player_ids')
        field_ids = WebContext.form_data_to_list_str(flat_data, 'field_ids')
        fields = [
            field
            for field in data_source.player_updater_fields
            if field.id in field_ids
        ]
        allowed_players_by_id = web_context.client.allowed_players_by_id
        players: list[Player] = []
        for player_id in player_ids:
            if player := allowed_players_by_id.get(player_id, None):
                players.append(player)
        player_comparators = await data_source.get_player_comparators(
            players, fields, diff_only=True
        )
        if player_comparators is None:
            Message.error(
                request,
                _(
                    'Connection to the data source [{data_source}] failed. '
                    'Consult the logs for more details.'
                ).format(data_source=data_source.name),
            )
        else:
            event.update_players(
                [
                    comparator.updated_player_from_match(fields)
                    for comparator in player_comparators
                ]
            )
            count: int = len(player_comparators)
            Message.success(
                request,
                ngettext(
                    '{count} player updated.', '{count} players updated.', count
                ).format(count=count)
                if count
                else _('No players updated.'),
            )
        redirect_url = request.app.route_reverse(
            f'admin-event-{tab}-tab', event_uniq_id=event.uniq_id
        )
        if tab == 'pairings':
            redirect_url += '?skip_ratings_warning=1'
        return Redirect(redirect_url, status_code=303)

    @get(
        path='/event-players-diff-modal/{event_uniq_id:str}/{data_source_id:str}/{tab:str}',
        name='admin-event-players-diff-modal',
        guards=[TournamentActionGuard(AuthAction.UPDATE_PLAYERS)],
    )
    async def htmx_admin_event_players_diff_modal(
        self,
        request: HTMXRequest,
        data_source_id: FromPath[str],
        tab: FromPath[str],
        tournament_id: FromQuery[int | None] = None,
    ) -> Template:
        web_context = PlayerAdminWebContext(
            request,
            tournament_id=tournament_id,
            data_source_id=data_source_id,
        )
        data_source = web_context.get_admin_data_source()
        players: list[Player] = []
        if tournament := web_context.admin_tournament:
            for tournament_player in tournament.sorted_tournament_players:
                players.append(tournament_player)
        else:
            players = web_context.client.sorted_allowed_players
        fields = data_source.player_updater_fields
        player_comparators = await data_source.get_player_comparators(players, fields)
        if player_comparators is None:
            Message.error(
                request,
                _('Could not connect to data source [{data_source}].').format(
                    data_source=data_source.name
                ),
            )
            return self._render_players_tab(web_context)
        updated_field_ids = {
            field_id
            for comparator in player_comparators
            for field_id in comparator.diff_field_ids
        }
        template_context = web_context.template_context | {
            'modal': 'players_diff',
            'data_source': data_source,
            'fields': fields,
            'updated_field_ids': updated_field_ids,
            'player_comparators': player_comparators,
            'update_enabled': bool(updated_field_ids),
            'tab': tab,
        }
        return self._admin_base_event_render(template_context)

    @get(
        path='/players/needs-refresh-message/{event_uniq_id:str}/{reason:str}',
        name='players-needs-refresh-message',
    )
    async def htmx_admin_players_refresh_message(
        self,
        request: HTMXRequest,
        event_uniq_id: FromPath[str],
        reason: FromPath[str],
        ignore: FromQuery[bool] = False,
    ) -> Template:
        if ignore:
            return HTMXTemplate(template_name='/common/empty.html')
        return HTMXTemplate(
            template_name='/admin/common/needs_refresh.html',
            context={
                'url': request.app.route_reverse(
                    'admin-event-players-tab', event_uniq_id=event_uniq_id
                ),
                'event_uniq_id': event_uniq_id,
                'reason': reason,
            },
        )

    @get(
        path=[
            '/search-player/{event_uniq_id:str}',
            '/search-player/{event_uniq_id:str}/{page:int}',
        ],
        name='admin-search-player',
    )
    async def htmx_admin_search_player(
        self,
        request: HTMXRequest,
        data_source_id: FromQuery[str],
        player_id: FromQuery[int | None],
        search: FromQuery[str],
        page: FromPath[int] = 0,
        usage: FromQuery[str] = 'player',
    ) -> Template:
        web_context = PlayerAdminWebContext(
            request, player_id, data_source_id=data_source_id
        )
        data_source = web_context.get_admin_data_source()
        players: list[Player] = []
        connection_error: str | None = None
        search = search.strip()
        if search:
            try:
                stored_players = await data_source.search_player(
                    search,
                    web_context.get_admin_event().federation,
                    page,
                    DataSource.SEARCH_LIMIT,
                )
                for stored_player in stored_players:
                    stored_player.id = 0
                    players.append(Player(web_context.get_admin_event(), stored_player))
            except SharlyChessException as e:
                connection_error = str(e)
            SessionPlayersActiveDataSource(request).set(data_source.id)
        return HTMXTemplate(
            template_name='admin/common/search_results.html',
            context=web_context.template_context
            | {
                'usage': usage,
                'search': search,
                'search_results': players,
                'has_more_results': len(players) == DataSource.SEARCH_LIMIT,
                'page': page,
                'data_source': data_source,
                'connection_error': connection_error,
            },
        )

    @staticmethod
    def _players_export_sort_key(player: Player) -> Any:
        if player.event.is_team_event:
            return (
                player.event.teams_by_id[player.team_id].name
                if player.team_id
                else '|',  # players with no team at the end
                player.team_index,
            )
        else:
            return player.last_name, player.first_name

    @get(
        path=[
            '/event-export-players/{event_uniq_id:str}/{exporter_id:str}',
            '/event-export-players/{event_uniq_id:str}/{tournament_id:int}/{exporter_id:str}',
        ],
        name='event-export-players',
    )
    async def htmx_event_export_players(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int | None],
        exporter_id: FromPath[str],
    ) -> Response[str] | File:
        web_context = PlayerAdminWebContext(request, tournament_id=tournament_id)
        event = web_context.get_admin_event()
        tournament = web_context.admin_tournament
        if tournament:
            players: list[Player] = list(tournament.tournament_players)
        else:
            search_results = self.get_search_results(web_context)
            players: list[Player] = [
                event.players_by_id[player_id]
                for player_id in search_results
                if player_id in event.players_by_id
            ]
        players = sorted(players, key=self._players_export_sort_key)
        try:
            exporter = PlayerExporterManager().get_object(exporter_id)
        except KeyError:
            raise NotFoundException(f'Unknown exporter [{exporter_id}].')
        return exporter.download_players_file(players, event)

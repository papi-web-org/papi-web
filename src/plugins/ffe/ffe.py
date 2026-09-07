import copy
import re
from collections import Counter, defaultdict
from types import ModuleType
from typing import Any, TYPE_CHECKING, Iterable, Optional

from packaging.version import Version

from common import TEST_ENV, DEVEL_ENV
from common.exception import SharlyChessException
from common.i18n import _, ngettext
from data.account import Account
from data.columns import player_table, player_datasheet
from data.columns.player_datasheet import DatasheetColumn
from data.columns.player_table import TournamentPlayerTableColumn, ColumnUsage
from data.columns.players_tab import (
    PlayersTabColumn,
    ClubPlayersTabColumn,
    FideIdPlayersTabColumn,
)
from data.criteria.player_filter_options import PlayerFilterOption, ClubsFilterOption
from data.criteria.player_filters import PlayerFilter, ClubPlayerFilter
from data.criteria.tournament_criteria import (
    TournamentCriterion,
    GenderTournamentCriterion,
)
from data.input_output import DataSource, TournamentExporter, TournamentImporter
from data.input_output.data_source import FideDataSource
from data.input_output.trf.trf_data import TrfNationalPlayer
from data.pairings.managers import PairingVariationManager
from data.pairings.variations import SwissVariation
from data.player import (
    Player,
    PlayerProfileLink,
    PlayerRating,
    PlayerRatingAndType,
    TournamentPlayer,
)
from data.player_categories import PlayerCategory, JuniorCategory
from data.print_documents import (
    PlayerSplitter,
    PrintDocument,
    PrintOption,
    IndividualTeamType,
)
from data.print_documents.documents import StatisticsPrintDocument
from data.print_documents.place_cards.data import PlaceCardPlayer
from data.print_documents.player_splitters import ClubPlayerSplitter
from data.print_documents.qrcode_types import QRCodeType
from data.print_documents.individual_teams import ClubIndividualTeamType
from data.tie_breaks import TieBreak, TieBreakOption
from data.tie_breaks.system_sets import SystemTieBreakSet
from data.tie_breaks.tie_breaks import ProgressiveScoresTieBreak
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import StoredPlayer
from database.sqlite.fide.fide_database import FideDatabase
from database.sqlite.local_source_database import LocalSourceDatabase
from plugins.ffe import migrations, PLUGIN_NAME, ffe_tie_breaks
from plugins.ffe.ffe_background_uploader import (
    EventLoader,
    FfeBackgroundUploader,
)
from plugins.ffe.ffe_data_sources import FfeLocalDataSource, FfeOnlineDataSource
from plugins.ffe.ffe_database import FfeDatabase
from plugins.ffe.ffe_entity import (
    FFESiteQRCodeType,
    LeaguePlayerSplitter,
    NicoisSwissVariation,
    FfeLeaguePlayerFilter,
    FfeLeaguesFilterOption,
    FfeLeagueTableColumn,
    FfeIdDatasheetColumn,
    FfeLicenceNumberDatasheetColumn,
    FfeLicenceDatasheetColumn,
    FfeLeagueDatasheetColumn,
    FfeLicenceTypeTableColumn,
    FfeLeaguePlayersTabColumn,
    FfeLicencePlayersTabColumn,
    FfeLicenceTournamentCriterion,
    FfeLeagueTournamentCriterion,
    FfeLeagueIndividualTeamType,
)
from plugins.ffe.ffe_rule_sets import (
    ChampionnatFemininN1N2RuleSet,
    CoupeDeLaPariteRuleSet,
    CoupeJeanClaudeLoubatiereRuleSet,
)
from plugins.ffe.ffe_sql_server import FFESqlServer
from plugins.ffe.ffe_tie_breaks import (
    BasePapiTieBreak,
    PapiBuchholzTypeOption,
    PapiBuchholzTypeManager,
    PapiBuchholzTieBreak,
)
from plugins.ffe.ffe_tournament_controller import FfeTournamentController
from plugins.ffe.ffe_tournament_exporters import PapiTournamentExporter
from plugins.ffe.ffe_tournament_importers import (
    PapiJsonTournamentImporter,
    PapiTournamentImporter,
    OnlineTournamentImporter,
)
from plugins.ffe.ffe_upload_controller import (
    FfeUploadController,
)
from plugins.ffe.papi_converter import PapiConverter, PapiPlayer
from plugins.ffe.print_documents.ffe_documents import FFEPrintDocument
from plugins.ffe.print_documents.ffe_pairing_sheet_document import (
    FfePairingSheetDocument,
)
from plugins.ffe.print_documents.ffe_options import (
    FFEDocumentTypePrintOption,
    FFET3NoLicencePlayersPrintOption,
    FFET4NoLicencePlayersPrintOption,
    FFEWriterPrintOption,
    FFETraineePrintOption,
    FFEChiefArbiterPrintOption,
    FFEArbiterPrintOption,
)
from plugins.ffe.utils import (
    FFEUtils,
    PlayerFFELicence,
    FfeAccountPluginData,
    FFEArbiterTitle,
    FFE_LEAGUES,
)
from plugins.ffe.utils import (
    FfeEventPluginData,
    FfePlayerPluginData,
    FfeTournamentPluginData,
)
from data.tie_breaks import tie_breaks as tie_breaks_module
from plugins.hookspec import hookimpl, hookspec
from plugins.migration import PluginMigrationManager
from plugins.sce.sce_data import SCEPlayerSyncData
from plugins.sce.sce_tournament_results_builder import SCEUploadColumn
from plugins.utils import (
    ExtraStatisticsSection,
    NavDataTransferItem,
    Plugin,
    PluginUtils,
    PluginData,
    AccountPluginData,
    TournamentConnectionField,
)
from utils.enum import (
    EventType,
    PlayerRatingType,
    Result,
    TournamentRating,
)
from web.admin.collection import ListColumn
from web.controllers.admin.player_admin_controller import PlayerAdminWebContext
from web.controllers.base_controller import BaseController, WebContext

if TYPE_CHECKING:
    from data.event import Event
    from database.sqlite.event.event_store import StoredEvent
    from data.prohibited_pairings import RoundProhibitedPairingGroup
    from data.rule_sets import RuleSet
    from data.tournament import Tournament
    from database.sqlite.event.event_store import StoredTournament
    from web.admin.collection import AdminCollectionSpec


class FfePluginHooks:
    @hookspec
    def update_papi_player(
        self,
        papi_player: PapiPlayer,
        tournament_player: TournamentPlayer,
        is_ffe_upload: bool,
    ):
        """Called when a player is converted to Papi format"""

    @hookspec
    def augment_stored_player_on_papi_import(
        self,
        event: 'Event',
        importer: TournamentImporter,
        stored_player: StoredPlayer,
    ):
        """Augment player data when fetched from Papi."""


class FfePlugin(Plugin):
    @staticmethod
    def static_id() -> str:
        return PLUGIN_NAME

    @staticmethod
    def static_name() -> str:
        return _('Fédération Française des Échecs')

    @property
    def dependencies(self) -> list[type[Plugin]]:
        return []

    @property
    def description(self) -> str:
        return _(
            'French Federation specific features (player search, results uploading, leagues, Papi import/export...)'
        )

    @property
    def version(self) -> Version:
        return Version('0.1.1')

    @property
    def hookspecs(self) -> type | None:
        return FfePluginHooks

    @property
    def default_is_enabled(self) -> bool:
        return True

    @property
    def default_event_is_enabled(self) -> bool:
        return True

    @property
    def federation(self) -> str | None:
        return 'FRA'

    @property
    def base_migration_module(self) -> ModuleType:
        return migrations

    @property
    def event_form_script_template(self) -> str:
        return '/ffe_event_form_script.js'

    @property
    def event_form_fields_template(self) -> str:
        return '/ffe_event_form_fields.html'

    def used_by_stored_tournament(
        self, stored_event: 'StoredEvent', stored_tournament: 'StoredTournament'
    ) -> bool:
        ffe_data = stored_tournament.plugin_data.get(PLUGIN_NAME, {})
        if ffe_data.get('ffe_id', None):
            return True
        for stored_tie_break in stored_tournament.stored_tie_breaks:
            if any(
                stored_tie_break.type == tie_break_type.static_id()
                for tie_break_type in self._tie_break_types
            ):
                return True
        if stored_tournament.pairing == NicoisSwissVariation.static_id():
            return True
        return False

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
        return [
            FfeUploadController,
            FfeTournamentController,
        ]

    @hookimpl
    def get_base_admin_template_context(self) -> dict[str, Any]:
        return {
            'ffe_auth_valid': '',
            'ffe_utils': FFEUtils,
        }

    # ---------------------------------------------------------------------------------
    # Input-Output
    # ---------------------------------------------------------------------------------

    @hookimpl
    def insert_data_sources(self, data_sources: list[type[DataSource]]):
        local: type[DataSource] = FfeLocalDataSource
        online: type[DataSource] = FfeOnlineDataSource
        fide: type[DataSource] = FideDataSource
        PluginUtils.insert_on_equals(data_sources, online, fide, False)
        PluginUtils.insert_on_equals(data_sources, local, fide, False)

    @hookimpl
    def insert_local_source_databases(self, databases: list[type[LocalSourceDatabase]]):
        ffe: type[LocalSourceDatabase] = FfeDatabase
        fide: type[LocalSourceDatabase] = FideDatabase
        PluginUtils.insert_on_equals(databases, ffe, fide, False)

    @hookimpl
    def insert_tournament_exporters(self, exporters: list[type[TournamentExporter]]):
        exporters.append(PapiTournamentExporter)

    @hookimpl
    def insert_tournament_importers(self, importers: list[type[TournamentImporter]]):
        importers.append(PapiTournamentImporter)
        if TEST_ENV or DEVEL_ENV:
            importers.append(PapiJsonTournamentImporter)
            importers.append(OnlineTournamentImporter)

    # ---------------------------------------------------------------------------------
    # Players
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_player_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, FfePlayerPluginData

    @hookimpl
    def get_prohibited_pairing_dimensions(self):
        from data.prohibited_pairings import ProhibitedPairingDimension

        return [
            ProhibitedPairingDimension(
                id='ffe-league',
                label=_('League'),
                is_team=False,
                group_key=lambda player: (
                    FFEUtils.get_player_plugin_data(player).league or None
                ),
            )
        ]

    @hookimpl
    def get_team_affiliation_sources(self):
        from data.teams.team_affiliation import (
            TeamAffiliationSource,
            team_shared_player_value,
        )

        return [
            TeamAffiliationSource(
                id='ffe-league',
                label=_('League'),
                resolve=lambda team: team_shared_player_value(
                    team,
                    lambda player: (
                        FFEUtils.get_player_plugin_data(player).league or None
                    ),
                ),
            )
        ]

    @hookimpl
    def get_round_prohibited_pairing_groups(
        self, tournament: 'Tournament', round_: int
    ) -> 'list[RoundProhibitedPairingGroup]':
        # FFE cups: two teams that have won both of their first two matches
        # are not paired together in round 3 (hard). The no-protection cup
        # variants opt out. The exception (a single qualifying place for the
        # N1F) is handled by picking the no-protection variant, not here.
        from data.prohibited_pairings import RoundProhibitedPairingGroup

        if round_ != 3:
            return []
        rule_set = tournament.rule_set
        if rule_set is None or not getattr(rule_set, 'round3_winner_protection', False):
            return []
        winners = [
            row['team'].id
            for row in tournament.team_standings(after_round=2)
            if row['played'] == 2 and row['wins'] == 2
        ]
        if len(winners) < 2:
            return []
        return [
            RoundProhibitedPairingGroup(
                name=_('Won both of the first two matches'),
                is_hard=True,
                member_ids=winners,
            )
        ]

    @hookimpl
    def get_player_form_template_context(
        self, web_context: 'PlayerAdminWebContext'
    ) -> dict[str, Any]:
        return {
            'licence_options': {
                str(licence.value): licence.compact_name for licence in PlayerFFELicence
            },
            'ffe_league_options': {'': '-'}
            | {code: f'{code} - {name}' for code, name in FFE_LEAGUES.items()},
        }

    @hookimpl
    def insert_player_form_fields_template(
        self, templates_by_section: defaultdict[str, list[str]]
    ):
        templates_by_section['identity'].insert(
            0, '/ffe_player_form_identity_fields.html'
        )
        templates_by_section['fide'].append('/ffe_player_form_fields.html')

    @hookimpl
    def validate_player_form_fields(
        self,
        data: dict[str, str],
        errors: dict[str, str],
    ):
        league: str | None = WebContext.form_data_to_str(data, field := 'ffe_league')
        if league and league not in FFE_LEAGUES:
            # should never happen, not translated.
            errors[field] = f'Invalid league value [{data[field]}].'
            data[field] = ''
        try:
            if value := WebContext.form_data_to_str(data, field := 'ffe_licence'):
                PlayerFFELicence(value)
        except ValueError:
            errors[field] = f'Invalid FFE licence [{data[field]}].'

        ffe_licence_number = WebContext.form_data_to_str(
            data, field := 'ffe_licence_number'
        )
        if ffe_licence_number and not PlayerFFELicence.validate(ffe_licence_number):
            errors[field] = _(
                'Invalid FFE licence number [{ffe_licence_number}].'
            ).format(ffe_licence_number=ffe_licence_number)

    @hookimpl
    def get_player_duplicate_key(
        self, stored_player: StoredPlayer
    ) -> tuple[str, str] | None:
        if licence_number := self.get_data(
            stored_player.plugin_data, 'ffe_licence_number'
        ):
            return self.id, licence_number
        return None

    @hookimpl
    async def augment_player_after_search(
        self,
        stored_player: StoredPlayer,
        data_source: DataSource,
        with_arbiter_title: bool,
    ):
        fide_id = stored_player.fide_id
        if not fide_id:
            return
        if data_source.id == FfeLocalDataSource.static_id():
            # nothing more to get from the online database for local searches
            return
        ffe_stored_player: StoredPlayer | None = None
        if data_source.id != FfeOnlineDataSource.static_id():
            # Try to get more information by requesting the FFE SQL server
            ffe_stored_player: StoredPlayer | None = None
            try:
                # Try to get more information by requesting the FFE database
                async with FFESqlServer() as ffe_sql_server:
                    ffe_stored_player = (
                        await ffe_sql_server.get_stored_player_by_fide_id(
                            player_fide_id=fide_id,
                        )
                    )
            except SharlyChessException:
                pass
        if not ffe_stored_player or with_arbiter_title:
            if (ffe_database := FfeDatabase()).exists():
                # Try to get more information by requesting the FFE database
                with ffe_database:
                    ffe_stored_player = ffe_database.get_stored_player_by_fide_id(
                        player_fide_id=fide_id,
                    )
        if ffe_stored_player:
            for rating_type in TournamentRating:
                stored_rating = stored_player.ratings.get(rating_type.value, None)
                rating = (
                    PlayerRating.from_stored_value(stored_rating)
                    if stored_rating
                    else None
                )
                ffe_stored_rating = ffe_stored_player.ratings.get(
                    rating_type.value, None
                )
                if ffe_stored_rating:
                    ffe_rating = PlayerRating.from_stored_value(ffe_stored_rating)
                    augmented_rating = PlayerRating(
                        fide=rating.fide
                        if rating and rating.fide is not None
                        else ffe_rating.fide,
                        national=rating.national
                        if rating and rating.national is not None
                        else ffe_rating.national,
                        estimated=rating.estimated
                        if rating and rating.estimated is not None
                        else ffe_rating.estimated,
                    )
                    stored_player.ratings[rating_type.value] = (
                        augmented_rating.stored_value
                    )
            if not stored_player.date_of_birth or (
                ffe_stored_player.date_of_birth
                and (
                    not stored_player.year_of_birth
                    or stored_player.year_of_birth
                    == ffe_stored_player.date_of_birth.year
                )
            ):
                stored_player.date_of_birth = ffe_stored_player.date_of_birth
                stored_player.year_of_birth = None
            if not stored_player.comment:
                stored_player.comment = ffe_stored_player.comment
            if not stored_player.club:
                stored_player.club = ffe_stored_player.club
            stored_player.plugin_data[self.id] = copy.copy(
                ffe_stored_player.plugin_data.get(self.id, {})
            )
            stored_player.transient_arbiter_titles['ffe'] = (
                ffe_stored_player.transient_arbiter_titles.get('ffe', '')
            )

    @hookimpl
    def augment_place_card_player(
        self,
        tournament_player: TournamentPlayer,
        place_card_player: PlaceCardPlayer,
    ):
        plugin_data = FFEUtils.get_player_plugin_data(tournament_player)
        setattr(place_card_player, 'ffe_league', plugin_data.league)
        setattr(
            place_card_player,
            'ffe_licence',
            plugin_data.ffe_licence.compact_name if plugin_data.ffe_licence else '',
        )
        setattr(
            place_card_player,
            'ffe_licence_number',
            plugin_data.ffe_licence_number or '',
        )

    @hookimpl
    def place_card_field_tokens(self) -> list[dict[str, str]]:
        return [
            {'group': 'FFE', 'label': _('League'), 'expr': '{{ player.ffe_league }}'},
            {'group': 'FFE', 'label': _('Licence'), 'expr': '{{ player.ffe_licence }}'},
            {
                'group': 'FFE',
                'label': _('Licence number'),
                'expr': '{{ player.ffe_licence_number }}',
            },
        ]

    @hookimpl
    def insert_player_profile_links(
        self,
        player: Player,
        links: list[PlayerProfileLink],
    ):
        plugin_data = FFEUtils.get_player_plugin_data(player)
        # The licence number is what an arbiter recognises; the profile page
        # is keyed on the numeric FFE id, which only players coming from an
        # FFE source carry. Show whichever we have, link when we have both.
        label = plugin_data.ffe_licence_number or (
            str(plugin_data.ffe_id) if plugin_data.ffe_id else None
        )
        if not label:
            return
        links.append(
            PlayerProfileLink(
                label=_('FFE {id}').format(id=label),
                url=(
                    FFEUtils.player_url(plugin_data.ffe_id)
                    if plugin_data.ffe_id
                    else None
                ),
            )
        )

    @hookimpl
    def get_player_rating(
        self,
        tournament_rating: TournamentRating,
        player_rating_type: PlayerRatingType,
        player: 'Player',
        category: 'PlayerCategory',
    ) -> Optional[PlayerRatingAndType]:
        # In France, regardless of the player_rating_type of the tournament,
        # the FIDE rating is used, if available, falling back to the national rating
        ratings = player.ratings[tournament_rating]
        if ratings.fide is not None:
            return PlayerRatingAndType(ratings.fide, PlayerRatingType.FIDE)
        if ratings.national is not None:
            return PlayerRatingAndType(ratings.national, PlayerRatingType.NATIONAL)
        if ratings.estimated is not None:
            return PlayerRatingAndType(ratings.estimated, PlayerRatingType.ESTIMATED)
        if tournament_rating == TournamentRating.STANDARD:
            if isinstance(category, JuniorCategory):
                value = 1299
            else:
                value = 1399
        else:
            value = 1199
            if isinstance(category, JuniorCategory):
                if category.age_limit <= 10:
                    value = 799
                elif category.age_limit <= 14:
                    value = 999
        return PlayerRatingAndType(value, PlayerRatingType.ESTIMATED)

    @hookimpl
    def augment_trf_national_player(
        self, player: 'Player', trf_national_player: 'TrfNationalPlayer'
    ):
        plugin_data = FFEUtils.get_player_plugin_data(player)
        trf_national_player.classification = plugin_data.ffe_licence.value
        trf_national_player.national_id = plugin_data.ffe_licence_number or ''
        trf_national_player.origin = plugin_data.league or ''

    @hookimpl
    def augment_stored_player_from_trf_national_player(
        self,
        stored_player: 'StoredPlayer',
        trf_national_player: 'TrfNationalPlayer',
    ):
        tnp = trf_national_player
        plugin_data = FfePlayerPluginData.from_stored_value(
            stored_player.plugin_data.get(PLUGIN_NAME, {})
        )
        try:
            plugin_data.ffe_licence = PlayerFFELicence(tnp.classification)
        except ValueError:
            pass
        if tnp.origin in FFE_LEAGUES:
            plugin_data.league = tnp.origin
        if PlayerFFELicence.validate(tnp.national_id):
            plugin_data.ffe_licence_number = tnp.national_id
        stored_player.plugin_data[PLUGIN_NAME] = plugin_data.to_stored_value()

    @hookimpl
    def validate_player_tournament_move(
        self, tournament: 'Tournament', player: TournamentPlayer
    ):
        plugin_data = FFEUtils.get_player_plugin_data(player)
        ffe_licence_number = plugin_data.ffe_licence_number
        ffe_id = plugin_data.ffe_id
        if ffe_licence_number and any(
            FFEUtils.get_player_plugin_data(player_).ffe_licence_number
            == ffe_licence_number
            for player_ in tournament.tournament_players_by_id.values()
        ):
            message = _(
                'FFE licence [{ffe_licence_number}] already '
                'present in tournament [{tournament}].'
            ).format(
                ffe_licence_number=ffe_licence_number,
                tournament=tournament.name,
            )
            raise ValueError(message)
        elif ffe_id and any(
            FFEUtils.get_player_plugin_data(tournament_player_).ffe_id == ffe_id
            for tournament_player_ in tournament.tournament_players_by_id.values()
        ):
            # This string is not translated because the error should never happen
            raise ValueError(
                f'FFE ID [{ffe_id}] already present in tournament [{tournament.name}].'
            )

    @staticmethod
    def _get_ffe_club_sort_key(player: Player) -> tuple:
        return (
            not player.club.name,
            player.federation,
            FFEUtils.get_player_plugin_data(player).league or '',
            player.club,
        )

    @hookimpl
    def alter_players_tab_columns(self, columns: list[PlayersTabColumn]):
        for column in columns:
            if isinstance(column, ClubPlayersTabColumn):
                column.sort_key_function = self._get_ffe_club_sort_key
                break
        PluginUtils.insert_on_isinstance(
            columns,
            FfeLeaguePlayersTabColumn(),
            ClubPlayersTabColumn,
            after=False,
        )
        PluginUtils.insert_on_isinstance(
            columns,
            FfeLicencePlayersTabColumn(),
            FideIdPlayersTabColumn,
        )

    @hookimpl
    def insert_player_datasheet_columns(self, datasheet_columns: list[DatasheetColumn]):
        tournament: type[DatasheetColumn] = player_datasheet.TournamentColumn
        ffe_columns: list[DatasheetColumn] = [
            FfeIdDatasheetColumn(),
            FfeLicenceNumberDatasheetColumn(),
            FfeLicenceDatasheetColumn(),
        ]
        for column in ffe_columns:
            PluginUtils.insert_on_isinstance(
                datasheet_columns, column, tournament, after=False
            )
        federation: type[DatasheetColumn] = player_datasheet.FederationColumn
        PluginUtils.insert_on_isinstance(
            datasheet_columns, FfeLeagueDatasheetColumn(), federation
        )

    # ---------------------------------------------------------------------------------
    # Events
    # ---------------------------------------------------------------------------------

    @hookimpl
    def on_event_duplicated(self, event_database: EventDatabase):
        stored_tournaments = event_database.load_stored_tournaments()
        for stored_tournament in stored_tournaments:
            old_plugin_data = FfeTournamentPluginData.from_stored_value(
                stored_tournament.plugin_data.get(PLUGIN_NAME, {})
            )

            # Only retain the auto_upload setting
            new_plugin_data = FfeTournamentPluginData(
                auto_upload=old_plugin_data.auto_upload
            )
            stored_tournament.plugin_data[PLUGIN_NAME] = (
                new_plugin_data.to_stored_value()
            )
            event_database.update_stored_tournament(stored_tournament)

    @hookimpl
    def get_event_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, FfeEventPluginData

    @hookimpl
    def leave_fixed_board_holes(self, tournament: 'Tournament') -> bool:
        return FFEUtils.get_event_plugin_data(tournament.event).leave_fixed_board_holes

    @hookimpl
    def get_default_prize_currency(self) -> str:
        return 'EUR'

    # ---------------------------------------------------------------------------------
    # Tournaments
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_tournament_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, FfeTournamentPluginData

    @hookimpl
    def on_tournament_data_updated(
        self, stored_event: 'StoredEvent', stored_tournament: 'StoredTournament'
    ):
        # The FFE upload pipeline is Papi-based. In a team event only a
        # Scheveningen (uploaded as an individual Swiss) auto-uploads; the
        # other team systems have no Papi form.
        if stored_event.event_type == EventType.TEAM:
            from data.pairings.scheveningen import ScheveningenPairingSystem

            if not (stored_tournament.pairing or '').startswith(
                f'{ScheveningenPairingSystem.static_id()}_'
            ):
                return
        # Defer the event reload so result entry does not wait for it.
        if not FfeBackgroundUploader.should_schedule_tournament_upload(
            stored_event, stored_tournament
        ):
            return

        from threading import Thread

        from common.logger import get_logger

        uniq_id = stored_event.uniq_id
        tournament_id = stored_tournament.id
        assert tournament_id is not None

        def _reload_and_schedule() -> None:
            try:
                event = EventLoader().load_event(uniq_id)
                tournament = event.tournaments_by_id[tournament_id]
                FfeBackgroundUploader.schedule_upload(tournament)
            except Exception:
                get_logger().exception(
                    'FFE auto-upload scheduling failed for event [%s]', uniq_id
                )

        Thread(target=_reload_and_schedule, daemon=True).start()

    @hookimpl
    def get_tournament_form_fields_template_and_data(
        self, event: 'Event', tournament: 'Tournament | None'
    ) -> tuple[str, dict[str, Any]] | None:
        # The FFE-site connection is Papi-based. Individual tournaments
        # always carry the fields; among the team systems only a saved
        # Scheveningen, which is uploaded as an individual Swiss. On
        # creation the system is not settled yet, so team forms stay bare
        # until the tournament exists and is a Scheveningen.
        if event.is_team_event and not (
            tournament is not None and FFEUtils.supports_ffe_transfer(tournament)
        ):
            return None
        return '/ffe_tournament_form_fields.html', {}

    @hookimpl
    def validate_tournament_form_fields(
        self, data: dict[str, str], errors: dict[str, str]
    ):
        try:
            WebContext.form_data_to_int(data, 'ffe_id')
        except ValueError:
            errors['ffe_id'] = _('The FFE ID is a positive integer.')
        ffe_password = WebContext.form_data_to_str(data, 'ffe_password')
        if ffe_password and not re.match('^[A-Z]{10}$', ffe_password):
            errors['ffe_password'] = _(
                'The password of the tournament on the FFE website is made of 10 uppercase letters.'
            )

    @hookimpl
    def get_tournament_page_template_context(self) -> dict[str, Any]:
        return {'ffe_utils': FFEUtils}

    @hookimpl
    def get_tournament_connection_field(
        self, tournament: 'Tournament'
    ) -> TournamentConnectionField | None:
        if not FFEUtils.supports_ffe_transfer(tournament):
            return None
        if not FFEUtils.get_tournament_plugin_data(tournament).ffe_id:
            return None
        return TournamentConnectionField(
            label=_('FFE'),
            template='/ffe_tournament_connection_value.html',
        )

    @hookimpl
    def extend_admin_collection(
        self,
        collection_key: str,
        collection_spec: 'AdminCollectionSpec',
        event: Optional['Event'],
    ) -> None:
        if collection_key != 'tournaments':
            return
        collection_spec.ensure_list_column(
            ListColumn('transfer', label=_('Transfer')),
            before='actions',
        )

    @hookimpl
    def get_tournament_card_action_menu_items_template(self) -> str:
        return '/ffe_tournament_card_action_menu_items.html'

    @hookimpl
    def get_tournament_tie_breaks_warning_message(
        self, tournament: 'Tournament'
    ) -> str | None:
        if not FFEUtils.get_tournament_plugin_data(tournament).ffe_id:
            return None
        return PapiConverter.check_tiebreaks_warning(
            tournament.tie_breaks, three_points_for_a_win=tournament.win_points == 3.0
        )

    @hookimpl
    def get_tournament_pairing_warning_message(
        self, tournament: 'Tournament'
    ) -> str | None:
        if not FFEUtils.get_tournament_plugin_data(tournament).ffe_id:
            return None
        return PapiConverter.check_pairing_warning(tournament)

    @hookimpl
    def signal_tournament_set(
        self, event: 'Event', stored_tournament: 'StoredTournament'
    ) -> str | None:
        if blocker := PapiConverter.check_rounds(stored_tournament.rounds):
            return blocker
        pairing_variation = PairingVariationManager(event).get_object(
            stored_tournament.pairing
        )
        if warning := PapiConverter.check_pairing_variation_warning(pairing_variation):
            return warning
        return None

    @hookimpl
    def signal_special_result_set(
        self, tournament: 'Tournament', result: Result
    ) -> str | None:
        return PapiConverter.check_result(result, tournament)

    @hookimpl
    def insert_tournament_criteria_types(
        self, criteria_types: list[type['TournamentCriterion']]
    ):
        licence: type[TournamentCriterion] = FfeLicenceTournamentCriterion
        league: type[TournamentCriterion] = FfeLeagueTournamentCriterion
        gender: type[TournamentCriterion] = GenderTournamentCriterion
        PluginUtils.insert_on_equals(criteria_types, licence, gender)
        PluginUtils.insert_on_equals(criteria_types, league, licence)

    # ---------------------------------------------------------------------------------
    # Upload
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_nav_data_transfer_items(
        self, event: 'Event'
    ) -> Iterable[NavDataTransferItem]:
        # FFE upload is Papi-based. A team event only earns the transfer
        # entry through a Scheveningen, which uploads as an individual Swiss.
        if not FFEUtils.event_supports_ffe_transfer(event):
            return []
        return [
            NavDataTransferItem(
                key='ffe_upload',
                title=_('FFE'),
                icon_path='/images/ffe.png',
                modal_route_name='ffe-upload-modal',
                has_upload_error=any(
                    FFEUtils.get_tournament_plugin_data(tournament).upload_failure_id
                    for tournament in event.tournaments
                ),
            )
        ]

    # ---------------------------------------------------------------------------------
    # Printing
    # ---------------------------------------------------------------------------------

    @hookimpl
    def insert_print_document(self, print_documents: list[type['PrintDocument']]):
        from data.print_documents.documents import MatchSheetsPrintDocument

        print_documents.append(FFEPrintDocument)
        # Place the FFE fiche right after the match sheets document.
        try:
            index = print_documents.index(MatchSheetsPrintDocument)
            print_documents.insert(index + 1, FfePairingSheetDocument)
        except ValueError:
            print_documents.append(FfePairingSheetDocument)

    @hookimpl
    def insert_print_option(self, print_options: list[type['PrintOption']]):
        print_options.insert(0, FFEArbiterPrintOption)
        print_options.insert(0, FFEChiefArbiterPrintOption)
        print_options.insert(0, FFEWriterPrintOption)
        print_options.insert(0, FFEDocumentTypePrintOption)
        print_options.append(FFET3NoLicencePlayersPrintOption)
        print_options.append(FFET4NoLicencePlayersPrintOption)
        print_options.append(FFETraineePrintOption)

    @hookimpl
    def alter_print_and_screen_player_columns(
        self,
        usage: ColumnUsage,
        player_columns: list['TournamentPlayerTableColumn'],
    ):
        PluginUtils.insert_on_isinstance(
            player_columns,
            FfeLeagueTableColumn(usage),
            player_table.FederationColumn,
        )
        PluginUtils.insert_on_isinstance(
            player_columns,
            FfeLicenceTypeTableColumn(usage),
            player_table.PaidColumn,
            after=False,
        )

    @hookimpl
    def insert_print_player_splitter_types(
        self, player_splitter_types: list[type[PlayerSplitter]]
    ):
        lps: type[PlayerSplitter] = LeaguePlayerSplitter
        cps: type[PlayerSplitter] = ClubPlayerSplitter
        PluginUtils.insert_on_equals(player_splitter_types, lps, cps)

    @hookimpl
    def insert_print_qrcode_types(self, qrcode_types: list[type[QRCodeType]]):
        qrcode_types.append(FFESiteQRCodeType)

    @hookimpl
    def insert_print_individual_team_types(
        self, individual_team_types: list[type[IndividualTeamType]]
    ):
        ltt: type[IndividualTeamType] = FfeLeagueIndividualTeamType
        ctt: type[IndividualTeamType] = ClubIndividualTeamType
        PluginUtils.insert_on_equals(individual_team_types, ltt, ctt)

    @hookimpl
    def get_extra_statistics_sections(
        self, document: PrintDocument, tournaments: list['Tournament']
    ) -> Iterable[ExtraStatisticsSection]:
        if isinstance(document, StatisticsPrintDocument):
            counter = Counter[str](
                league
                for tournament in tournaments
                for p in tournament.tournament_players
                if (league := FFEUtils.get_player_plugin_data(p).league) is not None
            )

            if not counter:
                return []

            items: list[tuple[str, int]] = list(counter.items())
            items = sorted(items, key=lambda item: (-item[1], item[0]))
            rows = {k: v for k, v in items}

            return [
                ExtraStatisticsSection(
                    at='club',
                    title=_('Leagues'),
                    rows=rows,
                    subtitle=ngettext(
                        '{count} league represented',
                        '{count} leagues represented',
                        len(rows),
                    ).format(count=len(rows)),
                )
            ]
        return []

    # ---------------------------------------------------------------------------------
    # Tie breaks
    # ---------------------------------------------------------------------------------

    @property
    def _tie_break_types(self) -> list[type[BasePapiTieBreak]]:
        return [
            ffe_tie_breaks.PapiBuchholzTieBreak,
            ffe_tie_breaks.PapiPerformanceTieBreak,
            ffe_tie_breaks.PapiSumOfBuchholzTieBreak,
            ffe_tie_breaks.PapiKashdanTieBreak,
        ]

    @hookimpl
    def insert_tie_break_types(self, tie_break_types: list[type[TieBreak]]):
        for tie_break_type in self._tie_break_types:
            PluginUtils.insert_on_equals(
                tie_break_types, tie_break_type, tie_break_type.base_tie_break_type()
            )
        tie_break_types.append(ffe_tie_breaks.BerlinTieBreak)
        tie_break_types.append(ffe_tie_breaks.GamePointsDifferentialTieBreak)
        tie_break_types.append(ffe_tie_breaks.GamePointsForTieBreak)
        tie_break_types.append(ffe_tie_breaks.BoardDifferentialTieBreak)
        tie_break_types.append(ffe_tie_breaks.LowestOwnAverageRatingTieBreak)

    @hookimpl
    def insert_tie_break_option_types(
        self, tie_break_option_types: list[type[TieBreakOption]]
    ):
        tie_break_option_types.append(PapiBuchholzTypeOption)

    @hookimpl
    def insert_rule_sets(self, rule_sets: list[type['RuleSet']]):
        rule_sets.append(CoupeJeanClaudeLoubatiereRuleSet)
        rule_sets.append(CoupeDeLaPariteRuleSet)
        rule_sets.append(ChampionnatFemininN1N2RuleSet)

    @hookimpl
    def insert_swiss_system_tie_break_sets(
        self, system_sets: list['SystemTieBreakSet']
    ):
        from plugins.ffe import ffe_tie_breaks
        from plugins.ffe.ffe_tie_breaks import (
            PapiBuchholzTypeOption,
            StandardPapiBuchholzType,
            CutPapiBuchholzType,
        )

        system_sets.append(
            SystemTieBreakSet(
                key=f'{PLUGIN_NAME}:youth-championship-swiss',
                name=_('"France jeunes" and qualifiers'),
                tie_breaks=[
                    tie_breaks_module.PointsTieBreak(),
                    ffe_tie_breaks.PapiBuchholzTieBreak(
                        [PapiBuchholzTypeOption(CutPapiBuchholzType().id)]
                    ),
                    ffe_tie_breaks.PapiBuchholzTieBreak(
                        [PapiBuchholzTypeOption(StandardPapiBuchholzType().id)]
                    ),
                    ffe_tie_breaks.PapiPerformanceTieBreak(),
                ],
            )
        )
        system_sets.append(
            SystemTieBreakSet(
                key=f'{PLUGIN_NAME}:youth-championship-swiss-unrated',
                name=_('"France jeunes" and qualifiers - Unrated'),
                tie_breaks=[
                    tie_breaks_module.PointsTieBreak(),
                    ffe_tie_breaks.PapiBuchholzTieBreak(
                        [PapiBuchholzTypeOption(CutPapiBuchholzType().id)]
                    ),
                    ffe_tie_breaks.PapiBuchholzTieBreak(
                        [PapiBuchholzTypeOption(StandardPapiBuchholzType().id)]
                    ),
                    ProgressiveScoresTieBreak(),
                ],
            )
        )

    @hookimpl
    def insert_team_swiss_system_tie_break_sets(
        self, system_sets: list['SystemTieBreakSet']
    ):
        # TODO add the FFE-specific tie-breaks needed
        pass

    @hookimpl
    def insert_team_round_robin_system_tie_break_sets(
        self, system_sets: list['SystemTieBreakSet']
    ):
        # TODO add the FFE-specific tie-breaks needed
        pass

    @hookimpl
    def add_tie_breaks_to_trf_acronym_mapping(
        self, tie_break_by_acronym: dict[str, TieBreak]
    ):
        for buchholz_type in PapiBuchholzTypeManager().objects():
            tie_break = PapiBuchholzTieBreak([PapiBuchholzTypeOption(buchholz_type.id)])
            tie_break_by_acronym[tie_break.trf_acronym] = tie_break
        tie_break_by_acronym |= {
            tie_break.trf_acronym: tie_break
            for tie_break in [
                ffe_tie_breaks.PapiPerformanceTieBreak(),
                ffe_tie_breaks.PapiSumOfBuchholzTieBreak(),
                ffe_tie_breaks.PapiKashdanTieBreak(),
                ffe_tie_breaks.BerlinTieBreak(),
                ffe_tie_breaks.GamePointsDifferentialTieBreak(),
                ffe_tie_breaks.GamePointsForTieBreak(),
                ffe_tie_breaks.LowestOwnAverageRatingTieBreak(),
            ]
        }

    # ---------------------------------------------------------------------------------
    # Pairings
    # ---------------------------------------------------------------------------------

    @hookimpl
    def insert_swiss_pairing_variation_types(
        self, variation_types: list[type[SwissVariation]]
    ):
        variation_types.append(NicoisSwissVariation)

    # ---------------------------------------------------------------------------------
    # Prizes
    # ---------------------------------------------------------------------------------

    @hookimpl
    def insert_player_filter_types(
        self, player_filter_types: list[type['PlayerFilter']]
    ):
        league: type[PlayerFilter] = FfeLeaguePlayerFilter
        club: type[PlayerFilter] = ClubPlayerFilter
        PluginUtils.insert_on_equals(player_filter_types, league, club)

    @hookimpl
    def insert_player_filter_option_types(
        self, player_filter_option_types: list[type['PlayerFilterOption']]
    ):
        league: type[PlayerFilterOption] = FfeLeaguesFilterOption
        club: type[PlayerFilterOption] = ClubsFilterOption
        PluginUtils.insert_on_equals(player_filter_option_types, league, club)

    # ---------------------------------------------------------------------------------
    # Accounts
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_account_plugin_data_class(self) -> tuple[str, type[AccountPluginData]]:
        return self.id, FfeAccountPluginData

    @hookimpl
    def get_account_form_fields_template_and_data(self) -> tuple[str, dict[str, Any]]:
        return (
            '/ffe_account_form_fields.html',
            {
                'ffe_arbiter_title_options': {
                    WebContext.value_to_form_data(
                        ffe_arbiter_title.value
                    ): ffe_arbiter_title.name
                    for ffe_arbiter_title in FFEArbiterTitle
                },
            },
        )

    @hookimpl
    def validate_account_form_fields(
        self,
        data: dict[str, str],
        errors: dict[str, str],
    ):
        field: str = 'ffe_arbiter_title'
        try:
            if value := WebContext.form_data_to_str(data, field):
                FFEArbiterTitle(value)
        except ValueError:
            errors[field] = f'Invalid FFE arbiter title [{data[field]}].'

        ffe_licence_number: str | None = WebContext.form_data_to_str(
            data, field := 'ffe_licence_number'
        )
        if ffe_licence_number:
            if not PlayerFFELicence.validate(ffe_licence_number):
                errors[field] = _(
                    'Invalid FFE licence number [{ffe_licence_number}].'
                ).format(ffe_licence_number=data[field])

    @hookimpl
    def get_account_card_title_suffix(self, account: Account) -> str | None:
        title = FFEUtils.get_account_plugin_data(account).ffe_arbiter_title
        if title != FFEArbiterTitle.NONE:
            return title.short_name
        return None

    # ---------------------------------------------------------------------------------
    # Plugin hooks
    # ---------------------------------------------------------------------------------

    @hookimpl
    def augment_sce_player_sync_data_from_player(
        self,
        player: TournamentPlayer,
        sync_data: SCEPlayerSyncData,
    ):
        plugin_data = FFEUtils.get_player_plugin_data(player)
        sync_data.national_id = plugin_data.ffe_licence_number
        sync_data.ffe_licence = plugin_data.ffe_licence
        sync_data.ffe_league = plugin_data.league

    @hookimpl
    def augment_sce_player_sync_data_from_sce_data(
        self,
        sce_data: dict[str, Any],
        sync_data: SCEPlayerSyncData,
    ):
        sync_data.national_id = sce_data['national_id']
        sync_data.ffe_licence = PlayerFFELicence(
            sce_data['ffe_licence_type'] or PlayerFFELicence.NONE
        )
        sync_data.ffe_league = sce_data['ffe_league']

    @hookimpl
    def augment_stored_player_from_sce_player_sync_data(
        self,
        event: 'Event',
        stored_player: StoredPlayer,
        sync_data: SCEPlayerSyncData,
        database: EventDatabase | None,
    ):
        plugin_data = FfePlayerPluginData.from_stored_value(
            stored_player.plugin_data.get(PLUGIN_NAME, {})
        )
        plugin_data.ffe_licence_number = sync_data.national_id
        plugin_data.ffe_licence = sync_data.ffe_licence
        plugin_data.league = sync_data.ffe_league
        stored_player.plugin_data[PLUGIN_NAME] = plugin_data.to_stored_value()

    @hookimpl
    def update_sce_player_diff_field_labels(self, diff_fields: dict[str, str | None]):
        diff_fields['national_id'] = _('FFE Licence no. *** LICENCE NUMBER')
        diff_fields['ffe_licence_str'] = _('FFE Licence')
        diff_fields['ffe_league'] = _('League')

    @hookimpl
    def add_sce_upload_player_custom_fields(
        self, custom_fields: dict[str, Any], player: TournamentPlayer
    ):
        plugin_data = FFEUtils.get_player_plugin_data(player)
        if plugin_data.league:
            custom_fields['ffe_league'] = plugin_data.league

    @hookimpl
    def alter_sce_upload_player_columns(self, columns: list[SCEUploadColumn]):
        league = SCEUploadColumn('ffe_league', _('League'), is_custom=True)
        PluginUtils.insert_on_attr_equals(columns, league, 'id', 'federation')

    @hookimpl
    def alter_sce_upload_ranking_columns(self, columns: list[SCEUploadColumn]):
        league = SCEUploadColumn('ffe_league', _('League'), is_custom=True)
        PluginUtils.insert_on_attr_equals(columns, league, 'id', 'federation')

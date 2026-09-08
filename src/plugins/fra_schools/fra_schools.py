from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any, override, Iterable

from packaging.version import Version

from common.i18n import _, ngettext
from common.logger import get_logger
from data.columns import player_table, player_datasheet
from data.columns.player_datasheet import DatasheetColumn
from data.columns.player_table import TournamentPlayerTableColumn, ColumnUsage
from data.columns.players_tab import (
    PlayersTabColumn,
    ClubPlayersTabColumn,
    FederationPlayersTabColumn,
)
from data.criteria.player_filter_options import PlayerFilterOption, ClubsFilterOption
from data.criteria.player_filters import PlayerFilter, ClubPlayerFilter
from data.event import Event
from data.input_output import TournamentImporter
from data.player import TournamentPlayer
from data.print_documents import PlayerSplitter, IndividualTeamType, PrintOption
from data.print_documents.documents import (
    PrintDocument,
    StatisticsPrintDocument,
    IndividuelTeamRankingPrintDocument,
)
from data.print_documents.player_splitters import ClubPlayerSplitter
from data.tie_breaks.system_sets import SystemTieBreakSet
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredEvent,
    StoredTournament,
    StoredPlayer,
)
from database.sqlite.local_source_database import LocalSourceDatabase
from plugins import PLUGINS_DIR
from plugins.chessevent.tournament_importer.data import ChessEventPlayer
from plugins.ffe.ffe import FfeLeagueTableColumn, FfePlugin
from plugins.ffe.ffe_database import FfeDatabase
from plugins.ffe.ffe_entity import FfeLeaguePlayersTabColumn
from plugins.ffe.papi_converter import PapiPlayer
from plugins.fra_schools import PLUGIN_NAME
from plugins.fra_schools.fra_schools_controller import FRASchoolsController
from plugins.fra_schools.fra_schools_database import FRASchoolsDatabase
from plugins.fra_schools.fra_schools_entity import (
    FraSchoolCodeDatasheetColumn,
    FraSchoolLabelDatasheetColumn,
    FraSchoolPlayerSplitter,
    FraSchoolTableColumn,
    FRASchoolPlayerFilter,
    FRASchoolsFilterOption,
    FraSchoolsPlayersTabColumn,
)
from plugins.fra_schools.fra_schools_ranking_document import (
    FRASchoolsIndividualTeamMaxPerSchoolPrintOption,
    FraSchoolsRankingPrintDocument,
    FRASchoolsIndividualTeamDisplayIncompletePrintOption,
    FraSchoolsIndividualTeamType,
)
from plugins.fra_schools.utils import (
    FRASchoolsPlayerPluginData,
    FRASchoolsUtils,
    FRASchoolsEventPluginData,
    FRASchool,
)
from plugins.hookspec import ExtraStatisticsSection, hookimpl
from plugins.manager import Path
from plugins.sce.sce_data import SCEPlayerSyncData, SCEFraSchoolSyncData
from plugins.sce.sce_tournament_results_builder import SCEUploadColumn
from plugins.utils import (
    Plugin,
    PluginData,
    PluginUtils,
)
from utils.enum import (
    PlayersScreenPlayerFormat,
    PlayersScreenBoardFormat,
    PlayersScreenOpponentFormat,
)
from web.controllers.admin.player_admin_controller import PlayerAdminWebContext
from web.controllers.base_controller import BaseController

if TYPE_CHECKING:
    from data.rule_sets import RuleSet
    from data.tie_breaks.tie_breaks import TieBreak
    from data.tournament import Tournament

logger = get_logger()


class FRASchoolsPlugin(Plugin):
    @staticmethod
    def static_id() -> str:
        return PLUGIN_NAME

    @staticmethod
    def static_name() -> str:
        return _('French School Competitions')

    @property
    def dependencies(self) -> list[type[Plugin]]:
        return [FfePlugin]

    @property
    def description(self) -> str:
        return _('Adds support for school competitions in France')

    @property
    def keywords(self) -> list[str]:
        return ['school', 'scolaire', 'unss', 'france']

    @property
    def doc_markdown(self) -> str:
        return '\n\n'.join(
            [
                _(
                    'French school competitions gather players by school rather than '
                    'by club, from the local stage up to the national finals.'
                ),
                _(
                    '- the school of a player picked from the national database of the '
                    'schools;\n'
                    '- the players of a same school kept apart in the pairings;\n'
                    '- the schools used as the affiliation of the teams;\n'
                    '- the school available as a column of the players and of the '
                    'documents.'
                ),
            ]
        )

    @property
    def version(self) -> Version:
        return Version('0.1.1')

    @override
    @property
    def templates_path(self) -> Path:
        return PLUGINS_DIR / self.id / 'templates'

    @override
    @property
    def federation(self) -> str | None:
        return 'FRA'

    def used_by_stored_tournament(
        self, stored_event: 'StoredEvent', stored_tournament: StoredTournament
    ) -> bool:
        tournament_players = stored_tournament.stored_tournament_players
        for stored_tournament_player in tournament_players:
            stored_player = next(
                stored_player
                for stored_player in stored_event.stored_players
                if stored_player.id == stored_tournament_player.player_id
            )
            data = stored_player.plugin_data.get(PLUGIN_NAME, {})
            if data.get('fra_school_id', None) is not None:
                return True
        return False

    def on_enable(self):
        schools_database = FRASchoolsDatabase()
        if not schools_database.exists():
            schools_database.update()

    # ---------------------------------------------------------------------------------
    # Initialisation and configuration
    # ---------------------------------------------------------------------------------

    @property
    def controllers(self) -> list[type[BaseController]]:
        return [
            FRASchoolsController,
        ]

    # ---------------------------------------------------------------------------------
    # Input-Output
    # ---------------------------------------------------------------------------------

    @hookimpl(trylast=True)
    def insert_local_source_databases(self, databases: list[type[LocalSourceDatabase]]):
        schools: type[LocalSourceDatabase] = FRASchoolsDatabase
        ffe: type[LocalSourceDatabase] = FfeDatabase
        PluginUtils.insert_on_equals(databases, schools, ffe, True)

    # ---------------------------------------------------------------------------------
    # Events
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_event_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, FRASchoolsEventPluginData

    @property
    def event_form_fields_template(self) -> str:
        return '/fra_schools_event_form_fields.html'

    # ---------------------------------------------------------------------------------
    # Players
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_player_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, FRASchoolsPlayerPluginData

    @hookimpl
    def get_prohibited_pairing_dimensions(self):
        from data.prohibited_pairings import ProhibitedPairingDimension

        def school_key(player):
            school = FRASchoolsUtils.get_player_school(player)
            return str(school.id) if school and school.id is not None else None

        return [
            ProhibitedPairingDimension(
                id='fra-school',
                label=_('School'),
                is_team=False,
                group_key=school_key,
            )
        ]

    @hookimpl
    def get_team_affiliation_sources(self):
        from data.teams.team_affiliation import (
            TeamAffiliationSource,
            team_shared_player_value,
        )

        def school_name(player):
            school = FRASchoolsUtils.get_player_school(player)
            return school.name if school else None

        return [
            TeamAffiliationSource(
                id='fra-school',
                label=_('School'),
                resolve=lambda team: team_shared_player_value(team, school_name),
            )
        ]

    @hookimpl
    def get_player_form_template_context(
        self, web_context: 'PlayerAdminWebContext'
    ) -> dict[str, Any]:
        return FRASchoolsController.get_fra_school_template_context(web_context)

    @hookimpl
    def insert_player_form_carry_over_field(self, fields: list[str]):
        fields.append('fra_school_id')

    @hookimpl
    def insert_player_form_fields_template(
        self, templates_by_section: defaultdict[str, list[str]]
    ):
        templates_by_section['identity'].append('/fra_schools_player_form_fields.html')

    @hookimpl(trylast=True)
    def alter_players_tab_columns(self, columns: list[PlayersTabColumn]):
        for column in columns:
            if column.__class__ in [
                FederationPlayersTabColumn,
                FfeLeaguePlayersTabColumn,
                ClubPlayersTabColumn,
            ]:
                column.is_default_visible = False
        PluginUtils.insert_on_isinstance(
            columns,
            FraSchoolsPlayersTabColumn(),
            ClubPlayersTabColumn,
        )

    @hookimpl
    def insert_player_datasheet_columns(self, datasheet_columns: list[DatasheetColumn]):
        club: type[DatasheetColumn] = player_datasheet.ClubColumn
        fra_school_columns: list[DatasheetColumn] = [
            FraSchoolCodeDatasheetColumn(),
            FraSchoolLabelDatasheetColumn(),
        ]
        for column in fra_school_columns:
            PluginUtils.insert_on_isinstance(
                datasheet_columns, column, club, after=True
            )

    # ---------------------------------------------------------------------------------
    # Screens
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_default_players_screen_player_format(self) -> PlayersScreenPlayerFormat:
        return PlayersScreenPlayerFormat.NAME

    @hookimpl
    def get_default_players_screen_board_format(self) -> PlayersScreenBoardFormat:
        return PlayersScreenBoardFormat.MINIMAL

    @hookimpl
    def get_default_players_screen_opponent_format(self) -> PlayersScreenOpponentFormat:
        return PlayersScreenOpponentFormat.NONE

    @hookimpl
    def get_default_players_screen_columns(self) -> int | None:
        return 3

    # ---------------------------------------------------------------------------------
    # Printing
    # ---------------------------------------------------------------------------------

    @hookimpl
    def insert_print_document(self, print_documents: list[type['PrintDocument']]):
        sps: type[PrintDocument] = FraSchoolsRankingPrintDocument
        pps: type[PrintDocument] = IndividuelTeamRankingPrintDocument
        PluginUtils.insert_on_equals(print_documents, sps, pps, True)

    @hookimpl
    def insert_print_option(self, print_options: list[type['PrintOption']]):
        print_options.append(FRASchoolsIndividualTeamMaxPerSchoolPrintOption)
        print_options.append(FRASchoolsIndividualTeamDisplayIncompletePrintOption)

    @hookimpl(trylast=True)
    def alter_print_and_screen_player_columns(
        self,
        usage: ColumnUsage,
        player_columns: list['TournamentPlayerTableColumn'],
    ):
        # Remove FederationColumn and LeagueColumn
        player_columns[:] = [
            col
            for col in player_columns
            if not isinstance(
                col, (player_table.FederationColumn, FfeLeagueTableColumn)
            )
        ]
        PluginUtils.replace_on_isinstance(
            player_columns,
            FraSchoolTableColumn(usage),
            player_table.ClubColumn,
        )

    @hookimpl
    def insert_print_player_splitter_types(
        self, player_splitter_types: list[type[PlayerSplitter]]
    ):
        lps: type[PlayerSplitter] = FraSchoolPlayerSplitter
        cps: type[PlayerSplitter] = ClubPlayerSplitter
        PluginUtils.insert_on_equals(player_splitter_types, lps, cps, False)

    @hookimpl
    def insert_print_individual_team_types(
        self, individual_team_types: list[type[IndividualTeamType]]
    ):
        individual_team_types.append(FraSchoolsIndividualTeamType)

    @hookimpl
    def get_extra_statistics_sections(
        self, document: PrintDocument, tournaments: list['Tournament']
    ) -> Iterable[ExtraStatisticsSection]:
        if isinstance(document, StatisticsPrintDocument):
            counter = Counter[int](
                fra_school_id
                for tournament in tournaments
                for p in tournament.tournament_players
                if (
                    fra_school_id := FRASchoolsUtils.get_player_plugin_data(
                        p
                    ).fra_school_id
                )
                is not None
            )

            if not counter:
                return []

            items: list[tuple[int, int]] = list(counter.items())
            items = sorted(items, key=lambda item: (-item[1], item[0]))
            event = document.event
            assert event is not None
            rows = {}
            for k, v in items:
                school = FRASchoolsUtils.get_school_by_id(event, k)
                if school is not None:
                    rows[f'{school.name} ({school.postal_code})'] = v

            return [
                ExtraStatisticsSection(
                    at='club',
                    title=_('School'),
                    rows=rows,
                    subtitle=ngettext(
                        '{count} school represented',
                        '{count} schools represented',
                        len(rows),
                    ).format(count=len(rows)),
                )
            ]
        return []

    # ---------------------------------------------------------------------------------
    # Prizes
    # ---------------------------------------------------------------------------------

    @hookimpl
    def insert_player_filter_types(
        self, player_filter_types: list[type['PlayerFilter']]
    ):
        school: type[PlayerFilter] = FRASchoolPlayerFilter
        club: type[PlayerFilter] = ClubPlayerFilter
        PluginUtils.insert_on_equals(player_filter_types, school, club, False)

    @hookimpl
    def insert_player_filter_option_types(
        self, player_filter_option_types: list[type['PlayerFilterOption']]
    ):
        school: type[PlayerFilterOption] = FRASchoolsFilterOption
        club: type[PlayerFilterOption] = ClubsFilterOption
        PluginUtils.insert_on_equals(player_filter_option_types, school, club, False)

    # ---------------------------------------------------------------------------------
    # Tie-breaks
    # ---------------------------------------------------------------------------------

    @hookimpl
    def insert_rule_sets(self, rule_sets: list[type['RuleSet']]):
        from plugins.fra_schools.fra_schools_rule_sets import (
            ChampionnatScolaireRuleSet,
        )

        rule_sets.append(ChampionnatScolaireRuleSet)

    @hookimpl
    def insert_tie_break_types(self, tie_break_types: list[type['TieBreak']]):
        from plugins.fra_schools.fra_schools_tie_breaks import (
            BoardOrderWinsTieBreak,
        )

        tie_break_types.append(BoardOrderWinsTieBreak)

    @hookimpl(trylast=True)
    def insert_swiss_system_tie_break_sets(
        self, system_sets: list['SystemTieBreakSet']
    ):
        from data.tie_breaks import tie_breaks
        from plugins.ffe import ffe_tie_breaks
        from plugins.ffe.ffe_tie_breaks import (
            PapiBuchholzTypeOption,
            StandardPapiBuchholzType,
            CutPapiBuchholzType,
        )

        system_sets.insert(
            0,
            SystemTieBreakSet(
                key=f'{PLUGIN_NAME}:fra-schools-championship',
                name=_('French schools championship'),
                tie_breaks=[
                    ffe_tie_breaks.PapiBuchholzTieBreak(
                        [PapiBuchholzTypeOption(CutPapiBuchholzType().id)]
                    ),
                    ffe_tie_breaks.PapiBuchholzTieBreak(
                        [PapiBuchholzTypeOption(StandardPapiBuchholzType().id)]
                    ),
                    tie_breaks.ProgressiveScoresTieBreak(),
                ],
            ),
        )

    # ---------------------------------------------------------------------------------
    # Plugin hooks
    # ---------------------------------------------------------------------------------

    @hookimpl
    def update_papi_player(
        self,
        papi_player: PapiPlayer,
        tournament_player: TournamentPlayer,
        is_ffe_upload: bool,
    ):
        school = FRASchoolsUtils.get_player_school(tournament_player)
        club = ''
        if school:
            plugin_data = FRASchoolsUtils.get_event_plugin_data(tournament_player.event)
            if is_ffe_upload and plugin_data.hide_school_code_on_upload:
                club = school.label
            else:
                club = school.full_name
        papi_player.club = club

    @hookimpl
    def augment_stored_player_from_chessevent_player(
        self,
        event: Event,
        importer: TournamentImporter,
        stored_player: StoredPlayer,
        chessevent_player: ChessEventPlayer,
    ):
        school_id: int | None = None
        ce_school = chessevent_player.school
        if ce_school and FRASchoolsDatabase.file_path().exists():
            school_code = FRASchoolsUtils.extract_school_code(ce_school)
            if not school_code:
                logger.warning(
                    'Player [%s %s] [%s] [%s] - School code not found (ignored).',
                    stored_player.last_name,
                    stored_player.first_name,
                    chessevent_player.ffe_license_number,
                    chessevent_player.school,
                )
            else:
                fra_schools = FRASchoolsUtils.get_event_plugin_data(event).fra_schools
                school_id = next(
                    (s.id for s in fra_schools if s.code == school_code),
                    None,
                )
                if not school_id:
                    with FRASchoolsDatabase() as database:
                        school = database.get_school_by_code(school_code)
                    if not school:
                        logger.warning(
                            'Player [%s %s] - No school found for code [%s] (ignored).',
                            stored_player.last_name,
                            stored_player.first_name,
                            school_code,
                        )
                    else:
                        importer.stored_event_modified = True
                        school_id = FRASchoolsUtils.add_event_school(
                            event, school, save=False
                        )
        stored_player.plugin_data[PLUGIN_NAME] = FRASchoolsPlayerPluginData(
            school_id
        ).to_stored_value()

    @hookimpl
    def augment_stored_player_on_papi_import(
        self,
        event: Event,
        importer: TournamentImporter,
        stored_player: StoredPlayer,
    ):
        school_id: int | None = None
        if stored_player.club:
            school_code = FRASchoolsUtils.extract_school_code(stored_player.club)
            if school_code:
                fra_schools = FRASchoolsUtils.get_event_plugin_data(event).fra_schools
                school_id = next(
                    (s.id for s in fra_schools if s.code == school_code),
                    None,
                )
                if not school_id:
                    with FRASchoolsDatabase() as database:
                        school = database.get_school_by_code(school_code)
                    if not school:
                        logger.warning(
                            'Player [%s %s] - No school found for code [%s] (ignored).',
                            stored_player.last_name,
                            stored_player.first_name,
                            school_code,
                        )
                    else:
                        importer.stored_event_modified = True
                        school_id = FRASchoolsUtils.add_event_school(
                            event, school, save=False
                        )
        if school_id:
            stored_player.club = None
        stored_player.plugin_data[PLUGIN_NAME] = FRASchoolsPlayerPluginData(
            school_id
        ).to_stored_value()

    SCE_MANUAL_PREFIX = 'manual:'

    @hookimpl
    def augment_sce_player_sync_data_from_player(
        self,
        player: TournamentPlayer,
        sync_data: SCEPlayerSyncData,
    ):
        school = FRASchoolsUtils.get_player_school(player)
        sync_data.fra_school = (
            SCEFraSchoolSyncData(
                code=school.code or self.SCE_MANUAL_PREFIX + str(school.id),
                label=school.label,
            )
            if school
            else None
        )

    @hookimpl
    def augment_sce_player_sync_data_from_sce_data(
        self,
        sce_data: dict[str, Any],
        sync_data: SCEPlayerSyncData,
    ):
        sync_data.fra_school = SCEFraSchoolSyncData.from_dict_value(
            sce_data.get('fra_school')
        )

    @hookimpl
    def augment_stored_player_from_sce_player_sync_data(
        self,
        event: Event,
        stored_player: StoredPlayer,
        sync_data: SCEPlayerSyncData,
        database: EventDatabase | None,
    ):
        plugin_data = FRASchoolsPlayerPluginData.from_stored_value(
            stored_player.plugin_data.get(PLUGIN_NAME, {})
        )
        sce_school = sync_data.fra_school
        school_id: int | None = None
        if sce_school:
            if self.SCE_MANUAL_PREFIX in sce_school.code:
                school_id = int(sce_school.code.replace(self.SCE_MANUAL_PREFIX, ''))
            else:
                school = FRASchoolsUtils.get_school_by_code(event, sce_school.code)
                if school:
                    plugin_data.fra_school_id = school.id
                else:
                    school = FRASchool.from_label(sce_school.label)
                    school.code = sce_school.code
                    school_id = FRASchoolsUtils.add_event_school(
                        event, school, database=database
                    )
        plugin_data.fra_school_id = school_id
        stored_player.plugin_data[PLUGIN_NAME] = plugin_data.to_stored_value()

    @hookimpl
    def update_sce_player_diff_field_labels(self, diff_fields: dict[str, str | None]):
        diff_fields['fra_school_label_str'] = _('School')

    @hookimpl
    def add_sce_upload_player_custom_fields(
        self, custom_fields: dict[str, Any], player: TournamentPlayer
    ):
        school = FRASchoolsUtils.get_player_school(player)
        if school:
            custom_fields['fra_school'] = school.label

    @staticmethod
    def _replace_sce_upload_origin_columns(columns: list[SCEUploadColumn]):
        school = SCEUploadColumn('fra_school', _('French school'), is_custom=True)
        PluginUtils.insert_on_attr_equals(columns, school, 'id', 'federation')
        new_columns = [
            column
            for column in columns
            if column.id not in ('federation', 'ffe_league', 'club')
        ]
        columns.clear()
        columns.extend(new_columns)

    @hookimpl(trylast=True)
    def alter_sce_upload_player_columns(self, columns: list[SCEUploadColumn]):
        self._replace_sce_upload_origin_columns(columns)

    @hookimpl(trylast=True)
    def alter_sce_upload_ranking_columns(self, columns: list[SCEUploadColumn]):
        self._replace_sce_upload_origin_columns(columns)

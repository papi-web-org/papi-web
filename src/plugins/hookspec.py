from collections import defaultdict
from collections.abc import Iterable
from typing import Any, Hashable, TYPE_CHECKING, Optional

import apluggy as pluggy  # type: ignore

from common import APP_NAME

from plugins.utils import (
    ExtraStatisticsSection,
    NavDataTransferItem,
    PluginData,
    AccountPluginData,
    TournamentConnectionField,
)
from utils.enum import (
    Result,
    TournamentRating,
    PlayersScreenPlayerFormat,
    PlayersScreenBoardFormat,
    PlayersScreenOpponentFormat,
)

if TYPE_CHECKING:
    from data.account import Account
    from data.columns.player_datasheet import DatasheetColumn
    from data.columns.board_table import BoardColumn
    from data.columns.column import ColumnUsage, Column
    from data.columns.player_table import TournamentPlayerTableColumn
    from data.columns.players_tab import PlayersTabColumn
    from data.criteria.player_filter_options import PlayerFilterOption
    from data.criteria.player_filters import PlayerFilter
    from data.criteria.tournament_criteria import TournamentCriterion
    from data.event import Event
    from data.input_output import DataSource, TournamentExporter, TournamentImporter
    from data.input_output.trf.trf_data import TrfNationalPlayer
    from data.pairings.systems import PairingSystem
    from data.pairings.variations import PairingVariation, SwissVariation
    from data.player import (
        Player,
        PlayerProfileLink,
        TournamentPlayer,
        PlayerRatingAndType,
        PlayerRatingType,
        PlayerCategory,
    )
    from plugins.migration import PluginMigrationManager
    from data.print_documents import (
        PrintDocument,
        PrintOption,
        PlayerSplitter,
        QRCodeType,
        IndividualTeamType,
    )
    from data.print_documents.place_cards.data import PlaceCardPlayer
    from data.prohibited_pairings import (
        ProhibitedPairingDimension,
        RoundProhibitedPairingGroup,
    )
    from data.rule_sets import RuleSet
    from data.screens.screen_types import ScreenType
    from data.teams.team_affiliation import TeamAffiliationSource
    from data.tie_breaks import TieBreak, TieBreakOption
    from data.tie_breaks.system_sets import SystemTieBreakSet
    from data.tournament import Tournament
    from database.sqlite.event.event_store import StoredPlayer
    from database.sqlite.event.event_database import EventDatabase
    from database.sqlite.event.event_store import (
        StoredEvent,
        StoredTournament,
    )
    from database.sqlite.local_source_database.databases import LocalSourceDatabase
    from web.admin.collection import AdminCollectionSpec
    from web.controllers.admin.player_admin_controller import PlayerAdminWebContext

hookspec = pluggy.HookspecMarker(APP_NAME)
hookimpl = pluggy.HookimplMarker(APP_NAME)

# pylint: disable=empty-body
# mypy: disable-error-code=empty-body


class AppHookSpecs:
    """Holds all hook specs for this application"""

    # ---------------------------------------------------------------------------------
    # Initialisation and configuration
    # ---------------------------------------------------------------------------------

    @hookspec
    def get_event_migration_manager(
        self, event_database: 'EventDatabase'
    ) -> 'PluginMigrationManager':
        """Provide a migration manager for event databases"""

    @hookspec
    def get_base_admin_template_context(self) -> dict[str, Any]:
        """Provide additional template context for AdminWebContext"""

    @hookspec
    def extend_admin_collection(
        self,
        collection_key: str,
        collection_spec: 'AdminCollectionSpec',
        event: Optional['Event'],
    ):
        """Extend a request-scoped admin card/list collection."""

    # ---------------------------------------------------------------------------------
    # Input-Output
    # ---------------------------------------------------------------------------------

    @hookspec
    def insert_data_sources(self, data_sources: list[type['DataSource']]):
        """Provide extra data sources."""

    @hookspec
    def insert_local_source_databases(
        self, databases: list[type['LocalSourceDatabase']]
    ):
        """Provide extra local source databases."""

    @hookspec
    def insert_tournament_exporters(self, exporters: list[type['TournamentExporter']]):
        """Provide extra tournament export options."""

    @hookspec
    def insert_tournament_importers(self, importers: list[type['TournamentImporter']]):
        """Provide extra tournament import options."""

    # ---------------------------------------------------------------------------------
    # Players
    # ---------------------------------------------------------------------------------

    @hookspec
    def on_player_deleted(self, player: 'Player'):
        """Called when a player is deleted."""

    @hookspec
    def get_player_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        """Get the data class to use to store plugin player values.
        Also provide the ID of the plugin."""

    @hookspec
    def get_player_form_template_context(
        self, web_context: 'PlayerAdminWebContext'
    ) -> dict[str, Any]:
        """Provide additional template context for rendering the player form."""

    @hookspec
    def insert_player_form_carry_over_field(self, fields: list[str]):
        """Insert fields that are carried over in the player form. These fields
        are saved after the player search and when clicking using the 'Add other' button."""

    @hookspec
    def insert_player_form_fields_template(
        self, templates_by_section: defaultdict[str, list[str]]
    ):
        """Provide paths of templates of fields to insert into the player form,
        organised by the section at which to add the fields."""

    @hookspec
    def validate_player_form_fields(
        self,
        data: dict[str, str],
        errors: dict[str, str],
    ):
        """Validate the additional player form fields. Add the errors to the *errors* dict."""

    @hookspec
    def get_player_duplicate_key(
        self, stored_player: 'StoredPlayer'
    ) -> tuple[str, Hashable] | None:
        """Return a namespaced key used to detect plugin-specific duplicates.

        The first item is the plugin ID. Return ``None`` when no key applies.
        """

    @hookspec
    async def augment_player_after_search(
        self,
        stored_player: 'StoredPlayer',
        data_source: 'DataSource',
        with_arbiter_title: bool,
    ):
        """Add plugin specific data to a player after a successful player search"""

    @hookspec
    def augment_place_card_player(
        self,
        tournament_player: 'TournamentPlayer',
        place_card_player: 'PlaceCardPlayer',
    ):
        """Add plugin specific data to a player before printing place cards."""

    @hookspec
    def place_card_field_tokens(self) -> list[dict[str, str]]:
        """Return the place card field tokens the plugin adds (matching the data
        it sets in ``augment_place_card_player``). Each is a dict with keys
        ``group`` (e.g. a federation code), ``label`` (localized) and ``expr``
        (the Jinja expression). Surfaced in the visual editor's field picker."""

    @hookspec
    def insert_player_profile_links(
        self,
        player: 'Player',
        links: list['PlayerProfileLink'],
    ):
        """Add federation identifiers to the identity line of a player's"""

    @hookspec(firstresult=True)
    def get_player_rating(
        self,
        tournament_rating: TournamentRating,
        player_rating_type: 'PlayerRatingType',
        player: 'Player',
        category: 'PlayerCategory',
    ) -> Optional['PlayerRatingAndType']:
        """Get the estimated rating of a player."""

    @hookspec
    def validate_player_tournament_move(
        self, tournament: 'Tournament', player: 'TournamentPlayer'
    ):
        """Test if a player can be moved to a tournament.
        Raises a translated ValueError if so."""

    @hookspec
    def augment_trf_national_player(
        self, player: 'Player', trf_national_player: 'TrfNationalPlayer'
    ):
        """Augment a TRF national player from a player."""

    @hookspec
    def augment_stored_player_from_trf_national_player(
        self,
        stored_player: 'StoredPlayer',
        trf_national_player: 'TrfNationalPlayer',
    ):
        """Augment a stored player from a TRF national player."""

    @hookspec(firstresult=True)
    def player_distribution_error_message(self, event: 'Event') -> str | None:
        """Get an error message disabling the player distribution."""

    @hookspec
    def alter_players_tab_columns(self, columns: list['PlayersTabColumn']):
        """Add, modify or delete columns of the player tab."""

    @hookspec
    def insert_player_datasheet_columns(
        self, datasheet_columns: list['DatasheetColumn']
    ):
        """Provide extra columns for the player download datasheets"""

    @hookspec
    def get_check_in_table_column(self) -> 'Column[Tournament]':
        """Get a column to insert into the check-in table."""

    @hookspec
    def on_before_load_tournaments_check_in_modal(self, event: 'Event'):
        """Executed before the check-in modal is loaded."""

    # ---------------------------------------------------------------------------------
    # Events
    # ---------------------------------------------------------------------------------

    @hookspec
    def on_event_duplicated(self, event_database: 'EventDatabase'):
        """Called after an event is duplicated"""

    @hookspec
    def get_event_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        """Get the data class to use to store plugin event values.
        Also provide the ID of the plugin."""

    @hookspec
    def create_event_button_template(self) -> str:
        """Template of a button added to the `Create event` dropdown."""

    @hookspec
    def validate_event_form_fields(
        self,
        action: str,
        event: Optional['Event'],
        data: dict[str, str],
        errors: dict[str, str],
    ):
        """Validate the additional event form fields"""

    @hookspec(firstresult=True)
    def get_default_prize_currency(self) -> str:
        """Define the prize currency used as default for events
        organized by federations with unknown currencies."""

    # ---------------------------------------------------------------------------------
    # Tournaments
    # ---------------------------------------------------------------------------------

    @hookspec
    def get_tournament_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        """Get the data class to use to store plugin tournament values.
        Also provide the ID of the plugin."""

    @hookspec
    def on_tournament_data_updated(
        self, stored_event: 'StoredEvent', stored_tournament: 'StoredTournament'
    ):
        """Called when the (publishable) data of a tournament is updated"""

    @hookspec
    def get_tournament_form_fields_template_and_data(
        self, event: 'Event', tournament: 'Tournament | None'
    ) -> tuple[str, dict[str, Any]]:
        """Provide a path to the template containing additional tournament form fields"""

    @hookspec
    def validate_tournament_form_fields(
        self, data: dict[str, str], errors: dict[str, str]
    ):
        """Validate the additional tournament form fields"""

    @hookspec
    def get_tournament_page_template_context(self) -> dict[str, Any]:
        """Get the context used for the templates provided for the tournament page."""

    @hookspec
    def get_tournament_connection_field(
        self, tournament: 'Tournament'
    ) -> TournamentConnectionField | None:
        """Describe a tournament's connection to an external service.

        These fields are grouped in the tournament card and list Transfer
        section. Return None if the connection is undefined."""

    @hookspec
    def get_tournament_card_fields_template(self) -> str:
        """Provide a path to the template of fields to be added to tournament cards."""

    @hookspec(firstresult=True)
    def get_tournament_card_time_control_template(self) -> str:
        """Provide a path to the time control template to be used for tournament cards."""

    @hookspec
    def get_tournament_card_action_menu_items_template(self) -> str:
        """Path to the template to be added to the 'Actions' menu of the tournament card"""

    @hookspec
    def get_tournament_tab_action_menu_items_template(self) -> str:
        """Path to the template to be added to the 'Actions' menu of the tournament tab."""

    @hookspec
    def set_for_round(self, tournament: 'Tournament', round_: int):
        """Called to initialise the tournament for the given round."""

    @hookspec(firstresult=True)
    def get_tournament_tie_breaks_warning_message(
        self, tournament: 'Tournament'
    ) -> str | None:
        """Warning message for the tie-breaks of a tournament."""

    @hookspec(firstresult=True)
    def get_tournament_pairing_warning_message(
        self, tournament: 'Tournament'
    ) -> str | None:
        """Warning message for the pairing settings of a tournament."""

    @hookspec(firstresult=True)
    def leave_fixed_board_holes(self, tournament: 'Tournament') -> bool | None:
        """Whether a fixed board number should leave the table it displaces
        empty (and duplicate the number it lands on) instead of numbering the
        round compactly, to stay compatible with the reference file format.
        ``None`` when the plugin has no opinion."""

    @hookspec
    def get_prohibited_pairing_dimensions(
        self,
    ) -> list['ProhibitedPairingDimension']:
        """Extra prohibited-pairing grouping dimensions a plugin
        contributes (e.g. a federation "ligue", a school). Each buckets
        a tournament's members so that members sharing a key must not be
        paired. Core already ships club / federation / team-group."""

    @hookspec
    def get_team_affiliation_sources(self) -> list['TeamAffiliationSource']:
        """Extra ways to derive a team's affiliation from its players (e.g. a
        federation league, a school), offered by the teams tab's
        "fill affiliations" action. Each resolves a team to an affiliation
        name or ``None``. Core already ships the players' common club."""

    @hookspec
    def get_round_prohibited_pairing_groups(
        self, tournament: 'Tournament', round_: int
    ) -> list['RoundProhibitedPairingGroup']:
        """Prohibited-pairing groups a plugin contributes *dynamically* for a
        specific ``round_`` — typically computed from results so far (a static
        affiliation dimension can't express them). Each is a
        :class:`RoundProhibitedPairingGroup` (``name`` / ``is_hard`` /
        ``member_ids`` — team ids in a team tournament, player ids otherwise);
        groups of fewer than two members are ignored. The named groups appear
        in the prohibited-pairings modal and are merged into the round's
        snapshot alongside the dimension- and manual-derived groups."""

    @hookspec
    def signal_tournament_set(
        self, event: 'Event', stored_tournament: 'StoredTournament'
    ) -> str | None:
        """A signal sent when a tournament is updated. Returns a string to be displayed to the user"""

    @hookspec
    def signal_special_result_set(
        self, tournament: 'Tournament | None', result: Result
    ) -> str | None:
        """A signal sent when a special result is set. Returns a string to be displayed to the user"""

    @hookspec
    def load_tournament_check_in_data(self, tournament: 'Tournament'):
        """Load the check-in data of a tournament."""

    @hookspec
    def insert_tournament_criteria_types(
        self, criteria_types: list[type['TournamentCriterion']]
    ):
        """Provide additional tournament criteria types."""

    # ---------------------------------------------------------------------------------
    # Upload
    # ---------------------------------------------------------------------------------

    @hookspec
    def get_nav_data_transfer_items(
        self, event: 'Event'
    ) -> Iterable['NavDataTransferItem']:
        """Provide items for the data transfer menu."""

    # ---------------------------------------------------------------------------------
    # Screens
    # ---------------------------------------------------------------------------------

    @hookspec(firstresult=True)
    def get_default_players_screen_player_format(self) -> PlayersScreenPlayerFormat:
        """Return default format for the players on the Players Screens."""

    @hookspec(firstresult=True)
    def get_default_players_screen_board_format(self) -> PlayersScreenBoardFormat:
        """Return default display format for the boards on the Players Screens."""

    @hookspec(firstresult=True)
    def get_default_players_screen_opponent_format(self) -> PlayersScreenOpponentFormat:
        """Return default display format for the opponents on the Players Screens."""

    @hookspec(firstresult=True)
    def get_default_players_screen_columns(self) -> int | None:
        """Return default number of columns of the Players Screens."""

    @hookspec
    def insert_screen_types(self, screen_types: list[type['ScreenType']]):
        """Provide extra screen types."""

    @hookspec
    def get_screen_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        """Get the data class to use to store plugin screen values.
        Also provide the ID of the plugin."""

    # ---------------------------------------------------------------------------------
    # Printing
    # ---------------------------------------------------------------------------------
    @hookspec
    def insert_print_document(self, print_documents: list[type['PrintDocument']]):
        """Provide extra print documents"""

    @hookspec
    def insert_print_option(self, print_options: list[type['PrintOption']]):
        """Provide extra print options"""

    @hookspec
    def alter_print_and_screen_player_columns(
        self,
        usage: 'ColumnUsage',
        player_columns: list['TournamentPlayerTableColumn'],
    ):
        """Alter the player columns of print documents and screens."""

    @hookspec
    def alter_print_and_screen_board_columns(
        self,
        usage: 'ColumnUsage',
        board_columns: list['BoardColumn'],
        tournament: 'Tournament',
    ):
        """Alter the board columns of a print documents and screens."""

    @hookspec
    def insert_print_player_splitter_types(
        self, player_splitter_types: list[type['PlayerSplitter']]
    ):
        """Provide print player splitting options"""

    @hookspec
    def insert_print_qrcode_types(self, qrcode_types: list[type['QRCodeType']]):
        """Provide QR Code options"""

    @hookspec
    def insert_print_individual_team_types(
        self, individual_team_types: list[type['IndividualTeamType']]
    ):
        """Provide print team type options"""

    @hookspec
    def get_extra_statistics_sections(
        self, document: 'PrintDocument', tournaments: list['Tournament']
    ) -> Iterable[ExtraStatisticsSection]:
        """Provide extra sections for the statistics print view"""

    # ---------------------------------------------------------------------------------
    # Tie breaks
    # ---------------------------------------------------------------------------------

    @hookspec
    def insert_tie_break_types(self, tie_break_types: list[type['TieBreak']]):
        """Provide extra tournament tie-breaks."""

    @hookspec
    def insert_tie_break_option_types(
        self, tie_break_option_types: list[type['TieBreakOption']]
    ):
        """Provide extra tournament tie-break options."""

    @hookspec
    def insert_swiss_system_tie_break_sets(
        self, system_sets: list['SystemTieBreakSet']
    ):
        """Provide extra system tie-break sets for the swiss pairing system."""

    @hookspec
    def insert_team_swiss_system_tie_break_sets(
        self, system_sets: list['SystemTieBreakSet']
    ):
        """Provide extra system tie-break sets for the team swiss pairing system."""

    @hookspec
    def insert_team_round_robin_system_tie_break_sets(
        self, system_sets: list['SystemTieBreakSet']
    ):
        """Provide extra system tie-break sets for the team round-robin pairing system."""

    @hookspec
    def add_tie_breaks_to_trf_acronym_mapping(
        self, tie_break_by_acronym: dict[str, 'TieBreak']
    ):
        """AAdd tie-breaks whose base acronym does not necessarily match to a manual acronym mapping."""

    # ---------------------------------------------------------------------------------
    # Rule sets
    # ---------------------------------------------------------------------------------

    @hookspec
    def insert_rule_sets(self, rule_sets: list[type['RuleSet']]):
        """Provide extra official rule sets (federation cups etc.) that
        an arbiter can pick when creating a tournament. The picker in
        the tournament modal filters by ``RuleSet.event_type``."""

    # ---------------------------------------------------------------------------------
    # Pairings
    # ---------------------------------------------------------------------------------

    @hookspec
    def insert_swiss_pairing_variation_types(
        self, variation_types: list[type['SwissVariation']]
    ):
        """Provide extra swiss pairing variations."""

    @hookspec
    def insert_team_pairing_systems(self, pairing_systems: list[type['PairingSystem']]):
        """Provide extra team-event pairing systems"""

    @hookspec
    def insert_team_pairing_variations(
        self, variations: list[type['PairingVariation']]
    ):
        """Provide extra team-event pairing variations to expose alongside
        the core Team Swiss / Team Round-Robin variations."""

    # ---------------------------------------------------------------------------------
    # Prizes
    # ---------------------------------------------------------------------------------

    @hookspec
    def insert_player_filter_types(
        self, player_filter_types: list[type['PlayerFilter']]
    ):
        """Provide extra player filters for prizes."""

    @hookspec
    def insert_player_filter_option_types(
        self, player_filter_option_types: list[type['PlayerFilterOption']]
    ):
        """Provide the options of the added prize player filters."""

    # ---------------------------------------------------------------------------------
    # Accounts
    # ---------------------------------------------------------------------------------

    @hookspec
    def get_account_plugin_data_class(self) -> tuple[str, type[AccountPluginData]]:
        """Get the data class to use to store plugin account values.
        Also provide the ID of the plugin."""

    @hookspec
    def get_account_form_fields_template_and_data(self) -> tuple[str, dict[str, Any]]:
        """Provide a path to the template containing additional account form fields"""

    @hookspec
    def validate_account_form_fields(
        self,
        data: dict[str, str],
        errors: dict[str, str],
    ):
        """Validate the additional account form fields"""

    @hookspec
    def get_account_card_title_suffix(self, account: 'Account') -> str | None:
        """Add a suffix for an account to be displayed in the card title."""

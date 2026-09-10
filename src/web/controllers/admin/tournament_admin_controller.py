import json
import random
from collections import defaultdict
from datetime import datetime
from functools import partial
from tempfile import NamedTemporaryFile
from typing import Annotated, Any

from litestar import post, get, patch, delete
from litestar.enums import RequestEncodingType
from litestar.exceptions import NotFoundException, ClientException, ValidationException
from litestar.params import Body, FromPath, FromQuery
from litestar.plugins.htmx import HTMXRequest, HTMXTemplate
from litestar.response import Template, File, Redirect
from litestar.status_codes import HTTP_200_OK

from common.exception import SharlyChessException, OptionError, ImporterError, FormError
from common.i18n import _, ngettext
from common.logger import get_logger
from common.sharly_chess_config import SharlyChessConfig
from data.access_levels.actions import AuthAction
from data.board import Board, PlayerRatingType
from data.criteria.managers import TournamentCriterionManager
from data.event import Event
from data.championship.championship_loader import ChampionshipLoader
from data.input_output import (
    DataSourceManager,
    TournamentExporter,
    TournamentExporterManager,
    TournamentImporterManager,
)
from data.input_output.tournament_importer_options import (
    TournamentImporterOption,
    FileOption,
)
from data.input_output.tournament_importers import TournamentImporter
from data.input_output.trf.trf_importer import TrfTournamentImporter
from data.pairings import PairingSystem, PairingSystemManager
from data.pairings.systems import (
    SwissPairingSystem,
    TeamSwissPairingSystem,
)
from data.player import TournamentPlayer
from data.rule_sets import RuleSet, RuleSetManager
from data.rule_sets.rule_sets import RuleSetField, rule_set_config_key
from data.tie_breaks import (
    TieBreakManager,
    TieBreak,
    TieBreakOptionManager,
    TieBreakPurpose,
)
from data.tie_breaks.sets import (
    TieBreakSetSource,
    available_tie_break_sets,
    get_tie_break_set,
    instantiate_tie_break,
    stored_tie_break_to_dict,
    TieBreakSet,
)
from data.tournament import Tournament
from database.sqlite.config.config_database import ConfigDatabase
from database.sqlite.config.config_store import StoredTieBreakSet
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredTieBreak,
    StoredTournament,
    StoredScreen,
    StoredPairing,
    StoredPrizeGroup,
    StoredPrizeCategory,
    StoredPrizeCriterion,
    StoredPrize,
)
from plugins.manager import plugin_manager
from plugins.utils import TournamentConnectionField
from utils import Utils
from utils.date_time import format_date, format_date_range
from utils.enum import (
    BoardColor,
    EventType,
    FormAction,
    Result,
    ScoreType,
    TeamColourType,
    TournamentRating,
)
from data.screens.manager import ScreenTypeManager
from web.controllers.admin.base_event_admin_controller import (
    BaseEventAdminWebContext,
    BaseEventAdminController,
)
from web.controllers.base_controller import WebContext
from web.guards import EventGuard, ActionGuard, TournamentActionGuard
from web.messages import Message
from web.session import (
    SessionTournamentsShowDetails,
    SessionTieBreakAddOtherActive,
    SessionDistributeType,
    SessionDistributeUseBalanceGroups,
    SessionDistributeUnselectedTournaments,
    SessionDistributeGroupsById,
    SessionDistributePlayerCountByTournamentId,
)
from web.utils import SelectOption

logger = get_logger()


class TournamentAdminWebContext(BaseEventAdminWebContext):
    def __init__(
        self,
        request: HTMXRequest,
        tournament_id: int | None = None,
        tie_break_id: int | None = None,
        exporter_id: str | None = None,
        reload_event: bool = False,
    ):
        super().__init__(request, reload_event)
        assert self.admin_event is not None

        self.admin_tournament: Tournament | None = None
        if tournament_id:
            try:
                self.admin_tournament = self.admin_event.tournaments_by_id[
                    tournament_id
                ]
            except KeyError:
                raise NotFoundException(f'Tournament [{tournament_id}] not found.')

        self.admin_tie_break_id = tie_break_id
        if tie_break_id:
            assert self.admin_tournament is not None
            if tie_break_id not in self.admin_tournament.tie_breaks_by_id:
                raise NotFoundException(
                    f'Unknown tie-break ID [{tie_break_id}] '
                    f'for tournament [{self.admin_tournament.name}].'
                )
        self.admin_exporter: TournamentExporter | None = None
        if exporter_id:
            try:
                self.admin_exporter = TournamentExporterManager(
                    self.get_admin_event()
                ).get_object(exporter_id)
            except KeyError:
                raise NotFoundException(f'Unknown tournament exporter [{exporter_id}].')

    def get_admin_tournament(self) -> Tournament:
        assert self.admin_tournament is not None
        return self.admin_tournament

    def get_admin_tie_break(self) -> TieBreak:
        assert self.admin_tie_break_id is not None
        return self.get_admin_tournament().tie_breaks_by_id[self.admin_tie_break_id]

    def get_admin_exporter(self) -> TournamentExporter:
        assert self.admin_exporter is not None
        return self.admin_exporter

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'admin_tournament': self.admin_tournament,
            'admin_tie_break_id': self.admin_tie_break_id,
            'admin_exporter': self.admin_exporter,
            'allowed_tournaments': self.client.allowed_tournaments_for_action(
                AuthAction.VIEW_TOURNAMENTS_TAB
            ),
        }


class TournamentAdminController(BaseEventAdminController):
    guards = [
        EventGuard(),
        TournamentActionGuard(AuthAction.VIEW_TOURNAMENTS_TAB),
    ]

    @classmethod
    def _admin_event_tournaments_render(
        cls,
        web_context: TournamentAdminWebContext,
        template_context: dict[str, Any] | None = None,
    ) -> Template:
        event = web_context.get_admin_event()
        request = web_context.request
        plugin_context = Utils.concat_dicts(
            plugin_manager.hook_for_event(
                event, 'get_tournament_page_template_context'
            )()
        )
        plugin_card_fields_templates = plugin_manager.hook_for_event(
            event, 'get_tournament_card_fields_template'
        )()
        plugin_card_action_menu_items_templates = plugin_manager.hook_for_event(
            event, 'get_tournament_card_action_menu_items_template'
        )()
        plugin_tab_action_menu_items_templates = plugin_manager.hook_for_event(
            event, 'get_tournament_tab_action_menu_items_template'
        )()
        tournament_importers: list[TournamentImporter] = TournamentImporterManager(
            event
        ).objects()
        tournament_exporters: list[TournamentExporter] = TournamentExporterManager(
            event
        ).objects()
        template_context = (
            web_context.template_context
            | {
                'admin_event_tab': 'admin-event-tournaments-tab',
                'get_tournament_connection_fields': partial(
                    cls._get_tournament_connection_fields, event=event
                ),
                'tournament_card_time_control_template': plugin_manager.hook_for_event(
                    event, 'get_tournament_card_time_control_template'
                )()
                or 'tournament_card_time_control.html',
                'plugin_card_fields_templates': plugin_card_fields_templates,
                'tournament_importers': tournament_importers,
                'tournament_exporters': tournament_exporters,
                'plugin_card_action_menu_items_templates': plugin_card_action_menu_items_templates,
                'plugin_tab_action_menu_items_templates': plugin_tab_action_menu_items_templates,
                'show_details': SessionTournamentsShowDetails(request).get(),
                'data_sources': DataSourceManager().objects(),
            }
            | plugin_context
            | (template_context or {})
        )
        return cls._admin_base_event_render(template_context)

    @staticmethod
    def _get_tournament_connection_fields(
        tournament: Tournament, event: Event
    ) -> list[TournamentConnectionField]:
        return [
            field
            for field in plugin_manager.hook_for_event(
                event, 'get_tournament_connection_field'
            )(tournament=tournament)
            if field is not None
        ]

    @get(
        path='/event/{event_uniq_id:str}/tournaments',
        name='admin-event-tournaments-tab',
    )
    async def htmx_admin_event_tournaments_tab(
        self,
        request: HTMXRequest,
        show_details: FromQuery[bool | None],
    ) -> Template:
        web_context = TournamentAdminWebContext(request)
        if show_details is not None:
            SessionTournamentsShowDetails(request).set(show_details)

        return self._admin_event_tournaments_render(web_context)

    @classmethod
    def _prepare_tournament_modal_data(
        cls,
        action: FormAction,
        web_context: TournamentAdminWebContext,
        data: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
        redirect_to: str | None = None,
    ):
        admin_event = web_context.get_admin_event()
        pairing_systems = PairingSystemManager(admin_event).objects()
        pairing_system: PairingSystem = (
            TeamSwissPairingSystem()
            if admin_event.is_team_event
            else SwissPairingSystem()
        )
        tournament_criteria = TournamentCriterionManager(admin_event).objects()
        if data is None:
            match action:
                case 'update':
                    name = web_context.get_admin_tournament().stored_tournament.name
                case 'create':
                    name = admin_event.get_unused_tournament_name()
                case 'clone':
                    name = admin_event.get_unused_tournament_name(
                        web_context.get_admin_tournament().stored_tournament.name
                    )
                case _:
                    raise ValueError(f'action=[{action}]')
            time_control_trf25: str | None = None
            record_illegal_moves: int | None = None
            first_board_number: int | None = None
            paired_bye_result: float | None = None
            max_byes: int | None = None
            last_rounds_no_byes: int | None = None
            location: str | None = None
            player_rating_type: int | None = None
            pairing_variations: dict[str, str | None] = {
                system.variation_field_id: None for system in pairing_systems
            }
            override_unrated_rapid_blitz: bool = True
            team_player_count: int | None = None
            roster_max_size: int | None = None
            color_pattern: str | None = None
            game_points: dict[int, float] | None = None
            match_points: dict[int, float] | None = None
            primary_score: str | None = None
            secondary_score_for_colours: bool = True
            team_colour_type: str | None = None
            enforce_roster_order: bool = False
            round_robin_participation_rule: bool = True
            rule_set: str | None = None
            rule_set_config: dict[str, Any] = {}
            stored_plugin_data: dict[str, dict[str, Any]] = {}
            if action == 'create':
                # Blank by default: the arbiter sets it (Swiss), or leaves it for
                # a system that settles its own count. Stored as 0 = unset.
                rounds = 0
                rating = TournamentRating.STANDARD.value
                start_date = admin_event.start_date
                stop_date = admin_event.stop_date
                if admin_event.is_team_event:
                    team_player_count = 4
                    primary_score = ScoreType.MATCH_POINTS.value
                    team_colour_type = TeamColourType.A.value
            else:
                admin_tournament = web_context.get_admin_tournament()
                stored_tournament = admin_tournament.stored_tournament
                time_control_trf25 = stored_tournament.time_control_trf25
                record_illegal_moves = stored_tournament.record_illegal_moves
                first_board_number = stored_tournament.first_board_number
                paired_bye_result = stored_tournament.paired_bye_result
                max_byes = stored_tournament.max_byes
                last_rounds_no_byes = stored_tournament.last_rounds_no_byes
                location = stored_tournament.location
                player_rating_type = stored_tournament.player_rating_type
                start_date = admin_tournament.start_date
                stop_date = admin_tournament.stop_date
                rating = admin_tournament.rating.value
                rounds = stored_tournament.rounds
                pairing_system = admin_tournament.pairing_system
                pairing_variations[
                    admin_tournament.pairing_system.variation_field_id
                ] = admin_tournament.pairing_variation.id
                override_unrated_rapid_blitz = (
                    stored_tournament.override_unrated_rapid_blitz
                )
                team_player_count = stored_tournament.team_player_count
                roster_max_size = stored_tournament.roster_max_size
                color_pattern = stored_tournament.color_pattern
                game_points = stored_tournament.game_points
                match_points = stored_tournament.match_points
                primary_score = (
                    stored_tournament.primary_score or ScoreType.MATCH_POINTS.value
                )
                secondary_score_for_colours = (
                    stored_tournament.secondary_score_for_colours
                )
                team_colour_type = (
                    stored_tournament.team_colour_type or TeamColourType.A.value
                )
                enforce_roster_order = stored_tournament.enforce_roster_order
                round_robin_participation_rule = (
                    stored_tournament.round_robin_participation_rule
                )
                rule_set = stored_tournament.rule_set
                rule_set_config = stored_tournament.rule_set_config
                for criterion in tournament_criteria:
                    if criterion.id in stored_tournament.criteria:
                        value = criterion.value_from_stored_value(
                            stored_tournament.criteria[criterion.id]
                        )
                        criterion.set_value(value)
                stored_plugin_data = stored_tournament.plugin_data

            plugin_form_data: dict[str, str] = {}
            for (
                plugin_id,
                plugin_data_class,
            ) in Tournament.plugin_data_class_by_plugin_id().items():
                plugin_form_data |= plugin_data_class.from_stored_value(
                    stored_plugin_data.get(plugin_id, {})
                ).to_form_data(action=action)

            criteria_form_data: dict[str, str] = {}
            for criterion in tournament_criteria:
                criterion.add_to_form_data(criteria_form_data)

            # Every rule set's own fields are rendered (the picker switches
            # between them client-side), so seed them all with their
            # defaults and the selected one with the stored values.
            rule_set_config_form_data: dict[str, str] = {}
            for rs in RuleSetManager(admin_event).objects():
                stored_values = rule_set_config if rs.id == rule_set else {}
                for config_field in rs.config_fields:
                    value = stored_values.get(config_field.id, config_field.default)
                    rule_set_config_form_data[config_field.form_field_name(rs.id)] = (
                        cls._rule_set_config_form_value(config_field, value)
                    )

            round_datetimes: dict[int, datetime | None] = {}
            if action in ('update', 'clone'):
                tournament = web_context.get_admin_tournament()
                round_datetimes = tournament.round_datetimes
            # Cover any round that already has a saved date, even past the
            # stored count — a system that settles its own count stores 0, so
            # ``rounds`` would otherwise drop the dates the schedule shows.
            schedule_form_data: dict[str, str] = {}
            last_scheduled = max(round_datetimes.keys(), default=0)
            for round_num in range(1, max(rounds, last_scheduled) + 1):
                dt = round_datetimes.get(round_num)
                schedule_form_data[f'round_{round_num}_datetime'] = (
                    WebContext.value_to_form_data(dt) if dt else ''
                )

            data: dict[str, str] = WebContext.values_dict_to_form_data(
                {
                    'name': name,
                    'time_control_trf25': time_control_trf25,
                    'record_illegal_moves': record_illegal_moves,
                    'first_board_number': first_board_number,
                    'paired_bye_result': paired_bye_result,
                    'max_byes': max_byes,
                    'last_rounds_no_byes': last_rounds_no_byes,
                    'location': location,
                    'player_rating_type': player_rating_type,
                    'rounds': rounds,
                    'rating': rating,
                    'pairing_system': pairing_system.id,
                    'override_unrated_rapid_blitz': override_unrated_rapid_blitz,
                    'team_player_count': team_player_count,
                    'roster_max_size': roster_max_size,
                    'color_pattern': color_pattern,
                    'gp_win': (
                        game_points.get(Result.WIN.value) if game_points else None
                    ),
                    'gp_draw': (
                        game_points.get(Result.DRAW.value) if game_points else None
                    ),
                    'gp_loss': (
                        game_points.get(Result.LOSS.value) if game_points else None
                    ),
                    'gp_zpb': (
                        game_points.get(Result.ZERO_POINT_BYE.value)
                        if game_points
                        else None
                    ),
                    'gp_pab': (
                        game_points.get(Result.PAIRING_ALLOCATED_BYE.value)
                        if game_points
                        else None
                    ),
                    'mp_win': (
                        match_points.get(Result.WIN.value) if match_points else None
                    ),
                    'mp_draw': (
                        match_points.get(Result.DRAW.value) if match_points else None
                    ),
                    'mp_loss': (
                        match_points.get(Result.LOSS.value) if match_points else None
                    ),
                    'mp_zpb': (
                        match_points.get(Result.ZERO_POINT_BYE.value)
                        if match_points
                        else None
                    ),
                    'mp_pab': (
                        match_points.get(Result.PAIRING_ALLOCATED_BYE.value)
                        if match_points
                        else None
                    ),
                    'primary_score': primary_score,
                    'secondary_score_for_colours': (
                        'on' if secondary_score_for_colours else ''
                    ),
                    'team_colour_type': team_colour_type,
                    'enforce_roster_order': 'on' if enforce_roster_order else '',
                    'round_robin_participation_rule': (
                        'on' if round_robin_participation_rule else ''
                    ),
                    'rule_set': rule_set,
                    'date_range': WebContext.value_to_date_range_form_data(
                        start_date, stop_date
                    ),
                    'redirect_to': redirect_to,
                }
                | {field: variation for field, variation in pairing_variations.items()}
                | plugin_form_data
                | schedule_form_data
                | criteria_form_data
                | rule_set_config_form_data
            )
            stored_tournament, errors = cls._admin_get_validated_tournament_data(
                action, web_context, data
            )

        schedule_min_date = admin_event.start_date
        schedule_max_date = admin_event.stop_date
        try:
            assert data is not None
            date_range = WebContext.form_data_to_date_range(data, 'date_range')
            if date_range:
                schedule_min_date, schedule_max_date = date_range
        except FormError:
            pass
        plugin_results = plugin_manager.hook_for_event(
            admin_event, 'get_tournament_form_fields_template_and_data'
        )(event=admin_event, tournament=web_context.admin_tournament)

        plugin_form_fields_templates = [template for template, __ in plugin_results]
        form_fields_templates_data = {
            key: value for __, data in plugin_results for key, value in data.items()
        }

        player_rating_type_options: dict[str, str] = {
            '': '',
            str(PlayerRatingType.FIDE.value): _('FIDE'),
            str(PlayerRatingType.NATIONAL.value): _(
                'National *** NAME FOR RATING TYPE NATIONAL'
            ),
        }
        player_rating_type_options[''] = _('Use default - {option}').format(
            option=player_rating_type_options[str(admin_event.player_rating_type.value)]
        )

        # data and errors are always populated by the if/else block above
        assert data is not None
        assert errors is not None
        # Resolve the round-count field first: for a system that settles its own
        # count it clears data['rounds'] (blank), and the schedule shows a prompt
        # to set a number rather than any rows.
        rounds_field_context = cls._rounds_field_context(
            web_context.admin_tournament, data
        )
        rounds = int(data.get('rounds') or 0)
        event_type = (
            EventType.TEAM if admin_event.is_team_event else EventType.INDIVIDUAL
        )
        rule_sets = RuleSetManager(admin_event).for_event_type(event_type)
        rule_set_options: dict[str, str] = {'': '—'}
        rule_set_managed_fields: dict[str, list[str]] = {}
        # Per-pairing defaults: nested dict keyed by rule-set id → pairing
        # key ('' = no system, a system id, or a full variation id). The
        # modal JS prefers the variation entry, falling back to the system
        # then '', so defaults can differ between variations of one system
        # (e.g. single vs double round-robin round counts).
        # …and, one level up, by the values of the rule set's own fields
        # that declare ``affects_defaults`` ('' = the rule set has none).
        rule_set_defaults: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
        rule_set_lock_titles: dict[str, str] = {}
        # Serialisable description of each rule set's own fields, shared
        # by the rendering loop and the modal JS.
        rule_set_config_fields: dict[str, list[dict[str, Any]]] = {}
        for rs in rule_sets:
            rule_set_options[rs.id] = rs.name
            rule_set_managed_fields[rs.id] = sorted(rs.managed_fields)
            rule_set_config_fields[rs.id] = [
                {
                    'id': config_field.id,
                    'name': config_field.form_field_name(rs.id),
                    'label': config_field.label,
                    'kind': config_field.kind,
                    'help_text': config_field.help_text,
                    'choices': {value: label for value, label in config_field.choices},
                    'affects_defaults': config_field.affects_defaults,
                    'locked_once_paired': config_field.locked_once_paired,
                }
                for config_field in rs.config_fields
            ]
            defaults_by_config: dict[str, dict[str, dict[str, str]]] = {}
            for config in rs.config_combinations() or [{}]:
                configured = type(rs)(config)
                defaults_by_pairing: dict[str, dict[str, str]] = {
                    '': dict(configured.form_defaults()),
                }
                for system in pairing_systems:
                    defaults_by_pairing[system.id] = dict(
                        configured.form_defaults(system.id)
                    )
                    variation_manager = system.variation_manager(admin_event)
                    for variation in variation_manager.entity_types():
                        variation_id = variation.static_id()
                        defaults_by_pairing[variation_id] = dict(
                            configured.form_defaults(system.id, variation_id)
                        )
                defaults_by_config[rule_set_config_key(config)] = defaults_by_pairing
            rule_set_defaults[rs.id] = defaults_by_config
            rule_set_lock_titles[rs.id] = _('Set by rule set "{name}".').format(
                name=rs.name
            )
        template_context = (
            {
                'rating_options': cls._get_rating_options(),
                'pairing_systems': pairing_systems,
                'pairing_system_options': PairingSystemManager(admin_event).options(),
                'rule_sets': rule_sets,
                'rule_set_options': rule_set_options,
                'rule_set_managed_fields': rule_set_managed_fields,
                'rule_set_defaults': rule_set_defaults,
                'rule_set_lock_titles': rule_set_lock_titles,
                'rule_set_config_fields': rule_set_config_fields,
                'plugin_form_fields_templates': plugin_form_fields_templates,
                'admin_tournament': None
                if action == 'clone'
                else web_context.admin_tournament,
                'cloned_tournament': web_context.admin_tournament
                if action == 'clone'
                else None,
                'player_rating_type_options': player_rating_type_options,
                'is_team_event': admin_event.is_team_event,
                'BoardColor': BoardColor,
                'score_type_options': {t.value: str(t) for t in ScoreType},
                'team_colour_type_options': {t.value: str(t) for t in TeamColourType},
                'modal': 'tournament',
                'action': action,
                'data': data,
                'errors': errors,
            }
            | rounds_field_context
            | {
                'tournament_criteria': tournament_criteria,
                'force_criteria_open': any(
                    criterion.is_used_in_form_data(data)
                    for criterion in tournament_criteria
                ),
                'force_points_open': any(
                    field in errors or (data.get(field) or '').strip()
                    for field in (
                        'gp_win',
                        'gp_draw',
                        'gp_loss',
                        'gp_zpb',
                        'gp_pab',
                        'mp_win',
                        'mp_draw',
                        'mp_loss',
                        'mp_zpb',
                        'mp_pab',
                    )
                ),
                # The current rounds count is needed to render the schedule inputs
                'schedule_rounds': rounds,
                'force_schedule_open': any(
                    data.get(f'round_{n}_datetime') for n in range(1, rounds + 1)
                ),
                'schedule_min_date': format_date(schedule_min_date),
                'schedule_max_date': format_date(schedule_max_date),
            }
            | form_fields_templates_data
        )

        return template_context

    @classmethod
    def _admin_get_validated_tournament_data(
        cls,
        action: str,
        web_context: TournamentAdminWebContext,
        data: dict[str, str] | None = None,
    ) -> tuple[StoredTournament, dict[str, str]]:
        event = web_context.get_admin_event()
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        start_date = event.start_date
        stop_date = event.stop_date
        # 0 (a blank field) means unset: a system that settles its own count
        # works it out (see ``Tournament.rounds``); any other system needs a
        # value (checked below). A stored non-zero value on an automatic system
        # is only the arbiter's schedule count, still overridden by
        # ``Tournament.rounds``.
        rounds = WebContext.form_data_to_int(data, field := 'rounds') or 0
        rounds_are_automatic = rounds == 0
        tournament: Tournament | None = None

        index = len(event.tournaments)
        if rounds < 0:
            errors[field] = _('A positive integer is expected.')
        elif rounds_are_automatic:
            pass
        elif action == 'update':
            tournament = web_context.get_admin_tournament()
            index = tournament.index
            if rounds < tournament.last_paired_round:
                errors['rounds'] = _(
                    'Impossible to set a round number lower '
                    'than the last round with pairings #{round}.'
                ).format(round=tournament.current_round)
        rating = (
            WebContext.form_data_to_int(data, field := 'rating')
            or TournamentRating.STANDARD.value
        )
        try:
            TournamentRating(rating)
        except ValueError:
            errors[field] = f'Unknown rating [{rating}]'
        try:
            date_range = WebContext.form_data_to_date_range(data, field := 'date_range')
            if date_range:
                start_date, stop_date = date_range
        except FormError as e:
            errors[field] = str(e)

        default_pairing_system_id = (
            TeamSwissPairingSystem.static_id()
            if event.is_team_event
            else SwissPairingSystem.static_id()
        )
        pairing_system = PairingSystemManager(event).get_object(
            WebContext.form_data_to_str(data, 'pairing_system')
            or default_pairing_system_id
        )
        pairing = WebContext.form_data_to_str(
            data, f'{pairing_system.id}_pairing_variation'
        )

        # A system that does not settle its own count needs an explicit number:
        # a blank field must not silently become one round. Only flag it when we
        # are sure the chosen system is not an automatic one.
        if rounds_are_automatic and pairing:
            from data.pairings import PairingVariationManager

            try:
                variation = PairingVariationManager(event).get_object(pairing)
            except KeyError:
                variation = None
            if variation is not None and not variation.sets_its_own_round_count:
                errors.setdefault('rounds', _('Please enter the number of rounds.'))

        if action == 'update':
            tournament = web_context.get_admin_tournament()
            if tournament.started:
                not_updatable_values: dict[str, str] = {
                    'rating': str(tournament.rating.value),
                    tournament.pairing_system.variation_field_id: tournament.pairing_variation.id,
                    'pairing_system': tournament.pairing_system.id,
                }
                if not tournament.pairing_system.allow_rounds_update_once_started:
                    not_updatable_values |= {'rounds': str(tournament.rounds)}
                for field, expected_value in not_updatable_values.items():
                    if data.get(field, '') != expected_value:
                        errors[field] = _(
                            "This field can't be updated once the tournament has started."
                        )
            elif tournament.has_pairings:
                # Not "started" (no current round) but already paired:
                # changing the pairing system would orphan the existing
                # boards. Block it — the arbiter must unpair first.
                for field, expected_value in (
                    (
                        tournament.pairing_system.variation_field_id,
                        tournament.pairing_variation.id,
                    ),
                    ('pairing_system', tournament.pairing_system.id),
                ):
                    if data.get(field, '') != expected_value:
                        errors[field] = _(
                            'Unpair the tournament before changing its pairing system.'
                        )
        name = WebContext.form_data_to_str(data, field := 'name') or ''
        if not name:
            errors['name'] = _('This field is required.')
        else:
            used_names = list(event.tournaments_by_name.keys())
            if action == 'update':
                used_names.remove(web_context.get_admin_tournament().name)
            if name in used_names:
                errors[field] = _('This name is already used.')
        time_control_trf25 = WebContext.form_data_to_str(data, 'time_control_trf25')
        record_illegal_moves = cls._admin_validate_record_illegal_moves_update_data(
            data, errors
        )
        first_board_number = WebContext.form_data_to_int(data, 'first_board_number')
        paired_bye_result = WebContext.form_data_to_int(data, 'paired_bye_result')
        max_byes = WebContext.form_data_to_int(data, 'max_byes')
        last_rounds_no_byes = WebContext.form_data_to_int(data, 'last_rounds_no_byes')
        location = WebContext.form_data_to_str(data, 'location')
        player_rating_type = WebContext.form_data_to_int(data, 'player_rating_type')
        override_unrated_rapid_blitz = WebContext.form_data_to_bool(
            data, 'override_unrated_rapid_blitz'
        )

        game_points: dict[int, float] = {}
        for result, gp_field in (
            (Result.WIN, 'gp_win'),
            (Result.DRAW, 'gp_draw'),
            (Result.LOSS, 'gp_loss'),
            (Result.ZERO_POINT_BYE, 'gp_zpb'),
            (Result.PAIRING_ALLOCATED_BYE, 'gp_pab'),
        ):
            raw = WebContext.form_data_to_str(data, gp_field)
            if raw is None or raw == '':
                continue
            try:
                gp_value = float(raw)
            except ValueError:
                errors[gp_field] = _('A number is expected.')
                continue
            # Negative game points aren't representable in the TRF
            # point system (bbpPairings reads it to pair) — disallow
            # them for now.
            if gp_value < 0:
                errors[gp_field] = _('A positive value is expected.')
                continue
            game_points[result.value] = gp_value

        # A win must be worth at least a draw, and a draw at least a
        # loss.
        win_gp = game_points.get(Result.WIN.value)
        draw_gp = game_points.get(Result.DRAW.value)
        loss_gp = game_points.get(Result.LOSS.value)
        if (
            win_gp is not None
            and draw_gp is not None
            and loss_gp is not None
            and not (loss_gp <= draw_gp <= win_gp)
        ):
            errors['gp_draw'] = _('Game points must satisfy loss ≤ draw ≤ win.')

        team_player_count: int | None = None
        roster_max_size: int | None = None
        color_pattern: str | None = None
        match_points: dict[int, float] | None = None
        primary_score: str | None = None
        secondary_score_for_colours = True
        team_colour_type: str | None = None
        enforce_roster_order = False
        if event.is_team_event:
            enforce_roster_order = WebContext.form_data_to_bool(
                data, 'enforce_roster_order'
            )
            secondary_score_for_colours = WebContext.form_data_to_bool(
                data, 'secondary_score_for_colours'
            )
            team_player_count = WebContext.form_data_to_int(
                data, field := 'team_player_count'
            )
            if team_player_count is None or team_player_count < 1:
                errors[field] = _('A positive integer is expected.')

            # Roster cap is optional (blank = no limit) but, when set, must be
            # at least the team-match size.
            roster_max_size = WebContext.form_data_to_int(
                data, field := 'roster_max_size'
            )
            if roster_max_size is not None and roster_max_size < 1:
                errors[field] = _('A positive integer is expected.')
            elif (
                roster_max_size is not None
                and team_player_count is not None
                and roster_max_size < team_player_count
            ):
                errors[field] = _(
                    'The roster cap cannot be smaller than the team-match size.'
                )

            field_name = 'primary_score'
            raw_score = (
                WebContext.form_data_to_str(data, field_name)
                or ScoreType.MATCH_POINTS.value
            )
            try:
                primary_score = ScoreType(raw_score).value
            except ValueError:
                errors[field_name] = f'Invalid score type value [{raw_score}].'
                primary_score = ScoreType.MATCH_POINTS.value

            raw_colour_type = (
                WebContext.form_data_to_str(data, 'team_colour_type')
                or TeamColourType.A.value
            )
            try:
                team_colour_type = TeamColourType(raw_colour_type).value
            except ValueError:
                errors['team_colour_type'] = (
                    f'Invalid colour-type value [{raw_colour_type}].'
                )
                team_colour_type = TeamColourType.A.value

            color_pattern = (
                WebContext.form_data_to_str(data, field := 'color_pattern') or None
            )
            if color_pattern is not None:
                stripped = color_pattern.strip().upper()
                allowed = {BoardColor.WHITE.value, BoardColor.BLACK.value}
                if not stripped:
                    color_pattern = None
                elif not set(stripped) <= allowed:
                    errors[field] = _(
                        'Use only "{w}" and "{b}" characters '
                        '(or leave blank for default).'
                    ).format(w=BoardColor.WHITE.value, b=BoardColor.BLACK.value)
                elif (
                    team_player_count is not None
                    and team_player_count > 0
                    and len(stripped) != team_player_count
                ):
                    errors[field] = _(
                        'Length ({len}) must match players per team match ({count}).'
                    ).format(len=len(stripped), count=team_player_count)
                else:
                    color_pattern = stripped

            match_points = {}
            for result, mp_field in (
                (Result.WIN, 'mp_win'),
                (Result.DRAW, 'mp_draw'),
                (Result.LOSS, 'mp_loss'),
                (Result.ZERO_POINT_BYE, 'mp_zpb'),
                (Result.PAIRING_ALLOCATED_BYE, 'mp_pab'),
            ):
                raw = WebContext.form_data_to_str(data, mp_field)
                if raw is None or raw == '':
                    continue
                try:
                    mp_value = float(raw)
                except ValueError:
                    errors[mp_field] = _('A number is expected.')
                    continue
                if mp_value < 0:
                    errors[mp_field] = _('A positive value is expected.')
                    continue
                match_points[result.value] = mp_value

            # A win must be worth at least a draw, and a draw at least
            # a loss.
            win_mp = match_points.get(Result.WIN.value)
            draw_mp = match_points.get(Result.DRAW.value)
            loss_mp = match_points.get(Result.LOSS.value)
            if (
                win_mp is not None
                and draw_mp is not None
                and loss_mp is not None
                and not (loss_mp <= draw_mp <= win_mp)
            ):
                errors['mp_draw'] = _('Match points must satisfy loss ≤ draw ≤ win.')

        round_robin_participation_rule = WebContext.form_data_to_bool(
            data, 'round_robin_participation_rule'
        )

        rule_set_id = WebContext.form_data_to_str(data, field := 'rule_set') or None
        rule_set_type: type['RuleSet'] | None = None
        if rule_set_id:
            try:
                rule_set_type = RuleSetManager(event).get_type(rule_set_id)
            except KeyError:
                errors[field] = _('Unknown rule set [{id}].').format(id=rule_set_id)
                rule_set_id = None
        rule_set_config = (
            cls._read_rule_set_config(rule_set_type(), data, errors)
            if rule_set_type is not None
            else {}
        )

        stored_criteria: dict[str, Any] = {}
        for criterion in TournamentCriterionManager(event).objects():
            value = criterion.value_from_form_data(data, errors)
            if value is None:
                continue
            criterion.set_value(value)
            stored_criteria[criterion.id] = criterion.stored_value

        # validation of rounds within the range of the event and sequentially ordered
        round_datetimes: dict[int, datetime | None] = {}
        prev_dt: datetime | None = None
        for round_num in range(1, rounds + 1):
            field = f'round_{round_num}_datetime'
            try:
                dt = WebContext.form_data_to_datetime(data, field)
                if dt is not None:
                    # validate for date range and sequential ordering
                    if not start_date <= dt.date() <= stop_date:
                        errors[field] = _(
                            'Time outside of tournament time range ({range}).'
                        ).format(range=format_date_range(start_date, stop_date))
                    elif prev_dt is not None and dt <= prev_dt:
                        errors[field] = _(
                            'Round #%(round)d must be scheduled after round #%(prev)d.'
                        ) % {'round': round_num, 'prev': round_num - 1}
                    else:
                        prev_dt = dt
                round_datetimes[round_num] = dt
            except FormError as e:
                errors[field] = str(e)
                round_datetimes[round_num] = None

        plugin_manager.hook_for_event(
            web_context.get_admin_event(), 'validate_tournament_form_fields'
        )(data=data, errors=errors)

        plugin_data: dict[str, dict[str, Any]] = {}
        for (
            plugin_id,
            plugin_data_class,
        ) in Tournament.plugin_data_class_by_plugin_id().items():
            previous_object = None
            if tournament is not None:
                previous_object = tournament.plugin_data.get(plugin_id)

            plugin_data[plugin_id] = plugin_data_class.from_form_data(
                data, action=action, previous_object=previous_object
            ).to_stored_value()

        stored_tournament = StoredTournament(
            id=web_context.admin_tournament.id
            if web_context.admin_tournament
            and action
            not in [
                'create',
                'clone',
            ]
            else None,
            name=name,
            index=index,
            time_control_trf25=time_control_trf25,
            record_illegal_moves=record_illegal_moves,
            first_board_number=first_board_number,
            paired_bye_result=paired_bye_result,
            max_byes=max_byes,
            last_rounds_no_byes=last_rounds_no_byes,
            location=location,
            player_rating_type=player_rating_type,
            start_date=start_date,
            stop_date=stop_date,
            # 0 = unset; a system that settles its own count keeps it (worked
            # out by ``Tournament.rounds``), which also defaults everything else
            # to at least one round. Don't force 1 here, or clearing an
            # automatic field would store a spurious count.
            rounds=rounds,
            rating=rating or TournamentRating.STANDARD.value,
            pairing=pairing or '',
            override_unrated_rapid_blitz=override_unrated_rapid_blitz,
            game_points=game_points or None,
            team_player_count=team_player_count,
            roster_max_size=roster_max_size,
            match_points=match_points,
            color_pattern=color_pattern,
            primary_score=primary_score,
            secondary_score_for_colours=secondary_score_for_colours,
            team_colour_type=team_colour_type,
            enforce_roster_order=enforce_roster_order,
            round_robin_participation_rule=round_robin_participation_rule,
            rule_set=rule_set_id,
            rule_set_config=rule_set_config,
            plugin_data=plugin_data,
            round_datetimes=round_datetimes,
            criteria=stored_criteria,
        )
        # When a rule set is attached, let it override the form's
        # scoring / format defaults. The user can edit later to deviate.
        if rule_set_type is not None and not errors:
            system_id = cls._resolve_pairing_system_id(event, stored_tournament.pairing)
            rule_set_type(rule_set_config).apply_defaults(stored_tournament, system_id)
        return stored_tournament, errors

    @staticmethod
    def _rule_set_config_form_value(config_field: RuleSetField, value: Any) -> str:
        """Render one rule-set config value as form data (the checkbox
        macro reads 'on' / absent)."""
        if config_field.kind == 'bool':
            return 'on' if value else ''
        return '' if value is None else str(value)

    @staticmethod
    def _read_rule_set_config(
        rule_set: 'RuleSet', data: dict[str, str], errors: dict[str, str]
    ) -> dict[str, Any]:
        """Read the values of the fields the rule set adds to the form,
        keyed by field id. Types and ``select`` choices are checked here;
        anything beyond that is the rule set's own business."""
        values: dict[str, Any] = {}
        value: Any
        for config_field in rule_set.config_fields:
            name = config_field.form_field_name(rule_set.id)
            match config_field.kind:
                case 'bool':
                    values[config_field.id] = WebContext.form_data_to_bool(data, name)
                    continue
                case 'int':
                    try:
                        value = WebContext.form_data_to_int(data, name)
                    except ValueError:
                        errors[name] = _('An integer is expected.')
                        continue
                case _:
                    value = WebContext.form_data_to_str(data, name)
            if value is None or value == '':
                values[config_field.id] = config_field.default
                continue
            if config_field.kind == 'select' and value not in config_field.values():
                errors[name] = _('Unexpected value [{value}].').format(value=value)
                continue
            values[config_field.id] = value
        fields_by_id = {f.id: f for f in rule_set.config_fields}
        for field_id, message in rule_set.validate_config(values).items():
            invalid_field = fields_by_id.get(field_id)
            if invalid_field is not None:
                errors[invalid_field.form_field_name(rule_set.id)] = message
        return values

    @staticmethod
    def _resolve_pairing_system_id(event: 'Event', variation_id: str) -> str | None:
        """Resolve a pairing-variation id to its system id (the value
        rule sets key their overrides by). Returns ``None`` when the
        variation isn't registered."""
        from data.pairings import PairingVariationManager

        try:
            variation = PairingVariationManager(event).get_object(variation_id)
        except KeyError:
            return None
        return variation.system().id

    @classmethod
    def _apply_rule_set_tie_breaks(
        cls,
        database: 'EventDatabase',
        event: 'Event',
        stored_tournament: StoredTournament,
    ) -> None:
        """Replace the tournament's stored tie-breaks with the rule
        set's canonical list for the current pairing system. No-op
        when the tournament has no rule set, or its rule set defines
        no overrides for the chosen pairing system. Called after every
        tournament save."""
        rule_set_id = stored_tournament.rule_set
        if not rule_set_id or stored_tournament.id is None:
            return
        try:
            rule_set_type = RuleSetManager(event).get_type(rule_set_id)
        except KeyError:
            return
        rule_set = rule_set_type(stored_tournament.rule_set_config)
        # ``stored_tournament.pairing`` is the pairing VARIATION id;
        # rule sets key their overrides by pairing SYSTEM id (e.g.
        # ``TEAM_SWISS``) — resolve the variation to find the system.
        system_id = cls._resolve_pairing_system_id(event, stored_tournament.pairing)
        if system_id is None:
            return
        overrides = rule_set.tie_breaks_for_pairing(system_id)
        if not overrides:
            return
        # Rule sets carry standings criteria, so the list replaced here is a
        # standings one.
        database.delete_all_tournament_stored_tie_breaks(stored_tournament.id)
        for index, (tb_type, options) in enumerate(overrides):
            database.add_stored_tie_break(
                StoredTieBreak(
                    id=None,
                    tournament_id=stored_tournament.id,
                    type=tb_type,
                    options=dict(options),
                    index=index,
                )
            )

    @get(
        path='/tournament-modal/create/{event_uniq_id:str}',
        name='admin-tournament-create-modal',
    )
    async def htmx_admin_tournament_create_modal(
        self, request: HTMXRequest
    ) -> Template:
        web_context = TournamentAdminWebContext(request)
        template_context = self._prepare_tournament_modal_data(
            FormAction.CREATE, web_context
        )

        return self._admin_event_tournaments_render(
            web_context=web_context,
            template_context=template_context,
        )

    @get(
        path='/tournament-modal/{action:str}/{event_uniq_id:str}/{tournament_id:int}',
        name='admin-tournament-modal',
        guards=[TournamentActionGuard(AuthAction.UPDATE_TOURNAMENTS)],
    )
    async def htmx_admin_tournament_modal(
        self,
        request: HTMXRequest,
        action: FromQuery[FormAction],
        tournament_id: FromPath[int],
        redirect_to: FromQuery[str | None] = None,
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id=tournament_id)
        template_context = self._prepare_tournament_modal_data(
            action, web_context, redirect_to=redirect_to
        )

        return self._admin_event_tournaments_render(
            web_context=web_context,
            template_context=template_context,
        )

    @staticmethod
    def _rounds_field_context(
        tournament: Tournament | None,
        data: dict[str, str],
    ) -> dict[str, Any]:
        """How to render the round-count field for the chosen pairing system.

        The field starts blank for every system (nothing is prefilled). A
        round-robin's length follows from its entrants, a knock-out's from the
        bracket depth: those systems settle their own count (worked out on
        demand by ``Tournament.rounds``, stored as 0), so a blank field shows an
        "Automatic" placeholder and is the arbiter's to override only when they
        want to lay a schedule over a specific number — whatever they enter is
        stored and shown again, and generation warns if it differs from what the
        system will play. Once paired the count is fixed and the field is greyed.
        """
        from data.pairings import PairingVariationManager

        # A stored 0 (or the create default) means "unset" — show it blank so
        # the placeholder can speak, for every system.
        if (data.get('rounds') or '').strip() == '0':
            data['rounds'] = ''

        # 'pairing_system' carries the system id; the chosen variation
        # sits in a field named after that system and carries the full
        # variation id.
        system_id = data.get('pairing_system') or ''
        variation_id = data.get(f'{system_id}_pairing_variation') or ''
        variation = None
        if variation_id:
            try:
                variation = PairingVariationManager(
                    tournament.event if tournament else None
                ).get_object(variation_id)
            except KeyError:
                variation = None
        if variation is None or not variation.sets_its_own_round_count:
            return {
                'rounds_are_automatic': False,
                'rounds_placeholder_automatic': False,
                'rounds_automatic_count': None,
                'rounds_automatic_reason': '',
                'rounds_automatic_hint': '',
            }
        # Once the tournament is under way the count is settled by the bracket
        # (or table), so show it, greyed out — no longer the arbiter's to change.
        if tournament is not None and tournament.has_pairings:
            data['rounds'] = str(tournament.rounds)
            return {
                'rounds_are_automatic': True,
                'rounds_placeholder_automatic': True,
                'rounds_automatic_count': tournament.rounds,
                'rounds_automatic_reason': _(
                    'The number of rounds follows from the pairing system.'
                ),
                'rounds_automatic_hint': '',
            }
        # Before pairing: blank (showing the "Automatic" placeholder) unless the
        # arbiter has entered a value, which is kept as-is. ``rounds_automatic_
        # count`` feeds the schedule fallback only, not the placeholder.
        auto = tournament.automatic_rounds if tournament else None
        return {
            'rounds_are_automatic': False,
            'rounds_placeholder_automatic': True,
            'rounds_automatic_count': auto,
            'rounds_automatic_reason': '',
            'rounds_automatic_hint': '',
        }

    @get(
        path='/tournament-rounds-field/{event_uniq_id:str}',
        name='admin-tournament-rounds-field',
    )
    async def htmx_admin_tournament_rounds_field(
        self,
        request: HTMXRequest,
        tournament_id: FromQuery[int | None] = None,
    ) -> Template:
        """Re-render the round-count field alone, after a change to the
        pairing system, its variation or the board count."""
        web_context = TournamentAdminWebContext(request, tournament_id=tournament_id)
        tournament = web_context.admin_tournament
        data: dict[str, str] = dict(request.query_params)
        # Seed from the stored value (0 = unset → blank), not the worked-out
        # count, so switching system leaves the field blank rather than sticking
        # to the automatic number.
        data.setdefault(
            'rounds',
            str(tournament.stored_tournament.rounds) if tournament else '',
        )
        template_context = (
            web_context.template_context
            | {
                'admin_event': web_context.get_admin_event(),
                'data': data,
                'errors': {},
                'reload_schedule_script': (
                    "htmx.trigger(document.getElementById('schedule-section'), "
                    "'schedule-params-updated')"
                ),
            }
            | self._rounds_field_context(tournament, data)
        )
        return HTMXTemplate(
            template_name='/admin/tournaments/tournament_rounds_field.html',
            re_swap='outerHTML',
            re_target='#rounds-field',
            context=template_context,
        )

    @get(
        path='/tournament-schedule-section/{event_uniq_id:str}',
        name='admin-tournament-schedule-section',
    )
    async def htmx_admin_tournament_schedule_section(
        self,
        request: HTMXRequest,
        tournament_id: FromQuery[int | None] = None,
        rounds: FromQuery[str | None] = None,
        date_range: FromQuery[str | None] = None,
    ) -> Template:
        """Return just the schedule section for an outerHTML swap.

        Called by the rounds number input on change so the schedule fields
        update live without a full modal re-render.
        """
        web_context = TournamentAdminWebContext(request, tournament_id=tournament_id)
        tournament = web_context.admin_tournament
        event = web_context.get_admin_event()
        # Blank means no schedule yet — show the prompt (0 rows). The one
        # exception is a paired tournament: its field is disabled, so the
        # browser omits it, and the settled count should still lay out the rows.
        rounds_value = int(rounds or 0)
        if rounds_value < 1 and tournament is not None and tournament.has_pairings:
            rounds_value = tournament.rounds

        min_date = event.start_date
        max_date = event.stop_date
        if date_range:
            try:
                form_date_range = WebContext.form_data_to_date_range(
                    {'range': date_range}, 'range'
                )
                if form_date_range:
                    min_date, max_date = form_date_range
            except FormError:
                pass

        # preserve datetimes when the user changes the number of rounds.
        # prefer values submitted from the form i.e user-typed, not yet saved
        # over values from the database.
        existing_datetimes: dict[int, datetime | None] = {}
        if tournament:
            existing_datetimes = tournament.round_datetimes

        # extract form-submitted round datetime values (sent via hx-include)
        form_datetimes: dict[str, str] = {}
        for key, value in request.query_params.items():
            if key.startswith('round_') and key.endswith('_datetime'):
                form_datetimes[key] = value

        schedule_form_data: dict[str, str] = {}
        has_any_value = False
        for round_num in range(1, rounds_value + 1):
            field = f'round_{round_num}_datetime'
            if field in form_datetimes and form_datetimes[field]:
                schedule_form_data[field] = form_datetimes[field]
                has_any_value = True
            else:
                dt = existing_datetimes.get(round_num)
                schedule_form_data[field] = (
                    WebContext.value_to_form_data(dt) if dt else ''
                )
                if dt:
                    has_any_value = True

        # evaluate if the schedule section should be open or collapsed
        # if collapsed it should remain collapsed
        schedule_collapsed_form = request.query_params.get('schedule_collapsed')
        if schedule_collapsed_form is not None:
            force_schedule_open = schedule_collapsed_form == 'false'
        else:
            force_schedule_open = has_any_value

        template_context = web_context.template_context | {
            'admin_event': event,
            'schedule_rounds': rounds_value,
            'data': schedule_form_data,
            'errors': {},
            'force_schedule_open': force_schedule_open,
            'schedule_min_date': format_date(min_date),
            'schedule_max_date': format_date(max_date),
        }

        return HTMXTemplate(
            template_name='/admin/tournaments/tournament_schedule_section.html',
            # replace the entire schedule section, looks cleaner
            re_swap='outerHTML',
            re_target='#schedule-section',
            context=template_context,
        )

    def _admin_tournament_update(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        action: FormAction,
        tournament_id: int | None,
    ) -> Template | Redirect:
        web_context = TournamentAdminWebContext(request, tournament_id=tournament_id)
        event = web_context.get_admin_event()
        stored_tournament, errors = self._admin_get_validated_tournament_data(
            action, web_context, data
        )
        if errors:
            template_context = self._prepare_tournament_modal_data(
                action, web_context, data, errors=errors
            )
            return self._admin_event_tournaments_render(
                web_context=web_context,
                template_context=template_context,
            )

        if message := plugin_manager.hook_for_event(event, 'signal_tournament_set')(
            event=event, stored_tournament=stored_tournament
        ):
            Message.warning(request, message)

        with EventDatabase(event.uniq_id, write=True) as database:
            if action == FormAction.UPDATE:
                tournament = web_context.get_admin_tournament()
                if tournament.rounds < stored_tournament.rounds:
                    database.delete_stored_pairings_after_round(
                        tournament.id, tournament.rounds
                    )
                    for tournament_player in tournament.tournament_players:
                        if not tournament_player.pairings_by_round[
                            tournament.rounds
                        ].zero_point_bye:
                            continue
                        for round_ in range(
                            tournament.rounds + 1, stored_tournament.rounds + 1
                        ):
                            database.add_stored_pairing(
                                StoredPairing(
                                    tournament_id=tournament.id,
                                    player_id=tournament_player.id,
                                    round_=round_,
                                    result=Result.ZERO_POINT_BYE.value,
                                    board_id=None,
                                )
                            )

                database.update_stored_tournament(stored_tournament)
                assert stored_tournament.id is not None
                database.reseed_tie_breaks_on_pairing_change(
                    stored_tournament.id,
                    tournament.stored_tournament.pairing,
                    stored_tournament.pairing,
                )
                self._apply_rule_set_tie_breaks(database, event, stored_tournament)
                success_message = _(
                    'Tournament [{tournament}] has been updated.'
                ).format(tournament=stored_tournament.name)
            else:
                stored_tournament.id = database.add_stored_tournament(stored_tournament)
                tournament = Tournament(event, stored_tournament)
                if action == FormAction.CLONE:
                    base_tournament = web_context.get_admin_tournament()
                    assert tournament.id is not None
                    database.delete_all_tournament_stored_tie_breaks(tournament.id)
                    for tie_break in base_tournament.tie_breaks_with_invalid:
                        stored_tie_break = tie_break.to_stored_value()
                        stored_tie_break.tournament_id = tournament.id
                        database.add_stored_tie_break(stored_tie_break)
                    for (
                        base_group
                    ) in base_tournament.stored_tournament.stored_prize_groups:
                        group_id = database.add_stored_prize_group(
                            StoredPrizeGroup(
                                id=None,
                                tournament_id=tournament.id,
                                name=base_group.name,
                            )
                        )
                        for base_category in base_group.stored_prize_categories:
                            category_id = database.add_stored_prize_category(
                                StoredPrizeCategory(
                                    id=None,
                                    prize_group_id=group_id,
                                    name=base_category.name,
                                    prize_sharing=base_category.prize_sharing,
                                    sharing_threshold=base_category.sharing_threshold,
                                    is_main=base_category.is_main,
                                    index=base_category.index,
                                )
                            )
                            for base_criterion in base_category.stored_prize_criteria:
                                database.add_stored_prize_criterion(
                                    StoredPrizeCriterion(
                                        id=None,
                                        prize_category_id=category_id,
                                        type=base_criterion.type,
                                        options=base_criterion.options,
                                    )
                                )
                            for base_prize in base_category.stored_prizes:
                                database.add_stored_prize(
                                    StoredPrize(
                                        id=None,
                                        prize_category_id=category_id,
                                        type=base_prize.type,
                                        value=base_prize.value,
                                        description=base_prize.description,
                                    )
                                )
                self._apply_rule_set_tie_breaks(database, event, stored_tournament)
                if 'add_screens' in data:
                    timer_id: int | None = None
                    if len(event.timers_by_id) == 1:
                        timer_id = list(event.timers_by_id.keys())[0]
                    for screen_type in ScreenTypeManager(event).objects():
                        # Default screens are the per-tournament (set-based)
                        # types available for the event.
                        if not screen_type.has_screen_sets:
                            continue
                        if not screen_type.supports_event_type(event.event_type):
                            continue
                        type_fields = screen_type.create_form_data(event)
                        columns = type_fields.pop('columns', 1)
                        stored_screen: StoredScreen = database.add_stored_screen(
                            StoredScreen(
                                id=None,
                                uniq_id=event.get_unused_screen_uniq_id(
                                    base_uniq_id=Utils.name_to_uniq_id(
                                        f'{tournament.name}-{screen_type.value}'
                                    )
                                ),
                                type=screen_type.value,
                                public=True,
                                name=f'{screen_type.name} ({tournament.name})',
                                columns=columns,
                                font_size=None,
                                menu_text=None,
                                timer_id=timer_id,
                                message_default=True,
                                message_text=None,
                                **type_fields,
                            )
                        )
                        assert stored_screen.id is not None
                        database.add_stored_screen_set(stored_screen.id, tournament.id)
                    success_message = _(
                        'Tournament [{tournament}] has been created '
                        'and default screens have been added.'
                    ).format(tournament=tournament.name)
                else:
                    success_message = _(
                        'Tournament [{tournament}] has been created.'
                    ).format(tournament=tournament.name)

                tournament_id = tournament.id

        redirect_to = WebContext.form_data_to_str(data, 'redirect_to')
        if redirect_to:
            return Redirect(redirect_to, status_code=303)
        web_context = TournamentAdminWebContext(
            request, tournament_id, reload_event=True
        )
        if action == FormAction.CREATE:
            tournament = web_context.get_admin_tournament()
            return self._admin_base_event_render(
                web_context.template_context
                | self._tie_breaks_modal_context(
                    tournament, success_message=success_message
                )
            )
        Message.success(request, success_message)
        return self._admin_event_tournaments_render(web_context)

    @post(
        path='/tournament-create/{event_uniq_id:str}',
        name='admin-tournament-create',
        guards=[ActionGuard(AuthAction.ADD_TOURNAMENTS)],
    )
    async def htmx_admin_tournament_create(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template | Redirect:
        return self._admin_tournament_update(
            request,
            action=FormAction.CREATE,
            tournament_id=None,
            data=data,
        )

    @post(
        path='/tournament-clone/{event_uniq_id:str}/{tournament_id:int}',
        name='admin-tournament-clone',
        guards=[ActionGuard(AuthAction.ADD_TOURNAMENTS)],
    )
    async def htmx_admin_tournament_clone(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        tournament_id: FromPath[int],
    ) -> Template | Redirect:
        return self._admin_tournament_update(
            request,
            action=FormAction.CLONE,
            tournament_id=tournament_id,
            data=data,
        )

    @patch(
        path='/tournament-update/{event_uniq_id:str}/{tournament_id:int}',
        name='admin-tournament-update',
        guards=[TournamentActionGuard(AuthAction.UPDATE_TOURNAMENTS)],
    )
    async def htmx_admin_tournament_update(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        tournament_id: FromPath[int],
    ) -> Template | Redirect:
        return self._admin_tournament_update(
            request,
            action=FormAction.UPDATE,
            tournament_id=tournament_id,
            data=data,
        )

    @get(
        path='/tournament-delete-modal/{event_uniq_id:str}/{tournament_id:int}',
        name='admin-tournament-delete-modal',
    )
    async def htmx_admin_tournament_delete_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int | None],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        tournament = web_context.get_admin_tournament()
        referencing_championships = [
            ChampionshipLoader().load_championship(championship_id)
            for championship_id in ChampionshipLoader.championship_ids_referencing(
                web_context.get_admin_event().uniq_id, tournament.id
            )
        ]
        return self._admin_base_event_render(
            web_context.template_context
            | {
                'modal': 'tournament-delete',
                'referencing_championships': referencing_championships,
            }
        )

    @delete(
        path='/tournament-delete/{event_uniq_id:str}/{tournament_id:int}',
        name='admin-tournament-delete',
        guards=[ActionGuard(AuthAction.DELETE_TOURNAMENTS)],
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_tournament_delete(
        self,
        request: HTMXRequest,
        event_uniq_id: FromPath[str],
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        with EventDatabase(event_uniq_id, True) as database:
            database.delete_stored_tournament(tournament_id)
        Message.success(
            request,
            _('Tournament [{tournament}] has been deleted.').format(
                tournament=web_context.get_admin_tournament().name
            ),
        )

        web_context = TournamentAdminWebContext(request, reload_event=True)
        return self._admin_event_tournaments_render(web_context)

    @patch(
        path='/tournament-reorder/{event_uniq_id:str}',
        name='admin-tournament-reorder',
        guards=[ActionGuard(AuthAction.ADD_TOURNAMENTS)],
    )
    async def htmx_admin_tournament_reorder(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, list[int]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = TournamentAdminWebContext(request)
        sorted_tournament_ids = data['item']
        with EventDatabase(web_context.get_admin_event().uniq_id, True) as database:
            for tournament in web_context.get_admin_event().tournaments_by_id.values():
                if tournament.id not in sorted_tournament_ids:
                    raise ValueError(f'Missing tournament id: {tournament.id}')
                index = sorted_tournament_ids.index(tournament.id)
                if index != tournament.index:
                    tournament.stored_tournament.index = index
                    database.update_stored_tournament(tournament.stored_tournament)
        web_context = TournamentAdminWebContext(request, reload_event=True)
        return self._admin_event_tournaments_render(web_context)

    # -------------------------------------------------------------------------
    # Tournament import/export
    # -------------------------------------------------------------------------

    @get(
        path='/tournament-export/data-loss-modal/{event_uniq_id:str}/{tournament_id:int}/{exporter_id:str}',
        name='tournament-export-data-loss-modal',
    )
    async def htmx_tournament_export_loss_warning_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        exporter_id: FromPath[str],
    ) -> Template:
        web_context = TournamentAdminWebContext(
            request, tournament_id, exporter_id=exporter_id
        )
        return self._admin_base_event_render(
            web_context.template_context | {'modal': 'tournament-export-data-loss'}
        )

    @get(
        path='/tournament-export/{event_uniq_id:str}/{tournament_id:int}/{exporter_id:str}',
        name='admin-tournament-export',
    )
    async def admin_tournament_export(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        exporter_id: FromPath[str],
    ) -> File | Template:
        web_context = TournamentAdminWebContext(
            request, tournament_id, exporter_id=exporter_id
        )
        tournament = web_context.get_admin_tournament()
        exporter = web_context.get_admin_exporter()

        temp_file = NamedTemporaryFile(
            delete=False,
            mode='wb' if exporter.is_binary_file else 'w',
            suffix=f'.{exporter.file_extension}',
            encoding=exporter.file_encoding,
        )
        try:
            with temp_file:
                exporter.dump_to_file(temp_file, tournament)
            return File(
                path=temp_file.name,
                filename=f'{exporter.file_name(tournament)}.{exporter.file_extension}',
            )
        except Exception as exception:
            temp_file.close()
            logger.exception(
                'Error when exporting tournament [%s] using exporter [%s]:\n%s',
                tournament.name,
                exporter.id,
                exception,
            )
            Message.error(
                request, _('An error occurred. Consult the logs for more details.')
            )
            return self.render_messages(request)

    @staticmethod
    def _tournament_import_modal_context(
        event: Event,
        importer_id: str,
        tournament: Tournament | None = None,
        data: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        importer = TournamentImporterManager(event).get_object(importer_id)
        default_data = WebContext.values_dict_to_form_data(
            {
                option.id: option.get_default_value(tournament)
                for option in importer.default_options()
            }
        )
        context: dict[str, Any] = {
            'data': default_data | (data or {}),
            'importer': importer,
            'modal': 'tournament-import',
            'errors': errors or {},
        }
        for option in importer.default_options():
            context |= option.template_context
        return context

    @get(
        path=[
            '/tournament-import-modal/{event_uniq_id:str}/{importer_id:str}',
            '/tournament-import-modal/{event_uniq_id:str}/{tournament_id:int}/{importer_id:str}',
        ],
        name='admin-tournament-import-modal',
    )
    async def htmx_admin_tournament_import_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int | None],
        importer_id: FromPath[str],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        event = web_context.get_admin_event()
        template_context = self._tournament_import_modal_context(
            event, importer_id, web_context.admin_tournament
        )
        return self._admin_base_event_render(
            web_context.template_context | template_context
        )

    @post(
        path=[
            '/tournament-import/{event_uniq_id:str}/{importer_id:str}',
            '/tournament-import/{event_uniq_id:str}/{tournament_id:int}/{importer_id:str}',
        ],
        name='admin-tournament-import',
        guards=[ActionGuard(AuthAction.ADD_TOURNAMENTS)],
    )
    async def admin_tournament_import(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, Any], Body(media_type=RequestEncodingType.MULTI_PART)
        ],
        tournament_id: FromPath[int | None],
        importer_id: FromPath[str],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        if web_context.admin_tournament and web_context.admin_tournament.started:
            raise ClientException('Import only possible before the tournament starts.')
        errors: dict[str, str] = {}
        event = web_context.get_admin_event()
        normalized_data = await WebContext.normalize_multipart_data(data)
        importer_type = TournamentImporterManager(event).get_type(importer_id)
        importer_options: list[TournamentImporterOption] = []
        for importer_option in importer_type().default_options():
            value = WebContext.form_data_to_value(
                normalized_data, importer_option.id, importer_option.type
            )
            importer_options.append(type(importer_option)(value))
        importer = importer_type(importer_options)
        try:
            importer.validate_options(event)
            tournament_id = importer.load_tournament(
                event, web_context.admin_tournament
            )
            web_context = TournamentAdminWebContext(
                request, tournament_id, reload_event=True
            )
            Message.success(
                request,
                _('Tournament [{tournament}] successfully imported.').format(
                    tournament=web_context.get_admin_tournament().name
                ),
            )
            return self._admin_event_tournaments_render(web_context)
        except OptionError as error:
            errors[error.option.id] = str(error)
        except ImporterError as error:
            errors['alert'] = str(error)
        except SharlyChessException as error:
            logger.exception(f'Tournament importer [{importer.id}] error: {error}')
            errors['alert'] = _('An error occurred. Consult the logs for more details.')
        finally:
            importer.on_import_finished()
        template_context = self._tournament_import_modal_context(
            event,
            importer_id,
            web_context.admin_tournament,
            data=normalized_data,
            errors=errors,
        )
        return self._admin_base_event_render(
            web_context.template_context | template_context
        )

    @post(
        path=[
            '/tournament-import/check-trf/{event_uniq_id:str}',
            '/tournament-import/check-trf/{event_uniq_id:str}/{tournament_id:int}',
        ],
        name='tournament-import-check-trf',
        guards=[ActionGuard(AuthAction.ADD_TOURNAMENTS)],
    )
    async def htmx_tournament_import_check_trf(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, Any], Body(media_type=RequestEncodingType.MULTI_PART)
        ],
        tournament_id: FromPath[int | None],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        event = web_context.get_admin_event()
        tournament = web_context.admin_tournament
        normalized_data = await WebContext.normalize_multipart_data(data)
        file_path = WebContext.form_data_to_path(normalized_data, 'file')
        importer = TrfTournamentImporter([FileOption(file_path)])
        message: str | None = None
        message_type = 'error'
        try:
            importer.validate_options(event)
            stored_tournament, stored_players = importer.load_stored_tournament(
                event, getattr(tournament, 'stored_tournament', None)
            )
            importer.check_players_unicity(stored_players)
            importer.check_pairing_inconsistencies(stored_tournament)
            features = importer.get_not_importable_features(event)
            if features:
                message_type = 'warning'
                message = _("The following features won't be imported:")
                feature_list = ''.join(f'<li>{feature}</li>' for feature in features)
                message += f'<ul class="mb-0">{feature_list}</ul>'

        except (OptionError, ImporterError) as error:
            message = str(error)
        except Exception as error:
            logger.exception(f'Tournament importer [{importer.id}] error: {error}')
            message = _('An error occurred. Consult the logs for more details.')
        finally:
            importer.on_import_finished()
        return HTMXTemplate(
            template_name='/common/alert.html' if message else '/common/empty.html',
            re_swap='innerHTML',
            re_target='#alert-message',
            context={
                'message': message,
                'type': message_type,
                'hide_remove_button': True,
            },
        )

    # -------------------------------------------------------------------------
    # Tie breaks
    # -------------------------------------------------------------------------

    @classmethod
    def _validate_tie_break_form_data(
        cls,
        web_context: TournamentAdminWebContext,
        action: FormAction,
        data: dict[str, str],
    ) -> dict[str, str]:
        event = web_context.get_admin_event()
        tournament = web_context.get_admin_tournament()
        errors: dict[str, str] = {}
        field = 'type'
        tie_break_id = data.get(field, '')
        if not tie_break_id:
            return {field: _('A value is expected.')}
        try:
            TieBreakManager(event).get_type(tie_break_id)
        except KeyError:
            return {field: f'Unknown tie-break [{tie_break_id}].'}
        tie_break = cls._tie_break_from_data(event, data)
        advancement = tournament.tie_break_config_purpose == TieBreakPurpose.ADVANCEMENT
        if advancement and not tie_break.usable_as_knockout_advancement:
            errors[field] = _(
                'This tie-break cannot decide which team advances in a knock-out.'
            )
        elif not advancement and (
            message := tournament.tie_break_invalid_message(tie_break)
        ):
            errors[field] = message
        else:
            existing_tie_breaks = [
                tie_break_
                for object_id, tie_break_ in tournament.tie_breaks_by_id.items()
                if (
                    action != FormAction.UPDATE
                    or object_id != web_context.admin_tie_break_id
                )
            ]
            if tie_break in existing_tie_breaks and not tie_break.allow_multiple:
                has_modifiers = any(
                    option.include_in_equals for option in tie_break.default_options()
                )
                errors[field] = (
                    _('This tie-break is already used with the same modifiers.')
                    if has_modifiers
                    else _('This tie-break is already used.')
                )
        try:
            tie_break.validate_options()
        except OptionError as error:
            errors[error.option.id] = str(error)
        return errors

    @staticmethod
    def _tie_break_from_data(event: Event, data: dict[str, str]) -> TieBreak:
        tie_break_type = TieBreakManager(event).get_type(data['type'])
        options = []
        for option in tie_break_type().default_options():
            value = WebContext.form_data_to_value(data, option.id, option.type)
            options.append(type(option)(value))
        return tie_break_type(options)

    @staticmethod
    def _tie_break_form_modal_context(
        web_context: TournamentAdminWebContext,
        data: dict[str, str],
        action: FormAction,
        errors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        event = web_context.get_admin_event()
        tournament = web_context.get_admin_tournament()
        request = web_context.request
        default_data = {
            option.id: WebContext.value_to_form_data(option.default_value)
            for option in TieBreakOptionManager(event).objects()
        } | {'type': ''}

        advancement = tournament.tie_break_config_purpose == TieBreakPurpose.ADVANCEMENT
        tie_break_select_options: dict[str, dict[str, SelectOption]] = defaultdict(dict)
        for tie_break in TieBreakManager(event).objects():
            if advancement:
                # A knock-out configures the tie-breaks that decide who
                # advances from a level match. Team advancement compares
                # teams (team tie-breaks); individual advancement compares
                # players. The manual play-off marker suits either.
                if not tie_break.usable_as_knockout_advancement:
                    continue
                if not tie_break.is_manual:
                    # Team advancement compares teams, so any tie-break with
                    # a team-mode value qualifies (the team-specific ones and
                    # the individual ones usable in team mode). Individual
                    # advancement excludes the team-only tie-breaks.
                    if event.is_team_event and not tie_break.supports_team_mode:
                        continue
                    if not event.is_team_event and tie_break.is_team_tiebreak:
                        continue
            else:
                if not tie_break.is_compatible_with(tournament.pairing_system):
                    continue
                # Team events: only tie-breaks that produce a per-team value
                # (FIDE MTB26 "both" + team-only groups). Individual events:
                # everything except team-only.
                if event.is_team_event:
                    if not tie_break.supports_team_mode:
                        continue
                else:
                    if tie_break.is_team_tiebreak:
                        continue
            # Picker shows the family acronym (e.g. ``ESB``) instead
            # of the configured variant (``EMMSB``) — the variant is a
            # tie-break option, not a separate type. Same idea for the
            # tooltip: explain the family, not the default variant.
            tie_break_select_options[tie_break.category.name][tie_break.id] = (
                SelectOption(
                    f'{tie_break.picker_acronym} - {tie_break.name}',
                    tie_break.picker_help_text,
                )
            )
        return {
            'modal': 'tie_break_form',
            'action': action,
            'tie_break_select_options': {'': '-'} | tie_break_select_options,
            'tie_break_options': TieBreakOptionManager(event).objects(),
            'containers_by_type': {
                tie_break.id: [
                    option.container_id for option in tie_break.default_options()
                ]
                for tie_break in TieBreakManager(event).objects()
            }
            | {'': []},
            'add_other_active': SessionTieBreakAddOtherActive(request).get(),
            'data': default_data | data,
            'errors': errors or {},
        }

    @staticmethod
    def _tie_breaks_modal_context(
        tournament: Tournament,
        success_message: str | None = None,
        save_as_error: str | None = None,
        save_as_name_value: str | None = None,
    ) -> dict[str, Any]:
        """Build the additional context for the tie-breaks modal: the picker
        of tie-break sets and the user-set list for the save-as button."""
        if tournament.tie_break_config_purpose == TieBreakPurpose.ADVANCEMENT:
            # A knock-out's advancement tie-breaks are a short, hand-picked
            # list; the standings-oriented preset sets do not apply.
            return {
                'modal': 'tie_breaks',
                'tie_break_set_select_options': {},
                'tie_break_set_custom_names': [],
                'tie_break_set_save_as_error': None,
                'tie_break_set_save_as_name_value': '',
            } | ({'success_message': success_message} if success_message else {})
        grouped = available_tie_break_sets(tournament)

        select_options: dict[str, dict[str, SelectOption]] = {}
        for source in TieBreakSetSource:
            sets = grouped.get(source, [])
            if not sets:
                continue
            options: dict[str, SelectOption] = {}
            for tie_break_set in sets:
                options[f'{source.value}|{tie_break_set.key}'] = SelectOption(
                    name=tie_break_set.name,
                    tooltip=(
                        tie_break_set.disabled_reason
                        if tie_break_set.disabled
                        else tie_break_set.tooltip_message(tournament.event)
                    ),
                    disabled=tie_break_set.disabled,
                    subtitle=' - '.join(tie_break_set.tie_break_acronyms),
                )
            select_options[source.label] = options

        existing_custom_set_names = [
            tie_break_set.name
            for tie_break_set in grouped.get(TieBreakSetSource.CUSTOM, [])
        ]

        context: dict[str, Any] = {
            'modal': 'tie_breaks',
            'tie_break_set_select_options': select_options,
            'tie_break_set_custom_names': existing_custom_set_names,
            'tie_break_set_save_as_error': save_as_error,
            'tie_break_set_save_as_name_value': save_as_name_value or '',
        }
        if success_message:
            context['success_message'] = success_message
        return context

    @post(
        path=(
            '/tournaments/apply-tie-break-set/{event_uniq_id:str}/{tournament_id:int}'
        ),
        name='admin-apply-tie-break-set',
        guards=[TournamentActionGuard(AuthAction.UPDATE_TOURNAMENTS)],
    )
    async def htmx_admin_apply_tie_break_set(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        data: Annotated[
            dict[str, str | list[str]] | None,
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ] = None,
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        tournament = web_context.get_admin_tournament()
        raw = (data or {}).get('tie_break_set', '')
        if isinstance(raw, list):
            raw = raw[0] if raw else ''
        selection = raw
        if '|' not in selection:
            raise ClientException(f'Invalid tie-break set selection [{selection}].')
        source, key = selection.split('|', 1)
        tie_break_set = get_tie_break_set(tournament, source, key)
        if tie_break_set is None:
            raise ClientException(
                f'Tie-break set [{key}] not found for source [{source}].'
            )
        if tie_break_set.disabled:
            raise ClientException(
                tie_break_set.disabled_reason or 'Tie-break set is disabled.'
            )
        # A set is the whole ranking order, so it replaces what is there
        # rather than adding to it — a tournament always holds at least
        # the points, which would otherwise be listed twice.
        assert tournament.id is not None
        with EventDatabase(tournament.event.uniq_id, write=True) as database:
            database.delete_all_tournament_stored_tie_breaks(tournament.id)
        tournament.tie_breaks_by_id.clear()
        for stored_tb in tie_break_set.stored_tie_breaks:
            tie_break = instantiate_tie_break(stored_tb, tournament.event)
            if tie_break is not None:
                tournament.add_tie_break(tie_break)
        return self._admin_base_event_render(
            web_context.template_context | self._tie_breaks_modal_context(tournament)
        )

    @post(
        path=(
            '/tournaments/save-tie-break-set/{event_uniq_id:str}/{tournament_id:int}'
        ),
        name='admin-save-tie-break-set',
        guards=[TournamentActionGuard(AuthAction.UPDATE_TOURNAMENTS)],
    )
    async def htmx_admin_save_tie_break_set(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        tournament = web_context.get_admin_tournament()
        name = (WebContext.form_data_to_str(data, 'name') or '').strip()
        overwrite = WebContext.form_data_to_bool(data, 'overwrite')
        error: str | None = None
        if not name:
            error = _('Please choose a name for the set.')
        elif tournament.tie_breaks_invalid_messages:
            error = _(
                'The tournament has invalid tie-breaks; '
                'please fix them before saving as a set.'
            )
        elif not tournament.tie_breaks_by_id:
            error = _('The tournament has no tie-breaks to save.')
        success_message: str | None = None
        if not error:
            pairing_system_id = tournament.pairing_system.id
            stored_tie_breaks = [
                stored_tie_break_to_dict(tb.to_stored_value())
                for tb in tournament.tie_breaks_by_id.values()
            ]
            with ConfigDatabase(True) as database:
                existing = database.find_stored_tie_break_set_by_name(
                    pairing_system_id, name
                )
                if existing is not None and not overwrite:
                    error = _(
                        'A set named [{name}] already exists. '
                        'Tick the overwrite option to replace it.'
                    ).format(name=name)
                elif existing is not None:
                    existing.stored_tie_breaks = stored_tie_breaks
                    database.update_stored_tie_break_set(existing)
                    success_message = _('Set [{name}] has been updated.').format(
                        name=name
                    )
                else:
                    database.add_stored_tie_break_set(
                        StoredTieBreakSet(
                            id=None,
                            name=name,
                            pairing_system_id=pairing_system_id,
                            stored_tie_breaks=stored_tie_breaks,
                        )
                    )
                    success_message = _('Set [{name}] has been saved.').format(
                        name=name
                    )
            SharlyChessConfig().load_and_set_env()
        return self._admin_base_event_render(
            web_context.template_context
            | self._tie_breaks_modal_context(
                tournament,
                success_message=success_message,
                save_as_error=error,
                save_as_name_value=name if error else '',
            )
        )

    @post(
        path='/tournaments/tie-break/create/{event_uniq_id:str}/{tournament_id:int}',
        name='admin-tie-break-create',
        guards=[TournamentActionGuard(AuthAction.UPDATE_TOURNAMENTS)],
    )
    async def htmx_admin_tie_break_create(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        event = web_context.get_admin_event()
        tournament = web_context.get_admin_tournament()
        add_other = WebContext.resolve_add_other(
            data, SessionTieBreakAddOtherActive(request)
        )
        if errors := self._validate_tie_break_form_data(
            web_context, FormAction.CREATE, data
        ):
            return self._admin_base_event_render(
                web_context.template_context
                | self._tie_break_form_modal_context(
                    web_context, data, FormAction.CREATE, errors
                )
            )
        tie_break = self._tie_break_from_data(event, data)
        tournament.add_tie_break(tie_break)
        if add_other:
            template_context = self._tie_break_form_modal_context(
                web_context, {}, FormAction.CREATE, errors
            ) | {'previous_tie_break': tie_break}
        else:
            template_context = self._tie_breaks_modal_context(tournament)
        return self._admin_base_event_render(
            web_context.template_context | template_context
        )

    @post(
        path=(
            '/tournaments/tie-break/duplicate/{event_uniq_id:str}'
            '/{tournament_id:int}/{tie_break_id:int}'
        ),
        name='admin-tie-break-duplicate',
        guards=[TournamentActionGuard(AuthAction.UPDATE_TOURNAMENTS)],
    )
    async def htmx_admin_tie_break_duplicate(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        tie_break_id: FromPath[int],
    ) -> Template:
        web_context = TournamentAdminWebContext(
            request, tournament_id, tie_break_id=tie_break_id
        )
        tournament = web_context.get_admin_tournament()
        tie_break = web_context.get_admin_tie_break()
        if not tie_break.allow_multiple:
            raise ValidationException(
                f"Tie-breaks of type [{tie_break.id}] can't be duplicated."
            )
        tournament.add_tie_break(tie_break)
        return self._admin_base_event_render(
            web_context.template_context | self._tie_breaks_modal_context(tournament)
        )

    @patch(
        path=(
            '/tournaments/tie-break/update/{event_uniq_id:str}'
            '/{tournament_id:int}/{tie_break_id:int}'
        ),
        name='admin-tie-break-update',
        guards=[TournamentActionGuard(AuthAction.UPDATE_TOURNAMENTS)],
    )
    async def htmx_admin_tie_break_update(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        tournament_id: FromPath[int],
        tie_break_id: FromPath[int],
    ) -> Template:
        web_context = TournamentAdminWebContext(
            request,
            tournament_id,
            tie_break_id=tie_break_id,
        )
        event = web_context.get_admin_event()
        tournament = web_context.get_admin_tournament()
        if errors := self._validate_tie_break_form_data(
            web_context, FormAction.UPDATE, data
        ):
            return self._admin_base_event_render(
                web_context.template_context
                | self._tie_break_form_modal_context(
                    web_context, data, FormAction.UPDATE, errors
                )
            )
        tie_break = self._tie_break_from_data(event, data)
        tournament.update_tie_break(tie_break_id, tie_break)
        return self._admin_base_event_render(
            web_context.template_context | self._tie_breaks_modal_context(tournament)
        )

    @delete(
        path=(
            '/tournaments/tie-break/delete/{event_uniq_id:str}'
            '/{tournament_id:int}/{tie_break_id:int}'
        ),
        name='admin-tie-break-delete',
        guards=[TournamentActionGuard(AuthAction.UPDATE_TOURNAMENTS)],
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_tie_break_delete(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        tie_break_id: FromPath[int],
    ) -> Template:
        web_context = TournamentAdminWebContext(
            request,
            tournament_id,
            tie_break_id=tie_break_id,
        )
        tournament = web_context.get_admin_tournament()
        tournament.delete_tie_break(tie_break_id)
        return self._admin_base_event_render(
            web_context.template_context | self._tie_breaks_modal_context(tournament)
        )

    @patch(
        path='/tournament-reorder-tie-breaks/{event_uniq_id:str}/{tournament_id:int}',
        name='admin-tournament-reorder-tie-breaks',
        guards=[TournamentActionGuard(AuthAction.UPDATE_TOURNAMENTS)],
    )
    async def htmx_admin_tournament_reorder_tie_breaks(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        data: Annotated[
            dict[str, list[int]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        tournament = web_context.get_admin_tournament()
        tournament.reorder_tie_breaks(data.get('tie_break_ids', []))
        return self._admin_base_event_render(
            web_context.template_context | self._tie_breaks_modal_context(tournament)
        )

    @get(
        path='/tournaments/tie-breaks-modal/{event_uniq_id:str}/{tournament_id:int}',
        name='admin-tie-breaks-modal',
    )
    async def htmx_admin_tie_breaks_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        tournament = web_context.get_admin_tournament()
        return self._admin_base_event_render(
            web_context.template_context | self._tie_breaks_modal_context(tournament)
        )

    @staticmethod
    def _tie_break_sets_modal_context(event: 'Event') -> dict[str, Any]:
        """Context for the custom TB-set management modal: lists all
        custom sets, grouped by the pairing system they belong to.

        The systems on offer depend on the event — a team event has its
        own — while the sets are global to the installation, so a set may
        name a system this event never offers. Those are grouped under
        the stored id rather than left to fail: the modal lists every
        set, whichever event it is opened from.
        """
        system_name_by_id = PairingSystemManager(event).options()
        custom_sets_by_pairing_system_name: dict[str, list[TieBreakSet]] = {
            system_name: [] for system_name in system_name_by_id.values()
        }
        for tie_break_set in SharlyChessConfig().custom_tie_break_sets:
            from data.tie_breaks.sets import fill_acronyms

            fill_acronyms(tie_break_set, event=None)
            system_name = system_name_by_id.get(
                tie_break_set.pairing_system_id, tie_break_set.pairing_system_id
            )
            custom_sets_by_pairing_system_name.setdefault(system_name, []).append(
                tie_break_set
            )

        return {
            'modal': 'tie_break_sets',
            'custom_sets_by_pairing_system_name': {
                name: sets
                for name, sets in custom_sets_by_pairing_system_name.items()
                if sets
            },
        }

    @get(
        path=(
            '/tournaments/tie-break-sets-modal/{event_uniq_id:str}/{tournament_id:int}'
        ),
        name='admin-tie-break-sets-modal',
        guards=[TournamentActionGuard(AuthAction.UPDATE_TOURNAMENTS)],
    )
    async def htmx_admin_tie_break_sets_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        return self._admin_base_event_render(
            web_context.template_context
            | self._tie_break_sets_modal_context(web_context.get_admin_event())
        )

    @delete(
        path=(
            '/tournaments/tie-break-set/delete/{event_uniq_id:str}'
            '/{tournament_id:int}/{tie_break_set_id:int}'
        ),
        name='admin-tie-break-set-delete',
        guards=[TournamentActionGuard(AuthAction.UPDATE_TOURNAMENTS)],
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_tie_break_set_delete(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        tie_break_set_id: FromPath[int],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        with ConfigDatabase(True) as database:
            database.delete_stored_tie_break_set(tie_break_set_id)
        SharlyChessConfig().load_and_set_env()
        return self._admin_base_event_render(
            web_context.template_context
            | self._tie_break_sets_modal_context(web_context.get_admin_event())
        )

    @get(
        path='/tournaments/tie-break-modal/create/{event_uniq_id:str}/{tournament_id:int}',
        name='admin-tie-break-create-modal',
    )
    async def htmx_admin_tie_break_create_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        return self._admin_base_event_render(
            web_context.template_context
            | self._tie_break_form_modal_context(web_context, {}, FormAction.CREATE)
        )

    @get(
        path=(
            '/tournaments/tie-break-modal/update/{event_uniq_id:str}'
            '/{tournament_id:int}/{tie_break_id:int}'
        ),
        name='admin-tie-break-update-modal',
    )
    async def htmx_admin_tie_break_update_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        tie_break_id: FromPath[int],
    ) -> Template:
        web_context = TournamentAdminWebContext(
            request, tournament_id, tie_break_id=tie_break_id
        )
        tie_break = web_context.get_admin_tie_break()
        data = {'type': tie_break.id} | {
            option.id: WebContext.value_to_form_data(option.value)
            for option in tie_break.options
        }
        return self._admin_base_event_render(
            web_context.template_context
            | self._tie_break_form_modal_context(web_context, data, FormAction.UPDATE)
        )

    # -------------------------------------------------------------------------
    # Misc
    # -------------------------------------------------------------------------

    @get(
        path=[
            '/random-player/{event_uniq_id:str}',
            '/random-player/{event_uniq_id:str}/{tournament_id:int}',
        ],
        name='admin-random-player',
    )
    async def htmx_random_player(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int | None],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        event = web_context.get_admin_event()
        tournament = web_context.admin_tournament
        if not tournament:
            allowed_tournaments = web_context.client.allowed_tournaments_for_action(
                AuthAction.VIEW_TOURNAMENTS_TAB
            )
            tournament = random.choice(
                [
                    tournament_
                    for tournament_ in allowed_tournaments
                    if tournament_.tournament_players
                ]
            )
        tournament_player: TournamentPlayer | None = None
        if tournament and tournament.tournament_players:
            tournament_player = random.choice(list(tournament.tournament_players))

        board: Board | None = None
        opponent: TournamentPlayer | None = None
        if tournament_player and tournament.started:
            pairing = tournament_player.pairings[tournament.current_round]
            board = pairing.board
            opponent = pairing.opponent

        return HTMXTemplate(
            template_name='admin/tournaments/random_player_modal.html',
            context={
                'random_player': tournament_player,
                'opponent_name': opponent.full_name if opponent else None,
                'tournament': tournament,
                'admin_event': event,
                'board': board,
            },
            re_target='#modal-wrapper',
            trigger_event='modal_opened',
            after='settle',
        )

    @get(
        path='/delete-unpaired-players/{event_uniq_id:str}/{tournament_id:int}',
        name='delete-unpaired-players',
    )
    async def htmx_delete_unpaired_players(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        event = web_context.get_admin_event()
        tournament = web_context.get_admin_tournament()
        if not tournament.started:
            raise ClientException(f'Tournament [{tournament.name}] is not started.')
        players = [
            player
            for player in tournament.tournament_players
            if not player.has_real_pairings
        ]
        with EventDatabase(event.uniq_id, True) as database:
            for player in players:
                database.delete_stored_player(player.id)
        Message.success(
            request,
            ngettext(
                '{count} player deleted.',
                '{count} players deleted.',
                len(players),
            ).format(count=len(players)),
        )
        web_context = TournamentAdminWebContext(
            request, tournament_id, reload_event=True
        )
        return self._admin_event_tournaments_render(web_context)

    @classmethod
    def _player_distribution_modal_context(
        cls, web_context: TournamentAdminWebContext
    ) -> dict[str, Any]:
        request = web_context.request
        event = web_context.get_admin_event()
        session_groups_by_id = SessionDistributeGroupsById(request, event).get()
        groups_by_id: dict[int, list[int]] = {}
        tournament_ids = list(event.tournaments_by_id)
        for group_id, group_tournament_ids in session_groups_by_id.items():
            group = [
                tournament_id
                for tournament_id in group_tournament_ids
                if tournament_id in tournament_ids
            ]
            if len(group) > 1:
                groups_by_id[int(group_id)] = group
        tournament_players = event.tournament_players
        criteria_player_ids_by_tournament_id = {
            tournament.id: [
                player.id
                for player in tournament_players
                if tournament.player_matches_criteria(player)
            ]
            for tournament in event.tournaments
        }
        session_count_by_tournament_id = SessionDistributePlayerCountByTournamentId(
            request, event
        ).get()
        return {
            'modal': 'distribute-players',
            'distribution_type_options': {
                'rating': SelectOption(
                    _('Descending rating'),
                    _(
                        'Distribute the players by descending rating and '
                        'choose the number of players participating in each tournament.'
                    ),
                ),
                'criteria': SelectOption(
                    _('Criteria'),
                    _(
                        'Allocate players to the first tournament '
                        'for which the criteria are met.'
                    ),
                ),
            },
            'groups_by_id': groups_by_id,
            'unselected_tournament_ids': SessionDistributeUnselectedTournaments(
                request, event
            ).get(),
            'player_count_by_tournament_id': {
                int(tournament_id): player_count
                for tournament_id, player_count in session_count_by_tournament_id.items()
                if int(tournament_id) in event.tournaments_by_id
            },
            'criteria_player_ids_by_tournament_id': criteria_player_ids_by_tournament_id,
            'player_ids': list(event.players),
            'data': WebContext.values_dict_to_form_data(
                {
                    'distribution_type': SessionDistributeType(request).get(),
                    'use_balance_groups': SessionDistributeUseBalanceGroups(
                        request
                    ).get(),
                }
            ),
            'errors': {},
        }

    @get(
        path='/distribute-players-modal/{event_uniq_id:str}',
        name='admin-distribute-players-modal',
    )
    async def htmx_admin_distribute_players_modal(
        self,
        request: HTMXRequest,
    ) -> Template:
        web_context = TournamentAdminWebContext(request)
        return self._admin_event_tournaments_render(
            web_context,
            self._player_distribution_modal_context(web_context),
        )

    @staticmethod
    def _move_next_player_to_tournament(
        tournament_players: list[TournamentPlayer],
        tournament: Tournament,
    ) -> bool:
        """Moves the next player of the list to the target tournament, returns True on success, False otherwise."""
        try:
            tournament_player: TournamentPlayer = tournament_players.pop(0)
        except IndexError:
            logger.debug('No more players.')
            return False
        if tournament_player.tournament != tournament:
            logger.debug(
                'Moving player [%s] to tournament [%s]...',
                tournament_player.full_name,
                tournament.name,
            )
            tournament.event.move_player_to_tournament(tournament_player, tournament)
        else:
            logger.debug(
                'Player [%s] already in tournament [%s]...',
                tournament_player.full_name,
                tournament.name,
            )
        return True

    @classmethod
    def _distribute_players_by_rating(
        cls,
        event: Event,
        player_count_by_tournament_id: dict[int, int],
        groups_by_id: dict[str, list[int]],
    ):
        """Distribute the players among the tournaments with the given settings."""
        tournament_players: list[TournamentPlayer] = sorted(
            event.tournament_players,
            key=lambda player: player.starting_rank_sort_key,
        )
        group_id_by_tournament_id = {
            tournament.id: next(
                (
                    group_id
                    for group_id, tournament_ids in groups_by_id.items()
                    if tournament.id in tournament_ids
                ),
                None,
            )
            for tournament in event.sorted_tournaments
        }
        tournament_groups: list[list[Tournament]] = []
        previous_group_id: str | None = None
        for tournament in event.sorted_tournaments:
            group_id = group_id_by_tournament_id[tournament.id]
            if group_id is not None and group_id == previous_group_id:
                tournament_groups[-1].append(tournament)
            else:
                previous_group_id = group_id
                tournament_groups.append([tournament])
        for tournament_group in tournament_groups:
            while tournament_group:
                tournament_group = [
                    tournament
                    for tournament in tournament_group
                    if player_count_by_tournament_id[tournament.id] > 0
                ]
                for tournament in tournament_group:
                    cls._move_next_player_to_tournament(tournament_players, tournament)
                    player_count_by_tournament_id[tournament.id] -= 1

    @post(
        path='/distribute-players/{event_uniq_id:str}',
        name='admin-distribute-players',
    )
    async def htmx_admin_distribute_players(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = TournamentAdminWebContext(request)
        event = web_context.get_admin_event()
        flat_data = WebContext.flatten_list_data(data)

        distribution_type = (
            WebContext.form_data_to_str(flat_data, 'distribution_type') or ''
        )
        groups_by_id = json.loads(flat_data.get('groups_by_id', '{}'))
        tournament_ids = WebContext.form_data_to_list_int(flat_data, 'tournament_ids')
        use_balance_groups = WebContext.form_data_to_bool(
            flat_data, 'use_balance_groups'
        )
        user_player_count_by_tournament_id: dict[str, str] = {}
        for tournament in event.tournaments:
            count = WebContext.form_data_to_int(
                flat_data, f'user_player_count_{tournament.id}'
            )
            if count is not None:
                user_player_count_by_tournament_id[str(tournament.id)] = str(count)

        SessionDistributeType(request).set(distribution_type)
        SessionDistributeGroupsById(request, event).set(groups_by_id)
        SessionDistributeUseBalanceGroups(request).set(use_balance_groups)
        SessionDistributeUnselectedTournaments(request, event).set(
            [
                tournament_id
                for tournament_id in event.tournaments_by_id
                if tournament_id not in tournament_ids
            ]
        )
        SessionDistributePlayerCountByTournamentId(request, event).set(
            user_player_count_by_tournament_id
        )

        if distribution_type == 'rating':
            player_count_by_tournament_id = {
                tournament.id: WebContext.form_data_to_int(
                    flat_data, f'player_count_{tournament.id}'
                )
                or 0
                for tournament in event.sorted_tournaments
            }
            self._distribute_players_by_rating(
                event,
                player_count_by_tournament_id,
                groups_by_id if use_balance_groups else {},
            )
        else:
            tournament_players = event.tournament_players
            matched_player_ids: list[int] = []
            for tournament in event.sorted_tournaments:
                if tournament.id not in tournament_ids:
                    continue
                for player in tournament_players:
                    if player.id in matched_player_ids:
                        continue
                    if tournament.player_matches_criteria(player):
                        matched_player_ids.append(player.id)
                        if player.tournament.id != tournament.id:
                            event.move_player_to_tournament(player, tournament)
        Message.success(
            request, _('Players successfully distributed among the tournaments.')
        )
        return self._admin_event_tournaments_render(web_context)

import shutil
from collections import defaultdict
from copy import copy
from datetime import date
from logging import Logger
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Any, Literal

from litestar import delete, get, patch, post
from litestar.enums import RequestEncodingType
from litestar.exceptions import ClientException, NotFoundException
from litestar.params import Body, FromPath, FromQuery
from litestar.plugins.htmx import ClientRedirect, HTMXRequest, HTMXTemplate, Reswap
from litestar.response import File, Redirect, Template
from litestar.status_codes import HTTP_200_OK

from common import (
    BASE_DIR,
    check_rgb_str,
    is_http_url,
    is_valid_email,
)
from common.exception import FormError, SharlyChessException
from common.i18n import (
    _,
    locales,
)
from common.i18n.utils import by, locale_localized_name
from common.logger import get_logger
from common.network import NetworkMonitor
from common.sharly_chess_config import SharlyChessConfig
from data.access_levels.actions import AuthAction
from data.board import PlayerRatingType
from data.event import Event
from data.input_output import OnlineDataSourceManager
from data.event_metadata import EventMetadata
from data.championship.championship_loader import (
    ChampionshipArchiveLoader,
    ChampionshipLoader,
)
from data.loader import ArchiveLoader, EventLoader
from data.player_categories import (
    SELECTABLE_JUNIOR_CATEGORIES,
    SELECTABLE_SENIOR_CATEGORIES,
    PlayerCategory,
)
from data.tag import DEFAULT_TAG_COLOR, default_tag_sets
from database.sqlite.config.config_database import ConfigDatabase
from database.sqlite.config.config_store import (
    StoredConfig,
    StoredPlayerCategorySet,
    StoredPlugin,
    StoredTag,
)
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import StoredEvent
from database.sqlite.local_source_database import (
    LocalSourceDatabase,
    LocalSourceDatabaseManager,
    OutdatedActionManager,
    OutdatedDelayManager,
)
from database.sqlite.local_source_database.actions import (
    NotifOutdatedAction,
    OutdatedAction,
)
from database.sqlite.local_source_database.delays import (
    DisabledOutdatedDelay,
    OutdatedDelay,
)
from database.sqlite.sqlite_database import SQLiteDatabase
from plugins.manager import Plugin, plugin_manager
from utils import Utils
from utils.date_time import (
    DateFormatterManager,
    format_date,
    format_date_range,
)
from utils.enum import EventType, Extension, FormAction
from web.controllers.admin.base_admin_controller import (
    AdminWebContext,
    BaseAdminController,
)
from web.controllers.base_controller import WebContext
from web.guards import ActionGuard
from web.messages import Message
from web.session import (
    SessionEventsShowDetails,
    SessionTagsAddOtherActive,
    SessionEventsTags,
    SessionUserAccountId,
    SessionUserAccountPasswordHash,
)
from web.urls import admin_event_url

logger: Logger = get_logger()


class IndexAdminController(BaseAdminController):
    @classmethod
    def _admin_validate_config_update_data(
        cls,
        data: dict[str, str] | None = None,
    ) -> StoredConfig:
        config = SharlyChessConfig()
        if data is None:
            data = {}
        errors: dict[str, str] = {}
        experimental = WebContext.form_data_to_bool(data, 'experimental')
        federation = WebContext.form_data_to_str(data, field := 'federation')
        if federation:
            if federation not in config.federations:
                errors[field] = f'Invalid federation [{federation}].'
                data[field] = ''
                federation = None
        else:
            errors[field] = _('Please choose a federation.')
        locale = WebContext.form_data_to_str(data, field := 'locale')
        if locale and locale not in locales:
            errors[field] = _('Invalid locale [{locale}].').format(locale=locale)
            data[field] = ''
        date_formatter_id = (
            WebContext.form_data_to_str(data, field := 'date_formatter') or ''
        )
        try:
            DateFormatterManager().get_object(date_formatter_id)
        except KeyError:
            errors[field] = f'invalid date formatter [{date_formatter_id}].'
        stored_config = copy(config.stored_config)
        stored_config.force_edit = False
        stored_config.experimental = experimental
        stored_config.federation = federation
        stored_config.locale = locale
        stored_config.date_formatter = date_formatter_id
        stored_config.errors = errors
        return stored_config

    @classmethod
    def _admin_validate_plugins_update_data(
        cls, data: dict[str, str] | None = None
    ) -> list[StoredPlugin]:
        if data is None:
            data = {}
        stored_plugins: list[StoredPlugin] = []
        enabled_plugins = plugin_manager.get_plugins_with_dependencies(
            [
                plugin
                for plugin in plugin_manager.all_plugins
                if WebContext.form_data_to_bool(data, plugin.form_key)
            ]
        )
        for plugin in plugin_manager.all_plugins:
            stored_plugins.append(
                StoredPlugin(
                    name=plugin.id,
                    is_enabled=plugin in enabled_plugins,
                )
            )
        return stored_plugins

    @classmethod
    def admin_shell_context(
        cls,
        web_context: AdminWebContext,
        template_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the full admin-shell context (sidebar nav_tabs, logo, etc.).
        Reused by other controllers that render inside the admin shell."""
        sorted_archives = ArchiveLoader.get_sorted_archives()
        public_only: bool = not web_context.client.can_view_private_events
        events_metadata = EventLoader.get_events_metadata(public_only=public_only)
        if not public_only:
            # Events whose file exists but could not be opened (locked, file sync…)
            # are listed as not accessible rather than silently disappearing.
            events_metadata = (
                events_metadata + EventLoader.inaccessible_events_metadata()
            )
        passed_events = EventLoader.select_events_metadata(events_metadata, 'passed')
        current_events = EventLoader.select_events_metadata(events_metadata, 'current')
        coming_events = EventLoader.select_events_metadata(events_metadata, 'coming')
        lan_events = [
            event
            for event in current_events + coming_events
            if event.are_all_plugins_enabled
        ]
        # The tag filter narrows the event lists only: the home page is a
        # landing page and carries no filter control. Tags deleted since the
        # filter was set are dropped from it.
        all_tags = SharlyChessConfig().tags
        tag_filter = SessionEventsTags(web_context.request).get() & {
            tag.id for tag in all_tags
        }
        # Tabs stay enabled on their unfiltered content, otherwise filtering a
        # tab down to nothing would disable it and bounce the user elsewhere.
        has_passed_events = bool(passed_events)
        has_current_events = bool(current_events)
        has_coming_events = bool(coming_events)

        def _tagged(events: list[EventMetadata]) -> list[EventMetadata]:
            """The events carrying every selected tag."""
            return [event for event in events if tag_filter <= set(event.tag_ids)]

        def _tag_counts(events: list[EventMetadata]) -> dict[int, int]:
            """Per tag, how many events would remain were it added to the
            selection — the number shown on its filter badge, and 0 for the
            ones the badge disables."""
            return {
                tag.id: sum(
                    1 for event in events if tag_filter | {tag.id} <= set(event.tag_ids)
                )
                for tag in all_tags
            }

        passed_tag_counts = _tag_counts(passed_events)
        current_tag_counts = _tag_counts(current_events)
        coming_tag_counts = _tag_counts(coming_events)
        if tag_filter:
            passed_events = _tagged(passed_events)
            current_events = _tagged(current_events)
            coming_events = _tagged(coming_events)
        nav_tabs: dict[str, dict[str, Any]] = {
            'home': {
                'title': _('Home'),
                'template': 'index/home_tab.html',
                'icon_class': 'bi-house-fill',
                'disabled': False,
                'events': sorted(lan_events, key=by('name')),
                'experimental_features_warning': True,
            },
        }
        if web_context.client.can_view_passed_events:
            nav_tabs |= {
                'current_events': {
                    'section_title': _('Events'),
                    'section_create_modal_url': (
                        web_context.request.app.route_reverse(
                            'admin-event-modal', admin_tab='home', action='create'
                        )
                        if web_context.client.can_create_events
                        else None
                    ),
                    'section_create_label': _('Create an event'),
                    'title': _('Current ({num})').format(
                        num=len(current_events) or '-'
                    ),
                    'template': 'index/events_tab.html',
                    'events': current_events,
                    'tag_counts': current_tag_counts,
                    'disabled': not has_current_events,
                    'empty_str': _('No current event carries the selected tags.')
                    if tag_filter
                    else _('No current events.'),
                    'icon_class': 'bi-calendar indented',
                    'page_title': _('Current events'),
                    'divider': True,
                },
                'coming_events': {
                    'title': _('Upcoming ({num})').format(
                        num=len(coming_events) or '-'
                    ),
                    'template': 'index/events_tab.html',
                    'events': coming_events,
                    'tag_counts': coming_tag_counts,
                    'disabled': not has_coming_events,
                    'empty_str': _('No upcoming event carries the selected tags.')
                    if tag_filter
                    else _('No upcoming events.'),
                    'icon_class': 'bi-calendar-check indented',
                    'page_title': _('Upcoming events'),
                },
                'passed_events': {
                    'title': _('Passed ({num})').format(num=len(passed_events) or '-'),
                    'template': 'index/events_tab.html',
                    'events': passed_events,
                    'tag_counts': passed_tag_counts,
                    'disabled': not has_passed_events,
                    'empty_str': _('No passed event carries the selected tags.')
                    if tag_filter
                    else _('No passed events.'),
                    'icon_class': 'bi-calendar-minus indented',
                    'page_title': _('Passed events'),
                },
                'archives': {
                    'title': _('Archived ({num})').format(
                        num=len(sorted_archives) or '-'
                    ),
                    'template': 'index/archives_tab.html',
                    'archives': sorted_archives,
                    'disabled': not sorted_archives,
                    'empty_str': _('No archived events.'),
                    'icon_class': 'bi-archive indented',
                    'page_title': _('Archived events'),
                },
            }
        else:
            nav_tabs |= {
                'home': {
                    'title': _('Events ({num})').format(num=len(lan_events) or '-'),
                    'template': 'index/home_tab.html',
                    'events': lan_events,
                    'disabled': False,
                    'empty_str': _('No events.'),
                    'icon_class': 'bi-house-fill',
                    'page_title': _('Events'),
                    'divider': True,
                },
            }
        if web_context.client.can_manage_events:
            championships = []
            championship_loader = ChampionshipLoader()
            championship_archives = ChampionshipArchiveLoader.get_sorted_archives()
            for championship_id in championship_loader.all_championship_ids():
                try:
                    championships.append(
                        championship_loader.load_championship(championship_id)
                    )
                except Exception as error:
                    logger.warning(
                        'Could not load championship [%s]: %s',
                        championship_id,
                        error,
                    )
            today = date.today()
            coming_championships = [
                item
                for item in championships
                if item.start_date is not None and today < item.start_date
            ]
            passed_championships = [
                item
                for item in championships
                if item.stop_date is not None and item.stop_date < today
            ]
            dated_championship_ids = {
                id(item) for item in coming_championships + passed_championships
            }
            current_championships = [
                item for item in championships if id(item) not in dated_championship_ids
            ]

            def championship_sort_key(item):
                return (
                    item.stop_date or date.max,
                    item.start_date or date.min,
                    item.name.casefold(),
                )

            current_championships.sort(key=championship_sort_key)
            coming_championships.sort(key=championship_sort_key)
            passed_championships.sort(
                key=lambda item: (
                    -(item.stop_date or date.min).toordinal(),
                    -(item.start_date or date.min).toordinal(),
                    item.name.casefold(),
                )
            )
            nav_tabs |= {
                'championships': {
                    'section_title': _('Championships'),
                    'section_create_modal_url': (
                        web_context.request.app.route_reverse(
                            'admin-championship-create-modal'
                        )
                    ),
                    'section_create_label': _('Create a championship'),
                    'title': _('Current ({num})').format(
                        num=len(current_championships) or '-'
                    ),
                    'template': 'index/championships_tab.html',
                    'championships': current_championships,
                    'disabled': not current_championships,
                    'empty_str': _('No current championships.'),
                    'icon_class': 'bi-calendar indented',
                    'page_title': _('Current championships'),
                    'divider': True,
                },
                'coming_championships': {
                    'title': _('Upcoming ({num})').format(
                        num=len(coming_championships) or '-'
                    ),
                    'template': 'index/championships_tab.html',
                    'championships': coming_championships,
                    'disabled': not coming_championships,
                    'empty_str': _('No upcoming championships.'),
                    'icon_class': 'bi-calendar-check indented',
                    'page_title': _('Upcoming championships'),
                },
                'passed_championships': {
                    'title': _('Passed ({num})').format(
                        num=len(passed_championships) or '-'
                    ),
                    'template': 'index/championships_tab.html',
                    'championships': passed_championships,
                    'disabled': not passed_championships,
                    'empty_str': _('No passed championships.'),
                    'icon_class': 'bi-calendar-minus indented',
                    'page_title': _('Passed championships'),
                },
                'championship_archives': {
                    'title': _('Archived ({num})').format(
                        num=len(championship_archives) or '-'
                    ),
                    'template': 'index/championship_archives_tab.html',
                    'championship_archives': championship_archives,
                    'disabled': not championship_archives,
                    'empty_str': _('No archived championships.'),
                    'icon_class': 'bi-archive indented',
                    'page_title': _('Archived championships'),
                },
            }
        admin_tab = web_context.admin_tab
        if (not template_context or 'modal' not in template_context) and (
            admin_tab not in nav_tabs or nav_tabs[admin_tab]['disabled']
        ):
            nav_ids = list(nav_tabs)
            start_index = nav_ids.index(admin_tab) if admin_tab in nav_tabs else -1
            web_context.admin_tab = next(
                (
                    nav_ids[(start_index + offset) % len(nav_ids)]
                    for offset in range(1, len(nav_ids) + 1)
                    if not nav_tabs[nav_ids[(start_index + offset) % len(nav_ids)]][
                        'disabled'
                    ]
                ),
                nav_ids[0],
            )

        svg_logo = (BASE_DIR / 'src/web/static/images/sharly-chess-logo.svg').read_text(
            encoding='utf-8'
        )
        request = web_context.request
        context = (
            web_context.template_context
            | {
                'messages': Message.messages(request),
                'format_date_range': format_date_range,
                'format_date': format_date,
                'nav_tabs': nav_tabs,
                'svg_logo': svg_logo,
                'all_tags': all_tags,
                'admin_events_tag_filter': tag_filter,
                'show_details': SessionEventsShowDetails(request).get(),
                'plugin_event_create_button_templates': (
                    plugin_manager.hook.create_event_button_template()
                ),
            }
            | (template_context or {})
        )

        return context

    @classmethod
    def _admin_render(
        cls,
        web_context: AdminWebContext,
        template_context: dict[str, Any] | None = None,
        keep_modal_open: bool | None = None,
    ) -> Template:
        context = cls.admin_shell_context(web_context, template_context)
        if 'modal' in context:
            return cls._render_modal(
                'admin/modals.html', context, bool(keep_modal_open)
            )
        return HTMXTemplate(template_name='admin/index.html', context=context)

    @get(
        path='/{admin_tab:str}',
        name='admin-tab',
    )
    async def htmx_admin_tab(
        self,
        request: HTMXRequest,
        admin_tab: FromPath[str],
        show_details: FromQuery[bool | None] = None,
        filter_tags: FromQuery[str | None] = None,
    ) -> Template:
        web_context = AdminWebContext(request, admin_tab=admin_tab)

        if show_details is not None:
            SessionEventsShowDetails(request).set(show_details)

        # A ';'-separated list of tag ids; empty clears the filter, absent
        # leaves it untouched.
        if filter_tags is not None:
            SessionEventsTags(request).set(
                {
                    int(value)
                    for value in filter_tags.split(';')
                    if value.strip().isdigit()
                }
            )

        return self._admin_render(web_context=web_context)

    @staticmethod
    def _age_category_sets_form_context(
        data: dict[str, str],
        errors: dict[str, str] | None = None,
        sets_container_state: Literal['hidden', 'list', 'form'] = 'hidden',
    ) -> dict[str, Any]:
        default_data = WebContext.values_dict_to_form_data(
            {
                'category_set_name': '',
                'category_set_categories': [],
                'age_categories': [],
            }
        )
        category_sets = SharlyChessConfig().player_category_sets
        category_options: dict[str, dict[str, str]] = {
            _('Category sets'): {
                category_set.form_key: category_set.name
                for category_set in category_sets
            },
            _('Junior categories'): {
                category.id: category.name for category in SELECTABLE_JUNIOR_CATEGORIES
            },
            _('Senior categories'): {
                category.id: category.name for category in SELECTABLE_SENIOR_CATEGORIES
            },
        }
        return {
            'age_category_sets_container_state': sets_container_state,
            'player_category_options': category_options,
            'player_category_sets': category_sets,
            'errors': errors or {},
            'data': default_data | data,
        }

    @staticmethod
    def _tags_form_context(
        data: dict[str, str],
        errors: dict[str, str] | None = None,
        container_state: Literal['hidden', 'list', 'form'] = 'hidden',
        edited_tag_id: int | None = None,
    ) -> dict[str, Any]:
        """The context of the tags form of the event modal. The tags
        themselves are global to the installation, the form only picks
        which ones the event carries."""
        tags = SharlyChessConfig().tags
        event_counts_by_tag_id: dict[int, int] = defaultdict(int)
        # Counting reopens every event database, so it is only done when the
        # manager panel — the only place showing the counts — is open.
        if container_state != 'hidden':
            for event_metadata in EventLoader.get_events_metadata():
                for tag_id in event_metadata.tag_ids:
                    event_counts_by_tag_id[tag_id] += 1
        default_data = WebContext.values_dict_to_form_data(
            {
                'tag_name': '',
                'tag_color': DEFAULT_TAG_COLOR,
                'tags': [],
            }
        )
        return {
            'tags_container_state': container_state,
            'tag_options': {str(tag.id): tag.name for tag in tags},
            'all_tags': tags,
            # Proposed while the registry is empty, which is the only state
            # the manager offers them in.
            'default_tag_sets': default_tag_sets() if not tags else [],
            'tag_event_counts': event_counts_by_tag_id,
            'edited_tag_id': edited_tag_id,
            'default_tag_color': DEFAULT_TAG_COLOR,
            'errors': errors or {},
            'data': default_data | data,
        }

    @classmethod
    def _prepare_event_modal_data(
        cls,
        action: str,
        request: HTMXRequest,
        admin_event: Event | None,
    ) -> dict[str, Any]:
        if action == 'create':
            name = EventLoader.get(request).get_unused_event_name(_('New event'))
            uniq_id = EventLoader.get(request).get_unused_event_uniq_id(_('event'))
            public = False
            config = SharlyChessConfig()
            allow_multi_tournament_players = True
            federation = config.federation.name if config.federation else ''
            player_rating_type = PlayerRatingType.FIDE.value
            event_type = EventType.INDIVIDUAL.value
            location: str | None = None
            age_category_base_date: date | None = None
            age_category_change_month: int = 1
            age_categories: list[str] | None = None
            organiser_name: str | None = None
            organiser_home_page: str | None = None
            organiser_email: str | None = None
            organiser_director: str | None = None
            tag_ids: list[int] = []
            stored_plugin_data: dict[str, dict[str, Any]] = {}
            event_enabled_plugins = [
                plugin
                for plugin in plugin_manager.enabled_plugins
                if plugin.default_event_is_enabled
            ]
        else:
            assert admin_event is not None
            stored_event = admin_event.stored_event
            if action == 'update':
                name = stored_event.name
                uniq_id = stored_event.uniq_id
            else:
                loader = EventLoader()
                name = loader.get_unused_event_name(stored_event.name)
                uniq_id = loader.get_unused_event_uniq_id(stored_event.uniq_id)
            public = stored_event.public
            allow_multi_tournament_players = admin_event.allow_multi_tournament_players
            federation = stored_event.federation
            location = stored_event.location
            age_category_base_date = stored_event.age_category_base_date
            age_category_change_month = stored_event.age_category_change_month
            age_categories = stored_event.age_categories
            organiser_name = stored_event.organiser_name
            organiser_home_page = stored_event.organiser_home_page
            organiser_email = stored_event.organiser_email
            organiser_director = stored_event.organiser_director
            tag_ids = stored_event.tag_ids
            player_rating_type = stored_event.player_rating_type
            event_type = stored_event.event_type.value
            stored_plugin_data = stored_event.plugin_data
            event_enabled_plugins = admin_event.enabled_plugins

        plugin_form_data: dict[str, str] = {}
        for (
            plugin_id,
            plugin_data_class,
        ) in Event.plugin_data_class_by_plugin_id().items():
            plugin_form_data |= plugin_data_class.from_stored_value(
                stored_plugin_data.get(plugin_id, {})
            ).to_form_data(action=action)
        plugin_form_data |= {
            plugin.form_key: WebContext.value_to_form_data(
                plugin in event_enabled_plugins
            )
            for plugin in plugin_manager.enabled_plugins
        }

        return (
            WebContext.values_dict_to_form_data(
                {
                    'uniq_id': uniq_id,
                    'name': name,
                    'public': public,
                    'allow_multi_tournament_players': allow_multi_tournament_players,
                    'federation': federation,
                    'event_type': event_type,
                    'player_rating_type': player_rating_type,
                    'location': location,
                    'organiser_name': organiser_name,
                    'organiser_home_page': organiser_home_page,
                    'organiser_email': organiser_email,
                    'organiser_director': organiser_director,
                    'age_category_base_date': age_category_base_date,
                    'age_category_change_month': age_category_change_month,
                    'age_categories': age_categories,
                    'tags': tag_ids,
                }
            )
            | plugin_form_data
        )

    @classmethod
    def _read_event_form_data(
        cls,
        action: FormAction,
        web_context: WebContext,
        admin_event: Event | None,
        data: dict[str, str] | None = None,
    ) -> tuple[StoredEvent | None, dict[str, str]]:
        if data is None:
            data = {}
        uniq_id: str
        errors: dict[str, str] = {}
        config = SharlyChessConfig()

        name = WebContext.form_data_to_str(data, field := 'name') or ''
        if not name:
            errors[field] = _('Please enter the name of the event.')
        if action == 'update' and web_context.client.can_rename_event:
            assert admin_event is not None
            uniq_id = admin_event.uniq_id
        else:
            uniq_id = EventLoader().get_unused_event_uniq_id(
                Utils.name_to_uniq_id(name)
            )
        if action == FormAction.CLONE:
            try:
                WebContext.form_data_to_date(data, field := 'clone_start_date')
            except FormError as e:
                errors[field] = str(e)

        federation = WebContext.form_data_to_str(data, field := 'federation', '') or ''
        if federation not in SharlyChessConfig().federations:
            # should never happen, not translated.
            errors[field] = f'Invalid federation value [{data[field]}].'
            data[field] = ''

        if action == FormAction.CREATE:
            event_type_raw = (
                WebContext.form_data_to_str(
                    data, field := 'event_type', EventType.INDIVIDUAL.value
                )
                or EventType.INDIVIDUAL.value
            )
            try:
                event_type = EventType(event_type_raw)
            except ValueError:
                errors[field] = f'Invalid event type value [{event_type_raw}].'
                event_type = EventType.INDIVIDUAL
        else:
            assert admin_event is not None
            event_type = admin_event.event_type

        public = WebContext.form_data_to_bool(data, 'public')
        location = WebContext.form_data_to_str(data, 'location')
        organiser_name = WebContext.form_data_to_str(data, 'organiser_name')
        organiser_director = WebContext.form_data_to_str(data, 'organiser_director')

        organiser_home_page = WebContext.form_data_to_str(
            data, field := 'organiser_home_page'
        )
        if organiser_home_page and not is_http_url(organiser_home_page):
            errors[field] = _('Please supply a valid URL (e.g. https://my.domain.com).')

        organiser_email = WebContext.form_data_to_str(data, field := 'organiser_email')
        if organiser_email and not is_valid_email(organiser_email):
            errors[field] = _('Please supply a valid email address.')

        player_rating_type: int = (
            WebContext.form_data_to_int(data, 'player_rating_type')
            or PlayerRatingType.FIDE.value
        )

        age_categories = WebContext.form_data_to_list_str(data, 'age_categories')
        age_category_base_date: date | None = None
        try:
            age_category_base_date = WebContext.form_data_to_date(
                data, field := 'age_category_base_date'
            )
        except FormError as e:
            errors[field] = str(e)
        age_category_change_month = (
            WebContext.form_data_to_int(data, 'age_category_change_month') or 1
        )
        allow_multi_tournament_players = WebContext.form_data_to_bool(
            data, 'allow_multi_tournament_players'
        )

        # Only tags that still exist are kept: a tag deleted while the event
        # referenced it is silently dropped the next time the event is saved.
        known_tag_ids = config.tags_by_id
        tag_ids = [
            tag_id
            for tag_id in (
                int(value)
                for value in WebContext.form_data_to_list_str(data, 'tags')
                if value.isdigit()
            )
            if tag_id in known_tag_ids
        ]

        enabled_plugins = plugin_manager.get_plugins_with_dependencies(
            [
                plugin
                for plugin in plugin_manager.enabled_plugins
                if WebContext.form_data_to_bool(data, plugin.form_key)
                and plugin.supports_event_type(event_type)
            ]
        )

        plugin_manager.hook_for_plugins('validate_event_form_fields', enabled_plugins)(
            action=action, event=admin_event, data=data, errors=errors
        )

        plugin_data: dict[str, dict[str, Any]] = {}
        for (
            plugin_id,
            plugin_data_class,
        ) in Event.plugin_data_class_by_plugin_id().items():
            previous_object = None
            if admin_event is not None:
                previous_object = admin_event.plugin_data.get(plugin_id)

            plugin_data[plugin_id] = plugin_data_class.from_form_data(
                data, action=action, previous_object=previous_object
            ).to_stored_value()

        if errors:
            return None, errors

        stored_event = StoredEvent(
            uniq_id=uniq_id,
            name=name,
            federation=federation,
            event_type=event_type,
            public=bool(public),
            allow_multi_tournament_players=allow_multi_tournament_players,
            location=location,
            organiser_name=organiser_name,
            organiser_home_page=organiser_home_page,
            organiser_email=organiser_email,
            organiser_director=organiser_director,
            age_category_base_date=age_category_base_date,
            age_category_change_month=age_category_change_month,
            age_categories=age_categories,
            tag_ids=tag_ids,
            player_rating_type=player_rating_type,
            plugin_data=plugin_data,
            enabled_plugins=[plugin.id for plugin in enabled_plugins],
            # Defaults edited in other tabs
            timer_colors=config.default_timer_colors,  # type: ignore
            timer_delays=config.default_timer_delays,  # type: ignore
            background_color=config.default_background_color,
            message_background_color=config.default_message_background_color,
            message_color=config.default_message_color,
        )
        if admin_event:
            # Defaults edited in other tabs
            stored_event.timer_colors = admin_event.stored_event.timer_colors
            stored_event.timer_delays = admin_event.stored_event.timer_delays
            stored_event.background_color = admin_event.stored_event.background_color
            stored_event.message_background_color = admin_event.message_background_color
            stored_event.message_color = admin_event.message_color
            stored_event.message_text = admin_event.message_text
            stored_event.prize_currency = admin_event.stored_event.prize_currency

        return stored_event, errors

    def _event_modal_context(
        self,
        web_context: AdminWebContext,
        action: FormAction,
        data: dict[str, str],
        errors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        event = web_context.admin_event
        federation_plugin_used = False
        if action == FormAction.UPDATE:
            assert event is not None
            for plugin in event.enabled_plugins:
                if not plugin.federation:
                    continue
                if plugin.used_by_tournaments_count(event):
                    federation_plugin_used = True
                    break
        errors = errors or {}
        event_type_locked = action != FormAction.CREATE
        template_context = {
            'federation_options': self._get_federation_options(),
            'months_options': self._months_options(),
            'modal': 'event',
            'event_uniq_ids': EventLoader.all_event_ids(),
            'plugins': plugin_manager.enabled_plugins,
            'federation_plugin_used': federation_plugin_used,
            'event_type_options': {
                event_type.value: str(event_type) for event_type in EventType
            },
            'event_type_locked': event_type_locked,
            'player_rating_type_options': {
                str(PlayerRatingType.FIDE.value): _('FIDE'),
                str(PlayerRatingType.NATIONAL.value): _(
                    'National *** NAME FOR RATING TYPE NATIONAL'
                ),
            },
            'has_multi_tournament_players': event
            and event.has_multi_tournament_players,
            'force_organiser_open': any(
                field in errors
                for field in [
                    'organiser_name',
                    'organiser_home_page',
                    'organiser_email',
                ]
            ),
            'force_categories_open': any(
                field in errors
                for field in [
                    'age_categories',
                    'age_category_base_date',
                    'age_category_change_month',
                ]
            ),
            'action': action,
            'data': data,
            'errors': errors,
        }
        age_categories_context = self._age_category_sets_form_context(data, errors)
        # Chained on the data already completed above, so that neither form's
        # defaults are dropped.
        tags_context = self._tags_form_context(age_categories_context['data'], errors)
        return template_context | age_categories_context | tags_context

    @get(
        path=[
            '/{admin_tab:str}/event-modal/{action:str}',
            '/{admin_tab:str}/event-modal/{action:str}/{event_uniq_id:str}',
            '/event-modal/{action:str}/{event_uniq_id:str}',
        ],
        name='admin-event-modal',
        guards=[ActionGuard(AuthAction.VIEW_EVENT_CONFIG)],
    )
    async def htmx_admin_tab_event_create_modal(
        self,
        request: HTMXRequest,
        action: FromPath[FormAction],
        admin_tab: FromPath[str | None] = None,
    ) -> Template:
        web_context = AdminWebContext(request, admin_tab=admin_tab)
        data = self._prepare_event_modal_data(action, request, web_context.admin_event)
        template_context = self._event_modal_context(web_context, action, data)

        return self._admin_render(
            web_context=web_context,
            template_context=template_context,
        )

    @post(
        path='/{admin_tab:str}/create-event',
        name='admin-tab-create-event',
        guards=[ActionGuard(AuthAction.CREATE_EVENTS)],
    )
    async def htmx_admin_tab_event_create(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        admin_tab: FromQuery[str],
    ) -> Template | Redirect:
        web_context = AdminWebContext(request, admin_tab=admin_tab)
        flat_data = WebContext.flatten_list_data(data)
        stored_event, errors = self._read_event_form_data(
            FormAction.CREATE, web_context, None, flat_data
        )
        if not stored_event:
            template_context = self._event_modal_context(
                web_context, FormAction.CREATE, flat_data, errors=errors
            )
            return self._admin_render(
                web_context=web_context,
                template_context=template_context,
            )

        uniq_id: str = stored_event.uniq_id
        EventDatabase(uniq_id).create()
        with EventDatabase(uniq_id, write=True) as database:
            database.update_stored_event(stored_event)
        Message.success(
            request, _('Event [{uniq_id}] has been created.').format(uniq_id=uniq_id)
        )
        return Redirect(admin_event_url(request, event_uniq_id=uniq_id))

    @get(
        path='/{admin_tab:str}/event-modal/delete/{event_uniq_id:str}',
        name='admin-event-delete-modal',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_event_delete_modal(
        self, request: HTMXRequest, admin_tab: FromPath[str]
    ) -> Template:
        web_context = AdminWebContext(request, admin_tab=admin_tab)
        referencing_championships = [
            ChampionshipLoader().load_championship(championship_id)
            for championship_id in ChampionshipLoader.championship_ids_referencing(
                web_context.get_admin_event().uniq_id
            )
        ]
        return self._admin_render(
            web_context,
            {
                'modal': 'event-delete',
                'referencing_championships': referencing_championships,
            },
        )

    @delete(
        path='/{admin_tab:str}/event-delete/{event_uniq_id:str}',
        name='admin-event-delete',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_event_delete(
        self, request: HTMXRequest, admin_tab: FromPath[str]
    ) -> Template:
        web_context = AdminWebContext(request, admin_tab=admin_tab)
        event = web_context.get_admin_event()
        try:
            arch = EventDatabase(event.uniq_id).delete()
        except PermissionError as ex:
            raise ClientException(f'Archiving the database failed: {ex}')

        Message.success(
            request,
            _(
                'Event [{uniq_id}] has been deleted, the database has been archived ({arch}).'
            ).format(uniq_id=event.uniq_id, arch=arch),
        )

        return self._admin_render(web_context)

    @post(
        path='/event-clone/{event_uniq_id:str}',
        name='admin-event-clone',
        guards=[ActionGuard(AuthAction.CREATE_EVENTS)],
    )
    async def htmx_admin_event_clone(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template | ClientRedirect:
        web_context = AdminWebContext(request)
        flat_data = WebContext.flatten_list_data(data)
        event = web_context.get_admin_event()
        stored_event, errors = self._read_event_form_data(
            FormAction.CLONE, web_context, event, flat_data
        )
        if not stored_event:
            template_context = self._event_modal_context(
                web_context, FormAction.CLONE, flat_data, errors=errors
            )
            return self._admin_render(
                web_context=web_context,
                template_context=template_context,
            )
        clone_players = WebContext.form_data_to_bool(flat_data, 'clone_players')
        clone_pairings = WebContext.form_data_to_bool(flat_data, 'clone_pairings')
        start_date = WebContext.form_data_to_date(flat_data, 'clone_start_date')
        uniq_id: str = stored_event.uniq_id
        EventDatabase(event.uniq_id).clone(new_uniq_id=uniq_id)
        with EventDatabase(uniq_id, write=True) as database:
            database.update_stored_event(stored_event)
            if not clone_players:
                database.delete_all_stored_players()
            elif not clone_pairings:
                database.delete_all_stored_pairings()

            if not (clone_pairings and clone_players):
                for tournament in event.tournaments:
                    database.set_tournament_pairing_settings(tournament.id, {})
                    database.set_tournament_current_round(tournament.id, None)
            stored_event = database.load_stored_event()
            if start_date:
                day_diff = start_date - event.start_date
                for stored_timer in stored_event.stored_timers:
                    for stored_timer_hour in stored_timer.stored_timer_hours:
                        stored_timer_hour.triggered_at += day_diff
                        database.update_stored_timer_hour(stored_timer_hour)
                for stored_tournament in stored_event.stored_tournaments:
                    stored_tournament.start_date += day_diff
                    stored_tournament.stop_date += day_diff
                    stored_tournament.round_datetimes = {
                        round_: datetime_ + day_diff if datetime_ else None
                        for round_, datetime_ in stored_tournament.round_datetimes.items()
                    }
                    database.update_stored_tournament(stored_tournament)
            plugin_manager.hook.on_event_duplicated(event_database=database)

        # Carry the current login into the duplicate: the clone copies the
        # accounts (same ids and password hashes), so a remote organiser stays
        # authenticated on the new event instead of landing there anonymously.
        account = web_context.client.account
        if (
            not account.administrator
            and not account.anonymous
            and account.password_hash
        ):
            new_event = Event(stored_event)
            SessionUserAccountId(request, new_event).set(account.id)
            SessionUserAccountPasswordHash(request, new_event).set(
                account.password_hash
            )

        Message.success(
            request,
            _('Event [{uniq_id}] has been created.').format(uniq_id=uniq_id),
        )
        return ClientRedirect(redirect_to=admin_event_url(request, uniq_id))

    @patch(
        path=[
            '/event-update/{event_uniq_id:str}',
            '/{admin_tab:str}/event-update/{event_uniq_id:str}',
        ],
        name='admin-event-update',
        guards=[ActionGuard(AuthAction.UPDATE_EVENT)],
    )
    async def htmx_admin_event_update(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        admin_tab: FromPath[str | None],
    ) -> Template:
        web_context = AdminWebContext(request, admin_tab=admin_tab)
        flat_data = WebContext.flatten_list_data(data)
        event = web_context.get_admin_event()
        stored_event, errors = self._read_event_form_data(
            FormAction.UPDATE, web_context, event, flat_data
        )
        if not stored_event:
            template_context = self._event_modal_context(
                web_context, FormAction.UPDATE, flat_data, errors=errors
            )
            return self._admin_render(
                web_context=web_context,
                template_context=template_context,
            )

        uniq_id = stored_event.uniq_id
        with EventDatabase(uniq_id, write=True) as database:
            database.update_stored_event(stored_event)

        Message.success(
            request,
            _('Event [{uniq_id}] has been updated.').format(uniq_id=uniq_id),
        )
        return self._render_empty_modal_and_messages(request)

    @patch(
        path='/event-uniq-id-update/{event_uniq_id:str}',
        name='admin-event-uniq-id-update',
        guards=[ActionGuard(AuthAction.RENAME_EVENT)],
    )
    async def htmx_admin_event_uniq_id_update(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> ClientRedirect:
        web_context = AdminWebContext(request)
        event = web_context.get_admin_event()
        new_uniq_id = WebContext.form_data_to_str(data, 'uniq_id')
        if (
            not new_uniq_id
            or not SharlyChessConfig.uniq_id_regex.match(new_uniq_id)
            or (
                new_uniq_id != event.uniq_id
                and new_uniq_id in EventLoader.all_event_ids()
            )
        ):
            # No precise error (validated in JS)
            raise ClientException(f'Invalid event uniq ID [{new_uniq_id}].')
        if new_uniq_id != event.uniq_id:
            try:
                EventDatabase(event.uniq_id).rename(new_uniq_id)
            except PermissionError as ex:
                raise ClientException(f'Renaming the database failed: {ex}.')
            ChampionshipLoader.rename_event_references(event.uniq_id, new_uniq_id)
            Message.success(
                request,
                _(
                    'Event unique ID has been renamed from '
                    '[{old_uniq_id}] to [{new_uniq_id}].'
                ).format(
                    old_uniq_id=event.uniq_id,
                    new_uniq_id=new_uniq_id,
                ),
            )
        return ClientRedirect(redirect_to=admin_event_url(request, new_uniq_id))

    @classmethod
    def _render_age_category_sets_modal(
        cls,
        web_context: AdminWebContext,
        data: dict[str, str],
        errors: dict[str, str] | None = None,
        container_state: Literal['hidden', 'list', 'form'] = 'list',
    ) -> Template:
        """``data`` is the event modal's in-progress form, carried through so
        that Back can restore it."""
        return cls._admin_render(
            web_context=web_context,
            template_context=(
                cls._age_category_sets_form_context(
                    data, errors, sets_container_state=container_state
                )
                | {
                    'modal': 'event-age-category-sets',
                    'event_form_data': data,
                }
            ),
        )

    @post(
        path='/age-category-sets/manager',
        name='age-category-sets-manager',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_age_category_sets_manager(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        """Open the category-set manager, carrying the event modal's form."""
        web_context = AdminWebContext(request)
        return self._render_age_category_sets_modal(
            web_context, WebContext.flatten_list_data(data)
        )

    @post(
        path='/age-category-sets/add-form',
        name='age-category-set-add-form',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_age_category_set_add_form(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        flat_data = WebContext.flatten_list_data(data) | {
            'category_set_name': '',
            'category_set_categories': '',
        }
        return self._render_age_category_sets_modal(
            web_context, flat_data, container_state='form'
        )

    @post(
        path='/player-category-set/create',
        name='player-category-set-create',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_create_player_category_set(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        flat_data = WebContext.flatten_list_data(data)
        errors: dict[str, str] = {}
        category_sets = SharlyChessConfig().player_category_sets
        name = (
            WebContext.form_data_to_str(flat_data, field := 'category_set_name') or ''
        )
        if not name:
            errors[field] = _('This field is required.')
        elif name in (category_set.name for category_set in category_sets):
            errors[field] = _('A set with this name already existe.')
        category_ids = WebContext.form_data_to_list_str(
            flat_data, field := 'category_set_categories'
        )
        if not category_ids:
            errors[field] = _('This field is required.')
        for category in category_ids:
            try:
                PlayerCategory.from_id(category)
            except ValueError:
                errors[field] = f'Unknown category [{category}].'
        if errors:
            return self._render_age_category_sets_modal(
                web_context, flat_data, errors, container_state='form'
            )
        with ConfigDatabase(True) as database:
            database.add_stored_player_category_set(
                StoredPlayerCategorySet(id=None, name=name, categories=category_ids)
            )
        SharlyChessConfig().load_and_set_env()
        flat_data |= {'category_set_name': '', 'category_set_categories': ''}
        return self._render_age_category_sets_modal(web_context, flat_data)

    @post(
        # A POST, not a DELETE: see tag-delete.
        path='/player-category-set/delete/{player_category_set_id:int}',
        name='player-category-set-delete',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_delete_player_category_set(
        self,
        request: HTMXRequest,
        player_category_set_id: FromPath[int],
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        with ConfigDatabase(True) as database:
            database.delete_stored_player_category_set(player_category_set_id)
        SharlyChessConfig().load_and_set_env()
        return self._render_age_category_sets_modal(
            web_context, WebContext.flatten_list_data(data)
        )

    @classmethod
    def _render_tags_modal(
        cls,
        web_context: AdminWebContext,
        data: dict[str, str],
        errors: dict[str, str] | None = None,
        container_state: Literal['hidden', 'list', 'form'] = 'list',
        edited_tag_id: int | None = None,
    ) -> Template:
        """``data`` is the event modal's in-progress form, carried through so
        that Back can restore it."""
        return cls._admin_render(
            web_context=web_context,
            template_context=(
                cls._tags_form_context(
                    data,
                    errors,
                    container_state=container_state,
                    edited_tag_id=edited_tag_id,
                )
                | {
                    'modal': 'event-tags',
                    'event_form_data': data,
                    'add_other_active': SessionTagsAddOtherActive(
                        web_context.request
                    ).get(),
                }
            ),
        )

    @staticmethod
    def _read_tag_form_data(
        data: dict[str, str], ignore_tag_id: int | None = None
    ) -> tuple[str, str, dict[str, str]]:
        """The name and colour of the tag being created or updated, together
        with the validation errors."""
        errors: dict[str, str] = {}
        name = WebContext.form_data_to_str(data, field := 'tag_name') or ''
        if not name:
            errors[field] = _('This field is required.')
        elif any(
            tag.name.lower() == name.lower() and tag.id != ignore_tag_id
            for tag in SharlyChessConfig().tags
        ):
            errors[field] = _('This name is already used.')
        color = DEFAULT_TAG_COLOR
        try:
            color = check_rgb_str(
                WebContext.form_data_to_str(data, field := 'tag_color')
                or DEFAULT_TAG_COLOR
            )
        except ValueError:
            errors[field] = _('Please choose a valid colour.')
        return name, color, errors

    @post(
        path='/tag/create',
        name='tag-create',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_create_tag(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        flat_data = WebContext.flatten_list_data(data)
        add_other = WebContext.resolve_add_other(
            flat_data, SessionTagsAddOtherActive(request)
        )
        name, color, errors = self._read_tag_form_data(flat_data)
        if errors:
            return self._render_tags_modal(
                web_context, flat_data, errors, container_state='form'
            )
        with ConfigDatabase(True) as database:
            tag_id = database.add_stored_tag(StoredTag(id=None, name=name, color=color))
        SharlyChessConfig().load_and_set_env()
        # A tag created from an event is meant for that event: select it.
        selected_tag_ids = WebContext.form_data_to_list_str(flat_data, 'tags')
        selected_tag_ids.append(str(tag_id))
        flat_data['tags'] = ';'.join(selected_tag_ids)
        if add_other:
            flat_data |= {'tag_name': '', 'tag_color': DEFAULT_TAG_COLOR}
            return self._render_tags_modal(
                web_context, flat_data, container_state='form'
            )
        return self._render_tags_modal(web_context, flat_data)

    @post(
        path=[
            '/{admin_tab:str}/event-modal-restore/{action:str}',
            '/{admin_tab:str}/event-modal-restore/{action:str}/{event_uniq_id:str}',
            '/event-modal-restore/{action:str}/{event_uniq_id:str}',
        ],
        name='admin-event-modal-restore',
        guards=[ActionGuard(AuthAction.VIEW_EVENT_CONFIG)],
    )
    async def htmx_admin_event_modal_restore(
        self,
        request: HTMXRequest,
        action: FromPath[FormAction],
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        admin_tab: FromPath[str | None] = None,
    ) -> Template:
        """Re-open the event modal on the form the tag manager was opened
        from, so leaving to manage tags doesn't discard unsaved edits."""
        web_context = AdminWebContext(request, admin_tab=admin_tab)
        flat_data = WebContext.flatten_list_data(data)
        template_context = self._event_modal_context(web_context, action, flat_data)
        return self._admin_render(
            web_context=web_context, template_context=template_context
        )

    @post(
        path='/tag/manager',
        name='tag-manager',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_tag_manager(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        """Open the tag manager, carrying the event modal's in-progress form."""
        web_context = AdminWebContext(request)
        return self._render_tags_modal(web_context, WebContext.flatten_list_data(data))

    @post(
        path='/tag/add-form',
        name='tag-add-form',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_tag_add_form(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        flat_data = WebContext.flatten_list_data(data) | {
            'tag_name': '',
            'tag_color': DEFAULT_TAG_COLOR,
        }
        return self._render_tags_modal(web_context, flat_data, container_state='form')

    @post(
        path='/tag/update-form/{tag_id:int}',
        name='tag-update-form',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_tag_update_form(
        self,
        request: HTMXRequest,
        tag_id: FromPath[int],
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        tag = SharlyChessConfig().tags_by_id.get(tag_id)
        if tag is None:
            raise NotFoundException(f'Unknown tag [{tag_id}].')
        flat_data = WebContext.flatten_list_data(data) | {
            'tag_name': tag.name,
            'tag_color': tag.color,
        }
        return self._render_tags_modal(
            web_context, flat_data, container_state='form', edited_tag_id=tag_id
        )

    @patch(
        path='/tag/update/{tag_id:int}',
        name='tag-update',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_update_tag(
        self,
        request: HTMXRequest,
        tag_id: FromPath[int],
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        if tag_id not in SharlyChessConfig().tags_by_id:
            raise NotFoundException(f'Unknown tag [{tag_id}].')
        flat_data = WebContext.flatten_list_data(data)
        name, color, errors = self._read_tag_form_data(flat_data, ignore_tag_id=tag_id)
        if errors:
            return self._render_tags_modal(
                web_context,
                flat_data,
                errors,
                container_state='form',
                edited_tag_id=tag_id,
            )
        with ConfigDatabase(True) as database:
            database.update_stored_tag(StoredTag(id=tag_id, name=name, color=color))
        SharlyChessConfig().load_and_set_env()
        return self._render_tags_modal(web_context, flat_data)

    @post(
        path='/tag/add-sets',
        name='tag-sets-add',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_add_tag_sets(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        """Take the ready-made sets ticked in the manager. A set is only
        offered on an empty registry, but names are unique, so one already
        in use is left alone rather than refused."""
        web_context = AdminWebContext(request)
        flat_data = WebContext.flatten_list_data(data)
        picked = set(WebContext.form_data_to_list_str(flat_data, 'tag_sets'))
        flat_data.pop('tag_sets', None)
        names = {tag.name for tag in SharlyChessConfig().tags}
        with ConfigDatabase(True) as database:
            for tag_set in default_tag_sets():
                if tag_set.id not in picked:
                    continue
                for tag in tag_set.tags:
                    if tag.name in names:
                        continue
                    names.add(tag.name)
                    database.add_stored_tag(
                        StoredTag(id=None, name=tag.name, color=tag.color)
                    )
        SharlyChessConfig().load_and_set_env()
        return self._render_tags_modal(web_context, flat_data)

    @patch(
        path='/tag/reorder',
        name='tag-reorder',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_reorder_tags(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        """Rank the tags in the dragged order. The rows of the tag manager
        are sent along with the event form they carry, so the ids are read
        out of it and the rest is handed back untouched."""
        web_context = AdminWebContext(request)
        flat_data = WebContext.flatten_list_data(data)
        tag_ids = [
            int(value)
            for value in WebContext.form_data_to_list_str(flat_data, 'tag_ids')
            if value.isdigit()
        ]
        flat_data.pop('tag_ids', None)
        with ConfigDatabase(True) as database:
            database.reorder_stored_tags(tag_ids)
        SharlyChessConfig().load_and_set_env()
        return self._render_tags_modal(web_context, flat_data)

    @post(
        # A POST, not a DELETE: htmx sends DELETE parameters in the URL, and
        # the event form carried by the modal belongs in the body.
        path='/tag/delete/{tag_id:int}',
        name='tag-delete',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_delete_tag(
        self,
        request: HTMXRequest,
        tag_id: FromPath[int],
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        with ConfigDatabase(True) as database:
            database.delete_stored_tag(tag_id)
        SharlyChessConfig().load_and_set_env()
        # The events that carried the tag keep the id, which no longer
        # resolves and is therefore ignored (and dropped when next saved).
        flat_data = WebContext.flatten_list_data(data)
        selected_tag_ids = [
            value
            for value in WebContext.form_data_to_list_str(flat_data, 'tags')
            if value != str(tag_id)
        ]
        flat_data['tags'] = ';'.join(selected_tag_ids)
        return self._render_tags_modal(web_context, flat_data)

    @classmethod
    def _enable_missing_plugins(cls, request: HTMXRequest, event_uniq_id: str):
        with EventDatabase(event_uniq_id) as database:
            stored_event = database.load_stored_event_metadata()
        for plugin in plugin_manager.enable_missing_plugins(
            stored_event.enabled_plugins
        ):
            Message.warning(
                request,
                _('Plugin [{plugin}] was enabled.').format(plugin=plugin.name),
            )

    @post(
        path='/event-import/{admin_tab:str}',
        name='event-import',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_event_import(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, Any], Body(media_type=RequestEncodingType.MULTI_PART)
        ],
        admin_tab: FromPath[str],
    ) -> Template | ClientRedirect:
        web_context = AdminWebContext(request, admin_tab)
        normalized_data = await WebContext.normalize_multipart_data(data)
        file_path = WebContext.form_data_to_path(normalized_data, 'file')
        assert file_path is not None
        suffix = '.' + Extension.EVENT_DB
        if file_path.suffix != suffix:
            error_message = _(
                'Invalid file extension [{extension}] (expected: {expected}).'
            ).format(extension=file_path.suffix, expected=suffix)
        elif not SQLiteDatabase(file_path).is_sqlite_file():
            error_message = _(
                'This file is incorrectly formatted, '
                'the extension has most likely been changed.'
            )
        else:
            try:
                event_uniq_id = EventLoader().import_event(file_path)
                self._enable_missing_plugins(request, event_uniq_id)
                Message.success(
                    request,
                    _('Event [{event}] has been imported.').format(event=event_uniq_id),
                )
                return ClientRedirect(admin_event_url(request, event_uniq_id))
            except Exception as error:
                logger.exception(error)
                if isinstance(error, SharlyChessException):
                    message = _(
                        "This event can't be used by the current version of Sharly Chess."
                    )
                else:
                    message = _('An unexpected error occurred.')
                error_message = message + ' ' + _('Consult the logs for more details.')
        Message.error(request, error_message)
        file_path.unlink(missing_ok=True)
        return self._admin_render(web_context)

    @get(
        path='/event-export-modal/{event_uniq_id:str}',
        name='event-export-modal',
        guards=[ActionGuard(AuthAction.MANAGE_EVENTS)],
    )
    async def htmx_admin_event_export_modal(self, request: HTMXRequest) -> Template:
        web_context = AdminWebContext(request)
        return HTMXTemplate(
            template_name='admin/modals.html',
            context=(
                web_context.template_context
                | {
                    'modal': 'event-export',
                    'data': WebContext.values_dict_to_form_data(
                        {
                            'include_players': True,
                            'include_private_player_data': False,
                            'include_connection_data': False,
                        }
                    ),
                    'errors': {},
                }
            ),
            re_target='#modal-wrapper',
        )

    @get(
        path='/event-export/{event_uniq_id:str}',
        name='admin-event-export',
    )
    async def admin_event_export(
        self,
        request: HTMXRequest,
        include_players: FromQuery[str | None] = None,
        include_private_player_data: FromQuery[str | None] = None,
        include_connection_data: FromQuery[str | None] = None,
    ) -> File | Template:
        web_context = AdminWebContext(request)
        event = web_context.get_admin_event()
        temp_file = NamedTemporaryFile(
            delete=False,
            mode='wb',
            suffix='.sce',
        )

        with EventDatabase(event.uniq_id, True) as database:
            shutil.copy(database.file.resolve(), temp_file.name)

        with EventDatabase(
            file_path=Path(temp_file.name), write=True, check_dirty_tournaments=False
        ) as tmp_event_database:
            # Tag ids are local to this installation, they would be
            # meaningless (or worse, wrong) anywhere else.
            tmp_event_database.delete_all_tags()
            if include_players != 'on':
                tmp_event_database.delete_all_stored_players()
            elif include_private_player_data != 'on':
                tmp_event_database.delete_players_personal_data()
            if include_connection_data != 'on':
                plugin_manager.hook.on_event_duplicated(
                    event_database=tmp_event_database
                )

        try:
            return File(
                path=temp_file.name,
                filename=database.file.resolve().name,
            )
        except Exception as exception:
            logger.exception(
                'Error when exporting event [%s]:\n%s',
                event.name,
                exception,
            )
            Message.error(
                request, _('An error occurred. Consult the logs for more details.')
            )
            return self.render_messages(request)

    @post(
        path='/restore-archive/{archive_name:str}',
        name='admin-restore-archive',
        guards=[ActionGuard(AuthAction.MANAGE_ARCHIVES)],
    )
    async def htmx_admin_restore_archive(
        self,
        request: HTMXRequest,
        archive_name: FromPath[str],
    ) -> Template:
        web_context = AdminWebContext(request, admin_tab='archives')
        archive = ArchiveLoader.get_archive(archive_name)
        if not archive:
            raise NotFoundException(f'Unknown archive [{archive_name}]')
        uniq_id = archive.restore()
        if uniq_id:
            self._enable_missing_plugins(request, uniq_id)
            Message.success(
                request,
                _(
                    'Archive [{archive}] successfully restored (see event [{event}]).'
                ).format(archive=archive.name, event=uniq_id),
            )
        else:
            Message.error(
                request,
                _(
                    'Archive [{archive}] could not be restored, '
                    'consult the logs for more details.'
                ).format(archive=archive.name),
            )
        return self._admin_render(web_context=web_context)

    @delete(
        path='/delete-archive/{archive_name:str}',
        name='admin-delete-archive',
        guards=[ActionGuard(AuthAction.MANAGE_ARCHIVES)],
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_delete_archive(
        self,
        request: HTMXRequest,
        archive_name: FromPath[str],
    ) -> Template:
        web_context = AdminWebContext(request, admin_tab='archives')
        archive = ArchiveLoader.get_archive(archive_name)
        if not archive:
            raise NotFoundException(f'Unknown archive [{archive_name}]')
        archive.file.unlink(missing_ok=True)
        Message.success(
            request,
            _('Archive [{archive}] successfully deleted.').format(archive=archive.name),
        )
        return self._admin_render(web_context=web_context)

    @patch(
        path='/locale-update/{locale:str}',
        name='admin-locale-update',
    )
    async def htmx_admin_locale_update(
        self, request: HTMXRequest, locale: FromPath[str]
    ) -> Template:
        web_context = AdminWebContext(request)
        sharly_chess_config: SharlyChessConfig = SharlyChessConfig()
        if locale in locales:
            stored_config: StoredConfig = sharly_chess_config.stored_config
            stored_config.locale = locale
            with ConfigDatabase(write=True) as config_database:
                config_database.update_stored_config(sharly_chess_config.stored_config)
            sharly_chess_config.load_and_set_env()
        return self._admin_render(web_context=web_context)

    def _config_modal_context(
        self,
        data: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        config = SharlyChessConfig()
        if data is None:
            data = WebContext.values_dict_to_form_data(
                {
                    'console_log_level': config.console_log_level,
                    'console_color': config.console_color,
                    'console_show_date': config.console_show_date,
                    'console_show_level': config.console_show_level,
                    'experimental': config.experimental,
                    'launch_browser': config.launch_browser,
                    'federation': config.stored_config.federation,
                    'locale': config.locale,
                    'date_formatter': config.date_formatter.id,
                }
            )

        for plugin in plugin_manager.all_plugins:
            if plugin.form_key not in data:
                data[plugin.form_key] = WebContext.value_to_form_data(plugin.is_enabled)

        if errors is None:
            errors = {}

        locale_options: dict[str, str] = {
            locale: locale_localized_name(locale) for locale in locales
        }

        global_plugins: list[Plugin] = []
        plugins_by_federation: dict[str | None, list[Plugin]] = defaultdict(list)

        for plugin in plugin_manager.all_plugins:
            federation = plugin.federation
            if federation:
                plugins_by_federation[federation].append(plugin)
            else:
                global_plugins.append(plugin)

        template_context = {
            'events_metadata': EventLoader.get_events_metadata(),
            'locale_options': locale_options,
            'global_plugins': global_plugins,
            'federation_plugins': plugins_by_federation,
            'federation_options': (
                {} if data['federation'] else {'': _('Please choose a federation')}
            )
            | self._get_federation_options(),
            'date_formatter_options': DateFormatterManager().options(),
            'modal': 'config',
            'data': data,
            'errors': errors,
        }

        return template_context

    @get(
        path='/config-modal',
        name='admin-config-modal',
        guards=[ActionGuard(AuthAction.MANAGE_APPLICATION_SETTINGS)],
    )
    async def htmx_admin_config_modal(self, request: HTMXRequest) -> Template:
        config = SharlyChessConfig()
        web_context = AdminWebContext(request)
        template_context = self._config_modal_context()
        return self._admin_render(
            web_context=web_context,
            template_context=template_context,
            keep_modal_open=config.force_edit,
        )

    @patch(
        path='/config-update',
        name='admin-config-update',
        guards=[ActionGuard(AuthAction.MANAGE_APPLICATION_SETTINGS)],
    )
    async def htmx_admin_config_update(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        stored_config: StoredConfig = self._admin_validate_config_update_data(data)
        stored_plugins: list[StoredPlugin] = self._admin_validate_plugins_update_data(
            data
        )
        errors = stored_config.errors
        if errors:
            template_context = self._config_modal_context(data, errors)
            sharly_chess_config: SharlyChessConfig = SharlyChessConfig()
            return self._admin_render(
                web_context=web_context,
                template_context=template_context,
                keep_modal_open=sharly_chess_config.force_edit,
            )
        with ConfigDatabase(write=True) as config_database:
            stored_config.force_edit = False
            config_database.update_stored_config(stored_config)
            for stored_plugin in stored_plugins:
                config_database.update_stored_plugin(stored_plugin)
        config = SharlyChessConfig()
        if config.locale != stored_config.locale:
            self.set_locale(request, stored_config.locale)
        config.load_and_set_env()
        Message.success(request, _('Sharly Chess settings have been updated.'))
        return self._render_empty_modal_and_messages(request, after_receive=True)

    @get(
        path='/database-status-badge',
        name='admin-database-status-badge',
        guards=[ActionGuard(AuthAction.MANAGE_SOURCE_DATABASES)],
    )
    async def htmx_admin_status_badge(
        self,
        request: HTMXRequest,
    ) -> Template:
        source_databases: list[LocalSourceDatabase] = (
            LocalSourceDatabaseManager().objects()
        )
        for database in source_databases:
            database.check()
            if database.update_status is not None:
                if database.update_status:
                    Message.success(
                        request,
                        _('Database [{database}] successfully updated.').format(
                            database=database.name
                        ),
                    )
                else:
                    Message.error(
                        request,
                        _('Error when updating database [{database}].').format(
                            database=database.name
                        ),
                    )
                database.__class__.update_status = None

        if any([database.is_updating for database in source_databases]):
            template_name = '/admin/common/database/updating_badge.html'
        elif any([database.outdated_warning for database in source_databases]):
            template_name = '/admin/common/database/out_of_date_badge.html'
        else:
            template_name = '/admin/common/database/settings_badge.html'
        return HTMXTemplate(
            template_name='/admin/common/database/database_badge_and_messages.html',
            context={
                'badge': template_name,
                'messages': Message.messages(request),
            },
        )

    @staticmethod
    def _database_modal_context() -> dict[str, Any]:
        return {
            'databases': LocalSourceDatabaseManager().objects(),
            'online_data_sources': OnlineDataSourceManager().objects(),
            'network_connected': NetworkMonitor.connected(),
            'outdate_delay_options': OutdatedDelayManager().options(),
            'outdate_action_options': OutdatedActionManager().options(),
            'modal': 'database',
        }

    @get(
        path='/database-modal',
        name='admin-database-modal',
        guards=[ActionGuard(AuthAction.MANAGE_SOURCE_DATABASES)],
    )
    async def htmx_admin_database_modal(self, request: HTMXRequest) -> Template:
        web_context = AdminWebContext(request)
        template_context = self._database_modal_context()
        return self._admin_render(
            web_context=web_context,
            template_context=template_context,
        )

    @patch(
        path='/database-options-update/{database_id:str}',
        name='admin-database-options-update',
        guards=[ActionGuard(AuthAction.MANAGE_SOURCE_DATABASES)],
    )
    async def _database_options_update(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        database_id: FromPath[str],
    ) -> Template:
        database = LocalSourceDatabaseManager().get_object(database_id)
        stored_database = database.stored_source_database
        delay: OutdatedDelay = DisabledOutdatedDelay()
        if delay_id := WebContext.form_data_to_str(data, 'outdate_delay'):
            delay = OutdatedDelayManager().get_object(delay_id)
        action: OutdatedAction = NotifOutdatedAction()
        if action_id := WebContext.form_data_to_str(data, 'outdate_action'):
            action = OutdatedActionManager().get_object(action_id)
        stored_database.outdate_delay = delay.id
        stored_database.outdate_action = action.id
        database.update_stored_source_database(stored_database)
        database.check()
        return HTMXTemplate(
            template_name='admin/common/database/database_row.html',
            context=self._database_modal_context() | {'database': database},
        )

    @get(
        path='/database-status/{database_id:str}',
        name='admin-database-status',
        guards=[ActionGuard(AuthAction.MANAGE_SOURCE_DATABASES)],
    )
    async def _database_update_status(self, database_id: FromPath[str]) -> Template:
        database = LocalSourceDatabaseManager().get_object(database_id)
        return HTMXTemplate(
            template_name='/admin/common/database/database_update_buttons.html',
            context={'database': database},
        )

    @post(
        path='/database-update/{database_id:str}',
        name='admin-database-update',
        guards=[ActionGuard(AuthAction.MANAGE_SOURCE_DATABASES)],
    )
    async def _database_update(self, database_id: FromPath[str]) -> Reswap:
        database = LocalSourceDatabaseManager().get_object(database_id)
        database.update()
        return Reswap(content=None, method='none', status_code=HTTP_200_OK)

    @delete(
        path='/database-delete/{database_id:str}',
        name='admin-database-delete',
        guards=[ActionGuard(AuthAction.MANAGE_SOURCE_DATABASES)],
        status_code=HTTP_200_OK,
    )
    async def _database_delete(self, database_id: FromPath[str]) -> Template:
        try:
            database = LocalSourceDatabaseManager().get_object(database_id)
            database.delete()
        except KeyError:
            raise NotFoundException(f'Unknown database [{database_id}].')
        return HTMXTemplate(
            template_name='/admin/common/database/database_update_buttons.html',
            context={'database': database},
        )

    @post(
        path='/online-data-source/check/{data_source_id:str}',
        name='admin-online-data-source-check',
        guards=[ActionGuard(AuthAction.MANAGE_SOURCE_DATABASES)],
    )
    async def htmx_admin_data_source_check(
        self,
        request: HTMXRequest,
        data_source_id: FromPath[str],
    ) -> Template:
        web_context = AdminWebContext(request)
        try:
            data_source = OnlineDataSourceManager().get_object(data_source_id)
            await data_source.reload_connection_status()
        except KeyError:
            raise NotFoundException(f'Unknown data source [{data_source_id}].')
        template_context = self._database_modal_context()
        return self._admin_render(
            web_context=web_context,
            template_context=template_context,
        )

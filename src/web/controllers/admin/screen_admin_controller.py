from typing import Annotated, Any

import requests
import validators
from litestar import post, get, delete, patch
from litestar.enums import RequestEncodingType
from litestar.exceptions import NotFoundException, ClientException
from litestar.params import Body, FromPath, FromQuery
from litestar.plugins.htmx import HTMXRequest
from litestar.response import Template
from litestar.status_codes import HTTP_200_OK
from litestar_htmx import HTMXTemplate

from common import REQUEST_TIMEOUT
from common.i18n import _
from common.sharly_chess_config import SharlyChessConfig
from data.access_levels.actions import AuthAction
from data.screens.screen import Screen
from data.screens.screen_set import ScreenSet
from data.screens.manager import ScreenTypeManager
from data.screens.screen_types import ScreenType
from utils import Utils
from utils.enum import BoardSelectionMode
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import StoredScreen, StoredScreenSet
from web.controllers.admin.base_event_admin_controller import (
    BaseEventAdminWebContext,
    BaseEventAdminController,
)
from web.controllers.admin.event_admin_controller import Redirect
from web.controllers.base_controller import WebContext
from web.guards import EventGuard, ActionGuard, ManageScreenEntityGuard
from web.messages import Message
from web.session import (
    SessionScreensShowFamilyScreens,
    SessionScreensShowDetails,
    SessionScreensScreenTypes,
)
from web.urls import admin_event_url

# A 2 MB image is ~2.8 MB once base64-encoded into a data: URI.
MAX_UPLOADED_IMAGE_CHARS = 2_800_000


class ScreenAdminWebContext(BaseEventAdminWebContext):
    def __init__(
        self,
        request: HTMXRequest,
        screen_id: int | None = None,
        screen_type_id: str | None = None,
        screen_set_id: int | None = None,
        reload_event: bool = False,
    ):
        super().__init__(request, reload_event)
        assert self.admin_event is not None
        self.admin_screen: Screen | None = None
        self.admin_screen_set: ScreenSet | None = None
        if screen_id:
            try:
                self.admin_screen = self.admin_event.basic_screens_by_id[screen_id]
            except KeyError:
                raise NotFoundException(f'Screen [{screen_id}] not found.')

        if screen_set_id:
            assert self.admin_screen is not None
            try:
                self.admin_screen_set = self.admin_screen.screen_sets_by_id[
                    screen_set_id
                ]
            except KeyError:
                raise NotFoundException(
                    f'Screen set [{screen_set_id}] not found for screen [{self.admin_screen.uniq_id}]'
                )

        # The raw type id (a built-in id or a plugin-defined one).
        self.screen_type_id: str | None = None
        if self.admin_screen:
            self.screen_type_id = self.admin_screen.type
        elif screen_type_id:
            if screen_type_id not in ScreenTypeManager(self.get_admin_event()).ids():
                raise NotFoundException(f'Unknown screen type [{screen_type_id}].')
            self.screen_type_id = screen_type_id

    def get_admin_screen(self) -> Screen:
        assert self.admin_screen is not None
        return self.admin_screen

    def get_admin_screen_set(self) -> ScreenSet:
        assert self.admin_screen_set is not None
        return self.admin_screen_set

    @property
    def screen_type(self) -> ScreenType | None:
        if self.screen_type_id is None:
            return None
        return ScreenTypeManager(self.get_admin_event()).get_object(self.screen_type_id)

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'admin_screen': self.admin_screen,
            'screen_type': self.screen_type,
            'admin_screen_set': self.admin_screen_set,
        }


class ScreenAdminRenderer(BaseEventAdminController):
    guards = [
        EventGuard(),
        ActionGuard(AuthAction.VIEW_PUBLIC_SCREENS),
    ]

    @classmethod
    def _admin_event_screens_render(
        cls,
        request: HTMXRequest,
        modal: str | None = None,
        action: str | None = None,
        screen_id: int | None = None,
        screen_type: str | None = None,
        screen_set_id: int | None = None,
        reload_event: bool = False,
        data: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
        scroll_to_screen_id: int | None = None,
    ) -> HTMXTemplate | Redirect:
        web_context = ScreenAdminWebContext(
            request,
            screen_id=screen_id,
            screen_type_id=screen_type,
            screen_set_id=screen_set_id,
            reload_event=reload_event,
        )
        event = web_context.get_admin_event()
        admin_screen_types_data: dict[ScreenType, dict[str, Any]] = {
            screen_type: {}
            for screen_type in ScreenTypeManager(event).objects()
            if screen_type.supports_event_type(event.event_type)
        }
        template_context: dict[str, Any] = web_context.template_context

        if web_context.client.can_manage_screens:
            # 'admin' view
            show_family_screens = SessionScreensShowFamilyScreens(request).get()
            sorted_screens_by_type: dict[str, list[Screen]]
            if show_family_screens:
                sorted_screens_by_type = event.sorted_screens_by_screen_type
            else:
                sorted_screens_by_type = event.sorted_basic_screens_by_screen_type
            for screen_type_ in list(admin_screen_types_data):
                screens = sorted_screens_by_type[screen_type_.id]
                admin_screen_types_data[screen_type_]['has_screen_sets'] = (
                    screen_type_.has_screen_sets
                )
                admin_screen_types_data[screen_type_]['screens'] = screens
                admin_screen_types_data[screen_type_]['title'] = (
                    f'{screen_type_.name} ({len(screens) or "-"})'
                )
            template_context |= {
                'admin_event_tab': 'admin-event-screens-tab',
                'admin_screen_types_data': admin_screen_types_data,
                'show_family_screens': show_family_screens,
                'show_details': SessionScreensShowDetails(request).get(),
                'admin_screens_screen_types': SessionScreensScreenTypes(request).get(),
                'admin_screens_count': sum(
                    len(data) for data in admin_screen_types_data.values()
                ),
                'scroll_to_screen_id': scroll_to_screen_id,
            }
        else:
            # 'user' view
            screen_type_obj = web_context.screen_type
            assert screen_type_obj is not None
            if web_context.client.can_view_private_screens:
                sorted_screens = event.sorted_screens_by_screen_type[screen_type_obj.id]
            else:
                sorted_screens = event.sorted_public_screens_by_screen_type[
                    screen_type_obj.id
                ]
            if not sorted_screens:
                return Redirect(admin_event_url(request, event_uniq_id=event.uniq_id))

            # setdefault: legacy screens of a type no longer offered for
            # the event's type still render rather than crash.
            admin_screen_type_data = admin_screen_types_data.setdefault(
                screen_type_obj, {}
            )
            admin_screen_type_data['screens'] = sorted_screens
            admin_screen_type_data['title'] = (
                f'{screen_type_obj.name} ({len(sorted_screens) or "-"})'
            )

            template_context |= {
                'admin_event_tab': f'admin-event-{screen_type_obj.id}-screens-tab',
                'admin_screen_type_data': admin_screen_type_data,
                'admin_screens_count': len(admin_screen_type_data['screens']),
            }

        match modal:
            case None:
                pass
            case 'screen':
                if data is None:
                    public: bool | None = None
                    name: str | None = None
                    columns: int | None = None
                    font_size: int | None = None
                    menu_text: str | None = None
                    timer_id: int | None = None
                    message_default: bool | None = None
                    message_text: str | None = None
                    init_set_tournament_id: int | None = None
                    # Type-specific form values, provided by the screen type.
                    type_values: dict[str, Any] = {}
                    match action:
                        case 'update':
                            stored_screen = web_context.get_admin_screen().stored_screen
                            assert stored_screen is not None
                            name = stored_screen.name
                        case 'create':
                            screen_type_obj = web_context.screen_type
                            assert screen_type_obj is not None
                            # Set-based screens open on a first tournament.
                            if screen_type_obj.has_screen_sets:
                                init_set_tournament_id = list(
                                    event.tournaments_by_id.keys()
                                )[0]
                            # No default name: an unnamed screen is named
                            # automatically from its tournament(s).
                        case 'clone':
                            screen = web_context.get_admin_screen()
                            name = event.get_unused_screen_name(
                                base_name=screen.name,
                                screen_type=screen.screen_type,
                            )
                        case 'delete':
                            pass
                        case _:
                            raise ValueError(f'action=[{action}]')
                    match action:
                        case 'update' | 'clone':
                            screen = web_context.get_admin_screen()
                            stored_screen = screen.stored_screen
                            assert stored_screen is not None
                            public = stored_screen.public
                            columns = stored_screen.columns
                            font_size = stored_screen.font_size
                            menu_text = stored_screen.menu_text
                            timer_id = stored_screen.timer_id
                            type_values = screen.screen_type.default_form_data(screen)
                            message_default = stored_screen.message_default
                            message_text = stored_screen.message_text
                        case 'create':
                            public = True
                            message_default = True
                            create_type = web_context.screen_type
                            assert create_type is not None
                            type_values = create_type.create_form_data(event)
                            columns = type_values.pop('columns', None)
                        case 'delete':
                            pass
                        case _:
                            raise ValueError(f'action=[{action}]')
                    form_values: dict[str, Any] = {
                        'public': public,
                        'name': name,
                        'columns': columns,
                        'font_size': font_size,
                        'menu_text': menu_text,
                        'timer_id': timer_id,
                        'message_text_checkbox': message_default,
                        'message_text': message_text,
                        'init_set_tournament_id': init_set_tournament_id,
                    }
                    form_values.update(type_values)
                    form_values['background_color_checkbox'] = (
                        form_values.get('background_color') is None
                    )
                    data = WebContext.values_dict_to_form_data(form_values)
                # Errors are only surfaced when passed in from a failed submit;
                # a freshly opened form must not show validation errors.
                if errors is None:
                    errors = {}
                template_context |= {
                    'tournament_options': web_context.get_tournament_options(),
                    'screen_type_options': cls._get_screen_type_options(
                        family_screens_only=False, event=event
                    ),
                    'timer_options': cls._get_timer_options(event),
                    'ranking_crosstable_options': cls._get_ranking_crosstable_options(),
                    'screen_uniq_ids': list(event.screens_by_uniq_id.keys()),
                    'players_player_format_options': web_context.get_players_screen_player_format_options(),
                    'players_board_format_options': web_context.get_players_screen_board_format_options(),
                    'players_opponent_format_options': web_context.get_players_screen_opponent_format_options(),
                    'modal': modal,
                    'action': action,
                    'data': data,
                    'errors': errors,
                }
            case 'screen_sets':
                template_context |= {
                    'modal': modal,
                }
            case 'screen_set_form':
                if data is None:
                    if action == 'update' and web_context.admin_screen_set:
                        stored_screen_set = (
                            web_context.admin_screen_set.stored_screen_set
                        )
                        assert stored_screen_set is not None
                        data = {
                            'tournament_id': WebContext.value_to_form_data(
                                stored_screen_set.tournament_id
                            ),
                            'fixed_boards_str': WebContext.value_to_form_data(
                                stored_screen_set.fixed_boards_str
                            ),
                            'name': WebContext.value_to_form_data(
                                stored_screen_set.name
                            ),
                            'first': WebContext.value_to_form_data(
                                stored_screen_set.first
                            ),
                            'last': WebContext.value_to_form_data(
                                stored_screen_set.last
                            ),
                            'fixed_board_order': WebContext.value_to_form_data(
                                stored_screen_set.fixed_board_order
                                or (
                                    BoardSelectionMode.SPECIFIC.value
                                    if stored_screen_set.fixed_boards_str is not None
                                    else BoardSelectionMode.PAIRING.value
                                )
                            ),
                        }
                    else:
                        data = {}
                if errors is None:
                    errors = {}
                template_context |= {
                    'tournament_options': web_context.get_tournament_options(),
                    'modal': modal,
                    'action': action,
                    'data': data,
                    'errors': errors,
                }
            case _:
                raise ValueError(f'modal=[{modal}]')
        return cls._admin_base_event_render(template_context)


class ScreenAdminController(ScreenAdminRenderer):
    guards = [
        EventGuard(),
        ActionGuard(AuthAction.VIEW_PUBLIC_SCREENS),
        ManageScreenEntityGuard('screen_id'),
    ]

    @classmethod
    def _admin_validate_screen_update_data(
        cls,
        action: str | None,
        web_context: ScreenAdminWebContext,
        data: dict[str, str] | None = None,
    ) -> StoredScreen:
        event = web_context.get_admin_event()
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        field: str
        type_: str
        init_set_tournament_id: int | None = None
        match action:
            case 'create':
                screen_type = web_context.screen_type
                assert screen_type is not None
                assert web_context.screen_type_id is not None
                type_ = web_context.screen_type_id
                if not screen_type.supports_event_type(event.event_type):
                    raise ValueError(
                        f'Screen type [{type_}] is not available for '
                        f'[{event.event_type}] events.'
                    )
                # Set-based screens open on a first tournament; standalone
                # ones (results, image) don't take one.
                if screen_type.has_screen_sets:
                    field = 'init_set_tournament_id'
                    init_set_tournament_id = WebContext.form_data_to_int(data, field)
                    if init_set_tournament_id not in event.tournaments_by_id:
                        errors[field] = _('Please choose the tournament.')
            case 'update' | 'clone' | 'delete':
                stored_screen = web_context.get_admin_screen().stored_screen
                assert stored_screen is not None
                type_ = stored_screen.type
            case _:
                raise ValueError(f'action=[{action}]')
        name: str | None = None
        public: bool | None = None
        menu_text: str | None = None
        columns: int | None = None
        font_size: int | None = None
        timer_id: int | None = None
        message_default: bool = True
        message_text: str | None = None
        # Type-specific StoredScreen fields, extracted by the screen type.
        type_values: dict[str, Any] = {}
        # Plugin-provided screen data, persisted into StoredScreen.plugin_data.
        plugin_data: dict[str, dict[str, Any]] = {}
        match action:
            case 'create' | 'clone' | 'update':
                name = WebContext.form_data_to_str(data, 'name') or ''
                public = WebContext.form_data_to_bool(data, 'public')
                field = 'columns'
                try:
                    columns = WebContext.form_data_to_int(data, field, minimum=1)
                except ValueError:
                    errors[field] = _('A positive integer is expected.')
                field = 'font_size'
                try:
                    font_size = WebContext.form_data_to_int(data, field, minimum=1)
                except ValueError:
                    errors[field] = _('A positive integer is expected.')
                menu_text = WebContext.form_data_to_str(data, 'menu_text', '')
                field = 'timer_id'
                try:
                    timer_id = WebContext.form_data_to_int(data, field)
                    if timer_id and timer_id not in event.timers_by_id:
                        errors[field] = _('Timer [{timer_id}] not found.').format(
                            timer_id=timer_id
                        )
                except ValueError:
                    errors[field] = _('A positive integer is expected.')
                screen_type = web_context.screen_type
                assert screen_type is not None
                type_values = screen_type.read_form_data(data, errors, event)
                for (
                    plugin_id,
                    plugin_data_class,
                ) in Screen.plugin_data_class_by_plugin_id().items():
                    previous_object = (
                        web_context.admin_screen.plugin_data.get(plugin_id)
                        if web_context.admin_screen
                        else None
                    )
                    plugin_data[plugin_id] = plugin_data_class.from_form_data(
                        data, action=action, previous_object=previous_object
                    ).to_stored_value()
                # The background image URL's format and reachability are checked
                # here since that is network I/O (kept out of the data layer).
                if 'background_image' in type_values:
                    field = 'background_image'
                    background_image = type_values[field]
                    if not background_image:
                        errors[field] = _('Please enter an image URL or upload a file.')
                    elif background_image.startswith('data:'):
                        # An uploaded image, stored inline in the event database.
                        if len(background_image) > MAX_UPLOADED_IMAGE_CHARS:
                            errors[field] = _(
                                'The uploaded image is too large (max 2 MB).'
                            )
                    elif not validators.url(background_image):
                        errors[field] = _('Invalid URL [{background_image}].').format(
                            background_image=background_image
                        )
                    else:
                        try:
                            response = requests.get(
                                background_image, timeout=REQUEST_TIMEOUT
                            )
                            if response.status_code != 200:
                                errors[field] = _(
                                    'URL [{url}] responded code [{code}].'
                                ).format(
                                    url=background_image, code=response.status_code
                                )
                        except requests.ConnectionError as ce:
                            errors[field] = _(
                                'URL [{url}] did not respond (error: [{error}]).'
                            ).format(url=background_image, error=str(ce))
                field = 'message_text'
                message_default = WebContext.form_data_to_bool(
                    data, field + '_checkbox'
                )
                if (
                    message_default
                    and web_context.admin_screen
                    and web_context.admin_screen.stored_screen
                ):
                    # do not change the original value when the default message is used
                    # (needed since disabled fields are not submitted)
                    message_text = web_context.admin_screen.stored_screen.message_text
                else:
                    message_text = WebContext.form_data_to_str(data, field)
                if action == 'update':
                    uniq_id = web_context.get_admin_screen().uniq_id
                else:
                    uniq_id = event.get_unused_screen_uniq_id(
                        web_context.screen_type,
                        Utils.name_to_uniq_id(name) if name else None,
                    )
            case 'delete':
                uniq_id = ''
            case _:
                raise ValueError(f'action=[{action}]')

        screen_id: int | None = None
        if web_context.admin_screen and action not in [
            'create',
            'clone',
        ]:
            screen_id = web_context.admin_screen.id

        return StoredScreen(
            id=screen_id,
            uniq_id=uniq_id,
            type=type_,
            public=bool(public),
            name=name,
            columns=columns,
            font_size=font_size,
            menu_text=menu_text,
            timer_id=timer_id,
            message_default=message_default,
            message_text=message_text,
            plugin_data=plugin_data,
            errors=errors,
            init_set_tournament_id=init_set_tournament_id,
            **type_values,
        )

    @staticmethod
    def _read_screen_set_form_data(
        web_context: ScreenAdminWebContext,
        data: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Validate the screen-set form. Returns a (values, errors) tuple: the
        values dict (tournament_id/name/first/last/fixed_boards_str) is None
        when validation failed."""
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        tournament_id: int | None = None
        name: str | None
        first: int | None = None
        last: int | None = None
        field = 'name'
        name = WebContext.form_data_to_str(data, field)
        field = 'tournament_id'

        event = web_context.get_admin_event()
        screen = web_context.get_admin_screen()
        try:
            if len(event.tournaments_by_id) == 1:
                tournament_id = list(event.tournaments_by_id.keys())[0]
                data[field] = WebContext.value_to_form_data(tournament_id)
            else:
                tournament_id = WebContext.form_data_to_int(data, field)
                if not tournament_id:
                    errors[field] = _('Please choose the tournament.')
                elif tournament_id not in event.tournaments_by_id:
                    errors[field] = _('Tournament [{tournament_id}] not found.').format(
                        tournament_id=tournament_id
                    )
        except ValueError:
            errors[field] = _('A positive integer is expected.')
        mode: BoardSelectionMode | None = None
        if screen.screen_type.supports_fixed_boards:
            mode_value = WebContext.form_data_to_str(data, 'fixed_board_order') or ''
            if mode_value and mode_value not in {m.value for m in BoardSelectionMode}:
                errors['fixed_board_order'] = _('Invalid value.')
            else:
                mode = (
                    BoardSelectionMode(mode_value)
                    if mode_value
                    else BoardSelectionMode.PAIRING
                )
        fixed_boards_str: str | None = None
        if mode == BoardSelectionMode.SPECIFIC:
            # Explicit board numbers; first/last are not used.
            fixed_boards_str = WebContext.form_data_to_str(data, 'fixed_boards_str')
            if fixed_boards_str:
                for fixed_board_str in map(str.strip, fixed_boards_str.split(',')):
                    if fixed_board_str:
                        try:
                            int(fixed_board_str)
                        except ValueError:
                            errors['fixed_boards_str'] = _(
                                'Invalid board number [{fixed_board_str}].'
                            ).format(fixed_board_str=fixed_board_str)
                            break
        else:
            # Range by first/last (pairing position or board number); any
            # explicit board list is cleared.
            field = 'first'
            try:
                first = WebContext.form_data_to_int(data, field, minimum=1)
            except ValueError:
                errors[field] = _('A positive integer is expected.')
            field = 'last'
            try:
                last = WebContext.form_data_to_int(data, field, minimum=1)
            except ValueError:
                errors[field] = _('A positive integer is expected.')
            if first and last and first > last:
                error: str = _(
                    'Numbers {first} and {last} are not compatible ({first} > {last}).'
                ).format(first=first, last=last)
                errors['first'] = error
                errors['last'] = error

        if errors:
            return None, errors

        assert tournament_id is not None
        return {
            'tournament_id': tournament_id,
            'name': name,
            'first': first,
            'last': last,
            'fixed_boards_str': fixed_boards_str,
            'fixed_board_order': mode.value if mode else None,
        }, errors

    @get(
        path='/event/{event_uniq_id:str}/screens',
        name='admin-event-screens-tab',
    )
    async def htmx_admin_event_screens_tab(
        self,
        request: HTMXRequest,
        show_family_screens: FromQuery[bool | None],
        show_details: FromQuery[bool | None],
    ) -> Template | Redirect:
        if show_family_screens is not None:
            SessionScreensShowFamilyScreens(request).set(show_family_screens)
        if show_details is not None:
            SessionScreensShowDetails(request).set(show_details)
        # The expand/collapse of each type's section is posted as
        # ``admin_screens_show_<type_id>`` — read generically so any screen
        # type (including plugin-defined ones) is handled.
        prefix = 'admin_screens_show_'
        screen_types = SessionScreensScreenTypes(request).get()
        changed = False
        for key, raw in request.query_params.items():
            if not key.startswith(prefix):
                continue
            type_id = key[len(prefix) :]
            if raw in ('true', 'on', '1'):
                screen_types.add(type_id)
            else:
                screen_types.discard(type_id)
            changed = True
        if changed:
            SessionScreensScreenTypes(request).set(screen_types)
        return self._admin_event_screens_render(request)

    @get(
        path='/screen-modal/create/{event_uniq_id:str}/{screen_type:str}',
        name='admin-screen-create-modal',
    )
    async def htmx_admin_screen_create_modal(
        self,
        request: HTMXRequest,
        screen_type: FromPath[str],
    ) -> Template | Redirect:
        return self._admin_event_screens_render(
            request,
            modal='screen',
            action='create',
            screen_id=None,
            screen_type=screen_type,
        )

    @get(
        path='/screen-modal/{action:str}/{event_uniq_id:str}/{screen_id:int}',
        name='admin-screen-modal',
    )
    async def htmx_admin_screen_modal(
        self,
        request: HTMXRequest,
        action: FromPath[str],
        screen_id: FromPath[int | None],
    ) -> Template | Redirect:
        return self._admin_event_screens_render(
            request,
            modal='screen',
            action=action,
            screen_id=screen_id,
        )

    @staticmethod
    def _expand_screen_type_section(request: HTMXRequest, screen_type: str) -> None:
        screen_types = SessionScreensScreenTypes(request).get()
        screen_types.add(screen_type)
        SessionScreensScreenTypes(request).set(screen_types)

    def _admin_screen_update(
        self,
        request: HTMXRequest,
        action: str,
        screen_id: int | None,
        screen_type: str | None,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template | Redirect:
        assert screen_id is not None or screen_type is not None
        match action:
            case 'update' | 'delete' | 'clone' | 'create':
                web_context = ScreenAdminWebContext(
                    request,
                    screen_id=screen_id,
                    screen_type_id=screen_type,
                )
            case _:
                raise ValueError(f'action=[{action}]')

        event = web_context.get_admin_event()
        stored_screen: StoredScreen = self._admin_validate_screen_update_data(
            action, web_context, data
        )
        if stored_screen.errors:
            return self._admin_event_screens_render(
                request,
                modal='screen',
                action=action,
                screen_id=screen_id,
                screen_type=screen_type,
                data=data,
                errors=stored_screen.errors,
            )
        scroll_to_screen_id: int | None = None
        with EventDatabase(event.uniq_id, write=True) as event_database:
            match action:
                case 'create':
                    # init_set_tournament_id is the id of the tournament that should be
                    # used to create the default screen_set.
                    # It is set in the screen creation form.
                    # It needs to be saved because EventDatabase.add_stored_screen()
                    # doesn't save it (it is not stored in the database).
                    init_set_tournament_id: int | None = (
                        stored_screen.init_set_tournament_id
                    )
                    stored_screen = event_database.add_stored_screen(stored_screen)
                    assert stored_screen.id is not None
                    self._expand_screen_type_section(request, stored_screen.type)
                    scroll_to_screen_id = stored_screen.id
                    if (
                        ScreenTypeManager(event)
                        .get_object(stored_screen.type)
                        .has_screen_sets
                    ):
                        if init_set_tournament_id is None:
                            raise RuntimeError(
                                'Missing data: not able to create default screen set'
                            )
                        event_database.add_stored_screen_set(
                            stored_screen.id, init_set_tournament_id
                        )
                    Message.success(
                        request,
                        _('Screen [{screen_uniq_id}] has been created.').format(
                            screen_uniq_id=stored_screen.uniq_id
                        ),
                    )
                case 'clone':
                    screen = web_context.get_admin_screen()
                    stored_screen = event_database.add_stored_screen(stored_screen)
                    assert stored_screen.id is not None
                    self._expand_screen_type_section(request, stored_screen.type)
                    scroll_to_screen_id = stored_screen.id
                    if (
                        ScreenTypeManager(event)
                        .get_object(stored_screen.type)
                        .has_screen_sets
                    ):
                        for screen_set in screen.sorted_screen_sets:
                            assert screen_set.id is not None
                            event_database.clone_stored_screen_set(
                                screen_set.id, stored_screen.id
                            )
                    Message.success(
                        request,
                        _('Screen [{screen_uniq_id}] has been created.').format(
                            screen_uniq_id=stored_screen.uniq_id
                        ),
                    )
                case 'update':
                    stored_screen = event_database.update_stored_screen(stored_screen)
                    assert stored_screen.id is not None
                    scroll_to_screen_id = stored_screen.id
                    Message.success(
                        request,
                        _('Screen [{screen_uniq_id}] has been updated.').format(
                            screen_uniq_id=stored_screen.uniq_id
                        ),
                    )
                case 'delete':
                    screen = web_context.get_admin_screen()
                    event_database.delete_stored_screen(screen.id)
                    Message.success(
                        request,
                        _('Screen [{screen_uniq_id}] has been deleted.').format(
                            screen_uniq_id=screen.uniq_id
                        ),
                    )
                case _:
                    raise ValueError(f'action=[{action}]')

        return self._admin_event_screens_render(
            request, reload_event=True, scroll_to_screen_id=scroll_to_screen_id
        )

    @post(
        path='/screen-create/{event_uniq_id:str}/{screen_type:str}',
        name='admin-screen-create',
        guards=[ActionGuard(AuthAction.MANAGE_SCREENS)],
    )
    async def htmx_admin_screen_create(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        screen_type: FromPath[str],
    ) -> Template | Redirect:
        return self._admin_screen_update(
            request,
            action='create',
            screen_id=None,
            screen_type=screen_type,
            data=WebContext.flatten_list_data(data),
        )

    @post(
        path='/screen-clone/{event_uniq_id:str}/{screen_id:int}',
        name='admin-screen-clone',
    )
    async def htmx_admin_screen_clone(
        self,
        request: HTMXRequest,
        screen_id: FromPath[int],
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template | Redirect:
        return self._admin_screen_update(
            request,
            action='clone',
            screen_id=screen_id,
            screen_type=None,
            data=WebContext.flatten_list_data(data),
        )

    @patch(
        path='/screen-update/{event_uniq_id:str}/{screen_id:int}',
        name='admin-screen-update',
    )
    async def htmx_admin_screen_update(
        self,
        request: HTMXRequest,
        screen_id: FromPath[int],
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template | Redirect:
        return self._admin_screen_update(
            request,
            action='update',
            screen_id=screen_id,
            screen_type=None,
            data=WebContext.flatten_list_data(data),
        )

    @patch(
        path='/screen-uniq-id-update/{event_uniq_id:str}/{screen_id:int}',
        name='admin-screen-uniq-id-update',
    )
    async def htmx_admin_screen_uniq_id_update(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        screen_id: FromPath[int],
    ) -> HTMXTemplate:
        web_context = ScreenAdminWebContext(request, screen_id)
        event = web_context.get_admin_event()
        screen = web_context.get_admin_screen()
        new_uniq_id = WebContext.form_data_to_str(data, 'uniq_id')
        if (
            not new_uniq_id
            or not SharlyChessConfig.uniq_id_regex.match(new_uniq_id)
            or (
                new_uniq_id != screen.uniq_id
                and new_uniq_id in event.screens_by_uniq_id.keys()
            )
        ):
            # No precise error (validated in JS)
            raise ClientException(f'Invalid uniq ID [{new_uniq_id}].')
        stored_screen = screen.stored_screen
        assert stored_screen is not None
        stored_screen.uniq_id = new_uniq_id
        with EventDatabase(event.uniq_id, True) as database:
            database.update_stored_screen(stored_screen)

        web_context = ScreenAdminWebContext(request, screen_id, reload_event=True)
        event = web_context.get_admin_event()
        return HTMXTemplate(
            template_name='/admin/screens/screen_update_modal_header.html',
            context=web_context.template_context
            | {
                'screen_uniq_ids': list(event.screens_by_uniq_id.keys()),
                'oob_eye_link': True,
            },
            re_swap='innerHTML',
            re_target='.modal-header',
        )

    @delete(
        path='/screen-delete/{event_uniq_id:str}/{screen_id:int}',
        name='admin-screen-delete',
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_screen_delete(
        self,
        request: HTMXRequest,
        screen_id: FromPath[int],
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template | Redirect:
        return self._admin_screen_update(
            request,
            action='delete',
            screen_id=screen_id,
            screen_type=None,
            data=data,
        )

    @get(
        path='/screen-sets-modal/{event_uniq_id:str}/{screen_id:int}',
        name='admin-screen-sets-modal',
    )
    async def htmx_admin_screen_sets_modal(
        self,
        request: HTMXRequest,
        screen_id: FromPath[int],
    ) -> Template | Redirect:
        return self._admin_event_screens_render(
            request,
            modal='screen_sets',
            screen_id=screen_id,
            screen_set_id=None,
        )

    @get(
        path='/screen-set-modal/create/{event_uniq_id:str}/{screen_id:int}',
        name='admin-screen-set-create-modal',
    )
    async def htmx_admin_screen_set_create_modal(
        self,
        request: HTMXRequest,
        screen_id: FromPath[int],
    ) -> Template | Redirect:
        return self._admin_event_screens_render(
            request,
            modal='screen_set_form',
            action='create',
            screen_id=screen_id,
            screen_set_id=None,
        )

    @get(
        path='/screen-set-modal/update/{event_uniq_id:str}/{screen_id:int}/{screen_set_id:int}',
        name='admin-screen-set-update-modal',
    )
    async def htmx_admin_screen_set_update_modal(
        self,
        request: HTMXRequest,
        screen_id: FromPath[int],
        screen_set_id: FromPath[int],
    ) -> Template | Redirect:
        return self._admin_event_screens_render(
            request,
            modal='screen_set_form',
            action='update',
            screen_id=screen_id,
            screen_set_id=screen_set_id,
        )

    def _admin_screen_sets_update(
        self,
        request: HTMXRequest,
        screen_id: int,
        screen_set_id: int | None,
        action: str,
        data: Annotated[
            dict[str, Any],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template | Redirect:
        match action:
            case 'delete' | 'clone' | 'create' | 'update' | 'reorder':
                web_context: ScreenAdminWebContext = ScreenAdminWebContext(
                    request,
                    screen_id=screen_id,
                    screen_set_id=screen_set_id,
                )
            case _:
                raise ValueError(f'action=[{action}]')
        event = web_context.get_admin_event()
        screen = web_context.get_admin_screen()
        if action == 'delete' and len(screen.sorted_screen_sets) <= 1:
            raise ClientException('The last set of a screen can not be deleted.')
        with EventDatabase(event.uniq_id, write=True) as event_database:
            match action:
                case 'create' | 'update':
                    values, errors = self._read_screen_set_form_data(web_context, data)
                    if values is None:
                        return self._admin_event_screens_render(
                            request,
                            modal='screen_set_form',
                            action=action,
                            screen_id=screen_id,
                            screen_set_id=screen_set_id,
                            data=data,
                            errors=errors,
                        )
                    if action == 'create':
                        stored_screen_set: StoredScreenSet = (
                            event_database.add_stored_screen_set(
                                screen.id, values['tournament_id']
                            )
                        )
                    else:
                        existing = web_context.get_admin_screen_set().stored_screen_set
                        assert existing is not None
                        stored_screen_set = existing
                        stored_screen_set.tournament_id = values['tournament_id']
                    stored_screen_set.name = values['name']
                    stored_screen_set.first = values['first']
                    stored_screen_set.last = values['last']
                    stored_screen_set.fixed_boards_str = values['fixed_boards_str']
                    stored_screen_set.fixed_board_order = values['fixed_board_order']
                    event_database.update_stored_screen_set(stored_screen_set)
                case 'delete':
                    screen_set = web_context.get_admin_screen_set()
                    assert screen_set.id is not None
                    event_database.delete_stored_screen_set(screen_set.id, screen.id)
                case 'clone':
                    screen_set = web_context.get_admin_screen_set()
                    assert screen_set.id is not None
                    event_database.clone_stored_screen_set(screen_set.id, screen.id)
                case 'reorder':
                    event_database.reorder_stored_screen_sets(screen.id, data['item'])
                case _:
                    raise ValueError(f'action=[{action}]')

        return self._admin_event_screens_render(
            request,
            modal='screen_sets',
            screen_id=screen_id,
            screen_set_id=None,
            reload_event=True,
        )

    @post(
        path='/screen-set-create/{event_uniq_id:str}/{screen_id:int}',
        name='admin-screen-set-create',
    )
    async def htmx_admin_screen_set_create(
        self,
        request: HTMXRequest,
        screen_id: FromPath[int],
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template | Redirect:
        return self._admin_screen_sets_update(
            request,
            action='create',
            screen_id=screen_id,
            screen_set_id=None,
            data=data,
        )

    @post(
        path='/screen-set-clone/{event_uniq_id:str}/{screen_id:int}/{screen_set_id:int}',
        name='admin-screen-set-clone',
    )
    async def htmx_admin_screen_set_clone(
        self,
        request: HTMXRequest,
        screen_id: FromPath[int],
        screen_set_id: FromPath[int],
        data: Annotated[
            dict[str, str | list[int]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template | Redirect:
        return self._admin_screen_sets_update(
            request,
            action='clone',
            screen_id=screen_id,
            screen_set_id=screen_set_id,
            data=data,
        )

    @patch(
        path='/screen-set-update/{event_uniq_id:str}/{screen_id:int}/{screen_set_id:int}',
        name='admin-screen-set-update',
    )
    async def htmx_admin_screen_set_update(
        self,
        request: HTMXRequest,
        screen_id: FromPath[int],
        screen_set_id: FromPath[int],
        data: Annotated[
            dict[str, str | list[int]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template | Redirect:
        return self._admin_screen_sets_update(
            request,
            action='update',
            screen_id=screen_id,
            screen_set_id=screen_set_id,
            data=data,
        )

    @delete(
        path='/screen-set-delete/{event_uniq_id:str}/{screen_id:int}/{screen_set_id:int}',
        name='admin-screen-set-delete',
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_screen_set_delete(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[int]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        screen_id: FromPath[int],
        screen_set_id: FromPath[int],
    ) -> Template | Redirect:
        return self._admin_screen_sets_update(
            request,
            action='delete',
            screen_id=screen_id,
            screen_set_id=screen_set_id,
            data=data,
        )

    @patch(
        path='/screen-reorder-sets/{event_uniq_id:str}/{screen_id:int}',
        name='admin-screen-reorder-sets',
    )
    async def htmx_admin_screen_reorder_sets(
        self,
        request: HTMXRequest,
        screen_id: FromPath[int],
        data: Annotated[
            dict[str, str | list[int]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template | Redirect:
        return self._admin_screen_sets_update(
            request,
            action='reorder',
            screen_id=screen_id,
            screen_set_id=None,
            data=data,
        )

    @get(
        path='/event/{event_uniq_id:str}/input-screens',
        name='admin-event-input-screens-tab',
    )
    async def htmx_admin_event_input_screens_tab(
        self, request: HTMXRequest
    ) -> Template | Redirect:
        return self._admin_event_screens_render(request, screen_type='input')

    @get(
        path='/event/{event_uniq_id:str}/check-in-screens',
        name='admin-event-check-in-screens-tab',
    )
    async def htmx_admin_event_check_in_screens_tab(
        self, request: HTMXRequest
    ) -> Template | Redirect:
        return self._admin_event_screens_render(request, screen_type='check-in')

    @get(
        path='/event/{event_uniq_id:str}/boards-screens',
        name='admin-event-boards-screens-tab',
    )
    async def htmx_admin_event_boards_screens_tab(
        self, request: HTMXRequest
    ) -> Template | Redirect:
        return self._admin_event_screens_render(request, screen_type='boards')

    @get(
        path='/event/{event_uniq_id:str}/players-screens',
        name='admin-event-players-screens-tab',
    )
    async def htmx_admin_event_players_screens_tab(
        self, request: HTMXRequest
    ) -> Template | Redirect:
        return self._admin_event_screens_render(request, screen_type='players')

    @get(
        path='/event/{event_uniq_id:str}/results-screens',
        name='admin-event-results-screens-tab',
    )
    async def htmx_admin_event_results_screens_tab(
        self, request: HTMXRequest
    ) -> Template | Redirect:
        return self._admin_event_screens_render(request, screen_type='results')

    @get(
        path='/event/{event_uniq_id:str}/ranking-screens',
        name='admin-event-ranking-screens-tab',
    )
    async def htmx_admin_event_ranking_screens_tab(
        self, request: HTMXRequest
    ) -> Template | Redirect:
        return self._admin_event_screens_render(request, screen_type='ranking')

    @get(
        path='/event/{event_uniq_id:str}/image-screens',
        name='admin-event-image-screens-tab',
    )
    async def htmx_admin_event_image_screens_tab(
        self, request: HTMXRequest
    ) -> Template | Redirect:
        return self._admin_event_screens_render(request, screen_type='image')

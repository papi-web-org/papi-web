from logging import Logger
from typing import Annotated, Any

from litestar import post
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, Reswap
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.status_codes import HTTP_304_NOT_MODIFIED

from common.exception import PapiWebException
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import Event
from data.loader import EventLoader
from data.rotator import Rotator
from data.screen import Screen
from web.messages import Message
from web.session import SessionHandler
from web.controllers.index_controller import AbstractController, WebContext

logger: Logger = get_logger()


class UserWebContext(WebContext):
    """
    The basic user web context, where parameters user_main_selector and user_event_selector are expected and passed
    to the template engine to propagate the context.
    """

    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_needed: bool = False,
    ):
        super().__init__(request, data)
        self.user_main_selector: str = ''
        self.user_event_selector: str = ''
        self.user_event: Event | None = None
        if self.error:
            return
        self.user_main_selector: str = self._form_data_to_str('user_main_selector')
        if not self.user_main_selector:
            pass
        elif self.user_main_selector.startswith('@'):
            pass
        else:
            try:
                self.user_event = EventLoader.get(request=self.request, lazy_load=False).load_event(
                    self.user_main_selector)
                if not self.user_event.public and not self.admin_auth:
                    self._redirect_error(f'L\'évènement [{self.user_event.uniq_id}] est privé.')
                    self.user_main_selector = ''
                    self.user_event = None
                    return
            except PapiWebException as pwe:
                self._redirect_error(f'L\'évènement [{self.user_main_selector}] est introuvable : {pwe}')
                self.user_main_selector = ''
                self.user_event = None
                return
        if event_needed and not self.user_event:
            self._redirect_error(f'L\'évènement n\'est pas spécifie')
            return
        self.user_event_selector: str = self._form_data_to_str('user_event_selector')

    @property
    def background_color(self) -> str:
        return PapiWebConfig.user_background_color

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'user_main_selector': self.user_main_selector,
            'user_event_selector': self.user_event_selector,
            'user_event': self.user_event,
        }


class EventUserWebContext(UserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ):
        super().__init__(request, data, True)
        if self.error:
            return

    @property
    def background_image(self) -> str:
        return ''

    @property
    def background_color(self) -> str:
        return PapiWebConfig.default_background_color


class AbstractUserController(AbstractController):

    @staticmethod
    def _user_render_index(
            web_context: UserWebContext,
    ) -> Template:
        if web_context.user_event:
            input_screens: list[Screen]
            boards_screens: list[Screen]
            players_screens: list[Screen]
            results_screens: list[Screen]
            image_screens: list[Screen]
            rotators: list[Rotator]
            if web_context.admin_auth:
                input_screens = web_context.user_event.input_screens_sorted_by_uniq_id
                boards_screens = web_context.user_event.boards_screens_sorted_by_uniq_id
                players_screens = web_context.user_event.players_screens_sorted_by_uniq_id
                results_screens = web_context.user_event.results_screens_sorted_by_uniq_id
                image_screens = web_context.user_event.image_screens_sorted_by_uniq_id
                rotators = web_context.user_event.rotators_sorted_by_uniq_id
            else:
                input_screens = web_context.user_event.public_input_screens_sorted_by_uniq_id
                boards_screens = web_context.user_event.public_boards_screens_sorted_by_uniq_id
                players_screens = web_context.user_event.public_players_screens_sorted_by_uniq_id
                results_screens = web_context.user_event.public_results_screens_sorted_by_uniq_id
                image_screens = web_context.user_event.public_image_screens_sorted_by_uniq_id
                rotators = web_context.user_event.public_rotators_sorted_by_uniq_id
            nav_tabs: dict[str, dict] = {
                'input': {
                    'title': f'Saisie des résultats ({len(input_screens) or "-"})',
                    'screens': input_screens,
                    'disabled': not input_screens,
                },
                'boards': {
                    'title': f'Appariements par échiquier ({len(boards_screens) or "-"})',
                    'screens': boards_screens,
                    'disabled': not boards_screens,
                },
                'players': {
                    'title': f'Appariements par ordre alphabétique ({len(players_screens) or "-"})',
                    'screens': players_screens,
                    'disabled': not players_screens,
                },
                'results': {
                    'title': f'Derniers résultats ({len(results_screens) or "-"})',
                    'screens': results_screens,
                    'disabled': not results_screens,
                },
                'image': {
                    'title': f'Image ({len(image_screens) or "-"})',
                    'screens': image_screens,
                    'disabled': not image_screens,
                },
                'rotators': {
                    'title': f'Écrans rotatifs ({len(rotators) or "-"})',
                    'rotators': rotators,
                    'disabled': not rotators,
                },
            }
            if not web_context.user_event_selector or nav_tabs[web_context.user_event_selector]['disabled']:
                web_context.user_event_selector = list(nav_tabs.keys())[0]
            for nav_index in range(len(nav_tabs)):
                if web_context.user_event_selector == list(nav_tabs.keys())[nav_index] \
                        and nav_tabs[web_context.user_event_selector]['disabled']:
                    web_context.user_event_selector = list(nav_tabs.keys())[(nav_index + 1) % len(nav_tabs)]
        else:
            event_loader: EventLoader = EventLoader.get(request=web_context.request, lazy_load=True)
            current_events: list[Event]
            coming_events: list[Event]
            passed_events: list[Event]
            if web_context.admin_auth:
                current_events = event_loader.current_events
                coming_events = event_loader.coming_events
                passed_events = event_loader.passed_events
            else:
                current_events = event_loader.current_public_events
                coming_events = event_loader.coming_public_events
                passed_events = event_loader.passed_public_events
            nav_tabs: dict[str, dict] = {
                '@current_events': {
                    'title': f'Évènements en cours ({len(current_events) or "-"})',
                    'events': current_events,
                    'empty_str': 'Aucun évènement en cours.',
                    'class': 'bg-primary-subtle',
                    'icon_class': 'bi-calendar',
                    'disabled': not current_events,
                },
                '@coming_events': {
                    'title': f'Évènements à venir ({len(coming_events) or "-"})',
                    'events': coming_events,
                    'empty_str': 'Aucun évènement à venir.',
                    'class': 'bg-info-subtle',
                    'icon_class': 'bi-calendar-check',
                    'disabled': not coming_events,
                },
                '@passed_events': {
                    'title': f'Évènements passés ({len(passed_events) or "-"})',
                    'events': passed_events,
                    'empty_str': 'Aucun évènement passé.',
                    'class': 'bg-secondary-subtle',
                    'icon_class': 'bi-calendar-minus',
                    'disabled': not passed_events,
                },
            }
            if not web_context.user_main_selector or nav_tabs[web_context.user_main_selector]['disabled']:
                web_context.user_main_selector = list(nav_tabs.keys())[0]
            for nav_index in range(len(nav_tabs)):
                if web_context.user_main_selector == list(nav_tabs.keys())[nav_index] \
                        and nav_tabs[web_context.user_main_selector]['disabled']:
                    web_context.user_main_selector = list(nav_tabs.keys())[(nav_index + 1) % len(nav_tabs)]
        return HTMXTemplate(
            template_name="user.html",
            context=web_context.template_context | {
                'messages': Message.messages(web_context.request),
                'user_columns': SessionHandler.get_session_user_columns(web_context.request),
                'nav_tabs': nav_tabs,
            })


class IndexUserController(AbstractUserController):

    @staticmethod
    def _user_index_update_needed(
            request: HTMXRequest,
            date: float, ) -> bool:
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        for public_event in event_loader.public_events:
            web_context: EventUserWebContext = EventUserWebContext(
                request, {'user_main_selector': public_event.uniq_id, })
            if web_context.error:
                return False
            if web_context.user_event.last_update > date:
                return True
            for tournament in web_context.user_event.tournaments_by_id.values():
                if tournament.last_update > date:
                    return True
        return False

    @post(
        path='/user-render-if-updated',
        name='user-render-if-updated',
    )
    async def htmx_user_render_index_if_updated(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Reswap | Redirect:
        try:
            date: float = WebContext.form_data_to_float(data, 'date', 0.0)
        except ValueError as ve:
            return AbstractController.redirect_error(request, ve)
        if date <= 0.0:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)  # timer is hanged
        if self._user_index_update_needed(request, date):
            web_context: UserWebContext = UserWebContext(request, data, False)
            return self._user_render_index(web_context)
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

    @post(
        path='/user-render',
        name='user-render',
    )
    async def htmx_user_render_index(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        web_context: UserWebContext = UserWebContext(request, data, False)
        return self._user_render_index(web_context)

    @post(
        path='/user-update-header',
        name='user-update-header'
    )
    async def htmx_user_update_header(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        web_context: UserWebContext = UserWebContext(request, data, True)
        if web_context.error:
            return web_context.error
        field: str = f'user_columns'
        if field in data:
            SessionHandler.set_session_user_columns(request, WebContext.form_data_to_int(data, field))
        return self._user_render_index(web_context)

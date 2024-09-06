import time

from logging import Logger
from typing import Annotated

from litestar import get, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.status_codes import HTTP_304_NOT_MODIFIED
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, Reswap

from common.exception import PapiWebException
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import NewEvent
from data.family import NewFamily
from data.loader import EventLoader
from data.rotator import NewRotator
from data.screen import NewScreen
from data.tournament import NewTournament
from web.messages import Message
from web.session import SessionHandler
from web.views import AController, WebContext

logger: Logger = get_logger()


class UserWebContext(WebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
            event_needed: bool = False,
    ):
        super().__init__(request, data)
        self.user_main_selector: str = ''
        self.user_event_selector: str = ''
        self.user_event: NewEvent | None = None
        if self.error:
            return
        self.user_main_selector: str = self._form_data_to_str('user_main_selector')
        if not self.user_main_selector:
            pass
        elif self.user_main_selector.startswith('@'):
            pass
        else:
            try:
                self.user_event = EventLoader.get(request=self.request, lazy_load=lazy_load).load_event(
                    self.user_main_selector)
                if not self.user_event.public:
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


class EventUserWebContext(UserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data, lazy_load, True)
        if self.error:
            return


class AUserController(AController):

    @staticmethod
    def _user_render_index(
            web_context: UserWebContext,
    ) -> Template:
        if web_context.user_event:
            nav_tabs: dict[str, dict] = {
                'input': {
                    'title': f'Saisie des résultats '
                             f'({len(web_context.user_event.public_input_screens_sorted_by_uniq_id) or "-"})',
                    'screens': web_context.user_event.public_input_screens_sorted_by_uniq_id,
                    'disabled': not web_context.user_event.public_input_screens_sorted_by_uniq_id,
                },
                'boards': {
                    'title': f'Affichage des échiquiers '
                             f'({len(web_context.user_event.public_boards_screens_sorted_by_uniq_id) or "-"})',
                    'screens': web_context.user_event.public_boards_screens_sorted_by_uniq_id,
                    'disabled': not web_context.user_event.public_boards_screens_sorted_by_uniq_id,
                },
                'players': {
                    'title': f'Affichage des appariements par ordre alphabétique '
                             f'({len(web_context.user_event.public_players_screens_sorted_by_uniq_id) or "-"})',
                    'screens': web_context.user_event.public_players_screens_sorted_by_uniq_id,
                    'disabled': not web_context.user_event.public_players_screens_sorted_by_uniq_id,
                },
                'results': {
                    'title': f'Affichage des résultats '
                             f'({len(web_context.user_event.public_results_screens_sorted_by_uniq_id) or "-"})',
                    'screens': web_context.user_event.public_results_screens_sorted_by_uniq_id,
                    'disabled': not web_context.user_event.public_results_screens_sorted_by_uniq_id,
                },
                'rotators': {
                    'title': f'Écrans rotatifs '
                             f'({len(web_context.user_event.public_rotators_sorted_by_uniq_id) or "-"})',
                    'rotators': web_context.user_event.public_rotators_sorted_by_uniq_id,
                    'disabled': not web_context.user_event.public_rotators_sorted_by_uniq_id,
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
            nav_tabs: dict[str, dict] = {
                '@current_events': {
                    'title': f'Évènements en cours ({len(event_loader.current_public_events) or "-"})',
                    'events': event_loader.current_public_events,
                    'empty_str': 'Aucun évènement en cours.',
                    'class': 'bg-primary-subtle',
                    'icon_class': 'bi-calendar',
                    'disabled': not event_loader.current_public_events,
                },
                '@coming_events': {
                    'title': f'Évènements à venir ({len(event_loader.coming_public_events) or "-"})',
                    'events': event_loader.coming_public_events,
                    'empty_str': 'Aucun évènement à venir.',
                    'class': 'bg-info-subtle',
                    'icon_class': 'bi-calendar-check',
                    'disabled': not event_loader.coming_public_events,
                },
                '@passed_events': {
                    'title': f'Évènements passés ({len(event_loader.passed_public_events) or "-"})',
                    'events': event_loader.passed_public_events,
                    'empty_str': 'Aucun évènement passé.',
                    'class': 'bg-secondary-subtle',
                    'icon_class': 'bi-calendar-minus',
                    'disabled': not event_loader.passed_public_events,
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
            context={
                'papi_web_config': PapiWebConfig(),
                'user_main_selector': web_context.user_main_selector,
                'user_event_selector': web_context.user_event_selector,
                'user_event': web_context.user_event,
                'messages': Message.messages(web_context.request),
                'now': time.time(),
                'user_columns': SessionHandler.get_session_user_columns(web_context.request),
                'nav_tabs': nav_tabs,
            })


class UserIndexController(AUserController):

    @staticmethod
    def _user_index_update_needed(
            request: HTMXRequest,
            date: float, ) -> bool:
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        for public_event in event_loader.public_events:
            web_context: EventUserWebContext = EventUserWebContext(
                request, {'user_main_selector': public_event.uniq_id, }, True)
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
            return AController.redirect_error(request, str(ve))
        if date <= 0.0:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)  # timer is hanged
        if self._user_index_update_needed(request, date):
            web_context: UserWebContext = UserWebContext(request, data, True, False)
            return self._user_render_index(web_context)
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

    @get(
        path='/user-render',
        name='user-render',
    )
    async def htmx_user_render_index(self, request: HTMXRequest) -> Template:
        web_context: UserWebContext = UserWebContext(request, {}, True, False)
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
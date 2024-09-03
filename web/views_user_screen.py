import time
from contextlib import suppress
from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import Reswap, HTMXTemplate
from litestar.status_codes import HTTP_304_NOT_MODIFIED

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import NewEvent
from data.family import NewFamily
from data.rotator import NewRotator
from data.screen import NewScreen
from data.tournament import NewTournament
from data.util import ScreenType
from web.messages import Message
from web.session import SessionHandler
from web.views import WebContext
from web.views_user_index import AUserController, ScreenUserWebContext, BasicScreenOrFamilyUserWebContext, \
    EventUserWebContext, RotatorUserWebContext

logger: Logger = get_logger()


class UserScreenController(AUserController):

    @classmethod
    def _user_render_screen(
            cls, request: HTMXRequest,
            event: NewEvent,
            user_event_selector: str,
            screen: NewScreen = None,
            rotator: NewRotator = None,
            rotator_screen_index: int = None,
    ) -> Template:
        assert screen is not None or rotator is not None
        the_screen: NewScreen = screen if screen else rotator.rotating_screens[
            rotator_screen_index if rotator_screen_index is not None else 0]
        login_needed: bool = cls._event_login_needed(request, event, the_screen)
        return HTMXTemplate(
            template_name="user_screen.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'user_event': event,
                'user_event_selector': user_event_selector,
                'screen': the_screen,
                'rotator': rotator,
                'now': time.time(),
                'login_needed': login_needed,
                'rotator_screen_index': rotator_screen_index,
                'last_result_updated': SessionHandler.get_session_last_result_updated(request),
                'last_illegal_move_updated': SessionHandler.get_session_last_illegal_move_updated(request),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
                'messages': Message.messages(request),
            },
        )

    @post(
        path='/user-login',
        name='user-login',
    )
    async def htmx_login(
            self,
            request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        web_context: EventUserWebContext = EventUserWebContext(request, data, True)
        if web_context.error:
            return web_context.error
        if data['password'] == web_context.event.update_password:
            Message.success(request, 'Authentification réussie !')
            SessionHandler.store_password(request, web_context.event, data['password'])
            web_context: ScreenUserWebContext = ScreenUserWebContext(request, data, False)
            if web_context.error:
                return web_context.error
            user_event_selector: str = self._form_data_to_str_or_none(data, 'user_event_selector')
            return self._user_render_screen(
                request, web_context.event, user_event_selector, screen=web_context.screen, rotator=web_context.rotator)
        if data['password'] == '':
            Message.warning(request, 'Veuillez indiquer le code d\'accès.')
        else:
            Message.error(request, 'Code d\'accès incorrect.')
            SessionHandler.store_password(request, web_context.event, None)
        return self._render_messages(request)

    @post(
        path='/user-screen-render',
        name='user-screen-render',
    )
    async def htmx_user_screen_render(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        web_context: ScreenUserWebContext = ScreenUserWebContext(request, data, False)
        if web_context.error:
            return web_context.error
        return self._user_render_screen(
            request, web_context.event, web_context.user_event_selector, screen=web_context.screen,
            rotator=web_context.rotator, rotator_screen_index=web_context.rotator_screen_index)

    @staticmethod
    def _user_screen_page_update_needed(screen: NewScreen, family: NewFamily, date: float, ) -> bool:
        if screen:
            if screen.event.last_update > date:
                return True
            if screen.last_update > date:
                return True
            match screen.type:
                case ScreenType.Boards | ScreenType.Input | ScreenType.Players:
                    pass
                case ScreenType.Results:
                    results_tournament_ids: list[int] = screen.results_tournament_ids \
                        if screen.results_tournament_ids else screen.event.tournaments_by_id.keys()
                    for tournament_id in results_tournament_ids:
                        with suppress(KeyError):
                            tournament: NewTournament = screen.event.tournaments_by_id[tournament_id]
                            if tournament.last_update > date:
                                return True
                            if tournament.last_result_update > date:
                                return True
                case _:
                    raise ValueError(f'type={screen.type}')
        else:
            if family.event.last_update > date:
                return True
            if family.last_update > date:
                return True
        return False

    @post(
        path='/user-screen-render-if-updated',
        name='user-screen-render-if-updated',
    )
    async def htmx_user_screen_render_if_updated(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Reswap:
        web_context: BasicScreenOrFamilyUserWebContext = BasicScreenOrFamilyUserWebContext(
            request, data, True)
        if web_context.error:
            return web_context.error
        try:
            date: float = WebContext.form_data_to_float(data, 'date', 0.0)
        except ValueError as ve:
            Message.error(request, str(ve))
            return self._render_messages(request)
        if date <= 0.0:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)  # timer is hanged
        if self._user_screen_page_update_needed(web_context.screen, web_context.family, date):
            web_context: ScreenUserWebContext = ScreenUserWebContext(request, data, False)
            if web_context.error:
                return web_context.error
            return self._user_render_screen(
                request, web_context.event, web_context.user_event_selector, screen=web_context.screen,
                rotator=web_context.rotator, rotator_screen_index=web_context.rotator_screen_index)
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

    @post(
        path='/user-rotator-render',
        name='user-rotator-render'
    )
    async def htmx_user_rotator_render_screen(
        self, request: HTMXRequest,
        data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        web_context: RotatorUserWebContext = RotatorUserWebContext(request, data, False)
        if web_context.error:
            return web_context.error
        return self._user_render_screen(
            request, web_context.event, web_context.user_event_selector, rotator=web_context.rotator,
            rotator_screen_index=web_context.rotator_screen_index % len(web_context.rotator.rotating_screens))

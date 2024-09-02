import time
from contextlib import suppress

from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, Reswap
from litestar.status_codes import HTTP_304_NOT_MODIFIED

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.family import NewFamily
from data.screen_set import NewScreenSet
from data.tournament import NewTournament
from data.util import ScreenType
from web.messages import Message
from web.session import SessionHandler
from web.views import WebContext
from web.views_user_index import AUserController, ScreenSetOrFamilyUserWebContext

logger: Logger = get_logger()


class UserScreenSetController(AUserController):
    @staticmethod
    def _user_screen_set_div_update_needed(screen_set: NewScreenSet, family: NewFamily, date: float, ) -> bool:
        tournament: NewTournament = screen_set.tournament if screen_set else family.tournament
        if tournament.last_update > date:
            if tournament.last_update > date:
                return True
        if tournament.last_check_in_update > date:
            return True
        type: ScreenType = screen_set.type if screen_set else family.type
        match type:
            case ScreenType.Boards | ScreenType.Input:
                if tournament.last_illegal_move_update > date:
                    return True
                if tournament.last_result_update > date:
                    return True
            case ScreenType.Players:
                pass
            case _:
                raise ValueError(f'type={screen_set.type}')
        with suppress(FileNotFoundError):
            if tournament.file.lstat().st_mtime > date:
                return True
        return False

    @post(
        path='/user-boards-screen-set-render-if-updated',
        name='user-boards-screen-set-render-if-updated',
    )
    async def htmx_user_boards_screen_set_render_if_updated(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Reswap:
        web_context: ScreenSetOrFamilyUserWebContext = ScreenSetOrFamilyUserWebContext(request, data, True)
        if web_context.error:
            return web_context.error
        try:
            date: float = WebContext.form_data_to_float(data, 'date', 0.0)
        except ValueError as ve:
            Message.error(request, str(ve))
            return self._render_messages(request)
        if date <= 0.0:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)  # timer is hanged
        if not self._user_screen_set_div_update_needed(web_context.screen_set, web_context.family, date):
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)
        web_context = ScreenSetOrFamilyUserWebContext(request, data, True)
        if web_context.error:
            return web_context.error
        return HTMXTemplate(
            template_name='user_boards_screen_set.html',
            context={
                'papi_web_config': PapiWebConfig(),
                'event': web_context.event,
                'screen': web_context.screen,
                'rotator': web_context.rotator,
                'rotator_screen_index': web_context.rotator_screen_index,
                'screen_set': web_context.screen_set,
                'now': time.time(),
                'last_result_updated': SessionHandler.get_session_last_result_updated(request),
                'last_illegal_move_updated': SessionHandler.get_session_last_illegal_move_updated(request),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
            },
        )

    @post(
        path='/user-players-screen-set-render-if-updated',
        name='user-players-screen-set-render-if-updated',
    )
    async def htmx_user_players_screen_set_render_if_updated(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Reswap:
        web_context: ScreenSetOrFamilyUserWebContext = ScreenSetOrFamilyUserWebContext(request, data, False)
        if web_context.error:
            return web_context.error
        try:
            date: float = WebContext.form_data_to_float(data, 'date', 0.0)
        except ValueError as ve:
            Message.error(request, str(ve))
            return self._render_messages(request)
        if date <= 0.0:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)  # timer is hanged
        if not self._user_screen_set_div_update_needed(web_context.screen_set, web_context.family, date):
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)
        return HTMXTemplate(
            template_name='user_players_screen_set.html',
            context={
                'event': web_context.event,
                'user_selector': web_context.user_selector,
                'screen': web_context.screen,
                'rotator': web_context.rotator,
                'rotator_screen_index': web_context.rotator_screen_index,
                'screen_set': web_context.screen_set,
                'now': time.time(),
            },
        )

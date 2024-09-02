import time

from logging import Logger
from typing import Annotated

from litestar import patch
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate

from common.logger import get_logger
from data.loader import EventLoader
from web.session import SessionHandler
from web.views_user_index import AUserController, PlayerUserWebContext

logger: Logger = get_logger()


class UserCheckInController(AUserController):
    @staticmethod
    def _render_input_screen_player_row_player_cell(
            request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        web_context: PlayerUserWebContext = PlayerUserWebContext(request, data, False)
        if web_context.error:
            return web_context.error
        return HTMXTemplate(
            template_name='user_boards_screen_player_row_player_cell.html',
            context={
                'event': web_context.event,
                'user_selector': web_context.user_selector,
                'tournament': web_context.tournament,
                'player': web_context.player,
                'screen': web_context.screen,
                'rotator': web_context.rotator,
                'rotator_screen_index': web_context.rotator_screen_index,
                'now': time.time(),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
            })

    @patch(
        path='/user-input-screen-toggle-check-in',
        name='user-input-screen-toggle-check-in',
    )
    async def htmx_user_input_screen_toggle_check_in(
        self, request: HTMXRequest,
        data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        web_context: PlayerUserWebContext = PlayerUserWebContext(request, data, False)
        if web_context.error:
            return web_context.error
        web_context.tournament.check_in_player(web_context.player, not web_context.player.check_in)
        SessionHandler.set_session_last_check_in_updated(request, web_context.tournament.id, web_context.player.id)
        EventLoader.get(request=request, lazy_load=False).clear_cache(web_context.event.uniq_id)
        return self._render_input_screen_player_row_player_cell(request, data)

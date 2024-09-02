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
from web.views_user_index import AUserController

logger: Logger = get_logger()


class UserCheckInController(AUserController):
    @classmethod
    def _render_input_screen_player_row_player_cell(
            cls,
            request: HTMXRequest,
            event_uniq_id: str,
            user_selector: str,
            screen_uniq_id: str,
            tournament_id: int,
            player_id: int,
    ) -> Template | Redirect:
        response, event, screen, tournament, player, board = cls._load_player_context(
            request, event_uniq_id, user_selector, screen_uniq_id, tournament_id, False, player_id)
        if response:
            return response
        return HTMXTemplate(
            template_name='user_boards_screen_player_row_player_cell.html',
            context={
                'event': event,
                'user_selector': user_selector,
                'tournament': tournament,
                'player': player,
                'screen': screen,
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
        event_uniq_id: str = self._form_data_to_str_or_none(data, 'event_uniq_id')
        user_selector: str = self._form_data_to_str_or_none(data, 'user_selector')
        screen_uniq_id: str = self._form_data_to_str_or_none(data, 'screen_uniq_id')
        tournament_id: int = self._form_data_to_int_or_none(data, 'tournament_id')
        player_id: int = self._form_data_to_int_or_none(data, 'player_id')
        response, event, screen, tournament, player, board = self._load_player_context(
            request, event_uniq_id, user_selector, screen_uniq_id, tournament_id, False, player_id)
        if response:
            return response
        tournament.check_in_player(player, not player.check_in)
        SessionHandler.set_session_last_check_in_updated(request, tournament_id, player_id)
        EventLoader.get(request=request, lazy_load=False).clear_cache(event_uniq_id)
        return self._render_input_screen_player_row_player_cell(
            request, event_uniq_id, user_selector, screen_uniq_id, tournament_id, player_id)

import time

from logging import Logger

from litestar import patch
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
            event_loader: EventLoader,
            event_uniq_id: str,
            screen_uniq_id: str,
            tournament_id: int,
            player_id: int,
    ) -> Template | Redirect:
        response, event, screen, tournament, player, board = cls._load_player_context(
            request, event_loader, event_uniq_id, screen_uniq_id, tournament_id, False, player_id)
        if response:
            return response
        return HTMXTemplate(
            template_name='user_boards_screen_player_row_player_cell.html',
            context={
                'event': event,
                'tournament': tournament,
                'player': player,
                'screen': screen,
                'now': time.time(),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
            })

    @patch(
        path='/user-input-screen-toggle-check-in'
             '/{event_uniq_id:str}/{screen_uniq_id:str}/{tournament_id:int}/{player_id:int}',
        name='user-input-screen-toggle-check-in',
    )
    async def htmx_user_input_screen_toggle_check_in(
            self, request: HTMXRequest, event_uniq_id: str, screen_uniq_id: str, tournament_id: int, player_id: int
    ) -> Template | Redirect:
        event_loader: EventLoader = EventLoader()
        response, event, screen, tournament, player, board = self._load_player_context(
            request, event_loader, event_uniq_id, screen_uniq_id, tournament_id, False, player_id)
        if response:
            return response
        tournament.check_in_player(player, not player.check_in)
        SessionHandler.set_session_last_check_in_updated(request, tournament_id, player_id)
        event_loader.clear_cache(event.uniq_id)
        return self._render_input_screen_player_row_player_cell(
            request, event_loader, event_uniq_id, screen_uniq_id, tournament_id, player_id)

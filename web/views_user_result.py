from contextlib import suppress

from logging import Logger

from litestar import get, put, delete
from litestar.response import Template, Redirect
from litestar.status_codes import HTTP_200_OK
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate

from common.logger import get_logger
from data.board import Board
from data.event import NewEvent
from data.loader import EventLoader
from data.screen import NewScreen
from data.tournament import NewTournament
from data.util import Result
from web.messages import Message
from web.session import SessionHandler
from web.views_user_index import AUserController

logger: Logger = get_logger()


class UserResultController(AUserController):
    @staticmethod
    def _render_input_screen_result_modal(
            event: NewEvent, screen: NewScreen, tournament: NewTournament, board: Board,
    ) -> Template:
        return HTMXTemplate(
            template_name="user_input_screen_board_result_modal.html",
            context={
                'event': event,
                'tournament': tournament,
                'board': board,
                'screen': screen,
            })

    @get(
        path='/user-input-screen-render-result-modal'
             '/{event_uniq_id:str}'
             '/{screen_uniq_id:str}'
             '/{tournament_id:int}'
             '/{board_id:int}',
        name='user-input-screen-render-result-modal'
    )
    async def htmx_user_input_screen_render_result_modal(
            self,
            request: HTMXRequest,
            event_uniq_id: str,
            tournament_id: int,
            board_id: int,
            screen_uniq_id: str,
    ) -> Redirect | Template:
        response, event, screen, tournament, board = self._load_board_context(
            request, EventLoader(), event_uniq_id, screen_uniq_id, tournament_id, True, board_id)
        if response:
            return response
        return self._render_input_screen_result_modal(event, screen, tournament, board)

    @put(
        path='/user-input-screen-add-result'
             '/{event_uniq_id:str}'
             '/{screen_uniq_id:str}'
             '/{tournament_id:int}'
             '/{round:int}'
             '/{board_id:int}'
             '/{result:int}',
        name='user-input-screen-add-result'
    )
    async def htmx_user_input_screen_add_result(
            self, request: HTMXRequest,
            event_uniq_id: str, screen_uniq_id: str, tournament_id: int, round: int, board_id: int, result: int | None,
    ) -> Template:
        event_loader: EventLoader = EventLoader()
        response, event, screen, tournament, board = self._load_board_context(
            request, event_loader, event_uniq_id, screen_uniq_id, tournament_id, True, board_id)
        if response:
            return response
        if result not in Result.imputable_results():
            Message.error(request, f'Le résultat [{result}] est invalide.')
            return self._render_messages(request)
        tournament.add_result(board, Result.from_papi_value(result))
        SessionHandler.set_session_last_result_updated(request, tournament_id, round, board_id)
        event_loader.clear_cache(event.uniq_id)
        return self._render_input_screen_board_row(
            request, event_loader, event_uniq_id, screen_uniq_id, tournament_id, board_id)

    @delete(
        path='/user-input-screen-delete-result'
             '/{event_uniq_id:str}/{screen_uniq_id:str}/{tournament_id:int}/{round:int}/{board_id:int}',
        name='user-input-screen-delete-result',
        status_code=HTTP_200_OK,
    )
    async def htmx_user_input_screen_delete_result(
            self, request: HTMXRequest, event_uniq_id: str, screen_uniq_id: str, tournament_id: int, round: int,
            board_id: int,
    ) -> Template:
        event_loader: EventLoader = EventLoader()
        response, event, screen, tournament, board = self._load_board_context(
            request, event_loader, event_uniq_id, screen_uniq_id, tournament_id, True, board_id)
        if response:
            return response
        with suppress(ValueError):
            tournament.delete_result(board)
            SessionHandler.set_session_last_result_updated(request, tournament_id, round, board_id)
        event_loader.clear_cache(event.uniq_id)
        return self._render_input_screen_board_row(
            request, event_loader, event_uniq_id, screen_uniq_id, tournament_id, board_id)

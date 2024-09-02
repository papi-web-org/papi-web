from contextlib import suppress

from logging import Logger
from typing import Annotated

from litestar import put, delete, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
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
            event: NewEvent, user_selector: str, screen: NewScreen, tournament: NewTournament, board: Board,
    ) -> Template:
        return HTMXTemplate(
            template_name="user_input_screen_board_result_modal.html",
            context={
                'event': event,
                'user_selector': user_selector,
                'tournament': tournament,
                'board': board,
                'screen': screen,
            })

    @post(
        path='/user-input-screen-render-result-modal',
        name='user-input-screen-render-result-modal'
    )
    async def htmx_user_input_screen_render_result_modal(
            self,
            request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Redirect | Template:
        event_uniq_id: str = self._form_data_to_str_or_none(data, 'event_uniq_id')
        user_selector: str = self._form_data_to_str_or_none(data, 'user_selector')
        screen_uniq_id: str = self._form_data_to_str_or_none(data, 'screen_uniq_id')
        tournament_id: int = self._form_data_to_int_or_none(data, 'tournament_id')
        board_id: int = self._form_data_to_int_or_none(data, 'board_id')
        response, event, screen, tournament, board = self._load_board_context(
            request, event_uniq_id, user_selector, screen_uniq_id, tournament_id, True, board_id)
        if response:
            return response
        return self._render_input_screen_result_modal(event, user_selector, screen, tournament, board)

    @classmethod
    def _user_input_screen_update_result(
            cls, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        event_uniq_id: str = cls._form_data_to_str_or_none(data, 'event_uniq_id')
        user_selector: str = cls._form_data_to_str_or_none(data, 'user_selector')
        screen_uniq_id: str = cls._form_data_to_str_or_none(data, 'screen_uniq_id')
        tournament_id: int = cls._form_data_to_int_or_none(data, 'tournament_id')
        round: int = cls._form_data_to_int_or_none(data, 'round')
        board_id: int = cls._form_data_to_int_or_none(data, 'board_id')
        response, event, screen, tournament, board = cls._load_board_context(
            request, event_uniq_id, user_selector, screen_uniq_id, tournament_id, True, board_id)
        if response:
            return response
        result: int = cls._form_data_to_int_or_none(data, 'result')
        if result is None:
            with suppress(ValueError):
                tournament.delete_result(board)
        else:
            if result not in Result.imputable_results():
                Message.error(request, f'Le résultat [{result}] est invalide.')
                return cls._render_messages(request)
            tournament.add_result(board, Result.from_papi_value(result))
        SessionHandler.set_session_last_result_updated(request, tournament_id, round, board_id)
        EventLoader.get(request=request, lazy_load=False).clear_cache(event.uniq_id)
        return cls._render_input_screen_board_row(
            request, event_uniq_id, user_selector, screen_uniq_id, tournament_id, board_id)

    @put(
        path='/user-input-screen-add-result',
        name='user-input-screen-add-result'
    )
    async def htmx_user_input_screen_add_result(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        return self._user_input_screen_update_result(request, data)

    @delete(
        path='/user-input-screen-delete-result',
        name='user-input-screen-delete-result',
        status_code=HTTP_200_OK,
    )
    async def htmx_user_input_screen_delete_result(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        return self._user_input_screen_update_result(request, data)

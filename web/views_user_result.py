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
from data.loader import EventLoader
from data.util import Result
from web.messages import Message
from web.session import SessionHandler
from web.views import WebContext
from web.views_user_index import AUserController, BoardUserWebContext

logger: Logger = get_logger()


class UserResultController(AUserController):

    @post(
        path='/user-input-screen-render-result-modal',
        name='user-input-screen-render-result-modal'
    )
    async def htmx_user_input_screen_render_result_modal(
            self,
            request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Redirect | Template:
        web_context: BoardUserWebContext = BoardUserWebContext(request, data)
        if web_context.error:
            return web_context.error
        return HTMXTemplate(
            template_name="user_input_screen_board_result_modal.html",
            context={
                'event': web_context.event,
                'user_event_selector': web_context.user_event_selector,
                'tournament': web_context.tournament,
                'board': web_context.board,
                'screen': web_context.screen,
            })

    def _user_input_screen_update_result(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        web_context: BoardUserWebContext = BoardUserWebContext(request, data)
        if web_context.error:
            return web_context.error
        field: str = 'round'
        try:
            round: int | None = WebContext.form_data_to_int(data, field)
        except ValueError as ve:
            Message.error(request, f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
            return self._render_messages(request)
        field: str = 'result'
        try:
            result: int | None = WebContext.form_data_to_int(data, field)
        except ValueError as ve:
            Message.error(request, f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
            return self._render_messages(request)
        if result is None:
            with suppress(ValueError):
                web_context.tournament.delete_result(web_context.board)
        else:
            if result not in Result.imputable_results():
                Message.error(request, f'Le résultat [{result}] est invalide.')
                return self._render_messages(request)
            web_context.tournament.add_result(web_context.board, Result.from_papi_value(result))
        SessionHandler.set_session_last_result_updated(request, web_context.tournament.id, round, web_context.board.id)
        EventLoader.get(request=request, lazy_load=False).clear_cache(web_context.event.uniq_id)
        return self._render_input_screen_board_row(request, data)

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

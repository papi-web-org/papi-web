from logging import Logger
from typing import Annotated

from litestar import put, delete
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.status_codes import HTTP_200_OK
from litestar.contrib.htmx.request import HTMXRequest

from common.logger import get_logger
from data.loader import EventLoader
from web.messages import Message
from web.session import SessionHandler
from web.views_user_index import AUserController, PlayerUserWebContext

logger: Logger = get_logger()


class UserIllegalMoveController(AUserController):
    @classmethod
    def _delete_or_add_illegal_move(
            cls, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            add: bool
    ) -> Template | Redirect:
        web_context: PlayerUserWebContext = PlayerUserWebContext(request, data, True)
        if web_context.error:
            return web_context.error
        if add:
            web_context.tournament.store_illegal_move(web_context.player)
        else:
            if not web_context.tournament.delete_illegal_move(web_context.player):
                Message.error(
                    request,
                    f'Le·la joueur·euse {web_context.player.id} n\'a pas de coup illégal enregistré.')
                return cls._render_messages(request)
        SessionHandler.set_session_last_illegal_move_updated(request, web_context.tournament.id, web_context.player.id)
        EventLoader.get(request=request, lazy_load=False).clear_cache(web_context.event.uniq_id)
        return cls._render_input_screen_board_row(request, data)

    @put(
        path='/user-input-screen-add-illegal-move',
        name='user-input-screen-add-illegal-move',
        status_code=HTTP_200_OK,
    )
    async def htmx_user_input_screen_add_illegal_move(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        return self._delete_or_add_illegal_move(request, data, add=True)

    @delete(
        path='/user-input-screen-delete-illegal-move',
        name='user-input-screen-delete-illegal-move',
        status_code=HTTP_200_OK,
    )
    async def htmx_user_input_screen_delete_illegal_move(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        return self._delete_or_add_illegal_move(request, data, add=False)

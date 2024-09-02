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
from web.views_user_index import AUserController

logger: Logger = get_logger()


class UserIllegalMoveController(AUserController):
    @classmethod
    def _delete_or_add_illegal_move(
            cls, request: HTMXRequest,
            event_uniq_id: str,
            user_selector: str,
            screen_uniq_id: str,
            tournament_id: int,
            player_id: int,
            add: bool
    ) -> Template | Redirect:
        response, event, screen, tournament, player, board = cls._load_player_context(
            request, event_uniq_id, user_selector, screen_uniq_id, tournament_id, True, player_id)
        if response:
            return response
        if add:
            tournament.store_illegal_move(player)
        else:
            if not tournament.delete_illegal_move(player):
                Message.error(
                    request,
                    f'Le·la joueur·euse {player_id} n\'a pas de coup illégal enregistré.')
                return cls._render_messages(request)
        SessionHandler.set_session_last_illegal_move_updated(request, tournament_id, player_id)
        EventLoader.get(request=request, lazy_load=False).clear_cache(event_uniq_id)
        return cls._render_input_screen_board_row(
            request, event_uniq_id, user_selector, screen_uniq_id, tournament_id, board.id)

    @put(
        path='/user-input-screen-add-illegal-move',
        name='user-input-screen-add-illegal-move',
        status_code=HTTP_200_OK,
    )
    async def htmx_user_input_screen_add_illegal_move(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        event_uniq_id: str = self._form_data_to_str_or_none(data, 'event_uniq_id')
        user_selector: str = self._form_data_to_str_or_none(data, 'user_selector')
        screen_uniq_id: str = self._form_data_to_str_or_none(data, 'screen_uniq_id')
        tournament_id: int = self._form_data_to_int_or_none(data, 'tournament_id')
        player_id: int = self._form_data_to_int_or_none(data, 'player_id')
        return self._delete_or_add_illegal_move(
            request, event_uniq_id, user_selector, screen_uniq_id, tournament_id, player_id, add=True)

    @delete(
        path='/user-input-screen-delete-illegal-move',
        name='user-input-screen-delete-illegal-move',
        status_code=HTTP_200_OK,
    )
    async def htmx_user_input_screen_delete_illegal_move(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED),],
    ) -> Template | Redirect:
        event_uniq_id: str = self._form_data_to_str_or_none(data, 'event_uniq_id')
        user_selector: str = self._form_data_to_str_or_none(data, 'user_selector')
        screen_uniq_id: str = self._form_data_to_str_or_none(data, 'screen_uniq_id')
        tournament_id: int = self._form_data_to_int_or_none(data, 'tournament_id')
        player_id: int = self._form_data_to_int_or_none(data, 'player_id')
        return self._delete_or_add_illegal_move(
            request, event_uniq_id, user_selector, screen_uniq_id, tournament_id, player_id, add=False)

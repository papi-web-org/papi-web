import time
from contextlib import suppress

from logging import Logger
from typing import Annotated

from litestar import patch, delete, put, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate
from litestar.status_codes import HTTP_200_OK

from common.logger import get_logger
from data.board import Board
from data.loader import EventLoader
from data.player import Player
from data.util import Result
from web.messages import Message
from web.session import SessionHandler
from web.views import WebContext, AController
from web.views_user import AUserController, TournamentUserWebContext

logger: Logger = get_logger()


class BoardUserWebContext(TournamentUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ):
        super().__init__(
            request, data, True)
        self.board: Board | None = None
        if self.error:
            return
        field: str = 'board_id'
        try:
            board_id: int | None = self._form_data_to_int(field)
        except ValueError as ve:
            self._redirect_error(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
            return
        try:
            self.board = self.tournament.boards[board_id - 1]
        except KeyError:
            self._redirect_error(f'L\'échiquier [{board_id}] n\'existe pas.')
            return


class PlayerUserWebContext(TournamentUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            tournament_started: bool | None,
    ):
        super().__init__(request, data, tournament_started)
        self.player: Player | None = None
        self.board: Board | None = None
        if self.error:
            return
        field: str = 'player_id'
        try:
            player_id: int | None = self._form_data_to_int(field)
        except ValueError as ve:
            self._redirect_error(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
            return
        try:
            self.player = self.tournament.players_by_id[player_id]
        except KeyError:
            self._redirect_error(f'Le·la joueur·euse [{player_id}] n\'existe pas.')
            return
        self.board = self.tournament.boards[self.player.board_id - 1] if self.player.board_id else None


class AUserInputController(AUserController):
    @classmethod
    def _render_input_screen_board_row(
            cls,
            request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        web_context: BoardUserWebContext = BoardUserWebContext(request, data)
        if web_context.error:
            return web_context.error
        return HTMXTemplate(
            template_name='user_boards_screen_board_row.html',
            context={
                'user_event': web_context.user_event,
                'user_event_selector': web_context.user_event_selector,
                'tournament': web_context.tournament,
                'board': web_context.board,
                'screen': web_context.screen,
                'rotator': web_context.rotator,
                'rotator_screen_index': web_context.rotator_screen_index if web_context.rotator else 0,
                'now': time.time(),
                'last_result_updated': SessionHandler.get_session_last_result_updated(request),
                'last_illegal_move_updated': SessionHandler.get_session_last_illegal_move_updated(request),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
            })


class UserCheckInController(AUserInputController):

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
        EventLoader.get(request=request, lazy_load=False).clear_cache(web_context.user_event.uniq_id)
        web_context: PlayerUserWebContext = PlayerUserWebContext(request, data, False)
        if web_context.error:
            return web_context.error
        return HTMXTemplate(
            template_name='user_boards_screen_player_row_player_cell.html',
            context={
                'user_event': web_context.user_event,
                'user_event_selector': web_context.user_event_selector,
                'tournament': web_context.tournament,
                'player': web_context.player,
                'screen': web_context.screen,
                'rotator': web_context.rotator,
                'rotator_screen_index': web_context.rotator_screen_index,
                'now': time.time(),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
            })


class UserIllegalMoveController(AUserInputController):
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
            SessionHandler.set_session_last_illegal_move_updated(
                request, web_context.tournament.id, web_context.player.id)
        else:
            if not web_context.tournament.delete_illegal_move(web_context.player):
                Message.error(
                    request,
                    f'Le·la joueur·euse {web_context.player.id} n\'a pas de coup illégal enregistré.')
            else:
                SessionHandler.set_session_last_illegal_move_updated(
                    request, web_context.tournament.id, web_context.player.id)
        EventLoader.get(request=request, lazy_load=False).clear_cache(web_context.user_event.uniq_id)
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


class UserResultController(AUserInputController):

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
                'user_event': web_context.user_event,
                'user_event_selector': web_context.user_event_selector,
                'tournament': web_context.tournament,
                'board': web_context.board,
                'screen': web_context.screen,
            })

    def _user_input_screen_update_result(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        web_context: BoardUserWebContext = BoardUserWebContext(request, data)
        if web_context.error:
            return web_context.error
        field: str = 'round'
        try:
            round: int | None = WebContext.form_data_to_int(data, field)
        except ValueError as ve:
            return AController.redirect_error(
                request, f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
        field: str = 'result'
        try:
            result: int | None = WebContext.form_data_to_int(data, field)
        except ValueError as ve:
            return AController.redirect_error(
                request, f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
        if result is None:
            with suppress(ValueError):
                web_context.tournament.delete_result(web_context.board)
        else:
            if result not in Result.imputable_results():
                return AController.redirect_error(request, f'Le résultat [{result}] est invalide.')
            web_context.tournament.add_result(web_context.board, Result.from_papi_value(result))
        SessionHandler.set_session_last_result_updated(request, web_context.tournament.id, round, web_context.board.id)
        EventLoader.get(request=request, lazy_load=False).clear_cache(web_context.user_event.uniq_id)
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

from contextlib import suppress
from io import BytesIO
from logging import Logger
from pathlib import Path
from typing import Annotated, Any
from zipfile import ZipInfo, ZipFile

from litestar import patch, delete, put, post, Response
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect, File
from litestar.status_codes import HTTP_200_OK

from common.logger import get_logger
from data.board import Board
from data.loader import EventLoader
from data.player import Player
from data.tournament import Tournament
from data.util import Result
from web.messages import Message
from web.session import SessionHandler
from web.controllers.index_controller import WebContext, AbstractController
from web.controllers.user.index_user_controller import AbstractUserController, EventUserWebContext
from web.controllers.user.screen_user_controller import ScreenUserWebContext

logger: Logger = get_logger()


class TournamentUserWebContext(ScreenUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            tournament_started: bool | None,
    ):
        super().__init__(request, data)
        self.tournament: Tournament | None = None
        if self.error:
            return
        field: str = 'tournament_id'
        try:
            tournament_id: int | None = self._form_data_to_int(field)
        except ValueError as ve:
            self._redirect_error(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
            return
        try:
            self.tournament: Tournament = self.user_event.tournaments_by_id[tournament_id]
        except KeyError:
            self._redirect_error(f'Le tournoi [{tournament_id}] n\'existe pas.')
            return
        if tournament_started is not None:
            if tournament_started:
                if not self.tournament.current_round:
                    self._redirect_error(f'Le tournoi [{self.tournament.uniq_id}] n\'est pas commencé.')
                    return
            else:
                if self.tournament.current_round:
                    self._redirect_error(f'Le tournoi [{self.tournament.uniq_id}] est commencé.')
                    return

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'tournament': self.tournament,
        }


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

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'board': self.board,
        }


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

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'player': self.player,
            'board': self.board,
        }


class AbstractUserInputController(AbstractUserController):
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
            context=web_context.template_context | {
                'last_result_updated': SessionHandler.get_session_last_result_updated(request),
                'last_illegal_move_updated': SessionHandler.get_session_last_illegal_move_updated(request),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
            })


class CheckInUserController(AbstractUserInputController):

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
            context=web_context.template_context | {
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
            })


class IllegalMoveUserController(AbstractUserInputController):
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


class ResultUserController(AbstractUserInputController):

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
            context=web_context.template_context | {
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
            return AbstractController.redirect_error(
                request, f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
        field: str = 'result'
        try:
            result: int | None = WebContext.form_data_to_int(data, field)
        except ValueError as ve:
            return AbstractController.redirect_error(
                request, f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
        if result is None:
            with suppress(ValueError):
                web_context.tournament.delete_result(web_context.board)
        else:
            if result not in Result.imputable_results():
                return AbstractController.redirect_error(request, f'Le résultat [{result}] est invalide.')
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


class DownloadUserController(AbstractUserController):
    @post(
        path='/user-download-event-tournaments',
        name='user-download-event-tournaments'
    )
    async def htmx_user_download_event_tournaments(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Response[bytes] | Template:
        web_context: EventUserWebContext = EventUserWebContext(request, data)
        if web_context.error:
            return web_context.error
        tournament_files: list[Path] = [
            tournament.file
            for tournament in web_context.user_event.tournaments_by_id.values()
            if tournament.file_exists
        ]
        if not tournament_files:
            return AbstractController.redirect_error(
                request, f'Aucun fichier de tournoi pour l\'évènement [{web_context.user_event.uniq_id}].')
        archive = BytesIO()
        with ZipFile(archive, 'w') as zip_archive:
            for tournament_file in tournament_files:
                zip_entry: ZipInfo = ZipInfo(tournament_file.name)
                with open(tournament_file, 'rb') as tournament_handler:
                    zip_archive.writestr(
                        zip_entry, tournament_handler.read())
        return Response(content=bytes(archive.getbuffer()), media_type='application/zip')

    @post(
        path='/user-download-tournament',
        name='user-download-tournament'
    )
    async def htmx_user_download_tournament(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> File | Template | Redirect:
        web_context: TournamentUserWebContext = TournamentUserWebContext(request, data, None)
        if web_context.error:
            return web_context.error
        if not web_context.tournament.file_exists:
            return AbstractController.redirect_error(
                request, f'Le fichier [{web_context.tournament.file}] n\'existe pas.')
        return File(path=web_context.tournament.file, filename=web_context.tournament.file.name)

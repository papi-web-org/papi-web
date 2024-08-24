import time

from logging import Logger
from typing import Annotated

from litestar import get, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.status_codes import HTTP_304_NOT_MODIFIED
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, Reswap

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.board import Board
from data.event import NewEvent
from data.loader import EventLoader
from data.player import Player
from data.rotator import NewRotator
from data.screen import NewScreen
from data.tournament import NewTournament
from web.messages import Message
from web.session import SessionHandler
from web.views import AController

logger: Logger = get_logger()


class AUserController(AController):
    @classmethod
    def _load_event_context(
            cls,
            request: HTMXRequest,
            event_loader: EventLoader,
            event_uniq_id: str,
    ) -> tuple[Redirect | Template | None, NewEvent | None, ]:
        event: NewEvent = event_loader.load_event(event_uniq_id)
        if event.errors:
            return cls._redirect_to_index_on_error(request, event.errors), None
        if not event.public:
            Message.error(request, f'L\'évènement [{event.uniq_id}] est privé.')
            return cls._user_render_index(request, event_loader), None
        return None, event

    @classmethod
    def _load_screen_context(
            cls,
            request: HTMXRequest,
            event_loader: EventLoader,
            event_uniq_id: str,
            screen_uniq_id: str,
    ) -> tuple[Redirect | Template | None, NewEvent | None, NewScreen | None, ]:
        response, event = cls._load_event_context(request, event_loader, event_uniq_id)
        if response:
            return response, None, None
        try:
            screen = event.screens_by_uniq_id[screen_uniq_id]
        except KeyError:
            return cls._redirect_to_index_on_error(
                request, f'L\'écran [{screen_uniq_id}] n\'existe pas.'), None, None
        return None, event, screen

    @classmethod
    def _load_tournament_context(
            cls,
            request: HTMXRequest,
            event_loader: EventLoader,
            event_uniq_id: str,
            screen_uniq_id: str,
            tournament_id: int,
            tournament_started: bool | None,
    ) -> tuple[Redirect | Template | None, NewEvent | None, NewScreen | None, NewTournament | None, ]:
        response, event, screen = cls._load_screen_context(request, event_loader, event_uniq_id, screen_uniq_id)
        if response:
            return response, None, None, None
        try:
            tournament: NewTournament = event.tournaments_by_id[tournament_id]
        except KeyError:
            return (cls._redirect_to_index_on_error(request, f'Le tournoi [{tournament_id}] n\'existe pas.'),
                    None, None, None)
        if tournament_started is not None:
            if tournament_started:
                if not tournament.current_round:
                    return (cls._redirect_to_index_on_error(
                        request, f'Le tournoi [{tournament.uniq_id}] n\'est pas commencé.'),
                            None, None, None)
            else:
                if tournament.current_round:
                    return (cls._redirect_to_index_on_error(
                        request, f'Le tournoi [{tournament.uniq_id}] est commencé.'),
                            None, None, None)
        return None, event, screen, tournament

    @classmethod
    def _load_board_context(
            cls,
            request: HTMXRequest,
            event_loader: EventLoader,
            event_uniq_id: str,
            screen_uniq_id: str,
            tournament_id: int,
            tournament_started: bool | None,
            board_id: int,
    ) -> tuple[Redirect | Template | None, NewEvent | None, NewScreen | None, NewTournament | None, Board | None, ]:
        response, event, screen, tournament = cls._load_tournament_context(
            request, event_loader, event_uniq_id, screen_uniq_id, tournament_id, tournament_started)
        if response:
            return response, None, None, None, None
        if cls._event_login_needed(request, event, screen):
            return cls._user_render_screen(request, event, screen, retarget_to_body=True), None, None, None, None
        try:
            board: Board = tournament.boards[board_id - 1]
        except KeyError:
            return (cls._redirect_to_index_on_error(
                request, f'L\'échiquier [{board_id}] introuvable pour le tournoi [{tournament.uniq_id}].'),
                    None, None, None, None)
        return None, event, screen, tournament, board

    @classmethod
    def _load_player_context(
            cls,
            request: HTMXRequest,
            event_loader: EventLoader,
            event_uniq_id: str,
            screen_uniq_id: str,
            tournament_id: int,
            tournament_started: bool,
            player_id: int,
    ) -> tuple[
        Template | Redirect | None, NewEvent | None, NewScreen | None, NewTournament | None, Player | None, Board | None
    ]:
        response, event, screen, tournament = cls._load_tournament_context(
            request, event_loader, event_uniq_id, screen_uniq_id, tournament_id, tournament_started)
        if response:
            return response, None, None, None, None, None
        if cls._event_login_needed(request, event, screen):
            return cls._user_render_screen(request, event, screen, retarget_to_body=True), None, None, None, None, None
        try:
            player: Player = tournament.players_by_id[player_id]
        except KeyError:
            return (cls._redirect_to_index_on_error(
                request, f'Le·la joueur·euse [{player_id}] est introuvable pour le tournoi [{tournament.uniq_id}].'),
                    None, None, None, None, None)
        board: Board = tournament.boards[player.board_id - 1] if player.board_id else None
        return None, event, screen, tournament, player, board

    @staticmethod
    def _user_render_index(
            request: HTMXRequest,
            event_loader: EventLoader | None,
    ) -> Template:
        return HTMXTemplate(
            template_name="user_index.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'event_loader': event_loader if event_loader else EventLoader(),
                'messages': Message.messages(request),
                'now': time.time(),
            })

    @classmethod
    def _user_render_screen(
            cls, request: HTMXRequest,
            event: NewEvent,
            screen: NewScreen = None,
            rotator: NewRotator = None, rotator_screen_index: int = 0,
            retarget_to_body: bool = False,
    ) -> Template:
        assert screen is not None or rotator is not None
        the_screen: NewScreen = screen if screen else rotator.rotating_screens[rotator_screen_index]
        login_needed: bool = cls._event_login_needed(request, event, the_screen)
        return HTMXTemplate(
            template_name="user_screen.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'event': event,
                'screen': the_screen,
                'now': time.time(),
                'login_needed': login_needed,
                'rotator': rotator,
                'rotator_screen_index': rotator_screen_index,
                'last_result_updated': SessionHandler.get_session_last_result_updated(request),
                'last_illegal_move_updated': SessionHandler.get_session_last_illegal_move_updated(request),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
                'messages': Message.messages(request),
            },
            re_target='body' if retarget_to_body else None,
        )

    @classmethod
    def _render_input_screen_board_row(
            cls,
            request: HTMXRequest,
            event_loader: EventLoader,
            event_uniq_id: str,
            screen_uniq_id: str,
            tournament_id: int,
            board_id: int,
    ) -> Template:
        response, event, screen, tournament, board = cls._load_board_context(
            request, event_loader, event_uniq_id, screen_uniq_id, tournament_id, True, board_id)
        if response:
            return response
        return HTMXTemplate(
            template_name='user_boards_screen_board_row.html',
            context={
                'event': event,
                'tournament': tournament,
                'board': board,
                'screen': screen,
                'now': time.time(),
                'last_result_updated': SessionHandler.get_session_last_result_updated(request),
                'last_illegal_move_updated': SessionHandler.get_session_last_illegal_move_updated(request),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
            })


class UserIndexController(AUserController):
    @staticmethod
    def _user_index_update_needed(event_loader: EventLoader, date: float, ) -> bool:
        for event_uniq_id in event_loader.events_by_id:
            event: NewEvent = event_loader.load_event(event_uniq_id)
            if event.last_update > date:
                return True
            for tournament in event.tournaments_by_id.values():
                if tournament.last_update > date:
                    return True
        return False

    @post(
        path='/user-render-if-updated',
        name='user-render-if-updated',
    )
    async def htmx_user_render_if_updated(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Reswap:
        try:
            date: float = self._form_data_to_float_or_none(data, 'date')
        except ValueError as ve:
            Message.error(request, str(ve))
            return self._render_messages(request)
        event_loader: EventLoader = EventLoader()
        if self._user_index_update_needed(event_loader, date):
            return self._user_render_index(request, event_loader)
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

    @get(
        path='/user-render',
        name='user-render',
    )
    async def htmx_user_render_index(self, request: HTMXRequest) -> Template:
        return self._user_render_index(request, None)

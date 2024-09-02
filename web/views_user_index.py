import time

from logging import Logger
from typing import Annotated

from litestar import get, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.status_codes import HTTP_304_NOT_MODIFIED
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, Reswap

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.board import Board
from data.event import NewEvent
from data.family import NewFamily
from data.loader import EventLoader
from data.player import Player
from data.rotator import NewRotator
from data.screen import NewScreen
from data.screen_set import NewScreenSet
from data.tournament import NewTournament
from web.messages import Message
from web.session import SessionHandler
from web.views import AController, WebContext

logger: Logger = get_logger()


class UserWebContext(WebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ):
        super().__init__(request, data)
        self.user_selector: str = self._form_data_to_str('user_selector')


class EventUserWebContext(UserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data)
        try:
            event_uniq_id: str = self._form_data_to_str('event_uniq_id')
        except ValueError as ve:
            self._redirect_to_index(str(ve))
            return
        self.event: NewEvent = EventLoader.get(request=self.request, lazy_load=lazy_load).load_event(event_uniq_id)
        if self.event.errors:
            self._redirect_to_index(self.event.errors)
            return
        if not self.event.public:
            self._redirect_to_index(f'L\'évènement [{self.event.uniq_id}] est privé.')
            return


class RotatorUserWebContext(EventUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data, lazy_load)
        self.rotator: NewRotator | None = None
        self.rotator_screen_index: int = 0
        if self.error:
            return
        field: str = 'rotator_id'
        try:
            rotator_id: int | None = self._form_data_to_int(field)
        except ValueError as ve:
            self._redirect_to_index(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
            return
        field: str = 'rotator_screen_index'
        if rotator_id:
            try:
                rotator_screen_index: int = self._form_data_to_int(field, 0)
            except ValueError as ve:
                self._redirect_to_index(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
                return
            try:
                self.rotator = self.event.rotators_by_id[rotator_id]
            except KeyError:
                self._redirect_to_index(f'L\'écran rotatif [{rotator_id}] n\'existe pas.')
                return
            self.rotator_screen_index = rotator_screen_index


class ScreenUserWebContext(RotatorUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data, lazy_load)
        self.screen: NewScreen | None = None
        if self.error:
            return
        field: str = 'screen_uniq_id'
        screen_uniq_id: str = self._form_data_to_str(field)
        try:
            self.screen = self.event.screens_by_uniq_id[screen_uniq_id]
        except KeyError:
            self._redirect_to_index(f'L\'écran [{data.get(field, None)}] n\'existe pas.')
            return


class BasicScreenOrFamilyUserWebContext(ScreenUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data, lazy_load)
        self.family: NewFamily | None = None
        if self.error:
            return
        if ':' in self.screen.uniq_id:
            family_uniq_id: str = self.screen.uniq_id.split(':')[0]
            self.screen = None
            try:
                self.family = self.event.families_by_uniq_id[family_uniq_id]
            except KeyError:
                self._redirect_to_index(f'La famille [{family_uniq_id}] n\'existe pas.')
                return


class ScreenSetOrFamilyUserWebContext(BasicScreenOrFamilyUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data, lazy_load)
        self.screen_set: NewScreenSet | None = None
        if self.error:
            return
        if self.screen:
            field: str = 'screen_set_uniq_id'
            screen_set_uniq_id: str = self._form_data_to_str(field)
            try:
                self.screen_set = self.screen.screen_sets_by_uniq_id[screen_set_uniq_id]
            except KeyError:
                self._redirect_to_index(
                    f'L\'ensemble [{screen_set_uniq_id}] de l\'écran [{self.screen.uniq_id}] est introuvable.')
                return


class TournamentUserWebContext(ScreenUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            tournament_started: bool | None,
    ):
        super().__init__(request, data, tournament_started is None)
        self.tournament: NewTournament | None = None
        if self.error:
            return
        field: str = 'tournament_id'
        try:
            tournament_id: int | None = self._form_data_to_int(field)
        except ValueError as ve:
            self._redirect_to_index(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
            return
        try:
            self.tournament: NewTournament = self.event.tournaments_by_id[tournament_id]
        except KeyError:
            self._redirect_to_index(f'Le tournoi [{tournament_id}] n\'existe pas.')
            return
        if tournament_started is not None:
            if tournament_started:
                if not self.tournament.current_round:
                    self._redirect_to_index(f'Le tournoi [{self.tournament.uniq_id}] n\'est pas commencé.')
                    return
            else:
                if self.tournament.current_round:
                    self._redirect_to_index(f'Le tournoi [{self.tournament.uniq_id}] est commencé.')
                    return


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
            self._redirect_to_index(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
            return
        try:
            self.board = self.tournament.boards[board_id - 1]
        except KeyError:
            self._redirect_to_index(f'L\'échiquier [{board_id}] n\'existe pas.')
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
            self._redirect_to_index(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
            return
        try:
            self.player = self.tournament.players_by_id[player_id]
        except KeyError:
            self._redirect_to_index(f'Le·la joueur·euse [{player_id}] n\'existe pas.')
            return
        self.board = self.tournament.boards[self.player.board_id - 1] if self.player.board_id else None


class AUserController(AController):
    @staticmethod
    def _user_render_index(
            request: HTMXRequest,
    ) -> Template:
        return HTMXTemplate(
            template_name="user_index.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'event_loader': EventLoader.get(request=request, lazy_load=True),
                'messages': Message.messages(request),
                'now': time.time(),
                'user_columns': SessionHandler.get_session_user_columns(request),
            })

    @classmethod
    def _user_render_screen(
            cls, request: HTMXRequest,
            event: NewEvent,
            user_selector: str,
            screen: NewScreen = None,
            rotator: NewRotator = None,
            rotator_screen_index: int = None,
    ) -> Template:
        assert screen is not None or rotator is not None
        the_screen: NewScreen = screen if screen else rotator.rotating_screens[
            rotator_screen_index if rotator_screen_index is not None else 0]
        login_needed: bool = cls._event_login_needed(request, event, the_screen)
        return HTMXTemplate(
            template_name="user_screen.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'event': event,
                'user_selector': user_selector,
                'screen': the_screen,
                'rotator': rotator,
                'now': time.time(),
                'login_needed': login_needed,
                'rotator_screen_index': rotator_screen_index,
                'last_result_updated': SessionHandler.get_session_last_result_updated(request),
                'last_illegal_move_updated': SessionHandler.get_session_last_illegal_move_updated(request),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
                'messages': Message.messages(request),
            },
        )

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
                'event': web_context.event,
                'user_selector': web_context.user_selector,
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


class UserIndexController(AUserController):
    @staticmethod
    def _user_index_update_needed(
            request: HTMXRequest,
            date: float, ) -> bool:
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        for event_uniq_id in event_loader.events_by_id:
            web_context: EventUserWebContext = EventUserWebContext(
                request, {'event_uniq_id': event_uniq_id, }, True)
            if web_context.error:
                return False
            if web_context.event.last_update > date:
                return True
            for tournament in web_context.event.tournaments_by_id.values():
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
            date: float = WebContext.form_data_to_float(data, 'date', 0.0)
        except ValueError as ve:
            Message.error(request, str(ve))
            return self._render_messages(request)
        if date <= 0.0:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)  # timer is hanged
        if self._user_index_update_needed(request, date):
            return self._user_render_index(request)
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

    @get(
        path='/user-render',
        name='user-render',
    )
    async def htmx_user_render_index(self, request: HTMXRequest) -> Template:
        return self._user_render_index(request)

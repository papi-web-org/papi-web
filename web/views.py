from zipfile import ZipFile, ZipInfo
from io import BytesIO
from contextlib import suppress
from pathlib import Path

import time

from logging import Logger
from typing import Annotated

from litestar import get, post, Response, put, delete, patch, Controller
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect, File
from litestar.status_codes import HTTP_200_OK, HTTP_304_NOT_MODIFIED
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, Reswap, ClientRedirect, ClientRefresh

from common.logger import get_logger
from common.papi_web_config import PAPI_WEB_COPYRIGHT, PAPI_WEB_URL, PAPI_WEB_VERSION, PapiWebConfig
from data.board import Board
from data.event import Event, get_events_sorted_by_name, get_events_by_id
from data.player import Player
from data.rotator import Rotator
from data.screen import AScreen
from data.screen_set import ScreenSet
from data.tournament import Tournament
from data.util import Result
from database.access import access_driver, odbc_drivers
from web.messages import Message
from web.session import SessionHandler
from web.urls import index_url, event_url

logger: Logger = get_logger()

papi_web_info: dict[str, str] = {
    'version': PAPI_WEB_VERSION,
    'url': PAPI_WEB_URL,
    'copyright': PAPI_WEB_COPYRIGHT,
}


class AController(Controller):

    @staticmethod
    def _redirect_response(request: HTMXRequest, redirect_to: str) -> Redirect | ClientRedirect:
        return ClientRedirect(redirect_to=redirect_to) if request.htmx else Redirect(path=redirect_to)

    @staticmethod
    def _render_messages(request: HTMXRequest) -> Template:
        return HTMXTemplate(
            template_name='messages.html',
            re_swap='afterbegin',
            re_target='#messages',
            context={
                'messages': Message.messages(request),
            })

    @staticmethod
    def _event_login_needed(request: HTMXRequest, event: Event, screen: AScreen | None = None) -> bool:
        if screen is not None:
            if not screen.update:
                return False
        if not event.update_password:
            return False
        session_password: str | None = SessionHandler.get_stored_password(request, event)
        logger.debug('session_password=%s', "*" * (8 if session_password else 0))
        if session_password is None:
            Message.error(request,
                          'Un code d\'accès est nécessaire pour accéder à l\'interface de saisie des résultats.')
            return True
        if session_password != event.update_password:
            Message.error(request, 'Code d\'accès incorrect.')
            SessionHandler.store_password(request, event, None)
            return True
        return False


class LoginController(AController):
    @post(
        path='/login/{event_id:str}',
        name='login',
    )
    async def htmx_login(
            self,
            request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
            event_id: str,
    ) -> Template | ClientRedirect | ClientRefresh:
        event: Event = Event(event_id, True)
        if event.errors:
            for error in event.errors:
                Message.error(request, error)
            return ClientRedirect(redirect_to=index_url(request))
        if data['password'] == event.update_password:
            Message.success(request, 'Authentification réussie.')
            SessionHandler.store_password(request, event, data['password'])
            return ClientRefresh()
        if data['password'] == '':
            Message.warning(request, 'Veuillez indiquer le code d\'accès.')
        else:
            Message.error(request, 'Code d\'accès incorrect.')
            SessionHandler.store_password(request, event, None)
        return self._render_messages(request)


class IndexController(AController):
    @get(
        path='/',
        name='index'
    )
    async def index(self, request: HTMXRequest) -> Template:
        events: list[Event] = get_events_sorted_by_name(True)
        if len(events) == 0:
            Message.error(request, 'Aucun évènement trouvé')
        return HTMXTemplate(
            template_name="index.html",
            context={
                'papi_web_info': papi_web_info,
                'papi_web_config': PapiWebConfig(),
                'events': events,
                'odbc_drivers': odbc_drivers(),
                'access_driver': access_driver(),
                'messages': Message.messages(request),
            })


class UserController(AController):
    @get(
        path='/event/{event_id:str}',
        name='render-event'
    )
    async def render_event(self, request: HTMXRequest, event_id: str) -> Template | Redirect:
        event: Event = Event(event_id, True)
        if event.errors:
            for error in event.errors:
                Message.error(request, error)
            return Redirect(path=index_url(request))
        return HTMXTemplate(
            template_name="event.html",
            context={
                'papi_web_info': papi_web_info,
                'event': event,
                'messages': Message.messages(request),
                'now': time.time(),
            })

    @get(
        path='/render-event-if-updated/{event_id:str}/{date:float}',
        name='render-event-if-updated',
    )
    async def htmx_render_event_if_updated(
            self, request: HTMXRequest, event_id: str, date: float
    ) -> Template | ClientRefresh | Reswap:
        file_dependencies: list[Path] = Event.get_event_file_dependencies(event_id)
        if file_dependencies:
            try:
                last_update: float = file_dependencies[0].lstat().st_mtime
                for dependency in file_dependencies[1:]:
                    with suppress(FileNotFoundError):
                        last_update = max(last_update, dependency.lstat().st_mtime)
                if last_update < date:
                    return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)
                else:
                    return ClientRefresh()
            except FileNotFoundError as fnfe:
                Message.warning(request, f'Fichier [{fnfe.filename}] non trouvé')
        else:
            Message.error(
                request, f'Aucune dépendance de fichier trouvée pour l\'évènement [{event_id}]')
        return self._render_messages(request)

    def _render_screen(
            self, request: HTMXRequest,
            event: Event,
            screen: AScreen = None,
            rotator: Rotator = None, rotator_screen_index: int = 0,
    ) -> Template:
        the_screen: AScreen = screen if screen else rotator.screens[rotator_screen_index]
        login_needed: bool = self._event_login_needed(request, event, the_screen)
        return HTMXTemplate(
            template_name="screen.html",
            context={
                'papi_web_info': papi_web_info,
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
            })

    @get(
        path='/screen/{event_id:str}/{screen_id:str}',
        name='render-screen',
    )
    async def render_screen(self, request: HTMXRequest, event_id: str, screen_id: str) -> Template | Redirect:
        event: Event = Event(event_id, True)
        error: str
        redirect_to: str
        if not event.errors:
            try:
                screen: AScreen = event.screens[screen_id]
                return self._render_screen(request, event=event, screen=screen, )
            except KeyError:
                error = f'écran [{screen_id}] introuvable'
                redirect_to = event_url(request, event_id)
        else:
            error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
            redirect_to = index_url(request)
        Message.error(
            request, f'L\'affichage de l\'écran [{event_id}/{screen_id}] a échoué ({error})')
        return Redirect(path=redirect_to)

    @get(
        path='/render-screen-if-updated/{event_id:str}/{screen_id:str}/{date:float}',
        name='render-screen-if-updated',
    )
    async def htmx_render_screen_if_updated(
            self, request: HTMXRequest, event_id: str, screen_id: str, date: float
    ) -> Template | ClientRefresh | Reswap:
        file_dependencies: list[Path] = AScreen.get_screen_file_dependencies(
            event_id, screen_id)
        if not file_dependencies:
            Message.error(
                request,
                f'Aucune dépendance de fichier trouvée pour l\'écran [{screen_id}] de l\'évènement [{event_id}]')
        else:
            try:
                last_update: float = file_dependencies[0].lstat().st_mtime
                for dependency in file_dependencies[1:]:
                    with suppress(FileNotFoundError):
                        last_update = max(last_update, dependency.lstat().st_mtime)
                if last_update < date:
                    return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)
                else:
                    return ClientRefresh()
            except FileNotFoundError as fnfe:
                Message.warning(request, f'Fichier [{fnfe.filename}] non trouvé')
        return self._render_messages(request)

    def _render_rotator_screen(
            self, request: HTMXRequest, event_id: str, rotator_id: str, rotator_screen_index: int = 0,
    ) -> Template | Redirect | ClientRedirect:
        event: Event = Event(event_id, True)
        error: str
        redirect_to: str
        if not event.errors:
            try:
                rotator: Rotator = event.rotators[rotator_id]
                return self._render_screen(
                    request, event=event, rotator=rotator,
                    rotator_screen_index=rotator_screen_index % len(rotator.screens))
            except KeyError:
                error = f'écran rotatif [{rotator_id}] introuvable'
                redirect_to = event_url(request, event_id)
        else:
            error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
            redirect_to = index_url(request)
        Message.error(
            request, f'L\'affichage de l\'écran rotatif [{event_id}/{rotator_id}] a échoué ({error})')
        return self._redirect_response(request, redirect_to)

    @get(
        path='/rotator/{event_id:str}/{rotator_id:str}',
        name='render-rotator'
    )
    async def render_rotator(
            self, request: HTMXRequest, event_id: str, rotator_id: str
    ) -> Template | Redirect:
        return self._render_rotator_screen(request, event_id, rotator_id)

    @get(
        path='/render-rotator-screen/{event_id:str}/{rotator_id:str}/{rotator_screen_index:int}',
        name='render-rotator-screen'
    )
    async def htmx_render_rotator_screen(
            self, request: HTMXRequest, event_id: str, rotator_id: str, rotator_screen_index: int
    ) -> Template | ClientRedirect:
        return self._render_rotator_screen(request, event_id, rotator_id, rotator_screen_index)

    def _load_boards_screen_board_result_modal_data(
            self, request: HTMXRequest, event_id: str, tournament_uniq_id: str, board_id: int, screen_id: str,
    ) -> tuple[Event | None, Tournament | None, Board | None, AScreen | None, ]:
        error: str
        event: Event = Event(event_id, True)
        if not event.errors:
            if not self._event_login_needed(request, event):
                try:
                    tournament: Tournament = event.tournaments[tournament_uniq_id]
                    if tournament.current_round:
                        try:
                            board: Board = tournament.boards[board_id - 1]
                            try:
                                screen: AScreen = event.screens[screen_id]
                                return event, tournament, board, screen
                            except KeyError:
                                error = f'écran [{screen_id}] introuvable'
                        except KeyError:
                            error = f'échiquier [{board_id}] introuvable pour le tournoi [{tournament.uniq_id}]'
                    else:
                        error = f'aucun appariement trouvé pour le tournoi [{tournament_uniq_id}]'
                except KeyError:
                    error = f'tournoi [{tournament_uniq_id}] est introuvable'
            else:
                error = f'gestion des résultats non autorisée pour \'évènement [{event_id}]'
        else:
            error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
        Message.error(
            request, f'L\'affichage de l\'écran de saisie du résultat a échoué ({error})')
        return None, None, None, None,

    @staticmethod
    def _render_boards_screen_board_result_modal(
            event: Event, tournament: Tournament, board: Board, screen: AScreen,
    ) -> Template:
        return HTMXTemplate(
            template_name="boards_screen_board_result_modal.html",
            context={
                'event': event,
                'tournament': tournament,
                'board': board,
                'screen': screen,
            })

    @get(
        path='/render-boards-screen-board-result-modal'
             '/{event_id:str}'
             '/{tournament_uniq_id:str}'
             '/{board_id:int}'
             '/{screen_id:str}',
        name='render-boards-screen-board-result-modal'
    )
    async def htmx_render_boards_screen_board_result_modal(
            self, request: HTMXRequest, event_id: str, tournament_uniq_id: str, board_id: int, screen_id: str,
    ) -> Template:
        event, tournament, board, screen = self._load_boards_screen_board_result_modal_data(
            request, event_id, tournament_uniq_id, board_id, screen_id)
        if event is None:
            return self._render_messages(request)
        return self._render_boards_screen_board_result_modal(event, tournament, board, screen)

    def _load_boards_screen_board_row_data(
            self, request: HTMXRequest, event_id: str, tournament_uniq_id: str, board_id: int, screen_id: str,
    ) -> tuple[Event | None, Tournament | None, Board | None, AScreen | None]:
        error: str
        event: Event = Event(event_id, True)
        if not event.errors:
            if not self._event_login_needed(request, event):
                try:
                    tournament: Tournament = event.tournaments[tournament_uniq_id]
                    if tournament.current_round:
                        try:
                            board: Board = tournament.boards[board_id - 1]
                            try:
                                screen: AScreen = event.screens[screen_id]
                                return event, tournament, board, screen
                            except KeyError:
                                error = f'écran [{screen_id}] introuvable'
                        except KeyError:
                            error = f'échiquier [{board_id}] introuvable pour le tournoi [{tournament.uniq_id}]'
                    else:
                        error = f'aucun appariement trouvé pour le tournoi [{tournament_uniq_id}]'
                except KeyError:
                    error = f'tournoi [{tournament_uniq_id}] est introuvable'
            else:
                error = f'gestion des résultats non autorisée pour \'évènement [{event_id}]'
        else:
            error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
        Message.error(request, f'L\'écriture du résultat à échoué ({error})')
        return None, None, None, None,

    def _render_boards_screen_board_row(
            self,
            request: HTMXRequest,
            event_id: str,
            tournament_uniq_id: str,
            board_id: int,
            screen_id: str,
    ) -> Template:
        template_name: str = 'boards_screen_board_row.html'
        event, tournament, board, screen = self._load_boards_screen_board_row_data(
            request, event_id, tournament_uniq_id, board_id, screen_id)
        if event is None:
            return self._render_messages(request)
        return HTMXTemplate(
            template_name=template_name,
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

    @put(
        path='/board-result'
             '/{event_id:str}'
             '/{tournament_uniq_id:str}'
             '/{round:int}'
             '/{board_id:int}'
             '/{result:int}'
             '/{screen_id:str}',
        name='add-board-result'
    )
    async def htmx_add_board_result(
            self, request: HTMXRequest,
            event_id: str, tournament_uniq_id: str, round: int, board_id: int, result: int | None, screen_id: str,
    ) -> Template:
        event, tournament, board, screen = self._load_boards_screen_board_row_data(
            request, event_id, tournament_uniq_id, board_id, screen_id)
        if event is None:
            return self._render_messages(request)
        if result not in Result.imputable_results():
            Message.error(
                request, f'L\'écriture du résultat a échoué (résultat invalide [{result}])')
            return self._render_messages(request)
        tournament.add_result(board, Result.from_papi_value(result))
        SessionHandler.set_session_last_result_updated(request, tournament_uniq_id, round, board_id)
        return self._render_boards_screen_board_row(request, event_id, tournament_uniq_id, board_id, screen_id)

    @delete(
        path='/board-result/{event_id:str}/{tournament_uniq_id:str}/{round:int}/{board_id:int}/{screen_id:str}',
        name='delete-board-result',
        status_code=HTTP_200_OK,
    )
    async def htmx_delete_board_result(
        self, request: HTMXRequest, event_id: str, tournament_uniq_id: str, round: int, board_id: int, screen_id: str,
    ) -> Template:
        event, tournament, board, screen = self._load_boards_screen_board_row_data(
            request, event_id, tournament_uniq_id, board_id, screen_id)
        if event is None:
            return self._render_messages(request)
        with suppress(ValueError):
            tournament.delete_result(board)
            SessionHandler.set_session_last_result_updated(request, tournament_uniq_id, round, board_id)
        return self._render_boards_screen_board_row(request, event_id, tournament_uniq_id, board_id, screen_id)

    def _load_boards_screen_board_row_illegal_move_data(
            self, request: HTMXRequest, event_id: str, tournament_uniq_id: str, player_id: int, screen_id: str,
    ) -> tuple[Event | None, Tournament | None, Player | None, Board | None, AScreen | None]:
        error: str
        event: Event = Event(event_id, True)
        if not event.errors:
            if not self._event_login_needed(request, event):
                try:
                    tournament: Tournament = event.tournaments[tournament_uniq_id]
                    if tournament.current_round:
                        try:
                            player: Player = tournament.players_by_id[player_id]
                            try:
                                board: Board = tournament.boards[player.board_id - 1]
                                try:
                                    screen: AScreen = event.screens[screen_id]
                                    return event, tournament, player, board, screen
                                except KeyError:
                                    error = f'écran [{screen_id}] introuvable'
                            except KeyError:
                                error = \
                                    f'échiquier [{player.board_id}] introuvable pour le tournoi [{tournament.uniq_id}])'
                        except KeyError:
                            error = f'joueur·euse [{player_id}] introuvable pour le tournoi [{tournament.uniq_id}])'
                    else:
                        error = f'aucun appariement trouvé pour le tournoi [{tournament_uniq_id}]'
                except KeyError:
                    error = f'tournoi [{tournament_uniq_id}] introuvable'
            else:
                error = f'gestion des coups illégaux non autorisée pour \'évènement [{event_id}]'
        else:
            error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
        Message.error(
            request, f'L\'opération sur les coups illégaux a échoué ({error})')
        return None, None, None, None, None,

    @put(
        path='/player-illegal-move/{event_id:str}/{tournament_uniq_id:str}/{player_id:int}/{screen_id:str}',
        name='put-player-illegal-move',
        status_code=HTTP_200_OK,
    )
    async def htmx_add_illegal_move(
            self, request: HTMXRequest, event_id: str, tournament_uniq_id: str, player_id: int, screen_id: str,
    ) -> Template:
        event, tournament, player, board, screen = self._load_boards_screen_board_row_illegal_move_data(
            request, event_id, tournament_uniq_id, player_id, screen_id)
        if event is None:
            return self._render_messages(request)
        tournament.store_illegal_move(player)
        SessionHandler.set_session_last_illegal_move_updated(request, tournament_uniq_id, player_id)
        return self._render_boards_screen_board_row(request, event_id, tournament_uniq_id, board.id, screen_id)

    @delete(
        path='/player-illegal-move/{event_id:str}/{tournament_uniq_id:str}/{player_id:int}/{screen_id:str}',
        name='delete-player-illegal-move',
        status_code=HTTP_200_OK,
    )
    async def htmx_delete_illegal_move(
            self, request: HTMXRequest, event_id: str, tournament_uniq_id: str, player_id: int, screen_id: str,
    ) -> Template:
        event, tournament, player, board, screen = self._load_boards_screen_board_row_illegal_move_data(
            request, event_id, tournament_uniq_id, player_id, screen_id)
        if event is None:
            return self._render_messages(request)
        if not tournament.delete_illegal_move(player):
            Message.error(
                request,
                f'Pas de coup illégal trouvé pour le·la joueur·euse {player_id} dans le tournoi [{tournament.uniq_id}]')
            return self._render_messages(request)
        SessionHandler.set_session_last_illegal_move_updated(request, tournament_uniq_id, player_id)
        return self._render_boards_screen_board_row(request, event_id, tournament_uniq_id, board.id, screen_id)

    def _load_boards_screen_player_row_player_cell_data(
            self, request: HTMXRequest, event_id: str, tournament_uniq_id: str, player_id: int, screen_id: str,
    ) -> tuple[Event | None, Tournament | None, Player | None, AScreen | None]:
        error: str
        event: Event = Event(event_id, True)
        if not event.errors:
            if not self._event_login_needed(request, event):
                try:
                    tournament: Tournament = event.tournaments[tournament_uniq_id]
                    if not tournament.current_round:
                        try:
                            player: Player = tournament.players_by_id[player_id]
                            try:
                                screen: AScreen = event.screens[screen_id]
                                return event, tournament, player, screen
                            except KeyError:
                                error = f'écran [{screen_id}] introuvable'
                        except KeyError:
                            error = f'joueur·euse [{player_id}] introuvable pour le tournoi [{tournament.uniq_id}])'
                    else:
                        error = f'pointage clos pour le tournoi [{tournament_uniq_id}]'
                except KeyError:
                    error = f'tournoi [{tournament_uniq_id}] introuvable'
            else:
                error = f'gestion du pointage non autorisée pour l\'évènement [{event_id}]'
        else:
            error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
        Message.error(request, f'L\'opération a échoué ({error})')
        return None, None, None, None,

    def _render_boards_screen_player_row_player_cell(
            self, request: HTMXRequest, event_id: str, tournament_uniq_id: str, player_id: int, screen_id: str,
    ) -> Template:
        template_name: str = 'boards_screen_player_row_player_cell.html'
        event, tournament, player, screen = self._load_boards_screen_player_row_player_cell_data(
            request, event_id, tournament_uniq_id, player_id, screen_id)
        if event is None:
            return self._render_messages(request)
        return HTMXTemplate(
            template_name=template_name,
            context={
                'event': event,
                'tournament': tournament,
                'player': player,
                'screen': screen,
                'now': time.time(),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
            })

    @patch(
        path='/toggle-player-check-in/{event_id:str}/{tournament_uniq_id:str}/{player_id:int}/{screen_id:str}',
        name='toggle-player-check-in',
    )
    async def htmx_toggle_player_check_in(
            self, request: HTMXRequest, event_id: str, screen_id: str, tournament_uniq_id: str, player_id: int
    ) -> Template:
        event, tournament, player, screen = self._load_boards_screen_player_row_player_cell_data(
            request, event_id, tournament_uniq_id, player_id, screen_id)
        if not event:
            return self._render_messages(request)
        tournament.check_in_player(player, not player.check_in)
        SessionHandler.set_session_last_check_in_updated(request, tournament_uniq_id, player_id)
        return self._render_boards_screen_player_row_player_cell(
            request, event_id, tournament_uniq_id, player_id, screen_id)

    @staticmethod
    def _load_boards_or_players_screen_set_data(
            request: HTMXRequest, event_id: str, screen_id: str, screen_set_id: int,
    ) -> tuple[Event | None, AScreen | None, ScreenSet | None, ]:
        error: str
        event: Event = Event(event_id, True)
        if not event.errors:
            try:
                screen: AScreen = event.screens[screen_id]
                try:
                    screen_set = screen.sets[screen_set_id]
                    return event, screen, screen_set
                except KeyError:
                    error = f'ensemble [{screen_set_id}] de l\'écran [{screen_id}] introuvable'
            except KeyError:
                error = f'écran [{screen_id}] introuvable'
        else:
            error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
        Message.error(
            request, f'La mise à jour de l\'écran [{event_id}/{screen_id}/{screen_set_id}] a échoué ({error})')
        return None, None, None,

    @get(
        path='/render-boards-screen-set-if-updated'
             '/{event_id:str}'
             '/{screen_id:str}'
             '/{screen_set_id:int}'
             '/{date:float}',
        name='render-boards-screen-set-if-updated',
    )
    async def htmx_render_boards_screen_set_if_updated(
            self, request: HTMXRequest, event_id: str, screen_id: str, screen_set_id: int, date: float
    ) -> Template | Reswap:
        file_dependencies: list[Path] = ScreenSet.get_screen_set_file_dependencies(
            event_id, screen_id, screen_set_id)
        if not file_dependencies:
            Message.error(
                request,
                f'Aucune dépendance de fichier trouvée pour l\'ensemble [{screen_set_id}] '
                f'de l\'écran [{screen_id}] de l\'évènement [{event_id}]')
            return self._render_messages(request)
        try:
            last_update: float = file_dependencies[0].lstat().st_mtime
            for dependency in file_dependencies[1:]:
                with suppress(FileNotFoundError):
                    last_update = max(last_update, dependency.lstat().st_mtime)
            if last_update < date:
                return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)
        except FileNotFoundError as fnfe:
            Message.warning(request, f'Fichier [{fnfe.filename}] non trouvé')
            return self._render_messages(request)
        template_name: str = 'boards_screen_set.html'
        event, screen, screen_set = self._load_boards_or_players_screen_set_data(
            request, event_id, screen_id, screen_set_id)
        if event is None:
            return self._render_messages(request)
        return HTMXTemplate(
            template_name=template_name,
            context={
                'event': event,
                'screen': screen,
                'screen_set': screen_set,
                'now': time.time(),
                'last_result_updated': SessionHandler.get_session_last_result_updated(request),
                'last_illegal_move_updated': SessionHandler.get_session_last_illegal_move_updated(request),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
            },
        )

    @get(
        path='/render-players-screen-set-if-updated'
             '/{event_id:str}'
             '/{screen_id:str}'
             '/{screen_set_id:int}'
             '/{date:float}',
        name='render-players-screen-set-if-updated',
    )
    async def htmx_render_players_screen_set_if_updated(
            self, request: HTMXRequest, event_id: str, screen_id: str, screen_set_id: int, date: float
    ) -> Template | Reswap:
        file_dependencies: list[Path] = ScreenSet.get_screen_set_file_dependencies(
            event_id, screen_id, screen_set_id)
        if not file_dependencies:
            Message.error(
                request,
                f'Aucune dépendance de fichier trouvée pour l\'ensemble [{screen_set_id}] de l\'écran [{screen_id}] '
                f'de l\'évènement [{event_id}]')
            return self._render_messages(request)
        try:
            last_update: float = file_dependencies[0].lstat().st_mtime
            for dependency in file_dependencies[1:]:
                with suppress(FileNotFoundError):
                    last_update = max(last_update, dependency.lstat().st_mtime)
            if last_update < date:
                return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)
        except FileNotFoundError as fnfe:
            Message.warning(request, f'Fichier [{fnfe.filename}] non trouvé')
            return self._render_messages(request)
        template_name: str = 'players_screen_set.html'
        event, screen, screen_set = self._load_boards_or_players_screen_set_data(
            request, event_id, screen_id, screen_set_id)
        if event is None:
            return self._render_messages(request)
        return HTMXTemplate(
            template_name=template_name,
            context={
                'event': event,
                'screen': screen,
                'screen_set': screen_set,
                'now': time.time(),
            },
        )

    @get(
        path='/download-event-tournaments/{event_id:str}',
        name='download-event-tournaments'
    )
    async def htmx_download_event_tournaments(self, request: HTMXRequest, event_id: str) -> Response[bytes] | Template:
        error: str
        event: Event = Event(event_id, True)
        if not event.errors:
            tournament_files: list[Path] = [
                tournament.file
                for tournament in event.tournaments.values()
                if tournament.file.exists()
            ]
            if tournament_files:
                archive = BytesIO()
                with ZipFile(archive, 'w') as zip_archive:
                    for tournament_file in tournament_files:
                        zip_entry: ZipInfo = ZipInfo(tournament_file.name)
                        with open(tournament_file, 'rb') as tournament_handler:
                            zip_archive.writestr(
                                zip_entry, tournament_handler.read())
                return Response(content=bytes(archive.getbuffer()), media_type='application/zip')
            else:
                error = f'Aucun fichier de tournoi pour l\'évènement [{event_id}]'
        else:
            error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
        Message.error(
            request,
            f'Le téléchargement des fichiers Papi de l\'évènement [{event_id}] a échoué ({error})')
        return self._render_messages(request)

    @get(
        path='/download-tournament/{event_id:str}/{tournament_uniq_id:str}',
        name='download-tournament'
    )
    async def htmx_download_tournament(
            self, request: HTMXRequest, event_id: str, tournament_uniq_id: str
    ) -> File | Template:
        error: str
        event: Event = Event(event_id, True)
        if not event.errors:
            try:
                tournament: Tournament = event.tournaments[tournament_uniq_id]
                if tournament.file.exists():
                    return File(path=tournament.file, filename=tournament.file.name)
                else:
                    error = f'aucun fichier pour le tournoi [{tournament_uniq_id}]'
            except KeyError:
                error = f'tournoi [{tournament_uniq_id}] introuvable'
        else:
            error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
        Message.error(
            request,
            f'Le téléchargement du fichier Papi du tournoi [{event_id}/{tournament_uniq_id}] a échoué ({error})')
        return self._render_messages(request)


class AdminController(AController):
    @staticmethod
    def _admin_render_index(
        request: HTMXRequest,
        events: list[Event],
        admin_main_selector: str = '',
        admin_event: Event = None,
        admin_event_selector: str = '',
    ) -> Template:
        context: dict = {
            'papi_web_info': papi_web_info,
            'papi_web_config': PapiWebConfig(),
            'odbc_drivers': odbc_drivers(),
            'access_driver': access_driver(),
            'events': events,
            'messages': Message.messages(request),
            'admin_main_selector_options': {
                '': '-- Configuration de Papi-web',
                '@list-events': '-- Liste des évènements',
            },
            'admin_main_selector': admin_event.id if admin_event else admin_main_selector,
            'admin_event': admin_event,
            'admin_event_selector_options': {
                '': 'Configuration',
                '@tournaments': 'Tournois',
                '@screens': 'Écrans',
                '@families': 'Familles d\'écrans',
                '@rotators': 'Écrans rotatifs',
                '@timers': 'Chronomètre',
                '@messages': 'Messages',
                '@check_in': 'Pointage',
                '@pairings': 'Appariements',
            },
            'admin_event_selector': admin_event_selector,
        }
        return HTMXTemplate(
            template_name="admin.html",
            context=context)

    @get(
        path='/admin',
        name='admin-render-index'
    )
    async def admin_render_index(self, request: HTMXRequest) -> Template | Redirect:
        events: list[Event] = get_events_sorted_by_name(True)
        return self._admin_render_index(request, events)

    @post(
        path='/admin-update-header',
        name='admin-update-header'
    )
    async def htmx_admin_update_header(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        error: str
        events_by_id = get_events_by_id(load_screens=False, with_tournaments_only=False)
        events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
        admin_main_selector: str = data.get('admin_main_selector', '')
        admin_event_selector: str = data.get('admin_event_selector', '')
        admin_event: Event | None = None
        try:
            if admin_main_selector == '':
                pass
            elif admin_main_selector == '@list-events':
                pass
            elif admin_main_selector:
                admin_event: Event = events_by_id[admin_main_selector]
            return self._admin_render_index(request, events, admin_main_selector, admin_event, admin_event_selector)
        except KeyError:
            Message.error(request, f'Évènement [{admin_main_selector}] introuvable')
        return self._render_messages(request)

    @staticmethod
    def _admin_validate_event_update_data(
            admin_event: Event | None,
            events_by_id: dict[str, Event],
            data: dict[str, str] | None = None,
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        event_uniq_id: str = data.get('event_uniq_id')
        if not event_uniq_id:
            errors['event_uniq_id'] = 'Veuillez entrer l\'identifiant de l\'évènement.'
        else:
            if admin_event:
                if event_uniq_id != admin_event.id and event_uniq_id in events_by_id:
                    errors['event_uniq_id'] = f'Un autre évènement avec l\'identifiant [{event_uniq_id}] existe déjà.'
            else:
                if event_uniq_id in events_by_id:
                    errors['event_uniq_id'] = f'L\'évènement [{event_uniq_id}] existe déjà.'
        event_name: str = data.get('event_name')
        if not event_name:
            errors['event_name'] = 'Veuillez entrer le nom de l\'évènement.'
        try:
            event_record_illegal_moves: int = int(data.get('event_record_illegal_moves'))
            assert 0 <= event_record_illegal_moves <= 3
        except (ValueError, AssertionError):
            errors['event_record_illegal_moves'] = 'La valeur entrée n\'est pas valide.'
        try:
            event_allow_deletion: bool = bool(data.get('event_allow_deletion'))
        except ValueError:
            errors['event_allow_deletion'] = 'La valeur entrée n\'est pas valide.'
        return errors

    @staticmethod
    def _admin_event_render_edit_configuration_modal(
            admin_event: Event,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        return HTMXTemplate(
            template_name='admin_event_edit_configuration_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'admin_event': admin_event,
                'data': data,
                'errors': errors,
                'record_illegal_moves_options': {
                    '0': 'Aucun enregistrement des coups illégaux',
                    '1': 'Maximum 1 coup illégal',
                    '2': 'Maximum 2 coups illégaux',
                    '3': 'Maximum 3 coups illégaux',
                },
            })

    @post(
        path='/admin-event-render-edit-configuration-modal',
        name='admin-event-render-edit-configuration-modal'
    )
    async def htmx_admin_event_render_edit_configuration_modal(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        events_by_id: dict[str, Event] = get_events_by_id(load_screens=False, with_tournaments_only=False)
        admin_event_id: str = data.get('admin_event_id')
        admin_event: Event | None = None
        if admin_event_id:
            try:
                admin_event: Event = events_by_id[admin_event_id]
                data: dict[str, str] = {
                    'event_uniq_id': admin_event.id,
                    'event_name': admin_event.name,
                    'event_css': admin_event.css,
                    'event_update_password': admin_event.update_password,
                    'event_record_illegal_moves': admin_event.record_illegal_moves,
                    'event_allow_deletion': admin_event.allow_deletion,
                }
            except KeyError:
                Message.error(request, f'L\'évènement [{admin_event_id}] est introuvable.')
                return self._render_messages(request)
        else:
            data: dict[str, str] = {}
        errors: dict[str, str] = self._admin_validate_event_update_data(admin_event, events_by_id, data)
        return self._admin_event_render_edit_configuration_modal(admin_event, data, errors)

    @post(
        path='/admin-event-update-configuration',
        name='admin-event-update-configuration'
    )
    async def htmx_admin_event_update_configuration(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        logger.warning(f'data=[{data}]')
        events_by_id: dict[str, Event] = get_events_by_id(load_screens=False, with_tournaments_only=False)
        admin_event_id: str = data.get('admin_event_id')
        admin_event: Event | None = None
        if admin_event_id:
            try:
                admin_event = events_by_id[admin_event_id]
            except KeyError:
                Message.error(request, f'L\'évènement [{admin_event_id}] est introuvable.')
                events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
                return self._admin_render_index(request, events, admin_main_selector='@list-events')
        errors: dict[str, str] = self._admin_validate_event_update_data(admin_event, events_by_id, data)
        if errors:
            return self._admin_event_render_edit_configuration_modal(admin_event, data, errors)
        if admin_event:
            # TODO Update the event (if data['event_uniq_id'] != admin_event.id delete events_by_id[admin_event.id])
            # admin_event: Event = UPDATE_EVENT(data)
            # Message.success(request, f'L\'évènement [{admin_event.id}] a été modifié.')
            # events_by_id[admin_event.id] = admin_event
            events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
            # return _admin_render_index(request, events, admin_event=admin_event)
            Message.error(
                request, f'La modification des évènements par l\'interface web n\'est pas encore implémentée.')
            return self._admin_render_index(request, events, admin_event=admin_event, admin_event_selector='')
        else:
            # TODO Create the event
            # admin_event: Event = CREATE_EVENT(data)
            # Message.success(request, f'L\'évènement [{admin_event.id}] a été créé.')
            # events_by_id[admin_event.id] = admin_event
            events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
            # return _admin_render_index(request, events, admin_event=admin_event)
            Message.error(request, f'La création des évènements par l\'interface web n\'est pas encore implémentée.')
            return self._admin_render_index(request, events, admin_main_selector='@list-events')

    @staticmethod
    def _admin_validate_event_delete_data(
            admin_event: Event | None,
            data: dict[str, str] | None = None,
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        event_uniq_id: str = data.get('event_uniq_id')
        if not event_uniq_id:
            errors['event_uniq_id'] = 'Veuillez entrer l\'identifiant de l\'évènement.'
        elif event_uniq_id != admin_event.id:
            errors['event_uniq_id'] = f'L\'identifiant entré n\'est pas valide.'
        return errors

    @staticmethod
    def _admin_event_render_delete_modal(
            admin_event: Event,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        return HTMXTemplate(
            template_name='admin_event_delete_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'admin_event': admin_event,
                'data': data,
                'errors': errors,
            })

    @post(
        path='/admin-event-render-delete-modal',
        name='admin-event-render-delete-modal'
    )
    async def htmx_admin_event_render_delete_modal(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        events_by_id: dict[str, Event] = get_events_by_id(load_screens=False, with_tournaments_only=False)
        admin_event_id: str = data.get('admin_event_id')
        try:
            admin_event: Event = events_by_id[admin_event_id]
            data: dict[str, str] = {}
            errors: dict[str, str] = self._admin_validate_event_delete_data(admin_event, data)
            return self._admin_event_render_delete_modal(admin_event, data, errors)
        except KeyError:
            Message.error(request, f'L\'évènement [{admin_event_id}] est introuvable.')
            return self._render_messages(request)

    @post(
        path='/admin-event-delete',
        name='admin-event-delete'
    )
    async def htmx_admin_event_delete(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        logger.warning(f'data=[{data}]')
        events_by_id: dict[str, Event] = get_events_by_id(load_screens=False, with_tournaments_only=False)
        admin_event_id: str = data.get('admin_event_id')
        try:
            admin_event: Event = events_by_id[admin_event_id]
            errors: dict[str, str] = self._admin_validate_event_delete_data(admin_event, data)
            if errors:
                return self._admin_event_render_edit_configuration_modal(admin_event, data, errors)
            # TODO Delete the event
            # DELETE_EVENT(data)
            # Message.success(request, f'L\'évènement [{admin_event.id}] a été supprimé.')
            # del events_by_id[admin_event.id]
            events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
            Message.error(
                request, f'La suppression des évènements par l\'interface web n\'est pas encore implémentée.')
        except KeyError:
            Message.error(request, f'L\'évènement [{admin_event_id}] est introuvable.')
        events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
        return self._admin_render_index(request, events, admin_main_selector='@list-events')

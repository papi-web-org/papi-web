from zipfile import ZipFile, ZipInfo
from io import BytesIO
from contextlib import suppress
from pathlib import Path

import time

from logging import Logger

from litestar import get, Response, put, delete, patch
from litestar.response import Template, Redirect, File
from litestar.status_codes import HTTP_200_OK, HTTP_304_NOT_MODIFIED
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, Reswap, ClientRedirect, ClientRefresh

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.board import Board
from data.event import Event
from data.player import Player
from data.rotator import Rotator
from data.screen import AScreen
from data.screen_set import ScreenSet
from data.tournament import Tournament
from data.util import Result
from database.sqlite import EventDatabase
from web.messages import Message
from web.session import SessionHandler
from web.urls import index_url, event_url
from web.views import AController

logger: Logger = get_logger()


class UserController(AController):
    @get(
        path='/event/{event_uniq_id:str}',
        name='render-event'
    )
    async def render_event(self, request: HTMXRequest, event_uniq_id: str) -> Template | Redirect:
        event: Event = Event(event_uniq_id, True)
        if event.errors:
            for error in event.errors:
                Message.error(request, error)
            return Redirect(path=index_url(request))
        return HTMXTemplate(
            template_name="event.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'event': event,
                'messages': Message.messages(request),
                'now': time.time(),
            })

    @get(
        path='/render-event-if-updated/{event_uniq_id:str}/{date:float}',
        name='render-event-if-updated',
    )
    async def htmx_render_event_if_updated(
            self, request: HTMXRequest, event_uniq_id: str, date: float
    ) -> Template | ClientRefresh | Reswap:
        file_dependencies: list[Path] = Event.get_event_file_dependencies(event_uniq_id)
        if file_dependencies:
            try:
                last_update: float = file_dependencies[0].lstat().st_mtime
                for dependency in file_dependencies[1:]:
                    with suppress(FileNotFoundError):
                        last_update = max(last_update, dependency.lstat().st_mtime)
                        if last_update > date:
                            return ClientRefresh()
                return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)
            except FileNotFoundError as fnfe:
                Message.warning(request, f'Fichier [{fnfe.filename}] non trouvé')
        else:
            Message.error(
                request, f'Aucune dépendance de fichier trouvée pour l\'évènement [{event_uniq_id}]')
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
            })

    @get(
        path='/screen/{event_uniq_id:str}/{screen_id:str}',
        name='render-screen',
    )
    async def render_screen(self, request: HTMXRequest, event_uniq_id: str, screen_id: str) -> Template | Redirect:
        event: Event = Event(event_uniq_id, True)
        error: str
        redirect_to: str
        if not event.errors:
            try:
                screen: AScreen = event.screens[screen_id]
                return self._render_screen(request, event=event, screen=screen, )
            except KeyError:
                error = f'écran [{screen_id}] introuvable'
                redirect_to = event_url(request, event_uniq_id)
        else:
            error = f'erreur au chargement de l\'évènement [{event_uniq_id}] : [{", ".join(event.errors)}]'
            redirect_to = index_url(request)
        Message.error(
            request, f'L\'affichage de l\'écran [{event_uniq_id}/{screen_id}] a échoué ({error})')
        return Redirect(path=redirect_to)

    @get(
        path='/render-screen-if-updated/{event_uniq_id:str}/{screen_id:str}/{date:float}',
        name='render-screen-if-updated',
    )
    async def htmx_render_screen_if_updated(
            self, request: HTMXRequest, event_uniq_id: str, screen_id: str, date: float
    ) -> Template | ClientRefresh | Reswap:
        file_dependencies: list[Path] = AScreen.get_screen_file_dependencies(
            event_uniq_id, screen_id)
        if not file_dependencies:
            Message.error(
                request,
                f'Aucune dépendance de fichier trouvée pour l\'écran [{screen_id}] de l\'évènement [{event_uniq_id}]')
        else:
            try:
                for dependency in file_dependencies:
                    with suppress(FileNotFoundError):
                        if dependency.lstat().st_mtime > date:
                            return ClientRefresh()
                return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)
            except FileNotFoundError as fnfe:
                Message.warning(request, f'Fichier [{fnfe.filename}] non trouvé')
        return self._render_messages(request)

    def _render_rotator_screen(
            self, request: HTMXRequest, event_uniq_id: str, rotator_id: str, rotator_screen_index: int = 0,
    ) -> Template | Redirect | ClientRedirect:
        event: Event = Event(event_uniq_id, True)
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
                redirect_to = event_url(request, event_uniq_id)
        else:
            error = f'erreur au chargement de l\'évènement [{event_uniq_id}] : [{", ".join(event.errors)}]'
            redirect_to = index_url(request)
        Message.error(
            request, f'L\'affichage de l\'écran rotatif [{event_uniq_id}/{rotator_id}] a échoué ({error})')
        return self._redirect_response(request, redirect_to)

    @get(
        path='/rotator/{event_uniq_id:str}/{rotator_id:str}',
        name='render-rotator'
    )
    async def render_rotator(
            self, request: HTMXRequest, event_uniq_id: str, rotator_id: str
    ) -> Template | Redirect:
        return self._render_rotator_screen(request, event_uniq_id, rotator_id)

    @get(
        path='/render-rotator-screen/{event_uniq_id:str}/{rotator_id:str}/{rotator_screen_index:int}',
        name='render-rotator-screen'
    )
    async def htmx_render_rotator_screen(
            self, request: HTMXRequest, event_uniq_id: str, rotator_id: str, rotator_screen_index: int
    ) -> Template | ClientRedirect:
        return self._render_rotator_screen(request, event_uniq_id, rotator_id, rotator_screen_index)

    def _load_boards_screen_board_result_modal_data(
            self, request: HTMXRequest, event_uniq_id: str, tournament_uniq_id: str, board_id: int, screen_id: str,
    ) -> tuple[Event | None, Tournament | None, Board | None, AScreen | None, ]:
        error: str
        event: Event = Event(event_uniq_id, True)
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
                error = f'gestion des résultats non autorisée pour \'évènement [{event_uniq_id}]'
        else:
            error = f'erreur au chargement de l\'évènement [{event_uniq_id}] : [{", ".join(event.errors)}]'
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
             '/{event_uniq_id:str}'
             '/{tournament_uniq_id:str}'
             '/{board_id:int}'
             '/{screen_id:str}',
        name='render-boards-screen-board-result-modal'
    )
    async def htmx_render_boards_screen_board_result_modal(
            self, request: HTMXRequest, event_uniq_id: str, tournament_uniq_id: str, board_id: int, screen_id: str,
    ) -> Template:
        event, tournament, board, screen = self._load_boards_screen_board_result_modal_data(
            request, event_uniq_id, tournament_uniq_id, board_id, screen_id)
        if event is None:
            return self._render_messages(request)
        return self._render_boards_screen_board_result_modal(event, tournament, board, screen)

    def _load_boards_screen_board_row_data(
            self, request: HTMXRequest, event_uniq_id: str, tournament_uniq_id: str, board_id: int, screen_id: str,
    ) -> tuple[Event | None, Tournament | None, Board | None, AScreen | None]:
        error: str
        event: Event = Event(event_uniq_id, True)
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
                error = f'gestion des résultats non autorisée pour \'évènement [{event_uniq_id}]'
        else:
            error = f'erreur au chargement de l\'évènement [{event_uniq_id}] : [{", ".join(event.errors)}]'
        Message.error(request, f'L\'écriture du résultat à échoué ({error})')
        return None, None, None, None,

    def _render_boards_screen_board_row(
            self,
            request: HTMXRequest,
            event_uniq_id: str,
            tournament_uniq_id: str,
            board_id: int,
            screen_id: str,
    ) -> Template:
        template_name: str = 'boards_screen_board_row.html'
        event, tournament, board, screen = self._load_boards_screen_board_row_data(
            request, event_uniq_id, tournament_uniq_id, board_id, screen_id)
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
             '/{event_uniq_id:str}'
             '/{tournament_uniq_id:str}'
             '/{round:int}'
             '/{board_id:int}'
             '/{result:int}'
             '/{screen_id:str}',
        name='add-board-result'
    )
    async def htmx_add_board_result(
            self, request: HTMXRequest,
            event_uniq_id: str, tournament_uniq_id: str, round: int, board_id: int, result: int | None, screen_id: str,
    ) -> Template:
        event, tournament, board, screen = self._load_boards_screen_board_row_data(
            request, event_uniq_id, tournament_uniq_id, board_id, screen_id)
        if event is None:
            return self._render_messages(request)
        if result not in Result.imputable_results():
            Message.error(
                request, f'L\'écriture du résultat a échoué (résultat invalide [{result}])')
            return self._render_messages(request)
        tournament.add_result(board, Result.from_papi_value(result))
        SessionHandler.set_session_last_result_updated(request, tournament_uniq_id, round, board_id)
        return self._render_boards_screen_board_row(request, event_uniq_id, tournament_uniq_id, board_id, screen_id)

    @delete(
        path='/board-result/{event_uniq_id:str}/{tournament_uniq_id:str}/{round:int}/{board_id:int}/{screen_id:str}',
        name='delete-board-result',
        status_code=HTTP_200_OK,
    )
    async def htmx_delete_board_result(
            self, request: HTMXRequest, event_uniq_id: str, tournament_uniq_id: str, round: int, board_id: int,
            screen_id: str,
    ) -> Template:
        event, tournament, board, screen = self._load_boards_screen_board_row_data(
            request, event_uniq_id, tournament_uniq_id, board_id, screen_id)
        if event is None:
            return self._render_messages(request)
        with suppress(ValueError):
            tournament.delete_result(board)
            SessionHandler.set_session_last_result_updated(request, tournament_uniq_id, round, board_id)
        return self._render_boards_screen_board_row(request, event_uniq_id, tournament_uniq_id, board_id, screen_id)

    def _load_boards_screen_board_row_illegal_move_data(
            self, request: HTMXRequest, event_uniq_id: str, tournament_uniq_id: str, player_id: int, screen_id: str,
    ) -> tuple[Event | None, Tournament | None, Player | None, Board | None, AScreen | None]:
        error: str
        event: Event = Event(event_uniq_id, True)
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
                error = f'gestion des coups illégaux non autorisée pour \'évènement [{event_uniq_id}]'
        else:
            error = f'erreur au chargement de l\'évènement [{event_uniq_id}] : [{", ".join(event.errors)}]'
        Message.error(
            request, f'L\'opération sur les coups illégaux a échoué ({error})')
        return None, None, None, None, None,

    @put(
        path='/player-illegal-move/{event_uniq_id:str}/{tournament_uniq_id:str}/{player_id:int}/{screen_id:str}',
        name='put-player-illegal-move',
        status_code=HTTP_200_OK,
    )
    async def htmx_add_illegal_move(
            self, request: HTMXRequest, event_uniq_id: str, tournament_uniq_id: str, player_id: int, screen_id: str,
    ) -> Template:
        event, tournament, player, board, screen = self._load_boards_screen_board_row_illegal_move_data(
            request, event_uniq_id, tournament_uniq_id, player_id, screen_id)
        if event is None:
            return self._render_messages(request)
        tournament.store_illegal_move(player)
        SessionHandler.set_session_last_illegal_move_updated(request, tournament_uniq_id, player_id)
        return self._render_boards_screen_board_row(request, event_uniq_id, tournament_uniq_id, board.id, screen_id)

    @delete(
        path='/player-illegal-move/{event_uniq_id:str}/{tournament_uniq_id:str}/{player_id:int}/{screen_id:str}',
        name='delete-player-illegal-move',
        status_code=HTTP_200_OK,
    )
    async def htmx_delete_illegal_move(
            self, request: HTMXRequest, event_uniq_id: str, tournament_uniq_id: str, player_id: int, screen_id: str,
    ) -> Template:
        event, tournament, player, board, screen = self._load_boards_screen_board_row_illegal_move_data(
            request, event_uniq_id, tournament_uniq_id, player_id, screen_id)
        if event is None:
            return self._render_messages(request)
        if not tournament.delete_illegal_move(player):
            Message.error(
                request,
                f'Pas de coup illégal trouvé pour le·la joueur·euse {player_id} dans le tournoi [{tournament.uniq_id}]')
            return self._render_messages(request)
        SessionHandler.set_session_last_illegal_move_updated(request, tournament_uniq_id, player_id)
        return self._render_boards_screen_board_row(request, event_uniq_id, tournament_uniq_id, board.id, screen_id)

    def _load_boards_screen_player_row_player_cell_data(
            self, request: HTMXRequest, event_uniq_id: str, tournament_uniq_id: str, player_id: int, screen_id: str,
    ) -> tuple[Event | None, Tournament | None, Player | None, AScreen | None]:
        error: str
        event: Event = Event(event_uniq_id, True)
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
                error = f'gestion du pointage non autorisée pour l\'évènement [{event_uniq_id}]'
        else:
            error = f'erreur au chargement de l\'évènement [{event_uniq_id}] : [{", ".join(event.errors)}]'
        Message.error(request, f'L\'opération a échoué ({error})')
        return None, None, None, None,

    def _render_boards_screen_player_row_player_cell(
            self, request: HTMXRequest, event_uniq_id: str, tournament_uniq_id: str, player_id: int, screen_id: str,
    ) -> Template:
        template_name: str = 'boards_screen_player_row_player_cell.html'
        event, tournament, player, screen = self._load_boards_screen_player_row_player_cell_data(
            request, event_uniq_id, tournament_uniq_id, player_id, screen_id)
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
        path='/toggle-player-check-in/{event_uniq_id:str}/{tournament_uniq_id:str}/{player_id:int}/{screen_id:str}',
        name='toggle-player-check-in',
    )
    async def htmx_toggle_player_check_in(
            self, request: HTMXRequest, event_uniq_id: str, screen_id: str, tournament_uniq_id: str, player_id: int
    ) -> Template:
        event, tournament, player, screen = self._load_boards_screen_player_row_player_cell_data(
            request, event_uniq_id, tournament_uniq_id, player_id, screen_id)
        if not event:
            return self._render_messages(request)
        tournament.check_in_player(player, not player.check_in)
        SessionHandler.set_session_last_check_in_updated(request, tournament_uniq_id, player_id)
        return self._render_boards_screen_player_row_player_cell(
            request, event_uniq_id, tournament_uniq_id, player_id, screen_id)

    @staticmethod
    def _load_boards_or_players_screen_set_data(
            request: HTMXRequest, event_uniq_id: str, screen_id: str, screen_set_id: int,
    ) -> tuple[Event | None, AScreen | None, ScreenSet | None, ]:
        error: str
        event: Event = Event(event_uniq_id, True)
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
            error = f'erreur au chargement de l\'évènement [{event_uniq_id}] : [{", ".join(event.errors)}]'
        Message.error(
            request, f'La mise à jour de l\'écran [{event_uniq_id}/{screen_id}/{screen_set_id}] a échoué ({error})')
        return None, None, None,

    @get(
        path='/render-boards-screen-set-if-updated'
             '/{event_uniq_id:str}'
             '/{screen_id:str}'
             '/{screen_set_id:int}'
             '/{date:float}',
        name='render-boards-screen-set-if-updated',
    )
    async def htmx_render_boards_screen_set_if_updated(
            self, request: HTMXRequest, event_uniq_id: str, screen_id: str, screen_set_id: int, date: float
    ) -> Template | Reswap:
        file_dependencies: list[Path] = ScreenSet.get_screen_set_file_dependencies(
            event_uniq_id, screen_id, screen_set_id)
        if not file_dependencies:
            Message.error(
                request,
                f'Aucune dépendance de fichier trouvée pour l\'ensemble [{screen_set_id}] '
                f'de l\'écran [{screen_id}] de l\'évènement [{event_uniq_id}]')
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
            request, event_uniq_id, screen_id, screen_set_id)
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
             '/{event_uniq_id:str}'
             '/{screen_id:str}'
             '/{screen_set_id:int}'
             '/{date:float}',
        name='render-players-screen-set-if-updated',
    )
    async def htmx_render_players_screen_set_if_updated(
            self, request: HTMXRequest, event_uniq_id: str, screen_id: str, screen_set_id: int, date: float
    ) -> Template | Reswap:
        file_dependencies: list[Path] = ScreenSet.get_screen_set_file_dependencies(
            event_uniq_id, screen_id, screen_set_id)
        if not file_dependencies:
            Message.error(
                request,
                f'Aucune dépendance de fichier trouvée pour l\'ensemble [{screen_set_id}] de l\'écran [{screen_id}] '
                f'de l\'évènement [{event_uniq_id}]')
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
            request, event_uniq_id, screen_id, screen_set_id)
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
        path='/download-event-tournaments/{event_uniq_id:str}',
        name='download-event-tournaments'
    )
    async def htmx_download_event_tournaments(
            self, request: HTMXRequest, event_uniq_id: str
    ) -> Response[bytes] | Template:
        error: str
        event: Event = Event(event_uniq_id, True)
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
                error = f'Aucun fichier de tournoi pour l\'évènement [{event_uniq_id}]'
        else:
            error = f'erreur au chargement de l\'évènement [{event_uniq_id}] : [{", ".join(event.errors)}]'
        Message.error(
            request,
            f'Le téléchargement des fichiers Papi de l\'évènement [{event_uniq_id}] a échoué ({error})')
        return self._render_messages(request)

    @get(
        path='/download-tournament/{event_uniq_id:str}/{tournament_uniq_id:str}',
        name='download-tournament'
    )
    async def htmx_download_tournament(
            self, request: HTMXRequest, event_uniq_id: str, tournament_uniq_id: str
    ) -> File | Template:
        error: str
        event: Event = Event(event_uniq_id, True)
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
            error = f'erreur au chargement de l\'évènement [{event_uniq_id}] : [{", ".join(event.errors)}]'
        Message.error(
            request,
            f'Le téléchargement du fichier Papi du tournoi [{event_uniq_id}/{tournament_uniq_id}] a échoué ({error})')
        return self._render_messages(request)

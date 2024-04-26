from zipfile import ZipFile, ZipInfo
from io import BytesIO
from contextlib import suppress
from pathlib import Path

import time

from logging import Logger
from typing import Annotated

from litestar import get, post, Response, put, delete, patch
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect, File
from litestar.status_codes import HTTP_200_OK, HTTP_304_NOT_MODIFIED
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, Reswap, ClientRedirect, ClientRefresh

from common.logger import get_logger
from common.papi_web_config import PAPI_WEB_COPYRIGHT, PAPI_WEB_URL, PAPI_WEB_VERSION, PapiWebConfig
from data.board import Board
from data.event import Event, get_events_by_name
from data.player import Player
from data.rotator import Rotator
from data.screen import AScreen
from data.screen_set import ScreenSet
from data.tournament import Tournament
from data.util import Result
from database.access import access_driver, odbc_drivers
from web.messages import Message
from web.session import set_session_last_illegal_move_updated, get_session_last_illegal_move_updated, \
    set_session_last_result_updated, set_session_last_check_in_updated, get_session_last_check_in_updated, \
    get_session_last_result_updated, store_password, get_stored_password
from web.urls import index_url, event_url

logger: Logger = get_logger()

papi_web_info: dict[str, str] = {
    'version': PAPI_WEB_VERSION,
    'url': PAPI_WEB_URL,
    'copyright': PAPI_WEB_COPYRIGHT,
}


def _redirect_response(request: HTMXRequest, redirect_to: str) -> Redirect | ClientRedirect:
    return ClientRedirect(redirect_to=redirect_to) if request.htmx else Redirect(path=redirect_to)


def _render_messages(request: HTMXRequest) -> Template:
    template_name: str = 'messages.html'
    return HTMXTemplate(
        template_name=template_name,
        re_swap="afterbegin",
        re_target="#messages",
        context={
            'messages': Message.messages(request),
        })


@get(
    path='/',
    name='index'
)
async def index(request: HTMXRequest) -> Template:
    events: list[Event] = get_events_by_name(True)
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


@get(
    path='/event/{event_id:str}',
    name='render-event'
)
async def render_event(request: HTMXRequest, event_id: str) -> Template | Redirect:
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
        request: HTMXRequest, event_id: str, date: float
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
    return _render_messages(request)


@post(
    path='/login/{event_id:str}',
    name='login',
)
async def htmx_login(
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
        store_password(request, event, data['password'])
        return ClientRefresh()
    if data['password'] == '':
        Message.warning(request, 'Veuillez indiquer le code d\'accès.')
    else:
        Message.error(request, 'Code d\'accès incorrect.')
        store_password(request, event, None)
    return _render_messages(request)


def _event_login_needed(request: HTMXRequest, event: Event, screen: AScreen | None = None) -> bool:
    if screen is not None:
        if not screen.update:
            return False
    if not event.update_password:
        return False
    session_password: str | None = get_stored_password(request, event)
    logger.debug('session_password=%s', "*" * (8 if session_password else 0))
    if session_password is None:
        Message.error(request,
                      'Un code d\'accès est nécessaire pour accéder à l\'interface de saisie des résultats.')
        return True
    if session_password != event.update_password:
        Message.error(request, 'Code d\'accès incorrect.')
        store_password(request, event, None)
        return True
    return False


def _render_screen(
        request: HTMXRequest, event: Event,
        screen: AScreen = None,
        rotator: Rotator = None, rotator_screen_index: int = 0,
) -> Template:
    the_screen: AScreen = screen if screen else rotator.screens[rotator_screen_index]
    login_needed: bool = _event_login_needed(request, event, the_screen)
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
            'last_result_updated': get_session_last_result_updated(request),
            'last_illegal_move_updated': get_session_last_illegal_move_updated(request),
            'last_check_in_updated': get_session_last_check_in_updated(request),
            'messages': Message.messages(request),
        })


@get(
    path='/screen/{event_id:str}/{screen_id:str}',
    name='render-screen',
)
async def render_screen(request: HTMXRequest, event_id: str, screen_id: str) -> Template | Redirect:
    event: Event = Event(event_id, True)
    error: str
    redirect_to: str
    if not event.errors:
        try:
            screen: AScreen = event.screens[screen_id]
            return _render_screen(request, event=event, screen=screen, )
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
        request: HTMXRequest, event_id: str, screen_id: str, date: float
) -> Template | ClientRefresh | Reswap:
    file_dependencies: list[Path] = AScreen.get_screen_file_dependencies(
        event_id, screen_id)
    if not file_dependencies:
        Message.error(
            request,
            f'Aucune dépendance de fichier trouvée pour l\'écran [{screen_id}] de l\'évènement [{event_id}]')
        return _render_messages(request)
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
        return _render_messages(request)


def _render_rotator_screen(
        request: HTMXRequest, event_id: str, rotator_id: str, rotator_screen_index: int = 0,
) -> Template | Redirect | ClientRedirect:
    event: Event = Event(event_id, True)
    error: str
    redirect_to: str
    if not event.errors:
        try:
            rotator: Rotator = event.rotators[rotator_id]
            return _render_screen(
                request, event=event, rotator=rotator, rotator_screen_index=rotator_screen_index % len(rotator.screens))
        except KeyError:
            error = f'écran rotatif [{rotator_id}] introuvable'
            redirect_to = event_url(request, event_id)
    else:
        error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
        redirect_to = index_url(request)
    Message.error(
        request, f'L\'affichage de l\'écran rotatif [{event_id}/{rotator_id}] a échoué ({error})')
    return _redirect_response(request, redirect_to)


@get(
    path='/rotator/{event_id:str}/{rotator_id:str}',
    name='render-rotator'
)
async def render_rotator(
        request: HTMXRequest, event_id: str, rotator_id: str
) -> Template | Redirect:
    return _render_rotator_screen(request, event_id, rotator_id)


@get(
    path='/render-rotator-screen/{event_id:str}/{rotator_id:str}/{rotator_screen_index:int}',
    name='render-rotator-screen'
)
async def htmx_render_rotator_screen(
        request: HTMXRequest, event_id: str, rotator_id: str, rotator_screen_index: int
) -> Template | ClientRedirect:
    return _render_rotator_screen(request, event_id, rotator_id, rotator_screen_index)


def _load_boards_screen_board_result_modal_data(
        request: HTMXRequest, event_id: str, tournament_id: str, board_id: int, screen_id: str,
) -> tuple[Event | None, Tournament | None, Board | None, AScreen | None, ]:
    error: str
    event: Event = Event(event_id, True)
    if not event.errors:
        if not _event_login_needed(request, event):
            try:
                tournament: Tournament = event.tournaments[tournament_id]
                if tournament.current_round:
                    try:
                        board: Board = tournament.boards[board_id - 1]
                        try:
                            screen: AScreen = event.screens[screen_id]
                            return event, tournament, board, screen
                        except KeyError:
                            error = f'échiquier [{board_id}] introuvable pour le tournoi [{tournament.id}]'
                    except KeyError:
                        error = f'échiquier [{board_id}] introuvable pour le tournoi [{tournament.id}]'
                else:
                    error = f'aucun appariement trouvé pour le tournoi [{tournament_id}]'
            except KeyError:
                error = f'tournoi [{tournament_id}] est introuvable'
        else:
            error = f'gestion des résultats non autorisée pour \'évènement [{event_id}]'
    else:
        error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
    Message.error(
        request, f'L\'affichage de l\'écran de saisie du résultat a échoué ({error})')
    return None, None, None, None,


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
    path='/render-boards-screen-board-result-modal/{event_id:str}/{tournament_id:str}/{board_id:int}/{screen_id:str}',
    name='render-boards-screen-board-result-modal'
)
async def htmx_render_boards_screen_board_result_modal(
        request: HTMXRequest, event_id: str, tournament_id: str, board_id: int, screen_id: str,
) -> Template:
    event, tournament, board, screen = _load_boards_screen_board_result_modal_data(
        request, event_id, tournament_id, board_id, screen_id)
    if event is None:
        return _render_messages(request)
    return _render_boards_screen_board_result_modal(event, tournament, board, screen)


def _load_boards_screen_board_row_data(
        request: HTMXRequest, event_id: str, tournament_id: str, board_id: int, screen_id: str,
) -> tuple[Event | None, Tournament | None, Board | None, AScreen | None]:
    error: str
    event: Event = Event(event_id, True)
    if not event.errors:
        if not _event_login_needed(request, event):
            try:
                tournament: Tournament = event.tournaments[tournament_id]
                if tournament.current_round:
                    try:
                        board: Board = tournament.boards[board_id - 1]
                        try:
                            screen: AScreen = event.screens[screen_id]
                            return event, tournament, board, screen
                        except KeyError:
                            error = f'écran [{screen_id}] introuvable'
                    except KeyError:
                        error = f'échiquier [{board_id}] introuvable pour le tournoi [{tournament.id}]'
                else:
                    error = f'aucun appariement trouvé pour le tournoi [{tournament_id}]'
            except KeyError:
                error = f'tournoi [{tournament_id}] est introuvable'
        else:
            error = f'gestion des résultats non autorisée pour \'évènement [{event_id}]'
    else:
        error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
    Message.error(request, f'L\'écriture du résultat à échoué ({error})')
    return None, None, None, None,


def _render_boards_screen_board_row(
        request: HTMXRequest,
        event_id: str,
        tournament_id: str,
        board_id: int,
        screen_id: str,
) -> Template:
    template_name: str = 'boards_screen_board_row.html'
    event, tournament, board, screen = _load_boards_screen_board_row_data(
        request, event_id, tournament_id, board_id, screen_id)
    if event is None:
        return _render_messages(request)
    return HTMXTemplate(
        template_name=template_name,
        context={
            'event': event,
            'tournament': tournament,
            'board': board,
            'screen': screen,
            'now': time.time(),
            'last_result_updated': get_session_last_result_updated(request),
            'last_illegal_move_updated': get_session_last_illegal_move_updated(request),
            'last_check_in_updated': get_session_last_check_in_updated(request),
        })


@patch(
    path='/board-result/{event_id:str}/{tournament_id:str}/{board_id:int}/{result:int}/{screen_id:str}',
    name='update-board-result'
)
async def htmx_update_board_result(
        request: HTMXRequest, event_id: str, tournament_id: str, board_id: int, result: int | None, screen_id: str,
) -> Template:
    event, tournament, board, screen = _load_boards_screen_board_row_data(
        request, event_id, tournament_id, board_id, screen_id)
    if event is None:
        return _render_messages(request)
    if result not in Result.imputable_results():
        Message.error(
            request, f'L\'écriture du résultat a échoué (résultat invalide [{result}])')
        return _render_messages(request)
    tournament.add_result(board, Result.from_papi_value(result))
    event.store_result(tournament, board, result)
    set_session_last_result_updated(request, tournament_id, board_id)
    return _render_boards_screen_board_row(request, event_id, tournament_id, board_id, screen_id)


@delete(
    path='/board-result/{event_id:str}/{tournament_id:str}/{board_id:int}/{screen_id:str}',
    name='delete-board-result',
    status_code=HTTP_200_OK,
)
async def htmx_remove_board_result(
    request: HTMXRequest, event_id: str, tournament_id: str, board_id: int, screen_id: str,
) -> Template:
    event, tournament, board, screen = _load_boards_screen_board_row_data(
        request, event_id, tournament_id, board_id, screen_id)
    if event is None:
        return _render_messages(request)
    with suppress(ValueError):
        event.remove_result(tournament, board)
        tournament.remove_result(board)
        set_session_last_result_updated(request, tournament_id, board_id)
    return _render_boards_screen_board_row(request, event_id, tournament_id, board_id, screen_id)


def _load_boards_screen_board_row_illegal_move_data(
        request: HTMXRequest, event_id: str, tournament_id: str, player_id: int, screen_id: str,
) -> tuple[Event | None, Tournament | None, Player | None, Board | None, AScreen | None]:
    error: str
    event: Event = Event(event_id, True)
    if not event.errors:
        if not _event_login_needed(request, event):
            try:
                tournament: Tournament = event.tournaments[tournament_id]
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
                            error = f'échiquier [{player.board_id}] introuvable pour le tournoi [{tournament.id}])'
                    except KeyError:
                        error = f'joueur·euse [{player_id}] introuvable pour le tournoi [{tournament.id}])'
                else:
                    error = f'Aucun appariement trouvé pour le tournoi [{tournament_id}]'
            except KeyError:
                error = f'tournoi [{tournament_id}] introuvable'
        else:
            error = f'gestion des coups illégaux non autorisée pour \'évènement [{event_id}]'
    else:
        error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
    Message.error(
        request, f'L\'opération sur les coups illégaux a échoué ({error})')
    return None, None, None, None, None,


@put(
    path='/player-illegal-move/{event_id:str}/{tournament_id:str}/{player_id:int}/{screen_id:str}',
    name='put-player-illegal-move',
    status_code=HTTP_200_OK,
)
async def htmx_add_illegal_move(
        request: HTMXRequest, event_id: str, tournament_id: str, player_id: int, screen_id: str,
) -> Template:
    event, tournament, player, board, screen = _load_boards_screen_board_row_illegal_move_data(
        request, event_id, tournament_id, player_id, screen_id)
    if event is None:
        return _render_messages(request)
    tournament.store_illegal_move(player)
    set_session_last_illegal_move_updated(request, tournament_id, player_id)
    return _render_boards_screen_board_row(request, event_id, tournament_id, board.id, screen_id)


@delete(
    path='/player-illegal-move/{event_id:str}/{tournament_id:str}/{player_id:int}/{screen_id:str}',
    name='delete-player-illegal-move',
    status_code=HTTP_200_OK,
)
async def htmx_delete_illegal_move(
        request: HTMXRequest, event_id: str, tournament_id: str, player_id: int, screen_id: str,
) -> Template:
    event, tournament, player, board, screen = _load_boards_screen_board_row_illegal_move_data(
        request, event_id, tournament_id, player_id, screen_id)
    if event is None:
        return _render_messages(request)
    if not tournament.delete_illegal_move(player):
        Message.error(
            request,
            f'Pas de coup illégal trouvé pour le·la joueur·euse {player_id} dans le tournoi [{tournament.id}]')
        return _render_messages(request)
    set_session_last_illegal_move_updated(request, tournament_id, player_id)
    return _render_boards_screen_board_row(request, event_id, tournament_id, board.id, screen_id)


def _load_boards_screen_player_row_player_cell_data(
        request: HTMXRequest, event_id: str, tournament_id: str, player_id: int, screen_id: str,
) -> tuple[Event | None, Tournament | None, Player | None, AScreen | None]:
    error: str
    event: Event = Event(event_id, True)
    if not event.errors:
        if not _event_login_needed(request, event):
            try:
                tournament: Tournament = event.tournaments[tournament_id]
                if not tournament.current_round:
                    try:
                        player: Player = tournament.players_by_id[player_id]
                        try:
                            screen: AScreen = event.screens[screen_id]
                            return event, tournament, player, screen
                        except KeyError:
                            error = f'L\'écran [{screen_id}] introuvable'
                    except KeyError:
                        error = f'joueur·euse [{player_id}] introuvable pour le tournoi [{tournament.id}])'
                else:
                    error = f'pointage clos pour le tournoi [{tournament_id}]'
            except KeyError:
                error = f'tournoi [{tournament_id}] introuvable'
        else:
            error = f'gestion du pointage non autorisée pour l\'évènement [{event_id}]'
    else:
        error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
    Message.error(request, f'L\'opération a échoué ({error})')
    return None, None, None, None,


def _render_boards_screen_player_row_player_cell(
        request: HTMXRequest, event_id: str, tournament_id: str, player_id: int, screen_id: str,
) -> Template:
    template_name: str = 'boards_screen_player_row_player_cell.html'
    event, tournament, player, screen = _load_boards_screen_player_row_player_cell_data(
        request, event_id, tournament_id, player_id, screen_id)
    if event is None:
        return _render_messages(request)
    return HTMXTemplate(
        template_name=template_name,
        context={
            'event': event,
            'tournament': tournament,
            'player': player,
            'screen': screen,
            'now': time.time(),
            'last_check_in_updated': get_session_last_check_in_updated(request),
        })


@patch(
    path='/toggle-player-check-in/{event_id:str}/{tournament_id:str}/{player_id:int}/{screen_id:str}',
    name='toggle-player-check-in',
)
async def htmx_toggle_player_check_in(
        request: HTMXRequest, event_id: str, screen_id: str, tournament_id: str, player_id: int
) -> Template:
    event, tournament, player, screen = _load_boards_screen_player_row_player_cell_data(
        request, event_id, tournament_id, player_id, screen_id)
    if not event:
        return _render_messages(request)
    tournament.check_in_player(player, not player.check_in)
    set_session_last_check_in_updated(request, tournament_id, player_id)
    return _render_boards_screen_player_row_player_cell(request, event_id, tournament_id, player_id, screen_id)


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
        request: HTMXRequest, event_id: str, screen_id: str, screen_set_id: int, date: float
) -> Template | Reswap:
    file_dependencies: list[Path] = ScreenSet.get_screen_set_file_dependencies(
        event_id, screen_id, screen_set_id)
    if not file_dependencies:
        Message.error(
            request,
            f'Aucune dépendance de fichier trouvée pour l\'ensemble [{screen_set_id}] de l\'écran [{screen_id}] '
            f'de l\'évènement [{event_id}]')
        return _render_messages(request)
    try:
        last_update: float = file_dependencies[0].lstat().st_mtime
        for dependency in file_dependencies[1:]:
            with suppress(FileNotFoundError):
                last_update = max(last_update, dependency.lstat().st_mtime)
        if last_update < date:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)
    except FileNotFoundError as fnfe:
        Message.warning(request, f'Fichier [{fnfe.filename}] non trouvé')
        return _render_messages(request)
    template_name: str = 'boards_screen_set.html'
    event, screen, screen_set = _load_boards_or_players_screen_set_data(
        request, event_id, screen_id, screen_set_id)
    if event is None:
        return _render_messages(request)
    return HTMXTemplate(
        template_name=template_name,
        context={
            'event': event,
            'screen': screen,
            'screen_set': screen_set,
            'now': time.time(),
            'last_result_updated': get_session_last_result_updated(request),
            'last_illegal_move_updated': get_session_last_illegal_move_updated(request),
            'last_check_in_updated': get_session_last_check_in_updated(request),
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
        request: HTMXRequest, event_id: str, screen_id: str, screen_set_id: int, date: float
) -> Template | Reswap:
    file_dependencies: list[Path] = ScreenSet.get_screen_set_file_dependencies(
        event_id, screen_id, screen_set_id)
    if not file_dependencies:
        Message.error(
            request,
            f'Aucune dépendance de fichier trouvée pour l\'ensemble [{screen_set_id}] de l\'écran [{screen_id}] '
            f'de l\'évènement [{event_id}]')
        return _render_messages(request)
    try:
        last_update: float = file_dependencies[0].lstat().st_mtime
        for dependency in file_dependencies[1:]:
            with suppress(FileNotFoundError):
                last_update = max(last_update, dependency.lstat().st_mtime)
        if last_update < date:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)
    except FileNotFoundError as fnfe:
        Message.warning(request, f'Fichier [{fnfe.filename}] non trouvé')
        return _render_messages(request)
    template_name: str = 'players_screen_set.html'
    event, screen, screen_set = _load_boards_or_players_screen_set_data(
        request, event_id, screen_id, screen_set_id)
    if event is None:
        return _render_messages(request)
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
async def htmx_download_event_tournaments(request: HTMXRequest, event_id: str) -> Response[bytes] | Template:
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
    return _render_messages(request)


@get(
    path='/download-tournament/{event_id:str}/{tournament_id:str}',
    name='download-tournament'
)
async def htmx_download_tournament(request: HTMXRequest, event_id: str, tournament_id: str) -> File | Template:
    error: str
    event: Event = Event(event_id, True)
    if not event.errors:
        try:
            tournament: Tournament = event.tournaments[tournament_id]
            if tournament.file.exists():
                return File(path=tournament.file, filename=tournament.file.name)
            else:
                error = f'aucun fichier pour le tournoi [{tournament_id}]'
        except KeyError:
            error = f'tournoi [{tournament_id}] introuvable'
    else:
        error = f'erreur au chargement de l\'évènement [{event_id}] : [{", ".join(event.errors)}]'
    Message.error(
        request,
        f'Le téléchargement du fichier Papi du tournoi [{event_id}/{tournament_id}] a échoué ({error})')
    return _render_messages(request)

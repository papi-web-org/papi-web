from zipfile import ZipFile, ZipInfo
from io import BytesIO
from contextlib import suppress
from pathlib import Path

import math
import time

from logging import Logger
from typing import Annotated

from litestar import Request, get, post, Response
from litestar.enums import RequestEncodingType
from litestar.exceptions import HTTPException
from litestar.params import Body
from litestar.response import Template, Redirect, File
from litestar.status_codes import HTTP_303_SEE_OTHER, HTTP_307_TEMPORARY_REDIRECT

from common.logger import get_logger
from common.papi_web_config import PAPI_WEB_COPYRIGHT, PAPI_WEB_URL, PAPI_WEB_VERSION, PapiWebConfig
from data.board import Board
from data.event import Event, get_events_by_name
from data.rotator import Rotator
from data.screen import AScreen
from data.tournament import Tournament
from data.util import Result, Color
from database.access import access_driver, odbc_drivers
from web.messages import Message
from web.urls import index_url, event_url, screen_url, rotator_screen_url

logger: Logger = get_logger()

papi_web_info: dict[str, str] = {
    'version': PAPI_WEB_VERSION,
    'url': PAPI_WEB_URL,
    'copyright': PAPI_WEB_COPYRIGHT,
}


@get(path='/', name='index')
async def index(request: Request) -> Template:
    events: list[Event] = get_events_by_name(True)
    if len(events) == 0:
        Message.error(request, 'Aucun évènement trouvé')
    return Template(
        template_name="index.html",
        context={
            'papi_web_info': papi_web_info,
            'papi_web_config': PapiWebConfig(),
            'events': events,
            'odbc_drivers': odbc_drivers(),
            'access_driver': access_driver(),
            'messages': Message.messages(request),
        })


def load_event(request: Request, event_id: str) -> Event | None:
    event: Event = Event(event_id, True)
    if event.errors:
        for error in event.errors:
            Message.error(request, error)
        return None
    return event


@get(path='/event/{event_id:str}', name='show-event')
async def show_event(request: Request, event_id: str) -> Template | Redirect:
    event: Event = load_event(request, event_id)
    if event is None:
        return Redirect(
            path=index_url(request),
            status_code=HTTP_307_TEMPORARY_REDIRECT)
    return Template(
        template_name="event.html",
        context={
            'papi_web_info': papi_web_info,
            'event': event,
            'messages': Message.messages(request),
        })


def session_password_key(event: Event) -> str:
    return 'auth-' + event.id


def store_password(request: Request, event: Event, password: str | None):
    request.session[session_password_key(event)] = password


def get_stored_password(request: Request, event: Event) -> str | None:
    return request.session.get(session_password_key(event), None)


def render_screen(
        request: Request, event: Event, screen: AScreen, login_needed: bool, rotator_next_url: str = None,
        rotator_delay: int = None
) -> Template:
    last_result_entered: dict[str, int | str | float] | None = None
    try:
        last_result_entered = request.session['last_result_entered']
    except KeyError:
        pass
    return Template(
        template_name="screen.html",
        context={
            'papi_web_info': papi_web_info,
            'event': event,
            'screen': screen,
            'now': math.floor(time.time()),
            'login_needed': login_needed,
            'rotator_next_url': rotator_next_url,
            'rotator_delay': rotator_delay,
            'last_result_entered': last_result_entered,
            'messages': Message.messages(request),
        })


@post(
    path='/login/{event_id:str}/{screen_id:str}',
    name='login',
)
async def login(
        request: Request,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        event_id: str,
        screen_id: str
) -> Redirect:
    # HTTP_303_SEE_OTHER is used in this POST handler to be redirected with a GET method (otherwise POST is used)
    event: Event = load_event(request, event_id)
    if event is None:
        return Redirect(
            path=index_url(request),
            status_code=HTTP_303_SEE_OTHER,
        )
    if screen_id not in event.screens:
        Message.error(request, f'Écran [{screen_id}] introuvable')
        return Redirect(
            path=event_url(request, event_id),
            status_code=HTTP_303_SEE_OTHER)
    if 'password' not in data:
        Message.warning(request, 'Veuillez indiquer le code d\'accès.')
    elif data['password'] == event.update_password:
        Message.success(request, f'Authentification réussie.')
        store_password(request, event, data['password'])
    else:
        Message.error(request, f'Code d\'accès incorrect.')
        store_password(request, event, None)
    return Redirect(
        path=screen_url(request, event_id, screen_id),
        status_code=HTTP_303_SEE_OTHER)


def event_login_needed(request: Request, event: Event, screen: AScreen | None = None) -> bool:
    if screen is not None:
        if not screen.update:
            return False
    if not event.update_password:
        return False
    session_password: str | None = get_stored_password(request, event)
    logger.info(f'session_password={"*" * len(session_password) if session_password else 0}')
    if session_password is None:
        Message.error(request,
                      f'Un code d\'accès est nécessaire pour accéder à l\'interface de saisie des résultats.')
        return True
    if session_password != event.update_password:
        Message.error(request, f'Code d\'accès incorrect.')
        store_password(request, event, None)
        return True
    return False


@get(
    path='/screen/{event_id:str}/{screen_id:str}',
    name='show-screen',
)
async def show_screen(request: Request, event_id: str, screen_id: str) -> Template | Redirect:
    event: Event = load_event(request, event_id)
    if event is None:
        return Redirect(
            path=index_url(request),
            status_code=HTTP_307_TEMPORARY_REDIRECT)
    if screen_id not in event.screens:
        Message.error(request, f'Écran [{screen_id}] introuvable')
        return Redirect(
            path=event_url(request, event_id),
            status_code=HTTP_307_TEMPORARY_REDIRECT)
    screen: AScreen = event.screens[screen_id]
    login_needed: bool = event_login_needed(request, event, screen)
    return render_screen(request, event, screen, login_needed)


@get(path='/rotator/{event_id:str}/{rotator_id:str}', name='show-rotator')
async def show_rotator(
        request: Request, event_id: str, rotator_id: str) -> Redirect:
    return Redirect(
        path=rotator_screen_url(request, event_id, rotator_id, 0),
        status_code=HTTP_307_TEMPORARY_REDIRECT)


@get(path='/rotator/{event_id:str}/{rotator_id:str}/{screen_index:int}', name='show-rotator-screen')
async def show_rotator_screen(
        request: Request, event_id: str, rotator_id: str, screen_index: int) -> Template | Redirect:
    event: Event = load_event(request, event_id)
    if event is None:
        return Redirect(
            path=index_url(request),
            status_code=HTTP_307_TEMPORARY_REDIRECT)
    if rotator_id not in event.rotators:
        Message.error(request, f'Écran rotatif [{rotator_id}] non trouvé')
        return Redirect(
            path=event_url(request, event_id),
            status_code=HTTP_307_TEMPORARY_REDIRECT)
    rotator: Rotator = event.rotators[rotator_id]
    screen_index: int = screen_index % len(rotator.screens)
    screen: AScreen = rotator.screens[screen_index]
    login_needed: bool = event_login_needed(request, event, screen)
    return render_screen(
        request, event, screen, login_needed,
        rotator_next_url=rotator_screen_url(request, event_id, rotator_id, (screen_index + 1) % len(rotator.screens)),
        rotator_delay=rotator.delay)


@get(
    path='/result/{event_id:str}/{screen_id:str}/{tournament_id:str}/{board_id:int}/{result:int}',
    name='update-result'
)
async def update_result(
        request: Request, event_id: str, screen_id: str, tournament_id: str, board_id: int, result: int
) -> Template | Redirect:
    event: Event = load_event(request, event_id)
    if event is None:
        return Redirect(
            path=index_url(request),
            status_code=HTTP_307_TEMPORARY_REDIRECT)
    if not event_login_needed(request, event):
        tournament: Tournament
        try:
            tournament = event.tournaments[tournament_id]
            board: Board
            try:
                board = tournament.boards[board_id - 1]
                if result not in Result.imputable_results():
                    Message.error(request, f'L\'écriture du résultat à échoué (résultat invalide [{result}])')
                else:
                    tournament.add_result(board, Result.from_papi_value(result))
                    event.store_result(tournament, board, result)
                    request.session['last_result_entered']: dict[str, int | str | float] = {
                        'tournament_id': tournament_id,
                        'board_id': board_id,
                        'expiration': time.time() + 10,
                    }
            except KeyError:
                Message.error(
                    request, f'L\'échiquier [{board_id}] est introuvable pour le tournoi [{tournament.id}])')
        except KeyError:
            Message.error(request, f'Tournoi [{tournament_id}] non trouvé')
    return Redirect(
        path=screen_url(request, event_id, screen_id),
        status_code=HTTP_307_TEMPORARY_REDIRECT)


@get(
    path='/illegal-move/{event_id:str}/{screen_id:str}/{tournament_id:str}/{board_id:int}/{color:str}',
    name='add-illegal-move'
)
async def add_illegal_move(
        request: Request, event_id: str, screen_id: str, tournament_id: str, board_id: int, color: str
) -> Template | Redirect:
    event: Event = load_event(request, event_id)
    if event is None:
        return Redirect(
            path=index_url(request),
            status_code=HTTP_307_TEMPORARY_REDIRECT)
    if not event_login_needed(request, event):
        tournament: Tournament
        try:
            tournament = event.tournaments[tournament_id]
            board: Board
            try:
                board = tournament.boards[board_id - 1]
                if color.upper() not in Color:
                    Message.error(request, f'L\'écriture du résultat à échoué (couleur invalide [{color}])')
                else:
                    tournament.store_illegal_move(board, Color(color))
                    request.session['last_illegal_move_added']: dict[str, int | str | float] = {
                        'tournament_id': tournament_id,
                        'board_id': board_id,
                        'color': str,
                        'expiration': time.time() + 10,
                    }
            except KeyError:
                Message.error(
                    request, f'L\'échiquier [{board_id}] est introuvable pour le tournoi [{tournament.id}])')
        except KeyError:
            Message.error(request, f'Tournoi [{tournament_id}] non trouvé')
    return Redirect(
        path=screen_url(request, event_id, screen_id),
        status_code=HTTP_307_TEMPORARY_REDIRECT)


@get(path='/screen-last-update/{event_id:str}/{screen_id:str}', name='get-screen-last-update')
async def get_screen_last_update(request: Request, event_id: str, screen_id: str) -> str:
    screen_files: list[Path] = AScreen.get_screen_file_dependencies(event_id, screen_id)
    try:
        mtime: float = screen_files[0].lstat().st_mtime
        for screen_file in screen_files[1:]:
            with suppress(FileNotFoundError):
                mtime = max(mtime, screen_file.lstat().st_mtime)
        last_update: int = math.ceil(mtime)
        logger.debug(f'last_update({event_id}/{screen_id})={last_update}')
        return str(last_update)
    except FileNotFoundError:
        error: str = f'Aucun tournoi pour l\'écran [{screen_id}]'
        Message.error(request, error)
        raise HTTPException(detail=error, status_code=500)


@get(path='/download-event/{event_id:str}', name='download-event')
async def download_event(request: Request, event_id: str) -> Response[bytes] | Redirect:
    event: Event = load_event(request, event_id)
    if event is None:
        return Redirect(
            path=index_url(request),
            status_code=HTTP_307_TEMPORARY_REDIRECT)
    tournament_files: list[Path] = []
    for tournament in event.tournaments.values():
        if tournament.file.exists():
            tournament_files.append(tournament.file)
    if not tournament_files:
        Message.error(request, f'Aucun fichier de tournoi pour l\'évènement [{event_id}]')
        return Redirect(
            path=event_url(request, event_id),
            status_code=HTTP_307_TEMPORARY_REDIRECT)
    archive = BytesIO()
    with ZipFile(archive, 'w') as zip_archive:
        for tournament_file in tournament_files:
            zip_entry: ZipInfo = ZipInfo(tournament_file.name)
            with open(tournament_file, 'rb') as tournament_handler:
                zip_archive.writestr(zip_entry, tournament_handler.read())
    return Response(content=bytes(archive.getbuffer()), media_type='application/zip')


@get(path='/download-tournament/{event_id:str}/{tournament_id:str}', name='download-tournament')
async def download_tournament(request: Request, event_id: str, tournament_id: str) -> File | Redirect:
    event: Event = load_event(request, event_id)
    if event is None:
        return Redirect(
            path=index_url(request),
            status_code=HTTP_307_TEMPORARY_REDIRECT)
    tournament: Tournament
    try:
        tournament = event.tournaments[tournament_id]
        if tournament.file.exists():
            return File(path=tournament.file, filename=tournament.file.name)
        else:
            Message.error(request, f'Aucun fichier de tournoi pour l\'évènement [{event_id}]')
            return Redirect(
                path=event_url(request, event_id),
                status_code=HTTP_307_TEMPORARY_REDIRECT)
    except KeyError:
        Message.error(request, f'Le tournoi [{tournament_id}] n\'existe pas pour l\'évènement [{event_id}]')
        return Redirect(
            path=event_url(request, event_id),
            status_code=HTTP_307_TEMPORARY_REDIRECT)

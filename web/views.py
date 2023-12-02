from contextlib import suppress
from pathlib import Path

import math
import time
from django.contrib import messages
from django.http import HttpResponse, HttpRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.template.defaulttags import register
from logging import Logger

from common.logger import get_logger
from common.papi_web_config import PAPI_WEB_COPYRIGHT, PAPI_WEB_URL, PAPI_WEB_VERSION, PapiWebConfig
from data.board import Board
from data.event import Event, get_events_by_name
from data.rotator import Rotator
from data.screen import AScreen
from data.tournament import Tournament
from data.util import Result

logger: Logger = get_logger()

papi_web_info: dict[str, str] = {
    'version': PAPI_WEB_VERSION,
    'url': PAPI_WEB_URL,
    'copyright': PAPI_WEB_COPYRIGHT,
}


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


def event_url(event_id: str) -> str:
    return reverse('show-event', kwargs={'event_id': event_id, })


def screen_url(event_id: str, screen_id: str) -> str:
    return reverse('show-screen', kwargs={'event_id': event_id, 'screen_id': screen_id, })


def rotator_url(event_id: str, rotator_id: str) -> str:
    return reverse('show-rotator', kwargs={'event_id': event_id, 'rotator_id': rotator_id, })


def rotator_screen_url(event_id: str, rotator_id: str, screen_index: int) -> str:
    return reverse(
        'show-rotator-screen',
        kwargs={'event_id': event_id, 'rotator_id': rotator_id, 'screen_index': screen_index, })


def render_screen(
        request: HttpRequest, event: Event, screen: AScreen, login_needed: bool, rotator_next_url: str = None,
        rotator_delay: int = None
) -> HttpResponse:
    return render(request, 'screen.html', {
        'papi_web_info': papi_web_info,
        'event': event,
        'screen': screen,
        'now': math.floor(time.time()),
        'login_needed': login_needed,
        'rotator_next_url': rotator_next_url,
        'rotator_delay': rotator_delay,
    })


def index(request: HttpRequest) -> HttpResponse:
    events: list[Event] = get_events_by_name()
    if len(events) == 0:
        messages.error(request, 'No event found')
    return render(request, 'index.html', {
        'papi_web_info': papi_web_info,
        'papi_web_config': PapiWebConfig(),
        'events': events,
    })


def load_event(request: HttpRequest, event_id: str) -> Event | None:
    event: Event = Event(event_id)
    if event.errors:
        for error in event.errors:
            messages.error(request, error)
        return None
    return event


def show_event(request: HttpRequest, event_id: str) -> HttpResponse:
    event: Event = load_event(request, event_id)
    if event is None:
        return redirect('index')
    return render(request, 'event.html', {'papi_web_info': papi_web_info, 'event': event, })


def session_password_key(event: Event) -> str:
    return 'auth-' + event.id


def store_password(request: HttpRequest, event: Event, password: int):
    request.session[session_password_key(event)] = password


def get_stored_password(request: HttpRequest, event: Event) -> str:
    return request.session.get(session_password_key(event), None)


def check_auth(request: HttpRequest, event: Event) -> tuple[bool, bool]:
    # -> login_needed, do_redirect
    logger.debug(f'check_auth({event.id})...')
    if 'password' in request.POST:
        logger.debug(f'POST.password={request.POST["password"]}')
        if request.POST['password'] == event.update_password:
            messages.success(request, f'Authentification réussie.')
            store_password(request, event, request.POST['password'])
            return False, True
        messages.error(request, f'Code d\'accès incorrect.')
        return True, True
    session_password: str = get_stored_password(request, event)
    logger.debug(f'session_password={session_password}')
    if session_password is None:
        messages.error(request, f'Un code d\'accès est nécessaire pour accéder à l\'interface de saisie des résultats.')
        return True, False
    if session_password != event.update_password:
        messages.error(request, f'Code d\'accès incorrect.')
        return True, False
    return False, False


def show_screen(request: HttpRequest, event_id: str, screen_id: str) -> HttpResponse:
    event: Event = load_event(request, event_id)
    if event is None:
        return redirect('index')
    if screen_id not in event.screens:
        messages.error(request, f'Screen [{screen_id}] not found')
        return redirect(event_url(event_id))
    screen: AScreen = event.screens[screen_id]
    login_needed: bool = False
    if event.update_password and screen.update:
        login_needed, do_redirect = check_auth(request, event)
        if do_redirect:
            return redirect(screen_url(event.id, screen.id, ))
    return render_screen(request, event, screen, login_needed)


def show_rotator(request: HttpRequest, event_id: str, rotator_id: str, screen_index: int = None) -> HttpResponse:
    if screen_index is None:
        return redirect(rotator_screen_url(event_id, rotator_id, 0))
    event: Event = load_event(request, event_id)
    if event is None:
        return redirect('index')
    if rotator_id not in event.rotators:
        messages.error(request, f'Rotator [{rotator_id}] not found')
        return redirect(event_url(event_id))
    rotator: Rotator = event.rotators[rotator_id]
    screen_index: int = screen_index % len(rotator.screens)
    screen: AScreen = rotator.screens[screen_index]
    login_needed: bool = False
    if event.update_password and screen.update:
        login_needed, do_redirect = check_auth(request, event)
        if do_redirect:
            return redirect(rotator_screen_url(event.id, rotator.id, screen_index))
    return render_screen(
        request, event, rotator.screens[screen_index], login_needed,
        rotator_screen_url(event.id, rotator.id, (screen_index + 1) % len(rotator.screens)), rotator.delay)


def update_result(
        request: HttpRequest, event_id: str, screen_id: str, tournament_id: str, board_id: int, result: int
) -> HttpResponse:
    event: Event = load_event(request, event_id)
    if event is None:
        return redirect('index')
    if event.update_password:
        login_needed, do_redirect = check_auth(request, event)
        if login_needed or do_redirect:
            return redirect(screen_url(event.id, screen_id, ))
    tournament: Tournament
    try:
        tournament = event.tournaments[tournament_id]
    except KeyError:
        messages.error(request, f'Tournament [{tournament_id}] not found')
        return redirect(event_url(event_id))
    board: Board
    try:
        board = tournament.boards[board_id - 1]
    except KeyError:
        messages.error(
            request, f'Writing result failed (board [{board_id}] not found for tournament [{tournament.id}])')
        return redirect(screen_url(event.id, screen_id, ))
    if result not in Result.imputable_results():
        messages.error(request, f'Writing result failed (invalid result [{result}])')
        return redirect(screen_url(event.id, screen_id, ))
    tournament.add_result(board, Result.from_papi_value(result))
    event.store_result(tournament, board, result)
    return redirect(screen_url(event_id, screen_id, ))


def get_screen_last_update(request: HttpRequest, event_id: str, screen_id: str) -> HttpResponse:
    screen_files: list[Path] = AScreen.get_screen_file_dependencies(event_id, screen_id)
    try:
        mtime: float = screen_files[0].lstat().st_mtime
        for screen_file in screen_files[1:]:
            with suppress(FileNotFoundError):
                mtime = max(mtime, screen_file.lstat().st_mtime)
        last_update: int = math.ceil(mtime)
        logger.debug(f'last_update({event_id}/{screen_id})={last_update}')
        return HttpResponse(str(last_update), content_type='text/plain')
    except FileNotFoundError:
        messages.error(request, f'Screen [{screen_id}] not found')
        return HttpResponse(status=500)

import math
import os
import time
from typing import List, Dict, Optional, Tuple
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
from data.screen import AScreen, SCREEN_TYPE_RESULTS
from data.tournament import Tournament
from database.papi import RESULT_LOSS, RESULT_GAIN, RESULT_DRAW_OR_BYE_05

logger: Logger = get_logger()

papi_web_info: Dict[str, str] = {
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
    events: List[Event] = get_events_by_name()
    if len(events) == 0:
        messages.error(request, 'No event found')
    return render(request, 'index.html', {
        'papi_web_info': papi_web_info,
        'papi_web_config': PapiWebConfig(),
        'events': events,
    })


def load_event(request: HttpRequest, event_id: str) -> Optional[Event]:
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


def check_auth(request: HttpRequest, event: Event) -> Tuple[bool, bool]:
    # -> login_needed, do_redirect
    logger.debug('check_auth({})...'.format(event.id))
    if 'password' in request.POST:
        logger.debug('POST.password={}'.format(request.POST['password']))
        if request.POST['password'] == event.update_password:
            messages.success(request, 'Authentification réussie.')
            store_password(request, event, request.POST['password'])
            return False, True
        messages.error(request, 'Code d\'accès incorrect.')
        return True, True
    session_password: str = get_stored_password(request, event)
    logger.debug('session_password={}'.format(session_password))
    if session_password is None:
        messages.error(request, 'Un code d\'accès est nécessaire pour accéder à l\'interface de saisie des résultats.')
        return True, False
    if session_password != event.update_password:
        messages.error(request, 'Code d\'accès incorrect.')
        return True, False
    return False, False


def show_screen(request: HttpRequest, event_id: str, screen_id: str) -> HttpResponse:
    event: Event = load_event(request, event_id)
    if event is None:
        return redirect('index')
    if screen_id not in event.screens:
        messages.error(request, 'Screen [{}] not found'.format(screen_id))
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
        messages.error(request, 'Rotator [{}] not found'.format(rotator_id))
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
        messages.error(request, 'Tournament [{}] not found'.format(tournament_id))
        return redirect(event_url(event_id))
    board: Board
    try:
        board = tournament.boards[board_id - 1]
    except KeyError:
        messages.error(request, 'Writing result failed (board [{}] not found for tournament [{}])'.format(
            board_id, tournament.id))
        return redirect(screen_url(event.id, screen_id, ))
    if result not in [RESULT_LOSS, RESULT_DRAW_OR_BYE_05, RESULT_GAIN]:
        messages.error(request, 'Writing result failed (invalid result [{}])'.format(result))
        return redirect(screen_url(event.id, screen_id, ))
    tournament.add_result(board, result)
    event.store_result(tournament, board, result)
    return redirect(screen_url(event_id, screen_id, ))


def get_screen_last_update(request: HttpRequest, event_id: str, screen_id: str) -> HttpResponse:
    event: Event = load_event(request, event_id)
    if event is None:
        return redirect('index')
    try:
        screen: AScreen = event.screens[screen_id]
        screen_files: List[str] = []
        if screen.type == SCREEN_TYPE_RESULTS:
            for tournament in event.tournaments.values():
                if tournament.file not in screen_files:
                    screen_files.append(tournament.file)
        else:
            for set in screen.sets:
                if set.tournament.file not in screen_files:
                    screen_files.append(set.tournament.file)
        mtime: float = 0.0
        for screen_file in screen_files:
            mtime = max(mtime, os.path.getmtime(screen_file))
        return HttpResponse(str(math.ceil(mtime)), content_type='text/plain')
    except KeyError:
        messages.error(request, 'Screen [{}] not found'.format(screen_id))
        return redirect(event_url(event_id))

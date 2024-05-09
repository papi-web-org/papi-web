import time

from litestar.contrib.htmx.request import HTMXRequest

from data.event import Event


def session_password_key(event: Event) -> str:
    return 'auth-' + event.id


def store_password(request: HTMXRequest, event: Event, password: str | None):
    request.session[session_password_key(event)] = password


def get_stored_password(request: HTMXRequest, event: Event) -> str | None:
    return request.session.get(session_password_key(event), None)


def set_session_last_result_updated(request: HTMXRequest, tournament_id: str, round: int, board_id: int, ):
    request.session['last_result_updated']: dict[str, int | str | float] = {
        'tournament_id': tournament_id,
        'round': round,
        'board_id': board_id,
        'expiration': time.time() + 20,
    }


def get_session_last_result_updated(request: HTMXRequest):
    return request.session.get('last_result_updated', None)


def set_session_last_illegal_move_updated(request: HTMXRequest, tournament_id: str, player_id: int, ):
    request.session['last_illegal_move_updated']: dict[str, int | str | float] = {
        'tournament_id': tournament_id,
        'player_id': player_id,
        'expiration': time.time() + 20,
    }


def get_session_last_illegal_move_updated(request: HTMXRequest):
    return request.session.get('last_illegal_move_updated', None)


def set_session_last_check_in_updated(request: HTMXRequest, tournament_id: str, player_id: int, ):
    request.session['last_check_in_updated']: dict[str, int | str | float] = {
        'tournament_id': tournament_id,
        'player_id': player_id,
        'expiration': time.time() + 20,
    }


def get_session_last_check_in_updated(request: HTMXRequest):
    return request.session.get('last_check_in_updated', None)

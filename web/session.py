import time

from litestar.contrib.htmx.request import HTMXRequest

from common.singleton import singleton
from data.event import Event


class SessionHandler:
    @staticmethod
    def session_password_key(event: Event) -> str:
        return 'auth-' + event.id

    @staticmethod
    def store_password(request: HTMXRequest, event: Event, password: str | None):
        request.session[SessionHandler.session_password_key(event)] = password

    @staticmethod
    def get_stored_password(request: HTMXRequest, event: Event) -> str | None:
        return request.session.get(SessionHandler.session_password_key(event), None)

    @staticmethod
    def set_session_last_result_updated(request: HTMXRequest, tournament_uniq_id: str, round: int, board_id: int, ):
        request.session['last_result_updated']: dict[str, int | str | float] = {
            'tournament_uniq_id': tournament_uniq_id,
            'round': round,
            'board_id': board_id,
            'expiration': time.time() + 20,
        }

    @staticmethod
    def get_session_last_result_updated(request: HTMXRequest):
        return request.session.get('last_result_updated', None)

    @staticmethod
    def set_session_last_illegal_move_updated(request: HTMXRequest, tournament_uniq_id: str, player_id: int, ):
        request.session['last_illegal_move_updated']: dict[str, int | str | float] = {
            'tournament_uniq_id': tournament_uniq_id,
            'player_id': player_id,
            'expiration': time.time() + 20,
        }

    @staticmethod
    def get_session_last_illegal_move_updated(request: HTMXRequest):
        return request.session.get('last_illegal_move_updated', None)

    @staticmethod
    def set_session_last_check_in_updated(request: HTMXRequest, tournament_uniq_id: str, player_id: int, ):
        request.session['last_check_in_updated']: dict[str, int | str | float] = {
            'tournament_uniq_id': tournament_uniq_id,
            'player_id': player_id,
            'expiration': time.time() + 20,
        }

    @staticmethod
    def get_session_last_check_in_updated(request: HTMXRequest):
        return request.session.get('last_check_in_updated', None)

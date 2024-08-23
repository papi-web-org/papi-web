import time

from litestar.contrib.htmx.request import HTMXRequest

from data.event import NewEvent


class SessionHandler:

    AUTH_SESSION_KEY: str = 'auth'

    @staticmethod
    def store_password(request: HTMXRequest, event: NewEvent, password: str | None):
        if 'auth' not in request.session:
            request.session['auth']: dict[str, str] = {}
        request.session['auth'][event.uniq_id] = password

    @staticmethod
    def get_stored_password(request: HTMXRequest, event: NewEvent) -> str | None:
        try:
            return request.session['auth'][event.uniq_id]
        except KeyError:
            return None

    LAST_RESULT_UPDATED_SESSION_KEY: str = 'last_result_updated'

    @classmethod
    def set_session_last_result_updated(
            cls, request: HTMXRequest, tournament_id: int, round: int, board_id: int, ):
        request.session[cls.LAST_RESULT_UPDATED_SESSION_KEY]: dict[str, int | str | float] = {
            'tournament_id': tournament_id,
            'round': round,
            'board_id': board_id,
            'expiration': time.time() + 20,
        }

    @classmethod
    def get_session_last_result_updated(cls, request: HTMXRequest):
        return request.session.get(cls.LAST_RESULT_UPDATED_SESSION_KEY, None)

    LAST_ILLEGAL_MOVE_UPDATED_SESSION_KEY: str = 'last_illegal_move_updated'

    @classmethod
    def set_session_last_illegal_move_updated(cls, request: HTMXRequest, tournament_id: int, player_id: int, ):
        request.session[cls.LAST_ILLEGAL_MOVE_UPDATED_SESSION_KEY]: dict[str, int | str | float] = {
            'tournament_id': tournament_id,
            'player_id': player_id,
            'expiration': time.time() + 20,
        }

    @classmethod
    def get_session_last_illegal_move_updated(cls, request: HTMXRequest):
        return request.session.get(cls.LAST_ILLEGAL_MOVE_UPDATED_SESSION_KEY, None)

    LAST_CHECK_IN_UPDATED_SESSION_KEY: str = 'last_check_in_updated'

    @classmethod
    def set_session_last_check_in_updated(cls, request: HTMXRequest, tournament_id: int, player_id: int, ):
        request.session[cls.LAST_CHECK_IN_UPDATED_SESSION_KEY]: dict[str, int | str | float] = {
            'tournament_id': tournament_id,
            'player_id': player_id,
            'expiration': time.time() + 20,
        }

    @classmethod
    def get_session_last_check_in_updated(cls, request: HTMXRequest):
        return request.session.get(cls.LAST_CHECK_IN_UPDATED_SESSION_KEY, None)

    SHOW_FAMILY_SCREENS_ON_SCREEN_LIST: str = 'show_family_screens_on_screen_list'

    @classmethod
    def set_session_show_family_screens_on_screen_list(cls, request: HTMXRequest, b: bool):
        request.session[cls.SHOW_FAMILY_SCREENS_ON_SCREEN_LIST]: bool = b

    @classmethod
    def get_session_show_family_screens_on_screen_list(cls, request: HTMXRequest) -> bool:
        return request.session.get(cls.SHOW_FAMILY_SCREENS_ON_SCREEN_LIST, True)

    SHOW_DETAILS_ON_SCREEN_LIST: str = 'show_details_on_screen_list'

    @classmethod
    def set_session_show_details_on_screen_list(cls, request: HTMXRequest, b: bool):
        request.session[cls.SHOW_DETAILS_ON_SCREEN_LIST]: bool = b

    @classmethod
    def get_session_show_details_on_screen_list(cls, request: HTMXRequest) -> bool:
        return request.session.get(cls.SHOW_DETAILS_ON_SCREEN_LIST, True)

    SCREEN_TYPES_ON_SCREEN_LIST_SESSION_KEY: str = 'screen_types_on_screen_list'

    @classmethod
    def set_session_screen_types_on_screen_list(cls, request: HTMXRequest, screen_types: list[str]):
        request.session[cls.SCREEN_TYPES_ON_SCREEN_LIST_SESSION_KEY]: list[str] = screen_types

    @classmethod
    def get_session_screen_types_on_screen_list(cls, request: HTMXRequest) -> list[str]:
        return request.session.get(
            cls.SCREEN_TYPES_ON_SCREEN_LIST_SESSION_KEY, ['boards', 'input', 'players', 'results'])

    SCREEN_TYPES_ON_FAMILY_LIST_SESSION_KEY: str = 'screen_types_on_family_list'

    @classmethod
    def set_session_screen_types_on_family_list(cls, request: HTMXRequest, screen_types: list[str]):
        request.session[cls.SCREEN_TYPES_ON_FAMILY_LIST_SESSION_KEY]: list[str] = screen_types

    @classmethod
    def get_session_screen_types_on_family_list(cls, request: HTMXRequest) -> list[str]:
        return request.session.get(cls.SCREEN_TYPES_ON_FAMILY_LIST_SESSION_KEY, ['boards', 'input', 'players'])

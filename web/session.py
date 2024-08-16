import time

from litestar.contrib.htmx.request import HTMXRequest

from data.event import Event


class SessionHandler:
    @staticmethod
    def session_password_key(event: Event) -> str:
        return 'auth-' + event.uniq_id

    @staticmethod
    def store_password(request: HTMXRequest, event: Event, password: str | None):
        request.session[SessionHandler.session_password_key(event)] = password

    @staticmethod
    def get_stored_password(request: HTMXRequest, event: Event) -> str | None:
        return request.session.get(SessionHandler.session_password_key(event), None)

    LAST_RESULT_UPDATED: str = 'last_result_updated'

    @classmethod
    def set_session_last_result_updated(cls, request: HTMXRequest, tournament_uniq_id: str, round: int, board_id: int, ):
        request.session[cls.LAST_RESULT_UPDATED]: dict[str, int | str | float] = {
            'tournament_uniq_id': tournament_uniq_id,
            'round': round,
            'board_id': board_id,
            'expiration': time.time() + 20,
        }

    @classmethod
    def get_session_last_result_updated(cls, request: HTMXRequest):
        return request.session.get(cls.LAST_RESULT_UPDATED, None)

    LAST_ILLEGAL_MOVE_UPDATED: str = 'last_illegal_move_updated'

    @classmethod
    def set_session_last_illegal_move_updated(cls, request: HTMXRequest, tournament_uniq_id: str, player_id: int, ):
        request.session[cls.LAST_ILLEGAL_MOVE_UPDATED]: dict[str, int | str | float] = {
            'tournament_uniq_id': tournament_uniq_id,
            'player_id': player_id,
            'expiration': time.time() + 20,
        }

    @classmethod
    def get_session_last_illegal_move_updated(cls, request: HTMXRequest):
        return request.session.get(cls.LAST_ILLEGAL_MOVE_UPDATED, None)

    LAST_CHECK_IN_UPDATED: str = 'last_check_in_updated'

    @classmethod
    def set_session_last_check_in_updated(cls, request: HTMXRequest, tournament_uniq_id: str, player_id: int, ):
        request.session[cls.LAST_CHECK_IN_UPDATED]: dict[str, int | str | float] = {
            'tournament_uniq_id': tournament_uniq_id,
            'player_id': player_id,
            'expiration': time.time() + 20,
        }

    @classmethod
    def get_session_last_check_in_updated(cls, request: HTMXRequest):
        return request.session.get(cls.LAST_CHECK_IN_UPDATED, None)

    SHOW_FAMILY_SCREENS_ON_SCREEN_LIST: str = 'show_family_screens_on_screen_list'

    @classmethod
    def set_session_show_family_screens_on_screen_list(cls, request: HTMXRequest, b: bool):
        request.session[cls.SHOW_FAMILY_SCREENS_ON_SCREEN_LIST]: bool = b

    @classmethod
    def get_session_show_family_screens_on_screen_list(cls, request: HTMXRequest) -> bool:
        return request.session.get(cls.SHOW_FAMILY_SCREENS_ON_SCREEN_LIST, True)

    SCREEN_TYPES_ON_SCREEN_LIST: str = 'screen_types_on_screen_list'

    @classmethod
    def set_session_screen_types_on_screen_list(cls, request: HTMXRequest, screen_types: list[str]):
        request.session[cls.SCREEN_TYPES_ON_SCREEN_LIST]: list[str] = screen_types

    @classmethod
    def get_session_screen_types_on_screen_list(cls, request: HTMXRequest) -> list[str]:
        return request.session.get(cls.SCREEN_TYPES_ON_SCREEN_LIST, ['boards', 'input', 'players', 'results'])

    SCREEN_TYPES_ON_FAMILY_LIST: str = 'screen_types_on_family_list'

    @classmethod
    def set_session_screen_types_on_family_list(cls, request: HTMXRequest, screen_types: list[str]):
        request.session[cls.SCREEN_TYPES_ON_FAMILY_LIST]: list[str] = screen_types

    @classmethod
    def get_session_screen_types_on_family_list(cls, request: HTMXRequest) -> list[str]:
        return request.session.get(cls.SCREEN_TYPES_ON_FAMILY_LIST, ['boards', 'input', 'players'])

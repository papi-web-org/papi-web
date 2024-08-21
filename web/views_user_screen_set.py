import time
from contextlib import suppress

from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, Reswap
from litestar.status_codes import HTTP_304_NOT_MODIFIED

from common.logger import get_logger
from data.event import NewEvent
from data.loader import EventLoader
from data.screen import NewScreen
from data.screen_set import NewScreenSet
from data.util import ScreenType
from web.messages import Message
from web.session import SessionHandler
from web.views_user_index import AUserController

logger: Logger = get_logger()


class UserScreenSetController(AUserController):
    @staticmethod
    def _user_screen_set_div_update_needed(screen_set: NewScreenSet, date: float, ) -> bool:
        if screen_set.tournament.last_update > date:
            return True
        if screen_set.tournament.last_check_in_update > date:
            return True
        match screen_set.type:
            case ScreenType.Boards | ScreenType.Input:
                if screen_set.tournament.last_illegal_move_update > date:
                    return True
                if screen_set.tournament.last_result_update > date:
                    return True
            case ScreenType.Players:
                pass
            case _:
                raise ValueError(f'type={screen_set.type}')
        with suppress(FileNotFoundError):
            if screen_set.tournament.file.lstat().st_mtime > date:
                return True
        return False

    @classmethod
    def _load_screen_set_context(
            cls,
            request: HTMXRequest,
            event_loader: EventLoader,
            event_uniq_id: str,
            screen_uniq_id: str,
            screen_set_uniq_id: str,
    ) -> tuple[Template | Redirect | None, NewEvent | None, NewScreen | None, NewScreenSet | None, ]:
        response, event, screen = cls._load_screen_context(request, event_loader, event_uniq_id, screen_uniq_id)
        if response:
            return response, None, None, None
        try:
            screen_set: NewScreenSet = screen.screen_sets_by_uniq_id[screen_set_uniq_id]
        except KeyError:
            Message.error(
                request, f'L\'ensemble [{screen_set_uniq_id}] de l\'écran [{screen.uniq_id}] est introuvable.')
            return cls._render_messages(request), None, None, None
        return None, event, screen, screen_set

    @post(
        path='/user-boards-screen-set-render-if-updated',
        name='user-boards-screen-set-render-if-updated',
    )
    async def htmx_user_boards_screen_set_render_if_updated(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Reswap:
        try:
            event_uniq_id: str = self._form_data_to_str_or_none(data, 'event_uniq_id')
            screen_uniq_id: str = self._form_data_to_str_or_none(data, 'screen_uniq_id')
            screen_set_uniq_id: str = self._form_data_to_str_or_none(data, 'screen_set_uniq_id')
            date: float = self._form_data_to_float_or_none(data, 'date')
        except ValueError as ve:
            Message.error(request, str(ve))
            return self._render_messages(request)
        if not date:
            return Reswap(content=None, method='none', status_code=286)  # stop pooling
        response, event, screen, screen_set = self._load_screen_set_context(
            request, EventLoader(), event_uniq_id, screen_uniq_id, screen_set_uniq_id)
        if response:
            return response
        if self._user_screen_set_div_update_needed(screen_set, date):
            return HTMXTemplate(
                template_name='user_boards_screen_set.html',
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
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

    @post(
        path='/user-players-screen-set-render-if-updated',
        name='user-players-screen-set-render-if-updated',
    )
    async def htmx_user_players_screen_set_render_if_updated(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Reswap:
        try:
            event_uniq_id: str = self._form_data_to_str_or_none(data, 'event_uniq_id')
            screen_uniq_id: str = self._form_data_to_str_or_none(data, 'screen_uniq_id')
            screen_set_uniq_id: str = self._form_data_to_str_or_none(data, 'screen_set_uniq_id')
            date: float = self._form_data_to_float_or_none(data, 'date')
        except ValueError as ve:
            Message.error(request, str(ve))
            return self._render_messages(request)
        if not date:
            return Reswap(content=None, method='none', status_code=286)  # stop pooling
        response, event, screen, screen_set = self._load_screen_set_context(
            request, EventLoader(), event_uniq_id, screen_uniq_id, screen_set_uniq_id)
        if self._user_screen_set_div_update_needed(screen_set, date):
            return HTMXTemplate(
                template_name='user_players_screen_set.html',
                context={
                    'event': event,
                    'screen': screen,
                    'screen_set': screen_set,
                    'now': time.time(),
                },
            )
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

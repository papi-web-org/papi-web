from contextlib import suppress
from logging import Logger
from typing import Annotated

from litestar import get, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import Reswap
from litestar.status_codes import HTTP_304_NOT_MODIFIED

from common.logger import get_logger
from data.loader import EventLoader
from data.screen import NewScreen
from data.tournament import NewTournament
from data.util import ScreenType
from web.messages import Message
from web.views_user_index import AUserController

logger: Logger = get_logger()


class UserScreenController(AUserController):
    @get(
        path='/user-screen-render/{event_uniq_id:str}/{screen_uniq_id:str}',
        name='user-screen-render',
    )
    async def htmx_user_screen_render(
            self, request: HTMXRequest, event_uniq_id: str, screen_uniq_id: str
    ) -> Template | Redirect:
        response, event, screen = self._load_screen_context(request, EventLoader(), event_uniq_id, screen_uniq_id)
        if response:
            return response
        return self._user_render_screen(request, event=event, screen=screen, )

    @staticmethod
    def _user_screen_page_update_needed(screen: NewScreen, date: float, ) -> bool:
        if screen.event.last_update > date:
            return True
        if screen.last_update > date:
            return True
        match screen.type:
            case ScreenType.Boards | ScreenType.Input | ScreenType.Players:
                pass
            case ScreenType.Results:
                results_tournament_ids: list[int] = screen.results_tournament_ids \
                    if screen.results_tournament_ids else screen.event.tournaments_by_id.keys()
                for tournament_id in results_tournament_ids:
                    with suppress(KeyError):
                        tournament: NewTournament = screen.event.tournaments_by_id[tournament_id]
                        if tournament.last_update > date:
                            return True
                        if tournament.last_result_update > date:
                            return True
            case _:
                raise ValueError(f'type={screen.type}')
        return False

    @post(
        path='/user-screen-render-if-updated',
        name='user-screen-render-if-updated',
    )
    async def htmx_user_screen_render_if_updated(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Reswap:
        try:
            event_uniq_id: str = self._form_data_to_str_or_none(data, 'event_uniq_id')
            screen_uniq_id: str = self._form_data_to_str_or_none(data, 'screen_uniq_id')
            date: float = self._form_data_to_float_or_none(data, 'date')
        except ValueError as ve:
            Message.error(request, str(ve))
            return self._render_messages(request)
        if not date:
            return Reswap(content=None, method='none', status_code=286)  # stop pooling
        response, event, screen = self._load_screen_context(request, EventLoader(), event_uniq_id, screen_uniq_id)
        if response:
            return response
        if self._user_screen_page_update_needed(screen, date):
            return self._user_render_screen(request, event, screen)
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

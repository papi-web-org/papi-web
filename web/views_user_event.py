import time
from contextlib import suppress
from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import Reswap, HTMXTemplate
from litestar.status_codes import HTTP_304_NOT_MODIFIED

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import NewEvent
from data.util import ScreenType
from web.messages import Message
from web.session import SessionHandler
from web.views import WebContext
from web.views_user_index import AUserController, EventUserWebContext

logger: Logger = get_logger()


class UserEventController(AUserController):

    @classmethod
    def _user_render_event(
            cls,
            request: HTMXRequest,
            event: NewEvent,
            user_event_selector: str | None,
    ) -> Template | Redirect:
        return HTMXTemplate(
            template_name="user_event.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'user_event': event,
                'user_event_selector': user_event_selector or 'input',
                'messages': Message.messages(request),
                'now': time.time(),
                'user_columns': SessionHandler.get_session_user_columns(request),
                'nav_tabs': {
                    'input': {
                        'title': 'Saisie des résultats',
                        'screens': event.input_screens_sorted_by_uniq_id,
                    },
                    'boards': {
                        'title': 'Affichage des échiquiers',
                        'screens': event.boards_screens_sorted_by_uniq_id,
                    },
                    'players': {
                        'title': 'Affichage des appariements par ordre alphabétique',
                        'screens': event.players_screens_sorted_by_uniq_id,
                    },
                    'results': {
                        'title': 'Affichage des résultats',
                        'screens': event.results_screens_sorted_by_uniq_id,
                    },
                    'rotators': {
                        'title': 'Écrans rotatifs',
                        'rotators': event.rotators_sorted_by_uniq_id,
                    },
                }
            })

    @staticmethod
    def _user_event_page_update_needed(event: NewEvent, date: float, ) -> bool:
        if event.last_update > date:
            return True
        for screen in event.basic_screens_by_id.values():
            if screen.last_update > date:
                return True
            for screen_set in screen.screen_sets_by_id.values():
                if screen_set.last_update > date:
                    return True
                if screen_set.tournament.last_update > date:
                    return True
                if screen.type in [ScreenType.Boards, ScreenType.Input, ]:
                    if screen_set.tournament.last_illegal_move_update > date:
                        return True
                    if screen_set.tournament.last_result_update > date:
                        return True
                    if screen_set.tournament.last_update > date:
                        return True
                if screen_set.tournament.last_check_in_update > date:
                    return True
            if screen.type == ScreenType.Results:
                results_tournament_ids: list[int] = screen.results_tournament_ids \
                    if screen.results_tournament_ids else event.tournaments_by_id.keys()
                for tournament_id in results_tournament_ids:
                    with suppress(KeyError):
                        if screen.event.tournaments_by_id[tournament_id].last_result_update > date:
                            return True
        for family in event.families_by_id.values():
            if family.last_update > date:
                return True
            if family.tournament.last_update > date:
                return True
            match family.type:
                case ScreenType.Boards | ScreenType.Input:
                    if family.tournament.last_illegal_move_update > date:
                        return True
                    if family.tournament.last_result_update > date:
                        return True
                    if family.tournament.last_check_in_update > date:
                        return True
                case ScreenType.Players:
                    if family.tournament.last_check_in_update > date:
                        return True
                case _:
                    raise ValueError(f'type={family.type}')
        return False

    @post(
        path='/user-event-render-if-updated',
        name='user-event-render-if-updated',
    )
    async def htmx_user_event_render_if_updated(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Reswap:
        web_context: EventUserWebContext = EventUserWebContext(request, data, True)
        if web_context.error:
            return web_context.error
        try:
            date: float = WebContext.form_data_to_float(data, 'date', 0.0)
        except ValueError as ve:
            Message.error(request, str(ve))
            return self._render_messages(request)
        if date <= 0.0:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)  # timer is hanged
        if self._user_event_page_update_needed(web_context.event, date):
            web_context: EventUserWebContext = EventUserWebContext(request, data, False)
            if web_context.error:
                return web_context.error
            user_event_selector: str = self._form_data_to_str_or_none(data, 'user_event_selector')
            return self._user_render_event(request, web_context.event, user_event_selector)
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

    @post(
        path='/user-event-render',
        name='user-event-render',
    )
    async def htmx_user_event_render(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        web_context: EventUserWebContext = EventUserWebContext(request, data, False)
        if web_context.error:
            return web_context.error
        return self._user_render_event(request, web_context.event, web_context.user_event_selector)

    @post(
        path='/user-update-header',
        name='user-update-header'
    )
    async def htmx_user_event_update_header(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        web_context: EventUserWebContext = EventUserWebContext(request, data, False)
        if web_context.error:
            return web_context.error
        field: str = f'user_columns'
        if field in data:
            SessionHandler.set_session_user_columns(request, self._form_data_to_int_or_none(data, field))
        return self._user_render_event(request, web_context.event, web_context.user_event_selector)

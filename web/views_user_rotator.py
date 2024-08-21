from logging import Logger

from litestar import get
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest

from common.logger import get_logger
from data.event import NewEvent
from data.loader import EventLoader
from data.rotator import NewRotator
from web.messages import Message
from web.views_user_index import AUserController

logger: Logger = get_logger()


class UserRotatorController(AUserController):
    @classmethod
    def _load_rotator_context(
            cls, request: HTMXRequest, event_uniq_id: str, rotator_id: int, rotator_screen_index: int,
    ) -> tuple[Template | Redirect | None, NewEvent | None, NewRotator | None, int | None]:
        response, event = cls._load_event_context(request, EventLoader(), event_uniq_id)
        if response:
            return response, None, None, None
        try:
            rotator: NewRotator = event.rotators_by_id[rotator_id]
        except KeyError:
            return cls._redirect_to_index_on_error(
                request, f'L\'écran rotatif [{rotator_id}] n\'existe pas.'), None, None, None
        if not rotator.rotating_screens:
            Message.error(request, f'L\'écran rotatif [{rotator_id}] n\'a aucun écran.')
            return cls._render_messages(request), None, None, None
        rotator_screen_index = rotator_screen_index % len(rotator.rotating_screens)
        try:
            rotator.rotating_screens[rotator_screen_index]
        except KeyError:
            Message.error(
                request, f'L\'écran #{rotator_screen_index} de l\'"cran rotatif [{rotator_id}] n\'existe pas.')
            return cls._render_messages(request), None, None, None
        return None, event, rotator, rotator_screen_index

    @get(
        path='/user-rotator-render/{event_uniq_id:str}/{rotator_id:int}',
        name='user-rotator-render'
    )
    async def htmx_user_rotator_render(
            self, request: HTMXRequest, event_uniq_id: str, rotator_id: int,
    ) -> Template | Redirect:
        response, event, rotator, rotator_screen_index = self._load_rotator_context(
            request, event_uniq_id, rotator_id, 0)
        if response:
            return response
        return self._user_render_screen(request, event=event, rotator=rotator, rotator_screen_index=rotator_screen_index)

    @get(
        path='/user-rotator-render-screen/{event_uniq_id:str}/{rotator_id:int}/{rotator_screen_index:int}',
        name='user-rotator-render-screen'
    )
    async def htmx_user_rotator_render_screen(
            self, request: HTMXRequest, event_uniq_id: str, rotator_id: int, rotator_screen_index: int
    ) -> Template | Redirect:
        response, event, rotator, rotator_screen_index = self._load_rotator_context(
            request, event_uniq_id, rotator_id, rotator_screen_index)
        if response:
            return response
        return self._user_render_screen(request, event=event, rotator=rotator, rotator_screen_index=rotator_screen_index)

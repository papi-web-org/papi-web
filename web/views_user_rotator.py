from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest

from common.logger import get_logger
from data.event import NewEvent
from data.rotator import NewRotator
from web.messages import Message
from web.views_user_index import AUserController

logger: Logger = get_logger()


class UserRotatorController(AUserController):
    @classmethod
    def _load_rotator_context(
            cls, request: HTMXRequest, event_uniq_id: str, rotator_id: int,
            rotator_screen_index: int,
    ) -> tuple[Template | Redirect | None, NewEvent | None, NewRotator | None, int | None]:
        response, event = cls._load_event_context(request, True, event_uniq_id)
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

    @post(
        path='/user-rotator-render',
        name='user-rotator-render'
    )
    async def htmx_user_rotator_render_screen(
        self, request: HTMXRequest,
        data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        event_uniq_id: str = self._form_data_to_str_or_none(data, 'event_uniq_id')
        rotator_id: int = self._form_data_to_int_or_none(data, 'rotator_id')
        rotator_screen_index: int = self._form_data_to_int_or_none(data, 'rotator_screen_index', 0)
        response, event, rotator, rotator_screen_index = self._load_rotator_context(
            request, event_uniq_id, rotator_id, rotator_screen_index)
        if response:
            return response
        user_selector: str = self._form_data_to_str_or_none(data, 'user_selector')
        return self._user_render_screen(
            request, event, user_selector, rotator=rotator, rotator_screen_index=rotator_screen_index)

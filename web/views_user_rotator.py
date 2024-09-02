from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest

from common.logger import get_logger
from web.views_user_index import AUserController, RotatorUserWebContext

logger: Logger = get_logger()


class UserRotatorController(AUserController):
    @post(
        path='/user-rotator-render',
        name='user-rotator-render'
    )
    async def htmx_user_rotator_render_screen(
        self, request: HTMXRequest,
        data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        web_context: RotatorUserWebContext = RotatorUserWebContext(request, data, False)
        if web_context.error:
            return web_context.error
        return self._user_render_screen(
            request, web_context.event, web_context.user_selector, rotator=web_context.rotator,
            rotator_screen_index=web_context.rotator_screen_index % len(web_context.rotator.rotating_screens))

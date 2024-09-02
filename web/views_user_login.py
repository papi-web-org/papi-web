from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.contrib.htmx.request import HTMXRequest

from common.logger import get_logger
from web.messages import Message
from web.session import SessionHandler
from web.views_user_index import AUserController, EventUserWebContext, ScreenUserWebContext

logger: Logger = get_logger()


class UserLoginController(AUserController):
    @post(
        path='/user-login',
        name='user-login',
    )
    async def htmx_login(
            self,
            request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        web_context: EventUserWebContext = EventUserWebContext(request, data, True)
        if web_context.error:
            return web_context.error
        if data['password'] == web_context.event.update_password:
            Message.success(request, 'Authentification réussie !')
            SessionHandler.store_password(request, web_context.event, data['password'])
            web_context: ScreenUserWebContext = ScreenUserWebContext(request, data, False)
            if web_context.error:
                return web_context.error
            user_selector: str = self._form_data_to_str_or_none(data, 'user_selector')
            return self._user_render_screen(
                request, web_context.event, user_selector, screen=web_context.screen, rotator=web_context.rotator)
        if data['password'] == '':
            Message.warning(request, 'Veuillez indiquer le code d\'accès.')
        else:
            Message.error(request, 'Code d\'accès incorrect.')
            SessionHandler.store_password(request, web_context.event, None)
        return self._render_messages(request)

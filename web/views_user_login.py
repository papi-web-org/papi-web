from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.contrib.htmx.request import HTMXRequest

from common.logger import get_logger
from data.loader import EventLoader
from web.messages import Message
from web.session import SessionHandler
from web.views_user_index import AUserController

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
        event_uniq_id: str = self._form_data_to_str_or_none(data, 'event_uniq_id')
        screen_uniq_id: str = self._form_data_to_str_or_none(data, 'screen_uniq_id')
        response, event = self._load_event_context(
            request, EventLoader.get(request=request, lazy_load=True), event_uniq_id)
        if response:
            return response
        if data['password'] == event.update_password:
            Message.success(request, 'Authentification réussie !')
            SessionHandler.store_password(request, event, data['password'])
            response, event, screen = self._load_screen_context(
                request, EventLoader.get(request=request, lazy_load=False), event_uniq_id, screen_uniq_id)
            if response:
                return response
            user_selector: str = self._form_data_to_str_or_none(data, 'user_selector')
            return self._user_render_screen(request, event, user_selector, screen=screen)
        if data['password'] == '':
            Message.warning(request, 'Veuillez indiquer le code d\'accès.')
        else:
            Message.error(request, 'Code d\'accès incorrect.')
            SessionHandler.store_password(request, event, None)
        return self._render_messages(request)

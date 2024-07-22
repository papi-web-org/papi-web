
from logging import Logger
from typing import Annotated

from litestar import get, post, Controller
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, ClientRedirect, ClientRefresh

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import Event, get_events_sorted_by_name
from data.screen import AScreen
from database.access import access_driver, odbc_drivers
from web.messages import Message
from web.session import SessionHandler
from web.urls import index_url

logger: Logger = get_logger()


class AController(Controller):
    @staticmethod
    def _redirect_response(request: HTMXRequest, redirect_to: str) -> Redirect | ClientRedirect:
        return ClientRedirect(redirect_to=redirect_to) if request.htmx else Redirect(path=redirect_to)

    @staticmethod
    def _render_messages(request: HTMXRequest) -> Template:
        return HTMXTemplate(
            template_name='messages.html',
            re_swap='afterbegin',
            re_target='#messages',
            context={
                'messages': Message.messages(request),
            })

    @staticmethod
    def _event_login_needed(request: HTMXRequest, event: Event, screen: AScreen | None = None) -> bool:
        if screen is not None:
            if not screen.update:
                return False
        if not event.update_password:
            return False
        session_password: str | None = SessionHandler.get_stored_password(request, event)
        logger.debug('session_password=%s', "*" * (8 if session_password else 0))
        if session_password is None:
            Message.error(request,
                          'Un code d\'accès est nécessaire pour accéder à l\'interface de saisie des résultats.')
            return True
        if session_password != event.update_password:
            Message.error(request, 'Code d\'accès incorrect.')
            SessionHandler.store_password(request, event, None)
            return True
        return False


class LoginController(AController):
    @post(
        path='/login/{event_uniq_id:str}',
        name='login',
    )
    async def htmx_login(
            self,
            request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
            event_uniq_id: str,
    ) -> Template | ClientRedirect | ClientRefresh:
        event: Event = Event(event_uniq_id, True)
        if event.errors:
            for error in event.errors:
                Message.error(request, error)
            return ClientRedirect(redirect_to=index_url(request))
        if data['password'] == event.update_password:
            Message.success(request, 'Authentification réussie.')
            SessionHandler.store_password(request, event, data['password'])
            return ClientRefresh()
        if data['password'] == '':
            Message.warning(request, 'Veuillez indiquer le code d\'accès.')
        else:
            Message.error(request, 'Code d\'accès incorrect.')
            SessionHandler.store_password(request, event, None)
        return self._render_messages(request)


class IndexController(AController):
    @get(
        path='/',
        name='index'
    )
    async def index(self, request: HTMXRequest) -> Template:
        events: list[Event] = get_events_sorted_by_name(True)
        if len(events) == 0:
            Message.error(request, 'Aucun évènement trouvé')
        return HTMXTemplate(
            template_name="index.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'events': events,
                'odbc_drivers': odbc_drivers(),
                'access_driver': access_driver(),
                'messages': Message.messages(request),
            })

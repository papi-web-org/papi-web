from contextlib import suppress
from logging import Logger
from typing import Annotated

from pathlib import Path
from litestar import get, post, Controller, route
from litestar.enums import RequestEncodingType, HttpMethod
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, ClientRedirect, ClientRefresh
from litestar.contrib.htmx.response import HTMXTemplate, ClientRedirect, HXLocation

from common import RGB, check_rgb_str
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import Event, get_events_sorted_by_name, NewEvent
from data.loader import EventLoader
from data.screen import AScreen
from database.access import access_driver, odbc_drivers
from web.messages import Message
from web.session import SessionHandler
from web.urls import index_url

logger: Logger = get_logger()


class AController(Controller):
    @staticmethod
    def _form_data_to_str_or_none(
            data: dict[str, str], field: str, empty_value: int | None = None
    ) -> str | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        return data[field]

    @staticmethod
    def _form_data_to_int_or_none(
            data: dict[str, str], field: str, empty_value: int | None = None, minimum: int = None
    ) -> int | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        int_val = int(data[field])
        if minimum is not None and int_val < minimum:
            raise ValueError(f'{int_val} < {minimum}')
        return int_val

    @staticmethod
    def _form_data_to_bool_or_none(data: dict[str, str], field: str, empty_value: bool | None = None) -> bool | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip().lower()
        if not data[field]:
            return empty_value
        return data[field] in ['true', 'on', ]

    @staticmethod
    def _form_data_to_rgb_or_none(data: dict[str, str], field: str, empty_value: RGB | None = None) -> str | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip().lower()
        if not data[field]:
            return empty_value
        return check_rgb_str(data[field])

    @staticmethod
    def _value_to_form_data(value: str | int | bool | Path | None) -> str | None:
        if value is None:
            return ''
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, bool):
            return 'true' if value else ''
        if isinstance(value, int):
            return str(value)
        if isinstance(value, Path):
            return str(value)
        raise ValueError

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

    @staticmethod
    def _admin_render_index(
        request: HTMXRequest,
        event_loader: EventLoader = None,
        admin_main_selector: str = '',
        admin_event: NewEvent = None,
        admin_event_selector: str = '',
    ) -> Template:
        context: dict = {
            'papi_web_config': PapiWebConfig(),
            'odbc_drivers': odbc_drivers(),
            'access_driver': access_driver(),
            'event_loader': event_loader if event_loader else EventLoader(),
            'messages': Message.messages(request),
            'admin_main_selector_options': {
                '': '-- Configuration de Papi-web',
                '@events': '-- Liste des évènements',
            },
            'admin_main_selector': admin_event.uniq_id if admin_event else admin_main_selector,
            'admin_event': admin_event,
            'admin_event_selector_options': {
                '': 'Configuration générale',
                '@chessevents': 'Connexions à ChessEvent',
                '@timers': 'Chronomètres',
                '@tournaments': 'Tournois',
                '@screens': 'Écrans',
                '@families': 'Familles d\'écrans',
                '@rotators': 'Écrans rotatifs',
                # '@messages': 'Messages',
                # '@check_in': 'Pointage',
                # '@pairings': 'Appariements',
            },
            'admin_event_selector': admin_event_selector,
            'show_family_screens_on_event_list': SessionHandler.get_session_show_family_screens_on_screen_list(request),
            'screen_types_on_event_list': SessionHandler.get_session_screen_types_on_screen_list(request),
            'screen_types_on_family_list': SessionHandler.get_session_screen_types_on_family_list(request),
        }
        return HTMXTemplate(
            template_name="admin.html",
            context=context)

    @staticmethod
    def _user_render_index(request: HTMXRequest) -> Template:
        return HTMXTemplate(
            template_name="user.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'event_loader': EventLoader(),
                'messages': Message.messages(request),
            })


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
    @staticmethod
    def _render_index(request: HTMXRequest, ) -> Template:
        return HTMXTemplate(
            template_name="index.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'messages': Message.messages(request),
            })

    @get(
        path='/',
        name='index-get'
    )
    async def index_get(self, request: HTMXRequest, ) -> Template:
        return self._render_index(request)

    @post(path='/', name='index-post' )
    async def index(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        target: str = self._form_data_to_str_or_none(data, 'target')
        match target:
            case 'admin':
                return self._admin_render_index(request)
            case 'user':
                return self._user_render_index(request)
            case _:
                return self._render_index(request)

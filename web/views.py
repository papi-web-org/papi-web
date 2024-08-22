import time
from datetime import datetime
from logging import Logger

from pathlib import Path
from litestar import get, Controller
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate

from common import RGB, check_rgb_str
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import NewEvent
from data.loader import EventLoader
from data.screen import NewScreen
from data.util import ScreenType
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
    def _form_data_to_float_or_none(
            data: dict[str, str], field: str, empty_value: float | None = None, minimum: float = None
    ) -> float | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        float_val = float(data[field])
        if minimum is not None and float_val < minimum:
            raise ValueError(f'{float_val} < {minimum}')
        return float_val

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
            return 'on' if value else ''
        if isinstance(value, int):
            return str(value)
        if isinstance(value, Path):
            return str(value)
        raise ValueError

    @staticmethod
    def _value_to_datetime_form_data(value: float | None) -> str | None:
        if value is None:
            return ''
        return datetime.strftime(datetime.fromtimestamp(value), '%Y-%m-%dT%H:%M')

    @staticmethod
    def admin_auth(request: HTMXRequest) -> bool:
        if request.client.host == '127.0.0.1':
            return True
        return False

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
    def _event_login_needed(request: HTMXRequest, event: NewEvent, screen: NewScreen | None = None) -> bool:
        if screen is not None:
            if screen.type != ScreenType.Input:
                return False
        if not event.update_password:
            return False
        session_password: str | None = SessionHandler.get_stored_password(request, event)
        logger.debug('session_password=%s', "*" * (8 if session_password else 0))
        if session_password is None:
            Message.error(request, f'Veuillez vous identifier pour accéder aux écrans de saisie de '
                                   f'l\'évènement [{event.uniq_id}].')
            return True
        if session_password != event.update_password:
            Message.error(request, 'Code d\'accès incorrect.')
            SessionHandler.store_password(request, event, None)
            return True
        return False

    @staticmethod
    def _redirect_to_index_on_error(request: HTMXRequest, errors: str | list[str]) -> Redirect:
        Message.error(request, errors)
        return Redirect(path=index_url(request))

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
            'main_nav_tabs': {
                '': {
                    'title': 'Configuration Papi-web',
                    'template': 'admin_config.html',
                },
                '@events': {
                    'title': 'Évènements',
                    'template': 'admin_event_list.html',
                },
            },
            'event_nav_tabs': {
                '': {
                    'title': admin_event.uniq_id if admin_event else '',
                    'template': 'admin_event_config.html',
                },
                '@tournaments': {
                    'title': f'Tournois ({len(admin_event.tournaments_by_id) if admin_event else "-"})',
                    'template': 'admin_tournament_list.html',
                },
                '@screens': {
                    'title': f'Écrans ({len(admin_event.basic_screens_by_id) if admin_event else "-"})',
                    'template': 'admin_screen_list.html',
                },
                '@families': {
                    'title': f'Familles ({len(admin_event.families_by_id) if admin_event else "-"})',
                    'template': 'admin_family_list.html',
                },
                '@rotators': {
                    'title': f'Écrans rotatifs ({len(admin_event.families_by_id) if admin_event else "-"})',
                    'template': 'admin_rotator_list.html',
                },
                '@timers': {
                    'title': f'Écrans rotatifs ({len(admin_event.rotators_by_id) if admin_event else "-"})',
                    'template': 'admin_timer_list.html',
                },
                '@chessevents': {
                    'title': f'ChessEvent ({len(admin_event.chessevents_by_id) if admin_event else "-"})',
                    'template': 'admin_chessevent_list.html',
                },
            },
            'admin_main_selector': admin_event.uniq_id if admin_event else admin_main_selector,
            'admin_event': admin_event,
            'admin_event_selector': admin_event_selector,
            'show_family_screens_on_event_list': SessionHandler.get_session_show_family_screens_on_screen_list(request),
            'screen_types_on_event_list': SessionHandler.get_session_screen_types_on_screen_list(request),
            'screen_types_on_family_list': SessionHandler.get_session_screen_types_on_family_list(request),
        }
        return HTMXTemplate(
            template_name="admin.html",
            context=context)

    @classmethod
    def _user_render_event(
            cls,
            request: HTMXRequest,
            event: NewEvent,
    ) -> Template | Redirect:
        return HTMXTemplate(
            template_name="user_event.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'event': event,
                'messages': Message.messages(request),
                'now': time.time(),
            })


class IndexController(AController):
    def _render_index(self, request: HTMXRequest, ) -> Template:
        return HTMXTemplate(
            template_name="index.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'messages': Message.messages(request),
                'admin_auth': self.admin_auth(request),
            })

    @get(
        path='/',
        name='index'
    )
    async def index(self, request: HTMXRequest, ) -> Template:
        return self._render_index(request)

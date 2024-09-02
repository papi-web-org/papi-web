import time
from datetime import datetime
from logging import Logger

from pathlib import Path
from typing import Annotated

from litestar import get, Controller
from litestar.enums import RequestEncodingType
from litestar.params import Body
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


class WebContext:
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ):
        self.request = request
        self.data = data
        self.error: Redirect | Template | None = None

    @staticmethod
    def form_data_to_str(data: dict[str, str], field: str, empty_value: str | None = None) -> str | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        return data[field]

    def _form_data_to_str(self, field: str, empty_value: str | None = None) -> str | None:
        return self.form_data_to_str(self.data, field, empty_value)

    @staticmethod
    def form_data_to_int(
            data: dict[str, str], field: str, empty_value: int | None = None, minimum: int = None) -> int | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        int_val = int(data[field])
        if minimum is not None and int_val < minimum:
            raise ValueError(f'{int_val} < {minimum}')
        return int_val

    def _form_data_to_int(self, field: str, empty_value: int | None = None, minimum: int = None) -> int | None:
        return self.form_data_to_int(self.data, field, empty_value, minimum)

    @staticmethod
    def form_data_to_float(
            data: dict[str, str], field: str, empty_value: float | None = None, minimum: float = None) -> float | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        float_val = float(data[field])
        if minimum is not None and float_val < minimum:
            raise ValueError(f'{float_val} < {minimum}')
        return float_val

    def _form_data_to_float(self, field: str, empty_value: str | None = None, minimum: float = None) -> float | None:
        return self.form_data_to_float(self.data, field, empty_value, minimum)

    @staticmethod
    def form_data_to_bool(data: dict[str, str], field: str, empty_value: bool | None = None) -> bool | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip().lower()
        if not data[field]:
            return empty_value
        return data[field] in ['true', 'on', ]

    def _form_data_to_bool(self, field: str, empty_value: str | None = None) -> bool | None:
        return self.form_data_to_bool(self.data, field, empty_value)

    @staticmethod
    def form_data_to_rgb(data: dict[str, str], field: str, empty_value: RGB | None = None) -> str | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip().lower()
        if not data[field]:
            return empty_value
        return check_rgb_str(data[field])

    def _form_data_to_rgb(self, field: str, empty_value: RGB | None = None) -> str | None:
        return self.form_data_to_rgb(self.data, field, empty_value)

    def _redirect_to_index(self, errors: str | list[str]):
        Message.error(self.request, errors)
        self.error = Redirect(path=index_url(self.request))


class AController(Controller):

    @staticmethod
    def _form_data_to_str_or_none(
            data: dict[str, str], field: str, empty_value: str | None = None
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
        admin_main_selector: str = '',
        admin_event: NewEvent = None,
        admin_event_selector: str = '',
    ) -> Template:
        context: dict = {
            'papi_web_config': PapiWebConfig(),
            'odbc_drivers': odbc_drivers(),
            'access_driver': access_driver(),
            'event_loader': EventLoader.get(request=request, lazy_load=True),
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
                    'title': f'Écrans rotatifs ({len(admin_event.rotators_by_id) if admin_event else "-"})',
                    'template': 'admin_rotator_list.html',
                },
                '@timers': {
                    'title': f'Chronomètres ({len(admin_event.timers_by_id) if admin_event else "-"})',
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
            'admin_columns': SessionHandler.get_session_admin_columns(request),
            'show_family_screens_on_screen_list': SessionHandler.get_session_show_family_screens_on_screen_list(
                request),
            'show_details_on_screen_list': SessionHandler.get_session_show_details_on_screen_list(request),
            'show_details_on_family_list': SessionHandler.get_session_show_details_on_family_list(request),
            'show_details_on_rotator_list': SessionHandler.get_session_show_details_on_rotator_list(request),
            'screen_types_on_screen_list': SessionHandler.get_session_screen_types_on_screen_list(request),
        }
        return HTMXTemplate(
            template_name="admin.html",
            context=context)

    @classmethod
    def _user_render_event(
            cls,
            request: HTMXRequest,
            event: NewEvent,
            user_selector: str | None,
    ) -> Template | Redirect:
        return HTMXTemplate(
            template_name="user_event.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'event': event,
                'user_selector': user_selector or 'input',
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

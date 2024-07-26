from logging import Logger
from pathlib import Path
from typing import Annotated

from litestar import get, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate

from common.exception import PapiWebException
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import NewEvent
from data.loader import EventLoader
from database.access import access_driver, odbc_drivers
from web.messages import Message
from web.views import AController

logger: Logger = get_logger()


class AAdminController(AController):

    @staticmethod
    def form_data_to_str_or_none(data: dict[str, str], field: str, empty_value: int | None = None) -> str | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        return data[field]

    @staticmethod
    def form_data_to_int_or_none(data: dict[str, str], field: str, empty_value: int | None = None) -> int | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        return int(data[field])

    @staticmethod
    def form_data_to_bool_or_none(data: dict[str, str], field: str, empty_value: bool | None = None) -> bool | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        return bool(data[field])

    @staticmethod
    def value_to_form_data(value: str | int | bool | Path | None) -> str | None:
        if value is None:
            return ''
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, int):
            return str(value)
        if isinstance(value, bool):
            return str(1 if value else 0)
        if isinstance(value, Path):
            return str(value)
        raise ValueError

    @staticmethod
    def _get_record_illegal_moves_options(default: int | None, ) -> dict[str, str]:
        options: dict[str, str] = {
            '': '',
            '0': 'Aucun enregistrement des coups illégaux',
            '1': 'Maximum 1 coup illégal',
            '2': 'Maximum 2 coups illégaux',
            '3': 'Maximum 3 coups illégaux',
        }
        options[''] = f'Par défaut ({options[str(default)]})'
        return options

    @staticmethod
    def _admin_render_index(
        request: HTMXRequest,
        event_loader: EventLoader,
        admin_main_selector: str = '',
        admin_event: NewEvent = None,
        admin_event_selector: str = '',
    ) -> Template:
        context: dict = {
            'papi_web_config': PapiWebConfig(),
            'odbc_drivers': odbc_drivers(),
            'access_driver': access_driver(),
            'event_loader': event_loader,
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
                '@tournaments': 'Tournois',
                # '@screens': 'Écrans',
                # '@families': 'Familles d\'écrans',
                # '@rotators': 'Écrans rotatifs',
                # '@timers': 'Chronomètres',
                # '@messages': 'Messages',
                # '@check_in': 'Pointage',
                # '@pairings': 'Appariements',
            },
            'admin_event_selector': admin_event_selector,
        }
        return HTMXTemplate(
            template_name="admin.html",
            context=context)


class AdminController(AAdminController):
    @get(
        path='/admin',
        name='admin-render-index'
    )
    async def admin_render_index(self, request: HTMXRequest) -> Template | Redirect:
        return self._admin_render_index(request, EventLoader())

    @post(
        path='/admin-update-header',
        name='admin-update-header'
    )
    async def htmx_admin_update_header(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        event_loader: EventLoader = EventLoader()
        admin_main_selector: str = data.get('admin_main_selector', '')
        admin_event_selector: str = data.get('admin_event_selector', '')
        admin_event: NewEvent | None = None
        if not admin_main_selector:
            pass
        elif admin_main_selector == '@events':
            pass
        else:
            try:
                admin_event = event_loader.load_event(admin_main_selector)
            except PapiWebException as pwe:
                Message.error(request, f'L\'évènement [{admin_main_selector}] est introuvable : {pwe}')
                return self._render_messages(request)
        return self._admin_render_index(
            request, event_loader, admin_main_selector=admin_main_selector, admin_event=admin_event,
            admin_event_selector=admin_event_selector)

from logging import Logger
from typing import Annotated

from litestar import get, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import Event, get_events_sorted_by_name, get_events_by_uniq_id
from database.access import access_driver, odbc_drivers
from web.messages import Message
from web.views import AController

logger: Logger = get_logger()


class AAdminController(AController):

    @staticmethod
    def _admin_render_index(
        request: HTMXRequest,
        events: list[Event],
        admin_main_selector: str = '',
        admin_event: Event = None,
        admin_event_selector: str = '',
    ) -> Template:
        context: dict = {
            'papi_web_config': PapiWebConfig(),
            'odbc_drivers': odbc_drivers(),
            'access_driver': access_driver(),
            'events': events,
            'messages': Message.messages(request),
            'admin_main_selector_options': {
                '': '-- Configuration de Papi-web',
                '@list-events': '-- Liste des évènements',
            },
            'admin_main_selector': admin_event.uniq_id if admin_event else admin_main_selector,
            'admin_event': admin_event,
            'admin_event_selector_options': {
                '': 'Configuration',
                '@chessevents': 'ChessEvent',
                '@tournaments': 'Tournois',
                '@screens': 'Écrans',
                '@families': 'Familles d\'écrans',
                '@rotators': 'Écrans rotatifs',
                '@timers': 'Chronomètres',
                '@messages': 'Messages',
                '@check_in': 'Pointage',
                '@pairings': 'Appariements',
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
        events: list[Event] = get_events_sorted_by_name(True)
        return self._admin_render_index(request, events)

    @post(
        path='/admin-update-header',
        name='admin-update-header'
    )
    async def htmx_admin_update_header(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        error: str
        events_by_id = get_events_by_uniq_id(load_screens=False, with_tournaments_only=False)
        events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
        admin_main_selector: str = data.get('admin_main_selector', '')
        admin_event_selector: str = data.get('admin_event_selector', '')
        admin_event: Event | None = None
        try:
            if admin_main_selector == '':
                pass
            elif admin_main_selector == '@list-events':
                pass
            elif admin_main_selector:
                admin_event: Event = events_by_id[admin_main_selector]
            return self._admin_render_index(request, events, admin_main_selector, admin_event, admin_event_selector)
        except KeyError:
            Message.error(request, f'Évènement [{admin_main_selector}] introuvable')
        return self._render_messages(request)

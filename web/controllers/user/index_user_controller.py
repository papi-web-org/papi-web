from logging import Logger
from typing import Annotated, Any

from litestar import get
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, Reswap
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.status_codes import HTTP_304_NOT_MODIFIED

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import Event
from data.loader import EventLoader
from web.controllers.index_controller import AbstractController, WebContext
from web.messages import Message
from web.session import SessionHandler

logger: Logger = get_logger()


class UserWebContext(WebContext):
    """
    The basic user web context, where parameter user_tab is passed to the template engine to propagate the context.
    """

    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ] | None,
            user_tab: str | None,
    ):
        super().__init__(request, data=data)
        self.user_tab: str | None = user_tab
        if self.error:
            return
        self.check_user_tab()

    def check_user_tab(self):
        if self.user_tab not in [None, 'passed_events', 'current_events', 'coming_events', ]:
            self._redirect_error(f'Invalid value [{self.user_tab}] for parameter [user_tab]')

    @property
    def background_color(self) -> str:
        return PapiWebConfig.user_background_color

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'user_tab': self.user_tab,
        }


class AbstractUserController(AbstractController):
    pass


class IndexUserController(AbstractUserController):

    @staticmethod
    def _user_render(
            web_context: UserWebContext,
    ) -> Template:
        event_loader: EventLoader = EventLoader.get(request=web_context.request, lazy_load=True)
        current_events: list[Event]
        coming_events: list[Event]
        passed_events: list[Event]
        if web_context.admin_auth:
            current_events = event_loader.current_events
            coming_events = event_loader.coming_events
            passed_events = event_loader.passed_events
        else:
            current_events = event_loader.current_public_events
            coming_events = event_loader.coming_public_events
            passed_events = event_loader.passed_public_events
        nav_tabs: dict[str, dict] = {
            'current_events': {
                'title': f'Évènements en cours ({len(current_events) or "-"})',
                'events': current_events,
                'empty_str': 'Aucun évènement en cours.',
                'class': 'bg-primary-subtle',
                'icon_class': 'bi-calendar',
                'disabled': not current_events,
            },
            'coming_events': {
                'title': f'Évènements à venir ({len(coming_events) or "-"})',
                'events': coming_events,
                'empty_str': 'Aucun évènement à venir.',
                'class': 'bg-info-subtle',
                'icon_class': 'bi-calendar-check',
                'disabled': not coming_events,
            },
            'passed_events': {
                'title': f'Évènements passés ({len(passed_events) or "-"})',
                'events': passed_events,
                'empty_str': 'Aucun évènement passé.',
                'class': 'bg-secondary-subtle',
                'icon_class': 'bi-calendar-minus',
                'disabled': not passed_events,
            },
        }
        if not web_context.user_tab or nav_tabs[web_context.user_tab]['disabled']:
            web_context.user_tab = list(nav_tabs.keys())[0]
        for nav_index in range(len(nav_tabs)):
            if web_context.user_tab == list(nav_tabs.keys())[nav_index] \
                    and nav_tabs[web_context.user_tab]['disabled']:
                web_context.user_tab = list(nav_tabs.keys())[(nav_index + 1) % len(nav_tabs)]
        return HTMXTemplate(
            template_name="user_index.html",
            context=web_context.template_context | {
                'messages': Message.messages(web_context.request),
                'user_columns': SessionHandler.get_session_user_columns(web_context.request),
                'nav_tabs': nav_tabs,
            })

    @staticmethod
    def _user_refresh_needed(
            request: HTMXRequest,
            user_tab: str | None,
            date: float, ) -> bool:
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        web_context: UserWebContext = UserWebContext(request, data=None, user_tab=user_tab)
        if web_context.error:
            return False
        events: list[Event]
        if web_context.admin_auth:
            events = list(event_loader.events_by_id.values())
        else:
            events = event_loader.public_events
        for event in events:
            if event.last_update > date:
                return True
            for tournament in event.tournaments_by_id.values():
                if tournament.last_update > date:
                    return True
        return False

    def _user(
            self, request: HTMXRequest,
            user_tab: str | None,
            user_columns: int | None,
    ) -> Template | Reswap | Redirect:
        if user_columns:
            SessionHandler.set_session_user_columns(request, user_columns)
        date: float | None = self.get_if_modified_since(request)
        if date is None or self._user_refresh_needed(request, user_tab, date):
            web_context: UserWebContext = UserWebContext(request, data=None, user_tab=user_tab)
            return self._user_render(web_context)
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

    @get(
        path='/user',
        name='user',
    )
    async def htmx_user(
            self, request: HTMXRequest,
            user_columns: int | None,
    ) -> Template | Reswap | Redirect:
        return self._user(request, user_tab=None, user_columns=user_columns)

    @get(
        path='/user/{user_tab:str}',
        name='user-tab',
    )
    async def htmx_user_tab(
            self, request: HTMXRequest,
            user_tab: str,
            user_columns: int | None,
    ) -> Template | Reswap | Redirect:
        return self._user(request, user_tab=user_tab, user_columns=user_columns)

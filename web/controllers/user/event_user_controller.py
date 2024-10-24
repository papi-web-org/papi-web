from contextlib import suppress
from logging import Logger
from typing import Annotated, Any

from litestar import get
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import Reswap, HTMXTemplate, ClientRedirect
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.status_codes import HTTP_304_NOT_MODIFIED

from common.exception import PapiWebException
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import Event
from data.loader import EventLoader
from data.rotator import Rotator
from data.screen import Screen
from data.util import ScreenType
from web.controllers.user.index_user_controller import AbstractUserController, UserWebContext
from web.messages import Message
from web.session import SessionHandler

logger: Logger = get_logger()


class EventUserWebContext(UserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ] | None,
            event_uniq_id: str,
            user_event_tab: str | None,
    ):
        super().__init__(request, data=data, user_tab=None)
        self.user_event: Event | None = None
        self.user_event_tab: str | None = user_event_tab
        if self.error:
            return
        if not event_uniq_id:
            self._redirect_error(f'L\'évènement n\'est pas spécifie')
            return
        try:
            self.user_event = EventLoader.get(request=self.request, lazy_load=False).load_event(event_uniq_id)
            if self.user_event.public or self.admin_auth:
                self.user_event_tab = user_event_tab
                return
            self._redirect_error(f'L\'évènement [{self.user_event.uniq_id}] est privé.')
        except PapiWebException as pwe:
            self._redirect_error(f'L\'évènement [{event_uniq_id}] est introuvable : {pwe}')

    def check_user_tab(self):
        pass

    @property
    def background_image(self) -> str:
        return ''

    @property
    def background_color(self) -> str:
        return PapiWebConfig.user_background_color

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'user_event_tab': self.user_event_tab,
            'user_event': self.user_event,
        }


class EventUserController(AbstractUserController):

    @staticmethod
    def _user_event_render(
            web_context: EventUserWebContext,
    ) -> Template:
        input_screens: list[Screen]
        boards_screens: list[Screen]
        players_screens: list[Screen]
        results_screens: list[Screen]
        image_screens: list[Screen]
        rotators: list[Rotator]
        if web_context.admin_auth:
            input_screens = web_context.user_event.input_screens_sorted_by_uniq_id
            boards_screens = web_context.user_event.boards_screens_sorted_by_uniq_id
            players_screens = web_context.user_event.players_screens_sorted_by_uniq_id
            results_screens = web_context.user_event.results_screens_sorted_by_uniq_id
            image_screens = web_context.user_event.image_screens_sorted_by_uniq_id
            rotators = web_context.user_event.rotators_sorted_by_uniq_id
        else:
            input_screens = web_context.user_event.public_input_screens_sorted_by_uniq_id
            boards_screens = web_context.user_event.public_boards_screens_sorted_by_uniq_id
            players_screens = web_context.user_event.public_players_screens_sorted_by_uniq_id
            results_screens = web_context.user_event.public_results_screens_sorted_by_uniq_id
            image_screens = web_context.user_event.public_image_screens_sorted_by_uniq_id
            rotators = web_context.user_event.public_rotators_sorted_by_uniq_id
        nav_tabs: dict[str, dict] = {
            'input': {
                'title': f'Saisie des résultats ({len(input_screens) or "-"})',
                'screens': input_screens,
                'disabled': not input_screens,
            },
            'boards': {
                'title': f'Appariements par échiquier ({len(boards_screens) or "-"})',
                'screens': boards_screens,
                'disabled': not boards_screens,
            },
            'players': {
                'title': f'Appariements par ordre alphabétique ({len(players_screens) or "-"})',
                'screens': players_screens,
                'disabled': not players_screens,
            },
            'results': {
                'title': f'Derniers résultats ({len(results_screens) or "-"})',
                'screens': results_screens,
                'disabled': not results_screens,
            },
            'image': {
                'title': f'Image ({len(image_screens) or "-"})',
                'screens': image_screens,
                'disabled': not image_screens,
            },
            'rotators': {
                'title': f'Écrans rotatifs ({len(rotators) or "-"})',
                'rotators': rotators,
                'disabled': not rotators,
            },
        }
        if not web_context.user_event_tab or nav_tabs[web_context.user_event_tab]['disabled']:
            web_context.user_event_tab = list(nav_tabs.keys())[0]
        for nav_index in range(len(nav_tabs)):
            if web_context.user_event_tab == list(nav_tabs.keys())[nav_index] \
                    and nav_tabs[web_context.user_event_tab]['disabled']:
                web_context.user_event_tab = list(nav_tabs.keys())[(nav_index + 1) % len(nav_tabs)]
        return HTMXTemplate(
            template_name="user_event.html",
            context=web_context.template_context | {
                'messages': Message.messages(web_context.request),
                'user_columns': SessionHandler.get_session_user_columns(web_context.request),
                'nav_tabs': nav_tabs,
            })

    @staticmethod
    def _user_event_refresh_needed(event: Event, date: float, ) -> bool:
        if event.last_update > date:
            return True
        for screen in event.basic_screens_by_id.values():
            if screen.last_update > date:
                return True
            for screen_set in screen.screen_sets_by_id.values():
                if screen_set.last_update > date:
                    return True
                if screen_set.tournament.last_update > date:
                    return True
                if screen.type in [ScreenType.Boards, ScreenType.Input, ]:
                    if screen_set.tournament.last_illegal_move_update > date:
                        return True
                    if screen_set.tournament.last_result_update > date:
                        return True
                    if screen_set.tournament.last_update > date:
                        return True
                if screen_set.tournament.last_check_in_update > date:
                    return True
            if screen.type == ScreenType.Results:
                results_tournament_ids: list[int] = screen.results_tournament_ids \
                    if screen.results_tournament_ids else event.tournaments_by_id.keys()
                for tournament_id in results_tournament_ids:
                    with suppress(KeyError):
                        if screen.event.tournaments_by_id[tournament_id].last_result_update > date:
                            return True
        for family in event.families_by_id.values():
            if family.last_update > date:
                return True
            if family.tournament.last_update > date:
                return True
            match family.type:
                case ScreenType.Boards | ScreenType.Input:
                    if family.tournament.last_illegal_move_update > date:
                        return True
                    if family.tournament.last_result_update > date:
                        return True
                    if family.tournament.last_check_in_update > date:
                        return True
                case ScreenType.Players:
                    if family.tournament.last_check_in_update > date:
                        return True
                case _:
                    raise ValueError(f'type={family.type}')
        return False

    def _user_event(
            self, request: HTMXRequest,
            event_uniq_id: str,
            user_event_tab: str | None,
            user_columns: int | None,
    ) -> Template | Reswap | ClientRedirect:
        web_context: EventUserWebContext = EventUserWebContext(
            request,
            data=None,
            event_uniq_id=event_uniq_id,
            user_event_tab=user_event_tab)
        if web_context.error:
            return web_context.error
        if user_columns:
            SessionHandler.set_session_user_columns(request, user_columns)
        date: float | None = self.get_if_modified_since(request)
        if date is None or self._user_event_refresh_needed(web_context.user_event, date):
            return self._user_event_render(web_context)
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

    @get(
        path='/user/event/{event_uniq_id:str}',
        name='user-event',
    )
    async def htmx_user_event(
            self, request: HTMXRequest,
            event_uniq_id: str,
            user_columns: int | None,
    ) -> Template | Reswap | ClientRedirect:
        return self._user_event(
            request, event_uniq_id=event_uniq_id, user_event_tab=None, user_columns=user_columns)

    @get(
        path='/user/event/{event_uniq_id:str}/{user_event_tab:str}',
        name='user-event-tab',
    )
    async def htmx_user_event_tab(
            self, request: HTMXRequest,
            event_uniq_id: str,
            user_event_tab: str,
            user_columns: int | None,
    ) -> Template | Reswap | ClientRedirect:
        return self._user_event(
            request, event_uniq_id=event_uniq_id, user_event_tab=user_event_tab, user_columns=user_columns)

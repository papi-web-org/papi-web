from contextlib import suppress
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
from data.family import Family
from data.screen_set import ScreenSet
from data.tournament import Tournament
from data.util import ScreenType
from web.controllers.index_controller import AbstractController
from web.controllers.user.index_user_controller import AbstractUserController
from web.controllers.user.screen_user_controller import BasicScreenOrFamilyUserWebContext
from web.session import SessionHandler

logger: Logger = get_logger()


class ScreenSetOrFamilyUserWebContext(BasicScreenOrFamilyUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ] | None,
            event_uniq_id: str,
            screen_uniq_id: str,
            screen_set_uniq_id: str,
    ):
        super().__init__(request, data=data, event_uniq_id=event_uniq_id, screen_uniq_id=screen_uniq_id)
        self.screen_set: ScreenSet | None = None
        if self.error:
            return
        try:
            self.screen_set = self.screen.screen_sets_by_uniq_id[screen_set_uniq_id]
        except KeyError:
            self._redirect_error(
                f'L\'ensemble [{screen_set_uniq_id}] de l\'écran [{self.screen.uniq_id}] est introuvable.')
            return

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'screen_set': self.screen_set,
        }


class ScreenSetUserController(AbstractUserController):

    @staticmethod
    def _user_screen_set_refresh_needed(
            screen_set: ScreenSet,
            family: Family,
            date: float,
    ) -> bool:
        tournament: Tournament = screen_set.tournament if screen_set else family.tournament
        if tournament.last_update > date:
            if tournament.last_update > date:
                return True
        if tournament.last_check_in_update > date:
            return True
        type: ScreenType = screen_set.type if screen_set else family.type
        match type:
            case ScreenType.Boards | ScreenType.Input:
                if tournament.last_illegal_move_update > date:
                    return True
                if tournament.last_result_update > date:
                    return True
            case ScreenType.Players:
                pass
            case _:
                raise ValueError(f'type={screen_set.type}')
        with suppress(FileNotFoundError):
            if tournament.file.lstat().st_mtime > date:
                return True
        return False

    @get(
        path='/user/screen-set/{event_uniq_id:str}/{screen_uniq_id:str}/{screen_set_uniq_id:str}',
        name='user-screen-set',
    )
    async def htmx_user_screen_set(
            self, request: HTMXRequest,
            event_uniq_id: str,
            screen_uniq_id: str,
            screen_set_uniq_id: str,
    ) -> Template | Reswap | Redirect:
        web_context: ScreenSetOrFamilyUserWebContext = ScreenSetOrFamilyUserWebContext(
            request, data=None, event_uniq_id=event_uniq_id, screen_uniq_id=screen_uniq_id,
            screen_set_uniq_id=screen_set_uniq_id)
        if web_context.error:
            return web_context.error
        date: float = self.get_if_modified_since(request)
        if date is None:
            return AbstractController.redirect_error(request, 'L\'entête If-Modified-Since est absente.')
        if self._user_screen_set_refresh_needed(web_context.screen_set, web_context.family, date):
            if web_context.screen.type in [ScreenType.Boards, ScreenType.Input, ]:
                return HTMXTemplate(
                    template_name='user_boards_screen_set.html',
                    context=web_context.template_context | {
                        'last_result_updated': SessionHandler.get_session_last_result_updated(request),
                        'last_illegal_move_updated': SessionHandler.get_session_last_illegal_move_updated(request),
                        'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(request),
                    },
                )
            else:
                return HTMXTemplate(
                    template_name='user_players_screen_set.html',
                    context=web_context.template_context | {
                    },
                )
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

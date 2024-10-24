from contextlib import suppress
from logging import Logger
from typing import Annotated, Any

from litestar import post, get
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import Reswap, HTMXTemplate, ClientRedirect
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.status_codes import HTTP_304_NOT_MODIFIED

from common.logger import get_logger
from data.family import Family
from data.rotator import Rotator
from data.screen import Screen
from data.tournament import Tournament
from data.util import ScreenType
from web.controllers.user.event_user_controller import EventUserWebContext
from web.controllers.user.index_user_controller import AbstractUserController
from web.messages import Message
from web.session import SessionHandler

logger: Logger = get_logger()


class ScreenOrRotatorUserWebContext(EventUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ] | None,
            event_uniq_id: str,
            screen_uniq_id: str | None,
            rotator_id: int | None,
            rotator_screen_index: int | None,
    ):
        super().__init__(request, data=data, event_uniq_id=event_uniq_id, user_event_tab=None)
        self.screen: Screen | None = None
        self.rotator: Rotator | None = None
        self.rotator_screen_index: int | None = rotator_screen_index or 0
        if self.error:
            return
        if screen_uniq_id:
            try:
                self.screen = self.user_event.screens_by_uniq_id[screen_uniq_id]
            except KeyError:
                self._redirect_error(f'L\'écran [{screen_uniq_id}] n\'existe pas.')
                return
            if not self.screen.public and not self.admin_auth:
                self._redirect_error(f'L\'écran [{self.screen.uniq_id}] est réservé aux arbitres.')
                return
            self.user_event_tab = self.screen.type.to_str()
        else:
            try:
                self.rotator = self.user_event.rotators_by_id[rotator_id]
            except KeyError:
                self._redirect_error(f'L\'écran rotatif [{rotator_id}] n\'existe pas.')
                return
            if not self.rotator.public and not self.admin_auth:
                self._redirect_error(f'L\'écran rotatif [{self.rotator.uniq_id}] est réservé aux arbitres.')
                return
            self.rotator_screen_index = self.rotator_screen_index % len(self.rotator.rotating_screens)
            self.screen = self.rotator.rotating_screens[self.rotator_screen_index]
            self.user_event_tab = 'rotators'

    @property
    def login_needed(self) -> bool:
        if self.screen is not None:
            if self.screen.type != ScreenType.Input:
                return False
        if not self.user_event.update_password:
            return False
        session_password: str | None = SessionHandler.get_stored_password(self.request, self.user_event)
        logger.debug('session_password=%s', "*" * (8 if session_password else 0))
        if session_password is None:
            Message.error(
                self.request,
                f'Veuillez vous identifier pour accéder aux écrans de saisie de l\'évènement '
                f'[{self.user_event.uniq_id}].')
            return True
        if session_password != self.user_event.update_password:
            Message.error(self.request, 'Code d\'accès incorrect.')
            SessionHandler.store_password(self.request, self.user_event, None)
            return True
        return False

    @property
    def background_image(self) -> str:
        return self.screen.background_image

    @property
    def background_color(self) -> str:
        return self.screen.background_color

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'rotator': self.rotator,
            'rotator_screen_index': self.rotator_screen_index,
            'screen': self.screen,
            'login_needed': self.login_needed,
        }


class ScreenUserWebContext(ScreenOrRotatorUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ] | None,
            event_uniq_id: str,
            screen_uniq_id: str | None,
            screen_needed: bool,
    ):
        super().__init__(
            request, data=data, event_uniq_id=event_uniq_id, screen_uniq_id=screen_uniq_id, rotator_id=None,
            rotator_screen_index=None)
        if screen_needed and not self.screen:
            self._redirect_error(f'L\'écran est obligatoire.')
            return


class RotatorUserWebContext(ScreenOrRotatorUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ] | None,
            event_uniq_id: str,
            rotator_id: int,
            rotator_screen_index: int,
    ):
        super().__init__(
            request, data=data, event_uniq_id=event_uniq_id, screen_uniq_id=None, rotator_id=rotator_id,
            rotator_screen_index=rotator_screen_index)


class BasicScreenOrFamilyUserWebContext(ScreenUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ] | None,
            event_uniq_id: str,
            screen_uniq_id: str | None,
    ):
        super().__init__(
            request, data=data, event_uniq_id=event_uniq_id, screen_uniq_id=screen_uniq_id, screen_needed=True)
        self.family: Family | None = None
        if self.error:
            return
        if ':' in self.screen.uniq_id:
            family_uniq_id: str = self.screen.uniq_id.split(':')[0]
            try:
                self.family = self.user_event.families_by_uniq_id[family_uniq_id]
            except KeyError:
                self._redirect_error(f'La famille [{family_uniq_id}] n\'existe pas.')
                return

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'family': self.family,
        }


class LoginUserWebContext(ScreenUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            screen_uniq_id: str | None,
    ):
        super().__init__(
            request, data=data, event_uniq_id=event_uniq_id, screen_uniq_id=screen_uniq_id, screen_needed=True)
        field: str = 'password'
        self.password: str = self._form_data_to_str(field, None)
        if self.password is None:
            self._redirect_error(f'La paramètre [{field}] est manquant.')


class AbstractScreenUserController(AbstractUserController):

    @classmethod
    def _user_screen_render(
            cls,
            web_context: ScreenOrRotatorUserWebContext,
    ) -> Template | ClientRedirect:
        return HTMXTemplate(
            template_name="user_screen.html",
            context=web_context.template_context | {
                'last_result_updated': SessionHandler.get_session_last_result_updated(web_context.request),
                'last_illegal_move_updated': SessionHandler.get_session_last_illegal_move_updated(web_context.request),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(web_context.request),
                'messages': Message.messages(web_context.request),
            },
        )


class ScreenUserController(AbstractScreenUserController):

    @post(
        path='/user/login/{event_uniq_id:str}/{screen_uniq_id:str}',
        name='user-login',
    )
    async def htmx_user_login(
            self,
            request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            screen_uniq_id: str,
    ) -> Template | ClientRedirect:
        web_context: LoginUserWebContext = LoginUserWebContext(
            request, data=data, event_uniq_id=event_uniq_id, screen_uniq_id=screen_uniq_id)
        if web_context.error:
            return web_context.error
        if data['password'] == web_context.user_event.update_password:
            Message.success(request, 'Authentification réussie !')
            SessionHandler.store_password(request, web_context.user_event, web_context.password)
            return self._user_screen_render(web_context)
        if data['password'] == '':
            Message.warning(request, 'Veuillez indiquer le code d\'accès.')
        else:
            Message.error(request, 'Code d\'accès incorrect.')
            SessionHandler.store_password(request, web_context.user_event, None)
        return self._render_messages(request)

    @staticmethod
    def _user_screen_refresh_needed(
            web_context: BasicScreenOrFamilyUserWebContext,
            date: float,
    ) -> bool:
        if web_context.screen:
            if web_context.screen.event.last_update > date:
                return True
            if web_context.screen.last_update > date:
                return True
            match web_context.screen.type:
                case ScreenType.Boards | ScreenType.Input | ScreenType.Players | ScreenType.Image:
                    pass
                case ScreenType.Results:
                    results_tournament_ids: list[int] = web_context.screen.results_tournament_ids \
                        if web_context.screen.results_tournament_ids \
                        else web_context.screen.event.tournaments_by_id.keys()
                    for tournament_id in results_tournament_ids:
                        with suppress(KeyError):
                            tournament: Tournament = web_context.screen.event.tournaments_by_id[tournament_id]
                            if tournament.last_update > date:
                                return True
                            if tournament.last_result_update > date:
                                return True
                case _:
                    raise ValueError(f'type={web_context.screen.type}')
        else:
            if web_context.family.event.last_update > date:
                return True
            if web_context.family.last_update > date:
                return True
        return False

    @get(
        path='/user/screen/{event_uniq_id:str}/{screen_uniq_id:str}',
        name='user-screen',
    )
    async def htmx_user_screen(
            self, request: HTMXRequest,
            event_uniq_id: str,
            screen_uniq_id: str,
    ) -> Template | Reswap | ClientRedirect:
        web_context: BasicScreenOrFamilyUserWebContext = BasicScreenOrFamilyUserWebContext(
            request, data=None, event_uniq_id=event_uniq_id, screen_uniq_id=screen_uniq_id)
        if web_context.error:
            return web_context.error
        date: float = self.get_if_modified_since(request)
        if date is None or self._user_screen_refresh_needed(web_context, date):
            return self._user_screen_render(web_context)
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

    @get(
        path='/user/rotator/{event_uniq_id:str}/{rotator_id:int}/{rotator_screen_index:int}',
        name='user-rotator'
    )
    async def htmx_user_rotator(
        self, request: HTMXRequest,
        event_uniq_id: str,
        rotator_id: int,
        rotator_screen_index: int,
    ) -> Template | ClientRedirect:
        web_context: RotatorUserWebContext = RotatorUserWebContext(
            request, data=None, event_uniq_id=event_uniq_id, rotator_id=rotator_id,
            rotator_screen_index=rotator_screen_index)
        if web_context.error:
            return web_context.error
        return self._user_screen_render(web_context)

import time
from contextlib import suppress
from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import Reswap, HTMXTemplate
from litestar.status_codes import HTTP_304_NOT_MODIFIED

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.family import Family
from data.rotator import Rotator
from data.screen import Screen
from data.tournament import Tournament
from data.util import ScreenType
from web.messages import Message
from web.session import SessionHandler
from web.views import WebContext, AController
from web.views_user import AUserController, EventUserWebContext

logger: Logger = get_logger()


class ScreenOrRotatorUserWebContext(EventUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
            load_rotator: bool,
    ):
        super().__init__(request, data, lazy_load)
        self.screen: Screen | None = None
        self.rotator: Rotator | None = None
        self.rotator_screen_index: int = 0
        if self.error:
            return
        if load_rotator:
            field: str = 'rotator_id'
            try:
                rotator_id: int | None = self._form_data_to_int(field, minimum=1)
            except ValueError as ve:
                self._redirect_error(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
                return
            try:
                self.rotator = self.user_event.rotators_by_id[rotator_id]
            except KeyError:
                self._redirect_error(f'L\'écran rotatif [{rotator_id}] n\'existe pas.')
                return
            try:
                self.rotator_screen_index = self._form_data_to_int(field, 0)
            except ValueError as ve:
                self._redirect_error(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
                return
            if not self.rotator.public and not self.admin_auth:
                self._redirect_error(f'L\'écran rotatif [{self.rotator.uniq_id}] est réservé aux arbitres.')
                return
            self.rotator_screen_index = self.rotator_screen_index % len(self.rotator.rotating_screens)
            self.screen = self.rotator.rotating_screens[self.rotator_screen_index]
        else:
            field: str = 'screen_uniq_id'
            screen_uniq_id: str = self._form_data_to_str(field)
            try:
                self.screen = self.user_event.screens_by_uniq_id[screen_uniq_id]
            except KeyError:
                self._redirect_error(f'L\'écran [{data.get(field, None)}] n\'existe pas.')
                return
            if not self.screen.public and not self.admin_auth:
                self._redirect_error(f'L\'écran [{self.screen.uniq_id}] est réservé aux arbitres.')
                return


class ScreenUserWebContext(ScreenOrRotatorUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data, lazy_load, False)


class RotatorUserWebContext(ScreenOrRotatorUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data, lazy_load, True)


class BasicScreenOrFamilyUserWebContext(ScreenUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data, lazy_load)
        self.family: Family | None = None
        if self.error:
            return
        if ':' in self.screen.uniq_id:
            family_uniq_id: str = self.screen.uniq_id.split(':')[0]
            self.screen = None
            try:
                self.family = self.user_event.families_by_uniq_id[family_uniq_id]
            except KeyError:
                self._redirect_error(f'La famille [{family_uniq_id}] n\'existe pas.')
                return


class UserScreenController(AUserController):

    @staticmethod
    def _event_login_needed(
            web_context: ScreenOrRotatorUserWebContext
    ) -> bool:
        if web_context.screen is not None:
            if web_context.screen.type != ScreenType.Input:
                return False
        if not web_context.user_event.update_password:
            return False
        session_password: str | None = SessionHandler.get_stored_password(web_context.request, web_context.user_event)
        logger.debug('session_password=%s', "*" * (8 if session_password else 0))
        if session_password is None:
            Message.error(web_context.request, f'Veuillez vous identifier pour accéder aux écrans de '
                                               f'saisie de l\'évènement [{web_context.user_event.uniq_id}].')
            return True
        if session_password != web_context.user_event.update_password:
            Message.error(web_context.request, 'Code d\'accès incorrect.')
            SessionHandler.store_password(web_context.request, web_context.user_event, None)
            return True
        return False

    @classmethod
    def _user_render_screen(
            cls,
            web_context: ScreenOrRotatorUserWebContext,
    ) -> Template:
        return HTMXTemplate(
            template_name="user_screen.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'user_main_selector': web_context.user_main_selector,
                'user_event_selector': web_context.user_event_selector,
                'user_event': web_context.user_event,
                'screen': web_context.screen,
                'rotator': web_context.rotator,
                'rotator_screen_index': web_context.rotator_screen_index,
                'now': time.time(),
                'login_needed': cls._event_login_needed(web_context),
                'last_result_updated': SessionHandler.get_session_last_result_updated(web_context.request),
                'last_illegal_move_updated': SessionHandler.get_session_last_illegal_move_updated(web_context.request),
                'last_check_in_updated': SessionHandler.get_session_last_check_in_updated(web_context.request),
                'messages': Message.messages(web_context.request),
            },
        )

    @post(
        path='/user-login',
        name='user-login',
    )
    async def htmx_login(
            self,
            request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        web_context: EventUserWebContext = EventUserWebContext(request, data, True)
        if web_context.error:
            return web_context.error
        if data['password'] == web_context.user_event.update_password:
            Message.success(request, 'Authentification réussie !')
            SessionHandler.store_password(request, web_context.user_event, data['password'])
            web_context: ScreenUserWebContext = ScreenUserWebContext(request, data, False)
            if web_context.error:
                return web_context.error
            return self._user_render_screen(web_context)
        if data['password'] == '':
            Message.warning(request, 'Veuillez indiquer le code d\'accès.')
        else:
            Message.error(request, 'Code d\'accès incorrect.')
            SessionHandler.store_password(request, web_context.user_event, None)
        return self._render_messages(request)

    @post(
        path='/user-screen-render',
        name='user-screen-render',
    )
    async def htmx_user_screen_render(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        web_context: ScreenUserWebContext = ScreenUserWebContext(request, data, False)
        if web_context.error:
            return web_context.error
        return self._user_render_screen(web_context)

    @staticmethod
    def _user_screen_page_update_needed(
            web_context: BasicScreenOrFamilyUserWebContext,
            date: float,
    ) -> bool:
        if web_context.screen:
            if web_context.screen.event.last_update > date:
                return True
            if web_context.screen.last_update > date:
                return True
            match web_context.screen.type:
                case ScreenType.Boards | ScreenType.Input | ScreenType.Players:
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

    @post(
        path='/user-screen-render-if-updated',
        name='user-screen-render-if-updated',
    )
    async def htmx_user_screen_render_if_updated(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Reswap | Redirect:
        web_context: BasicScreenOrFamilyUserWebContext = BasicScreenOrFamilyUserWebContext(
            request, data, True)
        if web_context.error:
            return web_context.error
        try:
            date: float = WebContext.form_data_to_float(data, 'date', 0.0)
        except ValueError as ve:
            return AController.redirect_error(request, str(ve))
        if date <= 0.0:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)  # timer is hanged
        if self._user_screen_page_update_needed(web_context, date):
            web_context: ScreenUserWebContext = ScreenUserWebContext(request, data, False)
            if web_context.error:
                return web_context.error
            return self._user_render_screen(web_context)
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

    @post(
        path='/user-rotator-render',
        name='user-rotator-render'
    )
    async def htmx_user_rotator_render_screen(
        self, request: HTMXRequest,
        data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        web_context: RotatorUserWebContext = RotatorUserWebContext(request, data, False)
        if web_context.error:
            return web_context.error
        return self._user_render_screen(web_context)

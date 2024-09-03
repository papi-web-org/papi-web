import time

from logging import Logger
from typing import Annotated

from litestar import get, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.status_codes import HTTP_304_NOT_MODIFIED
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, Reswap

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import NewEvent
from data.family import NewFamily
from data.loader import EventLoader
from data.rotator import NewRotator
from data.screen import NewScreen
from data.tournament import NewTournament
from web.messages import Message
from web.session import SessionHandler
from web.views import AController, WebContext

logger: Logger = get_logger()


class UserWebContext(WebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ):
        super().__init__(request, data)
        self.user_event_selector: str = self._form_data_to_str('user_event_selector')


class EventUserWebContext(UserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data)
        try:
            user_event_uniq_id: str = self._form_data_to_str('user_event_uniq_id')
        except ValueError as ve:
            self._redirect_to_index(str(ve))
            return
        self.event: NewEvent = EventLoader.get(request=self.request, lazy_load=lazy_load).load_event(user_event_uniq_id)
        if self.event.errors:
            self._redirect_to_index(self.event.errors)
            return
        if not self.event.public:
            self._redirect_to_index(f'L\'évènement [{self.event.uniq_id}] est privé.')
            return


class RotatorUserWebContext(EventUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data, lazy_load)
        self.rotator: NewRotator | None = None
        self.rotator_screen_index: int = 0
        if self.error:
            return
        field: str = 'rotator_id'
        try:
            rotator_id: int | None = self._form_data_to_int(field)
        except ValueError as ve:
            self._redirect_to_index(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
            return
        field: str = 'rotator_screen_index'
        if rotator_id:
            try:
                rotator_screen_index: int = self._form_data_to_int(field, 0)
            except ValueError as ve:
                self._redirect_to_index(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
                return
            try:
                self.rotator = self.event.rotators_by_id[rotator_id]
            except KeyError:
                self._redirect_to_index(f'L\'écran rotatif [{rotator_id}] n\'existe pas.')
                return
            self.rotator_screen_index = rotator_screen_index


class ScreenUserWebContext(RotatorUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data, lazy_load)
        self.screen: NewScreen | None = None
        if self.error:
            return
        field: str = 'screen_uniq_id'
        screen_uniq_id: str = self._form_data_to_str(field)
        try:
            self.screen = self.event.screens_by_uniq_id[screen_uniq_id]
        except KeyError:
            self._redirect_to_index(f'L\'écran [{data.get(field, None)}] n\'existe pas.')
            return


class BasicScreenOrFamilyUserWebContext(ScreenUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data, lazy_load)
        self.family: NewFamily | None = None
        if self.error:
            return
        if ':' in self.screen.uniq_id:
            family_uniq_id: str = self.screen.uniq_id.split(':')[0]
            self.screen = None
            try:
                self.family = self.event.families_by_uniq_id[family_uniq_id]
            except KeyError:
                self._redirect_to_index(f'La famille [{family_uniq_id}] n\'existe pas.')
                return


class TournamentUserWebContext(ScreenUserWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            tournament_started: bool | None,
    ):
        super().__init__(request, data, tournament_started is None)
        self.tournament: NewTournament | None = None
        if self.error:
            return
        field: str = 'tournament_id'
        try:
            tournament_id: int | None = self._form_data_to_int(field)
        except ValueError as ve:
            self._redirect_to_index(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
            return
        try:
            self.tournament: NewTournament = self.event.tournaments_by_id[tournament_id]
        except KeyError:
            self._redirect_to_index(f'Le tournoi [{tournament_id}] n\'existe pas.')
            return
        if tournament_started is not None:
            if tournament_started:
                if not self.tournament.current_round:
                    self._redirect_to_index(f'Le tournoi [{self.tournament.uniq_id}] n\'est pas commencé.')
                    return
            else:
                if self.tournament.current_round:
                    self._redirect_to_index(f'Le tournoi [{self.tournament.uniq_id}] est commencé.')
                    return


class AUserController(AController):
    pass


class UserIndexController(AUserController):

    @staticmethod
    def _user_render_index(
            request: HTMXRequest,
    ) -> Template:
        return HTMXTemplate(
            template_name="user_index.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'event_loader': EventLoader.get(request=request, lazy_load=True),
                'messages': Message.messages(request),
                'now': time.time(),
                'user_columns': SessionHandler.get_session_user_columns(request),
            })

    @staticmethod
    def _user_index_update_needed(
            request: HTMXRequest,
            date: float, ) -> bool:
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        for public_event in event_loader.public_events:
            web_context: EventUserWebContext = EventUserWebContext(
                request, {'event_uniq_id': public_event.uniq_id, }, True)
            if web_context.error:
                return False
            if web_context.event.last_update > date:
                return True
            for tournament in web_context.event.tournaments_by_id.values():
                if tournament.last_update > date:
                    return True
        return False

    @post(
        path='/user-render-if-updated',
        name='user-render-if-updated',
    )
    async def htmx_user_render_if_updated(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Reswap:
        try:
            date: float = WebContext.form_data_to_float(data, 'date', 0.0)
        except ValueError as ve:
            Message.error(request, str(ve))
            return self._render_messages(request)
        if date <= 0.0:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)  # timer is hanged
        if self._user_index_update_needed(request, date):
            return self._user_render_index(request)
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)

    @get(
        path='/user-render',
        name='user-render',
    )
    async def htmx_user_render_index(self, request: HTMXRequest) -> Template:
        return self._user_render_index(request)

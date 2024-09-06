from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.chessevent import ChessEvent
from data.loader import EventLoader
from database.sqlite import EventDatabase
from database.store import StoredChessEvent
from web.messages import Message
from web.views import WebContext
from web.views_admin import AAdminController
from web.views_admin_event import EventAdminWebContext

logger: Logger = get_logger()


class ChessEventAdminWebContext(EventAdminWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
            chessevent_needed: bool,
    ):
        super().__init__(request, data, lazy_load, True)
        self.admin_chessevent: ChessEvent | None = None
        field: str = 'admin_chessevent_id'
        if field in self.data:
            try:
                admin_chessevent_id: int | None = self._form_data_to_int(field, minimum=1)
            except ValueError as ve:
                self._redirect_error(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
                return
            try:
                self.admin_chessevent = self.admin_event.chessevents_by_id[admin_chessevent_id]
            except KeyError:
                self._redirect_error(f'La connexion à ChessEvent [{admin_chessevent_id}] n\'existe pas')
                return
        if chessevent_needed and not self.admin_chessevent:
            self._redirect_error(f'La connexion à ChessEvent n\'est pas spécifié')
            return


class AdminChessEventController(AAdminController):

    @staticmethod
    def _admin_validate_chessevent_update_data(
            action: str,
            web_context: ChessEventAdminWebContext,
            data: dict[str, str] | None = None,
    ) -> StoredChessEvent:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        uniq_id: str = WebContext.form_data_to_str(data, 'uniq_id')
        match action:
            case 'create':
                if not uniq_id:
                    errors['uniq_id'] = 'Veuillez entrer l\'identifiant de la connexion à ChessEvent.'
                elif uniq_id in web_context.admin_event.chessevents_by_uniq_id:
                    errors['uniq_id'] = f'La connexion à ChessEvent [{uniq_id}] existe déjà.'
            case 'update':
                if not uniq_id:
                    errors['uniq_id'] = 'Veuillez entrer l\'identifiant de la connexion à ChessEvent.'
                elif uniq_id != web_context.admin_chessevent.uniq_id \
                        and uniq_id in web_context.admin_event.chessevents_by_uniq_id:
                    errors['uniq_id'] = \
                        f'Une autre connexion à ChessEvent avec l\'identifiant [{uniq_id}] existe déjà.'
            case 'delete' | 'clone':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        user_id: str = WebContext.form_data_to_str(data, 'user_id')
        password: str = WebContext.form_data_to_str(data, 'password')
        event_id: str = WebContext.form_data_to_str(data, 'event_id')
        match action:
            case 'create' | 'update':
                if not user_id:
                    errors['user_id'] = 'Veuillez entrer l\'identifiant de connexion à ChessEvent.'
                if not password:
                    errors['password'] = 'Veuillez entrer le mot de passe de connexion à ChessEvent.'
                if not event_id:
                    errors['event_id'] = 'Veuillez entrer le nom de l\'évènement ChessEvent.'
            case 'delete' | 'clone':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        return StoredChessEvent(
            id=web_context.admin_chessevent.id if action != 'create' else None,
            uniq_id=uniq_id,
            user_id=user_id,
            password=password,
            event_id=event_id,
            errors=errors,
        )

    def _admin_chessevent_render_edit_modal(
            self,
            action: str,
            web_context: ChessEventAdminWebContext,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        if data is None:
            data: dict[str, str] = {}
            match action:
                case 'update':
                    data['uniq_id'] = WebContext.value_to_form_data(
                        web_context.admin_chessevent.stored_chessevent.uniq_id)
                case 'create':
                    data['uniq_id'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            match action:
                case 'update':
                    data['uniq_id'] = WebContext.value_to_form_data(
                        web_context.admin_chessevent.stored_chessevent.uniq_id)
                    data['event_id'] = WebContext.value_to_form_data(
                        web_context.admin_chessevent.stored_chessevent.event_id)
                    data['user_id'] = WebContext.value_to_form_data(
                        web_context.admin_chessevent.stored_chessevent.user_id)
                    data['password'] = WebContext.value_to_form_data(
                        web_context.admin_chessevent.stored_chessevent.password)
                case 'create':
                    data['uniq_id'] = ''
                    data['event_id'] = ''
                    data['user_id'] = ''
                    data['password'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            stored_chessevent: StoredChessEvent = self._admin_validate_chessevent_update_data(action, web_context, data)
            errors = stored_chessevent.errors
        if errors is None:
            errors = {}
        return HTMXTemplate(
            template_name='admin_chessevent_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'papi_web_config': PapiWebConfig(),
                'admin_auth': web_context.admin_auth,
                'action': action,
                'admin_main_selector': web_context.admin_main_selector,
                'admin_event_selector': web_context.admin_event_selector,
                'admin_event': web_context.admin_event,
                'admin_chessevent': web_context.admin_chessevent,
                'data': data,
                'errors': errors,
            })

    @post(
        path='/admin-chessevent-render-edit-modal',
        name='admin-chessevent-render-edit-modal'
    )
    async def htmx_admin_chessevent_render_edit_modal(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        action: str = WebContext.form_data_to_str(data, 'action')
        web_context: ChessEventAdminWebContext
        match action:
            case 'update' | 'delete':
                web_context = ChessEventAdminWebContext(request, data, True, True)
            case 'create':
                web_context = ChessEventAdminWebContext(request, data, True, False)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        return self._admin_chessevent_render_edit_modal(action, web_context)

    @post(
        path='/admin-chessevent-update',
        name='admin-chessevent-update'
    )
    async def htmx_admin_chessevent_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        action: str = WebContext.form_data_to_str(data, 'action')
        if action == 'close':
            web_context: EventAdminWebContext = EventAdminWebContext(request, data, True, True)
            if web_context.error:
                return web_context.error
            return self._admin_render_index(web_context)
        match action:
            case 'update' | 'delete' | 'clone':
                web_context: ChessEventAdminWebContext = ChessEventAdminWebContext(request, data, True, True)
            case 'create':
                web_context: ChessEventAdminWebContext = ChessEventAdminWebContext(request, data, True, False)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        stored_chessevent: StoredChessEvent = self._admin_validate_chessevent_update_data(action, web_context, data)
        if stored_chessevent.errors:
            return self._admin_chessevent_render_edit_modal(action, web_context, data, stored_chessevent.errors)
        next_chessevent_id: int | None = None
        next_action: str | None = None
        with EventDatabase(web_context.admin_event.uniq_id, write=True) as event_database:
            match action:
                case 'update':
                    stored_chessevent = event_database.update_stored_chessevent(stored_chessevent)
                    Message.success(request, f'La connexion à ChessEvent [{stored_chessevent.uniq_id}] a été modifiée.')
                case 'create':
                    stored_chessevent = event_database.add_stored_chessevent(stored_chessevent)
                    Message.success(request, f'La connexion à ChessEvent [{stored_chessevent.uniq_id}] a été créée.')
                case 'delete':
                    event_database.delete_stored_chessevent(web_context.admin_chessevent.id)
                    Message.success(
                        request, f'La connexion à ChessEvent [{web_context.admin_chessevent.uniq_id}] a été supprimée.')
                case 'clone':
                    stored_chessevent = event_database.clone_stored_chessevent(web_context.admin_chessevent.id)
                    Message.success(
                        request,
                        f'La connexion à ChessEvent [{web_context.admin_chessevent.uniq_id}] a été dupliquée '
                        f'([{stored_chessevent.uniq_id}]).')
                    next_chessevent_id = stored_chessevent.id
                    next_action = 'update'
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        web_context.set_admin_event(event_loader.reload_event(web_context.admin_event.uniq_id))
        if next_chessevent_id:
            web_context.admin_chessevent = web_context.admin_event.chessevents_by_id[next_chessevent_id]
            return self._admin_chessevent_render_edit_modal(next_action, web_context)
        else:
            return self._admin_render_index(web_context)

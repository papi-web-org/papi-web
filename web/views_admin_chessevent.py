from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate

from common.exception import PapiWebException
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.chessevent import NewChessEvent
from data.event import NewEvent
from data.loader import EventLoader
from database.sqlite import EventDatabase
from database.store import StoredChessEvent
from web.messages import Message
from web.views_admin_index import AAdminController

logger: Logger = get_logger()


class AdminChessEventController(AAdminController):
    def _admin_validate_chessevent_update_data(
            self, action: str, admin_event: NewEvent,
            admin_chessevent: NewChessEvent,
            data: dict[str, str] | None = None,
    ) -> StoredChessEvent:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        uniq_id: str = self._form_data_to_str_or_none(data, 'uniq_id')
        match action:
            case 'create':
                if not uniq_id:
                    errors['uniq_id'] = 'Veuillez entrer l\'identifiant de la connexion à ChessEvent.'
                elif uniq_id in admin_event.chessevents_by_uniq_id:
                    errors['uniq_id'] = f'La connexion à ChessEvent [{uniq_id}] existe déjà.'
            case 'update':
                if not uniq_id:
                    errors['uniq_id'] = 'Veuillez entrer l\'identifiant de la connexion à ChessEvent.'
                elif uniq_id != admin_chessevent.uniq_id and uniq_id in admin_event.chessevents_by_uniq_id:
                    errors['uniq_id'] = \
                        f'Une autre connexion à ChessEvent avec l\'identifiant [{uniq_id}] existe déjà.'
            case 'delete' | 'clone':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        user_id: str = self._form_data_to_str_or_none(data, 'user_id')
        password: str = self._form_data_to_str_or_none(data, 'password')
        event_id: str = self._form_data_to_str_or_none(data, 'event_id')
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
            id=admin_chessevent.id if action != 'create' else None,
            uniq_id=uniq_id,
            user_id=user_id,
            password=password,
            event_id=event_id,
            errors=errors,
        )

    def _admin_chessevent_render_edit_modal(
            self,
            action: str,
            admin_event: NewEvent,
            admin_chessevent: NewChessEvent | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        if data is None:
            data: dict[str, str] = {}
            match action:
                case 'update':
                    data['uniq_id'] = self._value_to_form_data(admin_chessevent.stored_chessevent.uniq_id)
                case 'create':
                    data['uniq_id'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            match action:
                case 'update':
                    data['uniq_id'] = self._value_to_form_data(admin_chessevent.stored_chessevent.uniq_id)
                    data['event_id'] = self._value_to_form_data(admin_chessevent.stored_chessevent.event_id)
                    data['user_id'] = self._value_to_form_data(admin_chessevent.stored_chessevent.user_id)
                    data['password'] = self._value_to_form_data(admin_chessevent.stored_chessevent.password)
                case 'create':
                    data['uniq_id'] = ''
                    data['event_id'] = ''
                    data['user_id'] = ''
                    data['password'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            stored_chessevent: StoredChessEvent = self._admin_validate_chessevent_update_data(
                action, admin_event, admin_chessevent, data)
            errors = stored_chessevent.errors
        if errors is None:
            errors = {}
        return HTMXTemplate(
            template_name='admin_chessevent_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'papi_web_config': PapiWebConfig(),
                'action': action,
                'admin_event': admin_event,
                'admin_chessevent': admin_chessevent,
                'data': data,
                'errors': errors,
            })

    @post(
        path='/admin-chessevent-render-edit-modal',
        name='admin-chessevent-render-edit-modal'
    )
    async def htmx_admin_chessevent_render_edit_modal(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        action: str = self._form_data_to_str_or_none(data, 'action')
        admin_event_uniq_id: str = self._form_data_to_str_or_none(data, 'admin_event_uniq_id')
        try:
            admin_event: NewEvent = EventLoader.get(request=request, lazy_load=True).load_event(admin_event_uniq_id)
        except PapiWebException as pwe:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : [{pwe}].')
            return self._render_messages(request)
        admin_chessevent: NewChessEvent | None = None
        match action:
            case 'update' | 'delete':
                admin_chessevent_id: int = self._form_data_to_int_or_none(data, 'admin_chessevent_id')
                try:
                    admin_chessevent = admin_event.chessevents_by_id[admin_chessevent_id]
                except KeyError:
                    Message.error(request, f'La connexion à ChessEvent [{admin_chessevent_id}] est introuvable.')
                    return self._render_messages(request)
            case 'create':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        return self._admin_chessevent_render_edit_modal(action, admin_event, admin_chessevent)

    @post(
        path='/admin-chessevent-update',
        name='admin-chessevent-update'
    )
    async def htmx_admin_chessevent_update(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        action: str = self._form_data_to_str_or_none(data, 'action')
        admin_event_uniq_id: str = self._form_data_to_str_or_none(data, 'admin_event_uniq_id')
        try:
            admin_event: NewEvent = event_loader.load_event(admin_event_uniq_id)
        except PapiWebException as pwe:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : [{pwe}].')
            return self._render_messages(request)
        if action == 'close':
            return self._admin_render_index(
                request, admin_event=admin_event, admin_event_selector='@chessevents')
        admin_chessevent: NewChessEvent | None = None
        match action:
            case 'update' | 'delete' | 'clone':
                admin_chessevent_id: int = self._form_data_to_int_or_none(data, 'admin_chessevent_id')
                try:
                    admin_chessevent = admin_event.chessevents_by_id[admin_chessevent_id]
                except KeyError:
                    Message.error(request, f'La connexion à ChessEvent [{admin_chessevent_id}] est introuvable.')
                    return self._render_messages(request)
            case 'create':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        stored_chessevent: StoredChessEvent = self._admin_validate_chessevent_update_data(
            action, admin_event, admin_chessevent, data)
        if stored_chessevent.errors:
            return self._admin_chessevent_render_edit_modal(
                action, admin_event, admin_chessevent, data, stored_chessevent.errors)
        next_chessevent_id: int | None = None
        next_action: str | None = None
        with EventDatabase(admin_event.uniq_id, write=True) as event_database:
            match action:
                case 'update':
                    stored_chessevent = event_database.update_stored_chessevent(stored_chessevent)
                    Message.success(request, f'La connexion à ChessEvent [{stored_chessevent.uniq_id}] a été modifiée.')
                case 'create':
                    stored_chessevent = event_database.add_stored_chessevent(stored_chessevent)
                    Message.success(request, f'La connexion à ChessEvent [{stored_chessevent.uniq_id}] a été créée.')
                    next_chessevent_id = stored_chessevent.id
                    next_action = 'update'
                case 'delete':
                    event_database.delete_stored_chessevent(admin_chessevent.id)
                    Message.success(request, f'La connexion à ChessEvent [{admin_chessevent.uniq_id}] a été supprimée.')
                case 'clone':
                    stored_chessevent = event_database.clone_stored_chessevent(admin_chessevent.id)
                    Message.success(
                        request,
                        f'La connexion à ChessEvent [{admin_chessevent.uniq_id}] a été dupliquée '
                        f'([{stored_chessevent.uniq_id}]).')
                    next_chessevent_id = stored_chessevent.id
                    next_action = 'update'
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        admin_event = event_loader.reload_event(admin_event.uniq_id)
        if next_chessevent_id:
            admin_chessevent = admin_event.chessevents_by_id[next_chessevent_id]
            return self._admin_chessevent_render_edit_modal(next_action, admin_event, admin_chessevent)
        else:
            return self._admin_render_index(request, admin_event=admin_event, admin_event_selector='@chessevents')

from logging import Logger
from typing import Annotated, Any

from litestar import get, delete, patch, post
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.status_codes import HTTP_200_OK

from common.logger import get_logger
from data.chessevent import ChessEvent
from data.loader import EventLoader
from database.sqlite import EventDatabase
from database.store import StoredChessEvent
from web.controllers.admin.event_admin_controller import EventAdminWebContext, AbstractEventAdminController
from web.controllers.index_controller import WebContext
from web.messages import Message

logger: Logger = get_logger()


class ChessEventAdminWebContext(EventAdminWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ] | None,
            event_uniq_id: str,
            chessevent_id: int | None,
    ):
        super().__init__(request, data=data, event_uniq_id=event_uniq_id, admin_event_tab=None)
        self.admin_chessevent: ChessEvent | None = None
        if chessevent_id:
            try:
                self.admin_chessevent = self.admin_event.chessevents_by_id[chessevent_id]
            except KeyError:
                self._redirect_error(f'La connexion à ChessEvent [{chessevent_id}] n\'existe pas')
                return

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'admin_chessevent': self.admin_chessevent,
        }


class ChessEventAdminController(AbstractEventAdminController):

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

    def _admin_chessevent_modal(
            self, request: HTMXRequest,
            action: str,
            event_uniq_id: str,
            chessevent_id: int | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        web_context: ChessEventAdminWebContext = ChessEventAdminWebContext(
            request, data=None, event_uniq_id=event_uniq_id, chessevent_id=chessevent_id)
        if data is None:
            data: dict[str, str] = {}
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
            template_name='admin_chessevent_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context=web_context.template_context | {
                'action': action,
                'data': data,
                'errors': errors,
            })

    @get(
        path='/admin/chessevent-modal/create/{event_uniq_id:str}',
        name='admin-chessevent-create-modal'
    )
    async def htmx_admin_chessevent_create_modal(
            self, request: HTMXRequest,
            event_uniq_id: str,
    ) -> Template:
        return self._admin_chessevent_modal(
            request, action='create', event_uniq_id=event_uniq_id, chessevent_id=None)

    @get(
        path='/admin-chessevent-modal/{action:str}/{event_uniq_id:str}/{chessevent_id:int}',
        name='admin-chessevent-modal'
    )
    async def htmx_admin_chessevent_modal(
            self, request: HTMXRequest,
            action: str,
            event_uniq_id: str,
            chessevent_id: int | None,
    ) -> Template:
        return self._admin_chessevent_modal(
            request, action=action, event_uniq_id=event_uniq_id, chessevent_id=chessevent_id)

    def _admin_chessevent_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            action: str,
            event_uniq_id: str,
            chessevent_id: int | None,
    ) -> Template:
        match action:
            case 'update' | 'delete' | 'clone' | 'create':
                web_context: ChessEventAdminWebContext = ChessEventAdminWebContext(
                    request, data=data, event_uniq_id=event_uniq_id, chessevent_id=chessevent_id)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        stored_chessevent: StoredChessEvent = self._admin_validate_chessevent_update_data(action, web_context, data)
        if stored_chessevent.errors:
            return self._admin_chessevent_modal(
                request, action=action, event_uniq_id=event_uniq_id, chessevent_id=chessevent_id, data=data,
                errors=stored_chessevent.errors)
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        with EventDatabase(web_context.admin_event.uniq_id, write=True) as event_database:
            match action:
                case 'create':
                    stored_chessevent = event_database.add_stored_chessevent(stored_chessevent)
                    event_database.commit()
                    Message.success(request, f'La connexion à ChessEvent [{stored_chessevent.uniq_id}] a été créée.')
                    event_loader.clear_cache(event_uniq_id)
                    return self._admin_event_render(
                        request, event_uniq_id=event_uniq_id, admin_event_tab='chessevents')
                case 'update':
                    stored_chessevent = event_database.update_stored_chessevent(stored_chessevent)
                    event_database.commit()
                    Message.success(request, f'La connexion à ChessEvent [{stored_chessevent.uniq_id}] a été modifiée.')
                    event_loader.clear_cache(event_uniq_id)
                    return self._admin_event_render(
                        request, event_uniq_id=event_uniq_id, admin_event_tab='chessevents')
                case 'delete':
                    event_database.delete_stored_chessevent(web_context.admin_chessevent.id)
                    event_database.commit()
                    Message.success(
                        request, f'La connexion à ChessEvent [{web_context.admin_chessevent.uniq_id}] a été supprimée.')
                    event_loader.clear_cache(event_uniq_id)
                    return self._admin_event_render(
                        request, event_uniq_id=event_uniq_id, admin_event_tab='chessevents')
                case 'clone':
                    stored_chessevent = event_database.clone_stored_chessevent(web_context.admin_chessevent.id)
                    event_database.commit()
                    Message.success(
                        request,
                        f'La connexion à ChessEvent [{web_context.admin_chessevent.uniq_id}] a été dupliquée '
                        f'([{stored_chessevent.uniq_id}]).')
                    event_loader.clear_cache(event_uniq_id)
                    return self._admin_chessevent_modal(
                        request, action='update', event_uniq_id=event_uniq_id, chessevent_id=stored_chessevent.id)
                case _:
                    raise ValueError(f'action=[{action}]')

    @post(
        path='/admin/chessevent-create/{event_uniq_id:str}',
        name='admin-chessevent-create'
    )
    async def htmx_admin_chessevent_create(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
    ) -> Template:
        return self._admin_chessevent_update(
            request, data=data, action='create', event_uniq_id=event_uniq_id, chessevent_id=None)

    @post(
        path='/admin/chessevent-clone/{event_uniq_id:str}/{chessevent_id:int}',
        name='admin-chessevent-clone'
    )
    async def htmx_admin_chessevent_clone(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            chessevent_id: int | None,
    ) -> Template:
        return self._admin_chessevent_update(
            request, data=data, action='clone', event_uniq_id=event_uniq_id, chessevent_id=chessevent_id)

    @patch(
        path='/admin/chessevent-update/{event_uniq_id:str}/{chessevent_id:int}',
        name='admin-chessevent-update'
    )
    async def htmx_admin_chessevent_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            chessevent_id: int | None,
    ) -> Template:
        return self._admin_chessevent_update(
            request, data=data, action='update', event_uniq_id=event_uniq_id, chessevent_id=chessevent_id)

    @delete(
        path='/admin/chessevent-delete/{event_uniq_id:str}/{chessevent_id:int}',
        name='admin-chessevent-delete',
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_chessevent_delete(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            chessevent_id: int | None,
    ) -> Template:
        return self._admin_chessevent_update(
            request, data=data, action='delete', event_uniq_id=event_uniq_id, chessevent_id=chessevent_id)

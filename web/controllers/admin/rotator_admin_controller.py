from logging import Logger
from typing import Annotated, Any

from litestar import post, get, delete, patch
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, ClientRedirect
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.status_codes import HTTP_200_OK

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.loader import EventLoader
from data.rotator import Rotator
from database.sqlite import EventDatabase
from database.store import StoredRotator
from web.controllers.admin.event_admin_controller import EventAdminWebContext, AbstractEventAdminController
from web.controllers.index_controller import WebContext
from web.messages import Message

logger: Logger = get_logger()


class RotatorAdminWebContext(EventAdminWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ] | None,
            event_uniq_id: str,
            rotator_id: int | None,
    ):
        super().__init__(request, data=data, event_uniq_id=event_uniq_id, admin_event_tab=None)
        self.admin_rotator: Rotator | None = None
        if self.error:
            return
        if rotator_id:
            try:
                self.admin_rotator = self.admin_event.rotators_by_id[rotator_id]
            except KeyError:
                self._redirect_error(f'L\'écran rotatif [{rotator_id}] n\'existe pas')
                return

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'admin_rotator': self.admin_rotator,
        }


class RotatorAdminController(AbstractEventAdminController):

    @staticmethod
    def _admin_validate_rotator_update_data(
            action: str,
            web_context: RotatorAdminWebContext,
            data: dict[str, str] | None = None,
    ) -> StoredRotator:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        field = 'uniq_id'
        uniq_id: str = WebContext.form_data_to_str(data, field)
        match action:
            case 'create' | 'clone':
                if not uniq_id:
                    errors[field] = 'Veuillez entrer l\'identifiant de l\'écran rotatif.'
                elif uniq_id in web_context.admin_event.rotators_by_uniq_id:
                    errors[field] = f'L\'écran rotatif [{uniq_id}] existe déjà.'
            case 'update':
                if not uniq_id:
                    errors[field] = 'Veuillez entrer l\'identifiant de l\'écran rotatif.'
                elif uniq_id != web_context.admin_rotator.uniq_id \
                        and uniq_id in web_context.admin_event.rotators_by_uniq_id:
                    errors[field] = \
                        f'Un autre écran rotatif avec l\'identifiant [{uniq_id}] existe déjà.'
            case 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        public: bool | None = None
        delay: int | None = None
        show_menus: bool | None = None
        screen_ids: list[int] | None = None
        family_ids: list[int] | None = None
        match action:
            case 'create' | 'update' | 'clone':
                public: bool = WebContext.form_data_to_bool(data, 'public')
                try:
                    delay = WebContext.form_data_to_int(data, 'delay', minimum=1)
                except ValueError:
                    errors['delay'] = 'Un entier positif est attendu.'
                show_menus = WebContext.form_data_to_bool(data, 'show_menus')
                screen_ids = []
                for screen_id in web_context.admin_event.basic_screens_by_id:
                    field = f'screen_{screen_id}'
                    if WebContext.form_data_to_bool(data, field):
                        screen_ids.append(screen_id)
                family_ids = []
                for family_id in web_context.admin_event.families_by_id:
                    field = f'family_{family_id}'
                    if WebContext.form_data_to_bool(data, field):
                        family_ids.append(family_id)
            case 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        return StoredRotator(
            id=web_context.admin_rotator.id if action != 'create' else None,
            uniq_id=uniq_id,
            public=public,
            delay=delay,
            show_menus=show_menus,
            screen_ids=screen_ids,
            family_ids=family_ids,
            errors=errors,
        )

    @staticmethod
    def _get_show_menus_options() -> dict[str, str]:
        options: dict[str, str] = {
            '': '-',
            'off': 'Pas d\'affichage des menus des écrans',
            'on': 'Affichage des menus des écrans',
        }
        options[''] = f'Par défaut ({options["on" if PapiWebConfig.default_rotator_show_menus else "off"]})'
        return options

    def _admin_rotator_modal(
            self, request: HTMXRequest,
            action: str,
            event_uniq_id: str,
            rotator_id: int | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template | ClientRedirect:
        web_context: RotatorAdminWebContext = RotatorAdminWebContext(
            request, data=None, event_uniq_id=event_uniq_id, rotator_id=rotator_id)
        if web_context.error:
            return web_context.error
        if data is None:
            data = {}
            data: dict[str, str]
            match action:
                case 'update' | 'clone':
                    data['uniq_id'] = WebContext.value_to_form_data(web_context.admin_rotator.stored_rotator.uniq_id)
                    data['public'] = WebContext.value_to_form_data(web_context.admin_rotator.stored_rotator.public)
                    data['delay'] = WebContext.value_to_form_data(web_context.admin_rotator.stored_rotator.delay)
                    data['show_menus'] = WebContext.value_to_form_data(
                        web_context.admin_rotator.stored_rotator.show_menus)
                    for screen_id in web_context.admin_event.basic_screens_by_id:
                        data[f'screen_{screen_id}'] = WebContext.value_to_form_data(
                            screen_id in web_context.admin_rotator.stored_rotator.screen_ids)
                    for family_id in web_context.admin_event.families_by_id:
                        data[f'family_{family_id}'] = WebContext.value_to_form_data(
                            family_id in web_context.admin_rotator.stored_rotator.family_ids)
                case 'create':
                    data['type'] = ''
                    data['public'] = WebContext.value_to_form_data(True)
                    data['uniq_id'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            stored_rotator: StoredRotator = self._admin_validate_rotator_update_data(action, web_context, data)
            errors = stored_rotator.errors
        if errors is None:
            errors = {}
        return HTMXTemplate(
            template_name='admin_rotator_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context=web_context.template_context | {
                'action': action,
                'show_menus_options': self._get_show_menus_options(),
                'data': data,
                'errors': errors,
            })

    @get(
        path='/admin/rotator-modal/create/{event_uniq_id:str}',
        name='admin-rotator-create-modal'
    )
    async def htmx_admin_rotator_create_modal(
            self, request: HTMXRequest,
            event_uniq_id: str,
    ) -> Template | ClientRedirect:
        return self._admin_rotator_modal(
            request, action='create', event_uniq_id=event_uniq_id, rotator_id=None)

    @get(
        path='/admin/rotator-modal/{action:str}/{event_uniq_id:str}/{rotator_id:int}',
        name='admin-rotator-modal'
    )
    async def htmx_admin_rotator_modal(
            self, request: HTMXRequest,
            action: str,
            event_uniq_id: str,
            rotator_id: int | None,
    ) -> Template | ClientRedirect:
        return self._admin_rotator_modal(
            request, action=action, event_uniq_id=event_uniq_id, rotator_id=rotator_id)

    def _admin_rotator_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            action: str,
            event_uniq_id: str,
            rotator_id: int | None,
    ) -> Template | ClientRedirect:
        match action:
            case 'update' | 'delete' | 'clone' | 'create':
                web_context: RotatorAdminWebContext = RotatorAdminWebContext(
                    request, data=data, event_uniq_id=event_uniq_id, rotator_id=rotator_id)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        stored_rotator: StoredRotator = self._admin_validate_rotator_update_data(action, web_context, data)
        if stored_rotator.errors:
            return self._admin_rotator_modal(
                request, action=action, event_uniq_id=event_uniq_id, rotator_id=rotator_id, data=data,
                errors=stored_rotator.errors)
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=False)
        with EventDatabase(web_context.admin_event.uniq_id, write=True) as event_database:
            match action:
                case 'create':
                    stored_rotator = event_database.add_stored_rotator(stored_rotator)
                    event_database.commit()
                    Message.success(request, f'L\'écran rotatif [{stored_rotator.uniq_id}] a été créé.')
                    event_loader.clear_cache(event_uniq_id)
                    return self._admin_event_render(request, event_uniq_id=event_uniq_id, admin_event_tab='rotators')
                case 'update':
                    stored_rotator = event_database.update_stored_rotator(stored_rotator)
                    event_database.commit()
                    Message.success(request, f'L\'écran rotatif [{stored_rotator.uniq_id}] a été modifié.')
                    event_loader.clear_cache(event_uniq_id)
                    return self._admin_event_render(request, event_uniq_id=event_uniq_id, admin_event_tab='rotators')
                case 'delete':
                    event_database.delete_stored_rotator(web_context.admin_rotator.id)
                    event_database.commit()
                    Message.success(
                        request, f'L\'écran rotatif [{web_context.admin_rotator.uniq_id}] a été supprimé.')
                    event_loader.clear_cache(event_uniq_id)
                    return self._admin_event_render(request, event_uniq_id=event_uniq_id, admin_event_tab='rotators')
                case 'clone':
                    stored_rotator = event_database.clone_stored_rotator(web_context.admin_rotator.id)
                    event_database.commit()
                    Message.success(
                        request,
                        f'L\'écran rotatif [{web_context.admin_rotator.uniq_id}] a été dupliqué '
                        f'([{stored_rotator.uniq_id}]).')
                    event_loader.clear_cache(event_uniq_id)
                    return self._admin_event_render(request, event_uniq_id=event_uniq_id, admin_event_tab='rotators')
                case _:
                    raise ValueError(f'action=[{action}]')

    @post(
        path='/admin/rotator-create/{event_uniq_id:str}',
        name='admin-rotator-create'
    )
    async def htmx_admin_rotator_create(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
    ) -> Template | ClientRedirect:
        return self._admin_rotator_update(
            request, data=data, action='create', event_uniq_id=event_uniq_id, rotator_id=None)

    @post(
        path='/admin/rotator-clone/{event_uniq_id:str}/{rotator_id:int}',
        name='admin-rotator-clone',
    )
    async def htmx_admin_rotator_clone(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            rotator_id: int | None,
    ) -> Template | ClientRedirect:
        return self._admin_rotator_update(
            request, data=data, action='clone', event_uniq_id=event_uniq_id, rotator_id=rotator_id)

    @patch(
        path='/admin/rotator-update/{event_uniq_id:str}/{rotator_id:int}',
        name='admin-rotator-update',
    )
    async def htmx_admin_rotator_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            rotator_id: int | None,
    ) -> Template | ClientRedirect:
        return self._admin_rotator_update(
            request, data=data, action='update', event_uniq_id=event_uniq_id, rotator_id=rotator_id)

    @delete(
        path='/admin/rotator-delete/{event_uniq_id:str}/{rotator_id:int}',
        name='admin-rotator-delete',
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_rotator_delete(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            rotator_id: int | None,
    ) -> Template | ClientRedirect:
        return self._admin_rotator_update(
            request, data=data, action='delete', event_uniq_id=event_uniq_id, rotator_id=rotator_id)

from logging import Logger
from typing import Annotated, Any

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.loader import EventLoader
from data.rotator import Rotator
from database.sqlite import EventDatabase
from database.store import StoredRotator
from web.messages import Message
from web.views import WebContext
from web.views_admin import AAdminController
from web.views_admin_event import EventAdminWebContext

logger: Logger = get_logger()


class RotatorAdminWebContext(EventAdminWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
            rotator_needed: bool,
    ):
        super().__init__(request, data, lazy_load, True)
        self.admin_rotator: Rotator | None = None
        field: str = 'admin_rotator_id'
        if field in self.data:
            try:
                admin_rotator_id: int | None = self._form_data_to_int(field, minimum=1)
            except ValueError as ve:
                self._redirect_error(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
                return
            try:
                self.admin_rotator = self.admin_event.rotators_by_id[admin_rotator_id]
            except KeyError:
                self._redirect_error(f'L\'écran rotatif [{admin_rotator_id}] n\'existe pas')
                return
        if rotator_needed and not self.admin_rotator:
            self._redirect_error(f'L\'écran rotatif n\'est pas spécifié')
            return

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'admin_rotator': self.admin_rotator,
        }


class AdminRotatorController(AAdminController):

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
            case 'create':
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
            case 'delete' | 'clone':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        public: bool | None = None
        delay: int | None = None
        show_menus: bool | None = None
        screen_ids: list[int] | None = None
        family_ids: list[int] | None = None
        match action:
            case 'create' | 'update':
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
            case 'delete' | 'clone':
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

    def _admin_rotator_render_edit_modal(
            self,
            action: str,
            web_context: RotatorAdminWebContext,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        if data is None:
            data = {}
            data: dict[str, str]
            match action:
                case 'update':
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
            template_name='admin_rotator_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context=web_context.template_context | {
                'action': action,
                'show_menus_options': self._get_show_menus_options(),
                'data': data,
                'errors': errors,
            })

    @post(
        path='/admin-rotator-render-edit-modal',
        name='admin-rotator-render-edit-modal'
    )
    async def htmx_admin_rotator_render_edit_modal(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        action: str = WebContext.form_data_to_str(data, 'action')
        web_context: RotatorAdminWebContext
        match action:
            case 'update' | 'delete':
                web_context = RotatorAdminWebContext(request, data, True, True)
            case 'create':
                web_context = RotatorAdminWebContext(request, data, True, False)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        return self._admin_rotator_render_edit_modal(action, web_context)

    @post(
        path='/admin-rotator-update',
        name='admin-rotator-update'
    )
    async def htmx_admin_rotator_update(
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
                web_context: RotatorAdminWebContext = RotatorAdminWebContext(request, data, True, True)
            case 'create':
                web_context: RotatorAdminWebContext = RotatorAdminWebContext(request, data, True, False)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        stored_rotator: StoredRotator = self._admin_validate_rotator_update_data(action, web_context, data)
        if stored_rotator.errors:
            return self._admin_rotator_render_edit_modal(action, web_context, data, stored_rotator.errors)
        next_rotator_id: int | None = None
        next_action: str | None = None
        with EventDatabase(web_context.admin_event.uniq_id, write=True) as event_database:
            match action:
                case 'update':
                    stored_rotator = event_database.update_stored_rotator(stored_rotator)
                    Message.success(request, f'L\'écran rotatif [{stored_rotator.uniq_id}] a été modifié.')
                case 'create':
                    stored_rotator = event_database.add_stored_rotator(stored_rotator)
                    Message.success(request, f'L\'écran rotatif [{stored_rotator.uniq_id}] a été créé.')
                    next_rotator_id = stored_rotator.id
                    next_action = 'update'
                case 'delete':
                    event_database.delete_stored_rotator(web_context.admin_rotator.id)
                    Message.success(
                        request, f'L\'écran rotatif [{web_context.admin_rotator.uniq_id}] a été supprimé.')
                case 'clone':
                    stored_rotator = event_database.clone_stored_rotator(web_context.admin_rotator.id)
                    Message.success(
                        request,
                        f'L\'écran rotatif [{web_context.admin_rotator.uniq_id}] a été dupliqué '
                        f'([{stored_rotator.uniq_id}]).')
                    next_rotator_id = stored_rotator.id
                    next_action = 'update'
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        web_context.set_admin_event(event_loader.reload_event(web_context.admin_event.uniq_id))
        if next_rotator_id:
            web_context.admin_rotator = web_context.admin_event.rotators_by_id[next_rotator_id]
            return self._admin_rotator_render_edit_modal(next_action, web_context)
        else:
            return self._admin_render_index(web_context)

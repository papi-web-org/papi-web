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
from data.event import NewEvent
from data.loader import EventLoader
from data.rotator import NewRotator
from database.sqlite import EventDatabase
from database.store import StoredRotator
from web.messages import Message
from web.views_admin_index import AAdminController

logger: Logger = get_logger()


class AdminRotatorController(AAdminController):
    def _admin_validate_rotator_update_data(
            self, action: str,
            admin_event: NewEvent,
            admin_rotator: NewRotator,
            data: dict[str, str] | None = None,
    ) -> StoredRotator:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        field = 'uniq_id'
        uniq_id: str = self._form_data_to_str_or_none(data, field)
        match action:
            case 'create':
                if not uniq_id:
                    errors[field] = 'Veuillez entrer l\'identifiant de l\'écran rotatif.'
                elif uniq_id in admin_event.rotators_by_uniq_id:
                    errors[field] = f'L\'écran rotatif [{uniq_id}] existe déjà.'
            case 'update':
                if not uniq_id:
                    errors[field] = 'Veuillez entrer l\'identifiant de l\'écran rotatif.'
                elif uniq_id != admin_rotator.uniq_id and uniq_id in admin_event.rotators_by_uniq_id:
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
                public: bool = self._form_data_to_bool_or_none(data, 'public')
                try:
                    delay = self._form_data_to_int_or_none(data, 'delay', minimum=1)
                except ValueError:
                    errors['delay'] = 'Un entier positif est attendu.'
                show_menus = self._form_data_to_bool_or_none(data, 'show_menus')
                screen_ids = []
                for screen_id in admin_event.basic_screens_by_id:
                    field = f'screen_{screen_id}'
                    if self._form_data_to_bool_or_none(data, field):
                        screen_ids.append(screen_id)
                family_ids = []
                for family_id in admin_event.families_by_id:
                    field = f'family_{family_id}'
                    if self._form_data_to_bool_or_none(data, field):
                        family_ids.append(family_id)
            case 'delete' | 'clone':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        return StoredRotator(
            id=admin_rotator.id if action != 'create' else None,
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
            '0': 'Pas d\'affichage des menus des écrans',
            '1': 'Affichage des menus des écrans',
        }
        options[''] = f'Par défaut ({options["1" if PapiWebConfig().default_rotator_show_menus else "0"]})'
        return options

    def _admin_rotator_render_edit_modal(
            self,
            action: str,
            admin_event: NewEvent,
            admin_rotator: NewRotator | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        if data is None:
            data = {}
            if admin_rotator:
                data: dict[str, str]
                match action:
                    case 'update':
                        data = {
                            'uniq_id': self._value_to_form_data(admin_rotator.stored_rotator.uniq_id),
                            'public': self._value_to_form_data(admin_rotator.stored_rotator.public),
                            'delay': self._value_to_form_data(admin_rotator.stored_rotator.delay),
                            'show_menus': self._value_to_form_data(admin_rotator.stored_rotator.show_menus),
                        }
                        for screen_id in admin_event.basic_screens_by_id:
                            data[f'screen_{screen_id}'] = self._value_to_form_data(
                                screen_id in admin_rotator.stored_rotator.screen_ids)
                        for family_id in admin_event.families_by_id:
                            data[f'family_{family_id}'] = self._value_to_form_data(
                                family_id in admin_rotator.stored_rotator.family_ids)
                    case 'create':
                        data = {
                            'type': '',
                            'public': self._value_to_form_data(True),
                            'uniq_id': '',
                        }
                    case 'delete':
                        pass
                    case _:
                        raise ValueError(f'action=[{action}]')
            stored_rotator: StoredRotator = self._admin_validate_rotator_update_data(
                action, admin_event, admin_rotator, data)
            errors = stored_rotator.errors
        if errors is None:
            errors = {}
        return HTMXTemplate(
            template_name='admin_rotator_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'papi_web_config': PapiWebConfig(),
                'action': action,
                'admin_event': admin_event,
                'admin_rotator': admin_rotator,
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
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        event_loader: EventLoader = EventLoader()
        action: str = self._form_data_to_str_or_none(data, 'action')
        admin_event_uniq_id: str = self._form_data_to_str_or_none(data, 'admin_event_uniq_id')
        try:
            admin_event: NewEvent = event_loader.load_event(admin_event_uniq_id)
        except PapiWebException as pwe:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : [{pwe}].')
            return self._render_messages(request)
        admin_rotator: NewRotator | None = None
        match action:
            case 'update' | 'delete':
                admin_rotator_id: int = self._form_data_to_int_or_none(data, 'admin_rotator_id')
                try:
                    admin_rotator = admin_event.rotators_by_id[admin_rotator_id]
                except KeyError:
                    Message.error(request, f'L\'écran rotatif [{admin_rotator_id}] est introuvable.')
                    return self._render_messages(request)
            case 'create':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        return self._admin_rotator_render_edit_modal(action, admin_event, admin_rotator)

    @post(
        path='/admin-rotator-update',
        name='admin-rotator-update'
    )
    async def htmx_admin_rotator_update(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        event_loader: EventLoader = EventLoader()
        action: str = self._form_data_to_str_or_none(data, 'action')
        admin_event_uniq_id: str = self._form_data_to_str_or_none(data, 'admin_event_uniq_id')
        try:
            admin_event: NewEvent = event_loader.load_event(admin_event_uniq_id)
        except PapiWebException as pwe:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : [{pwe}].')
            return self._render_messages(request)
        if action == 'close':
            return self._admin_render_index(
                request, event_loader, admin_event=admin_event, admin_event_selector='@rotators')
        admin_rotator: NewRotator | None = None
        match action:
            case 'update' | 'delete' | 'clone':
                admin_rotator_id: int = self._form_data_to_int_or_none(data, 'admin_rotator_id')
                try:
                    admin_rotator = admin_event.rotators_by_id[admin_rotator_id]
                except KeyError:
                    Message.error(request, f'L\'écran rotatif [{admin_rotator_id}] est introuvable.')
                    return self._render_messages(request)
            case 'create':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        stored_rotator: StoredRotator = self._admin_validate_rotator_update_data(
            action, admin_event, admin_rotator, data)
        if stored_rotator.errors:
            return self._admin_rotator_render_edit_modal(
                action, admin_event, admin_rotator, data, stored_rotator.errors)
        next_rotator_id: int | None = None
        next_action: str | None = None
        with EventDatabase(admin_event.uniq_id, write=True) as event_database:
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
                    event_database.delete_stored_rotator(admin_rotator.id)
                    Message.success(request, f'L\'écran rotatif [{admin_rotator.uniq_id}] a été supprimé.')
                case 'clone':
                    stored_rotator = event_database.clone_stored_rotator(admin_rotator.id)
                    Message.success(
                        request,
                        f'L\'écran rotatif [{admin_rotator.uniq_id}] a été dupliqué ([{stored_rotator.uniq_id}]).')
                    next_rotator_id = stored_rotator.id
                    next_action = 'update'
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        admin_event = event_loader.load_event(admin_event.uniq_id, reload=True)
        if next_rotator_id:
            admin_rotator = admin_event.rotators_by_id[next_rotator_id]
            return self._admin_rotator_render_edit_modal(next_action, admin_event, admin_rotator)
        else:
            return self._admin_render_index(
                request, event_loader, admin_event=admin_event, admin_event_selector='@rotators')

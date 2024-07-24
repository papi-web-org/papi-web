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
from database.sqlite import EventDatabase
from database.store import StoredEvent
from web.messages import Message
from web.views_admin import AAdminController

logger: Logger = get_logger()


class AdminEventController(AAdminController):

    def _admin_validate_event_update_data(
            self, event_loader: EventLoader, action: str, admin_event: NewEvent | None,
            data: dict[str, str] | None = None,
    ) -> StoredEvent:
        if data is None:
            data = {}
        errors: dict[str, str] = {}
        uniq_id: str | None = self.form_data_to_str_or_none(data, 'uniq_id')
        if action == 'delete':
            if not uniq_id:
                errors['uniq_id'] = 'Veuillez entrer l\'identifiant de l\'évènement.'
            elif uniq_id != admin_event.uniq_id:
                errors['uniq_id'] = f'L\'identifiant entré n\'est pas valide.'
        else:
            if not uniq_id:
                errors['uniq_id'] = 'Veuillez entrer l\'identifiant de l\'évènement.'
            elif uniq_id.find('/') != -1:
                errors['uniq_id'] = "le caractère « / » n\'est pas autorisé"
            else:
                match action:
                    case 'create' | 'clone':
                        if uniq_id in event_loader.event_ids:
                            errors['uniq_id'] = f'L\'évènement [{uniq_id}] existe déjà.'
                    case 'update':
                        if uniq_id != admin_event.uniq_id and uniq_id in event_loader.event_ids:
                            errors['uniq_id'] = f'L\'évènement [{uniq_id}] existe déjà.'
                    case _:
                        raise ValueError(f'action=[{action}]')
        name: str | None = self.form_data_to_str_or_none(data, 'name')
        match action:
            case 'create' | 'clone' | 'update':
                if not name:
                    errors['name'] = 'Veuillez entrer le nom de l\'évènement.'
            case 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        path: str | None = self.form_data_to_str_or_none(data, 'path')
        css: str | None = self.form_data_to_str_or_none(data, 'css')
        update_password: str | None = self.form_data_to_str_or_none(data, 'update_password')
        record_illegal_moves: int | None = None
        allow_results_deletion: bool | None = None
        match action:
            case 'update':
                try:
                    record_illegal_moves = self.form_data_to_int_or_none(data, 'record_illegal_moves')
                    assert record_illegal_moves is None or 0 <= record_illegal_moves <= 3
                except (ValueError, AssertionError):
                    errors['record_illegal_moves'] = 'La valeur entrée n\'est pas valide.'
                try:
                    allow_results_deletion = self.form_data_to_bool_or_none(data, 'allow_results_deletion')
                except ValueError:
                    errors['allow_results_deletion'] = 'La valeur entrée n\'est pas valide.'
            case 'create' | 'clone' | 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        return StoredEvent(
            uniq_id=uniq_id,
            name=name,
            path=path,
            css=css,
            update_password=update_password,
            record_illegal_moves=record_illegal_moves,
            allow_results_deletion=allow_results_deletion,
            errors=errors,
        )

    @staticmethod
    def _admin_event_render_edit_modal(
            action: str,
            admin_event: NewEvent | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        record_illegal_moves_options: dict[str, str] = {
            '': '',
            '0': 'Aucun enregistrement des coups illégaux',
            '1': 'Maximum 1 coup illégal',
            '2': 'Maximum 2 coups illégaux',
            '3': 'Maximum 3 coups illégaux',
        }
        record_illegal_moves_options[''] = \
            f'Par défaut ({record_illegal_moves_options[str(PapiWebConfig().default_record_illegal_moves_number)]})'
        allow_results_deletion_options: dict[str, str] = {
            '': '',
            '0': 'Non autorisée',
            '1': 'Autorisée',
        }
        allow_results_deletion_options[''] = \
            f'Par défaut ({allow_results_deletion_options[str(int(PapiWebConfig().default_allow_results_deletion))]})'
        return HTMXTemplate(
            template_name='admin_event_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'papi_web_config': PapiWebConfig(),
                'action': action,
                'admin_event': admin_event,
                'data': data,
                'errors': errors,
                'record_illegal_moves_options': record_illegal_moves_options,
                'allow_results_deletion_options': allow_results_deletion_options,
            })

    @post(
        path='/admin-event-render-edit-modal',
        name='admin-event-render-edit-modal'
    )
    async def htmx_admin_event_render_edit_modal(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        event_loader: EventLoader = EventLoader()
        action: str = self.form_data_to_str_or_none(data, 'action')
        admin_event: NewEvent | None = None
        match action:
            case 'create':
                pass
            case 'clone' | 'update' | 'delete':
                admin_event_uniq_id: str = self.form_data_to_str_or_none(data, 'admin_event_uniq_id')
                try:
                    admin_event: NewEvent = event_loader.load_event(admin_event_uniq_id)
                except PapiWebException as pwe:
                    Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : {pwe}.')
                    return self._render_messages(request)
            case _:
                raise ValueError(f'action=[{action}]')
        data: dict[str, str]
        match action:
            case 'create' | 'delete':
                data = {}
            case 'clone' | 'update':
                data = {
                    'uniq_id':
                        '' if action == 'clone' else self.value_to_form_data(admin_event.stored_event.uniq_id),
                    'name': self.value_to_form_data(admin_event.stored_event.name),
                    'css': self.value_to_form_data(admin_event.stored_event.css),
                    'path': self.value_to_form_data(admin_event.stored_event.path),
                    'update_password': self.value_to_form_data(admin_event.stored_event.update_password),
                    'record_illegal_moves': self.value_to_form_data(admin_event.stored_event.record_illegal_moves),
                    'allow_results_deletion':
                        self.value_to_form_data(admin_event.stored_event.allow_results_deletion),
                }
            case _:
                raise ValueError(f'action=[{action}]')
        stored_event: StoredEvent = self._admin_validate_event_update_data(event_loader, action, admin_event, data)
        return self._admin_event_render_edit_modal(action, admin_event, data, stored_event.errors)

    @post(
        path='/admin-event-update',
        name='admin-event-update'
    )
    async def htmx_admin_event_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        event_loader: EventLoader = EventLoader()
        action: str = self.form_data_to_str_or_none(data, 'action')
        admin_event: NewEvent | None = None
        match action:
            case 'create':
                pass
            case 'clone' | 'update' | 'delete':
                admin_event_uniq_id: str = self.form_data_to_str_or_none(data, 'admin_event_uniq_id')
                try:
                    admin_event = event_loader.load_event(admin_event_uniq_id)
                except PapiWebException as pwe:
                    Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : {pwe}')
                    return self._render_messages(request)
            case _:
                raise ValueError(f'action=[{action}]')
        stored_event: StoredEvent = self._admin_validate_event_update_data(event_loader, action, admin_event, data)
        if stored_event.errors:
            return self._admin_event_render_edit_modal(action, admin_event, data, stored_event.errors)
        uniq_id: str = stored_event.uniq_id
        match action:
            case 'create':
                EventDatabase(uniq_id).create()
                with EventDatabase(uniq_id, write=True) as event_database:
                    event_database.update_stored_event(stored_event)
                    event_database.commit()
                event_loader.clear_cache()
                Message.success(request, f'L\'évènement [{uniq_id}] a été créé.')
                admin_event = event_loader.load_event(uniq_id)
                return self._admin_render_index(request, event_loader, admin_event=admin_event, admin_event_selector='')
            case 'update':
                rename: bool = uniq_id != admin_event.uniq_id
                if rename:
                    try:
                        EventDatabase(admin_event.uniq_id).rename(new_uniq_id=uniq_id)
                    except PermissionError as pe:
                        Message.error(request, f'Le renommage de la base de données a échoué : {pe}')
                        return self._render_messages(request)
                with EventDatabase(uniq_id, write=True) as event_database:
                    event_database.update_stored_event(stored_event)
                    event_database.commit()
                event_loader.clear_cache(admin_event.uniq_id)
                if rename:
                    Message.success(
                        request, f'L\'évènement [{admin_event.uniq_id}] a été renommé ([{uniq_id}) et modifié.')
                else:
                    Message.success(request, f'L\'évènement [{uniq_id}] a été modifié.')
                admin_event = event_loader.load_event(uniq_id)
                return self._admin_render_index(request, event_loader, admin_event=admin_event, admin_event_selector='')
            case 'clone':
                EventDatabase(admin_event.uniq_id).clone(new_uniq_id=uniq_id)
                with EventDatabase(uniq_id, write=True) as event_database:
                    event_database.update_stored_event(stored_event)
                    event_database.commit()
                event_loader.clear_cache()
                Message.success(request, f'L\'évènement [{admin_event.uniq_id}] a été dupliqué ([{uniq_id}]).')
                admin_event = event_loader.load_event(uniq_id)
                return self._admin_render_index(request, event_loader, admin_event=admin_event, admin_event_selector='')
            case 'delete':
                arch = EventDatabase(admin_event.uniq_id).delete()
                event_loader.clear_cache(admin_event.uniq_id)
                Message.success(
                    request,
                    f'L\'évènement [{admin_event.uniq_id}] a été supprimé, la base de données a été archivée ({arch}).')
                return self._admin_render_index(request, event_loader, admin_main_selector='@events')
            case _:
                raise ValueError(f'action=[{action}]')

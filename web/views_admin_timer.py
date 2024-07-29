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
from data.timer import NewTimer
from data.event import NewEvent
from data.loader import EventLoader
from database.sqlite import EventDatabase
from database.store import StoredTimer
from web.messages import Message
from web.views_admin import AAdminController

logger: Logger = get_logger()


class AdminTimerController(AAdminController):

    def _admin_validate_timer_update_data(
            self, action: str, admin_event: NewEvent,
            admin_timer: NewTimer,
            data: dict[str, str] | None = None,
    ) -> StoredTimer:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        uniq_id: str = self.form_data_to_str_or_none(data, 'uniq_id')
        if action == 'delete':
            pass
        else:
            if not uniq_id:
                errors['uniq_id'] = 'Veuillez entrer l\'identifiant du chronomètre.'
            else:
                match action:
                    case 'create' | 'clone':
                        if uniq_id in admin_event.timer_uniq_ids:
                            errors['uniq_id'] = f'Le chronomètre [{uniq_id}] existe déjà.'
                    case 'update':
                        if uniq_id != admin_timer.uniq_id and uniq_id in admin_event.timer_uniq_ids:
                            errors['uniq_id'] = f'Le chronomètre [{uniq_id}] existe déjà.'
                    case _:
                        raise ValueError(f'action=[{action}]')
        colors: dict[int, str | None] = {i: None for i in range(1, 4)}
        color_checkboxes: dict[int, bool | None] = {i: None for i in range(1, 4)}
        delays: dict[int, int | None] = {i: None for i in range(1, 4)}
        match action:
            case 'update':
                for i in range(1, 4):
                    field: str = f'color_{i}'
                    color_checkboxes[i] = self.form_data_to_bool_or_none(data, field+'_checkbox')
                    if not color_checkboxes[i]:
                        try:
                            colors[i] = self.form_data_to_rgb_or_none(data, field)
                        except ValueError:
                            errors[field] = f'La couleur n\'est pas valide [{data[field]}] (attendu [#HHHHHH]).'
                    field: str = f'delay_{i}'
                    try:
                        delays[i] = self.form_data_to_int_or_none(data, field, minimum=1)
                    except ValueError:
                        errors[field] = f'Le délai [{data[field]}] n\'est pas valide (attendu un entier positif).'
            case 'delete' | 'create' | 'clone':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        return StoredTimer(
            id=admin_timer.id if action != 'create' else None,
            uniq_id=uniq_id,
            colors=colors,
            delays=delays,
            errors=errors,
        )

    @classmethod
    def _admin_timer_render_edit_modal(
            cls, action: str,
            admin_event: NewEvent,
            admin_timer: NewTimer | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        return HTMXTemplate(
            template_name='admin_timer_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'papi_web_config': PapiWebConfig(),
                'action': action,
                'admin_event': admin_event,
                'admin_timer': admin_timer,
                'data': data,
                'timer_color_texts': cls._get_timer_color_texts(admin_event.timer_delays),
                'errors': errors,
            })

    @post(
        path='/admin-timer-render-edit-modal',
        name='admin-timer-render-edit-modal'
    )
    async def htmx_admin_timer_render_edit_modal(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        event_loader: EventLoader = EventLoader()
        action: str = self.form_data_to_str_or_none(data, 'action')
        admin_event_uniq_id: str = self.form_data_to_str_or_none(data, 'admin_event_uniq_id')
        try:
            admin_event: NewEvent = event_loader.load_event(admin_event_uniq_id)
        except PapiWebException as pwe:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : [{pwe}].')
            return self._render_messages(request)
        admin_timer: NewTimer | None = None
        match action:
            case 'update' | 'delete' | 'clone':
                admin_timer_id: int = self.form_data_to_int_or_none(data, 'admin_timer_id')
                try:
                    admin_timer = admin_event.timers_by_id[admin_timer_id]
                except KeyError:
                    Message.error(request, f'Le chronomètre [{admin_timer_id}] est introuvable.')
                    return self._render_messages(request)
            case 'create':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        data: dict[str, str] = {}
        match action:
            case 'update':
                data['uniq_id'] = self.value_to_form_data(admin_timer.stored_timer.uniq_id)
            case 'create' | 'clone':
                data['uniq_id'] = ''
            case 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        match action:
            case 'update' | 'clone':
                for i in range(1, 4):
                    data[f'color_{i}'] = self.value_to_form_data(admin_timer.colors[i])
                    data[f'color_{i}_checkbox'] = self.value_to_form_data(admin_timer.stored_timer.colors[i] is None)
                    data[f'delay_{i}'] = self.value_to_form_data(admin_timer.stored_timer.delays[i])
            case 'create':
                for i in range(1, 4):
                    data[f'color_{i}'] = ''
                    data[f'color_{i}_checkbox'] = ''
                    data[f'delay_{i}'] = ''
            case 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        stored_timer: StoredTimer = self._admin_validate_timer_update_data(
            action, admin_event, admin_timer, data)
        return self._admin_timer_render_edit_modal(
            action, admin_event, admin_timer, data, stored_timer.errors)

    @post(
        path='/admin-timer-update',
        name='admin-timer-update'
    )
    async def htmx_admin_timer_update(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        event_loader: EventLoader = EventLoader()
        action: str = self.form_data_to_str_or_none(data, 'action')
        admin_event_uniq_id: str = self.form_data_to_str_or_none(data, 'admin_event_uniq_id')
        try:
            admin_event: NewEvent = event_loader.load_event(admin_event_uniq_id)
        except PapiWebException as pwe:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : [{pwe}].')
            return self._render_messages(request)
        admin_timer: NewTimer | None = None
        match action:
            case 'update' | 'delete' | 'clone':
                admin_timer_id: int = self.form_data_to_int_or_none(data, 'admin_timer_id')
                try:
                    admin_timer = admin_event.timers_by_id[admin_timer_id]
                except KeyError:
                    Message.error(request, f'Le chronomètre [{admin_timer_id}] est introuvable.')
                    return self._render_messages(request)
            case 'create':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        stored_timer: StoredTimer = self._admin_validate_timer_update_data(
            action, admin_event, admin_timer, data)
        if stored_timer.errors:
            return self._admin_timer_render_edit_modal(
                action, admin_event, admin_timer, data, stored_timer.errors)
        with (EventDatabase(admin_event.uniq_id, write=True) as event_database):
            match action:
                case 'update':
                    stored_timer = event_database.update_stored_timer(stored_timer)
                    Message.success(request, f'Le chronomètre [{stored_timer.uniq_id}] a été modifié.')
                case 'create':
                    stored_timer = event_database.add_stored_timer(stored_timer)
                    Message.success(request, f'Le chronomètre [{stored_timer.uniq_id}] a été créé.')
                case 'delete':
                    event_database.delete_stored_timer(admin_timer.id)
                    Message.success(request, f'Le chronomètre [{admin_timer.uniq_id}] a été supprimé.')
                case 'clone':
                    stored_timer = event_database.clone_stored_timer(
                        admin_timer.id, stored_timer.uniq_id, )
                    Message.success(
                        request,
                        f'Le chronomètre [{admin_timer.uniq_id}] a été dupliqué.'
                        f'([{stored_timer.uniq_id}]).')
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        event_loader.clear_cache(admin_event.uniq_id)
        admin_event = event_loader.load_event(admin_event.uniq_id, reload=True)
        return self._admin_render_index(
            request, event_loader, admin_event=admin_event, admin_event_selector='@timers')

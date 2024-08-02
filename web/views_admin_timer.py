from datetime import datetime
import re
import time
from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, Reswap

from common.exception import PapiWebException
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.timer import NewTimer, NewTimerHour
from data.event import NewEvent
from data.loader import EventLoader
from database.sqlite import EventDatabase
from database.store import StoredTimer, StoredTimerHour
from web.messages import Message
from web.views_admin import AAdminController

logger: Logger = get_logger()


class AdminTimerController(AAdminController):

    def _admin_validate_timer_update_data(
            self,
            action: str,
            admin_event: NewEvent,
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

    def _admin_validate_timer_hour_update_data(
            self,
            admin_timer: NewTimer,
            admin_timer_hour: NewTimerHour,
            previous_valid_timer_hour: NewTimerHour | None,
            data: dict[str, str] | None = None,
    ) -> StoredTimerHour:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        uniq_id: str = self.form_data_to_str_or_none(data, 'uniq_id')
        if not uniq_id:
            errors['uniq_id'] = 'Veuillez entrer l\'identifiant de l\'horaire (ou le numéro de ronde).'
        time_str: str = self.form_data_to_str_or_none(data, 'time_str')
        date_str: str = self.form_data_to_str_or_none(data, 'date_str')
        if not time_str:
            errors['time_str'] = f'Veuillez entrer l\'heure.'
        else:
            matches = re.match('^(?P<hour>[0-9]{1,2}):(?P<minute>[0-9]{1,2})$', time_str)
            if not matches:
                errors['time_str'] = f'Veuillez entrer une heure valide.'
        if not previous_valid_timer_hour and not date_str:
            errors['date_str'] = f'Veuillez entrer La date du premier horaire.'
        elif date_str:
            if not re.match('^#?(?P<year>[0-9]{4})-(?P<month>[0-9]{1,2})-(?P<day>[0-9]{1,2})$', date_str):
                errors['date_str'] = f'Veuillez entrer une date valide.'
        if 'time_str' not in errors and 'date_str' not in errors:
            datetime_str: str
            if date_str:
                datetime_str = f'{date_str} {time_str}'
            else:
                datetime_str = f'{previous_valid_timer_hour.date_str} {time_str}'
            try:
                timestamp: int = int(time.mktime(datetime.strptime(
                    datetime_str, '%Y-%m-%d %H:%M').timetuple()))
                if previous_valid_timer_hour and timestamp <= previous_valid_timer_hour.timestamp:
                    errors['time_str'] = (f'L\'horaire [{datetime_str}] arrive avant l\'horaire précédent '
                                          f'[{previous_valid_timer_hour.datetime_str}], horaire non valide')
                    if date_str:
                        errors['date_str'] = errors['time_str']
            except ValueError:
                errors['time_str'] = f'Veuillez entrer une date et une heure valides.'
                if date_str:
                    errors['date_str'] = errors['time_str']
        if uniq_id != admin_timer_hour.uniq_id and uniq_id in admin_timer.timer_hour_uniq_ids:
            errors['uniq_id'] = f'L\'horaire [{uniq_id}] existe déjà.'
        text_before: str = self.form_data_to_str_or_none(data, 'text_before')
        text_after: str = self.form_data_to_str_or_none(data, 'text_after')
        try:
            round: int = int(uniq_id)
            assert round > 0, ValueError
        except (TypeError, ValueError):
            if not text_before:
                errors['text_before'] = \
                    'Veuillez entrer le texte avant l\'horaire (obligatoire sauf pour les débuts de ronde).'
            if not text_after:
                errors['text_after'] = \
                    'Veuillez entrer le texte après l\'horaire (obligatoire sauf pour les débuts de ronde).'
        return StoredTimerHour(
            id=admin_timer_hour.id,
            order=admin_timer_hour.order,
            timer_id=admin_timer.id,
            uniq_id=uniq_id,
            date_str=date_str,
            time_str=time_str,
            text_before=text_before,
            text_after=text_after,
            errors=errors,
        )

    @classmethod
    def _admin_timer_render_hours_modal(
            cls,
            action: str,
            admin_event: NewEvent,
            admin_timer: NewTimer | None,
            admin_timer_hour: NewTimerHour | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        return HTMXTemplate(
            template_name='admin_timer_hours_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'papi_web_config': PapiWebConfig(),
                'action': action,
                'admin_event': admin_event,
                'admin_timer': admin_timer,
                'admin_timer_hour': admin_timer_hour,
                'data': data,
                'errors': errors,
            })

    @post(
        path='/admin-timer-render-hours-modal',
        name='admin-timer-render-hours-modal'
    )
    async def htmx_admin_timer_render_hours_modal(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str | list[int]],
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
        admin_timer_id: int = self.form_data_to_int_or_none(data, 'admin_timer_id')
        try:
            admin_timer = admin_event.timers_by_id[admin_timer_id]
        except KeyError:
            Message.error(request, f'Le chronomètre [{admin_timer_id}] est introuvable.')
        admin_timer_hour_id: int = self.form_data_to_int_or_none(data, 'admin_timer_hour_id')
        data: dict[str, str] = {}
        admin_timer_hour: NewTimerHour | None
        errors: dict[str, str]
        if action == 'edit':
            try:
                admin_timer_hour = admin_timer.timer_hours_by_id[admin_timer_hour_id]
            except KeyError:
                Message.error(request, f'L\'horaire [{admin_timer_hour_id}] est introuvable.')
                return self._render_messages(request)
            data['uniq_id'] = self.value_to_form_data(admin_timer_hour.stored_timer_hour.uniq_id)
            data['date_str'] = self.value_to_form_data(admin_timer_hour.stored_timer_hour.date_str)
            data['time_str'] = self.value_to_form_data(admin_timer_hour.stored_timer_hour.time_str)
            data['text_before'] = self.value_to_form_data(admin_timer_hour.stored_timer_hour.text_before)
            data['text_after'] = self.value_to_form_data(admin_timer_hour.stored_timer_hour.text_after)
            stored_timer_hour = self._admin_validate_timer_hour_update_data(
                admin_timer, admin_timer_hour, admin_timer.get_previous_timer_hour(admin_timer_hour), data)
            errors = stored_timer_hour.errors
        else:
            admin_timer_hour = None
            errors = {}
        return self._admin_timer_render_hours_modal(action, admin_event, admin_timer, admin_timer_hour, data, errors)

    @post(
        path='/admin-timer-hours-update',
        name='admin-timer-hours-update'
    )
    async def htmx_admin_timer_hours_update(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str | list[int]],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template | Reswap:
        event_loader: EventLoader = EventLoader()
        admin_event_uniq_id: str = self.form_data_to_str_or_none(data, 'admin_event_uniq_id')
        try:
            admin_event: NewEvent = event_loader.load_event(admin_event_uniq_id)
        except PapiWebException as pwe:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : [{pwe}].')
            return self._render_messages(request)
        action: str = self.form_data_to_str_or_none(data, 'action')
        admin_timer: NewTimer | None = None
        match action:
            case 'delete' | 'clone' | 'update' | 'add' | 'reorder' | 'cancel':
                admin_timer_id: int = self.form_data_to_int_or_none(data, 'admin_timer_id')
                try:
                    admin_timer = admin_event.timers_by_id[admin_timer_id]
                except KeyError:
                    Message.error(request, f'Le chronomètre [{admin_timer_id}] est introuvable.')
                    return self._render_messages(request)
            case 'close':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        admin_timer_hour: NewTimerHour | None = None
        match action:
            case 'delete' | 'clone' | 'update':
                admin_timer_hour_id: int = self.form_data_to_int_or_none(data, 'admin_timer_hour_id')
                try:
                    admin_timer_hour = admin_timer.timer_hours_by_id[admin_timer_hour_id]
                except KeyError:
                    Message.error(request, f'L\'horaire [{admin_timer_hour_id}] est introuvable.')
                    return self._render_messages(request)
            case 'add' | 'reorder' | 'cancel' | 'close':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        stored_timer_hour: StoredTimerHour | None = None
        with (EventDatabase(admin_event.uniq_id, write=True) as event_database):
            match action:
                case 'close':
                    return self._admin_render_index(
                        request, event_loader, admin_event=admin_event, admin_event_selector='@timers')
                case 'update':
                    stored_timer_hour: StoredTimerHour = self._admin_validate_timer_hour_update_data(
                        admin_timer, admin_timer_hour, admin_timer.get_previous_timer_hour(admin_timer_hour), data)
                    if stored_timer_hour.errors:
                        return self._admin_timer_render_hours_modal(
                            'edit', admin_event, admin_timer, admin_timer_hour, data, stored_timer_hour.errors)
                    stored_timer_hour = event_database.update_stored_timer_hour(stored_timer_hour)
                case 'delete':
                    event_database.delete_stored_timer_hour(admin_timer_hour.id)
                    event_database.order_stored_timer_hours(admin_timer.id)
                case 'clone':
                    stored_timer_hour = event_database.clone_stored_timer_hour(admin_timer_hour.id)
                case 'add':
                    stored_timer_hour = event_database.add_stored_timer_hour(admin_timer.id)
                case 'reorder':
                    event_database.reorder_stored_timer_hours(data['item'])
                case 'cancel':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        event_loader.clear_cache(admin_event.uniq_id)
        admin_event = event_loader.load_event(admin_event.uniq_id, reload=True)
        admin_timer = admin_event.timers_by_id[admin_timer.id]
        admin_timer_hour = admin_timer.timer_hours_by_id[stored_timer_hour.id] if stored_timer_hour else None
        return self._admin_timer_render_hours_modal(
            '', admin_event=admin_event, admin_timer=admin_timer, admin_timer_hour=admin_timer_hour)

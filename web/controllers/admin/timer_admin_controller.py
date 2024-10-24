import re
import time
from datetime import datetime
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
from data.loader import EventLoader
from data.timer import Timer, TimerHour
from database.sqlite import EventDatabase
from database.store import StoredTimer, StoredTimerHour
from web.controllers.admin.event_admin_controller import EventAdminWebContext, AbstractEventAdminController
from web.controllers.index_controller import WebContext, AbstractController
from web.messages import Message

logger: Logger = get_logger()


class TimerAdminWebContext(EventAdminWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ] | None,
            event_uniq_id: str,
            timer_id: int | None,
            timer_hour_id: int | None,
    ):
        super().__init__(request, data=data, event_uniq_id=event_uniq_id, admin_event_tab=None)
        self.admin_timer: Timer | None = None
        self.admin_timer_hour: TimerHour | None = None
        if self.error:
            return
        if timer_id:
            try:
                self.admin_timer = self.admin_event.timers_by_id[timer_id]
            except KeyError:
                self._redirect_error(f'Le chronomètre [{timer_id}] n\'existe pas')
                return
        if timer_hour_id:
            try:
                self.admin_timer_hour = self.admin_timer.timer_hours_by_id[timer_hour_id]
            except KeyError:
                self._redirect_error(
                    f'L\'horaire [{timer_hour_id}] n\'existe pas pour le chronomètre '
                    f'[{self.admin_timer.uniq_id}]')
                return

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'admin_timer': self.admin_timer,
            'admin_timer_hour': self.admin_timer_hour,
        }


class TimerAdminController(AbstractEventAdminController):

    @staticmethod
    def _admin_validate_timer_update_data(
            action: str,
            web_context: TimerAdminWebContext,
            data: dict[str, str] | None = None,
    ) -> StoredTimer | None:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        match action:
            case 'delete' | 'create' | 'clone' | 'update':
                uniq_id: str = WebContext.form_data_to_str(data, 'uniq_id')
            case _:
                raise ValueError(f'action=[{action}]')
        match action:
            case 'create' | 'clone' | 'update':
                if not uniq_id:
                    errors['uniq_id'] = 'Veuillez entrer l\'identifiant du chronomètre.'
            case 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        match action:
            case 'create' | 'clone':
                if uniq_id in web_context.admin_event.timers_by_uniq_id:
                    errors['uniq_id'] = f'Le chronomètre [{uniq_id}] existe déjà.'
            case 'update':
                if uniq_id != web_context.admin_timer.uniq_id and uniq_id in web_context.admin_event.timers_by_uniq_id:
                    errors['uniq_id'] = f'Le chronomètre [{uniq_id}] existe déjà.'
            case 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        colors: dict[int, str | None] = {i: None for i in range(1, 4)}
        color_checkboxes: dict[int, bool | None] = {i: None for i in range(1, 4)}
        delays: dict[int, int | None] = {i: None for i in range(1, 4)}
        match action:
            case 'update':
                for i in range(1, 4):
                    field: str = f'color_{i}'
                    color_checkboxes[i] = WebContext.form_data_to_bool(data, field + '_checkbox')
                    if not color_checkboxes[i]:
                        try:
                            colors[i] = WebContext.form_data_to_rgb(data, field)
                        except ValueError:
                            errors[field] = f'La couleur n\'est pas valide [{data[field]}] (attendu [#HHHHHH]).'
                    field: str = f'delay_{i}'
                    try:
                        delays[i] = WebContext.form_data_to_int(data, field, minimum=1)
                    except ValueError:
                        errors[field] = f'Le délai [{data[field]}] n\'est pas valide (attendu un entier positif).'
            case 'create' | 'clone' | 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        return StoredTimer(
            id=web_context.admin_timer.id if action != 'create' else None,
            uniq_id=uniq_id,
            colors=colors,
            delays=delays,
            errors=errors,
        )

    def _admin_timer_modal(
            self, request: HTMXRequest,
            action: str,
            event_uniq_id: str,
            timer_id: int | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template | ClientRedirect:
        web_context: TimerAdminWebContext = TimerAdminWebContext(
            request, data=None, event_uniq_id=event_uniq_id, timer_id=timer_id, timer_hour_id=None)
        if web_context.error:
            return web_context.error
        if data is None:
            data = {}
            match action:
                case 'update':
                    data['uniq_id'] = WebContext.value_to_form_data(web_context.admin_timer.stored_timer.uniq_id)
                case 'create' | 'clone':
                    data['uniq_id'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            match action:
                case 'update' | 'clone':
                    for i in range(1, 4):
                        data[f'color_{i}'] = WebContext.value_to_form_data(web_context.admin_timer.colors[i])
                        data[f'color_{i}_checkbox'] = WebContext.value_to_form_data(
                            web_context.admin_timer.stored_timer.colors[i] is None)
                        data[f'delay_{i}'] = WebContext.value_to_form_data(
                            web_context.admin_timer.stored_timer.delays[i])
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
                action, web_context, data)
            errors = stored_timer.errors
        if errors is None:
            errors = {}
        return HTMXTemplate(
            template_name='admin_timer_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context=web_context.template_context | {
                'action': action,
                'data': data,
                'timer_color_texts': self._get_timer_color_texts(web_context.admin_event.timer_delays),
                'errors': errors,
            })

    @get(
        path='/admin/timer-modal/create/{event_uniq_id:str}',
        name='admin-timer-create-modal'
    )
    async def htmx_admin_timer_create_modal(
            self, request: HTMXRequest,
            event_uniq_id: str,
    ) -> Template | ClientRedirect:
        return self._admin_timer_modal(request, action='create', event_uniq_id=event_uniq_id, timer_id=None)

    @get(
        path='/admin/timer-modal/{action:str}/{event_uniq_id:str}/{timer_id:int}',
        name='admin-timer-modal'
    )
    async def htmx_admin_timer_modal(
            self, request: HTMXRequest,
            action: str,
            event_uniq_id: str,
            timer_id: int | None,
    ) -> Template | ClientRedirect:
        return self._admin_timer_modal(request, action=action, event_uniq_id=event_uniq_id, timer_id=timer_id)

    def _admin_timer_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            action: str,
            event_uniq_id: str,
            timer_id: int | None,
    ) -> Template | ClientRedirect:
        match action:
            case 'update' | 'delete' | 'clone' | 'create':
                web_context: TimerAdminWebContext = TimerAdminWebContext(
                    request, data=data, event_uniq_id=event_uniq_id, timer_id=timer_id, timer_hour_id=None)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        stored_timer: StoredTimer | None = self._admin_validate_timer_update_data(action, web_context, data)
        if stored_timer.errors:
            return self._admin_timer_modal(
                request, action=action, event_uniq_id=event_uniq_id, timer_id=timer_id, data=data,
                errors=stored_timer.errors)
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        with (EventDatabase(web_context.admin_event.uniq_id, write=True) as event_database):
            match action:
                case 'create':
                    stored_timer = event_database.add_stored_timer(stored_timer)
                    event_database.commit()
                    Message.success(request, f'Le chronomètre [{stored_timer.uniq_id}] a été créé.')
                    event_loader.clear_cache(event_uniq_id)
                    return self._admin_timer_modal(
                        request, action='update', event_uniq_id=event_uniq_id, timer_id=stored_timer.id)
                case 'update':
                    stored_timer = event_database.update_stored_timer(stored_timer)
                    Message.success(request, f'Le chronomètre [{stored_timer.uniq_id}] a été modifié.')
                    if not web_context.admin_timer.timer_hours_by_id:
                        stored_timer_hour: StoredTimerHour = event_database.add_stored_timer_hour(
                            web_context.admin_timer.id, set_datetime=True)
                        event_database.commit()
                        event_loader.clear_cache(event_uniq_id)
                        return self._admin_timer_hours_modal(
                            request, event_uniq_id=event_uniq_id, timer_id=stored_timer.id,
                            timer_hour_id=stored_timer_hour.id)
                    else:
                        event_database.commit()
                        event_loader.clear_cache(event_uniq_id)
                        for timer_hour in web_context.admin_timer.timer_hours_sorted_by_order:
                            if timer_hour.error:
                                return self._admin_timer_hours_modal(
                                    request, event_uniq_id=event_uniq_id, timer_id=stored_timer.id,
                                    timer_hour_id=timer_hour.id)
                        return self._admin_event_render(
                            request, event_uniq_id=event_uniq_id, admin_event_tab='timers')
                case 'delete':
                    event_database.delete_stored_timer(web_context.admin_timer.id)
                    event_database.commit()
                    Message.success(request, f'Le chronomètre [{web_context.admin_timer.uniq_id}] a été supprimé.')
                    event_loader.clear_cache(event_uniq_id)
                    return self._admin_event_render(request, event_uniq_id=event_uniq_id, admin_event_tab='timers')
                case 'clone':
                    stored_timer = event_database.clone_stored_timer(web_context.admin_timer.id, stored_timer.uniq_id, )
                    event_database.commit()
                    Message.success(
                        request,
                        f'Le chronomètre [{web_context.admin_timer.uniq_id}] a été dupliqué '
                        f'([{stored_timer.uniq_id}]).')
                    event_loader.clear_cache(event_uniq_id)
                    return self._admin_timer_modal(
                        request, action='update', event_uniq_id=event_uniq_id, timer_id=stored_timer.id)
                case _:
                    raise ValueError(f'action=[{action}]')

    @post(
        path='/admin/timer-create/{event_uniq_id:str}',
        name='admin-timer-create'
    )
    async def htmx_admin_timer_create(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
    ) -> Template | ClientRedirect:
        return self._admin_timer_update(
            request, data=data, action='create', event_uniq_id=event_uniq_id, timer_id=None)

    @post(
        path='/admin/timer-clone/{event_uniq_id:str}/{timer_id:int}',
        name='admin-timer-clone',
    )
    async def htmx_admin_timer_clone(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            timer_id: int | None,
    ) -> Template | ClientRedirect:
        return self._admin_timer_update(
            request, data=data, action='clone', event_uniq_id=event_uniq_id, timer_id=timer_id)

    @patch(
        path='/admin/timer-update/{event_uniq_id:str}/{timer_id:int}',
        name='admin-timer-update',
    )
    async def htmx_admin_timer_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            timer_id: int | None,
    ) -> Template | ClientRedirect:
        return self._admin_timer_update(
            request, data=data, action='update', event_uniq_id=event_uniq_id, timer_id=timer_id)

    @delete(
        path='/admin/timer-delete/{event_uniq_id:str}/{timer_id:int}',
        name='admin-timer-delete',
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_timer_delete(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            timer_id: int | None,
    ) -> Template | ClientRedirect:
        return self._admin_timer_update(
            request, data=data, action='delete', event_uniq_id=event_uniq_id, timer_id=timer_id)

    @staticmethod
    def _admin_validate_timer_hour_update_data(
            web_context: TimerAdminWebContext,
            previous_valid_timer_hour: TimerHour | None,
            data: dict[str, str] | None = None,
    ) -> StoredTimerHour:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        uniq_id: str = WebContext.form_data_to_str(data, 'uniq_id')
        if not uniq_id:
            errors['uniq_id'] = 'Veuillez entrer l\'identifiant de l\'horaire (ou le numéro de ronde).'
        time_str: str = WebContext.form_data_to_str(data, 'time_str')
        date_str: str = WebContext.form_data_to_str(data, 'date_str')
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
        if uniq_id != web_context.admin_timer_hour.uniq_id and uniq_id in web_context.admin_timer.timer_hour_uniq_ids:
            errors['uniq_id'] = f'L\'horaire [{uniq_id}] existe déjà.'
        text_before: str = WebContext.form_data_to_str(data, 'text_before')
        text_after: str = WebContext.form_data_to_str(data, 'text_after')
        try:
            round: int = int(uniq_id)
            if round <= 0:
                errors['uniq_id'] = 'Les numéros de ronde doivent être positifs.'
        except (TypeError, ValueError, AssertionError):
            if not text_before:
                errors['text_before'] = \
                    'Veuillez entrer le texte avant l\'horaire (obligatoire sauf pour les débuts de ronde).'
            if not text_after:
                errors['text_after'] = \
                    'Veuillez entrer le texte après l\'horaire (obligatoire sauf pour les débuts de ronde).'
        return StoredTimerHour(
            id=web_context.admin_timer_hour.id,
            order=web_context.admin_timer_hour.order,
            timer_id=web_context.admin_timer.id,
            uniq_id=uniq_id,
            date_str=date_str,
            time_str=time_str,
            text_before=text_before,
            text_after=text_after,
            errors=errors,
        )

    def _admin_timer_hours_modal(
            self, request: HTMXRequest,
            event_uniq_id: str,
            timer_id: int,
            timer_hour_id: int | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template | ClientRedirect:
        web_context: TimerAdminWebContext = TimerAdminWebContext(
            request, data=None, event_uniq_id=event_uniq_id, timer_id=timer_id, timer_hour_id=timer_hour_id)
        if web_context.error:
            return web_context.error
        if data is None:
            if web_context.admin_timer_hour:
                data = {
                    'uniq_id': WebContext.value_to_form_data(web_context.admin_timer_hour.stored_timer_hour.uniq_id),
                    'date_str': WebContext.value_to_form_data(web_context.admin_timer_hour.stored_timer_hour.date_str),
                    'time_str': WebContext.value_to_form_data(web_context.admin_timer_hour.stored_timer_hour.time_str),
                    'text_before': WebContext.value_to_form_data(
                        web_context.admin_timer_hour.stored_timer_hour.text_before),
                    'text_after': WebContext.value_to_form_data(
                        web_context.admin_timer_hour.stored_timer_hour.text_after),
                }
                stored_timer_hour = self._admin_validate_timer_hour_update_data(
                    web_context, web_context.admin_timer.get_previous_timer_hour(web_context.admin_timer_hour), data)
                errors = stored_timer_hour.errors
            else:
                data = {}
        if errors is None:
            errors = {}
        return HTMXTemplate(
            template_name='admin_timer_hours_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context=web_context.template_context | {
                'data': data,
                'errors': errors,
            })

    @get(
        path='/admin/timer-hours-modal/{event_uniq_id:str}/{timer_id:int}',
        name='admin-timer-hours-modal'
    )
    async def htmx_admin_timer_hours_modal(
            self, request: HTMXRequest,
            event_uniq_id: str,
            timer_id: int,
    ) -> Template | ClientRedirect:
        return self._admin_timer_hours_modal(
            request, event_uniq_id=event_uniq_id, timer_id=timer_id, timer_hour_id=None)

    @get(
        path='/admin/timer-hours-hour-modal/{event_uniq_id:str}/{timer_id:int}/{timer_hour_id:int}',
        name='admin-timer-hours-hour-modal'
    )
    async def htmx_admin_timer_hours_hour_modal(
            self, request: HTMXRequest,
            event_uniq_id: str,
            timer_id: int,
            timer_hour_id: int,
    ) -> Template | ClientRedirect:
        return self._admin_timer_hours_modal(
            request, event_uniq_id=event_uniq_id, timer_id=timer_id, timer_hour_id=timer_hour_id)

    def _admin_timer_hours_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str | list[int]], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            action: str,
            event_uniq_id: str,
            timer_id: int,
            timer_hour_id: int | None,
    ) -> Template | ClientRedirect:
        match action:
            case 'delete' | 'clone' | 'update' | 'add' | 'reorder':
                web_context: TimerAdminWebContext = TimerAdminWebContext(
                    request, data=data, event_uniq_id=event_uniq_id, timer_id=timer_id, timer_hour_id=timer_hour_id)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        match action:
            case 'delete':
                if len(web_context.admin_timer.timer_hours_by_id) <= 1:
                    return AbstractController.redirect_error(
                        request, f'Le dernier horaire d\'un chronomètre ne peut être supprimé.')
            case 'update' | 'clone' | 'add' | 'reorder':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        next_timer_hour_id: int | None = None
        with (EventDatabase(web_context.admin_event.uniq_id, write=True) as event_database):
            match action:
                case 'update':
                    stored_timer_hour: StoredTimerHour = self._admin_validate_timer_hour_update_data(
                        web_context, web_context.admin_timer.get_previous_timer_hour(web_context.admin_timer_hour),
                        data)
                    if stored_timer_hour.errors:
                        return self._admin_timer_hours_modal(
                            request, event_uniq_id=event_uniq_id, timer_id=timer_id, timer_hour_id=timer_hour_id,
                            data=data, errors=stored_timer_hour.errors)
                    event_database.update_stored_timer_hour(stored_timer_hour)
                case 'delete':
                    event_database.delete_stored_timer_hour(web_context.admin_timer_hour.id, web_context.admin_timer.id)
                case 'clone':
                    stored_timer_hour = event_database.clone_stored_timer_hour(web_context.admin_timer_hour.id)
                    next_timer_hour_id = stored_timer_hour.id
                case 'add':
                    stored_timer_hour = event_database.add_stored_timer_hour(web_context.admin_timer.id)
                    next_timer_hour_id = stored_timer_hour.id
                case 'reorder':
                    event_database.reorder_stored_timer_hours(data['item'])
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        event_loader.clear_cache(event_uniq_id)
        return self._admin_timer_hours_modal(
            request, event_uniq_id=event_uniq_id, timer_id=timer_id, timer_hour_id=next_timer_hour_id, data=None,
            errors=None)

    @post(
        path='/admin/timer-hour-add/{event_uniq_id:str}/{timer_id:int}',
        name='admin-timer-hour-add',
    )
    async def htmx_admin_timer_hour_add(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            timer_id: int,
    ) -> Template | ClientRedirect:
        return self._admin_timer_hours_update(
            request, data=data, action='add', event_uniq_id=event_uniq_id, timer_id=timer_id, timer_hour_id=None)

    @post(
        path='/admin/timer-hour-clone/{event_uniq_id:str}/{timer_id:int}/{timer_hour_id:int}',
        name='admin-timer-hour-clone',
    )
    async def htmx_admin_timer_hour_clone(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str | list[int]], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            timer_id: int,
            timer_hour_id: int,
    ) -> Template | ClientRedirect:
        return self._admin_timer_hours_update(
            request, data=data, action='clone', event_uniq_id=event_uniq_id, timer_id=timer_id,
            timer_hour_id=timer_hour_id)

    @patch(
        path='/admin/timer-hour-update/{event_uniq_id:str}/{timer_id:int}/{timer_hour_id:int}',
        name='admin-timer-hour-update',
    )
    async def htmx_admin_timer_hour_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str | list[int]], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            timer_id: int,
            timer_hour_id: int,
    ) -> Template | ClientRedirect:
        return self._admin_timer_hours_update(
            request, data=data, action='update', event_uniq_id=event_uniq_id, timer_id=timer_id,
            timer_hour_id=timer_hour_id)

    @delete(
        path='/admin/timer-hour-delete/{event_uniq_id:str}/{timer_id:int}/{timer_hour_id:int}',
        name='admin-timer-hour-delete',
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_timer_hour_delete(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str | list[int]], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            timer_id: int,
            timer_hour_id: int,
    ) -> Template | ClientRedirect:
        return self._admin_timer_hours_update(
            request, data=data, action='delete', event_uniq_id=event_uniq_id, timer_id=timer_id,
            timer_hour_id=timer_hour_id)

    @patch(
        path='/admin/timer-reorder-hours/{event_uniq_id:str}/{timer_id:int}',
        name='admin-timer-reorder-hours',
    )
    async def htmx_admin_timer_reorder_hours(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str | list[int]], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            event_uniq_id: str,
            timer_id: int,
    ) -> Template | ClientRedirect:
        return self._admin_timer_hours_update(
            request, data=data, action='reorder', event_uniq_id=event_uniq_id, timer_id=timer_id, timer_hour_id=None)

from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate

from common.logger import get_logger
from data.event import Event, get_events_by_uniq_id
from web.messages import Message
from web.views_admin import AAdminController

logger: Logger = get_logger()


class AdminEventController(AAdminController):
    @staticmethod
    def _admin_validate_event_update_data(
            admin_event: Event | None,
            events_by_id: dict[str, Event],
            data: dict[str, str] | None = None,
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        event_uniq_id: str = data.get('event_uniq_id', '')
        if not event_uniq_id:
            errors['event_uniq_id'] = 'Veuillez entrer l\'identifiant de l\'évènement.'
        else:
            if event_uniq_id.find('/') != -1:
                errors['event_uniq_id'] = "le caractère « / » n\'est pas autorisé"
            else:
                if admin_event:
                    if event_uniq_id != admin_event.uniq_id and event_uniq_id in events_by_id:
                        errors['event_uniq_id'] = f'Un autre évènement avec l\'identifiant [{event_uniq_id}] existe déjà.'
                else:
                    if event_uniq_id in events_by_id:
                        errors['event_uniq_id'] = f'L\'évènement [{event_uniq_id}] existe déjà.'
        event_name: str = data.get('event_name', '')
        if not event_name:
            errors['event_name'] = 'Veuillez entrer le nom de l\'évènement.'
        try:
            event_record_illegal_moves: int = int(data.get('event_record_illegal_moves', '0'))
            assert 0 <= event_record_illegal_moves <= 3
        except (ValueError, AssertionError):
            errors['event_record_illegal_moves'] = 'La valeur entrée n\'est pas valide.'
        try:
            bool(data.get('event_allow_deletion', ''))
        except ValueError:
            errors['event_allow_deletion'] = 'La valeur entrée n\'est pas valide.'
        return errors

    @staticmethod
    def _admin_event_render_edit_modal(
            admin_event: Event | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        return HTMXTemplate(
            template_name='admin_event_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'admin_event': admin_event,
                'data': data,
                'errors': errors,
                'record_illegal_moves_options': {
                    '0': 'Aucun enregistrement des coups illégaux',
                    '1': 'Maximum 1 coup illégal',
                    '2': 'Maximum 2 coups illégaux',
                    '3': 'Maximum 3 coups illégaux',
                },
            })

    @post(
        path='/admin-event-render-edit-modal',
        name='admin-event-render-edit-modal'
    )
    async def htmx_admin_event_render_edit_modal(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        events_by_id: dict[str, Event] = get_events_by_uniq_id(load_screens=False, with_tournaments_only=False)
        admin_event_uniq_id: str = data.get('admin_event_uniq_id', '')
        admin_event: Event | None = None
        if admin_event_uniq_id:
            try:
                admin_event: Event = events_by_id[admin_event_uniq_id]
                data: dict[str, str] = {
                    'event_uniq_id': admin_event.uniq_id,
                    'event_name': admin_event.name,
                    'event_css': admin_event.css,
                    'event_update_password': admin_event.update_password,
                    'event_record_illegal_moves': admin_event.record_illegal_moves,
                    'event_allow_deletion': admin_event.allow_deletion,
                }
            except KeyError:
                Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable.')
                return self._render_messages(request)
        else:
            data: dict[str, str] = {}
        errors: dict[str, str] = self._admin_validate_event_update_data(admin_event, events_by_id, data)
        return self._admin_event_render_edit_modal(admin_event, data, errors)

    @post(
        path='/admin-event-update',
        name='admin-event-update'
    )
    async def htmx_admin_event_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        events_by_id: dict[str, Event] = get_events_by_uniq_id(load_screens=False, with_tournaments_only=False)
        admin_event_uniq_id: str = data.get('admin_event_uniq_id', '')
        admin_event: Event | None = None
        if admin_event_uniq_id:
            try:
                admin_event = events_by_id[admin_event_uniq_id]
            except KeyError:
                Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable.')
                return self._render_messages(request)
        errors: dict[str, str] = self._admin_validate_event_update_data(admin_event, events_by_id, data)
        if errors:
            return self._admin_event_render_edit_modal(admin_event, data, errors)
        if admin_event:
            # TODO Update the event
            # admin_event: Event = UPDATE_EVENT(data)
            # Message.success(request, f'L\'évènement [{admin_event.uniq_uniq_id}] a été modifié.')
            # events_by_id[admin_event.uniq_uniq_id] = admin_event
            # if data['event_uniq_id'] != admin_event.uniq_uniq_id:
            #     delete events_by_id['event_uniq_id'])
            events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
            # return _admin_render_index(request, events, admin_event=admin_event)
            Message.error(
                request, f'La modification des évènements par l\'interface web n\'est pas encore implémentée.')
            return self._admin_render_index(request, events, admin_event=admin_event, admin_event_selector='')
        else:
            # TODO Create the event
            # admin_event: Event = CREATE_EVENT(data)
            # Message.success(request, f'L\'évènement [{admin_event.uniq_uniq_id}] a été créé.')
            # events_by_id[admin_event.uniq_uniq_id] = admin_event
            events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
            # return _admin_render_index(request, events, admin_event=admin_event)
            Message.error(request, f'La création des évènements par l\'interface web n\'est pas encore implémentée.')
            return self._admin_render_index(request, events, admin_main_selector='@events')

    @staticmethod
    def _admin_validate_event_delete_data(
            admin_event: Event | None,
            data: dict[str, str] | None = None,
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        event_uniq_id: str = data.get('event_uniq_id', '')
        if not event_uniq_id:
            errors['event_uniq_id'] = 'Veuillez entrer l\'identifiant de l\'évènement.'
        elif event_uniq_id != admin_event.uniq_id:
            errors['event_uniq_id'] = f'L\'identifiant entré n\'est pas valide.'
        return errors

    @staticmethod
    def _admin_event_render_delete_modal(
            admin_event: Event,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        return HTMXTemplate(
            template_name='admin_event_delete_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'admin_event': admin_event,
                'data': data,
                'errors': errors,
            })

    @post(
        path='/admin-event-render-delete-modal',
        name='admin-event-render-delete-modal'
    )
    async def htmx_admin_event_render_delete_modal(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        events_by_id: dict[str, Event] = get_events_by_uniq_id(load_screens=False, with_tournaments_only=False)
        admin_event_uniq_id: str = data.get('admin_event_uniq_id', '')
        try:
            admin_event: Event = events_by_id[admin_event_uniq_id]
        except KeyError:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable.')
            return self._render_messages(request)
        data: dict[str, str] = {}
        errors: dict[str, str] = self._admin_validate_event_delete_data(admin_event, data)
        return self._admin_event_render_delete_modal(admin_event, data, errors)

    @post(
        path='/admin-event-delete',
        name='admin-event-delete'
    )
    async def htmx_admin_event_delete(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        events_by_id: dict[str, Event] = get_events_by_uniq_id(load_screens=False, with_tournaments_only=False)
        admin_event_uniq_id: str = data.get('admin_event_uniq_id', '')
        try:
            admin_event: Event = events_by_id[admin_event_uniq_id]
        except KeyError:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable.')
            return self._render_messages(request)
        errors: dict[str, str] = self._admin_validate_event_delete_data(admin_event, data)
        if errors:
            return self._admin_event_render_delete_modal(admin_event, data, errors)
        # TODO Delete the event
        # DELETE_EVENT(data)
        # Message.success(request, f'L\'évènement [{admin_event.uniq_uniq_id}] a été supprimé.')
        # del events_by_id[admin_event.uniq_uniq_id]
        Message.error(request, f'La suppression des évènements par l\'interface web n\'est pas encore implémentée.')
        events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
        return self._admin_render_index(request, events, admin_main_selector='@events')

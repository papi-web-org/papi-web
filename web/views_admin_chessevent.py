from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate

from common.logger import get_logger
from data.chessevent import ChessEvent
from data.event import Event, get_events_by_uniq_id
from web.messages import Message
from web.views_admin import AAdminController

logger: Logger = get_logger()


class AdminChessEventController(AAdminController):
    @staticmethod
    def _admin_validate_chessevent_update_data(
            admin_event: Event,
            admin_chessevent: ChessEvent,
            data: dict[str, str] | None = None,
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        chessevent_uniq_id: str = data.get('chessevent_uniq_id', '')
        if not chessevent_uniq_id:
            errors['chessevent_uniq_id'] = 'Veuillez entrer l\'identifiant de la connexion à ChessEvent.'
        else:
            if admin_chessevent:
                if (chessevent_uniq_id != admin_chessevent.uniq_id
                        and chessevent_uniq_id in admin_event.chessevents):
                    errors['chessevent_uniq_id'] = \
                        (f'Une autre connexion à ChessEvent avec l\'identifiant [{chessevent_uniq_id}] '
                         f'existe déjà.')
            else:
                if chessevent_uniq_id in admin_event.chessevents:
                    errors['chessevent_uniq_id'] = f'La connexion à ChessEvent [{chessevent_uniq_id}] existe déjà.'
        chessevent_user_id: str = data.get('chessevent_user_id', '')
        if not chessevent_user_id:
            errors['chessevent_user_id'] = 'Veuillez entrer l\'identifiant de connexion à ChessEvent.'
        chessevent_password: str = data.get('chessevent_password', '')
        if not chessevent_password:
            errors['chessevent_password'] = 'Veuillez entrer le mot de passe de connexion à ChessEvent.'
        chessevent_event_id: str = data.get('chessevent_event_id', '')
        if not chessevent_event_id:
            errors['chessevent_event_id'] = 'Veuillez entrer le nom de l\'évènement ChessEvent.'
        return errors

    @staticmethod
    def _admin_chessevent_render_edit_modal(
            admin_event: Event,
            admin_chessevent: ChessEvent | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        return HTMXTemplate(
            template_name='admin_chessevent_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
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
        events_by_id: dict[str, Event] = get_events_by_uniq_id(load_screens=False, with_tournaments_only=False)
        admin_event_uniq_id: str = data.get('admin_event_uniq_id', '')
        try:
            admin_event: Event = events_by_id[admin_event_uniq_id]
        except KeyError:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable.')
            return self._render_messages(request)
        admin_chessevent_uniq_id: str = data.get('admin_chessevent_uniq_id', '')
        admin_chessevent: ChessEvent | None = None
        if admin_chessevent_uniq_id:
            try:
                admin_chessevent = admin_event.chessevents[
                    admin_chessevent_uniq_id]
                data: dict[str, str] = {
                    'chessevent_uniq_id': admin_chessevent.uniq_id,
                    'chessevent_user_id': admin_chessevent.user_id,
                    'chessevent_password': admin_chessevent.password,
                    'chessevent_event_id': admin_chessevent.event_id,
                }
            except KeyError:
                Message.error(request, f'La connexion à ChessEvent [{admin_chessevent_uniq_id}] est introuvable.')
                return self._render_messages(request)
        else:
            data: dict[str, str] = {}
        errors: dict[str, str] = self._admin_validate_chessevent_update_data(admin_event, admin_chessevent, data)
        return self._admin_chessevent_render_edit_modal(admin_event, admin_chessevent, data, errors)

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
        events_by_id: dict[str, Event] = get_events_by_uniq_id(load_screens=False, with_tournaments_only=False)
        admin_event_uniq_id: str = data.get('admin_event_uniq_id', '')
        try:
            admin_event: Event = events_by_id[admin_event_uniq_id]
        except KeyError:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable.')
            return self._render_messages(request)
        admin_chessevent_uniq_id: str = data.get('admin_chessevent_uniq_id', '')
        admin_chessevent: ChessEvent | None = None
        if admin_chessevent_uniq_id:
            try:
                admin_chessevent = admin_event.chessevents[
                    admin_chessevent_uniq_id]
            except KeyError:
                Message.error(request, f'La connexion à ChessEvent [{admin_chessevent_uniq_id}] est introuvable.')
                return self._render_messages(request)
        errors: dict[str, str] = self._admin_validate_chessevent_update_data(
            admin_event, admin_chessevent, data)
        if errors:
            return self._admin_chessevent_render_edit_modal(
                admin_event, admin_chessevent, data, errors)
        if admin_chessevent:
            # TODO Update the ChessEvent
            # admin_event: Event = UPDATE_CHESSEVENT(data)
            # Message.success(
            #     request, f'La connexion ChessEvent [{admin_chessevent.uniq_id}] a été modifiée.')
            # admin_event.chessevents[admin_chessevents.uniq_id] = admin_chessevent
            # if data['chessevent_uniq_id'] != admin_chessevent.uniq_id:
            #     delete admin_event.chessevents['chessevent_uniq_id'])
            events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
            # return _admin_render_index(
            #     request, events, admin_event=admin_event, admin_chessevent=admin_chessevent)
            Message.error(
                request,
                f'La modification des connexions à ChessEvent par l\'interface web n\'est pas encore implémentée.')
        else:
            # TODO Create the ChessEvent
            # admin_chessevent: ChessEvent = CREATE_CHESSEVENT(data)
            # Message.success(request, f'La connexion [{admin_chessevents.uniq_id}] a été créée.')
            # admin_event.chessevents[admin_chessevents.uniq_id] = admin_chessevent
            events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
            # return _admin_render_index(
            #     request, events, admin_event=admin_event, admin_chessevent=admin_chessevent)
            Message.error(request,
                          f'La création des connexions à ChessEvent par l\'interface web n\'est pas encore '
                          f'implémentée.')
        return self._admin_render_index(
            request, events, admin_event=admin_event, admin_event_selector='@chessevents')

    @staticmethod
    def _admin_validate_chessevent_delete_data(
            admin_chessevent: ChessEvent,
            data: dict[str, str] | None = None,
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        chessevent_uniq_id: str = data.get('chessevent_uniq_id', '')
        if not chessevent_uniq_id:
            errors['chessevent_uniq_id'] = 'Veuillez entrer l\'identifiant de la connexion à ChessEvent.'
        elif chessevent_uniq_id != admin_chessevent.uniq_id:
            errors['chessevent_uniq_id'] = f'L\'identifiant entré n\'est pas valide.'
        return errors

    @staticmethod
    def _admin_chessevent_render_delete_modal(
            admin_event: Event,
            admin_chessevent: ChessEvent,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        return HTMXTemplate(
            template_name='admin_chessevent_delete_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'admin_event': admin_event,
                'admin_chessevent': admin_chessevent,
                'data': data,
                'errors': errors,
            })

    @post(
        path='/admin-chessevent-render-delete-modal',
        name='admin-chessevent-render-delete-modal'
    )
    async def htmx_admin_event_render_delete_modal(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        events_by_id: dict[str, Event] = get_events_by_uniq_id(load_screens=False, with_tournaments_only=False)
        admin_event_uniq_id: str = data.get('admin_event_uniq_id', '')
        try:
            admin_event: Event = events_by_id[admin_event_uniq_id]
        except KeyError:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable.')
            return self._render_messages(request)
        admin_chessevent_uniq_id: str = data.get('admin_chessevent_uniq_id', '')
        try:
            admin_chessevent: ChessEvent = admin_event.chessevents[admin_chessevent_uniq_id]
            data: dict[str, str] = {}
            errors: dict[str, str] = self._admin_validate_chessevent_delete_data(admin_chessevent, data)
            return self._admin_chessevent_render_delete_modal(admin_event, admin_chessevent, data, errors)
        except KeyError:
            Message.error(request, f'La connexion à ChessEvent [{admin_chessevent_uniq_id}] est introuvable.')
            return self._render_messages(request)

    @post(
        path='/admin-chessevent-delete',
        name='admin-chessevent-delete'
    )
    async def htmx_admin_event_delete(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        events_by_id: dict[str, Event] = get_events_by_uniq_id(load_screens=False, with_tournaments_only=False)
        admin_event_uniq_id: str = data.get('admin_event_uniq_id', '')
        try:
            admin_event: Event = events_by_id[admin_event_uniq_id]
        except KeyError:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable.')
            return self._render_messages(request)
        admin_chessevent_uniq_id: str = data.get('admin_chessevent_uniq_id', '')
        try:
            admin_chessevent: ChessEvent = admin_event.chessevents[admin_chessevent_uniq_id]
        except KeyError:
            Message.error(request, f'La connexion à ChessEvent [{admin_chessevent_uniq_id}] est introuvable.')
            return self._render_messages(request)
        errors: dict[str, str] = self._admin_validate_chessevent_delete_data(admin_chessevent, data)
        if errors:
            return self._admin_chessevent_render_delete_modal(admin_event, admin_chessevent, data, errors)
        # TODO Delete the ChessEvent
        # DELETE_CHESSEVENT(data)
        # Message.success(
        #     request, f'La connexion ChessEvent [{admin_chessevent.uniq_id}] a été supprimée.')
        # del admin_event.chessevents[admin_chessevent.uniq_id]
        Message.error(request,
                      f'La suppression des connexions à ChessEvent par l\'interface web n\'est pas encore implémentée.')
        events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
        return self._admin_render_index(request, events, admin_event=admin_event, admin_event_selector='@chessevents')

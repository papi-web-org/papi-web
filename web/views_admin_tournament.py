import re
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
from data.tournament import NewTournament
from data.event import NewEvent
from data.loader import EventLoader
from database.sqlite import EventDatabase
from database.store import StoredTournament
from web.messages import Message
from web.views_admin import AAdminController

logger: Logger = get_logger()


class AdminTournamentController(AAdminController):

    def _admin_validate_tournament_update_data(
            self, action: str, admin_event: NewEvent,
            admin_tournament: NewTournament,
            data: dict[str, str] | None = None,
    ) -> StoredTournament:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        uniq_id: str = self.form_data_to_str_or_none(data, 'uniq_id')
        if action == 'delete':
            if not uniq_id:
                errors['uniq_id'] = 'Veuillez entrer l\'identifiant du tournoi.'
            elif uniq_id != admin_tournament.uniq_id:
                errors['uniq_id'] = f'L\'identifiant entré n\'est pas valide.'
        else:
            if not uniq_id:
                errors['uniq_id'] = 'Veuillez entrer l\'identifiant du tournoi.'
            elif uniq_id.find('/') != -1:
                errors['uniq_id'] = "le caractère « / » n\'est pas autorisé"
            else:
                match action:
                    case 'create' | 'clone':
                        if uniq_id in admin_event.tournament_uniq_ids:
                            errors['uniq_id'] = f'Le tournoi [{uniq_id}] existe déjà.'
                    case 'update':
                        if uniq_id != admin_tournament.uniq_id and uniq_id in admin_event.tournament_uniq_ids:
                            errors['uniq_id'] = f'Le tournoi [{uniq_id}] existe déjà.'
                    case _:
                        raise ValueError(f'action=[{action}]')
        name: str = self.form_data_to_str_or_none(data, 'name')
        path: str | None = self.form_data_to_str_or_none(data, 'path')
        filename: str | None = self.form_data_to_str_or_none(data, 'filename')
        ffe_id: int | None = self.form_data_to_int_or_none(data, 'ffe_id')
        ffe_password: str | None = self.form_data_to_str_or_none(data, 'ffe_password')
        time_control_initial_time: int | None = self.form_data_to_int_or_none(data, 'time_control_initial_time')
        time_control_increment: int | None = self.form_data_to_int_or_none(data, 'time_control_increment')
        time_control_handicap_penalty_value: int | None = self.form_data_to_int_or_none(
            data, 'time_control_handicap_penalty_value')
        time_control_handicap_penalty_step: int | None = self.form_data_to_int_or_none(
            data, 'time_control_handicap_penalty_step')
        time_control_handicap_min_time: int | None = self.form_data_to_int_or_none(
            data, 'time_control_handicap_min_time')
        chessevent_id: int | None = self.form_data_to_int_or_none(data, 'chessevent_id')
        chessevent_tournament_name: str = self.form_data_to_str_or_none(data, 'chessevent_tournament_name')
        record_illegal_moves: int | None = self.form_data_to_str_or_none(data, 'record_illegal_moves')
        match action:
            case 'create' | 'update' | 'clone':
                if not name:
                    errors['name'] = 'Veuillez entrer le nom du tournoi.'
                if ffe_password and not re.match('^[A-Z]{10}$', ffe_password):
                    errors['ffe_password'] = \
                        'Le mot de passe du tournoi sur le site FFE doit être composé de 10 lettres majuscules.'
            case 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        return StoredTournament(
            id=admin_tournament.id if action != 'create' else None,
            uniq_id=uniq_id,
            name=name,
            path=path,
            filename=filename,
            ffe_id=ffe_id,
            ffe_password=ffe_password,
            time_control_initial_time=time_control_initial_time,
            time_control_increment=time_control_increment,
            time_control_handicap_penalty_value=time_control_handicap_penalty_value,
            time_control_handicap_penalty_step=time_control_handicap_penalty_step,
            time_control_handicap_min_time=time_control_handicap_min_time,
            chessevent_id=chessevent_id,
            chessevent_tournament_name=chessevent_tournament_name,
            record_illegal_moves=record_illegal_moves,
            errors=errors,
        )

    def _admin_tournament_render_edit_modal(
            self,
            action: str,
            admin_event: NewEvent,
            admin_tournament: NewTournament | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        return HTMXTemplate(
            template_name='admin_tournament_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'papi_web_config': PapiWebConfig(),
                'action': action,
                'admin_event': admin_event,
                'admin_tournament': admin_tournament,
                'data': data,
                'record_illegal_moves_options': self._get_record_illegal_moves_options(
                    admin_event.record_illegal_moves),
                'errors': errors,
            })

    @post(
        path='/admin-tournament-render-edit-modal',
        name='admin-tournament-render-edit-modal'
    )
    async def htmx_admin_tournament_render_edit_modal(
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
        admin_tournament: NewTournament | None = None
        match action:
            case 'update' | 'delete' | 'clone':
                admin_tournament_id: int = self.form_data_to_int_or_none(data, 'admin_tournament_id')
                try:
                    admin_tournament = admin_event.tournaments_by_id[admin_tournament_id]
                except KeyError:
                    Message.error(request, f'Le tournoi [{admin_tournament_id}] est introuvable.')
                    return self._render_messages(request)
            case 'create':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        data: dict[str, str] = {}
        match action:
            case 'update':
                data['uniq_id'] = self.value_to_form_data(admin_tournament.stored_tournament.uniq_id)
            case 'create' | 'clone':
                data['uniq_id'] = ''
            case 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        match action:
            case 'update' | 'clone':
                data['name'] = self.value_to_form_data(admin_tournament.stored_tournament.name)
                data['path'] = self.value_to_form_data(admin_tournament.stored_tournament.path)
                data['filename'] = self.value_to_form_data(admin_tournament.stored_tournament.filename)
                data['ffe_id'] = self.value_to_form_data(admin_tournament.stored_tournament.ffe_id)
                data['ffe_password'] = self.value_to_form_data(admin_tournament.stored_tournament.ffe_password)
            case 'create':
                data['name'] = ''
                data['path'] = ''
                data['filename'] = ''
                data['ffe_id'] = ''
                data['ffe_password'] = ''
            case 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        match action:
            case 'update':
                data['time_control_initial_time'] = self.value_to_form_data(
                    admin_tournament.stored_tournament.time_control_initial_time)
                data['time_control_increment'] = self.value_to_form_data(
                    admin_tournament.stored_tournament.time_control_increment)
                data['time_control_handicap_penalty_value'] = self.value_to_form_data(
                    admin_tournament.stored_tournament.time_control_handicap_penalty_value)
                data['time_control_handicap_penalty_step'] = self.value_to_form_data(
                    admin_tournament.stored_tournament.time_control_handicap_penalty_step)
                data['time_control_handicap_min_time'] = self.value_to_form_data(
                    admin_tournament.stored_tournament.time_control_handicap_min_time)
                data['chessevent_id'] = self.value_to_form_data(
                    admin_tournament.stored_tournament.chessevent_id)
                data['chessevent_tournament_name'] = self.value_to_form_data(
                    admin_tournament.stored_tournament.chessevent_tournament_name)
                data['record_illegal_moves'] = self.value_to_form_data(
                    admin_tournament.stored_tournament.record_illegal_moves)
            case 'delete' | 'clone' | 'create':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        stored_tournament: StoredTournament = self._admin_validate_tournament_update_data(
            action, admin_event, admin_tournament, data)
        return self._admin_tournament_render_edit_modal(
            action, admin_event, admin_tournament, data, stored_tournament.errors)

    @post(
        path='/admin-tournament-update',
        name='admin-tournament-update'
    )
    async def htmx_admin_tournament_update(
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
        admin_tournament: NewTournament | None = None
        match action:
            case 'update' | 'delete' | 'clone':
                admin_tournament_id: int = self.form_data_to_int_or_none(data, 'admin_tournament_id')
                try:
                    admin_tournament = admin_event.tournaments_by_id[admin_tournament_id]
                except KeyError:
                    Message.error(request, f'Le tournoi [{admin_tournament_id}] est introuvable.')
                    return self._render_messages(request)
            case 'create':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        stored_tournament: StoredTournament = self._admin_validate_tournament_update_data(
            action, admin_event, admin_tournament, data)
        if stored_tournament.errors:
            return self._admin_tournament_render_edit_modal(
                action, admin_event, admin_tournament, data, stored_tournament.errors)
        with (EventDatabase(admin_event.uniq_id, write=True) as event_database):
            match action:
                case 'update':
                    stored_tournament = event_database.update_stored_tournament(stored_tournament)
                    Message.success(request, f'Le tournoi [{stored_tournament.uniq_id}] a été modifié.')
                case 'create':
                    stored_tournament = event_database.add_stored_tournament(stored_tournament)
                    Message.success(request, f'Le tournoi [{stored_tournament.uniq_id}] a été créé.')
                case 'delete':
                    event_database.delete_stored_tournament(admin_tournament.id)
                    Message.success(request, f'Le tournoi [{admin_tournament.uniq_id}] a été supprimé.')
                case 'clone':
                    stored_tournament = event_database.clone_stored_tournament(
                        admin_tournament.id, stored_tournament.uniq_id, stored_tournament.name, stored_tournament.path,
                        stored_tournament.filename, stored_tournament.ffe_id, stored_tournament.ffe_password, )
                    Message.success(
                        request,
                        f'Le tournoi [{admin_tournament.uniq_id}] a été dupliqué.'
                        f'([{stored_tournament.uniq_id}]).')
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        event_loader.clear_cache(admin_event.uniq_id)
        admin_event = event_loader.load_event(admin_event.uniq_id, reload=True)
        return self._admin_render_index(
            request, event_loader, admin_event=admin_event, admin_event_selector='@tournaments')

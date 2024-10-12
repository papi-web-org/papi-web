import re
from logging import Logger
from typing import Annotated, Any

from litestar import post
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template

from common.logger import get_logger
from data.event import Event
from data.loader import EventLoader
from data.tournament import Tournament
from database.sqlite import EventDatabase
from database.store import StoredTournament
from web.messages import Message
from web.controllers.index_controller import WebContext
from web.controllers.admin.index_admin_controller import AbstractAdminController
from web.controllers.admin.event_admin_controller import EventAdminWebContext

logger: Logger = get_logger()


class TournamentAdminWebContext(EventAdminWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            tournament_needed: bool,
    ):
        super().__init__(request, data, True)
        self.admin_tournament: Tournament | None = None
        field: str = 'admin_tournament_id'
        if field in self.data:
            try:
                admin_tournament_id: int | None = self._form_data_to_int(field, minimum=1)
            except ValueError as ve:
                self._redirect_error(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
                return
            try:
                self.admin_tournament = self.admin_event.tournaments_by_id[admin_tournament_id]
            except KeyError:
                self._redirect_error(f'Le tournoi [{admin_tournament_id}] n\'existe pas')
                return
        if tournament_needed and not self.admin_tournament:
            self._redirect_error(f'Le tournoi n\'est pas spécifié')
            return

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'admin_tournament': self.admin_tournament,
        }


class TournamentAdminController(AbstractAdminController):

    @staticmethod
    def _admin_validate_tournament_update_data(
            action: str,
            web_context: TournamentAdminWebContext,
            data: dict[str, str] | None = None,
    ) -> StoredTournament:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        uniq_id: str = WebContext.form_data_to_str(data, 'uniq_id')
        if action == 'delete':
            if not uniq_id:
                errors['uniq_id'] = 'Veuillez entrer l\'identifiant du tournoi.'
            elif uniq_id != web_context.admin_tournament.uniq_id:
                errors['uniq_id'] = f'L\'identifiant entré n\'est pas valide.'
        else:
            if not uniq_id:
                errors['uniq_id'] = 'Veuillez entrer l\'identifiant du tournoi.'
            elif uniq_id.find('/') != -1:
                errors['uniq_id'] = "le caractère « / » n\'est pas autorisé"
            else:
                match action:
                    case 'create' | 'clone':
                        if uniq_id in web_context.admin_event.tournaments_by_uniq_id:
                            errors['uniq_id'] = f'Le tournoi [{uniq_id}] existe déjà.'
                    case 'update':
                        if uniq_id != web_context.admin_tournament.uniq_id \
                                and uniq_id in web_context.admin_event.tournaments_by_uniq_id:
                            errors['uniq_id'] = f'Le tournoi [{uniq_id}] existe déjà.'
                    case _:
                        raise ValueError(f'action=[{action}]')
        name: str | None = None
        path: str | None = None
        filename: str | None = None
        ffe_id: int | None = None
        ffe_password: str | None = None
        match action:
            case 'create' | 'update' | 'clone':
                name = WebContext.form_data_to_str(data, 'name')
                if not name:
                    errors['name'] = 'Veuillez entrer le nom du tournoi.'
                path = WebContext.form_data_to_str(data, 'path')
                filename = WebContext.form_data_to_str(data, 'filename')
                try:
                    ffe_id = WebContext.form_data_to_int(data, 'ffe_id')
                except ValueError:
                    errors['ffe_id'] = 'L\'identifiant FFE est un entier positif.'
                ffe_password = WebContext.form_data_to_str(data, 'ffe_password')
                if ffe_password and not re.match('^[A-Z]{10}$', ffe_password):
                    errors['ffe_password'] = \
                        'Le mot de passe du tournoi sur le site FFE doit être composé de 10 lettres majuscules.'
            case 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        time_control_initial_time: int | None = None
        time_control_increment: int | None = None
        time_control_handicap_penalty_value: int | None = None
        time_control_handicap_penalty_step: int | None = None
        time_control_handicap_min_time: int | None = None
        chessevent_id: int | None = None
        chessevent_tournament_name: str | None = None
        record_illegal_moves: int | None = None
        match action:
            case 'update':
                time_control_initial_time = WebContext.form_data_to_int(data, 'time_control_initial_time')
                time_control_increment = WebContext.form_data_to_int(data, 'time_control_increment')
                time_control_handicap_penalty_value = WebContext.form_data_to_int(
                    data, 'time_control_handicap_penalty_value')
                time_control_handicap_penalty_step = WebContext.form_data_to_int(
                    data, 'time_control_handicap_penalty_step')
                time_control_handicap_min_time = WebContext.form_data_to_int(
                    data, 'time_control_handicap_min_time')
                chessevent_id = WebContext.form_data_to_int(data, 'chessevent_id')
                chessevent_tournament_name = WebContext.form_data_to_str(data, 'chessevent_tournament_name')
                record_illegal_moves = WebContext.form_data_to_str(data, 'record_illegal_moves')
            case 'delete' | 'create' | 'clone':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        return StoredTournament(
            id=web_context.admin_tournament.id if action != 'create' else None,
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

    @staticmethod
    def _get_chessevent_options(admin_event: Event) -> dict[str, str]:
        options: dict[str, str] = {
            '': 'Pas de connexion à ChessEvent',
        }
        for chessevent in admin_event.chessevents_by_id.values():
            options[str(chessevent.id)] = (f' {chessevent.uniq_id} ({chessevent.user_id}'
                                           f'/{chessevent.shadowed_password}/{chessevent.event_id})')
        return options

    def _admin_tournament_render_edit_modal(
            self,
            action: str,
            web_context: TournamentAdminWebContext,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        if data is None:
            data = {}
            match action:
                case 'update':
                    data['uniq_id'] = WebContext.value_to_form_data(
                        web_context.admin_tournament.stored_tournament.uniq_id)
                case 'create' | 'clone':
                    data['uniq_id'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            match action:
                case 'update' | 'clone':
                    data['name'] = WebContext.value_to_form_data(web_context.admin_tournament.stored_tournament.name)
                    data['path'] = WebContext.value_to_form_data(web_context.admin_tournament.stored_tournament.path)
                    data['filename'] = WebContext.value_to_form_data(
                        web_context.admin_tournament.stored_tournament.filename)
                    data['ffe_id'] = WebContext.value_to_form_data(
                        web_context.admin_tournament.stored_tournament.ffe_id)
                    data['ffe_password'] = WebContext.value_to_form_data(
                        web_context.admin_tournament.stored_tournament.ffe_password)
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
                    data['time_control_initial_time'] = WebContext.value_to_form_data(
                        web_context.admin_tournament.stored_tournament.time_control_initial_time)
                    data['time_control_increment'] = WebContext.value_to_form_data(
                        web_context.admin_tournament.stored_tournament.time_control_increment)
                    data['time_control_handicap_penalty_value'] = WebContext.value_to_form_data(
                        web_context.admin_tournament.stored_tournament.time_control_handicap_penalty_value)
                    data['time_control_handicap_penalty_step'] = WebContext.value_to_form_data(
                        web_context.admin_tournament.stored_tournament.time_control_handicap_penalty_step)
                    data['time_control_handicap_min_time'] = WebContext.value_to_form_data(
                        web_context.admin_tournament.stored_tournament.time_control_handicap_min_time)
                    data['chessevent_id'] = WebContext.value_to_form_data(
                        web_context.admin_tournament.stored_tournament.chessevent_id)
                    data['chessevent_tournament_name'] = WebContext.value_to_form_data(
                        web_context.admin_tournament.stored_tournament.chessevent_tournament_name)
                    data['record_illegal_moves'] = WebContext.value_to_form_data(
                        web_context.admin_tournament.stored_tournament.record_illegal_moves)
                case 'delete' | 'clone' | 'create':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            stored_tournament: StoredTournament = self._admin_validate_tournament_update_data(
                action, web_context, data)
            errors = stored_tournament.errors
        if errors is None:
            errors = {}
        return HTMXTemplate(
            template_name='admin_tournament_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context=web_context.template_context | {
                'action': action,
                'chessevent_options': self._get_chessevent_options(web_context.admin_event),
                'data': data,
                'record_illegal_moves_options': self._get_record_illegal_moves_options(
                    web_context.admin_event.record_illegal_moves),
                'errors': errors,
            })

    @post(
        path='/admin-tournament-render-edit-modal',
        name='admin-tournament-render-edit-modal'
    )
    async def htmx_admin_tournament_render_edit_modal(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        action: str = WebContext.form_data_to_str(data, 'action')
        web_context: TournamentAdminWebContext
        match action:
            case 'update' | 'delete' | 'clone':
                web_context = TournamentAdminWebContext(request, data, True)
            case 'create':
                web_context = TournamentAdminWebContext(request, data, False)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        return self._admin_tournament_render_edit_modal(action, web_context)

    @post(
        path='/admin-tournament-update',
        name='admin-tournament-update'
    )
    async def htmx_admin_tournament_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        action: str = WebContext.form_data_to_str(data, 'action')
        if action == 'close':
            web_context: EventAdminWebContext = EventAdminWebContext(request, data, True)
            if web_context.error:
                return web_context.error
            return self._admin_render_index(web_context)
        match action:
            case 'update' | 'delete' | 'clone':
                web_context: TournamentAdminWebContext = TournamentAdminWebContext(request, data, True)
            case 'create':
                web_context: TournamentAdminWebContext = TournamentAdminWebContext(request, data, False)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        stored_tournament: StoredTournament | None = self._admin_validate_tournament_update_data(
            action, web_context, data)
        if stored_tournament.errors:
            return self._admin_tournament_render_edit_modal(action, web_context, data, stored_tournament.errors)
        with (EventDatabase(web_context.admin_event.uniq_id, write=True) as event_database):
            match action:
                case 'update':
                    stored_tournament = event_database.update_stored_tournament(stored_tournament)
                    Message.success(request, f'Le tournoi [{stored_tournament.uniq_id}] a été modifié.')
                    stored_tournament = None
                case 'create':
                    stored_tournament = event_database.add_stored_tournament(stored_tournament)
                    Message.success(request, f'Le tournoi [{stored_tournament.uniq_id}] a été créé.')
                case 'delete':
                    event_database.delete_stored_tournament(web_context.admin_tournament.id)
                    Message.success(request, f'Le tournoi [{web_context.admin_tournament.uniq_id}] a été supprimé.')
                    stored_tournament = None
                case 'clone':
                    stored_tournament = event_database.clone_stored_tournament(
                        web_context.admin_tournament.id, stored_tournament.uniq_id, stored_tournament.name,
                        stored_tournament.path, stored_tournament.filename, stored_tournament.ffe_id,
                        stored_tournament.ffe_password, )
                    Message.success(
                        request, f'Le tournoi [{web_context.admin_tournament.uniq_id}] a été dupliqué '
                                 f'([{stored_tournament.uniq_id}]).')
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=False)
        web_context.set_admin_event(event_loader.reload_event(web_context.admin_event.uniq_id))
        if stored_tournament:
            web_context.admin_tournament = web_context.admin_event.tournaments_by_id[stored_tournament.id]
            return self._admin_tournament_render_edit_modal('update', web_context)
        else:
            return self._admin_render_index(web_context)

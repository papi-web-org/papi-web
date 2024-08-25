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
from data.family import NewFamily
from data.event import NewEvent
from data.loader import EventLoader
from data.util import ScreenType
from database.sqlite import EventDatabase
from database.store import StoredFamily
from web.messages import Message
from web.views_admin_index import AAdminController

logger: Logger = get_logger()


class AdminFamilyController(AAdminController):

    def _admin_validate_family_update_data(
            self,
            action: str,
            admin_event: NewEvent,
            admin_family: NewFamily,
            data: dict[str, str] | None = None,
    ) -> StoredFamily:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        type: str
        field: str = 'type'
        match action:
            case 'create':
                type = self._form_data_to_str_or_none(data, field)
                match type:
                    case 'boards' | 'input' | 'players':
                        pass
                    case None:
                        errors[field] = 'Veuillez choisir le type de famille.'
                    case _:
                        raise ValueError(f'type=[{type}]')
            case 'update' | 'delete':
                type = admin_family.stored_family.type
            case _:
                raise ValueError(f'action=[{action}]')
        field = 'uniq_id'
        uniq_id: str = self._form_data_to_str_or_none(data, field)
        name: str | None = None
        public: bool | None = None
        if action == 'delete':
            pass
        else:
            if not uniq_id:
                errors[field] = 'Veuillez entrer l\'identifiant de la famille.'
            else:
                match action:
                    case 'create':
                        if uniq_id in admin_event.families_by_uniq_id:
                            errors[field] = f'La famille [{uniq_id}] existe déjà.'
                    case 'update':
                        if uniq_id != admin_family.uniq_id and uniq_id in admin_event.families_by_uniq_id:
                            errors[field] = f'La famille [{uniq_id}] existe déjà.'
                    case _:
                        raise ValueError(f'action=[{action}]')
            name = self._form_data_to_str_or_none(data, 'name')
            public: bool = self._form_data_to_bool_or_none(data, 'public')
        menu: str | None = None
        menu_text: str | None = None
        columns: int | None = None
        timer_id: int | None = None
        players_show_unpaired: bool | None = None
        tournament_id: int | None = None
        first: int | None = None
        last: int | None = None
        parts: int | None = None
        number: int | None = None
        match action:
            case 'delete':
                pass
            case 'create' | 'update':
                field: str = 'tournament_id'
                try:
                    if len(admin_event.tournaments_by_id) == 1:
                        tournament_id = list(admin_event.tournaments_by_id.keys())[0]
                        data[field] = self._value_to_form_data(tournament_id)
                    else:
                        tournament_id = self._form_data_to_int_or_none(data, field)
                        if not tournament_id:
                            errors[field] = f'Veuillez indiquer le tournoi.'
                        elif tournament_id not in admin_event.tournaments_by_id:
                            errors[field] = f'Le tournoi [{tournament_id}] n\'existe pas.'
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
            case _:
                raise ValueError(f'action=[{action}]')
        match action:
            case 'create' | 'delete':
                pass
            case 'update':
                field = 'columns'
                try:
                    columns = self._form_data_to_int_or_none(data, field, minimum=1)
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
                menu_text = self._form_data_to_str_or_none(data, 'menu_text')
                menu = self._form_data_to_str_or_none(data, 'menu')
                field = 'timer_id'
                try:
                    timer_id = self._form_data_to_int_or_none(data, field)
                    if timer_id and timer_id not in admin_event.timers_by_id:
                        errors[field] = f'Le chronomètre [{timer_id}] n\'existe pas.'
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
                match type:
                    case 'boards' | 'input':
                        field: str = 'first'
                        try:
                            first = self._form_data_to_int_or_none(data, field, minimum=1)
                        except ValueError:
                            errors[field] = 'Un entier positif est attendu.'
                        field: str = 'last'
                        try:
                            last = self._form_data_to_int_or_none(data, field, minimum=1)
                        except ValueError:
                            errors[field] = 'Un entier positif est attendu.'
                        if first and last and first > last:
                            error: str = f'Les nombres {first} et {last} ne sont pas compatibles ({first} > {last}).'
                            errors['first'] = error
                            errors['last'] = error
                    case 'players':
                        players_show_unpaired = self._form_data_to_bool_or_none(data, 'players_show_unpaired')
                    case _:
                        raise ValueError(f'type=[{type}]')
                field: str = 'tournament_id'
                try:
                    tournament_id = self._form_data_to_int_or_none(data, field)
                    if not tournament_id:
                        errors[field] = f'Veuillez indiquer le tournoi.'
                    elif tournament_id not in admin_event.tournaments_by_id:
                        errors[field] = f'Le tournoi [{tournament_id}] n\'existe pas.'
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
                field: str = 'parts'
                try:
                    parts = self._form_data_to_int_or_none(data, field, minimum=1)
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
                field: str = 'number'
                try:
                    number = self._form_data_to_int_or_none(data, field, minimum=1)
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
                if parts and number:
                    error: str = 'Les découpages en un nombre de parties et un nombre d\'éléments ne sont pas ' \
                                 'compatibles.'
                    errors['parts'] = error
                    errors['number'] = error
            case _:
                raise ValueError(f'action=[{action}]')
        return StoredFamily(
            id=admin_family.id if action != 'create' else None,
            uniq_id=uniq_id,
            type=type,
            public=public,
            tournament_id=tournament_id,
            name=name,
            columns=columns,
            menu_text=menu_text,
            menu=menu,
            timer_id=timer_id,
            players_show_unpaired=players_show_unpaired,
            first=first,
            last=last,
            parts=parts,
            number=number,
            errors=errors,
        )

    @staticmethod
    def _get_tournament_options(admin_event: NewEvent) -> dict[str, str]:
        options: dict[str, str] = {
        }
        for tournament in admin_event.tournaments_by_id.values():
            options[str(tournament.id)] = f'{tournament.name} ({tournament.filename})'
        return options

    def _admin_family_render_edit_modal(
            self, action: str,
            admin_event: NewEvent,
            admin_family: NewFamily | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        if data is None:
            data: dict[str, str] = {}
            match action:
                case 'update':
                    data['uniq_id'] = self._value_to_form_data(admin_family.stored_family.uniq_id)
                case 'create' | 'clone':
                    data['uniq_id'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            match action:
                case 'update':
                    data['public'] = self._value_to_form_data(admin_family.stored_family.public)
                    data['name'] = self._value_to_form_data(admin_family.stored_family.name)
                    data['tournament_id'] = self._value_to_form_data(admin_family.stored_family.tournament_id)
                    data['columns'] = self._value_to_form_data(admin_family.stored_family.columns)
                    data['menu_text'] = self._value_to_form_data(admin_family.stored_family.menu_text)
                    data['menu'] = self._value_to_form_data(admin_family.stored_family.menu)
                    data['timer_id'] = self._value_to_form_data(admin_family.stored_family.timer_id)
                    match admin_family.type:
                        case ScreenType.Boards | ScreenType.Input:
                            data['first'] = self._value_to_form_data(admin_family.stored_family.first)
                            data['last'] = self._value_to_form_data(admin_family.stored_family.last)
                        case ScreenType.Players:
                            data['players_show_unpaired'] = self._value_to_form_data(
                                admin_family.stored_family.players_show_unpaired)
                        case _:
                            raise ValueError(f'type=[{admin_family.type}]')
                    data['parts'] = self._value_to_form_data(admin_family.stored_family.parts)
                    data['number'] = self._value_to_form_data(admin_family.stored_family.number)
                case 'create':
                    data['type'] = ''
                    data['public'] = self._value_to_form_data(True)
                    data['uniq_id'] = ''
                    data['name'] = ''
                    data['tournament_id'] = self._value_to_form_data(list(admin_event.tournaments_by_id.keys())[0])
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            stored_family: StoredFamily = self._admin_validate_family_update_data(
                action, admin_event, admin_family, data)
            errors = stored_family.errors
        if errors is None:
            errors = {}
        return HTMXTemplate(
            template_name='admin_family_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'papi_web_config': PapiWebConfig(),
                'action': action,
                'admin_event': admin_event,
                'admin_family': admin_family,
                'data': data,
                'tournament_options': self._get_tournament_options(admin_event),
                'screen_type_options': self._get_screen_type_options(results_screen_allowed=False),
                'timer_options': self._get_timer_options(admin_event),
                'players_show_unpaired_options': self._get_players_show_unpaired_options(),
                'errors': errors,
            })

    @post(
        path='/admin-family-render-edit-modal',
        name='admin-family-render-edit-modal'
    )
    async def htmx_admin_family_render_edit_modal(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        event_loader: EventLoader = EventLoader()
        action: str = self._form_data_to_str_or_none(data, 'action')
        admin_event_uniq_id: str = self._form_data_to_str_or_none(data, 'admin_event_uniq_id')
        try:
            admin_event: NewEvent = event_loader.load_event(admin_event_uniq_id)
        except PapiWebException as pwe:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : [{pwe}].')
            return self._render_messages(request)
        admin_family: NewFamily | None = None
        match action:
            case 'update' | 'delete':
                admin_family_id: int = self._form_data_to_int_or_none(data, 'admin_family_id')
                try:
                    admin_family = admin_event.families_by_id[admin_family_id]
                except KeyError:
                    Message.error(request, f'La famille [{admin_family_id}] est introuvable.')
                    return self._render_messages(request)
            case 'create':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        return self._admin_family_render_edit_modal(action, admin_event, admin_family)

    @post(
        path='/admin-family-update',
        name='admin-family-update'
    )
    async def htmx_admin_family_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
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
                request, event_loader, admin_event=admin_event, admin_event_selector='@families')
        admin_family: NewFamily | None = None
        match action:
            case 'update' | 'delete':
                admin_screen_id: int = self._form_data_to_int_or_none(data, 'admin_family_id')
                try:
                    admin_family = admin_event.families_by_id[admin_screen_id]
                except KeyError:
                    Message.error(request, f'La famille [{admin_screen_id}] est introuvable.')
                    return self._render_messages(request)
            case 'create':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        stored_family: StoredFamily = self._admin_validate_family_update_data(action, admin_event, admin_family, data)
        if stored_family.errors:
            return self._admin_family_render_edit_modal(action, admin_event, admin_family, data, stored_family.errors)
        next_family_id: int | None = None
        next_action: str | None = None
        with (EventDatabase(admin_event.uniq_id, write=True) as event_database):
            match action:
                case 'update':
                    stored_family = event_database.update_stored_family(stored_family)
                    Message.success(request, f'La famille [{stored_family.uniq_id}] a été modifiée.')
                case 'create':
                    stored_family = event_database.add_stored_family(stored_family)
                    Message.success(request, f'La famille [{stored_family.uniq_id}] a été créée.')
                    next_family_id = stored_family.id
                    next_action = 'update'
                case 'delete':
                    event_database.delete_stored_family(admin_family.id)
                    Message.success(request, f'La famille [{admin_family.uniq_id}] a été supprimée.')
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        admin_event = event_loader.load_event(admin_event.uniq_id, reload=True)
        if next_family_id:
            admin_family = admin_event.families_by_id[next_family_id]
            return self._admin_family_render_edit_modal(next_action, admin_event, admin_family)
        else:
            return self._admin_render_index(
                request, event_loader, admin_event=admin_event, admin_event_selector='@families')

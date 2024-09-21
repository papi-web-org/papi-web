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
from data.family import Family
from data.loader import EventLoader
from data.util import ScreenType
from database.sqlite import EventDatabase
from database.store import StoredFamily
from web.messages import Message
from web.controllers.index_controller import WebContext
from web.controllers.admin.index_admin_controller import AbstractAdminController
from web.controllers.admin.event_admin_controller import EventAdminWebContext

logger: Logger = get_logger()


class FamilyAdminWebContext(EventAdminWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
            family_needed: bool,
    ):
        super().__init__(request, data, lazy_load, True)
        self.admin_family: Family | None = None
        field: str = 'admin_family_id'
        if field in self.data:
            try:
                admin_family_id: int | None = self._form_data_to_int(field, minimum=1)
            except ValueError as ve:
                self._redirect_error(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
                return
            try:
                self.admin_family = self.admin_event.families_by_id[admin_family_id]
            except KeyError:
                self._redirect_error(f'La famille [{admin_family_id}] n\'existe pas')
                return
        if family_needed and not self.admin_family:
            self._redirect_error(f'La famille n\'est pas spécifiée')
            return

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'admin_family': self.admin_family,
        }


class FamilyAdminController(AbstractAdminController):

    @staticmethod
    def _admin_validate_family_update_data(
            action: str,
            web_context: FamilyAdminWebContext,
            data: dict[str, str] | None = None,
    ) -> StoredFamily:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        type: str
        field: str = 'type'
        match action:
            case 'create':
                type = WebContext.form_data_to_str(data, field)
                match type:
                    case 'boards' | 'input' | 'players':
                        pass
                    case None:
                        errors[field] = 'Veuillez choisir le type de famille.'
                    case _:
                        raise ValueError(f'type=[{type}]')
            case 'update' | 'delete' | 'clone':
                type = web_context.admin_family.stored_family.type
            case _:
                raise ValueError(f'action=[{action}]')
        field = 'uniq_id'
        uniq_id: str = WebContext.form_data_to_str(data, field)
        name: str | None = None
        public: bool | None = None
        if action in ['delete', 'clone', ]:
            pass
        else:
            if not uniq_id:
                errors[field] = 'Veuillez entrer l\'identifiant de la famille.'
            else:
                match action:
                    case 'create':
                        if uniq_id in web_context.admin_event.families_by_uniq_id:
                            errors[field] = f'La famille [{uniq_id}] existe déjà.'
                    case 'update':
                        if uniq_id != web_context.admin_family.uniq_id \
                                and uniq_id in web_context.admin_event.families_by_uniq_id:
                            errors[field] = f'La famille [{uniq_id}] existe déjà.'
                    case _:
                        raise ValueError(f'action=[{action}]')
            name = WebContext.form_data_to_str(data, 'name')
            public: bool = WebContext.form_data_to_bool(data, 'public')
        menu_link: bool | None = None
        menu_text: str | None = None
        menu: str | None = None
        columns: int | None = None
        timer_id: int | None = None
        players_show_unpaired: bool | None = None
        tournament_id: int | None = None
        first: int | None = None
        last: int | None = None
        parts: int | None = None
        number: int | None = None
        match action:
            case 'delete' | 'clone':
                pass
            case 'create' | 'update':
                field: str = 'tournament_id'
                try:
                    if len(web_context.admin_event.tournaments_by_id) == 1:
                        tournament_id = list(web_context.admin_event.tournaments_by_id.keys())[0]
                        data[field] = WebContext.value_to_form_data(tournament_id)
                    else:
                        tournament_id = WebContext.form_data_to_int(data, field)
                        if not tournament_id:
                            errors[field] = f'Veuillez indiquer le tournoi.'
                        elif tournament_id not in web_context.admin_event.tournaments_by_id:
                            errors[field] = f'Le tournoi [{tournament_id}] n\'existe pas.'
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
            case _:
                raise ValueError(f'action=[{action}]')
        match action:
            case 'create':
                menu_link = True
                menu_text = ''
                menu = ''
            case 'delete' | 'clone':
                pass
            case 'update':
                field = 'columns'
                try:
                    columns = WebContext.form_data_to_int(data, field, minimum=1)
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
                menu_link = WebContext.form_data_to_bool(data, 'menu_link', False)
                menu_text = WebContext.form_data_to_str(data, 'menu_text', '')
                menu = WebContext.form_data_to_str(data, 'menu', '')
                field = 'timer_id'
                try:
                    timer_id = WebContext.form_data_to_int(data, field)
                    if timer_id and timer_id not in web_context.admin_event.timers_by_id:
                        errors[field] = f'Le chronomètre [{timer_id}] n\'existe pas.'
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
                field: str = 'first'
                try:
                    first = WebContext.form_data_to_int(data, field, minimum=1)
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
                field: str = 'last'
                try:
                    last = WebContext.form_data_to_int(data, field, minimum=1)
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
                if first and last and first > last:
                    error: str = f'Les nombres {first} et {last} ne sont pas compatibles ({first} > {last}).'
                    errors['first'] = error
                    errors['last'] = error
                match type:
                    case 'boards' | 'input':
                        pass
                    case 'players':
                        players_show_unpaired = WebContext.form_data_to_bool(data, 'players_show_unpaired')
                    case _:
                        raise ValueError(f'type=[{type}]')
                field: str = 'tournament_id'
                try:
                    tournament_id = WebContext.form_data_to_int(data, field)
                    if not tournament_id:
                        errors[field] = f'Veuillez indiquer le tournoi.'
                    elif tournament_id not in web_context.admin_event.tournaments_by_id:
                        errors[field] = f'Le tournoi [{tournament_id}] n\'existe pas.'
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
                field: str = 'parts'
                try:
                    parts = WebContext.form_data_to_int(data, field, minimum=1)
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
                field: str = 'number'
                try:
                    number = WebContext.form_data_to_int(data, field, minimum=1)
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
            id=web_context.admin_family.id if action != 'create' else None,
            uniq_id=uniq_id,
            type=type,
            public=public,
            tournament_id=tournament_id,
            name=name,
            columns=columns,
            menu_link=menu_link,
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
    def _get_tournament_options(admin_event: Event) -> dict[str, str]:
        options: dict[str, str] = {
        }
        for tournament in admin_event.tournaments_by_id.values():
            options[str(tournament.id)] = f'{tournament.name} ({tournament.filename})'
        return options

    def _admin_family_render_edit_modal(
            self, action: str,
            web_context: FamilyAdminWebContext,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        if data is None:
            data: dict[str, str] = {}
            match action:
                case 'update':
                    data['uniq_id'] = WebContext.value_to_form_data(web_context.admin_family.stored_family.uniq_id)
                case 'create' | 'clone':
                    data['uniq_id'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            match action:
                case 'update':
                    data['public'] = WebContext.value_to_form_data(web_context.admin_family.stored_family.public)
                    data['name'] = WebContext.value_to_form_data(web_context.admin_family.stored_family.name)
                    data['tournament_id'] = WebContext.value_to_form_data(
                        web_context.admin_family.stored_family.tournament_id)
                    data['columns'] = WebContext.value_to_form_data(web_context.admin_family.stored_family.columns)
                    data['menu_link'] = WebContext.value_to_form_data(web_context.admin_family.stored_family.menu_link)
                    data['menu_text'] = WebContext.value_to_form_data(web_context.admin_family.stored_family.menu_text)
                    data['menu'] = WebContext.value_to_form_data(web_context.admin_family.stored_family.menu)
                    data['timer_id'] = WebContext.value_to_form_data(web_context.admin_family.stored_family.timer_id)
                    data['first'] = WebContext.value_to_form_data(web_context.admin_family.stored_family.first)
                    data['last'] = WebContext.value_to_form_data(web_context.admin_family.stored_family.last)
                    match web_context.admin_family.type:
                        case ScreenType.Boards | ScreenType.Input:
                            pass
                        case ScreenType.Players:
                            data['players_show_unpaired'] = WebContext.value_to_form_data(
                                web_context.admin_family.stored_family.players_show_unpaired)
                        case _:
                            raise ValueError(f'type=[{web_context.admin_family.type}]')
                    data['parts'] = WebContext.value_to_form_data(web_context.admin_family.stored_family.parts)
                    data['number'] = WebContext.value_to_form_data(web_context.admin_family.stored_family.number)
                case 'create':
                    data['type'] = ''
                    data['public'] = WebContext.value_to_form_data(True)
                    data['uniq_id'] = ''
                    data['name'] = ''
                    data['tournament_id'] = WebContext.value_to_form_data(list(
                        web_context.admin_event.tournaments_by_id.keys())[0])
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            stored_family: StoredFamily = self._admin_validate_family_update_data(
                action, web_context, data)
            errors = stored_family.errors
        if errors is None:
            errors = {}
        return HTMXTemplate(
            template_name='admin_family_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context=web_context.template_context | {
                'action': action,
                'data': data,
                'tournament_options': self._get_tournament_options(web_context.admin_event),
                'screen_type_options': self._get_screen_type_options(family_screens_only=True),
                'timer_options': self._get_timer_options(web_context.admin_event),
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
        action: str = WebContext.form_data_to_str(data, 'action')
        web_context: FamilyAdminWebContext
        match action:
            case 'update' | 'delete':
                web_context = FamilyAdminWebContext(request, data, True, True)
            case 'create':
                web_context = FamilyAdminWebContext(request, data, True, False)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        return self._admin_family_render_edit_modal(action, web_context)

    @post(
        path='/admin-family-update',
        name='admin-family-update'
    )
    async def htmx_admin_family_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        action: str = WebContext.form_data_to_str(data, 'action')
        if action == 'close':
            web_context: EventAdminWebContext = EventAdminWebContext(request, data, True, True)
            if web_context.error:
                return web_context.error
            return self._admin_render_index(web_context)
        match action:
            case 'update' | 'delete' | 'clone':
                web_context: FamilyAdminWebContext = FamilyAdminWebContext(request, data, True, True)
            case 'create':
                web_context: FamilyAdminWebContext = FamilyAdminWebContext(request, data, True, False)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        stored_family: StoredFamily = self._admin_validate_family_update_data(action, web_context, data)
        if stored_family.errors:
            return self._admin_family_render_edit_modal(action, web_context, data, stored_family.errors)
        next_family_id: int | None = None
        next_action: str | None = None
        with (EventDatabase(web_context.admin_event.uniq_id, write=True) as event_database):
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
                    event_database.delete_stored_family(web_context.admin_family.id)
                    Message.success(request, f'La famille [{web_context.admin_family.uniq_id}] a été supprimée.')
                case 'clone':
                    stored_family = event_database.clone_stored_family(web_context.admin_family.id)
                    Message.success(
                        request,
                        f'La famille [{web_context.admin_family.uniq_id}] a été dupliquée '
                        f'([{stored_family.uniq_id}]).')
                    next_family_id = stored_family.id
                    next_action = 'update'
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        web_context.set_admin_event(event_loader.reload_event(web_context.admin_event.uniq_id))
        if next_family_id:
            web_context.admin_family = web_context.admin_event.families_by_id[next_family_id]
            return self._admin_family_render_edit_modal(next_action, web_context)
        else:
            return self._admin_render_index(web_context)

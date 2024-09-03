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
from data.screen import NewScreen
from data.screen_set import NewScreenSet
from data.event import NewEvent
from data.loader import EventLoader
from data.util import ScreenType
from database.sqlite import EventDatabase
from database.store import StoredScreen, StoredScreenSet
from web.messages import Message
from web.views_admin import AAdminController

logger: Logger = get_logger()


class AdminScreenController(AAdminController):

    def _admin_validate_screen_update_data(
            self,
            action: str,
            admin_event: NewEvent,
            admin_screen: NewScreen,
            data: dict[str, str] | None = None,
    ) -> StoredScreen:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        type: str
        field: str = 'type'
        match action:
            case 'create':
                type = self._form_data_to_str_or_none(data, field)
                match type:
                    case 'boards' | 'input' | 'players' | 'results':
                        pass
                    case None:
                        errors[field] = 'Veuillez choisir le type d\'écran.'
                    case _:
                        raise ValueError(f'type=[{type}]')
            case 'update' | 'clone' | 'delete':
                type = admin_screen.stored_screen.type
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
                errors[field] = 'Veuillez entrer l\'identifiant de l\'écran.'
            elif ':' in uniq_id:
                errors[field] = 'Le caractère [:] est interdit.'
            else:
                match action:
                    case 'create' | 'clone':
                        if uniq_id in admin_event.screens_by_uniq_id:
                            errors[field] = f'L\'écran [{uniq_id}] existe déjà.'
                    case 'update':
                        if uniq_id != admin_screen.uniq_id and uniq_id in admin_event.screens_by_uniq_id:
                            errors[field] = f'L\'écran [{uniq_id}] existe déjà.'
                    case _:
                        raise ValueError(f'action=[{action}]')
            name = self._form_data_to_str_or_none(data, 'name')
            public = self._form_data_to_bool_or_none(data, 'public')
        menu: str | None = None
        menu_text: str | None = None
        columns: int | None = None
        timer_id: int | None = None
        players_show_unpaired: bool | None = None
        results_limit: int | None = None
        results_tournament_ids: list[int] | None = None
        match action:
            case 'create' | 'delete' | 'clone':
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
                match admin_screen.type:
                    case ScreenType.Boards | ScreenType.Input:
                        pass
                    case ScreenType.Players:
                        players_show_unpaired = self._form_data_to_bool_or_none(data, 'players_show_unpaired')
                    case ScreenType.Results:
                        field = 'results_limit'
                        try:
                            results_limit = self._form_data_to_int_or_none(data, field)
                        except ValueError:
                            errors[field] = 'Un entier positif est attendu.'
                        results_tournament_ids = []
                        for tournament_id in admin_event.tournaments_by_id:
                            field = f'results_tournament_{tournament_id}'
                            if self._form_data_to_bool_or_none(data, field):
                                results_tournament_ids.append(tournament_id)
                    case _:
                        raise ValueError(f'type=[{admin_screen.type}]')
            case _:
                raise ValueError(f'action=[{action}]')
        return StoredScreen(
            id=admin_screen.id if action != 'create' else None,
            uniq_id=uniq_id,
            type=type,
            public=public,
            name=name,
            columns=columns,
            menu_text=menu_text,
            menu=menu,
            timer_id=timer_id,
            players_show_unpaired=players_show_unpaired,
            results_limit=results_limit,
            results_tournament_ids=results_tournament_ids,
            errors=errors,
        )

    def _admin_screen_render_edit_modal(
            self, action: str,
            admin_event: NewEvent,
            admin_screen: NewScreen | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        if data is None:
            data: dict[str, str] = {}
            match action:
                case 'update':
                    data['uniq_id'] = self._value_to_form_data(admin_screen.stored_screen.uniq_id)
                case 'create' | 'clone':
                    data['uniq_id'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            match action:
                case 'update' | 'clone':
                    data['public'] = self._value_to_form_data(admin_screen.stored_screen.public)
                    data['name'] = self._value_to_form_data(admin_screen.stored_screen.name)
                    data['columns'] = self._value_to_form_data(admin_screen.stored_screen.columns)
                    data['menu_text'] = self._value_to_form_data(admin_screen.stored_screen.menu_text)
                    data['menu'] = self._value_to_form_data(admin_screen.stored_screen.menu)
                    data['timer_id'] = self._value_to_form_data(admin_screen.stored_screen.timer_id)
                    match admin_screen.type:
                        case ScreenType.Boards | ScreenType.Input:
                            pass
                        case ScreenType.Players:
                            data['players_show_unpaired'] = self._value_to_form_data(
                                admin_screen.stored_screen.players_show_unpaired)
                        case ScreenType.Results:
                            data['results_limit'] = self._value_to_form_data(
                                admin_screen.stored_screen.results_limit)
                            for tournament_id in admin_event.tournaments_by_id:
                                data[f'results_tournament_{tournament_id}'] = self._value_to_form_data(
                                    tournament_id in admin_screen.stored_screen.results_tournament_ids)
                        case _:
                            raise ValueError(f'action={action}')
                case 'create':
                    data['type'] = ''
                    data['public'] = self._value_to_form_data(True)
                    data['uniq_id'] = ''
                    data['name'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            stored_screen: StoredScreen = self._admin_validate_screen_update_data(
                action, admin_event, admin_screen, data)
            errors = stored_screen.errors
        if errors is None:
            errors = {}
        return HTMXTemplate(
            template_name='admin_screen_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'papi_web_config': PapiWebConfig(),
                'action': action,
                'admin_event': admin_event,
                'admin_screen': admin_screen,
                'data': data,
                'screen_type_options': self._get_screen_type_options(results_screen_allowed=True),
                'timer_options': self._get_timer_options(admin_event),
                'players_show_unpaired_options': self._get_players_show_unpaired_options(),
                'errors': errors,
            })

    @post(
        path='/admin-screen-render-edit-modal',
        name='admin-screen-render-edit-modal'
    )
    async def htmx_admin_screen_render_edit_modal(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        action: str = self._form_data_to_str_or_none(data, 'action')
        admin_event_uniq_id: str = self._form_data_to_str_or_none(data, 'admin_event_uniq_id')
        try:
            admin_event: NewEvent = EventLoader.get(request=request, lazy_load=True).load_event(admin_event_uniq_id)
        except PapiWebException as pwe:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : [{pwe}].')
            return self._render_messages(request)
        admin_screen: NewScreen | None = None
        match action:
            case 'update' | 'delete' | 'clone':
                admin_screen_id: int = self._form_data_to_int_or_none(data, 'admin_screen_id')
                try:
                    admin_screen = admin_event.basic_screens_by_id[admin_screen_id]
                except KeyError:
                    Message.error(request, f'L\'écran [{admin_screen_id}] est introuvable.')
                    return self._render_messages(request)
            case 'create':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        return self._admin_screen_render_edit_modal(action, admin_event, admin_screen)

    @post(
        path='/admin-screen-update',
        name='admin-screen-update'
    )
    async def htmx_admin_screen_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        action: str = self._form_data_to_str_or_none(data, 'action')
        admin_event_uniq_id: str = self._form_data_to_str_or_none(data, 'admin_event_uniq_id')
        try:
            admin_event: NewEvent = event_loader.load_event(admin_event_uniq_id)
        except PapiWebException as pwe:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : [{pwe}].')
            return self._render_messages(request)
        if action == 'close':
            return self._admin_render_index(
                request, admin_event=admin_event, admin_event_selector='@screens')
        admin_screen: NewScreen | None = None
        match action:
            case 'update' | 'delete' | 'clone':
                admin_screen_id: int = self._form_data_to_int_or_none(data, 'admin_screen_id')
                try:
                    admin_screen = admin_event.basic_screens_by_id[admin_screen_id]
                except KeyError:
                    Message.error(request, f'L\'écran [{admin_screen_id}] est introuvable.')
                    return self._render_messages(request)
            case 'create':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        stored_screen: StoredScreen | None = self._admin_validate_screen_update_data(
            action, admin_event, admin_screen, data)
        if stored_screen.errors:
            return self._admin_screen_render_edit_modal(
                action, admin_event, admin_screen, data, stored_screen.errors)
        next_action: str | None = None
        next_screen_id: int | None = None
        next_screen_set_id: int | None = None
        with (EventDatabase(admin_event.uniq_id, write=True) as event_database):
            match action:
                case 'update':
                    stored_screen = event_database.update_stored_screen(stored_screen)
                    Message.success(request, f'L\'écran [{stored_screen.uniq_id}] a été modifié.')
                case 'create':
                    stored_screen = event_database.add_stored_screen(stored_screen)
                    if stored_screen.type in [ScreenType.Boards, ScreenType.Input, ScreenType.Players]:
                        event_database.add_stored_screen_set(
                            stored_screen.id, admin_event.tournaments_sorted_by_uniq_id[0].id)
                    Message.success(request, f'L\'écran [{stored_screen.uniq_id}] a été créé.')
                    next_screen_id = stored_screen.id
                    next_action = 'update'
                case 'delete':
                    event_database.delete_stored_screen(admin_screen.id)
                    Message.success(request, f'L\'écran [{admin_screen.uniq_id}] a été supprimé.')
                case 'clone':
                    stored_screen = event_database.clone_stored_screen(
                        admin_screen.id, stored_screen.uniq_id, self._form_data_to_str_or_none(data, 'name'))
                    Message.success(
                        request,
                        f'L\'écran [{admin_screen.uniq_id}] a été dupliqué ([{stored_screen.uniq_id}]).')
                    next_screen_id = stored_screen.id
                    next_action = 'update'
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        admin_event = event_loader.reload_event(admin_event.uniq_id)
        if next_screen_id:
            admin_screen = admin_event.basic_screens_by_id[next_screen_id]
            if next_screen_set_id:
                admin_screen_set = admin_screen.screen_sets_by_id[next_screen_set_id]
                return self._admin_screen_render_sets_modal(admin_event, admin_screen, admin_screen_set)
            else:
                return self._admin_screen_render_edit_modal(next_action, admin_event, admin_screen=admin_screen)
        else:
            return self._admin_render_index(request, admin_event=admin_event, admin_event_selector='@screens')

    def _admin_validate_screen_set_update_data(
            self,
            admin_screen: NewScreen,
            admin_screen_set: NewScreenSet,
            data: dict[str, str] | None = None,
    ) -> StoredScreenSet:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        tournament_id: int | None = None
        name: str | None
        first: int | None = None
        last: int | None = None
        field: str = 'name'
        name = self._form_data_to_str_or_none(data, field)
        field: str = 'tournament_id'
        try:
            if len(admin_screen.event.tournaments_by_id) == 1:
                tournament_id = list(admin_screen.event.tournaments_by_id.keys())[0]
                data[field] = self._value_to_form_data(tournament_id)
            else:
                tournament_id = self._form_data_to_int_or_none(data, field)
                if not tournament_id:
                    errors[field] = f'Veuillez indiquer le tournoi.'
                elif tournament_id not in admin_screen.event.tournaments_by_id:
                    errors[field] = f'Le tournoi [{tournament_id}] n\'existe pas.'
        except ValueError:
            errors[field] = 'Un entier positif est attendu.'
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
        fixed_boards_str: str | None = None
        if admin_screen.type in [ScreenType.Boards, ScreenType.Input]:
            fixed_boards_str = self._form_data_to_str_or_none(data, 'fixed_boards_str')
            if fixed_boards_str:
                for fixed_board_str in list(map(str.strip, fixed_boards_str.split(','))):
                    if fixed_board_str:
                        try:
                            int(fixed_board_str)
                        except ValueError:
                            errors['fixed_boards_str'] = f'Le numéro d\'échiquier {fixed_board_str} n\'est pas valide.'
                            break
        return StoredScreenSet(
            id=admin_screen_set.id,
            screen_id=admin_screen.id,
            name=name,
            tournament_id=tournament_id,
            order=admin_screen_set.order,
            fixed_boards_str=fixed_boards_str,
            first=first,
            last=last,
            errors=errors,
        )

    @staticmethod
    def _get_tournament_options(admin_event: NewEvent) -> dict[str, str]:
        options: dict[str, str] = {
        }
        for tournament in admin_event.tournaments_by_id.values():
            options[str(tournament.id)] = f'{tournament.name} ({tournament.filename})'
        return options

    def _admin_screen_render_sets_modal(
            self,
            admin_event: NewEvent,
            admin_screen: NewScreen | None,
            admin_screen_set: NewScreenSet | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        if data is None:
            if admin_screen_set:
                data = {
                    'tournament_id': self._value_to_form_data(admin_screen_set.stored_screen_set.tournament_id),
                    'fixed_boards_str': self._value_to_form_data(admin_screen_set.stored_screen_set.fixed_boards_str),
                    'name': self._value_to_form_data(admin_screen_set.stored_screen_set.name),
                    'first': self._value_to_form_data(admin_screen_set.stored_screen_set.first),
                    'last': self._value_to_form_data(admin_screen_set.stored_screen_set.last),
                }
                if admin_screen.type in [ScreenType.Boards, ScreenType.Input]:
                    data['fixed_boards_str'] = self._value_to_form_data(
                        admin_screen_set.stored_screen_set.fixed_boards_str)
                stored_screen_set = self._admin_validate_screen_set_update_data(admin_screen, admin_screen_set, data)
                errors = stored_screen_set.errors
            else:
                data = {}
        if errors is None:
            errors = {}
        return HTMXTemplate(
            template_name='admin_screen_sets_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'papi_web_config': PapiWebConfig(),
                'admin_event': admin_event,
                'admin_screen': admin_screen,
                'admin_screen_set': admin_screen_set,
                'tournament_options': self._get_tournament_options(admin_event),
                'data': data,
                'errors': errors,
            })

    @post(
        path='/admin-screen-render-sets-modal',
        name='admin-screen-render-sets-modal'
    )
    async def htmx_admin_screen_render_sets_modal(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str | list[int]], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        admin_event_uniq_id: str = self._form_data_to_str_or_none(data, 'admin_event_uniq_id')
        try:
            admin_event: NewEvent = event_loader.load_event(admin_event_uniq_id)
        except PapiWebException as pwe:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : [{pwe}].')
            return self._render_messages(request)
        admin_screen: NewScreen | None = None
        admin_screen_id: int = self._form_data_to_int_or_none(data, 'admin_screen_id')
        try:
            admin_screen = admin_event.basic_screens_by_id[admin_screen_id]
        except KeyError:
            Message.error(request, f'L\'écran [{admin_screen_id}] est introuvable.')
        admin_screen_set_id: int = self._form_data_to_int_or_none(data, 'admin_screen_set_id')
        if admin_screen_set_id:
            try:
                admin_screen_set: NewScreenSet = admin_screen.screen_sets_by_id[admin_screen_set_id]
            except KeyError:
                Message.error(request, f'L\'horaire [{admin_screen_set_id}] est introuvable.')
                return self._render_messages(request)
            return self._admin_screen_render_sets_modal(admin_event, admin_screen, admin_screen_set)
        return self._admin_screen_render_sets_modal(admin_event, admin_screen, None)

    @post(
        path='/admin-screen-sets-update',
        name='admin-screen-sets-update'
    )
    async def htmx_admin_screen_sets_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str | list[int]], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Reswap:
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        admin_event_uniq_id: str = self._form_data_to_str_or_none(data, 'admin_event_uniq_id')
        try:
            admin_event: NewEvent = event_loader.load_event(admin_event_uniq_id)
        except PapiWebException as pwe:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable : [{pwe}].')
            return self._render_messages(request)
        action: str = self._form_data_to_str_or_none(data, 'action')
        if action == 'close':
            return self._admin_render_index(request, admin_event=admin_event, admin_event_selector='@screens')
        match action:
            case 'delete' | 'clone' | 'update' | 'add' | 'reorder' | 'cancel':
                admin_screen_id: int = self._form_data_to_int_or_none(data, 'admin_screen_id')
                try:
                    admin_screen: NewScreen = admin_event.basic_screens_by_id[admin_screen_id]
                except KeyError:
                    Message.error(request, f'L\'écran [{admin_screen_id}] est introuvable.')
                    return self._render_messages(request)
            case _:
                raise ValueError(f'action=[{action}]')
        admin_screen_set: NewScreenSet | None = None
        match action:
            case 'delete' | 'clone' | 'update':
                admin_screen_set_id: int = self._form_data_to_int_or_none(data, 'admin_screen_set_id')
                try:
                    admin_screen_set = admin_screen.screen_sets_by_id[admin_screen_set_id]
                except KeyError:
                    Message.error(request, f'L\'ensemble [{admin_screen_set_id}] est introuvable.')
                    return self._render_messages(request)
            case 'add' | 'reorder' | 'cancel':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        match action:
            case 'delete':
                if len(admin_screen.screen_sets_sorted_by_order) <= 1:
                    Message.error(request, f'Le dernier ensemble d\'un écran ne peut être supprimé.')
                    return self._render_messages(request)
            case 'update' | 'clone' | 'add' | 'reorder' | 'cancel':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        next_screen_set_id: int | None = None
        with (EventDatabase(admin_event.uniq_id, write=True) as event_database):
            match action:
                case 'update':
                    stored_screen_set: StoredScreenSet = self._admin_validate_screen_set_update_data(
                        admin_screen, admin_screen_set, data)
                    if stored_screen_set.errors:
                        return self._admin_screen_render_sets_modal(
                            admin_event, admin_screen, admin_screen_set, data, stored_screen_set.errors)
                    event_database.update_stored_screen_set(stored_screen_set)
                case 'delete':
                    event_database.delete_stored_screen_set(admin_screen_set.id, admin_screen.id)
                case 'clone':
                    stored_screen_set = event_database.clone_stored_screen_set(admin_screen_set.id, admin_screen.id)
                    next_screen_set_id = stored_screen_set.id
                case 'add':
                    stored_screen_set = event_database.add_stored_screen_set(
                        admin_screen.id, list(admin_event.tournaments_by_id.keys())[0])
                    next_screen_set_id = stored_screen_set.id
                case 'reorder':
                    event_database.reorder_stored_screen_sets(admin_screen.id, data['item'])
                case 'cancel':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        admin_event = event_loader.reload_event(admin_event.uniq_id)
        admin_screen = admin_event.basic_screens_by_id[admin_screen.id]
        admin_screen_set: NewScreenSet
        if next_screen_set_id:
            admin_screen_set = admin_screen.screen_sets_by_id[next_screen_set_id]
        else:
            admin_screen_set = None
        return self._admin_screen_render_sets_modal(admin_event, admin_screen, admin_screen_set)

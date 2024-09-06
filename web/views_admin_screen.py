from logging import Logger
from typing import Annotated

import requests
import validators
from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, Reswap

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.screen import Screen
from data.screen_set import ScreenSet
from data.event import Event
from data.loader import EventLoader
from data.util import ScreenType
from database.sqlite import EventDatabase
from database.store import StoredScreen, StoredScreenSet
from web.messages import Message
from web.views import WebContext, AController
from web.views_admin import AAdminController
from web.views_admin_event import EventAdminWebContext

logger: Logger = get_logger()


class ScreenAdminWebContext(EventAdminWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
            screen_needed: bool,
            screen_set_needed: bool,
    ):
        super().__init__(request, data, lazy_load, True)
        self.admin_screen: Screen | None = None
        self.admin_screen_set: ScreenSet | None = None
        field: str = 'admin_screen_id'
        if field in self.data:
            try:
                admin_screen_id: int | None = self._form_data_to_int(field, minimum=1)
            except ValueError as ve:
                self._redirect_error(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
                return
            try:
                self.admin_screen = self.admin_event.basic_screens_by_id[admin_screen_id]
            except KeyError:
                self._redirect_error(f'L\'écran [{admin_screen_id}] n\'existe pas')
                return
        if screen_needed and not self.admin_screen:
            self._redirect_error(f'L\'écran n\'est pas spécifié')
            return
        field: str = 'admin_screen_set_id'
        if field in self.data:
            try:
                admin_screen_set_id: int | None = self._form_data_to_int(field, minimum=1)
            except ValueError as ve:
                self._redirect_error(f'Valeur non valide pour [{field}]: [{data.get(field, None)}] ({ve})')
                return
            try:
                self.admin_screen_set = self.admin_screen.screen_sets_by_id[admin_screen_set_id]
            except KeyError:
                self._redirect_error(
                    f'L\'ensemble d\'écran [{admin_screen_set_id}] n\'existe pas pour l\'écran '
                    f'[{self.admin_screen.uniq_id}]')
                return
        if screen_set_needed and not self.admin_screen_set:
            self._redirect_error(f'L\'ensemble d\'écran n\'est pas spécifié')
            return


class AdminScreenController(AAdminController):

    @staticmethod
    def _admin_validate_screen_update_data(
            action: str,
            web_context: ScreenAdminWebContext,
            data: dict[str, str] | None = None,
    ) -> StoredScreen:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        type: str
        field: str = 'type'
        match action:
            case 'create':
                type = WebContext.form_data_to_str(data, field)
                match type:
                    case 'boards' | 'input' | 'players' | 'results' | 'image':
                        pass
                    case None:
                        errors[field] = 'Veuillez choisir le type d\'écran.'
                    case _:
                        raise ValueError(f'type=[{type}]')
            case 'update' | 'clone' | 'delete':
                type = web_context.admin_screen.stored_screen.type
            case _:
                raise ValueError(f'action=[{action}]')
        field = 'uniq_id'
        uniq_id: str = WebContext.form_data_to_str(data, field)
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
                        if uniq_id in web_context.admin_event.screens_by_uniq_id:
                            errors[field] = f'L\'écran [{uniq_id}] existe déjà.'
                    case 'update':
                        if uniq_id != web_context.admin_screen.uniq_id \
                                and uniq_id in web_context.admin_event.screens_by_uniq_id:
                            errors[field] = f'L\'écran [{uniq_id}] existe déjà.'
                    case _:
                        raise ValueError(f'action=[{action}]')
            name = WebContext.form_data_to_str(data, 'name')
            public = WebContext.form_data_to_bool(data, 'public')
        menu: str | None = None
        menu_text: str | None = None
        columns: int | None = None
        timer_id: int | None = None
        players_show_unpaired: bool | None = None
        results_limit: int | None = None
        results_tournament_ids: list[int] | None = None
        image: str | None = None
        match action:
            case 'create' | 'delete' | 'clone':
                pass
            case 'update':
                field = 'columns'
                try:
                    columns = WebContext.form_data_to_int(data, field, minimum=1)
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
                menu_text = WebContext.form_data_to_str(data, 'menu_text')
                menu = WebContext.form_data_to_str(data, 'menu')
                field = 'timer_id'
                try:
                    timer_id = WebContext.form_data_to_int(data, field)
                    if timer_id and timer_id not in web_context.admin_event.timers_by_id:
                        errors[field] = f'Le chronomètre [{timer_id}] n\'existe pas.'
                except ValueError:
                    errors[field] = 'Un entier positif est attendu.'
                match web_context.admin_screen.type:
                    case ScreenType.Boards | ScreenType.Input:
                        pass
                    case ScreenType.Players:
                        players_show_unpaired = WebContext.form_data_to_bool(data, 'players_show_unpaired')
                    case ScreenType.Results:
                        field = 'results_limit'
                        try:
                            results_limit = WebContext.form_data_to_int(data, field)
                        except ValueError:
                            errors[field] = 'Un entier positif est attendu.'
                        results_tournament_ids = []
                        for tournament_id in web_context.admin_event.tournaments_by_id:
                            field = f'results_tournament_{tournament_id}'
                            if WebContext.form_data_to_bool(data, field):
                                results_tournament_ids.append(tournament_id)
                    case ScreenType.Image:
                        field = 'image'
                        image = WebContext.form_data_to_str(data, field, '')
                        if not image:
                            errors[field] = f'Veuillez préciser l\'URL de l\'image.'
                        elif not validators.url(image):
                            errors[field] = f'L\'URL [{image}] n\'est pas valide.'
                        else:
                            try:
                                response = requests.get(image)
                                if response.status_code != 200:
                                    errors[field] = f'L\'URL [{image}] est en erreur (code [{response.status_code}]).'
                            except requests.ConnectionError as ce:
                                errors[field] = f'L\'URL [{image}] est en erreur ([{ce}]).'
                    case _:
                        raise ValueError(f'type=[{web_context.admin_screen.type}]')
            case _:
                raise ValueError(f'action=[{action}]')
        return StoredScreen(
            id=web_context.admin_screen.id if action != 'create' else None,
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
            image=image,
            errors=errors,
        )

    def _admin_screen_render_edit_modal(
            self, action: str,
            web_context: ScreenAdminWebContext,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        if data is None:
            data: dict[str, str] = {}
            match action:
                case 'update':
                    data['uniq_id'] = WebContext.value_to_form_data(web_context.admin_screen.stored_screen.uniq_id)
                case 'create' | 'clone':
                    data['uniq_id'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            match action:
                case 'update' | 'clone':
                    data['public'] = WebContext.value_to_form_data(web_context.admin_screen.stored_screen.public)
                    data['name'] = WebContext.value_to_form_data(web_context.admin_screen.stored_screen.name)
                    data['columns'] = WebContext.value_to_form_data(web_context.admin_screen.stored_screen.columns)
                    data['menu_text'] = WebContext.value_to_form_data(web_context.admin_screen.stored_screen.menu_text)
                    data['menu'] = WebContext.value_to_form_data(web_context.admin_screen.stored_screen.menu)
                    data['timer_id'] = WebContext.value_to_form_data(web_context.admin_screen.stored_screen.timer_id)
                    match web_context.admin_screen.type:
                        case ScreenType.Boards | ScreenType.Input:
                            pass
                        case ScreenType.Players:
                            data['players_show_unpaired'] = WebContext.value_to_form_data(
                                web_context.admin_screen.stored_screen.players_show_unpaired)
                        case ScreenType.Results:
                            data['results_limit'] = WebContext.value_to_form_data(
                                web_context.admin_screen.stored_screen.results_limit)
                            for tournament_id in web_context.admin_event.tournaments_by_id:
                                data[f'results_tournament_{tournament_id}'] = WebContext.value_to_form_data(
                                    tournament_id in web_context.admin_screen.stored_screen.results_tournament_ids)
                        case ScreenType.Image:
                            data['image'] = WebContext.value_to_form_data(
                                web_context.admin_screen.stored_screen.image)
                        case _:
                            raise ValueError(f'action={action}')
                case 'create':
                    data['type'] = ''
                    data['public'] = WebContext.value_to_form_data(True)
                    data['uniq_id'] = ''
                    data['name'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            stored_screen: StoredScreen = self._admin_validate_screen_update_data(action, web_context, data)
            errors = stored_screen.errors
        if errors is None:
            errors = {}
        return HTMXTemplate(
            template_name='admin_screen_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'papi_web_config': PapiWebConfig(),
                'admin_auth': web_context.admin_auth,
                'action': action,
                'admin_main_selector': web_context.admin_main_selector,
                'admin_event_selector': web_context.admin_event_selector,
                'admin_event': web_context.admin_event,
                'admin_screen': web_context.admin_screen,
                'data': data,
                'screen_type_options': self._get_screen_type_options(family_screens_only=False),
                'timer_options': self._get_timer_options(web_context.admin_event),
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
        action: str = WebContext.form_data_to_str(data, 'action')
        web_context: ScreenAdminWebContext
        match action:
            case 'update' | 'delete' | 'clone':
                web_context = ScreenAdminWebContext(request, data, True, True, False)
            case 'create':
                web_context = ScreenAdminWebContext(request, data, True, False, False)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        return self._admin_screen_render_edit_modal(action, web_context)

    @post(
        path='/admin-screen-update',
        name='admin-screen-update'
    )
    async def htmx_admin_screen_update(
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
                web_context: ScreenAdminWebContext = ScreenAdminWebContext(request, data, True, True, False)
            case 'create':
                web_context: ScreenAdminWebContext = ScreenAdminWebContext(request, data, True, False, False)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        stored_screen: StoredScreen | None = self._admin_validate_screen_update_data(action, web_context, data)
        if stored_screen.errors:
            return self._admin_screen_render_edit_modal(action, web_context, data, stored_screen.errors)
        next_action: str | None = None
        next_screen_id: int | None = None
        with EventDatabase(web_context.admin_event.uniq_id, write=True) as event_database:
            match action:
                case 'update':
                    stored_screen = event_database.update_stored_screen(stored_screen)
                    Message.success(request, f'L\'écran [{stored_screen.uniq_id}] a été modifié.')
                case 'create':
                    stored_screen = event_database.add_stored_screen(stored_screen)
                    if stored_screen.type in [ScreenType.Boards, ScreenType.Input, ScreenType.Players]:
                        event_database.add_stored_screen_set(
                            stored_screen.id, web_context.admin_event.tournaments_sorted_by_uniq_id[0].id)
                    Message.success(request, f'L\'écran [{stored_screen.uniq_id}] a été créé.')
                    next_screen_id = stored_screen.id
                    next_action = 'update'
                case 'delete':
                    event_database.delete_stored_screen(web_context.admin_screen.id)
                    Message.success(request, f'L\'écran [{web_context.admin_screen.uniq_id}] a été supprimé.')
                case 'clone':
                    stored_screen = event_database.clone_stored_screen(
                        web_context.admin_screen.id, stored_screen.uniq_id, WebContext.form_data_to_str(data, 'name'))
                    Message.success(
                        request,
                        f'L\'écran [{web_context.admin_screen.uniq_id}] a été dupliqué ([{stored_screen.uniq_id}]).')
                    next_screen_id = stored_screen.id
                    next_action = 'update'
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        web_context.set_admin_event(event_loader.reload_event(web_context.admin_event.uniq_id))
        if next_screen_id:
            web_context.admin_screen = web_context.admin_event.basic_screens_by_id[next_screen_id]
            return self._admin_screen_render_edit_modal(next_action, web_context)
        else:
            return self._admin_render_index(web_context)

    @staticmethod
    def _admin_validate_screen_set_update_data(
            web_context: ScreenAdminWebContext,
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
        name = WebContext.form_data_to_str(data, field)
        field: str = 'tournament_id'
        try:
            if len(web_context.admin_screen.event.tournaments_by_id) == 1:
                tournament_id = list(web_context.admin_screen.event.tournaments_by_id.keys())[0]
                data[field] = WebContext.value_to_form_data(tournament_id)
            else:
                tournament_id = WebContext.form_data_to_int(data, field)
                if not tournament_id:
                    errors[field] = f'Veuillez indiquer le tournoi.'
                elif tournament_id not in web_context.admin_screen.event.tournaments_by_id:
                    errors[field] = f'Le tournoi [{tournament_id}] n\'existe pas.'
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
        fixed_boards_str: str | None = None
        if web_context.admin_screen.type in [ScreenType.Boards, ScreenType.Input]:
            fixed_boards_str = WebContext.form_data_to_str(data, 'fixed_boards_str')
            if fixed_boards_str:
                for fixed_board_str in list(map(str.strip, fixed_boards_str.split(','))):
                    if fixed_board_str:
                        try:
                            int(fixed_board_str)
                        except ValueError:
                            errors['fixed_boards_str'] = f'Le numéro d\'échiquier {fixed_board_str} n\'est pas valide.'
                            break
        return StoredScreenSet(
            id=web_context.admin_screen_set.id,
            screen_id=web_context.admin_screen.id,
            name=name,
            tournament_id=tournament_id,
            order=web_context.admin_screen_set.order,
            fixed_boards_str=fixed_boards_str,
            first=first,
            last=last,
            errors=errors,
        )

    @staticmethod
    def _get_tournament_options(admin_event: Event) -> dict[str, str]:
        options: dict[str, str] = {}
        for tournament in admin_event.tournaments_by_id.values():
            options[str(tournament.id)] = f'{tournament.name} ({tournament.filename})'
        return options

    def _admin_screen_render_sets_modal(
            self,
            web_context: ScreenAdminWebContext,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        if data is None:
            if web_context.admin_screen_set:
                data = {
                    'tournament_id': WebContext.value_to_form_data(
                        web_context.admin_screen_set.stored_screen_set.tournament_id),
                    'fixed_boards_str': WebContext.value_to_form_data(
                        web_context.admin_screen_set.stored_screen_set.fixed_boards_str),
                    'name': WebContext.value_to_form_data(web_context.admin_screen_set.stored_screen_set.name),
                    'first': WebContext.value_to_form_data(web_context.admin_screen_set.stored_screen_set.first),
                    'last': WebContext.value_to_form_data(web_context.admin_screen_set.stored_screen_set.last),
                }
                if web_context.admin_screen.type in [ScreenType.Boards, ScreenType.Input]:
                    data['fixed_boards_str'] = WebContext.value_to_form_data(
                        web_context.admin_screen_set.stored_screen_set.fixed_boards_str)
                stored_screen_set = self._admin_validate_screen_set_update_data(web_context, data)
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
                'admin_auth': web_context.admin_auth,
                'admin_main_selector': web_context.admin_main_selector,
                'admin_event_selector': web_context.admin_event_selector,
                'admin_event': web_context.admin_event,
                'admin_screen': web_context.admin_screen,
                'admin_screen_set': web_context.admin_screen_set,
                'tournament_options': self._get_tournament_options(web_context.admin_event),
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
        web_context: ScreenAdminWebContext = ScreenAdminWebContext(request, data, True, True, True)
        if web_context.error:
            return web_context.error
        return self._admin_screen_render_sets_modal(web_context)

    @post(
        path='/admin-screen-sets-update',
        name='admin-screen-sets-update'
    )
    async def htmx_admin_screen_sets_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str | list[int]], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Reswap | Redirect:
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        action: str = WebContext.form_data_to_str(data, 'action')
        if action == 'close':
            web_context: EventAdminWebContext = EventAdminWebContext(request, data, True, True)
            if web_context.error:
                return web_context.error
            return self._admin_render_index(web_context)
        match action:
            case 'delete' | 'clone' | 'update':
                web_context: ScreenAdminWebContext = ScreenAdminWebContext(request, data, True, True, True)
            case 'add' | 'reorder' | 'cancel':
                web_context: ScreenAdminWebContext = ScreenAdminWebContext(request, data, True, True, False)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        match action:
            case 'delete':
                if len(web_context.admin_screen.screen_sets_sorted_by_order) <= 1:
                    return AController.redirect_error(
                        request, f'Le dernier ensemble d\'un écran ne peut être supprimé.')
            case 'update' | 'clone' | 'add' | 'reorder' | 'cancel':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        next_screen_set_id: int | None = None
        with (EventDatabase(web_context.admin_event.uniq_id, write=True) as event_database):
            match action:
                case 'update':
                    stored_screen_set: StoredScreenSet = self._admin_validate_screen_set_update_data(web_context, data)
                    if stored_screen_set.errors:
                        return self._admin_screen_render_sets_modal(web_context, data, stored_screen_set.errors)
                    event_database.update_stored_screen_set(stored_screen_set)
                case 'delete':
                    event_database.delete_stored_screen_set(
                        web_context.admin_screen_set.id, web_context.admin_screen.id)
                case 'clone':
                    stored_screen_set = event_database.clone_stored_screen_set(
                        web_context.admin_screen_set.id, web_context.admin_screen.id)
                    next_screen_set_id = stored_screen_set.id
                case 'add':
                    stored_screen_set = event_database.add_stored_screen_set(
                        web_context.admin_screen.id, list(web_context.admin_event.tournaments_by_id.keys())[0])
                    next_screen_set_id = stored_screen_set.id
                case 'reorder':
                    event_database.reorder_stored_screen_sets(web_context.admin_screen.id, data['item'])
                case 'cancel':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            event_database.commit()
        web_context.set_admin_event(event_loader.reload_event(web_context.admin_event.uniq_id))
        web_context.admin_screen = web_context.admin_event.basic_screens_by_id[web_context.admin_screen.id]
        web_context.admin_screen_set = None
        if next_screen_set_id:
            web_context.admin_screen_set = web_context.admin_screen.screen_sets_by_id[next_screen_set_id]
        return self._admin_screen_render_sets_modal(web_context)

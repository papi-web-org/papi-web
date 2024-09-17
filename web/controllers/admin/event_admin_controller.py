import time
from datetime import datetime
from logging import Logger
from pathlib import Path
from typing import Annotated, Any

import requests
import validators
from litestar import post
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect

from common import format_timestamp_date
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.loader import EventLoader
from database.sqlite import EventDatabase
from database.store import StoredEvent
from web.messages import Message
from web.controllers.index_controller import WebContext, AbstractController
from web.controllers.admin.index_admin_controller import AbstractAdminController, AdminWebContext

logger: Logger = get_logger()


class EventAdminWebContext(AdminWebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
            event_needed: bool,
    ):
        super().__init__(request, data, lazy_load)
        if self.error:
            return
        if event_needed and not self.admin_event:
            self._redirect_error(f'L\'évènement n\'est pas spécifie')
            return


class EventAdminController(AbstractAdminController):

    @staticmethod
    def _admin_validate_event_update_data(
            action: str,
            web_context: EventAdminWebContext,
            data: dict[str, str] | None = None,
    ) -> StoredEvent:
        if data is None:
            data = {}
        errors: dict[str, str] = {}
        uniq_id: str | None = WebContext.form_data_to_str(data, 'uniq_id')
        if action == 'delete':
            if not uniq_id:
                errors['uniq_id'] = 'Veuillez entrer l\'identifiant de l\'évènement.'
            elif uniq_id != web_context.admin_event.uniq_id:
                errors['uniq_id'] = f'L\'identifiant entré n\'est pas valide.'
        else:
            if not uniq_id:
                errors['uniq_id'] = 'Veuillez entrer l\'identifiant de l\'évènement.'
            elif uniq_id.find('/') != -1:
                errors['uniq_id'] = "le caractère « / » n\'est pas autorisé"
            else:
                event_uniq_ids: list[str] = EventLoader.get(request=web_context.request, lazy_load=True).event_uniq_ids
                match action:
                    case 'create' | 'clone':
                        if uniq_id in event_uniq_ids:
                            errors['uniq_id'] = f'L\'évènement [{uniq_id}] existe déjà.'
                    case 'update':
                        if uniq_id != web_context.admin_event.uniq_id and uniq_id in event_uniq_ids:
                            errors['uniq_id'] = f'L\'évènement [{uniq_id}] existe déjà.'
                    case _:
                        raise ValueError(f'action=[{action}]')
        name: str | None = WebContext.form_data_to_str(data, 'name')
        start: float | None = None
        stop: float | None = None
        match action:
            case 'create' | 'clone' | 'update':
                if not name:
                    errors['name'] = 'Veuillez entrer le nom de l\'évènement.'
                start_str: str | None = WebContext.form_data_to_str(data, 'start')
                if not start_str:
                    errors['start'] = 'Veuillez entrer la date de début de l\'évènement.'
                else:
                    start = time.mktime(datetime.strptime(start_str, '%Y-%m-%dT%H:%M').timetuple())
                stop_str: str | None = WebContext.form_data_to_str(data, 'stop')
                if not stop_str:
                    errors['stop'] = 'Veuillez entrer la date de fin de l\'évènement.'
                else:
                    stop = time.mktime(datetime.strptime(stop_str, '%Y-%m-%dT%H:%M').timetuple())
            case 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        public: bool | None = WebContext.form_data_to_bool(data, 'public')
        path: str | None = WebContext.form_data_to_str(data, 'path')
        background_image: str | None = None
        background_color: str | None = None
        update_password: str | None = WebContext.form_data_to_str(data, 'update_password')
        record_illegal_moves: int | None = None
        allow_results_deletion_on_input_screens: bool | None = None
        timer_colors: dict[int, str | None] = {i: None for i in range(1, 4)}
        timer_color_checkboxes: dict[int, bool | None] = {i: None for i in range(1, 4)}
        timer_delays: dict[int, int | None] = {i: None for i in range(1, 4)}
        match action:
            case 'update':
                field = 'background_image'
                if background_image := WebContext.form_data_to_str(data, field, ''):
                    if validators.url(background_image):
                        try:
                            response = requests.get(background_image)
                            if response.status_code != 200:
                                errors[field] = \
                                    f'L\'URL [{background_image}] est en erreur (code [{response.status_code}]).'
                        except requests.ConnectionError as ce:
                            errors[field] = f'L\'URL [{background_image}] est en erreur ([{ce}]).'
                    else:
                        background_image = background_image.strip('/')
                        if background_image.find('..') != -1:
                            errors[field] = f'Le chemin [{background_image}] est incorrect.'
                            data[field] = ''
                        else:
                            file: Path = PapiWebConfig.custom_path / background_image
                            if not file.exists():
                                errors[field] = f'Le fichier [{background_image}] est introuvable.'
                field: str = 'background_color'
                color_checkbox = WebContext.form_data_to_bool(data, field + '_checkbox')
                if not color_checkbox:
                    try:
                        background_color = WebContext.form_data_to_rgb(data, field)
                    except ValueError:
                        errors[field] = f'La couleur [{data[field]}] n\'est pas valide (attendu [#RRGGBB]).'
                try:
                    record_illegal_moves = WebContext.form_data_to_int(data, 'record_illegal_moves')
                    assert record_illegal_moves is None or 0 <= record_illegal_moves <= 3
                except (ValueError, AssertionError):
                    errors['record_illegal_moves'] = f'La valeur entrée [{data[field]}] n\'est pas valide.'
                try:
                    allow_results_deletion_on_input_screens = WebContext.form_data_to_bool(
                        data, 'allow_results_deletion_on_input_screens')
                except ValueError:
                    errors['allow_results_deletion_on_input_screens'] = \
                        f'La valeur entrée [{data[field]}] n\'est pas valide.'
                for i in range(1, 4):
                    field: str = f'color_{i}'
                    timer_color_checkboxes[i] = WebContext.form_data_to_bool(data, field + '_checkbox')
                    if not timer_color_checkboxes[i]:
                        try:
                            timer_colors[i] = WebContext.form_data_to_rgb(data, field)
                        except ValueError:
                            errors[field] = f'La couleur [{data[field]}] n\'est pas valide (attendu [#HHHHHH]).'
                    field: str = f'delay_{i}'
                    try:
                        timer_delays[i] = WebContext.form_data_to_int(data, field, minimum=1)
                    except ValueError:
                        errors[field] = f'Le délai [{data[field]}] n\'est pas valide (attendu un entier positif).'
            case 'create' | 'clone' | 'delete':
                pass
            case _:
                raise ValueError(f'action=[{action}]')
        return StoredEvent(
            uniq_id=uniq_id,
            name=name,
            start=start,
            stop=stop,
            public=public,
            path=path,
            background_image=background_image,
            background_color=background_color,
            update_password=update_password,
            record_illegal_moves=record_illegal_moves,
            allow_results_deletion_on_input_screens=allow_results_deletion_on_input_screens,
            timer_colors=timer_colors,
            timer_delays=timer_delays,
            errors=errors,
        )

    @staticmethod
    def background_images_jstree_data(background_image: str) -> list[dict[str, Any]]:
        custom_path: Path = PapiWebConfig.custom_path
        dir_nodes: list[dict[str, str]] = []
        file_nodes: list[dict[str, str]] = []
        for item in custom_path.rglob('*'):
            item_str = str(item).replace(str(custom_path), '').replace('\\', '/').lstrip('/')
            node: dict[str, Any] = {
                'id': item_str or '#',
                'parent': '/'.join(item_str.split('/')[:-1]) or '#',
                'text': f'{" " if item.is_dir() else ""}{item_str.split("/")[-1]}',
                'state': {},
            }
            if item.is_dir():
                node['icon'] = 'bi-folder'
            else:
                node['icon'] = 'bi-card-image'
                if background_image == item_str:
                    node['state']['selected'] = True
                node['a_attr'] = {
                    'onclick': f'$("#background-image").val("{item_str}"); '
                               f'$.ajax({{'
                               f'    url: "/background",'
                               f'    type: "POST",'
                               f'    data: {{ "image": "{item_str}", "color": $("#background-color").val() }},'
                               f'    success: function(data) {{'
                               f'        $("#background-image-test").css("background-image", data["url"]);'
                               f'        $("#background-image-test").css("background-color", data["color"]);'
                               f'    }},'
                               f'    error: function(jqXHR, exception) {{'
                               f'        console.log('
                               f'            "Changing background failed: status_code=" + jqXHR.status '
                               f'            + ", exception=" + exception + ", response=" + jqXHR.responseText'
                               f'        );'
                               f'    }},'
                               f'}});',
                }
            if item.is_dir():
                dir_nodes.append(node)
            else:
                file_nodes.append(node)
        return file_nodes + dir_nodes

    def _admin_event_render_edit_modal(
            self,
            action: str,
            web_context: EventAdminWebContext | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        if data is None:
            data: dict[str, str] = {}
            match action:
                case 'update':
                    data['uniq_id'] = WebContext.value_to_form_data(web_context.admin_event.stored_event.uniq_id)
                case 'create' | 'clone':
                    data['uniq_id'] = ''
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            match action:
                case 'update':
                    data['uniq_id'] = '' if action == 'clone' else WebContext.value_to_form_data(
                        web_context.admin_event.stored_event.uniq_id)
                    data['name'] = WebContext.value_to_form_data(web_context.admin_event.stored_event.name)
                    data['public'] = WebContext.value_to_form_data(web_context.admin_event.stored_event.public)
                    data['start'] = WebContext.value_to_datetime_form_data(web_context.admin_event.stored_event.start)
                    data['stop'] = WebContext.value_to_datetime_form_data(web_context.admin_event.stored_event.stop)
                    data['background_image'] = WebContext.value_to_form_data(
                        web_context.admin_event.stored_event.background_image)
                    data['background_color'] = WebContext.value_to_form_data(
                        web_context.admin_event.stored_event.background_color)
                    data['background_color_checkbox'] = WebContext.value_to_form_data(
                        web_context.admin_event.stored_event.background_color is None)
                    data['path'] = WebContext.value_to_form_data(web_context.admin_event.stored_event.path)
                    data['update_password'] = WebContext.value_to_form_data(
                        web_context.admin_event.stored_event.update_password)
                    data['record_illegal_moves'] = WebContext.value_to_form_data(
                        web_context.admin_event.stored_event.record_illegal_moves)
                    data['allow_results_deletion_on_input_screens'] = WebContext.value_to_form_data(
                        web_context.admin_event.stored_event.allow_results_deletion_on_input_screens)
                    for i in range(1, 4):
                        data[f'color_{i}'] = WebContext.value_to_form_data(web_context.admin_event.timer_colors[i])
                        data[f'color_{i}_checkbox'] = WebContext.value_to_form_data(
                            web_context.admin_event.stored_event.timer_colors[i] is None)
                        data[f'delay_{i}'] = WebContext.value_to_form_data(
                            web_context.admin_event.stored_event.timer_delays[i])
                case 'create':
                    data['public'] = WebContext.value_to_form_data(False)
                    today_str: str = format_timestamp_date()
                    start = time.mktime(datetime.strptime(
                        f'{today_str} 00:00', '%Y-%m-%d %H:%M').timetuple())
                    stop = time.mktime(datetime.strptime(
                        f'{today_str} 23:59', '%Y-%m-%d %H:%M').timetuple())
                    data['start'] = WebContext.value_to_datetime_form_data(start)
                    data['stop'] = WebContext.value_to_datetime_form_data(stop)
                case 'delete':
                    pass
                case _:
                    raise ValueError(f'action=[{action}]')
            stored_event: StoredEvent = self._admin_validate_event_update_data(action, web_context, data)
            errors = stored_event.errors
        if errors is None:
            errors = {}
        allow_results_deletion_on_input_screens_options: dict[str, str] = {
            '': '',
            'off': 'Non autorisée',
            'on': 'Autorisée',
        }
        default_option = PapiWebConfig.default_allow_results_deletion_on_input_screens
        allow_results_deletion_on_input_screens_options[''] = \
            (f'Par défaut '
             f'({allow_results_deletion_on_input_screens_options["on" if default_option else "off"]})')
        return HTMXTemplate(
            template_name='admin_event_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context=web_context.template_context | {
                'action': action,
                'data': data,
                'errors': errors,
                'record_illegal_moves_options': self._get_record_illegal_moves_options(
                    PapiWebConfig.default_record_illegal_moves_number),
                'allow_results_deletion_on_input_screens_options': allow_results_deletion_on_input_screens_options,
                'timer_color_texts': self._get_timer_color_texts(PapiWebConfig.default_timer_delays),
                'background_images_jstree_data': self.background_images_jstree_data(
                    data['background_image']) if action == 'update' else {}
            })

    @post(
        path='/admin-event-render-edit-modal',
        name='admin-event-render-edit-modal'
    )
    async def htmx_admin_event_render_edit_modal(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        action: str = WebContext.form_data_to_str(data, 'action')
        web_context: EventAdminWebContext
        match action:
            case 'clone' | 'update' | 'delete':
                web_context = EventAdminWebContext(request, data, True, True)
            case 'create':
                web_context = EventAdminWebContext(request, data, True, False)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        return self._admin_event_render_edit_modal(action, web_context, )

    @post(
        path='/admin-event-update',
        name='admin-event-update'
    )
    async def htmx_admin_event_update(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template | Redirect:
        web_context: EventAdminWebContext
        action: str = WebContext.form_data_to_str(data, 'action')
        if action == 'close':
            web_context: AdminWebContext = AdminWebContext(request, data, True)
            if web_context.error:
                return web_context.error
            return self._admin_render_index(web_context)
        match action:
            case 'create':
                web_context = EventAdminWebContext(request, data, True, False)
            case 'clone' | 'update' | 'delete':
                web_context = EventAdminWebContext(request, data, True, True)
            case _:
                raise ValueError(f'action=[{action}]')
        if web_context.error:
            return web_context.error
        stored_event: StoredEvent = self._admin_validate_event_update_data(action, web_context, data)
        if stored_event.errors:
            return self._admin_event_render_edit_modal(action, web_context, data, stored_event.errors)
        uniq_id: str = stored_event.uniq_id
        event_loader = EventLoader.get(request, lazy_load=True)
        match action:
            case 'create':
                EventDatabase(uniq_id).create()
                with EventDatabase(uniq_id, write=True) as event_database:
                    event_database.update_stored_event(stored_event)
                    event_database.commit()
                Message.success(request, f'L\'évènement [{uniq_id}] a été créé.')
                web_context.set_admin_event(event_loader.load_event(uniq_id))
                return self._admin_render_index(web_context)
            case 'update':
                rename: bool = uniq_id != web_context.admin_event.uniq_id
                if rename:
                    event_loader.clear_cache(web_context.admin_event.uniq_id)
                    try:
                        EventDatabase(web_context.admin_event.uniq_id).rename(new_uniq_id=uniq_id)
                    except PermissionError as pe:
                        return AbstractController.redirect_error(
                            request, f'Le renommage de la base de données a échoué : {pe}')
                with EventDatabase(uniq_id, write=True) as event_database:
                    event_database.update_stored_event(stored_event)
                    event_database.commit()
                if rename:
                    Message.success(
                        request,
                        f'L\'évènement [{web_context.admin_event.uniq_id}] a été renommé ([{uniq_id}) et modifié.')
                else:
                    Message.success(request, f'L\'évènement [{uniq_id}] a été modifié.')
                web_context.set_admin_event(event_loader.reload_event(uniq_id))
                return self._admin_render_index(web_context)
            case 'clone':
                EventDatabase(web_context.admin_event.uniq_id).clone(new_uniq_id=uniq_id)
                with EventDatabase(uniq_id, write=True) as event_database:
                    event_database.update_stored_event(stored_event)
                    event_database.commit()
                Message.success(
                    request, f'L\'évènement [{web_context.admin_event.uniq_id}] a été dupliqué ([{uniq_id}]).')
                web_context.set_admin_event(event_loader.load_event(uniq_id))
                return self._admin_render_index(web_context)
            case 'delete':
                arch = EventDatabase(web_context.admin_event.uniq_id).delete()
                event_loader.clear_cache(web_context.admin_event.uniq_id)
                Message.success(
                    request, f'L\'évènement [{web_context.admin_event.uniq_id}] a été supprimé, la base '
                             f'de données a été archivée ({arch}).')
                web_context.set_admin_event(None)
                return self._admin_render_index(web_context)
            case _:
                raise ValueError(f'action=[{action}]')

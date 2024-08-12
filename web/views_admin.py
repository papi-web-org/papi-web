from logging import Logger
from pathlib import Path
from typing import Annotated

from litestar import get, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate

from common import RGB, check_rgb_str
from common.exception import PapiWebException
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import NewEvent
from data.loader import EventLoader
from database.access import access_driver, odbc_drivers
from web.messages import Message
from web.views import AController

logger: Logger = get_logger()


class AAdminController(AController):

    @staticmethod
    def form_data_to_str_or_none(
            data: dict[str, str], field: str, empty_value: int | None = None
    ) -> str | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        return data[field]

    @staticmethod
    def form_data_to_int_or_none(
            data: dict[str, str], field: str, empty_value: int | None = None, minimum: int = None
    ) -> int | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        int_val = int(data[field])
        if minimum is not None and int_val < minimum:
            raise ValueError(f'{int_val} < {minimum}')
        return int_val

    @staticmethod
    def form_data_to_bool_or_none(data: dict[str, str], field: str, empty_value: bool | None = None) -> bool | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip().lower()
        if not data[field]:
            return empty_value
        return data[field] in ['true', 'on', ]

    @staticmethod
    def form_data_to_rgb_or_none(data: dict[str, str], field: str, empty_value: RGB | None = None) -> str | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip().lower()
        if not data[field]:
            return empty_value
        return check_rgb_str(data[field])

    @staticmethod
    def value_to_form_data(value: str | int | bool | Path | None) -> str | None:
        if value is None:
            return ''
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, bool):
            return 'true' if value else ''
        if isinstance(value, int):
            return str(value)
        if isinstance(value, Path):
            return str(value)
        raise ValueError

    @staticmethod
    def _get_record_illegal_moves_options(default: int | None, ) -> dict[str, str]:
        options: dict[str, str] = {
            '': '',
            '0': 'Aucun enregistrement des coups illégaux',
            '1': 'Maximum 1 coup illégal',
            '2': 'Maximum 2 coups illégaux',
            '3': 'Maximum 3 coups illégaux',
        }
        options[''] = f'Par défaut ({options[str(default)]})'
        return options

    @staticmethod
    def _get_timer_color_texts(delays: dict[int, int]) -> dict[int, str]:
        return {
            1: f'La couleur n°1 est utilisée jusqu\'à {delays[1]} minutes avant le début des rondes (délai n°1), '
               f'la couleur change ensuite progressivement jusqu\'à la couleur n°2 ({delays[2]} minutes avant le '
               f'début des rondes).',
            2: f'La couleur n°2 est utilisée {delays[2]} minutes avant le début des rondes (délai n°2), la couleur '
               f'change ensuite progressivement jusqu\'à la couleur n°3 (au début des rondes).',
            3: f'La couleur n°3 est utilisée à partir du début des rondes et pendant {delays[3]} minutes (délai n°3).',
        }

    @staticmethod
    def _get_screen_type_options(results_screen_allowed: bool) -> dict[str, str]:
        options: dict[str, str] = {
            '': '-',
            'boards': 'Affichage des échiquiers',
            'boards-update': 'Saisie des résultats',
            'players': 'Appariements par ordre alphabétique',
        }
        if results_screen_allowed:
            options['results'] = 'Derniers résultats'
        return options

    @staticmethod
    def _get_timer_options(event: NewEvent) -> dict[str, str]:
        options: dict[str, str] = {
            '': 'Pas de chronomètre',
        }
        for timer in event.timers_by_id.values():
            options[str(timer.id)] = f'Chronomètre [{timer.uniq_id}]'
        return options

    @staticmethod
    def _get_players_show_unpaired_options() -> dict[str, str]:
        options: dict[str, str] = {
            '': '-',
            '0': 'Affichage seulement des joueur·euses apparié·es',
            '1': 'Affichage de tou·tes les joueur·euses, apparié·es ou non',
        }
        options[''] = f'Par défaut ({options["1" if PapiWebConfig().default_players_show_unpaired else "0"]})'
        return options

    @staticmethod
    def _admin_render_index(
        request: HTMXRequest,
        event_loader: EventLoader,
        admin_main_selector: str = '',
        admin_event: NewEvent = None,
        admin_event_selector: str = '',
    ) -> Template:
        context: dict = {
            'papi_web_config': PapiWebConfig(),
            'odbc_drivers': odbc_drivers(),
            'access_driver': access_driver(),
            'event_loader': event_loader,
            'messages': Message.messages(request),
            'admin_main_selector_options': {
                '': '-- Configuration de Papi-web',
                '@events': '-- Liste des évènements',
            },
            'admin_main_selector': admin_event.uniq_id if admin_event else admin_main_selector,
            'admin_event': admin_event,
            'admin_event_selector_options': {
                '': 'Configuration générale',
                '@chessevents': 'Connexions à ChessEvent',
                '@timers': 'Chronomètres',
                '@tournaments': 'Tournois',
                '@screens': 'Écrans',
                '@families': 'Familles d\'écrans',
                '@rotators': 'Écrans rotatifs',
                # '@messages': 'Messages',
                # '@check_in': 'Pointage',
                # '@pairings': 'Appariements',
            },
            'admin_event_selector': admin_event_selector,
        }
        return HTMXTemplate(
            template_name="admin.html",
            context=context)


class AdminController(AAdminController):
    @get(
        path='/admin',
        name='admin-render-index'
    )
    async def admin_render_index(self, request: HTMXRequest) -> Template | Redirect:
        return self._admin_render_index(request, EventLoader())

    @post(
        path='/admin-update-header',
        name='admin-update-header'
    )
    async def htmx_admin_update_header(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        event_loader: EventLoader = EventLoader()
        admin_main_selector: str = data.get('admin_main_selector', '')
        admin_event_selector: str = data.get('admin_event_selector', '')
        admin_event: NewEvent | None = None
        if not admin_main_selector:
            pass
        elif admin_main_selector == '@events':
            pass
        else:
            try:
                admin_event = event_loader.load_event(admin_main_selector)
            except PapiWebException as pwe:
                Message.error(request, f'L\'évènement [{admin_main_selector}] est introuvable : {pwe}')
                return self._render_messages(request)
        return self._admin_render_index(
            request, event_loader, admin_main_selector=admin_main_selector, admin_event=admin_event,
            admin_event_selector=admin_event_selector)

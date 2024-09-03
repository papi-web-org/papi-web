from logging import Logger
from typing import Annotated

from litestar import post, get
from litestar.contrib.htmx.response import HTMXTemplate
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.contrib.htmx.request import HTMXRequest

from common.exception import PapiWebException
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import NewEvent
from data.loader import EventLoader
from database.access import access_driver, odbc_drivers
from web.messages import Message
from web.session import SessionHandler
from web.views import AController

logger: Logger = get_logger()


class AAdminController(AController):

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
            'input': 'Saisie des résultats',
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
        admin_main_selector: str = '',
        admin_event: NewEvent = None,
        admin_event_selector: str = '',
    ) -> Template:
        context: dict = {
            'papi_web_config': PapiWebConfig(),
            'odbc_drivers': odbc_drivers(),
            'access_driver': access_driver(),
            'event_loader': EventLoader.get(request=request, lazy_load=True),
            'messages': Message.messages(request),
            'main_nav_tabs': {
                '': {
                    'title': 'Configuration Papi-web',
                    'template': 'admin_config.html',
                },
                '@events': {
                    'title': 'Évènements',
                    'template': 'admin_event_list.html',
                },
            },
            'event_nav_tabs': {
                '': {
                    'title': admin_event.uniq_id if admin_event else '',
                    'template': 'admin_event_config.html',
                },
                '@tournaments': {
                    'title': f'Tournois ({len(admin_event.tournaments_by_id) if admin_event else "-"})',
                    'template': 'admin_tournament_list.html',
                },
                '@screens': {
                    'title': f'Écrans ({len(admin_event.basic_screens_by_id) if admin_event else "-"})',
                    'template': 'admin_screen_list.html',
                },
                '@families': {
                    'title': f'Familles ({len(admin_event.families_by_id) if admin_event else "-"})',
                    'template': 'admin_family_list.html',
                },
                '@rotators': {
                    'title': f'Écrans rotatifs ({len(admin_event.rotators_by_id) if admin_event else "-"})',
                    'template': 'admin_rotator_list.html',
                },
                '@timers': {
                    'title': f'Chronomètres ({len(admin_event.timers_by_id) if admin_event else "-"})',
                    'template': 'admin_timer_list.html',
                },
                '@chessevents': {
                    'title': f'ChessEvent ({len(admin_event.chessevents_by_id) if admin_event else "-"})',
                    'template': 'admin_chessevent_list.html',
                },
            },
            'admin_main_selector': admin_event.uniq_id if admin_event else admin_main_selector,
            'admin_event': admin_event,
            'admin_event_selector': admin_event_selector,
            'admin_columns': SessionHandler.get_session_admin_columns(request),
            'show_family_screens_on_screen_list': SessionHandler.get_session_show_family_screens_on_screen_list(
                request),
            'show_details_on_screen_list': SessionHandler.get_session_show_details_on_screen_list(request),
            'show_details_on_family_list': SessionHandler.get_session_show_details_on_family_list(request),
            'show_details_on_rotator_list': SessionHandler.get_session_show_details_on_rotator_list(request),
            'screen_types_on_screen_list': SessionHandler.get_session_screen_types_on_screen_list(request),
        }
        return HTMXTemplate(
            template_name="admin.html",
            context=context)


class AdminIndexController(AAdminController):
    @get(
        path='/admin-render',
        name='admin-render'
    )
    async def htmx_admin_render_index(self, request: HTMXRequest) -> Template:
        return self._admin_render_index(request)

    @post(
        path='/admin-update-header',
        name='admin-update-header'
    )
    async def htmx_admin_update_header(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        admin_main_selector: str = self._form_data_to_str_or_none(data, 'admin_main_selector', '')
        admin_event_selector: str = self._form_data_to_str_or_none(data, 'admin_event_selector', '')
        admin_event: NewEvent | None = None
        if not admin_main_selector:
            pass
        elif admin_main_selector == '@events':
            pass
        else:
            try:
                admin_event = EventLoader.get(request=request, lazy_load=False).load_event(admin_main_selector)
            except PapiWebException as pwe:
                Message.error(request, f'L\'évènement [{admin_main_selector}] est introuvable : {pwe}')
                return self._render_messages(request)
        field: str = f'admin_columns'
        if field in data:
            SessionHandler.set_session_admin_columns(request, self._form_data_to_int_or_none(data, field))
        field: str = 'show_family_screens_on_screen_list'
        if field in data:
            SessionHandler.set_session_show_family_screens_on_screen_list(
                request, self._form_data_to_bool_or_none(data, field))
        field: str = 'show_details_on_screen_list'
        if field in data:
            SessionHandler.set_session_show_details_on_screen_list(
                request, self._form_data_to_bool_or_none(data, field))
        field: str = 'show_details_on_family_list'
        if field in data:
            SessionHandler.set_session_show_details_on_family_list(
                request, self._form_data_to_bool_or_none(data, field))
        field: str = 'show_details_on_rotator_list'
        if field in data:
            SessionHandler.set_session_show_details_on_rotator_list(
                request, self._form_data_to_bool_or_none(data, field))
        screen_types: list[str] = SessionHandler.get_session_screen_types_on_screen_list(request)
        for field, screen_type in {
            'show_boards_screens_on_screen_list': 'boards',
            'show_input_screens_on_screen_list': 'input',
            'show_players_screens_on_screen_list': 'players',
            'show_results_screens_on_screen_list': 'results',
        }.items():
            if field in data:
                if self._form_data_to_bool_or_none(data, field):
                    screen_types.append(screen_type)
                else:
                    screen_types.remove(screen_type)
                SessionHandler.set_session_screen_types_on_screen_list(request, screen_types)
                continue
        return self._admin_render_index(
            request, admin_main_selector=admin_main_selector, admin_event=admin_event,
            admin_event_selector=admin_event_selector)

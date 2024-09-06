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
from data.event import Event
from data.loader import EventLoader
from database.access import access_driver, odbc_drivers
from web.messages import Message
from web.session import SessionHandler
from web.views import AController, WebContext

logger: Logger = get_logger()


class AdminWebContext(WebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
            lazy_load: bool,
    ):
        super().__init__(request, data)
        self._admin_main_selector: str = ''
        self.admin_event_selector: str = ''
        self._admin_event: Event | None = None
        if self.error:
            return
        self._admin_main_selector: str = self._form_data_to_str('admin_main_selector', '')
        if not self.admin_main_selector:
            pass
        elif self.admin_main_selector.startswith('@'):
            pass
        else:
            try:
                self.set_admin_event(EventLoader.get(request=self.request, lazy_load=lazy_load).load_event(
                    self.admin_main_selector))
            except PapiWebException as pwe:
                self._redirect_error(f'L\'évènement [{self.admin_main_selector}] est introuvable : {pwe}')
                self.set_admin_event(None)
                return
        self.admin_event_selector: str = self._form_data_to_str('admin_event_selector', '')

    @property
    def admin_main_selector(self) -> str:
        return self._admin_main_selector

    @property
    def admin_event(self) -> Event | None:
        return self._admin_event

    def set_admin_event(self, event: Event | None):
        self._admin_event = event
        self._admin_main_selector = event.uniq_id if event else ''

    def set_admin_main_selector(self, admin_main_selector: str):
        self._admin_event = None
        self._admin_main_selector = admin_main_selector


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
    def _get_timer_options(event: Event) -> dict[str, str]:
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
            web_context: AdminWebContext,
    ) -> Template:
        event_loader: EventLoader = EventLoader.get(request=web_context.request, lazy_load=True)
        nav_tabs: dict[str, dict[str]]
        if web_context.admin_event:
            nav_tabs = {
                '': {
                    'title': web_context.admin_event.uniq_id,
                    'template': 'admin_event_config.html',
                },
                '@tournaments': {
                    'title': f'Tournois ({len(web_context.admin_event.tournaments_by_id) or "-"})',
                    'template': 'admin_tournament_list.html',
                },
                '@screens': {
                    'title': f'Écrans ({len(web_context.admin_event.basic_screens_by_id) or "-"})',
                    'template': 'admin_screen_list.html',
                },
                '@families': {
                    'title': f'Familles ({len(web_context.admin_event.families_by_id) or  "-"})',
                    'template': 'admin_family_list.html',
                },
                '@rotators': {
                    'title': f'Écrans rotatifs ({len(web_context.admin_event.rotators_by_id) or "-"})',
                    'template': 'admin_rotator_list.html',
                },
                '@timers': {
                    'title': f'Chronomètres ({len(web_context.admin_event.timers_by_id) or "-"})',
                    'template': 'admin_timer_list.html',
                },
                '@chessevents': {
                    'title': f'ChessEvent ({len(web_context.admin_event.chessevents_by_id) or "-"})',
                    'template': 'admin_chessevent_list.html',
                },
            }
        else:
            nav_tabs = {
                '@current_events': {
                    'title': f'Évènements en cours ({len(event_loader.current_events) or "-"})',
                    'events': event_loader.current_events,
                    'disabled': not event_loader.current_events,
                    'empty_str': 'Aucun évènement en cours.',
                    'class': 'bg-primary-subtle',
                    'icon_class': 'bi-calendar',
                },
                '@coming_events': {
                    'title': f'Évènements à venir ({len(event_loader.coming_events) or "-"})',
                    'events': event_loader.coming_events,
                    'disabled': not event_loader.coming_events,
                    'empty_str': 'Aucun évènement à venir.',
                    'class': 'bg-info-subtle',
                    'icon_class': 'bi-calendar-check',
                },
                '@passed_events': {
                    'title': f'Évènements passés ({len(event_loader.passed_events) or "-"})',
                    'events': event_loader.passed_events,
                    'disabled': not event_loader.passed_events,
                    'empty_str': 'Aucun évènement passé.',
                    'class': 'bg-secondary-subtle',
                    'icon_class': 'bi-calendar-minus',
                },
                '@config': {
                    'title': 'Configuration Papi-web',
                    'template': 'admin_config.html',
                    'disabled': False,
                },
            }
            if not web_context.admin_main_selector or nav_tabs[web_context.admin_main_selector]['disabled']:
                web_context.set_admin_main_selector(list(nav_tabs.keys())[0])
            for nav_index in range(len(nav_tabs)):
                if web_context.admin_main_selector == list(nav_tabs.keys())[nav_index] \
                        and nav_tabs[web_context.admin_main_selector]['disabled']:
                    web_context.set_admin_main_selector(list(nav_tabs.keys())[(nav_index + 1) % len(nav_tabs)])
        return HTMXTemplate(
            template_name="admin.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'odbc_drivers': odbc_drivers(),
                'access_driver': access_driver(),
                'messages': Message.messages(web_context.request),
                'nav_tabs': nav_tabs,
                'event_loader': event_loader,
                'admin_main_selector': web_context.admin_main_selector,
                'admin_event': web_context.admin_event,
                'admin_event_selector': web_context.admin_event_selector,
                'admin_columns': SessionHandler.get_session_admin_columns(web_context.request),
                'show_family_screens_on_screen_list': SessionHandler.get_session_show_family_screens_on_screen_list(
                    web_context.request),
                'show_details_on_screen_list': SessionHandler.get_session_show_details_on_screen_list(
                    web_context.request),
                'show_details_on_family_list': SessionHandler.get_session_show_details_on_family_list(
                    web_context.request),
                'show_details_on_rotator_list': SessionHandler.get_session_show_details_on_rotator_list(
                    web_context.request),
                'screen_types_on_screen_list': SessionHandler.get_session_screen_types_on_screen_list(
                    web_context.request),
            })


class AdminIndexController(AAdminController):
    @post(
        path='/admin-render',
        name='admin-render'
    )
    async def htmx_admin_render_index(
            self, request: HTMXRequest
    ) -> Template:
        web_context: AdminWebContext = AdminWebContext(request, {}, True)
        return self._admin_render_index(web_context)

    @post(
        path='/admin-update-header',
        name='admin-update-header'
    )
    async def htmx_admin_update_header(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Template:
        web_context: AdminWebContext = AdminWebContext(request, data, True)
        if web_context.error:
            return web_context.error
        field: str = f'admin_columns'
        if field in data:
            SessionHandler.set_session_admin_columns(request, WebContext.form_data_to_int(data, field))
        field: str = 'show_family_screens_on_screen_list'
        if field in data:
            SessionHandler.set_session_show_family_screens_on_screen_list(
                request, WebContext.form_data_to_bool(data, field))
        field: str = 'show_details_on_screen_list'
        if field in data:
            SessionHandler.set_session_show_details_on_screen_list(
                request, WebContext.form_data_to_bool(data, field))
        field: str = 'show_details_on_family_list'
        if field in data:
            SessionHandler.set_session_show_details_on_family_list(
                request, WebContext.form_data_to_bool(data, field))
        field: str = 'show_details_on_rotator_list'
        if field in data:
            SessionHandler.set_session_show_details_on_rotator_list(
                request, WebContext.form_data_to_bool(data, field))
        screen_types: list[str] = SessionHandler.get_session_screen_types_on_screen_list(request)
        for field, screen_type in {
            'show_boards_screens_on_screen_list': 'boards',
            'show_input_screens_on_screen_list': 'input',
            'show_players_screens_on_screen_list': 'players',
            'show_results_screens_on_screen_list': 'results',
        }.items():
            if field in data:
                if WebContext.form_data_to_bool(data, field):
                    screen_types.append(screen_type)
                else:
                    screen_types.remove(screen_type)
                SessionHandler.set_session_screen_types_on_screen_list(request, screen_types)
                continue
        return self._admin_render_index(web_context)

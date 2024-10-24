from logging import Logger
from typing import Annotated, Any

from litestar import get
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate, ClientRedirect
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.event import Event
from data.loader import EventLoader, ArchiveLoader
from database.access import access_driver, odbc_drivers
from web.controllers.index_controller import AbstractController, WebContext
from web.messages import Message
from web.session import SessionHandler

logger: Logger = get_logger()


class AdminWebContext(WebContext):
    """
    The basic admin web context.
    """

    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ] | None,
            admin_tab: str | None,
    ):
        super().__init__(request, data=data)
        self.admin_tab: str | None = admin_tab
        if self.error:
            return
        self.check_admin_tab()

    def check_admin_tab(self):
        if self.admin_tab not in [None, 'config', 'passed_events', 'current_events', 'coming_events', 'archives', ]:
            self._redirect_error(f'Invalid value [{self.admin_tab}] for parameter [admin_tab]')

    @property
    def background_image(self) -> str:
        if self.admin_tab in ['archives', 'config', ]:
            return PapiWebConfig.default_background_image
        else:
            return ''

    @property
    def background_color(self) -> str:
        return PapiWebConfig.admin_background_color

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'admin_tab': self.admin_tab,
        }


class AbstractAdminController(AbstractController):

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
    def _get_screen_type_options(family_screens_only: bool) -> dict[str, str]:
        options: dict[str, str] = {
            '': '-',
            'boards': 'Appariements par échiquier',
            'input': 'Saisie des résultats',
            'players': 'Appariements par ordre alphabétique',
        }
        if not family_screens_only:
            options['results'] = 'Derniers résultats'
            options['image'] = 'Image'
        return options

    @staticmethod
    def _get_timer_options(event: Event) -> dict[str, str]:
        options: dict[str, str] = {
            '': 'Pas de chronomètre' if event.timers_by_id else 'Aucun chronomètre enregistré',
        }
        for timer in event.timers_by_id.values():
            options[str(timer.id)] = f'Chronomètre [{timer.uniq_id}]'
        return options

    @staticmethod
    def _get_players_show_unpaired_options() -> dict[str, str]:
        options: dict[str, str] = {
            '': '-',
            'off': 'Affichage seulement des joueur·euses apparié·es',
            'on': 'Affichage de tou·tes les joueur·euses, apparié·es ou non',
        }
        options[''] = f'Par défaut ({options["on" if PapiWebConfig.default_players_show_unpaired else "off"]})'
        return options


class AbstractIndexAdminController(AbstractAdminController):

    @classmethod
    def _admin_render(
            cls,
            request: HTMXRequest,
            admin_tab: str | None,
    ) -> Template | ClientRedirect:
        web_context: AdminWebContext = AdminWebContext(request, data=None, admin_tab=admin_tab)
        if web_context.error:
            return web_context.error
        event_loader: EventLoader = EventLoader.get(request=request, lazy_load=True)
        archive_loader: ArchiveLoader = ArchiveLoader.get(request=request)
        nav_tabs: dict[str, dict[str]] = {
            'current_events': {
                'title': f'Évènements en cours ({len(event_loader.current_events) or "-"})',
                'template': 'admin_events.html',
                'events': event_loader.current_events,
                'disabled': not event_loader.current_events,
                'empty_str': 'Aucun évènement en cours.',
                'icon_class': 'bi-calendar',
            },
            'coming_events': {
                'title': f'Évènements à venir ({len(event_loader.coming_events) or "-"})',
                'template': 'admin_events.html',
                'events': event_loader.coming_events,
                'disabled': not event_loader.coming_events,
                'empty_str': 'Aucun évènement à venir.',
                'icon_class': 'bi-calendar-check',
            },
            'passed_events': {
                'title': f'Évènements passés ({len(event_loader.passed_events) or "-"})',
                'template': 'admin_events.html',
                'events': event_loader.passed_events,
                'disabled': not event_loader.passed_events,
                'empty_str': 'Aucun évènement passé.',
                'icon_class': 'bi-calendar-minus',
            },
            'archives': {
                'title': f'Archives ({len(archive_loader.archives_sorted_by_date) or "-"})',
                'template': 'admin_archives.html',
                'archives': archive_loader.archives_sorted_by_date,
                'disabled': not archive_loader.archives_sorted_by_date,
                'empty_str': 'Aucun évènement archivé.',
                'icon_class': 'bi-archive-fill',
            },
            'config': {
                'title': 'Configuration Papi-web',
                'template': 'admin_config.html',
                'icon_class': 'bi-gear-fill',
                'disabled': False,
            },
        }
        if not web_context.admin_tab or nav_tabs[web_context.admin_tab]['disabled']:
            web_context.admin_tab = list(nav_tabs.keys())[0]
        for nav_index in range(len(nav_tabs)):
            if web_context.admin_tab == list(nav_tabs.keys())[nav_index] \
                    and nav_tabs[web_context.admin_tab]['disabled']:
                web_context.admin_tab = list(nav_tabs.keys())[(nav_index + 1) % len(nav_tabs)]
        return HTMXTemplate(
            template_name="admin_index.html",
            context=web_context.template_context | {
                'odbc_drivers': odbc_drivers(),
                'access_driver': access_driver(),
                'messages': Message.messages(web_context.request),
                'nav_tabs': nav_tabs,
                'admin_columns': SessionHandler.get_session_admin_columns(web_context.request),
            })


class IndexAdminController(AbstractIndexAdminController):

    @classmethod
    def _admin(
            cls, request: HTMXRequest,
            admin_tab: str | None,
            admin_columns: int | None,
    ) -> Template | ClientRedirect:
        if admin_columns is not None:
            SessionHandler.set_session_admin_columns(request, admin_columns)
        return cls._admin_render(request, admin_tab)

    @get(
        path='/admin',
        name='admin'
    )
    async def htmx_admin(
            self, request: HTMXRequest,
            admin_columns: int | None,
    ) -> Template | ClientRedirect:
        return self._admin(
            request,
            admin_tab=None,
            admin_columns=admin_columns,
        )

    @get(
        path='/admin/{admin_tab:str}',
        name='admin-tab'
    )
    async def htmx_admin_tab(
            self, request: HTMXRequest,
            admin_tab: str,
            admin_columns: int | None,
    ) -> Template | ClientRedirect:
        return self._admin(
            request,
            admin_tab=admin_tab,
            admin_columns=admin_columns,
        )

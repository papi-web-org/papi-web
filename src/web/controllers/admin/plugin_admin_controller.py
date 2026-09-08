from logging import Logger
from typing import Any
from urllib.parse import urlparse
from webbrowser import open as open_url

from litestar import get, post
from litestar.exceptions import NotFoundException
from litestar.params import FromPath, FromQuery
from litestar.plugins.htmx import HTMXRequest, HTMXTemplate
from litestar.response import Response, Template
from litestar.status_codes import HTTP_204_NO_CONTENT

from common.i18n import _
from common.i18n.utils import by
from common.logger import get_logger
from common.sharly_chess_config import SharlyChessConfig
from data.access_levels.actions import AuthAction
from data.event_metadata import EventMetadata
from data.loader import EventLoader
from plugins.manager import Plugin, plugin_manager
from utils.system_accent import readable_text_color, system_accent_color
from web.controllers.admin.base_admin_controller import (
    AdminWebContext,
    BaseAdminController,
)
from web.guards import ActionGuard
from web.messages import Message

logger: Logger = get_logger()

# The plugins pages live outside the admin nav tabs: this value replaces the tab
# id in their shell context so the sidebar highlights their own button instead
# of falling back to the first nav tab.
PLUGINS_ADMIN_TAB = 'plugins'

# The documentation website, on top of the application itself: the plugins pages
# only open links of these hosts, all the others are rejected.
DOCUMENTATION_HOSTS = ('sharly-chess.com', 'www.sharly-chess.com')


class PluginAdminController(BaseAdminController):
    """The section listing the plugins of the application and allowing
    to enable and disable them."""

    guards = [ActionGuard(AuthAction.MANAGE_APPLICATION_SETTINGS)]

    @staticmethod
    def _get_plugin(plugin_id: str) -> Plugin:
        try:
            return plugin_manager.plugins_by_id[plugin_id]
        except KeyError:
            raise NotFoundException(f'Unknown plugin [{plugin_id}]') from None

    @staticmethod
    def _sorted_plugins() -> list[Plugin]:
        return sorted(plugin_manager.all_plugins, key=by('name'))

    @classmethod
    def _used_by_events(cls, plugin: Plugin) -> list[EventMetadata]:
        # Events that could not be opened (locked, file sync…) use the plugin
        # too, and are the ones the interface has to warn about.
        events_metadata = (
            EventLoader.get_events_metadata()
            + EventLoader.inaccessible_events_metadata()
        )
        return sorted(plugin.used_by_events(events_metadata), key=by('name'))

    @classmethod
    def _detail_context(cls, plugin: Plugin, embedded: bool) -> dict[str, Any]:
        federations = SharlyChessConfig().federations
        return {
            'plugin': plugin,
            'embedded': embedded,
            'used_by_events': cls._used_by_events(plugin),
            'federation_name': federations.get(plugin.federation)
            if plugin.federation
            else None,
            'blocking_plugins': plugin.required_by_enabled_plugins,
        }

    @classmethod
    def _page_context(
        cls,
        web_context: AdminWebContext,
        plugin: Plugin | None,
        embedded: bool,
    ) -> dict[str, Any]:
        from web.controllers.admin.index_admin_controller import IndexAdminController

        context = IndexAdminController.admin_shell_context(web_context) | {
            'admin_tab': PLUGINS_ADMIN_TAB,
            'plugins': cls._sorted_plugins(),
            'selected_plugin': plugin,
            'embedded': embedded,
        }
        if embedded:
            # Displayed in the window of the application, which has a theme of
            # its own: neither the dark theme of the admin view nor the light
            # theme of the remote screens. The light theme of Bootstrap is the
            # base it is built on, see the app-window class of the page.
            accent_color = system_accent_color()
            context |= {
                'theme': 'light',
                'background_info': {'color': 'transparent'},
                'accent_color': accent_color,
                'accent_text_color': readable_text_color(accent_color)
                if accent_color
                else None,
            }
        if plugin:
            context |= cls._detail_context(plugin, embedded)
        return context

    @classmethod
    def _render_page(
        cls,
        web_context: AdminWebContext,
        plugin: Plugin | None,
        embedded: bool,
    ) -> Template:
        return HTMXTemplate(
            template_name='admin/plugins/plugins_page.html',
            context=cls._page_context(web_context, plugin, embedded),
        )

    @get(path='/plugins', name='admin-plugins')
    async def htmx_admin_plugins(
        self,
        request: HTMXRequest,
        plugin_id: FromQuery[str | None] = None,
        embedded: FromQuery[bool | None] = None,
    ) -> Template:
        return self._render_page(
            AdminWebContext(request),
            self._get_plugin(plugin_id) if plugin_id else None,
            bool(embedded),
        )

    @get(path='/plugin-detail/{plugin_id:str}', name='admin-plugin-detail')
    async def htmx_admin_plugin_detail(
        self,
        request: HTMXRequest,
        plugin_id: FromPath[str],
        embedded: FromQuery[bool | None] = None,
    ) -> Template:
        web_context = AdminWebContext(request)
        plugin = self._get_plugin(plugin_id)
        return HTMXTemplate(
            template_name='admin/plugins/_plugin_detail.html',
            context=web_context.template_context
            | self._detail_context(plugin, bool(embedded)),
        )

    @post(path='/plugin-toggle/{plugin_id:str}', name='admin-plugin-toggle')
    async def htmx_admin_plugin_toggle(
        self,
        request: HTMXRequest,
        plugin_id: FromPath[str],
        embedded: FromQuery[bool | None] = None,
    ) -> Template:
        web_context = AdminWebContext(request)
        plugin = self._get_plugin(plugin_id)
        if plugin.is_enabled:
            self._disable_plugin(request, plugin)
        else:
            self._enable_plugin(request, plugin)
        return self._render_page(web_context, plugin, bool(embedded))

    @classmethod
    def _enable_plugin(cls, request: HTMXRequest, plugin: Plugin):
        # The page displays the plugin and its dependencies as installed, so
        # there is nothing to report when it worked.
        plugin_manager.enable_missing_plugins([plugin.id])

    @classmethod
    def _disable_plugin(cls, request: HTMXRequest, plugin: Plugin):
        # The interface hides the button in both cases, the checks are repeated
        # here because disabling a plugin still in use breaks the events using it.
        if blocking_plugins := plugin.required_by_enabled_plugins:
            Message.error(
                request,
                _('Plugin [{plugin}] is needed by the plugins {plugins}.').format(
                    plugin=plugin.name,
                    plugins=', '.join(
                        blocking_plugin.name for blocking_plugin in blocking_plugins
                    ),
                ),
            )
            return
        if cls._used_by_events(plugin):
            Message.error(
                request,
                _(
                    'Plugin [{plugin}] is used by events and can not be uninstalled.'
                ).format(plugin=plugin.name),
            )
            return
        plugin_manager.disable_plugin(plugin)

    @post(
        path='/plugin-default-event/{plugin_id:str}',
        name='admin-plugin-default-event',
    )
    async def htmx_admin_plugin_default_event(
        self,
        request: HTMXRequest,
        plugin_id: FromPath[str],
        embedded: FromQuery[bool | None] = None,
    ) -> Template:
        """Sets whether new events enable the plugin."""
        web_context = AdminWebContext(request)
        plugin = self._get_plugin(plugin_id)
        plugin_manager.set_event_is_enabled_by_default(
            plugin, not plugin.event_is_enabled_by_default
        )
        return HTMXTemplate(
            template_name='admin/plugins/_plugin_detail.html',
            context=web_context.template_context
            | self._detail_context(plugin, bool(embedded)),
        )

    @get(path='/open-external', name='admin-open-external')
    async def open_external(
        self,
        url: FromQuery[str],
    ) -> Response[None]:
        """Opens a link in the web browser of the user. Used by the plugins pages
        when they are displayed in the application itself, where a link would
        otherwise replace the page with no way back."""
        hostname = urlparse(url).hostname
        local_hostname = urlparse(SharlyChessConfig().local_url).hostname
        if hostname in DOCUMENTATION_HOSTS or hostname == local_hostname:
            open_url(url)
        else:
            logger.warning('Refused to open the URL [%s].', url)
        return Response(content=None, status_code=HTTP_204_NO_CONTENT)

from contextvars import ContextVar
from functools import partial
import os
import posixpath
import sqlite3
import typing as t
from pathlib import Path
from typing import Sequence

import aiosqlite
from aiosqlitepool import SQLiteConnectionPool
from jinja2 import (
    Environment,
    FileSystemLoader,
    Template as JinjaTemplate,
    TemplateNotFound,
)
from jinja2.runtime import Context as JinjaContext
from litestar import Router
from litestar.plugins.jinja import JinjaTemplateEngine
from litestar.datastructures import CacheControlHeader
from litestar.events import listener
from litestar.middleware.session import SessionMiddleware
from litestar.middleware.session.server_side import ServerSideSessionConfig
from litestar.static_files import create_static_files_router
from litestar.status_codes import (
    HTTP_404_NOT_FOUND,
    HTTP_423_LOCKED,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_403_FORBIDDEN,
    HTTP_400_BAD_REQUEST,
)

from litestar.stores.base import Store
from litestar.template import TemplateConfig
from litestar.types import ControllerRouterHandler, Middleware
from litestar.middleware.base import DefineMiddleware

from common import BASE_DIR, TMP_DIR, DEVEL_ENV
from common.exception import DatabaseInaccessibleException
from common.i18n import gettext, ngettext
from data.input_output import OnlineDataSourceManager

from plugins.manager import plugin_manager
from web.controllers.admin.display_controller_admin_controller import (
    DisplayControllerAdminController,
)
from web.controllers.admin.event_admin_controller import EventAdminController
from web.controllers.admin.event_documents_controller import EventDocumentsController
from web.controllers.admin.family_admin_controller import FamilyAdminController
from web.controllers.admin.index_admin_controller import IndexAdminController
from web.controllers.admin.championship_admin_controller import (
    ChampionshipAdminController,
)
from web.controllers.admin.place_card_template_admin_controller import (
    PlaceCardTemplateAdminController,
)
from web.controllers.admin.player_admin_controller import PlayerAdminController
from web.controllers.admin.prize_admin_controller import PrizeAdminController
from web.controllers.admin.prize_config_admin_controller import (
    PrizeConfigAdminController,
)
from web.controllers.profile_controller import ProfileController
from web.controllers.admin.rotator_admin_controller import RotatorAdminController
from web.controllers.admin.menu_admin_controller import MenuAdminController
from web.controllers.admin.screen_config_admin_controller import (
    ScreenConfigAdminController,
)
from web.controllers.admin.screen_admin_controller import ScreenAdminController
from web.controllers.admin.pairings_admin_controller import PairingsAdminController
from web.controllers.admin.team_admin_controller import TeamAdminController
from web.controllers.admin.timer_admin_controller import TimerAdminController
from web.controllers.admin.tournament_admin_controller import TournamentAdminController
from web.controllers.admin.account_admin_controller import AccountAdminController
from web.controllers.index_controller import IndexController
from web.controllers.qrcode_controller import QRCodeController
from web.controllers.user.screen_user_controller import ScreenUserController
from web.controllers.user.input_user_controller import InputUserController
from web.sqlite_store import SQLiteStore
from web.session_backend import SkipUnchangedSessionBackend
from web.performance import current_request_performance, record_template

static_files_base_dir = BASE_DIR / 'src/web/static'

static_files_folders = [
    static_files_base_dir,
    *plugin_manager.static_paths,
]

static_files_router: Router = create_static_files_router(
    path='/static',
    directories=list(static_files_folders),
    name='static',
    cache_control=CacheControlHeader(max_age=0 if DEVEL_ENV else 3600),
)

_route_handlers: Sequence[ControllerRouterHandler] = [
    IndexController,
    ScreenUserController,
    InputUserController,
    IndexAdminController,
    ChampionshipAdminController,
    EventAdminController,
    EventDocumentsController,
    PlaceCardTemplateAdminController,
    TournamentAdminController,
    TeamAdminController,
    PairingsAdminController,
    PrizeConfigAdminController,
    PrizeAdminController,
    ScreenConfigAdminController,
    ScreenAdminController,
    TimerAdminController,
    FamilyAdminController,
    RotatorAdminController,
    MenuAdminController,
    PlayerAdminController,
    DisplayControllerAdminController,
    QRCodeController,
    AccountAdminController,
    ProfileController,
    static_files_router,
    # Plugin controllers
    *[
        controller
        for plugin in plugin_manager.all_plugins
        for controller in plugin.controllers
    ],
]

route_handlers = _route_handlers

exception_handlers = {
    HTTP_400_BAD_REQUEST: IndexController.handle_exception,
    HTTP_403_FORBIDDEN: IndexController.handle_exception,
    HTTP_404_NOT_FOUND: IndexController.handle_exception,
    HTTP_423_LOCKED: IndexController.handle_exception,
    HTTP_500_INTERNAL_SERVER_ERROR: IndexController.handle_exception,
    # A write action (event update, pairing…) reaching an event whose file has
    # become locked opens the database directly, so it raises this exception
    # instead of an HTTP 423. Map it to the same locked-event error page.
    DatabaseInaccessibleException: IndexController.handle_database_inaccessible,
}


@listener('connected')
async def load_first_online_data_sources_connection_status():
    for data_source in OnlineDataSourceManager().objects():
        if data_source.connection_status is None:
            await data_source.reload_connection_status()


listeners = [load_first_online_data_sources_connection_status]


class FileSystemLoaderWithRelativePath(FileSystemLoader):
    """override super().get_source() to allow .. in the template."""

    def get_source(
        self,
        environment: Environment,
        template: str,
    ) -> t.Tuple[str, str, t.Callable[[], bool]]:
        # pieces = self.split_template_path(template)
        pieces: list[str] = template.split('/')

        for searchpath in self.searchpath:
            # Use posixpath even on Windows to avoid "drive:" or UNC
            # segments breaking out of the search directory.
            filename = posixpath.join(searchpath, *pieces)
            if os.path.isfile(filename):
                break
        else:
            plural = 'path' if len(self.searchpath) == 1 else 'paths'
            paths_str = ', '.join(repr(p) for p in self.searchpath)
            raise TemplateNotFound(
                template,
                f'{template!r} not found in search {plural}: {paths_str}',
            )

        with open(filename, encoding=self.encoding) as f:
            contents = f.read()

        mtime = os.path.getmtime(filename)

        def uptodate() -> bool:
            try:
                return os.path.getmtime(filename) == mtime
            except OSError:
                return False

        # Use normpath to convert Windows altsep to sep.
        return contents, os.path.normpath(filename), uptodate


_render_contexts: ContextVar[list[JinjaContext] | None] = ContextVar(
    'sharly_chess_jinja_render_contexts', default=None
)


class ReleasableJinjaContext(JinjaContext):
    """A Jinja context that releases request data after rendering.

    Macros form cycles with their context. Only per-render contexts may be
    cleared; cached global-only macro contexts must remain intact.
    """

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        contexts = _render_contexts.get()
        if contexts is not None and set(self.parent).difference(self.globals_keys):
            # Global-only contexts belong to cached macro modules.
            contexts.append(self)

    def release(self) -> None:
        """Detach request data and break macro cycles after rendering."""
        self.parent.clear()
        self.vars.clear()
        self.exported_vars.clear()
        self.blocks.clear()


class ProfiledJinjaTemplate(JinjaTemplate):
    """Profile rendering and release its request-owned Jinja contexts."""

    def render(self, *args: t.Any, **kwargs: t.Any) -> str:
        profile = current_request_performance()
        start: float | None = None
        if profile is not None:
            from time import perf_counter

            start = perf_counter()
        contexts: list[JinjaContext] = []
        # Collect contexts created by nested templates during this render.
        token = _render_contexts.set(contexts)
        try:
            return super().render(*args, **kwargs)
        finally:
            # Release contexts after successful and failed renders.
            for context in contexts:
                assert isinstance(context, ReleasableJinjaContext)
                context.release()
            _render_contexts.reset(token)
            if start is not None:
                from time import perf_counter

                record_template(self.name, perf_counter() - start)


class SharlyChessEnvironment(Environment):
    """Override to:
    - have a join_path() method that accepts relative path from the template that call %include, %extends and %from
    - use a loader that accepts relative path with ..
    - load the gettext methods"""

    def __init__(
        self,
        directories: list[Path],
    ) -> None:
        template_loader: FileSystemLoader = FileSystemLoaderWithRelativePath(
            searchpath=directories
        )
        super().__init__(
            loader=template_loader,
            autoescape=True,
            trim_blocks=True,
            auto_reload=DEVEL_ENV,
        )
        self.context_class = ReleasableJinjaContext
        self.template_class = ProfiledJinjaTemplate
        self.add_extension('jinja2.ext.i18n')
        self.install_gettext_callables(  # type: ignore
            gettext=gettext, ngettext=ngettext, newstyle=True
        )
        self.add_extension('jinja2.ext.do')

    def join_path(self, template: str, parent: str) -> str:
        return str(Path(parent).parent / template)


template_dirs: list[Path] = [
    BASE_DIR / 'src/web/templates',
    *[path for path in plugin_manager.templates_paths],
    # lib files can be included in print view to build self-contained files
    BASE_DIR / 'src/web/static',
]

template_engine: JinjaTemplateEngine = JinjaTemplateEngine(
    engine_instance=SharlyChessEnvironment(template_dirs),
)

# create the Jinja config that will be passed to the Litestar app
template_config: TemplateConfig = TemplateConfig(
    engine=template_engine,
    # engine_callback=register_template_callables,
)


sessions_path: Path = TMP_DIR / 'session.db'


def create_sessions_database(path: Path):
    database = sqlite3.connect(path)
    cursor = database.cursor()
    cursor.execute(
        'CREATE TABLE IF NOT EXISTS store(key TEXT PRIMARY KEY, data BLOB, expires_at)'
    )
    cursor.execute('CREATE INDEX IF NOT EXISTS expiry_index ON store(expires_at)')
    database.commit()
    cursor.close()
    database.close()
    return None


create_sessions_database(sessions_path)


async def create_connection(path: os.PathLike[str]) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(Path(path))
    # Apply high-performance pragmas
    await conn.execute('PRAGMA journal_mode = WAL')
    await conn.execute('PRAGMA synchronous = NORMAL')
    await conn.execute('PRAGMA cache_size = 10000')
    await conn.execute('PRAGMA temp_store = MEMORY')
    await conn.execute('PRAGMA foreign_keys = ON')
    await conn.execute('PRAGMA mmap_size = 268435456')

    return conn


session_pool = SQLiteConnectionPool(
    connection_factory=partial(create_connection, sessions_path),
    pool_size=10,
    acquisition_timeout=30,
)

stores: dict[str, Store] = {'sessions': SQLiteStore(session_pool)}

_session_config = ServerSideSessionConfig(
    key='sharly-chess-session',
    exclude=[
        r'^/static/*',
        r'^/ws$',
        r'.*\.(png|jpg|jpeg|gif|css|js|svg|ico|json)$',
    ],
)

middlewares: Sequence[Middleware] = [
    DefineMiddleware(
        SessionMiddleware,
        backend=SkipUnchangedSessionBackend(config=_session_config),
    ),
]

from os import urandom
from pathlib import Path
from typing import Sequence

from litestar import Router
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.middleware.session.client_side import CookieBackendConfig
from litestar.static_files import create_static_files_router
from litestar.template import TemplateConfig
from litestar.types import ControllerRouterHandler, Middleware

from web.views import (delete_illegal_move, index, show_event, login, show_screen, show_rotator, show_rotator_screen,
                       update_result, get_screen_last_update, download_event, download_tournament, add_illegal_move,
                       toggle_player_check_in)

BASE_DIR = Path(__file__).resolve().parent.parent

static_files_folders = [
    BASE_DIR / 'web' / 'static',
    Path().absolute() / 'custom',
]

static_files_router: Router = create_static_files_router(
    path='/static',
    directories=static_files_folders,
    name='static',
)

route_handlers: Sequence[ControllerRouterHandler] = [
    index,
    show_event,
    login,
    show_screen,
    show_rotator,
    show_rotator_screen,
    update_result,
    add_illegal_move,
    delete_illegal_move,
    toggle_player_check_in,
    get_screen_last_update,
    download_event,
    download_tournament,
    static_files_router,
]

template_config: TemplateConfig = TemplateConfig(
        directory=BASE_DIR / 'web' / 'templates',
        engine=JinjaTemplateEngine)

middlewares: Sequence[Middleware] = [
    CookieBackendConfig(secret=urandom(16)).middleware,
]

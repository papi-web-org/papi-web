from os import urandom
from pathlib import Path
from typing import Sequence

from litestar import Router
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.middleware.session.client_side import CookieBackendConfig
from litestar.static_files import create_static_files_router
from litestar.template import TemplateConfig
from litestar.types import ControllerRouterHandler, Middleware

from web.views import (index,
                       render_event, htmx_render_event_if_updated,
                       htmx_login,
                       render_screen, htmx_render_screen_if_updated,
                       render_rotator,
                       htmx_render_rotator_screen,
                       htmx_render_boards_screen_board_result_modal,
                       htmx_add_board_result,
                       htmx_delete_board_result,
                       htmx_download_event_tournaments, htmx_download_tournament,
                       htmx_add_illegal_move, htmx_delete_illegal_move,
                       htmx_toggle_player_check_in,
                       htmx_render_boards_screen_set_if_updated,
                       htmx_render_players_screen_set_if_updated,
                       render_manage,
                       htmx_update_manage_main_selector, htmx_update_manage_event_selector,
                       )

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
    render_event,
    htmx_render_event_if_updated,
    htmx_login,
    render_screen,
    htmx_render_screen_if_updated,
    render_rotator,
    htmx_render_rotator_screen,
    htmx_render_boards_screen_board_result_modal,
    htmx_add_board_result,
    htmx_delete_board_result,
    htmx_add_illegal_move,
    htmx_delete_illegal_move,
    htmx_toggle_player_check_in,
    htmx_render_boards_screen_set_if_updated,
    htmx_render_players_screen_set_if_updated,
    htmx_download_event_tournaments,
    htmx_download_tournament,
    render_manage,
    htmx_update_manage_main_selector,
    htmx_update_manage_event_selector,
    static_files_router,
]

template_config: TemplateConfig = TemplateConfig(
        directory=BASE_DIR / 'web' / 'templates',
        engine=JinjaTemplateEngine)

middlewares: Sequence[Middleware] = [
    CookieBackendConfig(secret=urandom(16)).middleware,
]

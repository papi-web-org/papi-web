from os import urandom
from pathlib import Path
from typing import Sequence

from litestar import Router
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.middleware.session.client_side import CookieBackendConfig
from litestar.static_files import create_static_files_router
from litestar.template import TemplateConfig
from litestar.types import ControllerRouterHandler, Middleware

from web.views import LoginController, IndexController
from web.views_admin import AdminController
from web.views_admin_chessevent import AdminChessEventController
from web.views_admin_event import AdminEventController
from web.views_admin_timer import AdminTimerController
from web.views_admin_tournament import AdminTournamentController
from web.views_admin_screen import AdminScreenController
from web.views_admin_family import AdminFamilyController
from web.views_admin_rotator import AdminRotatorController
from web.views_user import UserController

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
    LoginController,
    IndexController,
    UserController,
    AdminController,
    AdminEventController,
    AdminChessEventController,
    AdminTournamentController,
    AdminScreenController,
    AdminTimerController,
    AdminFamilyController,
    AdminRotatorController,
    static_files_router,
]

template_config: TemplateConfig = TemplateConfig(
        directory=BASE_DIR / 'web' / 'templates',
        engine=JinjaTemplateEngine)

middlewares: Sequence[Middleware] = [
    CookieBackendConfig(secret=urandom(16)).middleware,
]

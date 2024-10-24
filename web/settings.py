from os import urandom
from pathlib import Path
from typing import Sequence

from litestar import Router
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.middleware.session.client_side import CookieBackendConfig
from litestar.static_files import create_static_files_router
from litestar.template import TemplateConfig
from litestar.types import ControllerRouterHandler, Middleware

from common.papi_web_config import PapiWebConfig
from web.controllers.index_controller import IndexController
from web.controllers.admin.index_admin_controller import IndexAdminController
from web.controllers.admin.chessevent_admin_controller import ChessEventAdminController
from web.controllers.admin.event_admin_controller import EventAdminController
from web.controllers.admin.family_admin_controller import FamilyAdminController
from web.controllers.admin.rotator_admin_controller import RotatorAdminController
from web.controllers.admin.screen_admin_controller import ScreenAdminController
from web.controllers.admin.timer_admin_controller import TimerAdminController
from web.controllers.admin.tournament_admin_controller import TournamentAdminController
from web.controllers.background_controller import BackgroundController
from web.controllers.user.index_user_controller import IndexUserController
from web.controllers.user.event_user_controller import EventUserController
from web.controllers.user.screen_user_controller import ScreenUserController
from web.controllers.user.screen_set_user_controller import ScreenSetUserController
from web.controllers.user.tournament_user_controller import CheckInUserController, IllegalMoveUserController, \
    ResultUserController, DownloadUserController

BASE_DIR = Path(__file__).resolve().parent.parent

static_files_folders = [
    BASE_DIR / 'web' / 'static',
    PapiWebConfig.custom_path,
]

static_files_router: Router = create_static_files_router(
    path='/static',
    directories=static_files_folders,
    name='static',
)


route_handlers: Sequence[ControllerRouterHandler] = [
    IndexController,
    BackgroundController,
    IndexUserController,
    EventUserController,
    ScreenUserController,
    ScreenSetUserController,
    ResultUserController,
    CheckInUserController,
    IllegalMoveUserController,
    DownloadUserController,
    IndexAdminController,
    EventAdminController,
    ChessEventAdminController,
    TournamentAdminController,
    ScreenAdminController,
    TimerAdminController,
    FamilyAdminController,
    RotatorAdminController,
    static_files_router,
]

template_config: TemplateConfig = TemplateConfig(
        directory=BASE_DIR / 'web' / 'templates',
        engine=JinjaTemplateEngine)

middlewares: Sequence[Middleware] = [
    CookieBackendConfig(secret=urandom(16)).middleware,
]

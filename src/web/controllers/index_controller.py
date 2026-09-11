import json
from typing import AsyncGenerator

from litestar import Response, get, route, HttpMethod, status_codes, websocket_stream
from litestar.channels import ChannelsPlugin
from litestar.config.response_cache import CACHE_FOREVER
from litestar.di import NamedDependency
from litestar.exceptions import HTTPException
from litestar.params import FromPath, FromQuery
from litestar.plugins.htmx import HTMXRequest, HTMXTemplate
from litestar.response import Redirect, Template
from litestar.status_codes import HTTP_204_NO_CONTENT

from common.i18n import _
from common.sharly_chess_config import SharlyChessConfig
from web.controllers.admin.base_admin_controller import AdminWebContext
from web.controllers.admin.index_admin_controller import IndexAdminController
from web.controllers.base_controller import BaseController, WebContext
from web.remote_access import remote_identity
from web.session import SessionEventsShowDetails


class IndexController(BaseController):
    ALL_HTTP_METHODS: list[HttpMethod] = [
        HttpMethod.GET,
        HttpMethod.POST,
        HttpMethod.PATCH,
        HttpMethod.PUT,
        HttpMethod.HEAD,
        HttpMethod.OPTIONS,
    ]

    @get(
        path='/',
        name='index',
    )
    async def index(
        self,
        request: HTMXRequest,
        locale: FromQuery[str | None] = None,
        show_details: FromQuery[bool | None] = None,
    ) -> Template | Redirect:
        web_context = AdminWebContext(request)
        self.set_locale(request, locale)
        if show_details is not None:
            SessionEventsShowDetails(request).set(show_details)
        return IndexAdminController._admin_render(web_context)

    @get(
        path='/empty-modal',
        name='empty-modal',
    )
    async def empty_modal(
        self,
    ) -> Template:
        return HTMXTemplate(
            template_name='common/empty_modal.html',
            re_target='#modal-wrapper',
        )

    @get(
        path='/robots.txt',
        name='robots',
        cache=CACHE_FOREVER,
    )
    async def robots(self, request: HTMXRequest) -> Response[str]:
        """Ask crawlers to leave the event alone.

        A tournament's screens are of no use in a search engine, and an event
        that has finished should not go on being served from one. This is a
        request rather than a barrier: it is honoured by the crawlers that
        index, and ignored by the ones probing for files the server has never
        had.
        """
        return Response(
            'User-agent: *\nDisallow: /\n',
            media_type='text/plain',
        )

    @get(
        path='/favicon.ico',
        name='favicon',
        cache=CACHE_FOREVER,
    )
    async def favicon(
        self,
        request: HTMXRequest,
    ) -> Redirect:
        return Redirect(
            request.app.route_reverse(
                'static',
                file_path='/images/sharly-chess.ico',
                version=SharlyChessConfig.version,
            )
        )

    @staticmethod
    def _error_template(
        request: HTMXRequest,
        status_code: int,
    ) -> HTMXTemplate:
        reload_message: str | None = None
        title: str
        error_message: str
        if request.htmx:
            reload_message = _('Reload the page')
        match status_code:
            case status_codes.HTTP_400_BAD_REQUEST:
                title = _('400 - Bad request')
                error_message = _('Consult the logs for more details.')
            case status_codes.HTTP_401_UNAUTHORIZED:
                title = _('401 - Authentication failed')
                error_message = _('Sorry, authorization failed.')
                if request.htmx:
                    reload_message = _('Retry')
            case status_codes.HTTP_403_FORBIDDEN:
                title = _('403 - Access Forbidden')
                error_message = _('Sorry, you are not allowed to access this page.')
                if request.htmx:
                    reload_message = _('Retry')
            case status_codes.HTTP_404_NOT_FOUND:
                title = _('404 - Page Not Found')
                error_message = _('Sorry, the page you are looking for does not exist.')
                reload_message = None
            case status_codes.HTTP_423_LOCKED:
                title = _('The event could not be opened')
                error_message = _(
                    'The event is present on the server but could not be opened. It may be '
                    'temporarily locked by another program, by file synchronisation '
                    '(OneDrive, Google Drive, DropBox, etc.) or by antivirus software. Wait '
                    'a moment and try again. If it keeps happening, move the data folder '
                    'out of any synchronised location (Console > Parameters > Data folder < Move).'
                )
                reload_message = reload_message or _('Retry')
            case status_codes.HTTP_500_INTERNAL_SERVER_ERROR:
                title = _('500 - Internal Server Error')
                error_message = _('Sorry, an unexpected error has occurred.')
            case _:
                title = _('{status_code} - Unknown error').format(
                    status_code=status_code
                )
                error_message = _('An unexpected error occurred.')
        return HTMXTemplate(
            template_name='error.html',
            context=WebContext(request).template_context
            | {
                'reload_message': reload_message,
                'error_title': title,
                'error_message': error_message,
            },
            re_target='body',
        )

    @classmethod
    def handle_exception(
        cls, request: HTMXRequest, exception: HTTPException
    ) -> Redirect | HTMXTemplate:
        return cls._render_error(request, getattr(exception, 'status_code', 500))

    @classmethod
    def handle_database_inaccessible(
        cls, request: HTMXRequest, exception: Exception
    ) -> Redirect | HTMXTemplate:
        # An event file that opened fine at page load can become locked (another
        # program, file sync, antivirus…) before a later action reaches it. Such
        # actions open the database directly, without going through get_event, so
        # the raised DatabaseInaccessibleException is mapped to the 423 page here
        # rather than surfacing as a generic 500 error.
        return cls._render_error(request, status_codes.HTTP_423_LOCKED)

    @classmethod
    def _render_error(
        cls, request: HTMXRequest, status_code: int
    ) -> Redirect | HTMXTemplate:
        # Prevent infinite redirect loops if the error handler itself fails
        if request.url.path.startswith('/error/'):
            return cls._error_template(request, status_code)

        # A locked event may become accessible again once the lock is released,
        # so the error is rendered on the original URL (rather than redirecting to
        # /error/423) to let the "Retry" link re-request that same URL.
        if request.htmx or status_code == status_codes.HTTP_423_LOCKED:
            return cls._error_template(request, status_code)
        return Redirect(
            path=request.app.route_reverse('http-error', status_code=status_code)
        )

    @route(
        http_method=ALL_HTTP_METHODS,
        path='/error/{status_code:int}',
        name='http-error',
    )
    async def handle_http_error(
        self, request: HTMXRequest, status_code: FromPath[int]
    ) -> HTMXTemplate:
        return self._error_template(request, status_code)

    @websocket_stream('/ws')
    async def ws_handler(
        self, channels: NamedDependency[ChannelsPlugin]
    ) -> AsyncGenerator[dict, None]:
        async with channels.start_subscription(['ws']) as subscriber:
            async for raw_event in subscriber.iter_events():
                event = (
                    json.loads(raw_event)
                    if isinstance(raw_event, (bytes, str))
                    else raw_event
                )
                yield event

    @get('/.well-known/appspecific/com.chrome.devtools.json')
    async def chrome_devtools_placeholder(self) -> Response:
        return Response(content='{}', media_type='application/json')

    @get('/.well-known/sharly-chess-instance')
    async def remote_access_instance(self, request: HTMXRequest) -> Response:
        """Answers which event is behind this hostname, for whoever issued it.

        Unguarded on purpose: it is asked from outside, before anyone has
        logged in, and it says nothing an attacker gains by. The nonce is only
        useful to whoever handed it down."""
        identity = remote_identity(request.headers.get('host', ''))
        if identity is None:
            # Answered rather than raised: the application turns a raised 404
            # into a redirect to a page for a person to read, and this is read
            # by the control plane.
            return Response(
                content={},
                media_type='application/json',
                status_code=status_codes.HTTP_404_NOT_FOUND,
                headers={'Cache-Control': 'no-store'},
            )
        return Response(
            content={
                'remote_uniq_id': identity.remote_uniq_id,
                'instance_nonce': identity.instance_nonce,
            },
            media_type='application/json',
            headers={'Cache-Control': 'no-store'},
        )

    @get(
        path=[
            '/apple-touch-icon.png',
            '/apple-touch-icon-precomposed.png',
            '/currentsetting.htm',
        ],
    )
    async def no_content(self) -> Response:
        return Response(status_code=HTTP_204_NO_CONTENT, content=None)

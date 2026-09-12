import asyncio
import platform
import signal
import socket
import sys
import time
from threading import Thread
from time import sleep
from types import FrameType
from typing import Callable, ClassVar, cast
from webbrowser import open

import requests
import uvicorn
from litestar import Litestar
from litestar.config.compression import CompressionConfig
from litestar.exceptions import (
    MethodNotAllowedException,
    PermissionDeniedException,
    NotFoundException,
    ClientException,
    ValidationException,
)
from litestar.logging import LoggingConfig
from litestar.plugins.htmx import HTMXRequest
from litestar.types import ASGIApp, Scope, HTTPScope

from common import REQUEST_TIMEOUT, TEST_ENV
from common.installation_checker import InstallationChecker
from common.data_recovery import DataRecovery
from common.logger import get_logger, set_logging_config
from common.network import NetworkMonitor
from common.sharly_chess_config import SharlyChessConfig
from data.input_output import DataSourceManager
from web.channels import channels_plugin
from web.garbage_collection import RequestGarbageCollectionMiddleware
from web.performance import PerformanceMiddleware
from web.tunnel import request_is_tunnelled
from web.remote_access_manager import (
    resume_session_in_background,
    stop_all_sessions,
)
from web.settings import (
    route_handlers,
    template_config,
    middlewares,
    stores,
    exception_handlers,
    listeners,
)

logger = get_logger()

HANDLED_SIGNALS: list[int] = [
    signal.SIGINT,  # Unix signal 2. Sent by Ctrl+C.
    signal.SIGTERM,  # Unix signal 15. Sent by `kill <pid>`.
]
if sys.platform == 'win32':  # pragma: py-not-win32
    HANDLED_SIGNALS.append(signal.SIGBREAK)  # Windows signal 21. Sent by Ctrl+Break.

_PORT_TIMEOUT = 10  # Timeout when looking for a specific port


def launch_browser(url: str):
    # Set the locale as the function is called in a new thread.
    SharlyChessConfig().load_and_set_env()
    logger.info(f'Opening the welcome page [{url}] in a browser…')
    while True:
        try:
            requests.get(url, timeout=REQUEST_TIMEOUT)
            break
        except requests.RequestException as e:
            msg = 'Web server not started yet ({ex}), waiting…'.format(
                ex=e.__class__.__name__
            )
            if isinstance(e, requests.TooManyRedirects) and e.response is not None:
                msg += f' History: {[r.url for r in e.response.history]}'
            logger.info(msg)
            sleep(1)
    open(url, new=2)


class ServerEngine:
    app: ClassVar[Litestar | None] = None
    server: ClassVar[uvicorn.Server | None] = None

    def __init__(
        self,
        debug: bool = False,
        profile: bool = False,
        port: int | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        handle_signals: bool = True,
        on_port_chosen: Callable[[], None] | None = None,
    ):
        self.debug = debug
        self.profile = profile
        self.handle_signals = handle_signals
        self.port = port
        self.on_port_chosen = on_port_chosen

        # before all the rest, initialize a SharlyChessConfig instance to set the language.
        config = SharlyChessConfig()
        config.load_and_set_env()
        logger.info(
            'Sharly Chess %s - %s - %s',
            config.version,
            config.copyright,
            config.web_url,
        )
        logger.info('Locale: %s', config.locale)
        if not InstallationChecker.check():
            return
        if not TEST_ENV:
            DataRecovery.setup()

        self.loop = self._ensure_loop(loop)

    def _ensure_loop(
        self, loop: asyncio.AbstractEventLoop | None
    ) -> asyncio.AbstractEventLoop:
        if loop is not None:
            return loop
        # Try running loop first (inside an event-loop callback)
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            pass
        # No current running loop -> create & set one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop

    async def serve(self):
        logger.debug('System information:')
        logger.debug(
            ' - Machine/processor: %s/%s', platform.machine(), platform.processor()
        )
        logger.debug(' - Platform: %s', platform.platform())
        logger.debug(' - Architecture: %s', ' '.join(platform.architecture()))
        logger.info('Starting Sharly Chess server, Please wait…')
        sc_config = SharlyChessConfig()
        logger.info(f'Console logging level: {sc_config.console_log_level_str}')

        for data_source in DataSourceManager().objects():
            data_source.on_app_init()

        if self.port:
            for __ in range(_PORT_TIMEOUT):
                if not self.__port_in_use(self.port):
                    sc_config.web_port = self.port
                    break
                logger.debug(f'Port {self.port} already in use (waiting)')
                time.sleep(1)
            if not sc_config.web_port:
                logger.info(
                    f'Timeout exceeded for port {self.port}, fallback to other ports'
                )
        if not sc_config.web_port:
            for port in sc_config.web_ports:
                if not self.__port_in_use(port):
                    sc_config.web_port = port
                    break
                logger.debug(f'Port {port} already in use')
            if sc_config.web_port is None:
                ports_str = ', '.join(str(port) for port in sc_config.web_ports)
                logger.error(
                    f'All the candidate ports [{ports_str}] are already'
                    f' in use, can not start Sharly Chess server.'
                )
                return

        if self.on_port_chosen:
            self.on_port_chosen()

        logger.info(f'Port: {sc_config.web_port}')
        logger.info(f'Local URL: {sc_config.local_url}')

        if sc_config.launch_browser:
            Thread(target=launch_browser, args=(sc_config.local_url,)).start()

        NetworkMonitor.start_monitoring()

        logging_config = set_logging_config(
            console_log_level=sc_config.console_log_level,
        )

        def log_http_exception(exc: Exception, scope: Scope):
            if not scope['type'] == 'http':
                return
            if isinstance(exc, PermissionDeniedException):
                prefix = '403 permission denied'
            elif isinstance(exc, NotFoundException):
                prefix = '404 not found'
            elif isinstance(exc, ClientException) and exc.status_code == 400:
                prefix = '400 bad request'
            else:
                return
            http = cast(HTTPScope, scope)
            # Anything reachable from the internet is found within minutes and
            # probed continuously for files it has never had. Said once per
            # request at the level real faults are reported, that noise buries
            # them. From the venue network the same request is worth seeing.
            log = logger.debug if request_is_tunnelled(scope) else logger.error
            log(
                '%s: %s %s\n%s',
                prefix,
                http.get('method', '?'),
                http.get('path', '?'),
                exc,
            )

        app: Litestar = Litestar(
            debug=self.debug,
            request_class=HTMXRequest,
            # Said on every response as well as in robots.txt, because a
            # crawler that arrives at a page by following a link elsewhere has
            # no reason to have read the file first.
            response_headers={'X-Robots-Tag': 'noindex, nofollow'},
            route_handlers=route_handlers,
            exception_handlers=exception_handlers,  # type: ignore
            template_config=template_config,
            # Favor response latency over maximum compression.
            compression_config=CompressionConfig(backend='gzip', gzip_compress_level=3),
            logging_config=LoggingConfig(
                **logging_config,
                # Litestar's default only logs exceptions when debug=True.
                log_exceptions='always',
                disable_stack_trace={
                    400,
                    403,
                    404,
                    ClientException,
                    ValidationException,
                    PermissionDeniedException,
                    NotFoundException,
                    MethodNotAllowedException,
                },
            ),  # type: ignore
            after_exception=[log_http_exception],
            middleware=middlewares,
            stores=stores,
            pdb_on_exception=self.debug,
            plugins=[channels_plugin],
            listeners=listeners,
        )
        self.__class__.app = app
        asgi_app: ASGIApp = RequestGarbageCollectionMiddleware(app)
        if self.profile:
            asgi_app = PerformanceMiddleware(asgi_app)

        config = uvicorn.Config(
            app=asgi_app,
            host=sc_config.web_host,
            port=sc_config.web_port,
            log_config=logging_config,
            timeout_graceful_shutdown=5,
        )
        server = uvicorn.Server(config)
        self.__class__.server = server

        def handle_exit(sig_: int, frame: FrameType | None) -> None:
            server.should_exit = True
            server.force_exit = True

        # We need to handle signals ourselves in order to gracefully shut down the SSE connections.
        # Calling `serve` doesn't allow us to intercept signals, so we use `_serve` instead.  The only
        # difference is that `serve` captures signals before calling `_serve` internally.

        if self.handle_signals:
            import threading

            if threading.current_thread() is threading.main_thread():
                for sig in HANDLED_SIGNALS:
                    signal.signal(sig, handle_exit)

        sockets: list[socket.socket] = [
            self.__bind_socket(sc_config.web_host, sc_config.web_port)
        ]
        tunnel_socket: socket.socket | None = self.__bind_tunnel_socket()
        if tunnel_socket is not None:
            sockets.append(tunnel_socket)

        # Only once the listener the tunnel client connects to is bound, since
        # resuming an event raises a tunnel that dials straight back into it.
        resume_session_in_background()

        try:
            await server._serve(sockets=sockets)
        finally:
            # Giving the leases up is what lets another machine pick these
            # events up without waiting for them to lapse.
            stop_all_sessions()

    @staticmethod
    def __bind_tunnel_socket() -> socket.socket | None:
        """Bind the loopback listener the tunnel client connects to.

        The port is the one thing that tells a request arriving from the
        internet apart from the arbiter's own browser, so it is recorded as the
        listener is bound rather than chosen in advance: between finding a port
        free and taking it, another program can take it first.

        Remote access is the only thing lost if no port can be had, so the
        server goes on serving the local network either way.
        """
        sc_config = SharlyChessConfig()
        for candidate in sc_config.web_tunnel_ports or [0]:
            try:
                sock = ServerEngine.__bind_socket(sc_config.web_tunnel_host, candidate)
            except OSError as error:
                logger.debug(f'Tunnel port {candidate} unavailable: {error}')
                continue
            sc_config.web_tunnel_port = sock.getsockname()[1]
            logger.info(f'Tunnel port: {sc_config.web_tunnel_port}')
            return sock
        logger.warning('No tunnel port could be bound, remote access is unavailable.')
        return None

    @staticmethod
    def __bind_socket(host: str, port: int) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        return sock

    @staticmethod
    def __port_in_use(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0

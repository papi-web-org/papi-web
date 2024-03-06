from threading import Thread
from time import sleep

import pyodbc
import requests
from webbrowser import open
import socket
from logging import Logger
from litestar import Litestar
import uvicorn
from litestar.config.allowed_hosts import AllowedHostsConfig

from common.logger import get_logger
from common.engine import Engine
import platform

from web.settings import route_handlers, template_config, middlewares

logger: Logger = get_logger()


def launch_browser(url: str):
    logger.info(f'Opening the welcome page [{url}] in a browser...')
    while True:
        try:
            requests.get(url)
            break
        except requests.RequestException as e:
            logger.debug(f'Web server not started yet ({e.__class__.__name__}), waiting...')
            sleep(1)
    open(url, new=2)


class ServerEngine(Engine):
    def __init__(self):
        logger.info(f'Starting Papi-web server, please wait...')
        super().__init__()
        logger.debug('ODBC drivers found:')
        for driver in pyodbc.drivers():
            logger.debug(f' - {driver}')
        logger.debug('System information:')
        logger.debug(f' - Machine/processor: {platform.machine()}/{platform.processor()}')
        logger.debug(f' - Platform: {platform.platform()}')
        logger.debug(f' - Architecture: {" ".join(platform.architecture())}')
        logger.info(f'log: {self._config.log_level_str}')
        logger.info(f'port: {self._config.web_port}')
        logger.info(f'local URL: {self._config.local_url}')
        if self._config.lan_url:
            logger.info(f'LAN/WAN URL: {self._config.lan_url}')
        if self.__port_in_use(self._config.web_port):
            logger.error(f'Port [{self._config.web_port}] already in use, can not start Papi-web server')
            return
        if self._config.web_launch_browser:
            Thread(target=launch_browser, args=(self._config.local_url, )).start()
        app: Litestar = Litestar(
            debug=True,
            route_handlers=route_handlers,
            template_config=template_config,
            middleware=middlewares,
            allowed_hosts=AllowedHostsConfig(
                allowed_hosts=["*"],
            ),
        )
        uvicorn.run(app, port=self._config.web_port, log_level='info')

    @staticmethod
    def __port_in_use(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0

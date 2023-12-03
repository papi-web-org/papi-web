import os

import django
from django.core.management import call_command
from webbrowser import open
import socket
from logging import Logger

from common.logger import get_logger
from common.engine import Engine

logger: Logger = get_logger()


class ServerEngine(Engine):
    def __init__(self):
        super().__init__()
        logger.info(f'log: {self._config.log_level_str}')
        logger.info(f'host: {self._config.web_host}')
        logger.info(f'port: {self._config.web_port}')
        logger.info(f'local URL: {self._config.local_url}')
        if self._config.lan_url:
            logger.info(f'LAN/WAN URL: {self._config.lan_url}')
        logger.info(f'Setting up Django...')
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web.settings')
        django.setup()
        if self.__port_in_use(self._config.web_port):
            logger.error(f'Port [{self._config.web_port}] already in use, can not start Papi-web server')
            return
        if self._config.web_launch_browser:
            logger.info(f'Opening the welcome page [{self._config.local_url}] in a browser...')
            open(self._config.local_url, new=2)
        logger.info(f'Starting Papi-web server, please wait...')
        call_command(
            'runserver',
            [
                f'{self._config.web_host}:{self._config.web_port}',
                '--noreload',
            ]
        )

    @staticmethod
    def __port_in_use(port: int):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0

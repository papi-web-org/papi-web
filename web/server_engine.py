import os
import django
from data.event import get_events
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
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web.settings')
        logger.info('log: {}'.format(self._config.log_level_str))
        logger.info('host: {}'.format(self._config.web_host))
        logger.info('port: {}'.format(self._config.web_port))
        logger.info('local URL: {}'.format(self._config.local_url))
        if self._config.lan_url:
            logger.info('LAN/WAN URL: {}'.format(self._config.lan_url))
        get_events(silent=False)
        logger.info('Setting up Django...')
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web.settings')
        django.setup()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', self._config.web_port)) == 0:
                logger.error('Port [{}] already in use, can not start Papi-web server'.format(self._config.web_port))
                return
        if self._config.web_launch_browser:
            logger.info('Opening the welcome page [{}] in a browser...'.format(self._config.local_url))
            open(self._config.local_url, new=2)
        logger.info('Starting Papi-web server, please wait...')
        call_command(
            'runserver',
            [
                '{}:{}'.format(self._config.web_host, self._config.web_port),
                '--noreload',
            ]
        )

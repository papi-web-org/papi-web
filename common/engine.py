import logging
import os
from logging import Logger

from common.config_reader import TMP_DIR
from common.papi_web_config import PapiWebConfig
from common.logger import get_logger, configure_logger
from data.event import get_events

logger: Logger = get_logger()
configure_logger(logging.INFO)


class Engine:
    def __init__(self):
        if not os.path.isdir(TMP_DIR):
            os.makedirs(TMP_DIR)
        logger.info('Reading configuration file...')
        self.__config = PapiWebConfig()

    @property
    def _config(self):
        return self.__config

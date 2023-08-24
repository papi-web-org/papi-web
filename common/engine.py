import logging
import os

from common.papi_web_config import PapiWebConfig, TMP_DIR
from logging import Logger
from logger import get_logger

logger: Logger = get_logger()


class Engine:
    def __init__(self):
        logger.info('Reading configuration file...')
        self.__config = PapiWebConfig()
        if not os.path.isdir(TMP_DIR):
            os.makedirs(TMP_DIR)

    @property
    def _config(self):
        return self.__config

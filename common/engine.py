from pathlib import Path
import logging
from logging import Logger

from common.config_reader import TMP_DIR
from common.papi_web_config import PapiWebConfig
from common.logger import get_logger, configure_logger

logger: Logger = get_logger()
configure_logger(logging.INFO)


class Engine:
    def __init__(self):
        if not TMP_DIR.is_dir():
            TMP_DIR.mkdir(parents=True)
        logger.info(f'Reading configuration file...')
        self.__config = PapiWebConfig()

    @property
    def _config(self):
        return self.__config

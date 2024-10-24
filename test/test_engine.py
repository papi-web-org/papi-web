from logging import Logger

from common.logger import get_logger
from common.engine import Engine
from data.loader import EventLoader

logger: Logger = get_logger()


class TestEngine(Engine):
    def __init__(self):
        super().__init__()
        logger.info(EventLoader(lazy_load=False).events_sorted_by_name)

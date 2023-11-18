from logging import Logger

from common.logger import get_logger
from common.engine import Engine
from ffe.event_selector import EventSelector

logger: Logger = get_logger()


class FFEEngine(Engine):
    def __init__(self):
        try:
            super().__init__()
            while EventSelector(self._config).run():
                pass
        except KeyboardInterrupt:
            pass

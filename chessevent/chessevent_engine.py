from logging import Logger

from chessevent.event_selector import EventSelector
from common.logger import get_logger
from common.engine import Engine

logger: Logger = get_logger()


class ChessEventEngine(Engine):
    """The ChessEvent Engine."""
    def __init__(self):
        try:
            super().__init__()
            while EventSelector().run():
                pass
        except KeyboardInterrupt:
            pass

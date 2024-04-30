from logging import Logger

from common.logger import get_logger
from common.engine import Engine
from data.event import get_events_sorted_by_name

logger: Logger = get_logger()


class TestEngine(Engine):
    def __init__(self):
        super().__init__()
        get_events_sorted_by_name(True, with_tournaments_only=True)

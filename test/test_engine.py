from logging import Logger
from typing import List

from common.logger import get_logger
from common.engine import Engine
from data.event import get_events_by_name, Event

logger: Logger = get_logger()


class TestEngine(Engine):
    def __init__(self):
        super().__init__()
        events: List[Event] = get_events_by_name(True, silent=False, with_tournaments_only=True)

from common.engine import Engine
from data.event import get_events
from ffe.event_selector import EventSelector
from logging import Logger
from logger import get_logger

logger: Logger = get_logger()


class FFEEngine(Engine):
    def __init__(self):
        super().__init__()
        while EventSelector(get_events()).run():
            pass

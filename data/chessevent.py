from functools import cached_property
from logging import Logger

from common.logger import get_logger
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from data.event import Event
    from data.event import Tournament
from database.store import StoredChessEvent

logger: Logger = get_logger()


class ChessEvent:
    """A data wrapper around a StoredChessEvent."""
    def __init__(self, event: 'Event', stored_chessevent: StoredChessEvent, ):
        self.stored_chessevent: StoredChessEvent = stored_chessevent
        self.event: 'Event' = event

    @property
    def id(self) -> int:
        return self.stored_chessevent.id

    @property
    def uniq_id(self) -> str:
        return self.stored_chessevent.uniq_id

    @property
    def user_id(self) -> str:
        return self.stored_chessevent.user_id

    @property
    def password(self) -> str:
        return self.stored_chessevent.password

    @property
    def shadowed_password(self) -> str:
        if self.password:
            return '*' * 8
        else:
            return ''

    @property
    def event_id(self) -> str:
        return self.stored_chessevent.event_id

    @cached_property
    def dependent_tournaments(self) -> list['Tournament']:
        return [
            tournament
            for tournament in self.event.tournaments_by_id.values()
            if tournament.chessevent and tournament.chessevent.id == self.id
        ]

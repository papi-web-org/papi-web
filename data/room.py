from dataclasses import dataclass, field
from logging import Logger
from typing import NamedTuple, Self

from common.config_reader import ConfigReader, TMP_DIR
from common.logger import get_logger
from data.tournament import Tournament


logger: Logger = get_logger()


class BoardInterval(NamedTuple):
    """An interval for boards in a room configuration.
    An interval is of the form *tournament:start-end*, *tournament* may be None,
    while *start* and *end* cannot both be None."""
    tournament: str | None
    start: int | None
    end: int | None

    @property
    def boards(self, max_tournament_board: int) -> range:
        """A range object representing the boards of the boards interval.
        This range object may be empty if *start* and *end* are not in
        increasing order, or if *start* < *max_tournament_board*."""
        return range(self.start or 1, 1 + (self.end or max_tournament_board))

    @classmethod
    def from_interval_string(cls, value: str) -> Self:
        """Parse a board interval from a config string:
        Format:
        [tournament:][start][-][end]
        If tournament is not defined, use None instead.
        If there is no -, then it's a single number, thus start = end
        If the interval is of the form start-, then end = None
        If the interval if of the form -end, then start = None
        """
        if ':' in value:
            # FIXME(Amaras): this assumes that there is no : in the
            # tournament id, we need to fix this before review
            tournament, _, interval = value.partition(':')
        else:
            tournament, interval = None, value
        left, sep, right = interval.partition('-')
        if sep:
            # NOTE(Amaras): value's format is one of:
            # tournament:- -> Invalid
            # tournament:start-
            # tournament:-end
            # tournament:start-end
            # Above, tournament may be empty (in which case : is not necessary)
            try:
                left: int = int(left)
            except ValueError:
                logger.info("Invalid value %s, must be an integer", left)
                left = None
            try:
                right: int = int(right)
            except ValueError:
                logger.info("Invalid value %s, must be an integer", right)
                right = None
            if left is None and right is None:
                raise ValueError(
                    "Interval must be of the form [tournament:]start-end, "
                    "and at least one of *start* and *end* must be defined"
                )
            return cls(tournament or None, left, right)
        else:
            # NOTE(Amaras): transparently let the ValueError propagate
            return cls(tournament or None, int(left))


@dataclass
class Room:
    _id: str
    name: str | None = ''
    boards: list[BoardInterval] = field(default_factory=list)


class RoomBuilder:
    def __init__(self, config_reader: ConfigReader, event_id: str,
            tournaments: dict[str, Tournament]):
        self._config_reader: ConfigReader = config_reader
        self.event_id: str = event_id
        self._tournaments: dict[str, Tournament] = tournaments
        self.rooms: dict[str, Room] = {}
        room_ids: list[str] = self._read_room_ids()
        if not room_ids:
            rooms_ids = ['default']
            self.rooms = {
                'default': Room('default', 'default',
                    [
                        BoardInterval(tournament_id, 1, None)
                        for tournament_id in self._tournaments.keys()
                    ]
                )
            }
        


    def _read_room_ids(self) -> list[str]:
        return self._config_reader.get_subsection_keys_with_prefix('room')

 

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
    tournament: str
    start: int | None
    end: int | None

    def boards(self, max_tournament_board: int) -> frozenset[tuple[str, int]]:
        """A frozenset object representing the boards of the boards interval.
        This frozenset object may be empty if *start* and *end* are not in
        increasing order, or if *start* < *max_tournament_board*."""
        return frozenset(
            map(lambda elt: (self.tournament, elt),
                range(
                    self.start or 1,
                    1 + (self.end or max_tournament_board)
                )
            )
        )

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
            tournament, _, interval = value.partition(':')
        else:
            tournament, interval = '', value
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
            return cls(tournament or '', left, right)
        else:
            # NOTE(Amaras): transparently let the ValueError propagate
            return cls(tournament or '', board := int(left), board)


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
        for room_id in room_ids:
            if room := self._build_room(room_id):
                self.rooms[room._id] = room
        if not self.rooms:
            self._config_reader.add_info(
                "aucune salle de jeu valide définie, création d'une salle "
                "par défaut")
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

    def _build_room(self, room_id: str) -> Room | None:
        room_section_key = f'room.{room_id}'
        if '/' in room_id:
            self._config_reader.add_error(
                "le caractère « / » n'est pas autorisé dans les "
                "identifiants des salles de jeu, salle ignorée",
                room_section_key
            )
            return None
        room_section = self._config_reader[room_section_key]
        key = 'name'
        try:
            room_name = room_section[key]
        except KeyError:
            self._config_reader.add_info(
                f"Aucun nom donné à la salle, utilisation de l'identifiant :"
                f" [{room_id}]",
                room_section_key, key)
            room_name = room_id
        key = 'boards'
        try:
            boards_to_parse = map(str.strip, room_section[key].split(','))
            boards = list(
                map(
                    BoardInterval.from_interval_string,
                    boards_to_parse
                )
            )
        except KeyError:
            self._config_reader.add_warning(
                f"Aucun ensemble d'échiquiers pour la salle [{room_name}], "
                f"ignorée",
                room_section_key, key)
            return None
        for key, _ in self._config_reader.items(room_section_key):
            if key not in ConfigReader.room_keys:
                self._config_reader.add_warning(
                    'option inconnue', room_section_key, key)

        return Room(room_id, room_name, boards)

from datetime import datetime
import re
import time
from contextlib import suppress
from logging import Logger
from dataclasses import dataclass, field
from collections import namedtuple
import warnings

from common.config_reader import ConfigReader
from common.logger import get_logger

logger: Logger = get_logger()

ROUND_DEFAULT_TEXT_BEFORE: str = 'Début de la ronde {} dans %s'
ROUND_DEFAULT_TEXT_AFTER: str = 'Ronde {} commencée depuis %s'


def timestamp_to_datetime(ts: int) -> datetime:
    return datetime.fromtimestamp(ts)


def datetime_to_str(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%d %H:%M')


def timestamp_to_str(ts: int) -> str:
    return datetime_to_str(timestamp_to_datetime(ts))


@dataclass
class TimerHour:
    _id: int | str
    timestamp: int
    round: int | None = None
    text_before: str | None = None
    text_after: str | None = None
    datetime: datetime = field(init=False)
    timestamp_1: int | None = field(default=None, init=False)
    timestamp_2: int | None = field(default=None, init=False)
    timestamp_3: int | None = field(default=None, init=False)
    timestamp_next: int | None = field(default=None, init=False)
    last: bool = field(default=False, init=False)

    def __post_init__(self):
        if self.text_before is None and self.round is not None:
            self.text_before = ROUND_DEFAULT_TEXT_BEFORE.format(self.round)
        if self.text_after is None and self.round is not None:
            self.text_after = ROUND_DEFAULT_TEXT_AFTER.format(self.round)
        self.datetime = timestamp_to_datetime(self.timestamp)

    @property
    def id(self) -> int | str:
        return self._id

    @property
    def datetime_str(self) -> str:
        return self.datetime.strftime('%Y-%m-%d %H:%M')

    @property
    def date_str(self) -> str:
        return self.datetime.strftime('%Y-%m-%d')

    @property
    def time_str(self) -> str:
        return self.datetime.strftime('%H:%M')

    def set_text_before(self, text: str):
        warnings.warn("Use direct assignment to text_before instead")
        self.text_before = text

    def set_text_after(self, text: str):
        warnings.warn("Use direct assignment to text_after instead")
        self.text_after = text

    def set_round(self, round_: int):
        self.text_before = ROUND_DEFAULT_TEXT_BEFORE.format(round_)
        self.text_after = ROUND_DEFAULT_TEXT_AFTER.format(round_)

    @property
    def datetime_str_1(self) -> str:
        return timestamp_to_str(self.timestamp_1)

    @property
    def datetime_str_2(self) -> str:
        return timestamp_to_str(self.timestamp_2)

    @property
    def datetime_str_3(self) -> str:
        return timestamp_to_str(self.timestamp_3)

    @property
    def datetime_str_next(self) -> str:
        return timestamp_to_str(self.timestamp_next)

    def set_timestamps(self, timestamp_1: int, timestamp_2: int, timestamp_3: int, timestamp_next: int):
        self.timestamp_1 = timestamp_1
        self.timestamp_2 = timestamp_2
        self.timestamp_3 = timestamp_3
        self.timestamp_next = timestamp_next

    def set_last(self, last: bool):
        warnings.warn("Use direct assignment to last instead")
        self.last = last

    def __repr__(self):
        return f'{self.__class__.__name__}({self.timestamp} {self.datetime_str} [{self.text_before}/{self.text_after}])'


RGB = namedtuple('RGB', ['red', 'green', 'blue'])
DEFAULT_COLORS: dict[int, RGB] = {
        1: RGB(0, 255, 0),
        2: RGB(255, 127, 0),
        3: RGB(255, 0, 0),
}
DEFAULT_DELAYS: dict[int, int] = {1: 15, 2: 5, 3: 10, }


class Timer:
    def __init__(self):
        self.colors: dict[int, RGB] = DEFAULT_COLORS
        self.delays: dict[int, int] = DEFAULT_DELAYS
        self.hours: list[TimerHour] = []

    def set_hours_timestamps(self):
        for hour in self.hours:
            hour.set_timestamps(
                hour.timestamp - self.delays[1] * 60 - self.delays[2] * 60,
                hour.timestamp - self.delays[2] * 60,
                hour.timestamp,
                hour.timestamp + self.delays[3] * 60)
        self.hours[-1].last = True

    def __repr__(self):
        return f'{type(self).__name__}({self.colors} {self.delays} {self.hours})'


class TimerBuilder:

    def __init__(self, config_reader: ConfigReader):
        self._config_reader: ConfigReader = config_reader
        self.timer: Timer | None = None
        section_key = 'timer.hour'
        hour_ids: list[str] = self._config_reader.get_subsection_keys_with_prefix(section_key)
        if not hour_ids:
            self._config_reader.add_debug(
                'aucun horaire déclaré, le chronomètre ne sera pas disponible',
                'timer.hour.*'
            )
            return
        timer: Timer = Timer()
        for hour_id in hour_ids:
            self._add_hour(timer, hour_id)
        if not timer.hours:
            self._config_reader.add_warning(
                'aucun horaire défini, le chronomètre ne sera pas disponible',
                section_key
            )
            return
        self.timer = timer
        self._set_colors()
        self._set_delays()
        timer.set_hours_timestamps()

    def _add_hour(self, timer: Timer, hour_id: str):
        section_key = f'timer.hour.{hour_id}'
        timer_section = self._config_reader[section_key]
        section_keys: list[str] = ['date', 'text_before', 'text_after', ]
        key = 'date'
        if key not in timer_section:
            self._config_reader.add_warning('option absente, horaire ignoré', section_key, key)
            return
        previous_hour: TimerHour | None = None
        if timer.hours:
            previous_hour = timer.hours[-1]
        datetime_str = re.sub(r'\s+', ' ', str(timer_section.get(key)).strip().upper())
        timestamp: int | None = None
        matches = re.match(
            '^#?(?P<year>[0-9]{4})-(?P<month>[0-9]{1,2})-(?P<day>[0-9]{1,2}) '
            '(?P<hour>[0-9]{1,2}):(?P<minute>[0-9]{1,2})$',
            datetime_str)
        if matches:
            try:
                timestamp = int(time.mktime(datetime.strptime(datetime_str, '%Y-%m-%d %H:%M').timetuple()))
            except ValueError:
                pass
        else:
            matches = re.match('^(?P<hour>[0-9]{1,2}):(?P<minute>[0-9]{1,2})$', datetime_str)
            if matches:
                if previous_hour is None:
                    self._config_reader.add_warning(
                        'le jour du premier horaire doit être spécifié, horaire ignoré', section_key, key)
                    return
                self._config_reader.add_debug(
                    f'jour non spécifié, [{datetime_str} {previous_hour}] pris en compte', section_key, key)
                try:
                    timestamp = int(time.mktime(datetime.strptime(
                        previous_hour.date_str + ' ' + datetime_str, '%Y-%m-%d %H:%M').timetuple()))
                except ValueError:
                    pass
        if timestamp is None:
            self._config_reader.add_warning(
                f'date [{datetime_str}] non valide ([YYYY-MM-DD hh:mm] ou [hh:mm] attendu), horaire ignoré',
                section_key, key)
            return
        hour: TimerHour = TimerHour(hour_id, timestamp)
        if timer.hours:
            previous_hour = timer.hours[-1]
            if timestamp <= previous_hour.timestamp:
                self._config_reader.add_warning(
                    f"l'horaire [{hour.datetime_str}] arrive avant l'horaire précédent [{previous_hour.datetime_str}], "
                    f"horaire ignoré", section_key, key)
                return

        if hour_id.isdigit():
            hour.set_round(int(hour_id))
        key = 'text_before'
        with suppress(KeyError):
            hour.text_before = (timer_section[key])
        key = 'text_after'
        with suppress(KeyError):
            hour.text_after = (timer_section[key])
        if hour.text_before is None or hour.text_after is None:
            self._config_reader.add_warning(
                'les options [text_before] et [text_after] sont attendues, horaire ignoré', section_key)
            return
        for key, _ in self._config_reader.items(section_key):
            if key not in section_keys:
                self._config_reader.add_warning('option inconnue', section_key, key)
        timer.hours.append(hour)

    def _set_colors(self):
        section_key = 'timer.colors'
        try:
            color_section = self._config_reader[section_key]
        except KeyError:
            return
        section_keys = [str(id) for id in range(1, 4)]
        simplified_hex_pattern = re.compile('^#?(?P<R>[0-9A-F])(?P<G>[0-9A-F])(?P<B>[0-9A-F])$')
        hex_pattern = re.compile('^#?(?P<R>[0-9A-F]{2})(?P<G>[0-9A-F]{2})(?P<B>[0-9A-F]{2})$')
        rgb_pattern = re.compile(r'^(?:RBG)*\((?P<R>[0-9]+),(?P<G>[0-9]+)(?P<B>[0-9]+)\)*$')
        for key in color_section:
            if key not in section_keys:
                self._config_reader.add_warning(
                    'option de couleur invalide (acceptées : '
                    f'[{", ".join(section_keys)}]), '
                    'couleur ignorée',
                    section_key,
                    key
                )
                continue
            color_id = int(key)
            color_rbg: tuple[int, int, int] | None = None
            color_value: str = color_section.get(key).replace(' ', '').upper()
            if matches := simplified_hex_pattern.match(color_value):
                color_rbg = (
                    int(matches.group('R') * 2, 16),
                    int(matches.group('G') * 2, 16),
                    int(matches.group('B') * 2, 16),
                )
            elif matches := hex_pattern.match(color_value):
                color_rbg = (
                    int(matches.group('R'), 16),
                    int(matches.group('G'), 16),
                    int(matches.group('B'), 16),
                )
            elif matches := rgb_pattern.match(color_value):
                color_rbg = (
                    int(matches.group('R')),
                    int(matches.group('G')),
                    int(matches.group('B')),
                )
                if color_rbg[0] > 255 or color_rbg[1] > 255 or color_rbg[2] > 255:
                    color_rbg = None
            if color_rbg is None:
                self._config_reader.add_warning(
                    f'couleur [{color_value}] non valide (#HHH, #HHHHHH ou '
                    'RGB(RRR, GGG, BBB) attendu), la couleur par défaut sera '
                    'utilisée',
                    section_key,
                    key
                )
            else:
                self._config_reader.add_info(
                    f'couleur personnalisée [{color_rbg}] définie',
                    section_key,
                    key
                )
                self.timer.colors[color_id] = color_rbg

    def _set_delays(self):
        section_key = 'timer.delays'
        try:
            delay_section = self._config_reader[section_key]
        except KeyError:
            return
        section_keys = ('1', '2', '3')
        for key in delay_section:
            if key not in section_keys:
                self._config_reader.add_warning(
                    'option de délai non valide (acceptées: '
                    f'[{", ".join(section_keys)}])',
                    section_key,
                    key
                )
                continue
            delay_id = int(key)
            delay: int | None = self._config_reader.getint_safe(section_key, key, minimum=1)
            if delay is None:
                self._config_reader.add_warning(
                    'un entier positif est attendu, ignoré',
                    section_key,
                    key
                )
            else:
                self.timer.delays[delay_id] = delay

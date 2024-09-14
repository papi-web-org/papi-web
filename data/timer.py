import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from logging import Logger
from typing import TYPE_CHECKING

from common import RGB, hexa_to_rgb, format_timestamp_date_time, format_timestamp_date, \
    format_timestamp_time
from common.papi_web_config import PapiWebConfig
from database.store import StoredTimerHour, StoredTimer

if TYPE_CHECKING:
    from data.event import Event

from common.logger import get_logger

logger: Logger = get_logger()


@dataclass
class TimerHour:
    timer: 'Timer'
    stored_timer_hour: StoredTimerHour
    timestamp: int | None = field(init=False, default=None)
    _round: int | None = field(init=False, default=None)
    _text_before: str | None = field(default=None)
    _text_after: str | None = field(default=None)
    last_valid: bool = field(init=False, default=None)
    error: str | None = field(default=None)

    @property
    def datetime(self) -> datetime | None:
        return datetime.fromtimestamp(self.timestamp) if self.timestamp else None

    @property
    def datetime_str(self) -> str | None:
        return format_timestamp_date_time(self.timestamp) if self.timestamp else None

    @property
    def date_str(self) -> str | None:
        return format_timestamp_date(self.timestamp) if self.timestamp else None

    @property
    def time_str(self) -> str | None:
        return format_timestamp_time(self.timestamp) if self.timestamp else None

    @property
    def id(self) -> int | None:
        return self.stored_timer_hour.id if self.stored_timer_hour else None

    @property
    def uniq_id(self) -> str | None:
        return self.stored_timer_hour.uniq_id if self.stored_timer_hour else None

    @property
    def order(self) -> int | None:
        return self.stored_timer_hour.order if self.stored_timer_hour else None

    @property
    def round(self) -> int:
        if self._round is None:
            try:
                self._round = max(int(self.uniq_id), 0)
            except ValueError:
                self._round = 0
        return self._round

    def _format_stored_text(self, text, round_default_text) -> str:
        if self.round:
            return text.format(self.round) if text else round_default_text.format(self.round)
        else:
            return text if text else ''

    @property
    def text_before(self) -> str:
        papi_web_config: PapiWebConfig = PapiWebConfig()
        if self._text_before is None:
            self._text_before = self._format_stored_text(
                self.stored_timer_hour.text_before, papi_web_config.default_timer_round_text_before)
        return self._text_before

    @property
    def text_after(self) -> str:
        papi_web_config: PapiWebConfig = PapiWebConfig()
        if self._text_after is None:
            self._text_after = self._format_stored_text(
                self.stored_timer_hour.text_after, papi_web_config.default_timer_round_text_after)
        return self._text_after

    @property
    def timestamp_1(self) -> int:
        return self.timestamp - self.timer.delays[1] * 60 - self.timer.delays[2] * 60

    @property
    def timestamp_2(self) -> int:
        return self.timestamp - self.timer.delays[2] * 60

    @property
    def timestamp_3(self) -> int:
        return self.timestamp

    @property
    def timestamp_next(self) -> int:
        return self.timestamp + self.timer.delays[3] * 60

    @property
    def datetime_str_1(self) -> str:
        return format_timestamp_date_time(self.timestamp_1)

    @property
    def datetime_str_2(self) -> str:
        return format_timestamp_date_time(self.timestamp_2)

    @property
    def datetime_str_3(self) -> str:
        return format_timestamp_date_time(self.timestamp_3)

    @property
    def datetime_str_next(self) -> str:
        return format_timestamp_date_time(self.timestamp_next)

    def __repr__(self):
        return (f'{self.__class__.__name__}(id={self.id} order={self.order} uniq_id={self.uniq_id} '
                f'datetime={self.datetime_str} texts=[{self.text_before}]/[{self.text_after}])')


class Timer:
    def __init__(self, event: 'Event', stored_timer: StoredTimer):
        self.event: 'Event' = event
        self.stored_timer: StoredTimer = stored_timer
        self.timer_hours_by_id: dict[int, TimerHour] = {}
        self._timer_hour_uniq_ids: list[str] | None = None
        self._timer_hours_sorted_by_order: list[TimerHour] | None = None
        self._colors: dict[int, str] | None = None
        self._delays: dict[int, int] | None = None
        self.valid: bool = True
        self.error: str | None = None
        self._build_timer_hours()

    @property
    def id(self) -> int:
        return self.stored_timer.id if self.stored_timer else None

    @property
    def timer_hour_uniq_ids(self) -> list[str]:
        if self._timer_hour_uniq_ids is None:
            self._timer_hour_uniq_ids = [timer_hour.uniq_id for timer_hour in self.timer_hours_by_id.values()]
        return self._timer_hour_uniq_ids

    @property
    def timer_hours_sorted_by_order(self) -> list[TimerHour]:
        if self._timer_hours_sorted_by_order is None:
            self._timer_hours_sorted_by_order = sorted(
                self.timer_hours_by_id.values(), key=lambda timer_hour: timer_hour.order)
        return self._timer_hours_sorted_by_order

    @property
    def uniq_id(self) -> str:
        return self.stored_timer.uniq_id if self.stored_timer else None

    def _build_timer_hours(self):
        previous_valid_timer_hour: TimerHour | None = None
        for stored_timer_hour in self.stored_timer.stored_timer_hours:
            timer_hour: TimerHour = TimerHour(self, stored_timer_hour)
            self.timer_hours_by_id[timer_hour.id] = timer_hour
            if not stored_timer_hour.time_str:
                timer_hour.error = f'L\'heure n\'est pas définie.'
                self.event.add_warning(timer_hour.error, timer_hour=timer_hour)
            else:
                matches = re.match('^(?P<hour>[0-9]{1,2}):(?P<minute>[0-9]{1,2})$', stored_timer_hour.time_str)
                if not matches:
                    timer_hour.error = f'L\'heure [{stored_timer_hour.time_str}]n\'est pas valide.'
                    self.event.add_warning(timer_hour.error, timer_hour=timer_hour)
                elif previous_valid_timer_hour is None and not stored_timer_hour.date_str:
                    timer_hour.error = f'La date du premier horaire n\'est pas définie (obligatoire).'
                    self.event.add_warning(timer_hour.error, timer_hour=timer_hour)
                else:
                    datetime_str: str
                    if stored_timer_hour.date_str and not re.match(
                            '^#?(?P<year>[0-9]{4})-(?P<month>[0-9]{1,2})-(?P<day>[0-9]{1,2})$',
                            stored_timer_hour.date_str):
                        timer_hour.error = f'La date [{stored_timer_hour.date_str}] n\'est pas valide.'
                        self.event.add_warning(timer_hour.error, timer_hour=timer_hour)
                    else:
                        if stored_timer_hour.date_str:
                            datetime_str = f'{stored_timer_hour.date_str} {stored_timer_hour.time_str}'
                        else:
                            datetime_str = f'{previous_valid_timer_hour.date_str} {stored_timer_hour.time_str}'
                        try:
                            timer_hour.timestamp = int(time.mktime(datetime.strptime(
                                datetime_str, '%Y-%m-%d %H:%M').timetuple()))
                            if (previous_valid_timer_hour
                                    and timer_hour.timestamp <= previous_valid_timer_hour.timestamp):
                                timer_hour.error = (
                                    f'L\'horaire [{timer_hour.datetime_str}] arrive avant l\'horaire précédent '
                                    f'[{previous_valid_timer_hour.datetime_str}], horaire non valide')
                                self.event.add_warning(timer_hour.error, timer_hour=timer_hour)
                        except ValueError:
                            timer_hour.error = f'La date et l\'heure [{datetime_str}] ne sont pas valides.'
                            self.event.add_warning(timer_hour.error, timer_hour=timer_hour)
            if not timer_hour.error:
                previous_valid_timer_hour = timer_hour
        if previous_valid_timer_hour:
            for timer_hour in reversed(self.timer_hours_sorted_by_order):
                if not timer_hour.error:
                    timer_hour.last_valid = True
                    break
        else:
            self.error = 'Aucun horaire valide défini.'
            self.event.add_warning(self.error, timer=self)

    @property
    def colors(self) -> dict[int, str]:
        if self._colors is None:
            self._colors = {
                1: self.stored_timer.colors[1] if self.stored_timer.colors[1] else self.event.timer_colors[1],
                2: self.stored_timer.colors[2] if self.stored_timer.colors[2] else self.event.timer_colors[2],
                3: self.stored_timer.colors[3] if self.stored_timer.colors[3] else self.event.timer_colors[3],
             }
        return self._colors

    @property
    def color_1_rgb(self) -> RGB:
        return hexa_to_rgb(self.colors[1])

    @property
    def color_2_rgb(self) -> RGB:
        return hexa_to_rgb(self.colors[2])

    @property
    def color_3_rgb(self) -> RGB:
        return hexa_to_rgb(self.colors[3])

    @property
    def delays(self) -> dict[int, int]:
        if self._delays is None:
            self._delays = {
                1: self.stored_timer.delays[1] if self.stored_timer.delays[1] else self.event.timer_delays[1],
                2: self.stored_timer.delays[2] if self.stored_timer.delays[2] else self.event.timer_delays[2],
                3: self.stored_timer.delays[3] if self.stored_timer.delays[3] else self.event.timer_delays[3],
             }
        return self._delays

    def get_previous_timer_hour(self, timer_hour: TimerHour) -> TimerHour | None:
        previous_timer_hour: TimerHour | None = None
        for th in self.timer_hours_by_id.values():
            if th.id == timer_hour.id:
                return previous_timer_hour
            previous_timer_hour = th
        return None

    def __repr__(self):
        return f'{type(self).__name__}({self.colors} {self.delays} {self.timer_hours_by_id})'

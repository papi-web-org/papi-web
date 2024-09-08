import json
import shutil
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from logging import Logger
from pathlib import Path
from sqlite3 import Connection, Cursor, connect, OperationalError
from typing import Self, Any

import yaml
from packaging.version import Version

from common import format_timestamp_date, format_timestamp_time
from common.exception import PapiWebException
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.board import Board
from data.result import Result as DataResult
from data.util import Result as UtilResult
from database.store import StoredTournament, StoredEvent, StoredChessEvent, StoredTimer, StoredTimerHour, \
    StoredFamily, StoredIllegalMove, StoredResult, StoredRotator, StoredScreenSet, StoredScreen, StoredSkippedRound

logger: Logger = get_logger()


@dataclass
class SQLiteDatabase:
    """A database using SQLite.

    This is a rework of the papi database, and stores slightly more information than
    the papi database.
    """
    file: Path
    write: bool = field(default=False)
    database: Connection | None = field(init=False, default=None)
    cursor: Cursor | None = field(init=False, default=None)

    def __enter__(self) -> Self:
        db_url: str = f'file:{self.file}?mode={"rw" if self.write else "ro"}'
        self.database = connect(db_url, detect_types=1, uri=True)
        self.cursor = self.database.cursor()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        if self.database is not None:
            self.cursor.close()
            del self.cursor
            self.cursor = None
            self.database.close()
            del self.database
            self.database = None

    def _execute(self, query: str, params: tuple = ()):
        self.cursor.execute(query, params)

    def _fetchall(self) -> Iterator[dict[str, Any]]:
        columns = [column[0] for column in self.cursor.description]
        for row in self.cursor.fetchall():
            yield dict(zip(columns, row))

    def _fetchone(self) -> dict[str, Any]:
        columns = [column[0] for column in self.cursor.description]
        result = self.cursor.fetchone()
        return {} if result is None else dict(zip(columns, result))

    def commit(self):
        self.database.commit()

    def _last_inserted_id(self) -> int:
        return self.cursor.lastrowid

    @staticmethod
    def load_bool_from_database_field(data: int | None, if_none=None) -> bool:
        return data == 1 if data is not None else if_none

    @staticmethod
    def load_json_from_database_field(json_data: str | None, if_none=None) -> Any:
        return json.loads(json_data) if json_data is not None else if_none

    @staticmethod
    def set_dict_int_keys(string_dict: dict[str, Any]) -> dict[int, Any]:
        # This method is needed because JSON turns all keys to strings
        return None if string_dict is None else {int(k): v for k, v in string_dict.items()}

    @staticmethod
    def dump_to_json_database_field(obj: Any, if_none=None) -> str | None:
        if obj is not None:
            return json.dumps(obj)
        if if_none is not None:
            return json.dumps(if_none)
        return None

    @classmethod
    def dump_to_json_database_timer_colors(cls, colors) -> str | None:
        return cls.dump_to_json_database_field(colors, {i: None for i in range(1, 4)})

    @classmethod
    def dump_to_json_database_timer_delays(cls, delays) -> str | None:
        return cls.dump_to_json_database_field(delays, {i: None for i in range(1, 4)})


class EventDatabase(SQLiteDatabase):
    def __init__(self, uniq_id: str, write: bool = False):
        self.uniq_id = uniq_id
        self._version: Version | None = None
        super().__init__(self.event_database_path(self.uniq_id), write)

    @staticmethod
    def event_database_path(uniq_id: str) -> Path:
        papi_web_config: PapiWebConfig = PapiWebConfig()
        return papi_web_config.event_path / f'{uniq_id}.{papi_web_config.event_ext}'

    def exists(self) -> bool:
        return self.file.exists()

    @staticmethod
    def _check_populate_dict(
            yml_file: Path,
            dict_path: str, supposed_dict: dict,
            mandatory_fields: list[str] = None,
            optional_fields: list['str'] = None,
            field_type: type = None,
            empty_allowed: bool = True,
    ):
        assert isinstance(supposed_dict, dict), f'{yml_file.name}: {dict_path}/ is no dictionary'
        fields: list[str] = []
        if mandatory_fields is not None:
            for k in mandatory_fields:
                assert k in supposed_dict, f'{yml_file.name}: {dict_path}/{k} is not set'
            fields += mandatory_fields
        if optional_fields is not None:
            fields += optional_fields
        if fields:
            for k in supposed_dict:
                assert k in fields, f'{yml_file.name}: invalid key {dict_path}/{k} (valid_keys: {", ".join(fields)})'
                if field_type is not None:
                    assert isinstance(supposed_dict[k], field_type), \
                        f'{yml_file.name}: {dict_path} should contain only items of type [{field_type}]'
        if not empty_allowed:
            assert supposed_dict, f'{yml_file.name}: dictionary {dict_path} is empty'

    @staticmethod
    def _check_populate_list(
            yml_file: Path,
            list_path: str, supposed_list: list,
            item_type: type = None,
            items_number: int = None,
            empty_allowed: bool = True,
    ):
        assert isinstance(supposed_list, list), f'{yml_file.name}: {list_path} is no list'
        if item_type is not None:
            assert all(isinstance(item, item_type) for item in supposed_list), \
                f'{yml_file.name}: {list_path} should contain only items of type [{item_type}]'
        if items_number is not None:
            assert len(supposed_list) == items_number, \
                f'{yml_file.name}: {list_path} should contain exactly {items_number} items'
        if not empty_allowed:
            assert supposed_list, f'{yml_file.name}: list {list_path} is empty'

    def create(self, populate: bool = False):
        if self.exists():
            raise PapiWebException(
                f'La base de données ne peut être créée car le fichier [{self.file.resolve()}] existe déjà.')
        papi_web_config: PapiWebConfig = PapiWebConfig()
        papi_web_config.event_path.mkdir(parents=True, exist_ok=True)
        database: Connection | None = None
        cursor: Cursor | None = None
        try:
            database = connect(database=self.file, detect_types=1, uri=True)
            cursor = database.cursor()
            today_str: str = format_timestamp_date()
            event_start = time.mktime(datetime.strptime(f'{today_str} 00:00', '%Y-%m-%d %H:%M').timetuple())
            event_stop = time.mktime(datetime.strptime(f'{today_str} 23:59', '%Y-%m-%d %H:%M').timetuple())
            with open(papi_web_config.database_sql_path / 'create_event.sql', encoding='utf-8') as f:
                papi_web_version: Version = papi_web_config.version
                cursor.executescript(f.read().format(
                    version=f'{papi_web_version.major}.{papi_web_version.minor}.{papi_web_version.micro}',
                    name=self.uniq_id, start=event_start, stop=event_stop, now=time.time()))
            database.commit()
            logger.info('La base de données [%s] a été créée', self.file)
            if populate:
                with (EventDatabase(self.uniq_id, write=True) as event_database):
                    yml_file = papi_web_config.database_yml_path / f'{self.uniq_id}.yml'
                    event_dict = yaml.safe_load(yml_file.read_text(encoding='utf-8'))
                    self._check_populate_dict(
                        yml_file, '', event_dict,
                        mandatory_fields=['name', ],
                        optional_fields=['start', 'stop', 'path', 'image_url', 'image_color', 'public',
                                         'update_password', 'record_illegal_moves',
                                         'allow_results_deletion_on_input_screens', 'chessevents', 'tournaments',
                                         'timers', 'screens', 'families', 'rotators', 'timer_colors', 'timer_delays', ],
                        empty_allowed=False)
                    timer_delays: dict[int, int] | None = None
                    if 'timer_delays' in event_dict:
                        self._check_populate_list(
                            yml_file, f'/timer_delays', event_dict['timer_delays'],
                            items_number=3, item_type=int)
                        timer_delays = {i + 1: event_dict[
                            'timer_delays'][i] for i in range(0, len(event_dict['timer_delays']))}
                    timer_colors: dict[int, str] | None = None
                    if 'timer_colors' in event_dict:
                        self._check_populate_list(
                            yml_file, f'/timer_colors', event_dict['timer_colors'],
                            items_number=3, item_type=str)
                        timer_colors = {i + 1: event_dict[
                            'timer_colors'][i] for i in range(0, len(event_dict['timer_colors']))}
                    if 'start' in event_dict:
                        event_start = time.mktime(datetime.strptime(
                            event_dict['start'], '%Y-%m-%d %H:%M').timetuple())
                    if 'stop' in event_dict:
                        event_stop = time.mktime(datetime.strptime(
                            event_dict['stop'], '%Y-%m-%d %H:%M').timetuple())
                    event_database.update_stored_event(StoredEvent(
                        uniq_id=self.uniq_id,
                        name=event_dict['name'],
                        start=event_start,
                        stop=event_stop,
                        path=event_dict.get('path', None),
                        image_url=event_dict.get('image_color', None),
                        image_color=event_dict.get('image_color', None),
                        update_password=event_dict.get('update_password', None),
                        record_illegal_moves=event_dict.get('record_illegal_moves', None),
                        allow_results_deletion_on_input_screens=event_dict.get(
                            'allow_results_deletion_on_input_screens', None),
                        timer_colors=timer_colors,
                        timer_delays=timer_delays,
                        public=event_dict.get('public', False),
                    ))
                    chessevent_ids_by_uniq_id: dict[str, int] = {}
                    if 'chessevents' in event_dict:
                        self._check_populate_dict(yml_file, '/chessevents', event_dict['chessevents'])
                        for chessevent_uniq_id, chessevent_dict in event_dict['chessevents'].items():
                            self._check_populate_dict(
                                yml_file, f'/chessevents/{chessevent_uniq_id}', chessevent_dict,
                                mandatory_fields=['user_id', 'password', 'event_id', ])
                            stored_chessevent: StoredChessEvent = event_database.add_stored_chessevent(StoredChessEvent(
                                id=None,
                                uniq_id=chessevent_uniq_id,
                                user_id=chessevent_dict.get('user_id', None),
                                password=chessevent_dict.get('password', None),
                                event_id=chessevent_dict.get('event_id', None),
                            ))
                            chessevent_ids_by_uniq_id[chessevent_uniq_id] = stored_chessevent.id
                    timer_ids_by_uniq_id: dict[str, int] = {}
                    if 'timers' in event_dict:
                        self._check_populate_dict(yml_file, '/timers', event_dict['timers'])
                        for timer_uniq_id, timer_dict in event_dict['timers'].items():
                            self._check_populate_dict(
                                yml_file, f'/timers/{timer_uniq_id}', timer_dict,
                                mandatory_fields=['hours', ], optional_fields=['delays', 'colors', ])
                            delays: dict[int, int] | None = None
                            if 'delays' in timer_dict:
                                self._check_populate_list(
                                    yml_file, f'/timers/{timer_uniq_id}/delays', timer_dict['delays'],
                                    items_number=3, item_type=int)
                                delays = {i + 1: timer_dict['delays'][i] for i in range(0, len(timer_dict['delays']))}
                            colors: dict[int, str] | None = None
                            if 'colors' in timer_dict:
                                self._check_populate_list(
                                    yml_file, f'/timers/{timer_uniq_id}/colors', timer_dict['colors'],
                                    items_number=3, item_type=str)
                                colors = {i + 1: timer_dict['colors'][i] for i in range(0, len(timer_dict['colors']))}
                            stored_timer: StoredTimer = event_database.add_stored_timer(StoredTimer(
                                id=None,
                                uniq_id=timer_uniq_id,
                                colors=colors,
                                delays=delays,
                            ))
                            timer_ids_by_uniq_id[timer_uniq_id] = stored_timer.id
                            self._check_populate_dict(yml_file, f'/timers/{timer_uniq_id}/hours', timer_dict['hours'])
                            for timer_hour_uniq_id, timer_hour_dict in timer_dict['hours'].items():
                                self._check_populate_dict(
                                    yml_file, f'/timers/{timer_uniq_id}/hours/{timer_hour_uniq_id}',
                                    timer_hour_dict, mandatory_fields=['time_str', ],
                                    optional_fields=['date_str', 'text_before', 'text_after', ])
                                stored_timer_hour: StoredTimerHour = event_database.add_stored_timer_hour(
                                    stored_timer.id)
                                stored_timer_hour.uniq_id = timer_hour_uniq_id
                                stored_timer_hour.date_str = timer_hour_dict.get('date_str', None)
                                stored_timer_hour.time_str = timer_hour_dict['time_str']
                                with suppress(KeyError):
                                    stored_timer_hour.text_before = timer_hour_dict.get('text_before', None)
                                with suppress(KeyError):
                                    stored_timer_hour.text_after = timer_hour_dict.get('text_after', None)
                                event_database.update_stored_timer_hour(stored_timer_hour)
                    tournament_ids_by_uniq_id: dict[str, int] = {}
                    if 'tournaments' in event_dict:
                        self._check_populate_dict(yml_file, '/tournaments', event_dict['tournaments'])
                        for tournament_uniq_id, tournament_dict in event_dict['tournaments'].items():
                            self._check_populate_dict(
                                yml_file, f'/tournaments/{tournament_uniq_id}', tournament_dict,
                                mandatory_fields=['name', ],
                                optional_fields=[
                                    'filename', 'ffe_id', 'ffe_password', 'time_control_initial_time',
                                    'time_control_increment', 'time_control_handicap_penalty_value',
                                    'time_control_handicap_penalty_step', 'time_control_handicap_min_time',
                                    'chessevent_uniq_id', 'chessevent_tournament_name', 'time_control_initial_time',
                                    'time_control_increment', 'time_control_handicap_penalty_value',
                                    'time_control_handicap_penalty_step', 'time_control_handicap_min_time', ])
                            chessevent_uniq_id: str = tournament_dict.get('chessevent_uniq_id', None)
                            chessevent_id: int = chessevent_ids_by_uniq_id[
                                chessevent_uniq_id] if chessevent_uniq_id else None
                            stored_tournament: StoredTournament = event_database.add_stored_tournament(StoredTournament(
                                id=None,
                                uniq_id=tournament_uniq_id,
                                path=None,
                                filename=tournament_dict.get('filename', None),
                                name=tournament_dict.get('name', None),
                                ffe_id=tournament_dict.get('ffe_id', None),
                                ffe_password=tournament_dict.get('ffe_password', None),
                                time_control_initial_time=tournament_dict.get('time_control_initial_time', None),
                                time_control_increment=tournament_dict.get('time_control_increment', None),
                                time_control_handicap_penalty_value=tournament_dict.get(
                                    'time_control_handicap_penalty_value', None),
                                time_control_handicap_penalty_step=tournament_dict.get(
                                    'time_control_handicap_penalty_step', None),
                                time_control_handicap_min_time=tournament_dict.get(
                                    'time_control_handicap_min_time', None),
                                chessevent_id=chessevent_id,
                                chessevent_tournament_name=tournament_dict.get('chessevent_tournament_name', None),
                                record_illegal_moves=None,
                            ))
                            tournament_ids_by_uniq_id[tournament_uniq_id] = stored_tournament.id
                    screen_ids_by_uniq_id: dict[str, int] = {}
                    if 'screens' in event_dict:
                        self._check_populate_dict(yml_file, '/screens', event_dict['screens'])
                        for screen_uniq_id, screen_dict in event_dict['screens'].items():
                            self._check_populate_dict(
                                yml_file, f'/screens/{screen_uniq_id}', screen_dict,
                                mandatory_fields=['type', ],
                                optional_fields=['public', 'timer_uniq_id', 'players_show_unpaired',
                                                 'results_limit', 'results_tournament_uniq_ids', 'image_url',
                                                 'image_color', 'name', 'columns', 'menu_text', 'menu', 'sets'])
                            assert screen_dict, f'{yml_file.name}: dictionary screens.{screen_uniq_id} is empty'
                            timer_uniq_id: str | None = screen_dict.get('timer_uniq_id', None)
                            timer_id: int = timer_ids_by_uniq_id[timer_uniq_id] if timer_uniq_id else None
                            type: str = screen_dict.get('type', None)
                            players_show_unpaired: bool | None = None
                            results_limit: int | None = None
                            results_tournament_ids: list[int] | None = None
                            image_url: str | None = None
                            image_color: str | None = None
                            match type:
                                case 'boards' | 'input':
                                    pass
                                case 'players':
                                    players_show_unpaired = screen_dict.get('players_show_unpaired', False)
                                case 'results':
                                    results_limit: int = screen_dict.get('results_limit', None)
                                    if 'results_tournament_uniq_ids' in screen_dict:
                                        self._check_populate_list(
                                            yml_file, f'/screens/{screen_uniq_id}/results_tournament_uniq_ids',
                                            screen_dict['results_tournament_uniq_ids'])
                                        results_tournament_ids = [
                                            tournament_ids_by_uniq_id[tournament_uniq_id]
                                            for tournament_uniq_id in screen_dict['results_tournament_uniq_ids']
                                        ]
                                    else:
                                        results_tournament_ids = []
                                case 'image':
                                    image_url: str = screen_dict.get('image_url', None)
                                    image_color: str = screen_dict.get('image_color', None)
                                case _:
                                    raise ValueError
                            stored_screen: StoredScreen = event_database.add_stored_screen(StoredScreen(
                                id=None,
                                uniq_id=screen_uniq_id,
                                name=screen_dict.get('name', None),
                                type=type,
                                public=screen_dict.get('public', True),
                                columns=screen_dict.get('columns', None),
                                menu_text=screen_dict.get('menu_text', None),
                                menu=screen_dict.get('menu', None),
                                timer_id=timer_id,
                                players_show_unpaired=players_show_unpaired,
                                results_limit=results_limit,
                                results_tournament_ids=results_tournament_ids,
                                image_url=image_url,
                                image_color=image_color,
                            ))
                            screen_ids_by_uniq_id[screen_uniq_id] = stored_screen.id
                            if 'sets' in screen_dict:
                                self._check_populate_list(yml_file, f'/screens/{screen_uniq_id}', screen_dict['sets'])
                                for screen_set_dict in screen_dict['sets']:
                                    self._check_populate_dict(
                                        yml_file, f'/screens/{screen_uniq_id}/sets', screen_set_dict,
                                        optional_fields=[
                                            'tournament_uniq_id', 'name', 'fixed_boards_str', 'first', 'last', ])
                                    tournament_uniq_id: str = screen_set_dict.get('tournament_uniq_id', None)
                                    tournament_id: int = tournament_ids_by_uniq_id[
                                        tournament_uniq_id] if tournament_uniq_id else None
                                    stored_screen_set: StoredScreenSet = event_database.add_stored_screen_set(
                                        stored_screen.id, tournament_id)
                                    stored_screen_set.tournament_id = tournament_id
                                    stored_screen_set.name = screen_set_dict.get('name', None)
                                    stored_screen_set.fixed_boards_str = screen_set_dict.get('fixed_boards_str', None)
                                    stored_screen_set.first = screen_set_dict.get('first', None)
                                    stored_screen_set.last = screen_set_dict.get('last', None)
                                    stored_screen_set.part = screen_set_dict.get('part', None)
                                    stored_screen_set.parts = screen_set_dict.get('parts', None)
                                    stored_screen_set.number = screen_set_dict.get('number', None)
                                    event_database.update_stored_screen_set(stored_screen_set)
                    family_ids_by_uniq_id: dict[str, int] = {}
                    if 'families' in event_dict:
                        self._check_populate_dict(yml_file, '/families', event_dict['families'])
                        for family_uniq_id, family_dict in event_dict['families'].items():
                            self._check_populate_dict(
                                yml_file, f'/families/{family_uniq_id}', family_dict,
                                mandatory_fields=['type', ],
                                optional_fields=['public', 'tournament_uniq_id', 'timer_uniq_id',
                                                 'players_show_unpaired', 'name', 'columns', 'menu_text', 'menu',
                                                 'first', 'last', 'parts', 'number', ])
                            timer_uniq_id: str | None = family_dict.get('timer_uniq_id', None)
                            timer_id: int = timer_ids_by_uniq_id[timer_uniq_id] if timer_uniq_id else None
                            type: str = family_dict.get('type', None)
                            tournament_uniq_id: str = family_dict.get('tournament_uniq_id', None)
                            tournament_id: int = tournament_ids_by_uniq_id[
                                tournament_uniq_id] if tournament_uniq_id else None
                            players_show_unpaired: bool | None = None
                            match type:
                                case 'boards' | 'input':
                                    pass
                                case 'players':
                                    players_show_unpaired = family_dict.get('players_show_unpaired', False)
                                case _:
                                    raise ValueError(f'type={type}')
                            stored_family: StoredFamily = event_database.add_stored_family(StoredFamily(
                                id=None,
                                uniq_id=family_uniq_id,
                                name=family_dict.get('name', None),
                                tournament_id=tournament_id,
                                type=type,
                                public=screen_dict.get('public', True),
                                columns=family_dict.get('columns', None),
                                menu_text=family_dict.get('menu_text', None),
                                menu=family_dict.get('menu', None),
                                timer_id=timer_id,
                                players_show_unpaired=players_show_unpaired,
                                first=family_dict.get('first', None),
                                last=family_dict.get('last', None),
                                parts=family_dict.get('parts', None),
                                number=family_dict.get('number', None),
                            ))
                            family_ids_by_uniq_id[family_uniq_id] = stored_family.id
                    if 'rotators' in event_dict:
                        self._check_populate_dict(yml_file, '/rotators', event_dict['rotators'])
                        for rotator_uniq_id, rotator_dict in event_dict['rotators'].items():
                            self._check_populate_dict(
                                yml_file, f'/rotators/{rotator_uniq_id}', rotator_dict,
                                optional_fields=[
                                    'public', 'delay', 'show_menus', 'screen_uniq_ids', 'family_uniq_ids',
                                ])
                            screen_ids: list[int]
                            family_ids: list[int]
                            if 'screen_uniq_ids' in rotator_dict:
                                self._check_populate_list(
                                    yml_file, f'/rotator/{rotator_uniq_id}/screen_uniq_ids',
                                    rotator_dict['screen_uniq_ids'])
                                screen_ids = [
                                    screen_ids_by_uniq_id[screen_uniq_id]
                                    for screen_uniq_id in rotator_dict['screen_uniq_ids']
                                ]
                            else:
                                screen_ids = []
                            if 'family_uniq_ids' in rotator_dict:
                                self._check_populate_list(
                                    yml_file, f'/rotator/{rotator_uniq_id}/family_uniq_ids',
                                    rotator_dict['family_uniq_ids'])
                                family_ids = [
                                    family_ids_by_uniq_id[family_uniq_id]
                                    for family_uniq_id in rotator_dict['family_uniq_ids']
                                ]
                            else:
                                family_ids = []
                            event_database.add_stored_rotator(StoredRotator(
                                id=None,
                                uniq_id=rotator_uniq_id,
                                public=screen_dict.get('public', True),
                                delay=rotator_dict.get('delay', None),
                                show_menus=rotator_dict.get('show_menus', None),
                                screen_ids=screen_ids,
                                family_ids=family_ids,
                            ))
                    event_database.commit()
                logger.info('La base de données [%s] a été peuplée', self.file)
        except OperationalError as e:
            logger.warning('La création de la base de données %s a échoué : %s', self.file, e.args)
            raise e
        finally:
            if cursor is not None:
                cursor.close()
            if database is not None:
                database.close()

    def delete(self) -> Path:
        file: Path = EventDatabase(self.uniq_id).file
        arch: Path = file.parent / f'{file.stem}_{datetime.strftime(datetime.now(), "%Y-%m-%d-%H-%M")}.arch'
        file.rename(arch)
        return arch

    def set_last_update(self):
        self._execute('UPDATE `info` SET `last_update` = ?', (time.time(),))

    def rename(self, new_uniq_id: str = None):
        self.file.rename(EventDatabase(new_uniq_id).file)
        with EventDatabase(new_uniq_id, write=True) as event_database:
            event_database.set_last_update()
            event_database.commit()

    def clone(self, new_uniq_id: str):
        shutil.copy(self.file, EventDatabase(new_uniq_id).file)
        with EventDatabase(new_uniq_id, write=True) as event_database:
            event_database.set_last_update()
            event_database.commit()

    def __enter__(self) -> Self:
        if not self.exists():
            raise FileNotFoundError(
                f'La base de données ne peut être ouverte car le fichier [{self.file.resolve()}] n\'existe pas.')
        super().__enter__()
        papi_web_version: Version = PapiWebConfig().version
        if self.version != Version(f'{papi_web_version.major}.{papi_web_version.minor}.{papi_web_version.micro}'):
            if self.write:
                self.upgrade()
            else:
                with EventDatabase(self.uniq_id, write=True) as event_database:
                    event_database.upgrade()
        return self

    """ 
    ---------------------------------------------------------------------------------
    StoredEvent 
    ---------------------------------------------------------------------------------
    """

    def _row_to_stored_event(self, row: dict[str, Any]) -> StoredEvent:
        return StoredEvent(
            uniq_id=self.uniq_id,
            version=row['version'],
            name=row['name'],
            start=row['start'],
            stop=row['stop'],
            public=self.load_bool_from_database_field(row['public']),
            path=row['path'],
            image_url=row['image_url'],
            image_color=row['image_color'],
            update_password=row['update_password'],
            record_illegal_moves=row['record_illegal_moves'],
            allow_results_deletion_on_input_screens=self.load_bool_from_database_field(
                row['allow_results_deletion_on_input_screens']),
            timer_colors=self.set_dict_int_keys(self.load_json_from_database_field(row['timer_colors'])),
            timer_delays=self.set_dict_int_keys(self.load_json_from_database_field(row['timer_delays'])),
            last_update=row['last_update'],
        )

    def _get_stored_event(self) -> StoredEvent:
        self._execute(
            'SELECT * FROM `info`',
            (),
        )
        return self._row_to_stored_event(self._fetchone())

    def load_stored_event(self) -> StoredEvent:
        stored_event: StoredEvent = self._get_stored_event()
        stored_event.stored_chessevents = self.load_stored_chessevents()
        stored_event.stored_tournaments = self.load_stored_tournaments()
        stored_event.stored_timers = self.load_stored_timers()
        stored_event.stored_families = self.load_stored_families()
        stored_event.stored_screens = self.load_stored_screens()
        stored_event.stored_rotators = self.load_stored_rotators()
        return stored_event

    @property
    def version(self) -> Version:
        if self._version is None:
            self._version = Version(self._get_stored_event().version)
        return self._version

    def set_version(self, version: Version):
        self._execute(
            'UPDATE `info` SET `version` = ?, `last_update` = ?',
            (f'{version.major}.{version.minor}.{version.micro}', time.time()))
        self._version = version

    def _upgrade(self, version: Version):
        match version:
            case Version('2.4.1'):
                self._execute('')
                self.set_version(version)
                self.commit()
            case _:
                raise PapiWebException(
                    f'La base de données {self.file.name} ne peut être mise à jour en version {version}.')
        logger.info(f'La base de données {self.file.name} a été mise à jour en version {version}.')

    def upgrade(self):
        papi_web_version: Version = PapiWebConfig().version
        if self.version > papi_web_version:
            raise PapiWebException(
                f'Votre version de Papi-web ({papi_web_version}) '
                f'ne peut pas ouvrir les bases de données en version {self.version}, '
                f'veuillez mettre à jour votre version de Papi-web')
        logger.info(f'Mise à jour de la base de données...')
        if self.version < (version := Version('2.4.1')):
            self._upgrade(version)

    def update_stored_event(
            self, stored_event: StoredEvent
    ) -> StoredEvent:
        fields: list[str] = [
            'name', 'start', 'stop', 'public', 'path', 'image_url', 'image_color', 'update_password',
            'record_illegal_moves', 'allow_results_deletion_on_input_screens', 'timer_colors', 'timer_delays',
            'last_update',
        ]
        params: list = [
            stored_event.name, stored_event.start, stored_event.stop, stored_event.public, stored_event.path,
            stored_event.image_url, stored_event.image_color, stored_event.update_password,
            stored_event.record_illegal_moves, stored_event.allow_results_deletion_on_input_screens,
            self.dump_to_json_database_timer_colors(stored_event.timer_colors),
            self.dump_to_json_database_timer_delays(stored_event.timer_delays),
            time.time(),
        ]
        field_sets = [f"`{f}` = ?" for f in fields]
        self._execute(
            f'UPDATE `info` SET {", ".join(field_sets)}',
            tuple(params))
        return self._get_stored_event()

    """ 
    ---------------------------------------------------------------------------------
    StoredChessEvent 
    ---------------------------------------------------------------------------------
    """

    @staticmethod
    def _row_to_stored_chessevent(row: dict[str, Any]) -> StoredChessEvent:
        return StoredChessEvent(
                id=row['id'],
                uniq_id=row['uniq_id'],
                user_id=row['user_id'],
                password=row['password'],
                event_id=row['event_id'],
            )

    def get_stored_chessevent(self, chessevent_id: int) -> StoredChessEvent | None:
        self._execute(
            'SELECT * FROM `chessevent` WHERE `id` = ?',
            (chessevent_id,),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_chessevent(row)
        return None

    def load_stored_chessevents(self) -> list[StoredChessEvent]:
        self._execute(
            'SELECT * FROM `chessevent` ORDER BY `uniq_id`',
            (),
        )
        return [self._row_to_stored_chessevent(row) for row in self._fetchall()]

    def _write_stored_chessevent(
            self, stored_chessevent: StoredChessEvent,
    ) -> StoredChessEvent:
        fields: list[str] = ['uniq_id', 'user_id', 'password', 'event_id', ]
        params: list = [
            stored_chessevent.uniq_id, stored_chessevent.user_id, stored_chessevent.password,
            stored_chessevent.event_id,
        ]
        if stored_chessevent.id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `chessevent`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            stored_chessevent = self.get_stored_chessevent(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_chessevent.id]
            self._execute(
                f'UPDATE `chessevent` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            stored_chessevent = self.get_stored_chessevent(stored_chessevent.id)
        self.set_last_update()
        return stored_chessevent

    def add_stored_chessevent(
            self, stored_chessevent: StoredChessEvent,
    ) -> StoredChessEvent:
        assert stored_chessevent.id is None, f'stored_chessevent.id={stored_chessevent.id}'
        return self._write_stored_chessevent(stored_chessevent)

    def update_stored_chessevent(
            self, stored_chessevent: StoredChessEvent,
    ) -> StoredChessEvent:
        assert stored_chessevent.id is not None
        return self._write_stored_chessevent(stored_chessevent)

    def delete_stored_chessevent(self, chessevent_id: int):
        self._execute(
            'UPDATE `tournament` '
            'SET `chessevent_id` = NULL, `chessevent_tournament_name` = NULL '
            'WHERE `chessevent_id` = ?;', (chessevent_id,))
        self._execute('DELETE FROM `chessevent` WHERE `id` = ?;', (chessevent_id,))
        self.set_last_update()

    def clone_stored_chessevent(
            self, chessevent_id: int,
    ) -> StoredChessEvent:
        stored_chessevent = self.get_stored_chessevent(chessevent_id)
        stored_chessevent.id = None
        self._execute(
            'SELECT uniq_id FROM `chessevent`',
            (),
        )
        uniq_ids: list[str] = [row['uniq_id'] for row in self._fetchall()]
        uniq_id: str = f'{stored_chessevent.uniq_id}-clone'
        clone_index: int = 1
        stored_chessevent.uniq_id = uniq_id
        while stored_chessevent.uniq_id in uniq_ids:
            clone_index += 1
            stored_chessevent.uniq_id = f'{uniq_id}{clone_index}'
        return self._write_stored_chessevent(stored_chessevent)

    """ 
    ---------------------------------------------------------------------------------
    StoredTimerHour
    ---------------------------------------------------------------------------------
    """

    @staticmethod
    def _row_to_stored_timer_hour(row: dict[str, Any]) -> StoredTimerHour:
        return StoredTimerHour(
            id=row['id'],
            uniq_id=row['uniq_id'],
            timer_id=row['timer_id'],
            order=row['order'],
            date_str=row['date_str'],
            time_str=row['time_str'],
            text_before=row['text_before'],
            text_after=row['text_after'],
        )

    def get_stored_timer_hour(self, timer_hour_id: int) -> StoredTimerHour | None:
        self._execute(
            'SELECT * FROM `timer_hour` WHERE `id` = ?',
            (timer_hour_id,),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_timer_hour(row)
        return None

    def get_stored_timer_next_hour_order(self, timer_id: int) -> int:
        self._execute(
            'SELECT MAX(`order`) AS order_max FROM `timer_hour` WHERE `timer_id` = ?',
            (timer_id, ),
        )
        row: dict[str, Any] = self._fetchone()
        return (row['order_max'] if row['order_max'] else 0) + 1

    def get_stored_timer_next_round(self, timer_id: int) -> int:
        self._execute(
            'SELECT `uniq_id` FROM `timer_hour` WHERE `timer_id` = ?',
            (timer_id, ),
        )
        highest_round: int = 0
        for row in self._fetchall():
            with suppress(ValueError):
                highest_round = max(highest_round, int(row['uniq_id']))
        return highest_round + 1

    def load_stored_timer_hours(self, timer_id: int) -> list[StoredTimerHour]:
        self._execute(
            'SELECT * FROM `timer_hour` WHERE `timer_id` = ? ORDER BY `order`',
            (timer_id, ),
        )
        return [self._row_to_stored_timer_hour(row) for row in self._fetchall()]

    def _write_stored_timer_hour(
            self, stored_timer_hour: StoredTimerHour,
    ) -> StoredTimerHour:
        fields: list[str] = ['timer_id', 'uniq_id', 'order', 'date_str', 'time_str', 'text_before', 'text_after', ]
        params: list = [
            stored_timer_hour.timer_id, stored_timer_hour.uniq_id, stored_timer_hour.order, stored_timer_hour.date_str,
            stored_timer_hour.time_str, stored_timer_hour.text_before, stored_timer_hour.text_after,
        ]
        if stored_timer_hour.id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `timer_hour`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            stored_timer_hour = self.get_stored_timer_hour(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_timer_hour.id]
            self._execute(
                f'UPDATE `timer_hour` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            stored_timer_hour = self.get_stored_timer_hour(stored_timer_hour.id)
        self.set_last_update()
        return stored_timer_hour

    def reorder_stored_timer_hours(
            self, timer_hour_ids: list[int],
    ):
        order: int = 1
        for timer_hour_id in timer_hour_ids:
            self._execute(
                f'UPDATE `timer_hour` SET `order` = ? WHERE `id` = ?',
                (order, timer_hour_id, ),
            )
            order += 1
        self.set_last_update()

    def update_stored_timer_hour(
            self, stored_timer_hour: StoredTimerHour,
    ) -> StoredTimerHour:
        assert stored_timer_hour.id is not None
        return self._write_stored_timer_hour(stored_timer_hour)

    def add_stored_timer_hour(
            self,
            timer_id: int,
            set_datetime: bool = False,
    ) -> StoredTimerHour:
        stored_timer_hour: StoredTimerHour = StoredTimerHour(
            id=None,
            timer_id=timer_id,
            uniq_id=str(self.get_stored_timer_next_round(timer_id)),
            order=self.get_stored_timer_next_hour_order(timer_id),
        )
        if set_datetime:
            stored_timer_hour.date_str = format_timestamp_date()
            stored_timer_hour.time_str = format_timestamp_time(time.time())
        return self._write_stored_timer_hour(stored_timer_hour)

    def clone_stored_timer_hour(self, timer_hour_id: int, timer_id: int | None = None):
        stored_timer_hour = self.get_stored_timer_hour(timer_hour_id)
        stored_timer_hour.id = None
        if timer_id is None:
            round: int = 0
            try:
                round = int(stored_timer_hour.uniq_id)
            except ValueError:
                pass
            stored_timer_hour.order = self.get_stored_timer_next_hour_order(stored_timer_hour.timer_id)
            if round:
                stored_timer_hour.uniq_id = str(self.get_stored_timer_next_round(stored_timer_hour.timer_id))
            else:
                self._execute(
                    'SELECT uniq_id FROM `timer_hour` WHERE `timer_id` = ?',
                    (stored_timer_hour.timer_id, ),
                )
                uniq_ids: list[str] = [row['uniq_id'] for row in self._fetchall()]
                uniq_id: str = f'{stored_timer_hour.uniq_id}-clone'
                clone_index: int = 1
                stored_timer_hour.uniq_id = uniq_id
                while stored_timer_hour.uniq_id in uniq_ids:
                    clone_index += 1
                    stored_timer_hour.uniq_id = f'{uniq_id}{clone_index}'
        else:
            stored_timer_hour.timer_id = timer_id
        return self._write_stored_timer_hour(stored_timer_hour)

    def delete_stored_timer_hour(self, timer_hour_id: int, timer_id: int):
        self._execute('DELETE FROM `timer_hour` WHERE `id` = ?;', (timer_hour_id,))
        order: int = 1
        for stored_timer_hour in self.load_stored_timer_hours(timer_id):
            self._execute(
                f'UPDATE `timer_hour` SET `order` = ? WHERE `id` = ?',
                (order, stored_timer_hour.id, ),
            )
            order += 1
        self.set_last_update()

    def _delete_stored_timer_hours(self, timer_id: int):
        self._execute('DELETE FROM `timer_hour` WHERE `timer_id` = ?;', (timer_id,))

    """ 
    ---------------------------------------------------------------------------------
    StoredTimer
    ---------------------------------------------------------------------------------
    """

    @classmethod
    def _row_to_stored_timer(cls, row: dict[str, Any]) -> StoredTimer:
        return StoredTimer(
            id=row['id'],
            uniq_id=row['uniq_id'],
            colors=cls.set_dict_int_keys(cls.load_json_from_database_field(row['colors'])),
            delays=cls.set_dict_int_keys(cls.load_json_from_database_field(row['delays'])),
        )

    def get_stored_timer(self, timer_id: int) -> StoredTimer | None:
        self._execute(
            'SELECT * FROM `timer` WHERE `id` = ?',
            (timer_id,),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_timer(row)
        return None

    def load_stored_timer(self, timer_id: int) -> StoredTimer:
        stored_timer: StoredTimer
        if stored_timer := self.get_stored_timer(timer_id):
            stored_timer.stored_timer_hours = self.load_stored_timer_hours(stored_timer.id)
        return stored_timer

    def get_stored_timer_ids(self) -> list[int]:
        self._execute('SELECT `id` FROM `timer` ORDER BY `uniq_id`', (), )
        return [row['id'] for row in self._fetchall()]

    def load_stored_timers(self) -> list[StoredTimer]:
        stored_timers: list[StoredTimer] = [self.get_stored_timer(id) for id in self.get_stored_timer_ids()]
        for stored_timer in stored_timers:
            stored_timer.stored_timer_hours = self.load_stored_timer_hours(stored_timer.id)
        return stored_timers

    def _write_stored_timer(
            self, stored_timer: StoredTimer,
    ) -> StoredTimer:
        fields: list[str] = [
            'uniq_id',
            'colors',
            'delays',
        ]
        params: list = [
            stored_timer.uniq_id,
            self.dump_to_json_database_timer_colors(stored_timer.colors),
            self.dump_to_json_database_timer_delays(stored_timer.delays),
        ]
        if stored_timer.id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `timer`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            stored_timer = self.get_stored_timer(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_timer.id]
            self._execute(
                f'UPDATE `timer` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            stored_timer = self.get_stored_timer(stored_timer.id)
        self.set_last_update()
        return stored_timer

    def add_stored_timer(
            self, stored_timer: StoredTimer,
    ) -> StoredTimer:
        assert stored_timer.id is None, f'stored_timer.id={stored_timer.id}'
        return self._write_stored_timer(stored_timer)

    def update_stored_timer(
            self, stored_timer: StoredTimer,
    ) -> StoredTimer:
        assert stored_timer.id is not None
        return self._write_stored_timer(stored_timer)

    def clone_stored_timer(
            self, timer_id: int, new_uniq_id: str,
    ) -> StoredTimer:
        stored_timer = self.load_stored_timer(timer_id)
        stored_timer.id = None
        stored_timer.uniq_id = new_uniq_id
        new_stored_timer: StoredTimer = self._write_stored_timer(stored_timer)
        for stored_timer_hour in stored_timer.stored_timer_hours:
            new_stored_timer.stored_timer_hours.append(
                self.clone_stored_timer_hour(stored_timer_hour.id, new_stored_timer.id))
        return new_stored_timer

    def delete_stored_timer(self, timer_id: int):
        self._execute('UPDATE `family` SET `timer_id` = NULL WHERE `timer_id` = ?;', (timer_id,))
        self._execute('UPDATE `screen` SET `timer_id` = NULL WHERE `timer_id` = ?;', (timer_id,))
        self._delete_stored_timer_hours(timer_id)
        # references are not deleted as they shoud be!
        self._execute('DELETE FROM `timer` WHERE id = ?;', (timer_id,))
        self.set_last_update()

    """ 
    ---------------------------------------------------------------------------------
    Skipped rounds 
    ---------------------------------------------------------------------------------
    """

    @staticmethod
    def _row_to_stored_skipped_round(row: dict[str, Any]) -> StoredSkippedRound:
        return StoredSkippedRound(
            id=row['id'],
            tournament_id=row['tournament_id'],
            round=row['round'],
            papi_player_id=row['papi_player_id'],
            score=row['score'],
        )

    def load_stored_skipped_rounds(self, tournament_id: int) -> list[StoredSkippedRound]:
        self._execute(
            'SELECT * FROM `skipped_round` WHERE `tournament_id` = ? ORDER BY `id`',
            (tournament_id, ),
        )
        return [self._row_to_stored_skipped_round(row) for row in self._fetchall()]

    def delete_tournament_stored_skipped_rounds(self, tournament_id: int):
        self._execute(
            'DELETE FROM `skipped_round` WHERE `tournament_id` = ?',
            (tournament_id, ),
        )

    def add_player_stored_skipped_rounds(
            self, tournament_id: int, papi_player_id: int, skipped_rounds: dict[int, float]
    ):
        if skipped_rounds:
            for round, score in skipped_rounds.items():
                self._execute(
                    'INSERT INTO `skipped_round`('
                    '    `tournament_id`, '
                    '    `papi_player_id`, '
                    '    `round`, '
                    '    `score`'
                    ') VALUES(?, ?, ?, ?)',
                    (tournament_id, papi_player_id, round, score),
                )

    """ 
    ---------------------------------------------------------------------------------
    StoredTournament 
    ---------------------------------------------------------------------------------
    """

    @staticmethod
    def _row_to_stored_tournament(row: dict[str, Any]) -> StoredTournament:
        return StoredTournament(
            id=row['id'],
            uniq_id=row['uniq_id'],
            name=row['name'],
            path=row['path'],
            filename=row['filename'],
            ffe_id=row['ffe_id'],
            ffe_password=row['ffe_password'],
            time_control_initial_time=row['time_control_initial_time'],
            time_control_increment=row['time_control_increment'],
            time_control_handicap_penalty_step=row['time_control_handicap_penalty_step'],
            time_control_handicap_penalty_value=row['time_control_handicap_penalty_value'],
            time_control_handicap_min_time=row['time_control_handicap_min_time'],
            chessevent_id=row['chessevent_id'],
            chessevent_tournament_name=row['chessevent_tournament_name'],
            record_illegal_moves=row['record_illegal_moves'],
            last_update=row['last_update'],
            last_result_update=row['last_result_update'],
            last_illegal_move_update=row['last_illegal_move_update'],
            last_check_in_update=row['last_check_in_update'],
            last_ffe_upload=row['last_ffe_upload'],
            last_chessevent_download_md5=row['last_chessevent_download_md5'],
        )

    def get_stored_tournament(self, tournament_id: int) -> StoredTournament | None:
        self._execute(
            'SELECT * FROM `tournament` WHERE `id` = ?',
            (tournament_id,),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_tournament(row)
        return None

    def load_stored_tournaments(self) -> list[StoredTournament]:
        self._execute(
            'SELECT * FROM `tournament` ORDER BY `uniq_id`',
            (),
        )
        stored_tournaments: list[StoredTournament] = [self._row_to_stored_tournament(row) for row in self._fetchall()]
        for stored_tournament in stored_tournaments:
            stored_tournament.stored_skipped_rounds = self.load_stored_skipped_rounds(stored_tournament.id)
        return stored_tournaments

    def _write_stored_tournament(
            self, stored_tournament: StoredTournament,
    ) -> StoredTournament:
        fields: list[str] = [
            'uniq_id', 'name', 'path', 'filename', 'ffe_id', 'ffe_password',
            'time_control_initial_time', 'time_control_increment', 'time_control_handicap_penalty_step',
            'time_control_handicap_penalty_value', 'time_control_handicap_min_time', 'chessevent_id',
            'chessevent_tournament_name', 'record_illegal_moves', 'last_update', 'last_result_update',
            'last_illegal_move_update', 'last_check_in_update', 'last_ffe_upload', 'last_chessevent_download_md5',
        ]
        params: list = [
            stored_tournament.uniq_id, stored_tournament.name, stored_tournament.path, stored_tournament.filename,
            stored_tournament.ffe_id, stored_tournament.ffe_password, stored_tournament.time_control_initial_time,
            stored_tournament.time_control_increment, stored_tournament.time_control_handicap_penalty_step,
            stored_tournament.time_control_handicap_penalty_value, stored_tournament.time_control_handicap_min_time,
            stored_tournament.chessevent_id, stored_tournament.chessevent_tournament_name,
            stored_tournament.record_illegal_moves, time.time(), stored_tournament.last_result_update,
            stored_tournament.last_illegal_move_update, stored_tournament.last_check_in_update,
            stored_tournament.last_ffe_upload, stored_tournament.last_chessevent_download_md5,
        ]
        if stored_tournament.id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `tournament`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            stored_tournament = self.get_stored_tournament(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_tournament.id]
            self._execute(
                f'UPDATE `tournament` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            stored_tournament = self.get_stored_tournament(stored_tournament.id)
        self.set_last_update()
        return stored_tournament

    def add_stored_tournament(
            self, stored_tournament: StoredTournament,
    ) -> StoredTournament:
        assert stored_tournament.id is None, f'stored_tournament.id={stored_tournament.id}'
        return self._write_stored_tournament(stored_tournament)

    def update_stored_tournament(
            self, stored_tournament: StoredTournament,
    ) -> StoredTournament:
        assert stored_tournament.id is not None
        return self._write_stored_tournament(stored_tournament)

    def delete_stored_tournament(self, tournament_id: int):
        self.delete_tournament_stored_skipped_rounds(tournament_id)
        self._delete_tournament_stored_screens(tournament_id)
        self._delete_tournament_stored_families(tournament_id)
        self._delete_tournament_stored_illegal_moves(tournament_id)
        self._delete_tournament_stored_results(tournament_id)
        # references are not deleted on cascade as they should be!
        self._execute('DELETE FROM `tournament` WHERE `id` = ?;', (tournament_id,))
        self.set_last_update()

    def clone_stored_tournament(
            self, tournament_id: int, new_uniq_id: str, new_name: str, new_path: str | None, new_filename: str | None,
            new_ffe_id: int | None, new_ffe_password: str | None,
    ) -> StoredTournament:
        stored_tournament = self.get_stored_tournament(tournament_id)
        stored_tournament.id = None
        stored_tournament.uniq_id = new_uniq_id
        stored_tournament.name = new_name
        stored_tournament.path = new_path
        stored_tournament.filename = new_filename
        stored_tournament.ffe_id = new_ffe_id
        stored_tournament.ffe_password = new_ffe_password
        stored_tournament.last_update = time.time(),
        stored_tournament.last_result_update = 0.0
        stored_tournament.last_illegal_move_update = 0.0
        stored_tournament.last_check_in_update = 0.0
        stored_tournament.last_ffe_upload = 0.0
        stored_tournament.last_chessevent_download = 0.0
        return self._write_stored_tournament(stored_tournament)

    def set_tournament_last_ffe_upload(self, tournament_id: int):
        self._execute(
            f'UPDATE `tournament` SET `last_ffe_upload` = ? WHERE `id` = ?',
            (time.time(), tournament_id, ))

    def set_tournament_last_chessevent_download_md5(self, tournament_id: int, md5: str = None):
        self._execute(
            f'UPDATE `tournament` SET `last_chessevent_download_md5` = ? WHERE `id` = ?',
            (md5, tournament_id, ))

    def _set_tournament_last_illegal_move_update(self, tournament_id: int):
        self._execute(
            'UPDATE `tournament` SET `last_illegal_move_update` = ? WHERE `id` = ?',
            (time.time(), tournament_id, ),
        )

    def set_tournament_last_check_in_update(self, tournament_id: int):
        self._execute(
            'UPDATE `tournament` SET `last_check_in_update` = ? WHERE `id` = ?',
            (time.time(), tournament_id, ),
        )

    def _set_tournament_last_result_update(self, tournament_id: int):
        self._execute(
            'UPDATE `tournament` SET `last_result_update` = ? WHERE `id` = ?',
            (time.time(), tournament_id, ),
        )

    """ 
    ---------------------------------------------------------------------------------
    Illegal moves 
    ---------------------------------------------------------------------------------
    """

    @staticmethod
    def _row_to_stored_illegal_move(row: dict[str, Any]) -> StoredIllegalMove:
        return StoredIllegalMove(
            id=row['id'],
            tournament_id=row['tournament_id'],
            round=row['round'],
            player_id=row['player_id'],
            date=row['date'],
        )

    def _get_stored_illegal_move(self, illegal_move_id: int, ) -> StoredIllegalMove | None:
        self._execute(
            'SELECT * FROM `illegal_move` WHERE `id` = ?',
            (illegal_move_id,),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_illegal_move(row)
        return None

    def get_stored_illegal_moves(self, tournament_id: int, round: int) -> Counter[int]:
        self._execute(
            'SELECT `illegal_move`.* '
            'FROM `illegal_move` '
            'JOIN `tournament` ON `illegal_move`.`tournament_id` = `tournament`.`id`' 
            'WHERE `tournament`.`id` = ? AND `round` = ?',
            (tournament_id, round,),
        )
        illegal_moves: Counter[int] = Counter[int]()
        for row in self._fetchall():
            illegal_moves[int(row['player_id'])] += 1
        return illegal_moves

    def add_stored_illegal_move(self, tournament_id: int, round: int, player_id: int) -> StoredIllegalMove:
        self._set_tournament_last_illegal_move_update(tournament_id)
        fields: list[str] = ['tournament_id', 'round', 'player_id', 'date', ]
        params: list = [tournament_id, round, player_id, time.time()]
        protected_fields = [f"`{f}`" for f in fields]
        self._execute(
            f'INSERT INTO `illegal_move`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
            tuple(params))
        return self._get_stored_illegal_move(self._last_inserted_id())

    def delete_stored_illegal_move(self, tournament_id: int, round: int, player_id: int) -> bool:
        self._set_tournament_last_illegal_move_update(tournament_id)
        self._execute(
            'SELECT `id` FROM `illegal_move` WHERE `tournament_id` = ? AND `round` = ? AND `player_id` = ? LIMIT 1',
            (tournament_id, round, player_id, ),
        )
        row: dict[str, Any] = self._fetchone()
        if not row:
            return False
        self._execute(
            'DELETE FROM `illegal_move` WHERE `id` = ?',
            (row['id'], ),
        )
        return True

    def _delete_tournament_stored_illegal_moves(self, tournament_id: int, round: int = 0):
        self._set_tournament_last_illegal_move_update(tournament_id)
        if round:
            self._execute(
                'DELETE FROM `illegal_move` WHERE `tournament_id` = ? AND `round` = ?',
                (tournament_id, round, ),
            )
        else:
            self._execute(
                'DELETE FROM `illegal_move` WHERE `tournament_id` = ?',
                (tournament_id, ),
            )

    """ 
    ---------------------------------------------------------------------------------
    results
    ---------------------------------------------------------------------------------
    """

    @staticmethod
    def _row_to_stored_result(row: dict[str, Any]) -> StoredResult:
        return StoredResult(
            id=row['id'],
            tournament_id=row['tournament_id'],
            board_id=row['board_id'],
            result=row['result'],
            date=row['date'],
        )

    def _get_stored_result(
            self, result_id: int,
    ) -> StoredResult | None:
        self._execute(
            'SELECT * FROM `result` WHERE `id` = ?',
            (result_id,),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_result(row)
        return None

    def add_stored_result(self, tournament_id: int, round: int, board: Board, result: UtilResult):
        self._set_tournament_last_result_update(tournament_id)
        self._execute(
            'INSERT INTO `result`('
            '    `tournament_id`, `round`, `board_id`, '
            '    `white_player_id`, `black_player_id`, '
            '    `value`, `date`'
            ') VALUES(?, ?, ?, ?, ?, ?, ?)',
            (
                tournament_id,
                round,
                board.id,
                board.white_player.id,
                board.black_player.id,
                result,
                time.time(),
            ),
        )

    def delete_stored_result(self, tournament_id: int, round: int, board_id: int):
        self._set_tournament_last_result_update(tournament_id)
        self._execute(
            'DELETE FROM `result` WHERE `tournament_id` = ? AND `round` = ? AND `board_id` = ?',
            (tournament_id, round, board_id),
        )

    def _delete_tournament_stored_results(self, tournament_id: int):
        self._execute(
            'DELETE FROM `result` WHERE `tournament_id` = ?',
            (tournament_id, ),
        )

    def get_stored_results(self, limit: int, tournament_ids: list[int]) -> list[DataResult]:
        if not tournament_ids:
            query: str = ('SELECT '
                          '    * '
                          'FROM `result` '
                          'ORDER BY `date` DESC')
            params: tuple = ()
        else:
            query: str = ('SELECT '
                          '    * '
                          'FROM `result` '
                          f'WHERE {" OR ".join([f"`tournament_id` = ?", ] * len(tournament_ids))} '
                          'ORDER BY `date` DESC')
            params: tuple[int] = tuple(tournament_ids)
        if limit:
            query += ' LIMIT ?'
            params = (limit, )
        self._execute(query, params)
        results: list[DataResult] = []
        for row in self._fetchall():
            try:
                value: UtilResult = UtilResult.from_papi_value(int(row['value']))
            except ValueError:
                logger.warning('invalid result [%s] found in database', row['value'])
                continue
            results.append(DataResult(
                    row['date'],
                    row['tournament_id'],
                    row['round'],
                    row['board_id'],
                    row['white_player_id'],
                    row['black_player_id'],
                    value))
        return results

    """ 
    ---------------------------------------------------------------------------------
    StoredFamily 
    ---------------------------------------------------------------------------------
    """

    @classmethod
    def _row_to_stored_family(cls, row: dict[str, Any]) -> StoredFamily:
        return StoredFamily(
            id=row['id'],
            uniq_id=row['uniq_id'],
            name=row['name'],
            type=row['type'],
            public=cls.load_bool_from_database_field(row['public']),
            tournament_id=row['tournament_id'],
            players_show_unpaired=cls.load_bool_from_database_field(row['players_show_unpaired']),
            columns=row['columns'],
            menu_text=row['menu_text'],
            menu=row['menu'],
            timer_id=row['timer_id'],
            first=row['first'],
            last=row['last'],
            parts=row['parts'],
            number=row['number'],
            last_update=row['last_update'],
        )

    def get_stored_family(self, family_id: int) -> StoredFamily | None:
        self._execute(
            'SELECT * FROM `family` WHERE `id` = ?',
            (family_id,),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_family(row)
        return None

    def load_stored_families(self) -> list[StoredFamily]:
        self._execute(
            'SELECT * FROM `family` ORDER BY `uniq_id`',
            (),
        )
        return [self._row_to_stored_family(row) for row in self._fetchall()]

    def _write_stored_family(
            self, stored_family: StoredFamily,
    ) -> StoredFamily:
        fields: list[str] = [
            'uniq_id', 'name', 'type', 'public', 'tournament_id', 'columns', 'menu_text', 'menu', 'timer_id',
            'players_show_unpaired', 'first', 'last', 'parts', 'number', 'last_update',
        ]
        params: list = [
            stored_family.uniq_id, stored_family.name, stored_family.type, stored_family.public,
            stored_family.tournament_id, stored_family.columns, stored_family.menu_text, stored_family.menu,
            stored_family.timer_id, stored_family.players_show_unpaired, stored_family.first, stored_family.last,
            stored_family.parts, stored_family.number, time.time(),
        ]
        if stored_family.id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `family`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            stored_family = self.get_stored_family(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_family.id]
            self._execute(
                f'UPDATE `family` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            stored_family = self.get_stored_family(stored_family.id)
        self.set_last_update()
        return stored_family

    def add_stored_family(
            self, stored_family: StoredFamily,
    ) -> StoredFamily:
        assert stored_family.id is None, f'stored_family.id={stored_family.id}'
        return self._write_stored_family(stored_family)

    def update_stored_family(
            self, stored_family: StoredFamily,
    ) -> StoredFamily:
        assert stored_family.id is not None
        return self._write_stored_family(stored_family)

    def delete_stored_family(self, family_id: int):
        self._execute('DELETE FROM `family` WHERE `id` = ?;', (family_id,))
        self.set_last_update()

    def _delete_tournament_stored_families(self, tournament_id: int):
        self._execute('DELETE FROM `family` WHERE `tournament_id` = ?;', (tournament_id,))

    """ 
    ---------------------------------------------------------------------------------
    StoredScreen 
    ---------------------------------------------------------------------------------
    """

    @classmethod
    def _row_to_stored_screen(cls, row: dict[str, Any]) -> StoredScreen:
        return StoredScreen(
            id=row['id'],
            uniq_id=row['uniq_id'],
            name=row['name'],
            type=row['type'],
            public=cls.load_bool_from_database_field(row['public']),
            columns=row['columns'],
            menu_text=row['menu_text'],
            menu=row['menu'],
            timer_id=row['timer_id'],
            players_show_unpaired=cls.load_bool_from_database_field(row['players_show_unpaired']),
            results_limit=row['results_limit'],
            results_tournament_ids=cls.load_json_from_database_field(row['results_tournament_ids']),
            image_url=row['image_url'],
            image_color=row['image_color'],
            last_update=row['last_update'],
        )

    def get_stored_screen(self, screen_id: int) -> StoredScreen | None:
        self._execute(
            'SELECT * FROM `screen` WHERE `id` = ?',
            (screen_id,),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_screen(row)
        return None

    def load_stored_screen(self, screen_id: int) -> StoredScreen:
        stored_screen: StoredScreen
        if stored_screen := self.get_stored_screen(screen_id):
            stored_screen.stored_screen_sets = self.load_stored_screen_sets(stored_screen.id)
        return stored_screen

    def load_stored_screens(self) -> list[StoredScreen]:
        self._execute(
            'SELECT * FROM `screen` ORDER BY `uniq_id`',
            (),
        )
        stored_screens: list[StoredScreen] = [self._row_to_stored_screen(row) for row in self._fetchall()]
        for stored_screen in stored_screens:
            stored_screen.stored_screen_sets = self.load_stored_screen_sets(stored_screen.id)
        return stored_screens

    def _set_stored_screen_last_update(self, screen_id: int):
        self._execute(
            f'UPDATE `screen` SET `last_update` = ? WHERE `id` = ?',
            (time.time(), screen_id,),
        )

    def _write_stored_screen(
            self, stored_screen: StoredScreen,
    ) -> StoredScreen:
        fields: list[str] = [
            'uniq_id', 'name', 'type', 'public', 'players_show_unpaired', 'columns', 'menu_text', 'menu', 'timer_id',
            'results_limit', 'results_tournament_ids', 'image_url', 'image_color', 'last_update',
        ]
        params: list = [
            stored_screen.uniq_id, stored_screen.name, stored_screen.type,
            stored_screen.public, stored_screen.players_show_unpaired if stored_screen.type == 'players' else None,
            stored_screen.columns, stored_screen.menu_text, stored_screen.menu, stored_screen.timer_id,
            stored_screen.results_limit if stored_screen.type == 'results' else None,
            self.dump_to_json_database_field(stored_screen.results_tournament_ids, [])
            if stored_screen.type == 'results' else None,
            stored_screen.image_url if stored_screen.type == 'image' else None,
            stored_screen.image_color if stored_screen.type == 'image' else None,
            time.time(),
        ]
        if stored_screen.id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `screen`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            stored_screen = self.get_stored_screen(screen_id=self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_screen.id]
            self._execute(
                f'UPDATE `screen` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            stored_screen = self.get_stored_screen(screen_id=stored_screen.id)
        self.set_last_update()
        return stored_screen

    def clone_stored_screen(
            self, screen_id: int, new_uniq_id: str, new_name: str,
    ) -> StoredScreen:
        stored_screen = self.load_stored_screen(screen_id)
        stored_screen.id = None
        stored_screen.uniq_id = new_uniq_id
        stored_screen.name = new_name
        stored_screen.last_update = time.time()
        new_stored_screen: StoredScreen = self._write_stored_screen(stored_screen)
        for stored_screen_set in stored_screen.stored_screen_sets:
            new_stored_screen.stored_screen_sets.append(
                self.clone_stored_screen_set(stored_screen_set.id, new_stored_screen.id))
        return new_stored_screen

    def add_stored_screen(
            self, stored_screen: StoredScreen,
    ) -> StoredScreen:
        assert stored_screen.id is None, f'stored_screen.id={stored_screen.id}'
        return self._write_stored_screen(stored_screen)

    def update_stored_screen(
            self, stored_screen: StoredScreen,
    ) -> StoredScreen:
        assert stored_screen.id is not None
        return self._write_stored_screen(stored_screen)

    def _delete_screen_stored_screen_sets(self, screen_id: int):
        self._execute('DELETE FROM `screen_set` WHERE `screen_id` = ?;', (screen_id,))

    def delete_stored_screen(self, screen_id: int):
        self._delete_screen_stored_screen_sets(screen_id)
        self._execute('DELETE FROM `screen` WHERE `id` = ?;', (screen_id,))
        self.set_last_update()

    def _delete_tournament_stored_screens(self, tournament_id: int):
        self._execute(
            'SELECT `screen`.`id` AS `screen_id` '
            'FROM `screen` '
            'JOIN `screen_set` ON `screen_set`.`screen_id` = `screen`.`id` ' 
            'WHERE `screen_set`.`tournament_id` = ?',
            (tournament_id,),
        )
        for row in self._fetchall():
            self.delete_stored_screen(row['screen_id'])

    """ 
    ---------------------------------------------------------------------------------
    StoredScreenSet
    ---------------------------------------------------------------------------------
    """

    @staticmethod
    def _row_to_stored_screen_set(row: dict[str, Any]) -> StoredScreenSet:
        return StoredScreenSet(
            id=row['id'],
            screen_id=row['screen_id'],
            tournament_id=row['tournament_id'],
            order=row['order'],
            name=row['name'],
            fixed_boards_str=row['fixed_boards_str'],
            first=row['first'],
            last=row['last'],
            last_update=row['last_update'],
        )

    def get_stored_screen_set(self, screen_id: int) -> StoredScreenSet | None:
        self._execute(
            'SELECT * FROM `screen_set` WHERE `id` = ?',
            (screen_id,),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_screen_set(row)
        return None

    def get_stored_screen_next_set_order(self, screen_id: int) -> int:
        self._execute(
            'SELECT MAX(`order`) AS order_max FROM `screen_set` WHERE `screen_id` = ?',
            (screen_id, ),
        )
        row: dict[str, Any] = self._fetchone()
        return (row['order_max'] if row['order_max'] else 0) + 1

    def load_stored_screen_sets(self, screen_id: int) -> list[StoredScreenSet]:
        self._execute(
            'SELECT * FROM `screen_set` WHERE `screen_id` = ? ORDER BY `order`',
            (screen_id, ),
        )
        return [self._row_to_stored_screen_set(row) for row in self._fetchall()]

    def reorder_stored_screen_sets(
            self, screen_id: int, screen_set_ids: list[int],
    ):
        order: int = 1
        for screen_set_id in screen_set_ids:
            self._execute(
                f'UPDATE `screen_set` SET `order` = ?, `last_update` = ? WHERE `id` = ?',
                (order, time.time(), screen_set_id, ),
            )
            order += 1
        self._set_stored_screen_last_update(screen_id)
        self.set_last_update()

    def _write_stored_screen_set(
        self, stored_screen_set: StoredScreenSet,
    ) -> StoredScreenSet:
        fields: list[str] = [
            'screen_id', 'tournament_id', 'name', 'order', 'fixed_boards_str', 'first', 'last', 'last_update',
        ]
        params: list = [
            stored_screen_set.screen_id, stored_screen_set.tournament_id, stored_screen_set.name,
            stored_screen_set.order, stored_screen_set.fixed_boards_str, stored_screen_set.first,
            stored_screen_set.last, time.time(),
        ]
        if stored_screen_set.id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `screen_set`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            stored_screen_set = self.get_stored_screen_set(screen_id=self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_screen_set.id]
            self._execute(
                f'UPDATE `screen_set` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            stored_screen_set = self.get_stored_screen_set(screen_id=stored_screen_set.id)
        self.set_last_update()
        return stored_screen_set

    def clone_stored_screen_set(
            self, screen_set_id: int, screen_id: int,
    ) -> StoredScreenSet:
        stored_screen_set = self.get_stored_screen_set(screen_set_id)
        stored_screen_set.id = None
        stored_screen_set.screen_id = screen_id
        stored_screen_set.last_update = time.time()
        stored_screen_set.order = self.get_stored_screen_next_set_order(stored_screen_set.screen_id)
        new_stored_screen_set: StoredScreenSet = self._write_stored_screen_set(stored_screen_set)
        return new_stored_screen_set

    def add_stored_screen_set(
            self, screen_id: int,
            tournament_id: int,
    ) -> StoredScreenSet:
        stored_screen_set: StoredScreenSet = StoredScreenSet(
            id=None,
            screen_id=screen_id,
            tournament_id=tournament_id,
            order=self.get_stored_screen_next_set_order(screen_id),
            name=None,
            fixed_boards_str=None,
            first=None,
            last=None,
        )
        return self._write_stored_screen_set(stored_screen_set)

    def update_stored_screen_set(
        self, stored_screen_set: StoredScreenSet,
    ) -> StoredScreenSet:
        assert stored_screen_set.id is not None
        return self._write_stored_screen_set(stored_screen_set)

    def delete_stored_screen_set(self, screen_set_id: int, screen_id: int):
        order: int = 1
        for stored_screen_set in self.load_stored_screen_sets(screen_id):
            self._execute(
                f'UPDATE `screen_set` SET `order` = ?, `last_update` = ? WHERE `id` = ?',
                (order, time.time(), stored_screen_set.id, ),
            )
            order += 1
        self._set_stored_screen_last_update(screen_id)
        self._execute('DELETE FROM `screen_set` WHERE `id` = ?;', (screen_set_id,))
        self.set_last_update()

    """ 
    ---------------------------------------------------------------------------------
    StoredRotator 
    ---------------------------------------------------------------------------------
    """

    @classmethod
    def _row_to_stored_rotator(cls, row: dict[str, Any]) -> StoredRotator:
        return StoredRotator(
            id=row['id'],
            uniq_id=row['uniq_id'],
            public=cls.load_bool_from_database_field(row['public']),
            delay=row['delay'],
            show_menus=cls.load_bool_from_database_field(row['show_menus']),
            screen_ids=cls.load_json_from_database_field(row['screen_ids']),
            family_ids=cls.load_json_from_database_field(row['family_ids']),
        )

    def get_stored_rotator(self, rotator_id: int) -> StoredRotator | None:
        self._execute(
            'SELECT * FROM `rotator` WHERE `id` = ?',
            (rotator_id,),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_rotator(row)
        return None

    def load_stored_rotators(self) -> list[StoredRotator]:
        self._execute(
            'SELECT * FROM `rotator` ORDER BY `uniq_id`',
            (),
        )
        return [self._row_to_stored_rotator(row) for row in self._fetchall()]

    def _write_stored_rotator(
            self, stored_rotator: StoredRotator,
    ) -> StoredRotator:
        fields: list[str] = ['uniq_id', 'public', 'delay', 'show_menus', 'screen_ids', 'family_ids', ]
        params: list = [
            stored_rotator.uniq_id, stored_rotator.public, stored_rotator.delay, stored_rotator.show_menus,
            self.dump_to_json_database_field(stored_rotator.screen_ids, []),
            self.dump_to_json_database_field(stored_rotator.family_ids, []),
        ]
        if stored_rotator.id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `rotator`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            stored_rotator = self.get_stored_rotator(rotator_id=self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_rotator.id]
            self._execute(
                f'UPDATE `rotator` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            stored_rotator = self.get_stored_rotator(stored_rotator.id)
        self.set_last_update()
        return stored_rotator

    def add_stored_rotator(
            self, stored_rotator: StoredRotator,
    ) -> StoredRotator:
        assert stored_rotator.id is None
        return self._write_stored_rotator(stored_rotator)

    def update_stored_rotator(
            self, stored_rotator: StoredRotator,
    ) -> StoredRotator:
        assert stored_rotator.id is not None
        return self._write_stored_rotator(stored_rotator)

    def delete_stored_rotator(self, rotator_id: int):
        self._execute('DELETE FROM `rotator` WHERE `id` = ?;', (rotator_id,))
        self.set_last_update()

    def clone_stored_rotator(
            self, rotator_id: int,
    ) -> StoredRotator:
        stored_rotator = self.get_stored_rotator(rotator_id)
        stored_rotator.id = None
        self._execute(
            'SELECT uniq_id FROM `rotator`',
            (),
        )
        uniq_ids: list[str] = [row['uniq_id'] for row in self._fetchall()]
        uniq_id: str = f'{stored_rotator.uniq_id}-clone'
        clone_index: int = 1
        stored_rotator.uniq_id = uniq_id
        while stored_rotator.uniq_id in uniq_ids:
            clone_index += 1
            stored_rotator.uniq_id = f'{uniq_id}{clone_index}'
        return self._write_stored_rotator(stored_rotator)

"""A database schema based on sqlite3.

At this time, this database stores results and illegal moves. """
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

from common.exception import PapiWebException
from data.util import Result as UtilResult
from data.result import Result as DataResult
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.board import Board
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
    def json_to_dict_with_int_keys(json_string: str):
        # This method is needed because JSON turns all keys to strings
        return {int(k): v for k, v in json.loads(json_string).items()}


class EventDatabase(SQLiteDatabase):
    def __init__(self, uniq_id: str, write: bool = False):
        self.uniq_id = uniq_id
        self._version: Version | None = None
        super().__init__(PapiWebConfig().db_path / f'{self.uniq_id}.{PapiWebConfig().db_ext}', write)

    def exists(self) -> bool:
        return self.file.exists()

    def create(self, populate: bool = False):
        if self.exists():
            raise PapiWebException(
                f'La base de données ne peut être créée car le fichier [{self.file.resolve()}] existe déjà.')
        papi_web_config: PapiWebConfig = PapiWebConfig()
        papi_web_config.db_path.mkdir(parents=True, exist_ok=True)
        database: Connection | None = None
        cursor: Cursor | None = None
        try:
            database = connect(database=self.file, detect_types=1, uri=True)
            cursor = database.cursor()
            with open(papi_web_config.database_sql_path / 'create_event.sql', encoding='utf-8') as f:
                papi_web_version: Version = papi_web_config.version
                cursor.executescript(f.read().format(
                    version=f'{papi_web_version.major}.{papi_web_version.minor}.{papi_web_version.micro}'))
            database.commit()
            logger.info('La base de données [%s] a été créée', self.file)
            if populate:
                with EventDatabase(self.uniq_id, write=True) as event_database:
                    event_dict = yaml.safe_load(
                        (papi_web_config.database_yml_path / f'{self.uniq_id}.yml').read_text(encoding='utf-8'))
                    event_database.update_stored_event(StoredEvent(
                        uniq_id=self.uniq_id,
                        name=event_dict['name'],
                        path=None,
                        css=event_dict['css'],
                        update_password=event_dict['update_password'],
                        record_illegal_moves=event_dict['record_illegal_moves'],
                        allow_results_deletion=event_dict['allow_results_deletion'],
                    ))
                    chessevent_ids_by_uniq_id: dict[str, int] = {}
                    for chessevent_uniq_id, chessevent_dict in event_dict['chessevents'].items():
                        stored_chessevent: StoredChessEvent = event_database.add_stored_chessevent(StoredChessEvent(
                            id=None,
                            uniq_id=chessevent_uniq_id,
                            user_id=chessevent_dict['user_id'],
                            password=chessevent_dict['password'],
                            event_id=chessevent_dict['event_id'],
                        ))
                        chessevent_ids_by_uniq_id[chessevent_uniq_id] = stored_chessevent.id
                    timer_ids_by_uniq_id: dict[str, int] = {}
                    for timer_uniq_id, timer_dict in event_dict['timers'].items():
                        stored_timer: StoredTimer = event_database.add_stored_timer(StoredTimer(
                            id=None,
                            uniq_id=timer_uniq_id,
                            colors={i: None for i in range(1, 4)},
                            delays={i: None for i in range(1, 4)},
                        ))
                        timer_ids_by_uniq_id[timer_uniq_id] = stored_timer.id
                        for timer_hour_uniq_id, timer_hour_dict in timer_dict['hours'].items():
                            stored_timer_hour: StoredTimerHour = event_database.add_stored_timer_hour(stored_timer.id)
                            stored_timer_hour.uniq_id = timer_hour_uniq_id
                            stored_timer_hour.date_str = timer_hour_dict.get('date_str', None)
                            stored_timer_hour.time_str = timer_hour_dict['time_str']
                            with suppress(KeyError):
                                stored_timer_hour.text_before = timer_hour_dict.get('text_before', None)
                            with suppress(KeyError):
                                stored_timer_hour.text_after = timer_hour_dict.get('text_after', None)
                            event_database.update_stored_timer_hour(stored_timer_hour)
                    tournament_ids_by_uniq_id: dict[str, int] = {}
                    for tournament_uniq_id, tournament_dict in event_dict['tournaments'].items():
                        chessevent_uniq_id: str = tournament_dict.get('chessevent_uniq_id', None)
                        chessevent_id: int = chessevent_ids_by_uniq_id[
                            chessevent_uniq_id] if chessevent_uniq_id else None
                        stored_tournament: StoredTournament = event_database.add_stored_tournament(StoredTournament(
                            id=None,
                            uniq_id=tournament_uniq_id,
                            path=None,
                            filename=tournament_dict["filename"],
                            name=tournament_dict["name"],
                            ffe_id=tournament_dict["ffe_id"],
                            ffe_password=tournament_dict["ffe_password"],
                            time_control_initial_time=None,
                            time_control_increment=None,
                            time_control_handicap_penalty_value=None,
                            time_control_handicap_penalty_step=None,
                            time_control_handicap_min_time=None,
                            chessevent_id=chessevent_id,
                            chessevent_tournament_name=tournament_dict.get("chessevent_tournament_name", None),
                            record_illegal_moves=None,
                        ))
                        tournament_ids_by_uniq_id[tournament_uniq_id] = stored_tournament.id
                    screen_ids_by_uniq_id: dict[str, int] = {}
                    for screen_uniq_id, screen_dict in event_dict['screens'].items():
                        timer_uniq_id: str | None = screen_dict.get('timer_uniq_id', None)
                        timer_id: int = timer_ids_by_uniq_id[timer_uniq_id] if timer_uniq_id else None
                        type = screen_dict.get('type', None)
                        boards_update: bool | None = None
                        players_show_unpaired: bool | None = None
                        results_limit: int | None = None
                        results_tournament_ids: list[int] | None = None
                        match type:
                            case 'boards':
                                boards_update = screen_dict.get('boards_update', False)
                            case 'players':
                                players_show_unpaired = screen_dict.get('players_show_unpaired', False)
                            case 'results':
                                results_limit: list[str] = screen_dict.get('results_limit', None)
                                results_tournament_uniq_ids: list[str] = screen_dict.get(
                                    'results_tournament_uniq_ids', None)
                                results_tournament_ids = [
                                    tournament_ids_by_uniq_id[tournament_uniq_id]
                                    for tournament_uniq_id in results_tournament_uniq_ids
                                ] if results_tournament_uniq_ids else []
                            case _:
                                raise ValueError
                        stored_screen: StoredScreen = event_database.add_stored_screen(StoredScreen(
                            id=None,
                            uniq_id=screen_uniq_id,
                            name=screen_dict.get('name', None),
                            type=type,
                            columns=screen_dict.get('columns', None),
                            menu_text=screen_dict.get('menu_text', None),
                            menu=screen_dict.get('menu', None),
                            timer_id=timer_id,
                            boards_update=boards_update,
                            players_show_unpaired=players_show_unpaired,
                            results_limit=results_limit,
                            results_tournament_ids=results_tournament_ids,
                        ))
                        screen_ids_by_uniq_id[screen_uniq_id] = stored_screen.id
                        if 'sets' in screen_dict:
                            for screen_set_dict in screen_dict['sets']:
                                tournament_uniq_id: str = screen_set_dict.get('tournament_uniq_id', None)
                                tournament_id: int = tournament_ids_by_uniq_id[
                                    tournament_uniq_id] if tournament_uniq_id else None
                                stored_screen_set: StoredScreenSet = event_database.add_stored_screen_set(
                                    stored_screen.id)
                                stored_screen_set.tournament_id = tournament_id
                                stored_screen_set.name = screen_set_dict.get('name', None)
                                stored_screen_set.fixed_boards_str = screen_set_dict.get('fixed_boards_str', None)
                                stored_screen_set.first = screen_set_dict.get('first', None)
                                stored_screen_set.last = screen_set_dict.get('last', None)
                                stored_screen_set.part = screen_set_dict.get('part', None)
                                stored_screen_set.parts = screen_set_dict.get('parts', None)
                                stored_screen_set.number = screen_set_dict.get('number', None)
                                event_database.update_stored_screen_set(stored_screen_set)
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
        arch: Path = Path(file.parent, f'{file.stem}_{datetime.now().strftime("%Y%m%d%H%M")}.arch')
        file.rename(arch)
        return arch

    def rename(self, new_uniq_id: str = None):
        self.file.rename(EventDatabase(new_uniq_id).file)

    def clone(self, new_uniq_id: str):
        shutil.copy(self.file, EventDatabase(new_uniq_id).file)

    def __enter__(self) -> Self:
        if not self.exists():
            raise PapiWebException(
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
            path=row['path'],
            css=row['css'],
            update_password=row['update_password'],
            record_illegal_moves=row['record_illegal_moves'],
            allow_results_deletion=row['allow_results_deletion'],
            timer_colors=self.json_to_dict_with_int_keys(row['timer_colors'])
            if row['timer_colors'] else {i: None for i in range(1, 4)},
            timer_delays=self.json_to_dict_with_int_keys(row['timer_delays'])
            if row['timer_delays'] else {i: None for i in range(1, 4)},
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
        self._execute('UPDATE `info` SET `version` = ?', (f'{version.major}.{version.minor}.{version.micro}', ))
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
            'name', 'path', 'css', 'update_password', 'record_illegal_moves', 'allow_results_deletion',
            'timer_colors', 'timer_delays',
        ]
        params: list = [
            stored_event.name, stored_event.path, stored_event.css, stored_event.update_password,
            stored_event.record_illegal_moves, stored_event.allow_results_deletion,
            json.dumps(stored_event.timer_colors), json.dumps(stored_event.timer_delays),
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

    def get_stored_chessevent(self, id: int) -> StoredChessEvent | None:
        self._execute(
            'SELECT * FROM `chessevent` WHERE `id` = ?',
            (id, ),
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
            return self.get_stored_chessevent(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_chessevent.id]
            self._execute(
                f'UPDATE `chessevent` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_chessevent(stored_chessevent.id)

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

    def delete_stored_chessevent(self, id: int):
        self._execute('DELETE FROM `chessevent` WHERE `id` = ?;', (id, ))

    def clone_stored_chessevent(
            self, id: int,
    ) -> StoredChessEvent:
        stored_chessevent = self.get_stored_chessevent(id)
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

    def get_stored_timer_hour(self, id: int) -> StoredTimerHour | None:
        self._execute(
            'SELECT * FROM `timer_hour` WHERE `id` = ?',
            (id, ),
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
            return self.get_stored_timer_hour(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_timer_hour.id]
            self._execute(
                f'UPDATE `timer_hour` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_timer_hour(stored_timer_hour.id)

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

    def order_stored_timer_hours(
            self, timer_id: int,
    ):
        order: int = 1
        for stored_timer_hour in self.load_stored_timer_hours(timer_id):
            self._execute(
                f'UPDATE `timer_hour` SET `order` = ? WHERE `id` = ?',
                (order, stored_timer_hour.id, ),
            )
            order += 1

    def update_stored_timer_hour(
            self, stored_timer_hour: StoredTimerHour,
    ) -> StoredTimerHour:
        assert stored_timer_hour.id is not None
        return self._write_stored_timer_hour(stored_timer_hour)

    def add_stored_timer_hour(
            self, timer_id: int,
    ) -> StoredTimerHour:
        stored_timer_hour: StoredTimerHour = StoredTimerHour(
            id=None,
            timer_id=timer_id,
            uniq_id=str(self.get_stored_timer_next_round(timer_id)),
            order=self.get_stored_timer_next_hour_order(timer_id),
        )
        return self._write_stored_timer_hour(stored_timer_hour)

    def clone_stored_timer_hour(self, id: int, timer_id: int | None = None):
        stored_timer_hour = self.get_stored_timer_hour(id)
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

    def delete_stored_timer_hour(self, id: int):
        self._execute('DELETE FROM `timer_hour` WHERE `id` = ?;', (id, ))

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
            colors=cls.json_to_dict_with_int_keys(row['colors']) if row['colors'] else {i: None for i in range(1, 4)},
            delays=cls.json_to_dict_with_int_keys(row['delays']) if row['delays'] else {i: None for i in range(1, 4)},
        )

    def get_stored_timer(self, id: int) -> StoredTimer | None:
        self._execute(
            'SELECT * FROM `timer` WHERE `id` = ?',
            (id, ),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_timer(row)
        return None

    def load_stored_timer(self, id: int) -> StoredTimer:
        stored_timer: StoredTimer
        if stored_timer := self.get_stored_timer(id):
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
            json.dumps(stored_timer.colors),
            json.dumps(stored_timer.delays),
        ]
        if stored_timer.id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `timer`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_timer(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_timer.id]
            self._execute(
                f'UPDATE `timer` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_timer(stored_timer.id)

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
            self, id: int, new_uniq_id: str,
    ) -> StoredTimer:
        stored_timer = self.load_stored_timer(id)
        stored_timer.id = None
        stored_timer.uniq_id = new_uniq_id
        new_stored_timer: StoredTimer = self._write_stored_timer(stored_timer)
        for stored_timer_hour in stored_timer.stored_timer_hours:
            new_stored_timer.stored_timer_hours.append(
                self.clone_stored_timer_hour(stored_timer_hour.id, new_stored_timer.id))
        return new_stored_timer

    def delete_stored_timer(self, id: int):
        self._execute('UPDATE `family` SET `timer_id` = NULL WHERE `timer_id` = ?;', (id, ))
        self._execute('UPDATE `screen` SET `timer_id` = NULL WHERE `timer_id` = ?;', (id, ))
        self._execute('DELETE FROM `timer` WHERE id = ?;', (id, ))

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
            last_result_update=row['last_result_update'],
            last_illegal_move_update=row['last_illegal_move_update'],
            last_ffe_upload=row['last_ffe_upload'],
            last_chessevent_download=row['last_chessevent_download'],
        )

    def get_stored_tournament(self, id: int) -> StoredTournament | None:
        self._execute(
            'SELECT * FROM `tournament` WHERE `id` = ?',
            (id, ),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_tournament(row)
        return None

    def get_stored_tournament_with_uniq_id(self, uniq_id: str) -> StoredTournament | None:
        # TODO Remove this method
        self._execute(
            'SELECT * FROM `tournament` WHERE `uniq_id` = ?',
            (uniq_id,),
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
            'chessevent_tournament_name', 'record_illegal_moves', 'last_result_update', 'last_illegal_move_update',
            'last_ffe_upload', 'last_chessevent_download',
        ]
        params: list = [
            stored_tournament.uniq_id, stored_tournament.name, stored_tournament.path, stored_tournament.filename,
            stored_tournament.ffe_id, stored_tournament.ffe_password, stored_tournament.time_control_initial_time,
            stored_tournament.time_control_increment, stored_tournament.time_control_handicap_penalty_step,
            stored_tournament.time_control_handicap_penalty_value, stored_tournament.time_control_handicap_min_time,
            stored_tournament.chessevent_id, stored_tournament.chessevent_tournament_name,
            stored_tournament.record_illegal_moves, stored_tournament.last_result_update,
            stored_tournament.last_illegal_move_update, stored_tournament.last_ffe_upload,
            stored_tournament.last_chessevent_download,
        ]
        if stored_tournament.id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `tournament`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_tournament(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_tournament.id]
            self._execute(
                f'UPDATE `tournament` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_tournament(stored_tournament.id)

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

    def delete_stored_tournament(self, id: int):
        self._execute('UPDATE `family` SET `tournament_id` = NULL WHERE `tournament_id` = ?;', (id, ))
        self._execute('UPDATE `screen_set` SET `tournament_id` = NULL WHERE `tournament_id` = ?;', (id, ))
        self._execute('DELETE FROM `tournament` WHERE `id` = ?;', (id, ))
        # other references are deleted on cascade

    def clone_stored_tournament(
            self, id: int, new_uniq_id: str, new_name: str, new_path: str | None, new_filename: str | None,
            new_ffe_id: int | None, new_ffe_password: str | None,
    ) -> StoredTournament:
        stored_tournament = self.get_stored_tournament(id)
        stored_tournament.id = None
        stored_tournament.uniq_id = new_uniq_id
        stored_tournament.name = new_name
        stored_tournament.path = new_path
        stored_tournament.filename = new_filename
        stored_tournament.ffe_id = new_ffe_id
        stored_tournament.ffe_password = new_ffe_password
        stored_tournament.last_result_update = 0.0
        stored_tournament.last_illegal_move_update = 0.0
        stored_tournament.last_ffe_upload = 0.0
        stored_tournament.last_chessevent_download = 0.0
        return self._write_stored_tournament(stored_tournament)

    def set_tournament_last_ffe_upload(self, tournament_id: int, timestamp: float):
        self._execute(
            f'UPDATE `tournament` SET `last_ffe_upload` = ? WHERE `id` = ?',
            (tournament_id, timestamp if timestamp else time.time()))

    def set_tournament_last_chessevent_download(self, tournament_id: int, timestamp: float = None):
        self._execute(
            f'UPDATE `tournament` SET `last_chessevent_download` = ? WHERE `id` = ?',
            (tournament_id, timestamp if timestamp else time.time()))

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

    def _get_stored_illegal_move(self, id: int, ) -> StoredIllegalMove | None:
        self._execute(
            'SELECT * FROM `illegal_move` WHERE `id` = ?',
            (id, ),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_illegal_move(row)
        return None

    def _set_tournament_last_illegal_move_update(self, tournament_id: int) -> StoredTournament:
        stored_tournament: StoredTournament = self.get_stored_tournament(tournament_id)
        if not stored_tournament:
            raise PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
        self._execute(
            'UPDATE `tournament` SET `last_illegal_move_update` = ? WHERE `id` = ?',
            (time.time(), stored_tournament.id, ),
        )
        return self.get_stored_tournament(stored_tournament.id)

    def get_illegal_moves(self, tournament_id: int, round: int) -> Counter[int]:
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

    def get_illegal_moves_with_tournament_uniq_id(self, tournament_uniq_id: str, round: int) -> Counter[int]:
        # TODO Remove this method
        stored_tournament: StoredTournament = self.get_stored_tournament_with_uniq_id(tournament_uniq_id)
        return self.get_illegal_moves(stored_tournament.id, round) if stored_tournament else Counter[int]()

    def add_illegal_move(self, tournament_id: int, round: int, player_id: int) -> StoredIllegalMove:
        stored_tournament: StoredTournament = self._set_tournament_last_illegal_move_update(tournament_id)
        if not stored_tournament:
            raise PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
        fields: list[str] = ['tournament_id', 'round', 'player_id', 'date', ]
        params: list = [stored_tournament.id, round, player_id, time.time()]
        protected_fields = [f"`{f}`" for f in fields]
        self._execute(
            f'INSERT INTO `illegal_move`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
            tuple(params))
        return self._get_stored_illegal_move(self._last_inserted_id())

    def add_illegal_move_with_tournament_uniq_id(
            self, tournament_uniq_id: str, round: int, player_id: int
    ) -> StoredIllegalMove:
        # TODO Remove this method
        stored_tournament: StoredTournament = self.get_stored_tournament_with_uniq_id(tournament_uniq_id)
        if not stored_tournament:
            raise PapiWebException(f'Le tournoi [{tournament_uniq_id}] est introuvable.')
        return self.add_illegal_move(stored_tournament.id, round, player_id)

    def delete_illegal_move(self, tournament_id: int, round: int, player_id: int) -> bool:
        stored_tournament: StoredTournament = self._set_tournament_last_illegal_move_update(tournament_id)
        if not stored_tournament:
            PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
        self._execute(
            'SELECT `id` FROM `illegal_move` WHERE `tournament_id` = ? AND `round` = ? AND `player_id` = ? LIMIT 1',
            (stored_tournament.id, round, player_id, ),
        )
        row: dict[str, Any] = self._fetchone()
        if not row:
            return False
        self._execute(
            'DELETE FROM `illegal_move` WHERE `id` = ?',
            (row['id'], ),
        )
        return True

    def delete_illegal_move_with_tournament_uniq_id(self, tournament_uniq_id: str, round: int, player_id: int) -> bool:
        # TODO Remove this method
        stored_tournament: StoredTournament = self.get_stored_tournament_with_uniq_id(tournament_uniq_id)
        if not stored_tournament:
            raise PapiWebException(f'Le tournoi [{tournament_uniq_id}] est introuvable.')
        return self.delete_illegal_move(stored_tournament.id, round, player_id)

    def delete_illegal_moves(self, tournament_id: int, round: int):
        stored_tournament: StoredTournament = self._set_tournament_last_illegal_move_update(tournament_id)
        if not stored_tournament:
            raise PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
        self._execute(
            'DELETE FROM `illegal_move` WHERE `tournament_id` = ? AND `round` = ?',
            (stored_tournament.id, round,),
        )

    def delete_illegal_moves_with_tournament_uniq_id(self, tournament_uniq_id: str, round: int):
        # TODO Remove this method
        stored_tournament: StoredTournament = self.get_stored_tournament_with_uniq_id(tournament_uniq_id)
        if not stored_tournament:
            raise PapiWebException(f'Le tournoi [{tournament_uniq_id}] est introuvable.')
        return self.delete_illegal_moves(stored_tournament.id, round)

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
            self, id: int,
    ) -> StoredResult | None:
        self._execute(
            'SELECT * FROM `result` WHERE `id` = ?',
            (id, ),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_result(row)
        return None

    def _set_tournament_last_result_update(self, tournament_id: int) -> StoredTournament:
        stored_tournament: StoredTournament = self.get_stored_tournament(tournament_id)
        if not stored_tournament:
            raise PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
        self._execute(
            'UPDATE `tournament` SET `last_result_update` = ? WHERE `id` = ?',
            (time.time(), stored_tournament.id, ),
        )
        return stored_tournament

    def add_result(self, tournament_id: int, round: int, board: Board, result: UtilResult):
        stored_tournament: StoredTournament = self._set_tournament_last_result_update(tournament_id)
        if not stored_tournament:
            PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
        self._execute(
            'INSERT INTO `result`('
            '    `tournament_id`, `round`, `board_id`, '
            '    `white_player_id`, `black_player_id`, '
            '    `value`, `date`'
            ') VALUES(?, ?, ?, ?, ?, ?, ?)',
            (
                stored_tournament.id,
                round,
                board.id,
                board.white_player.id,
                board.black_player.id,
                result,
                time.time(),
            ),
        )

    def add_result_with_tournament_uniq_id(self, tournament_uniq_id: str, round: int, board: Board, result: UtilResult):
        # TODO Remove this method
        stored_tournament: StoredTournament = self.get_stored_tournament_with_uniq_id(tournament_uniq_id)
        if not stored_tournament:
            PapiWebException(f'Le tournoi [{tournament_uniq_id}] est introuvable.')
        return self.add_result(stored_tournament.id, round, board, result)

    def delete_result(self, tournament_id: int, round: int, board_id: int):
        stored_tournament: StoredTournament = self._set_tournament_last_result_update(tournament_id)
        if not stored_tournament:
            raise PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
        self._execute(
            'DELETE FROM `result` WHERE `tournament_id` = ? AND `round` = ? AND `board_id` = ?',
            (stored_tournament.id, round, board_id),
        )

    def delete_result_with_tournament_uniq_id(self, tournament_uniq_id: str, round: int, board_id: int):
        # TODO Remove this method
        stored_tournament: StoredTournament = self.get_stored_tournament_with_uniq_id(tournament_uniq_id)
        if not stored_tournament:
            raise PapiWebException(f'Le tournoi [{tournament_uniq_id}] est introuvable.')
        return self.delete_result(stored_tournament.id, round, board_id)

    def get_results(self, limit: int, tournament_ids: list[int]) -> Iterator[DataResult]:
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
        for row in self._fetchall():
            try:
                value: UtilResult = UtilResult.from_papi_value(int(row['value']))
            except ValueError:
                logger.warning('invalid result [%s] found in database', row['value'])
                continue
            yield DataResult(
                    row['date'],
                    row['tournament_uniq_id'],
                    row['round'],
                    row['board_id'],
                    row['white_player_id'],
                    row['black_player_id'],
                    value)

    """ 
    ---------------------------------------------------------------------------------
    StoredFamily 
    ---------------------------------------------------------------------------------
    """

    @staticmethod
    def _row_to_stored_family(row: dict[str, Any]) -> StoredFamily:
        return StoredFamily(
            id=row['id'],
            uniq_id=row['uniq_id'],
            name=row['name'],
            type=row['type'],
            tournament_id=row['tournament_id'],
            boards_update=row['boards_update'],
            players_show_unpaired=row['players_show_unpaired'],
            columns=row['columns'],
            menu_text=row['menu_text'],
            menu=row['menu'],
            timer_id=row['timer_id'],
            first=row['first'],
            last=row['last'],
            parts=row['parts'],
            number=row['number'],
        )

    def get_stored_family(self, id: int) -> StoredFamily | None:
        self._execute(
            'SELECT * FROM `family` WHERE `id` = ?',
            (id, ),
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
            'uniq_id', 'name', 'type', 'tournament_id', 'columns', 'menu_text', 'menu', 'timer_id', 'boards_update',
            'players_show_unpaired', 'first', 'last', 'parts', 'number',
        ]
        params: list = [
            stored_family.uniq_id, stored_family.name, stored_family.type, stored_family.tournament_id,
            stored_family.columns, stored_family.menu_text, stored_family.menu, stored_family.timer_id,
            stored_family.boards_update, stored_family.players_show_unpaired, stored_family.first, stored_family.last,
            stored_family.parts, stored_family.number,
        ]
        if stored_family.id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `family`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_family(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_family.id]
            self._execute(
                f'UPDATE `family` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_family(stored_family.id)

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

    def delete_stored_family(self, id: int):
        self._execute('DELETE FROM `family` WHERE `id` = ?;', (id, ))

    """ 
    ---------------------------------------------------------------------------------
    StoredScreen 
    ---------------------------------------------------------------------------------
    """

    @staticmethod
    def _row_to_stored_screen(row: dict[str, Any]) -> StoredScreen:
        return StoredScreen(
            id=row['id'],
            uniq_id=row['uniq_id'],
            name=row['name'],
            type=row['type'],
            columns=row['columns'],
            menu_text=row['menu_text'],
            menu=row['menu'],
            timer_id=row['timer_id'],
            boards_update=row['boards_update'],
            players_show_unpaired=row['players_show_unpaired'],
            results_limit=row['results_limit'],
            results_tournament_ids=json.loads(row['results_tournament_ids'])
            if row['results_tournament_ids'] is not None else None,
        )

    def get_stored_screen(self, id: int) -> StoredScreen | None:
        self._execute(
            'SELECT * FROM `screen` WHERE `id` = ?',
            (id, ),
        )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_screen(row)
        return None

    def load_stored_screen(self, id: int) -> StoredScreen:
        stored_screen: StoredScreen
        if stored_screen := self.get_stored_screen(id):
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

    def _write_stored_screen(
            self, stored_screen: StoredScreen,
    ) -> StoredScreen:
        fields: list[str] = [
            'uniq_id', 'name', 'type', 'boards_update', 'players_show_unpaired', 'columns', 'menu_text', 'menu',
            'timer_id', 'results_limit', 'results_tournament_ids',
        ]
        params: list = [
            stored_screen.uniq_id, stored_screen.name, stored_screen.type, stored_screen.boards_update,
            stored_screen.players_show_unpaired, stored_screen.columns, stored_screen.menu_text,
            stored_screen.menu, stored_screen.timer_id, stored_screen.results_limit,
            json.dumps(stored_screen.results_tournament_ids)
            if stored_screen.results_tournament_ids is not None else None,
        ]
        if stored_screen.id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `screen`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_screen(id=self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_screen.id]
            self._execute(
                f'UPDATE `screen` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_screen(id=stored_screen.id)

    def clone_stored_screen(
            self, id: int, new_uniq_id: str, new_name: str,
    ) -> StoredScreen:
        stored_screen = self.load_stored_screen(id)
        stored_screen.id = None
        stored_screen.uniq_id = new_uniq_id
        stored_screen.name = new_name
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

    def delete_stored_screen(self, id: int):
        self._execute('DELETE FROM `screen` WHERE `id` = ?;', (id, ))

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
            first=row['first'],
            fixed_boards_str=row['fixed_boards_str'],
            last=row['last'],
        )

    def get_stored_screen_set(self, id: int) -> StoredScreenSet | None:
        self._execute(
            'SELECT * FROM `screen_set` WHERE `id` = ?',
            (id, ),
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
            self, screen_set_ids: list[int],
    ):
        order: int = 1
        for screen_set_id in screen_set_ids:
            self._execute(
                f'UPDATE `screen_set` SET `order` = ? WHERE `id` = ?',
                (order, screen_set_id, ),
            )
            order += 1

    def order_stored_screen_sets(
            self, screen_id: int,
    ):
        order: int = 1
        for stored_screen_set in self.load_stored_screen_sets(screen_id):
            self._execute(
                f'UPDATE `screen_set` SET `order` = ? WHERE `id` = ?',
                (order, stored_screen_set.id, ),
            )
            order += 1

    def _write_stored_screen_set(
        self, stored_screen_set: StoredScreenSet,
    ) -> StoredScreenSet:
        fields: list[str] = [
            'screen_id', 'tournament_id', 'name', 'order', 'fixed_boards_str', 'first', 'last',
        ]
        params: list = [
            stored_screen_set.screen_id, stored_screen_set.tournament_id, stored_screen_set.name,
            stored_screen_set.order, stored_screen_set.fixed_boards_str, stored_screen_set.first,
            stored_screen_set.last,
        ]
        if stored_screen_set.id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `screen_set`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_screen_set(id=self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [stored_screen_set.id]
            self._execute(
                f'UPDATE `screen_set` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_screen_set(id=stored_screen_set.id)

    def clone_stored_screen_set(
            self, id: int, screen_id: int,
    ) -> StoredScreenSet:
        stored_screen_set = self.get_stored_screen_set(id)
        stored_screen_set.id = None
        stored_screen_set.screen_id = screen_id
        stored_screen_set.order = self.get_stored_screen_next_set_order(stored_screen_set.screen_id)
        new_stored_screen_set: StoredScreenSet = self._write_stored_screen_set(stored_screen_set)
        return new_stored_screen_set

    def add_stored_screen_set(
            self, screen_id: int,
    ) -> StoredScreenSet:
        stored_screen_set: StoredScreenSet = StoredScreenSet(
            id=None,
            screen_id=screen_id,
            tournament_id=None,
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

    def delete_stored_screen_set(self, id: int):
        self._execute('DELETE FROM `screen_set` WHERE `id` = ?;', (id, ))

    """ 
    ---------------------------------------------------------------------------------
    StoredRotator 
    ---------------------------------------------------------------------------------
    """

    @staticmethod
    def _row_to_stored_rotator(row: dict[str, Any]) -> StoredRotator:
        return StoredRotator(
            id=row['id'],
            uniq_id=row['uniq_id'],
            screens_str=row['screens_str'],
            families_str=row['families_str'],
            delay=row['delay'],
        )

    def get_stored_rotator(self, id: int) -> StoredRotator | None:
        self._execute(
            'SELECT * FROM `rotator` WHERE `id` = ?',
            (id, ),
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
            self, id: int | None, uniq_id: str, screens_str: str, families_str: str, delay: int,
    ) -> StoredRotator:
        fields: list[str] = ['uniq_id', 'screens_str', 'families_str', 'delay', ]
        params: list = [uniq_id, screens_str, families_str, delay, ]
        if id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `rotator`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_rotator(id=self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [id]
            self._execute(
                f'UPDATE `rotator` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_rotator(id=id)

    def add_stored_rotator(
            self, uniq_id: str, screens_str: str, families_str: str, delay: int,
    ) -> StoredRotator:
        return self._write_stored_rotator(None, uniq_id, screens_str, families_str, delay)

    def update_stored_rotator(
            self, id: int, uniq_id: str, screens_str: str, families_str: str, delay: int,
    ) -> StoredRotator:
        return self._write_stored_rotator(id, uniq_id, screens_str, families_str, delay)

    def delete_stored_rotator(self, id: int):
        self._execute('DELETE FROM `rotator` WHERE `id` = ?;', (id, ))

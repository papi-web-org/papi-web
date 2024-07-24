"""A database schema based on sqlite3.

At this time, this database stores results and illegal moves. """
import shutil
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from logging import Logger
from pathlib import Path
from sqlite3 import Connection, Cursor, connect, OperationalError
from typing import Self, Any, Unpack

from packaging.version import Version

from common.exception import PapiWebException
from data.util import Result as UtilResult, ScreenType
from data.result import Result as DataResult
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.board import Board
from database.store import StoredTournament, StoredEvent, StoredChessEvent, StoredTimer, StoredTimerHour, \
    StoredFamily, StoredIllegalMove, StoredResult, StoredRotator, StoredScreenSet, StoredScreen

logger: Logger = get_logger()

SQL_PATH: Path = Path(__file__).resolve().parent / 'sql'


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


class EventDatabase(SQLiteDatabase):
    def __init__(self, uniq_id: str, write: bool = False):
        self.uniq_id = uniq_id
        self._version: Version | None = None
        super().__init__(PapiWebConfig().db_path / f'{self.uniq_id}.{PapiWebConfig().db_ext}', write)

    def exists(self) -> bool:
        return self.file.exists()

    def create(self):
        assert not self.exists(), PapiWebException(
                f'La base de données ne peut être créée car le fichier [{self.file.resolve()}] existe déjà.')
        PapiWebConfig().db_path.mkdir(parents=True, exist_ok=True)
        database: Connection | None = None
        cursor: Cursor | None = None
        try:
            database = connect(database=self.file, detect_types=1, uri=True)
            cursor = database.cursor()
            with open(SQL_PATH / 'create_event.sql', encoding='utf-8') as f:
                papi_web_version: Version = PapiWebConfig().version
                cursor.executescript(f.read().format(
                    version=f'{papi_web_version.major}.{papi_web_version.minor}.{papi_web_version.micro}'))
            database.commit()
            logger.info('La base de données [%s] a été créée', self.file)
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
        assert self.exists(), PapiWebException(
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
        ]
        params: list = [
            stored_event.name, stored_event.path, stored_event.css, stored_event.update_password,
            stored_event.record_illegal_moves, stored_event.allow_results_deletion,
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
        assert stored_chessevent.id is None, ValueError
        return self._write_stored_chessevent(stored_chessevent)

    def update_stored_chessevent(
            self, stored_chessevent: StoredChessEvent,
    ) -> StoredChessEvent:
        assert stored_chessevent.id is not None, ValueError
        return self._write_stored_chessevent(stored_chessevent)

    def delete_stored_chessevent(self, id: int):
        self._execute('DELETE FROM `chessevent` WHERE `id` = ?;', (id, ))

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
            timer_id=row['timer_id'],
            order=row['order'],
            date=row['date'],
            round=row['round'],
            event=row['event'],
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

    def load_stored_timer_hours(self, timer_id: int) -> list[StoredTimerHour]:
        self._execute(
            'SELECT * FROM `timer_hour` WHERE `timer_id` = ? ORDER BY `order`',
            (timer_id, ),
        )
        return [self._row_to_stored_timer_hour(row) for row in self._fetchall()]

    def _write_stored_timer_hour(
            self, id: int | None, timer_id: int, order: int, date: str, round: int, event: str,
            text_before: str, text_after: str
    ) -> StoredTimerHour:
        fields: list[str] = ['timer_id', 'order', 'date', 'round', 'event', 'text_before', 'text_after', ]
        params: list = [timer_id, order, date, round, event, text_before, text_after, ]
        if id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `timer_hour`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_timer_hour(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [id]
            self._execute(
                f'UPDATE `timer_hour` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_timer_hour(id)

    def add_stored_timer_hour(
            self, timer_id: int, order: int, date: str, round: int, event: str,
            text_before: str, text_after: str
    ) -> StoredTimerHour:
        return self._write_stored_timer_hour(None, timer_id, order, date, round, event, text_before, text_after)

    def update_stored_timer_hour(
            self, id: int, timer_id: int, order: int, date: str, round: int, event: str,
            text_before: str, text_after: str
    ) -> StoredTimerHour:
        return self._write_stored_timer_hour(id, timer_id, order, date, round, event, text_before, text_after)

    def delete_stored_timer_hour(self, id: int):
        self._execute('DELETE FROM `timer_hour` WHERE `id` = ?;', (id, ))

    """ 
    ---------------------------------------------------------------------------------
    StoredTimer
    ---------------------------------------------------------------------------------
    """

    @staticmethod
    def _row_to_stored_timer(row: dict[str, Any]) -> StoredTimer:
        return StoredTimer(
            id=row['id'],
            uniq_id=row['uniq_id'],
            delay_1=row['delay_1'],
            delay_2=row['delay_2'],
            delay_3=row['delay_3'],
            color_1=row['color_1'],
            color_2=row['color_2'],
            color_3=row['color_3'],
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

    def load_stored_timers(self) -> list[StoredTimer]:
        self._execute(
            'SELECT * FROM `timer` ORDER BY `uniq_id`',
            (),
        )
        stored_timers: list[StoredTimer] = [self._row_to_stored_timer(row) for row in self._fetchall()]
        for stored_timer in stored_timers:
            stored_timer.stored_timer_hours = self.load_stored_timer_hours(stored_timer.id)
        return stored_timers

    def _write_stored_timer(
            self, id: int | None, uniq_id: str,
            delay_1: int, delay_2: int, delay_3: int,
            color_1: str, color_2: str, color_3: str
    ) -> StoredTimer:
        fields: list[str] = ['uniq_id', 'delay_1', 'delay_2', 'delay_3', 'color_1', 'color_2', 'color_3', ]
        params: list = [uniq_id, delay_1, delay_2, delay_3, color_1, color_2, color_3]
        if id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `timer`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_timer(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [id]
            self._execute(
                f'UPDATE `timer` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_timer(id)

    def add_stored_timer(
            self, uniq_id: str,
            delay_1: int, delay_2: int, delay_3: int,
            color_1: str, color_2: str, color_3: str
    ) -> StoredTimer:
        return self._write_stored_timer(None, uniq_id, delay_1, delay_2, delay_3, color_1, color_2, color_3)

    def update_stored_timer(
            self, id: int, uniq_id: str,
            delay_1: int, delay_2: int, delay_3: int,
            color_1: str, color_2: str, color_3: str
    ) -> StoredTimer:
        return self._write_stored_timer(id, uniq_id, delay_1, delay_2, delay_3, color_1, color_2, color_3)

    def delete_stored_timer(self, id: int):
        self._execute('DELETE FROM `timer_hour` WHERE timer_id = ?;', (id, ))
        self._execute('DELETE FROM `timer` WHERE `id` = ?;', (id, ))

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
                handicap_initial_time=row['handicap_initial_time'],
                handicap_increment=row['handicap_increment'],
                handicap_penalty_step=row['handicap_penalty_step'],
                handicap_penalty_value=row['handicap_penalty_value'],
                handicap_min_time=row['handicap_min_time'],
                chessevent_id=row['chessevent_id'],
                chessevent_tournament_name=row['chessevent_tournament_name'],
                record_illegal_moves=row['record_illegal_moves'],
                rounds=row['rounds'],
                pairing=row['pairing'],
                rating=row['rating'],
                rating_limit_1=row['rating_limit_1'],
                rating_limit_2=row['rating_limit_2'],
                last_result_update=row['last_result_update'],
                last_illegal_move_update=row['last_illegal_move_update'],
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

    def _write_stored_tournament(
            self, id: int | None, uniq_id: str,
            name: str, path: str, filename: str, ffe_id: int, ffe_password: str,
            handicap_initial_time: int, handicap_increment: int, handicap_penalty_step: int,
            handicap_penalty_value: int, handicap_min_time: int,
            chessevent_id: str, chessevent_tournament_name: str,
            record_illegal_moves: bool, rounds: int, pairing: str, rating: str,
            rating_limit_1: int, rating_limit_2: int, last_result_update: float, last_illegal_move_update: float,
    ) -> StoredTournament:
        fields: list[str] = [
            'uniq_id', 'name', 'path', 'filename', 'ffe_id', 'ffe_password',
            'handicap_initial_time', 'handicap_increment', 'handicap_penalty_step',
            'handicap_penalty_value', 'handicap_min_time',
            'chessevent_id', 'chessevent_tournament_name', 'record_illegal_moves', 'rounds', 'pairing', 'rating',
            'rating_limit_1', 'rating_limit_2', 'last_result_update', 'last_illegal_move_update'
        ]
        params: list = [
            uniq_id, name, path, filename, ffe_id, ffe_password,
            handicap_initial_time, handicap_increment, handicap_penalty_step, handicap_penalty_value, handicap_min_time,
            chessevent_id, chessevent_tournament_name, record_illegal_moves, rounds, pairing, rating,
            rating_limit_1, rating_limit_2, last_result_update, last_illegal_move_update
        ]
        if id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `tournament`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_tournament(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [id]
            self._execute(
                f'UPDATE `tournament` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_tournament(id)

    def add_stored_tournament(
            self, uniq_id: str,
            name: str, path: str, filename: str, ffe_id: int, ffe_password: str,
            handicap_initial_time: int, handicap_increment: int, handicap_penalty_step: int,
            handicap_penalty_value: int, handicap_min_time: int,
            chessevent_id: str, chessevent_tournament_name: str,
            record_illegal_moves: bool, rounds: int, pairing: str, rating: str,
            rating_limit_1: int, rating_limit_2: int, last_result_update: float, last_illegal_move_update: float,
    ) -> StoredTournament:
        return self._write_stored_tournament(
            None, uniq_id, name, path, filename, ffe_id, ffe_password,
            handicap_initial_time, handicap_increment, handicap_penalty_step, handicap_penalty_value,
            handicap_min_time, chessevent_id, chessevent_tournament_name, record_illegal_moves, rounds, pairing,
            rating, rating_limit_1, rating_limit_2, last_result_update, last_illegal_move_update)

    def update_stored_tournament(
            self, id: int, uniq_id: str,
            name: str, path: str, filename: str, ffe_id: int, ffe_password: str,
            handicap_initial_time: int, handicap_increment: int, handicap_penalty_step: int,
            handicap_penalty_value: int, handicap_min_time: int,
            chessevent_id: str, chessevent_tournament_name: str,
            record_illegal_moves: bool, rounds: int, pairing: str, rating: str,
            rating_limit_1: int, rating_limit_2: int, last_result_update: float, last_illegal_move_update: float,
    ) -> StoredTournament:
        return self._write_stored_tournament(
            id, uniq_id, name, path, filename, ffe_id, ffe_password,
            handicap_initial_time, handicap_increment, handicap_penalty_step, handicap_penalty_value,
            handicap_min_time, chessevent_id, chessevent_tournament_name, record_illegal_moves, rounds, pairing,
            rating, rating_limit_1, rating_limit_2, last_result_update, last_illegal_move_update)

    def delete_stored_tournament(self, id: int):
        self._execute('DELETE FROM `timer_hour` WHERE timer_id = ?;', (id, ))
        self._execute('DELETE FROM `timer` WHERE `id` = ?;', (id, ))

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
        assert stored_tournament, PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
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

    def add_illegal_move(self, tournament_id: int, round: int, player_id: int) -> StoredIllegalMove:
        stored_tournament: StoredTournament = self._set_tournament_last_illegal_move_update(tournament_id)
        assert stored_tournament, PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
        fields: list[str] = ['tournament_id', 'round', 'player_id', 'date', ]
        params: list = [stored_tournament.id, round, player_id, time.time()]
        protected_fields = [f"`{f}`" for f in fields]
        self._execute(
            f'INSERT INTO `illegal_move`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
            tuple(params))
        return self._get_stored_illegal_move(self._last_inserted_id())

    def delete_illegal_move(self, tournament_id: int, round: int, player_id: int) -> bool:
        stored_tournament: StoredTournament = self._set_tournament_last_illegal_move_update(tournament_id)
        assert stored_tournament, PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
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

    def delete_illegal_moves(self, tournament_id: int, round: int):
        stored_tournament: StoredTournament = self._set_tournament_last_illegal_move_update(tournament_id)
        assert stored_tournament, PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
        self._execute(
            'DELETE FROM `illegal_move` WHERE `tournament_id` = ? AND `round` = ?',
            (stored_tournament.id, round,),
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
        assert stored_tournament, PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
        self._execute(
            'UPDATE `tournament` SET `last_result_update` = ? WHERE `id` = ?',
            (time.time(), stored_tournament.id, ),
        )
        return stored_tournament

    def add_result(self, tournament_id: int, round: int, board: Board, result: UtilResult):
        stored_tournament: StoredTournament = self._set_tournament_last_result_update(tournament_id)
        assert stored_tournament, PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
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

    def delete_result(self, tournament_id: int, round: int, board_id: int):
        stored_tournament: StoredTournament = self._set_tournament_last_result_update(tournament_id)
        assert stored_tournament, PapiWebException(f'Le tournoi [{tournament_id}] est introuvable.')
        self._execute(
            'DELETE FROM `result` WHERE `tournament_id` = ? AND `round` = ? AND `board_id` = ?',
            (stored_tournament.id, round, board_id),
        )

    def get_results(self, limit: int, *tournament_ids: Unpack[int]) -> Iterator[DataResult]:
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
            params: list[str] = [tournament_uniq_id for tournament_uniq_id in tournament_ids]
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
            boards_update=row['boards_update'],
            players_show_unpaired=row['players_show_unpaired'],
            columns=row['columns'],
            menu_text=row['menu_text'],
            menu=row['menu'],
            timer_id=row['timer_id'],
            results_limit=row['results_limit'],
            results_tournaments_str=row['results_tournaments_str'],
            range=row['range'],
            first=row['first'],
            last=row['last'],
            part=row['part'],
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
            self, id: int | None, uniq_id: str, name: str, type: ScreenType, boards_update: str,
            players_show_unpaired: bool, columns: int, menu_text: str, menu: str,
            timer_id: int, results_limit: int, results_tournaments_str: str, range: str,
            first: int, last: int, part: int, parts: int, number: int,
    ) -> StoredFamily:
        fields: list[str] = [
            'uniq_id', 'name', 'type', 'boards_update', 'players_show_unpaired', 'columns', 'menu_text', 'menu',
            'timer_id', 'results_limit', 'results_tournaments_str', 'range', 'first', 'last', 'part', 'parts',
            'number',
        ]
        params: list = [
            uniq_id, name, type, boards_update, players_show_unpaired, columns, menu_text, menu,
            timer_id, results_limit, results_tournaments_str, range, first, last, part, parts,
            number,
        ]
        if id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `family`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_family(self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [id]
            self._execute(
                f'UPDATE `family` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_family(id)

    def add_stored_family(
            self, uniq_id: str, name: str, type: ScreenType, boards_update: str,
            players_show_unpaired: bool, columns: int, menu_text: str, menu: str,
            timer_id: int, results_limit: int, results_tournaments_str: str, range: str,
            first: int, last: int, part: int, parts: int, number: int,
    ) -> StoredFamily:
        return self._write_stored_family(
            None, uniq_id, name, type, boards_update, players_show_unpaired, columns, menu_text, menu, timer_id,
            results_limit, results_tournaments_str, range, first, last, part, parts, number)

    def update_stored_family(
            self, id: int, uniq_id: str, name: str, type: ScreenType, boards_update: str,
            players_show_unpaired: bool, columns: int, menu_text: str, menu: str,
            timer_id: int, results_limit: int, results_tournaments_str: str, range: str,
            first: int, last: int, part: int, parts: int, number: int,
    ) -> StoredFamily:
        return self._write_stored_family(
            id, uniq_id, name, type, boards_update, players_show_unpaired, columns, menu_text, menu, timer_id,
            results_limit, results_tournaments_str, range, first, last, part, parts, number)

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
            boards_update=row['boards_update'],
            players_show_unpaired=row['players_show_unpaired'],
            columns=row['columns'],
            menu_text=row['menu_text'],
            menu=row['menu'],
            timer_id=row['timer_id'],
            results_limit=row['results_limit'],
            results_tournaments_str=row['results_tournaments_str'],
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

    def load_stored_screens(self) -> list[StoredScreen]:
        self._execute(
            'SELECT * FROM `screen` ORDER BY `uniq_id`',
            (),
        )
        stored_screens: list[StoredScreen] = [self._row_to_stored_screen(row) for row in self._fetchall()]
        for stored_screen in stored_screens:
            stored_screen.stored_screen_sets = self.load_stored_screen_set(stored_screen.id)
        return stored_screens

    def _write_stored_screen(
            self, id: int | None, uniq_id: str, name: str, type: ScreenType, boards_update: str,
            players_show_unpaired: bool, columns: int, menu_text: str, menu: str,
            timer_id: int, results_limit: int, results_tournaments_str: str, range: str,
            first: int, last: int, part: int, parts: int, number: int,
    ) -> StoredScreen:
        fields: list[str] = [
            'uniq_id', 'name', 'type', 'boards_update', 'players_show_unpaired', 'columns', 'menu_text', 'menu',
            'imer_id', 'results_limit', 'results_tournaments_str', 'range', 'first', 'last', 'part', 'parts',
            'number',
        ]
        params: list = [
            uniq_id, name, type, boards_update, players_show_unpaired, columns, menu_text, menu,
            timer_id, results_limit, results_tournaments_str, range, first, last, part, parts,
            number,
        ]
        if id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `screen`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_screen(id=self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [id]
            self._execute(
                f'UPDATE `screen` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_screen(id=id)

    def add_stored_screen(
            self, uniq_id: str, name: str, type: ScreenType, boards_update: str,
            players_show_unpaired: bool, columns: int, menu_text: str, menu: str,
            timer_id: int, results_limit: int, results_tournaments_str: str, range: str,
            first: int, last: int, part: int, parts: int, number: int,
    ) -> StoredScreen:
        return self._write_stored_screen(
            None, uniq_id, name, type, boards_update, players_show_unpaired, columns, menu_text, menu, timer_id,
            results_limit, results_tournaments_str, range, first, last, part, parts, number)

    def update_stored_screen(
            self, id: int, uniq_id: str, name: str, type: ScreenType, boards_update: str,
            players_show_unpaired: bool, columns: int, menu_text: str, menu: str,
            timer_id: int, results_limit: int, results_tournaments_str: str, range: str,
            first: int, last: int, part: int, parts: int, number: int,
    ) -> StoredScreen:
        return self._write_stored_screen(
            id, uniq_id, name, type, boards_update, players_show_unpaired, columns, menu_text, menu, timer_id,
            results_limit, results_tournaments_str, range, first, last, part, parts, number)

    def delete_stored_screen(self, id: int):
        self._execute('DELETE FROM `screen_set` WHERE `screen_id` = ?;', (id, ))
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
            first=row['first'],
            last=row['last'],
            part=row['part'],
            parts=row['parts'],
            number=row['number'],
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

    def load_stored_screen_set(self, screen_id: int) -> list[StoredScreenSet]:
        self._execute(
            'SELECT * FROM `screen_set` WHERE `screen_id` = ? ORDER BY `order`',
            (screen_id, ),
        )
        return [self._row_to_stored_screen_set(row) for row in self._fetchall()]

    def _write_stored_screen_set(
        self, id: int | None, screen_id: int, tournament_id: int, order: int,
        first: int, last: int, part: int, parts: int, number: int,
    ) -> StoredScreenSet:
        fields: list[str] = ['screen_id', 'tournament_id', 'order', 'first', 'last', 'part', 'parts', 'number', ]
        params: list = [screen_id, tournament_id, order, first, last, part, parts, number, ]
        if id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `screen_set`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_screen_set(id=self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [id]
            self._execute(
                f'UPDATE `screen_set` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_screen_set(id=id)

    def add_stored_screen_set(
        self, screen_id: int, tournament_id: int, order: int,
        first: int, last: int, part: int, parts: int, number: int,
    ) -> StoredScreenSet:
        return self._write_stored_screen_set(
            None, screen_id, tournament_id, order, first, last, part, parts, number)

    def update_stored_screen_set(
        self, id: int, screen_id: int, tournament_id: int, order: int,
        first: int, last: int, part: int, parts: int, number: int,
    ) -> StoredScreenSet:
        return self._write_stored_screen_set(
            id, screen_id, tournament_id, order, first, last, part, parts, number)

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

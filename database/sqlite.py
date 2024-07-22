"""A database schema based on sqlite3.

At this time, this database stores results and illegal moves. """
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from logging import Logger
from pathlib import Path
from sqlite3 import Connection, Cursor, connect, OperationalError
from typing import Self, Any, Unpack

from packaging.version import Version

from common.exception import PapiWebException
from data.util import Result as UtilResult, ScreenType
from data.result import Result as DataResult
from common.logger import get_logger
from common.papi_web_config import PAPI_WEB_VERSION
from data.board import Board
from database.store import StoredTournament, StoredEvent, StoredChessEvent, StoredTimer, StoredTimerHour, \
    StoredFamily, StoredIllegalMove, StoredResult, StoredRotator, StoredScreenSet, StoredScreen

logger: Logger = get_logger()

DB_PATH: Path = Path('.') / 'db'
SQL_PATH: Path = Path(__file__).resolve().parent / 'sql'


@dataclass
class SQLiteDatabase:
    """A database using SQLite.

    This is a rework of the papi database, and stores slightly more information than
    the papi database.
    """
    file: Path
    method: str
    read_only: bool = field(init=False, default=True)
    database: Connection | None = field(init=False, default=None)
    cursor: Cursor | None = field(init=False, default=None)

    def __post_init__(self):
        match self.method:
            case 'r':
                self.read_only = True
            case 'w':
                self.read_only = False
            case _:
                raise ValueError

    def __enter__(self) -> Self:
        db_url: str = f'file:{self.file}?mode={"ro" if self.read_only else "rw"}'
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

    def _commit(self):
        self.database.commit()

    def _last_inserted_id(self) -> int:
        return self.cursor.lastrowid


class EventDatabase(SQLiteDatabase):
    def __init__(self, event_uniq_id: str, method: str):
        self.event_uniq_id = event_uniq_id
        self._version: Version | None = None
        super().__init__(DB_PATH / f'{self.event_uniq_id}.db', method)

    def __post_init__(self):
        super().__post_init__()
        DB_PATH.mkdir(parents=True, exist_ok=True)
        if not self.file.is_file():
            database: Connection | None = None
            cursor: Cursor | None = None
            try:
                database = connect(database=self.file, detect_types=1, uri=True)
                cursor = database.cursor()
                with open(SQL_PATH / 'create_event.sql', encoding='utf-8') as f:
                    cursor.executescript(f.read().format(
                        version=f'{PAPI_WEB_VERSION.major}.{PAPI_WEB_VERSION.minor}.{PAPI_WEB_VERSION.micro}'))
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

    def __enter__(self) -> Self:
        super().__enter__()
        if self.version != Version(f'{PAPI_WEB_VERSION.major}.{PAPI_WEB_VERSION.minor}.{PAPI_WEB_VERSION.micro}'):
            if self.read_only:
                with EventDatabase(self.event_uniq_id, 'w') as event_database:
                    event_database: EventDatabase
                    event_database.upgrade()
            else:
                self.upgrade()
        return self

    """ 
    ---------------------------------------------------------------------------------
    StoredEvent 
    ---------------------------------------------------------------------------------
    """

    @staticmethod
    def _row_to_stored_event(row: dict[str, Any]) -> StoredEvent:
        return StoredEvent(
                version=row['version'],
                name=row['name'],
                path=row['path'],
                css=row['css'],
                update_password=row['update_password'],
                record_illegal_moves=row['record_illegal_moves'],
                allow_deletion=row['allow_deletion'],
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
                self._execute('CREATE TABLE `chessevent` ('
                              '    `id` INTEGER NOT NULL,'
                              '    `uniq_id` TEXT NOT NULL,'
                              '    `user_id` TEXT NOT NULL,'
                              '    `password` TEXT NOT NULL,'
                              '    `event_id` TEXT NOT NULL,'
                              '    PRIMARY KEY(`id` AUTOINCREMENT),'
                              '    UNIQUE(`uniq_id`)'
                              ');'
                              )
                self.set_version(version)
                self.commit()
            case _:
                raise PapiWebException(
                    f'La base de données {self.file.name} ne peut être mise à jour en version {version}.')
        logger.info(f'La base de données {self.file.name} a été mise à jour en version {version}.')

    def upgrade(self):
        if self.version > PAPI_WEB_VERSION:
            raise PapiWebException(
                f'Votre version de Papi-web ({PAPI_WEB_VERSION}) '
                f'ne peut pas ouvrir les bases de données en version {self.version}, '
                f'veuillez mettre à jour votre version de Papi-web')
        logger.info(f'Mise à jour de la base de données...')
        if self.version < (version := Version('2.4.1')):
            self._upgrade(version)

    def commit(self):
        self._commit()

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

    def get_stored_chessevent(self, id: int = None, uniq_id: int = None) -> StoredChessEvent | None:
        if id is not None:
            assert uniq_id is None, ValueError
            self._execute(
                'SELECT * FROM `chessevent` WHERE `id` = ?',
                (id, ),
            )
        else:
            assert uniq_id is not None, ValueError
            self._execute(
                'SELECT * FROM `chessevent` WHERE `uniq_id` = ?',
                (uniq_id, ),
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
            self, id: int | None, uniq_id: str, user_id: str, password: str, event_id: str
    ) -> StoredChessEvent:
        fields: list[str] = ['uniq_id', 'user_id', 'password', 'event_id', ]
        params: list = [uniq_id, user_id, password, event_id, ]
        if id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `chessevent`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_chessevent(id=self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [id]
            self._execute(
                f'UPDATE `chessevent` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_chessevent(id=id)

    def add_stored_chessevent(
            self, uniq_id: str, user_id: str, password: str, event_id: str
    ) -> StoredChessEvent:
        return self._write_stored_chessevent(None, uniq_id, user_id, password, event_id)

    def update_stored_chessevent(
            self, id: int, uniq_id: str, user_id: str, password: str, event_id: str
    ) -> StoredChessEvent:
        return self._write_stored_chessevent(id, uniq_id, user_id, password, event_id)

    def delete_stored_chessevent(self, id: int):
        self._execute('DELETE FROM `chessevent` WHERE `id` = ?;', (id, ))

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

    def get_stored_timer_hour(self, id: int = None) -> StoredTimerHour | None:
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
            self, id: int | None, timer_id: int, order: int, date: str, round: int | None, event: str | None,
            text_before: str | None, text_after: str | None
    ) -> StoredTimerHour:
        fields: list[str] = ['timer_id', 'order', 'date', 'round', 'event', 'text_before', 'text_after', ]
        params: list = [timer_id, order, date, round, event, text_before, text_after, ]
        if id is None:
            protected_fields = [f"`{f}`" for f in fields]
            self._execute(
                f'INSERT INTO `timer_hour`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params))
            return self.get_stored_timer_hour(id=self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [id]
            self._execute(
                f'UPDATE `timer_hour` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_timer_hour(id=id)

    def add_stored_timer_hour(
            self, timer_id: int, order: int, date: str, round: int | None, event: str | None,
            text_before: str | None, text_after: str | None
    ) -> StoredTimerHour:
        return self._write_stored_timer_hour(None, timer_id, order, date, round, event, text_before, text_after)

    def update_stored_timer_hour(
            self, id: int, timer_id: int, order: int, date: str, round: int | None, event: str | None,
            text_before: str | None, text_after: str | None
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

    def get_stored_timer(self, id: int = None) -> StoredTimer | None:
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
            return self.get_stored_timer(id=self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [id]
            self._execute(
                f'UPDATE `timer` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_timer(id=id)

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

    def _write_stored_tournament(self, uniq_id: str) -> StoredTournament:
        self._execute(
            'INSERT INTO `tournament`(`uniq_id`) VALUES(?)',
            (uniq_id,),
        )
        return self.get_stored_tournament(id=self._last_inserted_id())

    def get_stored_tournament(
            self, id: int | None = None, uniq_id: str | None = None, create_if_absent: bool = False,
    ) -> StoredTournament | None:
        if id is not None:
            assert uniq_id is None and not create_if_absent, ValueError(
                f'id=[{id}], uniq_id=[{uniq_id}], create_if_absent=[{create_if_absent}]')
            self._execute(
                'SELECT * FROM `tournament` WHERE `id` = ?',
                (id, ),
            )
        else:
            assert uniq_id is not None, ValueError(
                f'id=[{id}], uniq_id=[{uniq_id}], create_if_absent=[{create_if_absent}]')
            self._execute(
                'SELECT * FROM `tournament` WHERE `uniq_id` = ?',
                (uniq_id, ),
            )
        row: dict[str, Any]
        if row := self._fetchone():
            return self._row_to_stored_tournament(row)
        if create_if_absent:
            if self.read_only:
                with EventDatabase(self.event_uniq_id, 'w') as event_database:
                    event_database: EventDatabase
                    stored_tournament: StoredTournament = event_database.get_stored_tournament(
                        uniq_id=uniq_id, create_if_absent=True)
                    event_database.commit()
                    return stored_tournament
            else:
                return self._write_stored_tournament(uniq_id)
        return None

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

    def _set_tournament_last_illegal_move_update(self, tournament_uniq_id: str) -> StoredTournament:
        stored_tournament: StoredTournament = self.get_stored_tournament(
            uniq_id=tournament_uniq_id, create_if_absent=True)
        self._execute(
            'UPDATE `tournament` SET `last_illegal_move_update` = ? WHERE `id` = ?',
            (time.time(), stored_tournament.id, ),
        )
        return self.get_stored_tournament(id=stored_tournament.id)

    def get_illegal_moves(self, tournament_uniq_id: str, round: int) -> Counter[int]:
        # TODO move this method to get_illegal_moves(tournament_id: int, round: int)
        self._execute(
            'SELECT `illegal_move`.* '
            'FROM `illegal_move` '
            'JOIN `tournament` ON `illegal_move`.`tournament_id` = `tournament`.`id`' 
            'WHERE `tournament`.`uniq_id` = ? AND `round` = ?',
            (tournament_uniq_id, round, ),
        )
        illegal_moves: Counter[int] = Counter[int]()
        for row in self._fetchall():
            illegal_moves[int(row['player_id'])] += 1
        return illegal_moves

    def add_illegal_move(self, tournament_uniq_id: str, round: int, player_id: int) -> StoredIllegalMove:
        # TODO move this method to get_illegal_moves(tournament_id: int, round: int, player_id: int)
        stored_tournament: StoredTournament = self._set_tournament_last_illegal_move_update(
            tournament_uniq_id=tournament_uniq_id)
        fields: list[str] = ['tournament_id', 'round', 'player_id', 'date', ]
        params: list = [stored_tournament.id, round, player_id, time.time()]
        protected_fields = [f"`{f}`" for f in fields]
        self._execute(
            f'INSERT INTO `illegal_move`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
            tuple(params))
        return self._get_stored_illegal_move(id=self._last_inserted_id())

    def delete_illegal_move(self, tournament_uniq_id: str, round: int, player_id: int) -> bool:
        # TODO move this method to delete_illegal_move(tournament_id: int, round: int, player_id: int)
        stored_tournament: StoredTournament = self._set_tournament_last_illegal_move_update(
            tournament_uniq_id=tournament_uniq_id)
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

    def delete_illegal_moves(self, tournament_uniq_id: str, round: int):
        # TODO move this method to delete_illegal_moves(tournament_id: int, round: int)
        stored_tournament: StoredTournament = self._set_tournament_last_illegal_move_update(
            tournament_uniq_id=tournament_uniq_id)
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

    def _set_tournament_last_result_update(self, tournament_uniq_id: str) -> StoredTournament:
        stored_tournament: StoredTournament = self.get_stored_tournament(
            uniq_id=tournament_uniq_id, create_if_absent=True)
        self._execute(
            'UPDATE `tournament` SET `last_result_update` = ? WHERE `id` = ?',
            (time.time(), stored_tournament.id, ),
        )
        return stored_tournament

    def add_result(self, tournament_uniq_id: str, round: int, board: Board, result: UtilResult):
        # TODO move this method to add_result(tournament_id: int, round: int, board: Board, result: UtilResult)
        stored_tournament: StoredTournament = self._set_tournament_last_result_update(
            tournament_uniq_id=tournament_uniq_id)
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

    def delete_result(self, tournament_uniq_id: str, round: int, board_id: int):
        # TODO move this method to delete_result(tournament_id: int, round: int, board_id: int)
        stored_tournament: StoredTournament = self._set_tournament_last_result_update(
            tournament_uniq_id=tournament_uniq_id)
        self._execute(
            'DELETE FROM `result` WHERE `tournament_id` = ? AND `round` = ? AND `board_id` = ?',
            (stored_tournament.id, round, board_id),
        )

    def get_results(self, limit: int, *tournament_uniq_ids: Unpack[str]) -> Iterator[DataResult]:
        # TODO move this method to get_results(limit: int, *tournament_ids: Unpack[int]) -> Iterator[DataResult]
        if not tournament_uniq_ids:
            query: str = ('SELECT '
                          '    `tournament`.`uniq_id` as `tournament_uniq_id`, '
                          '    `result`.`round`, `result`.`board_id`, '
                          '    `result`.`white_player_id`, `result`.`black_player_id`, '
                          '    `result`.`date`, `result`.`value` '
                          'FROM `result` '
                          'JOIN `tournament` ON `result`.`tournament_id` = `tournament`.`id` '
                          'ORDER BY `date` DESC')
            params: tuple = ()
            if limit:
                query += ' LIMIT ?'
                params = (limit, )
        else:
            query: str = ('SELECT '
                          '    `tournament`.`uniq_id` as `tournament_uniq_id`, '
                          '    `result`.`round`, `result`.`board_id`, '
                          '    `result`.`white_player_id`, `result`.`black_player_id`, '
                          '    `result`.`date`, `result`.`value` '
                          'FROM `result` '
                          'JOIN `tournament` ON `result`.`tournament_id` = `tournament`.`id` '
                          f'WHERE {" OR ".join([f"`tournament`.`uniq_id` = ?", ] * len(tournament_uniq_ids))} '
                          'ORDER BY `date` DESC')
            params: list[str] = [tournament_uniq_id for tournament_uniq_id in tournament_uniq_ids]
            if limit:
                query += ' LIMIT ?'
                params += (limit, )
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

    def get_stored_family(self, id: int = None, uniq_id: int = None) -> StoredFamily | None:
        if id is not None:
            assert uniq_id is None, ValueError
            self._execute(
                'SELECT * FROM `family` WHERE `id` = ?',
                (id, ),
            )
        else:
            assert uniq_id is not None, ValueError
            self._execute(
                'SELECT * FROM `family` WHERE `uniq_id` = ?',
                (uniq_id, ),
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
            players_show_unpaired: bool | None, columns: int | None, menu_text: str | None, menu: str | None,
            timer_id: int | None, results_limit: int | None, results_tournaments_str: str | None, range: str | None,
            first: int | None, last: int | None, part: int | None, parts: int | None, number: int | None,
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
            return self.get_stored_family(id=self._last_inserted_id())
        else:
            field_sets = [f"`{f}` = ?" for f in fields]
            params += [id]
            self._execute(
                f'UPDATE `family` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params))
            return self.get_stored_family(id=id)

    def add_stored_family(
            self, uniq_id: str, name: str, type: ScreenType, boards_update: str,
            players_show_unpaired: bool | None, columns: int | None, menu_text: str | None, menu: str | None,
            timer_id: int | None, results_limit: int | None, results_tournaments_str: str | None, range: str | None,
            first: int | None, last: int | None, part: int | None, parts: int | None, number: int | None,
    ) -> StoredFamily:
        return self._write_stored_family(
            None, uniq_id, name, type, boards_update, players_show_unpaired, columns, menu_text, menu, timer_id,
            results_limit, results_tournaments_str, range, first, last, part, parts, number)

    def update_stored_family(
            self, id: int, uniq_id: str, name: str, type: ScreenType, boards_update: str,
            players_show_unpaired: bool | None, columns: int | None, menu_text: str | None, menu: str | None,
            timer_id: int | None, results_limit: int | None, results_tournaments_str: str | None, range: str | None,
            first: int | None, last: int | None, part: int | None, parts: int | None, number: int | None,
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

    def get_stored_screen(self, id: int = None, uniq_id: int = None) -> StoredScreen | None:
        if id is not None:
            assert uniq_id is None, ValueError
            self._execute(
                'SELECT * FROM `screen` WHERE `id` = ?',
                (id, ),
            )
        else:
            assert uniq_id is not None, ValueError
            self._execute(
                'SELECT * FROM `screen` WHERE `uniq_id` = ?',
                (uniq_id, ),
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
            players_show_unpaired: bool | None, columns: int | None, menu_text: str | None, menu: str | None,
            timer_id: int | None, results_limit: int | None, results_tournaments_str: str | None, range: str | None,
            first: int | None, last: int | None, part: int | None, parts: int | None, number: int | None,
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
            players_show_unpaired: bool | None, columns: int | None, menu_text: str | None, menu: str | None,
            timer_id: int | None, results_limit: int | None, results_tournaments_str: str | None, range: str | None,
            first: int | None, last: int | None, part: int | None, parts: int | None, number: int | None,
    ) -> StoredScreen:
        return self._write_stored_screen(
            None, uniq_id, name, type, boards_update, players_show_unpaired, columns, menu_text, menu, timer_id,
            results_limit, results_tournaments_str, range, first, last, part, parts, number)

    def update_stored_screen(
            self, id: int, uniq_id: str, name: str, type: ScreenType, boards_update: str,
            players_show_unpaired: bool | None, columns: int | None, menu_text: str | None, menu: str | None,
            timer_id: int | None, results_limit: int | None, results_tournaments_str: str | None, range: str | None,
            first: int | None, last: int | None, part: int | None, parts: int | None, number: int | None,
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

    def get_stored_screen_set(self, id: int = None, uniq_id: int = None) -> StoredScreenSet | None:
        if id is not None:
            assert uniq_id is None, ValueError
            self._execute(
                'SELECT * FROM `screen_set` WHERE `id` = ?',
                (id, ),
            )
        else:
            assert uniq_id is not None, ValueError
            self._execute(
                'SELECT * FROM `screen_set` WHERE `uniq_id` = ?',
                (uniq_id, ),
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
        first: int | None, last: int | None, part: int | None, parts: int | None, number: int | None,
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
        first: int | None, last: int | None, part: int | None, parts: int | None, number: int | None,
    ) -> StoredScreenSet:
        return self._write_stored_screen_set(
            None, screen_id, tournament_id, order, first, last, part, parts, number)

    def update_stored_screen_set(
        self, id: int, screen_id: int, tournament_id: int, order: int,
        first: int | None, last: int | None, part: int | None, parts: int | None, number: int | None,
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

    def get_stored_rotator(self, id: int = None, uniq_id: int = None) -> StoredRotator | None:
        if id is not None:
            assert uniq_id is None, ValueError
            self._execute(
                'SELECT * FROM `rotator` WHERE `id` = ?',
                (id, ),
            )
        else:
            assert uniq_id is not None, ValueError
            self._execute(
                'SELECT * FROM `rotator` WHERE `uniq_id` = ?',
                (uniq_id, ),
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
            self, id: int | None, uniq_id: str, screens_str: str | None, families_str: str | None, delay: int | None,
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
            self, uniq_id: str, screens_str: str, families_str: str,
    ) -> StoredRotator:
        return self._write_stored_rotator(None, uniq_id, screens_str, families_str)

    def update_stored_rotator(
            self, id: int, uniq_id: str, screens_str: str, families_str: str,
    ) -> StoredRotator:
        return self._write_stored_rotator(id, uniq_id, screens_str, families_str)

    def delete_stored_rotator(self, id: int):
        self._execute('DELETE FROM `rotator` WHERE `id` = ?;', (id, ))


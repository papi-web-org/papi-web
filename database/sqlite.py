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
from data.util import Result as UtilResult
from data.result import Result as DataResult
from common.logger import get_logger
from common.papi_web_config import PAPI_WEB_VERSION
from data.board import Board

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

    @property
    def version(self) -> Version:
        if self._version is None:
            self._execute('SELECT `version` FROM `info`', )
            self._version = Version(self._fetchone()['version'])
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

    def _add_tournament(self, tournament_uniq_id: str) -> tuple[int, float, float]:
        self._execute(
            'INSERT INTO `tournament`(`uniq_id`) VALUES(?)',
            (tournament_uniq_id, ),
        )
        return self._last_inserted_id(), 0.0, 0.0

    def _get_tournament_info_from_uniq_id(
            self, tournament_uniq_id: str, create_if_absent: bool = False
    ) -> tuple[int | None, float, float]:
        self._execute(
            'SELECT '
            '    `id`, '
            '    `last_result_update`, '
            '    `last_illegal_move_update` '
            'FROM `tournament` WHERE `uniq_id` = ?',
            (tournament_uniq_id, ),
        )
        row: dict[str, Any] = self._fetchone()
        if row:
            return row['id'], row['last_result_update'], row['last_illegal_move_update']
        if create_if_absent:
            return self._add_tournament(tournament_uniq_id)
        return None, 0.0, 0.0

    def _get_tournament_id_from_uniq_id(self, tournament_uniq_id: str, create_if_absent: bool = False) -> int | None:
        return self._get_tournament_info_from_uniq_id(tournament_uniq_id, create_if_absent)[0]

    def get_tournament_last_updates_from_uniq_id(self, tournament_uniq_id: str) -> tuple[int, int]:
        info: tuple = self._get_tournament_info_from_uniq_id(tournament_uniq_id)
        return info[1], info[2]

    def _set_tournament_last_illegal_move_update(self, tournament_uniq_id: str, now: float | None = None) -> int:
        tournament_id: int = self._get_tournament_id_from_uniq_id(tournament_uniq_id, create_if_absent=True)
        if now is None:
            now = time.time()
        self._execute(
            'UPDATE `tournament` SET `last_illegal_move_update` = ? WHERE `id` = ?',
            (now, tournament_id, ),
        )
        return tournament_id

    def get_illegal_moves(self, tournament_uniq_id: str, round: int) -> Counter[int]:
        self._execute(
            'SELECT `illegal_move`.`id`, `illegal_move`.`player_id` '
            'FROM `illegal_move` '
            'JOIN `tournament` ON `illegal_move`.`tournament_id` = `tournament`.`id`' 
            'WHERE `tournament`.`uniq_id` = ? AND `round` = ?',
            (tournament_uniq_id, round, ),
        )
        illegal_moves: Counter[int] = Counter[int]()
        for row in self._fetchall():
            illegal_moves[int(row['player_id'])] += 1
        return illegal_moves

    def store_illegal_move(self, tournament_uniq_id: str, round: int, player_id: int):
        now: float = time.time()
        tournament_id: int = self._set_tournament_last_illegal_move_update(tournament_uniq_id, now)
        self._execute(
            'INSERT INTO `illegal_move`(`tournament_id`, `round`, `player_id`, `date`) VALUES(?, ?, ?, ?)',
            (tournament_id, round, player_id, now),
        )

    def delete_illegal_move(self, tournament_uniq_id: str, round: int, player_id: int) -> bool:
        tournament_id: int = self._set_tournament_last_illegal_move_update(tournament_uniq_id)
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

    def delete_illegal_moves(self, tournament_uniq_id: str, round: int):
        tournament_id: int = self._set_tournament_last_illegal_move_update(tournament_uniq_id)
        self._execute(
            'DELETE FROM `illegal_move` WHERE `tournament_id` = ? AND `round` = ?',
            (tournament_id, round,),
        )

    def _set_tournament_last_result_update(self, tournament_uniq_id: str, now: float | None = None) -> int:
        tournament_id: int = self._get_tournament_id_from_uniq_id(tournament_uniq_id, create_if_absent=True)
        if now is None:
            now = time.time()
        self._execute(
            'UPDATE `tournament` SET `last_result_update` = ? WHERE `id` = ?',
            (now, tournament_id, ),
        )
        return tournament_id

    def add_result(self, tournament_uniq_id: str, round: int, board: Board, result: UtilResult):
        now: float = time.time()
        tournament_id: int = self._set_tournament_last_result_update(tournament_uniq_id, now)
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
                now,
            ),
        )

    def delete_result(self, tournament_uniq_id: str, round: int, board_id: int):
        tournament_id: int = self._set_tournament_last_result_update(tournament_uniq_id)
        self._execute(
            'DELETE FROM `result` WHERE `tournament_id` = ? AND `round` = ? AND `board_id` = ?',
            (tournament_id, round, board_id),
        )

    def get_results(self, limit: int, *tournament_uniq_ids: Unpack[str]) -> Iterator[DataResult]:
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

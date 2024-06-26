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


class EventDatabase(SQLiteDatabase):
    def __init__(self, event_id: str, method: str):
        super().__init__(DB_PATH / f'{event_id}.db', method)

    def __post_init__(self):
        super().__post_init__()
        DB_PATH.mkdir(parents=True, exist_ok=True)
        if not self.file.is_file():
            database: Connection | None = None
            cursor: Cursor | None = None
            try:
                database = connect(database=self.file, detect_types=1, uri=True)
                cursor = database.cursor()
                with open(SQL_PATH / 'init.sql', encoding='utf-8') as f:
                    cursor.executescript(f.read().format(version=PAPI_WEB_VERSION))
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
        self._execute('SELECT `version` FROM `info`', )
        database_version: Version = Version(self._fetchone()["version"])
        if database_version != PAPI_WEB_VERSION:
            self._upgrade(database_version)
        return self

    def _upgrade_2_5_0(self):
        pass

    def _upgrade(self, from_version: Version):
        if from_version > PAPI_WEB_VERSION:
            raise ValueError(
                f'Votre version de Papi-web ({PAPI_WEB_VERSION}) '
                f'ne peut pas ouvrir les bases de données en version {from_version}, '
                f'veuillez mettre à jour votre version de Papi-web')
        if from_version < Version('2.5.0'):
            self._upgrade_2_5_0()

    def commit(self):
        self._commit()

    def _set_tournament_updated(self, tournament_id: str):
        self._execute(
            'SELECT `last_update` FROM `tournament` WHERE `id` = ?',
            (tournament_id, ),
        )
        if self._fetchone():
            self._execute(
                'UPDATE `tournament` SET `last_update` = ? WHERE `id` = ?',
                (time.time(), tournament_id, ),
            )
        else:
            self._execute(
                'INSERT INTO `tournament`(`id`, `last_update`) VALUES(?, ?)',
                (tournament_id, time.time(), ),
            )

    def get_illegal_moves(self, tournament_id: str, round: int) -> Counter[int]:
        self._execute(
            'SELECT `id`, `player_id` FROM `illegal_move` WHERE `tournament_id` = ? AND `round` = ?',
            (tournament_id, round, ),
        )
        illegal_moves: Counter[int] = Counter[int]()
        for row in self._fetchall():
            illegal_moves[int(row['player_id'])] += 1
        return illegal_moves

    def store_illegal_move(self, tournament_id: str, round: int, player_id: int):
        now: float = time.time()
        self._execute(
            'INSERT INTO `illegal_move`(`tournament_id`, `round`, `player_id`, `date`) VALUES(?, ?, ?, ?)',
            (tournament_id, round, player_id, now),
        )
        self._set_tournament_updated(tournament_id)

    def delete_illegal_move(self, tournament_id: str, round: int, player_id: int) -> bool:
        self._execute(
            'SELECT `id` FROM `illegal_move` WHERE `tournament_id` = ? AND `round` = ? AND `player_id` = ? LIMIT 1',
            (tournament_id, round, player_id, ),
        )
        row: dict[str, Any] = self._fetchone()
        if row is None:
            return False
        self._execute(
            'DELETE FROM `illegal_move` WHERE `id` = ?',
            (row['id'], ),
        )
        self._set_tournament_updated(tournament_id)
        return True

    def delete_illegal_moves(self, tournament_id: str, round: int):
        self._execute(
            'DELETE FROM `illegal_move` WHERE `tournament_id` = ? AND `round` = ?',
            (tournament_id, round, ),
        )
        self._set_tournament_updated(tournament_id)

    def add_result(self, tournament_id: str, round: int, board: Board, result: UtilResult):
        self._execute(
            'INSERT INTO `result`('
            '`tournament_id`, `round`, `board_id`, `white_player`, `black_player`, `value`, `date`'
            ') VALUES(?, ?, ?, ?, ?, ?, ?)',
            (
                tournament_id,
                round,
                board.id,
                f'{board.white_player.last_name} {board.white_player.first_name} {board.white_player.rating}',
                f'{board.black_player.last_name} {board.black_player.first_name} {board.black_player.rating}',
                result,
                time.time(),
            ),
        )

    def delete_result(self, tournament_id: str, round: int, board_id: int):
        self._execute(
            'DELETE FROM `result` WHERE `tournament_id` = ? AND `round` = ? AND `board_id` = ?',
            (tournament_id, round, board_id),
        )

    def get_results(self, limit: int, *tournaments: Unpack[str]) -> Iterator[DataResult]:
        if not tournaments:
            query: str = ('SELECT `tournament_id`, `round`, `board_id`, `white_player`, `black_player`, `date`, `value` '
                          'FROM `result` ORDER BY `date` DESC')
            params: tuple = ()
            if limit:
                query += ' LIMIT ?'
                params = (limit, )
        elif len(tournaments) == 1:
            query: str = ('SELECT `tournament_id`, `round`, `board_id`, `white_player`, `black_player`, `date`, `value` '
                          'FROM `result` WHERE `tournament_id` = ? ORDER BY `date` DESC')
            params = (tournaments[0], )
            if limit:
                query += ' LIMIT ?'
                params += (limit, )
        else:
            # FIXME(Amaras) : Check if `WHERE value in (?, ?, ...)` is posible in SQLITE
            query_parts: list[str] = []
            params: tuple = ()
            for tournament in tournaments:
                query_part: str = ('SELECT `tournament_id`, `round`, `board_id`, `white_player`, `black_player`, `date`, `value` '
                                   'FROM `result` WHERE `tournament_id` = ? ORDER BY `date` DESC')
                params += (tournament, )
                if limit:
                    query_part += ' LIMIT ?'
                    params += (limit, )
                query_parts.append('\n'.join(('SELECT * FROM (', query_part, ')')))
            query: str = '\nUNION\n'.join(query_parts) + ' ORDER BY `date` DESC'
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
                    row['tournament_id'],
                    row['round'],
                    row['board_id'],
                    row['white_player'],
                    row['black_player'],
                    value)

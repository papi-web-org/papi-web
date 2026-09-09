import json
import sqlite3
from time import perf_counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from sqlite3 import Connection, Cursor, connect, OperationalError
from typing import Self, Any

from common.logger import get_logger


logger = get_logger()


@dataclass
class SQLiteDatabase:
    """
    The base generic class for SQLite databases.
    """

    file: Path
    write: bool = field(default=False)
    enable_foreign_keys: bool = field(default=True)
    database: Connection | None = field(init=False, default=None)
    cursor: Cursor | None = field(init=False, default=None)

    def is_sqlite_file(self) -> bool:
        try:
            with self:
                self.execute('SELECT 1 AS is_sqlite')
                row = self.fetchone()
                return row.get('is_sqlite') == 1
        except sqlite3.DatabaseError:
            return False

    def exists(self) -> bool:
        """Checks if the database file exists."""
        return self.file.exists()

    def delete(self):
        """Deletes the database if it exists."""
        self.file.unlink(missing_ok=True)

    def _create(self, script: str | None = None):
        database: Connection | None = None
        try:
            Path(self.file).parent.mkdir(parents=True, exist_ok=True)
            database = connect(database=self.file, detect_types=1, uri=True)
            if script:
                database.executescript(script)
                database.commit()
            database.close()
        except OperationalError as e:
            if database:
                database.close()
            self.file.unlink(missing_ok=True)
            raise e

    def __enter__(self) -> Self:
        db_url: str = f'file:{self.file}?mode={"rw" if self.write else "ro"}'
        try:
            self.database = connect(db_url, detect_types=1, uri=True)
            self.cursor = self.database.cursor()

            self.cursor.execute('PRAGMA busy_timeout=5000')

            if self.write:
                fk_status = 'ON' if self.enable_foreign_keys else 'OFF'
                self.cursor.execute(f'PRAGMA foreign_keys={fk_status}')
                self.cursor.execute('PRAGMA journal_mode=DELETE')
                self.cursor.execute('BEGIN IMMEDIATE')

            return self
        except OperationalError as e:
            # A failure to open the file (missing, locked, inaccessible…) is an
            # expected, handled case surfaced by the callers, so it is kept at
            # debug level to avoid flooding the logs.
            logger.debug(
                'Failed to open database %s (write=%s): %s',
                self.file,
                self.write,
                e,
            )
            raise
        except Exception as e:
            logger.exception(
                'Failed to open database %s (write=%s): %s',
                self.file,
                self.write,
                e,
            )
            raise

    def __exit__(self, exc_type, exc_value, tb):
        try:
            if self.database and self.write:
                if exc_type is None:
                    self.database.commit()
                else:
                    logger.debug(
                        'Rolling back [%s] due to exception [%s]: %s',
                        self.file,
                        exc_type,
                        exc_value,
                    )
                    self.database.rollback()
        finally:
            try:
                if self.cursor is not None:
                    self.cursor.close()
            finally:
                del self.cursor
                self.cursor = None
                if self.database is not None:
                    self.database.close()
                    del self.database
                    self.database = None

    def execute(self, query: str, params: tuple | dict[str, Any] = ()):
        assert self.cursor is not None
        from web.performance import current_request_performance, record_sql

        if current_request_performance() is None:
            self.cursor.execute(query, params)
            return
        start = perf_counter()
        try:
            self.cursor.execute(query, params)
        finally:
            record_sql(query, perf_counter() - start)

    def executemany(self, query: str, params: Iterable[tuple | dict[str, Any]] = ()):
        assert self.cursor is not None
        from web.performance import current_request_performance, record_sql

        if current_request_performance() is None:
            self.cursor.executemany(query, params)
            return
        start = perf_counter()
        try:
            self.cursor.executemany(query, params)
        finally:
            record_sql(query, perf_counter() - start)

    def executescript(self, sql: str):
        assert self.cursor is not None
        self.cursor.executescript(sql)

    def fetchall(self) -> Iterator[dict[str, Any]]:
        assert self.cursor is not None
        columns = [column[0] for column in self.cursor.description]
        for row in self.cursor.fetchall():
            yield dict(zip(columns, row))

    def fetchone(self) -> dict[str, Any]:
        assert self.cursor is not None
        columns = [column[0] for column in self.cursor.description]
        result = self.cursor.fetchone()
        return {} if result is None else dict(zip(columns, result))

    def commit(self):
        assert self.database is not None
        self.database.commit()

    def _last_inserted_id(self) -> int | None:
        assert self.cursor is not None
        return self.cursor.lastrowid

    def _get_table_count(self, table_name: str) -> int:
        self.execute(f'SELECT COUNT(*) as `count` FROM `{table_name}`')
        return self.fetchone()['count']

    @staticmethod
    def load_bool_or_none_from_database_field(
        data: int | None, if_none: bool | None = None
    ) -> bool | None:
        """Returns True if `data` is 1, False if `data` is something else other
        than None, and `if_none` if `data` is None."""
        return data == 1 if data is not None else if_none

    @staticmethod
    def load_bool_from_database_field(data: int | None) -> bool:
        """Returns True if `data` is 1, False otherwise."""
        return data == 1

    @classmethod
    def load_optional_date_from_database_field(cls, data: str | None) -> date | None:
        return cls.load_date_from_database_field(data) if data else None

    @staticmethod
    def load_date_from_database_field(data: str) -> date:
        # Stored dates are ISO; retain strptime for legacy values.
        try:
            return date.fromisoformat(data)
        except ValueError:
            return datetime.strptime(data, '%Y-%m-%d').date()

    @staticmethod
    def dump_date_to_database_field(date_: date | None) -> str | None:
        return date_.strftime('%Y-%m-%d') if date_ else None

    @staticmethod
    def load_datetime_from_database_field(data: str) -> datetime:
        return datetime.fromisoformat(data).astimezone().replace(tzinfo=None)

    @staticmethod
    def now_as_database_timestamp() -> str:
        """Returns current time as UTC ISO 8601 string for DB storage (e.g. '2026-02-20 08:07:52.662+00:00')."""
        return datetime.now(timezone.utc).isoformat(sep=' ', timespec='milliseconds')

    @staticmethod
    def load_optional_timestamp_from_database_field(
        ts: str | None,
    ) -> datetime | None:
        """Load optional timestamp from database field (UTC ISO TEXT) to local naive datetime."""
        return (
            datetime.fromisoformat(ts).astimezone().replace(tzinfo=None) if ts else None
        )

    @staticmethod
    def dump_optional_datetime_to_timestamp_field(
        datetime_: datetime | None,
    ) -> str | None:
        """Dump local naive datetime to UTC ISO TEXT for DB storage."""
        return (
            datetime_.astimezone(timezone.utc).isoformat(
                sep=' ', timespec='milliseconds'
            )
            if datetime_
            else None
        )

    @staticmethod
    def dump_datetime_to_database_field(datetime_: datetime) -> str:
        return datetime_.astimezone(timezone.utc).isoformat(
            sep=' ', timespec='milliseconds'
        )

    @staticmethod
    def load_json_from_database_field(json_data: str | None, if_none=None) -> Any:
        """Decodes the JSON data `json_data` and returns the result.
        If `json_data` is None, returns `if_none`."""
        return json.loads(json_data) if json_data is not None else if_none

    @staticmethod
    def set_dict_int_keys(string_dict: dict[str, Any]) -> dict[int, Any]:
        """Maps the string keys to integer keys and returns the resulting dict.
        If `string_dict` is None, returns None."""
        # This method is needed because JSON turns all keys to strings
        return {int(k): v for k, v in string_dict.items()}

    @staticmethod
    def dump_to_json_database_field(obj: Any, if_none=None) -> str | None:
        """Serializes the given object `obj` to JSON.
        Returns the JSON serialization of `if_none` otherwise (may be None)."""
        if obj is not None:
            return json.dumps(obj)
        if if_none is not None:
            return json.dumps(if_none)
        return None

    @staticmethod
    def _get_fields_dict(data_object: Any, fields: list[str]) -> dict[str, Any]:
        """Get a dict of the attributes of a data object by name.
        Raises an AttributeError if one of the fields is not an attribute.
        Usage: database insertion for fields of a stored object."""
        return {field_: getattr(data_object, field_) for field_ in fields}

from pathlib import Path
from typing import Any
import pyodbc
from logging import Logger
from dataclasses import dataclass, field

from common.exception import PapiException
from common.logger import get_logger

logger: Logger = get_logger()


@dataclass
class AccessDatabase:
    __file: Path
    __database: pyodbc.Connection = field(init=False)
    __cursor: pyodbc.Cursor = field(init=False)

    def __post_init__(self):
        self.__database = None
        self._open()

    def _open(self):
        if self.__database is None:
            access_driver: str = 'Microsoft Access Driver (*.mdb, *.accdb)'
            if access_driver not in pyodbc.drivers():
                msg: str = 'ODBC driver installed are:'
                for driver in pyodbc.drivers():
                    msg = msg + f'\n - {driver}'
                install_url: str = 'https://www.microsoft.com/en-us/download/details.aspx?id=54920'
                msg = msg + f'\nInstall driver [{access_driver}] (cf {install_url}) and retry.'
                msg = msg + f'\nNote: for 32bits/64bits compatibility, use accessdatabaseengine_X64.exe /passive'
                raise PapiException(msg)
            db_url: str = f'DRIVER={{{access_driver}}};DBQ={self.__file.resolve()};'
            # log_info(db_url)
            try:
                self.__database = pyodbc.connect(db_url)
            except pyodbc.Error as e:
                raise PapiException(f'Connection to file {self.__file} failed: {e.args}')
            self.__cursor = self.__database.cursor()

    def _close(self):
        if self.__database is not None:
            self.__cursor.close()
            self.__database = None
            self.__cursor = None

    def _execute(self, query: str, params: tuple = ()):
        # log_info(f'query={query}')
        # log_info(f'params={params}')
        self._open()
        self.__cursor.execute(query, params)

    def _fetchall(self) -> list[dict[str, Any]]:
        self._open()
        columns = [column[0] for column in self.__cursor.description]
        results = []
        for row in self.__cursor.fetchall():
            results.append(dict(zip(columns, row)))
        return results

    def _fetchone(self) -> dict[str, Any]:
        self._open()
        columns = [column[0] for column in self.__cursor.description]
        return dict(zip(columns, self.__cursor.fetchone()))

    def _fetchval(self) -> Any:
        self._open()
        return self.__cursor.fetchval()

    def _commit(self):
        self._open()
        self.__cursor.commit()

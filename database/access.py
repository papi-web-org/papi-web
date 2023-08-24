import os
from typing import Any, Dict, List, Tuple, Optional
import pyodbc
from common.exception import PapiException
from logging import Logger
from logger import get_logger

logger: Logger = get_logger()


class AccessDatabase:

    def __init__(self, file: str):
        self.__file = file
        self.__database: Optional[pyodbc.Connection] = None
        self.__cursor: Optional[pyodbc.Cursor] = None

    def _open(self):
        if self.__database is None:
            access_driver: str = 'Microsoft Access Driver (*.mdb, *.accdb)'
            if access_driver not in pyodbc.drivers():
                msg: str = 'ODBC driver installed are:'
                for driver in pyodbc.drivers():
                    msg = msg + '\n - {}'.format(driver)
                install_url: str = 'https://www.microsoft.com/en-us/download/details.aspx?id=54920'
                msg = msg + '\nInstall driver [{}] (cf {}) and retry.'.format(
                    access_driver, install_url)
                msg = msg + '\nNote: for 32bits/64bits compatibility, use accessdatabaseengine_X64.exe /passive'
                raise PapiException(msg)
            db_url: str = 'DRIVER={{{}}};DBQ={};'.format(access_driver, os.path.relpath(self.__file))
            # log_info(db_url)
            try:
                self.__database = pyodbc.connect(db_url)
            except pyodbc.Error as e:
                raise PapiException('Connection to file {} failed: {}'.format(self.__file, e.args))
            self.__cursor = self.__database.cursor()

    def _close(self):
        if self.__database is not None:
            self.__cursor.close()
            self.__database = None
            self.__cursor = None

    def _execute(self, query: str, params: Tuple = ()):
        # log_info('query={}'.format(query))
        # log_info('params={}'.format(params))
        self._open()
        self.__cursor.execute(query, params)

    def _fetchall(self) -> List[Dict[str, Any]]:
        self._open()
        columns = [column[0] for column in self.__cursor.description]
        results = []
        for row in self.__cursor.fetchall():
            results.append(dict(zip(columns, row)))
        return results

    def _fetchone(self) -> Dict[str, Any]:
        self._open()
        columns = [column[0] for column in self.__cursor.description]
        return dict(zip(columns, self.__cursor.fetchone()))

    def _fetchval(self) -> Any:
        self._open()
        return self.__cursor.fetchval()

    def _commit(self):
        self._open()
        self.__cursor.commit()

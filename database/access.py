import time
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
    """Base class for Access-based databases."""
    file: Path
    database: pyodbc.Connection | None = field(init=False, default=None)
    cursor: pyodbc.Cursor | None = field(init=False, default=None)

    # NOTE(Amaras) This is the start of the infrastructure to build a DB as a
    # context manager (making it possible to use it using the with statement).
    # This function is responsible for opening the ressource and giving a way
    # to access it.
    def __enter__(self):
        self._open()
        return self

    # NOTE(Amaras) Context manager infrastructure: this dunder method is
    # supposed to close the ressource and handle exceptions (by catching or
    # passing them through, DO NOT re-raise exceptions here).
    def __exit__(self, exc_type, exc_value, traceback):
        self._close()

    def _open(self):
        if self.database is None:
            access_driver: str = 'Microsoft Access Driver (*.mdb, *.accdb)'
            if access_driver not in pyodbc.drivers():
                logger.error('Les pilotes ODBC installés sont les suivants :')
                for driver in pyodbc.drivers():
                    logger.error(f' - {driver}')
                logger.error(f'Pilote nécessaire : {access_driver}')
                install_url: str = 'https://www.microsoft.com/en-us/download/details.aspx?id=54920'
                logger.error(f'Installer le pilote (cf {install_url}) et relancer.')
                logger.error(f'Note : pour une compatibilité 32bits et 64bits, '
                             f'utiliser la commande suivante à l\'installation :')
                logger.error(f'accessdatabaseengine_X64.exe /passive')
                raise PapiException('Pilote Microsoft Access introuvable')
            db_url: str = f'DRIVER={{{access_driver}}};DBQ={self.file.resolve()};'
            # Get rid of unresolved pyodbc.Error: ('HY000', 'The driver did not supply an error!')
            while self.database is None:
                try:
                    self.database = pyodbc.connect(db_url)
                except pyodbc.Error as e:
                    logger.error(f'La connection au fichier {self.file} a échoué: {e.args}')
                    time.sleep(1)
            self.cursor = self.database.cursor()

    def _close(self):
        if self.database is not None:
            self.cursor.close()
            self.database = None
            self.cursor = None

    def _execute(self, query: str, params: tuple = ()):
        # log_info(f'query={query}')
        # log_info(f'params={params}')
        self._open()
        self.cursor.execute(query, params)

    def _fetchall(self) -> list[dict[str, Any]]:
        self._open()
        columns = [column[0] for column in self.cursor.description]
        results = []
        for row in self.cursor.fetchall():
            results.append(dict(zip(columns, row)))
        return results

    def _fetchone(self) -> dict[str, Any]:
        self._open()
        columns = [column[0] for column in self.cursor.description]
        return dict(zip(columns, self.cursor.fetchone()))

    def _fetchval(self) -> Any:
        self._open()
        return self.cursor.fetchval()

    def _commit(self):
        self._open()
        self.cursor.commit()

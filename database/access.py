import time
from pathlib import Path
from typing import Any, Self
from logging import Logger
from dataclasses import dataclass, field
from collections.abc import Iterator
import pyodbc

from common.exception import PapiWebException
from common.logger import get_logger

logger: Logger = get_logger()

pyodbc.pooling = False
logger.info('Pooling ODBC : %s', f"{'des' if not pyodbc.pooling else ''}activé")


@dataclass
class AccessDatabase:
    """Base class for Access-based databases."""
    file: Path
    write: bool = field(default=False)
    database: pyodbc.Connection | None = field(init=False, default=None)
    cursor: pyodbc.Cursor | None = field(init=False, default=None)

    # NOTE(Amaras) This is the start of the infrastructure to build a DB as a
    # context manager (making it possible to use it using the with statement).
    # This function is responsible for opening the ressource and giving a way
    # to access it.
    def __enter__(self) -> Self:
        needed_driver: str = access_driver()
        if needed_driver not in pyodbc.drivers():
            logger.error('Les pilotes ODBC installés sont les suivants :')
            for driver in odbc_drivers():
                logger.error(' - %s', driver)
            logger.error('Pilote nécessaire : %s', needed_driver)
            install_url: str = 'https://www.microsoft.com/en-us/download/details.aspx?id=54920'
            logger.error('Installer le pilote (cf %s) et relancer.', install_url)
            logger.error('Note : pour une compatibilité 32bits et 64bits, '
                         'utiliser la commande suivante à l\'installation :')
            logger.error('accessdatabaseengine_X64.exe /passive')
            raise PapiWebException('Pilote Microsoft Access introuvable')
        db_url: str = f'DRIVER={{{needed_driver}}};DBQ={self.file.resolve()};'
        # Get rid of unresolved pyodbc.Error: ('HY000', 'The driver did not supply an error!')
        while self.database is None:
            try:
                self.database = pyodbc.connect(db_url, readonly=not self.write)
            except pyodbc.Error as e:
                logger.error('La connection au fichier %s a échoué: %s', self.file, e.args)
                time.sleep(1)
        self.cursor = self.database.cursor()
        return self

    # NOTE(Amaras) Context manager infrastructure: this dunder method is
    # supposed to close the ressource and handle exceptions (by catching or
    # passing them through, DO NOT re-raise exceptions here).
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
        return dict(zip(columns, self.cursor.fetchone()))

    def _fetchval(self) -> Any:
        return self.cursor.fetchval()

    def _commit(self):
        self.cursor.commit()


def odbc_drivers() -> list[str]:
    return pyodbc.drivers()


def access_driver() -> str:
    return 'Microsoft Access Driver (*.mdb, *.accdb)'

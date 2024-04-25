"""A database schema based on sqlite3.

This database stores tournaments, pairings and players for now."""

from pathlib import Path
import sqlite3

class SQLiteDatabase:
    """A database using SQLite.

    This is a rework of the papi database, and stores slightly more information than
    the papi database.
    """

    def __init__(self, filename: str):
        self.filename = filename
    
    def __enter__(self) -> sqlite3.Cursor:
        self.connection = sqlite3.connect(self.filename, detect_types=1)
        self.cursor = self.connection.cursor()
        return self.cursor

    def __exit__(self, exc_type, exc_value, traceback):
        self.cursor.close()
        self.connection.close()

    @classmethod
    def create_databse(cls, filename: str):
        """Creates a database with a given filename and returns it.
        The file must not exist"""
        Path(filename).touch(exist_ok=False)
        instance = cls(filename)
        with open('create_db.sql', encoding='utf-8') as f:
            with instance as cur:
                cur.executescript(f.read())
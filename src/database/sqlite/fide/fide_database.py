import re
from contextlib import suppress
from datetime import date
from logging import Logger
from pathlib import Path
from typing import Iterator, Any, override

from packaging.version import Version

from common import BASE_DIR
from common.i18n import _
from common.i18n.utils import unicode_normalize
from common.logger import get_logger
from data.player import PlayerRating
from database.sqlite.config.config_store import StoredLocalSourceDatabase
from database.sqlite.event.event_store import StoredPlayer
from database.sqlite.local_source_database import LocalSourcePlayerDatabase
from database.sqlite.local_source_database.actions import NotifOutdatedAction
from database.sqlite.local_source_database.delays import MonthFirstDayOutdatedDelay
from utils.enum import (
    TournamentRating,
)

logger: Logger = get_logger()


class FideDatabase(LocalSourcePlayerDatabase):
    """
    The SQLite database class for FIDE players. Usage:
    1. Check if the database exists and is up-to-date.
        If outdated, the outdate action is executed:
    FideDatabase().check()
    2. Search the database:
    with FideDatabase() as fide_database:
        for player in fide_database.search_player('my name'):
            ...
    """

    @staticmethod
    def static_id() -> str:
        return 'fide'

    @staticmethod
    def static_name() -> str:
        return _('FIDE')

    @staticmethod
    def version() -> Version:
        return Version('2')

    @property
    def _source_file_name(self) -> str:
        return 'fide_players_v2.db'

    @classmethod
    def credentials_file(cls) -> Path:
        return BASE_DIR / 'src' / '.fide-database-enc-credentials'

    @classmethod
    def github_tag(cls) -> str:
        return 'fide-latest'

    def _download_source_file(self, source_file_dir: Path) -> bool:
        return self._download_enc_source_file(source_file_dir)

    @override
    @property
    def default_stored_database(self) -> StoredLocalSourceDatabase:
        return StoredLocalSourceDatabase(
            name=self.id,
            outdate_delay=MonthFirstDayOutdatedDelay.static_id(),
            outdate_action=NotifOutdatedAction.static_id(),
        )

    def read_federation_ids(self) -> Iterator[str]:
        self.execute(
            'SELECT DISTINCT federation FROM `player` ORDER BY `federation`',
            (),
        )
        yield from map(lambda row: row['federation'], self.fetchall())

    @staticmethod
    def _get_player_from_row(row: dict[str, Any]) -> StoredPlayer:
        rating_keys = {
            TournamentRating.STANDARD: ('standard_rating', 'k_standard'),
            TournamentRating.RAPID: ('rapid_rating', 'k_rapid'),
            TournamentRating.BLITZ: ('blitz_rating', 'k_blitz'),
        }
        ratings = {
            tournament_rating.value: PlayerRating(
                fide=row[rating_key] or None,
                k_factor=row.get(k_key) or None,
            ).stored_value
            for tournament_rating, (rating_key, k_key) in rating_keys.items()
        }
        return StoredPlayer(
            id=None,
            first_name=row['first_name'].title() if row['first_name'] else '',
            last_name=row['last_name'].upper(),
            year_of_birth=row['year_of_birth'],
            gender=row['gender'],
            title=row['fide_title'],
            women_title=row.get('fide_women_title') or '',
            transient_arbiter_titles={'fide': row['fide_arbiter_title']},
            ratings=ratings,
            fide_id=row['fide_id'],
            federation=row['federation'],
        )

    def search_player(
        self,
        string: str,
        federation: str,
        page: int = 0,
        limit: int | None = None,
    ) -> list[StoredPlayer]:
        tokens: list[str] = [
            unicode_normalize(token) for token in re.split(r'\s+', string)
        ]
        str_fields: tuple[tuple[str, str, str], ...] = (
            ('last_name', '%', '%'),
            ('first_name', '%', '%'),
        )
        int_fields: tuple[str, ...] = ('fide_id',)
        token_conditions: dict[str, str] = {}
        params: list[Any] = []
        for token in tokens:
            expressions = [f'({field[0]} LIKE ?)' for field in str_fields]
            params += [f'{field[1]}{token}{field[2]}' for field in str_fields]
            int_value: int
            with suppress(ValueError):
                int_value = int(token.strip())
                expressions += [f'({field} = ?)' for field in int_fields]
                params += [
                    int_value,
                ] * len(int_fields)
            token_conditions[token] = ' OR '.join(expressions)
        conditions: str = ' AND '.join(
            map(lambda condition: f'({condition})', token_conditions.values())
        )

        # We build one CASE block that sorts best → worst
        order_clauses = []
        for token in tokens:
            order_clauses.append("""
                CASE
                    WHEN last_name LIKE ? AND federation = ? THEN 0
                    WHEN first_name LIKE ? AND federation = ? THEN 1
                    WHEN (last_name LIKE ? OR first_name LIKE ?) THEN 2
                    WHEN federation = ? THEN 3
                    ELSE 4
                END
            """)

            # Params for this token in the same order
            params += [
                f'{token}%',
                federation,
                f'{token}%',
                federation,
                f'{token}%',
                f'{token}%',
                federation,
            ]

        order_expr = ' + '.join(order_clauses)

        query: str = f"""
            SELECT *
            FROM player
            WHERE {conditions}
            ORDER BY {order_expr}, last_name, first_name
        """

        if limit:
            query += ' LIMIT ?'
            params += [
                limit,
            ]
        if page and limit:
            query += ' OFFSET ?'
            params += [
                page * limit,
            ]

        self.execute(query, tuple(params))
        return [self._get_player_from_row(row) for row in self.fetchall()]

    def get_stored_player_by_fide_id(self, player_fide_id: int) -> StoredPlayer | None:
        self.execute('SELECT * FROM `player` WHERE `fide_id` = ?', (player_fide_id,))
        if player_row := self.fetchone():
            return self._get_player_from_row(player_row)
        return None

    def covers_rating_period(self, day: date) -> bool:
        """Whether the installed database is the rating list of *day*'s period.

        FIDE publishes a rating list on the 1st of every month, so the list
        installed during a given month is the one that applies to the
        tournaments of that month."""
        if not self.exists():
            return False
        updated_at = self.updated_at
        if updated_at is None:
            return False
        return (updated_at.year, updated_at.month) == (day.year, day.month)

    def get_stored_players_by_fide_id(
        self, player_fide_ids: list[int]
    ) -> list[StoredPlayer]:
        query_array = ', '.join('?' for _ in player_fide_ids)
        self.execute(
            f'SELECT * FROM player WHERE fide_id IN ({query_array})',
            tuple(player_fide_ids),
        )
        return [self._get_player_from_row(row) for row in self.fetchall()]

    # ---------------------------------------------------------------------------------
    # Legacy
    # ---------------------------------------------------------------------------------

    @property
    def legacy_min_recovery_version(self) -> Version | None:
        # Pre-version-5 databases use the version 1 schema, which lacks the
        # columns of the current schema, so they cannot be recovered.
        return None

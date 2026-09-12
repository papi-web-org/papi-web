import re
from contextlib import suppress
from datetime import datetime, date
from logging import Logger
from pathlib import Path
from typing import Any, override

from packaging.version import Version
from text_unidecode import unidecode

from common.i18n import _
from common.i18n.utils import unicode_normalize
from common.logger import get_logger
from data.player import PlayerRating
from database.sqlite.config.config_store import StoredLocalSourceDatabase
from database.sqlite.event.event_store import StoredPlayer
from database.sqlite.local_source_database import LocalSourcePlayerDatabase
from database.sqlite.local_source_database.actions import NotifOutdatedAction
from database.sqlite.local_source_database.delays import Days2OutdatedDelay
from plugins import ffe
from plugins.ffe import PLUGIN_NAME
from plugins.ffe.utils import PlayerFFELicence, FfePlayerPluginData
from utils.enum import (
    TournamentRating,
    PlayerRatingType,
    PlayerGender,
    PlayerTitle,
)

logger: Logger = get_logger()


class FfeDatabase(LocalSourcePlayerDatabase):
    """
    The SQLite database class for FFE players. Usage:
    1. Check if the database exists and is up-to-date.
        If outdated, the outdate action is executed:
    FfeDatabase().check()
    2. Search the database:
    with FfeDatabase() as ffe_database:
        for player in ffe_database.search_player('my name'):
            ...
    """

    @staticmethod
    def static_id() -> str:
        return 'ffe'

    @staticmethod
    def static_name() -> str:
        return _('FFE')

    @staticmethod
    def version() -> Version:
        return Version('1')

    @property
    def _source_file_name(self) -> str:
        return 'ffe_players_v1.db'

    @classmethod
    def credentials_file(cls) -> Path:
        return ffe.PLUGIN_DIR / '.database-enc-credentials'

    @classmethod
    def github_tag(cls) -> str:
        return 'ffe-latest'

    def _download_source_file(self, source_file_dir: Path) -> bool:
        return self._download_enc_source_file(source_file_dir)

    @override
    @property
    def default_stored_database(self) -> StoredLocalSourceDatabase:
        return StoredLocalSourceDatabase(
            name=self.id,
            outdate_delay=Days2OutdatedDelay.static_id(),
            outdate_action=NotifOutdatedAction.static_id(),
        )

    @staticmethod
    def get_stored_player_from_row(row: dict[str, Any]) -> StoredPlayer:
        fide_title = PlayerTitle(row['fide_title'])
        return StoredPlayer(
            id=0,
            first_name=row['first_name'].title() if row['first_name'] else '',
            last_name=row['last_name'].upper(),
            date_of_birth=datetime.strptime(row['date_of_birth'], '%Y-%m-%d').date(),
            gender=PlayerGender(row['gender']),
            title=fide_title.open_value,
            women_title=fide_title.women_value,
            ratings={
                TournamentRating.STANDARD.value: PlayerRating.from_type(
                    row['standard_rating'],
                    PlayerRatingType(row['standard_rating_type']),
                ).stored_value,
                TournamentRating.RAPID.value: PlayerRating.from_type(
                    row['rapid_rating'], PlayerRatingType(row['rapid_rating_type'])
                ).stored_value,
                TournamentRating.BLITZ.value: PlayerRating.from_type(
                    row['blitz_rating'], PlayerRatingType(row['blitz_rating_type'])
                ).stored_value,
            },
            fide_id=int(row['fide_id']) if row['fide_id'] else None,
            federation=row['federation'],
            club=row['club'],
            transient_arbiter_titles={'ffe': row['ffe_arbiter_title']},
            plugin_data={
                PLUGIN_NAME: FfePlayerPluginData(
                    ffe_id=row['ffe_id'],
                    ffe_licence=PlayerFFELicence(row['ffe_licence']),
                    ffe_licence_number=row['ffe_licence_number'],
                    league=row['league'],
                ).to_stored_value()
            },
        )

    def search_player(
        self,
        string: str,
        federation: str,
        page: int = 0,
        limit: int | None = None,
        filters: dict | None = None,
    ) -> list[StoredPlayer]:
        tokens: list[str] = [
            unicode_normalize(token) for token in re.split(r'\s+', string)
        ]
        str_fields: tuple[tuple[str, str, str], ...] = (
            ('last_name', '%', '%'),
            ('first_name', '%', '%'),
            ('ffe_licence_number', '', ''),
        )
        int_fields: tuple[str, ...] = ('fide_id',)
        filter_conditions, filter_params = self._process_filters(filters or {})
        token_conditions: dict[str, str] = {}
        params: list[Any] = list(filter_params)
        for token in tokens:
            expressions = [f'({field[0]} LIKE ?)' for field in str_fields]
            params += [f'{field[1]}{token}{field[2]}' for field in str_fields]
            with suppress(ValueError):
                int_value = int(token.strip())
                expressions += [f'({field} = ?)' for field in int_fields]
                params += [
                    int_value,
                ] * len(int_fields)
            token_conditions[token] = ' OR '.join(expressions)
        conditions: str = ' AND '.join(
            filter_conditions
            + list(map(lambda condition: f'({condition})', token_conditions.values()))
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

        self.execute(
            query,
            tuple(params),
        )

        return [self.get_stored_player_from_row(row) for row in self.fetchall()]

    def _get_stored_player_by_id(self, field: str, id_: int) -> StoredPlayer | None:
        self.execute(f'SELECT * FROM `player` WHERE {field} = ?', (id_,))
        if row := self.fetchone():
            return self.get_stored_player_from_row(row)
        else:
            return None

    def get_stored_player_by_ffe_id(
        self,
        player_ffe_id: int,
    ) -> StoredPlayer | None:
        return self._get_stored_player_by_id('ffe_id', player_ffe_id)

    def get_stored_player_by_fide_id(
        self,
        player_fide_id: int,
    ) -> StoredPlayer | None:
        return self._get_stored_player_by_id('fide_id', player_fide_id)

    def get_stored_players_by_licence_numbers(
        self, licence_numbers: list[str]
    ) -> list[StoredPlayer]:
        query_array = ', '.join('?' for _ in licence_numbers)
        self.execute(
            f'SELECT * FROM `player` WHERE `ffe_licence_number` IN ({query_array})',
            tuple(licence_numbers),
        )
        return [self.get_stored_player_from_row(row) for row in self.fetchall()]

    def get_stored_players_by_fide_ids(self, fide_ids: list[int]) -> list[StoredPlayer]:
        query_array = ', '.join('?' for _ in fide_ids)
        self.execute(
            f'SELECT * FROM player WHERE fide_id IN ({query_array})',
            tuple(fide_ids),
        )
        return [self.get_stored_player_from_row(row) for row in self.fetchall()]

    def get_stored_players_by_name_keys(
        self, name_keys: list[tuple[str, str, date]]
    ) -> list[StoredPlayer]:
        query_array = ', '.join('(?, ?, ?)' for _ in name_keys)
        params: list[str] = []
        for name_key in name_keys:
            params += [
                unidecode(name_key[0]),
                unidecode(name_key[1]),
                self.dump_date_to_database_field(name_key[2]) or '',
            ]
        self.execute(
            'SELECT * FROM player '
            f'WHERE (last_name, first_name, date_of_birth) IN ({query_array})',
            tuple(params),
        )
        return [self.get_stored_player_from_row(row) for row in self.fetchall()]

    @classmethod
    def _process_filters(cls, filters: dict) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if 'ffe_licence_filter' in filters:
            if filters['ffe_licence_filter'] == 'B':
                conditions.append("(ffe_licence IN ('B', 'A') OR federation !='FRA')")
            elif filters['ffe_licence_filter'] == 'A':
                conditions.append("(ffe_licence='A' OR federation !='FRA')")
        if 'federation_filter' in filters:
            conditions.append('federation = ?')
            params.append(filters['federation_filter'])
        if 'gender_filter' in filters:
            conditions.append('gender = ?')
            params.append(filters['gender_filter'])
        if 'ffe_league_filter' in filters:
            conditions.append('league = ?')
            params.append(filters['ffe_league_filter'])
        if 'club_filter' in filters:
            club: str = filters['club_filter']
            conditions.append('LOWER(club) LIKE LOWER(?)')
            params.append(f'%{club}%')
        if filters.get('year_of_birth_filter', None):
            age_conditions: list[str] = []
            for min_year, max_year in filters['year_of_birth_filter']:
                match min_year, max_year:
                    case None, None:
                        continue
                    case None, _:
                        age_conditions.append("strftime('%Y', date_of_birth) <= ?")
                        params.append(str(max_year))
                    case _, None:
                        age_conditions.append("strftime('%Y', date_of_birth) >= ?")
                        params.append(str(min_year))
                    case _, _:
                        age_conditions.append(
                            "strftime('%Y', date_of_birth) BETWEEN ? AND ?"
                        )
                        params += [str(min_year), str(max_year)]
            if age_conditions:
                conditions.append(f'({" OR ".join(age_conditions)})')
        return conditions, params

    # ---------------------------------------------------------------------------------
    # Legacy
    # ---------------------------------------------------------------------------------

    @property
    def legacy_min_recovery_version(self) -> Version:
        # Last change done in https://github.com/Sharly-Chess/sharly-chess/pull/1739
        return Version('3.6.0')

    @staticmethod
    def _legacy_dir() -> Path:
        return Path('tmp') / PLUGIN_NAME

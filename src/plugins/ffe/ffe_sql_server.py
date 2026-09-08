import itertools
import re
from contextlib import suppress
from datetime import datetime, date
from logging import Logger
from pathlib import Path
from typing import Any

from text_unidecode import unidecode

from common.exception import SharlyChessException
from common.i18n import _
from common.i18n.utils import unicode_normalize
from common.logger import get_logger
from common.network import NetworkMonitor
from data.player import PlayerRating
from database.sql_server.sql_server import SqlServer, SqlServerCredentials
from database.sqlite.event.event_store import StoredPlayer
from plugins import PLUGINS_DIR
from plugins.ffe import PLUGIN_NAME
from plugins.ffe.papi_mappers import (
    PapiPlayerTitle,
    PapiPlayerGender,
    PapiPlayerRatingType,
    PapiPlayerFFELicence,
)
from plugins.ffe.utils import FfePlayerPluginData, PlayerFFELicence
from utils.enum import TournamentRating, PlayerRatingType

logger: Logger = get_logger()


class FFESqlServer(SqlServer):
    TIMEOUT = 10
    CREDENTIALS_FILE: Path = PLUGINS_DIR / 'ffe' / '.sql-server-credentials'

    def __init__(self):
        super().__init__(self.CREDENTIALS_FILE, timeout=self.TIMEOUT)
        if not NetworkMonitor.connected():
            error: str = _('No internet connection')
            logger.error(error)
            raise SharlyChessException(error)

    @classmethod
    def dump_credentials(
        cls,
        host: str,
        user: str,
        password: str,
        database: str,
    ):
        SqlServerCredentials.dump(
            cls.CREDENTIALS_FILE,
            host,
            user,
            password,
            database,
        )

    PLAYER_FIELDS: tuple[str, ...] = (
        'Ref',
        'NrFFE',
        'Nom',
        'Prenom',
        'Sexe',
        'NeLe',
        'Cat',
        # not allowed: 'EC', 'Adresse', 'CP', 'TelDom', 'TelBur', 'TelPort', 'Fax', 'EMail',
        'Federation',
        'ClubRef',
        # not allowed: 'OldClubRef', 'Mute',
        'Elo',
        # not allowed: 'Elo10', 'Fide10', 'Elo01', 'Fide01',
        # not needed 'Elo03',
        'Fide03',  # RapideFide
        'Elo06',  # Blitz
        'Fide06',  # BlitzFide
        'Rapide',
        # not allowed: 'Perf', 'NbrParties', 'FideNbrParties',
        'Fide',
        'FideCode',
        'FideTitre',
        'AffType',
        # not needed 'Actif',
        # not allowed: 'BordereauRef', 'OldAffType', 'OldBordereauRef',
        # not allowed: 'Suspendu', 'MuteState', 'AJoue',
        # not allowed: 'Revue', 'RevueDu', 'RevueDuParClub', 'RevueDebut', 'NewsLetter',
        # not allowed: 'Password', 'MaJ',
    )

    CLUB_FIELDS: tuple[str, ...] = (
        # unused 'Ref',
        # unused 'NrFFE',
        'Nom',
        # not allowed: 'Intitule',
        'Commune',
        # not allowed: 'CommuneRef', 'ComiteRef',
        'Ligue',
        # not allowed: 'Adresse', 'CP', 'SalleAdresse', 'SalleCP', 'Latitude', 'Longitude',
        # not allowed: 'Tel', 'Fax', 'EMail', 'URL',
        # not needed 'Actif',
        # not allowed: 'Ouverture', 'President', 'Secretaire', 'Tresorier', 'Technique', 'Jeune',
        # not allowed: 'WebAdmin', 'WebAdminEMail', 'WebAutorisation',
        # not allowed: 'Repport', 'Nouveau', 'Electeur', 'Situation', 'PrefNr', 'PrefDate', 'Prefecture',
        # not allowed: 'NbrAffPrecedent', 'NbrBPrecedent', 'NbrAffA', 'NbrAffB', 'NbrJourOuvre',
        # not allowed: 'DivisionAdulte', 'DivisionJeune', 'DivisionFeminine', 'Label', 'Imprimer',
        # not allowed: 'Edoc', 'Handicape', 'QPV', 'Palmares', 'Login', 'Password', 'MaJ',
    )

    @staticmethod
    def _get_stored_player_from_row(row: dict[str, Any]) -> StoredPlayer:
        date_of_birth: date | None = None
        dob = row['NeLe']
        if isinstance(dob, datetime):
            date_of_birth = dob.date()
        elif isinstance(dob, date):
            date_of_birth = dob

        fide_title = PapiPlayerTitle.get_core_object(row['FideTitre'] or '')
        return StoredPlayer(
            id=None,
            first_name=row['Prenom'].title() if row['Prenom'] else '',
            last_name=row['Nom'].upper(),
            date_of_birth=date_of_birth,
            gender=PapiPlayerGender.get_core_object(row['Sexe']),
            title=fide_title.open_value,
            women_title=fide_title.women_value,
            ratings={
                TournamentRating.STANDARD.value: PlayerRating.from_type(
                    row['Elo'], PapiPlayerRatingType.get_core_object(row['Fide'])
                ).stored_value,
                TournamentRating.RAPID.value: PlayerRating.from_type(
                    row['Rapide'], PapiPlayerRatingType.get_core_object(row['Fide03'])
                ).stored_value,
                TournamentRating.BLITZ.value: PlayerRating.from_type(
                    row['Elo06'], PapiPlayerRatingType.get_core_object(row['Fide06'])
                ).stored_value,
            },
            fide_id=int(row['FideCode'].strip("' ")) if row['FideCode'] else 0,
            federation=row['Federation'],
            club=row['ClubNom'] if row['ClubNom'] else '',
            plugin_data={
                PLUGIN_NAME: FfePlayerPluginData(
                    ffe_id=row['Ref'],
                    ffe_licence=PapiPlayerFFELicence.get_core_object(
                        row['AffType'] or '', row['NrFFE']
                    ),
                    ffe_licence_number=row['NrFFE'],
                    league=row['ClubLigue'],
                ).to_stored_value()
            },
        )

    def get_player_fields(self) -> list[str]:
        return [f'joueur.{f} AS {f}' for f in self.PLAYER_FIELDS]

    def get_club_fields(self) -> list[str]:
        return [f'club.{f} AS Club{f}' for f in self.CLUB_FIELDS]

    RATING_TYPE_CONDITION: str = f'joueur.Fide IN ({", ".join(map(lambda s: f"'{s}'", [PlayerRatingType.ESTIMATED, PlayerRatingType.NATIONAL, PlayerRatingType.FIDE]))})'

    @staticmethod
    def string_matches_fide_id(string: str) -> int | None:
        return int(string) if string.isdecimal() else None

    @staticmethod
    def remote_fide_id_format_1(fide_id: int) -> str:
        return str(fide_id).rjust(8, '0').ljust(10, ' ')

    @staticmethod
    def remote_fide_id_format_2(fide_id: int) -> str:
        return f"'{fide_id}'"

    async def search_player(
        self,
        string: str,
        federation: str,
        page: int = 0,
        limit: int | None = None,
        filters: dict | None = None,
    ) -> list[StoredPlayer]:
        """Searches the SQL server for the given tokens, raises SharlyChessException on error."""
        # NOTE(Amaras): Quicken search if the string looks like a complete FFE
        # licence number, so that it skips a more complex request
        string = string.upper().strip()
        if PlayerFFELicence.validate(string):
            return await self.get_stored_players_by_licence_numbers([string])
        if fide_id := self.string_matches_fide_id(string):
            return await self.get_players_by_fide_id([fide_id])
        tokens: list[str] = [
            unicode_normalize(token) for token in re.split(r'\s+', string)
        ]
        str_fields: tuple[tuple[str, str, str], ...] = (
            ('joueur.Nom', '%', '%'),
            ('joueur.Prenom', '%', '%'),
            ('joueur.NrFFE', '', ''),
        )
        filter_conditions, filter_params = self._process_filters(filters or {})
        conditions: list[str] = [
            self.RATING_TYPE_CONDITION,
            *filter_conditions,
        ]
        params: list[Any] = list(filter_params)
        for token in tokens:
            token_expressions: list[str] = [
                f'(UPPER({field[0]}) LIKE %s)' for field in str_fields
            ]
            token_params: list[str | int] = [
                f'{field[1]}{token}{field[2]}' for field in str_fields
            ]
            with suppress(ValueError):
                int_value = int(token.strip())
                token_expressions.append('(joueur.FideCode IN (%s, %s))')
                token_params += [
                    self.remote_fide_id_format_1(int_value),
                    self.remote_fide_id_format_2(int_value),
                ]
            conditions += [
                ' OR '.join(token_expressions),
            ]
            params += token_params
        condition: str = ' AND '.join(map(lambda c: f'({c})', conditions))

        # We build one CASE block that sorts best → worst
        order_clauses = []
        for token in tokens:
            order_clauses.append("""
                CASE
                    WHEN UPPER(joueur.Nom) LIKE %s AND federation = %s THEN 0
                    WHEN UPPER(joueur.Prenom) LIKE %s AND federation = %s THEN 1
                    WHEN UPPER(joueur.Nom) LIKE %s OR UPPER(joueur.Prenom) LIKE %s THEN 2
                    WHEN federation = %s THEN 3
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
        return await self._get_stored_players_by_condition(
            condition,
            params,
            order_by=f'{order_expr}, Joueur.Nom, Joueur.Prenom',
            limit=limit,
            offset=page * limit if limit else None,
        )

    async def _get_stored_player_by_condition(
        self, condition: str, params: list
    ) -> StoredPlayer | None:
        query: str = (
            f'SELECT {", ".join(self.get_player_fields() + self.get_club_fields())} '
            f'FROM joueur LEFT JOIN club on joueur.ClubRef = club.Ref '
            f'WHERE {condition} AND {self.RATING_TYPE_CONDITION}'
        )
        await self.execute(query, tuple(params))
        if row := await self.fetchone():
            return self._get_stored_player_from_row(row)
        else:
            return None

    async def _get_stored_players_by_condition(
        self,
        condition: str,
        params: list,
        order_by: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> list[StoredPlayer]:
        query: str = (
            f'SELECT {", ".join(self.get_player_fields() + self.get_club_fields())} '
            f'FROM joueur LEFT JOIN club on joueur.ClubRef = club.Ref '
            f'WHERE ({condition}) AND {self.RATING_TYPE_CONDITION}'
        )
        if order_by:
            query += f' ORDER BY {order_by}'
        if offset is not None:
            query += ' OFFSET %s ROWS'
            params.append(offset)
            if limit:
                query += ' FETCH NEXT %s ROWS ONLY'
                params.append(limit)
        await self.execute(query, tuple(params))
        return [self._get_stored_player_from_row(row) async for row in self.fetchall()]

    async def get_stored_player_by_ffe_id(
        self,
        player_ffe_id: int,
    ) -> StoredPlayer | None:
        return await self._get_stored_player_by_condition(
            'joueur.Ref = %s', [player_ffe_id]
        )

    async def get_stored_player_by_fide_id(
        self,
        player_fide_id: int,
    ) -> StoredPlayer | None:
        return await self._get_stored_player_by_condition(
            'joueur.FideCode IN (%s, %s)',
            [
                self.remote_fide_id_format_1(player_fide_id),
                self.remote_fide_id_format_2(player_fide_id),
            ],
        )

    async def get_stored_players_by_licence_numbers(
        self, licence_numbers: list[str]
    ) -> list[StoredPlayer]:
        return await self._get_stored_players_by_condition(
            f'joueur.NrFFE IN ({", ".join(["%s"] * len(licence_numbers))})',
            licence_numbers,
        )

    async def get_stored_players_by_fide_ids(
        self, fide_ids: list[int]
    ) -> list[StoredPlayer]:
        return await self._get_stored_players_by_condition(
            f'joueur.FideCode IN ({", ".join(["%s"] * len(fide_ids) * 2)})',
            list(
                itertools.chain.from_iterable(
                    [
                        self.remote_fide_id_format_1(fide_id),
                        self.remote_fide_id_format_2(fide_id),
                    ]
                    for fide_id in fide_ids
                )
            ),
        )

    # The query scales fast, so it is required to paginate the results
    # A page of 30 is about a 5 seconds query (half the timeout)
    NAME_KEYS_PAGE_SIZE = 30

    async def _get_stored_players_by_name_keys_page(
        self, name_keys: list[tuple[str, str, date]]
    ):
        name_str_keys: list[str] = []
        name_dob_str_keys: list[str] = []
        for name_key in name_keys:
            name_str_key = '|'.join(
                (unidecode(name_key[0]).upper(), unidecode(name_key[1]).upper())
            )
            name_str_keys.append(name_str_key)
            name_dob_str_keys.append(
                '|'.join((name_str_key, name_key[2].strftime('%Y-%m-%d')))
            )
        name_query = "UPPER(joueur.Nom) + '|' + UPPER(Joueur.Prenom)"
        query_array = ', '.join('%s' for _ in name_keys)
        stored_players = await self._get_stored_players_by_condition(
            f'{name_query} IN ({query_array})',
            name_str_keys,
        )
        # DOB formatting is too expensive in SQL Server, we have to do the
        # matching only on the name, and match the DOB in python
        return [
            stored_player
            for stored_player in stored_players
            if stored_player.date_of_birth
            and '|'.join(
                (
                    stored_player.last_name.upper(),
                    (stored_player.first_name or '').upper(),
                    stored_player.date_of_birth.strftime('%Y-%m-%d'),
                )
            )
            in name_dob_str_keys
        ]

    async def get_stored_players_by_name_keys(
        self, name_keys: list[tuple[str, str, date]]
    ) -> list[StoredPlayer]:
        stored_players: list[StoredPlayer] = []
        while name_keys:
            stored_players += await self._get_stored_players_by_name_keys_page(
                name_keys[: self.NAME_KEYS_PAGE_SIZE]
            )
            name_keys = name_keys[self.NAME_KEYS_PAGE_SIZE :]
        return stored_players

    async def get_players_by_fide_id(
        self,
        player_fide_ids: list[int],
    ) -> list[StoredPlayer]:
        params: list[str] = []
        for player_fide_id in player_fide_ids:
            params += [
                self.remote_fide_id_format_1(player_fide_id),
                self.remote_fide_id_format_2(player_fide_id),
            ]
        return await self._get_stored_players_by_condition(
            f'joueur.FideCode IN ({", ".join(["%s"] * 2 * len(player_fide_ids))})',
            params,
        )

    @staticmethod
    def _process_filters(filters: dict) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if 'ffe_licence_filter' in filters:
            if filters['ffe_licence_filter'] == 'B':
                conditions.append(
                    "(joueur.AffType IN ('B', 'A') OR joueur.Federation !='fra')"
                )
            elif filters['ffe_licence_filter'] == 'A':
                conditions.append("(joueur.AffType='A' OR joueur.Federation !='fra')")
        if 'federation_filter' in filters:
            conditions.append('joueur.Federation = %s')
            params.append(filters['federation_filter'])
        if 'gender_filter' in filters:
            conditions.append('joueur.Sexe = %s')
            params.append(filters['gender_filter'])
        if 'ffe_league_filter' in filters:
            conditions.append('club.Ligue = %s')
            params.append(filters['ffe_league_filter'])
        if 'club_filter' in filters:
            club: str = filters['club_filter']
            conditions.append('LOWER(club.Nom) LIKE LOWER(%s)')
            params.append(f'%{club}%')
        if filters.get('year_of_birth_filter', None):
            age_conditions = []
            for min_year, max_year in filters['year_of_birth_filter']:
                match min_year, max_year:
                    case None, None:
                        continue
                    case None, _:
                        age_conditions.append('YEAR(joueur.NeLe) <= %s')
                        params.append(max_year)
                    case _, None:
                        age_conditions.append('YEAR(joueur.NeLe) >= %s')
                        params.append(min_year)
                    case _, _:
                        age_conditions.append('YEAR(joueur.NeLe) BETWEEN %s AND %s')
                        params += [min_year, max_year]
            if age_conditions:
                conditions.append(f'({" OR ".join(age_conditions)})')
        return conditions, params

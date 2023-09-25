from pathlib import Path
from logging import Logger

from database.access import AccessDatabase
from data.pairing import Pairing
from data.player import Player, PLAYER_TITLE_VALUES, COLOR_DB_VALUES
from common.logger import get_logger

logger: Logger = get_logger()

RESULT_NOT_PAIRED: int = 0              # forfeit (opp is None, not paired)
RESULT_LOSS: int = 1                    # loss (opp > 1)
RESULT_DRAW_OR_BYE_05: int = 2          # draw (opp > 1) or bye 0.5pt (opp is None)
RESULT_GAIN: int = 3                    # won (opp > 1)
RESULT_FORFEIT_LOSS: int = 4            # forfeit (opp > 1, paired)
RESULT_DOUBLE_FORFEIT: int = 5          # double forfeit (opp > 1)
RESULT_EXE_FORFEIT_GAIN_BYE_1: int = 6  # exempt (opp == 1), forfeit won (opp > 1), bye 1pt (opp is None)

RESULT_STRINGS: dict[int, str] = {
    RESULT_NOT_PAIRED: '',
    RESULT_LOSS: '0-1',
    RESULT_DRAW_OR_BYE_05: '1/2',
    RESULT_GAIN: '1-0',
    RESULT_FORFEIT_LOSS: '1-F',
    RESULT_DOUBLE_FORFEIT: 'F-F',
    RESULT_EXE_FORFEIT_GAIN_BYE_1: '1-F',
}

TOURNAMENT_PAIRING_STANDARD: int = 1
TOURNAMENT_PAIRING_HALEY: int = 2
TOURNAMENT_PAIRING_HALEY_SOFT: int = 3
TOURNAMENT_PAIRING_SAD: int = 4
TOURNAMENT_PAIRING_DB_VALUES: dict[int, str] = {
    TOURNAMENT_PAIRING_STANDARD: 'Standard',
    TOURNAMENT_PAIRING_HALEY: 'Haley',
    TOURNAMENT_PAIRING_HALEY_SOFT: 'HaleySoft',
    TOURNAMENT_PAIRING_SAD: 'SAD',
}
TOURNAMENT_PAIRING_VALUES: dict[str, int] = {v: k for k, v in TOURNAMENT_PAIRING_DB_VALUES.items()}
TOURNAMENT_PAIRING_STRINGS: dict[int, str] = {
    TOURNAMENT_PAIRING_STANDARD: 'Standard',
    TOURNAMENT_PAIRING_HALEY: 'Haley',
    TOURNAMENT_PAIRING_HALEY_SOFT: 'Haley Dégressif',
    TOURNAMENT_PAIRING_SAD: 'Système Accéléré Dégressif',
}

TOURNAMENT_RATING_STANDARD: int = 1
TOURNAMENT_RATING_RAPID: int = 2
TOURNAMENT_RATING_BLITZ: int = 3
TOURNAMENT_RATING_DB_FIELDS: dict[int, str] = {
    TOURNAMENT_RATING_STANDARD: 'Elo',
    TOURNAMENT_RATING_RAPID: 'Rapide',
    TOURNAMENT_RATING_BLITZ: 'Blitz',
}
TOURNAMENT_RATING_VALUES: dict[str, int] = {v: k for k, v in TOURNAMENT_RATING_DB_FIELDS.items()}
TOURNAMENT_RATING_STRINGS: dict[int, str] = {
    TOURNAMENT_RATING_STANDARD: 'Standard',
    TOURNAMENT_RATING_RAPID: 'Rapide',
    TOURNAMENT_RATING_BLITZ: 'Blitz',
}
TOURNAMENT_RATING_TYPE_DB_FIELDS: dict[int, str] = {
    TOURNAMENT_RATING_STANDARD: 'Fide',
    TOURNAMENT_RATING_RAPID: 'RapideFide',
    TOURNAMENT_RATING_BLITZ: 'BlitzFide',
}


class PapiDatabase(AccessDatabase):

    def __init__(self, file: Path):
        super().__init__(file)
        '''self.__player_fields: list[str] = [
            'Ref',
            'RefFFE',
            'Nr',
            'NrFFE',
            'Nom', 'Prenom', 'Sexe', 'NeLe',
            'Cat', 'Elo', 'Rapide', 'Blitz',
            'Federation', 'ClubRef', 'Club', 'Ligue',
            'Fide', 'RapideFide', 'BlitzFide',
            'FideCode', 'FideTitre',
            'AffType',
            'Pointe', 'InscriptionRegle', 'InscriptionDu',
            'Adresse', 'CP', 'Tel', 'EMail', 'Commentaire',
            'Pts', 'PtA', 'PtF', 'Dep1', 'Dep2', 'Dep3',
            'Place', 'Perf', 'Board', 'Fixe', 'Flotteur',
        ]
        for round in range(24):
            for suffix in ['Cl', 'Adv', 'Res']:
                self.__player_fields.append('Rd' + str(round + 1).zfill(2) + suffix)'''

    '''def update(self, event: str, city: str, start_date: str, end_date: str, rounds_number: int, arbiter: str):
        query: str = 'UPDATE info SET `Value` = ? WHERE Variable = ?'
        # log_info(f'query={query}')
        self._execute(query, (event, 'Nom', ))
        self._execute(query, (city, 'Lieu'))
        self._execute(query, (start_date, 'DateDebut', ))
        self._execute(query, (end_date, 'DateFin', ))
        self._execute(query, (str(rounds_number), 'NbrRondes', ))
        self._execute(query, (arbiter, 'Arbitre', ))
        self._commit()'''

    def _query(self, query: str, params: tuple = ()):
        self._execute(query, params)
        self._commit()

    def close(self):
        self._close()

    def __read_var(self, name) -> str:
        query: str = 'SELECT Value FROM INFO WHERE Variable = ?'
        self._execute(query, (name, ))
        return self._fetchval()

    def read_info(self) -> tuple[int, int, int, int, int, ]:
        rounds: int = int(self.__read_var('NbrRondes'))
        pairing: int = TOURNAMENT_PAIRING_VALUES[self.__read_var('Pairing')]
        rating: int = TOURNAMENT_RATING_VALUES[self.__read_var('ClassElo')]
        rating_limit1: int = int(self.__read_var('EloBase1'))
        rating_limit2: int = int(self.__read_var('EloBase2'))
        return rounds, pairing, rating, rating_limit1, rating_limit2

    def read_players(self, rating: int, rounds: int) -> dict[int, Player]:
        players: dict[int, Player] = {}
        player_fields: list[str] = [
            'Ref', 'Nom', 'Prenom', 'Sexe', 'FideTitre', 'Fixe',
            'Elo', 'Rapide', 'Blitz', 'Fide', 'RapideFide', 'BlitzFide',
        ]
        for round in range(1, rounds + 1):
            for suffix in ['Cl', 'Adv', 'Res']:
                player_fields.append('Rd' + str(round).zfill(2) + suffix)
        query: str = f'SELECT {", ".join(player_fields)} FROM joueur ORDER BY Ref'
        self._execute(query)
        for row in self._fetchall():
            pairings: dict[int, Pairing] = {}
            for round in range(1, rounds + 1):
                color: str = row['Rd' + str(round).zfill(2) + 'Cl']
                if color in COLOR_DB_VALUES:
                    color = COLOR_DB_VALUES[color]
                pairings[round] = Pairing(
                    color, row['Rd' + str(round).zfill(2) + 'Adv'],
                    row['Rd' + str(round).zfill(2) + 'Res'])
            players[row['Ref']] = Player(
                row['Ref'], row['Nom'] if row['Nom'] else '', row['Prenom'] if row['Prenom'] else '', row['Sexe'],
                PLAYER_TITLE_VALUES[row['FideTitre'].strip()],
                row[TOURNAMENT_RATING_DB_FIELDS[rating]],
                row[TOURNAMENT_RATING_TYPE_DB_FIELDS[rating]],
                row['Fixe'], pairings)
        return players

    def add_result(self, player_id: int, round: int, result: int):
        query: str = f'UPDATE joueur SET Rd{str(round).zfill(2)}Res = ? WHERE Ref = ?'
        self._query(query, (result, player_id, ))

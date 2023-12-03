import hashlib
import json
import time
from json import JSONDecodeError
from logging import Logger
from pathlib import Path

import chardet

from chessevent.chessevent_session import ChessEventSession
from common.config_reader import TMP_DIR
from common.logger import get_logger, print_interactive, input_interactive
from common.papi_web_config import PapiWebConfig
from common.singleton import singleton
from data.chessevent_tournament import ChessEventTournament
from data.event import Event
from data.tournament import Tournament
from database.papi_template import create_empty_papi_database
from ffe.ffe_session import FFESession

logger: Logger = get_logger()


@singleton
class ActionSelector:

    def __init__(self, config: PapiWebConfig):
        self.__config = config

    @classmethod
    def __get_chessevent_tournaments(cls, event: Event) -> list[Tournament]:
        if not event.tournaments:
            return []
        tournaments: list[Tournament] = []
        for tournament in event.tournaments.values():
            if not tournament.chessevent_tournament_name:
                logger.warning(f'Connexion à Chess Event non définie pour le tournoi [{tournament.id}]')
            elif not tournament.file:
                logger.warning(f'Fichier non défini pour le tournoi [{tournament.id}]')
            elif tournament.current_round:
                logger.warning(f'Le tournoi [{tournament.id}] est déjà commencé')
            else:
                tournaments.append(tournament)
        return tournaments

    def run(self, event_id: str) -> bool:
        event: Event = Event(event_id, False)
        logger.info(f'Évènement : {event.name}')
        tournaments: list[Tournament] = self.__get_chessevent_tournaments(event)
        if not tournaments:
            logger.error(f'La création des fichiers Papi n\'est possible pour aucun tournoi')
            return False
        logger.info(f'Tournois : {", ".join([str(tournament.name) for tournament in tournaments])}')
        print_interactive(f'Actions :')
        print_interactive(f'  - [C] Créer les fichiers Papi')
        print_interactive(f'  - [U] Créer les fichiers Papi et les envoyer sur le site fédéral')
        print_interactive(f'  - [Q] Revenir à la liste des évènements')
        action_choice: str | None = None
        while not action_choice:
            action_choice = input_interactive(f'Entrez votre choix : ').upper()
        if action_choice == 'Q':
            return False
        if action_choice in ['C', 'U']:
            if action_choice == 'C':
                logger.info(f'Action : création des fichiers Papi')
            else:
                logger.info(f'Action : création des fichiers Papi et envoi sur le site fédéral')
            print_interactive(f'Fréquence :')
            print_interactive(f'  - [1] Une seule fois')
            print_interactive(f'  - [C] En continu')
            print_interactive(f'  - [A] Abandonner')
            times_choice: str | None = None
            while not times_choice:
                times_choice = input_interactive(f'Entrez votre choix : ').upper()
            if times_choice == 'A':
                return False
            if times_choice in ['1', 'C']:
                try:
                    chessevent_timeout_min: int = 10
                    chessevent_timeout_max: int = 180
                    chessevent_timeout: int = chessevent_timeout_min
                    while True:
                        for tournament in tournaments:
                            data: str | None = ChessEventSession(tournament).read_data()
                            if data is None:
                                continue
                            encoding = chardet.detect(data.encode())['encoding']
                            if encoding == 'MacRoman':
                                logger.warning(f'MacRoman encoding detected, assuming utf-8.')
                                encoding = 'utf-8'
                            chessevent_tournament_info: dict[str, str | int | list[dict[bool | str, str | int | None]]]
                            data = '\n'.join([line for line in data.split('\n')])
                            try:
                                chessevent_tournament_info = json.loads(data)
                            except JSONDecodeError as jde:
                                error_output: Path = (
                                        TMP_DIR / event.id /
                                        f'{tournament.id}_error_l{jde.lineno}_c{jde.colno}_p{jde.pos}.json'
                                )
                                error_output.parents[0].mkdir(parents=True, exist_ok=True)
                                with open(error_output, 'w') as f:
                                    f.write(data)
                                logger.error(f'les données du tournoi (encodage {encoding}) n\'ont pas pu être '
                                             f'décodées, elles ont été sauvegardées dans le fichier {error_output} '
                                             f'(erreur ligne {jde.lineno}, colonne {jde.colno}, position {jde.pos})')
                                continue
                            data_md5 = hashlib.md5(data.encode('utf-8')).hexdigest()
                            try:
                                with open(tournament.chessevent_download_marker, 'r') as f:
                                    if data_md5 == f.read():
                                        logger.info(f'Les données du tournoi [{tournament.name}] sur Chess Event '
                                                    f'n\'ont pas été modifiées.')
                                        continue
                            except FileNotFoundError:
                                pass
                            chessevent_tournament = ChessEventTournament(chessevent_tournament_info)
                            if chessevent_tournament.error:
                                continue
                            chessevent_timeout = chessevent_timeout_min
                            tournament.file.unlink(missing_ok=True)
                            create_empty_papi_database(tournament.file)
                            players_number: int = tournament.write_chessevent_info_to_database(chessevent_tournament)
                            logger.info(f'Le fichier {tournament.file} a été créé ({players_number} joueur·euses).')
                            tournament.chessevent_download_marker.parents[0].mkdir(parents=True, exist_ok=True)
                            with open(tournament.chessevent_download_marker, 'w') as f:
                                f.write(data_md5)
                            if action_choice == 'U':
                                if not tournament.ffe_id or not tournament.ffe_password:
                                    logger.warning(f'Identifiants de connexion au site fédéral non définis pour le '
                                                   f'tournoi [{tournament.name}], l\'envoi sur le site fédéral est '
                                                   f'impossible')
                                else:
                                    FFESession(tournament).upload(set_visible=True)
                        if times_choice == '1':
                            return True
                        time.sleep(chessevent_timeout)
                        chessevent_timeout = min(chessevent_timeout_max, int(chessevent_timeout * 1.2))
                        tournaments: list[Tournament] = self.__get_chessevent_tournaments(event)
                        if not tournaments:
                            logger.error(f'Plus aucun tournoi n\'est éligible pour la création des fichiers Papi')
                            return False
                except KeyboardInterrupt:
                    return False
        return True

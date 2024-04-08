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
from database.papi_template import create_empty_papi_database, PAPI_VERSIONS
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
                logger.warning('Connexion à Chess Event non définie pour le tournoi [%s]', tournament.id)
            elif not tournament.file:
                logger.warning('Fichier non défini pour le tournoi [%s]', tournament.id)
            elif tournament.current_round:
                logger.warning('Le tournoi [%s] est déjà commencé', tournament.id)
            else:
                tournaments.append(tournament)
        return tournaments

    def run(self, event_id: str) -> bool:
        event: Event = Event(event_id, False)
        logger.info('Évènement : %s', event.name)
        tournaments: list[Tournament] = self.__get_chessevent_tournaments(event)
        if not tournaments:
            logger.error('La création des fichiers Papi n\'est possible pour aucun tournoi')
            return False
        logger.info('Tournois : %s', ", ".join(map(lambda t: str(t.name), tournaments)))
        print_interactive('Actions :')
        print_interactive('  - [C] Créer les fichiers Papi')
        print_interactive('  - [U] Créer les fichiers Papi et les envoyer sur le site fédéral')
        print_interactive('  - [Q] Revenir à la liste des évènements')
        action_choice: str | None = None
        while action_choice not in ['C', 'U', 'Q', ]:
            action_choice = input_interactive('Entrez votre choix (par défaut C) : ').upper() or 'C'
        if action_choice == 'Q':
            return False
        if action_choice in ['C', 'U']:
            if action_choice == 'C':
                logger.info('Action : création des fichiers Papi')
            else:
                logger.info('Action : création des fichiers Papi et envoi sur le site fédéral')
            print_interactive('Fréquence :')
            print_interactive('  - [1] Une seule fois')
            print_interactive('  - [C] En continu')
            print_interactive('  - [A] Abandonner')
            times_choice: str | None = None
            while times_choice not in ['1', 'C', 'A', ]:
                times_choice = input_interactive('Entrez votre choix (par défaut 1) : ').upper() or '1'
            if times_choice == 'A':
                return False
            if times_choice in ['1', 'C']:
                if len(PAPI_VERSIONS) > 1:
                    default_papi_version = PAPI_VERSIONS[-1]
                    print_interactive('Version de Papi :')
                    version_choices = [str(i + 1) for i in range(len(PAPI_VERSIONS))] + ['A', ]
                    for i in range(len(PAPI_VERSIONS)):
                        print_interactive(f'  - [{i + 1}] {PAPI_VERSIONS[i]}')
                    print_interactive('  - [A] Abandonner')
                    version_choice: str | None = None
                    while version_choice not in version_choices:
                        version_choice = input_interactive(
                            f'Entrez votre choix (par défaut {len(PAPI_VERSIONS)} = {default_papi_version}) : ').upper()
                        if not version_choice:
                            version_choice = str(len(PAPI_VERSIONS))
                    if version_choice == 'A':
                        return False
                    papi_version = PAPI_VERSIONS[int(version_choice) - 1]
                else:
                    papi_version = PAPI_VERSIONS[-1]
                logger.info('Version de Papi : %s', papi_version)
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
                                logger.warning('MacRoman encoding detected, assuming utf-8.')
                                encoding = 'utf-8'
                            chessevent_tournament_info: dict[str, str | int | list[dict[bool | str, str | int | None]]]
                            # NOTE(Amaras) what does this accomplish?
                            data = '\n'.join([line for line in data.split('\n')])
                            try:
                                chessevent_tournament_info = json.loads(data)
                            except JSONDecodeError as jde:
                                error_output: Path = (
                                        TMP_DIR / event.id /
                                        f'{tournament.id}_error_l{jde.lineno}_c{jde.colno}_p{jde.pos}.json'
                                )
                                error_output.parents[0].mkdir(parents=True, exist_ok=True)
                                with open(error_output, 'w', encoding="utf-8") as f:
                                    f.write(data)
                                logger.error('les données du tournoi (encodage %s) n\'ont pas pu être '
                                             'décodées, elles ont été sauvegardées dans le fichier %s '
                                             '(erreur ligne %s, colonne %s, position %s)',
                                             encoding, error_output, jde.lineno, jde.colno, jde.pos)
                                continue
                            # NOTE(Amaras) we should probably use another hashing algorithm
                            # MD5 has been proven unsecure, even for this usecase.
                            # I recommend something like SHA-2 (not proven unsecure yet).
                            data_md5 = hashlib.md5(data.encode('utf-8')).hexdigest()
                            try:
                                with open(tournament.chessevent_download_marker, 'r', encoding='utf-8)') as f:
                                    if data_md5 == f.read() and tournament.file.exists():
                                        logger.info('Les données du tournoi [%s] sur Chess Event '
                                                    'n\'ont pas été modifiées.',
                                                    tournament.name)
                                        continue
                            except FileNotFoundError:
                                pass
                            chessevent_tournament = ChessEventTournament(chessevent_tournament_info)
                            if chessevent_tournament.error:
                                continue
                            chessevent_timeout = chessevent_timeout_min
                            tournament.file.unlink(missing_ok=True)
                            create_empty_papi_database(tournament.file, papi_version)
                            players_number: int = tournament.write_chessevent_info_to_database(chessevent_tournament)
                            logger.info('Le fichier %s a été créé (%s joueur·euses).',
                                        tournament.file, players_number)
                            tournament.chessevent_download_marker.parents[0].mkdir(parents=True, exist_ok=True)
                            with open(tournament.chessevent_download_marker, 'w', encoding='utf-8') as f:
                                f.write(data_md5)
                            if action_choice == 'U':
                                if not tournament.ffe_id or not tournament.ffe_password:
                                    logger.warning('Identifiants de connexion au site fédéral non définis pour le '
                                                   'tournoi [%s], l\'envoi sur le site fédéral est '
                                                   'impossible.',
                                                   tournament.name)
                                else:
                                    FFESession(tournament).upload(set_visible=True)
                        if times_choice == '1':
                            return True
                        time.sleep(chessevent_timeout)
                        chessevent_timeout = min(chessevent_timeout_max, int(chessevent_timeout * 1.2))
                        tournaments: list[Tournament] = self.__get_chessevent_tournaments(event)
                        if not tournaments:
                            logger.error('Plus aucun tournoi n\'est éligible pour la création des fichiers Papi.')
                            return False
                except KeyboardInterrupt:
                    return False
        return True

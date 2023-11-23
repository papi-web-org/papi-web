import json
import time
from datetime import datetime
from logging import Logger
from pathlib import Path

from chessevent.chessevent_session import ChessEventSession
from common.config_reader import TMP_DIR
from common.logger import get_logger, print_interactive, input_interactive
from common.papi_web_config import PapiWebConfig
from common.singleton import singleton
from data.event import Event
from data.tournament import Tournament
from data.util import ChessEventTournament
from database.papi_template import create_empty_papi_database

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
            if not tournament.chessevent_tournament_id:
                logger.warning(f'Connexion à Chess Event non définie pour le tournoi [{tournament.id}]')
            elif not tournament.file:
                logger.warning(f'Fichier non défini pour le tournoi [{tournament.id}]')
            else:
                tournaments.append(tournament)
        return tournaments

    def run(self, event_id: str) -> bool:
        event: Event = Event(event_id)
        print_interactive(f'Évènement : {event.name}')
        tournaments = self.__get_chessevent_tournaments(event)
        if not tournaments:
            logger.error(f'Aucun tournoi éligible pour la création des fichiers Papi pour cet évènement')
            return False
        choice: str | None = None
        print_interactive(f'Tournois : {", ".join([str(tournament.name) for tournament in tournaments])}')
        print_interactive(f'Actions :')
        print_interactive(f'  - [C] Créer les fichiers Papi des tournois')
        print_interactive(f'  - [Q] Revenir à la liste des évènements')
        while choice is None:
            choice = input_interactive(f'Entrez votre choix : ').upper()
        if choice == 'Q':
            return False
        if choice == 'C':
            print_interactive(f'Action : création des fichiers Papi des tournois')
            for tournament in tournaments:
                print_interactive(f'Tournoi : {tournament.name}')
                data: str | None = ChessEventSession(tournament).read_data()
                if data is None:
                    continue
                chessevent_tournament_info: dict[str, str | int | list[dict[bool | str, str | int | None]]]
                chessevent_tournament_info = json.loads(data)
                chessevent_tournament = ChessEventTournament(chessevent_tournament_info)
                if chessevent_tournament.error:
                    continue
                if tournament.file.exists():
                    choice: str = input_interactive(
                        f'Le fichier {tournament.file} existe, voulez-vous le remplacer [o/n] ? ')
                    if choice.upper() != 'O':
                        continue
                    date: str = datetime.fromtimestamp(time.time()).strftime("%Y%m%d%H%M%S")
                    save: Path = TMP_DIR / f'{tournament.file.stem}-{date}{tournament.file.suffix}'
                    try:
                        tournament.file.rename(save)
                    except PermissionError as pe:
                        logger.error(f'L\'erreur suivante a été rencontrée : {pe}.')
                        logger.error(f'Le fichier {tournament.file} ne peut être sauvegardé.')
                        continue
                    logger.info(f'Le fichier {tournament.file} a été sauvegardé sous {save}.')
                create_empty_papi_database(tournament.file)
                players_number: int = tournament.write_chessevent_info_to_database(chessevent_tournament)
                logger.info(f'Le fichier {tournament.file} a été créé ({players_number} joueur·euses).')
            return True
        return True

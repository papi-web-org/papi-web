import time
from typing import List, Optional
from logging import Logger

from common.logger import get_logger, print_interactive, input_interactive
from common.papi_web_config import PapiWebConfig
from common.singleton import singleton
from data.event import Event
from data.tournament import Tournament
from ffe.ffe_session import FFESession

logger: Logger = get_logger()


@singleton
class ActionSelector:

    def __init__(self, config: PapiWebConfig):
        self.__config = config

    @classmethod
    def __get_qualified_tournaments(cls, event: Event) -> List[Tournament]:
        if not event.tournaments:
            return []
        tournaments: List[Tournament] = []
        for tournament in event.tournaments.values():
            if not tournament.ffe_id or not tournament.ffe_password:
                logger.warning(f'Identifiants de connexion FFE non définis pour le tournoi [{tournament.id}]')
            else:
                tournaments.append(tournament)
        return tournaments

    @classmethod
    def __get_qualified_tournaments_with_file(cls, event: Event) -> List[Tournament]:
        if not event.tournaments:
            return []
        tournaments: List[Tournament] = []
        for tournament in event.tournaments.values():
            if not tournament.ffe_id or not tournament.ffe_password:
                logger.warning(f'Identifiants de connexion non définis pour le tournoi [{tournament.id}]')
            elif not tournament.file:
                logger.warning(f'Fichier non trouvé pour le tournoi [{tournament.id}]')
            else:
                tournaments.append(tournament)
        return tournaments

    def run(self, event_id: str) -> bool:
        event: Event = Event(event_id)
        print_interactive(f'Evènement : {event.name}')
        tournaments = self.__get_qualified_tournaments(event)
        if not tournaments:
            logger.error(f'Aucun tournoi éligible aux opérations FFE pour cet évènement')
            return False
        choice: Optional[str] = None
        print_interactive(f'Tournois : {", ".join([str(tournament.ffe_id) for tournament in tournaments])}')
        print_interactive(f'Actions :')
        print_interactive(f'  - [T] Tester les codes d\'accès des tournois')
        print_interactive(f'  - [V] Rendre les tournois visibles sur le site fédéral')
        print_interactive(f'  - [H] Télécharger les factures d\'homologation')
        print_interactive(f'  - [U] Mettre en ligne les tournois')
        print_interactive(f'  - [Q] Revenir à la liste des évènements')
        while choice is None:
            choice = input_interactive(f'Entrez votre choix : ').upper()
        if choice == 'Q':
            return False
        if choice == 'T':
            print_interactive(f'Action : test des codes d\'accès')
            tournaments = self.__get_qualified_tournaments(Event(event_id))
            if not tournaments:
                logger.error(f'Aucun tournoi éligible pour cette action')
                return True
            for tournament in tournaments:
                FFESession(tournament).test()
            return True
        if choice == 'V':
            print_interactive(f'Action : affichage des tournois en ligne')
            tournaments = self.__get_qualified_tournaments_with_file(Event(event_id))
            if not tournaments:
                logger.error(f'Aucun tournoi éligible pour cette action')
                return True
            for tournament in tournaments:
                FFESession(tournament).upload(set_visible=True)
            return True
        if choice == 'H':
            print_interactive(f'Action : téléchargement des factures d\'homologation')
            tournaments = self.__get_qualified_tournaments(Event(event_id))
            if not tournaments:
                logger.error(f'Aucun tournoi éligible pour cette action')
                return True
            for tournament in tournaments:
                FFESession(tournament).get_fees()
            return True
        if choice == 'U':
            print_interactive(f'Action : mise en ligne des résultats')
            try:
                while True:
                    tournaments = self.__get_qualified_tournaments_with_file(Event(event_id))
                    if not tournaments:
                        logger.error(f'Aucun tournoi éligible pour cette action')
                        return True
                    updated_tournaments: List[Tournament] = []
                    for tournament in tournaments:
                        upload: bool
                        if not tournament.ffe_upload_marker.is_file():
                            upload = True
                        else:
                            marker_time = tournament.ffe_upload_marker.lstat().st_mtime
                            if marker_time > tournament.file.lstat().st_mtime:
                                # last version already uploaded
                                upload = False
                            elif marker_time < time.time() + self.__config.ffe_upload_delay:
                                # last upload too recent
                                upload = False
                            else:
                                upload = True
                        if upload:
                            updated_tournaments.append(tournament)
                    if not updated_tournaments:
                        logger.info(f'Tous les tournois sont à jour')
                    for tournament in updated_tournaments:
                        FFESession(tournament).upload(set_visible=False)
                    time.sleep(10)
            except KeyboardInterrupt:
                logger.info(f'Fin de la mise en ligne')
                return True
        return True

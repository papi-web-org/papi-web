import time
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
    def __get_qualified_tournaments(cls, event: Event) -> list[Tournament]:
        if not event.tournaments:
            return []
        tournaments: list[Tournament] = []
        for tournament in event.tournaments.values():
            if not tournament.ffe_id or not tournament.ffe_password:
                logger.warning(f'Identifiants de connexion FFE non définis pour le tournoi [{tournament.id}]')
            else:
                tournaments.append(tournament)
        return tournaments

    @classmethod
    def __get_qualified_tournaments_with_existing_file(cls, event: Event) -> list[Tournament]:
        if not event.tournaments:
            return []
        tournaments: list[Tournament] = []
        for tournament in event.tournaments.values():
            if not tournament.ffe_id or not tournament.ffe_password:
                logger.warning(f'Identifiants de connexion non définis pour le tournoi [{tournament.id}]')
            elif not tournament.file:
                logger.warning(f'Fichier non défini pour le tournoi [{tournament.id}]')
            elif not tournament.file.exists():
                logger.warning(f'Fichier non trouvé pour le tournoi [{tournament.id}]')
            else:
                tournaments.append(tournament)
        return tournaments

    def run(self, event_id: str) -> bool:
        event: Event = Event(event_id, False)
        logger.info(f'Évènement : {event.name}')
        tournaments = self.__get_qualified_tournaments(event)
        if not tournaments:
            logger.error(f'Aucun tournoi éligible aux opérations FFE pour cet évènement')
            return False
        choice: str | None = None
        logger.info(f'Tournois : {", ".join([str(tournament.ffe_id) for tournament in tournaments])}')
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
            logger.info(f'Action : test des codes d\'accès')
            tournaments = self.__get_qualified_tournaments(Event(event_id, False))
            if not tournaments:
                logger.error(f'Aucun tournoi éligible pour cette action')
                return True
            for tournament in tournaments:
                FFESession(tournament).test()
            return True
        if choice == 'V':
            logger.info(f'Action : affichage des tournois en ligne')
            tournaments = self.__get_qualified_tournaments_with_existing_file(Event(event_id, False))
            if not tournaments:
                logger.error(f'Aucun tournoi éligible pour cette action')
                return True
            for tournament in tournaments:
                FFESession(tournament).upload(set_visible=True)
            return True
        if choice == 'H':
            logger.info(f'Action : téléchargement des factures d\'homologation')
            tournaments = self.__get_qualified_tournaments(Event(event_id, False))
            if not tournaments:
                logger.error(f'Aucun tournoi éligible pour cette action')
                return True
            for tournament in tournaments:
                FFESession(tournament).get_fees()
            return True
        if choice == 'U':
            (logger.info(f'Action : mise en ligne des résultats'))
            try:
                while True:
                    tournaments = self.__get_qualified_tournaments_with_existing_file(Event(event_id, False))
                    if not tournaments:
                        logger.error(f'Aucun tournoi éligible pour cette action')
                        return True
                    updated_tournaments: list[Tournament] = []
                    for tournament in tournaments:
                        if tournament.ffe_upload_needed(self.__config.ffe_upload_delay):
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

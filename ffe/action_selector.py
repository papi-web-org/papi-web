import os.path
import time
from typing import List, Optional
from logging import Logger

from common.logger import get_logger, print_interactive, input_interactive
from data.event import Event
from data.tournament import Tournament
from ffe.ffe_session import FFESession

logger: Logger = get_logger()


class ActionSelector:

    @classmethod
    def __get_qualified_tournaments(cls, event: Event) -> List[Tournament]:
        if not event.tournaments:
            return []
        tournaments: List[Tournament] = []
        for tournament in event.tournaments.values():
            if not tournament.ffe_id or not tournament.ffe_password:
                logger.warning('Identifiants de connexion FFE non définis pour le tournoi [{}]'.format(tournament.id))
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
                logger.warning('Identifiants de connexion non définis pour le tournoi [{}]'.format(tournament.id))
            elif not tournament.file:
                logger.warning('Fichier non trouvé pour le tournoi [{}]'.format(tournament.id))
            else:
                tournaments.append(tournament)
        return tournaments

    @classmethod
    def run(cls, event_id: str) -> bool:
        event: Event = Event(event_id)
        print_interactive('Evènement : {}'.format(event.name))
        tournaments = cls.__get_qualified_tournaments(event)
        if not tournaments:
            logger.error('Aucun tournoi éligible aux opérations FFE pour cet évènement')
            return False
        choice: Optional[str] = None
        print_interactive('Tournois : {}'.format(', '.join([str(tournament.ffe_id) for tournament in tournaments])))
        print_interactive('Actions :')
        print_interactive('  - [T] Tester les codes d\'accès des tournois')
        print_interactive('  - [V] Rendre les tournois visibles sur le site fédéral')
        print_interactive('  - [H] Télécharger les factures d\'homologation')
        print_interactive('  - [U] Mettre en ligne les tournois')
        print_interactive('  - [Q] Revenir à la liste des évènements')
        while choice is None:
            choice = input_interactive('Entrez votre choix : ').upper()
        if choice == 'Q':
            return False
        if choice == 'T':
            print_interactive('Action : test des codes d\'accès')
            tournaments = cls.__get_qualified_tournaments(Event(event_id))
            if not tournaments:
                logger.error('Aucun tournoi éligible pour cette action')
                return True
            for tournament in tournaments:
                FFESession(tournament).test()
            return True
        if choice == 'V':
            print_interactive('Action : affichage des tournois en ligne')
            tournaments = cls.__get_qualified_tournaments_with_file(Event(event_id))
            if not tournaments:
                logger.error('Aucun tournoi éligible pour cette action')
                return True
            for tournament in tournaments:
                FFESession(tournament).upload(set_visible=True)
            return True
        if choice == 'H':
            print_interactive('Action : téléchargement des factures d\'homologation')
            tournaments = cls.__get_qualified_tournaments(Event(event_id))
            if not tournaments:
                logger.error('Aucun tournoi éligible pour cette action')
                return True
            for tournament in tournaments:
                FFESession(tournament).get_fees()
            return True
        if choice == 'U':
            print_interactive('Action : mise en ligne des résultats')
            while True:
                tournaments = cls.__get_qualified_tournaments_with_file(Event(event_id))
                if not tournaments:
                    logger.error('Aucun tournoi éligible pour cette action')
                    return True
                updated_tournaments: List[Tournament] = []
                for tournament in tournaments:
                    upload: bool
                    if not os.path.isfile(tournament.ffe_upload_marker):
                        upload = True
                    elif os.path.getmtime(tournament.file) <= os.path.getmtime(tournament.ffe_upload_marker):
                        upload = False
                    elif time.time() <= os.path.getmtime(tournament.file) + 5:
                        upload = False
                    else:
                        upload = True
                    if upload:
                        updated_tournaments.append(tournament)
                if not updated_tournaments:
                    logger.info('Tous les tournois sont à jour')
                for tournament in updated_tournaments:
                    FFESession(tournament).upload(set_visible=False)
                time.sleep(10)

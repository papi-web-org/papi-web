import os.path
import time
from typing import List, Optional
from logging import Logger

from common.logger import get_logger
from data.event import Event
from data.tournament import Tournament
from ffe.ffe_session import FFESession

logger: Logger = get_logger()


class ActionSelector:
    def __init__(self, event: Event):
        self.__event: Event = event

    def run(self) -> bool:
        if not self.__event.tournaments:
            logger.error('Aucun tournoi défini pour cet évènement')
            return False
        tournaments: List[Tournament] = []
        for tournament in self.__event.tournaments.values():
            if tournament.ffe_id:
                tournaments.append(tournament)
            else:
                logger.warning('L\'identifiant FFE (ffe_id) du tournoi [{}] n\'est pas défini'.format(tournament.id))
        if not tournaments:
            logger.error('Aucun tournoi avec un identifiant FFE défini pour cet évènement')
            return False
        logger.info('Tournois : {}'.format(
            ', '.join([(str(tournament.ffe_id) + ' (' + tournament.file + ')') for tournament in tournaments])))
        logger.info('Actions :')
        logger.info('  - [T] Tester les codes d\'accès des tournois')
        logger.info('  - [V] Rendre les tournois visibles sur le site fédéral')
        logger.info('  - [H] Télécharger les factures d\'homologation')
        logger.info('  - [U] Mettre en ligne les tournois')
        logger.info('  - [Q] Revenir à la liste des évènements')
        choice: Optional[str] = None
        while choice is None:
            logger.info('Entrez votre choix :')
            choice = input().strip().upper()
            if choice == 'Q':
                return False
            if choice == 'T':
                for tournament in tournaments:
                    FFESession(tournament).test()
            elif choice == 'V':
                for tournament in tournaments:
                    FFESession(tournament).set_visible()
            if choice == 'H':
                for tournament in tournaments:
                    FFESession(tournament).get_fees()
            if choice == 'U':
                while True:
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
                        FFESession(tournament).upload()
                    time.sleep(10)
        return True

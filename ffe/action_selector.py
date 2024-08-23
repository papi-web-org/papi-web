import time
from logging import Logger

from common.logger import get_logger, print_interactive, input_interactive
from common.papi_web_config import PapiWebConfig
from common.singleton import singleton
from data.event import NewEvent
from data.loader import EventLoader
from data.tournament import NewTournament
from data.util import NeedsUpload
from ffe.ffe_session import FFESession

logger: Logger = get_logger()


@singleton
class ActionSelector:

    @classmethod
    def __get_qualified_tournaments(cls, event: NewEvent) -> list[NewTournament]:
        if not event.tournaments_by_id:
            return []
        tournaments: list[NewTournament] = []
        for tournament in event.tournaments_by_id.values():
            if not tournament.ffe_id or not tournament.ffe_password:
                logger.warning('Identifiants de connexion FFE non définis pour le tournoi [%s]', tournament.uniq_id)
            else:
                tournaments.append(tournament)
        return tournaments

    @classmethod
    def __get_qualified_tournaments_with_existing_file(cls, event: NewEvent) -> list[NewTournament]:
        if not event.tournaments_by_id:
            return []
        tournaments: list[NewTournament] = []
        for tournament in event.tournaments_by_id.values():
            if not tournament.ffe_id or not tournament.ffe_password:
                logger.warning('Identifiants de connexion non définis pour le tournoi [%s]', tournament.uniq_id)
            elif not tournament.file:
                logger.warning('Fichier non défini pour le tournoi [%s]', tournament.uniq_id)
            elif not tournament.file.exists():
                logger.warning('Fichier non trouvé pour le tournoi [%s]', tournament.uniq_id)
            else:
                tournaments.append(tournament)
        return tournaments

    def run(self, event_uniq_id: str) -> bool:
        event_loader: EventLoader = EventLoader()
        event: NewEvent = event_loader.load_event(event_uniq_id, reload=True)
        logger.info('Évènement : %s', event.name)
        tournaments = self.__get_qualified_tournaments(event)
        if not tournaments:
            logger.error('Aucun tournoi éligible aux opérations FFE pour cet évènement')
            return False
        choice: str | None = None
        logger.info('Tournois : %s', ", ".join((str(tournament.ffe_id) for tournament in tournaments)))
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
            logger.info('Action : test des codes d\'accès')
            tournaments = self.__get_qualified_tournaments(event_loader.load_event(event_uniq_id, reload=True))
            if not tournaments:
                logger.error('Aucun tournoi éligible pour cette action')
                return True
            for tournament in tournaments:
                FFESession(tournament).test()
            return True
        if choice == 'V':
            logger.info('Action : affichage des tournois en ligne')
            tournaments = self.__get_qualified_tournaments_with_existing_file(event_loader.load_event(event_uniq_id, reload=True))
            if not tournaments:
                logger.error('Aucun tournoi éligible pour cette action')
                return True
            for tournament in tournaments:
                FFESession(tournament).upload(set_visible=True)
            return True
        if choice == 'H':
            logger.info('Action : téléchargement des factures d\'homologation')
            tournaments = self.__get_qualified_tournaments(event_loader.load_event(event_uniq_id, reload=True))
            if not tournaments:
                logger.error('Aucun tournoi éligible pour cette action')
                return True
            for tournament in tournaments:
                FFESession(tournament).get_fees()
            return True
        if choice == 'U':
            (logger.info('Action : mise en ligne des résultats'))
            ffe_upload_delay: int = PapiWebConfig().ffe_upload_delay
            try:
                while True:
                    tournaments = self.__get_qualified_tournaments_with_existing_file(
                        event_loader.load_event(event_uniq_id, reload=True))
                    if not tournaments:
                        logger.error('Aucun tournoi éligible pour cette action')
                        return True
                    updated_tournaments: list[NewTournament] = []
                    recently_updated_tournaments: int = 0
                    for tournament in tournaments:
                        needs_upload: NeedsUpload = tournament.ffe_upload_needed
                        match needs_upload:
                            case NeedsUpload.YES:
                                updated_tournaments.append(tournament)
                            case NeedsUpload.RECENT_CHANGE:
                                recently_updated_tournaments += 1
                            case NeedsUpload.NO_CHANGE:
                                pass
                    if not updated_tournaments:
                        if recently_updated_tournaments == 0:
                            logger.info('Tous les tournois sont à jour')
                        else:
                            logger.info(
                                f'{recently_updated_tournaments} tournoi(s) a(ont) été modifié(s) il y a moins de '
                                f'{ffe_upload_delay} secondes, temporisation en cours')
                    for tournament in updated_tournaments:
                        FFESession(tournament).upload(set_visible=False)
                    time.sleep(10)
            except KeyboardInterrupt:
                logger.info('Fin de la mise en ligne')
                return True
        return True

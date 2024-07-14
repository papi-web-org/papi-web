from logging import Logger
from random import randrange, shuffle
from threading import Thread
from webbrowser import open  # pylint: disable=redefined-builtin

from common.logger import get_logger
from common.engine import Engine
from data.board import Board
from data.event import Event
from data.util import ScreenType

logger: Logger = get_logger()


class StressEngine(Engine):
    def __init__(self, event_id: str):
        super().__init__()
        event: Event = Event(event_id, True)
        if event.errors:
            logger.error('Erreur au chargement de l\'évènement [%s] :', event_id)
            for error in event.errors:
                logger.error('- %s', error)
            return
        screen_id: str | None = None
        for screen in event.screens.values():
            if screen.type == ScreenType.Boards and screen.update:
                screen_id = screen.id
                break
        if screen_id is None:
            logger.error('Aucun écran de saisie trouvé pour l\'évènement [%s].', event_id)
            return
        urls: list[str] = []
        for tournament in event.tournaments.values():
            if not tournament.file.exists():
                logger.error(
                    'Le fichier [%s] du tournoi [%s] est introuvable, tournoi ignoré.',
                    tournament.file, tournament.uniq_id)
                continue
            if not tournament.current_round:
                logger.error('Aucune ronde trouvée pour le tournoi [%s], tournoi ignoré.', tournament.uniq_id)
                continue
            tournament_boards: list[Board] = [board for board in tournament.boards if not board.result]
            if not tournament_boards:
                logger.error(
                    'Aucun échiquier sans résultat à la ronde %s '
                    'pour le tournoi [%s], tournoi ignoré.',
                    tournament.current_round, tournament.uniq_id)
                continue
            urls.extend(
                [self.result_url(event_id, screen_id, tournament.uniq_id, board.id) for board in tournament_boards])
            logger.info(
                '%s résultats préparés pour le tournoi [%s].',
                len(tournament_boards), tournament.uniq_id)
        shuffle(urls)
        for url in urls:
            Thread(target=self.enter_result, args=(url, )).start()

    def result_url(self, event_id: str, screen_id: str, tournament_uniq_id: str, board_id: int) -> str:
        return (f'http://localhost:{self._config.web_port}'
                f'/result/{event_id}/{screen_id}/{tournament_uniq_id}/{board_id}/{randrange(3) + 1}')

    @staticmethod
    def enter_result(url: str):
        logger.info('Opening the welcome page [%s] in a browser...', url)
        open(url, new=2)

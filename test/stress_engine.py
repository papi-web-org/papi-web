from logging import Logger
from random import randrange, shuffle
from threading import Thread

from common.logger import get_logger
from common.engine import Engine
from data.board import Board
from data.event import Event
from webbrowser import open
from data.util import ScreenType

logger: Logger = get_logger()


class StressEngine(Engine):
    def __init__(self, event_id: str):
        super().__init__()
        event: Event = Event(event_id, True)
        if event.errors:
            logger.error(f'Erreur au chargement de l\'évènement [{event_id}] :')
            for error in event.errors:
                logger.error(f'- {error}')
            return
        screen_id: str | None = None
        for screen in event.screens.values():
            if screen.type == ScreenType.Boards and screen.update:
                screen_id = screen.id
                break
        if screen_id is None:
            logger.error(f'Aucun écran de saisie trouvé pour l\'évènement [{event_id}].')
            return
        urls: list[str] = []
        for tournament in event.tournaments.values():
            if not tournament.file.exists():
                logger.error(
                    f'Le fichier [{tournament.file}] du tournoi [{tournament.id}] est introuvable, tournoi ignoré.')
                continue
            if not tournament.current_round:
                logger.error(f'Aucune ronde trouvée pour le tournoi [{tournament.id}], tournoi ignoré.')
                continue
            tournament_boards: list[Board] = [board for board in tournament.boards if not board.result]
            if not tournament_boards:
                logger.error(
                    f'Aucun échiquier sans résultat à la ronde {tournament.current_round} '
                    f'pour le tournoi [{tournament.id}], tournoi ignoré.')
                continue
            urls.extend([self.result_url(event_id, screen_id, tournament.id, board.id) for board in tournament_boards])
            logger.info(
                f'{len(tournament_boards)} résultats préparés pour le tournoi [{tournament.id}].')
        shuffle(urls)
        for url in urls:
            Thread(target=self.enter_result, args=(url, )).start()

    def result_url(self, event_id: str, screen_id: str, tournament_id: str, board_id: int) -> str:
        return (f'http://localhost:{self._config.web_port}'
                f'/result/{event_id}/{screen_id}/{tournament_id}/{board_id}/{randrange(3) + 1}')

    @staticmethod
    def enter_result(url: str):
        logger.info(f'Opening the welcome page [{url}] in a browser...')
        open(url, new=2)

from typing import List, Optional
from data.event import Event
from ffe.action_selector import ActionSelector
from logging import Logger
from logger import get_logger

logger: Logger = get_logger()


class EventSelector:
    def __init__(self, events: List[Event]):
        self.__events: List[Event] = events

    def run(self):
        if not self.__events:
            logger.error('Aucun fichier de configuration d\'évènement trouvé')
            return False
        event_num: Optional[int] = None
        if len(self.__events) == 1:
            event_num = 1
            logger.info('Un seul évènement trouvé, tapez Entrée pour continuer (Q pour quitter) ')
            if input().strip().upper() == 'Q':
                return False
        else:
            event_range = range(1, len(self.__events) + 1)
            for num in event_range:
                event: Event = self.__events[num - 1]
                logger.info('[{}] {} ({}.ini)'.format(num, event.name, event.id))
            while event_num is None:
                logger.info('Veuillez entrer le numéro de votre évènement (ou [Q] pour quitter) : ')
                choice: str = input().strip().upper()
                if choice == 'Q':
                    return False
                try:
                    event_num = int(choice)
                    if event_num not in event_range:
                        event_num = None
                except ValueError:
                    pass
        event: Event = self.__events[event_num - 1]
        logger.info('Evènement : {}'.format(event.name))
        while ActionSelector(Event(event.id)).run():
            pass

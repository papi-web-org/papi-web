from typing import List, Optional
from logging import Logger

from common.singleton import singleton
from common.logger import get_logger, print_interactive, input_interactive
from data.event import Event, get_events
from ffe.action_selector import ActionSelector

logger: Logger = get_logger()


@singleton
class EventSelector:
    def __init__(self):
        self.__silent: bool = False

    def run(self) -> bool:
        events: List[Event] = get_events(self.__silent)
        self.__silent = True  # verbose on the first call only
        if not events:
            logger.error('Aucun fichier de configuration d\'évènement trouvé')
            return False
        event_num: Optional[int] = None
        if len(events) == 1:
            event_num = 1
            if input_interactive('Un seul évènement trouvé, tapez Entrée pour continuer (Q pour quitter) ') == 'Q':
                return False
        else:
            print_interactive('Veuillez entrer le numéro de votre évènement :')
            event_range = range(1, len(events) + 1)
            for num in event_range:
                event: Event = events[num - 1]
                print_interactive('  - [{}] {} ({}.ini)'.format(num, event.name, event.id))
            print_interactive('  - [Q] Quitter')
            while event_num is None:
                choice: str = input_interactive('Votre choix : ')
                if choice == 'Q':
                    return False
                try:
                    event_num = int(choice)
                    if event_num not in event_range:
                        event_num = None
                except ValueError:
                    pass
        event: Event = events[event_num - 1]
        while ActionSelector.run(event.id):
            pass
        return True

from logging import Logger

from common.exception import PapiWebException
from common.singleton import Singleton
from common.logger import get_logger, print_interactive, input_interactive
from data.event import Event
from data.loader import EventLoader
from ffe.action_selector import ActionSelector

logger: Logger = get_logger()


class EventSelector(metaclass=Singleton):
    def __init__(self):
        self.__silent: bool = False

    @staticmethod
    def run() -> bool:
        events: list[Event] = EventLoader.get(request=None, lazy_load=True).events_with_tournaments_sorted_by_name
        if not events:
            logger.error('Aucun évènement trouvé')
            return False
        event_num: int | None = None
        if len(events) == 1:
            event_num = 1
            if input_interactive('Un seul évènement trouvé, tapez Entrée pour continuer (Q pour quitter) ') == 'Q':
                return False
        else:
            print_interactive('Veuillez entrer le numéro de votre évènement :')
            event_range = range(1, len(events) + 1)
            for num in event_range:
                event: Event = events[num - 1]
                print_interactive(f'  - [{num}] {event.name} ({event.uniq_id})')
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
        try:
            while ActionSelector().run(event.uniq_id):
                pass
        except PapiWebException as pwe:
            logger.warning(pwe)
        return True

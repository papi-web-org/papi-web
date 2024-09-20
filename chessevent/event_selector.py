from logging import Logger

from chessevent.action_selector import ActionSelector
from common.logger import get_logger, print_interactive, input_interactive
from common.singleton import Singleton
from data.event import Event
from data.loader import EventLoader

logger: Logger = get_logger()


class EventSelector(metaclass=Singleton):
    """The CLI interface to select an event."""
    def __init__(self):
        self.__silent: bool = False

    @staticmethod
    def run() -> bool:
        """The CLI interface function for selection of an event.
        Returns True if all went well (might be unreachable).
        Returns False if interrupted or if the user choses to quit."""
        events: list[Event] = EventLoader.get(request=None, lazy_load=True).events_sorted_by_name
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
                print_interactive(f'  - [{num}] {event.name} ({event.uniq_id}.ini)')
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
        while ActionSelector().run(event.uniq_id):
            pass
        return True

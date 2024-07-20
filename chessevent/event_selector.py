from typing import List, Optional
from logging import Logger

from chessevent.action_selector import ActionSelector
from common.papi_web_config import PapiWebConfig
from common.singleton import singleton
from common.logger import get_logger, print_interactive, input_interactive
from data.event import Event, get_events_sorted_by_name

logger: Logger = get_logger()


@singleton
class EventSelector:
    def __init__(self, config: PapiWebConfig):
        self.__silent: bool = False
        self.__config: PapiWebConfig = config

    def run(self) -> bool:
        events: List[Event] = get_events_sorted_by_name(False, with_tournaments_only=True)
        self.__silent = True  # verbose on the first call only
        if not events:
            logger.error('Aucun évènement trouvé')
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
        while ActionSelector(self.__config).run(event.uniq_id):
            pass
        return True

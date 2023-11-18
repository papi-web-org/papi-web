from typing import List, Optional
from logging import Logger

from common.papi_web_config import PapiWebConfig
from common.singleton import singleton
from common.logger import get_logger, print_interactive, input_interactive
from data.event import Event, get_events_by_name
from ffe.action_selector import ActionSelector

logger: Logger = get_logger()


@singleton
class EventSelector:
    def __init__(self, config: PapiWebConfig):
        self.__silent: bool = False
        self.__config: PapiWebConfig = config

    def run(self) -> bool:
        try:
            events: List[Event] = get_events_by_name(silent=self.__silent, with_tournaments_only=True)
            self.__silent = True  # verbose on the first call only
            if not events:
                logger.error(f'Aucun évènement trouvé')
                return False
            event_num: Optional[int] = None
            if len(events) == 1:
                event_num = 1
                if input_interactive(f'Un seul évènement trouvé, tapez Entrée pour continuer (Q pour quitter) ') == 'Q':
                    return False
            else:
                print_interactive(f'Veuillez entrer le numéro de votre évènement :')
                event_range = range(1, len(events) + 1)
                for num in event_range:
                    event: Event = events[num - 1]
                    print_interactive(f'  - [{num}] {event.name} ({event.id}.ini)')
                print_interactive('  - [Q] Quitter')
                while event_num is None:
                    choice: str = input_interactive(f'Votre choix : ')
                    if choice == 'Q':
                        return False
                    try:
                        event_num = int(choice)
                        if event_num not in event_range:
                            event_num = None
                    except ValueError:
                        pass
            event: Event = events[event_num - 1]
            while ActionSelector(self.__config).run(event.id):
                pass
            return True
        except UnicodeDecodeError:
            # caught from input_interactive() when stopping the engine in dev mode
            return False

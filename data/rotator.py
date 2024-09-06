from contextlib import suppress
from logging import Logger
from typing import TYPE_CHECKING

from common.papi_web_config import PapiWebConfig
from data.family import Family

if TYPE_CHECKING:
    from data.event import Event

from common.logger import get_logger
from data.screen import Screen
from database.store import StoredRotator

logger: Logger = get_logger()


ROTATOR_DEFAULT_DELAY: int = 15


class Rotator:
    def __init__(self, event: 'Event', stored_rotator: StoredRotator, ):
        self.event: 'Event' = event
        self.stored_rotator: StoredRotator = stored_rotator
        self._families: list[Family] | None = None
        self._screens: list[Screen] | None = None
        self._rotating_screens: list[Screen] | None = None

    @property
    def id(self) -> int:
        return self.stored_rotator.id

    @property
    def public(self) -> bool:
        return self.stored_rotator.public

    @property
    def uniq_id(self) -> str:
        return self.stored_rotator.uniq_id

    @property
    def delay(self) -> int:
        return self.stored_rotator.delay if self.stored_rotator.delay is not None \
            else PapiWebConfig().default_rotator_delay

    @property
    def show_menus(self) -> bool:
        return self.stored_rotator.show_menus if self.stored_rotator.show_menus is not None \
            else PapiWebConfig().default_rotator_show_menus

    @property
    def screens(self) -> list[Screen]:
        if self._screens is None:
            self._screens = []
            if self.stored_rotator.screen_ids:
                for screen_id in self.stored_rotator.screen_ids:
                    with suppress(KeyError):
                        self._screens.append(self.event.basic_screens_by_id[screen_id])
        return self._screens

    @property
    def families(self) -> list[Family]:
        if self._families is None:
            self._families = []
            if self.stored_rotator.family_ids:
                for family_id in self.stored_rotator.family_ids:
                    with suppress(KeyError):
                        self._families.append(self.event.families_by_id[family_id])
        return self._families

    @property
    def rotating_screens(self) -> list[Screen]:
        if self._rotating_screens is None:
            self._rotating_screens = [screen for screen in self.screens]
            for family in self.families:
                self._rotating_screens += [screen for screen in family.screens_by_uniq_id.values()]
        return self._rotating_screens

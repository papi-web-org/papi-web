from typing import TYPE_CHECKING, Any

from common.i18n import _
from data.pairings.settings import PairingSetting

if TYPE_CHECKING:
    from data.tournament import Tournament


class KnockoutThirdPlaceSetting(PairingSetting[bool]):
    """Whether a single-elimination knock-out plays a match for third
    place between the two losing semi-finalists, alongside the final."""

    @staticmethod
    def static_id() -> str:
        return 'KNOCKOUT_THIRD_PLACE'

    @staticmethod
    def static_name() -> str:
        return _('Third-place playoff')

    @property
    def template_path(self) -> str:
        return '/admin/pairings/settings/knockout_third_place.html'

    def tooltip_representation(self, value: bool) -> str | None:
        return _('Third-place playoff') if value else None

    def from_form_data(self, data: dict[str, str]) -> bool:
        return data.get(self.id) == 'on'

    def to_form_data(self, object_: bool) -> dict[str, str]:
        return {self.id: 'on' if object_ else ''}

    def get_data_errors(
        self, tournament: 'Tournament', data: dict[str, str]
    ) -> dict[str, str]:
        return {}

    @classmethod
    def default_value(cls, tournament: 'Tournament') -> bool:
        return False

    @classmethod
    def to_stored_value(cls, object_: bool) -> Any:
        return bool(object_)

    @classmethod
    def from_stored_value(cls, value: Any) -> bool:
        return bool(value)

from abc import ABC, abstractmethod
from datetime import datetime

from common.i18n import _
from utils.date_time import format_date, format_time
from utils.entity import IdentifiableEntity


class SCESyncStatus(IdentifiableEntity, ABC):
    @staticmethod
    def static_name() -> str:
        return ''

    @property
    @abstractmethod
    def icon_classes(self) -> str:
        """Classes representing the icon of the status."""

    @abstractmethod
    def tooltip_message(self, last_attempt_at: datetime) -> str:
        """Tooltip message of the status."""

    @property
    def update_last_sync_at(self) -> bool:
        """Defines if the last sync time should be updated."""
        return False

    @property
    def notify_error_status(self) -> bool:
        """Defines if the status is notified to the user via
        an error badge on the data transfer button."""
        return False


class NeverSyncedSCESyncStatus(SCESyncStatus):
    @staticmethod
    def static_id() -> str:
        return 'NEVER'

    @property
    def icon_classes(self) -> str:
        return ''

    def tooltip_message(self, last_attempt_at: datetime) -> str:
        return ''


class SuccessSCESyncStatus(SCESyncStatus):
    @staticmethod
    def static_id() -> str:
        return 'SUCCESS'

    @property
    def icon_classes(self) -> str:
        return 'bi-check-lg text-success'

    def tooltip_message(self, last_attempt_at: datetime) -> str:
        return _('Last synchronisation attempt ran successfully.')

    @property
    def update_last_sync_at(self) -> bool:
        return True


class WarningSCESyncStatus(SCESyncStatus, ABC):
    @property
    def icon_classes(self) -> str:
        return 'bi-exclamation-triangle-fill text-warning'

    @property
    def notify_error_status(self) -> bool:
        return True


class TournamentConflictsSCESyncStatus(WarningSCESyncStatus):
    @staticmethod
    def static_id() -> str:
        return 'TOURNAMENT_CONFLICTS'

    def tooltip_message(self, last_attempt_at: datetime) -> str:
        return _(
            'Synchronisation interrupted on {last_attempt_date} '
            'at {last_attempt_time}, tournament conflicts detected.'
        ).format(
            last_attempt_date=format_date(last_attempt_at.date()),
            last_attempt_time=format_time(last_attempt_at),
        )


class PlayerConflictsSCESyncStatus(WarningSCESyncStatus):
    @staticmethod
    def static_id() -> str:
        return 'PLAYER_CONFLICTS'

    def tooltip_message(self, last_attempt_at: datetime) -> str:
        return _('Player conflicts detected during the last synchronisation attempt.')

    @property
    def update_last_sync_at(self) -> bool:
        return True


class PlayerDuplicatesSCESyncStatus(WarningSCESyncStatus):
    @staticmethod
    def static_id() -> str:
        return 'PLAYER_DUPLICATES'

    def tooltip_message(self, last_attempt_at: datetime) -> str:
        return _('Player duplicates detected during the last synchronisation attempt.')

    @property
    def update_last_sync_at(self) -> bool:
        return True


class PlayerDuplicatesAndConflictsSCESyncStatus(WarningSCESyncStatus):
    @staticmethod
    def static_id() -> str:
        return 'PLAYER_DUPLICATES_AND_CONFLICTS'

    def tooltip_message(self, last_attempt_at: datetime) -> str:
        return _(
            'Player duplicates and conflicts detected '
            'during the last synchronisation attempt.'
        )

    @property
    def update_last_sync_at(self) -> bool:
        return True


class FailureSCESyncStatus(SCESyncStatus, ABC):
    @property
    def notify_error_status(self) -> bool:
        return True

    @property
    def icon_classes(self) -> str:
        return 'bi-x-lg text-danger'

    @property
    @abstractmethod
    def details(self) -> str:
        """Reason why the sync failed, displayed in the tooltip."""

    @property
    def consult_logs_message(self) -> bool:
        """Defines if the tooltip contains a message sending to the logs."""
        return False

    def tooltip_message(self, last_attempt_at: datetime) -> str:
        return _(
            'Last synchronisation attempt failed on {last_attempt_date} '
            'at {last_attempt_time} (details: {details}).'
        ).format(
            last_attempt_date=format_date(last_attempt_at.date()),
            last_attempt_time=format_time(last_attempt_at),
            details=self.details,
        )


class NetworkFailureSCESyncStatus(FailureSCESyncStatus):
    @staticmethod
    def static_id() -> str:
        return 'NETWORK_FAILURE'

    @property
    def details(self) -> str:
        return _('no internet connection')


class UnexpectedFailureSCESyncStatus(FailureSCESyncStatus):
    @staticmethod
    def static_id() -> str:
        return 'UNEXPECTED_FAILURE'

    @property
    def details(self) -> str:
        return _('consult the logs')


class AuthFailureSCESyncStatus(FailureSCESyncStatus):
    @staticmethod
    def static_id() -> str:
        return 'AUTH_FAILURE'

    @property
    def details(self) -> str:
        return _('re-authorisation required')

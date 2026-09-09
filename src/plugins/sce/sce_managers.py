from plugins.sce.sce_event_status import (
    SCEEventStatus,
    PublishedSCEEventStatus,
    DraftSCEEventStatus,
    ArchivedSCEEventStatus,
    NoInternetSCEEventStatus,
    InvalidRefreshTokenSCEEventStatus,
    NotFoundSCEEventStatus,
    UnexpectedHttpSCEEventStatus,
    NotConnectedSCEEventStatus,
    NotReachableSCEEventStatus,
)
from plugins.sce.sce_sync_status import (
    SCESyncStatus,
    NeverSyncedSCESyncStatus,
    SuccessSCESyncStatus,
    TournamentConflictsSCESyncStatus,
    PlayerConflictsSCESyncStatus,
    NetworkFailureSCESyncStatus,
    UnexpectedFailureSCESyncStatus,
    AuthFailureSCESyncStatus,
    PlayerDuplicatesSCESyncStatus,
    PlayerDuplicatesAndConflictsSCESyncStatus,
)
from plugins.sce.sce_tournament_status import (
    NetworkFailureSCETournamentStatus,
    NotFoundFailureSCETournamentStatus,
    UnexpectedFailureSCETournamentStatus,
    AuthFailureSCETournamentStatus,
    FailureSCETournamentStatus,
)
from utils.entity import EntityManager


class SCEEventStatusManager(EntityManager[SCEEventStatus]):
    def entity_types(self) -> list[type[SCEEventStatus]]:
        return [
            PublishedSCEEventStatus,
            DraftSCEEventStatus,
            ArchivedSCEEventStatus,
            NoInternetSCEEventStatus,
            InvalidRefreshTokenSCEEventStatus,
            NotFoundSCEEventStatus,
            UnexpectedHttpSCEEventStatus,
            NotConnectedSCEEventStatus,
            NotReachableSCEEventStatus,
        ]


class SCETournamentFailureStatusManager(EntityManager[FailureSCETournamentStatus]):
    def entity_types(self) -> list[type[FailureSCETournamentStatus]]:
        return [
            NetworkFailureSCETournamentStatus,
            NotFoundFailureSCETournamentStatus,
            UnexpectedFailureSCETournamentStatus,
            AuthFailureSCETournamentStatus,
        ]


class SCESyncStatusManager(EntityManager[SCESyncStatus]):
    def entity_types(self) -> list[type[SCESyncStatus]]:
        return [
            NeverSyncedSCESyncStatus,
            SuccessSCESyncStatus,
            TournamentConflictsSCESyncStatus,
            PlayerConflictsSCESyncStatus,
            PlayerDuplicatesSCESyncStatus,
            PlayerDuplicatesAndConflictsSCESyncStatus,
            NetworkFailureSCESyncStatus,
            UnexpectedFailureSCESyncStatus,
            AuthFailureSCESyncStatus,
        ]

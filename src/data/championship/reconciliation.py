"""Cross-event player reconciliation.

The same player or team enters several tournaments as a distinct rows in each
independent event. This module groups those rows into a single reconciled
competitor, matching them live by identity keys (fide id / name+birth / plugin key,
via :meth:`Event.get_player_identity_keys`). Manual overrides pin a source
competitor to a named group, adding an extra identity key so the organiser can fix
matches the automatic pass missed."""

from datetime import date
from typing import Any, TYPE_CHECKING

from common.i18n.utils import normalized_key
from data.championship.options import TeamScoreBasis
from utils.enum import Result, ScoreType

if TYPE_CHECKING:
    from data.championship.championship import ChampionshipSource
    from data.player import TournamentPlayer
    from data.teams.team import Team


class ReconciledParticipation:
    """One reconciled player's participation in a single source tournament."""

    def __init__(
        self, source: 'ChampionshipSource', tournament_player: 'TournamentPlayer'
    ):
        self.source: 'ChampionshipSource' = source
        self.tournament_player: 'TournamentPlayer' = tournament_player

    @property
    def event_uniq_id(self) -> str:
        return self.source.event_uniq_id

    @property
    def tournament_id(self) -> int:
        return self.source.tournament_id

    @property
    def source_player_id(self) -> int:
        return self.tournament_player.id

    @property
    def source_competitor_id(self) -> int:
        return self.source_player_id

    def points(self, _team_score_basis: TeamScoreBasis) -> float:
        return self.tournament_player.points or 0.0

    @property
    def coefficient(self) -> float:
        return getattr(self.source, 'coefficient', 1.0)

    def weighted_points(self, team_score_basis: TeamScoreBasis) -> float:
        return self.points(team_score_basis) * self.coefficient

    @property
    def rank(self) -> int:
        return self.tournament_player.rank or 0

    @property
    def field_size(self) -> int:
        # The size of the field that was ranked: a participant dropped from
        # the source's standings (FIDE 6.6) is not part of it, and must not
        # inflate the ranking points of those who were.
        tournament = self.source.tournament
        if tournament is None:
            return 0
        return sum(
            not player.is_excluded_from_standings
            for player in tournament.tournament_players
        )

    @property
    def wins(self) -> int:
        return sum(
            1
            for pairing in self.tournament_player.pairings_by_round.values()
            if pairing.win
        )

    #: An individual game has a single score, so there is no secondary score
    #: to fall back on (the extended direct encounter is a team-only rule).
    has_secondary_score = False

    def encounters(self, _team_score_basis: TeamScoreBasis, secondary: bool = False):
        # Only games actually played over the board count for the direct
        # encounter: forfeit wins/losses (and games with no result yet) are
        # excluded, so a walkover does not decide a shared ranking.
        for pairing in self.tournament_player.pairings_by_round.values():
            if pairing.opponent_id is not None and pairing.played:
                yield pairing.opponent_id, pairing.points


def _competitor_key(participations) -> str:
    """A stable identifier for a reconciled competitor, derived from the sorted
    set of its source participations. Survives a recompute as long as the same
    participations reconcile together (a manual order is intentionally dropped
    when a merge changes)."""
    return '|'.join(
        sorted(
            f'{p.event_uniq_id}:{p.tournament_id}:{p.source_competitor_id}'
            for p in participations
        )
    )


class ReconciledPlayer:
    """A single human, with the participations gathered across the sources."""

    def __init__(self, participations: list[ReconciledParticipation]):
        self.participations: list[ReconciledParticipation] = participations

    @property
    def key(self) -> str:
        return _competitor_key(self.participations)

    @property
    def _representative(self) -> 'TournamentPlayer':
        # Prefer a participation carrying a fide id, then one with a birth date,
        # so the canonical identity is the most complete one available.
        players = [p.tournament_player for p in self.participations]
        return (
            next((p for p in players if p.fide_id), None)
            or next((p for p in players if p.date_of_birth), None)
            or players[0]
        )

    @property
    def last_name(self) -> str:
        return self._representative.last_name

    @property
    def first_name(self) -> str:
        return self._representative.first_name

    @property
    def fide_id(self) -> int | None:
        return next(
            (
                p.tournament_player.fide_id
                for p in self.participations
                if p.tournament_player.fide_id
            ),
            None,
        )

    @property
    def date_of_birth(self) -> date | None:
        return next(
            (
                p.tournament_player.date_of_birth
                for p in self.participations
                if p.tournament_player.date_of_birth
            ),
            None,
        )

    @property
    def year_of_birth(self) -> int | None:
        if self.date_of_birth:
            return self.date_of_birth.year
        return next(
            (
                p.tournament_player.year_of_birth
                for p in self.participations
                if p.tournament_player.year_of_birth
            ),
            None,
        )


class ReconciledTeamParticipation:
    """One team's live standing in a referenced team tournament."""

    def __init__(
        self,
        source: 'ChampionshipSource',
        team: 'Team',
        standings_row: dict[str, Any],
    ):
        self.source = source
        self.team = team
        self.standings_row = standings_row

    @property
    def event_uniq_id(self) -> str:
        return self.source.event_uniq_id

    @property
    def tournament_id(self) -> int:
        return self.source.tournament_id

    @property
    def source_competitor_id(self) -> int:
        return self.team.id

    def _uses_match_points(self, basis: TeamScoreBasis) -> bool:
        if basis == TeamScoreBasis.MATCH_POINTS:
            return True
        if basis == TeamScoreBasis.GAME_POINTS:
            return False
        tournament = self.source.tournament
        assert tournament is not None
        return tournament.primary_score == ScoreType.MATCH_POINTS

    def points(self, team_score_basis: TeamScoreBasis) -> float:
        key = 'mp' if self._uses_match_points(team_score_basis) else 'gp'
        return float(self.standings_row[key])

    @property
    def coefficient(self) -> float:
        return getattr(self.source, 'coefficient', 1.0)

    def weighted_points(self, team_score_basis: TeamScoreBasis) -> float:
        return self.points(team_score_basis) * self.coefficient

    @property
    def rank(self) -> int:
        return int(self.standings_row['rank'])

    @property
    def field_size(self) -> int:
        tournament = self.source.tournament
        if tournament is None:
            return 0
        return sum(not team.is_excluded_from_standings for team in tournament.teams)

    @property
    def wins(self) -> int:
        return int(self.standings_row['wins'])

    #: A team match carries both a match-point and a game-point score, so the
    #: extended direct encounter (Art. 13.3) can fall back from the primary
    #: score to the secondary one.
    has_secondary_score = True

    def encounters(self, team_score_basis: TeamScoreBasis, secondary: bool = False):
        tournament = self.source.tournament
        assert tournament is not None
        team_id = self.team.id
        # The extended direct encounter reapplies the rule with the secondary
        # score, which is simply the other team score (Art. 13.1).
        uses_match_points = self._uses_match_points(team_score_basis)
        if secondary:
            uses_match_points = not uses_match_points
        for team_board in tournament.team_boards_by_id.values():
            stored = team_board.stored_team_board
            if stored.team_b_id is None or team_id not in (
                stored.team_a_id,
                stored.team_b_id,
            ):
                continue
            if not team_board.all_games_played:
                continue
            opponent_id = (
                stored.team_b_id if team_id == stored.team_a_id else stored.team_a_id
            )
            a_gp, b_gp = team_board.effective_game_points
            own_gp, opponent_gp = (
                (a_gp, b_gp) if team_id == stored.team_a_id else (b_gp, a_gp)
            )
            if uses_match_points:
                match_points = tournament.match_points
                if own_gp > opponent_gp:
                    points = match_points.get(Result.WIN, 2.0)
                elif own_gp < opponent_gp:
                    points = match_points.get(Result.LOSS, 0.0)
                else:
                    points = match_points.get(Result.DRAW, 1.0)
            else:
                points = own_gp
            yield opponent_id, float(points)


class ReconciledTeam:
    """The same team across independent team events."""

    def __init__(self, participations: list[ReconciledTeamParticipation]):
        self.participations = participations

    @property
    def key(self) -> str:
        return _competitor_key(self.participations)

    @property
    def _representative(self) -> 'Team':
        return self.participations[0].team

    @property
    def name(self) -> str:
        return self._representative.name

    @property
    def federation(self) -> str:
        return next(
            (p.team.federation for p in self.participations if p.team.federation),
            '',
        )


class _UnionFind:
    def __init__(self, size: int):
        self._parent = list(range(size))

    def find(self, index: int) -> int:
        while self._parent[index] != index:
            self._parent[index] = self._parent[self._parent[index]]
            index = self._parent[index]
        return index

    def union(self, left: int, right: int):
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self._parent[right_root] = left_root


def reconcile_players(
    sources: list['ChampionshipSource'],
    overrides_by_ref: dict[tuple[str, int, int], str],
) -> list[ReconciledPlayer]:
    """Group the participants of every resolved source into reconciled players.

    ``overrides_by_ref`` maps ``(event_uniq_id, tournament_id, source_player_id)``
    to a group key; participants sharing a group key are forced together."""
    participations: list[ReconciledParticipation] = []
    for source in sources:
        if source.tournament is None:
            continue
        for tournament_player in source.tournament.tournament_players:
            # A player dropped from a source's standings (FIDE 6.6) did not
            # place in it, so brings nothing to the championship.
            if tournament_player.is_excluded_from_standings:
                continue
            participations.append(ReconciledParticipation(source, tournament_player))

    union_find = _UnionFind(len(participations))
    representative_by_key: dict[tuple, int] = {}
    for index, participation in enumerate(participations):
        event = participation.source.event
        keys: set[tuple] = set()
        if event is not None:
            keys = event.get_player_identity_keys(
                participation.tournament_player.stored_player
            )
        override_group = overrides_by_ref.get(
            (
                participation.event_uniq_id,
                participation.tournament_id,
                participation.source_player_id,
            )
        )
        if override_group is not None:
            keys.add(('override', override_group))
        for key in keys:
            if key in representative_by_key:
                union_find.union(representative_by_key[key], index)
            else:
                representative_by_key[key] = index

    groups: dict[int, list[ReconciledParticipation]] = {}
    for index, participation in enumerate(participations):
        groups.setdefault(union_find.find(index), []).append(participation)

    return [ReconciledPlayer(group) for group in groups.values()]


def reconcile_teams(
    sources: list['ChampionshipSource'],
    overrides_by_ref: dict[tuple[str, int, int], str],
) -> list[ReconciledTeam]:
    """Group teams across sources by exact normalized name and federation.

    The automatic key is intentionally conservative. Manual overrides handle
    renamed teams and the exceptional cases where local labels collide.
    """
    participations: list[ReconciledTeamParticipation] = []
    for source in sources:
        tournament = source.tournament
        if tournament is None:
            continue
        standings_by_team_id = {
            row['team'].id: row for row in tournament.team_standings()
        }
        for team in tournament.teams:
            if team.is_excluded_from_standings:
                continue
            row = standings_by_team_id.get(team.id)
            if row is not None:
                participations.append(ReconciledTeamParticipation(source, team, row))

    union_find = _UnionFind(len(participations))
    representative_by_key: dict[tuple, int] = {}
    for index, participation in enumerate(participations):
        team = participation.team
        keys: set[tuple] = {
            (
                'team',
                normalized_key(team.name),
                team.federation.strip().upper(),
            )
        }
        override_group = overrides_by_ref.get(
            (
                participation.event_uniq_id,
                participation.tournament_id,
                participation.source_competitor_id,
            )
        )
        if override_group is not None:
            keys.add(('override', override_group))
        for key in keys:
            if key in representative_by_key:
                union_find.union(representative_by_key[key], index)
            else:
                representative_by_key[key] = index

    groups: dict[int, list[ReconciledTeamParticipation]] = {}
    for index, participation in enumerate(participations):
        groups.setdefault(union_find.find(index), []).append(participation)
    return [ReconciledTeam(group) for group in groups.values()]

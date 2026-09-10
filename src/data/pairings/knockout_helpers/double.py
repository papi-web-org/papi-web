"""Double-elimination behavior for knock-out engines."""

from typing import TYPE_CHECKING, Any, Protocol, cast

from common.i18n import _
from data.pairings import double_elimination
from data.pairings.knockout_helpers import bracket as knockout_bracket
from data.pairings.knockout_helpers.common import tie_resolution_message
from data.pairings.knockout_helpers.two_game import TwoGameMatchMixin
from data.pairings.settings import PairingSetting

if TYPE_CHECKING:
    from data.pairings.knockout_helpers.layout import MatchDescriptor
    from data.tournament import Tournament, TournamentPlayer


class _DoubleEliminationGroupingHost(Protocol):
    def _grouped_leaves(self, tournament: 'Tournament') -> list[int | None] | None: ...


class _TwoGameDoubleElimHost(Protocol):
    def knockout_placement_values(
        self, tournament: 'Tournament', *, after_round: int | None = None
    ) -> dict[int, float]: ...
    def _schedule(
        self, tournament: 'Tournament'
    ) -> list['double_elimination.Match']: ...

    def _resolved(
        self, tournament: 'Tournament'
    ) -> tuple[list['double_elimination.Match'], dict, dict]: ...

    def _match_participants(
        self, tournament: 'Tournament', by_id: dict, match_id: str, cache: dict
    ) -> tuple[int | None, int | None]: ...

    def _match_winner(
        self, tournament: 'Tournament', by_id: dict, match_id: str, cache: dict
    ) -> int | None: ...

    def _match_loser(
        self, tournament: 'Tournament', by_id: dict, match_id: str, cache: dict
    ) -> int | None: ...

    def _reset_needed(
        self, tournament: 'Tournament', by_id: dict, cache: dict
    ) -> bool: ...

    def _bracket_participant_count(self, tournament: 'Tournament') -> int: ...

    def _match_section_label(
        self, tournament: 'Tournament', match: 'double_elimination.Match'
    ) -> str: ...

    def _board_match(
        self, tournament: 'Tournament', board: Any
    ) -> 'double_elimination.Match | None': ...


class DoubleEliminationResetSetting(PairingSetting[bool]):
    """Whether a double-elimination grand final can reset the bracket."""

    @staticmethod
    def static_id() -> str:
        return 'KNOCKOUT_GRAND_FINAL_RESET'

    @staticmethod
    def static_name() -> str:
        return _('Grand final reset')

    @property
    def template_path(self) -> str:
        return '/admin/pairings/settings/knockout_grand_final_reset.html'

    def tooltip_representation(self, value: bool) -> str | None:
        return _('Grand final reset') if value else None

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


class DoubleEliminationMixin:
    """Shared source resolution for individual and team double elimination."""

    def _double_elim_grouping_host(self) -> _DoubleEliminationGroupingHost:
        return cast(_DoubleEliminationGroupingHost, self)

    def _participant_count(self, tournament: 'Tournament') -> int:
        raise NotImplementedError

    def _seed_id(self, tournament: 'Tournament', seed: int) -> int:
        raise NotImplementedError

    def _played_match_winner(
        self, tournament: 'Tournament', match: double_elimination.Match, a_id, b_id
    ) -> int | None:
        raise NotImplementedError

    def _bracket_participant_count(self, tournament: 'Tournament') -> int:
        leaves = self._double_elim_grouping_host()._grouped_leaves(tournament)
        return (
            len(leaves) if leaves is not None else self._participant_count(tournament)
        )

    def _grouped_seed_map(
        self, tournament: 'Tournament'
    ) -> dict[int, int | None] | None:
        leaves = self._double_elim_grouping_host()._grouped_leaves(tournament)
        if leaves is None:
            return None
        order = knockout_bracket.seed_order(len(leaves))
        return {order[leaf]: leaves[leaf] for leaf in range(len(leaves))}

    def _seed_participant(self, tournament: 'Tournament', seed: int) -> int | None:
        seed_map = self._grouped_seed_map(tournament)
        if seed_map is not None:
            return seed_map.get(seed)
        if seed > self._participant_count(tournament):
            return None
        return self._seed_id(tournament, seed)

    def _seed_absent(self, tournament: 'Tournament', seed: int) -> bool:
        seed_map = self._grouped_seed_map(tournament)
        if seed_map is not None:
            return seed_map.get(seed) is None
        return seed > self._participant_count(tournament)

    def _schedule(self, tournament: 'Tournament') -> list[double_elimination.Match]:
        return double_elimination.schedule(
            self._bracket_participant_count(tournament),
            with_reset=DoubleEliminationResetSetting.get_value(tournament),
        )

    def _resolved(
        self, tournament: 'Tournament'
    ) -> tuple[list[double_elimination.Match], dict, dict]:
        """The match graph, its matches by id, and the cache the source
        resolution memoises winners and losers in. Resolving one match walks
        every match it descends from, and the standings ask for a placement per
        participant, so the three are built once per tournament. The graph is
        empty below two participants, where there is nothing to play."""
        knockout = getattr(tournament, 'knockout', None)
        cache = knockout.engine_cache if knockout is not None else {}
        resolved = cache.get('double_elimination')
        if resolved is None:
            schedule = self._schedule(tournament)
            resolved = (schedule, {match.id: match for match in schedule}, {})
            cache['double_elimination'] = resolved
        return resolved

    def _resolve_source(
        self,
        tournament: 'Tournament',
        by_id: dict,
        source: double_elimination.Source,
        cache: dict,
    ) -> int | None:
        if isinstance(source, double_elimination.Seed):
            return self._seed_participant(tournament, source.seed)
        if isinstance(source, double_elimination.WinnerOf):
            return self._match_winner(tournament, by_id, source.match_id, cache)
        return self._match_loser(tournament, by_id, source.match_id, cache)

    def _match_participants(
        self, tournament: 'Tournament', by_id: dict, match_id: str, cache: dict
    ) -> tuple[int | None, int | None]:
        match = by_id[match_id]
        return (
            self._resolve_source(tournament, by_id, match.a, cache),
            self._resolve_source(tournament, by_id, match.b, cache),
        )

    def _source_absent(
        self,
        tournament: 'Tournament',
        by_id: dict,
        source: double_elimination.Source,
        cache: dict,
    ) -> bool:
        if isinstance(source, double_elimination.Seed):
            return self._seed_absent(tournament, source.seed)
        if isinstance(source, double_elimination.WinnerOf):
            return self._match_empty(tournament, by_id, source.match_id, cache)
        return self._match_lacks_loser(tournament, by_id, source.match_id, cache)

    def _match_empty(
        self, tournament: 'Tournament', by_id: dict, match_id: str, cache: dict
    ) -> bool:
        key = ('empty', match_id)
        if key in cache:
            return cache[key]
        cache[key] = False
        match = by_id[match_id]
        result = self._source_absent(
            tournament, by_id, match.a, cache
        ) and self._source_absent(tournament, by_id, match.b, cache)
        cache[key] = result
        return result

    def _match_lacks_loser(
        self, tournament: 'Tournament', by_id: dict, match_id: str, cache: dict
    ) -> bool:
        key = ('no_loser', match_id)
        if key in cache:
            return cache[key]
        cache[key] = False
        match = by_id[match_id]
        result = self._source_absent(
            tournament, by_id, match.a, cache
        ) or self._source_absent(tournament, by_id, match.b, cache)
        cache[key] = result
        return result

    def _match_winner(
        self, tournament: 'Tournament', by_id: dict, match_id: str, cache: dict
    ) -> int | None:
        key = ('winner', match_id)
        if key in cache:
            return cache[key]
        cache[key] = None
        match = by_id[match_id]
        a_absent = self._source_absent(tournament, by_id, match.a, cache)
        b_absent = self._source_absent(tournament, by_id, match.b, cache)
        a_id, b_id = self._match_participants(tournament, by_id, match_id, cache)
        if a_absent and b_absent:
            winner = None
        elif b_absent:
            winner = a_id
        elif a_absent:
            winner = b_id
        elif a_id is None or b_id is None:
            winner = None
        else:
            winner = self._played_match_winner(tournament, match, a_id, b_id)
        cache[key] = winner
        return winner

    def _match_loser(
        self, tournament: 'Tournament', by_id: dict, match_id: str, cache: dict
    ) -> int | None:
        a_id, b_id = self._match_participants(tournament, by_id, match_id, cache)
        if a_id is None or b_id is None:
            return None
        winner = self._match_winner(tournament, by_id, match_id, cache)
        if winner is None:
            return None
        return a_id if winner == b_id else b_id

    def _reset_needed(self, tournament: 'Tournament', by_id: dict, cache: dict) -> bool:
        gf_winner = self._match_winner(
            tournament, by_id, double_elimination.GRAND_FINAL, cache
        )
        if gf_winner is None:
            return False
        losers_final = by_id[double_elimination.GRAND_FINAL].b.match_id
        return gf_winner == self._match_winner(tournament, by_id, losers_final, cache)

    def reset_is_due(self, tournament: 'Tournament') -> bool:
        if not DoubleEliminationResetSetting.get_value(tournament):
            return False
        _, by_id, cache = self._resolved(tournament)
        if not by_id:
            return False
        return self._reset_needed(tournament, by_id, cache)

    def tournament_is_over(self, tournament: 'Tournament') -> bool:
        _, by_id, cache = self._resolved(tournament)
        if not by_id:
            return False
        if (
            self._match_winner(tournament, by_id, double_elimination.GRAND_FINAL, cache)
            is None
        ):
            return False
        return not self._reset_needed(tournament, by_id, cache)

    def _round_match_pairs(
        self, tournament: 'Tournament', round_: int
    ) -> list[tuple[int, int | None]]:
        schedule, by_id, cache = self._resolved(tournament)
        pairs: list[tuple[int, int | None]] = []
        for match in double_elimination.matches_for_round(schedule, round_):
            if match.bracket == double_elimination.GRAND_FINAL_RESET and (
                not self._reset_needed(tournament, by_id, cache)
            ):
                continue
            a_id, b_id = self._match_participants(tournament, by_id, match.id, cache)
            if a_id is None and b_id is None:
                continue
            if a_id is None or b_id is None:
                present = a_id if a_id is not None else b_id
                assert present is not None
                pairs.append((present, None))
            else:
                pairs.append((a_id, b_id))
        return pairs

    def _de_round_of(self, round_: int) -> int:
        """The bracket round an app round plays. One app round per bracket
        round, unless the variant spreads a match over several games."""
        return round_

    def _placement_final_value(self, tournament: 'Tournament') -> float:
        """The placement value of the participant who loses the grand final —
        the last bracket round, beyond every other elimination."""
        return float(tournament.rounds)

    def _completed_de_rounds(self, after_round: int) -> int:
        """The last bracket round decided by app round *after_round*. One app
        round per bracket round, unless the variant spreads a match over
        several games, where a level counts once its last game is played."""
        return after_round

    def _descriptor_played_rounds(self, de_round: int) -> tuple[int, ...]:
        """The app rounds a bracket round is played in — one, unless the
        variant spreads its matches over several games."""
        return (de_round,)

    def _double_elimination_gate(
        self, tournament: 'Tournament', at_round: int
    ) -> str | None:
        if at_round <= 1:
            return None
        schedule, by_id, cache = self._resolved(tournament)
        for round_ in range(1, at_round):
            if not tournament.is_round_finished(round_):
                return _(
                    'Pairings generation not allowed if previous rounds have '
                    'missing results.'
                )
            for match in double_elimination.matches_for_round(schedule, round_):
                a_id, b_id = self._match_participants(
                    tournament, by_id, match.id, cache
                )
                if (
                    a_id is not None
                    and b_id is not None
                    and (self._match_winner(tournament, by_id, match.id, cache) is None)
                ):
                    return tie_resolution_message(tournament, round_)
        if DoubleEliminationResetSetting.get_value(tournament):
            reset_round = double_elimination.round_count(
                self._bracket_participant_count(tournament), with_reset=True
            )
            if at_round == reset_round and not self._reset_needed(
                tournament, by_id, cache
            ):
                return _(
                    'No reset game is needed: the winners-bracket champion won '
                    'the grand final.'
                )
        return None

    def knockout_placement_values(
        self, tournament: 'Tournament', *, after_round: int | None = None
    ) -> dict[int, float]:
        """Each eliminated participant's placement: the bracket round that put
        them out. *after_round* asks for the standings as they stood then —
        matches played later have not happened yet, so whoever they knocked out
        is still in."""
        schedule, by_id, cache = self._resolved(tournament)
        if not by_id:
            return {}
        decided = (
            None if after_round is None else self._completed_de_rounds(after_round)
        )
        values: dict[int, float] = {}
        for match in schedule:
            if match.bracket != double_elimination.LOSERS:
                continue
            if decided is not None and match.round > decided:
                continue
            loser = self._match_loser(tournament, by_id, match.id, cache)
            if loser is not None:
                values.setdefault(loser, float(match.round))
        final_id = double_elimination.GRAND_FINAL
        if double_elimination.GRAND_FINAL_RESET in by_id and self._reset_needed(
            tournament, by_id, cache
        ):
            final_id = double_elimination.GRAND_FINAL_RESET
        if decided is not None and by_id[final_id].round > decided:
            return values
        runner_up = self._match_loser(tournament, by_id, final_id, cache)
        if runner_up is not None:
            values[runner_up] = self._placement_final_value(tournament)
        return values

    def _board_participant_ids(self, board) -> set[int]:
        raise NotImplementedError

    def board_bracket(self, tournament: 'Tournament', board) -> str | None:
        match = self._board_match(tournament, board)
        return match.bracket if match is not None else None

    def board_section_label(self, tournament: 'Tournament', board) -> str | None:
        match = self._board_match(tournament, board)
        return self._match_section_label(tournament, match) if match else None

    def _board_match(
        self, tournament: 'Tournament', board
    ) -> 'double_elimination.Match | None':
        wanted = self._board_participant_ids(board)
        if not wanted:
            return None
        best, best_overlap = None, 0
        for ids, match in self._round_match_map(tournament, board.round).items():
            overlap = len(ids & wanted)
            if overlap > best_overlap:
                best, best_overlap = match, overlap
        return best

    def _round_match_map(
        self, tournament: 'Tournament', round_: int
    ) -> dict[frozenset, 'double_elimination.Match']:
        schedule, by_id, cache = self._resolved(tournament)
        result: dict[frozenset, double_elimination.Match] = {}
        for match in double_elimination.matches_for_round(
            schedule, self._de_round_of(round_)
        ):
            a_id, b_id = self._match_participants(tournament, by_id, match.id, cache)
            ids = frozenset(x for x in (a_id, b_id) if x is not None)
            if ids:
                result[ids] = match
        return result

    def _match_section_label(
        self, tournament: 'Tournament', match: 'double_elimination.Match'
    ) -> str:
        if match.bracket == double_elimination.GRAND_FINAL:
            return _('Grand Final')
        if match.bracket == double_elimination.GRAND_FINAL_RESET:
            return _('Grand Final (reset)')
        number = int(match.id.split('.')[0][1:])
        rounds = knockout_bracket.round_count(
            self._bracket_participant_count(tournament)
        )
        if match.bracket == double_elimination.WINNERS:
            from_end = rounds - number
            if from_end <= 0:
                return _('Upper Bracket Final')
            if from_end == 1:
                return _('Upper Bracket Semifinals')
            if from_end == 2:
                return _('Upper Bracket Quarterfinals')
            return _('Upper Bracket Round of {count}').format(count=2 ** (from_end + 1))
        losers_rounds = 2 * (rounds - 1)
        from_end = losers_rounds - number
        if from_end <= 0:
            return _('Lower Bracket Final')
        if from_end == 1:
            return _('Lower Bracket Semifinals')
        if from_end == 2:
            return _('Lower Bracket Quarterfinals')
        return _('Lower Bracket Round {number}').format(number=number)

    def bracket_match_descriptors(
        self, tournament: 'Tournament'
    ) -> list['MatchDescriptor']:
        from data.pairings.knockout_helpers.layout import MatchDescriptor

        schedule, by_id, cache = self._resolved(tournament)
        descriptors: list[MatchDescriptor] = []
        for match in schedule:
            if match.bracket == double_elimination.WINNERS:
                section = 'upper'
                column = int(match.id.split('.')[0][1:]) - 1
            elif match.bracket == double_elimination.LOSERS:
                section = 'lower'
                column = int(match.id.split('.')[0][1:]) - 1
            elif match.bracket == double_elimination.GRAND_FINAL:
                section, column = 'final', 0
            else:
                section, column = 'final', 1
            a_id, b_id = self._match_participants(tournament, by_id, match.id, cache)
            descriptors.append(
                MatchDescriptor(
                    id=match.id,
                    section=section,
                    column=column,
                    round_name=self._match_section_label(tournament, match),
                    app_round=match.round,
                    played_rounds=self._descriptor_played_rounds(match.round),
                    a_id=a_id,
                    b_id=b_id,
                    winner_id=self._match_winner(tournament, by_id, match.id, cache),
                    source_top=self._source_match_id(match.a),
                    source_bottom=self._source_match_id(match.b),
                )
            )
        return descriptors

    @staticmethod
    def _source_match_id(source: 'double_elimination.Source') -> str | None:
        if isinstance(source, double_elimination.WinnerOf | double_elimination.LoserOf):
            return source.match_id
        return None


class TwoGameDoubleElimMixin(TwoGameMatchMixin):
    """Double-elimination two-game behavior."""

    def _two_game_double_elim_host(self) -> _TwoGameDoubleElimHost:
        return cast(_TwoGameDoubleElimHost, self)

    def _double_elimination_gate(
        self, tournament: 'Tournament', at_round: int
    ) -> str | None:
        if at_round <= 1:
            return None
        host = self._two_game_double_elim_host()
        schedule, by_id, cache = host._resolved(tournament)
        for app_round in range(1, at_round):
            if not tournament.is_round_finished(app_round):
                return _(
                    'Pairings generation not allowed if previous rounds have '
                    'missing results.'
                )
        completed = (at_round - 1) // self.GAMES_PER_MATCH
        for de_round in range(1, completed + 1):
            for match in double_elimination.matches_for_round(schedule, de_round):
                a_id, b_id = host._match_participants(
                    tournament, by_id, match.id, cache
                )
                if (
                    a_id is not None
                    and b_id is not None
                    and host._match_winner(tournament, by_id, match.id, cache) is None
                ):
                    return tie_resolution_message(
                        tournament, self._game_app_round(de_round, 2)
                    )
        if DoubleEliminationResetSetting.get_value(tournament):
            reset_de_round = double_elimination.round_count(
                host._bracket_participant_count(tournament), with_reset=True
            )
            if self._level_of(at_round) == reset_de_round and not host._reset_needed(
                tournament, by_id, cache
            ):
                return _(
                    'No reset game is needed: the winners-bracket champion won '
                    'the grand final.'
                )
        return None

    def _de_round_of(self, round_: int) -> int:
        return self._level_of(round_)

    def _placement_final_value(self, tournament: 'Tournament') -> float:
        return float(self._level_count(tournament))

    def _completed_de_rounds(self, after_round: int) -> int:
        return self._completed_level_count(after_round)

    def _descriptor_played_rounds(self, de_round: int) -> tuple[int, ...]:
        return (
            self._game_app_round(de_round, 1),
            self._game_app_round(de_round, 2),
        )

    def board_section_label(self, tournament: 'Tournament', board) -> str | None:
        host = self._two_game_double_elim_host()
        match = host._board_match(tournament, board)
        if match is None:
            return None
        return _('{stage} — game {game}').format(
            stage=host._match_section_label(tournament, match),
            game=self._game_of(board.round),
        )

    def ranking_value(
        self, tournament: 'Tournament', player: 'TournamentPlayer', *, after_round: int
    ) -> float:
        host = self._two_game_double_elim_host()
        return host.knockout_placement_values(tournament, after_round=after_round).get(
            player.id, float(self._level_count(tournament) + 1)
        )

    def team_ranking_values(
        self, tournament: 'Tournament', *, after_round: int
    ) -> dict[int, float]:
        host = self._two_game_double_elim_host()
        placed = host.knockout_placement_values(tournament, after_round=after_round)
        survivor = float(self._level_count(tournament) + 1)
        return {team.id: placed.get(team.id, survivor) for team in tournament.teams}

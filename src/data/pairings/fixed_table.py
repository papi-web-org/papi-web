"""Framework for table-driven team pairing systems.

A *fixed-table* pairing system pairs individual players from different teams
according to a pre-computed lookup table — no engine logic, no Swiss/round-
robin computation. Each table covers one combination of (team_count,
players_per_team). The table provides, for each round and each board, which
players face each other, with the first-listed player playing white.

Concrete systems live in plugins; they only need to declare the abstract
methods that yield the table-set.

For team rosters larger than the maximum tabulated player count, the engine
chains multiple base tables in (typically 12-player) blocks, adjusting
player numbers — see ``FixedTablePairingEngine._build_combined_pairings``.

The systems built on this framework are flat (``paired_by_team = False``):
each player faces an opponent from a different team but boards are not
grouped into team-vs-team blocks. Rankings remain individual-style; team
totals are derived by separate ranking code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from common.exception import SharlyChessException
from common.i18n import _
from data.pairings.engines import PairingEngine
from data.pairings.systems import PairingSystem
from data.pairings.variations import PairingVariation
from utils.enum import Result
from database.sqlite.event.event_store import StoredBoard

if TYPE_CHECKING:
    from data.teams.team import Team
    from data.tournament import Tournament


# ---------------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class TablePairing:
    """One pairing cell in a fixed table.

    Players are addressed by team letter (``'A'``..``'M'``) and 1-based
    intra-team index. ``white`` plays white, ``black`` plays black.
    """

    white_team: str
    white_index: int
    black_team: str
    black_index: int


@dataclass(frozen=True)
class FixedPairingTable:
    """A complete table for one (team_count, players_per_team) configuration.

    ``rounds`` is the ordered list of regular rounds. ``is_compromise`` marks a
    table for an otherwise impossible shape that deliberately relaxes one
    fixed-table ideal, with the verifier applying the corresponding
    best-compromise checks. Each round is a list of ``TablePairing`` indexed by
    board (board ``i`` = ``rounds[r][i]``).
    """

    team_count: int
    players_per_team: int
    rounds: tuple[tuple[TablePairing, ...], ...]
    is_compromise: bool = False

    @property
    def regular_round_count(self) -> int:
        return len(self.rounds)

    def round_pairings(
        self, round_index: int, total_rounds: int
    ) -> tuple[TablePairing, ...]:
        """Return the pairings for round ``round_index`` (1-based).

        Maps the tournament's intended round number onto the table's round list.
        """
        if round_index < 1 or round_index > total_rounds:
            raise ValueError(f'Round {round_index} out of range 1..{total_rounds}.')
        return self.rounds[(round_index - 1) % self.regular_round_count]


class PairingTableProvider(ABC):
    """A system that can produce the whole schedule of a shape as a
    :class:`FixedPairingTable`, whether it reads it from a registry of
    tabulated combinations or works it out.

    Declared apart from any one framework so that the schedule print
    document can render every such system through the same call."""

    @abstractmethod
    def get_table(
        self,
        team_count: int,
        players_per_team: int,
        tournament: 'Tournament | None' = None,
    ) -> FixedPairingTable | None:
        """The table for the given (team_count, players_per_team) combo,
        or ``None`` when this system has none for that shape.

        ``tournament`` is forwarded so implementations can consult the
        variation or the rule set (a double round, cell overrides for a
        specific cup)."""


# ---------------------------------------------------------------------------------
# Abstract system / variation
# ---------------------------------------------------------------------------------


class FixedTablePairingSystem(
    PairingSystem['FixedTableVariation'], PairingTableProvider, ABC
):
    """A pairing system driven by pre-computed lookup tables, spreading
    each round's boards over more teams than the two a match has.

    Concrete subclasses (typically plugin-provided) implement
    :meth:`get_table` to return the table for a given (team_count,
    players_per_team) combination, or ``None`` if unsupported (in which
    case the engine will try to combine smaller tables).

    A round pairs players from several teams at once, so it is no team's
    match: the boards stay flat (``paired_by_team = False``), and a
    team's score is the sum of its players' game points.
    """

    @property
    def paired_by_team(self) -> bool:
        return False

    @property
    def uses_team_letters(self) -> bool:
        # The table addresses teams by letter (A, B, …) — see team_by_letter.
        return True

    @property
    def allow_bye_definition(self) -> bool:
        return False

    @property
    def show_unfinished_round_modal(self) -> bool:
        # Warn before leaving a round whose results aren't all in, as the
        # Swiss / round-robin systems do.
        return True

    @property
    def show_unpaired_player_modal(self) -> bool:
        return False

    @property
    def show_unpaired_team_modal(self) -> bool:
        return False

    @property
    def allow_team_addition_once_paired(self) -> bool:
        return False

    @property
    def split_unpaired_and_bye_players(self) -> bool:
        return False

    @property
    def supports_match_points(self) -> bool:
        # Fixed-table systems aggregate individual game points only;
        # there's no match-points side of the score.
        return False

    @abstractmethod
    def supported_team_counts(self) -> tuple[int, ...]:
        """Tuple of supported team counts (used for validation messages)."""


class FixedTableVariation(PairingVariation, ABC):
    """Variation for a fixed-table system. Subclasses only need to declare
    the engine concrete class (which itself knows the system class)."""


def _can_tile(target: int, sizes: tuple[int, ...]) -> bool:
    """Whether ``target`` can be expressed as a sum of elements drawn
    from ``sizes`` (with repetition). Used to validate player counts
    larger than the maximum base table — they're only valid when they
    can be chained from available block sizes."""
    if target < 0:
        return False
    if target == 0:
        return True
    seen = {0}
    while seen:
        nxt = set()
        for s in seen:
            for size in sizes:
                v = s + size
                if v == target:
                    return True
                if v < target:
                    nxt.add(v)
        if not nxt or nxt == seen:
            break
        seen = nxt
    return False


# ---------------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------------


class FixedTablePairingEngine(PairingEngine):
    """Engine that consumes a :class:`FixedPairingTable` and produces flat
    :class:`StoredBoard` rows. No team_board envelope (flat mixed
    pairings between players from different teams).

    For team rosters larger than the largest tabulated player count, the
    engine chains base tables in blocks: e.g. a 38-player 3-team event with
    a 12-player base table uses one block for players 1-12, another for
    13-24, another for 25-32, then a smaller (e.g. 6-player) table for
    the remainder. Each block keeps its own intra-team indexing, offset by
    the block start.
    """

    @property
    @abstractmethod
    def system(self) -> FixedTablePairingSystem:
        """The concrete system providing the lookup tables."""

    @property
    @override
    def pab_result(self) -> Result:
        # A flat board with one empty seat is an incomplete-roster hole,
        # not a bye: the present player wins by forfeit, as in Swiss.
        return Result.FORFEIT_WIN

    def invalid_player_count_message(self, tournament: 'Tournament') -> str | None:
        teams = self._teams_for_tournament(tournament)
        supported = self.system.supported_team_counts()
        if not supported:
            return _('No tables available for this pairing system.')
        max_teams = max(supported)
        if len(teams) > max_teams:
            return _('This pairing system supports up to {n} teams.').format(
                n=max_teams
            )
        if len(teams) < min(supported):
            return _('This pairing system requires at least {n} teams.').format(
                n=min(supported)
            )
        if len(teams) not in supported:
            return _('No table available for {n} teams.').format(n=len(teams))
        n = tournament.team_player_count or 0
        if n <= 0:
            return _('Tournament has no team-player count configured.')
        # Cap rounds by what the chosen table can actually produce. (The
        # old check was hardcoded to ``rounds < team_count``, which broke
        # for cup-specific tables that ship more regular rounds than the
        # standard FFE registry.)
        chosen_table = self.system.get_table(len(teams), n, tournament)
        if chosen_table is not None:
            max_rounds = chosen_table.regular_round_count
            if tournament.rounds > max_rounds:
                return _(
                    'This pairing table covers up to {max_rounds} rounds '
                    'for {t} teams of {p} players. Reduce the round count.'
                ).format(
                    max_rounds=max_rounds,
                    t=len(teams),
                    p=n,
                )
        # Validate the player count: tables exist for specific sizes
        # (typically 4, 6, 8, 10, 12) and rosters larger than the
        # largest base table are tiled in blocks. Counts that can't be
        # tiled (e.g. odd counts when only even tables are available)
        # are rejected up-front rather than failing inside the engine.
        if chosen_table is None:
            candidates = self._candidate_player_counts(len(teams), tournament)
            if not candidates:
                candidate_max_rounds = self._max_candidate_round_count(
                    len(teams), tournament
                )
                if (
                    candidate_max_rounds is not None
                    and tournament.rounds > candidate_max_rounds
                ):
                    return _(
                        'This pairing table covers up to {max_rounds} rounds '
                        'for {t} teams. Reduce the round count.'
                    ).format(
                        max_rounds=candidate_max_rounds,
                        t=len(teams),
                    )
                return _('No tables available for {t} teams.').format(t=len(teams))
            if not _can_tile(n, candidates):
                return _(
                    '{n} players per team is not supported (FFE tables '
                    'cover {sizes}; rosters larger than the maximum can '
                    'be tiled in blocks).'
                ).format(n=n, sizes=', '.join(str(c) for c in sorted(candidates)))
        # Incomplete rosters are allowed (as in Swiss): a team with fewer
        # than ``n`` players simply leaves a hole on the missing boards,
        # scored as a forfeit win for the present opponent.
        return None

    def pairings_generation_disabled_message(
        self, tournament: 'Tournament', at_round: int
    ) -> str | None:
        if message := super().pairings_generation_disabled_message(
            tournament, at_round
        ):
            return message
        teams = self._teams_for_tournament(tournament)
        if not any(
            player is not None
            for team in teams
            for player in team.effective_round_slots(at_round)
        ):
            return _('Pairings generation disabled if there are no players to pair.')
        if any(
            not tournament.is_round_finished(round_) for round_ in range(1, at_round)
        ):
            return _(
                'Pairings generation not allowed if previous rounds have '
                'missing results.'
            )
        return None

    def _generate_stored_boards(
        self,
        tournament: 'Tournament',
        round_: int,
        partial_pairings: bool = False,
        prohibited_pairing_override: 'list | None' = None,
    ) -> list[StoredBoard]:
        teams = self._teams_for_tournament(tournament)
        n = tournament.team_player_count or 0
        if not teams or n <= 0:
            return []
        # Order teams stably: by pairing_number then id. Letter A = first
        # team, B = second, etc.
        team_by_letter: dict[str, 'Team'] = {
            chr(ord('A') + i): team for i, team in enumerate(teams)
        }
        pairings = self._build_combined_pairings(tournament, round_, len(teams), n)
        stored_boards: list[StoredBoard] = []
        for index, p in enumerate(pairings):
            white_team = team_by_letter.get(p.white_team)
            black_team = team_by_letter.get(p.black_team)
            if white_team is None or black_team is None:
                raise SharlyChessException(
                    f'Table references unknown team letter '
                    f'{p.white_team!r}/{p.black_team!r}.'
                )
            white_player = self._team_player(white_team, p.white_index, round_)
            black_player = self._team_player(black_team, p.black_index, round_)
            if white_player is None and black_player is None:
                # Both teams are short this seat. A flat board has no round
                # column — its round is recovered from a pairing or a
                # team_board (see ``load_tournament_stored_boards_by_round``),
                # and a player-less flat board has neither, so it can't be
                # persisted. Skip it rather than create an orphan that
                # vanishes on reload.
                continue
            # One side missing (incomplete roster / lineup hole) ⇒ a hole;
            # the present player is given a forfeit win in ``create_boards``.
            stored_boards.append(
                StoredBoard(
                    id=None,
                    white_player_id=white_player.id if white_player else None,
                    black_player_id=black_player.id if black_player else None,
                    index=index,
                )
            )
        return stored_boards

    @override
    def generate_pairings(
        self,
        tournament: 'Tournament',
        round_: int,
        partial_pairings: bool = False,
    ) -> str:
        if self.pairings_generation_disabled_message(tournament, round_):
            raise ValueError(
                f'Pairings generation not allowed for round {round_} '
                f'of tournament [{tournament.name}].'
            )
        try:
            stored_boards = self._generate_stored_boards(tournament, round_)
        except Exception as e:
            from common.logger import get_logger

            get_logger().exception(e)
            return _('An error occurred. Consult the logs for more details.')
        if not stored_boards:
            return _('Pairing is not possible.')
        # Route through ``tournament.create_boards``: it inserts the
        # ``StoredBoard`` rows AND wires up each player's ``Pairing`` to
        # the new ``board_id``, which is required for result entry. The
        # PAB branches inside are dead code for flat fixed-table systems
        # (every board has both players) but harmless.
        tournament.create_boards(stored_boards, round_, self.pab_result)
        return ''

    def _combined_pairings_or_empty(
        self,
        tournament: 'Tournament',
        round_: int,
        team_count: int,
        players_per_team: int,
    ) -> list[TablePairing]:
        """The round's pairings, or nothing when this tournament's shape
        has no usable table.

        The read-only callers below run on every render of the pairings
        tab, including when the system was picked for a shape it cannot
        pair (say a two-team system on three teams). That has to leave
        the tab standing — the pairing buttons carry
        ``invalid_player_count_message`` to explain it — rather than
        raise out of the page. Generation itself still fails loudly.
        """
        try:
            return self._build_combined_pairings(
                tournament, round_, team_count, players_per_team
            )
        except SharlyChessException:
            return []

    def team_by_letter(self, tournament: 'Tournament') -> dict[str, 'Team']:
        """The table's team-letter assignment (``'A'`` = first team in
        the canonical order, ``'B'`` = second, …)."""
        return {
            chr(ord('A') + i): team
            for i, team in enumerate(self._teams_for_tournament(tournament))
        }

    def board_references(
        self, tournament: 'Tournament', round_: int
    ) -> list[tuple[str, str]]:
        """Per board (in board-index order), the table's player
        references for the round — ``(white_ref, black_ref)``, e.g.
        ``('A1', 'B3')`` = first player of team A (white) vs third
        player of team B."""
        teams = self._teams_for_tournament(tournament)
        n = tournament.team_player_count or 0
        if not teams or n <= 0:
            return []
        return [
            (
                f'{p.white_team}{p.white_index}',
                f'{p.black_team}{p.black_index}',
            )
            for p in self._combined_pairings_or_empty(tournament, round_, len(teams), n)
        ]

    def round_team_by_letter(
        self, tournament: 'Tournament', round_: int
    ) -> dict[str, 'Team']:
        """The letter assignment actually used when ``round_`` was
        paired, recovered from the stored boards (the canonical team
        order may have changed since). Majority vote across the
        round's seats, so isolated manual substitutions don't skew
        the mapping. Falls back to the current canonical assignment
        when the round has no boards."""
        from collections import Counter

        teams = self._teams_for_tournament(tournament)
        n = tournament.team_player_count or 0
        if not teams or n <= 0:
            return {}
        boards = sorted(tournament.get_round_boards(round_), key=lambda b: b.index)
        votes: dict[str, Counter] = {}
        for board, p in zip(
            boards,
            self._combined_pairings_or_empty(tournament, round_, len(teams), n),
        ):
            wtp = board.optional_white_tournament_player
            btp = board.black_tournament_player
            if wtp is not None and wtp.team is not None:
                votes.setdefault(p.white_team, Counter())[wtp.team.id] += 1
            if btp is not None and btp.team is not None:
                votes.setdefault(p.black_team, Counter())[btp.team.id] += 1
        letters = {
            letter: tournament.event.teams_by_id[counter.most_common(1)[0][0]]
            for letter, counter in votes.items()
            if counter
        }
        return letters or self.team_by_letter(tournament)

    def round_seats(
        self, tournament: 'Tournament', round_: int
    ) -> dict[tuple[int, int], tuple[int, str]]:
        """Map ``(team_id, slot)`` (0-based intra-team slot) to
        ``(board_index, side)`` for the given round, straight from the
        pairing table. Boards are created in table order with
        ``index = enumerate position``, so the mapping addresses the
        round's stored boards even when a seat is currently a hole."""
        teams = self._teams_for_tournament(tournament)
        n = tournament.team_player_count or 0
        if not teams or n <= 0:
            return {}
        team_by_letter: dict[str, 'Team'] = {
            chr(ord('A') + i): team for i, team in enumerate(teams)
        }
        seats: dict[tuple[int, int], tuple[int, str]] = {}
        for index, p in enumerate(
            self._combined_pairings_or_empty(tournament, round_, len(teams), n)
        ):
            white_team = team_by_letter.get(p.white_team)
            black_team = team_by_letter.get(p.black_team)
            if white_team is not None:
                seats[(white_team.id, p.white_index - 1)] = (index, 'white')
            if black_team is not None:
                seats[(black_team.id, p.black_index - 1)] = (index, 'black')
        return seats

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _teams_for_tournament(tournament: 'Tournament') -> list['Team']:
        return sorted(
            (
                team
                for team in tournament.event.sorted_teams
                if team.tournament_id == tournament.id
            ),
            key=lambda t: (
                t.pairing_number if t.pairing_number is not None else float('inf'),
                t.id,
            ),
        )

    @staticmethod
    def _team_player(team: 'Team', index_1based: int, round_: int):
        # Hole-aware seat lookup: ``effective_round_slots`` is length
        # team_player_count with ``None`` at each hole. No roster fallback —
        # falling back to ``team.players`` would re-seat a benched player and
        # double-book them on a higher board.
        slots = team.effective_round_slots(round_)
        idx = index_1based - 1
        if 0 <= idx < len(slots):
            return slots[idx]
        return None

    def _build_combined_pairings(
        self,
        tournament: 'Tournament',
        round_: int,
        team_count: int,
        players_per_team: int,
    ) -> list[TablePairing]:
        """Build the full list of pairings for the round, combining base
        tables when ``players_per_team`` exceeds the largest tabulated
        player count for ``team_count`` teams. Player indices in trailing
        blocks are offset to refer to the correct intra-team numbers."""
        # Try exact match first.
        exact = self.system.get_table(team_count, players_per_team, tournament)
        if exact is not None:
            return list(exact.round_pairings(round_, tournament.rounds))

        # No exact table — chain in descending-size blocks.
        candidates = sorted(
            (
                pc
                for pc in self._candidate_player_counts(team_count, tournament)
                if pc <= players_per_team
            ),
            reverse=True,
        )
        if not candidates:
            raise SharlyChessException(
                _('No usable table for {t} teams of {p} players.').format(
                    t=team_count, p=players_per_team
                )
            )
        result: list[TablePairing] = []
        remaining = players_per_team
        offset = 0
        while remaining > 0:
            block = next((c for c in candidates if c <= remaining), None)
            if block is None:
                raise SharlyChessException(
                    _(
                        'Cannot tile {remaining} remaining players into '
                        'a base table for {t} teams.'
                    ).format(remaining=remaining, t=team_count)
                )
            table = self.system.get_table(team_count, block, tournament)
            if table is None:
                raise SharlyChessException(
                    _('Missing base table for {t} teams, {p} players.').format(
                        t=team_count, p=block
                    )
                )
            for p in table.round_pairings(round_, tournament.rounds):
                result.append(
                    TablePairing(
                        white_team=p.white_team,
                        white_index=p.white_index + offset,
                        black_team=p.black_team,
                        black_index=p.black_index + offset,
                    )
                )
            remaining -= block
            offset += block
        return result

    def _candidate_player_counts(
        self, team_count: int, tournament: 'Tournament | None' = None
    ) -> tuple[int, ...]:
        """The set of players_per_team values for which we have base tables
        at ``team_count`` teams. Default: probe common sizes."""
        out: list[int] = []
        for pc in (4, 6, 8, 10, 12):
            table = self.system.get_table(team_count, pc, tournament)
            if table is None:
                continue
            if tournament is not None and table.regular_round_count < tournament.rounds:
                continue
            out.append(pc)
        return tuple(out)

    def _max_candidate_round_count(
        self, team_count: int, tournament: 'Tournament | None' = None
    ) -> int | None:
        max_rounds: int | None = None
        for pc in (4, 6, 8, 10, 12):
            table = self.system.get_table(team_count, pc, tournament)
            if table is None:
                continue
            max_rounds = (
                table.regular_round_count
                if max_rounds is None
                else max(max_rounds, table.regular_round_count)
            )
        return max_rounds

import weakref
from functools import cached_property
from typing import TYPE_CHECKING

from collections.abc import Sequence

from common.i18n import _
from database.sqlite.event.event_database import EventDatabase
from utils.enum import TeamByeType
from database.sqlite.event.event_store import (
    StoredTeam,
    StoredTeamGroup,
    StoredTeamRoundLineupEntry,
)

if TYPE_CHECKING:
    from data.event import Event
    from data.player import Player
    from data.tournament import Tournament


class TeamGroup:
    """An event-level reusable team grouping (club / league / …).
    Teams reference one by id; used to keep teams in the same group
    from being paired together."""

    def __init__(self, event: 'Event', stored_team_group: StoredTeamGroup):
        self._event_ref: 'weakref.ReferenceType[Event]' = weakref.ref(event)
        self.stored_team_group = stored_team_group

    @property
    def event(self) -> 'Event':
        event = self._event_ref()
        assert event is not None
        return event

    @property
    def id(self) -> int:
        assert self.stored_team_group.id is not None
        return self.stored_team_group.id

    @property
    def name(self) -> str:
        return self.stored_team_group.name


class RosterFullError(Exception):
    """Raised by :meth:`Team.add_player` when the team is at its
    roster cap (set by the tournament's rule set)."""

    def __init__(self, team: 'Team', max_size: int):
        super().__init__(f'Roster full ({max_size} players) for team {team.name}')
        self.team = team
        self.max_size = max_size


class Team:
    """A team of players competing as a unit in a team tournament."""

    def __init__(self, event: 'Event', stored_team: StoredTeam):
        self._event_ref: 'weakref.ReferenceType[Event]' = weakref.ref(event)
        self.stored_team = stored_team

    @property
    def event(self) -> 'Event':
        if (event := self._event_ref()) is None:
            raise RuntimeError('Event reference has been garbage collected')
        return event

    @property
    def id(self) -> int:
        assert self.stored_team.id is not None
        return self.stored_team.id

    @property
    def name(self) -> str:
        return self.stored_team.name

    @property
    def tournament_id(self) -> int | None:
        return self.stored_team.tournament_id

    @property
    def tournament(self) -> 'Tournament | None':
        if self.tournament_id is None:
            return None
        return self.event.tournaments_by_id.get(self.tournament_id)

    @property
    def pairing_number(self) -> int | None:
        return self.stored_team.pairing_number

    @property
    def pairing_label(self) -> str | None:
        """Human label for the pairing number: a letter (``A``, ``B``, …) for
        systems that address teams alphabetically (round-robin Berger grids,
        Molter tables), otherwise ``#N``. ``None`` when the team has no
        pairing number."""
        number = self.pairing_number
        if number is None:
            return None
        tournament = self.tournament
        if (
            tournament is not None
            and 1 <= number <= 26
            and tournament.pairing_system.uses_team_letters
        ):
            return chr(ord('A') + number - 1)
        return f'#{number}'

    def player_round_label(self, player: 'Player', round_: int) -> str | None:
        """Fixed-table code for ``player`` this round — the team letter plus
        the player's 1-based line-up slot (e.g. ``A1``, ``B3``). Derived from
        the player's actual seat in :meth:`effective_round_slots`, so it
        follows the player wherever they end up (manual re-pairing included),
        independent of which physical board they sit at. ``None`` when the
        team has no letter or the player isn't in this round's line-up."""
        letter = self.pairing_label
        if letter is None:
            return None
        for index, slot_player in enumerate(self.effective_round_slots(round_)):
            if slot_player is not None and slot_player.id == player.id:
                return f'{letter}{index + 1}'
        return None

    @property
    def group_id(self) -> int | None:
        return self.stored_team.group_id

    @property
    def federation(self) -> str:
        return self.stored_team.federation or ''

    @property
    def group(self) -> 'TeamGroup | None':
        group_id = self.stored_team.group_id
        if group_id is None:
            return None
        return self.event.team_groups_by_id.get(group_id)

    @property
    def check_in(self) -> bool:
        """Whether the team is checked in for the current round. Teams
        play whole rounds together — there's no per-player check-in in
        team mode (player check-in is the only mechanism in individual
        mode)."""
        return self.stored_team.check_in

    @property
    def captain(self) -> 'Player | None':
        """The playing captain, when one is set. ``None`` for a
        non-playing captain (see :attr:`captain_display_name`)."""
        captain_id = self.stored_team.captain_id
        if captain_id is None:
            return None
        captain = self.event.players_by_id.get(captain_id)
        # Defensive: if the captain has been removed from the team
        # (or the event), don't claim them as captain.
        if captain is None or captain.stored_player.team_id != self.id:
            return None
        return captain

    @property
    def captain_display_name(self) -> str | None:
        """The captain's name whichever kind is set: the playing
        captain's full name, or the free-typed non-playing captain's
        name. ``None`` when the team has no captain."""
        captain = self.captain
        if captain is not None:
            return captain.full_name
        return self.stored_team.captain_name or None

    @cached_property
    def is_excluded_from_standings(self) -> bool:
        """FIDE 6.6 (team analogue): a team round-robin team that completed
        less than 50% of its matches — every board forfeited, the mark of a
        withdrawn or expelled team — is kept in the crosstable but dropped
        from the final standings, and its matches don't count in the other
        teams' tie-breaks.

        A match counts as not completed when the team forfeited every one of
        its boards (:meth:`TeamBoard.team_all_forfeit`). Two conditions, both
        required:

        - The team did not play its *last* scheduled match (it forfeited
          every board). A team present for its final round was there at the
          end and so did not withdraw, whatever it missed earlier.
        - More than half of its scheduled matches were forfeited this way.

        A match still being played, or a bye, is not counted.
        """
        from data.pairings.systems import TeamRoundRobinPairingSystem

        tournament = self.tournament
        if tournament is None:
            return False
        if not tournament.round_robin_participation_rule:
            return False
        if not isinstance(tournament.pairing_system, TeamRoundRobinPairingSystem):
            return False
        scheduled = [
            team_board
            for team_board in tournament.team_boards_by_id.values()
            if team_board.stored_team_board.team_b_id is not None
            and self.id
            in (
                team_board.stored_team_board.team_a_id,
                team_board.stored_team_board.team_b_id,
            )
        ]
        if not scheduled:
            return False
        last_scheduled = max(scheduled, key=lambda team_board: team_board.round)
        if not last_scheduled.team_all_forfeit(self.id):
            return False
        abandoned = sum(
            1 for team_board in scheduled if team_board.team_all_forfeit(self.id)
        )
        return abandoned * 2 > len(scheduled)

    @property
    def has_been_paired(self) -> bool:
        """True if this team has been paired in at least one round.
        Used to lock cross-tournament drag.

        Two pairing shapes exist: team-board envelopes (Swiss / Berger)
        and flat fixed-table boards (Molter), where each roster player
        gets an individual board with no team envelope. Check both, or
        a Molter-paired team would look unpaired and could be wrongly
        reassigned — orphaning its boards. Standalone manual byes do not
        count as pairings, just as a player's boardless bye does not."""
        tournament = self.tournament
        if tournament is None:
            return False
        manual_bye_types = TeamByeType.manual_bye_types()
        if any(
            (
                tb.stored_team_board.team_a_id == self.id
                or tb.stored_team_board.team_b_id == self.id
            )
            and not (
                tb.stored_team_board.team_b_id is None
                and tb.stored_team_board.bye_type in manual_bye_types
            )
            for tb in tournament.team_boards_by_id.values()
        ):
            return True
        # Flat (Molter) pairings: any roster player carrying a board.
        player_ids = {p.id for p in self.players}
        if not player_ids:
            return False
        return any(
            pairing.stored_pairing.board_id is not None
            for tournament_player in tournament.tournament_players
            if tournament_player.id in player_ids
            for pairing in tournament_player.pairings_by_round.values()
        )

    @cached_property
    def players(self) -> list['Player']:
        """Players belonging to this team, ordered by *team_index*.
        Players without an index are sorted last by id."""
        return sorted(
            (
                player
                for player in self.event.players_by_id.values()
                if player.stored_player.team_id == self.id
            ),
            key=lambda p: (
                p.team_index if p.team_index is not None else float('inf'),
                p.id,
            ),
        )

    @cached_property
    def players_by_id(self) -> dict[int, 'Player']:
        return {player.id: player for player in self.players}

    @property
    def average_rating(self) -> int | None:
        """Mean of the roster's event-default ratings, rounded. ``None``
        if no player on the roster has a rating."""
        ratings = [r for r in (p.event_default_rating for p in self.players) if r]
        if not ratings:
            return None
        return round(sum(ratings) / len(ratings))

    def lineup_average_rating(self, round_: int) -> int | None:
        """Mean event-default rating of the players fielded in *round_*'s
        effective lineup (holes skipped), rounded. ``None`` when no
        fielded player has a rating."""
        ratings = [
            p.event_default_rating
            for p in self.effective_round_lineup(round_)
            if p.event_default_rating
        ]
        if not ratings:
            return None
        return round(sum(ratings) / len(ratings))

    @property
    def roster_warning_message(self) -> str | None:
        """Combined roster warnings for the team card: a generic over-cap
        warning when the roster exceeds the tournament's maximum size, plus
        any rule-set-specific warnings (rating ceilings, composition…).
        Returns ``None`` when the roster is clean. Rendered as a triangle +
        tooltip on the team card."""
        warnings: list[str] = []
        max_size = self.roster_max_size
        if max_size is not None and len(self.players) > max_size:
            warnings.append(
                _('The roster has %(count)d players, more than the maximum of %(max)d.')
                % {'count': len(self.players), 'max': max_size}
            )
        tournament = self.tournament
        rule_set = tournament.rule_set if tournament else None
        if rule_set is not None:
            warnings.extend(rule_set.roster_warnings(self))
        return ' '.join(warnings) or None

    @property
    def lineups_by_round(self) -> dict[int, list['Player']]:
        """Per-round lineup as a list of players ordered by board index.
        Missing rounds are absent from the dict."""
        result: dict[int, list['Player']] = {}
        players_by_id = self.event.players_by_id
        for round_, entries in self.stored_team.stored_round_lineups.items():
            ordered = sorted(entries, key=lambda e: e.index)
            result[round_] = [
                players_by_id[entry.player_id]
                for entry in ordered
                if entry.player_id in players_by_id
            ]
        return result

    def get_round_lineup(self, round_: int) -> list['Player']:
        return self.lineups_by_round.get(round_, [])

    def has_explicit_round_lineup(self, round_: int) -> bool:
        return round_ in self.stored_team.stored_round_lineups

    def effective_round_lineup(self, round_: int) -> list['Player']:
        """Lineup applied for *round_* as a compact (no-hole) list of
        players. The stored override if any; otherwise, for rounds after
        the first, the *previous* round's effective lineup (which chains
        back to round 1); round 1 (or no tournament) falls back to the
        first *team_player_count* roster players. Holes are skipped —
        use :meth:`effective_round_slots` to see them."""
        if self.has_explicit_round_lineup(round_):
            return self.get_round_lineup(round_)
        tournament = self.tournament
        if tournament is None:
            # No tournament yet: the base lineup is the whole roster
            # (the roster size stands in for the board count).
            return list(self.players)
        if tournament.team_player_count is None:
            return []
        if round_ > 1:
            return self.effective_round_lineup(round_ - 1)
        return self.players[: tournament.team_player_count]

    def lineup_source(self, round_: int) -> str:
        """How *round_*'s effective lineup is obtained: ``'explicit'`` when
        a lineup is stored, ``'roster'`` for round 1 (or no tournament) with
        none stored, else ``'previous'`` (inherited from the prior round).
        Drives the editor's labelling and the "use previous" checkbox."""
        if self.has_explicit_round_lineup(round_):
            return 'explicit'
        if self.tournament is None or round_ <= 1:
            return 'roster'
        return 'previous'

    def effective_round_slots(
        self, round_: int, board_count: int | None = None
    ) -> list['Player | None']:
        """Lineup applied for *round_* as a list of length
        ``team_player_count``, with ``None`` at each board index where
        the team has a hole (no player on that slot for this round).
        Slot K is filled by the stored lineup entry whose ``index``
        equals K. When no explicit lineup is stored, the first
        ``team_player_count`` roster players fill slots 0…N-1
        contiguously.

        ``board_count`` overrides the slot count — used to edit a base
        lineup for a team not yet assigned to a tournament (where the
        roster size stands in for the board count)."""
        if board_count is not None:
            n = board_count
        else:
            tournament = self.tournament
            if tournament is None or tournament.team_player_count is None:
                return []
            n = tournament.team_player_count
        slots: list['Player | None'] = [None] * n
        if self.has_explicit_round_lineup(round_):
            players_by_id = self.event.players_by_id
            for entry in self.stored_team.stored_round_lineups[round_]:
                if 0 <= entry.index < n and entry.player_id in players_by_id:
                    slots[entry.index] = players_by_id[entry.player_id]
            return slots
        # No stored lineup: rounds after the first inherit the previous
        # round's lineup (chains back to round 1's roster default). The
        # ``board_count`` override is the base-lineup editor for a team not
        # yet in a tournament — that's always round-1 / roster semantics.
        if board_count is None and round_ > 1:
            return self.effective_round_slots(round_ - 1)
        roster = self.players[:n]
        for i, player in enumerate(roster):
            slots[i] = player
        return slots

    def round_board_slots(self, round_: int) -> list['Player | None'] | None:
        """Per-board occupants for *round_* read from the actual paired
        boards — the source of truth once a round is paired. Length is
        ``team_player_count``, ``None`` at each board the team left as a
        hole. Returns ``None`` when this team has no team-vs-team board for
        the round (unpaired, or a bye), so callers fall back to
        :meth:`effective_round_slots`. Unlike that method, this never
        invents a default roster, so it stays consistent with what the
        pairings tab shows even when no explicit lineup was stored."""
        tournament = self.tournament
        if tournament is None or tournament.team_player_count is None:
            return None
        team_board = next(
            (
                tb
                for tb in tournament.get_round_team_boards(round_)
                if tb.stored_team_board.team_b_id is not None
                and self.id
                in (
                    tb.stored_team_board.team_a_id,
                    tb.stored_team_board.team_b_id,
                )
            ),
            None,
        )
        if team_board is None:
            return None
        n = tournament.team_player_count
        slots: list['Player | None'] = [None] * n
        players_by_id = self.event.players_by_id
        # Which line-up slot each board seats this team's player on. A
        # match seats slot i on board i, but a table that rotates one
        # team around the other does not.
        slot_by_board_index = tournament.pairing_variation.engine.team_board_slots(
            tournament, team_board, self.id
        )
        for board in team_board.boards:
            slot = slot_by_board_index.get(board.index)
            if slot is None or not 0 <= slot < n:
                continue
            for player_id in (
                board.stored_board.white_player_id,
                board.stored_board.black_player_id,
            ):
                player = players_by_id.get(player_id) if player_id else None
                if player is not None and player.team_id == self.id:
                    slots[slot] = player
                    break
        return slots

    def lineup_out_of_roster_order(self, round_: int) -> bool:
        """True iff *round_*'s board players (holes skipped) are not in
        ascending roster order. Used to warn when a line-up reshuffles
        players relative to the roster."""
        roster_index = {player.id: i for i, player in enumerate(self.players)}
        last = -1
        for player in self.effective_round_lineup(round_):
            idx = roster_index.get(player.id)
            if idx is None:
                continue
            if idx < last:
                return True
            last = idx
        return False

    # -------------------------------------------------------------------------
    # Mutations
    # -------------------------------------------------------------------------

    def update(self, database: EventDatabase):
        database.update_stored_team(self.stored_team)

    def _delete_boardless_player_pairings(
        self,
        tournament: 'Tournament',
        database: EventDatabase,
    ) -> None:
        """Delete boardless player records when leaving ``tournament``.

        Player pairing records are scoped to their tournament. A movable
        team has no player attached to a real board, so its old boardless
        records must not remain behind after its tournament assignment
        changes.
        """
        for player in self.players:
            tournament_player = tournament.tournament_players_by_id.get(player.id)
            if tournament_player is None:
                continue
            stored_pairings = tournament_player.stored_tournament_player.stored_pairings
            kept_pairings = []
            for stored_pairing in stored_pairings:
                if stored_pairing.board_id is None:
                    database.delete_stored_pairing(stored_pairing)
                else:
                    kept_pairings.append(stored_pairing)
            tournament_player.stored_tournament_player.stored_pairings = kept_pairings
            tournament_player.__dict__.pop('pairings_by_round', None)

    def set_tournament(self, tournament_id: int | None, database: EventDatabase):
        old_tournament = self.tournament
        if self.stored_team.tournament_id == tournament_id:
            return

        # Standalone team byes are not pairings and therefore do not prevent
        # a tournament move. Remove those old-tournament envelopes before
        # changing the assignment. Also discard any boardless player records
        # left by older team-TRF imports; player round records are scoped to
        # the tournament the team is leaving.
        if old_tournament is not None:
            manual_bye_types = TeamByeType.manual_bye_types()
            for round_, round_list in list(
                old_tournament.stored_tournament.stored_team_boards_by_round.items()
            ):
                kept = []
                for stored_team_board in round_list:
                    is_own_manual_bye = (
                        stored_team_board.team_a_id == self.id
                        and stored_team_board.team_b_id is None
                        and stored_team_board.bye_type in manual_bye_types
                    )
                    if is_own_manual_bye:
                        if stored_team_board.id is not None:
                            database.delete_stored_team_board(stored_team_board.id)
                    else:
                        kept.append(stored_team_board)
                if kept:
                    old_tournament.stored_tournament.stored_team_boards_by_round[
                        round_
                    ] = kept
                else:
                    old_tournament.stored_tournament.stored_team_boards_by_round.pop(
                        round_, None
                    )

            self._delete_boardless_player_pairings(old_tournament, database)
            old_tournament.clear_team_cache()

        # Pairing numbers are scoped to a tournament; moving a team to
        # a different tournament invalidates whatever number it had
        # (and worse, can silently collide with an existing team's
        # pairing number on the new side — TRF26 export then emits
        # duplicate TPNs and downstream records become ambiguous).
        # Clear it on every transition.
        self.stored_team.pairing_number = None
        database.set_team_pairing_number(self.id, None)
        self.stored_team.tournament_id = tournament_id
        database.set_team_tournament(self.id, tournament_id)
        if tournament_id is not None:
            new_tournament = self.event.tournaments_by_id.get(tournament_id)
            if new_tournament is not None:
                new_tournament.clear_team_cache()

    def set_pairing_number(self, pairing_number: int | None, database: EventDatabase):
        self.stored_team.pairing_number = pairing_number
        database.set_team_pairing_number(self.id, pairing_number)

    def set_captain(
        self,
        captain_id: int | None,
        captain_name: str | None,
        database: EventDatabase,
    ):
        """Set this team's captain: a playing captain by ``captain_id``
        (must belong to this team's roster — caller enforces), or a
        non-playing one by free-typed ``captain_name``. The two are
        mutually exclusive; pass both ``None`` to clear."""
        if captain_id is not None:
            captain_name = None
        self.stored_team.captain_id = captain_id
        self.stored_team.captain_name = captain_name
        database.set_team_captain(self.id, captain_id, captain_name)

    def set_group(self, group_id: int | None, database: EventDatabase):
        self.stored_team.group_id = group_id
        database.set_team_group(self.id, group_id)

    def set_check_in(self, check_in: bool, database: EventDatabase):
        self.stored_team.check_in = check_in
        database.set_team_check_in(self.id, check_in)

    def set_round_lineup(
        self,
        round_: int,
        player_ids: Sequence[int | None],
        database: EventDatabase,
    ):
        """Replace the team's lineup for the given round. Position in
        *player_ids* determines the board index (0-based). ``None``
        at index i = hole on board i (no row stored for that index,
        producing a gap in the lineup's index sequence)."""
        entries = [
            StoredTeamRoundLineupEntry(
                team_id=self.id,
                round_=round_,
                player_id=player_id,
                index=index,
            )
            for index, player_id in enumerate(player_ids)
            if player_id is not None
        ]
        database.replace_team_round_lineup(self.id, round_, entries)
        self.stored_team.stored_round_lineups[round_] = entries

    def delete_round_lineup(self, round_: int, database: EventDatabase):
        database.delete_team_round_lineup(self.id, round_)
        self.stored_team.stored_round_lineups.pop(round_, None)

    def round_bye_type(self, round_: int) -> str | None:
        """Bye-type marker (``PAB`` / ``HPB`` / ``FPB`` / ``ZPB``) for this
        team in *round_*, or ``None`` if the team has no bye envelope
        that round."""
        tournament = self.tournament
        if tournament is None:
            return None
        for tb in tournament.get_round_team_boards(round_):
            stb = tb.stored_team_board
            if stb.team_a_id == self.id and stb.team_b_id is None:
                return stb.bye_type
        return None

    def set_round_bye(
        self,
        round_: int,
        bye_type: str | None,
        database: EventDatabase,
    ) -> None:
        """Pre-mark the team's round as a bye (PAB / HPB / FPB / ZPB).
        Persisted as a ``team_board`` envelope with ``team_b_id``
        ``None`` and the chosen ``bye_type`` — the pairing engine
        respects existing bye envelopes and won't pair the team into
        the round.

        Passing ``None`` removes any existing bye envelope for the
        round. Caller is responsible for ensuring the team isn't
        currently in a paired team_board (the unpaired-side UI is the
        only place this is reachable from)."""
        assert self.tournament_id is not None, (
            'Cannot set a round bye on a team with no tournament.'
        )
        tournament = self.tournament
        assert tournament is not None
        round_list = (
            tournament.stored_tournament.stored_team_boards_by_round.setdefault(
                round_, []
            )
        )
        existing = next(
            (
                stb
                for stb in round_list
                if stb.team_a_id == self.id and stb.team_b_id is None
            ),
            None,
        )
        if bye_type is None:
            if existing is not None and existing.id is not None:
                database.delete_stored_team_board(existing.id)
                round_list.remove(existing)
                tournament.clear_team_cache()
            return
        if existing is not None:
            existing.bye_type = bye_type
            database.update_stored_team_board(existing)
            tournament.clear_team_cache()
            return
        from database.sqlite.event.event_store import StoredTeamBoard

        # Hidden byes (HPB / FPB / ZPB) don't sit at a table → no table
        # number. A PAB is displayed, so it takes the next number after
        # the real matches.
        if bye_type == TeamByeType.PAB:
            index: int | None = (
                max(
                    (stb.index for stb in round_list if stb.index is not None),
                    default=-1,
                )
                + 1
            )
        else:
            index = None
        stb = StoredTeamBoard(
            id=None,
            tournament_id=self.tournament_id,
            round_=round_,
            team_a_id=self.id,
            team_b_id=None,
            index=index,
            bye_type=bye_type,
        )
        stb.id = database.add_stored_team_board(stb)
        round_list.append(stb)
        tournament.clear_team_cache()

    def give_byes_for_paired_rounds(self, database: EventDatabase) -> None:
        """Zero-point-bye this team for every already-paired round —
        the team counterpart of the ZPB rows a late-added player gets
        in :meth:`Tournament.add_player_to_tournament`. The current
        round is included only once its results are complete (an
        in-play round leaves the team in the to-pair column instead).
        No-op for unassigned teams and non-team-paired systems."""
        tournament = self.tournament
        if tournament is None or not tournament.pairing_system.paired_by_team:
            return
        last_paired = tournament.last_paired_round
        if not last_paired:
            return
        last_zpb_round = (
            last_paired
            if tournament.team_round_results_complete(last_paired)
            else last_paired - 1
        )
        for round_ in range(1, last_zpb_round + 1):
            in_envelope = any(
                stb.team_a_id == self.id or stb.team_b_id == self.id
                for stb in tournament.stored_tournament.stored_team_boards_by_round.get(
                    round_, []
                )
            )
            if not in_envelope:
                self.set_round_bye(round_, TeamByeType.ZPB, database)

    # -------------------------------------------------------------------------
    # Roster
    # -------------------------------------------------------------------------

    def _invalidate_players(self):
        if 'players' in self.__dict__:
            del self.__dict__['players']
        if 'players_by_id' in self.__dict__:
            del self.__dict__['players_by_id']

    @property
    def roster_max_size(self) -> int | None:
        """Roster cap configured on the team's tournament (set directly or
        by its rule set), or ``None`` (uncapped). Centralised so every add
        path obeys it."""
        tournament = self.tournament
        return tournament.roster_max_size if tournament else None

    def add_player(self, player: 'Player', database: EventDatabase):
        """Add a player to the team's roster.
        Removes the player from any previous team (event-wide uniqueness).
        Appends at the end of the roster ordering.

        Raises :class:`RosterFullError` when adding would exceed the
        rule-set roster cap."""
        previous_team_id = player.stored_player.team_id
        if previous_team_id == self.id:
            return
        max_size = self.roster_max_size
        if max_size is not None and len(self.players) >= max_size:
            raise RosterFullError(self, max_size)
        next_index = (
            max(
                (p.team_index for p in self.players if p.team_index is not None),
                default=-1,
            )
            + 1
        )
        player.stored_player.team_id = self.id
        player.stored_player.team_index = next_index
        database.set_player_team(player.id, self.id, next_index)
        self._invalidate_players()
        player.invalidate_team_derived_cache()
        if self.tournament is not None:
            self.tournament.register_rostered_player(player.id)
        if previous_team_id is not None:
            previous_team = self.event.teams_by_id.get(previous_team_id)
            if previous_team is not None:
                # Losing its captain to another team leaves the previous
                # team captainless.
                if previous_team.stored_team.captain_id == player.id:
                    previous_team.set_captain(None, None, database)
                previous_team._invalidate_players()
                previous_team._compact_indexes(database)
                previous_tournament = previous_team.tournament
                if previous_tournament is not None and previous_tournament.id != (
                    self.tournament.id if self.tournament else None
                ):
                    previous_tournament.unregister_rostered_player(player.id)

    def remove_player(self, player: 'Player', database: EventDatabase):
        """Remove a player from this team. Compacts remaining indexes."""
        if player.stored_player.team_id != self.id:
            return
        if self.stored_team.captain_id == player.id:
            self.set_captain(None, None, database)
        player.stored_player.team_id = None
        player.stored_player.team_index = None
        database.set_player_team(player.id, None, None)
        self._invalidate_players()
        player.invalidate_team_derived_cache()
        if self.tournament is not None:
            self.tournament.unregister_rostered_player(player.id)
        self._compact_indexes(database)

    def _compact_indexes(self, database: EventDatabase):
        """Renumber remaining players' team_index sequentially from 0."""
        remaining = self.players
        if not remaining:
            return
        ids = [p.id for p in remaining]
        for new_index, p in enumerate(remaining):
            p.stored_player.team_index = new_index
        database.reorder_team_players(self.id, ids)
        self._invalidate_players()

    def reorder_players(self, ordered_player_ids: list[int], database: EventDatabase):
        """Reorder roster players. Silently ignores ids not on this team."""
        current_ids = {p.id for p in self.players}
        filtered = [pid for pid in ordered_player_ids if pid in current_ids]
        # Append any missing roster members (defensive)
        for pid in current_ids:
            if pid not in filtered:
                filtered.append(pid)
        for new_index, pid in enumerate(filtered):
            player = self.event.players_by_id[pid]
            player.stored_player.team_index = new_index
        database.reorder_team_players(self.id, filtered)
        self._invalidate_players()

    def __repr__(self) -> str:
        return (
            f'{self.__class__.__name__}(id={self.id!r}, name={self.name!r}, '
            f'tournament_id={self.tournament_id!r}, '
            f'pairing_number={self.pairing_number!r})'
        )

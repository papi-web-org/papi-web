import re
from collections import defaultdict
from datetime import datetime, date
from typing import TYPE_CHECKING, Any

from common.exception import ImporterError
from common.i18n import _
from common.sharly_chess_config import SharlyChessConfig
from data.event import Event
from data.input_output.tournament_importer_options import (
    TournamentImporterOption,
    FileOption,
    TournamentRatingOption,
)
from data.input_output.tournament_importers import FileTournamentImporter
from data.input_output.trf.trf_data import (
    TRF_DATE_FORMAT,
    TrfGame,
    TrfPlayer,
    TrfTournament,
)
from data.input_output.trf.trf_mappers import (
    TrfPlayerGender,
    TrfColor,
    TrfResult,
    TrfPlayerTitle,
    TrfEncodedType,
    TrfPointSystemResult,
)
from data.input_output.trf.trf_serializer import TrfSerializer
from data.pairings.settings import ColorSeedSetting
from data.tie_breaks import TieBreak, TieBreakManager
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredBoard,
    StoredPairing,
    StoredPlayer,
    StoredTeam,
    StoredTeamBoard,
    StoredTeamRoundLineupEntry,
    StoredTournament,
    StoredTournamentPlayer,
    set_stored_fields,
)
from plugins.manager import plugin_manager
from utils import Utils
from utils.enum import (
    TournamentRating,
    Result,
    BoardColor,
    PlayerRatingType,
    TeamByeType,
)
from utils.time_control import parse_time_control_trf25
from utils.types import PlayerRating

if TYPE_CHECKING:
    from data.tournament import Tournament


class TrfTournamentImporter(FileTournamentImporter):
    #: TRF26 172 starting-rank methods, mapped to the rating a
    #: tournament here would be set to. ``HBFN`` / ``LBFN`` (highest /
    #: lowest of the two) and ``OTHER`` have no equivalent and are
    #: reported instead.
    STARTING_RANK_RATING_TYPES: dict[str, PlayerRatingType] = {
        'FIDE': PlayerRatingType.FIDE,
        'FIDON': PlayerRatingType.FIDE,
        'NRO': PlayerRatingType.NATIONAL,
        'NIDOF': PlayerRatingType.NATIONAL,
    }

    @staticmethod
    def static_id() -> str:
        return 'TRF'

    @staticmethod
    def static_name() -> str:
        return _('TRF file')

    @property
    def tie_breaks_are_authoritative(self) -> bool:
        # Record 212 lists the criteria that define the standings, so a
        # file omitting PTS ranks without the score on purpose. Record
        # 202 only lists what breaks ties, and `_read_trf_tournament`
        # prepends PTS for it.
        return True

    @staticmethod
    def available_options() -> list[type[TournamentImporterOption]]:
        return [
            FileOption,
            TournamentRatingOption,
        ]

    @property
    def modal_title(self) -> str:
        return _('Import TRF file')

    @property
    def accepted_file_suffixes(self) -> list[str]:
        return ['.trf', '.trfx']

    @property
    def on_file_selected_post_route_name(self) -> str | None:
        return 'tournament-import-check-trf'

    # Populated during ``load_stored_tournament`` for tournaments that
    # carry TRF26 team rosters (310 records). Each entry is the
    # ``StoredTeam`` to insert plus the original TRF player ids that
    # belong to it — we resolve those to internal ids in
    # ``_write_stored_tournament`` once the players are persisted.
    _pending_teams: list[tuple[StoredTeam, list[int]]]
    # ``(round, TPN of team)`` → list of TRF player ids in board order,
    # extracted from 300 records. ``None`` entries mark empty slots.
    _pending_oodo: dict[tuple[int, int], list[int | None]]
    # ``(round, frozenset({a_tpn, b_tpn}))`` → ``(team_a_tpn,
    # team_b_tpn)`` in the original source's orientation, taken from
    # the first 300 record for each match-pair. Drives which team
    # appears on the left of the round display.
    _pending_oodo_orientation: dict[tuple[int, frozenset[int]], tuple[int, int]]
    # round → TPN of the team that got the team-level PAB that round
    # (from 320).
    _pending_pab_team_by_round: dict[int, int]
    # (round, TPN) → bye_type string ('HPB' / 'FPB' / 'ZPB') from 240
    # records. Applied to the team's bye envelope during team_board
    # reconstruction.
    _pending_manual_team_byes: dict[tuple[int, int], str]
    # (round, TPN) → (mp_delta, gp_delta) from 299 records — the
    # arbiter's manual team bonus / penalty points, applied once the
    # teams are persisted and TPNs resolve to team ids.
    _pending_point_adjustments: dict[tuple[int, int], tuple[float, float]]
    # round → list of prohibited-pairing groups (each a list of pairing
    # numbers) from 260 records, expanded per round. Resolved to member
    # ids and written as per-round snapshots once the tournament is live.
    _pending_prohibited_snapshots: dict[int, list[list[int]]]

    def load_stored_tournament(
        self, event: Event, stored_tournament: StoredTournament | None = None
    ) -> tuple[StoredTournament, list[StoredPlayer]]:
        (file_path, tournament_rating) = self.get_option_values()
        with open(file_path, 'r', encoding='utf-8') as file:
            trf_tournament = TrfSerializer.load(file)
        self._check_team_event_compatibility(event, trf_tournament)
        stored_tournament = self._read_trf_tournament(
            event, trf_tournament, stored_tournament
        )
        self._populate_acceleration(event, stored_tournament, trf_tournament)
        stored_tournament.rating = tournament_rating
        self._pending_teams = self._read_trf_teams(trf_tournament)
        # OOdO records (TRF26 300) carry the per-round team lineups in
        # board order; the team-board reconstruction below uses them to
        # set ``board.index`` correctly even when historical lineups
        # diverge from the current 310 roster.
        self._pending_oodo = self._read_trf_oodo_records(trf_tournament)
        self._pending_oodo_orientation = self._read_trf_oodo_match_orientation(
            trf_tournament
        )
        # 320 carries the team-PAB schedule per round so we can
        # synthesise a (team, None) envelope for teams that got the
        # round bye even though they don't appear in any 300 record.
        if trf_tournament.team_pabs is not None:
            self._pending_pab_team_by_round = dict(
                trf_tournament.team_pabs.team_id_by_round
            )
        else:
            self._pending_pab_team_by_round = {}
        # 240 records: per-round manual team byes (F/H/Z). Stash for
        # the team-board reconstruction step in
        # ``_write_stored_tournament`` to apply.
        self._pending_manual_team_byes = self._read_trf_manual_team_byes(trf_tournament)
        # 299 records: manual team bonus / penalty points, keyed by
        # (round, TPN). Applied once teams are persisted.
        self._pending_point_adjustments = {}
        for assignment in trf_tournament.abnormal_points_assignments:
            if assignment.round is None:
                continue
            mp = assignment.match_points or 0.0
            gp = assignment.game_points or 0.0
            if not mp and not gp:
                continue
            for tpn in assignment.pairing_numbers:
                if tpn:
                    self._pending_point_adjustments[(assignment.round, tpn)] = (mp, gp)
        # 260 records: prohibited pairings, expanded to per-round groups
        # of pairing numbers. Resolved + written as snapshots post-import.
        self._pending_prohibited_snapshots = {}
        for prohibited in trf_tournament.prohibited_pairings:
            numbers = [number for number in prohibited.pairing_numbers if number]
            if len(numbers) < 2:
                continue
            last_round = (
                prohibited.last_round
                if prohibited.last_round is not None
                else prohibited.first_round
            )
            for round_ in range(prohibited.first_round, last_round + 1):
                self._pending_prohibited_snapshots.setdefault(round_, []).append(
                    numbers
                )
        if self._pending_prohibited_snapshots:
            self.post_import_task.append(self._apply_prohibited_pairings)

        next_board_id = 1
        board_id_by_player_id_by_round: dict[int, dict[int, int]] = defaultdict(dict)
        stored_boards_by_round: dict[int, list[StoredBoard]] = defaultdict(list)
        stored_players: list[StoredPlayer] = []
        for trf_player in trf_tournament.players:
            player_id = trf_player.id
            try:
                self._validate_trf_player(trf_player)
            except ImporterError as exception:
                raise ImporterError(
                    _('Player [{player_id}]: {error}').format(
                        player_id=player_id,
                        error=exception,
                    )
                )
            stored_player = self._read_trf_player(
                trf_player, TournamentRating(tournament_rating), event
            )
            stored_tournament_player = StoredTournamentPlayer(
                player_id=player_id,
                pairing_number=trf_player.id,
            )
            for trf_game in trf_player.games:
                if trf_game.round > stored_tournament.rounds:
                    stored_tournament.rounds = trf_game.round
                round_nb = trf_game.round
                try:
                    self._validate_trf_game(trf_game)
                except ImporterError as exception:
                    raise ImporterError(
                        _('Player [{player_id}] - round {round}: ').format(
                            player_id=player_id,
                            round=round_nb,
                        )
                        + str(exception)
                    )
                # In a team TRF, 240 is authoritative for team F/H/Z byes.
                # A no-opponent 001 block is player-level information:
                # 0000 / "-" / blank (equivalent to Z) is also the
                # specification's representation for a roster member who
                # was not nominated. Sharly has no individual-bye state in
                # a team tournament, so do not turn these Z/H/F blocks into
                # persisted player pairings. The team envelope is rebuilt
                # separately from 240.
                result = TrfResult.get_core_object(
                    trf_game.result, has_opponent=bool(trf_game.opponent_id)
                )
                if (
                    event.is_team_event
                    and not trf_game.opponent_id
                    and result.is_no_board_bye
                ):
                    continue
                stored_pairing, stored_board = self._read_trf_game(trf_game, player_id)
                if stored_board:
                    if player_id in board_id_by_player_id_by_round[round_nb]:
                        board_id = board_id_by_player_id_by_round[round_nb][player_id]
                    else:
                        board_id = next_board_id
                        next_board_id += 1
                        set_stored_fields(stored_board, id=board_id)
                        stored_boards_by_round[round_nb].append(stored_board)
                        if trf_game.opponent_id:
                            board_id_by_player_id_by_round[round_nb][
                                trf_game.opponent_id
                            ] = board_id
                    stored_pairing.board_id = board_id
                stored_tournament_player.stored_pairings.append(stored_pairing)
            stored_players.append(stored_player)
            stored_tournament.stored_tournament_players.append(stored_tournament_player)
        stored_tournament.stored_boards_by_round = stored_boards_by_round
        if stored_boards_by_round:
            # Widen only — the 142 ``num_rounds`` value (set in
            # ``_read_trf_tournament``) is the source of truth for the
            # total round count; we just need to make sure it covers
            # any actually-played rounds we found above.
            stored_tournament.rounds = max(
                stored_tournament.rounds, max(stored_boards_by_round)
            )
        return stored_tournament, stored_players

    def _apply_prohibited_pairings(self, tournament: 'Tournament') -> None:
        """Resolve the parsed 260 pairing numbers to member ids (players
        for an individual tournament, teams for a team one) and write
        them as per-round prohibited-pairing snapshots. Imported groups
        are hard (260 carries no hard/soft distinction)."""
        if not self._pending_prohibited_snapshots:
            return
        is_team = tournament.is_team_tournament
        with EventDatabase(tournament.event.uniq_id, True) as database:
            for round_, number_groups in self._pending_prohibited_snapshots.items():
                groups: list[tuple[bool, list[int]]] = []
                for numbers in number_groups:
                    member_ids: list[int] = []
                    for number in numbers:
                        member: Any
                        if is_team:
                            member = tournament.teams_by_pairing_number.get(number)
                        else:
                            member = (
                                tournament.tournament_players_by_pairing_number.get(
                                    number
                                )
                            )
                        if member is not None:
                            member_ids.append(member.id)
                    if len(member_ids) >= 2:
                        groups.append((True, member_ids))
                if groups:
                    database.replace_round_prohibited_pairing_snapshot(
                        tournament.id, round_, groups
                    )

    def get_not_importable_features(self, event: Event) -> list[str]:
        file_path = self.get_option_values()[0]
        with open(file_path, 'r', encoding='utf-8') as file:
            tournament = TrfSerializer.load(file)
        features: list[str] = []
        if tournament.teams and not event.is_team_event:
            features.append(
                _(
                    'Team tournament file in an individual event — '
                    'create a team event first.'
                )
            )
        elif event.is_team_event and not tournament.teams:
            features.append(
                _(
                    'Individual tournament file in a team event — '
                    'create an individual event first.'
                )
            )
        if tournament.deprecated_teams and not tournament.teams:
            # Legacy 013 records still aren't read; the 310-format teams
            # introduced in TRF26 are imported below.
            features.append(_('Teams'))
        unknown_symbols = self._unknown_point_system_symbols(tournament)
        if unknown_symbols:
            features.append(
                _('162 Point system results: {symbols}').format(
                    symbols=', '.join(unknown_symbols)
                )
            )
        sr_method = tournament.starting_rank_method
        if sr_method and sr_method not in self.STARTING_RANK_RATING_TYPES:
            features.append(
                _('172 Starting rank method {method}').format(method=sr_method)
            )
        encoded_type = tournament.encoded_type
        if encoded_type and not TrfEncodedType.get_supported_pairing_variation(
            encoded_type
        ):
            default = TrfEncodedType.get_not_supported_default_type(encoded_type)
            features.append(
                _('192 Encoded type {type} (default: {default})').format(
                    type=encoded_type,
                    default=default,
                )
            )
        tie_breaks = tournament.standings_tie_breaks
        standard_tie_breaks = ['PTS'] + tournament.tie_breaks
        if tie_breaks and tournament.tie_breaks and tie_breaks != standard_tie_breaks:
            features.append(_('202 and 212 tie-breaks (212 used)'))
            tie_breaks = standard_tie_breaks
        if not tie_breaks:
            tie_breaks = standard_tie_breaks
        if tie_breaks:
            __, unknown = self._read_tie_breaks(tie_breaks, event)
            if unknown:
                features.append(
                    _('{code} Unknown tie-breaks: {tie_breaks}').format(
                        code=212 if tournament.standings_tie_breaks else 202,
                        tie_breaks=', '.join(unknown),
                    )
                )

        if tournament.accelerated_rounds and not self._acceleration_is_importable(
            tournament
        ):
            features.append(_('250 Accelerated rounds'))
        if tournament.abnormal_points_assignments and not tournament.teams:
            features.append(_('299 Abnormal assignment points'))
        if any(
            federation != event.federation
            for federation in tournament.national_players_by_federation
        ):
            features.append(
                _(
                    'National rating support for other federations '
                    'than the event federation {federation}'
                ).format(federation=event.federation)
            )
        if tournament.xx_fields:
            features.append(_('XX fields'))
        if tournament.bb_fields:
            features.append(_('BB fields'))

        return features

    @staticmethod
    def _acceleration_is_importable(trf_tournament: TrfTournament) -> bool:
        """250 records are imported as the custom accelerated system. The
        published systems already carry their acceleration in the 192
        encoded type, so only a plain Swiss tournament is switched over."""
        from data.pairings.variations import StandardSwissVariation

        if trf_tournament.teams:
            return False
        variation = TrfEncodedType.get_supported_pairing_variation(
            trf_tournament.encoded_type or 'FIDE_DUTCH_2026'
        )
        if variation is None or variation.id != StandardSwissVariation.static_id():
            return False
        return True

    def _populate_acceleration(
        self,
        event: Event,
        stored_tournament: StoredTournament,
        trf_tournament: TrfTournament,
    ):
        """Import the 250 records as the rules of the custom accelerated
        system."""
        from data.pairings.settings import AccelerationRule
        from data.pairings.acceleration import (
            CustomAccelerationSetting,
            CustomAccelerationSwissVariation,
        )

        if not trf_tournament.accelerated_rounds:
            return
        if not self._acceleration_is_importable(trf_tournament):
            return
        rules = [
            AccelerationRule(
                vpoints=accelerated_round.game_points or 0.0,
                first_round=accelerated_round.first_round,
                last_round=accelerated_round.last_round,
                number_range=(accelerated_round.first_id, accelerated_round.last_id),
            )
            for accelerated_round in trf_tournament.accelerated_rounds
        ]
        stored_tournament.pairing = CustomAccelerationSwissVariation.static_id()
        stored_tournament.pairing_settings = stored_tournament.pairing_settings | {
            CustomAccelerationSetting.static_id(): (
                CustomAccelerationSetting.to_stored_value(rules)
            )
        }

    @staticmethod
    def _check_team_event_compatibility(
        event: Event, trf_tournament: TrfTournament
    ) -> None:
        """Refuse a TRF file whose team-ness doesn't match the event
        type. ``get_not_importable_features`` already surfaces this
        mismatch in the import dialog; this is the back-stop for any
        code path that skips the dialog."""
        if trf_tournament.teams and not event.is_team_event:
            raise ImporterError(
                _('Team tournament file cannot be imported into an individual event.')
            )
        if event.is_team_event and not trf_tournament.teams:
            raise ImporterError(
                _('Individual tournament file cannot be imported into a team event.')
            )

    @staticmethod
    def _unknown_point_system_symbols(trf_tournament: TrfTournament) -> list[str]:
        """162 result symbols with no equivalent here — 'X' (unknown
        result, e.g. an adjourned game) is the one the spec defines."""
        unknown: list[str] = []
        for symbol in trf_tournament.individuals_point_system:
            try:
                TrfPointSystemResult.get_core_object(symbol)
            except KeyError:
                unknown.append(symbol)
        return sorted(unknown)

    @staticmethod
    def _populate_game_points(
        stored_tournament: StoredTournament,
        trf_tournament: TrfTournament,
    ) -> None:
        """Fill the game-point values from the TRF26 162 record. These
        apply to individual and team tournaments alike — in team mode
        they are the per-board scoresheet that sits alongside the 362
        match points. Read before the team fields, so that an explicit
        320 team PAB can override the ``P`` value given here."""
        game_points: dict[int, float] = {}
        for symbol, value in trf_tournament.individuals_point_system.items():
            try:
                outcome = TrfPointSystemResult.get_core_object(symbol)
            except KeyError:
                continue
            game_points[outcome.value] = float(value)
        if game_points:
            stored_tournament.game_points = game_points

    @staticmethod
    def _populate_team_fields(
        stored_tournament: StoredTournament,
        trf_tournament: TrfTournament,
    ) -> None:
        """Fill the team-mode fields on ``stored_tournament`` from
        TRF26 records (192 ``encoded_type``, 310 rosters, 352
        ``board_color_sequence``, 362 ``teams_point_system``).
        No-op when the file isn't a team tournament."""
        if not trf_tournament.teams:
            return
        score_config = TrfEncodedType.get_team_score_config(trf_tournament.encoded_type)
        if score_config:
            # Score + colour config only ride on the team-Swiss codes
            # (FIDE_TEAM_…MP/GP). Round-robin/two-game codes carry no
            # score config, so leave the tournament's own settings alone.
            primary, secondary = score_config
            stored_tournament.primary_score = primary.value
            # No secondary in the code means it isn't used for colours.
            stored_tournament.secondary_score_for_colours = secondary is not None
            colour_type = TrfEncodedType.get_team_colour_type(
                trf_tournament.encoded_type
            )
            if colour_type:
                stored_tournament.team_colour_type = colour_type.value
        if trf_tournament.board_color_sequence:
            stored_tournament.color_pattern = trf_tournament.board_color_sequence
        match_points_by_symbol = trf_tournament.teams_point_system
        if match_points_by_symbol:
            stored_tournament.match_points = {
                Result.WIN.value: float(match_points_by_symbol.get('TW', 2.0)),
                Result.DRAW.value: float(match_points_by_symbol.get('TD', 1.0)),
                Result.LOSS.value: float(match_points_by_symbol.get('TL', 0.0)),
            }
        team_pabs = trf_tournament.team_pabs
        if team_pabs is not None:
            if team_pabs.match_points is not None:
                stored_tournament.match_points = stored_tournament.match_points or {}
                stored_tournament.match_points[Result.PAIRING_ALLOCATED_BYE.value] = (
                    float(team_pabs.match_points)
                )
            if team_pabs.game_points is not None:
                stored_tournament.game_points = stored_tournament.game_points or {}
                stored_tournament.game_points[Result.PAIRING_ALLOCATED_BYE.value] = (
                    float(team_pabs.game_points)
                )
        roster_size = max(
            (len(team.player_ids) for team in trf_tournament.teams), default=0
        )
        pattern_size = len(stored_tournament.color_pattern or '')
        if pattern_size:
            stored_tournament.team_player_count = pattern_size
        elif roster_size:
            stored_tournament.team_player_count = roster_size

    @staticmethod
    def _read_trf_oodo_records(
        trf_tournament: TrfTournament,
    ) -> dict[tuple[int, int], list[int | None]]:
        """Index the 300 records by ``(round, team TPN)`` so the
        reconstruction step can look up the per-round lineup directly
        without re-walking the record list."""
        result: dict[tuple[int, int], list[int | None]] = {}
        for entry in trf_tournament.oodo_team_pairings:
            result[(entry.round, entry.team_id)] = list(entry.boards)
        return result

    @staticmethod
    def _read_trf_manual_team_byes(
        trf_tournament: TrfTournament,
    ) -> dict[tuple[int, int], str]:
        """TRF26 240 records (team-mode interpretation): per
        ``(round, team TPN)`` mapping to ``HPB`` / ``FPB`` / ``ZPB``."""
        bye_type_by_letter = {
            'F': TeamByeType.FPB,
            'H': TeamByeType.HPB,
            'Z': TeamByeType.ZPB,
        }
        result: dict[tuple[int, int], str] = {}
        for trf_round_bye in trf_tournament.round_byes:
            mapped = bye_type_by_letter.get((trf_round_bye.type or '').upper())
            if mapped is None:
                continue
            for tpn in trf_round_bye.pairing_numbers:
                result[(trf_round_bye.round, tpn)] = mapped
        return result

    @staticmethod
    def _read_trf_oodo_match_orientation(
        trf_tournament: TrfTournament,
    ) -> dict[tuple[int, frozenset[int]], tuple[int, int]]:
        """For each round and team-pair, the ``(team_a_TPN, team_b_TPN)``
        the source tournament used. The 300 records emit team_a's view
        before team_b's, so the first one we see locks in the
        orientation — preserving which team appears on the left of the
        round display and which colour pattern slot each team takes.

        Falls back to 330 (team-forfeited-match) records when the 300
        record set doesn't include a pair — typically a match fully
        forfeited by one team where neither side fielded a player."""
        result: dict[tuple[int, frozenset[int]], tuple[int, int]] = {}
        for entry in trf_tournament.oodo_team_pairings:
            key = (entry.round, frozenset({entry.team_id, entry.opponent_team_id}))
            if key in result:
                continue
            result[key] = (entry.team_id, entry.opponent_team_id)
        for forfeit in trf_tournament.team_forfeited_matches:
            key = (
                forfeit.round,
                frozenset({forfeit.white_team_id, forfeit.black_team_id}),
            )
            if key in result:
                continue
            # White team listed first as ``team_a`` — colour pattern
            # ordering matches the export side.
            result[key] = (forfeit.white_team_id, forfeit.black_team_id)
        return result

    @staticmethod
    def _read_trf_teams(
        trf_tournament: TrfTournament,
    ) -> list[tuple[StoredTeam, list[int]]]:
        """Build ``(StoredTeam, [trf player ids])`` pairs for each 310
        roster. ``team.id`` (the TPN) becomes ``pairing_number``."""
        result: list[tuple[StoredTeam, list[int]]] = []
        for trf_team in trf_tournament.teams:
            stored_team = StoredTeam(
                id=None,
                name=trf_team.name or trf_team.nickname or f'Team {trf_team.id}',
                pairing_number=trf_team.id or None,
                # A team listed in a 310 roster is taking part. Left
                # checked out it would be given a zero-point bye when
                # the next round is paired, and a file where every team
                # is absent has no pairing at all.
                check_in=True,
            )
            result.append((stored_team, list(trf_team.player_ids)))
        return result

    def _write_stored_tournament(
        self,
        stored_tournament: StoredTournament,
        stored_players: list[StoredPlayer],
        database: EventDatabase,
    ) -> int:
        """Run the base writer, then persist team rosters when the TRF
        carried 310 records. Capture each ``StoredPlayer.id`` (still
        the external TRF id at this point) so we can remap team
        membership after the players are inserted."""
        external_player_ids = [player.id for player in stored_players]
        tournament_id = super()._write_stored_tournament(
            stored_tournament, stored_players, database
        )
        internal_by_external = {
            external_id: player.id
            for external_id, player in zip(external_player_ids, stored_players)
            if external_id is not None and player.id is not None
        }
        if not self._pending_teams:
            # 299 in an individual file targets players, and carries the
            # delta in the game-points field — 8-11 is team-only.
            for (
                round_,
                pairing_number,
            ), (_mp, delta) in self._pending_point_adjustments.items():
                player_id = internal_by_external.get(pairing_number)
                if player_id is None or not delta:
                    continue
                database.set_stored_player_point_adjustment(
                    tournament_id, player_id, round_, delta, None
                )
            return tournament_id
        team_id_by_internal_player_id: dict[int, int] = {}
        team_index_by_internal_player_id: dict[int, int] = {}
        pairing_number_by_team_id: dict[int, int] = {}
        team_id_by_tpn: dict[int, int] = {}
        # Reuse an existing team with the same name instead of inserting a
        # duplicate — but only within the tournament being imported into.
        # A team belongs to one tournament, so reusing one from another
        # would attach the imported players to *that* tournament and leave
        # this one empty. New teams are registered as we go so a name
        # repeated within this file also reuses the first.
        stored_teams = database.load_stored_teams()
        existing_team_id_by_name: dict[str, int] = {
            team.name: team.id
            for team in stored_teams
            if team.id is not None and team.tournament_id == tournament_id
        }
        # Teams can be moved between tournaments, so their names are kept
        # unique across the whole event; a name already taken by another
        # tournament's team is suffixed, as tournament names are.
        used_team_names: set[str] = {team.name for team in stored_teams}
        for stored_team, trf_player_ids in self._pending_teams:
            reused_team_id = existing_team_id_by_name.get(stored_team.name)
            if reused_team_id is not None:
                team_id = reused_team_id
                stored_team.id = team_id
            else:
                stored_team.tournament_id = tournament_id
                stored_team.name = Utils.get_unused_item_name(
                    stored_team.name, used_team_names
                )
                used_team_names.add(stored_team.name)
                team_id = database.add_stored_team(stored_team)
                stored_team.id = team_id
                existing_team_id_by_name[stored_team.name] = team_id
            if stored_team.pairing_number is not None:
                pairing_number_by_team_id[team_id] = stored_team.pairing_number
                team_id_by_tpn[stored_team.pairing_number] = team_id
            for index, trf_player_id in enumerate(trf_player_ids):
                internal_player_id = internal_by_external.get(trf_player_id)
                if internal_player_id is None:
                    continue
                database.set_player_team(internal_player_id, team_id, index)
                team_id_by_internal_player_id[internal_player_id] = team_id
                team_index_by_internal_player_id[internal_player_id] = index
        # Resolve OOdO TRF-player ids → internal player ids; the
        # reconstruction step keys lineups by ``(round, team_db_id)``.
        oodo_by_round_team: dict[tuple[int, int], dict[int, int]] = {}
        for (round_, tpn), trf_player_ids_per_board in self._pending_oodo.items():
            resolved_team_id = team_id_by_tpn.get(tpn)
            if resolved_team_id is None:
                continue
            slot_to_player: dict[int, int] = {}
            for slot, maybe_trf_id in enumerate(trf_player_ids_per_board):
                if maybe_trf_id is None or maybe_trf_id == 0:
                    continue
                internal_player_id = internal_by_external.get(maybe_trf_id)
                if internal_player_id is None:
                    continue
                slot_to_player[internal_player_id] = slot
            if slot_to_player:
                oodo_by_round_team[(round_, resolved_team_id)] = slot_to_player
        # Players that appear in an OOdO lineup but never made it onto
        # a 310 roster (typically substitutes who played early rounds
        # and were then moved off the team) still need a team_id —
        # otherwise the team-block display hides them with the
        # ``if team_a_player.team_id`` guard. Walk OOdO in round order
        # so later rounds overwrite earlier ones, mirroring the rule
        # "most recent team membership wins".
        for (_round, oodo_team_id), slot_map in sorted(
            oodo_by_round_team.items(), key=lambda item: item[0][0]
        ):
            for internal_player_id, slot in slot_map.items():
                if internal_player_id in team_id_by_internal_player_id:
                    continue
                database.set_player_team(internal_player_id, oodo_team_id, slot)
                team_id_by_internal_player_id[internal_player_id] = oodo_team_id
                team_index_by_internal_player_id[internal_player_id] = slot

        # Translate the OOdO orientation map from TPN → team_db_id so
        # the reconstruction step doesn't need to know about TPNs.
        oodo_orientation: dict[tuple[int, frozenset[int]], tuple[int, int]] = {}
        for (
            round_,
            tpn_pair,
        ), (a_tpn, b_tpn) in self._pending_oodo_orientation.items():
            a_team = team_id_by_tpn.get(a_tpn)
            b_team = team_id_by_tpn.get(b_tpn)
            if a_team is None or b_team is None:
                continue
            oodo_orientation[(round_, frozenset({a_team, b_team}))] = (a_team, b_team)
        for (round_, tpn), (mp, gp) in self._pending_point_adjustments.items():
            resolved_team_id = team_id_by_tpn.get(tpn)
            if resolved_team_id is None:
                continue
            database.set_stored_team_point_adjustment(
                tournament_id, resolved_team_id, round_, mp, gp, None
            )
        pab_team_id_by_round: dict[int, int] = {}
        for round_, tpn in self._pending_pab_team_by_round.items():
            resolved = team_id_by_tpn.get(tpn)
            if resolved is not None:
                pab_team_id_by_round[round_] = resolved
        # Resolve the parsed 240 records (keyed by TPN) into the
        # team-id space the reconstruction step uses.
        manual_byes_by_round_team: dict[tuple[int, int], str] = {}
        for (round_, tpn), bye_type in self._pending_manual_team_byes.items():
            resolved_id: int | None = team_id_by_tpn.get(tpn)
            if resolved_id is not None:
                manual_byes_by_round_team[(round_, resolved_id)] = bye_type

        self._reconstruct_team_boards(
            stored_tournament,
            tournament_id,
            team_id_by_internal_player_id,
            team_index_by_internal_player_id,
            pairing_number_by_team_id,
            oodo_by_round_team,
            oodo_orientation,
            pab_team_id_by_round,
            manual_byes_by_round_team,
            database,
        )
        return tournament_id

    @staticmethod
    def _reconstruct_team_boards(
        stored_tournament: StoredTournament,
        tournament_id: int,
        team_id_by_player_id: dict[int, int],
        team_index_by_player_id: dict[int, int],
        pairing_number_by_team_id: dict[int, int],
        oodo_by_round_team: dict[tuple[int, int], dict[int, int]],
        oodo_orientation: dict[tuple[int, frozenset[int]], tuple[int, int]],
        pab_team_id_by_round: dict[int, int],
        manual_byes_by_round_team: dict[tuple[int, int], str],
        database: EventDatabase,
    ) -> None:
        """Re-create per-round ``StoredTeamBoard`` envelopes plus
        per-round lineups from 001 games, with 300 OOdO records as
        explicit lineup overrides.

        Reciprocal 001 opponent records identify ordinary matches even
        when both teams followed their 310 roster order and therefore
        correctly have no 300 record. A 300 record supplies the exact
        slots when a team played out of order or with an unoccupied
        board. Lone boards (PAB-style entries with no opponent) are
        attached to the team's real match when one exists."""

        color_pattern = stored_tournament.color_pattern or ''
        # ``(player_id, round)`` → its pairing, so a synthesised
        # hole-board can be linked back to the forfeit pairing.
        pairing_by_player_round: dict[tuple[int, int], StoredPairing] = {}
        for stp in stored_tournament.stored_tournament_players:
            for sp in stp.stored_pairings:
                pairing_by_player_round[(stp.player_id, sp.round_)] = sp

        # A future-round 240 bye or a boardless 320 PAB still needs a
        # team envelope, so reconstruction cannot be limited to rounds
        # that happen to contain individual board records.
        reconstruction_rounds = set(stored_tournament.stored_boards_by_round)
        reconstruction_rounds.update(round_ for round_, _ in oodo_by_round_team)
        reconstruction_rounds.update(round_ for round_, _ in oodo_orientation)
        reconstruction_rounds.update(pab_team_id_by_round)
        reconstruction_rounds.update(round_ for round_, _ in manual_byes_by_round_team)

        # Pre-index all stored_boards by player so we can look up the
        # board for a given (slot's player) cheaply.
        for round_ in sorted(reconstruction_rounds):
            stored_boards = stored_tournament.stored_boards_by_round.get(round_, [])
            boards_by_player_id: dict[int, StoredBoard] = {}
            for board in stored_boards:
                if board.white_player_id is not None:
                    boards_by_player_id.setdefault(board.white_player_id, board)
                if board.black_player_id is not None:
                    boards_by_player_id.setdefault(board.black_player_id, board)

            # Start with the explicit OOdO / forfeit orientations.
            # Then add ordinary default-order matches directly from
            # reciprocal 001 boards: TRF26 says 300 must be omitted when
            # the 310 order was followed.
            orientation_by_pair: dict[frozenset[int], tuple[int, int]] = {}
            for (
                orientation_round,
                pair,
            ), (team_a_id, team_b_id) in oodo_orientation.items():
                if orientation_round != round_:
                    continue
                orientation_by_pair.setdefault(pair, (team_a_id, team_b_id))

            boards_by_team_pair: dict[frozenset[int], list[StoredBoard]] = defaultdict(
                list
            )
            for board in stored_boards:
                if board.white_player_id is None or board.black_player_id is None:
                    continue
                white_team_id = team_id_by_player_id.get(board.white_player_id)
                black_team_id = team_id_by_player_id.get(board.black_player_id)
                if (
                    white_team_id is None
                    or black_team_id is None
                    or white_team_id == black_team_id
                ):
                    continue
                pair = frozenset({white_team_id, black_team_id})
                boards_by_team_pair[pair].append(board)

            # For teams without 300, the selected players appear in 310
            # order with any non-nominated roster members skipped. Their
            # compressed order is therefore the board-slot order.
            default_lineup_by_team_pair: dict[
                tuple[frozenset[int], int], dict[int, int]
            ] = {}
            for pair, pair_boards in boards_by_team_pair.items():
                for team_id in pair:
                    player_ids = {
                        player_id
                        for board in pair_boards
                        for player_id in (
                            board.white_player_id,
                            board.black_player_id,
                        )
                        if player_id is not None
                        and team_id_by_player_id.get(player_id) == team_id
                    }
                    ordered_player_ids = sorted(
                        player_ids,
                        key=lambda player_id: (
                            team_index_by_player_id.get(player_id, 10**9),
                            player_id,
                        ),
                    )
                    default_lineup_by_team_pair[(pair, team_id)] = {
                        player_id: slot
                        for slot, player_id in enumerate(ordered_player_ids)
                    }

                if pair in orientation_by_pair:
                    continue
                sample_board = min(
                    pair_boards,
                    key=lambda board: min(
                        default_lineup_by_team_pair[(pair, team_id)].get(
                            player_id, 10**9
                        )
                        for team_id in pair
                        for player_id in (
                            board.white_player_id,
                            board.black_player_id,
                        )
                        if player_id is not None
                        and team_id_by_player_id.get(player_id) == team_id
                    ),
                )
                assert sample_board.white_player_id is not None
                assert sample_board.black_player_id is not None
                white_team_id = team_id_by_player_id[sample_board.white_player_id]
                black_team_id = team_id_by_player_id[sample_board.black_player_id]
                white_slot = default_lineup_by_team_pair[(pair, white_team_id)].get(
                    sample_board.white_player_id, 0
                )
                if white_slot < len(color_pattern):
                    team_a_is_white = color_pattern[white_slot].upper() == 'W'
                else:
                    team_a_is_white = white_slot % 2 == 0
                orientation_by_pair[pair] = (
                    (white_team_id, black_team_id)
                    if team_a_is_white
                    else (black_team_id, white_team_id)
                )

            # Display order is fixed later by ``_reorder_tournament_boards``;
            # sorting here merely makes reconstruction deterministic.
            real_matches = sorted(
                orientation_by_pair.values(),
                key=lambda match: (
                    min(
                        pairing_number_by_team_id.get(match[0], match[0]),
                        pairing_number_by_team_id.get(match[1], match[1]),
                    ),
                    max(
                        pairing_number_by_team_id.get(match[0], match[0]),
                        pairing_number_by_team_id.get(match[1], match[1]),
                    ),
                ),
            )

            # Teams that participate in a real match this round don't
            # also get a lone (team, None) PAB envelope — their empty
            # slots are folded into the real match below.
            teams_in_real_match: set[int] = set()
            for team_a_id, team_b_id in real_matches:
                teams_in_real_match.add(team_a_id)
                teams_in_real_match.add(team_b_id)

            # Older Sharly exports could let a later manual-bye envelope
            # overwrite the real team PAB in record 320. The compatibility
            # recovery below uses individual ``0000 - U`` boards only when
            # 320 and 240 contradict each other for the same team. Outside
            # that legacy signature, 320 remains authoritative as required
            # by TRF26. A U record belonging to a team in a real match is a
            # hole-board instead and is handled by the real-match loop.
            pab_board_ids_by_team: dict[int, set[int]] = defaultdict(set)
            for board in stored_boards:
                assert board.id is not None
                player_id = board.white_player_id or board.black_player_id
                if player_id is None:
                    continue
                pairing = pairing_by_player_round.get((player_id, round_))
                if (
                    pairing is None
                    or pairing.result != Result.PAIRING_ALLOCATED_BYE.value
                ):
                    continue
                pab_team_id = team_id_by_player_id.get(player_id)
                if pab_team_id is not None and pab_team_id not in teams_in_real_match:
                    pab_board_ids_by_team[pab_team_id].add(board.id)

            # Lone (team, None) envelopes for this round:
            # * 320 record → engine PAB (single team per round).
            # * 240 records → manual byes (HPB / FPB / ZPB), one team
            #   per entry, distinct from PAB. Teams already in a real
            #   match (folded-in empty slots) are excluded — a real
            #   match takes precedence.
            #
            # ``bye_envelopes`` carries ``(team_id, bye_type_or_None)``.
            # ``None`` means PAB; otherwise it's the manual bye type.
            bye_envelopes: list[tuple[int, str | None]] = []
            pab_team_id = pab_team_id_by_round.get(round_)
            if pab_team_id is not None and pab_team_id not in teams_in_real_match:
                bye_envelopes.append((pab_team_id, None))
            for (mb_round, mb_team_id), mb_type in manual_byes_by_round_team.items():
                if mb_round != round_:
                    continue
                if mb_team_id in teams_in_real_match:
                    continue
                if mb_team_id == pab_team_id:
                    # Manual bye supersedes the 320 PAB entry if both
                    # accidentally name the same team.
                    bye_envelopes = [
                        (tid, bt) for tid, bt in bye_envelopes if tid != mb_team_id
                    ]
                bye_envelopes.append((mb_team_id, mb_type))
            legacy_320_conflict = (
                pab_team_id is not None
                and (
                    round_,
                    pab_team_id,
                )
                in manual_byes_by_round_team
            )
            if legacy_320_conflict:
                enveloped_team_ids = {team_id for team_id, _ in bye_envelopes}
                inferred_candidates = [
                    team_id
                    for team_id in pab_board_ids_by_team
                    if team_id not in enveloped_team_ids
                ]
                if inferred_candidates:
                    inferred_team_id = min(
                        inferred_candidates,
                        key=lambda team_id: (
                            -len(pab_board_ids_by_team[team_id]),
                            pairing_number_by_team_id.get(team_id, team_id),
                        ),
                    )
                    bye_envelopes.append((inferred_team_id, None))

            # TRF26 makes a team Z record in 240 optional: once a round
            # has actual matches or a 320 PAB, any otherwise unaccounted
            # team is a ZPB by exclusion. Do not apply this merely because
            # future-round 240 pre-marks exist; those rounds are not paired
            # yet and the other teams remain eligible.
            if real_matches or any(bye_type is None for _, bye_type in bye_envelopes):
                accounted_team_ids = teams_in_real_match | {
                    team_id for team_id, _ in bye_envelopes
                }
                for absent_team_id in sorted(
                    set(pairing_number_by_team_id) - accounted_team_ids,
                    key=lambda team_id: pairing_number_by_team_id[team_id],
                ):
                    bye_envelopes.append((absent_team_id, TeamByeType.ZPB))

            match_index = 0
            assigned_board_ids: set[int] = set()
            lineup_by_team: dict[int, dict[int, int]] = {}
            for team_a_id, team_b_id in real_matches:
                stb = StoredTeamBoard(
                    id=None,
                    tournament_id=tournament_id,
                    round_=round_,
                    team_a_id=team_a_id,
                    team_b_id=team_b_id,
                    index=match_index,
                )
                stb.id = database.add_stored_team_board(stb)
                match_index += 1
                pair = frozenset({team_a_id, team_b_id})
                slot_a = oodo_by_round_team.get(
                    (round_, team_a_id),
                    default_lineup_by_team_pair.get((pair, team_a_id), {}),
                )
                slot_b = oodo_by_round_team.get(
                    (round_, team_b_id),
                    default_lineup_by_team_pair.get((pair, team_b_id), {}),
                )
                lineup_by_team[team_a_id] = slot_a
                lineup_by_team[team_b_id] = slot_b
                for is_team_a, slot_map in ((True, slot_a), (False, slot_b)):
                    for player_id, slot in slot_map.items():
                        match_board = boards_by_player_id.get(player_id)
                        if match_board is not None:
                            if match_board.id in assigned_board_ids:
                                continue
                            assert match_board.id is not None
                            set_stored_fields(
                                match_board, index=slot, team_board_id=stb.id
                            )
                            database.update_stored_board(match_board)
                            assigned_board_ids.add(match_board.id)
                            continue
                        # Player was fielded against an empty opposing
                        # board (a hole): the ``0000`` game produced no
                        # board record. Synthesise one — colour from the
                        # pattern, opposing side empty — and point the
                        # player's (forfeit) pairing at it, so the match
                        # score counts the board.
                        if slot < len(color_pattern):
                            pattern_white = color_pattern[slot].upper() == 'W'
                        else:
                            pattern_white = slot % 2 == 0
                        player_is_white = (
                            pattern_white if is_team_a else not pattern_white
                        )
                        hole_board = StoredBoard(
                            id=None,
                            white_player_id=player_id if player_is_white else None,
                            black_player_id=None if player_is_white else player_id,
                            index=slot,
                            team_board_id=stb.id,
                        )
                        set_stored_fields(
                            hole_board, id=database.add_stored_board(hole_board)
                        )
                        pairing = pairing_by_player_round.get((player_id, round_))
                        if pairing is not None:
                            pairing.board_id = hole_board.id
                            database.update_stored_pairing(pairing)

            for team_id, bye_type in bye_envelopes:
                # PAB (``bye_type is None``) is displayed → gets the next
                # table number; hidden byes (HPB/FPB/ZPB) hold NULL.
                if bye_type is None:
                    bye_index: int | None = match_index
                    match_index += 1
                else:
                    bye_index = None
                stb = StoredTeamBoard(
                    id=None,
                    tournament_id=tournament_id,
                    round_=round_,
                    team_a_id=team_id,
                    team_b_id=None,
                    index=bye_index,
                    bye_type=bye_type,
                )
                stb.id = database.add_stored_team_board(stb)
                match_index += 1
                slot_map = oodo_by_round_team.get((round_, team_id), {})
                for player_id, slot in slot_map.items():
                    pab_board = boards_by_player_id.get(player_id)
                    if pab_board is None or pab_board.id in assigned_board_ids:
                        continue
                    assert pab_board.id is not None
                    set_stored_fields(pab_board, index=slot, team_board_id=stb.id)
                    database.update_stored_board(pab_board)
                    assigned_board_ids.add(pab_board.id)

            # Persist every reconstructed lineup. For OOdO teams this is
            # the explicit 300 order; for default-order teams it is the
            # selected subset of the 310 roster recovered from 001.
            for (oodo_round, team_id), slot_map in oodo_by_round_team.items():
                if oodo_round != round_:
                    continue
                lineup_by_team.setdefault(team_id, slot_map)
            # A lineup holds a row per board, with no player on the ones
            # the team left empty — so a team that fielded nobody has a
            # lineup of its own rather than one taken from the round
            # before.
            boards_per_match = stored_tournament.team_player_count or 0
            for team_id, slot_map in lineup_by_team.items():
                slots: list[int | None] = [None] * boards_per_match
                for player_id, slot in slot_map.items():
                    if 0 <= slot < boards_per_match:
                        slots[slot] = player_id
                lineup_entries = [
                    StoredTeamRoundLineupEntry(
                        team_id=team_id,
                        round_=round_,
                        player_id=player_id,
                        index=index,
                    )
                    for index, player_id in enumerate(slots)
                ]
                database.replace_team_round_lineup(team_id, round_, lineup_entries)

    @classmethod
    def _read_tie_breaks(
        cls, tie_break_acronyms: list[str], event: Event
    ) -> tuple[list[TieBreak], list[str]]:
        tie_breaks: list[TieBreak] = []
        unknown_acronyms: list[str] = []
        manager = TieBreakManager(event)
        for acronym in tie_break_acronyms:
            # PTS is not skipped: TRF26 makes it one of the criteria that
            # define the standings, and where it sits decides the ranking.
            is_fide = not acronym.startswith('OTHER_')
            tie_break = manager.tie_break_from_trf_acronym(acronym)
            if tie_break and is_fide == tie_break.is_fide:
                tie_breaks.append(tie_break)
            else:
                unknown_acronyms.append(acronym)
        return tie_breaks, unknown_acronyms

    @staticmethod
    def _validate_trf_player(trf_player: TrfPlayer):
        try:
            TrfPlayerGender.get_core_object(trf_player.gender)
        except KeyError:
            raise ImporterError(
                _('Unknown gender [{gender}].').format(gender=trf_player.gender)
            )
        try:
            TrfPlayerTitle.get_core_object(trf_player.title)
        except KeyError:
            raise ImporterError(
                _('Unknown title [{title}].').format(title=trf_player.title)
            )
        if (
            trf_player.federation
            and trf_player.federation.upper() not in SharlyChessConfig().federations
        ):
            raise ImporterError(
                _('Unknown federation [{federation}].').format(
                    federation=trf_player.federation.upper()
                )
            )
        if trf_player.birth_date:
            try:
                datetime.strptime(trf_player.birth_date, '%Y/%m/%d')
            except ValueError:
                if not re.match(r'^\d{4}/00/00$', trf_player.birth_date):
                    raise ImporterError(
                        _('Invalid date format [{date}] (expected: {format}).').format(
                            date=trf_player.birth_date, format=_('YYYY/MM/DD')
                        )
                    )

    @staticmethod
    def _validate_trf_game(trf_game: TrfGame):
        try:
            color = TrfColor.get_core_object(trf_game.color)
        except KeyError:
            raise ImporterError(
                _('Unknown color [{color}].').format(color=trf_game.color)
            )
        try:
            result = TrfResult.get_core_object(
                trf_game.result, has_opponent=bool(trf_game.opponent_id)
            )
        except KeyError:
            raise ImporterError(
                _('Unknown result [{result}].').format(result=trf_game.result)
            )

        if trf_game.opponent_id and result.is_bye:
            raise ImporterError(
                _("Result [{result}] can't be used with an opponent.").format(
                    result=trf_game.result
                )
            )
        if not trf_game.opponent_id and not (
            result.is_bye
            or result == Result.NO_RESULT
            or result
            in (
                Result.FORFEIT_WIN,
                Result.FORFEIT_LOSS,
                Result.DOUBLE_FORFEIT,
            )
        ):
            raise ImporterError(
                _("Result [{result}] can't be used without an opponent.").format(
                    result=trf_game.result
                )
            )
        if trf_game.opponent_id and not color:
            raise ImporterError(
                _("Color [{color}] can't be used with an opponent.").format(
                    color=trf_game.color
                )
            )
        if (
            not trf_game.opponent_id
            and color
            and result
            not in (
                Result.FORFEIT_WIN,
                Result.FORFEIT_LOSS,
                Result.DOUBLE_FORFEIT,
            )
        ):
            raise ImporterError(
                _("Color [{color}] can't be used without an opponent.").format(
                    color=trf_game.color
                )
            )

    @classmethod
    def _read_trf_tournament(
        cls,
        event: Event,
        trf_tournament: TrfTournament,
        stored_tournament: StoredTournament | None = None,
    ) -> StoredTournament:
        if not stored_tournament:
            stored_tournament = StoredTournament(
                id=None,
                name=trf_tournament.name,
                start_date=event.start_date,
                stop_date=event.stop_date,
            )
        stored_tournament.location = trf_tournament.city
        if trf_tournament.start_date:
            try:
                stored_tournament.start_date = datetime.strptime(
                    trf_tournament.start_date, TRF_DATE_FORMAT
                ).date()
            except ValueError:
                raise ImporterError(
                    _('Invalid date format [{date}] (expected: {format}).').format(
                        date=trf_tournament.start_date, format=_('YYYY/MM/DD')
                    )
                )
        if trf_tournament.end_date:
            try:
                stored_tournament.stop_date = datetime.strptime(
                    trf_tournament.end_date, TRF_DATE_FORMAT
                ).date()
            except ValueError:
                raise ImporterError(
                    _('Invalid date format [{date}] (expected: {format}).').format(
                        date=trf_tournament.end_date, format=_('YYYY/MM/DD')
                    )
                )
        last_date_count = 0
        last_date: date | None = None
        for round_, trf_date in enumerate(trf_tournament.round_dates, start=1):
            if not trf_date:
                continue
            try:
                round_datetime = datetime.strptime(trf_date, '%y/%m/%d')
                if round_datetime.date() == last_date:
                    last_date_count += 1
                else:
                    last_date = round_datetime.date()
                    last_date_count = 0
                round_datetime = round_datetime.replace(
                    hour=last_date_count, minute=0, second=0
                )
                stored_tournament.round_datetimes[round_] = round_datetime
            except ValueError:
                message = _(
                    'Invalid date format [{date}] (expected: {format}).'
                ).format(date=trf_date, format=_('YY/MM/DD'))
                raise ImporterError(
                    _('{string}: {value}').format(string='132', value=message)
                )
        stored_tournament.rounds = trf_tournament.num_rounds_estimation
        initial_color = trf_tournament.initial_color
        if initial_color:
            try:
                BoardColor(initial_color)
                stored_tournament.pairing_settings[ColorSeedSetting().id] = (
                    initial_color
                )
            except ValueError:
                message = _('Unknown color [{color}].').format(color=initial_color)
                raise ImporterError(
                    _('{string}: {value}').format(string='152', value=message)
                )
        rating_type = cls.STARTING_RANK_RATING_TYPES.get(
            trf_tournament.starting_rank_method
        )
        if rating_type is not None:
            stored_tournament.player_rating_type = rating_type
        encoded_type = trf_tournament.encoded_type
        # Refuse files whose tournament type can't be honoured exactly: an
        # unknown code (no matching pairing system) or a CUSTOM_* code (a
        # third-party engine whose pairings we can't reproduce). Importing
        # either would silently substitute a different pairing system.
        if encoded_type and (
            encoded_type.startswith('CUSTOM')
            or TrfEncodedType.get_supported_pairing_variation(encoded_type) is None
        ):
            raise ImporterError(
                _(
                    'This file uses a tournament type ({type}) that Sharly '
                    'Chess cannot import, because its pairings cannot be '
                    'reproduced exactly.'
                ).format(type=encoded_type)
            )
        stored_tournament.pairing = TrfEncodedType.get_pairing_variation(
            encoded_type
        ).id
        cls._populate_game_points(stored_tournament, trf_tournament)
        cls._populate_team_fields(stored_tournament, trf_tournament)
        trf_tie_breaks = (
            trf_tournament.standings_tie_breaks or ['PTS'] + trf_tournament.tie_breaks
        )
        tie_breaks = cls._read_tie_breaks(trf_tie_breaks, event)[0]
        stored_tournament.stored_tie_breaks = [
            tie_break.to_stored_value() for tie_break in tie_breaks
        ]
        time_control = trf_tournament.time_control
        if time_control:
            try:
                parse_time_control_trf25(time_control)
                stored_tournament.time_control_trf25 = time_control
            except ValueError:
                raise ImporterError(
                    _('Invalid time control format [{time_control}].').format(
                        time_control=time_control
                    )
                )
        return stored_tournament

    @staticmethod
    def _read_trf_player(
        trf_player: TrfPlayer,
        tournament_rating: TournamentRating,
        event: Event,
    ) -> StoredPlayer:
        national_player = trf_player.national_player_by_federation.get(event.federation)
        ratings = {tr.value: PlayerRating().stored_value for tr in TournamentRating}
        ratings[tournament_rating.value] = PlayerRating(
            fide=trf_player.rating or None,
            national=getattr(national_player, 'rating', 0) or None,
        ).stored_value
        date_of_birth: date | None = None
        year_of_birth: int | None = None
        if trf_player.birth_date:
            try:
                date_of_birth = datetime.strptime(
                    trf_player.birth_date, '%Y/%m/%d'
                ).date()
            except ValueError:
                if re.match(r'^\d{4}/00/00$', trf_player.birth_date):
                    year_of_birth = int(trf_player.birth_date.split('/')[0])

        trf_title = TrfPlayerTitle.get_core_object(trf_player.title)
        stored_player = StoredPlayer(
            id=trf_player.id,
            last_name=trf_player.name.split(',')[0].strip().upper(),
            ratings=ratings,
            first_name=(
                trf_player.name.split(',')[1].strip()
                if ',' in trf_player.name
                else None
            ),
            gender=TrfPlayerGender.get_core_object(trf_player.gender).value,
            title=trf_title.open_value,
            women_title=trf_title.women_value,
            fide_id=trf_player.fide_id,
            date_of_birth=date_of_birth,
            year_of_birth=year_of_birth,
            federation=trf_player.federation.upper() or 'FID',
            # Same reasoning as the teams: a player carried by a 001
            # record is entered, and would otherwise be left out of the
            # next round's pairing.
            check_in=True,
        )
        if national_player:
            plugin_manager.hook_for_event(
                event, 'augment_stored_player_from_trf_national_player'
            )(
                stored_player=stored_player,
                trf_national_player=national_player,
            )
        return stored_player

    @staticmethod
    def _read_trf_game(
        trf_game: TrfGame, player_id: int
    ) -> tuple[StoredPairing, StoredBoard | None]:
        stored_board: StoredBoard | None = None
        result = TrfResult.get_core_object(
            trf_game.result, has_opponent=bool(trf_game.opponent_id)
        )
        color = TrfColor.get_core_object(trf_game.color)
        stored_pairing = StoredPairing(
            tournament_id=0,
            player_id=player_id,
            round_=trf_game.round,
            result=result.value,
            board_id=None,
        )
        if trf_game.opponent_id:
            stored_board = StoredBoard(
                id=None,
                white_player_id=(
                    player_id if color == BoardColor.WHITE else trf_game.opponent_id
                ),
                black_player_id=(
                    trf_game.opponent_id if color == BoardColor.WHITE else player_id
                ),
                index=0,
            )
        elif result.is_board_bye:
            stored_board = StoredBoard(
                id=None,
                white_player_id=player_id,
                black_player_id=None,
                index=0,
            )
        elif (
            result
            in (
                Result.FORFEIT_WIN,
                Result.FORFEIT_LOSS,
                Result.DOUBLE_FORFEIT,
            )
            and color is not None
        ):
            # Hole-opponent forfeit in a team match: player has a
            # board on a known side, opposing side is a hole. The
            # team-block reconstruction later attaches this board to
            # its parent ``team_board``.
            stored_board = StoredBoard(
                id=None,
                white_player_id=player_id if color == BoardColor.WHITE else None,
                black_player_id=player_id if color == BoardColor.BLACK else None,
                index=0,
            )
        return stored_pairing, stored_board

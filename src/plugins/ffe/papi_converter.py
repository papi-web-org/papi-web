import glob
import json
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from common.exception import SharlyChessException, DictReaderException
from common.i18n import _
from common.logger import get_logger
from common.sharly_chess_config import SharlyChessConfig
from common.tool_installer import PapiConverterInstaller
from data.event import Event
from data.input_output.dict_reader import dict_to_dataclass
from data.pairings.engines import DoubleBergerPairingEngine
from data.pairings.scheveningen import ScheveningenPairingSystem
from data.pairings.variations import (
    BergerRoundRobinVariation,
    DoubleBergerRoundRobinVariation,
    PairingVariation,
)
from data.player import TournamentPlayer, PlayerRating
from data.player_categories import PlayerCategory
from data.tie_breaks.tie_breaks import ManualTieBreak, PointsTieBreak, TieBreak
from data.tournament import Tournament
from database.sqlite.event.event_store import (
    StoredTournament,
    StoredPlayer,
    StoredBoard,
    StoredTournamentPlayer,
    StoredPairing,
    StoredTieBreak,
    set_stored_fields,
)
from plugins.ffe import PLUGIN_NAME
from plugins.ffe.papi_mappers import (
    PapiPairingVariation,
    PapiPlayerCategory,
    PapiTournamentRating,
    PapiTieBreak,
    PapiThreePointsForAWin,
    PapiPlayerGender,
    PapiPlayerRatingType,
    PapiPlayerFFELicence,
    PapiRound,
    PapiColor,
    PapiPlayerTitle,
    PapiPairingSystem,
)
from plugins.ffe.utils import FFEUtils
from plugins.ffe.utils import FfePlayerPluginData, PlayerFFELicence, FFE_EPOCH
from plugins.manager import plugin_manager
from data.pairings.acceleration import (
    BakuSwissVariation,
    AccelerationSwissVariation,
    CustomAccelerationSwissVariation,
    InitialScoreSwissVariation,
)
from utils import Utils
from utils.enum import (
    TournamentRating,
    PlayerGender,
    PlayerTitle,
    PlayerRatingType,
    Result,
)

logger = get_logger()

PAPI_DATE_FORMAT = '%d/%m/%Y'


@dataclass
class PapiVariables:
    name: str
    type: str | None = None
    rounds: str | None = None
    pairing: str | None = None
    timeControl: str | None = None
    ratingClass: str | None = None
    ratingThreshold1: str | None = None
    ratingThreshold2: str | None = None
    tiebreak1: str | None = None
    tiebreak2: str | None = None
    tiebreak3: str | None = None
    pointSystem: str | None = None
    venue: str | None = None
    startDate: str = ''
    endDate: str = ''
    arbiter: str | None = None
    homologation: str | None = None


@dataclass
class PapiPlayer:
    lastName: str
    firstName: str | None = None
    birthDate: str | None = None
    category: str | None = None
    gender: str | None = None
    email: str | None = None
    phone: str | None = None
    comment: str | None = None
    owed: int | float | None = None
    paid: int | float | None = None
    fideTitle: str | None = None
    elo: int = 0
    fideElo: str | None = None
    rapidElo: int = 0
    fideRapidElo: str | None = None
    blitzElo: int = 0
    fideBlitzElo: str | None = None
    fideCode: str | None = None
    federation: str = 'FID'
    licenceType: str | None = None
    nrFFE: str | None = None
    refFFE: int | None = None
    league: str | None = None
    club: str | None = None
    fixedBoard: int | None = None
    checkedIn: bool = False

    # Unused
    nr: int | None = None
    address: str | None = None
    postalCode: str | None = None

    rounds: dict[int, PapiRound] = field(default_factory=dict[int, PapiRound])


@dataclass
class PapiData:
    variables: PapiVariables
    players: list[PapiPlayer]


@dataclass
class PapiRating:
    value_field: str
    value: int
    type_field: str
    type: str | None
    tournament_rating: TournamentRating


class PapiConverter:
    """Wrapper on the Papi converter
    (see https://github.com/Sharly-Chess/papi-converter)"""

    # Used to input unique FFE IDs, preventing breaking the UNIQUE clause on this column
    MOCK_FFE_ID_DELTA = int((datetime.now() - FFE_EPOCH).total_seconds())

    @property
    def executable_path(self) -> Path:
        return PapiConverterInstaller().executable_path

    def convert_player_database(self, source_file: Path, target_file: Path) -> bool:
        """Converts the .mdb player database to an SQLLite database."""
        # Clean up any existing temporary H2 database files to avoid conflicts
        # H2 creates files with patterns like: filename.mv.db, filename.trace.db

        # Clean up H2 files with various patterns
        cleanup_patterns = [
            str(target_file.parent / f'{target_file.stem}*.mv.db'),
            str(target_file.parent / f'{target_file.stem}*.trace.db'),
            str(target_file.parent / f'{target_file.name}*.mv.db'),
            str(target_file.parent / f'{target_file.name}*.trace.db'),
            str(target_file.with_suffix('.mv.db')),
            str(target_file.with_suffix('.trace.db')),
        ]

        for pattern in cleanup_patterns:
            for file_path in glob.glob(pattern):
                Path(file_path).unlink(missing_ok=True)

        # Also ensure the target file itself is clean
        target_file.unlink(missing_ok=True)

        # Create a temporary SQL dump file
        sql_dump_file = target_file.with_suffix('.sql')

        try:
            # First, create the SQL dump
            Utils.run_process(
                [
                    self.executable_path,
                    '--playerdb',
                    str(source_file.resolve()),
                    str(sql_dump_file.resolve()),
                ],
                capture_output=True,
                encoding='utf-8',
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise SharlyChessException(
                f'PapiConverter execution failed with status {e.returncode}.\n'
                f'stdout: {e.stdout}\nstderr: {e.stderr}'
            )

        if not sql_dump_file.exists():
            raise SharlyChessException(
                'Player database conversion error: PapiConverter ran successfully but the SQL dump file was not created.'
            )

        try:
            # Create the SQLite database from the SQL dump using Python's sqlite3 module
            with open(sql_dump_file, 'r', encoding='utf-8') as dump_file:
                sql_content = dump_file.read()

            # Create the SQLite database and execute the SQL dump
            conn = sqlite3.connect(str(target_file))
            try:
                conn.executescript(sql_content)
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            raise SharlyChessException(f'SQLite database creation failed: {e}')
        finally:
            # Clean up the temporary SQL dump file
            sql_dump_file.unlink(missing_ok=True)
            if not target_file.exists():
                raise SharlyChessException(
                    'Player database conversion error: SQLite database was not created.'
                )
            return True

    def read_papi_file(self, source_file: Path) -> PapiData:
        """Read the papi file *source_file* into stored objects.
        Raises a SharlyChessException if the conversion fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_dir: Path = Path(tmpdir)
            target_file = tmp_dir / 'papi-converter-output.json'
            result = Utils.run_process(
                [
                    self.executable_path,
                    source_file,
                    target_file,
                ],
                capture_output=True,
                encoding='utf-8',
            )
            if not target_file.exists():
                raise SharlyChessException(
                    f'Papi file conversion to JSON failed.'
                    f'PapiConverter failed with status {result.returncode}.\n'
                    f'stdout: {result.stdout}\nstderr: {result.stderr}'
                )

            with open(target_file, 'r', encoding='utf-8') as file:
                papi_data_dict = json.load(file)
            return dict_to_dataclass(PapiData, papi_data_dict)

    def read_papi_data(
        self,
        event: Event,
        papi_data: PapiData,
        stored_tournament: StoredTournament | None = None,
    ) -> tuple[StoredTournament, list[StoredPlayer]]:
        """Read a PapiData object into stored objects.
        If a StoredTournament object is provided, add the values to this one,
        otherwise creates a new one."""

        stored_tournament = self._read_papi_variables(
            papi_data.variables, stored_tournament
        )
        is_round_robin = (
            stored_tournament.pairing == BergerRoundRobinVariation.static_id()
        )

        if is_round_robin and stored_tournament.rounds == (
            DoubleBergerPairingEngine().get_round_count(len(papi_data.players))
        ):
            stored_tournament.pairing = DoubleBergerRoundRobinVariation.static_id()

        has_manual_tiebreak = any(
            stored_tie_break.type == ManualTieBreak.static_id()
            for stored_tie_break in stored_tournament.stored_tie_breaks
        )

        next_board_id = 1
        board_id_by_player_id_by_round: dict[int, dict[int, int]] = {
            round_: {} for round_ in range(1, stored_tournament.rounds + 1)
        }
        stored_boards_by_round: dict[int, list[StoredBoard]] = {
            round_: [] for round_ in range(1, stored_tournament.rounds + 1)
        }
        stored_players: list[StoredPlayer] = []
        max_opponent_id = len(papi_data.players) - 1
        for player_id, papi_player in enumerate(papi_data.players):
            stored_player = self._read_papi_player(event, player_id, papi_player)
            stored_player.id = player_id
            stored_tournament_player = StoredTournamentPlayer(player_id=player_id)
            round_keys = papi_player.rounds.keys()

            if has_manual_tiebreak:
                # The relative order of the players is stored in the fixed table field with values above 1000!
                if stored_player.fixed and stored_player.fixed >= 1000:
                    stored_tournament_player.manual_tiebreak = (
                        stored_player.fixed - 1000
                    )
                    stored_player.fixed = None

            if is_round_robin:
                start_round = 1
                end_round = stored_tournament.rounds
            else:
                start_round = min(round_keys) if round_keys else 1
                end_round = max(round_keys) if round_keys else 0
            for round_nb in range(start_round, end_round + 1):
                papi_round = papi_player.rounds.get(round_nb, None)
                if round_nb > stored_tournament.rounds or (
                    papi_round is None and not is_round_robin
                ):
                    continue
                if papi_round is None:
                    stored_pairing = StoredPairing(
                        tournament_id=0,
                        player_id=player_id,
                        round_=round_nb,
                        result=Result.REST_GAME,
                        board_id=None,
                    )
                    stored_board: StoredBoard | None = StoredBoard(
                        id=None,
                        white_player_id=player_id,
                        black_player_id=None,
                        index=0,
                        last_result_update=None,
                    )
                else:
                    stored_pairing, stored_board = self._read_papi_round(
                        player_id, round_nb, papi_round, max_opponent_id, is_round_robin
                    )
                if stored_board:
                    if player_id in board_id_by_player_id_by_round[round_nb]:
                        board_id = board_id_by_player_id_by_round[round_nb][player_id]
                    else:
                        board_id = next_board_id
                        next_board_id += 1
                        set_stored_fields(stored_board, id=board_id)
                        stored_boards_by_round[round_nb].append(stored_board)
                        if papi_round and papi_round.opponent is not None:
                            board_id_by_player_id_by_round[round_nb][
                                papi_round.opponent
                            ] = board_id
                    stored_pairing.board_id = board_id
                stored_tournament_player.stored_pairings.append(stored_pairing)
            stored_players.append(stored_player)
            stored_tournament.stored_tournament_players.append(stored_tournament_player)
        stored_tournament.stored_boards_by_round = stored_boards_by_round
        return stored_tournament, stored_players

    @staticmethod
    def _read_papi_variables(
        variables: PapiVariables,
        stored_tournament: StoredTournament | None = None,
    ) -> StoredTournament:
        def raise_exception(field_: str, message: str):
            raise DictReaderException(['variables', field_], message)

        def raise_unknown_value(field_: str, value: Any):
            raise_exception(field_, _('Unknown value [{value}]').format(value=value))

        if not stored_tournament:
            if not variables.name:
                raise_exception('name', _('A non-empty string is expected'))
            stored_tournament = StoredTournament(
                id=None,
                name=variables.name,
                start_date=datetime.strptime(
                    variables.startDate, PAPI_DATE_FORMAT
                ).date(),
                stop_date=datetime.strptime(variables.endDate, PAPI_DATE_FORMAT).date(),
            )
        stored_tournament.override_unrated_rapid_blitz = False
        rounds = 7
        if variables.rounds:
            if not variables.rounds.isdigit():
                raise_exception('rounds', _('A positive integer is expected.'))
            rounds = int(variables.rounds)
        stored_tournament.rounds = rounds
        pairing = SharlyChessConfig.default_pairing_variation_id
        if variables.pairing:
            try:
                pairing = PapiPairingVariation.get_core_object(variables.pairing).id
            except KeyError:
                raise_unknown_value('pairing', variables.pairing)
        stored_tournament.pairing = pairing
        rating = TournamentRating.STANDARD
        if variables.ratingClass:
            try:
                rating = PapiTournamentRating.get_core_object(variables.ratingClass)
            except KeyError:
                raise_unknown_value('ratingClass', variables.ratingClass)
        stored_tournament.rating = rating.value
        tie_breaks: list[StoredTieBreak] = []
        for index, papi_tie_break in enumerate(
            (
                variables.tiebreak1,
                variables.tiebreak2,
                variables.tiebreak3,
            )
        ):
            if not papi_tie_break:
                continue
            try:
                tie_break = PapiTieBreak.get_core_object(papi_tie_break)
                tie_breaks.append(tie_break.to_stored_value())
            except KeyError:
                raise_unknown_value(f'tiebreak{index + 1}', papi_tie_break)
        stored_tournament.stored_tie_breaks = tie_breaks
        three_points_for_a_win = False
        if variables.pointSystem:
            try:
                three_points_for_a_win = PapiThreePointsForAWin.get_core_object(
                    variables.pointSystem
                )
            except KeyError:
                raise_unknown_value('pointSystem', variables.pointSystem)
        if three_points_for_a_win:
            game_points = {
                Result.WIN.value: 3.0,
                Result.DRAW.value: 1.0,
                Result.LOSS.value: 0.0,
            }
        else:
            game_points = {
                Result.WIN.value: 1.0,
                Result.DRAW.value: 0.5,
                Result.LOSS.value: 0.0,
            }
        game_points[Result.ZERO_POINT_BYE.value] = 0.0
        game_points[Result.PAIRING_ALLOCATED_BYE.value] = game_points[Result.WIN.value]
        stored_tournament.game_points = game_points
        stored_tournament.location = variables.venue
        ffe_id = None
        if variables.homologation:
            homologation = variables.homologation.strip()
            if not homologation.isdigit():
                # Papi form allows for a non-integer value,
                # so the value is ignored instead of raising
                logger.warning(
                    'Homologation number [%s] is not an integer, its value is ignored.',
                    homologation,
                )
            else:
                ffe_id = int(homologation)
        plugin_data = stored_tournament.plugin_data or {}
        if PLUGIN_NAME not in plugin_data:
            plugin_data[PLUGIN_NAME] = {}
        plugin_data[PLUGIN_NAME] |= {'ffe_id': ffe_id}
        stored_tournament.plugin_data = plugin_data
        return stored_tournament

    @staticmethod
    def _read_papi_player(
        event: Event, player_id: int, papi_player: PapiPlayer
    ) -> StoredPlayer:
        def raise_exception(field_: str, message: str):
            raise DictReaderException(['players', str(player_id), field_], message)

        def raise_unknown_value(field_: str, value: Any):
            raise_exception(field_, _('Unknown value [{value}]').format(value=value))

        if not papi_player.lastName:
            raise_exception('name', _('A non-empty string is expected'))

        date_of_birth: date | None = None
        year_of_birth: int | None = None
        if papi_player.birthDate:
            try:
                date_of_birth = datetime.strptime(
                    papi_player.birthDate, PAPI_DATE_FORMAT
                ).date()
            except ValueError:
                raise_exception(
                    'birthDate',
                    _('Invalid date format [{date}] (expected: {format}).').format(
                        date=papi_player.birthDate, format=_('DD/MM/YYYY')
                    ),
                )
        elif papi_player.category:
            category = PapiPlayerCategory.get_core_object(papi_player.category)
            year_of_birth = category.representative_year(
                event, event.start_date, event.stop_date
            )

        gender = PlayerGender.NONE
        if papi_player.gender:
            try:
                gender = PapiPlayerGender.get_core_object(papi_player.gender)
            except KeyError:
                raise_unknown_value('gender', papi_player.gender)
        title = PlayerTitle.NONE
        if papi_player.fideTitle:
            try:
                title = PapiPlayerTitle.get_core_object(papi_player.fideTitle)
            except KeyError:
                raise_unknown_value('fideTitle', papi_player.fideTitle)

        ratings: dict[int, dict[str, int | None]] = {}
        papi_ratings = [
            PapiRating(
                'elo',
                papi_player.elo,
                'fideElo',
                papi_player.fideElo,
                TournamentRating.STANDARD,
            ),
            PapiRating(
                'rapidElo',
                papi_player.rapidElo,
                'fideRapidElo',
                papi_player.fideRapidElo,
                TournamentRating.RAPID,
            ),
            PapiRating(
                'blitzElo',
                papi_player.blitzElo,
                'fideBlitzElo',
                papi_player.fideRapidElo,
                TournamentRating.BLITZ,
            ),
        ]
        for papi_rating in papi_ratings:
            if papi_rating.value < 0:
                raise_exception(
                    papi_rating.value_field, _('A positive integer is expected.')
                )
            rating_type = PlayerRatingType.ESTIMATED
            if papi_rating.type:
                try:
                    rating_type = PapiPlayerRatingType.get_core_object(papi_rating.type)
                except KeyError:
                    raise_unknown_value(papi_rating.type_field, papi_rating.type)
            ratings[papi_rating.tournament_rating.value] = PlayerRating.from_type(
                papi_rating.value, rating_type
            ).stored_value

        fide_id: int | None = None
        if papi_player.fideCode:
            try:
                fide_id = int(papi_player.fideCode.replace("'", '').strip())
            except ValueError:
                logger.warning('Invalid FIDE ID [%s], ignored.', papi_player.fideCode)

        ffe_licence = PlayerFFELicence.NONE
        if papi_player.licenceType:
            try:
                ffe_licence = PapiPlayerFFELicence.get_core_object(
                    papi_player.licenceType, papi_player.nrFFE
                )
            except KeyError:
                raise_unknown_value('licenceType', papi_player.licenceType)
        return StoredPlayer(
            id=None,
            last_name=papi_player.lastName.upper(),
            first_name=papi_player.firstName.title() if papi_player.firstName else None,
            date_of_birth=date_of_birth,
            year_of_birth=year_of_birth,
            gender=gender.value,
            mail=papi_player.email,
            phone=papi_player.phone,
            comment=papi_player.comment,
            owed=float(papi_player.owed or 0),
            paid=float(papi_player.paid or 0),
            title=title.open_value,
            women_title=title.women_value,
            ratings=ratings,
            fide_id=fide_id,
            federation=papi_player.federation,
            club=papi_player.club,
            fixed=papi_player.fixedBoard,
            check_in=papi_player.checkedIn,
            plugin_data={
                PLUGIN_NAME: FfePlayerPluginData(
                    ffe_id=papi_player.refFFE,
                    ffe_licence=ffe_licence,
                    ffe_licence_number=papi_player.nrFFE,
                    league=papi_player.league,
                ).to_stored_value()
            },
        )

    @staticmethod
    def _read_papi_round(
        player_id: int,
        round_nb: int,
        papi_round: PapiRound,
        max_opponent_id: int,
        is_round_robin: bool,
    ) -> tuple[StoredPairing, StoredBoard | None]:
        def raise_exception(field_: str, message: str):
            raise DictReaderException(['players', str(player_id), field_], message)

        if papi_round.opponent is not None:
            if papi_round.opponent > max_opponent_id:
                raise_exception(
                    'opponent',
                    _('Unknown player ID [{player_id}]').format(
                        player_id=papi_round.opponent
                    ),
                )
        stored_board: StoredBoard | None = None
        result = papi_round.to_result(is_round_robin)
        stored_pairing = StoredPairing(
            tournament_id=0,
            player_id=player_id,
            round_=round_nb,
            result=result.value,
            board_id=None,
        )

        color = PapiColor.WHITE if result == Result.REST_GAME else papi_round.color
        if color in (PapiColor.WHITE, PapiColor.BLACK):
            if color == PapiColor.WHITE:
                white_id = player_id
                black_id = papi_round.opponent
            else:
                if papi_round is None:
                    raise_exception(
                        'color',
                        _('Black pairings are supposed to have an opponent'),
                    )
                assert papi_round.opponent is not None
                white_id = papi_round.opponent
                black_id = player_id
            stored_board = StoredBoard(
                id=None,
                white_player_id=white_id,
                black_player_id=black_id,
                index=0,
                last_result_update=None,
            )
        return stored_pairing, stored_board

    @classmethod
    def check_pairing_variation_warning(
        cls, pairing_variation: PairingVariation
    ) -> str | None:
        if pairing_variation == BakuSwissVariation():
            return _(
                'The Baku acceleration system is not recognized by the FFE, there may be differences in the display of pairings on the FFE website.'
            )
        if isinstance(
            pairing_variation,
            (CustomAccelerationSwissVariation, InitialScoreSwissVariation),
        ):
            return _(
                'The [{variation}] pairing system is not recognized by the FFE, '
                'which derives acceleration from the ratings: the pairings '
                'displayed on the FFE website may differ.'
            ).format(variation=pairing_variation.name)
        return None

    @classmethod
    def check_tiebreaks_warning(
        cls,
        tie_breaks: list[TieBreak],
        three_points_for_a_win: bool = False,
    ) -> str | None:
        if tie_breaks and isinstance(tie_breaks[0], PointsTieBreak):
            # Papi always ranks on the points first and has no code for them,
            # so a leading PTS takes no slot (see _tiebreaks_to_papi_tiebreaks).
            tie_breaks = tie_breaks[1:]
        if len(tie_breaks) <= 3 and all(
            PapiTieBreak.get_outer_value(tie_break, three_points_for_a_win)
            for tie_break in tie_breaks
        ):
            return None
        return '<br/>'.join(
            (
                _(
                    'Some of the tie-break values will not '
                    'appear in the results on the FFE website.'
                ),
                _(
                    'However, the order of the results of the last round '
                    'will remain the same as the ones in Sharly Chess.'
                ),
            )
        )

    @classmethod
    def scheveningen_export_warning(cls, tournament: Tournament) -> str | None:
        """The warning that a Scheveningen has no Papi form of its own and
        is exported / uploaded as an individual Swiss. Shared by the export
        modal and the tournament tab's pairing warning."""
        if isinstance(tournament.pairing_system, ScheveningenPairingSystem):
            return _(
                'This Scheveningen is unknown by the FFE website and will be exported as an individual Swiss tournament.'
            )
        return None

    @classmethod
    def check_pairing_warning(cls, tournament: Tournament) -> str | None:
        if warning := cls.scheveningen_export_warning(tournament):
            return warning
        if isinstance(tournament.pairing_variation, AccelerationSwissVariation):
            return _(
                "The player's points and the board numbers may differ on the FFE website because Sharly Chess uses pairing numbers for the acceleration groups (the FFE website uses rating thresholds)."
            )
        else:
            return None

    @classmethod
    def check_result(cls, result: Result, tournament: Tournament) -> str | None:
        if not PapiRound.is_convertible_to_papi(result, tournament):
            return _('The Papi format does not support result [{result}].').format(
                result=result
            )
        return None

    MAX_PAPI_ROUNDS = 24

    @classmethod
    def check_rounds(cls, rounds: int) -> str | None:
        if rounds > cls.MAX_PAPI_ROUNDS:
            return _(
                'The PAPI format does not support {rounds} rounds (maximum: {max}).'
            ).format(rounds=rounds, max=cls.MAX_PAPI_ROUNDS)
        return None

    # WIN / DRAW / LOSS presets the legacy Papi format can round-trip.
    # Standard FIDE (1 / 0.5 / 0) and "3 points for a win" (3 / 1 / 0)
    # are the only schemes the format was ever specified for; anything
    # else is silently lost on import.
    _SUPPORTED_GAME_POINT_PRESETS: tuple[tuple[float, float, float], ...] = (
        (1.0, 0.5, 0.0),
        (3.0, 1.0, 0.0),
    )

    @classmethod
    def papi_export_unavailable_message(cls, tournament: Tournament) -> str | None:
        """Return a message if the export to Papi is unavailable, None otherwise."""
        # A Scheveningen is the one team system that can be flattened to an
        # individual Swiss (every player has one opponent per round), so it
        # is exported that way; the other team systems have no Papi form.
        if tournament.event.is_team_event and not isinstance(
            tournament.pairing_system, ScheveningenPairingSystem
        ):
            return _('Papi export is not available for team events.')

        # Papi ranks on the points and then on up to three tie-breaks;
        # there is no way to express a criterion that outranks the score.
        if not tournament.leads_on_points:
            return _(
                'Papi export requires the standings to be ranked on the points '
                'first. This tournament ranks on [{tie_break}] before them, '
                'which the Papi format cannot represent.'
            ).format(tie_break=tournament.leading_tie_break.full_name)

        win = tournament.win_points
        draw = tournament.draw_points
        loss = tournament.loss_points
        if (win, draw, loss) not in cls._SUPPORTED_GAME_POINT_PRESETS:
            return _(
                'Papi export only supports the standard (1 / 0.5 / 0) or '
                '"3 points for a win" (3 / 1 / 0) game-point scales. '
                'Current values: {win} / {draw} / {loss}.'
            ).format(
                win=Utils.points_str(win),
                draw=Utils.points_str(draw),
                loss=Utils.points_str(loss),
            )

        if rounds_blocker := cls.check_rounds(tournament.rounds):
            return rounds_blocker

        for round_ in range(1, tournament.rounds + 1):
            for player in tournament.tournament_players:
                if msg := cls.check_result(player.pairings[round_].result, tournament):
                    return msg

        # Papi has nowhere to record a bonus / penalty, so exporting a
        # tournament that uses them would silently drop points and change
        # the standings.
        if any(
            adjustment.delta
            for adjustment in (
                tournament.stored_tournament.stored_player_point_adjustments
            )
        ):
            return _(
                'Papi export does not support bonus / penalty points, which '
                'this tournament uses.'
            )

        return None

    @classmethod
    def papi_export_warning(cls, tournament: Tournament) -> str | None:
        warnings: list[str] = []
        if warning := cls.scheveningen_export_warning(tournament):
            warnings.append(warning)
        if warning := cls.check_tiebreaks_warning(
            tournament.tie_breaks,
            three_points_for_a_win=tournament.win_points == 3.0,
        ):
            warnings.append(warning)
        if warning := cls.check_pairing_variation_warning(tournament.pairing_variation):
            warnings.append(warning)
        return '<br/>'.join(warnings) or None

    def write_papi_file(
        self,
        tournament: Tournament,
        target_file: Path,
        anonymize_player_data: bool = False,
        is_ffe_upload: bool = False,
    ):
        """Write the tournament data to a papi file.
        Converts a Tournament to JSON format that can be sent to papi-converter.
        Raises a SharlyChessException if the conversion fails."""
        papi_data = self.tournament_to_papi_data(
            tournament, anonymize_player_data, is_ffe_upload
        )
        papi_data_dict = {
            'variables': {
                key: value or '' for key, value in papi_data.variables.__dict__.items()
            },
            'players': [
                self._papi_player_to_dict(player) for player in papi_data.players
            ],
        }

        # Write JSON to temporary file first
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path: Path = Path(tmpdir)
            temp_json_file = tmp_path / 'papi-converter-input.json'
            with open(temp_json_file, 'w', encoding='utf-8') as file:
                json.dump(papi_data_dict, file, ensure_ascii=False, indent=2)

            # Use papi-converter to convert JSON to PAPI format
            result = Utils.run_process(
                [
                    self.executable_path,
                    temp_json_file,
                    target_file,
                ],
                capture_output=True,
                encoding='utf-8',
            )

            if result.returncode != 0 or not target_file.exists():
                raise SharlyChessException(
                    'JSON to Papi file conversion failed.'
                    f'PapiConverter failed with status {result.returncode}.\n'
                    f'stdout: {result.stdout}\nstderr: {result.stderr}'
                )
            else:
                logger.debug(
                    'JSON to Papi conversion successful for tournament [%s]. '
                    'PapiConverter output:\n%s',
                    tournament.name,
                    result.stdout,
                )

    @classmethod
    def _get_rating_thresholds_from_pairing_settings(
        cls,
        tournament: Tournament,
    ) -> tuple[int, int]:
        rating_threshold_1: int = 0
        rating_threshold_2: int = 0
        variation: PairingVariation = tournament.pairing_variation
        group_max_numbers: list[int] = variation.get_acceleration_group_max_numbers(
            tournament
        )
        if len(group_max_numbers) > 0 and group_max_numbers[0] > 0:
            rating_threshold_1 = tournament.tournament_players_by_pairing_number[
                group_max_numbers[0]
            ].rating
            if len(group_max_numbers) > 1 and group_max_numbers[0] > 0:
                rating_threshold_2 = tournament.tournament_players_by_pairing_number[
                    group_max_numbers[1]
                ].rating
        return rating_threshold_1, rating_threshold_2

    def tournament_to_papi_data(
        self,
        tournament: Tournament,
        anonymize_player_data: bool = False,
        is_ffe_upload: bool = False,
    ) -> PapiData:
        """Convert a Tournament object to PapiData."""
        papi_tiebreaks, manual_tiebreak_by_player_id = (
            self._tiebreaks_to_papi_tiebreaks(tournament)
        )
        rating_thresholds: tuple[int, int] = (
            self._get_rating_thresholds_from_pairing_settings(tournament)
        )
        # Convert tournament variables
        variables = PapiVariables(
            name=tournament.full_name,
            type=PapiPairingSystem.get_outer_value(tournament.pairing_system),
            rounds=str(tournament.rounds),
            pairing=PapiPairingVariation.get_outer_value(tournament.pairing_variation),
            ratingClass=PapiTournamentRating.get_outer_value(tournament.rating),
            venue=tournament.location,
            startDate=tournament.start_date.strftime(PAPI_DATE_FORMAT),
            endDate=tournament.stop_date.strftime(PAPI_DATE_FORMAT),
            tiebreak1=papi_tiebreaks[0],
            tiebreak2=papi_tiebreaks[1],
            tiebreak3=papi_tiebreaks[2],
            pointSystem=PapiThreePointsForAWin.get_outer_value(
                tournament.win_points == 3.0
            ),
            arbiter='',
            timeControl=tournament.time_control_trf25,
            ratingThreshold1=str(rating_thresholds[0]),
            ratingThreshold2=str(rating_thresholds[1]),
            homologation=str(
                FFEUtils.get_tournament_plugin_data(tournament).ffe_id or ''
            ),
        )

        # Create mapping from internal player ID to index in PapiPlayer list
        player_id_to_index = {
            tournament_player.id: index
            for index, tournament_player in enumerate(tournament.tournament_players)
        }

        # Convert players
        papi_players: list[PapiPlayer] = []
        for tournament_player in tournament.tournament_players:
            papi_player = self._player_to_papi_player(
                tournament_player,
                player_id_to_index,
                tournament.pab_equivalent_result,
                manual_tiebreak_by_player_id.get(tournament_player.id, None),
                anonymize_player_data,
            )
            plugin_manager.hook_for_event(tournament.event, 'update_papi_player')(
                papi_player=papi_player,
                tournament_player=tournament_player,
                is_ffe_upload=is_ffe_upload,
            )
            papi_players.append(papi_player)

        return PapiData(variables=variables, players=papi_players)

    @staticmethod
    def _tiebreaks_to_papi_tiebreaks(
        tournament: Tournament,
    ) -> tuple[list[str | None], dict[int, int]]:
        if tournament.pairing_system.eliminates_participants:
            # A knock-out ranks by the round reached, not by any tie-break, so
            # export none — its configured tie-breaks are Art. 12 advancement
            # criteria (deciding a level match), not standings.
            return [None, None, None], {}
        papi_tiebreaks: list[str | None] = []
        manual_tiebreak_by_player_id: dict[int, int] = {}
        manual_index: int | None = None
        use_manual: bool = False
        for index, tiebreak in enumerate(tournament.tie_breaks):
            if isinstance(tiebreak, PointsTieBreak):
                # Papi always ranks on the points first and has no code
                # for them, so they take no slot. Anywhere but first and
                # the ranking is one Papi cannot express — fall back to
                # the manual tie-break, which carries it exactly.
                if index > 0:
                    use_manual = True
                    break
                continue
            if tiebreak == ManualTieBreak():
                manual_index = index
            papi_tiebreak = PapiTieBreak.get_outer_value(
                tiebreak, three_points_for_a_win=tournament.win_points == 3.0
            )
            if len(papi_tiebreaks) > 2 or not papi_tiebreak:
                use_manual = True
                break
            papi_tiebreaks.append(papi_tiebreak)
        if not tournament.started:
            # Do not set a manual tie-break if the tournament is not started
            pass
        elif use_manual:
            # Replace the final Papi tie-break by a manual tie-break representing the SC ranking
            # This way, at least the last round is correct
            if manual_index is not None:
                papi_tiebreaks = papi_tiebreaks[: manual_index + 1]
            else:
                papi_tiebreaks = papi_tiebreaks[:2]
                papi_tiebreaks.append(PapiTieBreak.get_outer_value(ManualTieBreak()))
            tournament.compute_tournament_player_ranks()
            player_count = tournament.player_count
            for tournament_player in tournament.tournament_players:
                manual_tiebreak_by_player_id[tournament_player.id] = (
                    player_count - tournament_player.rank + 1
                )
        elif len(papi_tiebreaks) < 3 and manual_index is None:
            # If a spot is available, add a manual tie-break representing the start rank
            # This way, the rankings are the same on all rounds
            papi_tiebreaks.append(PapiTieBreak.get_outer_value(ManualTieBreak()))
            player_count = tournament.player_count
            for index, tournament_player in enumerate(
                sorted(
                    tournament.tournament_players,
                    key=lambda p: p.starting_rank_sort_key,
                )
            ):
                manual_tiebreak_by_player_id[tournament_player.id] = (
                    player_count - index
                )
        elif manual_index is not None:
            # Setup the manual tie-break values from the stored value
            manual_tiebreak_by_player_id = {
                tournament_player.id: tournament_player.manual_tiebreak
                for tournament_player in tournament.tournament_players
                if tournament_player.manual_tiebreak is not None
            }
            # Those values can be negative, so to have a clean representation in Papi a delta is added
            if manual_tiebreak_by_player_id:
                min_value = min(manual_tiebreak_by_player_id.values())
                if min_value <= 0:
                    manual_tiebreak_by_player_id = {
                        player_id: manual_tiebreak - (min_value + 1)
                        for player_id, manual_tiebreak in manual_tiebreak_by_player_id.items()
                    }
        papi_tiebreaks += [None] * (3 - len(papi_tiebreaks))
        return papi_tiebreaks, manual_tiebreak_by_player_id

    def _player_to_papi_player(
        self,
        tournament_player: TournamentPlayer,
        player_id_to_index: dict[int, int],
        pab_value: Result,
        manual_tie_break_value: int | None,
        anonymize_player_data: bool,
    ) -> PapiPlayer:
        """Convert a Player object to PapiPlayer."""

        plugin_data = tournament_player.plugin_data[PLUGIN_NAME]
        assert isinstance(plugin_data, FfePlayerPluginData)

        fixed_board: int | None = tournament_player.fixed
        if manual_tie_break_value is not None:
            # The relative order of the players is stored in the fixed table field with values above 1000
            fixed_board = manual_tie_break_value + 1000
        dob: date | None = None
        if tournament_player.date_of_birth:
            dob = tournament_player.date_of_birth
        elif tournament_player.year_of_birth:
            dob = date(tournament_player.year_of_birth, 1, 1)
        papi_category = ''
        if tournament_player.year_of_birth:
            category = PlayerCategory.from_year_of_birth(
                tournament_player.event,
                tournament_player.year_of_birth,
                tournament_player.tournament.start_date,
                tournament_player.tournament.stop_date,
                junior_categories=PlayerCategory.get_junior_categories(
                    [8, 10, 12, 14, 16, 18, 20]
                ),
                senior_categories=PlayerCategory.get_senior_categories([20, 50, 65]),
            )
            papi_category = PapiPlayerCategory.get_outer_value(category) or ''
        papi_player = PapiPlayer(
            lastName=tournament_player.last_name,
            firstName=tournament_player.first_name,
            birthDate=dob.strftime(PAPI_DATE_FORMAT) if dob else None,
            category=papi_category,
            gender=PapiPlayerGender.get_outer_value(tournament_player.gender),
            email=None if anonymize_player_data else tournament_player.mail,
            phone=None if anonymize_player_data else tournament_player.phone,
            comment=tournament_player.comment,
            owed=tournament_player.owed if tournament_player.owed != 0 else None,
            paid=tournament_player.paid if tournament_player.paid != 0 else None,
            fideTitle=PapiPlayerTitle.get_outer_value(
                tournament_player.strongest_title
            ),
            fideCode=str(tournament_player.fide_id)
            if tournament_player.fide_id
            else None,
            federation=tournament_player.federation.name,
            club=tournament_player.club.name,
            fixedBoard=fixed_board,
            checkedIn=tournament_player.check_in,
            elo=self._get_papi_elo(tournament_player, TournamentRating.STANDARD),
            fideElo=self._get_papi_elo_type(
                tournament_player, TournamentRating.STANDARD
            ),
            rapidElo=self._get_papi_elo(tournament_player, TournamentRating.RAPID),
            fideRapidElo=self._get_papi_elo_type(
                tournament_player, TournamentRating.RAPID
            ),
            blitzElo=self._get_papi_elo(tournament_player, TournamentRating.BLITZ),
            fideBlitzElo=self._get_papi_elo_type(
                tournament_player, TournamentRating.BLITZ
            ),
            licenceType=PapiPlayerFFELicence.get_outer_value(
                plugin_data.ffe_licence, plugin_data.ffe_licence_number
            ),
            refFFE=plugin_data.ffe_id
            or (self.MOCK_FFE_ID_DELTA + tournament_player.id),
            nrFFE=plugin_data.ffe_licence_number,
            league=plugin_data.league,
        )

        # Convert rounds/pairings
        tournament = tournament_player.tournament
        eliminates = tournament.pairing_system.eliminates_participants
        for round, pairing in tournament_player.pairings_by_round.items():
            papi_round = PapiRound.from_pairing(pairing, pab_value)

            # Get opponent index using the mapping from internal player ID to index
            opponent_index = None
            if pairing.opponent_id is not None:
                opponent_index = player_id_to_index.get(pairing.opponent_id)
            papi_round.opponent = opponent_index

            # In a knock-out a player has no opponent in a round when they are
            # eliminated (unpaired) or seated on a structural bye (a top seed
            # sitting the round out). Papi cannot take a *scoring* bye with no
            # adversary — it assigns a default one, so several such byes in a
            # round collide on its per-round adversary index — so represent
            # every opponent-less played round as a zero-point bye, which it
            # accepts and which leaves the score untouched (a knock-out ranks
            # on the round reached, not on the points).
            if (
                eliminates
                and papi_round.opponent is None
                and tournament.round_has_pairings(round)
            ):
                papi_round = PapiRound.zero_point_bye()

            papi_player.rounds[round] = papi_round

        return papi_player

    def _get_papi_elo(
        self, tournament_player: TournamentPlayer, tournament_rating: TournamentRating
    ) -> int:
        # Override unrated rapid/blitz rating in the export
        # When exporting to Papi we can safely assume that the player type for the tournament rating is FIDE
        if tournament_player.rating_is_overridden(
            tournament_rating, PlayerRatingType.FIDE
        ):
            tournament_rating = TournamentRating.STANDARD
        return tournament_player.get_rating_and_type(
            tournament_rating, PlayerRatingType.FIDE, tournament_player.category
        ).value

    def _get_papi_elo_type(
        self, tournament_player: TournamentPlayer, tournament_rating: TournamentRating
    ) -> str:
        if tournament_player.rating_is_overridden(
            tournament_rating, PlayerRatingType.FIDE
        ):
            tournament_rating = TournamentRating.STANDARD
        rating_and_type = tournament_player.get_rating_and_type(
            tournament_rating, PlayerRatingType.FIDE, tournament_player.category
        )
        rating_type = rating_and_type.type
        default_rating = PapiPlayerRatingType.get_outer_value(
            PlayerRatingType.ESTIMATED
        )
        assert default_rating is not None
        if rating_type:
            return PapiPlayerRatingType.get_outer_value(rating_type) or default_rating
        return default_rating

    def _papi_player_to_dict(self, papi_player: PapiPlayer) -> dict:
        """Convert PapiPlayer to dictionary for JSON serialization."""
        player_dict = {k: v for k, v in papi_player.__dict__.items() if v is not None}
        # Convert rounds dict to proper format
        rounds_dict = {}
        for round_nb, papi_round in papi_player.rounds.items():
            rounds_dict[str(round_nb)] = {
                k: v for k, v in papi_round.__dict__.items() if v is not None
            }
        player_dict['rounds'] = rounds_dict
        return player_dict

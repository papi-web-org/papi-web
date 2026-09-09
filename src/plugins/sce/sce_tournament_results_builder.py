"""Builds the tournament results payload for the SCE platform API."""

from dataclasses import dataclass
from typing import Any

from data.tie_breaks.cutters import CutTieBreakCutter, MedianTieBreakCutter
from data.tie_breaks.options import (
    CutterTieBreakOption,
    CutterWithMedianTieBreakOption,
    ForeModifierTieBreakOption,
    KoyaLimitTieBreakOption,
    PlayedModifierTieBreakOption,
    ReversedTieBreakOption,
)
from data.tie_breaks.tie_breaks import TieBreak
from data.tournament import Tournament
from plugins.ffe.ffe_tie_breaks import BasePapiTieBreak
from plugins.manager import plugin_manager
from plugins.sce.sce_mappers import (
    SCEPairingSystem,
    SCEPlayerGender,
    SCEPlayerRatingType,
)
from plugins.sce.utils import SCEUtils
from utils.enum import Result

# Tiebreak base codes known to the SCE frontend (FIDE + other supported bases)
_KNOWN_BASES: frozenset[str] = frozenset(
    {
        'DE',
        'WIN',
        'WON',
        'BPG',
        'BWG',
        'REP',
        'PS',
        'BH',
        'AOB',
        'FB',
        'SB',
        'KS',
        'ARO',
        'APRO',
        'APPO',
        'TPR',
        'PTP',
        'MPvGP',
        'ESB',
        'EDE',
        'BC',
        'TBR',
        'BBE',
        'SSSC',
        'KA',
        'SOB',
        'MAN',
    }
)


def _tiebreak_to_dict(tie_break: TieBreak) -> dict[str, Any]:
    # FFE Papi variants: report as their FIDE equivalent base
    if isinstance(tie_break, BasePapiTieBreak):
        return {'base': tie_break.base_tie_break.base_acronym}

    available = set(tie_break.available_options())
    base = tie_break.base_acronym
    result: dict[str, Any] = {'base': base}

    # Cut / Median — CutterWithMedian takes precedence over plain Cutter
    for option_type in (CutterWithMedianTieBreakOption, CutterTieBreakOption):
        if option_type in available:
            cutter = tie_break._get_option(option_type).cutter  # noqa: SLF001
            if isinstance(cutter, CutTieBreakCutter):
                result['cut'] = cutter.cut_value()
            elif isinstance(cutter, MedianTieBreakCutter):
                result['median'] = cutter.cut_value()
            break

    # Played modifier
    if PlayedModifierTieBreakOption in available:
        if tie_break._get_option(PlayedModifierTieBreakOption).value:  # noqa: SLF001
            result['played'] = True

    # Fore modifier (e.g. AOB/F — Average of Opponents' Buchholz with Fore)
    if ForeModifierTieBreakOption in available:
        if tie_break._get_option(ForeModifierTieBreakOption).value:  # noqa: SLF001
            result['fore'] = True

    # Reversed modifier (TPN/R - RTNG/R)
    if ReversedTieBreakOption in available:
        result['reversed'] = True

    # Koya limit (half-points above/below the 50% threshold)
    if KoyaLimitTieBreakOption in available:
        limit = tie_break._get_option(KoyaLimitTieBreakOption).value  # noqa: SLF001
        if limit:
            result['limit'] = limit

    # Unknown bases need an explicit name for the frontend to display
    if base not in _KNOWN_BASES:
        result['name'] = tie_break.full_name

    return result


@dataclass
class SCEUploadColumn:
    id: str
    label: str | None = None
    is_custom: bool = False

    def __post_init__(self):
        if self.is_custom and self.label is None:
            raise ValueError('Custom columns require a label')

    def to_dict(self) -> dict[str, Any]:
        data = {'key': f'custom:{self.id}' if self.is_custom else self.id}
        if self.label is not None:
            data['label'] = self.label
        return data


def _build_display_config(tournament: Tournament) -> dict[str, Any]:
    event = tournament.event
    player_columns: list[SCEUploadColumn] = [
        SCEUploadColumn('pairingNumber'),
        SCEUploadColumn('name'),
        SCEUploadColumn('rating'),
        SCEUploadColumn('ageCategory'),
        SCEUploadColumn('federation'),
        SCEUploadColumn('club'),
    ]

    plugin_manager.hook_for_event(event, 'alter_sce_upload_player_columns')(
        columns=player_columns
    )

    ranking_columns: list[SCEUploadColumn] = [
        SCEUploadColumn('rank'),
        SCEUploadColumn('name'),
        SCEUploadColumn('rating'),
        SCEUploadColumn('ageCategory'),
        SCEUploadColumn('federation'),
        SCEUploadColumn('club'),
        SCEUploadColumn('points'),
    ]
    for i in range(len(tournament.tie_breaks)):
        ranking_columns.append(SCEUploadColumn(f'tb:{i}'))
    plugin_manager.hook_for_event(event, 'alter_sce_upload_ranking_columns')(
        columns=ranking_columns
    )

    white_pairing_columns: list[SCEUploadColumn] = [
        SCEUploadColumn('points'),
        SCEUploadColumn('name'),
        SCEUploadColumn('rating'),
    ]
    black_pairing_columns: list[SCEUploadColumn] = [
        SCEUploadColumn('name'),
        SCEUploadColumn('rating'),
        SCEUploadColumn('points'),
    ]

    return {
        'playerColumns': [column.to_dict() for column in player_columns],
        'rankingColumns': [column.to_dict() for column in ranking_columns],
        'pairings': [
            {'type': 'column', 'key': 'table'},
            {
                'type': 'white',
                'columns': [column.to_dict() for column in white_pairing_columns],
            },
            {'type': 'column', 'key': 'result'},
            {
                'type': 'black',
                'columns': [column.to_dict() for column in black_pairing_columns],
            },
        ],
    }


def _scoring_system(tournament: Tournament) -> dict[str, float] | None:
    win = tournament.win_points
    draw = tournament.draw_points
    loss = tournament.loss_points
    pab = tournament.pab_points

    if win == 1.0 and draw == 0.5 and loss == 0.0 and pab == 1.0:
        return None

    scoring: dict[str, float] = {}
    if win != 1.0:
        scoring['win'] = win
    if draw != 0.5:
        scoring['draw'] = draw
    if loss != 0.0:
        scoring['loss'] = loss
    if pab != win:
        scoring['pairingAllocatedBye'] = pab
    return scoring or None


def _build_players(tournament: Tournament) -> list[dict[str, Any]]:
    players = []
    for player in tournament.tournament_players_by_pairing_number.values():
        if player.is_excluded_from_standings:
            continue
        p: dict[str, Any] = {
            'pairingNumber': player.pairing_number,
            'lastName': player.last_name,
        }
        if player.first_name:
            p['firstName'] = player.first_name
        if player.strongest_title.value:
            p['title'] = player.strongest_title.value
        if player.rating:
            p['rating'] = player.rating
            rating_type_str = SCEPlayerRatingType.get_outer_value(player.rating_type)
            if rating_type_str:
                p['ratingType'] = rating_type_str
        if player.fide_id:
            p['fideId'] = str(player.fide_id)
        if player.category.name:
            p['ageCategory'] = player.category.name
        if player.federation.name:
            p['federation'] = player.federation.name
        if player.club.name:
            p['club'] = player.club.name
        if player.year_of_birth:
            p['yearOfBirth'] = player.year_of_birth
        gender = SCEPlayerGender.get_outer_value(player.gender)
        if gender:
            p['gender'] = gender

        sce_player_data = SCEUtils.get_player_plugin_data(player)
        if sce_player_data.id:
            p['registrationId'] = sce_player_data.id

        custom_fields: dict[str, Any] = {}
        plugin_manager.hook_for_event(
            player.event, 'add_sce_upload_player_custom_fields'
        )(player=player, custom_fields=custom_fields)
        if custom_fields:
            p['custom'] = custom_fields

        players.append(p)
    return players


def _build_pairings(tournament: Tournament) -> list[dict[str, Any]]:
    pairings = []
    for round_ in range(1, tournament.current_round + 1):
        for board in tournament.get_round_boards(round_):
            black = board.black_tournament_player
            if board.white_tournament_player.is_excluded_from_standings or (
                black is not None and black.is_excluded_from_standings
            ):
                continue

            entry: dict[str, Any] = {
                'round': round_,
                'table': (
                    board.number
                    if not tournament.leave_fixed_board_holes
                    else board.standard_number
                ),
                'board': board.id,
                'whitePairingNumber': board.white_tournament_player.pairing_number,
                'blackPairingNumber': black.pairing_number if black else -1,
                'whiteResult': board.white_pairing.result.value,
                'blackResult': (
                    board.black_pairing.result.value
                    if black
                    else Result.NO_RESULT.value
                ),
            }
            # TODO (Molrn) Add pairing custom fields to support Handicap games
            pairings.append(entry)
    return pairings


def _build_rankings(tournament: Tournament) -> list[dict[str, Any]]:
    ranking_round = tournament.max_ranking_round
    standings = []
    if ranking_round > 0:
        tournament.compute_tournament_player_ranks(after_round=ranking_round)
        for rank, player in tournament.tournament_players_by_rank.items():
            if player.is_excluded_from_standings:
                continue
            standings.append(
                {
                    'rank': rank,
                    'pairingNumber': player.pairing_number,
                    'points': player.points,
                    'tiebreaks': [tv.display_value for tv in player.tie_break_values],
                }
            )

    return [{'round': ranking_round, 'standings': standings}]


def build_tournament_results(
    tournament: Tournament,
    sce_event_id: str,
    sce_tournament_id: str,
) -> dict[str, Any]:
    """Build the full tournament results payload for the SCE API."""
    tournament.set_tournament_players_pairing_numbers()

    tiebreaks = [_tiebreak_to_dict(tb) for tb in tournament.tie_breaks]
    display_config = _build_display_config(tournament)

    tournament_meta: dict[str, Any] = {
        'name': tournament.name,
        'type': SCEPairingSystem.get_outer_value(tournament.pairing_system),
        'rounds': tournament.rounds,
        'currentRound': tournament.current_round,
        'tiebreaks': tiebreaks,
        'displayConfig': display_config,
    }
    if tournament.time_control_trf25:
        tournament_meta['timeControl'] = tournament.time_control_trf25
    scoring = _scoring_system(tournament)
    if scoring:
        tournament_meta['scoringSystem'] = scoring

    return {
        'version': 1,
        'eventId': sce_event_id,
        'tournamentId': sce_tournament_id,
        'tournament': tournament_meta,
        'players': _build_players(tournament),
        'pairings': _build_pairings(tournament),
        'rankings': _build_rankings(tournament),
    }

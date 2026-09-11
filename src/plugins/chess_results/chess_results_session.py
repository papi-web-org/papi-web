import os
import random
import xml.etree.ElementTree as ET
from functools import partial
from logging import Logger

import requests
from requests import Session

from common.logger import get_logger
from data.tournament import Tournament
from data.pairings.variations import (
    DoubleBergerRoundRobinVariation,
    DoubleBergerTeamRoundRobinVariation,
)
from database.sqlite.config.config_database import ConfigDatabase
from plugins.chess_results import PLUGIN_NAME, MAX_TIE_BREAKS
from plugins.chess_results.chess_results_mappers import (
    ChessResultTournamentRating,
    ChessResultsPlayerGender,
    ChessResultsTieBreak,
    ChessResultPairingSystem,
)
from plugins.chess_results.chess_results_upload_status import (
    FailureCRUploadStatus,
    FinishedFailureCRUploadStatus,
    UnexpectedFailureCRUploadStatus,
)
from plugins.chess_results.utils import CRUtils
from plugins.manager import plugin_manager
from plugins.utils import PluginUtils
from utils.enum import Result
from utils.time_control import trf25_to_human_readable

logger: Logger = get_logger()
get_data = partial(PluginUtils.get_plugin_data, PLUGIN_NAME)

CHESS_RESULTS_URL: str = 'https://chess-results.com/Uploadxml.aspx'
CHESS_RESULTS_SOURCE = 13


def _forfeit_code(result: Result) -> str:
    """Chess-Results ``forfeit`` marker: ``K`` for forfeits, ``D`` for
    penalty results (0-0 and the half-point penalties), ``U`` for
    unrated results, empty otherwise."""
    match result:
        case Result.FORFEIT_LOSS | Result.FORFEIT_WIN | Result.DOUBLE_FORFEIT:
            return 'K'
        case (
            Result.PENALTY_LL
            | Result.PENALTY_DL
            | Result.PENALTY_LD
            | Result.UNRATED_PENALTY_LL
            | Result.UNRATED_PENALTY_DL
            | Result.UNRATED_PENALTY_LD
        ):
            return 'D'
        case Result.UNRATED_WIN | Result.UNRATED_DRAW | Result.UNRATED_LOSS:
            return 'U'
        case _:
            return ''


def _upload_federation(event) -> str:
    """The federation sent to Chess-Results. Setting the
    ``CHESS_RESULTS_TEST`` environment variable forces the ``XXX`` test
    federation, which keeps the upload out of the real country listings."""
    if os.getenv('CHESS_RESULTS_TEST'):
        return 'XXX'
    return event.federation or 'FID'


class ChessResultsSession(Session):
    """A requests session specialized for communication with Chess-Results.com."""

    def __init__(self, tournament: Tournament):
        super().__init__()
        self.tournament = tournament

    def _chess_results_init(self) -> str:
        """Initializes a session on Chess-Results.com
        Return sid on success, False otherwise."""
        url = CHESS_RESULTS_URL
        params: dict[str, str | int] = {
            'key1': 'GETSID',
            'source': CHESS_RESULTS_SOURCE,
        }

        response = requests.get(url, params=params)
        response.raise_for_status()  # Raise an error if the request failed
        root = ET.fromstring(response.text)

        result = root.find('result')
        if result is not None and result.attrib.get('status') == 'OK':
            return result.attrib['sid']

        raise Exception('No SID found in response.')

    def get_new_tournament_key(
        self, source: int, sid: str, creator_id: str, tournament: Tournament
    ) -> str:
        url = 'https://chess-results.com/Uploadxml.aspx'
        root = ET.Element('chessresults')
        ET.SubElement(
            root,
            'getkey',
            {
                'source': str(source),
                'sid': CRUtils.encrypt(sid),
                'creatorID': str(creator_id),
                'federation': _upload_federation(tournament.event),
                'tournament': tournament.full_name,
            },
        )
        xml_payload = ET.tostring(root, encoding='utf-8', xml_declaration=True).decode(
            'utf-8'
        )

        headers = {'Content-Type': 'application/xml'}
        resp = requests.post(
            url,
            params={'key1': 'GETKEY'},
            data=xml_payload.encode('utf-8'),
            headers=headers,
        )
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        result = root.find('result')
        if result is not None and result.attrib.get('status') == 'OK':
            return result.attrib['key']
        else:
            raise RuntimeError('GETKEY failed: ' + resp.text)

    def build_tournament_xml(
        self,
        tournament: Tournament,
        sid: str,
        tnr: str,
        creator_id: str,
        state: int | None,
    ) -> str:
        """
        Build Chess-Results upload XML from a Sharly Chess Tournament.
        """

        event = tournament.event
        root = ET.Element('chessresults')

        # Team-vs-team systems upload as Chess-Results team tournaments
        # (type 2/3 + team sections); flat fixed-table systems keep the
        # individual layout. Systems without a dedicated Chess-Results
        # type upload as individual Swiss.
        is_team = (
            tournament.is_team_tournament and tournament.pairing_system.paired_by_team
        )
        type_code, replay = ChessResultPairingSystem.get_outer_value(
            tournament.pairing_system
        ) or ('0', '1')
        # "Replayed" (each pairing met more than once) is a variation, not a
        # separate system: a double round-robin reports its round count as
        # the replay so Chess-Results encodes it as a multi-cycle event.
        is_replayed_pairing = isinstance(
            tournament.pairing_variation,
            (DoubleBergerRoundRobinVariation, DoubleBergerTeamRoundRobinVariation),
        )
        if is_replayed_pairing:
            replay = str(tournament.rounds)
        if is_team:
            color_pattern = (tournament.color_pattern or 'W').upper()
            home_color = 'w' if color_pattern[:1] == 'W' else 's'
            # 'J' when every board of a team plays the same colour
            # (all-white AND all-black patterns), 'N' when they alternate.
            all_same_color = all(color == color_pattern[0] for color in color_pattern)
            same_color = 'J' if all_same_color else 'N'
            player_per_team = str(tournament.team_player_count or '')
        else:
            home_color = ''
            same_color = ''
            player_per_team = ''

        # --- Tournament section ---
        tdata = ET.SubElement(root, 'tournamentdata')

        # Get up to `MAX_TIE_BREAKS`` tiebreak keys (pad with zeros if fewer).
        # The points are one of them (code 1), in whatever place the
        # ranking gives them.
        tb_details: list[tuple[str, str]] = []
        for tie_break in tournament.tie_breaks[:MAX_TIE_BREAKS]:
            cr_tie_break = ChessResultsTieBreak.from_tie_break(tournament, tie_break)
            tb_details.append((str(cr_tie_break.number), cr_tie_break.params_str))
        while len(tb_details) < MAX_TIE_BREAKS:
            tb_details.append(('0', ''))

        ET.SubElement(
            tdata,
            'tournament',
            {
                'key': str(tnr),
                'type': type_code,
                'name': tournament.full_name[:160],
                'fideeventid': '',
                'remark': f'#{CRUtils.resolve_remark(tournament)}'[:599],
                'director': (event.organiser_director or '')[:80],
                'organiser': (event.organiser_name or '')[:80],
                'location': tournament.location or '',
                'arbiter': ', '.join(
                    arbiter.fide_arbiter_str for arbiter in tournament.arbiters
                ),
                'rounds': str(tournament.rounds),
                'currentround': str(tournament.current_round or 0),
                'rankinground': str(
                    max(
                        0,
                        tournament.current_round - 1
                        if tournament.playing
                        else tournament.current_round,
                    )
                ),
                'sortstartrank': '2',
                'from': tournament.start_date.strftime('%Y%m%d'),
                'to': tournament.stop_date.strftime('%Y%m%d'),
                'ratedfide': '-',
                'ratednational': '-',
                'replay': replay,
                'timetype': ChessResultTournamentRating.get_outer_value(
                    tournament.rating
                )
                or '',
                'timecontrol': trf25_to_human_readable(tournament.time_control_trf25)
                if tournament.time_control_trf25
                else '',
                'homecolor': home_color,
                'samecolor': same_color,
                'playerperteam': player_per_team,
                'ratingavg': str(round(tournament.average_player_rating)),
                'endstatus': 'N',
                'chiefarbiter': getattr(
                    tournament.chief_arbiter, 'fide_arbiter_str', ''
                ),
                'deputyarbiter': ', '.join(
                    arbiter.fide_arbiter_str for arbiter in tournament.deputy_arbiters
                ),
                'homepageorganiser': (event.organiser_home_page or '')[:80],
                'mail': (event.organiser_email or '')[:80],
                'federation': _upload_federation(tournament.event),
                'federalstate': str(state) if state else '',
                'creator': creator_id,
            }
            | {f'tb{i + 1}no': tb_details[i][0] for i in range(MAX_TIE_BREAKS)}
            | {
                f'tb{i + 1}_detail': tb_details[i][1]
                for i in range(min(MAX_TIE_BREAKS, len(tb_details)))
            },
        )

        # --- Rounds section ---
        rdata = ET.SubElement(root, 'rounds')
        for rnd in range(1, tournament.rounds + 1):
            dt = tournament.round_datetimes.get(rnd)
            ET.SubElement(
                rdata,
                'round',
                {
                    'round': str(rnd),
                    'date': dt.strftime('%Y%m%d') if dt else '',
                    'time': dt.strftime('%H:%M') if dt else '',
                    # In a two-game match every round replays the same
                    # pairing — the round number is the encounter index.
                    'replay': str(rnd) if is_replayed_pairing else '1',
                },
            )

        if is_team:
            self._append_team_sections(root, tournament)
            self._append_security(root, sid, tnr, creator_id)
            xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            return xml_bytes.decode('utf-8')

        # --- Player list ---
        pdata = ET.SubElement(root, 'players')
        prev_tb_values: list[str] | None = None
        tournament.compute_tournament_player_ranks()
        # Chess-Results publishes the standings, so a player dropped from
        # them (FIDE 6.6) is not uploaded at all, games included.
        for p in tournament.tournament_players_by_pairing_number.values():
            if p.is_excluded_from_standings:
                continue
            # Get up to `MAX_TIE_BREAKS` tiebreak keys (pad with zeros if fewer)
            tb_values: list[str] = []
            for tbv in p.tie_break_values[:MAX_TIE_BREAKS]:
                value = str(tbv.value)
                if tbv.tie_break.is_manual:
                    value = str(1000 - float(tbv.value))
                tb_values.append(str(value))
            while len(tb_values) < MAX_TIE_BREAKS:
                tb_values.append('')

            same_as_previous = (
                tb_values == prev_tb_values if prev_tb_values is not None else False
            )
            prev_tb_values = tb_values

            ratings = p.ratings.get(tournament.rating)
            k_factor, k_factor_is_estimated = p.fide_rating_coefficient
            rating_change = p.fide_rating_change
            ET.SubElement(
                pdata,
                'player',
                {
                    'no': str(
                        p.pairing_number if p.pairing_number is not None else p.rank
                    ),
                    'id': str(p.id),
                    'lastname': p.last_name,
                    'firstname': p.first_name or '',
                    'atitle': '',
                    'title': p.strongest_title.short_name,
                    'rtg': str(p.rating),
                    'rtgfide': str(getattr(ratings, 'fide', '') or ''),
                    'rtgnat': str(getattr(ratings, 'national', '') or ''),
                    'dob': str(p.year_of_birth),
                    'sex': ChessResultsPlayerGender.get_outer_value(p.gender) or '',
                    'fed': p.federation.name,
                    'board': '',
                    'teamno': '0',
                    'fideid': str(p.fide_id or ''),
                    'clubname': p.club.name or '',
                    'typ': p.category.name,
                    'rank': str(p.rank),
                    'pts': str(p.points or 0),
                    'equal': 'J' if same_as_previous else 'N',
                    # Only the official coefficient is uploaded: an estimate
                    # would make Chess-Results show wrong rating changes.
                    'kfaktor': '' if k_factor_is_estimated else str(k_factor),
                    'rtgdifference': str(rating_change)
                    if rating_change is not None
                    else '',
                    'state': '',
                }
                | {f'tb{i + 1}': tb_values[i] for i in range(MAX_TIE_BREAKS)},
            )

        # --- Pairings / Results ---
        ppair = ET.SubElement(root, 'playerpairings')
        point_values: dict[Result, float] = {
            Result.PAIRING_ALLOCATED_BYE: tournament.pab_points,
        }
        for round_ in range(1, tournament.current_round + 1):
            tournament.set_for_round(round_)
            tournament.compute_tournament_player_ranks(after_round=round_)
            last_board_id = 0
            boards = tournament.get_round_boards(round_)
            # In compact numbering the display number carries the fixed table
            # (and is a clean bijection); in hole mode it can duplicate, so keep
            # the positional id there.
            compact_numbering = not tournament.leave_fixed_board_holes
            for board in boards:
                if any(
                    player is not None and player.is_excluded_from_standings
                    for player in (
                        board.optional_white_tournament_player,
                        board.black_tournament_player,
                    )
                ):
                    continue
                table_number = board.number if compact_numbering else board.board_id
                ET.SubElement(
                    ppair,
                    'playerpairing',
                    {
                        'round': str(round_),
                        'pairing': str(table_number),
                        'board': '1',
                        'whiteno': str(board.white_tournament_player.pairing_number),
                        'blackno': str(
                            board.black_tournament_player.pairing_number
                            if board.black_tournament_player
                            else -1
                        ),
                        'reswhite': str(
                            board.white_pairing.result.points(point_values) or ''
                        ),
                        'resblack': str(
                            board.black_pairing.result.points(point_values) or ''
                        )
                        if board.black_tournament_player
                        else '',
                        'forfeit': _forfeit_code(board.result),
                    },
                )
                last_board_id = max(last_board_id, table_number)

            for player in tournament.get_unpaired_tournament_players(boards):
                if player.is_excluded_from_standings:
                    continue
                last_board_id += 1
                result = player.pairings_by_round[round_].result
                ET.SubElement(
                    ppair,
                    'playerpairing',
                    {
                        'round': str(round_),
                        'pairing': str(last_board_id),
                        'board': '1',
                        'whiteno': str(player.pairing_number),
                        'blackno': '-2',
                        'reswhite': str(result.points(point_values) or ''),
                        'resblack': '',
                        'forfeit': '',
                    },
                )

        self._append_security(root, sid, tnr, creator_id)

        # Return as UTF-8 XML
        xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        return xml_bytes.decode('utf-8')

    @staticmethod
    def _append_security(root: ET.Element, sid: str, tnr: str, creator_id: str):
        security = ET.SubElement(root, 'security')
        ET.SubElement(
            security,
            'securitydata',
            {
                'source': str(CHESS_RESULTS_SOURCE),
                'sid': CRUtils.encrypt(sid),
                'creator_sid': CRUtils.encrypt(creator_id),
                'tnr_sid': CRUtils.encrypt(str(tnr)),
            },
        )

    def _append_team_sections(self, root: ET.Element, tournament: Tournament):
        """Players, teams, team pairings and per-board player pairings of
        a team-vs-team tournament (Chess-Results types 2/3). Players are
        numbered sequentially grouped by team in roster order — the
        numbering Chess-Results displays and that the pairings reference."""
        from utils.enum import ScoreType

        event = tournament.event
        # Chess-Results publishes the standings, so a team dropped from
        # them (FIDE 6.6) is not uploaded at all, matches included.
        teams = sorted(
            (
                team
                for team in event.teams_by_id.values()
                if team.tournament_id == tournament.id
                and not team.is_excluded_from_standings
            ),
            key=lambda team: (team.pairing_number or 0, team.name.lower()),
        )
        team_no = {
            team.id: team.pairing_number or index
            for index, team in enumerate(teams, start=1)
        }
        tournament_players_by_id = tournament.tournament_players_by_id

        # Dense individual ranks by points (the player tie-breaks are team
        # tie-breaks here, meaningless per player — left empty).
        uploaded_player_ids = {player.id for team in teams for player in team.players}
        ranked = sorted(
            (
                tp
                for tp in tournament_players_by_id.values()
                if tp.id in uploaded_player_ids
            ),
            key=lambda tp: -(tp.points or 0),
        )
        rank_by_id: dict[int, int] = {}
        previous_points: float | None = None
        rank = 0
        for index, tp in enumerate(ranked, start=1):
            points = tp.points or 0
            if previous_points is None or points < previous_points:
                rank = index
                previous_points = points
            rank_by_id[tp.id] = rank

        # --- Player list (grouped by team, roster order) ---
        pdata = ET.SubElement(root, 'players')
        no_by_player_id: dict[int, int] = {}
        no = 0
        for team in teams:
            for board_index, player in enumerate(team.players, start=1):
                no += 1
                no_by_player_id[player.id] = no
                member_tp = tournament_players_by_id.get(player.id)
                ratings = (
                    member_tp.ratings.get(tournament.rating) if member_tp else None
                )
                k_factor, k_factor_is_estimated = (
                    member_tp.fide_rating_coefficient if member_tp else (0, True)
                )
                rating_change = member_tp.fide_rating_change if member_tp else None
                ET.SubElement(
                    pdata,
                    'player',
                    {
                        'no': str(no),
                        'id': str(player.id),
                        'lastname': player.last_name,
                        'firstname': player.first_name or '',
                        'atitle': '',
                        'title': player.strongest_title.short_name,
                        'rtg': str(member_tp.rating if member_tp else ''),
                        'rtgfide': str(getattr(ratings, 'fide', '') or ''),
                        'rtgnat': str(getattr(ratings, 'national', '') or ''),
                        'dob': str(player.year_of_birth or ''),
                        'sex': ChessResultsPlayerGender.get_outer_value(player.gender)
                        or '',
                        'fed': player.federation.name,
                        'board': str(board_index),
                        'teamno': str(team_no[team.id]),
                        'fideid': str(player.fide_id or ''),
                        'clubname': player.club.name or '',
                        'typ': player.category.name,
                        'rank': str(rank_by_id.get(player.id, '')),
                        'pts': str((member_tp.points if member_tp else 0) or 0),
                        'equal': 'N',
                        'kfaktor': '' if k_factor_is_estimated else str(k_factor),
                        'rtgdifference': str(rating_change)
                        if rating_change is not None
                        else '',
                        'state': '',
                    }
                    | {f'tb{i + 1}': '' for i in range(MAX_TIE_BREAKS)},
                )

        # --- Teams ---
        standings_by_team_id = {
            row['team'].id: row for row in tournament.team_standings()
        }
        primary_is_mp = tournament.primary_score == ScoreType.MATCH_POINTS
        tdata = ET.SubElement(root, 'teams')
        previous_tbs: list[str] | None = None
        for team in teams:
            row = standings_by_team_id.get(team.id)
            tb_values: list[str] = []
            if row:
                for tbv in row.get('tie_break_values', [])[:MAX_TIE_BREAKS]:
                    tb_values.append(f'{tbv.value:g}')
            while len(tb_values) < MAX_TIE_BREAKS:
                tb_values.append('')
            same_as_previous = (
                tb_values == previous_tbs if previous_tbs is not None else False
            )
            previous_tbs = tb_values
            points = (row['mp'] if primary_is_mp else row['gp']) if row else 0
            ET.SubElement(
                tdata,
                'team',
                {
                    'no': str(team_no[team.id]),
                    'teamname': team.name[:40],
                    'teamshort': team.name[:25],
                    'rank': str(row['rank'] if row else ''),
                    'points': f'{points:g}',
                    'captain': (team.captain_display_name or '')[:70],
                    'equal': 'J' if same_as_previous else 'N',
                    'federation': team.federation,
                    'state': '',
                    'rtg_average': str(team.average_rating or ''),
                }
                | {f'tb{i + 1}': tb_values[i] for i in range(MAX_TIE_BREAKS)},
            )

        # --- Pairings ---
        ppair = ET.SubElement(root, 'playerpairings')
        tpair = ET.SubElement(root, 'teampairings')
        point_values: dict[Result, float] = {
            Result.PAIRING_ALLOCATED_BYE: tournament.pab_points,
        }
        for round_ in range(1, tournament.current_round + 1):
            tournament.set_for_round(round_)
            visible_matches = sorted(
                (
                    team_board
                    for team_board in tournament.get_round_team_boards(round_)
                    if team_board.display_number is not None
                ),
                key=lambda team_board: team_board.display_number or 0,
            )
            for team_board in visible_matches:
                pairing_no = team_board.display_number
                stb = team_board.stored_team_board
                if stb.team_a_id not in team_no or (
                    stb.team_b_id is not None and stb.team_b_id not in team_no
                ):
                    continue
                gp_a, gp_b = team_board.game_points
                if stb.team_b_id is None:
                    # PAB: full game points to the bye team, no boards
                    # (team_board.game_points is 0 with no boards, so use
                    # the team-level PAB game points).
                    ET.SubElement(
                        tpair,
                        'teampairing',
                        {
                            'round': str(round_),
                            'pairing': str(pairing_no),
                            'no1': str(team_no[stb.team_a_id]),
                            'no2': '-1',
                            'res1': f'{tournament.team_pab_game_points:g}',
                            'res2': '0',
                        },
                    )
                    continue
                boards = team_board.boards
                # The 'white' team holds white on board 1.
                white_team_id = None
                if boards:
                    white_team_id, _black_team_id = team_board.board_team_ids(boards[0])
                if white_team_id is None:
                    pattern = (tournament.color_pattern or 'W').upper()
                    white_team_id = (
                        stb.team_a_id if pattern[:1] == 'W' else stb.team_b_id
                    )
                if white_team_id == stb.team_a_id:
                    no1, no2 = team_no[stb.team_a_id], team_no[stb.team_b_id]
                    res1, res2 = gp_a, gp_b
                else:
                    no1, no2 = team_no[stb.team_b_id], team_no[stb.team_a_id]
                    res1, res2 = gp_b, gp_a
                ET.SubElement(
                    tpair,
                    'teampairing',
                    {
                        'round': str(round_),
                        'pairing': str(pairing_no),
                        'no1': str(no1),
                        'no2': str(no2),
                        'res1': f'{res1:g}',
                        'res2': f'{res2:g}',
                    },
                )
                for slot, board in enumerate(boards, start=1):
                    wtp = board.optional_white_tournament_player
                    btp = board.black_tournament_player
                    white_pairing = board.optional_white_pairing
                    black_pairing = board.optional_black_pairing
                    ET.SubElement(
                        ppair,
                        'playerpairing',
                        {
                            'round': str(round_),
                            'pairing': str(pairing_no),
                            'board': str(slot),
                            'whiteno': str(no_by_player_id.get(wtp.id, 0))
                            if wtp
                            else '0',
                            'blackno': str(no_by_player_id.get(btp.id, 0))
                            if btp
                            else '0',
                            'reswhite': str(
                                white_pairing.result.points(point_values) or ''
                            )
                            if white_pairing
                            else '',
                            'resblack': str(
                                black_pairing.result.points(point_values) or ''
                            )
                            if black_pairing
                            else '',
                            'forfeit': _forfeit_code(board.result),
                        },
                    )

    def upload(self) -> FailureCRUploadStatus | None:
        """Upload the tournament to Chess-Results.com."""

        logger.info(
            'Sending tournament (%s) to Chess-Results.com...',
            self.tournament.name,
        )

        sid = self._chess_results_init()
        tournament_plugin_data = CRUtils.get_tournament_plugin_data(self.tournament)
        event_plugin_data = CRUtils.get_event_plugin_data(self.tournament.event)
        tnr = tournament_plugin_data.tnr
        creator_id = tournament_plugin_data.creator_id

        if not tnr:
            # See if we have a creator_id stored in the config
            chess_results_plugin = plugin_manager.plugins_by_id[PLUGIN_NAME]
            chess_results_plugin_data = chess_results_plugin.get_plugin_data()
            creator_id = chess_results_plugin_data.creator_id
            if not creator_id:
                creator_id = str(random.randint(1, 2**16 - 1))
                with ConfigDatabase(write=True) as config_database:
                    chess_results_plugin_data.creator_id = creator_id
                    stored_plugin = chess_results_plugin.context.stored_plugin
                    stored_plugin.plugin_data = (
                        chess_results_plugin_data.to_stored_value()
                    )
                    config_database.update_stored_plugin(stored_plugin)

            # First upload, create the tournament on the site
            tnr = self.get_new_tournament_key(13, sid, creator_id, self.tournament)

            tournament_plugin_data.tnr = tnr
            tournament_plugin_data.creator_id = creator_id
            CRUtils.update_tournament_plugin_data(
                self.tournament, tournament_plugin_data
            )

        assert creator_id is not None
        xml_data = self.build_tournament_xml(
            self.tournament, sid, tnr, creator_id, event_plugin_data.state
        )
        logger.debug(xml_data)

        xml_sanitized = xml_data.replace('<', '{').replace('>', '}')
        url = f'{CHESS_RESULTS_URL}?key1=UPLOAD'
        response = requests.post(url, data={'xml': xml_sanitized})
        response.raise_for_status()

        root = ET.fromstring(response.text)
        result = root.find('result')
        logger.debug(response.text)
        if result is not None and result.attrib.get('status') == 'OK':
            return None

        msg = root.find('.//message')

        if msg is not None:
            error_text = msg.attrib.get('Text', '')
            if 'MsgNo:28' in error_text:
                return FinishedFailureCRUploadStatus()

            # Retry logic: Invalid Source-ID or tournament number
            # This can happen if the user deletes the tournament and then tries to upload again
            if 'Source-ID (Swiss-Manager Tournaments) not valid' in error_text:
                logger.warning(
                    'Invalid Source-ID detected, retrying without tnr/creator_id...'
                )
                # Remove the invalid keys
                tournament_plugin_data.tnr = None
                tournament_plugin_data.creator_id = None
                CRUtils.update_tournament_plugin_data(
                    self.tournament, tournament_plugin_data
                )

                # Retry the upload once (fresh creation)
                return self.upload()

            logger.error(error_text)
        else:
            logger.error('No message received from Chess-Results.com.')
        return UnexpectedFailureCRUploadStatus()

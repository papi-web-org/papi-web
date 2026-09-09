"""
All the classes of this module are basic data classes stored in the event databases.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


from common.sharly_chess_config import SharlyChessConfig
from utils.enum import EventType, PrizeCategoryRankingBasis


def set_stored_fields(obj: Any, **fields: Any) -> None:
    """Mutate a frozen stored record while preserving its identity."""
    for name, value in fields.items():
        object.__setattr__(obj, name, value)


@dataclass
class StoredTimerHour:
    id: int | None
    uniq_id: str
    timer_id: int
    triggered_at: datetime
    text_before: str | None = None
    text_after: str | None = None
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredTimer:
    id: int | None
    name: str
    colors: dict[int, str | None]
    delays: dict[int, int | None]
    stored_timer_hours: list[StoredTimerHour] = field(
        default_factory=list[StoredTimerHour]
    )
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredPrizeCriterion:
    id: int | None
    prize_category_id: int
    type: str
    options: dict[str, Any]


@dataclass
class StoredPrize:
    id: int | None
    prize_category_id: int
    type: str
    value: float
    description: str
    complementary_value: float | None = None


@dataclass
class StoredPrizeCategory:
    id: int | None
    prize_group_id: int
    name: str
    prize_sharing: str
    sharing_threshold: float | None
    is_main: bool
    index: int
    ranking_basis: str = PrizeCategoryRankingBasis.FINAL_STANDING.value
    stored_prize_criteria: list[StoredPrizeCriterion] = field(
        default_factory=list[StoredPrizeCriterion]
    )
    stored_prizes: list[StoredPrize] = field(default_factory=list[StoredPrize])


@dataclass
class StoredPrizeGroup:
    id: int | None
    tournament_id: int
    name: str
    stored_prize_categories: list[StoredPrizeCategory] = field(
        default_factory=list[StoredPrizeCategory]
    )


@dataclass
class StoredTieBreak:
    id: int | None
    tournament_id: int
    type: str
    options: dict[str, Any]
    index: int


@dataclass
class StoredPairing:
    tournament_id: int
    player_id: int
    round_: int
    result: int
    board_id: int | None
    illegal_moves: int = 0
    effective_points: float | None = None


@dataclass(frozen=True)
class StoredBoard:
    id: int | None
    white_player_id: int | None
    black_player_id: int | None
    index: int
    last_result_update: datetime | None = None
    team_board_id: int | None = None
    # Fixed table number in force when the board was paired. ``None`` on
    # legacy boards (derive live from the seated players), ``0`` when the
    # board was snapshotted with no fixed player, a positive value for a
    # snapshotted fixed board.
    #
    # We snapshot the fixed *input*, not the resolved display number, because
    # the display number is a whole-round computation (compact fill / clash
    # resolution across sibling boards) and hole mode renders "fixed
    # (standard)" from the fixed and index-derived values separately. Freezing
    # only the fixed input stops a later edit to a player's fixed table from
    # renumbering rounds they have already played, while first_board_number,
    # board index and the numbering mode stay live.
    fixed_number: int | None = None


@dataclass
class StoredTeamRoundLineupEntry:
    team_id: int
    round_: int
    player_id: int
    index: int


@dataclass
class StoredTeamGroup:
    """Event-level reusable team grouping (club / league / …). Teams
    reference one by ``group_id``."""

    id: int | None
    name: str


@dataclass
class StoredTeam:
    id: int | None
    name: str
    tournament_id: int | None = None
    pairing_number: int | None = None
    captain_id: int | None = None
    captain_name: str | None = None
    group_id: int | None = None
    federation: str | None = None
    check_in: bool = False
    stored_round_lineups: dict[int, list[StoredTeamRoundLineupEntry]] = field(
        default_factory=dict[int, list[StoredTeamRoundLineupEntry]]
    )


@dataclass
class StoredTeamBoard:
    id: int | None
    tournament_id: int
    round_: int
    team_a_id: int
    # Table number slot (0-based). None for hidden byes (HPB / FPB /
    # ZPB) that don't occupy a table; real matches and the PAB bye
    # carry an index.
    index: int | None
    team_b_id: int | None = None
    last_result_update: datetime | None = None
    # Bye type when ``team_b_id`` is None: ``PAB`` (pairing-allocated),
    # ``HPB`` (half-point), ``FPB`` (full-point) or ``ZPB`` (zero-point).
    # NULL on regular paired team_boards.
    bye_type: str | None = None


@dataclass
class StoredTeamPairingBlock:
    id: int | None
    tournament_id: int
    team_a_id: int
    team_b_id: int
    round_: int | None = None
    reason: str | None = None


@dataclass
class StoredTeamPointAdjustment:
    """Manual per-team, per-round bonus / penalty points. ``mp_delta``
    and ``gp_delta`` may be negative. One row per (tournament, team,
    round)."""

    id: int | None
    tournament_id: int
    team_id: int
    round_: int
    mp_delta: float = 0.0
    gp_delta: float = 0.0
    reason: str | None = None


@dataclass
class StoredPlayerPointAdjustment:
    """Manual per-player, per-round bonus / penalty points for individual
    tournaments. A single ``delta`` (which may be negative) because those
    score in game points only. One row per (tournament, player, round)."""

    id: int | None
    tournament_id: int
    player_id: int
    round_: int
    delta: float = 0.0
    reason: str | None = None


@dataclass
class StoredProhibitedPairingGroup:
    """A set of members (player ids, or team ids in team mode) that must
    not be paired together. ``round_`` is None for a reusable manual
    template group, or a round number for an immutable per-round
    snapshot (manual + dimension-derived, flattened). ``is_hard``
    distinguishes hard from soft constraints. ``protect_rank`` is the
    soft-relaxation cutoff frozen for a round snapshot (members ranked
    ``<= protect_rank`` kept their soft separations); ``None`` for
    template groups, hard-only rounds, and imported snapshots."""

    id: int | None
    tournament_id: int
    round_: int | None = None
    is_hard: bool = True
    member_ids: list[int] = field(default_factory=list[int])
    protect_rank: int | None = None


@dataclass
class StoredTournamentPlayer:
    tournament_id: int = 0
    player_id: int = 0
    pairing_number: int | None = None
    manual_tiebreak: int | None = None
    stored_pairings: list[StoredPairing] = field(default_factory=list[StoredPairing])


@dataclass
class StoredPlayer:
    id: int | None
    last_name: str = ''
    ratings: dict[int, dict[str, int | None]] = field(
        default_factory=dict[int, dict[str, int | None]]
    )
    first_name: str | None = None
    date_of_birth: date | None = None
    year_of_birth: int | None = None
    gender: str = ''
    mail: str | None = None
    phone: str | None = None
    comment: str | None = None
    owed: float = 0.0
    paid: float = 0.0
    title: str = ''
    women_title: str = ''
    fide_id: int | None = None
    federation: str = 'FID'
    club: str | None = None
    fixed: int | None = None
    check_in: bool = False
    team_id: int | None = None
    team_index: int | None = None

    plugin_data: dict[str, dict[str, Any]] = field(
        default_factory=dict[str, dict[str, Any]]
    )
    transient_arbiter_titles: dict[str, Any] = field(default_factory=dict[str, Any])
    # Team name from a datasheet import (team mode); resolved to a team
    # membership after the player is persisted. Not stored.
    transient_team_name: str | None = None


@dataclass
class StoredTournament:
    id: int | None
    name: str
    index: int = 0
    time_control_trf25: str | None = None
    record_illegal_moves: int | None = None
    first_board_number: int | None = None
    paired_bye_result: int | None = None
    max_byes: int | None = None
    last_rounds_no_byes: int | None = None
    location: str | None = None
    start_date: date = field(default_factory=date.today)
    stop_date: date = field(default_factory=date.today)
    pairing: str = SharlyChessConfig.default_pairing_variation_id
    pairing_settings: dict[str, Any] = field(default_factory=dict[str, Any])
    current_round: int | None = None
    check_in_open: bool = True
    rounds: int = 1
    rating: int = 1
    player_rating_type: int | None = None
    last_update: datetime = field(default_factory=datetime.now)
    last_player_update: datetime | None = None
    last_pairing_update: datetime | None = None
    override_unrated_rapid_blitz: bool = True
    game_points: dict[int, float] | None = None
    criteria: dict[str, Any] = field(default_factory=dict)
    round_datetimes: dict[int, datetime | None] = field(default_factory=dict)
    team_player_count: int | None = None
    roster_max_size: int | None = None
    match_points: dict[int, float] | None = None
    color_pattern: str | None = None
    primary_score: str | None = None
    secondary_score_for_colours: bool = True
    team_colour_type: str | None = None
    enforce_roster_order: bool = False
    team_sort_mode: str = 'MANUAL'
    rule_set: str | None = None
    rule_set_config: dict[str, Any] = field(default_factory=dict[str, Any])
    prohibited_pairing_dimension: str | None = None
    prohibited_pairing_dimension_is_hard: bool = True
    round_robin_participation_rule: bool = True
    stored_tie_breaks: list[StoredTieBreak] = field(
        default_factory=list[StoredTieBreak]
    )
    stored_prize_groups: list[StoredPrizeGroup] = field(
        default_factory=list[StoredPrizeGroup]
    )

    stored_tournament_players: list[StoredTournamentPlayer] = field(
        default_factory=list[StoredTournamentPlayer]
    )
    stored_boards_by_round: dict[int, list[StoredBoard]] = field(
        default_factory=dict[int, list[StoredBoard]]
    )
    stored_team_boards_by_round: dict[int, list[StoredTeamBoard]] = field(
        default_factory=dict[int, list[StoredTeamBoard]]
    )
    stored_team_pairing_blocks: list[StoredTeamPairingBlock] = field(
        default_factory=list[StoredTeamPairingBlock]
    )
    stored_team_point_adjustments: list[StoredTeamPointAdjustment] = field(
        default_factory=list[StoredTeamPointAdjustment]
    )
    stored_player_point_adjustments: list[StoredPlayerPointAdjustment] = field(
        default_factory=list[StoredPlayerPointAdjustment]
    )
    stored_prohibited_pairing_groups: list['StoredProhibitedPairingGroup'] = field(
        default_factory=list['StoredProhibitedPairingGroup']
    )

    # Plugins can add their own tournament data
    plugin_data: dict[str, dict[str, Any]] = field(
        default_factory=dict[str, dict[str, Any]]
    )


@dataclass
class StoredScreenSet:
    id: int | None
    screen_id: int
    tournament_id: int
    name: str | None
    order: int | None
    fixed_boards_str: str | None
    first: int | None
    last: int | None
    fixed_board_order: str | None = None
    last_update: datetime = field(default_factory=datetime.now)
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredScreen:
    id: int | None
    uniq_id: str
    name: str | None
    type: str
    columns: int | None
    font_size: int | None
    menu_text: str | None
    timer_id: int | None
    input_exit_button: bool | None = None
    players_show_unpaired: bool | None = None
    players_player_format: int | None = None
    players_board_format: int | None = None
    players_opponent_format: int | None = None
    results_limit: int | None = None
    results_max_age: int | None = None
    background_image: str | None = None
    background_color: str | None = None
    results_tournament_ids: list[int] = field(default_factory=list[int])
    ranking_crosstable: bool = False
    ranking_round: int | None = None
    ranking_min_points: float | None = None
    ranking_max_points: float | None = None
    stored_screen_sets: list[StoredScreenSet] = field(
        default_factory=list[StoredScreenSet]
    )
    last_update: datetime = field(default_factory=datetime.now)
    public: bool = True
    message_default: bool = True
    message_text: str | None = None
    plugin_data: dict[str, dict[str, Any]] = field(
        default_factory=dict[str, dict[str, Any]]
    )
    errors: dict[str, str] = field(default_factory=dict[str, str])
    init_set_tournament_id: int | None = None


@dataclass
class StoredFamily:
    id: int | None
    uniq_id: str
    name: str | None
    type: str
    tournament_id: int
    columns: int | None
    font_size: int | None
    menu_text: str
    timer_id: int | None
    input_exit_button: bool | None = None
    players_show_unpaired: bool | None = None
    players_player_format: int | None = None
    players_board_format: int | None = None
    players_opponent_format: int | None = None
    ranking_crosstable: bool = False
    ranking_round: int | None = None
    ranking_min_points: float | None = None
    ranking_max_points: float | None = None
    first: int | None = None
    last: int | None = None
    parts: int | None = None
    number: int | None = None
    fixed_board_order: str | None = None
    public: bool = True
    message_default: bool = True
    message_text: str | None = None
    last_update: datetime = field(default_factory=datetime.now)
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredRotatingScreen:
    id: int | None
    rotator_id: int
    screen_id: int | None = None
    family_id: int | None = None
    index: int = 0


@dataclass
class StoredRotator:
    id: int | None
    name: str
    delay: int | None = None
    public: bool = True
    message_default: bool = True
    message_text: str | None = None
    timer_id: int | None = None
    stored_rotating_screens: list[StoredRotatingScreen] = field(
        default_factory=list[StoredRotatingScreen]
    )


@dataclass
class StoredMenuItem:
    id: int | None
    menu_id: int
    screen_id: int | None = None
    family_id: int | None = None
    screen_type: str | None = None
    index: int = 0


@dataclass
class StoredMenu:
    id: int | None
    name: str | None = None
    default_type: str | None = None
    submenu_mode: str = 'automatic'
    stored_menu_items: list[StoredMenuItem] = field(
        default_factory=list[StoredMenuItem]
    )


@dataclass
class StoredDisplayController:
    id: int | None
    name: str
    public: bool = True
    screen_id: int | None = None
    rotator_id: int | None = None
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredPermission:
    account_id: int
    access_level: str
    tournament_ids: list[int] | None = None


@dataclass
class StoredRole:
    account_id: int | None
    role: str
    tournament_ids: list[int] | None = None


@dataclass
class StoredAccount:
    id: int | None
    active: bool
    first_name: str | None
    last_name: str | None
    fide_id: int | None = None
    fide_arbiter_title: str = ''
    password_hash: str | None = None
    mail: str | None = None
    phone: str | None = None
    stored_permissions: list[StoredPermission] = field(
        default_factory=list[StoredPermission]
    )
    stored_roles: list[StoredRole] = field(default_factory=list[StoredRole])
    # Plugins can add their own account data
    plugin_data: dict[str, dict[str, Any]] = field(
        default_factory=dict[str, dict[str, Any]]
    )


@dataclass
class BaseStoredEvent:
    uniq_id: str
    name: str
    federation: str
    player_rating_type: int
    public: bool = False
    location: str | None = None
    background_color: str | None = None
    timer_colors: dict[int, str | None] = field(default_factory=dict[int, str | None])
    timer_delays: dict[int, int | None] = field(default_factory=dict[int, int | None])
    message_text: str | None = None
    message_color: str | None = None
    message_background_color: str | None = None
    prize_currency: str | None = None
    age_category_base_date: date | None = None
    age_category_change_month: int = 1
    age_categories: list[str] | None = None
    organiser_name: str | None = None
    organiser_home_page: str | None = None
    organiser_email: str | None = None
    organiser_director: str | None = None
    allow_multi_tournament_players: bool = True
    event_type: EventType = EventType.INDIVIDUAL

    # The ids of the tags of the event, as defined in the config database.
    # Ids are local to an installation: they are stripped on export/import
    # and ids that no longer resolve are ignored (see data.tag).
    tag_ids: list[int] = field(default_factory=list[int])

    # Plugins can add their own event data
    plugin_data: dict[str, dict[str, Any]] = field(
        default_factory=dict[str, dict[str, Any]]
    )
    enabled_plugins: list[str] = field(default_factory=list[str])


@dataclass
class StoredEvent(BaseStoredEvent):
    stored_players: list[StoredPlayer] = field(default_factory=list[StoredPlayer])
    stored_tournaments: list[StoredTournament] = field(
        default_factory=list[StoredTournament]
    )
    stored_teams: list[StoredTeam] = field(default_factory=list[StoredTeam])
    stored_team_groups: list[StoredTeamGroup] = field(
        default_factory=list[StoredTeamGroup]
    )
    stored_timers: list[StoredTimer] = field(default_factory=list[StoredTimer])
    stored_screens: list[StoredScreen] = field(default_factory=list[StoredScreen])
    stored_families: list[StoredFamily] = field(default_factory=list[StoredFamily])
    stored_rotators: list[StoredRotator] = field(default_factory=list[StoredRotator])
    stored_menus: list[StoredMenu] = field(default_factory=list[StoredMenu])
    stored_display_controllers: list[StoredDisplayController] = field(
        default_factory=list[StoredDisplayController]
    )
    stored_accounts: list[StoredAccount] = field(default_factory=list[StoredAccount])

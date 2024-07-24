from dataclasses import dataclass, field

from data.util import TournamentPairing, TournamentRating, ScreenType


@dataclass
class StoredTimerHour:
    id: int | None
    uniq__id: str
    timer_id: int
    order: int
    date_str: str | None
    text_before: str | None
    text_after: str | None


@dataclass
class StoredTimer:
    id: int | None
    uniq_id: str
    delay_1: int | None
    delay_2: int | None
    delay_3: int | None
    color_1: str | None
    color_2: str | None
    color_3: str | None
    stored_timer_hours: list[StoredTimerHour] = field(default_factory=list[StoredTimerHour])


@dataclass
class StoredChessEvent:
    id: int | None
    uniq_id: str
    user_id: str
    password: str
    event_id: str
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredTournament:
    id: int | None
    uniq_id: str
    name: str
    path: str | None
    filename: str | None
    ffe_id: int | None
    ffe_password: str | None
    handicap_initial_time: int | None
    handicap_increment: int | None
    handicap_penalty_step: int | None
    handicap_penalty_value: int | None
    handicap_min_time: int | None
    chessevent_id: int | None
    chessevent_tournament_name: str | None
    record_illegal_moves: int | None
    rounds: int
    pairing: str
    rating: str
    rating_limit_1: int | None
    rating_limit_2: int | None
    last_result_update: float
    last_illegal_move_update: float
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredScreenSet:
    id: int | None
    screen_id: int
    tournament_id: int
    order: int
    first: int | None
    last: int | None
    part: int | None
    parts: int | None
    number: int | None


@dataclass
class StoredScreen:
    id: int | None
    uniq_id: str
    name: str
    type: ScreenType
    boards_update: bool
    players_show_unpaired: bool
    columns: int
    menu_text: str | None
    menu: str | None
    timer_id: int | None
    results_limit: int | None
    results_tournaments_str: str | None
    stored_screen_sets: list[StoredScreenSet] = field(default_factory=list[StoredScreenSet])
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredFamily:
    id: int | None
    uniq_id: str
    name: str
    type: ScreenType
    boards_update: bool
    players_show_unpaired: bool
    columns: int
    menu_text: str | None
    menu: str | None
    timer_id: int | None
    results_limit: int | None
    results_tournaments_str: str | None
    range: str | None
    first: int | None
    last: int | None
    part: int | None
    parts: int | None
    number: int | None
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredRotator:
    id: int | None
    uniq_id: str
    families_str: str | None
    screens_str: str | None
    delay: int | None
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredEvent:
    uniq_id: str
    name: str
    path: str | None
    css: str | None
    update_password: str | None
    record_illegal_moves: int | None
    allow_results_deletion: bool | None
    stored_chessevents: list[StoredChessEvent] = field(default_factory=list[StoredChessEvent])
    stored_screens: list[StoredScreen] = field(default_factory=list[StoredScreen])
    stored_families: list[StoredFamily] = field(default_factory=list[StoredFamily])
    stored_rotators: list[StoredRotator] = field(default_factory=list[StoredRotator])
    version: str | None = field(default=None)
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredIllegalMove:
    id: int | None
    tournament_id: str
    round: int
    player_id: int
    date: float


@dataclass
class StoredResult:
    id: int | None
    tournament_id: str
    board_id: int
    result: int
    date: float
from dataclasses import dataclass, field

from data.util import TournamentPairing, TournamentRating, ScreenType


@dataclass
class StoredTimerHour:
    id: int | None
    timer_id: int
    order: int
    date: str
    round: int | None
    event: str | None
    text_before: str
    text_after: str


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


@dataclass
class StoredTournament:
    id: int | None
    uniq_id: str
    name: str | None = field(default=None)
    path: str | None = field(default=None)
    filename: str | None = field(default=None)
    ffe_id: int | None = field(default=None)
    ffe_password: str | None = field(default=None)
    handicap_initial_time: int | None = field(default=None)
    handicap_increment: int | None = field(default=None)
    handicap_penalty_step: int | None = field(default=None)
    handicap_penalty_value: int | None = field(default=None)
    handicap_min_time: int | None = field(default=None)
    chessevent_id: int | None = field(default=None)
    chessevent_tournament_name: str | None = field(default=None)
    record_illegal_moves: int | None = field(default=None)
    rounds: int | None = field(default=None)
    pairing: TournamentPairing | None = field(default=None)
    rating: TournamentRating | None = field(default=None)
    rating_limit_1: int | None = field(default=None)
    rating_limit_2: int | None = field(default=None)
    last_result_update: float | None = field(default=None)
    last_illegal_move_update: float | None = field(default=None)


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


@dataclass
class StoredFamily:
    id: int | None
    uniq_id: str
    name: str
    type: ScreenType
    boards_update: bool
    players_show_unpaired: bool | None
    columns: int | None
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


@dataclass
class StoredRotator:
    id: int | None
    uniq_id: str
    families_str: str | None
    screens_str: str | None
    delay: int | None


@dataclass
class StoredEvent:
    version: str
    name: str
    path: str | None = field(default=None)
    css: str | None = field(default=None)
    update_password: str | None = field(default=None)
    record_illegal_moves: int | None = field(default=None)
    allow_deletion: bool | None = field(default=None)
    stored_chessevents: list[StoredChessEvent] = field(default_factory=list[StoredChessEvent])
    stored_screens: list[StoredScreen] = field(default_factory=list[StoredScreen])
    stored_families: list[StoredFamily] = field(default_factory=list[StoredFamily])
    stored_rotators: list[StoredRotator] = field(default_factory=list[StoredRotator])


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

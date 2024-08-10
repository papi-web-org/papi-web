from dataclasses import dataclass, field


@dataclass
class StoredTimerHour:
    id: int | None
    uniq_id: str
    timer_id: int
    order: int | None = field(default=None)
    date_str: str | None = field(default=None)
    time_str: str | None = field(default=None)
    text_before: str | None = field(default=None)
    text_after: str | None = field(default=None)
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredTimer:
    id: int | None
    uniq_id: str
    colors: dict[int, str | None]
    delays: dict[int, int | None]
    stored_timer_hours: list[StoredTimerHour] = field(default_factory=list[StoredTimerHour])
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredChessEvent:
    id: int | None
    uniq_id: str
    user_id: str
    password: str
    event_id: str
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredSkippedRound:
    id: int | None
    tournament_id: int
    round: int
    papi_player_id: int
    score: float


@dataclass
class StoredTournament:
    id: int | None
    uniq_id: str
    name: str
    path: str | None
    filename: str | None
    ffe_id: int | None
    ffe_password: str | None
    time_control_initial_time: int | None
    time_control_increment: int | None
    time_control_handicap_penalty_step: int | None
    time_control_handicap_penalty_value: int | None
    time_control_handicap_min_time: int | None
    chessevent_id: int | None
    chessevent_tournament_name: str | None
    record_illegal_moves: int | None
    last_result_update: float = field(default=0.0)
    last_illegal_move_update: float = field(default=0.0)
    last_ffe_upload: float = field(default=0.0)
    last_chessevent_download: float = field(default=0.0)
    stored_skipped_rounds: list[StoredSkippedRound] = field(default_factory=list[StoredSkippedRound])
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredScreenSet:
    id: int | None
    screen_id: int
    tournament_id: int | None
    name: str | None
    order: int | None
    fixed_boards_str: str | None
    first: int | None
    last: int | None
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredScreen:
    id: int | None
    uniq_id: str
    name: str | None
    type: str
    columns: int | None
    menu_text: str | None
    menu: str | None
    timer_id: int | None
    boards_update: bool | None
    players_show_unpaired: bool | None
    results_limit: int | None | None
    results_tournament_ids: list[int] = field(default_factory=list[int])
    stored_screen_sets: list[StoredScreenSet] = field(default_factory=list[StoredScreenSet])
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredFamily:
    id: int | None
    uniq_id: str
    name: str | None
    type: str
    tournament_id: int
    columns: int | None
    menu_text: str | None
    menu: str | None
    timer_id: int | None
    boards_update: bool | None
    players_show_unpaired: bool | None
    first: int | None
    last: int | None
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
    stored_timers: list[StoredTimer] = field(default_factory=list[StoredTimer])
    stored_tournaments: list[StoredTournament] = field(default_factory=list[StoredTournament])
    stored_screens: list[StoredScreen] = field(default_factory=list[StoredScreen])
    stored_families: list[StoredFamily] = field(default_factory=list[StoredFamily])
    stored_rotators: list[StoredRotator] = field(default_factory=list[StoredRotator])
    version: str | None = field(default=None)
    timer_colors: dict[int, str | None] = field(default_factory=dict[int, str | None])
    timer_delays: dict[int, int | None] = field(default_factory=dict[int, int | None])
    errors: dict[str, str] = field(default_factory=dict[str, str])

    def __post_init__(self):
        pass


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
    tournament_id: int
    board_id: int
    result: int
    date: float

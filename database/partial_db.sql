BEGIN;

CREATE TABLE "info" (
    schema_version INTEGER NOT NULL,
);

CREATE TABLE "tournament" (
    id INTEGER NOT NULL,
    tournament_name TEXT NOT NULL,
    last_update INTEGER,
    PRIMARY KEY (id AUTOINCREMENT),
);

CREATE TABLE player (
    id INTEGER NOT NULL,
    tournament_id INTEGER NOT NULL,
    ffe_id INTEGER,
    last_name TEXT NOT NULL,
    first_name TEXT,
    rating INTEGER,
    PRIMARY KEY(id AUTOINCREMENT),
);

CREATE TABLE possible_results (
    id INTEGER NOT NULL,
    label TEXT,
)

INSERT INTO result(label) VALUES
    (""),
    (-),
    (+),
    (W),
    (D),
    (L),
    (1),
    (=),
    (0),
    (H),
    (F),
    (U),
    (Z);

CREATE TABLE pairing (
    id INTEGER NOT NULL,
    tournament_id INTEGER NOT NULL,
    board_id INTEGER NOT NULL,
    round_ INTEGER NOT NULL,
    white_id INTEGER NOT NULL,
    black_id INTEGER NOT NULL,
    white_result INTEGER NOT NULL,
    black_result INTEGER,
    board_number INTEGER,
    PRIMARY KEY(id AUTOINCREMENT),
    FOREIGN KEY(tournament_id) REFERENCES tournament(id),
    FOREIGN KEY(white_id) REFERENCES player(id),
    FOREIGN KEY(black_id) REFERENCES player(id),
    FOREIGN KEY(white_result) REFERENCES result(id),
    FOREIGN KEY(black_result) REFERENCES result(id)
);

CREATE TABLE illegal_move (
    id INTEGER NOT NULL,
    tournament_id INTEGER NOT NULL,
    round_ INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    PRIMARY KEY(id AUTOINCREMENT),
    FOREIGN KEY(tournament_id) REFERENCES tournament(id),
    FOREIGN KEY(player_id) REFERENCES player(id)
)

COMMIT;
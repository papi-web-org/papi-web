CREATE TABLE `info` (
    `version` TEXT NOT NULL,
    `finished` INTEGER NOT NULL
);

INSERT INTO `info`(`version`, `finished`) VALUES('{version}', 0);

CREATE TABLE `tournament` (
    `id` TEXT NOT NULL,
    `last_update` REAL NOT NULL,
    PRIMARY KEY(`id`)
);

CREATE TABLE `illegal_move` (
    `id` INTEGER NOT NULL,
    `tournament_id` TEXT NOT NULL,
    `round` INTEGER NOT NULL,
    `player_id` INTEGER NOT NULL,
    `date` REAL NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT)
);

CREATE TABLE `result` (
    `id` INTEGER NOT NULL,
    `tournament_id` TEXT NOT NULL,
    `round` INTEGER NOT NULL,
    `board_id` INTEGER NOT NULL,
    `white_player` TEXT NOT NULL,
    `black_player` TEXT NOT NULL,
    `date` REAL NOT NULL,
    `value` INTEGER NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT)
);

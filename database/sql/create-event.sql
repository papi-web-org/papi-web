/* These lines ease debug on https://sqliteonline.com/ */
DROP TABLE IF EXISTS `info`;
DROP TABLE IF EXISTS `tournament`;
DROP TABLE IF EXISTS `illegal_move`;
DROP TABLE IF EXISTS `result`;

CREATE TABLE `info` (
    `version` TEXT NOT NULL
);

INSERT INTO `info`(`version`) VALUES('{version}');

CREATE TABLE `tournament` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `last_illegal_move_update` FLOAT DEFAULT 0.0,
    `last_result_update` FLOAT DEFAULT 0.0,
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`)
);

CREATE TABLE `illegal_move` (
    `id` INTEGER NOT NULL,
    `tournament_id` INTEGER NOT NULL,
    `round` INTEGER NOT NULL,
    `player_id` INTEGER NOT NULL,
    `date` FLOAT NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT),
    FOREIGN KEY (`tournament_id`) REFERENCES `tournament`(`id`)
);

CREATE TABLE `result` (
    `id` INTEGER NOT NULL,
    `tournament_id` INTEGER NOT NULL,
    `round` INTEGER NOT NULL,
    `board_id` INTEGER NOT NULL,
    `white_player_id` INTEGER NOT NULL,
    `black_player_id` INTEGER NOT NULL,
    `date` REAL NOT NULL,
    `value` INTEGER NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT),
    FOREIGN KEY (`tournament_id`) REFERENCES `tournament`(`id`)
);

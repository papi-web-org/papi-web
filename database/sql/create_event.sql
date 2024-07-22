/* These lines ease debug on https://sqliteonline.com/ */
DROP TABLE IF EXISTS `info`;
DROP TABLE IF EXISTS `chessevent`;
DROP TABLE IF EXISTS `tournament`;
DROP TABLE IF EXISTS `illegal_move`;
DROP TABLE IF EXISTS `result`;

CREATE TABLE `info` (
    `version` TEXT NOT NULL,
    `name` TEXT NOT NULL DEFAULT 'Évènement',
    `path` TEXT NOT NULL DEFAULT '',
    `css` TEXT NOT NULL DEFAULT '',
    `update_password` TEXT NOT NULL DEFAULT '',
    `record_illegal_moves` INTEGER NOT NULL DEFAULT 0,
    `allow_deletion` INTEGER NOT NULL DEFAULT 0

);

INSERT INTO `info`(`version`) VALUES('{version}');

CREATE TABLE `chessevent` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `user_id` TEXT NOT NULL,
    `password` TEXT NOT NULL,
    `event_id` TEXT NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`)
);

CREATE TABLE `timer_hour` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `timer_id` INTEGER NOT NULL,
    `order` INTEGER NOT NULL,
    `date` FLOAT DEFAULT 0.0,
    `round` INTEGER NOT NULL DEFAULT -1,
    `event` TEXT NOT NULL DEFAULT '',
    `text_before` TEXT NOT NULL DEFAULT '',
    `text_after` TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`),
    FOREIGN KEY (`timer_id`) REFERENCES `timer`(`id`)
);

CREATE TABLE `timer` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `delay_1` INTEGER NOT NULL DEFAULT -1,
    `delay_2` INTEGER NOT NULL DEFAULT -1,
    `delay_3` INTEGER NOT NULL DEFAULT -1,
    `color_1` TEXT NOT NULL DEFAULT '',
    `color_2` TEXT NOT NULL DEFAULT '',
    `color_3` TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`)
);

CREATE TABLE `tournament` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `name` TEXT NOT NULL DEFAULT 'Tournoi',
    `path` TEXT NOT NULL DEFAULT '',
    `filename` TEXT NOT NULL DEFAULT '',
    `ffe_id` INTEGER NOT NULL DEFAULT -1,
    `ffe_password` TEXT NOT NULL DEFAULT '',
    `handicap_initial_time` INTEGER NOT NULL DEFAULT -1,
    `handicap_increment` INTEGER NOT NULL DEFAULT -1,
    `handicap_penalty_step` INTEGER NOT NULL DEFAULT -1,
    `handicap_penalty_value` INTEGER NOT NULL DEFAULT -1,
    `handicap_min_time` INTEGER NOT NULL DEFAULT -1,
    `chessevent_id` INTEGER,
    `chessevent_tournament_name` TEXT NOT NULL DEFAULT '',
    `record_illegal_moves` INTEGER NOT NULL DEFAULT 0,
    `rounds` INTEGER NOT NULL DEFAULT 1,
    `pairing` TEXT NOT NULL DEFAULT 'Standard',
    `rating` TEXT NOT NULL DEFAULT 'Elo',
    `rating_limit_1` INTEGER NOT NULL DEFAULT -1,
    `rating_limit_2` INTEGER NOT NULL DEFAULT -1,
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

CREATE TABLE `screen` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `name` TEXT NOT NULL DEFAULT 'Écran',
    `type` TEXT NOT NULL DEFAULT 'Boards',
    `boards_update` INTEGER NOT NULL NOT NULL DEFAULT 0,
    `players_show_unpaired` INTEGER NOT NULL NOT NULL DEFAULT 0,
    `columns` INTEGER NOT NULL DEFAULT 1,
    `menu_text` TEXT NOT NULL DEFAULT '',
    `menu` TEXT NOT NULL DEFAULT '',
    `timer_id` INTEGER NOT NULL DEFAULT -1,
    `results_limit` INTEGER NOT NULL DEFAULT 0,
    `results_tournaments_str` TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(`id` AUTOINCREMENT),
    FOREIGN KEY (`timer_id`) REFERENCES `timer`(`id`)
);

CREATE TABLE `screen_set` (
    `id` INTEGER NOT NULL,
    `screen_id` INTEGER NOT NULL,
    `tournament_id` INTEGER NOT NULL,
    `order` INTEGER NOT NULL,
    `first` INTEGER NOT NULL DEFAULT -1,
    `last` INTEGER NOT NULL DEFAULT -1,
    `part` INTEGER NOT NULL DEFAULT -1,
    `parts` INTEGER NOT NULL DEFAULT -1,
    `number` INTEGER NOT NULL DEFAULT -1,
    PRIMARY KEY(`id` AUTOINCREMENT),
    FOREIGN KEY (`screen_id`) REFERENCES `screen`(`id`),
    FOREIGN KEY (`tournament_id`) REFERENCES `tournament`(`id`)
);

CREATE TABLE `family` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `name` TEXT NOT NULL DEFAULT 'Famille',
    `type` TEXT NOT NULL DEFAULT 'Boards',
    `boards_update` INTEGER NOT NULL NOT NULL DEFAULT 0,
    `players_show_unpaired` INTEGER NOT NULL NOT NULL DEFAULT -1,
    `columns` INTEGER NOT NULL DEFAULT 1,
    `menu_text` TEXT NOT NULL DEFAULT '',
    `menu` TEXT NOT NULL DEFAULT '',
    `timer_id` INTEGER,
    `results_limit` INTEGER NOT NULL DEFAULT -1,
    `results_tournaments_str` TEXT NOT NULL DEFAULT '',
    `tournament_id` INTEGER NOT NULL,
    `range` TEXT NOT NULL DEFAULT '',
    `first` INTEGER NOT NULL DEFAULT -1,
    `last` INTEGER NOT NULL DEFAULT -1,
    `part` INTEGER NOT NULL DEFAULT -1,
    `parts` INTEGER NOT NULL DEFAULT -1,
    `number` INTEGER NOT NULL DEFAULT -1,
    PRIMARY KEY(`id` AUTOINCREMENT),
    FOREIGN KEY (`timer_id`) REFERENCES `timer`(`id`),
    FOREIGN KEY (`tournament_id`) REFERENCES `tournament`(`id`)
);

CREATE TABLE `rotator` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `screens_str` TEXT NOT NULL DEFAULT '',
    `families_str` TEXT NOT NULL DEFAULT '',
    `delay` INTEGER NOT NULL DEFAULT -1,
    PRIMARY KEY(`id` AUTOINCREMENT)
);


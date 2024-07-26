/* These lines ease debug on https://sqliteonline.com/ */
DROP TABLE IF EXISTS `info`;
DROP TABLE IF EXISTS `chessevent`;
DROP TABLE IF EXISTS `tournament`;
DROP TABLE IF EXISTS `illegal_move`;
DROP TABLE IF EXISTS `result`;

CREATE TABLE `info` (
    `version` TEXT NOT NULL,
    `name` TEXT NOT NULL DEFAULT 'Évènement',
    `path` TEXT,
    `css` TEXT,
    `update_password` TEXT,
    `record_illegal_moves` INTEGER,
    `allow_results_deletion` INTEGER

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
    `date_str` TEXT,
    `text_before` TEXT,
    `text_after` TEXT,
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`),
    FOREIGN KEY (`timer_id`) REFERENCES `timer`(`id`) ON DELETE CASCADE
);

CREATE TABLE `timer` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `delay_1` INTEGER,
    `delay_2` INTEGER,
    `delay_3` INTEGER,
    `color_1` TEXT,
    `color_2` TEXT,
    `color_3` TEXT,
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`)
);

CREATE TABLE `tournament` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `name` TEXT NOT NULL DEFAULT 'Tournoi',
    `path` TEXT,
    `filename` TEXT,
    `ffe_id` INTEGER,
    `ffe_password` TEXT,
    `time_control_initial_time` INTEGER,
    `time_control_increment` INTEGER,
    `time_control_handicap_penalty_step` INTEGER,
    `time_control_handicap_penalty_value` INTEGER,
    `time_control_handicap_min_time` INTEGER,
    `chessevent_id` INTEGER,
    `chessevent_tournament_name` TEXT,
    `record_illegal_moves` INTEGER,
    `last_illegal_move_update` FLOAT NOT NULL DEFAULT 0.0,
    `last_result_update` FLOAT NOT NULL DEFAULT 0.0,
    `last_ffe_upload` FLOAT NOT NULL DEFAULT 0.0,
    `last_chessevent_download` FLOAT NOT NULL DEFAULT 0.0,
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`),
    FOREIGN KEY (`chessevent_id`) REFERENCES `chessevent`(`id`)
);

CREATE TABLE `illegal_move` (
    `id` INTEGER NOT NULL,
    `tournament_id` INTEGER NOT NULL,
    `round` INTEGER NOT NULL,
    `player_id` INTEGER NOT NULL,
    `date` FLOAT NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT),
    FOREIGN KEY (`tournament_id`) REFERENCES `tournament`(`id`) ON DELETE CASCADE
);

CREATE TABLE `result` (
    `id` INTEGER NOT NULL,
    `tournament_id` INTEGER NOT NULL,
    `round` INTEGER NOT NULL,
    `board_id` INTEGER NOT NULL,
    `white_player_id` INTEGER NOT NULL,
    `black_player_id` INTEGER NOT NULL,
    `date` FLOAT NOT NULL,
    `value` INTEGER NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT),
    FOREIGN KEY (`tournament_id`) REFERENCES `tournament`(`id`) ON DELETE CASCADE
);

CREATE TABLE `screen` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `name` TEXT NOT NULL DEFAULT 'Écran',
    `type` TEXT NOT NULL DEFAULT 'Boards',
    `boards_update` INTEGER NOT NULL,
    `players_show_unpaired` INTEGER NOT NULL,
    `columns` INTEGER NOT NULL,
    `menu_text` TEXT,
    `menu` TEXT,
    `timer_id` INTEGER,
    `results_limit` INTEGER,
    `results_tournaments_str` TEXT,
    PRIMARY KEY(`id` AUTOINCREMENT),
    FOREIGN KEY (`timer_id`) REFERENCES `timer`(`id`)
);

CREATE TABLE `screen_set` (
    `id` INTEGER NOT NULL,
    `screen_id` INTEGER NOT NULL,
    `tournament_id` INTEGER NOT NULL,
    `order` INTEGER NOT NULL,
    `first` INTEGER,
    `last` INTEGER,
    `part` INTEGER,
    `parts` INTEGER,
    `number` INTEGER,
    PRIMARY KEY(`id` AUTOINCREMENT),
    FOREIGN KEY (`screen_id`) REFERENCES `screen`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`tournament_id`) REFERENCES `tournament`(`id`)
);

CREATE TABLE `family` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `name` TEXT NOT NULL DEFAULT 'Famille',
    `type` TEXT NOT NULL DEFAULT 'Boards',
    `boards_update` INTEGER NOT NULL,
    `players_show_unpaired` INTEGER NOT NULL,
    `columns` INTEGER NOT NULL,
    `menu_text` TEXT,
    `menu` TEXT,
    `timer_id` INTEGER,
    `results_limit` INTEGER,
    `results_tournaments_str` TEXT,
    `tournament_id` INTEGER,
    `range` TEXT,
    `first` INTEGER,
    `last` INTEGER,
    `part` INTEGER,
    `parts` INTEGER,
    `number` INTEGER,
    PRIMARY KEY(`id` AUTOINCREMENT),
    FOREIGN KEY (`timer_id`) REFERENCES `timer`(`id`),
    FOREIGN KEY (`tournament_id`) REFERENCES `tournament`(`id`)
);

CREATE TABLE `rotator` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `screens_str` TEXT,
    `families_str` TEXT,
    `delay` INTEGER,
    PRIMARY KEY(`id` AUTOINCREMENT)
);

CREATE TABLE `skipped_round` (
    `id` INTEGER NOT NULL,
    `tournament_id` INTEGER NOT NULL,
    `round` INTEGER NOT NULL,
    `papi_player_id` INTEGER NOT NULL,
    `score` FLOAT NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT),
    FOREIGN KEY (`tournament_id`) REFERENCES `tournament`(`id`) ON DELETE CASCADE
);

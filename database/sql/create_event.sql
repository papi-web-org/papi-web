/* These lines ease debug on https://sqliteonline.com/ */
DROP TABLE IF EXISTS `info`;
DROP TABLE IF EXISTS `chessevent`;
DROP TABLE IF EXISTS `timer_hour`;
DROP TABLE IF EXISTS `timer`;
DROP TABLE IF EXISTS `tournament`;
DROP TABLE IF EXISTS `illegal_move`;
DROP TABLE IF EXISTS `result`;
DROP TABLE IF EXISTS `screen`;
DROP TABLE IF EXISTS `screen_set`;
DROP TABLE IF EXISTS `family`;
DROP TABLE IF EXISTS `rotator`;
DROP TABLE IF EXISTS `skipped_round`;

CREATE TABLE `info` (
    `version` TEXT NOT NULL,
    `name` TEXT NOT NULL DEFAULT '?',
    `start` FLOAT NOT NULL,
    `stop` FLOAT NOT NULL,
    `public` INTEGER,
    `path` TEXT,
    `background_image` TEXT,
    `background_color` TEXT,
    `update_password` TEXT,
    `record_illegal_moves` INTEGER,
    `allow_results_deletion_on_input_screens` INTEGER,
    `timer_colors` TEXT,
    `timer_delays` TEXT,
    `last_update` FLOAT NOT NULL
);

INSERT INTO `info`(
    `version`, `name`, `start`, `stop`, `last_update`
) VALUES(
    '{version}', '{name}', '{start}', '{stop}', '{now}'
);

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
    `time_str` TEXT,
    `text_before` TEXT,
    `text_after` TEXT,
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`timer_id`, `uniq_id`),
    FOREIGN KEY (`timer_id`) REFERENCES `timer`(`id`) ON DELETE CASCADE
);

CREATE TABLE `timer` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `colors` TEXT,
    `delays` TEXT,
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`)
);

CREATE TABLE `tournament` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `name` TEXT NOT NULL,
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
    `last_update` FLOAT NOT NULL,
    `last_illegal_move_update` FLOAT NOT NULL DEFAULT 0.0,
    `last_result_update` FLOAT NOT NULL DEFAULT 0.0,
    `last_check_in_update` FLOAT NOT NULL DEFAULT 0.0,
    `last_ffe_upload` FLOAT NOT NULL DEFAULT 0.0,
    `last_chessevent_download_md5` TEXT,
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
    `name` TEXT,
    `type` TEXT NOT NULL,
    `public` INTEGER,
    `columns` INTEGER,
    `menu_link` INTEGER,
    `menu_text` TEXT,
    `menu` TEXT,
    `timer_id` INTEGER,
    `players_show_unpaired` INTEGER,
    `results_limit` INTEGER,
    `results_tournament_ids` TEXT,
    `background_image` TEXT,
    `background_color` TEXT,
    `last_update` FLOAT NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`),
    FOREIGN KEY (`timer_id`) REFERENCES `timer`(`id`)
);

CREATE TABLE `screen_set` (
    `id` INTEGER NOT NULL,
    `screen_id` INTEGER NOT NULL,
    `tournament_id` INTEGER NOT NULL,
    `name` TEXT,
    `order` INTEGER NOT NULL,
    `first` INTEGER,
    `last` INTEGER,
    `fixed_boards_str` TEXT,
    `last_update` FLOAT NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT),
    FOREIGN KEY (`screen_id`) REFERENCES `screen`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`tournament_id`) REFERENCES `tournament`(`id`) ON DELETE CASCADE
);

CREATE TABLE `family` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `type` TEXT NOT NULL,
    `public` INTEGER,
    `name` TEXT,
    `players_show_unpaired` INTEGER,
    `columns` INTEGER,
    `menu_link` INTEGER NOT NULL,
    `menu_text` TEXT NOT NULL,
    `menu` TEXT NOT NULL,
    `timer_id` INTEGER,
    `tournament_id` INTEGER NOT NULL,
    `range` TEXT,
    `first` INTEGER,
    `last` INTEGER,
    `parts` INTEGER,
    `number` INTEGER,
    `last_update` FLOAT NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`),
    FOREIGN KEY (`timer_id`) REFERENCES `timer`(`id`),
    FOREIGN KEY (`tournament_id`) REFERENCES `tournament`(`id`) ON DELETE CASCADE
);

CREATE TABLE `rotator` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `public` INTEGER,
    `screen_ids` TEXT,
    `family_ids` TEXT,
    `delay` INTEGER,
    `show_menus` INTEGER,
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`)
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

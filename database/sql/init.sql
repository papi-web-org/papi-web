CREATE TABLE `info` (
    `version` TEXT NOT NULL,
    `ini_read` FLOAT NOT NULL DEFAULT 0,
    `path` TEXT DEFAULT NULL,
    `css` TEXT DEFAULT NULL,
    `record_illegal_moves` INTEGER DEFAULT 0,
    `finished` INTEGER NOT NULL DEFAULT 0 /* COLLATE BINARY IN (0, 1) */
);

INSERT INTO `info`(`version`) VALUES('{version}');

CREATE TABLE `tournament` (
    `id` TEXT NOT NULL,
    `last_update` FLOAT NOT NULL,
    PRIMARY KEY(`id`)
);

CREATE TABLE `illegal_move` (
    `id` INTEGER NOT NULL,
    `tournament_id` TEXT NOT NULL,
    `round` INTEGER NOT NULL,
    `player_id` INTEGER NOT NULL,
    `date` FLOAT NOT NULL,
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

/*
CREATE TABLE `chessevent_connection` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `user_id` TEXT NOT NULL,
    `password` TEXT NOT NULL,
    `event_id` TEXT NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`)
);
*/

/*
CREATE TABLE `pairing_engine` (
    id INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    PRIMARY KEY("id" AUTOINCREMENT),
    UNIQUE(`uniq_id`)
);
*/

/*
CREATE TABLE `timer` (
    id INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `color_1` TEXT DEFAULT NULL,
    `color_2` TEXT DEFAULT NULL,
    `color_3` TEXT DEFAULT NULL,
    `delay_1` INTEGER DEFAULT NULL,
    `delay_2` INTEGER DEFAULT NULL,
    `delay_3` INTEGER DEFAULT NULL,
    PRIMARY KEY("id" AUTOINCREMENT),
    UNIQUE(`uniq_id`)
);
*/

/*
CREATE TABLE `timer_hour` (
    id INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `timer_id` INTEGER NOT NULL,
    `date` FLOAT NOT NULL,
    `text_before` TEXT DEFAULT NULL,
    `text_after` TEXT DEFAULT NULL,
    PRIMARY KEY("id" AUTOINCREMENT),
    UNIQUE(`uniq_id`),
    FOREIGN KEY (timer_id) REFERENCES timer(id),
);
*/

/*
CREATE TABLE `tournament` (
    `id` TEXT NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `name` TEXT NOT NULL,
    `path` TEXT DEFAULT NULL,
    `filename` TEXT DEFAULT NULL,
    `ffe_id` INTEGER DEFAULT NULL,
    `ffe_password` TEXT DEFAULT NULL,
    `chessevent_connection_id` TEXT DEFAULT NULL,
    `chessevent_tournament_name` TEXT DEFAULT NULL,
    `record_illegal_moves` INTEGER DEFAULT NULL,
    `last_update` FLOAT NOT NULL DEFAULT (julianday('now') - 2440587.5) * 86400.0,
    `pairing_engine_id` INTEGER DEFAULT NULL,
    `handicap_initial_time` INTEGER DEFAULT NULL,
    `handicap_increment` INTEGER DEFAULT NULL,
    `handicap_penalty_step` INTEGER DEFAULT NULL,
    `handicap_penalty_value` INTEGER DEFAULT NULL,
    `handicap_min_time` INTEGER DEFAULT NULL,
    PRIMARY KEY(`id`),
    UNIQUE(`uniq_id`),
    FOREIGN KEY (chessevent_connection_id) REFERENCES chessevent_connection(id),
);
*/

/*
CREATE TABLE `screen_template` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `type` TEXT NOT NULL CHECK (`type` in ('boards', 'players', 'results')),
    `name` TEXT DEFAULT NULL,
    `update` INTEGER NOT NULL DEFAULT 0 COLLATE BINARY IN (0, 1),
    `show_unpaired` INTEGER NOT NULL DEFAULT 0 COLLATE BINARY IN (0, 1),
    `menu` TEXT NOT NULL DEFAULT 'none',
    `menu_text` TEXT DEFAULT NULL,
    `timer_id` INTEGER DEFAULT NULL,
    `limit` INTEGER DEFAULT NULL,
    `columns` INTEGER NOT NULL DEFAULT 1,
    `value` INTEGER NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`),
    FOREIGN KEY (timer_id) REFERENCES timer(id)
);
*/

/*
CREATE TABLE `screen` (
    `id` INTEGER NOT NULL,
    `uniq_id` TEXT NOT NULL,
    `type` TEXT NOT NULL CHECK (`type` in ('boards', 'players', 'results')),
    `name` TEXT DEFAULT NULL,
    `update` INTEGER NOT NULL DEFAULT 0 COLLATE BINARY IN (0, 1),
    `show_unpaired` INTEGER NOT NULL DEFAULT 0 COLLATE BINARY IN (0, 1),
    `menu` TEXT NOT NULL DEFAULT 'none',
    `menu_text` TEXT DEFAULT NULL,
    `timer_id` INTEGER DEFAULT NULL,
    `limit` INTEGER DEFAULT NULL,
    `columns` INTEGER NOT NULL DEFAULT 1,
    `value` INTEGER NOT NULL,
    PRIMARY KEY(`id` AUTOINCREMENT),
    UNIQUE(`uniq_id`),
    FOREIGN KEY (timer_id) REFERENCES timer(id)
);
*/

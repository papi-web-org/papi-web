BEGIN;

CREATE TABLE "info" (
    version INTEGER NOT NULL,
    admin_password TEXT
);

CREATE TABLE "event" (
    id INTEGER NOT NULL,
    name TEXT NOT NULL,
    update_password TEXT,
    edit_passord TEXT,
    timer_enabled INTEGER NOT NULL DEFAULT 0 COLLATE BINARY IN (0, 1),
    timer_text_before_round TEXT
    timer_text_after_round TEXT,
    ffe_upload_enabled INTEGER NOT NULL DEFAULT 0 COLLATE BINARY IN (0, 1),
    chessevent_update_enabled INTEGER NOT NULL DEFAULT 0 COLLATE BINARY IN (0, 1),
    css_path TEXT,
    PRIMARY KEY("id" AUTOINCREMENT)
);

CREATE TABLE "chessevent_connection" (
    id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    ce_user_id TEXT,
    ce_password TEXT,
    ce_event_id TEXT,
    PRIMARY KEY("id" AUTOINCREMENT),
    FOREIGN KEY("event_id") REFERENCES "event"("id"),
);

CREATE TABLE "start_color" (
    id INTEGER NOT NULL,
    label TEXT NOT NULL,
    PRIMARY KEY("id" AUTOINCREMENT)
);
INSERT INTO start_color("label") VALUES (R);
INSERT INTO start_color("label") VALUES (W);
INSERT INTO start_color("label") VALUES (B);

CREATE TABLE "pairing_engine" (
    id INTEGER NOT NULL,
    label TEXT,
    PRIMARY KEY("id" AUTOINCREMENT)
);

CREATE TABLE "rating_type" (
    id INTEGER NOT NULL
    label TEXT,
    PRIMARY KEY("id" AUTOINCREMENT)
);
INSERT INTO "rating_type"("label") VALUES (std);
INSERT INTO "rating_type"("label") VALUES (rapid);
INSERT INTO "rating_type"("label") VALUES (blitz); 

CREATE TABLE "tie_break" (
    id INTEGER NOT NULL,
    label TEXT NOT NULL,
    modifier TEXT,
    PRIMARY KEY ("id")
);

CREATE TABLE "tournament" (
    id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    time_control_initial_time INTEGER,
    time_control_increment INTEGER,
    handicap_penalty_step INTEGER,
    handicap_penalty_value INTEGER,
    handicap_min_time INTEGER,
    rounds INTEGER NOT NULL DEFAULT 1,
    top_seed_start_color_id INTEGER NOT NULL,
    maximum_player_byes INTEGER NOT NULL DEFAULT 0,
    last_rounds_no_player_byes INTEGER NOT NULL DEFAULT 0,
    pairing_engine_id INTEGER NOT NULL,
    acceleration_ceil_1 INTEGER,
    acceleration_ceil_2 INTEGER,
    rating_used INTEGER NOT NULL,
    parings_published INTEGER NOT NULL DEFAULT 0 COLLATE BINARY IN (0, 1),
    chief_arbiter_fin INTEGER NOT NULL,
    arbiters TEXT,
    start_date INTEGER,
    end_date INTEGER,
    tie_break_1_id INTEGER NOT NULL,
    tie_break_2_id INTEGER,
    tie_break_3_id INTEGER,
    tie_break_4_id INTEGER,
    ffe_id TEXT,
    ffe_password TEXT,
    ffe_upload_enabled INTEGER NOT NULL DEFAULT 0 COLLATE BINARY IN (0, 1),
    current_round INTEGER NOT NULL,
    chessevent_connection_id INTEGER,
    chessevent_tournament_name TEXT,
    chessevent_update_enabled INTEGER COLLATE BINARY IN (0, 1),
    last_then_first_name INTEGER NOT NULL DEFAULT 1 COLLATE BINARY IN (0, 1),
    last_update INTEGER,
    PRIMARY KEY (id AUTOINCREMENT),
    FOREIGN KEY (event_id) REFERECES event(id),
    FOREIGN KEY (top_seed_color_id) REFERENCES start_color(id),
    FOREIGN KEY (paring_engine_id) REFERENCES pairing_engine(id),
    FOREIGN KEY (rating_used) REFERENCES rating_type(id),
    FOREIGN KEY (tie_break_1_id) REFERENCES tie_break(id),
    FOREIGN KEY (tie_break_2_id) REFERENCES tie_break(id),
    FOREIGN KEY (tie_break_3_id) REFERENCES tie_break(id),
    FOREIGN KEY (tie_break_4_id) REFERENCES tie_break(id),
    FOREIGN KEY (chessevent_connection_id) REFERENCES chessevent_connection(id),
);

CREATE TABLE player_ffe_status (
    id INTEGER NOT NULL,
    label TEXT,
    PRIMARY KEY(id AUTOINCREMENT),
);
INSERT INTO player_ffe_status(label) VALUES (X);
INSERT INTO player_ffe_status(label) VALUES (N);
INSERT INTO player_ffe_status(label) VALUES (B);
INSERT INTO player_ffe_status(label) VALUES (A);
CREATE TABLE player_title (
    id INTEGER NOT NULL,
    label TEXT,
    PRIMARY KEY(id AUTOINCREMENT),
);

INSERT INTO player_title(label) VALUES (N);
INSERT INTO player_title(label) VALUES (WCM);
INSERT INTO player_title(label) VALUES (WFM);
INSERT INTO player_title(label) VALUES (CM);
INSERT INTO player_title(label) VALUES (WIM);
INSERT INTO player_title(label) VALUES (FM);
INSERT INTO player_title(label) VALUES (WGM);
INSERT INTO player_title(label) VALUES (IM);
INSERT INTO player_title(label) VALUES (GM);

CREATE TABLE player_gender (
    id INTEGER NOT NULL,
    label TEXT,
    PRIMARY KEY(id AUTOINCREMENT),
);
INSERT INTO player_gender(label) VALUES (F);
INSERT INTO player_gender(label) VALUES (M);

CREATE TABLE player_category (
    id INTEGER NOT NULL,
    label TEXT,
    min_age INTEGER,
    max_age INTEGER
);
INSERT INTO player_category(label, max_age) VALUES (u8, 7);
INSERT INTO player_category(label, min_age, max_age) VALUES (u10, 8, 9);
INSERT INTO player_category(label, min_age, max_age) VALUES (u12, 10, 11);
INSERT INTO player_category(label, min_age, max_age) VALUES (u14, 12, 13);
INSERT INTO player_category(label, min_age, max_age) VALUES (u16, 14, 15);
INSERT INTO player_category(label, min_age, max_age) VALUES (u18, 16, 17);
INSERT INTO player_category(label, min_age, max_age) VALUES (u20, 18, 19);
INSERT INTO player_category(label, min_age, max_age) VALUES (adult, 20, 49);
INSERT INTO player_category(label, min_age, max_age) VALUES (o50, 50, 64);
INSERT INTO player_category(label, min_age) VALUES (o65, 65);

CREATE TABLE player_rating_level (
    id INTEGER NOT NULL,
    label TEXT,
    PRIMARY KEY(id AUTOINCREMENT)
)
INSERT INTO player_rating_level(label) VALUES (E);
INSERT INTO player_rating_level(label) VALUES (N);
INSERT INTO player_rating_level(label) VALUES (F);

CREATE TABLE player_status (
    id INTEGER NOT NULL,
    label TEXT,
    PRIMARY KEY(id AUTOINCREMENT)
);
INSERT INTO player_status(label) VALUES (P);
INSERT INTO player_status(label) VALUES (W);
COMMIT;
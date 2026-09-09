# _Sharly Chess_ - Description of the databases

## _Sharly Chess_ configuration database (`events/.scc`)

### `info` table (general application configuration)

> [!NOTE]
> :information_source: Table `info` contains only one line.

| Field                   | Type      | Constraint                 | Description                                                                                                                  |
|-------------------------|-----------|----------------------------|------------------------------------------------------------------------------------------------------------------------------|
| `force_edit`            | `INTEGER` | NOT NULL                   | Boolean:<br/>- `1`: Editing the configuration is mandatory;<br/>- `0`: Editing the configuration is possible but optional    |
| `console_log_level`     | `INTEGER` |                            | The console logging level                                                                                                    |
| `console_color`         | `INTEGER` |                            | Boolean:<br/>- `1`: Use colors on the console (default);<br/>- `0`: Do not use colors on the console                         |
| `console_show_date`     | `INTEGER` |                            | Boolean:<br/>- `1`: Show the date and time on the console;<br/>- `0`: Do not show the date and time on the console (default) |
| `console_show_level`    | `INTEGER` |                            | Boolean:<br/>- `1`: Show the logging level on the console;<br/>- `0`: Do not show the logging level on the console (default) |
| `launch_browser`        | `INTEGER` |                            | Boolean:<br/>- `1`: A browser is automatically opened (default);<br/>- `0`: No browser is opened                             |
| `federation`            | `TEXT`    |                            | The default federation code for events                                                                                       |
| `locale`                | `TEXT`    |                            | The default language used for users                                                                                          |
| `experimental`          | `INTEGER` |                            | Boolean:<br/>- `1`: Experimental features are enabled;<br/>- `0`: Experimental features are disabled (default)               |
| `date_formatter`        | `TEXT`    | NOT NULL<br/>DEFAULT 'ISO' | The format used to display dates (`ISO`, `EU`, `US`)                                                                         |
| `check_beta_versions`   | `INTEGER` | NOT NULL<br/>DEFAULT 0     | Boolean:<br/>- `1`: Beta releases are considered when looking for updates;<br/>- `0`: Only final releases are (default)      |
| `last_notified_version` | `TEXT`    |                            | The last version the user was notified about, so the notice is shown once                                                    |

### `local_source_database` table (local player databases)

| Field            | Type    | Constraint               | Description                                                                          |
|------------------|---------|--------------------------|--------------------------------------------------------------------------------------|
| `name`           | `TEXT`  | NOT NULL<br/>PRIMARY KEY | The database name                                                                    |
| `outdate_delay`  | `TEXT`  | NOT NULL                 | The auto-update delay (`disabled`, `daily`, `2days`, `3days`, `weekly`, `month_1st`) |
| `outdate_action` | `TEXT`  | NOT NULL                 | The action to take when the database needs to be updated (`notif`, `auto_update`)    |
| `updated_at`     | `FLOAT` |                          | The last update date for the database                                                |

### `metadata` table (application metadata)

| Field       | Type   | Constraint                               | Description              |
|-------------|--------|------------------------------------------|--------------------------|
| `version`   | `TEXT` | NOT NULL                                 | The application version  |
| `migration` | `TEXT` | NOT NULL<br/>DEFAULT 'm000_no_migration' | The last database update |

### `player_category_set` table (reusable player category sets)

| Field        | Type      | Constraint                                 | Description                                       |
|--------------|-----------|--------------------------------------------|---------------------------------------------------|
| `id`         | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The category set's ID                             |
| `name`       | `TEXT`    | NOT NULL                                   | The name of the category set                      |
| `categories` | `TEXT`    | NOT NULL                                   | The age categories making up the set, JSON format |

### `plugin` table (extensions)

| Field         | Type      | Constraint                | Description                                                                           |
|---------------|-----------|---------------------------|---------------------------------------------------------------------------------------|
| `name`        | `TEXT`    | NOT NULL<br/>PRIMARY KEY  | The name of the extension                                                             |
| `is_enabled`  | `INTEGER` | NOT NULL                  | Boolean:<br/>- `1`: The extension is enabled;<br/>- `0`: The extension is not enabled |
| `plugin_data` | `TEXT`    | NOT NULL<br/>DEFAULT '{}' | Additional data used by the extension, in JSON format                                 |

### `tag` table (tags)

| Field   | Type      | Constraint                                 | Description                |
|---------|-----------|--------------------------------------------|----------------------------|
| `id`    | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The tag's ID               |
| `name`  | `TEXT`    | NOT NULL<br/>UNIQUE                        | The name of the tag        |
| `color` | `TEXT`    | NOT NULL                                   | The color used for the tag |
| `index` | `INTEGER` | NOT NULL DEFAULT 0                         | The index of the tags      |

### `tie_break_set` table (reusable tie-break sets)

| Field               | Type      | Constraint                                 | Description                                                 |
|---------------------|-----------|--------------------------------------------|-------------------------------------------------------------|
| `id`                | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The tie-break set's ID                                      |
| `name`              | `TEXT`    | NOT NULL                                   | The name of the tie-break set                               |
| `pairing_system_id` | `TEXT`    | NOT NULL                                   | The pairing system the set applies to                       |
| `stored_tie_breaks` | `TEXT`    | NOT NULL                                   | The tie-breaks of the set and their options, in JSON format |
|                     |           | UNIQUE(`pairing_system_id`, `name`)        |                                                             |

## Event Database (`events/*.sce`)

``sce`` stands for **S**harly **C**hess **E**vent.

### `account` table (accounts)

| Field                | Type      | Constraint                                 | Description                                                                            |
|----------------------|-----------|--------------------------------------------|----------------------------------------------------------------------------------------|
| `id`                 | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The account ID<br/>- `1`: administrator<br/>- `2`: anonymous<br/>- `3+`: user accounts |
| `active`             | `INTEGER` | NOT NULL<br/>DEFAULT 1                     | Boolean:<br/>- `1`: the account can sign in;<br/>- `0`: the account is disabled        |
| `last_name`          | `TEXT`    |                                            | The person's last name (`NULL` for administrator and anonymous accounts)               |
| `first_name`         | `TEXT`    |                                            | The person's first name                                                                |
| `password_hash`      | `TEXT`    |                                            | A hash of the password                                                                 |
| `fide_id`            | `INTEGER` |                                            | The person's _FIDE_ ID                                                                 |
| `mail`               | `TEXT`    |                                            | The person's email address                                                             |
| `phone`              | `TEXT`    |                                            | The person's phone number                                                              |
| `fide_arbiter_title` | `TEXT`    |                                            | The person's _FIDE_ arbiter title (`'IA'`, `'FA'`, `'NA'`, `NULL`)                     |
| `plugin_data`        | `TEXT`    | NOT NULL<br/>DEFAULT '{}'                  | Additional data used by plugins, in JSON format                                        |

### `account_permission` table (account access levels)

> [!NOTE]
> :information_source: A permission is granted either for the whole event (`tournament_id` is `NULL`) or for one tournament.

| Field           | Type      | Constraint                                                | Description                                             |
|-----------------|-----------|-----------------------------------------------------------|---------------------------------------------------------|
| `account_id`    | `INTEGER` | NOT NULL<br/>REFERENCES `account`(`id`) ON DELETE CASCADE | The account the permission is granted to                |
| `access_level`  | `TEXT`    | NOT NULL                                                  | The granted access level                                |
| `tournament_id` | `INTEGER` | REFERENCES `tournament`(`id`) ON DELETE CASCADE           | The tournament it applies to (`NULL` = the whole event) |
|                 |           | UNIQUE(`account_id`, `access_level`, `tournament_id`)     |                                                         |

### `account_role` table (account roles)

> [!NOTE]
> :information_source: A role is held either for the whole event (`tournament_id` is `NULL`) or for one tournament. Unique indexes enforce that a tournament has at most one chief arbiter, and that an account holds at most one of the arbiter roles (`chief_arbiter`, `deputy_arbiter`, `arbiter`) per tournament.

| Field           | Type      | Constraint                                                | Description                                        |
|-----------------|-----------|-----------------------------------------------------------|----------------------------------------------------|
| `account_id`    | `INTEGER` | NOT NULL<br/>REFERENCES `account`(`id`) ON DELETE CASCADE | The account holding the role                       |
| `tournament_id` | `INTEGER` | REFERENCES `tournament`(`id`) ON DELETE CASCADE           | The tournament it is held for (`NULL` = the event) |
| `role`          | `TEXT`    | NOT NULL                                                  | The role held                                      |
|                 |           | UNIQUE(`account_id`, `role`, `tournament_id`)             |                                                    |

### `board` table (chess boards)

| Field                | Type      | Constraint                                       | Description                                                   |
|----------------------|-----------|--------------------------------------------------|---------------------------------------------------------------|
| `id`                 | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT       | The board ID                                                  |
| `white_player_id`    | `INTEGER` | REFERENCES `player`(`id`) ON DELETE CASCADE      | The white player ID (can be NULL for byes / team-match holes) |
| `black_player_id`    | `INTEGER` | REFERENCES `player`(`id`) ON DELETE CASCADE      | The black player ID (can be NULL for byes)                    |
| `index`              | `INTEGER` | NOT NULL                                         | The board number/index                                        |
| `last_result_update` | `FLOAT`   |                                                  | Timestamp of the last result update for board                 |
| `team_board_id`      | `INTEGER` | REFERENCES `team_board`(`id`) ON DELETE SET NULL | Parent team match (team tournaments only)                     |
| `fixed_number`       | `INTEGER` |                                                  | The board's fixed number, or `NULL`                           |

### `display_controller` table (display controllers)

| Field         | Type      | Constraint                                    | Description                                                                                                                        |
|---------------|-----------|-----------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| `id`          | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT    | The display controller ID                                                                                                          |
| `name`        | `TEXT`    | NOT NULL<br/>UNIQUE                           | The display controller name                                                                                                        |
| `public`      | `INTEGER` |                                               | Boolean:<br/>- `1`: the controller is public (visible to users on the public interface);<br/>- `0`: the controller is for referees |
| `screen_id`   | `INTEGER` | REFERENCES `screen`(`id`) ON DELETE SET NULL  | The screen ID to display                                                                                                           |
| `rotator_id`  | `INTEGER` | REFERENCES `rotator`(`id`) ON DELETE SET NULL | The rotator ID to display                                                                                                          |
| `last_update` | `TEXT`    |                                               | The date the controller was last updated                                                                                           |

### `family` table (screen families)

| Field                     | Type      | Constraint                                 | Description                                                                                                                                                                                                                                              |
|---------------------------|-----------|--------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`                      | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The family ID                                                                                                                                                                                                                                            |
| `uniq_id`                 | `TEXT`    | NOT NULL<br/>UNIQUE                        | The unique text ID of the family                                                                                                                                                                                                                         |
| `type`                    | `TEXT`    | NOT NULL                                   | The screen type:<br/>- `input`: player check-in and results entry<br/>- `boards`: pairings by chessboard<br/>- `players`: pairings in alphabetical order<br/>- `results`: latest results<br/>- `image`: image                                            |
| `public`                  | `INTEGER` |                                            | Boolean:<br/>- `1`: the family is public (visible to users on the public interface);<br/>- `0`: the family is reserved for referees                                                                                                                      |
| `name`                    | `TEXT`    |                                            | The name of the family                                                                                                                                                                                                                                   |
| `columns`                 | `INTEGER` |                                            | The number of columns in the family's screens                                                                                                                                                                                                            |
| `menu_text`               | `TEXT`    | NOT NULL                                   | The text of the hyperlink to the family's screens, used on other screens                                                                                                                                                                                 |
| `timer_id`                | `INTEGER` | REFERENCES `timer`(`id`)                   | The ID of the timer used on the family's screens                                                                                                                                                                                                         |
| `tournament_id`           | `INTEGER` | REFERENCES `tournament`(`id`)              | The ID of the tournament in the family                                                                                                                                                                                                                   |
| `input_exit_button`       | `INTEGER` |                                            | Boolean:<br/>- `NULL` if `type` is different from `input`;<br/>- `1`: a button to exit the page is displayed;<br/>- `0`: the button is not displayed                                                                                                     |
| `players_show_unpaired`   | `INTEGER` |                                            | Boolean:<br/>- `NULL` if `type` is different from `players`;<br/>- `0`: non-paired players are hidden;<br/>- `1`: non-paired players are shown                                                                                                           |
| `players_player_format`   | `INTEGER` |                                            | The display of the player:<br/>- `NULL` if `type` is different from `players`;<br/>- `1`: `GM CARLSEN Magnus`<br/>- `2`: `GM CARLSEN Magnus 2840`<br/>- `3`: `GM CARLSEN Magnus 2840F`<br/>- `4`: `GM CARLSEN Magnus 2840F \[4\]`                        |
| `players_board_format`    | `INTEGER` |                                            | The display of the board:<br/>- `NULL` if `type` is different from `players`;<br/>- `1`: `27 White`<br/>- `2`: `#27 with White`<br/>- `3`: `Board #27 White`<br/>- `4`: `Board #27 with White`                                                           |
| `players_opponent_format` | `INTEGER` |                                            | The display of the opponent:<br/>- `NULL` if `type` is different from `players`;<br/>- `1`: players' opponent are hidden;<br/>- `2`: `GM HOU Yifan`<br/>- `3`: `GM HOU Yifan 2613`<br/>- `4`: `GM HOU Yifan 2613F`<br/>- `5`: `GM HOU Yifan 2613F \[6\]` |
| `ranking_crosstable`      | `INTEGER` |                                            | Boolean:<br/>- `1`: American grid;<br/>- `0`: simple ranking                                                                                                                                                                                             |
| `ranking_round`           | `INTEGER` |                                            | The number of the round to display (by default the last round played)                                                                                                                                                                                    |
| `ranking_min_points`      | `FLOAT`   |                                            | The minimum number of points of the displayed players                                                                                                                                                                                                    |
| `ranking_max_points`      | `FLOAT`   |                                            | The maximum number of points of the displayed players                                                                                                                                                                                                    |
| `font_size`               | `INTEGER` |                                            | The font size in percentage (default 100%)                                                                                                                                                                                                               |
| `first`                   | `INTEGER` |                                            | The number of the first element (board or player) to consider                                                                                                                                                                                            |
| `last`                    | `INTEGER` |                                            | The number of the last element (board or player) to consider                                                                                                                                                                                             |
| `range`                   | `TEXT`    |                                            | The range of screens to generate, for example `4-6` (by default, all screens in the family are generated)                                                                                                                                                |
| `parts`                   | `INTEGER` |                                            | The number of screens in the family (the number of elements per screen is calculated automatically)                                                                                                                                                      |
| `number`                  | `INTEGER` |                                            | The number of elements (boards or players) per screen (the number of screens is calculated automatically)                                                                                                                                                |
| `message_default`         | `INTEGER` | NOT NULL<br/>DEFAULT 1                     | Boolean:<br/>- `1`: The event alert message (or the rotating screen, if applicable) is used for the screens in the family;<br/>- `0`: The alert message for the screens in the family is used instead of the event alert message                         |
| `message_text`            | `TEXT`    |                                            | The text of the screen's alert message (by default, no alert message is displayed)                                                                                                                                                                       |
| `last_update`             | `TEXT`    | NOT NULL                                   | The last date the screen was modified                                                                                                                                                                                                                    |
| `fixed_board_order`       | `TEXT`    |                                            | The way to order fixed boards: `pairing`, `board` or `specific`                                                                                                                                                                                          |

### `info` table (general information about the event)

> [!NOTE]
> :information_source:
> - The `info` table contains only one row.
> - The event's unique identifier is not stored in the database; it is retrieved from the event database filename.
> - The event has no dates of its own: they are derived from those of its tournaments.
> - The `deprecated_` fields are only present in databases carried forward from earlier versions; a database created now does not have them.

| Field                            | Type      | Constraint                        | Description                                                                                                                                         |
|----------------------------------|-----------|-----------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `name`                           | `TEXT`    | NOT NULL<br> DEFAULT '?'          | The name of the event                                                                                                                               |
| `location`                       | `TEXT`    |                                   | The location of the event                                                                                                                           |
| `public`                         | `INTEGER` |                                   | Boolean:<br/>- `1`: the event is public (visible to users on the public interface);<br/>- `0`: the event is reserved for referees                   |
| `background_color`               | `TEXT`    |                                   | The background color of the event's screens in hexadecimal format '`#RRGGBB` (default `#E9ECEF`)                                                    |
| `timer_colors`                   | `TEXT`    |                                   | The default colors used for timers in JSON format (dictionary with keys `1'`, `2'`, and `3'`, each color is stored in hexadecimal format `#RRGGBB`) |
| `timer_delays`                   | `TEXT`    |                                   | The default delays used for timers in JSON format (dictionary with keys `1'`, `2'`, and `3'`, each delay is stored as an integer, in seconds)       |
| `message_text`                   | `TEXT`    |                                   | The text of the event's alert messages (by default, no alert messages are displayed)                                                                |
| `message_color`                  | `TEXT`    |                                   | The color of the event's alert messages in hexadecimal format `#RRGGBB` (default `#FF0000`)                                                         |
| `message_background_color`       | `TEXT`    |                                   | The background color of the event's alert messages in hexadecimal format `#RRGGBB` (default `#FFFF00`)                                              |
| `federation`                     | `TEXT`    | NOT NULL<br/>DEFAULT 'NON'        | The event's federation code                                                                                                                         |
| `event_type`                     | `TEXT`    | NOT NULL<br/>DEFAULT 'INDIVIDUAL' | The competition type hosted by the event (`INDIVIDUAL`, `TEAM`; extensible)                                                                         |
| `prize_currency`                 | `TEXT`    |                                   | The currency the event's prizes are expressed in                                                                                                    |
| `player_rating_type`             | `INTEGER` | NOT NULL<br/>DEFAULT 3            | The rating the event's players are ranked on by default (see `tournament`.`rating`)                                                                 |
| `allow_multi_tournament_players` | `INTEGER` | NOT NULL<br/>DEFAULT 1            | Boolean:<br/>- `1`: a player may take part in several of the event's tournaments;<br/>- `0`: a player belongs to a single tournament                |
| `deprecated_chessevent_user_id`  | `TEXT`    |                                   | _Deprecated_                                                                                                                                        |
| `deprecated_chessevent_password` | `TEXT`    |                                   | _Deprecated_                                                                                                                                        |
| `deprecated_chessevent_event_id` | `TEXT`    |                                   | _Deprecated_                                                                                                                                        |
| `plugin_data`                    | `TEXT`    |                                   | Additional data used by plugins, in JSON format                                                                                                     |
| `enabled_plugins`                | `TEXT`    | NOT NULL<br/>DEFAULT '[]'         | The list of the plugins enabled for the event, in JSON format                                                                                       |
| `organiser_name`                 | `TEXT`    |                                   | The organiser's name                                                                                                                                |
| `organiser_home_page`            | `TEXT`    |                                   | The organiser's home page                                                                                                                           |
| `organiser_email`                | `TEXT`    |                                   | The organiser's email address                                                                                                                       |
| `organiser_director`             | `TEXT`    |                                   | The name of the organiser's director                                                                                                                |
| `age_category_base_date`         | `TEXT`    |                                   | The base date to calculate the players' category (`YYYY-MM-DD`)                                                                                     |
| `age_categories`                 | `TEXT`    |                                   | The age categories used to split the players                                                                                                        |
| `age_category_change_month`      | `INTEGER` | DEFAULT 1                         | The number of the month on which the category of the players changes                                                                                |
| `tag_ids`                        | `TEXT`    | NOT NULL<br/>DEFAULT '[]'         | The IDs of the event's tags, in JSON format                                                                                                         |

### `menu` table (menus)

| Field          | Type      | Constraint                                 | Description                                                |
|----------------|-----------|--------------------------------------------|------------------------------------------------------------|
| `id`           | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The menu's identifier                                      |
| `name`         | `TEXT`    |                                            | The menu's name, optional                                  |
| `default_type` | `TEXT`    |                                            | The menu's screen type                                     |
| `submenu_mode` | `TEXT`    | NOT NULL<br/>DEFAULT 'automatic'           | The display mode: `dropdown`, `no_dropdown` or `automatic` |

### `menu_item` table (menu items)

| Field         | Type      | Constraint                                 | Description                                    |
|---------------|-----------|--------------------------------------------|------------------------------------------------|
| `id`          | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The menu item's identifier                     |
| `menu_id`     | `INTEGER` | NOT NULL                                   | The ID of the menu                             |
| `screen_id`   | `INTEGER` |                                            | The ID of the screen, `NULL` if a family       |
| `family_id`   | `INTEGER` |                                            | The ID of the family, `NULL` if a basic screen |
| `screen_type` | `TEXT`    |                                            | The menu item's screen type                    |
| `index`       | `INTEGER` | NOT NULL<br/>DEFAULT 0                     | The order of the item in its menu              |

### `metadata` table (event metadata)

| Field       | Type   | Constraint                               | Description                           |
|-------------|--------|------------------------------------------|---------------------------------------|
| `version`   | `TEXT` | NOT NULL                                 | The event database version            |
| `migration` | `TEXT` | NOT NULL<br/>DEFAULT 'm000_no_migration' | The last update of the event database |

### `pairing` table (tournament pairings and results)

| Field              | Type      | Constraint                                                 | Description                                             |
|--------------------|-----------|------------------------------------------------------------|---------------------------------------------------------|
| `tournament_id`    | `INTEGER` | NOT NULL<br/>REFERENCES `tournament`(`id`)<br/>PRIMARY KEY | The tournament ID                                       |
| `player_id`        | `INTEGER` | NOT NULL<br/>REFERENCES `player`(`id`)<br/>PRIMARY KEY     | The player ID                                           |
| `round`            | `INTEGER` | NOT NULL<br/>PRIMARY KEY                                   | The round number                                        |
| `result`           | `INTEGER` | NOT NULL                                                   | The game result for the player                          |
| `board_id`         | `INTEGER` | REFERENCES `board`(`id`)                                   | The board ID where the game is played                   |
| `illegal_moves`    | `INTEGER` | NOT NULL<br/>DEFAULT 0                                     | Number of illegal moves made by the player in the round |
| `effective_points` | `REAL`    |                                                            | Override game points used for match-point calc          |

### `player` table (players)

| Field           | Type      | Constraint                                 | Description                                                      |
|-----------------|-----------|--------------------------------------------|------------------------------------------------------------------|
| `id`            | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The player ID                                                    |
| `last_name`     | `TEXT`    | NOT NULL                                   | The player's last name                                           |
| `first_name`    | `TEXT`    |                                            | The player's first name                                          |
| `date_of_birth` | `TEXT`    |                                            | The player's date of birth in YYYY-MM-DD format                  |
| `year_of_birth` | `INTEGER` |                                            | The player's year of birth, when the full date is not known      |
| `gender`        | `TEXT`    |                                            | The player's gender                                              |
| `mail`          | `TEXT`    |                                            | The player's email address                                       |
| `phone`         | `TEXT`    |                                            | The player's phone number                                        |
| `comment`       | `TEXT`    |                                            | Comments about the player                                        |
| `owed`          | `FLOAT`   | NOT NULL                                   | Amount of money owed by the player                               |
| `paid`          | `FLOAT`   | NOT NULL                                   | Amount of money paid by the player                               |
| `title`         | `TEXT`    |                                            | The player's chess title                                         |
| `women_title`   | `TEXT`    | NOT NULL<br/>DEFAULT ''                    | The player's chess women title                                   |
| `ratings`       | `TEXT`    | NOT NULL                                   | The player's ratings in JSON format                              |
| `fide_id`       | `INTEGER` |                                            | The player's _FIDE_ ID                                           |
| `federation`    | `TEXT`    |                                            | The player's federation code                                     |
| `club`          | `TEXT`    |                                            | The player's chess club                                          |
| `fixed`         | `INTEGER` |                                            | The player's fixed table (if any)                                |
| `check_in`      | `INTEGER` | NOT NULL<br/>DEFAULT 0                     | Boolean: whether the player has checked in                       |
| `team_id`       | `INTEGER` | REFERENCES `team`(`id`) ON DELETE SET NULL | The player's team (team tournaments only)                        |
| `team_index`    | `INTEGER` |                                            | The player's board order within the team (team tournaments only) |
| `plugin_data`   | `TEXT`    | NOT NULL                                   | Additional data used by plugins, in JSON format                  |

### `player_point_adjustment` table (players' point adjustments)

> [!NOTE]
> :information_source: The team counterpart is `team_point_adjustment`, which carries a match-point delta alongside the game-point one.

| Field           | Type      | Constraint                                                   | Description                         |
|-----------------|-----------|--------------------------------------------------------------|-------------------------------------|
| `id`            | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT                   | The adjustment ID                   |
| `tournament_id` | `INTEGER` | NOT NULL<br/>REFERENCES `tournament`(`id`) ON DELETE CASCADE | The tournament ID                   |
| `player_id`     | `INTEGER` | NOT NULL<br/>REFERENCES `player`(`id`) ON DELETE CASCADE     | The adjusted player                 |
| `round`         | `INTEGER` | NOT NULL                                                     | The round the adjustment applies to |
| `delta`         | `REAL`    | NOT NULL<br/>DEFAULT 0                                       | The points delta (may be negative)  |
| `reason`        | `TEXT`    |                                                              | Optional explanation                |
|                 |           | UNIQUE(`tournament_id`, `player_id`, `round`)                |                                     |

### `plugin_metadata` table (plugin metadata for the event)

| Field       | Type   | Constraint                               | Description                                        |
|-------------|--------|------------------------------------------|----------------------------------------------------|
| `name`      | `TEXT` | NOT NULL                                 | The name of the plugin                             |
| `version`   | `TEXT` | NOT NULL                                 | The database version of the plugin for the event   |
| `migration` | `TEXT` | NOT NULL<br/>DEFAULT 'm000_no_migration' | The latest extension database update for the event |

### `prize` table (prizes)

| Field               | Type      | Constraint                                            | Description                                                    |
|---------------------|-----------|-------------------------------------------------------|----------------------------------------------------------------|
| `id`                | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT<br/>UNIQUE | The prize ID                                                   |
| `prize_category_id` | `INTEGER` | NOT NULL<br/>REFERENCES `prize_category`(`id`)        | The prize category ID                                          |
| `value`             | `FLOAT`   | NOT NULL<br/>DEFAULT 0.0                              | The monetary value of the prize                                |
| `type`              | `TEXT`    |                                                       | The type of the prize (`MONETARY`, `NON_MONETARY` or `HYBRID`) |
| `description`       | `TEXT`    |                                                       | The prize description                                          |

### `prize_category` table (prize categories)

| Field               | Type      | Constraint                                            | Description                                                                                  |
|---------------------|-----------|-------------------------------------------------------|----------------------------------------------------------------------------------------------|
| `id`                | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT<br/>UNIQUE | The prize category ID                                                                        |
| `prize_group_id`    | `INTEGER` | NOT NULL<br/>REFERENCES `prize_group`(`id`)           | The prize group ID                                                                           |
| `name`              | `TEXT`    | NOT NULL                                              | The prize category name                                                                      |
| `prize_sharing`     | `TEXT`    | NOT NULL                                              | How prizes are shared in this category                                                       |
| `sharing_threshold` | `FLOAT`   |                                                       | The threshold for prize sharing                                                              |
| `is_main`           | `INTEGER` | NOT NULL<br/>DEFAULT 0                                | Boolean: whether this is the main prize category                                             |
| `index`             | `INTEGER` | NOT NULL                                              | The ordering index of the category                                                           |
| `ranking_basis`     | `TEXT`    | NOT NULL<br/>DEFAULT 'final_standing'                 | How players are ranked (`final standing`, `average_performance` or `best_round_performance`) |

### `prize_criterion` table (prize criteria)

| Field               | Type      | Constraint                                            | Description                      |
|---------------------|-----------|-------------------------------------------------------|----------------------------------|
| `id`                | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT<br/>UNIQUE | The prize criterion ID           |
| `prize_category_id` | `INTEGER` | NOT NULL<br/>REFERENCES `prize_category`(`id`)        | The prize category ID            |
| `type`              | `TEXT`    | NOT NULL                                              | The criterion type               |
| `options`           | `TEXT`    |                                                       | Criterion options in JSON format |

### `prize_group` table (prize groups)

| Field           | Type      | Constraint                                            | Description          |
|-----------------|-----------|-------------------------------------------------------|----------------------|
| `id`            | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT<br/>UNIQUE | The prize group ID   |
| `tournament_id` | `INTEGER` | NOT NULL<br/>REFERENCES `tournament`(`id`)            | The tournament ID    |
| `name`          | `TEXT`    | NOT NULL                                              | The prize group name |

### `prohibited_pairing_group` table (prohibited-pairing groups)

> [!NOTE]
> :information_source: A group is a set of members (players or teams) that must not be paired together. `round` NULL = a reusable manual template carried forward; a non-NULL `round` = an immutable per-round snapshot driving the TRF 260 export. `protect_rank` (snapshot rows) records the soft-relaxation cutoff applied that round.

| Field           | Type      | Constraint                                                   | Description                                               |
|-----------------|-----------|--------------------------------------------------------------|-----------------------------------------------------------|
| `id`            | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT                   | The group ID                                              |
| `tournament_id` | `INTEGER` | NOT NULL<br/>REFERENCES `tournament`(`id`) ON DELETE CASCADE | The tournament ID                                         |
| `round`         | `INTEGER` |                                                              | `NULL` = reusable template; non-NULL = per-round snapshot |
| `is_hard`       | `INTEGER` | NOT NULL<br/>DEFAULT 1                                       | Boolean: hard (`1`) vs soft (`0`) constraint              |
| `protect_rank`  | `INTEGER` |                                                              | Soft-relaxation cutoff for the round (snapshot rows only) |

### `prohibited_pairing_group_member` table (prohibited-pairing group members)

| Field       | Type      | Constraint                                                                                 | Description                    |
|-------------|-----------|--------------------------------------------------------------------------------------------|--------------------------------|
| `group_id`  | `INTEGER` | NOT NULL<br/>REFERENCES `prohibited_pairing_group`(`id`) ON DELETE CASCADE<br/>PRIMARY KEY | The group ID                   |
| `member_id` | `INTEGER` | NOT NULL<br/>PRIMARY KEY                                                                   | The member ID (player or team) |

### `rotating_screen` table (rotating screens)

| Field        | Type      | Constraint                                 | Description                                                           |
|--------------|-----------|--------------------------------------------|-----------------------------------------------------------------------|
| `id`         | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The rotating screen's identifier                                      |
| `rotator_id` | `INTEGER` | NOT NULL                                   | The ID of the rotator                                                 |
| `screen_id`  | `INTEGER` |                                            | The ID of the screen, `NULL` if a family                              |
| `family_id`  | `INTEGER` |                                            | The ID of the family, `NULL` if a basic screen                        |
| `index`      | `INTEGER` | NOT NULL                                   | The order of the screen/family in the screens/families of the rotator |

### `rotator` table (rotators)

> [!NOTE]
> :information_source: The screens and families a rotator cycles through are held in the `rotating_screen` table, one row per entry.

| Field             | Type      | Constraint                                  | Description                                                                                                                                                                                                  |
|-------------------|-----------|---------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`              | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT  | The rotating screen's identifier                                                                                                                                                                             |
| `name`            | `TEXT`    | NOT NULL<br/>UNIQUE                         | The name of the rotating screen                                                                                                                                                                              |
| `public`          | `INTEGER` |                                             | Boolean:<br/>- `1`: The rotating screen is public (visible to users on the public interface);<br/>- `0`: The rotating screen is reserved for referees                                                        |
| `delay`           | `INTEGER` |                                             | The screen rotation delay in seconds, optional (default 15)                                                                                                                                                  |
| `timer_id`        | `INTEGER` | REFERENCES `timer`(`id`) ON DELETE SET NULL | The ID of the timer used on the rotating screen                                                                                                                                                              |
| `message_default` | `INTEGER` | NOT NULL<br/>DEFAULT 1                      | Boolean:<br/>- `1`: The event alert message is used (unless a message is defined for the screens);<br/>- `0`: The alert message for the rotating screen's screens is used instead of the event alert message |
| `message_text`    | `TEXT`    |                                             | The screen's alert message text (by default, no alert message is displayed)                                                                                                                                  |

### `screen` table (screens)

| Field                     | Type      | Constraint                                 | Description                                                                                                                                                                                                                                              |
|---------------------------|-----------|--------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`                      | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The screen ID                                                                                                                                                                                                                                            |
| `uniq_id`                 | `TEXT`    | NOT NULL<br/>UNIQUE                        | The unique text ID of the screen                                                                                                                                                                                                                         |
| `type`                    | `TEXT`    | NOT NULL                                   | The screen type:<br/>- `input`: player check-in and results entry<br/>- `boards`: pairings by chessboard<br/>- `players`: pairings in alphabetical order<br/>- `results`: latest results<br/>- `image`: image                                            |
| `public`                  | `INTEGER` |                                            | Boolean:<br/>- `1`: the screen is public (visible to users on the public interface);<br/>- `0`: the screen is reserved for referees                                                                                                                      |
| `name`                    | `TEXT`    |                                            | The name of the screen                                                                                                                                                                                                                                   |
| `columns`                 | `INTEGER` |                                            | The number of columns on the screen                                                                                                                                                                                                                      |
| `menu_text`               | `TEXT`    |                                            | `NULL` if `type` is `image`, otherwise the text of the hyperlink to the screen, used on other screens                                                                                                                                                    |
| `timer_id`                | `INTEGER` | REFERENCES `timer`(`id`)                   | The timer ID                                                                                                                                                                                                                                             |
| `input_exit_button`       | `INTEGER` |                                            | Boolean:<br/>- `NULL` if `type` is different from `input`;<br/>- `1`: a button to exit the page is displayed;<br/>- `0`: the button is not displayed                                                                                                     |
| `players_show_unpaired`   | `INTEGER` |                                            | Boolean:<br/>- `NULL` if `type` is different from `players`;<br/>- `0`: non-paired players are hidden;<br/>- `1`: non-paired players are shown                                                                                                           |
| `players_player_format`   | `INTEGER` |                                            | The display of the player:<br/>- `NULL` if `type` is different from `players`;<br/>- `1`: `GM CARLSEN Magnus`<br/>- `2`: `GM CARLSEN Magnus 2840`<br/>- `3`: `GM CARLSEN Magnus 2840F`<br/>- `4`: `GM CARLSEN Magnus 2840F \[4\]`                        |
| `players_board_format`    | `INTEGER` |                                            | The display of the board:<br/>- `NULL` if `type` is different from `players`;<br/>- `1`: `27 White`<br/>- `2`: `#27 with White`<br/>- `3`: `Board #27 White`<br/>- `4`: `Board #27 with White`                                                           |
| `players_opponent_format` | `INTEGER` |                                            | The display of the opponent:<br/>- `NULL` if `type` is different from `players`;<br/>- `1`: players' opponent are hidden;<br/>- `2`: `GM HOU Yifan`<br/>- `3`: `GM HOU Yifan 2613`<br/>- `4`: `GM HOU Yifan 2613F`<br/>- `5`: `GM HOU Yifan 2613F \[6\]` |
| `results_limit`           | `INTEGER` |                                            | - `NULL` if `type` is different from `results`;<br/>- `0`: all recent results are shown;<br/>- positive integer: the maximum number of results shown on the screen                                                                                       |
| `results_max_age`         | `INTEGER` |                                            | - `NULL` if `type` is different from `results`;<br/>- `NULL` or positive integer: the maximum age of results displayed on the screen (in minutes, default 60)                                                                                            |
| `results_tournament_ids`  | `TEXT`    |                                            | - `NULL` if `type` is not equal to `results`;<br/>- The list of tournament IDs for which results are displayed on the screen, in JSON format (if the list is empty, the results of all tournaments are displayed)                                        |
| `background_image`        | `TEXT`    |                                            | - `NULL` if `type` is not equal to `image`;<br/>- The URL of the image to display                                                                                                                                                                        |
| `background_color`        | `TEXT`    |                                            | - `NULL` if `type` is not equal to `image`;<br/>- The background color of the image, in hexadecimal format `#RRGGBB`                                                                                                                                     |
| `ranking_crosstable`      | `INTEGER` |                                            | Boolean:<br/>- `1`: American grid;<br/>- `0`: simple ranking                                                                                                                                                                                             |
| `ranking_round`           | `INTEGER` |                                            | The number of the round to display (by default the last round played)                                                                                                                                                                                    |
| `ranking_min_points`      | `FLOAT`   |                                            | The minimum number of points of the displayed players                                                                                                                                                                                                    |
| `ranking_max_points`      | `FLOAT`   |                                            | The maximum number of points for the displayed players                                                                                                                                                                                                   |
| `font_size`               | `INTEGER` |                                            | The font size in percentage (default 100%)                                                                                                                                                                                                               |
| `message_default`         | `INTEGER` | NOT NULL<br/>DEFAULT 1                     | Boolean:<br/>- `1`: The event alert message (or the rotating screen, if applicable) is used;<br/>- `0`: The screen alert message is used instead of the event alert message                                                                              |
| `message_text`            | `TEXT`    |                                            | The text of the screen's alert message (by default, no alert message is displayed)                                                                                                                                                                       |
| `last_update`             | `TEXT`    | NOT NULL                                   | The date the screen was last modified                                                                                                                                                                                                                    |
| `plugin_data`             | `TEXT`    |                                            | Additional data used by plugins, in JSON format                                                                                                                                                                                                          |

### `screen_set` table (screen sets)

| Field               | Type      | Constraint                                                   | Description                                                     |
|---------------------|-----------|--------------------------------------------------------------|-----------------------------------------------------------------|
| `id`                | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT                   | The set ID                                                      |
| `screen_id`         | `INTEGER` | NOT NULL<br/>REFERENCES `screen`(`id`) ON DELETE CASCADE     | The ID of the screen the set belongs to                         |
| `tournament_id`     | `INTEGER` | NOT NULL<br/>REFERENCES `tournament`(`id`) ON DELETE CASCADE | The tournament ID                                               |
| `name`              | `TEXT`    |                                                              | The name of the set                                             |
| `order`             | `INTEGER` | NOT NULL                                                     | The order of the set relative to other sets on its screen       |
| `first`             | `INTEGER` |                                                              | The number of the first element (board or player) to consider   |
| `last`              | `INTEGER` |                                                              | The number of the last element (board or player) to consider    |
| `fixed_boards_str`  | `TEXT`    |                                                              | Board numbers separated by commas                               |
| `last_update`       | `TEXT`    | NOT NULL                                                     | The date the set was last modified                              |
| `fixed_board_order` | `TEXT`    |                                                              | The way to order fixed boards: `pairing`, `board` or `specific` |

### `team` table (teams in team tournaments)

| Field            | Type      | Constraint                                       | Description                                                 |
|------------------|-----------|--------------------------------------------------|-------------------------------------------------------------|
| `id`             | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT       | The team ID                                                 |
| `tournament_id`  | `INTEGER` | REFERENCES `tournament`(`id`) ON DELETE SET NULL | The assigned tournament (`NULL` = unassigned, event-scoped) |
| `name`           | `TEXT`    | NOT NULL                                         | The team name                                               |
| `pairing_number` | `INTEGER` |                                                  | The team's pairing number in the tournament                 |
| `captain_id`     | `INTEGER` | REFERENCES `player`(`id`) ON DELETE SET NULL     | The team captain, if a registered player                    |
| `captain_name`   | `TEXT`    |                                                  | The captain's name (free text, e.g. non-playing captain)    |
| `group_id`       | `INTEGER` | REFERENCES `team_group`(`id`) ON DELETE SET NULL | The team's group (club / league / etc.), if any             |
| `federation`     | `TEXT`    |                                                  | The team's federation code                                  |
| `check_in`       | `INTEGER` | NOT NULL<br/>DEFAULT 0                           | Boolean: whether the team has checked in                    |

### `team_board` table (team-vs-team matches)

| Field                | Type      | Constraint                                                   | Description                                                                          |
|----------------------|-----------|--------------------------------------------------------------|--------------------------------------------------------------------------------------|
| `id`                 | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT                   | The team match ID                                                                    |
| `tournament_id`      | `INTEGER` | NOT NULL<br/>REFERENCES `tournament`(`id`) ON DELETE CASCADE | The tournament ID                                                                    |
| `round`              | `INTEGER` | NOT NULL                                                     | The round number                                                                     |
| `team_a_id`          | `INTEGER` | NOT NULL<br/>REFERENCES `team`(`id`) ON DELETE CASCADE       | One of the two teams (symmetric; colors via `color_pattern`)                         |
| `team_b_id`          | `INTEGER` | REFERENCES `team`(`id`) ON DELETE CASCADE                    | The other team (`NULL` = bye)                                                        |
| `index`              | `INTEGER` |                                                              | Table slot (0-based). `NULL` for hidden byes (HPB/FPB/ZPB) that don't sit at a table |
| `last_result_update` | `TEXT`    |                                                              | Timestamp of the last result update                                                  |
| `bye_type`           | `TEXT`    |                                                              | Bye type when `team_b_id` is NULL (PAB/HPB/FPB/ZPB); `NULL` for regular pairings     |

### `team_group` table (reusable team groupings)

> [!NOTE]
> :information_source: Event-level groupings (club, league, etc.). Teams reference a group via `team`.`group_id`; used downstream to keep teams in the same group from being paired together.

| Field  | Type      | Constraint                                 | Description         |
|--------|-----------|--------------------------------------------|---------------------|
| `id`   | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The team group ID   |
| `name` | `TEXT`    | NOT NULL                                   | The team group name |

### `team_pairing_block` table (prohibited team pairings)

| Field           | Type      | Constraint                                                   | Description                                                |
|-----------------|-----------|--------------------------------------------------------------|------------------------------------------------------------|
| `id`            | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT                   | The block entry ID                                         |
| `tournament_id` | `INTEGER` | NOT NULL<br/>REFERENCES `tournament`(`id`) ON DELETE CASCADE | The tournament ID                                          |
| `round`         | `INTEGER` |                                                              | The round to block on; `NULL` = block for all rounds       |
| `team_a_id`     | `INTEGER` | NOT NULL<br/>REFERENCES `team`(`id`) ON DELETE CASCADE       | First team in the prohibited pair                          |
| `team_b_id`     | `INTEGER` | NOT NULL<br/>REFERENCES `team`(`id`) ON DELETE CASCADE       | Second team in the prohibited pair                         |
| `reason`        | `TEXT`    |                                                              | Optional explanation (e.g. same club, won previous rounds) |

### `team_point_adjustment` table (manual team point bonuses / penalties)

| Field           | Type      | Constraint                                                   | Description                         |
|-----------------|-----------|--------------------------------------------------------------|-------------------------------------|
| `id`            | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT                   | The adjustment ID                   |
| `tournament_id` | `INTEGER` | NOT NULL<br/>REFERENCES `tournament`(`id`) ON DELETE CASCADE | The tournament ID                   |
| `team_id`       | `INTEGER` | NOT NULL<br/>REFERENCES `team`(`id`) ON DELETE CASCADE       | The adjusted team                   |
| `round`         | `INTEGER` | NOT NULL                                                     | The round the adjustment applies to |
| `mp_delta`      | `REAL`    | NOT NULL<br/>DEFAULT 0                                       | Match-point delta (may be negative) |
| `gp_delta`      | `REAL`    | NOT NULL<br/>DEFAULT 0                                       | Game-point delta (may be negative)  |
| `reason`        | `TEXT`    |                                                              | Optional explanation                |
|                 |           | UNIQUE(`tournament_id`, `team_id`, `round`)                  |                                     |

### `team_round_lineup` table (team line-ups per round)

| Field       | Type      | Constraint                                                             | Description                                              |
|-------------|-----------|------------------------------------------------------------------------|----------------------------------------------------------|
| `team_id`   | `INTEGER` | NOT NULL<br/>REFERENCES `team`(`id`) ON DELETE CASCADE<br/>PRIMARY KEY | The team ID                                              |
| `round`     | `INTEGER` | NOT NULL<br/>PRIMARY KEY                                               | The round number                                         |
| `player_id` | `INTEGER` | NOT NULL<br/>REFERENCES `player`(`id`) ON DELETE CASCADE               | The player playing on this board for the round           |
| `index`     | `INTEGER` | NOT NULL<br/>PRIMARY KEY                                               | The board index within the team for that round (0-based) |

### `tie_break` table (tournament tie-breaks)

> [!NOTE]
> :information_source: One row per tie-break of a tournament; `index` gives the order they are applied in.

| Field           | Type      | Constraint                                                   | Description                             |
|-----------------|-----------|--------------------------------------------------------------|-----------------------------------------|
| `id`            | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT                   | The tie-break ID                        |
| `tournament_id` | `INTEGER` | NOT NULL<br/>REFERENCES `tournament`(`id`) ON DELETE CASCADE | The tournament ID                       |
| `type`          | `TEXT`    | NOT NULL                                                     | The tie-break type                      |
| `options`       | `TEXT`    | NOT NULL                                                     | The tie-break's options, in JSON format |
| `index`         | `INTEGER` | NOT NULL                                                     | The order the tie-break is applied in   |

### `timer` table (timer configurations)

| Field    | Type      | Constraint                                 | Description                                                                                                                        |
|----------|-----------|--------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| `id`     | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The stopwatch identifier                                                                                                           |
| `name`   | `TEXT`    | NOT NULL<br/>UNIQUE                        | The name of the stopwatch                                                                                                          |
| `colors` | `TEXT`    |                                            | The colors used in JSON format (dictionary with keys `1'`, `2'`, and `3'`, each color is stored in hexadecimal format ``#RRGGBB``) |
| `delays` | `TEXT`    |                                            | The delays used in JSON format (dictionary with keys `'1'`, `'2'` and `'3'`, each delay is stored as an integer, in seconds)       |

### `timer_hour` table (timer hours)

| Field          | Type      | Constraint                                 | Description                                                                                                                           |
|----------------|-----------|--------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| `id`           | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The timer ID                                                                                                                          |
| `uniq_id`      | `TEXT`    | NOT NULL                                   | The unique text ID of the timer (if the field is a positive integer, the timer is identified as the start of the corresponding round) |
| `timer_id`     | `INTEGER` | NOT NULL<br>REFERENCES `timer`(`id`)       | The timer ID                                                                                                                          |
| `triggered_at` | `TEXT`    |                                            | The datetime at which the timer hour is triggered (ISO format)                                                                        |
| `text_before`  | `TEXT`    |                                            | The text to display on the timer before the schedule                                                                                  |
| `text_after`   | `TEXT`    |                                            | The text to display on the timer after the schedule                                                                                   |
|                |           | UNIQUE(`uniq_id`, `timer_id`)              |                                                                                                                                       |

### `tournament` table (tournaments)

> [!NOTE]
> :information_source: The `deprecated_` fields are only present in databases carried forward from earlier versions; a database created now does not have them.

| Field                                     | Type      | Constraint                                 | Description                                                                                                                                          |
|-------------------------------------------|-----------|--------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`                                      | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The tournament ID                                                                                                                                    |
| `name`                                    | `TEXT`    | NOT NULL<br/>UNIQUE                        | The tournament name                                                                                                                                  |
| `index`                                   | `INTEGER` | NOT NULL<br/>DEFAULT 0                     | The order of the tournament within its event                                                                                                         |
| `location`                                | `TEXT`    |                                            | The location of the tournament (by default the location of the event)                                                                                |
| `start_date`                              | `TEXT`    |                                            | The start date of the tournament (`YYYY-MM-DD`)                                                                                                      |
| `stop_date`                               | `TEXT`    |                                            | The end date of the tournament (`YYYY-MM-DD`)                                                                                                        |
| `time_control_trf25`                      | `TEXT`    |                                            | The time control in TRF25 format                                                                                                                     |
| `record_illegal_moves`                    | `INTEGER` |                                            | The maximum number of illegal moves that can be recorded for a player per round                                                                      |
| `check_in_open`                           | `INTEGER` | NOT NULL<br/>DEFAULT 0                     | Boolean: whether check-in is open for the tournament                                                                                                 |
| `dirty`                                   | `BOOLEAN` | DEFAULT 0                                  | Boolean: whether the tournament changed since the last time its screens were rendered (set by trigger)                                               |
| `last_update`                             | `TEXT`    | NOT NULL<br/>DEFAULT ''                    | The last date the tournament was modified                                                                                                            |
| `last_player_update`                      | `TEXT`    | NOT NULL<br/>DEFAULT ''                    | The last date a player associated with this tournament was modified                                                                                  |
| `last_pairing_update`                     | `TEXT`    | NOT NULL<br/>DEFAULT ''                    | The last date a pairing associated with this tournament score was modified                                                                           |
| `first_board_number`                      | `INTEGER` |                                            | The first board number                                                                                                                               |
| `paired_bye_result`                       | `INTEGER` |                                            | Result awarded to bye players                                                                                                                        |
| `max_byes`                                | `INTEGER` |                                            | The maximum number of byes a player can claim                                                                                                        |
| `last_rounds_no_byes`                     | `INTEGER` |                                            | The number of final rounds for which players cannot take byes                                                                                        |
| `rounds`                                  | `INTEGER` | NOT NULL<br/>DEFAULT 1                     | The tournament's round count (`0` when the pairing system settles it from its entrants or its boards)                                                |
| `rating`                                  | `INTEGER` | NOT NULL<br/>DEFAULT 1                     | The tournament's rating:<br/>- `1`: Estimated<br/>- `2`: National<br/>- `3`: _FIDE_                                                                  |
| `player_rating_type`                      | `INTEGER` |                                            | The rating the players are ranked on, overriding the event's                                                                                         |
| `override_unrated_rapid_blitz`            | `INTEGER` |                                            | Boolean: whether unrated rapid / blitz players fall back to their standard rating                                                                    |
| `pairing`                                 | `TEXT`    |                                            | The tournament's pairing as a string                                                                                                                 |
| `pairing_settings`                        | `TEXT`    |                                            | The tournament's pairing settings, in JSON format                                                                                                    |
| `current_round`                           | `INTEGER` |                                            | The tournament's current round                                                                                                                       |
| `round_datetimes`                         | `TEXT`    |                                            | The round schedule in JSON format ({int: datetime, None})                                                                                            |
| `criteria`                                | `TEXT`    | NOT NULL<br/>DEFAULT '{}'                  | The criteria in JSON format ({str: Any})                                                                                                             |
| `game_points`                             | `TEXT`    |                                            | Game points awarded per result (WIN, DRAW, LOSS, ZERO_POINT_BYE, PAIRING_ALLOCATED_BYE), JSON dict (replaces `three_points_for_a_win` / `pab_value`) |
| `team_player_count`                       | `INTEGER` |                                            | Number of boards per team match. `NULL` for individual tournaments                                                                                   |
| `roster_max_size`                         | `INTEGER` |                                            | Largest number of players a team may have on its roster (`NULL` = no limit)                                                                          |
| `match_points`                            | `TEXT`    |                                            | Points awarded per team match outcome, JSON dict keyed by `Result.value` (team mode only)                                                            |
| `color_pattern`                           | `TEXT`    |                                            | Per-board color allocation pattern ID (plugin-extendable, team mode only)                                                                            |
| `team_colour_type`                        | `TEXT`    |                                            | Colour-allocation scheme for team matches (team mode only)                                                                                           |
| `primary_score`                           | `TEXT`    |                                            | Primary ranking score ID for the team standings (team mode only)                                                                                     |
| `secondary_score_for_colours`             | `INTEGER` | NOT NULL DEFAULT 1                         | Boolean: whether the secondary score is used for colour allocation                                                                                   |
| `enforce_roster_order`                    | `INTEGER` | NOT NULL<br/>DEFAULT 0                     | Boolean: whether round line-ups must follow the team roster order                                                                                    |
| `team_sort_mode`                          | `TEXT`    | NOT NULL<br/>DEFAULT 'MANUAL'              | How teams are ordered (e.g. `MANUAL`; extensible)                                                                                                    |
| `rule_set`                                | `TEXT`    |                                            | The applied rule-set ID (e.g. an FFE rule set), if any                                                                                               |
| `rule_set_config`                         | `TEXT`    |                                            | The configuration of the rule set for the tournament, in JSON format                                                                                 |
| `prohibited_pairing_dimension`            | `TEXT`    |                                            | Grouping-dimension ID used to derive prohibited pairings (`NULL` = off)                                                                              |
| `prohibited_pairing_dimension_is_hard`    | `INTEGER` | NOT NULL<br/>DEFAULT 1                     | Boolean: whether the prohibited-pairing dimension is a hard constraint                                                                               |
| `round_robin_participation_rule`          | `INTEGER` | NOT NULL<br/>DEFAULT 0                     | Boolean: whether the round-robin &lt;50% participation rule (FIDE 6.6) applies — leavers dropped from the final standings.                           |
| `deprecated_chessevent_user_id`           | `TEXT`    |                                            | _Deprecated_                                                                                                                                         |
| `deprecated_chessevent_password`          | `TEXT`    |                                            | _Deprecated_                                                                                                                                         |
| `deprecated_chessevent_event_id`          | `TEXT`    |                                            | _Deprecated_                                                                                                                                         |
| `deprecated_chessevent_tournament_name`   | `TEXT`    |                                            | _Deprecated_                                                                                                                                         |
| `deprecated_last_chessevent_download_md5` | `TEXT`    |                                            | _Deprecated_                                                                                                                                         |
| `plugin_data`                             | `TEXT`    |                                            | Additional data used by plugins, in JSON format                                                                                                      |

### `tournament_player` table (tournament player associations)

| Field             | Type      | Constraint                                                 | Description                                                                       |
|-------------------|-----------|------------------------------------------------------------|-----------------------------------------------------------------------------------|
| `tournament_id`   | `INTEGER` | NOT NULL<br/>REFERENCES `tournament`(`id`)<br/>PRIMARY KEY | The tournament ID                                                                 |
| `player_id`       | `INTEGER` | NOT NULL<br/>REFERENCES `player`(`id`)<br/>PRIMARY KEY     | The player ID                                                                     |
| `pairing_number`  | `INTEGER` |                                                            | The player's pairing number in tournament                                         |
| `manual_tiebreak` | `INTEGER` |                                                            | The rank the arbiter settled by hand, breaking a tie the tie-breaks left standing |

## FIDE Local Database (`tmp/fide.db`)

### `player` table (FIDE players)

| Field                | Type      | Constraint                                 | Description                            |
|----------------------|-----------|--------------------------------------------|----------------------------------------|
| `id`                 | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The player's internal ID               |
| `fide_id`            | `INTEGER` | NOT NULL                                   | The player's _FFE_ ID                  |
| `last_name`          | `TEXT`    | NOT NULL                                   | The player's last name                 |
| `first_name`         | `TEXT`    |                                            | The player's first name                |
| `federation`         | `TEXT`    | NOT NULL                                   | The player's federation code           |
| `gender`             | `INTEGER` | NOT NULL                                   | The player's gender (1: Woman, 2: Man) |
| `title`              | `TEXT`    | NOT NULL                                   | The player's _FIDE_ title              |
| `standard_rating`    | `INTEGER` | NOT NULL                                   | The player's standard rating           |
| `rapid_rating`       | `INTEGER` | NOT NULL                                   | The player's rapid rating              |
| `blitz_rating`       | `INTEGER` | NOT NULL                                   | The player's blitz rating              |
| `year_of_birth`      | `INTEGER` | NOT NULL                                   | The player's year of birth             |
| `fide_arbiter_title` | `TEXT`    | NOT NULL                                   | The player's _FIDE_ arbiter title      |

## _FFE_ Local Database (`tmp/ffe/ffe.db`)

> [!NOTE]
> :information_source: This database is managed by plugin `ffe`.

### `player` table (_FFE_ players)

| Field                | Type      | Constraint                                 | Description                                      |
|----------------------|-----------|--------------------------------------------|--------------------------------------------------|
| `id`                 | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | The player's internal ID                         |
| `fide_id`            | `INTEGER` | NOT NULL                                   | The player's _FFE_ ID                            |
| `last_name`          | `TEXT`    | NOT NULL                                   | The player's last name                           |
| `first_name`         | `TEXT`    |                                            | The player's first name                          |
| `date_of_birth`      | `TEXT`    |                                            | The player's date of birth in YYYY-MM-DD format  |
| `gender`             | `INTEGER` | NOT NULL                                   | The player's gender (1: Man, 2: Woman, 9: Other) |
| `ffe_licence_number` | `TEXT`    |                                            | The player's licence number (Xnnnnn)             |
| `ffe_licence`        | `INTEGER` | NOT NULL                                   | The player's licence type (1: None, 2: A, 3: B)  |
| `federation`         | `TEXT`    | NOT NULL                                   | The player's federation code                     |
| `league`             | `TEXT`    |                                            | The player's _FFE_ league (3-letter) code        |
| `city`               | `TEXT`    |                                            | The city of the player's club                    |
| `club`               | `TEXT`    |                                            | The player's club name                           |
| `fide_id`            | `INTEGER` |                                            | The player's _FIDE_ ID (if any)                  |
| `fide_title`         | `TEXT`    | NOT NULL                                   | The player's _FIDE_ title                        |
| `standard_rating`    | `INTEGER` | NOT NULL                                   | The player's standard rating                     |
| `rapid_rating`       | `INTEGER` | NOT NULL                                   | The player's rapid rating                        |
| `blitz_rating`       | `INTEGER` | NOT NULL                                   | The player's blitz rating                        |
| `ffe_arbiter_title`  | `TEXT`    | NOT NULL                                   | The player's _FFE_ arbiter title                 |

## FRA Schools Local Database (`tmp/fra_schools/fra_schools.db`)

> [!NOTE]
> :information_source: This database is managed by plugin `fra_schools`.

### `department` table (French departments)

| Field  | Type   | Constraint | Description                                           |
|--------|--------|------------|-------------------------------------------------------|
| `id`   | `TEXT` | NOT NULL   | The department's ID (`01` to `988`)                   |
| `name` | `TEXT` | NOT NULL   | The department's name (`Ain` to `Nouvelle Calédonie`) |

### `school` table (schools)

| Field         | Type      | Constraint | Description                                       |
|---------------|-----------|------------|---------------------------------------------------|
| `id`          | `INTEGER` | NOT NULL   | The school's internal ID                          |
| `code`        | `TEXT`    | NOT NULL   | The school's code (`DEPnnnnL`)                    |
| `name`        | `TEXT`    | NOT NULL   | The school's name                                 |
| `postal_code` | `TEXT`    | NOT NULL   | The school's postal code                          |
| `department`  | `TEXT`    |            | The school's department (if any)                  |
| `city`        | `TEXT`    | NOT NULL   | The school's city                                 |
| `type`        | `TEXT`    | NOT NULL   | The school's type (`Ecole`, `Collège` or `Lycée`) |
| `private`     | `INTEGER` | NOT NULL   | Boolean: `0` if public, `1` if private            |

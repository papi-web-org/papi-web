**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Stockage des données

Cette page est dédiée aux évolutions possibles du stockage des données de Papi-web.

> [!NOTE]
> L'abandon de Access permettrait :
> - de supprimer les problèmes liés à la base de données actuelle ;
> - de rendre l'application portable sur d'autres plateformes que Windows.

## Type de stockage

SGBD relationnel ou JSON texte ?

Un SGBD léger permettrait de limiter le parsing des données et de gérer les accès concurrentiels.

## Structuration des données

Un stockage par tournoi, un stockage par évènement ou un stockage global pour toutes les données sur la machine ?

Il parait indispensable d'avoir un format d'export (pour transporter un évènement ou tournoi d'une machine vers une 
autre) mais cela ne justifie pas forcément d'avoir un stockage par évènement ou tournoi (on peut envisager un format 
de stockage et un format d'export).

Note : la rupture avec le stockage actuel peut être perturbante (aujourd'hui : 1 tournoi = 1 fichier) ; lors du premier lancement d'une version appuyée sur une base de données, l'application devrait récupérer toutes les données enregistrées précédemment aux formats Papi/ini.

## Données à stocker

Les données sont décrites ci-dessous dans l'hypothèse d'un stockage global des données.

### Informations générales (table INFO)

| Champ            | Type         | Remarque                                                                         |
|------------------|--------------|----------------------------------------------------------------------------------|
| `version`        | int not null | Pour permettre la migration des bases de données par l'application au chargement |
| `admin_password` | str          | Le mot de passe d'administration (création et suppression des tournois)          |

### Évènement (table EVENT)

| Champ                       | Type          | Remarque                                                                                                        |
|-----------------------------|---------------|-----------------------------------------------------------------------------------------------------------------|
| `id`                        | autoincrement | PK                                                                                                              |
| `name`                      | str           |                                                                                                                 |
| `update_password`           | str           | Le mot de passe pour entrer les résultats (pourquoi en NUMERIC dans SQLite ?)                                   |
| `edit_password`             | str           | Le mot de passe pour éditer l'évènement                                                                         |
| `timer_enabled`             | bool          |                                                                                                                 |
| `timer_text_before_round`   | str           | Le texte du chronomètre avant le début d'une ronde                                                              |
| `timer_text_after_round`    | str           | Le texte du chronomètre après le début d'une ronde                                                              |
| `ffe_upload_enabled`        | bool          | true si le téléchargement sur le site fédéral est activé pour le tournoi (note : plus parlant que `ffe_upload`) |
| `chessevent_update_enabled` | bool          | true si la mise à jour depuis Chess Event est activée (note : plus parlant que `chessevent_download`)           |
| `css`                       | str           |                                                                                                                 |

### ### Connexions à Chess Event (table CHESSEVENT_CONNECTION)

| Champ         | Type          | Remarque                          |
|---------------|---------------|-----------------------------------|
| `id`          | autoincrement | PK                                |
| `event_id`    | int not null  | FK(`EVENT.id`)                    |
| `ce_user_id`  | str           |                                   |
| `ce_password` | str           |                                   |
| `ce_event_id` | str           | `ce_event_id` ou `ce_event_str` ? |

### Couleurs de démarrage (table START_COLOR)

| Champ   | Type          | Remarque                  |
|---------|---------------|---------------------------|
| `id`    | autoincrement | PK                        |
| `label` | str not null  |                           |
| `name`  | str not null  | Utile ? l10n-compatible ? |

#### Données pré-remplies

| `id` | `label` | `name`      |
|------|---------|-------------|
| 1    | `R`     | `Aléatoire` |
| 2    | `W`     | `Blancs`    |
| 3    | `B`     | `Noirs`     |

### Tournoi (table TOURNAMENT)

| Champ                        | Type          | Remarque                                                                  |
|------------------------------|---------------|---------------------------------------------------------------------------|
| `id`                         | autoincrement | PK                                                                        |
| `event_id`                   | int not null  | FK(`EVENT.id`)                                                            |
| `name`                       | str           |                                                                           |
| `time_control_initial_time`  | int           |                                                                           |
| `time_control_increment`     | int           |                                                                           |
| `handicap_penalty_step`      | int           |                                                                           |
| `handicap_penalty_value`     | int           |                                                                           |
| `handicap_min_time`          | int           |                                                                           |
| `rounds`                     | int           |                                                                           |
| `top_seed_start_color_id`    | enum          | FK(`START_COLOR.id`)                                                      |
| `points_paired_bye`          | float         | Points d'exempt                                                           |
| `maximum player_byes`        | int           | Le nombre maximum de byes pendant le tournoi                              |
| `last_round_no_player_byes`  | int           | Le nombre des dernières rondes où les byes ne sont pas autorisés          |
| `pairing_engine`             | enum          |                                                                           |
| `acceleration_ceil_1`        | int           |                                                                           |
| `accelaration_ceil_2`        | int           |                                                                           |
| `rating_used`                | enum          |                                                                           |
| `pairings_published`         | bool          |                                                                           |
| `chief_arbiter`              | int           | Fide id ? Faut-il mettre d'autres arbitres ?                              |
| `start`                      | timestamp     |                                                                           |
| `end`                        | timestamp     |                                                                           |
| `tie_break_1`                | enum          | Cf remarque plus bas sur le stockage des départages                       |
| `tie_break_2`                | enum          |                                                                           |
| `tie_break_3`                | enum          |                                                                           |
| `tie_break_4`                | enum          |                                                                           |
| `ffe_id`                     | str           |                                                                           |
| `ffe_password`               | str           |                                                                           |
| `ffe_upload_enabled`         | bool          | true si le téléchargement sur le site fédéral est activé pour le tournoi  |
| `current_round`              | int           |                                                                           |
| `chessevent_connection_id`   | int           | FK(`CHESSEVENT_CONNECTION.id`)                                            |
| `chessevent_tournament_name` | str           |                                                                           |
| `chessevent_update_enabled`  | bool          | true si la mise à jour depuis Chess Event est activée                     |
| `last_then_first_name`       | bool          |                                                                           |
| `last_update`                | timestamp     | Car on ne peut plus s'appuyer sur la date de modification du fichier papi |

Un choix doit être fait pour le stockage des départages (`tie_break_x`) :
- un champ principal `tie_break_x` et des champs annexes pour les paramètres :
  - `tie_break_x_buchholz_virtual_opponents`, 
  - `tie_break_x_buchholz_unplayed_as_draw`, 
  - `tie_break_x_buchholz_cut_bottom`, 
  - `tie_break_x_buchholz_cut_top`, 
  - `tie_break_x_average_rating_exclude_forfeits`, 
  - `tie_break_x_average_rating_cut`, 
  - `tie_break_x_average_rating_unrated_rating`, 
  - `tie_break_x_koya_cutoff_percent`, 
  - `tie_break_x_number_of_wins_exclude_forfeits`, 
  - `tie_break_x_number_of_wins_color`, 
  - `tie_break_x_progressive_cut`, 
  - `tie_break_x_sonneborn_berger_virtual_opponents`, 
  - `tie_break_x_sonneborn_berger_unplayed_as_draw`, 
  - `tie_break_x_sonneborn_berger_cut_bottom`, 
  - `tie_break_x_sonneborn_berger_cut_top`
- un champ principal `tie_break_x` et un champ annexe `tie_break_x_parameters` au format JSON pour les paramètres
- un champ principal `tie_break_x` au format JSON 

### Types de licence FFE (table PLAYER_FFE_STATUS)

| Champ   | Type          | Remarque                  |
|---------|---------------|---------------------------|
| `id`    | autoincrement | PK                        |
| `label` | str not null  |                           |
| `name`  | str not null  | Utile ? l10n-compatible ? |

#### Données pré-remplies

| `id` | `label` | `name`                    |
|------|---------|---------------------------|
| 1    | ``      | ``                        |
| 2    | `N`     | `License non renouvelée`  |
| 3    | `B`     | `License B (loisir)`      |
| 4    | `A`     | `License A (compétition)` |

### Titres des joueur·euses (table PLAYER_TITLE)

| Champ   | Type          | Remarque                  |
|---------|---------------|---------------------------|
| `id`    | autoincrement | PK                        |
| `label` | str not null  |                           |
| `name`  | str not null  | Utile ? l10n-compatible ? |

#### Données pré-remplies

| `id` | `label` | `name`                       |
|------|---------|------------------------------|
| 1    | ``      | ``                           |
| 2    | `WCM`   | `Woman Candidate Master`     |
| 3    | `WFM`   | `Woman Fide Master`          |
| 4    | `CM`    | `Candidate Master`           |
| 5    | `WIM`   | `Woman International Master` |
| 6    | `FM`    | `Fide Master`                |
| 7    | `WGM`   | `Woman Grand Master`         |
| 8    | `IM`    | `International Master`       |
| 9    | `GM`    | `Grand Master`               |

Note : dans l'ordre GM-IM-WGM-FM-WIM-CM-WFM-WCM-none (cf https://handbook.fide.com/chapter/C0402)

### Genres des joueur·euses (table PLAYER_GENDER)

| Champ   | Type          | Remarque                  |
|---------|---------------|---------------------------|
| `id`    | autoincrement | PK                        |
| `label` | str not null  |                           |
| `name`  | str not null  | Utile ? l10n-compatible ? |

#### Données pré-remplies

| `id` | `label` | `name`          |
|------|---------|-----------------|
| 1    | ``      | `Non identifié` |
| 2    | `F`     | `Femme`         |
| 3    | `M`     | `Homme`         |

### Catégories des joueur·euses (table PLAYER_CATEGORY)

| Champ     | Type          | Remarque |
|-----------|---------------|----------|
| `id`      | autoincrement | PK       |
| `label`   | str not null  |          |
| `min_age` | int           |          |
| `max_age` | int           |          |

#### Données pré-remplies

| `id` | `label` | `name`  | `min_age` | `max_age` |
|------|---------|---------|-----------|-----------|
| 1    | ``      | ``      |           |           |
| 2    | `u8`    | `U8`    |           | `7`       |
| 3    | `u10`   | `U8`    | `8`       | `9`       |
| 4    | `u12`   | `U8`    | `10`      | `11`      |
| 5    | `u14`   | `U8`    | `12`      | `13`      |
| 6    | `u16`   | `U8`    | `14`      | `15`      |
| 7    | `u18`   | `U8`    | `16`      | `17`      |
| 8    | `u20`   | `U8`    | `18`      | `19`      |
| 9    | `adult` | `Sen`   | `20`      | `49`      |
| 10   | `o50`   | `Sep`   | `50`      | `64`      |
| 11   | `o65`   | `Vet`   | `65`      |           |

### Niveau de classement des joueur·euses (table PLAYER_RATING_LEVEL)

| Champ     | Type          | Remarque                  |
|-----------|---------------|---------------------------|
| `id`      | autoincrement | PK                        |
| `label`   | str not null  |                           |
| `name`    | str not null  | Utile ? l10n-compatible ? |

#### Données pré-remplies

| `id` | `label` | `name`                |
|------|---------|-----------------------|
| 1    | ``      | `Aucun classement`    |
| 2    | `E`     | `Classement estimé`   |
| 3    | `N`     | `Classement national` |
| 4    | `F`     | `Classement Fide`     |

### Statut des joueur·euses dans le tournoi (table PLAYER_STATUS)

| Champ     | Type          | Remarque                  |
|-----------|---------------|---------------------------|
| `id`      | autoincrement | PK                        |
| `label`   | str not null  |                           |
| `name`    | str not null  | Utile ? l10n-compatible ? |

#### Données pré-remplies

| `id` | `label` | `name`    |
|------|---------|-----------|
| 1    | ``      | ``        |
| 2    | `P`     | `Joue`    |
| 3    | `W`     | `Abandon` |

### Joueur·euses (table PLAYER)

| Champ                | Type          | Remarque                     |
|----------------------|---------------|------------------------------|
| `id`                 | autoincrement | PK                           |
| `tournament_id`      | int not null  | FK(`TOURNAMENT.id`)          |
| `ffe_id`             | int           |                              |
| `ffe_status_id`      | int           | FK(`PLAYER_FFE_STATUS.id`)   |
| `ffe_license_number` | str           | Note : peut être null        |
| `fide_id`            | int           | Note : peut être null        |
| `title_id`           | int not null  | FK(`PLAYER_TITLE.id`)        |
| `last_name`          | str not null  |                              |
| `first_name`         | str           |                              |
| `gender_id`          | int not null  | FK(`PLAYER_GENDER.id`)       |
| `birth`              | int           |                              |
| `category_id`        | int not null  | FK(`PLAYER_CATEGORY.id`)     |
| `s_rating`           | int           | Note : peut être null        |
| `s_rating_level_id`  | int not null  | FK(`PLAYER_RATING_LEVEL.id`) |
| `r_rating`           | int           | Note : peut être null        |
| `r_rating_level_id`  | int not null  | FK(`PLAYER_RATING_LEVEL.id`) |
| `b_rating`           | int           | Note : peut être null        |
| `b_rating_level_id`  | int not null  | FK(`PLAYER_RATING_LEVEL.id`) |
| `federation`         | str           | Note : peut être null        |
| `ffe_league`         | str           |                              |
| `ffe_club_id`        | int           |                              |
| `ffe_club_name`      | str           |                              |
| `check_in`           | bool          |                              |
| `phone`              | str           |                              |
| `mail`               | str           |                              |
| `points`             | float         | Nombre de points total       |
| `standings_points`   | float         | Nombre de points réels       |
| `virtual_points`     | float         | Nombre de points fictifs     |
| `tie_break_1`        | float         |                              |
| `tie_break_2`        | float         |                              |
| `tie_break_3`        | float         |                              |
| `tie_break_4`        | float         |                              |
| `status`             | int not null  | FK(`PLAYER_STATUS_.id`)      |
| `rank`               | int           | Classement                   |
| `board`              | int           | L'échiquier fixe             |

### Ronde (table ROUND)

| Champ            | Type          | Remarque            |
|------------------|---------------|---------------------|
| `id`             | autoincrement | PK                  |
| `tournament_id`  | int not null  | FK(`TOURNAMENT.id`) |
| `date`           | timestamp     |                     |

### Couleur des appariements (table PAIRING_COLOR)

| Champ     | Type          | Remarque                  |
|-----------|---------------|---------------------------|
| `id`      | autoincrement | PK                        |
| `label`   | str not null  |                           |
| `name`    | str not null  | Utile ? l10n-compatible ? |

#### Données pré-remplies

| `id` | `label` | `name`   |
|------|---------|----------|
| 1    | ``      | ``       |
| 2    | `W`     | `Blancs` |
| 3    | `B`     | `Noirs`  |

### Couleur des appariements (table RESULT)

| Champ     | Type          | Remarque                  |
|-----------|---------------|---------------------------|
| `id`      | autoincrement | PK                        |
| `label`   | str not null  |                           |
| `name`    | str not null  | Utile ? l10n-compatible ? |

#### Données pré-remplies

| `id` | `trf` | `name`                         |
|------|-------|--------------------------------|
| 1    | ``    | ``                             |
| 2    | `-`   | `Défaite par forfait`          |
| 3    | `+`   | `Victoire par forfait`         |
| 4    | `W`   | `Victoire (non comptabilisée)` |
| 5    | `D`   | `Nulle (non comptabilisée)`    |
| 6    | `L`   | `Défaite (non comptabilisée)`  |
| 7    | `1`   | `Victoire`                     |
| 8    | `=`   | `Nulle`                        |
| 9    | `0`   | `Défaite`                      |
| 10   | `H`   | `Bye 0,5 point`                |
| 11   | `F`   | `Bye 1 point`                  |
| 12   | `U`   | `Exempt`                       |
| 13   | `Z`   | `Non apparié·e`                |

Une implémentation libre de parser TRF : https://github.com/sklangen/TRF

### Appariement (table PAIRING)

| Champ          | Type          | Remarque               |
|----------------|---------------|------------------------|
| `id`           | autoincrement | PK                     |
| `round_id`     | int not null  | FK(`ROUND.id`)         |
| `player_id`    | int not null  | FK(`PLAYER.id`)        |
| `opponent_id`  | int           | FK(`PLAYER.id`)        |
| `color_id`     | int not null  | FK(`PAIRING_COLOR.id`) |
| `result_id`    | int not null  | FK(`RESULT.id`)        |
| `board_number` | int           |                        |

### Chronomètre (table TIMER)

| Champ         | Type          | Remarque                              |
|---------------|---------------|---------------------------------------|
| `id`          | autoincrement | PK                                    |
| `event_id`    | int not null  | FK(`EVENT.id`)                        |
| `order`       | int           |                                       |
| `name`        | str           | Un entier pour les numéros des rondes |
| `date`        | timestamp     |                                       |
| `text_before` | str           |                                       |
| `text_after`  | str           |                                       |

### Types d'écran (table SCREEN_TYPE)

| Champ     | Type          | Remarque                  |
|-----------|---------------|---------------------------|
| `id`      | autoincrement | PK                        |
| `label`   | str not null  |                           |
| `name`    | str not null  | Utile ? l10n-compatible ? |

#### Données pré-remplies

| `id` | `trf`     | `name`                                |
|------|-----------|---------------------------------------|
| 1    | `boards`  | `Appariements par échiquier`          |
| 2    | `players` | `Appariements par ordre alphabétique` |
| 3    | `results` | `Derniers résultats`                  |

### Types d'écran (table SCREEN_MENU_TYPE)

| Champ     | Type          | Remarque                  |
|-----------|---------------|---------------------------|
| `id`      | autoincrement | PK                        |
| `label`   | str not null  |                           |
| `name`    | str not null  | Utile ? l10n-compatible ? |

#### Données pré-remplies

| `id` | `label`  | `name`                                |
|------|----------|---------------------------------------|
| 1    | `view`   | `Écrans d'affichage des appariements` |
| 2    | `update` | `Écrans de saisie des scores`         |
| 3    | `family` | `Écrans de la famille`                |
| 4    | `list`   | `Liste d'écrans`                      |

### Écrans (table SCREEN)

| Champ                | Type          | Remarque                                              |
|----------------------|---------------|-------------------------------------------------------|
| `id`                 | autoincrement | PK                                                    |
| `screen_id`          | int not null  | FK(`SCREEN.id`)                                       |
| `label`              | str           | Optionnel, pour utilisation dans `menu_screen_labels` |
| `name`               | str           |                                                       |
| `screen_type_id`     | int not null  | FK(`SCREEN_TYPE.id`)                                  |
| `family_id`          | int           | FK(`SCREEN_FAMILY.id`)                                |
| `menu_text`          | str           |                                                       |
| `menu_type_id`       | int not null  | FK(`SCREEN_MENU_TYPE.id`)                             |
| `menu_screen_labels` | str           | Liste de labels d'écran séparés par des virgules      |
| `show_timer`         | bool          |                                                       |
| `boards_update`      | bool          |                                                       |
| `results_columns`    | int not null  |                                                       |
| `results_limit`      | int           |                                                       |

### Parties d'écran (table SCREEN_SET)

| Champ           | Type          | Remarque            |
|-----------------|---------------|---------------------|
| `id`            | autoincrement | PK                  |
| `screen_id`     | int not null  | FK(`SCREEN.id`)     |
| `order`         | int           |                     |
| `name`          | str           |                     |
| `tournament_id` | int not null  | FK(`TOURNAMENT.id`) |
| `columns`       | int not null  |                     |
| `date`          | timestamp     |                     |
| `text_before`   | str           |                     |
| `text_after`    | str           |                     |
| `first`         | int           |                     |
| `last`          | int           |                     |
| `part`          | int           |                     |
| `parts`         | int           |                     |

Note : les structures de données des modèles et des familles méritent d'être revues.

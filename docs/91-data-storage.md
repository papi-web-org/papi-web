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

### Évènement (table INFO)

| Champ            | Type | Remarque                                                                         |
|------------------|------|----------------------------------------------------------------------------------|
| `version`        | int  | Pour permettre la migration des bases de données par l'application au chargement |
| `admin_password` | str  | Le mot de passe d'administration (création et suppression des tournois)          |

### Évènement (table EVENT)

| Champ                     | Type | Remarque                                           |
|---------------------------|------|----------------------------------------------------|
| `id`                      | int  | L'identifiant unique sur la machine                |
| `name`                    | str  |                                                    |
| `update_password`         | str  | Le mot de passe pour entrer les résultats          |
| `edit_password`           | str  | Le mot de passe pour éditer l'évènement            |
| `timer_enabled`           | bool |                                                    |
| `timer_text_before_round` | str  | Le texte du chronomètre avant le début d'une ronde |
| `timer_text_after_round`  | str  | Le texte du chronomètre après le début d'une ronde |
| `ffe_upload`              | bool |                                                    |
| `chessevent_download`     | bool |                                                    |

### ### Connexions à Chess Event (table CHESSEVENT)

| Champ         | Type | Remarque      |
|---------------|------|---------------|
| `id`          | int  |               |
| `event_id`    | int  | \> `EVENT.id` |
| `ce_user_id`  | str  |               |
| `ce_password` | str  |               |
| `ce_event_id` | str  |               |

### Tournoi (table TOURNAMENT)

| Champ                        | Type      | Remarque                                                                 |
|------------------------------|-----------|--------------------------------------------------------------------------|
| `id`                         | int       |                                                                          |
| `event_id`                   | int       | \> `EVENT.id`                                                            |
| `name`                       | str       |                                                                          |
| `time_control_initial_time`  | int       |                                                                          |
| `time_control_increment`     | int       |                                                                          |
| `handicap_penalty_step`      | int       |                                                                          |
| `handicap_penalty_value`     | int       |                                                                          |
| `handicap_min_time`          | int       |                                                                          |
| `rounds`                     | int       |                                                                          |
| `top_seed_start_color`       | enum      | Random, White, Black                                                     |
| `points_paired_bye`          | float     | Points d'exempt                                                          |
| `pairing_engine`             | enum      |                                                                          |
| `acceleration_ceil_1`        | int       |                                                                          |
| `accelaration_ceil_2`        | int       |                                                                          |
| `rating_used`                | enum      |                                                                          |
| `pairings_published`         | bool      |                                                                          |
| `chief_arbiter`              | int       | Fide id ? Faut-il mettre d'autres arbitres ?                             |
| `start`                      | timestamp |                                                                          |
| `end`                        | timestamp |                                                                          |
| `tie_break_1`                | enum      | Cf remarque plus bas sur le stockage des départages                      |
| `tie_break_2`                | enum      |                                                                          |
| `tie_break_3`                | enum      |                                                                          |
| `tie_break_4`                | enum      |                                                                          |
| `ffe_id`                     | str       |                                                                          |
| `ffe_password`               | str       |                                                                          |
| `ffe_upload`                 | bool      | true si le téléchargement sur le site fédéral est activé pour le tournoi |
| `current_round`              | int       |                                                                          |
| `chessevent_connection_id`   | int       | \> CHESSEVENT.id                                                         |
| `chessevent_tournament_name` | str       |                                                                          |
| `chessevent_update`          | bool      | true si la mise à jour depuis Chess Event est activée                    |
| `last_then_first_name`       | bool      |                                                                          |

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

### Joueur·euses (table PLAYER)

| Champ                       | Type  | Remarque                                                         |
|-----------------------------|-------|------------------------------------------------------------------|
| `id`                        | int   |                                                                  |
| `tournament_id`             | int   | \> `TOURNAMENT.id`                                               |
| `ffe_id`                    | int   |                                                                  |
| `ffe_license`               | enum  |                                                                  |
| `ffe_license_number`        | str   |                                                                  |
| `fide_id`                   | int   |                                                                  |
| `title`                     | enum  |                                                                  |
| `last_name`                 | str   |                                                                  |
| `first_name`                | str   |                                                                  |
| `gender`                    | enum  |                                                                  |
| `birth`                     | int   |                                                                  |
| `category`                  | enum  |                                                                  |
| `standard_rating`           | int   |                                                                  |
| `standard_rating_type`      | enum  |                                                                  |
| `rapid_rating`              | int   |                                                                  |
| `rapid_rating_type`         | enum  |                                                                  |
| `blitz_rating`              | int   |                                                                  |
| `blitz_rating_type`         | enum  |                                                                  |
| `federation`                | str   |                                                                  |
| `league`                    | str   |                                                                  |
| `club_id`                   | int   |                                                                  |
| `club_name`                 | str   |                                                                  |
| `check_in`                  | bool  |                                                                  |
| `phone`                     | str   |                                                                  |
| `mail`                      | str   |                                                                  |
| `points`                    | float | Nombre de points total                                           |
| `standings_points`          | float | Nombre de points réels                                           |
| `virtual_points`            | float | Nombre de points fictifs                                         |
| `tie_break_1`               | float |                                                                  |
| `tie_break_2`               | float |                                                                  |
| `tie_break_3`               | float |                                                                  |
| `tie_break_4`               | float |                                                                  |
| `status`                    | enum  | Playing or Withdrawn                                             |
| `rank`                      | int   | Classement                                                       |
| `board`                     | int   | L'échiquier fixe                                                 |
| `maximum player_byes`       | int   | Le nombre maximum de byes pendant le tournoi                     |
| `last_round_no_player_byes` | int   | Le nombre des dernières rondes où les byes ne sont pas autorisés |

### Ronde (table ROUND)

| Champ            | Type      | Remarque                              |
|------------------|-----------|---------------------------------------|
| `id`             | int       |                                       |
| `tournament_id`  | int       | \> `TOURNAMENT.id`                    |
| `date`           | timestamp |                                       |

### Appariement (table PAIRING)

| Champ          | Type | Remarque       |
|----------------|------|----------------|
| `id`           | int  |                |
| `round_id`     | int  | \> `ROUND.id`  |
| `player_id`    | int  | \> `PLAYER.id` |
| `color`        | enum |                |
| `result`       | enum |                |
| `board_number` | int  |                |

### ### Chronomètre (table TIMER)

| Champ         | Type      | Remarque                              |
|---------------|-----------|---------------------------------------|
| `id`          | int       |                                       |
| `event_id`    | int       | \> `EVENT.id`                         |
| `order`       | int       |                                       |
| `name`        | str       | Un entier pour les numéros des rondes |
| `date`        | timestamp |                                       |
| `text_before` | str       |                                       |
| `text_after`  | str       |                                       |


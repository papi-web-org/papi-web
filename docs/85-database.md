**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Annexe technique : Description de la base de données

## Version 2.4.0

> [!NOTE]
> Dans une version future, les joueur·euses seront également stocké·es dans la base de données.

### table `info` (informations générales sur l'évènement)

> [!NOTE]
> - La table `info` ne contient qu'une seule ligne.
> - L'identifiant unique du tournoi n'est pas stocké dans la base de données, il est récupéré par le nom du fichier de la base de données de l'évènement.

| Champ                                     | Type      | Contrainte               | Description                                                                                                                                                                                                                                                           |
|-------------------------------------------|-----------|--------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `version`                                 | `TEXT`    | NOT NULL                 | Le numéro de version de la base de données (`x.y.z`).                                                                                                                                                                                                                 |
| `name`                                    | `TEXT`    | NOT NULL<br> DEFAULT '?' | Le nom de l'évènement.                                                                                                                                                                                                                                                |
| `start`                                   | `FLOAT`   | NOT NULL                 | La date de début de l'évènement (timestamp).                                                                                                                                                                                                                          |
| `stop`                                    | `FLOAT`   | NOT NULL                 | La date de fin de l'évènement (timestamp).                                                                                                                                                                                                                            |
| `public`                                  | `INTEGER` |                          | Booléen :<br/>- `1` : l'évènement est public (visible par les utilisateur·ices sur l'interface publique') ;<br/>- `0` : l'évènement est réservé aux arbitres.                                                                                                         |
| `path`                                    | `TEXT`    |                          | Le chemin, relatif ou absolu, des fichiers Papi des tournois de l'évènement.                                                                                                                                                                                          |
| `update_password`                         | `TEXT`    |                          | Le mot de passe à fournir pour utiliser les écrans de saisie.                                                                                                                                                                                                         |
| `record_illegal_moves`                    | `INTEGER` |                          | Le nombre maximum de coups illégaux que l'on peut enregistrer pour un·e joueur·euse par ronde par défaut (ce nombre peut être modifié pour chaque tournoi de l'évènement). Si ce nombre n'est pas précisé, aucun coup légal ne peut être enregistré (par défaut `0`). |
| `allow_results_deletion_on_input_screens` | `INTEGER` |                          | Booléen :<br/>- `0` : l'évènement est réservé aux arbitres ;<br/>- `1` : l'évènement est public (visible par les utilisateur·ices sur l'interface publique').                                                                                                         |
| `timer_colors`                            | `TEXT`    |                          | Les couleurs utilisées par défaut pour les chronomètres au format JSON (dictionnaire avec les clés `'1'`, `'2'` et `'3'`, chaque couleur est stockée au format hexadécimal '`#RRGGBB`').                                                                              |
| `timer_delays`                            | `TEXT`    |                          | Les délais utilisés par défaut pour les chronomètres au format JSON (dictionnaire avec les clés `'1'`, `'2'` et `'3'`, chaque délai est stocké sous forme d'un entier, en secondes).                                                                                  |
| `last_update`                             | `FLOAT`   | NOT NULL                 | La date de la dernière mise à jour de l'évènement (timestamp).                                                                                                                                                                                                        |

### table `chessevent` (connexions à ChessEvent)

| Champ                | Type      | Contrainte                                 | Description                                                           |
|----------------------|-----------|--------------------------------------------|-----------------------------------------------------------------------|
| `id`                 | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant de la connexion.                                        |
| `uniq_id`            | `TEXT`    | NOT NULL<br>UNIQUE                         | L'identifiant textuel unique de la connexion.                         |
| `user_id`            | `TEXT`    | NOT NULL                                   | L'identifiant utilisé pour le connexion à la plateforme ChessEvent.   |
| `password`           | `TEXT`    | NOT NULL                                   | Le mot de passe utilisé pour le connexion à la plateforme ChessEvent. |
| `event_id`           | `TEXT`    | NOT NULL                                   | L'identifiant de l'évènement ChessEvent sur la plateforme.            |

### table `timer` (chronomètre)

| Champ     | Type      | Contrainte                                 | Description                                                                                                                                             |
|-----------|-----------|--------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`      | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant du chronomètre.                                                                                                                           |
| `uniq_id` | `TEXT`    | NOT NULL<br/>UNIQUE                        | L'identifiant textuel unique du chronomètre.                                                                                                            |
| `colors`  | `TEXT`    |                                            | Les couleurs utilisées au format JSON (dictionnaire avec les clés `'1'`, `'2'` et `'3'`, chaque couleur est stockée au format hexadécimal '`#RRGGBB`'). |
| `delays`  | `TEXT`    |                                            | Les délais utilisés au format JSON (dictionnaire avec les clés `'1'`, `'2'` et `'3'`, chaque délai est stocké sous forme d'un entier, en secondes).     |

### table `timer_hour` (horaires des chronomètres)

| Champ         | Type      | Contrainte                                 | Description                                                                                                                                       |
|---------------|-----------|--------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`          | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant de l'horaire.                                                                                                                       |
| `uniq_id`     | `TEXT`    | NOT NULL                                   | L'identifiant textuel unique de l'horaire (si le champ est un entier positif, l'horaire est identifié comme le début de la ronde correspondante). |
| `timer_id`    | `INTEGER` | NOT NULL<br>REFERENCES `timer`(`id`)       | L'identifiant du chronomètre.                                                                                                                     |
| `order`       | `INTEGER` | NOT NULL                                   | L'ordre de l'horaire vis-à-vis des autres horaires de son chronomètre.                                                                            |
| `date_str`    | `TEXT`    |                                            | La date de l'horaire au format AAAA-MM-JJ.                                                                                                        |
| `time_str`    | `TEXT`    |                                            | L'heure de l'horaire au format hh:mm.                                                                                                             |
| `text_before` | `TEXT`    |                                            | Le texte à afficher sur le chronomètre avant l'horaire.                                                                                           |
| `text_after`  | `TEXT`    |                                            | Le texte à afficher sur le chronomètre après l'horaire.                                                                                           |
|               |           | UNIQUE(`uniq_id`, `timer_id`)              |                                                                                                                                                   |

### table `tournament` (tournois)

| Champ                                 | Type      | Contrainte                                 | Description                                                                                                                                                                             |
|---------------------------------------|-----------|--------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`                                  | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant du tournoi.                                                                                                                                                               |
| `uniq_id`                             | `TEXT`    | NOT NULL                                   | L'identifiant textuel unique du tournoi.                                                                                                                                                |
| `name`                                | `TEXT`    | NOT NULL                                   | Le nom du tournoi.                                                                                                                                                                      |
| `path`                                | `TEXT`    |                                            | Le chemin absolu ou relatif où est stocké le fichier du tournoi.                                                                                                                        |
| `filename`                            | `TEXT`    |                                            | Le nom du fichier Papi du tournoi, sans l'extension `.papi`.                                                                                                                            |
| `ffe_id`                              | `INTEGER` |                                            | Le numéro d'homologation du tournoi sur le site fédéral.                                                                                                                                |
| `ffe_password`                        | `TEXT`    |                                            | Le code d'accès au tournoi sur le site fédéral (composé de 10 lettres majuscules).                                                                                                      |
| `time_control_initial_time`           | `INTEGER` |                                            | Le temps initial à la pendule en secondes (peut être nul si incrément).                                                                                                                 |
| `time_control_increment`              | `INTEGER` |                                            | L'incrément de temps gagné par les joueur·euses à chaque coup.                                                                                                                          |
| `time_control_handical_penalty_step`  | `INTEGER` |                                            | Le temps retranché au·à la joueur·euse le·la mieux classé·e, en secondes (ce temps est multiplié par le nombre de tranches de différence entre les deux joueur·euses).                  |
| `time_control_handical_penalty_value` | `INTEGER` |                                            | Le nombre de points de différences entre le classement des joueurs servant à calculer le nombre de pénalités appliquées au·à la joueur·euse le·la mieux classé·e.                       |
| `time_control_handicap_min_time`      | `INTEGER` |                                            | Le temps minimal qui sera accordé au·à la joueur·euse le·la mieux classé·e même si la différence de classement est très importante.                                                     |
| `chessevent_id`                       | `INTEGER` | REFERENCES `chessevent`(`id`)              | L'identifiant de la connexion à ChessEvent.                                                                                                                                             |
| `chessevent_tournament_name`          | `TEXT`    |                                            | L'identifiant du tournoi sur la plateforme ChessEvent.                                                                                                                                  |
| `record_illegal_moves`                | `INTEGER` |                                            | Le nombre maximum de coups illégaux que l'on peut enregistrer pour un·e joueur·euse par ronde. Si ce nombre n'est pas précisé, la configuration par défaut de l'évènement est utilisée. |
| `last_update`                         | `FLOAT`   | NOT NULL                                   | La date de dernière modification du tournoi.                                                                                                                                            |
| `last_illegal_move_update`            | `FLOAT`   | NOT NULL DEFAULT 0.0                       | La date de dernière modification des coups illégaux du tournoi.                                                                                                                         |
| `last_result_update`                  | `FLOAT`   | NOT NULL DEFAULT 0.0                       | La date de dernière modification d'un résultat du tournoi.                                                                                                                              |
| `last_check_in_update`                | `FLOAT`   | NOT NULL DEFAULT 0.0                       | La date de dernière modification du pointage du tournoi.                                                                                                                                |
| `last_ffe_upload`                     | `FLOAT`   | NOT NULL DEFAULT 0.0                       | La date de dernier envoi du tournoi vers le site fédéral.                                                                                                                               |
| `last_chessevent_download_md5`        | `TEXT`    |                                            | L'empreinte du dernier téléchargement du tournoi depuis la plateforme ChessEvent.                                                                                                       |

### table `illegal_move` (coups illégaux)

| Champ           | Type      | Contrainte                                 | Description                                            |
|-----------------|-----------|--------------------------------------------|--------------------------------------------------------|
| `id`            | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant du coup illégal.                         |
| `tournament_id` | `INTEGER` | NOT NULL<br/>REFERENCES `tournament`(`id`) | L'identifiant du tournoi.                              |
| `round`         | `INTEGER` | NOT NULL                                   | Le numéro de la ronde.                                 |
| `player_id`     | `INTEGER` | NOT NULL                                   | Le numéro du joueur (dans le fichier Papi du tournoi). |
| `date`          | `FLOAT`   | NOT NULL                                   | La date d'enregistrement.                              |

### table `result`

| Champ             | Type      | Contrainte                                 | Description                                                                                                                                                                      |
|-------------------|-----------|--------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`              | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant du résultat.                                                                                                                                                       |
| `tournament_id`   | `INTEGER` | NOT NULL<br/>REFERENCES `tournament`(`id`) | L'identifiant du tournoi.                                                                                                                                                        |
| `round`           | `INTEGER` | NOT NULL                                   | Le numéro de la ronde.                                                                                                                                                           |
| `board_id`        | `INTEGER` | NOT NULL                                   | Le numéro de l'échiquier.                                                                                                                                                        |
| `white_player_id` | `INTEGER` | NOT NULL                                   | Le numéro du joueur avec les Blancs (dans le fichier Papi du tournoi).                                                                                                           |
| `black_player_id` | `INTEGER` | NOT NULL                                   | Le numéro du joueur avec les Noirs (dans le fichier Papi du tournoi).                                                                                                            |
| `date`            | `FLOAT`   | NOT NULL                                   | La date d'enregistrement.                                                                                                                                                        |
| `value`           | `INTEGER` | NOT NULL                                   | Le résultat :<br/>- `1` : gain Noirs<br/>- `2` : nulle<br/>- `3` : gain Blancs<br/>- `4` : gain Noirs par forfait<br/>- `5` : double forfait<br/>- `6` : gain Blancs par forfait |

### table `screen` (écrans)

| Champ                    | Type      | Contrainte                                 | Description                                                                                                                                                                                                                  |
|--------------------------|-----------|--------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`                     | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant de l'écran.                                                                                                                                                                                                    |
| `uniq_id`                | `TEXT`    | NOT NULL<br/>UNIQUE                        | L'identifiant textuel unique de l'écran.                                                                                                                                                                                     |
| `type`                   | `TEXT`    | NOT NULL                                   | Le type d'écran :<br/>- `input` : saisie des résultats<br/>- `boards` : appariements par échiquier<br/>- `players` : appariements par ordre alphabétique<br/>- `results` : derniers résultats<br/>- `image` : image          |
| `public`                 | `INTEGER` |                                            | Booléen :<br/>- `1` : l'écran est public (visible par les utilisateur·ices sur l'interface publique') ;<br/>- `0` : l'écran est réservé aux arbitres.                                                                        |
| `name`                   | `TEXT`    |                                            | Le nom de l'écran.                                                                                                                                                                                                           |
| `columns`                | `INTEGER` |                                            | Le nombre de colonnes de l'écran.                                                                                                                                                                                            |
| `menu_link`              | `INTEGER` |                                            | Booléen :<br/>- `NULL` si `type` est `image` ;<br/>- `1` : un lien vers cet écran pourra être affiché depuis les autres écrans ;<br/>- `0` : aucun lien vers cet écran ne sera jamais affiché.                               |
| `menu_text`              | `TEXT`    |                                            | `NULL` si `type` est `image`, sinon le texte du lien hypertexte vers l'écran, utilisé sur les autres écrans.                                                                                                                 |
| `menu`                   | `TEXT`    |                                            | `NULL` si `type` est `image`, sinon le menu à afficher sur l'écran (liens hypertextes vers d'autres écrans).                                                                                                                 |
| `timer_id`               | `INTEGER` | REFERENCES `timer`(`id`)                   | L'identifiant du chronomètre.                                                                                                                                                                                                |
| `players_show_unpaired`  | `INTEGER` |                                            | Booléen :<br/>- `NULL` si `type` différent de `players` ;<br/>- `0` : les joueur·euses non apparié·es sont caché·es ;<br/>- `0` : les joueur·euses non apparié·es sont montré·es.                                            |
| `results_limit`          | `INTEGER` |                                            | - `NULL` si `type` différent de `results` ;<br/>- `0` : tous les derniers résultats sont montrés ;<br/>- entier positif : le nombre maximum de résultats montrés sur l'écran.                                                |
| `results_tournament_ids` | `TEXT`    |                                            | - `NULL` si `type` différent de `results` ;<br/>- La liste des identifiants des tournois dont on affiche les résultats sur l'écran, au format JSON (si la liste est vide, les résultats de tous les tournois sont affichés). |
| `background_image`       | `TEXT`    |                                            | - `NULL` si `type` différent de `image` ;<br/>- L'URL de l'image à afficher.                                                                                                                                                 |
| `background_color`       | `TEXT`    |                                            | - `NULL` si `type` différent de `image` ;<br/>- La couleur de fond de l'image, au format hexadécimal `#RRGGBB`.                                                                                                              |
| `last_update`            | `FLOAT`   | NOT NULL                                   | La date de dernière modification de l'écran.                                                                                                                                                                                 |

### table `screen_set` (ensembles d'écran)

| Champ                    | Type      | Contrainte                                 | Description                                                                  |
|--------------------------|-----------|--------------------------------------------|------------------------------------------------------------------------------|
| `id`                     | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant de l'écran.                                                    |
| `screen_id`              | `TEXT`    | NOT NULL<br/>REFERENCES `screen`(`id`)     | L'identifiant textuel unique de l'écran.                                     |
| `tournament_id`          | `TEXT`    | NOT NULL<br/>REFERENCES `tournament`(`id`) | L'identifiant du tournoi.                                                    |
| `name`                   | `TEXT`    |                                            | Le nom de l'ensemble.                                                        |
| `order`                  | `INTEGER` | NOT NULL                                   | L'ordre de l'ensemble vis-à-vis des autres ensembles de son écran.           |
| `first`                  | `INTEGER` |                                            | Le numéro du premier élément (échiquier ou joueur·euse) à prendre en compte. |
| `last`                   | `INTEGER` |                                            | Le numéro du dernier élément (échiquier ou joueur·euse) à prendre en compte. |
| `fixed_boards_str`       | `TEXT`    |                                            | Des numéros d'échiquiers séparés par des virgules.                           |
| `last_update`            | `FLOAT`   | NOT NULL                                   | La date de dernière modification de l'ensemble.                              |

### table `family` (familles d'écrans)

| Champ                   | Type      | Contrainte                                 | Description                                                                                                                                                                                                         |
|-------------------------|-----------|--------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`                    | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant de la famille.                                                                                                                                                                                        |
| `uniq_id`               | `TEXT`    | NOT NULL<br/>UNIQUE                        | L'identifiant textuel unique de la famille.                                                                                                                                                                         |
| `type`                  | `TEXT`    | NOT NULL                                   | Le type d'écran :<br/>- `input` : saisie des résultats<br/>- `boards` : appariements par échiquier<br/>- `players` : appariements par ordre alphabétique<br/>- `results` : derniers résultats<br/>- `image` : image |
| `public`                | `INTEGER` |                                            | Booléen :<br/>- `1` : la famille est publique (visible par les utilisateur·ices sur l'interface publique') ;<br/>- `0` : la famille est réservés aux arbitres.                                                      |
| `name`                  | `TEXT`    |                                            | Le nom de la famille.                                                                                                                                                                                               |
| `columns`               | `INTEGER` |                                            | Le nombre de colonnes des écrans de la famille.                                                                                                                                                                     |
| `menu_link`             | `INTEGER` | NOT NULL                                   | Booléen :<br/>- `1` : un lien vers les écrans de la famille pourra être affiché depuis les autres écrans ;<br/>- `0` : aucun lien vers les écrans de la famille ne sera jamais affiché.                             |
| `menu_text`             | `TEXT`    | NOT NULL                                   | Le texte du lien hypertexte vers les écrans de la famille, utilisé sur les autres écrans.                                                                                                                           |
| `menu`                  | `TEXT`    | NOT NULL                                   | Le menu à afficher sur les écrans de la famille (liens hypertextes vers d'autres écrans).                                                                                                                           |
| `timer_id`              | `INTEGER` | REFERENCES `timer`(`id`)                   | L'identifiant du chronomètre utilisé sur les écrans de la famille.                                                                                                                                                  |
| `players_show_unpaired` | `INTEGER` |                                            | Booléen :<br/>- `NULL` si `type` différent de `players` ;<br/>- `0` : les joueur·euses non apparié·es sont caché·es ;<br/>- `0` : les joueur·euses non apparié·es sont montré·es.                                   |
| `first`                 | `INTEGER` |                                            | Le numéro du premier élément (échiquier ou joueur·euse) à prendre en compte.                                                                                                                                        |
| `last`                  | `INTEGER` |                                            | Le numéro du dernier élément (échiquier ou joueur·euse) à prendre en compte.                                                                                                                                        |
| `range`                 | `TEXT`    |                                            | La plage d'écrans à générer, par exemple `4-6` (par défaut tous les écrans de la famille sont générés).                                                                                                             |
| `parts`                 | `INTEGER` |                                            | Le nombre d'écrans de la famille (le nombre d'éléments par écran est calculé automatiquement).                                                                                                                      |
| `number`                | `INTEGER` |                                            | Le nombre d'éléments (échiquiers ou joueur·euses) par écran (le nombre d'écrans est calculé automatiquement).                                                                                                       |
| `last_update`           | `FLOAT`   | NOT NULL                                   | La date de dernière modification de l'écran.                                                                                                                                                                        |

### table `rotator` (écrans rotatifs)

| Champ                   | Type      | Contrainte                                 | Description                                                                                                                                                                       |
|-------------------------|-----------|--------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`                    | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant de l'écran rotatif'.                                                                                                                                                |
| `uniq_id`               | `TEXT`    | NOT NULL<br/>UNIQUE                        | L'identifiant textuel unique de l'écran rotatif.                                                                                                                                  |
| `public`                | `INTEGER` |                                            | Booléen :<br/>- `1` : l'écran rotatif est public (visible par les utilisateur·ices sur l'interface publique') ;<br/>- `0` : l'écran rotatif est réservé aux arbitres.             |
| `screen_ids`            | `TEXT`    |                                            | La liste des écrans à afficher, au format JSON.                                                                                                                                   |
| `family_ids`            | `TEXT`    |                                            | La liste des familles d'écrans à afficher, au format JSON.                                                                                                                        |
| `delay`                 | `INTEGER` |                                            | Le délai de rotation des écrans en secondes, facultatif (par défaut 15).                                                                                                          |
| `show_menus`            | `INTEGER` |                                            | Booléen :<br/>- `1` : les menus des écrans sont affichés ;<br/>- `0` : les menus des écrans ne sont pas affichés (par défaut).                                                    |

### table `skipped_round` (forfaits et byes)

| Champ              | Type      | Contrainte                                 | Description                                                                     |
|--------------------|-----------|--------------------------------------------|---------------------------------------------------------------------------------|
| `id`               | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant.                                                                  |
| `tournament_id`    | `TEXT`    | NOT NULL<br/>REFERENCES `tournament`(`id`) | L'identifiant du tournoi.                                                       |
| `round`            | `INTEGER` | NOT NULL                                   | Le numéro de la ronde.                                                          |
| `papi_player_id`   | `INTEGER` | NOT NULL                                   | Lu numéro du·de la joueur·euse dans le fichier Papi.                            |
| `score`            | `FLOAT`   | NOT NULL                                   | Le score :<br/>- `0` : forfait ;<br/>- `0.5` : bye ;<br/>- `1`: bye à un point. |

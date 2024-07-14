**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Annexe technique : Description de la base de données

## Version 2.4.0

> [!NOTE]
> Dans une version future, les joueur·euses seront également stocké·es dans la base de données.

### table `info`

> [!NOTE]
> La table `info` ne contient qu'une seule ligne.

| Champ     | Type    | Contrainte | Description                                           |
|-----------|---------|------------|-------------------------------------------------------|
| `version` | `TEXT`  | NOT NULL   | Le numéro de version de la base de données (`x.y.z`). |

### table `tournament`

| Champ         | Type      | Contrainte                                 | Description                                                                                                                                 |
|---------------|-----------|--------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------|
| `id`          | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant unique.                                                                                                                       |
| `label`       | `TEXT`    | NOT NULL                                   | L'identifiant textuel du tournoi (tel que déclaré dans le fichier de configuration de l'évènement).                                         |
| `last_update` | `FLOAT`   | NOT NULL                                   | La date de dernière modification du tournoi (dans cette version, correspond à l'ajout ou la suppression d'un coup illégal ou d'un résultat. |

### table `illegal_move`

| Champ           | Type      | Contrainte                                 | Description                                                                                        |
|-----------------|-----------|--------------------------------------------|----------------------------------------------------------------------------------------------------|
| `id`            | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant unique.                                                                              |
| `tournament_id` | `INTEGER` | NOT NULL                                   | L'identifiant unique du tournoi (tel que déclaré dans le fichier de configuration de l'évènement). |
| `round`         | `INTEGER` | NOT NULL                                   | Le numéro de la ronde.                                                                             |
| `player_id`     | `INTEGER` | NOT NULL                                   | Le numéro du joueur (dans le fichier Papi du tournoi).                                             |
| `date`          | `FLOAT`   | NOT NULL                                   | La date d'enregistrement.                                                                          |

### table `result`

| Champ             | Type      | Contrainte                                 | Description                                                                                                                                                                      |
|-------------------|-----------|--------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`              | `INTEGER` | NOT NULL<br/>PRIMARY KEY<br/>AUTOINCREMENT | L'identifiant unique.                                                                                                                                                            |
| `tournament_id`   | `TEXT`    | NOT NULL                                   | L'identifiant unique du tournoi (tel que déclaré dans le fichier de configuration de l'évènement).                                                                               |
| `round`           | `INTEGER` | NOT NULL                                   | Le numéro de la ronde.                                                                                                                                                           |
| `board_id`        | `INTEGER` | NOT NULL                                   | Le numéro de l'échiquier.                                                                                                                                                        |
| `white_player_id` | `INTEGER` | NOT NULL                                   | Le numéro du joueur avec les Blancs (dans le fichier Papi du tournoi).                                                                                                           |
| `black_player_id` | `INTEGER` | NOT NULL                                   | Le numéro du joueur avec les Noirs (dans le fichier Papi du tournoi).                                                                                                            |
| `date`            | `FLOAT`   | NOT NULL                                   | La date d'enregistrement.                                                                                                                                                        |
| `value`           | `INTEGER` | NOT NULL                                   | Le résultat :<br/>- `1` : gain Noirs<br/>- `2` : nulle<br/>- `3` : gain Blancs<br/>- `4` : gain Noirs par forfait<br/>- `5` : double forfait<br/>- `6` : gain Blancs par forfait |

**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Téléchargement des fichiers Papi depuis la plateforme d'inscription Chess Event

## Généralités

Chess Event est une plateforme d'inscription aux évènements échiquéens développée par Dominique RUHLMANN et hébergée par la Ligue de Bretagne des Échecs :

- [Accéder à la plateforme Chess Event](https://services.breizh-chess-online.fr/chessevent)

La version 2.1 de Papi-web permettra le téléchargement des fichiers Papi directement depuis la plateforme Chess Event. 

## Fonctionnement

### Utilisation

Le téléchargement se fera en appelant un nouveau script chessevent.bat.

Une confirmation devra être demandée à l'utilisateur·trice pour limiter les risques d'écrasement de fichiers déjà existants en cours de tournoi.

### Authentification

Le téléchargement se fera sur authentification pour limiter la diffusion des coordonnées des joueur·euses (adresses mél et numéros de téléphone).

Les identifiants utilisés seront ceux de la plateforme Chess Event, ils seront déclarés dans le fichier de configuration des évènements dans une nouvelle rubrique `[chessevent]`.

| Option     | Description                                                                      |
|------------|----------------------------------------------------------------------------------|
| `user_id`  | L'identifiant FFE de l'utilisateur·trice (de la forme XNNNNN, obligatoire).      |
| `password` | Le mot de passe l'utilisateur·trice sur la plateforme Chess Event (obligatoire). |

### Désignation d'un évènement sur la plateforme Chess Event

L'identifiant de l'évènement sur la plateforme Chess Event sera également indiqué dans la rubrique `[chessevent]` :

| Option          | Description                                                 |
|-----------------|-------------------------------------------------------------|
| `chessevent_id` | L'identifiant de l'évènement sur la plateforme Chess Event. |

### Désignation de l'évènement Chess Event

L'identifiant d'un évènement sur la plateforme Chess Event sera également indiqué dans la déclaration du tournoi (rubrique `[tournament]` ou `[tournament.<tournament_id>]`) :

| Option          | Description                                                 |
|-----------------|-------------------------------------------------------------|
| `chessevent_id` | L'identifiant de l'évènement sur la plateforme Chess Event. |

## Requêtes de téléchargement

### URL

L'URL de la requête sera https://services.breizh-chess-online.fr/chessevent/download.

### Paramètres

Tous les paramètres seront passés en clair dans le corps de la requête HTTPS sous la forme de paramètres (méthode POST).

| Paramètre       | Description                                                                      |
|-----------------|----------------------------------------------------------------------------------|
| `user_id`       | L'identifiant FFE de l'utilisateur·trice (de la forme XNNNNN, obligatoire).      |
| `password`      | Le mot de passe l'utilisateur·trice sur la plateforme Chess Event (obligatoire). |
| `event_id`      | L'identifiant de l'évènement sur la plateforme Chess Event.                      |
| `tournament_id` | L'identifiant du tournoi sur la plateforme Chess Event.                          |

## Données attendues

Les données attendues sont un dictionnaire au format JSON dans le corps de la réponse à la requête.

| Champ          | Type        | Description                                    |
|----------------|-------------|------------------------------------------------|
| `name`         | `str`       | Le nom.                                        |
| `type`         | `enum`      | Le type (énumération plus bas).                |
| `rounds`       | `int`       | Le nombre de rondes.                           |
| `pairing`      | `enum`      | L'appariement (énumération plus bas).          |
| `time_control` | `str`       | La cadence.                                    |
| `location`     | `str`       | Le lieu.                                       |
| `arbiter`      | `str`       | L'arbitre.                                     |
| `start`        | `timestamp` | La date de début.                              |
| `end`          | `timestamp` | La date de fin.                                |
| `tie_break_1`  | `enum`      | Le premier départage (énumération plus bas).   |
| `tie_break_2`  | `enum`      | Le deuxième départage (énumération plus bas).  |
| `tie_break_3`  | `enum`      | Le troisième départage (énumération plus bas). |
| `ratings`      | `enum`      | Le classement utilisé (énumération plus bas).  |
| `players`      | `dict`      | Les joueur·euses (détails plus bas).           |

### Énumération des types de tournoi

| Numéro | Type de tournoi |
|--------|-----------------|
| `1`    | Suisse          |
| `2`    | Toutes rondes   |

### Énumération des appariements

| Numéro | Appariement     |
|--------|-----------------|
| `1`    | Standard        |
| `2`    | Haley           |
| `3`    | Haley dégressif |
| `4`    | SAD             |
| `5`    | Accéléré niçois |
| `6`    | Berger          |

### Énumération des départages

| Numéro | Départage           |
|--------|---------------------|
| `0`    | _aucun départage_   |
| `1`    | Buchholz            |
| `2`    | Buchholz Tronqué    |
| `3`    | Buchholz Médian     |
| `4`    | Cumulatif           |
| `5`    | Performance         |
| `6`    | Somme des Buchholz  |
| `7`    | Nombre de victoires |
| `8`    | Kashdan             |
| `9`    | Koya                |
| `10`   | Sonnenborn-Berger   |

### Description des joueur·euses

| Champ                  | Type        | Description                                            |
|------------------------|-------------|--------------------------------------------------------|
| `last_name`            | `str`       | Le nom de famille.                                     |
| `first_name`           | `str`       | Le prénom.                                             |
| `ffe_id`               | `str`       | Le numéro de licence FFE (au format XNNNNN).           |
| `fide_id`              | `int`       | L'identifiant Fide.                                    |
| `gender`               | `enum`      | Le genre (énumération plus bas).                       |
| `birth`                | `timestamp` | La date de naissance.                                  |
| `category`             | `enum`      | La catégorie.                                          |
| `standard_rating`      | `int`       | Le classement standard.                                |
| `standard_rating_type` | `enum`      | Le type de classement standard (énumération plus bas). |
| `rapid_rating`         | `int`       | Le classement rapide.                                  |
| `rapid_rating_type`    | `enum`      | Le type de classement rapide (énumération plus bas).   |
| `blitz_rating`         | `int`       | Le classement blitz.                                   |
| `blitz_rating_type`    | `enum`      | Le type de classement blitz (énumération plus bas).    |
| `title`                | `enum`      | Le titre.                                              |
| `license`              | `enum`      | La licence (énumération plus bas).                     |
| `federation`           | `str`       | Le code de la fédération (FED).                        |
| `league`               | `str`       | Le code de la ligue (LIG).                             |
| `club`                 | `str`       | Le club.                                               |
| `email`                | `str`       | L'adresse électronique'.                               |
| `phone`                | `str`       | Le numéro de téléphone.                                |
| `fee`                  | `float`     | Le montant de l'inscription.                           |
| `paid`                 | `float`     | La somme réglée.                                       |
| `check_in`             | `bool`      | `true` si le·la joueur·euse a pointé, `false` sinon.   |

### Énumération des genres

| Numéro | Genre               |
|--------|---------------------|
| `F`    | Féminin             |
| `M`    | Masculin            |

### Énumération des catégories

| Numéro | Catégorie |
|--------|-----------|
| `1`    | U8 (Ppo)  |
| `2`    | U10 (Pou) |
| `3`    | U12 (Pup) |
| `4`    | U14 (Ben) |
| `5`    | U16 (Min) |
| `6`    | U18 (Cad) |
| `7`    | U20 (Jun) |
| `8`    | Sen       |
| `9`    | Sep       |
| `10`   | Vet       |

### Énumération des types de classement

| Numéro | Type de classement |
|--------|--------------------|
| `F`    | Fide               |
| `N`    | National           |
| `E`    | Estime             |

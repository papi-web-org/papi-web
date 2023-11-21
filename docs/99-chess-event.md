**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Création des fichiers Papi depuis la plateforme d'inscription Chess Event

## Généralités

Chess Event est une plateforme d'inscription aux évènements échiquéens développée par Dominique RUHLMANN et hébergée par la Ligue de Bretagne des Échecs :

- [Accéder à la plateforme Chess Event](https://services.breizh-chess-online.fr/chessevent)

La version 2.1 de Papi-web permettra la création des fichiers Papi directement à partir des données de la plateforme Chess Event. 

## Fonctionnement

### Utilisation

Le téléchargement se fait en appelant un nouveau script chessevent.bat.

Une confirmation est demandée à l'utilisateur·trice pour limiter les risques d'écrasement de fichiers déjà existants en cours de tournoi.

### Authentification

Le téléchargement se fait sur authentification pour limiter la diffusion des coordonnées des joueur·euses (adresses mél et numéros de téléphone).

Les identifiants utilisés pour l'authentification sur la plateforme Chess Event sont ceux de la plateforme Chess Event, ils sont déclarés dans le fichier de configuration des évènements dans une nouvelle rubrique `[chessevent]`.

| Option     | Description                                                                                              |
|------------|----------------------------------------------------------------------------------------------------------|
| `user_id`  | L'identifiant FFE de l'utilisateur·trice sur la plateforme Chess Event (de la forme XNNNNN, facultatif). |
| `password` | Le mot de passe l'utilisateur·trice sur la plateforme Chess Event (facultatif).                          |

Ces valeurs sont utilisées par défaut pour tous les tournois de l'évènement Papi-web et peuvent être surchargées au niveau de chaque tournoi (options `chessevent_user_id` et `chessevent_password`).

### Désignation d'un évènement sur la plateforme Chess Event

L'identifiant de l'évènement sur la plateforme Chess Event sera également indiqué dans la rubrique `[chessevent]` :

| Option      | Description                                                 |
|-------------|-------------------------------------------------------------|
| `event_id`  | L'identifiant de l'évènement sur la plateforme Chess Event. |

Cette valeur est utilisée par défaut pour tous les tournois de l'évènement Papi-web et peut être surchargée au niveau de chaque tournoi (option `chessevent_event_id`).

### Désignation d'un tournoi Chess Event

L'identifiant d'un tournoi sur la plateforme Chess Event sera indiqué dans la déclaration du tournoi (rubrique `[tournament]` ou `[tournament.<tournament_id>]`) :

| Option                     | Description                                                              |
|----------------------------|--------------------------------------------------------------------------|
| `chessevent_tournament_id` | L'identifiant de l'évènement sur la plateforme Chess Event (facultatif). |

Comme indiqué précédemment, les valeurs des options de la rubrique `[chessevent]` peuvent être surchargées pour chaque tournoi : 

| Option                | Description                                                                                                                                                    |
|-----------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `chessevent_user_id`  | L'identifiant FFE de l'utilisateur·trice sur la plateforme Chess Event (de la forme XNNNNN, facultatif, valeur définie par défaut par `[chessevent].user_id`). |
| `chessevent_password` | Le mot de passe l'utilisateur·trice sur la plateforme Chess Event (facultatif, valeur définie par défaut par `[chessevent].password`).                         |
| `chessevent_event_id` | L'identifiant de l'évènement sur la plateforme Chess Event (facultatif, valeur définie par défaut par `[chessevent].event_id`).                                |

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
| `rating`       | `enum`      | Le classement utilisé (énumération plus bas).  |
| `players`      | `list`      | Les joueur·euses (détails plus bas).           |

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

| Numéro | Genre    |
|--------|----------|
| `0`    | _aucun_  |
| `1`    | Féminin  |
| `2`    | Masculin |

### Énumération des catégories

| Numéro | Catégorie |
|--------|-----------|
| `0`    | _aucune_  |
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
| `0`    | _aucun_            |
| `1`    | Estimé             |
| `2`    | National           |
| `3`    | Fide               |

### Énumération des licences

| Lettre | Licence                |
|--------|------------------------|
| `0`    | _aucune_               |
| `1`    | Licence non renouvelée |
| `2`    | Licence B              |
| `3`    | Licence 3              |

## Codes d'erreur

En cas d'erreur, la réponse au format JSON ne contient qu'un champ `error: str` qui précise l'erreur rencontrée. 

Les codes d'erreur suivants sont utilisés :

| Statut HTTP | Signification                                                                             | Champ `error`          |
|-------------|-------------------------------------------------------------------------------------------|------------------------|
| 200         | _succès_                                                                                  |                        |
| 401         | Problème d'authentification (impossibilité de s'identifier sur la plateforme Chess Event) | `Unauthorized`         |
| 403         | Problème d'autorisation (identifiants non autorisés pour l'évènement demandé)             | `Access forbidden`     |
| 498         | Tournoi non trouvé                                                                        | `Tournament not found` |
| 499         | Évènement non trouvé                                                                      | `Event not found`      |
| 500         | Autres erreurs                                                                            | À préciser             |

Le script de création des fichiers Papi devra également gérer les problèmes d'accès à l'URL de requête.

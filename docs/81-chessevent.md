**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Annexe technique : interfaçage avec Chess Event

La configuration de Papi-web pour l'accès à la plateforme Chess Event est décrite dans la documentation utilisateur :

- [Création des fichiers Papi des tournois à partir de la plateforme d'inscription en ligne Chess Event](37-chessevent.md)

Cette page en décrit les aspects techniques.

### Authentification

Le téléchargement se fait sur authentification pour limiter la diffusion des coordonnées des joueur·euses (adresses mél et numéros de téléphone).

Les identifiants utilisés pour l'authentification sont ceux de la plateforme Chess Event (administrateur, utilisateur ou gestionnaire d'évènement).

| Option     | Description                                                                                              |
|------------|----------------------------------------------------------------------------------------------------------|
| `user_id`  | L'identifiant FFE de l'utilisateur·trice sur la plateforme Chess Event (de la forme XNNNNN, facultatif). |
| `password` | Le mot de passe l'utilisateur·trice sur la plateforme Chess Event (facultatif).                          |

Ces valeurs sont utilisées pour tous les tournois de l'évènement Papi-web.

### Désignation d'un évènement sur la plateforme Chess Event

L'identifiant de l'évènement sur la plateforme Chess Event est également indiqué dans la rubrique `[chessevent]` :

| Option      | Description                                                 |
|-------------|-------------------------------------------------------------|
| `event_id`  | L'identifiant de l'évènement sur la plateforme Chess Event. |

Cette valeur est utilisée pour tous les tournois de l'évènement Papi-web.

### Désignation d'un tournoi Chess Event

Le nom du tournoi sur la plateforme Chess Event est indiqué dans la déclaration du tournoi (rubrique `[tournament.<tournament_id>]` ou `[tournament]` s'il n'y a qu'un seul tournoi) :

| Option                       | Description                                                   |
|------------------------------|---------------------------------------------------------------|
| `chessevent_tournament_name` | Le nom du tournoi sur la plateforme Chess Event (facultatif). |

## Requêtes de téléchargement

### URL

L'URL de la requête sera https://services.breizh-chess-online.fr/chessevent/download.

### Paramètres

Tous les paramètres seront passés en clair dans le corps de la requête HTTPS sous la forme de paramètres (méthode POST).

| Paramètre         | Description                                                                      |
|-------------------|----------------------------------------------------------------------------------|
| `user_id`         | L'identifiant FFE de l'utilisateur·trice (de la forme XNNNNN, obligatoire).      |
| `password`        | Le mot de passe l'utilisateur·trice sur la plateforme Chess Event (obligatoire). |
| `event_id`        | L'identifiant de l'évènement sur la plateforme Chess Event.                      |
| `tournament_name` | Le nom du tournoi sur la plateforme Chess Event.                                 |

Exemple de paramètres :
```
- user_id=C69548
- password=my-password
- event_id=BRE_35_domloupfide36
- tournament_name=Tournoi A
```

## Données attendues

### Description des tournois

Les données sont attendues sous la forme d'un dictionnaire au format JSON (`Content-Type: application/json`).

| Champ                                       | Type        | Description                                                                                                                                                                                                                                                                             |
|---------------------------------------------|-------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `name`                                      | `str`       | Le nom.                                                                                                                                                                                                                                                                                 |
| `type`                                      | `enum`      | Le type :<br/>`1` = Suisse<br/>`2` = Toutes rondes                                                                                                                                                                                                                                      |
| `rounds`                                    | `int`       | Le nombre de rondes.                                                                                                                                                                                                                                                                    |
| `pairing`                                   | `enum`      | L'appariement :<br/>`1` = Standard<br/>`2` = Haley<br/>`3` = Haley dégressif<br/>`4` = SAD<br/>`5` = Accéléré niçois<br/>`6` = Berger<br/>                                                                                                                                              |
| `time_control`                              | `str`       | La cadence.                                                                                                                                                                                                                                                                             |
| `location`                                  | `str`       | Le lieu.                                                                                                                                                                                                                                                                                |
| `arbiter`                                   | `str`       | L'arbitre.                                                                                                                                                                                                                                                                              |
| `start`                                     | `timestamp` | La date de début.                                                                                                                                                                                                                                                                       |
| `end`                                       | `timestamp` | La date de fin.                                                                                                                                                                                                                                                                         |
| `tie_break_1`, `tie_break_2`, `tie_break_3` | `enum`      | Les départages :<br/>`0` = _aucun départage_<br/>`1` = Buchholz<br/>`2` = Buchholz Tronqué<br/>`3` = Buchholz Médian<br/>`4` = Cumulatif<br/>`5` = Performance<br/>`6` = Somme des Buchholz<br/>`7` = Nombre de victoires<br/>`8` = Kashdan<br/>`9` = Koya<br/>`10` = Sonnenborn-Berger |
| `rating`                                    | `enum`      | Le classement utilisé :<br/>`1` = Standard<br/>`2` = Rapide<br/>`3` = Blitz                                                                                                                                                                                                             |
| `players`                                   | `list`      | La liste des joueur·euses (détails plus bas).                                                                                                                                                                                                                                           |

Exemple de tournoi :

`{`<br/>
&nbsp;&nbsp;`'name': '36e open Fide de Domloup',`<br/>
&nbsp;&nbsp;`'type': 1,`  # Suisse<br/>
&nbsp;&nbsp;`'rounds': 5,`<br/> 
&nbsp;&nbsp;`'pairing': 1,`  # Standard<br/> 
&nbsp;&nbsp;`'time_control': 'G3600 + 30',`<br/> 
&nbsp;&nbsp;`'location': 'Domloup',`<br/> 
&nbsp;&nbsp;`'arbiter': 'AUBRY Pascal C69548',`<br/> 
&nbsp;&nbsp;`'start': 1708767000,`  # 2024-02-24 09:30<br/> 
&nbsp;&nbsp;`'end': 1708880400,`  # 2024-02-25 17:00<br/> 
&nbsp;&nbsp;`'tie_break_1': 2,`  # Buchholz tronqué<br/> 
&nbsp;&nbsp;`'tie_break_2': 3,`  # Buchholz médian<br/> 
&nbsp;&nbsp;`'tie_break_3': 5,`  # Performance<br/> 
&nbsp;&nbsp;`'rating': 1,`  # Standard<br/> 
&nbsp;&nbsp;`'players': [`<br/> 
&nbsp;&nbsp;&nbsp;&nbsp;`...`<br/> 
&nbsp;&nbsp;`],`<br/> 
`}`

### Description des joueur·euses

| Champ                  | Type        | Description                                                                                                                                                                                                             |
|------------------------|-------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `last_name`            | `str`       | Le nom de famille.                                                                                                                                                                                                      |
| `first_name`           | `str`       | Le prénom.                                                                                                                                                                                                              |
| `gender`               | `enum`      | Le genre :<br/>`0` = _aucun_<br/>`1` = Féminin<br/>`2` = Masculin                                                                                                                                                       |
| `birth`                | `timestamp` | La date de naissance.                                                                                                                                                                                                   |
| `federation`           | `str`       | Le code de la fédération (FED).                                                                                                                                                                                         |
| `fide_id`              | `int`       | L'identifiant Fide.                                                                                                                                                                                                     |
| `ffe_id`               | `str`       | L'identifiant FFE (champ RefFFE dans Papi).                                                                                                                                                                             |
| `ffe_license`          | `enum`      | La licence :<br/>`0` = _aucune_<br/>`1` = Licence non renouvelée (N)<br/>`2` = Licence B<br/>`3` = Licence A                                                                                                            |
| `ffe_licence_number`   | `str`       | Le numéro de licence FFE (champ NrFFE dans Papi, au format XNNNNN).                                                                                                                                                     |
| `ffe_league`           | `str`       | Le code de la ligue (LIG).                                                                                                                                                                                              |
| `ffe_club_id`          | `int`       | Le numéro d'identifiant du club.                                                                                                                                                                                        |
| `ffe_club`             | `str`       | Le club.                                                                                                                                                                                                                |
| `category`             | `enum`      | La catégorie :<br/>`0` = _aucune_<br/>`1` = U8 (Ppo)<br/>`2` = U10 (Pou)<br/>`3` = U12 (Pup)<br/>`4` = U14 (Ben)<br/>`5` = U16 (Min)<br/>`6` = U18 (Cad)<br/>`7` = U20 (Jun)<br/>`8` = Sen<br/>`9` = Sep<br/>`10` = Vet |
| `standard_rating`      | `int`       | Le classement standard.                                                                                                                                                                                                 |
| `standard_rating_type` | `enum`      | Le type de classement standard :<br/>`1` = Estimé<br/>`2` = National<br/>`3` = Fide                                                                                                                                     |
| `rapid_rating`         | `int`       | Le classement rapide.                                                                                                                                                                                                   |
| `rapid_rating_type`    | `enum`      | Le type de classement rapide (cf `standard_rating_type`).                                                                                                                                                               |
| `blitz_rating`         | `int`       | Le classement blitz.                                                                                                                                                                                                    |
| `blitz_rating_type`    | `enum`      | Le type de classement blitz (cf `standard_rating_type`).                                                                                                                                                                |
| `title`                | `enum`      | Le titre :<br/>`0` = _aucun_<br/>`1` = Maître Fide féminin<br/>`2` = Maître Fide<br/>`3` = Maître International féminin<br/>`4` = Maître International<br/>`5` = Grand Maître féminin<br/>`6` = Grand Maître            |
| `email`                | `str`       | L'adresse électronique'.                                                                                                                                                                                                |
| `phone`                | `str`       | Le numéro de téléphone.                                                                                                                                                                                                 |
| `fee`                  | `float`     | Le montant de l'inscription.                                                                                                                                                                                            |
| `paid`                 | `float`     | La somme réglée.                                                                                                                                                                                                        |
| `check_in`             | `bool`      | `true` si le·la joueur·euse a pointé, `false` sinon.                                                                                                                                                                    |
| `board`                | `int`       | Un numéro d'échiquier fixe, `0` sinon.                                                                                                                                                                                  |
| `skipped_rounds`       | `dict`      | Un dictionnaire avec pour clé les rondes non journées et pour valeur les points marqués `0.0` si forfait, `0.5` ou `1.0` si points joker.                                                                               |

Exemple de joueur·euse :

`{`<br/>
&nbsp;&nbsp;`'last_name': 'AUBRY',`<br/>
&nbsp;&nbsp;`'first_name': 'Pascal',`<br/>
&nbsp;&nbsp;`'ffe_id': 'C69548',`<br/>
&nbsp;&nbsp;`'fide_id': 20671806,`<br/>
&nbsp;&nbsp;`'gender': 2,`<br/>
&nbsp;&nbsp;`'birth': -41990400,`  # 1968-09-02<br/>
&nbsp;&nbsp;`'category': 9,`  # Sep<br/>
&nbsp;&nbsp;`'standard_rating': 1458,`<br/>
&nbsp;&nbsp;`'standard_rating_type': 3,`  # F<br/>
&nbsp;&nbsp;`'rapid_rating': 1440,`<br/>
&nbsp;&nbsp;`'rapid_rating_type': 3,`  # F<br/>
&nbsp;&nbsp;`'blitz_rating': 1440,`<br/>
&nbsp;&nbsp;`'blitz_rating_type': 1,`  # E<br/>
&nbsp;&nbsp;`'title': 0,`<br/>
&nbsp;&nbsp;`'license': 3,  # A`<br/>
&nbsp;&nbsp;`'federation': 'FRA',`<br/>
&nbsp;&nbsp;`'league': 'BRE',`<br/>
&nbsp;&nbsp;`'club_id': 1918,`<br/>
&nbsp;&nbsp;`'club': 'Echiquier Domloupéen',`<br/>
&nbsp;&nbsp;`'email': 'pascal.aubry@echecs35.fr',`<br/>
&nbsp;&nbsp;`'phone': '0677939521',`<br/>
&nbsp;&nbsp;`'fee': 25.0,`<br/>
&nbsp;&nbsp;`'paid': 25.0,`<br/>
&nbsp;&nbsp;`'check_in': true,`<br/>
&nbsp;&nbsp;`'board': 0,`<br/>
&nbsp;&nbsp;`'skipped_rounds': {`<br/>
&nbsp;&nbsp;&nbsp;&nbsp;`1: 0.5,`  # bye ronde 1<br/>
&nbsp;&nbsp;&nbsp;&nbsp;`2: 0.0,`  # absent ronde 3<br/>
&nbsp;&nbsp;`}`<br/>
`}`

## Codes d'erreur

En cas d'erreur, la réponse au format JSON ne contient qu'un champ `error: str` qui précise l'erreur rencontrée. 

Les codes d'erreur suivants sont utilisés :

| Statut HTTP | Signification                                                                             | Champ `error`          |
|-------------|-------------------------------------------------------------------------------------------|------------------------|
| 200         | _succès_                                                                                  |                        |
| 401         | Problème d'authentification (impossibilité de s'identifier sur la plateforme Chess Event) | `Unauthorized`         |
| 403         | Problème d'autorisation (identifiants non autorisés pour l'évènement demandé)             | `Access forbidden`     |
| 497         | Identifiant non trouvé                                                                    | `User not found`       |
| 498         | Tournoi non trouvé                                                                        | `Tournament not found` |
| 499         | Évènement non trouvé                                                                      | `Event not found`      |
| 500         | Autres erreurs                                                                            | À préciser             |



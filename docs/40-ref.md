**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Guide de référence

## Généralités (`[event]`)

| Option            | Description                                                                                                                                         |
|-------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `name`            | Le nom de l'évènement (obligatoire), utilisé sur la page d'accueil de Papi-web (liste des évènements) et sur la page de description de l'évènement. |
| `update_password` | Le code d'accès aux pages de saisie des scores (facultatif).                                                                                        |
| `css`             | La personnalisation CSS de l'évènement (facultative).<br/>Pour utiliser `custom/ffe/ffe.css`, on utilisera `css = ffe/ffe.css`.                     |

## Tournois (`[tournament.<tournament_id>]` ou `[tournament]`)

L'identifiant du tournoi (`<tournament_id>`) est facultatif si l'évènement ne comporte qu'un tournoi, obligatoire s'il y en a plusieurs (s'il n'est pas précisé, l'identifiant du tournoi sera `default`).

| Option         | Description                                                                                                                                                                 |
|----------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `name`         | Le nom du tournoi (facultatif) est utilisé sur la page de description de l'évènement et sur les écrans.<br/>S'il n'est pas précisé, le nom du tournoi est son identifiant.  |
| `path`         | Le répertoire dans le quel est stocké le fichier Papi du tournoi (facultatif, par défaut `papi/`).                                                                          |
| `filename`     | Le nom du fichier du tournoi (facultatif).<br/>Si l'option `filename` n'est pas utilisée, le nom du fichier sera par défaut le numéro d'homologation du tournoi (`ffe_id`). |
| `ffe_id`       | Le numéro d'homologation du tournoi (facultatif).                                                                                                                           |
| `ffe_password` | Le code d'accès à l'interface de gestion du tournoi sur le site fédéral (facultatif).                                                                                       |

> [!NOTE]
> Si ni `filename` ni `ffe_id` ne sont utilisées ou si le fichier est introuvable, seules les opérations de test des accès et de récupération de la facture d'homologation sur le site fédérale seront disponiibles.
> Si `ffe_id` ou `ffe_password` ne sont utilisées, les opérations sur le site fédéral ne seront pas disponibles.

### Tournois à handicap (`[tournament.<tournament_id>.handicap]` ou `[tournament.handicap]`)

Pour les tournois à handicap, toutes les options ci-dessous sont obligatoires.

| Option          | Description                                                                          |
|-----------------|--------------------------------------------------------------------------------------|
| `initial_time`  | Le temps initial des joueur·euses à la pendule en secondes.                          |
| `increment`     | Le rajout à chaque coup, en secondes.                                                |
| `penalty_step`  | La différence de classement, pour le calcul des temps des joueur·euses.              |
| `penalty_value` | La pénalité à la pendule, pour le calcul des temps des joueur·euses.                 |
| `min_time`      | Le temps minimal pour les joueur·euses, après application des éventuelles pénalités. |

Voir également : [Configuration d'un tournoi à handicap](32-handicap.md)

## Modèles d'écran (`[template.<template_id>]`)

| Option | Description                                    |
|--------|------------------------------------------------|
| `???`  | Toutes les options des écrans sont autorisées. |

Selon le type de l'écran, on pourra ajouter une rubrique `[template.<template_id>.boards]` ou `[template.<template_id>.players]`.

Voir également : [Modèles et familles d'écran](33-templates-families.md)

## Écrans (`[screen.<screen_id>]`)

L'identifiant de l'écran (`<screen_id>`) est obligatoire.

| Option       | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
|--------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `template`   | L'identifiant du modèle sur lequel l'écran est construit (facultatif).<br/>Cf [Modèles et familles d'écran](33-templates-families.md).                                                                                                                                                                                                                                                                                                                                                                                       |
| `type`       | Le type de l'écran (obligatoire) :<br/>- `type = boards` : écran d'affichage des appariements par échiquier (affichage simple si `update = off`, saisie des scores si `update = on`).<br/>- `type = players` : écran d'affichage des appariements par ordre alphabétique.<br/>- `type = results` : affichage des derniers résultats de l'évènement.                                                                                                                                                                          |
| `name`       | Le nom de l'écran (fazcultatif).<br/>Par défaut, le nom de l'écran sera `Derniers résultats` pour les écrans de résultats, ou le nom du premier ensemble d'échiquier et de joueur·euses pour les autres écrans (mieux, pour utiliser les _tokens_ `%t`, `%f` et `%l`).                                                                                                                                                                                                                                                       |
| `update`     | `update = on` pour les écrans de saisie ou `update = off` pour les écrans d'affichage des appariements par échiquier (facultatif, par défaut `update = off`).<br/>Cette option n'est pas autorisée pour les écrans d'affichage des appariements par ordre alphabétique et les écrans de résultats.                                                                                                                                                                                                                           |
| `menu`       | Le menu qui sera affiché sur l'écran (facultatif, par défaut `menu = none`) :<br/>- `menu = none` : aucun menu.<br/>- `menu = view` : visualisation (tous les écrans de visualisation de l'évènement)).<br/>- `menu = update` : saisie (tous les écrans de saisie de l'évènement).<br/>- `menu = family` : famille (tous les écrans de la famille de l'écran, option autorisée seulement pour les écrans d'une famille).<br/>- `menu = <screen_id_1>, ...` : liste d'écrans (identifiants d'écran séparés par des virgules). |
| `menu_text`  | Le texte du lien hypertexte utilisé sur cet écran.<br/>Les _tokens_ suivants peuvent être utilisés :<br/>- `%t` : remplacé par le nom du tournoi.<br/>- `%f` (_first_) et `%l` (_last_) : remplacés par les numéros des premier/dernier échiquiers (écrans de saisie ou d'affichage des appariements par échiquier) ou les trois premières lettres du nom de famille des premier·ère/dernier·ère joueur·euse (écran d'affichage des appariements par ordre alphabétique).                                                    |
| `show_timer` | `show_timer = on` pour afficher le chronomètre, `show_timer = off` sinon (facultatif, par défaut `show_timer = off`).                                                                                                                                                                                                                                                                                                                                                                                                        |
| `limit`      | Le nombre maximal de résultats affichés (cette option n'est autorisée que pour les écrans de résultats).                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `columns`    | Le nombre de colonnes utilisé pour le rendu de l'écran (facultatif, par défaut `1`).                                                                                                                                                                                                                                                                                                                                                                                                                                         |


Voir également :
- [Saisie des résultats](21-update.md)
- [Affichage des appariements par échiquier](22-pairings-by-board.md)
- [Affichage des appariements par ordre alphabétique](23-pairings-by-player.md)
- [Affichage des derniers résultats saisis](24-last-results.md)

### Ensembles d'échiquiers (`[screen.<screen_id>.boards]` ou `[screen.<screen_id>.boards].<screen_set_id>`)

Les écrans qui affichent plusieurs ensembles d'échiquiers doivent utiliser pour chacun une rubrique `[screen.<screen_id>.boards.<screen_set_id>]` (où `<screen_set_id>` est l'identifiant de l'ensemble), alors ceux qui n'affichent q'un ensemble d'échiquier peuvent utiliser la rubrique `[screen.<screen_id>.boards]`.

Une rubrique `[screen.<screen_id>.boards]` (ou au moins une rubrique `[screen.<screen_id>.boards.<screen_set_id>]`) est obligatoire pour les écrans de type `boards` (saisie et affichage des appariements par échiquier). 

| Option       | Description                                                                                                                                                                                                                                                                                                                                     |
|--------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `tournament` | L'identifiant du tournoi dont il faut afficher les échiquiers.<br/>L'option `tournament` est facultative si l'évènement ne compte qu'un seul tournoi.                                                                                                                                                                                           |
| `name`       | Le nom de l'ensemble d'échiquiers (par défaut `%t` ou `%t échiquiers %f à %l` si les options `first`/`last` ou `part`/`parts` sont utilisées).<br/>Les _tokens_ suivants peuvent être utilisés :<br/>- `%t` : remplacé par le nom du tournoi.<br/>- `%f` (_first_) et `%l` (_last_) : remplacés par les numéros des premier/dernier échiquiers. |
| `first`      | Le numéro du premier échiquier à afficher (facultatif, par défaut `1`).                                                                                                                                                                                                                                                                         |
| `last`       | Le numéro du dernier échiquier à afficher (facultatif, par défaut le numéro du dernier échiquier).                                                                                                                                                                                                                                              |
| `part`       | Le sous-ensemble d'échiquiers à afficher (facultatif, cf ``parts``).                                                                                                                                                                                                                                                                            |
| `parts`      | Le nombre de sous-ensembles d'échiquiers du tournoi à considérer (facultatif, cf ``part``).                                                                                                                                                                                                                                                     |

> [!NOTE]
> - les options `part`/`parts` doivent toujours être utilisées ensemble, et sont incompatibles avec les options `first`/`last` ;
> - les options `first`/`last` sont incompatibles avec les options `part`/`parts`, par défaut `first` vaut 1 et `last` vaut le numéro du dernier échiquier.

### Ensembles de joueur·euses (`[screen.<screen_id>.players]` ou `[screen.<screen_id>.players].<screen_set_id>`)

Les écrans qui affichent plusieurs ensembles de joueur·euses doivent utiliser pour chacun une rubrique `[screen.<screen_id>.players.<screen_set_id>]` (où `<screen_set_id>` est l'identifiant de l'ensemble), alors ceux qui n'affichent q'un ensemble de joueur·euses peuvent utiliser la rubrique `[screen.<screen_id>.players]`.

Une rubrique `[screen.<screen_id>.players]` (ou au moins une rubrique `[screen.<screen_id>.players.<screen_set_id>]`) est obligatoire pour les écrans de type `players`. 

| Option       | Description                                                                                                                                                                                                                                                                                                                                              |
|--------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `tournament` | L'identifiant du tournoi dont il faut afficher les joueur·euses.<br/>L'option `tournament` est facultative si l'évènement ne compte qu'un seul tournoi.                                                                                                                                                                                                  |
| `name`       | Le nom de l'ensemble de joueur·euses (par défaut `%t` ou `%t %f à %l` si les options `first`/`last` ou `part`/`parts` sont utilisées).<br/>Les _tokens_ suivants peuvent être utilisés :<br/>- `%t` : remplacé par le nom du tournoi.<br/>- `%f` (_first_) et `%l` (_last_) : remplacés par les noms de famille des premier·ère/dernier·ère joueur·euse. |
| `first`      | Le numéro du·de la premier·ère joueur·euse à afficher (facultatif, par défaut `1`).                                                                                                                                                                                                                                                                      |
| `last`       | Le numéro du·de la premier·ère joueur·euse à afficher (facultatif, par défaut le numéro du dernier échiquier).                                                                                                                                                                                                                                           |
| `part`       | Le sous-ensemble de joueur·euses à afficher (facultatif, cf ``parts``).                                                                                                                                                                                                                                                                                  |
| `parts`      | Le nombre de sous-ensembles de joueur·euses du tournoi à considérer (facultatif, cf ``part``).                                                                                                                                                                                                                                                           |

> [!NOTE]
> - les options `part`/`parts` doivent toujours être utilisées ensemble, et sont incompatibles avec les options `first`/`last` ;
> - les options `first`/`last` sont incompatibles avec les options `part`/`parts`, par défaut `first` vaut 1 et `last` vaut le numéro du dernier échiquier.

## Familles d'écrans (`[family.<family_id>]`)

L'identifiant de la famille (`<family_id>`) est obligatoire et peut-être utilisé ultérieurement pour désigner la famille (dans un menu par exemple).

| Option     | Description                                                                                                                                    |
|------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| `template` | L'identifiant du modèle sur lequel la famille est basée (obligatoire).                                                                         |
| `range`    | La plage de valeurs utilisée pour construire la famille (obligatoire), de chiffres ou de lettres (par exemple `range = 1-6` ou `range = A-F`). |


## Écrans rotatifs (`[rotator.<rotator_id>]`)

L'identifiant de l'écran (`<rotator_id>`) est obligatoire.

| Option     | Description                                                                    |
|------------|--------------------------------------------------------------------------------|
| `families` | Les identifiants des familles des écrans à afficher, séparés par les virgules. |
| `screens`  | Les identifiants des écrans à afficher, séparés par les virgules.              |
| `delay`    | Le délai de transition entre deux écrans, en secondes (par défaut `15`).       |

> [!NOTE]
> Au moins une des deux options `screens` ou `families` doit être utilisée pour préciser les écrans à afficher.

## Chronomètre

### Horaires des rondes (`[timer.hour.<round_id>]`)

Lorsque l'identifiant `<round_id>` est un numéro, alors Papi-web considère automatiquement que l'horaire est celui du début de la ronde correspondante (par exemple `[timer.3]` est la rubrique du début de la troisième ronde).

| Option        | Description                                                                                                                                                            |
|---------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `date`        | Le jour et l'heure de la ronde (obligatoire), au format `AAAA-MM-JJ hh:mm` ou `hh:mm` (pour le premier horaire du chronomètre, la précision du jour est obligatoire).  |
| `text_before` | La texte affiché sur le chronomètre avant la ronde (facultatif, par défaut `Début de la ronde <numéro> dans %s`).                                                      |
| `text_after`  | La texte affiché sur le chronomètre après la ronde (facultatif, par défaut `Ronde <numéro> commencée depuis %s`).                                                      |

### Autres horaires (`[timer.hour.<event_id>]`)

| Option        | Description                                                                                                                                               |
|---------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `date`        | Le jour et l'heure (obligatoire), au format `AAAA-MM-JJ hh:mm` ou `hh:mm` (pour le premier horaire du chronomètre, la précision du jour est obligatoire). |
| `text_before` | La texte affiché sur le chronomètre avant l'horaire (obligatoire).                                                                                        |
| `text_after`  | La texte affiché sur le chronomètre après l'horaire (obligatoire).                                                                                        |

### Couleurs du chronomètre (`[timer.colors]`)

Pour savoir à quoi correspondent les index des couleurs, consulter [Utilisation d'un chronomètre](31-timer.md).

| Option                                     | Description                                                                                                        |
|--------------------------------------------|--------------------------------------------------------------------------------------------------------------------|
| `1`, `2` ou `3`<br/>(index de la couleur)  | La couleur pour remplacer la valeur par défaut, au format `#RRGGBB`, `#RGB` ou `rgb(RRR, GGG, BBB)` (facultative). |

## Chronomètre (`[timer.delays]`)

Pour savoir à quoi correspondent les index des délais, consulter [Utilisation d'un chronomètre](31-timer.md).

| Option                                | Description                                                            |
|---------------------------------------|------------------------------------------------------------------------|
| `1`, `2` ou `3`<br/>(index du délai)  | Le délai pour remplacer la valeur par défaut, en minutes (facultatif). |


**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Annexe technique : URLs utilisées par le serveur web

> [!CAUTION]
> Cette page décrivant les URLs utilisées par l'application est obsolète.

Cette page décrit les URLs utilisées par Papi-web.

| URI                                                                               | Description                                                                   |
|-----------------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| `/`                                                                               | Page d'accueil                                                                |
| `/event/<event_id>`                                                               | Page de description d'un évènement                                            |
| `/login/<event_id>`                                                               | Authentification d'un évènement, redirige vers `/event/<event_id>`            |
| `/screen/<event_id>/<screen_id>`                                                  | Écran d'affichage                                                             |
| `/rotator/<event_id>/<rotator_id>`[`/<screen_index>`]                             | Écran d'affichage rotatif                                                     |
| `/update-result/<event_id>/<screen_id>/<tournament_id>/<board_id>/<result>`]      | Saisie d'un résultat, redirige vers `/screen/<event_id>/<screen_id>`          |
| `/screen-last-update/<event_id>/<screen_id>`                                      | Récupération de la date de mise à jour pour un écran                          |
| `/add-illegal-move/<event_id>/<screen_id>/<tournament_id>/<board_id>/<color>`]    | Ajout d'un coup illégal, redirige vers `/screen/<event_id>/<screen_id>`       |
| `/delete-illegal-move/<event_id>/<screen_id>/<tournament_id>/<board_id>/<color>`] | Suppression d'un coup illégal, redirige vers `/screen/<event_id>/<screen_id>` |


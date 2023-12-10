**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Annexe technique : URLs utilisées par le serveur web

Cette page décrit les URLs utilisées par Papi-web.

| URI                                                                   | Description                                                          |
|-----------------------------------------------------------------------|----------------------------------------------------------------------|
| `/`                                                                   | Page d'accueil                                                       |
| `/event/<event_id>`                                                   | Page de description d'un évènement                                   |
| `/login/<event_id>`                                                   | Authentification d'un évènement, redirige vers `/event/<event_id>`   |
| `/screen/<event_id>/<screen_id>`                                      | Écran d'affichage                                                    |
| `/rotator/<event_id>/<rotator_id>`[`/<screen_index>`]                 | Écran d'affichage rotatif                                            |
| `/result/<event_id>/<screen_id>/<tournament_id>/<board_id>/<result>`] | Saisie d'un résultat, redirige vers `/screen/<event_id>/<screen_id>` |
| `/screen-last-update/<event_id>/<screen_id>`                          | Récupération de la date de mise à jour pour un écran                 |


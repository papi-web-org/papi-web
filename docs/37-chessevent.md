**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Création des fichiers Papi des tournois à partir de la plateforme d'inscription en ligne Chess Event

> [!NOTE]
> Cette fonctionnalité n'est disponible qu'à partir de la version 2.1 de Papi-web.<br/>
> Les aspects techniques de la récupération des données sur la plateforme Chess Events sont décrits sur [cette page](81-chessevent.md).

## Généralités

Chess Event est une plateforme d'inscription aux évènements échiquéens développée par Dominique RUHLMANN et hébergée par la Ligue de Bretagne des Échecs :

- [Accéder à la plateforme Chess Event](https://services.breizh-chess-online.fr/chessevent)

La plateforme d'inscription en ligne Chess Event permet :
- aux joueur·euses de s'inscrire en ligne ;
- aux organisateur·trices de gérer en ligne les inscriptions à leurs tournois ;
- aux arbitres/organisateur·trices de gérer le pointage en ligne ;
- aux arbitres de télécharger les fichiers Papi des tournois sur leur ordinateur à la fin du pointage.

Le téléchargement des fichiers Papi des tournois depuis la plateforme Chess Event est possible mais nécessite l'installation d'un logiciel tiers (un moteur PHP, par exemple celui de XAMPP).

A partir de la version 2.1, les fichiers Papi des tournois peuvent être téléchargés sur l'ordinateur de l'arbitre sans installation supplémentaire. 

## Configuration de l'accès à la plateforme Chess Event

En règle générale tous les tournois d'un évènement dans Papi-web sont gérés au sein du même évènement sur la plateforme Chess Event. L'accès à la plateforme d'inscription en ligne se configure à l'aide de la rubrique `[chessevent]` :

```
[chessevent]
user_id = X12345
password = ********
event_id = mon_evenement
```

## Configuration de l'identifiant d'un tournoi sur la plateforme Chess Event

Dans la rubrique `[tournament.<tournament_id>]` d'un tournoi (la rubrique `[tournament]` si l'évènement ne compte qu'un seul tournoi), l'option suivante permet d'indiquer l'identifiant du tournoi sur la plateforme Chess Event :

```
[tournament.<tournament_id>]
chessevent_tournament_id = mon_tournoi
```

## Création des fichiers Papi

Il suffit de lancer le script `chessevent.bat` et suivre les instructions :

```
INFO     Papi-web 2.0.3 Copyright © Pascal AUBRY 2013-2023
INFO     Reading configuration file...
[...]
Veuillez entrer le numéro de votre évènement :
    [...]
  - [6] Open Fide de Domloup (domloup-fide.ini)
    [...]
  - [Q] Quitter
Votre choix : 6
Évènement : Open Fide de Domloup
Tournois : A, B, C, D, E, F, X
Actions :
  - [C] Créer les fichiers Papi des tournois
  - [Q] Revenir à la liste des évènements
Entrez votre choix : c
Action : création des fichiers Papi des tournois
Tournoi : A
Configuration Chess Event : C12345:********@BRE_35_domloupfide36/TournoiA
INFO     Données récupérées de la plateforme Chess Event : 2413 octets
Le fichier papi\domloup-fide-36-A.papi existe, voulez-vous le remplacer [o/n] ? o
INFO     Le fichier papi\domloup-fide-36-A.papi a été sauvegardé sous tmp\domloup-fide-36-A-20231122235718.papi.
INFO     Le fichier papi\domloup-fide-36-A.papi a été créé (20 joueur·euses).
[...]
```

Voir également : [Guide de référence de la configuration des évènements](40-ref.md)

## Évènement Papi-web avec des tournois de plusieurs évènements Chess Event

Dans ce cas particulier, il faut définir plusieurs connexions à Chess Event :

```
[chessevent.jeunes]
user_id = X12345
password = ********
event_id = evenement_jeunes

[chessevent.adultes]
user_id = Y67890
password = ********
event_id = evenement_adultes
```

Puis indiquer pour chaque tournoi la connexion à Chess Event qu'il faut utiliser avec l'option `chessevent_connection_id` :

```
[tournament.jeunes]
chessevent_connection_id = jeunes
chessevent_tournament_id = tournoi_jeunes
...
[tournament.adultes]
chessevent_connection_id = adultes
chessevent_tournament_id = tournoi_adultes
```

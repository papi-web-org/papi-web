# Papi-web, pour les arbitres 2.0

Papi-web, programme de saisie des résultats dans Papi et de mise en ligne des résultats sur le site fédéral, a été développé à titre gracieux pour les arbitres et organisateurs de la Fédération Française des Échecs par Pascal AUBRY. Il est livré sans aucune garantie et peut être redistribué, sans aucune contrepartie financière.

## Papi-web, c'est arrivé comment ?

Papi-web est né de quelques observations simples : 

- Pendant les tournois, les arbitres « à l'ancienne » (qui se reconnaitront :-) ) passent un temps non négligeable sur le clavier de leur ordinateur à entrer les résultats des joueur·euses, puis à les vérifier ; l'arbitrage des parties en souffre, c'est pourtant le coeur de métier des arbitres !
- La saisie des résultats par l'arbitre est souvent source d'erreurs, en simple saisie en cadence lente à cause des erreurs sur les feuilles de partie, et surtout en double saisie en cadence rapide quand les joueur·euses notent leur scores sur un papier et que l'arbitre les reporte ensuite dans la « boule Papi » ;
- Il faut attendre la fin des rondes pour en connaître les résultats, difficile de communiquer sur les aspects sportifs d'un évènement échiquéen dans ces conditions...
- Sur des opens rapides en faible cadence (typiquement 9 rondes en 12 minutes et 3 secondes par coups), les retards s'accumulent sur la journée à cause des temps de saisie, les pauses déjeuner sont raccourcies, les remises des prix ont lieu systématiquement en retard, ...

Papi-web est ainsi né en septembre 2013 pour la [7e édition de l'open rapide de Domloup](http://domloup.echecs35.fr/node/1561), et son utilisation avait été relayée dans le [BAF n°135](http://www.echecs.asso.fr/Arbitrage/Baf135.pdf) ([Bulletin des Arbitres fédéraux](http://www.echecs.asso.fr/Default.aspx?Cat=5)). Depuis cette date, le logiciel n'a cessé d'évoluer grâce aux contributions et sous l'impulsion des utilisateur·trices...

![Première utilisation de Papi-web dans une compétition homologuée en 2013](docs/images/saisie-2013.jpg)

En mai 2018, un débriefing avec Pierre LAPEYRE après un stage d'arbitrage à Domloup se conclut à une heure très avancée sur une conclusion simple : il faut absolument diffuser Papi-web pour permettre aux arbitres de se concentrer sur leur coeur de métier, et il faut pour cela le mettre en place sur une manifestation de masse. Après un test grandeur nature quelques semaines avant au festival international de Metz par Eric DELMOTTE, la décision est prise d'utiliser Papi-web au championnat de France et ce sont Pierre LAPEYRE et Eric DELMOTTE qui en font la promotion à Nîmes en août 2018 ([voir la vidéo](https://www.youtube.com/watch?v=u2arqnRH9SA)) !

## Papi-web, c'est quoi ?

C'est un programme qui permet :
- La saisie des résultats par les joueurs eux-mêmes, directement dans la « boule Papi » de l'arbitre ;
- L'affichage des tournois gérés sur le site fédéral ;
- La mise en ligne des résultats sur le site fédéral en temps réel ;
- Le téléchargement des factures d'homologation depuis le site fédéral.

![Workflow](docs/images/workflow.jpg)

## Papi-web, ça sert à quoi ?

Papi-web permet aux arbitres de se concentrer sur leur job, qui consiste essentiellement à arbitrer les parties d'échecs, en minimisant le temps passé sur l'ordinateur à entrer les résultats des joueur·euses, les contrôler, ...

Papi-web participe à l'animation des tournois grâce à l'affichage des résultats en temps-réel, qui est particulièrement apprécié des accompagnateur·trices dans les compétitions jeunes, et par le public en général pour les autres compétitions.

L'affichage permanent d'un timer permet également aux joueur·euses de se préparer dans les temps pour les rondes.

## Papi-web, comment ça marche ?

Une page web dans la salle de jeu présente aux joueur·euses les matches de la ronde en cours, ceux-ci sélectionnent leur table puis indiquent leur score, qui est enregistré directement dans la « boule Papi ». L'arbitre n'a plus qu'à gérer, dans le logiciel Papi :

- les appariements, comme il le fait habituellement ;
- les éventuelles erreurs de saisie, extrêmement rares lorsque la saisie est faite par les joueur·euses eux·elles-mêmes.

En parallèle, un programme en ligne de commande se charge de mettre en ligne sur le site fédéral les « boules Papi » dès qu'elles sont modifiées, en temps-réel.

## Papi-web, qui l'utilise ?

Le logiciel Papi-web peut être utilisé gratuitement et sans autorisation par tou·tes celles·ceux qui le considérent comme un Beerware lorsqu'il·elles croisent son auteur :-)

Vous n'en faites pas encore partie ? Lancez-vous en découvrant les nouveautés de la version 2 !

Pour être prévenu des nouvelles versions de Papi-web, il suffit de s'abonner à la liste de diffusion papi-web-news@echecs35.fr (demande par mail à pascal.aubry@echecs35.fr).

# Installer et mettre à jour Papi-web

## Prérequis

Un ordinateur sous Windows avec :
  - [la dernière version de Papi](https://dna.ffechecs.fr/ressources/appariements/papi/) opérationnelle (septembre 2023 : version 3.3.6)
  - [le pilote Access](https://www.microsoft.com/en-us/download/details.aspx?id=54920) permettant de modifier les fichiers Papi

[!NOTE]
L'installation de XAMPP ou d'autres outils tiers n'est plus nécessaire à partir de la version 2.0.

## Téléchargement et installation

La dernière version de Papi-web doit être téléchargée depuis ce répertoire, décompressée et installée sur l'ordinateur qui jouera le rôle de serveur, sur lequel seront également les fichiers Papi.

| Fichiers et répertoires  | Signification  |
| -----------------------  | -------------  |
| `papi-web-<version>.exe`  | L'exécutable unique de Papi-web  |
| `server.bat`  | Le script de lancement du serveur de Papi-web  |
| `ffe.bat`  | Le script de lancement des outils d'interface avec le site fédéral  |
| `papi-web.ini`  | Le fichier de configuration de Papi-web  |
| `events/*.ini`  | Les fichiers de configuration des évènements (un fichier par évènement, les fichiers de configuration des évènements sont toujours localisés à cet endroit)  |
| `papi/*.papi`  | Les fichiers Papi des tournois égérés (il est possible configurer Papi-web pour que les fichiers Papi soient localisés dans un autre répertoire)  |
| `custom/club/XNNNNN/*`, `custom/ligue/BRE/*`, `custom/FFF/*`  | Les fichiers de personnalisation des écrans d'affichage, de saisie, ...  |
| `fees/XXXXX.html`  | Les factures d'homologation téléchargées depuis le site fédéral  |
| `tmp/*`  | Les fichiers temporaires  |

## Mise à jour

Pour installer une nouvelle version de Papi-web :
1. procédez comme pour une première installation
1. récupérez vos personnalisations :
  - la configuration de papi-web (`papi-web.ini`)
  - les fichiers de configuration de vos évènements (`events/*.ini`)
  - les fichiers de personnalisation des écrans (`custom/*`)
  - éventuellement les fichiers Papi si vous les avez stockés dans le répertoire `papi/`.

# Utiliser Papi-web
L'utilisation de Papi-web nécessite un peu d'apprentissage : il vous sera très vite indispensable, en particulier pour gérer de grois évènements, mais il est fortement conseillé de s'entrainer sur des évènements modestes dans un premier temps.

## Configuration de Papi-web (`papi-web.ini`)
La configuration fournie par défaut dans le fichier `papi-web.ini` est suffisante pour la très grande majorité des cas.

### Messages (`[loggin]`)
#### level
```
[logging]
level = INFO
```
Pour obtenir plus de messages utiliser `level = DEBUG`.
### Réseau (`[web]`)
#### host
```
[web]
host = 0.0.0.0
```
La valeur `0.0.0.0` rend Papi-web accessible depuis tous les clients de votrer réseau local (consulter votre administrateur·trice réseau pour restreindre les plages IP autorisées).
#### port
```
[web]
port = 80
```
La valeur par défaut `80` est celle classiquement utilisée par les serveurs web, qui rendra le serveur accessible depuis votre serveur à l'URL `http://127.0.0.1` ou bien `http://localhost`, et depuis un client du réseau local à l'URL `http://<ip_serveur>`. Si le port `80` est déjà utilisé sur votre serveur (cela est indiqué lorsqu'on lance `server.bat`), vous pouvez changer le port, par exemple pour `8080` (les URLs à utiliser seront alors `http://127.0.0.1::8080`, `http://localhost:8080` et `http://<ip_serveur>:8080`).
#### launch_browser
```
[web]
launch_brower = on
```
Par défaut, le navigateur web ouvre la page d'accueil au démarrage du serveur (pour ne pas ouvrir automatiquement la page d'accueil, utilisez `launch_browser = off`).

## Gestion du serveur Papi-web (`server.bat`)

Le serveur Papi-web se lance en exécutant le script `server.bat` :
```
C:\...\papi-web-<version>$ server.bat
INFO     log level: INFO
INFO     host: 0.0.0.0
INFO     port: 80
INFO     local URL: http://127.0.0.1
INFO     LAN/WAN URL: http://192.168.1.79
INFO     Setting up Django...
INFO     Opening the welcome page [http://127.0.0.1] in a browser...
INFO     Starting Papi-web server, please wait...
August 25, 2023 - 22:48:04
Django version 4.2.3, using settings 'web.settings'
Starting development server at http://0.0.0.0:80/
Quit the server with CTRL-BREAK.
```
On arrête le serveur en tapant `Ctrl-C`.

## Utilisation de l'interface avec le site fédéral

Les outils d'interface avec le site fédéral se lancent en exécutant le script `ffe.bat` :
```
C:\...\papi-web-<version>$ ffe.bat
INFO     [1] Open Fide de domloup (domloup-fide.ini)
INFO     [2] Championnat de France de parties rapides (france-rapide.ini)
INFO     Veuillez entrer le numéro de votre évènement (ou [Q] pour quitter) :
2
INFO     Evènement : Championnat de France de parties rapides
INFO     Tournois : 58878 (C:\...\58878.papi)
INFO     Actions :
INFO       - [T] Tester les codes d'accès des tournois
INFO       - [V] Rendre les tournois visibles sur le site fédéral
INFO       - [H] Télécharger les factures d'homologation
INFO       - [U] Mettre en ligne les tournois
INFO       - [Q] Revenir à la liste des évènements
INFO     Entrez votre choix :
```
[!NOTE]
Pour utiliser les outils d'interface avec le site fédéral sur les tournois de vos évènements, il est nécessaire de déclarer le numéro d'homologation et le code d'accès des tournois.

# Configurer vos évènements

## Configuration d'un petit tournoi amical

Même pour un petit tournoi amical au club, l'utilisation de Papi-web pour l'entrée des résultats permet de fluidifier le déroulement de la compétition.
On crée un fichier `amical.ini` dans le répertoire `events` pour déclarer l'évènement.
```
[event]
name = Tournoi amical 17 juin 2023

[tournament] 
name = Tournoi amical
filename = amical-20230617
```
La rubrique `[event]` est obligatoire et permet de déclarer le nom de l'évènement.

Le tournoi est nommé `Tournoi amical` et le fichier Papi du tournoi est `amical-20230617.papi`, stocké dans le répertoire par défaut `papi/` (pour le localiser à un autre endroit, on utilisera par exemple `path = c:\...\echecs\domloup\2023\tournois\amical`)

Lorsqu'aucun écran n'est déclaré, Papi-web ajoute automatiquement, pour chaque tournoi, les quatre écrans suivants :
- saisie des résultats
- affichage des appariements par échiquier
- affichage des appariements par ordre alphabétique
- affichage des derniers résultats

La configuration d'un écran de saisie des résultats se fait en déclarant un écran de type (`type = boards`, affichage par échiquier) en positionnant `update = true` :
```
[screen.saisie]
type = boards
update = true
[screen.saisie.boards]
tournament = amical
```

TODO Positionner par défaut lorsqu'il n'y a qu'un tournoi







Démarrer le serveur Papi-Web présente la page d'accueil avec un lien vers la page de l'évènement, et la page de l'évènement présente un lien vers l'écran de saisie des résultats.

Il ne reste plus qu'à apparier la première ronde, demander aux joueur·euses de saisir leurs résultats, apparier les rondes suivantes, ...

[!NOTE]
Il est également possible 
## Configuration d'un petit tournoi homologué

Pour pouvoir utiliser les outils d'interface avec le site fédéral, il faut préciser le numéro d'homologation du tournoi et le code d'accès du tournoi sur le site fédéral de gestion des tournois.
```
[tournament.homologué]
path = C:\OneDrive\echecs\domloup\2023\tournois\officiel
filename = homologué-20230617
name = Tournoi homologué 17 juin 2023
ffe_id = 57777
ffe_password = KJGYREIOBZ
```
[!NOTE]
Lorsque l'on précise le numéro d'homologation (`ffe_id`), si `filename` n'est pas précisé alors Papi-web cherchera un fichier dont le nom est le numéro d'homologation (ici `57777.papi`), dans le répertoire précisé par `path` ou dans le répertoire `papi/` par défaut.

En précisant simplement `ffe_id` et `ffe_password`, les opérations sur le site fédéral seront accessibles.

## Utilisation de plusieurs écrans de saisie

A partir de quelques dizaines de joueurs, un écran de saisie unique devient illisible et il est nécessaire de partager les échiquiers entre plusieurs écrans :
```
[screen.saisie-1]
type = boards
update = true
[screen.saisie-1.boards]
tournament = amical
first = 1
last = 20

[screen.saisie-2]
type = boards
update = true
[screen.saisie-2.boards]
tournament = amical
first = 21
```
On définit ainsi deux écrans de saisie, le premier pour les échiquiers 1 à 20 et le second pour les autres.

Il est également possible (et souvent beaucoup plus pratique) de demander à Papi-web de séparer les échiquiers en partie égales, par exemple :
```
[screen.saisie-1]
type = boards
update = true
[screen.saisie-1.boards]
tournament = amical
part = 1
parts = 2

[screen.saisie-2]
type = boards
update = true
[screen.saisie-2.boards]
tournament = amical
part = 2
parts = 2
```
Le premier écran de saisie affichera la première moitié des échiquiers, le second les autres.

Lorsque l'on utilise plusieurs écrans de saisie il est pratique de pouvoir rapidement passer de l'un à l'autre, c'est le rôle des menus des écrans.

La directive `menu` permet de préciser quel menu sera affiché sur un écran

## Tournoi à handicap

# ChangeLog

**Version 2.0 - Septembre 2023**
- Livraison sous forme d'un exécutable autonome (ne nécessite plus l'installation de XAMPP)
- Configuration des évènements au format INI (plus simple que PHP)
- Amélioration de la page d'acceuil
- Ajout d'une page par évènement
- Ajout d'écrans d'affichage des appariements par ordre alphabétique
- Simplification de la configuration des écrans grâce aux modèles et aux familles d'écran

**Version 1.19 - 22 janvier 2023**
- Correction d'un bug de protection des pages de saisie des résultats

**Version 1.18 - 4 février 2020**
- Correction d'un bug d'affichage des derniers résultats
- Correction d'un bug de transmission sur le site fédéral

**Version 1.17 - 4 octobre 2019**
- Correction d'un bug d'accès concurrent (saisie des résultats sur plusieurs écrans)
- Correction d'un bug d'affichage des joueurs avant appariement

**Version 1.16 - 31 août 2019**
- Correction d'un bug d'affichage du chronomètre

**Version 1.15 - 31 août 2019**
- Compatibilité avec Papi 3.3.6
- Support du système de Haley dégressif
- Support du « bye »
- Ajout du chronomètre
- Amélioration du rafraichissement des pages
- Rennomage de la propriété no-banner en no_banner

**Version 1.14 - 9 avril 2019**
- Ajout des écrans d'affichage des résultats
- Ajout des écrans d'affichage des derniers résultats
- Ajout du rafraichissement automatique des écrans de saisie
- Amélioration des temps de réponse
- Simplification des URL des écrans
- Téléchargement systématique des fichiers avant affichage sur le site FFE

**Version 1.13 - 10 novembre 2018**
- Affichage des numéros des échiquiers

**Version 1.12 - 30 octobre 2018**
- Support des tournois à handicap

**Version 1.11 - 27 octobre 2018**
- Support du Suisse Accéléré Degressif (SAD)
- Support de l'acélération de Haley

**Version 1.10 - 26 octobre 2018**
- Possibilité de tester les codes d'accès au site FFE
- Possibilité de rendre les données visibles sur le site FFE
- Possibilité de télécharger les factures d'homologation depuis le site FFE
- Renommage du script upload.bat en ffe.bat

**Version 1.9 - 23 octobre 2018**
- Correction de la mise en ligne sur le site fédéral

**Version 1.8 - 1er septembre 2018**
- Amélioration des transitions entre les requêtes

**Version 1.7 - 31 août 2018**
- Recherche automatique des mises à jour

**Version 1.6 - 30 août 2018**
- Ecriture de la documentation
- Diffusion sous forme d'une archive
- Amélioration de l'affichage des participants avant les appariements
- Amélioration des styles CSS (normalisation)
- Obfuscation des sources PHP

**Version 1.5 - 3 août 2018**
- Ajout des personnalisations CSS
- Amélioration de l'affichage (bandeau supérieur toujours visible)

**Version 1.4 - 28 juillet 2018**
- Gestion de plusieurs écrans de saisie


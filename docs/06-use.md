**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Configuration et utilisation

L'utilisation de Papi-web nécessite un peu d'apprentissage : il vous sera très vite indispensable, en particulier pour gérer de gros évènements, mais il est fortement conseillé de s'entrainer sur des évènements modestes dans un premier temps.

## Configuration (`papi-web.ini`)
La configuration fournie par défaut dans le fichier `papi-web.ini` est suffisante pour la très grande majorité des cas.

### Messages (`[logging]`)
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
La valeur `0.0.0.0` rend Papi-web accessible depuis tous les clients de votre réseau local (consulter votre administrateur·trice réseau pour restreindre les plages IP autorisées).
#### port
```
[web]
port = 80
```
La valeur par défaut `80` est celle classiquement utilisée par les serveurs web, qui rendra le serveur accessible depuis votre serveur à l'URL `http://127.0.0.1` ou bien `http://localhost`, et depuis un client du réseau local à l'URL `http://<ip_serveur>`. Si le port `80` est déjà utilisé sur votre serveur (cela est indiqué lorsqu'on lance `server.bat`), vous pouvez changer le port, par exemple pour `8080` (les URLs à utiliser seront alors `http://127.0.0.1::8080`, `http://localhost:8080` et `http://<ip_serveur>:8080`).
#### launch_browser
```
[web]
launch_browser = on
```
Par défaut, le navigateur web ouvre la page d'accueil au démarrage du serveur (pour ne pas ouvrir automatiquement la page d'accueil, utilisez `launch_browser = off`).

### Site fédéral (`[ffe]`)
#### upload_delay
```
[ffe]
upload_delay = 300
```
Le délai minimum entre deux téléchargements sur le site fédéral est par défaut fixé à `180` secondes (minimum `60` secondes).

## Gestion du serveur Papi-web (`server.bat`)

Le serveur Papi-web se lance en exécutant le script `server.bat` :
```
C:\...\papi-web-<version>$ server.bat
Papi-web <version> Copyright © Pascal AUBRY 2013-2024
Starting Papi-web server, please wait...
Reading configuration file...
log: INFO
port: 80
local URL: http://127.0.0.1
LAN/WAN URL: http://192.168.43.85
INFO:     Started server process [XXXXX]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:80 (Press CTRL+C to quit)
```
On arrête le serveur en tapant `Ctrl-C`.

## Interface avec le site fédéral (`ffe.bat`)

Les outils d'interface avec le site fédéral se lancent en exécutant le script `ffe.bat` :
```
C:\...\papi-web-<version>$ ffe.bat
[1] Open Fide de domloup (domloup-fide.ini)
[2] Championnat de France de parties rapides (france-rapide.ini)
Veuillez entrer le numéro de votre évènement (ou [Q] pour quitter) :
2
Evènement : Championnat de France de parties rapides
Tournois : 58878 (C:\...\58878.papi)
Actions :
- [T] Tester les codes d'accès des tournois
- [V] Rendre les tournois visibles sur le site fédéral
- [H] Télécharger les factures d'homologation
- [U] Mettre en ligne les tournois
- [Q] Revenir à la liste des évènements
Entrez votre choix :
```
> [!NOTE]
> Pour utiliser les outils d'interface avec le site fédéral sur les tournois de vos évènements, il est nécessaire de déclarer le numéro d'homologation et le code d'accès des tournois.

## Interface avec la plateforme ChessEvent (`chessevent.bat`)

Les outils d'interface avec la plateforme ChessEvent se lancent en exécutant le script `chessevent.bat` :
```
C:\...\papi-web-<version>$ chessevent.bat
[1] Open Fide de domloup (domloup-fide.ini)
[2] Championnat de France de parties rapides (france-rapide.ini)
Veuillez entrer le numéro de votre évènement (ou [Q] pour quitter) :
1
Évènement : 37e open Fide de Domloup
Tournois : Tournoi A, Tournoi B, Tournoi C, Tournoi D, Tournoi E, Tournoi F, Tournoi X
Actions :
  - [C] Créer les fichiers Papi
  - [U] Créer les fichiers Papi et les envoyer sur le site fédéral
  - [Q] Revenir à la liste des évènements
Entrez votre choix (par défaut C) : 
```

> [!NOTE]
> Pour utiliser les outils d'interface avec la plateforme ChessEvent sur les tournois de vos évènements, il est nécessaire de déclarer les identifiants d'accès à la plateforme ChessEvent.


**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Configuration et utilisation

L'utilisation de Papi-web nécessite un peu d'apprentissage : il vous sera très vite indispensable, en particulier pour gérer de grois évènements, mais il est fortement conseillé de s'entrainer sur des évènements modestes dans un premier temps.

## Configuration (`papi-web.ini`)
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

## Interface avec le site fédéral (`ffe.bat`)

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
> [!NOTE]
> Pour utiliser les outils d'interface avec le site fédéral sur les tournois de vos évènements, il est nécessaire de déclarer le numéro d'homologation et le code d'accès des tournois ([détails](12-qualified.md)).


# Papi-web, installation et mise à jour

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


**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Installation et mise à jour

## Prérequis

Un ordinateur sous Windows avec :
  - [la dernière version de Papi](https://dna.ffechecs.fr/ressources/appariements/papi/) opérationnelle (septembre 2023 : version 3.3.7)
  - [le pilote Access](https://www.microsoft.com/en-us/download/details.aspx?id=54920) permettant de modifier les fichiers Papi

[!NOTE]
L'installation de XAMPP ou d'autres outils tiers n'est plus nécessaire à partir de la version 2.0.

## Téléchargement et installation

La dernière version de Papi-web doit être téléchargée depuis [ce répertoire](../downloads), décompressée et installée sur l'ordinateur qui jouera le rôle de serveur, sur lequel seront également les fichiers Papi.

- **[Télécharger la version 2.0-rc11](https://raw.githubusercontent.com/pascalaubry/papi-web/main/downloads/papi-web-2.0-rc11.zip)**

| Fichiers et répertoires                                      | Signification                                                                                                                                               |
|--------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `papi-web-<version>.exe`                                     | L'exécutable unique de Papi-web                                                                                                                             |
| `server.bat`                                                 | Le script de lancement du serveur de Papi-web                                                                                                               |
| `ffe.bat`                                                    | Le script de lancement des outils d'interface avec le site fédéral                                                                                          |
| `papi-web.ini`                                               | Le fichier de configuration de Papi-web                                                                                                                     |
| `events/*.ini`                                               | Les fichiers de configuration des évènements (un fichier par évènement, les fichiers de configuration des évènements sont toujours localisés à cet endroit) |
| `papi/*.papi`                                                | Les fichiers Papi des tournois gérés (il est possible configurer Papi-web pour que les fichiers Papi soient localisés dans un autre répertoire)             |
| `custom/club/XNNNNN/*`, `custom/ligue/BRE/*`, `custom/FFF/*` | Les fichiers de personnalisation des écrans d'affichage, de saisie, ...                                                                                     |
| `tmp/*`                                                      | Les fichiers temporaires                                                                                                                                    |

## Mise à jour

Pour installer une nouvelle version de Papi-web :
1. procédez comme pour une première installation
2. récupérez vos personnalisations :
  - la configuration de papi-web (`papi-web.ini`)
  - les fichiers de configuration de vos évènements (`events/*.ini`)
  - les fichiers de personnalisation des écrans (`custom/*`)
  - éventuellement les fichiers Papi si vous les avez stockés dans le répertoire `papi/`.


**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Installation et mise à jour

## Prérequis

Un ordinateur sous Windows avec :
  - [la dernière version de Papi](https://dna.ffechecs.fr/ressources/appariements/papi/) opérationnelle (septembre 2023 : version 3.3.7)
  - [le pilote Access](https://www.microsoft.com/en-us/download/details.aspx?id=54920) permettant de modifier les fichiers Papi

> [!NOTE]
> L'installation de XAMPP ou d'autres outils tiers n'est plus nécessaire à partir de la version 2.0.

## Téléchargement et installation

Téléchargez la dernière version de Papi-web, décompressez et installez la 
sur l'ordinateur qui jouera le rôle de serveur (sur lequel seront également les fichiers Papi).

- **[Télécharger la dernière version (2.1.4)](https://github.com/papi-web-org/papi-web/releases/download/2.1.4/papi-web-2.1.4.zip)**
- **[Voir toutes les versions](https://github.com/pascalaubry/papi-web/releases)**

| Fichiers et répertoires                                                | Type                 | Signification                                                                                                                                               |
|------------------------------------------------------------------------|----------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`server.bat`**                                                       | **Script**           | Le script de lancement du serveur de Papi-web                                                                                                               |
| **`ffe.bat`**                                                          | **Script**           | Le script de lancement des outils d'interface avec le site fédéral                                                                                          |
| **`chessevent.bat`**                                                   | **Script**           | Le script de création des fichiers papi des tournois à partir de la plateforme Chess Event                                                                  |
| **`papi-web.ini`**                                                     | **Configuration**    | Le fichier de configuration de Papi-web                                                                                                                     |
| **`events\*.ini`**                                                     | **Configuration**    | Les fichiers de configuration des évènements (un fichier par évènement, les fichiers de configuration des évènements sont toujours localisés à cet endroit) |
| **`papi\*.papi`**                                                      | **Papi**             | Les fichiers Papi des tournois gérés (il est possible configurer Papi-web pour que les fichiers Papi soient localisés dans un autre répertoire)             |
| **`custom\club\XNNNNN\*.*`, `custom\ligue\BRE\*.*`, `custom\FFF\*.*`** | **Personnalisation** | Les fichiers de personnalisation des écrans d'affichage, de saisie, ...                                                                                     |
| `bin\papi-web-<version>.exe`                                           | Exécutable           | L'exécutable unique de Papi-web                                                                                                                             |
| `tmp\*.*`                                                              | temporaire           | Les fichiers temporaires                                                                                                                                    |

> [!NOTE]
> Selon votre antivirus, il est possible que vous deviez ajouter une exception pour le fichier exécutable `bin\papi-web-<version>.exe` (par exemple dans Avast : ☰ Menu ▸ Paramètres ▸ Général ▸ Exclusions ▸ Ajouter une exclusion).

## Mise à jour

Pour installer une nouvelle version de Papi-web :
1. procédez comme pour une première installation
2. récupérez vos personnalisations :
  - la configuration de papi-web (`papi-web.ini`)
  - les fichiers de configuration de vos évènements (`events/*.ini`)
  - les fichiers de personnalisation des écrans (`custom/*`)
  - éventuellement les fichiers Papi si vous les avez stockés dans le répertoire `papi/`.


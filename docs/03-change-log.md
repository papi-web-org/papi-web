**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - ChangeLog

## Version 2.2 - Non publiée
- Vérification de la dernière version disponible au démarrage

## Version 2.1.4 - 23 janvier 2024
- Ajout de l'option `show_unpaired` pour limiter l'affichage des appariements par ordre alphabétique aux joueur·euses apparié·es

## Version 2.1.3 - 22 janvier 2024
- Mise en forfait général des joueur·euses non pointé·es dans ChessEvent dans les fichiers Papi

## Version 2.1.2 - 21 janvier 2024
- Ajout du numéro d'homologation de ChessEvent dans les fichiers Papi

## Version 2.1.1 - 10 décembre 2023
- Possibilité de fixer le nombre d'échiquiers ou de joueur·euses par écran
- Possibilité de fonctionner en réseau local sans aucune connexion internet (intégration des bibliothèques CSS et Javascript)

## Version 2.1.0 - 9 décembre 2023
- Création des fichiers Papi des tournois à partir de la plateforme d'inscription en ligne Chess Event
- Suppression des données personnelles des joueur·euses avant téléchargement sur le site fédéral

## Version 2.0.3 - 19 novembre 2023
- Réduction _a minima_ des téléchargements des tournois vers le site fédéral 
- Amélioration de la détection de l'encodage des fichiers de configuration

## Version 2.0.0 - 10 novembre 2023
- Livraison sous forme d'un exécutable autonome (ne nécessite plus l'installation de XAMPP)
- Configuration des évènements au format INI (plus simple que PHP)
- Amélioration de la page d'accueil
- Ajout d'une page par évènement
- Ajout d'écrans d'affichage des appariements par ordre alphabétique
- Ajout des écrans rotatifs
- Simplification de la configuration des écrans grâce aux modèles et aux familles d'écran
- Ajout d'une temporisation pour le transfert des fichiers Papi sur le site fédéral
- Publication des sources

## Version 1.19 - 22 janvier 2023
- Correction d'un bug de protection des pages de saisie des résultats

## Version 1.18 - 4 février 2020
- Correction d'un bug d'affichage des derniers résultats
- Correction d'un bug de transmission sur le site fédéral

## Version 1.17 - 4 octobre 2019
- Correction d'un bug d'accès concurrent (saisie des résultats sur plusieurs écrans)
- Correction d'un bug d'affichage des joueurs avant appariement

## Version 1.16 - 31 août 2019
- Correction d'un bug d'affichage du chronomètre

## Version 1.15 - 31 août 2019
- Compatibilité avec Papi 3.3.6
- Support du système de Haley dégressif
- Support du « bye »
- Ajout du chronomètre
- Amélioration du rafraichissement des pages
- Renommage de la propriété no-banner en no_banner

## Version 1.14 - 9 avril 2019
- Ajout des écrans d'affichage des résultats
- Ajout des écrans d'affichage des derniers résultats
- Ajout du rafraichissement automatique des écrans de saisie
- Amélioration des temps de réponse
- Simplification des URL des écrans
- Téléchargement systématique des fichiers avant affichage sur le site FFE

## Version 1.13 - 10 novembre 2018
- Affichage des numéros des échiquiers

## Version 1.12 - 30 octobre 2018
- Support des tournois à handicap

## Version 1.11 - 27 octobre 2018
- Support du Suisse Accéléré Dégressif (SAD)
- Support de l'accélération de Haley

## Version 1.10 - 26 octobre 2018
- Possibilité de tester les codes d'accès au site FFE
- Possibilité de rendre les données visibles sur le site FFE
- Possibilité de télécharger les factures d'homologation depuis le site FFE
- Renommage du script upload.bat en ffe.bat

## Version 1.9 - 23 octobre 2018
- Correction de la mise en ligne sur le site fédéral

## Version 1.8 - 1er septembre 2018
- Amélioration des transitions entre les requêtes

## Version 1.7 - 31 août 2018
- Recherche automatique des mises à jour

## Version 1.6 - 30 août 2018
- Écriture de la documentation
- Diffusion sous forme d'une archive
- Amélioration de l'affichage des participants avant les appariements
- Amélioration des styles CSS (normalisation)
- Obfuscation des sources PHP

## Version 1.5 - 3 août 2018
- Ajout des personnalisations CSS
- Amélioration de l'affichage (bandeau supérieur toujours visible)

## Version 1.4 - 28 juillet 2018
- Gestion de plusieurs écrans de saisie

# Politique de numérotation des versions (`x.y.z`)

- `x` : numéro majeur (changements complets du logiciel)
- `y` : numéro mineur (modifications de configuration et évolutions fonctionnelles)
- `z` : numéro de correctif (modification du code)

**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - ChangeLog

## Version 2.4 - septembre 2024
- Déclaration de tous les objets par l'interface web (Abandon du format INI)
- Ajout de la création automatique de tournois d'exemple
- Fluidification de la navigation (HTMX)
- Masquage de toutes les URLs de l'application
- Ajout de la possibilité (configurable) de supprimer un résultat mal rentré
- Ajout de la possibilité de spécifier des tables fixes sur les écrans d'appariements
- Ajout de la possibilité de spécifier les tournois affichés sur les écrans de résultats
- Affichage du numéro de ronde sur les écrans de résultats
- Simplification de la page d'accueil de l'interface web
- Présentation des évènements et des écrans à l'aide de tuiles
- Amélioration de l'authentification sur les écrans de saisie
- Ajout de la possibilité de restreindre la visibilité de certains évènements, certains écrans, certaines familles d'écrans, certains écrans rotatifs
- Ajout d'écrans fixes permettant d'insérer des images dans les écrans rotatifs
- Suppression de la personnalisation CSS et remplacement par une image et une couleur de fond
- Contournement d'un bug du site fédéral sur l'affichage des classements (suppression des forfaits en l'absence d'appariement)

## Version 2.3.2 - 15 avril 2024
- Correction d'un problème d'affichage des appariements par ordre alphabétique

## Version 2.3.1 - 14 avril 2024
- Correction d'un problème d'encodage des fichiers de configuration

## Version 2.3.0 - 8 avril 2024
- Affichage des joueur·euses par ordre alphabétique avant appariement
- Ajout du pointage sur les écrans de saisie
- Ajout de la [Foire Aux Questions](50-faq.md)
- Correction d'un problème d'affichage du classement et des grilles américaines sur le site fédéral pour les fichiers Papi générés depuis ChessEvent
- Correction d'un problème de couleurs sur les appariements par ordre alphabétique
- Interdiction du caractère `/` dans les identifiants des écrans et des tournois

## Version 2.2.1 - 28 mars 2024
- Correction d'un bug de configuration

## Version 2.2.0 - 27 mars 2024
- Allègement du moteur web (remplacement de Django par Litestar)
- Affichage du pointage des joueur·euses
- Enregistrement des coups illégaux (option `record_illegal_moves`)
- Mise à jour de l'URL de ChessEvent suite au déménagement de la plateforme

## Version 2.1.8 - 16 février 2024
- Suppression du _pooling_ ODBC

## Version 2.1.7 - 13 février 2024
- Corrections et amélioration de la documentation

## Version 2.1.6 - 4 février 2024
- Affichage des pilotes ODBC sur la page d'accueil

## Version 2.1.5 - 24 janvier 2024
- Simplification de la configuration des évènements :
  - Pour un modèle, suppression de l'obligation de préciser la rubrique `[template.<template_id>.boards]`/`[template.<template_id>.players]` lorsque l'évènement ne compte qu'un seul tournoi
  - Pour une famille, utilisation par défaut du modèle du même nom
  - Pour un écran rotatif, utilisation par défaut de la famille du même nom

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
- Renommage du script `upload.bat` en `ffe.bat`

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

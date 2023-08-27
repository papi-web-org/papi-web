# Papi-web - Configuration d'un tournoi homologué

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

En précisant simplement `ffe_id` et `ffe_password`, les opérations sur le site fédéral seront accessibles en lançant le script `ffe.bat`.

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


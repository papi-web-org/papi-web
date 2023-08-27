# Papi-web - Nouveautés de la version 2

## Installation plus rapide

Papi-web est désormais livré sous la forme d'un exécutable Windows autonome.

L'installation de XAMPP (ou d'un autre serveur Apache/PHP) n'est plus nécessaire.

## Configuration plus simple

Papi-web et les évènements sont désormais configuré au format INI :

```
[rubrique]
option = valeur
```

L'écriture de lignes de code PHP n'est plus nécessaire, la configuration d'un tournoi sans personnalisation se fait en quelques secondes :

```
[event]
name = Tournoi amical 17 juin 2023

[tournament]
filename = amical-20230617
```

## Page d'accueil mieux renseignée

La page d'accueil se lance automatiquement au démarrage du serveur web et renseigne sur tous les évènements configurés sur le serveur.

![Page d'accueil](images/home.jpg)

## Une page par évènement

Une page par évènement précise toutes les caractéristiques de l'évènement.

![Informations](images/event-infos.jpg)

![Tournois](images/event-tournaments.jpg)

![Ecrans](images/event-screens.jpg)

![Ecrans rotatifs](images/event-rotators.jpg)

![Timer](images/event-timer.jpg)

## Simplification de l'affichage multi-écrans

Pour présenter un tournoi sur plusieurs écrans, indiquez simplement la partie que vous souhaitez afficher, Papi-web se charge du reste !

```
[screen.pairings-7.boards]
type = boards
part = 1
parts = 12
```

![Affichage standard des appariements](images/screen-pairings-1.jpg)


## Présentation des écrans en plusieurs colonnes

Pour un meilleurs affichage, tous les écrans peuvent être présentés en multi-colonnes.

```
[screen.pairings]
type = boards
columns = 2
```
![Affichage des appariements en deux colonnes](images/screen-pairings-2.jpg)

## Affichage des appariements par ordre alphabétique

Pour les tournois à fortes participation (à partir d'une centaine de joueur·euses), il est désormais possible d'afficher les appariements par ordre alphabétique.

```
[screen.players]
type = players
```

![Appariements par ordre alphabétique](images/screen-players.jpg)

## Créations des écrans multiples à l'aide de modèles

Pour la présentation multi-écrans, il est possible d'utiliser des modèles (les modifications d'un modèle sont répercutées sur tous les écrans basés sur le modèle).

```
# modèle d'affichage des appariements par ordre alphabétique
[template.alpha]
type = players
tournament = principal
columns = 2
menu_text = [%f-%l]
[template.apha.players]
parts = 2

# écran n°1
[screen.alpha-1]
template = alpha
[screen.alpha-1.players]
part = 1

# écran n°2
[screen.alpha-2]
template = alpha
[screen.alpha-2.players]
part = 2
```

## Création de familles d'écrans multiples

Pour encore plus de souplesse, il est possible de définir toute une famille d'écrans en une fois :

```
# modèle de saisie des résultats
[template.saisie]
type = boards
update = true
columns = 2
menu_text = [%f-%l]
[template.saisie.boards]
part = ?
parts = 10

# écrans n°1 à 10 !
[family.saisie]
template = saisie
range = 1-10
```

Dans l'exemple ci-dessus, 10 écrans de saisie des résultats sont automatiquement créés !

## écrans rotatifs

Avec la version 1 de Papi-web, les organisateurs s'appuyaient parfois sur des modules externes de navigateurs (Tab Rotate sur Chrome, Tab Rotator sur Firefox, ...) pour permettre une rotation de l'affichage entre plusieurs écrans.

Cette fonctionnalité est intégrée nativement dans la version 2 de Papi-web grâce aux écrans rotatifs :

```
# modèle d'affichage des appariement
[template.appariements]
type = boards
menu_text = Tournoi ?
[template.saisie.boards]
tournament = domloup-fide-?

# 6 écrans d'affichage des appariements pour les tournois A à F
[family.appariements]
template = appariements
range = A-F

[rotator.appariements]
families = appariements
```

![NOTE]
Il est également possible de configurer des écran rotatifs sur une liste d'écran, par exemple :

```
# modèle d'affichage des tournois
[template.tournoi]
type = boards
menu_text = Tournoi ?
[template.saisie.boards]
tournament = domloup-fide-?

# 6 écrans d'affichage des appariements pour les tournois A à F
[family.tournoi]
template = tournoi
range = A-F

[rotator.tournoi-AB]
screens = tournoi-A,tournoi-B

[rotator.tournoi-CD]
screens = tournoi-C,tournoi-D

[rotator.tournoi-EF]
screens = tournoi-E,tournoi-F
```

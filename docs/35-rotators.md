**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Écrans rotatifs

Avec la version 1 de Papi-web, les organisateurs s'appuyaient parfois sur des modules externes de navigateurs (Tab Rotate sur Chrome, Tab Rotator sur Firefox, ...) pour permettre une rotation de l'affichage entre plusieurs écrans.

Cette fonctionnalité est intégrée nativement dans la version 2 de Papi-web grâce aux écrans rotatifs.

La déclaration d'un écran rotatif se fait en créant une rubrique `[rotator.<rotator_id>]`, où `<rotator_id>` est l'identifiant de l'écran rotatif.

Deux options permettent de spécifier les écrans qui seront projetés alternativement :
- `screens`, qui permet d'afficher une liste précise d'écrans ;
- `families`, qui permet de désigner d'un coup tous les écrans de familles.

> [!NOTE]
> Il est possible d'utiliser à la fois `families` et `screens`.

## Exemple n°1 : rotation entre les écrans d'une famille (`families`)

```
# modèle d'affichage des appariement
[template.appariements]
type = boards
menu_text = Tournoi ?
[template.appariements.boards]
tournament = domloup-fide-?

# 6 écrans d'affichage des appariements pour les tournois A à F
[family.appariements]
template = appariements
range = A-F

[rotator.appariements]
families = appariements
```

## Exemple n°2 : rotation entre une liste d'écrans (`screens`)

```
# modèle d'affichage des tournois
[template.tournoi]
type = boards
menu_text = Tournoi ?
[template.tournoi.boards]
tournament = tournoi-?

# 6 écrans d'affichage des appariements pour les tournois A à F (tournois nommés tournoi-A à tournoi-F)
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

> [!NOTE]
> Pour l'option `families`, il est possible de préciser plusieurs familles (séparées par des virgules).

```
[template.a]
type = boards
menu_text = Tournoi a
[template.a.boards]
tournament = a

[family.a]
template = a
parts = 3

[template.b]
type = boards
menu_text = Tournoi b
[template.b.boards]
tournament = b

[family.b]
template = b
parts = 2

[rotator.tournoi-AB]
families = a,b
```

Voir également : [Guide de référence de la configuration des évènements](40-ref.md)


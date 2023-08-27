[Sommaire de la documentation](../README.md)

# Papi-web - Utilisation de plusieurs écrans de saisie

## Partage des échiquiers par numéros

A partir de quelques dizaines de joueurs, la présence de tous les échiquiers sur un seul écran le rend illisible et il est nécessaire de partager les échiquiers entre plusieurs écrans :
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
On définit ici deux écrans de saisie, le premier pour les échiquiers 1 à 20 et le second pour les autres.

## Partage des échiquiers par parties égales

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
Le premier écran de saisie affichera la première moitié des échiquiers, le second l'autre moitié.

## Navigation entre les écrans par le menu

Lorsque l'on utilise plusieurs écrans de saisie il est pratique de pouvoir rapidement passer de l'un à l'autre, c'est le rôle des menus des écrans.

Les directives `menu_text` `menu` permettent de configurer ces menus.

### Menu affiché sur un écran

La directive `menu` permet de définir le menu qui sera affiché sur un écran :

- `menu = saisie-1,saisie-2` affichera un menu avec des liens vers les écrans `saisie-1` et `saisie-2` (une liste d'écran désignés par leur identifiant et séparés par des virgules).
- `menu = update` affichera un menu contenant des liens vers tous les écrans de saisie de l'évènement.
- `menu = view` affichera un menu contenant des liens vers tous les écrans de saisie de l'évènement.



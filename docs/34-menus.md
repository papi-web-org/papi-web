**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Configuration des menus des écrans

Lorsque l'on utilise plusieurs écrans, les menus permettent de passer facilement d'un menu à un autre.

Dans la rubrique `[screen.<screen_id>]` d'un écran, deux options servent à gérer les menus :
- `menu` permet de définir le menu qui sera affiché sur l'écran ;
- `menu_text` permet de définir le texte du lien hypertexte de cet écran dans les menus.

## Définition du menu affiché sur un écran

L'option `menu` peut avoir les valeurs suivantes :

### Aucun menu : `menu = none`

aucun menu ne sera affiché sur cet écran (par exemple, il n'est en général pas nécessaire d'afficher des liens hypertextes puisque la navigation entre les écrans est automatique). `menu = none` est la valeur par défaut.

### Visualisation : `menu = view`

le menu contiendra des liens vers tous les écrans de l'évènement :
- affichage des appariements par échiquier
- affichage des appariements par ordre alphabétique
- affichage des résultats

### Saisie : `menu = update`

le menu contiendra des liens vers tous les écrans de saisie de l'évènement.

### Famille (de l'écran) : `menu = family`

le menu contiendra des liens vers tous les écrans de la famille de l'écran (cette valeur n'est autorisée que pour les écrans d'une famille).

### Liste d'écrans : `menu = <écran n°1, ...>`

le menu contiendra des liens vers les écrans dont on indique la liste des identifiants, séparés par des virgules.

## Définition du lien hypertexte d'un écran

L'option `menu_text` est uen chaîne de caractère libre.

Avant d'être affichée à l'écran, les remplacements suivants sont effectués :
- `%t` est remplacé par le nom du tournoi concerné par l'écran
- `%f` (f = first) est remplacé par le numéro du premier échiquier ou les trois premières lettres du nom du·de la premier·ère joueur·euse
- `%l` (l = last) est remplacé par le numéro du dernier échiquier ou les trois premières lettres du nom du·de la dernier·ère joueur·euse

> [!NOTE]
- Si l'écran présente plusieurs ensembles concernant plusieurs tournois, le tournoi du premier ensemble sera considéré pour les remplacements.

### Exemples

```
[tournament.a]
ffe_id = 59999
name = A

[tournament.b]
ffe_id = 60000
name = B

[tournament.j]
ffe_id = 60000
name = jeunes

[template.commun]
type = boards
update = on
menu = a-1, a-2, a-3, b-1, b-2, j
menu_text = %t

[family.a]
template = commun
[family.a.boards]
tournament = a
parts = 3
part = ?

[family.b]
template = commun
[family.b.boards]
tournament = b
parts = 2
part = ?

[screen.j]
template = commun
[screen.b.boards]
tournament = j
```

![Exemple de menu](images/menus-0.jpg)

```
[template.saisie]
type = boards
update = on
show_timer = off
menu = family
menu_text = %t
[template.saisie.boards]
tournament = ?

[family.saisie]
template = saisie
range = A-F
```

![Exemple de menu](images/menus-1.jpg)

```
[template.alpha]
type = players
columns = 2
menu = family
menu_text = [%f-%l]
[template.alpha.players]
part = ?
parts = 12
name = Appariements de %f à %l

[family.alpha]
template = alpha
range = 1-12
```

![Exemple de menu](images/menus-2.jpg)

Voir également : [Guide de référence de la configuration des évènements](40-ref.md)


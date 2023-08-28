**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Modèles et familles d'écran

Les modèles et les familles ont été introduits dans Papi-web en version 2 pour simplifier la configuration des écrans multiples.

> [!NOTE]
> Les options `menu` et `menu_text` sont décrites sur la page [Configuration des menus des écrans](34-menus.md).

## Les modèles d'écran

Les modèles servent à définir des « patrons » qui peuvent être réutilisés pour créer les écrans. Le bénéfice de l'utilisation des modèles réside en la facilité à modifier d'un coup tous les écrans basés sur un modèle.

Un modèle d'écran se déclare à l'aide d'une rubrique `[template.<template_id>]`, où `template_id` sera l'identifiant du modèle. Dans la rubrique `[template.<template_id>]` peuvent se trouver les options habituellement utilisées pour les écrans, et on peut ajouter les sous-rubriques permettant par exemple de définir les échiquiers ou les joueur·euses qui seront présentées sur l'écran.

Dans les trois exemples ci-dessous :
- on factorise dans un modèle tous les éléments communs des écrans, qui n'ont ainsi pas besoin d'être répétés pour chaque écran ;
- pour chaque écran, on fait référence au modèle et on ajoute les options propres à chaque écran.


### Exemple n°1 : écrans de saisie d'un évènement avec plusieurs tournois

#### Déclaration du modèle

```
[template.saisie]
type = boards
update = on
menu = saisie-A,saisie-B,saisie-C,saisie-D,saisie-E
[template.saisie.boards]
name = %t
```

#### Déclaration des écrans

```
[screen.saisie-A]
template = saisie
menu_text = Tournoi A
[screen.saisie-A.boards]
Tournament = A

[screen.saisie-B]
template = saisie
menu_text = Tournoi B
[screen.saisie-B.boards]
Tournament = B

[screen.saisie-C]
template = saisie
menu_text = Tournoi C
[screen.saisie-C.boards]
Tournament = C

[screen.saisie-D]
template = saisie
menu_text = Tournoi D
[screen.saisie-D.boards]
Tournament = D

[screen.saisie-E]
template = saisie
menu_text = Tournoi E
[screen.saisie-E.boards]
Tournament = E
```

### Exemple n°2 : écrans d'affichage des appariements par échiquier

#### Déclaration du modèle

```
[template.appariements]
type = boards
update = off
menu = appariements-1,appariements-2,appariements-3,appariements-4,appariements-5
menu_text = Éch. [%f à %l]
[template.appariements.boards]
tournament = principal
parts = 5
name = Échiquiers %f à %l
```

#### Déclaration des écrans

```
[screen.appariements-1]
template = appariements
[screen.appariements-1.boards]
part = 1

[screen.appariements-2]
template = appariements
[screen.appariements-2.boards]
part = 2

[screen.appariements-3]
template = appariements
[screen.appariements-3.boards]
part = 3

[screen.appariements-4]
template = appariements
[screen.appariements-4.boards]
part = 4

[screen.appariements-5]
template = appariements
[screen.appariements-5.boards]
part = 5
```

### Exemple n°3 : écrans d'affichage des appariements par ordre alphabétique

#### Déclaration du modèle

```
[template.alpha]
type = players
update = on
columns = 2
menu = alpha-1,alpha-2,alpha-3,alpha-4,alpha-5
menu_text = [%f - %l]
[template.alpha.boards]
tournament = principal
parts = 5
name = Joueur·euses %f à %l
```

#### Déclaration des écrans

```
[screen.alpha-1]
template = alpha
[screen.alpha-1.boards]
part = 1

[screen.alpha-2]
template = alpha
[screen.alpha-2.boards]
part = 2

[screen.alpha-3]
template = alpha
[screen.alpha-3.boards]
part = 3

[screen.alpha-4]
template = alpha
[screen.alpha-4.boards]
part = 4

[screen.alpha-5]
template = alpha
[screen.alpha-5.boards]
part = 5
```

## Les familles d'écran

Les familles servent à générer tout un ensemble d'écrans à partir d'un modèle, en se basant sur une plage de valeurs. Le bénéfice de l'utilisation des familles réside en la facilité d'ajouter et modifier des écrans basés sur un même modèle, de les personnaliser (nom et menus).

Une famille d'écrans se déclare à l'aide d'une rubrique `[family.<family_id>]`, où `family_id` sera l'identifiant du modèle. Dans la rubrique `[family.<family_id>]` doivent se trouver :
- le modèle sur lequel sont basés les écrans (option `template`) ;
- la plage de valeurs à partir de laquelle seront construits les écrans (option `range`) peuvent être des entiers ou des lettres.

> [!NOTE]
> L'identifiant d'une famille n'est pas forcément celui du modèle.

Les valeurs de la plage de l'option `range` sont utilisées à la création des écrans en remplacement de tous les points d'interrogation trouvés dans les options des modèles.

### Exemple n°1 : écrans de saisie d'un évènement avec plusieurs tournois

#### Déclaration du modèle

```
[template.saisie]
type = boards
update = on
menu = family
menu_text = Tournoi ?
[screen.saisie.boards]
Tournament = ?
name = %t
```

#### Déclaration de la famille d'écrans

```
[family.saisie]
template = saisie
range = A-E
```

Cette déclaration crée automatiquement les écrans saisie-A à saisie-E, chaque écran affichant les échiquiers de son tournoi.

### Exemple n°2 : écrans d'affichage des appariements par échiquier

#### Déclaration du modèle

```
[template.appariements]
type = boards
update = off
menu = family
menu_text = Éch. [%f à %l]
[template.appariements.boards]
tournament = principal
parts = 5
part = ?
name = Échiquiers %f à %l
```

#### Déclaration de la famille d'écrans

```
[family.appariements]
template = appariements
range = 1-5
```

Cette déclaration crée automatiquement les écrans appariement-1 à appariements-5, chaque écran affichant les échiquiers de sa partie.

### Exemple n°3 : écrans d'affichage des appariements par ordre alphabétique

#### Déclaration du modèle

```
[template.alpha]
type = players
update = on
columns = 2
menu = family
menu_text = [%f - %l]
[template.alpha.boards]
tournament = principal
parts = 5
part = ?
name = Joueur·euses %f à %l
```

#### Déclaration de la famille d'écrans

```
[family.alpha]
template = alpha
range = 1-5
```

Cette déclaration crée automatiquement les écrans alpha-1 à alpha-5, chaque écran affichant les joueur·euses de sa partie.


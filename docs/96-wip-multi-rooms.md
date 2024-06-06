**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Gestion d'un évènement sur plusieurs salles


## Gestion basique (un seul tournoi)

Lorsqu'il n'y a qu'une seule salle de jeu dans un événement, la salle de jeu peut être déclarée en utilisant la rubrique `[room]`, mais la déclaration n'est pas nécessaire, une salle étant créée par défaut.

```
[room]
name = Salle 301
```

Lorsque le tournoi est joué dans plusieurs salles de jeu, les salles doivent être distinguées les unes de autres par un identifiant unique. Par exemple, l'Open International d'Avoine comprend deux salles de jeu : l'espace culturel, et la salle des fêtes.

On déclare alors les salles de jeu non plus dans une unique rubrique `[room]`, mais dans plusieurs rubriques `[room.<room_id>]`, où `<room_id>` est l'identifiant que vous choisissez pour vos salles.
Lors de la déclaration, les échiquiers de la salle peuvent être spécifiés avec l'option `boards` par une liste d'intervalles de nombres séparés par des virgules :

```
[room.salle-a]
name = Salle A
# La table 101 est une table fixe dans la salle A
boards = 1-20, 41-60, 101

[room.salle-b]
name = Salle B
boards = 21-40, 61-80
```

### Exemple

```
[event]
name = Open d'Avoine 2023

[room.espace-culturel]
name = Espace Culturel
boards = -77, 201, 202, 203

[room.salle-fêtes]
name = Salle des Fêtes
boards = 78-, 204, 205
```

> [!NOTE]
> La définition de l'unique salle de jeu n'est pas nécessaire, Papi-web crée une salle par défaut.
> De même, lorsque vous ne déclarez qu'une salle à l'aide de la rubrique `[room]`, Papi-web considère que l'identifiant de cette salle est `default`, comme si vous aviez déclaré votre salle dans la rubrique `[room.default]`
> Chaque intervalle de nombre peut ne pas avoir de début explicite (considérés comme commançant à la table 1) ou de fin explicite (considéré comme la dernière table non-fixe), et peut contenir un unique nombre.
> Dans tous les cas, deux salles distinctes ne peuvent pas inclure le même échiquier

## Gestion avancée (plusieurs tournois)

> [!IMPORTANT]
> La syntaxe exacte n'est pas définie à ce jour, les deux possibilités suivantes sont envisageables.

### Première possibilité : sections de salle

#### Exemple de syntaxe

```
[tournament.principal]
name = Tournoi principal

[tournament.b]
name = Tournoi B

[room.gauche]
name = Salle de gauche

[room.gauche.principal]
# option `tournament` non nécessaire : l'identifiant de section de salle correspond
# à un tournoi
boards = -20, 101

[room.gauche.b]
# Idem que plus haut
boards = 11-, 100

[room.droite]
name = Salle de droite

[room.droite.a]
# Option `tournament` obligatoire ici : pas de tournoi `a`
tournament = principal
boards = 21-, 102

[room.droite.c]
# Option `tournament` obligatoire ici : pas de tournoi `c`
tournament = b
boards = -10 
```


### Deuxième possibilité : syntaxe d'intervalle summplémentaire

#### Exemple de syntaxe
```
[tournament.principal]
name = Tournoi Principal

[tournament.b]
name = Tournoi B

[room.gauche]
name = Salle de gauche
boards = principal:-20, principal:101, b:11-, b:100

[room.droite]
name = Salle de droite
boards = principal:21-, principal:102, b:-10
```

Voir également : [Guide de référence de la configuration des évènements](40-ref.md)

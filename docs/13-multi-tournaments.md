**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Gestion d'un évènement avec plusieurs tournois

Lorsqu'il n'y qu'un seul tournoi dans un évènement, le tournoi est déclaré en utilisant la rubrique `[tournament]`.

```
[tournament]
name = Le plus beau tournoi du monde
```

Lorsqu'un évènement regroupe plusieurs tournois, les tournois doivent être distingués les uns des autres par un identifiant unique. Par exemple pour un tournoi rapide de club, on gèrera souvent en parallèle un tournoi principal et un tournoi jeunes.

On déclare alors les tournois non plus dans une unique rubrique `[tournament]` mais dans plusieurs rubriques `[tournament.<id>]`, où `<id>` est l'identifiant que vous choisissez pour vos tournois.

## Exemple

```
[event]
name = Tournoi rapide du club

[tournament.principal]
name = Tournoi principal
ffe_id = 59999 

[tournament.jeunes]
name = Tournoi jeunes
ffe_id = 60000 
```

> [!NOTE]
> Pour information, lorsque vous ne déclarez qu'un seul tournoi à l'aide de la rubrique `[tournament]`, Papi-web considère que l'identifiant de ce tournoi est `default`, comme si vous aviez déclaré votre tournoi dans la rubrique `[tournament.default]`.
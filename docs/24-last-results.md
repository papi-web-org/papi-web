**[Retour au sommaire de la documentation](../README.md)**

# Affichage des résultats

> [!CAUTION]
> Cette page décrivant la configuration au format INI des écrans d'affichage des derniers résultats est obsolète et sera prochainement remplacée par un tutoriel.

Dans les évènements avec plusieurs tournois, il peut être utile de suivre l'intégralité des résultats sur un seul écran, c'est l'objet des écrans de résultats.

Tous les résultats saisis via les écrans de saisie sont automatiquement répertoriés et affichés en commençant par les plus récents sur les écrans de résultats.

Comme dit dans la partie [Gestion d'un petit tournoi amical](11-friendly.md), la simple déclaration d'un tournoi crée automatiquement plusieurs écrans, dont un écran de résultats. Pour personnaliser son ou ses écrans de résultats, il faut le ou les déclarer manuellement.

## Déclaration d'un écran de résultats (`type = results`)

On déclare un écran de résultats en créant une rubrique `[screen.<screen_id>]`, où `screen_id` est l'identifiant que vous aurez choisi pour votre écran. Vous pouvez par exemple déclarer un écran nommé `résultats` de la manière suivante :
```
[screen.résultats]
type = results
limit = 30
```

Le paramètre `limit` permet de limiter le nombre de résultats affichés (ici 30).

## Limitation des tournois dans les écrans de résultats

Dans le cas où un écran de résultats est affiché aux spectateurs, il peut être appréciable de scinder cet écran pour ne montrer que les résultats d'un ou plusieurs tournois. Pour un événement comprenant 3 tournois (`a`, `b` et `jeunes`), il est possible de définir deux écrans de résultats, un nommé `résultats-tc` (tournois `a` et `b`), et un autre nommé `résultats-j` (tournoi jeunes) de cette manière :
```
[screen.résultats-tc]
type = results
tournaments = a, b

[screen.résultats-j]
type = results
tournaments = j
```

> [!NOTE]
> - par défaut, les résultats de tous les tournois sont affichés sur les écrans de résultats ;
> - les résultats sont conservés au maximum une heure sur le serveur.

> [!NOTE]
> Les options de personnalisation des menus sont décrites sur la page [Configuration des menus des écrans](33-menus.md).

Voir également : [Guide de référence de la configuration des évènements](40-ref.md)


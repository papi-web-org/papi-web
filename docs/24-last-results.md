**[Retour au sommaire de la documentation](../README.md)**

# Affichage des résultats

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

> [!NOTE]
> - les résultats de tous les tournois sont affichés sur les écrans de résultats ;
> - les résultats sont conservés au maximum une heure sur le serveur.

> [!NOTE]
> Les options de personnalisation des menus sont décrites sur la page [Configuration des menus des écrans](34-menus.md).

Voir également : [Guide de référence de la configuration des évènements](40-ref.md)


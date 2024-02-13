**[Retour au sommaire de la documentation](../README.md)**

# Affichage des appariements par échiquier

Les écrans d'affichage des appariements par échiquier ne sont ni plus ni moins que des [écrans de saisie](21-update.md) sur lesquels la saisie est invalidée.

Leur déclaration est exactement la même sur tous les points, à l'exception de l'option `update` qui doit être positionnée à `off` (ou simplement omise car `off` est la valeur par défaut).

On utilisera donc par exemple simplement (avec un seul tournoi) :
```
[screen.appariements]
type = boards
```

> [!NOTE]
> L'option `[event] update_password` ne contrôle pas l'accès aux écrans d'affichage des appariements.
> Les options de personnalisation des menus sont décrites sur la page [Configuration des menus des écrans](34-menus.md).

Voir également : [Guide de référence de la configuration des évènements](40-ref.md)


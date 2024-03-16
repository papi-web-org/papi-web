**[Retour au sommaire de la documentation](../README.md)**

# Papi-web - Personnalisation du rendu des écrans (CSS)

Il est possible de personnaliser le rendu des écrans à l'aide de fichiers CSS (Cascading Style Sheets).

Les personnalisations doivent être déposées dans le répertoire `custom/`, au format CSS. Vous pouvez également déposer dans le répertoire `custom/` des images, d'autres fichiers CSS, ...

## Utilisation d'une personnalisation (`[event] css`)

On utilise une personnalisation en utilisation l'option `css` dans la rubrique `[event]`, par exemple :

```
[event] 
css = ffe/ffe.css
```

## Exemple (Ligue de Bretagne)

```
body {
	background-position: center center;
	background-image: url("BRE.png");
	background-repeat: no-repeat;
}
```

![Ligue de Bretagne](../custom/ligue/BRE/BRE.png)

## Modèles de personnalisation

Vous trouverez ci-dessous quelques personnalisations déjà existantes :

- [`custom/fide`](../custom/fide) (Fédération Internationale des Échecs)
- [`custom/ffe`](../custom/ffe) (Fédération Française des Échecs)
- [`custom/ligue/BRE`](../custom/ligue/BRE) (Ligue de Bretagne)
- [`custom/cdje/35`](../custom/cdje/35) (Comité Départemental d'Ille-et-Vilaine)
- [`custom/club/F35043`](../custom/club/F35043) (Échiquier Domloupéen)

Si vous souhaitez partager votre personnalisation dans de futures versions de Papi-Web, faites nous signe !

Voir également : [Guide de référence de la configuration des évènements](40-ref.md)


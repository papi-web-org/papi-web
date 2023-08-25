# Papi-web, pour les arbitres 2.0

Papi-web, programme de saisie des résultats dans Papi et de mise en ligne des résultats sur le site fédéral, a été développé à titre gracieux pour les arbitres et organisateurs de la Fédération Française des Échecs par Pascal AUBRY. Il est livré sans aucune garantie et peut être redistribué, sans aucune contrepartie financière.

## Papi-web, ça vient d'où ?

Papi-web est né de quelques observations simples :

- Pendant les tournois, les arbitres « à l'ancienne » (qui se reconnaitront :-) ) passent un temps non négligeable sur le clavier de leur ordinateur à entrer les résultats des joueur·euses, puis à les vérifier ; l'arbitrage des parties en souffre, c'est pourtant le coeur de métier des arbitres !
- La saisie des résultats par l'arbitre est souvent source d'erreurs, en simple saisie en cadence lente à cause des erreurs sur les feuilles de partie, et surtout en double saisie en cadence rapide quand les joueur·euses notent leur scores sur un papier et que l'arbitre les reporte ensuite dans la « boule Papi » ;
- Il faut attendre la fin des rondes pour en connaître les résultats, difficile de communiquer sur les aspects sportifs d'un évènement échiquéen dans ces conditions...
- Sur des opens rapides en faible cadence (typiquement 9 rondes en 12 minutes et 3 secondes par coups), les retards s'accumulent sur la journée à cause des temps de saisie, les pauses déjeuner sont raccourcies, les remises des prix ont lieu systématiquement en retard, ...

Papi-web est ainsi né en septembre 2013 pour la [7e édition de l'open rapide de Domloup](http://domloup.echecs35.fr/node/1561), et son utilisation avait été relayée dans le [BAF n°135](http://www.echecs.asso.fr/Arbitrage/Baf135.pdf) ([Bulletin des Arbitres fédéraux](http://www.echecs.asso.fr/Default.aspx?Cat=5)). Depuis cette date, le logiciel n'a cessé d'évoluer grâce aux contributions et sous l'impulsion des utilisateur·trices...

![Première utilisation de Papi-web dans une compétition homologuée en 2013](docs/images/saisie-2013.jpg)

En mai 2018, un débriefing avec Pierre LAPEYRE après un stage d'arbitrage à Domloup se conclut à une heure très avancée sur une conclusion simple : il faut absolument diffuser Papi-web pour permettre aux arbitres de se concentrer sur leur coeur de métier, et il faut pour cela le mettre en place sur une manifestation de masse. Après un test grandeur nature quelques semaines avant au festival international de Metz par Eric DELMOTTE, la décision est prise d'utiliser Papi-web au championnat de France et ce sont Pierre LAPEYRE et Eric DELMOTTE qui en font la promotion à Nîmes en août 2018 ([voir la vidéo](https://www.youtube.com/watch?v=u2arqnRH9SA)) !

## Papi-web, c'est quoi ?

C'est un programme qui permet :
- La saisie des résultats par les joueurs eux-mêmes, directement dans la « boule Papi » de l'arbitre ;
- La mise en ligne des résultats sur le site fédéral en temps réel.

![Workflow](docs/images/workflow.jpg)

## Papi-web, ça sert à quoi ?

Papi-web permet aux arbitres de se concentrer sur leur job, qui consiste essentiellement à arbitrer les parties d'échecs, en minimisant le temps passé sur l'ordinateur à entrer les résultats des joueur·euses, les contrôler, ...

Papi-web participe à l'animation des tournois grâce à l'affichage des résultats en temps-réel, qui est particulièrement apprécié des accompagnateur·trices dans les compétitions jeunes, et par le public en général pour les autres compétitions.

L'affichage permanent d'un timer permet également aux joueur·euses de se préparer dans les temps pour les rondes.

## Papi-web, comment ça marche ?

Une page web dans la salle de jeu présente aux joueur·euses les matches de la ronde en cours, ceux-ci sélectionnent leur table puis indiquent leur score, qui est enregistré directement dans la « boule Papi ». L'arbitre n'a plus qu'à gérer, dans le logiciel Papi :

- les appariements, comme il le fait habituellement ;
- les éventuelles erreurs de saisie, extrêmement rares lorsque la saisie est faite par les joueur·euses eux·elles-mêmes.

En parallèle, un programme en ligne de commande se charge de mettre en ligne sur le site fédéral les « boules Papi » dès qu'elles sont modifiées, en temps-réel.

## Papi-web, qui l'utilise ?

Le logiciel Papi-web peut être utilisé gratuitement et sans autorisation par tou·tes celles·ceux qui le considérent comme un Beerware lorsqu'ils croisent son auteur :-)

Vous n'en faites pas encore partie ? Lancez-vous !

# En savoir plus...

- Comment installer et mettre à jour Papi-web
- Comment utiliser Papi-web

# Comment être prévenu des nouvelles versions ?

Il suffit de s'abonner à la liste de diffusion papi-web-news@echecs35.fr (demande par mail à pascal.aubry@echecs35.fr).

# Nouveautés de la version 2

# ChangeLog

## Version 2.0 - Septembre 2023
- Livraison sous forme d'un exécutable autonome (ne nécessite plus l'installation de XAMPP)
- Configuration des évènements au format INI (plus simple que PHP)
- Amélioration de la page d'acceuil
- Ajout d'une page par évènement
- Ajout d'écrans d'affichage des appariements par ordre alphabétique
- Simplification de la configuration des écrans grâce aux modèles et aux familles d'écran

## Version 1.19 - 22 janvier 2023
- Correction d'un bug de protection des pages de saisie des résultats

## Version 1.18 - 4 février 2020
- Correction d'un bug d'affichage des derniers résultats
- Correction d'un bug de transmission sur le site fédéral

## Version 1.17 - 4 octobre 2019
- Correction d'un bug d'accès concurrent (saisie des résultats sur plusieurs écrans)
- Correction d'un bug d'affichage des joueurs avant appariement

## Version 1.16 - 31 août 2019
- Correction d'un bug d'affichage du chronomètre

## Version 1.15 - 31 août 2019
- Compatibilité avec Papi 3.3.6
- Support du système de Haley dégressif
- Support du « bye »
- Ajout du chronomètre
- Amélioration du rafraichissement des pages
- Rennomage de la propriété no-banner en no_banner

## Version 1.14 - 9 avril 2019
- Ajout des écrans d'affichage des résultats
- Ajout des écrans d'affichage des derniers résultats
- Ajout du rafraichissement automatique des écrans de saisie
- Amélioration des temps de réponse
- Simplification des URL des écrans
- Téléchargement systématique des fichiers avant affichage sur le site FFE

## Version 1.13 - 10 novembre 2018
- Affichage des numéros des échiquiers

## Version 1.12 - 30 octobre 2018
- Support des tournois à handicap

## Version 1.11 - 27 octobre 2018
- Support du Suisse Accéléré Degressif (SAD)
- Support de l'acélération de Haley

## Version 1.10 - 26 octobre 2018
- Possibilité de tester les codes d'accès au site FFE
- Possibilité de rendre les données visibles sur le site FFE
- Possibilité de télécharger les factures d'homologation depuis le site FFE
- Renommage du script upload.bat en ffe.bat

## Version 1.9 - 23 octobre 2018
- Correction de la mise en ligne sur le site fédéral

## Version 1.8 - 1er septembre 2018
- Amélioration des transitions entre les requêtes

## Version 1.7 - 31 août 2018
- Recherche automatique des mises à jour

## Version 1.6 - 30 août 2018
- Ecriture de la documentation
- Diffusion sous forme d'une archive
- Amélioration de l'affichage des participants avant les appariements
- Amélioration des styles CSS (normalisation)
- Obfuscation des sources PHP

## Version 1.5 - 3 août 2018
- Ajout des personnalisations CSS
- Amélioration de l'affichage (bandeau supérieur toujours visible)

## Version 1.4 - 28 juillet 2018
- Gestion de plusieurs écrans de saisie


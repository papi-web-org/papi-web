[Sommaire de la documentation](../README.md)

# Papi-web - configuration d'un tournoi amical

Même pour un petit tournoi amical au club, l'utilisation de Papi-web pour l'entrée des résultats permet de fluidifier le déroulement de la compétition.
On crée un fichier `amical.ini` dans le répertoire `events` pour déclarer l'évènement.
```
[event]
name = Tournoi amical 17 juin 2023

[tournament] 
name = Tournoi amical
filename = amical-20230617
```
La rubrique `[event]` est obligatoire et permet de déclarer le nom de l'évènement.

Le tournoi est nommé `Tournoi amical` et le fichier Papi du tournoi est `amical-20230617.papi`, stocké dans le répertoire par défaut `papi/` (pour le localiser à un autre endroit, on utilisera par exemple `path = c:\...\echecs\domloup\2023\tournois\amical`)

Lorsqu'aucun écran n'est déclaré, Papi-web ajoute automatiquement, pour chaque tournoi, les quatre écrans suivants :
- saisie des résultats
- affichage des appariements par échiquier
- affichage des appariements par ordre alphabétique
- affichage des derniers résultats

Démarrer le serveur Papi-Web présente la page d'accueil avec un lien vers la page de l'évènement, et la page de l'évènement présente un lien vers l'écran de saisie des résultats.

Il ne reste plus qu'à apparier la première ronde, demander aux joueur·euses de saisir leurs résultats, apparier les rondes suivantes, ...

